"""A-owned application worker lifecycle and isolated LTtx request queues."""
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
import uuid

from .algo import ALGO_ACTIONS
from .smart_orders import SMART_ACTIONS
from .flow_control import KeyedExecutor
from .protocol import loads_message, pack_response

SERVICE_CHANNEL = 'cfquant.center.services.request'
SERVICE_ACTIONS = ALGO_ACTIONS | SMART_ACTIONS | {'cfquant.notify.send'}


def configure_center_paths():
    """Choose one state root for the bridge, service worker and installed CLI."""
    root = Path(__file__).resolve().parents[1]
    source = (root / 'pyproject.toml').is_file() and (root / 'cfquant_web_server.py').is_file()
    default = root if source else Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'cfquant'
    state = Path(os.path.expandvars(str(os.environ.get('CFQUANT_HOME') or
        os.environ.get('CFQUANT_STATE_DIR') or default))).expanduser().resolve()
    os.environ['CFQUANT_HOME'] = str(state)
    os.environ['CFQUANT_RUNTIME_DIR'] = str(Path(os.path.expandvars(
        os.environ.get('CFQUANT_RUNTIME_DIR') or str(state / 'runtime'))).expanduser().resolve())
    # The worker runs from the package directory, not necessarily the caller's
    # cwd. Resolve explicit paths before spawning it or handing off a restart.
    for key in ('CFQUANT_STATE_DIR', 'CFQUANT_WEB_CONFIG_FILE', 'CFQUANT_WEB_SETTINGS_DB_FILE',
                'CFQUANT_LOG_DIR', 'CFQUANT_FRIDA_TEMP_DIR', 'CFQUANT_LTTX_RUNTIME_DIR',
                'CFQUANT_MANAGEMENT_TOKEN_FILE', 'CFQUANT_PIPE_HUB_STATUS_FILE'):
        if os.environ.get(key):
            os.environ[key] = str(Path(os.path.expandvars(os.environ[key])).expanduser().resolve())


def configure_center_transport():
    """Apply CLI environment changes after the package's eager SDK imports."""
    from .config import configure
    configure(host=os.environ.get('CFQUANT_LTTX_HOST') or os.environ.get('CFQUANT_SOCKET_HOST'),
              port=os.environ.get('CFQUANT_LTTX_PORT') or os.environ.get('CFQUANT_SOCKET_PORT'),
              token=os.environ.get('CFQUANT_LTTX_TOKEN') or os.environ.get('CFQUANT_SOCKET_TOKEN'),
              pipe_name=os.environ.get('CFQUANT_PIPE_NAME'))


def runtime_root():
    return Path(os.environ.get('CFQUANT_RUNTIME_DIR') or
                Path(os.environ.get('CFQUANT_HOME') or Path.cwd()) / 'runtime')


def write_runtime_json(path, data):
    """Readers see either the previous state or a complete new document."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def center_version_status(installed_version, updated_at=0):
    """Compare the current parent's loaded version with the installed files."""
    parent_pid = int(os.environ.get('CFQUANT_CENTER_PARENT_PID') or 0)
    if not parent_pid:
        return {}
    path = Path(os.environ.get('CFQUANT_PIPE_HUB_STATUS_FILE') or
                runtime_root() / 'status/cfquant_pipe_hub_status.json')
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        matches = state.get('pid') == parent_pid and state.get('running') is True
        version = state.get('core_version') if matches else None
        created = float(state.get('process_created') or 0) if matches else 0
    except (OSError, ValueError, TypeError, AttributeError):
        version, created = None, 0
    return {'running_center_version': version, 'center_process_created': created,
            'center_restart_required': bool(not version or version != installed_version or float(updated_at or 0) > created)}


def service_token(create=False):
    path = runtime_root() / 'config/center-services.key'
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('x', encoding='ascii') as stream:
                stream.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    token = path.read_text(encoding='ascii').strip()
    if len(token) != 64:
        raise RuntimeError('invalid center service credential')
    return token


class ServiceQueues:
    """Independent bounded pools; FIFO for one account inside each lane."""
    def __init__(self):
        self.lanes = {name: KeyedExecutor(workers=workers, max_pending=limit, name='cfquant-service-' + name) for name, workers, limit in
                      [('algorithm', 6, 256), ('notification', 4, 128), ('control', 2, 64)]}

    def submit(self, msg, run, reject):
        action = msg.get('action', '')
        lane = 'notification' if action == 'cfquant.notify.send' else (
            'algorithm' if action in ALGO_ACTIONS | SMART_ACTIONS else 'control')
        params = msg.get('params') or {}
        account = params.get('account') or {}
        account_key = params.get('account_key') or account.get('account_key')
        identity = (account_key or params.get('account_id') or account.get('account_id') or 'default',
                    params.get('account_type') or account.get('account_type') or 'STOCK',
                    params.get('bridge_id') or account.get('bridge_id') or '')
        self.lanes[lane].submit([('account',) + identity], run, reject)

    def status(self):
        return {key: lane.status() for key, lane in self.lanes.items()}

    def close(self):
        for lane in self.lanes.values():
            lane.close()


