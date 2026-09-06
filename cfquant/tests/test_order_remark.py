import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cfquant_web_server as web
from cfquant import xtconstant
from cfquant.qmt_bridge import CfquantQmtBridge
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.tx_trade_bridge import TxTradeBridge


class DummyContext(object):
    pass


def _base_order_params(**overrides):
    params = {
        "account": {"account_id": "A123", "account_type": "STOCK"},
        "stock_code": "000001.SZ",
        "order_type": 23,
        "order_volume": 100,
        "price_type": 11,
        "price": 10.0,
    }
    params.update(overrides)
    return params


def _recording_passorder(calls):
    def passorder(*args):
        calls.append(args)
        return "ORDER-1"

    return passorder


def _recording_cancel(calls):
    def cancel(*args):
        calls.append(args)
        return True

    return cancel


def test_qmt_bridge_uses_strategy_name_as_default_remark():
    calls = []
    bridge = CfquantQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(_base_order_params(strategy_name="strategy-a"))

    assert result["order_remark"] == "strategy-a"
    assert calls[0][7] == "strategy-a"
    assert calls[0][9] == "strategy-a"


def test_qmt_bridge_remark_alias_precedes_strategy_name():
    calls = []
    bridge = CfquantQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(_base_order_params(remark="remark-a", strategy_name="strategy-a"))

    assert result["order_remark"] == "remark-a"
    assert calls[0][9] == "remark-a"


def test_tx_trade_bridge_order_remark_precedes_strategy_name():
    calls = []
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(
        _base_order_params(order_remark="remark-a", strategy_name="strategy-a"),
        {"id": "request-1"},
    )

    assert result["order_remark"] == "remark-a"
    assert calls[0][7] == "strategy-a"
    assert calls[0][9] == "remark-a"


def test_tx_trade_bridge_resolves_zero_passorder_result_to_new_order_id():
    last_order_ids = iter(("700001", "700002"))
    calls = []

    def get_last_order_id(*args):
        calls.append(args)
        return next(last_order_ids)

    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_last_order_id": get_last_order_id,
        },
    )

    result = bridge._order_stock(
        _base_order_params(strategy_name="hxy", order_remark="remark"),
        {"id": "request-1"},
    )

    assert result["request_result"] == 0
    assert result["order_id"] == 700002
    assert calls == [
        ("A123", "stock", "order", "hxy"),
        ("A123", "stock", "order", "hxy"),
    ]


def test_qmt_bridge_resolves_zero_passorder_result_to_new_order_id():
    last_order_ids = iter(("800001", "800002"))

    bridge = CfquantQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_last_order_id": lambda *args: next(last_order_ids),
        },
    )

    result = bridge._order_stock(
        _base_order_params(strategy_name="hxy", order_remark="remark"),
    )

    assert result["request_result"] == 0
    assert result["order_id"] == 800002


def test_tx_trade_bridge_async_zero_is_accepted_without_sync_order_lookup():
    last_order_id_calls = []
    detail_calls = []
    events = []

    def get_last_order_id(*args):
        last_order_id_calls.append(args)
        return "700001"

    def get_trade_detail_data(*args):
        detail_calls.append(args)
        return []

    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_last_order_id": get_last_order_id,
            "get_trade_detail_data": get_trade_detail_data,
        },
    )
    bridge._send_trader_event = lambda client_id, name, data: events.append((client_id, name, data))

    result = bridge._order_stock_async(
        _base_order_params(strategy_name="hxy", order_remark="remark", seq=21),
        {"id": "request-1", "client_id": "client-1"},
    )

    assert result == {"seq": 21, "accepted": True, "request_result": 0}
    assert len(last_order_id_calls) == 1
    assert detail_calls == []
    assert events == []
    assert len(bridge.pending_async_orders) == 1

    assert bridge._handle_async_order_callback({
        "m_strAccountID": "A123",
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
        "m_nRef": 700002,
        "m_strRemark": "other-remark",
    }) is False
    assert bridge._handle_async_order_callback({
        "m_strAccountID": "A123",
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
        "m_nRef": 700002,
        "m_strRemark": "remark",
        "m_strStrategyName": "hxy",
    }) is True
    assert events == [("client-1", "on_order_stock_async_response", {
        "account_type": "STOCK",
        "account_id": "A123",
        "order_id": 700002,
        "strategy_name": "hxy",
        "order_remark": "remark",
        "seq": 21,
    })]
    assert bridge.pending_async_orders == []


