"""First binding initialization with fake processes and real model configuration."""
import threading
from types import SimpleNamespace

import pytest

from cfquant.tests.test_qmt_strategy_web import web_config
from cfquant.tests.test_qmt_strategy_deploy import deployment, finish_import, models, ACCOUNT_KEY


@pytest.fixture
def bootstrap(web_config, deployment, monkeypatch, tmp_path):
    import cfquant.qmt_component_login as component
    import cfquant.qmt_update as updater
    web, config = web_config
    manager, row, infos, running, root = deployment
    (root / "config/indexUserConfig.xml").write_text(
        '<ICUserConfigFile><FormulaCatalog/><strategyTrade/></ICUserConfigFile>', encoding="utf-8")
    manager.configure(row, infos)
    row["qmt_auto_login"] = {"enabled": True, "auto_fill_credentials": True, "login_account": "test-login"}
    monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "saved")
    monkeypatch.setattr(web, "QMT_AUTO_LOGIN_STATE_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(web, "QMT_COMPONENT_JOBS", {})
    monkeypatch.setattr(web, "QMT_STRATEGIES", manager)
    paths = {"bin_dir": str(root / "bin.x64"), "exe_path": str(root / "bin.x64/XtItClient.exe")}
    monkeypatch.setattr(web, "_qmt_auto_login_paths", lambda _: paths)
    monkeypatch.setattr(web, "_qmt_component_login_preflight", lambda *a: None)
    launches, queued, stops = [], [], []
    monkeypatch.setattr(web, "_qmt_auto_login_processes",
                        lambda *a, **k: [{"pid": launches[-1]}] if running[0] else [])
    def launch(*a, **k):
        running[0] = True
        launches.append(101 + len(launches))
        return {"pid": launches[-1]}
    monkeypatch.setattr(web, "_qmt_auto_login_start_xtitclient", launch)
    monkeypatch.setattr(web, "_qmt_auto_login_stop_xtitclient",
                        lambda *a, **k: pytest.fail("first initialization must not force-kill"))
    key = web._qmt_component_job_key(paths["bin_dir"])
    def queue(login_row, login_paths, pid):
        queued.append((login_row, dict(login_paths), pid))
        web.QMT_COMPONENT_JOBS[key] = SimpleNamespace(is_alive=lambda: True, qmt_pid=pid)
    monkeypatch.setattr(web, "_qmt_queue_component_login", queue)
    def stop(*a, **k):
        stops.append(launches[-1])
        finish_import(manager, root)
        auth = root / "userdata/users/test/authAndConfig.xml"
        auth.parent.mkdir(parents=True, exist_ok=True)
        auth.write_text('<TTAuthAndConfigFile><AccountAuth key="%s"/></TTAuthAndConfigFile>'
                        % ACCOUNT_KEY, encoding="utf-8")
        running[0] = False
        return {"exit_confirmed": True}
    monkeypatch.setattr(web, "_qmt_bootstrap_graceful_exit", stop)
    monkeypatch.setattr(component, "login_running_qmt",
                        lambda *a, **k: {"outcome": "logged_in", "login_succeeded": True})
    monkeypatch.setattr(updater, "manage_qmt_startup", lambda directory, pid, login, **k: login(pid, lambda: None))
    def work():
        login_row, login_paths, pid = queued.pop(0)
        web.QMT_COMPONENT_JOBS[key] = threading.current_thread()
        web._qmt_component_login_worker(login_row, login_paths, pid, config.path)
    return SimpleNamespace(web=web, row=row, root=root, manager=manager, running=running,
                           launches=launches, queued=queued, stops=stops, work=work, key=key)


def test_saved_binding_completes_first_login_model_configuration_and_second_login(bootstrap):
    b = bootstrap
    result = b.web.qmt_auto_login_apply_for_account(b.row)
    assert result["strategy_bootstrap_phase"] == "waiting_login"
    assert b.launches == [101]
    duplicate = b.web.qmt_auto_login_apply_for_account(b.row)
    assert duplicate["strategy_bootstrap_phase"] == "waiting_login"
    assert len(b.queued) == 1
    b.work()
    assert b.stops == [101] and b.launches == [101, 102]
    role = next(iter(b.manager.jobs.values()))["roles"][0]
    assert models(b.root)[role["name"]].getAttribute("m_strAccountKey") == ACCOUNT_KEY
    assert b.web._qmt_auto_login_saved_session(b.row)["strategy_bootstrap_phase"] == "restarting"
    assert b.key in b.web.QMT_COMPONENT_JOBS  # old worker must retain the new login job
    b.work()
    session = b.web._qmt_auto_login_saved_session(b.row)
    assert session["strategy_bootstrap_phase"] == "complete" and session["login_succeeded"]
    assert not session["strategy_deploy_deferred"] and not session["error"]
    assert b.launches == [101, 102] and b.stops == [101]
    assert b.key not in b.web.QMT_COMPONENT_JOBS


def test_missing_key_after_login_stops_before_second_launch(bootstrap, monkeypatch):
    b = bootstrap
    def stop(*a, **k):
        b.running[0] = False
        return {"exit_confirmed": True}
    monkeypatch.setattr(b.web, "_qmt_bootstrap_graceful_exit", stop)
    b.web.qmt_auto_login_apply_for_account(b.row)
    b.work()
    session = b.web._qmt_auto_login_saved_session(b.row)
    assert session["strategy_bootstrap_phase"] == "error"
    assert "资金账号和账户类型" in session["strategy_bootstrap_error"]
    assert b.launches == [101] and not b.queued


@pytest.mark.parametrize("outcome", ["credential_error", "challenge", "component_error"])
def test_failed_login_does_not_close_or_restart(bootstrap, monkeypatch, outcome):
    import cfquant.qmt_component_login as component
    b = bootstrap
    monkeypatch.setattr(component, "login_running_qmt",
                        lambda *a, **k: {"outcome": outcome, "login_succeeded": False})
    b.web.qmt_auto_login_apply_for_account(b.row)
    b.work()
    assert b.web._qmt_auto_login_saved_session(b.row)["strategy_bootstrap_phase"] == "error"
    assert b.launches == [101] and not b.stops


def test_disabling_automation_cancels_bootstrap(bootstrap):
    b = bootstrap
    b.web.qmt_auto_login_apply_for_account(b.row)
    b.web.qmt_auto_login_apply_for_account(b.row, {"enabled": False})
    b.work()
    assert b.launches == [101] and not b.stops
    assert b.web._qmt_auto_login_saved_session(b.row)["state"] == "disabled"


def test_runtime_installer_owns_its_bootstrap(bootstrap):
    b = bootstrap
    result = b.web.qmt_auto_login_apply_for_account(b.row, reason="python-runtime-bootstrap-first")
    assert result["strategy_deploy_deferred"] and not result["strategy_bootstrap_phase"]
    b.work()
    assert b.launches == [101] and not b.stops


def test_late_compatibility_fallback_shows_manual_instructions(bootstrap, monkeypatch):
    import cfquant.qmt_component_login as component
    from cfquant.qmt_native_worker import QmtLoginUnsupported
    b = bootstrap
    def unsupported(*a, **k):
        raise QmtLoginUnsupported("unsupported test version")
    monkeypatch.setattr(component, "login_running_qmt", unsupported)
    b.web.qmt_auto_login_apply_for_account(b.row)
    b.work()
    session = b.web._qmt_auto_login_saved_session(b.row)
    assert not session["strategy_bootstrap_phase"] and session["login_degraded"]
    assert "正常退出后在绑定页面重新启动" in session["message"]
    assert b.launches == [101] and not b.stops


def test_existing_account_key_needs_only_one_launch(bootstrap):
    b = bootstrap
    b.row["qmt_strategy"]["account_keys"] = {"normal": ACCOUNT_KEY}
    job = next(iter(b.manager.jobs.values()))
    job["roles"][0]["account_key"] = ACCOUNT_KEY
    result = b.web.qmt_auto_login_apply_for_account(b.row)
    assert not result["strategy_bootstrap_phase"] and not result["strategy_deploy_deferred"]
    b.work()
    assert b.launches == [101] and not b.stops


@pytest.mark.parametrize("case", ["exited", "timeout", "changed", "cancelled"])
def test_graceful_exit_requires_exact_process_and_never_force_kills(web_config, monkeypatch, case):
    from cfquant import qmt_native_worker as native
    web, _ = web_config
    pids, calls = [101], []
    monkeypatch.setattr(web, "_qmt_auto_login_processes", lambda *a, **k: [{"pid": pid} for pid in pids])
    monkeypatch.setattr(web, "_qmt_auto_login_stop_xtitclient", lambda *a, **k: pytest.fail("no force-kill"))
    def request(account):
        assert account == "test-login"
        calls.append("request")
        if case == "exited":
            pids.clear()
        elif case == "changed":
            pids[:] = [202]
    backend = SimpleNamespace(request_exit=request, confirm_exit=lambda: None, close=lambda: calls.append("release"))
    monkeypatch.setattr(native, "IsolatedLoginBackend", lambda *a, **k: backend)
    args = ({"qmt_auto_login": {"login_account": "test-login"}}, {"bin_dir": "fake"}, 101)
    if case == "exited":
        assert web._qmt_bootstrap_graceful_exit(*args)["graceful"]
    else:
        with pytest.raises(RuntimeError):
            web._qmt_bootstrap_graceful_exit(*args, timeout=0 if case == "timeout" else 1,
                                            should_cancel=lambda: case == "cancelled")
    assert calls == ([] if case == "cancelled" else ["request", "release"])
