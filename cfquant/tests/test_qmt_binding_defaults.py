"""Version-gated preference migrations never start a terminal or touch credentials."""
import copy
import json
from pathlib import Path

import pytest

from cfquant.qmt_binding_defaults import MIGRATION_KEY, migrate_qmt_automation_defaults
from cfquant.tests.test_qmt_strategy_web import web_config


def legacy_config(version='0.2.58'):
    result = {
        'account_configs': {'fixture': {
            'account_id': 'fixture', 'account_type': 'STOCK', 'bridge_id': 'fixture',
            'mode': 'lite', 'qmt_dir': 'D:/fixture-qmt', 'enabled': False,
            'qmt_auto_login': {'enabled': False, 'auto_update': False,
                               'auto_fill_credentials': False, 'restart_times': ['10:30']},
            'qmt_strategy': {'enabled': False, 'autorun': False, 'live': False, 'stock': 'SZ399001'},
        }},
        'unknown_setting': {'preserve': True},
    }
    if version is not None:
        result['saved_core_version'] = version
    return result


@pytest.mark.parametrize('version', ['0.2.58', '0.2.9', '0.1.99', 'v0.2.58', '0.2.59rc1'])
def test_known_older_versions_enable_only_automation(version):
    raw = legacy_config(version)
    before = copy.deepcopy(raw)
    migrated, count = migrate_qmt_automation_defaults(raw)
    assert raw == before
    assert count == 1
    row = migrated['account_configs']['fixture']
    assert row['qmt_auto_login'] == dict(raw['account_configs']['fixture']['qmt_auto_login'], enabled=True, auto_update=True)
    assert row['qmt_strategy'] == dict(raw['account_configs']['fixture']['qmt_strategy'], enabled=True, autorun=True)
    assert row['enabled'] is False  # Whole-binding opt-out still applies.
    assert migrated['unknown_setting'] == raw['unknown_setting']
    assert migrated[MIGRATION_KEY]['source_version'] == version


@pytest.mark.parametrize('version', [None, '', 'unknown', 2, '0.2.59', '0.2.60', '0.2.100', '1.0.0', '0.2.59.post1'])
def test_unknown_equal_and_newer_versions_keep_explicit_opt_out(version):
    raw = legacy_config(version)
    assert migrate_qmt_automation_defaults(raw) == (raw, 0)


def test_core_version_alias_missing_fields_list_and_legacy_pairs():
    raw = {'core_version': '0.2.57', 'account_configs': [{'account_id': 'fixture'}],
           'account_pairs': {'fixture': {'account_id': 'fixture', 'qmt_auto_login': False}}}
    migrated, count = migrate_qmt_automation_defaults(raw)
    assert count == 1
    assert migrated['account_configs'][0]['qmt_strategy'] == {'enabled': True, 'autorun': True}
    assert migrated['account_pairs']['fixture']['qmt_auto_login'] == {'enabled': True, 'auto_update': True, 'restart_times': ['09:00']}


def test_persist_backup_reload_and_user_opt_out_are_one_time(web_config):
    web, config = web_config
    path = Path(config.path)
    raw = legacy_config()
    raw['account_configs']['fixture']['qmt_auto_login']['restart_times'] = []
    path.write_text(json.dumps(raw), encoding='utf-8')
    original = path.read_bytes()
    loaded = web.WebRuntimeConfig(config.path, config.settings_db_path)
    assert Path(str(path) + '.before-qmt-automation-0.2.59.bak').read_bytes() == original
    assert json.loads(path.read_text(encoding='utf-8'))[MIGRATION_KEY]['version'] == '0.2.59'
    assert loaded.account_configs()['fixture']['qmt_auto_login']['restart_times'] == []
    row = loaded.account_configs()['fixture']
    saved = loaded.save_account_config('fixture', bridge_id='fixture', qmt_dir=row['qmt_dir'],
        qmt_auto_login={'enabled': False, 'auto_update': False}, qmt_strategy={'enabled': False, 'autorun': False})
    reloaded = web.WebRuntimeConfig(config.path, config.settings_db_path)
    row = reloaded.account_configs()[saved['account_key']]
    assert row['qmt_auto_login']['enabled'] is row['qmt_auto_login']['auto_update'] is False
    assert row['qmt_strategy']['enabled'] is row['qmt_strategy']['autorun'] is False
    assert json.loads(path.read_text(encoding='utf-8'))['saved_core_version'] == web.CORE_VERSION
    assert Path(str(path) + '.before-qmt-automation-0.2.59.bak').read_bytes() == original


def test_load_unknown_version_does_not_infer_from_installed_version(web_config, monkeypatch):
    web, config = web_config
    monkeypatch.setattr(web, 'CORE_VERSION', '0.2.58')
    path = Path(config.path)
    path.write_text(json.dumps(legacy_config(None)), encoding='utf-8')
    original = path.read_bytes()
    loaded = web.WebRuntimeConfig(config.path, config.settings_db_path)
    assert loaded.account_configs()['fixture']['qmt_auto_login']['enabled'] is False
    assert path.read_bytes() == original
    assert not Path(str(path) + '.before-qmt-automation-0.2.59.bak').exists()


def test_persistence_failure_keeps_old_preferences_and_allows_retry(web_config, monkeypatch):
    web, config = web_config
    path = Path(config.path)
    path.write_text(json.dumps(legacy_config()), encoding='utf-8')
    original = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(web.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('fixture write failure')))
        loaded = web.WebRuntimeConfig(config.path, config.settings_db_path)
    assert path.read_bytes() == original
    assert loaded.account_configs()['fixture']['qmt_auto_login']['enabled'] is False
    assert loaded.account_configs()['fixture']['qmt_strategy']['autorun'] is False
    loaded.load()
    assert loaded.account_configs()['fixture']['qmt_strategy']['autorun'] is True


def test_new_binding_defaults_and_explicit_disabled_choice(web_config, tmp_path):
    web, config = web_config
    row = config.save_account_config('new', qmt_dir=str(tmp_path), qmt_auto_login={'auto_fill_credentials': False})
    assert row['qmt_auto_login']['enabled'] is row['qmt_auto_login']['auto_update'] is True
    assert row['qmt_strategy']['enabled'] is row['qmt_strategy']['autorun'] is True
    row = config.save_account_config('off', qmt_dir=str(tmp_path),
        qmt_auto_login={'enabled': False, 'auto_update': False}, qmt_strategy={'enabled': False, 'autorun': False})
    restored = web.WebRuntimeConfig(config.path, config.settings_db_path).account_configs()[row['account_key']]
    assert restored['qmt_auto_login']['enabled'] is restored['qmt_auto_login']['auto_update'] is False
    assert restored['qmt_strategy']['enabled'] is restored['qmt_strategy']['autorun'] is False
