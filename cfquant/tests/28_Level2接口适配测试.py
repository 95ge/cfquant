"""Offline native QMT / RPC fixtures only. No live connections or orders."""
import ast
import base64
import datetime as dt
import importlib.util
import json
import math
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import cfquant_web_server as web
from cfquant import level2, xtdata
from cfquant.normal_bridge import COALESCED_QUERY_ACTIONS, NormalQmtBridge
from cfquant.pipe_bridge import PipeNormalQmtBridge
from cfquant.protocol import decode_value, encode_value, loads_message, pack_event, pack_request, pack_response
from cfquant.qmt_bridge import CfquantQmtBridge
from cfquant.tx_trade_bridge import TxTradeBridge

ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))
BIG_ID = 2 ** 60 + 37
CODE = "000001.SZ"


def lite_namespace(path):
    tree = ast.parse(path.read_text(encoding="gbk"))
    helpers = {key for key in vars(level2) if not key.startswith("__") and key != "l2_array"}
    functions = {"encode_value", "_encode_dataframe", "_encode_series", "_clean_cell", "_looks_like_dataframe", "_looks_like_series", "_get_pandas"}
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in helpers | functions:
            body.append(node)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in helpers:
            body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "TxTradeBridge":
            node.bases = [ast.Name(id="BaseTradeBridge", ctx=ast.Load())]
            node.body = [method for method in node.body if isinstance(method, ast.FunctionDef)
                         and method.name in ("_get_market_data", "_get_market_data_ex", "_dispatch_xtdata_compat")]
            body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in ("NormalQmtBridge", "PipeNormalQmtBridge"):
            body.append(node)
    tree.body = body
    ns = dict(BaseTradeBridge=TxTradeBridge, queue=queue, threading=threading, time=time,
              dt=dt, json=json, math=math, base64=base64, loads_message=loads_message,
              pack_event=pack_event, pack_response=pack_response,
              COALESCED_QUERY_ACTIONS=COALESCED_QUERY_ACTIONS, DEFAULT_PIPE_NAME="offline")
    exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), ns)
    return ns


class FakeQmt:
    def __init__(self):
        self.calls = []
        self.callbacks = {}
        self.unsubscribed = []
        self.data = pd.DataFrame({"time": [1789010100000], "price": [11.6], "orderNo": [BIG_ID],
                                  "bidPrice": [np.array([11.6, 11.5])], "bidVol": [[100, 200]]})
        self.initial = True

    def get_market_data_ex(self, *args):
        self.calls.append(args)
        return {CODE: self.data}

    def get_market_data(self, *args):
        raise AssertionError("deprecated market-data call must not handle Level2")

    def subscribe_quote(self, code, period, dividend_type, result_type, callback):
        self.calls.append((code, period, dividend_type, result_type))
        sid = 100 + len(self.callbacks)
        self.callbacks[sid] = callback
        if self.initial:
            callback({code: self.data})
        return sid

    def unsubscribe_quote(self, sid):
        self.unsubscribed.append(sid)
        return 0


class RecordingTx:
    def __init__(self):
        self.messages = []
        self.receiver = None

    def push(self, kind, payload, client_id):
        message = loads_message(payload)
        self.messages.append((kind, message, client_id))
        if self.receiver and kind == "event":
            self.receiver(message)

    def close(self):
        pass


@pytest.fixture(params=[TxTradeBridge, NormalQmtBridge, PipeNormalQmtBridge, CfquantQmtBridge] + LITE_PATHS,
                ids=["trade", "lttx", "ctypes", "legacy"] + [p.stem for p in LITE_PATHS])
def bridge(request):
    cls = lite_namespace(request.param)["PipeNormalQmtBridge"] if isinstance(request.param, Path) else request.param
    obj = cls(FakeQmt(), show=False)
    obj._log = lambda message: None
    obj.tx = RecordingTx()
    obj.running = True
    yield obj
    obj.close()


def rpc(bridge, action, params):
    msg = loads_message(pack_request(action, params=params, client_id="offline-client"))
    result = bridge._dispatch(action, msg["params"], msg)
    return decode_value(loads_message(pack_response(msg["id"], result=result))["result"])


def sdk(monkeypatch, bridge):
    callbacks = {}
    client = SimpleNamespace(request=lambda action, params: rpc(bridge, action, params),
                             add_callback=lambda event, cb: callbacks.update({event: cb}),
                             remove_callback=lambda event, cb: callbacks.pop(event, None))
    monkeypatch.setattr(xtdata, "get_client", lambda: client)
    monkeypatch.setattr(xtdata, "_subscription_callbacks", {})
    bridge.tx.receiver = lambda msg: callbacks[msg["event"]](decode_value(msg["data"])) if msg["event"] in callbacks else None
    return callbacks


