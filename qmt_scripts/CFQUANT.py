#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib
import datetime as dt
import json


_cf_bridge = None
_cf_timer_key = None
_TIMER_INTERVAL_MS = 500
_PUMP_MAX_COUNT = 20
_PUMP_MAX_MS = 0
DEFAULT_ACCOUNT_ID = ""
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)
RUNTIME_CONFIG = {}
RUNTIME_CHANNELS = {}


def _runtime_config_paths():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(base_dir)
        candidates = []
        env_path = os.environ.get("CFQUANT_BRIDGE_CONFIG_FILE")
        if env_path:
            candidates.append(env_path)
        if os.path.basename(base_dir).lower() == "python":
            candidates.append(os.path.join(parent_dir, "bin.x64", "cfquant_bridge_config.json"))
            candidates.append(os.path.join(base_dir, "cfquant_bridge_config.json"))
        else:
            candidates.append(os.path.join(base_dir, "cfquant_bridge_config.json"))
            candidates.append(os.path.join(base_dir, "bin.x64", "cfquant_bridge_config.json"))
        candidates.append(os.path.join(parent_dir, "cfquant_bridge_config.json"))
        result = []
        seen = set()
        for path in candidates:
            if not path:
                continue
            path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            result.append(path)
        return result
    except Exception:
        return []


def _load_runtime_config():
    for path in _runtime_config_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r") as f:
                data = json.loads(f.read())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _config_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("0", "false", "no", "off", "disable", "disabled", "closed", "close"):
        return False
    if text in ("1", "true", "yes", "on", "enable", "enabled", "open"):
        return True
    return default


def _apply_runtime_config():
    global BRIDGE_ID, RUNTIME_CONFIG, RUNTIME_CHANNELS

    data = _load_runtime_config()
    RUNTIME_CONFIG = data
    if not data:
        return
    if not os.environ.get("CFQUANT_BRIDGE_ID") and data.get("bridge_id"):
        BRIDGE_ID = data.get("bridge_id")
    channels = data.get("channels") or {}
    if isinstance(channels, dict):
        RUNTIME_CHANNELS = channels
    if not os.environ.get("CFQUANT_QMT_LOG_LANGUAGE") and data.get("qmt_log_language"):
        os.environ["CFQUANT_QMT_LOG_LANGUAGE"] = str(data.get("qmt_log_language") or "zh")
    if not os.environ.get("CFQUANT_QMT_LOG_ENABLED") and "qmt_log_enabled" in data:
        os.environ["CFQUANT_QMT_LOG_ENABLED"] = "1" if _config_bool(data.get("qmt_log_enabled"), True) else "0"


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
_apply_runtime_config()

from cfquant import __version__ as _ENTRY_VERSION
from cfquant.logging_i18n import get_log_enabled, translate_log


def _print_log(message):
    if get_log_enabled():
        print(translate_log(message))


def _load_bridge_starter():
    import cfquant.tx_trade_bridge as tx_trade_bridge
    import cfquant.normal_bridge as normal_bridge

    try:
        tx_trade_bridge = importlib.reload(tx_trade_bridge)
    except Exception as e:
        _print_log("tx trade bridge reload failed:%s" % e)
    try:
        normal_bridge = importlib.reload(normal_bridge)
    except Exception as e:
        _print_log("normal bridge reload failed:%s" % e)
    return normal_bridge.start_normal_bridge


start_normal_bridge = _load_bridge_starter()

from cfquant.channels import channels_for_bridge, normalize_bridge_id

BRIDGE_ID = normalize_bridge_id(BRIDGE_ID)
BRIDGE_CHANNELS = channels_for_bridge(BRIDGE_ID)
for _channel_key in ("normal", "callback"):
    _channel_value = RUNTIME_CHANNELS.get(_channel_key) or RUNTIME_CONFIG.get("%s_channel" % _channel_key)
    if _channel_value:
        BRIDGE_CHANNELS[_channel_key] = str(_channel_value).strip()

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
_print_log("cfquant normal bridge module loaded")
_print_log("cfquant entry version:%s" % _ENTRY_VERSION)
_print_log("cfquant bridge id:%s normal_channel:%s callback_channel:%s" % (
    BRIDGE_ID,
    BRIDGE_CHANNELS["normal"],
    BRIDGE_CHANNELS["callback"],
))
_print_log("cfquant normal bridge pump max_count:%s max_ms:%s" % (_PUMP_MAX_COUNT, _PUMP_MAX_MS))


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
        _print_log("cfquant normal bridge timer scheduled key:%s interval_ms:%s" % (_cf_timer_key, _TIMER_INTERVAL_MS))
    except Exception as e:
        _print_log("cfquant normal bridge timer schedule failed:%s" % e)


def init(ContextInfo):
    if _cf_bridge:
        _cf_bridge.set_context(ContextInfo)
    _schedule_cf_timer(ContextInfo)
    _print_log("cfquant normal bridge context ready version:%s" % _ENTRY_VERSION)


def handlebar(ContextInfo):
    if _cf_bridge:
        _cf_bridge.pump()


def stop(ContextInfo):
    global _cf_bridge, _cf_timer_key

    if ContextInfo is not None and _cf_timer_key:
        try:
            ContextInfo.cancel_schedule_run(_cf_timer_key)
        except Exception as e:
            _print_log("cfquant normal bridge timer cancel failed:%s" % e)
        _cf_timer_key = None

    if _cf_bridge:
        _cf_bridge.close()
        _cf_bridge = None
        _print_log("cfquant normal bridge stopped")


def _publish_callback(event_name, obj):
    try:
        if _cf_bridge:
            _cf_bridge.publish_callback_event(event_name, obj)
    except Exception as e:
        _print_log("cfquant callback publish failed event=%s error=%s" % (event_name, e))


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
