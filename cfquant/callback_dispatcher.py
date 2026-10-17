# -*- coding: utf-8 -*-
"""Serial user callbacks, independent of the RPC receive thread."""
from collections import deque
import logging
import os
import tempfile
import threading
import time

from .protocol import decode_value, dumps_message, loads_message


class CallbackDispatcher(object):
    def __init__(self, dispatch, on_error=None):
        self._dispatch = dispatch
        self._on_error = on_error
        self._condition = threading.Condition()
        self._queue = deque()
        self._generation = 0
        self._active = False
        self._thread = None
        self._context = threading.local()
        self._memory_limit = max(0, int(os.environ.get("CFQUANT_CALLBACK_MEMORY_BYTES", 64 * 1024 * 1024)))
        self._memory_bytes = 0
        self._spool = None
        self._spool_size = 0
        self._spool_live = 0
        self._last_wait_ms = self._last_callback_ms = 0.0
        self._last_warning = 0.0

    def start(self):
        with self._condition:
            self._generation += 1
            self._active = True
            self._clear_queue()
            return self._generation

    def stop(self):
        with self._condition:
            self._active = False
            self._generation += 1
            self._clear_queue()
            self._condition.notify_all()
        # Never join: close/stop may be called by a callback itself.

    def submit(self, generation, message, raw=None):
        with self._condition:
            if not self._active or generation != self._generation:
                return
            # Do not block the receive thread on a slow user callback. Trade
            # events cannot be silently dropped or coalesced.
            raw = raw if raw is not None else dumps_message(message)
            size = len(raw) * 8 + 256  # Include the decoded dict/list object overhead.
            self._queue.append([generation, message, time.monotonic(), raw, None, size])
            self._memory_bytes += size
            self._spill_queue()
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="cfquant-event-callback")
                self._thread.daemon = True
                self._thread.start()
            self._condition.notify()

    def _clear_queue(self):
        self._queue.clear()
        self._memory_bytes = self._spool_size = self._spool_live = 0
        if self._spool is not None:
            self._spool.close()
            self._spool = None

    def _spill_queue(self):
        # Allow one full batch in memory: a single large snapshot is not a
        # backlog and must not make every healthy callback perform disk IO.
        if len(self._queue) <= 1:
            return
        for item in self._queue:
            if self._memory_bytes <= self._memory_limit:
                break
            if item[4] is not None:
                continue
            if self._spool is None:
                self._spool = tempfile.TemporaryFile(prefix="cfquant-callbacks-")
            raw = item[3].encode("utf-8") if isinstance(item[3], str) else item[3]
            self._spool.seek(self._spool_size)
            if self._spool.write(raw) != len(raw):
                raise OSError("callback backlog could not be preserved")
            item[4] = (self._spool_size, len(raw))
            self._spool_size += len(raw)
            self._spool_live += len(raw)
            self._memory_bytes -= item[5]
            item[1] = item[3] = None
        if self._queue and len(self._queue) >= 1000 and time.monotonic() - self._last_warning >= 5:
            self._last_warning = time.monotonic()
            logging.getLogger(__name__).warning("callback backlog count=%s oldest_ms=%.1f spooled_bytes=%s",
                                               len(self._queue), (time.monotonic() - self._queue[0][2]) * 1000, self._spool_live)

    def _take_message(self, item):
        if item[4] is None:
            self._memory_bytes -= item[5]
            return item[1], None
        offset, size = item[4]
        self._spool.seek(offset)
        raw = self._spool.read(size)
        if len(raw) != size:
            raise OSError("callback backlog read was incomplete")
        self._spool_live -= size
        if self._spool_live == 0:
            self._spool.close()
            self._spool = None
            self._spool_size = 0
        elif self._spool_size > max(self._memory_limit, 1024 * 1024) + self._spool_live * 2:
            replacement = tempfile.TemporaryFile(prefix="cfquant-callbacks-")
            offsets = []
            try:
                for queued in self._queue:
                    if queued[4] is None:
                        continue
                    previous, length = queued[4]
                    self._spool.seek(previous)
                    value = self._spool.read(length)
                    next_offset = replacement.tell()
                    if len(value) != length or replacement.write(value) != length:
                        raise OSError("callback backlog compaction was incomplete")
                    offsets.append((queued, (next_offset, length)))
            except BaseException:
                replacement.close()
                raise
            self._spool.close()
            self._spool = replacement
            self._spool_size = replacement.tell()
            for queued, location in offsets:
                queued[4] = location
        return None, raw

    def status(self):
        with self._condition:
            return {"queued_callbacks": len(self._queue), "estimated_memory_bytes": self._memory_bytes,
                    "memory_limit_bytes": self._memory_limit, "spooled_bytes": self._spool_live,
                    "oldest_age_ms": round((time.monotonic() - self._queue[0][2]) * 1000, 3) if self._queue else 0,
                    "last_queue_ms": round(self._last_wait_ms, 3), "last_callback_ms": round(self._last_callback_ms, 3)}

    def is_current_callback(self):
        generation = getattr(self._context, "generation", None)
        with self._condition:
            return generation is None or (self._active and generation == self._generation)

    def is_generation(self, generation):
        with self._condition:
            return generation == self._generation

    def check_request(self):
        if not self.is_current_callback():
            raise RuntimeError("callback belongs to a closed cfquant connection")

    def _run(self):
        while True:
            try:
                with self._condition:
                    while self._active and not self._queue:
                        self._condition.wait()
                    if not self._active:
                        self._thread = None
                        return
                    item = self._queue.popleft()
                    generation = item[0]
                    message, raw = self._take_message(item)
                if message is None:
                    message = loads_message(raw)
                    if message is None:
                        raise ValueError("invalid preserved callback message")
            except Exception as error:
                logging.getLogger(__name__).exception("callback backlog failed; connection must be restarted")
                with self._condition:
                    if generation != self._generation:
                        continue  # An old connection must not close its replacement.
                    self._active = False
                    self._clear_queue()
                    self._thread = None
                if self._on_error is not None:
                    self._on_error(error, generation)
                return
            started = time.monotonic()
            self._last_wait_ms = (started - item[2]) * 1000
            self._context.generation = generation
            try:
                if self.is_current_callback():
                    self._dispatch(message)
            except Exception:
                logging.getLogger(__name__).exception("callback dispatch failed event=%s", message.get("event"))
            finally:
                self._last_callback_ms = (time.monotonic() - started) * 1000
                del self._context.generation


def dispatch_callbacks(callbacks, message, is_current):
    event = message.get("event")
    raw_data = message.get("data")
    meta = message.get("meta")
    plain_quote = (isinstance(raw_data, dict) and isinstance(meta, dict)
                   and meta.get("quote_json_plain") is True)
    # The direct snapshot encoder emits only JSON scalars/containers, no tagged
    # SDK values. Do not walk all symbols a second time after JSON parsing.
    data = raw_data if plain_quote else decode_value(raw_data)
    full_message = dict(message, data=data)
    deliveries = [(list(callbacks.get("__event__", [])), full_message),
                  (list(callbacks.get(event, [])), data)]
    if event and event.startswith("quote:"):
        quote_message = dict(full_message)
        if quote_message.get("subscription_id") is not None and quote_message.get("subscribe_id") is None:
            quote_message["subscribe_id"] = quote_message["subscription_id"]
        deliveries.append((list(callbacks.get("quote", [])), quote_message))
    for handlers, payload in deliveries:
        for callback in handlers:
            if not is_current():
                return
            try:
                callback(payload)
            except Exception:
                logging.getLogger(__name__).exception("user callback failed event=%s", event)
