"""Web order tester checks with fake bindings and fake QMT execution only."""

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

import pytest

import cfquant_web_server as web
from cfquant.tests.test_cftrader_web import routing, order
from cfquant.tx_trade_bridge import TxTradeBridge


@pytest.fixture
def binding(monkeypatch):
    row = dict(account_id='TEST_ONLY', account_type='CREDIT', bridge_id='test_bridge',
               account_key='test_binding', enabled=True)
    monkeypatch.setattr(web, 'account_config_for_request', lambda body: row)
    return row


def body(batch=True):
    value = dict(account_id='TEST_ONLY', account_type='CREDIT', account_key='test_binding',
                 confirm_text='CFTRADER TEST_ONLY %s' % (2 if batch else 1), strategy_name='web-test')
    value.update(orders=[order(), order('000001.SZ')]) if batch else value.update(order())
    return value


def cancel_body():
    return dict(account_id='TEST_ONLY', account_type='CREDIT', account_key='test_binding',
                confirm_text='CFTRADER TEST_ONLY 2',
                cancels=[dict(order_id='1001', stock_code='600000.SH'), dict(order_id='1002', market='SZ')])


@pytest.mark.parametrize('asynchronous', [False, True])
def test_web_batch_sends_one_qmt_request_and_preserves_original_callbacks(binding, routing, asynchronous):
    clients, calls = routing
    native, callbacks = [], []
    bridge = TxTradeBridge(None, show=False, globals_dict={'passorder': lambda *args: native.append(args) or 1000 + len(native)})
    bridge.order_meta_enabled = False
    bridge._send_trader_event = lambda client, event, data: callbacks.append((event, data))
    def request(bridge_id, channel, action, params, **kwargs):
        calls.append((action, params))
        return bridge._dispatch(action, params, {'client_id': 'original-web-client', 'id': 'fake-request'})
    clients.request = request
    try:
        method = 'order_stock_batch' + ('_async' if asynchronous else '')
        result = web.submit_cftrader_order(body(), method)
        assert len(calls) == 1 and len(native) == 2
        assert calls[0][0] == 'cftrader.' + method
        assert result['result']['submitted'] == 2
        assert result['result']['execution'] == 'qmt'
        assert result['result']['qmt_submit_ms'] >= 0
        assert all(args[0] == 33 and args[2] == 'TEST_ONLY' for args in native)
        assert len(callbacks) == (2 if asynchronous else 0)
        if asynchronous:
            assert all(event == 'on_order_stock_async_response' for event, data in callbacks)
            assert [data['seq'] for event, data in callbacks] == calls[0][1]['seqs']
    finally:
        bridge.close()


@pytest.mark.parametrize('asynchronous', [False, True])
def test_web_cancel_batch_sends_one_qmt_request(binding, routing, asynchronous):
    clients, calls = routing
    method = 'cancel_order_stock_batch' + ('_async' if asynchronous else '')
    result = web.submit_cftrader_order(cancel_body(), method)
    assert len(calls) == 1
    assert calls[0][2] == 'cftrader.' + method
    assert 'cancels' in calls[0][3] and 'orders' not in calls[0][3]
    assert result['api_method'] == 'cftrader.' + method
    assert result['result']['operation'] == 'cancel'
    assert result['result']['submitted'] == 2
    if asynchronous:
        assert len(calls[0][3]['seqs']) == 2


@pytest.mark.parametrize('asynchronous', [False, True])
def test_web_single_uses_original_xttrader_action(binding, monkeypatch, asynchronous):
    calls = []
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(result={'seq': args[4]['seq'], 'accepted': True} if asynchronous else {'order_id': 1001})
    monkeypatch.setattr(web, 'account_request', request)
    method = 'order_stock' + ('_async' if asynchronous else '')
    result = web.submit_cftrader_order(body(False), method)
    assert len(calls) == 1 and calls[0][0][3] == 'xttrader.' + method
    assert calls[0][0][4]['order_volume'] == 100
    assert result['api_method'] == 'cftrader.' + method


@pytest.mark.parametrize('changes', [
    {'confirm_text': ''}, {'confirm_text': 'CFTRADER TEST_ONLY 1'},
    {'account_id': 'OTHER'}, {'account_type': 'STOCK'}, {'account_key': 'OTHER'}, {'bridge_id': 'OTHER'},
    {'orders': []}, {'orders': 'bad json'}, {'orders': [dict(order(), order_volume=0)]},
    {'orders': [dict(order(), price=float('nan'))]}, {'orders': [dict(order(), price=0)]},
    {'stop_on_error': 'false'},
])
def test_invalid_web_order_never_reaches_qmt(binding, routing, changes):
    _, calls = routing
    value = body()
    value.update(changes)
    with pytest.raises((ValueError, TypeError)):
        web.submit_cftrader_order(value, 'order_stock_batch')
    assert calls == []


@pytest.mark.parametrize('changes', [
    {'confirm_text': ''}, {'confirm_text': 'CFTRADER TEST_ONLY 1'},
    {'cancels': []}, {'cancels': [dict(order_id='')]},
    {'cancels': [dict(order_id='1001', market='HK')]}, {'stop_on_error': 'false'},
])
def test_invalid_web_cancel_batch_never_reaches_qmt(binding, routing, changes):
    _, calls = routing
    value = cancel_body()
    value.update(changes)
    with pytest.raises((ValueError, TypeError)):
        web.submit_cftrader_order(value, 'cancel_order_stock_batch')
    assert calls == []


def test_disabled_binding_and_unknown_method_never_reach_qmt(binding, routing):
    _, calls = routing
    binding['enabled'] = False
    with pytest.raises(ValueError, match='disabled'):
        web.submit_cftrader_order(body(), 'order_stock_batch')
    with pytest.raises(ValueError, match='unsupported'):
        web.submit_cftrader_order(body(), '__getattribute__')
    assert calls == []


def test_web_async_batches_use_distinct_sequences(binding, routing):
    results = [web.submit_cftrader_order(body(), 'order_stock_batch_async')['result'] for _ in range(2)]
    seqs = [row['seq'] for result in results for row in result['results']]
    assert len(set(seqs)) == 4


def test_web_batch_lost_response_is_unknown_without_replay(binding, routing):
    clients, calls = routing
    def request(*args, **kwargs):
        calls.append(args)
        raise web.CfquantTimeout('lost response')
    clients.request = request
    result = web.submit_cftrader_order(body(), 'order_stock_batch')['result']
    assert result['unknown'] == 2 and len(calls) == 1


def test_http_batch_route_checks_authentication_and_validation(binding, routing, monkeypatch):
    _, calls = routing
    monkeypatch.setattr(web, 'WEB_CONFIG', SimpleNamespace(
        web_auth_enabled=lambda: False, api_key=lambda: 'local-test-key',
        account_config=lambda **kwargs: binding))

    class Handler(web.CfquantWebHandler):
        def _request_allowed(self):
            return True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(value, authenticated=True):
        conn = HTTPConnection(*server.server_address, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['X-API-Key'] = 'local-test-key'
        try:
            conn.request('POST', '/api/cftrader/order_stock_batch', json.dumps(value), headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read().decode('utf-8'))
        finally:
            conn.close()

    try:
        assert post(body(), False)[0] == 401
        assert calls == []
        assert post(dict(body(), confirm_text=''))[0] == 400
        assert calls == []
        status, payload = post(body())
        assert status == 200 and payload['ok'] is True
        assert payload['data']['result']['submitted'] == 2, payload
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
