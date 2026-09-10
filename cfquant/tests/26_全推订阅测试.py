"""Whole-quote regressions using fake QMT and RPC; never connect to a live account."""
import ast
import datetime as dt
import json
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace

import pytest

import cfquant_web_server as web
from cfquant import xtdata
from cfquant import level2
from cfquant.normal_bridge import COALESCED_QUERY_ACTIONS, NormalQmtBridge
from cfquant.pipe_bridge import PipeNormalQmtBridge
from cfquant.protocol import loads_message, pack_event, pack_request, pack_response
from cfquant.tx_trade_bridge import TxTradeBridge


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))


def lite_bridge_class(path):
    tree = ast.parse(path.read_text(encoding="gbk"))
    tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name in ("NormalQmtBridge", "PipeNormalQmtBridge")]
    namespace = dict(TxTradeBridge=TxTradeBridge, queue=queue, threading=threading,
                     time=time, dt=dt, json=json, loads_message=loads_message,
                     pack_event=pack_event, pack_response=pack_response,
                     COALESCED_QUERY_ACTIONS=COALESCED_QUERY_ACTIONS,
                     DEFAULT_PIPE_NAME="offline-test")
    namespace.update({key: value for key, value in vars(level2).items() if not key.startswith("__")})
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace["PipeNormalQmtBridge"]


class RecordingTx:
    def __init__(self):
        self.messages = []

    def push(self, kind, payload, client_id):
        self.messages.append((kind, loads_message(payload), client_id))

    def close(self):
        pass


class FakeQmt:
    def __init__(self):
        self.subscribed = []
        self.unsubscribed = []
        self.callbacks = {}

    def subscribe_whole_quote(self, codes, callback):
        native_id = 100 + len(self.subscribed)
        self.subscribed.append(codes)
        self.callbacks[native_id] = callback
        return native_id

    def unsubscribe_quote(self, native_id):
        self.unsubscribed.append(native_id)

    def subscribe_quote(self, code, period, dividend_type, result_type, callback):
        return self.subscribe_whole_quote([code], callback)


@pytest.fixture(params=[NormalQmtBridge, PipeNormalQmtBridge] + LITE_PATHS,
                ids=["lttx", "ctypes"] + [path.stem for path in LITE_PATHS])
def bridge(request):
    cls = lite_bridge_class(request.param) if isinstance(request.param, Path) else request.param
    result = cls(FakeQmt(), show=False, schedule_timer=False)
    result._log = lambda message: None
    result.tx = RecordingTx()
    result.running = True
    yield result
    result.close()


def rpc(bridge, action, params=None, client="client-a"):
    message = loads_message(pack_request(action, params=params or {}, client_id=client))
    return bridge._dispatch(action, message["params"], message)


@pytest.mark.parametrize("codes", [["BJ"], ["SH", "SZ", "BJ"], ["830799.BJ"],
                                   ["SF", "rb2610.SF", "CUSTOM"], [], ["bj", "BJ", "bj"]])
def test_whole_quote_forwards_requested_list_without_whitelist(bridge, codes):
    result = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": codes})
    assert bridge.context.subscribed == [codes]
    assert result["internal_subscribe_id"] == 100
    assert result["publish_existing"] is False
    assert bridge.quote_subscriptions[result["subscribe_id"]]["code_list"] == codes


def test_stock_list_alias_is_forwarded(bridge):
    rpc(bridge, "xtdata.subscribe_whole_quote", {"stock_list": ["BJ"]})
    assert bridge.context.subscribed == [["BJ"]]


def test_dispatch_uses_explicit_params(bridge):
    bridge._dispatch("xtdata.subscribe_whole_quote", {"code_list": ["BJ"]}, {"client_id": "client-a"})
    assert bridge.context.subscribed == [["BJ"]]


