"""Isolate QMT/Frida native code from the Web process using private stdio RPC.

Credentials only travel over the child's stdin, never argv, files or logs.
Requests are not replayed after a crash or timeout: a native action may have run.
"""

from .diagnostic_context import VersionedErrorMixin
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .qmt_native_files import NativeWorkerFiles, sweep_worker_directories


LOGIN_METHODS = frozenset(("already_logged_in", "state", "select_account", "submit",
                           "fill", "solve_captcha", "wait_outcome", "acknowledge_failure", "diagnostics"))
STRATEGY_METHODS = frozenset(("snapshot", "start_strategy", "notices", "dismiss_notice"))
MAX_MESSAGE = 4 * 1024 * 1024


class QmtAutomationError(VersionedErrorMixin, RuntimeError):
    """A failed native worker; safe to display without native exception contents."""


class QmtAutomationCancelled(QmtAutomationError):
    pass


class NativeWorker:
    def __init__(self, kind, directory, *, timeout=40, expected_pid=None,
                 should_cancel=lambda: False, command=None, executable_path=None):
        if os.environ.get("CFQUANT_QMT_AUTOMATION", "1").lower() in ("0", "false", "off"):
            raise QmtAutomationError("QMT 原生自动化已关闭，请手动登录并启动策略；Web 服务及行情交易接口仍可使用。")
        self.should_cancel = should_cancel
        self.call_timeout = max(15.0, float(timeout) + 10)
        self.methods = LOGIN_METHODS if kind == "login" else STRATEGY_METHODS
        self._lock = threading.RLock()
        self._responses = queue.Queue()
        self._sequence = 0
        self._closed = False
        self._tls_error = False
        self.files = NativeWorkerFiles()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        env.update(self.files.environment())
        worker_command = command
        if worker_command is None:
            worker_command = ([sys.executable, "--cfquant-native-worker"] if getattr(sys, "frozen", False)
                              else [sys.executable, "-u", "-m", "cfquant.qmt_native_worker"])
        try:
            self.process = subprocess.Popen(
                worker_command,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                cwd=None if getattr(sys, "frozen", False) else str(Path(__file__).resolve().parents[1]),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            try:
                self.files.register(self.process.pid)
            except Exception:
                if self.process.poll() is None:
                    self.process.kill()
                self.process.wait(timeout=5)
                for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                    stream.close()
                raise
        except Exception:
            self.files.close()
            raise
        self._readers = [
            threading.Thread(target=self._read_responses, name="qmt-native-response", daemon=True),
            threading.Thread(target=self._read_errors, name="qmt-native-stderr", daemon=True),
        ]
        for thread in self._readers:
            thread.start()
        try:
            open_kwargs = dict(kind=kind, directory=str(directory), timeout=timeout,
                               expected_pid=expected_pid)
            if executable_path:
                open_kwargs["executable_path"] = str(executable_path)
            info = self.call("open", **open_kwargs)
            self.pid = info.get("pid")
            self.main_hwnd = info.get("main_hwnd")
        except BaseException:
            self.close(force=True)
            raise

    def _read_responses(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_MESSAGE + 1)
                if not line or len(line) > MAX_MESSAGE:
                    break
                self._responses.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self._responses.put(None)

    def _read_errors(self):
        try:
            while True:
                chunk = self.process.stderr.readline(4096)
                if not chunk:
                    break
                if "Unable to locate the ntdll loader TLS routines" in chunk:
                    self._tls_error = True
                # Native output can contain input values; never forward it.
        except (ValueError, OSError):
            pass

    def _failure(self, reason):
        from .qmt_dependencies import FRIDA_REQUIREMENT
        detail = "Frida 与当前 Windows 不兼容" if self._tls_error else reason
        return QmtAutomationError(
            "QMT 自动化子进程%s，已停止本次自动操作，Web 服务继续运行。"
            "请检查自动登录组件并安装 %s，或手动登录、启动 QMT 策略。" % (detail, FRIDA_REQUIREMENT))

    def call(self, method, *args, **kwargs):
        with self._lock:
            if self._closed:
                raise self._failure("已关闭")
            self._sequence += 1
            request_id = self._sequence
            try:
                if self.should_cancel():
                    raise QmtAutomationCancelled("QMT 自动操作已取消")
                message = json.dumps(dict(id=request_id, method=method, args=args, kwargs=kwargs), ensure_ascii=True)
                if len(message) > MAX_MESSAGE:
                    raise self._failure("请求过大")
                self.process.stdin.write(message + "\n")
                self.process.stdin.flush()
                deadline = time.monotonic() + self.call_timeout
                while True:
                    if self.should_cancel():
                        raise QmtAutomationCancelled("QMT 自动操作已取消")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise self._failure("响应超时")
                    try:
                        reply = self._responses.get(timeout=min(.1, remaining))
                        break
                    except queue.Empty:
                        continue
                if not isinstance(reply, dict) or reply.get("id") != request_id:
                    raise self._failure("异常退出或通信中断")
            except (BrokenPipeError, OSError) as error:
                self.close(force=True)
                raise self._failure("通信中断") from error
            except BaseException:
                self.close(force=True)
                raise
            if not reply.get("ok"):
                self._raise_remote(reply)
            return reply.get("result")

    @staticmethod
    def _raise_remote(reply):
        from .qmt_component_login import QmtNotReady, QmtProcessExited
        from .qmt_dependencies import QmtDependencyError
        from .qmt_strategy_recovery import UnsupportedQmt
        errors = {cls.__name__: cls for cls in (QmtNotReady, QmtProcessExited, QmtDependencyError, UnsupportedQmt)}
        raise errors.get(reply.get("error_type"), RuntimeError)(reply.get("error") or "QMT native operation failed")

    def __getattr__(self, name):
        if name not in self.methods:
            raise AttributeError(name)
        return lambda *args, **kwargs: self.call(name, *args, **kwargs)

    def close(self, force=False):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if not force and self.process.poll() is None:
                    self.process.stdin.write(json.dumps(dict(id=0, method="close")) + "\n")
                    self.process.stdin.flush()
                    self.process.wait(timeout=3)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
            finally:
                if self.process.poll() is None:
                    self.process.kill()
                self.process.wait(timeout=5)
                try:
                    self.process.stdin.close()
                except OSError:
                    pass  # A crash may leave buffered input with no reader.
                for thread in self._readers:
                    thread.join(timeout=1)
                self.process.stdout.close()
                self.process.stderr.close()
                self.files.close()


class StrategyWorkerHost:
    """Reuse one Frida host, but detach the QMT session after every inspection."""
    def __init__(self, worker_factory=NativeWorker):
        self.worker_factory = worker_factory
        self.worker = None
        self.lock = threading.RLock()
        self.stopped = threading.Event()

    def __call__(self, directory):
        self.lock.acquire()
        try:
            if self.stopped.is_set():
                raise QmtAutomationCancelled("QMT 策略检测已停止")
            worker = self.worker
            if worker is not None and (worker._closed or worker.process.poll() is not None):
                worker.close(force=True)
                self.worker = worker = None
            if worker is None:
                worker = self.worker_factory("strategy", directory, timeout=15,
                                             should_cancel=self.stopped.is_set)
                self.worker = worker
            else:
                sweep_worker_directories(worker.files.root)
                info = worker.call("open", kind="strategy", directory=str(directory), timeout=15)
                worker.pid, worker.main_hwnd = info.get("pid"), info.get("main_hwnd")
            return _StrategyWorkerLease(self, worker)
        except BaseException:
            self._discard()
            self.lock.release()
            raise

    def _discard(self):
        if self.worker is not None:
            worker, self.worker = self.worker, None
            worker.close(force=True)

    def close(self):
        self.stopped.set()
        with self.lock:
            if self.worker is not None:
                worker, self.worker = self.worker, None
                worker.close()


class _StrategyWorkerLease:
    def __init__(self, host, worker):
        self.host, self.worker = host, worker
        self.pid, self.main_hwnd = worker.pid, worker.main_hwnd
        self.closed = False

    def __getattr__(self, name):
        if name not in STRATEGY_METHODS:
            raise AttributeError(name)
        def call(*args, **kwargs):
            if self.closed:
                raise QmtAutomationCancelled("QMT 策略检测会话已关闭")
            return self.worker.call(name, *args, **kwargs)
        return call

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            try:
                self.worker.call("release")
            except Exception:
                self.host._discard()
        finally:
            self.host.lock.release()


class IsolatedLoginBackend(NativeWorker):
    def __init__(self, directory, timeout=40, expected_pid=None, *, should_cancel=lambda: False,
                 executable_path=None):
        super().__init__("login", directory, timeout=timeout, expected_pid=expected_pid,
                         should_cancel=should_cancel, executable_path=executable_path)


class IsolatedStrategyBackend(NativeWorker):
    def __init__(self, directory):
        super().__init__("strategy", directory, timeout=15)


def verify_environment_isolated(directory, executable_path=None):
    worker = NativeWorker("verify", directory, timeout=5, executable_path=executable_path)
    worker.close()


def _open_backend(kind, directory, timeout=40, expected_pid=None, executable_path=None):
    from .qmt_component_login import QtLoginBackend, _verify_environment_native
    if kind == "verify":
        _verify_environment_native(directory, executable_path=executable_path)
        return None
    if kind == "login":
        return QtLoginBackend(Path(directory), timeout, expected_pid=expected_pid,
                              executable_path=executable_path)
    if kind == "strategy":
        from .qmt_strategy_recovery import QtStrategyBackend
        return QtStrategyBackend(directory)
    raise ValueError("Unknown QMT worker kind")


def serve(factory=_open_backend):
    # Reserve stdout for protocol, including when a native DLL prints to fd 1.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    requests = queue.Queue(maxsize=2)
    def receive():
        try:
            while True:
                line = sys.stdin.readline(MAX_MESSAGE + 1)
                if not line or len(line) > MAX_MESSAGE:
                    break
                requests.put(json.loads(line))
        finally:
            # Also stop a hung native call if the Web parent exits unexpectedly.
            os._exit(0)
    threading.Thread(target=receive, name="qmt-native-input", daemon=True).start()
    backend = None
    opened = False
    methods = frozenset()
    try:
        while True:
            request = requests.get()
            method = request.get("method")
            if method == "close":
                break
            try:
                if method == "open" and not opened:
                    kwargs = request["kwargs"]
                    backend = factory(**kwargs)
                    opened = True
                    methods = LOGIN_METHODS if kwargs["kind"] == "login" else STRATEGY_METHODS
                    result = {key: getattr(backend, key, None) for key in ("pid", "main_hwnd")}
                elif method == "release" and opened:
                    try:
                        if backend is not None:
                            backend.close()
                    finally:
                        backend, opened, methods = None, False, frozenset()
                    result = None
                elif opened and backend is not None and method in methods:
                    result = getattr(backend, method)(*request.get("args", []), **request.get("kwargs", {}))
                else:
                    raise ValueError("Unsupported QMT worker request")
                reply = dict(id=request["id"], ok=True, result=result)
            except Exception as error:
                reply = dict(id=request["id"], ok=False, error_type=type(error).__name__,
                             error="QMT credential entry failed" if method == "fill" else str(error))
            output.write(json.dumps(reply, ensure_ascii=True) + "\n")
            output.flush()
            request = None
    finally:
        try:
            if backend is not None:
                backend.close()
        finally:
            try:
                # detach() releases a target session, not the host's DLL cache.
                frida = sys.modules.get("frida")
                if frida is not None:
                    frida.shutdown()
            finally:
                output.close()


if __name__ == "__main__":
    serve()
