import json
import tempfile
import unittest
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch, Mock

from tasks.AssetSnapshot.capture import CaptureQueue, device_lock
from tasks.AssetSnapshot.history import SnapshotStore
from tasks.AssetSnapshot.repository import StaleBaselineError
from tasks.AssetSnapshot.statistics import history, latest_payload

MAPPING = {'金币': 'gold', '符咒': 'mystic_talisman'}


def payload(at, value, source='observed', precision='exact', run_id=None):
    return {'status': 'ready', 'updatedAt': at, 'runId': run_id or at,
            'values': {'gold': value, 'mystic_talisman': 0},
            'assets': {'gold': {'quantity': value, 'source': source, 'precision': precision,
                                'observedAt': at if source == 'observed' else None}}}


class AssetChangesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(self.temp.name, 'test', '127.0.0.1:5555', '角色', MAPPING)

    def save(self, at, value, **kwargs):
        previous = self.store.load()
        return self.store.save(payload(at, value, **kwargs), 'recent' if previous else 'composite', previous)

    def test_first_positive_negative_and_zero(self):
        for day, value, delta in [(26, 100, None), (27, 130, 30), (28, 120, -10), (29, 120, 0)]:
            self.save(f'2026-10-{day}T20:00:00+08:00', value)
            result = latest_payload(self.store.repository.documents(), 'test')
            self.assertEqual(result['assets']['gold']['change']['delta'], delta)
        self.assertEqual(len(self.store.repository.documents()), 4)

    def test_legacy_migration_is_idempotent_and_not_a_comparison(self):
        doc = {'schemaVersion': 1, 'identity': self.store.identity,
               'fullScanCompletedAt': '2026-10-26T20:00:00', 'lastCategory': 'composite',
               'snapshot': {'status': 'ready', 'updatedAt': '2026-10-26T20:00:00', 'values': {'gold': 100, 'mystic_talisman': 0}}}
        self.store.path.write_text(json.dumps(doc), encoding='utf-8')
        self.assertEqual(self.store.load()['origin'], 'legacy')
        self.store.load()
        self.save('2026-10-27T20:00:00+08:00', 110)
        self.assertEqual(len(self.store.repository.documents()), 2)
        self.assertIsNone(latest_payload(self.store.repository.documents(), 'test')['assets']['gold']['change']['delta'])

    def test_unobserved_and_approximate(self):
        self.save('2026-10-26T20:00:00+08:00', 100)
        for day, source in [(27, 'carried'), (28, 'assumed_zero'), (29, 'unsupported')]:
            self.save(f'2026-10-{day}T20:00:00+08:00', 0, source=source)
            result = latest_payload(self.store.repository.documents(), 'test')
            self.assertIsNone(result['assets']['gold']['change']['delta'])
        self.save('2026-10-30T20:00:00+08:00', 200)
        self.save('2026-10-31T20:00:00+08:00', 100, precision='display_quantized')
        self.assertTrue(latest_payload(self.store.repository.documents(), 'test')['assets']['gold']['change']['approximate'])

    def test_seven_days_has_extra_baseline_and_gaps_are_not_zero(self):
        for at, value in [('2026-10-26', 100), ('2026-10-27', 120), ('2026-10-29', 90), ('2026-11-02', 130)]:
            self.save(at + 'T20:00:00+08:00', value)
        result = history(self.store.repository.documents(), 'gold', '2026-11-02')
        self.assertEqual(result['summary']['netChange'], 30)
        self.assertEqual(len(result['daily']), 7)
        self.assertEqual(result['daily'][0]['delta'], 20)
        self.assertIsNone(result['daily'][1]['closeValue'])
        self.assertIsNone(result['daily'][2]['delta'])
        self.assertTrue(result['summary']['hasGaps'])
        self.assertEqual(result['summary']['observedDayCount'], 3)

    def test_partial_and_no_today_never_claim_complete_week(self):
        self.save('2026-10-28T20:00:00+08:00', 10)
        self.save('2026-10-29T20:00:00+08:00', 20)
        result = history(self.store.repository.documents(), 'gold', '2026-11-02')
        self.assertIsNone(result['summary']['netChange'])
        self.assertEqual(result['summary']['partialChange']['delta'], 10)

    def test_intraday_last_valid_observation_and_midnight_timezone(self):
        self.save('2026-10-31T15:59:00Z', 10)
        self.save('2026-10-31T16:01:00Z', 20)
        self.save('2026-11-01T10:00:00Z', 30)
        self.save('2026-11-01T11:00:00Z', 30, source='carried')
        result = history(self.store.repository.documents(), 'gold', '2026-11-01')
        self.assertEqual(result['daily'][-1]['closeValue'], 30)
        self.assertEqual(result['daily'][-1]['delta'], 20)
        self.assertEqual(len(result['records']), 4)
        self.assertEqual([row['quantity'] for row in result['records']], [10, 20, 30, 30])
        self.assertEqual(result['records'][-1]['source'], 'carried')
        self.assertIsNone(result['records'][-1]['delta'])

    def test_all_queries_are_preserved_including_same_day_and_unchanged_values(self):
        self.save('2026-10-26T20:00:00+08:00', 100)
        first = self.save('2026-11-02T09:00:00+08:00', 110)
        second = self.save('2026-11-02T12:00:00+08:00', 110)
        third = self.save('2026-11-02T12:00:00+08:00', 110, run_id='another-query-same-second')
        result = history(self.store.repository.documents(), 'gold', '2026-11-02')
        self.assertEqual(result['summary']['recordCount'], 3)
        self.assertEqual([row['snapshotId'] for row in result['records']], [first['snapshotId'], second['snapshotId'], third['snapshotId']])
        self.assertEqual([row['quantity'] for row in result['records']], [110, 110, 110])
        self.assertEqual([row['delta'] for row in result['records']], [10, 0, 0])
        limited = history(self.store.repository.documents(second['snapshotId']), 'gold', '2026-11-02')
        self.assertEqual(len(limited['records']), 2)

    def test_query_records_use_capture_time_window_and_keep_unobserved_queries(self):
        self.save('2026-10-26T23:59:59+08:00', 100)
        self.save('2026-10-27T00:00:00+08:00', 100, source='carried')
        self.save('2026-11-02T23:59:59+08:00', 120)
        self.save('2026-11-03T00:00:00+08:00', 130)
        result = history(self.store.repository.documents(), 'gold', '2026-11-02')
        self.assertEqual(len(result['records']), 2)
        self.assertFalse(result['records'][0]['observed'])
        self.assertEqual(result['records'][0]['quantity'], 100)
        self.assertEqual(result['records'][-1]['quantity'], 120)

    def test_stale_baseline_and_clock_regression_do_not_write(self):
        first = self.save('2026-10-26T20:00:00+08:00', 100)
        self.save('2026-10-27T20:00:00+08:00', 110)
        with self.assertRaises(StaleBaselineError):
            self.store.save(payload('2026-10-28T20:00:00+08:00', 120), 'recent', first)
        with self.assertRaises(ValueError):
            self.save('2026-10-25T20:00:00+08:00', 100)
        self.assertEqual(len(self.store.repository.documents()), 2)

    def test_run_retry_and_json_export_failure_keep_commit(self):
        first = self.save('2026-10-26T20:00:00+08:00', 100, run_id='once')
        with patch.object(self.store, '_export', side_effect=OSError('read only')):
            saved = self.store.save(payload('2026-10-26T20:00:00+08:00', 100, run_id='once'), 'composite', None)
        self.assertEqual(saved['snapshotId'], first['snapshotId'])
        self.assertEqual(len(self.store.repository.documents()), 1)
        with patch.object(self.store, '_export', side_effect=OSError('read only')):
            second = self.store.save(payload('2026-10-27T20:00:00+08:00', 110), 'recent', first)
        self.store.load()
        self.assertEqual(json.loads(self.store.path.read_text(encoding='utf-8'))['snapshotId'], second['snapshotId'])

    def test_identity_generation_and_as_of(self):
        first = self.save('2026-10-26T20:00:00+08:00', 100)
        self.save('2026-10-27T20:00:00+08:00', 110)
        self.assertEqual(len(self.store.repository.documents(first['snapshotId'])), 1)
        other = SnapshotStore(self.temp.name, 'other', '127.0.0.1:5555', '角色', MAPPING)
        self.assertIsNone(other.load())
        with self.assertRaises(KeyError):
            other.repository.documents(first['snapshotId'])
        reset = SnapshotStore(self.temp.name, 'test', '127.0.0.1:5555', '角色', MAPPING, generation=1)
        self.assertIsNone(reset.load())

    def test_capture_concurrent_submits_share_one_active_job(self):
        queue = CaptureQueue(self.store.repository)
        with ThreadPoolExecutor(4) as pool:
            requests = list(pool.map(lambda i: queue.submit(f'test-key-{i}'), range(4)))
        self.assertEqual(len({r['requestId'] for r in requests}), 1)
        queue.interrupt('test')
        self.assertEqual(queue.get()['status'], 'interrupted')
        self.assertEqual(queue.submit('test-key-3')['requestId'], requests[0]['requestId'])
        again = queue.submit('new-key-after-stop')
        self.assertNotEqual(again['requestId'], requests[0]['requestId'])

    def test_worker_failure_and_restart_reconcile(self):
        queue = CaptureQueue(self.store.repository)
        job = queue.submit('test-request')
        with self.store.repository.connect() as db:
            db.execute("UPDATE asset_capture_request SET status='running' WHERE id=?", (job['requestId'],))
        queue.reconcile()
        self.assertEqual(queue.get()['status'], 'interrupted')

    def test_capture_executes_workflow_once_and_binds_committed_snapshot(self):
        queue = CaptureQueue(self.store.repository)
        job = queue.submit('workflow-once')
        original = {'enable': False, 'next_run': 'tomorrow'}
        config = SimpleNamespace(scheduler=original.copy())
        store = self.store
        class FakeTask:
            def __init__(self, config, device):
                self.capture_run_id = None
            def execute_workflow(self):
                saved = store.save(payload('2026-11-02T12:00:00Z', 120, run_id=self.capture_run_id), 'composite', None)
                return {'snapshotId': saved['snapshotId']}
        with patch('module.config.config.Config', return_value=config), \
             patch('module.device.device.Device', return_value=object()), \
             patch('module.image.rpc.get_image_client'), patch('module.ocr.rpc.get_ocr_client'), \
             patch('tasks.AssetSnapshot.capture.store_for', return_value=store), \
             patch('tasks.AssetSnapshot.script_task.ScriptTask', FakeTask):
            self.assertTrue(queue.consume('127.0.0.1:5555'))
            self.assertFalse(queue.consume('127.0.0.1:5555'))
        result = queue.get(job['requestId'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['snapshotId'], self.store.load()['snapshotId'])
        self.assertEqual(config.scheduler, original)

    def test_interrupted_request_cannot_commit_late(self):
        queue = CaptureQueue(self.store.repository)
        job = queue.submit('stop-before-save')
        with self.store.repository.connect() as db:
            run_id = db.execute('SELECT run_id FROM asset_capture_request WHERE id=?', (job['requestId'],)).fetchone()[0]
        queue.interrupt('test')
        with self.assertRaises(ValueError):
            self.save('2026-11-02T12:00:00Z', 10, run_id=run_id)
        self.assertIsNone(self.store.load())

    def test_device_mutex_blocks_another_worker(self):
        from filelock import Timeout
        with device_lock('localhost:5555', self.temp.name):
            with self.assertRaises(Timeout):
                device_lock('127.0.0.1:5555', self.temp.name).acquire(timeout=0)

    def test_normal_scheduler_idle_closes_game_only_beyond_configured_threshold(self):
        from datetime import datetime, time, timedelta
        from module.script.runtime_controller import ScriptRuntimeController, ScriptRuntimeDecision
        optimization = SimpleNamespace(when_task_queue_empty='close_game', close_game_limit_time=time(minute=30))
        owner = SimpleNamespace(config=SimpleNamespace(script=SimpleNamespace(optimization=optimization)),
                                device=Mock(), wait_until=Mock(return_value=True), _emulator_down=False)
        runtime = ScriptRuntimeController(owner)
        runtime._prepare_idle_close_game = Mock(return_value=ScriptRuntimeDecision.READY)
        runtime._prepare_idle_keep_game_running = Mock(return_value=ScriptRuntimeDecision.READY)
        self.assertEqual(runtime.handle_wait_during_idle(datetime.now() + timedelta(hours=1)), ScriptRuntimeDecision.READY)
        runtime._prepare_idle_close_game.assert_called_once()
        runtime._prepare_idle_keep_game_running.assert_not_called()
        runtime._prepare_idle_close_game.reset_mock()
        runtime.handle_wait_during_idle(datetime.now() + timedelta(minutes=5))
        runtime._prepare_idle_close_game.assert_not_called()
        runtime._prepare_idle_keep_game_running.assert_called_once()

    def test_service_stopped_profile_launches_worker_and_running_profile_queues(self):
        import asyncio
        from module.server.asset_capture_service import AssetCaptureService
        queue = CaptureQueue(self.store.repository)
        queue.submit('pump-worker-request')
        process = Mock()
        process.is_alive.return_value = True
        process.pid = 123
        config = SimpleNamespace(script=SimpleNamespace(device=SimpleNamespace(serial='127.0.0.1:5555')))
        for active in (False, True):
            manager = SimpleNamespace(script_process={'test': SimpleNamespace(_process=process if active else None)},
                                      config_cache=lambda _: config)
            service = AssetCaptureService(manager)
            context = Mock()
            async def end_iteration(_):
                raise asyncio.CancelledError
            with patch('module.server.asset_capture_service.SnapshotRepository', return_value=self.store.repository), \
                 patch('module.server.asset_capture_service.get_context', return_value=context), \
                 patch('module.server.asset_capture_service.asyncio.sleep', side_effect=end_iteration):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(service._pump())
            if active:
                context.Process.assert_not_called()
                self.assertEqual(queue.get()['status'], 'queued')
            else:
                context.Process.return_value.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