@pytest.mark.parametrize("method,period", list(level2.L2_GET_PERIODS.items()))
def test_sdk_l2_queries_preserve_fields_precision_and_depth(monkeypatch, bridge, method, period):
    sdk(monkeypatch, bridge)
    data = getattr(xtdata, method)(stock_code=CODE, count=10)
    assert data.dtype.names == tuple(bridge.context.data.columns)
    assert data["orderNo"][0] == BIG_ID
    assert data["bidPrice"][0] == [11.6, 11.5]
    assert data["bidVol"][0] == [100, 200]
    assert bridge.context.calls == [([], [CODE], period, "", "", 10, "none", False)]


@pytest.mark.parametrize("period", level2.L2_PERIODS)
def test_six_period_query_protocol_and_no_forward_fill(bridge, period):
    result = rpc(bridge, "xtdata.get_market_data_ex", {"stock_list": [CODE], "period": period, "fill_data": True})
    assert result[CODE]["orderNo"].iloc[0] == BIG_ID
    assert result[CODE]["bidPrice"].iloc[0] == [11.6, 11.5]
    assert bridge.context.calls[-1][2] == period
    assert bridge.context.calls[-1][-1] is False
    rpc(bridge, "xtdata.get_market_data", {"stock_list": [CODE], "period": period})
    assert bridge.context.calls[-1][2] == period


def test_field_filter_empty_missing_and_old_generic_payload(monkeypatch, bridge):
    sdk(monkeypatch, bridge)
    assert xtdata.get_l2_order(["orderNo"], CODE).dtype.names == ("orderNo",)
    packet = rpc(bridge, "xtdata.get_l2_order", {"args": [["orderNo"], CODE], "kwargs": {"count": 1}})
    assert packet["records"] == [{"orderNo": BIG_ID}]
    with pytest.raises(ValueError, match="missing requested fields"):
        xtdata.get_l2_order(["missing"], CODE)
    bridge.context.data = bridge.context.data.iloc[:0]
    assert len(xtdata.get_l2_quote(stock_code=CODE)) == 0
    bridge.context.data = None
    assert xtdata.get_l2_quote(stock_code=CODE) is None


@pytest.mark.parametrize("period", level2.L2_PERIODS)
def test_native_period_subscription_first_callback_and_cleanup(monkeypatch, bridge, period):
    if type(bridge) is TxTradeBridge:
        pytest.skip("subscriptions intentionally route to the normal bridge")
    callbacks = sdk(monkeypatch, bridge)
    received = []
    sid = xtdata.subscribe_quote(CODE, period=period, callback=received.append)
    assert bridge.context.calls == [(CODE, period, "none", "dict")]
    assert len(received) == 1
    assert received[0][CODE][0]["orderNo"] == BIG_ID
    assert isinstance(received[0][CODE], list)
    assert len(callbacks) == 1
    native_cb = bridge.context.callbacks[100]
    native_cb({CODE: {"orderNo": np.int64(BIG_ID), "price": 11.6}})
    assert received[-1] == {CODE: [{"orderNo": BIG_ID, "price": 11.6}]}
    xtdata.unsubscribe_quote(sid)
    assert bridge.context.unsubscribed == [100]
    assert callbacks == {}
    native_cb({CODE: {"price": 12.0}})
    assert len(received) == 2


def test_native_subscription_error_and_unsubscribe_retry(monkeypatch, bridge):
    if type(bridge) is TxTradeBridge:
        pytest.skip("query-only bridge")
    callbacks = sdk(monkeypatch, bridge)
    subscribe = bridge.context.subscribe_quote
    calls = []
    def fail(*args):
        calls.append(args)
        raise TypeError("permission denied by backend")
    bridge.context.subscribe_quote = fail
    with pytest.raises(TypeError, match="permission denied"):
        xtdata.subscribe_quote(CODE, "l2quote", callback=lambda data: None)
    assert len(calls) == 1 and callbacks == {}
    bridge.context.subscribe_quote = subscribe
    sid = xtdata.subscribe_quote(CODE, "l2quote", callback=lambda data: None)
    unsubscribe = bridge.context.unsubscribe_quote
    bridge.context.unsubscribe_quote = lambda seq: -1
    with pytest.raises(RuntimeError, match="unsubscribe_quote failed"):
        xtdata.unsubscribe_quote(sid)
    assert len(callbacks) == 1
    bridge.context.unsubscribe_quote = unsubscribe
    xtdata.unsubscribe_quote(sid)
    assert callbacks == {}


