# -*- coding: utf-8 -*-
"""Offline regressions. All account and bridge calls are local fakes."""
import os
import json
import threading
import time

import pandas as pd
import pytest

import cfquant_web_server as web
import cfquant.tx_trade_bridge as tx_trade_bridge_module
from cfquant import xtconstant
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.pipe_bridge import PipeNormalQmtBridge, PipeTradeBridge
from cfquant.runtime_report import module_source_state, source_sha256
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount, XtAsset, XtOrder, XtPosition, XtTrade, normalize_order_price_type


def test_shared_qmt_context_registers_auto_trade_callback_once():
    class CallbackContext(object):
        def __init__(self):
            self.calls = []

        def set_auto_trade_callback(self, enabled):
            self.calls.append(bool(enabled))
            return "registered"

    context = CallbackContext()
    normal = NormalQmtBridge(
        context=None,
        show=False,
        dispatch_on_qmt_thread=True,
        schedule_timer=False,
    )
    trade = TxTradeBridge(context=None, show=False)
    try:
        normal.set_context(context)
        trade.set_context(context)

        # The QMT entry refreshes both bridge objects again in after_init.
        normal.auto_trade_callback_enabled = False
        trade.auto_trade_callback_enabled = False
        normal._enable_auto_trade_callback()
        trade._enable_auto_trade_callback()

        assert context.calls == [True]
        assert normal.auto_trade_callback_enabled is True
        assert trade.auto_trade_callback_enabled is True
    finally:
        normal.close()
        trade.close()
        tx_trade_bridge_module._AUTO_TRADE_CALLBACK_REGISTRY.pop(id(context), None)


def test_web_lttx_route_dedupes_same_trader_event_payload():
    route = web.LttxWebRouteServer()
    client_id = "external_trade_client"
    account_id = "8885060548"
    account_type = "STOCK"
    bridge_id = "default"
    account_key = web.account_key_for(account_id, account_type, bridge_id)
    pushed = []

    def capture_push(item_client_id, event, data=None, subscription_id=None):
        pushed.append((item_client_id, event, dict(data or {}), subscription_id))

    route._push_event = capture_push
    route._account_subscribers[account_key] = {client_id}

    first_order = {
        "account_id": account_id,
        "account_type": 2,
        "stock_code": "002148.SZ",
        "order_id": 1082130908,
        "order_sysid": "1602193470177586775",
        "order_time": "212423",
        "order_type": 24,
        "order_volume": 100,
        "price": 6.8,
        "traded_volume": 0,
        "traded_price": 0.0,
        "order_status": 50,
        "m_strAccountID": account_id,
        "m_strExchangeID": "SZ",
        "m_strInstrumentID": "002148",
        "m_strOrderID": "1602193470177586775",
        "m_strOrderSysID": "",
        "m_nVolumeTotal": 0,
    }

    def make_event(data, source=None, seq=None):
        row = {
            "type": "event",
            "event": "trader:on_stock_order",
            "bridge_id": bridge_id,
            "account_id": account_id,
            "account_type": account_type,
            "data": dict(data),
        }
        if source:
            row["source"] = source
        if seq is not None:
            row["seq"] = seq
            row["received_at"] = time.time()
        return row

    route._on_client_event(make_event(first_order, source="client"))
    route._on_client_event(make_event(first_order, source="channel", seq=1))
    assert len(pushed) == 1

    second_order = dict(
        first_order,
        order_sysid="958",
        order_time="212421",
        m_strOrderSysID="958",
        m_nVolumeTotal=100,
    )
    route._on_client_event(make_event(second_order, source="client"))
    route._on_client_event(make_event(second_order, source="channel", seq=2))
    assert len(pushed) == 2
    assert pushed[0][2]["order_sysid"] == "1602193470177586775"
    assert pushed[1][2]["order_sysid"] == "958"


