"""Exercise real receive loops and Trader APIs with in-memory transports only."""
import queue
import threading
from types import SimpleNamespace

import pytest

from cfquant.client import LTtxRpcClient, WebLttxRpcClient, CfquantTimeout, CfquantError
from cfquant.pipe_client import PipeRpcClient
from cfquant.pipe_transport import loads_pipe_message
from cfquant.protocol import loads_message, pack_event, pack_response
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount


@pytest.fixture(params=['lttx', 'web', 'pipe'])
def env(request, monkeypatch):
    incoming = queue.Queue()
    sent = []
    reply = [True]

    def send(raw):
        msg = loads_message(raw)
        sent.append(msg)
        if not reply[0]:
            return
        action = msg['action']
        result = [{'stock_code': '000001.SZ', 'volume': 100}]
        if action.endswith('order_stock_async'):
            result = {'accepted': True, 'seq': msg['params']['seq']}
        incoming.put(pack_response(msg['id'], result=result))
        if action == 'xttrader.order_stock_async':
            event = pack_event('trader:on_order_stock_async_response', {
                'seq': msg['params']['seq'], 'account_id': 'TEST_ONLY', 'order_id': 123,
            })
            incoming.put(event)
            incoming.put(event)  # Duplicate must not trigger a second user response.

    class FakeTx:
        Q = incoming
        def start_tx(self): pass
        def start_txg(self, client_id): pass
        def push(self, key, raw, channel): send(raw)
        def close(self): incoming.put(None)

    class FakePipe:
        def write_frame(self, raw):
            envelope = loads_pipe_message(raw)
            if envelope['type'] != 'hello':
                send(envelope['payload'])
        def read_frame(self): return incoming.get()
        def close(self): incoming.put(None)

    if request.param == 'pipe':
        monkeypatch.setattr('cfquant.pipe_client.connect_pipe', lambda *a, **kw: FakePipe())
        client = PipeRpcClient(timeout=0.3)
    else:
        cls = WebLttxRpcClient if request.param == 'web' else LTtxRpcClient
        kwargs = {'registry': {'web_request_channel': 'offline.web'}} if request.param == 'web' else {}
        client = cls(timeout=0.3, **kwargs)
        monkeypatch.setattr(client, '_load_txl', lambda: lambda *a, **kw: FakeTx())
    account = StockAccount('TEST_ONLY')
    callback = XtQuantTraderCallback()
    trader = XtQuantTrader(callback=callback, account=account)
    monkeypatch.setattr(trader, '_get_client', lambda *a: client)
    trader._clients[trader.bridge_id] = client
    trader._register_trader_events()
    client.start()
    state = SimpleNamespace(client=client, trader=trader, account=account, callback=callback,
                            incoming=incoming, sent=sent, reply=reply)
    yield state
    client.close()
    client._recv_thread.join(2)


def test_trade_callback_queries_orders_and_cancels(env):
    done = threading.Event()
    responses = []
    results = []
    threads = []

    def trade(data):
        threads.append(threading.current_thread())
        results.append(env.trader.query_stock_positions(env.account)[0].volume)
        results.append(env.trader.order_stock_async(env.account, '000001.SZ', 23, 100, 11, 1.0))
        results.append(env.trader.cancel_order_stock_async(env.account, 123))

    def response(data):
        responses.append(data.seq)
        # Nested synchronous query in the asynchronous order response too.
        results.append(env.trader.query_stock_positions(env.account)[0].volume)
        done.set()

    env.callback.on_stock_trade = trade
    env.callback.on_order_stock_async_response = response
    env.incoming.put(pack_event('trader:on_stock_trade', {'account_id': 'TEST_ONLY'}))
    assert done.wait(3)
    assert results[0] == results[-1] == 100
    assert results[1] > 0 and results[2] > 0
    assert responses == [results[1]]
    assert threads[0] is not env.client._recv_thread
    assert sum(x['action'] == 'xttrader.order_stock_async' for x in env.sent) == 1


def test_slow_callback_does_not_block_rpc_and_callbacks_remain_serial(env, caplog):
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    delivered = []
    def callback(value):
        delivered.append(value)
        if value == 1:
            entered.set()
            assert release.wait(3)
            raise ValueError('callback-test-error')
        done.set()
    env.client.add_callback('test', callback)
    try:
        env.incoming.put(pack_event('test', 1))
        assert entered.wait(2)
        env.incoming.put(pack_event('test', 2))
        assert env.trader.query_stock_positions(env.account)[0].volume == 100
        assert delivered == [1]
    finally:
        release.set()
    assert done.wait(2)
    assert delivered == [1, 2]
    assert 'callback-test-error' in caplog.text


