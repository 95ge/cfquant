# -*- coding: utf-8 -*-
import os
import re


LEGACY_NORMAL_REQUEST_CHANNEL = "cfquant.normal.request"
LEGACY_TRADE_REQUEST_CHANNEL = "cfquant.trade.request"
LEGACY_CALLBACK_EVENT_CHANNEL = "cfquant.callback.event"


def normalize_bridge_id(value=None):
    value = str(value or "").strip()
    if not value:
        return "default"
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", value)
    return value or "default"


def bridge_id_from_env(default="default"):
    return normalize_bridge_id(os.environ.get("CFQUANT_BRIDGE_ID") or default)


def bridge_env_prefix(bridge_id):
    safe = re.sub(r"[^0-9A-Za-z]+", "_", normalize_bridge_id(bridge_id)).upper()
    return "CFQUANT_BRIDGE_%s_" % safe


def channels_for_bridge(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or bridge_id_from_env())
    prefix = bridge_env_prefix(bridge_id)
    if bridge_id == "default":
        default_normal = os.environ.get("CFQUANT_NORMAL_REQUEST_CHANNEL", LEGACY_NORMAL_REQUEST_CHANNEL)
        default_trade = os.environ.get("CFQUANT_TRADE_REQUEST_CHANNEL", LEGACY_TRADE_REQUEST_CHANNEL)
        default_callback = os.environ.get("CFQUANT_CALLBACK_EVENT_CHANNEL", LEGACY_CALLBACK_EVENT_CHANNEL)
    else:
        default_normal = "cfquant.%s.normal.request" % bridge_id
        default_trade = "cfquant.%s.trade.request" % bridge_id
        default_callback = "cfquant.%s.callback.event" % bridge_id
    return {
        "normal": os.environ.get(prefix + "NORMAL_REQUEST_CHANNEL", default_normal),
        "trade": os.environ.get(prefix + "TRADE_REQUEST_CHANNEL", default_trade),
        "callback": os.environ.get(prefix + "CALLBACK_EVENT_CHANNEL", default_callback),
    }


def bridge_name(bridge_id):
    bridge_id = normalize_bridge_id(bridge_id)
    prefix = bridge_env_prefix(bridge_id)
    return os.environ.get(prefix + "NAME", bridge_id)


def configured_bridge_ids():
    raw = os.environ.get("CFQUANT_BRIDGE_IDS")
    if raw:
        ids = [normalize_bridge_id(item) for item in raw.split(",") if item.strip()]
    else:
        ids = [bridge_id_from_env()]
    seen = set()
    result = []
    for bridge_id in ids:
        if bridge_id in seen:
            continue
        seen.add(bridge_id)
        result.append(bridge_id)
    return result or ["default"]


def configured_bridges():
    result = {}
    for bridge_id in configured_bridge_ids():
        result[bridge_id] = {
            "id": bridge_id,
            "name": bridge_name(bridge_id),
            "channels": channels_for_bridge(bridge_id),
        }
    return result
