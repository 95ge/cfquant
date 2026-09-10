"""Local fakes only: batch routing, native execution and transport failures."""

from types import SimpleNamespace

import pytest

import cfquant_web_server as web
from cfquant.batch_orders import batch_result, batch_result_rows, prepare_batch_orders
from cfquant.cftrader import CfQuantTrader
from cfquant.client import CfquantError, CfquantTimeout
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader


def order(code='600000.SH'):
    return dict(stock_code=code, order_type=23, order_volume=100, price_type=11, price=10.0)


def payload(asynchronous=False, codes=('600000.SH', '000001.SZ')):
    return dict(account=dict(account_id='TEST_ONLY', account_type='STOCK'), batch_id='route-test',
                orders=prepare_batch_orders([order(code) for code in codes], 'route-test'),
                seqs=list(range(10, 10 + len(codes))) if asynchronous else [])


@pytest.fixture
def routing(monkeypatch):
    monkeypatch.setattr(web, 'WEB_CONFIG', None)
    monkeypatch.setattr(web, 'resolve_bridge_id', lambda **kwargs: kwargs.get('bridge_id') or 'test_bridge')
    monkeypatch.setattr(web, 'resolve_account_mode', lambda *args, **kwargs: 'lttx')
    monkeypatch.setattr(web, 'default_runtime_client_mode', lambda: 'lttx')
    monkeypatch.setattr(web, 'account_market_route_config', lambda **kwargs: ({}, {}))
    calls = []
    def request(bridge_id, channel, action, params, **kwargs):
        calls.append((bridge_id, channel, action, params, kwargs))
        asynchronous = action.endswith('_async')
        rows = batch_result_rows(params['orders'], params.get('seqs'))
        for index, row in enumerate(rows):
            row.update(status='submitted', ok=True, order_id=None if asynchronous else 1000 + index)
        return batch_result(params['account'], params['batch_id'], asynchronous, rows)
    clients = SimpleNamespace(request=request)
    monkeypatch.setattr(web, 'CLIENTS', clients)
    return clients, calls


@pytest.mark.parametrize('asynchronous', [False, True])
def test_external_sdk_batch_is_forwarded_once_and_executed_inside_qmt(routing, monkeypatch, asynchronous):
    clients, calls = routing
    native = []
    bridge = TxTradeBridge(None, show=False, globals_dict={'passorder': lambda *args: native.append(args) or 1000 + len(native)})
    bridge.order_meta_enabled = False
    def request(bridge_id, channel, action, params, **kwargs):
        calls.append((bridge_id, channel, action, params, kwargs))
        return bridge._dispatch(action, params, {'client_id': 'test-caller', 'id': 'test-request'})
    clients.request = request
    trader = XtQuantTrader(account=dict(account_id='TEST_ONLY', account_type='STOCK', bridge_id='test_bridge'))
    outer = []
    def sdk_request(action, params):
        outer.append((action, params))
        return web.route_external_lttx_request(dict(action=action, params=params))[0]
    monkeypatch.setattr(trader, '_trade_request', sdk_request)
    bridge._send_trader_event = lambda *args: None
    try:
        api = CfQuantTrader(trader)
        result = (api.order_stock_batch_async if asynchronous else api.order_stock_batch)(None, [order(), order('000001.SZ')])
        assert result['submitted'] == 2
        assert len(outer) == len(calls) == 1
        assert calls[0][0:2] == ('test_bridge', 'trade')
        assert len(calls[0][3]['orders']) == len(native) == 2
        assert calls[0][4]['mode'] == 'lttx'
    finally:
        bridge.close()
        trader.stop()


