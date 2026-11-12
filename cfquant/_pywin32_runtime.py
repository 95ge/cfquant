"""Select pywin32's own support DLL before importing its native extensions.

Keep this module stdlib-only: dependency probes load it by path in the selected
interpreter, without importing the rest of cfquant or any win32 extension.
"""

import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import threading


_LOCK = threading.Lock()
_HANDLES = []
_STATE = None


def pywin32_installation():
    """Conda records can survive a pip upgrade; pywin32-ctypes is unrelated."""
    try:
        distribution = importlib.metadata.distribution("pywin32")
    except importlib.metadata.PackageNotFoundError:
        return {"conda_pywin32": False}
    installer = (distribution.read_text("INSTALLER") or "").strip().lower()
    conda_version = ""
    for path in (Path(sys.prefix) / "conda-meta").glob("pywin32-*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("name") == "pywin32":
            conda_version = str(record.get("version") or "")
            break
    return {
        "pywin32_installer": installer,
        "conda_pywin32_version": conda_version,
        "conda_pywin32": bool(conda_version and conda_version == distribution.version
                              and installer != "pip"),
    }


def _loaded_dll_path(filename):
    # No win32api here: it is one of the modules that needs this DLL to work.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel32.GetModuleFileNameW.restype = ctypes.c_uint
    handle = kernel32.GetModuleHandleW(filename)
    if not handle:
        return ""
    buffer = ctypes.create_unicode_buffer(32768)
    if not kernel32.GetModuleFileNameW(handle, buffer, len(buffer)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def _same_dll(left, right):
    if left.samefile(right):
        return True
    # A postinstall copy is fine if it is byte-for-byte the same build.
    return hashlib.sha256(left.read_bytes()).digest() == hashlib.sha256(right.read_bytes()).digest()


def prepare_pywin32_runtime():
    """Preload the installed wheel's DLL; never replace an already loaded build.

Old Conda/postinstall copies can remain beside win32api.pyd or in Library/bin.
Adding a search directory alone cannot override those copies (or a DLL already
loaded by another module). Resolve the current distribution's manifest instead.
"""
    global _STATE
    if sys.platform != "win32":
        return {}
    with _LOCK:
        if _STATE is not None:
            return dict(_STATE)
        try:
            distribution = importlib.metadata.distribution("pywin32")
        except importlib.metadata.PackageNotFoundError:
            return {}  # Let the normal import report a missing package.
        filename = "pywintypes%d%d.dll" % sys.version_info[:2]
        expected = "pywin32_system32/" + filename
        entry = next((p for p in distribution.files or ()
                      if str(p).replace("\\", "/").lower() == expected.lower()), None)
        if entry is None:
            return {}  # A Conda-native layout owns its own DLL resolution.
        selected = Path(distribution.locate_file(entry)).resolve()
        if not selected.is_file():
            raise ImportError("pywin32 配套 DLL 缺失：%s；请重装当前环境的 pywin32。" % selected)
        loaded = _loaded_dll_path(filename)
        if loaded and not _same_dll(Path(loaded), selected):
            raise ImportError(
                "pywin32 DLL 版本冲突：当前进程已加载 %s，安装包配套 DLL 为 %s。"
                "请停止 CFQuant，修复当前环境后重新启动。" % (loaded, selected))
        if not loaded:
            # Retain both handles for the lifetime of the process. No PATH or
            # system directory changes and no DLL copies/deletions are needed.
            directory = os.add_dll_directory(str(selected.parent))
            try:
                dll = ctypes.WinDLL(str(selected))
            except OSError:
                directory.close()
                raise
            _HANDLES.extend((directory, dll))
            loaded = _loaded_dll_path(filename)
        _STATE = {"selected_dll": str(selected), "loaded_dll": loaded}
        return dict(_STATE)
