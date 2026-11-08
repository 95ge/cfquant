"""Persistent telemetry tests using synthetic callbacks and isolated databases only."""
import copy
import sqlite3
import threading
import time
from datetime import datetime

import pytest

from cfquant.trading_monitor import TradingMonitor, SHANGHAI, day_text, is_trading_time


NOW = datetime(2026, 11, 3, 10, 0, tzinfo=SHANGHAI).timestamp()


def callback(kind='order', order_id=1, **fields):
    event = {'event': 'trader:on_stock_' + kind, 'bridge_id': 'qmt-one', 'account_id': 'paper',
             'account_type': 'STOCK', 'received_at': NOW - 2,
             'data': {'account_id': 'paper', 'order_id': order_id, 'stock_code': '000001.SZ',
                      'order_status': 50, 'order_date': '20261103', 'trade_date': '20261103'}}
    event['data'].update(fields)
    return event


def bound_accounts():
    return [dict(account_key=f'{bridge}:{kind}:paper', account_id='paper', account_type=kind,
                 bridge_id=bridge, bridge_ids=[bridge, 'qmt-sh'] if bridge == 'qmt-one' and kind == 'STOCK' else [bridge],
                 display_name=name, binding_enabled=True)
            for bridge, kind, name in [('qmt-one', 'STOCK', '主账号'), ('qmt-one', 'CREDIT', '信用账号'),
                                       ('qmt-two', 'STOCK', '第二部署')]]


@pytest.fixture
def monitor(tmp_path):
    instance = TradingMonitor(tmp_path / 'monitor.sqlite3')
    instance.start()
    yield instance
    instance.close()
    assert not instance._thread.is_alive()


def snapshot(monitor, **kwargs):
    assert monitor.flush(), monitor.health()
    return monitor.query('2026-11-03', '2026-11-03', now=NOW, **kwargs)


def test_duplicate_callbacks_restart_partial_fills_cancels_and_out_of_order(monitor):
    pending = callback(order_status=52, traded_volume=10)
    for event in [callback(), pending, pending, callback(order_status=53, traded_volume=10), callback()]:
        monitor.record_callback(event)
    trade = callback('trade', traded_id='fill-1', traded_volume=10, traded_amount=123.4)
    monitor.record_callback(trade)
    monitor.record_callback(dict(trade, received_at=NOW, client_id='duplicate-route'))
    result = snapshot(monitor)
    assert result['stats']['order_count'] == 1
    assert result['stats']['filled_order_count'] == 1
    assert result['stats']['canceled_count'] == 1
    assert result['stats']['trade_count'] == 1
    assert result['stats']['traded_amount'] == 123.4
    assert result['stats']['fill_ratio'] == result['stats']['cancel_ratio'] == result['stats']['report_cancel_ratio'] == 1
    assert result['stats']['order_rate'] == result['stats']['trade_rate'] == 1 / 60
    assert result['series'][0]['orders'] == result['series'][0]['trades'] == result['series'][0]['cancels'] == 1
    monitor.close()
    monitor.start()
    monitor.record_callback(trade)
    monitor.record_callback(pending)
    assert snapshot(monitor)['stats'] == result['stats']


def test_pending_cancel_is_not_canceled_and_zero_denominators(monitor):
    monitor.record_callback(callback(order_status=52))
    result = snapshot(monitor)
    assert result['stats']['canceled_count'] == 0
    assert result['stats']['report_cancel_ratio'] is None
    empty = snapshot(monitor, account_id='unknown')
    assert empty['stats']['fill_ratio'] is None
    assert empty['stats']['latency'] == {'count': 0, 'avg_ms': None, 'max_ms': None, 'p95_ms': None}


