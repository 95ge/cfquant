"""Ordinary center/SDK lifecycle checks; no production accounts or services."""
import json
import os
from pathlib import Path
import threading

import pytest


def test_cli_settings_reach_center_and_child_environment(monkeypatch, tmp_path):
    from cfquant import cli, config, pipe_hub
    monkeypatch.setattr(config, '_config', dict(config._config, host='old-host', port=1))
    for key in ('CFQUANT_HOME', 'CFQUANT_RUNTIME_DIR', 'CFQUANT_PIPE_NAME',
                'CFQUANT_LTTX_HOST', 'CFQUANT_LTTX_PORT', 'CFQUANT_WEB_ENABLED'):
        monkeypatch.setenv(key, os.environ.get(key, ''))
    monkeypatch.setattr(cli, '_print_startup_banner', lambda args: None)
    observed = []
    def run(**kwargs):
        observed.append((kwargs, config.get_config(), dict(os.environ)))
    monkeypatch.setattr(pipe_hub, 'run_pipe_hub', run)
    channel = r'\\.\pipe\cfquant-test-config'
    cli.main(['center', '--home', str(tmp_path), '--lttx-host', 'new-host',
              '--lttx-port', '23456', '--pipe-name', channel, '--no-web'])
    args, cfg, env = observed[0]
    assert (cfg['host'], cfg['port']) == ('new-host', 23456)
    assert args['pipe_name'] == cfg['pipe_name'] == env['CFQUANT_PIPE_NAME'] == channel


def test_center_paths_are_absolute_before_worker_changes_directory(monkeypatch, tmp_path):
    from cfquant.center_services import configure_center_paths
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('CFQUANT_HOME', 'data')
    monkeypatch.setenv('CFQUANT_RUNTIME_DIR', 'custom-runtime')
    monkeypatch.setenv('CFQUANT_WEB_CONFIG_FILE', 'config.json')
    configure_center_paths()
    assert os.environ['CFQUANT_HOME'] == str(tmp_path / 'data')
    assert os.environ['CFQUANT_RUNTIME_DIR'] == str(tmp_path / 'custom-runtime')
    assert os.environ['CFQUANT_WEB_CONFIG_FILE'] == str(tmp_path / 'config.json')


def test_rejected_duplicate_does_not_overwrite_active_center_status(monkeypatch, tmp_path):
    from cfquant.bridge_center import BridgeCenter
    from cfquant.pipe_hub import CfquantPipeHub
    status = tmp_path / 'status.json'
    original = json.dumps({'pid': 999, 'running': True})
    status.write_text(original, encoding='utf-8')
    monkeypatch.setenv('CFQUANT_PIPE_HUB_STATUS_FILE', str(status))
    def reject(self):
        raise RuntimeError('another bridge center already owns this LTtx endpoint')
    monkeypatch.setattr(BridgeCenter, 'start', reject)
    import uuid
    hub = CfquantPipeHub(pipe_name=r'\\.\pipe\cfquant-rejected-' + uuid.uuid4().hex, show=False)
    try:
        with pytest.raises(RuntimeError, match='another bridge center'):
            hub.start()
    finally:
        hub.close()
    assert status.read_text(encoding='utf-8') == original


@pytest.mark.skipif(os.name != 'nt', reason='Windows QMT pipes')
def test_pipe_ownership_is_exclusive_even_with_another_lttx_endpoint(monkeypatch):
    import uuid
    from cfquant import config
    from cfquant.bridge_center import BridgeCenter, _CenterGuard
    from cfquant.pipe_hub import CfquantPipeHub
    name = r'\\.\pipe\cfquant-exclusive-' + uuid.uuid4().hex
    guard = _CenterGuard(identity='pipe:' + name.lower())
    guard.acquire()
    hub = CfquantPipeHub(pipe_name=name.upper(), show=False)
    monkeypatch.setattr(config, '_config', dict(config._config, port=65432))
    monkeypatch.setattr(BridgeCenter, 'start', lambda self: pytest.fail('second center reached LTtx startup'))
    try:
        with pytest.raises(RuntimeError, match='QMT named pipe'):
            hub.start()
    finally:
        hub.close()
        guard.close()


def test_sdk_close_can_cancel_account_channel_startup(monkeypatch):
    from cfquant import center_client
    from cfquant.client import WebLttxRpcClient
    from cfquant.market_channel import ChannelSubscription
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    errors = []
    class Tx:
        def start_txg(self, channel):
            entered.set()
            release.wait(5)
        def close(self):
            release.set()
    monkeypatch.setattr(center_client, 'ChannelSubscription',
        lambda *a, **k: ChannelSubscription(*a, **k, factory=lambda *a, **k: Tx()))
    monkeypatch.setattr(WebLttxRpcClient, 'request', lambda *a, **k:
        {'mode': 'ctypes', 'event_channel': 'cfquant.account.test'})
    client = center_client.CenterRpcClient()
    def subscribe():
        try:
            client.request('xttrader.subscribe', {'account_id': 'TEST'})
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=subscribe, daemon=True)
    closer = threading.Thread(target=lambda: (client.close(), closed.set()), daemon=True)
    try:
        thread.start()
        assert entered.wait(1)
        closer.start()
        assert closed.wait(1), 'close is blocked behind the subscription startup lock'
        thread.join(timeout=1)
        assert errors and not thread.is_alive()
    finally:
        release.set()
        thread.join(timeout=2)
        closer.join(timeout=2)
        client.close()


