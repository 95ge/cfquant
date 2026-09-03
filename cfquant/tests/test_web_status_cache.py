# -*- coding: utf-8 -*-
from types import SimpleNamespace

import cfquant_web_server as web


def _status(online, mode):
    return {
        "normal": {"online": online, "channel": "%s.normal" % mode},
        "trade": {"online": online, "channel": "%s.trade" % mode},
        "monitor": {"ready": True, "cached": True, "transport_mode": mode},
    }


def test_channel_status_monitor_keeps_ctypes_and_lttx_snapshots_separate():
    monitor = web.ChannelStatusMonitor()
    monitor._snapshots["default"] = {
        "ctypes": _status(True, "ctypes"),
        "lttx": _status(False, "lttx"),
    }

    assert monitor.latest("default", mode="ctypes")["normal"]["online"] is True
    assert monitor.latest("default", mode="lttx")["normal"]["online"] is False


def test_account_route_status_reads_monitor_cache_without_sync_probe(monkeypatch):
    ctypes_snapshot = _status(True, "ctypes")
    lttx_snapshot = _status(True, "lttx")
    calls = []

    class FakeMonitor(object):
        def latest(self, bridge_id, mode=None):
            calls.append((bridge_id, mode))
            return lttx_snapshot if mode == "lttx" else ctypes_snapshot

    fake_config = SimpleNamespace(
        account_config=lambda **kwargs: {
            "account_key": "default:STOCK:8885060548",
            "bridge_id": "default",
            "mode": "lttx",
        },
        data_provider_account_key=lambda: "",
    )

    monkeypatch.setattr(web, "WEB_CONFIG", fake_config)
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "default")
    monkeypatch.setattr(web, "resolve_account_mode", lambda *args, **kwargs: "lttx")
    monkeypatch.setattr(web, "account_market_route_config", lambda **kwargs: ({}, {}))
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})
    monkeypatch.setattr(web, "STATUS_MONITOR", FakeMonitor())
    monkeypatch.setattr(
        web,
        "ctypes_bridge_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync ctypes probe")),
    )
    monkeypatch.setattr(
        web,
        "probe_bridge_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync LTtx probe")),
    )

    result = web.account_route_status(
        "8885060548",
        bridge_id="default",
        account_type="STOCK",
        account_key="default:STOCK:8885060548",
    )

    assert result["ready"] is True
    assert result["effective_mode"] == "lttx"
    assert ("default", "ctypes") in calls
    assert ("default", "lttx") in calls


def test_account_data_cache_prewarm_tracks_configured_accounts_separately(monkeypatch):
    cache = web.AccountDataCache(interval=5, background_timeout=2)
    stale_key = ("old", "normal", "old:STOCK:000001", "000001", "STOCK")
    page_key = ("default", "normal", "default:STOCK:8885060548", "8885060548", "STOCK")
    cache._prewarm_subscriptions[stale_key] = {"asset"}
    cache._subscriptions[page_key] = {"orders"}
    monkeypatch.setattr(
        web,
        "enabled_account_configs",
        lambda: {
            "default:STOCK:8885060548": {
                "account_key": "default:STOCK:8885060548",
                "account_id": "8885060548",
                "account_type": "STOCK",
                "bridge_id": "default",
                "enabled": True,
            },
        },
    )
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})
    monkeypatch.setattr(web, "account_market_route_entries", lambda **kwargs: ({}, []))

    result = cache.prime_configured_accounts(sections=["asset", "positions"])
    key = ("default", "normal", "default:STOCK:8885060548", "8885060548", "STOCK")

    assert result == {
        "account_count": 1,
        "subscription_count": 1,
        "sections": ["asset", "positions"],
    }
    assert cache._prewarm_subscriptions[key] == {"asset", "positions"}
    assert stale_key not in cache._prewarm_subscriptions
    assert cache._subscriptions[page_key] == {"orders"}


def test_account_data_cache_uses_short_background_timeout(monkeypatch):
    cache = web.AccountDataCache(interval=5, background_timeout=2.5)
    cache._running = True
    cache._prewarm_subscriptions[("default", "normal", "default:STOCK:8885060548", "8885060548", "STOCK")] = {"asset"}
    calls = []

    def fake_query(bridge_id, channel, account_id, sections, **kwargs):
        calls.append((bridge_id, channel, account_id, list(sections), kwargs["timeout"]))
        return {"asset": {"ok": True, "data": {}}}

    monkeypatch.setattr(web, "query_account_live", fake_query)
    monkeypatch.setattr(cache, "_store_result", lambda *args, **kwargs: None)

    cache._refresh_subscriptions()

    assert calls == [("default", "normal", "8885060548", ["asset"], 2.5)]
