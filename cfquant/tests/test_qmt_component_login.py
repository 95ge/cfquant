"""Submission policy tests: no live credentials or trading-terminal dependencies."""
import pytest

from cfquant.qmt_component_login import auto_login


class Terminal:
    def __init__(self, saved=True, outcomes=("logged_in",), logged_in=False, notice=None, busy=False):
        self.saved = saved
        self.outcomes = iter(outcomes)
        self.logged_in = logged_in
        self.notice = notice
        self.busy = busy
        self.calls = []

    def already_logged_in(self):
        return self.logged_in

    def state(self):
        return dict(has_password=self.saved, login_enabled=self.saved, notice=self.notice, busy=self.busy)

    def fill(self, value):
        assert value == "synthetic-fixture"
        self.calls.append("fill")
        self.saved = True

    def submit(self):
        self.calls.append("submit")

    def wait_outcome(self):
        self.calls.append("wait")
        return next(self.outcomes)

    def acknowledge_failure(self):
        self.calls.append("acknowledge")


def no_password():
    pytest.fail("The password provider must not be called")


def test_remembered_password_is_replaced_before_submission():
    terminal = Terminal()
    result = auto_login(terminal, lambda: "synthetic-fixture")
    assert result == dict(outcome="logged_in", login_succeeded=True, attempts=["provided"], password_requested=True)
    assert terminal.calls == ["fill", "submit", "wait"]


def test_empty_password_is_filled_before_the_first_submission():
    terminal = Terminal(saved=False)
    result = auto_login(terminal, lambda: "synthetic-fixture")
    assert result["login_succeeded"]
    assert result["attempts"] == ["provided"]
    assert terminal.calls == ["fill", "submit", "wait"]


def test_rejected_saved_password_is_not_submitted_again():
    terminal = Terminal(outcomes=("credential_error", "logged_in"))
    result = auto_login(terminal, lambda: "synthetic-fixture")
    assert not result["login_succeeded"]
    assert result["attempts"] == ["provided"]
    assert terminal.calls == ["fill", "submit", "wait"]


def test_rejected_replacement_stops_without_second_submission():
    terminal = Terminal(outcomes=("credential_error", "credential_error"))
    result = auto_login(terminal, lambda: "synthetic-fixture")
    assert result["outcome"] == "credential_error"
    assert terminal.calls.count("submit") == 1


@pytest.mark.parametrize("outcome", ["timeout", "network_error", "challenge", "unrecognized_dialog"])
def test_uncertain_or_noncredential_failure_never_causes_a_second_submission(outcome):
    terminal = Terminal(outcomes=(outcome,))
    result = auto_login(terminal, lambda: "synthetic-fixture")
    assert result["outcome"] == outcome
    assert terminal.calls == ["fill", "submit", "wait"]


def test_already_logged_in_does_not_submit():
    terminal = Terminal(logged_in=True)
    result = auto_login(terminal, no_password)
    assert result["login_succeeded"]
    assert result["outcome"] == "already_logged_in"
    assert not terminal.calls


@pytest.mark.parametrize("notice", ["challenge", "network_error"])
def test_existing_notice_blocks_submission(notice):
    terminal = Terminal(notice=notice)
    assert auto_login(terminal, no_password)["outcome"] == notice
    assert not terminal.calls


def test_in_progress_login_never_requests_a_password():
    terminal = Terminal(saved=False, busy=True)
    assert auto_login(terminal, no_password)["outcome"] == "login_not_ready"
    assert not terminal.calls


def test_no_provided_password_leaves_empty_form_untouched():
    terminal = Terminal(saved=False)
    assert auto_login(terminal, lambda: "")["outcome"] == "password_required"
    assert not terminal.calls


def test_existing_password_error_is_replaced_without_resubmitting_bad_contents():
    terminal = Terminal(notice="credential_error")
    result = auto_login(terminal, lambda: "synthetic-fixture")
    assert result["attempts"] == ["provided"]
    assert terminal.calls == ["acknowledge", "fill", "submit", "wait"]


