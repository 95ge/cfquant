"""Unknown Qt must not prevent launch or trigger repeated credential entry."""
import copy
import threading
from types import SimpleNamespace

import pytest

from cfquant.tests.test_qmt_strategy_web import web_config
from cfquant.qmt_credentials import QmtCredentialStore
from cfquant.qmt_native_worker import QmtAutomationError, QmtLoginUnsupported


@pytest.fixture
def startup(web_config, monkeypatch, tmp_path):
    web, config = web_config
    monkeypatch.setenv('CFQUANT_QMT_AUTO_START', 'saved')
    monkeypatch.setattr(web, 'QMT_AUTO_LOGIN_STATE_FILE', str(tmp_path/'sessions.json'))
    monkeypatch.setattr(web, 'QMT_COMPONENT_JOBS', {})
    paths = {'bin_dir':str(tmp_path/'QMT'), 'exe_path':'fixture.exe'}
    row = {'account_id':'fixture', 'qmt_dir':paths['bin_dir'], 'qmt_auto_login':{
        'enabled':True, 'auto_fill_credentials':True, 'login_account':'fixture-login',
        'auto_update':True, 'restart_times':['09:00']}}
    running, calls = [], []
    monkeypatch.setattr(web, '_qmt_auto_login_paths', lambda _: paths)
    monkeypatch.setattr(web, '_qmt_auto_login_processes', lambda *a, **k: list(running))
    def stop(*a, **k):
        calls.append('stop')
        running.clear()
        return {}
    def start(*a, **k):
        calls.append('start')
        running.append({'pid':456})
        return {'pid':456}
    monkeypatch.setattr(web, '_qmt_auto_login_stop_xtitclient', stop)
    monkeypatch.setattr(web, '_qmt_auto_login_start_xtitclient', start)
    monkeypatch.setattr(web, 'QMT_STRATEGIES', SimpleNamespace(prepare_for_start=lambda _: {}))
    monkeypatch.setattr(web, '_qmt_queue_component_login', lambda row, paths, pid: calls.append(('queue', paths, pid)))
    def preflight(*a):
        raise QmtLoginUnsupported('Qt 5.15.3 not validated')
    monkeypatch.setattr(web, '_qmt_component_login_preflight', preflight)
    return web, config, row, paths, running, calls


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('restart', [False, True])
def test_unsupported_qt_starts_or_keeps_terminal_and_preserves_preferences(startup, existing, restart):
    web, config, row, paths, running, calls = startup
    if existing:
        running.append({'pid':123})
    original = copy.deepcopy(row)
    result = web.qmt_auto_login_apply_for_account(row, restart=restart)
    assert result['configured'] and not result.get('error')
    assert result['login_state'] == 'manual_login_required'
    assert result['auto_fill_credentials'] and not result['effective_auto_fill_credentials']
    assert result['login_degraded'] and not result['login_succeeded']
    assert result['restarted'] == restart
    assert row == original
    actions = [call for call in calls if isinstance(call, str)]
    assert actions == (['stop', 'start'] if restart else [] if existing else ['start'])
    assert calls[-1][0] == 'queue'
    assert calls[-1][1]['login_compatibility_warning']
    session = web._qmt_auto_login_saved_session(row)
    assert session['auto_fill_credentials'] and session['restart_times'] == ['09:00']
    assert session['pid'] == (123 if existing and not restart else 456)
    assert not session['error'] and '手动登录' in session['message']


def test_duplicate_manual_request_keeps_worker_and_process(startup):
    web, _, row, paths, running, calls = startup
    running.append({'pid':123})
    web._qmt_auto_login_update_session(row, dict(web._qmt_manual_login_status('Qt 5.15.3'), pid=123))
    key = web._qmt_component_job_key(paths['bin_dir'])
    job = SimpleNamespace(is_alive=lambda: True, qmt_pid=123)
    web.QMT_COMPONENT_JOBS[key] = job
    result = web.qmt_auto_login_apply_for_account(row)
    assert result['login_state'] == 'manual_login_required' and result['pid'] == 123
    assert calls == [] and web.QMT_COMPONENT_JOBS[key] is job


def test_new_incompatibility_cancels_prior_login_without_restarting_terminal(startup):
    web, _, row, paths, running, calls = startup
    running.append({'pid':123})
    key = web._qmt_component_job_key(paths['bin_dir'])
    web.QMT_COMPONENT_JOBS[key] = SimpleNamespace(is_alive=lambda: True, qmt_pid=123)
    web._qmt_auto_login_update_session(row, {'pid':123, 'login_state':'logging_in'})
    result = web.qmt_auto_login_apply_for_account(row)
    assert result['login_state'] == 'manual_login_required'
    assert key not in web.QMT_COMPONENT_JOBS
    assert len(calls) == 1 and calls[0][0] == 'queue' and calls[0][2] == 123


def test_component_corruption_still_blocks_restart(startup, monkeypatch):
    web, _, row, _, running, calls = startup
    running.append({'pid':123})
    def preflight(*a):
        raise QmtAutomationError('mixed Qt DLL versions')
    monkeypatch.setattr(web, '_qmt_component_login_preflight', preflight)
    result = web.qmt_auto_login_apply_for_account(row, restart=True)
    assert not result['configured'] and 'mixed Qt' in result['error']
    assert calls == [] and running == [{'pid':123}]
    assert not web._qmt_auto_login_saved_session(row)['login_degraded']