def test_qmt_bridge_async_zero_waits_for_matching_order_callback():
    events = []
    bridge = CfquantQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_last_order_id": lambda *args: "800001",
        },
    )
    bridge._send_trader_event = lambda client_id, name, data: events.append((client_id, name, data))

    result = bridge._order_stock_async(
        _base_order_params(strategy_name="hxy", order_remark="remark", seq=22),
        {"id": "request-2", "client_id": "client-2"},
    )

    assert result == {"seq": 22, "accepted": True, "request_result": 0}
    assert events == []
    assert bridge._handle_async_order_callback({
        "account_id": "A123",
        "stock_code": "000001.SZ",
        "order_id": 800002,
        "order_remark": "remark",
    }) is True
    assert events[0][2] == {
        "account_type": "STOCK",
        "account_id": "A123",
        "order_id": 800002,
        "strategy_name": "hxy",
        "order_remark": "remark",
        "seq": 22,
    }


def test_tx_trade_bridge_async_explicit_failure_is_not_registered():
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": lambda *args: -1},
    )

    result = bridge._order_stock_async(
        _base_order_params(seq=23),
        {"id": "request-3", "client_id": "client-3"},
    )

    assert result == {"seq": -1, "accepted": False, "request_result": -1}
    assert bridge.pending_async_orders == []


def test_normal_bridge_turns_real_order_callback_into_xtorderresponse():
    class FakeTx(object):
        def __init__(self):
            self.pushes = []

        def push(self, *args):
            self.pushes.append(args)
            return 0

    events = []
    bridge = NormalQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: None,
            "get_last_order_id": lambda *args: "700001",
        },
    )
    bridge.tx = FakeTx()
    bridge._send_trader_event = lambda client_id, name, data: events.append((client_id, name, data))
    bridge._order_stock_async(
        _base_order_params(strategy_name="hxy", order_remark="remark", seq=24),
        {"id": "request-4", "client_id": "client-4"},
    )

    bridge.publish_callback_event("trader:on_stock_order", {
        "m_strAccountID": "A123",
        "m_nAccountType": 2,
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
        "m_nRef": 700002,
        "m_strOrderRef": "700002",
        "m_strOrderSysID": "SYS-2",
        "m_strRemark": "",
        "m_strStrategyName": "",
    })

    response_events = [item for item in events if item[1] == "on_order_stock_async_response"]
    assert response_events == [("client-4", "on_order_stock_async_response", {
        "account_type": "STOCK",
        "account_id": "A123",
        "order_id": 700002,
        "strategy_name": "hxy",
        "order_remark": "remark",
        "seq": 24,
    })]
    callback_payload = json.loads(bridge.tx.pushes[0][1])
    assert callback_payload["data"]["order_remark"] == "remark"
    assert callback_payload["data"]["strategy_name"] == "hxy"


def test_tx_trade_bridge_never_exposes_zero_as_order_id_when_lookup_is_stale():
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_last_order_id": lambda *args: "700001",
        },
    )

    result = bridge._order_stock(
        _base_order_params(find_order_wait=0),
        {"id": "request-1"},
    )

    assert result["order_id"] == -1


def test_tx_trade_bridge_falls_back_to_matching_order_detail_for_zero_result():
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_trade_detail_data": lambda *args: [{
                "m_nRef": 700003,
                "m_strInstrumentID": "000001",
                "m_strExchangeID": "SZ",
                "m_strRemark": "remark",
            }],
        },
    )

    result = bridge._order_stock(
        _base_order_params(order_remark="remark", find_order_wait=0),
        {"id": "request-1"},
    )

    assert result["order_id"] == 700003


