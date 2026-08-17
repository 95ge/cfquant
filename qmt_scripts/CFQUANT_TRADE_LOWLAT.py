#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib
import json


_trade_bridge = None
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

    try:
        tx_trade_bridge = importlib.reload(tx_trade_bridge)
    except Exception as e:
        _print_log("tx trade bridge reload failed:%s" % e)
    return tx_trade_bridge.start_tx_trade_bridge


start_tx_trade_bridge = _load_bridge_starter()

from cfquant.channels import channels_for_bridge, normalize_bridge_id

BRIDGE_ID = normalize_bridge_id(BRIDGE_ID)
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
