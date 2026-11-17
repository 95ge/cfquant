"""Qt login compatibility gates without a running terminal or real credentials."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfquant import qmt_component_login as login, qmt_dependencies
from cfquant.qmt_native_worker import NativeWorker, QmtAutomationError, QmtLoginUnsupported


def terminal(tmp_path, monkeypatch, versions, machine=0x8664):
    image = bytearray(128)
    image[0x3c:0x40] = (64).to_bytes(4, 'little')
    image[68:70] = machine.to_bytes(2, 'little')
    (tmp_path/'XtItClient.exe').write_bytes(image)
    def version(path, _):
        major, minor, patch, revision = versions[Path(path).name]
        return {'FileVersionMS': major << 16 | minor, 'FileVersionLS': patch << 16 | revision}
    monkeypatch.setattr(qmt_dependencies, 'import_login_module',
                        lambda name: SimpleNamespace(GetFileVersionInfo=version))


@pytest.mark.parametrize('version', [(5,6,2,0), (5,15,2,0)])
def test_supported_login_abis(tmp_path, monkeypatch, version):
    terminal(tmp_path, monkeypatch, dict.fromkeys(('Qt5Core.dll','Qt5Widgets.dll'), version))
    assert login._verify_environment_native(tmp_path)['qt_version'] == '.'.join(map(str,version[:3]))


@pytest.mark.parametrize('version', [(5,9,9,0), (5,15,3,0), (5,15,2,1), (6,5,0,0)])
def test_unvalidated_versions_report_actual_component_and_manual_recovery(tmp_path, monkeypatch, version):
    terminal(tmp_path, monkeypatch, dict.fromkeys(('Qt5Core.dll','Qt5Widgets.dll'), version))
    with pytest.raises(QmtLoginUnsupported) as raised:
        login._verify_environment_native(tmp_path)
    assert '.'.join(map(str,version)) in str(raised.value)
    assert 'Qt5Core.dll' in str(raised.value) and '手动登录' in str(raised.value)


@pytest.mark.parametrize('core', [(5,15,2,0), (5,15,3,0)])
def test_partial_qt_update_rejected(tmp_path, monkeypatch, core):
    terminal(tmp_path, monkeypatch, {'Qt5Core.dll':core,'Qt5Widgets.dll':(5,6,2,0)})
    with pytest.raises(QmtAutomationError, match='版本不一致') as raised:
        login._verify_environment_native(tmp_path)
    assert not isinstance(raised.value, QmtLoginUnsupported)


@pytest.mark.parametrize('version', [(5,15,2,0), (5,15,3,0)])
def test_x86_client_still_rejected(tmp_path, monkeypatch, version):
    terminal(tmp_path, monkeypatch, dict.fromkeys(('Qt5Core.dll','Qt5Widgets.dll'), version), machine=0x14c)
    with pytest.raises(RuntimeError, match='64 位') as raised:
        login._verify_environment_native(tmp_path)
    assert not isinstance(raised.value, QmtLoginUnsupported)


def test_loaded_qt_does_not_match_updated_files():
    login._validate_loaded_qt('5.15.2', '5.15.2')
    with pytest.raises(QmtAutomationError, match='已加载 Qt 5.6.2.*磁盘组件为 Qt 5.15.2'):
        login._validate_loaded_qt('5.15.2','5.6.2')


def test_loaded_modules_must_belong_to_binding(tmp_path):
    names = ('Qt5Core.dll','Qt5Widgets.dll','LoginDialog.dll')
    modules = {name:str(tmp_path/name) for name in names}
    login._validate_login_modules(tmp_path, modules)
    with pytest.raises(login.QmtNotReady):
        login._validate_login_modules(tmp_path, dict(modules, **{'LoginDialog.dll':None}))
    with pytest.raises(QmtAutomationError, match='不属于当前绑定目录'):
        login._validate_login_modules(tmp_path, dict(modules, **{'Qt5Core.dll':str(tmp_path/'another'/'Qt5Core.dll')}))


def test_compatibility_errors_survive_worker_rpc():
    with pytest.raises(QmtAutomationError, match='Qt 5.15.3'):
        NativeWorker._raise_remote({'error_type':'QmtAutomationError','error':'Qt 5.15.3 not validated'})
    with pytest.raises(QmtLoginUnsupported, match='Qt 5.15.3'):
        NativeWorker._raise_remote({'error_type':'QmtLoginUnsupported','error':'Qt 5.15.3 not validated'})
