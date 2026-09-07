import pytest

from cfquant import xtconstant
from cfquant.qmt_bridge import CfquantQmtBridge
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import (
    StockAccount,
    XtOrder,
    XtOrderResponse,
    filter_cancelable_orders,
    is_cancelable_order_status,
)


def _order(status, order_id=None):
    return {
        "order_id": order_id or "order-%s" % status,
        "stock_code": "000001.SZ",
        "order_status": status,
    }


def test_cancelable_order_status_set_matches_qmt_active_statuses():
    assert is_cancelable_order_status(xtconstant.ORDER_UNREPORTED)
    assert is_cancelable_order_status(str(xtconstant.ORDER_WAIT_REPORTING))
    assert is_cancelable_order_status(float(xtconstant.ORDER_REPORTED))
    assert is_cancelable_order_status("ORDER_PART_SUCC")
    assert not is_cancelable_order_status(xtconstant.ORDER_REPORTED_CANCEL)
    assert not is_cancelable_order_status(xtconstant.ORDER_PARTSUCC_CANCEL)
    assert not is_cancelable_order_status(xtconstant.ORDER_SUCCEEDED)
    assert not is_cancelable_order_status(xtconstant.ORDER_CANCELED)
    assert not is_cancelable_order_status(xtconstant.ORDER_JUNK)


def test_filter_cancelable_orders_keeps_only_active_statuses():
    orders = [
        _order(xtconstant.ORDER_UNREPORTED),
        _order(xtconstant.ORDER_WAIT_REPORTING),
        _order(xtconstant.ORDER_REPORTED),
        _order(xtconstant.ORDER_REPORTED_CANCEL),
        _order(xtconstant.ORDER_PARTSUCC_CANCEL),
        _order(xtconstant.ORDER_PART_CANCEL),
        _order(xtconstant.ORDER_CANCELED),
        _order(xtconstant.ORDER_PART_SUCC),
        _order(xtconstant.ORDER_SUCCEEDED),
        _order(xtconstant.ORDER_JUNK),
        _order(xtconstant.ORDER_UNKNOWN),
    ]

    result = filter_cancelable_orders(orders)

    assert [item["order_status"] for item in result] == [
        xtconstant.ORDER_UNREPORTED,
        xtconstant.ORDER_WAIT_REPORTING,
        xtconstant.ORDER_REPORTED,
        xtconstant.ORDER_PART_SUCC,
    ]


def test_query_stock_orders_applies_cancelable_only_filter(monkeypatch):
    account = StockAccount("A123")
    returned_orders = [
        _order(xtconstant.ORDER_REPORTED, "can-cancel"),
        _order(xtconstant.ORDER_SUCCEEDED, "done"),
    ]
    calls = []

    def fake_trade_request(self, action, params=None, timeout=None):
        calls.append((action, params, timeout))
        return returned_orders

    monkeypatch.setattr(XtQuantTrader, "_trade_request", fake_trade_request)
    trader = XtQuantTrader()

    all_orders = trader.query_stock_orders(account, cancelable_only=False)
    cancelable_orders = trader.query_stock_orders(account, cancelable_only=True)

    assert [order.order_id for order in all_orders] == ["can-cancel", "done"]
    assert [order.order_id for order in cancelable_orders] == ["can-cancel"]
    assert calls[0][1]["cancelable_only"] is False
    assert calls[1][1]["cancelable_only"] is True


def test_query_stock_orders_treats_string_false_as_not_cancelable_only(monkeypatch):
    account = StockAccount("A123")
    returned_orders = [
        _order(xtconstant.ORDER_REPORTED, "can-cancel"),
        _order(xtconstant.ORDER_SUCCEEDED, "done"),
    ]
    calls = []

    def fake_trade_request(self, action, params=None, timeout=None):
        calls.append((action, params, timeout))
        return returned_orders

    monkeypatch.setattr(XtQuantTrader, "_trade_request", fake_trade_request)
    trader = XtQuantTrader()

    orders = trader.query_stock_orders(account, cancelable_only="false")

    assert [order.order_id for order in orders] == ["can-cancel", "done"]
    assert calls[0][1]["cancelable_only"] is False


def test_xtorder_uses_big_qmt_order_reference_as_miniqmt_order_id():
    order = XtOrder.from_any({
        "m_nRef": 719000001,
        "m_strOrderRef": "719000001",
        "m_strOrderSysID": "SYS-1",
        "m_strErrorMsg": "已报",
    })

    assert order.order_id == 719000001
    assert order.order_sysid == "SYS-1"
    assert order.status_msg == "已报"


def test_xtorder_response_uses_big_qmt_order_reference():
    response = XtOrderResponse.from_any({
        "m_strOrderRef": "719000002",
        "m_strRemark": "remark-a",
        "m_strStrategyName": "strategy-a",
        "m_nSeq": 9,
    })

    assert response.order_id == 719000002
    assert response.order_remark == "remark-a"
    assert response.strategy_name == "strategy-a"
    assert response.seq == 9