def test_date_bridge_account_type_isolation_and_business_day(monitor):
    for day, bridge, account_type in [('20261103','qmt-one','STOCK'), ('20261102','qmt-one','STOCK'),
                                     ('20261103','qmt-two','STOCK'), ('20261103','qmt-one','CREDIT')]:
        event = callback(order_date=day)
        event.update(bridge_id=bridge, account_type=account_type)
        monitor.record_callback(event)
    result = snapshot(monitor)
    assert result['stats']['order_count'] == 3
    assert snapshot(monitor, bridge_id='qmt-one', account_type='STOCK')['stats']['order_count'] == 1
    yesterday = monitor.query('2026-11-02', '2026-11-02', now=NOW)
    assert yesterday['stats']['order_count'] == 1
    assert yesterday['stats']['order_rate'] is None
    assert yesterday['series'] == []  # A replay received today must not create a fabricated historical rate.
    assert not yesterday['live']
    assert day_text(datetime(2026, 11, 2, 16, 0, tzinfo=__import__('datetime').timezone.utc).timestamp()) == '2026-11-03'


def test_error_events_unknown_ids_pagination_and_sql_parameters(monitor):
    monitor.record_callback(callback(order_status=57, status_msg='<script>alert(1)</script>'))
    event = callback()
    event['event'] = 'trader:on_cancel_error'
    event['data']['error_msg'] = 'cancel rejected'
    for _ in range(2):
        monitor.record_callback(event)
    for idx in range(60):
        monitor.record_callback(callback(order_id=100 + idx))
    result = snapshot(monitor, kind='abnormal')
    assert result['total'] == 2
    assert result['stats']['abnormal_count'] == 2
    assert snapshot(monitor, page=2)['events']
    assert len(snapshot(monitor)['events']) == 50
    assert snapshot(monitor, account_id="' OR 1=1--")['total'] == 0
    for start, end in [('2026-11-04','2026-11-03'), ('2026-01-01','2026-11-03'), ('bad','2026-11-03')]:
        with pytest.raises(ValueError):
            monitor.query(start, end)


def test_request_latency_percentiles_and_native_failure(monitor, monkeypatch):
    monkeypatch.setattr('cfquant.trading_monitor.time.time', lambda: NOW)
    for i in range(1, 21):
        monitor.record_request('qmt-one','xttrader.order_stock', {'account': {'account_id':'paper','account_type':'STOCK'}}, i, result=i)
    monitor.record_request('qmt-one','xttrader.cancel_order_stock', {'account_id':'paper'}, 100, result=-1)
    monitor.record_request('qmt-one','xtdata.get_full_tick', {}, 9999, result={})
    result = snapshot(monitor)
    assert result['stats']['request_count'] == 21
    assert result['stats']['failed_request_count'] == 1
    assert result['stats']['cancel_request_count'] == 1
    assert result['stats']['order_count'] == 0  # Requests are not confirmed orders.
    assert result['stats']['latency'] == {'count':21, 'avg_ms':310/21, 'max_ms':100, 'p95_ms':20}


def test_nodes_history_staleness_and_pipe_has_no_synthetic_latency(monitor):
    row = {'bridge_id':'qmt-one','bridge_name':'测试部署','checked_at':NOW-40,
           'monitor':{'transport_mode':'ctypes','interval_seconds':10},
           'normal':{'online':True,'latency_ms':0}, 'trade':{'online':False,'error':'offline'}}
    monitor.record_snapshot(row)
    result = snapshot(monitor)
    assert len(result['nodes']) == 2
    assert all(node['stale'] and node['latency_ms'] is None for node in result['nodes'])
    row = copy.deepcopy(row)
    row.update(checked_at=NOW-1)
    row['normal']['online'] = False
    monitor.record_snapshot(row)
    nodes = snapshot(monitor)['nodes']
    assert len(nodes) == 2 and all(not node['stale'] for node in nodes)
    historical = monitor.query('2026-11-03','2026-11-03', now=NOW+86400)
    assert not historical['live'] and all(not node['stale'] for node in historical['nodes'])


