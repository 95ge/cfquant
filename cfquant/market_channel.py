"""LTtx whole-market consumers. Memory only, one ordered worker per subscription."""
import atexit
from numbers import Integral
import queue
import sys
import threading
import time

from .config import get_config
from .diagnostic_context import get_logger
from .protocol import loads_message, decode_value
from .shared_quotes import quote_scope, quote_matches

WHOLE_QUOTE_CHANNEL = 'all_gp_hq'


class MemoryChannelQueue(queue.Queue):
    """The LTtx receive queue itself, with constant-time in-memory accounting."""
    def __init__(self):
        super().__init__()
        self.bytes = self.received = self.discarded = 0
        self.last_queue_ms = 0.0

    def _put(self, value):
        size = sys.getsizeof(value)
        self.queue.append((value, time.monotonic(), size))
        self.bytes += size
        self.received += 1

    def _get(self):
        value, received, size = self.queue.popleft()
        self.bytes -= size
        self.last_queue_ms = (time.monotonic() - received) * 1000
        return value

    def status(self):
        with self.mutex:
            return dict(queued_callbacks=len(self.queue), estimated_memory_bytes=self.bytes,
                        oldest_age_ms=(time.monotonic() - self.queue[0][1]) * 1000 if self.queue else 0,
                        last_queue_ms=self.last_queue_ms, received_messages=self.received,
                        discarded_on_close=self.discarded)

    def clear(self):
        with self.mutex:
            self.discarded += len(self.queue)
            self.queue.clear()
            self.bytes = 0


class ChannelSubscription:
    """Dedicated transport and worker: slow callbacks never occupy a trading queue."""
    def __init__(self, callback, codes=(), channel=WHOLE_QUOTE_CHANNEL, factory=None,
                 config=None, event=False, diagnostic=False):
        from .client import _load_txl
        cfg = config or get_config()
        self.callback, self.codes, self.channel = callback, quote_scope(codes), channel
        self.event = event
        self.diagnostic = diagnostic
        self.closed = threading.Event()
        self.received = self.processed = self.failures = 0
        self.last_received = self.last_callback_ms = 0
        self.error = ''
        self._last_warning = 0
        self.tx = (factory or _load_txl())(cfg['host'], cfg['port'], cfg['token'], show=False)
        self.tx.Q = MemoryChannelQueue()
        self.thread = None
        self._start_lock = threading.Lock()

    def start(self):
        with self._start_lock:
            if self.closed.is_set():
                raise RuntimeError('channel subscription is closed')
            if self.thread is not None:
                return self
            return self._start()

    def _start(self):
        try:
            self.tx.start_txg(self.channel)
            if self.closed.is_set():
                raise RuntimeError('channel subscription closed during startup')
            self.thread = threading.Thread(target=self._run, name='cfquant-channel-' + self.channel,
                                           daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.close()
            raise

    def _run(self):
        while not self.closed.is_set():
            try:
                raw = self.tx.Q.get(timeout=.2)
            except queue.Empty:
                continue
            if raw is None or self.closed.is_set():
                break
            try:
                message = loads_message(raw)
                if not message or message.get('type') != 'event':
                    continue
                data = message.get('data')
                if not (message.get('meta') or {}).get('quote_json_plain'):
                    data = decode_value(data)
                    message = dict(message, data=data)
                envelope = data
                if isinstance(data, dict) and data.get('schema') == 'cfquant.quote_latency.v1':
                    data = data.get('quotes')
                if self.event:
                    value = message
                else:
                    if not isinstance(data, dict):
                        continue
                    # Each batch is delivered intact, with only explicit scope filtering.
                    value = {code: quote for code, quote in data.items() if quote_matches(code, self.codes)}
                    if not value:
                        continue
                    if self.diagnostic:
                        value = dict(envelope, quotes=value)
                self.received += 1
                self.last_received = time.time()
                started = time.monotonic()
                if self.callback:
                    self.callback(value)
                self.processed += 1
                self.last_callback_ms = (time.monotonic() - started) * 1000
                if self.tx.Q.qsize() >= 1000 and time.monotonic() - self._last_warning > 5:
                    self._last_warning = time.monotonic()
                    get_logger(__name__).warning('LTtx consumer backlog channel=%s queued=%s',
                                                 self.channel, self.tx.Q.qsize())
            except Exception as error:
                self.failures += 1
                self.error = str(error)
                if time.monotonic() - self._last_warning > 5:
                    self._last_warning = time.monotonic()
                    get_logger(__name__).exception('channel callback failed channel=%s failures=%s',
                                                   self.channel, self.failures)

    def status(self):
        return dict(self.tx.Q.status(), channel=self.channel, received=self.received,
                    processed=self.processed, failures=self.failures, error=self.error,
                    last_callback_ms=self.last_callback_ms, last_received=self.last_received,
                    spooled_bytes=0, running=not self.closed.is_set(),
                    connected=bool((getattr(self.tx, 'txg_dict', {}).get(self.channel) or {}).get('txg_running')))

    def close(self):
        self.closed.set()
        self.tx.close()
        self.tx.Q.clear()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)


_lock = threading.RLock()
_subscriptions = {}
_sequence = 1 << 52  # Disjoint from native QMT IDs; remains exactly representable in JSON.


def subscribe(codes, callback, diagnostic=False):
    if callback is not None and not callable(callback):
        raise TypeError('callback must be callable')
    global _sequence
    subscription = ChannelSubscription(callback, codes, diagnostic=diagnostic)
    with _lock:
        _sequence += 1
        key = _sequence
        _subscriptions[key] = subscription
    try:
        subscription.start()
        return key
    except BaseException:
        unsubscribe(key)
        raise


def unsubscribe(key):
    with _lock:
        subscription = _subscriptions.pop(key, None)
    if subscription is None:
        return False
    subscription.close()
    return True


def owns(key):
    return isinstance(key, Integral) and key >= 1 << 52


def close_all():
    with _lock:
        subscriptions = list(_subscriptions.values())
        _subscriptions.clear()
    for subscription in subscriptions:
        subscription.close()


atexit.register(close_all)
