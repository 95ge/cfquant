"""Outgoing JSON checks with fake transports; no sockets, QMT, or real orders."""
import ast
import json
import math
from pathlib import Path
import queue
from types import SimpleNamespace
import time
import uuid

import numpy as np
import pandas as pd
import pytest

from cfquant import protocol, xtconstant
from cfquant.client import CfquantError, CfquantTimeout, LTtxRpcClient, WebLttxRpcClient
from cfquant.pipe_client import PipeRpcClient
from cfquant.pipe_transport import loads_pipe_message
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))
BIG_ID = 2 ** 60 + 37


@pytest.fixture(params=[None] + LITE_PATHS, ids=["core"] + [p.stem for p in LITE_PATHS])
def wire(request):
    if request.param is None:
        return protocol
    tree = ast.parse(request.param.read_text(encoding="gbk"), feature_version=(3, 6))
    names = {"now_ms", "new_id", "normalize_json_value", "dumps_message", "loads_message", "pack_request"}
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    ns = dict(json=json, math=math, time=time, uuid=uuid, PROTOCOL_VERSION=1, MESSAGE_PREFIX="cfquant:")
    exec(compile(tree, str(request.param), "exec"), ns)
    return SimpleNamespace(**ns)


@pytest.mark.parametrize("value,expected", [
    (np.int8(12), 12), (np.int32(100), 100), (np.int64(BIG_ID), BIG_ID),
    (np.uint64(2 ** 64 - 1), 2 ** 64 - 1), (np.float16(1.5), 1.5),
    (np.float32(11.5), 11.5), (np.float64(11.6), 11.6),
    (np.longdouble("11.5"), 11.5), (np.bool_(True), True),
    (np.str_("000001.SZ"), "000001.SZ"), (np.array(100), 100),
])
def test_numpy_scalars_are_builtin_json_values_without_mutating_input(wire, value, expected):
    params = {"orders": [{"value": value}], "options": (value, None)}
    data = wire.loads_message(wire.pack_request("test.request", params))["params"]
    assert data["orders"][0]["value"] == expected
    assert type(data["orders"][0]["value"]) is type(expected)
    assert data["options"] == [expected, None]
    assert params["orders"][0]["value"] is value
    assert isinstance(params["options"], tuple)


def test_dataframe_cell_numbers_and_nested_keys(wire):
    frame = pd.DataFrame({"volume": pd.Series([100], dtype="int64"), "price": pd.Series([11.6], dtype="float32")})
    params = {"order_volume": frame.at[0, "volume"], "price": frame.at[0, "price"],
              "flags": {np.int64(1): np.bool_(False)}}
    data = wire.loads_message(wire.pack_request("xttrader.order_stock", params))["params"]
    assert type(data["order_volume"]) is int and data["order_volume"] == 100
    assert type(data["price"]) is float and data["price"] == float(frame.at[0, "price"])
    assert data["flags"] == {"1": False}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"),
                                   np.float32("nan"), np.float64("inf"), np.array(float("nan"))])
def test_non_finite_numbers_fail_with_field_path(wire, value):
    with pytest.raises(ValueError, match=r"message.params.orders\[0\].price.*NaN and infinity"):
        wire.pack_request("xttrader.order_stock", {"orders": [{"price": value}]})


@pytest.mark.parametrize("value", [pd.DataFrame({"price": [11.6]}), pd.Series([11.6]),
                                   np.array([11.6]), np.complex128(1 + 2j), pd.NA, pd.NaT,
                                   pd.Timestamp("2026-09-11"), object()])
def test_ambiguous_or_unsupported_types_are_not_stringified_or_unwrapped(wire, value):
    with pytest.raises(TypeError, match=r"message.params.price: unsupported JSON type"):
        wire.pack_request("xttrader.order_stock", {"price": value})


def test_circular_references_fail_but_shared_values_work(wire):
    row = {"volume": np.int64(100)}
    assert wire.loads_message(wire.pack_request("test", {"rows": [row, row]}))["params"]["rows"] == [{"volume": 100}] * 2
    row["self"] = row
    with pytest.raises(ValueError, match="circular reference"):
        wire.pack_request("test", {"rows": [row]})


def test_empty_dataframe_root_has_a_clear_type_error(wire):
    with pytest.raises(TypeError, match=r"message.params.*DataFrame"):
        wire.pack_request("test", pd.DataFrame())


