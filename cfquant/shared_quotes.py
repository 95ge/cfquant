"""One upstream whole-quote subscription, leased by independent consumers.

The upstream adapter owns routing and reconnect detection. No trading API is
called here. A cache is shared by all leases; callbacks receive private copies.
"""

import copy
import logging
import threading
import time


def quote_scope(codes):
    if isinstance(codes, str):
        codes = codes.replace("\uff0c", ",").split(",")
    if not isinstance(codes, (list, tuple, set)):
        raise ValueError("code_list must be a list of markets or securities")
    result = []
    for code in codes:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("market/security codes must be nonempty strings")
        code = code.strip()
        if code not in result:
            result.append(code)
    return result


def quote_matches(code, scope):
    return not scope or code in scope or code.rsplit(".", 1)[-1] in scope


def quote_scope_union(*scopes):
    result = []
    for scope in scopes:
        for code in scope:
            if code not in result and not ("." in code and code.rsplit(".", 1)[-1] in result):
                result.append(code)
    markets = set(code for code in result if "." not in code)
    return [code for code in result if "." not in code or code.rsplit(".", 1)[-1] not in markets]


class _QuoteListener:
    """One bounded pending batch; a slow callback never blocks ingestion."""

    def __init__(self, callback, asynchronous):
        self.callback = callback
        self.asynchronous = asynchronous
        self._condition = threading.Condition()
        self._pending = {}
        self._closed = False
        self._thread = None

    def push(self, data):
        if not self.callback or not data:
            return
        if not self.asynchronous:
            with self._condition:
                if self._closed:
                    return
            self._call(data)
            return
        with self._condition:
            if self._closed:
                return
            self._pending.update(copy.deepcopy(data))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="cfquant-shared-quote", daemon=True)
                self._thread.start()
            self._condition.notify()

    def _call(self, data):
        try:
            self.callback(copy.deepcopy(data))
        except Exception:
            logging.getLogger(__name__).exception("shared quote listener failed")

    def _run(self):
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                data, self._pending = self._pending, {}
            self._call(data)

    def close(self):
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()


