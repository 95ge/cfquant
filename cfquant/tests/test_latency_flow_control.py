"""Offline regression of overload, isolation and compatibility; no live orders."""
import json
import os
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from cfquant import protocol
from cfquant.callback_dispatcher import CallbackDispatcher
from cfquant.flow_control import KeyedExecutor, OrderedSender
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.pipe_hub import CfquantPipeHub
from cfquant.pipe_transport import PipeTxClient, loads_pipe_message
from cfquant.pipe_transport import create_pipe_instance, connect_pipe, wait_for_pipe_client
from cfquant.quote_history import QuoteHistory
import cfquant_web_server as web


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'background work did not finish'
        threading.Event().wait(.005)


class Connection:
    def __init__(self, block=False):
        self.entered, self.release = threading.Event(), threading.Event()
        if not block:
            self.release.set()
        self.frames = []
        self.closed = False

    def write_frame(self, data):
        self.entered.set()
        assert self.release.wait(3)
        if self.closed:
            raise OSError('closed test connection')
        self.frames.append(data)

    sendall = write_frame

    def shutdown(self, *args):
        self.close()

    def close(self):
        self.closed = True
        self.release.set()


def test_sender_fifo_and_overflow_are_explicit_and_never_replayed():
    slow, fast = Connection(True), Connection()
    errors = []
    def failed(error):
        errors.append(error)
        slow.close()
    sender = OrderedSender(slow.write_frame, failed, max_items=2, max_bytes=100)
    independent = OrderedSender(fast.write_frame, lambda e: pytest.fail(str(e)))
    try:
        sender.submit(b'first')
        assert slow.entered.wait(2)
        sender.submit(b'second')
        independent.submit(b'other-client')
        eventually(lambda: fast.frames)
        assert not slow.frames
        with pytest.raises(BufferError):
            sender.submit(b'third')
        sender._thread.join(2)
        assert len(errors) == 1 and slow.closed
        assert not slow.frames
        assert sender.status()['buffered_bytes'] == 0
        with pytest.raises(RuntimeError):
            sender.submit(b'retry')
    finally:
        slow.close()
        sender.close()
        independent.close()


def test_sender_sends_all_frames_in_order_and_reports_queue():
    conn = Connection(True)
    sender = OrderedSender(conn.write_frame, lambda e: pytest.fail(str(e)))
    try:
        for i in range(100):
            sender.submit(str(i).encode())
        assert conn.entered.wait(2)
        assert sender.status()['queued_frames'] == 99
        conn.release.set()
        eventually(lambda: sender.status()['sent_frames'] == 100)
        assert conn.frames == [str(i).encode() for i in range(100)]
        assert sender.status()['buffered_bytes'] == 0
    finally:
        sender.close()


def test_keyed_executor_preserves_client_and_account_order_without_global_blocking():
    pool = KeyedExecutor(workers=4)
    entered, release, unrelated = threading.Event(), threading.Event(), threading.Event()
    calls, errors = [], []
    def first():
        calls.append('first')
        entered.set()
        assert release.wait(3)
    try:
        pool.submit(['client-a', 'account-1'], first, errors.append)
        assert entered.wait(2)
        pool.submit(['client-b', 'account-1'], lambda: calls.append('second'), errors.append)
        # This must not overtake second even though its account is different.
        pool.submit(['client-b', 'account-2'], lambda: calls.append('third'), errors.append)
        pool.submit(['client-c', 'account-3'], unrelated.set, errors.append)
        assert unrelated.wait(2)
        assert calls == ['first']
        release.set()
        eventually(lambda: len(calls) == 3)
        assert calls == ['first', 'second', 'third'] and not errors
    finally:
        release.set()
        pool.close()


def test_executor_close_rejects_pending_without_execution():
    pool = KeyedExecutor(workers=1, max_pending=1)
    entered, release = threading.Event(), threading.Event()
    calls, rejected = [], []
    def first():
        entered.set()
        release.wait(3)
    pool.submit(['a'], first, rejected.append)
    assert entered.wait(2)
    pool.submit(['a'], lambda: calls.append('unstarted'), rejected.append)
    with pytest.raises(BufferError):
        pool.submit(['b'], lambda: None, rejected.append)
    pool.close()
    release.set()
    assert not calls and len(rejected) == 1


