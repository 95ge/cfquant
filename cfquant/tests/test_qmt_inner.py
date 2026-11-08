"""Native API contract tests: real RPC encoding around a fake QMT runtime."""
import ast
import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from cfquant import QmtInnerApi
from cfquant.client import CfquantError
from cfquant.protocol import pack_request, pack_response, pack_event, loads_message, decode_value
from cfquant.qmt_inner_runtime import dispatch_inner_api, publish_inner_callback
from cfquant.qmt_inner_catalog import INNER_METHODS


class Loopback:
    def __init__(self, context=None, globals_dict=None, bridge=None, client_id='test-client'):
        self.callbacks = {}
        self.calls = []
        self.closed = False
        self.client_id = client_id
        self.bridge = bridge or SimpleNamespace(context=context or SimpleNamespace(),
                                                globals_dict=globals_dict or {})
        self.bridge._send_event = self.send_event

    def request(self, action, params, timeout=None):
        msg = loads_message(pack_request(action, params, client_id=self.client_id))
        self.calls.append(msg)
        try:
            result = dispatch_inner_api(self.bridge, action, msg['params'], msg)
        except Exception as error:
            raise CfquantError(str(error)) from error
        return decode_value(loads_message(pack_response(msg['id'], result=result))['result'])

    def add_callback(self, event, callback):
        self.callbacks.setdefault(event, []).append(callback)

    def remove_callback(self, event, callback):
        self.callbacks[event].remove(callback)

    def send_event(self, client_id, name, data, **kwargs):
        event = loads_message(pack_event(name, data=data, client_id=client_id, **kwargs))
        for handler in self.callbacks.get(name, []):
            handler(decode_value(event['data']))

    def close(self):
        self.closed = True


def test_market_uses_native_parameters_and_dataframe_roundtrip():
    calls = []
    frame = pd.DataFrame({'close': [12.5]}, index=['20261105'])
    def get_market_data_ex(*args):
        calls.append(args)
        return {'000001.SZ': frame}
    client = Loopback(SimpleNamespace(get_market_data_ex=get_market_data_ex))
    with QmtInnerApi(client=client, bridge_id='test-qmt') as qmt:
        result = qmt.market.get_market_data_ex(['close'], ['000001.SZ'], period='1d', count=1)
        pd.testing.assert_frame_equal(result['000001.SZ'], frame)
    assert calls == [(['close'], ['000001.SZ'], '1d', '', '', 1, 'follow', True, True)]
    assert client.calls[0]['action'] == 'qmt_inner.call'
    assert client.calls[0]['params']['bridge_id'] == 'test-qmt'
    assert not client.closed


def test_account_bound_session_leaves_bridge_resolution_to_web_router():
    client = Loopback(SimpleNamespace(get_full_tick=lambda codes: {'codes': codes}))
    with QmtInnerApi(client=client, account_id='55009948', account_type='STOCK') as qmt:
        assert qmt.market.get_full_tick(['000001.SZ']) == {'codes': ['000001.SZ']}
    params = client.calls[0]['params']
    assert params['account_id'] == '55009948'
    assert params['account_type'] == 'STOCK'
    assert params['bridge_id'] == ''


def test_unbound_session_leaves_bridge_resolution_to_current_web_provider():
    client = Loopback(SimpleNamespace(get_full_tick=lambda codes: {'codes': codes}))
    with QmtInnerApi(client=client) as qmt:
        qmt.market.get_full_tick(['000001.SZ'])
    assert client.calls[0]['params']['account_id'] == ''
    assert client.calls[0]['params']['bridge_id'] == ''


def test_native_owner_is_not_shadowed_by_global_or_context():
    client = Loopback(SimpleNamespace(get_full_tick=lambda codes: 'context',
                                      get_trade_detail_data=lambda *args: 'wrong'),
                      {'get_full_tick': lambda *args: 'wrong', 'get_trade_detail_data': lambda *args: []})
    with QmtInnerApi(client=client) as qmt:
        assert qmt.market.get_full_tick(['000001.SZ']) == 'context'
        assert qmt.trade.get_trade_detail_data('demo', 'stock', 'position') == []


