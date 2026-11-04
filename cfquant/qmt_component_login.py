"""Explicit QMT component login for a configured binding (Windows, Qt 5.6.2 x64).

Run with --binding NAME. Password is requested only if needed, using --prompt
or stdin. This tool never starts/stops QMT; it replaces the login form contents.
The web auto-start service also uses login_running_qmt after starting a process.
"""
import argparse
import getpass
import json
from pathlib import Path
import sys
import time

from .qmt_native_worker import IsolatedLoginBackend, QmtAutomationCancelled, verify_environment_isolated


class QmtNotReady(RuntimeError):
    pass


class QmtProcessExited(RuntimeError):
    pass


def verify_environment(directory):
    """Validate dependencies and native ABI before stopping a running terminal."""
    verify_environment_isolated(directory)


def _verify_environment_native(directory, *, strategy=False):
    """Only invoked inside the native worker or the standalone login CLI."""
    try:
        from .qmt_dependencies import LOGIN_MODULES, import_login_module
    except ImportError:
        from qmt_dependencies import LOGIN_MODULES, import_login_module
    modules = {name: import_login_module(name) for name in LOGIN_MODULES}
    win32api = modules["win32api"]
    directory = Path(directory)
    for module in ("Qt5Core.dll", "Qt5Widgets.dll"):
        version = win32api.GetFileVersionInfo(str(directory / module), "\\")
        if strategy:
            if version["FileVersionMS"] >> 16 != 5:
                raise RuntimeError("QMT 策略检测需要兼容的 Qt 5 接口，当前组件 ABI 不受支持")
        elif (version["FileVersionMS"], version["FileVersionLS"]) != ((5 << 16) | 6, 2 << 16):
            raise RuntimeError("QMT 组件自动登录当前仅支持 Qt 5.6.2，请先适配此客户端版本")
    with (directory / "XtItClient.exe").open("rb") as stream:
        stream.seek(0x3C)
        offset = int.from_bytes(stream.read(4), "little")
        stream.seek(offset + 4)
        if int.from_bytes(stream.read(2), "little") != 0x8664:
            raise RuntimeError("QMT 原生组件操作需要 64 位客户端")


def auto_login(backend, password_provider, *, retry_not_ready=False, login_account=None,
               should_cancel=lambda: False, on_wait=lambda phase: None):
    """Wait through startup/update when managed, and submit the credential once.

    Readiness retries never force a disabled button. After submission, a timeout
    only renews observation: it is not evidence that another submission is safe.
    """
    attempts = []
    password_requested = False

    def result(outcome):
        return {"outcome": outcome, "login_succeeded": outcome in ("logged_in", "already_logged_in"),
                "attempts": attempts, "password_requested": password_requested}

    while True:
        if should_cancel():
            return result("cancelled")
        if backend.already_logged_in():
            if login_account is not None:
                backend.select_account(login_account)
            return result("already_logged_in")
        state = backend.state()
        if state.get("notice") in ("challenge", "network_error"):
            return result(state["notice"])
        if not state.get("busy"):
            if not password_requested or not state.get("has_password"):
                if not password_requested:
                    if state.get("notice") == "credential_error":
                        backend.acknowledge_failure()
                    if login_account is not None:
                        backend.select_account(login_account, replace=True)
                if should_cancel():
                    return result("cancelled")
                password_requested = True
                password = password_provider()
                if not password:
                    return result("password_required")
                try:
                    backend.fill(password)
                finally:
                    password = None
                state = backend.state()
            if state.get("login_enabled") and not state.get("busy"):
                if should_cancel():
                    return result("cancelled")
                try:
                    backend.submit()
                except QmtNotReady:
                    # The button can become disabled between status and submit.
                    pass
                else:
                    attempts.append("provided")
                    break
        if not retry_not_ready:
            return result("login_not_ready")
        on_wait("waiting_ready")
        time.sleep(0.5)

    on_wait("logging_in")
    while True:
        if should_cancel():
            return result("cancelled")
        outcome = backend.wait_outcome()
        if outcome != "timeout" or not retry_not_ready:
            return result(outcome)
        on_wait("logging_in")
        time.sleep(0.5)


def select_binding(config_path, name):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    rows = config.get("account_configs") or {}
    rows = rows.values() if isinstance(rows, dict) else rows
    matches = [row for row in rows if row.get("display_name") == name]
    if len(matches) != 1:
        raise ValueError("Expected exactly one binding with that display name")
    root = Path(matches[0]["qmt_dir"]).resolve()
    for directory in (root, root / "bin.x64"):
        if (directory / "XtItClient.exe").is_file():
            return matches[0], directory
    raise ValueError("Binding directory does not contain XtItClient.exe")


