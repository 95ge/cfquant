from cfquant.qmt_bridge import CfquantQmtBridge
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
