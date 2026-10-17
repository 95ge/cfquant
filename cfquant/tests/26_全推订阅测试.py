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
from cfquant.protocol import loads_message, pack_event, pack_request, pack_response, pack_quote_latency_event, pack_whole_quote_event, decode_value
from cfquant.callback_dispatcher import dispatch_callbacks
from cfquant.protocol import encode_response_result, request_expired
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
                     encode_response_result=encode_response_result, request_expired=request_expired,
                     pack_quote_latency_event=pack_quote_latency_event,
                     pack_whole_quote_event=pack_whole_quote_event,
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


def test_diagnostic_subscription_is_independent_and_preserves_quotes(bridge):
    ordinary = rpc(bridge, "xtdata.subscribe_whole_quote", {"code_list": ["SZ"]})
    diagnostic = rpc(bridge, "xtdata.subscribe_whole_quote_latency", {"code_list": ["SZ"]})
    assert ordinary["subscribe_id"] != diagnostic["subscribe_id"]
    data = {"000001.SZ": {"time": 1792112400000, "lastPrice": 10, "bidPrice": [9, 8]}}
    begin = time.time() * 1000
    bridge.context.callbacks[diagnostic["internal_subscribe_id"]](data)
    _, event, client = bridge.tx.messages[-1]
    assert client == "client-a"
    assert event["data"]["quotes"] == data
    assert event["data"]["schema"] == "cfquant.quote_latency.v1"
    assert begin <= event["data"]["qmt_callback_at_ms"] <= event["data"]["qmt_push_at_ms"] <= time.time() * 1000
    bridge.context.callbacks[ordinary["internal_subscribe_id"]](data)
    assert bridge.tx.messages[-1][1]["data"] == data
    rpc(bridge, "xtdata.unsubscribe_quote", {"subscribe_id": diagnostic["subscribe_id"]})
    count = len(bridge.tx.messages)
    bridge.context.callbacks[diagnostic["internal_subscribe_id"]](data)
    assert len(bridge.tx.messages) == count
    assert ordinary["subscribe_id"] in bridge.quote_subscriptions


def test_diagnostic_first_snapshot_keeps_callback_timestamp(bridge):
    data = {"000001.SZ": {"lastPrice": 10}}
    called = []
    def subscribe(codes, callback):
        callback(data)
        called.append(time.time() * 1000)
        return 777
    bridge.context.subscribe_whole_quote = subscribe
    rpc(bridge, "xtdata.subscribe_whole_quote_latency", {"code_list": ["SZ"]})
    payload = bridge.tx.messages[-1][1]["data"]
    assert payload["quotes"] == data
    assert payload["qmt_callback_at_ms"] <= payload["qmt_push_at_ms"] <= called[0]


@pytest.mark.parametrize('kind', ['whole_quote', 'whole_quote_latency'])
def test_whole_quote_freezes_native_snapshot_and_does_not_preconvert(bridge, monkeypatch, kind):
    data = {"000001.SZ": {"lastPrice": 10, "bidPrice": [9, 8]}}
    def unexpected_conversion(value):
        raise AssertionError("plain quote must not run recursive quote_plain")
    monkeypatch.setitem(bridge._subscribe_native_quote.__func__.__globals__, 'quote_plain', unexpected_conversion)
    def subscribe(codes, callback):
        callback(data)
        data['000001.SZ']['lastPrice'] = 99
        data['000001.SZ']['bidPrice'][0] = 98
        return 777
    bridge.context.subscribe_whole_quote = subscribe
    rpc(bridge, 'xtdata.subscribe_' + kind, {'code_list': ['SZ']})
    event = bridge.tx.messages[-1][1]
    quotes = event['data']['quotes'] if kind == 'whole_quote_latency' else event['data']
    assert quotes == {'000001.SZ': {'lastPrice': 10, 'bidPrice': [9, 8]}}
    assert event['meta']['quote_json_plain'] is True
    if kind == 'whole_quote_latency':
        assert event['data']['qmt_encoding'] == 'direct_json'
        assert event['data']['qmt_encode_ms'] >= 0


def test_diagnostic_nonfinite_quote_uses_compatible_encoding(bridge):
    result = rpc(bridge, 'xtdata.subscribe_whole_quote_latency', {'code_list': ['SZ']})
    bridge.context.callbacks[result['internal_subscribe_id']]({
        '000001.SZ': {'lastPrice': float('nan'), 'askPrice': [float('inf'), 10]}})
    event = bridge.tx.messages[-1][1]
    assert event['data']['quotes']['000001.SZ'] == {'lastPrice': None, 'askPrice': [None, 10]}
    assert event['data']['qmt_encoding'] == 'compatible_json'
    assert not event['meta'].get('quote_json_plain')


