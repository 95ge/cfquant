"""Independent LTtx ingress/egress for PipeHub. No Web imports or HTTP calls."""
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time

from .channels import channels_for_bridge, normalize_bridge_id
from .config import get_config
from .flow_control import KeyedExecutor
from .protocol import dumps_message, loads_message, pack_response, pack_event
from .pipe_transport import loads_pipe_message
from .xtconstant import ACCOUNT_TYPE_DICT
from .batch_orders import CFTRADER_BATCH_ACTIONS
from .center_services import SERVICE_ACTIONS, SERVICE_CHANNEL, ServiceQueues, service_token

CENTER_CHANNEL = 'cfquant.center.request'


def request_market(params):
    aliases = {'0': 'SH', '1': 'SZ', 'SSE': 'SH', 'SHSE': 'SH', 'XSHG': 'SH',
               'SZSE': 'SZ', 'XSHE': 'SZ'}
    for key in ('route_market', 'market', 'exchange', 'exchange_id', 'market_id'):
        value = params.get(key)
        if value is not None and value != '':
            value = str(value).upper()
            return aliases.get(value, value)
    stock = str(params.get('stock_code') or '').upper()
    if '.' in stock:
        return stock.rsplit('.', 1)[-1]
    return ''


class _CenterGuard:
    """One center per endpoint in this Windows session; never run active replicas."""
    def __init__(self, identity=None, label='LTtx endpoint'):
        self.handle = None
        self.identity, self.label = identity, label

    def acquire(self):
        if os.name != 'nt':
            raise RuntimeError('the QMT bridge center requires Windows')
        import ctypes
        from ctypes import wintypes
        cfg = get_config()
        identity = self.identity or '%s:%s:%s' % (cfg['host'], cfg['port'], CENTER_CHANNEL)
        name = 'Local\\CFQuantCenter-' + hashlib.sha256(identity.encode()).hexdigest()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == 183:
            kernel.CloseHandle(handle)
            raise RuntimeError('another bridge center already owns this %s' % self.label)
        self.kernel, self.handle = kernel, handle

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def account_channel(bridge, account, account_type):
    identity = json.dumps([bridge, account, account_type], ensure_ascii=True)
    return 'cfquant.account.' + hashlib.sha256(identity.encode('ascii')).hexdigest()[:32]


