import itertools
import threading
from types import SimpleNamespace

import pandas as pd
import pytest

import cfquant_web_server as web
from cfquant import xtconstant, xtdata
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.pipe_bridge import PipeNormalQmtBridge, PipeTradeBridge
from cfquant.protocol import decode_value, loads_message, pack_request, pack_response
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import (
    CreditAssure, CreditSloCode, CreditSubjects, StockAccount, XtCreditDetail, XtPositionStatistics,
)


def make_bridge(functions=None, cls=TxTradeBridge, context=None):
    bridge = cls(context or object(), globals_dict=functions or {}, show=False)
    bridge._log = lambda message: None
    return bridge


class LoopbackClient:
    def __init__(self, bridge):
        self.bridge = bridge
        self.calls = []

    def request(self, action, params, timeout=None):
        self.calls.append((action, params))
        message = loads_message(pack_request(action, params=params, client_id="test"))
        result = self.bridge._dispatch(action, message["params"], message)
        return decode_value(loads_message(pack_response(message["id"], ok=True, result=result))["result"])


def wire_sdk(monkeypatch, functions=None, cls=TxTradeBridge):
    client = LoopbackClient(make_bridge(functions, cls))
    monkeypatch.setattr(xtdata, "get_client", lambda: client)
    trader = XtQuantTrader()
    trader._seq = itertools.count(1)
    trader._trade_request = client.request
    return client, trader


@pytest.mark.parametrize("cls", [TxTradeBridge, NormalQmtBridge, PipeTradeBridge, PipeNormalQmtBridge])
def test_legacy_instrument_alias_shared_by_all_bridges(monkeypatch, cls):
    calls = []
    original = {"InstrumentID": "000001", "PreClose": 10.2}
    wire_sdk(monkeypatch, {"get_instrumentdetail": lambda code: calls.append(code) or original}, cls)
    result = xtdata.get_instrument_detail("000001.SZ", True)
    assert calls == ["000001.SZ"]
    assert result["PreClose"] == 10.2
    assert result["cfquant_detail_partial"] is True
    assert result["cfquant_detail_source"] == "get_instrumentdetail"
    assert "cfquant_detail_partial" not in original


def test_instrument_tries_legacy_after_missing_modern_callable(monkeypatch):
    def modern(*args):
        raise NotImplementedError("get_instrument_detail not found")

    wire_sdk(monkeypatch, {"get_instrument_detail": modern, "get_instrumentdetail": lambda code: {"PreClose": 9}})
    assert xtdata.get_instrument_detail("000001.SZ")["PreClose"] == 9


@pytest.mark.parametrize("error", [RuntimeError("permission denied"), AttributeError("broken internal state")])
def test_instrument_does_not_hide_real_errors(monkeypatch, error):
    def modern(*args):
        raise error

    wire_sdk(monkeypatch, {"get_instrument_detail": modern, "get_instrumentdetail": lambda code: pytest.fail("unexpected fallback")})
    with pytest.raises(type(error), match=str(error)):
        xtdata.get_instrument_detail("000001.SZ")


def test_nested_context_callable_resolution(monkeypatch):
    context = SimpleNamespace(context=SimpleNamespace(get_convert_bond_info=lambda code: {"stockcode": "000001.SZ", "convert_price": 10.5}))
    monkeypatch.setattr(xtdata, "get_client", lambda: LoopbackClient(make_bridge(context=context)))
    result = xtdata.get_cb_info("123001.SZ")
    assert result == {
        "bondCode": "123001.SZ", "stockCode": "000001.SZ", "bondConvPrice": 10.5,
        "cfquant_partial": True, "cfquant_source": "get_convert_bond_info",
    }
    assert "bondIssueSize" not in result


@pytest.mark.parametrize("value", [None, {}])
def test_cb_info_preserves_no_data(monkeypatch, value):
    wire_sdk(monkeypatch, {"get_convert_bond_info": lambda code: value})
    assert xtdata.get_cb_info("123001.SZ") == value


def test_cb_info_does_not_call_same_named_vba_function(monkeypatch):
    wire_sdk(monkeypatch, {"get_cb_info": lambda *args: pytest.fail("VBA is not the Python source")})
    with pytest.raises(NotImplementedError, match="get_convert_bond_info"):
        xtdata.get_cb_info("123001.SZ")


