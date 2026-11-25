"""Center A bootstrap, application lifecycle and optional presentation adapter."""
import argparse
import json
import os
import socket
from pathlib import Path
import threading
import time
from http.server import ThreadingHTTPServer

from .center_services import RuntimeRpcServer, runtime_root, write_runtime_json


def service_address_available():
    """Reuse an existing center; reject other port owners before starting A."""
    from types import SimpleNamespace
    from .cli import _resolve_web_address, _web_probe_host, _cfquant_web_available
    args = SimpleNamespace(host=None, port=None)
    host, port = _resolve_web_address(args)
    if not 1 <= int(port) <= 65535:
        raise ValueError('center API port must be between 1 and 65535')
    probe_host = _web_probe_host(host)
    try:
        with socket.create_connection((probe_host, port), timeout=.5):
            pass
    except OSError:
        return True
    if _cfquant_web_available(probe_host, port):
        print('cfquant center already running on http://%s:%s; reuse existing instance' % (probe_host, port))
        return False
    raise RuntimeError('cfquant API port %s is already occupied by another process' % port)


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(int(os.environ.get('CFQUANT_HTTP_WORKERS', '64')))
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                # Consume already-arriving headers before closing, otherwise
                # Windows can reset a normal GET before its 503 is delivered.
                request.settimeout(.05)
                try:
                    request.recv(65536)
                except (OSError, socket.timeout):
                    pass
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class RuntimeServices:
    """One owner for tasks/configuration; HTTP listener restarts do not stop it."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.started = []
        self.rpc = RuntimeRpcServer(self.dispatch)

    def dispatch(self, action, params):
        if action == 'cfquant.notify.send':
            return self.runtime.send_user_notification(params)
        return self.runtime.algorithm_request(action, params)

    def ready(self):
        if not self.rpc.connected():
            return False
        # The worker can finish booting before its parent subscribes to LTtx.
        # Never advertise readiness using the previous parent's status file.
        path = Path(os.environ.get('CFQUANT_PIPE_HUB_STATUS_FILE') or
                    runtime_root() / 'status/cfquant_pipe_hub_status.json')
        try:
            status = json.loads(path.read_text(encoding='utf-8'))
            return bool(status.get('running') and status.get('pid') == int(os.environ['CFQUANT_CENTER_PARENT_PID'])
                        and (status.get('center') or {}).get('connected'))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False

    def _start(self, component):
        self.started.append(component)
        component.start()

    def start(self):
        r = self.runtime
        r.report_startup_dependencies()
        r.ensure_lttx_started('独立中心 A 启动')
        self.prepare_qmt()
        r.TRADING_MONITOR.restore()
        r.MONITOR_NOTIFICATIONS.restore()
        r.internal_api_key()
        for mode in r.configured_runtime_modes():
            r.CLIENTS.start(mode)
        # Kept as an old SDK compatibility channel, owned by A's worker.
        self._start(r.LTTX_WEB_ROUTE)
        for component in (r.STATUS_MONITOR, r.MONITOR_NOTIFICATIONS):
            self._start(component)
        r.QMT_STRATEGIES.reconcile(r.WEB_CONFIG.account_configs())
        for component in (r.QMT_STRATEGIES, r.QMT_STRATEGY_RECOVERY,
                          r.QMT_AUTO_LOGIN_RESTART_SCHEDULER, r.QMT_PROCESS_WATCHDOG,
                          r.ACCOUNT_CACHE, r.CALLBACKS, r.QUOTES, r.LOG_CLEANUP):
            self._start(component)
        if os.path.isfile(os.path.join(r.RUNTIME_DB_DIR, 'algorithm_tasks.sqlite3')):
            r.algorithm_engine()
        self._start(self.rpc)
        try:
            from .remote_adapter import register_runtime, refresh_launch_settings
            register_runtime(r)
            refresh_launch_settings(r)
            r.start_remote_management_agent()
        except Exception as error:
            r.safe_print('center remote management unavailable: %s' % error)
        r.MANAGEMENT_READY = True

    def prepare_qmt(self):
        r = self.runtime
        preserve = os.environ.pop('CFQUANT_REMOTE_PRESERVE_QMT', '') == '1'
        apply_policy = os.environ.pop('CFQUANT_CENTER_APPLY_QMT_START_POLICY', '') == '1'
        if not preserve:
            r.STARTUP_QMT_CORE_DEPLOY = r.auto_deploy_qmt_core_for_all_accounts(source_dir=r.BASE_DIR)
            for result in r.refresh_bound_qmt_strategies(force=True):
                if result.get('error'):
                    r.safe_print('center strategy refresh failed: %s' % result['error'])
        if not preserve or apply_policy:
            r.start_configured_qmt_on_web_startup()

    def close(self):
        r = self.runtime
        r.MANAGEMENT_READY = False
        for component in reversed(self.started):
            try:
                component.close()
            except Exception as error:
                r.safe_print('center service shutdown failed: %s' % error)
        self.started.clear()
        if r._ALGO_ENGINE is not None:
            r.CLIENTS.remove_callback('__event__', r._ALGO_ENGINE.notify)
            r._ALGO_ENGINE.close()
        for component in (r.LATENCY_QUOTES, r.PROJECT_QUOTES, r.CLIENTS, r.TRADING_MONITOR):
            component.close()
        if r._SUBSCRIPTION_MANAGER is not None:
            r._SUBSCRIPTION_MANAGER.close()


def worker_main(runtime, argv=None):
    """Run under A's supervisor; no browser resources are needed for startup."""
    parent_pid = int(os.environ.get('CFQUANT_CENTER_PARENT_PID') or 0)
    if not parent_pid:
        raise RuntimeError('start application services through cfquant center, not as an orphan worker')
    r = runtime
    r.WEB_BOUND_HOST = os.environ.get('CFQUANT_WEB_HOST') or ('0.0.0.0' if r.WEB_CONFIG.allow_remote() else '127.0.0.1')
    r.WEB_BOUND_PORT = r.normalize_web_port(os.environ.get('CFQUANT_WEB_PORT'), default=r.WEB_CONFIG.web_port())
    # Reserve the API address before any deployment/login/scheduler starts.
    server = BoundedHTTPServer((r.WEB_BOUND_HOST, r.WEB_BOUND_PORT), r.CfquantWebHandler)
    services = RuntimeServices(r)
    r.CENTER_SERVICES = services
    stopped = threading.Event()
    parent_lost = threading.Event()
    current_server = [server]
    def watch_parent():
        import psutil
        try:
            parent = psutil.Process(parent_pid)
            expected_created = float(os.environ.get('CFQUANT_CENTER_PARENT_CREATED') or 0)
            if expected_created and abs(parent.create_time() - expected_created) > .05:
                raise psutil.NoSuchProcess(parent_pid)
            while not stopped.wait(.5):
                if not parent.is_running():
                    break
                shutdown = runtime_root() / 'status/center-services-stop.json'
                if shutdown.exists():
                    try:
                        if json.loads(shutdown.read_text(encoding='utf-8')).get('parent_pid') == parent_pid:
                            break
                    except (OSError, ValueError):
                        pass
        except psutil.Error:
            pass
        if not stopped.is_set():
            parent_lost.set()
            r.MANAGEMENT_READY = False
            # shutdown() waits for serve_forever(), which may not have started
            # yet if QMT initialization is blocked. Do not block the watcher.
            threading.Thread(target=current_server[0].shutdown, daemon=True).start()
            if not stopped.wait(5):
                # Windows does not kill children when their parent dies. Bound
                # orphan lifetime even inside a blocked vendor/startup call.
                os._exit(0)
    watcher = threading.Thread(target=watch_parent, name='cfquant-services-parent', daemon=True)
    try:
        watcher.start()
        services.start()
        while not parent_lost.is_set():
            write_runtime_json(runtime_root() / 'status/center-services-listener.json', dict(
                parent_pid=parent_pid, parent_created=float(os.environ.get('CFQUANT_CENTER_PARENT_CREATED') or 0),
                CFQUANT_WEB_HOST=r.WEB_BOUND_HOST, CFQUANT_WEB_PORT=r.WEB_BOUND_PORT))
            r.safe_print('cfquant center API listening on http://%s:%s; web_display=%s' %
                         (r.WEB_BOUND_HOST, r.WEB_BOUND_PORT, os.environ.get('CFQUANT_WEB_ENABLED', '1')))
            server.serve_forever(poll_interval=.2)
            with r.WEB_RESTART_LOCK:
                request, r.WEB_RESTART_REQUEST = r.WEB_RESTART_REQUEST, None
            if not request:
                break
            reason = str(request.get('reason') or '')
            if reason in ('management', 'project-update', 'project-rollback', 'project-update-upload', 'ensure-latest'):
                path = runtime_root() / 'status/center-services-restart.json'
                write_runtime_json(path, dict(parent_pid=parent_pid, restart_center=True,
                    preserve_qmt=reason == 'management',
                    restart_lttx=reason != 'management',
                    apply_qmt_start_policy=bool(request.get('apply_qmt_start_policy')),
                    CFQUANT_WEB_HOST=request.get('host') or r.WEB_BOUND_HOST,
                    CFQUANT_WEB_PORT=request.get('port') or r.WEB_BOUND_PORT,
                    CFQUANT_QMT_AUTO_START=os.environ.get('CFQUANT_QMT_AUTO_START', 'saved')))
                break
            # Listener/display configuration changes preserve all task owners.
            server.server_close()
            r.WEB_BOUND_HOST = request.get('host') or r.WEB_BOUND_HOST
            r.WEB_BOUND_PORT = request.get('port') or r.WEB_BOUND_PORT
            server = BoundedHTTPServer((r.WEB_BOUND_HOST, r.WEB_BOUND_PORT), r.CfquantWebHandler)
            current_server[0] = server
    finally:
        try:
            services.close()
        finally:
            server.server_close()
            stopped.set()
    return 0


