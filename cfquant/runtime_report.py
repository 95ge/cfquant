# -*- coding: utf-8 -*-
"""QMT runtime version marker helpers.

The marker file is intentionally independent from LTtx and pipe RPC so the web
process can identify the running QMT script version even while request channels
are blocked or still warming up.
"""

import glob
import json
import os
import sys
import tempfile
import time


RUNTIME_SCHEMA = "cfquant.qmt.runtime"
MARKER_FILENAME_PREFIX = "cfquant_qmt_runtime"


def _now_text(ts=None):
    ts = float(ts if ts is not None else time.time())
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _text(value):
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _path(value):
    value = _text(value)
    if not value:
        return ""
    try:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
    except Exception:
        return value


def _safe_name(value, default="runtime"):
    value = _text(value) or default
    out = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out).strip("._")
    return name or default


def _append_unique(paths, path):
    path = _path(path)
    if not path:
        return
    try:
        key = os.path.normcase(os.path.abspath(path))
    except Exception:
        key = path.lower()
    for item in paths:
        try:
            item_key = os.path.normcase(os.path.abspath(item))
        except Exception:
            item_key = item.lower()
        if item_key == key:
            return
    paths.append(path)


def configured_marker_dirs(config=None, entry_base_dir=None):
    config = config if isinstance(config, dict) else {}
    paths = []

    for key in ("qmt_runtime_marker_dir", "runtime_marker_dir"):
        _append_unique(paths, config.get(key))
    for key in ("runtime_status_dir", "web_runtime_status_dir"):
        base = _path(config.get(key))
        if base:
            _append_unique(paths, os.path.join(base, "qmt_runtime"))
    for key in ("runtime_dir", "web_runtime_dir"):
        base = _path(config.get(key))
        if base:
            _append_unique(paths, os.path.join(base, "status", "qmt_runtime"))

    for name in ("CFQUANT_QMT_RUNTIME_MARKER_DIR", "CFQUANT_RUNTIME_MARKER_DIR"):
        _append_unique(paths, os.environ.get(name))
    for name in ("CFQUANT_RUNTIME_STATUS_DIR", "CFQUANT_WEB_RUNTIME_STATUS_DIR"):
        base = _path(os.environ.get(name))
        if base:
            _append_unique(paths, os.path.join(base, "qmt_runtime"))
    for name in ("CFQUANT_RUNTIME_DIR", "CFQUANT_WEB_RUNTIME_DIR"):
        base = _path(os.environ.get(name))
        if base:
            _append_unique(paths, os.path.join(base, "status", "qmt_runtime"))

    base_dir = _path(entry_base_dir)
    if not base_dir:
        entry_file = _path(config.get("entry_file"))
        if entry_file:
            base_dir = os.path.dirname(entry_file)
    if base_dir:
        parent_dir = os.path.dirname(base_dir)
        _append_unique(paths, os.path.join(base_dir, "runtime", "status", "qmt_runtime"))
        if parent_dir and parent_dir != base_dir:
            _append_unique(paths, os.path.join(parent_dir, "runtime", "status", "qmt_runtime"))
            if os.path.basename(base_dir).lower() == "python":
                _append_unique(paths, os.path.join(parent_dir, "bin.x64", "runtime", "status", "qmt_runtime"))

    if not paths:
        _append_unique(paths, os.path.join(tempfile.gettempdir(), "cfquant", "runtime", "status", "qmt_runtime"))
    return paths


def build_qmt_runtime_report(
    reason="startup",
    version="",
    core_version="",
    entry_version="",
    entry_script="",
    entry_file="",
    bridge="",
    bridge_id="default",
    account_id="",
    account_type="",
    account_key="",
    mode="",
    transport="",
    runtime_mode="",
    channel_key="runtime",
    request_channel="",
    callback_event_channel="",
    channels=None,
    pipe_name="",
    market="",
    market_role="",
    market_route_parent_bridge_id="",
    config=None,
    globals_dict=None,
    module_file="",
    started_at=None,
    extra=None,
):
    config = config if isinstance(config, dict) else {}
    globals_dict = globals_dict if isinstance(globals_dict, dict) else {}
    channels = channels if isinstance(channels, dict) else (config.get("channels") if isinstance(config.get("channels"), dict) else {})
    channel_key = _text(channel_key) or "runtime"
    request_channel = _text(request_channel) or _text(channels.get(channel_key))
    entry_file = _path(entry_file or globals_dict.get("__file__") or config.get("entry_file"))
    entry_script = _text(entry_script or config.get("entry_script"))
    if not entry_script and entry_file:
        entry_script = os.path.basename(entry_file)
    entry_version = _text(
        entry_version
        or globals_dict.get("_ENTRY_VERSION")
        or globals_dict.get("LITE_ENTRY_VERSION")
        or globals_dict.get("ENTRY_VERSION")
        or config.get("entry_version")
        or config.get("qmt_runtime_entry_version")
    )
    core_version = _text(
        core_version
        or globals_dict.get("CORE_VERSION")
        or globals_dict.get("_CORE_VERSION")
        or version
        or config.get("core_version")
        or config.get("qmt_runtime_core_version")
    )
    version = _text(version or core_version)
    started = started_at
    if started in (None, "", 0):
        started = globals_dict.get("_runtime_started_at") or config.get("started_at") or time.time()
    try:
        started = float(started)
    except Exception:
        started = time.time()
    now = time.time()
    report = {
        "schema": RUNTIME_SCHEMA,
        "report_schema": "cfquant.qmt.runtime_marker.v1",
        "version": version,
        "core_version": core_version or version,
        "entry_version": entry_version,
        "entry_script": entry_script,
        "entry_file": entry_file,
        "bridge": _text(bridge),
        "bridge_id": _text(bridge_id or config.get("bridge_id") or globals_dict.get("BRIDGE_ID") or "default") or "default",
        "account_id": _text(account_id or config.get("account_id") or globals_dict.get("DEFAULT_ACCOUNT_ID")),
        "account_type": _text(account_type or config.get("account_type") or globals_dict.get("DEFAULT_ACCOUNT_TYPE")),
        "account_key": _text(account_key or config.get("account_key")),
        "mode": _text(mode or config.get("mode")),
        "transport": _text(transport),
        "runtime_mode": _text(runtime_mode),
        "channel_key": channel_key,
        "request_channel": request_channel,
        "callback_event_channel": _text(callback_event_channel),
        "channels": dict(channels or {}),
        "pipe_name": _text(pipe_name or config.get("pipe_name")),
        "market": _text(market or config.get("market") or globals_dict.get("QMT_MARKET")),
        "market_role": _text(market_role or config.get("market_role")),
        "market_route_parent_bridge_id": _text(market_route_parent_bridge_id or config.get("market_route_parent_bridge_id")),
        "core_dir": os.path.dirname(os.path.abspath(__file__)),
        "version_file": os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.py"),
        "module_file": _path(module_file or __file__),
        "config_path": _path(globals_dict.get("RUNTIME_CONFIG_PATH") or config.get("config_path") or config.get("path")),
        "python": sys.executable,
        "pid": os.getpid(),
        "cwd": _path(os.getcwd()),
        "started_at": started,
        "started_at_text": _now_text(started),
        "reported_at": now,
        "reported_at_text": _now_text(now),
        "reason": _text(reason or "startup"),
        "source": "qmt_startup_marker",
    }
    if isinstance(extra, dict):
        report.update(extra)
    return report


