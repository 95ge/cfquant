"""Terminal crash recovery, ownership and restart throttling."""
from types import SimpleNamespace

import pytest

from cfquant.tests.test_qmt_strategy_web import web_config


@pytest.fixture
def watchdog(web_config, monkeypatch, tmp_path):
    web, config = web_config
    monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "saved")
    monkeypatch.setattr(web, "QMT_AUTO_LOGIN_STATE_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(web, "QMT_COMPONENT_JOBS", {})
    monkeypatch.setattr(web, "QMT_PYTHON_RUNTIME_JOBS", {})
    monkeypatch.setattr(web, "_record_monitor_notification", lambda *a, **k: None)
    row = {"account_key": "one", "account_id": "fixture", "enabled": True,
           "qmt_dir": str(tmp_path / "QMT/bin.x64"),
           "qmt_auto_login": {"enabled": True, "auto_fill_credentials": False}}
    config._data["account_configs"] = {"one": row}
    paths = {"bin_dir": row["qmt_dir"], "exe_path": "fixture.exe"}
    monkeypatch.setattr(web, "_qmt_auto_login_paths", lambda directory: paths)
    running, calls, clock = [{"pid": 123}], [], [0.0]
    monkeypatch.setattr(web, "_qmt_auto_login_processes", lambda *a, **k: list(running))
    monkeypatch.setattr(web, "qmt_auto_login_apply_for_account",
                        lambda *a, **k: calls.append(k) or {"configured": True, "pid": 456})
    job = web.QmtProcessWatchdog(clock=lambda: clock[0])
    return web, config, row, job, running, calls, clock


def test_crash_recovery_debounces_deduplicates_and_backs_off(watchdog):
    web, config, row, job, running, calls, clock = watchdog
    config._data["account_configs"]["two"] = dict(row, account_key="two")
    job.run_pending()
    running.clear()
    clock[0] = 10
    assert job.run_pending() == []
    clock[0] = 20
    assert len(job.run_pending()) == 1
    assert calls == [{"restart": False, "reason": "process_exit"}]
    assert web._qmt_auto_login_saved_session(row)["process_recovery"]["attempts"] == 1
    clock[0] = 79
    assert job.run_pending() == []
    clock[0] = 80
    assert len(job.run_pending()) == 1
    clock[0] = 199
    assert job.run_pending() == []
    clock[0] = 200
    assert len(job.run_pending()) == 1


@pytest.mark.parametrize("block", ["disabled", "binding", "policy", "login", "runtime", "deploy"])
def test_does_not_interfere_with_disabled_or_owned_transitions(watchdog, monkeypatch, block):
    web, _, row, job, running, calls, clock = watchdog
    job.run_pending()
    running.clear()
    if block == "disabled":
        row["qmt_auto_login"]["enabled"] = False
    elif block == "binding":
        row["enabled"] = False
    elif block == "policy":
        monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "0")
    elif block == "login":
        web.QMT_COMPONENT_JOBS[web._qmt_component_job_key(row["qmt_dir"])] = SimpleNamespace(is_alive=lambda: True)
    elif block == "runtime":
        web.QMT_PYTHON_RUNTIME_JOBS["task"] = {"state": "running", "qmt_dir": row["qmt_dir"]}
    else:
        web._qmt_auto_login_update_session(row, {"state": "waiting_deploy"})
    for clock[0] in (10, 20, 600):
        assert job.run_pending() == []
    assert not calls


def test_unstarted_binding_is_not_armed_but_saved_pid_survives_web_reload(watchdog):
    web, _, row, job, running, calls, clock = watchdog
    running.clear()
    job.run_pending()
    clock[0] = 20
    job.run_pending()
    assert not calls
    web._qmt_auto_login_update_session(row, {"pid": 123})
    job.run_pending()
    clock[0] = 30
    assert len(job.run_pending()) == 1


def test_process_scan_error_never_starts_terminal(watchdog, monkeypatch):
    web, _, _, job, _, calls, clock = watchdog
    job.run_pending()
    def denied(*a, **k):
        raise RuntimeError("access denied")
    monkeypatch.setattr(web, "_qmt_auto_login_processes", denied)
    for clock[0] in (10, 20, 30):
        job.run_pending()
    assert not calls


def test_restart_race_keeps_new_terminal_running(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    row = {"account_id": "fixture", "qmt_dir": str(tmp_path / "QMT/bin.x64"),
           "qmt_auto_login": {"enabled": True, "auto_fill_credentials": False}}
    monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "saved")
    monkeypatch.setattr(web, "_qmt_auto_login_paths", lambda d: {"bin_dir": d, "exe_path": "fixture.exe"})
    monkeypatch.setattr(web, "_qmt_auto_login_processes", lambda *a, **k: [{"pid": 789}])
    monkeypatch.setattr(web, "_qmt_auto_login_stop_xtitclient", lambda *a, **k: pytest.fail("must not stop new QMT"))
    monkeypatch.setattr(web, "_qmt_auto_login_start_xtitclient", lambda *a, **k: pytest.fail("must not duplicate QMT"))
    result = web.qmt_auto_login_apply_for_account(row, reason="process_exit")
    assert result["configured"] and result["pid"] == 789


@pytest.mark.parametrize("auto_fill", [False, True])
def test_missing_terminal_launches_then_queues_existing_login_flow(web_config, monkeypatch, tmp_path, auto_fill):
    web, _ = web_config
    monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "saved")
    monkeypatch.setattr(web, "QMT_AUTO_LOGIN_STATE_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(web, "QMT_COMPONENT_JOBS", {})
    row = {"account_id": "fixture", "qmt_dir": str(tmp_path / "QMT/bin.x64"),
           "qmt_auto_login": {"enabled": True, "auto_fill_credentials": auto_fill}}
    paths = {"bin_dir": row["qmt_dir"], "exe_path": "fixture.exe"}
    monkeypatch.setattr(web, "_qmt_auto_login_paths", lambda d: paths)
    monkeypatch.setattr(web, "_qmt_auto_login_processes", lambda *a, **k: [])
    monkeypatch.setattr(web, "_qmt_component_login_preflight", lambda *a: None)
    calls = []
    monkeypatch.setattr(web, "_qmt_auto_login_stop_xtitclient", lambda *a, **k: pytest.fail("already exited"))
    monkeypatch.setattr(web, "QMT_STRATEGIES", SimpleNamespace(
        prepare_for_start=lambda d: calls.append("deploy") or {}))
    monkeypatch.setattr(web, "_qmt_auto_login_start_xtitclient",
                        lambda *a, **k: calls.append("launch") or {"pid": 456})
    monkeypatch.setattr(web, "_qmt_queue_component_login",
                        lambda r, p, pid: calls.append(("login", pid)))
    result = web.qmt_auto_login_apply_for_account(row, reason="process_exit")
    assert result["configured"] and result["pid"] == 456
    assert calls == ["deploy", "launch"] + ([("login", 456)] if auto_fill else [])


def test_stable_terminal_resets_crash_backoff(watchdog):
    _, _, _, job, running, calls, clock = watchdog
    job.run_pending()
    running.clear()
    clock[0] = 10
    job.run_pending()
    clock[0] = 20
    job.run_pending()
    running.append({"pid": 456})
    clock[0] = 30
    job.run_pending()
    clock[0] = 330
    job.run_pending()
    running.clear()
    clock[0] = 340
    job.run_pending()
    clock[0] = 350
    job.run_pending()
    assert len(calls) == 2
    assert next(iter(job.observed.values()))["attempts"] == 1
