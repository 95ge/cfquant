"""Credit adapters tested with fake QMT functions; no live business operations."""
import threading
from types import SimpleNamespace

import pytest

from cfquant import xtconstant
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.pipe_bridge import PipeNormalQmtBridge, PipeTradeBridge
from cfquant.protocol import decode_value, loads_message, pack_request, pack_response
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount, StkCompacts, XtCreditDetail, XtSmtAppointmentResponse


ACCOUNT = StockAccount("C123", "CREDIT")
PARAMS = {"account": {"account_id": "C123", "account_type": 3}}
BRIDGES = [TxTradeBridge, NormalQmtBridge, PipeTradeBridge, PipeNormalQmtBridge]


def wire(functions, cls=TxTradeBridge):
    bridge = cls(object(), globals_dict=functions, show=False)
    bridge._log = lambda message: None
    trader = XtQuantTrader()

    def request(action, params, timeout=None):
        msg = loads_message(pack_request(action, params=params, client_id="client"))
        result = bridge._dispatch(action, msg["params"], msg)
        return decode_value(loads_message(pack_response(msg["id"], result=result))["result"])

    def push(kind, raw, target):
        assert target == "client"
        msg = loads_message(raw)
        if msg["type"] == "event":
            trader._make_trader_handler(msg["event"].split(":", 1)[1])(decode_value(msg["data"]))

    bridge.tx = SimpleNamespace(push=push)
    trader._trade_request = request
    return bridge, trader


@pytest.mark.parametrize("cls", BRIDGES)
def test_credit_asset_sdk_aliases_types_and_async(cls):
    raw = SimpleNamespace(m_strAccountID=b"C123", m_nBrokerType=3,
                          m_dInstrumentValue=500.0, m_dTotalDebit=120.0,
                          m_dFinUsedQuota=80.0, m_dSloUsedQuota=0.0,
                          m_dFinEnableQuota=20.0, m_dAvailable=0.0)
    calls = []
    _, trader = wire({"get_trade_detail_data": lambda *args: calls.append(args) or [raw]}, cls)
    row = trader.query_credit_detail(ACCOUNT)[0]
    assert isinstance(row, XtCreditDetail)
    assert row.account_id == "C123" and row.account_type == xtconstant.CREDIT_ACCOUNT
    assert row.m_dMarketValue == 500.0 and row.m_dTotalDebt == 120.0
    assert row.m_dAvailable == 0.0
    assert row.m_dFinEnableQuota == 20.0
    assert not hasattr(row, "m_dFinDebt")
    assert not hasattr(row, "m_dFinFee")
    assert not hasattr(row, "m_dFinUsedQuota")
    assert row.cfquant_qmt_fields == {"m_dFinUsedQuota": 80.0, "m_dSloUsedQuota": 0.0}
    assert "m_dFinUsedQuota" in row.cfquant_missing_fields
    done = threading.Event()
    received = []
    try:
        assert trader.query_credit_detail_async(ACCOUNT, lambda rows: (received.extend(rows), done.set())) > 0
        assert done.wait(2)
        assert vars(received[0]) == vars(row)
        assert calls == [("C123", "credit", "account")] * 2
    finally:
        trader.stop()


def test_native_credit_fields_override_legacy_aliases():
    _, trader = wire({"query_credit_detail": lambda *args: [{
        "account_id": "C123", "m_dMarketValue": 300.0, "m_dInstrumentValue": 400.0,
        "m_dTotalDebt": 0.0, "m_dTotalDebit": 99.0, "m_dFinUsedQuota": 70.0,
    }]})
    row = trader.query_credit_detail(ACCOUNT)[0]
    assert row.m_dMarketValue == 300.0 and row.m_dTotalDebt == 0.0
    assert row.m_dFinUsedQuota == 70.0


