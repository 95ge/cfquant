# -*- coding: utf-8 -*-
import queue
import threading
import time

from .config import get_config
from .protocol import decode_value, dumps_message, loads_message, new_id, pack_request


class CfquantError(RuntimeError):
    pass


class CfquantTimeout(TimeoutError):
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
        self._started = False
        self._recv_thread = None

    def start(self):
        with self._lock:
            if self._started:
                return
            txl = self._load_txl()
            self._tx = txl(self.host, self.port, self.token)
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
        try:
            from tx import txl
        except Exception as e:
            raise CfquantError("无法导入 LTtx txl，请确认 tx.py 在 Python 路径中: %s" % e)
        return txl


_default_client = None
_client_lock = threading.Lock()


def get_client():
    global _default_client
    with _client_lock:
        if _default_client is None:
            _default_client = LTtxRpcClient()
        return _default_client


def configure(**kwargs):
    from .config import configure as configure_config

    configure_config(**kwargs)
    global _default_client
    with _client_lock:
        if _default_client is not None:
            _default_client.close()
        _default_client = None
