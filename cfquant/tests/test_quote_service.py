import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from cfquant import runtime_services as web
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
    bridge._subscribe_internal_whole_quote()
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
        # The QMT bridge owns the native subscription; Web only owns delivery.
        assert not service.unsubscribed
        project.close()
        assert not service.unsubscribed
        service.bridge.close()
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


def test_last_viewer_disconnect_keeps_upstream_without_delivering_to_closed_viewer(service):
    seen = []
    project = service.project
    lease = project.acquire("viewer", ["SH"], seen.append)
    project.release(lease)
    assert project.status()["consumers"] == 0
    assert project.status()["leases"] == []
    assert project.status()["state"] == "idle"
    assert service.subscribed == [["SH", "SZ", "BJ"]]
    assert service.unsubscribed == []

    service.callbacks[100]({"600000.SH": {"time": 2, "lastPrice": 12}})
    assert seen == []
    assert project.snapshot("600000.SH") is None
    assert service.bridge.worker_event.is_set()
    assert service.bridge.quote_subscriptions == {}

    # A later viewer reuses the existing native subscription rather than
    # cancelling and re-creating it.
    next_lease = project.acquire("viewer-again", ["SH"], seen.append)
    assert len(service.subscribed) == 1
    assert service.unsubscribed == []
    project.release(next_lease)


@pytest.mark.parametrize("failure", [TimeoutError("probe timed out"),
                                    {"ready": False}, {"ready": True},
                                    {"ready": True, "lease_keys": None}])
def test_uncertain_probe_does_not_stop_delivery_or_recreate_a_healthy_lease(service, failure):
    project = service.project
    project.acquire("viewer", ["SH"])
    service.callbacks[100]({"600000.SH": {"time": 1, "lastPrice": 10}})
    generation = project.snapshot("600000.SH")["generation"]
    original_probe = project._probe_rpc
    def failed_probe(handle):
        if isinstance(failure, Exception):
            raise failure
        return failure
    project._probe_rpc = failed_probe
    try:
        project.check_connection()
        assert project.status()["health_error"]
        assert project.status()["state"] == "live"
        service.callbacks[100]({"600000.SH": {"time": 2, "lastPrice": 12}})
        assert project.snapshot("600000.SH")["quote"]["lastPrice"] == 12
    finally:
        project._probe_rpc = original_probe
    project.check_connection()
    assert project.status()["health_error"] == ""
    assert project.snapshot("600000.SH")["generation"] == generation
    assert len(service.requests) == 1
    assert service.unsubscribed == []


def test_confirmed_missing_delivery_lease_recovers_without_replacing_native_feed(service):
    project = service.project
    project.acquire("viewer", ["SH"])
    row = next(iter(service.bridge.quote_subscriptions.values()))
    row["lease_deadline"] = 0
    service.bridge._expire_whole_quote_leases()
    assert service.bridge.quote_subscriptions == {}
    assert service.unsubscribed == []
    project.check_connection()
    assert project.status()["consumers"] == 1
    assert project.status()["state"] == "live"
    assert len(service.requests) == 2
    assert len(service.bridge.quote_subscriptions) == 1
    assert len(service.subscribed) == 1
    assert service.unsubscribed == []


def test_provider_conflict_does_not_replace_active_algorithms_source(service):
    service.project.acquire("algo", ["SH"], purpose="algo")
    with pytest.raises(ValueError, match="another bridge_id"):
        service.project.acquire("viewer", ["SH"], source={"bridge_id": "other"})
    assert len(service.subscribed) == 1


@pytest.mark.parametrize("diagnostic", [False, True])
def test_web_viewer_follows_algorithm_source_and_receives_quotes(service, diagnostic):
    seen, delivered = [], threading.Event()
    def broadcast(event):
        seen.append(event)
        delivered.set()
    project = service.project
    algo = project.acquire("algo", ["SH"], purpose="algo")
    store = web.QuoteSubscriptionStore(shared_service=project, diagnostic=diagnostic,
        manager=SimpleNamespace(count=lambda *args: 1, broadcast=broadcast))
    store._schedule_idle_release_locked = lambda: None
    try:
        viewer = store.subscribe_whole({"markets": ["SH"], "bridge_id": "other", "account_id": "other-account"})
        assert viewer["bridge_id"] == "test"
        assert viewer["requested_bridge_id"] == "other"
        assert viewer["source_reused"] is True
        assert len(service.requests) == 1
        service.callbacks[100]({"600000.SH": {"lastPrice": 10}})
        assert delivered.wait(2)
        assert seen[-1]["subscribe_id"] == viewer["subscribe_id"]
        assert seen[-1]["data"]["600000.SH"]["lastPrice"] == 10
        store.unsubscribe(viewer)
        service.callbacks[100]({"600000.SH": {"lastPrice": 11}})
        assert project.snapshot("600000.SH")["quote"]["lastPrice"] == 11
        assert project.status()["consumers"] == 1
        assert not service.unsubscribed
    finally:
        store.close()
        project.release(algo)


