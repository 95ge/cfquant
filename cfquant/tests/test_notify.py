"""Offline account notification routing, persistence and platform delivery."""
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from cfquant import notify, webhook
import cfquant_web_server as web


@pytest.fixture
def delivery(monkeypatch):
    state = SimpleNamespace(calls=[], response=b'{"errcode":0}', status=200, error=None)

    class Response:
        def __enter__(self):
            self.status = state.status
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return state.response[:limit]

    def send(request, timeout):
        state.calls.append((request, timeout))
        if state.error:
            raise state.error
        return Response()

    monkeypatch.setattr(webhook.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=send))
    monkeypatch.setattr(webhook.time, "time", lambda: 1700000000)
    return state


@pytest.fixture
def config(tmp_path, monkeypatch):
    config = web.WebRuntimeConfig(str(tmp_path / "web.json"), str(tmp_path / "settings.db"))
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "account_request", lambda *a, **k: pytest.fail("Messages must not route to QMT"))
    return config


def bind(config, account_id="TEST", **kwargs):
    return config.save_account_config(account_id, qmt_strategy={"enabled": False},
                                     qmt_auto_login={"enabled": False}, **kwargs)


TARGET = {"enabled": True, "provider": "dingtalk", "url": "https://example.invalid/hook?token=PRIVATE_TOKEN", "secret": "PRIVATE_SECRET"}


@pytest.mark.parametrize("provider", webhook.PROVIDERS)
def test_platform_payload_signing_and_success(delivery, provider):
    delivery.response = b'{"code":0}' if provider == "feishu" else b'{"errcode":0}'
    result = notify.send("完成\n下一行", title="标题", provider=provider, webhook_url=TARGET["url"], secret=TARGET["secret"])
    assert result == {"sent": True, "provider": provider, "source": "explicit", "http_status": 200}
    request, timeout = delivery.calls[0]
    body = json.loads(request.data)
    assert timeout == 8
    text = "标题\n完成\n下一行"
    if provider == "feishu":
        assert body["content"]["text"] == text and body["msg_type"] == "text"
        key = b"1700000000\nPRIVATE_SECRET"
        assert body["sign"] == base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()
        assert body["timestamp"] == "1700000000"
    elif provider == "generic":
        assert body == {"title": "标题", "message": "完成\n下一行"}
    else:
        assert body == {"msgtype": "text", "text": {"content": text}}
    query = parse_qs(urlsplit(request.full_url).query)
    if provider == "dingtalk":
        assert query["timestamp"] == ["1700000000000"]
        assert query["sign"] == [base64.b64encode(hmac.new(b"PRIVATE_SECRET", b"1700000000000\nPRIVATE_SECRET", hashlib.sha256).digest()).decode()]
    else:
        assert "sign" not in query


@pytest.mark.parametrize("response", [b'{"errcode":310000}', b'{"code":19021}', b'{}', b'null', b'[]', b'not-json'])
def test_platform_rejection_not_reported_as_success(delivery, response):
    delivery.response = response
    with pytest.raises(webhook.WebhookError):
        notify.send("hello", webhook_url=TARGET["url"], provider="dingtalk")
    assert len(delivery.calls) == 1


def test_transport_error_has_no_credentials_and_no_retry(delivery):
    delivery.error = OSError(TARGET["url"] + TARGET["secret"])
    with pytest.raises(webhook.WebhookError) as error:
        notify.send("hello", webhook_url=TARGET["url"], provider="dingtalk", secret=TARGET["secret"])
    assert "PRIVATE" not in str(error.value)
    assert len(delivery.calls) == 1


@pytest.mark.parametrize("params", [
    {}, {"account_id": "   "}, {"webhook_url": TARGET["url"]}, {"provider": "wecom"},
    {"account_id": "TEST", "secret": "x"},
    {"webhook_url": "file:///C:/x", "provider": "generic"},
    {"webhook_url": TARGET["url"], "provider": "unknown"},
    {"webhook_url": TARGET["url"], "provider": "wecom", "timeout": float("nan")},
])
def test_invalid_request_fails_before_sending(delivery, params):
    with pytest.raises(ValueError):
        notify.send("hello", **params)
    assert not delivery.calls


def test_utf8_limits_and_monitor_reuses_delivery(delivery, tmp_path):
    with pytest.raises(ValueError, match="2048"):
        notify.send("中" * 683, webhook_url=TARGET["url"], provider="wecom")
    from cfquant.monitor_notifications import MonitorNotificationService
    service = MonitorNotificationService(tmp_path / "monitor.json")
    delivery.response = b'{"code":0}'
    service._send_webhook(dict(TARGET, type="feishu", provider="feishu"),
                          {"title": "test", "message": "message", "occurred_at": 1700000000})
    assert "sign" in json.loads(delivery.calls[0][0].data)
    delivery.response = b'{"code":19021}'
    with pytest.raises(webhook.WebhookError):
        service._send_webhook(dict(TARGET, provider="feishu"), {"message": "message", "occurred_at": 1700000000})