def test_compatible_version_recovers_on_next_start(startup, monkeypatch):
    web, _, row, _, _, calls = startup
    web.qmt_auto_login_apply_for_account(row)
    calls.clear()
    monkeypatch.setattr(web, '_qmt_component_login_preflight', lambda *a: None)
    result = web.qmt_auto_login_apply_for_account(row)
    assert result['login_state'] == 'logging_in'
    session = web._qmt_auto_login_saved_session(row)
    assert session['effective_auto_fill_credentials'] and not session['login_degraded']
    assert session['compatibility_warning'] == ''
    assert calls[:2] == ['stop', 'start']


def test_launch_failure_during_fallback_remains_an_error(startup, monkeypatch):
    web, _, row, _, _, _ = startup
    def start(*a, **k):
        raise OSError('fixture launch failed')
    monkeypatch.setattr(web, '_qmt_auto_login_start_xtitclient', start)
    result = web.qmt_auto_login_apply_for_account(row)
    assert not result['configured'] and 'fixture launch failed' in result['error']
    assert result['login_state'] == 'component_unavailable'
    assert not result['login_degraded'] and not result['effective_auto_fill_credentials']


def test_disabling_automation_clears_manual_runtime_state(startup):
    web, _, row, _, _, _ = startup
    web.qmt_auto_login_apply_for_account(row)
    result = web.qmt_auto_login_apply_for_account(row, {'enabled':False})
    assert not result['effective_auto_fill_credentials']
    session = web._qmt_auto_login_saved_session(row)
    assert session['login_state'] == 'disabled'
    assert not session['login_degraded'] and not session['compatibility_warning']


@pytest.mark.parametrize('preflight_degraded', [False, True])
@pytest.mark.parametrize('new_pid', [False, True])
def test_worker_does_not_retry_same_pid_or_read_password_and_rechecks_after_update(
        startup, monkeypatch, preflight_degraded, new_pid):
    from cfquant import qmt_component_login as component, qmt_update
    web, config, row, paths, _, _ = startup
    key = web._qmt_component_job_key(paths['bin_dir'])
    web.QMT_COMPONENT_JOBS[key] = threading.current_thread()
    web._qmt_auto_login_update_session(row, {'pid':456})
    if preflight_degraded:
        paths['login_compatibility_warning'] = 'Qt 5.15.3 not validated'
    monkeypatch.setattr(QmtCredentialStore, 'password', lambda *a: pytest.fail('must not read password'))
    attempts = []
    def login(*a, expected_pid, **k):
        attempts.append(expected_pid)
        if expected_pid == 456:
            raise QmtLoginUnsupported('Qt 5.15.3 not validated')
        return {'outcome':'already_logged_in', 'login_succeeded':True, 'attempts':[]}
    monkeypatch.setattr(component, 'login_running_qmt', login)
    def manage(directory, pid, login, *, on_wait, on_pid, **kwargs):
        result = login(pid, lambda: None)
        assert result['outcome'] == 'manual_login_required'
        # Even if the supervisor asks twice, native login must not run twice.
        assert login(pid, lambda: None) == result
        on_wait('update_background')
        assert web._qmt_auto_login_saved_session(row)['login_state'] == 'manual_login_required'
        if new_pid:
            on_pid(789)
            result = login(789, lambda: None)
        return result
    monkeypatch.setattr(qmt_update, 'manage_qmt_startup', manage)
    web._qmt_component_login_worker(row, paths, 456, config.path)
    assert attempts == ([] if preflight_degraded else [456]) + ([789] if new_pid else [])
    session = web._qmt_auto_login_saved_session(row)
    assert session['login_succeeded'] == new_pid
    assert session['login_degraded'] != new_pid
    assert not session['error'] and key not in web.QMT_COMPONENT_JOBS


@pytest.mark.parametrize('updated', [False, True])
def test_supervisor_observes_late_updates_without_repeating_manual_login(monkeypatch, updated):
    from cfquant import qmt_update as update
    clock = [0.0]
    monkeypatch.setattr(update.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(update.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    processes = SimpleNamespace(pid=456)
    monkeypatch.setattr(update, 'UpdateProcesses', lambda *a: processes)
    class Monitor:
        active = False
        updates = 0
        def __init__(self, *a):
            pass
        def before_poll(self):
            if updated and clock[0] >= 5 and not self.updates:
                self.updates += 1
                processes.pid = 789
                raise update.QmtUpdated()
    monkeypatch.setattr(update, 'UpdateMonitor', Monitor)
    attempts = []
    def login(pid, poll):
        attempts.append(pid)
        return {'outcome':'manual_login_required', 'login_succeeded':False}
    result = update.manage_qmt_startup('fixture', 456, login)
    assert result['outcome'] == 'manual_login_required'
    assert attempts == ([456, 789] if updated else [456])
    assert clock[0] >= 90 and result['update_count'] == int(updated)