def test_divid_factors_wire_shape_sort_and_exchange_date_range(monkeypatch):
    start = xtdata._divid_time_bound("20240909")
    end = xtdata._divid_time_bound("20240909", end=True)
    row = [0.1, 0.2, 0.3, 0.4, 5.0, 1, 1.2]
    raw = {end + 1: row, end: row, start - 1: row, start: row}
    calls = []
    wire_sdk(monkeypatch, {"get_divid_factors": lambda code: calls.append(code) or raw})
    result = xtdata.get_divid_factors("600000.SH", "20240909", "20240909")
    assert isinstance(result, pd.DataFrame)
    assert list(result.index) == [start, end]
    assert list(result.columns) == ["interest", "stockBonus", "stockGift", "allotNum", "allotPrice", "gugai", "dr"]
    assert result.iloc[0].tolist() == row
    assert calls == ["600000.SH"]
    assert start == 1725811200000
    assert len(raw) == 4


def test_divid_time_bound_seconds():
    assert xtdata._divid_time_bound("20240909000000") == xtdata._divid_time_bound("20240909")
    assert xtdata._divid_time_bound("20240909000000", end=True) == 1725811200999


@pytest.mark.parametrize("start,end", [("20240910", "20240909"), ("20240230", ""), ("bad", ""), (None, "")])
def test_divid_rejects_invalid_range_before_rpc(monkeypatch, start, end):
    client, _ = wire_sdk(monkeypatch)
    with pytest.raises(ValueError):
        xtdata.get_divid_factors("600000.SH", start, end)
    assert client.calls == []


@pytest.mark.parametrize("value", [{1: [1, 2]}, {1: {"dr": 1.0}}, []])
def test_divid_rejects_invalid_backend_shape(monkeypatch, value):
    wire_sdk(monkeypatch, {"get_divid_factors": lambda code: value})
    with pytest.raises(ValueError):
        xtdata.get_divid_factors("600000.SH")


def test_divid_empty_and_named_rows(monkeypatch):
    wire_sdk(monkeypatch, {"get_divid_factors": lambda code: {}})
    empty = xtdata.get_divid_factors("600000.SH")
    assert empty.empty and len(empty.columns) == 7
    row = dict(zip(empty.columns, range(7)))
    wire_sdk(monkeypatch, {"get_divid_factors": lambda code: {1: row}})
    assert xtdata.get_divid_factors("600000.SH").iloc[0].tolist() == list(range(7))


def test_sector_tree_flattens_and_handles_duplicate_and_cyclic_nodes(monkeypatch):
    tree = {"": [["A"], ["folder1", "folder2"]], "folder1": [["B", "A"], ["folder2"]], "folder2": [["C"], ["folder1"]]}
    calls = []
    wire_sdk(monkeypatch, {"get_sector_list": lambda node: calls.append(node) or tree[node]})
    assert xtdata.get_sector_list() == ["A", "B", "C"]
    assert calls == ["", "folder1", "folder2"]


@pytest.mark.parametrize("info", [None, [], ["sector", "folder"], [["A"], [None]]])
def test_sector_tree_rejects_invalid_shape(monkeypatch, info):
    wire_sdk(monkeypatch, {"get_sector_list": lambda node: info})
    with pytest.raises(ValueError):
        xtdata.get_sector_list()


def test_sector_history_timestamp_forwarded(monkeypatch):
    calls = []
    wire_sdk(monkeypatch, {"get_stock_list_in_sector": lambda *args: calls.append(args) or ["000001.SZ"]})
    assert xtdata.get_stock_list_in_sector("A") == ["000001.SZ"]
    xtdata.get_stock_list_in_sector("A", real_timetag=1234567890000)
    assert calls == [("A",), ("A", 1234567890000)]


def test_sector_history_is_not_silently_dropped(monkeypatch):
    wire_sdk(monkeypatch, {"get_stock_list_in_sector": lambda sector: pytest.fail("must not query current data")})
    with pytest.raises(TypeError):
        xtdata.get_stock_list_in_sector("A", 1234567890000)


