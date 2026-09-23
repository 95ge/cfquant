# -*- coding: utf-8 -*-
"""Serial user callbacks, independent of the RPC receive thread."""
from collections import deque
import logging
import threading

from .protocol import decode_value


class CallbackDispatcher(object):
    def __init__(self, dispatch):
        self._dispatch = dispatch
        self._condition = threading.Condition()
        self._queue = deque()
        self._generation = 0
        self._active = False
        self._thread = None
        self._context = threading.local()

    def start(self):
        with self._condition:
            self._generation += 1
            self._active = True
            self._queue.clear()
            return self._generation

    def stop(self):
        with self._condition:
            self._active = False
            self._generation += 1
            self._queue.clear()
            self._condition.notify_all()
        # Never join: close/stop may be called by a callback itself.

    def submit(self, generation, message):
        with self._condition:
            if not self._active or generation != self._generation:
                return
            # Do not block the receive thread on a slow user callback. Trade
            # events cannot be silently dropped or coalesced.
            self._queue.append((generation, message))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="cfquant-event-callback")
                self._thread.daemon = True
                self._thread.start()
            self._condition.notify()

    def is_current_callback(self):
        generation = getattr(self._context, "generation", None)
        with self._condition:
            return generation is None or (self._active and generation == self._generation)

    def check_request(self):
        if not self.is_current_callback():
            raise RuntimeError("callback belongs to a closed cfquant connection")

    def _run(self):
        while True:
            with self._condition:
                while self._active and not self._queue:
                    self._condition.wait()
                if not self._active:
                    self._thread = None
                    return
                generation, message = self._queue.popleft()
            self._context.generation = generation
            try:
                if self.is_current_callback():
                    self._dispatch(message)
            except Exception:
                logging.getLogger(__name__).exception("callback dispatch failed event=%s", message.get("event"))
            finally:
                del self._context.generation


def dispatch_callbacks(callbacks, message, is_current):
    event = message.get("event")
    data = decode_value(message.get("data"))
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
