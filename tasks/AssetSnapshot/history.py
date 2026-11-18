from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from module.logger import logger


class SnapshotStore:
    """Keep completed baselines separate from scheduler configuration and diagnostics."""

    def __init__(self, root: str | Path, profile: str, serial: str, character: str,
                 mapping: Mapping[str, str], generation: int = 0):
        self.identity = {"config": profile, "serial": serial, "character": character}
        self.variables = set(mapping.values())
        digest = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()[:24]
        self.path = Path(root) / f"{digest}.json"
        from tasks.AssetSnapshot.repository import SnapshotRepository
        self.repository = SnapshotRepository(root, self.identity, self.variables, generation)

    def _valid(self, document: object) -> bool:
        if not isinstance(document, dict):
            return False
        snapshot = document.get("snapshot")
        if not isinstance(snapshot, dict):
            return False
        values = snapshot.get("values")
        from tasks.AssetSnapshot.repository import parse_time
        try:
            parse_time(snapshot.get('updatedAt', ''))
            parse_time(document.get('fullScanCompletedAt', ''))
        except (ValueError, TypeError, AttributeError):
            return False
        return (
            document.get("schemaVersion") == 1
            and document.get("identity") == self.identity
            and bool(document.get("fullScanCompletedAt"))
            and snapshot.get("status") == "ready"
            and bool(snapshot.get("updatedAt"))
            and isinstance(values, dict)
            and set(values) == self.variables
            and all(type(value) is int and value >= 0 for value in values.values())
        )

    def load(self) -> dict | None:
        current = self.repository.latest()
        if current is not None:
            if not self._valid(current):
                return None
            try:
                cached = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else None
                if (cached or {}).get('snapshotId') != current['snapshotId']:
                    self._export_latest()
            except (OSError, ValueError):
                try:
                    self._export_latest()
                except OSError as error:
                    logger.warning(f'AssetSnapshot compatibility export retry failed: {error}')
            return current
        self.repository.migrate(self._load_json() if self.repository.generation == 0 else None)
        return self.repository.latest()

    def _load_json(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning(f"AssetSnapshot history unreadable, use full scan: {self.path}")
            return None
        if not self._valid(document):
            logger.warning(f"AssetSnapshot history invalid, use full scan: {self.path}")
            return None
        return document

    def save(self, snapshot: dict, category: str, previous: dict | None) -> dict:
        if category not in {"composite", "recent"}:
            raise ValueError("unknown snapshot category")
        if category == "recent" and not self._valid(previous):
            raise ValueError("recent scan requires a completed full baseline")
        document = {
            "schemaVersion": 1,
            "identity": self.identity,
            "fullScanCompletedAt": snapshot.get("updatedAt") if category == "composite"
                else previous["fullScanCompletedAt"],
            "lastCategory": category,
            "snapshot": snapshot,
        }
        if not self._valid(document):
            raise ValueError("cannot persist incomplete asset snapshot")
        document = self.repository.append(document, previous)
        try:
            self._export_latest()
        except OSError as error:
            logger.warning(f"AssetSnapshot JSON export failed; committed history is safe: {error}")
        return document

    def _export_latest(self):
        # Serialize the projection with commits so an older writer cannot roll it back.
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM asset_snapshot WHERE identity_id=? ORDER BY id DESC LIMIT 1',
                             (self.repository.identity_id,)).fetchone()
            if row:
                self._export(self.repository.decode(row))

    def _export(self, document):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.stem, suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            Path(temp_name).unlink(missing_ok=True)