class RuntimeRpcServer:
    def __init__(self, dispatch, factory=None, token=None):
        self.dispatch = dispatch
        self.factory = factory
        self.token = token or service_token(create=True)
        self.queues = ServiceQueues()
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.tx = None
        self.thread = None
        self.error = ''

    def start(self):
        self.thread = threading.Thread(target=self._run, name='cfquant-services-receive', daemon=True)
        self.thread.start()

    def _run(self):
        from .client import _load_txl
        from .config import get_config
        cfg = get_config()
        while not self.stop.is_set():
            tx = None
            try:
                tx = (self.factory or _load_txl())(cfg['host'], cfg['port'], cfg['token'], show=False)
                self.tx = tx
                tx.start_txg(SERVICE_CHANNEL)
                self.ready.set()
                self.error = ''
                while not self.stop.is_set():
                    try:
                        raw = tx.Q.get(timeout=.2)
                    except queue.Empty:
                        continue
                    msg = loads_message(raw)
                    if msg and msg.get('type') == 'request':
                        self.enqueue(msg, tx)
            except Exception as error:
                self.error = str(error)
            finally:
                self.ready.clear()
                if tx is not None:
                    tx.close()
                self.tx = None
            self.stop.wait(1)

    def enqueue(self, msg, tx):
        params = dict(msg.get('params') or {})
        credential = params.pop('_center_service_token', '')
        target = msg.get('client_id') or msg.get('reply_channel')
        if not target:
            return
        def reply(result=None, error=None):
            if self.tx is tx:
                tx.push('response', pack_response(msg.get('id'), ok=error is None,
                                                  result=result, error=error), target)
        if not secrets.compare_digest(str(credential), self.token):
            reply(error=PermissionError('center service authentication failed'))
            return
        if msg.get('action') not in SERVICE_ACTIONS:
            reply(error=ValueError('unsupported center service action'))
            return
        entered = time.monotonic()
        def execute():
            if self.stop.is_set() or self.tx is not tx:
                return
            remaining = float(msg.get('timeout') or 15) - (time.monotonic() - entered)
            if remaining <= 0:
                raise TimeoutError('request expired in center service queue before execution')
            reply(self.dispatch(msg['action'], params))
        try:
            self.queues.submit(dict(msg, params=params), execute, lambda error: reply(error=error))
        except Exception as error:
            reply(error=error)

    def connected(self):
        tx = self.tx
        return bool(self.ready.is_set() and tx and getattr(tx, 'tx_running', False)
                    and (getattr(tx, 'txg_dict', {}).get(SERVICE_CHANNEL) or {}).get('txg_running'))

    def status(self):
        return dict(connected=self.connected(), error=self.error, queues=self.queues.status())

    def close(self):
        self.stop.set()
        self.queues.close()
        if self.tx is not None:
            self.tx.close()
        if self.thread is not None:
            self.thread.join(timeout=2)


