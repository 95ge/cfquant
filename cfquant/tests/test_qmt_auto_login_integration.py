"""Trading-day restart policy, credential isolation and login orchestration."""
import datetime
import json
import time
import threading
from types import SimpleNamespace

import pytest

from cfquant.tests.test_qmt_strategy_web import web_config, login_credentials
from cfquant.tests.test_management import service
from cfquant.qmt_credentials import QmtCredentialStore
from cfquant.trading_calendar import is_trading_day


@pytest.fixture
def scheduler(web_config, monkeypatch, tmp_path):
    web, config = web_config
    monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "saved")
    monkeypatch.setattr(web, "QMT_AUTO_LOGIN_STATE_FILE", str(tmp_path / "schedule.json"))
    monkeypatch.setattr(web, "QMT_COMPONENT_JOBS", {})
    row = {"account_key": "test", "account_id": "synthetic", "qmt_dir": str(tmp_path / "QMT"),
           "enabled": True, "qmt_auto_login": {"enabled": True, "restart_times": ["09:00"]}}
    config._data["account_configs"] = {"test": row}
    calls = []
    monkeypatch.setattr(web, "qmt_auto_login_restart_for_account",
                        lambda r, settings, reason: calls.append((r["account_key"], reason)) or {"restarted": True})
    return web, config, calls


def at(day, clock="09:00:00"):
    return time.strptime(day + " " + clock, "%Y-%m-%d %H:%M:%S")


def test_weekend_and_holiday_skip_then_first_session_runs(scheduler):
    web, _, calls = scheduler
    job = web.QmtAutoLoginRestartScheduler()
    assert job.run_pending(at("2026-10-01")) == []
    assert job.run_pending(at("2026-10-04")) == []
    assert job.run_pending(at("2026-10-07")) == []
    assert job.run_pending(at("2026-10-08")) == [{"restarted": True}]
    assert calls == [("test", "scheduled:09:00")]


def test_schedule_deduplicates_directory_across_bindings_and_web_restarts(scheduler):
    web, config, calls = scheduler
    original = config._data["account_configs"]["test"]
    config._data["account_configs"]["other"] = dict(original, account_key="other", qmt_dir=original["qmt_dir"] + "/bin.x64")
    assert len(web.QmtAutoLoginRestartScheduler().run_pending(at("2026-10-19"))) == 1
    assert web.QmtAutoLoginRestartScheduler().run_pending(at("2026-10-19", "09:02:00")) == []
    assert len(calls) == 1


def test_failed_login_on_previous_day_does_not_block_next_trading_day(scheduler, monkeypatch):
    web, _, calls = scheduler
    def fail(row, settings, reason):
        calls.append(reason)
        raise RuntimeError("network failure")
    monkeypatch.setattr(web, "qmt_auto_login_restart_for_account", fail)
    job = web.QmtAutoLoginRestartScheduler()
    assert job.run_pending(at("2026-10-16"))[0]["error"]
    assert job.run_pending(at("2026-10-17")) == []
    assert job.run_pending(at("2026-10-19"))[0]["error"]
    assert len(calls) == 2


def test_catchup_is_bounded_and_disabled_bindings_do_not_restart(scheduler):
    web, config, calls = scheduler
    assert web.QmtAutoLoginRestartScheduler().run_pending(at("2026-10-19", "12:00:00")) == []
    config._data["account_configs"]["test"]["enabled"] = False
    assert web.QmtAutoLoginRestartScheduler().run_pending(at("2026-10-19")) == []
    config._data["account_configs"]["test"]["enabled"] = True
    assert len(web.QmtAutoLoginRestartScheduler().run_pending(at("2026-10-19", "09:04:00"))) == 1
    assert len(calls) == 1


def test_calendar_failure_never_kills_a_process(scheduler, monkeypatch):
    import cfquant.trading_calendar as calendar
    web, _, calls = scheduler
    monkeypatch.setattr(calendar, "is_trading_day", lambda day: (_ for _ in ()).throw(ValueError("outdated calendar")))
    with pytest.raises(ValueError, match="outdated"):
        web.QmtAutoLoginRestartScheduler().run_pending(at("2026-10-19"))
    assert calls == []


