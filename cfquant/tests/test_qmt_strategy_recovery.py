"""Recovery policy tests use synthetic bindings and never attach to a terminal."""
import copy
import threading

import pytest

from cfquant.qmt_strategy_deploy import normalize_strategy_settings
from cfquant.qmt_strategy_recovery import (
    QmtStrategyRecovery, QmtStrategyRecoveryScheduler, QtStrategyBackend,
    RecoveryJournal, UnsupportedQmt, expected_models, confirm_recovery_bridge,
)


@pytest.fixture
def recovery_case(tmp_path):
    root = tmp_path / "terminal"
    (root / "bin.x64").mkdir(parents=True)
    settings = normalize_strategy_settings(dict(enabled=True, autorun=True, live=True))
    row = dict(account_key="binding", account_id="TEST001", enabled=True, mode="lite",
               qmt_dir=str(root), qmt_strategy=settings)
    accounts = {"binding": row}
    job = dict(account_key="binding", account_id="TEST001", enabled=True, mode="lite",
               root=str(root), settings=copy.deepcopy(settings), generation="g1", roles=[{
                   "name": "CFQ_TEST001_LITE", "role": "normal", "model_id": "7",
                   "model_prepared": True, "resolved_account_key": "test-account-key",
                   "control_sync": {"pid": 123, "state": "running", "last_success_at": 1000},
               }])
    calls, now = [], [1000]

    class Backend:
        pid = 123
        running = False
        outcome = {"outcome": "start_requested", "requested": True}
        def snapshot(self):
            return {"models": copy.deepcopy(self.models), "whitelist_ready": True}
        def start_strategy(self, expected):
            calls.append(expected)
            return self.outcome
        def close(self):
            self.closed = True
        def notices(self):
            return []

    backend = Backend()
    backend.models = [dict(expected_models(job, accounts)[0], running=False),
                      dict(name="USER_STRATEGY", running=False),
                      dict(name="CFQ_TEST001_CTYPES", running=False)]
    controller = QmtStrategyRecovery(lambda: accounts, backend_factory=lambda root: backend, clock=lambda: now[0],
                                    event_sink=lambda event: None, notice_probe=lambda *a: False)
    return controller, backend, calls, now, job, accounts


