"""Launch routing and hook ownership without starting any trading terminal."""
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from cfquant import qmt_vm_runtime as runtime, qmt_vm_worker as worker
from cfquant.qmt_vm_settings import normalize_qmt_vm_settings as normalize
from cfquant.tests.test_qmt_strategy_web import web_config


@pytest.mark.parametrize('vm,mac', [(False, False), (True, False), (False, True), (True, True)])
def test_launch_selects_only_requested_features(web_config, tmp_path, monkeypatch, vm, mac):
    web, _ = web_config
    settings = normalize({'disable_vm': vm, 'inject_mac': mac, 'mac_address': '02-AA-BB-CC-DD-EE'})
    calls = []
    paths = {'bin_dir': str(tmp_path), 'exe_path': str(tmp_path / 'XtItClient.exe'), 'qmt_vm': settings}
    monkeypatch.setattr(web.subprocess, 'Popen', lambda *a, **kw: calls.append(('plain', a, kw)) or SimpleNamespace(pid=10))
    monkeypatch.setattr(web, 'start_feature_process', lambda *a, **kw:
                        calls.append(('hooks', a, kw)) or {'qmt_pid': 11, 'launcher_pid': 12})
    monkeypatch.setattr(web, 'QMT_AUTO_LOGIN_RESTART_ARG', 'custom-restart')
    result = web._qmt_auto_login_start_xtitclient(paths, use_link=True)
    assert len(calls) == 1
    assert calls[0][0] == ('hooks' if vm or mac else 'plain')
    assert result['pid'] == (11 if vm or mac else 10)
    if vm or mac:
        assert result['launcher_pid'] == 12
        assert calls[0][1] == (str(tmp_path), settings)
        assert calls[0][2]['qmt_args'] == ['custom-restart']