def test_native_records_keep_boost_properties_without_xt_field_mapping():
    class Position:
        __slots__ = ()
        m_nVolume = 100
        m_strInstrumentID = '000001'
    client = Loopback(globals_dict={'get_trade_detail_data': lambda *args: [Position()]})
    with QmtInnerApi(client=client) as qmt:
        rows = qmt.trade.get_trade_detail_data('demo', 'stock', 'position')
        assert rows[0].m_nVolume == 100
        assert rows[0]['m_strInstrumentID'] == '000001'
        assert 'volume' not in rows[0]


@pytest.mark.parametrize('missing_error', [AttributeError, KeyError])
def test_native_records_without_python_type_metadata(missing_error):
    class NativeMeta(type):
        def __getattribute__(cls, name):
            if name == '__module__':
                raise missing_error(name)
            return super().__getattribute__(name)

    class NativeRecord(metaclass=NativeMeta):
        __slots__ = ()
        m_strInstrumentID = '000001'
        m_nVolume = 100

        def __getattribute__(self, name):
            if name == '__dict__':
                raise missing_error(name)
            return super().__getattribute__(name)

    client = Loopback(globals_dict={'get_trade_detail_data': lambda *args: [NativeRecord()]})
    with QmtInnerApi(client=client) as qmt:
        rows = qmt.trade.get_trade_detail_data('demo', 'credit', 'position')
        assert rows[0].m_strInstrumentID == '000001'
        assert rows[0].m_nVolume == 100


def test_passorder_overloads_context_and_no_return_reinterpretation():
    calls = []
    context = SimpleNamespace()
    client = Loopback(context, {'passorder': lambda *args: calls.append(args)})
    with QmtInnerApi(client=client) as qmt:
        assert qmt.trade.passorder(23, 1101, 'demo', '000001.SZ', 11, 10, 100) is None
        qmt.trade.passorder(23, 1101, 'demo', '000001.SZ', 11, 10, 100, 'strategy', 2, 'remark')
        qmt.trade.passorder(23, 1101, 'demo', '000001.SZ', 11, 10, 100, qmt.context)
    assert [len(args) for args in calls] == [8, 11, 8]
    assert all(args[-1] is context for args in calls)
    assert calls[1][7:10] == ('strategy', 2, 'remark')


def test_native_failure_never_retries_an_order():
    calls = []
    def passorder(*args):
        calls.append(args)
        raise TypeError('native failure after submission')
    client = Loopback(globals_dict={'passorder': passorder})
    with QmtInnerApi(client=client) as qmt:
        with pytest.raises(CfquantError, match='after submission'):
            qmt.trade.passorder(23, 1101, 'demo', '000001.SZ', 11, 10, 100)
    assert len(calls) == 1


def test_out_of_scope_methods_are_removed_from_client_and_rejected_by_bridge():
    excluded = {
        'system': 'set_output_index_property is_last_bar is_new_bar get_bar_timetag run_time',
        'market': 'get_history_data get_market_data subscribe_formula unsubscribe_formula call_formula call_formula_batch',
        'trade': 'order_lots order_value order_percent order_target_value order_target_percent order_shares '
                 'buy_open buy_close_tdayfirst buy_close_ydayfirst sell_open sell_close_tdayfirst sell_close_ydayfirst get_debt_contract',
        'reference': 'call_vba get_vba_func_result',
        'drawing': 'paint draw_text draw_number draw_vertline draw_icon',
    }
    calls = []
    native = {name: lambda *args: calls.append(args) for names in excluded.values() for name in names.split()}
    client = Loopback(context=SimpleNamespace(**native), globals_dict=native)
    with QmtInnerApi(client=client) as qmt:
        capabilities = qmt.capabilities()
        assert not hasattr(qmt, 'drawing')
        assert 'drawing' not in capabilities
        for category, names in excluded.items():
            for name in names.split():
                assert name not in capabilities.get(category, {})
                assert not hasattr(getattr(qmt, category, None), name)
                with pytest.raises(ValueError, match='unsupported'):
                    qmt.call(category, name)
                with pytest.raises(CfquantError, match='unsupported'):
                    client.request('qmt_inner.call', dict(session_id=qmt._session_id, category=category, method=name))
    assert not calls


