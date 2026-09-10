# -*- coding: utf-8 -*-
"""Account cache regressions with fake clocks and queries; no live RPC."""
import threading
from types import SimpleNamespace

import pytest

import cfquant_web_server as web


KEY = ("default", "trade", "default:STOCK:paper", "paper", "STOCK")


@pytest.fixture
def environment(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(web.time, "time", lambda: clock[0])
    monkeypatch.setattr(web.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})
    monkeypatch.setattr(web, "enabled_account_configs", lambda: {
        KEY[2]: {"account_id": "paper", "account_type": "STOCK", "bridge_id": "default", "mode": "lttx", "enabled": True},
    })
    monkeypatch.setattr(web, "account_market_route_entries", lambda **kwargs: ({}, []))
    calls = []

    def query(bridge_id, channel, account_id, sections, **kwargs):
        calls.append((bridge_id, channel, account_id, list(sections)))
        values = {
            "asset": [{"available": 100, "balance": 1000, "account_id": account_id}],
            "positions": [
                {"stock_code": "000001.SZ", "volume": 100, "can_use_volume": 100},
                {"stock_code": "600000.SH", "volume": 200, "can_use_volume": 200},
            ],
            "orders": [], "trades": [],
        }
        return {section: {"ok": True, "data": values[section]} for section in sections}

    monkeypatch.setattr(web, "query_account_live", query)
    cache = web.AccountDataCache(interval=30, idle_seconds=90)
    cache._running = True
    return SimpleNamespace(cache=cache, clock=clock, calls=calls, query=query)


def get(cache, sections=("asset", "positions"), **kwargs):
    return cache.get("default", "trade", "paper", sections, account_type="STOCK", account_key=KEY[2], **kwargs)


def event(name="on_stock_asset", data=None, **kwargs):
    return dict({"event": "trader:" + name, "bridge_id": "default", "account_id": "paper", "account_type": "STOCK", "data": data or {}}, **kwargs)


def test_no_default_prewarm_and_no_queries_without_readers(environment, monkeypatch):
    monkeypatch.setattr(web, "ACCOUNT_CACHE_PREWARM_SECTIONS", ())
    assert environment.cache.prime_configured_accounts()["subscription_count"] == 0
    for _ in range(100):
        environment.cache._refresh_subscriptions()
        environment.clock[0] += 1
    assert environment.calls == []


def test_initial_snapshot_then_only_due_sections_are_queried(environment):
    cache = environment.cache
    assert get(cache)["asset"]["data"][0]["available"] == 100
    assert len(environment.calls) == 1
    environment.clock[0] += 15
    get(cache)
    cache._refresh_subscriptions()
    assert len(environment.calls) == 1
    get(cache, ["trades"])
    environment.clock[0] += 15
    cache._refresh_subscriptions()
    assert environment.calls[-1][3] == ["asset", "positions"]
    assert len(environment.calls) == 3


def test_idle_sections_expire_even_when_other_sections_stay_active(environment):
    cache = environment.cache
    get(cache, ["asset", "positions", "trades"])
    for _ in range(6):
        environment.clock[0] += 15
        get(cache)
        cache._refresh_subscriptions()
    assert cache._subscriptions[KEY] == {"asset", "positions"}
    environment.clock[0] += 90
    before = len(environment.calls)
    cache._refresh_subscriptions()
    cache.update_from_event(event("on_stock_trade", {"order_id": 1}))
    environment.clock[0] += 3
    cache._refresh_subscriptions()
    assert len(environment.calls) == before
    assert not cache._subscriptions


def test_explicit_prewarm_remains_opt_in(environment):
    cache = environment.cache
    cache.prime_configured_accounts(["asset"])
    cache._refresh_subscriptions()
    environment.clock[0] += 120
    cache._refresh_subscriptions()
    assert len(environment.calls) == 2


def test_disabled_account_loses_background_subscription(environment, monkeypatch):
    cache = environment.cache
    get(cache)
    monkeypatch.setattr(web, "enabled_account_configs", lambda: {})
    cache.prime_configured_accounts()
    environment.clock[0] += 30
    cache._refresh_subscriptions()
    assert len(environment.calls) == 1