class CenterRoutes:
    def __init__(self, path=None):
        runtime = Path(os.environ.get('CFQUANT_RUNTIME_DIR') or Path.cwd() / 'runtime')
        self.path = Path(path or os.environ.get('CFQUANT_WEB_CONFIG_FILE') or
                         runtime / 'config/cfquant_web_config.json')
        self._stamp, self._config = None, {}
        self._lock = threading.Lock()

    def read(self):
        with self._lock:
            if not self.path.exists():
                return {}
            info = self.path.stat()
            stamp = (info.st_mtime_ns, info.st_size)
            if stamp != self._stamp:
                with self.path.open(encoding='utf-8') as stream:
                    self._config = json.load(stream)
                self._stamp = stamp
            return self._config

    def resolve(self, action, params):
        config = self.read()
        data_action = action.startswith(('xtdata.', 'qmt_inner.'))
        account = params.get('account') or {}
        aid = str(params.get('account_id') or account.get('account_id') or '')
        atype = params.get('account_type') or account.get('account_type') or 'STOCK'
        if str(atype).isdigit():
            atype = int(atype)
        atype = str(ACCOUNT_TYPE_DICT.get(atype, atype)).upper()
        bridge = params.get('bridge_id') or account.get('bridge_id')
        key = params.get('account_key') or account.get('account_key')
        rows = [dict(row, account_key=k) for k, row in config.get('account_configs', {}).items()
                if row.get('enabled', True)]
        requested = bool(aid or key or bridge)
        matches = [row for row in rows if (not aid or str(row.get('account_id')) == aid)
                   and (not aid or str(row.get('account_type') or 'STOCK').upper() == atype)
                   and (not key or row['account_key'] == key)
                   and (not bridge or row.get('bridge_id', 'default') == bridge
                        or any(child.get('bridge_id') == bridge for child in
                               (row.get('market_bridges') or {}).values()))]
        if not aid and not key:
            preferred = (config.get('data_provider_account_key') if data_action
                         else config.get('default_account_key'))
            chosen = [row for row in matches if row['account_key'] == preferred]
            if not chosen and data_action:
                chosen = [row for row in matches if row.get('data_provider')]
            if chosen:
                matches = chosen
        if len(matches) > 1 and bridge and not aid and not key and not action.startswith(('xttrader.', 'cftrader.')):
            if len({(row.get('mode', 'ctypes'), row.get('bridge_id')) for row in matches}) == 1:
                matches = matches[:1]  # Bridge status/data requests are not account selections.
        if len(matches) > 1:
            raise ValueError('ambiguous account route; specify account_key or bridge_id')
        if requested and rows and not matches:
            raise ValueError('no enabled account matches request')
        row = matches[0] if matches else {}
        mode = params.get('_center_transport_mode') or row.get('mode', 'ctypes')
        if mode not in ('ctypes', 'lite', 'lite_advanced', 'lttx'):
            raise ValueError('unknown bridge transport mode')
        bridge = normalize_bridge_id(bridge or row.get('bridge_id'))
        aid = aid or str(row.get('account_id') or config.get('default_account_id') or '')
        atype = str(row.get('account_type') or atype).upper()
        market_routes = row.get('market_bridges') or {}
        market = request_market(params)
        market_action = action in CFTRADER_BATCH_ACTIONS or action in (
            'xttrader.order_stock', 'xttrader.order_stock_async', 'xttrader.order_stock_batch',
            'xttrader.cancel_order_stock_sysid', 'xttrader.cancel_order_stock_sysid_async')
        if market_action and row.get('market_routing_enabled') and market and not any(
                child.get('bridge_id') == bridge for child in market_routes.values()):
            target = market_routes.get(market)
            if not target or not target.get('bridge_id') or target.get('enabled', True) is False:
                raise ValueError('no configured bridge for security market')
            bridge = normalize_bridge_id(target['bridge_id'])
        channel = params.get('_center_request_channel') or params.get('channel')
        if channel not in ('normal', 'trade') and channel:
            allowed = {value for item in config.get('bridges', {}).values()
                       for value in (item.get('channels') or {}).values()}
            allowed.update(channels_for_bridge(bridge).values())
            if channel not in allowed:
                raise ValueError('unknown bridge request channel')
        else:
            channel = channel or ('trade' if action.startswith(('xttrader.', 'cftrader.')) else 'normal')
            channel = channels_for_bridge(bridge)[channel]
        # Pipe trade endpoints can share the registration table while native
        # callback ownership belongs to the normal endpoint. Probe its state.
        if mode in ('ctypes', 'lite', 'lite_advanced') and action in (
                'xttrader.subscribe', 'xttrader.unsubscribe', 'cfquant.account_subscription_status'):
            channel = channels_for_bridge(bridge)['normal']
        return dict(bridge_id=bridge, account_id=aid, account_type=atype,
                    account_key=row.get('account_key', ''),
                    request_channel=channel, mode=mode,
                    market_routes={market: dict(bridge_id=child.get('bridge_id'), enabled=child.get('enabled', True))
                                   for market, child in market_routes.items()} if row.get('market_routing_enabled') and not any(
                        child.get('bridge_id') == bridge for child in market_routes.values()) else {},
                    event_channel=account_channel(bridge, aid, atype))

    def quote_source(self):
        explicit = os.environ.get('CFQUANT_QUOTE_BRIDGE_ID')
        if explicit:
            return normalize_bridge_id(explicit)
        return self.resolve('xtdata.subscribe_whole_quote', {})['bridge_id']

    def quote_route(self):
        explicit = os.environ.get('CFQUANT_QUOTE_BRIDGE_ID')
        return self.resolve('xtdata.subscribe_whole_quote', {'bridge_id': explicit} if explicit else {})


