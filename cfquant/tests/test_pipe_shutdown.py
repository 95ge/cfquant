"""Stop real Pipe workers with isolated transports, including standalone Lite."""
import ast
import os
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from cfquant import pipe_bridge, pipe_transport
from cfquant.qmt_pipe_runtime import ManagedPipeRuntime


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))


@pytest.fixture(scope='module', params=[None] + LITE_PATHS,
                ids=lambda path: path.stem if path else 'shared')
def implementation(request):
    if request.param is None:
        return SimpleNamespace(client=pipe_transport.PipeTxClient,
                               normal=pipe_bridge.PipeNormalQmtBridge,
                               trade=pipe_bridge.PipeTradeBridge,
                               runtime=ManagedPipeRuntime)
    tree = ast.parse(request.param.read_bytes().decode('gbk'), feature_version=(3, 6))
    cutoff = next(n.lineno for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == '_entry_file_path')
    # Execute the actual definitions without loading a strategy or connecting
    # to a configured Hub. Do not evaluate module startup/environment changes.
    body = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
            or (isinstance(n, ast.Assign) and n.lineno < cutoff
                and all(isinstance(target, ast.Name) for target in n.targets))]
    namespace = {'__name__': 'offline_shutdown', '__file__': str(request.param)}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(request.param), 'exec'), namespace)
    namespace.update(_LOG_ENABLED=False, _QMT_BOUND_LOG_ENABLED=False)
    return SimpleNamespace(client=namespace['PipeTxClient'],
                           normal=namespace['PipeNormalQmtBridge'],
                           trade=namespace['PipeTradeBridge'],
                           runtime=namespace['ManagedPipeRuntime'])


class Connection:
    def __init__(self, block_hello=False, payload=None):
        self.closed = threading.Event()
        self.writing = threading.Event()
        self.block_hello = block_hello
        self.payload = payload

    def write_frame(self, payload):
        self.writing.set()
        if self.block_hello:
            if not self.closed.wait(5):
                raise AssertionError('shutdown did not interrupt handshake')
            raise OSError('connection closed')

    def read_frame(self):
        if self.payload is not None:
            payload, self.payload = self.payload, None
            return payload
        self.closed.wait(5)
        return None

    def close(self):
        self.closed.set()


def patch_connect(monkeypatch, implementation, function):
    monkeypatch.setitem(implementation.client._open_connection.__globals__, 'connect_pipe', function)


def assert_stopped(client):
    assert not client.running
    assert client._get_conns() == (None, None)
    for worker in (client.thread, client.heartbeat_thread):
        if worker is not None:
            assert not worker.is_alive()


@pytest.mark.skipif(os.name != 'nt', reason='Windows named pipes')
def test_missing_pipe_connect_is_cancelled_by_close(implementation):
    # A random nonexistent pipe cannot reach the user's QMT or running Hub.
    client = implementation.client(pipe_name='cfquant-shutdown-' + uuid.uuid4().hex,
                                   connect_timeout_ms=30000, show=False)
    entered = threading.Event()
    opening = client._open_connection

    def open_connection(role):
        entered.set()
        return opening(role)

    client._open_connection = open_connection
    errors = []
    client._log = errors.append
    client.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        client.close()
        assert time.monotonic() - started < 1.5
        assert_stopped(client)
        assert errors == []
    finally:
        client.close()


@pytest.mark.parametrize('role', ['rx', 'tx'])
def test_close_interrupts_unpublished_handshake(implementation, monkeypatch, role):
    connections = [Connection(block_hello=role == 'rx'), Connection(block_hello=role == 'tx')]
    attempts = []

    def connect(*args, **kwargs):
        conn = connections[len(attempts)]
        attempts.append(conn)
        return conn

    patch_connect(monkeypatch, implementation, connect)
    client = implementation.client(show=False)
    messages = []
    client._log = messages.append
    client.start()
    try:
        assert connections[0 if role == 'rx' else 1].writing.wait(2)
        assert client._get_conns() == (None, None)
        client.close()
        assert_stopped(client)
        assert all(conn.closed.is_set() for conn in attempts)
        assert not client._connecting_conns
        assert messages == []
        with pytest.raises(RuntimeError, match='closed'):
            client.start()
    finally:
        client.close()