def test_tx_trade_bridge_ignores_system_order_id_when_resolving_sync_order():
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_last_order_id": lambda *args: "xt700003",
            "get_trade_detail_data": lambda *args: [{
                "m_nRef": 700003,
                "m_strOrderSysID": "xt700003",
                "m_strInstrumentID": "000001",
                "m_strExchangeID": "SZ",
                "m_strRemark": "remark",
            }],
        },
    )

    result = bridge._order_stock(
        _base_order_params(order_remark="remark", find_order_wait=0),
        {"id": "request-1"},
    )

    assert result["order_id"] == 700003
    assert isinstance(result["order_id"], int)


def test_query_order_restores_strategy_name_from_submitted_remark():
    raw_order = {
        "m_strAccountID": "A123",
        "m_nRef": 700004,
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
        "m_strRemark": "remark",
        "m_strStrategyName": "",
    }
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={
            "passorder": lambda *args: 0,
            "get_trade_detail_data": lambda *args: [raw_order],
        },
    )

    bridge._order_stock(
        _base_order_params(strategy_name="hxy", order_remark="remark", find_order_wait=0),
        {"id": "request-1"},
    )
    orders = bridge._query_trade_detail(
        {"account": {"account_id": "A123", "account_type": "STOCK"}},
        "order",
    )

    assert orders[0]["strategy_name"] == "hxy"
    assert orders[0]["m_strStrategyName"] == "hxy"


def test_big_qmt_order_fields_map_to_miniqmt_shape_and_json_primitives():
    class ScalarBytes(object):
        def __init__(self, value):
            self.value = value

        def item(self):
            return self.value

    class BigQmtOrder(object):
        m_strAccountID = b"A123"
        m_strInstrumentID = b"000001"
        m_strExchangeID = b"SZ"
        m_strInstrumentName = "平安银行".encode("gbk")
        m_nRef = 719000001
        m_strOrderRef = b"719000001"
        m_strOrderSysID = ScalarBytes(b"SYS-1")
        m_nOrderPriceType = 11
        m_nOrderType = 0
        m_nOffsetFlag = 49
        m_dLimitPrice = 10.5
        m_nVolumeTotalOriginal = 100
        m_nVolumeTraded = 0
        m_nOrderStatus = 50
        m_strErrorMsg = "已报".encode("gbk")
        m_strInsertDate = b"20260906"
        m_strInsertTime = b"09:35:01"
        m_strRemark = b"remark"

    order = BigQmtOrder()
    tx_row = TxTradeBridge(DummyContext(), show=False, globals_dict={})._format_trade_detail(order, "order")
    qmt_row = CfquantQmtBridge(DummyContext(), show=False, globals_dict={})._format_trade_detail(order, "ORDER")

    for row in (tx_row, qmt_row):
        assert row["order_id"] == 719000001
        assert row["m_nOrderID"] == 719000001
        assert row["m_strOrderID"] == "719000001"
        assert row["order_sysid"] == "SYS-1"
        assert row["order_type"] == xtconstant.STOCK_SELL
        assert row["instrument_name"] == "平安银行"
        assert row["status_msg"] == "已报"
        assert json.loads(json.dumps(row, ensure_ascii=False))["order_id"] == 719000001


def test_tx_trade_bridge_batch_keeps_row_strategy_name_as_remark():
    calls = []
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock_batch(
        {
            "account": {"account_id": "A123", "account_type": "STOCK"},
            "orders": [
                _base_order_params(strategy_name="strategy-a"),
            ],
        },
        {"id": "batch-1"},
    )

    assert result["submitted"] == 1
    assert calls[0][7] == "strategy-a"
    assert calls[0][9] == "strategy-a"


