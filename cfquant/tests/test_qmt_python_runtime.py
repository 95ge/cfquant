import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from cfquant.qmt_python_runtime import (
    QmtPythonPackage,
    QmtPythonRuntime,
    QmtPythonRuntimeError,
)


def _package(runtime, archive):
    digest = hashlib.md5(archive.read_bytes()).hexdigest()
    return QmtPythonPackage(runtime, "2.0.3.12", "http://example.invalid/runtime.zip",
                            archive.name, digest, True)


def test_install_and_switch_python312(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    account = root / "userdata" / "users" / "55009948"
    account.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.33.0"/><python libs_path="%s" m_nPythonVersion="0" native_libs_path="x"/></root>' % bin_dir,
        encoding="utf-8",
    )
    manager = QmtPythonRuntime(root, account_id="55009948")
    archive = manager.download_dir / "python312x64-test.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python.exe", "python")
        bundle.writestr("python312.dll", "dll")
        bundle.writestr("Lib/site.py", "# test")
    package = _package("py312", archive)
    manager.install("py312", package=package)
    result = manager.switch_account("py312")
    assert (bin_dir / "python312" / "python.exe").is_file()
    assert 'm_nPythonVersion="1"' in (account / "Config.xml").read_text(encoding="utf-8")
    assert result["runtime"] == "py312"
    assert Path(result["backup"]).is_file()


def test_py36_install_merges_runtime_and_preserves_qmt_files(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    bin_dir.mkdir(parents=True)
    (bin_dir / "XtItClient.exe").write_bytes(b"qmt")
    (bin_dir / "python36.dll").write_bytes(b"old-dll")
    manager = QmtPythonRuntime(root)
    archive = manager.download_dir / "Python36x64-test.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python36.dll", "new-dll")
        bundle.writestr("DLLs/_socket.pyd", "socket")
        bundle.writestr("Lib/site.py", "# test")
    package = _package("py36", archive)
    result = manager.install("py36", package=package)
    assert (bin_dir / "python36.dll").read_bytes() == b"new-dll"
    assert (bin_dir / "DLLs" / "_socket.pyd").read_bytes() == b"socket"
    assert (bin_dir / "Lib" / "site.py").is_file()
    assert (bin_dir / "XtItClient.exe").read_bytes() == b"qmt"
    assert result["installed"] is True
    assert json.loads((root / "config" / "pythonlibDownloadInfo.txt").read_text())['md5'] == package.md5


def test_binding_status_identifies_selected_runtime_without_network(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    account = root / "userdata" / "users" / "55009948"
    account.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    runtime_dir = bin_dir / "python312"
    runtime_dir.mkdir()
    (runtime_dir / "python.exe").write_bytes(b"python")
    (runtime_dir / "python312.dll").write_bytes(b"dll")
    (runtime_dir / "Lib").mkdir()
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.33.0"/><python libs_path="%s" m_nPythonVersion="1"/></root>' % runtime_dir,
        encoding="utf-8",
    )
    status = QmtPythonRuntime(root, account_id="55009948").binding_status()
    assert status["selected_runtime"] == "py312"
    assert status["state"] == "ready"
    assert status["python_library_downloaded"] is True
    assert status["runtimes"]["py312"]["installed"] is True


def test_binding_status_fixes_old_qmt_to_default_py36(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    account = root / "userdata" / "users" / "8885060548"
    account.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    (bin_dir / "python36.dll").write_bytes(b"dll")
    (bin_dir / "Lib").mkdir()
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.19.0"/><python libs_path="%s" m_nPythonVersion="1"/></root>' % (bin_dir / "python312"),
        encoding="utf-8",
    )
    status = QmtPythonRuntime(root, account_id="8885060548").binding_status()
    assert status["qmt_version"] == "2.1.19.0"
    assert status["py312_supported"] is False
    assert status["runtime_selection"] == "fixed_py36"
    assert status["available_runtimes"] == ["py36"]
    assert status["configured_runtime"] == "py312"
    assert status["selected_runtime"] == "py36"
    assert status["state"] == "ready"


