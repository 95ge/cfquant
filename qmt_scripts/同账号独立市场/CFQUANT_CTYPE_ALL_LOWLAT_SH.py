#coding:gbk
#! /usr/bin/python
# Embedded same-account market entry. Do not load parent entry files at runtime.

import os as _cfquant_market_os

_CFQUANT_MARKET = "SH"
_CFQUANT_CONFIG_FILENAME = "cfquant_bridge_config_SH.json"


def _cfquant_market_base_dir():
    path = globals().get("__file__") or ""
    if path and not str(path).startswith("<"):
        try:
            return _cfquant_market_os.path.dirname(_cfquant_market_os.path.abspath(path))
        except Exception:
            return ""
    try:
        return _cfquant_market_os.path.abspath(_cfquant_market_os.getcwd())
    except Exception:
        return ""


def _cfquant_market_config_path():
    base = _cfquant_market_base_dir()
    parent = _cfquant_market_os.path.dirname(base) if base else ""
    if base and _cfquant_market_os.path.basename(base).lower() == "python" and parent:
        return _cfquant_market_os.path.join(parent, "bin.x64", _CFQUANT_CONFIG_FILENAME)
    if base:
        return _cfquant_market_os.path.join(base, _CFQUANT_CONFIG_FILENAME)
    return _CFQUANT_CONFIG_FILENAME


_cfquant_market_os.environ["CFQUANT_MARKET"] = _CFQUANT_MARKET
_cfquant_market_os.environ["CFQUANT_MARKET_SOURCE"] = "cfquant_market_entry"
if not _cfquant_market_os.environ.get("CFQUANT_BRIDGE_CONFIG_FILE"):
    _cfquant_market_os.environ["CFQUANT_BRIDGE_CONFIG_FILE"] = _cfquant_market_config_path()
    _cfquant_market_os.environ["CFQUANT_BRIDGE_CONFIG_FILE_SOURCE"] = "cfquant_market_entry"

# Embedded market entry: CFQUANT_CTYPE_ALL_LOWLAT_SH.py
#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib
import datetime as dt
import io
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
DEFAULT_ACCOUNT_ID = str(os.environ.get("CFQUANT_ACCOUNT_ID") or "").strip()
DEFAULT_ACCOUNT_TYPE = str(os.environ.get("CFQUANT_ACCOUNT_TYPE") or "STOCK").strip().upper()
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)
PIPE_NAME = os.environ.get("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub")
RUNTIME_CONFIG_PATH = ""
RUNTIME_CONFIG = {}
RUNTIME_CHANNELS = {}
QMT_MARKET = os.environ.get("CFQUANT_MARKET", "").strip().upper()
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
            os.path.isfile(os.path.join(cwd, "CFQUANT_CTYPE_ALL_LOWLAT_SH.py"))
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
                os.path.isfile(os.path.join(base, "CFQUANT_CTYPE_ALL_LOWLAT_SH.py"))
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
        market = str(os.environ.get("CFQUANT_MARKET") or QMT_MARKET or "").strip().upper()
        market_filenames = []
        if market in ("SH", "SZ"):
            market_filenames.append("cfquant_bridge_config_%s.json" % market)
        if os.path.basename(base_dir).lower() == "python":
            for filename in market_filenames:
                candidates.append(os.path.join(parent_dir, "bin.x64", filename))
                candidates.append(os.path.join(base_dir, filename))
            candidates.append(os.path.join(parent_dir, "bin.x64", "cfquant_bridge_config.json"))
            candidates.append(os.path.join(base_dir, "cfquant_bridge_config.json"))
        else:
            for filename in market_filenames:
                candidates.append(os.path.join(base_dir, filename))
                candidates.append(os.path.join(base_dir, "bin.x64", filename))
            candidates.append(os.path.join(base_dir, "cfquant_bridge_config.json"))
            candidates.append(os.path.join(base_dir, "bin.x64", "cfquant_bridge_config.json"))
        for filename in market_filenames:
            candidates.append(os.path.join(parent_dir, filename))
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
        for index, opener in enumerate((
            lambda: io.open(path, "r", encoding="utf-8"),
            lambda: open(path, "r"),
        )):
            try:
                with opener() as f:
                    data = json.loads(f.read())
                if isinstance(data, dict):
                    return path, data
            except Exception as e:
                if index == 1:
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


