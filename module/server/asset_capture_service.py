import asyncio
from multiprocessing import get_context

from module.config.utils import configured_device_id
from tasks.AssetSnapshot.capture import CaptureQueue, device_key, store_for, worker
from tasks.AssetSnapshot.repository import SnapshotRepository


class AssetCaptureService:
    def __init__(self, manager):
        self.manager = manager
        self.workers = {}
        self.task = None

    async def start(self):
        if self.task and not self.task.done():
            return
        repo = SnapshotRepository("config/asset_snapshot", {}, set())
        CaptureQueue(repo).reconcile()
        self.task = asyncio.create_task(self._pump())

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        for process in self.workers.values():
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
        CaptureQueue(SnapshotRepository("config/asset_snapshot", {}, set())).reconcile()

    def cancel(self, config_name):
        queue = CaptureQueue(store_for(self.manager.config_cache(config_name)).repository)
        with queue.repo.connect() as db:
            pids = {r[0] for r in db.execute("SELECT owner_pid FROM asset_capture_request WHERE config_name=? AND status='running'", (config_name,))}
        for process in self.workers.values():
            if process.pid in pids and process.is_alive():
                process.terminate()
                process.join(timeout=1)
        queue.interrupt(config_name)

    async def _pump(self):
        from module.logger import logger
        while True:
            try:
                for key, process in list(self.workers.items()):
                    if not process.is_alive():
                        process.join(timeout=0)
                        # An abnormal worker must not leave a permanent running state.
                        repo = SnapshotRepository("config/asset_snapshot", {}, set())
                        with repo.connect() as db:
                            rows = db.execute("SELECT id,run_id FROM asset_capture_request WHERE owner_pid=? AND status='running'", (process.pid,)).fetchall()
                            for row in rows:
                                saved = db.execute("SELECT id FROM asset_snapshot WHERE run_id=?", (row["run_id"],)).fetchone()
                                db.execute("UPDATE asset_capture_request SET status=?,snapshot_id=?,error_message=? WHERE id=?", (
                                    "succeeded" if saved else "interrupted", saved["id"] if saved else None,
                                    None if saved else "采集进程退出，请重试", row["id"]))
                        del self.workers[key]
                repo = SnapshotRepository("config/asset_snapshot", {}, set())
                with repo.connect() as db:
                    alive = {p.pid for p in self.workers.values() if p.is_alive()}
                    alive.update(s._process.pid for s in list(self.manager.script_process.values()) if s._process and s._process.is_alive())
                    for running in db.execute("SELECT id,run_id,owner_pid FROM asset_capture_request WHERE status='running'").fetchall():
                        if running['owner_pid'] not in alive:
                            saved = db.execute("SELECT id FROM asset_snapshot WHERE run_id=?", (running['run_id'],)).fetchone()
                            db.execute("UPDATE asset_capture_request SET status=?,snapshot_id=?,error_message=? WHERE id=?", (
                                'succeeded' if saved else 'interrupted', saved['id'] if saved else None,
                                None if saved else '采集进程已停止，请重试', running['id']))
                    pending = db.execute("SELECT DISTINCT config_name,device_key FROM asset_capture_request WHERE status='queued'").fetchall()
                for row in pending:
                    key = row["device_key"]
                    if key in self.workers:
                        continue
                    active = False
                    for name, script in list(self.manager.script_process.items()):
                        process = script._process
                        if process and process.is_alive():
                            config = self.manager.config_cache(name)
                            if device_key(configured_device_id(config)) == key:
                                active = True
                                break
                    if not active:
                        process = get_context("spawn").Process(target=worker, args=(row["config_name"],), daemon=True)
                        process.start()
                        self.workers[key] = process
            except asyncio.CancelledError:
                return
            except Exception as error:
                logger.exception(error)
            await asyncio.sleep(1)