@pytest.mark.parametrize("raw,market,expected", [
    (50, "SZ", 11), ("50", "SZ", 11), (84, "SH", 44), (86, "SZ", 45),
    (85, "SH", 43), (85, "BJ", 43), (88, "SH", 42), (88, "SZ", 47),
    (88, "", 88), (49, "SZ", 49), (51, "SZ", 51), (999, "SZ", 999),
    (11, "SZ", 11), (5, "SZ", 5), (None, "SZ", None),
    ("unknown", "SZ", "unknown"), (87, "SZ", 46), (89, "SZ", 48), (87, "SH", 87),
])
def test_price_enum_translation(raw, market, expected):
    assert normalize_order_price_type(raw, market) == expected


@pytest.mark.parametrize("bridge_class", [TxTradeBridge, NormalQmtBridge, PipeTradeBridge, PipeNormalQmtBridge])
def test_price_type_bridge_query_sdk_and_callback_agree(bridge_class):
    bridge = bridge_class(object(), globals_dict={}, show=False)
    raw = {"m_nOrderPriceType": 50, "m_strInstrumentID": "000001", "m_strExchangeID": "SZ", "m_nRef": 123}
    encoded = bridge._format_trade_detail(raw, "order")
    assert encoded["price_type"] == xtconstant.FIX_PRICE
    assert encoded["m_nOrderPriceType"] == 50
    old_bridge = dict(encoded, price_type=50)
    order = XtOrder.from_any(old_bridge)
    assert order.price_type == 11
    assert order.m_nOrderPriceType == old_bridge["price_type"] == 50
    assert XtOrder.from_any(order).price_type == 11
    assert XtOrder.from_any(dict(old_bridge, price_type=5)).price_type == 5
    callback = XtQuantTraderCallback()
    received = []
    callback.on_stock_order = received.append
    trader = XtQuantTrader(callback=callback)
    try:
        trader._make_trader_handler("on_stock_order")(old_bridge)
        assert received[0].price_type == 11
    finally:
        trader.stop()


@pytest.fixture
def trader():
    instance = XtQuantTrader()
    yield instance
    instance.stop()


@pytest.mark.parametrize("name,raw,expected", [
    ("asset", [{"m_dAvailable": 1000}], XtAsset),
    ("orders", [{"m_nOrderPriceType": 50, "m_strInstrumentID": "000001", "m_strExchangeID": "SZ"}], XtOrder),
    ("positions", [{"m_nVolume": 100}], XtPosition),
    ("trades", [{"m_dPrice": 11.6}], XtTrade),
])
def test_query_returns_seq_without_waiting_and_callback_has_sdk_type(trader, name, raw, expected):
    entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
    threads, results = [], []

    def request(*args, **kwargs):
        threads.append(threading.current_thread().name)
        entered.set()
        assert release.wait(3)
        return raw

    def callback(value):
        threads.append(threading.current_thread().name)
        results.append(value)
        delivered.set()

    trader._trade_request = request
    try:
        seq = getattr(trader, "query_stock_%s_async" % name)(StockAccount("SIM_TEST"), callback)
        assert isinstance(seq, int) and seq > 0
        assert entered.wait(2)
        assert not delivered.is_set()
        release.set()
        assert delivered.wait(2)
        values = results[0] if isinstance(results[0], list) else [results[0]]
        assert all(isinstance(value, expected) for value in values)
        assert all(value.account_id == "SIM_TEST" for value in values)
        assert all(thread != threading.current_thread().name for thread in threads)
        assert len(results) == 1
    finally:
        release.set()


def test_query_callbacks_are_ordered_but_do_not_block_next_query(trader):
    callback_entered, release, second_queried, done = [threading.Event() for _ in range(4)]
    results = []
    trader.query_stock_asset = lambda account: account["account_id"]

    def first(value):
        callback_entered.set()
        assert release.wait(3)
        results.append(value)

    def query_second(account):
        second_queried.set()
        return account["account_id"]

    try:
        seq1 = trader.query_stock_asset_async(StockAccount("first"), first)
        assert callback_entered.wait(2)
        trader.query_stock_asset = query_second
        seq2 = trader.query_stock_asset_async(StockAccount("second"), lambda value: (results.append(value), done.set()))
        assert seq2 > seq1
        assert second_queried.wait(2)
        assert not done.is_set()
        release.set()
        assert done.wait(2)
        assert results == ["first", "second"]
    finally:
        release.set()


