# -*- coding: utf-8 -*-
import json
import queue
import socket
import threading
import time

from .config import get_config
from .protocol import decode_value, dumps_message, loads_message, new_id, pack_request


class CfquantError(RuntimeError):
    pass


class CfquantTimeout(TimeoutError):
    pass


PIPE_TRANSPORTS = ("pipe", "ctypes", "named_pipe", "named-pipe")
WEB_LTTX_TRANSPORTS = ("web", "web_lttx", "lttx_web", "web-lttx", "lttx-web")


def _load_txl():
    errors = []
    try:
        from .tx import txl
        return txl
    except Exception as e:
        errors.append("cfquant.tx: %s" % e)
    try:
        from tx import txl
        return txl
    except Exception as e:
        errors.append("tx.py: %s" % e)
    try:
        from LTtx.tx import txl
        return txl
    except Exception as e:
        errors.append("LTtx.tx: %s" % e)
    raise CfquantError("failed to import LTtx txl; tried %s" % "; ".join(errors))


def _tcp_reachable(host, port, timeout=0.35):
    try:
        sock = socket.create_connection((host, int(port)), timeout=float(timeout))
        sock.close()
        return True
    except Exception:
        return False


def _normalize_registry(value):
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except Exception:
            return {}
    if not isinstance(value, dict):
        return {}
    if value.get("schema") != "cfquant.lttx.registry":
        return {}
    return value


def load_lttx_registry(cfg=None):
    cfg = cfg or get_config()
    host = cfg.get("host") or "127.0.0.1"
    port = int(cfg.get("port") or 2049)
    if not _tcp_reachable(host, port):
        return {}
    tx = None
    try:
        txl = _load_txl()
        tx = txl(host, port, cfg.get("token") or "LTtx", show=False)
        tx.start_tx()
        value = tx.get(cfg.get("discovery_key") or "cfquant.runtime")
        return _normalize_registry(value)
    except Exception:
        return {}
    finally:
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass


class LTtxRpcClient(object):
    """
    cfquant 外部端 LTtx/TX RPC 客户端。

    - 通过 start_tx() 向大 QMT 的固定请求频道发送 request。
    - 通过 start_txg(client_id) 订阅自己的专属回包频道。
    - 大 QMT 按请求里的 client_id 原路 push response/event。
    """

    def __init__(self, host=None, port=None, token=None, request_channel=None, timeout=None, client_id=None):
        cfg = get_config()
        self.host = host or cfg["host"]
        self.port = int(port or cfg["port"])
        self.token = token or cfg["token"]
        self.request_channel = request_channel or cfg["request_channel"]
        self.timeout = float(timeout or cfg["timeout"])
        self.client_id = client_id or cfg.get("client_id") or new_id("client")
        self.reply_channel = self.client_id
        self._tx = None
        self._pending = {}
        self._callbacks = {}
        self._lock = threading.RLock()
        self._pending_lock = threading.RLock()
        self._show = True
        self._started = False
        self._recv_thread = None

    def start(self, show=None):
        with self._lock:
            if self._started:
                return
            if show is not None:
                self._show = show
            txl = self._load_txl()
            self._tx = txl(self.host, self.port, self.token, show=self._show)
            self._tx.start_tx()
            self._tx.start_txg(self.client_id)
            self._started = True
            self._recv_thread = threading.Thread(target=self._recv_loop)
            self._recv_thread.daemon = True
            self._recv_thread.start()

    def close(self):
        with self._lock:
            self._started = False
            tx = self._tx
            self._tx = None
            if tx is not None:
                try:
                    tx.Q.put(None)
                except Exception:
                    pass
                try:
                    tx.close()
                except Exception:
                    pass
            with self._pending_lock:
                for q in list(self._pending.values()):
                    try:
                        q.put_nowait({"ok": False, "error": {"message": "cfquant client closed"}})
                    except Exception:
                        pass
                self._pending.clear()

    def request(self, action, params=None, timeout=None, request_channel=None):
        self.start()
        request_id = new_id("req")
        q = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = q
        raw = pack_request(
            action,
            params=params or {},
            reply_channel=self.reply_channel,
            client_id=self.client_id,
            request_id=request_id,
        )
        self._push("request", raw, request_channel or self.request_channel)
        try:
            msg = q.get(timeout=float(timeout or self.timeout))
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise CfquantTimeout("cfquant request timeout: %s" % action)
        if not msg.get("ok"):
            err = msg.get("error") or {}
            raise CfquantError(err.get("message") or str(err))
        return decode_value(msg.get("result"))

    def publish_event(self, channel, payload):
        self.start()
        self._push("event", dumps_message(payload), channel)

    def add_callback(self, event, callback):
        if callback is None:
            return
        self._callbacks.setdefault(event, []).append(callback)

    def remove_callback(self, event, callback):
        callbacks = self._callbacks.get(event) or []
        if callback in callbacks:
            callbacks.remove(callback)

    def _recv_loop(self):
        while self._started:
            try:
                tx = self._tx
                if tx is None:
                    break
                raw = tx.Q.get()
                if raw is None:
                    break
                msg = loads_message(raw)
                if not msg:
                    continue
                msg_type = msg.get("type")
                if msg_type == "response":
                    with self._pending_lock:
                        q = self._pending.pop(msg.get("id"), None)
                    if q:
                        q.put(msg)
                elif msg_type == "event":
                    self._dispatch_event(msg)
            except Exception:
                time.sleep(0.05)
                if not self._started:
                    break

    def _dispatch_event(self, msg):
        event = msg.get("event")
        data = decode_value(msg.get("data"))
        full_msg = dict(msg)
        full_msg["data"] = data
        for callback in list(self._callbacks.get("__event__", [])):
            try:
                callback(full_msg)
            except Exception:
                pass
        for callback in list(self._callbacks.get(event, [])):
            try:
                callback(data)
            except Exception:
                pass
        if event and event.startswith("quote:"):
            quote_msg = dict(msg)
            quote_msg["data"] = data
            if quote_msg.get("subscription_id") is not None and quote_msg.get("subscribe_id") is None:
                quote_msg["subscribe_id"] = quote_msg.get("subscription_id")
            for callback in list(self._callbacks.get("quote", [])):
                try:
                    callback(quote_msg)
                except Exception:
                    pass

    def _push(self, key, payload, channel):
        tx = self._tx
        if tx is None:
            raise CfquantError("cfquant LTtx client not started")
        result = tx.push(key, payload, channel)
        if isinstance(result, dict) and result.get("code", 0) != 0:
            raise CfquantError(result.get("msg") or "LTtx push failed")
        return result

    def _load_txl(self):
        return _load_txl()


