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
    def backend(directory, timeout, expected_pid):
        assert expected_pid == 456
        calls.append("attach")
        if calls.count("attach") == 1:
            raise component.QmtNotReady("modules loading")
        return terminal
    monkeypatch.setattr(component, "QtLoginBackend", backend)
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
    backend.existing_main = False
    backend.hwnd = 123
    backend.identity = previous_account
    backend.api = SimpleNamespace(selectaccount=lambda *args: calls.append(('account', args)),
                                  fill=lambda *args: calls.append(('password', args)))
    backend.select_account('fixture-user', replace=True)
    assert calls == [('account', ('123', 'fixture-user', True)), ('password', ('123', '', False))]
    assert backend.identity == 'fixture-user'