def test_order_stock_async_returns_request_seq_or_minus_one(monkeypatch):
    account = StockAccount("A123")
    responses = iter((
        {"seq": 1, "accepted": True, "request_result": 0},
        {"seq": -1, "accepted": False, "request_result": -1},
    ))

    monkeypatch.setattr(
        XtQuantTrader,
        "_trade_request",
        lambda self, action, params=None, timeout=None: next(responses),
    )
    trader = XtQuantTrader()

    seq = trader.order_stock_async(account, "000001.SZ", 23, 100, 11, 10.0, "hxy", "remark")
    failed = trader.order_stock_async(account, "000001.SZ", 23, 100, 11, 10.0, "hxy", "remark")

    assert isinstance(seq, int) and seq > 0
    assert failed == -1


def test_order_stock_async_is_completed_from_cross_process_order_callback(monkeypatch):
    class Callback(object):
        def __init__(self):
            self.orders = []
            self.responses = []

        def on_stock_order(self, order):
            self.orders.append(order)

        def on_order_stock_async_response(self, response):
            self.responses.append(response)

    monkeypatch.setattr(
        XtQuantTrader,
        "_trade_request",
        lambda self, action, params=None, timeout=None: {
            "seq": params.get("seq"),
            "accepted": True,
            "request_result": 0,
        },
    )
    callback = Callback()
    account = StockAccount("A123")
    trader = XtQuantTrader(callback=callback, account=account)

    seq = trader.order_stock_async(account, "000001.SZ", 23, 100, 11, 10.0, "hxy", "remark")
    trader._make_trader_handler("on_stock_order")({
        "account_id": "A123",
        "stock_code": "000001.SZ",
        "order_id": 719000010,
        "order_remark": "",
        "strategy_name": "",
    })
    trader._make_trader_handler("on_order_stock_async_response")({
        "account_id": "A123",
        "order_id": 719000010,
        "strategy_name": "hxy",
        "order_remark": "remark",
        "seq": seq,
    })

    assert callback.orders[0].order_remark == "remark"
    assert callback.orders[0].strategy_name == "hxy"
    assert len(callback.responses) == 1
    assert vars(callback.responses[0]) == {
        "account_type": xtconstant.SECURITY_ACCOUNT,
        "account_id": "A123",
        "order_id": 719000010,
        "strategy_name": "hxy",
        "order_remark": "remark",
        "seq": seq,
    }


def test_xtorderresponse_canonical_payload_has_miniqmt_fields_only():
    response = XtOrderResponse.from_any({
        "account_type": xtconstant.SECURITY_ACCOUNT,
        "account_id": "A123",
        "order_id": 719000003,
        "strategy_name": "hxy",
        "order_remark": "remark",
        "seq": 10,
    })

    assert set(vars(response)) == {
        "account_type",
        "account_id",
        "order_id",
        "strategy_name",
        "order_remark",
        "seq",
    }


def test_xtquanttrader_auto_assigns_session_id_when_omitted_or_zero():
    account = StockAccount("A123")

    trader_default = XtQuantTrader(account=account)
    trader_zero = XtQuantTrader("", 0, account=account)
    trader_explicit = XtQuantTrader("", 10001, account=account)

    assert isinstance(trader_default.session_id, int)
    assert trader_default.session_id > 0
    assert trader_zero.session_id > 0
    assert trader_default.session_id != trader_zero.session_id
    assert trader_explicit.session_id == 10001


def test_tx_trade_bridge_filters_cancelable_order_query():
    rows = [
        {"m_nOrderID": "can-cancel", "m_nOrderStatus": xtconstant.ORDER_REPORTED},
        {"m_nOrderID": "done", "m_nOrderStatus": xtconstant.ORDER_SUCCEEDED},
    ]
    bridge = TxTradeBridge(
        object(),
        show=False,
        globals_dict={"get_trade_detail_data": lambda *args: rows},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "A123", "account_type": "STOCK"},
        "cancelable_only": "true",
    }, "order")

    assert [row["m_nOrderID"] for row in result] == ["can-cancel"]


def test_tx_trade_bridge_query_prefers_three_arg_signature():
    context = object()
    calls = []

    def get_trade_detail_data(*args):
        calls.append(args)
        return [{"m_dAvailable": 1.0}]

    bridge = TxTradeBridge(
        context,
        show=False,
        globals_dict={"get_trade_detail_data": get_trade_detail_data},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "A123", "account_type": "STOCK"},
    }, "account")

    assert calls == [("A123", "stock", "account")]
    assert result[0]["m_dAvailable"] == 1.0