def test_async_query_failure_is_logged_not_reported_as_success(trader, caplog):
    called, done = [], threading.Event()

    def broken(account):
        raise RuntimeError("offline query test error")

    trader.query_stock_asset = broken
    seq = trader.query_stock_asset_async(StockAccount("SIM_TEST"), called.append)
    trader.query_stock_positions = lambda account: []
    trader.query_stock_positions_async(StockAccount("SIM_TEST"), lambda value: done.set())
    assert done.wait(2)
    assert called == []
    assert "seq=%s" % seq in caplog.text
    assert "offline query test error" in caplog.text


def test_callback_exception_does_not_kill_following_callback(trader, caplog):
    done = threading.Event()
    trader.query_stock_asset = lambda account: account

    def broken(value):
        raise ValueError("callback test error")

    trader.query_stock_asset_async(StockAccount("SIM_TEST"), broken)
    trader.query_stock_asset_async(StockAccount("SIM_TEST"), lambda value: done.set())
    assert done.wait(2)
    assert "callback test error" in caplog.text


def test_stop_suppresses_pending_results_and_does_not_reopen_clients(trader, monkeypatch):
    import cfquant.xttrader as module
    entered, release, finished = [threading.Event() for _ in range(3)]
    callbacks, queries = [], []
    monkeypatch.setattr(module, "_new_trade_client", lambda **kw: pytest.fail("must not reopen a client after stop"))

    def query(account):
        queries.append(account["account_id"])
        entered.set()
        assert release.wait(3)
        try:
            trader._get_client()
        finally:
            finished.set()

    trader.query_stock_asset = query
    try:
        trader.query_stock_asset_async(StockAccount("first"), callbacks.append)
        assert entered.wait(2)
        trader.query_stock_asset_async(StockAccount("queued"), callbacks.append)
        trader.stop()
        with pytest.raises(RuntimeError, match="stopped"):
            trader.query_stock_asset_async(StockAccount("new"), callbacks.append)
        release.set()
        assert finished.wait(2)
        assert not trader._clients
        assert callbacks == []
        assert queries == ["first"]
    finally:
        release.set()


def test_callback_can_stop_trader_without_joining_itself(trader):
    done = threading.Event()
    trader.query_stock_asset = lambda account: account

    def callback(value):
        trader.stop()
        done.set()

    trader.query_stock_asset_async(StockAccount("SIM_TEST"), callback)
    assert done.wait(2)


def test_compat_readonly_async_uses_background_query_and_preserves_seq(trader):
    entered, release, done = [threading.Event() for _ in range(3)]
    captured, results = [], []

    def query(method, body):
        captured.append((method, body))
        entered.set()
        assert release.wait(3)
        return {"SH": 2000}

    trader._compat_request = query
    try:
        seq = trader.query_new_purchase_limit_async(StockAccount("SIM_TEST"), lambda value: (results.append(value), done.set()))
        assert entered.wait(2)
        assert captured[0][0] == "query_new_purchase_limit"
        assert captured[0][1]["seq"] == seq
        assert not done.is_set()
        release.set()
        assert done.wait(2)
        assert results == [{"SH": 2000}]
    finally:
        release.set()


def test_queued_query_keeps_account_identity_at_submission(trader):
    entered, release, done = [threading.Event() for _ in range(3)]
    accounts = []

    def query(account):
        entered.set()
        assert release.wait(3)
        accounts.append(account["account_id"])
        return None

    trader.query_stock_asset = query
    account = StockAccount("SIM_ORIGINAL")
    try:
        trader.query_stock_asset_async(account, lambda value: done.set())
        assert entered.wait(2)
        account.account_id = "CHANGED_AFTER_SUBMISSION"
        release.set()
        assert done.wait(2)
        assert accounts == ["SIM_ORIGINAL"]
    finally:
        release.set()


def test_disk_hash_change_requires_restart_even_with_preserved_mtime(tmp_path):
    source = tmp_path / "bridge.py"
    source.write_text("old = True\n", encoding="utf-8")
    loaded, modified = source_sha256(source), source.stat().st_mtime
    assert module_source_state(str(source), loaded)["restart_required"] is False
    source.write_text("old = False\n", encoding="utf-8")
    os.utime(source, (modified, modified))
    result = module_source_state(str(source), loaded)
    assert result["restart_required"] is True
    assert result["module_source_state"] == "changed"


