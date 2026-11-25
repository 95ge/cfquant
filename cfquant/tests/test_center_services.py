"""A owns services; blocked application work cannot occupy core dispatch pools."""
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import uuid

import pytest

from cfquant.bridge_center import BridgeCenter
from cfquant.center_services import RuntimeRpcServer, ServiceQueues
from cfquant.protocol import loads_message, pack_request
from cfquant.tests.test_bridge_center import broker, eventually


def test_notification_block_does_not_block_algorithms_or_core_control():
    center = BridgeCenter(SimpleNamespace())
    release, entered, notified = threading.Event(), threading.Event(), threading.Event()
    def handle(msg):
        if msg['action'] == 'cfquant.notify.send':
            entered.set()
            release.wait(3)
        else:
            notified.set()
    center.handle = handle
    errors = []
    try:
        center.enqueue(dict(client_id='same', action='cfquant.notify.send'), errors.append)
        assert entered.wait(1)
        for action in ('cfquant.ping', 'cftrader.calculate_position', 'xttrader.subscribe', 'xtdata.get_full_tick'):
            notified.clear()
            center.enqueue(dict(client_id='same', action=action), errors.append)
            assert notified.wait(1), action
        assert not errors
    finally:
        release.set()
        center.close()


def test_worker_account_ordering_limits_and_deadline():
    release, entered = threading.Event(), threading.Event()
    seen, sent = [], []
    def dispatch(action, params):
        seen.append(params['n'])
        if params['n'] == 1:
            entered.set()
            release.wait(3)
        return params['n']
    server = RuntimeRpcServer(dispatch, token='test-token')
    tx = SimpleNamespace(push=lambda key, raw, channel: sent.append(loads_message(raw)))
    server.tx = tx
    server.queues.lanes['algorithm'].max_pending = 1
    def message(n, timeout=2):
        return loads_message(pack_request('cftrader.calculate_position',
            dict(n=n, account_id='same', _center_service_token='test-token'), timeout=timeout, client_id=str(n)))
    try:
        server.enqueue(message(1), tx)
        assert entered.wait(1)
        server.enqueue(message(2, timeout=.01), tx)
        server.enqueue(message(3), tx)
        eventually(lambda: len(sent) == 1)
        assert not sent[0]['ok'] and 'full' in sent[0]['error']['message']
        time.sleep(.025)
        release.set()
        eventually(lambda: len(sent) == 3)
        assert seen == [1]  # Neither overflow nor expired writes may execute later.
        assert sum(not row['ok'] for row in sent) == 2
    finally:
        release.set()
        server.tx = None
        server.close()


def test_worker_rejects_unauthenticated_messages():
    sent = []
    server = RuntimeRpcServer(lambda *args: pytest.fail('unauthenticated request executed'), token='secret')
    tx = SimpleNamespace(push=lambda key, raw, channel: sent.append(loads_message(raw)))
    server.tx = tx
    try:
        server.enqueue(loads_message(pack_request('cfquant.notify.send', {}, client_id='bad')), tx)
        assert not sent[0]['ok']
    finally:
        server.tx = None
        server.close()


def test_readiness_requires_the_current_center_connection(tmp_path, monkeypatch):
    from cfquant.center_runtime import RuntimeServices
    ready = threading.Event()
    services = RuntimeServices.__new__(RuntimeServices)
    services.rpc = SimpleNamespace(connected=ready.is_set)
    path = tmp_path / 'status.json'
    monkeypatch.setenv('CFQUANT_PIPE_HUB_STATUS_FILE', str(path))
    monkeypatch.setenv('CFQUANT_CENTER_PARENT_PID', '123')
    ready.set()
    for pid, connected, expected in [(122, True, False), (123, False, False), (123, True, True)]:
        path.write_text(json.dumps(dict(pid=pid, running=True, center=dict(connected=connected))), encoding='utf-8')
        assert services.ready() is expected
    ready.clear()
    assert not services.ready()


