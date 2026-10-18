"""Management SDK and real HTTP handlers; QMT and release downloads are mocked."""

import json
import os
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace
from http.server import ThreadingHTTPServer

import pytest

from cfquant.management import ManagementError, RuntimeManager
from cfquant.tests.test_qmt_strategy_web import login_credentials


@pytest.fixture
def service(tmp_path, monkeypatch):
    import cfquant_web_server as web
    root = tmp_path / 'service'
    root.mkdir()
    key = tmp_path / 'management.key'
    key.write_text('test-management-key', encoding='ascii')
    monkeypatch.setenv('CFQUANT_MANAGEMENT_TOKEN_FILE', str(key))
    # The restart handler changes this environment variable in the server thread.
    monkeypatch.setenv('CFQUANT_QMT_AUTO_START', 'saved')
    config = web.WebRuntimeConfig(str(tmp_path / 'config.json'), str(tmp_path / 'settings.db'))
    monkeypatch.setattr(web, 'WEB_CONFIG', config)
    monkeypatch.setattr(web, 'STATE_DIR', str(tmp_path))
    monkeypatch.setattr(web, 'BASE_DIR', str(root))
    monkeypatch.setattr(web, 'MANAGEMENT_READY', True)
    monkeypatch.setattr(web, 'MANAGEMENT_BOOT_ID', 'first-boot')
    monkeypatch.setattr(web, '_RUNNING_FROM_SOURCE', True)
    monkeypatch.setattr(web, 'PROJECT_UPDATER', web.CfquantProjectUpdater())
    monkeypatch.setattr(web, 'PROJECT_UPDATE_DIR', str(tmp_path / 'updates'))
    monkeypatch.setattr(web, 'qmt_process_snapshots_for_request', lambda **kwargs: [])
    monkeypatch.setattr(web, 'auto_deploy_qmt_core_for_account', lambda *a, **k: {'summary': {'ok': True}})
    monkeypatch.setattr(web, 'write_qmt_bridge_identity', lambda row: {'written': True})
    monkeypatch.setattr(web, 'write_qmt_market_bridge_identities', lambda row: [])
    monkeypatch.setattr(web, 'configure_account_qmt_strategies', lambda *a: {})
    monkeypatch.setattr(web, 'ensure_account_runtime', lambda mode: {'mode': mode})
    monkeypatch.setattr(web.ACCOUNT_CACHE, 'prime_configured_accounts', lambda: None)
    monkeypatch.setattr(web.STATUS_MONITOR, 'wake', lambda: None)
    monkeypatch.setattr(web.CALLBACKS, 'refresh_channels', lambda channels: None)
    launches = []
    monkeypatch.setattr(web, 'qmt_auto_login_apply_for_account',
                        lambda row, request=None, **kwargs: launches.append(request) or {'enabled': (request or {}).get('enabled', False)})
    server = ThreadingHTTPServer(('127.0.0.1', 0), web.CfquantWebHandler)
    monkeypatch.setattr(web, 'WEB_BOUND_HOST', '127.0.0.1')
    monkeypatch.setattr(web, 'WEB_BOUND_PORT', server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime = RuntimeManager(tmp_path, port=server.server_port)
    try:
        yield SimpleNamespace(web=web, config=config, runtime=runtime, root=root,
                              key=key, launches=launches, server=server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('auto_start', [True, False])
def test_initialize_and_repeat_binding_over_http(service, tmp_path, auto_start, login_credentials):
    runtime = service.runtime
    kwargs = dict(account_type='CREDIT', auto_start_qmt=auto_start, live=False)
    if auto_start:
        kwargs['qmt_auto_login'] = dict(login_credentials)
    result = runtime.initialize('TEST_ONLY', str(tmp_path / 'qmt'), **kwargs)
    assert result['initialized']
    assert result['setup']['setup_required'] is False
    assert service.launches == [dict(login_credentials, enabled=True) if auto_start else {'enabled': False}]
    binding = result['account']
    assert binding['qmt_strategy']['autorun'] is True
    assert binding['qmt_strategy']['live'] is False
    if auto_start:
        kwargs['qmt_auto_login'].pop('password')
    assert runtime.initialize('TEST_ONLY', str(tmp_path / 'qmt'), **kwargs)['unchanged']
    assert len(service.launches) == 1
    assert len(runtime.accounts.list()) == 1


def test_management_requires_credential_and_checks_instance(service, tmp_path):
    with pytest.raises(ManagementError) as error:
        RuntimeManager(base_url=service.runtime.base_url).status()
    assert error.value.code == 'authentication_failed'
    other = RuntimeManager(tmp_path / 'other', port=service.server.server_port,
                           api_key='test-api-key')
    service.config.set_api_key('test-api-key')
    with pytest.raises(ManagementError, match='another cfquant'):
        other.status()
    assert RuntimeManager(base_url=service.runtime.base_url, api_key='test-api-key').status()['api_version'] == 1


def test_running_qmt_returns_structured_error_without_mutation(service, monkeypatch, tmp_path):
    monkeypatch.setattr(service.web, 'qmt_process_snapshots_for_request',
                        lambda **k: [{'running': True, 'qmt_dir': 'test', 'pids': [999]}])
    with pytest.raises(ManagementError) as error:
        service.runtime.initialize('TEST_ONLY', str(tmp_path / 'qmt'))
    assert error.value.code == 'qmt_running'
    assert error.value.status == 409
    assert service.runtime.accounts.list() == {}


def test_wait_ready_does_not_confuse_service_health_with_qmt(service, monkeypatch):
    binding = dict(account_id='TEST_ONLY', account_type='STOCK', bridge_id='test', enabled=True,
                   status={'ready': False})
    monkeypatch.setattr(service.web, 'binding_status_snapshot', lambda: {'bindings': [binding]})
    with pytest.raises(ManagementError) as error:
        service.runtime.wait_ready('TEST_ONLY', timeout=0.1)
    assert error.value.code == 'qmt_not_ready'
    binding['status']['ready'] = True
    assert service.runtime.wait_ready('TEST_ONLY', timeout=1)['status']['ready']


def test_restart_waits_for_new_boot_and_preserves_listener(service, monkeypatch):
    requests = []
    def restart(server, info):
        requests.append(info)
        service.web.MANAGEMENT_BOOT_ID = 'new-boot'
    monkeypatch.setattr(service.web, 'schedule_web_reload', restart)
    result = service.runtime.restart(auto_start_qmt=False, timeout=2)
    assert result['boot_id'] == 'new-boot'
    assert result['auto_start_qmt'] is False
    assert requests[0]['port'] == service.server.server_port


def test_update_and_rollback_over_http(service, monkeypatch):
    web = service.web
    calls = []
    monkeypatch.setattr(web.PROJECT_UPDATER, 'update_from_official',
                        lambda **kwargs: calls.append(kwargs) or {'updated': True, 'update_completed': True})
    monkeypatch.setattr(web, 'schedule_web_reload', lambda *a: setattr(web, 'MANAGEMENT_BOOT_ID', 'updated-boot'))
    result = service.runtime.updates.apply()
    assert result['updated'] and result['service']['boot_id'] == 'updated-boot'
    assert calls[0]['site_url'] == web.DEFAULT_OFFICIAL_SITE_URL
    monkeypatch.setattr(web.PROJECT_UPDATER, 'rollback', lambda backup: {'restored_backup': backup})
    assert service.runtime.updates.rollback('backup-123', restart=False)['restored_backup'] == 'backup-123'


@pytest.mark.parametrize('installed, available', [('', True), ('old', True), ('new', False)])
def test_check_detects_same_version_updates(service, monkeypatch, installed, available):
    status = {'current_version': '0.2.45', 'version_info': {'update_available': False,
              'remote': {'version': '0.2.45', 'sha256': 'new'}},
              'last_update': {'source': {'fetch': {'sha256': installed}}}}
    monkeypatch.setattr(service.web, 'project_update_status', lambda **kw: status)
    assert service.runtime.updates.check()['available'] is available


def test_stop_is_authenticated_and_stops_only_http_service(service):
    assert service.runtime.stop()['stopping']


def test_install_uses_separate_source_and_excludes_runtime_data(tmp_path):
    runtime = RuntimeManager(tmp_path / 'app state')
    result = runtime.ensure_installed()
    assert result['created']
    assert (runtime.project_dir / 'cfquant/management.py').is_file()
    assert (runtime.project_dir / 'web_dashboard/index.html').is_file()
    assert not (runtime.project_dir / 'log').exists()
    assert not list(runtime.project_dir.rglob('*.env'))
    assert not list(runtime.project_dir.rglob('*.db'))
    assert not runtime.ensure_installed()['created']


def test_hidden_start_isolates_env_and_reports_early_exit(tmp_path, monkeypatch):
    runtime = RuntimeManager(tmp_path)
    monkeypatch.setattr(runtime, 'ensure_installed', lambda: None)
    monkeypatch.setattr(runtime, '_listening', lambda: False)
    monkeypatch.setenv('CFQUANT_WEB_CONFIG_FILE', 'must-not-inherit')
    monkeypatch.setenv('PYTHONPATH', 'must-not-inherit')
    calls = []
    def launch(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(poll=lambda: 1, returncode=1)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    with pytest.raises(ManagementError) as error:
        runtime.start(auto_start_qmt=False)
    assert error.value.code == 'service_exited'
    env = calls[0][1]['env']
    assert 'PYTHONPATH' not in env and 'CFQUANT_WEB_CONFIG_FILE' not in env
    assert env['CFQUANT_QMT_AUTO_START'] == '0'
    assert env['CFQUANT_MANAGEMENT_TOKEN_FILE'] == str(tmp_path / 'management.key')
    if os.name == 'nt':
        assert calls[0][1]['creationflags'] & subprocess.CREATE_NO_WINDOW


@pytest.mark.parametrize('policy, expected', [('0', 0), ('1', 1), ('saved', 0)])
def test_startup_qmt_override(service, monkeypatch, policy, expected):
    monkeypatch.setenv('CFQUANT_QMT_AUTO_START', policy)
    service.config._data['account_configs'] = {'one': {'account_id': 'TEST_ONLY', 'enabled': True,
        'qmt_dir': 'test', 'qmt_auto_login': {'enabled': False}}}
    assert len(service.web.start_configured_qmt_on_web_startup()) == expected


def test_managed_install_rejects_release_without_management_before_copy(service, tmp_path):
    source = tmp_path / 'old-release'
    (source / 'cfquant').mkdir(parents=True)
    (source / 'web_dashboard').mkdir()
    (source / 'cfquant/__init__.py').write_text('')
    (source / 'cfquant_web_server.py').write_text('old server')
    (source / 'web_dashboard/index.html').write_text('old')
    with pytest.raises(RuntimeError, match='does not support the management API'):
        service.web.PROJECT_UPDATER._install_source(str(source), {})
    assert not (service.root / 'cfquant_web_server.py').exists()


def test_update_and_rollback_replace_only_service_files(service, monkeypatch, tmp_path):
    web = service.web
    source = tmp_path / 'new-release'
    for root, version in ((service.root, '1.0.0'), (source, '2.0.0')):
        (root / 'cfquant').mkdir(parents=True)
        (root / 'web_dashboard').mkdir()
        (root / 'cfquant/__init__.py').write_text("__version__ = %r\n" % version)
        (root / 'cfquant/version.py').write_text("__version__ = %r\n" % version)
        (root / 'cfquant/management.py').write_text('# management SDK\n')
        (root / 'cfquant_web_server.py').write_text('def management_status(): pass\n# ' + version)
        (root / 'web_dashboard/index.html').write_text(version)
    (source / 'new_module.py').write_text('NEW = True\n')
    (service.root / 'runtime').mkdir()
    private_state = service.root / 'runtime/config.json'
    private_state.write_text('{"keep": true}')
    sdk_file = Path(__import__('cfquant.management', fromlist=['x']).__file__)
    original_sdk = sdk_file.read_bytes()
    downloads = []
    def fetch(site_url, destination):
        import shutil
        downloads.append(site_url)
        shutil.copytree(source, destination)
        return {'sha256': 'new-hash'}
    monkeypatch.setattr(web.UPDATER, '_fetch_official_package', fetch)
    monkeypatch.setattr(web, 'auto_deploy_qmt_core_for_all_accounts',
                        lambda **kw: {'summary': {'ok': True, 'target_count': 0}})
    monkeypatch.setattr(web, 'CORE_VERSION_PATH', str(service.root / 'cfquant/version.py'))
    monkeypatch.setattr(web, 'CORE_VERSION', '1.0.0')
    monkeypatch.setattr(web, '_remote_project_version_info',
                        lambda **kw: {'version': '2.0.0', 'sha256': 'new-hash'})
    conditional = service.runtime.updates.ensure_latest(restart=False)
    assert conditional['status'] == 'updated'
    result = conditional['update']
    assert result['current_version'] == '2.0.0'
    assert result['update_completed']
    assert web.PROJECT_UPDATER._read_install_meta()['source']['fetch']['sha256'] == 'new-hash'
    assert web.PROJECT_UPDATER._read_install_meta()['qmt_core_deploy']['summary']['ok'] is True
    assert service.runtime.updates.ensure_latest(restart=False)['status'] == 'restart_required'
    # Model a new process after the installation receipt was written.
    monkeypatch.setattr(web, 'CORE_VERSION', '2.0.0')
    monkeypatch.setattr(web, 'MANAGEMENT_STARTED_AT', web.PROJECT_UPDATER._read_install_meta()['updated_at'] + 1)
    assert service.runtime.updates.ensure_latest()['status'] == 'up_to_date'
    assert len(downloads) == 1
    restored = service.runtime.updates.rollback(result['backup']['name'], restart=False)
    assert restored['current_version'] == '1.0.0'
    assert not (service.root / 'new_module.py').exists()
    assert private_state.read_text() == '{"keep": true}'
    assert sdk_file.read_bytes() == original_sdk


@pytest.mark.parametrize('action', ['stop', 'restart'])
def test_lifecycle_rejects_active_update(service, action):
    with service.web.PROJECT_UPDATER._operation('update'):
        with pytest.raises(ManagementError) as error:
            getattr(service.runtime, action)()
    assert error.value.status == 409
    assert error.value.code == 'project_update_busy'


def test_failed_remote_check_is_not_reported_as_up_to_date(service, monkeypatch):
    monkeypatch.setattr(service.web, 'project_update_status', lambda **kw: {
        'version_info': {'update_available': False, 'remote': {'error': 'offline'}}})
    result = service.runtime.updates.check()
    assert result['available'] is None
    assert result['remote']['error'] == 'offline'


def test_no_auto_start_blocks_qmt_launch_and_scheduled_restart(monkeypatch):
    import cfquant_web_server as web
    monkeypatch.setenv('CFQUANT_QMT_AUTO_START', '0')
    monkeypatch.setattr(web, '_qmt_auto_login_update_session', lambda *a: None)
    monkeypatch.setattr(web, '_qmt_auto_login_paths', lambda *a: pytest.fail('Must not access QMT'))
    monkeypatch.setattr(web, 'qmt_auto_login_restart_for_account', lambda *a, **k: pytest.fail('Must not restart QMT'))
    result = web.qmt_auto_login_apply_for_account(
        {'qmt_auto_login': {'enabled': True}}, restart=True)
    assert not result['enabled'] and not result['started'] and not result['restarted']
    assert web.QmtAutoLoginRestartScheduler().run_pending() == []


@pytest.mark.parametrize('flag, expected', [('--auto-start-qmt', '1'), ('--no-auto-start-qmt', '0')])
def test_cli_applies_qmt_startup_policy(monkeypatch, flag, expected):
    from cfquant import cli
    monkeypatch.setenv('CFQUANT_QMT_AUTO_START', 'saved')
    args = cli._serve_parser().parse_args([flag])
    cli._apply_web_environment(args)
    assert os.environ['CFQUANT_QMT_AUTO_START'] == expected


@pytest.mark.parametrize('operation', ['apply', 'rollback', 'ensure_latest'])
def test_updates_reject_truthy_strings_that_could_close_qmt(tmp_path, operation):
    updates = RuntimeManager(tmp_path).updates
    arguments = {'backup': 'test'} if operation == 'rollback' else {}
    with pytest.raises(ValueError, match='must be bools'):
        getattr(updates, operation)(auto_close_qmt='false', **arguments)


@pytest.fixture
def release_state(service, monkeypatch):
    state = {'current_version': '0.2.45', 'version_info': {
        'imported_core_version': '0.2.45', 'core_comparison': 'same',
        'remote': {'version': '0.2.45', 'sha256': 'same-hash'}},
        'last_update': {'source': {'fetch': {'sha256': 'same-hash'}}}}
    def status(**kwargs):
        assert kwargs['force'] is True
        return state
    monkeypatch.setattr(service.web.PROJECT_UPDATER, 'status', status)
    return state


def test_ensure_latest_does_nothing_when_latest_even_with_qmt_running(service, release_state, monkeypatch):
    monkeypatch.setattr(service.web, 'qmt_update_preflight', lambda **k: pytest.fail('No QMT side effects'))
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official', lambda: pytest.fail('No download'))
    monkeypatch.setattr(service.web, 'schedule_web_reload', lambda *a: pytest.fail('No restart'))
    result = service.runtime.updates.ensure_latest(auto_close_qmt=True)
    assert result['status'] == 'up_to_date'
    assert result['updated'] is False
    assert result['current_version'] == result['latest_version'] == '0.2.45'
    assert service.web.PROJECT_UPDATER.operation_status()['busy'] is False


@pytest.mark.parametrize('kind', ['new_version', 'same_version_patch', 'unknown_hash', 'partial_deploy'])
def test_ensure_latest_applies_when_needed_and_restarts(service, release_state, monkeypatch, kind):
    state = release_state
    if kind == 'new_version':
        state['version_info']['core_comparison'] = 'newer'
        state['version_info']['remote']['version'] = '0.2.46'
    elif kind == 'same_version_patch':
        state['version_info']['remote']['sha256'] = 'new-hash'
    elif kind == 'unknown_hash':
        state['last_update'] = {}
    else:
        state['last_update']['qmt_core_deploy'] = {'summary': {'ok': False}}
    calls = []
    def install():
        assert service.web.PROJECT_UPDATER.is_busy()
        calls.append('install')
        return {'updated': True, 'update_completed': True,
                'current_version': state['version_info']['remote']['version']}
    monkeypatch.setattr(service.web, 'qmt_update_preflight', lambda **kw: calls.append(kw['body']))
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official', install)
    monkeypatch.setattr(service.web, 'schedule_web_reload', lambda *a: setattr(service.web, 'MANAGEMENT_BOOT_ID', 'after-update'))
    result = service.runtime.updates.ensure_latest(auto_close_qmt=True)
    assert result['status'] == 'updated' and result['updated'] is True
    assert result['service']['boot_id'] == 'after-update'
    assert not result['restart_required']
    assert calls == [{'auto_close_qmt': True}, 'install']


def test_ensure_latest_can_leave_restart_to_caller(service, release_state, monkeypatch):
    release_state['version_info']['remote']['sha256'] = 'new-hash'
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official',
                        lambda: {'current_version': '0.2.45', 'update_completed': True})
    monkeypatch.setattr(service.web, 'schedule_web_reload', lambda *a: pytest.fail('Caller disabled restart'))
    result = service.runtime.updates.ensure_latest(restart=False)
    assert result['status'] == 'updated'
    assert result['restart_required'] is True


@pytest.mark.parametrize('reason', ['offline', 'missing_version', 'incomparable'])
def test_ensure_latest_does_not_claim_latest_when_check_fails(service, release_state, monkeypatch, reason):
    if reason == 'offline':
        release_state['version_info']['remote']['error'] = 'offline'
    elif reason == 'missing_version':
        release_state['version_info']['remote']['version'] = ''
    else:
        release_state['version_info']['core_comparison'] = 'different'
    monkeypatch.setattr(service.web, 'qmt_update_preflight', lambda **k: pytest.fail('No QMT mutation'))
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official', lambda: pytest.fail('No download'))
    result = service.runtime.updates.ensure_latest()
    assert result['status'] == 'check_failed'
    assert result['updated'] is False
    assert result['check']['available'] is None


def test_ensure_latest_never_downgrades_for_different_hash(service, release_state, monkeypatch):
    release_state['version_info'].update(core_comparison='older', remote={'version': '0.2.44', 'sha256': 'older-hash'})
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official', lambda: pytest.fail('No downgrade'))
    result = service.runtime.updates.ensure_latest()
    assert result['status'] == 'local_newer'
    assert result['updated'] is False


def test_ensure_latest_reports_partial_deployment(service, release_state, monkeypatch):
    release_state['version_info']['remote']['sha256'] = 'new-hash'
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official',
                        lambda: {'update_completed': False, 'qmt_core_deploy': {'summary': {'ok': False}}})
    result = service.runtime.updates.ensure_latest(restart=False)
    assert result['status'] == 'update_incomplete'
    assert result['updated'] is True
    assert result['update']['qmt_core_deploy']['summary']['ok'] is False


def test_ensure_latest_restarts_pending_install_without_downloading(service, release_state, monkeypatch):
    release_state['version_info']['restart_required'] = True
    # Running Web code can lag behind files already installed on disk.
    release_state['version_info'].update(web_comparison='newer', installed_web_comparison='same')
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official', lambda: pytest.fail('Already installed'))
    assert service.runtime.updates.ensure_latest(restart=False)['status'] == 'restart_required'
    monkeypatch.setattr(service.web, 'schedule_web_reload', lambda *a: setattr(service.web, 'MANAGEMENT_BOOT_ID', 'new-boot'))
    result = service.runtime.updates.ensure_latest()
    assert result['status'] == 'up_to_date'
    assert result['updated'] is False and result['restart_required'] is False
    assert result['service']['boot_id'] == 'new-boot'


def test_ensure_latest_enforces_qmt_preflight_and_update_lock(service, release_state, monkeypatch):
    release_state['version_info']['remote']['sha256'] = 'new-hash'
    def running(**kwargs):
        raise service.web.QmtRunningError('QMT running')
    monkeypatch.setattr(service.web, 'qmt_update_preflight', running)
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official', lambda: pytest.fail('Must not download'))
    with pytest.raises(ManagementError) as error:
        service.runtime.updates.ensure_latest()
    assert error.value.code == 'qmt_running'
    with service.web.PROJECT_UPDATER._operation('update'):
        with pytest.raises(ManagementError) as error:
            service.runtime.updates.ensure_latest()
        assert error.value.code == 'project_update_busy'


def test_version_info_distinguishes_running_files_and_remote(service, monkeypatch, tmp_path):
    web = service.web
    version_path = tmp_path / 'version.py'
    version_path.write_text('__version__ = "9.0.0"\nWEB_VERSION = "web_20990101_01"\n', encoding='utf-8')
    monkeypatch.setattr(web, 'CORE_VERSION_PATH', str(version_path))
    monkeypatch.setattr(web, 'CORE_VERSION', '8.0.0')
    monkeypatch.setattr(web, 'WEB_VERSION', 'web_20980101_01')
    calls = []
    def remote(**kwargs):
        calls.append(kwargs)
        return {'version': '10.0.0', 'web_version': 'web_21000101_01'}
    monkeypatch.setattr(web, '_remote_project_version_info', remote)
    monkeypatch.setattr(web, 'refresh_runtime_version_report', lambda *a, **k: pytest.fail('Do not probe QMT'))
    info = service.runtime.version_info(include_remote=False)
    assert not calls
    assert info['running_version'] == '8.0.0'
    assert info['installed_version'] == '9.0.0'
    assert info['installed_web_version'] == 'web_20990101_01'
    assert info['restart_required'] is True
    assert info['latest_version'] is None
    info = service.runtime.version_info(force=True)
    assert info['latest_version'] == '10.0.0'
    assert calls[0]['force'] is True
    status = service.runtime.status()
    assert status['running_core_version'] == '8.0.0' and status['core_version'] == '9.0.0'


def test_same_version_install_still_requires_restart(service, monkeypatch):
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_read_install_meta',
                        lambda: {'updated_at': service.web.MANAGEMENT_STARTED_AT + 1})
    assert service.runtime.version_info(include_remote=False)['restart_required'] is True


