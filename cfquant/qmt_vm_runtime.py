"""Isolated, persistent QMT launch hooks, independent of the private project."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .qmt_vm_settings import normalize_qmt_vm_settings, qmt_vm_settings_enabled


def _worker_command(check=False):
    executable = Path(sys.executable)
    if executable.name.lower() == 'pythonw.exe':
        executable = executable.with_name('python.exe')
    command = [str(executable), '-B', str(Path(__file__).with_name('qmt_vm_worker.py'))]
    return command + ['--check'] if check else command


def _worker_kwargs():
    return dict(cwd=str(Path(__file__).resolve().parent), encoding='utf-8',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)


def preflight_feature_process(qmt_dir, settings):
    """Check dependencies and discover predicates before stopping an old QMT."""
    settings = normalize_qmt_vm_settings(settings, strict=True)
    if not qmt_vm_settings_enabled(settings):
        return None
    request = {'directory': str(qmt_dir), 'settings': settings}
    result = subprocess.run(_worker_command(check=True), input=json.dumps(request),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=120, **_worker_kwargs())
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError('QMT 启动设置预检失败：检查 Python 依赖和运行环境') from None
    if result.returncode or payload.get('error'):
        raise RuntimeError(payload.get('error') or 'QMT 启动设置预检失败')
    return payload


def start_feature_process(qmt_dir, settings, *, qmt_args=None, env=None, timeout=120):
    """Return the real QMT PID after hooks are installed and it is resumed.

    Until a successful handshake, closing stdin makes the worker dispose of its
    own new QMT child. After commitment the worker lives until QMT exits, even
    across a Web restart. No historical PID is ever used for cleanup.
    """
    settings = normalize_qmt_vm_settings(settings, strict=True)
    if not qmt_vm_settings_enabled(settings):
        return None
    process = subprocess.Popen(_worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, **_worker_kwargs())
    responses = queue.Queue()

    def read_responses():
        try:
            for line in process.stdout:
                responses.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            responses.put({'error': 'QMT 启动设置进程已退出，请检查依赖或客户端适配'})

    reader = threading.Thread(target=read_responses, name='qmt-launch-handshake', daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def receive(expected):
        try:
            payload = responses.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise RuntimeError('QMT 启动设置超时，已取消此次启动') from None
        if payload.get('error'):
            raise RuntimeError(payload['error'])
        if payload.get('state') != expected:
            raise RuntimeError('QMT 启动设置握手状态异常')
        return payload

    try:
        request = {'directory': str(qmt_dir), 'settings': settings, 'qmt_args': list(qmt_args or []),
                   'env': dict(env or {})}
        process.stdin.write(json.dumps(request) + '\n')
        process.stdin.flush()
        launch = receive('ready')
        if int(launch.get('qmt_pid') or 0) <= 0:
            raise RuntimeError('QMT 启动设置没有返回有效的客户端 PID')
        process.stdin.write('commit\n')
        process.stdin.flush()
        receive('committed')
        launch['launcher_pid'] = process.pid
        return launch
    finally:
        # EOF cancels any uncommitted launch; the worker owns child cleanup.
        try:
            process.stdin.close()
        except OSError:
            pass
        def reap():
            process.wait()
            reader.join()
            process.stdout.close()
        threading.Thread(target=reap, name='qmt-launch-reaper', daemon=True).start()