@pytest.mark.parametrize("method,name", [("create_sector", "sector_name"), ("create_sector_folder", "folder_name")])
def test_sector_creation_preserves_actual_name_and_overwrite(monkeypatch, method, name):
    calls = []
    wire_sdk(monkeypatch, {method: lambda *args: calls.append(args) or "created-1"})
    assert getattr(xtdata, method)(parent_node="parent", **{name: "created", "overwrite": False}) == "created-1"
    assert calls == [("parent", "created", False)]


def test_reset_sector_accepts_legacy_generic_payload_and_empty_list(monkeypatch):
    calls = []
    client, _ = wire_sdk(monkeypatch, {"reset_sector_stock_list": lambda *args: calls.append(args) or True})
    assert xtdata.reset_sector("A", []) is True
    assert client.request("xtdata.reset_sector", {"args": [], "kwargs": {"sector_name": "A", "stock_list": ["000001.SZ"]}}) is True
    assert calls == [("A", []), ("A", ["000001.SZ"])]


def test_sector_deletion_aggregates_failure_without_skipping_later_codes(monkeypatch):
    calls = []
    def remove(sector, code):
        calls.append((sector, code))
        return code != "000001.SZ"

    wire_sdk(monkeypatch, {"remove_stock_from_sector": remove})
    assert xtdata.remove_stock_from_sector("A", ["000001.SZ", "600000.SH", "000001.SZ"]) is False
    assert calls == [("A", "000001.SZ"), ("A", "600000.SH")]
    assert xtdata.remove_stock_from_sector("A", []) is True


@pytest.mark.parametrize("method", ["reset_sector", "remove_stock_from_sector"])
@pytest.mark.parametrize("codes", ["000001.SZ", ["000001.SZ", None], [""]])
def test_sector_mutation_validates_entire_list_before_first_change(monkeypatch, method, codes):
    wire_sdk(monkeypatch, {"reset_sector_stock_list": lambda *args: pytest.fail("invalid mutation"), "remove_stock_from_sector": lambda *args: pytest.fail("invalid mutation")})
    with pytest.raises(ValueError, match="stock_list"):
        getattr(xtdata, method)("A", codes)


def test_sector_mutation_does_not_retry_business_typeerror(monkeypatch):
    calls = []
    def create(*args):
        calls.append(args)
        raise TypeError("backend failure after write")

    wire_sdk(monkeypatch, {"create_sector": create})
    with pytest.raises(TypeError, match="backend failure"):
        xtdata.create_sector("", "A", True)
    assert len(calls) == 1


def test_formula_batch_signature_and_wire_dataframe(monkeypatch):
    calls = []
    def batch(*args):
        calls.append(args)
        return [{"formula": "MA", "stock": "000001.SZ", "argument": {}, "result": {"outputs": pd.DataFrame({"MA": [10.5]}, index=["20240909"])}}]

    wire_sdk(monkeypatch, {"call_formula_batch": batch})
    result = xtdata.call_formula_batch(["MA"], ["000001.SZ"], "1d", count=2, extend_params=[{"MA:n1": 5}])
    assert calls == [(["MA"], ["000001.SZ"], "1d", "", "", 2, "none", [{"MA:n1": 5}])]
    assert result[0]["result"]["outputs"].iloc[0, 0] == 10.5


def test_position_statistics_uses_documented_detail_type(monkeypatch):
    calls = []
    raw = SimpleNamespace(m_strAccountID="A123", m_strExchangeID="SF", m_strInstrumentID="ag2412", m_nPosition=3, m_nYestodayPosition=2, m_dOpenCost=100.5)
    _, trader = wire_sdk(monkeypatch, {"get_trade_detail_data": lambda *args: calls.append(args) or [raw]})
    result = trader.query_position_statistics(StockAccount("A123", "FUTURE"))
    assert calls == [("A123", "future", "position_statistics")]
    assert isinstance(result[0], XtPositionStatistics)
    assert result[0].yesterday_position == 2
    assert result[0].open_cost == 100.5
    assert result[0].exchange_id == "SF"
    assert result[0].account_type == xtconstant.FUTURE_ACCOUNT
    assert not hasattr(result[0], "float_profit")


