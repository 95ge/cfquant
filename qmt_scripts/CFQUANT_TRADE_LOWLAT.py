#coding:gbk
#! /usr/bin/python

import os
import sys
import importlib


_trade_bridge = None
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

    try:
        tx_trade_bridge = importlib.reload(tx_trade_bridge)
    except Exception as e:
        print("tx trade bridge reload failed:%s" % e)
    return tx_trade_bridge.start_tx_trade_bridge


start_tx_trade_bridge = _load_bridge_starter()

from cfquant.channels import channels_for_bridge, normalize_bridge_id

BRIDGE_ID = normalize_bridge_id(BRIDGE_ID)
BRIDGE_CHANNELS = channels_for_bridge(BRIDGE_ID)

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
print("cfquant lowlat trade bridge module loaded")
print("cfquant lowlat entry version:%s" % _ENTRY_VERSION)
print("cfquant bridge id:%s trade_channel:%s" % (BRIDGE_ID, BRIDGE_CHANNELS["trade"]))


def init(ContextInfo):
    if _trade_bridge:
        _trade_bridge.set_context(ContextInfo)
        print("cfquant lowlat trade context ready version:%s" % _ENTRY_VERSION)
        _trade_bridge.run_forever(sleep_seconds=0.001)


def handlebar(ContextInfo):
    pass


def stop(ContextInfo):
    global _trade_bridge

    if _trade_bridge:
        _trade_bridge.close()
        _trade_bridge = None
        print("cfquant lowlat trade bridge stopped")
