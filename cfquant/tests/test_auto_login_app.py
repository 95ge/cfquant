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
