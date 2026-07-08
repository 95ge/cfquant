# -*- coding: utf-8 -*-
import datetime as dt
import json
import queue
import threading
import time

from .protocol import loads_message, pack_event, pack_response
from .tx_trade_bridge import TxTradeBridge


class NormalQmtBridge(TxTradeBridge):
    def __init__(
        self,
        context,
        ip="127.0.0.1",
        port=2049,
        token="LTtx",
        request_channel="cfquant.request",
        callback_event_channel="cfquant.callback.event",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
        pump_max_count=20,
        pump_max_ms=10,
    ):
        super(NormalQmtBridge, self).__init__(
            context,
            ip=ip,
            port=port,
            token=token,
            request_channel=request_channel,
            bridge_id=bridge_id,
            account_id=account_id,
            show=show,
            globals_dict=globals_dict,
        )
        self.request_queue = queue.Queue(maxsize=10000)
        self.recv_thread = None
        self.worker_thread = None
        self.worker_event = threading.Event()
        self.worker_source = ""
        self.worker_source_lock = threading.Lock()
        self.pump_max_count = int(pump_max_count)
        self.pump_max_ms = float(pump_max_ms)
        self.subscription_seq = 0
        self.quote_subscriptions = {}
        self.whole_quote_publish_sub_id = None
        self.whole_quote_publish_enabled = False
        self.whole_quote_sub_id = None
        self.schedule_key = None
        self.callback_event_channel = callback_event_channel
        self.bridge_id = bridge_id or "default"

    def start(self):
        if self.running:
            return self
        self.running = True
        txl = self._load_txl()
        self.tx = txl(self.ip, self.port, self.token)
        self.tx.start_tx()
        self.tx.start_txg(self.request_channel)
        self.recv_thread = threading.Thread(target=self._recv_loop)
        self.recv_thread.daemon = True
        self.recv_thread.start()
        self._log(
            "normal bridge started LTtx=%s:%s request_channel=%s"
            % (self.ip, self.port, self.request_channel)
        )
        return self

    def set_context(self, context):
        self.context = context
        self._subscribe_internal_whole_quote()
        self._start_worker_thread(context)
        self._schedule_timer()
        self._log("normal bridge worker is released by quote/timer/handlebar callbacks")
        self._log("normal bridge context ready")

    def close(self):
        self.running = False
        self.worker_event.set()
        if self.context is not None and self.schedule_key:
            try:
                self.context.cancel_schedule_run(self.schedule_key)
            except Exception:
                pass
        super(NormalQmtBridge, self).close()

    def _recv_loop(self):
        while self.running:
            try:
                raw = self.tx.Q.get()
                if raw is None:
                    break
                self._handle_raw_from_thread(raw)
            except Exception as e:
                if self.running:
                    self._log("normal bridge recv error: %s" % e)
                time.sleep(0.05)

    def _handle_raw_from_thread(self, raw):
        msg = loads_message(raw)
        if not msg or msg.get("type") != "request":
            return
        action = msg.get("action")
        if action == "cfquant.ping":
            self._send_response(msg, {"pong": True, "ts": time.time(), "request_channel": self.request_channel})
            return
        if action == "xtdata.subscribe_whole_quote":
            self._handle_whole_quote_publish_subscribe(msg)
            return
        if action == "xtdata.subscribe_quote":
            self._handle_quote_subscribe(msg, kind="quote")
            return
        if action == "xtdata.unsubscribe_quote":
            self._handle_quote_unsubscribe(msg)
            return
        try:
            self.request_queue.put_nowait((msg, time.time()))
            self._log(
                "normal bridge request queued action=%s id=%s queue_size=%s"
                % (msg.get("action"), msg.get("id"), self.request_queue.qsize())
            )
        except queue.Full as e:
            self._send_error(msg, e)

    def _start_worker_thread(self, context):
        if self.worker_thread is not None and self.worker_thread.is_alive():
            return
        self.context = context
        self.worker_thread = threading.Thread(target=self._worker_loop, args=(context,))
        self.worker_thread.daemon = True
        self.worker_thread.start()
        self._log("normal bridge worker thread started in init context")

    def _handle_quote_subscribe(self, msg, kind):
        self.subscription_seq += 1
        sub_id = self.subscription_seq
        params = msg.get("params") or {}
        self.quote_subscriptions[sub_id] = {
            "kind": kind,
            "client_id": msg.get("client_id"),
            "stock_code": params.get("stock_code", ""),
            "code_list": params.get("code_list", params.get("stock_list", [])),
        }
        self._send_response(msg, {"subscribe_id": sub_id})
        self._log("normal bridge quote subscribed id=%s kind=%s" % (sub_id, kind))

    def _handle_whole_quote_publish_subscribe(self, msg):
        if self.whole_quote_publish_sub_id is None:
            self.subscription_seq += 1
            self.whole_quote_publish_sub_id = self.subscription_seq
        sub_id = self.whole_quote_publish_sub_id
        params = msg.get("params") or {}
        self.quote_subscriptions[sub_id] = {
            "kind": "whole_quote",
            "client_id": msg.get("client_id"),
            "code_list": params.get("code_list", params.get("stock_list", ["SH", "SZ"])),
            "internal_subscribe_id": self.whole_quote_sub_id,
            "publish_existing": True,
        }
        self.whole_quote_publish_enabled = True
        self._send_response(msg, {
            "subscribe_id": sub_id,
            "internal_subscribe_id": self.whole_quote_sub_id,
            "publish_existing": True,
        })
        self._log(
            "normal bridge whole quote publish enabled id=%s internal_id=%s"
            % (sub_id, self.whole_quote_sub_id)
        )

    def _handle_quote_unsubscribe(self, msg):
        params = msg.get("params") or {}
        sub_id = params.get("subscribe_id")
        removed = self.quote_subscriptions.pop(sub_id, None)
        if removed is None:
            try:
                removed = self.quote_subscriptions.pop(int(sub_id), None)
            except Exception:
                removed = None
        if str(sub_id) == str(self.whole_quote_publish_sub_id):
            self.whole_quote_publish_enabled = False
        self._send_response(msg, True)
        self._log("normal bridge quote unsubscribed id=%s" % sub_id)

    def pump(self):
        self._release_worker("pump")
        return self.request_queue.qsize()

    def _release_worker(self, source):
        with self.worker_source_lock:
            self.worker_source = source
        self.worker_event.set()

    def _worker_loop(self, context=None):
        if context is not None:
            self.context = context
        while self.running:
            self.worker_event.wait(0.5)
            if not self.running:
                break
            if not self.worker_event.is_set():
                continue
            self.worker_event.clear()
            with self.worker_source_lock:
                source = self.worker_source or "unknown"
            try:
                self._drain_requests(source)
            except Exception as e:
                self._log("normal bridge worker error source=%s error=%s" % (source, e))

    def _drain_requests(self, source):
        start = time.perf_counter()
        count = 0
        while self.running and count < self.pump_max_count:
            if (time.perf_counter() - start) * 1000 >= self.pump_max_ms:
                break
            try:
                msg, received_at = self.request_queue.get_nowait()
            except queue.Empty:
                break
            try:
                result = self._dispatch(msg.get("action"), msg.get("params") or {}, msg)
                self._send_response(msg, result)
                self._log(
                    "normal bridge worker response source=%s action=%s id=%s total_ms=%.2f"
                    % (source, msg.get("action"), msg.get("id"), (time.time() - received_at) * 1000)
                )
            except Exception as e:
                self._log(
                    "normal bridge worker request_error source=%s action=%s id=%s error=%s"
                    % (source, msg.get("action"), msg.get("id"), e)
                )
                self._send_error(msg, e)
            count += 1
        return count

    def _on_whole_quote(self, data):
        self._release_worker("whole_quote")
        if not self.quote_subscriptions:
            return
        for sub_id, sub in list(self.quote_subscriptions.items()):
            if sub.get("kind") == "whole_quote" and not self.whole_quote_publish_enabled:
                continue
            client_id = sub.get("client_id")
            if not client_id:
                continue
            event_data = data
            if sub.get("kind") == "quote":
                stock_code = sub.get("stock_code")
                if stock_code and isinstance(data, dict):
                    value = data.get(stock_code)
                    if value is None:
                        continue
                    event_data = {stock_code: value}
            event = pack_event(
                "quote:%s" % sub_id,
                data=event_data,
                client_id=client_id,
                subscription_id=sub_id,
            )
            self.tx.push("event", event, client_id)

    def _on_timer(self, *args, **kwargs):
        self._release_worker("timer")

    def _subscribe_internal_whole_quote(self):
        if self.context is None or self.whole_quote_sub_id:
            return
        try:
            self.whole_quote_sub_id = self.context.subscribe_whole_quote(["SH", "SZ"], callback=self._on_whole_quote)
            self._log("normal bridge internal whole quote subscribed id=%s" % self.whole_quote_sub_id)
        except Exception as e:
            self._log("normal bridge internal whole quote subscribe failed: %s" % e)

    def _schedule_timer(self):
        if self.context is None or self.schedule_key:
            return
        try:
            first_time = dt.datetime.now() + dt.timedelta(seconds=1)
            self.schedule_key = self.context.schedule_run(
                self._on_timer,
                first_time,
                repeat_times=-1,
                interval=dt.timedelta(milliseconds=500),
                name="cfquant_normal_bridge_pump",
            )
            self._log("normal bridge timer scheduled key=%s" % self.schedule_key)
        except Exception as e:
            self._log("normal bridge timer schedule failed: %s" % e)

    def _send_response(self, msg, result):
        client_id = msg.get("client_id") or msg.get("reply_channel")
        if not client_id:
            return
        response = pack_response(msg.get("id"), ok=True, result=result)
        self.tx.push("response", response, client_id)

    def _send_error(self, msg, error):
        client_id = msg.get("client_id") or msg.get("reply_channel")
        if not client_id:
            return
        self._log(
            "normal bridge send_error action=%s id=%s client_id=%s error=%s"
            % (msg.get("action"), msg.get("id"), client_id, error)
        )
        response = pack_response(msg.get("id"), ok=False, error=error)
        self.tx.push("response", response, client_id)

    def publish_callback_event(self, event_name, obj):
        if self.tx is None:
            return
        data = self._callback_object_to_dict(obj)
        account_id = self._callback_account_id(obj, data)
        payload = {
            "type": "event",
            "event": event_name,
            "account_id": account_id,
            "bridge_id": self.bridge_id,
            "source": "CFQUANT",
            "ts": int(time.time() * 1000),
            "data": data,
        }
        self.tx.push("event", json.dumps(payload, ensure_ascii=False), self.callback_event_channel)
        if account_id:
            self._send_trader_event_to_account(account_id, event_name.replace("trader:", "", 1), data)
        self._log("normal bridge callback event sent event=%s account=%s" % (event_name, account_id or "-"))

    def _callback_object_to_dict(self, obj):
        fields = [
            "account_id",
            "m_strAccountID",
            "m_strAccountId",
            "m_strAccount",
            "m_accountID",
            "m_strStatus",
            "m_strInstrumentID",
            "m_strExchangeID",
            "m_strInstrumentName",
            "m_nOffsetFlag",
            "m_nVolumeTotalOriginal",
            "m_nVolumeTraded",
            "m_nVolume",
            "m_nCanUseVolume",
            "m_dPrice",
            "m_dTradedPrice",
            "m_dTradeAmount",
            "m_dBalance",
            "m_dAssureAsset",
            "m_dInstrumentValue",
            "m_dTotalDebit",
            "m_dAvailable",
            "m_dPositionProfit",
            "m_dOpenPrice",
            "m_dPositionCost",
            "m_strRemark",
            "m_strOrderSysID",
            "m_strOrderID",
            "m_nOrderID",
            "m_nOrderStatus",
            "m_strOrderStatus",
            "m_nOrderState",
            "m_strStatusMsg",
        ]
        data = {}
        for field in fields:
            value = self._get_value(obj, field)
            if value is not None:
                data[field] = value
        code = data.get("m_strInstrumentID")
        market = data.get("m_strExchangeID")
        if code and market:
            data["stock_code"] = "%s.%s" % (code, market)
        return data

    def _callback_account_id(self, obj, data):
        for key in ("account_id", "m_strAccountID", "m_strAccountId", "m_strAccount", "m_accountID"):
            value = data.get(key)
            if value:
                return str(value).strip()
        for name in ("account_id", "m_strAccountID", "m_strAccountId", "m_strAccount", "m_accountID"):
            value = self._get_value(obj, name)
            if value:
                return str(value).strip()
        return str(self.account_id or "").strip()

    def _status_extra(self):
        return {
            "request_queue_size": self.request_queue.qsize(),
            "recv_thread_alive": self.recv_thread.is_alive() if self.recv_thread else False,
            "worker_thread_alive": self.worker_thread.is_alive() if self.worker_thread else False,
            "whole_quote_sub_id": self.whole_quote_sub_id,
            "schedule_key": self.schedule_key,
            "quote_subscription_count": len(self.quote_subscriptions),
            "whole_quote_publish_enabled": self.whole_quote_publish_enabled,
            "whole_quote_publish_sub_id": self.whole_quote_publish_sub_id,
            "pump_max_count": self.pump_max_count,
            "pump_max_ms": self.pump_max_ms,
        }


def start_normal_bridge(
    context,
    ip="127.0.0.1",
    port=2049,
    token="LTtx",
    request_channel="cfquant.request",
    callback_event_channel="cfquant.callback.event",
    bridge_id="default",
    account_id="",
    show=True,
):
    import sys

    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return NormalQmtBridge(
        context,
        ip=ip,
        port=port,
        token=token,
        request_channel=request_channel,
        callback_event_channel=callback_event_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
    ).start()
