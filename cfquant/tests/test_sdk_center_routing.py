"""SDK routing must not change when Web/A discovery records change."""
import queue

import pytest

from cfquant import client, config
from cfquant.center_client import CenterRpcClient
from cfquant.management import RuntimeManager
from cfquant.protocol import loads_message, pack_response
from cfquant.qmt_inner import QmtInnerApi
from cfquant.xttrader import XtQuantTrader


@pytest.fixture
def wire(monkeypatch):
    sent = []
    respond = [True]

    class MemoryTx:
        def __init__(self, *args, **kwargs):
            self.Q = queue.Queue()
        def start_tx(self):
            pass
        def start_txg(self, channel):
            pass
        def push(self, key, raw, channel):
            msg = loads_message(raw)
            sent.append((channel, msg))
            if respond[0]:
                self.Q.put(pack_response(msg['id'], result={'ok': True}))
        def close(self):
            self.Q.put(None)

    monkeypatch.setattr(client, '_load_txl', lambda: MemoryTx)
    return sent, respond


@pytest.mark.parametrize('transport', ['auto', 'web', 'web_lttx'])
def test_request_timeout_keeps_same_center_when_it_later_recovers(monkeypatch, wire, transport):
    sent, respond = wire
    registry_reads = []
    def registry(cfg=None, key=None):
        registry_reads.append(key)
        return {} if key else {'web_request_channel': 'old.web.request'}
    monkeypatch.setattr(client, 'load_lttx_registry', registry)
    rpc = client.create_rpc_client(transport=transport, timeout=.05)
    try:
        respond[0] = False
        with pytest.raises(client.CfquantTimeout):
            rpc.request('xtdata.get_full_tick', {'stock_list': ['000001.SZ']})
        respond[0] = True
        assert rpc.request('xtdata.get_full_tick', {'stock_list': ['000001.SZ']}) == {'ok': True}
        assert [channel for channel, _ in sent] == ['cfquant.center.request'] * 2
        assert not registry_reads
    finally:
        rpc.close()


def test_management_configures_center_then_trader_uses_center(monkeypatch, wire):
    import cfquant
    for key in list(config._config):
        monkeypatch.setitem(config._config, key, config._config[key])
    monkeypatch.setattr(cfquant, 'configure', config.configure)
    runtime = RuntimeManager(base_url='http://offline.invalid')
    monkeypatch.setattr(runtime, 'status', lambda: {'lttx_host': '127.0.0.1', 'lttx_port': 12049})
    runtime.configure_client()
    assert config.get_config()['transport'] == 'center'
    trader = XtQuantTrader()
    try:
        rpc = trader._get_client()
        assert type(rpc) is CenterRpcClient
        assert (rpc.host, rpc.port) == ('127.0.0.1', 12049)
        assert rpc.request('xttrader.query_account_infos') == {'ok': True}
        assert wire[0][0][0] == 'cfquant.center.request'
        assert wire[0][0][1]['params']['_center_request_channel'] == 'trade'
    finally:
        trader.stop()


@pytest.mark.parametrize('transport', ['auto', 'web', 'web_lttx'])
def test_default_market_client_honors_legacy_configuration_without_web(monkeypatch, wire, transport):
    monkeypatch.setattr(client, '_default_client', None)
    monkeypatch.setitem(config._config, 'transport', transport)
    monkeypatch.setitem(config._config, 'web_request_channel', 'old.web.request')
    try:
        rpc = client.get_client()
        assert type(rpc) is CenterRpcClient
        rpc.request('xtdata.get_full_tick', {})
        assert wire[0][0][0] == 'cfquant.center.request'
    finally:
        client.close_client()


@pytest.mark.parametrize('action', ['cftrader.order_algo', 'cftrader.order_condition', 'cfquant.notify.send'])
def test_application_services_use_center_without_web_discovery(monkeypatch, wire, action):
    monkeypatch.setattr(client, 'load_lttx_registry', lambda cfg=None, key=None:
                        {'web_request_channel': 'application.web.request'})
    rpc = client.create_rpc_client(transport='center')
    try:
        assert rpc.request(action, {}) == {'ok': True}
        assert [channel for channel, _ in wire[0]] == ['cfquant.center.request']
    finally:
        rpc.close()


@pytest.mark.parametrize('transport', ['auto', 'web_lttx'])
def test_inner_api_preserves_account_and_normal_route_through_center(wire, transport):
    with QmtInnerApi(account_id='TEST', transport=transport, recovery='lease') as api:
        assert type(api._client) is CenterRpcClient
        assert api.capabilities() == {'ok': True}
        channel, request = wire[0][0]
        assert channel == 'cfquant.center.request'
        assert request['action'] == 'qmt_inner.capabilities'
        assert request['params']['account_id'] == 'TEST'
        assert request['params']['_center_request_channel'] == 'normal'