def test_qmt_bridge_maps_credit_stock_buy_to_big_qmt_collateral_buy():
    calls = []
    bridge = CfquantQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(
        _base_order_params(
            account={"account_id": "C123", "account_type": "CREDIT"},
            order_type=xtconstant.CREDIT_BUY,
        )
    )

    assert calls[0][0] == xtconstant.QMT_CREDIT_BUY
    assert result["order_type"] == xtconstant.QMT_CREDIT_BUY
    assert result["account_type"] == "CREDIT"


def test_tx_trade_bridge_credit_action_precedes_order_type():
    calls = []
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(
        _base_order_params(
            account={"account_id": "C123", "account_type": xtconstant.CREDIT_ACCOUNT},
            order_type=xtconstant.CREDIT_BUY,
            credit_action="credit_fin_buy",
        ),
        {"id": "request-1"},
    )

    assert calls[0][0] == xtconstant.CREDIT_FIN_BUY
    assert result["order_type"] == xtconstant.CREDIT_FIN_BUY
    assert result["account_type"] == "CREDIT"


def test_tx_trade_bridge_maps_miniqmt_credit_special_to_big_qmt_optype():
    calls = []
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(
        _base_order_params(
            account={"account_id": "C123", "account_type": "CREDIT"},
            order_type=xtconstant.CREDIT_FIN_BUY_SPECIAL,
        ),
        {"id": "request-1"},
    )

    assert calls[0][0] == xtconstant.QMT_CREDIT_FIN_BUY_SPECIAL
    assert result["order_type"] == xtconstant.QMT_CREDIT_FIN_BUY_SPECIAL


def test_web_credit_order_action_resolution_and_confirmation():
    action = web.resolve_order_action("CREDIT", "buy", credit_action="credit_slo_sell")
    assert action["side"] == "sell"
    assert action["order_type"] == web.CREDIT_SLO_SELL
    assert action["credit_action"] == "credit_slo_sell"

    legacy = web.resolve_order_action("CREDIT", "buy", explicit_order_type=40)
    assert legacy["order_type"] == web.CREDIT_FIN_BUY_SPECIAL
    assert legacy["credit_action"] == "credit_fin_buy_special"

    assert web.order_confirmation_options(
        "CREDIT",
        "buy",
        "000001.SZ",
        100,
        10,
        credit_action="credit_fin_buy",
    ) == ["CREDIT_FIN_BUY 000001.SZ 100 @ 10.000"]


def test_web_submit_credit_order_passes_credit_action(monkeypatch):
    captured = {}

    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "default")
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})

    def fake_account_request(account_id, bridge_id, channel, action, params, **kwargs):
        captured.update({
            "account_id": account_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "action": action,
            "params": params,
            "kwargs": kwargs,
        })
        return {
            "bridge_id": bridge_id,
            "channel": "trade",
            "mode": "ctypes",
            "fallback": False,
            "fallback_reason": "",
            "result": {"order_id": "ORDER-1"},
        }

    monkeypatch.setattr(web, "account_request", fake_account_request)

    result = web.submit_credit_order({
        "account_id": "C123",
        "stock_code": "000001.SZ",
        "price": 10,
        "volume": 100,
        "credit_action": "credit_fin_buy",
        "confirm_text": "CREDIT_FIN_BUY 000001.SZ 100 @ 10.000",
    })

    assert result["account_type"] == "CREDIT"
    assert result["order_type"] == web.CREDIT_FIN_BUY
    assert result["credit_action"] == "credit_fin_buy"
    assert captured["action"] == "xttrader.order_stock"
    assert captured["params"]["order_type"] == web.CREDIT_FIN_BUY
    assert captured["params"]["credit_action"] == "credit_fin_buy"


