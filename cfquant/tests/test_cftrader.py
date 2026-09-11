"""Batch-order SDK tests. All RPC requests and native orders are local fakes."""

import copy
import ast
from functools import lru_cache
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfquant import cftrader, xtconstant
from cfquant.client import CfquantTimeout
from cfquant.pipe_bridge import PipeTradeBridge, PipeNormalQmtBridge
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.protocol import decode_value, loads_message, pack_request, pack_response
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount, XtOrderResponse


def order(**changes):
    row = dict(stock_code="600000.SH", order_type=xtconstant.STOCK_BUY, order_volume=100,
               price_type=xtconstant.FIX_PRICE, price=10.5)
    row.update(changes)
    return row


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))


@lru_cache(None)
def lite_bridge(path):
    source = path.read_text(encoding='gbk')
    shared = source.split('# BEGIN GENERATED CFTRADER BATCH\n', 1)[1].split('# END GENERATED CFTRADER BATCH', 1)[0]
    assert shared.strip() == (ROOT / 'cfquant/batch_orders.py').read_text(encoding='ascii').strip()
    ast.parse(source, feature_version=(3, 6))
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'TxTradeBridge')
    cls.bases = [ast.Name(id='BaseTradeBridge', ctx=ast.Load())]
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in (
        '_dispatch', '_order_stock', '_order_stock_async', '_async_order_record',
        '_register_pending_async_order', '_send_async_order_response',
        '_find_order_id', '_get_last_order_id', '_order_id_from_detail',
    )]
    namespace = dict(BaseTradeBridge=TxTradeBridge)
    exec(compile(shared, str(path), 'exec'), namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec'), namespace)
    return namespace['TxTradeBridge']


@pytest.fixture(params=[TxTradeBridge, PipeTradeBridge, NormalQmtBridge, PipeNormalQmtBridge] + LITE_PATHS,
                ids=['lttx', 'ctypes', 'normal', 'pipe-normal'] + [path.stem for path in LITE_PATHS])
def connected(request, monkeypatch):
    account = StockAccount("TEST_ONLY", "STOCK")
    account.bridge_id = "test_only"
    native_calls, cancel_calls, requests, responses, cancel_responses, orders, errors = [], [], [], [], [], [], []
    outcomes = []
    def passorder(*args):
        native_calls.append(args)
        result = outcomes.pop(0) if outcomes else 1000 + len(native_calls)
        if isinstance(result, Exception):
            raise result
        return result
    def cancel(*args):
        cancel_calls.append(args)
        result = outcomes.pop(0) if outcomes else True
        if isinstance(result, Exception):
            raise result
        return result
    cls = lite_bridge(request.param) if isinstance(request.param, Path) else request.param
    bridge = cls(None, show=False, globals_dict={"passorder": passorder, "cancel": cancel})
    bridge.order_meta_enabled = False
    callback = XtQuantTraderCallback()
    callback.on_order_stock_async_response = responses.append
    callback.on_cancel_order_stock_async_response = cancel_responses.append
    callback.on_stock_order = orders.append
    callback.on_order_error = errors.append
    trader = XtQuantTrader(callback=callback, account=account)
    class Client:
        def __init__(self):
            self.handlers = {}
        def add_callback(self, event, handler):
            self.handlers[event] = handler
        def request(self, action, params, timeout=None):
            requests.append((action, copy.deepcopy(params)))
            message = loads_message(pack_request(action, params, client_id=trader.client_id))
            result = bridge._dispatch(action, message['params'], message)
            return decode_value(loads_message(pack_response(message['id'], result=result))['result'])
        def close(self):
            pass
    client = Client()
    monkeypatch.setattr(trader, "_get_client", lambda bridge_id=None: client)
    bridge._send_trader_event = lambda client_id, name, data: client.handlers["trader:" + name](data)
    yield SimpleNamespace(api=cftrader.CfQuantTrader(trader), trader=trader, client=client, account=account,
                          bridge=bridge, native_calls=native_calls, requests=requests, outcomes=outcomes,
                          cancel_calls=cancel_calls, responses=responses, cancel_responses=cancel_responses,
                          orders=orders, errors=errors)
    bridge.close()
    trader.stop()


def test_single_order_signatures_and_results_match_xttrader(connected):
    env = connected
    for name in ("order_stock", "order_stock_async"):
        assert inspect.signature(getattr(cftrader.CfQuantTrader, name)) == inspect.signature(getattr(XtQuantTrader, name))
    assert env.api.order_stock(env.account, **order()) == 1001
    seq = env.api.order_stock_async(env.account, **order())
    assert env.responses[0].seq == seq
    assert env.responses[0].order_id == 1002
    assert not hasattr(env.api, "register_callback")
    assert not hasattr(env.api, "query_stock_asset")
    assert not hasattr(env.api, "stop")


@pytest.mark.parametrize("internal_id,sysid", [
    (1082130604, 899), (1082130609, 904), (1082130619, 914),
    (1082130624, 919), (1082130629, 924),
])
@pytest.mark.parametrize("native_result", [None, 0])
def test_single_sync_waits_for_internal_id_when_broker_id_arrives_first(
        connected, monkeypatch, internal_id, sysid, native_result):
    env = connected
    env.account.account_type = xtconstant.CREDIT_ACCOUNT
    env.outcomes[:] = [native_result]
    last_ids = iter([str(sysid - 1), str(sysid)])
    monkeypatch.setattr(env.bridge, '_get_last_order_id', lambda *args: int(next(last_ids)))
    snapshots = iter([[], [dict(account_id=env.account.account_id, stock_code='000001.SZ',
                               order_remark='delayed-credit-order', order_id=internal_id,
                               order_sysid=str(sysid))]])
    queries = []

    def query(params, kind):
        queries.append((params, kind))
        return next(snapshots)

    monkeypatch.setattr(env.bridge, '_query_trade_detail', query)
    result = env.trader.order_stock(env.account, **order(stock_code='000001.SZ',
                                    order_type=xtconstant.CREDIT_BUY, order_remark='delayed-credit-order'))
    assert result == internal_id
    assert len(env.native_calls) == 1
    assert len(queries) == 2
    assert env.native_calls[0][0] == 33


@pytest.mark.parametrize('detail_state', ['empty', 'error', 'different_remark', 'different_stock'])
def test_single_sync_never_returns_an_unverified_latest_broker_id(connected, monkeypatch, detail_state):
    env = connected
    env.outcomes[:] = [0]
    monkeypatch.setenv('CFQUANT_ORDER_ID_WAIT_SECONDS', '0')
    last_ids = iter([898, 899])
    monkeypatch.setattr(env.bridge, '_get_last_order_id', lambda *args: next(last_ids))

    def query(params, kind):
        if detail_state == 'error':
            raise RuntimeError('query unavailable')
        if detail_state == 'empty':
            return []
        return [dict(order_id=1082130604, order_sysid='899',
                     order_remark='other' if detail_state == 'different_remark' else 'my-order',
                     stock_code='000001.SZ' if detail_state == 'different_stock' else '600000.SH')]

    monkeypatch.setattr(env.bridge, '_query_trade_detail', query)
    assert env.trader.order_stock(env.account, **order(order_remark='my-order')) == -1
    assert len(env.native_calls) == 1


def test_sync_batch_preserves_order_parameters_input_and_session(connected):
    env = connected
    orders = [order(), order(stock_code="000001.SZ", order_type=xtconstant.STOCK_SELL,
                            strategy_name="per_row", order_remark="per_row_remark")]
    original = copy.deepcopy(orders)
    result = env.api.order_stock_batch(None, orders, strategy_name="batch", order_remark="rebalance")
    assert orders == original
    assert result["ok"] is True
    assert result["total"] == result["submitted"] == result["attempted"] == 2
    assert result["failed"] == result["unknown"] == result["skipped"] == 0
    assert [row["order_id"] for row in result["results"]] == [1001, 1002]
    assert [row["order_remark"] for row in result["results"]] == ["rebalance_1", "per_row_remark"]
    assert env.native_calls[0][2:7] == ("TEST_ONLY", "600000.SH", xtconstant.FIX_PRICE, 10.5, 100)
    assert env.native_calls[1][7] == "per_row"
    assert all(params["account"]["bridge_id"] == "test_only" for _, params in env.requests)
    assert env.responses == []
    assert len(env.requests) == 1
    assert env.requests[0][0] == 'cftrader.order_stock_batch'
    assert len(env.requests[0][1]['orders']) == 2
    assert result['execution'] == 'qmt'
    assert result['qmt_submit_ms'] >= 0


def test_async_batch_uses_original_seq_allocator_and_callback_deduplication(connected):
    env = connected
    first_seq = env.trader.order_stock_async(env.account, **order(order_remark="single"))
    result = env.api.order_stock_batch_async(env.account, [order(), order()])
    assert result["ok"] is True
    seqs = [row["seq"] for row in result["results"]]
    assert first_seq < seqs[0] < seqs[1]
    assert [item.seq for item in env.responses] == [first_seq] + seqs
    assert all(isinstance(item, XtOrderResponse) for item in env.responses)
    assert len({row["order_remark"] for row in result["results"]}) == 2
    assert env.trader._pending_async_orders == []
    env.client.handlers["trader:on_order_stock_async_response"](vars(env.responses[-1]))
    assert len(env.responses) == 3
    env.client.handlers["trader:on_stock_order"]({"account_id": "TEST_ONLY", "order_id": 1003})
    env.client.handlers["trader:on_order_error"]({"account_id": "TEST_ONLY", "error_msg": "fake rejection"})
    assert len(env.orders) == len(env.errors) == 1
    assert len(env.requests) == 2
    assert env.requests[1][0] == 'cftrader.order_stock_batch_async'
    assert env.requests[1][1]['seqs'] == seqs


@pytest.mark.parametrize('asynchronous', [False, True])
def test_cancel_batch_submits_once_and_preserves_zero_success_result(connected, asynchronous):
    env = connected
    method = env.api.cancel_order_stock_batch_async if asynchronous else env.api.cancel_order_stock_batch
    result = method(env.account, [
        dict(order_id=1001, stock_code='600000.SH'),
        dict(order_id='1002', market='SZ'),
    ])
    assert result['operation'] == 'cancel'
    assert result['ok'] is True
    assert result['submitted'] == result['attempted'] == result['total'] == 2
    assert [row['order_id'] for row in result['results']] == ['1001', '1002']
    assert [row['cancel_result'] for row in result['results']] == [0, 0]
    assert len(env.requests) == 1
    assert env.requests[0][0] == 'cftrader.cancel_order_stock_batch' + ('_async' if asynchronous else '')
    assert [call[0] for call in env.cancel_calls] == ['1001', '1002']
    assert env.native_calls == []
    if asynchronous:
        assert [row['seq'] for row in result['results']] == env.requests[0][1]['seqs']
        assert [item.seq for item in env.cancel_responses] == env.requests[0][1]['seqs']
    else:
        assert env.cancel_responses == []


@pytest.mark.parametrize("stop_on_error,expected", [(False, ["failed", "submitted"]),
                                                   (True, ["failed", "skipped"])])
def test_cancel_batch_rejections_and_stop_on_error(connected, stop_on_error, expected):
    env = connected
    env.outcomes[:] = [False, True]
    result = env.api.cancel_order_stock_batch(env.account, ['1001', '1002'], stop_on_error=stop_on_error)
    assert [row['status'] for row in result['results']] == expected
    assert result['failed'] == 1
    assert len(env.cancel_calls) == (1 if stop_on_error else 2)


@pytest.mark.parametrize("bad", [[], [{}], [dict(order_id='')], [dict(order_id='1001', market='HK')],
                                [dict(order_id='1001', unexpected=True)], ['1001', '1001'],
                                [dict(order_id='1001', market='SZ'), dict(order_id='1001', market='SZ')]])
def test_invalid_cancel_batch_is_rejected_before_qmt(connected, bad):
    env = connected
    with pytest.raises(ValueError):
        env.api.cancel_order_stock_batch(env.account, bad)
    assert env.requests == []
    assert env.cancel_calls == []


@pytest.mark.parametrize('asynchronous', [False, True])
def test_cancel_batch_lost_response_never_replays(connected, monkeypatch, asynchronous):
    env = connected
    original = env.client.request
    def lose_response(*args, **kwargs):
        original(*args, **kwargs)
        raise CfquantTimeout('cancel response was lost after QMT submitted requests')
    monkeypatch.setattr(env.client, 'request', lose_response)
    method = env.api.cancel_order_stock_batch_async if asynchronous else env.api.cancel_order_stock_batch
    result = method(env.account, ['1001', '1002'])
    assert result['operation'] == 'cancel'
    assert result['unknown'] == 2
    assert len(env.requests) == 1
    assert len(env.cancel_calls) == 2
    assert 'cancel response was lost' in result['request_error']


@pytest.mark.parametrize("stop_on_error,expected", [(False, ["submitted", "failed", "submitted"]),
                                                   (True, ["submitted", "failed", "skipped"])])
def test_async_batch_rejections_and_stop_on_error(connected, stop_on_error, expected):
    env = connected
    env.outcomes[:] = [1001, -1, 1003]
    result = env.api.order_stock_batch_async(env.account, [order(), order(), order()], stop_on_error=stop_on_error)
    assert [row["status"] for row in result["results"]] == expected
    assert result["failed"] == 1
    assert len(env.native_calls) == (2 if stop_on_error else 3)
    assert env.trader._pending_async_orders == []


@pytest.mark.parametrize("asynchronous", [False, True])
def test_timeout_preserves_partial_results_and_never_submits_remaining_orders(connected, asynchronous):
    env = connected
    env.outcomes[:] = [1001, CfquantTimeout("fake lost response"), 1003]
    method = env.api.order_stock_batch_async if asynchronous else env.api.order_stock_batch
    result = method(env.account, [order(), order(), order()])
    assert result["submitted"] == result["unknown"] == result["skipped"] == 1
    assert result["attempted"] == 2
    assert [row["status"] for row in result["results"]] == ["submitted", "unknown", "skipped"]
    assert result["results"][1]["error"] == "fake lost response"
    assert len(env.native_calls) == 2


def test_sync_missing_id_does_not_delay_remaining_native_submissions(connected, monkeypatch):
    env = connected
    env.outcomes[:] = [None]
    monkeypatch.setattr(env.bridge, "_find_order_id", lambda *args: None)
    result = env.api.order_stock_batch(env.account, [order(), order()])
    assert result["unknown"] == result["submitted"] == 1
    assert result['skipped'] == 0
    assert result["results"][0]["order_id"] == -1
    assert len(env.native_calls) == 2


@pytest.mark.parametrize("bad", [None, {}, {"price": float("nan")}, {"price": float("inf")},
                                {"order_volume": 0}, {"order_volume": 10.5}, {"order_type": True},
                                {"stock_code": ""}, {"account": "ANOTHER_ACCOUNT"}, {"order_volum": 100}])
def test_entire_batch_is_validated_before_any_order_is_sent(connected, bad):
    env = connected
    invalid = bad if bad in (None, {}) else order(**bad)
    with pytest.raises(ValueError):
        env.api.order_stock_batch(env.account, [order(), invalid])
    assert env.native_calls == env.requests == []


def test_credit_and_futures_use_original_order_constants_and_code_case(connected):
    env = connected
    credit = dict(account_id="TEST_ONLY", account_type="CREDIT", bridge_id="test_credit")
    result = env.api.order_stock_batch(credit, [order(order_type=xtconstant.CREDIT_FIN_BUY)])
    assert result["submitted"] == 1
    assert env.native_calls[0][0] == 27
    future = dict(account_id="TEST_ONLY", account_type="FUTURE", bridge_id="test_future")
    result = env.api.order_stock_batch(future, [order(stock_code="rb2610.SF", order_type=xtconstant.FUTURE_OPEN_LONG, order_volume=1)])
    assert result["submitted"] == 1
    assert env.native_calls[-1][3] == "rb2610.SF"


def test_duplicate_correlation_and_invalid_options_send_nothing(connected):
    env = connected
    with pytest.raises(ValueError, match="distinct remarks"):
        env.api.order_stock_batch_async(env.account, [order(order_remark="same"), order(order_remark="same")])
    with pytest.raises(ValueError, match="boolean"):
        env.api.order_stock_batch(env.account, [order()], stop_on_error="false")
    with pytest.raises(ValueError, match="non-empty"):
        env.api.order_stock_batch(env.account, [])
    assert env.requests == []


def test_facade_requires_an_existing_trader_without_opening_a_session():
    with pytest.raises(TypeError, match="XtQuantTrader"):
        cftrader.CfQuantTrader("D:/QMT")


@pytest.mark.parametrize('asynchronous', [False, True])
def test_batch_never_loops_over_sdk_single_order_requests(connected, monkeypatch, asynchronous):
    env = connected
    def forbidden(*args, **kwargs):
        raise AssertionError('batch must not call SDK singles or per-order ID lookup')
    monkeypatch.setattr(env.trader, 'order_stock', forbidden)
    monkeypatch.setattr(env.trader, 'order_stock_async', forbidden)
    monkeypatch.setattr(env.bridge, '_find_order_id', forbidden)
    monkeypatch.setattr(env.bridge, '_get_last_order_id', forbidden)
    method = env.api.order_stock_batch_async if asynchronous else env.api.order_stock_batch
    result = method(env.account, [order() for _ in range(100)])
    assert result['submitted'] == 100
    assert len(env.requests) == 1
    assert len(env.native_calls) == 100


def test_sync_resolves_all_ids_after_submission_with_shared_queries(connected, monkeypatch):
    env = connected
    env.outcomes[:] = [None, None, None]
    queried_after = []
    previous = dict(stock_code='600000', order_remark='first', order_id=5000)
    def query(params, kind):
        assert kind == 'order'
        queried_after.append(len(env.native_calls))
        if not env.native_calls:
            return [previous]
        assert len(env.native_calls) == 3
        rows = env.requests[0][1]['orders']
        return [previous] + [dict(stock_code=row['stock_code'].split('.')[0],
                                 order_remark=row['order_remark'], order_id=6000 + index)
                             for index, row in reversed(list(enumerate(rows)))]
    monkeypatch.setattr(env.bridge, '_query_trade_detail', query)
    result = env.api.order_stock_batch(env.account, [order(order_remark='first'), order(), order()])
    assert [row['order_id'] for row in result['results']] == [6000, 6001, 6002]
    assert queried_after == [0, 3]
    assert result['submitted'] == 3
    assert len(env.requests) == 1


def test_sync_does_not_bind_ambiguous_order_ids(connected, monkeypatch):
    env = connected
    env.outcomes[:] = [None]
    monkeypatch.setenv('CFQUANT_ORDER_ID_WAIT_SECONDS', '0')
    def query(params, kind):
        return [dict(stock_code='600000', order_remark='ambiguous', order_id=order_id)
                for order_id in (6000, 6001)] if env.native_calls else []
    monkeypatch.setattr(env.bridge, '_query_trade_detail', query)
    result = env.api.order_stock_batch(env.account, [order(order_remark='ambiguous')])
    assert result['unknown'] == 1
    assert result['results'][0]['order_id'] == -1


@pytest.mark.parametrize('asynchronous', [False, True])
def test_lost_batch_response_never_replays_and_late_callbacks_still_work(connected, monkeypatch, asynchronous):
    env = connected
    env.outcomes[:] = [None, None, None] if asynchronous else [1001, 1002, 1003]
    original = env.client.request
    def lose_response(*args, **kwargs):
        original(*args, **kwargs)
        raise CfquantTimeout('response was lost after QMT submitted all orders')
    monkeypatch.setattr(env.client, 'request', lose_response)
    method = env.api.order_stock_batch_async if asynchronous else env.api.order_stock_batch
    result = method(env.account, [order(), order(), order()])
    assert result['unknown'] == 3
    assert result['skipped'] == result['submitted'] == 0
    assert len(env.requests) == 1
    assert len(env.native_calls) == 3
    assert 'response was lost' in result['request_error']
    if asynchronous:
        assert len(env.trader._pending_async_orders) == 3
        for index, row in enumerate(result['results']):
            env.bridge._handle_async_order_callback(dict(account_id='TEST_ONLY', stock_code=row['stock_code'],
                                                         order_remark=row['order_remark'], order_id=7000 + index))
        assert [response.seq for response in env.responses] == [row['seq'] for row in result['results']]
        assert env.trader._pending_async_orders == []


@pytest.mark.parametrize('stop_on_error', [False, True])
def test_sync_native_rejection_is_explicit_and_honors_stop(connected, stop_on_error):
    env = connected
    env.outcomes[:] = [-1, 1002]
    result = env.api.order_stock_batch(env.account, [order(), order()], stop_on_error=stop_on_error)
    assert result['failed'] == 1
    assert result['submitted'] == (0 if stop_on_error else 1)
    assert result['skipped'] == (1 if stop_on_error else 0)
    assert len(env.requests) == 1


def test_qmt_revalidates_whole_wire_batch_before_native_submission(connected):
    env = connected
    params = dict(account=dict(account_id='TEST_ONLY', account_type='STOCK'), batch_id='wire-test',
                  orders=[order(), order(order_volume=0)])
    with pytest.raises(ValueError, match='positive'):
        env.bridge._dispatch('cftrader.order_stock_batch', params, {})
    params['orders'][1] = order()
    params['seqs'] = [1, 1]
    with pytest.raises(ValueError, match='seqs'):
        env.bridge._dispatch('cftrader.order_stock_batch_async', params, {})
    assert env.native_calls == []


def test_unsupported_bridge_does_not_fall_back_to_single_orders(connected, monkeypatch):
    env = connected
    def old_bridge(action, params, msg):
        raise ValueError('unsupported action: ' + action)
    monkeypatch.setattr(env.bridge, '_dispatch', old_bridge)
    result = env.api.order_stock_batch(env.account, [order(), order()])
    assert result['unknown'] == 2
    assert 'unsupported action' in result['request_error']
    assert len(env.requests) == 1
    assert env.native_calls == []


@pytest.mark.parametrize('field,value', [('seq', 999999), ('ok', False), ('order_remark', 'another-row')])
def test_inconsistent_batch_response_is_unknown_without_replaying(connected, monkeypatch, field, value):
    env = connected
    original = env.client.request
    def corrupted(*args, **kwargs):
        response = original(*args, **kwargs)
        response['results'][0][field] = value
        return response
    monkeypatch.setattr(env.client, 'request', corrupted)
    result = env.api.order_stock_batch_async(env.account, [order(), order()])
    assert result['unknown'] == 2
    assert len(env.native_calls) == 2
    assert len(env.requests) == 1
