"""Default-off launch preferences, persistence, isolation and rejection ordering."""
import json

import pytest

from cfquant.qmt_vm_settings import normalize_qmt_vm_settings as normalize
from cfquant.tests.test_qmt_strategy_web import web_config

OFF = {'disable_vm': False, 'inject_mac': False, 'mac_address': ''}
MAC = '02-AA-BB-CC-DD-EE'


@pytest.mark.parametrize('value', [None, {}, {'disable_vm': 'false', 'inject_mac': 1}])
def test_missing_or_malformed_flags_never_enable_hooks(value):
    assert normalize(value) == OFF


@pytest.mark.parametrize('value', [True, [], {'disable_vm': 1}, {'inject_mac': 'true'},
    {'inject_mac': True}, {'mac_address': '00-00-00-00-00-00'},
    {'mac_address': 'FF-FF-FF-FF-FF-FF'}, {'mac_address': '01-11-22-33-44-55'},
    {'mac_address': '02-XX-22-33-44-55'}, {'mac_address': '02-11-22'}])
def test_invalid_settings_are_rejected(value):
    with pytest.raises(ValueError):
        normalize(value, strict=True)


def save(config, tmp_path, account='fixture', **kwargs):
    return config.save_account_config(account, bridge_id=account, qmt_dir=str(tmp_path / account),
        qmt_auto_login={'enabled': False}, qmt_strategy={'enabled': False}, **kwargs)


def test_defaults_partial_edit_reload_and_binding_isolation(web_config, tmp_path):
    web, config = web_config
    first = save(config, tmp_path)
    assert first['qmt_vm'] == OFF
    edited = save(config, tmp_path, qmt_vm={'disable_vm': True, 'inject_mac': True,
                                          'mac_address': ' 02:aa:bb:cc:dd:ee '})
    assert edited['qmt_vm'] == dict(OFF, disable_vm=True, inject_mac=True, mac_address=MAC)
    assert save(config, tmp_path)['qmt_vm'] == edited['qmt_vm']
    assert save(config, tmp_path, 'second')['qmt_vm'] == OFF
    disabled = save(config, tmp_path, qmt_vm={'disable_vm': False, 'inject_mac': False})
    restored = web.WebRuntimeConfig(config.path, config.settings_db_path)
    assert restored.account_configs()[first['account_key']]['qmt_vm'] == dict(OFF, mac_address=MAC)
    assert restored.account_pairs()[first['account_key']]['qmt_vm'] == disabled['qmt_vm']
    assert restored.account_configs()['second:STOCK:second']['qmt_vm'] == OFF


def test_legacy_load_and_invalid_edit_preserve_original(web_config, tmp_path):
    web, config = web_config
    row = save(config, tmp_path)
    raw = json.loads(open(config.path, encoding='utf-8').read())
    raw['account_configs'][row['account_key']].pop('qmt_vm')
    with open(config.path, 'w', encoding='utf-8') as output:
        json.dump(raw, output)
    assert web.WebRuntimeConfig(config.path, config.settings_db_path).account_configs()[row['account_key']]['qmt_vm'] == OFF
    before = config.snapshot()
    with pytest.raises(ValueError):
        save(config, tmp_path, qmt_vm={'inject_mac': True, 'mac_address': 'invalid'})
    assert config.snapshot() == before


@pytest.mark.parametrize('endpoint', ['save_account_runtime_config', 'initialize_web_setup'])
def test_bad_mac_is_rejected_before_process_stop_or_setup_changes(web_config, monkeypatch, tmp_path, endpoint):
    web, config = web_config
    before = config.snapshot()
    monkeypatch.setattr(web, 'qmt_process_preflight', lambda **kw: pytest.fail('must not stop QMT'))
    with pytest.raises(ValueError, match='MAC'):
        getattr(web, endpoint)({'account_id': 'fixture', 'qmt_dir': str(tmp_path),
            'auto_close_qmt': True, 'qmt_auto_login': {'enabled': False},
            'qmt_vm': {'inject_mac': True, 'mac_address': 'invalid'}})
    assert config.snapshot() == before


def test_shared_directory_conflicts_are_rejected_but_disabled_bindings_are_ignored(web_config, tmp_path):
    web, config = web_config
    common = dict(qmt_auto_login={'enabled': False}, qmt_strategy={'enabled': False})
    first = config.save_account_config('one', qmt_dir=str(tmp_path), **common)
    before = config.snapshot()
    with pytest.raises(ValueError, match='同一 QMT'):
        config.save_account_config('two', bridge_id='two', qmt_dir=str(tmp_path / 'bin.x64'),
                                   qmt_vm={'disable_vm': True}, **common)
    assert config.snapshot() == before
    config.save_account_config('one', bridge_id=first['bridge_id'], qmt_dir=str(tmp_path), enabled=False, **common)
    config.save_account_config('two', bridge_id='two', qmt_dir=str(tmp_path / 'bin.x64'),
                               qmt_vm={'disable_vm': True}, **common)
    assert web._qmt_vm_settings_for_qmt_dir(str(tmp_path))['disable_vm'] is True