def test_asset_callback_updates_only_present_fields_without_rpc(environment):
    cache = environment.cache
    get(cache)
    checked = cache._entries[KEY + ("asset",)]["checked_at"]
    environment.clock[0] += 5
    cache.update_from_event(event(data={"m_dAvailable": 0}))
    result = get(cache)["asset"]
    assert result["data"][0]["available"] == 0
    assert result["data"][0]["balance"] == 1000
    assert result["checked_at"] == checked
    assert result["update_source"] == "callback"
    cache._refresh_subscriptions()
    assert len(environment.calls) == 1
    environment.clock[0] += 25
    cache._refresh_subscriptions()
    assert len(environment.calls) == 2


def test_continuous_asset_callbacks_still_only_need_30_second_snapshot_queries(environment):
    cache = environment.cache
    get(cache)
    for second in range(1, 66):
        environment.clock[0] += 1
        cache.update_from_event(event(data={"available": second}))
        get(cache)
        cache._refresh_subscriptions()
    assert len(environment.calls) == 3  # Initial snapshot, 30 seconds, 60 seconds.


def test_failed_refresh_releases_waiters_and_obeys_retry_throttle(environment, monkeypatch):
    cache = environment.cache
    failures = []

    def fail(*args, **kwargs):
        failures.append(True)
        raise RuntimeError("fake bridge failure")

    monkeypatch.setattr(web, "query_account_live", fail)
    with pytest.raises(RuntimeError, match="fake bridge"):
        get(cache)
    assert not cache._refreshing
    cache._refresh_subscriptions()
    assert len(failures) == 1
    monkeypatch.setattr(web, "query_account_live", environment.query)
    environment.clock[0] += 3
    assert get(cache)["asset"]["ok"] is True


def test_position_delta_does_not_replace_the_full_list(environment):
    cache = environment.cache
    get(cache)
    cache.update_from_event(event("on_stock_position", {"m_strInstrumentID": "000001", "m_strExchangeID": "SZ", "m_nVolume": 0, "m_nCanUseVolume": 0}))
    rows = get(cache)["positions"]["data"]
    assert len(rows) == 2
    assert rows[0]["volume"] == 0
    assert rows[1]["volume"] == 200
    assert len(environment.calls) == 1


@pytest.mark.parametrize("data", [
    {"stock_code": "999999.SZ", "volume": 100},
    {"stock_code": "000001.SZ", "volume": 100, "stock_holder": "other-unit"},
    {"volume": 100},
])
def test_unmatched_or_ambiguous_position_queues_a_single_reconciliation(environment, data):
    cache = environment.cache
    get(cache)
    for _ in range(10):
        cache.update_from_event(event("on_stock_position", data))
    assert len(environment.calls) == 1
    environment.clock[0] += 3
    cache._refresh_subscriptions()
    assert environment.calls[-1][3] == ["positions"]
    cache._refresh_subscriptions()
    assert len(environment.calls) == 2


def test_callbacks_cannot_cross_account_type_or_bridge(environment):
    cache = environment.cache
    get(cache)
    for overrides in ({"account_id": "other"}, {"account_type": "CREDIT"}, {"bridge_id": "other"}, {"bridge_id": ""}):
        cache.update_from_event(event(data={"available": 9}, **overrides))
    cache.update_from_event(event(data={"account_id": "other", "available": 9}))
    assert get(cache)["asset"]["data"][0]["available"] == 100
    assert not cache._dirty


def test_missing_type_is_not_guessed_for_ambiguous_identity(environment, monkeypatch):
    cache = environment.cache
    get(cache)
    monkeypatch.setattr(web, "account_identity_is_ambiguous", lambda *args: True)
    cache.update_from_event(event(data={"available": 9}, account_type=""))
    assert get(cache)["asset"]["data"][0]["available"] == 100


