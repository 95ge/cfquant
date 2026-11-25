"""Bounded in-memory Web display history; never a durable market-data archive."""
from collections import deque
import json
import threading


class QuoteHistory(object):
    def __init__(self, max_events=1000, memory_bytes=64 * 1024 * 1024):
        self.max_events = max(1, int(max_events))
        self.memory_limit = max(0, int(memory_bytes))
        self._rows = deque()
        self._memory_bytes = 0
        self._evicted = 0
        self._lock = threading.RLock()

    def __len__(self):
        with self._lock:
            return len(self._rows)

    def append(self, event, encoded):
        with self._lock:
            self._rows.append(dict(seq=event.get('seq', 0),
                                   subscribe_id=str(event.get('subscribe_id') or ''), data=encoded))
            self._memory_bytes += len(encoded)
            while len(self._rows) > self.max_events or self._memory_bytes > self.memory_limit:
                self._memory_bytes -= len(self._rows.popleft()['data'])
                self._evicted += 1

    def latest(self, since=0, limit=200, subscribe_id=None):
        with self._lock:
            rows = [row for row in self._rows if row['seq'] > since
                    and (not subscribe_id or row['subscribe_id'] == str(subscribe_id))]
            return [json.loads(row['data'].decode('utf-8'))['event'] for row in rows[-int(limit):]]

    def clear(self, subscribe_id=None):
        with self._lock:
            self._rows = deque(row for row in self._rows if subscribe_id is not None
                               and row['subscribe_id'] != str(subscribe_id))
            self._memory_bytes = sum(len(row['data']) for row in self._rows)

    def status(self):
        with self._lock:
            return dict(retained_batches=len(self._rows), max_batches=self.max_events,
                        memory_bytes=self._memory_bytes, memory_limit_bytes=self.memory_limit,
                        disk_bytes=0, disk_live_bytes=0, evicted_batches=self._evicted,
                        oldest_seq=self._rows[0]['seq'] if self._rows else None)
