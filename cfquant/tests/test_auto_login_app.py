"""Portable tests for the standalone QMT auto-login scheduler configuration."""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("cfquant_private_auto_login", ROOT / "private/auto_login/app.py")
auto_login = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_login)


class FakeVault:
    def encrypt(self, value):
        return "protected:" + value[::-1]

    def decrypt(self, value):
        return value.removeprefix("protected:")[::-1]


def test_profile_store_round_trip_keeps_password_out_of_plaintext(tmp_path):
    store = auto_login.ProfileStore(tmp_path / "profiles.json", vault=FakeVault())
    profile = auto_login.ProfileStore.normalize({
        "id": "qmt-one", "name": "国金模拟", "executable": "D:/QMT/XtItClient.exe",
        "login_account": "demo", "start_time": "09:00", "weekdays": [0, 1, 2, 3, 4],
        "password": store.vault.encrypt("secret"),
    })
    store.save([profile])
    loaded = store.load()
    assert loaded[0]["id"] == "qmt-one"
    assert "secret" not in (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert store.password(loaded[0]) == "secret"


@pytest.mark.parametrize("value", ["9:00", "25:00", "09:60", ""])
def test_profile_validation_rejects_invalid_start_time(value):
    profile = auto_login.ProfileStore.normalize({
        "name": "QMT", "executable": "D:/QMT/XtItClient.exe", "login_account": "demo",
        "password": "protected:secret", "start_time": value,
    })
    with pytest.raises(ValueError, match="启动时间"):
        auto_login.validate_profile(profile)


def test_command_arguments_are_parsed_without_shell_execution():
    assert auto_login.command_arguments('--profile "paper account" --mode lite') == [
        '--profile', '"paper account"', '--mode', 'lite'
    ]
    with pytest.raises(ValueError, match="启动参数"):
        auto_login.command_arguments('"unterminated')


def test_scheduler_triggers_each_profile_once_per_minute():
    class Launcher:
        def start(self, profile):
            pass

    profile = auto_login.ProfileStore.normalize({"id": "qmt", "name": "QMT", "executable": "x.exe",
                                                  "login_account": "demo", "password": "protected:p"})
    scheduler = auto_login.Scheduler(lambda: [profile], Launcher())
    now = auto_login.dt.datetime(2026, 11, 9, 9, 0)
    assert scheduler.due_profiles(now) == [profile]
    assert scheduler.due_profiles(now) == []


def test_qmt_login_forwards_configured_executable_path(monkeypatch, tmp_path):
    import cfquant.qmt_component_login as component

    class Terminal:
        def already_logged_in(self):
            return False

        def state(self):
            return {"has_password": False, "login_enabled": True, "busy": False}

        def select_account(self, account, replace=False):
            pass

        def fill(self, password):
            pass

        def submit(self):
            pass

        def wait_outcome(self):
            return "logged_in"

        def close(self):
            pass

    seen = {}

    def backend(directory, timeout, **kwargs):
        seen.update(kwargs)
        return Terminal()

    monkeypatch.setattr(component, "IsolatedLoginBackend", backend)
    result = component.login_running_qmt(
        tmp_path, "demo", lambda: "secret", startup_timeout=1,
        executable_path=tmp_path / "OtherQmtClient.exe",
    )
    assert result["login_succeeded"]
    assert seen["executable_path"] == tmp_path / "OtherQmtClient.exe"


def test_notification_credentials_are_encrypted_and_round_trip(tmp_path):
    store = auto_login.ProfileStore(tmp_path / "profiles.json", vault=FakeVault())
    settings = auto_login.notification_stored_settings(store, {
        "enabled": True, "providers": ["smtp", "dingtalk"],
        "configs": {
            "smtp": {"host": "smtp.qq.com", "password": "mail-secret", "recipient": "user@example.com"},
            "dingtalk": {"webhook": "https://example.test/hook", "signing_key": "robot-secret"},
        },
    })
    store.save([], settings)
    raw = (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert "mail-secret" not in raw
    assert "robot-secret" not in raw
    loaded = auto_login.notification_plain_settings(store, store.load_notifications())
    assert loaded["configs"]["smtp"]["password"] == "mail-secret"
    assert loaded["configs"]["dingtalk"]["signing_key"] == "robot-secret"


def test_notification_webhook_payload(monkeypatch):
    seen = {}

    def post(url, payload):
        seen.update(url=url, payload=payload)
        return "{}"

    monkeypatch.setattr(auto_login.NotificationService, "_post_json", staticmethod(post))
    result = auto_login.NotificationService().send({
        "provider": "wechat", "webhook": "https://example.test/hook",
    }, "subject", "body")
    assert "消息已发送" in result
    assert seen["payload"]["msgtype"] == "text"
    assert "subject" in seen["payload"]["text"]["content"]


def test_notification_can_send_to_multiple_webhooks(monkeypatch):
    calls = []

    def post(url, payload):
        calls.append((url, payload))
        return "{}"

    monkeypatch.setattr(auto_login.NotificationService, "_post_json", staticmethod(post))
    result = auto_login.NotificationService().send({
        "providers": ["wechat", "feishu"],
        "configs": {
            "wechat": {"webhook": "https://example.test/wechat"},
            "feishu": {"webhook": "https://example.test/feishu"},
        },
    }, "subject", "body")
    assert len(calls) == 2
    assert "wechat" in result and "feishu" in result


def test_runtime_validation_rejects_bad_restart_values():
    profile = auto_login.ProfileStore.normalize({
        "name": "QMT", "executable": "D:/QMT/XtItClient.exe", "start_time": "09:00",
        "restart_countdown": "-1", "daemon_delay": "10", "auto_login": False,
    })
    with pytest.raises(ValueError, match="倒计时"):
        auto_login.validate_profile(profile)


def test_run_log_store_persists_and_manages_history(tmp_path):
    store = auto_login.RunLogStore(tmp_path / "cfquant_auto_login.sqlite3", retention_days=30)
    store.append({"id": "qmt", "name": "演示 QMT"}, "QMT 已启动")
    rows = store.list_logs()
    assert len(rows) == 1
    assert rows[0]["profile_name"] == "演示 QMT"
    assert rows[0]["message"] == "QMT 已启动"
    assert (tmp_path / "cfquant_auto_login.sqlite3").exists()
    assert store.delete_ids([rows[0]["id"]]) == 1
    assert store.list_logs() == []


def test_run_log_store_cleanup_and_keep_all(tmp_path):
    store = auto_login.RunLogStore(tmp_path / "logs.sqlite3", retention_days=30)
    store.append({"id": "qmt", "name": "QMT"}, "old")
    with store.lock, store._connect() as connection:
        connection.execute("UPDATE run_logs SET created_at = ?", ("2020-01-01T00:00:00",))
        connection.commit()
    assert store.cleanup() == 1
    store.append({"id": "qmt", "name": "QMT"}, "keep")
    assert store.set_retention(0) == 0
    assert len(store.list_logs()) == 1


def test_runtime_normalizes_shutdown_defaults_and_days():
    runtime = auto_login.ProfileStore.normalize_runtime({
        "shutdown_enabled": True,
        "shutdown_time": "23:10",
        "shutdown_weekdays": [0, 2, 9, "bad"],
        "shutdown_countdown": 120,
    })
    assert runtime["shutdown_enabled"] is True
    assert runtime["shutdown_time"] == "23:10"
    assert runtime["shutdown_weekdays"] == [0, 2]
    assert runtime["shutdown_countdown"] == "120"
    auto_login.validate_shutdown_settings(runtime)


@pytest.mark.parametrize("value", ["9:00", "25:00", "18:60", ""])
def test_shutdown_validation_rejects_invalid_time(value):
    runtime = auto_login.ProfileStore.normalize_runtime({"shutdown_time": value})
    with pytest.raises(ValueError, match="关机时间"):
        auto_login.validate_shutdown_settings(runtime)


def test_scheduler_triggers_shutdown_once_per_minute():
    class Launcher:
        def start(self, profile):
            pass

        def event_callback(self, profile, message):
            pass

    runtime = auto_login.ProfileStore.normalize_runtime({
        "shutdown_enabled": True,
        "shutdown_time": "18:30",
        "shutdown_weekdays": [0],
        "shutdown_countdown": "60",
    })
    calls = []
    scheduler = auto_login.Scheduler(lambda: [], Launcher(), lambda: runtime, lambda config: calls.append(config))
    now = auto_login.dt.datetime(2026, 11, 9, 18, 30)
    assert scheduler.due_shutdown(now) is True
    assert scheduler.due_shutdown(now) is False
    assert calls == []
    assert scheduler.last_shutdown_slots == {"2026-11-09 18:30"}


def test_system_shutdown_command_is_explicit_and_cancelable(monkeypatch):
    calls = []
    monkeypatch.setattr(auto_login.os, "name", "nt")

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(auto_login.subprocess, "run", lambda args, **kwargs: calls.append(args) or Result())
    auto_login.request_system_shutdown(90)
    auto_login.cancel_system_shutdown()
    assert calls[0][:4] == ["shutdown.exe", "/s", "/t", "90"]
    assert calls[1] == ["shutdown.exe", "/a"]


def test_startup_failure_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("CFQUANT_AUTO_LOGIN_LOG_DIR", str(tmp_path))
    try:
        raise RuntimeError("synthetic startup failure")
    except RuntimeError as error:
        report = auto_login.write_crash_report(error)
    assert report == tmp_path / "cfquant_auto_login_crash.log"
    assert "synthetic startup failure" in report.read_text(encoding="utf-8")


def test_damaged_log_database_is_preserved_and_gui_can_continue(tmp_path):
    path = tmp_path / "logs.sqlite3"
    path.write_bytes(b"damaged sqlite fixture")
    store = auto_login.RunLogStore(path)
    assert path.read_bytes() == b"damaged sqlite fixture"
    assert store.path != path
    assert store.startup_warning
    store.append({"name": "system"}, "recovered")
    assert store.list_logs()[0]["message"] == "recovered"
    # Connections must be closed, not left holding the database open on Windows.
    moved = store.path.with_suffix(".moved")
    store.path.rename(moved)


def test_unwritable_program_directory_uses_writable_fallback(tmp_path, monkeypatch):
    primary = tmp_path / "protected"
    fallback = tmp_path / "writable"
    monkeypatch.setenv("CFQUANT_AUTO_LOGIN_LOG_DIR", str(primary))
    monkeypatch.setenv("CFQUANT_RUNTIME_DIR", str(fallback))
    probe = auto_login._probe_writable_directory
    monkeypatch.setattr(auto_login, "_probe_writable_directory", lambda path: path != primary and probe(path))
    assert auto_login.runtime_data_dir() == fallback


def test_notification_failure_returns_message_without_tk_calls(monkeypatch):
    def fail(*args):
        raise RuntimeError("simulated network error")
    monkeypatch.setattr(auto_login.NotificationService, "send", fail)
    results = auto_login.queue.Queue()
    auto_login.NotificationDialog._run_test(object(), {}, results)
    assert results.get_nowait() == (False, "simulated network error")


def test_shutdown_failure_is_reported(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(auto_login.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=5, stdout="", stderr="access denied"))
    with pytest.raises(RuntimeError, match="access denied"):
        auto_login.request_system_shutdown(60)


@pytest.fixture
def desktop_app(tmp_path, monkeypatch):
    if auto_login.os.name != "nt":
        pytest.skip("Windows desktop regression test")
    monkeypatch.setenv("CFQUANT_AUTO_LOGIN_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("CFQUANT_AUTO_LOGIN_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(auto_login.Scheduler, "start", lambda self: None)
    app = auto_login.AutoLoginApp()
    try:
        app.update()
        yield app
    finally:
        app.scheduler.close()
        app.manager.stop_all()
        for callback in app.tk.splitlist(app.tk.call("after", "info")):
            app.after_cancel(callback)
        app.destroy()


def test_required_agreement_visible_before_main_window(desktop_app):
    app = desktop_app
    dialog = next(child for child in app.winfo_children() if isinstance(child, auto_login.AgreementDialog))
    assert app.state() == "withdrawn"
    assert dialog.winfo_viewable()
    assert not app._scheduler_started
    dialog.accept_var.set(True)
    dialog._accept()
    app.update()
    assert app.winfo_viewable()
    assert app._scheduler_started
    assert app.store.load_runtime()["agreement_accepted"]


def test_agreement_save_failure_keeps_visible_dialog(desktop_app, monkeypatch):
    app = desktop_app
    dialog = next(child for child in app.winfo_children() if isinstance(child, auto_login.AgreementDialog))
    errors = []
    monkeypatch.setattr(auto_login.messagebox, "showerror", lambda *args, **kwargs: errors.append(kwargs["parent"]))
    def fail(*args):
        raise PermissionError("read only config")
    monkeypatch.setattr(app.store, "save", fail)
    dialog.accept_var.set(True)
    dialog._accept()
    assert not app.runtime["agreement_accepted"]
    assert not app._scheduler_started
    assert dialog.winfo_viewable()
    assert errors == [dialog]


def test_shutdown_save_failure_does_not_activate_schedule(desktop_app, monkeypatch):
    app = desktop_app
    before = dict(app.runtime)
    app.shutdown_enabled_var.set(True)
    errors = []
    monkeypatch.setattr(auto_login.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    def fail(*args):
        raise PermissionError("read only config")
    monkeypatch.setattr(app.store, "save", fail)
    app._save_shutdown()
    assert app.runtime == before
    assert errors