def test_response_missing_values_keep_existing_null_behavior():
    raw = protocol.pack_response("offline", result={"price": np.nan, "missing": pd.NA, "id": np.int64(BIG_ID)})
    assert protocol.loads_message(raw)["result"] == {"price": None, "missing": None, "id": BIG_ID}


@pytest.fixture(params=[LTtxRpcClient, WebLttxRpcClient, PipeRpcClient], ids=["lttx", "web-lttx", "pipe"])
def transport(request, monkeypatch):
    kwargs = {"client_id": "offline-json-test", "timeout": 0.01}
    if request.param is WebLttxRpcClient:
        kwargs["registry"] = {"web_request_channel": "offline.web"}
    client = request.param(**kwargs)
    state = SimpleNamespace(client=client, starts=0, messages=[], error=None, respond=True)

    def start():
        state.starts += 1

    def send(raw):
        if state.error:
            raise state.error
        msg = protocol.loads_message(raw)
        state.messages.append(msg)
        if msg.get("type") == "request" and state.respond:
            client._pending[msg["id"]].put({"ok": True, "result": {"order_id": BIG_ID, "accepted": True}})

    def push(kind, raw, channel):
        # This is the JSON boundary inside LTtx; all custom numbers must be gone.
        frame = json.loads(json.dumps({"kind": kind, "payload": raw, "channel": channel}, allow_nan=False))
        send(frame["payload"])
        return {"code": 0}

    monkeypatch.setattr(client, "start", start)
    if isinstance(client, PipeRpcClient):
        client._tx_conn = SimpleNamespace(write_frame=lambda raw: send(loads_pipe_message(raw)["payload"]), close=lambda: None)
    else:
        client._tx = SimpleNamespace(push=push, Q=queue.Queue(), close=lambda: None)
    yield state
    client.close()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_sdk_order_methods_accept_dataframe_scalars(transport, monkeypatch, asynchronous):
    trader = XtQuantTrader(account=StockAccount("OFFLINE_TEST", "STOCK"))
    monkeypatch.setattr(trader, "_get_client", lambda bridge_id=None: transport.client)
    frame = pd.DataFrame({"volume": [100], "price": pd.Series([11.5], dtype="float32")})
    method = trader.order_stock_async if asynchronous else trader.order_stock
    result = method(trader.account, np.str_("000001.SZ"), np.int32(xtconstant.STOCK_BUY),
                    frame.at[0, "volume"], np.int64(xtconstant.FIX_PRICE), frame.at[0, "price"])
    assert result > 0
    assert len(transport.messages) == 1
    params = transport.messages[0]["params"]
    assert type(params["order_volume"]) is int and params["order_volume"] == 100
    assert type(params["price"]) is float and params["price"] == 11.5
    assert type(params["order_type"]) is int and type(params["price_type"]) is int
    assert transport.client._pending == {}


@pytest.mark.parametrize("bad_price", [pd.Series([11.6]), pd.DataFrame({"price": [11.6]}), pd.NA, np.nan])
def test_bad_async_order_does_not_start_send_or_leak_pending(transport, monkeypatch, bad_price):
    trader = XtQuantTrader(account=StockAccount("OFFLINE_TEST", "STOCK"))
    monkeypatch.setattr(trader, "_get_client", lambda bridge_id=None: transport.client)
    with pytest.raises((TypeError, ValueError), match="message.params.price"):
        trader.order_stock_async(trader.account, "000001.SZ", 23, np.int64(100), 11, bad_price)
    assert transport.starts == 0 and transport.messages == []
    assert transport.client._pending == {} and trader._pending_async_orders == []


def test_send_failure_releases_pending_without_retry(transport):
    transport.error = CfquantError("offline send failure")
    with pytest.raises(CfquantError, match="offline send failure"):
        transport.client.request("test", {"value": np.int64(100)})
    assert transport.starts == 1 and transport.client._pending == {}


def test_timeout_releases_pending_without_retry(transport):
    transport.respond = False
    with pytest.raises(CfquantTimeout):
        transport.client.request("test", {"value": np.int64(100)})
    assert len(transport.messages) == 1 and transport.client._pending == {}


def test_publish_event_normalizes_before_transport_start(transport):
    with pytest.raises(TypeError, match="message.data.price"):
        transport.client.publish_event("offline", {"type": "event", "data": {"price": pd.Series([11.6])}})
    assert transport.starts == 0 and transport.messages == []
    transport.client.publish_event("offline", {"type": "event", "data": {"count": np.int64(100)}})
    assert transport.messages[-1]["data"] == {"count": 100}