def test_concurrent_web_and_diagnostic_viewers_follow_first_source(service):
    project = service.project
    entered, finish, second_started = threading.Event(), threading.Event(), threading.Event()
    original = project._subscribe_rpc
    def blocked_subscribe(params, source):
        entered.set()
        assert finish.wait(3)
        return original(params, source)
    project._subscribe_rpc = blocked_subscribe
    stores = [web.QuoteSubscriptionStore(shared_service=project, diagnostic=diagnostic,
        manager=SimpleNamespace(count=lambda *args: 1, broadcast=lambda e: None)) for diagnostic in (False, True)]
    for store in stores:
        store._schedule_idle_release_locked = lambda: None
    def second():
        second_started.set()
        return stores[1].subscribe_whole({"bridge_id": "other"})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(stores[0].subscribe_whole, {"bridge_id": "test"})
            try:
                assert entered.wait(2)
                other = pool.submit(second)
                assert second_started.wait(2)
            finally:
                finish.set()
            assert first.result(timeout=3)["source_reused"] is False
            assert other.result(timeout=3)["source_reused"] is True
        assert project.status()["consumers"] == 2
        assert len(service.requests) == 1
    finally:
        for store in stores:
            store.close()


def test_viewer_recovers_unconfirmed_subscription_on_original_source(service):
    original = service.project._subscribe_rpc
    sources = []
    def resolved_subscribe(params, source):
        if not source.get("bridge_id"):
            source.update(bridge_id="test", account_id="provider")
        sources.append(dict(source))
        return original(params, source)
    service.project._subscribe_rpc = resolved_subscribe
    service.lose_ack[0] = True
    with pytest.raises(TimeoutError):
        service.project.acquire("algo", ["SH"], purpose="algo")
    # Even before acknowledgement, explicit SDK requests may not retarget it.
    with pytest.raises(ValueError, match="another bridge_id"):
        service.project.acquire("sdk", ["SH"], source={"bridge_id": "other"})
    store = web.QuoteSubscriptionStore(shared_service=service.project,
        manager=SimpleNamespace(count=lambda *args: 1, broadcast=lambda e: None))
    store._schedule_idle_release_locked = lambda: None
    try:
        row = store.subscribe_whole({"bridge_id": "other"})
        assert row["bridge_id"] == "test"
        assert row["source_reused"] is True
        assert sources == [{"bridge_id": "test", "account_id": "provider"}] * 2
        assert service.requests[0]["shared_lease_key"] == service.requests[1]["shared_lease_key"]
        assert len(service.subscribed) == 1
    finally:
        store.close()


@pytest.mark.parametrize("diagnostic", [False, True])
def test_connect_renews_or_recovers_expired_viewer_without_releasing_algorithm(service, diagnostic):
    project = service.project
    project.acquire("algo", ["SH"], purpose="algo")
    store = web.QuoteSubscriptionStore(shared_service=project, diagnostic=diagnostic,
        manager=SimpleNamespace(count=lambda *args: 0, broadcast=lambda e: None))
    store._schedule_idle_release_locked = lambda: None
    try:
        body = {"markets": ["SH"], "bridge_id": "other"}
        first = store.subscribe_whole(body)
        body["resume_subscribe_id"] = first["subscribe_id"]
        resumed = store.subscribe_whole(body)
        assert resumed["subscribe_id"] == first["subscribe_id"]
        assert resumed["already_subscribed"] is True
        assert not store.release_idle_whole_subscription()["released"]
        # Simulate the renewed connection window expiring before connecting.
        store._subscriptions[first["subscribe_id"]]["connect_deadline"] = time.time() - 1
        assert store.release_idle_whole_subscription()["released"]
        restored = store.subscribe_whole(body)
        assert restored["subscribe_id"] != first["subscribe_id"]
        assert restored["already_subscribed"] is False
        assert restored["source_reused"] is True
        assert not store.release_idle_whole_subscription()["released"]
        assert project.status()["consumers"] == 2
        assert len(service.requests) == 1
        # An explicit stop still releases immediately during the connect window.
        renewed = store.subscribe_whole(dict(body, resume_subscribe_id=restored["subscribe_id"]))
        store.unsubscribe(renewed)
        assert project.status()["consumers"] == 1
    finally:
        store.close()


def test_stopping_expired_shared_id_never_forwards_native_unsubscribe(service):
    project = service.project
    project.acquire("algo", ["SH"], purpose="algo")
    store = web.QuoteSubscriptionStore(shared_service=project,
        manager=SimpleNamespace(count=lambda *args: 0, broadcast=lambda e: None))
    store._schedule_idle_release_locked = lambda: None
    def reject_native_unsubscribe(*args, **kwargs):
        pytest.fail("expired shared ID must never be sent to QMT")
    store._request_unsubscribe = reject_native_unsubscribe
    try:
        viewer = store.subscribe_whole({"markets": ["SH"]})
        assert store.release_idle_whole_subscription()["released"]
        reply = store.unsubscribe(dict(viewer, shared_only=True))
        assert reply["already_released"] is True
        # A native single-symbol subscription with the same number is unrelated.
        store._subscriptions[viewer["subscribe_id"]] = dict(subscribe_id=viewer["subscribe_id"], kind="quote")
        assert store.unsubscribe(dict(viewer, shared_only=True))["result"] is False
        assert viewer["subscribe_id"] in store._subscriptions
        assert project.status()["consumers"] == 1
    finally:
        store._subscriptions.clear()
        store.close()


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
