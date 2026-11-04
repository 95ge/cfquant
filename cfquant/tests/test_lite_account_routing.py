"""Exercise standalone account routing without starting QMT or sending orders."""

import ast
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))


@pytest.fixture(params=LITE_PATHS, ids=lambda path: path.stem)
def lite(request):
    source = request.param.read_text(encoding='gbk')
    tree = ast.parse(source, feature_version=(3, 6))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TxTradeBridge')
    cls.bases = []
    methods = {'_dispatch', '_subscribe_account', '_unsubscribe_account', '_account_subscription_status',
               '_client_ids_for_account', '_send_trader_event_to_account',
               '_account_subscriber_status', '_account_type_name'}
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods]
    namespace = dict(threading=threading, time=time)
    shared = source.split('# BEGIN GENERATED CFTRADER BATCH\n', 1)[1].split('# END GENERATED CFTRADER BATCH', 1)[0]
    exec(compile(shared, str(request.param), 'exec'), namespace)
    # Use the functions actually embedded in each script, including legacy ones
    # before the fix. Importing the package implementation would hide this bug.
    route_nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name.startswith(('_account_route_', 'account_route_'))]
    namespace.update(_ACCOUNT_ROUTE_LOCK=threading.RLock(),
                     _ACCOUNT_ROUTE_SUBSCRIBERS={}, _ACCOUNT_ROUTE_CLIENT_ACCOUNTS={})
    exec(compile(ast.Module(body=route_nodes + [cls], type_ignores=[]), str(request.param), 'exec'), namespace)

    def bridge(bridge_id='test_bridge'):
        instance = namespace['TxTradeBridge']()
        instance.bridge_id = bridge_id
        instance.account_id = ''
        instance.account_type = ''
        instance.request_channel = 'test.request'
        instance.subscriber_lock = threading.RLock()
        instance.account_subscribers = {}
        instance.confirmed_account_subscriptions = set()
        instance.auto_trade_callback_enabled = True
        instance.client_accounts = {}
        instance._set_context_account = lambda *args: None
        instance._enable_auto_trade_callback = lambda: None
        instance._log = lambda *args: None
        return instance

    return SimpleNamespace(bridge=bridge, scope=namespace)


@pytest.mark.parametrize('account_type', ['STOCK', 'CREDIT'])
def test_readme_connect_subscribes_and_disconnect_cleans_up(lite, monkeypatch, account_type):
    bridge = lite.bridge()
    account = StockAccount('TEST_ONLY', account_type, bridge_id=bridge.bridge_id)
    trader = XtQuantTrader('', account=account)
    calls = []

    class Client:
        def start(self):
            pass

        def add_callback(self, *args):
            pass

        def request(self, action, params=None, timeout=None, response_meta=None):
            calls.append(action)
            return bridge._dispatch(action, params or {}, {'client_id': trader.client_id})

        def close(self):
            pass

    monkeypatch.setattr(trader, '_get_client', lambda bridge_id=None: Client())
    try:
        assert trader.connect() == 0, trader.last_connect_error
        assert calls == ['xttrader.subscribe', 'cfquant.ping']
        # The other bridge instance receives callbacks through shared routing.
        callback_bridge = lite.bridge()
        assert callback_bridge._client_ids_for_account('TEST_ONLY', account_type) == [trader.client_id]
        assert callback_bridge._account_subscriber_status() == {account_type + ':TEST_ONLY': 1}
    finally:
        trader.disconnect()
    assert 'xttrader.unsubscribe' in calls
    assert bridge._account_subscriber_status() == {}
    assert lite.scope['_ACCOUNT_ROUTE_SUBSCRIBERS'] == {}
    assert lite.scope['_ACCOUNT_ROUTE_CLIENT_ACCOUNTS'] == {}


def test_callbacks_isolate_bridge_and_account_type(lite):
    first = lite.bridge('first')
    second = lite.bridge('second')
    for bridge, kind, client in [(first, 'STOCK', 'stock'), (first, 'CREDIT', 'credit'),
                                 (second, 'STOCK', 'other_bridge')]:
        bridge._subscribe_account({'account_id': 'SAME_ACCOUNT', 'account_type': kind}, {'client_id': client})
    receiver = lite.bridge('first')
    events = []
    receiver._send_trader_event = lambda client, name, data: events.append((client, name, data))
    receiver._send_trader_event_to_account('SAME_ACCOUNT', 'on_stock_trade', {}, account_type='CREDIT')
    assert events == [('credit', 'on_stock_trade', {'account_type': 'CREDIT'})]
    first._unsubscribe_account({'account_id': 'SAME_ACCOUNT', 'account_type': 'STOCK'}, {'client_id': 'stock'})
    assert receiver._client_ids_for_account('SAME_ACCOUNT', 'STOCK') == []
    assert receiver._client_ids_for_account('SAME_ACCOUNT', 'CREDIT') == ['credit']
    assert second._client_ids_for_account('SAME_ACCOUNT', 'STOCK') == ['other_bridge']


def test_unsubscribe_client_clears_all_its_accounts_only_in_one_bridge(lite):
    first, second = lite.bridge('first'), lite.bridge('second')
    for bridge in (first, second):
        for kind in ('STOCK', 'CREDIT'):
            bridge._subscribe_account({'account_id': 'TEST_ONLY', 'account_type': kind}, {'client_id': 'client'})
    first._unsubscribe_account({}, {'client_id': 'client'})
    assert lite.bridge('first')._account_subscriber_status() == {}
    assert lite.bridge('second')._account_subscriber_status() == {'STOCK:TEST_ONLY': 1, 'CREDIT:TEST_ONLY': 1}


@pytest.mark.parametrize('numeric, name', [(2, 'STOCK'), (3, 'CREDIT'), (7, 'HUGANGTONG'), (11, 'SHENGANGTONG')])
def test_routing_normalizes_numeric_account_types(lite, numeric, name):
    scope = lite.scope
    scope['account_route_subscribe']('bridge', 'TEST_ONLY', 'client', account_type=numeric)
    assert scope['account_route_client_ids']('bridge', 'TEST_ONLY', account_type=name) == ['client']
    scope['account_route_unsubscribe']('bridge', account_id='TEST_ONLY', account_type=name)
    assert scope['account_route_status']('bridge') == {}
    assert scope['_ACCOUNT_ROUTE_CLIENT_ACCOUNTS'] == {}
