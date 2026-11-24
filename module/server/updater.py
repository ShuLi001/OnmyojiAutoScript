import datetime
import os
import re
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Tuple
from uuid import uuid4

from filelock import FileLock
from deploy.git import GitManager
from deploy.pip import PipManager
from deploy.utils import DEPLOY_CONFIG
from module.config.atomicwrites import atomic_write
from module.logger import logger
from module.server.config import DeployConfig


DEFAULT_GIT_TIMEOUT = 5
DEFAULT_FETCH_TIMEOUT = 15
FETCH_RETRY = 2
DEFAULT_PULL_TIMEOUT = 300
update_lock = threading.Lock()
UPDATE_REPOSITORIES = {
    "Gitee": "https://gitee.com/Shu_Li_x/OnmyojiAutoScript.git",
    "GitHub": "https://github.com/ShuLi001/OnmyojiAutoScript.git",
}


class Updater(DeployConfig, GitManager, PipManager):
    def __init__(self, file=DEPLOY_CONFIG):
        self.file = file
        self.config = {}
        self.read()
        if not os.path.exists(file):
            self.write()
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

    def execute_command(self, args, timeout=DEFAULT_GIT_TIMEOUT) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(
                [self.git, *args], cwd=self.root_filepath,
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"Git {args[0]} timed out after {timeout}s")
            return None
        except OSError as e:
            logger.warning(f"Git {args[0]} failed: {e}")
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
            ["--no-pager", "log", f"--pretty=format:%{ph}---%an---%ad---%s", "--date=iso", f"-{n}", revision or "HEAD", "--"]
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
        return self.execute_output(["branch", "--show-current"]).strip()

    def update_target(self) -> dict:
        origin = self.execute_output(["remote", "get-url", "origin"]).strip()
        return {
            "repositories": UPDATE_REPOSITORIES,
            "repository": origin if origin in UPDATE_REPOSITORIES.values() else None,
            "branch": self.Branch,
        }

    def save_update_target(self, repository: str, branch: str):
        if repository not in UPDATE_REPOSITORIES.values():
            raise ValueError("请选择列表中的 OAS 更新源")
        if not re.fullmatch(r"[\w][\w./-]{0,199}", branch) or branch == "HEAD":
            raise ValueError("更新分支名称无效")
        valid = self.execute_command(["check-ref-format", f"refs/heads/{branch}"])
        if valid is None or valid.returncode:
            raise ValueError("更新分支名称无效")
        remote = self.execute_command(["ls-remote", "--exit-code", "--heads", repository, f"refs/heads/{branch}"],
                                      timeout=DEFAULT_FETCH_TIMEOUT)
        if remote is None or remote.returncode != 0:
            raise ValueError("远端没有这个分支" if remote and remote.returncode == 2 else "无法连接更新源并验证分支")

        def set_git(*args):
            result = self.execute_command(list(args))
            if result is None or result.returncode:
                raise RuntimeError("无法保存 Git 远端设置")

        path = Path(self.file)
        with FileLock(f"{path}.lock"):
            original = path.read_bytes()
            content = original.decode("utf-8")
            for key, value in (("Repository", repository), ("Branch", branch)):
                content, count = re.subn(rf"(?m)^([ \t]*{key}:[ \t]*)[^\r\n]*", lambda m: m[1] + value, content)
                if count != 1:
                    raise ValueError(f"部署配置中的 {key} 字段缺失或重复")
            old = self.execute_output(["config", "--local", "--get", "remote.origin.url"]).strip()
            if not old:
                raise ValueError("当前 OAS 仓库缺少 origin")
            push = self.execute_command(["config", "--local", "--get-all", "remote.origin.pushurl"])
            if push is None or push.returncode not in (0, 1):
                raise RuntimeError("无法读取 Git 推送地址")
            add_push = old != repository and push.returncode == 1
            if add_push:
                set_git("remote", "set-url", "--push", "origin", old)
            try:
                if old != repository:
                    set_git("remote", "set-url", "origin", repository)
                updated = content.encode("utf-8")
                if updated != original:
                    with atomic_write(str(path), mode="wb", overwrite=True) as out:
                        if os.name == "posix":
                            os.fchmod(out.fileno(), path.stat().st_mode & 0o777)
                        out.write(updated)
            except BaseException:
                if old != repository:
                    set_git("remote", "set-url", "origin", old)
                if add_push:
                    set_git("config", "--local", "--unset", "remote.origin.pushurl")
                raise
        return {"repository": repository, "branch": branch}

    def current_commit(self) -> str:
        return self.get_commit()

    def latest_commit(self) -> str:
        source = "origin"
        return self.get_commit(f"{source}/{self.Branch}")

    def fetch_remote(self) -> bool:
        source = "origin"
        for _ in range(FETCH_RETRY):
            result = self.execute_command(
                ["fetch", source, f"+refs/heads/{self.Branch}:refs/remotes/{source}/{self.Branch}"],
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
            ["rev-list", "--left-right", "--count", f"{left}...{right}", "--"]
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
        current = self.current_branch()

        checked = self.fetch_remote()
        if checked:
            distance = self.revision_distance("HEAD", remote_revision)
            if distance is None:
                checked = False
            else:
                ahead, behind = distance
                is_update = current != self.Branch or (not ahead and bool(behind))
                if ahead and current == self.Branch:
                    logger.info("Local branch has commits not in upstream, skip update")
                logger.info("New update available" if is_update else "No update")

        commits = self.get_commit(remote_revision, n=15) if checked else []
        latest_commit = commits[0] if commits and isinstance(commits, list) else commits
        return {
            'checked': checked,
            'is_update': is_update,
            'branch': current,
            'update_target': self.update_target(),
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
        switching = self.current_branch() != self.Branch
        if switching:
            if not self.fetch_remote():
                emit('无法拉取目标分支')
                return False
            local = self.execute_command(["show-ref", "--verify", "--quiet", f"refs/heads/{self.Branch}"])
            if local is None or local.returncode not in (0, 1):
                emit('无法检查本地目标分支')
                return False
            if local.returncode == 0:
                distance = self.revision_distance(f"refs/heads/{self.Branch}", f"refs/remotes/origin/{self.Branch}")
                if distance is None or distance[0]:
                    emit('本地目标分支有独立提交或无法核对，无法切换')
                    return False
                switch = ["switch", "--no-overwrite-ignore", self.Branch]
            else:
                switch = ["switch", "--no-overwrite-ignore", "-c", self.Branch, "--track", f"origin/{self.Branch}"]
            result = self.execute_command(switch)
            if result is None or result.returncode:
                emit(f'切换更新分支失败：{result.stderr.strip() if result else "Git 超时或不可用"}')
                return False
            emit(f'已切换到分支 {self.Branch}')
        env = os.environ.copy()
        env['GIT_TERMINAL_PROMPT'] = '0'
        env['GCM_INTERACTIVE'] = 'Never'
        # Capture both streams, including Git progress normally written to stderr.
        with subprocess.Popen(
            [self.git, 'pull', '--progress', '--ff-only' if switching else '--no-rebase', 'origin', self.Branch],
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