class _ReplyConnection:
    """PipeHub-compatible endpoint; publication uses LTtx's own send queue."""
    def __init__(self, center, client):
        self.center, self.client = center, client
        self.closed = False
        self.last_seen = time.monotonic()

    def write_frame(self, frame):
        self.last_seen = time.monotonic()
        envelope = loads_pipe_message(frame)
        self.center.publish('response', envelope['payload'], self.client)

    def close(self):
        self.closed = True


class _SubscriptionAdapter:
    def __init__(self, center):
        self.center = center
        self.clients = {}
        self.lock = threading.RLock()

    def prepare(self, spec):
        params = spec.get('params') or {}
        route = self.center.routes.resolve(spec['action'], params)
        route['request_channel'] = channels_for_bridge(route['bridge_id'])['normal']
        return dict(spec, route=route)

    def control(self, spec, **params):
        route = spec.get('route') or self.prepare(spec)['route']
        key = (route['mode'], route['request_channel'])
        with self.lock:
            client = self.clients.get(key)
            if client is None:
                if route['mode'] == 'lttx':
                    from .client import LTtxRpcClient
                    client = LTtxRpcClient(request_channel=key[1])
                else:
                    from .pipe_client import PipeRpcClient
                    client = PipeRpcClient(pipe_name=self.center.hub.pipe_name, request_channel=key[1])
                client.add_callback('__event__', self.on_event)
                self.clients[key] = client
        if 'spec_payload' in params:
            params['spec'] = params.pop('spec_payload')
        return client.request('cfquant.managed_subscription', params, timeout=12)

    def on_event(self, event):
        if event.get('event') == 'cfquant.managed_subscription':
            self.center.subscription_manager().on_event(event.get('data'))

    def emit(self, client, event, payload, subscription_id):
        self.center.publish('event', pack_event(event, payload, client, subscription_id), client)

    def close(self):
        for client in list(self.clients.values()):
            client.close()


