"""Lease-gated recovery of durable subscription intent, outside the QMT process."""
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
import threading
import time
import uuid

from .diagnostic_context import get_logger


class SubscriptionManager:
    def __init__(self, store, adapter, lease_seconds=45, clock=time.monotonic, start=True):
        self.store, self.adapter, self.lease_seconds, self.clock = store, adapter, lease_seconds, clock
        self.boot_id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._sessions, self._routes, self._busy, self._next = {}, {}, set(), {}
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='cfquant-subscriptions')
        self._thread = None
        self._prune_at = 0
        # A resource binding belongs to the previous bridge/service boot until
        # the current client handshake proves it still exists.
        for row in self.store.rows():
            if row['desired']:
                self.store.update(row['key'], state='awaiting_client', due=0)
        if start:
            self._thread = threading.Thread(target=self._run, name='cfquant-subscription-leases', daemon=True)
            self._thread.start()

    def handle(self, params, client):
        op, owner = params.get('op'), params.get('owner')
        if op == 'capabilities':
            return {'version': 1, 'boot_id': self.boot_id, 'lease_seconds': self.lease_seconds}
        if op == 'open':
            self.store.open_owner(owner, params.get('secret'), client)
            with self._lock:
                row = self._sessions.setdefault(owner, dict(nonce=secrets.token_hex(24), deadline=0, client=client))
                return {'boot_id': self.boot_id, 'nonce': row['nonce']}
        with self._lock:
            session = self._sessions.get(owner)
            if (params.get('boot_id') != self.boot_id or not session or session['client'] != client
                    or not secrets.compare_digest(str(params.get('nonce') or ''), session['nonce'])):
                raise ValueError('subscription handshake required')
        if op == 'sync':
            self.store.sync(owner, params.get('revision'), params.get('specs'), self.adapter.prepare)
            rows = self.store.rows(owner)
            with self._lock:
                session['deadline'] = self.clock() + self.lease_seconds
                self._next.clear()  # manifest changes wake pending cancellation/recovery
                for row in rows:
                    if row['desired']:
                        self._routes[row['key']] = (owner, client, row['spec'])
                    else:
                        self._routes.pop(row['key'], None)
            return {'boot_id': self.boot_id, 'subscriptions': self.status(owner)}
        if op == 'status':
            return {'boot_id': self.boot_id, 'subscriptions': self.status(owner)}
        if op == 'close':
            self.store.close_owner(owner)
            with self._lock:
                session['deadline'] = 0
                for key in list(self._routes):
                    if self._routes[key][0] == owner:
                        self._routes.pop(key)
            return True
        raise ValueError('unsupported subscription manager operation')

    def status(self, owner):
        live = self._is_live(owner)
        return {row['id']: dict(state=row['state'] if live or not row['desired'] else 'awaiting_client',
                                desired=bool(row['desired']), error=row['error'],
                                native_id=row['native_id'], generation=row['generation'])
                for row in self.store.rows(owner)}

    def _is_live(self, owner):
        with self._lock:
            return self._sessions.get(owner, {}).get('deadline', 0) > self.clock()

    def on_event(self, data):
        if not isinstance(data, dict) or data.get('epoch') != self.store.epoch:
            return
        with self._lock:
            route = self._routes.get(data.get('key'))
            if not route or not self._is_live(route[0]):
                return
            owner, client, spec = route
        action, params = spec['action'], spec['params']
        if action.startswith('xtdata.'):
            event = params.get('callback_event')
        elif action.startswith('qmt_inner.'):
            event = 'qmt_inner:' + params['session_id']
        else:
            event = data.get('event')
            if not str(event).startswith('trader:'):
                return
        if event:
            logical_id = data['key'].rsplit(':', 1)[-1]
            self.adapter.emit(client, event, data.get('payload'), logical_id)

    def tick(self):
        if self._stop.is_set():
            return
        now = self.clock()
        if now >= self._prune_at:
            self.store.prune()
            self._prune_at = now + 10
        groups = {}
        for row in self.store.rows():
            live = row['desired'] and self._is_live(row['owner'])
            if not live and not row['attempted']:
                if row['desired'] and row['state'] != 'awaiting_client':
                    self.store.update(row['key'], state='awaiting_client')
                elif not row['desired'] and row['state'] != 'released':
                    self.store.update(row['key'], state='released')
                continue
            group = json.dumps(row['spec']['route'], sort_keys=True)
            groups.setdefault(group, []).append(row)
        # One in-flight job per bridge route; bounded queue across all routes.
        with self._lock:
            for group, rows in groups.items():
                if len(self._busy) >= 4:
                    break
                if group in self._busy or now < self._next.get(group, 0):
                    continue
                self._busy.add(group)
                self._pool.submit(self._work, group, rows)

    def _control(self, spec, **params):
        return self.adapter.control(spec, **dict(params, epoch=self.store.epoch))

    def _work(self, group, rows):
        delay = .2
        try:
            now = self.store.clock()
            # Cleanup is a native operation, sharing the per-route rate budget.
            for row in rows:
                if not row['desired']:
                    self._control(row['spec'], op='release', key=row['key'])
                    self.store.update(row['key'], state='released', attempted=0, error='', attempts=0, due=0)
                    return
                # A durable desired row is fenced until its current client
                # completes the handshake.  Do not touch a bridge resource
                # merely because the Web process is between connections.
                if not self._is_live(row['owner']):
                    continue
                if row['due'] > now:
                    continue
            wanted = [row for row in rows if row['desired'] and self._is_live(row['owner']) and row['due'] <= now]
            if not wanted:
                delay = 1
                return
            # Probe and renew by batches; no native subscription mutation on a healthy probe.
            for offset in range(0, len(wanted), 200):
                batch = wanted[offset:offset + 200]
                result = self._control(batch[0]['spec'], op='probe', keys=[row['key'] for row in batch])
                resources = result['resources']
                missing = []
                for row in batch:
                    resource = resources[row['key']]
                    if resource['state'] == 'active':
                        self.store.update(row['key'], state='active', attempted=1, native_id=resource.get('native_id'),
                                          generation=result['generation'], error='', attempts=0, due=now + 10)
                    elif resource['state'] == 'uncertain':
                        self.store.update(row['key'], state='paused', attempted=1,
                                          error=resource.get('error') or 'native result uncertain', due=now + 10)
                    elif resource['state'] == 'missing':
                        # Once the bridge has fenced an ambiguous native
                        # result and its lease expires, the next probe is
                        # missing and it is safe to issue one fresh ensure.
                        missing.append(row)
                if missing:
                    # Round robin by previous attempt time prevents one failed resource starving others.
                    row = min(missing, key=lambda item: (item['due'], item['attempts'], item['key']))
                    current = next((r for r in self.store.rows(row['owner']) if r['key'] == row['key']), None)
                    if current is None or not current['desired'] or not self._is_live(row['owner']):
                        return
                    self.store.update(row['key'], attempted=1, state='recovering')
                    native_spec = {k: row['spec'][k] for k in ('action', 'params')}
                    result = self._control(row['spec'], op='ensure', key=row['key'], spec_payload=native_spec)
                    self.store.update(row['key'], state='active', native_id=result.get('native_id'),
                                      generation=result['generation'], error='', attempts=0, due=now + 10)
                    return
            delay = 1
        except Exception as error:
            # A single failed bridge backs off as a group, preserving other bridge workers.
            delay = 2
            now = self.store.clock()
            for row in rows:
                if row['due'] > now:
                    continue
                attempts = min(row['attempts'] + 1, 10)
                retry = min(30, 2 ** min(attempts - 1, 5))
                self.store.update(row['key'], error=str(error), attempts=attempts, due=now + retry)
            get_logger(__name__).debug('subscription recovery deferred: %s', error)
        finally:
            with self._lock:
                self._busy.discard(group)
                self._next[group] = self.clock() + delay

    def _run(self):
        while not self._stop.wait(.2):
            try:
                self.tick()
            except Exception:
                get_logger(__name__).exception('subscription maintenance failed')

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._pool.shutdown(wait=True)
        # Durable intent remains; QMT independently expires leases after 45 seconds.
        self.store.close()
