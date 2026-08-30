# -*- coding: utf-8 -*-
import os

from .channels import bridge_id_from_env, channels_for_bridge


DEFAULT_HOST = os.environ.get("CFQUANT_LTTX_HOST", os.environ.get("CFQUANT_SOCKET_HOST", "127.0.0.1"))
DEFAULT_PORT = int(os.environ.get("CFQUANT_LTTX_PORT", os.environ.get("CFQUANT_SOCKET_PORT", "2049")))
DEFAULT_TOKEN = os.environ.get("CFQUANT_LTTX_TOKEN", os.environ.get("CFQUANT_SOCKET_TOKEN", "LTtx"))
DEFAULT_TRANSPORT = os.environ.get("CFQUANT_TRANSPORT", "auto")
DEFAULT_PIPE_NAME = os.environ.get("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub")
DEFAULT_PIPE_CONNECT_TIMEOUT_MS = int(os.environ.get("CFQUANT_PIPE_CONNECT_TIMEOUT_MS", "3000"))
DEFAULT_DISCOVERY_KEY = os.environ.get("CFQUANT_DISCOVERY_KEY", "cfquant.runtime")
DEFAULT_WEB_REQUEST_CHANNEL = os.environ.get("CFQUANT_WEB_REQUEST_CHANNEL", "cfquant.web.request")
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
    "transport": DEFAULT_TRANSPORT,
    "pipe_name": DEFAULT_PIPE_NAME,
    "pipe_connect_timeout_ms": DEFAULT_PIPE_CONNECT_TIMEOUT_MS,
    "discovery_key": DEFAULT_DISCOVERY_KEY,
    "web_request_channel": DEFAULT_WEB_REQUEST_CHANNEL,
}


def configure(
    host=None,
    port=None,
    token=None,
    request_channel=None,
    timeout=None,
    client_id=None,
    bridge_id=None,
    transport=None,
    pipe_name=None,
    pipe_connect_timeout_ms=None,
    discovery_key=None,
    web_request_channel=None,
):
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
    if transport is not None:
        _config["transport"] = str(transport or "ctypes").lower()
    if pipe_name is not None:
        _config["pipe_name"] = pipe_name
    if pipe_connect_timeout_ms is not None:
        _config["pipe_connect_timeout_ms"] = int(pipe_connect_timeout_ms)
    if discovery_key is not None:
        _config["discovery_key"] = str(discovery_key or DEFAULT_DISCOVERY_KEY)
    if web_request_channel is not None:
        _config["web_request_channel"] = str(web_request_channel or DEFAULT_WEB_REQUEST_CHANNEL)


def get_config():
    return dict(_config)