@pytest.mark.parametrize('managed', [True, False])
def test_conditional_http_update_always_requires_credentials(service, monkeypatch, managed):
    if not managed:
        monkeypatch.delenv('CFQUANT_MANAGEMENT_TOKEN_FILE')
    with pytest.raises(ManagementError) as error:
        RuntimeManager(base_url=service.runtime.base_url)._request('POST', '/api/project-updates/ensure-latest', {})
    assert error.value.code == 'authentication_failed'


def test_conditional_http_reloads_only_when_needed(service, release_state, monkeypatch):
    reloads = []
    monkeypatch.setattr(service.web, 'schedule_web_reload', lambda server, info: reloads.append(info))
    latest = service.runtime._request('POST', '/api/project-updates/ensure-latest', {})
    assert latest['status'] == 'up_to_date' and reloads == []
    release_state['version_info']['remote']['sha256'] = 'new-hash'
    monkeypatch.setattr(service.web.PROJECT_UPDATER, '_update_from_official', lambda: {'update_completed': True})
    updated = service.runtime._request('POST', '/api/project-updates/ensure-latest', {})
    assert updated['status'] == 'updated'
    assert reloads[0]['port'] == service.server.server_port


def test_conditional_http_rejects_invalid_reload_before_any_update(service, monkeypatch):
    monkeypatch.setattr(service.web.PROJECT_UPDATER, 'ensure_latest', lambda **k: pytest.fail('Validate first'))
    with pytest.raises(ManagementError) as error:
        service.runtime._request('POST', '/api/project-updates/ensure-latest', {'reload': 'false'})
    assert error.value.status == 400
