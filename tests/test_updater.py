import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from module.server import updater


class UpdaterTest(unittest.TestCase):
    def test_pull_streams_both_outputs_and_reports_exit_code(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.stdout = io.StringIO('Receiving objects: 50%\n中文输出\n')
        process.wait.return_value = 0
        target = SimpleNamespace(git='git', Branch='mine', root_filepath='repo')
        logs = []
        process.wait.side_effect = lambda: self.assertIn('中文输出', logs) or 0
        with patch.object(updater.subprocess, 'Popen', return_value=process) as popen:
            self.assertTrue(updater.Updater.execute_pull(target, logs.append))
        self.assertEqual(popen.call_args.kwargs['stderr'], updater.subprocess.STDOUT)
        self.assertFalse(popen.call_args.kwargs.get('shell', False))
        self.assertEqual(popen.call_args.kwargs['env']['GIT_TERMINAL_PROMPT'], '0')
        self.assertIn('中文输出', logs)

        process.stdout = io.StringIO('error: local changes would be overwritten\n')
        process.wait.side_effect = None
        process.wait.return_value = 1
        with patch.object(updater.subprocess, 'Popen', return_value=process):
            self.assertFalse(updater.Updater.execute_pull(target, logs.append))
        self.assertIn('error: local changes would be overwritten', logs)
        self.assertIn('退出码 1', logs[-1])

    def test_pull_timeout_is_reported_as_failure(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.poll.return_value = None
        process.stdout = io.StringIO('')
        process.wait.return_value = -9
        target = SimpleNamespace(git='git', Branch='mine', root_filepath='repo')
        logs = []
        with patch.object(updater.subprocess, 'Popen', return_value=process), \
                patch.object(updater.subprocess, 'run'), \
                patch.object(updater.os, 'killpg', create=True), \
                patch.object(updater.threading, 'Timer') as timer:
            timer.side_effect = lambda seconds, callback: SimpleNamespace(
                start=callback, cancel=lambda: None)
            self.assertFalse(updater.Updater.execute_pull(target, logs.append))
        self.assertIn('更新超时', logs[-1])

    def test_background_job_keeps_live_logs_and_deduplicates_starts(self):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        job = updater.UpdateJob()

        def pull(on_log):
            on_log('Receiving objects: 50%')
            entered.set()
            release.wait(3)
            on_log('done')
            return True

        real_run = job._run

        def run():
            try:
                real_run()
            finally:
                finished.set()

        with patch.object(updater, 'Updater') as factory, patch.object(job, '_run', run):
            factory.return_value.execute_pull.side_effect = pull
            first = job.start()
            try:
                self.assertTrue(entered.wait(2))
                second = job.start()
                self.assertEqual(first['id'], second['id'])
                self.assertEqual(second['status'], 'running')
                self.assertIn('Receiving objects: 50%', second['logs'])
                self.assertEqual(factory.call_count, 1)
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
        final = job.snapshot()
        self.assertEqual(final['status'], 'succeeded')
        self.assertIn('done', final['logs'])
        final['logs'].clear()
        self.assertIn('done', job.snapshot()['logs'])

    def test_job_failure_exception_and_retry_have_distinct_results(self):
        job = updater.UpdateJob()
        with patch.object(updater.threading, 'Thread'), \
                patch.object(updater.logger, 'exception'), \
                patch.object(updater, 'Updater') as factory:
            factory.return_value.execute_pull.return_value = False
            first = job.start()
            job._run()
            self.assertEqual(job.snapshot()['status'], 'failed')
            self.assertIsNotNone(job.snapshot()['error'])
            factory.return_value.execute_pull.side_effect = OSError('git missing')
            second = job.start()
            job._run()
            self.assertNotEqual(first['id'], second['id'])
            self.assertEqual(job.snapshot()['error'], 'git missing')
            self.assertEqual(job.snapshot()['status'], 'failed')
            factory.return_value.execute_pull.side_effect = None
            factory.return_value.execute_pull.return_value = True
            job.start()
            job._run()
            self.assertIsNone(job.snapshot()['error'])
            self.assertNotIn('更新失败：git missing', job.snapshot()['logs'])
            self.assertEqual(job.snapshot()['status'], 'succeeded')

    def test_failed_revision_check_is_not_reported_as_up_to_date(self):
        target = MagicMock()
        target.Branch = 'mine'
        target.fetch_remote.return_value = True
        target.revision_distance.return_value = None
        result = updater.Updater.get_update_info(target)
        self.assertFalse(result['checked'])
        self.assertFalse(result['is_update'])

    def test_log_buffer_is_bounded(self):
        job = updater.UpdateJob()
        for index in range(1100):
            job._append(f'{index}: ' + 'x' * 3000)
        logs = job.snapshot()['logs']
        self.assertEqual(len(logs), 1000)
        self.assertTrue(logs[0].startswith('100: '))
        self.assertTrue(all(len(line) <= 2000 for line in logs))


if __name__ == '__main__':
    unittest.main()
