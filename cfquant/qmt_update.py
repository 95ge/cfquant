"""Manage the binding's XtUpdate and installer using native dialog commands.

No mouse/keyboard events, foreground activation, or arbitrary installer discovery.
Only an updater belonging to this QMT and its verified installation children are
eligible. Unknown dialogs are left open and reported for manual attention.
"""
from dataclasses import dataclass, field
from pathlib import Path
import os
import subprocess
import time


class QmtUpdateError(RuntimeError):
    def __init__(self, outcome):
        self.outcome = outcome
        super().__init__(outcome)


class QmtUpdated(Exception):
    pass


@dataclass
class Dialog:
    hwnd: int
    pid: int
    title: str
    buttons: dict = field(default_factory=dict)
    texts: list = field(default_factory=list)
    progress: bool = False


def dialog_action(dialog, installer=False):
    """Classify observed native layouts; never answer an unrelated Yes/No box."""
    import re
    ids = set(dialog.buttons)
    if not installer:
        if dialog.title != "更新程序":
            return "unknown"
        if ids == {1003, 1007, 1008} and not any(dialog.buttons.values()):
            return "offer"
        if ids == {1003, 1005} and dialog.progress:
            return "download"
    elif {6, 7}.issubset(ids):
        text = " ".join(dialog.texts)
        if re.search(r"安装(完毕|完成)[，,。\s]*是否立即运行", text):
            return "installed"
    return "unknown"


