"""Stock Connect contract tests; QMT/RPC/terminals are exclusively local fakes."""
import ast
from types import SimpleNamespace
from xml.dom import minidom

import pytest

import cfquant_web_server as web
from cfquant import account_routing, order_meta
from cfquant.stock_connect import connect_account_type
from cfquant.qmt_bridge import CfquantQmtBridge
from cfquant.qmt_strategy_deploy import _account_binding, _resolve_account_binding
from cfquant.xttype import StockAccount, XtOrder, XtPosition
from cfquant.tests.test_cftrader import connected, order, LITE_PATHS
from cfquant.tests.test_cftrader_web import routing, payload
from cfquant.tests.test_qmt_strategy_web import web_config


CASES = [('HUGANGTONG', 'HGT', 7), ('SHENGANGTONG', 'SGT', 11)]


@pytest.mark.parametrize('kind,market,number', CASES)
def test_account_identity_and_callbacks(kind, market, number):
    account = StockAccount('TEST_ONLY', kind)
    assert account.account_type == number
    for alias in (kind, number, str(number), kind + '_ACCOUNT', market):
        assert connect_account_type(alias) == kind
        assert web.normalize_account_type(alias) == kind
        assert account_routing._account_type(alias) == kind
        assert order_meta.normalize_account_type(alias) == kind
    for cls in (XtOrder, XtPosition):
        result = cls.from_any(dict(m_strAccountID='TEST_ONLY', m_nBrokerType=number,
                                   m_strInstrumentID='00700', m_strExchangeID=market))
        assert result.stock_code == '00700.' + market
        assert result.account_type == number


@pytest.mark.parametrize('kind,market,number', CASES)
@pytest.mark.parametrize('batch', [False, True])
@pytest.mark.parametrize('asynchronous', [False, True])
def test_sdk_to_qmt_order_and_cancel(connected, kind, market, number, batch, asynchronous):
    env = connected
    env.account.account_type = number
    code = '00700.' + market
    if batch:
        fn = env.api.order_stock_batch_async if asynchronous else env.api.order_stock_batch
        result = fn(env.account, [order(stock_code=code), order(stock_code='00941.' + market, order_type=24)])
        assert result['submitted'] == 2
    else:
        fn = env.trader.order_stock_async if asynchronous else env.trader.order_stock
        assert fn(env.account, code, 23, 100, 11, 350.0, 'connect', 'test') > 0
    assert env.native_calls[0][:4] == (23, 1101, 'TEST_ONLY', code)
    assert env.requests[0][1]['account']['account_type'] == number
    if asynchronous:
        remark = env.native_calls[0][9]
        env.bridge._handle_async_order_callback(dict(account_id='TEST_ONLY', account_type=kind,
                                                     stock_code=code, order_remark=remark, order_id=2001))
        assert env.responses[0].account_type == number
        assert env.responses[0].order_id == 2001
    if asynchronous:
        assert env.trader.cancel_order_stock_async(env.account, '2001') > 0
        assert env.cancel_responses[-1].account_type == number
        assert env.cancel_responses[-1].cancel_result == 0
    else:
        assert env.trader.cancel_order_stock(env.account, '2001') == 0
    assert env.cancel_calls[-1][:3] == ('2001', 'TEST_ONLY', kind)
    cancel_batch = env.api.cancel_order_stock_batch_async if asynchronous else env.api.cancel_order_stock_batch
    result = cancel_batch(env.account, [dict(order_id='2002', stock_code=code)])
    assert result['submitted'] == 1
    assert result['results'][0]['market'] == market
    assert env.cancel_calls[-1][2] == kind


@pytest.mark.parametrize('kind,market,number', CASES)
def test_queries_and_normal_callback_type(connected, kind, market, number):
    env = connected
    env.account.account_type = number
    calls = []
    def detail(account_id, account_type, datatype, *args):
        calls.append((account_id, account_type, datatype))
        return [SimpleNamespace(m_strAccountID=account_id, m_nBrokerType=number,
                                m_strInstrumentID='00700', m_strExchangeID=market,
                                m_nVolume=100, m_dAvailable=1000)]
    env.bridge.globals_dict['get_trade_detail_data'] = detail
    assert env.trader.query_stock_asset(env.account).account_type == number
    assert env.trader.query_stock_positions(env.account)[0].stock_code == '00700.' + market
    assert env.trader.query_stock_orders(env.account)[0].account_type == number
    assert env.trader.query_stock_trades(env.account)[0].account_type == number
    assert all(call[1].upper() == kind for call in calls)
    from cfquant.normal_bridge import NormalQmtBridge
    assert NormalQmtBridge._callback_account_type(env.bridge, None, {'m_nBrokerType': number}) == kind


