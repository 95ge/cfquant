#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib
import datetime as dt
import json
import queue
import threading
import time


_normal_bridge = None
_trade_bridge = None
_trade_thread = None
_trade_request_queue = queue.Queue(maxsize=10000)
_trade_timer_key = None
_trade_loop_started_at = 0
_trade_loop_error = ""
_trade_recv_count = 0
_trade_dispatch_count = 0
_trade_direct_dispatch_count = 0
_trade_reroute_count = 0
_trade_queue_full_count = 0
_trade_last_recv_at = 0
_trade_last_dispatch_at = 0
DEFAULT_ACCOUNT_ID = ""
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)
PIPE_NAME = os.environ.get("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub")
RUNTIME_CONFIG_PATH = ""
RUNTIME_CONFIG = {}
RUNTIME_CHANNELS = {}
PIPE_CONNECT_TIMEOUT_MS = int(os.environ.get("CFQUANT_PIPE_CONNECT_TIMEOUT_MS", "3000"))
TRADE_LOOP_IN_THREAD = os.environ.get("CFQUANT_CTYPE_TRADE_THREAD", "1").strip().lower() in ("1", "true", "yes", "on")
NORMAL_PUMP_MAX_COUNT = int(os.environ.get("CFQUANT_CTYPE_NORMAL_PUMP_MAX_COUNT", "100"))
NORMAL_PUMP_MAX_MS = float(os.environ.get("CFQUANT_CTYPE_NORMAL_PUMP_MAX_MS", "0"))
TRADE_SLEEP_SECONDS = float(os.environ.get("CFQUANT_CTYPE_TRADE_SLEEP_SECONDS", "0.001"))
TRADE_PUMP_MAX_COUNT = int(os.environ.get("CFQUANT_CTYPE_TRADE_PUMP_MAX_COUNT", "100"))
TRADE_PUMP_MAX_MS = float(os.environ.get("CFQUANT_CTYPE_TRADE_PUMP_MAX_MS", "0"))
TRADE_TIMER_INTERVAL_MS = int(os.environ.get("CFQUANT_CTYPE_TRADE_TIMER_INTERVAL_MS", "20"))


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
            os.path.isfile(os.path.join(cwd, "CFQUANT_CTYPE_ALL_LOWLAT.py"))
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
                os.path.isfile(os.path.join(base, "CFQUANT_CTYPE_ALL_LOWLAT.py"))
                or os.path.isfile(os.path.join(base, "cfquant_bridge_config.json"))
                or os.path.isdir(os.path.join(base, "cfquant"))
            ):
                return base
    try:
        return os.path.abspath(os.getcwd())
    except Exception:
        return ""


def _runtime_log_path():
    try:
        base_dir = _entry_base_dir()
        parent_dir = os.path.dirname(base_dir)
        configured = os.environ.get("CFQUANT_QMT_LOG_DIR") or os.environ.get("CFQUANT_LOG_DIR")
        if configured:
            candidates = [configured]
        elif os.path.basename(base_dir).lower() == "python":
            candidates = [
                os.path.join(parent_dir, "bin.x64", "log"),
                os.path.join(parent_dir, "log"),
                os.path.join(base_dir, "log"),
            ]
        else:
            candidates = [
                os.path.join(base_dir, "log"),
                os.path.join(parent_dir, "bin.x64", "log"),
                os.path.join(parent_dir, "log"),
            ]
        candidates.extend([
            os.path.join(parent_dir, "bin.x64", "tx_log"),
            os.path.join(base_dir, "tx_log"),
            os.path.join(parent_dir, "tx_log"),
            base_dir,
        ])
        for log_dir in candidates:
            if not log_dir:
                continue
            try:
                os.makedirs(log_dir, exist_ok=True)
                return os.path.join(log_dir, "cfquant_ctype_bridge.log")
            except Exception:
                if os.path.isdir(log_dir):
                    return os.path.join(log_dir, "cfquant_ctype_bridge.log")
    except Exception:
        pass
    return ""