def test_download_and_switch_rejects_py312_for_old_qmt(tmp_path):
    root = tmp_path / "qmt"
    account = root / "userdata" / "users" / "8885060548"
    account.mkdir(parents=True)
    (root / "bin.x64").mkdir(parents=True)
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.19.0"/><python libs_path="x" m_nPythonVersion="0"/></root>',
        encoding="utf-8",
    )
    manager = QmtPythonRuntime(root, account_id="8885060548")
    with pytest.raises(QmtPythonRuntimeError, match="only supports.*py36"):
        manager.download_and_switch("py312")


def test_zip_slip_is_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "bad")
    with pytest.raises(QmtPythonRuntimeError, match="unsafe path"):
        QmtPythonRuntime._safe_extract(archive, tmp_path / "extract")


def runtime_fixture(tmp_path, version="2.1.33.0", configured="py36", installed=("py36", "py312")):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    bin_dir.mkdir(parents=True)
    account = root / "userdata/users/TEST_ONLY"
    account.mkdir(parents=True)
    target = bin_dir / "python312" if configured == "py312" else bin_dir
    (account / "Config.xml").write_text(
        '<root><Global version="%s"/><python libs_path="%s" m_nPythonVersion="%s"/></root>'
        % (version, target.as_posix(), "1" if configured == "py312" else "0"), encoding="utf-8")
    for runtime in installed:
        directory = bin_dir / "python312" if runtime == "py312" else bin_dir
        (directory / "Lib").mkdir(parents=True, exist_ok=True)
        (directory / ("python312.dll" if runtime == "py312" else "python36.dll")).write_bytes(b"test")
        if runtime == "py312":
            (directory / "python.exe").write_bytes(b"test")
    return QmtPythonRuntime(root, account_id="TEST_ONLY")