def test_subscribe_callback_can_arrive_before_rpc_returns_and_close_unsubscribes():
    received, cancelled = [], []
    def subscribe(code, period, dividend, result_type, callback):
        callback({code: {'lastPrice': 10}})
        return 72
    client = Loopback(SimpleNamespace(subscribe_quote=subscribe, unsubscribe_quote=cancelled.append))
    with QmtInnerApi(client=client) as qmt:
        assert qmt.market.subscribe_quote('000001.SZ', callback=received.append) == 72
    assert received[0]['000001.SZ'].lastPrice == 10
    assert cancelled == [72]
    assert client.bridge._inner_api_sessions == {}


def test_native_callbacks_keep_context_name_and_original_args():
    received = []
    client = Loopback()
    with QmtInnerApi(client=client) as qmt:
        qmt.callbacks.register('orderError_callback', lambda *args: received.append(args))
        publish_inner_callback(client.bridge, 'orderError_callback', client.bridge.context,
                               SimpleNamespace(orderCode='000001.SZ'), 'test error')
        assert received == [(qmt.context, {'orderCode': '000001.SZ'}, 'test error')]
        qmt.callbacks.unregister('orderError_callback')
        publish_inner_callback(client.bridge, 'orderError_callback', client.bridge.context, {}, 'ignored')
        assert len(received) == 1


def test_schedule_run_transports_datetime_timedelta_and_callback():
    received, cancelled = [], []
    def schedule(func, time_point, repeat_times, interval, name):
        assert time_point == datetime.datetime(2026, 11, 5, 9, 30)
        assert interval == datetime.timedelta(seconds=3)
        func(client.bridge.context)
        return 12
    client = Loopback(SimpleNamespace(schedule_run=schedule, cancel_schedule_run=cancelled.append))
    with QmtInnerApi(client=client) as qmt:
        qmt.system.schedule_run(received.append, datetime.datetime(2026, 11, 5, 9, 30),
                                -1, datetime.timedelta(seconds=3), 'external')
        assert received == [qmt.context]
    assert cancelled == [12]


def test_capabilities_missing_method_and_private_names():
    client = Loopback(SimpleNamespace(get_full_tick=lambda codes: {}))
    with QmtInnerApi(client=client) as qmt:
        capabilities = qmt.capabilities()
        assert capabilities.market.get_full_tick is True
        assert capabilities.trade.passorder is False
        with pytest.raises(CfquantError, match='not available'):
            qmt.trade.get_basket('demo')
        with pytest.raises(ValueError, match='unsupported'):
            qmt.call('system', '__getattribute__', '__dict__')
        with pytest.raises(AttributeError):
            _ = qmt.context.credentials
        with pytest.raises(CfquantError, match='unsupported'):
            client.request('qmt_inner.call', dict(session_id='bad', category='system', method='eval', args=[]))


def test_context_attributes_and_native_calendar_are_remote():
    client = Loopback(SimpleNamespace(barpos=8, get_trading_dates=lambda *args: list(args)))
    with QmtInnerApi(client=client) as qmt:
        assert qmt.context.barpos == 8
        assert qmt.context.get_trading_dates('000001.SZ', '', '', 1) == ['000001.SZ', '', '', 1, '1d']
        assert qmt.market.get_trading_dates('000001.SZ', '20260101', '20261105', 10, '5m') == [
            '000001.SZ', '20260101', '20261105', 10, '5m']


def test_all_catalog_methods_are_discoverable():
    qmt = QmtInnerApi(client=Loopback())
    for category, name in INNER_METHODS:
        assert callable(getattr(getattr(qmt, category), name))
    qmt.close()


def test_sessions_close_only_their_own_resources():
    cancelled, ids = [], iter([10, 11])
    client = Loopback(SimpleNamespace(subscribe_whole_quote=lambda *args: next(ids),
                                     unsubscribe_quote=cancelled.append))
    first, second = QmtInnerApi(client=client), QmtInnerApi(client=client)
    first.market.subscribe_whole_quote(['SH'])
    second.market.subscribe_whole_quote(['SZ'])
    first.close()
    assert cancelled == [10]
    assert len(client.bridge._inner_api_sessions) == 1
    second.close()
    assert cancelled == [10, 11]


