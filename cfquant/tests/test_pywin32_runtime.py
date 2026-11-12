"""DLL selection and package ownership regressions without altering Python."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfquant import _pywin32_runtime as runtime
from cfquant import qmt_dependencies


@pytest.fixture
def installation(monkeypatch, tmp_path):
    filename = "pywintypes%d%d.dll" % runtime.sys.version_info[:2]
    entry = Path("pywin32_system32") / filename
    selected = tmp_path / entry
    selected.parent.mkdir()
    selected.write_bytes(b"current build")
    distribution = SimpleNamespace(
        version="312", files=[entry], locate_file=lambda p: tmp_path / p,
        read_text=lambda name: "pip\n",
    )
    monkeypatch.setattr(runtime.importlib.metadata, "distribution", lambda name: distribution)
    monkeypatch.setattr(runtime.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime, "_STATE", None)
    monkeypatch.setattr(runtime, "_HANDLES", [])
    return distribution, selected


@pytest.mark.parametrize("record_name,version,installer,owned", [
    ("pywin32-ctypes", "0.2.2", "", False),
    ("pywin32", "306", "pip", False),
    ("pywin32", "312", "pip", False),
    ("pywin32", "306", "", False),
    ("pywin32", "312", "", True),
    ("pywin32", "312", "conda", True),
])
def test_repair_uses_actual_package_owner(installation, tmp_path, record_name, version, installer, owned):
    distribution, _ = installation
    distribution.read_text = lambda name: installer
    records = tmp_path / "conda-meta"
    records.mkdir()
    (records / (record_name + "-" + version + "-build.json")).write_text(
        json.dumps({"name": record_name, "version": version}), encoding="utf-8")
    ownership = runtime.pywin32_installation()
    assert ownership["conda_pywin32"] is owned
    report = qmt_dependencies._finish_report(dict(
        python_executable=str(tmp_path / "python.exe"), prefix=str(tmp_path),
        environment="conda", supported=True,
        checks=[{"name": "win32api", "ok": False, "error": "DLL load failed"}],
        **ownership,
    ))
    command = report["repair_commands"][0]
    assert ("install --prefix" in command) is owned
    assert ("-m pip" in command) is not owned
    assert not any("pywin32_postinstall" in c for c in report["repair_commands"])


def test_preload_package_dll_once_and_retain_handles(installation, monkeypatch, tmp_path):
    _, selected = installation
    # This leftover is deliberately absent from the current package manifest.
    stale = tmp_path / "win32" / selected.name
    stale.parent.mkdir()
    stale.write_bytes(b"old build")
    loaded = []
    directory = SimpleNamespace(close=lambda: pytest.fail("directory handle closed early"))
    library = object()
    monkeypatch.setattr(runtime, "_loaded_dll_path", lambda name: loaded[-1] if loaded else "")
    monkeypatch.setattr(runtime.os, "add_dll_directory", lambda path: directory, raising=False)

    def load(path):
        loaded.append(path)
        return library

    monkeypatch.setattr(runtime.ctypes, "WinDLL", load, raising=False)
    first = runtime.prepare_pywin32_runtime()
    assert runtime.prepare_pywin32_runtime() == first
    assert loaded == [str(selected)]
    assert first["loaded_dll"] == str(selected)
    assert runtime._HANDLES == [directory, library]


@pytest.mark.parametrize("same_build", [False, True])
def test_existing_dll_is_never_replaced(installation, monkeypatch, tmp_path, same_build):
    _, selected = installation
    loaded = tmp_path / selected.name
    loaded.write_bytes(selected.read_bytes() if same_build else b"old build")
    monkeypatch.setattr(runtime, "_loaded_dll_path", lambda name: str(loaded))
    monkeypatch.setattr(runtime.ctypes, "WinDLL", lambda *a: pytest.fail("second DLL loaded"), raising=False)
    if same_build:
        assert runtime.prepare_pywin32_runtime()["loaded_dll"] == str(loaded)
    else:
        with pytest.raises(ImportError) as error:
            runtime.prepare_pywin32_runtime()
        assert str(selected) in str(error.value) and str(loaded) in str(error.value)
        assert runtime._STATE is None


def test_missing_owned_dll_does_not_fall_back_to_stale_copy(installation, monkeypatch):
    _, selected = installation
    selected.unlink()
    monkeypatch.setattr(runtime.ctypes, "WinDLL", lambda *a: pytest.fail("stale DLL loaded"), raising=False)
    with pytest.raises(ImportError, match="pywin32"):
        runtime.prepare_pywin32_runtime()


def test_native_conda_layout_keeps_its_loader(installation, monkeypatch):
    distribution, _ = installation
    distribution.files = [Path("win32/pywintypes.dll")]
    monkeypatch.setattr(runtime.ctypes, "WinDLL", lambda *a: pytest.fail("unexpected DLL load"), raising=False)
    assert runtime.prepare_pywin32_runtime() == {}


def test_failed_load_closes_directory_and_can_retry(installation, monkeypatch):
    _, selected = installation
    closed = []
    monkeypatch.setattr(runtime, "_loaded_dll_path", lambda name: "")
    monkeypatch.setattr(runtime.os, "add_dll_directory", lambda path: SimpleNamespace(
        close=lambda: closed.append(path)), raising=False)

    def fail(path):
        raise OSError("missing runtime dependency")

    monkeypatch.setattr(runtime.ctypes, "WinDLL", fail, raising=False)
    with pytest.raises(OSError):
        runtime.prepare_pywin32_runtime()
    assert closed == [str(selected.parent)]
    assert runtime._STATE is None and not runtime._HANDLES


def test_login_import_prepares_dll_before_native_extension(monkeypatch):
    calls = []
    monkeypatch.setattr(qmt_dependencies, "prepare_pywin32_runtime", lambda: calls.append("prepare"))
    monkeypatch.setattr(qmt_dependencies.importlib, "import_module", lambda name: calls.append(name))
    qmt_dependencies.import_login_module("win32gui")
    assert calls == ["prepare", "win32gui"]


def test_login_import_reports_conflict_without_loading_extension(monkeypatch):
    def conflict():
        raise ImportError("conflicting pywintypes DLL")

    monkeypatch.setattr(qmt_dependencies, "prepare_pywin32_runtime", conflict)
    monkeypatch.setattr(qmt_dependencies.importlib, "import_module", lambda name: pytest.fail("unsafe import"))
    with pytest.raises(qmt_dependencies.QmtDependencyError, match="conflicting pywintypes"):
        qmt_dependencies.import_login_module("win32api")
