#coding:gbk
#! /usr/bin/python
# Embedded same-account market entry. Do not load parent entry files at runtime.

import os as _cfquant_market_os

_CFQUANT_MARKET = "SZ"
_CFQUANT_CONFIG_FILENAME = "cfquant_bridge_config_SZ.json"


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


def _cfquant_market_should_set_config_path():
    current = str(_cfquant_market_os.environ.get("CFQUANT_BRIDGE_CONFIG_FILE") or "").strip()
    if not current:
        return True
    source = str(_cfquant_market_os.environ.get("CFQUANT_BRIDGE_CONFIG_FILE_SOURCE") or "").strip()
    if source in ("cfquant_market_entry", "cfquant_entry"):
        return True
    current_name = _cfquant_market_os.path.basename(current).lower()
    market_names = ("cfquant_bridge_config_sh.json", "cfquant_bridge_config_sz.json")
    return current_name in market_names and current_name != _CFQUANT_CONFIG_FILENAME.lower()


if _cfquant_market_should_set_config_path():
    _cfquant_market_os.environ["CFQUANT_BRIDGE_CONFIG_FILE"] = _cfquant_market_config_path()
    _cfquant_market_os.environ["CFQUANT_BRIDGE_CONFIG_FILE_SOURCE"] = "cfquant_market_entry"

# Embedded market entry: CFQUANT_TRADE_LOWLAT_SZ.py
#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib
import io
import json