@pytest.mark.parametrize("method,source,cls,field,value", [
    ("query_credit_assure", "get_assure_contract", CreditAssure, "assure_status", 48),
    ("query_credit_subjects", "get_assure_contract", CreditSubjects, "fin_ratio", 0.8),
    ("query_credit_slo_code", "get_enable_short_contract", CreditSloCode, "enable_amount", 100),
])
def test_credit_query_sync_and_callback_return_typed_fields(monkeypatch, method, source, cls, field, value):
    raw = {"m_strExchangeID": "SH", "m_strInstrumentID": "600000", "m_eAssureStatus": 48, "m_dFinRatio": 0.8, "m_nEnableAmount": 100, "m_eQuerySloType": 49}
    calls = []
    _, trader = wire_sdk(monkeypatch, {source: lambda account_id: calls.append(account_id) or [raw]})
    account = StockAccount("A123", "CREDIT")
    result = getattr(trader, method)(account)
    assert isinstance(result[0], cls)
    assert getattr(result[0], field) == value
    assert result[0].account_id == "A123"
    assert result[0].account_type == xtconstant.CREDIT_ACCOUNT
    assert result[0].exchange_id == xtconstant.SH_MARKET
    assert not hasattr(result[0], "slo_ratio")
    received = []
    done = threading.Event()
    try:
        assert getattr(trader, method + "_async")(account, lambda data: (received.append(data), done.set())) == 1
        assert done.wait(2)
        assert isinstance(received[0][0], cls)
        assert calls == ["A123", "A123"]
    finally:
        trader.stop()


@pytest.mark.parametrize("cls", [XtPositionStatistics, CreditAssure, CreditSubjects, CreditSloCode])
def test_query_object_reads_cpp_properties_and_preserves_native_fields(cls):
    row = type("CppRow", (), {"__slots__": (), "m_strAccountID": "A123", "m_strInstrumentID": "600000", "m_strExchangeID": "SH"})()
    result = cls.from_any(row)
    assert result.account_id == "A123"
    assert result.instrument_id == "600000"
    assert cls.from_any({"instrument_id": "native", "m_strInstrumentID": "other"}).instrument_id == "native"


def test_slo_source_enum_and_missing_fields():
    result = CreditSloCode.from_any({"m_eQuerySloType": 49, "m_nEnableAmount": 0})
    assert result.cashgroup_prop == 49
    assert result.enable_amount == 0
    assert not hasattr(result, "slo_ratio")


@pytest.mark.parametrize("cls", [TxTradeBridge, NormalQmtBridge, PipeTradeBridge, PipeNormalQmtBridge])
def test_credit_detail_uses_credit_account_query_and_preserves_cpp_fields(monkeypatch, cls):
    calls = []
    raw = type("CCreditAccountDetail", (), {
        "__slots__": (), "m_strAccountID": b"A123", "m_nBrokerType": 3,
        "m_dTotalDebit": 123.5, "m_dFinEnableQuota": 200.0,
        "m_dSloEnableQuota": 0.0, "m_dPerAssurescaleValue": 2.5,
        "m_dEnableBailBalance": 80.0,
    })()
    _, trader = wire_sdk(monkeypatch, {
        "get_trade_detail_data": lambda *args: calls.append(args) or [raw],
        "query_credit_detail": lambda *args: pytest.fail("unexpected legacy query"),
    }, cls)
    account = StockAccount("A123", "CREDIT")
    result = trader.query_credit_detail(account)
    assert calls == [("A123", "credit", "account")]
    assert isinstance(result[0], XtCreditDetail)
    assert result[0].account_id == "A123"
    assert result[0].account_type == xtconstant.CREDIT_ACCOUNT
    assert result[0].m_dTotalDebt == result[0].m_dTotalDebit == 123.5
    assert result[0].m_dFinEnableQuota == 200.0
    assert result[0].m_dSloEnableQuota == 0.0
    assert result[0].m_dPerAssurescaleValue == 2.5
    assert result[0].m_dEnableBailBalance == 80.0
    received = []
    done = threading.Event()
    try:
        assert trader.query_credit_detail_async(account, lambda data: (received.append(data), done.set())) == 1
        assert done.wait(2)
        assert isinstance(received[0][0], XtCreditDetail)
        assert vars(received[0][0]) == vars(result[0])
    finally:
        trader.stop()