@pytest.mark.parametrize('remembered', [True, False])
def test_fresh_process_waits_for_login_components_without_relaunch(monkeypatch, tmp_path, remembered):
    import cfquant.qmt_component_login as component
    calls = []
    terminal = Terminal(saved=remembered)
    terminal.select_account = lambda account, replace=False: calls.append(("account", account, replace))
    terminal.close = lambda: calls.append("closed")
    def backend(directory, timeout, expected_pid, **kwargs):
        assert expected_pid == 456
        calls.append("attach")
        if calls.count("attach") == 1:
            raise component.QmtNotReady("modules loading")
        return terminal
    monkeypatch.setattr(component, "IsolatedLoginBackend", backend)
    monkeypatch.setattr(component.time, "sleep", lambda _: None)
    result = component.login_running_qmt(tmp_path, "fixture-user", lambda: "synthetic-fixture", expected_pid=456)
    assert result["login_succeeded"]
    assert result['attempts'] == ['provided']
    assert calls == ["attach", "attach", ("account", "fixture-user", True), "closed"]


@pytest.mark.parametrize('remembered', [True, False])
@pytest.mark.parametrize('outcome', ['logged_in', 'credential_error', 'challenge'])
def test_managed_login_always_overwrites_password_and_submits_once(remembered, outcome):
    terminal = Terminal(saved=remembered, outcomes=(outcome,))
    result = auto_login(terminal, lambda: 'synthetic-fixture')
    assert result['outcome'] == outcome
    assert result['attempts'] == ['provided']
    assert terminal.calls == ['fill', 'submit', 'wait']


def test_managed_login_never_falls_back_to_remembered_password():
    terminal = Terminal(saved=True)
    result = auto_login(terminal, lambda: '')
    assert result['outcome'] == 'password_required'
    assert not terminal.calls


@pytest.mark.parametrize('previous_account', ['fixture-user', 'other-user'])
def test_managed_login_resets_account_and_clears_password_even_for_same_user(previous_account):
    from types import SimpleNamespace
    from cfquant.qmt_component_login import QtLoginBackend
    calls = []
    backend = QtLoginBackend.__new__(QtLoginBackend)
    backend.session = SimpleNamespace(is_detached=False)
    backend.windows = lambda: []
    backend.existing_main = False
    backend.hwnd = 123
    backend.identity = previous_account
    backend.api = SimpleNamespace(selectaccount=lambda *args: calls.append(('account', args)),
                                  fill=lambda *args: calls.append(('password', args)))
    backend.select_account('fixture-user', replace=True)
    assert calls == [('account', ('123', 'fixture-user', True)), ('password', ('123', '', False))]
    assert backend.identity == 'fixture-user'


