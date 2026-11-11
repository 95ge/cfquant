"""Split-order regressions. Every native call and transport is an in-memory fake."""

import copy
import json

import pytest

from cfquant import order_meta
from cfquant.order_identity import OrderCallbackCache, restore_order_remark
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttype import XtOrder, XtTrade
from cfquant.tests.test_cftrader import connected, order
from cfquant.tests.test_trade_strategy_callback import bridge


A, B = 1098909568, 1098909569
SUBMISSION = "a" * 32
REMARK = "split-test__cfq_" + SUBMISSION
ACCOUNT = "TEST_ONLY"


def child(number, remark=REMARK):
    return dict(account_id=ACCOUNT, account_type="STOCK", stock_code="688393.SH",
                order_id=number, m_nRef=number, m_nOrderID=number,
                order_sysid="SYS-" + str(number), m_strOrderSysID="SYS-" + str(number),
                order_volume=100000 if number == A else 12672, order_type=24, price=50,
                order_remark=remark, m_strRemark=remark)


def make_bridge(canonical=A):
    instance = TxTradeBridge.__new__(TxTradeBridge)
    instance.file_io_enabled = False
    TxTradeBridge.__init__(instance, None, show=False)
    instance._log = lambda *args, **kwargs: None
    record = dict(account_id=ACCOUNT, account_type="STOCK", stock_code="688393.SH",
                  user_order_id=REMARK, order_remark="split-test", strategy_name="strategy",
                  order_volume=112672, status="accepted")
    if canonical is not None:
        record.update(order_id=canonical, canonical_order_id=canonical, status="bound")
    instance.order_meta_cache.upsert(record)
    return instance


def query(instance, row):
    return instance._enrich_query_order_meta_fields(row, ACCOUNT, "STOCK")


def callback(instance, row):
    record, info = instance.order_meta_cache.resolve_callback(row, account_id=ACCOUNT, account_type="STOCK")
    return order_meta.apply_record_to_callback(row, record, info)


@pytest.mark.parametrize("canonical", [None, A, B])
@pytest.mark.parametrize("numbers", [(A, B), (B, A)])
@pytest.mark.parametrize("path", ["query", "callback", "interleaved"])
def test_children_keep_ids_and_tracking_across_arrival_orders(canonical, numbers, path):
    instance = make_bridge(canonical)
    for index, number in enumerate(numbers * 2):
        receive = callback if path == "callback" or (path == "interleaved" and index % 2) else query
        row = receive(instance, child(number))
        assert row["order_id"] == row["m_nRef"] == number
        assert row["order_volume"] == (100000 if number == A else 12672)
        assert row["order_remark"] == "split-test"
        assert row["cfquant_submission_id"] == SUBMISSION
        assert row["cfquant_child_id"] == SUBMISSION + ":" + str(number)
        assert row["strategy_name"] == "strategy"
        assert not row.get("cfquant_order_id_reconciled")
    cache = instance.order_meta_cache
    for number in (A, B):
        record = cache.by_ref[("default", "STOCK", ACCOUNT, str(number))]
        assert record["canonical_order_id"] == number
        assert str(B if number == A else A) not in record["order_refs"]


@pytest.mark.parametrize("reverse_store", [False, True])
def test_reload_retains_both_children_and_resolves_trades_without_remarks(reverse_store):
    instance = make_bridge()
    for number in (A, B):
        query(instance, child(number))
    store = {}
    for record in instance.order_meta_cache._unique_records_locked():
        store.update(order_meta.store_entries_for_record(record))
    if reverse_store:
        store = dict(reversed(list(store.items())))
    reloaded = make_bridge(None)
    reloaded.order_meta_cache.load_store(json.loads(json.dumps(store)))
    for number in (B, A):
        row = callback(reloaded, child(number, remark=""))
        assert XtTrade.from_any(row).order_id == number
        assert row["cfquant_child_id"] == SUBMISSION + ":" + str(number)


