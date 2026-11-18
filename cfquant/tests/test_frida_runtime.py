"""Cold Frida imports with old typing, including cached and delayed modules."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cfquant import qmt_dependencies


ROOT = Path(__file__).resolve().parents[2]
OLD_TYPING = '''
import builtins, sys, types, typing, typing_extensions
original_import = builtins.__import__
original_list = builtins.list
old_typing = types.ModuleType('typing')
old_typing.__dict__.update(vars(typing))
for name in ('NotRequired', 'ParamSpec'):
    old_typing.__dict__.pop(name, None)
sys.modules['typing'] = old_typing
'''
FRIDA_SOURCE = '''
from typing import NotRequired, TypedDict, ParamSpec
class Message(TypedDict):
    type: str
    payload: NotRequired[list[str]]
P = ParamSpec('P')
def convert(values: tuple[dict[str, list[int]], ...]) -> list[int]:
    return list(values[0]['items'])
async def convert_async(values: list[int]) -> list[int]:
    return list(values)
'''


@pytest.fixture
def frida_package(tmp_path):
    package = tmp_path / 'frida'
    package.mkdir()
    for filename in ('__init__.py', 'aio.py'):
        (package / filename).write_text(FRIDA_SOURCE, encoding='utf-8')
    metadata = tmp_path / 'frida-17.16.4.dist-info'
    metadata.mkdir()
    (metadata / 'METADATA').write_text('Name: frida\nVersion: 17.16.4\n', encoding='utf-8')
    return tmp_path


def run_child(source, root, executable=None):
    paths = [str(root), str(ROOT)]
    if executable:
        paths.extend(os.environ.get('CFQUANT_TEST_SITE38', '').split(os.pathsep))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(path for path in paths if path),
               CFQUANT_QMT_NO_FILE_IO='1')
    env.pop('PYTHONHOME', None)
    result = subprocess.run([executable or sys.executable, '-B', '-c', source], cwd=str(root), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                            timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('runtime', ['host', 'python38'])
def test_frida_sync_and_async_imports_keep_optional_keys_and_stdlib_unchanged(frida_package, cached, runtime):
    executable = None
    if runtime == 'python38':
        executable = os.environ.get('CFQUANT_TEST_PYTHON38')
        if not executable:
            pytest.skip('Set CFQUANT_TEST_PYTHON38 for actual Python 3.8 annotations')
    if cached:
        run_child('import compileall; assert compileall.compile_dir("frida", quiet=1)',
                  frida_package, executable)
    run_child(OLD_TYPING + '''
from cfquant.qmt_dependencies import import_login_module
first = import_login_module('frida')
assert import_login_module('frida') is first
import frida.aio
for module in (first, frida.aio):
    assert module.Message.__required_keys__ == frozenset(('type',))
    assert module.Message.__optional_keys__ == frozenset(('payload',))
    assert module.convert(({'items': (1, 2)},)) == [1, 2]
    assert __import__('asyncio').run(module.convert_async((3, 4))) == [3, 4]
assert not hasattr(old_typing, 'NotRequired')
assert not hasattr(old_typing, 'ParamSpec')
assert builtins.__import__ is original_import
assert builtins.list is original_list
try:
    from typing import NotRequired
except ImportError:
    pass
else:
    raise AssertionError('Compatibility escaped into another module')
''', frida_package, executable)


def test_dependency_probe_uses_the_same_frida_compatibility(frida_package):
    source = OLD_TYPING + "MODULES = ('frida',)\nFRIDA_VERSION = '17.16.4'\n" + qmt_dependencies._PROBE_CODE
    report = json.loads(run_child(source, frida_package))
    assert report['checks'][0]['ok'], report
    assert report['packages']['frida'] == '17.16.4'


def test_missing_typing_backport_produces_targeted_repair(frida_package):
    source = OLD_TYPING + "sys.modules['typing_extensions'] = None\n"
    source += "MODULES = ('frida',)\nFRIDA_VERSION = '17.16.4'\n" + qmt_dependencies._PROBE_CODE
    report = qmt_dependencies._finish_report(json.loads(run_child(source, frida_package)))
    assert report['checks'][0]['error_type'] == 'FridaTypingCompatibilityError'
    assert not report['ok']
    assert 'typing_extensions>=4.4' in report['repair_commands'][0]
    assert not any('force-reinstall' in command for command in report['repair_commands'])
    assert 'pywin32_postinstall' not in report['repair_note']


def test_modern_python_does_not_require_typing_extensions(frida_package):
    if sys.version_info < (3, 11):
        pytest.skip('Native NotRequired requires Python 3.11+')
    run_child('''
import sys, typing
sys.modules['typing_extensions'] = None
from cfquant.qmt_dependencies import import_login_module
module = import_login_module('frida')
assert module.NotRequired is typing.NotRequired
assert not any(type(finder).__name__ == '_TypingFinder' for finder in sys.meta_path)
''', frida_package)


def test_frida_only_failure_does_not_claim_to_run_pywin32_postinstall():
    report = qmt_dependencies._finish_report({
        'python_executable': 'C:/Python310/python.exe', 'environment': 'python',
        'supported': True, 'checks': [{'name': 'frida', 'ok': False, 'error': 'missing'}],
    })
    assert 'pywin32_postinstall' not in report['repair_note']
    assert not any('pywin32' in command for command in report['repair_commands'])