def main(argv=None):
    """Public A entry; old Web launch commands remain compatible."""
    parser = argparse.ArgumentParser(description='Start cfquant center A and its application services.')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-web', action='store_true', help='Disable pages; core APIs and services remain available.')
    parser.add_argument('--home', '--state-dir', dest='home')
    parser.add_argument('--runtime-dir')
    parser.add_argument('--pipe-name')
    args = parser.parse_args(argv)
    for name, key in [('host', 'CFQUANT_WEB_HOST'), ('port', 'CFQUANT_WEB_PORT'),
                      ('home', 'CFQUANT_HOME'), ('runtime_dir', 'CFQUANT_RUNTIME_DIR'), ('pipe_name', 'CFQUANT_PIPE_NAME')]:
        value = getattr(args, name)
        if value is not None:
            os.environ[key] = str(value)
    if args.home and not args.runtime_dir:
        os.environ['CFQUANT_RUNTIME_DIR'] = str(Path(args.home).resolve() / 'runtime')
    if args.no_web:
        os.environ['CFQUANT_WEB_ENABLED'] = '0'
    from .center_services import configure_center_paths, configure_center_transport
    configure_center_paths()
    configure_center_transport()
    from .pipe_hub import run_pipe_hub
    run_pipe_hub(pipe_name=os.environ.get('CFQUANT_PIPE_NAME'), core_services=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