_trade_bridge = None
DEFAULT_ACCOUNT_ID = ""
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)
RUNTIME_CONFIG = {}
RUNTIME_CHANNELS = {}
QMT_MARKET = os.environ.get("CFQUANT_MARKET", "").strip().upper()


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
            os.path.isfile(os.path.join(cwd, "CFQUANT_TRADE_LOWLAT_SZ.py"))
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
                os.path.isfile(os.path.join(base, "CFQUANT_TRADE_LOWLAT_SZ.py"))
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
    global BRIDGE_ID, RUNTIME_CONFIG, RUNTIME_CHANNELS, QMT_MARKET

    data = _load_runtime_config()
    RUNTIME_CONFIG = data
    if not data:
        return
    if data.get("bridge_id") and _env_allows_runtime_override("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID):
        BRIDGE_ID = data.get("bridge_id")
    if data.get("market"):
        market = str(data.get("market") or "").strip().upper()
        if market in ("SH", "SZ"):
            QMT_MARKET = market
            if not os.environ.get("CFQUANT_MARKET"):
                os.environ["CFQUANT_MARKET"] = market
                os.environ["CFQUANT_MARKET_SOURCE"] = "cfquant_entry"
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


def _install_logging_compat():
    """Keep this entry compatible with older cfquant packages in QMT."""
    logging_module = importlib.import_module("cfquant.logging_i18n")

    if not hasattr(logging_module, "normalize_log_language"):
        def _normalize_log_language(value=None):
            value = str(value or "").strip().lower()
            return "en" if value in ("en", "english") else "zh"

        logging_module.normalize_log_language = _normalize_log_language

    if not hasattr(logging_module, "normalize_log_enabled"):
        def _normalize_log_enabled(value=None):
            if isinstance(value, bool):
                return value
            if value is None:
                return True
            text = str(value).strip().lower()
            return text not in ("0", "false", "no", "off", "disable", "disabled", "closed", "close")

        logging_module.normalize_log_enabled = _normalize_log_enabled

    if not hasattr(logging_module, "_CFQUANT_COMPAT_LOG_LANGUAGE"):
        logging_module._CFQUANT_COMPAT_LOG_LANGUAGE = ""
    if not hasattr(logging_module, "_CFQUANT_COMPAT_LOG_ENABLED"):
        logging_module._CFQUANT_COMPAT_LOG_ENABLED = None

    if not hasattr(logging_module, "get_log_language"):
        def _get_log_language():
            if logging_module._CFQUANT_COMPAT_LOG_LANGUAGE:
                return logging_module._CFQUANT_COMPAT_LOG_LANGUAGE
            return logging_module.normalize_log_language(
                os.environ.get("CFQUANT_QMT_LOG_LANGUAGE")
                or os.environ.get("CFQUANT_LOG_LANGUAGE")
                or "zh"
            )

        logging_module.get_log_language = _get_log_language

    if not hasattr(logging_module, "set_log_language"):
        def _set_log_language(value):
            language = logging_module.normalize_log_language(value)
            logging_module._CFQUANT_COMPAT_LOG_LANGUAGE = language
            return language

        logging_module.set_log_language = _set_log_language

    if not hasattr(logging_module, "get_log_enabled"):
        def _get_log_enabled():
            if logging_module._CFQUANT_COMPAT_LOG_ENABLED is not None:
                return bool(logging_module._CFQUANT_COMPAT_LOG_ENABLED)
            return logging_module.normalize_log_enabled(
                os.environ.get("CFQUANT_QMT_LOG_ENABLED")
                or os.environ.get("CFQUANT_LOG_ENABLED")
                or "1"
            )

        logging_module.get_log_enabled = _get_log_enabled

    if not hasattr(logging_module, "set_log_enabled"):
        def _set_log_enabled(value):
            enabled = logging_module.normalize_log_enabled(value)
            logging_module._CFQUANT_COMPAT_LOG_ENABLED = enabled
            return enabled

        logging_module.set_log_enabled = _set_log_enabled

    if not hasattr(logging_module, "translate_log"):
        def _translate_log(message, language=None):
            return str(message)

        logging_module.translate_log = _translate_log

    return logging_module


_ensure_path()
_apply_runtime_config()

_logging_i18n = _install_logging_compat()
get_log_enabled = _logging_i18n.get_log_enabled
translate_log = _logging_i18n.translate_log

from cfquant import __version__ as _ENTRY_VERSION


def _print_log(message):
    if get_log_enabled():
        print(translate_log(message))


def _load_bridge_starter():
    import cfquant.tx_trade_bridge as tx_trade_bridge

    try:
        tx_trade_bridge = importlib.reload(tx_trade_bridge)
    except Exception as e:
        _print_log("tx trade bridge reload failed:%s" % e)
    return tx_trade_bridge.start_tx_trade_bridge


start_tx_trade_bridge = _load_bridge_starter()

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
BRIDGE_CHANNELS = channels_for_bridge(BRIDGE_ID)
_trade_channel_value = RUNTIME_CHANNELS.get("trade") or RUNTIME_CONFIG.get("trade_channel")
if _trade_channel_value:
    BRIDGE_CHANNELS["trade"] = str(_trade_channel_value).strip()

_trade_bridge = start_tx_trade_bridge(
    None,
    ip="127.0.0.1",
    port=2049,
    token="LTtx",
    request_channel=BRIDGE_CHANNELS["trade"],
    bridge_id=BRIDGE_ID,
    account_id=DEFAULT_ACCOUNT_ID,
    show=True,
)
_print_log("cfquant lowlat trade bridge module loaded")
_print_log("cfquant lowlat entry version:%s" % _ENTRY_VERSION)
_print_log("cfquant bridge id:%s trade_channel:%s" % (BRIDGE_ID, BRIDGE_CHANNELS["trade"]))
if QMT_MARKET:
    _print_log("cfquant lowlat market route market:%s bridge_id:%s" % (QMT_MARKET, BRIDGE_ID))


def _attach_trade_status_extra():
    if not _trade_bridge:
        return
    original_status_extra = _trade_bridge._status_extra

    def status_extra_with_market():
        data = original_status_extra()
        data.update({
            "qmt_runtime_market": QMT_MARKET,
            "qmt_runtime_market_role": RUNTIME_CONFIG.get("market_role") or ("trade" if QMT_MARKET else ""),
            "qmt_runtime_market_parent_bridge_id": RUNTIME_CONFIG.get("market_route_parent_bridge_id") or "",
        })
        return data

    _trade_bridge._status_extra = status_extra_with_market


_attach_trade_status_extra()


def init(ContextInfo):
    if _trade_bridge:
        _trade_bridge.set_context(ContextInfo)
        _print_log("cfquant lowlat trade context ready version:%s" % _ENTRY_VERSION)
        _trade_bridge.run_forever(sleep_seconds=0.001)


def handlebar(ContextInfo):
    pass


def stop(ContextInfo):
    global _trade_bridge

    if _trade_bridge:
        _trade_bridge.close()
        _trade_bridge = None
        _print_log("cfquant lowlat trade bridge stopped")