def test_concurrent_callbacks_and_shutdown_flush(monitor):
    threads = [threading.Thread(target=lambda: [monitor.record_callback(callback(order_id=i)) for i in range(1, 101)]) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    monitor.close()
    assert monitor.query('2026-11-03','2026-11-03', now=NOW)['stats']['order_count'] == 100
    assert monitor.health()['pending'] == 0


def test_locked_database_does_not_block_callback_and_recovers(monitor):
    monitor.record_callback(callback())
    snapshot(monitor)
    with sqlite3.connect(str(monitor.path)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        before = time.monotonic()
        monitor.record_callback(callback(order_id=2))
        assert time.monotonic() - before < .2
        lock.rollback()
    assert snapshot(monitor)['stats']['order_count'] == 2


def test_web_request_wrapper_preserves_return_error_and_no_retries(monkeypatch, monitor):
    import cfquant_web_server as web
    monkeypatch.setattr(web, 'TRADING_MONITOR', monitor)
    client = web.GlobalTxClient()
    calls = []
    def fake(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return 123
        raise TimeoutError('ambiguous submission')
    monkeypatch.setattr(client, '_request', fake)
    assert client.request('qmt-one', 'trade', 'xttrader.order_stock', {'account_id':'paper'}) == 123
    with pytest.raises(TimeoutError, match='ambiguous submission'):
        client.request('qmt-one', 'trade', 'xttrader.order_stock', {'account_id':'paper'})
    assert len(calls) == 2
    assert monitor.flush()
    result = monitor.query()
    assert result['stats']['request_count'] == 2
    assert result['stats']['failed_request_count'] == 1


def test_web_callback_integration(monkeypatch, monitor):
    import cfquant_web_server as web
    from types import SimpleNamespace
    monkeypatch.setattr(web, 'TRADING_MONITOR', monitor)
    monkeypatch.setattr(web, 'ACCOUNT_CACHE', SimpleNamespace(update_from_event=lambda event: None))
    monkeypatch.setattr(web, 'WS_CALLBACKS', SimpleNamespace(broadcast=lambda event: None))
    store = web.CallbackEventStore()
    store._append(callback())
    assert snapshot(monitor)['stats']['order_count'] == 1


def test_runtime_samples_are_minute_deduplicated_and_collect_all_hours(monitor):
    assert is_trading_time(NOW)
    assert not is_trading_time(datetime(2026, 11, 3, 20, 0, tzinfo=SHANGHAI).timestamp())
    performance = {'available': True, 'qmt_callback_total': 12,
                   'quote_callback_batches': 4, 'quote_distribution_batches': 3,
                   'request_completed': 2, 'process': {'pid': 123, 'cpu_percent': 7.5}}
    monitor.record_snapshot({'bridge_id': 'qmt-one', 'bridge_name': '主账号',
                            'checked_at': NOW, 'monitor': {'transport_mode': 'ctypes'},
                            'normal': {'online': True, 'performance': performance},
                            'trade': {'online': True, 'performance': performance}})
    monitor.record_snapshot({'bridge_id': 'qmt-one', 'bridge_name': '主账号',
                            'checked_at': NOW + 20, 'monitor': {'transport_mode': 'ctypes'},
                            'normal': {'online': True, 'performance': dict(performance, qmt_callback_total=13)},
                            'trade': {'online': True, 'performance': performance}})
    monitor.record_snapshot({'bridge_id': 'qmt-one', 'checked_at': datetime(2026, 11, 3, 20, 0, tzinfo=SHANGHAI).timestamp(),
                            'monitor': {'transport_mode': 'ctypes'}, 'normal': {'online': True}, 'trade': {'online': True}})
    assert monitor.flush()
    result = monitor.query_runtime('2026-11-03', '2026-11-03', bridge_id='qmt-one', now=NOW)
    assert len(result['samples']) == 2
    assert result['samples'][0]['normal']['qmt_callback_total'] == 13
    assert result['samples'][0]['process']['normal']['pid'] == 123
    assert result['samples'][1]['normal'] == {}


def test_runtime_retention_setting_and_cleanup(tmp_path):
    instance = TradingMonitor(tmp_path / 'runtime.sqlite3')
    instance.configure(False, runtime_retention_days=2)
    assert instance.settings()['runtime_retention_days'] == 2
    conn = instance._connect()
    try:
        conn.execute("INSERT INTO monitor_runtime_samples VALUES (?,?,?,?,?,?,?,?,?)",
                     ('old', NOW - 4 * 86400, int(NOW // 60) * 60, 'qmt-one', '', 'ctypes', '{}', '{}', '{}'))
        conn.commit()
        instance._last_runtime_cleanup = 0
        instance._cleanup_runtime_samples(conn, force=True)
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM monitor_runtime_samples").fetchone()[0] == 0
    finally:
        conn.close()
        instance.close()


def test_runtime_all_history_query_and_manual_cleanup(tmp_path):
    instance = TradingMonitor(tmp_path / 'runtime-all.sqlite3')
    instance.configure(False, runtime_retention_days=0)
    conn = instance._connect()
    try:
        rows = [
            ('old', NOW - 400 * 86400, int((NOW - 400 * 86400) // 60) * 60,
             'qmt-one', '', 'ctypes', '{}', '{}', '{}'),
            ('new', NOW - 2 * 86400, int((NOW - 2 * 86400) // 60) * 60,
             'qmt-one', '', 'ctypes', '{}', '{}', '{}'),
            ('lite', NOW - 1 * 86400, int((NOW - 1 * 86400) // 60) * 60,
             'qmt-one', '', 'lite', '{}', '{}', '{}'),
        ]
        conn.executemany("INSERT INTO monitor_runtime_samples VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    try:
        result = instance.query_runtime('all', '2026-11-03', bridge_id='qmt-one', now=NOW)
        assert result['retention_days'] == 0 and len(result['samples']) == 3
        assert result['mode'] == ''
        assert len(instance.query_runtime('all', '2026-11-03', bridge_id='qmt-one', mode='ctypes', now=NOW)['samples']) == 2
        assert len(instance.query_runtime('all', '2026-11-03', bridge_id='qmt-one', mode='lite', now=NOW)['samples']) == 1
        expired = instance.clear_runtime_history('expired')
        assert expired['deleted'] == 0 and expired['remaining'] == 3
        cleared = instance.clear_runtime_history('all')
        assert cleared['deleted'] == 3 and cleared['remaining'] == 0
    finally:
        instance.close()


@pytest.mark.parametrize('trade_first', [False, True])
def test_fill_ratio_uses_trade_callbacks_even_before_order(monitor, trade_first):
    order = callback()
    trade = callback('trade', traded_id='fill-a', traded_volume=100)
    for event in ([trade, order] if trade_first else [order, trade]):
        monitor.record_callback(event)
    assert snapshot(monitor)['stats']['fill_ratio'] == 1


def test_malformed_callback_does_not_drop_adjacent_events(monitor):
    monitor.record_callback(callback())
    malformed = callback(order_id=2)
    malformed['meta'] = 17
    malformed['bridge_id'] = ''
    monitor.record_callback(malformed)
    monitor.record_callback(callback(order_id=3))
    result = snapshot(monitor)
    assert result['stats']['order_count'] == 2
    assert result['collector']['dropped'] == 1


def test_monitor_endpoint_requires_authorization_and_validates_filters(monkeypatch, monitor):
    import cfquant_web_server as web
    from urllib.parse import urlparse
    monkeypatch.setattr(web, 'TRADING_MONITOR', monitor)
    monitor.record_callback(callback())
    snapshot(monitor)
    handler = object.__new__(web.CfquantWebHandler)
    written = []
    handler._write_json = lambda payload, status=200: written.append((status, payload))
    handler._authorized = lambda parsed: False
    handler._handle_api_get(urlparse('/api/monitor?start=2026-11-03&end=2026-11-03'))
    assert written[-1][0] == 401
    handler._authorized = lambda parsed: True
    handler._handle_api_get(urlparse('/api/monitor?start=2026-11-03&end=2026-11-03&bridge_id=qmt-one'))
    assert written[-1][0] == 200
    assert written[-1][1]['data']['stats']['order_count'] == 1
    handler._handle_api_get(urlparse('/api/monitor?start=not-a-date'))
    assert written[-1][0] == 400
    handler._handle_api_get(urlparse('/api/monitor/runtime?start=2026-11-03&end=2026-11-03&bridge_id=qmt-one'))
    assert written[-1][0] == 200
    assert 'samples' in written[-1][1]['data']


def test_full_queue_reports_loss_without_blocking(monitor, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = monitor._write_callback
    def slow(conn, *args):
        entered.set()
        assert release.wait(4)
        original(conn, *args)
    monkeypatch.setattr(monitor, '_write_callback', slow)
    monitor._queue.maxsize = 1
    try:
        monitor.record_callback(callback())
        assert entered.wait(3)
        monitor.record_callback(callback(order_id=2))
        monitor.record_callback(callback(order_id=3))
        assert monitor.health()['dropped'] == 1
    finally:
        release.set()
    assert snapshot(monitor)['stats']['order_count'] == 2


def test_transient_write_failure_retries_without_double_counting(monitor, monkeypatch):
    original = monitor._write_callback
    calls = []
    def transient(conn, *args):
        original(conn, *args)
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError('synthetic transient lock')
    monkeypatch.setattr(monitor, '_write_callback', transient)
    monitor.record_callback(callback())
    monitor.record_callback(callback(order_id=2))
    result = snapshot(monitor)
    assert len(calls) >= 3
    assert result['stats']['order_count'] == result['total'] == 2
    assert result['collector']['error'] == ''
    assert result['collector']['dropped'] == 0


@pytest.mark.parametrize('native,failed', [
    ({'cancel_result':-1,'request_result':False,'order_id':123}, True),
    ({'seq':-1,'accepted':False}, True),
    ({'request_result':False,'order_id':-1}, True),
    ({'failed':1,'total':3,'results':[]}, True),
    ({'request_result':0,'order_id':-1}, False),  # Accepted; order ID is not resolved yet.
    ({'cancel_result':0,'request_result':True}, False),
])
def test_qmt_response_failure_contracts(monitor, native, failed):
    monitor.record_request('qmt-one', 'xttrader.order_stock', {'account_id':'paper'}, 10, result=native)
    assert monitor.flush()
    assert monitor.query()['stats']['failed_request_count'] == int(failed)


def test_default_off_query_does_not_create_database_or_worker(tmp_path):
    instance = TradingMonitor(tmp_path / 'never-created.sqlite3')
    assert not instance.restore()['enabled']
    instance.record_callback(callback())
    instance.record_request('one', 'xttrader.order_stock', {}, 1, result=123)
    instance.record_snapshot({'bridge_id':'one'})
    data = instance.query(now=NOW)
    assert not data['collector']['enabled'] and not data['collector']['running']
    assert instance._thread is None and data['collector']['pending'] == 0
    assert data['stats']['order_count'] == 0 and data['stats']['order_rate'] is None
    assert not instance.path.exists() and not instance.settings_path.exists()


def test_enable_disable_persistence_history_and_reenable(tmp_path):
    path = tmp_path / 'monitor.sqlite3'
    instance = TradingMonitor(path)
    try:
        assert instance.configure(True)['enabled']
        instance.record_callback(callback())
        assert instance.flush()
        instance.close()  # Normal service shutdown must not change the user's saved choice.
        instance = TradingMonitor(path)
        assert instance.restore()['enabled']
        assert instance.query(now=NOW)['stats']['order_count'] == 1
        assert not instance.configure(False)['enabled']
        instance.record_callback(callback(order_id=2))
        assert not instance.health()['pending']
        data = instance.query(now=NOW)
        assert data['stats']['order_count'] == 1 and data['stats']['order_rate'] is None
        instance = TradingMonitor(path)
        assert not instance.restore()['enabled']
        assert instance._thread is None
        instance.configure(True)
        instance.record_callback(callback(order_id=2))
        assert instance.flush()
        assert instance.query(now=NOW)['stats']['order_count'] == 2
    finally:
        instance.close()


@pytest.mark.parametrize('value', ['true', 'false', 1, 0, None])
def test_enable_rejects_non_boolean_and_corrupt_settings_fail_closed(tmp_path, value):
    import json
    instance = TradingMonitor(tmp_path / 'off.sqlite3')
    with pytest.raises(ValueError):
        instance.configure(value)
    instance.settings_path.write_text(json.dumps({'enabled':value}), encoding='utf-8')
    assert not instance.restore()['enabled']
    assert instance.health()['error']
    assert not instance.path.exists()


def test_settings_save_error_keeps_previous_state(monitor, monkeypatch):
    def denied(*args):
        raise PermissionError('synthetic denied')
    monkeypatch.setattr('cfquant.trading_monitor.os.replace', denied)
    with pytest.raises(PermissionError):
        monitor.configure(False)
    assert monitor.enabled and monitor.health()['running']
    assert not list(monitor.settings_path.parent.glob('.monitor-*.tmp'))


def test_disabled_request_bypasses_monitor_work(monkeypatch, tmp_path):
    import cfquant_web_server as web
    instance = TradingMonitor(tmp_path / 'off.sqlite3')
    monkeypatch.setattr(web, 'TRADING_MONITOR', instance)
    monkeypatch.setattr(instance, 'record_request', lambda *a, **kw: pytest.fail('disabled collector invoked'))
    monkeypatch.setattr(web, '_external_account_id', lambda *a: pytest.fail('monitor account parsing invoked'))
    client = web.GlobalTxClient()
    monkeypatch.setattr(client, '_request', lambda *a, **kw: 123)
    assert client.request('one', 'trade', 'xttrader.order_stock', {'account_id':'paper'}) == 123
    assert not instance.path.exists()


def test_settings_http_authentication_validation_and_toggle(monkeypatch, tmp_path):
    import cfquant_web_server as web
    instance = TradingMonitor(tmp_path / 'endpoint.sqlite3')
    monkeypatch.setattr(web, 'TRADING_MONITOR', instance)
    handler = object.__new__(web.CfquantWebHandler)
    written = []
    handler.path = '/api/monitor/settings'
    handler._request_allowed = lambda: True
    handler._authorized = lambda parsed: False
    handler._read_json_body = lambda: {'enabled':True}
    handler._write_json = lambda payload, status=200: written.append((status, payload))
    try:
        handler.do_POST()
        assert written[-1][0] == 401 and not instance.enabled
        handler._authorized = lambda parsed: True
        handler.do_POST()
        assert written[-1][0] == 200 and instance.enabled
        handler._read_json_body = lambda: {'enabled':'false'}
        handler.do_POST()
        assert written[-1][0] == 400 and instance.enabled
        handler._read_json_body = lambda: {'enabled':False}
        handler.do_POST()
        assert written[-1][0] == 200 and not instance.enabled
        handler.path = '/api/monitor/runtime/cleanup'
        handler._authorized = lambda parsed: False
        handler._read_json_body = lambda: {'scope':'all'}
        handler.do_POST()
        assert written[-1][0] == 401
        handler._authorized = lambda parsed: True
        handler._read_json_body = lambda: []
        handler.do_POST()
        assert written[-1][0] == 400
        handler._read_json_body = lambda: {'scope':'invalid'}
        handler.do_POST()
        assert written[-1][0] == 400
        handler._read_json_body = lambda: {'scope':'all'}
        handler.do_POST()
        assert written[-1][0] == 200
        assert written[-1][1]['data']['scope'] == 'all'
    finally:
        instance.close()


def test_scope_filters_callbacks_requests_and_related_nodes_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr('cfquant.trading_monitor.time.time', lambda: NOW)
    instance = TradingMonitor(tmp_path / 'scope.sqlite3')
    accounts = bound_accounts()
    instance.update_accounts(accounts)
    try:
        instance.configure(True, [accounts[0]['account_key']])
        for i, (bridge, kind, account) in enumerate([
            ('qmt-one','STOCK','paper'), ('qmt-sh','STOCK','paper'),
            ('qmt-one','CREDIT','paper'), ('qmt-two','STOCK','paper'),
            ('qmt-one','STOCK','unbound'), ('qmt-one','','paper')]):
            event = dict(callback(order_id=i + 1), bridge_id=bridge, account_type=kind, account_id=account)
            instance.record_callback(event)
            instance.record_callback(dict(event, event='trader:on_order_error'))
            instance.record_callback(dict(event, event='trader:on_stock_trade', data=dict(event['data'], traded_id=str(i))))
            instance.record_request(bridge, 'xttrader.order_stock', {'account_id':account,'account_type':kind}, 2)
            instance.record_request(bridge, 'xttrader.cancel_order_stock', {'account_id':account,'account_type':kind}, 3)
            instance.record_snapshot({'bridge_id':bridge, 'checked_at':NOW, 'normal':{'online':True}})
        result = snapshot(instance)
        assert result['stats']['order_count'] == result['stats']['trade_count'] == 2
        assert result['stats']['error_count'] == 2
        assert result['stats']['request_count'] == 4
        assert {row['bridge_id'] for row in result['nodes']} == {'qmt-one','qmt-sh'}
        assert {row['account_type'] for row in result['events']} == {'STOCK'}
        instance.close()
        instance = TradingMonitor(instance.path)
        instance.update_accounts(accounts)
        assert instance.restore()['account_keys'] == [accounts[0]['account_key']]
        instance.record_callback(dict(callback(order_id=50), bridge_id='qmt-two'))
        assert snapshot(instance)['stats']['order_count'] == 2
        instance.configure(False)  # Omitted scope preserves user's selection.
        assert instance.settings()['account_keys'] == [accounts[0]['account_key']]
    finally:
        instance.close()


def test_all_scope_tracks_binding_additions_and_removals_without_restarting(monitor):
    accounts = bound_accounts()
    monitor.update_accounts(accounts[:1])
    assert monitor.health()['account_keys'] is None
    monitor.record_callback(dict(callback(order_id=1), bridge_id='qmt-two'))
    monitor.update_accounts(accounts)
    monitor.record_callback(dict(callback(order_id=2), bridge_id='qmt-two'))
    monitor.update_accounts(accounts[:1])
    monitor.record_callback(dict(callback(order_id=3), bridge_id='qmt-two'))
    assert snapshot(monitor)['stats']['order_count'] == 1
    monitor.configure(True, [accounts[0]['account_key']])
    monitor.update_accounts(accounts[1:])
    monitor.record_callback(callback(order_id=4))
    monitor.record_callback(dict(callback(order_id=5), bridge_id='qmt-two'))
    assert snapshot(monitor)['stats']['order_count'] == 1  # Never silently fall back to all.


@pytest.mark.parametrize('keys', ['all', [12], [''], {}, [], ['unknown']])
def test_invalid_scope_is_rejected_without_changing_state(monitor, keys):
    monitor.update_accounts(bound_accounts())
    with pytest.raises(ValueError):
        monitor.configure(True, keys)
    assert monitor.enabled and monitor.account_keys is None
    assert not monitor.settings_path.exists()


def test_scope_corruption_does_not_enable_collector(tmp_path):
    import json
    instance = TradingMonitor(tmp_path / 'scope.sqlite3')
    instance.settings_path.write_text(json.dumps({'enabled':True, 'account_keys':'all'}), encoding='utf-8')
    assert not instance.restore()['enabled']
    assert not instance.path.exists()


def test_web_binding_scope_normalizes_types_routes_and_updates_on_save(monkeypatch, tmp_path):
    import cfquant_web_server as web
    instance = TradingMonitor(tmp_path / 'scope.sqlite3', account_type_normalizer=web.normalize_account_type)
    config = web.WebRuntimeConfig(str(tmp_path / 'web.json'), settings_db_path=str(tmp_path / 'settings.sqlite3'))
    monkeypatch.setattr(web, 'TRADING_MONITOR', instance)
    monkeypatch.setattr(web, 'WEB_CONFIG', config)
    rows = bound_accounts()
    binding = dict(rows[0], market_routing_enabled=True, market_bridges={'SH':{'bridge_id':'qmt-sh'}, 'SZ':{'bridge_id':'qmt-sz'}},
                   qmt_dir='SENSITIVE_PATH', password='SENSITIVE_SECRET')
    try:
        with config._lock:
            config._data['account_configs'] = {binding['account_key']:binding}
            config._save_locked()
        settings = instance.settings()
        assert len(settings['accounts']) == 1
        assert 'SENSITIVE' not in str(settings)
        assert 'qmt-sh' in settings['accounts'][0]['bridge_ids']
        instance.configure(True)
        instance.record_callback(dict(callback(), account_type=2, bridge_id='qmt-sh'))
        instance.record_request('qmt-sh', 'xttrader.order_stock', {'account_id':'paper', 'account_type':2}, 2)
        assert snapshot(instance)['stats']['order_count'] == 1
        assert snapshot(instance)['events'][0]['account_type'] == 'STOCK'
        with config._lock:
            config._data['account_configs'] = {}
            config._save_locked()
        instance.record_callback(callback(order_id=2))
        assert snapshot(instance)['stats']['order_count'] == 1
    finally:
        instance.close()


def test_removed_nodes_keep_history_but_no_longer_report_live_collection(monitor):
    accounts = bound_accounts()
    monitor.update_accounts(accounts)
    monitor.record_snapshot({'bridge_id':'qmt-two', 'checked_at':NOW - 60})
    assert snapshot(monitor)['nodes'][0]['collecting']
    monitor.configure(True, [accounts[0]['account_key']])
    assert not snapshot(monitor)['nodes'][0]['collecting']


def test_settings_api_validates_bound_keys_and_roundtrips_selected_scope(monkeypatch, tmp_path):
    import cfquant_web_server as web
    instance = TradingMonitor(tmp_path / 'scope-http.sqlite3')
    monkeypatch.setattr(web, 'TRADING_MONITOR', instance)
    monkeypatch.setattr(web, 'refresh_monitor_accounts', lambda: instance.update_accounts(bound_accounts()))
    handler = object.__new__(web.CfquantWebHandler)
    written = []
    handler.path = '/api/monitor/settings'
    handler._request_allowed = lambda: True
    handler._authorized = lambda parsed: True
    handler._write_json = lambda payload, status=200: written.append((status, payload))
    try:
        keys = [bound_accounts()[1]['account_key']]
        handler._read_json_body = lambda: {'enabled':True, 'account_keys':keys}
        handler.do_POST()
        assert written[-1][0] == 200
        assert written[-1][1]['data']['account_keys'] == keys
        assert len(written[-1][1]['data']['accounts']) == 3
        handler._read_json_body = lambda: {'enabled':True, 'account_keys':['unbound']}
        handler.do_POST()
        assert written[-1][0] == 400 and instance.account_keys == keys
        handler._read_json_body = lambda: {'enabled':True, 'account_keys':None}
        handler.do_POST()
        assert written[-1][0] == 200 and instance.account_keys is None
        handler._read_json_body = lambda: {'enabled':True, 'runtime_retention_days':7}
        handler.do_POST()
        assert written[-1][0] == 200 and written[-1][1]['data']['runtime_retention_days'] == 7
    finally:
        instance.close()
