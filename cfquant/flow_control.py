"""Ordered, bounded background work. No QMT API calls run in these workers."""
from collections import deque
import logging
import threading
import time


class OrderedSender(object):
    """One FIFO writer per connection; overflow/failure closes that connection.

    Capacity includes the in-flight frame. Accepted frames are never coalesced,
    silently evicted, or replayed on a different connection.
    """
    def __init__(self, send, on_error, max_items=1024, max_bytes=128 * 1024 * 1024):
        self.send = send
        self.on_error = on_error
        self.max_items = max(1, int(max_items))
        self.max_bytes = max(1, int(max_bytes))
        self._condition = threading.Condition()
        self._queue = deque()
        self._bytes = 0
        self._inflight = None
        self._closed = False
        self._thread = None
        self._sent = 0
        self._last_queue_ms = 0.0
        self._last_send_ms = 0.0
        self._error = ""

    def submit(self, payload, size=None):
        size = len(payload) if size is None else int(size)
        error = None
        with self._condition:
            if self._closed:
                raise RuntimeError("sender is closed: %s" % self._error)
            count = len(self._queue) + (self._inflight is not None)
            if count >= self.max_items or self._bytes + size > self.max_bytes:
                error = BufferError("send backlog exceeded limits (%s frames, %s bytes)" % (count, self._bytes))
            else:
                self._queue.append((payload, size, time.monotonic()))
                self._bytes += size
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name="cfquant-ordered-send")
                    self._thread.daemon = True
                    self._thread.start()
                self._condition.notify()
        if error is not None:
            self._fail(error)
            raise error

    def close(self):
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._bytes = self._inflight[1] if self._inflight is not None else 0
            self._condition.notify_all()

    def _fail(self, error):
        with self._condition:
            if self._closed:
                return
            self._error = str(error)
            self.close()
        self.on_error(error)

    def _run(self):
        while True:
            with self._condition:
                while not self._closed and not self._queue:
                    self._condition.wait()
                if self._closed:
                    return
                item = self._queue.popleft()
                self._inflight = item
            started = time.monotonic()
            try:
                self.send(item[0])
            except Exception as error:
                self._fail(error)
                return
            finally:
                with self._condition:
                    self._last_queue_ms = (started - item[2]) * 1000
                    self._last_send_ms = (time.monotonic() - started) * 1000
                    self._bytes -= item[1]
                    self._inflight = None
            with self._condition:
                self._sent += 1

    def status(self):
        with self._condition:
            oldest = self._inflight or (self._queue[0] if self._queue else None)
            return {"queued_frames": len(self._queue), "buffered_bytes": self._bytes,
                    "sending": self._inflight is not None, "sent_frames": self._sent,
                    "oldest_age_ms": round((time.monotonic() - oldest[2]) * 1000, 3) if oldest else 0,
                    "last_queue_ms": round(self._last_queue_ms, 3),
                    "last_send_ms": round(self._last_send_ms, 3), "error": self._error}


class KeyedExecutor(object):
    """Parallel independent requests, FIFO for every shared resource key."""
    def __init__(self, workers=8, max_pending=1024):
        self.workers = max(1, int(workers))
        self.max_pending = max(1, int(max_pending))
        self._condition = threading.Condition()
        self._pending = deque()
        self._active = set()
        self._threads = []
        self._closed = False

    def submit(self, keys, run, reject):
        with self._condition:
            if self._closed or len(self._pending) >= self.max_pending:
                raise BufferError("Web route request queue is closed or full")
            self._pending.append((frozenset(keys), run, reject, time.monotonic()))
            if not self._threads:
                for _ in range(self.workers):
                    thread = threading.Thread(target=self._run, name="cfquant-web-route")
                    thread.daemon = True
                    self._threads.append(thread)
                    thread.start()
            self._condition.notify_all()

    def _take(self):
        blocked = set(self._active)
        for item in self._pending:
            if not blocked.intersection(item[0]):
                self._pending.remove(item)
                self._active.update(item[0])
                return item
            # A later request cannot overtake an earlier request sharing a key.
            blocked.update(item[0])
        return None

    def _run(self):
        while True:
            with self._condition:
                item = self._take()
                while item is None and not self._closed:
                    self._condition.wait()
                    item = self._take()
                if item is None:
                    return
            try:
                item[1]()
            except Exception as error:
                self._reject(item, error)
            finally:
                with self._condition:
                    self._active.difference_update(item[0])
                    self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            pending = list(self._pending)
            self._pending.clear()
            self._condition.notify_all()
        for item in pending:
            self._reject(item, RuntimeError("Web route stopped before request dispatch"))

    def _reject(self, item, error):
        try:
            item[2](error)
        except Exception:
            logging.getLogger(__name__).exception("Web route could not deliver request failure")

    def status(self):
        with self._condition:
            return {"queued_requests": len(self._pending), "active_keys": len(self._active),
                    "oldest_age_ms": round((time.monotonic() - self._pending[0][3]) * 1000, 3) if self._pending else 0}