def test_subscriptions_and_callbacks_are_independent(bridge):
    bridge._subscribe_internal_whole_quote()
    first = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["BJ"]})
    second = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["rb2610.SF"]}, client="client-b")
    assert first["subscribe_id"] != second["subscribe_id"]
    bridge._on_whole_quote({"000001.SZ": {"lastPrice": 10}})
    assert bridge.tx.messages == []
    payload = {"830799.BJ": {"lastPrice": 12}}
    bridge.context.callbacks[first["internal_subscribe_id"]](payload)
    kind, event, client = bridge.tx.messages.pop()
    assert (kind, client) == ("event", "client-a")
    assert event["subscription_id"] == first["subscribe_id"]
    assert event["data"] == payload
    payload = {"rb2610.SF": {"lastPrice": 3000}}
    bridge.context.callbacks[second["internal_subscribe_id"]](payload)
    assert bridge.tx.messages[-1][1]["data"] == payload
    assert bridge.tx.messages[-1][2] == "client-b"


def test_unsubscribe_releases_native_id_and_ignores_late_callbacks(bridge):
    first = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["BJ"]})
    second = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["SF"]})
    assert rpc(bridge, "xtdata.unsubscribe_quote", {"subscribe_id": str(first["subscribe_id"])}) is True
    assert bridge.context.unsubscribed == [first["internal_subscribe_id"]]
    bridge.context.callbacks[first["internal_subscribe_id"]]({"830799.BJ": {}})
    assert bridge.tx.messages == []
    assert bridge.whole_quote_publish_enabled is True
    assert second["subscribe_id"] in bridge.quote_subscriptions
    rpc(bridge, "xtdata.unsubscribe_quote", {"subscribe_id": second["subscribe_id"]})
    assert bridge.whole_quote_publish_enabled is False
    assert bridge.whole_quote_publish_sub_id is None


def test_subscription_failure_is_a_queued_error_not_false_success(bridge):
    def fail(*args, **kwargs):
        raise RuntimeError("QMT market unavailable")

    bridge.context.subscribe_whole_quote = fail
    bridge._handle_raw_from_thread(pack_request("xtdata.subscribe_whole_quote", {"code_list": ["BJ"]}, client_id="client-a"))
    assert bridge.tx.messages == []
    assert bridge.request_queue.qsize() == 1
    assert bridge._drain_requests("test") == 1
    kind, response, client = bridge.tx.messages[-1]
    assert (kind, client) == ("response", "client-a")
    assert response["ok"] is False
    assert "QMT market unavailable" in response["error"]["message"]
    assert bridge.quote_subscriptions == {}


def test_subscription_runs_in_dispatch_queue_and_responds_once(bridge):
    bridge._handle_raw_from_thread(pack_request("xtdata.subscribe_whole_quote", {"code_list": ["BJ"]}, client_id="client-a"))
    assert bridge.context.subscribed == []
    assert bridge._drain_requests("test") == 1
    assert bridge.context.subscribed == [["BJ"]]
    assert len(bridge.tx.messages) == 1
    response = bridge.tx.messages[0][1]
    assert response["ok"] is True
    bridge._handle_raw_from_thread(pack_request("xtdata.unsubscribe_quote", {"subscribe_id": response["result"]["subscribe_id"]}, client_id="client-a"))
    assert bridge.context.unsubscribed == []
    assert bridge._drain_requests("test") == 1
    assert bridge.context.unsubscribed == [100]
    assert len(bridge.tx.messages) == 2


def test_native_positional_callback_signature(bridge):
    calls = []
    def positional(*args):
        calls.append(args)
        return 200
    bridge.context.subscribe_whole_quote = positional
    rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["BJ"]})
    assert len(calls) == 1
    assert calls[0][0] == ["BJ"]
    calls[0][1]({"830799.BJ": {}})
    assert bridge.tx.messages[0][1]["data"] == {"830799.BJ": {}}


@pytest.mark.parametrize("invalid_id", [None, -1, False])
def test_invalid_native_id_does_not_register_subscription(bridge, invalid_id):
    bridge.context.subscribe_whole_quote = lambda *args, **kwargs: invalid_id
    with pytest.raises(RuntimeError, match="QMT subscribe_whole_quote failed"):
        rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["BJ"]})
    assert bridge.quote_subscriptions == {}