def test_legacy_polluted_store_does_not_authorize_sibling_aliases():
    instance = make_bridge()
    old = dict(next(iter(instance.order_meta_cache.by_user.values())))
    old.pop("order_identity_version")
    old.update(order_refs=[str(A), str(B), "SYS-" + str(B)], m_strOrderSysID="SYS-" + str(B))
    store = dict(order_meta.store_entries_for_record(old))
    instance.order_meta_cache.clear_account(account_id=ACCOUNT, account_type="STOCK")
    instance.order_meta_cache.load_store(store)
    # With no submission evidence, keep the native ID rather than guess metadata.
    assert query(instance, child(B, remark=""))["order_id"] == B
    for number in (B, A):
        assert query(instance, child(number))["order_id"] == number
    assert callback(instance, child(B, remark=""))["cfquant_child_id"] == SUBMISSION + ":" + str(B)


def test_known_broker_evidence_still_reconciles_cross_qmt_callback_alias():
    instance = make_bridge()
    query(instance, child(A))
    alias = child(700015)
    alias.update(order_sysid="SYS-" + str(A), m_strOrderSysID="SYS-" + str(A))
    result = callback(instance, alias)
    assert result["order_id"] == A
    assert result["cfquant_callback_order_id"] == 700015
    assert result["cfquant_child_id"] == SUBMISSION + ":" + str(A)
    alias = child(700015, remark="")
    alias.pop("order_sysid")
    alias.pop("m_strOrderSysID")
    assert callback(instance, alias)["order_id"] == A
    assert query(instance, child(B))["order_id"] == B


def test_submission_without_child_evidence_does_not_choose_a_sibling():
    instance = make_bridge()
    for number in (A, B):
        query(instance, child(number))
    row = callback(instance, dict(account_id=ACCOUNT, stock_code="688393.SH", order_remark=REMARK))
    assert row.get("order_id") is None
    assert row["cfquant_submission_id"] == SUBMISSION
    assert "cfquant_child_id" not in row


def test_callback_text_cache_keeps_siblings_separate():
    cache = OrderCallbackCache()
    for number in (A, B):
        cache.remember(dict(child(number), strategy_name="strategy"), "STOCK")
    assert len(cache.records) == 2
    for number in (A, B):
        data = child(number, remark="")
        cache.enrich(data, "STOCK")
        assert data["cfquant_child_id"] == SUBMISSION + ":" + str(number)


def test_broker_only_trade_uses_child_cache_not_submission_return_id():
    instance = make_bridge()
    instance._remember_order_request(ACCOUNT, "688393.SH", REMARK, "strategy", order_id=A)
    for number in (A, B):
        instance._remember_order_callback_fields(dict(child(number), strategy_name="strategy"))
    row = child(B)
    for name in ("order_id", "m_nRef", "m_nOrderID"):
        row.pop(name)
    instance._enrich_order_request_fields(row)
    assert row["order_id"] == B
    assert row["cfquant_child_id"] == SUBMISSION + ":" + str(B)


def test_missing_child_id_does_not_choose_first_known_child_in_legacy_path():
    instance = make_bridge()
    instance._remember_order_request(ACCOUNT, "688393.SH", REMARK, "strategy", order_id=A)
    for number in (A, B):
        instance._remember_order_callback_fields(dict(child(number), strategy_name="strategy"))
    row = dict(account_id=ACCOUNT, account_type="STOCK", stock_code="688393.SH", order_remark=REMARK)
    instance._enrich_order_request_fields(row)
    assert not row.get("order_id")
    assert "cfquant_child_id" not in row


def test_broker_only_callback_cannot_bind_unknown_child_to_shared_submission():
    instance = make_bridge()
    query(instance, child(A))
    row = child(B)
    for name in ("order_id", "m_nRef", "m_nOrderID"):
        row.pop(name)
    result = callback(instance, row)
    assert not result.get("order_id")
    assert "cfquant_child_id" not in result
    assert query(instance, child(B))["order_id"] == B
    assert callback(instance, child(A))["order_id"] == A


def test_numeric_broker_id_is_not_another_childs_local_id():
    instance = make_bridge()
    query(instance, child(A))
    row = dict(account_id=ACCOUNT, stock_code="688393.SH", order_sysid=str(A))
    assert not callback(instance, row).get("order_id")


