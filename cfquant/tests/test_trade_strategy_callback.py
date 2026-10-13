"""Offline callback regressions; no QMT connection or real orders."""

import ast
import json
from pathlib import Path
import threading
import time

import pytest

from cfquant.normal_bridge import NormalQmtBridge
from cfquant.order_identity import prepare_order_remark
from cfquant.pipe_bridge import PipeNormalQmtBridge
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import XtTrade, normalize_order_price_type


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))


class RecordingTx:
    def __init__(self):
        self.pushes = []
        self.store = {}

    def push(self, *args):
        self.pushes.append(args)

    def get(self, key):
        return self.store.get(key)

    def dict_change(self, key, name, value):
        self.store.setdefault(key, {})[name] = value

    def put(self, key, value):
        self.store[key] = value


def lite_bridge(path):
    # Run the actual embedded cache, initializer and callback methods. Importing
    # the entry module itself would start a live transport at module scope.
    source = path.read_text(encoding='gbk')
    tree = ast.parse(source, feature_version=(3, 6))
    namespace = dict(json=json, time=time, threading=threading,
                     normalize_order_price_type=normalize_order_price_type, QMT_MARKET='SZ')
    shared = source.split('# BEGIN GENERATED CFTRADER BATCH\n', 1)[1].split('# END GENERATED CFTRADER BATCH', 1)[0]
    exec(compile(shared, str(path), 'exec'), namespace)
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_truthy_param']
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(path), 'exec'), namespace)
    methods = {'__init__', '_remember_order_request', '_enrich_order_request_fields',
               '_remember_order_callback_fields', '_format_trade_detail', '_query_trade_detail',
               '_trade_detail_query_account_id', '_filter_trade_detail_market',
               '_active_market_route', '_market_suffix', '_formatted_trade_detail_market', '_stock_code_market'}
    nodes = []
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        selected = methods if cls.name == 'TxTradeBridge' else (
            {'publish_callback_event'} if cls.name == 'NormalQmtBridge' else set())
        nodes.extend(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in selected)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    overrides = {node.name: namespace[node.name] for node in nodes if node.name != '__init__'}
    cls = type('StandaloneBridge', (NormalQmtBridge,), overrides)
    bridge = cls(None, show=False, schedule_timer=False, order_meta_enabled=False)
    namespace['__init__'](bridge, None, show=False)
    return bridge


@pytest.fixture(params=['pipe', 'lttx'] + LITE_PATHS, ids=lambda value: value.stem if isinstance(value, Path) else value)
def bridge(request):
    if isinstance(request.param, Path):
        instance = lite_bridge(request.param)
    elif request.param == 'pipe':
        instance = PipeNormalQmtBridge(None, show=False, schedule_timer=False)
    else:
        instance = NormalQmtBridge(None, show=False, schedule_timer=False)
    instance.tx = RecordingTx()
    yield instance
    instance.close()


def raw(**changes):
    result = dict(m_strAccountID='TEST_ONLY', m_nAccountType=2, m_strInstrumentID='000001',
                  m_strExchangeID='SZ', m_nRef=700009, m_strOrderSysID='635082868',
                  m_strStrategyName='', m_strRemark='')
    result.update(changes)
    return result


def publish(bridge, kind, data):
    bridge.publish_callback_event('trader:on_stock_' + kind, data)
    return json.loads([p[1] for p in bridge.tx.pushes if p[0] == 'event'][-1])['data']


def submitted(bridge, order_id=700009, strategy='strategy-a'):
    internal = prepare_order_remark(dict(order_remark='remark'))
    bridge._remember_order_request('TEST_ONLY', '000001.SZ', internal, strategy, order_id=order_id)
    return internal


@pytest.mark.parametrize('event', [
    'on_stock_order', 'on_stock_trade', 'on_order_error', 'on_cancel_error',
    'on_order_stock_async_response', 'on_cancel_order_stock_async_response',
])
@pytest.mark.parametrize('strategy', ['', 'alpha_beta_v2', '\u7b56\u7565_\u4e00', 'alpha&&&beta'])
def test_public_callback_removes_internal_strategy_without_request_cache(bridge, event, strategy):
    internal = bridge._register_order_error_context('TEST_ONLY', '000001.SZ', strategy, 'remark')
    bridge.order_error_contexts.clear()
    bridge.publish_callback_event('trader:' + event, raw(
        strategy_name=internal, m_strStrategyName=internal, strategyName=internal,
        error_msg='rejected', _cfquant_force_order_error=True))
    data = json.loads([p[1] for p in bridge.tx.pushes if p[0] == 'event'][-1])['data']
    assert data['strategy_name'] == data['m_strStrategyName'] == strategy
    if 'strategyName' in data:
        assert data['strategyName'] == strategy


