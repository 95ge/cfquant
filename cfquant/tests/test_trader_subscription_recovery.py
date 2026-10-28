"""Restart account publishers/transports while the real SDK stays alive."""

import queue
import threading
import time
from types import SimpleNamespace

import pytest

from cfquant.client import CfquantError, LTtxRpcClient, WebLttxRpcClient
from cfquant.pipe_client import PipeRpcClient
from cfquant.pipe_transport import loads_pipe_message
from cfquant.protocol import loads_message, pack_event, pack_response
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "subscription recovery did not complete"


def account_key(account):
    return (account.get("bridge_id"), account["account_type"], account["account_id"])


class Publisher:
    def __init__(self):
        self.receivers = {}
        self.subscribers = {}
        self.requests = []
        self.ready = True
        self.available = True
        self.reject = set()
        self.before_subscribe = None
        self.ping_results = []

    def connection(self, *args, **kwargs):
        if not self.available:
            raise OSError("test transport offline")
        publisher = self

        class Connection:
            def __init__(self):
                self.Q = queue.Queue()
                self.run_on = True

            def start_tx(self):
                pass

            def start_txg(self, client_id):
                publisher.receivers[client_id] = self

            def push(self, key, raw, channel):
                if not self.run_on:
                    raise OSError("test transport closed")
                publisher.request(raw)

            def write_frame(self, raw):
                envelope = loads_pipe_message(raw)
                if envelope["type"] == "hello":
                    if envelope["role"] == "api_rx":
                        self.start_txg(envelope["client_id"])
                else:
                    self.push("request", envelope["payload"], envelope["request_channel"])

            def read_frame(self):
                return self.Q.get()

            def close(self):
                self.run_on = False
                self.Q.put(None)

        return Connection()

    def request(self, raw):
        msg = loads_message(raw)
        self.requests.append(msg)
        action = msg["action"]
        result, error = 0, None
        if action == "cfquant.ping" and self.ping_results:
            result = self.ping_results.pop(0)
        if action in ("xttrader.subscribe", "xttrader.unsubscribe"):
            key = account_key(msg["params"]["account"])
            if action == "xttrader.subscribe" and self.before_subscribe is not None:
                self.before_subscribe()
            if not self.ready:
                error = "Managed strategy is awaiting account mode confirmation from cfquant Web."
            elif key in self.reject:
                result = -1
            elif action == "xttrader.subscribe":
                self.subscribers.setdefault(key, set()).add(msg["client_id"])
            else:
                self.subscribers.get(key, set()).discard(msg["client_id"])
        self.receivers[msg["client_id"]].Q.put(
            pack_response(msg["id"], ok=error is None, result=result, error=error))

    def emit(self, account, value):
        for client_id in list(self.subscribers.get(account_key(account), ())):
            self.receivers[client_id].Q.put(pack_event("trader:on_stock_asset", dict(account, cash=value)))

    def disconnect(self):
        for connection in list(self.receivers.values()):
            connection.close()
        self.subscribers.clear()


@pytest.fixture(params=["pipe", "lttx", "web"])
def env(request, monkeypatch):
    publisher = Publisher()
    clients = []

    def new_client(client_id=None, bridge_id=None):
        if request.param == "pipe":
            client = PipeRpcClient(client_id=client_id, timeout=.2)
            monkeypatch.setattr("cfquant.pipe_client.connect_pipe", publisher.connection)
        else:
            cls = WebLttxRpcClient if request.param == "web" else LTtxRpcClient
            kwargs = {"registry": {"web_request_channel": "test.web"}} if request.param == "web" else {}
            client = cls(client_id=client_id, timeout=.2, **kwargs)
            monkeypatch.setattr(client, "_load_txl", lambda: publisher.connection)
        clients.append(client)
        return client

    monkeypatch.setattr("cfquant.xttrader._new_trade_client", new_client)
    account = StockAccount("TEST_A", "STOCK", bridge_id="test")
    payload = dict(account_id=account.account_id, account_type=account.account_type, bridge_id="test")
    received = []
    callback = XtQuantTraderCallback()
    callback.on_stock_asset = lambda asset: received.append((asset.account_id, asset.cash))
    trader = XtQuantTrader(callback=callback)
    trader.bridge_id = "test"
    trader._subscription_interval = .03
    trader._subscription_timeout = .2
    assert trader.connect() == 0
    assert trader.subscribe(account) == 0
    state = SimpleNamespace(publisher=publisher, trader=trader, account=account, payload=payload,
                            received=received, clients=clients, callback=callback)
    try:
        yield state
    finally:
        publisher.before_subscribe = None
        trader.stop()


