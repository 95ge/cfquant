"""Bounded local log browsing and rotation, independent of the web server."""
import datetime
import os
import re
import threading
import time
import uuid
from pathlib import Path


def retention_days(value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError("retention_days must be an integer between 1 and 3650")
    result = int(value)
    if not 1 <= result <= 3650:
        raise ValueError("retention_days must be between 1 and 3650")
    return result


def log_files(root, day):
    datetime.date.fromisoformat(day)
    root = Path(root).resolve()
    rows = []
    if not root.is_dir():
        return rows
    # The managed log directory only; never traverse symlinks or user paths.
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not Path(current, d).is_symlink()]
        for name in files:
            path = Path(current, name)
            if path.is_symlink() or path.suffix.lower() != '.log':
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            modified = datetime.datetime.fromtimestamp(stat.st_mtime).date().isoformat()
            dates = re.findall(r"(?<!\d)(20\d{2})[-_]?(\d{2})[-_]?(\d{2})(?!\d)", name)
            if modified != day and day not in ['-'.join(parts) for parts in dates]:
                continue
            rows.append({'name': path.relative_to(root).as_posix(), 'size': stat.st_size,
                         'modified': stat.st_mtime})
            if len(rows) >= 1000:
                return rows
    return sorted(rows, key=lambda row: row['modified'], reverse=True)


def read_log(root, name, limit=256 * 1024):
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not name or root not in path.parents or path.suffix.lower() != '.log':
        raise ValueError('Invalid log file')
    with path.open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        data = stream.read(limit)
    if size > limit and b'\n' in data:
        data = data.split(b'\n', 1)[1]
    return {'name': name, 'size': size, 'truncated': size > limit,
            'text': data.decode('utf-8', errors='replace')}


class RollingLogWriter:
    """File-like sink: rotate daily or at 20 MiB, preserving open-stream users."""
    encoding = 'utf-8'

    def __init__(self, path, max_bytes=20 * 1024 * 1024):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._day = time.strftime('%Y-%m-%d', time.localtime(self.path.stat().st_mtime)) if self.path.exists() else time.strftime('%Y-%m-%d')
        self._stream = self.path.open('a', encoding='utf-8', buffering=1)

    def write(self, text):
        with self._lock:
            day = time.strftime('%Y-%m-%d')
            if self._day != day or self._stream.tell() >= self.max_bytes:
                self._stream.close()
                try:
                    target = self.path.with_name('%s.%s.%s.log' % (self.path.stem, self._day, uuid.uuid4().hex[:12]))
                    self.path.rename(target)
                    self._day = day
                finally:
                    self._stream = self.path.open('a', encoding='utf-8', buffering=1)
            return self._stream.write(text)

    def flush(self):
        with self._lock:
            self._stream.flush()

    def close(self):
        with self._lock:
            self._stream.close()

    def isatty(self):
        return False
