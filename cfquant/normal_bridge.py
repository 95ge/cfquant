# -*- coding: utf-8 -*-
import datetime as dt
import json
import queue
import threading
import time

from . import order_meta
from .protocol import loads_message, pack_event, pack_response
from .tx_trade_bridge import TxTradeBridge


COALESCED_QUERY_ACTIONS = set([
    "xttrader.query_stock_asset",
    "xttrader.query_stock_positions",
    "xttrader.query_stock_orders",
    "xttrader.query_stock_trades",
    "xttrader.query_credit_detail",
    "xttrader.query_credit_subjects",
    "xttrader.query_credit_slo_code",
    "xttrader.query_credit_assure",
    "xttrader.query_stk_compacts",
])


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
        schedule_timer=True,
        pump_max_count=20,
        pump_max_ms=0,
        dispatch_on_qmt_thread=False,
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
        self.dispatch_on_qmt_thread = bool(dispatch_on_qmt_thread)
        self.dispatch_lock = threading.RLock()
        self.coalesce_lock = threading.RLock()
        self.coalesced_requests = {}
        self.coalesce_join_count = 0
        self.coalesce_dispatch_count = 0
        self.subscription_seq = 0
        self.quote_subscriptions = {}
        self.whole_quote_publish_sub_id = None
        self.whole_quote_publish_enabled = False
        self.whole_quote_sub_id = None
        self.schedule_key = None
        self.callback_event_channel = callback_event_channel
        self.bridge_id = bridge_id or "default"
        self.schedule_timer = bool(schedule_timer)
        self.order_meta_txs = {}
        self.order_meta_threads = {}
        self.order_meta_accounts = set()
        self.order_meta_subscription_lock = threading.RLock()
        self.order_meta_reset_slots = set()
        self.order_meta_store_load_times = {}

    def start(self):
        if self.running:
            return self
        self.running = True
        if not self.started_at:
            self.started_at = time.time()
        txl = self._load_txl()
        self.tx = txl(self.ip, self.port, self.token)
        self.tx.start_tx()
        self.tx.start_txg(self.request_channel)
        self.recv_thread = threading.Thread(target=self._recv_loop)
        self.recv_thread.daemon = True
        self.recv_thread.start()
        if self.account_id:
            self._ensure_order_meta_account_subscription(self.account_id, self.account_type)
        with self.order_meta_subscription_lock:
            initial_order_meta_accounts = list(self.order_meta_accounts)
        for account_type, account_id in initial_order_meta_accounts:
            self._ensure_order_meta_account_subscription(account_id, account_type)
        self._log(
            "normal bridge started LTtx=%s:%s request_channel=%s"
            % (self.ip, self.port, self.request_channel)
        )
        self._publish_runtime_report("start")
        return self

    def set_context(self, context):
        self.context = context
        if self.account_id:
            self._set_context_account(self.account_id, self.account_type)
        self._enable_auto_trade_callback()
        if self.account_id:
            self._ensure_order_meta_account_subscription(self.account_id, self.account_type)
        self._subscribe_internal_whole_quote()
        if self.dispatch_on_qmt_thread:
            self._log("normal bridge QMT-thread dispatch enabled")
        else:
            self._start_worker_thread(context)
        if self.schedule_timer:
            self._schedule_timer()
        if self.dispatch_on_qmt_thread:
            dispatch_source = "QMT timer/handlebar callbacks" if self.schedule_timer else "QMT caller thread callbacks"
            self._log("normal bridge requests are consumed by %s" % dispatch_source)
        else:
            self._log("normal bridge worker is released by quote/timer/handlebar callbacks")
        self._log("normal bridge context ready")
        self._publish_runtime_report("context_ready")

    def close(self):
        self.running = False
        self.worker_event.set()
        with self.order_meta_subscription_lock:
            meta_txs = list(self.order_meta_txs.values())
            self.order_meta_txs.clear()
            self.order_meta_threads.clear()
        if self.context is not None and self.schedule_key:
            try:
                self.context.cancel_schedule_run(self.schedule_key)
            except Exception:
                pass
        for meta_tx in meta_txs:
            try:
                meta_tx.close()
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
        if action == "cfquant.status":
            self._send_response(msg, self._status())
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
        if self._try_enqueue_coalesced_request(msg):
            return
        try:
            self.request_queue.put_nowait((msg, time.time(), None))
            self._release_worker("enqueue")
            self._log(
                "normal bridge request queued action=%s id=%s queue_size=%s"
                % (msg.get("action"), msg.get("id"), self.request_queue.qsize())
            )
        except queue.Full as e:
            self._send_error(msg, e)

    def _subscribe_account(self, params, msg=None):
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type")).upper()
        result = super(NormalQmtBridge, self)._subscribe_account(params, msg)
        self._ensure_order_meta_account_subscription(account_id or self.account_id, account_type or self.account_type)
        return result

    def _ensure_order_meta_account_subscription(self, account_id, account_type=None):
        account_id = str(account_id or "").strip()
        if not account_id:
            return False
        account_type = order_meta.normalize_account_type(account_type or self.account_type)
        account_key = (account_type, account_id)
        channel = order_meta.account_meta_channel(self.bridge_id, account_type, account_id)
        with self.order_meta_subscription_lock:
            self.order_meta_accounts.add(account_key)
            if self.tx is None or not self.running:
                return False
            if channel in self.order_meta_txs:
                return True
            txl = self._load_txl()
            try:
                meta_tx = txl(self.ip, self.port, self.token, show=False)
            except TypeError:
                meta_tx = txl(self.ip, self.port, self.token)
            try:
                meta_tx.start_txg(channel)
            except Exception:
                try:
                    meta_tx.close()
                except Exception:
                    pass
                raise
            thread = threading.Thread(target=self._order_meta_recv_loop, args=(channel, meta_tx))
            thread.daemon = True
            self.order_meta_txs[channel] = meta_tx
            self.order_meta_threads[channel] = thread
            thread.start()
        self._load_order_meta_store_throttled(account_id, account_type, force=True)
        self._log("normal bridge order meta subscribed account=%s type=%s channel=%s" % (account_id, account_type, channel))
        return True

    def _order_meta_recv_loop(self, channel, meta_tx):
        while self.running:
            try:
                raw = meta_tx.Q.get()
                if raw is None:
                    break
                self._handle_order_meta_raw(raw, channel)
            except Exception as e:
                if self.running:
                    self._log("normal bridge order meta recv error channel=%s error=%s" % (channel, e))
                time.sleep(0.05)

    def _handle_order_meta_raw(self, raw, channel=""):
        key, payload = order_meta.split_push_message(raw)
        if not key:
            return False
        record = order_meta.decode_record_payload(payload)
        if not isinstance(record, dict):
            return False
        record = order_meta.normalize_record(record, bridge_id=self.bridge_id)
        status = order_meta.normalize_text(record.get("status")).lower()
        if key == order_meta.ORDER_META_DELETE_KEY or status in ("delete", "deleted", "failed", "cancelled"):
            self.order_meta_cache.remove(record)
        else:
            self.order_meta_cache.upsert(record)
        self._persist_order_meta_record(record, payload=order_meta.encode_record(record))
        return True

    def _load_order_meta_store_throttled(self, account_id, account_type, force=False):
        account_id = str(account_id or "").strip()
        account_type = order_meta.normalize_account_type(account_type or self.account_type)
        if not account_id:
            return {"loaded": 0, "stale": 0}
        key = (account_type, account_id)
        now = time.time()
        with self.order_meta_subscription_lock:
            last_load = self.order_meta_store_load_times.get(key, 0.0)
            if not force and now - last_load < 1.0:
                return {"loaded": 0, "stale": 0}
            self.order_meta_store_load_times[key] = now
        return self._load_order_meta_store(account_id, account_type)

    def _enrich_callback_order_meta(self, event_name, data, account_id, account_type):
        if event_name not in ("trader:on_stock_order", "trader:on_stock_trade"):
            return None
        if not isinstance(data, dict):
            return None
        account_id = str(account_id or "").strip()
        account_type = order_meta.normalize_account_type(account_type or self.account_type)
        if account_id:
            data.setdefault("account_id", account_id)
            data.setdefault("m_strAccountID", account_id)
            self._ensure_order_meta_account_subscription(account_id, account_type)
        if account_type:
            data.setdefault("account_type", account_type)
        record, match_info = self.order_meta_cache.resolve_callback(
            data,
            bridge_id=self.bridge_id,
            account_type=account_type,
            account_id=account_id,
            allow_pending=True,
        )
        if record is None and account_id:
            self._load_order_meta_store_throttled(account_id, account_type)
            record, match_info = self.order_meta_cache.resolve_callback(
                data,
                bridge_id=self.bridge_id,
                account_type=account_type,
                account_id=account_id,
                allow_pending=True,
            )
        order_meta.apply_record_to_callback(data, record, match_info)
        order_meta.ensure_callback_text_fields(data)
        if record and match_info.get("bound_order_ref"):
            self._persist_order_meta_record(record, payload=order_meta.encode_record(record))
        return record

    def _maybe_reset_order_meta_stores(self):
        now = dt.datetime.now()
        slot = ""
        if now.hour == 9 and now.minute == 0:
            slot = "0900"
        elif now.hour >= 16:
            slot = "after_1600"
        if not slot:
            return
        trade_day = now.strftime("%Y%m%d")
        with self.order_meta_subscription_lock:
            self.order_meta_reset_slots = set(
                item for item in self.order_meta_reset_slots
                if item and item[0] == trade_day
            )
            accounts = list(self.order_meta_accounts)
            markers = []
            for account_type, account_id in accounts:
                marker = (trade_day, slot, account_type, account_id)
                if marker in self.order_meta_reset_slots:
                    continue
                self.order_meta_reset_slots.add(marker)
                markers.append((account_type, account_id, marker))
        for account_type, account_id, marker in markers:
            self._reset_order_meta_store(account_id, account_type, reason=marker[1])

    def _publish_runtime_report(self, reason):
        super(NormalQmtBridge, self)._publish_runtime_report(reason)
        if self.tx is None or not self.callback_event_channel:
            return
        try:
            data = self._runtime_info()
            data.update({
                "reason": reason,
                "transport": "lttx" if self.port else "pipe",
                "channel_key": "normal",
                "callback_event_channel": self.callback_event_channel,
            })
            payload = pack_event(
                "cfquant.runtime",
                data=data,
                client_id=self.callback_event_channel,
                meta={
                    "bridge_id": self.bridge_id,
                    "account_id": self.account_id,
                    "source": "qmt_runtime_report",
                },
            )
            self.tx.push("event", payload, self.callback_event_channel)
            self._log("normal bridge runtime report sent version=%s reason=%s" % (data.get("core_version") or "-", reason))
        except Exception as e:
            self._log("normal bridge runtime report failed:%s" % e)

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

    def _try_enqueue_coalesced_request(self, msg):
        coalesce_key = self._coalesce_key(msg)
        if not coalesce_key:
            return False
        received_at = time.time()
        action = msg.get("action")
        with self.coalesce_lock:
            current = self.coalesced_requests.get(coalesce_key)
            if current is not None:
                current["waiters"].append((msg, received_at))
                self.coalesce_join_count += 1
                self._log(
                    "normal bridge request coalesced action=%s id=%s waiters=%s"
                    % (action, msg.get("id"), len(current["waiters"]))
                )
                return True
            entry = {
                "key": coalesce_key,
                "action": action,
                "primary_id": msg.get("id"),
                "waiters": [(msg, received_at)],
            }
            self.coalesced_requests[coalesce_key] = entry
        try:
            self.request_queue.put_nowait((msg, received_at, coalesce_key))
            self._release_worker("enqueue")
            self._log(
                "normal bridge request queued action=%s id=%s queue_size=%s coalesced=1"
                % (action, msg.get("id"), self.request_queue.qsize())
            )
            return True
        except queue.Full as e:
            with self.coalesce_lock:
                if self.coalesced_requests.get(coalesce_key) is entry:
                    self.coalesced_requests.pop(coalesce_key, None)
            self._send_error(msg, e)
            return True

    def _coalesce_key(self, msg):
        action = msg.get("action")
        if action not in COALESCED_QUERY_ACTIONS:
            return None
        params = msg.get("params") or {}
        try:
            params_key = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            params_key = repr(params)
        return "%s|%s" % (action, params_key)

    def pump(self):
        if self.dispatch_on_qmt_thread:
            return self._drain_requests("pump")
        self._release_worker("pump")
        return self.request_queue.qsize()

    def on_timer(self, *args, **kwargs):
        self._maybe_reset_order_meta_stores()
        if self.dispatch_on_qmt_thread:
            self._drain_requests("timer")
            return
        self._release_worker("timer")

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
        with self.dispatch_lock:
            start = time.perf_counter()
            count = 0
            while self.running and count < self.pump_max_count:
                if self.pump_max_ms > 0 and (time.perf_counter() - start) * 1000 >= self.pump_max_ms:
                    break
                try:
                    item = self.request_queue.get_nowait()
                except queue.Empty:
                    break
                msg, received_at, coalesce_key = self._queue_item_parts(item)
                if coalesce_key:
                    self._drain_coalesced_request(source, msg, received_at, coalesce_key)
                else:
                    self._drain_single_request(source, msg, received_at)
                count += 1
            return count

    def _queue_item_parts(self, item):
        try:
            if len(item) == 3:
                return item
        except Exception:
            pass
        msg, received_at = item
        return msg, received_at, None

    def _drain_single_request(self, source, msg, received_at):
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

    def _drain_coalesced_request(self, source, msg, received_at, coalesce_key):
        try:
            result = self._dispatch(msg.get("action"), msg.get("params") or {}, msg)
            with self.coalesce_lock:
                entry = self.coalesced_requests.pop(coalesce_key, None)
                self.coalesce_dispatch_count += 1
            waiters = entry.get("waiters", []) if entry else [(msg, received_at)]
            for waiter_msg, _ in waiters:
                self._send_response(waiter_msg, result)
            self._log(
                "normal bridge worker coalesced_response source=%s action=%s id=%s waiters=%s total_ms=%.2f"
                % (source, msg.get("action"), msg.get("id"), len(waiters), (time.time() - received_at) * 1000)
            )
        except Exception as e:
            with self.coalesce_lock:
                entry = self.coalesced_requests.pop(coalesce_key, None)
                self.coalesce_dispatch_count += 1
            waiters = entry.get("waiters", []) if entry else [(msg, received_at)]
            self._log(
                "normal bridge worker coalesced_error source=%s action=%s id=%s waiters=%s error=%s"
                % (source, msg.get("action"), msg.get("id"), len(waiters), e)
            )
            for waiter_msg, _ in waiters:
                self._send_error(waiter_msg, e)

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
        self.on_timer(*args, **kwargs)

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
        if event_name == "trader:on_stock_order":
            data = self._format_trade_detail(obj, "order")
        elif event_name == "trader:on_stock_trade":
            data = self._format_trade_detail(obj, "deal")
        else:
            data = self._callback_object_to_dict(obj)
        account_id = self._callback_account_id(obj, data)
        account_type = self._callback_account_type(obj, data)
        if not account_type and self.account_type:
            account_type = order_meta.normalize_account_type(self.account_type)
        if account_id:
            data.setdefault("account_id", account_id)
        if account_type:
            data.setdefault("account_type", account_type)
        if event_name == "trader:on_stock_order":
            self._enrich_order_request_fields(data)
        self._enrich_callback_order_meta(event_name, data, account_id, account_type)
        if event_name == "trader:on_stock_order":
            self._handle_async_order_callback(data)
        payload = {
            "type": "event",
            "event": event_name,
            "account_id": account_id,
            "account_type": account_type,
            "bridge_id": self.bridge_id,
            "source": "CFQUANT",
            "ts": int(time.time() * 1000),
            "data": data,
        }
        self.tx.push("event", json.dumps(payload, ensure_ascii=False), self.callback_event_channel)
        if account_id:
            self._send_trader_event_to_account(account_id, event_name.replace("trader:", "", 1), data, account_type=account_type or None)
        self._log("normal bridge callback event sent event=%s account=%s" % (event_name, account_id or "-"))

    def _callback_object_to_dict(self, obj):
        fields = [
            "account_id",
            "account_type",
            "m_strAccountID",
            "m_strAccountId",
            "m_strAccount",
            "m_accountID",
            "m_nAccountType",
            "m_strAccountType",
            "order_source",
            "source",
            "order_remark",
            "strategy_name",
            "m_strStatus",
            "m_strInstrumentID",
            "m_strExchangeID",
            "m_strInstrumentName",
            "m_nOrderType",
            "m_nBusinessType",
            "m_nDirection",
            "m_nOffsetFlag",
            "m_nVolumeTotalOriginal",
            "m_nVolumeTraded",
            "m_nVolume",
            "m_nCanUseVolume",
            "m_nFrozenVolume",
            "m_nOnRoadVolume",
            "m_nYesterdayVolume",
            "m_nPriceType",
            "m_nOrderPriceType",
            "m_dLimitPrice",
            "m_dOrderPrice",
            "m_dPrice",
            "m_dTradedPrice",
            "m_dTradeAmount",
            "m_dCommission",
            "m_dBalance",
            "m_dAssureAsset",
            "m_dInstrumentValue",
            "m_dTotalDebit",
            "m_dAvailable",
            "m_dPositionProfit",
            "m_dLastPrice",
            "m_dProfitRate",
            "m_dOpenPrice",
            "m_dPositionCost",
            "m_strRemark",
            "m_strOrderRemark",
            "m_strStrategyName",
            "m_strOrderSysID",
            "m_strOrderID",
            "m_nOrderID",
            "m_strOrderRef",
            "m_nRef",
            "m_nOrderStatus",
            "m_strOrderStatus",
            "m_nOrderState",
            "m_strStatusMsg",
            "m_strOrderTime",
            "m_strEntrustTime",
            "m_strInsertTime",
            "m_nOrderTime",
            "m_nEntrustTime",
            "m_nInsertTime",
            "m_strOrderDate",
            "m_strEntrustDate",
            "m_strTradingDay",
        ]
        data = {}
        for field in fields:
            value = self._get_value(obj, field)
            if value is not None:
                data[field] = value
        code = data.get("m_strInstrumentID")
        market = data.get("m_strExchangeID")
        if code and market:
            data["stock_code"] = "%s.%s" % (code, self._market_suffix(market))
        source_text = " ".join(str(item or "") for item in (
            data.get("order_source"),
            data.get("source"),
            data.get("order_remark"),
            data.get("strategy_name"),
            data.get("m_strRemark"),
            data.get("m_strOrderRemark"),
            data.get("m_strStrategyName"),
        )).strip().lower()
        data["order_source"] = "cfquant" if "cfquant" in source_text else "other"
        return data

    def _market_suffix(self, value):
        text = str(value or "").strip().upper()
        aliases = {
            "0": "SH",
            "SH": "SH",
            "SSE": "SH",
            "SHSE": "SH",
            "1": "SZ",
            "SZ": "SZ",
            "SZSE": "SZ",
            "70": "BJ",
            "BJ": "BJ",
            "BSE": "BJ",
            "3": "SF",
            "SF": "SF",
            "SHFE": "SF",
            "SHF": "SF",
            "4": "DF",
            "DF": "DF",
            "DCE": "DF",
            "DLCE": "DF",
            "5": "ZF",
            "ZF": "ZF",
            "CZCE": "ZF",
            "ZCE": "ZF",
            "2": "IF",
            "IF": "IF",
            "CFFEX": "IF",
            "CFX": "IF",
            "6": "INE",
            "INE": "INE",
            "75": "GF",
            "GF": "GF",
            "GFEX": "GF",
            "7": "SHO",
            "SHO": "SHO",
            "SSEOPTION": "SHO",
            "SSE_OPTION": "SHO",
            "67": "SZO",
            "SZO": "SZO",
            "SZSEOPTION": "SZO",
            "SZSE_OPTION": "SZO",
        }
        return aliases.get(text, text)

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

    def _callback_account_type(self, obj, data):
        candidates = [
            data.get("account_type") if isinstance(data, dict) else None,
            data.get("m_nAccountType") if isinstance(data, dict) else None,
            data.get("m_strAccountType") if isinstance(data, dict) else None,
            self._get_value(obj, "account_type"),
            self._get_value(obj, "m_nAccountType"),
            self._get_value(obj, "m_strAccountType"),
        ]
        for value in candidates:
            if value in (None, ""):
                continue
            text = str(value).strip().upper()
            if text in ("2", "SECURITY", "SECURITY_ACCOUNT", "STOCK_ACCOUNT"):
                return "STOCK"
            if text in ("3", "CREDIT_ACCOUNT", "MARGIN"):
                return "CREDIT"
            if text in ("1", "FUTURE_ACCOUNT"):
                return "FUTURE"
            if text in ("5", "FUTURE_OPTION_ACCOUNT"):
                return "FUTURE_OPTION"
            if text in ("6", "STOCK_OPTION_ACCOUNT", "OPTION"):
                return "STOCK_OPTION"
            return text
        return ""

    def _status_extra(self):
        with self.coalesce_lock:
            coalesced_waiters = sum(len(item.get("waiters", [])) for item in self.coalesced_requests.values())
            coalesced_group_count = len(self.coalesced_requests)
        return {
            "request_queue_size": self.request_queue.qsize(),
            "recv_thread_alive": self.recv_thread.is_alive() if self.recv_thread else False,
            "worker_thread_alive": self.worker_thread.is_alive() if self.worker_thread else False,
            "whole_quote_sub_id": self.whole_quote_sub_id,
            "schedule_key": self.schedule_key,
            "quote_subscription_count": len(self.quote_subscriptions),
            "whole_quote_publish_enabled": self.whole_quote_publish_enabled,
            "whole_quote_publish_sub_id": self.whole_quote_publish_sub_id,
            "schedule_timer": self.schedule_timer,
            "pump_max_count": self.pump_max_count,
            "pump_max_ms": self.pump_max_ms,
            "dispatch_on_qmt_thread": self.dispatch_on_qmt_thread,
            "dispatch_thread": (
                "qmt_timer_or_handlebar"
                if self.dispatch_on_qmt_thread and self.schedule_timer
                else "qmt_caller_thread"
                if self.dispatch_on_qmt_thread
                else "worker"
            ),
            "coalesced_group_count": coalesced_group_count,
            "coalesced_waiter_count": coalesced_waiters,
            "coalesce_join_count": self.coalesce_join_count,
            "coalesce_dispatch_count": self.coalesce_dispatch_count,
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
    schedule_timer=True,
    pump_max_count=20,
    pump_max_ms=0,
    dispatch_on_qmt_thread=False,
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
        schedule_timer=schedule_timer,
        pump_max_count=pump_max_count,
        pump_max_ms=pump_max_ms,
        dispatch_on_qmt_thread=dispatch_on_qmt_thread,
    ).start()