def test_web_submit_credit_batch_order_maps_default_and_row_actions(monkeypatch):
    captured = {}

    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "default")
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})

    def fake_batch_request(account_id, bridge_id, channel, params, **kwargs):
        captured.update({
            "account_id": account_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "params": params,
            "kwargs": kwargs,
        })
        return {
            "bridge_id": bridge_id,
            "channel": "trade",
            "mode": "ctypes",
            "fallback": False,
            "fallback_reason": "",
            "result": {"submitted": 2},
        }

    monkeypatch.setattr(web, "account_batch_order_request", fake_batch_request)

    result = web.submit_credit_batch_orders({
        "account_id": "C123",
        "credit_action": "credit_fin_buy",
        "confirm_text": "BATCH 2",
        "orders": [
            {"stock_code": "000001.SZ", "price": 10, "volume": 100},
            {"stock_code": "600000.SH", "price": 8.5, "volume": 200, "credit_action": "credit_slo_sell"},
        ],
    })

    orders = captured["params"]["orders"]
    assert result["account_type"] == "CREDIT"
    assert orders[0]["order_type"] == web.CREDIT_FIN_BUY
    assert orders[0]["credit_action"] == "credit_fin_buy"
    assert orders[0]["side"] == "buy"
    assert orders[1]["order_type"] == web.CREDIT_SLO_SELL
    assert orders[1]["credit_action"] == "credit_slo_sell"
    assert orders[1]["side"] == "sell"


def test_tx_trade_bridge_future_order_keeps_miniqmt_optype():
    calls = []
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(
        _base_order_params(
            account={"account_id": "F123", "account_type": xtconstant.FUTURE_ACCOUNT},
            stock_code="IF2601.IF",
            order_type=xtconstant.FUTURE_OPEN_SHORT,
            order_volume=1,
        ),
        {"id": "request-1"},
    )

    assert calls[0][0] == xtconstant.FUTURE_OPEN_SHORT
    assert result["order_type"] == xtconstant.FUTURE_OPEN_SHORT
    assert result["account_type"] == "FUTURE"


def test_qmt_bridge_stock_option_maps_miniqmt_to_big_qmt_optype():
    calls = []
    bridge = CfquantQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(
        _base_order_params(
            account={"account_id": "O123", "account_type": xtconstant.STOCK_OPTION_ACCOUNT},
            stock_code="10000001.SH",
            order_type=xtconstant.STOCK_OPTION_SELL_OPEN,
            order_volume=1,
        )
    )

    assert calls[0][0] == xtconstant.QMT_STOCK_OPTION_SELL_OPEN
    assert result["order_type"] == xtconstant.QMT_STOCK_OPTION_SELL_OPEN
    assert result["account_type"] == "STOCK_OPTION"


def test_tx_trade_bridge_stock_option_action_maps_to_big_qmt_optype():
    calls = []
    bridge = TxTradeBridge(
        DummyContext(),
        show=False,
        globals_dict={"passorder": _recording_passorder(calls)},
    )

    result = bridge._order_stock(
        _base_order_params(
            account={"account_id": "O123", "account_type": "STOCK_OPTION"},
            stock_code="10000001.SH",
            order_action="stock_option_buy_close",
            order_volume=1,
        ),
        {"id": "request-1"},
    )

    assert calls[0][0] == xtconstant.QMT_STOCK_OPTION_BUY_CLOSE
    assert result["order_type"] == xtconstant.QMT_STOCK_OPTION_BUY_CLOSE


def test_qmt_bridge_cancel_uses_derivative_account_type():
    calls = []
    bridge = CfquantQmtBridge(
        DummyContext(),
        show=False,
        globals_dict={"cancel": _recording_cancel(calls)},
    )

    result = bridge._cancel_order_stock({
        "account": {"account_id": "F123", "account_type": xtconstant.FUTURE_ACCOUNT},
        "order_id": "ORDER-1",
    })

    assert calls[0][1] == "F123"
    assert calls[0][2] == "FUTURE"
    assert result["account_type"] == "FUTURE"