class SharedQuoteFeed:
    """Serialize physical subscription changes and reference-count leases.

    subscribe(scope, callback, generation) returns an opaque upstream handle.
    unsubscribe(handle) must raise on failure. Never acquire the lifecycle lock
    in an upstream callback: native APIs may invoke callbacks before returning.
    """

    def __init__(self, subscribe, unsubscribe, initial_scope=(), idle_seconds=5.0,
                 asynchronous=True, clock=None, cache_latest=True):
        self._subscribe = subscribe
        self._unsubscribe = unsubscribe
        self._base_scope = quote_scope(initial_scope)
        self._idle_seconds = max(0.0, float(idle_seconds))
        self._asynchronous = asynchronous
        self._cache_latest = cache_latest
        self._clock = clock or time.monotonic
        self._lifecycle = threading.RLock()
        self._lock = threading.RLock()
        self._leases = {}
        self._keys = {}
        self._seq = 0
        self._generation = 0
        self._quote_sequence = 0
        self._handle = None
        self._scope = []
        self._cache = {}
        self._pending_initial = {}
        self._state = "idle"
        self._error = ""
        self._timer = None
        self._closed = False
        self._last_received = None
        self.changed = threading.Event()

    def acquire(self, key, codes, callback=None, purpose="user"):
        codes = quote_scope(codes)
        if not key or (callback is not None and not callable(callback)):
            raise ValueError("a lease key and callable callback are required")
        with self._lifecycle:
            with self._lock:
                if self._closed:
                    raise RuntimeError("shared quote feed is closed")
                self._cancel_timer()
                if key in self._keys:
                    lease_id = self._keys[key]
                    if self._leases[lease_id]["codes"] != codes:
                        raise ValueError("lease key already used with another scope")
                    existing = True
                else:
                    self._seq += 1
                    lease_id = self._seq
                    self._leases[lease_id] = dict(key=key, codes=codes, purpose=purpose,
                                                 listener=_QuoteListener(callback, self._asynchronous))
                    self._keys[key] = lease_id
                    existing = False
                wanted = quote_scope_union(self._base_scope, self._scope, *[
                    row["codes"] for row in self._leases.values()])
            try:
                if self._handle is None or wanted != self._scope or self._state != "live":
                    self._replace(wanted)
            except BaseException:
                if not existing:
                    with self._lock:
                        row = self._leases.pop(lease_id)
                        self._keys.pop(key, None)
                        row["listener"].close()
                raise
            return lease_id

    def release(self, lease_id):
        with self._lifecycle:
            with self._lock:
                row = self._leases.get(lease_id)
                if row is None:
                    return False
                last = len(self._leases) == 1
            # For synchronous release, preserve the lease if native unsubscribe
            # fails. A caller can retry without losing the resource handle.
            if last and self._idle_seconds == 0:
                self._stop_upstream()
            with self._lock:
                row = self._leases.pop(lease_id)
                self._keys.pop(row["key"], None)
                row["listener"].close()
                if not self._leases and self._idle_seconds:
                    self._cancel_timer()
                    self._timer = threading.Timer(self._idle_seconds, self.release_idle)
                    self._timer.daemon = True
                    self._timer.start()
            return True

    def release_idle(self):
        with self._lifecycle:
            with self._lock:
                self._cancel_timer()
                if self._leases:
                    return False
            try:
                self._stop_upstream()
                return True
            except Exception as error:
                with self._lock:
                    self._error = str(error)
                    if not self._closed:
                        self._timer = threading.Timer(max(1.0, self._idle_seconds), self.release_idle)
                        self._timer.daemon = True
                        self._timer.start()
                return False

    def reconnect(self):
        """Replace once after a verified upstream session loss, for all leases."""
        with self._lifecycle:
            with self._lock:
                if self._closed or not self._leases:
                    return False
                wanted = quote_scope_union(self._base_scope, self._scope, *[
                    row["codes"] for row in self._leases.values()])
            self._replace(wanted)
            return True

    def upstream_lost(self):
        """Invalidate data immediately; retain the handle until cleanup succeeds."""
        with self._lock:
            self._state = "disconnected"
            self._cache.clear()
            self._pending_initial.clear()
            self.changed.set()

    def _replace(self, scope):
        self._stop_upstream()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._state = "subscribing"
            self._error = ""
            self._pending_initial.clear()
        try:
            handle = self._subscribe(list(scope), lambda data: self._receive(data, generation), generation)
            if handle is None or handle is False:
                raise RuntimeError("upstream did not acknowledge quote subscription")
        except BaseException as error:
            with self._lock:
                self._state = "error"
                self._error = str(error)
                self._pending_initial.clear()
                self._cache.clear()
                self.changed.set()
            raise
        with self._lock:
            self._handle = handle
            self._scope = list(scope)
            self._state = "live"
            pending, self._pending_initial = self._pending_initial, {}
        if pending:
            self._receive(pending, generation)

    def _stop_upstream(self):
        with self._lock:
            handle = self._handle
            self._state = "stopping" if handle is not None else "idle"
            self._cache.clear()
            self._pending_initial.clear()
            self.changed.set()
        if handle is not None:
            try:
                result = self._unsubscribe(handle)
                if result is False or (isinstance(result, (int, float)) and result < 0):
                    raise RuntimeError("upstream quote unsubscribe failed")
            except BaseException as error:
                with self._lock:
                    self._state = "error"
                    self._error = str(error)
                raise
        with self._lock:
            self._handle = None
            self._state = "idle"
            self._last_received = None

    def _receive(self, data, generation):
        if not isinstance(data, dict):
            return
        with self._lock:
            if self._closed or generation != self._generation:
                return
            if self._state == "subscribing" and self._cache_latest:
                self._pending_initial.update(copy.deepcopy(data))
                return
            if self._state != "live" and not (self._state == "subscribing" and not self._cache_latest):
                return
            now = self._clock()
            self._last_received = now
            changed = {}
            for code, quote in data.items():
                if not isinstance(code, str) or not isinstance(quote, dict):
                    continue
                previous = self._cache.get(code)
                old = previous["quote"] if previous else {}
                stamp, old_stamp = quote.get("time"), old.get("time")
                try:
                    if stamp is not None and old_stamp is not None and float(stamp) < float(old_stamp):
                        continue
                except (TypeError, ValueError):
                    continue
                merged = dict(old)
                merged.update(copy.deepcopy(quote))
                if self._cache_latest and previous is not None and merged == old:
                    continue
                self._quote_sequence += 1
                if self._cache_latest:
                    self._cache[code] = dict(quote=merged, received_at=time.time(), monotonic_at=now,
                                             generation=generation, sequence=self._quote_sequence)
                changed[code] = merged
            listeners = [(row["listener"], row["codes"]) for row in self._leases.values()]
            if changed:
                self.changed.set()
        for listener, codes in listeners:
            filtered = {code: quote for code, quote in changed.items() if quote_matches(code, codes)}
            listener.push(filtered)

    def snapshot(self, code, max_age=None):
        with self._lock:
            row = self._cache.get(code)
            if self._state != "live" or row is None:
                return None
            if max_age is not None and self._clock() - row["monotonic_at"] > max_age:
                return None
            return copy.deepcopy(row)

    def status(self):
        with self._lock:
            return dict(state=self._state, scope=list(self._scope), generation=self._generation,
                        consumers=len(self._leases), symbols=len(self._cache), error=self._error,
                        last_received_monotonic=self._last_received,
                        leases=[dict(lease_id=key, purpose=row["purpose"], codes=list(row["codes"]))
                                for key, row in self._leases.items()])

    def _cancel_timer(self):
        timer, self._timer = self._timer, None
        if timer:
            timer.cancel()

    def close(self):
        with self._lifecycle:
            with self._lock:
                self._closed = True
                self._cancel_timer()
                for row in self._leases.values():
                    row["listener"].close()
            self._stop_upstream()
            with self._lock:
                self._leases.clear()
                self._keys.clear()
                self._state = "closed"
