"""Bounded-memory Web history; old batches remain queryable in a temporary file."""
from collections import deque
import json
import tempfile
import threading


class QuoteHistory(object):
    def __init__(self, max_events=1000, memory_bytes=64 * 1024 * 1024):
        self.max_events = max(1, int(max_events))
        self.memory_limit = max(0, int(memory_bytes))
        self._rows = deque()
        self._memory_bytes = 0
        self._disk_live_bytes = 0
        self._file_size = 0
        self._file = None
        self._lock = threading.RLock()

    def __len__(self):
        with self._lock:
            return len(self._rows)

    def append(self, event, encoded):
        with self._lock:
            row = {"seq": event.get("seq", 0), "subscribe_id": str(event.get("subscribe_id") or ""),
                   "data": encoded, "size": len(encoded), "offset": None}
            self._rows.append(row)
            self._memory_bytes += row["size"]
            while len(self._rows) > self.max_events:
                self._discard(self._rows.popleft())
            self._spill()
            self._compact()

    def _discard(self, row):
        if row["data"] is not None:
            self._memory_bytes -= row["size"]
        else:
            self._disk_live_bytes -= row["size"]

    def _spill(self):
        for row in self._rows:
            if self._memory_bytes <= self.memory_limit:
                break
            if row["data"] is None:
                continue
            if self._file is None:
                self._file = tempfile.TemporaryFile(prefix="cfquant-quotes-")
            self._file.seek(self._file_size)
            written = self._file.write(row["data"])
            if written != row["size"]:
                raise OSError("incomplete quote history write")
            row["offset"] = self._file_size
            self._file_size += written
            self._disk_live_bytes += written
            self._memory_bytes -= written
            row["data"] = None

    def _bytes(self, row):
        if row["data"] is not None:
            return row["data"]
        self._file.seek(row["offset"])
        data = self._file.read(row["size"])
        if len(data) != row["size"]:
            raise OSError("incomplete quote history read")
        return data

    def _compact(self):
        if self._file is None:
            return
        if not self._disk_live_bytes:
            self._file.close()
            self._file = None
            self._file_size = 0
            return
        if self._file_size <= max(self.memory_limit, 1024 * 1024) + self._disk_live_bytes * 2:
            return
        replacement = tempfile.TemporaryFile(prefix="cfquant-quotes-")
        offsets = []
        try:
            for row in self._rows:
                if row["data"] is None:
                    offset = replacement.tell()
                    data = self._bytes(row)
                    if replacement.write(data) != len(data):
                        raise OSError("incomplete quote history compaction")
                    offsets.append((row, offset))
        except BaseException:
            replacement.close()
            raise
        self._file.close()
        self._file = replacement
        self._file_size = replacement.tell()
        for row, offset in offsets:
            row["offset"] = offset

    def latest(self, since=0, limit=200, subscribe_id=None):
        with self._lock:
            rows = [row for row in self._rows if row["seq"] > since
                    and (not subscribe_id or row["subscribe_id"] == str(subscribe_id))]
            return [json.loads(self._bytes(row).decode("utf-8"))["event"] for row in rows[-int(limit):]]

    def clear(self, subscribe_id=None):
        with self._lock:
            if subscribe_id is None:
                self._rows.clear()
                self._memory_bytes = self._disk_live_bytes = 0
            else:
                kept = deque()
                for row in self._rows:
                    if row["subscribe_id"] == str(subscribe_id):
                        self._discard(row)
                    else:
                        kept.append(row)
                self._rows = kept
            self._compact()

    def status(self):
        with self._lock:
            return {"retained_batches": len(self._rows), "max_batches": self.max_events,
                    "memory_bytes": self._memory_bytes, "memory_limit_bytes": self.memory_limit,
                    "disk_bytes": self._file_size, "disk_live_bytes": self._disk_live_bytes,
                    "oldest_seq": self._rows[0]["seq"] if self._rows else None}