def test_thousand_capability_boundary_and_native_price_range(monkeypatch, bridge):
    sdk(monkeypatch, bridge)
    with pytest.raises(NotImplementedError, match="native QMT callable"):
        xtdata.get_l2thousand_queue(CODE)
    calls = []
    def get_queue(code, gear_num, price):
        calls.append((code, gear_num, price))
        return {code: {"bidPrice": np.array([11.6]), "bidOrder": [[BIG_ID]]}}
    bridge.context.get_l2thousand_queue = get_queue
    result = xtdata.get_l2thousand_queue(CODE, price=(11.5, 11.6))
    assert calls[-1] == (CODE, None, (11.5, 11.6))
    assert result[CODE]["bidOrder"] == [[BIG_ID]]
    xtdata.get_l2thousand_queue(CODE, price=[11.5, 11.6])
    assert calls[-1][2] == [11.5, 11.6]
    if type(bridge) is TxTradeBridge:
        return
    with pytest.raises(NotImplementedError, match="native QMT callable"):
        xtdata.subscribe_l2thousand_queue(CODE, callback=lambda data: None)
    def subscribe_queue(code, callback, gear_num, price):
        calls.append((code, gear_num, price))
        callback({code: {"bidOrder": [[BIG_ID]]}})
        return 301
    bridge.context.subscribe_l2thousand_queue = subscribe_queue
    received = []
    sid = xtdata.subscribe_l2thousand_queue(CODE, received.append, price=(11.5, 11.6))
    assert calls[-1][2] == (11.5, 11.6)
    assert received == [{CODE: [{"bidOrder": [[BIG_ID]]}]}]
    xtdata.unsubscribe_quote(sid)
    assert bridge.context.unsubscribed[-1] == 301
    bridge.context.subscribe_l2thousand = lambda code, gear_num, callback: subscribe_queue(code, callback, gear_num, None)
    sid = xtdata.subscribe_l2thousand(CODE, gear_num=20, callback=received.append)
    assert calls[-1] == (CODE, 20, None)
    bridge.close()
    assert bridge.context.unsubscribed[-1] == 301


@pytest.mark.parametrize("path", [None] + LITE_PATHS, ids=["core"] + [p.stem for p in LITE_PATHS])
def test_wire_encoder_preserves_nullable_ids_arrays_and_numpy_scalars(path):
    encoder = encode_value if path is None else lite_namespace(path)["encode_value"]
    frame = pd.DataFrame({"id": pd.Series([BIG_ID, None], dtype=object), "price": [11.6, 12.0],
                          "depth": [np.array([100, 200]), np.array([300, 400])]})
    result = decode_value(json.loads(json.dumps(encoder(frame))))
    assert result["id"].iloc[0] == BIG_ID
    assert result["id"].iloc[1] is None
    assert result["depth"].iloc[0] == [100, 200]
    assert encoder(np.uint64(2 ** 64 - 1)) == 2 ** 64 - 1


def test_record_array_inputs_and_unsigned_id():
    values = np.array([(2 ** 64 - 1, 11.6)], dtype=[("orderNo", "u8"), ("price", "f8")])
    rows = level2.quote_records(values)
    data = level2.l2_array({"columns": ["orderNo", "price"], "records": rows})
    assert data["orderNo"][0] == 2 ** 64 - 1


@pytest.mark.parametrize("path", [None] + LITE_PATHS, ids=["core"] + [p.stem for p in LITE_PATHS])
def test_nullable_integer_columns_do_not_become_float_or_missing_strings(path):
    ns = vars(level2) if path is None else lite_namespace(path)
    encoder = encode_value if path is None else ns["encode_value"]
    frame = pd.DataFrame({"entrustNo": pd.Series([BIG_ID, pd.NA], dtype="Int64"), "price": [11.6, 11.7]})
    result = decode_value(json.loads(json.dumps(encoder(frame))))
    assert result["entrustNo"].tolist() == [BIG_ID, None]
    records = ns["quote_records"](frame)
    data = level2.l2_array({"columns": list(frame.columns), "records": records})
    assert data["entrustNo"].tolist() == [BIG_ID, None]


def test_dataframe_duplicate_columns_and_same_timestamp_records_survive():
    frame = pd.concat([pd.Series([BIG_ID], dtype=object), pd.Series([[1, 2]], dtype=object)], axis=1)
    frame.columns = ["value", "value"]
    decoded = decode_value(encode_value(frame))
    assert decoded.iloc[0, 0] == BIG_ID and decoded.iloc[0, 1] == [1, 2]
    rows = [{"time": 1, "entrustNo": BIG_ID}, {"time": 1, "entrustNo": BIG_ID + 1}]
    assert level2.quote_callback_data({CODE: rows}) == {CODE: rows}