class BridgeCenter:
    def __init__(self, hub, factory=None, routes=None):
        self.hub = hub
        self.routes = routes or CenterRoutes()
        self.factory = factory
        self.tx = None
        self.stop_event = threading.Event()
        self.thread = None
        self.executor = KeyedExecutor(workers=8, max_pending=1024, name='cfquant-center-query')
        self.trade_executor = KeyedExecutor(workers=8, max_pending=512, name='cfquant-center-trade')
        self.control_executor = KeyedExecutor(workers=2, max_pending=128, name='cfquant-center-control')
        self.service_queues = ServiceQueues()
        self.service_clients = {}
        self.clients = {}
        self.event_channels = set()
        self.legacy_clients = {}
        self.batch_clients = {}
        self.batch_last_seen = {}
        self.lock = threading.RLock()
        self.quote_batches = 0
        self.publication_failures = 0
        self.last_quote_at = 0
        self.error = ''
        self._subscriptions = None
        self._subscription_adapter = _SubscriptionAdapter(self)
        self.guard = _CenterGuard()

    def subscription_manager(self):
        with self.lock:
            if self._subscriptions is None:
                from .subscription_manager import SubscriptionManager
                from .subscription_store import SubscriptionStore
                runtime = Path(os.environ.get('CFQUANT_RUNTIME_DIR') or Path.cwd() / 'runtime')
                path = runtime / 'db/center-subscriptions.sqlite3'
                path.parent.mkdir(parents=True, exist_ok=True)
                self._subscriptions = SubscriptionManager(SubscriptionStore(path), self._subscription_adapter)
            return self._subscriptions

    def start(self):
        self.guard.acquire()
        self.thread = threading.Thread(target=self._run, name='cfquant-bridge-center', daemon=True)
        self.thread.start()

    def publish(self, key, payload, channel):
        tx = self.tx
        if tx is None:
            raise ConnectionError('LTtx bridge center disconnected')
        result = tx.push(key, payload, channel)
        if isinstance(result, dict) and result.get('code', 0) < 0:
            raise ConnectionError(result.get('msg'))

    def registry(self):
        config = self.routes.read()
        # Never publish credential-bearing bindings in discovery.
        accounts = {key: {name: row.get(name) for name in
                    ('account_id', 'account_type', 'bridge_id', 'mode', 'enabled', 'data_provider')}
                    for key, row in config.get('account_configs', {}).items()}
        return dict(schema='cfquant.lttx.registry', center_request_channel=CENTER_CHANNEL,
                    center=dict(enabled=True, pid=os.getpid()), accounts=accounts,
                    whole_quote_channel='all_gp_hq', updated_at=time.time(),
                    direct_fallback_transport='ctypes')

    def _run(self):
        from .client import _load_txl
        cfg = get_config()
        while not self.stop_event.is_set():
            tx = None
            try:
                tx = (self.factory or _load_txl())(cfg['host'], cfg['port'], cfg['token'], show=False)
                self.tx = tx  # close() can interrupt a connecting transport.
                tx.start_txg(CENTER_CHANNEL + '@cfquant.center.quotes')
                registered = 0
                while not self.stop_event.is_set():
                    if time.monotonic() - registered > 3:
                        tx.put('cfquant.center', self.registry())
                        registered = time.monotonic()
                        self.error = ''
                        self._reap_clients()
                        # Service readiness and queue telemetry must refresh
                        # even while QMT has no pipe traffic.
                        getattr(self.hub, '_write_status', lambda: None)()
                    try:
                        raw = tx.Q.get(timeout=.2)
                    except queue.Empty:
                        continue
                    msg = loads_message(raw)
                    if msg and msg.get('type') == 'event' and msg.get('event') == 'all_gp_hq':
                        data = msg.get('data') or {}
                        self.on_publish(dict(key='event', channel='all_gp_hq',
                            bridge_id=data.get('bridge_id'), payload=raw.split('|', 1)[-1]
                            if not raw.startswith('cfquant:') else raw))
                        continue
                    if not msg or msg.get('type') != 'request':
                        continue
                    client = msg.get('client_id') or msg.get('reply_channel')
                    if not client:
                        continue
                    def reject(error, message=msg):
                        self._reply(message, error=error)
                    self.enqueue(msg, reject)
            except Exception as error:
                self.error = str(error)
                self.hub._log('bridge center LTtx failed: %s' % error)
            finally:
                if tx is not None:
                    tx.close()
                self.tx = None
                getattr(self.hub, '_write_status', lambda: None)()
            self.stop_event.wait(1)

    def _reply(self, msg, result=None, error=None):
        self.publish('response', pack_response(msg.get('id'), ok=error is None, result=result, error=error),
                     msg.get('client_id') or msg.get('reply_channel'))

    def enqueue(self, msg, reject):
        entered = time.monotonic()
        action = str(msg.get('action') or '')
        def execute():
            remaining = float(msg.get('timeout') or 15) - (time.monotonic() - entered)
            if remaining <= 0:
                raise TimeoutError('request expired in center queue before execution')
            self.handle(dict(msg, timeout=remaining))
        try:
            if action in SERVICE_ACTIONS:
                self.service_queues.submit(msg, execute, reject)
            elif action in ('cfquant.ping', 'cfquant.center.route', 'cfquant.account_subscription_status'):
                self.control_executor.submit([msg.get('client_id')], execute, reject)
            elif action.startswith(('xttrader.', 'cftrader.')) and not action.startswith('xttrader.query_'):
                params = msg.get('params') or {}
                account = params.get('account') or {}
                key = (params.get('account_key') or account.get('account_key') or
                       params.get('account_id') or account.get('account_id') or 'default',
                       params.get('account_type') or account.get('account_type') or 'STOCK')
                self.trade_executor.submit([key], execute, reject)
            else:
                self.executor.submit([msg.get('client_id')], execute, reject)
        except Exception as error:
            reject(error)

    def _service_request(self, action, params, timeout):
        from .client import LTtxRpcClient
        lane = 'notification' if action == 'cfquant.notify.send' else 'algorithm'
        with self.lock:
            client = self.service_clients.get(lane)
            if client is None:
                client = self.service_clients[lane] = LTtxRpcClient(request_channel=SERVICE_CHANNEL)
        body = dict(params, _center_service_token=service_token())
        body.pop('_center_request_channel', None)
        return client.request(action, body, timeout=timeout)

    def _reap_clients(self):
        # A dead SDK must not leave one reply sender/thread per historical ID.
        # Outstanding requests and continuing event streams keep their routes.
        stale = []
        with self.lock:
            for key, client in list(self.batch_clients.items()):
                if time.monotonic() - self.batch_last_seen[key] > 900 and not client._pending:
                    self.batch_clients.pop(key).close()
                    self.batch_last_seen.pop(key, None)
            with self.hub.state_lock:
                busy = {row.get('conn') for row in self.hub.pending.values()}
            for client, endpoint in list(self.clients.items()):
                if endpoint not in busy and time.monotonic() - endpoint.last_seen > 900:
                    self.clients.pop(client, None)
                    stale.append(endpoint)
                    for key in list(self.legacy_clients):
                        if key[0] == client:
                            self.legacy_clients.pop(key).close()
        for endpoint in stale:
            endpoint.close()
            self.hub._drop_conn(endpoint)

    def handle(self, msg):
        try:
            action, params = msg.get('action', ''), dict(msg.get('params') or {})
            if action in SERVICE_ACTIONS:
                return self._reply(msg, self._service_request(action, params, float(msg.get('timeout') or 15)))
            if action == 'cfquant.subscriptions':
                return self._reply(msg, self.subscription_manager().handle(
                    params, msg.get('client_id') or msg.get('reply_channel')))
            if action in ('cfquant.registry', 'cfquant.discovery', 'cfquant.runtime', 'cfquant.ping'):
                return self._reply(msg, self.registry())
            route = self.routes.resolve(params.get('action', action) if action == 'cfquant.center.route' else action, params)
            if action == 'cfquant.center.route':
                return self._reply(msg, route)
            if action in CFTRADER_BATCH_ACTIONS and route['market_routes']:
                from .center_batch import route_batch
                result = route_batch(action, params, route['market_routes'],
                    lambda action, body, timeout: self._batch_request(msg, action, body, timeout),
                    float(msg.get('timeout') or 15))
                return self._reply(msg, result)
            if action == 'xttrader.order_stock_batch' and route['market_routes']:
                from .center_batch import route_legacy_batch
                result = route_legacy_batch(params, route['market_routes'],
                    lambda action, body, timeout: self._batch_request(msg, action, body, timeout),
                    float(msg.get('timeout') or 15))
                return self._reply(msg, result)
            if action == 'xttrader.unsubscribe':
                # Native account registration belongs to A, not one transient SDK.
                return self._reply(msg, 0)
            client = msg.get('client_id') or msg.get('reply_channel')
            with self.lock:
                endpoint = self.clients.get(client)
                if endpoint is None or endpoint.closed:
                    endpoint = self.clients[client] = _ReplyConnection(self, client)
                    self.hub._remember_client(endpoint, client, receive_conn=True)
                endpoint.last_seen = time.monotonic()
                if action in ('xttrader.subscribe', 'cfquant.account_subscription_status'):
                    self.event_channels.add(route['event_channel'])
            forward = dict(msg)
            params.pop('_center_request_channel', None)
            params.pop('_center_transport_mode', None)
            if action.startswith('qmt_inner.'):
                params['_inner_client_id'] = client
            if route['account_id'] and not params.get('account'):
                params.setdefault('account_id', route['account_id'])
                params.setdefault('account_type', route['account_type'])
            if action in ('xttrader.subscribe', 'cfquant.account_subscription_status'):
                forward['client_id'] = forward['reply_channel'] = route['event_channel']
                params['subscription_renewal'] = True
            forward['params'] = params
            if route['mode'] == 'lttx':
                from .client import LTtxRpcClient
                shared = action in ('xttrader.subscribe', 'cfquant.account_subscription_status')
                identity = route['event_channel'] if shared else client
                legacy_key = (identity, route['request_channel'])
                with self.lock:
                    upstream = self.legacy_clients.get(legacy_key)
                    if upstream is None:
                        upstream = LTtxRpcClient(client_id=identity if shared else 'center_' + identity + '_' +
                                                hashlib.sha256(route['request_channel'].encode()).hexdigest()[:12],
                                                request_channel=route['request_channel'])
                        if not shared:
                            upstream.add_callback('__event__', lambda event, target=client:
                                                  self.publish('event', dumps_message(event), target))
                        self.legacy_clients[legacy_key] = upstream
                result = upstream.request(action, params, timeout=float(msg.get('timeout') or 15))
                self._reply(msg, result=result)
                return
            self.hub._handle_api_request(endpoint, dict(payload=dumps_message(forward),
                client_id=client, request_channel=route['request_channel']))
        except Exception as error:
            self._reply(msg, error=error)

    def _batch_request(self, msg, action, params, timeout):
        route = self.routes.resolve(action, params)
        target = msg.get('client_id') or msg.get('reply_channel')
        key = (route['mode'], route['request_channel'], target)
        with self.lock:
            self.batch_last_seen[key] = time.monotonic()
            client = self.batch_clients.get(key)
            if client is None:
                identity = 'center-batch-' + target + '-' + hashlib.sha256(repr(key[:2]).encode()).hexdigest()[:12]
                options = dict(request_channel=route['request_channel'], client_id=identity)
                if route['mode'] == 'lttx':
                    from .client import LTtxRpcClient
                    client = LTtxRpcClient(**options)
                else:
                    from .pipe_client import PipeRpcClient
                    client = PipeRpcClient(pipe_name=self.hub.pipe_name, **options)
                client.add_callback('__event__', lambda event: self.publish('event', dumps_message(event), target))
                self.batch_clients[key] = client
        return client.request(action, {key: value for key, value in params.items()
                                      if not key.startswith('_center_')}, timeout=timeout)

    def on_publish(self, envelope):
        if envelope.get('key') != 'event':
            return False
        channel = envelope.get('channel')
        if channel == 'all_gp_hq':
            if normalize_bridge_id(envelope.get('bridge_id')) != self.routes.quote_source():
                return True
            try:
                self.publish('quote', envelope['payload'], 'all_gp_hq')
            except Exception:
                self.publication_failures += 1
                raise
            self.quote_batches += 1
            self.last_quote_at = time.time()
            return True
        if isinstance(channel, str) and channel.startswith('cfquant.account.'):
            # QMT may retain A's account registration across an A restart.
            # The channel is a routing identity, not an authorization boundary.
            self.publish('event', envelope['payload'], channel)
            return True
        if channel == channels_for_bridge(envelope.get('bridge_id'))['callback']:
            self.publish('event', envelope['payload'], channel)
            # Preserve explicit legacy pipe listeners during migration.
            return False
        return False

    def status(self):
        tx = self.tx
        return dict(running=not self.stop_event.is_set(),
                    connected=bool(tx and tx.tx_running and
                                   (tx.txg_dict.get(CENTER_CHANNEL) or {}).get('txg_running')),
                    quote_batches=self.quote_batches, last_quote_at=self.last_quote_at,
                    publication_failures=self.publication_failures, error=self.error,
                    send_queue=tx.tx_que.qsize() if tx else 0,
                    requests=self.executor.status(), event_channels=len(self.event_channels),
                    trade_requests=self.trade_executor.status(), control_requests=self.control_executor.status(),
                    service_requests=self.service_queues.status(),
                    services=self.hub.services.status() if getattr(self.hub, 'services', None) else None,
                    reply_clients=len(self.clients))

    def close(self):
        self.stop_event.set()
        if self.tx:
            self.tx.close()
        self.executor.close()
        self.trade_executor.close()
        self.control_executor.close()
        self.service_queues.close()
        for client in list(self.service_clients.values()):
            client.close()
        if self._subscriptions is not None:
            self._subscriptions.close()
        self._subscription_adapter.close()
        for client in list(self.legacy_clients.values()):
            client.close()
        for client in list(self.batch_clients.values()):
            client.close()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.guard.close()
