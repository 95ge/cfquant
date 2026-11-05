"""Private, bounded-lifetime files for native workers; never use system TEMP."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time
import uuid

import psutil


_SWEEP_LOCK = threading.Lock()
_LAST_SWEEP = {}
_WORKER_NAME = re.compile(r"worker-[0-9a-f]{32}\Z")


def worker_temp_root():
    configured = os.environ.get("CFQUANT_FRIDA_TEMP_DIR")
    if configured:
        return Path(os.path.expandvars(configured)).expanduser().resolve()
    runtime = os.environ.get("CFQUANT_RUNTIME_DIR")
    if runtime:
        return Path(os.path.expandvars(runtime)).expanduser().resolve() / "frida"
    base = (os.environ.get("CFQUANT_HOME") or os.environ.get("CFQUANT_STATE_DIR")
            or os.environ.get("CFQUANT_BASE_DIR") or str(Path(__file__).resolve().parents[1]))
    return Path(os.path.expandvars(base)).expanduser().resolve() / "runtime" / "frida"


def _process_alive(pid, created):
    try:
        return abs(psutil.Process(int(pid)).create_time() - float(created)) < 0.01
    except (psutil.NoSuchProcess, ValueError, TypeError):
        return False
    except psutil.AccessDenied:
        return True


def _linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0)
                                           & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def remove_worker_directory(root, directory):
    """Delete only a direct owned child; never traverse a symlink or junction."""
    root, directory = Path(root).resolve(), Path(directory)
    try:
        if (not _WORKER_NAME.fullmatch(directory.name) or _linked(directory)
                or directory.resolve().parent != root):
            return False
        for parent, directories, files in os.walk(directory, followlinks=False):
            if any(_linked(Path(parent) / name) for name in directories + files):
                return False
        # Keep the ownership marker until all possibly locked DLLs are gone.
        # A partial rmtree must not make a crashed worker's files uncollectable.
        marker = directory / "owner.json"
        for child in directory.iterdir():
            if child == marker:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        marker.unlink(missing_ok=True)
        directory.rmdir()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False  # Loaded DLLs can remain locked briefly; a later sweep retries.


def sweep_worker_directories(root, *, force=False):
    root = Path(root).resolve()
    now = time.time()
    with _SWEEP_LOCK:
        if not force and now - _LAST_SWEEP.get(str(root), 0) < 60:
            return
        _LAST_SWEEP[str(root)] = now
        if not root.is_dir():
            return
        for directory in root.iterdir():
            try:
                if (not _WORKER_NAME.fullmatch(directory.name) or _linked(directory)
                        or not directory.is_dir() or now - directory.stat().st_mtime < 60):
                    continue
                marker = directory / "owner.json"
                if _linked(marker):
                    continue
                owner = json.loads(marker.read_text(encoding="utf-8"))
                if owner.get("format") != "cfquant-native-worker-v1":
                    continue
                if not isinstance(owner.get("owner_pid"), int) or not isinstance(owner.get("owner_created"), (int, float)):
                    continue
                child = owner.get("child_pid")
                if child is not None and (not isinstance(child, int) or not isinstance(owner.get("child_created"), (int, float))):
                    continue
                # The parent's identity protects the mkdir/Popen registration window.
                if child is None:
                    alive = _process_alive(owner.get("owner_pid"), owner.get("owner_created"))
                else:
                    alive = _process_alive(child, owner.get("child_created"))
                if not alive:
                    remove_worker_directory(root, directory)
            except (OSError, ValueError, TypeError, AttributeError):
                continue


class NativeWorkerFiles:
    def __init__(self):
        self.root = worker_temp_root()
        self.root.mkdir(parents=True, exist_ok=True)
        sweep_worker_directories(self.root)
        self.path = self.root / ("worker-" + uuid.uuid4().hex)
        self.path.mkdir()
        self.owner = dict(format="cfquant-native-worker-v1", owner_pid=os.getpid(),
                          owner_created=psutil.Process().create_time())
        try:
            self._save()
        except Exception:
            self.close()
            raise

    def _save(self):
        marker = self.path / "owner.json"
        pending = marker.with_suffix(".pending")
        pending.write_text(json.dumps(self.owner), encoding="utf-8")
        pending.replace(marker)

    def register(self, pid):
        try:
            created = psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            created = 0  # The protocol reader reports an immediate child crash.
        self.owner.update(child_pid=pid, child_created=created)
        self._save()

    def environment(self):
        return {name: str(self.path) for name in ("TEMP", "TMP", "TMPDIR")}

    def close(self):
        return remove_worker_directory(self.root, self.path)
