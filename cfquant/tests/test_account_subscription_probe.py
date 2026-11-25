"""Control probes under blocked business work, without real QMT or orders."""
import threading
import time
from types import SimpleNamespace

import pytest

from cfquant.client import CfquantError, CfquantTimeout
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.protocol import loads_message, pack_request
from cfquant.qmt_pipe_runtime import ManagedPipeRuntime
from cfquant.xttrader import XtQuantTrader
from cfquant.tests.test_subscription_congestion import bridge
from cfquant.tests.test_lite_qmt_dispatch import lite, enqueue


PROBE = "cfquant.account_subscription_status"
PARAMS = {"account": {"account_id": "PAPER_A", "account_type": "STOCK", "bridge_id": "test"}}


def test_probe_only_confirms_completed_setup_and_correct_client(bridge):
    instance = bridge.instance
    msg = {"client_id": "offline-client"}
    original = instance.context.set_account
    def set_account(*args):
        assert instance._account_subscription_status(PARAMS, msg) == {"subscribed": False}
        original(*args)
    instance.context.set_account = set_account
    assert bridge.dispatch(PARAMS)["ok"]
    assert instance._account_subscription_status(PARAMS, msg) == {"subscribed": True}
    assert instance._account_subscription_status(PARAMS, {"client_id": "other"}) == {"subscribed": False}
    other_type = {"account": dict(PARAMS["account"], account_type="CREDIT")}
    assert instance._account_subscription_status(other_type, msg) == {"subscribed": False}
    instance._unsubscribe_account({}, msg)
    assert instance._account_subscription_status(PARAMS, msg) == {"subscribed": False}
    assert not instance.confirmed_account_subscriptions


def test_normal_probe_finishes_while_native_query_is_blocked():
    entered, release = threading.Event(), threading.Event()
    responses = []
    context = SimpleNamespace(set_account=lambda *a: None, set_auto_trade_callback=lambda *a: None)
    instance = NormalQmtBridge(context, show=False, order_meta_enabled=False, schedule_timer=False)
    instance.tx = SimpleNamespace(push=lambda _, raw, target: responses.append(loads_message(raw)))
    instance._subscribe_account(PARAMS, {"client_id": "test-client"})
    dispatch = instance._dispatch
    def blocked(action, params, msg):
        if action == "xttrader.query_stock_asset":
            entered.set()
            assert release.wait(3)
            return {}
        return dispatch(action, params, msg)
    instance._dispatch = blocked
    instance._handle_raw_from_thread(pack_request("xttrader.query_stock_asset", PARAMS, client_id="test-client"))
    msg, received, _ = instance.request_queue.get_nowait()
    worker = threading.Thread(target=instance._drain_single_request, args=("test", msg, received))
    worker.start()
    try:
        assert entered.wait(2)
        instance._handle_raw_from_thread(pack_request(PROBE, PARAMS, client_id="test-client", request_id="probe"))
        assert responses[-1]["id"] == "probe"
        assert responses[-1]["result"] == {"subscribed": True}
        assert not release.is_set() and worker.is_alive()
        assert instance.request_queue.empty()
        instance._unsubscribe_account(PARAMS, {"client_id": "test-client"})
        instance._handle_raw_from_thread(pack_request(PROBE, PARAMS, client_id="test-client"))
        assert responses[-1]["result"] == {"subscribed": False}
        assert instance._account_subscriber_status() == {}
    finally:
        release.set()
        worker.join(3)
        instance._unsubscribe_account({}, {"client_id": "test-client"})
        instance._release_auto_trade_callback()


def test_fast_probe_still_obeys_managed_runtime_gate():
    instance = NormalQmtBridge(None, show=False, order_meta_enabled=False, schedule_timer=False)
    runtime = ManagedPipeRuntime({"runtime_key": "test", "mode": "lite", "generation": "test"})
    runtime.active = True
    runtime.approved = False
    instance._dispatch = runtime.dispatch(instance._dispatch)
    responses = []
    instance.tx = SimpleNamespace(push=lambda _, raw, target: responses.append(loads_message(raw)))
    instance._handle_raw_from_thread(pack_request(PROBE, PARAMS, client_id="test-client"))
    assert responses[-1]["ok"] is False
    assert responses[-1]["error"]["code"] == "ACCOUNT_MODE_UNCONFIRMED"
    assert instance.request_queue.empty()


def test_embedded_probe_does_not_need_qmt_timer_or_native_setup(lite):
    params = {"account": {"account_id": "TEST_ONLY", "account_type": "CREDIT"}}
    enqueue(lite, "xttrader.subscribe", params=params)
    lite.ns["cfquant_ctype_trade_timer"](lite.context)
    before = list(lite.context.calls)
    enqueue(lite, PROBE, params=params)
    assert lite.tx.responses[-1]["result"] == {"subscribed": True}
    lite.bridge._unsubscribe_account(params, {"client_id": "fake-client"})
    enqueue(lite, PROBE, params=params)
    assert lite.tx.responses[-1]["result"] == {"subscribed": False}
    assert lite.context.calls == before


