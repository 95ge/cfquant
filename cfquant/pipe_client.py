# -*- coding: utf-8 -*-
import queue
import threading
import time

from .config import get_config
from .pipe_transport import (
    DEFAULT_PIPE_NAME,
    connect_pipe,
    dumps_pipe_message,
    loads_pipe_message,
    normalize_pipe_name,
)
from .protocol import decode_value, dumps_message, loads_message, new_id, pack_request


class PipeRpcClient(object):
    """
    External Python RPC client over the cfquant named-pipe hub.
    """

    def __init__(self, pipe_name=None, request_channel=None, timeout=None, client_id=None, connect_timeout_ms=None):
        cfg = get_config()
        self.pipe_name = normalize_pipe_name(pipe_name or cfg.get("pipe_name") or DEFAULT_PIPE_NAME)
        self.request_channel = request_channel or cfg["request_channel"]
        self.timeout = float(timeout or cfg["timeout"])
        self.client_id = client_id or cfg.get("client_id") or new_id("pipe_client")
        self.reply_channel = self.client_id
        self.connect_timeout_ms = int(connect_timeout_ms or cfg.get("pipe_connect_timeout_ms") or 3000)
        self._rx_conn = None
        self._tx_conn = None
        self._pending = {}
        self._callbacks = {}
        self._lock = threading.RLock()
        self._pending_lock = threading.RLock()
        self._started = False
        self._recv_thread = None

    def start(self):
        with self._lock:
            if self._started:
                return
            self._rx_conn = connect_pipe(self.pipe_name, timeout_ms=self.connect_timeout_ms)
            self._rx_conn.write_frame(dumps_pipe_message({
                "type": "hello",
                "role": "api_rx",
                "client_id": self.client_id,
            }))
            self._tx_conn = connect_pipe(self.pipe_name, timeout_ms=self.connect_timeout_ms)
            self._tx_conn.write_frame(dumps_pipe_message({
                "type": "hello",
                "role": "api_tx",
                "client_id": self.client_id,
            }))
            self._started = True
            self._recv_thread = threading.Thread(target=self._recv_loop)
            self._recv_thread.daemon = True
            self._recv_thread.start()

    def close(self):
        with self._lock:
            self._started = False
            conns = [self._rx_conn, self._tx_conn]
            self._rx_conn = None
            self._tx_conn = None
            for conn in conns:
                if conn is None:
                    continue
                try:
                    conn.close()
                except Exception:
                    pass
            with self._pending_lock:
                for q in list(self._pending.values()):
                    try:
                        q.put_nowait({"ok": False, "error": {"message": "cfquant pipe client closed"}})
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
        self._send_request(raw, request_channel or self.request_channel)
        try:
            msg = q.get(timeout=float(timeout or self.timeout))
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            from .client import CfquantTimeout

            raise CfquantTimeout("cfquant pipe request timeout: %s" % action)
        if not msg.get("ok"):
            err = msg.get("error") or {}
            from .client import CfquantError

            raise CfquantError(err.get("message") or str(err))
        return decode_value(msg.get("result"))

    def publish_event(self, channel, payload):
        self.start()
        self._send_request(dumps_message(payload), channel)

    def add_callback(self, event, callback):
        if callback is None:
            return
        self._callbacks.setdefault(event, []).append(callback)

    def remove_callback(self, event, callback):
        callbacks = self._callbacks.get(event) or []
        if callback in callbacks:
            callbacks.remove(callback)

    def _send_request(self, payload, request_channel):
        conn = self._tx_conn
        if conn is None:
            from .client import CfquantError

            raise CfquantError("cfquant pipe client not started")
        conn.write_frame(dumps_pipe_message({
            "type": "request",
            "role": "api_tx",
            "client_id": self.client_id,
            "request_channel": request_channel,
            "payload": payload,
        }))

    def _recv_loop(self):
        while self._started:
            try:
                conn = self._rx_conn
                if conn is None:
                    break
                raw = conn.read_frame()
                if raw is None:
                    break
                envelope = loads_pipe_message(raw)
                payload = envelope.get("payload") if envelope else raw
                msg = loads_message(payload)
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
