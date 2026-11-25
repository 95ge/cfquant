"""Center contracts and actual LTtx fan-out, without Web or a trading terminal."""
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from cfquant.bridge_center import BridgeCenter, CenterRoutes, account_channel
from cfquant.market_channel import ChannelSubscription
from cfquant.protocol import loads_message, pack_request, pack_quote_latency_event, pack_response, pack_event


def eventually(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    assert predicate()


def test_route_reload_ambiguity_and_secret_free_registry(tmp_path):
    path = tmp_path / 'routes.json'
    path.write_text(json.dumps(dict(account_configs={'one': dict(account_id='100', bridge_id='b', password='secret')})))
    routes = CenterRoutes(path)
    assert routes.resolve('xttrader.subscribe', {'account_id': '100'})['bridge_id'] == 'b'
    center = BridgeCenter(SimpleNamespace(), routes=routes)
    assert 'secret' not in json.dumps(center.registry())
    path.write_text(json.dumps(dict(account_configs={
        'one': dict(account_id='100', bridge_id='b'), 'two': dict(account_id='200', bridge_id='c')})))
    with pytest.raises(ValueError, match='ambiguous'):
        routes.quote_source()
    assert routes.resolve('xttrader.query_stock_asset', {'account_id': '200'})['bridge_id'] == 'c'
    assert account_channel('b', '100', 'STOCK') != account_channel('b', '100', 'CREDIT')
    center.close()


def test_routes_preserve_market_account_mode_and_provider(tmp_path, monkeypatch):
    path = tmp_path / 'routes.json'
    path.write_text(json.dumps(dict(data_provider_account_key='one', account_configs={
        'one': dict(account_id='100', account_type='CREDIT', bridge_id='parent', mode='lite_advanced',
                    market_routing_enabled=True, market_bridges={
                        'SH': dict(bridge_id='sh'), 'SZ': dict(bridge_id='sz')})})))
    routes = CenterRoutes(path)
    assert routes.resolve('qmt_inner.get_full_tick', {})['bridge_id'] == 'parent'
    params = dict(account_id='100', account_type=3)
    assert routes.resolve('xttrader.subscribe', params)['request_channel'] == 'cfquant.parent.normal.request'
    assert routes.resolve('xttrader.order_stock', dict(params, stock_code='600000.SH'))['bridge_id'] == 'sh'
    assert routes.resolve('xtdata.get_instrument_detail', dict(params, stock_code='600000.SH'))['bridge_id'] == 'parent'
    assert routes.resolve('xttrader.cancel_order_stock_sysid', dict(params, market=0))['bridge_id'] == 'sh'
    assert routes.resolve('xttrader.query_stock_asset', dict(params, bridge_id='sz'))['bridge_id'] == 'sz'
    assert routes.resolve('xttrader.subscribe', dict(params, _center_transport_mode='ctypes'))['mode'] == 'ctypes'
    monkeypatch.setenv('CFQUANT_QUOTE_BRIDGE_ID', 'sz')
    assert routes.quote_source() == routes.quote_route()['bridge_id'] == 'sz'


@pytest.mark.parametrize('mode', ['ctypes', 'lite', 'lite_advanced'])
@pytest.mark.parametrize('action', ['xttrader.subscribe', 'xttrader.unsubscribe', 'cfquant.account_subscription_status'])
def test_account_control_uses_native_callback_owner(tmp_path, mode, action):
    path = tmp_path / 'routes.json'
    path.write_text(json.dumps(dict(account_configs={
        'test': dict(account_id='TEST', account_type='STOCK', bridge_id='b', mode=mode)})))
    route = CenterRoutes(path).resolve(action, dict(account_id='TEST', _center_request_channel='cfquant.b.trade.request'))
    assert route['request_channel'] == 'cfquant.b.normal.request'


def test_sdk_probe_uses_callback_owner_with_older_center(monkeypatch):
    from cfquant.center_client import CenterRpcClient
    from cfquant.client import WebLttxRpcClient
    calls = []
    def request(self, action, params=None, **kwargs):
        calls.append((action, params))
        if action == 'cfquant.center.route':
            return dict(mode='lite', request_channel='cfquant.b.trade.request', event_channel='account-test')
        return dict(subscribed=params['_center_request_channel'] == 'normal')
    monkeypatch.setattr(WebLttxRpcClient, 'request', request)
    client = CenterRpcClient(request_channel='cfquant.b.trade.request')
    try:
        assert client.request('cfquant.account_subscription_status', {'account_id': 'TEST'}) == {'subscribed': True}
        assert len(calls) == 2
    finally:
        client.close()


@pytest.mark.parametrize('asynchronous', [False, True])
def test_center_batches_route_in_order_and_do_not_retry_unknown_writes(asynchronous):
    from cfquant.center_batch import route_batch
    from cfquant.batch_orders import prepare_batch_orders, batch_result_rows, batch_result
    from cfquant.client import CfquantTimeout
    params = dict(account=dict(account_id='TEST', account_type='STOCK'), batch_id='test',
                  orders=prepare_batch_orders([dict(stock_code=code, order_type=23, order_volume=100,
                                                    price_type=11, price=10.0)
                    for code in ('600000.SH', '000001.SZ', '600001.SH')], 'test'),
                  seqs=[10, 11, 12] if asynchronous else [])
    calls = []
    def request(action, body, timeout):
        calls.append(body)
        rows = batch_result_rows(body['orders'], body['seqs'] if asynchronous else None)
        for row in rows:
            row.update(status='submitted', ok=True, order_id=None if asynchronous else 1000 + len(calls))
        return batch_result(body['account'], body['batch_id'], asynchronous, rows)
    routes = dict(SH=dict(bridge_id='sh'), SZ=dict(bridge_id='sz'))
    action = 'cftrader.order_stock_batch' + ('_async' if asynchronous else '')
    result = route_batch(action, params, routes, request, 10)
    assert result['submitted'] == 3
    assert [body['bridge_id'] for body in calls] == ['sh', 'sz', 'sh']
    assert [row['index'] for row in result['results']] == [0, 1, 2]
    if asynchronous:
        assert [body['seqs'] for body in calls] == [[10], [11], [12]]
    calls.clear()
    def uncertain(*args):
        calls.append(args)
        raise CfquantTimeout('response lost')
    result = route_batch(action, params, routes, uncertain, 10)
    assert len(calls) == 1 and result['unknown'] == 1 and result['skipped'] == 2


def test_web_default_callback_listener_uses_only_lttx(monkeypatch):
    import cfquant_web_server as web
    from cfquant.tests.test_callback_recovery import MemoryTx
    tx = MemoryTx()
    monkeypatch.setattr(web, 'lttx_server_reachable', lambda: True)
    monkeypatch.setattr(web, 'txl', lambda *a, **kw: tx)
    store = web.CallbackEventStore(['cfquant.test.callback.event'], retry_interval=.02)
    monkeypatch.setattr(store, '_start_pipe_clients', lambda *a: pytest.fail('Web connected directly to QMT pipe'))
    rows = []
    monkeypatch.setattr(store, '_append', lambda event, source='client': rows.append(event))
    try:
        store.start()
        eventually(lambda: tx.channels is not None)
        tx.Q.put(pack_event('trader:on_stock_asset', {'account_id': 'TEST'}))
        eventually(lambda: len(rows) == 1)
        assert store._pipe_clients == {} and store._mode == 'lttx'
    finally:
        store.close()


class FakeTx:
    def __init__(self, *args, **kwargs):
        self.Q = queue.Queue()
    def start_txg(self, channel):
        self.channel = channel
    def close(self):
        self.Q.put(None)


def batch(number):
    return pack_quote_latency_event('all_gp_hq', dict(schema='cfquant.quote_latency.v1',
        qmt_callback_at_ms=number, quotes={'000001.SZ': {'time': number}, '600000.SH': {'time': number}}), 'all_gp_hq')


def test_callbacks_independent_ordered_and_never_spooled(monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, 'TemporaryFile', lambda *a, **kw: pytest.fail('market data spooled'))
    blocked, entered = threading.Event(), threading.Event()
    slow_rows, fast_rows, trade_rows = [], [], []
    def slow(data):
        entered.set()
        blocked.wait(3)
        slow_rows.append(data['000001.SZ']['time'])
    slow_sub = ChannelSubscription(slow, ['SZ'], factory=FakeTx).start()
    fast_sub = ChannelSubscription(lambda d: fast_rows.append(d['600000.SH']['time']), ['SH'], factory=FakeTx).start()
    trade = ChannelSubscription(trade_rows.append, channel='account-test', event=True, factory=FakeTx).start()
    try:
        for n in range(50):
            slow_sub.tx.Q.put(batch(n))
            fast_sub.tx.Q.put(batch(n))
        assert entered.wait(1)
        trade.tx.Q.put(pack_event('trader:on_stock_order', {'order_id': 'fixture'}))
        eventually(lambda: len(fast_rows) == 50 and len(trade_rows) == 1)
        assert fast_rows == list(range(50))
        assert not slow_rows
        assert slow_sub.status()['queued_callbacks'] == 49
        assert slow_sub.status()['estimated_memory_bytes'] > 0
        assert slow_sub.status()['oldest_age_ms'] > 0
        assert slow_sub.status()['spooled_bytes'] == 0
        blocked.set()
        eventually(lambda: len(slow_rows) == 50)
        assert slow_rows == list(range(50))
    finally:
        blocked.set()
        for sub in (slow_sub, fast_sub, trade):
            sub.close()
            assert sub.status()['queued_callbacks'] == 0


def test_center_source_filter_and_account_recovery(tmp_path):
    routes = CenterRoutes(tmp_path / 'absent.json')
    center = BridgeCenter(SimpleNamespace(), routes=routes)
    publications = []
    center.publish = lambda *args: publications.append(args)
    try:
        assert center.on_publish(dict(key='event', channel='all_gp_hq', bridge_id='other', payload=batch(0)))
        assert publications == []
        payload = batch(1)
        assert center.on_publish(dict(key='event', channel='all_gp_hq', bridge_id='default', payload=payload))
        channel = account_channel('default', 'TEST', 'STOCK')
        # Registrations in QMT survive A restarting; no SDK RPC is necessary to publish.
        assert center.on_publish(dict(key='event', channel=channel, payload='account-event'))
        assert publications == [('quote', payload, 'all_gp_hq'), ('event', 'account-event', channel)]
    finally:
        center.close()


def test_auto_discovery_prefers_live_independent_center(monkeypatch):
    from cfquant import client
    from cfquant.center_client import CenterRpcClient
    registry = dict(center={'enabled': True}, updated_at=time.time())
    monkeypatch.setattr(client, 'load_lttx_registry', lambda cfg=None, key=None: registry if key else {})
    rpc = client.create_rpc_client(transport='auto')
    assert isinstance(rpc, CenterRpcClient)
    assert rpc.request_channel == 'cfquant.center.request'
    rpc.close()
    registry['updated_at'] = 0
    from cfquant.pipe_client import PipeRpcClient
    rpc = client.create_rpc_client(transport='auto')
    assert isinstance(rpc, PipeRpcClient)
    rpc.close()


def test_legacy_qmt_starts_quote_publisher_without_external_subscription():
    from cfquant.qmt_bridge import CfquantQmtBridge
    native, sent = [], []
    def subscribe(codes, callback):
        native.append((codes, callback))
        return 10
    bridge = CfquantQmtBridge(SimpleNamespace(subscribe_whole_quote=subscribe), show=False)
    bridge.bridge_id = 'legacy-source'
    bridge._log = lambda *args: None
    bridge.tx = SimpleNamespace(push=lambda *args: sent.append(args))
    try:
        bridge.poll()
        assert len(native) == 1
        native[0][1]({'000001.SZ': {'lastPrice': 1}})
        assert sent[0][2] == 'cfquant.center.quotes'
        assert loads_message(sent[0][1])['data']['bridge_id'] == 'legacy-source'
        bridge.poll()
        assert len(native) == 1
    finally:
        bridge.close()


@pytest.fixture
def broker(tmp_path, monkeypatch):
    # A real isolated LTtx broker, never the user's service or accounts.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    from cfquant.config import _config
    monkeypatch.setitem(_config, 'port', port)
    monkeypatch.setitem(_config, 'host', '127.0.0.1')
    monkeypatch.setitem(_config, 'token', 'LTtx')
    monkeypatch.setenv('CFQUANT_TX_LOG_DIR', str(tmp_path / 'logs'))
    env = dict(os.environ, CFQUANT_LTTX_PORT=str(port), CFQUANT_LTTX_BACKGROUND='1',
               CFQUANT_HOME=str(tmp_path), CFQUANT_LTTX_RUNTIME_DIR=str(tmp_path / 'runtime'))
    entry = Path(__file__).resolve().parents[2] / 'LTtx/tx/LTtx_server.py'
    process = subprocess.Popen([sys.executable, '-B', str(entry)], env=env, cwd=tmp_path,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    def ready():
        with socket.socket() as sock:
            sock.settimeout(.1)
            return sock.connect_ex(('127.0.0.1', port)) == 0
    try:
        eventually(ready, 15)
        yield port
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows named pipes')
def test_real_pipe_center_lttx_fanout_requests_and_trade(broker, tmp_path, monkeypatch):
    from cfquant.pipe_hub import CfquantPipeHub
    from cfquant.pipe_transport import PipeTxClient
    from cfquant.center_client import CenterRpcClient
    from cfquant.client import _load_txl
    monkeypatch.setenv('CFQUANT_RUNTIME_DIR', str(tmp_path))
    pipe = r'\\.\pipe\cfquant-center-test-' + uuid.uuid4().hex
    hub = CfquantPipeHub(pipe_name=pipe, show=False)
    hub_thread = threading.Thread(target=hub.start, daemon=True)
    hub_thread.start()
    qmt = PipeTxClient(pipe_name=pipe, request_channels=['cfquant.normal.request', 'cfquant.trade.request'],
                       bridge_id='default', show=False)
    stop = threading.Event()
    client1 = CenterRpcClient(client_id='fixture-one')
    client2 = CenterRpcClient(client_id='fixture-two')
    quotes1, quotes2, events1, events2, registrations = [], [], [], [], set()
    raw_tx = _load_txl()('127.0.0.1', broker, 'LTtx', show=False)
    sub1 = sub2 = None
    try:
        qmt.start()
        eventually(lambda: hub.center is not None and hub.center.tx is not None)
        # Probe through LTtx; no Web module/process participates.
        eventually(lambda: bool(hub.center.tx.txg))
        assert hub.center.status()['connected']
        def respond():
            while not stop.is_set():
                try:
                    raw = qmt.Q.get(timeout=.1)
                except queue.Empty:
                    continue
                msg = loads_message(raw)
                if not msg:
                    continue
                if msg['action'] == 'xttrader.subscribe':
                    registrations.add(msg['client_id'])
                qmt.push('response', pack_response(msg['id'], result=0 if msg['action'] == 'xttrader.subscribe' else {'ok': True}), msg['client_id'])
        threading.Thread(target=respond, daemon=True).start()
        client1.add_callback('__event__', events1.append)
        client2.add_callback('__event__', events2.append)
        assert client1.request('xttrader.subscribe', {'account_id': 'TEST'}) == 0
        assert client2.request('xttrader.subscribe', {'account_id': 'TEST'}) == 0
        assert len(registrations) == 1
        sub1 = ChannelSubscription(quotes1.append).start()
        sub2 = ChannelSubscription(quotes2.append).start()
        assert sub1.status()['connected'] and sub2.status()['connected']
        raw_tx.start_txg('all_gp_hq')
        for n in range(10):
            qmt.push('event', batch(n), 'all_gp_hq')
        channel = next(iter(registrations))
        qmt.push('event', pack_event('trader:on_stock_order', {'order_id': 'fixture'}, channel), channel)
        eventually(lambda: len(quotes1) == len(quotes2) == 10 and len(events1) == len(events2) == 1)
        assert [row['000001.SZ']['time'] for row in quotes1] == list(range(10))
        assert [loads_message(raw_tx.Q.get(timeout=3))['data']['quotes']['000001.SZ']['time']
                for _ in range(10)] == list(range(10))
        assert client1.request('xtdata.get_full_tick', {}) == {'ok': True}
        client1.request('xttrader.unsubscribe', {'account_id': 'TEST'})
        qmt.push('event', pack_event('trader:on_stock_trade', {'trade_id': 'fixture'}, channel), channel)
        eventually(lambda: len(events2) == 2)
        assert len(events1) == 1
    finally:
        stop.set()
        for item in (sub1, sub2, raw_tx, client1, client2, qmt, hub):
            if item:
                item.close()
        hub_thread.join(timeout=2)


@pytest.mark.skipif(os.name != 'nt', reason='Windows center singleton')
def test_duplicate_center_rejected_and_guard_released(broker):
    from cfquant.bridge_center import _CenterGuard
    first, second = _CenterGuard(), _CenterGuard()
    try:
        first.acquire()
        with pytest.raises(RuntimeError, match='another bridge center'):
            second.acquire()
        first.close()
        second.acquire()
    finally:
        first.close()
        second.close()
