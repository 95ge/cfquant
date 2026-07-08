#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib


_cf_bridge = None
_ENTRY_VERSION = "normal_bridge_20260707_10"
DEFAULT_ACCOUNT_ID = ""
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)


def _ensure_path():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if base_dir and base_dir not in sys.path:
            sys.path.insert(0, base_dir)
    except Exception:
        pass


_ensure_path()


def _load_bridge_starter():
    import cfquant.cfquant.tx_trade_bridge as tx_trade_bridge
    import cfquant.cfquant.normal_bridge as normal_bridge

    try:
        tx_trade_bridge = importlib.reload(tx_trade_bridge)
    except Exception as e:
        print("tx trade bridge reload failed:%s" % e)
    try:
        normal_bridge = importlib.reload(normal_bridge)
    except Exception as e:
        print("normal bridge reload failed:%s" % e)
    return normal_bridge.start_normal_bridge


start_normal_bridge = _load_bridge_starter()

from cfquant.cfquant.channels import channels_for_bridge, normalize_bridge_id

BRIDGE_ID = normalize_bridge_id(BRIDGE_ID)
BRIDGE_CHANNELS = channels_for_bridge(BRIDGE_ID)

_cf_bridge = start_normal_bridge(
    None,
    ip="127.0.0.1",
    port=2049,
    token="LTtx",
    request_channel=BRIDGE_CHANNELS["normal"],
    callback_event_channel=BRIDGE_CHANNELS["callback"],
    bridge_id=BRIDGE_ID,
    account_id=DEFAULT_ACCOUNT_ID,
    show=True,
)
print("cfquant normal bridge module loaded")
print("cfquant entry version:%s" % _ENTRY_VERSION)
print("cfquant bridge id:%s normal_channel:%s callback_channel:%s" % (
    BRIDGE_ID,
    BRIDGE_CHANNELS["normal"],
    BRIDGE_CHANNELS["callback"],
))


def init(ContextInfo):
    if _cf_bridge:
        _cf_bridge.set_context(ContextInfo)
    print("cfquant normal bridge context ready version:%s" % _ENTRY_VERSION)


def handlebar(ContextInfo):
    if _cf_bridge:
        _cf_bridge.pump()


def stop(ContextInfo):
    global _cf_bridge

    if _cf_bridge:
        _cf_bridge.close()
        _cf_bridge = None
        print("cfquant normal bridge stopped")


def _publish_callback(event_name, obj):
    try:
        if _cf_bridge:
            _cf_bridge.publish_callback_event(event_name, obj)
    except Exception as e:
        print("cfquant callback publish failed event=%s error=%s" % (event_name, e))


def account_callback(ContextInfo, accountInfo):
    _publish_callback("trader:on_stock_asset", accountInfo)


def order_callback(ContextInfo, orderInfo):
    _publish_callback("trader:on_stock_order", orderInfo)


def deal_callback(ContextInfo, dealInfo):
    _publish_callback("trader:on_stock_trade", dealInfo)


def trade_callback(ContextInfo, tradeInfo):
    _publish_callback("trader:on_stock_trade", tradeInfo)


def position_callback(ContextInfo, positionInfo):
    _publish_callback("trader:on_stock_position", positionInfo)


def order_error_callback(ContextInfo, orderError):
    _publish_callback("trader:on_order_error", orderError)


def cancel_error_callback(ContextInfo, cancelError):
    _publish_callback("trader:on_cancel_error", cancelError)


def order_stock_async_response_callback(ContextInfo, response):
    _publish_callback("trader:on_order_stock_async_response", response)


def cancel_order_stock_async_response_callback(ContextInfo, response):
    _publish_callback("trader:on_cancel_order_stock_async_response", response)