@pytest.mark.parametrize("mode", ["lite_advanced", "lttx"])
@pytest.mark.parametrize("auto_fill", [False, True])
def test_trade_runtime_job_switches_and_restarts_only_trade_qmt(tmp_path, monkeypatch, mode, auto_fill):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import cfquant.qmt_credentials as credentials
    from cfquant import runtime_services as web
    normal = runtime_fixture(tmp_path / "normal", configured="py312")
    trade = runtime_fixture(tmp_path / "trade", configured="py312")
    normal_config = normal.qmt_dir / "userdata/users/TEST_ONLY/Config.xml"
    original = normal_config.read_bytes()
    row = dict(account_id="TEST_ONLY", account_key="test-binding", mode=mode,
        qmt_dir=str(normal.qmt_dir), qmt_trade_dir=str(trade.bin_dir),
        qmt_strategy={"enabled": False}, qmt_auto_login={"enabled": True, "auto_fill_credentials": auto_fill, "login_account": "fixture-login"})
    monkeypatch.setattr(web, "WEB_CONFIG", SimpleNamespace(path=str(tmp_path / "settings.json"), account_configs=lambda: {"test": row}))
    store = Mock()
    store.password.return_value = "fixture-password"
    monkeypatch.setattr(credentials, "QmtCredentialStore", lambda path: store)
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", {})
    monkeypatch.setattr(web.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(web, "emit_download_progress", lambda *a, **kw: None)
    monkeypatch.setattr(QmtPythonRuntime, "_qmt_processes", lambda self: [])
    monkeypatch.setattr(QmtPythonRuntime, "restart_qmt", lambda self: pytest.fail("must use managed target restart"))
    restarts = []
    def restart(target, settings, **kwargs):
        restarts.append(target)
        return {"configured": True, "pid": 456}
    monkeypatch.setattr(web, "qmt_auto_login_restart_for_account", restart)
    body = dict(qmt_dir=str(trade.bin_dir), account_id="TEST_ONLY", runtime="py36",
        reuse_installed=True, restart=True, job_id="trade-runtime")
    web.start_qmt_python_runtime_job(body)
    web._run_qmt_python_runtime_job(body["job_id"], body)
    job = web._qmt_python_job_snapshot(body["job_id"])
    assert job["state"] == "done"
    assert trade.binding_status()["selected_runtime"] == "py36"
    assert normal_config.read_bytes() == original
    assert normal.binding_status()["selected_runtime"] == "py312"
    assert len(restarts) == 1
    target = restarts[0]
    assert Path(target["qmt_dir"]) == trade.bin_dir
    assert target["qmt_role"] == "trade"
    assert target["_qmt_binding_source_row"]["qmt_dir"] == row["qmt_dir"]
    assert web._qmt_auto_login_session_key(target) != web._qmt_auto_login_session_key(row)
    assert row["qmt_dir"] == str(normal.qmt_dir)
    if auto_fill:
        store.password.assert_called_once_with(str(normal.qmt_dir), "fixture-login")
        store.save.assert_called_once_with(str(trade.bin_dir), "fixture-login", "fixture-password")
    else:
        store.save.assert_not_called()


def test_two_qmt_runtime_capabilities_are_checked_independently(tmp_path, monkeypatch):
    from cfquant import runtime_services as web
    normal = runtime_fixture(tmp_path / "normal", version="2.1.33.0")
    trade = runtime_fixture(tmp_path / "trade", version="2.1.32.0", installed=("py36",))
    first = web.qmt_python_runtime_status(dict(qmt_dir=str(normal.qmt_dir), account_id="TEST_ONLY", runtime="py36", refresh=False))
    second = web.qmt_python_runtime_status(dict(qmt_dir=str(trade.qmt_dir), account_id="TEST_ONLY", runtime="py36", refresh=False))
    assert first["binding"]["py312_supported"]
    assert not second["binding"]["py312_supported"]
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", {})
    with pytest.raises(QmtPythonRuntimeError):
        web.start_qmt_python_runtime_job(dict(qmt_dir=str(trade.qmt_dir), account_id="TEST_ONLY", runtime="py312"))


@pytest.mark.parametrize("version, supported", [
    ("2.1.32.99", False), ("2.1.33", True), ("2.1.33.0", True),
    ("2.1.34.0", True), ("", False), ("unknown", False), ("20261109", False),
])
def test_version_gate_is_conservative(tmp_path, version, supported):
    manager = runtime_fixture(tmp_path, version=version)
    binding = manager.binding_status()
    assert binding["py312_supported"] is supported
    assert binding["available_runtimes"] == (["py36", "py312"] if supported else ["py36"])


def test_installed_client_version_overrides_account_version(tmp_path, monkeypatch):
    manager = runtime_fixture(tmp_path)
    monkeypatch.setattr(manager, "_client_version", lambda: "2.1.19.0")
    assert manager.binding_status()["py312_supported"] is False
    with pytest.raises(QmtPythonRuntimeError, match="only supports"):
        manager.switch_account("py312")


@pytest.mark.parametrize("runtime", ["py36", "py312"])
def test_installed_library_switches_offline_and_restart_sees_new_config(tmp_path, monkeypatch, runtime):
    manager = runtime_fixture(tmp_path, configured="py312" if runtime == "py36" else "py36")
    monkeypatch.setattr(manager, "fetch_package", lambda *a: pytest.fail("Installed library must not be downloaded"))
    monkeypatch.setattr(manager, "install", lambda *a, **k: pytest.fail("Installed library must not be reinstalled"))
    processes = [object()]
    events = []
    monkeypatch.setattr(manager, "_qmt_processes", lambda: processes)
    monkeypatch.setattr(manager, "_stop_for_switch", lambda: processes.clear())
    def restart():
        assert not processes
        assert manager.binding_status()["selected_runtime"] == runtime
        return {"started": True}
    result = manager.download_and_switch(runtime, reuse_installed=True, restart_callback=restart,
                                         progress_callback=events.append)
    assert result["reused_installed"] is True and result["package"] is None
    assert result["switched"]["runtime"] == runtime
    assert result["restarted"]["started"] is True
    assert [item["phase"] for item in events] == ["reusing", "activating", "restarting"]
    assert manager.switch_account(runtime)["unchanged"] is True


@pytest.mark.parametrize("runtime, version", [("py36", "2.1.19.0"), ("py312", "2.1.33.0")])
def test_missing_selected_library_downloads_then_switches(tmp_path, monkeypatch, runtime, version):
    manager = runtime_fixture(tmp_path, version=version, installed=())
    archive = manager.download_dir / (runtime + "-test.zip")
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python.exe", "test")
        bundle.writestr("python312.dll" if runtime == "py312" else "python36.dll", "test")
        bundle.writestr("Lib/site.py", "test")
    package = _package(runtime, archive)
    calls = []
    monkeypatch.setattr(manager, "fetch_package", lambda runtime: calls.append(runtime) or package)
    monkeypatch.setattr(manager, "download", lambda *a, **kw: archive)
    monkeypatch.setattr(manager, "_qmt_processes", lambda: [])
    result = manager.download_and_switch(runtime, restart=False, reuse_installed=True)
    assert calls == [runtime]
    assert result["reused_installed"] is False
    assert manager.binding_status()["state"] == "ready"
    assert manager.binding_status()["selected_runtime"] == runtime


def test_invalid_config_fails_before_download_or_process_stop(tmp_path, monkeypatch):
    manager = runtime_fixture(tmp_path)
    config = manager.qmt_dir / "userdata/users/TEST_ONLY/Config.xml"
    config.write_text('<root><Global version="2.1.33.0"/></root>', encoding="utf-8")
    monkeypatch.setattr(manager, "fetch_package", lambda *a: pytest.fail("No download"))
    monkeypatch.setattr(manager, "_qmt_processes", lambda: pytest.fail("No process access"))
    with pytest.raises(QmtPythonRuntimeError, match="no Python library settings"):
        manager.download_and_switch("py312", reuse_installed=True)


def test_missing_account_config_can_install_runtime_before_first_login(tmp_path, monkeypatch):
    root = tmp_path / "qmt"
    (root / "bin.x64").mkdir(parents=True)
    manager = QmtPythonRuntime(root, account_id="55009948")
    archive = manager.download_dir / "Python36x64-first-login.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python36.dll", "new-dll")
        bundle.writestr("Lib/site.py", "# test")
    package = _package("py36", archive)
    monkeypatch.setattr(manager, "fetch_package", lambda runtime: package)
    monkeypatch.setattr(manager, "download", lambda *args, **kwargs: archive)
    monkeypatch.setattr(manager, "_qmt_processes", lambda: [])

    result = manager.download_and_switch(
        "py36", account_id="55009948", restart=True,
        allow_missing_account_config=True,
    )

    assert result["account_config_required"] is True
    assert result["switched"] is None
    assert result["restarted"] is None
    assert (root / "bin.x64" / "python36.dll").read_bytes() == b"new-dll"
    assert not (root / "userdata" / "users" / "55009948" / "Config.xml").exists()


