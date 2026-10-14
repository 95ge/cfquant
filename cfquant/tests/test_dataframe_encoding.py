"""Market data wire compatibility for the SDK and standalone Lite entries."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from cfquant import protocol
from cfquant.level2 import market_data_legacy_shape
from cfquant.tx_trade_bridge import TxTradeBridge


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))
BIG_ID = 2**60 + 37


@pytest.fixture(params=[None] + LITE_PATHS, ids=["core"] + [p.stem for p in LITE_PATHS])
def wire(request):
    if request.param is None:
        return protocol
    source = request.param.read_bytes().decode("gbk")
    tree = ast.parse(source, feature_version=(3, 6))
    shared = ast.parse((ROOT / "cfquant/protocol.py").read_text(encoding="utf-8"))
    names = {node.name for node in shared.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    namespace = dict(vars(protocol))
    exec(compile(tree, str(request.param), "exec"), namespace)
    return SimpleNamespace(**namespace)


def roundtrip(wire, value):
    response = protocol.loads_message(wire.pack_response("encoding-contract", result=value))
    assert response["ok"] and response["version"] == 1
    return protocol.decode_value(response["result"])


def test_mixed_numeric_values_keep_integer_precision_and_scalar_types(wire):
    frame = pd.DataFrame({
        "orderNo": pd.Series([BIG_ID, BIG_ID + 1], dtype="int64"),
        "unsignedNo": pd.Series([2**64 - 1, 2**63 + 17], dtype="uint64"),
        "price": [11.6, 11.7], "enabled": [True, False],
    })
    packet = json.loads(json.dumps(wire.encode_value(frame)))
    assert packet["data"] == [
        [BIG_ID, 2**64 - 1, 11.6, True],
        [BIG_ID + 1, 2**63 + 17, 11.7, False],
    ]
    assert type(packet["data"][0][0]) is int
    assert type(packet["data"][0][1]) is int
    assert type(packet["data"][0][2]) is float
    assert type(packet["data"][0][3]) is bool
    pd.testing.assert_frame_equal(roundtrip(wire, frame), frame)


def test_nullable_and_object_ids_do_not_round_or_become_strings(wire):
    frame = pd.DataFrame({
        "orderNo": pd.Series([BIG_ID, pd.NA], dtype="Int64"),
        "unsignedNo": pd.Series([2**64 - 1, pd.NA], dtype="UInt64"),
        "objectNo": pd.Series([BIG_ID + 1, None], dtype=object),
        "price": [11.6, np.nan],
    })
    packet = wire.encode_value(frame)
    assert packet["object_columns"] == ["orderNo", "unsignedNo", "objectNo"]
    assert packet["data"] == [[BIG_ID, 2**64 - 1, BIG_ID + 1, 11.6], [None, None, None, None]]
    restored = roundtrip(wire, frame)
    for field, value in [("orderNo", BIG_ID), ("unsignedNo", 2**64 - 1), ("objectNo", BIG_ID + 1)]:
        assert restored[field].tolist() == [value, None]
        assert restored[field].dtype == object


def test_object_cells_nested_depth_and_nonfinite_values_keep_wire_contract(wire):
    frame = pd.DataFrame({
        "depth": [np.array([100, 200], dtype="int64"), [300, 400], {"bid": [500]}],
        "payload": [b"abc", "行情", None],
        "price": [np.nan, np.inf, -np.inf],
    })
    packet = wire.encode_value(frame)
    assert packet["data"] == [
        [{"__cf_type__": "ndarray", "shape": [2], "data": [100, 200], "dtype": "int64"},
         {"__cf_type__": "bytes", "data": "YWJj"}, None],
        [[300, 400], "行情", None],
        [{"bid": [500]}, None, None],
    ]
    restored = roundtrip(wire, frame)
    np.testing.assert_array_equal(restored["depth"].iloc[0], np.array([100, 200], dtype="int64"))
    assert restored["depth"].iloc[1:].tolist() == [[300, 400], {"bid": [500]}]
    assert restored["payload"].tolist() == [b"abc", "行情", None]


def test_duplicate_labels_order_and_index_name_survive(wire):
    frame = pd.concat([pd.Series([BIG_ID, None], dtype=object), pd.Series([[1, 2], [3, 4]], dtype=object)], axis=1)
    frame.columns = ["value", "value"]
    frame.index = pd.Index(["same", "same"], name="stock")
    pd.testing.assert_frame_equal(roundtrip(wire, frame), frame)


def test_tuple_labels_keep_existing_tagged_format(wire):
    frame = pd.DataFrame([[1]], index=pd.MultiIndex.from_tuples([("stock", 1)]),
                         columns=pd.MultiIndex.from_tuples([("close", 2)]))
    packet = wire.encode_value(frame)
    assert packet["index"] == [{"__cf_type__": "tuple", "data": ["stock", 1]}]
    assert packet["columns"] == [{"__cf_type__": "tuple", "data": ["close", 2]}]
    assert packet["data"] == [[1]]


@pytest.mark.parametrize("frame", [pd.DataFrame(), pd.DataFrame(columns=["open", "close"]),
                                   pd.DataFrame(index=["stock1", "stock2"])])
def test_empty_shapes_keep_existing_wire_format(wire, frame):
    packet = wire.encode_value(frame)
    assert packet["data"] == []
    assert packet["columns"] == list(frame.columns)
    assert packet["index"] == list(frame.index)


def test_legacy_market_fallback_keeps_xtquant_field_stock_date_layout(wire):
    stocks = ["600000.SH", "000001.SZ"]
    dates = ["20261012", "20261013"]
    native = {code: pd.DataFrame({"close": [11.2, 11.3], "volume": [100, 200]}, index=dates) for code in stocks}
    bridge = TxTradeBridge(SimpleNamespace(get_market_data=lambda *args: pd.DataFrame(),
                                          get_market_data_ex=lambda *args: native), show=False)
    result = bridge._get_market_data({"field_list": ["volume", "close"], "stock_list": stocks,
                                      "period": "1d", "count": -1})
    decoded = roundtrip(wire, result)
    assert list(decoded) == ["volume", "close"]
    for field, values in [("volume", [100, 200]), ("close", [11.2, 11.3])]:
        expected = pd.DataFrame([values, values], index=stocks, columns=dates)
        pd.testing.assert_frame_equal(decoded[field], expected)


def test_extended_market_keeps_stock_frame_and_field_order(wire):
    frame = pd.DataFrame({"volume": [100, 200], "close": [11.2, 11.3]}, index=["20261012", "20261013"])
    native = {"000001.SZ": frame}
    restored = roundtrip(wire, native)
    assert list(restored) == ["000001.SZ"]
    pd.testing.assert_frame_equal(restored["000001.SZ"], frame)


def test_pipe_characters_inside_data_are_not_transport_prefixes(wire):
    frame = pd.DataFrame({"label|field": ["text|value"]}, index=["stock|date"])
    raw = wire.pack_response("pipe-character", result=frame)
    for message in (raw, "reply-channel|" + raw):
        packet = wire.loads_message(message)
        assert packet is not None
        pd.testing.assert_frame_equal(protocol.decode_value(packet["result"]), frame)


@pytest.mark.parametrize("shape", [(), (1,), (1, 1), (0,), (2, 0)])
def test_structured_arrays_preserve_shapes_fields_and_integer_ids(wire, shape):
    dtype = np.dtype([("orderNo", "u8"), ("price", "f8"), ("depth", "i8", (2,))])
    value = np.zeros(shape, dtype=dtype)
    value["orderNo"] = 2**64 - 1
    value["price"] = 11.6
    value["depth"] = [100, 200]
    decoded = roundtrip(wire, value)
    assert decoded.dtype == dtype and decoded.shape == shape
    np.testing.assert_array_equal(decoded, value)


def test_level2_record_object_depth_survives_json_and_sdk(wire):
    value = np.array([(BIG_ID, 11.6, np.array([11.5, 11.4]), [100, 200])],
                     dtype=[("orderNo", "i8"), ("price", "f8"), ("bidPrice", object), ("bidVol", object)])
    decoded = roundtrip(wire, {"000001.SZ": value})["000001.SZ"]
    assert decoded.dtype == value.dtype and decoded.shape == value.shape
    assert decoded["orderNo"].tolist() == [BIG_ID]
    np.testing.assert_array_equal(decoded["bidPrice"][0], value["bidPrice"][0])
    assert decoded["bidVol"].tolist() == [[100, 200]]


def test_wide_history_keeps_all_stocks_dates_and_values(wire):
    dates = [str(i) for i in range(5668)]
    native = {"000001.SZ": pd.DataFrame({"close": np.arange(5668, dtype=float),
                                        "volume": np.arange(5668, dtype="int64")}, index=dates)}
    expected = market_data_legacy_shape(native, "1d", ["close", "volume"], ["000001.SZ"])
    restored = roundtrip(wire, expected)
    assert list(restored) == ["close", "volume"]
    for field in expected:
        pd.testing.assert_frame_equal(restored[field], expected[field])


def test_standalone_encoder_matches_shared_source():
    core = ast.parse((ROOT / "cfquant/protocol.py").read_text(encoding="utf-8"))
    expected = ast.dump(next(n for n in core.body if isinstance(n, ast.FunctionDef) and n.name == "_encode_dataframe"))
    for path in LITE_PATHS:
        raw = path.read_bytes()
        assert b"\n" not in raw.replace(b"\r\n", b""), path
        tree = ast.parse(raw.decode("gbk"), feature_version=(3, 6))
        actual = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_encode_dataframe")
        assert ast.dump(actual) == expected, path