def test_update_handoff_can_launch_a_release_without_center_modules(tmp_path):
    from cfquant import center_restart
    copied_helper = tmp_path / 'center_restart.py'
    copied_helper.write_text(Path(center_restart.__file__).read_text(encoding='utf-8'), encoding='utf-8')
    marker = tmp_path / 'started'
    legacy_entry = tmp_path / 'cfquant_web_server.py'
    legacy_entry.write_text('from pathlib import Path\nPath(%r).write_text("started")\n' % str(marker), encoding='utf-8')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    broker_script = tmp_path / 'LTtx_server.py'
    broker_script.write_text('import time\ntime.sleep(60)\n', encoding='ascii')
    broker_process = subprocess.Popen([sys.executable, str(broker_script)],
        env=dict(os.environ, CFQUANT_RUNTIME_DIR=str(tmp_path / 'runtime')), creationflags=flags)
    parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], creationflags=flags)
    helper = subprocess.Popen([sys.executable, str(copied_helper), str(legacy_entry)],
        env=dict(os.environ, CFQUANT_RESTART_PARENT_PID=str(parent.pid),
            CFQUANT_RESTART_LTTX_IDENTITIES=json.dumps(center_restart.owned_lttx_processes(tmp_path / 'runtime'))),
        creationflags=flags)
    try:
        assert not marker.exists()
        assert broker_process.poll() is None
        parent.terminate()
        parent.wait(timeout=5)
        assert helper.wait(timeout=10) == 0
        assert broker_process.wait(timeout=5) is not None
        assert marker.read_text() == 'started'
    finally:
        for process in (helper, parent, broker_process):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_update_stops_only_owned_lttx_and_checks_pid_creation(tmp_path):
    from cfquant.center_restart import owned_lttx_processes, stop_recorded_processes
    import psutil
    script = tmp_path / 'LTtx_server.py'
    script.write_text('import subprocess, sys, time\nfrom pathlib import Path\n'
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], '
        'creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))\n'
        'Path(sys.argv[1]).write_text(str(child.pid))\ntime.sleep(60)\n', encoding='ascii')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    own_runtime, other_runtime = tmp_path / 'own', tmp_path / 'other'
    own_runtime.mkdir()
    other_runtime.mkdir()
    processes = [subprocess.Popen([sys.executable, str(script), str(runtime / 'child.pid')],
        env=dict(os.environ, CFQUANT_RUNTIME_DIR=str(runtime)), creationflags=flags)
        for runtime in (own_runtime, other_runtime)]
    try:
        eventually(lambda: all((runtime / 'child.pid').is_file() for runtime in (own_runtime, other_runtime)))
        children = [psutil.Process(int((runtime / 'child.pid').read_text())) for runtime in (own_runtime, other_runtime)]
        identities = owned_lttx_processes(own_runtime)
        assert [row['pid'] for row in identities] == [processes[0].pid]
        stop_recorded_processes([dict(identities[0], created=identities[0]['created'] - 10)])
        assert processes[0].poll() is None
        stop_recorded_processes(identities)
        assert processes[0].wait(timeout=5) is not None
        children[0].wait(timeout=5)
        assert children[1].is_running()
        assert processes[1].poll() is None
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        for runtime in (own_runtime, other_runtime):
            marker = runtime / 'child.pid'
            if marker.is_file():
                try:
                    child = psutil.Process(int(marker.read_text()))
                    child.terminate()
                    child.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass


@pytest.mark.parametrize('actual_parent, same_runtime, allowed', [(123, True, True), (456, True, False), (123, False, False)])
def test_remote_stop_plan_includes_only_verified_center_parent(tmp_path, monkeypatch, actual_parent, same_runtime, allowed):
    from cfquant import remote_adapter as adapter
    runtime = str(tmp_path / 'runtime')
    web = SimpleNamespace(PROJECT_UPDATER=SimpleNamespace(is_busy=lambda: False),
                          RUNTIME_DIR=runtime, PIPE_HUB_ENTRY=str(tmp_path / 'hub.py'),
                          LTTX_ENTRY=str(tmp_path / 'broker.py'), PIPE_HUB_MODULE='cfquant_pipe_hub',
                          MANAGEMENT_BOOT_ID='test-boot')
    monkeypatch.setenv('CFQUANT_CENTER_PARENT_PID', '123')
    monkeypatch.setattr(adapter, 'require', lambda *args: None)
    monkeypatch.setattr(adapter, 'check_conflicts', lambda *args: None)
    monkeypatch.setattr(adapter, 'process_identity', lambda pid: dict(pid=pid, created=1))
    monkeypatch.setattr(adapter.psutil, 'process_iter', lambda *args: [])
    monkeypatch.setattr(adapter.psutil, 'Process', lambda pid: SimpleNamespace(
        ppid=lambda: actual_parent, environ=lambda: {'CFQUANT_RUNTIME_DIR': runtime if same_runtime else str(tmp_path / 'other')}))
    if allowed:
        plan = adapter.service_plan(web, 'test-boot')
        assert [row['pid'] for row in plan['processes']] == [os.getpid(), 123]
    else:
        with pytest.raises(adapter.RemoteError, match='父进程归属'):
            adapter.service_plan(web, 'test-boot')


