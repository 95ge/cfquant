"""Client manifest and independent lease renewal for the Web transport."""
import copy
import json
import secrets
import threading
import time
import uuid

from .subscription_bridge import _SUB_QUOTES
from .diagnostic_context import get_logger


class SubscriptionSession:
    def __init__(self, request, interval=10):
        self.request, self.interval = request, interval
        self.owner, self.secret = uuid.uuid4().hex, secrets.token_hex(32)
        self.handshake = {}
        self.specs, self.statuses, self.identities = {}, {}, {}
        self.revision = 0
        self._lock, self._rpc_lock = threading.RLock(), threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.last_error = ''

    def _payload(self, op, **extra):
        return dict(op=op, owner=self.owner, **dict(self.handshake, **extra))

    def sync(self):
        with self._rpc_lock:
            for attempt in range(2):
                if not self.handshake:
                    try:
                        self.handshake = self.request('cfquant.subscriptions',
                            {'op': 'open', 'owner': self.owner, 'secret': self.secret}, timeout=3)
                    except Exception as error:
                        if 'subscription owner expired' not in str(error):
                            raise
                        self.owner, self.secret = uuid.uuid4().hex, secrets.token_hex(32)
                        continue
                with self._lock:
                    revision = self.revision
                    specs = copy.deepcopy(list(self.specs.values()))
                try:
                    result = self.request('cfquant.subscriptions', self._payload('sync', revision=revision, specs=specs), timeout=3)
                except Exception as error:
                    if 'subscription handshake required' in str(error):
                        self.handshake = {}
                        continue
                    raise
                with self._lock:
                    self.statuses = result['subscriptions']
                self.last_error = ''
                return
            raise RuntimeError('subscription handshake did not complete')

    def add(self, action, params, timeout=12, identity=None):
        with self._lock:
            sid = self.identities.get(identity) if identity else None
            if sid is None:
                sid = str(secrets.randbelow(2**52 - 1) + 1)
                self.specs[sid] = {'id': sid, 'action': action, 'params': copy.deepcopy(params)}
                self.revision += 1
                if identity:
                    self.identities[identity] = sid
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='cfquant-subscription-heartbeat', daemon=True)
                self._thread.start()
        deadline = time.monotonic() + timeout
        try:
            while not self._stop.is_set():
                self.sync()
                state = self.statuses.get(sid, {})
                if state.get('state') == 'active':
                    return int(sid)
                if state.get('state') == 'paused':
                    raise RuntimeError(state.get('error') or 'subscription recovery paused')
                if time.monotonic() >= deadline:
                    raise TimeoutError(state.get('error') or 'subscription acknowledgement timed out')
                self._stop.wait(.2)
            raise RuntimeError('subscription session closed')
        except BaseException:
            # Persist the cancellation after an ambiguous acknowledgement so
            # a late bridge result cannot leave an orphaned active lease.
            self.remove(sid, synchronize=True)
            raise

    def remove(self, sid, synchronize=True):
        with self._lock:
            sid = str(sid)
            existed = self.specs.pop(sid, None) is not None
            if existed:
                self.revision += 1
            for identity, value in list(self.identities.items()):
                if value == sid:
                    del self.identities[identity]
        if synchronize and existed:
            try:
                self.sync()
            except Exception as error:
                # Latest full manifest retains the local cancellation across reconnect.
                self.last_error = 'cancellation pending: ' + str(error)
        return existed

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.sync()
            except Exception as error:
                message = str(error)
                if self.last_error != message:
                    get_logger(__name__).warning('subscription recovery deferred: %s', message)
                self.last_error = message

    def close(self):
        self._stop.set()
        # Serialize close with a heartbeat/manifest sync.  Otherwise an
        # in-flight sync could publish the old manifest after the close
        # request and immediately re-arm the durable lease.
        with self._rpc_lock:
            with self._lock:
                self.specs.clear()
                self.identities.clear()
                self.revision += 1
            if self.handshake:
                try:
                    self.request('cfquant.subscriptions', self._payload('close'), timeout=2)
                except Exception:
                    pass


def subscription_identity(action, params):
    if action.startswith('xttrader.') or action == 'cfquant.account_subscription_status':
        account = params.get('account') or {}
        return 'account:' + json.dumps(account, sort_keys=True, separators=(',', ':'))
    if action == 'qmt_inner.callbacks':
        return 'inner:' + str(params.get('session_id')) + ':' + str(params.get('name'))
    return None


def managed_request(client, raw_request, action, params, timeout):
    """Return (handled, result); no retry/fallback after uncertain mutation."""
    params = dict(params or {})
    session = getattr(client, '_subscription_session', None)
    inner = bool(params.get('_managed_recovery'))
    # XtQuantTrader already has its own account-subscription recovery worker;
    # keep that protocol unchanged and persist market/native subscriptions here.
    eligible = action in _SUB_QUOTES or action in ('xtdata.unsubscribe_quote',)
    eligible = eligible or (inner and (action == 'qmt_inner.callbacks' or
        (action == 'qmt_inner.call' and params.get('method') in ('subscribe_quote', 'subscribe_whole_quote', 'unsubscribe_quote'))))
    if not eligible:
        return False, None
    if getattr(client, '_subscription_protocol', None) is None:
        try:
            value = raw_request('cfquant.subscriptions', {'op': 'capabilities'}, timeout=3)
        except Exception as error:
            if not str(error).lower().startswith(('unsupported action:', 'unsupported external web_lttx action:')):
                raise
            client._subscription_protocol = False
        else:
            client._subscription_protocol = isinstance(value, dict) and value.get('version') == 1
    if not client._subscription_protocol:
        if inner:
            raise RuntimeError('server does not support managed subscription recovery')
        return False, None
    if session is None:
        with client._subscription_init_lock:
            session = getattr(client, '_subscription_session', None)
            if session is None:
                session = client._subscription_session = SubscriptionSession(raw_request)
    identity = subscription_identity(action, params)
    if action == 'xtdata.unsubscribe_quote' or (inner and params.get('method') == 'unsubscribe_quote'):
        sid = params.get('subscribe_id') if not inner else (params.get('args') or [None])[0]
        if str(sid) not in session.specs:
            return (True, True) if inner else (False, None)
        session.remove(sid)
        return True, True
    if action == 'qmt_inner.callbacks':
        previous = session.identities.get(identity)
        if previous:
            session.remove(previous, synchronize=False)
        if not params.get('token'):
            session.sync()
            return True, True
    params.pop('subscription_renewal', None)
    sid = session.add(action, params, timeout=timeout or client.timeout, identity=identity)
    if action == 'xttrader.subscribe':
        return True, 0
    if action.startswith('qmt_inner.'):
        return True, True if action.endswith('callbacks') else sid
    return True, {'subscribe_id': sid, 'callback_event': params.get('callback_event'), 'managed': True}