@pytest.mark.parametrize("rows", [None, []])
def test_credit_detail_preserves_none_and_empty_results(monkeypatch, rows):
    _, trader = wire_sdk(monkeypatch, {"get_trade_detail_data": lambda *args: rows})
    assert trader.query_credit_detail(StockAccount("A123", "CREDIT")) == rows


def test_web_credit_detail_routes_to_native_credit_account_query(monkeypatch):
    calls = []
    client = LoopbackClient(make_bridge({
        "get_trade_detail_data": lambda *args: calls.append(args) or [{
            "m_strAccountID": "A123", "m_nBrokerType": 3, "m_dFinEnableQuota": 200.0,
        }],
    }, cls=PipeNormalQmtBridge))

    def request(account_id, bridge_id, channel, action, params, **kwargs):
        assert account_id == "A123"
        assert bridge_id == "credit_bridge"
        assert kwargs["account_type"] == "CREDIT"
        assert kwargs["default_channel"] == "normal"
        return {
            "bridge_id": bridge_id, "channel": "normal", "mode": "ctypes",
            "fallback": False, "fallback_reason": "",
            "result": client.request(action, params),
        }

    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "credit_bridge")
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": "Credit QMT"})
    monkeypatch.setattr(web, "account_request", request)
    result = web.query_credit_account({
        "account_id": "A123", "account_type": "CREDIT", "action": "detail",
        "account_key": "credit_bridge:CREDIT:A123",
    })
    assert calls == [("A123", "credit", "account")]
    assert result["action"] == "xttrader.query_credit_detail"
    assert result["result"][0]["m_dFinEnableQuota"] == 200.0
    assert result["result"][0]["account_id"] == result["account_id"] == "A123"


def test_credit_detail_supports_required_strategy_argument(monkeypatch):
    calls = []
    raw = {"m_strAccountID": "A123", "m_dFinUsedQuota": 0.0}

    def query(account_id, account_type, detail_type, strategy):
        calls.append((account_id, account_type, detail_type, strategy))
        return [raw]

    _, trader = wire_sdk(monkeypatch, {"get_trade_detail_data": query})
    result = trader.query_credit_detail(StockAccount("A123", "CREDIT"))
    assert calls == [("A123", "credit", "account", "")]
    assert result[0].cfquant_qmt_fields["m_dFinUsedQuota"] == 0.0
    assert not hasattr(result[0], "m_dFinUsedQuota")
    assert not hasattr(result[0], "m_dFinEnableQuota")
    assert "account_id" not in raw


def test_credit_detail_rejects_wrong_account_type_before_query(monkeypatch):
    _, trader = wire_sdk(monkeypatch, {"get_trade_detail_data": lambda *args: pytest.fail("unexpected query")})
    with pytest.raises(ValueError, match="requires a CREDIT account"):
        trader.query_credit_detail(StockAccount("A123"))


@pytest.mark.parametrize("row,error", [
    ({"m_strAccountID": "OTHER"}, "different account"),
    ({"account_id": "A123", "m_strAccountID": "OTHER"}, "different account"),
    ({"m_strAccountID": "A123", "m_nBrokerType": 2}, "non-CREDIT account"),
    ({}, "invalid credit account row"),
])
def test_credit_detail_rejects_mismatched_or_invalid_rows(monkeypatch, row, error):
    _, trader = wire_sdk(monkeypatch, {"get_trade_detail_data": lambda *args: [row]})
    with pytest.raises(ValueError, match=error):
        trader.query_credit_detail(StockAccount("A123", "CREDIT"))


def test_credit_detail_does_not_hide_qmt_query_failure(monkeypatch):
    def query(*args):
        raise RuntimeError("credit account is not logged in")

    _, trader = wire_sdk(monkeypatch, {
        "get_trade_detail_data": query,
        "query_credit_detail": lambda *args: pytest.fail("unexpected fallback"),
    })
    with pytest.raises(RuntimeError, match="not logged in"):
        trader.query_credit_detail(StockAccount("A123", "CREDIT"))


