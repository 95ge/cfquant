"""Own one freshly spawned QMT and its optional VM/MAC hooks for its lifetime."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import threading

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cfquant.qmt_vm_settings import normalize_qmt_vm_settings, qmt_vm_settings_enabled


def prepare(directory, settings):
    settings = normalize_qmt_vm_settings(settings, strict=True)
    if os.name != 'nt' or struct.calcsize('P') != 8:
        raise RuntimeError('QMT 启动设置需要 Windows 和 64 位 Python')
    from cfquant.qmt_dependencies import import_login_module
    for name in ('frida', 'win32api', 'win32event'):
        import_login_module(name)
    import psutil
    directory = Path(directory).resolve(strict=True)
    for name in ('XtItClient.exe', 'utils.dll') + (('User.dll',) if settings['disable_vm'] else ()):
        if not (directory / name).is_file():
            raise RuntimeError('QMT 目录缺少 ' + name)
    if not qmt_vm_settings_enabled(settings):
        raise ValueError('未启用任何 QMT 启动设置')
    discovery = None
    if settings['disable_vm']:
        from cfquant.qmt_vm_discovery import inspect_client
        discovery = inspect_client(directory)
    return directory, settings, discovery


def ensure_stopped(directory):
    import psutil
    expected = os.path.normcase(str(directory / 'XtItClient.exe'))
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').lower() != 'xtitclient.exe':
            continue
        try:
            if os.path.normcase(str(Path(process.exe()).resolve())) == expected:
                raise RuntimeError('此目录已有运行中的 QMT；请先退出再启动')
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            raise RuntimeError('无法确认 QMT 进程路径，请检查进程访问权限') from None


def agent_source(settings):
    # MAC-only must not load or resolve the VM predicates.
    root = Path(__file__).resolve().parent
    source = 'rpc.exports = {};\n'
    if settings['disable_vm']:
        source += (root / 'qmt_vm_agent.js').read_text(encoding='utf-8') + '\n'
    if settings['inject_mac']:
        source += (root / 'qmt_mac_agent.js').read_text(encoding='utf-8')
    return source


def install_hooks(session, directory, settings, discovery, on_message):
    script = session.create_script(agent_source(settings))
    script.on('message', on_message)
    script.load()
    if settings['inject_mac']:
        result = script.exports_sync.configuremac(str(directory), settings['mac_address'])
        if not result.get('ready'):
            raise RuntimeError('MAC 注入未就绪，已取消此次启动')
    if settings['disable_vm']:
        result = script.exports_sync.initialize(str(directory), discovery['hooks'])
        if not result.get('ready'):
            raise RuntimeError('虚拟机检测适配未就绪，已取消此次启动')
    return script


def launch(directory, settings, discovery, qmt_args, reply, commands, env=None):
    import frida
    import win32api
    import win32event
    digest = hashlib.sha256(os.path.normcase(str(directory)).encode('utf-8')).hexdigest()[:24]
    mutex = win32event.CreateMutex(None, False, 'Local\\CFQuantQmtVmStart_' + digest)
    device = frida.get_local_device()
    acquired = committed = False
    pid = session = script = None
    detached = threading.Event()
    failed = threading.Event()
    try:
        acquired = win32event.WaitForSingleObject(mutex, 10000) in (0, 0x80)
        if not acquired:
            raise RuntimeError('此目录的 QMT 启动设置进程正在运行')
        if commands['cancel'].is_set():
            raise RuntimeError('启动已取消')
        ensure_stopped(directory)
        executable = str(directory / 'XtItClient.exe')
        child_env = os.environ.copy()
        child_env.update({str(key): str(value) for key, value in (env or {}).items()})
        pid = device.spawn([executable] + list(qmt_args), cwd=str(directory), env=child_env, stdio='pipe')
        session = device.attach(pid)
        session.on('detached', lambda *args: detached.set())

        def on_message(message, data):
            if message.get('type') == 'error':
                failed.set()

        script = install_hooks(session, directory, settings, discovery, on_message)
        if failed.is_set() or detached.is_set() or commands['cancel'].is_set():
            raise RuntimeError('启动设置未就绪，已取消此次启动')
        device.resume(pid)
        reply({'state': 'ready', 'qmt_pid': pid, 'settings': settings})
        commands['received'].wait(15)
        if not commands['commit'].is_set() or failed.is_set() or detached.is_set():
            raise RuntimeError('启动未完成确认，已取消此次启动')
        reply({'state': 'committed'})
        committed = True
        # Keep Frida alive across Web restarts, but release the response pipe.
        sys.stdout.close()
        detached.wait()
    finally:
        if pid is not None and not committed:
            try:
                device.kill(pid)
            except frida.ProcessNotFoundError:
                pass
        if session is not None:
            try:
                session.detach()
            except (frida.InvalidOperationError, frida.TransportError):
                pass
        if acquired:
            win32event.ReleaseMutex(mutex)
        win32api.CloseHandle(mutex)


def main():
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding='utf-8')

    def reply(value):
        print(json.dumps(value, ensure_ascii=True), flush=True)

    try:
        request = json.loads(sys.stdin.readline())
        commands = {name: threading.Event() for name in ('commit', 'cancel', 'received')}
        check_only = '--check' in sys.argv
        if not check_only:
            def read_command():
                command = sys.stdin.readline().strip()
                commands['commit' if command == 'commit' else 'cancel'].set()
                commands['received'].set()
            threading.Thread(target=read_command, daemon=True).start()
        directory, settings, discovery = prepare(request['directory'], request['settings'])
        if check_only:
            reply({'ready': True})
        else:
            launch(directory, settings, discovery, request.get('qmt_args', []), reply, commands,
                   env=request.get('env') or {})
        return 0
    except Exception as error:
        if not sys.stdout.closed:
            reply({'error': str(error)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