@pytest.mark.parametrize('kind,market,number', CASES)
def test_reference_exchange_rate_is_native_and_account_scoped(connected, kind, market, number):
    env = connected
    env.account.account_type = number
    calls = []
    rates = dict(bidReferenceRate=0.91, askReferenceRate=0.93, dayBuyRiseRate=0.03, daySaleRiseRate=0.03)
    env.bridge.globals_dict['get_hkt_exchange_rate'] = lambda *args: calls.append(args) or rates
    assert env.trader.get_hkt_exchange_rate(env.account) == rates
    assert calls == [('TEST_ONLY', kind)]
    del env.bridge.globals_dict['get_hkt_exchange_rate']
    with pytest.raises(NotImplementedError, match='get_hkt_exchange_rate'):
        env.trader.get_hkt_exchange_rate(env.account)
    with pytest.raises(ValueError):
        env.trader.get_hkt_exchange_rate(StockAccount('TEST_ONLY', 'STOCK'))


@pytest.mark.parametrize('kind,market,number', CASES)
def test_quotes_calendar_and_eligibility_are_forwarded(connected, kind, market, number):
    env = connected
    code = '00700.' + market
    calls = []
    env.bridge.context = SimpleNamespace(get_full_tick=lambda codes: calls.append(codes) or {code: {'lastPrice': 350}})
    env.bridge.globals_dict['get_instrument_detail'] = lambda symbol, *args: {'InstrumentID': symbol, 'HSGTFlag': 5}
    env.bridge.globals_dict['get_trading_dates'] = lambda symbol, *args: calls.append(symbol) or [1700000000000]
    assert env.bridge._dispatch('xtdata.get_full_tick', {'code_list': [code]}, {})[code]['lastPrice'] == 350
    assert env.bridge._dispatch('xtdata.get_instrument_detail', {'stock_code': code}, {})['HSGTFlag'] == 5
    assert env.bridge._dispatch('xtdata.get_trading_dates', {'stockcode': code}, {}) == [1700000000000]
    assert calls == [[code], code]


def test_account_subscriptions_do_not_cross_connect_channels():
    for kind, _, number in CASES:
        account_routing.subscribe('connect-test', 'SAME_FUND', kind, account_type=number)
    try:
        assert account_routing.client_ids('connect-test', 'SAME_FUND', account_type='7') == ['HUGANGTONG']
        assert account_routing.client_ids('connect-test', 'SAME_FUND', account_type=11) == ['SHENGANGTONG']
    finally:
        for kind, _, number in CASES:
            account_routing.unsubscribe('connect-test', 'SAME_FUND', kind, account_type=number)


@pytest.mark.parametrize('account_type,code', [
    ('HUGANGTONG', '00700.SGT'), ('SHENGANGTONG', '00700.HGT'),
    ('STOCK', '00700.HGT'), ('CREDIT', '00700.SGT'),
    ('HUGANGTONG', '00700.HK'), ('HUGANGTONG', '00700'),
])
def test_mismatched_account_never_submits(connected, account_type, code):
    env = connected
    account = StockAccount('TEST_ONLY', account_type)
    with pytest.raises(ValueError):
        env.trader.order_stock(account, code, 23, 100, 11, 350.0)
    assert not env.native_calls


def test_batch_preflights_every_connect_row(connected):
    env = connected
    env.account.account_type = 7
    from cfquant.batch_orders import prepare_batch_orders
    rows = prepare_batch_orders([order(stock_code='00700.HGT'), order(stock_code='00700.SGT')], 'test')
    with pytest.raises(ValueError):
        env.bridge._dispatch('cftrader.order_stock_batch',
                             dict(account=dict(account_id='TEST_ONLY', account_type=7), orders=rows, batch_id='test'), {})
    assert not env.native_calls
    with pytest.raises(ValueError):
        env.bridge._cancel_order_stock(dict(account=dict(account_id='TEST_ONLY', account_type=7),
                                            order_id='2001', market='SGT'))
    assert not env.cancel_calls


@pytest.mark.parametrize('code,expected', [('700.HGT', '00700.HGT'), ('941.sgt', '00941.SGT'),
                                         ('00700.HK', '00700.HK'), ('600000.SH', '600000.SH')])
