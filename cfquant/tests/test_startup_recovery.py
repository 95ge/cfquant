"""Regressions for startup failures before the HTTP server is listening."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('content', [b'', b'\x00' * 19944, b'{"reports":'],
                         ids=['empty', 'nul-filled', 'truncated'])
def test_module_initialization_survives_corrupt_runtime_cache(tmp_path, content):
    cache = tmp_path / 'versions.json'
    cache.write_bytes(content)
    env = os.environ.copy()
    env.update({
        'CFQUANT_HOME': str(tmp_path),
        'CFQUANT_RUNTIME_DIR': str(tmp_path / 'runtime'),
        'CFQUANT_LOG_DIR': str(tmp_path / 'log'),
        'CFQUANT_QMT_RUNTIME_VERSION_FILE': str(cache),
        'PYTHONIOENCODING': 'utf-8',
    })
    result = subprocess.run(
        [sys.executable, '-c',
         'from cfquant import runtime_services as web; assert not web.RUNTIME_VERSIONS._reports'],
        cwd=ROOT, env=env, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    assert cache.read_bytes() == content


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch scripts')
def test_health_wait_stops_when_launched_process_exits(tmp_path):
    source = (ROOT / 'start_cfquant.bat').read_text(encoding='ascii')
    routine = source.split('\n:wait_for_cfquant_web\n', 1)[1].split('\n:show_port_owner\n')[0]
    script = tmp_path / 'wait.bat'
    script.write_text('@echo off\n' + routine, encoding='ascii')
    pid_file = tmp_path / 'child.pid'
    pid_file.write_text('2147483647', encoding='ascii')
    env = os.environ.copy()
    env['CFQUANT_START_PID_FILE'] = str(pid_file)
    result = subprocess.run(
        ['cmd.exe', '/d', '/c', str(script), '1', '90'],
        env=env, capture_output=True, timeout=15,
    )
    assert result.returncode == 1, result.stdout
    assert b'Web service exited before readiness' in result.stdout
    assert not pid_file.exists()


def test_startup_script_uses_component_log_directories():
    source = (ROOT / 'start_cfquant.bat').read_text(encoding='ascii')
    assert 'set "STARTUP_LOG_DIR=%LOG_DIR%\\startup"' in source
    assert 'set "WEB_LOG_DIR=%LOG_DIR%\\web"' in source
    assert 'set "START_LOG=%STARTUP_LOG_DIR%\\cfquant_startup.log"' in source
    assert 'set "WEB_STDOUT=%WEB_LOG_DIR%\\cfquant_web_server.' in source
    restart = (ROOT / 'restart_cfquant.bat').read_text(encoding='ascii')
    assert 'set "START_LOG=%STARTUP_LOG_DIR%\\cfquant_startup.log"' in restart
