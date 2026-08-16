#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib
import datetime as dt


_cf_bridge = None
_cf_timer_key = None
_TIMER_INTERVAL_MS = 500
_PUMP_MAX_COUNT = 20
_PUMP_MAX_MS = 0
DEFAULT_ACCOUNT_ID = ""
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)


def _ensure_path():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(base_dir)
        env_paths = [p for p in os.environ.get("CFQUANT_PYTHONPATH", "").split(os.pathsep) if p]
        if os.path.basename(base_dir).lower() == "python":
            candidates = env_paths + [os.path.join(parent_dir, "bin.x64"), base_dir, parent_dir]
        else:
            candidates = env_paths + [
                base_dir,
                os.path.join(base_dir, "bin.x64"),
                parent_dir,
                os.path.join(parent_dir, "bin.x64"),
                os.path.join(parent_dir, "python"),
            ]
        insert_at = 0
        for path in candidates:
            if path and os.path.isdir(path) and path not in sys.path:
                sys.path.insert(insert_at, path)
                insert_at += 1
    except Exception:
        pass


_ensure_path()

from cfquant import __version__ as _ENTRY_VERSION


def _load_bridge_starter():
    import cfquant.tx_trade_bridge as tx_trade_bridge
    import cfquant.normal_bridge as normal_bridge

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

from cfquant.channels import channels_for_bridge, normalize_bridge_id

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
    schedule_timer=False,
    pump_max_count=_PUMP_MAX_COUNT,
    pump_max_ms=_PUMP_MAX_MS,
)
print("cfquant normal bridge module loaded")
print("cfquant entry version:%s" % _ENTRY_VERSION)
print("cfquant bridge id:%s normal_channel:%s callback_channel:%s" % (
    BRIDGE_ID,
    BRIDGE_CHANNELS["normal"],
    BRIDGE_CHANNELS["callback"],
))
print("cfquant normal bridge pump max_count:%s max_ms:%s" % (_PUMP_MAX_COUNT, _PUMP_MAX_MS))


def cfquant_normal_timer(*args, **kwargs):
    if _cf_bridge:
        _cf_bridge.on_timer(*args, **kwargs)


def _schedule_cf_timer(ContextInfo):
    global _cf_timer_key

    if _cf_timer_key or ContextInfo is None:
        return
    try:
        first_time = dt.datetime.now() + dt.timedelta(seconds=1)
        _cf_timer_key = ContextInfo.schedule_run(
            cfquant_normal_timer,
            first_time,
            repeat_times=-1,
            interval=dt.timedelta(milliseconds=_TIMER_INTERVAL_MS),
            name="cfquant_normal_bridge_pump",
        )
        print("cfquant normal bridge timer scheduled key:%s interval_ms:%s" % (_cf_timer_key, _TIMER_INTERVAL_MS))
    except Exception as e:
        print("cfquant normal bridge timer schedule failed:%s" % e)


def init(ContextInfo):
    if _cf_bridge:
        _cf_bridge.set_context(ContextInfo)
    _schedule_cf_timer(ContextInfo)
    print("cfquant normal bridge context ready version:%s" % _ENTRY_VERSION)


def handlebar(ContextInfo):
    if _cf_bridge:
        _cf_bridge.pump()


def stop(ContextInfo):
    global _cf_bridge, _cf_timer_key

    if ContextInfo is not None and _cf_timer_key:
        try:
            ContextInfo.cancel_schedule_run(_cf_timer_key)
        except Exception as e:
            print("cfquant normal bridge timer cancel failed:%s" % e)
        _cf_timer_key = None

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