def test_empty_structured_array_preserves_field_names():
    empty = np.empty(0, dtype=[("time", "i8"), ("entrustNo", "i8")])
    packet = level2.l2_query(lambda *args: {CODE: empty}, "l2order", {"stock_code": CODE})
    assert level2.l2_array(packet).dtype.names == ("time", "entrustNo")


@pytest.mark.parametrize("method", list(level2.L2_GET_PERIODS) + ["get_l2thousand_queue", "get_full_tick"])
def test_advanced_readonly_routing_stays_trade_first(method):
    assert web.default_channel_for_action("xtdata." + method, mode="lttx") == "trade"


@pytest.mark.parametrize("method", ["subscribe_quote", "subscribe_l2thousand", "subscribe_l2thousand_queue", "unsubscribe_quote"])
def test_advanced_subscription_routing_uses_normal(method):
    assert web.forced_channel_for_action("xtdata." + method, mode="lttx") == "normal"


@pytest.mark.parametrize("method", ["subscribe_quote", "subscribe_l2thousand", "subscribe_l2thousand_queue"])
def test_web_forwards_first_packet_before_subscription_response_and_cleans_up(monkeypatch, method):
    route = web.LttxWebRouteServer()
    route.tx = RecordingTx()
    event = "quote:offline-unique"
    def request(msg):
        if msg["action"] != "xtdata.unsubscribe_quote":
            route._on_quote_event({"subscription_id": 1, "event": msg["params"]["callback_event"], "data": {CODE: [{"orderNo": BIG_ID}]}})
        return {"subscribe_id": 1}, {"bridge_id": "source", "channel": "normal", "mode": "lttx"}
    monkeypatch.setattr(web, "route_external_lttx_request", request)
    monkeypatch.setattr(web.CLIENTS, "request", lambda *args, **kwargs: True)
    route._handle_raw(pack_request("xtdata." + method, {"callback_event": event}, client_id="sdk"))
    assert [item[0] for item in route.tx.messages] == ["event", "response"]
    assert route.tx.messages[0][2] == "sdk"
    sid = route.tx.messages[-1][1]["result"]["subscribe_id"]
    assert route.tx.messages[0][1]["subscription_id"] == sid
    assert route.tx.messages[0][1]["event"] == event
    route._handle_raw(pack_request("xtdata.unsubscribe_quote", {"subscribe_id": sid}, client_id="sdk"))
    assert route._quote_routes == {} and route._quote_event_routes == {}
    before = len(route.tx.messages)
    route._on_quote_event({"subscription_id": 1, "event": event, "data": {}})
    assert len(route.tx.messages) == before


def test_web_failed_subscription_removes_provisional_callback(monkeypatch):
    route = web.LttxWebRouteServer()
    route.tx = RecordingTx()
    def fail(msg):
        raise RuntimeError("permission denied")
    monkeypatch.setattr(web, "route_external_lttx_request", fail)
    route._handle_raw(pack_request("xtdata.subscribe_quote", {"callback_event": "quote:failed"}, client_id="sdk"))
    assert route._quote_routes == {} and route._quote_event_routes == {}
    assert route.tx.messages[-1][1]["ok"] is False


@pytest.mark.parametrize("result", [None, False, 0, -1])
def test_web_rejected_native_id_cannot_leak_provisional_routes(monkeypatch, result):
    route = web.LttxWebRouteServer()
    route.tx = RecordingTx()
    monkeypatch.setattr(web, "route_external_lttx_request", lambda msg: ({"subscribe_id": result}, {}))
    route._handle_raw(pack_request("xtdata.subscribe_quote", {}, client_id="sdk"))
    assert route._quote_routes == {} and route._quote_event_routes == {}
    assert route.tx.messages[-1][1]["ok"] is False