def test_query_children_with_shared_broker_id_stay_separate():
    instance = make_bridge()
    for number in (A, B):
        row = child(number)
        row.update(order_sysid="SHARED", m_strOrderSysID="SHARED")
        assert query(instance, row)["order_id"] == number
    for number in (A, B):
        row = child(number)
        row.update(order_sysid="SHARED", m_strOrderSysID="SHARED")
        assert callback(instance, row)["order_id"] == number
    unknown = dict(account_id=ACCOUNT, stock_code="688393.SH", order_sysid="SHARED", order_remark=REMARK)
    assert not callback(instance, unknown).get("order_id")


def test_tracking_preserves_public_remark_and_recomputes_child_after_id_change():
    row = restore_order_remark(dict(order_id=A, order_remark=REMARK))
    row["order_id"] = B
    restore_order_remark(row)
    assert row["order_remark"] == "split-test"
    assert row["cfquant_child_id"] == SUBMISSION + ":" + str(B)
    row["order_id"] = -1
    restore_order_remark(row)
    assert "cfquant_child_id" not in row


@pytest.mark.parametrize("meta_enabled", [False, True])
def test_one_native_submission_split_orders_trades_and_cancel_remain_distinct(connected, meta_enabled):
    env = connected
    env.bridge.order_meta_enabled = meta_enabled
    native = []

    def passorder(*args):
        env.native_calls.append(args)
        for number in (A, B):
            native.append(dict(m_strAccountID=ACCOUNT, m_strInstrumentID="688393", m_strExchangeID="SH",
                               m_nRef=number, m_nOrderID=number, m_strOrderSysID="SYS-" + str(number),
                               m_strRemark=args[9], m_nVolumeTotalOriginal=100000 if number == A else 12672,
                               m_nVolume=100000 if number == A else 12672, m_strTradeID="T-" + str(number)))
        return A

    env.bridge.globals_dict.update(passorder=passorder, get_trade_detail_data=lambda *args: copy.deepcopy(native))
    env.trader.order_stock(env.account, **order(stock_code="688393.SH", order_volume=112672, order_remark="split-test"))
    assert len(env.native_calls) == 1
    assert env.native_calls[0][6] == 112672
    orders = env.trader.query_stock_orders(env.account)
    trades = env.trader.query_stock_trades(env.account)
    assert [row.order_id for row in orders] == [A, B]
    assert [row.order_id for row in trades] == [A, B]
    assert len({row.cfquant_submission_id for row in orders + trades}) == 1
    assert [row.cfquant_child_id for row in orders] == [row.cfquant_child_id for row in trades]
    assert len({row.cfquant_child_id for row in orders}) == 2
    second = env.trader.query_stock_order(env.account, B)
    assert second.order_volume == 12672
    env.trader.cancel_order_stock(env.account, second.order_id)
    assert env.cancel_calls[-1][0] == str(B)


def test_actual_callback_methods_including_lite_preserve_native_children(bridge):
    bridge._remember_order_request(ACCOUNT, "688393.SH", REMARK, "strategy", order_id=A)
    for number in (A, B):
        row = dict(m_strAccountID=ACCOUNT, m_strInstrumentID="688393", m_strExchangeID="SH",
                   m_nRef=number, m_nOrderID=number, m_strOrderSysID="SYS-" + str(number),
                   m_strRemark=REMARK, m_nVolumeTotalOriginal=100000 if number == A else 12672)
        bridge.publish_callback_event("trader:on_stock_order", row)
    events = [json.loads(item[1])["data"] for item in bridge.tx.pushes if item[0] == "event"]
    assert [XtOrder.from_any(row).order_id for row in events] == [A, B]
    assert len({row["cfquant_child_id"] for row in events}) == 2


def test_batch_submission_exposes_tracking_before_and_after_child_id(connected):
    result = connected.api.order_stock_batch(connected.account, [order(), order()])
    rows = result["results"]
    assert len({row["cfquant_submission_id"] for row in rows}) == 2
    for row in rows:
        assert row["cfquant_child_id"] == row["cfquant_submission_id"] + ":" + str(row["order_id"])
