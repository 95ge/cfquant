from cfquant.qmt_update import Dialog, QmtUpdated, UpdateMonitor, dialog_action


def offer(pid=10, hwnd=1):
    return Dialog(hwnd, pid, "更新程序", {1003: "", 1007: "", 1008: ""})


def progress(pid=10, hwnd=1):
    return Dialog(hwnd, pid, "更新程序", {1003: "", 1005: ""}, progress=True)


def installed(pid=11, hwnd=2):
    return Dialog(hwnd, pid, "QMT 2.1.33.0 安装", {6: "是(&Y)", 7: "否(&N)"},
                  ["安装完毕，是否立即运行 QMT？"])


class FakeProcesses:
    def __init__(self, scans):
        self.scans, self.answers, self.restarts = iter(scans), [], 0
        self.owners = {10: (1, False), 11: (2, True)}

    def scan(self):
        return next(self.scans)

    def answer(self, dialog, command, action, installer=False):
        self.answers.append((dialog.pid, command, action, installer))

    def restart(self):
        self.restarts += 1
        return 99


def test_update_prompt_defaults_to_decline_and_never_restarts():
    process = FakeProcesses([
        ({10: False}, [offer()]),
        ({10: False}, [progress()]),
        ({11: True}, [installed()]),
        ({}, []),
    ])
    monitor = UpdateMonitor(process, auto_update=False)
    assert monitor.poll()
    assert monitor.poll()
    assert monitor.poll()
    assert not monitor.poll()
    assert process.answers == [(10, 1008, "offer", False), (11, 7, "installed", True)]
    assert process.restarts == 0


def test_update_prompt_download_install_and_restart_are_native_actions():
    process = FakeProcesses([
        ({10: False}, [offer()]),
        ({10: False}, [progress()]),
        ({11: True}, [installed()]),
        ({}, []),
    ])
    phases = []
    monitor = UpdateMonitor(process, auto_update=True, on_wait=phases.append)
    assert monitor.poll()
    assert monitor.poll()
    assert monitor.poll()
    try:
        monitor.poll()
    except QmtUpdated:
        pass
    else:
        raise AssertionError("expected controlled QMT restart")
    assert process.answers == [(10, 1007, "offer", False), (11, 6, "installed", True)]
    assert process.restarts == 1
    assert "update_downloading" in phases and "update_installing" in phases


def test_unknown_dialog_is_left_for_manual_attention():
    dialog = Dialog(10, 1, "更新程序", {6: "是", 7: "否"}, ["安装完毕"])
    assert dialog_action(dialog) == "unknown"