def test_close_unblocks_reader_when_receive_queue_is_full(implementation, monkeypatch):
    entered = threading.Event()

    class ObservedQueue(queue.Queue):
        def put(self, value, *args, **kwargs):
            if self.full() and value is not None:
                entered.set()
            return super().put(value, *args, **kwargs)

    connections = iter([Connection(payload='request'), Connection()])
    patch_connect(monkeypatch, implementation, lambda *a, **k: next(connections))
    client = implementation.client(show=False)
    client.Q = ObservedQueue(maxsize=1)
    client.Q.put('already queued')
    client.start()
    try:
        assert entered.wait(2)
        client.close()
        assert_stopped(client)
        assert client.Q.get_nowait() == 'already queued'
        assert client.Q.empty()
    finally:
        client.close()


def test_close_interrupts_retry_backoff_and_heartbeat(implementation, monkeypatch):
    attempts = []
    logged = threading.Event()

    def fail(*args, **kwargs):
        attempts.append(1)
        raise FileNotFoundError('offline test')

    patch_connect(monkeypatch, implementation, fail)
    client = implementation.client(show=False, reconnect_interval=30)
    messages = []
    client._log = lambda message: (messages.append(message), logged.set())
    client.start()
    try:
        assert logged.wait(2)
        client.close()
        assert_stopped(client)
        assert len(attempts) == len(messages) == 1
    finally:
        client.close()


def test_close_from_connection_worker_does_not_join_itself(implementation, monkeypatch):
    connections = [Connection(), Connection()]
    remaining = iter(connections)
    patch_connect(monkeypatch, implementation, lambda *a, **k: next(remaining))
    client = implementation.client(show=False)
    client._log = lambda message: client.close()
    client.start()
    try:
        client.thread.join(2)
        assert_stopped(client)
        assert all(conn.closed.is_set() for conn in connections)
    finally:
        client.close()