def test_china_calendar_does_not_treat_makeup_saturday_as_trading_day():
    assert not is_trading_day(datetime.date(2026, 10, 10))
    assert is_trading_day(datetime.date(2026, 10, 8))


def test_saved_password_is_encrypted_not_in_config_or_public_state(web_config, monkeypatch, tmp_path):
    import cfquant.qmt_credentials as credentials
    web, config = web_config
    monkeypatch.setattr(credentials, "_protect", lambda value, entropy: b"opaque-test-ciphertext")
    monkeypatch.setattr(credentials, "_unprotect", lambda value, entropy: b"synthetic-test-secret")
    options = {"enabled": True, "login_account": "test-login", "password": "synthetic-test-secret"}
    row = config.save_account_config("test-fund", qmt_dir=str(tmp_path / "QMT"), qmt_auto_login=options)
    assert row["qmt_auto_login"]["password_saved"]
    assert row["qmt_auto_login"]["restart_times"] == ["09:00"]
    for value in (row, config.snapshot(), config.account_configs(), config.setup_info()):
        assert "synthetic-test-secret" not in json.dumps(value)
        assert '"password"' not in json.dumps(value)
    assert "synthetic-test-secret" not in open(config.path, encoding="utf-8").read()
    store = QmtCredentialStore(config.path)
    assert "synthetic-test-secret" not in store.path.read_text(encoding="utf-8")
    assert store.password(str(tmp_path / "QMT/bin.x64"), "test-login") == "synthetic-test-secret"
    assert store.password(str(tmp_path / "QMT"), "different-login") == ""
    updated = config.save_account_config("test-fund", qmt_dir=str(tmp_path / "QMT"),
                                         qmt_auto_login={"login_account": "test-login", "password": ""})
    assert updated["qmt_auto_login"]["password_saved"]
    restored = web.WebRuntimeConfig(config.path, str(tmp_path / "reloaded.db"))
    assert restored.account_configs()[row["account_key"]]["qmt_auto_login"]["password_saved"]


def test_explicit_empty_schedule_stays_disabled(web_config, tmp_path, login_credentials):
    _, config = web_config
    row = config.save_account_config("test-fund", qmt_dir=str(tmp_path), qmt_auto_login={"enabled": True, "restart_times": [], **login_credentials})
    assert row["qmt_auto_login"]["restart_times"] == []


@pytest.mark.parametrize("settings,match", [
    (None, "登录账号"),
    ({"enabled": True, "password": "synthetic-secret"}, "登录账号"),
    ({"enabled": True, "login_account": "fixture-login"}, "登录密码"),
    ({"enabled": True, "login_account": "fixture-login", "password_saved": True}, "登录密码"),
    ({"enabled": True, "login_account": "fixture-login", "password": 123}, "字符串"),
])
def test_missing_credentials_cannot_save_or_change_config(web_config, tmp_path, settings, match):
    _, config = web_config
    before = config.snapshot()
    with pytest.raises(ValueError, match=match):
        config.save_account_config("test-fund", qmt_dir=str(tmp_path / "QMT"), qmt_auto_login=settings)
    assert config.snapshot() == before
    assert not QmtCredentialStore(config.path).path.exists()


@pytest.mark.parametrize("endpoint", ["save_account_runtime_config", "initialize_web_setup"])
def test_validation_precedes_process_stop_and_setup_changes(web_config, monkeypatch, tmp_path, endpoint):
    web, config = web_config
    monkeypatch.setattr(web, "qmt_process_preflight", lambda **kw: pytest.fail("invalid request reached process preflight"))
    before = config.snapshot()
    with pytest.raises(ValueError, match="登录密码"):
        getattr(web, endpoint)({"account_id": "test-fund", "qmt_dir": str(tmp_path), "auto_close_qmt": True,
            "qmt_auto_login": {"enabled": True, "login_account": "fixture-login", "password_saved": True}})
    assert config.snapshot() == before