@pytest.mark.parametrize("cls", BRIDGES)
def test_debt_contract_fields_from_exact_native_signature(cls):
    fields = {
        "m_strAccountID": "C123", "m_nBrokerType": 3, "m_strExchangeID": "SH",
        "m_strInstrumentID": "600000", "m_eCompactType": 48, "m_eCashgroupProp": 49,
        "m_nOpenDate": 20260909, "m_nBusinessVol": 100, "m_nRealCompactVol": 50,
        "m_nRetEndDate": 20270309, "m_dBusinessBalance": 900.0, "m_dBusinessFare": 1.5,
        "m_dRealCompactBalance": 450.0, "m_dRealCompactFare": 0.5, "m_dRepaidFare": 1.0,
        "m_dRepaidBalance": 450.0, "m_strCompactId": "000123", "m_strPositionStr": "position-1",
    }
    raw = type("CStkUnclosedCompacts", (), dict(fields, __slots__=()))()
    calls = []
    _, trader = wire({
        "get_unclosed_compacts": lambda *args: calls.append(args) or [raw],
        "get_debt_contract": lambda *args: pytest.fail("unexpected deprecated source"),
    }, cls)
    row = trader.query_stk_compacts(ACCOUNT)[0]
    assert isinstance(row, StkCompacts)
    assert calls == [("C123", "CREDIT")]
    assert row.account_type == 3 and row.exchange_id == xtconstant.SH_MARKET
    assert row.compact_id == "000123" and row.instrument_id == "600000"
    assert row.compact_type == 48 and row.cashgroup_prop == 49
    assert row.businessFare == 1.5 and row.repaid_fare == 1.0
    assert row.business_vol == 100 and row.real_compact_vol == 50
    assert row.cfquant_missing_fields == []
    done = threading.Event()
    received = []
    try:
        assert trader.query_stk_compacts_async(ACCOUNT, lambda data: (received.extend(data), done.set())) > 0
        assert done.wait(2)
        assert isinstance(received[0], StkCompacts)
        assert vars(received[0]) == vars(row)
    finally:
        trader.stop()


def test_deprecated_debt_source_preserves_missing_fee_fields():
    calls = []
    _, trader = wire({"get_debt_contract": lambda account_id: calls.append(account_id) or [{
        "m_strAccountID": "C123", "m_dRepaidInterest": 12.0, "m_strCompactId": "0001",
    }]})
    row = trader.query_stk_compacts(ACCOUNT)[0]
    assert calls == ["C123"]
    assert row.compact_id == "0001" and row.m_dRepaidInterest == 12.0
    assert not hasattr(row, "repaid_fare")
    assert row.cfquant_source == "get_debt_contract"


@pytest.mark.parametrize("value", [None, []])
def test_debt_empty_result_does_not_switch_source(value):
    _, trader = wire({
        "get_unclosed_compacts": lambda *args: value,
        "get_debt_contract": lambda *args: pytest.fail("unexpected fallback"),
    })
    assert trader.query_stk_compacts(ACCOUNT) == value


@pytest.mark.parametrize("row", [
    {"m_strAccountID": "OTHER"}, {"account_id": "C123", "m_strAccountID": "OTHER"},
    {"m_strAccountID": "C123", "account_type": 2},
    {"m_strAccountID": "C123", "m_nBrokerType": 2},
])
def test_debt_rejects_other_account_or_account_type(row):
    _, trader = wire({"get_unclosed_compacts": lambda *args: [row]})
    with pytest.raises(ValueError, match="different account|non-CREDIT"):
        trader.query_stk_compacts(ACCOUNT)


def test_debt_qmt_error_is_not_retried_or_hidden():
    def fail(*args):
        raise RuntimeError("account unavailable")

    _, trader = wire({"get_unclosed_compacts": fail,
                      "get_debt_contract": lambda *args: pytest.fail("unexpected fallback")})
    with pytest.raises(RuntimeError, match="account unavailable"):
        trader.query_stk_compacts(ACCOUNT)


@pytest.mark.parametrize("method", ["query_credit_detail", "query_stk_compacts", "query_credit_subjects",
                                   "query_credit_assure", "query_credit_slo_code"])
def test_credit_queries_validate_type_before_using_compat_source(method):
    _, trader = wire({method: lambda *args: pytest.fail("wrong account query")})
    with pytest.raises(ValueError, match="CREDIT account"):
        getattr(trader, method)(StockAccount("C123", "STOCK"))


SMT_CASES = [
    ("smt_appointment_order", ("600000.SH", 7, 100, 0.02)),
    ("smt_appointment_cancel", ("APPLY-1",)),
    ("smt_negotiate_order", ("SRC-1", "600000.SH", 7, 100, 0.02, {})),
    ("smt_compact_return", ("SRC-1", "COMPACT-1", "600000.SH", 100)),
    ("smt_compact_renewal", ("COMPACT-1", "600000.SH", 7, 100, 0.02)),
]


