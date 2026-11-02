"""Transactional history shared by the scheduler, one-shot worker and HTTP readers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

STATISTICS_TZ = timezone(timedelta(hours=8))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=STATISTICS_TZ) if result.tzinfo is None else result


class StaleBaselineError(ValueError):
    pass


class SnapshotRepository:
    def __init__(self, root, identity, variables, generation=0):
        self.root = Path(root)
        self.identity = identity
        self.variables = set(variables)
        self.generation = generation
        self.identity_id = hashlib.sha256(json.dumps(
            {**identity, "generation": generation, "catalog": sorted(self.variables)}, sort_keys=True).encode()).hexdigest()[:24]
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "history.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS asset_identity (
                    id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, generation INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS asset_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity_id TEXT NOT NULL REFERENCES asset_identity(id),
                    run_id TEXT NOT NULL UNIQUE, captured_at TEXT NOT NULL,
                    document_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS snapshot_identity ON asset_snapshot(identity_id,id);
                CREATE INDEX IF NOT EXISTS snapshot_time ON asset_snapshot(identity_id,captured_at);
                CREATE TABLE IF NOT EXISTS asset_capture_request (
                    id TEXT PRIMARY KEY, identity_id TEXT NOT NULL,
                    config_name TEXT NOT NULL, device_key TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
                    requested_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    owner_pid INTEGER, run_id TEXT NOT NULL, snapshot_id INTEGER,
                    error_message TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS capture_active_identity
                    ON asset_capture_request(identity_id) WHERE status IN ('queued','running');
                CREATE TABLE IF NOT EXISTS asset_capture_key (
                    key TEXT PRIMARY KEY, identity_id TEXT NOT NULL,
                    request_id TEXT NOT NULL REFERENCES asset_capture_request(id));
                CREATE TABLE IF NOT EXISTS schema_migration(version INTEGER PRIMARY KEY, applied_at TEXT);
                INSERT OR IGNORE INTO schema_migration VALUES(1, CURRENT_TIMESTAMP);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        doc = json.loads(row["document_json"])
        doc["snapshotId"] = row["id"]
        return doc

    def migrate(self, document):
        if document is None:
            return
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM asset_snapshot WHERE identity_id=?", (self.identity_id,)).fetchone():
                return
            doc = json.loads(json.dumps(document))
            doc["origin"] = "legacy"
            doc["timeAssumed"] = datetime.fromisoformat(doc["snapshot"]["updatedAt"].replace('Z', '+00:00')).tzinfo is None
            doc["snapshot"]["assets"] = {key: {
                "source": "legacy_unknown", "precision": "unknown", "observedAt": None,
                "quantity": value, "readStatus": "legacy_unknown",
            } for key, value in doc["snapshot"]["values"].items()}
            self._insert(db, doc, "legacy-" + self.identity_id)

    def _insert(self, db, document, run_id):
        db.execute("INSERT OR IGNORE INTO asset_identity VALUES(?,?,?)", (
            self.identity_id, json.dumps(self.identity, sort_keys=True), self.generation))
        captured = parse_time(document["snapshot"]["updatedAt"]).astimezone(timezone.utc).isoformat()
        cursor = db.execute("INSERT INTO asset_snapshot(identity_id,run_id,captured_at,document_json) VALUES(?,?,?,?)", (
            self.identity_id, run_id, captured, json.dumps(document, ensure_ascii=False)))
        return cursor.lastrowid

    def latest(self):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM asset_snapshot WHERE identity_id=? ORDER BY id DESC LIMIT 1",
                                          (self.identity_id,)).fetchone())

    def append(self, document, previous):
        run_id = document["snapshot"].get("runId") or str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM asset_snapshot WHERE run_id=? AND identity_id=?",
                                  (run_id, self.identity_id)).fetchone()
            if existing:
                return self.decode(existing)
            request = db.execute("SELECT status FROM asset_capture_request WHERE run_id=?", (run_id,)).fetchone()
            if request and request["status"] != "running":
                raise ValueError("采集请求已被停止，保留上次成功快照")
            current = self.decode(db.execute("SELECT * FROM asset_snapshot WHERE identity_id=? ORDER BY id DESC LIMIT 1",
                                             (self.identity_id,)).fetchone())
            if (current or {}).get("snapshotId") != (previous or {}).get("snapshotId"):
                raise StaleBaselineError("资产基准已被其他采集更新，请重新采集")
            if current and parse_time(document["snapshot"]["updatedAt"]) < parse_time(current["snapshot"]["updatedAt"]):
                raise ValueError("采集时间早于上一份快照，请检查系统时间")
            result = json.loads(json.dumps(document))
            result["origin"] = "capture"
            result["completedAt"] = utc_now()
            result["snapshotId"] = self._insert(db, result, run_id)
            return result

    def documents(self, as_of=None, since=None, include_latest=False):
        with self.connect() as db:
            db.execute("BEGIN")
            query = "SELECT * FROM asset_snapshot WHERE identity_id=?"
            args = [self.identity_id]
            if as_of is not None:
                if not db.execute("SELECT 1 FROM asset_snapshot WHERE id=? AND identity_id=?", (as_of, self.identity_id)).fetchone():
                    raise KeyError("快照不存在或不属于当前身份")
                query += " AND id<=?"
                args.append(as_of)
            if since is not None:
                query += " AND (captured_at>=?"
                args.append(since.astimezone(timezone.utc).isoformat())
                if include_latest:
                    query += " OR id IN (SELECT id FROM asset_snapshot WHERE identity_id=? ORDER BY id DESC LIMIT 2)"
                    args.append(self.identity_id)
                query += ")"
            return [self.decode(row) for row in db.execute(query + " ORDER BY id", args)]
