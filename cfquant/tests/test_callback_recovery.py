"""Saved callback channels and listener recovery with real receive loops, no QMT."""

import queue
import threading
import time
from types import SimpleNamespace

import pytest

from cfquant import pipe_client
from cfquant.pipe_transport import loads_pipe_message
from cfquant.protocol import pack_event


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "callback recovery did not complete"


class MemoryHub:
    def __init__(self):
        self.available = True
        self.attempts = 0
        self.receivers = {}
        self.connections = []
        self.rejected_channels = set()

    def connect(self, *args, **kwargs):
        self.attempts += 1
        if not self.available:
            raise OSError("test hub unavailable")
        hub = self

        class Connection:
            def __init__(self):
                self.incoming = queue.Queue()
                self.closed = False

            def write_frame(self, raw):
                hello = loads_pipe_message(raw)
                assert hello["type"] == "hello", "listener must not send trading requests"
                channel = hello["client_id"]
                if hello["role"] == "api_tx" and channel in hub.rejected_channels:
                    raise OSError("test partial connection failure")
                if hello["role"] == "api_rx":
                    hub.receivers[channel] = self

            def read_frame(self):
                return self.incoming.get()

            def close(self):
                self.closed = True
                self.incoming.put(None)

        connection = Connection()
        self.connections.append(connection)
        return connection

    def emit(self, channel, value):
        self.receivers[channel].incoming.put(pack_event(
            "trader:on_stock_asset", {"account_id": "paper", "available": value},
        ))


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CFQUANT_HOME", str(tmp_path))
    monkeypatch.setenv("CFQUANT_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CFQUANT_LOG_DIR", str(tmp_path / "log"))
    from cfquant import runtime_services as web

    hub = MemoryHub()
    monkeypatch.setattr(pipe_client, "connect_pipe", hub.connect)
    monkeypatch.setattr(web, "CLIENTS", web.GlobalTxClient())
    monkeypatch.setattr(web, "lttx_server_reachable", lambda: False)
    monkeypatch.setattr(web, "safe_print", lambda *args: None)
    monkeypatch.setattr(web, "RUNTIME_VERSIONS", SimpleNamespace(update_from_event=lambda event: None))
    monkeypatch.setattr(web, "ACCOUNT_CACHE", SimpleNamespace(update_from_event=lambda event: None))
    forwarded = []
    monkeypatch.setattr(web, "LTTX_WEB_ROUTE", SimpleNamespace(_on_client_event=forwarded.append))
    monkeypatch.setattr(web, "WS_CALLBACKS", SimpleNamespace(broadcast=lambda event: None))
    stores = []

    def make_store(channels=None, retry_interval=0.03):
        store = web.CallbackEventStore(channels, retry_interval=retry_interval, legacy_pipe=True)
        stores.append(store)
        return store

    yield SimpleNamespace(web=web, hub=hub, make_store=make_store, forwarded=forwarded)
    for store in stores:
        store.close()


def test_start_and_restart_load_saved_binding_channels(environment, monkeypatch, tmp_path):
    web, hub = environment.web, environment.hub
    monkeypatch.setattr(web, "WEB_CONFIG", None)
    store = environment.make_store()  # Matches the actual module initialization order.
    path, db = str(tmp_path / "web.json"), str(tmp_path / "settings.db")
    config = web.WebRuntimeConfig(path, db)
    config.save_bridge({"id": "saved_binding"})
    monkeypatch.setattr(web, "WEB_CONFIG", web.WebRuntimeConfig(path, db))
    channel = "cfquant.saved_binding.callback.event"

    for value in (100, 200):
        store.start()
        wait_until(lambda: channel in hub.receivers and not hub.receivers[channel].closed)
        hub.emit(channel, value)
        wait_until(lambda: any(row["data"]["available"] == value for row in store.latest()))
        store.close()
    assert [row["data"]["available"] for row in store.latest()] == [100, 200]


def test_initial_hub_failure_recovers_without_rebinding(environment):
    hub = environment.hub
    hub.available = False
    store = environment.make_store(["saved.callback"])
    store.start()
    wait_until(lambda: hub.attempts > 0)
    hub.available = True
    wait_until(lambda: "saved.callback" in hub.receivers)
    hub.emit("saved.callback", 100)
    wait_until(lambda: len(store.latest()) == 1)
    assert len(environment.forwarded) == 1


def test_disconnect_reconnects_without_duplicate_handlers(environment):
    hub = environment.hub
    store = environment.make_store(["saved.callback"])
    store.start()
    wait_until(lambda: "saved.callback" in hub.receivers)
    for value in range(3):
        hub.emit("saved.callback", value)
        wait_until(lambda: len(store.latest()) == value + 1)
        old = hub.receivers["saved.callback"]
        old.close()  # Real PipeRpcClient receive loop detects EOF.
        wait_until(lambda: hub.receivers["saved.callback"] is not old)
    hub.emit("saved.callback", 3)
    wait_until(lambda: len(store.latest()) == 4)
    assert [row["data"]["available"] for row in store.latest()] == [0, 1, 2, 3]
    assert len(environment.forwarded) == 4
    client = store._pipe_clients["saved.callback"]
    assert client._callbacks["__event__"] == [store._on_channel_event]


