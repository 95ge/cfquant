#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib
import datetime as dt
import io
import json


_cf_bridge = None
_cf_timer_key = None
_TIMER_INTERVAL_MS = 500
_PUMP_MAX_COUNT = 20
_PUMP_MAX_MS = 0
DEFAULT_ACCOUNT_ID = str(os.environ.get("CFQUANT_ACCOUNT_ID") or "").strip()
DEFAULT_ACCOUNT_TYPE = str(os.environ.get("CFQUANT_ACCOUNT_TYPE") or "STOCK").strip().upper()
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)
RUNTIME_CONFIG = {}
RUNTIME_CHANNELS = {}


def _entry_file_path():
    path = globals().get("__file__") or ""
    path = str(path or "").strip()
    if path and not path.startswith("<"):
        try:
            return os.path.abspath(path)
        except Exception:
            return path
    return ""


def _entry_base_dir():
    entry_file = _entry_file_path()
    if entry_file:
        return os.path.dirname(entry_file)
    for name in ("CFQUANT_QMT_SCRIPT_DIR", "CFQUANT_SCRIPT_DIR", "CFQUANT_ENTRY_DIR"):
        path = str(os.environ.get(name) or "").strip()
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    try:
        cwd = os.path.abspath(os.getcwd())
        if (
            os.path.isfile(os.path.join(cwd, "CFQUANT.py"))
            or os.path.isfile(os.path.join(cwd, "cfquant_bridge_config.json"))
            or os.path.isdir(os.path.join(cwd, "cfquant"))
        ):
            return cwd
    except Exception:
        pass
    for path in sys.path:
        path = str(path or "").strip()
        if path and os.path.isdir(path):
            base = os.path.abspath(path)
            if (
                os.path.isfile(os.path.join(base, "CFQUANT.py"))
                or os.path.isfile(os.path.join(base, "cfquant_bridge_config.json"))
                or os.path.isdir(os.path.join(base, "cfquant"))
            ):
                return base
    try:
        return os.path.abspath(os.getcwd())
    except Exception:
        return ""


def _runtime_config_paths():
    try:
        base_dir = _entry_base_dir()
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
        for opener in (
            lambda: io.open(path, "r", encoding="utf-8"),
            lambda: open(path, "r"),
        ):
            try:
                with opener() as f:
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


def _env_allows_runtime_override(name, default_value=""):
    value = str(os.environ.get(name) or "").strip()
    if not value:
        return True
    if str(os.environ.get("%s_SOURCE" % name) or "").strip() == "cfquant_entry":
        return True
    return bool(default_value and value == default_value)


def _apply_runtime_config():
    global BRIDGE_ID, RUNTIME_CONFIG, RUNTIME_CHANNELS, DEFAULT_ACCOUNT_ID, DEFAULT_ACCOUNT_TYPE

    data = _load_runtime_config()
    RUNTIME_CONFIG = data
    if not data:
        return
    if data.get("account_id") and not DEFAULT_ACCOUNT_ID:
        DEFAULT_ACCOUNT_ID = str(data.get("account_id") or "").strip()
    if data.get("account_type"):
        DEFAULT_ACCOUNT_TYPE = str(data.get("account_type") or DEFAULT_ACCOUNT_TYPE or "STOCK").strip().upper()
    if data.get("bridge_id") and _env_allows_runtime_override("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID):
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
        base_dir = _entry_base_dir()
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
        ordered = []
        seen = set()
        for path in candidates:
            if not path or not os.path.isdir(path):
                continue
            path = os.path.abspath(path)
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(path)
        if ordered:
            sys.path[:] = ordered + [
                path for path in sys.path
                if os.path.normcase(os.path.abspath(path or os.curdir)) not in seen
            ]
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
if DEFAULT_ACCOUNT_TYPE and _cf_bridge:
    _cf_bridge.account_type = DEFAULT_ACCOUNT_TYPE
_print_log("cfquant normal bridge module loaded")
_print_log("cfquant entry version:%s" % _ENTRY_VERSION)
_print_log("cfquant bridge id:%s account:%s/%s normal_channel:%s callback_channel:%s" % (
    BRIDGE_ID,
    DEFAULT_ACCOUNT_ID or "-",
    DEFAULT_ACCOUNT_TYPE or "-",
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


_QMT_TRADE_CALLBACK_REGISTERED = False


def _register_qmt_trade_callback(ContextInfo, stage):
    global _QMT_TRADE_CALLBACK_REGISTERED

    if ContextInfo is None or _QMT_TRADE_CALLBACK_REGISTERED:
        return
    func = getattr(ContextInfo, "register_callback", None)
    if not callable(func):
        _print_log("cfquant qmt trade callback register skipped stage=%s reason=missing register_callback" % stage)
        return
    try:
        func(0)
        _QMT_TRADE_CALLBACK_REGISTERED = True
        _print_log("cfquant qmt trade callback registered stage=%s" % stage)
    except Exception as e:
        _print_log("cfquant qmt trade callback register failed stage=%s error=%s" % (stage, e))


def _refresh_auto_trade_callback(stage):
    if _cf_bridge is None or not hasattr(_cf_bridge, "_enable_auto_trade_callback"):
        return
    try:
        _cf_bridge.auto_trade_callback_enabled = False
        _cf_bridge._enable_auto_trade_callback()
        _print_log("cfquant auto trade callback refreshed stage=%s" % stage)
    except Exception as e:
        _print_log("cfquant auto trade callback refresh failed stage=%s error=%s" % (stage, e))


def _callback_brief(obj):
    try:
        parts = []
        for name in ("account_id", "m_strAccountID", "m_strInstrumentID", "m_strExchangeID", "m_strOrderSysID", "m_nOrderID", "m_strRemark"):
            value = getattr(obj, name, None)
            if value is None and hasattr(obj, "get"):
                value = obj.get(name)
            if value not in (None, ""):
                parts.append("%s=%s" % (name, value))
        return " ".join(parts) or type(obj).__name__
    except Exception:
        return type(obj).__name__


def _object_to_callback_dict(obj):
    if hasattr(obj, "items"):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {"value": str(obj)}


def init(ContextInfo):
    _register_qmt_trade_callback(ContextInfo, "init")
    if _cf_bridge:
        _cf_bridge.set_context(ContextInfo)
    _schedule_cf_timer(ContextInfo)
    _print_log("cfquant normal bridge context ready version:%s" % _ENTRY_VERSION)


def after_init(ContextInfo):
    _register_qmt_trade_callback(ContextInfo, "after_init")
    _refresh_auto_trade_callback("after_init")


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
        _print_log("cfquant raw qmt callback received event=%s %s" % (event_name, _callback_brief(obj)))
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


def orderError_callback(ContextInfo, passOrderInfo, msg):
    data = _object_to_callback_dict(passOrderInfo)
    data["error_msg"] = msg
    _publish_callback("trader:on_order_error", data)


def cancel_error_callback(ContextInfo, cancelError):
    _publish_callback("trader:on_cancel_error", cancelError)


def cancelError_callback(ContextInfo, cancelError):
    _publish_callback("trader:on_cancel_error", cancelError)


def order_stock_async_response_callback(ContextInfo, response):
    _publish_callback("trader:on_order_stock_async_response", response)


def cancel_order_stock_async_response_callback(ContextInfo, response):
    _publish_callback("trader:on_cancel_order_stock_async_response", response)