def test_publisher_restart_restores_callbacks_without_user_requests(env):
    publisher = env.publisher
    publisher.emit(env.payload, 1)
    wait_until(lambda: env.received == [("TEST_A", 1)])
    for value in (2, 3):
        publisher.ready = False
        publisher.subscribers.clear()  # QMT or Web restart; client socket stays open.
        wait_until(lambda: bool(env.trader._subscription_errors))
        publisher.ready = True
        wait_until(lambda: bool(publisher.subscribers.get(account_key(env.payload))))
        publisher.emit(env.payload, value)
        wait_until(lambda: len(env.received) == value)
    assert env.received == [("TEST_A", 1), ("TEST_A", 2), ("TEST_A", 3)]
    assert len(env.clients) == 1
    assert len(env.clients[0]._callbacks["trader:on_stock_asset"]) == 1
    assert {msg["action"] for msg in publisher.requests} <= {"cfquant.ping", "xttrader.subscribe"}


def test_connect_rebuilds_stale_session_after_qmt_reload(env):
    publisher = env.publisher
    old_client = env.trader._get_client()
    publisher.ping_results[:] = [-1]
    assert env.trader.connect() == 0
    assert env.trader.last_connect_error == ""
    assert len(env.clients) == 2
    assert env.trader._get_client() is not old_client
    assert publisher.subscribers.get(account_key(env.payload))


def test_transport_restart_restores_idle_listener(env):
    publisher = env.publisher
    publisher.available = False
    publisher.disconnect()
    wait_until(lambda: not env.clients[0]._started)
    wait_until(lambda: bool(env.trader._subscription_errors))
    publisher.available = True
    wait_until(lambda: bool(publisher.subscribers.get(account_key(env.payload))))
    publisher.emit(env.payload, 8)
    wait_until(lambda: env.received == [("TEST_A", 8)])
    assert len(env.clients[0]._callbacks["trader:on_stock_asset"]) == 1


def test_failed_account_does_not_block_other_accounts_or_restore_unsubscribed_account(env):
    publisher = env.publisher
    second = StockAccount("TEST_B", "CREDIT", bridge_id="second")
    second_payload = dict(account_id=second.account_id, account_type=second.account_type, bridge_id="second")
    assert env.trader.subscribe(second) == 0
    publisher.reject.add(account_key(env.payload))
    publisher.subscribers.clear()
    wait_until(lambda: bool(publisher.subscribers.get(account_key(second_payload))))
    publisher.emit(second_payload, 42)
    wait_until(lambda: env.received == [("TEST_B", 42)])

    publisher.ready = False
    with pytest.raises(CfquantError):
        env.trader.unsubscribe(env.account)
    publisher.requests.clear()
    publisher.ready = True
    publisher.reject.clear()
    publisher.subscribers.clear()
    wait_until(lambda: bool(publisher.subscribers.get(account_key(second_payload))))
    assert not publisher.subscribers.get(account_key(env.payload))
    assert all(msg["params"]["account"]["account_id"] == "TEST_B" for msg in publisher.requests)


def test_unsubscribe_serializes_with_inflight_renewal(env):
    entered, release = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
    env.publisher.before_subscribe = block
    assert entered.wait(2)
    done = threading.Event()
    def unsubscribe():
        env.trader.unsubscribe(env.account)
        done.set()
    worker = threading.Thread(target=unsubscribe)
    worker.start()
    try:
        env.publisher.before_subscribe = None
        release.set()
        assert done.wait(2)
        assert not env.publisher.subscribers.get(account_key(env.payload))
        assert env.publisher.requests[-1]["action"] == "xttrader.unsubscribe"
    finally:
        release.set()
        worker.join(2)


