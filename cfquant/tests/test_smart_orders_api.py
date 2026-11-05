import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from cfquant import cftrader
from cfquant.algo_broker import execution_time
from cfquant.planning_broker import PlanningBroker
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
from cfquant.tests.test_smart_orders import env, ACCOUNT, CODE


def test_planning_broker_uses_routed_native_account_fields_and_calendar():
    calls = []
    def trade(account, action, params):
        calls.append((action, params))
        if action.endswith("query_stock_asset"):
            return dict(m_dAvailable=20000, m_dBalance=100000)
        if action.endswith("query_stock_positions"):
            return [dict(stock_code=CODE, volume=1000, can_use_volume=500)]
        return [dict(stock_code=CODE, order_id=1, order_type=23, order_volume=200, traded_volume=100, order_status=55),
                dict(stock_code=CODE, order_id=2, order_type=23, order_volume=200, traded_volume=0, order_status=54)]
    def market(action, params):
        if action.endswith("get_instrument_detail"):
            return dict(PriceTick=.01)
        return ["20261105", "20261106", "20261109"]
    broker = PlanningBroker(trade, market)
    snap = broker.snapshot(ACCOUNT, CODE)
    assert snap["total_asset"] == 100000 and snap["available_cash"] == 20000
    assert snap["current_volume"] == 1000 and snap["sellable_volume"] == 500
    assert snap["pending_buy_volume"] == 100
    assert all(params["account"] == ACCOUNT and params["stock_code"] == CODE for _, params in calls)
    assert broker.session_end(CODE, execution_time("2026-11-05T11:35:00")) is None
    assert broker.session_end(CODE, execution_time("2026-11-07T10:00:00")) is None
    assert broker.session_end(CODE, execution_time("2026-11-05T10:00:00")) == execution_time("2026-11-05T11:30:00")
    # Calendar request starts after the opening day; fixture honors that range.
    broker.market_request = lambda action, params: ["20261106", "20261109"]
    at = broker.holding_deadline(CODE, dict(opened_at=execution_time("2026-11-05T10:00:00"), trading_days=2, exit_time="14:50"))
    assert at == execution_time("2026-11-09T14:50:00")


def test_sdk_shortcuts_and_plan_controls_share_account_and_stable_request(monkeypatch):
    calls = []
    def rpc(action, params):
        calls.append((action, params))
        return {"algo_id": "plan_test"} if "plan" in action else "condition_test"
    monkeypatch.setattr(cftrader, "_algo_rpc", rpc)
    trader = XtQuantTrader.__new__(XtQuantTrader)
    trader._resolve_account = lambda account: account
    api = cftrader.CfQuantTrader(trader)
    account = StockAccount("TEST_ONLY", "STOCK")
    calls_before = len(calls)
    assert api.calculate_position(stock_code=CODE, entry_price=10, method="cash_amount", cash_amount=10000)["quantity"] == 900
    assert len(calls) == calls_before
    for name, args, expected in (
        ("order_stop_loss", [9, 8.8], "stop_loss"), ("order_take_profit", [12, 11], "take_profit"),
        ("order_trailing_stop", [.05, 8.8], "trailing_stop"),
        ("order_breakeven_stop", [10, .1, 9], "breakeven_stop"),
        ("order_time_exit", ["2026-11-06T14:50:00", 8.8], "time_exit")):
        key = getattr(api, name)(account, CODE, 1000, *args, request_key="stable-" + name)
        assert calls[-1][0] == "cftrader.order_condition"
        assert calls[-1][1]["conditions"][0]["type"] == expected
        api.query_algo(key)
        assert calls[-1][1]["account"]["account_id"] == "TEST_ONLY"
    plan = api.preview_order_plan(account, CODE, dict(method="cash_amount", entry_price=10, cash_amount=1000))
    for name in ("submit_order_plan", "query_order_plan", "cancel_order_plan"):
        getattr(api, name)(plan["algo_id"])
        assert calls[-1][1]["account"]["account_id"] == "TEST_ONLY"
        assert calls[-1][1]["plan_id"] == "plan_test"


def test_http_routes_authentication_plan_workflow_and_rpc(env, monkeypatch):
    import cfquant_web_server as web
    monkeypatch.setattr(web, "WEB_CONFIG", SimpleNamespace(web_auth_enabled=lambda: False, api_key=lambda: "test-smart-key"))
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "")
    monkeypatch.setattr(web, "account_key_for", lambda *args: "")
    monkeypatch.setattr(web, "algorithm_engine", lambda: env.engine)
    class Handler(web.CfquantWebHandler):
        def _request_allowed(self):
            return True
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def post(path, payload, auth=True):
        conn = HTTPConnection(*server.server_address, timeout=5)
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["X-API-Key"] = "test-smart-key"
        try:
            conn.request("POST", "/api/trade/" + path, json.dumps(payload), headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()
    try:
        sizing = dict(stock_code=CODE, entry_price=10, stop_price=9, method="risk_percent", total_asset=100000, risk_percent=.02)
        assert post("position/calculate", sizing, False)[0] == 401
        status, result = post("position/calculate", sizing)
        assert status == 200 and result["data"]["quantity"] == 1900
        assert post("position/calculate", dict(sizing, stop_price=11))[0] == 400
        condition = dict(account=ACCOUNT, stock_code=CODE, order_volume=1000,
                         conditions=[dict(type="stop_loss", price=9)], execution=dict(limit_price=8.8))
        status, result = post("condition/submit", condition)
        assert status == 200, result
        cid = result["data"]
        assert post("algo/query", dict(account=ACCOUNT, algo_id=cid))[1]["data"]["kind"] == "condition"
        assert post("algo/pause", dict(account=ACCOUNT, algo_id=cid))[1]["data"]["status"] == "PAUSED"
        assert post("algo/resume", dict(account=ACCOUNT, algo_id=cid))[0] == 200
        body = dict(account=ACCOUNT, stock_code=CODE, sizing=dict(entry_price=10, stop_price=9, risk_percent=.02))
        status, result = post("plan/preview", body)
        assert status == 200, result
        pid = result["data"]["algo_id"]
        control = dict(account=ACCOUNT, plan_id=pid)
        assert post("plan/submit", control)[1]["data"]["status"] == "SUBMITTED"
        assert post("plan/query", control)[1]["data"]["entry_id"]
        assert len(post("plan/list", dict(account=ACCOUNT))[1]["data"]) == 1
        assert post("plan/query", dict(account=ACCOUNT, plan_id=cid))[0] == 400
        assert post("plan/cancel", control)[1]["data"]["cancel_requested"]
        assert post("plan/unknown", control)[0] == 400
        result, meta = web.route_external_lttx_request(dict(action="cftrader.calculate_position", params=sizing))
        assert result["quantity"] == 1900 and meta["route"] == "algorithm_service"
        result, _ = web.route_external_lttx_request(dict(action="cftrader.query_order_plan", params=control))
        assert result["algo_id"] == pid
        assert env.broker.sent == []  # Engine scheduler is intentionally not started in this test.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