def test_service_health_tracks_connection_loss_even_with_startup_ready_flag():
    from types import SimpleNamespace
    from cfquant.center_services import RuntimeRpcServer, SERVICE_CHANNEL
    server = RuntimeRpcServer(lambda *args: None, token='test')
    server.ready.set()
    server.tx = SimpleNamespace(tx_running=True, txg_dict={SERVICE_CHANNEL: {'txg_running': True}}, close=lambda: None)
    try:
        assert server.status()['connected']
        server.tx.txg_dict[SERVICE_CHANNEL]['txg_running'] = False
        assert not server.status()['connected']
        server.tx.txg_dict[SERVICE_CHANNEL]['txg_running'] = True
        server.tx.tx_running = False
        assert not server.status()['connected']
    finally:
        server.close()


def test_worker_recovery_reuses_last_bound_listener_not_stale_parent_env(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from cfquant import center_runtime
    from cfquant.center_services import ServiceSupervisor
    monkeypatch.setenv('CFQUANT_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setenv('CFQUANT_WEB_HOST', '127.0.0.1')
    monkeypatch.setenv('CFQUANT_WEB_PORT', '12000')
    supervisor = ServiceSupervisor(SimpleNamespace())
    monkeypatch.setenv('CFQUANT_CENTER_PARENT_PID', str(os.getpid()))
    monkeypatch.setenv('CFQUANT_CENTER_PARENT_CREATED', str(supervisor.parent_created))
    runtime = SimpleNamespace(WEB_CONFIG=SimpleNamespace(allow_remote=lambda: False, web_port=lambda: 12000),
        normalize_web_port=lambda value, default: int(value or default), CfquantWebHandler=None,
        WEB_RESTART_LOCK=threading.Lock(), WEB_RESTART_REQUEST=None, safe_print=lambda text: None)
    bindings = []
    class Server:
        def __init__(self, address, handler):
            bindings.append(address)
        def serve_forever(self, **kwargs):
            if len(bindings) == 1:
                runtime.WEB_RESTART_REQUEST = dict(reason='settings', host='127.0.0.1', port=13000)
        def shutdown(self):
            pass
        def server_close(self):
            pass
    monkeypatch.setattr(center_runtime, 'BoundedHTTPServer', Server)
    monkeypatch.setattr(center_runtime, 'RuntimeServices', lambda r: SimpleNamespace(start=lambda: None, close=lambda: None))
    assert center_runtime.worker_main(runtime) == 0
    assert bindings == [('127.0.0.1', 12000), ('127.0.0.1', 13000)]
    assert supervisor._worker_environment()['CFQUANT_WEB_PORT'] == '13000'
    # A later center must ignore an earlier process's listener record.
    supervisor.parent_created += 1
    assert supervisor._worker_environment()['CFQUANT_WEB_PORT'] == '12000'


def test_parent_death_cancels_worker_blocked_during_startup(tmp_path):
    import subprocess
    import sys
    import time
    import psutil
    marker = tmp_path / 'startup-entered'
    code = '''
import os, threading, time
from pathlib import Path
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler
from cfquant import center_runtime
class Services:
    def __init__(self, runtime): pass
    def start(self):
        Path(os.environ['TEST_STARTUP_MARKER']).write_text('started')
        time.sleep(60)
    def close(self): pass
center_runtime.RuntimeServices = Services
runtime = SimpleNamespace(WEB_CONFIG=SimpleNamespace(allow_remote=lambda:False, web_port=lambda:0),
    normalize_web_port=lambda value, default:0, CfquantWebHandler=BaseHTTPRequestHandler,
    WEB_RESTART_LOCK=threading.Lock(), WEB_RESTART_REQUEST=None, safe_print=lambda text:None)
center_runtime.worker_main(runtime)
'''
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], creationflags=flags)
    worker = subprocess.Popen([sys.executable, '-c', code], creationflags=flags,
        env=dict(os.environ, CFQUANT_CENTER_PARENT_PID=str(parent.pid),
            CFQUANT_CENTER_PARENT_CREATED=str(psutil.Process(parent.pid).create_time()),
            CFQUANT_RUNTIME_DIR=str(tmp_path / 'runtime'), TEST_STARTUP_MARKER=str(marker)))
    try:
        deadline = time.monotonic() + 8
        while not marker.exists():
            assert worker.poll() is None and time.monotonic() < deadline
            time.sleep(.05)
        parent.terminate()
        parent.wait(timeout=5)
        assert worker.wait(timeout=9) == 0
    finally:
        for process in (worker, parent):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


@pytest.mark.parametrize('preserve, explicit_policy, expected', [
    (True, False, []), (True, True, ['apply startup policy']),
    (False, False, ['deploy', 'refresh strategies', 'apply startup policy']),
])
def test_explicit_qmt_start_policy_is_applied_without_redeploying_running_qmt(
        monkeypatch, preserve, explicit_policy, expected):
    from types import SimpleNamespace
    from cfquant.center_runtime import RuntimeServices
    calls = []
    services = RuntimeServices.__new__(RuntimeServices)
    services.runtime = SimpleNamespace(BASE_DIR='test',
        auto_deploy_qmt_core_for_all_accounts=lambda **kwargs: calls.append('deploy'),
        refresh_bound_qmt_strategies=lambda **kwargs: calls.append('refresh strategies') or [],
        start_configured_qmt_on_web_startup=lambda: calls.append('apply startup policy'))
    monkeypatch.setenv('CFQUANT_REMOTE_PRESERVE_QMT', str(int(preserve)))
    monkeypatch.setenv('CFQUANT_CENTER_APPLY_QMT_START_POLICY', str(int(explicit_policy)))
    services.prepare_qmt()
    assert calls == expected
