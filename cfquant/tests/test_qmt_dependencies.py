import json
import subprocess

from cfquant import qmt_dependencies


def test_dependency_probe_reports_loaded_modules_and_versions(monkeypatch):
    monkeypatch.setattr(qmt_dependencies.sys, "platform", "win32")
    qmt_dependencies._CACHE.clear()
    payload = {
        "python_executable": "C:/Python311/python.exe",
        "python_version": "3.11.9",
        "prefix": "C:/Python311",
        "environment": "python",
        "conda_pywin32": False,
        "supported": True,
        "checks": [
            {"name": "frida", "ok": True, "path": "frida.pyd"},
            {"name": "win32api", "ok": False, "error": "DLL load failed while importing win32api"},
        ],
        "packages": {"pywin32": "306", "frida": "17.16.4"},
    }
    monkeypatch.setattr(qmt_dependencies.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps(payload), stderr=""
    ))

    report = qmt_dependencies.check_login_dependencies("C:/Python311/python.exe", refresh=True)

    assert report["ok"] is False
    assert report["python_executable"] == "C:/Python311/python.exe"
    assert report["repair_commands"]
    assert report["repair_commands"][0].startswith("& 'C:/Python311/python.exe' -m pip install")
    assert "pywin32_postinstall" in report["repair_commands"][1]


def test_conda_dependency_failure_generates_conda_repair_command(monkeypatch):
    monkeypatch.setattr(qmt_dependencies.sys, "platform", "win32")
    qmt_dependencies._CACHE.clear()
    payload = {
        "python_executable": "C:/Miniconda/envs/qmt/python.exe",
        "python_version": "3.12.4",
        "prefix": "C:/Miniconda/envs/qmt",
        "environment": "conda",
        "conda_pywin32": True,
        "conda_executable": "C:/Miniconda/Scripts/conda.exe",
        "supported": True,
        "checks": [{"name": "win32api", "ok": False, "error": "DLL load failed"}],
        "packages": {"pywin32": "306", "frida": "17.16.4"},
    }
    monkeypatch.setattr(qmt_dependencies.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps(payload), stderr=""
    ))

    report = qmt_dependencies.check_login_dependencies(payload["python_executable"], refresh=True)

    assert report["repair_commands"][0].startswith("& 'C:/Miniconda/Scripts/conda.exe' install --prefix")
    assert "--force-reinstall" in report["repair_commands"][0]


def test_venv_dependency_failure_uses_that_interpreter_without_postinstall(monkeypatch):
    monkeypatch.setattr(qmt_dependencies.sys, "platform", "win32")
    qmt_dependencies._CACHE.clear()
    payload = {
        "python_executable": "C:/work/.venv/Scripts/python.exe",
        "python_version": "3.12.4",
        "prefix": "C:/work/.venv",
        "base_prefix": "C:/Python312",
        "environment": "venv",
        "global_python": False,
        "conda_pywin32": False,
        "supported": True,
        "checks": [{"name": "win32api", "ok": False, "error": "DLL load failed"}],
        "packages": {"pywin32": "306", "frida": "17.16.4"},
    }
    monkeypatch.setattr(qmt_dependencies.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps(payload), stderr=""
    ))

    report = qmt_dependencies.check_login_dependencies(payload["python_executable"], refresh=True)

    assert report["repair_commands"][0].startswith("& 'C:/work/.venv/Scripts/python.exe' -m pip install")
    assert not any("pywin32_postinstall" in command for command in report["repair_commands"])
    assert "venv" in report["repair_note"]


def test_conda_without_conda_package_uses_exact_python_pip(monkeypatch):
    monkeypatch.setattr(qmt_dependencies.sys, "platform", "win32")
    qmt_dependencies._CACHE.clear()
    payload = {
        "python_executable": "C:/Miniconda/envs/qmt/python.exe",
        "python_version": "3.12.4",
        "prefix": "C:/Miniconda/envs/qmt",
        "base_prefix": "C:/Miniconda",
        "environment": "conda",
        "global_python": False,
        "conda_pywin32": False,
        "supported": True,
        "checks": [{"name": "win32api", "ok": False, "error": "DLL load failed"}],
        "packages": {"pywin32": "306", "frida": "17.16.4"},
    }
    monkeypatch.setattr(qmt_dependencies.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps(payload), stderr=""
    ))

    report = qmt_dependencies.check_login_dependencies(payload["python_executable"], refresh=True)

    assert report["repair_commands"][0].startswith("& 'C:/Miniconda/envs/qmt/python.exe' -m pip install")