def test_same_channel_refresh_wakes_repair_and_keeps_healthy_listener(environment):
    hub = environment.hub
    store = environment.make_store(["saved.callback"], retry_interval=60)
    store.start()
    wait_until(lambda: "saved.callback" in store._pipe_clients)
    healthy = hub.receivers["saved.callback"]
    for _ in range(3):
        store.refresh_channels(["saved.callback"])
    assert hub.receivers["saved.callback"] is healthy
    assert len(hub.connections) == 2
    # Hold the outage until the receive loop has observed EOF. A queued wake
    # from the healthy refreshes must not hide that state by reconnecting first.
    hub.available = False
    healthy.close()
    wait_until(lambda: not store._pipe_clients["saved.callback"]._started)
    hub.available = True
    store.refresh_channels(["saved.callback"])
    wait_until(lambda: hub.receivers["saved.callback"] is not healthy)
    hub.emit("saved.callback", 99)
    wait_until(lambda: len(store.latest()) == 1)


def test_partial_channel_failure_does_not_replace_healthy_connections(environment):
    hub = environment.hub
    hub.rejected_channels.add("bad.callback")
    store = environment.make_store(["good.callback", "bad.callback"])
    store.start()
    wait_until(lambda: "good.callback" in store._pipe_clients and "bad.callback" in store._pipe_errors)
    good = hub.receivers["good.callback"]
    hub.rejected_channels.clear()
    wait_until(lambda: "bad.callback" in store._pipe_clients)
    assert hub.receivers["good.callback"] is good
    assert all(conn.closed for conn in hub.connections if conn not in (
        store._pipe_clients["good.callback"]._rx_conn, store._pipe_clients["good.callback"]._tx_conn,
        store._pipe_clients["bad.callback"]._rx_conn, store._pipe_clients["bad.callback"]._tx_conn,
    ))
    hub.emit("bad.callback", 50)
    wait_until(lambda: len(store.latest()) == 1)


@pytest.mark.parametrize("follow_config", [False, True])
def test_channel_change_closes_old_listeners_and_shutdown_stops_retry(environment, monkeypatch, follow_config):
    hub, web = environment.hub, environment.web
    monkeypatch.setattr(web, "callback_channels", lambda: ["old.callback"])
    store = environment.make_store(None if follow_config else ["old.callback"])
    store.start()
    wait_until(lambda: "old.callback" in hub.receivers)
    old = hub.receivers["old.callback"]
    old_retry = store._retry_thread
    old_lttx = store._thread
    store.refresh_channels(["new.callback"])
    wait_until(lambda: "new.callback" in hub.receivers)
    assert old.closed
    assert not old_retry.is_alive() and not old_lttx.is_alive()
    assert web.CLIENTS._callbacks["__event__"] == [store._on_client_event]
    hub.emit("old.callback", -1)
    hub.emit("new.callback", 1)
    wait_until(lambda: len(store.latest()) == 1)
    assert store.latest()[0]["data"]["available"] == 1
    retry, lttx = store._retry_thread, store._thread
    store.close()
    assert not retry.is_alive() and not lttx.is_alive()
    assert all(conn.closed for conn in hub.connections)
    assert not web.CLIENTS._callbacks["__event__"]


class MemoryTx:
    def __init__(self):
        self.Q = queue.Queue()
        self.run_on = True
        self.channels = None

    def start_tx(self):
        pass

    def start_txg(self, channels):
        self.channels = channels

    def close(self):
        self.run_on = False
        self.Q.put(None)


def test_lttx_delayed_start_and_stopped_receiver_recover(environment, monkeypatch):
    web = environment.web
    available = threading.Event()
    transports = []

    def make_tx(*args, **kwargs):
        tx = MemoryTx()
        transports.append(tx)
        return tx

    monkeypatch.setattr(web, "lttx_server_reachable", available.is_set)
    monkeypatch.setattr(web, "txl", make_tx)
    store = environment.make_store(["saved.callback"])
    store.start()
    wait_until(lambda: "saved.callback" in environment.hub.receivers)
    assert transports == []
    available.set()
    wait_until(lambda: transports and transports[-1].channels == "saved.callback")
    first = transports[-1]
    first.Q.put(pack_event("trader:on_stock_asset", {"available": 10}))
    wait_until(lambda: len(store.latest()) == 1)
    first.close()
    wait_until(lambda: transports[-1] is not first and transports[-1].channels == "saved.callback")
    transports[-1].Q.put(pack_event("trader:on_stock_asset", {"available": 20}))
    wait_until(lambda: len(store.latest()) == 2)
    assert [row["data"]["available"] for row in store.latest()] == [10, 20]
    store.close()
    assert all(not tx.run_on for tx in transports)


def test_lttx_connecting_does_not_block_pipe_recovery_or_shutdown(environment, monkeypatch):
    class ConnectingTx(MemoryTx):
        def __init__(self):
            super().__init__()
            self.connecting = threading.Event()
            self.cancelled = threading.Event()

        def start_tx(self):
            self.connecting.set()
            assert self.cancelled.wait(3)

        def close(self):
            super().close()
            self.cancelled.set()

    tx = ConnectingTx()
    monkeypatch.setattr(environment.web, "lttx_server_reachable", lambda: True)
    monkeypatch.setattr(environment.web, "txl", lambda *a, **kw: tx)
    store = environment.make_store(["saved.callback"])
    environment.hub.available = False
    store.start()
    assert tx.connecting.wait(2)
    environment.hub.available = True
    wait_until(lambda: "saved.callback" in environment.hub.receivers)
    environment.hub.emit("saved.callback", 100)
    wait_until(lambda: len(store.latest()) == 1)
    retry, listener = store._retry_thread, store._thread
    store.close()
    assert not retry.is_alive() and not listener.is_alive()
    assert tx.cancelled.is_set()