@pytest.mark.parametrize("source", ["query_credit_detail", "get_credit_detail"])
def test_credit_detail_keeps_legacy_callable_without_trade_detail(monkeypatch, source):
    _, trader = wire_sdk(monkeypatch, {source: lambda *args: [{"account_id": "A123"}]})
    result = trader.query_credit_detail(StockAccount("A123", "CREDIT"))
    assert isinstance(result[0], XtCreditDetail)
    assert result[0].account_id == "A123"


@pytest.mark.parametrize("rows", [None, []])
def test_query_preserves_none_and_empty_list(monkeypatch, rows):
    _, trader = wire_sdk(monkeypatch, {"get_assure_contract": lambda account_id: rows})
    assert trader.query_credit_assure(StockAccount("A123", "CREDIT")) == rows


def test_query_rejects_wrong_account_type_before_call(monkeypatch):
    _, trader = wire_sdk(monkeypatch, {"get_assure_contract": lambda account_id: pytest.fail("wrong account type")})
    with pytest.raises(ValueError, match="CREDIT account"):
        trader.query_credit_assure(StockAccount("A123"))


def test_query_rejects_cross_account_data(monkeypatch):
    _, trader = wire_sdk(monkeypatch, {"get_assure_contract": lambda account_id: [{"m_strAccountID": "OTHER"}]})
    with pytest.raises(ValueError, match="different account"):
        trader.query_credit_assure(StockAccount("A123", "CREDIT"))


def test_query_normalizes_qmt_bytes_and_scalar_wrappers(monkeypatch):
    class Scalar:
        def item(self):
            return 100

    row = SimpleNamespace(m_strAccountID=b"A123", m_strExchangeID=b"SH",
                          m_strInstrumentID=b"600000", m_nEnableAmount=Scalar())
    _, trader = wire_sdk(monkeypatch, {"get_enable_short_contract": lambda account_id: [row]})
    result = trader.query_credit_slo_code(StockAccount("A123", "CREDIT"))[0]
    assert result.account_id == "A123"
    assert result.exchange_id == xtconstant.SH_MARKET
    assert result.instrument_id == "600000"
    assert result.enable_amount == 100


def test_ipo_and_purchase_limit_use_exact_qmt_signatures(monkeypatch):
    calls = []
    _, trader = wire_sdk(monkeypatch, {"get_ipo_data": lambda: {"123001.SZ": {"name": "CB"}}, "get_new_purchase_limit": lambda account_id: calls.append(account_id) or {"SH": 1000}})
    assert trader.query_ipo_data()["123001.SZ"]["name"] == "CB"
    assert trader.query_new_purchase_limit(StockAccount("A123")) == {"SH": 1000}
    assert calls == ["A123"]


@pytest.mark.parametrize("method", ["get_cb_info", "get_divid_factors", "get_sector_list", "get_stock_list_in_sector", "get_instrument_detail", "call_formula_batch"])
def test_new_readonly_methods_keep_trade_first_routing(monkeypatch, method):
    monkeypatch.setattr(web, "default_runtime_client_mode", lambda: "lttx")
    assert web._external_default_channel("xtdata." + method) == "trade"


def test_new_code_queries_include_market_routing_metadata(monkeypatch):
    client, _ = wire_sdk(monkeypatch, {
        "get_convert_bond_info": lambda code: {},
        "get_divid_factors": lambda code: {},
        "call_formula_batch": lambda *args: [],
    })
    xtdata.get_cb_info("123219.SZ")
    xtdata.get_divid_factors("600000.SH")
    xtdata.call_formula_batch(["MA"], ["000001.SZ", "600000.SH"], "1d")
    assert [web.data_request_markets(params) for action, params in client.calls] == [["SZ"], ["SH"], ["SZ", "SH"]]


def test_missing_legacy_callable_can_still_use_basic_fallback(monkeypatch):
    def missing(code):
        raise RuntimeError("get_instrumentdetail not found")

    wire_sdk(monkeypatch, {"get_instrumentdetail": missing, "get_stock_name": lambda code: "TEST"})
    assert xtdata.get_instrument_detail("000001.SZ")["cfquant_detail_fallback"] is True
