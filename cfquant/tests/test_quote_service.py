import threading
from types import SimpleNamespace

import pytest

import cfquant_web_server as web
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.protocol import loads_message, pack_request
from cfquant.quote_service import ProjectQuoteService


@pytest.fixture
def service(monkeypatch):
    callbacks, subscribed, unsubscribed, listeners = {}, [], [], []
    def subscribe(codes, callback):
        native_id = len(subscribed) + 100
        subscribed.append(codes)
        callbacks[native_id] = callback
        return native_id
    context = SimpleNamespace(subscribe_whole_quote=subscribe,
                              unsubscribe_quote=lambda native_id: unsubscribed.append(native_id))
    bridge = NormalQmtBridge(context, show=False, schedule_timer=False)
    bridge._log = lambda message: None
    def push(kind, payload, client):
        if kind == "event":
            for callback in list(listeners):
                callback(loads_message(payload))
    bridge.tx = SimpleNamespace(push=push, close=lambda: None)
    bridge.running = True
    requests = []
    lose_ack = [False]
    def upstream(params, source):
        requests.append(dict(params))
        result = bridge._dispatch("xtdata.subscribe_whole_quote_latency", params, {"client_id": "shared-service"})
        if lose_ack[0]:
            lose_ack[0] = False
            raise TimeoutError("lost subscription ack")
        return dict(result=result, bridge_id="test", channel="normal", mode="ctypes")
    def release(handle):
        return bridge._dispatch("xtdata.unsubscribe_quote", handle, {"client_id": "shared-service"})
    def probe(handle):
        return bridge._dispatch("cfquant.shared_quote_status", {}, {})
    project = ProjectQuoteService(upstream, release, probe,
                                  lambda event, cb: listeners.append(cb),
                                  lambda event, cb: listeners.remove(cb),
                                  idle_seconds=0, monitor_seconds=0)
    monkeypatch.setattr(web, "PROJECT_QUOTES", project)
    yield SimpleNamespace(project=project, bridge=bridge, callbacks=callbacks, requests=requests,
                          subscribed=subscribed, unsubscribed=unsubscribed, lose_ack=lose_ack)
    project.close()
    bridge.close()


def test_web_sdk_and_algorithm_share_source_and_independent_lifetimes(service):
    project = service.project
    web_store = web.QuoteSubscriptionStore(shared_service=project,
                                          manager=SimpleNamespace(count=lambda *args: 0, broadcast=lambda e: None))
    web_store._schedule_idle_release_locked = lambda: None
    router = web.LttxWebRouteServer()
    messages = []
    router.tx = SimpleNamespace(push=lambda kind, payload, client: messages.append((kind, loads_message(payload), client)))
    try:
        algo = project.acquire("algo:test", ["600000.SH"], purpose="algo")
        viewer = web_store.subscribe_whole({"markets": ["SH"]})
        request = loads_message(pack_request("xtdata.subscribe_whole_quote",
                                             {"code_list": ["600000.SH"], "callback_event": "quote:sdk"}, client_id="sdk-user"))
        router._handle_raw(request)
        assert messages[-1][1]["ok"]
        sdk_id = messages[-1][1]["result"]["subscribe_id"]
        assert service.subscribed == [["SH", "SZ", "BJ"]]
        assert len(service.requests) == 1
        assert project.status()["consumers"] == 3
        web_store.unsubscribe(viewer)
        assert not service.unsubscribed
        row = router._quote_routes[(str(sdk_id), "sdk-user")]
        router._release_external_quote(row, 1)
        assert not service.unsubscribed
        service.callbacks[100]({"600000.SH": {"time": 1, "lastPrice": 10, "volume": 100}})
        assert project.snapshot("600000.SH")["quote"]["volume"] == 100
        project.release(algo)
        assert service.unsubscribed == [100]
    finally:
        web_store.close()


def test_lost_subscribe_ack_retries_same_native_lease(service):
    service.lose_ack[0] = True
    with pytest.raises(TimeoutError):
        service.project.acquire("algo", ["600000.SH"], purpose="algo")
    service.project.acquire("algo", ["600000.SH"], purpose="algo")
    assert service.requests[0]["shared_lease_key"] == service.requests[1]["shared_lease_key"]
    assert len(service.subscribed) == len(service.bridge.quote_subscriptions) == 1
    service.callbacks[100]({"600000.SH": {"lastPrice": 10}})
    assert service.project.snapshot("600000.SH")


