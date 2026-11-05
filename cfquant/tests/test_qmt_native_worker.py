"""Exercise actual subprocess failure isolation without touching QMT or Frida."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from cfquant.qmt_native_worker import NativeWorker, QmtAutomationError, QmtAutomationCancelled


@pytest.fixture(autouse=True)
def private_native_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CFQUANT_FRIDA_TEMP_DIR", str(tmp_path / "native"))


FAKE_WORKER = '''
import os, sys, time
from cfquant.qmt_native_worker import serve
from cfquant.qmt_component_login import QmtNotReady
class Backend:
    pid = os.getpid()
    main_hwnd = 123
    def state(self):
        print('native diagnostic noise')
        return {'label': '\\u767b\\u5f55', 'pid': os.getpid()}
    def fill(self, password):
        print(password, file=sys.stderr)
        raise RuntimeError(password)
    def submit(self):
        raise QmtNotReady('not ready yet')
    def wait_outcome(self):
        time.sleep(60)
    def already_logged_in(self):
        os._exit(23)
    def select_account(self, account, replace=False):
        return account
    def close(self):
        pass
serve(lambda **kw: Backend())
'''


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.delenv("CFQUANT_QMT_AUTOMATION", raising=False)
    child = NativeWorker("login", ".", command=[sys.executable, "-u", "-c", FAKE_WORKER])
    try:
        yield child
    finally:
        child.close()


def test_native_calls_are_in_another_process_and_stdout_is_not_protocol(worker):
    result = worker.state()
    assert result == {"label": "登录", "pid": worker.pid}
    assert worker.pid != os.getpid()
    assert "frida" not in sys.modules
    assert worker.select_account("模拟账号") == "模拟账号"


def test_native_crash_is_reported_without_killing_caller_or_replaying(worker):
    with pytest.raises(QmtAutomationError):
        worker.already_logged_in()
    assert worker.process.returncode == 23
    assert not worker.files.path.exists()
    with pytest.raises(QmtAutomationError):
        worker.state()
    assert worker._sequence == 2  # open + crashed call; no automatic replay.


def test_hung_call_is_bounded_and_child_reaped(worker):
    worker.call_timeout = .25
    started = time.monotonic()
    with pytest.raises(QmtAutomationError, match="超时"):
        worker.wait_outcome()
    assert time.monotonic() - started < 5
    assert worker.process.poll() is not None
    assert all(not reader.is_alive() for reader in worker._readers)


def test_cancellation_interrupts_native_wait(worker):
    stop = threading.Event()
    worker.should_cancel = stop.is_set
    timer = threading.Timer(.2, stop.set)
    timer.start()
    try:
        with pytest.raises(QmtAutomationCancelled):
            worker.wait_outcome()
    finally:
        timer.cancel()
    assert worker.process.poll() is not None


def test_callback_failure_terminates_worker_without_masking_update_signal(worker):
    class UpdateFinished(Exception):
        pass
    worker.should_cancel = lambda: (_ for _ in ()).throw(UpdateFinished())
    with pytest.raises(UpdateFinished):
        worker.state()
    assert worker.process.poll() is not None


def test_native_errors_preserve_retryable_type_and_do_not_disclose_password(worker, capsys):
    from cfquant.qmt_component_login import QmtNotReady
    with pytest.raises(QmtNotReady, match="not ready yet"):
        worker.submit()
    secret = "synthetic-secret-do-not-log"
    with pytest.raises(RuntimeError) as caught:
        worker.fill(secret)
    assert secret not in str(caught.value)
    assert secret not in repr(worker.process.args)
    assert secret not in capsys.readouterr().out
    assert worker.state()["pid"] == worker.pid


def test_graceful_close_reaps_process_and_readers(worker):
    worker.close()
    assert worker.process.returncode == 0
    assert all(not reader.is_alive() for reader in worker._readers)
    assert not worker.files.path.exists()


def test_disabled_automation_never_starts_a_worker(monkeypatch):
    monkeypatch.setenv("CFQUANT_QMT_AUTOMATION", "0")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("automation was disabled"))
    with pytest.raises(QmtAutomationError, match="已关闭"):
        NativeWorker("login", ".")


def test_parent_pipe_loss_stops_even_a_hung_native_call():
    import json
    child = subprocess.Popen([sys.executable, "-u", "-c", FAKE_WORKER], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        child.stdin.write(json.dumps(dict(id=1, method="open", kwargs={"kind": "login"})) + "\n")
        child.stdin.flush()
        assert json.loads(child.stdout.readline())["ok"]
        child.stdin.write(json.dumps(dict(id=2, method="wait_outcome")) + "\n")
        child.stdin.flush()
        child.stdin.close()
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


def test_crash_during_worker_initialization_is_reaped(monkeypatch):
    processes = []
    popen = subprocess.Popen
    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(QmtAutomationError):
        NativeWorker("login", ".", command=[sys.executable, "-c", "import os; os._exit(23)"])
    assert len(processes) == 1 and processes[0].returncode == 23
    assert processes[0].stdin.closed and processes[0].stdout.closed and processes[0].stderr.closed


def test_dependency_pin_matches_native_gate():
    from cfquant.qmt_dependencies import FRIDA_REQUIREMENT
    root = Path(__file__).resolve().parents[2]
    for filename in ("pyproject.toml", "requirements.txt"):
        assert FRIDA_REQUIREMENT + "; sys_platform == 'win32'" in (root / filename).read_text(encoding="utf-8")
