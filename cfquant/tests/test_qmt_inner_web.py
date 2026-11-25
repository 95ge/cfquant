"""Native API routing must never replay a call or alter native callback data."""
from types import SimpleNamespace

import pytest

from cfquant import runtime_services as web
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


def test_external_native_call_resolves_bridge_from_account_without_bridge_id(routing):
    _, calls = routing
    params = dict(session_id='session', account_id='55009948', account_type='STOCK',
                  category='market', method='get_bvol', args=['000001.SZ'])
    result, meta = web.route_external_lttx_request(dict(action='qmt_inner.call', params=params,
                                                        client_id='real-client'))
    assert result == {'native': True}
    assert meta['route'] == 'qmt_inner'
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == ('test_bridge', 'normal', 'qmt_inner.call')
    assert args[3]['account_id'] == '55009948'
    assert not args[3].get('bridge_id')
    assert kwargs['mode'] == 'lttx'


def test_external_native_call_without_account_uses_current_data_provider(routing, monkeypatch):
    _, calls = routing
    monkeypatch.setattr(web, 'data_provider_candidates', lambda: [{
        'account_id': 'provider-account', 'account_type': 'STOCK',
        'account_key': 'provider-key', 'bridge_id': 'provider-bridge',
    }])
    params = dict(session_id='session', category='market', method='get_bvol', args=['000001.SZ'])
    result, meta = web.route_external_lttx_request(dict(action='qmt_inner.call', params=params,
                                                        client_id='real-client'))
    assert result == {'native': True}
    assert meta['route'] == 'qmt_inner'
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == ('test_bridge', 'normal', 'qmt_inner.call')
    assert args[3]['account_id'] == 'provider-account'
    assert args[3]['account_type'] == 'STOCK'
    assert args[3]['account_key'] == 'provider-key'
    assert not args[3].get('bridge_id')
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