def test_cleanup_failure_can_be_retried_without_repeating_completed_cleanup():
    attempted, ids = [], iter([10, 11])
    def unsubscribe(sub_id):
        attempted.append(sub_id)
        if sub_id == 11 and attempted.count(11) == 1:
            raise RuntimeError('temporary cleanup failure')
    client = Loopback(SimpleNamespace(subscribe_whole_quote=lambda *args: next(ids),
                                     unsubscribe_quote=unsubscribe))
    qmt = QmtInnerApi(client=client)
    qmt.market.subscribe_whole_quote(['SH'])
    qmt.market.subscribe_whole_quote(['SZ'])
    with pytest.raises(CfquantError, match='cleanup failure'):
        qmt.close()
    qmt.close()
    assert attempted == [10, 11, 11]


def test_timer_group_cancellation_does_not_cancel_ids_again_on_close():
    cancelled = []
    def cancel(key):
        cancelled.append(key)
        return True
    client = Loopback(SimpleNamespace(schedule_run=lambda *args: 18, cancel_schedule_run=cancel))
    with QmtInnerApi(client=client) as qmt:
        qmt.system.schedule_run(lambda C: None, '20261105093000', name='group')
        qmt.system.cancel_schedule_run('group')
    assert cancelled == ['group']


def test_unregister_quote_releases_local_handler_and_named_callback_registration():
    client = Loopback(SimpleNamespace(subscribe_whole_quote=lambda *args: 4, unsubscribe_quote=lambda key: None))
    with QmtInnerApi(client=client) as qmt:
        sub = qmt.market.subscribe_whole_quote(['SH'], callback=print)
        assert len(qmt._handlers) == 1
        qmt.market.unsubscribe_quote(sub)
        assert not qmt._handlers
        qmt.callbacks.order_callback(lambda C, info: None)
        assert len(qmt._handlers) == 1


def test_owned_client_routes_to_normal_and_closes(monkeypatch):
    created = []
    client = Loopback()
    def create(**kwargs):
        created.append(kwargs)
        return client
    monkeypatch.setattr('cfquant.qmt_inner.create_rpc_client', create)
    with QmtInnerApi(bridge_id='office'):
        pass
    assert created[0]['request_channel'] == 'cfquant.office.normal.request'
    assert client.closed


def test_all_shared_bridge_dispatchers_reach_native_api():
    from cfquant.normal_bridge import NormalQmtBridge
    from cfquant.pipe_bridge import PipeNormalQmtBridge
    from cfquant.qmt_bridge import CfquantQmtBridge
    from cfquant.tx_trade_bridge import TxTradeBridge
    for cls in (NormalQmtBridge, PipeNormalQmtBridge, CfquantQmtBridge, TxTradeBridge):
        bridge = object.__new__(cls)
        bridge.context = SimpleNamespace(get_full_tick=lambda codes: {'codes': codes})
        bridge.globals_dict = {}
        result = bridge._dispatch('qmt_inner.call', dict(session_id='native-test',
            category='market', method='get_full_tick', args=[['000001.SZ']]), {'client_id': 'client'})
        assert result == {'codes': ['000001.SZ']}


def test_lite_runtime_is_self_contained_and_callbacks_are_instrumented():
    from tools.sync_qmt_inner import updated_source, embedded_runtime, ROOT
    namespace = {}
    exec(compile(embedded_runtime(), '<inner-runtime>', 'exec'), namespace)
    bridge = SimpleNamespace(context=SimpleNamespace(get_full_tick=lambda codes: codes), globals_dict={})
    assert namespace['dispatch_inner_api'](bridge, 'qmt_inner.call',
        dict(session_id='test', category='market', method='get_full_tick', args=[['000001.SZ']]),
        {'client_id': 'test'}) == ['000001.SZ']
    for path in (ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py'):
        source = path.read_text(encoding='gbk')
        assert updated_source(source, lite=True) == source
        tree = ast.parse(source, feature_version=(3, 6))
        callbacks = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'orderError_callback']
        assert len(callbacks) == 1
        assert callbacks[0].body[0].value.func.id == '_publish_inner_callback'
