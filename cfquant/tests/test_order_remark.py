import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cfquant_web_server as web
from cfquant import xtconstant
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