def _write_runtime_log(message):
    try:
        path = _runtime_log_path()
        if not path:
            return
        log_dir = os.path.dirname(path)
        if log_dir and not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        with open(path, "a") as f:
            f.write("%s %s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


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
        try:
            with open(path, "r") as f:
                data = json.loads(f.read())
            if isinstance(data, dict):
                return path, data
        except Exception as e:
            _write_runtime_log("cfquant ctypes runtime config read failed path=%s error=%s" % (path, e))
    return "", {}


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
    global BRIDGE_ID, PIPE_NAME, RUNTIME_CONFIG_PATH, RUNTIME_CONFIG, RUNTIME_CHANNELS

    path, data = _load_runtime_config()
    RUNTIME_CONFIG_PATH = path
    RUNTIME_CONFIG = data
    if not data:
        _write_runtime_log("cfquant ctypes runtime config not found")
        return
    if not os.environ.get("CFQUANT_BRIDGE_ID") and data.get("bridge_id"):
        BRIDGE_ID = data.get("bridge_id")
    if not os.environ.get("CFQUANT_PIPE_NAME") and data.get("pipe_name"):
        PIPE_NAME = data.get("pipe_name")
    channels = data.get("channels") or {}
    if isinstance(channels, dict):
        RUNTIME_CHANNELS = channels
    if not os.environ.get("CFQUANT_QMT_LOG_LANGUAGE") and data.get("qmt_log_language"):
        os.environ["CFQUANT_QMT_LOG_LANGUAGE"] = str(data.get("qmt_log_language") or "zh")
    if not os.environ.get("CFQUANT_QMT_LOG_ENABLED") and "qmt_log_enabled" in data:
        os.environ["CFQUANT_QMT_LOG_ENABLED"] = "1" if _config_bool(data.get("qmt_log_enabled"), True) else "0"
    _write_runtime_log(
        "cfquant ctypes runtime config loaded path=%s bridge_id=%s pipe=%s"
        % (path, BRIDGE_ID, PIPE_NAME)
    )


_ensure_path()
_apply_runtime_config()
_write_runtime_log("cfquant ctypes entry executing file=%s sys_path_head=%s" % (_entry_file_path() or "<string>", sys.path[:5]))

try:
    from cfquant import __version__ as _ENTRY_VERSION
    from cfquant.logging_i18n import get_log_enabled, translate_log
    from cfquant.protocol import loads_message
    _write_runtime_log("cfquant import ok version=%s" % _ENTRY_VERSION)
except Exception as e:
    _write_runtime_log("cfquant import failed:%s sys_path_head=%s" % (e, sys.path[:8]))
    raise


def _print_log(message):
    if not get_log_enabled():
        return
    translated = translate_log(message)
    print(translated)
    _write_runtime_log(translated)


def _load_bridge_starters():
    import cfquant.pipe_transport as pipe_transport
    import cfquant.pipe_bridge as pipe_bridge

    try:
        pipe_transport = importlib.reload(pipe_transport)
    except Exception as e:
        _print_log("pipe transport reload failed:%s" % e)
    try:
        pipe_bridge = importlib.reload(pipe_bridge)
    except Exception as e:
        _print_log("pipe bridge reload failed:%s" % e)
    return pipe_bridge.start_pipe_normal_bridge, pipe_bridge.start_pipe_trade_bridge


start_pipe_normal_bridge, start_pipe_trade_bridge = _load_bridge_starters()

from cfquant.channels import channels_for_bridge, normalize_bridge_id

BRIDGE_ID = normalize_bridge_id(BRIDGE_ID)
if not os.environ.get("CFQUANT_BRIDGE_ID"):
    os.environ["CFQUANT_BRIDGE_ID"] = BRIDGE_ID
if PIPE_NAME and not os.environ.get("CFQUANT_PIPE_NAME"):
    os.environ["CFQUANT_PIPE_NAME"] = PIPE_NAME
BRIDGE_CHANNELS = channels_for_bridge(BRIDGE_ID)
for _channel_key in ("normal", "trade", "callback"):
    _channel_value = RUNTIME_CHANNELS.get(_channel_key) or RUNTIME_CONFIG.get("%s_channel" % _channel_key)
    if _channel_value:
        BRIDGE_CHANNELS[_channel_key] = str(_channel_value).strip()

_normal_bridge = start_pipe_normal_bridge(
    None,
    pipe_name=PIPE_NAME,
    request_channel=BRIDGE_CHANNELS["normal"],
    request_channels=[BRIDGE_CHANNELS["normal"]],
    callback_event_channel=BRIDGE_CHANNELS["callback"],
    bridge_id=BRIDGE_ID,
    account_id=DEFAULT_ACCOUNT_ID,
    show=True,
    schedule_timer=True,
    pump_max_count=NORMAL_PUMP_MAX_COUNT,
    pump_max_ms=NORMAL_PUMP_MAX_MS,
    connect_timeout_ms=PIPE_CONNECT_TIMEOUT_MS,
)

_trade_bridge = start_pipe_trade_bridge(
    None,
    pipe_name=PIPE_NAME,
    request_channel=BRIDGE_CHANNELS["trade"],
    bridge_id=BRIDGE_ID,
    account_id=DEFAULT_ACCOUNT_ID,
    show=True,
    connect_timeout_ms=PIPE_CONNECT_TIMEOUT_MS,
)

_print_log("cfquant ctypes all-in-one lowlat bridge module loaded")
_print_log("cfquant ctypes all-in-one lowlat entry version:%s" % _ENTRY_VERSION)
_print_log("cfquant ctypes bridge id:%s pipe:%s normal_channel:%s trade_channel:%s callback_channel:%s" % (
    BRIDGE_ID,
    PIPE_NAME,
    BRIDGE_CHANNELS["normal"],
    BRIDGE_CHANNELS["trade"],
    BRIDGE_CHANNELS["callback"],
))
_print_log("cfquant ctypes trade loop in thread:%s sleep_seconds:%s" % (TRADE_LOOP_IN_THREAD, TRADE_SLEEP_SECONDS))


def _attach_normal_status_extra():
    if not _normal_bridge:
        return
    original_status_extra = _normal_bridge._status_extra

    def status_extra_with_trade():
        data = original_status_extra()
        data.update({
            "ctype_trade_bridge_running": bool(_trade_bridge and _trade_bridge.running),
            "ctype_trade_thread_alive": bool(_trade_thread and _trade_thread.is_alive()),
            "ctype_trade_queue_size": _trade_request_queue.qsize(),
            "ctype_trade_timer_key": _trade_timer_key,
            "ctype_trade_loop_started_at": _trade_loop_started_at,
            "ctype_trade_loop_error": _trade_loop_error,
            "ctype_trade_recv_count": _trade_recv_count,
            "ctype_trade_dispatch_count": _trade_dispatch_count,
            "ctype_trade_direct_dispatch_count": _trade_direct_dispatch_count,
            "ctype_trade_reroute_count": _trade_reroute_count,
            "ctype_trade_queue_full_count": _trade_queue_full_count,
            "ctype_trade_last_recv_at": _trade_last_recv_at,
            "ctype_trade_last_dispatch_at": _trade_last_dispatch_at,
            "ctype_trade_request_channel": BRIDGE_CHANNELS["trade"],
            "ctype_trade_loop_in_thread": TRADE_LOOP_IN_THREAD,
            "ctype_trade_sleep_seconds": TRADE_SLEEP_SECONDS,
            "ctype_trade_pump_max_count": TRADE_PUMP_MAX_COUNT,
            "ctype_trade_pump_max_ms": TRADE_PUMP_MAX_MS,
            "ctype_trade_timer_interval_ms": TRADE_TIMER_INTERVAL_MS,
            "ctype_trade_dispatch_thread": "qmt_timer_or_handlebar",
            "ctype_trade_route_mode": "xttrader_to_normal_worker",
        })
        return data

    _normal_bridge._status_extra = status_extra_with_trade


def _run_trade_loop():
    global _trade_loop_error, _trade_recv_count, _trade_queue_full_count, _trade_last_recv_at

    while _trade_bridge and _trade_bridge.running:
        try:
            tx = _trade_bridge.tx
            if tx is None:
                time.sleep(0.05)
                continue
            raw = tx.Q.get(timeout=TRADE_SLEEP_SECONDS)
            if raw is None:
                continue
            _trade_request_queue.put_nowait(raw)
            _trade_recv_count += 1
            _trade_last_recv_at = time.time()
        except Exception as e:
            if isinstance(e, queue.Empty):
                continue
            if isinstance(e, queue.Full):
                _trade_queue_full_count += 1
                _trade_loop_error = "trade request queue full"
            else:
                _trade_loop_error = "%s:%s" % (type(e).__name__, e)
            _print_log("cfquant ctypes lowlat trade loop error:%s" % _trade_loop_error)
            try:
                time.sleep(0.05)
            except Exception:
                pass


def _drain_trade_requests(source):
    global _trade_dispatch_count, _trade_last_dispatch_at, _trade_loop_error

    if not _trade_bridge:
        return 0
    start = time.perf_counter()
    count = 0
    while count < TRADE_PUMP_MAX_COUNT:
        if TRADE_PUMP_MAX_MS > 0 and (time.perf_counter() - start) * 1000 >= TRADE_PUMP_MAX_MS:
            break
        try:
            raw = _trade_request_queue.get_nowait()
        except queue.Empty:
            break
        try:
            _handle_trade_raw(raw)
            _trade_dispatch_count += 1
            _trade_last_dispatch_at = time.time()
        except Exception as e:
            _trade_loop_error = "%s:%s" % (type(e).__name__, e)
            _print_log("cfquant ctypes lowlat trade dispatch error source=%s error=%s" % (source, _trade_loop_error))
        count += 1
    return count


def _handle_trade_raw(raw):
    if _should_reroute_trade_raw(raw) and _normal_bridge:
        return _reroute_trade_raw_to_normal(raw)
    _handle_trade_raw_direct(raw)


def _should_reroute_trade_raw(raw):
    msg = loads_message(raw)
    if not msg or msg.get("type") != "request":
        return False
    action = str(msg.get("action") or "")
    return action.startswith("xttrader.") or action == "cfquant.query_info"


def _reroute_trade_raw_to_normal(raw):
    global _trade_reroute_count

    _normal_bridge._handle_raw_from_thread(raw)
    _trade_reroute_count += 1


def _handle_trade_raw_direct(raw):
    global _trade_direct_dispatch_count

    _trade_bridge._handle_raw(raw)
    _trade_direct_dispatch_count += 1


def _start_trade_loop():
    global _trade_thread, _trade_loop_started_at, _trade_loop_error

    if not _trade_bridge:
        return
    if _trade_thread is not None and _trade_thread.is_alive():
        return
    if TRADE_LOOP_IN_THREAD:
        _trade_loop_error = ""
        _trade_loop_started_at = time.time()
        _trade_thread = threading.Thread(target=_run_trade_loop)
        _trade_thread.daemon = True
        _trade_thread.start()
        _print_log("cfquant ctypes lowlat trade loop started in worker thread")
        return
    _print_log("cfquant ctypes lowlat trade loop entering current QMT thread")
    _run_trade_loop()


def cfquant_ctype_trade_timer(*args, **kwargs):
    _drain_trade_requests("timer")


def _schedule_trade_timer(ContextInfo):
    global _trade_timer_key

    if _trade_timer_key or ContextInfo is None:
        return
    try:
        first_time = dt.datetime.now() + dt.timedelta(seconds=1)
        _trade_timer_key = ContextInfo.schedule_run(
            cfquant_ctype_trade_timer,
            first_time,
            repeat_times=-1,
            interval=dt.timedelta(milliseconds=TRADE_TIMER_INTERVAL_MS),
            name="cfquant_ctype_trade_bridge_pump",
        )
        _print_log("cfquant ctypes lowlat trade timer scheduled key:%s interval_ms:%s" % (_trade_timer_key, TRADE_TIMER_INTERVAL_MS))
    except Exception as e:
        _print_log("cfquant ctypes lowlat trade timer schedule failed:%s" % e)


_attach_normal_status_extra()
if TRADE_LOOP_IN_THREAD:
    _start_trade_loop()


def init(ContextInfo):
    if _normal_bridge:
        _normal_bridge.set_context(ContextInfo)
        _print_log("cfquant ctypes normal context ready version:%s" % _ENTRY_VERSION)
    if _trade_bridge:
        _trade_bridge.set_context(ContextInfo)
        _print_log("cfquant ctypes lowlat trade context ready version:%s" % _ENTRY_VERSION)
    _start_trade_loop()
    _schedule_trade_timer(ContextInfo)


def handlebar(ContextInfo):
    if TRADE_LOOP_IN_THREAD:
        _start_trade_loop()
    _drain_trade_requests("handlebar")
    if _normal_bridge:
        _normal_bridge.pump()


def stop(ContextInfo):
    global _normal_bridge, _trade_bridge, _trade_timer_key

    if ContextInfo is not None and _trade_timer_key:
        try:
            ContextInfo.cancel_schedule_run(_trade_timer_key)
        except Exception as e:
            _print_log("cfquant ctypes lowlat trade timer cancel failed:%s" % e)
        _trade_timer_key = None

    if _trade_bridge:
        _trade_bridge.close()
        _trade_bridge = None
        _print_log("cfquant ctypes lowlat trade bridge stopped")
    if _normal_bridge:
        _normal_bridge.close()
        _normal_bridge = None
        _print_log("cfquant ctypes normal bridge stopped")


def _publish_callback(event_name, obj):
    try:
        if _normal_bridge:
            _normal_bridge.publish_callback_event(event_name, obj)
    except Exception as e:
        _print_log("cfquant ctypes lowlat callback publish failed event=%s error=%s" % (event_name, e))


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