def _env_allows_runtime_override(name, default_value=""):
    value = str(os.environ.get(name) or "").strip()
    if not value:
        return True
    if str(os.environ.get("%s_SOURCE" % name) or "").strip() == "cfquant_entry":
        return True
    return bool(default_value and value == default_value)


def _apply_runtime_config():
    global BRIDGE_ID, PIPE_NAME, RUNTIME_CONFIG_PATH, RUNTIME_CONFIG, RUNTIME_CHANNELS, QMT_MARKET, DEFAULT_ACCOUNT_ID, DEFAULT_ACCOUNT_TYPE

    path, data = _load_runtime_config()
    RUNTIME_CONFIG_PATH = path
    RUNTIME_CONFIG = data
    if not data:
        _write_runtime_log("cfquant ctypes runtime config not found")
        return
    if data.get("account_id") and not DEFAULT_ACCOUNT_ID:
        DEFAULT_ACCOUNT_ID = str(data.get("account_id") or "").strip()
    if data.get("account_type"):
        DEFAULT_ACCOUNT_TYPE = str(data.get("account_type") or DEFAULT_ACCOUNT_TYPE or "STOCK").strip().upper()
    if data.get("bridge_id") and _env_allows_runtime_override("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID):
        BRIDGE_ID = data.get("bridge_id")
    if data.get("market"):
        market = str(data.get("market") or "").strip().upper()
        if market in ("SH", "SZ"):
            QMT_MARKET = market
            if not os.environ.get("CFQUANT_MARKET"):
                os.environ["CFQUANT_MARKET"] = market
                os.environ["CFQUANT_MARKET_SOURCE"] = "cfquant_entry"
    if data.get("pipe_name") and _env_allows_runtime_override("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub"):
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
    import cfquant as _cfquant
    from cfquant import __version__ as _ENTRY_VERSION
    from cfquant.logging_i18n import get_log_enabled, translate_log
    from cfquant.protocol import loads_message
    _write_runtime_log(
        "cfquant import ok version=%s module_file=%s"
        % (_ENTRY_VERSION, getattr(_cfquant, "__file__", "<unknown>"))
    )
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
QMT_MARKET = str(QMT_MARKET or os.environ.get("CFQUANT_MARKET") or RUNTIME_CONFIG.get("market") or "").strip().upper()
if QMT_MARKET not in ("SH", "SZ"):
    QMT_MARKET = ""
if not os.environ.get("CFQUANT_BRIDGE_ID"):
    os.environ["CFQUANT_BRIDGE_ID"] = BRIDGE_ID
    os.environ["CFQUANT_BRIDGE_ID_SOURCE"] = "cfquant_entry"
if QMT_MARKET and not os.environ.get("CFQUANT_MARKET"):
    os.environ["CFQUANT_MARKET"] = QMT_MARKET
    os.environ["CFQUANT_MARKET_SOURCE"] = "cfquant_entry"
if PIPE_NAME and not os.environ.get("CFQUANT_PIPE_NAME"):
    os.environ["CFQUANT_PIPE_NAME"] = PIPE_NAME
    os.environ["CFQUANT_PIPE_NAME_SOURCE"] = "cfquant_entry"
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
if DEFAULT_ACCOUNT_TYPE and _normal_bridge:
    _normal_bridge.account_type = DEFAULT_ACCOUNT_TYPE

_trade_bridge = start_pipe_trade_bridge(
    None,
    pipe_name=PIPE_NAME,
    request_channel=BRIDGE_CHANNELS["trade"],
    bridge_id=BRIDGE_ID,
    account_id=DEFAULT_ACCOUNT_ID,
    show=True,
    connect_timeout_ms=PIPE_CONNECT_TIMEOUT_MS,
)
if DEFAULT_ACCOUNT_TYPE and _trade_bridge:
    _trade_bridge.account_type = DEFAULT_ACCOUNT_TYPE

_print_log("cfquant ctypes all-in-one lowlat bridge module loaded")
_print_log("cfquant ctypes all-in-one lowlat entry version:%s" % _ENTRY_VERSION)
_print_log("cfquant ctypes bridge id:%s account:%s/%s pipe:%s normal_channel:%s trade_channel:%s callback_channel:%s" % (
    BRIDGE_ID,
    DEFAULT_ACCOUNT_ID or "-",
    DEFAULT_ACCOUNT_TYPE or "-",
    PIPE_NAME,
    BRIDGE_CHANNELS["normal"],
    BRIDGE_CHANNELS["trade"],
    BRIDGE_CHANNELS["callback"],
))
if QMT_MARKET:
    _print_log("cfquant ctypes market route market:%s bridge_id:%s" % (QMT_MARKET, BRIDGE_ID))
_print_log("cfquant ctypes trade loop in thread:%s sleep_seconds:%s" % (TRADE_LOOP_IN_THREAD, TRADE_SLEEP_SECONDS))


def _attach_normal_status_extra():
    if not _normal_bridge:
        return
    original_status_extra = _normal_bridge._status_extra

    def status_extra_with_trade():
        data = original_status_extra()
        data.update({
            "qmt_runtime_core_version": _ENTRY_VERSION,
            "qmt_runtime_module_file": getattr(_cfquant, "__file__", ""),
            "qmt_runtime_entry_file": _entry_file_path() or "<string>",
            "qmt_runtime_market": QMT_MARKET,
            "qmt_runtime_market_role": RUNTIME_CONFIG.get("market_role") or ("trade" if QMT_MARKET else ""),
            "qmt_runtime_market_parent_bridge_id": RUNTIME_CONFIG.get("market_route_parent_bridge_id") or "",
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


_QMT_TRADE_CALLBACK_REGISTERED = False


def _register_qmt_trade_callback(ContextInfo, stage):
    global _QMT_TRADE_CALLBACK_REGISTERED

    if ContextInfo is None or _QMT_TRADE_CALLBACK_REGISTERED:
        return
    func = getattr(ContextInfo, "register_callback", None)
    if not callable(func):
        _print_log("cfquant ctypes qmt trade callback register skipped stage=%s reason=missing register_callback" % stage)
        return
    try:
        func(0)
        _QMT_TRADE_CALLBACK_REGISTERED = True
        _print_log("cfquant ctypes qmt trade callback registered stage=%s" % stage)
    except Exception as e:
        _print_log("cfquant ctypes qmt trade callback register failed stage=%s error=%s" % (stage, e))


def _refresh_auto_trade_callback(stage):
    for bridge_name, bridge in (("normal", _normal_bridge), ("trade", _trade_bridge)):
        if bridge is None or not hasattr(bridge, "_enable_auto_trade_callback"):
            continue
        try:
            bridge.auto_trade_callback_enabled = False
            bridge._enable_auto_trade_callback()
            _print_log("cfquant ctypes auto trade callback refreshed stage=%s bridge=%s" % (stage, bridge_name))
        except Exception as e:
            _print_log("cfquant ctypes auto trade callback refresh failed stage=%s bridge=%s error=%s" % (stage, bridge_name, e))


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
    if _normal_bridge:
        _normal_bridge.set_context(ContextInfo)
        _print_log("cfquant ctypes normal context ready version:%s" % _ENTRY_VERSION)
    if _trade_bridge:
        _trade_bridge.set_context(ContextInfo)
        _print_log("cfquant ctypes lowlat trade context ready version:%s" % _ENTRY_VERSION)
    _start_trade_loop()
    _schedule_trade_timer(ContextInfo)


def after_init(ContextInfo):
    _register_qmt_trade_callback(ContextInfo, "after_init")
    _refresh_auto_trade_callback("after_init")


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
        _print_log("cfquant ctypes raw qmt callback received event=%s %s" % (event_name, _callback_brief(obj)))
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