def test_missing_account_config_invokes_managed_restart_callback(tmp_path, monkeypatch):
    root = tmp_path / "qmt"
    (root / "bin.x64").mkdir(parents=True)
    manager = QmtPythonRuntime(root, account_id="55009948")
    archive = manager.download_dir / "Python36-managed-bootstrap.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python36.dll", "new-dll")
        bundle.writestr("Lib/site.py", "# test")
    package = _package("py36", archive)
    monkeypatch.setattr(manager, "fetch_package", lambda runtime: package)
    monkeypatch.setattr(manager, "download", lambda *args, **kwargs: archive)
    monkeypatch.setattr(manager, "_qmt_processes", lambda: [])
    calls = []

    def restart_callback():
        calls.append("restart")
        return {"started": True, "bootstrap_completed": True}

    result = manager.download_and_switch(
        "py36", account_id="55009948", restart=True,
        allow_missing_account_config=True, restart_callback=restart_callback,
    )

    assert calls == ["restart"]
    assert result["account_config_required"] is True
    assert result["restarted"]["bootstrap_completed"] is True
    assert not (root / "userdata" / "users" / "55009948" / "Config.xml").exists()


def test_runtime_status_without_account_still_exposes_capabilities(tmp_path, monkeypatch):
    from cfquant import runtime_services as web
    manager = runtime_fixture(tmp_path)
    monkeypatch.setattr(QmtPythonRuntime, "_client_version", lambda self: "2.1.33.0")
    status = web.qmt_python_runtime_status({"qmt_dir": str(manager.qmt_dir), "runtime": "py36", "refresh": False})
    assert status["binding"]["available_runtimes"] == ["py36", "py312"]
    assert status["binding"]["config_exists"] is False