def test_stop_from_callback_stops_recovery_and_can_start_again(env):
    done = threading.Event()
    def stop_from_callback(asset):
        env.trader.stop()
        done.set()
    env.callback.on_stock_asset = stop_from_callback
    worker = env.trader._subscription_thread
    env.publisher.emit(env.payload, 10)
    assert done.wait(2)
    assert not worker.is_alive()
    assert not env.trader._subscribed_accounts
    assert all(client._closed for client in env.clients)

    env.callback.on_stock_asset = lambda asset: env.received.append((asset.account_id, asset.cash))
    assert env.trader.connect() == 0
    assert env.trader.subscribe(env.account) == 0
    assert env.trader._subscription_thread is not worker
    env.publisher.subscribers.clear()
    wait_until(lambda: bool(env.publisher.subscribers.get(account_key(env.payload))))
    env.publisher.emit(env.payload, 11)
    wait_until(lambda: env.received == [("TEST_A", 11)])


def test_stop_cancels_pending_subscription_response(env):
    original = env.publisher.request
    entered = threading.Event()
    def no_response(raw):
        if loads_message(raw)["action"] == "xttrader.subscribe":
            entered.set()
            return
        original(raw)
    env.publisher.request = no_response
    env.trader._subscription_timeout = 30
    assert entered.wait(2)
    worker = env.trader._subscription_thread
    before = time.monotonic()
    env.trader.stop()
    assert time.monotonic() - before < 1
    assert not worker.is_alive()
    assert all(client._closed for client in env.clients)


@pytest.mark.parametrize("cls", [LTtxRpcClient, WebLttxRpcClient])
def test_stop_interrupts_recovery_connection_handshake(monkeypatch, cls):
    publisher = Publisher()
    kwargs = {"registry": {"web_request_channel": "test.web"}} if cls is WebLttxRpcClient else {}
    client = cls(timeout=.2, **kwargs)
    monkeypatch.setattr(client, "_load_txl", lambda: publisher.connection)
    monkeypatch.setattr("cfquant.xttrader._new_trade_client", lambda **kw: client)
    account = StockAccount("TEST_ONLY", "STOCK", bridge_id="test")
    trader = XtQuantTrader(account=account)
    trader._subscription_interval = .03
    entered, cancelled = threading.Event(), threading.Event()

    class ConnectingTx:
        run_on = True
        Q = queue.Queue()
        def start_tx(self):
            entered.set()
            assert cancelled.wait(3)
            return {"code": -1, "msg": "test connection cancelled"}
        def close(self):
            self.run_on = False
            cancelled.set()

    try:
        assert trader.connect() == 0
        monkeypatch.setattr(client, "_load_txl", lambda: lambda *a, **kw: ConnectingTx())
        publisher.disconnect()
        assert entered.wait(2)
        worker = trader._subscription_thread
        trader.stop()
        assert cancelled.is_set()
        assert not worker.is_alive()
    finally:
        cancelled.set()
        trader.stop()


@pytest.mark.parametrize("failure", ["connect", "hello"])
def test_pipe_retry_closes_partial_connections(monkeypatch, failure):
    publisher = Publisher()
    connections = []
    attempts = []
    def connect(*args, **kwargs):
        attempts.append(True)
        if failure == "connect" and len(attempts) == 2:
            raise OSError("test send pipe unavailable")
        connection = publisher.connection()
        connections.append(connection)
        if failure == "hello" and len(attempts) == 2:
            def fail(raw):
                raise OSError("test hello rejected")
            connection.write_frame = fail
        return connection
    monkeypatch.setattr("cfquant.pipe_client.connect_pipe", connect)
    client = PipeRpcClient()
    try:
        with pytest.raises(OSError, match="test"):
            client.start()
        assert all(not conn.run_on for conn in connections)
        assert client._rx_conn is None and client._tx_conn is None
        client.start()
        assert client._started
        assert client._recv_thread.is_alive()
    finally:
        client.close()
