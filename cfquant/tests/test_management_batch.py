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
