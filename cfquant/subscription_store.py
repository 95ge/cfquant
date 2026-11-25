"""Durable desired subscriptions. Never stores executable Python objects."""
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid

from .subscription_bridge import validate_subscription_spec


class SubscriptionStore:
    def __init__(self, path, clock=time.time, owner_limit=128, per_owner=512,
                 active_limit=5000, record_limit=100000, resume_seconds=86400,
                 history_seconds=604800):
        # SQLite accepts PathLike values; normalize before building lock names.
        path = os.fsdecode(path)
        self.clock, self.owner_limit, self.per_owner = clock, owner_limit, per_owner
        self.active_limit, self.record_limit = active_limit, record_limit
        self.resume_seconds, self.history_seconds = resume_seconds, history_seconds
        self.lock = threading.RLock()
        self._owner_file = None
        if path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            handle = open(path + '.lock', 'a+b')
            try:
                if os.path.getsize(path + '.lock') == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                handle.close()
                raise RuntimeError('another subscription manager owns this database')
            self._owner_file = handle
        try:
            self.db = sqlite3.connect(path, timeout=3, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS owners (
                    id TEXT PRIMARY KEY, secret TEXT NOT NULL, client TEXT NOT NULL,
                    seen REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT -1, digest TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS subscriptions (
                    key TEXT PRIMARY KEY, owner TEXT NOT NULL, id TEXT NOT NULL,
                    spec TEXT NOT NULL, desired INTEGER NOT NULL, updated REAL NOT NULL,
                    state TEXT NOT NULL, attempted INTEGER NOT NULL DEFAULT 0,
                    native_id TEXT, generation TEXT, error TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0,
                    UNIQUE(owner, id));
                CREATE INDEX IF NOT EXISTS subscriptions_owner ON subscriptions(owner);
                CREATE INDEX IF NOT EXISTS subscriptions_cleanup ON subscriptions(desired, updated);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT OR IGNORE INTO meta VALUES ('epoch', 0);
                UPDATE meta SET value=value+1 WHERE key='epoch';
            ''')
            self.db.commit()
            self.epoch = self.db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0]
        except BaseException:
            if hasattr(self, 'db'):
                self.db.close()
            if self._owner_file:
                self._owner_file.close()
            raise

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def open_owner(self, owner, secret, client):
        if not all(isinstance(x, str) and 16 <= len(x) <= 128 for x in (owner, secret)) or not client:
            raise ValueError('invalid subscription owner credentials')
        with self.lock, self.db:
            row = self.db.execute('SELECT * FROM owners WHERE id=?', (owner,)).fetchone()
            if row:
                if not hmac.compare_digest(row['secret'], self.digest(secret)) or row['client'] != client:
                    raise ValueError('subscription owner mismatch')
                if row['closed'] or self.clock() - row['seen'] > self.resume_seconds:
                    raise ValueError('subscription owner expired')
            else:
                count = self.db.execute('SELECT count(*) FROM owners WHERE closed=0 AND seen>?',
                                        (self.clock() - self.resume_seconds,)).fetchone()[0]
                if count >= self.owner_limit:
                    raise ValueError('subscription owner limit reached')
                self.db.execute('INSERT INTO owners(id,secret,client,seen) VALUES (?,?,?,?)',
                                (owner, self.digest(secret), client, self.clock()))

    def sync(self, owner, revision, specs, prepare):
        if type(revision) is not int or revision < 0 or not isinstance(specs, list) or len(specs) > self.per_owner:
            raise ValueError('invalid or oversized subscription manifest')
        normalized = {}
        for item in specs:
            sid = item.get('id')
            if not isinstance(sid, str) or not sid.isdigit() or not 0 < int(sid) < 2**53 or sid in normalized:
                raise ValueError('invalid or duplicate logical subscription ID')
            spec = {'action': item.get('action'), 'params': item.get('params')}
            validate_subscription_spec(spec)
            normalized[sid] = spec
        raw = json.dumps(normalized, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(raw.encode('utf-8')) > 4 * 1024 * 1024:
            raise ValueError('subscription manifest exceeds 4 MiB')
        digest = self.digest(raw)
        with self.lock:
            current = self.db.execute('SELECT * FROM owners WHERE id=?', (owner,)).fetchone()
            if current is None or current['closed']:
                raise ValueError('subscription owner expired')
            if revision < current['revision'] or (revision == current['revision'] and current['digest'] != digest):
                raise ValueError('stale or conflicting subscription manifest')
            old = {row['id']: dict(row) for row in self.db.execute('SELECT * FROM subscriptions WHERE owner=?', (owner,))}
            # Route resolution is local only. Native RPC never runs inside a transaction.
            new = {}
            for sid, spec in normalized.items():
                if sid in old:
                    saved = json.loads(old[sid]['spec'])
                    if not old[sid]['desired'] or {k: saved[k] for k in ('action', 'params')} != spec:
                        raise ValueError('cancelled or changed subscription ID cannot be reused')
                else:
                    new[sid] = prepare(spec)
            active = self.db.execute('SELECT count(*) FROM subscriptions WHERE desired=1').fetchone()[0]
            removed = sum(row['desired'] for sid, row in old.items() if sid not in normalized)
            total = self.db.execute('SELECT count(*) FROM subscriptions').fetchone()[0]
            if active - removed + len(new) > self.active_limit or total + len(new) > self.record_limit:
                raise ValueError('subscription capacity reached')
            now = self.clock()
            with self.db:
                for sid, spec in new.items():
                    self.db.execute('INSERT INTO subscriptions(key,owner,id,spec,desired,updated,state) VALUES (?,?,?,?,1,?,?)',
                                    (owner + ':' + sid, owner, sid, json.dumps(spec, allow_nan=False), now, 'pending'))
                for sid, row in old.items():
                    if sid not in normalized and row['desired']:
                        self.db.execute("UPDATE subscriptions SET desired=0,state='releasing',updated=?,due=0 WHERE key=?", (now, row['key']))
                self.db.execute('UPDATE owners SET revision=?,digest=?,seen=? WHERE id=?', (revision, digest, now, owner))

    def rows(self, owner=None):
        with self.lock:
            query = 'SELECT * FROM subscriptions' + (' WHERE owner=?' if owner else '')
            rows = self.db.execute(query, (owner,) if owner else ()).fetchall()
            return [dict(row, spec=json.loads(row['spec'])) for row in rows]

    def update(self, key, **values):
        allowed = {'state', 'attempted', 'native_id', 'generation', 'error', 'attempts', 'due'}
        if not values or not set(values) <= allowed:
            raise ValueError('invalid subscription update')
        with self.lock, self.db:
            self.db.execute('UPDATE subscriptions SET ' + ','.join(k + '=?' for k in values) + ' WHERE key=?',
                            tuple(values.values()) + (key,))

    def close_owner(self, owner):
        with self.lock, self.db:
            self.db.execute('UPDATE owners SET closed=1,seen=? WHERE id=?', (self.clock(), owner))
            self.db.execute("UPDATE subscriptions SET desired=0,state='releasing',updated=?,due=0 WHERE owner=? AND desired=1",
                            (self.clock(), owner))

    def prune(self):
        now = self.clock()
        with self.lock, self.db:
            self.db.execute("UPDATE subscriptions SET desired=0,updated=?,state='releasing',due=0 WHERE desired=1 AND owner IN (SELECT id FROM owners WHERE seen<?)",
                            (now, now - self.resume_seconds))
            # A cancelled row may still have an old ``attempted`` marker when
            # the service was stopped before its native cleanup completed.
            # Retain it for the history window, then discard it regardless of
            # that marker; the bridge-side lease has already fenced the native
            # resource by this point.
            self.db.execute("DELETE FROM subscriptions WHERE key IN (SELECT key FROM subscriptions WHERE desired=0 AND updated<? LIMIT 200)",
                            (now - self.history_seconds,))
            self.db.execute('DELETE FROM owners WHERE seen<? AND NOT EXISTS (SELECT 1 FROM subscriptions WHERE owner=owners.id)',
                            (now - self.history_seconds,))

    def close(self):
        with self.lock:
            self.db.close()
            if self._owner_file:
                self._owner_file.close()
                self._owner_file = None
