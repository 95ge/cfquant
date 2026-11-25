"""Offline identity and operation regressions for derivatives and Stock Connect."""
from types import SimpleNamespace

import pytest

from cfquant.xttype import StockAccount, XtOrder, XtTrade, XtOrderResponse, XtCancelOrderResponse
from cfquant.tests.test_cftrader import connected


@pytest.mark.parametrize("account_type,code,operation", [
    ("FUTURE", "rb2610.SF", 0),
    ("FUTURE_OPTION", "m2701-C-3000.DF", 0),
    ("STOCK_OPTION", "10000001.SHO", 0),
    ("HUGANGTONG", "00700.HGT", 23),
    ("SHENGANGTONG", "00700.SGT", 24),
])
def test_query_callback_and_cancel_preserve_trading_identity(connected, account_type, code, operation):
    env = connected
    env.account.account_type = StockAccount("TEST_ONLY", account_type).account_type
    symbol, market = code.rsplit(".", 1)
    raw = SimpleNamespace(m_strAccountID="TEST_ONLY", m_nBrokerType=env.account.account_type,
                          m_strInstrumentID=symbol, m_strExchangeID=market,
                          m_nRef=123, m_strOrderSysID="000456", m_strStrategyName="alpha",
                          m_strRemark="remark", m_nOrderType=operation, m_nOffsetFlag=48,
                          m_nDirection=49, m_nOrderStatus=50, m_nVolume=1)
    env.bridge.globals_dict["get_trade_detail_data"] = lambda *args: [raw]
    trades = []
    env.trader.callback.on_stock_trade = trades.append
    order = env.trader.query_stock_orders(env.account)[0]
    trade = env.trader.query_stock_trades(env.account)[0]
    for event, detail in (("on_stock_order", "order"), ("on_stock_trade", "deal")):
        data = env.bridge._format_trade_detail(raw, detail)
        data["account_type"] = env.account.account_type
        env.trader._make_trader_handler(event)(data)
    for row in (order, trade, env.orders[-1], trades[-1]):
        assert row.order_id == 123
        assert row.order_sysid == "000456"
        assert row.strategy_name == "alpha"
        assert row.order_remark == "remark"
        assert row.account_type == env.account.account_type
        assert row.stock_code == code
        assert row.order_type == operation
        assert row.direction == 49
        assert row.offset_flag == 48
    assert env.trader.query_stock_order(env.account, "000456").order_id == 123
    assert env.trader.cancel_order_stock_sysid(env.account, market, order.order_sysid) == 0
    assert env.cancel_calls[-1][:2] == ("000456", "TEST_ONLY")
    assert env.cancel_calls[-1][2].upper() == account_type


@pytest.mark.parametrize("account_type,market", [
    ("FUTURE", "SF"), ("FUTURE_OPTION", "DF"), ("STOCK_OPTION", "SHO"),
    # Missing account metadata must not turn a known futures instrument into a stock.
    (None, "SF"),
])
@pytest.mark.parametrize("operation", [0, "0", None])
def test_derivative_open_flag_is_not_stock_buy(account_type, market, operation):
    raw = dict(stock_code="contract." + market, m_nOffsetFlag=48)
    if account_type is not None:
        raw["account_type"] = account_type
    if operation is not None:
        raw["order_type"] = operation
    assert XtTrade.from_any(raw).order_type == 0


@pytest.mark.parametrize("market,offset,operation", [
    ("SH", 48, 23), ("SZ", 49, 24), ("HGT", 48, 23), ("SGT", 49, 24),
])
def test_stock_trade_fallback_still_works_with_compact_fields(market, offset, operation):
    row = XtTrade.from_any(dict(stock_code="00700." + market, mnOffsetFlag=offset))
    assert row.order_type == operation


@pytest.mark.parametrize("cls", [XtOrder, XtTrade, XtOrderResponse, XtCancelOrderResponse])
@pytest.mark.parametrize("field", ["mnRef", "mnOrderID", "mstrOrderRef", "mstrOrderID"])
def test_compact_native_order_reference_is_available_for_cancellation(cls, field):
    raw = {field: "123", "mstrOrderSysID": "000456", "mstrStrategyName": "alpha"}
    row = cls.from_any(raw)
    assert row.order_id == 123
    assert getattr(row, field) == "123"
    if cls in (XtOrder, XtTrade, XtCancelOrderResponse):
        assert row.order_sysid == "000456"
    assert raw[field] == "123"
