import json
import os
from pathlib import Path
import time

import psutil
import pytest

from cfquant.qmt_native_files import (
    NativeWorkerFiles, remove_worker_directory, sweep_worker_directories, worker_temp_root,
)


@pytest.fixture(autouse=True)
def private_environment(monkeypatch, tmp_path):
    for name in ("CFQUANT_FRIDA_TEMP_DIR", "CFQUANT_RUNTIME_DIR", "CFQUANT_HOME",
                 "CFQUANT_STATE_DIR", "CFQUANT_BASE_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CFQUANT_BASE_DIR", str(tmp_path))


def test_files_default_to_project_and_do_not_change_parent_temp(tmp_path):
    old = {key: os.environ.get(key) for key in ("TEMP", "TMP", "TMPDIR")}
    files = NativeWorkerFiles()
    assert files.path.parent == tmp_path / "runtime" / "frida"
    assert files.environment() == {key: str(files.path) for key in old}
    assert {key: os.environ.get(key) for key in old} == old
    assert files.close() and not files.path.exists()


def test_managed_home_runtime_and_explicit_override_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("CFQUANT_HOME", str(tmp_path / "managed"))
    assert worker_temp_root() == tmp_path / "managed/runtime/frida"
    monkeypatch.setenv("CFQUANT_RUNTIME_DIR", str(tmp_path / "state"))
    assert worker_temp_root() == tmp_path / "state/frida"
    monkeypatch.setenv("CFQUANT_FRIDA_TEMP_DIR", str(tmp_path / "custom"))
    assert worker_temp_root() == tmp_path / "custom"


def age(files):
    old = time.time() - 120
    os.utime(files.path, (old, old))


def test_sweep_preserves_active_owner_and_worker_but_removes_dead_child():
    files = NativeWorkerFiles()
    (files.path / "frida-agent.dll").write_bytes(b"fixture")
    age(files)
    sweep_worker_directories(files.root, force=True)
    assert files.path.exists()  # The Popen registration window is protected.
    files.register(os.getpid())
    age(files)
    sweep_worker_directories(files.root, force=True)
    assert files.path.exists()
    files.owner["child_created"] = psutil.Process().create_time() - 100
    files._save()
    age(files)
    sweep_worker_directories(files.root, force=True)
    assert not files.path.exists()  # PID reuse is not mistaken for our worker.


def test_orphaned_unregistered_worker_is_collected_after_owner_exit():
    files = NativeWorkerFiles()
    files.owner["owner_created"] -= 100
    files._save()
    age(files)
    sweep_worker_directories(files.root, force=True)
    assert not files.path.exists()


def test_sweep_preserves_unknown_directories_and_invalid_markers(tmp_path):
    root = worker_temp_root()
    unknown = root / "unrelated"
    unknown.mkdir(parents=True)
    (unknown / "keep.txt").write_text("keep")
    files = NativeWorkerFiles()
    (files.path / "owner.json").write_text(json.dumps({"format": "cfquant-native-worker-v1"}))
    age(files)
    sweep_worker_directories(root, force=True)
    assert unknown.exists() and files.path.exists()
    assert not remove_worker_directory(root, unknown)
    assert not remove_worker_directory(root, tmp_path)
    files.close()


def test_cleanup_never_follows_directory_links(tmp_path):
    files = NativeWorkerFiles()
    outside = tmp_path / "outside"
    outside.mkdir()
    keep = outside / "keep.txt"
    keep.write_text("keep")
    link = files.path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are not permitted")
    assert not files.close() and keep.read_text() == "keep"
    link.unlink()
    assert files.close() and keep.exists()


def test_unwritable_private_root_does_not_fall_back_to_system_temp(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("file")
    monkeypatch.setenv("CFQUANT_FRIDA_TEMP_DIR", str(blocker / "native"))
    with pytest.raises(OSError):
        NativeWorkerFiles()


def test_locked_dll_keeps_owner_marker_for_later_recovery(monkeypatch):
    import cfquant.qmt_native_files as module
    files = NativeWorkerFiles()
    child = files.path / "frida-fixture"
    child.mkdir()
    (child / "frida-agent.dll").write_bytes(b"fixture")
    files.owner["owner_created"] -= 100
    files._save()
    with monkeypatch.context() as patch:
        def locked(path):
            raise PermissionError("DLL still unloading")
        patch.setattr(module.shutil, "rmtree", locked)
        assert not files.close()
    assert (files.path / "owner.json").exists()
    age(files)
    sweep_worker_directories(files.root, force=True)
    assert not files.path.exists()


def test_owner_record_failure_cleans_partially_created_directory(monkeypatch):
    def fail(self):
        raise OSError("disk full")
    monkeypatch.setattr(NativeWorkerFiles, "_save", fail)
    with pytest.raises(OSError, match="disk full"):
        NativeWorkerFiles()
    assert list(worker_temp_root().iterdir()) == []


def legacy_bundle(root, name='a' * 32):
    directory = root / ('frida-' + name)
    child = directory / 'x86_64'
    child.mkdir(parents=True)
    (child / 'frida-agent.dll').write_bytes(b'fixture')
    old = time.time() - 2 * 86400
    for path in (child / 'frida-agent.dll', child, directory):
        os.utime(path, (old, old))
    return directory


def test_legacy_cleanup_requires_known_layout_and_old_files(tmp_path):
    from cfquant.qmt_native_files import cleanup_legacy_frida_temp
    old = legacy_bundle(tmp_path)
    recent = legacy_bundle(tmp_path, 'b' * 32)
    os.utime(recent / 'x86_64/frida-agent.dll', None)
    unknown = legacy_bundle(tmp_path, 'c' * 32)
    (unknown / 'notes.txt').write_text('keep')
    result = cleanup_legacy_frida_temp(tmp_path)
    assert not old.exists()
    assert recent.exists() and unknown.exists()
    assert result['deleted_directories'] == 1
    assert result['deleted_bytes'] == len(b'fixture')


def test_legacy_cleanup_skips_locked_files_and_continues(tmp_path, monkeypatch):
    from cfquant.qmt_native_files import cleanup_legacy_frida_temp
    locked = legacy_bundle(tmp_path)
    other = legacy_bundle(tmp_path, 'b' * 32)
    unlink = Path.unlink
    def remove(path, *args, **kwargs):
        if locked in path.parents:
            raise PermissionError('loaded DLL')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', remove)
    result = cleanup_legacy_frida_temp(tmp_path)
    assert locked.exists() and not other.exists()
    assert result['failed_files'] == 1


def test_legacy_cleanup_never_follows_links(tmp_path):
    from cfquant.qmt_native_files import cleanup_legacy_frida_temp
    outside = tmp_path / 'outside'
    outside.mkdir()
    keep = outside / 'frida-agent.dll'
    keep.write_bytes(b'keep')
    directory = legacy_bundle(tmp_path)
    try:
        (directory / 'x86').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlinks unavailable')
    old = time.time() - 2 * 86400
    os.utime(directory, (old, old))
    cleanup_legacy_frida_temp(tmp_path)
    assert keep.read_bytes() == b'keep' and directory.exists()