def test_child_bridge_callback_only_updates_its_own_market_cache(environment):
    cache = environment.cache
    for bridge in ("market_sh", "market_sz"):
        cache.get(bridge, "trade", "paper", ["asset"], account_key=KEY[2])
    cache.update_from_event(event(data={"available": 9}, bridge_id="market_sh"))
    assert cache._entries[("market_sh",) + KEY[1:] + ("asset",)]["data"][0]["available"] == 9
    assert cache._entries[("market_sz",) + KEY[1:] + ("asset",)]["data"][0]["available"] == 100


def test_repeated_callback_cannot_start_a_query_storm(environment):
    cache = environment.cache
    get(cache)
    for tick in range(10):
        cache.update_from_event(event("on_stock_order", {"order_id": tick}))
        cache._refresh_subscriptions()
        environment.clock[0] += 0.1
    assert len(environment.calls) == 1
    environment.clock[0] += 2
    cache._refresh_subscriptions()
    assert len(environment.calls) == 2


def test_out_of_order_callbacks_are_ignored_after_a_newer_duplicate(environment):
    cache = environment.cache
    get(cache)
    cache.update_from_event(event(data={"available": 9}, ts=10))
    cache.update_from_event(event(data={"available": 9}, ts=30))
    cache.update_from_event(event(data={"available": 8}, ts=20))
    assert get(cache)["asset"]["data"][0]["available"] == 9


def test_query_cannot_overwrite_a_callback_received_during_the_rpc(environment, monkeypatch):
    cache = environment.cache
    get(cache)

    def query(*args, **kwargs):
        cache.update_from_event(event(data={"available": 77}))
        return environment.query(*args, **kwargs)

    monkeypatch.setattr(web, "query_account_live", query)
    assert get(cache, force=True)["asset"]["data"][0]["available"] == 77


def test_event_dirty_flag_survives_an_inflight_query(environment, monkeypatch):
    cache = environment.cache
    get(cache)

    def query(*args, **kwargs):
        cache.update_from_event(event("on_stock_trade", {"order_id": 5}))
        return environment.query(*args, **kwargs)

    monkeypatch.setattr(web, "query_account_live", query)
    get(cache, force=True)
    assert KEY + ("positions",) in cache._dirty
    monkeypatch.setattr(web, "query_account_live", environment.query)
    environment.clock[0] += 3
    cache._refresh_subscriptions()
    assert KEY + ("positions",) not in cache._dirty


def test_concurrent_initial_readers_share_one_query(environment, monkeypatch):
    cache = environment.cache
    entered = threading.Event()
    release = threading.Event()
    results = []
    errors = []

    def query(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return environment.query(*args, **kwargs)

    def read():
        try:
            results.append(get(cache))
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(web, "query_account_live", query)
    threads = [threading.Thread(target=read) for _ in range(2)]
    try:
        threads[0].start()
        assert entered.wait(3)
        threads[1].start()
        cache._refresh_subscriptions()
    finally:
        release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(4)
    assert not errors
    assert len(results) == 2
    assert len(environment.calls) == 1
    assert not cache._refreshing


def test_force_refresh_and_unsubscribed_queries_keep_their_contract(environment):
    cache = environment.cache
    get(cache)
    assert get(cache, force=True)["cache"]["force"] is True
    result = cache.get("default", "trade", "other", ["asset"], subscribe=False)
    assert result["cache"]["enabled"] is False
    assert all(key[3] != "other" for key in cache._subscriptions)
    assert len(environment.calls) == 3


def test_event_store_updates_cache_before_broadcast_without_rpc(environment, monkeypatch):
    cache = environment.cache
    get(cache)
    seen = []
    monkeypatch.setattr(web, "ACCOUNT_CACHE", cache)
    monkeypatch.setattr(web, "RUNTIME_VERSIONS", SimpleNamespace(update_from_event=lambda row: None))
    monkeypatch.setattr(web, "WS_CALLBACKS", SimpleNamespace(broadcast=lambda row: seen.append(get(cache)["asset"]["data"][0]["available"])))
    web.CallbackEventStore(channels=["fake"])._append(event(data={"available": 88}))
    assert seen == [88]
    assert len(environment.calls) == 1