def test_binding_persistence_masking_preserve_replace_disable_clear(config):
    row = bind(config, notification_webhook=TARGET)
    key = row["account_key"]
    for value in (row, config.account_configs(), config.account_config("TEST"),
                  config.account_config_by_key(key), config.snapshot()):
        assert "PRIVATE" not in json.dumps(value)
    assert row["notification_webhook"]["url_configured"] and row["notification_webhook"]["secret_configured"]
    assert bind(config)["notification_webhook"] == row["notification_webhook"]
    bind(config, "SECOND", notification_webhook=dict(TARGET, url="https://example.invalid/second"))
    config = web.WebRuntimeConfig(config.path, config.settings_db_path)
    assert config.account_webhook("TEST")[0] == TARGET
    config.save_account_webhook(key, {"url": "https://example.invalid/new"})
    assert config.account_webhook("TEST")[0]["secret"] == ""
    assert config.account_webhook("SECOND")[0]["secret"] == TARGET["secret"]
    config.save_account_webhook(key, {"enabled": False})
    with pytest.raises(ValueError, match="未启用"):
        config.account_webhook("TEST")
    config.save_account_webhook(key, {"enabled": True, "secret": "new"})
    config.save_account_webhook(key, {"clear_secret": True})
    assert config.account_webhook("TEST")[0]["secret"] == ""
    config.save_account_webhook(key, {"clear": True})
    assert not config.account_config_by_key(key)["notification_webhook"]["url_configured"]


def test_exact_account_resolution_and_override(config, delivery):
    first = bind(config, notification_webhook=TARGET, bridge_id="one")
    with pytest.raises(ValueError, match="指定"):
        web.send_user_notification({"account_id": "  ", "message": "hello"})
    bind(config, notification_webhook=dict(TARGET, provider="wecom", secret=""), account_type="CREDIT", bridge_id="two")
    with pytest.raises(ValueError, match="多个"):
        web.send_user_notification({"account_id": "TEST", "message": "hello"})
    with pytest.raises(ValueError, match="未找到"):
        web.send_user_notification({"account_id": "WRONG", "account_key": first["account_key"], "message": "hello"})
    result, meta = web.route_external_lttx_request({"action": "cfquant.notify.send", "params": {
        "account_id": "TEST", "account_type": "CREDIT", "message": "hello"}})
    assert result["provider"] == "wecom" and meta["route"] == "notification"
    delivery.calls.clear()
    result = web.send_user_notification({"account_id": "NOT_BOUND", "message": "override",
        "webhook_url": "https://example.invalid/override", "provider": "dingtalk"})
    assert result["source"] == "explicit"
    assert delivery.calls[0][0].full_url == "https://example.invalid/override"
    assert config.account_webhook(account_key=first["account_key"])[0] == TARGET


def test_sdk_account_mode_forces_web_route_and_never_fetches_secrets(config, delivery, monkeypatch):
    from cfquant import client
    row = bind(config, notification_webhook=TARGET)
    created, requests = [], []
    def request(action, params, timeout):
        requests.append((action, params, timeout))
        return web.route_external_lttx_request({"action": action, "params": params})[0]
    fake = SimpleNamespace(request=request, close=lambda: None)
    monkeypatch.setattr(client, "create_rpc_client", lambda **kw: created.append(kw) or fake)
    monkeypatch.setattr(notify, "_client", None)
    result = notify.send("SDK message", account_id="TEST")
    assert result["account_key"] == row["account_key"]
    assert created == [{"transport": "web_lttx"}]
    assert requests[0][2] == 13
    assert "PRIVATE" not in str(requests)


def test_http_auth_send_and_config_only_save(config, delivery, monkeypatch):
    row = bind(config, notification_webhook=TARGET)
    handler = object.__new__(web.CfquantWebHandler)
    written = []
    handler.path = "/api/notifications/send"
    handler._request_allowed = lambda: True
    handler._authorized = lambda parsed: False
    handler._write_json = lambda payload, status=200: written.append((status, payload))
    handler._read_json_body = lambda: {"account_id": "TEST", "message": "hello"}
    handler.do_POST()
    assert written[-1][0] == 401 and not delivery.calls
    handler._authorized = lambda parsed: True
    handler.do_POST()
    assert written[-1][1]["data"]["sent"] is True
    handler.path = "/api/account-config/webhook"
    handler._read_json_body = lambda: {"account_key": row["account_key"], "notification_webhook": {"enabled": False}}
    monkeypatch.setattr(web, "qmt_process_preflight", lambda **k: pytest.fail("Webhook edits must not stop QMT"))
    handler.do_POST()
    assert not written[-1][1]["data"]["account"]["notification_webhook"]["enabled"]
    assert "PRIVATE" not in str(written)


def test_failed_settings_save_retains_previous_target(config, monkeypatch):
    row = bind(config, notification_webhook=TARGET)
    monkeypatch.setattr(config, "_save_locked", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        config.save_account_webhook(row["account_key"], {"url": "https://example.invalid/new"})
    assert config.account_webhook("TEST")[0] == TARGET
