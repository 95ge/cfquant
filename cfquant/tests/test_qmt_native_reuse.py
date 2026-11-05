"""Exercise host reuse and cleanup using real subprocesses and synthetic native APIs."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from cfquant.qmt_native_worker import NativeWorker, StrategyWorkerHost, QmtAutomationError


HOST = r'''
import os, sys, time, tempfile
from pathlib import Path
from types import SimpleNamespace
from cfquant.qmt_native_worker import serve
report = Path(sys.argv[1])
released = 0
def shutdown():
    report.write_text('shutdown:' + str(released))
sys.modules['frida'] = SimpleNamespace(shutdown=shutdown)
cache = Path(tempfile.gettempdir()) / 'frida-fixture' / 'frida-agent.dll'
class Backend:
    def __init__(self, directory, **kwargs):
        self.directory = directory
        self.pid = os.getpid()
        self.main_hwnd = 123
        if not cache.exists():
            cache.parent.mkdir()
            cache.write_bytes(b'fixture')
        if directory == 'open-failure':
            raise RuntimeError('open failed')
    def snapshot(self):
        if self.directory == 'crash': os._exit(23)
        if self.directory == 'hang': time.sleep(60)
        return dict(directory=self.directory, pid=self.pid, released=released,
                    cache=str(cache), modified=cache.stat().st_mtime_ns)
    def close(self):
        global released
        released += 1
        if self.directory == 'close-failure': raise RuntimeError('detach failed')
serve(lambda **kwargs: Backend(**kwargs))
'''


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("CFQUANT_FRIDA_TEMP_DIR", str(tmp_path / "native"))
    report = tmp_path / "shutdown.txt"
    def factory(*args, **kwargs):
        return NativeWorker(*args, command=[sys.executable, "-u", "-c", HOST, str(report)], **kwargs)
    host = StrategyWorkerHost(factory)
    host.report = report
    yield host
    host.close()


def test_reuses_process_and_dll_but_releases_each_target_session(host):
    first = host("first")
    before = first.snapshot()
    worker = host.worker
    first.close()
    second = host("second")
    after = second.snapshot()
    assert after["pid"] == before["pid"] and after["directory"] == "second"
    assert after["released"] == 1 and after["modified"] == before["modified"]
    assert Path(after["cache"]).is_relative_to(worker.files.path)
    second.close()
    with pytest.raises(QmtAutomationError):
        second.snapshot()
    host.close()
    assert host.report.read_text() == "shutdown:2"
    assert worker.process.returncode == 0 and not worker.files.path.exists()


def test_crash_is_not_replayed_and_next_inspection_gets_a_new_host(host):
    lease = host("crash")
    dead = host.worker
    with pytest.raises(QmtAutomationError):
        lease.snapshot()
    lease.close()
    assert dead.process.returncode == 23 and not dead.files.path.exists()
    lease = host("next")
    assert lease.snapshot()["pid"] != dead.process.pid
    lease.close()


def test_open_failure_discards_cached_worker_and_cleans_files(host):
    first = host("first")
    worker = host.worker
    first.close()
    with pytest.raises(RuntimeError, match="open failed"):
        host("open-failure")
    assert host.worker is None and not worker.files.path.exists()


def test_shutdown_runs_even_when_detach_raises(host):
    lease = host("close-failure")
    worker = host.worker
    # Close the whole worker with its backend still attached.
    worker.close()
    assert host.report.read_text() == "shutdown:1"
    assert not worker.files.path.exists()
    lease.close()


def test_host_shutdown_cancels_active_native_wait(host):
    entered = threading.Event()
    def inspect():
        lease = host("hang")
        entered.set()
        try:
            with pytest.raises(QmtAutomationError):
                lease.snapshot()
        finally:
            lease.close()
    with ThreadPoolExecutor() as pool:
        result = pool.submit(inspect)
        assert entered.wait(5)
        host.close()
        result.result(timeout=5)
    assert host.worker is None


def test_process_launch_failure_cleans_allocated_directory(tmp_path, monkeypatch):
    root = tmp_path / "native"
    monkeypatch.setenv("CFQUANT_FRIDA_TEMP_DIR", str(root))
    def fail(*args, **kwargs):
        raise OSError("launch failed")
    monkeypatch.setattr(subprocess, "Popen", fail)
    with pytest.raises(OSError, match="launch failed"):
        NativeWorker("strategy", ".")
    assert list(root.iterdir()) == []