def test_web_probe_bypasses_same_client_query_and_needs_both_registrations(monkeypatch):
    from cfquant import runtime_services as web
    monkeypatch.setattr(web, "WEB_CONFIG", None)
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kw: "test")
    route = web.LttxWebRouteServer()
    entered, release, probe_done, write_done = [threading.Event() for _ in range(4)]
    replies, calls = {}, []
    remote_subscribed = [True]
    def push(_, raw, target):
        msg = loads_message(raw)
        replies[msg["id"]] = msg
        if msg["id"].startswith("probe"):
            probe_done.set()
        if msg["id"] == "unsubscribe":
            write_done.set()
    route.tx = SimpleNamespace(push=push)
    def dispatch(msg):
        calls.append(msg["id"])
        if msg["id"] == "block":
            entered.set()
            assert release.wait(3)
        return ({"subscribed": remote_subscribed[0]} if msg["action"] == PROBE else 0), {}
    monkeypatch.setattr(web, "route_external_lttx_request", dispatch)
    def send(identity, action, client="test-client"):
        route._enqueue_raw(pack_request(action, PARAMS, client_id=client, request_id=identity, timeout=2), route.tx)
    subscription = {"client_id": "test-client", "params": PARAMS}
    route._remember_external_subscription("xttrader.subscribe", subscription, 0)
    try:
        send("block", "xttrader.query_stock_asset")
        assert entered.wait(2)
        send("unsubscribe", "xttrader.unsubscribe")
        send("probe-healthy", PROBE)
        assert probe_done.wait(1)
        assert replies["probe-healthy"]["result"] == {"subscribed": True}
        assert not write_done.is_set()
        # Another caller must not inherit the shared upstream registration.
        probe_done.clear()
        send("probe-other", PROBE, client="other")
        assert probe_done.wait(1)
        assert replies["probe-other"]["result"] == {"subscribed": False}
        assert "probe-other" not in calls
        # QMT restarted but the local Web registration is still present.
        remote_subscribed[0] = False
        probe_done.clear()
        send("probe-qmt-restarted", PROBE)
        assert probe_done.wait(1)
        assert replies["probe-qmt-restarted"]["result"] == {"subscribed": False}
        release.set()
        assert write_done.wait(2)
        assert calls.index("block") < calls.index("unsubscribe")
        # Web registration removed: never restore it from a read-only probe.
        remote_subscribed[0] = True
        probe_done.clear()
        send("probe-web-missing", PROBE)
        assert probe_done.wait(1)
        assert replies["probe-web-missing"]["result"] == {"subscribed": False}
        assert "probe-web-missing" not in calls
    finally:
        release.set()
        route.close()


@pytest.mark.parametrize("message", ["unsupported action: ", "unsupported external web_lttx action: "])
def test_legacy_peer_fallback_is_cached_and_rechecked(message):
    trader = XtQuantTrader()
    calls = []
    legacy = [True]
    def request(action, params, **kwargs):
        calls.append(action)
        if action == PROBE:
            if legacy[0]:
                raise CfquantError(message + PROBE)
            return {"subscribed": True}
        return 0
    client = SimpleNamespace(request=request)
    stop = threading.Event()
    for _ in range(2):
        assert trader._renew_account_subscription(client, PARAMS["account"], "key", stop, {}) == 0
    assert calls == [PROBE, "xttrader.subscribe", "xttrader.subscribe"]
    trader._subscription_probe_after["key"] = time.monotonic() - 1
    legacy[0] = False
    assert trader._renew_account_subscription(client, PARAMS["account"], "key", stop, {}) == 0
    assert calls[-1] == PROBE


@pytest.mark.parametrize("error", [CfquantTimeout("busy"), CfquantError("ACCOUNT_MODE_UNCONFIRMED")])
def test_probe_failure_does_not_trigger_mutation_or_capability_downgrade(error):
    trader = XtQuantTrader()
    calls = []
    def request(action, params, **kwargs):
        calls.append(action)
        raise error
    with pytest.raises(type(error)):
        trader._renew_account_subscription(SimpleNamespace(request=request), PARAMS["account"],
                                          "key", threading.Event(), {})
    assert calls == [PROBE]
    assert not trader._subscription_probe_after


def test_new_web_preserves_old_qmt_unsupported_action_for_sdk(monkeypatch):
    from cfquant import runtime_services as web
    monkeypatch.setattr(web, "WEB_CONFIG", None)
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kw: "test")
    monkeypatch.setattr(web, "resolve_account_mode", lambda *a, **kw: "ctypes")
    monkeypatch.setattr(web, "resolve_market_route_for_request", lambda **kw: ("test", None))
    def request(*args, **kw):
        raise CfquantError("unsupported action: " + PROBE)
    monkeypatch.setattr(web, "CLIENTS", SimpleNamespace(request=request))
    with pytest.raises(CfquantError, match="^unsupported action: "):
        web.route_external_lttx_request({"action": PROBE, "params": PARAMS})


def test_failed_web_subscribe_cannot_create_a_healthy_probe(monkeypatch):
    from cfquant import runtime_services as web
    route = web.LttxWebRouteServer()
    for result in (False, -1):
        route._remember_external_subscription("xttrader.subscribe", {"client_id": "test", "params": PARAMS}, result)
        assert not route._account_subscribers


def test_web_queue_diagnostics_survive_error_response():
    from cfquant.rpc_timing import RpcTiming
    output = {}
    timing = RpcTiming(output, "probe-test")
    timing.sent()
    timing.received({"ok": False, "meta": {"route": "web_lttx", "web_queue_ms": 123}})
    timing.finish()
    assert output["request_id"] == "probe-test"
    assert output["web"] == {"queue_ms": 123, "route": "web_lttx"}
    assert output["rpc"]["response_received"] is True
    assert output["rpc"]["response_ok"] is False