class NativeDialogs:
    """Use stdlib Win32 bindings so password injection can remain disabled."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.user = c.WinDLL("user32", use_last_error=True)
        self.callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        signatures = {
            "EnumWindows": (w.BOOL, [self.callback_type, w.LPARAM]),
            "EnumChildWindows": (w.BOOL, [w.HWND, self.callback_type, w.LPARAM]),
            "GetWindowThreadProcessId": (w.DWORD, [w.HWND, c.POINTER(w.DWORD)]),
            "IsWindowVisible": (w.BOOL, [w.HWND]),
            "IsWindowEnabled": (w.BOOL, [w.HWND]),
            "IsWindow": (w.BOOL, [w.HWND]),
            "GetDlgCtrlID": (c.c_int, [w.HWND]),
            "GetDlgItem": (w.HWND, [w.HWND, c.c_int]),
            "GetWindowTextW": (c.c_int, [w.HWND, w.LPWSTR, c.c_int]),
            "GetClassNameW": (c.c_int, [w.HWND, w.LPWSTR, c.c_int]),
            "SendMessageTimeoutW": (c.c_ssize_t, [w.HWND, w.UINT, w.WPARAM, w.LPARAM,
                                                   w.UINT, w.UINT, c.POINTER(c.c_size_t)]),
        }
        for name, (ret, args) in signatures.items():
            function = getattr(self.user, name)
            function.restype, function.argtypes = ret, args

    def text(self, hwnd, class_name=False):
        buffer = self.c.create_unicode_buffer(4096)
        function = self.user.GetClassNameW if class_name else self.user.GetWindowTextW
        function(hwnd, buffer, len(buffer))
        return buffer.value

    def pid(self, hwnd):
        pid = self.w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, self.c.byref(pid))
        return pid.value

    def read(self, hwnd):
        dialog = Dialog(hwnd, self.pid(hwnd), self.text(hwnd))
        def child(control, _):
            if self.user.IsWindowVisible(control):
                cls = self.text(control, True)
                if cls == "Button" and self.user.IsWindowEnabled(control):
                    dialog.buttons[self.user.GetDlgCtrlID(control)] = self.text(control)
                elif cls == "Static":
                    dialog.texts.append(self.text(control))
                elif cls.startswith("ATL:") and self.text(control) == "UPDATER_Prgbar":
                    dialog.progress = True
            return True
        self.user.EnumChildWindows(hwnd, self.callback_type(child), 0)
        return dialog

    def windows(self, pids):
        result = []
        def visit(hwnd, _):
            if (self.pid(hwnd) in pids and self.user.IsWindowVisible(hwnd)
                    and self.text(hwnd, True) == "#32770"):
                result.append(self.read(hwnd))
            return True
        self.user.EnumWindows(self.callback_type(visit), 0)
        return result

    def answer(self, dialog, command, action, installer=False):
        # Recheck immediately before dispatch, including process ownership.
        current = self.read(dialog.hwnd)
        if current.pid != dialog.pid or dialog_action(current, installer) != action:
            raise QmtUpdateError("update_dialog_changed")
        if command not in current.buttons:
            raise QmtUpdateError("update_dialog_changed")
        button = self.user.GetDlgItem(dialog.hwnd, command)
        result = self.c.c_size_t()
        # WM_COMMAND invokes the dialog's existing command handler. No BM_CLICK,
        # SendInput, posted keystrokes, focus changes, or screen coordinates.
        ok = self.user.SendMessageTimeoutW(dialog.hwnd, 0x111, command, button, 2, 3000,
                                          self.c.byref(result))
        if not ok and self.user.IsWindow(dialog.hwnd):
            raise QmtUpdateError("update_command_failed")


def same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


class UpdateProcesses:
    def __init__(self, directory, pid):
        import psutil
        self.psutil = psutil
        self.directory = Path(directory).resolve()
        self.exe = self.directory / "XtItClient.exe"
        self.updater = self.directory / "XtUpdate.exe"
        self.qmt = psutil.Process(pid)
        if not same_path(self.qmt.exe(), self.exe):
            raise QmtUpdateError("update_process_changed")
        self.started = self.qmt.create_time()
        self.owners = {}  # PID -> (creation time, installer flag)
        self.native = NativeDialogs()
        self.launch = None

    @property
    def pid(self):
        return self.qmt.pid

    def scan(self):
        processes = list(self.psutil.process_iter(["name"]))
        # Register updater parents before considering children (iteration order
        # is not a process-tree order). Keep identities after parents exit.
        for process in processes:
            try:
                if (process.info["name"] or "").lower() != "xtupdate.exe":
                    continue
                if (same_path(process.exe(), self.updater)
                        and "ProcessID_%s" % self.pid in process.cmdline()
                        and process.create_time() >= self.started):
                    self.owners[process.pid] = (process.create_time(), False)
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                continue
        for process in processes:
            try:
                name = (process.info["name"] or "").lower()
                parent = self.owners.get(process.ppid()) if name.startswith("xtitclient_") else None
                if not parent or process.create_time() < parent[0]:
                    continue
                args = process.cmdline()
                destination = next((arg[3:] for arg in args[1:] if arg.startswith("/D=")), "")
                if destination and same_path(destination, self.directory.parent):
                    self.owners[process.pid] = (process.create_time(), True)
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                continue
        active = {}
        for pid, (created, installer) in self.owners.items():
            try:
                process = self.psutil.Process(pid)
                if process.is_running() and process.create_time() == created:
                    active[pid] = installer
            except self.psutil.NoSuchProcess:
                continue
        return active, self.native.windows(active)

    def answer(self, dialog, command, action, installer=False):
        created, owned_installer = self.owners[dialog.pid]
        process = self.psutil.Process(dialog.pid)
        if process.create_time() != created or owned_installer != installer:
            raise QmtUpdateError("update_process_changed")
        self.native.answer(dialog, command, action, installer)

    def restart(self):
        """Called only after the completion prompt AND installer process exit."""
        matches = []
        for process in self.psutil.process_iter(["name"]):
            try:
                if (process.info["name"] or "").lower() == "xtitclient.exe" and same_path(process.exe(), self.exe):
                    matches.append(process)
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                continue
        if len(matches) > 1:
            raise QmtUpdateError("update_process_changed")
        if matches and matches[0].pid == self.pid and matches[0].create_time() == self.started:
            self.qmt.terminate()
            try:
                self.qmt.wait(timeout=10)
            except self.psutil.TimeoutExpired:
                raise QmtUpdateError("update_restart_failed") from None
            matches = []
        if matches:
            new = matches[0]
            if new.create_time() <= self.started:
                raise QmtUpdateError("update_process_changed")
        else:
            self.launch = subprocess.Popen([str(self.exe)], cwd=str(self.directory))
            new = self.psutil.Process(self.launch.pid)
        self.qmt = new
        self.started = new.create_time()
        self.owners.clear()
        return new.pid


class UpdateMonitor:
    def __init__(self, processes, auto_update=False, should_cancel=lambda: False,
                 on_wait=lambda phase: None, on_pid=lambda pid: None, timeout=1800):
        self.processes, self.auto_update = processes, auto_update
        self.should_cancel, self.on_wait, self.on_pid = should_cancel, on_wait, on_pid
        self.timeout = timeout
        self.started = None
        self.accepted = False
        self.declined = False
        self.completed = False
        self.declined_completed = False
        self.handled = set()
        self.active = {}
        self.updates = 0
        self.missing_since = None

    def poll(self):
        if self.should_cancel():
            return False
        self.active, dialogs = self.processes.scan()
        if self.active and self.started is None:
            self.started = time.monotonic()
        if self.started is not None and time.monotonic() - self.started > self.timeout:
            raise QmtUpdateError("update_timeout")
        for dialog in dialogs:
            installer = self.active[dialog.pid]
            action = dialog_action(dialog, installer)
            key = (dialog.pid, dialog.hwnd, action)
            if key in self.handled:
                continue
            if self.should_cancel():
                return False
            if action == "offer":
                if self.auto_update and self.updates >= 2:
                    raise QmtUpdateError("update_restart_limit")
                self.processes.answer(dialog, 1007 if self.auto_update else 1008, action)
                self.accepted = self.auto_update
                self.declined = not self.auto_update
                self.on_wait("update_downloading" if self.auto_update else "update_skipped")
                self.handled.add(key)
            elif action == "download":
                if self.accepted:
                    self.on_wait("update_downloading")
            elif action == "installed":
                # The worker can attach after the download prompt has already
                # closed. Apply the configured default to this verified,
                # binding-owned completion dialog as well.
                if not self.accepted and not self.declined:
                    self.accepted = self.auto_update
                    self.declined = not self.auto_update
                # Finish the silent installer without letting it launch a second,
                # unmanaged QMT. Restart the exact binding after it has exited.
                if self.accepted:
                    self.on_wait("update_installing")
                self.processes.answer(dialog, 6 if self.accepted else 7, action, installer=True)
                self.completed = self.accepted
                self.declined_completed = self.declined
                self.on_wait("update_restarting" if self.accepted else "update_skipped")
                self.handled.add(key)
            else:
                raise QmtUpdateError("update_manual_required")
        if any(self.active.values()) and not self.completed:
            if not self.accepted and not self.declined:
                raise QmtUpdateError("update_manual_required")
            self.on_wait("update_installing")
        if (self.accepted or self.declined) and not self.active:
            if self.completed:
                if self.should_cancel():
                    return False
                new_pid = self.processes.restart()
                self.on_pid(new_pid)
                self.updates += 1
                self.accepted = self.completed = False
                self.started = self.missing_since = None
                self.handled.clear()
                raise QmtUpdated()
            if self.declined_completed:
                return False
            if self.declined:
                # The updater may close after the user chose “否” without
                # creating an installer. Continue the normal login path.
                return False
            # Updater exit and installer creation need not be seen in one poll.
            if self.missing_since is None:
                self.missing_since = time.monotonic()
            if time.monotonic() - self.missing_since > 15:
                raise QmtUpdateError("update_incomplete")
        else:
            self.missing_since = None
        return bool(self.active) and (self.accepted or self.declined)

    def before_poll(self):
        while not self.should_cancel() and self.poll():
            time.sleep(0.5)


def manage_qmt_startup(directory, pid, login, *, auto_update=False,
                       should_cancel=lambda: False, on_wait=lambda phase: None,
                       on_pid=lambda pid: None):
    """Supervise update/restart and rerun login only for the resulting new PID.

    login is None for a client with its own automatic login; no Qt injection or
    credential access happens in that mode. The worker continues observing the
    updater after login so its late dialogs cannot be left blocking the client.
    """
    processes = UpdateProcesses(directory, pid)
    monitor = UpdateMonitor(processes, auto_update, should_cancel, on_wait, on_pid)
    while not should_cancel():
        try:
            monitor.before_poll()
            if should_cancel():
                break
            if login is None:
                result = {"outcome": "client_login", "login_succeeded": False, "attempts": []}
                # A non-injected client may take time to spawn its updater.
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline or monitor.active:
                    if should_cancel():
                        break
                    monitor.before_poll()
                    time.sleep(0.5)
            else:
                result = login(processes.pid, monitor.before_poll)
                # Catch the updater in the gap between the final login poll and
                # completion, and continue handling any background download.
                monitor.before_poll()
                while monitor.active and not should_cancel():
                    on_wait("update_background")
                    time.sleep(0.5)
                    monitor.before_poll()
            if should_cancel():
                break
            return dict(result, pid=processes.pid, update_count=monitor.updates)
        except QmtUpdated:
            on_wait("waiting_ready")
            continue
        except QmtUpdateError as error:
            return {"outcome": error.outcome, "login_succeeded": False, "attempts": [], "pid": processes.pid}
    return {"outcome": "cancelled", "login_succeeded": False, "attempts": []}