def test_web_derivative_account_type_and_order_action_resolution():
    assert web.normalize_account_type("FUTURE_ACCOUNT") == "FUTURE"
    assert web.normalize_account_type("OPTION") == "STOCK_OPTION"

    future_action = web.resolve_order_action("FUTURE", "sell", order_action="future_open_short")
    assert future_action["side"] == "sell"
    assert future_action["order_type"] == xtconstant.FUTURE_OPEN_SHORT
    assert future_action["order_action"] == "future_open_short"

    option_action = web.resolve_order_action(
        "STOCK_OPTION",
        "sell",
        explicit_order_type=xtconstant.STOCK_OPTION_SELL_OPEN,
    )
    assert option_action["side"] == "sell"
    assert option_action["order_type"] == xtconstant.STOCK_OPTION_SELL_OPEN
    assert option_action["order_action"] == "stock_option_sell_open"

    assert web.order_confirmation_options(
        "STOCK_OPTION",
        "sell",
        "10000001.SH",
        1,
        0,
        order_action="stock_option_sell_open",
    ) == ["STOCK_OPTION_SELL_OPEN 10000001.SH 1 @ 0.000"]


def test_web_submit_stock_option_order_passes_order_action(monkeypatch):
    captured = {}

    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "default")
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})

    def fake_account_request(account_id, bridge_id, channel, action, params, **kwargs):
        captured.update({
            "account_id": account_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "action": action,
            "params": params,
            "kwargs": kwargs,
        })
        return {
            "bridge_id": bridge_id,
            "channel": "trade",
            "mode": "ctypes",
            "fallback": False,
            "fallback_reason": "",
            "result": {"order_id": "ORDER-1"},
        }

    monkeypatch.setattr(web, "account_request", fake_account_request)

    result = web.submit_stock_option_order({
        "account_id": "O123",
        "stock_code": "10000001.SH",
        "price_type": xtconstant.LATEST_PRICE,
        "price": 0,
        "volume": 1,
        "order_action": "stock_option_sell_open",
        "confirm_text": "STOCK_OPTION_SELL_OPEN 10000001.SH 1 @ 0.000",
    })

    assert result["account_type"] == "STOCK_OPTION"
    assert result["order_type"] == xtconstant.STOCK_OPTION_SELL_OPEN
    assert result["order_action"] == "stock_option_sell_open"
    assert captured["action"] == "xttrader.order_stock"
    assert captured["params"]["price_type"] == xtconstant.LATEST_PRICE
    assert captured["params"]["order_type"] == xtconstant.STOCK_OPTION_SELL_OPEN
    assert captured["params"]["order_action"] == "stock_option_sell_open"


def test_web_submit_future_batch_orders_maps_default_and_row_actions(monkeypatch):
    captured = {}

    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "default")
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})

    def fake_batch_request(account_id, bridge_id, channel, params, **kwargs):
        captured.update({
            "account_id": account_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "params": params,
            "kwargs": kwargs,
        })
        return {
            "bridge_id": bridge_id,
            "channel": "trade",
            "mode": "ctypes",
            "fallback": False,
            "fallback_reason": "",
            "result": {"submitted": 2},
        }

    monkeypatch.setattr(web, "account_batch_order_request", fake_batch_request)

    result = web.submit_future_batch_orders({
        "account_id": "F123",
        "order_action": "future_open_long",
        "confirm_text": "BATCH 2",
        "orders": [
            {"stock_code": "IF2601.IF", "price": 4200, "volume": 1},
            {"stock_code": "IF2601.IF", "price": 4200, "volume": 1, "order_action": "future_open_short"},
        ],
    })

    orders = captured["params"]["orders"]
    assert result["account_type"] == "FUTURE"
    assert orders[0]["order_type"] == xtconstant.FUTURE_OPEN_LONG
    assert orders[0]["order_action"] == "future_open_long"
    assert orders[0]["side"] == "buy"
    assert orders[1]["order_type"] == xtconstant.FUTURE_OPEN_SHORT
    assert orders[1]["order_action"] == "future_open_short"
    assert orders[1]["side"] == "sell"
