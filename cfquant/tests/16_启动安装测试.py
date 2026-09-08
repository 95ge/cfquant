# -*- coding: utf-8 -*-
import subprocess
from pathlib import Path

from cfquant import _editable_install


def test_editable_install_uses_split_arguments(tmp_path):
    command = _editable_install.editable_install_args(tmp_path, python_exe="python")

    assert command[:4] == ["python", "-m", "pip", "install"]
    assert "--editable" in command
    assert command[command.index("--editable") + 1] == "."
    assert "- e" not in subprocess.list2cmdline(command)
    assert "-e ." not in subprocess.list2cmdline(command)


def test_installed_check_runs_outside_project_tree(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(_editable_install, "neutral_check_cwd", lambda: tmp_path / "neutral")

    def fake_run(args, cwd, quiet=False, clear_pythonpath=False):
        calls.append((args, cwd, quiet, clear_pythonpath))

        class Result(object):
            returncode = 0

        return Result()

    monkeypatch.setattr(_editable_install, "run", fake_run)

    assert _editable_install.is_cfquant_installed("python") is True
    assert calls == [(
        ["python", "-c", _editable_install.INSTALLED_CHECK_CODE],
        tmp_path / "neutral",
        True,
        True,
    )]


def test_start_script_passes_dot_not_trailing_dp0():
    script = (Path(__file__).resolve().parents[2] / "start_cfquant.bat").read_text(encoding="utf-8")

    assert '"%PYTHON_EXE%" "%CFQUANT_INSTALL_HELPER%" .' in script
    assert '"%PYTHON_EXE%" "%CFQUANT_INSTALL_HELPER%" "%~dp0"' not in script
