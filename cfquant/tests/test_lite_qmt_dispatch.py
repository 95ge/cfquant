"""Exercise the actual standalone dispatcher with fake QMT/transport only.

No strategy is loaded, no pipe is connected and no real order is submitted.
"""
import ast
import threading
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from cfquant.protocol import decode_value, loads_message, pack_request


ROOT = Path(__file__).resolve().parents[2]
LITE_PATHS = sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))


class Transport:
    def __init__(self):
        self.messages = []
        self.closed = False

    def push(self, kind, payload, client_id):
        self.messages.append((kind, loads_message(payload), client_id))

    def _get_conn(self):
        return None if self.closed else self

    def close(self):
        self.closed = True

    @property
    def responses(self):
        return [message for kind, message, _ in self.messages if kind == 'response']


class Context:
    def __init__(self):
        self.calls = []
        self.timers = []
        self.cancelled = []
        self.frame = pd.DataFrame({'close': [10.5, 11.25], 'volume': [100, 200]},
                                  index=pd.Index(['20261012', '20261013'], name='time'))

    def set_account(self, *args):
        self.calls.append(('account', threading.get_ident(), args))

    def set_auto_trade_callback(self, *args):
        self.calls.append(('auto_callback', threading.get_ident(), args))

    def get_market_data_ex(self, *args):
        self.calls.append(('market_ex', threading.get_ident(), args))
        return {'600000.SH': self.frame.copy()}

    def get_full_tick(self, *args):
        self.calls.append(('tick', threading.get_ident(), args))
        return {'600000.SH': {'lastPrice': 11.25, 'volume': 200}}

    def get_trade_detail_data(self, *args):
        self.calls.append(('detail', threading.get_ident(), args))
        return []

    def schedule_run(self, callback, first_time, **kwargs):
        self.timers.append((callback, kwargs))
        return 'fake-qmt-timer'

    def cancel_schedule_run(self, key):
        self.cancelled.append(key)


@pytest.fixture(params=LITE_PATHS, ids=lambda p: p.stem)
def lite(request, monkeypatch):
    source = request.param.read_bytes().decode('gbk')
    tree = ast.parse(source, feature_version=(3, 6))
    cutoff = next(n.lineno for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_entry_file_path')
    # Load every real class and function, plus constants and queues. Exclude
    # module startup and assignments to os.environ/sys so tests are isolated.
    body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
            or (isinstance(n, ast.Assign) and n.lineno < cutoff
                and all(isinstance(t, ast.Name) for t in n.targets))]
    namespace = {'__name__': 'fake_qmt_entry', '__file__': str(request.param)}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(request.param), 'exec'), namespace)
    namespace.update(_LOG_ENABLED=False, _QMT_BOUND_LOG_ENABLED=False, DEFAULT_ACCOUNT_ID='TEST_ONLY', DEFAULT_ACCOUNT_TYPE='CREDIT',
                     BRIDGE_CHANNELS={'normal': 'test.normal', 'trade': 'test.trade', 'callback': 'test.callback'},
                     _ENTRY_VERSION=namespace['LITE_ENTRY_VERSION'], TRADE_LOOP_IN_THREAD=False)
    transport = Transport()

    def start(bridge):
        bridge.running = True
        bridge.tx = transport
        return bridge

    monkeypatch.setattr(namespace['PipeNormalQmtBridge'], 'start', start)
    # Evaluate the actual entry call to catch missing/incorrect dispatch flags.
    creation = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'start_pipe_normal_bridge')
    bridge = eval(compile(ast.Expression(creation), str(request.param), 'eval'), namespace)
    bridge.account_type = 'CREDIT'
    namespace['_normal_bridge'] = bridge
    context = Context()
    bridge.set_context(context)
    env = SimpleNamespace(ns=namespace, bridge=bridge, tx=transport, context=context, path=request.param)
    yield env
    bridge.close()


