# -*- coding: utf-8 -*-
import subprocess
from pathlib import Path

from cfquant import _editable_install
from cfquant import cli


def test_editable_install_uses_split_arguments(tmp_path):
    command = _editable_install.editable_install_args(tmp_path, python_exe="python")

    assert command[:4] == ["python", "-m", "pip", "install"]
    assert command[command.index("--index-url") + 1] == _editable_install.DEFAULT_PIP_INDEX_URL
    assert "--editable" in command
    assert command[command.index("--editable") + 1] == "."
    assert "- e" not in subprocess.list2cmdline(command)
    assert "-e ." not in subprocess.list2cmdline(command)


def test_editable_install_allows_pip_index_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CFQUANT_PIP_INDEX_URL", "https://pypi.example.test/simple")

    command = _editable_install.editable_install_args(tmp_path, python_exe="python")

    assert command[command.index("--index-url") + 1] == "https://pypi.example.test/simple"


def test_requirements_uses_tsinghua_mirror():
    requirements = (Path(__file__).resolve().parents[2] / "requirements.txt").read_text(
        encoding="utf-8"
    )

    assert "--index-url https://pypi.tuna.tsinghua.edu.cn/simple" in requirements


def test_run_command_is_a_serve_alias(capsys):
    assert cli.main(["run", "--dry-run"]) == 0
    assert "cfquant 启动参数预览" in capsys.readouterr().out


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


def test_run_editable_install_reports_success(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'cfquant'\n", encoding="utf-8")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

        class Result(object):
            returncode = 0
            stdout = "Successfully installed cfquant-0.2.13\n"

        return Result()

    monkeypatch.setattr(_editable_install.subprocess, "run", fake_run)
    result = _editable_install.run_editable_install(
        tmp_path,
        python_exe="python",
        timeout=12,
    )

    assert result["attempted"] is True
    assert result["ok"] is True
    assert result["returncode"] == 0
    assert calls[0][0][:4] == ["python", "-m", "pip", "install"]
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["timeout"] == 12.0


def test_run_editable_install_reports_failure(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'cfquant'\n", encoding="utf-8")

    def fake_run(args, **kwargs):
        class Result(object):
            returncode = 7
            stdout = "pip failed\n"

        return Result()

    monkeypatch.setattr(_editable_install.subprocess, "run", fake_run)
    result = _editable_install.run_editable_install(tmp_path, python_exe="python")

    assert result["attempted"] is True
    assert result["ok"] is False
    assert result["returncode"] == 7
    assert "pip failed" in result["output"]


def test_start_script_passes_dot_not_trailing_dp0():
    script = (Path(__file__).resolve().parents[2] / "start_cfquant.bat").read_text(encoding="utf-8")

    assert '"%PYTHON_EXE%" "%CFQUANT_INSTALL_HELPER%" .' in script
    assert '"%PYTHON_EXE%" "%CFQUANT_INSTALL_HELPER%" "%~dp0"' not in script