class WebLttxRpcClient(LTtxRpcClient):
    """
    外部 Python 默认路由客户端。

    请求仍然通过 LTtx 发送，但目标频道是 Web 服务注册的统一路由频道。
    Web 服务再根据账号配置选择 ctypes 通用桥或 LTtx 高级桥。
    """

    def __init__(
        self,
        host=None,
        port=None,
        token=None,
        request_channel=None,
        timeout=None,
        client_id=None,
        registry=None,
    ):
        cfg = get_config()
        self.registry = registry or load_lttx_registry(cfg)
        channel = (
            request_channel
            or self.registry.get("web_request_channel")
            or cfg.get("web_request_channel")
            or "cfquant.web.request"
        )
        super(WebLttxRpcClient, self).__init__(
            host=host,
            port=port,
            token=token,
            request_channel=channel,
            timeout=timeout,
            client_id=client_id,
        )


def _registry_has_web_route(registry):
    if not isinstance(registry, dict):
        return False
    web_route = registry.get("web_route") if isinstance(registry.get("web_route"), dict) else {}
    return bool(registry.get("web_request_channel") and web_route.get("enabled", True))


def create_rpc_client(request_channel=None, timeout=None, client_id=None, transport=None, bridge_id=None):
    cfg = get_config()
    mode = str(transport or cfg.get("transport") or "auto").lower()
    registry = {}
    if mode == "auto":
        registry = load_lttx_registry(cfg)
        if _registry_has_web_route(registry):
            return WebLttxRpcClient(
                timeout=timeout or cfg.get("timeout"),
                client_id=client_id,
                registry=registry,
            )
        mode = str(registry.get("direct_fallback_transport") or "ctypes").lower()
    if mode in WEB_LTTX_TRANSPORTS:
        return WebLttxRpcClient(
            timeout=timeout or cfg.get("timeout"),
            client_id=client_id,
            registry=registry or None,
        )
    if mode in PIPE_TRANSPORTS:
        from .pipe_client import PipeRpcClient

        return PipeRpcClient(
            pipe_name=cfg.get("pipe_name"),
            request_channel=request_channel or cfg.get("request_channel"),
            timeout=timeout or cfg.get("timeout"),
            client_id=client_id,
            connect_timeout_ms=cfg.get("pipe_connect_timeout_ms"),
        )
    return LTtxRpcClient(
        host=cfg.get("host"),
        port=cfg.get("port"),
        token=cfg.get("token"),
        request_channel=request_channel or cfg.get("request_channel"),
        timeout=timeout or cfg.get("timeout"),
        client_id=client_id,
    )


_default_client = None
_client_lock = threading.Lock()


def get_client():
    global _default_client
    with _client_lock:
        if _default_client is None:
            cfg = get_config()
            _default_client = create_rpc_client(
                request_channel=cfg.get("request_channel"),
                timeout=cfg.get("timeout"),
                client_id=cfg.get("client_id"),
            )
        return _default_client


def configure(**kwargs):
    from .config import configure as configure_config

    configure_config(**kwargs)
    global _default_client
    with _client_lock:
        if _default_client is not None:
            _default_client.close()
        _default_client = None
