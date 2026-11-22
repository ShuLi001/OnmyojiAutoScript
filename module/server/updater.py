import datetime
import os
import signal
import subprocess
import threading
from collections import deque
from typing import Tuple
from uuid import uuid4

from deploy.git import GitManager
from deploy.pip import PipManager
from deploy.utils import DEPLOY_CONFIG
from module.logger import logger
from module.server.config import DeployConfig


DEFAULT_GIT_TIMEOUT = 5
DEFAULT_FETCH_TIMEOUT = 15
FETCH_RETRY = 2
DEFAULT_PULL_TIMEOUT = 300
update_lock = threading.Lock()


class Updater(DeployConfig, GitManager, PipManager):
    def __init__(self, file=DEPLOY_CONFIG):
        super().__init__(file=file)
        self.state = 0

    @property
    def delay(self):
        self.read()
        return int(self.CheckUpdateInterval) * 60

    @property
    def schedule_time(self):
        self.read()
        t = self.AutoRestartTime
        if t is not None:
            return datetime.time.fromisoformat(t)
        else:
            return None

    def execute_command(self, command, timeout=DEFAULT_GIT_TIMEOUT) -> subprocess.CompletedProcess | None:
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
                shell=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"Git command timeout after {timeout}s: {command}")
            return None
        except OSError as e:
            logger.warning(f"Git command failed: {command}, error: {e}")
            return None

    def execute_output(self, command, timeout=DEFAULT_GIT_TIMEOUT) -> str:
        result = self.execute_command(command, timeout=timeout)
        if result is None:
            return ""
        if result.returncode:
            logger.warning(f"Git command failed: {command}, stderr: {result.stderr.strip()}")
            return ""
        return result.stdout

    def get_commit(self, revision="", n=1, short_sha1=False) -> Tuple:
        """
        Return:
            (sha1, author, isotime, message,)
        """
        ph = "h" if short_sha1 else "H"

        log = self.execute_output(
            f'"{self.git}" --no-pager log {revision} --pretty=format:"%{ph}---%an---%ad---%s" --date=iso -{n}'
        )

        if not log:
            return None, None, None, None

        logs = log.split("\n")
        logs = list(map(lambda log: tuple(log.split("---")), logs))

        if n == 1:
            return logs[0]
        else:
            return logs

    def current_branch(self) -> str:
        return self.Branch

    def current_commit(self) -> str:
        return self.get_commit()

    def latest_commit(self) -> str:
        source = "origin"
        return self.get_commit(f"{source}/{self.Branch}")

    def fetch_remote(self) -> bool:
        source = "origin"
        for _ in range(FETCH_RETRY):
            result = self.execute_command(
                f'"{self.git}" fetch {source} {self.Branch}',
                timeout=DEFAULT_FETCH_TIMEOUT,
            )
            if result is not None and result.returncode == 0:
                return True
            if result is not None:
                logger.warning(f"Git fetch failed: {result.stderr.strip()}")

        logger.warning("Git fetch failed")
        return False

    def revision_distance(self, left: str, right: str) -> tuple[int, int] | None:
        log = self.execute_output(
            f'"{self.git}" rev-list --left-right --count {left}...{right}'
        )
        if not log:
            return None

        try:
            ahead, behind = log.split()
            return int(ahead), int(behind)
        except ValueError:
            logger.warning(f"Unexpected git rev-list output: {log.strip()}")
            return None

    def get_update_info(self) -> dict:
        is_update = False
        source = "origin"
        remote_revision = f"{source}/{self.Branch}"

        checked = self.fetch_remote()
        if checked:
            distance = self.revision_distance("HEAD", remote_revision)
            if distance is None:
                checked = False
            else:
                ahead, behind = distance
                is_update = not ahead and bool(behind)
                if ahead:
                    logger.info("Local branch has commits not in upstream, skip update")
                logger.info("New update available" if is_update else "No update")

        commits = self.get_commit(remote_revision, n=15)
        latest_commit = commits[0] if commits and isinstance(commits, list) else commits
        return {
            'checked': checked,
            'is_update': is_update,
            'branch': self.current_branch(),
            'current_commit': self.current_commit(),
            'latest_commit': latest_commit,
            'commit': commits,
        }

    def execute_pull(self, on_log=None) -> bool:
        def emit(message):
            logger.info(message)
            if on_log is not None:
                on_log(message)

        emit(f'开始更新 OAS，分支：{self.Branch}')
        env = os.environ.copy()
        env['GIT_TERMINAL_PROMPT'] = '0'
        env['GCM_INTERACTIVE'] = 'Never'
        # Capture both streams, including Git progress normally written to stderr.
        with subprocess.Popen(
            [self.git, 'pull', '--progress', 'origin', self.Branch, '--no-rebase'],
            cwd=self.root_filepath, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt',
        ) as process:
            timed_out = threading.Event()

            def kill_on_timeout():
                if process.poll() is not None:
                    return
                timed_out.set()
                if os.name == 'nt':
                    subprocess.run(
                        ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            timer = threading.Timer(DEFAULT_PULL_TIMEOUT, kill_on_timeout)
            timer.daemon = True
            timer.start()
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        emit(line)
                code = process.wait()
            finally:
                timer.cancel()
            if timed_out.is_set():
                emit(f'更新超时（{DEFAULT_PULL_TIMEOUT} 秒），请检查网络后重试。')
                return False
            if code != 0:
                emit(f'Git 更新失败（退出码 {code}），请查看上方日志。')
                return False
        emit('OAS 代码更新完成。请停止脚本并重启 OAS 服务，使新代码生效。')
        return True


class UpdateJob:
    """One server-owned update; clients may disconnect and resume observing it."""

    def __init__(self):
        self._lock = threading.RLock()
        self._id = None
        self._status = 'idle'
        self._logs = deque(maxlen=1000)
        self._error = None

    def snapshot(self):
        with self._lock:
            return {
                'id': self._id, 'status': self._status,
                'logs': list(self._logs), 'error': self._error,
            }

    def _append(self, message):
        with self._lock:
            self._logs.append(str(message)[:2000])

    def start(self):
        with self._lock:
            if self._status == 'running':
                return self.snapshot()
            self._id = uuid4().hex
            self._status = 'running'
            self._error = None
            self._logs.clear()
            self._append('更新任务已创建，正在等待仓库就绪…')
            threading.Thread(target=self._run, name='oas-update', daemon=True).start()
            return self.snapshot()

    def _run(self):
        try:
            with update_lock:
                success = Updater().execute_pull(on_log=self._append)
            with self._lock:
                self._status = 'succeeded' if success else 'failed'
                if not success:
                    self._error = self._logs[-1] if self._logs else 'Git 更新失败'
        except Exception as exc:
            logger.exception('OAS update failed')
            with self._lock:
                self._error = str(exc)
                self._append(f'更新失败：{exc}')
                self._status = 'failed'


update_job = UpdateJob()


if __name__ == "__main__":
    updater = Updater()
    print(updater.latest_commit())
