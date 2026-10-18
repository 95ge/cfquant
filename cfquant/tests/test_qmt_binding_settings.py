"""Binding settings round-trip, isolation and deployment payload regressions."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cfquant_web_server as web
from cfquant.qmt_binding_settings import normalize_qmt_runtime_settings, qmt_runtime_identity
from cfquant.pipe_bridge import PipeNormalQmtBridge
from cfquant.tests.test_lite_deployment_paths import web_deployment, assert_lite_package, package_source
from cfquant.tests.test_qmt_strategy_deploy import deployment


@pytest.fixture
def config(tmp_path):
    return web.WebRuntimeConfig(str(tmp_path / 'settings.json'), str(tmp_path / 'settings.db'))


def save(config, account='TEST', **changes):
    args = dict(account_id=account, qmt_strategy={'enabled': False}, qmt_auto_login={'enabled': False})
    args.update(changes)
    return config.save_account_config(**args)


def test_binding_settings_preserve_partial_edits_and_reload(config):
    default = save(config)
    assert default['qmt_runtime'] == {'timer_interval_ms': 1, 'log_enabled': None}
    changed = save(config, qmt_runtime={'timer_interval_ms': 5, 'log_enabled': False})
    assert save(config)['qmt_runtime'] == changed['qmt_runtime']
    assert save(config, qmt_runtime={'timer_interval_ms': 10})['qmt_runtime'] == {
        'timer_interval_ms': 10, 'log_enabled': False}
    save(config, 'SECOND', qmt_runtime={'timer_interval_ms': 60, 'log_enabled': True})
    restored = web.WebRuntimeConfig(config.path, config.settings_db_path)
    values = {row['account_id']: row['qmt_runtime'] for row in restored.account_configs().values()}
    assert values['TEST'] == {'timer_interval_ms': 10, 'log_enabled': False}
    assert values['SECOND'] == {'timer_interval_ms': 60, 'log_enabled': True}
    assert save(config, qmt_runtime={'log_enabled': None})['qmt_runtime']['log_enabled'] is None


@pytest.mark.parametrize('value', [0, -1, 1001, 1.5, True, None, '', 'nan', '1e3'])
def test_reject_invalid_timer_without_changing_saved_binding(config, value):
    row = save(config, qmt_runtime={'timer_interval_ms': 5, 'log_enabled': False})
    with pytest.raises(ValueError, match='1.*1000'):
        save(config, qmt_runtime={'timer_interval_ms': value})
    assert config.account_configs()[row['account_key']]['qmt_runtime'] == row['qmt_runtime']


@pytest.mark.parametrize('value', ['off', 0, 1, [], {}])
def test_reject_invalid_log_choice(value):
    with pytest.raises(ValueError):
        normalize_qmt_runtime_settings({'log_enabled': value}, strict=True)


@pytest.mark.parametrize('choice', [None, True, False])
@pytest.mark.parametrize('global_value', [True, False])
def test_identity_uses_binding_override_and_global_fallback(choice, global_value):
    assert qmt_runtime_identity({'qmt_runtime': {'timer_interval_ms': 5, 'log_enabled': choice}}, global_value) == {
        'qmt_timer_interval_ms': 5, 'qmt_log_enabled': global_value if choice is None else choice}


def test_saved_binding_settings_reach_generated_lite_package(web_deployment, monkeypatch):
    module, manager, row, infos, root = web_deployment
    row['mode'] = 'lite'
    # Exercise real identity writers with only the temporary QMT directories.
    monkeypatch.setattr(module, 'write_qmt_bridge_identity', REAL_IDENTITY_WRITER)
    result = module.save_account_runtime_config({"qmt_auto_login": {"enabled": False},
        **{key: row[key] for key in ('account_id', 'account_type', 'bridge_id', 'qmt_dir', 'mode')},
        'qmt_runtime': {'timer_interval_ms': 5, 'log_enabled': False},
    })
    assert result['account']['qmt_runtime'] == {'timer_interval_ms': 5, 'log_enabled': False}
    job = assert_lite_package(manager, root)
    source = package_source(root / 'formulas' / (job['roles'][0]['name'] + '.rzrk'))
    config_node = next(n.value for n in ast.parse(source).body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'EMBEDDED_RUNTIME_CONFIG' for t in n.targets))
    embedded = ast.literal_eval(config_node)
    assert embedded['qmt_timer_interval_ms'] == 5
    assert embedded['qmt_log_enabled'] is False


REAL_IDENTITY_WRITER = web.write_qmt_bridge_identity


def test_global_toggle_respects_independent_binding_logs(config, monkeypatch):
    for name, choice in [('ON', True), ('OFF', False), ('GLOBAL', None)]:
        save(config, name, bridge_id=name.lower(), qmt_runtime={'log_enabled': choice})
    calls = []
    monkeypatch.setattr(web, 'WEB_CONFIG', config)
    monkeypatch.setattr(web, 'current_bridges', lambda: {name.lower(): {} for name in ('ON', 'OFF', 'GLOBAL')})
    monkeypatch.setattr(web, 'CLIENTS', SimpleNamespace(request=lambda *args, **kwargs: calls.append(args)))
    monkeypatch.setattr(web, 'sync_qmt_bridge_identities', lambda: [])
    web.save_qmt_log_language({'enabled': False, 'language': 'zh'})
    toggles = {args[0]: args[3]['enabled'] for args in calls if args[2] == 'cfquant.set_log_enabled'}
    assert toggles == {'on': True, 'off': False, 'global': False}


def test_common_bridges_in_one_process_have_independent_log_switches(capsys):
    from tools.sync_qmt_binding_settings import HELPERS
    def namespace(enabled):
        result = {'RUNTIME_CONFIG': {'qmt_log_enabled': enabled}, 'os': __import__('os'),
                  '_config_bool': lambda value, default=True: default if value is None else bool(value)}
        exec(HELPERS, result)
        return result
    quiet = PipeNormalQmtBridge(None, globals_dict=namespace(False))
    verbose = PipeNormalQmtBridge(None, globals_dict=namespace(True))
    quiet._log('QUIET')
    verbose._log('VERBOSE')
    assert capsys.readouterr().out.strip() == 'VERBOSE'
    verbose._set_log_enabled({'enabled': False})
    quiet._set_log_enabled({'enabled': True})
    assert verbose._status()['log_enabled'] is False
    assert quiet._status()['log_enabled'] is True


def test_legacy_bridge_without_scoped_getter_observes_global_log_changes(monkeypatch):
    from cfquant import tx_trade_bridge
    enabled = [True]
    monkeypatch.setattr(tx_trade_bridge, 'get_log_enabled', lambda: enabled[0])
    bridge = PipeNormalQmtBridge(None, globals_dict={'RUNTIME_CONFIG': {'qmt_log_enabled': True}})
    assert bridge._status()['log_enabled'] is True
    enabled[0] = False
    assert bridge._status()['log_enabled'] is False