def test_runtime_job_allows_install_before_first_qmt_login(tmp_path, monkeypatch):
    from cfquant import runtime_services as web
    root = tmp_path / "qmt"
    (root / "bin.x64").mkdir(parents=True)
    jobs = {}
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", jobs)
    monkeypatch.setattr(web.threading.Thread, "start", lambda self: None)
    result = web.start_qmt_python_runtime_job({
        "qmt_dir": str(root), "account_id": "55009948", "runtime": "py36",
        "allow_missing_account_config": True, "job_id": "first-login",
    })
    assert result["state"] == "queued"
    assert jobs["first-login"]["state"] == "queued"


def test_runtime_jobs_forward_reuse_and_reject_concurrent_directory(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cfquant import runtime_services as web
    manager = runtime_fixture(tmp_path)
    jobs, calls, events = {}, [], []
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", jobs)
    monkeypatch.setattr(web.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(web, "emit_download_progress", lambda *a, **kw: events.append(a[2]))
    monkeypatch.setattr(web, "_QmtPythonProgressNotifier", lambda *a: SimpleNamespace(
        notify=lambda stage, data: events.append(stage), close=lambda: None))
    def switch(self, runtime, **kwargs):
        calls.append((runtime, kwargs))
        for phase in ("reusing", "activating", "restarting"):
            kwargs["progress_callback"]({"phase": phase})
        return {}
    monkeypatch.setattr(QmtPythonRuntime, "download_and_switch", switch)
    body = {"qmt_dir": str(manager.qmt_dir), "account_id": "TEST_ONLY", "runtime": "py312",
            "reuse_installed": True, "restart": False, "job_id": "runtime-test"}
    web.start_qmt_python_runtime_job(body)
    with pytest.raises(ValueError, match="Python"):
        web.start_qmt_python_runtime_job(dict(body, job_id="other", qmt_dir=str(manager.bin_dir)))
    web._run_qmt_python_runtime_job("runtime-test", body)
    assert jobs["runtime-test"]["state"] == "done"
    assert calls[0][0] == "py312" and calls[0][1]["reuse_installed"] is True
    assert events == ["reusing", "activating", "restarting", "done"]


def test_runtime_job_rejects_unsupported_selection_before_scheduling(tmp_path, monkeypatch):
    from cfquant import runtime_services as web
    manager = runtime_fixture(tmp_path, version="2.1.19.0")
    jobs = {}
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", jobs)
    monkeypatch.setattr(web.threading.Thread, "start", lambda self: pytest.fail("Unsupported runtime must not start a job"))
    with pytest.raises(QmtPythonRuntimeError, match="only supports"):
        web.start_qmt_python_runtime_job({"qmt_dir": str(manager.qmt_dir), "account_id": "TEST_ONLY", "runtime": "py312"})
    assert not jobs


def test_runtime_job_completion_survives_notification_failure(tmp_path, monkeypatch):
    from cfquant import runtime_services as web
    manager = runtime_fixture(tmp_path)
    jobs = {}
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", jobs)
    notifiers = []
    notifier_class = web._QmtPythonProgressNotifier
    def notifier(*args):
        instance = notifier_class(*args)
        notifiers.append(instance)
        return instance
    monkeypatch.setattr(web, "_QmtPythonProgressNotifier", notifier)
    def unavailable(*args, **kwargs):
        raise RuntimeError("callback transport unavailable")
    monkeypatch.setattr(web, "emit_download_progress", unavailable)
    result = {"account_config_required": True, "installed": {"installed": True}, "restarted": None}
    def switch(self, runtime, **kwargs):
        kwargs["progress_callback"]({"phase": "download", "percent": 50})
        kwargs["progress_callback"]({"phase": "installed", "percent": 100})
        return result
    monkeypatch.setattr(QmtPythonRuntime, "download_and_switch", switch)
    body = {"qmt_dir": str(manager.qmt_dir), "account_id": "TEST_ONLY", "runtime": "py36", "job_id": "notify-failure"}
    with monkeypatch.context() as scheduling:
        scheduling.setattr(web.threading.Thread, "start", lambda self: None)
        web.start_qmt_python_runtime_job(body)
    web._run_qmt_python_runtime_job(body["job_id"], body)
    notifiers[0].thread.join(timeout=2)
    assert not notifiers[0].thread.is_alive()
    job = web._qmt_python_job_snapshot(body["job_id"])
    assert job["state"] == "done"
    assert job["result"] == result
    assert job["progress"]["phase"] == "done"
    assert job["progress"]["percent"] == 100


def test_runtime_job_initialization_failure_is_terminal(tmp_path, monkeypatch):
    from cfquant import runtime_services as web
    manager = runtime_fixture(tmp_path)
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", {})
    monkeypatch.setattr(web.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(web, "emit_download_progress", lambda *a, **kw: None)
    body = {"qmt_dir": str(manager.qmt_dir), "runtime": "py36", "job_id": "init-failure"}
    web.start_qmt_python_runtime_job(body)
    def invalid(_):
        raise ValueError("QMT directory unavailable")
    monkeypatch.setattr(web, "_qmt_python_runtime_row", invalid)
    web._run_qmt_python_runtime_job(body["job_id"], body)
    assert web._qmt_python_job_snapshot(body["job_id"])["state"] == "error"


def test_blocked_progress_subscriber_cannot_stall_installation(tmp_path, monkeypatch):
    import threading
    from cfquant import runtime_services as web
    manager = runtime_fixture(tmp_path)
    blocked, release, delivered = threading.Event(), threading.Event(), threading.Event()
    events = []
    monkeypatch.setattr(web, "WEB_CONFIG", None)
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", {"slow-socket": {"state": "queued"}})

    def emit(job_id, kind, stage, data, **kwargs):
        events.append(stage)
        if stage == "extract":
            blocked.set()
            release.wait(timeout=5)
        if stage == "done":
            delivered.set()

    def install(self, runtime, **kwargs):
        kwargs["progress_callback"]({"phase": "extract"})
        assert blocked.wait(timeout=2)
        kwargs["progress_callback"]({"phase": "installing"})
        kwargs["progress_callback"]({"phase": "installed", "percent": 100})
        return {"installed": {"installed": True}, "account_config_required": True}

    monkeypatch.setattr(web, "emit_download_progress", emit)
    monkeypatch.setattr(QmtPythonRuntime, "download_and_switch", install)
    body = {"qmt_dir": str(manager.qmt_dir), "runtime": "py36", "restart": False}
    worker = threading.Thread(target=web._run_qmt_python_runtime_job, args=("slow-socket", body))
    worker.start()
    try:
        assert blocked.wait(timeout=2)
        worker.join(timeout=2)
        assert not worker.is_alive(), "installation must finish while the socket is blocked"
        snapshot = web._qmt_python_job_snapshot("slow-socket")
        assert snapshot["state"] == "done" and snapshot["progress"]["phase"] == "done"
    finally:
        release.set()
        worker.join(timeout=5)
    assert delivered.wait(timeout=2)
    assert events == ["extract", "done"]  # Coalesce obsolete intermediate progress.


def test_new_binding_install_finishes_without_launching_qmt(tmp_path, monkeypatch):
    from cfquant import runtime_services as web
    root = tmp_path / "fresh-qmt"
    (root / "bin.x64").mkdir(parents=True)
    manager = QmtPythonRuntime(root, account_id="TEST_ONLY")
    archive = manager.download_dir / "py36.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python36.dll", "fixture")
        bundle.writestr("Lib/site.py", "# fixture")
    package = _package("py36", archive)
    monkeypatch.setattr(web, "WEB_CONFIG", None)
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", {"fresh": {"state": "queued"}})
    monkeypatch.setattr(web, "_qmt_python_runtime_row", lambda body: (manager, "py36"))
    monkeypatch.setattr(web, "emit_download_progress", lambda *a, **kw: None)
    monkeypatch.setattr(manager, "fetch_package", lambda runtime: package)
    monkeypatch.setattr(manager, "download", lambda *a, **kw: archive)
    monkeypatch.setattr(manager, "_qmt_processes", lambda: [])
    monkeypatch.setattr(manager, "restart_qmt", lambda: pytest.fail("unsaved binding must not launch QMT"))
    web._run_qmt_python_runtime_job("fresh", {"account_id": "TEST_ONLY", "runtime": "py36",
                                           "restart": True, "allow_missing_account_config": True})
    job = web._qmt_python_job_snapshot("fresh")
    assert job["state"] == "done"
    assert job["result"]["installed"]["installed"] is True
    assert job["result"]["account_config_required"] is True
    assert job["result"]["restarted"] is None
    assert job["progress"]["percent"] == 100


@pytest.mark.parametrize("restart_failed", [False, True])
def test_runtime_job_uses_managed_restart_without_inline_login_or_bypassing_errors(tmp_path, monkeypatch, restart_failed):
    from types import SimpleNamespace
    from cfquant import runtime_services as web
    manager = runtime_fixture(tmp_path)
    row = {"account_id": "TEST_ONLY", "qmt_dir": str(manager.qmt_dir)}
    monkeypatch.setattr(web, "WEB_CONFIG", SimpleNamespace(account_configs=lambda: {"test": row}))
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", {})
    monkeypatch.setattr(web.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(web, "emit_download_progress", lambda *a, **kw: None)
    monkeypatch.setattr(QmtPythonRuntime, "_qmt_processes", lambda self: [])
    monkeypatch.setattr(QmtPythonRuntime, "restart_qmt", lambda self: pytest.fail("must not bypass managed restart"))
    restart = {"configured": False, "error": "deployment write failed"} if restart_failed else {
        "configured": True, "pid": 456, "login_state": "logging_in"}
    monkeypatch.setattr(web, "qmt_auto_login_restart_for_account", lambda *a, **kw: restart)
    body = {"qmt_dir": str(manager.qmt_dir), "account_id": "TEST_ONLY", "runtime": "py36",
            "reuse_installed": True, "restart": True, "job_id": "managed-restart"}
    web.start_qmt_python_runtime_job(body)
    web._run_qmt_python_runtime_job(body["job_id"], body)
    job = web._qmt_python_job_snapshot(body["job_id"])
    assert job["state"] == ("error" if restart_failed else "done")
    if restart_failed:
        assert "deployment write failed" in job["error"]
    else:
        assert job["result"]["restarted"] == restart
    assert manager.binding_status()["state"] == "ready"


def test_runtime_bootstrap_starts_stops_and_starts_managed_qmt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cfquant import runtime_services as web

    row = {
        "account_key": "bootstrap-account",
        "account_id": "55009948",
        "qmt_dir": str(tmp_path / "qmt"),
        "qmt_strategy": {"enabled": True},
        "qmt_auto_login": {"enabled": True, "auto_fill_credentials": True},
    }
    manager = SimpleNamespace(
        binding_status=lambda account_id=None: {"state": "account_config_missing"},
        switch_account=lambda runtime, account_id=None: {"runtime": runtime, "account_id": account_id},
    )
    paths = {"bin_dir": str(tmp_path / "qmt" / "bin.x64"), "exe_path": "fixture.exe"}
    monkeypatch.setattr(web, "_qmt_auto_login_paths", lambda _: paths)
    monkeypatch.setattr(web, "_qmt_wait_for_runtime_bootstrap_login",
                        lambda row, paths: {"login_succeeded": True, "login_state": "logged_in"})
    monkeypatch.setattr(web, "_qmt_bootstrap_graceful_exit",
                        lambda *args, **kwargs: {"exit_confirmed": True})
    calls = []

    def restart(account_row, settings, reason):
        calls.append(reason)
        if reason.endswith("first"):
            return {"configured": True, "pid": 101, "strategy_deploy_deferred": True}
        return {"configured": True, "pid": 202, "strategy_deploy_deferred": False}

    monkeypatch.setattr(web, "qmt_auto_login_restart_for_account", restart)
    result = web._qmt_python_runtime_bootstrap_restart(
        row, row["qmt_auto_login"], manager, "py36", row["account_id"],
        body={"allow_missing_account_config": True},
    )

    assert calls == ["python-runtime-bootstrap-first", "python-runtime-bootstrap-final"]
    assert result["bootstrap_completed"] is True
    assert result["pid"] == 202
    assert result["runtime_switch"]["runtime"] == "py36"