def enqueue(env, action='xtdata.get_market_data_ex', request_id='request-1', params=None, trade=False):
    raw = pack_request(action, params=params or {'stock_list': ['600000.SH'], 'field_list': ['close', 'volume'],
                                               'period': '1d', 'count': 2},
                       client_id='fake-client', request_id=request_id)
    if trade:
        env.ns['_trade_request_queue'].put_nowait(raw)
    else:
        thread = threading.Thread(target=env.bridge._handle_raw_from_thread, args=(raw,))
        thread.start()
        thread.join(2)
        assert not thread.is_alive()


@pytest.mark.parametrize('callback', ['timer', 'timer_keyword', 'handlebar'])
def test_qmt_callback_dispatches_market_data_on_caller_and_preserves_frames(lite, callback):
    enqueue(lite)
    assert not lite.tx.responses
    assert not any(c[0] == 'market_ex' for c in lite.context.calls)
    fresh = Context()
    lite.ns['_trade_bridge'] = SimpleNamespace(context=lite.context)
    if callback == 'handlebar':
        lite.ns['handlebar'](fresh)
    elif callback == 'timer_keyword':
        lite.ns['cfquant_ctype_trade_timer'](ContextInfo=fresh)
    else:
        lite.ns['cfquant_ctype_trade_timer'](fresh)
    assert lite.bridge.context is fresh
    assert lite.ns['_trade_bridge'].context is fresh
    native = [c for c in fresh.calls if c[0] == 'market_ex']
    assert len(native) == 1 and native[0][1] == threading.get_ident()
    assert len(lite.tx.responses) == 1
    response = lite.tx.responses[0]
    assert response['ok'] is True
    pd.testing.assert_frame_equal(decode_value(response['result'])['600000.SH'], fresh.frame)
    assert response.get('meta'), 'market timing must survive the dispatch change'
    assert lite.bridge.worker_thread is None
    status = lite.bridge._status_extra()
    assert status['dispatch_on_qmt_thread'] is True
    assert status['dispatch_thread'] == 'qmt_caller_thread'
    assert status['worker_thread_alive'] is False


def test_entry_uses_one_fast_timer_and_can_dispatch_without_ticks(lite):
    assert lite.context.timers == []
    lite.ns['_schedule_trade_timer'](lite.context)
    lite.ns['_schedule_trade_timer'](lite.context)
    assert len(lite.context.timers) == 1
    callback, options = lite.context.timers[0]
    assert options['interval'].total_seconds() == .001
    enqueue(lite, 'xtdata.get_full_tick')
    callback()  # QMT versions that omit ContextInfo keep the initialized context.
    assert lite.tx.responses[0]['ok'] is True
    assert decode_value(lite.tx.responses[0]['result'])['600000.SH']['lastPrice'] == 11.25
    assert lite.bridge.worker_thread is None
    lite.ns['stop'](lite.context)
    assert lite.context.cancelled == ['fake-qmt-timer']
    assert lite.tx.closed and not lite.bridge.running


def test_coalesced_requests_and_pump_limit(lite):
    params = {'account': {'account_id': 'TEST_ONLY', 'account_type': 'CREDIT'}}
    for request_id in ('a', 'b'):
        enqueue(lite, 'xttrader.query_stock_positions', request_id, params)
    enqueue(lite, 'xtdata.get_full_tick', 'tick')
    lite.bridge.pump_max_count = 1
    lite.bridge.on_timer()
    assert {r['id'] for r in lite.tx.responses} == {'a', 'b'}
    assert all(r['ok'] for r in lite.tx.responses)
    assert len([c for c in lite.context.calls if c[0] == 'detail']) == 1
    assert lite.bridge.request_queue.qsize() == 1
    lite.ns['cfquant_ctype_trade_timer']()
    assert {r['id'] for r in lite.tx.responses} == {'a', 'b', 'tick'}


