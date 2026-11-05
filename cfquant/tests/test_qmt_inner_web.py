"""Native API routing must never replay a call or alter native callback data."""
from types import SimpleNamespace

import pytest

import cfquant_web_server as web
from cfquant.client import CfquantTimeout


@pytest.fixture
def routing(monkeypatch):
    monkeypatch.setattr(web, 'WEB_CONFIG', None)
    monkeypatch.setattr(web, 'resolve_bridge_id', lambda **kw: kw.get('bridge_id') or 'test_bridge')
    monkeypatch.setattr(web, 'resolve_account_mode', lambda *args, **kw: 'lttx')
    monkeypatch.setattr(web, 'default_runtime_client_mode', lambda: 'lttx')
    monkeypatch.setattr(web, 'account_market_route_config', lambda **kw: ({}, {}))
    calls = []
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return {'native': True}
    clients = SimpleNamespace(request=request)
    monkeypatch.setattr(web, 'CLIENTS', clients)
    return clients, calls


@pytest.mark.parametrize('account', ['', 'demo'])
def test_external_native_call_keeps_bridge_normal_channel_and_real_client(routing, account):
    _, calls = routing
    params = dict(session_id='session', bridge_id='office', account_id=account,
                  category='trade', method='passorder', args=[23, 1101, 'demo'],
                  channel='trade', _inner_client_id='forged-client')
    result, meta = web.route_external_lttx_request(dict(action='qmt_inner.call', params=params, client_id='real-client'))
    assert result == {'native': True}
    assert meta['route'] == 'qmt_inner'
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == ('office', 'normal', 'qmt_inner.call')
    assert args[3]['_inner_client_id'] == 'real-client'
    assert args[3]['args'] == params['args']
    assert kwargs['mode'] == 'lttx'


def test_web_does_not_fallback_after_ambiguous_native_order_timeout(routing):
    clients, calls = routing
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        raise CfquantTimeout('submitted but response lost')
    clients.request = request
    with pytest.raises(CfquantTimeout, match='response lost'):
        web.route_external_lttx_request(dict(action='qmt_inner.call', client_id='client',
            params=dict(session_id='session', bridge_id='office', category='trade', method='passorder')))
    assert len(calls) == 1


def test_web_forwards_native_event_to_only_originating_sdk():
    server = web.LttxWebRouteServer()
    received = []
    server._push_event = lambda *args: received.append(args)
    payload = {'token': 'callback', 'args': [{'m_nVolume': 100}]}
    server._on_client_event(dict(event='qmt_inner:session', data=payload,
                                 meta={'inner_client_id': 'external-sdk'}))
    assert received == [('external-sdk', 'qmt_inner:session', payload)]