@pytest.mark.skipif(os.name != 'nt', reason='Windows center')
@pytest.mark.parametrize('stop_mode', ['management', 'script'])
def test_headless_center_serves_application_rpc_without_web(broker, tmp_path, stop_mode):
    """Real A + owned worker + LTtx, empty bindings, no actual QMT or orders."""
    from cfquant.center_client import CenterRpcClient
    root = Path(__file__).resolve().parents[2]
    state = tmp_path / 'state'
    state.mkdir()
    temp = state / 'temp'
    temp.mkdir()
    config = state / 'web.json'
    config.write_text('{"account_configs": {}}', encoding='utf-8')
    management_key = state / 'management.key'
    management_key.write_text('headless-test-key', encoding='ascii')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        api_port = sock.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith('CFQUANT_')}
    env.update(CFQUANT_HOME=str(state), CFQUANT_RUNTIME_DIR=str(state / 'runtime'),
               CFQUANT_WEB_CONFIG_FILE=str(config), CFQUANT_WEB_SETTINGS_DB_FILE=str(state / 'web.db'),
               CFQUANT_LTTX_HOST='127.0.0.1', CFQUANT_LTTX_PORT=str(broker),
               CFQUANT_QMT_AUTO_START='0', CFQUANT_LOG_DIR=str(state / 'log'),
               CFQUANT_FRIDA_TEMP_DIR=str(temp / 'frida'), TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp),
               LOCALAPPDATA=str(state / 'localappdata'),
               CFQUANT_MANAGEMENT_TOKEN_FILE=str(management_key), CFQUANT_HTTP_WORKERS='2',
               PYTHONPATH=str(root), PYTHONIOENCODING='utf-8')
    command = [sys.executable, '-u', '-m', 'cfquant.center_runtime', '--no-web', '--host', '127.0.0.1',
               '--port', str(api_port), '--pipe-name', r'\\.\pipe\cfquant-headless-' + uuid.uuid4().hex]
    output = state / 'parent.log'
    rpc = CenterRpcClient(timeout=3)
    with output.open('wb') as log:
        process = subprocess.Popen(command, env=env, cwd=root, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic() + 35
        while True:
            if process.poll() is not None:
                pytest.fail(output.read_text(encoding='utf-8', errors='replace'))
            try:
                with urlopen('http://127.0.0.1:%s/api/health' % api_port, timeout=.5) as response:
                    assert response.status == 200
                    assert json.load(response)['data']['status'] == 'ok'
                break
            except Exception:
                if time.monotonic() > deadline:
                    logs = (state / 'log/center/services.log').read_text(encoding='utf-8', errors='replace')
                    pytest.fail(logs[-8000:])
                time.sleep(.1)
        with pytest.raises(HTTPError) as error:
            urlopen('http://127.0.0.1:%s/' % api_port, timeout=2)
        assert error.value.code == 404
        result = rpc.request('cftrader.calculate_position', dict(stock_code='600000.SH', entry_price=10,
            stop_price=9, method='risk_percent', total_asset=100000, risk_percent=.02, available_cash=100000))
        assert result['quantity'] == 1900
        assert rpc.request('cftrader.list_algos', dict(account_id='TEST')) == []
        # The task owner is the A-owned child, never a display process.
        with urlopen('http://127.0.0.1:%s/api/lttx' % api_port, timeout=3) as response:
            status = json.load(response)
        assert status['data']['application_queues']['connected']
        def api(path, body=None):
            request = Request('http://127.0.0.1:%s%s' % (api_port, path),
                              data=json.dumps(body).encode() if body is not None else None,
                              headers={'X-CFQuant-Management-Key': 'headless-test-key', 'Content-Type': 'application/json'})
            with urlopen(request, timeout=3) as response:
                return json.load(response)['data']
        before = api('/api/management/status')
        assert before['center_pid'] == process.pid and before['role'] == 'center_services'
        assert before['pid'] != process.pid and not before['web_display_enabled']
        slow = []
        try:
            for _ in range(2):
                sock = socket.create_connection(('127.0.0.1', api_port), timeout=2)
                sock.sendall(b'GET /api/health HTTP/1.1\r\n')
                slow.append(sock)
            time.sleep(.1)
            with pytest.raises(HTTPError) as full:
                urlopen('http://127.0.0.1:%s/api/health' % api_port, timeout=2)
            assert full.value.code == 503
            # Saturated HTTP/display clients do not occupy the LTtx service pool.
            assert rpc.request('cftrader.calculate_position', dict(stock_code='600000.SH', entry_price=10,
                stop_price=9, total_asset=100000, risk_percent=.02))['quantity'] == 1900
        finally:
            for sock in slow:
                sock.close()
        time.sleep(.1)
        api('/api/management/restart', {})
        def recovered():
            try:
                current = api('/api/management/status')
                return current['ready'] and current['boot_id'] != before['boot_id']
            except Exception:
                return False
        eventually(recovered, timeout=20)
        import psutil
        management_parent = psutil.Process(api('/api/management/status')['center_pid'])
        assert management_parent.pid != process.pid
        assert process.wait(timeout=15) == 0
        assert rpc.request('cftrader.list_algos', dict(account_id='TEST')) == []
        # Exercise the update handoff without installing a package or touching QMT.
        worker_pid = api('/api/management/status')['pid']
        restart_file = state / 'runtime/status/center-services-restart.json'
        restart_file.write_text(json.dumps(dict(parent_pid=management_parent.pid, restart_center=True,
            CFQUANT_WEB_HOST='127.0.0.1', CFQUANT_WEB_PORT=api_port, CFQUANT_QMT_AUTO_START='0')), encoding='utf-8')
        psutil.Process(worker_pid).terminate()
        management_parent.wait(timeout=15)
        new_center = []
        def handed_off():
            try:
                current = api('/api/management/status')
                if current['center_pid'] != management_parent.pid and current['ready']:
                    new_center.append(psutil.Process(current['center_pid']))
                    return True
            except Exception:
                pass
            return False
        eventually(handed_off, timeout=25)
        assert rpc.request('cftrader.list_algos', dict(account_id='TEST')) == []
        if stop_mode == 'management':
            api('/api/management/stop', {})
        else:
            # Run only the ownership-checked A subroutine, never broad legacy
            # script-name/port checks against the developer's other services.
            script = (root / 'stop_cfquant.bat').read_text(encoding='ascii')
            section = script.split('\n:stop_cfquant_center\n', 1)[1].split('\n:stop_python_script', 1)[0]
            line = next(line for line in section.splitlines() if line.startswith('powershell '))
            stop_command = line.split('-Command "', 1)[1][:-1]
            status_file = state / 'runtime/status/cfquant_pipe_hub_status.json'
            snapshot = json.loads(status_file.read_text(encoding='utf-8'))
            assert snapshot['pid'] == new_center[0].pid
            snapshot['process_created'] -= 10
            stale_file = state / 'stale-status.json'
            stale_file.write_text(json.dumps(snapshot), encoding='utf-8')
            command = ['powershell', '-NoProfile', '-NonInteractive', '-Command', stop_command]
            stale = subprocess.run(command, env=dict(env, CFQUANT_PIPE_HUB_STATUS_FILE=str(stale_file)),
                                   capture_output=True, timeout=15)
            assert stale.returncode == 0 and new_center[0].is_running(), stale.stdout
            assert b'PID was reused' in stale.stdout
            stopped = subprocess.run(command, env=env, capture_output=True, timeout=35)
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        new_center[0].wait(timeout=15)
    except BaseException:
        hub_status = state / 'runtime/status/cfquant_pipe_hub_status.json'
        if hub_status.exists():
            print(hub_status.read_text(encoding='utf-8'))
        service_log = state / 'log/center/services.log'
        if service_log.exists():
            print(service_log.read_text(encoding='utf-8', errors='replace')[-7000:])
        raise
    finally:
        rpc.close()
        # Handoff may have started a replacement A before an assertion failed.
        # Match the exact isolated state root; never stop a user's live center.
        import psutil
        owned = []
        for candidate in psutil.process_iter(['cmdline']):
            try:
                cmdline = ' '.join(candidate.info['cmdline'] or [])
                if any(name in cmdline for name in ('cfquant.center_runtime', 'center_restart.py', 'cfquant.runtime_services')):
                    if candidate.environ().get('CFQUANT_HOME') == str(state):
                        owned.append(candidate)
            except psutil.Error:
                pass
        for candidate in owned:
            try:
                candidate.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(owned, timeout=5)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        # Wait for the worker's parent watchdog before the broker fixture exits.
        time.sleep(1)


def test_display_listener_reload_does_not_restart_task_owner(monkeypatch):
    from cfquant import center_runtime
    calls = []
    runtime = SimpleNamespace(WEB_CONFIG=SimpleNamespace(allow_remote=lambda: False, web_port=lambda: 8765),
        normalize_web_port=lambda value, default: default, CfquantWebHandler=None,
        WEB_RESTART_LOCK=threading.Lock(), WEB_RESTART_REQUEST=None, safe_print=lambda text: None)
    class Services:
        def __init__(self, runtime):
            pass
        def start(self):
            calls.append('start tasks')
        def close(self):
            calls.append('stop tasks')
    class Server:
        def __init__(self, *args):
            calls.append('new listener')
        def serve_forever(self, **kwargs):
            assert calls.count('start tasks') == 1 and 'stop tasks' not in calls
            if calls.count('new listener') == 1:
                runtime.WEB_RESTART_REQUEST = dict(reason='settings')
        def shutdown(self):
            pass
        def server_close(self):
            calls.append('close listener')
    monkeypatch.setenv('CFQUANT_CENTER_PARENT_PID', str(os.getpid()))
    monkeypatch.setattr(center_runtime, 'RuntimeServices', Services)
    monkeypatch.setattr(center_runtime, 'BoundedHTTPServer', Server)
    assert center_runtime.worker_main(runtime) == 0
    assert calls.count('new listener') == 2
    assert calls.count('start tasks') == calls.count('stop tasks') == 1