def test_preflight_failure_does_not_stop_existing_terminal(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    monkeypatch.setenv('CFQUANT_QMT_AUTO_START', 'saved')
    monkeypatch.setattr(web, 'QMT_AUTO_LOGIN_STATE_FILE', str(tmp_path / 'state.json'))
    monkeypatch.setattr(web, '_qmt_auto_login_paths', lambda *a: {'bin_dir': str(tmp_path), 'exe_path': 'fixture'})
    monkeypatch.setattr(web, 'preflight_feature_process', lambda *a: (_ for _ in ()).throw(RuntimeError('discovery mismatch')))
    monkeypatch.setattr(web, '_qmt_auto_login_stop_xtitclient', lambda *a, **k: pytest.fail('must not stop existing QMT'))
    row = {'account_id': 'fixture', 'qmt_dir': str(tmp_path), 'qmt_vm': {'disable_vm': True},
           'qmt_auto_login': {'enabled': True, 'auto_fill_credentials': False}}
    result = web.qmt_auto_login_apply_for_account(row, restart=True)
    assert 'discovery mismatch' in result['error']
    assert not result['started']


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows launch preflight')
def test_mac_only_preflight_does_not_need_vm_predicates(monkeypatch, tmp_path):
    from cfquant import qmt_dependencies, qmt_vm_discovery
    monkeypatch.setattr(qmt_dependencies, 'import_login_module', lambda *a: None)
    monkeypatch.setattr(qmt_vm_discovery, 'inspect_client', lambda *a: pytest.fail('MAC-only must skip VM discovery'))
    (tmp_path / 'XtItClient.exe').touch()
    (tmp_path / 'utils.dll').touch()
    directory, settings, discovery = worker.prepare(tmp_path, {'inject_mac': True, 'mac_address': '02-AA-BB-CC-DD-EE'})
    assert discovery is None and not settings['disable_vm']
    assert directory == tmp_path


@pytest.mark.parametrize('vm,mac', [(True, False), (False, True), (True, True)])
def test_worker_installs_only_enabled_hooks(monkeypatch, tmp_path, vm, mac):
    calls = []
    settings = normalize({'disable_vm': vm, 'inject_mac': mac, 'mac_address': '02-AA-BB-CC-DD-EE'})
    api = SimpleNamespace(
        configuremac=lambda *a: calls.append(('mac', a)) or {'ready': True},
        initialize=lambda *a: calls.append(('vm', a)) or {'ready': True})
    script = SimpleNamespace(on=lambda *a: None, load=lambda: None, exports_sync=api)
    sources = []
    session = SimpleNamespace(create_script=lambda source: sources.append(source) or script)
    worker.install_hooks(session, tmp_path, settings, {'hooks': ['fixture']}, lambda *a: None)
    assert [call[0] for call in calls] == (['mac'] if mac else []) + (['vm'] if vm else [])
    assert ('function replaceGate' in sources[0]) == vm
    assert ('function rewriteMacList' in sources[0]) == mac


@pytest.mark.parametrize('failure', ['install', 'disconnect', 'success'])
def test_worker_owns_cleanup_of_only_its_child(monkeypatch, tmp_path, failure):
    calls, callbacks, replies = [], {}, []
    session = SimpleNamespace(on=lambda name, fn: callbacks.update({name: fn}), detach=lambda: calls.append('detach'))
    device = SimpleNamespace(spawn=lambda *a, **kw: 123, attach=lambda pid: session,
                             resume=lambda pid: calls.append(('resume', pid)), kill=lambda pid: calls.append(('kill', pid)))
    monkeypatch.setitem(sys.modules, 'frida', SimpleNamespace(get_local_device=lambda: device,
        ProcessNotFoundError=LookupError, InvalidOperationError=RuntimeError, TransportError=OSError))
    monkeypatch.setitem(sys.modules, 'win32api', SimpleNamespace(CloseHandle=lambda h: calls.append('close')))
    monkeypatch.setitem(sys.modules, 'win32event', SimpleNamespace(CreateMutex=lambda *a: 1,
        WaitForSingleObject=lambda *a: 0, ReleaseMutex=lambda h: calls.append('unlock')))
    monkeypatch.setattr(worker, 'ensure_stopped', lambda *a: None)
    def install(*a):
        if failure == 'install':
            raise RuntimeError('hook failed')
        return object()
    monkeypatch.setattr(worker, 'install_hooks', install)
    # The worker normally closes its protocol stream after commit.
    monkeypatch.setattr(worker, 'sys', SimpleNamespace(stdout=SimpleNamespace(close=lambda: callbacks['detached']())))
    commands = {name: threading.Event() for name in ('commit', 'cancel', 'received')}
    def reply(value):
        replies.append(value)
        if value['state'] == 'ready':
            commands['commit' if failure == 'success' else 'cancel'].set()
            commands['received'].set()
    if failure == 'success':
        worker.launch(tmp_path, normalize({'disable_vm': True}), {}, [], reply, commands)
        assert ('kill', 123) not in calls
        assert [p['state'] for p in replies] == ['ready', 'committed']
    else:
        with pytest.raises(RuntimeError):
            worker.launch(tmp_path, normalize({'disable_vm': True}), {}, [], reply, commands)
        assert ('kill', 123) in calls
    assert calls[-2:] == ['unlock', 'close']


def test_runtime_handshake_and_error_preserve_worker_reason(monkeypatch, tmp_path):
    script = tmp_path / 'fake_worker.py'
    script.write_text("import sys,json\nrequest=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'state':'ready','qmt_pid':678}),flush=True)\n"
        "assert sys.stdin.readline().strip()=='commit'\n"
        "print(json.dumps({'state':'committed'}),flush=True)\n", encoding='utf-8')
    monkeypatch.setattr(runtime, '_worker_command', lambda check=False: [sys.executable, '-B', str(script)])
    result = runtime.start_feature_process(tmp_path, {'disable_vm': True}, timeout=5)
    assert result['qmt_pid'] == 678 and result['launcher_pid'] > 0
    script.write_text("import sys,json\nsys.stdin.readline()\nprint(json.dumps({'error':'module mismatch'}),flush=True)\n", encoding='utf-8')
    with pytest.raises(RuntimeError, match='module mismatch'):
        runtime.start_feature_process(tmp_path, {'disable_vm': True}, timeout=5)


def test_handshake_timeout_closes_request_pipe_for_worker_cleanup(monkeypatch, tmp_path):
    marker = tmp_path / 'cancelled.txt'
    script = tmp_path / 'waiting_worker.py'
    script.write_text("import sys\nfrom pathlib import Path\nsys.stdin.readline()\n"
                      "assert sys.stdin.readline()==''\nPath(sys.argv[1]).write_text('cancelled')\n", encoding='utf-8')
    monkeypatch.setattr(runtime, '_worker_command', lambda check=False: [sys.executable, str(script), str(marker)])
    processes = []
    popen = runtime.subprocess.Popen
    def spawn(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    with pytest.raises(RuntimeError, match='超时'):
        runtime.start_feature_process(tmp_path, {'disable_vm': True}, timeout=0.2)
    assert processes[0].wait(timeout=5) == 0
    assert marker.read_text() == 'cancelled'


def test_windowless_web_uses_console_python_with_hidden_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.sys, 'executable', str(tmp_path / 'pythonw.exe'))
    assert Path(runtime._worker_command()[0]).name == 'python.exe'


@pytest.mark.parametrize('installer_started', [False, True])
def test_updater_restarts_through_hooks_even_if_installer_started_client(monkeypatch, tmp_path, installer_started):
    from cfquant import qmt_update as update
    calls = []
    exe = tmp_path / 'XtItClient.exe'
    def process(pid, created):
        return SimpleNamespace(pid=pid, info={'name': 'XtItClient.exe'}, exe=lambda: str(exe),
            create_time=lambda: created, terminate=lambda: calls.append(('stop', pid)), wait=lambda **kw: None)
    old, unsolicited, managed = process(10, 1), process(20, 2), process(30, 3)
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=lambda pid: {10: old, 30: managed}[pid],
        process_iter=lambda *a: [unsolicited if installer_started else old], NoSuchProcess=LookupError,
        AccessDenied=PermissionError, TimeoutExpired=TimeoutError))
    monkeypatch.setattr(update, 'NativeDialogs', lambda: None)
    monkeypatch.setattr(update.subprocess, 'Popen', lambda *a, **kw: pytest.fail('must use configured launch hooks'))
    processes = update.UpdateProcesses(tmp_path, 10, launch_client=lambda: calls.append('launch') or {'pid': 30})
    assert processes.restart() == 30
    assert calls == [('stop', 20 if installer_started else 10), 'launch']


