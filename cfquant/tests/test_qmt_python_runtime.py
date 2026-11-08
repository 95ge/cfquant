import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from cfquant.qmt_python_runtime import (
    QmtPythonPackage,
    QmtPythonRuntime,
    QmtPythonRuntimeError,
)


def _package(runtime, archive):
    digest = hashlib.md5(archive.read_bytes()).hexdigest()
    return QmtPythonPackage(runtime, "2.0.3.12", "http://example.invalid/runtime.zip",
                            archive.name, digest, True)


def test_install_and_switch_python312(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    account = root / "userdata" / "users" / "55009948"
    account.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.33.0"/><python libs_path="%s" m_nPythonVersion="0" native_libs_path="x"/></root>' % bin_dir,
        encoding="utf-8",
    )
    manager = QmtPythonRuntime(root, account_id="55009948")
    archive = manager.download_dir / "python312x64-test.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python.exe", "python")
        bundle.writestr("python312.dll", "dll")
        bundle.writestr("Lib/site.py", "# test")
    package = _package("py312", archive)
    manager.install("py312", package=package)
    result = manager.switch_account("py312")
    assert (bin_dir / "python312" / "python.exe").is_file()
    assert 'm_nPythonVersion="1"' in (account / "Config.xml").read_text(encoding="utf-8")
    assert result["runtime"] == "py312"
    assert Path(result["backup"]).is_file()


def test_py36_install_merges_runtime_and_preserves_qmt_files(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    bin_dir.mkdir(parents=True)
    (bin_dir / "XtItClient.exe").write_bytes(b"qmt")
    (bin_dir / "python36.dll").write_bytes(b"old-dll")
    manager = QmtPythonRuntime(root)
    archive = manager.download_dir / "Python36x64-test.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("python36.dll", "new-dll")
        bundle.writestr("DLLs/_socket.pyd", "socket")
        bundle.writestr("Lib/site.py", "# test")
    package = _package("py36", archive)
    result = manager.install("py36", package=package)
    assert (bin_dir / "python36.dll").read_bytes() == b"new-dll"
    assert (bin_dir / "DLLs" / "_socket.pyd").read_bytes() == b"socket"
    assert (bin_dir / "Lib" / "site.py").is_file()
    assert (bin_dir / "XtItClient.exe").read_bytes() == b"qmt"
    assert result["installed"] is True
    assert json.loads((root / "config" / "pythonlibDownloadInfo.txt").read_text())['md5'] == package.md5


def test_binding_status_identifies_selected_runtime_without_network(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    account = root / "userdata" / "users" / "55009948"
    account.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    runtime_dir = bin_dir / "python312"
    runtime_dir.mkdir()
    (runtime_dir / "python.exe").write_bytes(b"python")
    (runtime_dir / "python312.dll").write_bytes(b"dll")
    (runtime_dir / "Lib").mkdir()
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.33.0"/><python libs_path="%s" m_nPythonVersion="1"/></root>' % runtime_dir,
        encoding="utf-8",
    )
    status = QmtPythonRuntime(root, account_id="55009948").binding_status()
    assert status["selected_runtime"] == "py312"
    assert status["state"] == "ready"
    assert status["python_library_downloaded"] is True
    assert status["runtimes"]["py312"]["installed"] is True


def test_binding_status_fixes_old_qmt_to_default_py36(tmp_path):
    root = tmp_path / "qmt"
    bin_dir = root / "bin.x64"
    account = root / "userdata" / "users" / "8885060548"
    account.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    (bin_dir / "python36.dll").write_bytes(b"dll")
    (bin_dir / "Lib").mkdir()
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.19.0"/><python libs_path="%s" m_nPythonVersion="1"/></root>' % (bin_dir / "python312"),
        encoding="utf-8",
    )
    status = QmtPythonRuntime(root, account_id="8885060548").binding_status()
    assert status["qmt_version"] == "2.1.19.0"
    assert status["py312_supported"] is False
    assert status["runtime_selection"] == "fixed_py36"
    assert status["available_runtimes"] == ["py36"]
    assert status["configured_runtime"] == "py312"
    assert status["selected_runtime"] == "py36"
    assert status["state"] == "ready"


def test_download_and_switch_rejects_py312_for_old_qmt(tmp_path):
    root = tmp_path / "qmt"
    account = root / "userdata" / "users" / "8885060548"
    account.mkdir(parents=True)
    (root / "bin.x64").mkdir(parents=True)
    (account / "Config.xml").write_text(
        '<root><Global version="2.1.19.0"/><python libs_path="x" m_nPythonVersion="0"/></root>',
        encoding="utf-8",
    )
    manager = QmtPythonRuntime(root, account_id="8885060548")
    with pytest.raises(QmtPythonRuntimeError, match="only supports.*py36"):
        manager.download_and_switch("py312")


def test_zip_slip_is_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "bad")
    with pytest.raises(QmtPythonRuntimeError, match="unsafe path"):
        QmtPythonRuntime._safe_extract(archive, tmp_path / "extract")