def test_health_check_recovers_a_missing_native_subscription_without_losing_consumers(service):
    service.project.acquire("algo", ["600000.SH"], purpose="algo")
    service.callbacks[100]({"600000.SH": {"lastPrice": 10}})
    old_generation = service.project.snapshot("600000.SH")["generation"]
    service.bridge._close_quote_subscriptions()
    service.project.check_connection()
    assert service.project.status()["consumers"] == 1
    assert service.project.snapshot("600000.SH") is None
    service.callbacks[100]({"600000.SH": {"lastPrice": 999}})
    assert service.project.snapshot("600000.SH") is None
    service.callbacks[101]({"600000.SH": {"lastPrice": 11}})
    assert service.project.snapshot("600000.SH")["generation"] > old_generation


def test_viewer_idle_release_cannot_release_algo_reference(service):
    service.project.acquire("algo", ["SH"], purpose="algo")
    store = web.QuoteSubscriptionStore(shared_service=service.project,
                                      manager=SimpleNamespace(count=lambda *args: 0, broadcast=lambda e: None))
    store._schedule_idle_release_locked = lambda: None
    store.subscribe_whole({"markets": ["SH"]})
    store.subscribe_whole({"markets": ["BJ"]})
    assert store.release_idle_whole_subscription()["released"]
    assert service.project.status()["consumers"] == 1
    assert not service.unsubscribed
    store.close()


def test_provider_conflict_does_not_replace_active_algorithms_source(service):
    service.project.acquire("algo", ["SH"], purpose="algo")
    with pytest.raises(ValueError, match="another bridge_id"):
        service.project.acquire("viewer", ["SH"], source={"bridge_id": "other"})
    assert len(service.subscribed) == 1


def test_diagnostic_and_algo_share_one_rpc_and_preserve_source_time(service):
    received, delivered = [], threading.Event()
    def callback(payload):
        received.append(payload)
        delivered.set()
    algo = service.project.acquire("algo", ["SZ"], purpose="algo")
    diagnostic = service.project.acquire("diagnostic", ["SZ"], callback, diagnostic=True)
    service.callbacks[100]({"000001.SZ": {"time": 1793691000000, "lastPrice": 10}})
    assert delivered.wait(2)
    assert received[0]["schema"] == "cfquant.quote_latency.v1"
    assert received[0]["qmt_callback_at_ms"] <= received[0]["shared_received_at_ms"]
    assert service.project.snapshot("000001.SZ")["quote"]["lastPrice"] == 10
    assert len(service.requests) == len(service.subscribed) == 1
    service.project.release(diagnostic)
    assert not service.unsubscribed
    service.project.release(algo)


def test_sdk_heartbeat_and_expiry_preserve_algorithm_lease(service):
    import time
    service.project.acquire("algo", ["SH"], purpose="algo")
    router = web.LttxWebRouteServer()
    messages = []
    router.tx = SimpleNamespace(push=lambda kind,payload,client:messages.append(loads_message(payload)))
    router._handle_raw(pack_request("xtdata.subscribe_whole_quote", {"code_list":["SH"], "lease_timeout":45}, client_id="sdk"))
    sid = messages[-1]["result"]["subscribe_id"]
    row = router._quote_routes[(str(sid),"sdk")]
    row["lease_deadline"] = 0
    router._handle_raw(pack_request("cfquant.quote_heartbeat", {"subscribe_ids":[sid]}, client_id="sdk"))
    assert row["lease_deadline"] > time.monotonic()
    router._expire_shared_quote_clients()
    assert service.project.status()["consumers"] == 2
    row["lease_deadline"] = 0
    router._expire_shared_quote_clients()
    assert router._quote_routes == {}
    assert service.project.status()["consumers"] == 1
    assert not service.unsubscribed


def test_native_expired_client_does_not_stop_service_feed(service):
    service.project.acquire("algo", ["SH"], purpose="algo")
    reply = service.bridge._dispatch("xtdata.subscribe_whole_quote", {"code_list":["SH"], "lease_timeout":45}, {"client_id":"gone"})
    service.bridge.quote_subscriptions[reply["subscribe_id"]]["lease_deadline"] = 0
    service.bridge._expire_whole_quote_leases()
    assert reply["subscribe_id"] not in service.bridge.quote_subscriptions
    assert service.project.status()["consumers"] == 1
    assert not service.unsubscribed