def test_pipe_sender_freezes_payload_and_drops_old_connection_queue():
    client = PipeTxClient(show=False)
    old, new = Connection(True), Connection()
    client.tx_conn = old
    client.connection_generation = 1
    source = {'A': {'lastPrice': 10}}
    raw = protocol.pack_whole_quote_event('quote:test', source)
    assert client.push('event', raw, 'a')['code'] == 0
    assert old.entered.wait(2)
    client.push('event', raw, 'a')
    source['A']['lastPrice'] = 99
    client._drop_pair(1, conns=(old,))
    client.tx_conn = new
    client.connection_generation = 2
    try:
        client.push('event', raw, 'a')
        eventually(lambda: new.frames)
        assert not old.frames
        envelope = loads_pipe_message(new.frames[0])
        assert envelope['event_passthrough'] is True
        assert protocol.loads_message(envelope['payload'])['data']['A']['lastPrice'] == 10
        assert len(new.frames) == 1
    finally:
        client.close()


def test_hub_fast_event_does_not_parse_inner_json_or_block_other_recipient(monkeypatch):
    hub = CfquantPipeHub(show=False)
    slow, fast = Connection(True), Connection()
    hub._remember_client(slow, 'slow')
    hub._remember_client(fast, 'fast')
    monkeypatch.setattr('cfquant.pipe_hub.loads_message', lambda raw: pytest.fail('inner JSON parsed'))
    raw = protocol.pack_whole_quote_event('quote:all', {'SH': {'volume': 2**63 + 1}})
    try:
        hub._handle_qmt_publish(None, {'key': 'event', 'event_passthrough': True, 'channel': 'slow', 'payload': raw})
        assert slow.entered.wait(2)
        hub._handle_qmt_publish(None, {'key': 'event', 'event_passthrough': True, 'channel': 'fast', 'payload': raw})
        eventually(lambda: fast.frames)
        assert loads_pipe_message(fast.frames[0])['payload'] == raw
        assert not slow.frames
    finally:
        hub.close()


def test_hub_status_coalesces_and_replaces_valid_json(tmp_path, monkeypatch):
    hub = CfquantPipeHub(show=False)
    hub.status_file = str(tmp_path / 'hub.json')
    hub.status_interval = .05
    hub.running = True
    writes = []
    original = hub._persist_status
    def persist():
        writes.append(threading.get_ident())
        original()
    monkeypatch.setattr(hub, '_persist_status', persist)
    try:
        for _ in range(100):
            hub._write_status()
        eventually(lambda: (tmp_path / 'hub.json').exists())
        assert json.loads((tmp_path / 'hub.json').read_text())['running'] is True
        assert len(writes) < 10
        assert all(t != threading.get_ident() for t in writes)
        assert 'send_queues' in hub.status()
    finally:
        hub.close()
    assert json.loads((tmp_path / 'hub.json').read_text())['running'] is False


def test_hub_stalled_sender_is_closed_by_watchdog(tmp_path):
    hub = CfquantPipeHub(show=False)
    hub.status_file = str(tmp_path / 'hub.json')
    hub.status_interval, hub.send_timeout = .05, .05
    slow = Connection(True)
    hub.running = True
    hub._remember_client(slow, 'slow')
    try:
        hub._send_delivery(slow, 'frozen')
        hub._write_status()
        eventually(lambda: slow.closed)
        assert hub._client_rx_conn('slow') is None
    finally:
        hub.close()