def submit_order(env, request_id='order-1', wait=60):
    enqueue(env, 'xttrader.order_stock', request_id, {
        'account': {'account_id': 'TEST_ONLY', 'account_type': 'CREDIT'},
        'stock_code': '600000.SH', 'order_type': 23, 'order_volume': 100,
        'price_type': 11, 'price': 10.5, 'order_remark': 'same user remark',
        'find_order_wait': wait,
    }, trade=True)


def test_sync_trade_reroute_releases_qmt_thread_until_matching_callback(lite):
    submissions = []
    lite.bridge.globals_dict['passorder'] = lambda *args: submissions.append(args) or 0
    lite.ns['_trade_bridge'] = SimpleNamespace(context=lite.context)
    for request_id in ('order-1', 'order-2'):
        submit_order(lite, request_id)
    enqueue(lite, 'xtdata.get_full_tick', 'tick')
    lite.ns['cfquant_ctype_trade_timer'](lite.context)
    assert len(submissions) == 2
    assert [r['id'] for r in lite.tx.responses] == ['tick']
    assert len(lite.bridge.pending_sync_orders) == 2
    assert len({args[9] for args in submissions}) == 2
    assert not lite.bridge._resolve_pending_sync_order_callback({
        'account_id': 'WRONG_ACCOUNT', 'order_remark': submissions[0][9], 'm_nRef': 999,
    })
    for index in (1, 0):
        # Use the real callback publisher, including formatting and identity
        # restoration, rather than setting the pending record directly.
        lite.bridge.publish_callback_event('trader:on_stock_order', {
            'm_strAccountID': 'TEST_ONLY', 'm_strInstrumentID': '600000', 'm_strExchangeID': 'SH',
            'm_strRemark': submissions[index][9], 'm_nRef': 7000 + index,
            'm_strOrderSysID': 'SYS-%s' % index,
        })
        lite.ns['cfquant_ctype_trade_timer']()
    orders = [r for r in lite.tx.responses if r['id'].startswith('order')]
    assert [(r['id'], decode_value(r['result'])['order_id']) for r in orders] == [
        ('order-2', 7001), ('order-1', 7000),
    ]
    assert all(r['ok'] for r in orders)
    lite.ns['cfquant_ctype_trade_timer']()
    assert len(lite.tx.responses) == 3
    assert not lite.bridge.pending_sync_orders
    assert len(submissions) == 2


@pytest.mark.parametrize('outcome', ['timeout', 'rejected', 'exception'])
def test_sync_order_failure_finishes_once_without_resubmission(lite, outcome):
    submissions = []

    def passorder(*args):
        submissions.append(args)
        if outcome == 'exception':
            raise RuntimeError('fake native failure')
        return -1 if outcome == 'rejected' else 0

    lite.bridge.globals_dict['passorder'] = passorder
    lite.ns['_trade_bridge'] = SimpleNamespace(context=lite.context)
    submit_order(lite, wait=0)
    lite.ns['cfquant_ctype_trade_timer']()
    lite.ns['cfquant_ctype_trade_timer']()
    lite.ns['cfquant_ctype_trade_timer']()
    assert len(lite.tx.responses) == 1
    response = lite.tx.responses[0]
    if outcome == 'exception':
        assert response['ok'] is False
    else:
        assert response['ok'] is True
        assert decode_value(response['result'])['order_id'] == -1
    assert not lite.bridge.pending_sync_orders
    assert len(submissions) == 1


def test_templates_and_regenerators_keep_qmt_dispatch():
    from tools.sync_qmt_dispatch import updated_source
    from tools.sync_qmt_fileless import updated_source as fileless_source
    from tools.sync_qmt_batch import updated_source as batch_source
    for path in LITE_PATHS:
        raw = path.read_bytes()
        assert b'\n' not in raw.replace(b'\r\n', b'')
        source = raw.decode('gbk').replace('\r\n', '\n')
        assert updated_source(source) == source
        assert fileless_source(source, lite=True) == source
        assert fileless_source(batch_source(source), lite=True) == source
        assert '"xttrader_to_normal_qmt_timer"' in source
        assert 'from cfquant.' not in source
