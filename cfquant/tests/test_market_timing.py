"""Stage attribution and request isolation with fake QMT/transport only."""
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import time

import pandas as pd
import pytest

import cfquant_web_server as web
from cfquant import protocol
from cfquant import tx_trade_bridge as core
from cfquant import normal_bridge
from cfquant.client import CfquantError, CfquantTimeout, LTtxRpcClient
from cfquant.pipe_client import PipeRpcClient


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))
TIMED_METHODS = {"_dispatch", "_handle_raw", "_dispatch_timed_market_data", "_timed_market_call",
                 "_legacy_market_result", "_get_market_data", "_get_market_data_ex"}


class Clock:
    def __init__(self):
        self.now = 10.0

    def perf_counter(self):
        return self.now

    def advance(self, milliseconds):
        self.now += milliseconds / 1000


@pytest.fixture(params=[None] + LITE_PATHS, ids=["core"] + [p.stem for p in LITE_PATHS])
def implementation(request, monkeypatch):
    clock = Clock()
    fake_time = SimpleNamespace(**dict(vars(time), perf_counter=clock.perf_counter))
    if request.param is None:
        monkeypatch.setattr(core, "time", fake_time)
        return core.TxTradeBridge, core.__dict__, clock
    tree = ast.parse(request.param.read_text(encoding="gbk"), feature_version=(3, 6))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TxTradeBridge")
    cls.bases = [ast.Name(id="Base", ctx=ast.Load())]
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in TIMED_METHODS]
    namespace = dict(vars(core), Base=core.TxTradeBridge, time=fake_time)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(request.param), "exec"), namespace)
    return namespace["TxTradeBridge"], namespace, clock


def test_native_fallback_conversion_and_encoding_are_separate(implementation, monkeypatch):
    cls, namespace, clock = implementation
    frames = {"000001.SZ": pd.DataFrame({"close": [11.2, 11.3]})}

    def legacy(*args):
        clock.advance(20)
        return pd.DataFrame()

    def extended(*args):
        clock.advance(30)
        return frames

    original_convert = core.market_data_legacy_shape
    def convert(*args):
        clock.advance(5)
        return original_convert(*args)

    monkeypatch.setitem(namespace, "market_data_legacy_shape", convert)
    bridge = cls(SimpleNamespace(get_market_data=legacy, get_market_data_ex=extended), show=False)
    msg = {"id": "offline-fallback", "_received_monotonic": clock.now - .25}
    result = bridge._dispatch("xtdata.get_market_data", {
        "field_list": ["close"], "stock_list": ["000001.SZ"], "count": 2,
    }, msg)
    assert result["close"].loc["000001.SZ"].tolist() == [11.2, 11.3]
    timing = msg["_response_meta"]["timing"]["qmt"]
    assert (timing["queue_ms"], timing["native_ms"], timing["convert_ms"], timing["execute_ms"]) == (250, 50, 5, 55)
    assert timing["fallback_used"] is True
    assert [(x["method"], x["elapsed_ms"]) for x in timing["native_calls"]] == [("get_market_data", 20), ("get_market_data_ex", 30)]

    original_encode = protocol.encode_value
    def encode(value):
        # Advance once, not once per recursively encoded cell.
        monkeypatch.setattr(protocol, "encode_value", original_encode)
        clock.advance(8)
        return original_encode(value)

    monkeypatch.setattr(protocol, "time", SimpleNamespace(perf_counter=clock.perf_counter, time=time.time))
    monkeypatch.setattr(protocol, "encode_value", encode)
    response = protocol.loads_message(protocol.pack_response(msg["id"], result=result, meta=msg["_response_meta"]))
    assert response["meta"]["timing"]["qmt"]["encode_ms"] == 8
    pd.testing.assert_frame_equal(protocol.decode_value(response["result"])["close"], result["close"])


def test_native_error_retains_execution_timing(implementation):
    cls, _, clock = implementation
    def tick(codes):
        clock.advance(73)
        raise ValueError("QMT unavailable")

    sent = []
    bridge = cls(SimpleNamespace(get_full_tick=tick), show=False)
    bridge.tx = SimpleNamespace(push=lambda kind, raw, client: sent.append(protocol.loads_message(raw)))
    bridge._handle_raw(protocol.pack_request("xtdata.get_full_tick", {"code_list": ["000001.SZ"]}, client_id="offline"))
    response = sent[0]
    assert response["ok"] is False
    qmt = response["meta"]["timing"]["qmt"]
    assert qmt["native_ms"] == qmt["execute_ms"] == 73
    assert qmt["native_calls"][0]["ok"] is False


def test_normal_queue_delay_is_not_native_time(monkeypatch):
    clock = Clock()
    fake_time = SimpleNamespace(**dict(vars(time), perf_counter=clock.perf_counter))
    monkeypatch.setattr(core, "time", fake_time)
    monkeypatch.setattr(normal_bridge, "time", fake_time)
    def tick(codes):
        clock.advance(7)
        return {codes[0]: {"lastPrice": 11.3}}

    bridge = normal_bridge.NormalQmtBridge(SimpleNamespace(get_full_tick=tick), show=False, order_meta_enabled=False)
    sent = []
    bridge.tx = SimpleNamespace(push=lambda kind, raw, client: sent.append(protocol.loads_message(raw)))
    bridge._handle_raw_from_thread(protocol.pack_request("xtdata.get_full_tick", {"code_list": ["000001.SZ"]}, client_id="offline"))
    clock.advance(4000)
    msg, received, _ = bridge.request_queue.get_nowait()
    bridge._drain_single_request("test", msg, received)
    qmt = sent[0]["meta"]["timing"]["qmt"]
    assert qmt["queue_ms"] == 4000
    assert qmt["native_ms"] == qmt["execute_ms"] == 7


