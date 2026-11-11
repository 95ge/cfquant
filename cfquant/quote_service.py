"""Process-wide quote service used by Web, SDK routes and execution tasks."""
import threading
import time
import uuid

from .shared_quotes import SharedQuoteFeed, _QuoteListener, quote_scope, quote_matches


class ProjectQuoteService:
    def __init__(self, subscribe, unsubscribe, probe, add_callback, remove_callback,
                 initial_scope=("SH", "SZ", "BJ"), idle_seconds=5, monitor_seconds=3):
        self._subscribe_rpc = subscribe
        self._unsubscribe_rpc = unsubscribe
        self._probe_rpc = probe
        self._add_callback = add_callback
        self._remove_callback = remove_callback
        self._lock = threading.RLock()
        self._acquire_lock = threading.RLock()
        self._callbacks = {}
        self._diagnostics = {}
        self._source = {}
        self._route = None
        self._pending = None
        self._health_error = ""
        self._started = False
        self._stop = threading.Event()
        self._thread = None
        self._monitor_seconds = monitor_seconds
        self.feed = SharedQuoteFeed(self._subscribe, self._unsubscribe,
                                    initial_scope=initial_scope, idle_seconds=idle_seconds)

    def start(self):
        with self._lock:
            if self._started:
                return
            self._add_callback("quote", self._on_quote)
            self._started = True
            if self._monitor_seconds:
                self._thread = threading.Thread(target=self._monitor, name="cfquant-quote-health", daemon=True)
                self._thread.start()

    def acquire(self, key, codes, callback=None, purpose="user", source=None, diagnostic=False,
                reuse_source=False):
        codes = quote_scope(codes)
        source = {key: value for key, value in (source or {}).items()
                  if key in ("bridge_id", "channel", "account_id", "account_type", "account_key") and value}
        with self._acquire_lock:
            self.start()
            with self._lock:
                active = self.feed.status()["consumers"] or self._route or self._pending
                if active:
                    # Web viewers may follow the existing source. Decide under
                    # the same lock as acquisition, including unconfirmed RPCs;
                    # a status check by the caller can race another subscriber.
                    chosen = dict(self._source, **((self._pending or {}).get("source") or {}))
                    chosen.update(self._route or {})
                    if not reuse_source:
                        for name, value in source.items():
                            if chosen.get(name) and str(chosen[name]) != str(value):
                                raise ValueError("shared quotes already use another %s; release existing consumers first" % name)
                else:
                    self._source = source
            if diagnostic:
                with self._lock:
                    if key not in self._diagnostics:
                        deliver = (lambda batch: callback(batch["batch"])) if callback else None
                        self._diagnostics[key] = dict(codes=codes, listener=_QuoteListener(deliver, True), lease_id=None)
            try:
                lease = self.feed.acquire(key, codes, None if diagnostic else callback, purpose)
            except BaseException:
                with self._lock:
                    row = self._diagnostics.pop(key, None)
                if row:
                    row["listener"].close()
                raise
            if diagnostic:
                with self._lock:
                    self._diagnostics[key]["lease_id"] = lease
            return lease

    def release(self, lease_id):
        result = self.feed.release(int(lease_id))
        with self._lock:
            keys = [key for key, row in self._diagnostics.items() if row["lease_id"] == int(lease_id)]
            for key in keys:
                self._diagnostics.pop(key)["listener"].close()
        return result

    def snapshot(self, code, max_age=None):
        return self.feed.snapshot(code, max_age)

    def status(self):
        result = self.feed.status()
        with self._lock:
            route = dict(self._route or {})
            result["health_error"] = self._health_error
        route.pop("result", None)
        route.pop("shared_lease_key", None)
        result["source"] = route
        return result

    def _subscribe(self, codes, callback, generation):
        with self._lock:
            # Preserve an uncertain request identity across retries. The bridge
            # recognizes it even if the preceding RPC acknowledgement was lost.
            pending = self._pending
            if pending is None:
                token = "shared-quote-" + uuid.uuid4().hex
                pending = dict(params=dict(code_list=codes, callback_event="quote:" + token,
                                           shared_lease_key=token, lease_timeout=45), source=dict(self._source))
                self._pending = pending
            elif pending["params"]["code_list"] != codes:
                raise RuntimeError("an earlier quote subscription is unconfirmed; reconcile it before changing scope")
            event = pending["params"]["callback_event"]
            self._callbacks[event] = callback
        route = self._subscribe_rpc(pending["params"], pending["source"])
        result = route.get("result")
        native_id = result.get("subscribe_id") if isinstance(result, dict) else result
        if native_id is None or isinstance(native_id, bool) or int(native_id) <= 0:
            raise RuntimeError("invalid shared upstream subscription ID")
        handle = dict(route, subscribe_id=native_id, callback_event=event,
                      shared_lease_key=pending["params"]["shared_lease_key"])
        with self._lock:
            self._route = handle
            self._source = {name: value for name, value in pending["source"].items()}
            self._pending = None
        return handle

    def _unsubscribe(self, handle):
        result = self._unsubscribe_rpc(handle)
        if result is False or (isinstance(result, (int, float)) and result < 0):
            raise RuntimeError("shared quote unsubscribe failed")
        with self._lock:
            self._callbacks.pop(handle["callback_event"], None)
            if self._route is handle:
                self._route = None
        return result

    def _on_quote(self, event, received_at_ms=None):
        received_at_ms = time.time() * 1000 if received_at_ms is None else received_at_ms
        if not isinstance(event, dict):
            return
        with self._lock:
            callback = self._callbacks.get(event.get("event"))
        if callback:
            payload = event.get("data")
            if isinstance(payload, dict) and payload.get("schema") == "cfquant.quote_latency.v1":
                quotes = payload.get("quotes") or {}
                callback(quotes)
                with self._lock:
                    diagnostics = list(self._diagnostics.values())
                for row in diagnostics:
                    selected = {code: quote for code, quote in quotes.items() if quote_matches(code, row["codes"])}
                    if selected:
                        envelope = dict(payload, quotes=selected,
                                        shared_received_at_ms=received_at_ms if received_at_ms is not None else time.time() * 1000)
                        # One complete diagnostic batch per callback, with its
                        # original QMT timestamps; never merge different batches.
                        row["listener"].push({"batch": envelope})
            else:
                callback(payload)

    def check_connection(self):
        with self._lock:
            handle = self._route
        if handle is None or not self.feed.status()["consumers"]:
            return
        try:
            state = self._probe_rpc(handle)
            if not isinstance(state, dict) or not state.get("ready"):
                raise RuntimeError("quote provider is not ready")
            keys = state.get("lease_keys")
            if not isinstance(keys, list):
                raise RuntimeError("quote provider returned no valid lease list")
        except Exception as error:
            # A late acknowledgement does not prove that QMT lost its lease.
            # Keep receiving callbacks and verify again on the next probe.
            with self._lock:
                self._health_error = str(error)
            return
        with self._lock:
            if self._route is not handle:
                return
            self._health_error = ""
        try:
            exists = handle["shared_lease_key"] in keys
            if not exists or self.feed.status()["state"] != "live":
                self.feed.upstream_lost()
                self.feed.reconnect()
        except Exception as error:
            with self._lock:
                self._health_error = str(error)
            self.feed.upstream_lost()

    def _monitor(self):
        while not self._stop.wait(self._monitor_seconds):
            self.check_connection()

    def close(self):
        self._stop.set()
        self.feed.close()
        with self._lock:
            for row in self._diagnostics.values():
                row["listener"].close()
            self._diagnostics.clear()
            if self._started:
                self._remove_callback("quote", self._on_quote)
                self._started = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=4)
