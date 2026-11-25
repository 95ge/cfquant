"""Exercise management scripts with redirected input, without live services."""

import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows batch scripts')


def run_batch(path, env):
    started = time.monotonic()
    result = subprocess.run(
        ['cmd.exe', '/d', '/c', str(path)], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=40,
    )
    return result, time.monotonic() - started


def clean_env():
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith('CFQUANT_')}


@pytest.mark.parametrize('name', ['start', 'stop', 'restart'])
def test_completion_delay_works_with_redirected_stdin(tmp_path, name):
    source = (ROOT / (name + '_cfquant.bat')).read_text(encoding='ascii')
    assert 'powershell -NoProfile -WindowStyle Hidden' not in source
    routine = source.split('\n:pause_on_success\n', 1)[1].split('\n:log\n')[0]
    script = tmp_path / 'completion.bat'
    script.write_text('@echo off\n' + routine, encoding='ascii')
    env = clean_env()
    # A flag explicitly set to zero must not suppress the delay.
    env['CFQUANT_' + name.upper() + '_NO_PAUSE'] = '0'
    result, elapsed = run_batch(script, env)
    assert result.returncode == 0, result.stdout
    assert elapsed >= 5
    assert b'Closing in 5 seconds' in result.stdout


def test_start_failure_is_reported_before_delayed_exit(tmp_path):
    folder = tmp_path / ('management space ' + '\u6d4b\u8bd5')
    folder.mkdir()
    script = folder / 'start_cfquant.bat'
    shutil.copyfile(ROOT / script.name, script)
    result, elapsed = run_batch(script, clean_env())
    assert result.returncode == 1, result.stdout
    assert b'cfquant_web_server.py not found' in result.stdout
    assert b'Startup failed. Closing in 5 seconds' in result.stdout
    assert elapsed >= 5


def test_restart_aborts_when_stop_fails_even_if_http_port_is_free(tmp_path):
    script = tmp_path / 'restart_cfquant.bat'
    shutil.copyfile(ROOT / script.name, script)
    (tmp_path / 'stop_cfquant.bat').write_text('@echo off\nexit /b 1\n', encoding='ascii')
    (tmp_path / 'start_cfquant.bat').write_text('@echo off\necho started > started.txt\nexit /b 0\n', encoding='ascii')
    env = dict(clean_env(), CFQUANT_RESTART_NO_PAUSE='1')
    result, _ = run_batch(script, env)
    assert result.returncode == 1 and b'Restart aborted' in result.stdout
    assert not (tmp_path / 'started.txt').exists()


@pytest.mark.parametrize('name, command', [
    ('python.exe', 'python -m cfquant_pipe_hub'),
    ('cfquant-pipe-hub.exe', 'cfquant-pipe-hub.exe --home C:\\isolated'),
])
def test_stop_reports_unverified_legacy_launchers_instead_of_success(name, command):
    source = (ROOT / 'stop_cfquant.bat').read_text(encoding='ascii')
    routine = source.split('\n:stop_python_script\n', 1)[1].split('\n:stop_cfquant_web_port', 1)[0]
    line = next(line for line in routine.splitlines() if line.startswith('powershell '))
    script = line.split('-Command "', 1)[1][:-1]
    # Mock enumeration inside PowerShell; never scan or stop real services.
    prefix = ("function Get-CimInstance { [pscustomobject]@{ Name='%s'; CommandLine='%s'; ProcessId=123 } }; "
              "function Get-Process { throw 'Must not stop an unverified process' }; ") % (name, command)
    env = dict(clean_env(), CFQUANT_STOP_TARGET=r'C:\isolated\cfquant_pipe_hub.py', CFQUANT_STOP_NAME='PipeHub')
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', prefix + script],
                            capture_output=True, env=env, timeout=10)
    assert result.returncode == 1
    assert b'Unverified legacy' in result.stdout
    assert b'Must not stop' not in result.stderr
