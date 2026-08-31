# -*- coding: utf-8 -*-
import queue
import threading

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
            if self._started and self._recv_thread is not None and self._recv_thread.is_alive():
                return
            if self._started:
                self._started = False
                self._close_conns_locked()
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
            self._recv_thread = threading.Thread(target=self._recv_loop, args=(self._rx_conn,))
            self._recv_thread.daemon = True
            self._recv_thread.start()

    def close(self):
        with self._lock:
            self._started = False
            self._close_conns_locked()
        self._fail_pending("cfquant pipe client closed")

    def request(self, action, params=None, timeout=None, request_channel=None):
        self.start()
        effective_timeout = float(timeout or self.timeout)
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
            timeout=effective_timeout,
        )
        try:
            self._send_request(raw, request_channel or self.request_channel)
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            self.close()
            raise
        try:
            msg = q.get(timeout=effective_timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            self.close()
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

    def _recv_loop(self, expected_conn):
        disconnect_message = "cfquant pipe connection closed"
        while True:
            try:
                with self._lock:
                    if not self._started or self._rx_conn is not expected_conn:
                        return
                    conn = expected_conn
                if conn is None:
                    disconnect_message = "cfquant pipe receive connection missing"
                    break
                raw = conn.read_frame()
                if raw is None:
                    disconnect_message = "cfquant pipe receive connection closed"
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
            except Exception as e:
                disconnect_message = "cfquant pipe receive failed: %s" % e
                break
        self._mark_disconnected(disconnect_message, expected_conn=expected_conn)

    def _mark_disconnected(self, message, expected_conn=None):
        with self._lock:
            if expected_conn is not None and self._rx_conn is not expected_conn:
                return
            if not self._started and self._rx_conn is None and self._tx_conn is None:
                return
            self._started = False
            self._close_conns_locked()
        self._fail_pending(message)

    def _close_conns_locked(self):
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

    def _fail_pending(self, message):
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for q in pending:
            try:
                q.put_nowait({"ok": False, "error": {"message": message}})
            except Exception:
                pass

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
