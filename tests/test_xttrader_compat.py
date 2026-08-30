# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cfquant import xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import (
    StockAccount,
    XtAsset,
    XtCancelOrderResponse,
    XtOrder,
    XtOrderResponse,
    XtPosition,
    XtTrade,
)


def test_query_stock_asset_unwraps_list_and_maps_xtquant_fields():
    account = StockAccount("A100")
    trader = XtQuantTrader(account=account)

    def fake_request(action, params=None, timeout=None):
        assert action == "xttrader.query_stock_asset"
        assert params["account"]["account_id"] == "A100"
        return [{
            "m_dBalance": 100000.0,
            "m_dAvailable": 12000.0,
            "m_dInstrumentValue": 88000.0,
            "m_dPositionProfit": 123.4,
        }]

    trader._trade_request = fake_request
    asset = trader.query_stock_asset(account)

    assert isinstance(asset, XtAsset)
    assert not isinstance(asset, list)
    assert asset.account_id == "A100"
    assert asset.account_type == xtconstant.SECURITY_ACCOUNT
    assert asset.cash == 12000.0
    assert asset.market_value == 88000.0
    assert asset.total_asset == 100000.0
    assert asset.fetch_balance == 12000.0
    assert asset.frozen_cash == 0.0
    assert asset.m_dBalance == 100000.0


def test_query_stock_asset_empty_list_returns_none():
    account = StockAccount("A100")
    trader = XtQuantTrader(account=account)
    trader._trade_request = lambda action, params=None, timeout=None: []

    assert trader.query_stock_asset(account) is None


def test_order_trade_position_objects_keep_raw_fields_and_add_xtquant_aliases():
    order = XtOrder.from_any({
        "m_strInstrumentID": "600000",
        "m_strExchangeID": "SH",
        "m_nOrderID": 12345,
        "m_strOrderSysID": "SYS123",
        "m_nVolumeTotalOriginal": 1000,
        "m_nVolumeTraded": 400,
        "m_dTradedPrice": 10.5,
        "m_nOrderStatus": xtconstant.ORDER_SUCCEEDED,
        "m_strRemark": "remark",
        "m_strStrategyName": "strategy",
    })
    assert order.stock_code == "600000.SH"
    assert order.order_id == 12345
    assert order.order_sysid == "SYS123"
    assert order.order_volume == 1000
    assert order.traded_volume == 400
    assert order.traded_price == 10.5
    assert order.order_status == xtconstant.ORDER_SUCCEEDED
    assert order.order_remark == "remark"
    assert order.m_nOrderID == 12345

    trade = XtTrade.from_any({
        "stock_code": "000001.SZ",
        "price": 11.2,
        "volume": 300,
        "trade_amount": 3360.0,
        "m_strDealID": "D1",
    })
    assert trade.traded_id == "D1"
    assert trade.traded_price == 11.2
    assert trade.traded_volume == 300
    assert trade.traded_amount == 3360.0

    position = XtPosition.from_any({
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
        "m_nVolume": 500,
        "m_nCanUseVolume": 200,
        "m_dInstrumentValue": 5600.0,
        "m_dPositionCost": 10.1,
    })
    assert position.stock_code == "000001.SZ"
    assert position.volume == 500
    assert position.can_use_volume == 200
    assert position.market_value == 5600.0
    assert position.avg_price == 10.1


def test_query_list_objects_use_request_account_type():
    account = StockAccount("C100", "CREDIT")
    trader = XtQuantTrader(account=account)
    trader._trade_request = lambda action, params=None, timeout=None: [{
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
        "m_nVolume": 100,
    }]

    positions = trader.query_stock_positions(account)

    assert len(positions) == 1
    assert positions[0].account_id == "C100"
    assert positions[0].account_type == xtconstant.CREDIT_ACCOUNT


def test_async_order_response_objects_add_xtquant_aliases():
    response = XtOrderResponse.from_any({
        "account_id": "A100",
        "account_type": "STOCK",
        "m_nOrderID": 888,
        "m_strStrategyName": "s",
        "m_strRemark": "r",
    })
    assert response.account_type == xtconstant.SECURITY_ACCOUNT
    assert response.order_id == 888
    assert response.strategy_name == "s"
    assert response.order_remark == "r"

    cancel_response = XtCancelOrderResponse.from_any({
        "account_id": "A100",
        "account_type": "STOCK",
        "result": 0,
        "m_nOrderID": 888,
        "m_strOrderSysID": "SYS888",
    })
    assert cancel_response.account_type == xtconstant.SECURITY_ACCOUNT
    assert cancel_response.cancel_result == 0
    assert cancel_response.order_id == 888
    assert cancel_response.order_sysid == "SYS888"


def test_common_xtconstant_symbols_exist():
    assert xtconstant.CREDIT_FIN_BUY == 27
    assert xtconstant.ORDER_SUCCEEDED == 56
    assert xtconstant.ORDER_UNKNOWN == 255
    assert xtconstant.DIRECTION_FLAG_BUY == 48
    assert xtconstant.OFFSET_FLAG_OPEN == 48