@pytest.mark.parametrize('asynchronous', [False, True])
def test_qmt_timeout_does_not_fall_back_or_replay(routing, asynchronous):
    clients, calls = routing
    def timeout(*args, **kwargs):
        calls.append((args, kwargs))
        raise CfquantTimeout('lost QMT batch response')
    clients.request = timeout
    action = 'cftrader.order_stock_batch' + ('_async' if asynchronous else '')
    result, meta = web.route_external_lttx_request(dict(action=action, params=payload(asynchronous)))
    assert len(calls) == 1
    assert calls[0][1]['mode'] == 'lttx'
    assert result['unknown'] == 2
    assert result['skipped'] == 0
    assert all('lost QMT batch response' in row['error'] for row in result['results'])


def test_closed_pipe_error_does_not_resend_batch(monkeypatch):
    calls, dropped = [], []
    def closed(*args, **kwargs):
        calls.append((args, kwargs))
        raise CfquantError('cfquant pipe connection closed')
    client = SimpleNamespace(request=closed)
    manager = web.GlobalTxClient()
    monkeypatch.setattr(manager, '_get_client', lambda mode: client)
    monkeypatch.setattr(manager, '_drop_client', lambda *args: dropped.append(args))
    monkeypatch.setattr(web, 'bridge_channels', lambda bridge_id: dict(trade='fake.trade', normal='fake.normal'))
    with pytest.raises(CfquantError, match='closed'):
        manager.request('test_bridge', 'trade', 'cftrader.order_stock_batch', payload(), mode='ctypes')
    assert len(calls) == 1
    assert dropped == [('ctypes', client)]


@pytest.mark.parametrize('asynchronous', [False, True])
def test_independent_market_batches_preserve_input_order_and_seqs(routing, monkeypatch, asynchronous):
    clients, calls = routing
    routes = dict(SH=dict(bridge_id='qmt_sh'), SZ=dict(bridge_id='qmt_sz'))
    monkeypatch.setattr(web, 'account_market_route_config', lambda **kwargs: ({'market_routing_enabled': True}, routes))
    action = 'cftrader.order_stock_batch' + ('_async' if asynchronous else '')
    params = payload(asynchronous, ('600000.SH', '600001.SH', '000001.SZ', '000002.SZ', '600002.SH'))
    result, meta = web.route_external_lttx_request(dict(action=action, params=params))
    assert [call[0] for call in calls] == ['qmt_sh', 'qmt_sz', 'qmt_sh']
    assert [len(call[3]['orders']) for call in calls] == [2, 2, 1]
    assert [row['index'] for row in result['results']] == list(range(5))
    assert [row['stock_code'] for row in result['results']] == [row['stock_code'] for row in params['orders']]
    if asynchronous:
        assert [row['seq'] for row in result['results']] == params['seqs']
    assert result['submitted'] == 5


def test_invalid_market_route_is_rejected_before_any_batch(routing, monkeypatch):
    clients, calls = routing
    monkeypatch.setattr(web, 'account_market_route_config', lambda **kwargs: ({}, {'SH': dict(bridge_id='qmt_sh')}))
    with pytest.raises(ValueError, match='No enabled QMT market route'):
        web.route_external_lttx_request(dict(action='cftrader.order_stock_batch', params=payload()))
    assert calls == []


@pytest.mark.parametrize('outcome', ['failed', 'unknown'])
def test_market_batch_stop_preserves_completed_and_unsubmitted_segments(routing, monkeypatch, outcome):
    clients, calls = routing
    monkeypatch.setattr(web, 'account_market_route_config', lambda **kwargs: ({}, {
        'SH': dict(bridge_id='qmt_sh'), 'SZ': dict(bridge_id='qmt_sz'),
    }))
    original = clients.request
    def request(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(calls) == 2:
            if outcome == 'unknown':
                raise CfquantTimeout('second segment lost')
            result['results'][0].update(status='failed', ok=False, order_id=None, error='rejected')
        return result
    clients.request = request
    params = payload(codes=('600000.SH', '000001.SZ', '600001.SH'))
    params['stop_on_error'] = True
    result, _ = web.route_external_lttx_request(dict(action='cftrader.order_stock_batch', params=params))
    assert len(calls) == 2
    assert [row['status'] for row in result['results']] == ['submitted', outcome, 'skipped']