class QtLoginBackend:
    def __init__(self, directory, timeout=40, expected_pid=None, *, agent_extension="", strategy=False):
        try:
            from .qmt_dependencies import import_login_module
        except ImportError:
            from qmt_dependencies import import_login_module
        import psutil
        frida = import_login_module("frida")
        win32api = import_login_module("win32api")
        win32event = import_login_module("win32event")
        win32gui = import_login_module("win32gui")
        win32process = import_login_module("win32process")
        self.gui, self.process = win32gui, win32process
        self.timeout = timeout
        self.hwnd = None
        self.identity = None
        self.failure_hwnd = None
        self.session = None
        self.mutex = None
        self.messages = []
        self.should_cancel = lambda: False
        self.foreground_before = win32gui.GetForegroundWindow()
        expected = (directory / "XtItClient.exe").resolve()
        matches = []
        for process in psutil.process_iter(["name"]):
            try:
                if (process.info["name"] or "").lower() == "xtitclient.exe" and Path(process.exe()).resolve() == expected:
                    matches.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not matches:
            if expected_pid is not None and not psutil.pid_exists(expected_pid):
                raise QmtProcessExited("QMT process exited")
            raise QmtNotReady("QMT process is not ready")
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one running QMT for this binding directory")
        self.pid = matches[0].pid
        if expected_pid is not None and self.pid != expected_pid:
            raise RuntimeError("QMT process changed; stopping this login attempt")
        if strategy:
            _verify_environment_native(directory, strategy=True)
        else:
            _verify_environment_native(directory)
        self.mutex = win32event.CreateMutex(None, False, "Local\\CFQuantQmtComponentLogin_" + str(self.pid))
        acquired = win32event.WaitForSingleObject(self.mutex, 0)
        if acquired not in (0, 0x80):
            win32api.CloseHandle(self.mutex)
            self.mutex = None
            raise RuntimeError("Another component login is already running for this QMT")
        try:
            self.session = frida.attach(self.pid)
            modules = ["Qt5Core.dll", "Qt5Widgets.dll"]
            if not strategy:
                modules.append("LoginDialog.dll")
            readiness = self.session.create_script("rpc.exports.ready = () => %s.every(n => Process.findModuleByName(n) !== null);" % json.dumps(modules))
            readiness.load()
            ready = readiness.exports_sync.ready()
            readiness.unload()
            if not ready:
                raise QmtNotReady("QMT login modules are still loading")
            source = "" if strategy else Path(__file__).with_name("qmt_component_agent.js").read_text(encoding="utf-8")
            script = self.session.create_script(source + "\n" + agent_extension)
            script.on("message", lambda message, data: self.messages.append("agent_error") if message.get("type") == "error" else None)
            script.load()
            self.script, self.api = script, script.exports_sync
            self.existing_main = False
            self.main_hwnd = None
            for hwnd in self.windows():
                state = self.api.status(str(hwnd))["result"]
                if state.get("is_login"):
                    if self.hwnd is not None:
                        raise RuntimeError("Multiple login dialogs found")
                    self.hwnd = hwnd
                    self.identity = state["login_identity"]
                elif state.get("is_main"):
                    self.existing_main = True
                    self.main_hwnd = hwnd
            if self.hwnd is None and not self.existing_main:
                raise QmtNotReady("No supported login or main window found yet")
            self.minimized_before = bool(self.hwnd and self.gui.IsIconic(self.hwnd))
        except Exception:
            self.close()
            raise

    def windows(self):
        result = []
        def visit(hwnd, _):
            if self.process.GetWindowThreadProcessId(hwnd)[1] == self.pid and self.gui.IsWindowVisible(hwnd) and self.gui.GetClassName(hwnd).startswith("Qt"):
                result.append(hwnd)
        self.gui.EnumWindows(visit, None)
        return result

    def already_logged_in(self):
        if self.session.is_detached:
            raise QmtProcessExited("QMT automation session detached")
        if not self.existing_main or self.hwnd is not None:
            for hwnd in self.windows():
                if self.api.status(str(hwnd))["result"].get("is_main"):
                    self.existing_main, self.main_hwnd, self.hwnd = True, hwnd, None
                    break
        return self.existing_main and self.hwnd is None

    def state(self):
        state = self.api.status(str(self.hwnd))["result"]
        if not state.get("is_login") or state.get("login_identity") != self.identity:
            raise RuntimeError("Login window or selected account changed; stopping")
        state.pop("login_identity", None)
        for hwnd in self.windows():
            if hwnd != self.hwnd and hwnd != self.main_hwnd:
                kind = self.api.notice(str(hwnd))["result"].get("kind")
                if kind:
                    state["notice"] = kind
                    self.failure_hwnd = hwnd
                    break
        return state

    def select_account(self, account, replace=False):
        if self.already_logged_in():
            if account and not self.gui.GetWindowText(self.main_hwnd).startswith(account + " - "):
                raise RuntimeError("QMT 已登录的用户与配置的登录账号不一致，请重启该绑定 QMT")
            return
        if account and (replace or account != self.identity):
            self.api.selectaccount(str(self.hwnd), account, replace)
            self.identity = account
            # Managed login clears remembered contents even for the same user.
            self.api.fill(str(self.hwnd), "", False)

    def submit(self):
        state = self.state()
        if not state["has_password"] or not state["login_enabled"]:
            raise QmtNotReady("Login is not ready")
        if not self.api.submit(str(self.hwnd))["result"]["submitted"]:
            raise QmtNotReady("Login is not ready")

    def fill(self, password):
        self.state()
        self.api.fill(str(self.hwnd), password, False)

    def wait_outcome(self):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.should_cancel():
                return "cancelled"
            if self.session.is_detached:
                raise QmtProcessExited("QMT automation session detached")
            windows = self.windows()
            for hwnd in windows:
                caption = self.gui.GetWindowText(hwnd)
                if self.identity and caption.startswith(self.identity + " - "):
                    if self.api.status(str(hwnd))["result"].get("is_main"):
                        return "logged_in"
            for hwnd in windows:
                if hwnd == self.hwnd:
                    try:
                        state = self.state()
                    except Exception:
                        if not self.gui.IsWindow(hwnd) or not self.gui.IsWindowVisible(hwnd):
                            continue
                        raise
                    kind = state.get("notice")
                    if not state["login_enabled"]:
                        continue
                else:
                    kind = self.api.notice(str(hwnd))["result"].get("kind")
                if kind:
                    self.failure_hwnd = hwnd
                    return kind
            time.sleep(0.5)
        # A slow connection is not evidence of a wrong password. Never resubmit.
        return "timeout"

    def acknowledge_failure(self):
        if self.failure_hwnd and self.failure_hwnd != self.hwnd:
            self.api.acknowledge(str(self.failure_hwnd))
        self.failure_hwnd = None

    def close(self):
        try:
            from .qmt_dependencies import import_login_module
        except ImportError:
            from qmt_dependencies import import_login_module
        win32api = import_login_module("win32api")
        win32event = import_login_module("win32event")
        try:
            if self.session:
                self.session.detach()
                self.session = None
        finally:
            if self.mutex:
                win32event.ReleaseMutex(self.mutex)
                win32api.CloseHandle(self.mutex)
                self.mutex = None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "runtime/config/cfquant_web_config.json")
    parser.add_argument("--prompt", action="store_true", help="Read a needed password without echo; otherwise read one line of stdin")
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120:
        parser.error("timeout must be between 1 and 120 seconds")
    row, directory = select_binding(args.config, args.binding)
    backend = QtLoginBackend(directory, args.timeout)
    try:
        backend.select_account((row.get("qmt_auto_login") or {}).get("login_account", ""), replace=True)
        def read_password():
            return getpass.getpass("QMT password (hidden): ") if args.prompt else sys.stdin.readline().rstrip("\r\n")
        result = auto_login(backend, read_password)
        result.update(binding=args.binding, process_id=backend.pid,
                      minimized_before=backend.minimized_before,
                      foreground_before=backend.foreground_before,
                      foreground_after=backend.gui.GetForegroundWindow(),
                      script_errors=backend.messages,
                      input_method="Qt native methods; no keyboard/mouse input")
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.report:
            args.report.write_text(output, encoding="utf-8")
        print(output)
        return 0 if result["outcome"] in ("logged_in", "already_logged_in") else 1
    finally:
        backend.close()