def test_preflight_uses_private_temp_and_removes_files(monkeypatch, tmp_path):
    monkeypatch.setenv('CFQUANT_FRIDA_TEMP_DIR', str(tmp_path / 'frida'))
    directories = []
    def run(*args, **kwargs):
        directory = Path(kwargs['env']['TEMP'])
        assert kwargs['env']['TMP'] == str(directory)
        assert kwargs['env']['TMPDIR'] == str(directory)
        assert directory.parent == tmp_path / 'frida'
        (directory / 'frida-agent.dll').write_bytes(b'fixture')
        directories.append(directory)
        return SimpleNamespace(returncode=0, stdout='{"ready": true}')
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    assert runtime.preflight_feature_process(tmp_path, {'disable_vm': True}) == {'ready': True}
    assert directories and not directories[0].exists()


def test_launch_spawn_failure_removes_private_temp(monkeypatch, tmp_path):
    monkeypatch.setenv('CFQUANT_FRIDA_TEMP_DIR', str(tmp_path / 'frida'))
    def fail(*args, **kwargs):
        assert Path(kwargs['env']['TEMP']).is_dir()
        raise OSError('spawn failed')
    monkeypatch.setattr(runtime.subprocess, 'Popen', fail)
    with pytest.raises(OSError, match='spawn failed'):
        runtime.start_feature_process(tmp_path, {'disable_vm': True})
    assert list((tmp_path / 'frida').iterdir()) == []
