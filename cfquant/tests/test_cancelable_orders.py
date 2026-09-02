from cfquant import xtconstant
from cfquant.qmt_bridge import CfquantQmtBridge
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import (
    StockAccount,
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