def test_delayed_old_connector_cannot_be_restarted_or_publish(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    old_conn = Connection()

    def slow_connect(*args, **kwargs):
        entered.set()
        release.wait(5)
        return old_conn

    monkeypatch.setattr(pipe_transport, 'connect_pipe', slow_connect)
    client = pipe_transport.PipeTxClient(show=False)
    client.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        client.close()
        assert time.monotonic() - started < 1.5
        assert client.thread.is_alive()  # Simulate an uncooperative native call.
        with pytest.raises(RuntimeError, match='closed'):
            client.start()
        release.set()
        client.thread.join(2)
        assert_stopped(client)
        assert old_conn.closed.is_set()
        assert not old_conn.writing.is_set()
        assert client.connection_generation == 0
    finally:
        release.set()
        client.close()


@pytest.mark.skipif(os.name != 'nt', reason='Windows named pipes')
def test_close_cancels_native_read_and_blocked_sender(implementation, monkeypatch):
    servers, connections, acceptors = [], [], []
    client = None
    try:
        for role in ('rx', 'tx'):
            name = 'cfquant-shutdown-%s-%s' % (role, uuid.uuid4().hex)
            server = pipe_transport.create_pipe_instance(name, in_buffer_size=4096, out_buffer_size=4096)
            servers.append(server)
            acceptor = threading.Thread(target=pipe_transport.wait_for_pipe_client, args=(server,), daemon=True)
            acceptors.append(acceptor)
            acceptor.start()
            connections.append(pipe_transport.connect_pipe(name))
            acceptor.join(2)
            assert not acceptor.is_alive()
        remaining = iter(connections)
        patch_connect(monkeypatch, implementation, lambda *a, **k: next(remaining))
        client = implementation.client(show=False)
        reading = threading.Event()
        original_read = connections[0].read_frame

        def read():
            reading.set()
            return original_read()

        connections[0].read_frame = read
        client.start()
        assert reading.wait(2)
        assert client.push('event', 'x' * 1000000, 'offline.test')['code'] == 0
        sender = client._sender
        deadline = time.monotonic() + 2
        while not sender.status()['sending'] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sender.status()['sending']
        # The test servers neither send nor consume data. Only closing the
        # client can release ReadFile and the full-buffer WriteFile.
        client.close()
        assert_stopped(client)
        assert not sender._thread.is_alive()
        assert all(conn.closed for conn in connections)
    finally:
        if client is not None:
            client.close()
        for connection in connections + servers:
            connection.close()
        for acceptor in acceptors:
            acceptor.join(2)


@pytest.mark.parametrize('managed', [False, True])
def test_both_transports_stop_before_native_cleanup_and_late_callbacks(implementation, monkeypatch, managed):
    def offline(*args, **kwargs):
        raise FileNotFoundError('offline test')

    patch_connect(monkeypatch, implementation, offline)
    descriptor = dict(runtime_key=uuid.uuid4().hex, mode='lite', role='normal', generation='test') if managed else None
    runtime = implementation.runtime(descriptor).acquire()
    namespace = {'_managed_runtime': runtime}
    normal = implementation.normal(None, show=False, schedule_timer=False, globals_dict=namespace).start()
    trade = implementation.trade(None, show=False, globals_dict=namespace).start()
    clients = [normal.tx, trade.tx]
    entered, release = threading.Event(), threading.Event()
    callbacks = []

    def stop(context):
        # Models the entry's timer cancellation / native quote unsubscribe.
        entered.set()
        release.wait(5)
        trade.close()
        normal.close()

    namespace.update(_normal_bridge=normal, _trade_bridge=trade, stop=stop,
                     handlebar=lambda context: callbacks.append(normal.start()),
                     order_callback=lambda *args: callbacks.append('order'))
    runtime.bind(namespace)
    worker = threading.Thread(target=namespace['stop'], args=(None,), daemon=True)
    worker.start()
    try:
        assert entered.wait(3)
        assert worker.is_alive()
        assert not normal.running and not trade.running and not runtime.active
        for client in clients:
            assert_stopped(client)
        assert not normal.recv_thread.is_alive()
        namespace['handlebar'](None)
        namespace['order_callback'](None, {})
        assert callbacks == []
        assert normal.tx is None and trade.tx is None
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert runtime.bridges_closed
        namespace['stop'](None)  # Repeated stop is harmless.
        replacement = implementation.runtime(descriptor).acquire()
        replacement.close()
    finally:
        release.set()
        worker.join(3)
        runtime.close()


def test_direct_normal_close_stops_transport_before_waiting_for_dispatch(implementation, monkeypatch):
    attempted = threading.Event()

    def offline(*args, **kwargs):
        attempted.set()
        raise FileNotFoundError('offline test')

    patch_connect(monkeypatch, implementation, offline)
    bridge = implementation.normal(None, show=False, schedule_timer=False).start()
    client = bridge.tx
    reached = threading.Event()
    original_cleanup = bridge._close_quote_subscriptions

    def cleanup():
        reached.set()
        original_cleanup()

    bridge._close_quote_subscriptions = cleanup
    worker = threading.Thread(target=bridge.close, daemon=True)
    try:
        assert attempted.wait(2)
        with bridge.dispatch_lock:
            worker.start()
            assert reached.wait(3)
            assert worker.is_alive()
            assert_stopped(client)
        worker.join(2)
        assert not worker.is_alive()
        with pytest.raises(RuntimeError, match='closed'):
            bridge.start()
    finally:
        bridge.close()


def test_cleanup_failure_still_closes_other_bridge_and_can_retry(implementation, capsys):
    runtime = implementation.runtime().acquire()
    calls = []

    class Bridge:
        def __init__(self, name):
            self.name = name
            self.fail = name == 'normal'

        def stop_transport(self):
            calls.append(('pipe', self.name))

        def close(self):
            calls.append(('cleanup', self.name))
            if self.fail:
                self.fail = False
                raise RuntimeError('native cleanup failed')

    normal, trade = Bridge('normal'), Bridge('trade')
    # Attach directly to test the fallback when entry stop is unavailable.
    runtime.attached_bridges = [normal, trade]
    runtime.close()
    assert calls == [('pipe', 'normal'), ('pipe', 'trade'), ('cleanup', 'normal'), ('cleanup', 'trade')]
    assert 'native cleanup failed' in capsys.readouterr().out
    assert not runtime.bridges_closed
    runtime.close()
    assert runtime.bridges_closed