class ServiceSupervisor:
    """The bridge process owns the worker, including recovery after a crash."""
    def __init__(self, hub):
        import psutil
        self.hub = hub
        self.parent_created = psutil.Process().create_time()
        self.stop = threading.Event()
        self.process = None
        self.thread = None
        self.restarts = 0
        self.error = ''

        # Keep the bootstrap from the running version: an update/rollback can
        # remove its source module before the old parent has stopped.
        self.restart_source = Path(__file__).with_name('center_restart.py').read_text(encoding='utf-8')
        from .center_restart import owned_lttx_processes
        self.owned_lttx_processes = owned_lttx_processes

    def start(self):
        service_token(create=True)
        self.thread = threading.Thread(target=self._run, name='cfquant-services-supervisor', daemon=True)
        self.thread.start()

    def _worker_environment(self):
        env = dict(os.environ, CFQUANT_CENTER_PARENT_PID=str(os.getpid()),
                   CFQUANT_CENTER_PARENT_CREATED=str(self.parent_created),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        path = runtime_root() / 'status/center-services-listener.json'
        try:
            settings = json.loads(path.read_text(encoding='utf-8'))
            if (settings.get('parent_pid') == os.getpid()
                    and settings.get('parent_created') == self.parent_created):
                for key in ('CFQUANT_WEB_HOST', 'CFQUANT_WEB_PORT'):
                    if key in settings:
                        env[key] = str(settings[key])
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return env

    def _run(self):
        restart_file = runtime_root() / 'status/center-services-restart.json'
        while not self.stop.is_set():
            try:
                env = self._worker_environment()
                if self.restarts:
                    env['CFQUANT_REMOTE_PRESERVE_QMT'] = '1'
                    env.pop('CFQUANT_CENTER_APPLY_QMT_START_POLICY', None)
                root = str(Path(__file__).resolve().parents[1])
                env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
                if restart_file.exists():
                    settings = json.loads(restart_file.read_text(encoding='utf-8'))
                    if settings.get('parent_pid') == os.getpid():
                        for key in ('CFQUANT_WEB_HOST', 'CFQUANT_WEB_PORT', 'CFQUANT_QMT_AUTO_START'):
                            if key in settings:
                                env[key] = str(settings[key])
                                os.environ[key] = str(settings[key])
                    restart_file.unlink()
                logs = Path(os.environ.get('CFQUANT_LOG_DIR') or runtime_root().parent / 'log') / 'center'
                logs.mkdir(parents=True, exist_ok=True)
                self.process = subprocess.Popen([sys.executable, '-u', '-m', 'cfquant.runtime_services'],
                    cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                def copy_log(source=self.process.stdout):
                    from .log_management import RollingLogWriter
                    writer = RollingLogWriter(logs / 'services.log')
                    try:
                        for line in iter(source.readline, b''):
                            writer.write(line.decode('utf-8', errors='replace'))
                    finally:
                        source.close()
                        writer.close()
                threading.Thread(target=copy_log, name='cfquant-service-log', daemon=True).start()
                while not self.stop.wait(.25) and self.process.poll() is None:
                    pass
                if self.stop.is_set():
                    break
                code = self.process.returncode
                if restart_file.exists():
                    request = json.loads(restart_file.read_text(encoding='utf-8'))
                    if request.get('parent_pid') == os.getpid() and request.get('restart_center'):
                        restart_env = dict(env)
                        restart_env.pop('CFQUANT_CENTER_PARENT_PID', None)
                        restart_env.pop('CFQUANT_REMOTE_PRESERVE_QMT', None)
                        restart_env.pop('CFQUANT_CENTER_APPLY_QMT_START_POLICY', None)
                        if request.get('preserve_qmt'):
                            restart_env['CFQUANT_REMOTE_PRESERVE_QMT'] = '1'
                        if request.get('apply_qmt_start_policy'):
                            restart_env['CFQUANT_CENTER_APPLY_QMT_START_POLICY'] = '1'
                        if request.get('restart_lttx'):
                            restart_env['CFQUANT_RESTART_LTTX_IDENTITIES'] = json.dumps(
                                self.owned_lttx_processes(runtime_root()))
                        restart_env['CFQUANT_RESTART_PARENT_PID'] = str(os.getpid())
                        for key in ('CFQUANT_WEB_HOST', 'CFQUANT_WEB_PORT', 'CFQUANT_QMT_AUTO_START'):
                            if key in request:
                                restart_env[key] = str(request[key])
                        helper = runtime_root() / 'status/center_restart.py'
                        helper.write_text(self.restart_source, encoding='utf-8')
                        subprocess.Popen([sys.executable, str(helper), str(Path(root) / 'cfquant_web_server.py')],
                            cwd=root, env=restart_env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        restart_file.unlink()
                        threading.Thread(target=self.hub.close, daemon=True).start()
                        return
                if code == 0 and not restart_file.exists():
                    # An explicit management stop stops A, but never QMT.
                    threading.Thread(target=self.hub.close, daemon=True).start()
                    return
                self.error = '' if restart_file.exists() else 'application worker exited: %s' % code
                self.restarts += 1
            except Exception as error:
                self.error = str(error)
            self.stop.wait(min(10, 1 + self.restarts))

    def status(self):
        process = self.process
        return dict(pid=process.pid if process else None,
                    running=bool(process and process.poll() is None), restarts=self.restarts, error=self.error)

    def close(self):
        self.stop.set()
        process = self.process
        if process is not None and process.poll() is None:
            shutdown = runtime_root() / 'status/center-services-stop.json'
            write_runtime_json(shutdown, dict(parent_pid=os.getpid()))
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            finally:
                shutdown.unlink(missing_ok=True)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