@pytest.fixture(params=[PipeRpcClient, LTtxRpcClient], ids=["pipe", "lttx"])
def rpc(request, monkeypatch):
    client = request.param(client_id="offline-timing", timeout=.001)
    state = SimpleNamespace(client=client, respond=True, old=False, error=False)
    monkeypatch.setattr(client, "start", lambda: None)

    def send(raw, channel):
        msg = protocol.loads_message(raw)
        if not state.respond:
            return
        value = msg["params"].get("value", 11)
        meta = {} if state.old else {"timing": {"qmt": {"available": True, "native_ms": value}}}
        response = protocol.pack_response(msg["id"], result={"value": value},
                                          ok=not state.error, error=ValueError("native failure") if state.error else None, meta=meta)
        client._pending[msg["id"]].put(protocol.loads_message(response))

    if request.param is PipeRpcClient:
        monkeypatch.setattr(client, "_send_request", send)
    else:
        monkeypatch.setattr(client, "_push", lambda kind, raw, channel: send(raw, channel))
    return state


def test_rpc_concurrent_requests_keep_data_and_timings_isolated(rpc):
    def run(value):
        meta = {}
        result = rpc.client.request("xtdata.get_full_tick", {"value": value}, response_meta=meta)
        return result, meta
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run, range(12)))
    for value, (result, meta) in enumerate(rows):
        assert result == {"value": value}
        assert meta["qmt"]["native_ms"] == value
        assert meta["rpc"]["total_ms"] >= meta["rpc"]["wait_ms"] >= 0
        assert meta["rpc"]["decode_ms"] >= 0
    assert len({meta["request_id"] for _, meta in rows}) == 12
    assert rpc.client.request("xtdata.get_full_tick", {"value": 22}) == {"value": 22}


def test_rpc_old_bridge_and_timeout_do_not_invent_qmt_measurements(rpc):
    rpc.old = True
    old = {}
    rpc.client.request("xtdata.get_full_tick", response_meta=old)
    assert old["qmt"] == {"available": False, "reason": "bridge_timing_unavailable"}
    rpc.respond = False
    timeout = {}
    with pytest.raises(CfquantTimeout):
        rpc.client.request("xtdata.get_full_tick", response_meta=timeout)
    assert timeout["qmt"] == {"available": False, "reason": "no_response"}
    assert timeout["rpc"]["wait_ms"] > 0
    assert timeout["rpc"]["response_received"] is False
    assert "decode_ms" not in timeout["rpc"]


def test_web_keeps_timings_across_error_wrapping_and_clears_context(rpc, monkeypatch):
    clients = web.GlobalTxClient()
    monkeypatch.setattr(clients, "_get_client", lambda mode: rpc.client)
    monkeypatch.setattr(web, "bridge_channels", lambda bridge_id: {"normal": "offline.normal", "trade": "offline.trade"})

    @web.with_market_timing
    def route(body, action):
        try:
            result = clients.request("offline", "normal", action, {}, mode="lite", timeout=.001)
        except Exception as error:
            raise RuntimeError("provider failed: %s" % error) from error
        return {"result": result}

    rpc.error = True
    with pytest.raises(RuntimeError) as caught:
        route({}, "xtdata.get_full_tick")
    failure = web.fail(caught.value)
    assert failure["timing"]["qmt"].get("native_ms") == 11, failure
    assert failure["timing"]["rpc"]["response_ok"] is False
    assert web._market_timing_attempts.get() is None
    rpc.error = False
    rpc.respond = False
    with pytest.raises(RuntimeError) as caught:
        route({}, "xtdata.get_full_tick")
    assert web.fail(caught.value)["timing"]["qmt"]["reason"] == "no_response"
    assert web._market_timing_attempts.get() is None


def test_web_conversion_is_measured_after_rpc_and_preserves_result():
    data = {"result": {"000001.SZ": pd.DataFrame({"close": [11.3]})},
            "timing": {"qmt": {"available": True, "native_ms": 73}, "web": {"route_ms": 100}}}
    response = web.ok(data)
    assert response["data"]["result"] == {"000001.SZ": {"0": {"close": 11.3}}}
    assert response["data"]["timing"]["web"]["result_convert_ms"] >= 0
    assert response["data"]["timing"]["qmt"]["native_ms"] == 73
    assert "result_convert_ms" not in data["timing"]["web"]


def test_shipped_lite_timing_methods_and_protocol_match_shared_code():
    def methods(path, encoding, class_name=None):
        body = ast.parse(path.read_text(encoding=encoding)).body
        if class_name:
            body = next(n.body for n in body if isinstance(n, ast.ClassDef) and n.name == class_name)
        return {n.name: ast.dump(n, include_attributes=False) for n in body if isinstance(n, ast.FunctionDef)}

    for path in LITE_PATHS:
        for source, cls, names in [(ROOT / "cfquant/tx_trade_bridge.py", "TxTradeBridge", TIMED_METHODS),
                                    (ROOT / "cfquant/normal_bridge.py", "NormalQmtBridge", {"_send_response", "_send_error"}),
                                    (ROOT / "cfquant/protocol.py", None, {"pack_response"})]:
            embedded, shared = methods(path, "gbk", cls), methods(source, "utf-8", cls)
            for name in names:
                assert embedded[name] == shared[name], (path, name)
