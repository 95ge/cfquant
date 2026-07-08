# -*- coding: utf-8 -*-
import os

from .channels import bridge_id_from_env, channels_for_bridge


DEFAULT_HOST = os.environ.get("CFQUANT_LTTX_HOST", os.environ.get("CFQUANT_SOCKET_HOST", "127.0.0.1"))
DEFAULT_PORT = int(os.environ.get("CFQUANT_LTTX_PORT", os.environ.get("CFQUANT_SOCKET_PORT", "2049")))
DEFAULT_TOKEN = os.environ.get("CFQUANT_LTTX_TOKEN", os.environ.get("CFQUANT_SOCKET_TOKEN", "LTtx"))
DEFAULT_BRIDGE_ID = bridge_id_from_env()
DEFAULT_REQUEST_CHANNEL = os.environ.get(
    "CFQUANT_REQUEST_CHANNEL",
    channels_for_bridge(DEFAULT_BRIDGE_ID)["normal"],
)
DEFAULT_TIMEOUT = float(os.environ.get("CFQUANT_TIMEOUT", "15"))
DEFAULT_CLIENT_ID = os.environ.get("CFQUANT_CLIENT_ID")


_config = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    "token": DEFAULT_TOKEN,
    "bridge_id": DEFAULT_BRIDGE_ID,
    "request_channel": DEFAULT_REQUEST_CHANNEL,
    "timeout": DEFAULT_TIMEOUT,
    "client_id": DEFAULT_CLIENT_ID,
}


def configure(host=None, port=None, token=None, request_channel=None, timeout=None, client_id=None, bridge_id=None):
    """配置 cfquant 连接到 LTtx/TX 桥接端的参数。"""
    if host is not None:
        _config["host"] = host
    if port is not None:
        _config["port"] = int(port)
    if token is not None:
        _config["token"] = token
    if bridge_id is not None:
        from .channels import normalize_bridge_id

        _config["bridge_id"] = normalize_bridge_id(bridge_id)
        if request_channel is None:
            _config["request_channel"] = channels_for_bridge(_config["bridge_id"])["normal"]
    if request_channel is not None:
        _config["request_channel"] = request_channel
    if timeout is not None:
        _config["timeout"] = float(timeout)
    if client_id is not None:
        _config["client_id"] = client_id


def get_config():
    return dict(_config)