def test_web_preserves_five_digit_codes(code, expected):
    assert web.normalize_stock_code(code) == expected


@pytest.mark.parametrize('code', ['000700.HGT', '0.SGT', 'ABC.HGT', '123456.HK'])
def test_malformed_connect_code(code):
    with pytest.raises(ValueError):
        web.normalize_stock_code(code)


@pytest.mark.parametrize('kind,market,number', CASES)
def test_web_forwards_account_without_a_share_route(routing, kind, market, number):
    _, calls = routing
    params = payload(codes=['00700.' + market])
    params['account']['account_type'] = kind
    web.account_cftrader_batch_request('TEST_ONLY', 'connect_bridge', None,
                                     'cftrader.order_stock_batch', params, account_type=kind)
    assert calls[0][0] == 'connect_bridge'
    assert calls[0][3]['account']['account_type'] == kind
    assert calls[0][3]['orders'][0]['stock_code'] == '00700.' + market


def test_same_fund_account_has_separate_bindings(web_config):
    _, config = web_config
    rows = [config.save_account_config('TEST_ONLY', account_type=kind, bridge_id='test',
                                       qmt_strategy={'enabled': False}) for kind, _, _ in CASES]
    assert rows[0]['account_key'] != rows[1]['account_key']
    assert len(config.account_configs()) == 2


def test_strategy_selects_matching_native_account_key():
    doc = minidom.parseString('<root>' + ''.join(
        '<item account="1001" accountType="%s" m_strAccountKey="%s____101____201____49____1001____"/>' % (n, n)
        for n in (2, 7, 11)) + '</root>')
    for kind, _, number in CASES:
        assert _account_binding(doc, '1001', kind)[0] == str(number)
        with pytest.raises(ValueError):
            _account_binding(doc, '1001', kind, '2____101____201____49____1001____')


def test_a_share_strategy_does_not_hide_connect_authorization(tmp_path):
    doc = minidom.parseString('<root><item account="1001" accountType="2" '
                             'm_strAccountKey="2____101____201____49____1001____"/></root>')
    path = tmp_path / 'userdata/users/test/authAndConfig.xml'
    path.parent.mkdir(parents=True)
    key = '7____101____201____49____1001____'
    path.write_text('<TTAuthAndConfigFile><AccountAuth key="%s"/></TTAuthAndConfigFile>' % key, encoding='utf-8')
    assert _resolve_account_binding(tmp_path, doc, '1001', 'HUGANGTONG') == ('7', key)


def test_old_qmt_bridge_uses_documented_contract():
    calls = []
    bridge = CfquantQmtBridge.__new__(CfquantQmtBridge)
    bridge.context = SimpleNamespace(passorder=lambda *args: calls.append(args) or 2001)
    bridge.globals_dict = {}
    bridge._get_last_order_id = lambda *args: None
    bridge._remember_order_request = lambda *args: None
    bridge._get_global_func = lambda name: None
    params = dict(order(stock_code='00700.HGT'), account=dict(account_id='TEST_ONLY', account_type='7'))
    bridge._order_stock(params, resolve_order_id=False)
    assert calls[0][:4] == (23, 1101, 'TEST_ONLY', '00700.HGT')
    assert bridge._stock_order_type(dict(m_strExchangeID='HGT', m_nOffsetFlag=48)) == 23


@pytest.mark.parametrize('path', LITE_PATHS)
def test_standalone_connect_helpers_and_methods(path):
    from tools.sync_qmt_batch import updated_source
    source = path.read_text(encoding='gbk')
    assert source == updated_source(source)
    tree = ast.parse(source, feature_version=(3, 6))
    shared = source.split('# BEGIN GENERATED CFTRADER BATCH\n')[1].split('# END GENERATED CFTRADER BATCH')[0]
    namespace = {}
    exec(shared, namespace)
    assert namespace['validate_connect_order']({'stock_code': '00700.SGT'}, 11) == '00700.SGT'
    # Exercise the actual standalone callback and account normalization bodies.
    for cls_name, method in [('TxTradeBridge', '_account_type_name'), ('NormalQmtBridge', '_callback_account_type')]:
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
        cls.bases = []
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec'), namespace)
        instance = namespace[cls_name]()
        instance._get_value = lambda *args: None
        if method == '_account_type_name':
            assert instance._account_type_name('11') == 'SHENGANGTONG'
        else:
            assert instance._callback_account_type(None, {'m_nBrokerType': 7}) == 'HUGANGTONG'
