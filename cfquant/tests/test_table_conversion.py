"""Shared Web and quote conversions retain pandas' public output semantics."""
import ast
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import pytest

import cfquant_web_server as web
from cfquant import level2, protocol


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))
BIG_ID = 2**60 + 37


def frames():
    return {
        "numeric_ids": pd.DataFrame({"orderNo": pd.Series([BIG_ID, BIG_ID+1], dtype="int64"),
            "unsignedNo": pd.Series([2**64-1, 2**63+17], dtype="uint64"),
            "price": [11.6, np.nan], "flag": [True, False]}),
        "nonfinite": pd.DataFrame({"close": [np.nan, np.inf, -np.inf]}),
        "nullable": pd.DataFrame({"id": pd.Series([BIG_ID, pd.NA], dtype="Int64"),
            "flag": pd.Series([True, pd.NA], dtype="boolean")}),
        "object_depth": pd.DataFrame({"depth": [np.array([100,200]), [300,400]],
            "metadata": [{"label": "行情"}, None]}),
        "object_missing": pd.DataFrame({"value": pd.Series([pd.NA, pd.NaT, np.nan], dtype=object)}),
        "datetime": pd.DataFrame({"date": pd.to_datetime(["2026-01-01", None]),
            "delta": pd.to_timedelta([1, None], unit="ns")}),
        "category": pd.DataFrame({"v": pd.Categorical(["a", "b", None])}),
        "duplicate_columns": pd.DataFrame([[1,2]], columns=["v", "v"]),
        "tuple_labels": pd.DataFrame([[1.0,2.0]], index=pd.MultiIndex.from_tuples([("stock", 1)]),
            columns=pd.MultiIndex.from_tuples([("close", 1), ("close", 2)])),
        "json_key_collision": pd.DataFrame([[1,2],[3,4]],index=[1,"1"],columns=[1,"1"]),
        "empty": pd.DataFrame(),
        "no_rows": pd.DataFrame(columns=["open", "close"]),
        "no_columns": pd.DataFrame(index=["a", "b"]),
    }


@pytest.mark.parametrize("name", list(frames()))
@pytest.mark.parametrize("depth", [0, 2, 38, 39, 40])
def test_web_conversion_matches_pandas_index_contract(name, depth):
    frame = frames()[name]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        expected = web.to_jsonable(frame.to_dict(orient="index"), depth + 1)
        actual = web.to_jsonable(frame, depth)
    assert actual == expected
    assert json.dumps(actual, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)


def test_web_duplicate_index_keeps_existing_error():
    frame = pd.DataFrame({"close": [1.0,2.0]}, index=["same","same"])
    with pytest.raises(ValueError, match="unique"):
        web.to_jsonable(frame)


def test_web_depth_limit_still_applies_to_frame_itself():
    frame = pd.DataFrame({"close": [1.0]})
    assert web.to_jsonable(frame, 41) == str(frame)


def test_nested_financial_and_dividend_results_keep_public_shape():
    balance = pd.DataFrame({"reportDate": [20260630,20260930], "asset": [11.2,12.3],
                           "recordNo": [BIG_ID,BIG_ID+1]}, index=["first","second"])
    factors = pd.DataFrame({"factor": [1.1,1.2]}, index=["20260630","20260930"])
    result = {"financial": {"000001.SZ": {"Balance": balance}}, "factors": factors}
    actual = web.to_jsonable(result)
    assert actual["financial"]["000001.SZ"]["Balance"]["first"] == {
        "reportDate": 20260630, "asset": 11.2, "recordNo": BIG_ID}
    assert actual["factors"] == {"20260630": {"factor": 1.1}, "20260930": {"factor": 1.2}}
    decoded = protocol.decode_value(protocol.encode_value(result))
    pd.testing.assert_frame_equal(decoded["financial"]["000001.SZ"]["Balance"], balance)
    pd.testing.assert_frame_equal(decoded["factors"], factors)


@pytest.fixture(params=[None] + LITE_PATHS, ids=["core"] + [p.stem for p in LITE_PATHS])
def quote_converter(request):
    if request.param is None:
        return level2.quote_records
    tree = ast.parse(request.param.read_bytes().decode("gbk"), feature_version=(3,6))
    names = {"dataframe_numeric_rows", "quote_plain", "quote_records"}
    tree.body = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    namespace = {}
    exec(compile(tree, str(request.param), "exec"), namespace)
    return namespace["quote_records"]


@pytest.mark.parametrize("name", list(frames()))
def test_quote_records_keep_types_values_and_column_order(quote_converter, name):
    frame = frames()[name]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        expected = level2.quote_plain(frame.to_dict("records"))
        actual = quote_converter(frame)
    # The protocol normalizes non-finite values; compare exactly what callers receive.
    assert json.dumps(protocol.encode_value(actual), ensure_ascii=False) == json.dumps(
        protocol.encode_value(expected), ensure_ascii=False)


def test_quote_records_keep_repeated_timestamps(quote_converter):
    frame = pd.DataFrame({"orderNo": [BIG_ID,BIG_ID+1], "price": [11.6,11.7]}, index=[1,1])
    assert quote_converter(frame) == [{"orderNo": BIG_ID, "price": 11.6},
                                      {"orderNo": BIG_ID+1, "price": 11.7}]


def test_standalone_table_helpers_match_shared_sources():
    expected = {}
    for filename, names in [("cfquant/protocol.py", {"dataframe_numeric_rows"}),
                            ("cfquant/level2.py", {"quote_records"})]:
        tree = ast.parse((ROOT/filename).read_text(encoding="utf-8"))
        expected.update({node.name: ast.dump(node) for node in tree.body
                         if isinstance(node,ast.FunctionDef) and node.name in names})
    for path in LITE_PATHS:
        tree = ast.parse(path.read_bytes().decode("gbk"),feature_version=(3,6))
        actual = {node.name: ast.dump(node) for node in tree.body
                  if isinstance(node,ast.FunctionDef) and node.name in expected}
        assert actual == expected