def test_unsubscribe_failure_preserves_subscription_for_retry(bridge):
    result = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["BJ"]})
    unsubscribe = bridge.context.unsubscribe_quote
    bridge.context.unsubscribe_quote = lambda native_id: -1
    with pytest.raises(RuntimeError, match="QMT unsubscribe_quote failed"):
        rpc(bridge, "xtdata.unsubscribe_quote", {"subscribe_id": result["subscribe_id"]})
    assert result["subscribe_id"] in bridge.quote_subscriptions
    bridge.context.unsubscribe_quote = unsubscribe
    rpc(bridge, "xtdata.unsubscribe_quote", {"subscribe_id": result["subscribe_id"]})
    assert bridge.quote_subscriptions == {}


def test_close_releases_public_and_internal_quotes(bridge):
    bridge._subscribe_internal_whole_quote()
    rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["BJ"]})
    rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["CUSTOM"]})
    callbacks = list(bridge.context.callbacks.values())
    bridge.close()
    assert sorted(bridge.context.unsubscribed) == [100, 101, 102]
    assert bridge.quote_subscriptions == {}
    for callback in callbacks:
        callback({"830799.BJ": {}})


def test_legacy_single_quote_is_not_broken_by_whole_quote(bridge):
    single = rpc(bridge, "xtdata.subscribe_quote", {"stock_code": "000001.SZ"})
    whole = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["BJ"]})
    bridge._on_whole_quote({"000001.SZ": {"lastPrice": 10}, "600000.SH": {"lastPrice": 12}})
    assert bridge.tx.messages == []
    bridge.context.callbacks[single["internal_subscribe_id"]]({"000001.SZ": {"lastPrice": 10}})
    assert len(bridge.tx.messages) == 1
    assert bridge.tx.messages[0][1]["subscription_id"] == single["subscribe_id"]
    assert set(bridge.tx.messages[0][1]["data"]) == {"000001.SZ"}
    rpc(bridge, "xtdata.unsubscribe_quote", {"subscribe_id": single["subscribe_id"]})
    assert bridge.context.unsubscribed == [single["internal_subscribe_id"]]
    assert whole["subscribe_id"] in bridge.quote_subscriptions


def test_sdk_passes_list_and_registers_callback(monkeypatch, bridge):
    callbacks = {}
    client = SimpleNamespace(
        request=lambda action, params: rpc(bridge, action, params),
        add_callback=lambda event, callback: callbacks.update({event: callback}),
        remove_callback=lambda event, callback: callbacks.pop(event),
    )
    monkeypatch.setattr(xtdata, "get_client", lambda: client)
    monkeypatch.setattr(xtdata, "_subscription_callbacks", {})
    received = []
    sub_id = xtdata.subscribe_whole_quote(["BJ", "rb2610.SF"], callback=received.append)
    bridge.context.callbacks[100]({"rb2610.SF": {"lastPrice": 3000}})
    event = bridge.tx.messages[-1][1]
    callbacks[event["event"]](event["data"])
    assert received == [{"rb2610.SF": {"lastPrice": 3000}}]
    xtdata.unsubscribe_quote(sub_id)
    assert callbacks == {}


@pytest.fixture
def store(monkeypatch):
    store = web.QuoteSubscriptionStore()
    calls = []
    monkeypatch.setattr(store, "start", lambda: None)
    monkeypatch.setattr(store, "_schedule_idle_release_locked", lambda: None)
    monkeypatch.setattr(web.WS_QUOTES, "count", lambda: 1)

    def request(action, params, **kwargs):
        calls.append((action, params, kwargs))
        return {"result": {"subscribe_id": str(len(calls)), "publish_existing": False},
                "bridge_id": kwargs.get("bridge_id") or "default", "channel": "normal", "mode": "lttx"}

    def unsubscribe(bridge_id, channel, sub_id, **kwargs):
        # RPC must not hold the event-store lock: quote callbacks use another thread.
        acquired = []
        def check_lock():
            locked = store._lock.acquire(timeout=0.2)
            acquired.append(locked)
            if locked:
                store._lock.release()
        thread = threading.Thread(target=check_lock)
        thread.start()
        thread.join(timeout=1)
        assert acquired == [True]
        calls.append(("xtdata.unsubscribe_quote", {"subscribe_id": sub_id}, kwargs))
        return True

    monkeypatch.setattr(web, "data_provider_request", request)
    monkeypatch.setattr(store, "_request_unsubscribe", unsubscribe)
    return SimpleNamespace(quotes=store, calls=calls)