def test_query_stock_orders_preserves_requested_account_fields():
    row = {
        "m_nRef": 700001,
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
    }
    bridge = TxTradeBridge(
        object(),
        show=False,
        globals_dict={"get_trade_detail_data": lambda *args: [row]},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "C123", "account_type": "CREDIT"},
    }, "order")
    order = XtOrder.from_any(result[0])

    assert order.account_id == "C123"
    assert order.account_type == xtconstant.CREDIT_ACCOUNT
    assert order.order_id == 700001


def test_tx_trade_bridge_query_falls_back_to_three_args():
    rows = [{"m_dAvailable": 2.0}]

    def get_trade_detail_data(account_id, account_type, detail_type):
        assert (account_id, account_type, detail_type) == ("A123", "stock", "account")
        return rows

    bridge = TxTradeBridge(
        object(),
        show=False,
        globals_dict={"get_trade_detail_data": get_trade_detail_data},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "A123", "account_type": "STOCK"},
    }, "account")

    assert result[0]["m_dAvailable"] == 2.0


def test_tx_trade_bridge_query_uses_empty_strategy_name_when_fourth_arg_is_required():
    calls = []

    def get_trade_detail_data(*args):
        calls.append(args)
        if len(args) == 3:
            raise TypeError("strategyname is required")
        return [{"m_dAvailable": 2.5}]

    bridge = TxTradeBridge(
        object(),
        show=False,
        globals_dict={"get_trade_detail_data": get_trade_detail_data},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "A123", "account_type": "STOCK"},
    }, "account")

    assert calls == [
        ("A123", "stock", "account"),
        ("A123", "stock", "account", ""),
    ]
    assert result[0]["m_dAvailable"] == 2.5


def test_tx_trade_bridge_query_does_not_retry_request_id_error_with_context():
    calls = []

    def get_trade_detail_data(*args):
        calls.append(args)
        raise AttributeError("'NoneType' object has no attribute 'request_id'")

    bridge = TxTradeBridge(
        object(),
        show=False,
        globals_dict={"get_trade_detail_data": get_trade_detail_data},
    )

    with pytest.raises(AttributeError, match="request_id"):
        bridge._query_trade_detail({
            "account": {"account_id": "A123", "account_type": "STOCK"},
        }, "account")

    assert calls == [("A123", "stock", "account")]


def test_qmt_bridge_filters_cancelable_order_query():
    rows = [
        {"m_nOrderID": "can-cancel", "m_nOrderStatus": xtconstant.ORDER_PART_SUCC},
        {"m_nOrderID": "junk", "m_nOrderStatus": xtconstant.ORDER_JUNK},
    ]
    bridge = CfquantQmtBridge(
        object(),
        show=False,
        globals_dict={"get_trade_detail_data": lambda *args: rows},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "A123", "account_type": "STOCK"},
        "cancelable_only": 1,
    }, "ORDER")

    assert [row["m_nOrderID"] for row in result] == ["can-cancel"]


def test_qmt_bridge_query_prefers_three_arg_signature():
    context = object()
    calls = []

    def get_trade_detail_data(*args):
        calls.append(args)
        return [{"m_dAvailable": 3.0}]

    bridge = CfquantQmtBridge(
        context,
        show=False,
        globals_dict={"get_trade_detail_data": get_trade_detail_data},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "A123", "account_type": "STOCK"},
    }, "ACCOUNT")

    assert calls == [("A123", "stock", "account")]
    assert result[0]["m_dAvailable"] == 3.0


def test_qmt_bridge_query_uses_empty_strategy_name_when_fourth_arg_is_required():
    calls = []

    def get_trade_detail_data(*args):
        calls.append(args)
        if len(args) == 3:
            raise TypeError("strategyname is required")
        return [{"m_dAvailable": 4.0}]

    context = object()
    bridge = CfquantQmtBridge(
        context,
        show=False,
        globals_dict={"get_trade_detail_data": get_trade_detail_data},
    )

    result = bridge._query_trade_detail({
        "account": {"account_id": "A123", "account_type": "STOCK"},
    }, "ACCOUNT")

    assert calls == [
        ("A123", "stock", "account"),
        ("A123", "stock", "account", ""),
    ]
    assert result[0]["m_dAvailable"] == 4.0


def test_qmt_bridge_query_does_not_retry_request_id_error_with_context():
    calls = []

    def get_trade_detail_data(*args):
        calls.append(args)
        raise AttributeError("'NoneType' object has no attribute 'request_id'")

    bridge = CfquantQmtBridge(
        object(),
        show=False,
        globals_dict={"get_trade_detail_data": get_trade_detail_data},
    )

    with pytest.raises(AttributeError, match="request_id"):
        bridge._query_trade_detail({
            "account": {"account_id": "A123", "account_type": "STOCK"},
        }, "ACCOUNT")

    assert calls == [("A123", "stock", "account")]