def test_web_unsubscribe_failure_retains_exact_source_for_retry(monkeypatch):
    route = web.LttxWebRouteServer()
    route.tx = RecordingTx()
    monkeypatch.setattr(web, "route_external_lttx_request", lambda msg: ({"subscribe_id": 12}, {"bridge_id": "source", "channel": "normal", "mode": "lite"}))
    route._handle_raw(pack_request("xtdata.subscribe_quote", {}, client_id="sdk"))
    sid = route.tx.messages[-1][1]["result"]["subscribe_id"]
    monkeypatch.setattr(web.CLIENTS, "request", lambda *args, **kwargs: False)
    route._handle_raw(pack_request("xtdata.unsubscribe_quote", {"subscribe_id": sid}, client_id="sdk"))
    assert len(route._quote_routes) == len(route._quote_event_routes) == 1
    monkeypatch.setattr(web.CLIENTS, "request", lambda *args, **kwargs: True)
    route._handle_raw(pack_request("xtdata.unsubscribe_quote", {"subscribe_id": sid}, client_id="sdk"))
    assert route._quote_routes == {} and route._quote_event_routes == {}


def test_web_same_native_id_from_two_sources_keeps_routes_and_callbacks_isolated(monkeypatch):
    route = web.LttxWebRouteServer()
    route.tx = RecordingTx()
    events = []
    def request(msg):
        events.append(msg["params"]["callback_event"])
        return {"subscribe_id": 1}, {"bridge_id": "source-%s" % len(events), "channel": "normal", "mode": "lttx"}
    monkeypatch.setattr(web, "route_external_lttx_request", request)
    released = []
    monkeypatch.setattr(web.CLIENTS, "request", lambda *args, **kwargs: released.append((args, kwargs)) or True)
    ids = []
    for _ in range(2):
        route._handle_raw(pack_request("xtdata.subscribe_quote", {}, client_id="sdk"))
        ids.append(route.tx.messages[-1][1]["result"]["subscribe_id"])
    assert ids[0] != ids[1]
    for event, sid in zip(events, ids):
        route._on_quote_event({"subscription_id": 1, "event": event, "data": {}})
        assert route.tx.messages[-1][1]["subscription_id"] == sid
        assert route.tx.messages[-1][1]["event"] == "quote:%s" % sid
    route._handle_raw(pack_request("xtdata.unsubscribe_quote", {"subscribe_id": ids[0]}, client_id="other"))
    assert route.tx.messages[-1][1]["ok"] is False and released == []
    route._handle_raw(pack_request("xtdata.unsubscribe_quote", {"subscribe_id": ids[0]}, client_id="sdk"))
    assert released[0][0][:4] == ("source-1", "normal", "xtdata.unsubscribe_quote", {"subscribe_id": 1})
    assert released[0][1]["mode"] == "lttx"
    assert len(route._quote_routes) == 1
    before = len(route.tx.messages)
    route._on_quote_event({"subscription_id": 1, "event": events[0], "data": {}})
    assert len(route.tx.messages) == before
    route.close()
    assert released[-1][0][0] == "source-2"
    assert route._quote_event_routes == {} and route._quote_routes == {}


@pytest.mark.parametrize("emit,fail_unsubscribe", [(True, False), (False, False), (True, True)])
def test_readonly_example_uses_code_config_and_reports_empty_and_failed_cleanup(monkeypatch, tmp_path, emit, fail_unsubscribe):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    path = next(Path(__file__).parent.glob("29_*.py"))
    spec = importlib.util.spec_from_file_location("readonly_level2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configure_stdout", lambda: None)
    monkeypatch.setattr(module, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(module, "PERIODS", ["l2quote"])
    monkeypatch.setattr(module, "SECONDS", 0.001)
    configured = []
    monkeypatch.setattr(module, "configure", lambda **kwargs: configured.append(kwargs))
    monkeypatch.setattr(module, "close_default_client", lambda: None)
    def subscribe(code, period, callback):
        if emit:
            callback({code: [{"time": 1, "lastPrice": 11.6}]})
        return 100
    monkeypatch.setattr(module.xtdata, "subscribe_quote", subscribe)
    monkeypatch.setattr(module.xtdata, "get_market_data_ex", lambda *args, **kwargs: {module.STOCK_CODE: pd.DataFrame({"time": [1]})})
    monkeypatch.setattr(module.xtdata, "get_l2_quote", lambda **kwargs: np.array([(1,)], dtype=[("time", "i8")]))
    monkeypatch.setattr(module.xtdata, "unsubscribe_quote", lambda sid: not fail_unsubscribe)
    report = module.main()
    assert configured == [{"transport": module.TRANSPORT, "bridge_id": module.BRIDGE_ID, "timeout": module.REQUEST_TIMEOUT}]
    row = report["periods"]["l2quote"]
    assert row["valid_callback_count"] == int(emit)
    assert row["unsubscribe_ok"] == (not fail_unsubscribe)
    assert row["status"].startswith("失败" if fail_unsubscribe else "已收到" if emit else "待确认")
    assert len(list(tmp_path.glob("level2_test_*.json"))) == 1