def login_running_qmt(directory, login_account="", password_provider=lambda: "", expected_pid=None,
                      startup_timeout=60, timeout=40, *, should_cancel=lambda: False,
                      on_wait=lambda phase: None, before_poll=lambda: None):
    """Wait for QMT startup/updates and observe login until success or rejection.

    The web worker uses startup_timeout=None to wait while its process is alive.
    Cancellation stops waiting when that worker is disabled or superseded.
    """
    cancelled = should_cancel
    def should_cancel():
        if cancelled():
            return True
        before_poll()
        return cancelled()

    deadline = None if startup_timeout is None else time.monotonic() + startup_timeout
    backend = None
    while True:
        if should_cancel():
            return {"outcome": "cancelled", "login_succeeded": False, "attempts": []}
        try:
            backend = IsolatedLoginBackend(Path(directory), timeout, expected_pid=expected_pid,
                                           should_cancel=should_cancel)
            break
        except QmtAutomationCancelled:
            return {"outcome": "cancelled", "login_succeeded": False, "attempts": []}
        except QmtProcessExited:
            return {"outcome": "process_exited", "login_succeeded": False, "attempts": []}
        except QmtNotReady:
            if deadline is not None and time.monotonic() >= deadline:
                return {"outcome": "startup_timeout", "login_succeeded": False, "attempts": []}
            on_wait("waiting_ready")
            time.sleep(0.5)
    try:
        backend.should_cancel = should_cancel
        return auto_login(backend, password_provider, retry_not_ready=True, login_account=login_account,
                          should_cancel=should_cancel, on_wait=on_wait)
    except QmtAutomationCancelled:
        return {"outcome": "cancelled", "login_succeeded": False, "attempts": []}
    except QmtProcessExited:
        return {"outcome": "process_exited", "login_succeeded": False, "attempts": []}
    finally:
        backend.close()


if __name__ == "__main__":
    sys.exit(main())
