"""Durable one-shot requests consumed at a scheduler's safe boundary or by a worker."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from module.config.utils import configured_device_id
from tasks.AssetSnapshot.repository import utc_now


def device_key(serial):
    return str(serial).strip().lower().replace("localhost:", "127.0.0.1:")


def device_lock(serial, root="config/asset_snapshot"):
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(device_key(serial).encode()).hexdigest()[:24]
    return FileLock(str(path / f"device-{digest}.lock"))


def store_for(config, root="config/asset_snapshot"):
    from tasks.AssetSnapshot.assets import AssetSnapshotAssets
    from tasks.AssetSnapshot.history import SnapshotStore
    return SnapshotStore(root, config.config_name, configured_device_id(config),
                         str(config.restart.login_character_config.character), AssetSnapshotAssets.VARIABLE_MAPPING,
                         generation=config.asset_snapshot.asset_snapshot_config.history_generation)


class CaptureQueue:
    def __init__(self, repository):
        self.repo = repository

    @staticmethod
    def response(row):
        return {"requestId": row["id"], "status": row["status"], "snapshotId": row["snapshot_id"],
                "message": row["error_message"], "requestedAt": row["requested_at"]}

    def submit(self, key):
        with self.repo.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT r.* FROM asset_capture_request r JOIN asset_capture_key k ON k.request_id=r.id WHERE k.key=?", (key,)).fetchone()
            if row is None:
                row = db.execute("SELECT * FROM asset_capture_request WHERE idempotency_key=?", (key,)).fetchone()
            if row and row["identity_id"] != self.repo.identity_id:
                raise ValueError("此请求标识已用于其他身份")
            if not row:
                row = db.execute("SELECT * FROM asset_capture_request WHERE identity_id=? AND status IN ('queued','running')",
                                 (self.repo.identity_id,)).fetchone()
            if row:
                db.execute("INSERT OR IGNORE INTO asset_capture_key VALUES(?,?,?)", (key, self.repo.identity_id, row["id"]))
                return self.response(row)
            request_id = str(uuid4())
            db.execute("""INSERT INTO asset_capture_request
                (id,identity_id,config_name,device_key,idempotency_key,status,requested_at,run_id)
                VALUES(?,?,?,?,?,'queued',?,?)""", (request_id, self.repo.identity_id,
                self.repo.identity["config"], device_key(self.repo.identity["serial"]), key, utc_now(), str(uuid4())))
            db.execute("INSERT INTO asset_capture_key VALUES(?,?,?)", (key, self.repo.identity_id, request_id))
            return self.response(db.execute("SELECT * FROM asset_capture_request WHERE id=?", (request_id,)).fetchone())

    def get(self, request_id=None):
        with self.repo.connect() as db:
            sql = "SELECT * FROM asset_capture_request WHERE identity_id=?"
            args = [self.repo.identity_id]
            if request_id:
                sql += " AND id=?"
                args.append(request_id)
            row = db.execute(sql + " ORDER BY requested_at DESC,rowid DESC LIMIT 1", args).fetchone()
            return self.response(row) if row else None

    def pending(self, serial):
        with self.repo.connect() as db:
            return bool(db.execute("SELECT 1 FROM asset_capture_request WHERE device_key=? AND status='queued'",
                                   (device_key(serial),)).fetchone())

    def interrupt(self, config_name, message="采集被停止"):
        with self.repo.connect() as db:
            db.execute("UPDATE asset_capture_request SET status='succeeded',snapshot_id="
                       "(SELECT id FROM asset_snapshot WHERE run_id=asset_capture_request.run_id) "
                       "WHERE config_name=? AND status IN ('queued','running') AND EXISTS "
                       "(SELECT 1 FROM asset_snapshot WHERE run_id=asset_capture_request.run_id)", (config_name,))
            db.execute("UPDATE asset_capture_request SET status='interrupted',finished_at=?,error_message=? "
                       "WHERE config_name=? AND status IN ('queued','running')", (utc_now(), message, config_name))

    def reconcile(self):
        # Called once by the HTTP service on startup, before accepting new work.
        with self.repo.connect() as db:
            for row in db.execute("SELECT * FROM asset_capture_request WHERE status='running'").fetchall():
                saved = db.execute("SELECT id FROM asset_snapshot WHERE run_id=?", (row["run_id"],)).fetchone()
                db.execute("UPDATE asset_capture_request SET status=?,snapshot_id=?,finished_at=?,error_message=? WHERE id=?", (
                    "succeeded" if saved else "interrupted", saved["id"] if saved else None, utc_now(),
                    None if saved else "服务重启，采集已中断，请重试", row["id"]))

    def consume(self, serial):
        """Caller owns the device lock; execute one queued request without scheduler writes."""
        with self.repo.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM asset_capture_request WHERE device_key=? AND status='queued' ORDER BY rowid LIMIT 1",
                             (device_key(serial),)).fetchone()
            if not row:
                return False
            row = dict(row)
            db.execute("UPDATE asset_capture_request SET status='running',started_at=?,owner_pid=? WHERE id=?",
                       (utc_now(), os.getpid(), row["id"]))
        try:
            from module.config.config import Config
            from module.device.device import Device
            from module.image.rpc import get_image_client
            from module.ocr.rpc import get_ocr_client
            from tasks.AssetSnapshot.script_task import ScriptTask
            config = Config(row["config_name"])
            current = store_for(config, self.repo.root)
            if current.repository.identity_id != row["identity_id"]:
                raise ValueError("设备或角色设置已改变，请重新刷新资产")
            # The HTTP host manages RPC service lifetimes; child workers only connect.
            get_image_client(refresh=True)
            get_ocr_client(refresh=True)
            task = ScriptTask(config=config, device=Device(config))
            task.capture_run_id = row["run_id"]
            payload = task.execute_workflow()
            self.finish(row["id"], "succeeded", payload["snapshotId"])
        except Exception as error:
            from module.logger import logger
            logger.exception(error)
            self.finish(row["id"], "failed", message=str(error))
        return True

    def finish(self, request_id, status, snapshot_id=None, message=None):
        with self.repo.connect() as db:
            db.execute("UPDATE asset_capture_request SET status=?,snapshot_id=?,finished_at=?,error_message=? "
                       "WHERE id=? AND status='running'", (status, snapshot_id, utc_now(), message, request_id))


def consume_for(config):
    store = store_for(config)
    return CaptureQueue(store.repository).consume(configured_device_id(config))


def worker(config_name):
    from module.config.config import Config
    from module.logger import logger
    logger.set_file_logger(config_name, do_cleanup=False)
    config = Config(config_name)
    with device_lock(configured_device_id(config)):
        while consume_for(config):
            pass