def test_old_marker_mtime_is_only_a_suspicion_not_a_loaded_hash(tmp_path):
    source = tmp_path / "bridge.py"
    source.write_text("pass\n", encoding="utf-8")
    result = module_source_state(str(source), started_at=source.stat().st_mtime - 60)
    assert result["restart_required"]
    assert result["module_source_state"] == "changed_after_start_unverified"
    assert not result["module_loaded_sha256"]
    assert module_source_state("missing-file.py")["module_source_state"] == "unknown"


def test_web_runtime_reports_track_both_channels_not_only_latest(tmp_path):
    registry = web.RuntimeVersionRegistry(persist_file=str(tmp_path / "versions.json"))
    old = tmp_path / "old.py"
    old.write_text("pass\n", encoding="utf-8")
    now = time.time()
    for channel, module_file in (("trade", str(old)), ("normal", "")):
        runtime = {"reported_at": now, "started_at": now - 60, "module_file": module_file}
        row = registry._build_report("default", channel, "same-version", "test", "lttx", runtime, {})
        registry._remember(row)
        now += 1
    latest = registry.latest("default")
    assert latest["channel_key"] == "normal"
    assert latest["restart_required"]
    assert latest["restart_channels"] == ["trade"]
    assert "QMT" in latest["message"]
    json.dumps(latest)


def test_local_query_uses_modern_readonly_flag_and_preserves_empty_data():
    calls = []
    result = {"000001.SZ": pd.DataFrame({"close": [11.6]})}
    bridge = TxTradeBridge(object(), globals_dict={"get_market_data_ex": lambda *args: calls.append(args) or result}, show=False)
    params = {"field_list": ["close"], "stock_list": ["000001.SZ"], "period": "1d", "count": 1}
    assert bridge._get_local_data(params) is result
    assert calls[0] == (["close"], ["000001.SZ"], "1d", "", "", 1, "none", True, False)
    result.clear()
    assert bridge._get_local_data(params) == {}


def test_legacy_local_query_supplies_nonempty_date_defaults():
    calls = []
    bridge = TxTradeBridge(object(), globals_dict={"get_local_data": lambda *args: calls.append(args) or {}}, show=False)
    assert bridge._get_local_data({"stock_list": ["000001.SZ"], "start_time": "", "end_time": ""}) == {"000001.SZ": {}}
    assert calls[0][1:3] == ("19700101", "22010101")


def test_older_modern_signature_falls_back_without_enabling_subscription():
    def old_modern(fields, stocks, period, start, end, count, dividend, fill):
        pytest.fail("local query must never use subscribe=True default")

    bridge = TxTradeBridge(object(), globals_dict={"get_market_data_ex": old_modern, "get_local_data": lambda *args: {}}, show=False)
    assert bridge._get_local_data({"stock_list": ["000001.SZ"]}) == {"000001.SZ": {}}


def test_local_query_does_not_swallow_internal_type_error():
    def broken(*args):
        raise TypeError("invalid data field")

    bridge = TxTradeBridge(object(), globals_dict={"get_market_data_ex": broken, "get_local_data": lambda *args: pytest.fail("must preserve errors")}, show=False)
    with pytest.raises(TypeError, match="invalid data field"):
        bridge._get_local_data({})


@pytest.mark.parametrize("action,params,expected", [
    ("xtdata.get_full_tick", {}, "trade"),
    ("xtdata.get_instrument_detail", {}, "trade"),
    ("xtdata.get_cb_info", {}, "trade"),
    ("xtdata.get_local_data", {}, "trade"),
    ("xtdata.subscribe_quote", {}, "normal"),
    ("xtdata.subscribe_whole_quote", {}, "normal"),
    ("xtdata.get_market_data_ex", {"callback_event": "probe"}, "normal"),
])
def test_advanced_route_readonly_trade_callbacks_normal(action, params, expected):
    assert web.route_channel_for_account("SIM_TEST", mode="lttx", action=action, params=params) == expected