@pytest.mark.parametrize('event', [
    'on_stock_order', 'on_stock_trade', 'on_order_error', 'on_cancel_error',
    'on_order_stock_async_response', 'on_cancel_order_stock_async_response',
])
@pytest.mark.parametrize('strategy,tagged', [
    ('', True), ('alpha_beta_v2', True), ('\u7b56\u7565_\u4e00', True),
    ('alpha_beta_v2', False), ('alpha&&&beta', False), ('cfq_manual', False),
    ('alpha&&&_cfq_not-a-token', False),
])
def test_sdk_user_callback_restores_strategy_from_older_bridge(event, strategy, tagged):
    internal = strategy
    if tagged:
        internal = (strategy + '&&&_cfq_' if strategy else 'cfq_') + '0123456789ab'
    received = []
    callback = XtQuantTraderCallback()
    setattr(callback, event, received.append)
    trader = XtQuantTrader(callback=callback)
    try:
        trader._make_trader_handler(event)(dict(
            account_id='TEST_ONLY', order_id=700009, seq=1,
            strategy_name=internal, m_strStrategyName=internal,
            mstrStrategyName=internal, strategyName=internal))
        assert len(received) == 1
        for field in ('strategy_name', 'm_strStrategyName', 'mstrStrategyName', 'strategyName'):
            assert getattr(received[0], field) == strategy
    finally:
        trader.stop()


@pytest.mark.parametrize('bridge_class', [NormalQmtBridge, PipeNormalQmtBridge])
def test_strategy_is_restored_after_exact_error_context_matching(bridge_class):
    bridge = bridge_class(None, show=False, schedule_timer=False)
    bridge.order_meta_enabled = False
    bridge.tx = RecordingTx()
    try:
        tokens = [bridge._register_order_error_context('TEST_ONLY', '000001.SZ', 'alpha_beta', remark)
                  for remark in ('first', 'second')]
        for token, remark in zip(reversed(tokens), ('second', 'first')):
            bridge.publish_callback_event('trader:on_order_error', dict(
                accountID='TEST_ONLY', orderCode='SZ000001', strategyName=token,
                error_msg='rejected', _cfquant_force_order_error=True))
            data = json.loads([p[1] for p in bridge.tx.pushes if p[0] == 'event'][-1])['data']
            assert data['strategy_name'] == data['m_strStrategyName'] == data['strategyName'] == 'alpha_beta'
            assert data['order_remark'] == remark
            assert data['cfquant_order_error_context_consumed'] is True
        assert not bridge.order_error_contexts
    finally:
        bridge.close()


def test_trade_with_only_broker_id_restores_metadata_for_each_partial_fill(bridge):
    internal = submitted(bridge)
    order = publish(bridge, 'order', raw(m_strRemark=internal, m_nOrderStatus=50))
    assert order['strategy_name'] == 'strategy-a'
    for trade_id, volume in [('T1', 100), ('T2', 200)]:
        trade = XtTrade.from_any(publish(bridge, 'trade', raw(
            m_nRef=0, m_strTradeID=trade_id, m_nVolume=volume, m_dPrice=10.0)))
        assert trade.strategy_name == 'strategy-a'
        assert trade.m_strStrategyName == 'strategy-a'
        assert trade.order_remark == 'remark'
        assert (trade.traded_id, trade.traded_volume, trade.traded_price) == (trade_id, volume, 10.0)


def test_trade_with_public_remark_and_exact_id_restores_strategy(bridge):
    # No preceding order callback is needed when the submission has the ID.
    submitted(bridge)
    trade = XtTrade.from_any(publish(bridge, 'trade', raw(m_strRemark='remark')))
    assert trade.strategy_name == 'strategy-a'
    assert trade.order_remark == 'remark'


def test_native_order_strategy_is_remembered_without_submission_cache(bridge):
    publish(bridge, 'order', raw(m_strStrategyName='native-strategy', m_nOrderStatus=50))
    trade = XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0)))
    assert trade.strategy_name == 'native-strategy'


def test_order_query_seeds_trade_callback_metadata(bridge):
    bridge.globals_dict['get_trade_detail_data'] = lambda *args: [raw(m_strStrategyName='query-strategy')]
    rows = bridge._query_trade_detail({'account': {'account_id': 'TEST_ONLY', 'account_type': 'STOCK'}}, 'order')
    assert rows[0]['strategy_name'] == 'query-strategy'
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0))).strategy_name == 'query-strategy'