def test_hub_shutdown_and_background_status_do_not_share_temporary_file(tmp_path, monkeypatch):
    hub = CfquantPipeHub(show=False)
    hub.status_file = str(tmp_path / 'status.json')
    barrier = threading.Barrier(2)
    original, paths = json.dump, []
    def write(value, stream, **kwargs):
        paths.append(stream.name)
        barrier.wait(timeout=2)
        return original(value, stream, **kwargs)
    monkeypatch.setattr('cfquant.pipe_hub.json.dump', write)
    threads = [threading.Thread(target=hub._persist_status) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert len(set(paths)) == 2
    assert json.loads((tmp_path / 'status.json').read_text())['running'] is False
    assert list(tmp_path.iterdir()) == [tmp_path / 'status.json']


@pytest.mark.skipif(os.name != 'nt', reason='Windows named pipes')
@pytest.mark.parametrize('owner', ['hub', 'qmt'])
def test_actual_windows_blocked_pipe_can_be_cancelled_by_sender_watchdog(owner, tmp_path):
    # Unique local test pipe, unrelated to configured Hub or live QMT.
    name = 'cfquant-offline-latency-' + uuid.uuid4().hex
    server = create_pipe_instance(name)
    connected = threading.Event()
    def accept():
        wait_for_pipe_client(server)
        connected.set()
    accept_thread = threading.Thread(target=accept, daemon=True)
    accept_thread.start()
    client = connect_pipe(name)
    assert connected.wait(2)
    process = None
    try:
        if owner == 'hub':
            process = CfquantPipeHub(show=False)
            process.status_file = str(tmp_path / 'hub.json')
            process.status_interval, process.send_timeout = .05, .05
            process.running = True
            process._remember_client(server, 'test')
            process._send_delivery(server, 'x' * 1000000)
            sender = process._senders[server]
            process._write_status()
            target = server
        else:
            process = PipeTxClient(show=False, heartbeat_interval=0)
            process.tx_conn, process.connection_generation = client, 1
            process.running, process.send_timeout = True, .05
            process.push('event', 'x' * 1000000, 'test')
            sender = process._sender
            process.heartbeat_thread = threading.Thread(target=process._heartbeat_loop, daemon=True)
            process.heartbeat_thread.start()
            target = client
        eventually(lambda: sender.status()['sending'])
        eventually(lambda: target.closed)
        sender._thread.join(2)
        assert not sender._thread.is_alive()
    finally:
        server.close()
        client.close()
        if process is not None:
            process.close()


def test_quote_history_spill_compaction_filter_and_clear_keep_exact_values():
    history = QuoteHistory(max_events=4, memory_bytes=200)
    expected = []
    for seq in range(20):
        event = {'seq': seq, 'subscribe_id': str(seq % 2), 'data': {'name': '测试', 'large': 2**63 + seq, 'rows': 'x' * 200000}}
        expected.append(event)
        history.append(event, json.dumps({'event': event}, ensure_ascii=False).encode())
        assert history.status()['memory_bytes'] <= 200
    assert history.latest(since=0, limit=4) == expected[-4:]
    assert history.latest(since=16, subscribe_id='1') == expected[17::2]
    status = history.status()
    assert status['disk_bytes'] <= 1024 * 1024 + status['disk_live_bytes'] * 2
    history.clear('1')
    assert history.latest(since=0) == [expected[16], expected[18]]
    history.clear()
    assert len(history) == 0 and history.status()['disk_bytes'] == 0 and history._file is None


def test_callback_backlog_spills_without_losing_order_and_closes_tempfile(monkeypatch):
    monkeypatch.setenv('CFQUANT_CALLBACK_MEMORY_BYTES', '500')
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    delivered = []
    def callback(msg):
        delivered.append(msg['data'])
        if msg['data'] == 0:
            entered.set()
            assert release.wait(3)
        if msg['data'] == 30:
            done.set()
    dispatcher = CallbackDispatcher(callback)
    gen = dispatcher.start()
    try:
        dispatcher.submit(gen, {'type': 'event', 'event': 'test', 'data': 0})
        assert entered.wait(2)
        for i in range(1, 31):
            raw = protocol.pack_event('test', i)
            dispatcher.submit(gen, protocol.loads_message(raw), raw)
        assert dispatcher.status()['spooled_bytes'] > 0
        assert dispatcher.status()['queued_callbacks'] == 30
        release.set()
        assert done.wait(3)
        assert delivered == list(range(31))
        assert dispatcher.status()['spooled_bytes'] == 0
        assert dispatcher._spool is None
    finally:
        release.set()
        dispatcher.stop()


def test_single_large_callback_needs_no_disk(monkeypatch):
    monkeypatch.setenv('CFQUANT_CALLBACK_MEMORY_BYTES', '1')
    monkeypatch.setattr('cfquant.callback_dispatcher.tempfile.TemporaryFile', lambda **kw: pytest.fail('no backlog'))
    done = threading.Event()
    dispatcher = CallbackDispatcher(lambda msg: done.set())
    generation = dispatcher.start()
    try:
        dispatcher.submit(generation, {'type': 'event', 'event': 'test', 'data': 'x' * 100000})
        assert done.wait(2)
    finally:
        dispatcher.stop()


def test_callback_spool_decode_failure_is_explicit_and_generation_scoped(monkeypatch):
    monkeypatch.setenv('CFQUANT_CALLBACK_MEMORY_BYTES', '1')
    entered, release, failed = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def callback(msg):
        entered.set()
        release.wait(3)
    def failure(error, generation):
        errors.append((str(error), generation))
        failed.set()
    dispatcher = CallbackDispatcher(callback, failure)
    generation = dispatcher.start()
    try:
        dispatcher.submit(generation, {'type': 'event', 'data': 0})
        assert entered.wait(2)
        for i in (1, 2):
            dispatcher.submit(generation, {'type': 'event', 'data': i}, raw='corrupt wire data')
        release.set()
        assert failed.wait(2)
        assert errors == [('invalid preserved callback message', generation)]
        assert not dispatcher._active and dispatcher._spool is None
    finally:
        release.set()
        dispatcher.stop()


def test_quote_history_failure_is_visible_but_live_broadcast_continues(monkeypatch):
    sent = []
    store = web.QuoteSubscriptionStore(manager=SimpleNamespace(count=lambda: 1, broadcast=lambda event: sent.append(event)))
    store._subscriptions['7'] = {}
    monkeypatch.setattr(store._events, 'append', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    store._on_quote({'subscription_id': 7, 'data': {'600000.SH': {'lastPrice': 10}}})
    store._on_quote({'subscription_id': 7, 'data': {'600000.SH': {'lastPrice': 11}}})
    assert len(sent) == 2 and store.status()['history_error'] == 'disk full'
    with pytest.raises(OSError, match='history unavailable'):
        store.latest()
    store.close()


def test_plain_quote_web_history_and_broadcast_share_encoding_without_recursive_walk(monkeypatch):
    sent = []
    manager = SimpleNamespace(count=lambda: 1, broadcast_encoded=lambda event, raw: sent.append(raw))
    store = web.QuoteSubscriptionStore(manager=manager)
    store._subscriptions['7'] = {}
    msg = protocol.loads_message(protocol.pack_whole_quote_event('quote:7', {'600000.SH': {'volume': 2**63 + 1}}, subscription_id=7))
    monkeypatch.setattr(web, 'to_jsonable', lambda value: pytest.fail('plain JSON walked again'))
    try:
        store._on_quote(msg)
        assert json.loads(sent[0])['event'] == store.latest()[0]
        assert store.latest()[0]['data']['600000.SH']['volume'] == 2**63 + 1
    finally:
        store.close()


def test_http_response_converts_once_and_preserves_unusual_values(monkeypatch):
    import numpy as np
    original = web.to_jsonable
    payload = web.ok({'data': [np.int64(3), float('nan'), b'hello'], 'timing': {}})
    expected = json.loads(json.dumps(original(payload)))
    monkeypatch.setattr(web, 'to_jsonable', lambda value: pytest.fail('second recursive conversion'))
    assert json.loads(web.web_json_bytes(payload)) == expected
    monkeypatch.setattr(web, 'to_jsonable', original)
    payload['added'] = np.int64(5)
    assert json.loads(web.web_json_bytes(payload))['added'] == 5


def test_websocket_broadcast_encodes_once_and_slow_client_is_independent(monkeypatch):
    manager = web.WebSocketCallbackManager()
    slow, fast = Connection(True), Connection()
    clients = [web.WebSocketCallbackClient(sock) for sock in (slow, fast)]
    counts = []
    original = web.web_json_bytes
    def encode(value):
        counts.append(value)
        return original(value)
    monkeypatch.setattr(web, 'web_json_bytes', encode)
    for client in clients:
        manager.add(client)
    try:
        manager.broadcast({'event': 'trader:on_stock_trade', 'data': {'order_id': 42}})
        eventually(lambda: fast.frames)
        assert slow.entered.wait(2) and not slow.frames
        assert len(counts) == 1
        slow.release.set()
        eventually(lambda: slow.frames)
        assert slow.frames == fast.frames
    finally:
        for client in clients:
            client.close()


def test_web_route_parallel_clients_and_expired_query_not_order(monkeypatch):
    route = web.LttxWebRouteServer()
    route.tx = SimpleNamespace(push=lambda *args: replies.append(protocol.loads_message(args[1])))
    entered, release = threading.Event(), threading.Event()
    replies, calls = [], []
    def dispatch(msg):
        calls.append(msg['id'])
        if msg['id'] == 'block':
            entered.set()
            assert release.wait(3)
        return True, {}
    monkeypatch.setattr(web, 'route_external_lttx_request', dispatch)
    def enqueue(identity, client='a', action='xtdata.get_full_tick', timeout=5):
        route._enqueue_raw(protocol.pack_request(action, client_id=client, request_id=identity, timeout=timeout), route.tx)
    try:
        enqueue('block')
        assert entered.wait(2)
        enqueue('expired', timeout=-1)
        enqueue('write', action='xttrader.order_stock_async', timeout=-1)
        enqueue('independent', client='b')
        eventually(lambda: 'independent' in calls)
        assert calls == ['block', 'independent']
        release.set()
        eventually(lambda: len(replies) == 4)
        assert calls == ['block', 'independent', 'write']
        assert next(r for r in replies if r['id'] == 'expired')['ok'] is False
        assert next(r for r in replies if r['id'] == 'write')['ok'] is True
    finally:
        release.set()
        route.tx = None
        if route._executor:
            route._executor.close()


def test_subscription_completed_after_connection_change_is_released(monkeypatch):
    route = web.LttxWebRouteServer()
    old = SimpleNamespace(push=lambda *args: pytest.fail('sent on retired transport'))
    route.tx = old
    released = []
    def dispatch(msg):
        route.tx = object()
        return {'subscribe_id': 77}, {'bridge_id': 'test', 'channel': 'normal'}
    monkeypatch.setattr(web, 'route_external_lttx_request', dispatch)
    monkeypatch.setattr(route, '_release_external_quote', lambda row, timeout: released.append(row['native_id']))
    route._handle_raw(protocol.pack_request('xtdata.subscribe_whole_quote', {'code_list': ['SH', 'SZ', 'BJ']}, client_id='a'), response_tx=old)
    assert released == [77] and not route._quote_routes and not route._quote_event_routes


@pytest.mark.parametrize('action', ['xttrader.order_stock', 'xttrader.order_stock_async',
                                   'xttrader.cancel_order_stock', 'xtdata.subscribe_whole_quote',
                                   'xtdata.download_history_data', 'xttrader.query_stock_orders_async'])
def test_web_transport_disconnect_never_replays_a_write_or_callback_request(action, monkeypatch):
    manager = web.GlobalTxClient()
    calls = []
    def request(*args, **kwargs):
        calls.append(args)
        raise web.CfquantError('cfquant pipe receive connection closed')
    monkeypatch.setattr(manager, '_get_client', lambda mode: SimpleNamespace(request=request))
    monkeypatch.setattr(manager, '_drop_client', lambda *args: None)
    monkeypatch.setattr(web, 'bridge_channels', lambda bridge_id: {'normal': 'test', 'trade': 'test'})
    with pytest.raises(web.CfquantError):
        manager.request('test', 'trade', action, mode='ctypes')
    assert len(calls) == 1


def test_web_readonly_query_retains_single_reconnect_retry(monkeypatch):
    manager = web.GlobalTxClient()
    calls = []
    def request(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise web.CfquantError('cfquant pipe receive connection closed')
        return {'pong': True}
    monkeypatch.setattr(manager, '_get_client', lambda mode: SimpleNamespace(request=request))
    monkeypatch.setattr(manager, '_drop_client', lambda *args: None)
    monkeypatch.setattr(web, 'bridge_channels', lambda bridge_id: {'normal': 'test'})
    assert manager.request('test', 'normal', 'cfquant.ping', mode='ctypes') == {'pong': True}
    assert len(calls) == 2


@pytest.fixture
def bridge():
    result = NormalQmtBridge(SimpleNamespace(), show=False, schedule_timer=False, order_meta_enabled=False)
    result.running = True
    result.messages, result.calls = [], []
    result.tx = SimpleNamespace(push=lambda kind, raw, target: result.messages.append(protocol.loads_message(raw)))
    result._dispatch = lambda action, params, msg: result.calls.append(msg['id']) or {'result': 2**63 + 3}
    yield result
    result.running = False


def test_qmt_expired_read_is_skipped_but_write_executes_once(bridge):
    for identity, action in [('read', 'xtdata.get_full_tick'), ('write', 'xttrader.order_stock_async')]:
        msg = protocol.loads_message(protocol.pack_request(action, client_id='a', request_id=identity, timeout=.01))
        msg['_received_monotonic'] = time.perf_counter() - 1
        bridge._drain_single_request('test', msg, time.time())
    assert bridge.calls == ['write']
    assert [r['ok'] for r in bridge.messages] == [False, True]


def test_coalesced_queries_encode_once_and_keep_live_waiter_when_primary_expired(bridge, monkeypatch):
    counts = []
    original = protocol.encode_response_result
    monkeypatch.setattr('cfquant.normal_bridge.encode_response_result', lambda result: counts.append(result) or original(result))
    for i in range(3):
        raw = protocol.pack_request('xttrader.query_stock_positions', client_id=str(i), request_id=str(i), timeout=5)
        bridge._handle_raw_from_thread(raw)
    msg, received, key = bridge.request_queue.get_nowait()
    msg['_received_monotonic'] = time.perf_counter() - 10
    bridge._drain_coalesced_request('test', msg, received, key)
    assert bridge.calls == ['1'] and len(counts) == 1
    assert [(r['id'], r['ok']) for r in bridge.messages] == [('0', False), ('1', True), ('2', True)]
    assert bridge.messages[1]['result'] == bridge.messages[2]['result']


def test_coalesced_encoding_failure_replies_to_every_waiter(bridge, monkeypatch):
    monkeypatch.setattr('cfquant.normal_bridge.encode_response_result', lambda result: (_ for _ in ()).throw(ValueError('encoding failed')))
    for i in range(3):
        bridge._handle_raw_from_thread(protocol.pack_request('xttrader.query_stock_positions', client_id=str(i), request_id=str(i)))
    msg, received, key = bridge.request_queue.get_nowait()
    bridge._drain_coalesced_request('test', msg, received, key)
    assert [(r['id'], r['ok']) for r in bridge.messages] == [('0', False), ('1', False), ('2', False)]
    assert not bridge.coalesced_requests and bridge.coalesce_dispatch_count == 1


def test_qmt_pump_yields_between_requests_but_never_interrupts_one(bridge, monkeypatch):
    now = [10.0]
    monkeypatch.setattr('cfquant.normal_bridge.time', SimpleNamespace(perf_counter=lambda: now[0], time=time.time))
    bridge.pump_max_ms = 5
    def dispatch(action, params, msg):
        bridge.calls.append(msg['id'])
        now[0] += .010
        return True
    bridge._dispatch = dispatch
    for i in range(3):
        bridge._handle_raw_from_thread(protocol.pack_request('xttrader.order_stock_async', client_id='a', request_id=str(i)))
    assert bridge._drain_requests('test') == 1
    assert bridge.calls == ['0'] and bridge.request_queue.qsize() == 2
    assert bridge._drain_requests('test') == 1
    assert bridge.calls == ['0', '1']


def test_result_encoding_reports_all_substages_and_preserves_shape(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(protocol, 'time', SimpleNamespace(perf_counter=lambda: clock[0], time=time.time))
    encode, normalize = protocol.encode_value, protocol.normalize_json_value
    def encode_once(value):
        clock[0] += .003
        return value
    def normalize_once(value, *args, **kw):
        clock[0] += .007
        return value
    monkeypatch.setattr(protocol, 'encode_value', encode_once)
    monkeypatch.setattr(protocol, 'normalize_json_value', normalize_once)
    body, timing = protocol.encode_response_result({'id': 2**63 + 1})
    assert json.loads(body)['id'] == 2**63 + 1
    assert timing['encode_ms'] == 10 and timing['encode_value_ms'] == 3 and timing['normalize_ms'] == 7