def test_ordinary_full_batches_reach_callback_once_in_order(bridge):
    result = rpc(bridge, 'xtdata.subscribe_whole_quote', {'code_list': ['SH', 'SZ']})
    received = []
    callbacks = {result['callback_event']: [received.append]}
    batches = [{'%06d.SZ' % i: {'lastPrice': i / 100, 'volume': i} for i in range(26475)},
               {'000001.SZ': {'lastPrice': 99.125, 'volume': 999}}]
    for batch in batches:
        bridge.context.callbacks[result['internal_subscribe_id']](batch)
        event = bridge.tx.messages[-1][1]
        assert event['meta']['quote_json_plain'] is True
        dispatch_callbacks(callbacks, event, lambda: True)
    assert len(bridge.tx.messages) == len(received) == 2
    assert received == batches
    assert list(received[1]) == ['000001.SZ']  # No merging with the preceding batch.


def test_ordinary_special_values_preserve_legacy_callback_contract(bridge):
    np = pytest.importorskip('numpy')
    result = rpc(bridge, 'xtdata.subscribe_whole_quote', {'code_list': ['SZ']})
    batch = {'000001.SZ': {'lastPrice': np.float64('nan'), 'askPrice': np.array([float('inf'), 10]),
                          'volume': np.uint64(2**63 + 17), 'raw': b'\x00\xff', 'custom': SimpleNamespace(value=2)}}
    expected = decode_value(loads_message(pack_event('quote:test', level2.quote_plain(batch)))['data'])
    bridge.context.callbacks[result['internal_subscribe_id']](batch)
    event = bridge.tx.messages[-1][1]
    assert not event['meta'].get('quote_json_plain')
    received = []
    dispatch_callbacks({result['callback_event']: [received.append]}, event, lambda: True)
    quote = received[0]['000001.SZ']
    assert quote['lastPrice'] is None and quote['askPrice'] == [None, 10]
    assert quote['volume'] == expected['000001.SZ']['volume'] == 2**63 + 17
    assert quote['raw'] == expected['000001.SZ']['raw'] == b'\x00\xff'
    assert vars(quote['custom']) == vars(expected['000001.SZ']['custom'])


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


@pytest.mark.parametrize('plain', [True, False])
def test_web_route_preserves_whole_quote_batches_and_encoding_marker(monkeypatch, plain):
    messages, received = [], []
    router = web.LttxWebRouteServer()
    router.tx = SimpleNamespace(push=lambda kind, raw, channel: messages.append((kind, loads_message(raw), channel)))
    batch = {'000001.SZ': {'lastPrice': 10.25, 'volume': 2**63 + 17, 'bidPrice': [10, 9]},
             '600000.SH': {'lastPrice': 8.6}}
    if not plain:
        batch['000001.SZ']['raw'] = b'\x00\xff'
    def request(msg):
        router._on_quote_event({'subscription_id': 42, 'event': msg['params']['callback_event'],
                               'data': batch, 'meta': {'quote_json_plain': True} if plain else {}})
        return {'subscribe_id': 42}, {'bridge_id': 'test', 'channel': 'normal', 'mode': 'lite'}
    monkeypatch.setattr(web, 'route_external_lttx_request', request)
    monkeypatch.setattr(web.CLIENTS, 'request', lambda *args, **kwargs: True)
    if plain:
        def unexpected_pack(*args, **kwargs):
            raise AssertionError('Web must not run generic encoding for a plain whole-quote batch')
        monkeypatch.setattr(web, 'pack_event', unexpected_pack)
    router._handle_raw(pack_request('xtdata.subscribe_whole_quote',
        {'code_list': ['SH', 'SZ'], 'callback_event': 'quote:sdk'}, client_id='sdk'))
    assert [message[0] for message in messages] == ['event', 'response']
    event = messages[0][1]
    assert bool(event['meta'].get('quote_json_plain')) is plain
    assert messages[0][2] == 'sdk'
    dispatch_callbacks({'quote:sdk': [received.append]}, event, lambda: True)
    assert received == [batch]
    sid = messages[-1][1]['result']['subscribe_id']
    assert event['subscription_id'] == sid
    router._handle_raw(pack_request('xtdata.unsubscribe_quote', {'subscribe_id': sid}, client_id='sdk'))
    assert router._quote_routes == {} and router._quote_event_routes == {}


def test_web_plain_quote_fallback_does_not_leave_plain_marker_on_tagged_data():
    messages = []
    router = web.LttxWebRouteServer()
    router.tx = SimpleNamespace(push=lambda kind, raw, channel: messages.append(loads_message(raw)))
    router._push_event('sdk', 'quote:sdk', {'000001.SZ': {'raw': b'bytes'}}, 7, plain_quote=True)
    assert len(messages) == 1 and not messages[0]['meta'].get('quote_json_plain')
    assert decode_value(messages[0]['data']) == {'000001.SZ': {'raw': b'bytes'}}


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
    assert store.quotes.subscribe_whole({})["markets"] == ["SH", "SZ", "BJ"]


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
