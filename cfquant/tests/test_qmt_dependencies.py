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
    assert "pip install" in report["repair_commands"][0]


def test_conda_dependency_failure_generates_conda_repair_command(monkeypatch):
    monkeypatch.setattr(qmt_dependencies.sys, "platform", "win32")
    qmt_dependencies._CACHE.clear()
    payload = {
        "python_executable": "C:/Miniconda/envs/qmt/python.exe",
        "python_version": "3.12.4",
        "prefix": "C:/Miniconda/envs/qmt",
        "environment": "conda",
        "conda_pywin32": True,
        "supported": True,
        "checks": [{"name": "win32api", "ok": False, "error": "DLL load failed"}],
        "packages": {"pywin32": "306", "frida": "17.16.4"},
    }
    monkeypatch.setattr(qmt_dependencies.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps(payload), stderr=""
    ))

    report = qmt_dependencies.check_login_dependencies(payload["python_executable"], refresh=True)

    assert report["repair_commands"][0].startswith("conda install --prefix")
    assert "--force-reinstall" in report["repair_commands"][0]
