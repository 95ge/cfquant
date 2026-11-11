"""Manage the Python 3.6/3.12 runtime shipped with a QMT installation.

QMT downloads these runtimes from a small ``update*.cfg`` file.  The native
client does not expose its downloader to Python, so this module implements the
same public contract (configuration, HTTP range resume, MD5 verification and
atomic activation) without touching a live runtime until QMT has been stopped.

The class is deliberately independent from ``xttrader`` and from the web
server.  A caller can use it as a small local API, or provide a restart
callback when the surrounding application owns QMT lifecycle management.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Dict, Optional
import urllib.error
import urllib.request
import zipfile


class QmtPythonRuntimeError(RuntimeError):
    """A download, validation, activation, or restart operation failed."""


@dataclass(frozen=True)
class QmtPythonPackage:
    runtime: str
    version: str
    url: str
    filename: str
    md5: str
    force_update: bool = False

    def as_dict(self):
        return asdict(self)


@dataclass
class QmtPythonProgress:
    runtime: str
    phase: str
    bytes_done: int = 0
    bytes_total: int = 0
    percent: float = 0.0
    speed: float = 0.0
    eta: Optional[float] = None
    message: str = ""

    def as_dict(self):
        return asdict(self)


_CONFIG_NAMES = {"py36": "update36.cfg", "py312": "updateQMT312.cfg"}
_RUNTIME_ALIASES = {"36": "py36", "3.6": "py36", "python36": "py36",
                    "312": "py312", "3.12": "py312", "python312": "py312"}
_PY312_MIN_QMT_VERSION = (2, 1, 33, 0)
_CONFIG_LOCKS: Dict[str, threading.RLock] = {}
_CONFIG_LOCKS_GUARD = threading.Lock()


def _canonical_runtime(runtime: str) -> str:
    value = str(runtime or "").strip().lower()
    value = _RUNTIME_ALIASES.get(value, value)
    if value not in _CONFIG_NAMES:
        raise ValueError("runtime must be py36 or py312")
    return value


def _callback(callback, progress: QmtPythonProgress):
    if callback:
        callback(progress.as_dict())


def _version_tuple(value):
    """Parse a QMT version into a comparable four-part tuple.

    QMT has used both dotted versions (``2.1.33.0``) and build strings in
    different files.  Unknown values deliberately return ``None`` so callers
    can choose the conservative py36 runtime.
    """
    match = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?\s*", str(value or ""))
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


class QmtPythonRuntime:
    """Download and activate a QMT Python runtime.

    ``qmt_dir`` is the QMT installation directory (the parent of
    ``bin.x64``).  ``account_id`` is optional; when supplied, activation also
    changes that account's ``Config.xml`` to use the selected runtime.
    """

    def __init__(self, qmt_dir, *, account_id=None, timeout=60, opener=None):
        root = Path(qmt_dir).expanduser().resolve()
        if root.name.lower() == "bin.x64":
            self.bin_dir = root
            self.qmt_dir = root.parent
        else:
            self.qmt_dir = root
            self.bin_dir = root / "bin.x64"
        self.account_id = str(account_id) if account_id is not None else None
        self.timeout = float(timeout)
        self.state_dir = self.bin_dir / ".cfquant_python_runtime"
        self.download_dir = self.state_dir / "downloads"
        self.staging_dir = self.state_dir / "staging"
        self.backup_dir = self.state_dir / "backups"
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._lock = self._lock_for(str(self.bin_dir))

    @staticmethod
    def _lock_for(key):
        with _CONFIG_LOCKS_GUARD:
            return _CONFIG_LOCKS.setdefault(key, threading.RLock())

    @property
    def config_dir(self):
        return self.qmt_dir / "config"

    def _request(self, url, *, headers=None, timeout=None):
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        return self._opener.open(request, timeout=timeout or self.timeout)

    def fetch_package(self, runtime="py312") -> QmtPythonPackage:
        runtime = _canonical_runtime(runtime)
        cfg_url = "http://download.thinktrader.net:8800/download/" + _CONFIG_NAMES[runtime]
        try:
            with self._request(cfg_url) as response:
                raw = response.read().decode("utf-8-sig")
        except (OSError, urllib.error.URLError) as exc:
            raise QmtPythonRuntimeError("cannot fetch QMT runtime configuration: %s" % exc) from exc
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(raw)
            section = parser["python"]
            package = QmtPythonPackage(
                runtime=runtime,
                version=section.get("version", "").strip(),
                url=section.get("url", "").strip(),
                filename=Path(section.get("filename", "")).name,
                md5=section.get("md5", "").strip().lower(),
                force_update=section.getboolean("isforceupdate", fallback=False),
            )
        except (configparser.Error, KeyError, ValueError) as exc:
            raise QmtPythonRuntimeError("invalid QMT runtime configuration") from exc
        if not package.url or not package.filename or not re.fullmatch(r"[0-9a-f]{32}", package.md5):
            raise QmtPythonRuntimeError("QMT runtime configuration is incomplete")
        return package

    def _target_dir(self, runtime):
        return self.bin_dir if runtime == "py36" else self.bin_dir / "python312"

    def _marker_path(self):
        return self.config_dir / "pythonlibDownloadInfo.txt"

    def _metadata_path(self, runtime):
        return self.state_dir / (runtime + ".json")

    def _client_version(self):
        """Read the installed client's file version when Windows exposes it."""
        executable = self.bin_dir / "XtItClient.exe"
        if not executable.is_file():
            return ""
        try:
            import win32api
            info = win32api.GetFileVersionInfo(str(executable), "\\")
            ms = int(info.get("FileVersionMS", 0))
            ls = int(info.get("FileVersionLS", 0))
            return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
        except Exception:
            return ""

    def _read_metadata(self, runtime):
        try:
            return json.loads(self._metadata_path(runtime).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    def inspect(self, runtime="py312", *, refresh_remote=True):
        runtime = _canonical_runtime(runtime)
        package = None
        remote_error = None
        if refresh_remote:
            try:
                package = self.fetch_package(runtime)
            except QmtPythonRuntimeError as exc:
                remote_error = str(exc)
        target = self._target_dir(runtime)
        if runtime == "py312":
            required = [target / "python.exe", target / "python312.dll", target / "Lib"]
        else:
            required = [self.bin_dir / "python36.dll", self.bin_dir / "Lib"]
        installed = all(path.exists() for path in required)
        metadata = self._read_metadata(runtime)
        marker = ""
        try:
            marker = self._marker_path().read_text(encoding="utf-8").strip()
        except OSError:
            pass
        expected_md5 = package.md5 if package else metadata.get("md5", "")
        archive_name = package.filename if package else metadata.get("filename", "")
        if not archive_name and self.download_dir.is_dir():
            # A download can be completed before activation, so there may be
            # no runtime metadata yet.  There is one package per runtime in
            # this directory; exposing the newest zip keeps local inspection
            # useful without another network request.
            candidates = list(self.download_dir.glob("*.zip"))
            if candidates:
                archive_name = max(candidates, key=lambda path: path.stat().st_mtime).name
        archive = self.download_dir / archive_name if archive_name else self.download_dir / ""
        archive_md5 = self._md5(archive) if archive.is_file() else ""
        return {
            "qmt_dir": str(self.qmt_dir), "bin_dir": str(self.bin_dir),
            "account_id": self.account_id, "runtime": runtime,
            "target_dir": str(target), "installed": installed,
            "required_files": [str(path) for path in required],
            "version": package.version if package else metadata.get("version", ""),
            "package": package.as_dict() if package else None,
            "expected_md5": expected_md5, "archive": str(archive),
            "archive_exists": archive.is_file(), "archive_md5": archive_md5,
            "marker_md5": marker, "metadata": metadata,
            "remote_error": remote_error,
        }

    def binding_status(self, *, account_id=None):
        """Return the local Python-library state used by a QMT binding.

        This intentionally performs no network request.  Binding should be
        able to report a missing runtime even when the QMT download service is
        temporarily unavailable.
        """
        account = str(account_id if account_id is not None else self.account_id or "").strip()
        config = self.qmt_dir / "userdata" / "users" / account / "Config.xml" if account else None
        selected = None
        configured_runtime = None
        qmt_version = ""
        qmt_version_source = ""
        config_error = ""
        config_text = ""
        if not config or not config.is_file():
            config_error = "account_config_missing"
        else:
            try:
                config_text = config.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                config_error = "account_config_unreadable"
        if config_text:
            qmt_version_match = re.search(
                r'<Global\b[^>]*\bversion="([^"]+)"', config_text, flags=re.IGNORECASE
            )
            if qmt_version_match:
                qmt_version = qmt_version_match.group(1).strip()
                qmt_version_source = "Config.xml"
            version = re.search(r'\bm_nPythonVersion="([01])"', config_text)
            libs_path = re.search(r'\blibs_path="([^"]*)"', config_text)
            if version:
                configured_runtime = "py312" if version.group(1) == "1" else "py36"
            elif libs_path and Path(libs_path.group(1).replace("/", os.sep)).name.lower() == "python312":
                configured_runtime = "py312"
            elif libs_path:
                configured_runtime = "py36"
        client_version = self._client_version()
        if client_version:
            qmt_version = client_version
            qmt_version_source = "XtItClient.exe"
        parsed_qmt_version = _version_tuple(qmt_version)
        py312_supported = bool(
            parsed_qmt_version is not None and parsed_qmt_version >= _PY312_MIN_QMT_VERSION
        )
        # Older QMT clients have no Python 3.12 selector.  Missing or
        # malformed version metadata is treated the same way, which keeps a
        # binding on the native/default py36 runtime until it is verified.
        if configured_runtime:
            selected = configured_runtime if py312_supported or configured_runtime == "py36" else "py36"
        elif not py312_supported:
            selected = "py36"
        inspected = {
            runtime: self.inspect(runtime, refresh_remote=False)
            for runtime in ("py36", "py312")
        }
        selected_state = inspected.get(selected) if selected else None

        def summary(item):
            if not item:
                return None
            return {
                "runtime": item["runtime"],
                "target_dir": item["target_dir"],
                "installed": item["installed"],
                "required_files": item["required_files"],
                "version": item["version"],
                "marker_md5": item["marker_md5"],
                "archive_exists": item["archive_exists"],
                "expected_md5": item["expected_md5"],
            }

        runtimes = {runtime: summary(item) for runtime, item in inspected.items()}
        if config_error:
            state = config_error
        elif selected_state and selected_state["installed"]:
            state = "ready"
        elif selected:
            state = "python_library_missing"
        else:
            state = "runtime_not_selected"
        runtime_selection = "selectable" if py312_supported else "fixed_py36"
        available_runtimes = ["py36", "py312"] if py312_supported else ["py36"]
        return {
            "account_id": account,
            "config": str(config) if config else "",
            "config_exists": bool(config and config.is_file()),
            "qmt_version": qmt_version,
            "qmt_version_source": qmt_version_source,
            "py312_supported": py312_supported,
            "runtime_selection": runtime_selection,
            "available_runtimes": available_runtimes,
            "configured_runtime": configured_runtime,
            "selected_runtime": selected,
            "state": state,
            "python_library_downloaded": bool(selected_state and selected_state["installed"]),
            "selected": summary(selected_state),
            "runtimes": runtimes,
        }

    @staticmethod
    def _md5(path, chunk_size=1024 * 1024):
        digest = hashlib.md5()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def download(self, runtime="py312", *, progress_callback=None, cancel_event=None,
                 package=None, keep_existing=True):
        runtime = _canonical_runtime(runtime)
        package = package or self.fetch_package(runtime)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        destination = self.download_dir / package.filename
        partial = destination.with_suffix(destination.suffix + ".part")
        with self._lock:
            if destination.is_file() and self._md5(destination) == package.md5:
                _callback(progress_callback, QmtPythonProgress(
                    runtime, "download_verified", destination.stat().st_size,
                    destination.stat().st_size, 100, 0, 0, "download already verified"))
                return destination
            existing = partial.stat().st_size if partial.exists() and keep_existing else 0
            if not existing and not keep_existing and partial.exists():
                partial.unlink()
            headers = {"Accept-Encoding": "identity"}
            if existing:
                headers["Range"] = "bytes=%d-" % existing
            try:
                response = self._request(package.url, headers=headers)
            except (OSError, urllib.error.URLError) as exc:
                raise QmtPythonRuntimeError("cannot download QMT runtime: %s" % exc) from exc
            status = getattr(response, "status", response.getcode())
            if status == 206 and existing:
                mode, done = "ab", existing
            elif status == 200:
                mode, done = "wb", 0
            else:
                response.close()
                raise QmtPythonRuntimeError("unexpected QMT download HTTP status: %s" % status)
            total_header = response.headers.get("Content-Range", "").split("/")[-1]
            total = int(total_header) if total_header.isdigit() else int(response.headers.get("Content-Length") or 0) + done
            started = time.monotonic()
            _callback(progress_callback, QmtPythonProgress(runtime, "download", done, total,
                                                            (done / total * 100) if total else 0,
                                                            0, None, "downloading"))
            try:
                with response, open(partial, mode) as stream:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise QmtPythonRuntimeError("QMT runtime download cancelled")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        stream.write(chunk)
                        done += len(chunk)
                        elapsed = max(time.monotonic() - started, 0.001)
                        speed = (done - (existing if mode == "ab" else 0)) / elapsed
                        eta = ((total - done) / speed) if speed > 0 and total else None
                        _callback(progress_callback, QmtPythonProgress(
                            runtime, "download", done, total,
                            (done / total * 100) if total else 0, speed, eta, "downloading"))
                    stream.flush()
                    os.fsync(stream.fileno())
            except QmtPythonRuntimeError:
                raise
            except OSError as exc:
                raise QmtPythonRuntimeError("cannot write QMT runtime download: %s" % exc) from exc
            actual = self._md5(partial)
            if actual != package.md5:
                raise QmtPythonRuntimeError("QMT runtime MD5 mismatch: expected %s, got %s" %
                                             (package.md5, actual))
            os.replace(partial, destination)
            _callback(progress_callback, QmtPythonProgress(runtime, "download_verified",
                                                            total or destination.stat().st_size,
                                                            total or destination.stat().st_size,
                                                            100, 0, 0, "download verified"))
        return destination

    @staticmethod
    def _safe_extract(archive, destination):
        destination = Path(destination).resolve()
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                member = (destination / item.filename).resolve()
                if os.path.commonpath([str(destination), str(member)]) != str(destination):
                    raise QmtPythonRuntimeError("unsafe path in QMT runtime archive")
            bundle.extractall(destination)

    def _normalise_extracted(self, extracted, runtime):
        extracted = Path(extracted)
        entries = list(extracted.iterdir())
        if len(entries) == 1 and entries[0].is_dir() and entries[0].name.lower() in (runtime, "python312", "python36"):
            source = entries[0]
        else:
            source = extracted
        target = self._target_dir(runtime)
        install = extracted.parent / (runtime + "-install")
        if install.exists():
            shutil.rmtree(install)
        install.mkdir(parents=True)
        for item in source.iterdir():
            shutil.move(str(item), str(install / item.name))
        return install, target

    def install(self, runtime="py312", *, package=None, progress_callback=None):
        runtime = _canonical_runtime(runtime)
        package = package or self.fetch_package(runtime)
        archive = self.download_dir / package.filename
        if not archive.is_file() or self._md5(archive) != package.md5:
            raise QmtPythonRuntimeError("verified QMT runtime archive is missing")
        with self._lock:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            extracted = self.staging_dir / (runtime + "-extract")
            if extracted.exists():
                shutil.rmtree(extracted)
            extracted.mkdir()
            _callback(progress_callback, QmtPythonProgress(runtime, "extract", 0, 0, 0, 0, None, "extracting"))
            self._safe_extract(archive, extracted)
            install, target = self._normalise_extracted(extracted, runtime)
            if runtime == "py312":
                required = [install / "python.exe", install / "python312.dll", install / "Lib"]
            else:
                required = [install / "python36.dll", install / "Lib"]
            if not all(path.exists() for path in required):
                raise QmtPythonRuntimeError("QMT runtime archive has an unexpected layout")
            backup = None
            if runtime == "py312":
                if target.exists():
                    self.backup_dir.mkdir(parents=True, exist_ok=True)
                    backup = self.backup_dir / (runtime + "-" + time.strftime("%Y%m%d-%H%M%S") + "-%03d" % (int(time.time() * 1000) % 1000))
                    os.replace(target, backup)
                try:
                    os.replace(install, target)
                except Exception:
                    if backup and backup.exists() and not target.exists():
                        os.replace(backup, target)
                    raise
            else:
                # py36 is the native runtime in older QMT versions and lives
                # directly under bin.x64.  Merge only the files supplied by
                # the archive so the QMT client and its other DLLs remain in
                # place.  Existing files are moved to a per-install backup
                # before they are replaced.
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                backup = self.backup_dir / (runtime + "-" + time.strftime("%Y%m%d-%H%M%S") + "-%03d" % (int(time.time() * 1000) % 1000))
                backup.mkdir(parents=True, exist_ok=True)
                try:
                    for source in sorted(install.rglob("*")):
                        if not source.is_file():
                            continue
                        relative = source.relative_to(install)
                        destination = target / relative
                        saved = backup / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if destination.is_file():
                            saved.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(destination), str(saved))
                        elif destination.exists():
                            raise QmtPythonRuntimeError(
                                "cannot replace QMT runtime path: %s" % destination
                            )
                        shutil.copy2(source, destination)
                    marker = self._marker_path()
                    if marker.exists():
                        saved_marker = backup / "config" / "pythonlibDownloadInfo.txt"
                        saved_marker.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(marker, saved_marker)
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(json.dumps({
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "md5": package.md5,
                    }, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    # The files that were moved are recoverable from the
                    # backup directory.  Leave the backup in place for an
                    # operator to restore if a copy fails midway.
                    raise
            metadata = package.as_dict()
            metadata.update({"installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "target_dir": str(target), "backup": str(backup) if backup else None})
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_path(runtime).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            _callback(progress_callback, QmtPythonProgress(runtime, "installed", 1, 1, 100, 0, 0, "runtime installed"))
        return self.inspect(runtime, refresh_remote=False)

    def switch_account(self, runtime="py312", *, account_id=None):
        runtime = _canonical_runtime(runtime)
        account = str(account_id if account_id is not None else self.account_id) if (account_id is not None or self.account_id is not None) else None
        if not account:
            raise QmtPythonRuntimeError("account_id is required to switch QMT Python runtime")
        self.validate_selection(runtime, account_id=account)
        if not self.inspect(runtime, refresh_remote=False)["installed"]:
            raise QmtPythonRuntimeError("QMT Python library is not installed: %s" % runtime)
        config = self.qmt_dir / "userdata" / "users" / account / "Config.xml"
        if not config.is_file():
            raise QmtPythonRuntimeError("QMT account Config.xml not found: %s" % account)
        text = config.read_text(encoding="utf-8")
        path_value = (self.bin_dir / "python312" if runtime == "py312" else self.bin_dir).as_posix()
        if not re.search(r"<python\b[^>]*>", text):
            raise QmtPythonRuntimeError("QMT account Config.xml has no python settings")
        if not re.search(r'<python\b[^>]*\blibs_path="[^"]*"', text):
            raise QmtPythonRuntimeError("cannot update QMT python libs_path")
        updated = re.sub(r'(<python\b[^>]*\blibs_path=")[^"]*(")', r'\g<1>' + path_value + r'\2', text, count=1)
        if re.search(r'(<python\b[^>]*\bm_nPythonVersion=")[^"]*(")', updated):
            updated = re.sub(r'(<python\b[^>]*\bm_nPythonVersion=")[^"]*(")', r'\g<1>' + ("1" if runtime == "py312" else "0") + r'\2', updated, count=1)
        else:
            updated = re.sub(r'(<python\b)', r'\1 m_nPythonVersion="%s"' % ("1" if runtime == "py312" else "0"), updated, count=1)
        if updated == text:
            return {"account_id": account, "runtime": runtime, "config": str(config),
                    "backup": None, "libs_path": path_value, "unchanged": True}
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backup_dir / ("Config-%s-%s.xml" % (account, time.strftime("%Y%m%d-%H%M%S")))
        shutil.copy2(config, backup)
        temporary = config.with_suffix(".cfquant.tmp")
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, config)
        return {"account_id": account, "runtime": runtime, "config": str(config), "backup": str(backup), "libs_path": path_value}

    def _qmt_processes(self):
        try:
            import psutil
        except ImportError as exc:
            raise QmtPythonRuntimeError("psutil is required to restart QMT") from exc
        exe = (self.bin_dir / "XtItClient.exe").resolve()
        found = []
        for process in psutil.process_iter(["name"]):
            try:
                if (process.info.get("name") or "").lower() == "xtitclient.exe" and Path(process.exe()).resolve() == exe:
                    found.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return found

    def restart_qmt(self, *, timeout=90):
        import psutil
        processes = self._qmt_processes()
        for process in processes:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline and self._qmt_processes():
            time.sleep(0.25)
        remaining = self._qmt_processes()
        if remaining:
            raise QmtPythonRuntimeError("QMT did not stop before runtime switch")
        exe = self.bin_dir / "XtItClient.exe"
        if not exe.is_file():
            raise QmtPythonRuntimeError("QMT client executable not found")
        process = subprocess.Popen([str(exe)], cwd=str(self.bin_dir))
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            matches = self._qmt_processes()
            if matches:
                return {"pid": matches[0].pid, "started": True}
            time.sleep(0.25)
        raise QmtPythonRuntimeError("QMT did not start after runtime switch")

    def validate_selection(self, runtime, *, account_id=None,
                           allow_missing_account_config=False):
        runtime = _canonical_runtime(runtime)
        effective_account = account_id if account_id is not None else self.account_id
        binding = self.binding_status(account_id=effective_account)
        if runtime == "py312" and not binding["py312_supported"]:
            raise QmtPythonRuntimeError(
                "QMT %s only supports the default py36 runtime; py312 is unavailable"
                % (binding.get("qmt_version") or "unknown"))
        if effective_account:
            if not binding["config_exists"]:
                if allow_missing_account_config and binding["state"] == "account_config_missing":
                    return binding
                raise QmtPythonRuntimeError("QMT account Config.xml not found: %s; log in to QMT first" % effective_account)
            text = Path(binding["config"]).read_text(encoding="utf-8")
            if not re.search(r'<python\b[^>]*\blibs_path="[^"]*"', text):
                raise QmtPythonRuntimeError("QMT account Config.xml has no Python library settings")
        return binding

    def download_and_switch(self, runtime="py312", *, restart=True, account_id=None,
                            progress_callback=None, cancel_event=None,
                            restart_callback=None, reuse_installed=False,
                            allow_missing_account_config=False):
        runtime = _canonical_runtime(runtime)
        binding = self.validate_selection(
            runtime,
            account_id=account_id,
            allow_missing_account_config=allow_missing_account_config,
        )
        deferred_account_config = bool(
            allow_missing_account_config
            and (account_id or self.account_id)
            and binding.get("state") == "account_config_missing"
        )
        reuse = bool(reuse_installed and binding["runtimes"][runtime]["installed"])
        package, archive = None, None
        if reuse:
            _callback(progress_callback, QmtPythonProgress(runtime, "reusing", message="Python 库已安装，准备切换执行器"))
        else:
            package = self.fetch_package(runtime)
            archive = self.download(runtime, package=package, progress_callback=progress_callback,
                                    cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():
            raise QmtPythonRuntimeError("QMT Python runtime operation cancelled")
        _callback(progress_callback, QmtPythonProgress(
            runtime, "activating",
            message=("正在停止 QMT 并安装运行库" if deferred_account_config
                     else "正在停止 QMT 并配置执行器"),
        ))
        was_running = bool(self._qmt_processes())
        if restart and was_running:
            self._stop_for_switch()
        elif not restart and was_running:
            raise QmtPythonRuntimeError(
                "QMT is running; set restart=True before installing or activating a Python runtime")
        try:
            installed = self.inspect(runtime, refresh_remote=False) if reuse else self.install(runtime, package=package, progress_callback=progress_callback)
            switched = None if deferred_account_config else (
                self.switch_account(runtime, account_id=account_id)
                if (account_id or self.account_id) else None
            )
        finally:
            if restart and (not deferred_account_config or was_running):
                _callback(progress_callback, QmtPythonProgress(runtime, "restarting", message="正在重新启动 QMT"))
                if restart_callback:
                    restarted = restart_callback()
                elif self._qmt_processes():
                    restarted = {"started": True, "pid": self._qmt_processes()[0].pid}
                else:
                    restarted = self.restart_qmt()
            else:
                restarted = None
        return {"runtime": runtime, "package": package.as_dict() if package else None,
                "archive": str(archive) if archive else None, "reused_installed": reuse,
                "installed": installed, "switched": switched, "restarted": restarted,
                "account_config_required": deferred_account_config,
                "message": ("运行库已安装；请先在 QMT 登录此账号，再重新检测并应用执行器。"
                             if deferred_account_config else "")}

    def _stop_for_switch(self):
        for process in self._qmt_processes():
            try:
                process.terminate()
            except Exception:
                pass
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline and self._qmt_processes():
            time.sleep(0.25)
        if self._qmt_processes():
            raise QmtPythonRuntimeError("QMT did not stop before runtime activation")


__all__ = ["QmtPythonRuntime", "QmtPythonPackage", "QmtPythonProgress", "QmtPythonRuntimeError"]