@pytest.mark.parametrize("value, expected", [("BJ, SF,rb2610.SF,CUSTOM", ["BJ", "SF", "rb2610.SF", "CUSTOM"]),
                                            (["BJ", "CUSTOM", "BJ"], ["BJ", "CUSTOM", "BJ"]),
                                            ([], []), ("", []), (None, None)])
def test_web_forwards_arbitrary_markets_codes_and_empty_lists(store, value, expected):
    result = store.quotes.subscribe_whole({"markets": value})
    assert store.calls[0][1] == {"code_list": expected}
    assert result["markets"] == expected


def test_web_defaults_only_when_argument_is_omitted(store):
    assert store.quotes.subscribe_whole({})["markets"] == ["SH", "SZ"]


def test_web_code_list_alias_and_chinese_comma(store):
    value = "BJ\uff0crb2610.SF"
    assert store.quotes.subscribe_whole({"code_list": value})["markets"] == ["BJ", "rb2610.SF"]


def test_web_replaces_subscription_when_markets_change(store):
    first = store.quotes.subscribe_whole({"markets": ["SH", "SZ"]})
    second = store.quotes.subscribe_whole({"markets": ["BJ"]})
    assert [call[0] for call in store.calls] == ["xtdata.subscribe_whole_quote", "xtdata.unsubscribe_quote", "xtdata.subscribe_whole_quote"]
    assert second["markets"] == ["BJ"]
    assert second["already_subscribed"] is False
    assert first["subscribe_id"] not in store.quotes._subscriptions


def test_web_identical_subscription_can_be_reused(store):
    first = store.quotes.subscribe_whole({"markets": ["BJ"]})
    second = store.quotes.subscribe_whole({"markets": ["BJ"]})
    assert len(store.calls) == 1
    assert second["subscribe_id"] == first["subscribe_id"]
    assert second["already_subscribed"] is True


def test_web_concurrent_subscriptions_are_coalesced(store, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = web.data_provider_request
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return original(*args, **kwargs)
    monkeypatch.setattr(web, "data_provider_request", delayed)
    results = []
    def subscribe():
        results.append(store.quotes.subscribe_whole({"markets": ["BJ"]}))
    first = threading.Thread(target=subscribe)
    second = threading.Thread(target=subscribe)
    first.start()
    try:
        assert entered.wait(timeout=1)
        second.start()
    finally:
        release.set()
        first.join(timeout=3)
        if second.ident is not None:
            second.join(timeout=3)
    assert not first.is_alive() and not second.is_alive()
    assert len(results) == 2
    assert results[0]["subscribe_id"] == results[1]["subscribe_id"]
    assert len(store.calls) == 1


def test_web_different_bridge_is_not_reused(store):
    store.quotes.subscribe_whole({"markets": ["BJ"], "bridge_id": "first"})
    result = store.quotes.subscribe_whole({"markets": ["BJ"], "bridge_id": "second"})
    assert result["bridge_id"] == "second"
    assert len(store.calls) == 3


def test_web_disconnected_viewer_is_released_before_new_subscription(store, monkeypatch):
    store.quotes.subscribe_whole({"markets": ["BJ"]})
    monkeypatch.setattr(web.WS_QUOTES, "count", lambda: 0)
    store.quotes.subscribe_whole({"markets": ["BJ"]})
    assert len(store.calls) == 3


def test_web_does_not_report_success_when_qmt_rejects_market(store, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("QMT market unavailable")
    monkeypatch.setattr(web, "data_provider_request", fail)
    with pytest.raises(RuntimeError, match="QMT market unavailable"):
        store.quotes.subscribe_whole({"markets": ["CUSTOM"]})
    assert store.quotes._subscriptions == {}
