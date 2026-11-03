import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from cfquant import cftrader
from cfquant.algo_broker import RoutedAlgoBroker, SHANGHAI, execution_time, trading_windows
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount


def test_effective_duration_skips_lunch_and_auction():
    start = execution_time("2026-11-03T11:29:00")
    windows = trading_windows(start, 180)
    assert windows == [[start, start + 60], [execution_time("2026-11-03T13:00:00"), execution_time("2026-11-03T13:02:00")]]
    with pytest.raises(ValueError, match="does not fit"):
        trading_windows(execution_time("2026-11-03T14:56:00"), 120)


def test_historical_vwap_excludes_execution_day_and_uses_selected_minutes():
    requested = []
    frame = pd.DataFrame({"volume":[10,30,99999]}, index=["20261102093000","20261102093100","20261103093000"])
    def market(action, params):
        requested.append((action, params))
        return {"600000.SH":frame}
    broker = RoutedAlgoBroker(None, market)
    start = execution_time("2026-11-03T09:30:00")
    profile = broker._historical_profile({"stock_code":"600000.SH", "interval_seconds":60}, [[start,start+120]], start)
    assert profile == [10,30]
    assert requested[0][1]["end_time"] == "20261102235959"


def test_prepare_checks_requested_calendar_date_and_instrument_rules():
    dates = ["20261103"]
    def market(action, params):
        return dates if action.endswith("get_trading_dates") else {"PriceTick":.01}
    broker = RoutedAlgoBroker(None, market)
    config = dict(account={"account_type":"STOCK"}, stock_code="688001.SH", order_type=23, algo="TWAP", duration_seconds=60)
    now = execution_time("2026-11-03T09:30:00")
    result = broker.prepare(config, now)
    assert result["min_child_volume"] == 200 and result["volume_step"] == 1
    dates[:] = ["20261102"]
    with pytest.raises(ValueError, match="not a trading day"):
        broker.prepare(config, now)


def test_child_submission_uses_one_batch_without_retry_on_timeout():
    requests = []
    def trade(account, action, params):
        requests.append((action,params))
        raise TimeoutError("lost ack")
    broker = RoutedAlgoBroker(trade, None)
    config = dict(stock_code="600000.SH", order_type=23, algo="TWAP")
    with pytest.raises(TimeoutError):
        broker.submit({"account_id":"TEST_ONLY"}, config, dict(remark="algo:1",volume=100,price=10))
    assert len(requests) == 1
    assert requests[0][0] == "cftrader.order_stock_batch"
    assert requests[0][1]["orders"][0]["order_remark"] == "algo:1"


def test_sdk_algorithms_use_service_and_remember_account(monkeypatch):
    calls = []
    def rpc(action, params):
        calls.append((action,params))
        return "algo_test" if action.endswith("order_algo") else {"status":"PAUSED"}
    monkeypatch.setattr(cftrader, "_algo_rpc", rpc)
    trader = XtQuantTrader.__new__(XtQuantTrader)
    trader._resolve_account = lambda account:account
    api = cftrader.CfQuantTrader(trader)
    account = StockAccount("TEST_ONLY","STOCK")
    algo = api.order_pov(account,"600000.SH",23,1000,10,.1,request_key="stable")
    assert algo == "algo_test"
    assert calls[0][1]["algo"] == "POV" and calls[0][1]["participation_rate"] == .1
    assert calls[0][1]["request_key"] == "stable"
    api.pause_algo(algo)
    assert calls[1][1]["account"]["account_id"] == "TEST_ONLY"


def test_order_reconciliation_queries_the_configured_market_bridge(monkeypatch):
    import cfquant_web_server as web
    calls = []
    monkeypatch.setattr(web, "account_market_route_config", lambda **kwargs: ({}, {"SH":{"bridge_id":"sh-child"}}))
    monkeypatch.setattr(web, "resolve_account_mode", lambda *args, **kwargs:"lite")
    monkeypatch.setattr(web, "route_channel_for_account", lambda *args, **kwargs:"trade")
    monkeypatch.setattr(web, "CLIENTS", SimpleNamespace(request=lambda *args, **kwargs:calls.append(args) or []))
    account = dict(account_id="TEST_ONLY",account_type="STOCK",bridge_id="base")
    web._algo_trade_request(account,"xttrader.query_stock_orders",dict(account=account,stock_code="600000.SH"))
    assert calls[0][:3] == ("sh-child","trade","xttrader.query_stock_orders")


def test_external_algorithm_route_restores_account_identity(monkeypatch):
    import cfquant_web_server as web
    submitted = []
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs:"test-bridge")
    monkeypatch.setattr(web, "account_key_for", lambda *args:"test-key")
    engine = SimpleNamespace(submit=lambda params:submitted.append(params) or "algo_test",
                             query=lambda algo,account:{"algo_id":algo,"account":account})
    monkeypatch.setattr(web, "algorithm_engine", lambda:engine)
    result, meta = web.route_external_lttx_request(dict(action="cftrader.order_algo",
        params=dict(account={"account_id":"TEST_ONLY","account_type":"STOCK"},algo="TWAP",channel="trade")))
    assert result == "algo_test" and meta["route"] == "algorithm_service"
    assert submitted[0]["account"]["bridge_id"] == "test-bridge"
    assert submitted[0]["account"]["account_key"] == "test-key"
    assert "channel" not in submitted[0]
    task = web.algorithm_request("cftrader.query_algo",dict(account={"account_id":"TEST_ONLY","account_type":"STOCK"},algo_id=result))
    assert task["account"] == submitted[0]["account"]
