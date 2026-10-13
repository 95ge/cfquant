"""Focused runtime checks for the standalone Lite compatibility adapters."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from cfquant import level2
from cfquant.tx_trade_bridge import TxTradeBridge


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))


def _lite_bridge_class(path):
    source = path.read_bytes().decode("gbk")
    tree = ast.parse(source)
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TxTradeBridge"
    )
    methods = {
        "_dispatch_xtdata_compat", "_get_market_data", "_get_market_data_ex",
        "_get_local_data", "_call_local_data", "_dispatch_xttrader_compat",
        "_query_account_id", "_credit_account_id", "_call_trade_detail_data",
        "_credit_row_data", "_credit_field_value", "_format_credit_rows",
        "_query_credit_detail", "_query_qmt_objects", "_query_stk_compacts",
        "_smt_request", "_smt_response_data", "_format_transfer_result", "_format_compat_query_objects",
        "_format_compat_query_object", "_known_query_fields", "_plain_object",
        "_first_present",
    }
    class_node.bases = [ast.Name(id="BaseTradeBridge", ctx=ast.Load())]
    class_node.body = [
        node for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name in methods
    ]
    constants = {
        "SMT_ASYNC_ARGUMENT_COUNTS", "XTTRADER_TRANSFER_RESULT_METHODS",
        "LITE_OBJECT_QUERY_METHODS", "_LITE_CREDIT_FIELD_ALIASES",
        "L2_GET_PERIODS", "L2_PERIODS", "KLINE_PERIODS",
        "XTDATA_COMPAT_CANDIDATES", "XTDATA_MAINCHAIN_UNSUPPORTED",
    }
    body = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in constants for target in node.targets)
    ]
    body.append(class_node)
    module = ast.Module(body=body, type_ignores=[])
    namespace = dict(vars(__import__("cfquant.tx_trade_bridge", fromlist=["*"])))
    namespace.update(
        BaseTradeBridge=TxTradeBridge,
        market_data_result_needs_fallback=level2.market_data_result_needs_fallback,
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["TxTradeBridge"]


class _FakeQmt:
    def __init__(self):
        self.calls = []

    def get_market_data(self, *args):
        self.calls.append(("legacy", args))
        return pd.DataFrame()

    def get_market_data_ex(self, *args):
        self.calls.append(("modern", args))
        return {"000001.SZ": pd.DataFrame({"close": [11.6]})}

    def get_trade_detail_data(self, account_id, account_type, detail_type, strategy_name):
        self.calls.append(("detail", account_id, account_type, detail_type, strategy_name))
        if detail_type == "account":
            return [SimpleNamespace(m_strAccountID=account_id, m_dBalance=100.0, m_dFinUsedQuota=8.0)]
        return []

    def get_unclosed_compacts(self, account_id, account_type):
        self.calls.append(("compact", account_id, account_type))
        return [SimpleNamespace(m_strAccountID=account_id, m_strInstrumentID="000001", m_eCompactType=1)]


def _bridge(path):
    bridge = _lite_bridge_class(path)(_FakeQmt(), account_id="CREDIT-1", show=False)
    bridge._log = lambda *args, **kwargs: None
    bridge.tx = SimpleNamespace(push=lambda *args, **kwargs: None)
    return bridge


def test_all_lite_entries_contain_shared_data_and_credit_adapters():
    expected = {
        "_get_market_data", "_get_local_data", "_get_instrument_detail",
        "_get_cb_info", "_get_divid_factors", "_get_stock_list_in_sector",
        "_query_credit_detail", "_query_stk_compacts", "_call_trade_detail_data",
    }
    for path in LITE_PATHS:
        tree = ast.parse(path.read_bytes().decode("gbk"))
        bridge = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TxTradeBridge")
        names = {node.name for node in bridge.body if isinstance(node, ast.FunctionDef)}
        assert expected <= names, path


def test_lite_credit_detail_supports_qmt_four_argument_signature():
    bridge = _bridge(LITE_PATHS[0])
    result = bridge._dispatch(
        "xttrader.query_credit_detail",
        {"account": {"account_id": "CREDIT-1", "account_type": "CREDIT"}},
        {"client_id": "test"},
    )
    assert result[0]["account_id"] == "CREDIT-1"
    assert result[0]["account_type"] == 3
    assert result[0]["cfquant_qmt_fields"]["m_dFinUsedQuota"] == 8.0
    assert result[0]["cfquant_source"] == "get_trade_detail_data"
    assert ("detail", "CREDIT-1", "credit", "account", "") in bridge.context.calls


def test_lite_credit_compacts_and_market_fallback_match_common_contract():
    bridge = _bridge(LITE_PATHS[0])
    compact = bridge._dispatch(
        "xttrader.query_stk_compacts",
        {"account_id": "CREDIT-1", "account_type": "CREDIT"},
        {"client_id": "test"},
    )
    assert compact[0]["account_id"] == "CREDIT-1"
    assert compact[0]["instrument_id"] == "000001"

    result = bridge._dispatch(
        "xtdata.get_market_data",
        {"field_list": ["close"], "stock_list": ["000001.SZ"], "period": "1d"},
        {"client_id": "test"},
    )
    assert "close" in result
    local = bridge._dispatch(
        "xtdata.get_local_data",
        {"field_list": ["close"], "stock_list": ["000001.SZ"], "period": "1d"},
        {"client_id": "test"},
    )
    assert "000001.SZ" in local
    assert any(call[0] == "modern" and len(call[1]) == 9 for call in bridge.context.calls)