@pytest.fixture
def login_clock(monkeypatch):
    from types import SimpleNamespace
    import cfquant.qmt_component_login as component
    clock = SimpleNamespace(now=0.0)
    def sleep(seconds):
        clock.now += seconds
        assert clock.now < 300, "login retry did not finish"
    monkeypatch.setattr(component, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    return clock


@pytest.mark.parametrize("busy", [False, True])
def test_managed_login_waits_for_update_longer_than_previous_timeouts(monkeypatch, tmp_path, login_clock, busy):
    import cfquant.qmt_component_login as component
    terminal = Terminal(saved=False)
    def state():
        updating = login_clock.now < 125
        return dict(has_password=terminal.saved, busy=busy and updating,
                    login_enabled=terminal.saved and not updating)
    terminal.state = state
    accounts = []
    def select(account, replace=False):
        assert not state()["busy"]
        accounts.append((account, replace))
    terminal.select_account = select
    closed = []
    terminal.close = lambda: closed.append(True)
    monkeypatch.setattr(component, "IsolatedLoginBackend", lambda *a, **kw: terminal)
    result = component.login_running_qmt(tmp_path, "fixture-user", lambda: "synthetic-fixture")
    assert result["login_succeeded"] and login_clock.now == 125
    assert accounts == [("fixture-user", True)]
    assert terminal.calls == ["fill", "submit", "wait"]
    assert closed == [True]


def test_button_disabled_between_status_and_submit_is_retried(login_clock):
    from cfquant.qmt_component_login import QmtNotReady
    terminal = Terminal()
    def submit():
        if login_clock.now < 2:
            raise QmtNotReady("button became disabled")
        terminal.calls.append("submit")
    terminal.submit = submit
    result = auto_login(terminal, lambda: "synthetic-fixture", retry_not_ready=True)
    assert result["login_succeeded"] and login_clock.now == 2
    assert terminal.calls == ["fill", "submit", "wait"]


def test_slow_login_keeps_observing_without_another_submission(login_clock):
    terminal = Terminal(outcomes=("timeout", "timeout", "logged_in"))
    result = auto_login(terminal, lambda: "synthetic-fixture", retry_not_ready=True)
    assert result["login_succeeded"]
    assert terminal.calls == ["fill", "submit", "wait", "wait", "wait"]


def test_password_cleared_by_update_is_refilled_before_submission(login_clock):
    terminal = Terminal(saved=False)
    def state():
        if login_clock.now == 1:
            terminal.saved = False
        return dict(has_password=terminal.saved, busy=login_clock.now == 1,
                    login_enabled=terminal.saved and login_clock.now >= 2)
    terminal.state = state
    result = auto_login(terminal, lambda: "synthetic-fixture", retry_not_ready=True)
    assert result["login_succeeded"]
    assert terminal.calls == ["fill", "fill", "submit", "wait"]


@pytest.mark.parametrize("outcome", ["credential_error", "challenge", "network_error"])
def test_managed_retries_stop_on_actionable_rejection(login_clock, outcome):
    terminal = Terminal(outcomes=(outcome,))
    result = auto_login(terminal, lambda: "synthetic-fixture", retry_not_ready=True)
    assert result["outcome"] == outcome
    assert terminal.calls == ["fill", "submit", "wait"]


@pytest.mark.parametrize("busy", [False, True])
def test_waiting_for_update_can_be_cancelled(login_clock, busy):
    terminal = Terminal(busy=busy)
    terminal.state = lambda: dict(has_password=terminal.saved, busy=busy, login_enabled=False)
    result = auto_login(terminal, lambda: "synthetic-fixture", retry_not_ready=True,
                        should_cancel=lambda: login_clock.now >= 2)
    assert result["outcome"] == "cancelled" and result["attempts"] == []
    assert "submit" not in terminal.calls
    assert result["password_requested"] is not busy


def test_managed_startup_can_wait_beyond_one_minute(monkeypatch, tmp_path, login_clock):
    import cfquant.qmt_component_login as component
    terminal = Terminal()
    terminal.select_account = lambda *a, **kw: None
    terminal.close = lambda: None
    def attach(*a, **kw):
        if login_clock.now < 125:
            raise component.QmtNotReady("loading modules")
        return terminal
    monkeypatch.setattr(component, "IsolatedLoginBackend", attach)
    result = component.login_running_qmt(tmp_path, password_provider=lambda: "synthetic-fixture", startup_timeout=None)
    assert result["login_succeeded"] and login_clock.now == 125


@pytest.mark.parametrize("outcome", ["startup_timeout", "cancelled", "process_exited"])
def test_startup_stops_on_deadline_cancellation_or_process_exit(monkeypatch, tmp_path, login_clock, outcome):
    import cfquant.qmt_component_login as component
    def attach(*a, **kw):
        if outcome == "process_exited" and login_clock.now >= 2:
            raise component.QmtProcessExited("process exited")
        raise component.QmtNotReady("loading modules")
    monkeypatch.setattr(component, "IsolatedLoginBackend", attach)
    result = component.login_running_qmt(
        tmp_path, password_provider=no_password, startup_timeout=2 if outcome == "startup_timeout" else None,
        should_cancel=lambda: outcome == "cancelled" and login_clock.now >= 2)
    assert result["outcome"] == outcome and result["attempts"] == []


def test_native_submission_declined_on_gui_thread_is_retryable():
    from types import SimpleNamespace
    from cfquant.qmt_component_login import QtLoginBackend, QmtNotReady
    backend = QtLoginBackend.__new__(QtLoginBackend)
    backend.hwnd = 123
    backend.state = lambda: dict(has_password=True, login_enabled=True)
    backend.api = SimpleNamespace(submit=lambda hwnd: {"result": {"submitted": False}})
    with pytest.raises(QmtNotReady):
        backend.submit()


def test_login_completing_while_waiting_still_verifies_configured_account(login_clock):
    terminal = Terminal(busy=True)
    terminal.already_logged_in = lambda: login_clock.now >= 2
    selected = []
    terminal.select_account = lambda account: selected.append(account)
    result = auto_login(terminal, no_password, retry_not_ready=True, login_account="fixture-user")
    assert result["outcome"] == "already_logged_in"
    assert selected == ["fixture-user"]
    assert terminal.calls == []


def test_backend_detects_new_main_window_and_rejects_wrong_account():
    from types import SimpleNamespace
    from cfquant.qmt_component_login import QtLoginBackend
    backend = QtLoginBackend.__new__(QtLoginBackend)
    backend.session = SimpleNamespace(is_detached=False)
    backend.existing_main, backend.main_hwnd, backend.hwnd = False, None, 123
    backend.windows = lambda: [456]
    backend.api = SimpleNamespace(status=lambda hwnd: {"result": {"is_main": True}})
    backend.gui = SimpleNamespace(GetWindowText=lambda hwnd: "other-user - QMT")
    assert backend.already_logged_in()
    with pytest.raises(RuntimeError):
        backend.select_account("fixture-user")


def test_native_outcome_wait_can_be_cancelled_before_timeout(login_clock):
    from types import SimpleNamespace
    from cfquant.qmt_component_login import QtLoginBackend
    backend = QtLoginBackend.__new__(QtLoginBackend)
    backend.timeout = 40
    backend.session = SimpleNamespace(is_detached=False)
    backend.windows = lambda: []
    backend.should_cancel = lambda: login_clock.now >= 2
    assert backend.wait_outcome() == "cancelled"
    assert login_clock.now == 2


def test_process_exit_during_readiness_wait_closes_backend(monkeypatch, tmp_path, login_clock):
    import cfquant.qmt_component_login as component
    terminal = Terminal(busy=True)
    def check_main():
        if login_clock.now >= 2:
            raise component.QmtProcessExited("process exited")
        return False
    terminal.already_logged_in = check_main
    closed = []
    terminal.close = lambda: closed.append(True)
    monkeypatch.setattr(component, "IsolatedLoginBackend", lambda *a, **kw: terminal)
    result = component.login_running_qmt(tmp_path, password_provider=no_password)
    assert result["outcome"] == "process_exited"
    assert closed == [True] and terminal.calls == []
def test_cli_uses_isolated_backend_and_closes_it(tmp_path, monkeypatch, capsys):
    import json
    import sys
    from cfquant import qmt_component_login as module
    calls = []
    class Backend:
        pid = 123
        def select_account(self, account, replace=False):
            calls.append((account, replace))
        def diagnostics(self):
            return dict(minimized_before=False, foreground_before=1, foreground_after=1, script_errors=[])
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(module, "select_binding", lambda *args: ({}, tmp_path))
    monkeypatch.setattr(module, "IsolatedLoginBackend", lambda *args: Backend())
    monkeypatch.setattr(module, "QtLoginBackend", lambda *args: pytest.fail("CLI must isolate Frida"))
    monkeypatch.setattr(module, "auto_login", lambda *args: {"outcome": "already_logged_in"})
    monkeypatch.setattr(sys, "argv", ["qmt_component_login", "--binding", "fixture"])
    assert module.main() == 0
    assert calls == [("", True), "closed"]
    assert json.loads(capsys.readouterr().out)["script_errors"] == []
