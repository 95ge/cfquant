import time

from cfquant.monitor_notifications import MonitorNotificationService, normalize_config


def test_normalize_config_keeps_secrets_and_partial_heartbeat(tmp_path):
    service = MonitorNotificationService(tmp_path / "notifications.json")
    service.configure({
        "enabled": True,
        "event_types": ["trade"],
        "heartbeat": {"enabled": True, "interval_seconds": 600},
        "email": {"enabled": True, "host": "smtp.example", "password": "secret", "to": ["a@example.com"]},
        "webhooks": [{"id": "hook", "url": "https://example.test/hook", "type": "generic"}],
    })
    value = service.configure({"enabled": True, "event_types": ["trade"], "heartbeat": {"enabled": False}})
    assert value["heartbeat"]["interval_seconds"] == 600
    assert value["email"]["password_set"] is True
    assert value["email"]["password"] == "******"
    assert value["webhooks"][0]["url_configured"] is True
    assert "secret" not in value["webhooks"][0]
    service.close()

def test_callback_event_mapping_and_dedup(tmp_path):
    service = MonitorNotificationService(tmp_path / "notifications.json")
    delivered = []
    service._deliver = lambda kind, target, event: delivered.append(event["event_type"])
    service.configure({
        "enabled": True,
        "event_types": ["trade"],
        "dedup_seconds": 300,
        "webhooks": [{"id": "hook", "url": "https://example.test/hook", "enabled": True}],
    })
    event = {"event": "trader:on_stock_trade", "account_id": "paper", "data": {"stock_code": "000001"}}
    assert service.record_callback(event) is True
    assert service.record_callback(event) is False
    service._queue.join()
    assert delivered == ["trade"]
    service.close()


def test_schedule_modes(tmp_path, monkeypatch):
    service = MonitorNotificationService(tmp_path / "notifications.json")
    service.configure({"enabled": True, "event_types": ["heartbeat"], "schedule": {
        "mode": "custom", "weekdays": [0], "windows": [{"start": "09:00", "end": "10:00"}],
    }})
    monday_0930 = 1793583000  # 2026-11-02 09:30 Asia/Shanghai
    monday_1100 = 1793588400
    assert service._allowed_now(monday_0930) is True
    assert service._allowed_now(monday_1100) is False
    service.close()


def test_test_channel_bypasses_schedule_and_returns_failures(tmp_path):
    service = MonitorNotificationService(tmp_path / "notifications.json")
    calls = []
    service._deliver = lambda kind, target, event: calls.append(kind)
    service.configure({"enabled": False, "event_types": [], "email": {
        "enabled": True, "host": "smtp.example", "from": "a@example.com", "to": ["b@example.com"],
    }})
    result = service.test_channel("email")
    assert result == {"sent": 1, "failed": 0, "errors": []}
    assert calls == ["email"]
    service.close()