def marker_filename(report):
    report = report if isinstance(report, dict) else {}
    bridge_id = _safe_name(report.get("bridge_id") or "default", "default")
    channel_key = _safe_name(report.get("channel_key") or "runtime", "runtime")
    entry_script = _safe_name(os.path.splitext(os.path.basename(_text(report.get("entry_script"))))[0], "entry")
    pid = _safe_name(report.get("pid") or os.getpid(), "pid")
    return "%s_%s_%s_%s_%s.json" % (MARKER_FILENAME_PREFIX, bridge_id, channel_key, entry_script, pid)


def write_qmt_runtime_marker(report, marker_dirs=None, config=None, entry_base_dir=None):
    report = dict(report or {})
    dirs = []
    for path in marker_dirs or []:
        _append_unique(dirs, path)
    for path in configured_marker_dirs(config=config, entry_base_dir=entry_base_dir):
        _append_unique(dirs, path)

    files = []
    errors = []
    name = marker_filename(report)
    for directory in dirs:
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, name)
            temp_path = "%s.%s.tmp" % (path, os.getpid())
            data = dict(report)
            data["marker_file"] = path
            data["marker_dir"] = directory
            data["marker_written_at"] = time.time()
            data["marker_written_at_text"] = _now_text(data["marker_written_at"])
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temp_path, path)
            files.append(path)
        except Exception as e:
            errors.append("%s: %s" % (directory, e))
    return {
        "ok": bool(files),
        "files": files,
        "primary_file": files[0] if files else "",
        "errors": errors,
        "report": report,
    }


def publish_qmt_runtime_marker(marker_dirs=None, config=None, entry_base_dir=None, **kwargs):
    report = build_qmt_runtime_report(config=config, **kwargs)
    return write_qmt_runtime_marker(
        report,
        marker_dirs=marker_dirs,
        config=config,
        entry_base_dir=entry_base_dir,
    )


def _read_marker_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get("schema") != RUNTIME_SCHEMA and not data.get("core_version"):
            return None
        stat_result = os.stat(path)
        data.setdefault("marker_file", path)
        data.setdefault("marker_dir", os.path.dirname(path))
        data.setdefault("marker_mtime", stat_result.st_mtime)
        data.setdefault("marker_mtime_text", _now_text(stat_result.st_mtime))
        return data
    except Exception:
        return None


def read_qmt_runtime_markers(marker_dirs, max_age_seconds=None, max_files=256):
    if isinstance(marker_dirs, str):
        marker_dirs = [marker_dirs]
    paths = []
    for directory in marker_dirs or []:
        directory = _path(directory)
        if not directory or not os.path.isdir(directory):
            continue
        paths.extend(glob.glob(os.path.join(directory, "%s_*.json" % MARKER_FILENAME_PREFIX)))
    unique = []
    seen = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    unique.sort(key=lambda item: os.path.getmtime(item) if os.path.exists(item) else 0, reverse=True)
    if max_files:
        unique = unique[: int(max_files)]

    now = time.time()
    reports = []
    for path in unique:
        data = _read_marker_file(path)
        if not data or not data.get("core_version"):
            continue
        if max_age_seconds is not None:
            stamp = data.get("reported_at") or data.get("marker_written_at") or data.get("marker_mtime") or 0
            try:
                stamp = float(stamp)
            except Exception:
                stamp = 0.0
            if stamp and now - stamp > float(max_age_seconds):
                continue
        reports.append(data)
    return reports