def test_callback_query_timeout_does_not_kill_later_callbacks(env):
    done = threading.Event()
    errors = []
    def callback(value):
        if value == 1:
            try:
                env.trader.query_stock_positions(env.account)
            except CfquantTimeout as exc:
                errors.append(exc)
        else:
            done.set()
    env.client.add_callback('test', callback)
    env.reply[0] = False
    env.incoming.put(pack_event('test', 1))
    env.incoming.put(pack_event('test', 2))
    assert done.wait(2)
    assert len(errors) == 1
    assert not env.client._pending


def test_stop_inside_callback_drops_queued_callbacks(env):
    done = threading.Event()
    delivered = []
    def callback(value):
        delivered.append(value)
        env.trader.stop()
        done.set()
    env.client.add_callback('test', callback)
    env.incoming.put(pack_event('test', 1))
    env.incoming.put(pack_event('test', 2))
    assert done.wait(2)
    env.client._recv_thread.join(2)
    worker = env.client._event_dispatcher._thread
    if worker:
        worker.join(2)
        assert not worker.is_alive()
    assert delivered == [1]


@pytest.mark.parametrize('remote_disconnect', [False, True])
def test_close_releases_query_waiter(env, remote_disconnect):
    waiting, done = threading.Event(), threading.Event()
    errors = []
    env.reply[0] = False
    original_send = env.client._send_request if isinstance(env.client, PipeRpcClient) else env.client._push
    def send(*args, **kwargs):
        result = original_send(*args, **kwargs)
        waiting.set()
        return result
    name = '_send_request' if isinstance(env.client, PipeRpcClient) else '_push'
    setattr(env.client, name, send)
    def callback(value):
        try:
            env.client.request('query', timeout=10)
        except CfquantError as exc:
            errors.append(exc)
        finally:
            done.set()
    env.client.add_callback('test', callback)
    env.incoming.put(pack_event('test', 1))
    assert waiting.wait(2)
    if remote_disconnect:
        env.incoming.put(None)
    else:
        env.client.close()
    assert done.wait(2)
    assert len(errors) == 1


def test_relaxed_ordering_is_default_and_false_cannot_restore_deadlock(caplog):
    trader = XtQuantTrader()
    assert trader.relaxed_response_order_enabled
    trader.set_relaxed_response_order_enabled(False)
    assert trader.relaxed_response_order_enabled
    assert 'False is ignored' in caplog.text


def test_restart_discards_old_events_without_running_callbacks_concurrently(env):
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    delivered, stale_errors = [], []
    def callback(value):
        delivered.append(value)
        if value == 1:
            entered.set()
            assert release.wait(3)
            try:
                env.client.request('old-query')
            except RuntimeError as exc:
                stale_errors.append(str(exc))
        else:
            done.set()
    env.client.add_callback('test', callback)
    try:
        env.incoming.put(pack_event('test', 1))
        assert entered.wait(2)
        env.incoming.put(pack_event('test', 2))
        # Response processing proves event 2 has passed through the receive loop.
        env.client.request('barrier')
        env.client.close()
        env.client._recv_thread.join(2)
        while not env.incoming.empty():
            env.incoming.get_nowait()
        env.client.start()
        env.incoming.put(pack_event('test', 3))
        env.client.request('barrier')
        assert delivered == [1]
    finally:
        release.set()
    assert done.wait(2)
    assert delivered == [1, 3]
    assert len(stale_errors) == 1
    assert not any(x['action'] == 'old-query' for x in env.sent)


def test_order_response_can_submit_next_order(env):
    done = threading.Event()
    responses = []
    def response(data):
        responses.append(data.seq)
        if len(responses) == 1:
            env.trader.order_stock_async(env.account, '000001.SZ', 23, 100, 11, 1.0)
        else:
            done.set()
    env.callback.on_order_stock_async_response = response
    env.trader.order_stock_async(env.account, '000001.SZ', 23, 100, 11, 1.0)
    assert done.wait(2)
    assert len(responses) == len(set(responses)) == 2
    assert len(env.sent) == 2