def test_only_stopped_bound_mode_is_requested(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    result = recovery(job)
    assert result["state"] == "start_requested"
    assert [row["name"] for row in calls] == ["CFQ_TEST001_LITE"]
    assert backend.closed
    backend.models[0]["running"] = True
    now[0] += 20
    assert recovery(job)["state"] == "running"
    assert len(calls) == 1


@pytest.mark.parametrize("incompatible", [False, True])
def test_native_crash_degrades_recovery_and_popup_does_not_cause_crash_loop(recovery_case, incompatible):
    from cfquant.qmt_native_worker import QmtAutomationError
    from cfquant.qmt_dependencies import QmtDependencyError
    recovery, backend, calls, now, job, accounts = recovery_case
    attaches = []
    def crash(root):
        attaches.append(root)
        raise (QmtDependencyError if incompatible else QmtAutomationError)("native worker unavailable")
    recovery.backend_factory = crash
    recovery.notice_probe = lambda *a: [123]
    assert recovery(job)["state"] == "unavailable"
    now[0] += 1
    recovery(job)
    assert len(attaches) == 1
    now[0] += 60
    recovery(job)
    assert len(attaches) == 2 and not calls


@pytest.mark.parametrize("change", ["account", "mode", "root", "disabled", "manual", "removed", "pending_import", "old_generation"])
def test_ineligible_bindings_never_attach(recovery_case, change):
    recovery, backend, calls, now, job, accounts = recovery_case
    row = accounts["binding"]
    if change == "account": row["account_id"] = "OTHER"
    if change == "mode": row["mode"] = "ctypes"
    if change == "root": row["qmt_dir"] += "-other"
    if change == "disabled": row["enabled"] = False
    if change == "manual": row["qmt_strategy"]["autorun"] = False
    if change == "removed": accounts.clear()
    if change == "pending_import": job["roles"][0]["reimport_required"] = True
    if change == "old_generation": job["control_generation"] = "previous"
    recovery.backend_factory = lambda root: pytest.fail("must not attach")
    assert recovery(job)["state"] == "ineligible"
    assert not calls


@pytest.fixture
def notice_case(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    events, actions = [], []
    notice = {"hwnd": "456", "text": "[防外接] Python进程访问了网络地址 [192.0.2.1]，策略运行中止！"}
    visible = [True]
    backend.notices = lambda: [notice] if visible[0] else []
    def dismiss(found, expected):
        assert events[-1]["event"] == "illegal_ip_detected"  # Journal precedes dismissal.
        actions.append("dismiss")
        visible[0] = False
        return {"closed": True, "outcome": "closed"}
    backend.dismiss_notice = dismiss
    recovery.event_sink = events.append
    recovery.bridge_verifier = lambda job, pid: True
    return recovery_case, events, actions, visible


def test_popup_close_and_submission_are_not_success_until_bridge_confirmed(notice_case):
    (recovery, backend, calls, now, job, accounts), events, actions, visible = notice_case
    recovery.bridge_verifier = lambda job, pid: False
    result = recovery(job)
    assert result["incident"]["dismissed"] and not result["incident"].get("handled")
    assert actions == ["dismiss"] and len(calls) == 1
    backend.models[0]["running"] = True
    now[0] += 1
    recovery(job)
    assert not any(e["event"] == "illegal_ip_handled" for e in events)
    recovery.bridge_verifier = lambda job, pid: True
    now[0] += 1
    assert recovery(job)["incident"]["handled"]
    now[0] += 20
    recovery(job)
    assert [e["event"] for e in events].count("illegal_ip_handled") == 1
    assert len({e["event_id"] for e in events}) == 1


def test_warning_closure_refused_after_message_changed(notice_case):
    (recovery, backend, calls, now, job, accounts), events, actions, visible = notice_case
    backend.models[0]["running"] = True
    backend.dismiss_notice = lambda *a: {"closed": False, "outcome": "message_changed"}
    result = recovery(job)
    assert not result["incident"]["dismissed"]
    assert not result["incident"].get("handled")
    assert not any(e["event"] == "illegal_ip_handled" for e in events)


def test_detection_journal_failure_preserves_popup_and_retries_recording(notice_case):
    (recovery, backend, calls, now, job, accounts), events, actions, visible = notice_case
    def fail(event):
        raise OSError("disk full")
    recovery.event_sink = fail
    assert recovery(job)["state"] == "unavailable"
    assert not calls and not actions and visible[0]
    now[0] += 60
    recovery.event_sink = events.append
    recovery(job)
    assert actions == ["dismiss"]
    assert events[0]["event"] == "illegal_ip_detected"


def test_binding_change_during_notice_scan_prevents_dismissal(notice_case):
    (recovery, backend, calls, now, job, accounts), events, actions, visible = notice_case
    previous = backend.notices
    def scan():
        accounts["binding"]["enabled"] = False
        return previous()
    backend.notices = scan
    assert recovery(job)["state"] == "unavailable"
    assert not actions and not calls and not events


def test_inspection_never_dismisses_or_logs_warning(notice_case):
    (recovery, backend, calls, now, job, accounts), events, actions, visible = notice_case
    recovery(job, inspect_only=True)
    assert not actions and not calls and not events


def test_popup_detection_bypasses_twenty_second_native_poll_delay(notice_case):
    (recovery, backend, calls, now, job, accounts), events, actions, visible = notice_case
    job["recovery"] = dict(pid=123, main_hwnd=456, generation="g1", next_check_at=now[0] + 20)
    recovery.notice_probe = lambda *a: [789]
    recovery(job)
    assert actions == ["dismiss"]


def test_journal_appends_utf8_and_event_identity(tmp_path):
    import json
    journal = RecoveryJournal(tmp_path)
    journal({"event": "illegal_ip_detected", "event_id": "one", "message": "非法 IP 告警"})
    journal({"event": "illegal_ip_handled", "event_id": "one", "message": "处理成功"})
    lines = next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [event["message"] for event in events] == ["非法 IP 告警", "处理成功"]
    assert all(event["timestamp"] and event["event_id"] == "one" for event in events)


@pytest.mark.parametrize("mismatch", ["pid", "generation", "role", "runtime_key", "state", None])
def test_bridge_confirmation_requires_current_process_and_scope(recovery_case, monkeypatch, mismatch):
    import cfquant.qmt_strategy_recovery as module
    from cfquant.qmt_strategy_deploy import _digest
    import os
    recovery, backend, calls, now, job, accounts = recovery_case
    job["roles"][0]["identity"] = {}
    reply = dict(pid=123, generation="g1", role="normal", state="running",
                 runtime_key=_digest([os.path.normcase(job["root"]), job["account_id"]])[:24])
    if mismatch:
        reply[mismatch] = "different"
    closed = []
    class Pipe:
        def __call__(self, *a): return reply
        def close(self): closed.append(True)
    monkeypatch.setattr(module, "PipeStrategyController", Pipe)
    assert confirm_recovery_bridge(job, 123) is (mismatch is None)
    assert closed == [True]


@pytest.mark.parametrize("field", ["id", "account", "m_strAccountKey", "runMode", "startupAutorun", "stock", "peroid"])
def test_native_identity_mismatch_prevents_start(recovery_case, field):
    recovery, backend, calls, now, job, accounts = recovery_case
    backend.models[0][field] = "different"
    assert recovery(job)["state"] == "unavailable"
    assert not calls


def test_duplicate_name_prevents_start(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    backend.models.append(copy.deepcopy(backend.models[0]))
    assert recovery(job)["state"] == "unavailable"
    assert not calls


def test_binding_changed_during_attach_prevents_start(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    def attach(root):
        accounts["binding"]["mode"] = "ctypes"
        return backend
    recovery.backend_factory = attach
    assert recovery(job)["state"] == "binding_changed"
    assert not calls


def test_replaced_deployment_prevents_start(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    current = [True]
    recovery.job_is_current = lambda job: current[0]
    snapshot = backend.snapshot
    def replaced():
        current[0] = False
        return snapshot()
    backend.snapshot = replaced
    assert recovery(job)["state"] == "binding_changed"
    assert not calls


def test_running_model_with_dead_pipe_is_not_duplicated(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    backend.models[0]["running"] = True
    job["roles"][0]["control_sync"] = {}
    result = recovery(job)
    assert result["state"] == "running" and not result["bridge_confirmed"]
    assert not calls


def test_inspect_does_not_start(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    assert recovery(job, inspect_only=True)["state"] == "stopped"
    assert not calls


def test_backoff_and_limit_survive_controller_recreation(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    for attempt in range(5):
        assert recovery(job)["state"] == "start_requested"
        now[0] += 20
        assert recovery(job)["state"] == ("retry_exhausted" if attempt == 4 else "backoff")
        now[0] = job["recovery"]["retry_after"]
        recovery = QmtStrategyRecovery(lambda: accounts, backend_factory=lambda root: backend, clock=lambda: now[0],
                                      event_sink=lambda event: None, notice_probe=lambda *a: False)
    assert recovery(job)["state"] == "retry_exhausted"
    assert len(calls) == 5
    backend.pid = 456
    now[0] += 20
    assert recovery(job)["state"] == "start_requested"
    assert len(calls) == 6


def test_ambiguous_native_error_does_not_immediately_retry(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    def timeout(expected):
        calls.append(expected)
        raise TimeoutError("reply lost")
    backend.start_strategy = timeout
    assert recovery(job)["state"] == "unavailable"
    now[0] += 20
    recovery(job)
    assert len(calls) == 1
    assert job["recovery"]["attempts"] == {"CFQ_TEST001_LITE": 1}


def test_whitelist_not_ready_does_not_consume_retries(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    backend.outcome = {"outcome": "waiting_whitelist", "requested": False}
    for _ in range(6):
        assert recovery(job)["state"] == "waiting_whitelist"
        now[0] += 20
    assert job["recovery"]["attempts"] == {"CFQ_TEST001_LITE": 0}


@pytest.mark.parametrize('can_query', [True, False])
def test_backend_uses_live_capabilities_instead_of_file_hash(tmp_path, monkeypatch, can_query):
    from types import SimpleNamespace
    from cfquant.qmt_component_login import QtLoginBackend
    directory = tmp_path / "bin.x64"
    directory.mkdir()
    (directory / "Formula.dll").write_bytes(b"another broker or version")
    closed = []
    def attach(self, directory, *, agent_extension, strategy):
        assert strategy and 'strategycapabilities' in agent_extension
        self.api = SimpleNamespace(strategycapabilities=lambda: {
            'can_query': can_query, 'can_read_notices': False, 'missing_query': [] if can_query else ['isFomrulaRun']})
    monkeypatch.setattr(QtLoginBackend, '__init__', attach)
    monkeypatch.setattr(QtLoginBackend, 'already_logged_in', lambda self: True)
    monkeypatch.setattr(QtLoginBackend, 'close', lambda self: closed.append(True))
    if can_query:
        backend = QtStrategyBackend(tmp_path)
        assert backend.notices() == []
        assert not closed
        backend.close()
    else:
        with pytest.raises(UnsupportedQmt, match='isFomrulaRun'):
            QtStrategyBackend(tmp_path)
    assert closed == [True]


@pytest.mark.parametrize('running', [True, False])
@pytest.mark.parametrize('inspect_only', [True, False])
def test_query_continues_without_start_api_or_retry_consumption(recovery_case, running, inspect_only):
    recovery, backend, calls, now, job, accounts = recovery_case
    backend.models[0]['running'] = running
    snapshot = backend.snapshot
    backend.snapshot = lambda: dict(snapshot(), capabilities={'can_query': True, 'can_start': False})
    for _ in range(2):
        result = recovery(job, inspect_only=inspect_only)
        assert result['state'] == ('running' if running else 'stopped' if inspect_only else 'detection_only')
        assert result['strategies'][0]['running'] is running
        assert not result.get('attempts') and not result.get('retry_after')
        assert not calls
        now[0] += 20


def test_optional_notice_scan_failure_does_not_disable_strategy_detection(recovery_case):
    recovery, backend, calls, now, job, accounts = recovery_case
    backend.models[0]['running'] = True
    backend.notices = lambda: (_ for _ in ()).throw(RuntimeError('message layout unavailable'))
    result = recovery(job)
    assert result['state'] == 'running' and result['notice_error'] == 'message layout unavailable'
    assert not calls


def test_detection_only_is_visible_to_user(recovery_case, tmp_path):
    from types import SimpleNamespace
    recovery, backend, calls, now, job, accounts = recovery_case
    manager = SimpleNamespace(lock=threading.RLock(), jobs={'one': job})
    scheduler = QmtStrategyRecoveryScheduler(manager, lambda: accounts, tmp_path / 'status.json')
    import time
    scheduler.states = {'one': dict(state='detection_only', generation='g1', last_checked_at=time.time())}
    status = scheduler.decorate('binding', {'targets': [{'root': job['root'], 'state': 'waiting_start'}]})
    assert status['targets'][0]['state'] == 'waiting_manual_start'
    assert '手动启动' in status['targets'][0]['message']


def test_scheduler_rechecks_live_job_after_snapshot(recovery_case, tmp_path):
    from types import SimpleNamespace
    recovery, backend, calls, now, job, accounts = recovery_case
    manager = SimpleNamespace(lock=threading.RLock(), jobs={"one": job})
    scheduler = QmtStrategyRecoveryScheduler(manager, lambda: accounts, tmp_path / "status.json")
    original = backend.snapshot
    def snapshot():
        manager.jobs["one"]["generation"] = "new-generation"
        return original()
    backend.snapshot = snapshot
    scheduler.recovery.backend_factory = lambda root: backend
    scheduler.run_once()
    assert scheduler.states["one"]["state"] == "binding_changed"
    assert not calls