@pytest.mark.parametrize("method,args", SMT_CASES)
def test_smt_business_result_is_correlated_once_via_event(method, args):
    calls = []
    raw = {"success": True, "msg": "accepted", "apply_id": "APPLY-1", "seq": 987}
    _, trader = wire({method: lambda *values: calls.append(values) or raw})
    received = []
    trader.callback = SimpleNamespace(on_smt_appointment_async_response=received.append)
    seq = getattr(trader, method + "_async")(ACCOUNT, *args)
    assert seq > 0 and seq != 987
    assert calls == [("C123",) + args]
    assert len(received) == 1
    assert isinstance(received[0], XtSmtAppointmentResponse)
    assert received[0].seq == seq and received[0].apply_id == "APPLY-1"
    assert received[0].success is True
    assert raw["seq"] == 987


@pytest.mark.parametrize("raw", [False, -1])
def test_smt_rejected_submission_returns_minus_one_without_success_callback(raw):
    _, trader = wire({"smt_appointment_cancel": lambda *args: raw})
    trader.callback = SimpleNamespace(on_smt_appointment_async_response=lambda data: pytest.fail("fabricated callback"))
    assert trader.smt_appointment_cancel_async(ACCOUNT, "APPLY-1") == -1


@pytest.mark.parametrize("raw", [None, 123, True, {"accepted": True, "seq": 123},
                                  {"success": "false", "msg": "error", "apply_id": "-1"},
                                  {"success": True, "msg": "accepted", "apply_id": []},
                                  {"success": True, "msg": "accepted", "apply_id": " "},
                                  {"success": True, "msg": "accepted", "apply_id": True}])
def test_smt_acknowledgement_never_becomes_business_success(raw):
    _, trader = wire({"smt_appointment_cancel": lambda *args: raw})
    trader.callback = SimpleNamespace(on_smt_appointment_async_response=lambda data: pytest.fail("fabricated callback"))
    with pytest.raises(RuntimeError, match="business response"):
        trader.smt_appointment_cancel_async(ACCOUNT, "APPLY-1")


def test_smt_business_rejection_keeps_seq_and_failure():
    _, trader = wire({"smt_appointment_cancel": lambda *args: {
        "success": False, "msg": "not cancelable", "apply_id": "-1",
    }})
    received = []
    trader.callback = SimpleNamespace(on_smt_appointment_async_response=received.append)
    seq = trader.smt_appointment_cancel_async(ACCOUNT, "APPLY-1")
    assert received[0].seq == seq and received[0].success is False
    assert received[0].msg == "not cancelable"


def test_smt_cpp_response_fields_reach_sdk_callback():
    raw = type("BrokerResponse", (), dict(__slots__=(), m_bSuccess=True,
               m_strMsg="accepted", m_strApplyID="000123", m_nSeq=987))()
    _, trader = wire({"smt_appointment_cancel": lambda *args: raw})
    received = []
    trader.callback = SimpleNamespace(on_smt_appointment_async_response=received.append)
    seq = trader.smt_appointment_cancel_async(ACCOUNT, "000123")
    assert received[0].seq == seq and received[0].apply_id == "000123"
    assert received[0].msg == "accepted" and received[0].success is True


@pytest.mark.parametrize("fields", [{"account_id": "OTHER"}, {"account_type": 2}])
def test_smt_mismatched_account_response_is_not_delivered(fields):
    raw = dict(fields, success=True, msg="accepted", apply_id="000123")
    _, trader = wire({"smt_appointment_cancel": lambda *args: raw})
    trader.callback = SimpleNamespace(on_smt_appointment_async_response=lambda data: pytest.fail("wrong account"))
    with pytest.raises(ValueError, match="different account|non-CREDIT"):
        trader.smt_appointment_cancel_async(ACCOUNT, "000123")


def test_smt_side_effect_is_never_retried_after_type_error():
    calls = []

    def submit(*args):
        calls.append(args)
        raise TypeError("error after submission")

    _, trader = wire({"smt_appointment_cancel": submit})
    with pytest.raises(TypeError, match="after submission"):
        trader.smt_appointment_cancel_async(ACCOUNT, "APPLY-1")
    assert calls == [("C123", "APPLY-1")]


def test_smt_missing_native_capability_reports_unavailable():
    _, trader = wire({})
    with pytest.raises(NotImplementedError, match="QMT does not expose"):
        trader.smt_negotiate_order_async(ACCOUNT, "SRC-1", "600000.SH", 7, 100, 0.02)
