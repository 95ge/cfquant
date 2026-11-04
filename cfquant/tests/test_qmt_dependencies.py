import json
import subprocess

import pytest

from cfquant import qmt_dependencies


@pytest.mark.parametrize("version", ["17.25.0", "17.25.2", "18.0.0", "16.7.0"])
def test_importable_but_unvalidated_frida_is_rejected_and_repair_is_pinned(version):
    report = qmt_dependencies._finish_report({
        "python_executable": "C:/env/python.exe", "supported": True,
        "checks": [{"name": "frida", "ok": True}], "packages": {"frida": version},
    })
    assert not report["ok"]
    assert version in report["checks"][0]["error"]
    assert any("frida==17.16.4" in command for command in report["repair_commands"])
    assert not any("frida>=17" in command for command in report["repair_commands"])


def test_unsupported_frida_is_never_imported(monkeypatch):
    monkeypatch.setattr(qmt_dependencies.importlib.metadata, "version", lambda name: "17.25.0")
    monkeypatch.setattr(qmt_dependencies.importlib, "import_module", lambda name: pytest.fail("unsafe native import"))
    with pytest.raises(qmt_dependencies.QmtDependencyError, match="17.16.4"):
        qmt_dependencies.import_login_module("frida")


def test_compatibility_probe_rejects_version_before_loading_frida():
    # Execute the same probe in a real process with metadata/import stubs.
    script = """
import importlib, importlib.metadata
importlib.metadata.version = lambda name: '17.25.0'
def forbidden(name):
    raise BaseException('native module must not be imported')
importlib.import_module = forbidden
MODULES = ('frida',)
FRIDA_VERSION = '17.16.4'
""" + qmt_dependencies._PROBE_CODE
    import sys
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                            timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
    check = json.loads(result.stdout)["checks"][0]
    assert not check["ok"] and "17.16.4" in check["error"]


@pytest.mark.parametrize("pip_exit", [0, 1])
def test_launcher_repairs_frida_when_project_version_already_matches(monkeypatch, tmp_path, pip_exit):
    from cfquant import _editable_install as installer
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.2.59"', encoding="utf-8")
    monkeypatch.setattr(installer, "installed_package_version", lambda *a: "0.2.59")
    monkeypatch.setattr(installer, "report_startup_dependencies", lambda *a: {
        "supported": True, "packages": {"frida": "17.25.0"}})
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, pip_exit)
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.ensure_cfquant_installed(tmp_path, "C:/env/python.exe") == 0
    command, kwargs = calls[0]
    assert command[:3] == ["C:/env/python.exe", "-m", "pip"]
    assert "frida==17.16.4" in command
    assert kwargs["timeout"] == 120
    assert len(calls) == 1


def test_compatible_startup_does_not_reinstall_frida(monkeypatch):
    from cfquant import _editable_install as installer
    monkeypatch.setattr(installer, "report_startup_dependencies", lambda *a: {
        "supported": True, "packages": {"frida": "17.16.4"}})
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **kw: pytest.fail("unneeded installation"))
    installer.reconcile_startup_frida(".", "python")


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
