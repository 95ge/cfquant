"""Renewal congestion and bridge idempotence, using fake transport/QMT only."""
from types import SimpleNamespace

import pytest

from cfquant import account_routing
from cfquant.client import CfquantTimeout
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.protocol import pack_request, loads_message
from cfquant.tests.test_lite_qmt_dispatch import lite, enqueue


@pytest.mark.parametrize('renewal', [False, True])
@pytest.mark.parametrize('action', ['xttrader.subscribe', 'cfquant.account_subscription_status'])
def test_web_subscription_timeout_does_not_cool_down_or_close_trading_channel(monkeypatch, renewal, action):
    from cfquant import runtime_services as web
    manager = web.GlobalTxClient()
    calls = []
    def request(request_action, *args, **kwargs):
        calls.append(request_action)
        if request_action == action:
            raise CfquantTimeout('subscription response delayed behind quotes')
        return {'cash': 100}
    client = SimpleNamespace(request=request, close=lambda: pytest.fail('timeout closed shared client'))
    monkeypatch.setattr(manager, '_get_client', lambda mode: client)
    monkeypatch.setattr(web, 'bridge_channels', lambda bridge: {'normal':'test.normal', 'trade':'test.trade'})
    with pytest.raises(CfquantTimeout):
        manager.request('test', 'trade', action, {'subscription_renewal':renewal},
                        mode='ctypes', mark_offline_on_timeout=True)
    assert not manager._cooldown_until
    assert manager.request('test', 'trade', 'xttrader.query_stock_asset', mode='ctypes') == {'cash':100}
    assert calls == [action, 'xttrader.query_stock_asset']


@pytest.fixture(params=[TxTradeBridge, NormalQmtBridge], ids=['trade', 'normal'])
def bridge(request):
    native_calls, logs, responses = [], [], []
    context = SimpleNamespace(set_account=lambda *args: native_calls.append(args),
                              set_auto_trade_callback=lambda *args: 0)
    kwargs = {'order_meta_enabled':False} if request.param is NormalQmtBridge else {}
    instance = request.param(context, show=False, **kwargs)
    instance.bridge_id = 'offline-renewal-test'
    instance._log = logs.append
    instance.tx = SimpleNamespace(push=lambda kind, raw, client: responses.append(loads_message(raw)))
    def dispatch(params):
        raw = pack_request('xttrader.subscribe', params, client_id='offline-client')
        if request.param is NormalQmtBridge:
            instance._handle_raw_from_thread(raw)
            msg, received, _ = instance.request_queue.get_nowait()
            instance._drain_single_request('test', msg, received)
        else:
            instance._handle_raw(raw)
        return responses[-1]
    yield SimpleNamespace(instance=instance, calls=native_calls, logs=logs, dispatch=dispatch)
    account_routing.unsubscribe(instance.bridge_id, client_id='offline-client')
    instance._release_auto_trade_callback()


def test_renewal_does_not_repeat_native_account_switch_or_success_logs(bridge):
    first = {'account':{'account_id':'PAPER_A', 'account_type':'STOCK'}}
    second = {'account':{'account_id':'PAPER_B', 'account_type':'CREDIT'}}
    assert bridge.dispatch(first)['ok'] and bridge.dispatch(second)['ok']
    assert len(bridge.calls) == 2
    bridge.logs.clear()
    for _ in range(3):
        assert bridge.dispatch(dict(first, subscription_renewal=True))['ok']
    assert len(bridge.calls) == 2 and bridge.logs == []
    assert bridge.instance.account_id == 'PAPER_B'
    assert bridge.instance._account_subscriber_status() == {'STOCK:PAPER_A':1, 'CREDIT:PAPER_B':1}
    # Losing a registration must still trigger real setup, even on a renewal.
    bridge.instance._unsubscribe_account(first, {'client_id':'offline-client'})
    assert bridge.dispatch(dict(first, subscription_renewal=True))['ok']
    assert len(bridge.calls) == 3
    assert any('account subscribed' in row for row in bridge.logs)


def test_initial_subscription_installs_callback_routing_before_native_setup(bridge):
    def set_account(*args):
        assert bridge.instance.account_id == 'PAPER_A'
        assert bridge.instance._client_ids_for_account('PAPER_A', 'STOCK') == ['offline-client']
        bridge.calls.append(args)
    bridge.instance.context.set_account = set_account
    assert bridge.dispatch({'account':{'account_id':'PAPER_A', 'account_type':'STOCK'}})['ok']
    assert len(bridge.calls) == 1


def test_failed_initial_native_subscription_is_not_mistaken_for_successful_renewal(bridge):
    original = bridge.instance.context.set_account
    def fail(*args): raise RuntimeError('synthetic native failure')
    bridge.instance.context.set_account = fail
    params = {'account':{'account_id':'PAPER_A', 'account_type':'STOCK'}, 'subscription_renewal':True}
    assert not bridge.dispatch(params)['ok']
    assert bridge.instance._account_subscriber_status() == {}
    assert any('synthetic native failure' in row for row in bridge.logs)
    bridge.instance.context.set_account = original
    assert bridge.dispatch(params)['ok']
    assert bridge.instance._account_subscriber_status() == {'STOCK:PAPER_A':1}


def test_embedded_lite_renewal_remains_quiet_and_restores_missing_registration(lite):
    logs = []
    lite.bridge._log = logs.append
    params = {'account':{'account_id':'TEST_ONLY', 'account_type':'CREDIT'}}
    enqueue(lite, 'xttrader.subscribe', params=params)
    lite.ns['cfquant_ctype_trade_timer'](lite.context)
    assert lite.tx.responses[-1]['ok']
    baseline = len([row for row in lite.context.calls if row[0] == 'account'])
    logs.clear()
    for index in range(3):
        enqueue(lite, 'xttrader.subscribe', request_id='renew-%s' % index,
                params=dict(params, subscription_renewal=True))
        lite.ns['cfquant_ctype_trade_timer'](lite.context)
    assert all(row['ok'] for row in lite.tx.responses)
    assert len([row for row in lite.context.calls if row[0] == 'account']) == baseline
    assert logs == []
    lite.bridge._unsubscribe_account(params, {'client_id':'fake-client'})
    enqueue(lite, 'xttrader.subscribe', params=dict(params, subscription_renewal=True))
    lite.ns['cfquant_ctype_trade_timer'](lite.context)
    assert lite.tx.responses[-1]['ok']
    assert len([row for row in lite.context.calls if row[0] == 'account']) == baseline + 1