@pytest.mark.parametrize('changes', [
    {'m_strAccountID': 'OTHER'}, {'m_nAccountType': 3},
    {'m_strInstrumentID': '000002'}, {'m_strExchangeID': 'SH'},
    {'m_strOrderSysID': 'unknown'}, {'m_strOrderSysID': '0'},
    {'m_strRemark': 'different'},
    {'m_strRemark': 'remark__cfq_ffffffffffffffffffffffffffffffff'},
])
def test_broker_id_mapping_does_not_cross_scope_or_conflicting_remark(bridge, changes):
    internal = submitted(bridge)
    publish(bridge, 'order', raw(m_strRemark=internal, m_nOrderStatus=50))
    deal = raw(m_nRef=0)
    deal.update(changes)
    assert XtTrade.from_any(publish(bridge, 'trade', deal)).strategy_name == ''


def test_same_public_remark_selects_exact_order_and_rejects_other_uuid(bridge):
    submitted(bridge)
    submitted(bridge, order_id=700010, strategy='strategy-b')
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_strRemark='remark'))).strategy_name == 'strategy-a'
    other = 'remark__cfq_ffffffffffffffffffffffffffffffff'
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_strRemark=other))).strategy_name == ''


def test_ambiguous_broker_id_and_conflicting_local_id_are_not_guessed(bridge):
    publish(bridge, 'order', raw(m_strStrategyName='first', m_nOrderStatus=50))
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=999))).strategy_name == ''
    publish(bridge, 'order', raw(m_nRef=700010, m_strStrategyName='second', m_nOrderStatus=50))
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0))).strategy_name == ''
    assert XtTrade.from_any(publish(bridge, 'trade', raw())).strategy_name == 'first'


def test_trade_native_strategy_is_preserved(bridge):
    publish(bridge, 'order', raw(m_strStrategyName='cached', m_nOrderStatus=50))
    trade = XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0, m_strStrategyName='native')))
    assert trade.strategy_name == trade.m_strStrategyName == 'native'


def test_broker_id_is_not_confused_with_another_local_order_id(bridge):
    publish(bridge, 'order', raw(m_strOrderSysID='700010', m_strStrategyName='first', m_nOrderStatus=50))
    publish(bridge, 'order', raw(m_nRef=700010, m_strOrderSysID='OTHER', m_strStrategyName='second', m_nOrderStatus=50))
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0, m_strOrderSysID='700010'))).strategy_name == 'first'


def test_callback_cache_expiry_and_eviction_do_not_reuse_old_broker_ids(bridge):
    bridge.order_callback_cache.max_orders = 1
    publish(bridge, 'order', raw(m_strStrategyName='old', m_nOrderStatus=50))
    publish(bridge, 'order', raw(m_nRef=700010, m_strOrderSysID='NEW', m_strStrategyName='new', m_nOrderStatus=50))
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0))).strategy_name == ''
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0, m_strOrderSysID='NEW'))).strategy_name == 'new'
    bridge.order_callback_cache.day = '19990101'
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0, m_strOrderSysID='NEW'))).strategy_name == ''


def test_historical_order_cannot_seed_today_callback_cache(bridge):
    publish(bridge, 'order', raw(m_strStrategyName='historical', m_strInsertDate='19990101', m_nOrderStatus=50))
    assert XtTrade.from_any(publish(bridge, 'trade', raw(m_nRef=0))).strategy_name == ''


@pytest.mark.parametrize('via_query', [False, True])
def test_cross_qmt_bound_metadata_accepts_public_remark_only_with_exact_ref(via_query):
    bridge = NormalQmtBridge(None, show=False, schedule_timer=False)
    internal = prepare_order_remark(dict(order_remark='remark'))
    bridge.order_meta_cache.upsert(dict(account_id='TEST_ONLY', account_type='STOCK',
                                      stock_code='000001.SZ', user_order_id=internal,
                                      order_remark='remark', strategy_name='cross-qmt',
                                      order_id=700009, status='bound'))
    resolver = bridge._resolve_direct_query_order_meta if via_query else (
        lambda data, account, kind: bridge.order_meta_cache.resolve_callback(data, account_id=account, account_type=kind))
    for order_id, remark, hit in [(700009, 'remark', True), (700010, 'remark', False),
                                  (700009, 'remark__cfq_ffffffffffffffffffffffffffffffff', False)]:
        record, _ = resolver(dict(account_id='TEST_ONLY', stock_code='000001.SZ',
                                  order_id=order_id, order_remark=remark), 'TEST_ONLY', 'STOCK')
        assert bool(record) is hit