@pytest.mark.parametrize("change", ["account", "directory", "deleted_secret"])
def test_saved_password_must_match_actual_account_and_directory(web_config, tmp_path, login_credentials, change):
    _, config = web_config
    directory = str(tmp_path / "QMT")
    row = config.save_account_config("test-fund", qmt_dir=directory, qmt_auto_login=login_credentials)
    settings = dict(row["qmt_auto_login"])
    if change == "account":
        settings["login_account"] = "other-login"
    elif change == "directory":
        directory = str(tmp_path / "OtherQMT")
    else:
        QmtCredentialStore(config.path).path.unlink()
    before = config.snapshot()
    with pytest.raises(ValueError, match="登录密码"):
        config.save_account_config("test-fund", qmt_dir=directory, qmt_auto_login=settings)
    assert config.snapshot() == before


def test_disabling_auto_restart_needs_no_credentials(web_config):
    _, config = web_config
    row = config.save_account_config("test-fund", qmt_auto_login={"enabled": False})
    assert row["qmt_auto_login"] == {"enabled": False, "restart_times": []}


def test_reenabling_auto_restart_defaults_to_nine(web_config, tmp_path, login_credentials):
    _, config = web_config
    config.save_account_config('test-fund', qmt_dir=str(tmp_path), qmt_auto_login={'enabled': False})
    row = config.save_account_config('test-fund', qmt_dir=str(tmp_path), qmt_auto_login=dict(login_credentials, enabled=True))
    assert row['qmt_auto_login']['restart_times'] == ['09:00']


def test_legacy_binding_cannot_restart_without_saved_credentials(web_config, monkeypatch, tmp_path):
    import cfquant.qmt_component_login as component
    web, _ = web_config
    monkeypatch.setattr(component, "verify_environment", lambda *args: pytest.fail("credentials must be checked first"))
    with pytest.raises(ValueError, match="登录密码"):
        web._qmt_component_login_preflight({"bin_dir": str(tmp_path)},
            {"enabled": True, "login_account": "fixture-login", "password_saved": True})


def test_saved_password_reveal_is_explicit_and_bound_to_saved_identity(web_config, tmp_path, login_credentials, monkeypatch):
    import cfquant.qmt_credentials as credentials
    web, config = web_config
    monkeypatch.setattr(credentials, "_unprotect", lambda value, entropy: b"synthetic-test-secret")
    row = config.save_account_config("test-fund", qmt_dir=str(tmp_path), qmt_auto_login=login_credentials)
    request = {"account_key": row["account_key"], "login_account": "fixture-login", "qmt_dir": str(tmp_path / "bin.x64")}
    assert web.reveal_account_qmt_password(request) == {"password": "synthetic-test-secret"}
    assert "synthetic-test-secret" not in json.dumps(config.snapshot())
    for changes in ({"login_account": "other-login"}, {"qmt_dir": str(tmp_path / "other")}, {"account_key": "missing"}):
        with pytest.raises(ValueError):
            web.reveal_account_qmt_password(dict(request, **changes))


def test_password_reveal_http_requires_auth_and_disables_caching(service, tmp_path, login_credentials, monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    import cfquant.qmt_credentials as credentials
    monkeypatch.setattr(credentials, "_unprotect", lambda value, entropy: b"synthetic-test-secret")
    service.config.set_api_key('fixture-api-key')
    row = service.config.save_account_config('fixture-fund', qmt_dir=str(tmp_path), qmt_auto_login=login_credentials)
    url = service.runtime.base_url + '/api/account-config/qmt-password'
    body = json.dumps({'account_key': row['account_key'], 'login_account': 'fixture-login', 'qmt_dir': str(tmp_path)}).encode()
    request = Request(url, data=body, headers={'Content-Type': 'application/json'})
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 401
    assert b'synthetic-test-secret' not in error.value.read()
    request.add_header('X-API-Key', 'fixture-api-key')
    with urlopen(request, timeout=5) as response:
        assert response.headers['Cache-Control'] == 'no-store'
        assert json.load(response)['data']['password'] == 'synthetic-test-secret'


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows DPAPI")
def test_real_dpapi_round_trip(tmp_path):
    store = QmtCredentialStore(tmp_path / "web.json")
    store.save(str(tmp_path / "QMT"), "fixture-user", "synthetic-credential")
    assert "synthetic-credential" not in store.path.read_text(encoding="utf-8")
    assert store.password(str(tmp_path / "QMT"), "fixture-user") == "synthetic-credential"


@pytest.mark.parametrize("old_process_remains", [False, True])
@pytest.mark.parametrize("active_job", [False, True])
@pytest.mark.parametrize("explicit_restart", [False, True])
def test_restart_stops_old_process_before_starting_and_queueing_login(web_config, monkeypatch, tmp_path, old_process_remains, active_job, explicit_restart):
    web, config = web_config
    monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "saved")
    monkeypatch.setattr(web, "QMT_COMPONENT_JOBS", {})
    monkeypatch.setattr(web, "QMT_AUTO_LOGIN_STATE_FILE", str(tmp_path / "sessions.json"))
    calls = []
    running = [{'pid': 123}]
    paths = {"bin_dir": str(tmp_path / "QMT/bin.x64"), "exe_path": "fixture.exe"}
    if active_job:
        web.QMT_COMPONENT_JOBS[web._qmt_component_job_key(paths['bin_dir'])] = SimpleNamespace(is_alive=lambda: True, qmt_pid=123)
    monkeypatch.setattr(web, "_qmt_auto_login_paths", lambda directory: paths)
    monkeypatch.setattr(web, "_qmt_component_login_preflight", lambda *args: None)
    def stop(*args, **kwargs):
        calls.append('stop')
        if not old_process_remains:
            running.clear()
        return {}
    monkeypatch.setattr(web, "_qmt_auto_login_stop_xtitclient", stop)
    monkeypatch.setattr(web, "_qmt_auto_login_processes", lambda directory, **kwargs: list(running))
    monkeypatch.setattr(web, "_qmt_auto_login_start_xtitclient", lambda *a, **k: calls.append("start") or {"pid": 456})
    monkeypatch.setattr(web, "_qmt_queue_component_login", lambda row, p, pid: calls.append(("login", pid)))
    row = {"account_id": "fixture", "qmt_dir": paths["bin_dir"], "qmt_auto_login": {"enabled": True}}
    result = web.qmt_auto_login_apply_for_account(row, restart=explicit_restart)
    if active_job and not explicit_restart:
        assert calls == []  # Duplicate startup waits; an explicit restart must terminate it.
        assert result['login_state'] == 'logging_in'
    elif old_process_remains:
        assert result["error"]
        assert calls == ["stop"]
    else:
        assert calls == ["stop", "start", ("login", 456)]
        assert result["login_state"] == "logging_in"


def test_worker_records_success_and_supplies_saved_password_only_on_request(web_config, monkeypatch, tmp_path):
    import cfquant.qmt_component_login as component
    web, config = web_config
    monkeypatch.setattr(web, "QMT_AUTO_LOGIN_STATE_FILE", str(tmp_path / "sessions.json"))
    row = {"account_id": "fixture", "qmt_auto_login": {"login_account": "fixture-login"}}
    monkeypatch.setattr(web, 'QMT_COMPONENT_JOBS', {web._qmt_component_job_key(str(tmp_path)): threading.current_thread()})
    web._qmt_auto_login_update_session(row, {"pid": 456})
    monkeypatch.setattr(QmtCredentialStore, "password", lambda *a: "synthetic-credential")
    def login(directory, account, password_provider, expected_pid):
        assert expected_pid == 456 and account == "fixture-login"
        assert password_provider() == "synthetic-credential"
        return {"outcome": "logged_in", "login_succeeded": True, "attempts": ["provided"]}
    monkeypatch.setattr(component, "login_running_qmt", login)
    web._qmt_component_login_worker(row, {"bin_dir": str(tmp_path)}, 456, config.path)
    state = web._qmt_auto_login_saved_session(row)
    assert state["login_succeeded"]
    assert "synthetic-credential" not in json.dumps(state)


def test_scheduled_restart_is_not_skipped_by_an_old_login_task(scheduler, monkeypatch):
    web, config, calls = scheduler
    row = config._data['account_configs']['test']
    job = SimpleNamespace(is_alive=lambda: True, qmt_pid=123)
    monkeypatch.setattr(web, 'QMT_COMPONENT_JOBS', {web._qmt_component_job_key(row['qmt_dir']): job})
    assert web.QmtAutoLoginRestartScheduler().run_pending(at('2026-10-19')) == [{'restarted': True}]
    assert calls == [('test', 'scheduled:09:00')]


def test_old_login_worker_cannot_clear_or_overwrite_a_new_job(web_config, monkeypatch, tmp_path):
    import cfquant.qmt_component_login as component
    web, config = web_config
    monkeypatch.setattr(web, 'QMT_AUTO_LOGIN_STATE_FILE', str(tmp_path / 'sessions.json'))
    key = web._qmt_component_job_key(str(tmp_path))
    new_job = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(web, 'QMT_COMPONENT_JOBS', {key: new_job})
    row = {'account_id': 'fixture'}
    web._qmt_auto_login_update_session(row, {'pid': 456, 'message': 'new login in progress'})
    monkeypatch.setattr(component, 'login_running_qmt', lambda *a, **kw: {'outcome': 'logged_in', 'login_succeeded': True})
    # Even if Windows reuses a PID, ownership of the job distinguishes the workers.
    web._qmt_component_login_worker(row, {'bin_dir': str(tmp_path)}, 456, config.path)
    assert web.QMT_COMPONENT_JOBS[key] is new_job
    assert web._qmt_auto_login_saved_session(row)['message'] == 'new login in progress'


def test_force_stop_targets_exact_directory_and_waits_for_exit(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    paths = {'bin_dir': str(tmp_path / 'target'), 'exe_path': str(tmp_path / 'target/XtItClient.exe')}
    target = SimpleNamespace(info={'pid': 123, 'name': 'XtItClient.exe'}, exe=lambda: paths['exe_path'])
    other = SimpleNamespace(info={'pid': 987, 'name': 'XtItClient.exe'}, exe=lambda: str(tmp_path / 'other/XtItClient.exe'))
    remaining = [target, other]
    monkeypatch.setattr(web, '_qmt_auto_login_paths', lambda directory: paths)
    monkeypatch.setattr(web.psutil, 'process_iter', lambda attrs: list(remaining))
    commands = []
    def terminate(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(web.subprocess, 'run', terminate)
    def sleep(_):
        assert commands  # Exit is asynchronous, after the termination request.
        remaining.remove(target)
    monkeypatch.setattr(web.time, 'sleep', sleep)
    result = web._qmt_auto_login_stop_xtitclient({}, paths, session={'pid': 987})
    assert result['exit_confirmed'] and result['requested_pids'] == [123]
    if web.os.name == 'nt':
        assert commands == [['taskkill', '/PID', '123', '/T', '/F']]
    assert remaining == [other]


def test_process_query_failure_aborts_restart_before_launch(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    monkeypatch.setenv('CFQUANT_QMT_AUTO_START', 'saved')
    monkeypatch.setattr(web, 'QMT_AUTO_LOGIN_STATE_FILE', str(tmp_path / 'sessions.json'))
    monkeypatch.setattr(web, '_qmt_component_login_preflight', lambda *a: None)
    monkeypatch.setattr(web, '_qmt_auto_login_paths', lambda directory: {'bin_dir': str(tmp_path), 'exe_path': 'fixture.exe'})
    def denied(*args, **kwargs):
        raise RuntimeError('cannot verify process exit')
    monkeypatch.setattr(web, '_qmt_auto_login_processes', denied)
    monkeypatch.setattr(web, '_qmt_auto_login_start_xtitclient', lambda *a, **kw: pytest.fail('must not launch'))
    result = web.qmt_auto_login_restart_for_account({'account_id': 'fixture', 'qmt_dir': str(tmp_path)})
    assert 'cannot verify process exit' in result['error']


def test_force_stop_times_out_if_process_does_not_exit(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    clock = [0.0]
    monkeypatch.setattr(web, 'time', SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)))
    monkeypatch.setattr(web, '_qmt_auto_login_processes', lambda *a, **kw: [{'pid': 123}])
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=5, stdout='', stderr='access denied'))
    with pytest.raises(RuntimeError, match='旧 QMT 进程未完全退出'):
        web._qmt_auto_login_stop_xtitclient({}, {'bin_dir': str(tmp_path)})
    assert 8 <= clock[0] < 9
