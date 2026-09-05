# -*- coding: utf-8 -*-
import sys
sys.dont_write_bytecode = True

import argparse
import base64
import email.parser
import email.policy
import fnmatch
import hashlib
import json
import math
import mimetypes
import os
import posixpath
import queue
import re
import secrets
import shutil
import sqlite3
import socket
import stat
import subprocess
import tempfile
import threading
import time
import tokenize
import urllib.parse
import urllib.request
import zipfile
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
try:
    import psutil
except Exception:
    psutil = None
try:
    from importlib import resources as importlib_resources
    if not hasattr(importlib_resources, "files"):
        raise ImportError
except Exception:
    try:
        import importlib_resources
    except Exception:
        importlib_resources = None

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__import__("cfquant").__file__))
_SOURCE_ROOT = os.path.abspath(os.path.join(_PACKAGE_DIR, os.pardir))
_RUNNING_FROM_SOURCE = (
    os.path.isfile(os.path.join(_SOURCE_ROOT, "pyproject.toml"))
    and os.path.isfile(os.path.join(_SOURCE_ROOT, "web_dashboard", "index.html"))
)
_LTTX_TX_DIR = os.path.join(_SOURCE_ROOT, "LTtx", "tx")


def _prepend_import_path(path):
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return
    normalized = path.lower()
    sys.path = [
        item for item in sys.path
        if os.path.abspath(item or os.curdir).lower() != normalized
    ]
    sys.path.insert(0, path)


_prepend_import_path(_PROJECT_DIR)
_prepend_import_path(_LTTX_TX_DIR)

from cfquant.client import CfquantError, CfquantTimeout, LTtxRpcClient
from cfquant import xtconstant as cf_xtconstant
from cfquant.channels import configured_bridges, normalize_bridge_id
from cfquant.config import get_config as get_cfquant_config
from cfquant.logging_i18n import normalize_log_enabled, normalize_log_language
from cfquant.pipe_transport import DEFAULT_PIPE_NAME, normalize_pipe_name
from cfquant.protocol import decode_value, loads_message, new_id, pack_event, pack_response
from cfquant.runtime_report import read_qmt_runtime_markers as read_qmt_runtime_marker_files
from cfquant.version import WEB_VERSION, __version__ as CORE_VERSION
from tx import txl


BASE_DIR = os.path.abspath(os.environ.get("CFQUANT_BASE_DIR") or _SOURCE_ROOT)
CORE_VERSION_PATH = os.path.join(BASE_DIR, "cfquant", "version.py")
STATIC_DIR = os.environ.get("CFQUANT_WEB_STATIC_DIR") or os.path.join(BASE_DIR, "web_dashboard")
PACKAGE_STATIC_NAME = "web_dashboard"


def default_state_dir():
    configured = os.environ.get("CFQUANT_HOME") or os.environ.get("CFQUANT_STATE_DIR")
    if configured:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(configured)))
    if _RUNNING_FROM_SOURCE:
        return BASE_DIR
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.abspath(os.path.join(root, "cfquant"))
    root = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.abspath(os.path.join(root, "cfquant"))


STATE_DIR = default_state_dir()
RUNTIME_DIR = os.path.abspath(os.environ.get("CFQUANT_RUNTIME_DIR") or os.path.join(STATE_DIR, "runtime"))
RUNTIME_CONFIG_DIR = os.path.join(RUNTIME_DIR, "config")
RUNTIME_DB_DIR = os.path.join(RUNTIME_DIR, "db")
RUNTIME_LTTX_DIR = os.path.join(RUNTIME_DIR, "lttx")
RUNTIME_MEDIA_DIR = os.path.join(RUNTIME_DIR, "media")
RUNTIME_REPORTS_DIR = os.path.join(RUNTIME_DIR, "reports")
RUNTIME_STATUS_DIR = os.path.join(RUNTIME_DIR, "status")
QMT_RUNTIME_MARKER_DIR = os.path.abspath(
    os.environ.get("CFQUANT_QMT_RUNTIME_MARKER_DIR") or os.path.join(RUNTIME_STATUS_DIR, "qmt_runtime")
)
RUNTIME_AVATAR_DIR = os.path.join(RUNTIME_MEDIA_DIR, "avatars")
try:
    os.makedirs(RUNTIME_CONFIG_DIR, exist_ok=True)
    os.makedirs(RUNTIME_DB_DIR, exist_ok=True)
    os.makedirs(RUNTIME_LTTX_DIR, exist_ok=True)
    os.makedirs(RUNTIME_MEDIA_DIR, exist_ok=True)
    os.makedirs(RUNTIME_REPORTS_DIR, exist_ok=True)
    os.makedirs(RUNTIME_STATUS_DIR, exist_ok=True)
    os.makedirs(QMT_RUNTIME_MARKER_DIR, exist_ok=True)
    os.makedirs(RUNTIME_AVATAR_DIR, exist_ok=True)
except Exception:
    RUNTIME_DIR = os.path.join(tempfile.gettempdir(), "cfquant", "runtime")
    RUNTIME_CONFIG_DIR = os.path.join(RUNTIME_DIR, "config")
    RUNTIME_DB_DIR = os.path.join(RUNTIME_DIR, "db")
    RUNTIME_LTTX_DIR = os.path.join(RUNTIME_DIR, "lttx")
    RUNTIME_MEDIA_DIR = os.path.join(RUNTIME_DIR, "media")
    RUNTIME_REPORTS_DIR = os.path.join(RUNTIME_DIR, "reports")
    RUNTIME_STATUS_DIR = os.path.join(RUNTIME_DIR, "status")
    QMT_RUNTIME_MARKER_DIR = os.path.abspath(
        os.environ.get("CFQUANT_QMT_RUNTIME_MARKER_DIR") or os.path.join(RUNTIME_STATUS_DIR, "qmt_runtime")
    )
    RUNTIME_AVATAR_DIR = os.path.join(RUNTIME_MEDIA_DIR, "avatars")
    for directory in (
        RUNTIME_CONFIG_DIR,
        RUNTIME_DB_DIR,
        RUNTIME_LTTX_DIR,
        RUNTIME_MEDIA_DIR,
        RUNTIME_REPORTS_DIR,
        RUNTIME_STATUS_DIR,
        QMT_RUNTIME_MARKER_DIR,
        RUNTIME_AVATAR_DIR,
    ):
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception:
            pass
LOG_DIR = os.path.abspath(os.environ.get("CFQUANT_LOG_DIR") or os.path.join(STATE_DIR, "log"))
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception:
    LOG_DIR = os.path.join(tempfile.gettempdir(), "cfquant", "log")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        LOG_DIR = tempfile.gettempdir()
LOG_FILE = os.path.join(LOG_DIR, "cfquant_web_server.runtime.log")
LOG_RETENTION_DAYS = int(os.environ.get("CFQUANT_LOG_RETENTION_DAYS", "30"))
LOG_CLEANUP_INTERVAL_SECONDS = float(os.environ.get("CFQUANT_LOG_CLEANUP_INTERVAL_SECONDS", "21600"))


def read_python_dunder_version(path):
    path = os.path.abspath(str(path or ""))
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(8192)
        match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
        return match.group(1).strip() if match else ""
    except Exception:
        return ""


def current_core_version_info():
    file_version = read_python_dunder_version(CORE_VERSION_PATH)
    version = file_version or CORE_VERSION
    source = "cfquant/version.py" if file_version else "imported cfquant.version"
    checked_at = time.time()
    return {
        "version": version,
        "source": source,
        "path": CORE_VERSION_PATH if file_version else "",
        "file_version": file_version,
        "imported_version": CORE_VERSION,
        "import_stale": bool(file_version and file_version != CORE_VERSION),
        "checked_at": checked_at,
        "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(checked_at)),
    }


def current_core_version():
    return current_core_version_info().get("version") or CORE_VERSION


def normalize_official_site_url(site_url=None):
    value = str(site_url or DEFAULT_OFFICIAL_SITE_URL or "").strip()
    return value.rstrip("/")


def official_site_api_url(path, site_url=None):
    base = normalize_official_site_url(site_url)
    if not base:
        return ""
    return urllib.parse.urljoin(base + "/", str(path or "").lstrip("/"))


def fetch_json_url(url, timeout=None):
    if timeout is None:
        timeout = UPDATE_REMOTE_TIMEOUT_SECONDS
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "cfquant-web/%s" % current_core_version()},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024)
    text = raw.decode("utf-8", errors="replace")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("invalid json response")
    if data.get("ok") is False:
        raise RuntimeError(str(data.get("error") or "official site api failed"))
    return data


def official_release_info(site_url=None):
    endpoint = official_site_api_url("/api/releases/latest", site_url)
    if not endpoint:
        raise RuntimeError("未配置 cfquant 官网地址")
    data = fetch_json_url(endpoint)
    release = data.get("release") if isinstance(data.get("release"), dict) else data
    release = dict(release)
    download_url = str(release.get("download_url") or release.get("latest_download_url") or "").strip()
    if download_url and not re.match(r"^https?://", download_url, re.I):
        download_url = urllib.parse.urljoin(endpoint, download_url)
    if not download_url:
        download_url = official_site_api_url("/api/releases/latest/download", site_url)
    release["download_url"] = download_url
    release.setdefault("source", "cfquant.org")
    release.setdefault("site_url", normalize_official_site_url(site_url))
    return release


def _safe_static_rel_path(path):
    if path in ("", "/"):
        path = "/index.html"
    rel_path = posixpath.normpath(urllib.parse.unquote(path or ""))
    rel_path = rel_path.lstrip("/")
    if rel_path in ("", "."):
        rel_path = "index.html"
    parts = [part for part in rel_path.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def _package_static_file(rel_path):
    if importlib_resources is None:
        return None
    try:
        node = importlib_resources.files(PACKAGE_STATIC_NAME)
        for part in rel_path.split("/"):
            node = node.joinpath(part)
        return node if node.is_file() else None
    except Exception:
        return None


def static_assets_available():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return True
    return _package_static_file("index.html") is not None


def read_static_asset(path):
    rel_path = _safe_static_rel_path(path)
    if not rel_path:
        raise PermissionError("forbidden static path")
    static_root = os.path.abspath(STATIC_DIR)
    full_path = os.path.abspath(os.path.join(static_root, rel_path.replace("/", os.sep)))
    try:
        if os.path.commonpath([static_root, full_path]) == static_root and os.path.isfile(full_path):
            with open(full_path, "rb") as f:
                return rel_path, f.read()
    except ValueError:
        pass
    node = _package_static_file(rel_path)
    if node is not None:
        return rel_path, node.read_bytes()
    return rel_path, None


LTTX_HOST = os.environ.get("CFQUANT_LTTX_HOST", "127.0.0.1")
LTTX_PORT = int(os.environ.get("CFQUANT_LTTX_PORT", "2049"))
LTTX_DIR = os.path.join(BASE_DIR, "LTtx", "tx")
LTTX_ENTRY = os.environ.get("CFQUANT_LTTX_ENTRY") or os.path.join(LTTX_DIR, "LTtx_server.py")
LTTX_STDOUT_LOG = os.path.join(LOG_DIR, "lttx_server.stdout.log")
LTTX_STDERR_LOG = os.path.join(LOG_DIR, "lttx_server.stderr.log")
PIPE_HUB_ENTRY = os.environ.get("CFQUANT_PIPE_HUB_ENTRY") or os.path.join(_SOURCE_ROOT, "cfquant_pipe_hub.py")
PIPE_HUB_MODULE = "cfquant_pipe_hub"
PIPE_HUB_STDOUT_LOG = os.path.join(LOG_DIR, "cfquant_pipe_hub.stdout.log")
PIPE_HUB_STDERR_LOG = os.path.join(LOG_DIR, "cfquant_pipe_hub.stderr.log")
PIPE_HUB_STATUS_FILE = os.environ.get("CFQUANT_PIPE_HUB_STATUS_FILE") or os.path.join(
    RUNTIME_STATUS_DIR,
    "cfquant_pipe_hub_status.json",
)
QMT_BRIDGE_CONFIG_FILENAME = os.environ.get("CFQUANT_QMT_BRIDGE_CONFIG_FILENAME", "cfquant_bridge_config.json")
LTTX_DISCOVERY_KEY = os.environ.get("CFQUANT_DISCOVERY_KEY", "cfquant.runtime")
LTTX_WEB_REQUEST_CHANNEL = os.environ.get("CFQUANT_WEB_REQUEST_CHANNEL", "cfquant.web.request")
LTTX_REGISTRY_INTERVAL_SECONDS = float(os.environ.get("CFQUANT_LTTX_REGISTRY_INTERVAL_SECONDS", "5"))
try:
    _LOG_FP = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    _WINDOWLESS = os.path.basename(sys.executable).lower() == "pythonw.exe"
    if _WINDOWLESS or sys.stdout is None:
        sys.stdout = _LOG_FP
    if _WINDOWLESS or sys.stderr is None:
        sys.stderr = _LOG_FP
except Exception:
    _LOG_FP = None
DEFAULT_ACCOUNT_ID = os.environ.get("CFQUANT_ACCOUNT_ID", "").strip()
WEB_CONFIG_FILE = os.environ.get("CFQUANT_WEB_CONFIG_FILE") or os.path.join(
    RUNTIME_CONFIG_DIR,
    "cfquant_web_config.json",
)
WEB_SETTINGS_DB_FILE = os.environ.get("CFQUANT_WEB_SETTINGS_DB_FILE") or os.path.join(
    RUNTIME_DB_DIR,
    "cfquant_web_config.db",
)
RECONNECT_COOLDOWN_SECONDS = float(os.environ.get("CFQUANT_WEB_RECONNECT_COOLDOWN", "30"))
ENV_BRIDGES = configured_bridges()
BRIDGES = dict(ENV_BRIDGES)
DEFAULT_BRIDGE_ID = normalize_bridge_id(
    os.environ.get("CFQUANT_WEB_DEFAULT_BRIDGE_ID") or next(iter(ENV_BRIDGES.keys()))
)
if DEFAULT_BRIDGE_ID not in ENV_BRIDGES:
    DEFAULT_BRIDGE_ID = next(iter(ENV_BRIDGES.keys()))
CHANNELS = ENV_BRIDGES[DEFAULT_BRIDGE_ID]["channels"]
CALLBACK_EVENT_CHANNEL = CHANNELS["callback"]
STATUS_CHECK_INTERVAL_SECONDS = float(os.environ.get("CFQUANT_WEB_STATUS_INTERVAL", "15"))
STATUS_PROBE_TIMEOUT_SECONDS = float(os.environ.get("CFQUANT_WEB_STATUS_PROBE_TIMEOUT", "8"))
PIPE_HUB_STATUS_CACHE_SECONDS = float(os.environ.get("CFQUANT_WEB_PIPE_HUB_STATUS_CACHE_SECONDS", "2"))
RUNTIME_REPORT_TTL_SECONDS = float(os.environ.get("CFQUANT_QMT_RUNTIME_REPORT_TTL", "75"))
QMT_RUNTIME_VERSION_FILE = os.environ.get("CFQUANT_QMT_RUNTIME_VERSION_FILE") or os.path.join(
    RUNTIME_STATUS_DIR,
    "cfquant_qmt_runtime_versions.json",
)
ACCOUNT_CACHE_REFRESH_SECONDS = float(os.environ.get("CFQUANT_WEB_ACCOUNT_CACHE_INTERVAL", "5"))
ACCOUNT_QUERY_TIMEOUT_SECONDS = float(os.environ.get("CFQUANT_WEB_ACCOUNT_QUERY_TIMEOUT", "30"))
ACCOUNT_CACHE_BACKGROUND_TIMEOUT_SECONDS = max(
    0.5,
    min(
        ACCOUNT_QUERY_TIMEOUT_SECONDS,
        float(os.environ.get("CFQUANT_WEB_ACCOUNT_CACHE_BACKGROUND_TIMEOUT", "5")),
    ),
)
ACCOUNT_CACHE_PREWARM_SECTIONS = tuple(
    section.strip().lower()
    for section in os.environ.get("CFQUANT_WEB_ACCOUNT_CACHE_PREWARM_SECTIONS", "asset,positions").split(",")
    if section.strip()
)
UPDATE_UPLOAD_MAX_BYTES = int(os.environ.get("CFQUANT_UPDATE_UPLOAD_MAX_BYTES", str(80 * 1024 * 1024)))
AVATAR_UPLOAD_MAX_BYTES = int(os.environ.get("CFQUANT_AVATAR_UPLOAD_MAX_BYTES", str(2 * 1024 * 1024)))
DEFAULT_UPDATE_REPO_URL = os.environ.get("CFQUANT_UPDATE_REPO_URL", "https://github.com/95ge/cfquant.git").strip()
DEFAULT_OFFICIAL_SITE_URL = os.environ.get("CFQUANT_OFFICIAL_SITE_URL", "https://cfquant.org").strip().rstrip("/")
DEFAULT_UPDATE_REF = os.environ.get("CFQUANT_UPDATE_REF", "main").strip()
UPDATE_REMOTE_CACHE_SECONDS = float(os.environ.get("CFQUANT_UPDATE_REMOTE_CACHE_SECONDS", "300"))
UPDATE_REMOTE_TIMEOUT_SECONDS = float(os.environ.get("CFQUANT_UPDATE_REMOTE_TIMEOUT_SECONDS", "12"))
PROJECT_UPDATE_DIR = os.path.join(
    BASE_DIR if _RUNNING_FROM_SOURCE else STATE_DIR,
    ".cfquant_project_updates",
)
PROJECT_UPDATE_BACKUP_KEEP = int(os.environ.get("CFQUANT_PROJECT_UPDATE_BACKUP_KEEP", "2"))
QMT_ENTRY_SCRIPT_NAMES = (
    "CFQUANT_CTYPE_ALL_LOWLAT.py",
    "CFQUANT_LITE.py",
    "CFQUANT.py",
    "CFQUANT_TRADE_LOWLAT.py",
    os.path.join("同账号独立市场", "CFQUANT_CTYPE_ALL_LOWLAT_SH.py"),
    os.path.join("同账号独立市场", "CFQUANT_CTYPE_ALL_LOWLAT_SZ.py"),
    os.path.join("同账号独立市场", "CFQUANT_TRADE_LOWLAT_SH.py"),
    os.path.join("同账号独立市场", "CFQUANT_TRADE_LOWLAT_SZ.py"),
    os.path.join("同账号独立市场", "CFQUANT_LITE_SH.py"),
    os.path.join("同账号独立市场", "CFQUANT_LITE_SZ.py"),
)
WEB_BOUND_HOST = None
WEB_BOUND_PORT = None
WEB_RESTART_REQUEST = None
WEB_RESTART_LOCK = threading.RLock()
WEB_AUTH_TOKENS = {}
WEB_AUTH_LOCK = threading.RLock()
WEB_AUTH_COOKIE_NAME = "cfquant_web_token"
WEB_AUTH_SESSION_TTL_SECONDS = float(os.environ.get("CFQUANT_WEB_AUTH_SESSION_TTL_SECONDS", str(30 * 24 * 3600)))
BUILTIN_AVATARS = (
    {"id": "market-blue", "name": "Market Blue", "url": "/avatars/market-blue.svg"},
    {"id": "signal-green", "name": "Signal Green", "url": "/avatars/signal-green.svg"},
    {"id": "copper-grid", "name": "Copper Grid", "url": "/avatars/copper-grid.svg"},
    {"id": "violet-node", "name": "Violet Node", "url": "/avatars/violet-node.svg"},
    {"id": "slate-wave", "name": "Slate Wave", "url": "/avatars/slate-wave.svg"},
    {"id": "amber-pulse", "name": "Amber Pulse", "url": "/avatars/amber-pulse.svg"},
    {"id": "teal-orbit", "name": "Teal Orbit", "url": "/avatars/teal-orbit.svg"},
    {"id": "rose-circuit", "name": "Rose Circuit", "url": "/avatars/rose-circuit.svg"},
)
DEFAULT_AVATAR_URL = BUILTIN_AVATARS[0]["url"]
BUILTIN_AVATAR_URLS = set(item["url"] for item in BUILTIN_AVATARS)
AVATAR_UPLOAD_URL_PREFIX = "/media/avatars/"
AVATAR_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
STOCK_BUY = 23
STOCK_SELL = 24
FIX_PRICE = 11
CREDIT_BUY = 33
CREDIT_SELL = 34
CREDIT_FIN_BUY = 27
CREDIT_SLO_SELL = 28
CREDIT_BUY_SECU_REPAY = 29
CREDIT_DIRECT_SECU_REPAY = 30
CREDIT_SELL_SECU_REPAY = 31
CREDIT_DIRECT_CASH_REPAY = 32
CREDIT_FIN_BUY_SPECIAL = 70
CREDIT_SLO_SELL_SPECIAL = 71
CREDIT_BUY_SECU_REPAY_SPECIAL = 72
CREDIT_DIRECT_SECU_REPAY_SPECIAL = 73
CREDIT_SELL_SECU_REPAY_SPECIAL = 74
CREDIT_DIRECT_CASH_REPAY_SPECIAL = 75
FUTURE_OPEN_LONG = cf_xtconstant.FUTURE_OPEN_LONG
FUTURE_CLOSE_LONG_HISTORY = cf_xtconstant.FUTURE_CLOSE_LONG_HISTORY
FUTURE_CLOSE_LONG_TODAY = cf_xtconstant.FUTURE_CLOSE_LONG_TODAY
FUTURE_OPEN_SHORT = cf_xtconstant.FUTURE_OPEN_SHORT
FUTURE_CLOSE_SHORT_HISTORY = cf_xtconstant.FUTURE_CLOSE_SHORT_HISTORY
FUTURE_CLOSE_SHORT_TODAY = cf_xtconstant.FUTURE_CLOSE_SHORT_TODAY
FUTURE_CLOSE_LONG_TODAY_FIRST = cf_xtconstant.FUTURE_CLOSE_LONG_TODAY_FIRST
FUTURE_CLOSE_LONG_HISTORY_FIRST = cf_xtconstant.FUTURE_CLOSE_LONG_HISTORY_FIRST
FUTURE_CLOSE_SHORT_TODAY_FIRST = cf_xtconstant.FUTURE_CLOSE_SHORT_TODAY_FIRST
FUTURE_CLOSE_SHORT_HISTORY_FIRST = cf_xtconstant.FUTURE_CLOSE_SHORT_HISTORY_FIRST
FUTURE_CLOSE_LONG_TODAY_HISTORY_THEN_OPEN_SHORT = cf_xtconstant.FUTURE_CLOSE_LONG_TODAY_HISTORY_THEN_OPEN_SHORT
FUTURE_CLOSE_LONG_HISTORY_TODAY_THEN_OPEN_SHORT = cf_xtconstant.FUTURE_CLOSE_LONG_HISTORY_TODAY_THEN_OPEN_SHORT
FUTURE_CLOSE_SHORT_TODAY_HISTORY_THEN_OPEN_LONG = cf_xtconstant.FUTURE_CLOSE_SHORT_TODAY_HISTORY_THEN_OPEN_LONG
FUTURE_CLOSE_SHORT_HISTORY_TODAY_THEN_OPEN_LONG = cf_xtconstant.FUTURE_CLOSE_SHORT_HISTORY_TODAY_THEN_OPEN_LONG
FUTURE_OPEN = cf_xtconstant.FUTURE_OPEN
FUTURE_CLOSE = cf_xtconstant.FUTURE_CLOSE
FUTURE_ARBITRAGE_OPEN = cf_xtconstant.FUTURE_ARBITRAGE_OPEN
FUTURE_ARBITRAGE_CLOSE_HISTORY_FIRST = cf_xtconstant.FUTURE_ARBITRAGE_CLOSE_HISTORY_FIRST
FUTURE_ARBITRAGE_CLOSE_TODAY_FIRST = cf_xtconstant.FUTURE_ARBITRAGE_CLOSE_TODAY_FIRST
FUTURE_RENEW_LONG_CLOSE_HISTORY_FIRST = cf_xtconstant.FUTURE_RENEW_LONG_CLOSE_HISTORY_FIRST
FUTURE_RENEW_LONG_CLOSE_TODAY_FIRST = cf_xtconstant.FUTURE_RENEW_LONG_CLOSE_TODAY_FIRST
FUTURE_RENEW_SHORT_CLOSE_HISTORY_FIRST = cf_xtconstant.FUTURE_RENEW_SHORT_CLOSE_HISTORY_FIRST
FUTURE_RENEW_SHORT_CLOSE_TODAY_FIRST = cf_xtconstant.FUTURE_RENEW_SHORT_CLOSE_TODAY_FIRST
STOCK_OPTION_BUY_OPEN = cf_xtconstant.STOCK_OPTION_BUY_OPEN
STOCK_OPTION_SELL_CLOSE = cf_xtconstant.STOCK_OPTION_SELL_CLOSE
STOCK_OPTION_SELL_OPEN = cf_xtconstant.STOCK_OPTION_SELL_OPEN
STOCK_OPTION_BUY_CLOSE = cf_xtconstant.STOCK_OPTION_BUY_CLOSE
STOCK_OPTION_COVERED_OPEN = cf_xtconstant.STOCK_OPTION_COVERED_OPEN
STOCK_OPTION_COVERED_CLOSE = cf_xtconstant.STOCK_OPTION_COVERED_CLOSE
STOCK_OPTION_CALL_EXERCISE = cf_xtconstant.STOCK_OPTION_CALL_EXERCISE
STOCK_OPTION_PUT_EXERCISE = cf_xtconstant.STOCK_OPTION_PUT_EXERCISE
STOCK_OPTION_SECU_LOCK = cf_xtconstant.STOCK_OPTION_SECU_LOCK
STOCK_OPTION_SECU_UNLOCK = cf_xtconstant.STOCK_OPTION_SECU_UNLOCK
OPTION_FUTURE_OPTION_EXERCISE = cf_xtconstant.OPTION_FUTURE_OPTION_EXERCISE
ACCOUNT_ACTIONS = {
    "asset": "xttrader.query_stock_asset",
    "positions": "xttrader.query_stock_positions",
    "orders": "xttrader.query_stock_orders",
    "trades": "xttrader.query_stock_trades",
}
NORMAL_QMT_ACTIONS = {
    "xtdata.subscribe_quote",
    "xtdata.subscribe_whole_quote",
    "xtdata.unsubscribe_quote",
    "xtdata.download_history_data",
    "xtdata.download_history_data2",
    "xtdata.download_financial_data",
    "xtdata.download_financial_data2",
}
MARKET_ACCOUNT_ROW_SECTIONS = {"positions", "orders", "trades"}
CREDIT_ACTIONS = {
    "detail": "xttrader.query_credit_detail",
    "credit_detail": "xttrader.query_credit_detail",
    "subjects": "xttrader.query_credit_subjects",
    "credit_subjects": "xttrader.query_credit_subjects",
    "slo_code": "xttrader.query_credit_slo_code",
    "credit_slo_code": "xttrader.query_credit_slo_code",
    "assure": "xttrader.query_credit_assure",
    "credit_assure": "xttrader.query_credit_assure",
    "compacts": "xttrader.query_stk_compacts",
    "stk_compacts": "xttrader.query_stk_compacts",
}
CREDIT_ORDER_ACTIONS = {
    "credit_buy": {
        "order_type": CREDIT_BUY,
        "side": "buy",
        "label": "担保品买入",
        "description": "信用账户担保品买入，对应大 QMT passorder opType=33。",
    },
    "credit_sell": {
        "order_type": CREDIT_SELL,
        "side": "sell",
        "label": "担保品卖出",
        "description": "信用账户担保品卖出，对应大 QMT passorder opType=34。",
    },
    "credit_fin_buy": {
        "order_type": CREDIT_FIN_BUY,
        "side": "buy",
        "label": "融资买入",
        "description": "信用账户融资买入，对应大 QMT passorder opType=27。",
    },
    "credit_slo_sell": {
        "order_type": CREDIT_SLO_SELL,
        "side": "sell",
        "label": "融券卖出",
        "description": "信用账户融券卖出，对应大 QMT passorder opType=28。",
    },
    "credit_buy_secu_repay": {
        "order_type": CREDIT_BUY_SECU_REPAY,
        "side": "buy",
        "label": "买券还券",
        "description": "信用账户买券还券，对应大 QMT passorder opType=29。",
    },
    "credit_direct_secu_repay": {
        "order_type": CREDIT_DIRECT_SECU_REPAY,
        "side": "buy",
        "label": "直接还券",
        "description": "信用账户直接还券，对应大 QMT passorder opType=30。",
    },
    "credit_sell_secu_repay": {
        "order_type": CREDIT_SELL_SECU_REPAY,
        "side": "sell",
        "label": "卖券还款",
        "description": "信用账户卖券还款，对应大 QMT passorder opType=31。",
    },
    "credit_direct_cash_repay": {
        "order_type": CREDIT_DIRECT_CASH_REPAY,
        "side": "sell",
        "label": "直接还款",
        "description": "信用账户直接还款，对应大 QMT passorder opType=32。",
    },
    "credit_fin_buy_special": {
        "order_type": CREDIT_FIN_BUY_SPECIAL,
        "side": "buy",
        "label": "专项融资买入",
        "description": "信用账户专项融资买入，对应大 QMT passorder opType=70。",
    },
    "credit_slo_sell_special": {
        "order_type": CREDIT_SLO_SELL_SPECIAL,
        "side": "sell",
        "label": "专项融券卖出",
        "description": "信用账户专项融券卖出，对应大 QMT passorder opType=71。",
    },
    "credit_buy_secu_repay_special": {
        "order_type": CREDIT_BUY_SECU_REPAY_SPECIAL,
        "side": "buy",
        "label": "专项买券还券",
        "description": "信用账户专项买券还券，对应大 QMT passorder opType=72。",
    },
    "credit_direct_secu_repay_special": {
        "order_type": CREDIT_DIRECT_SECU_REPAY_SPECIAL,
        "side": "buy",
        "label": "专项直接还券",
        "description": "信用账户专项直接还券，对应大 QMT passorder opType=73。",
    },
    "credit_sell_secu_repay_special": {
        "order_type": CREDIT_SELL_SECU_REPAY_SPECIAL,
        "side": "sell",
        "label": "专项卖券还款",
        "description": "信用账户专项卖券还款，对应大 QMT passorder opType=74。",
    },
    "credit_direct_cash_repay_special": {
        "order_type": CREDIT_DIRECT_CASH_REPAY_SPECIAL,
        "side": "sell",
        "label": "专项直接还款",
        "description": "信用账户专项直接还款，对应大 QMT passorder opType=75。",
    },
}
CREDIT_ORDER_ACTION_ALIASES = {
    "buy": "credit_buy",
    "collateral_buy": "credit_buy",
    "assure_buy": "credit_buy",
    "担保品买入": "credit_buy",
    "sell": "credit_sell",
    "collateral_sell": "credit_sell",
    "assure_sell": "credit_sell",
    "担保品卖出": "credit_sell",
    "fin_buy": "credit_fin_buy",
    "finance_buy": "credit_fin_buy",
    "margin_buy": "credit_fin_buy",
    "融资买入": "credit_fin_buy",
    "slo_sell": "credit_slo_sell",
    "short_sell": "credit_slo_sell",
    "融券卖出": "credit_slo_sell",
    "buy_secu_repay": "credit_buy_secu_repay",
    "buy_security_repay": "credit_buy_secu_repay",
    "买券还券": "credit_buy_secu_repay",
    "direct_secu_repay": "credit_direct_secu_repay",
    "direct_security_repay": "credit_direct_secu_repay",
    "直接还券": "credit_direct_secu_repay",
    "sell_secu_repay": "credit_sell_secu_repay",
    "sell_security_repay": "credit_sell_secu_repay",
    "卖券还款": "credit_sell_secu_repay",
    "direct_cash_repay": "credit_direct_cash_repay",
    "cash_repay": "credit_direct_cash_repay",
    "直接还款": "credit_direct_cash_repay",
    "fin_buy_special": "credit_fin_buy_special",
    "finance_buy_special": "credit_fin_buy_special",
    "margin_buy_special": "credit_fin_buy_special",
    "专项融资买入": "credit_fin_buy_special",
    "slo_sell_special": "credit_slo_sell_special",
    "short_sell_special": "credit_slo_sell_special",
    "专项融券卖出": "credit_slo_sell_special",
    "buy_secu_repay_special": "credit_buy_secu_repay_special",
    "专项买券还券": "credit_buy_secu_repay_special",
    "direct_secu_repay_special": "credit_direct_secu_repay_special",
    "专项直接还券": "credit_direct_secu_repay_special",
    "sell_secu_repay_special": "credit_sell_secu_repay_special",
    "专项卖券还款": "credit_sell_secu_repay_special",
    "direct_cash_repay_special": "credit_direct_cash_repay_special",
    "专项直接还款": "credit_direct_cash_repay_special",
}
CREDIT_ORDER_TYPE_ACTIONS = dict(
    (int(info["order_type"]), action)
    for action, info in CREDIT_ORDER_ACTIONS.items()
)
QMT_ENTRY_SCRIPT_NAME_SET = {
    name.replace("\\", "/")
    for name in QMT_ENTRY_SCRIPT_NAMES
}


def _qmt_entry_script_roots():
    roots = []
    for base in (BASE_DIR, _SOURCE_ROOT):
        root = os.path.abspath(os.path.join(base, "qmt_scripts"))
        if root not in roots and os.path.isdir(root):
            roots.append(root)
    return roots


def _normalize_qmt_entry_script_name(value):
    name = str(value or "").strip().replace("\\", "/")
    name = posixpath.normpath(name).lstrip("/")
    if not name or name == "." or ".." in name.split("/"):
        raise ValueError("invalid QMT script name")
    if name not in QMT_ENTRY_SCRIPT_NAME_SET:
        raise ValueError("unsupported QMT script: %s" % name)
    return name


def qmt_entry_script_sources(names):
    result = []
    seen = set()
    for raw_name in names or []:
        name = _normalize_qmt_entry_script_name(raw_name)
        if name in seen:
            continue
        seen.add(name)
        source_path = None
        for root in _qmt_entry_script_roots():
            candidate = os.path.abspath(os.path.join(root, *name.split("/")))
            try:
                inside_root = os.path.commonpath([root, candidate]) == root
            except ValueError:
                inside_root = False
            if inside_root and os.path.isfile(candidate):
                source_path = candidate
                break
        if not source_path:
            raise FileNotFoundError("QMT script not found: %s" % name)
        try:
            with tokenize.open(source_path) as source_file:
                source = source_file.read()
        except Exception:
            with open(source_path, "r", encoding="utf-8", errors="replace") as source_file:
                source = source_file.read()
        result.append({
            "name": os.path.basename(name),
            "path": name,
            "source": source,
            "line_count": len(source.splitlines()),
        })
    return result
CREDIT_LEGACY_ORDER_TYPE_MAP = {
    STOCK_BUY: CREDIT_BUY,
    STOCK_SELL: CREDIT_SELL,
    40: CREDIT_FIN_BUY_SPECIAL,
    41: CREDIT_SLO_SELL_SPECIAL,
    42: CREDIT_BUY_SECU_REPAY_SPECIAL,
    43: CREDIT_DIRECT_SECU_REPAY_SPECIAL,
    44: CREDIT_SELL_SECU_REPAY_SPECIAL,
    45: CREDIT_DIRECT_CASH_REPAY_SPECIAL,
}
FUTURE_ORDER_ACTIONS = {
    "future_open_long": {"order_type": FUTURE_OPEN_LONG, "side": "buy", "label": "期货开多", "description": "MiniQMT FUTURE_OPEN_LONG，大 QMT passorder opType=0。"},
    "future_close_long_history": {"order_type": FUTURE_CLOSE_LONG_HISTORY, "side": "sell", "label": "期货平昨多", "description": "MiniQMT FUTURE_CLOSE_LONG_HISTORY，大 QMT passorder opType=1。"},
    "future_close_long_today": {"order_type": FUTURE_CLOSE_LONG_TODAY, "side": "sell", "label": "期货平今多", "description": "MiniQMT FUTURE_CLOSE_LONG_TODAY，大 QMT passorder opType=2。"},
    "future_open_short": {"order_type": FUTURE_OPEN_SHORT, "side": "sell", "label": "期货开空", "description": "MiniQMT FUTURE_OPEN_SHORT，大 QMT passorder opType=3。"},
    "future_close_short_history": {"order_type": FUTURE_CLOSE_SHORT_HISTORY, "side": "buy", "label": "期货平昨空", "description": "MiniQMT FUTURE_CLOSE_SHORT_HISTORY，大 QMT passorder opType=4。"},
    "future_close_short_today": {"order_type": FUTURE_CLOSE_SHORT_TODAY, "side": "buy", "label": "期货平今空", "description": "MiniQMT FUTURE_CLOSE_SHORT_TODAY，大 QMT passorder opType=5。"},
    "future_close_long_today_first": {"order_type": FUTURE_CLOSE_LONG_TODAY_FIRST, "side": "sell", "label": "期货平多今优先", "description": "MiniQMT FUTURE_CLOSE_LONG_TODAY_FIRST，大 QMT passorder opType=6。"},
    "future_close_long_history_first": {"order_type": FUTURE_CLOSE_LONG_HISTORY_FIRST, "side": "sell", "label": "期货平多昨优先", "description": "MiniQMT FUTURE_CLOSE_LONG_HISTORY_FIRST，大 QMT passorder opType=7。"},
    "future_close_short_today_first": {"order_type": FUTURE_CLOSE_SHORT_TODAY_FIRST, "side": "buy", "label": "期货平空今优先", "description": "MiniQMT FUTURE_CLOSE_SHORT_TODAY_FIRST，大 QMT passorder opType=8。"},
    "future_close_short_history_first": {"order_type": FUTURE_CLOSE_SHORT_HISTORY_FIRST, "side": "buy", "label": "期货平空昨优先", "description": "MiniQMT FUTURE_CLOSE_SHORT_HISTORY_FIRST，大 QMT passorder opType=9。"},
    "future_close_long_today_history_then_open_short": {"order_type": FUTURE_CLOSE_LONG_TODAY_HISTORY_THEN_OPEN_SHORT, "side": "sell", "label": "平多今昨后开空", "description": "MiniQMT FUTURE_CLOSE_LONG_TODAY_HISTORY_THEN_OPEN_SHORT，大 QMT passorder opType=10。"},
    "future_close_long_history_today_then_open_short": {"order_type": FUTURE_CLOSE_LONG_HISTORY_TODAY_THEN_OPEN_SHORT, "side": "sell", "label": "平多昨今后开空", "description": "MiniQMT FUTURE_CLOSE_LONG_HISTORY_TODAY_THEN_OPEN_SHORT，大 QMT passorder opType=11。"},
    "future_close_short_today_history_then_open_long": {"order_type": FUTURE_CLOSE_SHORT_TODAY_HISTORY_THEN_OPEN_LONG, "side": "buy", "label": "平空今昨后开多", "description": "MiniQMT FUTURE_CLOSE_SHORT_TODAY_HISTORY_THEN_OPEN_LONG，大 QMT passorder opType=12。"},
    "future_close_short_history_today_then_open_long": {"order_type": FUTURE_CLOSE_SHORT_HISTORY_TODAY_THEN_OPEN_LONG, "side": "buy", "label": "平空昨今后开多", "description": "MiniQMT FUTURE_CLOSE_SHORT_HISTORY_TODAY_THEN_OPEN_LONG，大 QMT passorder opType=13。"},
    "future_open": {"order_type": FUTURE_OPEN, "side": "", "label": "期货开仓", "description": "MiniQMT FUTURE_OPEN，大 QMT passorder opType=14。"},
    "future_close": {"order_type": FUTURE_CLOSE, "side": "", "label": "期货平仓", "description": "MiniQMT FUTURE_CLOSE，大 QMT passorder opType=15。"},
    "future_arbitrage_open": {"order_type": FUTURE_ARBITRAGE_OPEN, "side": "", "label": "期货套利开仓", "description": "MiniQMT FUTURE_ARBITRAGE_OPEN，大 QMT passorder opType=16。"},
    "future_arbitrage_close_history_first": {"order_type": FUTURE_ARBITRAGE_CLOSE_HISTORY_FIRST, "side": "", "label": "套利平仓昨优先", "description": "MiniQMT FUTURE_ARBITRAGE_CLOSE_HISTORY_FIRST，大 QMT passorder opType=17。"},
    "future_arbitrage_close_today_first": {"order_type": FUTURE_ARBITRAGE_CLOSE_TODAY_FIRST, "side": "", "label": "套利平仓今优先", "description": "MiniQMT FUTURE_ARBITRAGE_CLOSE_TODAY_FIRST，大 QMT passorder opType=18。"},
    "future_renew_long_close_history_first": {"order_type": FUTURE_RENEW_LONG_CLOSE_HISTORY_FIRST, "side": "sell", "label": "多头换月平昨优先", "description": "MiniQMT FUTURE_RENEW_LONG_CLOSE_HISTORY_FIRST，大 QMT passorder opType=19。"},
    "future_renew_long_close_today_first": {"order_type": FUTURE_RENEW_LONG_CLOSE_TODAY_FIRST, "side": "sell", "label": "多头换月平今优先", "description": "MiniQMT FUTURE_RENEW_LONG_CLOSE_TODAY_FIRST，大 QMT passorder opType=20。"},
    "future_renew_short_close_history_first": {"order_type": FUTURE_RENEW_SHORT_CLOSE_HISTORY_FIRST, "side": "buy", "label": "空头换月平昨优先", "description": "MiniQMT FUTURE_RENEW_SHORT_CLOSE_HISTORY_FIRST，大 QMT passorder opType=21。"},
    "future_renew_short_close_today_first": {"order_type": FUTURE_RENEW_SHORT_CLOSE_TODAY_FIRST, "side": "buy", "label": "空头换月平今优先", "description": "MiniQMT FUTURE_RENEW_SHORT_CLOSE_TODAY_FIRST，大 QMT passorder opType=22。"},
}
FUTURE_OPTION_ORDER_ACTIONS = dict(FUTURE_ORDER_ACTIONS)
FUTURE_OPTION_ORDER_ACTIONS["future_option_exercise"] = {
    "order_type": OPTION_FUTURE_OPTION_EXERCISE,
    "side": "",
    "label": "期货期权行权",
    "description": "MiniQMT OPTION_FUTURE_OPTION_EXERCISE，按大 QMT passorder opType=100 透传。",
}
STOCK_OPTION_ORDER_ACTIONS = {
    "stock_option_buy_open": {"order_type": STOCK_OPTION_BUY_OPEN, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_BUY_OPEN, "side": "buy", "label": "股票期权买入开仓", "description": "MiniQMT STOCK_OPTION_BUY_OPEN=48，桥接到大 QMT opType=50。"},
    "stock_option_sell_close": {"order_type": STOCK_OPTION_SELL_CLOSE, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_SELL_CLOSE, "side": "sell", "label": "股票期权卖出平仓", "description": "MiniQMT STOCK_OPTION_SELL_CLOSE=49，桥接到大 QMT opType=51。"},
    "stock_option_sell_open": {"order_type": STOCK_OPTION_SELL_OPEN, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_SELL_OPEN, "side": "sell", "label": "股票期权卖出开仓", "description": "MiniQMT STOCK_OPTION_SELL_OPEN=50，桥接到大 QMT opType=52。"},
    "stock_option_buy_close": {"order_type": STOCK_OPTION_BUY_CLOSE, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_BUY_CLOSE, "side": "buy", "label": "股票期权买入平仓", "description": "MiniQMT STOCK_OPTION_BUY_CLOSE=51，桥接到大 QMT opType=53。"},
    "stock_option_covered_open": {"order_type": STOCK_OPTION_COVERED_OPEN, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_COVERED_OPEN, "side": "sell", "label": "股票期权备兑开仓", "description": "MiniQMT STOCK_OPTION_COVERED_OPEN=52，桥接到大 QMT opType=54。"},
    "stock_option_covered_close": {"order_type": STOCK_OPTION_COVERED_CLOSE, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_COVERED_CLOSE, "side": "buy", "label": "股票期权备兑平仓", "description": "MiniQMT STOCK_OPTION_COVERED_CLOSE=53，桥接到大 QMT opType=55。"},
    "stock_option_call_exercise": {"order_type": STOCK_OPTION_CALL_EXERCISE, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_CALL_EXERCISE, "side": "", "label": "股票期权认购行权", "description": "MiniQMT STOCK_OPTION_CALL_EXERCISE=54，桥接到大 QMT opType=56。"},
    "stock_option_put_exercise": {"order_type": STOCK_OPTION_PUT_EXERCISE, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_PUT_EXERCISE, "side": "", "label": "股票期权认沽行权", "description": "MiniQMT STOCK_OPTION_PUT_EXERCISE=55，桥接到大 QMT opType=57。"},
    "stock_option_secu_lock": {"order_type": STOCK_OPTION_SECU_LOCK, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_SECU_LOCK, "side": "", "label": "股票期权证券锁定", "description": "MiniQMT STOCK_OPTION_SECU_LOCK=56，桥接到大 QMT opType=58。"},
    "stock_option_secu_unlock": {"order_type": STOCK_OPTION_SECU_UNLOCK, "qmt_order_type": cf_xtconstant.QMT_STOCK_OPTION_SECU_UNLOCK, "side": "", "label": "股票期权证券解锁", "description": "MiniQMT STOCK_OPTION_SECU_UNLOCK=57，桥接到大 QMT opType=59。"},
}
ORDER_ACTIONS_BY_ACCOUNT_TYPE = {
    "FUTURE": FUTURE_ORDER_ACTIONS,
    "FUTURE_OPTION": FUTURE_OPTION_ORDER_ACTIONS,
    "STOCK_OPTION": STOCK_OPTION_ORDER_ACTIONS,
}
DERIVATIVE_ACCOUNT_TYPES = set(ORDER_ACTIONS_BY_ACCOUNT_TYPE)
ORDER_ACTION_ALIASES = {
    "open_long": "future_open_long",
    "buy_open": "future_open_long",
    "close_long": "future_close_long_history_first",
    "sell_close": "future_close_long_history_first",
    "close_long_history": "future_close_long_history",
    "close_long_today": "future_close_long_today",
    "open_short": "future_open_short",
    "sell_open": "future_open_short",
    "close_short": "future_close_short_history_first",
    "buy_close": "future_close_short_history_first",
    "close_short_history": "future_close_short_history",
    "close_short_today": "future_close_short_today",
    "open": "future_open",
    "close": "future_close",
    "exercise": "future_option_exercise",
    "option_future_option_exercise": "future_option_exercise",
    "stock_option_buy_open": "stock_option_buy_open",
    "stock_option_sell_close": "stock_option_sell_close",
    "stock_option_sell_open": "stock_option_sell_open",
    "stock_option_buy_close": "stock_option_buy_close",
    "covered_open": "stock_option_covered_open",
    "covered_close": "stock_option_covered_close",
    "call_exercise": "stock_option_call_exercise",
    "put_exercise": "stock_option_put_exercise",
    "secu_lock": "stock_option_secu_lock",
    "secu_unlock": "stock_option_secu_unlock",
    "lock": "stock_option_secu_lock",
    "unlock": "stock_option_secu_unlock",
}
ORDER_TYPE_ACTIONS_BY_ACCOUNT_TYPE = {
    account_type: dict((int(info["order_type"]), action) for action, info in actions.items())
    for account_type, actions in ORDER_ACTIONS_BY_ACCOUNT_TYPE.items()
}
CREDIT_PROBE_ACTIONS = [
    ("asset", "xttrader.query_stock_asset"),
    ("positions", "xttrader.query_stock_positions"),
    ("orders", "xttrader.query_stock_orders"),
    ("trades", "xttrader.query_stock_trades"),
    ("credit_detail", "xttrader.query_credit_detail"),
    ("credit_subjects", "xttrader.query_credit_subjects"),
    ("credit_slo_code", "xttrader.query_credit_slo_code"),
    ("credit_assure", "xttrader.query_credit_assure"),
    ("stk_compacts", "xttrader.query_stk_compacts"),
]
ACCOUNT_TYPE_LABELS = {
    "STOCK": "普通",
    "CREDIT": "信用",
    "FUTURE": "期货",
    "FUTURE_OPTION": "期货期权",
    "STOCK_OPTION": "股票期权",
}
DOWNLOAD_CALLBACK_EVENT = "xtdata:download_progress"
DOWNLOAD_EVENT_PREFIX = "xtdata:download"
MARKET_ROUTE_MARKETS = ("SH", "SZ")
MARKET_ROUTE_TRADE_ACTIONS = {
    "xttrader.order_stock",
    "xttrader.order_stock_async",
    "xttrader.order_stock_batch",
    "xttrader.cancel_order_stock_sysid",
    "xttrader.cancel_order_stock_sysid_async",
}
MARKET_ROUTE_CONFIG_FILENAME_TEMPLATE = "cfquant_bridge_config_%s.json"


def normalize_account_type(value=None, default="STOCK"):
    raw = value
    if raw is None or raw == "":
        raw = default
    text = str(raw or default or "STOCK").strip()
    if not text:
        text = str(default or "STOCK")
    upper = text.upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "2": "STOCK",
        "STOCK": "STOCK",
        "SECURITY": "STOCK",
        "SECURITY_ACCOUNT": "STOCK",
        "STOCK_ACCOUNT": "STOCK",
        "NORMAL": "STOCK",
        "普通": "STOCK",
        "普通账户": "STOCK",
        "普通证券账户": "STOCK",
        "1": "FUTURE",
        "FUTURE": "FUTURE",
        "FUTURE_ACCOUNT": "FUTURE",
        "期货": "FUTURE",
        "期货账户": "FUTURE",
        "3": "CREDIT",
        "CREDIT": "CREDIT",
        "MARGIN": "CREDIT",
        "MARGIN_TRADING": "CREDIT",
        "CREDIT_ACCOUNT": "CREDIT",
        "信用": "CREDIT",
        "信用账户": "CREDIT",
        "融资融券": "CREDIT",
        "5": "FUTURE_OPTION",
        "FUTURE_OPTION": "FUTURE_OPTION",
        "FUTURE_OPTION_ACCOUNT": "FUTURE_OPTION",
        "FUTUREOPTION": "FUTURE_OPTION",
        "期货期权": "FUTURE_OPTION",
        "期货期权账户": "FUTURE_OPTION",
        "6": "STOCK_OPTION",
        "STOCK_OPTION": "STOCK_OPTION",
        "STOCK_OPTION_ACCOUNT": "STOCK_OPTION",
        "STOCKOPTION": "STOCK_OPTION",
        "OPTION": "STOCK_OPTION",
        "股票期权": "STOCK_OPTION",
        "股票期权账户": "STOCK_OPTION",
    }
    account_type = aliases.get(upper) or aliases.get(text) or upper
    if account_type not in ("STOCK", "CREDIT", "FUTURE", "FUTURE_OPTION", "STOCK_OPTION"):
        raise ValueError("unsupported account_type: %s" % text)
    return account_type


def account_type_label(account_type):
    return ACCOUNT_TYPE_LABELS.get(normalize_account_type(account_type), normalize_account_type(account_type))


def normalize_credit_order_action(value=None, side=None):
    text = str(value or "").strip()
    if not text:
        side_text = str(side or "").strip().lower()
        return "credit_sell" if side_text == "sell" else "credit_buy"
    lowered = text.lower()
    normalized = CREDIT_ORDER_ACTION_ALIASES.get(lowered) or CREDIT_ORDER_ACTION_ALIASES.get(text)
    if normalized:
        return normalized
    normalized = lowered if lowered.startswith("credit_") else "credit_%s" % lowered
    if normalized in CREDIT_ORDER_ACTIONS:
        return normalized
    raise ValueError("unknown credit order action: %s" % text)


def credit_order_action_info(value=None, side=None):
    action = normalize_credit_order_action(value, side=side)
    info = dict(CREDIT_ORDER_ACTIONS[action])
    info["action"] = action
    return info


def credit_actions_info():
    return {
        "queries": [
            {"action": key, "xttrader_action": action}
            for key, action in sorted(CREDIT_ACTIONS.items())
        ],
        "orders": [
            dict({"action": action}, **CREDIT_ORDER_ACTIONS[action])
            for action in CREDIT_ORDER_ACTIONS
        ],
        "aliases": dict(CREDIT_ORDER_ACTION_ALIASES),
    }


def derivative_order_action_candidates(account_type, text):
    account_type = normalize_account_type(account_type)
    text = str(text or "").strip().lower()
    if not text:
        return []
    if account_type == "STOCK_OPTION":
        aliases = {
            "buy_open": "stock_option_buy_open",
            "open_long": "stock_option_buy_open",
            "sell_close": "stock_option_sell_close",
            "close_long": "stock_option_sell_close",
            "sell_open": "stock_option_sell_open",
            "open_short": "stock_option_sell_open",
            "buy_close": "stock_option_buy_close",
            "close_short": "stock_option_buy_close",
            "covered_open": "stock_option_covered_open",
            "covered_close": "stock_option_covered_close",
            "call_exercise": "stock_option_call_exercise",
            "put_exercise": "stock_option_put_exercise",
            "secu_lock": "stock_option_secu_lock",
            "secu_unlock": "stock_option_secu_unlock",
            "lock": "stock_option_secu_lock",
            "unlock": "stock_option_secu_unlock",
        }
        return [
            text,
            aliases.get(text, ""),
            "stock_option_%s" % text,
            "stock_%s" % text,
            "option_%s" % text,
        ]
    aliases = {
        "open_long": "future_open_long",
        "buy_open": "future_open_long",
        "close_long": "future_close_long_history_first",
        "sell_close": "future_close_long_history_first",
        "close_long_history": "future_close_long_history",
        "close_long_today": "future_close_long_today",
        "open_short": "future_open_short",
        "sell_open": "future_open_short",
        "close_short": "future_close_short_history_first",
        "buy_close": "future_close_short_history_first",
        "close_short_history": "future_close_short_history",
        "close_short_today": "future_close_short_today",
        "open": "future_open",
        "close": "future_close",
        "exercise": "future_option_exercise",
        "option_future_option_exercise": "future_option_exercise",
    }
    return [
        text,
        aliases.get(text, ""),
        "future_%s" % text,
    ]


def normalize_derivative_order_action(account_type, value=None, side=None):
    account_type = normalize_account_type(account_type)
    actions = ORDER_ACTIONS_BY_ACCOUNT_TYPE.get(account_type)
    if not actions:
        raise ValueError("unsupported derivative account_type: %s" % account_type)
    text = str(value or "").strip()
    if not text:
        side_text = str(side or "").strip().lower()
        if account_type == "STOCK_OPTION":
            return "stock_option_sell_open" if side_text == "sell" else "stock_option_buy_open"
        return "future_open_short" if side_text == "sell" else "future_open_long"
    if text.lstrip("+-").isdigit():
        action = ORDER_TYPE_ACTIONS_BY_ACCOUNT_TYPE.get(account_type, {}).get(int(text))
        if action:
            return action
    for candidate in derivative_order_action_candidates(account_type, text):
        if candidate and candidate in actions:
            return candidate
    raise ValueError("unknown %s order action: %s" % (account_type, text))


def derivative_order_action_info(account_type, value=None, side=None):
    account_type = normalize_account_type(account_type)
    action = normalize_derivative_order_action(account_type, value, side=side)
    info = dict(ORDER_ACTIONS_BY_ACCOUNT_TYPE[account_type][action])
    info["action"] = action
    return info


def derivative_order_type_info(account_type, order_type):
    account_type = normalize_account_type(account_type)
    order_type = int(order_type)
    action = ORDER_TYPE_ACTIONS_BY_ACCOUNT_TYPE.get(account_type, {}).get(order_type, "")
    info = dict(ORDER_ACTIONS_BY_ACCOUNT_TYPE.get(account_type, {}).get(action) or {})
    if not info:
        info = {"order_type": order_type, "side": "", "label": "", "description": ""}
    info["action"] = action
    info["order_type"] = order_type
    return info


def order_actions_info():
    return {
        "credit": [
            dict({"action": action}, **CREDIT_ORDER_ACTIONS[action])
            for action in CREDIT_ORDER_ACTIONS
        ],
        "future": [
            dict({"action": action}, **FUTURE_ORDER_ACTIONS[action])
            for action in FUTURE_ORDER_ACTIONS
        ],
        "future_option": [
            dict({"action": action}, **FUTURE_OPTION_ORDER_ACTIONS[action])
            for action in FUTURE_OPTION_ORDER_ACTIONS
        ],
        "stock_option": [
            dict({"action": action}, **STOCK_OPTION_ORDER_ACTIONS[action])
            for action in STOCK_OPTION_ORDER_ACTIONS
        ],
        "aliases": dict(ORDER_ACTION_ALIASES),
        "credit_aliases": dict(CREDIT_ORDER_ACTION_ALIASES),
    }


def order_confirmation_text(action, stock_code, volume, price):
    return "%s %s %s @ %.3f" % (
        str(action or "").strip().upper(),
        normalize_stock_code(stock_code),
        int(volume),
        float(price),
    )


def order_confirmation_options(
    account_type,
    side,
    stock_code,
    volume,
    price,
    credit_action=None,
    order_action=None,
    order_type=None,
    allow_legacy_side=False,
):
    account_type = normalize_account_type(account_type)
    side = str(side or "").strip().lower()
    if account_type == "CREDIT":
        info = credit_order_action_info(credit_action, side=side)
        primary = order_confirmation_text(info["action"], stock_code, volume, price)
        legacy = order_confirmation_text(side, stock_code, volume, price)
        return [primary, legacy] if allow_legacy_side and legacy != primary else [primary]
    if account_type in DERIVATIVE_ACCOUNT_TYPES:
        if order_action not in (None, ""):
            info = derivative_order_action_info(account_type, order_action, side=side)
        elif order_type not in (None, ""):
            info = derivative_order_type_info(account_type, order_type)
        else:
            info = derivative_order_action_info(account_type, None, side=side)
        action = info.get("action") or "ORDER_TYPE_%s" % info.get("order_type")
        return [order_confirmation_text(action, stock_code, volume, price)]
    return [order_confirmation_text(side, stock_code, volume, price)]


def resolve_order_action(account_type, side, credit_action=None, order_action=None, explicit_order_type=None):
    account_type = normalize_account_type(account_type)
    if account_type == "CREDIT":
        if credit_action not in (None, ""):
            info = credit_order_action_info(credit_action, side=side)
            return {
                "side": info["side"],
                "order_type": int(info["order_type"]),
                "credit_action": info["action"],
                "credit_action_label": info["label"],
                "order_action": "",
                "order_action_label": "",
            }
        if explicit_order_type not in (None, ""):
            order_type = int(explicit_order_type)
            order_type = CREDIT_LEGACY_ORDER_TYPE_MAP.get(order_type, order_type)
            action = CREDIT_ORDER_TYPE_ACTIONS.get(order_type, "")
            info = CREDIT_ORDER_ACTIONS.get(action) or {}
            return {
                "side": info.get("side") or str(side or "").strip().lower(),
                "order_type": order_type,
                "credit_action": action,
                "credit_action_label": info.get("label", ""),
                "order_action": "",
                "order_action_label": "",
            }
        info = credit_order_action_info(None, side=side)
        return {
            "side": info["side"],
            "order_type": int(info["order_type"]),
            "credit_action": info["action"],
            "credit_action_label": info["label"],
            "order_action": "",
            "order_action_label": "",
        }
    if account_type in DERIVATIVE_ACCOUNT_TYPES:
        if order_action not in (None, ""):
            info = derivative_order_action_info(account_type, order_action, side=side)
        elif explicit_order_type not in (None, ""):
            info = derivative_order_type_info(account_type, explicit_order_type)
        else:
            info = derivative_order_action_info(account_type, None, side=side)
        return {
            "side": info.get("side") or str(side or "").strip().lower(),
            "order_type": int(info["order_type"]),
            "credit_action": "",
            "credit_action_label": "",
            "order_action": info.get("action", ""),
            "order_action_label": info.get("label", ""),
        }
    order_type = explicit_order_type
    if order_type in (None, ""):
        side = str(side or "").strip().lower()
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        order_type = STOCK_BUY if side == "buy" else STOCK_SELL
    return {
        "side": str(side or "").strip().lower(),
        "order_type": int(order_type),
        "credit_action": "",
        "credit_action_label": "",
        "order_action": "",
        "order_action_label": "",
    }


def account_key_for(account_id, account_type=None, bridge_id=None):
    account_id = str(account_id or "").strip()
    if not account_id:
        return ""
    return "%s:%s:%s" % (
        normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID),
        normalize_account_type(account_type),
        account_id,
    )


def account_subscription_keys(account_id, account_type=None, bridge_id=None, account_key=None):
    account_id = str(account_id or "").strip()
    account_key = str(account_key or "").strip()
    bridge_id = normalize_bridge_id(bridge_id) if bridge_id else ""
    keys = []

    def add(value):
        value = str(value or "").strip()
        if value and value not in keys:
            keys.append(value)

    add(account_key)
    if account_id:
        try:
            add(account_key_for(account_id, account_type, bridge_id or DEFAULT_BRIDGE_ID))
        except Exception:
            pass

    web_config = globals().get("WEB_CONFIG")
    if web_config is not None and account_id:
        try:
            configs = web_config.account_configs()
        except Exception:
            configs = {}
        for key, row in configs.items():
            if not isinstance(row, dict):
                continue
            row_account_id = str(row.get("account_id") or "").strip()
            if row_account_id != account_id:
                continue
            if account_type not in (None, ""):
                try:
                    if normalize_account_type(row.get("account_type") or "STOCK") != normalize_account_type(account_type):
                        continue
                except Exception:
                    continue
            if bridge_id and normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID) != bridge_id:
                continue
            add(key)
            add(row.get("account_key"))
            if str(row.get("account_key") or "").strip() == row_account_id:
                add(row_account_id)
            try:
                add(account_key_for(row_account_id, row.get("account_type") or account_type, row.get("bridge_id") or bridge_id or DEFAULT_BRIDGE_ID))
            except Exception:
                pass
    return keys


def account_identity(account_id=None, account_type=None, bridge_id=None, account_key=None):
    account_id = str(account_id or "").strip()
    account_type = normalize_account_type(account_type)
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    key = str(account_key or "").strip() or account_key_for(account_id, account_type, bridge_id)
    return {
        "account_key": key,
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "bridge_id": bridge_id,
    }


def parse_config_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if not text:
        return bool(default)
    if text in ("1", "true", "yes", "y", "on", "enable", "enabled", "open"):
        return True
    if text in ("0", "false", "no", "n", "off", "disable", "disabled", "closed", "close"):
        return False
    return bool(default)


def normalize_market_code(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = text.replace("_", "").replace("-", "")
    aliases = {
        "SH": "SH",
        "SSE": "SH",
        "SHSE": "SH",
        "XSHG": "SH",
        "1": "SH",
        "SZ": "SZ",
        "SZSE": "SZ",
        "XSHE": "SZ",
        "0": "SZ",
        "2": "SZ",
    }
    return aliases.get(text, text if text in MARKET_ROUTE_MARKETS else "")


def stock_code_market(stock_code):
    text = str(stock_code or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        return normalize_market_code(text.rsplit(".", 1)[-1])
    code = re.sub(r"\D", "", text)
    if not code:
        return ""
    if code.startswith(("5", "6", "9")):
        return "SH"
    if code.startswith(("0", "1", "2", "3")):
        return "SZ"
    return ""


def request_params_market(params):
    if not isinstance(params, dict):
        return ""
    for key in ("route_market", "market", "exchange", "exchange_id", "market_id"):
        market = normalize_market_code(params.get(key))
        if market:
            return market
    for key in ("stock_code", "code", "security_code", "instrument_id"):
        market = stock_code_market(params.get(key))
        if market:
            return market
    orders = params.get("orders")
    if isinstance(orders, list):
        markets = set()
        for row in orders:
            market = request_params_market(row) if isinstance(row, dict) else ""
            if market:
                markets.add(market)
        if len(markets) == 1:
            return next(iter(markets))
    return ""


def split_orders_by_market(orders):
    groups = {}
    for index, row in enumerate(orders or []):
        market = request_params_market(row) if isinstance(row, dict) else ""
        if not market:
            return {}
        groups.setdefault(market, []).append((index, row))
    return groups


def data_request_markets(params):
    result = []

    def add(value):
        market = normalize_market_code(value) or stock_code_market(value)
        if market and market not in result:
            result.append(market)

    if not isinstance(params, dict):
        return result
    explicit = request_params_market(params)
    if explicit:
        add(explicit)
    for key in ("stock_code", "code", "security_code", "instrument_id"):
        if params.get(key) not in (None, ""):
            add(params.get(key))
    for key in ("code_list", "stock_list", "stock_codes", "stocks"):
        value = params.get(key)
        if isinstance(value, str):
            items = [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
        elif isinstance(value, (list, tuple, set)):
            items = [item for item in value if str(item).strip()]
        else:
            items = []
        for item in items:
            add(item)
    return result


def market_account_row_market(row):
    if isinstance(row, dict):
        for key in ("market", "exchange", "exchange_id", "market_id", "m_strExchangeID"):
            market = normalize_market_code(row.get(key))
            if market:
                return market
        for key in ("stock_code", "code", "security_code"):
            market = stock_code_market(row.get(key))
            if market:
                return market
        instrument = str(row.get("m_strInstrumentID") or row.get("instrument_id") or "").strip()
        exchange = normalize_market_code(row.get("m_strExchangeID") or row.get("exchange_id"))
        if instrument and exchange:
            return exchange
        if instrument:
            market = stock_code_market(instrument)
            if market:
                return market
    return stock_code_market(row)


def default_market_bridge_id(account_id, account_type="STOCK", parent_bridge_id=None, market=""):
    market = normalize_market_code(market)
    if market not in MARKET_ROUTE_MARKETS:
        market = "SH"
    parent = normalize_bridge_id(parent_bridge_id or DEFAULT_BRIDGE_ID)
    if parent == DEFAULT_BRIDGE_ID:
        seed = "%s:%s" % (normalize_account_type(account_type), str(account_id or "").strip())
        parent = "acct_%s" % hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return normalize_bridge_id("%s_%s" % (parent, market.lower()))


def normalize_market_bridge_config(value, account_id="", account_type="STOCK", parent_bridge_id=None, enabled=False):
    raw = value if isinstance(value, dict) else {}
    result = {}
    for market in MARKET_ROUTE_MARKETS:
        item = raw.get(market) or raw.get(market.lower()) or {}
        if isinstance(item, str):
            item = {"bridge_id": item}
        if not isinstance(item, dict):
            item = {}
        has_input = bool(item)
        qmt_dir = normalize_optional_path(
            item.get("qmt_dir") or item.get("python_dir") or item.get("core_dir")
        )
        bridge_id = str(item.get("bridge_id") or item.get("id") or "").strip()
        if enabled or has_input or qmt_dir:
            bridge_id = normalize_bridge_id(
                bridge_id or default_market_bridge_id(account_id, account_type, parent_bridge_id, market)
            )
            result[market] = {
                "market": market,
                "bridge_id": bridge_id,
                "qmt_dir": qmt_dir,
                "config_filename": MARKET_ROUTE_CONFIG_FILENAME_TEMPLATE % market,
                "enabled": parse_config_bool(item.get("enabled"), True),
            }
    return result


def account_config_market_bridge_ids(config, account_id="", account_type="STOCK", parent_bridge_id=None):
    if not isinstance(config, dict):
        return []
    if not parse_config_bool(config.get("market_routing_enabled"), False):
        return []
    routes = normalize_market_bridge_config(
        config.get("market_bridges") or {},
        account_id=str(config.get("account_id") or account_id or "").strip(),
        account_type=normalize_account_type(config.get("account_type") or account_type or "STOCK"),
        parent_bridge_id=config.get("bridge_id") or parent_bridge_id,
        enabled=True,
    )
    bridge_ids = []
    for route in routes.values():
        if not isinstance(route, dict):
            continue
        if route.get("enabled", True) is False:
            continue
        bridge_id = normalize_bridge_id(route.get("bridge_id") or "")
        if bridge_id and bridge_id not in bridge_ids:
            bridge_ids.append(bridge_id)
    return bridge_ids


def account_config_has_market_bridge(config, bridge_id, account_id="", account_type="STOCK", parent_bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or "")
    if not bridge_id:
        return False
    return bridge_id in account_config_market_bridge_ids(
        config,
        account_id=account_id,
        account_type=account_type,
        parent_bridge_id=parent_bridge_id,
    )


def get_lan_ip():
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def normalize_web_port(value, default=8765, strict=False):
    if value is None or value == "":
        if strict:
            raise ValueError("web port is required")
        return int(default)
    try:
        port = int(value)
    except Exception:
        if strict:
            raise ValueError("web port must be an integer")
        return int(default)
    if port < 1 or port > 65535:
        if strict:
            raise ValueError("web port must be between 1 and 65535")
        return int(default)
    return port


def normalize_domain_patterns(value):
    if isinstance(value, str):
        raw_items = re.split(r"[\s,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = []
    result = []
    for item in raw_items:
        item = str(item or "").strip().lower()
        if not item:
            continue
        if "://" in item:
            parsed = urllib.parse.urlparse(item)
            item = (parsed.hostname or "").lower()
        if item.startswith("[") and item.endswith("]"):
            item = item[1:-1]
        if item and item not in result:
            result.append(item)
    return result


def extract_host_name(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        if "://" in value:
            return (urllib.parse.urlparse(value).hostname or "").lower()
        if value.startswith("["):
            end = value.find("]")
            return value[1:end].lower() if end >= 0 else value.strip("[]").lower()
        return value.split(":", 1)[0].lower()
    except Exception:
        return ""


def is_loopback_host(host):
    host = extract_host_name(host)
    return host in ("localhost", "::1", "0:0:0:0:0:0:0:1") or host.startswith("127.")


def host_matches_patterns(host, patterns):
    host = extract_host_name(host)
    if not host:
        return True
    if is_loopback_host(host):
        return True
    for pattern in normalize_domain_patterns(patterns):
        if pattern == "*" or fnmatch.fnmatch(host, pattern):
            return True
    return False


def web_password_hash(password, salt):
    salt_bytes = bytes.fromhex(str(salt))
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt_bytes,
        120000,
    )
    return digest.hex()


def mask_text(value):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 2:
        return "*" * len(value)
    return "%s%s" % (value[:1], "*" * (len(value) - 1))


def clear_web_auth_tokens():
    with WEB_AUTH_LOCK:
        WEB_AUTH_TOKENS.clear()
        _delete_persistent_web_auth_sessions_locked()


def _web_auth_token_hash(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _web_auth_settings_db_path():
    config = globals().get("WEB_CONFIG")
    return getattr(config, "settings_db_path", WEB_SETTINGS_DB_FILE)


def _ensure_web_auth_session_store_locked(conn):
    conn.execute(
        "create table if not exists web_auth_sessions ("
        "token_hash text primary key,"
        "username text not null,"
        "created_at real not null,"
        "expires_at real not null,"
        "last_seen_at real not null)"
    )


def _delete_persistent_web_auth_sessions_locked():
    try:
        with sqlite3.connect(_web_auth_settings_db_path()) as conn:
            _ensure_web_auth_session_store_locked(conn)
            conn.execute("delete from web_auth_sessions")
    except Exception as e:
        safe_print("web auth persistent sessions clear failed: %s" % e)


def _delete_persistent_web_auth_session_locked(token):
    try:
        with sqlite3.connect(_web_auth_settings_db_path()) as conn:
            _ensure_web_auth_session_store_locked(conn)
            conn.execute("delete from web_auth_sessions where token_hash = ?", (_web_auth_token_hash(token),))
    except Exception as e:
        safe_print("web auth persistent session revoke failed: %s" % e)


def _save_persistent_web_auth_session_locked(token, username, created_at, expires_at):
    try:
        with sqlite3.connect(_web_auth_settings_db_path()) as conn:
            _ensure_web_auth_session_store_locked(conn)
            conn.execute("delete from web_auth_sessions where expires_at <= ?", (time.time(),))
            conn.execute(
                "insert or replace into web_auth_sessions "
                "(token_hash, username, created_at, expires_at, last_seen_at) "
                "values (?, ?, ?, ?, ?)",
                (_web_auth_token_hash(token), str(username or ""), created_at, expires_at, created_at),
            )
    except Exception as e:
        safe_print("web auth persistent session save failed: %s" % e)


def _persistent_web_auth_token_info_locked(token):
    try:
        now = time.time()
        with sqlite3.connect(_web_auth_settings_db_path()) as conn:
            _ensure_web_auth_session_store_locked(conn)
            conn.execute("delete from web_auth_sessions where expires_at <= ?", (now,))
            row = conn.execute(
                "select username, created_at, expires_at from web_auth_sessions where token_hash = ?",
                (_web_auth_token_hash(token),),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "update web_auth_sessions set last_seen_at = ? where token_hash = ?",
                (now, _web_auth_token_hash(token)),
            )
        return {
            "username": str(row[0] or ""),
            "created_at": float(row[1] or 0),
            "expires_at": float(row[2] or 0),
            "persistent": True,
        }
    except Exception as e:
        safe_print("web auth persistent session lookup failed: %s" % e)
        return None


def issue_web_auth_token(username, remember=False):
    token = secrets.token_urlsafe(32)
    created_at = time.time()
    expires_at = created_at + WEB_AUTH_SESSION_TTL_SECONDS if remember else 0
    with WEB_AUTH_LOCK:
        WEB_AUTH_TOKENS[token] = {
            "username": str(username or ""),
            "created_at": created_at,
            "expires_at": expires_at,
            "persistent": bool(remember),
        }
        if remember:
            _save_persistent_web_auth_session_locked(token, username, created_at, expires_at)
    return token


def web_auth_token_info(token):
    token = str(token or "").strip()
    if not token:
        return None
    with WEB_AUTH_LOCK:
        info = WEB_AUTH_TOKENS.get(token)
        now = time.time()
        if info:
            expires_at = float(info.get("expires_at") or 0)
            if expires_at and expires_at <= now:
                WEB_AUTH_TOKENS.pop(token, None)
                _delete_persistent_web_auth_session_locked(token)
                return None
            return dict(info)
        info = _persistent_web_auth_token_info_locked(token)
        if info:
            WEB_AUTH_TOKENS[token] = dict(info)
            return dict(info)
        return None


def revoke_web_auth_token(token):
    token = str(token or "").strip()
    if not token:
        return
    with WEB_AUTH_LOCK:
        WEB_AUTH_TOKENS.pop(token, None)
        _delete_persistent_web_auth_session_locked(token)


def builtin_avatar_catalog():
    return [dict(item) for item in BUILTIN_AVATARS]


def normalize_avatar_url(value):
    url = str(value or "").strip()
    if not url:
        return DEFAULT_AVATAR_URL
    if url in BUILTIN_AVATAR_URLS:
        return url
    if url.startswith(AVATAR_UPLOAD_URL_PREFIX):
        filename = posixpath.basename(url)
        if (
            filename
            and filename == url[len(AVATAR_UPLOAD_URL_PREFIX):]
            and re.match(r"^[A-Za-z0-9_.-]+$", filename)
            and os.path.splitext(filename)[1].lower() in AVATAR_UPLOAD_EXTENSIONS
        ):
            return AVATAR_UPLOAD_URL_PREFIX + filename
    return DEFAULT_AVATAR_URL


def avatar_kind(url):
    url = normalize_avatar_url(url)
    return "upload" if url.startswith(AVATAR_UPLOAD_URL_PREFIX) else "builtin"


def normalize_user_profile(value=None):
    row = value if isinstance(value, dict) else {}
    avatar_url = normalize_avatar_url(row.get("avatar_url") or row.get("avatar"))
    display_name = str(row.get("display_name") or row.get("nickname") or "").strip()[:40]
    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "avatar_kind": avatar_kind(avatar_url),
        "updated_at": float(row.get("updated_at") or 0),
    }


def profile_display_label(profile, username=""):
    profile = normalize_user_profile(profile)
    return profile.get("display_name") or str(username or "").strip() or "管理员"


def user_profile_response(profile=None):
    base_profile = profile if profile is not None else (WEB_CONFIG.user_profile() if WEB_CONFIG is not None else {})
    profile = normalize_user_profile(base_profile)
    username = WEB_CONFIG.web_auth_info(include_username=True).get("username") if WEB_CONFIG is not None else ""
    profile["username"] = username or ""
    profile["display_label"] = profile_display_label(profile, username)
    return {
        "profile": profile,
        "avatars": builtin_avatar_catalog(),
        "upload": {
            "max_bytes": AVATAR_UPLOAD_MAX_BYTES,
            "allowed_extensions": sorted(AVATAR_UPLOAD_EXTENSIONS),
        },
    }


def detect_avatar_extension(filename, content_type, content):
    content = content or b""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return ".gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    ext = os.path.splitext(str(filename or ""))[1].lower()
    ctype = str(content_type or "").lower()
    if ext in AVATAR_UPLOAD_EXTENSIONS and ctype in ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"):
        return ".jpg" if ext == ".jpeg" else ext
    raise ValueError("只支持 PNG、JPG、WEBP 或 GIF 头像")


class WebRuntimeConfig(object):
    def __init__(self, path, settings_db_path=None):
        self.path = path
        self.settings_db_path = settings_db_path or WEB_SETTINGS_DB_FILE
        self._lock = threading.RLock()
        self._data = {
            "bridges": {},
            "account_pairs": {},
            "account_configs": {},
            "default_account_id": DEFAULT_ACCOUNT_ID,
            "default_account_type": "STOCK",
            "default_account_key": "",
            "initialized": False,
            "data_provider_account_id": "",
            "data_provider_account_type": "STOCK",
            "data_provider_account_key": "",
            "api_key": "",
            "allow_remote": False,
            "api_base_url": "",
            "web_port": normalize_web_port(os.environ.get("CFQUANT_WEB_PORT"), default=8765),
            "web_allowed_domains": "",
            "web_auth_enabled": False,
            "web_auth_username": "",
            "web_auth_salt": "",
            "web_auth_hash": "",
            "user_profile": normalize_user_profile({}),
            "cleanup_qmt_userdata_logs": False,
            "qmt_log_language": os.environ.get("CFQUANT_QMT_LOG_LANGUAGE", "zh"),
            "qmt_log_enabled": normalize_log_enabled(os.environ.get("CFQUANT_QMT_LOG_ENABLED", "1")),
            "transport_mode": os.environ.get("CFQUANT_WEB_TRANSPORT_MODE", os.environ.get("CFQUANT_TRANSPORT", "ctypes")),
        }
        self.load()

    def load(self):
        with self._lock:
            legacy_settings = {}
            if os.path.isfile(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, dict):
                        self._data["bridges"] = self._normalize_bridges(raw.get("bridges") or {})
                        self._data["account_pairs"] = self._normalize_pairs(raw.get("account_pairs") or {})
                        self._data["account_configs"] = self._normalize_account_configs(raw.get("account_configs") or {})
                        self._data["default_account_id"] = str(
                            raw.get("default_account_id") or DEFAULT_ACCOUNT_ID
                        ).strip() or DEFAULT_ACCOUNT_ID
                        self._data["default_account_type"] = normalize_account_type(raw.get("default_account_type") or "STOCK")
                        self._data["default_account_key"] = self._coerce_account_key_locked(
                            account_key=raw.get("default_account_key"),
                            account_id=self._data["default_account_id"],
                            account_type=self._data["default_account_type"],
                        )
                        self._data["initialized"] = bool(raw.get("initialized"))
                        self._data["data_provider_account_id"] = str(
                            raw.get("data_provider_account_id") or ""
                        ).strip()
                        self._data["data_provider_account_type"] = normalize_account_type(raw.get("data_provider_account_type") or "STOCK")
                        self._data["data_provider_account_key"] = self._coerce_account_key_locked(
                            account_key=raw.get("data_provider_account_key"),
                            account_id=self._data["data_provider_account_id"],
                            account_type=self._data["data_provider_account_type"],
                        )
                        self._data["user_profile"] = normalize_user_profile(raw.get("user_profile") or {})
                        web_server = raw.get("web_server") if isinstance(raw.get("web_server"), dict) else {}
                        web_port = raw.get("web_port")
                        if web_port in (None, ""):
                            web_port = web_server.get("port")
                        self._data["web_port"] = normalize_web_port(web_port, default=self._data["web_port"])
                        legacy_settings = {
                            "api_key": str(raw.get("api_key") or "").strip(),
                            "allow_remote": "1" if bool(raw.get("allow_remote")) else "0",
                            "api_base_url": str(raw.get("api_base_url") or "").strip(),
                        }
                except Exception as e:
                    safe_print("web runtime config load failed: %s" % e)
            try:
                self._ensure_settings_db_locked()
                self._migrate_legacy_settings_locked(legacy_settings)
                self._load_settings_locked()
            except Exception as e:
                safe_print("web sqlite settings load failed: %s" % e)
            self._repair_account_defaults_locked()

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._data, ensure_ascii=False))

    def bridges(self):
        bridges = dict(ENV_BRIDGES)
        with self._lock:
            custom = self._normalize_bridges(self._data.get("bridges") or {})
        bridges.update(custom)
        return bridges

    def account_pairs(self):
        with self._lock:
            return dict(self._data.get("account_pairs") or {})

    def account_configs(self):
        with self._lock:
            return json.loads(json.dumps(self._data.get("account_configs") or {}, ensure_ascii=False))

    def account_config(self, account_id=None, account_type=None, bridge_id=None, account_key=None):
        account_id = str(account_id or "").strip()
        account_key = str(account_key or "").strip()
        with self._lock:
            key = self._coerce_account_key_locked(
                account_key=account_key,
                account_id=account_id,
                account_type=account_type,
                bridge_id=bridge_id,
            )
            value = (self._data.get("account_configs") or {}).get(key) if key else None
            return json.loads(json.dumps(value, ensure_ascii=False)) if value else None

    def account_config_by_key(self, account_key):
        account_key = str(account_key or "").strip()
        if not account_key:
            return None
        with self._lock:
            value = (self._data.get("account_configs") or {}).get(account_key)
            return json.loads(json.dumps(value, ensure_ascii=False)) if value else None

    def _runtime_trade_qmt_dir(self, bridge_id):
        registry = globals().get("RUNTIME_VERSIONS")
        if registry is None:
            return ""
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        try:
            report = registry.latest(bridge_id)
        except Exception:
            return ""
        rows = report.get("reports") if isinstance(report, dict) else []
        if not isinstance(rows, list):
            return ""
        for row in rows:
            if not isinstance(row, dict):
                continue
            channel_key = str(row.get("channel_key") or "").strip().lower()
            runtime_mode = str(row.get("runtime_mode") or row.get("bridge") or "").strip().lower()
            if channel_key != "trade" and "txtradebridge" not in runtime_mode:
                continue
            core_dir = normalize_optional_path(row.get("core_dir") or "")
            if not core_dir:
                version_file = normalize_optional_path(row.get("version_file") or "")
                core_dir = os.path.dirname(version_file) if version_file else ""
            if os.path.basename(core_dir).lower() == "cfquant":
                core_dir = os.path.dirname(core_dir)
            return normalize_optional_path(core_dir)
        return ""

    def _find_account_configs_locked(self, account_id=None, account_type=None, bridge_id=None):
        account_id = str(account_id or "").strip()
        account_type = normalize_account_type(account_type) if account_type not in (None, "") else ""
        bridge_id = normalize_bridge_id(bridge_id) if bridge_id else ""
        rows = []
        for key, item in (self._data.get("account_configs") or {}).items():
            if not isinstance(item, dict):
                continue
            if account_id and str(item.get("account_id") or "").strip() != account_id:
                continue
            if account_type and normalize_account_type(item.get("account_type") or "STOCK") != account_type:
                continue
            if bridge_id and normalize_bridge_id(item.get("bridge_id") or DEFAULT_BRIDGE_ID) != bridge_id:
                continue
            row = dict(item)
            row.setdefault("account_key", key)
            rows.append((key, row))
        return rows

    def _coerce_account_key_locked(self, account_key=None, account_id=None, account_type=None, bridge_id=None):
        configs = self._data.get("account_configs") or {}
        account_key = str(account_key or "").strip()
        if account_key and account_key in configs:
            return account_key
        account_id = str(account_id or "").strip()
        if not account_id:
            return ""
        matches = self._find_account_configs_locked(account_id, account_type, bridge_id)
        if not matches:
            return ""
        default_key = str(self._data.get("default_account_key") or "").strip()
        if default_key:
            for key, _row in matches:
                if key == default_key:
                    return key
        for key, row in matches:
            if row.get("enabled", True):
                return key
        return matches[0][0]

    def _first_account_key_locked(self):
        configs = self._data.get("account_configs") or {}
        for key, row in configs.items():
            if isinstance(row, dict) and row.get("enabled", True):
                return key
        for key in configs:
            return key
        return ""

    def _repair_account_defaults_locked(self):
        configs = self._data.get("account_configs") or {}
        default_key = str(self._data.get("default_account_key") or "").strip()
        if default_key not in configs:
            default_key = self._coerce_account_key_locked(
                account_id=self._data.get("default_account_id") or DEFAULT_ACCOUNT_ID,
                account_type=self._data.get("default_account_type") or "STOCK",
            ) or self._first_account_key_locked()
            self._data["default_account_key"] = default_key
        if default_key and default_key in configs:
            row = configs[default_key]
            self._data["default_account_id"] = str(row.get("account_id") or DEFAULT_ACCOUNT_ID).strip() or DEFAULT_ACCOUNT_ID
            self._data["default_account_type"] = normalize_account_type(row.get("account_type") or "STOCK")
        provider_key = str(self._data.get("data_provider_account_key") or "").strip()
        if provider_key not in configs:
            provider_key = self._coerce_account_key_locked(
                account_id=self._data.get("data_provider_account_id") or "",
                account_type=self._data.get("data_provider_account_type") or "STOCK",
            )
            self._data["data_provider_account_key"] = provider_key
        if provider_key and provider_key in configs:
            row = configs[provider_key]
            self._data["data_provider_account_id"] = str(row.get("account_id") or "").strip()
            self._data["data_provider_account_type"] = normalize_account_type(row.get("account_type") or "STOCK")
            for key, item in configs.items():
                if isinstance(item, dict):
                    item["data_provider"] = key == provider_key

    def initialized(self):
        with self._lock:
            return bool(self._data.get("initialized"))

    def data_provider_account_id(self):
        with self._lock:
            return str(self._data.get("data_provider_account_id") or "").strip()

    def data_provider_account_key(self):
        with self._lock:
            return str(self._data.get("data_provider_account_key") or "").strip()

    def set_data_provider_account_id(self, account_id=None, account_type=None, bridge_id=None, account_key=None):
        account_id = str(account_id or "").strip()
        with self._lock:
            configs = self._data.setdefault("account_configs", {})
            selected_key = self._coerce_account_key_locked(
                account_key=account_key,
                account_id=account_id,
                account_type=account_type,
                bridge_id=bridge_id,
            )
            if (account_id or account_key) and not selected_key:
                raise ValueError("unknown account: %s" % (account_key or account_id))
            for key, item in configs.items():
                if isinstance(item, dict):
                    item["data_provider"] = key == selected_key
            selected = configs.get(selected_key) if selected_key else {}
            self._data["data_provider_account_key"] = selected_key
            self._data["data_provider_account_id"] = str((selected or {}).get("account_id") or account_id or "").strip()
            self._data["data_provider_account_type"] = normalize_account_type((selected or {}).get("account_type") or account_type or "STOCK")
            self._save_locked()
        return self.setup_info()

    def setup_info(self):
        with self._lock:
            configs = json.loads(json.dumps(self._data.get("account_configs") or {}, ensure_ascii=False))
            default_account_id = str(
                self._data.get("default_account_id") or DEFAULT_ACCOUNT_ID
            ).strip() or DEFAULT_ACCOUNT_ID
            default_account_type = normalize_account_type(self._data.get("default_account_type") or "STOCK")
            default_account_key = str(self._data.get("default_account_key") or "").strip()
            provider = str(self._data.get("data_provider_account_id") or "").strip()
            provider_type = normalize_account_type(self._data.get("data_provider_account_type") or "STOCK")
            provider_key = str(self._data.get("data_provider_account_key") or "").strip()
            initialized = bool(self._data.get("initialized"))
        default_config = configs.get(default_account_key) or {}
        default_mode = normalize_transport_mode(
            default_config.get("mode") or self.transport_mode()
        )
        default_qmt_trade_dir = default_config.get("qmt_trade_dir") or ""
        if not default_qmt_trade_dir and default_mode == "lttx":
            default_qmt_trade_dir = self._runtime_trade_qmt_dir(
                default_config.get("bridge_id") or DEFAULT_BRIDGE_ID
            )
        return {
            "initialized": initialized,
            "setup_required": not initialized,
            "default_account_id": default_account_id,
            "default_account_type": default_account_type,
            "default_account_key": default_account_key,
            "default_qmt_dir": default_config.get("qmt_dir") or "",
            "default_qmt_trade_dir": default_qmt_trade_dir,
            "default_mode": default_mode,
            "data_provider_account_id": provider,
            "data_provider_account_type": provider_type,
            "data_provider_account_key": provider_key,
            "account_configs": configs,
        }

    def save_account_config(
        self,
        account_id,
        account_type="STOCK",
        bridge_id=None,
        display_name=None,
        qmt_dir=None,
        qmt_trade_dir=None,
        mode="ctypes",
        data_provider=False,
        enabled=True,
        market_routing_enabled=False,
        market_bridges=None,
    ):
        account_id = str(account_id or "").strip()
        if not account_id:
            raise ValueError("account_id is required")
        account_type = normalize_account_type(account_type)
        display_name = None if display_name is None else str(display_name).strip()
        qmt_dir = normalize_optional_path(qmt_dir)
        qmt_trade_dir = normalize_optional_path(qmt_trade_dir)
        mode = normalize_transport_mode(mode)
        if mode == "lttx":
            if not qmt_dir:
                raise ValueError("高级模式需要填写普通 QMT 核心目录")
            if not qmt_trade_dir:
                raise ValueError("高级模式需要填写极速交易端 QMT 核心目录")
            if os.path.normcase(os.path.normpath(qmt_dir)) == os.path.normcase(os.path.normpath(qmt_trade_dir)):
                raise ValueError("高级模式的两个 QMT 核心目录必须不同")
        else:
            qmt_trade_dir = ""
        now = time.time()
        with self._lock:
            configs = self._data.setdefault("account_configs", {})
            bridge_id = self._account_bridge_id_locked(account_id, account_type, bridge_id, qmt_dir)
            account_key = account_key_for(account_id, account_type, bridge_id)
            existing = configs.get(account_key)
            if display_name is None and isinstance(existing, dict):
                display_name = str(existing.get("display_name") or existing.get("account_name") or "").strip()
            display_name = display_name or ""
            if market_bridges is None and isinstance(existing, dict):
                market_bridges = existing.get("market_bridges") or {}
                market_routing_enabled = parse_config_bool(
                    existing.get("market_routing_enabled"),
                    market_routing_enabled,
                )
            market_routing_enabled = parse_config_bool(market_routing_enabled, False)
            market_routes = normalize_market_bridge_config(
                market_bridges,
                account_id=account_id,
                account_type=account_type,
                parent_bridge_id=bridge_id,
                enabled=market_routing_enabled,
            )
            market_routing_enabled = bool(market_routing_enabled and market_routes)
            if bridge_id not in self.bridges():
                self._data.setdefault("bridges", {})[bridge_id] = self._bridge_row(
                    bridge_id,
                    self._account_bridge_name(account_id, bridge_id),
                    qmt_dir,
                    {},
                )
            else:
                bridge = self._data.setdefault("bridges", {}).get(bridge_id)
                if bridge is None:
                    self._data.setdefault("bridges", {})[bridge_id] = self._bridge_row(
                        bridge_id,
                        self._account_bridge_name(account_id, bridge_id),
                        qmt_dir,
                        {},
                    )
                elif qmt_dir and self._can_update_bridge_python_dir_locked(bridge_id, account_key, qmt_dir):
                    bridge["python_dir"] = qmt_dir
            if market_routing_enabled:
                for market, market_row in market_routes.items():
                    if not market_row.get("enabled", True):
                        continue
                    market_bridge_id = normalize_bridge_id(market_row.get("bridge_id"))
                    market_qmt_dir = normalize_optional_path(market_row.get("qmt_dir"))
                    bridge = self._data.setdefault("bridges", {}).get(market_bridge_id)
                    if bridge is None:
                        self._data.setdefault("bridges", {})[market_bridge_id] = self._bridge_row(
                            market_bridge_id,
                            self._account_market_bridge_name(account_id, market, market_bridge_id),
                            market_qmt_dir,
                            {},
                        )
                    elif market_qmt_dir:
                        bridge["python_dir"] = market_qmt_dir
            row = {
                "account_key": account_key,
                "account_id": account_id,
                "account_type": account_type,
                "account_type_label": account_type_label(account_type),
                "display_name": display_name,
                "bridge_id": bridge_id,
                "qmt_dir": qmt_dir,
                "qmt_trade_dir": qmt_trade_dir,
                "mode": mode,
                "data_provider": bool(data_provider),
                "enabled": bool(enabled),
                "market_routing_enabled": market_routing_enabled,
                "market_bridges": market_routes if market_routing_enabled else {},
                "updated_at": now,
            }
            if data_provider:
                for item in configs.values():
                    if isinstance(item, dict):
                        item["data_provider"] = False
                self._data["data_provider_account_key"] = account_key
                self._data["data_provider_account_id"] = account_id
                self._data["data_provider_account_type"] = account_type
            elif self._data.get("data_provider_account_key") == account_key:
                self._data["data_provider_account_key"] = ""
                self._data["data_provider_account_id"] = ""
            configs[account_key] = row
            self._data.setdefault("account_pairs", {})[account_key] = {
                "account_key": account_key,
                "account_id": account_id,
                "account_type": account_type,
                "bridge_id": bridge_id,
                "display_name": display_name,
                "qmt_dir": qmt_dir,
                "qmt_trade_dir": qmt_trade_dir,
                "market_routing_enabled": market_routing_enabled,
                "market_bridges": market_routes if market_routing_enabled else {},
                "updated_at": now,
            }
            self._data["initialized"] = True
            if len(configs) == 1:
                self._data["default_account_key"] = account_key
                self._data["default_account_id"] = account_id
                self._data["default_account_type"] = account_type
                self._data["transport_mode"] = mode
            self._save_locked()
            self._save_settings_locked({"transport_mode": self._data["transport_mode"]})
        return row

    def _account_bridge_id_locked(self, account_id, account_type="STOCK", requested_bridge_id=None, qmt_dir=""):
        requested = str(requested_bridge_id or "").strip()
        if requested:
            return normalize_bridge_id(requested)

        configs = self._data.setdefault("account_configs", {})
        qmt_dir_key = normalize_optional_path(qmt_dir).lower()
        existing_key = self._coerce_account_key_locked(account_id=account_id, account_type=account_type)
        existing = configs.get(existing_key) if existing_key else None
        if isinstance(existing, dict) and existing.get("bridge_id"):
            existing_bridge_id = normalize_bridge_id(existing.get("bridge_id"))
            existing_qmt_dir_key = normalize_optional_path(
                existing.get("qmt_dir") or existing.get("python_dir")
            ).lower()
            if not qmt_dir_key or not existing_qmt_dir_key or qmt_dir_key == existing_qmt_dir_key:
                return existing_bridge_id
            same_dir_bridge = self._bridge_id_for_qmt_dir_locked(qmt_dir_key)
            if same_dir_bridge:
                return same_dir_bridge
            if not self._bridge_has_other_account_locked(existing_bridge_id, existing_key):
                return existing_bridge_id
            return self._new_account_bridge_id_locked(account_id, account_type)

        if qmt_dir_key:
            same_dir_bridge = self._bridge_id_for_qmt_dir_locked(qmt_dir_key)
            if same_dir_bridge:
                return same_dir_bridge

        if not configs:
            return DEFAULT_BRIDGE_ID

        if not qmt_dir_key:
            return DEFAULT_BRIDGE_ID

        return self._new_account_bridge_id_locked(account_id, account_type)

    def _bridge_id_for_qmt_dir_locked(self, qmt_dir_key):
        for item in self._data.setdefault("account_configs", {}).values():
            if not isinstance(item, dict):
                continue
            item_qmt_dir = normalize_optional_path(item.get("qmt_dir") or item.get("python_dir")).lower()
            if item_qmt_dir and item_qmt_dir == qmt_dir_key and item.get("bridge_id"):
                return normalize_bridge_id(item.get("bridge_id"))
        return ""

    def _bridge_has_other_account_locked(self, bridge_id, account_key):
        bridge_id = normalize_bridge_id(bridge_id)
        for key, item in self._data.setdefault("account_configs", {}).items():
            if key == account_key or not isinstance(item, dict):
                continue
            if normalize_bridge_id(item.get("bridge_id")) == bridge_id:
                return True
        return False

    def _can_update_bridge_python_dir_locked(self, bridge_id, account_key, qmt_dir):
        qmt_dir_key = normalize_optional_path(qmt_dir).lower()
        if not qmt_dir_key:
            return False
        bridge = self._data.setdefault("bridges", {}).get(normalize_bridge_id(bridge_id)) or {}
        bridge_qmt_dir_key = normalize_optional_path(bridge.get("python_dir")).lower()
        if bridge_qmt_dir_key == qmt_dir_key:
            return False
        for key, item in self._data.setdefault("account_configs", {}).items():
            if key == account_key or not isinstance(item, dict):
                continue
            if normalize_bridge_id(item.get("bridge_id")) != normalize_bridge_id(bridge_id):
                continue
            item_qmt_dir_key = normalize_optional_path(item.get("qmt_dir") or item.get("python_dir")).lower()
            if item_qmt_dir_key and item_qmt_dir_key != qmt_dir_key:
                return False
        return True

    def _new_account_bridge_id_locked(self, account_id, account_type="STOCK"):
        seed = "%s:%s" % (normalize_account_type(account_type), str(account_id or "").strip())
        prefix = "acct_%s" % hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
        bridge_id = normalize_bridge_id(prefix)
        used = set(self.bridges().keys())
        if bridge_id not in used:
            return bridge_id
        index = 2
        while True:
            candidate = normalize_bridge_id("%s_%s" % (bridge_id, index))
            if candidate not in used:
                return candidate
            index += 1

    def _account_bridge_name(self, account_id, bridge_id):
        if bridge_id == DEFAULT_BRIDGE_ID:
            return "默认账号"
        return "账号 %s" % mask_text(account_id)

    def _account_market_bridge_name(self, account_id, market, bridge_id):
        market = normalize_market_code(market) or str(market or "").upper()
        return "%s %s" % (self._account_bridge_name(account_id, bridge_id), market)

    def reset_setup(self):
        with self._lock:
            self._data["initialized"] = False
            self._data["account_configs"] = {}
            self._data["account_pairs"] = {}
            self._data["default_account_id"] = DEFAULT_ACCOUNT_ID
            self._data["default_account_type"] = "STOCK"
            self._data["default_account_key"] = ""
            self._data["data_provider_account_id"] = ""
            self._data["data_provider_account_type"] = "STOCK"
            self._data["data_provider_account_key"] = ""
            self._data["transport_mode"] = "ctypes"
            self._save_locked()
            self._save_settings_locked({"transport_mode": "ctypes"})
        return self.setup_info()

    def api_key(self):
        with self._lock:
            return str(self._data.get("api_key") or "").strip()

    def api_key_info(self, include_secret=True):
        api_key = self.api_key()
        if not api_key:
            return {"enabled": False, "masked": "", "api_key": ""}
        if len(api_key) <= 8:
            masked = "*" * len(api_key)
        else:
            masked = "%s%s" % (api_key[:4], "*" * (len(api_key) - 8) + api_key[-4:])
        return {"enabled": True, "masked": masked, "api_key": api_key if include_secret else ""}

    def set_api_key(self, api_key):
        api_key = str(api_key or "").strip()
        with self._lock:
            self._data["api_key"] = api_key
            self._save_settings_locked({"api_key": api_key})
        return self.api_key_info()

    def generate_api_key(self):
        api_key = "cfq_%s" % secrets.token_urlsafe(24)
        info = self.set_api_key(api_key)
        info["api_key"] = api_key
        return info

    def allow_remote(self):
        with self._lock:
            return bool(self._data.get("allow_remote"))

    def web_port(self):
        with self._lock:
            return normalize_web_port(self._data.get("web_port"), default=8765)

    def allowed_domains(self):
        with self._lock:
            return normalize_domain_patterns(self._data.get("web_allowed_domains") or "")

    def web_auth_enabled(self):
        with self._lock:
            return bool(self._data.get("web_auth_enabled"))

    def web_auth_info(self, include_username=True):
        with self._lock:
            username = str(self._data.get("web_auth_username") or "").strip()
            enabled = bool(self._data.get("web_auth_enabled"))
            configured = bool(self._data.get("web_auth_hash"))
        return {
            "enabled": enabled,
            "configured": configured,
            "username": username if include_username else "",
            "username_masked": mask_text(username),
        }

    def user_profile(self):
        with self._lock:
            return normalize_user_profile(self._data.get("user_profile") or {})

    def set_user_profile(self, display_name=None, avatar_url=None):
        with self._lock:
            profile = normalize_user_profile(self._data.get("user_profile") or {})
            if display_name is not None:
                profile["display_name"] = str(display_name or "").strip()[:40]
            if avatar_url is not None:
                profile["avatar_url"] = normalize_avatar_url(avatar_url)
                profile["avatar_kind"] = avatar_kind(profile["avatar_url"])
            profile["updated_at"] = time.time()
            self._data["user_profile"] = profile
            self._save_locked()
            return dict(profile)

    def verify_web_auth(self, username, password):
        with self._lock:
            if not self._data.get("web_auth_enabled"):
                return False
            expected_user = str(self._data.get("web_auth_username") or "").strip()
            salt = str(self._data.get("web_auth_salt") or "").strip()
            expected_hash = str(self._data.get("web_auth_hash") or "").strip()
        if not expected_user or not salt or not expected_hash:
            return False
        if str(username or "").strip() != expected_user:
            return False
        try:
            actual_hash = web_password_hash(password, salt)
        except Exception:
            return False
        return secrets.compare_digest(actual_hash, expected_hash)

    def set_allow_remote(self, value, api_base_url=None):
        with self._lock:
            self._data["allow_remote"] = bool(value)
            if api_base_url is not None:
                self._data["api_base_url"] = str(api_base_url or "").strip()
            self._save_settings_locked({
                "allow_remote": "1" if self._data["allow_remote"] else "0",
                "api_base_url": self._data["api_base_url"],
            })
        return self.server_access_info()

    def set_server_access_settings(
        self,
        allow_remote=None,
        api_base_url=None,
        web_port=None,
        allowed_domains=None,
        web_auth_enabled=None,
        web_auth_username=None,
        web_auth_password=None,
    ):
        auth_changed = False
        with self._lock:
            settings_values = {}
            json_dirty = False

            next_allow_remote = bool(self._data.get("allow_remote"))
            next_api_base_url = str(self._data.get("api_base_url") or "").strip()
            next_web_port = normalize_web_port(self._data.get("web_port"), default=8765)
            next_domains_text = ",".join(self.allowed_domains())

            next_auth_enabled = bool(self._data.get("web_auth_enabled"))
            next_auth_username = str(self._data.get("web_auth_username") or "").strip()
            next_auth_salt = str(self._data.get("web_auth_salt") or "").strip()
            next_auth_hash = str(self._data.get("web_auth_hash") or "").strip()

            if allow_remote is not None:
                next_allow_remote = bool(allow_remote)
            if api_base_url is not None:
                next_api_base_url = str(api_base_url or "").strip()
            if web_port is not None:
                next_web_port = normalize_web_port(web_port, default=8765, strict=True)
            if allowed_domains is not None:
                next_domains_text = ",".join(normalize_domain_patterns(allowed_domains))

            if web_auth_enabled is not None:
                next_auth_enabled = bool(web_auth_enabled)
            if web_auth_username is not None:
                next_auth_username = str(web_auth_username or "").strip()
            if next_auth_enabled and not next_auth_username:
                next_auth_username = "admin"
            if web_auth_password is not None and str(web_auth_password) != "":
                next_auth_salt = secrets.token_hex(16)
                next_auth_hash = web_password_hash(web_auth_password, next_auth_salt)
            if next_auth_enabled and not next_auth_hash:
                raise ValueError("web auth password is required when web auth is enabled")

            if bool(self._data.get("allow_remote")) != next_allow_remote:
                self._data["allow_remote"] = next_allow_remote
                settings_values["allow_remote"] = "1" if next_allow_remote else "0"
            if str(self._data.get("api_base_url") or "").strip() != next_api_base_url:
                self._data["api_base_url"] = next_api_base_url
                settings_values["api_base_url"] = next_api_base_url
            if normalize_web_port(self._data.get("web_port"), default=8765) != next_web_port:
                self._data["web_port"] = next_web_port
                json_dirty = True
            if str(self._data.get("web_allowed_domains") or "") != next_domains_text:
                self._data["web_allowed_domains"] = next_domains_text
                settings_values["web_allowed_domains"] = next_domains_text

            current_auth = (
                bool(self._data.get("web_auth_enabled")),
                str(self._data.get("web_auth_username") or "").strip(),
                str(self._data.get("web_auth_salt") or "").strip(),
                str(self._data.get("web_auth_hash") or "").strip(),
            )
            next_auth = (next_auth_enabled, next_auth_username, next_auth_salt, next_auth_hash)
            if current_auth != next_auth:
                auth_changed = True
                self._data["web_auth_enabled"] = next_auth_enabled
                self._data["web_auth_username"] = next_auth_username
                self._data["web_auth_salt"] = next_auth_salt
                self._data["web_auth_hash"] = next_auth_hash
                settings_values.update({
                    "web_auth_enabled": "1" if next_auth_enabled else "0",
                    "web_auth_username": next_auth_username,
                    "web_auth_salt": next_auth_salt,
                    "web_auth_hash": next_auth_hash,
                })

            if settings_values:
                self._save_settings_locked(settings_values)
            if json_dirty:
                self._save_locked()

        if auth_changed:
            clear_web_auth_tokens()
        return self.server_access_info()

    def qmt_userdata_log_cleanup_enabled(self):
        with self._lock:
            return bool(self._data.get("cleanup_qmt_userdata_logs"))

    def log_cleanup_info(self):
        return {
            "retention_days": LOG_RETENTION_DAYS,
            "local_cfquant_logs_enabled": True,
            "qmt_userdata_log_cleanup_enabled": self.qmt_userdata_log_cleanup_enabled(),
        }

    def set_log_cleanup_settings(self, cleanup_qmt_userdata_logs=None):
        with self._lock:
            if cleanup_qmt_userdata_logs is not None:
                self._data["cleanup_qmt_userdata_logs"] = bool(cleanup_qmt_userdata_logs)
            self._save_settings_locked({
                "cleanup_qmt_userdata_logs": "1" if self._data.get("cleanup_qmt_userdata_logs") else "0",
            })
        return self.log_cleanup_info()

    def qmt_log_language(self):
        with self._lock:
            return normalize_log_language(self._data.get("qmt_log_language") or "zh")

    def qmt_log_enabled(self):
        with self._lock:
            return normalize_log_enabled(self._data.get("qmt_log_enabled"))

    def qmt_log_language_info(self):
        language = self.qmt_log_language()
        enabled = self.qmt_log_enabled()
        return {
            "language": language,
            "label": "中文" if language == "zh" else "English",
            "enabled": enabled,
            "enabled_label": "开启" if enabled else "关闭",
        }

    def transport_mode(self):
        with self._lock:
            return normalize_transport_mode(self._data.get("transport_mode") or "ctypes")

    def transport_info(self):
        mode = self.transport_mode()
        return {
            "mode": mode,
            "label": transport_mode_label(mode),
            "detail_label": transport_mode_detail_label(mode),
            "summary": transport_mode_summary(mode),
            "pipe_name": normalize_pipe_name(os.environ.get("CFQUANT_PIPE_NAME") or DEFAULT_PIPE_NAME),
        }

    def set_transport_mode(self, mode):
        mode = normalize_transport_mode(mode)
        with self._lock:
            self._data["transport_mode"] = mode
            self._save_settings_locked({"transport_mode": mode})
        return self.transport_info()

    def set_qmt_log_language(self, language, enabled=None):
        language = normalize_log_language(language)
        with self._lock:
            self._data["qmt_log_language"] = language
            values = {"qmt_log_language": language}
            if enabled is not None:
                self._data["qmt_log_enabled"] = normalize_log_enabled(enabled)
                values["qmt_log_enabled"] = "1" if self._data.get("qmt_log_enabled") else "0"
            self._save_settings_locked(values)
        return self.qmt_log_language_info()

    def server_access_info(self, bound_host=None, bound_port=None, include_auth_details=True):
        allow_remote = self.allow_remote()
        with self._lock:
            api_base_url = str(self._data.get("api_base_url") or "").strip()
        configured_host = "0.0.0.0" if allow_remote else "127.0.0.1"
        configured_port = self.web_port()
        host = bound_host if bound_host is not None else configured_host
        active_port = normalize_web_port(bound_port, default=configured_port) if bound_port else configured_port
        lan_ip = get_lan_ip()
        port_part = ":%s" % active_port if active_port else ""
        local_url = "http://127.0.0.1%s" % port_part if bound_port else ""
        lan_url = "http://%s%s" % (lan_ip, port_part) if bound_port and lan_ip != "127.0.0.1" else ""
        configured_local_url = "http://127.0.0.1:%s/" % configured_port
        configured_lan_url = "http://%s:%s/" % (lan_ip, configured_port) if lan_ip != "127.0.0.1" else ""
        host_needs_restart = bound_host is not None and host != configured_host
        port_needs_restart = bound_port is not None and int(bound_port) != int(configured_port)
        domains = self.allowed_domains()
        web_auth = self.web_auth_info(include_username=include_auth_details)
        return {
            "allow_remote": allow_remote,
            "configured_host": configured_host,
            "configured_port": configured_port,
            "web_port": configured_port,
            "bound_host": host,
            "bound_port": bound_port,
            "local_ip": lan_ip,
            "local_url": local_url,
            "lan_url": lan_url,
            "configured_local_url": configured_local_url,
            "configured_lan_url": configured_lan_url,
            "next_url": configured_local_url,
            "api_base_url": api_base_url,
            "allowed_domains": domains,
            "allowed_domains_text": ",".join(domains),
            "web_auth": web_auth,
            "web_auth_enabled": web_auth["enabled"],
            "web_auth_username": web_auth["username"],
            "web_auth_username_masked": web_auth["username_masked"],
            "requires_restart": host_needs_restart or port_needs_restart,
            "restart_required": host_needs_restart or port_needs_restart,
        }

    def save_bridge(self, bridge):
        bridge_id = normalize_bridge_id((bridge or {}).get("id") or (bridge or {}).get("bridge_id"))
        if not bridge_id:
            raise ValueError("bridge id is required")
        name = str((bridge or {}).get("name") or bridge_id).strip() or bridge_id
        channels = (bridge or {}).get("channels") or {}
        python_dir = normalize_optional_path((bridge or {}).get("python_dir") or (bridge or {}).get("project_dir"))
        row = {
            "id": bridge_id,
            "name": name,
            "python_dir": python_dir,
            "channels": {
                "normal": str(channels.get("normal") or ("cfquant.%s.normal.request" % bridge_id if bridge_id != "default" else CHANNELS["normal"])).strip(),
                "trade": str(channels.get("trade") or ("cfquant.%s.trade.request" % bridge_id if bridge_id != "default" else CHANNELS["trade"])).strip(),
                "callback": str(channels.get("callback") or ("cfquant.%s.callback.event" % bridge_id if bridge_id != "default" else CHANNELS["callback"])).strip(),
            },
        }
        with self._lock:
            self._data.setdefault("bridges", {})[bridge_id] = row
            self._save_locked()
        return row

    def _bridge_row(self, bridge_id, name, python_dir, channels):
        channels = channels or {}
        return {
            "id": bridge_id,
            "name": name,
            "python_dir": normalize_optional_path(python_dir),
            "channels": {
                "normal": str(channels.get("normal") or (
                    "cfquant.%s.normal.request" % bridge_id
                    if bridge_id != "default" else CHANNELS["normal"]
                )).strip(),
                "trade": str(channels.get("trade") or (
                    "cfquant.%s.trade.request" % bridge_id
                    if bridge_id != "default" else CHANNELS["trade"]
                )).strip(),
                "callback": str(channels.get("callback") or (
                    "cfquant.%s.callback.event" % bridge_id
                    if bridge_id != "default" else CHANNELS["callback"]
                )).strip(),
            },
        }

    def delete_bridge(self, bridge_id):
        bridge_id = normalize_bridge_id(bridge_id)
        if bridge_id in ENV_BRIDGES:
            raise ValueError("environment bridge cannot be deleted from web: %s" % bridge_id)
        with self._lock:
            self._data.setdefault("bridges", {}).pop(bridge_id, None)
            pairs = self._data.setdefault("account_pairs", {})
            for key, pair in list(pairs.items()):
                if normalize_bridge_id(pair.get("bridge_id")) == bridge_id:
                    pairs.pop(key, None)
            self._save_locked()

    def save_pair(self, account_id, bridge_id, account_type="STOCK", account_key=None, display_name=None):
        account_id = str(account_id or "").strip()
        account_type = normalize_account_type(account_type)
        bridge_id = normalize_bridge_id(bridge_id)
        display_name = str(display_name or "").strip()
        if not account_id:
            raise ValueError("account_id is required")
        if bridge_id not in self.bridges():
            raise ValueError("unknown bridge_id: %s" % bridge_id)
        account_key = str(account_key or "").strip() or account_key_for(account_id, account_type, bridge_id)
        row = {
            "account_key": account_key,
            "account_id": account_id,
            "account_type": account_type,
            "bridge_id": bridge_id,
            "display_name": display_name,
            "updated_at": time.time(),
        }
        with self._lock:
            self._data.setdefault("account_pairs", {})[account_key] = row
            self._save_locked()
        return row

    def delete_pair(self, account_id=None, account_type=None, bridge_id=None, account_key=None):
        account_id = str(account_id or "").strip()
        with self._lock:
            key = self._coerce_account_key_locked(
                account_key=account_key,
                account_id=account_id,
                account_type=account_type,
                bridge_id=bridge_id,
            ) or str(account_key or "").strip() or account_id
            self._data.setdefault("account_pairs", {}).pop(key, None)
            self._save_locked()

    def _ensure_settings_db_locked(self):
        db_dir = os.path.dirname(os.path.abspath(self.settings_db_path))
        if db_dir and not os.path.isdir(db_dir):
            os.makedirs(db_dir)
        with sqlite3.connect(self.settings_db_path) as conn:
            conn.execute(
                "create table if not exists settings ("
                "key text primary key,"
                "value text not null,"
                "updated_at real not null)"
            )
            _ensure_web_auth_session_store_locked(conn)

    def _settings_keys_locked(self):
        self._ensure_settings_db_locked()
        with sqlite3.connect(self.settings_db_path) as conn:
            rows = conn.execute("select key from settings").fetchall()
        return set(row[0] for row in rows)

    def _migrate_legacy_settings_locked(self, legacy_settings):
        if not legacy_settings:
            return
        existing = self._settings_keys_locked()
        values = {}
        api_key = str(legacy_settings.get("api_key") or "").strip()
        api_base_url = str(legacy_settings.get("api_base_url") or "").strip()
        if "api_key" not in existing and api_key:
            values["api_key"] = api_key
        if "allow_remote" not in existing:
            values["allow_remote"] = "1" if legacy_settings.get("allow_remote") == "1" else "0"
        if "api_base_url" not in existing and api_base_url:
            values["api_base_url"] = api_base_url
        if values:
            self._save_settings_locked(values)

    def _load_settings_locked(self):
        self._ensure_settings_db_locked()
        with sqlite3.connect(self.settings_db_path) as conn:
            rows = conn.execute("select key, value from settings").fetchall()
        settings = dict((str(key), str(value)) for key, value in rows)
        if "api_key" in settings:
            self._data["api_key"] = settings.get("api_key") or ""
        if "allow_remote" in settings:
            self._data["allow_remote"] = self._settings_bool(settings.get("allow_remote"))
        if "api_base_url" in settings:
            self._data["api_base_url"] = settings.get("api_base_url") or ""
        if "web_allowed_domains" in settings:
            self._data["web_allowed_domains"] = settings.get("web_allowed_domains") or ""
        if "web_auth_enabled" in settings:
            self._data["web_auth_enabled"] = self._settings_bool(settings.get("web_auth_enabled"))
        if "web_auth_username" in settings:
            self._data["web_auth_username"] = settings.get("web_auth_username") or ""
        if "web_auth_salt" in settings:
            self._data["web_auth_salt"] = settings.get("web_auth_salt") or ""
        if "web_auth_hash" in settings:
            self._data["web_auth_hash"] = settings.get("web_auth_hash") or ""
        if "cleanup_qmt_userdata_logs" in settings:
            self._data["cleanup_qmt_userdata_logs"] = self._settings_bool(settings.get("cleanup_qmt_userdata_logs"))
        if "qmt_log_language" in settings:
            self._data["qmt_log_language"] = normalize_log_language(settings.get("qmt_log_language"))
        if "qmt_log_enabled" in settings:
            self._data["qmt_log_enabled"] = normalize_log_enabled(settings.get("qmt_log_enabled"))
        if "transport_mode" in settings:
            self._data["transport_mode"] = normalize_transport_mode(settings.get("transport_mode"))

    def _save_settings_locked(self, values):
        self._ensure_settings_db_locked()
        rows = [(str(key), str(value or ""), time.time()) for key, value in (values or {}).items()]
        if not rows:
            return
        with sqlite3.connect(self.settings_db_path) as conn:
            conn.executemany(
                "insert or replace into settings (key, value, updated_at) values (?, ?, ?)",
                rows,
            )

    def _settings_bool(self, value):
        return str(value or "").strip().lower() in ("1", "true", "yes", "on")

    def _save_locked(self):
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump({
                "bridges": self._data.get("bridges") or {},
                "account_pairs": self._data.get("account_pairs") or {},
                "account_configs": self._data.get("account_configs") or {},
                "default_account_id": self._data.get("default_account_id") or DEFAULT_ACCOUNT_ID,
                "default_account_type": self._data.get("default_account_type") or "STOCK",
                "default_account_key": self._data.get("default_account_key") or "",
                "initialized": bool(self._data.get("initialized")),
                "data_provider_account_id": self._data.get("data_provider_account_id") or "",
                "data_provider_account_type": self._data.get("data_provider_account_type") or "STOCK",
                "data_provider_account_key": self._data.get("data_provider_account_key") or "",
                "web_port": normalize_web_port(self._data.get("web_port"), default=8765),
            }, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temp_path, self.path)

    def _normalize_bridges(self, value):
        result = {}
        if isinstance(value, list):
            items = value
        elif isinstance(value, dict):
            items = value.values()
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            bridge_id = normalize_bridge_id(item.get("id") or item.get("bridge_id"))
            channels = item.get("channels") or {}
            result[bridge_id] = {
                "id": bridge_id,
                "name": str(item.get("name") or bridge_id),
                "python_dir": normalize_optional_path(item.get("python_dir") or item.get("project_dir")),
                "channels": {
                    "normal": str(channels.get("normal") or ("cfquant.%s.normal.request" % bridge_id if bridge_id != "default" else CHANNELS["normal"])),
                    "trade": str(channels.get("trade") or ("cfquant.%s.trade.request" % bridge_id if bridge_id != "default" else CHANNELS["trade"])),
                    "callback": str(channels.get("callback") or ("cfquant.%s.callback.event" % bridge_id if bridge_id != "default" else CHANNELS["callback"])),
                },
            }
        return result

    def _normalize_pairs(self, value):
        result = {}
        if isinstance(value, list):
            items = value
        elif isinstance(value, dict):
            items = []
            for key, item in value.items():
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("account_key", key)
                    items.append(row)
                else:
                    items.append({"account_key": key, "account_id": key, "bridge_id": item})
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            account_id = str(item.get("account_id") or "").strip()
            account_type = normalize_account_type(item.get("account_type") or "STOCK")
            bridge_id = normalize_bridge_id(item.get("bridge_id"))
            account_key = str(item.get("account_key") or "").strip() or account_key_for(account_id, account_type, bridge_id)
            if account_id and bridge_id:
                result[account_key] = {
                    "account_key": account_key,
                    "account_id": account_id,
                    "account_type": account_type,
                    "bridge_id": bridge_id,
                    "display_name": str(item.get("display_name") or item.get("account_name") or ""),
                    "qmt_dir": normalize_optional_path(item.get("qmt_dir") or item.get("python_dir")),
                    "qmt_trade_dir": normalize_optional_path(
                        item.get("qmt_trade_dir")
                        or item.get("trade_qmt_dir")
                        or item.get("advanced_qmt_dir")
                        or item.get("qmt_trade_core_dir")
                    ),
                    "market_routing_enabled": parse_config_bool(item.get("market_routing_enabled"), False),
                    "market_bridges": normalize_market_bridge_config(
                        item.get("market_bridges") or {},
                        account_id=account_id,
                        account_type=account_type,
                        parent_bridge_id=bridge_id,
                        enabled=parse_config_bool(item.get("market_routing_enabled"), False),
                    ),
                    "updated_at": float(item.get("updated_at") or 0),
                }
        return result

    def _normalize_account_configs(self, value):
        result = {}
        if isinstance(value, list):
            items = value
        elif isinstance(value, dict):
            items = []
            for key, item in value.items():
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("account_key", key)
                    items.append(row)
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            account_id = str(item.get("account_id") or "").strip()
            if not account_id:
                continue
            account_type = normalize_account_type(item.get("account_type") or "STOCK")
            bridge_id = normalize_bridge_id(item.get("bridge_id") or DEFAULT_BRIDGE_ID)
            qmt_dir = normalize_optional_path(item.get("qmt_dir") or item.get("python_dir"))
            qmt_trade_dir = normalize_optional_path(
                item.get("qmt_trade_dir")
                or item.get("trade_qmt_dir")
                or item.get("advanced_qmt_dir")
                or item.get("qmt_trade_core_dir")
            )
            account_key = str(item.get("account_key") or "").strip() or account_key_for(account_id, account_type, bridge_id)
            result[account_key] = {
                "account_key": account_key,
                "account_id": account_id,
                "account_type": account_type,
                "account_type_label": account_type_label(account_type),
                "display_name": str(item.get("display_name") or item.get("account_name") or ""),
                "bridge_id": bridge_id,
                "qmt_dir": qmt_dir,
                "qmt_trade_dir": qmt_trade_dir,
                "mode": normalize_transport_mode(item.get("mode") or "ctypes"),
                "data_provider": bool(item.get("data_provider")),
                "enabled": item.get("enabled", True) is not False,
                "market_routing_enabled": parse_config_bool(item.get("market_routing_enabled"), False),
                "market_bridges": normalize_market_bridge_config(
                    item.get("market_bridges") or {},
                    account_id=account_id,
                    account_type=account_type,
                    parent_bridge_id=bridge_id,
                    enabled=parse_config_bool(item.get("market_routing_enabled"), False),
                ),
                "updated_at": float(item.get("updated_at") or 0),
            }
        return result


WEB_CONFIG = None


def current_bridges():
    if WEB_CONFIG is not None:
        return WEB_CONFIG.bridges()
    return dict(ENV_BRIDGES)


def configured_default_account_id():
    if WEB_CONFIG is not None:
        info = WEB_CONFIG.setup_info()
        return str(info.get("default_account_id") or DEFAULT_ACCOUNT_ID).strip() or DEFAULT_ACCOUNT_ID
    return DEFAULT_ACCOUNT_ID


def configured_default_account_type():
    if WEB_CONFIG is not None:
        info = WEB_CONFIG.setup_info()
        return normalize_account_type(info.get("default_account_type") or "STOCK")
    return "STOCK"


def configured_default_account_key():
    if WEB_CONFIG is not None:
        info = WEB_CONFIG.setup_info()
        return str(info.get("default_account_key") or "").strip()
    return ""


def bridge_config(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    bridges = current_bridges()
    if bridge_id not in bridges:
        raise ValueError("unknown bridge_id: %s" % bridge_id)
    return bridges[bridge_id]


def bridge_channels(bridge_id=None):
    return bridge_config(bridge_id)["channels"]


def normalize_transport_mode(value):
    value = str(value or "ctypes").strip().lower()
    if value in ("pipe", "ctypes", "named_pipe", "named-pipe", "universal", "universal_ctypes"):
        return "ctypes"
    if value in ("lite", "extreme", "extreme_lite", "lite_extreme", "lite_extreme_pipe", "extreme_pipe", "cfquant_lite", "ultimate"):
        return "lite"
    if value in ("lttx", "socket", "normal", "default"):
        return "lttx"
    raise ValueError("unknown transport mode: %s" % value)


def is_ctypes_transport_mode(mode):
    return normalize_transport_mode(mode) in ("ctypes", "lite")


def transport_client_mode(mode):
    return "ctypes" if is_ctypes_transport_mode(mode) else "lttx"


def transport_mode_label(mode):
    mode = normalize_transport_mode(mode)
    if mode == "lite":
        return "极致模式"
    return "通用模式" if mode == "ctypes" else "高级模式"


def transport_mode_detail_label(mode):
    mode = normalize_transport_mode(mode)
    if mode == "lite":
        return "纯 ctypes 自包含版"
    return "ctypes 通用版" if mode == "ctypes" else "LTtx 普通/极速双桥"


def transport_mode_summary(mode):
    mode = normalize_transport_mode(mode)
    return {
        "mode": mode,
        "label": transport_mode_label(mode),
        "detail_label": transport_mode_detail_label(mode),
        "request_scope": "纯 ctypes 单文件双通道" if mode == "lite" else ("单文件双通道" if mode == "ctypes" else "普通桥 + 交易桥"),
    }


def _advanced_mode_readiness(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    cfg = get_cfquant_config()
    probe_client = LTtxRpcClient(
        host=cfg.get("host") or LTTX_HOST,
        port=cfg.get("port") or LTTX_PORT,
        token=cfg.get("token") or "LTtx",
        client_id=new_id("cfquant_advanced_probe"),
    )
    try:
        try:
            probe_client.start()
            snapshot = probe_bridge_status(bridge_id=bridge_id, client=probe_client)
        except Exception as error:
            channels = bridge_channels(bridge_id)
            snapshot = {
                "normal": {
                    "online": False,
                    "channel": channels["normal"],
                    "error": str(error),
                },
                "trade": {
                    "online": False,
                    "channel": channels["trade"],
                    "error": str(error),
                },
            }
    finally:
        probe_client.close()
    normal = snapshot.get("normal") or {}
    trade = snapshot.get("trade") or {}
    missing = []
    if not normal.get("online"):
        missing.append("普通通道")
    if not trade.get("online"):
        missing.append("交易通道")
    return {
        "bridge_id": bridge_id,
        "bridge_name": bridge_config(bridge_id)["name"],
        "ready": not missing,
        "missing": missing,
        "status": snapshot,
    }


def cached_advanced_mode_readiness(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    snapshot = STATUS_MONITOR.latest(bridge_id=bridge_id, mode="lttx")
    normal = snapshot.get("normal") or {}
    trade = snapshot.get("trade") or {}
    missing = []
    if not normal.get("online"):
        missing.append("普通通道")
    if not trade.get("online"):
        missing.append("交易通道")
    return {
        "bridge_id": bridge_id,
        "bridge_name": bridge_config(bridge_id)["name"],
        "ready": not missing,
        "missing": missing,
        "status": snapshot,
        "cached": True,
    }


def resolve_bridge_id(account_id=None, bridge_id=None, account_type=None, account_key=None):
    account_id = str(account_id or "").strip()
    account_key = str(account_key or "").strip()
    raw_bridge_id = str(bridge_id or "").strip()
    requested_bridge_id = normalize_bridge_id(raw_bridge_id) if raw_bridge_id else ""
    if account_id or account_key:
        runtime = WEB_CONFIG.account_config(
            account_id=account_id,
            account_type=account_type,
            bridge_id=bridge_id,
            account_key=account_key,
        ) if WEB_CONFIG is not None else None
        if runtime and runtime.get("bridge_id"):
            runtime_bridge_id = normalize_bridge_id(runtime.get("bridge_id"))
            if (
                requested_bridge_id
                and requested_bridge_id != runtime_bridge_id
                and account_config_has_market_bridge(
                    runtime,
                    requested_bridge_id,
                    account_id=account_id,
                    account_type=account_type or runtime.get("account_type") or "STOCK",
                    parent_bridge_id=runtime_bridge_id,
                )
            ):
                return requested_bridge_id
            return runtime_bridge_id
        if requested_bridge_id and WEB_CONFIG is not None:
            for row_key, row in WEB_CONFIG.account_configs().items():
                if not isinstance(row, dict):
                    continue
                if account_key and account_key not in (str(row_key or "").strip(), str(row.get("account_key") or "").strip()):
                    continue
                if account_id and str(row.get("account_id") or "").strip() != account_id:
                    continue
                if account_type not in (None, "") and normalize_account_type(row.get("account_type") or "STOCK") != normalize_account_type(account_type):
                    continue
                if account_config_has_market_bridge(
                    row,
                    requested_bridge_id,
                    account_id=account_id,
                    account_type=account_type or row.get("account_type") or "STOCK",
                    parent_bridge_id=row.get("bridge_id") or DEFAULT_BRIDGE_ID,
                ):
                    return requested_bridge_id
        if WEB_CONFIG is not None:
            pair_key = account_key or account_key_for(account_id, account_type or "STOCK", bridge_id or DEFAULT_BRIDGE_ID)
            pair = WEB_CONFIG.account_pairs().get(pair_key)
            if not pair and account_id:
                for row in WEB_CONFIG.account_pairs().values():
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("account_id") or "").strip() != account_id:
                        continue
                    if account_type not in (None, "") and normalize_account_type(row.get("account_type") or "STOCK") != normalize_account_type(account_type):
                        continue
                    pair = row
                    break
            if pair and pair.get("bridge_id"):
                return normalize_bridge_id(pair.get("bridge_id"))
    if requested_bridge_id:
        return requested_bridge_id
    return DEFAULT_BRIDGE_ID


def resolve_account_mode(account_id=None, requested_mode=None, account_type=None, bridge_id=None, account_key=None):
    requested_mode = str(requested_mode or "").strip()
    if requested_mode:
        return normalize_transport_mode(requested_mode)
    account_id = str(account_id or "").strip()
    if (account_id or account_key) and WEB_CONFIG is not None:
        runtime = WEB_CONFIG.account_config(
            account_id=account_id,
            account_type=account_type,
            bridge_id=bridge_id,
            account_key=account_key,
        )
        if runtime and runtime.get("mode"):
            return normalize_transport_mode(runtime.get("mode"))
    return WEB_CONFIG.transport_mode() if WEB_CONFIG is not None else "ctypes"


def account_market_route_config(account_id=None, account_type=None, bridge_id=None, account_key=None):
    if WEB_CONFIG is None:
        return {}, {}
    config = WEB_CONFIG.account_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=bridge_id,
        account_key=account_key,
    ) or {}
    enabled = parse_config_bool(config.get("market_routing_enabled"), False)
    routes = normalize_market_bridge_config(
        config.get("market_bridges") or {},
        account_id=str(config.get("account_id") or account_id or "").strip(),
        account_type=normalize_account_type(config.get("account_type") or account_type or "STOCK"),
        parent_bridge_id=config.get("bridge_id") or bridge_id,
        enabled=enabled,
    )
    if not enabled:
        routes = {}
    return config, routes


def account_market_route_entries(account_id=None, account_type=None, bridge_id=None, account_key=None):
    requested_bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    config, routes = account_market_route_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=requested_bridge_id,
        account_key=account_key,
    )
    if not parse_config_bool((config or {}).get("market_routing_enabled"), False):
        return config or {}, []
    base_bridge_id = normalize_bridge_id((config or {}).get("bridge_id") or requested_bridge_id)
    if requested_bridge_id and requested_bridge_id != base_bridge_id:
        return config or {}, []
    entries = []
    for market in MARKET_ROUTE_MARKETS:
        route = (routes or {}).get(market) or {}
        if route.get("enabled", True) is False:
            continue
        child_bridge_id = normalize_bridge_id(route.get("bridge_id") or "")
        if child_bridge_id:
            entries.append({
                "market": market,
                "bridge_id": child_bridge_id,
                "route": route,
            })
    return config or {}, entries


def account_related_bridge_ids(account_id=None, account_type=None, bridge_id=None, account_key=None, include_base=True):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    config, entries = account_market_route_entries(
        account_id=account_id,
        account_type=account_type,
        bridge_id=bridge_id,
        account_key=account_key,
    )
    result = []

    def add(value):
        value = normalize_bridge_id(value or "")
        if value and value not in result:
            result.append(value)

    if include_base:
        add((config or {}).get("bridge_id") or bridge_id)
    if entries:
        for entry in entries:
            add(entry.get("bridge_id"))
    elif not include_base:
        add(bridge_id)
    return result


def action_supports_market_routing(action, params=None):
    action = str(action or "").strip()
    if action in MARKET_ROUTE_TRADE_ACTIONS:
        return True
    return False


def resolve_market_route_for_request(
    account_id=None,
    account_type=None,
    account_key=None,
    bridge_id=None,
    action=None,
    params=None,
    route_market=None,
):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    meta = {
        "enabled": False,
        "matched": False,
        "market": "",
        "base_bridge_id": bridge_id,
        "bridge_id": bridge_id,
        "route": None,
    }
    if not action_supports_market_routing(action, params):
        return bridge_id, meta
    config, routes = account_market_route_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=bridge_id,
        account_key=account_key,
    )
    meta["enabled"] = parse_config_bool(config.get("market_routing_enabled"), False)
    if not routes:
        return bridge_id, meta
    market = normalize_market_code(route_market) or request_params_market(params)
    meta["market"] = market
    if market not in MARKET_ROUTE_MARKETS:
        return bridge_id, meta
    route = routes.get(market) or {}
    if route.get("enabled", True) is False:
        return bridge_id, meta
    target_bridge_id = normalize_bridge_id(route.get("bridge_id") or "")
    if not target_bridge_id:
        return bridge_id, meta
    meta.update({
        "matched": True,
        "bridge_id": target_bridge_id,
        "route": route,
    })
    return target_bridge_id, meta


def enabled_account_configs():
    configs = WEB_CONFIG.account_configs() if WEB_CONFIG is not None else {}
    result = {}
    for account_id, config in configs.items():
        if not isinstance(config, dict):
            continue
        if config.get("enabled", True) is False:
            continue
        result[str(config.get("account_key") or account_id)] = config
    return result


def account_identity_is_ambiguous(bridge_id, account_id):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    account_id = str(account_id or "").strip()
    if not account_id:
        return False
    types = set()
    for config in enabled_account_configs().values():
        if normalize_bridge_id(config.get("bridge_id") or DEFAULT_BRIDGE_ID) != bridge_id:
            continue
        if str(config.get("account_id") or "").strip() != account_id:
            continue
        types.add(normalize_account_type(config.get("account_type") or "STOCK"))
    return len(types) > 1


def configured_runtime_modes():
    configs = enabled_account_configs()
    modes = set()
    for config in configs.values():
        modes.add(normalize_transport_mode(config.get("mode") or "ctypes"))
    if not modes:
        modes.add(WEB_CONFIG.transport_mode() if WEB_CONFIG is not None else "ctypes")
    return modes


def bridge_has_lttx_account(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    configs = enabled_account_configs()
    if not configs:
        return (WEB_CONFIG.transport_mode() if WEB_CONFIG is not None else "ctypes") == "lttx"
    for config in configs.values():
        if normalize_transport_mode(config.get("mode") or "ctypes") != "lttx":
            continue
        if normalize_bridge_id(config.get("bridge_id") or DEFAULT_BRIDGE_ID) == bridge_id:
            return True
    return False


def lttx_runtime_enabled():
    return "lttx" in configured_runtime_modes()


def default_runtime_client_mode():
    modes = configured_runtime_modes()
    if modes == {"lttx"}:
        return "lttx"
    if modes == {"lite"}:
        return "lite"
    return "ctypes"


def forced_channel_for_action(action, mode=None):
    action = str(action or "")
    mode = normalize_transport_mode(mode or default_runtime_client_mode())
    if action in NORMAL_QMT_ACTIONS:
        return "normal"
    if mode == "lttx" and action.startswith("xttrader."):
        return "trade"
    return None


def account_cache_channel_for_sections(
    account_id,
    requested_channel=None,
    default="normal",
    mode=None,
    account_type=None,
    bridge_id=None,
    account_key=None,
    sections=None,
):
    sections = sections or []
    mode = normalize_transport_mode(mode or resolve_account_mode(account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key))
    for section in sections:
        action = ACCOUNT_ACTIONS.get(str(section or "").strip().lower())
        forced = forced_channel_for_action(action, mode=mode)
        if forced:
            return forced
    if is_ctypes_transport_mode(mode):
        return normalize_channel(default, "normal")
    return normalize_channel(requested_channel, default)


def route_channel_for_account(account_id, requested_channel=None, default="normal", mode=None, account_type=None, bridge_id=None, account_key=None, action=None):
    default = normalize_channel(default, "normal")
    mode = normalize_transport_mode(mode or resolve_account_mode(account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key))
    forced = forced_channel_for_action(action, mode=mode)
    if forced:
        return forced
    if is_ctypes_transport_mode(mode):
        return default
    return normalize_channel(requested_channel, default)


def callback_channels():
    channels = []
    for bridge in current_bridges().values():
        channel = bridge["channels"]["callback"]
        if channel not in channels:
            channels.append(channel)
    return channels


def is_pipe_client_closed_error(error):
    text = str(error or "").strip().lower()
    if not text:
        return False
    closed_markers = (
        "cfquant pipe client closed",
        "cfquant pipe connection closed",
        "cfquant pipe receive connection closed",
        "cfquant pipe receive connection missing",
        "cfquant pipe client not started",
    )
    return any(marker in text for marker in closed_markers)


class GlobalTxClient(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._clients = {}
        self._callbacks = {}
        self.client_id = os.environ.get("CFQUANT_WEB_CLIENT_ID") or new_id("cfquant_web")
        self._cooldown_until = {}
        self._last_error = {}

    def start(self, mode=None):
        self._get_client(mode).start()

    def request(
        self,
        bridge_id,
        channel_key,
        action,
        params=None,
        timeout=8.0,
        mark_offline_on_timeout=False,
        ignore_cooldown=False,
        mode=None,
    ):
        channels = bridge_channels(bridge_id)
        if channel_key not in ("normal", "trade"):
            raise ValueError("unknown channel: %s" % channel_key)
        mode = normalize_transport_mode(mode or resolve_account_mode())
        cooldown_key = (mode, normalize_bridge_id(bridge_id), channel_key)
        if not ignore_cooldown:
            self._check_cooldown(cooldown_key)
        last_error = None
        for attempt in range(2):
            client = self._get_client(mode)
            try:
                result = client.request(
                    action,
                    params or {},
                    timeout=timeout,
                    request_channel=channels[channel_key],
                )
                self._cooldown_until.pop(cooldown_key, None)
                self._last_error.pop(cooldown_key, None)
                return result
            except CfquantError as e:
                last_error = e
                if attempt == 0 and is_pipe_client_closed_error(e):
                    self._drop_client(mode, client)
                    continue
                raise
            except CfquantTimeout as e:
                if mark_offline_on_timeout:
                    self._mark_failed(cooldown_key, e)
                self._drop_client(mode, client)
                raise
            except Exception as e:
                last_error = e
                self._mark_failed(cooldown_key, e)
                self._drop_client(mode, client)
                raise
        if last_error is not None:
            raise last_error

    def close(self, mode=None):
        modes = [normalize_transport_mode(mode)] if mode else ["ctypes", "lite", "lttx"]
        with self._lock:
            clients = [self._clients.pop(item, None) for item in modes]
        for client in clients:
            if client is None:
                continue
            try:
                client.close()
            except Exception:
                pass

    def _drop_client(self, mode, client=None):
        mode = normalize_transport_mode(mode)
        with self._lock:
            current = self._clients.get(mode)
            if client is not None and current is not client:
                return False
            current = self._clients.pop(mode, None)
        if current is None:
            return False
        try:
            current.close()
        except Exception:
            pass
        return True

    def _check_cooldown(self, cooldown_key):
        now = time.time()
        cooldown_until = self._cooldown_until.get(cooldown_key, 0)
        if now < cooldown_until:
            last_error = self._last_error.get(cooldown_key, "previous connection failed")
            raise RuntimeError(
                "mode %s bridge %s channel %s is in reconnect cooldown %.1fs: %s"
                % (cooldown_key[0], cooldown_key[1], cooldown_key[2], cooldown_until - now, last_error)
            )

    def _get_client(self, mode=None):
        mode = normalize_transport_mode(mode or default_runtime_client_mode())
        client_mode = transport_client_mode(mode)
        with self._lock:
            client = self._clients.get(mode)
            if client is None:
                if client_mode == "ctypes":
                    cfg = get_cfquant_config()
                    from cfquant.pipe_client import PipeRpcClient

                    client = PipeRpcClient(
                        pipe_name=os.environ.get("CFQUANT_PIPE_NAME") or cfg.get("pipe_name") or DEFAULT_PIPE_NAME,
                        request_channel=CHANNELS["normal"],
                        timeout=cfg.get("timeout"),
                        client_id="%s_%s" % (self.client_id, mode),
                        connect_timeout_ms=cfg.get("pipe_connect_timeout_ms"),
                    )
                else:
                    client = LTtxRpcClient(
                        request_channel=CHANNELS["normal"],
                        client_id="%s_lttx" % self.client_id,
                    )
                self._clients[mode] = client
                for event, callbacks in self._callbacks.items():
                    for callback in callbacks:
                        client.add_callback(event, callback)
            return client

    def _mark_failed(self, cooldown_key, error=None):
        self._cooldown_until[cooldown_key] = time.time() + RECONNECT_COOLDOWN_SECONDS
        if error is not None:
            self._last_error[cooldown_key] = str(error)

    def add_callback(self, event, callback):
        if callback is None:
            return
        with self._lock:
            callbacks = self._callbacks.setdefault(event, [])
            if callback not in callbacks:
                callbacks.append(callback)
            clients = list(self._clients.values())
        for client in clients:
            client.add_callback(event, callback)

    def remove_callback(self, event, callback):
        with self._lock:
            callbacks = self._callbacks.get(event) or []
            if callback in callbacks:
                callbacks.remove(callback)
            clients = list(self._clients.values())
        for client in clients:
            client.remove_callback(event, callback)


def account_request(
    account_id,
    bridge_id,
    requested_channel,
    action,
    params=None,
    default_channel="normal",
    timeout=8.0,
    mark_offline_on_timeout=True,
    ignore_cooldown=False,
    account_type=None,
    account_key=None,
    route_market=None,
):
    account_id = str(account_id or "").strip()
    request_params = params if isinstance(params, dict) else {}
    request_account = request_params.get("account") if isinstance(request_params.get("account"), dict) else {}
    account_type = normalize_account_type(account_type or request_account.get("account_type") or request_params.get("account_type") or "STOCK")
    bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=bridge_id, account_type=account_type, account_key=account_key)
    base_bridge_id = bridge_id
    base_config = WEB_CONFIG.account_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=base_bridge_id,
        account_key=account_key,
    ) if WEB_CONFIG is not None else None
    resolved_account_key = str(
        account_key
        or (base_config or {}).get("account_key")
        or account_key_for(account_id, account_type, base_bridge_id)
    ).strip()
    bridge_id, market_route = resolve_market_route_for_request(
        account_id=account_id,
        account_type=account_type,
        account_key=resolved_account_key,
        bridge_id=base_bridge_id,
        action=action,
        params=request_params,
        route_market=route_market,
    )
    preferred_mode = resolve_account_mode(account_id, account_type=account_type, bridge_id=base_bridge_id, account_key=resolved_account_key)
    modes = [preferred_mode]
    if preferred_mode == "lttx":
        modes.append("ctypes")
    attempts = []
    last_error = None
    for mode in modes:
        channel = route_channel_for_account(
            account_id,
            requested_channel=requested_channel,
            default=default_channel,
            mode=mode,
            account_type=account_type,
            bridge_id=bridge_id,
            account_key=resolved_account_key,
            action=action,
        )
        started = time.perf_counter()
        try:
            result = CLIENTS.request(
                bridge_id,
                channel,
                action,
                params,
                timeout=timeout,
                mark_offline_on_timeout=mark_offline_on_timeout,
                ignore_cooldown=ignore_cooldown,
                mode=mode,
            )
            return {
                "result": result,
                "mode": mode,
                "channel": channel,
                "bridge_id": bridge_id,
                "base_bridge_id": base_bridge_id,
                "market_route": market_route,
                "account_id": account_id,
                "account_type": account_type,
                "account_key": resolved_account_key,
                "fallback": bool(attempts),
                "fallback_reason": str(last_error or ""),
                "attempts": attempts + [{
                    "mode": mode,
                    "channel": channel,
                    "ok": True,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }],
            }
        except Exception as error:
            last_error = error
            attempts.append({
                "mode": mode,
                "channel": channel,
                "ok": False,
                "error": str(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            })
    detail = "; ".join(
        "%s/%s: %s" % (row["mode"], row["channel"], row.get("error") or "")
        for row in attempts
    )
    raise RuntimeError(
        "%s failed for account %s: %s" % (action, account_id or "--", detail or "no route attempted")
    )


def account_batch_order_request(
    account_id,
    bridge_id,
    requested_channel,
    params=None,
    default_channel="trade",
    timeout=12.0,
    account_type=None,
    account_key=None,
):
    request_params = params if isinstance(params, dict) else {}
    orders = request_params.get("orders") if isinstance(request_params.get("orders"), list) else []
    groups = split_orders_by_market(orders)
    _, market_routes = account_market_route_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=bridge_id,
        account_key=account_key,
    )
    if len(groups) <= 1 or not market_routes:
        market = next(iter(groups.keys())) if groups else ""
        return account_request(
            account_id,
            bridge_id,
            requested_channel,
            "xttrader.order_stock_batch",
            request_params,
            default_channel=default_channel,
            timeout=timeout,
            mark_offline_on_timeout=True,
            account_type=account_type,
            account_key=account_key,
            route_market=market,
        )

    combined_results = [None] * len(orders)
    group_results = []
    attempts = []
    started = time.perf_counter()
    first_route = None
    for market in MARKET_ROUTE_MARKETS:
        entries = groups.get(market) or []
        if not entries:
            continue
        route = market_routes.get(market) or {}
        if not route.get("bridge_id"):
            raise RuntimeError("market route %s has no bridge_id" % market)
        group_orders = [row for _index, row in entries]
        group_params = dict(request_params)
        group_params["orders"] = group_orders
        route_result = account_request(
            account_id,
            bridge_id,
            requested_channel,
            "xttrader.order_stock_batch",
            group_params,
            default_channel=default_channel,
            timeout=timeout,
            mark_offline_on_timeout=True,
            account_type=account_type,
            account_key=account_key,
            route_market=market,
        )
        if first_route is None:
            first_route = route_result
        raw_result = route_result.get("result")
        raw_results = raw_result.get("results") if isinstance(raw_result, dict) else raw_result if isinstance(raw_result, list) else None
        if isinstance(raw_results, list):
            for local_index, item in enumerate(raw_results):
                if local_index >= len(entries):
                    break
                original_index = entries[local_index][0]
                if isinstance(item, dict):
                    combined = dict(item)
                    combined["index"] = original_index
                    combined.setdefault("market", market)
                    combined.setdefault("bridge_id", route_result.get("bridge_id"))
                    combined_results[original_index] = combined
                else:
                    combined_results[original_index] = {
                        "ok": True,
                        "index": original_index,
                        "market": market,
                        "bridge_id": route_result.get("bridge_id"),
                        "result": item,
                    }
        else:
            for original_index, _row in entries:
                combined_results[original_index] = {
                    "ok": True,
                    "index": original_index,
                    "market": market,
                    "bridge_id": route_result.get("bridge_id"),
                    "result": raw_result,
                }
        meta = dict(route_result)
        meta.pop("result", None)
        group_results.append({
            "market": market,
            "bridge_id": route_result.get("bridge_id"),
            "channel": route_result.get("channel"),
            "mode": route_result.get("mode"),
            "count": len(entries),
            "route": meta,
        })
        attempts.extend(route_result.get("attempts") or [])

    route = dict(first_route or {})
    route.update({
        "result": {
            "ok": all(item is not None and (not isinstance(item, dict) or item.get("ok", True)) for item in combined_results),
            "market_routing": True,
            "results": combined_results,
            "groups": group_results,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        },
        "market_route": {
            "enabled": True,
            "matched": True,
            "mixed": True,
            "groups": group_results,
        },
        "attempts": attempts,
    })
    return route


def data_provider_candidates():
    configs = WEB_CONFIG.account_configs() if WEB_CONFIG is not None else {}
    preferred = WEB_CONFIG.data_provider_account_key() if WEB_CONFIG is not None else ""
    default_account_key = configured_default_account_key()
    result = []
    if preferred and preferred in configs and configs[preferred].get("enabled", True):
        result.append(configs[preferred])
    if default_account_key in configs and configs[default_account_key].get("enabled", True):
        if default_account_key not in [row.get("account_key") for row in result]:
            result.append(configs[default_account_key])
    for account_key, config in configs.items():
        if not isinstance(config, dict):
            continue
        if config.get("enabled", True) and account_key not in [row.get("account_key") for row in result]:
            result.append(config)
    if not result:
        default_account_id = configured_default_account_id()
        if default_account_id:
            result.append({
                "account_key": account_key_for(default_account_id, configured_default_account_type(), DEFAULT_BRIDGE_ID),
                "account_id": default_account_id,
                "account_type": configured_default_account_type(),
                "bridge_id": DEFAULT_BRIDGE_ID,
            })
    return result


def data_account_route_candidates(account_id, account_type, account_key, bridge_id=None, params=None):
    account_id = str(account_id or "").strip()
    account_type = normalize_account_type(account_type or "STOCK")
    account_key = str(account_key or "").strip()
    target_bridge_id = resolve_bridge_id(
        account_id=account_id,
        bridge_id=bridge_id,
        account_type=account_type,
        account_key=account_key,
    )
    if not account_key and WEB_CONFIG is not None:
        direct_config = WEB_CONFIG.account_config(
            account_id=account_id,
            account_type=account_type,
            bridge_id=target_bridge_id,
        ) or {}
        account_key = str(direct_config.get("account_key") or "").strip()
        if not account_key:
            for row in WEB_CONFIG.account_configs().values():
                if not isinstance(row, dict):
                    continue
                if str(row.get("account_id") or "").strip() != account_id:
                    continue
                if normalize_account_type(row.get("account_type") or "STOCK") != account_type:
                    continue
                if account_config_has_market_bridge(
                    row,
                    target_bridge_id,
                    account_id=account_id,
                    account_type=account_type,
                    parent_bridge_id=row.get("bridge_id") or DEFAULT_BRIDGE_ID,
                ):
                    account_key = str(row.get("account_key") or "").strip()
                    break
    config, entries = account_market_route_entries(
        account_id=account_id,
        account_type=account_type,
        bridge_id=target_bridge_id,
        account_key=account_key,
    )
    account_key = account_key or (config or {}).get("account_key") or account_key_for(account_id, account_type, target_bridge_id)
    requested_markets = data_request_markets(params)
    candidates = []
    seen = set()

    def add(candidate_bridge_id, market="", market_routing=False):
        candidate_bridge_id = normalize_bridge_id(candidate_bridge_id or "")
        if not candidate_bridge_id or candidate_bridge_id in seen:
            return
        seen.add(candidate_bridge_id)
        candidates.append({
            "bridge_id": candidate_bridge_id,
            "market": normalize_market_code(market),
            "market_routing": bool(market_routing),
            "base_bridge_id": normalize_bridge_id((config or {}).get("bridge_id") or target_bridge_id),
            "account_key": account_key,
        })

    if entries:
        by_market = {entry.get("market"): entry for entry in entries}
        for market in requested_markets:
            entry = by_market.get(market)
            if entry:
                add(entry.get("bridge_id"), market=market, market_routing=True)
        for entry in entries:
            add(entry.get("bridge_id"), market=entry.get("market"), market_routing=True)
        add((config or {}).get("bridge_id") or target_bridge_id, market="", market_routing=False)
    else:
        add(target_bridge_id, market="", market_routing=False)
    return candidates


def routed_xtdata_account_request(
    account_id,
    bridge_id,
    requested_channel,
    action,
    params=None,
    default_channel="normal",
    timeout=12.0,
    mark_offline_on_timeout=True,
    ignore_cooldown=False,
    account_type=None,
    account_key=None,
):
    account_id = str(account_id or "").strip()
    account_type = normalize_account_type(account_type or "STOCK")
    account_key = str(account_key or "").strip()
    attempts = []
    last_error = None
    candidates = data_account_route_candidates(
        account_id,
        account_type,
        account_key,
        bridge_id=bridge_id,
        params=params,
    )
    for candidate in candidates:
        candidate_bridge_id = candidate.get("bridge_id")
        candidate_account_key = str(candidate.get("account_key") or account_key or "").strip()
        started = time.perf_counter()
        try:
            route = account_request(
                account_id,
                candidate_bridge_id,
                requested_channel,
                action,
                params,
                default_channel=default_channel,
                timeout=timeout,
                mark_offline_on_timeout=mark_offline_on_timeout,
                ignore_cooldown=ignore_cooldown,
                account_type=account_type,
                account_key=candidate_account_key,
                route_market=candidate.get("market") or None,
            )
            if attempts:
                route["fallback"] = True
                route["fallback_reason"] = str(last_error or "")
                route["attempts"] = attempts + list(route.get("attempts") or [])
            route["data_route"] = candidate
            route["data_route_market"] = candidate.get("market") or ""
            route["data_route_market_routing"] = bool(candidate.get("market_routing"))
            return route
        except Exception as error:
            last_error = error
            attempts.append({
                "bridge_id": candidate_bridge_id,
                "market": candidate.get("market") or "",
                "market_routing": bool(candidate.get("market_routing")),
                "ok": False,
                "error": str(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            })
    detail = "; ".join(
        "%s%s: %s" % (
            row.get("bridge_id") or "-",
            ("/%s" % row.get("market")) if row.get("market") else "",
            row.get("error") or "",
        )
        for row in attempts
    )
    raise RuntimeError(
        "%s failed for account %s: %s" % (action, account_id or "--", detail or str(last_error or "no route attempted"))
    )


def data_provider_request(
    action,
    params,
    requested_channel=None,
    default_channel="normal",
    timeout=12.0,
    bridge_id=None,
):
    attempts = []
    last_error = None
    for account in data_provider_candidates():
        account_id = str(account.get("account_id") or "").strip()
        account_type = normalize_account_type(account.get("account_type") or "STOCK")
        account_key = str(account.get("account_key") or "").strip()
        target_bridge_id = bridge_id or account.get("bridge_id")
        try:
            route = routed_xtdata_account_request(
                account_id,
                target_bridge_id,
                requested_channel,
                action,
                params,
                default_channel=default_channel,
                timeout=timeout,
                mark_offline_on_timeout=True,
                ignore_cooldown=True,
                account_type=account_type,
                account_key=account_key,
            )
            route["data_provider"] = account_id
            route["data_provider_account_type"] = account_type
            route["data_provider_account_key"] = route.get("account_key") or account_key
            route["provider_fallback"] = bool(attempts)
            route["provider_attempts"] = attempts + [{
                "account_id": account_id,
                "account_type": account_type,
                "account_key": route.get("account_key") or account_key,
                "bridge_id": route.get("bridge_id"),
                "market": route.get("data_route_market") or "",
                "market_routing": bool(route.get("data_route_market_routing")),
                "ok": True,
                "mode": route["mode"],
                "channel": route["channel"],
            }]
            return route
        except Exception as error:
            last_error = error
            attempts.append({
                "account_id": account_id,
                "account_type": account_type,
                "account_key": account_key,
                "bridge_id": normalize_bridge_id(target_bridge_id or DEFAULT_BRIDGE_ID),
                "ok": False,
                "error": str(error),
            })
    detail = "; ".join(
        "%s/%s/%s: %s" % (
            row["account_id"],
            row.get("account_type") or "STOCK",
            row.get("bridge_id") or "-",
            row.get("error") or "",
        )
        for row in attempts
    )
    raise RuntimeError(
        "%s failed for all data providers: %s" % (action, detail or str(last_error or "no provider"))
    )


def account_route_status(account_id, bridge_id=None, account_type=None, account_key=None):
    account_id = str(account_id or "").strip() or configured_default_account_id()
    account_type = normalize_account_type(account_type or configured_default_account_type())
    bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=bridge_id, account_type=account_type, account_key=account_key)
    config = WEB_CONFIG.account_config(account_id=account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key) if WEB_CONFIG else {}
    account_key = account_key or (config or {}).get("account_key") or account_key_for(account_id, account_type, bridge_id)
    preferred_mode = resolve_account_mode(account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key)
    ctypes_status = STATUS_MONITOR.latest(bridge_id=bridge_id, mode="ctypes")
    if preferred_mode == "lttx":
        advanced = cached_advanced_mode_readiness(bridge_id)
    else:
        advanced = {
            "bridge_id": bridge_id,
            "bridge_name": bridge_config(bridge_id)["name"],
            "ready": False,
            "missing": [],
            "skipped": True,
            "reason": "当前账号为通用/极致模式，请求路由不走 LTtx；LTtx 仅用于自动发现和兼容服务",
            "status": {},
        }
    advanced_status = advanced.get("status") or {}
    ctypes_ready = bool(
        (ctypes_status.get("normal") or {}).get("online")
        and (ctypes_status.get("trade") or {}).get("online")
    )
    advanced_ready = bool(advanced.get("ready"))
    effective_mode = preferred_mode
    fallback = False
    if preferred_mode == "lttx" and not advanced_ready and ctypes_ready:
        effective_mode = "ctypes"
        fallback = True
    selected = advanced_status if effective_mode == "lttx" else ctypes_status
    market_config, market_routes = account_market_route_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=bridge_id,
        account_key=account_key,
    )
    market_route_statuses = {}
    for market, route in market_routes.items():
        if route.get("enabled", True) is False:
            continue
        child_bridge_id = normalize_bridge_id(route.get("bridge_id") or "")
        if not child_bridge_id:
            continue
        try:
            child_ctypes_status = STATUS_MONITOR.latest(bridge_id=child_bridge_id, mode="ctypes")
        except Exception as e:
            market_route_statuses[market] = {
                "market": market,
                "bridge_id": child_bridge_id,
                "base_bridge_id": bridge_id,
                "qmt_dir": normalize_optional_path(route.get("qmt_dir")),
                "preferred_mode": preferred_mode,
                "effective_mode": preferred_mode,
                "fallback": False,
                "ready": False,
                "status": {},
                "error": str(e),
                "modes": {},
            }
            continue
        child_ctypes_ready = bool((child_ctypes_status.get("trade") or {}).get("online"))
        if preferred_mode == "lttx":
            try:
                child_advanced = cached_advanced_mode_readiness(child_bridge_id)
                child_advanced_status = child_advanced.get("status") or {}
                child_advanced_ready = bool((child_advanced_status.get("trade") or {}).get("online"))
            except Exception as e:
                child_advanced = {"ready": False, "status": {}, "skipped": True, "reason": str(e)}
                child_advanced_status = {}
                child_advanced_ready = False
        else:
            child_advanced = {"ready": False, "status": {}, "skipped": True, "reason": ""}
            child_advanced_status = {}
            child_advanced_ready = False
        child_effective_mode = preferred_mode
        child_fallback = False
        if preferred_mode == "lttx" and not child_advanced_ready and child_ctypes_ready:
            child_effective_mode = "ctypes"
            child_fallback = True
        child_selected = child_advanced_status if child_effective_mode == "lttx" else child_ctypes_status
        market_route_statuses[market] = {
            "market": market,
            "bridge_id": child_bridge_id,
            "base_bridge_id": bridge_id,
            "qmt_dir": normalize_optional_path(route.get("qmt_dir")),
            "preferred_mode": preferred_mode,
            "effective_mode": child_effective_mode,
            "fallback": child_fallback,
            "ready": child_advanced_ready if child_effective_mode == "lttx" else child_ctypes_ready,
            "status": child_selected,
            "modes": {
                "ctypes": {"ready": child_ctypes_ready, "status": child_ctypes_status},
                "lttx": {
                    "ready": child_advanced_ready,
                    "status": child_advanced_status,
                    "skipped": bool(child_advanced.get("skipped")),
                    "reason": child_advanced.get("reason") or "",
                },
            },
        }
    market_routing_ready = bool(market_route_statuses) and all(
        row.get("ready") for row in market_route_statuses.values()
    )
    native_ready = advanced_ready if effective_mode == "lttx" else ctypes_ready
    account_ready = native_ready or market_routing_ready
    return {
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "account_key": account_key,
        "bridge_id": bridge_id,
        "preferred_mode": preferred_mode,
        "effective_mode": effective_mode,
        "fallback": fallback,
        "qmt_dir": (config or {}).get("qmt_dir", ""),
        "data_provider": account_key == (WEB_CONFIG.data_provider_account_key() if WEB_CONFIG else ""),
        "ready": account_ready,
        "native_ready": native_ready,
        "status": selected,
        "market_routing_enabled": parse_config_bool((market_config or {}).get("market_routing_enabled"), False),
        "market_routing_ready": market_routing_ready,
        "market_routes": market_route_statuses,
        "modes": {
            "ctypes": {"ready": ctypes_ready, "status": ctypes_status},
            "lttx": {
                "ready": advanced_ready,
                "status": advanced_status,
                "skipped": bool(advanced.get("skipped")),
                "reason": advanced.get("reason") or "",
            },
        },
    }


def binding_status_snapshot():
    configs = WEB_CONFIG.account_configs() if WEB_CONFIG is not None else {}
    pairs = WEB_CONFIG.account_pairs() if WEB_CONFIG is not None else {}
    entries = []
    known_keys = set()

    def append_entry(account_key, account_id, account_type, bridge_id):
        account_key = str(account_key or "").strip()
        account_id = str(account_id or "").strip()
        account_type = normalize_account_type(account_type or "STOCK")
        bridge_id = str(bridge_id or "").strip()
        if not account_id:
            return
        if not account_key:
            account_key = account_key_for(account_id, account_type, bridge_id or DEFAULT_BRIDGE_ID)
        if account_key in known_keys:
            return
        known_keys.add(account_key)
        entries.append({
            "account_key": account_key,
            "account_id": account_id,
            "account_type": account_type,
            "bridge_id": bridge_id,
        })

    for raw_key, config in configs.items():
        config = config if isinstance(config, dict) else {}
        account_id = str(config.get("account_id") or raw_key or "").strip()
        account_type = normalize_account_type(config.get("account_type") or "STOCK")
        bridge_id = str(config.get("bridge_id") or DEFAULT_BRIDGE_ID).strip()
        append_entry(config.get("account_key") or raw_key, account_id, account_type, bridge_id)

    for raw_key, pair in pairs.items():
        if isinstance(pair, dict):
            account_id = str(pair.get("account_id") or raw_key or "").strip()
            account_type = normalize_account_type(pair.get("account_type") or "STOCK")
            bridge_id = str(pair.get("bridge_id") or "").strip()
            account_key = pair.get("account_key") or raw_key
        else:
            account_id = str(raw_key or "").strip()
            account_type = "STOCK"
            bridge_id = str(pair or "").strip()
            account_key = account_key_for(account_id, account_type, bridge_id or DEFAULT_BRIDGE_ID)
        append_entry(account_key, account_id, account_type, bridge_id)

    rows = []
    for entry in entries:
        try:
            status = account_route_status(
                entry["account_id"],
                bridge_id=entry["bridge_id"] or None,
                account_type=entry["account_type"],
                account_key=entry["account_key"],
            )
            rows.append(dict(entry, status=status))
        except Exception as error:
            rows.append(dict(entry, error=str(error)))
    now = time.time()
    return {
        "bindings": rows,
        "cached": True,
        "checked_at": now,
        "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
    }


class PipeHubManager(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._status = None
        self._last_error = ""
        self._status_cache = None
        self._status_cache_at = 0.0

    def _python_exe(self):
        return sys.executable

    def _entry_path(self):
        entry = os.path.abspath(PIPE_HUB_ENTRY)
        return entry if os.path.isfile(entry) else ""

    def _command(self):
        entry = self._entry_path()
        if entry:
            return [self._python_exe(), entry]
        return [self._python_exe(), "-m", PIPE_HUB_MODULE]

    def _command_matches(self, command_line):
        command_line = str(command_line or "").lower()
        entry = self._entry_path()
        if entry and os.path.basename(entry).lower() in command_line:
            return True
        return PIPE_HUB_MODULE.lower() in command_line

    def status(self, force=False):
        with self._lock:
            now_monotonic = time.monotonic()
            if (
                not force
                and self._status_cache is not None
                and now_monotonic - self._status_cache_at < PIPE_HUB_STATUS_CACHE_SECONDS
            ):
                return dict(self._status_cache)

            data = self._read_status_file()
            if data:
                self._status = data
            running = False
            process_pid = None
            if self._process is not None and getattr(self._process, "poll", lambda: 1)() is None:
                process_pid = self._process.pid
                running = True
            if not running:
                try:
                    status_pid = int((self._status or {}).get("pid") or 0)
                except Exception:
                    status_pid = 0
                if status_pid:
                    status_details = process_details_by_pid([status_pid])
                    status_command = (status_details.get(status_pid) or {}).get("command_line") or ""
                    if self._command_matches(status_command):
                        process_pid = status_pid
                        running = True
            if not running:
                entry_name = os.path.basename(self._entry_path() or PIPE_HUB_MODULE).lower()
                module_name = PIPE_HUB_MODULE.lower()
                rows = run_powershell_json(
                    "$name='%s'; $module='%s'; "
                    "$rows=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -and ($_.CommandLine.ToLower().Contains($name) -or $_.CommandLine.ToLower().Contains($module)) } | "
                    "ForEach-Object { [pscustomobject]@{ pid=$_.ProcessId; command_line=$_.CommandLine } }); "
                    "if ($null -eq $rows) { '[]' } else { @($rows) | ConvertTo-Json -Compress }"
                    % (entry_name.replace("'", "''"), module_name.replace("'", "''")),
                    timeout=5.0,
                )
                for row in rows:
                    try:
                        candidate_pid = int(row.get("pid") or 0)
                    except Exception:
                        candidate_pid = 0
                    if candidate_pid:
                        process_pid = candidate_pid
                        running = True
                        break
            result = {
                "running": running,
                "pipe_name": (self._status or {}).get("pipe_name") or normalize_pipe_name(os.environ.get("CFQUANT_PIPE_NAME") or DEFAULT_PIPE_NAME),
                "status_file": PIPE_HUB_STATUS_FILE,
                "process_pid": process_pid,
                "last_error": self._last_error,
                "status": self._status or {},
                "entry": self._entry_path() or PIPE_HUB_MODULE,
                "checked_at": time.time(),
            }
            self._status_cache = result
            self._status_cache_at = now_monotonic
            return dict(result)

    def start(self):
        with self._lock:
            if self._process is not None and getattr(self._process, "poll", lambda: 1)() is None:
                return self.status(force=True)
            current = self.status(force=True)
            if current.get("running"):
                return current
            command = self._command()
            creationflags = 0
            if os.name == "nt":
                creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            popen_kwargs = {"creationflags": creationflags, "close_fds": False if os.name == "nt" else True}
            if os.name == "nt":
                hidden_kwargs = _hidden_subprocess_kwargs()
                popen_kwargs.update(hidden_kwargs)
                popen_kwargs["creationflags"] = creationflags | int(hidden_kwargs.get("creationflags") or 0)
            env = os.environ.copy()
            env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
            env.setdefault("CFQUANT_LOG_DIR", LOG_DIR)
            env.setdefault("CFQUANT_LOG_RETENTION_DAYS", str(LOG_RETENTION_DAYS))
            env.setdefault("CFQUANT_PIPE_HUB_STATUS_FILE", PIPE_HUB_STATUS_FILE)
            stdout = open(PIPE_HUB_STDOUT_LOG, "a", encoding="utf-8", buffering=1)
            stderr = open(PIPE_HUB_STDERR_LOG, "a", encoding="utf-8", buffering=1)
            try:
                self._process = subprocess.Popen(
                    command,
                    cwd=STATE_DIR if os.path.isdir(STATE_DIR) else BASE_DIR,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    env=env,
                    **popen_kwargs
                )
            finally:
                try:
                    stdout.close()
                    stderr.close()
                except Exception:
                    pass
            time.sleep(0.8)
            return self.status(force=True)

    def stop(self):
        with self._lock:
            process = self._process
            self._process = None
        pid = int(self.status().get("process_pid") or 0)
        if process is not None and getattr(process, "poll", lambda: 1)() is None:
            try:
                process.terminate()
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        elif pid > 0:
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=6.0,
                    **_hidden_subprocess_kwargs()
                )
                if completed.returncode != 0:
                    self._last_error = (completed.stderr or completed.stdout or "").strip()
            except Exception as e:
                self._last_error = str(e)
        return self.status(force=True)

    def _read_status_file(self):
        if not os.path.isfile(PIPE_HUB_STATUS_FILE):
            return {}
        try:
            with open(PIPE_HUB_STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self._last_error = str(e)
            return {}


PIPE_HUB = PipeHubManager()


CLIENTS = GlobalTxClient()


def _external_account_id(params):
    params = params or {}
    account = params.get("account") if isinstance(params.get("account"), dict) else {}
    return str(
        account.get("account_id")
        or account.get("m_strAccountID")
        or params.get("account_id")
        or params.get("m_strAccountID")
        or ""
    ).strip()


def _external_account_type(params):
    params = params or {}
    account = params.get("account") if isinstance(params.get("account"), dict) else {}
    return normalize_account_type(account.get("account_type") or params.get("account_type") or "STOCK")


def _external_account_key(params):
    params = params or {}
    account = params.get("account") if isinstance(params.get("account"), dict) else {}
    return str(account.get("account_key") or params.get("account_key") or "").strip()


def _external_default_channel(action):
    action = str(action or "")
    if action in {
        "xttrader.order_stock",
        "xttrader.order_stock_async",
        "xttrader.order_stock_batch",
        "xttrader.cancel_order_stock",
        "xttrader.cancel_order_stock_async",
        "xttrader.cancel_order_stock_sysid",
        "xttrader.cancel_order_stock_sysid_async",
    }:
        return "trade"
    if action in NORMAL_QMT_ACTIONS:
        return "normal"
    if action.startswith("xttrader."):
        return "trade"
    return "trade"


def build_lttx_registry():
    core_info = current_core_version_info()
    configs = WEB_CONFIG.account_configs() if WEB_CONFIG is not None else {}
    accounts = {}
    for account_key, row in configs.items():
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("account_id") or "").strip()
        account_type = normalize_account_type(row.get("account_type") or "STOCK")
        key = str(row.get("account_key") or account_key or account_key_for(account_id, account_type, row.get("bridge_id"))).strip()
        accounts[key] = {
            "account_key": key,
            "account_id": account_id,
            "account_type": account_type,
            "account_type_label": account_type_label(account_type),
            "bridge_id": normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID),
            "mode": normalize_transport_mode(row.get("mode") or "ctypes"),
            "enabled": bool(row.get("enabled", True)),
            "data_provider": bool(row.get("data_provider")),
        }
    now = time.time()
    return {
        "schema": "cfquant.lttx.registry",
        "version": core_info["version"],
        "core_version": core_info["version"],
        "core_version_info": core_info,
        "web_version": WEB_VERSION,
        "frontend_version": WEB_VERSION,
        "updated_at": now,
        "updated_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "discovery_key": LTTX_DISCOVERY_KEY,
        "web_request_channel": LTTX_WEB_REQUEST_CHANNEL,
        "transport_mode": WEB_CONFIG.transport_mode() if WEB_CONFIG is not None else "ctypes",
        "default_account_id": configured_default_account_id(),
        "default_account_type": configured_default_account_type(),
        "default_account_key": configured_default_account_key(),
        "data_provider_account_id": WEB_CONFIG.data_provider_account_id() if WEB_CONFIG is not None else "",
        "data_provider_account_type": WEB_CONFIG.setup_info().get("data_provider_account_type") if WEB_CONFIG is not None else "STOCK",
        "data_provider_account_key": WEB_CONFIG.data_provider_account_key() if WEB_CONFIG is not None else "",
        "accounts": accounts,
        "bridges": current_bridges(),
        "web_route": {
            "enabled": True,
            "request_channel": LTTX_WEB_REQUEST_CHANNEL,
            "transport": "web_lttx",
            "description": "外部 cfquant 通过 LTtx 统一请求频道进入 Web 账号路由。",
        },
        "direct_fallback_transport": "ctypes",
        "features": {
            "account_routing": True,
            "mode_auto_detect": True,
            "advanced_fallback_to_ctypes": True,
            "quote_event_forward": True,
            "trader_event_forward": True,
        },
    }


def route_external_lttx_request(msg):
    action = str(msg.get("action") or "")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    if action in ("cfquant.registry", "cfquant.discovery", "cfquant.runtime"):
        return build_lttx_registry(), {"route": "registry"}
    if action == "cfquant.ping":
        return {
            "pong": True,
            "via": "web_lttx",
            "ts": time.time(),
            "web_request_channel": LTTX_WEB_REQUEST_CHANNEL,
            "version": current_core_version(),
        }, {"route": "web_lttx"}
    if action == "cfquant.status":
        account_id = _external_account_id(params)
        account_type = _external_account_type(params)
        account_key = _external_account_key(params)
        if account_id:
            return account_route_status(account_id, bridge_id=params.get("bridge_id"), account_type=account_type, account_key=account_key), {"route": "account_status"}
        return build_lttx_registry(), {"route": "registry"}

    default_channel = normalize_channel(params.get("default_channel") or _external_default_channel(action), "normal")
    requested_channel = params.get("channel") or params.get("request_channel")
    account_id = _external_account_id(params)
    account_type = _external_account_type(params)
    account_key = _external_account_key(params)
    timeout = float(params.get("timeout") or msg.get("timeout") or 12.0)
    if action.startswith("xttrader."):
        account_id = account_id or configured_default_account_id()
        if action == "xttrader.order_stock_batch":
            route = account_batch_order_request(
                account_id,
                params.get("bridge_id"),
                requested_channel,
                params,
                default_channel=default_channel,
                timeout=timeout,
                account_type=account_type,
                account_key=account_key,
            )
        else:
            route = account_request(
                account_id,
                params.get("bridge_id"),
                requested_channel,
                action,
                params,
                default_channel=default_channel,
                timeout=timeout,
                mark_offline_on_timeout=True,
                account_type=account_type,
                account_key=account_key,
            )
        meta = dict(route)
        meta.pop("result", None)
        meta["route"] = "account"
        return route["result"], meta
    if action.startswith("xtdata."):
        if account_id:
            route = routed_xtdata_account_request(
                account_id,
                params.get("bridge_id"),
                requested_channel,
                action,
                params,
                default_channel=default_channel,
                timeout=timeout,
                mark_offline_on_timeout=True,
                account_type=account_type,
                account_key=account_key,
            )
        else:
            route = data_provider_request(
                action,
                params,
                requested_channel=requested_channel,
                default_channel=default_channel,
                timeout=timeout,
                bridge_id=params.get("bridge_id"),
            )
        meta = dict(route)
        meta.pop("result", None)
        meta["route"] = "data"
        return route["result"], meta
    raise ValueError("unsupported external web_lttx action: %s" % action)


class LttxWebRouteServer(object):
    def __init__(self, request_channel=LTTX_WEB_REQUEST_CHANNEL, discovery_key=LTTX_DISCOVERY_KEY):
        self.request_channel = request_channel
        self.discovery_key = discovery_key
        self.running = False
        self.tx = None
        self.thread = None
        self._lock = threading.RLock()
        self._quote_subscribers = {}
        self._account_subscribers = {}
        self._last_registry_put = 0.0

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            CLIENTS.add_callback("quote", self._on_quote_event)
            CLIENTS.add_callback("__event__", self._on_client_event)
            self.thread = threading.Thread(target=self._loop)
            self.thread.daemon = True
            self.thread.start()
        safe_print("cfquant LTtx 统一路由已启动 channel=%s registry=%s" % (self.request_channel, self.discovery_key))

    def close(self):
        self.running = False
        CLIENTS.remove_callback("quote", self._on_quote_event)
        CLIENTS.remove_callback("__event__", self._on_client_event)
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass

    def publish_registry(self, force=False):
        tx = self.tx
        if tx is None:
            return False
        now = time.time()
        if not force and now - self._last_registry_put < LTTX_REGISTRY_INTERVAL_SECONDS:
            return False
        registry = build_lttx_registry()
        try:
            tx.put(self.discovery_key, registry)
            tx.put("%s.version" % self.discovery_key, registry.get("version"))
            tx.put("%s.web_request_channel" % self.discovery_key, self.request_channel)
            tx.put("%s.transport_mode" % self.discovery_key, registry.get("transport_mode"))
            self._last_registry_put = now
            return True
        except Exception as e:
            safe_print("cfquant LTtx 注册信息写入失败: %s" % e)
            return False

    def _loop(self):
        while self.running:
            tx = None
            try:
                tx = txl(LTTX_HOST, LTTX_PORT, "LTtx", show=False)
                tx.start_tx()
                tx.start_txg(self.request_channel)
                self.tx = tx
                self.publish_registry(force=True)
                while self.running and self.tx is tx:
                    self.publish_registry()
                    try:
                        raw = tx.Q.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    if raw is None:
                        break
                    self._handle_raw(raw)
            except Exception as e:
                if self.running:
                    safe_print("cfquant LTtx 统一路由异常: %s，1秒后重试" % e)
                    time.sleep(1)
            finally:
                if self.tx is tx:
                    self.tx = None
                if tx is not None:
                    try:
                        tx.close()
                    except Exception:
                        pass

    def _handle_raw(self, raw):
        msg = loads_message(raw)
        if not msg or msg.get("type") != "request":
            return
        request_id = msg.get("id")
        client_id = msg.get("client_id") or msg.get("reply_channel")
        action = str(msg.get("action") or "")
        try:
            result, meta = route_external_lttx_request(msg)
            response = pack_response(request_id, ok=True, result=result, meta=meta)
            self._remember_external_subscription(action, msg, result)
        except Exception as e:
            response = pack_response(request_id, ok=False, error=e, meta={"route": "web_lttx"})
            safe_print("cfquant LTtx 统一路由请求失败 action=%s id=%s error=%s" % (action, request_id, e))
        if client_id and self.tx is not None:
            try:
                self.tx.push("response", response, client_id)
            except Exception as e:
                safe_print("cfquant LTtx 统一路由回包失败 client=%s error=%s" % (client_id, e))

    def _remember_external_subscription(self, action, msg, result):
        client_id = msg.get("client_id") or msg.get("reply_channel")
        params = msg.get("params") or {}
        if not client_id:
            return
        if action in ("xtdata.subscribe_quote", "xtdata.subscribe_whole_quote"):
            subscribe_id = ""
            if isinstance(result, dict):
                subscribe_id = str(result.get("subscribe_id") or "")
            else:
                subscribe_id = str(result or "")
            if subscribe_id:
                with self._lock:
                    self._quote_subscribers.setdefault(subscribe_id, set()).add(client_id)
        elif action == "xtdata.unsubscribe_quote":
            subscribe_id = str(params.get("subscribe_id") or "")
            if subscribe_id:
                with self._lock:
                    subscribers = self._quote_subscribers.get(subscribe_id)
                    if subscribers:
                        subscribers.discard(client_id)
                        if not subscribers:
                            self._quote_subscribers.pop(subscribe_id, None)
        elif action == "xttrader.subscribe":
            account_id = _external_account_id(params) or configured_default_account_id()
            account_type = _external_account_type(params)
            bridge_id = params.get("bridge_id") or resolve_bridge_id(account_id=account_id, account_type=account_type)
            account_key = _external_account_key(params)
            account_keys = account_subscription_keys(
                account_id,
                account_type,
                bridge_id,
                account_key,
            )
            if account_id:
                with self._lock:
                    for item_key in account_keys:
                        self._account_subscribers.setdefault(item_key, set()).add(client_id)
        elif action == "xttrader.unsubscribe":
            account_id = _external_account_id(params)
            account_type = _external_account_type(params)
            account_key = _external_account_key(params)
            account_keys = []
            if account_id:
                bridge_id = params.get("bridge_id") or resolve_bridge_id(account_id=account_id, account_type=account_type, account_key=account_key)
                account_keys = account_subscription_keys(
                    account_id,
                    account_type,
                    bridge_id,
                    account_key,
                )
            with self._lock:
                if account_keys:
                    for item_key in account_keys:
                        subscribers = self._account_subscribers.get(item_key)
                        if subscribers:
                            subscribers.discard(client_id)
                            if not subscribers:
                                self._account_subscribers.pop(item_key, None)
                elif account_key:
                    subscribers = self._account_subscribers.get(account_key)
                    if subscribers:
                        subscribers.discard(client_id)
                        if not subscribers:
                            self._account_subscribers.pop(account_key, None)
                else:
                    for subscribers in self._account_subscribers.values():
                        subscribers.discard(client_id)

    def _on_quote_event(self, msg):
        if not isinstance(msg, dict):
            return
        subscribe_id = str(msg.get("subscription_id") or msg.get("subscribe_id") or "")
        with self._lock:
            client_ids = sorted(self._quote_subscribers.get(subscribe_id, set()))
        for client_id in client_ids:
            self._push_event(client_id, msg.get("event") or "quote:%s" % subscribe_id, msg.get("data"), subscribe_id)

    def _on_client_event(self, msg):
        if not isinstance(msg, dict):
            return
        event = str(msg.get("event") or "")
        if not event.startswith("trader:"):
            return
        account_id = CallbackEventStore.event_account_id_static(msg)
        account_type = CallbackEventStore.event_account_type_static(msg)
        bridge_id = CallbackEventStore.event_bridge_id_static(msg) or DEFAULT_BRIDGE_ID
        if not account_id and isinstance(msg.get("data"), dict):
            account_id = _external_account_id(msg.get("data"))
            account_type = _external_account_type(msg.get("data"))
        account_keys = account_subscription_keys(account_id, account_type, bridge_id, msg.get("account_key")) if account_id else []
        with self._lock:
            client_ids_set = set()
            for account_key in account_keys:
                client_ids_set.update(self._account_subscribers.get(account_key, set()))
            client_ids = sorted(client_ids_set)
        for client_id in client_ids:
            self._push_event(client_id, event, msg.get("data"))

    def _push_event(self, client_id, event, data=None, subscription_id=None):
        tx = self.tx
        if tx is None or not client_id:
            return
        try:
            payload = pack_event(event, data=data, client_id=client_id, subscription_id=subscription_id)
            tx.push("event", payload, client_id)
        except Exception as e:
            safe_print("cfquant LTtx 统一路由事件转发失败 client=%s event=%s error=%s" % (client_id, event, e))


LTTX_WEB_ROUTE = LttxWebRouteServer()


class RuntimeVersionRegistry(object):
    def __init__(self, ttl_seconds=RUNTIME_REPORT_TTL_SECONDS, persist_file=None):
        self.ttl_seconds = float(ttl_seconds)
        self.persist_file = os.path.abspath(persist_file or QMT_RUNTIME_VERSION_FILE)
        self._lock = threading.RLock()
        self._reports = {}
        self._load_persisted()

    def update_from_status(self, bridge_id, channel_key, status, mode="", source="cfquant.status"):
        if not isinstance(status, dict):
            return None
        runtime = status.get("runtime") if isinstance(status.get("runtime"), dict) else {}
        version = self._first_value(
            runtime,
            status,
            keys=("core_version", "version", "runtime_core_version", "qmt_runtime_core_version"),
        )
        if not version:
            return None
        report = self._build_report(
            bridge_id=bridge_id or runtime.get("bridge_id") or status.get("bridge_id"),
            channel_key=channel_key,
            version=version,
            source=source,
            mode=mode or runtime.get("transport") or status.get("transport") or "",
            runtime=runtime,
            status=status,
        )
        return self._remember(report)

    def update_from_event(self, event):
        if not isinstance(event, dict):
            return None
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        event_name = str(event.get("event") or data.get("event") or "")
        schema = str(data.get("schema") or "")
        if event_name != "cfquant.runtime" and schema != "cfquant.qmt.runtime":
            return None
        version = self._first_value(
            data,
            keys=("core_version", "version", "runtime_core_version", "qmt_runtime_core_version"),
        )
        if not version:
            return None
        report = self._build_report(
            bridge_id=data.get("bridge_id") or event.get("bridge_id") or meta.get("bridge_id"),
            channel_key=data.get("channel_key") or data.get("channel") or data.get("request_channel") or "",
            version=version,
            source=str(meta.get("source") or "qmt_runtime_report"),
            mode=data.get("transport") or "",
            runtime=data,
            status={},
        )
        return self._remember(report)

    def latest(self, bridge_id=None):
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        with self._lock:
            rows = [
                dict(row)
                for (item_bridge_id, _channel), row in self._reports.items()
                if item_bridge_id == bridge_id
            ]
        if not rows:
            return self._empty_report(bridge_id)
        rows.sort(key=lambda item: float(item.get("reported_at") or 0), reverse=True)
        latest = rows[0]
        age = max(0.0, time.time() - float(latest.get("reported_at") or 0))
        latest["age_seconds"] = round(age, 1)
        latest["ttl_seconds"] = self.ttl_seconds
        latest["stale"] = age > self.ttl_seconds
        latest["reported"] = not latest["stale"]
        latest["has_report"] = True
        latest["saved"] = True
        latest["saved_version"] = latest.get("version") or ""
        latest["saved_core_version"] = latest.get("core_version") or latest.get("version") or ""
        latest["saved_reported_at"] = latest.get("reported_at") or 0
        latest["saved_reported_at_text"] = latest.get("reported_at_text") or ""
        latest["persist_file"] = self.persist_file
        latest["message"] = (
            "QMT 运行时版本已上报"
            if latest["reported"] else
            "QMT 运行时版本上报已过期，请确认对应 QMT 桥接脚本正在运行"
        )
        latest["reports"] = rows[:6]
        return latest

    def _remember(self, report):
        bridge_id = normalize_bridge_id(report.get("bridge_id") or DEFAULT_BRIDGE_ID)
        channel_key = str(report.get("channel_key") or report.get("request_channel") or "runtime").strip() or "runtime"
        report["bridge_id"] = bridge_id
        report["channel_key"] = channel_key
        with self._lock:
            existing = self._reports.get((bridge_id, channel_key))
            if existing and self._report_timestamp(report) <= self._report_timestamp(existing):
                # Marker files remain on disk after QMT restarts. Do not let
                # an older process report replace the active channel report.
                return dict(existing)
            self._reports[(bridge_id, channel_key)] = dict(report)
            self._persist_locked()
        return dict(report)

    def _load_persisted(self):
        try:
            if not os.path.isfile(self.persist_file):
                return
            with open(self.persist_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            rows = payload.get("reports") if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                return
            with self._lock:
                for row in rows:
                    if not isinstance(row, dict) or not row.get("version"):
                        continue
                    bridge_id = normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID)
                    channel_key = str(row.get("channel_key") or row.get("request_channel") or "runtime").strip() or "runtime"
                    item = dict(row)
                    item["bridge_id"] = bridge_id
                    item["channel_key"] = channel_key
                    item["loaded_from_disk"] = True
                    existing = self._reports.get((bridge_id, channel_key))
                    if not existing or self._report_timestamp(item) > self._report_timestamp(existing):
                        self._reports[(bridge_id, channel_key)] = item
        except Exception as e:
            safe_print("qmt runtime version persistence load failed: %s" % e)

    def _persist_locked(self):
        try:
            os.makedirs(os.path.dirname(self.persist_file), exist_ok=True)
            rows = sorted(
                [dict(row) for row in self._reports.values() if row.get("version")],
                key=lambda item: float(item.get("reported_at") or 0),
                reverse=True,
            )[:64]
            now = time.time()
            payload = {
                "schema": "cfquant.qmt.runtime_versions",
                "updated_at": now,
                "updated_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "reports": rows,
            }
            temp_path = self.persist_file + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temp_path, self.persist_file)
        except Exception as e:
            safe_print("qmt runtime version persistence write failed: %s" % e)

    def _build_report(self, bridge_id, channel_key, version, source, mode, runtime, status):
        now = time.time()
        runtime = runtime if isinstance(runtime, dict) else {}
        status = status if isinstance(status, dict) else {}
        request_channel = self._first_value(runtime, status, keys=("request_channel", "callback_event_channel"))
        reported_at = self._first_number(
            runtime,
            status,
            keys=("reported_at", "marker_written_at", "marker_mtime", "checked_at"),
        ) or now
        reported_at_text = self._first_value(
            runtime,
            status,
            keys=("reported_at_text", "marker_written_at_text", "marker_mtime_text", "checked_at_text"),
        ) or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(reported_at))
        return {
            "bridge_id": normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID),
            "channel_key": str(channel_key or "").strip(),
            "request_channel": request_channel,
            "version": str(version or "").strip(),
            "core_version": str(version or "").strip(),
            "source": source,
            "mode": str(mode or "").strip(),
            "transport": self._first_value(runtime, status, keys=("transport",)),
            "report_schema": self._first_value(runtime, status, keys=("report_schema", "schema")),
            "runtime_mode": self._first_value(
                runtime,
                status,
                keys=("runtime_mode", "qmt_runtime_mode", "transport_mode"),
            ),
            "entry_version": self._first_value(
                runtime,
                status,
                keys=("entry_version", "runtime_entry_version", "qmt_runtime_entry_version"),
            ),
            "entry_script": self._first_value(
                runtime,
                status,
                keys=("entry_script", "qmt_runtime_entry_script"),
            ),
            "bridge": self._first_value(runtime, status, keys=("bridge",)),
            "account_id": self._first_value(runtime, status, keys=("account_id",)),
            "account_type": self._first_value(runtime, status, keys=("account_type",)),
            "account_key": self._first_value(runtime, status, keys=("account_key",)),
            "pid": self._first_value(runtime, status, keys=("pid",)),
            "python": self._first_value(runtime, status, keys=("python",)),
            "entry_file": self._first_value(runtime, status, keys=("entry_file", "qmt_runtime_entry_file")),
            "core_dir": self._first_value(runtime, status, keys=("core_dir",)),
            "version_file": self._first_value(runtime, status, keys=("version_file",)),
            "pipe_name": self._first_value(runtime, status, keys=("pipe_name",)),
            "market": self._first_value(runtime, status, keys=("market",)),
            "market_role": self._first_value(runtime, status, keys=("market_role",)),
            "marker_file": self._first_value(runtime, status, keys=("marker_file", "marker_primary_file")),
            "marker_dir": self._first_value(runtime, status, keys=("marker_dir",)),
            "marker_written_at": self._first_value(runtime, status, keys=("marker_written_at",)),
            "marker_written_at_text": self._first_value(runtime, status, keys=("marker_written_at_text",)),
            "reason": self._first_value(runtime, status, keys=("reason",)),
            "started_at": runtime.get("started_at") or status.get("started_at") or 0,
            "started_at_text": runtime.get("started_at_text") or status.get("started_at_text") or "",
            "reported_at": reported_at,
            "reported_at_text": reported_at_text,
            "reported": True,
            "stale": False,
            "has_report": True,
            "message": "QMT 运行时版本已上报",
        }

    def _empty_report(self, bridge_id):
        return {
            "bridge_id": normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID),
            "version": "",
            "core_version": "",
            "reported": False,
            "has_report": False,
            "stale": False,
            "age_seconds": None,
            "ttl_seconds": self.ttl_seconds,
            "reports": [],
            "saved": False,
            "saved_version": "",
            "saved_core_version": "",
            "saved_reported_at": 0,
            "saved_reported_at_text": "",
            "persist_file": self.persist_file,
            "message": "未收到 QMT 运行时版本上报，请先运行对应 QMT 桥接脚本后再查看",
        }

    def _first_value(self, *items, keys):
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in keys:
                value = item.get(key)
                if value not in (None, ""):
                    return str(value).strip()
        return ""

    def _first_number(self, *items, keys):
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in keys:
                value = item.get(key)
                if value in (None, ""):
                    continue
                try:
                    return float(value)
                except Exception:
                    continue
        return 0.0

    @staticmethod
    def _report_timestamp(report):
        try:
            return float((report or {}).get("reported_at") or 0)
        except Exception:
            return 0.0


RUNTIME_VERSIONS = RuntimeVersionRegistry()


def ctypes_bridge_status(bridge_id=DEFAULT_BRIDGE_ID):
    bridge_id = normalize_bridge_id(bridge_id)
    read_qmt_runtime_marker_reports(bridge_id)
    channels = bridge_channels(bridge_id)
    hub = PIPE_HUB.status()
    hub_status = hub.get("status") or {}
    connected_channels = set(hub_status.get("qmt_channels") or [])
    rx_raw = hub_status.get("qmt_rx_channels")
    tx_raw = hub_status.get("qmt_tx_channels")
    ready_raw = hub_status.get("qmt_ready_channels")
    has_directional_channels = isinstance(rx_raw, list) or isinstance(tx_raw, list) or isinstance(ready_raw, list)
    rx_channels = set(rx_raw or [])
    tx_channels = set(tx_raw or [])
    ready_channels = set(ready_raw or [])
    hub_running = bool(hub.get("running"))

    def pipe_channel_ready(channel):
        if has_directional_channels:
            return channel in ready_channels or (channel in rx_channels and channel in tx_channels)
        return channel in connected_channels

    def pipe_channel_online(channel):
        return bool(hub_running and pipe_channel_ready(channel))

    now = time.time()
    normal_online = pipe_channel_online(channels["normal"])
    trade_online = pipe_channel_online(channels["trade"])
    result = {
        "bridge_id": bridge_id,
        "bridge_name": bridge_config(bridge_id)["name"],
        "runtime_report": RUNTIME_VERSIONS.latest(bridge_id),
        "normal": {
            "online": normal_online,
            "channel": channels["normal"],
            "probe_action": "pipe_hub.status",
            "status": {
                "bridge": "PipeNormalQmtBridge",
                "transport": "pipe",
                "pipe_name": hub.get("pipe_name"),
                "request_channel": channels["normal"],
                "pipe_connected": normal_online,
                "pipe_ready_channel": pipe_channel_ready(channels["normal"]),
                "pipe_rx_connected": channels["normal"] in rx_channels,
                "pipe_tx_connected": channels["normal"] in tx_channels,
            },
        },
        "trade": {
            "online": trade_online,
            "channel": channels["trade"],
            "probe_action": "pipe_hub.status",
            "status": {
                "bridge": "PipeTradeBridge",
                "transport": "pipe",
                "pipe_name": hub.get("pipe_name"),
                "request_channel": channels["trade"],
                "pipe_connected": trade_online,
                "pipe_ready_channel": pipe_channel_ready(channels["trade"]),
                "pipe_rx_connected": channels["trade"] in rx_channels,
                "pipe_tx_connected": channels["trade"] in tx_channels,
            },
        },
        "checked_at": now,
        "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "monitor": {
            "running": True,
            "interval_seconds": 0,
            "cached": False,
            "ready": True,
            "transport_mode": "ctypes",
            "pipe_hub": hub,
        },
    }
    for channel_name in ("normal", "trade"):
        row = result[channel_name]
        row["latency_ms"] = 0
        if not row["online"]:
            row["error"] = "ctypes PipeHub channel is offline"
    return result


class WebSocketCallbackClient(object):
    def __init__(self, sock, bridge_id="", account_id="", account_type="", account_key="", event_name="", event_prefix="", job_id=""):
        self.sock = sock
        self.bridge_id = normalize_bridge_id(bridge_id) if bridge_id else ""
        self.account_id = str(account_id or "").strip()
        self.account_type = normalize_account_type(account_type) if account_type not in ("", None) else ""
        self.account_key = str(account_key or "").strip()
        self.event_name = str(event_name or "").strip()
        self.event_prefix = str(event_prefix or "").strip()
        self.job_id = str(job_id or "").strip()
        self._lock = threading.RLock()
        self.alive = True

    def matches(self, event):
        if self.bridge_id:
            event_bridge_id = normalize_bridge_id(CallbackEventStore.event_bridge_id_static(event) or "default")
            bridge_ids = account_related_bridge_ids(
                account_id=self.account_id,
                account_type=self.account_type or None,
                bridge_id=self.bridge_id,
                account_key=self.account_key,
            ) if (self.account_id or self.account_key) else [self.bridge_id]
            if event_bridge_id not in bridge_ids:
                return False
        if self.account_id and CallbackEventStore.event_account_id_static(event) != self.account_id:
            return False
        if self.account_type:
            event_type = CallbackEventStore.event_account_type_static(event)
            if event_type and event_type != self.account_type:
                return False
            if not event_type and self.bridge_id and self.account_id and account_identity_is_ambiguous(self.bridge_id, self.account_id):
                return False
        event_name = str(event.get("event") or "")
        if self.event_name and event_name != self.event_name:
            return False
        if self.event_prefix and not event_name.startswith(self.event_prefix):
            return False
        if self.job_id and CallbackEventStore.event_job_id_static(event) != self.job_id:
            return False
        return True

    def send_json(self, payload):
        raw = json.dumps(to_jsonable(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        frame = self._frame(raw)
        with self._lock:
            self.sock.sendall(frame)

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except Exception:
            pass

    def _frame(self, payload):
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(length)
        elif length <= 0xFFFF:
            header.append(126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(127)
            header.extend(length.to_bytes(8, "big"))
        return bytes(header) + payload


class WebSocketCallbackManager(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._clients = set()

    def add(self, client):
        with self._lock:
            self._clients.add(client)

    def remove(self, client):
        with self._lock:
            self._clients.discard(client)
        client.close()

    def broadcast(self, event):
        dead = []
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            if not client.alive or not client.matches(event):
                continue
            try:
                client.send_json({
                    "type": "callback",
                    "event": event,
                })
            except Exception:
                dead.append(client)
        for client in dead:
            self.remove(client)

    def count(self):
        with self._lock:
            return len(self._clients)


WS_CALLBACKS = WebSocketCallbackManager()


class WebSocketQuoteClient(WebSocketCallbackClient):
    def __init__(self, sock, subscribe_id=None):
        WebSocketCallbackClient.__init__(self, sock)
        self.subscribe_id = str(subscribe_id or "").strip()

    def matches(self, event):
        if self.subscribe_id and str(event.get("subscribe_id") or "") != self.subscribe_id:
            return False
        return True


class WebSocketQuoteManager(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._clients = set()
        self.on_empty = None

    def add(self, client):
        with self._lock:
            self._clients.add(client)

    def remove(self, client):
        with self._lock:
            self._clients.discard(client)
            empty = not self._clients
        client.close()
        if empty and callable(self.on_empty):
            try:
                self.on_empty()
            except Exception as e:
                safe_print("websocket quotes empty callback failed: %s" % e)

    def broadcast(self, event):
        dead = []
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            if not client.alive or not client.matches(event):
                continue
            try:
                client.send_json({
                    "type": "quote",
                    "event": event,
                })
            except Exception:
                dead.append(client)
        for client in dead:
            self.remove(client)

    def count(self):
        with self._lock:
            return len(self._clients)


WS_QUOTES = WebSocketQuoteManager()


class QuoteSubscriptionStore(object):
    def __init__(self, max_events=1000):
        self.max_events = int(max_events)
        self._lock = threading.RLock()
        self._subscriptions = {}
        self._events = []
        self._seq = 0
        self._callback_registered = False
        self._whole_subscribe_id = None
        self._whole_subscribed_at = 0
        self._idle_release_timer = None

    def start(self):
        with self._lock:
            if self._callback_registered:
                return
            CLIENTS.add_callback("quote", self._on_quote)
            self._callback_registered = True

    def close(self):
        with self._lock:
            if self._callback_registered:
                CLIENTS.remove_callback("quote", self._on_quote)
                self._callback_registered = False

    def subscribe_whole(self, body):
        body = body or {}
        markets = self._normalize_markets(body.get("markets") or body.get("code_list") or ["SH", "SZ"])
        requested_channel = body.get("channel")
        timeout = request_timeout_value(body.get("timeout"), default=12.0)
        started = time.perf_counter()
        self.start()
        with self._lock:
            existing_id = self._whole_subscribe_id
            if existing_id and existing_id in self._subscriptions:
                row = self._subscriptions[existing_id]
                if WS_QUOTES.count() <= 0:
                    self._remove_subscription_locked(existing_id)
                    existing_id = None
                else:
                    self._clear_events_locked(existing_id)
                    row["event_count"] = 0
                    row.pop("last_event_at", None)
                    row["created_at"] = time.time()
                    self._whole_subscribed_at = row["created_at"]
                    self._schedule_idle_release_locked()
                    existing_bridge_id = row.get("bridge_id") or DEFAULT_BRIDGE_ID
                    return {
                        "subscribe_id": existing_id,
                        "bridge_id": existing_bridge_id,
                        "channel": row.get("channel") or "normal",
                        "account_id": row.get("account_id") or "",
                        "account_type": row.get("account_type") or "",
                        "account_key": row.get("account_key") or "",
                        "kind": "whole_quote",
                        "markets": row.get("markets") or markets,
                        "already_subscribed": True,
                        "event_count": row.get("event_count", 0),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
            if existing_id is None:
                self._clear_events_locked(None)
        route = data_provider_request(
            "xtdata.subscribe_whole_quote",
            {"code_list": markets},
            requested_channel=requested_channel,
            default_channel="normal",
            timeout=timeout,
            bridge_id=body.get("bridge_id"),
        )
        result = route["result"]
        bridge_id = route["bridge_id"]
        channel = route["channel"]
        subscribe_id = str(result.get("subscribe_id") if isinstance(result, dict) else result)
        with self._lock:
            self._subscriptions[subscribe_id] = {
                "subscribe_id": subscribe_id,
                "bridge_id": bridge_id,
                "channel": channel,
                "mode": route["mode"],
                "account_id": route.get("data_provider") or "",
                "account_type": route.get("data_provider_account_type") or "",
                "account_key": route.get("data_provider_account_key") or "",
                "kind": "whole_quote",
                "markets": markets,
                "created_at": time.time(),
                "event_count": 0,
                "publish_existing": bool(result.get("publish_existing")) if isinstance(result, dict) else False,
                "internal_subscribe_id": result.get("internal_subscribe_id") if isinstance(result, dict) else None,
            }
            self._whole_subscribe_id = subscribe_id
            self._whole_subscribed_at = time.time()
            self._clear_events_locked(subscribe_id)
            self._schedule_idle_release_locked()
        return {
            "subscribe_id": subscribe_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "account_id": route.get("data_provider") or "",
            "account_type": route.get("data_provider_account_type") or "",
            "account_key": route.get("data_provider_account_key") or "",
            "kind": "whole_quote",
            "markets": markets,
            "already_subscribed": False,
            "publish_existing": bool(result.get("publish_existing")) if isinstance(result, dict) else False,
            "internal_subscribe_id": result.get("internal_subscribe_id") if isinstance(result, dict) else None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def unsubscribe(self, body):
        subscribe_id = str((body or {}).get("subscribe_id") or "").strip()
        if not subscribe_id:
            raise ValueError("subscribe_id is required")
        with self._lock:
            row = dict(self._subscriptions.get(subscribe_id) or {})
        bridge_id = normalize_bridge_id(
            row.get("bridge_id") or (body or {}).get("bridge_id") or DEFAULT_BRIDGE_ID
        )
        channel = row.get("channel") or (body or {}).get("channel") or "normal"
        account_id = row.get("account_id") or ""
        account_type = row.get("account_type") or ""
        account_key = row.get("account_key") or ""
        result = self._request_unsubscribe(
            bridge_id,
            channel,
            subscribe_id,
            account_id=account_id,
            account_type=account_type,
            account_key=account_key,
            timeout=request_timeout_value((body or {}).get("timeout"), default=8.0, maximum=60.0),
        )
        with self._lock:
            self._remove_subscription_locked(subscribe_id)
        return {
            "subscribe_id": subscribe_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "account_id": account_id,
            "account_type": account_type,
            "account_key": account_key,
            "result": result,
        }

    def release_idle_whole_subscription(self, reason="", grace_seconds=0):
        with self._lock:
            subscribe_id = self._whole_subscribe_id
            if not subscribe_id or subscribe_id not in self._subscriptions:
                return {"released": False, "reason": "no whole quote subscription"}
            if WS_QUOTES.count() > 0:
                return {"released": False, "reason": "websocket clients still connected"}
            age = time.time() - (self._whole_subscribed_at or self._subscriptions[subscribe_id].get("created_at", 0))
            if grace_seconds and age < grace_seconds:
                return {"released": False, "reason": "within grace period", "age_seconds": round(age, 2)}
            row = dict(self._subscriptions.get(subscribe_id) or {})
        bridge_id = normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID)
        channel = normalize_channel(row.get("channel"), "normal")
        try:
            result = self._request_unsubscribe(
                bridge_id,
                channel,
                subscribe_id,
                account_id=row.get("account_id") or "",
                account_type=row.get("account_type") or "",
                account_key=row.get("account_key") or "",
                timeout=5.0,
            )
            error = ""
        except Exception as e:
            result = None
            error = str(e)
            safe_print("quote idle release failed subscribe_id=%s reason=%s error=%s" % (subscribe_id, reason, e))
        with self._lock:
            self._remove_subscription_locked(subscribe_id)
        return {
            "released": True,
            "subscribe_id": subscribe_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "reason": reason,
            "result": result,
            "error": error,
        }

    def _request_unsubscribe(self, bridge_id, channel, subscribe_id, account_id="", account_type="", account_key="", timeout=8.0):
        route = account_request(
            account_id,
            bridge_id,
            channel,
            "xtdata.unsubscribe_quote",
            {"subscribe_id": subscribe_id},
            timeout=timeout,
            default_channel="normal",
            ignore_cooldown=True,
            account_type=account_type or "STOCK",
            account_key=account_key,
        )
        return route["result"]

    def _remove_subscription_locked(self, subscribe_id):
        subscribe_id = str(subscribe_id or "")
        self._subscriptions.pop(subscribe_id, None)
        if str(subscribe_id) == str(self._whole_subscribe_id):
            self._whole_subscribe_id = None
            self._whole_subscribed_at = 0
            self._clear_events_locked(subscribe_id)
            self._cancel_idle_release_locked()

    def _clear_events_locked(self, subscribe_id=None):
        if subscribe_id:
            subscribe_id = str(subscribe_id)
            self._events = [
                row for row in self._events
                if str(row.get("subscribe_id") or "") != subscribe_id
            ]
        else:
            self._events = []
            self._seq = 0

    def _schedule_idle_release_locked(self):
        self._cancel_idle_release_locked()
        timer = threading.Timer(
            8.0,
            lambda: self.release_idle_whole_subscription(
                reason="no websocket client after subscribe",
                grace_seconds=0,
            ),
        )
        timer.daemon = True
        self._idle_release_timer = timer
        timer.start()

    def _cancel_idle_release_locked(self):
        timer = self._idle_release_timer
        self._idle_release_timer = None
        if timer:
            try:
                timer.cancel()
            except Exception:
                pass

    def latest(self, since=0, limit=200, subscribe_id=None):
        subscribe_id = str(subscribe_id or "").strip()
        with self._lock:
            rows = [row for row in self._events if row.get("seq", 0) > since]
            if subscribe_id:
                rows = [row for row in rows if str(row.get("subscribe_id") or "") == subscribe_id]
            return rows[-int(limit):]

    def status(self):
        with self._lock:
            return {
                "subscriptions": list(self._subscriptions.values()),
                "whole_subscribe_id": self._whole_subscribe_id,
                "event_count": len(self._events),
                "websocket_clients": WS_QUOTES.count(),
            }

    def _on_quote(self, data):
        event = self._normalize_event(data)
        with self._lock:
            subscribe_id = str(event.get("subscribe_id") or "")
            if subscribe_id and subscribe_id not in self._subscriptions:
                return
            if not subscribe_id and not self._subscriptions:
                return
            self._seq += 1
            event["seq"] = self._seq
            event["received_at"] = time.time()
            if subscribe_id and subscribe_id in self._subscriptions:
                self._subscriptions[subscribe_id]["event_count"] = self._subscriptions[subscribe_id].get("event_count", 0) + 1
                self._subscriptions[subscribe_id]["last_event_at"] = event["received_at"]
            self._events.append(event)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]
        WS_QUOTES.broadcast(event)
        self.release_idle_whole_subscription(reason="no websocket clients during quote", grace_seconds=8)

    def _normalize_event(self, data):
        if not isinstance(data, dict):
            return {"data": data}
        event = dict(data)
        if "data" not in event:
            event = {"data": event}
        payload = event.get("data")
        if isinstance(payload, dict):
            event.setdefault("code_count", len(payload))
        if event.get("subscription_id") is not None and event.get("subscribe_id") is None:
            event["subscribe_id"] = event.get("subscription_id")
        if event.get("subscribe_id") is not None:
            event["subscribe_id"] = str(event.get("subscribe_id"))
        elif event.get("event"):
            name = str(event.get("event") or "")
            if name.startswith("quote:"):
                event["subscribe_id"] = name.split(":", 1)[1]
        return event

    def _normalize_markets(self, value):
        if isinstance(value, str):
            items = [item.strip().upper() for item in value.replace("，", ",").split(",") if item.strip()]
        elif isinstance(value, (list, tuple, set)):
            items = [str(item).strip().upper() for item in value if str(item).strip()]
        else:
            items = []
        result = []
        for item in items or ["SH", "SZ"]:
            if item not in ("SH", "SZ"):
                raise ValueError("markets only supports SH/SZ for whole quote")
            if item not in result:
                result.append(item)
        return result


QUOTES = QuoteSubscriptionStore()


def _release_quote_subscription_on_empty():
    QUOTES.release_idle_whole_subscription(reason="no websocket quote clients", grace_seconds=0)


WS_QUOTES.on_empty = _release_quote_subscription_on_empty


class CallbackEventStore(object):
    def __init__(self, channels=None, max_events=500):
        self.channels = channels or callback_channels()
        self.max_events = int(max_events)
        self._lock = threading.RLock()
        self._events = []
        self._seq = 0
        self._tx = None
        self._thread = None
        self._running = False
        self._pipe_clients = {}
        self._mode = None

    def start(self):
        if self._running:
            return
        self._mode = "mixed"
        self._running = True
        try:
            CLIENTS.add_callback("__event__", self._on_client_event)
        except Exception as e:
            safe_print("cfquant callback CLIENTS listener start failed: %s" % e)
        try:
            pipe_count = self._start_pipe_clients()
            safe_print("cfquant callback pipe listeners started count=%s channels=%s" % (pipe_count, ",".join(self.channels)))
        except Exception as e:
            safe_print("cfquant callback pipe listeners start failed: %s" % e)
        try:
            lttx_count = self._start_lttx_client()
            if lttx_count:
                safe_print("cfquant callback LTtx listener started count=%s channels=%s" % (lttx_count, ",".join(self.channels)))
        except Exception as e:
            safe_print("cfquant callback LTtx listener start failed: %s" % e)
        safe_print("cfquant callback listeners started in mixed mode")

    def close(self):
        self._running = False
        try:
            CLIENTS.remove_callback("__event__", self._on_client_event)
        except Exception:
            pass
        for client in list(self._pipe_clients.values()):
            try:
                client.remove_callback("__event__", self._on_channel_event)
            except Exception:
                pass
            try:
                client.remove_callback("__event__", self._on_client_event)
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
        self._pipe_clients = {}
        tx = self._tx
        self._tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass

    def refresh_channels(self, channels):
        channels = channels or callback_channels()
        mode = "mixed"
        if channels == self.channels and self._running and mode == self._mode:
            return
        self.close()
        self.channels = channels
        self.start()

    def attach_pipe_client(self, client):
        if client is None:
            return
        try:
            client.add_callback("__event__", self._on_client_event)
        except Exception as e:
            safe_print("callback pipe attach failed: %s" % e)

    def detach_pipe_client(self, client):
        if client is None:
            return
        try:
            client.remove_callback("__event__", self._on_client_event)
        except Exception:
            pass

    def latest(self, since=0, limit=200, bridge_id=None, account_id=None, account_type=None, account_key=None, event_name=None, event_prefix=None, job_id=None):
        bridge_id = normalize_bridge_id(bridge_id) if bridge_id else None
        account_id = str(account_id or "").strip()
        account_type = normalize_account_type(account_type) if account_type not in ("", None) else ""
        account_key = str(account_key or "").strip()
        event_name = str(event_name or "").strip()
        event_prefix = str(event_prefix or "").strip()
        job_id = str(job_id or "").strip()
        with self._lock:
            rows = [row for row in self._events if row.get("seq", 0) > since]
            if bridge_id:
                bridge_ids = account_related_bridge_ids(
                    account_id=account_id,
                    account_type=account_type or None,
                    bridge_id=bridge_id,
                    account_key=account_key,
                ) if (account_id or account_key) else [bridge_id]
                rows = [
                    row
                    for row in rows
                    if normalize_bridge_id(self.event_bridge_id_static(row) or "default") in bridge_ids
                ]
            if account_id:
                rows = [
                    row
                    for row in rows
                    if self._event_account_id(row) == account_id
                ]
            if account_type:
                rows = [
                    row
                    for row in rows
                    if self.event_account_type_static(row) in ("", account_type)
                ]
            if event_name:
                rows = [
                    row
                    for row in rows
                    if str(row.get("event") or "") == event_name
                ]
            if event_prefix:
                rows = [
                    row
                    for row in rows
                    if str(row.get("event") or "").startswith(event_prefix)
                ]
            if job_id:
                rows = [
                    row
                    for row in rows
                    if self.event_job_id_static(row) == job_id
                ]
            return rows[-int(limit):]

    def _loop(self):
        while self._running:
            try:
                raw = self._tx.Q.get()
                event = self._parse(raw)
                if event:
                    self._append(event, source="channel")
            except Exception as e:
                if self._running:
                    safe_print("callback listener error: %s" % e)
                time.sleep(0.2)

    def _parse(self, raw):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if not isinstance(raw, str):
            return None
        key, value = raw.split("|", 1) if "|" in raw else ("", raw)
        msg = loads_message(raw)
        if isinstance(msg, dict) and msg.get("type") == "event":
            event = dict(msg)
            event["data"] = decode_value(event.get("data"))
            if key:
                event.setdefault("key", key)
            return event
        try:
            payload = json.loads(value)
        except Exception:
            payload = {"raw": value}
        if isinstance(payload, dict):
            payload.setdefault("key", key)
            return payload
        return {"key": key, "data": payload}

    def _append(self, event, source="client"):
        with self._lock:
            self._seq += 1
            row = dict(event)
            meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
            if not row.get("bridge_id") and meta.get("bridge_id"):
                row["bridge_id"] = meta.get("bridge_id")
            if not row.get("account_id"):
                account_id = self.event_account_id_static(row)
                if account_id:
                    row["account_id"] = account_id
            if not row.get("account_type"):
                account_type = self.event_account_type_static(row)
                if account_type:
                    row["account_type"] = account_type
                else:
                    inferred = self._infer_account_type(row)
                    if inferred:
                        row["account_type"] = inferred
            if row.get("account_id") and row.get("account_type") and row.get("bridge_id") and not row.get("account_key"):
                row["account_key"] = account_key_for(row.get("account_id"), row.get("account_type"), row.get("bridge_id"))
            row["seq"] = self._seq
            row["received_at"] = time.time()
            try:
                RUNTIME_VERSIONS.update_from_event(row)
            except Exception as e:
                safe_print("runtime version report parse failed: %s" % e)
            self._events.append(row)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]
        WS_CALLBACKS.broadcast(row)
        if source == "channel":
            self._forward_to_lttx_route(row)

    def _forward_to_lttx_route(self, row):
        event = str(row.get("event") or "")
        if not event.startswith("trader:"):
            return
        try:
            LTTX_WEB_ROUTE._on_client_event(row)
        except Exception as e:
            safe_print("callback event forward to LTtx route failed event=%s error=%s" % (event, e))

    def _on_client_event(self, event):
        if not isinstance(event, dict):
            return
        if event.get("type") != "event":
            return
        self._append(event, source="client")

    def _normalize_channel_event(self, event):
        data = event.get("data") if isinstance(event, dict) else None
        if not isinstance(data, dict):
            return event
        if data.get("type") != "event" or not data.get("event"):
            return event
        if event.get("event") and data.get("event") != event.get("event"):
            return event
        if not isinstance(data.get("data"), dict):
            return event
        normalized = dict(data)
        if event.get("client_id") and not normalized.get("client_id"):
            normalized["client_id"] = event.get("client_id")
        if event.get("subscription_id") and not normalized.get("subscription_id"):
            normalized["subscription_id"] = event.get("subscription_id")
        if isinstance(event.get("meta"), dict) and not normalized.get("meta"):
            normalized["meta"] = event.get("meta")
        return normalized

    def _on_channel_event(self, event):
        if not isinstance(event, dict):
            return
        if event.get("type") != "event":
            return
        event = self._normalize_channel_event(event)
        self._append(event, source="channel")

    def _start_lttx_client(self):
        channels = [str(channel or "").strip() for channel in self.channels]
        channels = [channel for channel in channels if channel]
        if not channels:
            return 0
        if not lttx_server_reachable():
            safe_print("callback LTtx listener skipped: LTtx server is not reachable")
            return 0
        tx = txl(LTTX_HOST, LTTX_PORT, "LTtx", show=False)
        tx.start_tx()
        tx.start_txg("@".join(channels))
        self._tx = tx
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()
        return len(channels)

    def _start_pipe_clients(self):
        from cfquant.pipe_client import PipeRpcClient

        cfg = get_cfquant_config()
        pipe_name = os.environ.get("CFQUANT_PIPE_NAME") or cfg.get("pipe_name") or DEFAULT_PIPE_NAME
        connect_timeout_ms = cfg.get("pipe_connect_timeout_ms")
        timeout = cfg.get("timeout")
        started = 0
        errors = []
        for channel in self.channels:
            if not channel:
                continue
            client = PipeRpcClient(
                pipe_name=pipe_name,
                request_channel=channel,
                timeout=timeout,
                client_id=channel,
                connect_timeout_ms=connect_timeout_ms,
            )
            try:
                client.start()
                client.add_callback("__event__", self._on_channel_event)
                self._pipe_clients[channel] = client
                started += 1
            except Exception as e:
                errors.append("%s: %s" % (channel, e))
                try:
                    client.close()
                except Exception:
                    pass
                safe_print("callback pipe client start failed channel=%s error=%s" % (channel, e))
        if started <= 0:
            detail = "; ".join(errors)
            raise RuntimeError("no callback pipe clients started%s" % (": " + detail if detail else ""))
        return started

    def _event_account_id(self, event):
        return self.event_account_id_static(event)

    @staticmethod
    def event_account_id_static(event):
        data = event.get("data") if isinstance(event, dict) else {}
        candidates = [
            event.get("account_id"),
            data.get("account_id") if isinstance(data, dict) else None,
            data.get("m_strAccountID") if isinstance(data, dict) else None,
            data.get("m_strAccountId") if isinstance(data, dict) else None,
            data.get("m_strAccount") if isinstance(data, dict) else None,
            data.get("m_accountID") if isinstance(data, dict) else None,
        ]
        for value in candidates:
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def event_account_type_static(event):
        data = event.get("data") if isinstance(event, dict) else {}
        meta = event.get("meta") if isinstance(event, dict) and isinstance(event.get("meta"), dict) else {}
        candidates = [
            event.get("account_type") if isinstance(event, dict) else None,
            meta.get("account_type"),
            data.get("account_type") if isinstance(data, dict) else None,
            data.get("m_nAccountType") if isinstance(data, dict) else None,
            data.get("m_strAccountType") if isinstance(data, dict) else None,
        ]
        for value in candidates:
            if value not in (None, ""):
                try:
                    return normalize_account_type(value)
                except Exception:
                    continue
        return ""

    def _infer_account_type(self, event):
        bridge_id = normalize_bridge_id(self.event_bridge_id_static(event) or DEFAULT_BRIDGE_ID)
        account_id = self.event_account_id_static(event)
        if not account_id:
            return ""
        matches = []
        for config in enabled_account_configs().values():
            if str(config.get("account_id") or "").strip() != account_id:
                continue
            candidate_bridge_ids = [normalize_bridge_id(config.get("bridge_id") or DEFAULT_BRIDGE_ID)]
            if parse_config_bool(config.get("market_routing_enabled"), False):
                market_routes = normalize_market_bridge_config(
                    config.get("market_bridges") or {},
                    account_id=config.get("account_id") or "",
                    account_type=config.get("account_type") or "STOCK",
                    parent_bridge_id=config.get("bridge_id") or DEFAULT_BRIDGE_ID,
                    enabled=True,
                )
                for route in market_routes.values():
                    child_bridge_id = normalize_bridge_id(route.get("bridge_id") or "")
                    if child_bridge_id and child_bridge_id not in candidate_bridge_ids:
                        candidate_bridge_ids.append(child_bridge_id)
            if bridge_id in candidate_bridge_ids:
                matches.append(normalize_account_type(config.get("account_type") or "STOCK"))
        unique = sorted(set(matches))
        return unique[0] if len(unique) == 1 else ""

    @staticmethod
    def event_bridge_id_static(event):
        if not isinstance(event, dict):
            return ""
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        candidates = [
            event.get("bridge_id"),
            meta.get("bridge_id"),
            data.get("bridge_id"),
        ]
        for value in candidates:
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def event_job_id_static(event):
        if not isinstance(event, dict):
            return ""
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        candidates = [
            event.get("job_id"),
            event.get("download_job_id"),
            meta.get("job_id"),
            meta.get("download_job_id"),
            data.get("job_id"),
            data.get("download_job_id"),
        ]
        for value in candidates:
            if value:
                return str(value).strip()
        return ""


CALLBACKS = CallbackEventStore()


def normalize_optional_path(value):
    value = str(value or "").strip().strip('"').strip("'")
    if not value:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))


def safe_print(message):
    line = str(message)
    printed_to_log = False
    try:
        print(line)
        printed_to_log = getattr(sys, "stdout", None) is _LOG_FP
    except Exception:
        pass
    if printed_to_log:
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def cleanup_files_by_age(root_dir, patterns=None, retention_days=LOG_RETENTION_DAYS, recursive=True):
    root_dir = os.path.abspath(root_dir)
    patterns = patterns or ["*"]
    result = {
        "root": root_dir,
        "exists": os.path.isdir(root_dir),
        "patterns": list(patterns),
        "recursive": bool(recursive),
        "scanned_files": 0,
        "kept_files": 0,
        "deleted_files": 0,
        "failed_files": 0,
        "deleted_bytes": 0,
        "errors": [],
    }
    if not result["exists"]:
        return result
    cutoff = time.time() - max(1, int(retention_days)) * 86400
    for current_root, dirs, files in os.walk(root_dir):
        if not recursive:
            dirs[:] = []
        for name in files:
            if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                continue
            path = os.path.join(current_root, name)
            result["scanned_files"] += 1
            try:
                stat_result = os.stat(path)
                if stat_result.st_mtime >= cutoff:
                    result["kept_files"] += 1
                    continue
                size = stat_result.st_size
                os.remove(path)
                result["deleted_files"] += 1
                result["deleted_bytes"] += size
            except Exception as e:
                result["failed_files"] += 1
                result["errors"].append("%s: %s" % (path, e))
    return result


def cleanup_cfquant_local_logs(retention_days=LOG_RETENTION_DAYS):
    targets = [
        (LOG_DIR, ["*.log", "*.csv", "*.txt"], True),
        (BASE_DIR, ["*.log"], False),
        (os.path.join(BASE_DIR, "log_data"), ["*.log", "*.csv", "*.txt"], True),
        (os.path.join(BASE_DIR, "tx_log"), ["*.log", "*.csv", "*.txt"], True),
        (os.path.join(BASE_DIR, "LTtx", "tx", "log_data"), ["*.log", "*.csv", "*.txt"], True),
        (os.path.join(BASE_DIR, "LTtx", "tx", "tx_log"), ["*.log", "*.csv", "*.txt"], True),
    ]
    started = time.time()
    results = [
        cleanup_files_by_age(path, patterns=patterns, retention_days=retention_days, recursive=recursive)
        for path, patterns, recursive in targets
    ]
    return {
        "retention_days": int(retention_days),
        "ran_at": started,
        "ran_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "targets": results,
        "scanned_files": sum(item.get("scanned_files", 0) for item in results),
        "deleted_files": sum(item.get("deleted_files", 0) for item in results),
        "failed_files": sum(item.get("failed_files", 0) for item in results),
        "deleted_bytes": sum(item.get("deleted_bytes", 0) for item in results),
    }


WEB_CONFIG = WebRuntimeConfig(WEB_CONFIG_FILE)
UPDATER = None


def ok(data=None):
    return {"ok": True, "data": to_jsonable(data)}


def fail(error, status=400):
    return {"ok": False, "error": str(error), "status": status}


def to_jsonable(value, depth=0):
    if depth > 40:
        return str(value)
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {
            jsonable_key(key): to_jsonable(row, depth + 1)
            for key, row in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(row, depth + 1) for row in value]

    type_name = value.__class__.__name__
    if type_name == "DataFrame" and hasattr(value, "to_dict"):
        return to_jsonable(value.to_dict(orient="index"), depth + 1)
    if type_name == "Series" and hasattr(value, "to_dict"):
        return to_jsonable(value.to_dict(), depth + 1)

    if hasattr(value, "item"):
        try:
            item = value.item()
            if item is not value:
                return to_jsonable(item, depth + 1)
        except Exception:
            pass
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        try:
            listed = value.tolist()
            if listed is not value:
                return to_jsonable(listed, depth + 1)
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def jsonable_key(value):
    safe = to_jsonable(value)
    if safe is None:
        return ""
    if isinstance(safe, str):
        return safe
    if isinstance(safe, (int, float, bool)):
        return str(safe)
    return str(safe)


def qmt_entry_manual_update_info(entry_files=None, required=False, reason=""):
    entry_files = [str(item) for item in (entry_files or []) if str(item or "").strip()]
    return {
        "required": bool(required),
        "reason": reason or (
            "本次更新包含 QMT 入口脚本变更"
            if required else
            "未检测到 QMT 入口脚本变更"
        ),
        "entry_files": entry_files,
        "message": (
            "QMT 入口启动文件需要用户手动更新后再启动。"
            "QMT 里的入口策略文件通常是加密文件，Web 无法自动覆盖；"
            "请根据当前模式手动更新对应入口文件，然后在 QMT 侧重新启动桥接脚本。"
            if required else
            "本次未检测到 QMT 入口脚本变更；如果只更新了核心包，仍需在 QMT 侧重启正在运行的桥接脚本。"
        ),
        "mode_files": {
            "通用模式": ["CFQUANT_CTYPE_ALL_LOWLAT.py"],
            "极致模式": ["CFQUANT_LITE.py"],
            "高级模式": ["CFQUANT.py", "CFQUANT_TRADE_LOWLAT.py"],
        },
    }


def qmt_restart_required_info(reason="", entry_info=None):
    entry_info = entry_info or qmt_entry_manual_update_info()
    return {
        "required": True,
        "reason": reason or "QMT 核心包已更新",
        "message": (
            "更新已写入文件系统，但 QMT 中正在运行的桥接脚本不会自动加载新代码；"
            "请停止并重新启动对应 QMT 入口脚本。"
        ),
        "entry_manual_update": entry_info,
    }


def qmt_restart_not_required_info(reason="", entry_info=None):
    entry_info = entry_info or qmt_entry_manual_update_info()
    return {
        "required": False,
        "reason": reason or "未检测到需要 QMT 重启的变更",
        "message": "本次 Web 项目更新未检测到 QMT 入口脚本变更，QMT 侧无需因为本次 Web 更新单独重启。",
        "entry_manual_update": entry_info,
    }


def file_content_equal(path_a, path_b):
    try:
        if not os.path.isfile(path_a) or not os.path.isfile(path_b):
            return False
        if os.path.getsize(path_a) != os.path.getsize(path_b):
            return False
        hash_a = hashlib.sha256()
        hash_b = hashlib.sha256()
        with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
            while True:
                chunk_a = fa.read(1024 * 1024)
                chunk_b = fb.read(1024 * 1024)
                if chunk_a != chunk_b:
                    return False
                if not chunk_a:
                    break
                hash_a.update(chunk_a)
                hash_b.update(chunk_b)
        return hash_a.digest() == hash_b.digest()
    except Exception:
        return False


class CfquantUpdater(object):
    BACKUP_KEEP = 2

    def __init__(self, config):
        self.config = config
        self._lock = threading.RLock()
        self._remote_cache = {}
        self._remote_lock = threading.RLock()

    def status(self, bridge_id=None, repo_url=None, ref=None):
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        bridge = bridge_config(bridge_id)
        python_dir = normalize_optional_path(bridge.get("python_dir"))
        _bridge, target_specs, missing_trade = self._configured_target_specs(bridge_id)
        qmt_trade_dir = next(
            (spec.get("python_dir") for spec in target_specs if spec.get("role") == "trade"),
            "",
        )
        repo_url = str(repo_url or DEFAULT_UPDATE_REPO_URL).strip()
        ref = str(ref or DEFAULT_UPDATE_REF).strip()
        result = {
            "bridge_id": bridge_id,
            "bridge_name": bridge.get("name") or bridge_id,
            "python_dir": python_dir,
            "qmt_trade_dir": qmt_trade_dir,
            "advanced_mode": bool(qmt_trade_dir or missing_trade),
            "configured": bool(python_dir),
            "ready": False,
            "errors": [],
            "warnings": [],
            "targets": {},
            "secondary_targets": [],
            "backups": [],
            "current_version": "",
            "runtime_version": "",
            "runtime_reported": False,
            "runtime_report": RUNTIME_VERSIONS.latest(bridge_id),
            "file_version": "",
            "latest_qmt_core_version": "",
            "qmt_builtin_version": "",
            "qmt_saved_report": {},
            "qmt_runtime_stale": False,
            "version_source": "",
            "last_update": {},
            "version_status": self._build_version_status(None, "", {}, repo_url, ref),
            "default_repo_url": repo_url,
            "default_official_site_url": DEFAULT_OFFICIAL_SITE_URL,
            "default_ref": ref,
        }
        if not python_dir:
            result["errors"].append("桥接端未设置 QMT 核心目录")
            return result
        try:
            target = self._target_paths(python_dir)
            result["targets"] = target
            result["backups"] = self._list_backups(target["backup_dir"])
            file_version = self._read_version(target["current_core"])
            runtime_report = refresh_runtime_version_report(bridge_id)
            runtime_version = runtime_report.get("version") if runtime_report.get("reported") else ""
            latest_qmt_version = runtime_report.get("version") if runtime_report.get("has_report") else ""
            result["file_version"] = file_version
            result["runtime_report"] = runtime_report
            result["runtime_reported"] = bool(runtime_report.get("reported"))
            result["runtime_version"] = runtime_version
            result["current_version"] = runtime_version
            result["latest_qmt_core_version"] = latest_qmt_version
            result["qmt_builtin_version"] = latest_qmt_version
            result["qmt_saved_report"] = runtime_report if runtime_report.get("has_report") else {}
            result["qmt_runtime_stale"] = bool(runtime_report.get("stale"))
            result["version_source"] = "qmt_runtime" if runtime_version else ""
            result["last_update"] = self._read_install_meta(target["updates_dir"])
            result["version_status"] = self._build_version_status(
                target,
                result["current_version"],
                result["last_update"],
                repo_url,
                ref,
                runtime_report=runtime_report,
                file_version=file_version,
            )
            if not runtime_version:
                result["warnings"].append(runtime_report.get("message") or "未收到 QMT 运行时版本上报，请先运行对应 QMT 桥接脚本后再查看")
            if not os.path.isdir(target["python_dir"]):
                result["errors"].append("QMT 核心目录不存在: %s" % target["python_dir"])
            if not os.path.isdir(target["project_dir"]):
                result["errors"].append("项目目录不存在: %s" % target["project_dir"])
            if not os.path.isdir(target["current_core"]):
                result["errors"].append("核心代码目录不存在: %s" % target["current_core"])
            if os.path.isfile(target["entry_file"]):
                result["entry_file"] = target["entry_file"]
            else:
                result["warnings"].append("未找到 QMT 入口脚本 CFQUANT.py，核心包更新仍可继续")
            for spec in target_specs[1:]:
                secondary_dir = normalize_optional_path(spec.get("python_dir"))
                secondary_status = {
                    "role": spec.get("role") or "trade",
                    "python_dir": secondary_dir,
                    "account_keys": list(spec.get("account_keys") or []),
                    "ready": False,
                    "errors": [],
                }
                if not secondary_dir:
                    secondary_status["errors"].append("高级模式未设置极速交易端 QMT 核心目录")
                else:
                    secondary_target = self._target_paths(secondary_dir)
                    secondary_status.update({
                        "configured_dir": secondary_target.get("configured_dir"),
                        "resolved_python_dir": secondary_target.get("python_dir"),
                        "project_dir": secondary_target.get("project_dir"),
                        "current_core": secondary_target.get("current_core"),
                    })
                    if not os.path.isdir(secondary_target["python_dir"]):
                        secondary_status["errors"].append(
                            "极速交易端 QMT 核心目录不存在: %s" % secondary_target["python_dir"]
                        )
                    if not os.path.isdir(secondary_target["project_dir"]):
                        secondary_status["errors"].append(
                            "极速交易端项目目录不存在: %s" % secondary_target["project_dir"]
                        )
                    if not os.path.isdir(secondary_target["current_core"]):
                        secondary_status["errors"].append(
                            "极速交易端核心代码目录不存在: %s" % secondary_target["current_core"]
                        )
                secondary_status["ready"] = not secondary_status["errors"]
                result["secondary_targets"].append(secondary_status)
                result["errors"].extend(secondary_status["errors"])
            for item in missing_trade:
                result["errors"].append(
                    "高级模式账号 %s 未设置极速交易端 QMT 核心目录"
                    % (item.get("account_id") or item.get("account_key") or "unknown")
                )
            result["ready"] = not result["errors"]
        except Exception as e:
            result["errors"].append(str(e))
        return result

    def update_from_github(self, bridge_id, repo_url, ref=""):
        repo_url = str(repo_url or "").strip()
        ref = str(ref or "").strip()
        if not repo_url:
            raise ValueError("repo_url is required")
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="cfquant_update_") as work_dir:
                source_dir = os.path.join(work_dir, "source")
                fetched = self._fetch_github(repo_url, ref, source_dir)
                return self._install_source(bridge_id, source_dir, {
                    "source": "github",
                    "repo_url": repo_url,
                    "ref": ref,
                    "fetch": fetched,
                })

    def update_from_official(self, bridge_id, site_url="", fallback_repo_url="", fallback_ref=""):
        site_url = normalize_official_site_url(site_url)
        fallback_repo_url = str(fallback_repo_url or DEFAULT_UPDATE_REPO_URL).strip()
        fallback_ref = str(fallback_ref or DEFAULT_UPDATE_REF).strip()
        official_error = ""
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="cfquant_update_") as work_dir:
                source_dir = os.path.join(work_dir, "source")
                try:
                    fetched = self._fetch_official_package(site_url, source_dir)
                    return self._install_source(bridge_id, source_dir, {
                        "source": "official_site",
                        "site_url": site_url or DEFAULT_OFFICIAL_SITE_URL,
                        "fetch": fetched,
                    })
                except Exception as e:
                    official_error = str(e) or repr(e)
                    safe_print("official site update failed, fallback to GitHub: %s" % official_error)
                if not fallback_repo_url:
                    raise RuntimeError("官网下载失败且未配置 GitHub 回退源: %s" % official_error)
                source_dir = os.path.join(work_dir, "github_source")
                fetched = self._fetch_github(fallback_repo_url, fallback_ref, source_dir)
                return self._install_source(bridge_id, source_dir, {
                    "source": "github_fallback",
                    "repo_url": fallback_repo_url,
                    "ref": fallback_ref,
                    "official_site_error": official_error,
                    "fetch": fetched,
                })

    def update_from_zip(self, bridge_id, filename, content):
        content = content or b""
        if not content:
            raise ValueError("zip content is empty")
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="cfquant_update_") as work_dir:
                zip_path = os.path.join(work_dir, "upload.zip")
                with open(zip_path, "wb") as f:
                    f.write(content)
                source_dir = os.path.join(work_dir, "source")
                self._safe_extract_zip(zip_path, source_dir)
                return self._install_source(bridge_id, source_dir, {
                    "source": "zip",
                    "filename": filename,
                    "size": len(content),
                })

    def install_local_core_to_qmt_dir(
        self,
        qmt_dir,
        bridge_id=None,
        qmt_role="normal",
        account_keys=None,
        source_dir=None,
    ):
        configured_dir = normalize_optional_path(qmt_dir)
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        result = {
            "bridge_id": bridge_id,
            "qmt_role": str(qmt_role or "normal"),
            "account_keys": list(account_keys or []),
            "configured_dir": configured_dir,
            "qmt_dir": configured_dir,
            "python_dir": "",
            "project_dir": "",
            "current_core": "",
            "source_core": "",
            "updated": False,
            "skipped": False,
            "backup": None,
            "removed_backups": [],
            "current_version": "",
            "qmt_restart_required": qmt_restart_not_required_info(
                reason="尚未执行 QMT 核心包自动复制"
            ),
            "error": "",
            "warning": "",
            "message": "",
        }
        if not configured_dir:
            result.update({
                "skipped": True,
                "warning": "QMT 目录未填写，已跳过 cfquant 核心包自动复制",
                "message": "QMT 目录未填写，已跳过 cfquant 核心包自动复制",
            })
            return result

        target = None
        current = ""
        temp_new = ""
        backup = None
        installed = False
        try:
            with self._lock:
                target = self._target_paths(configured_dir)
                target["bridge_id"] = bridge_id
                target["qmt_role"] = str(qmt_role or "normal")
                target["account_keys"] = list(account_keys or [])
                result.update({
                    "python_dir": target.get("python_dir") or "",
                    "project_dir": target.get("project_dir") or "",
                    "current_core": target.get("current_core") or "",
                    "script_dir": target.get("script_dir") or "",
                    "layout": target.get("layout") or "",
                })
                python_dir = normalize_optional_path(target.get("python_dir"))
                if not python_dir or not os.path.isdir(python_dir):
                    raise RuntimeError("QMT 核心目录不存在: %s" % (python_dir or configured_dir))
                if os.path.basename(os.path.normpath(python_dir)).lower() != "bin.x64":
                    raise RuntimeError(
                        "自动复制仅支持 QMT 的 bin.x64 目录，请填写 QMT 安装目录或 bin.x64: %s"
                        % python_dir
                    )

                source_root = normalize_optional_path(source_dir or BASE_DIR)
                source_core = self._find_source_core(source_root)
                if not source_core:
                    raise RuntimeError("本地项目中未找到 cfquant 核心目录: %s" % source_root)
                self._validate_core_dir(source_core)
                result["source_core"] = source_core

                current = target["current_core"]
                if os.path.isfile(current):
                    raise RuntimeError("目标路径已存在但不是目录: %s" % current)
                if self._core_content_equal(source_core, current):
                    result.update({
                        "skipped": True,
                        "current_version": self._read_version(current),
                        "qmt_restart_required": qmt_restart_not_required_info(
                            reason="QMT 核心包已是当前项目版本"
                        ),
                        "message": "QMT 核心包已是当前项目版本，无需重复复制",
                    })
                    return result

                os.makedirs(target["updates_dir"], exist_ok=True)
                os.makedirs(target["backup_dir"], exist_ok=True)
                if os.path.isdir(current):
                    backup = self._backup_current_core(target, label="auto")
                temp_new = os.path.join(
                    target["updates_dir"],
                    "new_core_%s_%s" % (self._timestamp(), str(qmt_role or "normal")),
                )
                self._copy_core(source_core, temp_new)
                if os.path.isdir(current):
                    self._remove_tree(current)
                os.replace(temp_new, current)
                installed = True
                meta = {
                    "source": "local_account_binding",
                    "reason": "保存账号配置时自动复制 cfquant 核心包",
                    "bridge_id": bridge_id,
                    "qmt_role": str(qmt_role or "normal"),
                }
                self._write_install_meta(target, meta, source_core, backup)
                removed = self._prune_backups(target["backup_dir"])
                result.update({
                    "updated": True,
                    "backup": backup,
                    "removed_backups": removed,
                    "current_version": self._read_version(current),
                    "qmt_restart_required": qmt_restart_required_info(
                        reason="QMT 核心包自动复制完成",
                        entry_info=qmt_entry_manual_update_info(
                            reason="账号保存只自动复制 cfquant 核心包，不会覆盖 QMT 入口策略文件"
                        ),
                    ),
                    "message": "cfquant 核心包已自动复制到 %s" % current,
                })
                return result
        except Exception as e:
            try:
                if temp_new:
                    self._remove_tree(temp_new)
                if backup:
                    self._restore_backup_dir(backup, current)
                elif installed and not backup and current:
                    self._remove_tree(current)
            except Exception as restore_error:
                safe_print("cfquant auto deploy cleanup failed: %s" % restore_error)
            result["error"] = str(e)
            result["qmt_restart_required"] = qmt_restart_not_required_info(
                reason="QMT 核心包自动复制失败"
            )
            result["message"] = "cfquant 核心包自动复制失败: %s" % e
            safe_print(
                "cfquant QMT core auto deploy failed bridge_id=%s role=%s qmt_dir=%s error=%s"
                % (bridge_id, qmt_role, configured_dir, e)
            )
            return result

    def _rollback_legacy(self, bridge_id, backup_name=None):
        with self._lock:
            target = self._require_ready_target(bridge_id)
            backups = self._list_backups(target["backup_dir"])
            if not backups:
                raise RuntimeError("没有可回滚的备份")
            if backup_name:
                backup_name = os.path.basename(str(backup_name))
                selected = next((row for row in backups if row["name"] == backup_name), None)
                if selected is None:
                    raise RuntimeError("backup not found: %s" % backup_name)
            else:
                selected = backups[0]
            current = target["current_core"]
            rollback_backup = self._backup_current_core(target, label="rollback")
            restored = False
            try:
                if os.path.isdir(current):
                    self._remove_tree(current)
                shutil.copytree(selected["path"], current, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                restored = True
            except Exception:
                if not restored:
                    self._restore_backup_dir(rollback_backup, current)
                raise
            removed = self._prune_backups(target["backup_dir"])
            entry_info = qmt_entry_manual_update_info(reason="QMT 核心包回滚未检测入口脚本变更")
            return {
                "bridge_id": target["bridge_id"],
                "python_dir": target["python_dir"],
                "restored_backup": selected,
                "rollback_backup": rollback_backup,
                "removed_backups": removed,
                "current_version": self._read_version(current),
                "backups": self._list_backups(target["backup_dir"]),
                "qmt_restart_required": qmt_restart_required_info(
                    reason="QMT 核心包已回滚",
                    entry_info=entry_info,
                ),
                "entry_manual_update": entry_info,
            }

    def rollback(self, bridge_id, backup_name=None):
        with self._lock:
            targets = self._require_ready_targets(bridge_id)
            selected_name = os.path.basename(str(backup_name)) if backup_name else ""
            primary_backups = self._list_backups(targets[0]["backup_dir"])
            if not primary_backups:
                raise RuntimeError("没有可回滚的备份: %s" % targets[0]["python_dir"])
            primary_selected = next(
                (row for row in primary_backups if row["name"] == selected_name),
                None,
            ) if selected_name else primary_backups[0]
            if primary_selected is None:
                raise RuntimeError("backup not found: %s" % selected_name)
            primary_index = primary_backups.index(primary_selected)
            selected_rows = []
            for index, target in enumerate(targets):
                backups = self._list_backups(target["backup_dir"])
                if not backups:
                    raise RuntimeError("没有可回滚的备份: %s" % target["python_dir"])
                if index == 0:
                    selected = primary_selected
                elif selected_name:
                    selected = next(
                        (row for row in backups if row["name"] == selected_name),
                        None,
                    )
                    if selected is None and primary_index < len(backups):
                        selected = backups[primary_index]
                else:
                    selected = backups[0]
                if selected is None:
                    raise RuntimeError(
                        "backup not found for %s: %s" % (target["python_dir"], selected_name)
                    )
                selected_rows.append((target, selected))
            rollback_rows = []
            try:
                for target, selected in selected_rows:
                    current = target["current_core"]
                    rollback_backup = self._backup_current_core(target, label="rollback")
                    try:
                        if os.path.isdir(current):
                            self._remove_tree(current)
                        shutil.copytree(
                            selected["path"],
                            current,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                        )
                        rollback_rows.append((target, selected, rollback_backup))
                    except Exception:
                        self._restore_backup_dir(rollback_backup, current)
                        raise
            except Exception:
                for target, _selected, rollback_backup in reversed(rollback_rows):
                    self._restore_backup_dir(rollback_backup, target["current_core"])
                raise
            primary_target, primary_selected, primary_rollback = rollback_rows[0]
            target_results = [
                {
                    "qmt_role": target.get("qmt_role") or "normal",
                    "account_keys": list(target.get("account_keys") or []),
                    "python_dir": target["python_dir"],
                    "configured_dir": target.get("configured_dir"),
                    "restored_backup": selected,
                    "rollback_backup": rollback_backup,
                    "current_version": self._read_version(target["current_core"]),
                    "backups": self._list_backups(target["backup_dir"]),
                }
                for target, selected, rollback_backup in rollback_rows
            ]
            removed = []
            for target, _selected, _rollback_backup in rollback_rows:
                removed.extend(self._prune_backups(target["backup_dir"]))
            entry_info = qmt_entry_manual_update_info(
                reason="QMT 核心包回滚未检测入口脚本变更"
            )
            return {
                "bridge_id": primary_target["bridge_id"],
                "python_dir": primary_target["python_dir"],
                "qmt_trade_dir": (
                    targets[1].get("configured_dir") if len(targets) > 1 else ""
                ),
                "restored_backup": primary_selected,
                "rollback_backup": primary_rollback,
                "removed_backups": removed,
                "current_version": self._read_version(primary_target["current_core"]),
                "backups": self._list_backups(primary_target["backup_dir"]),
                "target_results": target_results,
                "qmt_restart_required": qmt_restart_required_info(
                    reason="QMT 核心包已回滚",
                    entry_info=entry_info,
                ),
                "entry_manual_update": entry_info,
            }

    def _target_paths(self, python_dir):
        configured_dir = normalize_optional_path(python_dir)
        python_dir = self._resolve_qmt_core_dir(configured_dir)
        script_dir = self._resolve_qmt_script_dir(configured_dir, python_dir)
        single_project_dir = python_dir
        single_core = os.path.join(python_dir, "cfquant")
        legacy_project_dir = os.path.join(python_dir, "cfquant")
        legacy_core = os.path.join(legacy_project_dir, "cfquant")
        if self._looks_like_core(single_core):
            layout = "single"
            project_dir = single_project_dir
            current_core = single_core
            updates_dir = os.path.join(python_dir, ".cfquant_updates")
        elif self._looks_like_core(legacy_core):
            layout = "nested"
            project_dir = legacy_project_dir
            current_core = legacy_core
            updates_dir = os.path.join(legacy_project_dir, ".updates")
        else:
            layout = "single"
            project_dir = single_project_dir
            current_core = single_core
            updates_dir = os.path.join(python_dir, ".cfquant_updates")
        return {
            "layout": layout,
            "configured_dir": configured_dir,
            "python_dir": python_dir,
            "script_dir": script_dir,
            "project_dir": project_dir,
            "current_core": current_core,
            "updates_dir": updates_dir,
            "backup_dir": os.path.join(updates_dir, "backups"),
            "entry_file": os.path.join(script_dir or python_dir, "CFQUANT.py"),
        }

    def _resolve_qmt_core_dir(self, configured_dir):
        configured_dir = normalize_optional_path(configured_dir)
        if not configured_dir:
            return ""
        base_name = os.path.basename(configured_dir).lower()
        if base_name == "python":
            sibling_bin = os.path.join(os.path.dirname(configured_dir), "bin.x64")
            if os.path.isdir(sibling_bin):
                return sibling_bin
        child_bin = os.path.join(configured_dir, "bin.x64")
        if os.path.isdir(child_bin):
            return child_bin
        return configured_dir

    def _resolve_qmt_script_dir(self, configured_dir, core_dir):
        configured_dir = normalize_optional_path(configured_dir)
        core_dir = normalize_optional_path(core_dir)
        if not configured_dir:
            return ""
        if os.path.basename(configured_dir).lower() == "python":
            return configured_dir
        sibling_python = os.path.join(os.path.dirname(core_dir or configured_dir), "python")
        if os.path.isdir(sibling_python):
            return sibling_python
        child_python = os.path.join(configured_dir, "python")
        if os.path.isdir(child_python):
            return child_python
        return configured_dir

    def _path_key(self, path):
        path = normalize_optional_path(path)
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(os.path.normpath(path)))

    def _configured_target_specs(self, bridge_id):
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        bridge = bridge_config(bridge_id)
        primary_dir = normalize_optional_path(bridge.get("python_dir"))
        specs = [{
            "role": "normal",
            "python_dir": primary_dir,
            "account_keys": [],
        }]
        missing_trade = []
        configs = self.config.account_configs() if self.config is not None else {}
        seen_dirs = {self._path_key(primary_dir)} if primary_dir else set()
        for account_key, row in configs.items():
            if not isinstance(row, dict):
                continue
            if normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID) != bridge_id:
                continue
            if row.get("enabled", True) is False:
                continue
            if normalize_transport_mode(row.get("mode") or "ctypes") != "lttx":
                continue
            trade_dir = normalize_optional_path(
                row.get("qmt_trade_dir")
                or row.get("trade_qmt_dir")
                or row.get("advanced_qmt_dir")
                or row.get("qmt_trade_core_dir")
            )
            if not trade_dir:
                missing_trade.append({
                    "account_key": str(account_key or ""),
                    "account_id": str(row.get("account_id") or ""),
                })
                continue
            trade_key = self._path_key(trade_dir)
            if trade_key in seen_dirs:
                if trade_key == self._path_key(primary_dir):
                    missing_trade.append({
                        "account_key": str(account_key or ""),
                        "account_id": str(row.get("account_id") or ""),
                        "reason": "trade directory is the same as normal directory",
                    })
                else:
                    for spec in specs:
                        if self._path_key(spec.get("python_dir")) == trade_key:
                            spec.setdefault("account_keys", []).append(str(account_key or ""))
                            break
                continue
            seen_dirs.add(trade_key)
            specs.append({
                "role": "trade",
                "python_dir": trade_dir,
                "account_keys": [str(account_key or "")],
                "account_id": str(row.get("account_id") or ""),
            })
        return bridge, specs, missing_trade

    def _require_ready_targets(self, bridge_id):
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        _bridge, specs, missing_trade = self._configured_target_specs(bridge_id)
        if not specs or not specs[0].get("python_dir"):
            raise RuntimeError("桥接端未设置 QMT 核心目录")
        if missing_trade:
            accounts = ", ".join(
                item.get("account_id") or item.get("account_key") or "unknown"
                for item in missing_trade
            )
            raise RuntimeError("高级模式需要设置独立的极速交易端 QMT 核心目录: %s" % accounts)
        targets = []
        for spec in specs:
            target = self._target_paths(spec.get("python_dir"))
            target["bridge_id"] = bridge_id
            target["qmt_role"] = spec.get("role") or "normal"
            target["account_keys"] = list(spec.get("account_keys") or [])
            target["account_id"] = spec.get("account_id") or ""
            if not os.path.isdir(target["python_dir"]):
                raise RuntimeError("QMT 核心目录不存在: %s" % target["python_dir"])
            if not os.path.isdir(target["project_dir"]):
                raise RuntimeError("项目目录不存在: %s" % target["project_dir"])
            if not os.path.isdir(target["current_core"]):
                raise RuntimeError("核心代码目录不存在: %s" % target["current_core"])
            targets.append(target)
        return targets

    def _require_ready_target(self, bridge_id):
        return self._require_ready_targets(bridge_id)[0]

    def _require_ready_target_legacy(self, bridge_id):
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        bridge = bridge_config(bridge_id)
        python_dir = normalize_optional_path(bridge.get("python_dir"))
        if not python_dir:
            raise RuntimeError("桥接端未设置 QMT 核心目录")
        target = self._target_paths(python_dir)
        target["bridge_id"] = bridge_id
        if not os.path.isdir(target["python_dir"]):
            raise RuntimeError("QMT 核心目录不存在: %s" % target["python_dir"])
        if not os.path.isdir(target["project_dir"]):
            raise RuntimeError("项目目录不存在: %s" % target["project_dir"])
        if not os.path.isdir(target["current_core"]):
            raise RuntimeError("核心代码目录不存在: %s" % target["current_core"])
        return target

    def _install_source_legacy(self, bridge_id, source_dir, meta):
        target = self._require_ready_target(bridge_id)
        source_core = self._find_source_core(source_dir)
        if not source_core:
            raise RuntimeError("源码中未找到 cfquant 核心目录")
        self._validate_core_dir(source_core)
        entry_info = self._entry_update_info(source_dir)
        os.makedirs(target["backup_dir"], exist_ok=True)
        backup = self._backup_current_core(target)
        temp_new = os.path.join(target["updates_dir"], "new_core_%s" % self._timestamp())
        current = target["current_core"]
        installed = False
        try:
            self._copy_core(source_core, temp_new)
            if os.path.isdir(current):
                self._remove_tree(current)
            os.replace(temp_new, current)
            installed = True
            self._write_install_meta(target, meta, source_core, backup)
            removed = self._prune_backups(target["backup_dir"])
            return {
                "bridge_id": target["bridge_id"],
                "layout": target.get("layout"),
                "python_dir": target["python_dir"],
                "updated": True,
                "source": meta,
                "source_core": source_core,
                "backup": backup,
                "removed_backups": removed,
                "current_version": self._read_version(current),
                "backups": self._list_backups(target["backup_dir"]),
                "qmt_restart_required": qmt_restart_required_info(
                    reason="QMT 核心包已更新",
                    entry_info=entry_info,
                ),
                "entry_manual_update": entry_info,
            }
        except Exception:
            if not installed:
                self._remove_tree(temp_new)
            else:
                self._remove_tree(temp_new)
            self._restore_backup_dir(backup, current)
            raise

    def _install_source(self, bridge_id, source_dir, meta):
        targets = self._require_ready_targets(bridge_id)
        source_core = self._find_source_core(source_dir)
        if not source_core:
            raise RuntimeError("源码中未找到 cfquant 核心目录")
        self._validate_core_dir(source_core)
        entry_info = self._entry_update_info(source_dir)
        target_results = []
        completed = []
        try:
            for target in targets:
                os.makedirs(target["backup_dir"], exist_ok=True)
                backup = self._backup_current_core(target)
                temp_new = os.path.join(
                    target["updates_dir"],
                    "new_core_%s_%s" % (self._timestamp(), target.get("qmt_role") or "normal"),
                )
                current = target["current_core"]
                try:
                    self._copy_core(source_core, temp_new)
                    if os.path.isdir(current):
                        self._remove_tree(current)
                    os.replace(temp_new, current)
                    self._write_install_meta(target, meta, source_core, backup)
                    removed = self._prune_backups(target["backup_dir"])
                    result = {
                        "qmt_role": target.get("qmt_role") or "normal",
                        "account_keys": list(target.get("account_keys") or []),
                        "bridge_id": target["bridge_id"],
                        "layout": target.get("layout"),
                        "python_dir": target["python_dir"],
                        "configured_dir": target.get("configured_dir"),
                        "updated": True,
                        "source": meta,
                        "source_core": source_core,
                        "backup": backup,
                        "removed_backups": removed,
                        "current_version": self._read_version(current),
                        "backups": self._list_backups(target["backup_dir"]),
                    }
                    target_results.append(result)
                    completed.append((target, backup))
                except Exception:
                    self._remove_tree(temp_new)
                    self._restore_backup_dir(backup, current)
                    raise
        except Exception:
            for target, backup in reversed(completed):
                self._restore_backup_dir(backup, target["current_core"])
            raise
        primary = target_results[0]
        return {
            "bridge_id": primary["bridge_id"],
            "layout": primary.get("layout"),
            "python_dir": primary["python_dir"],
            "qmt_trade_dir": (
                targets[1].get("configured_dir") if len(targets) > 1 else ""
            ),
            "updated": True,
            "updated_targets": [row.get("python_dir") for row in target_results],
            "target_results": target_results,
            "source": meta,
            "source_core": source_core,
            "backup": primary["backup"],
            "removed_backups": primary["removed_backups"],
            "current_version": primary["current_version"],
            "backups": primary["backups"],
            "qmt_restart_required": qmt_restart_required_info(
                reason="QMT 核心包已更新",
                entry_info=entry_info,
            ),
            "entry_manual_update": entry_info,
        }

    def _build_version_status(self, target, current_version, last_update, repo_url, ref, runtime_report=None, file_version=""):
        current = self._current_version_info(target, current_version, last_update, runtime_report=runtime_report, file_version=file_version)
        remote = self._remote_version_info(repo_url, ref)
        matches_remote = None
        compare_version = current.get("runtime_version") or current.get("latest_qmt_core_version") or ""
        version_comparison = _compare_project_versions(compare_version, remote.get("version"))
        runtime_comparison = _compare_project_versions(current.get("runtime_version"), remote.get("version"))
        saved_qmt_comparison = _compare_project_versions(current.get("latest_qmt_core_version"), remote.get("version"))
        file_comparison = _compare_project_versions(current.get("file_version"), remote.get("version"))
        current_commit = (current.get("commit") or "").lower()
        remote_commit = (remote.get("commit") or "").lower()
        if current_commit and remote_commit:
            matches_remote = current_commit == remote_commit
        elif remote.get("version") and compare_version:
            matches_remote = version_comparison == "same"
        return {
            "current": current,
            "remote": remote,
            "matches_remote": matches_remote,
            "comparison": version_comparison,
            "runtime_comparison": runtime_comparison,
            "saved_qmt_comparison": saved_qmt_comparison,
            "file_comparison": file_comparison,
            "compare_version": compare_version,
            "compare_source": "qmt_runtime" if current.get("runtime_version") else ("qmt_saved_report" if current.get("latest_qmt_core_version") else ""),
        }

    def _current_version_info(self, target, current_version, last_update, runtime_report=None, file_version=""):
        last_update = last_update if isinstance(last_update, dict) else {}
        runtime_report = runtime_report if isinstance(runtime_report, dict) else {}
        source = last_update.get("source") if isinstance(last_update.get("source"), dict) else {}
        fetch = source.get("fetch") if isinstance(source.get("fetch"), dict) else {}
        commit = str(fetch.get("commit") or source.get("commit") or last_update.get("commit") or "").strip()
        source_name = "last_update" if commit else ""
        if not commit and target:
            commit = self._git_commit_near(target.get("project_dir") or target.get("python_dir") or "")
            if commit:
                source_name = "git"
        updated_at_text = str(last_update.get("updated_at_text") or "").strip()
        runtime_version = str(current_version or "").strip()
        runtime_reported = bool(runtime_report.get("reported") and runtime_report.get("version"))
        latest_qmt_core_version = str(runtime_report.get("version") or "").strip() if runtime_report.get("has_report") else ""
        return {
            "version": runtime_version,
            "runtime_version": runtime_version,
            "runtime_reported": runtime_reported,
            "runtime_report": runtime_report,
            "file_version": str(file_version or "").strip(),
            "latest_qmt_core_version": latest_qmt_core_version,
            "qmt_builtin_version": latest_qmt_core_version,
            "qmt_saved_reported_at_text": runtime_report.get("reported_at_text") or "",
            "qmt_runtime_stale": bool(runtime_report.get("stale")),
            "commit": commit,
            "short_commit": self._short_commit(commit),
            "source": "qmt_runtime" if runtime_reported else source_name,
            "updated_at_text": updated_at_text,
            "message": (
                "QMT 运行时版本已上报"
                if runtime_reported else
                (runtime_report.get("message") or "未收到 QMT 运行时版本上报，请先运行对应 QMT 桥接脚本后再查看")
            ),
        }

    def _remote_version_info(self, repo_url, ref):
        repo_url = str(repo_url or "").strip()
        ref = str(ref or "").strip()
        site_url = normalize_official_site_url()
        cache_key = "%s#%s#%s" % (site_url, repo_url, ref)
        now = time.time()
        with self._remote_lock:
            cached = self._remote_cache.get(cache_key)
            if cached and now - float(cached.get("checked_at") or 0) < UPDATE_REMOTE_CACHE_SECONDS:
                result = dict(cached)
                result["cached"] = True
                return result
        result = {
            "repo_url": repo_url,
            "ref": ref,
            "remote_ref": "",
            "version": "",
            "core_version": "",
            "web_version": "",
            "commit": "",
            "short_commit": "",
            "checked_at": now,
            "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "cached": False,
            "error": "",
            "source": "",
            "site_url": site_url,
            "download_url": "",
            "sha256": "",
            "fallback_error": "",
        }
        try:
            release = official_release_info(site_url)
            core_version = str(release.get("core_version") or release.get("version") or "")
            result.update({
                "version": core_version,
                "core_version": core_version,
                "web_version": str(release.get("web_version") or ""),
                "source": "cfquant.org",
                "download_url": str(release.get("download_url") or ""),
                "sha256": str(release.get("sha256") or ""),
                "checked_at": now,
                "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "error": "" if release.get("version") else "官网未返回版本号",
            })
        except Exception as e:
            result["fallback_error"] = str(e) or repr(e)
        if result.get("error") or not result.get("version"):
            if not repo_url:
                result["error"] = "官网不可用且未配置 GitHub 仓库: %s" % (result.get("fallback_error") or "")
            else:
                result.update(self._github_remote_version_info(repo_url, ref, now, result.get("fallback_error") or ""))
        with self._remote_lock:
            self._remote_cache[cache_key] = dict(result)
        return result

    def _github_remote_version_info(self, repo_url, ref, now, official_error=""):
        result = {
            "repo_url": repo_url,
            "ref": ref,
            "remote_ref": "",
            "version": "",
            "commit": "",
            "short_commit": "",
            "checked_at": now,
            "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "cached": False,
            "error": "",
            "source": "github",
            "site_url": normalize_official_site_url(),
            "download_url": "",
            "sha256": "",
            "fallback_error": official_error,
        }
        if not repo_url:
            result["error"] = "未配置 GitHub 仓库"
            return result
        errors = []
        for ref_name in self._remote_ref_candidates(ref):
            try:
                completed = subprocess.run(
                    ["git", "ls-remote", repo_url, ref_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=UPDATE_REMOTE_TIMEOUT_SECONDS,
                    **_hidden_subprocess_kwargs()
                )
                output = (completed.stdout or "").strip()
                if completed.returncode == 0 and output:
                    first = output.splitlines()[0].split()
                    if first:
                        result["commit"] = first[0]
                        result["short_commit"] = self._short_commit(first[0])
                        result["remote_ref"] = first[1] if len(first) > 1 else ref_name
                        result["source"] = "github"
                        break
                message = (completed.stderr or completed.stdout or "").strip()
                errors.append("%s: %s" % (ref_name, message or ("exit %s" % completed.returncode)))
            except Exception as e:
                errors.append("%s: %s" % (ref_name, str(e) or repr(e)))
        if not result["commit"]:
            result["error"] = "; ".join(errors) or "未获取到远端版本"
        return result

    def _remote_ref_candidates(self, ref):
        ref = str(ref or "").strip()
        if not ref:
            return ["HEAD"]
        candidates = []
        if ref.startswith("refs/"):
            candidates.append(ref)
        else:
            candidates.extend(["refs/heads/%s" % ref, "refs/tags/%s^{}" % ref, "refs/tags/%s" % ref, ref])
        result = []
        for item in candidates:
            if item not in result:
                result.append(item)
        return result

    def _git_commit_near(self, path):
        path = normalize_optional_path(path)
        if not path:
            return ""
        current = os.path.abspath(path)
        if os.path.isfile(current):
            current = os.path.dirname(current)
        for _ in range(8):
            if os.path.isdir(os.path.join(current, ".git")):
                try:
                    completed = subprocess.run(
                        ["git", "-C", current, "rev-parse", "HEAD"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=10,
                        **_hidden_subprocess_kwargs()
                    )
                    if completed.returncode == 0:
                        return (completed.stdout or "").strip()
                except Exception:
                    return ""
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return ""

    def _short_commit(self, commit):
        commit = str(commit or "").strip()
        return commit[:7] if len(commit) >= 7 else commit

    def _fetch_github(self, repo_url, ref, output_dir):
        errors = []
        clone_cmd = ["git", "clone", "--depth", "1"]
        if ref:
            clone_cmd.extend(["--branch", ref])
        clone_cmd.extend([repo_url, output_dir])
        try:
            completed = subprocess.run(
                clone_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                **_hidden_subprocess_kwargs()
            )
            if completed.returncode == 0:
                return {
                    "method": "git",
                    "commit": self._git_current_commit(output_dir),
                    "stdout": completed.stdout[-1000:],
                    "stderr": completed.stderr[-1000:],
                }
            git_error = (completed.stderr or completed.stdout or "").strip()
            errors.append("git clone: %s" % (git_error or ("exit %s" % completed.returncode)))
            safe_print("git clone failed: %s" % git_error)
        except Exception as e:
            message = str(e) or repr(e)
            errors.append("git clone: %s" % message)
            safe_print("git clone unavailable: %s" % message)
        owner, repo = self._parse_github_repo(repo_url)
        owner_q = urllib.parse.quote(owner)
        repo_q = urllib.parse.quote(repo)
        if ref:
            ref_q = urllib.parse.quote(ref)
            candidates = [
                ("zip-codeload-heads", "https://codeload.github.com/%s/%s/zip/refs/heads/%s" % (owner_q, repo_q, ref_q)),
                ("zip-codeload-tags", "https://codeload.github.com/%s/%s/zip/refs/tags/%s" % (owner_q, repo_q, ref_q)),
                ("zip-heads", "https://github.com/%s/%s/archive/refs/heads/%s.zip" % (owner_q, repo_q, ref_q)),
                ("zip-tags", "https://github.com/%s/%s/archive/refs/tags/%s.zip" % (owner_q, repo_q, ref_q)),
            ]
        else:
            candidates = [
                ("zip-codeload-main", "https://codeload.github.com/%s/%s/zip/refs/heads/main" % (owner_q, repo_q)),
                ("zip-codeload-master", "https://codeload.github.com/%s/%s/zip/refs/heads/master" % (owner_q, repo_q)),
                ("zip-main", "https://github.com/%s/%s/archive/refs/heads/main.zip" % (owner_q, repo_q)),
                ("zip-master", "https://github.com/%s/%s/archive/refs/heads/master.zip" % (owner_q, repo_q)),
            ]
        for method, archive_url in candidates:
            try:
                return self._download_github_archive(archive_url, output_dir, method)
            except Exception as e:
                errors.append("%s %s: %s" % (method, archive_url, str(e) or repr(e)))
        raise RuntimeError("GitHub fetch failed: %s" % "; ".join(errors))

    def _fetch_official_package(self, site_url, output_dir):
        release = official_release_info(site_url)
        download_url = str(release.get("download_url") or "").strip()
        if not download_url:
            raise RuntimeError("官网未返回项目包下载地址")
        os.makedirs(output_dir, exist_ok=True)
        zip_path = os.path.join(output_dir, "source.zip")
        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": "cfquant-updater/%s" % current_core_version()},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()
        if not data:
            raise RuntimeError("官网下载包为空")
        actual_sha256 = hashlib.sha256(data).hexdigest()
        expected_sha256 = str(release.get("sha256") or "").strip().lower()
        if expected_sha256 and actual_sha256.lower() != expected_sha256:
            raise RuntimeError("官网包 SHA256 校验失败")
        with open(zip_path, "wb") as f:
            f.write(data)
        extract_dir = os.path.join(output_dir, "extract")
        self._safe_extract_zip(zip_path, extract_dir)
        for name in os.listdir(extract_dir):
            src = os.path.join(extract_dir, name)
            dst = os.path.join(output_dir, name)
            os.replace(src, dst)
        self._remove_tree(extract_dir)
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return {
            "method": "official-site-zip",
            "site_url": normalize_official_site_url(site_url),
            "url": download_url,
            "version": str(release.get("version") or ""),
            "bytes": len(data),
            "sha256": actual_sha256,
            "release": {
                "title": release.get("title") or "",
                "version": release.get("version") or "",
                "updated_at": release.get("updated_at") or "",
                "channel": release.get("channel") or "",
            },
        }

    def _git_current_commit(self, repo_dir):
        try:
            completed = subprocess.run(
                ["git", "-C", repo_dir, "rev-parse", "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                **_hidden_subprocess_kwargs()
            )
            if completed.returncode == 0:
                return (completed.stdout or "").strip()
        except Exception:
            pass
        return ""

    def _download_github_archive(self, url, output_dir, method):
        os.makedirs(output_dir, exist_ok=True)
        zip_path = os.path.join(output_dir, "source.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "cfquant-updater"})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read()
        with open(zip_path, "wb") as f:
            f.write(data)
        extract_dir = os.path.join(output_dir, "extract")
        self._safe_extract_zip(zip_path, extract_dir)
        for name in os.listdir(extract_dir):
            src = os.path.join(extract_dir, name)
            dst = os.path.join(output_dir, name)
            os.replace(src, dst)
        self._remove_tree(extract_dir)
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return {"method": method, "url": url, "bytes": len(data)}

    def _parse_github_repo(self, repo_url):
        value = str(repo_url or "").strip()
        value = re.sub(r"\.git$", "", value)
        patterns = [
            r"github\.com[:/]+([^/\s]+)/([^/\s#?]+)",
            r"^([^/\s]+)/([^/\s#?]+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, value)
            if match:
                return match.group(1), match.group(2)
        raise ValueError("无法识别 GitHub 仓库地址: %s" % repo_url)

    def _safe_extract_zip(self, zip_path, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        root = os.path.abspath(output_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if not name or name.endswith("/"):
                    continue
                if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
                    raise RuntimeError("zip contains absolute path: %s" % info.filename)
                target = os.path.abspath(os.path.join(root, name))
                if not target.startswith(root + os.sep) and target != root:
                    raise RuntimeError("zip path escapes target: %s" % info.filename)
            zf.extractall(root)

    def _find_source_core(self, source_dir):
        source_dir = os.path.abspath(source_dir)
        candidates = [
            os.path.join(source_dir, "cfquant", "cfquant"),
            os.path.join(source_dir, "cfquant"),
        ]
        for candidate in candidates:
            if self._looks_like_core(candidate):
                return os.path.abspath(candidate)
        for root, dirs, files in os.walk(source_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            if "__pycache__" in dirs:
                dirs.remove("__pycache__")
            if self._looks_like_core(root):
                parent = os.path.basename(os.path.dirname(root)).lower()
                base = os.path.basename(root).lower()
                if base == "cfquant" and parent == "cfquant":
                    return os.path.abspath(root)
        for root, dirs, files in os.walk(source_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            if "__pycache__" in dirs:
                dirs.remove("__pycache__")
            if self._looks_like_core(root):
                return os.path.abspath(root)
        return ""

    def _find_source_project_root(self, source_dir):
        source_dir = os.path.abspath(source_dir)
        if self._looks_like_project_root(source_dir):
            return source_dir
        for root, dirs, files in os.walk(source_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            if "__pycache__" in dirs:
                dirs.remove("__pycache__")
            if self._looks_like_project_root(root):
                return os.path.abspath(root)
        return ""

    def _looks_like_project_root(self, path):
        return (
            os.path.isfile(os.path.join(path, "cfquant_web_server.py"))
            and os.path.isdir(os.path.join(path, "qmt_scripts"))
            and self._looks_like_core(os.path.join(path, "cfquant"))
        )

    def _entry_update_info(self, source_dir):
        project_root = self._find_source_project_root(source_dir)
        if not project_root:
            return qmt_entry_manual_update_info(reason="更新源未包含 QMT 入口脚本目录")
        changed = []
        available = []
        for filename in QMT_ENTRY_SCRIPT_NAMES:
            source_path = os.path.join(project_root, "qmt_scripts", filename)
            if not os.path.isfile(source_path):
                continue
            available.append(filename)
            local_path = os.path.join(BASE_DIR, "qmt_scripts", filename)
            if not file_content_equal(source_path, local_path):
                changed.append(filename)
        return qmt_entry_manual_update_info(
            entry_files=changed,
            required=bool(changed),
            reason=(
                "更新源中的 QMT 入口脚本与当前项目不一致"
                if changed else
                "更新源包含 QMT 入口脚本，但与当前项目一致"
                if available else
                "更新源未包含 QMT 入口脚本"
            ),
        )

    def _looks_like_core(self, path):
        if not os.path.isdir(path):
            return False
        required = ["__init__.py", "client.py", "protocol.py"]
        return all(os.path.isfile(os.path.join(path, name)) for name in required)

    def _validate_core_dir(self, path):
        if not self._looks_like_core(path):
            raise RuntimeError("核心目录结构不完整: %s" % path)
        entries = os.listdir(path)
        if any(name in entries for name in QMT_ENTRY_SCRIPT_NAMES):
            raise RuntimeError("源码核心目录包含入口脚本，已拒绝覆盖")

    def _copy_core(self, source_core, target_core):
        self._remove_tree(target_core)
        shutil.copytree(
            source_core,
            target_core,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache"),
        )

    def _core_content_equal(self, source_core, target_core):
        if not self._looks_like_core(source_core) or not self._looks_like_core(target_core):
            return False
        ignored_dirs = {"__pycache__", ".pytest_cache", ".mypy_cache"}
        ignored_suffixes = (".pyc", ".pyo")

        def walk_files(root):
            rows = []
            for current_root, dirs, files in os.walk(root):
                dirs[:] = [name for name in dirs if name not in ignored_dirs]
                for name in files:
                    if name.endswith(ignored_suffixes):
                        continue
                    path = os.path.join(current_root, name)
                    rows.append(os.path.relpath(path, root).replace("\\", "/"))
            rows.sort()
            return rows

        source_files = walk_files(source_core)
        target_files = walk_files(target_core)
        if source_files != target_files:
            return False
        for rel_path in source_files:
            if not file_content_equal(
                os.path.join(source_core, rel_path.replace("/", os.sep)),
                os.path.join(target_core, rel_path.replace("/", os.sep)),
            ):
                return False
        return True

    def _backup_current_core(self, target, label="backup"):
        os.makedirs(target["backup_dir"], exist_ok=True)
        name = "%s_%s" % (self._timestamp(), label)
        dest = os.path.join(target["backup_dir"], name)
        shutil.copytree(
            target["current_core"],
            dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache"),
        )
        return self._backup_info(dest)

    def _restore_backup_dir(self, backup, current):
        path = backup.get("path") if isinstance(backup, dict) else ""
        if not path or not os.path.isdir(path):
            return
        try:
            if os.path.isdir(current):
                self._remove_tree(current)
            shutil.copytree(path, current, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        except Exception as e:
            safe_print("backup restore failed: %s" % e)

    def _write_install_meta(self, target, meta, source_core, backup):
        meta_path = os.path.join(target["updates_dir"], "last_update.json")
        payload = {
            "updated_at": time.time(),
            "updated_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "bridge_id": target.get("bridge_id"),
            "python_dir": target.get("python_dir"),
            "source": meta,
            "source_core": source_core,
            "backup": backup,
        }
        os.makedirs(target["updates_dir"], exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)

    def _read_install_meta(self, updates_dir):
        meta_path = os.path.join(updates_dir, "last_update.json")
        if not os.path.isfile(meta_path):
            return {}
        try:
            with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            return {"error": str(e)}

    def _list_backups(self, backup_dir):
        if not os.path.isdir(backup_dir):
            return []
        rows = []
        for name in os.listdir(backup_dir):
            path = os.path.join(backup_dir, name)
            if os.path.isdir(path):
                rows.append(self._backup_info(path))
        rows.sort(key=lambda row: row.get("created_at") or 0, reverse=True)
        return rows

    def _backup_info(self, path):
        stat_result = os.stat(path)
        return {
            "name": os.path.basename(path),
            "path": os.path.abspath(path),
            "created_at": stat_result.st_mtime,
            "created_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat_result.st_mtime)),
            "version": self._read_version(path),
        }

    def _prune_backups(self, backup_dir):
        rows = self._list_backups(backup_dir)
        removed = []
        for row in rows[self.BACKUP_KEEP:]:
            try:
                self._remove_tree(row["path"])
                removed.append(row)
            except Exception as e:
                safe_print("backup prune failed %s: %s" % (row.get("path"), e))
        return removed

    def _read_version(self, core_dir):
        for filename in ("version.py", "__init__.py"):
            path = os.path.join(core_dir, filename)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(8192)
                match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
                if match:
                    return match.group(1)
            except Exception:
                continue
        return ""

    def _remove_tree(self, path):
        if not path or not os.path.exists(path):
            return
        def onerror(func, failed_path, exc_info):
            try:
                os.chmod(failed_path, stat.S_IWRITE)
                func(failed_path)
            except Exception:
                raise
        shutil.rmtree(path, onerror=onerror)

    def _timestamp(self):
        return time.strftime("%Y%m%d_%H%M%S")


class CfquantProjectUpdater(object):
    BACKUP_KEEP = PROJECT_UPDATE_BACKUP_KEEP
    EXCLUDED_DIR_NAMES = {
        ".git",
        ".cfquant_project_updates",
        ".cfquant_updates",
        ".updates",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "node_modules",
        "log",
        "log_data",
        "tx_log",
        "runtime",
        "pic",
        "remotion_intro",
    }
    PRESERVED_REL_PATHS = {
        "AGENTS.md",
        ".env",
        "cfquant_web_config.json",
        "cfquant_web_config.db",
        "cfquant_pipe_hub_status.json",
        "runtime/config/cfquant_web_config.json",
        "runtime/db/cfquant_web_config.db",
        "runtime/status/cfquant_pipe_hub_status.json",
        "LTtx/tx/Config.txt",
        "LTtx/tx/data0.txt",
    }
    EXCLUDED_FILE_PATTERNS = (
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.log",
        "*.tmp",
        "*.bak",
    )

    def __init__(self):
        self._lock = threading.RLock()

    def status(self, repo_url=None, ref=None, include_remote=True):
        repo_url = str(repo_url or DEFAULT_UPDATE_REPO_URL).strip()
        ref = str(ref or DEFAULT_UPDATE_REF).strip() or "main"
        errors = []
        warnings = []
        if not self._looks_like_project(BASE_DIR):
            errors.append("当前目录不是完整 cfquant 项目目录: %s" % BASE_DIR)
        try:
            backups = self._list_backups()
        except Exception as e:
            backups = []
            warnings.append("备份读取失败: %s" % e)
        return {
            "target_dir": BASE_DIR,
            "ready": not errors,
            "errors": errors,
            "warnings": warnings,
            "current_version": self._read_project_version(BASE_DIR) or current_core_version(),
            "last_update": self._read_install_meta(),
            "backups": backups,
            "version_info": project_version_info(
                include_remote=include_remote,
                repo_url=repo_url,
                ref=ref,
            ),
            "default_repo_url": repo_url,
            "default_official_site_url": DEFAULT_OFFICIAL_SITE_URL,
            "default_ref": ref,
            "preserved_paths": sorted(self.PRESERVED_REL_PATHS),
            "excluded_dirs": sorted(self.EXCLUDED_DIR_NAMES),
        }

    def update_from_github(self, repo_url, ref=""):
        repo_url = str(repo_url or "").strip()
        ref = str(ref or "").strip()
        if not repo_url:
            raise ValueError("repo_url is required")
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="cfquant_project_update_") as work_dir:
                source_dir = os.path.join(work_dir, "source")
                fetched = UPDATER._fetch_github(repo_url, ref, source_dir)
                return self._install_source(source_dir, {
                    "source": "github",
                    "repo_url": repo_url,
                    "ref": ref,
                    "fetch": fetched,
                })

    def update_from_official(self, site_url="", fallback_repo_url="", fallback_ref=""):
        site_url = normalize_official_site_url(site_url)
        fallback_repo_url = str(fallback_repo_url or DEFAULT_UPDATE_REPO_URL).strip()
        fallback_ref = str(fallback_ref or DEFAULT_UPDATE_REF).strip()
        official_error = ""
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="cfquant_project_update_") as work_dir:
                source_dir = os.path.join(work_dir, "source")
                try:
                    fetched = UPDATER._fetch_official_package(site_url, source_dir)
                    return self._install_source(source_dir, {
                        "source": "official_site",
                        "site_url": site_url or DEFAULT_OFFICIAL_SITE_URL,
                        "fetch": fetched,
                    })
                except Exception as e:
                    official_error = str(e) or repr(e)
                    safe_print("official site project update failed, fallback to GitHub: %s" % official_error)
                if not fallback_repo_url:
                    raise RuntimeError("官网下载失败且未配置 GitHub 回退源: %s" % official_error)
                source_dir = os.path.join(work_dir, "github_source")
                fetched = UPDATER._fetch_github(fallback_repo_url, fallback_ref, source_dir)
                return self._install_source(source_dir, {
                    "source": "github_fallback",
                    "repo_url": fallback_repo_url,
                    "ref": fallback_ref,
                    "official_site_error": official_error,
                    "fetch": fetched,
                })

    def update_from_zip(self, filename, content):
        content = content or b""
        if not content:
            raise ValueError("zip content is empty")
        with self._lock:
            with tempfile.TemporaryDirectory(prefix="cfquant_project_update_") as work_dir:
                zip_path = os.path.join(work_dir, "upload.zip")
                with open(zip_path, "wb") as f:
                    f.write(content)
                source_dir = os.path.join(work_dir, "source")
                UPDATER._safe_extract_zip(zip_path, source_dir)
                return self._install_source(source_dir, {
                    "source": "zip",
                    "filename": filename,
                    "size": len(content),
                })

    def rollback(self, backup_name=None):
        with self._lock:
            backups = self._list_backups()
            if not backups:
                raise RuntimeError("没有可回滚的项目备份")
            if backup_name:
                backup_name = os.path.basename(str(backup_name))
                selected = next((row for row in backups if row["name"] == backup_name), None)
                if selected is None:
                    raise RuntimeError("project backup not found: %s" % backup_name)
            else:
                selected = backups[0]
            rollback_backup = self._backup_project(
                self._manifest_rel_files(selected),
                label="rollback",
            )
            entry_info = self._entry_rollback_info(selected)
            self._restore_backup(selected)
            removed = self._prune_backups()
            return {
                "updated": True,
                "target_dir": BASE_DIR,
                "restored_backup": selected,
                "rollback_backup": rollback_backup,
                "removed_backups": removed,
                "current_version": self._read_project_version(BASE_DIR) or current_core_version(),
                "backups": self._list_backups(),
                "qmt_restart_required": (
                    qmt_restart_required_info(
                        reason="Web 项目回滚影响了 QMT 入口脚本",
                        entry_info=entry_info,
                    )
                    if entry_info.get("required")
                    else qmt_restart_not_required_info(
                        reason="Web 项目回滚未检测到 QMT 入口脚本变更",
                        entry_info=entry_info,
                    )
                ),
                "entry_manual_update": entry_info,
            }

    def _install_source(self, source_dir, meta):
        source_root = self._find_source_project(source_dir)
        if not source_root:
            raise RuntimeError("源码中未找到完整 cfquant 项目目录")
        rel_files = self._source_rel_files(source_root)
        if not rel_files:
            raise RuntimeError("源码中没有可更新的项目文件")
        backup = self._backup_project(rel_files, label="backup")
        copied = []
        changed = []
        try:
            for rel_path in rel_files:
                src = os.path.join(source_root, rel_path.replace("/", os.sep))
                dst = self._safe_target_path(rel_path)
                if not file_content_equal(src, dst):
                    changed.append(rel_path)
                parent = os.path.dirname(dst)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                if os.path.isdir(dst) and not os.path.islink(dst):
                    UPDATER._remove_tree(dst)
                elif os.path.exists(dst) and not os.path.isfile(dst):
                    os.remove(dst)
                shutil.copy2(src, dst)
                copied.append(rel_path)
            entry_info = self._entry_update_info(changed)
            self._write_install_meta(meta, source_root, backup, copied, changed, entry_info)
            removed = self._prune_backups()
            return {
                "updated": True,
                "target_dir": BASE_DIR,
                "source_project": source_root,
                "source": meta,
                "backup": backup,
                "copied_files": len(copied),
                "changed_files": len(changed),
                "changed_qmt_entry_files": entry_info.get("entry_files") or [],
                "removed_backups": removed,
                "current_version": self._read_project_version(BASE_DIR) or current_core_version(),
                "backups": self._list_backups(),
                "qmt_restart_required": (
                    qmt_restart_required_info(
                        reason="Web 项目更新包含 QMT 入口脚本变更",
                        entry_info=entry_info,
                    )
                    if entry_info.get("required")
                    else qmt_restart_not_required_info(
                        reason="Web 项目更新未检测到 QMT 入口脚本变更",
                        entry_info=entry_info,
                    )
                ),
                "entry_manual_update": entry_info,
            }
        except Exception:
            self._restore_backup(backup)
            raise

    def _find_source_project(self, source_dir):
        source_dir = os.path.abspath(source_dir)
        if self._looks_like_project(source_dir):
            return source_dir
        for root, dirs, files in os.walk(source_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            if "__pycache__" in dirs:
                dirs.remove("__pycache__")
            if self._looks_like_project(root):
                return os.path.abspath(root)
        return ""

    def _looks_like_project(self, path):
        return (
            os.path.isfile(os.path.join(path, "cfquant_web_server.py"))
            and os.path.isfile(os.path.join(path, "cfquant", "__init__.py"))
            and os.path.isfile(os.path.join(path, "web_dashboard", "index.html"))
        )

    def _source_rel_files(self, source_root):
        result = []
        for root, dirs, files in os.walk(source_root):
            rel_root = self._relpath(source_root, root)
            dirs[:] = [
                name for name in dirs
                if not self._is_excluded_path(self._join_rel(rel_root, name), is_dir=True)
            ]
            for filename in files:
                rel_path = self._join_rel(rel_root, filename)
                if self._is_excluded_path(rel_path, is_dir=False):
                    continue
                result.append(rel_path)
        result.sort()
        return result

    def _backup_project(self, rel_files, label="backup"):
        rel_files = sorted(set(rel_files or []))
        os.makedirs(self._backup_root(), exist_ok=True)
        name = "%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), label)
        backup_dir = os.path.join(self._backup_root(), name)
        files_dir = os.path.join(backup_dir, "files")
        os.makedirs(files_dir, exist_ok=True)
        manifest = {
            "schema": "cfquant.project.backup",
            "created_at": time.time(),
            "created_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "project_dir": BASE_DIR,
            "label": label,
            "files": {},
        }
        for rel_path in rel_files:
            if self._is_excluded_path(rel_path, is_dir=False):
                continue
            src = self._safe_target_path(rel_path)
            item = {"existed": os.path.isfile(src)}
            if os.path.isfile(src):
                dst = os.path.join(files_dir, rel_path.replace("/", os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                try:
                    item["size"] = os.path.getsize(src)
                except Exception:
                    pass
            manifest["files"][rel_path] = item
        self._write_json_file(os.path.join(backup_dir, "manifest.json"), manifest)
        return self._backup_info(backup_dir)

    def _restore_backup(self, backup):
        backup_dir = backup.get("path") if isinstance(backup, dict) else str(backup or "")
        backup_dir = os.path.abspath(backup_dir)
        if not backup_dir.startswith(os.path.abspath(self._backup_root()) + os.sep):
            raise RuntimeError("非法项目备份路径: %s" % backup_dir)
        manifest = self._read_json_file(os.path.join(backup_dir, "manifest.json"))
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        files_dir = os.path.join(backup_dir, "files")
        for rel_path, item in files.items():
            if self._is_excluded_path(rel_path, is_dir=False):
                continue
            dst = self._safe_target_path(rel_path)
            existed = bool(item.get("existed")) if isinstance(item, dict) else False
            if existed:
                src = os.path.join(files_dir, rel_path.replace("/", os.sep))
                if os.path.isfile(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
            elif os.path.isfile(dst):
                os.remove(dst)

    def _entry_update_info(self, changed_rel_files):
        entry_files = []
        for rel_path in changed_rel_files or []:
            normalized = self._normalize_rel(rel_path)
            if not normalized.lower().startswith("qmt_scripts/"):
                continue
            filename = os.path.basename(normalized)
            if filename in QMT_ENTRY_SCRIPT_NAMES:
                entry_files.append(filename)
        return qmt_entry_manual_update_info(
            entry_files=entry_files,
            required=bool(entry_files),
            reason=(
                "本次 Web 项目更新修改了 QMT 入口脚本"
                if entry_files else
                "本次 Web 项目更新未修改 QMT 入口脚本"
            ),
        )

    def _entry_rollback_info(self, backup):
        backup_dir = backup.get("path") if isinstance(backup, dict) else str(backup or "")
        backup_dir = os.path.abspath(backup_dir)
        manifest = self._read_json_file(os.path.join(backup_dir, "manifest.json"))
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        files_dir = os.path.join(backup_dir, "files")
        entry_files = []
        for rel_path, item in files.items():
            normalized = self._normalize_rel(rel_path)
            if not normalized.lower().startswith("qmt_scripts/"):
                continue
            filename = os.path.basename(normalized)
            if filename not in QMT_ENTRY_SCRIPT_NAMES:
                continue
            backup_path = os.path.join(files_dir, normalized.replace("/", os.sep))
            current_path = self._safe_target_path(normalized)
            existed = bool(item.get("existed")) if isinstance(item, dict) else False
            if existed and not file_content_equal(backup_path, current_path):
                entry_files.append(filename)
            elif not existed and os.path.isfile(current_path):
                entry_files.append(filename)
        return qmt_entry_manual_update_info(
            entry_files=entry_files,
            required=bool(entry_files),
            reason=(
                "本次 Web 项目回滚会修改 QMT 入口脚本"
                if entry_files else
                "本次 Web 项目回滚未修改 QMT 入口脚本"
            ),
        )

    def _write_install_meta(self, meta, source_root, backup, copied, changed, entry_info):
        payload = {
            "updated_at": time.time(),
            "updated_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "project_dir": BASE_DIR,
            "source": meta,
            "source_project": source_root,
            "backup": backup,
            "copied_files": copied,
            "changed_files": changed,
            "entry_manual_update": entry_info,
            "current_version": self._read_project_version(BASE_DIR) or current_core_version(),
        }
        os.makedirs(PROJECT_UPDATE_DIR, exist_ok=True)
        self._write_json_file(os.path.join(PROJECT_UPDATE_DIR, "last_update.json"), payload)

    def _read_install_meta(self):
        return self._read_json_file(os.path.join(PROJECT_UPDATE_DIR, "last_update.json"))

    def _manifest_rel_files(self, backup):
        manifest = self._read_json_file(os.path.join(backup.get("path") or "", "manifest.json"))
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        return list(files.keys())

    def _list_backups(self):
        backup_root = self._backup_root()
        if not os.path.isdir(backup_root):
            return []
        rows = []
        for name in os.listdir(backup_root):
            path = os.path.join(backup_root, name)
            if os.path.isdir(path):
                rows.append(self._backup_info(path))
        rows.sort(key=lambda row: row.get("created_at") or 0, reverse=True)
        return rows

    def _backup_info(self, path):
        stat_result = os.stat(path)
        manifest = self._read_json_file(os.path.join(path, "manifest.json"))
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        files_dir = os.path.join(path, "files")
        return {
            "name": os.path.basename(path),
            "path": os.path.abspath(path),
            "created_at": stat_result.st_mtime,
            "created_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat_result.st_mtime)),
            "version": self._read_project_version(files_dir),
            "file_count": len(files),
            "label": manifest.get("label") or "",
        }

    def _prune_backups(self):
        rows = self._list_backups()
        removed = []
        for row in rows[self.BACKUP_KEEP:]:
            try:
                UPDATER._remove_tree(row["path"])
                removed.append(row)
            except Exception as e:
                safe_print("project backup prune failed %s: %s" % (row.get("path"), e))
        return removed

    def _read_project_version(self, project_dir):
        candidates = [
            os.path.join(project_dir, "cfquant", "version.py"),
            os.path.join(project_dir, "cfquant", "__init__.py"),
        ]
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(8192)
                match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
                if match:
                    return match.group(1)
            except Exception:
                continue
        return ""

    def _is_excluded_path(self, rel_path, is_dir=False):
        rel_path = self._normalize_rel(rel_path)
        if not rel_path:
            return False
        parts = [part.lower() for part in rel_path.split("/") if part]
        if any(part in self.EXCLUDED_DIR_NAMES for part in parts):
            return True
        if rel_path.lower() in {item.lower() for item in self.PRESERVED_REL_PATHS}:
            return True
        if not is_dir:
            filename = parts[-1] if parts else ""
            if any(fnmatch.fnmatch(filename, pattern.lower()) for pattern in self.EXCLUDED_FILE_PATTERNS):
                return True
        return False

    def _safe_target_path(self, rel_path):
        rel_path = self._normalize_rel(rel_path)
        target = os.path.abspath(os.path.join(BASE_DIR, rel_path.replace("/", os.sep)))
        root = os.path.abspath(BASE_DIR)
        if target != root and not target.startswith(root + os.sep):
            raise RuntimeError("项目更新路径越界: %s" % rel_path)
        return target

    def _backup_root(self):
        return os.path.join(PROJECT_UPDATE_DIR, "backups")

    def _relpath(self, root, path):
        rel = os.path.relpath(path, root)
        return "" if rel == "." else self._normalize_rel(rel)

    def _join_rel(self, rel_root, name):
        return self._normalize_rel(os.path.join(rel_root, name) if rel_root else name)

    def _normalize_rel(self, path):
        rel = str(path or "").replace("\\", "/").strip("/")
        rel = posixpath.normpath(rel)
        return "" if rel == "." else rel

    def _read_json_file(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_json_file(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


UPDATER = CfquantUpdater(WEB_CONFIG)
PROJECT_UPDATER = CfquantProjectUpdater()


def _write_qmt_bridge_identity_for_dir(row, qmt_dir_override=None, qmt_role="normal"):
    row = row or {}
    bridge_id = normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID)
    qmt_dir = normalize_optional_path(
        qmt_dir_override if qmt_dir_override is not None else row.get("qmt_dir") or row.get("python_dir")
    )
    account_type = normalize_account_type(row.get("account_type") or "STOCK")
    result = {
        "written": False,
        "qmt_role": qmt_role,
        "bridge_id": bridge_id,
        "account_id": str(row.get("account_id") or ""),
        "account_type": account_type,
        "account_key": str(row.get("account_key") or ""),
        "qmt_dir": qmt_dir,
        "path": "",
        "error": "",
        "warning": "",
    }
    if not qmt_dir:
        result["warning"] = "QMT 核心目录未填写，无法自动写入 ctypes 身份配置"
        return result
    try:
        target = UPDATER._target_paths(qmt_dir) if UPDATER is not None else {"python_dir": qmt_dir, "script_dir": ""}
        core_dir = normalize_optional_path(target.get("python_dir") or qmt_dir)
        if not core_dir or not os.path.isdir(core_dir):
            result["error"] = "QMT 核心目录不存在: %s" % (core_dir or qmt_dir)
            return result
        channels = bridge_channels(bridge_id)
        accounts = []
        if WEB_CONFIG is not None:
            for item in WEB_CONFIG.account_configs().values():
                if not isinstance(item, dict):
                    continue
                if normalize_bridge_id(item.get("bridge_id") or DEFAULT_BRIDGE_ID) != bridge_id:
                    continue
                if item.get("enabled", True) is False:
                    continue
                account_id = str(item.get("account_id") or "").strip()
                if not account_id:
                    continue
                item_type = normalize_account_type(item.get("account_type") or "STOCK")
                accounts.append({
                    "account_key": str(item.get("account_key") or account_key_for(account_id, item_type, bridge_id)),
                    "account_id": account_id,
                    "account_type": item_type,
                    "account_type_label": account_type_label(item_type),
                    "display_name": str(item.get("display_name") or ""),
                    "data_provider": bool(item.get("data_provider")),
                })
        if not accounts and row.get("account_id"):
            accounts.append({
                "account_key": str(row.get("account_key") or account_key_for(row.get("account_id"), account_type, bridge_id)),
                "account_id": str(row.get("account_id") or ""),
                "account_type": account_type,
                "account_type_label": account_type_label(account_type),
                "display_name": str(row.get("display_name") or ""),
                "data_provider": bool(row.get("data_provider")),
            })
        payload = {
            "config_version": 2,
            "bridge_id": bridge_id,
            "account_id": str(row.get("account_id") or ""),
            "account_type": account_type,
            "account_key": str(row.get("account_key") or account_key_for(row.get("account_id"), account_type, bridge_id)),
            "accounts": accounts,
            "mode": normalize_transport_mode(row.get("mode") or "ctypes"),
            "qmt_role": qmt_role,
            "qmt_trade_dir": normalize_optional_path(row.get("qmt_trade_dir")),
            "pipe_name": normalize_pipe_name(os.environ.get("CFQUANT_PIPE_NAME") or DEFAULT_PIPE_NAME),
            "channels": channels,
            "runtime_dir": RUNTIME_DIR,
            "runtime_status_dir": RUNTIME_STATUS_DIR,
            "runtime_marker_dir": QMT_RUNTIME_MARKER_DIR,
            "qmt_runtime_marker_dir": QMT_RUNTIME_MARKER_DIR,
            "qmt_runtime_version_file": QMT_RUNTIME_VERSION_FILE,
            "qmt_log_language": WEB_CONFIG.qmt_log_language() if WEB_CONFIG is not None else "zh",
            "qmt_log_enabled": WEB_CONFIG.qmt_log_enabled() if WEB_CONFIG is not None else True,
            "updated_at": time.time(),
            "updated_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "source": "cfquant_web_account_binding",
        }
        path = os.path.join(core_dir, QMT_BRIDGE_CONFIG_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2, sort_keys=True)
        result.update({
            "written": True,
            "path": path,
            "core_dir": core_dir,
            "script_dir": normalize_optional_path(target.get("script_dir")),
            "channels": channels,
            "accounts": accounts,
        })
        return result
    except Exception as e:
        result["error"] = str(e)
        safe_print("cfquant QMT bridge identity write failed bridge_id=%s qmt_dir=%s error=%s" % (bridge_id, qmt_dir, e))
        return result


def write_qmt_bridge_identity(row):
    row = row or {}
    result = _write_qmt_bridge_identity_for_dir(row)
    if normalize_transport_mode(row.get("mode") or "ctypes") != "lttx":
        return result
    trade_dir = normalize_optional_path(
        row.get("qmt_trade_dir")
        or row.get("trade_qmt_dir")
        or row.get("advanced_qmt_dir")
        or row.get("qmt_trade_core_dir")
    )
    trade_result = _write_qmt_bridge_identity_for_dir(row, trade_dir, qmt_role="trade")
    result["trade_identity"] = trade_result
    if trade_result.get("error") and not result.get("error"):
        result["error"] = "极速交易端 QMT 身份配置写入失败: %s" % trade_result.get("error")
    elif trade_result.get("warning") and not result.get("warning"):
        result["warning"] = "极速交易端 QMT 身份配置未写入: %s" % trade_result.get("warning")
    return result


def write_qmt_market_bridge_identities(row):
    row = row or {}
    if not parse_config_bool(row.get("market_routing_enabled"), False):
        return []
    account_id = str(row.get("account_id") or "").strip()
    account_type = normalize_account_type(row.get("account_type") or "STOCK")
    account_key = str(row.get("account_key") or account_key_for(account_id, account_type, row.get("bridge_id"))).strip()
    parent_bridge_id = normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID)
    routes = normalize_market_bridge_config(
        row.get("market_bridges") or {},
        account_id=account_id,
        account_type=account_type,
        parent_bridge_id=parent_bridge_id,
        enabled=True,
    )
    accounts = [{
        "account_key": account_key,
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "display_name": str(row.get("display_name") or ""),
        "data_provider": bool(row.get("data_provider")),
    }]
    results = []
    for market, route in routes.items():
        if route.get("enabled", True) is False:
            continue
        bridge_id = normalize_bridge_id(route.get("bridge_id") or "")
        qmt_dir = normalize_optional_path(route.get("qmt_dir"))
        filename = str(route.get("config_filename") or (MARKET_ROUTE_CONFIG_FILENAME_TEMPLATE % market))
        result = {
            "written": False,
            "market": market,
            "bridge_id": bridge_id,
            "parent_bridge_id": parent_bridge_id,
            "account_id": account_id,
            "account_type": account_type,
            "account_key": account_key,
            "qmt_dir": qmt_dir,
            "path": "",
            "error": "",
            "warning": "",
        }
        if not bridge_id:
            result["warning"] = "market bridge_id is empty"
            results.append(result)
            continue
        if not qmt_dir:
            result["warning"] = "market QMT dir is empty"
            results.append(result)
            continue
        try:
            target = UPDATER._target_paths(qmt_dir) if UPDATER is not None else {"python_dir": qmt_dir, "script_dir": ""}
            core_dir = normalize_optional_path(target.get("python_dir") or qmt_dir)
            if not core_dir or not os.path.isdir(core_dir):
                result["error"] = "QMT core dir does not exist: %s" % (core_dir or qmt_dir)
                results.append(result)
                continue
            channels = bridge_channels(bridge_id)
            payload = {
                "config_version": 3,
                "bridge_id": bridge_id,
                "account_id": account_id,
                "account_type": account_type,
                "account_key": account_key,
                "accounts": accounts,
                "mode": normalize_transport_mode(row.get("mode") or "ctypes"),
                "pipe_name": normalize_pipe_name(os.environ.get("CFQUANT_PIPE_NAME") or DEFAULT_PIPE_NAME),
                "channels": channels,
                "runtime_dir": RUNTIME_DIR,
                "runtime_status_dir": RUNTIME_STATUS_DIR,
                "runtime_marker_dir": QMT_RUNTIME_MARKER_DIR,
                "qmt_runtime_marker_dir": QMT_RUNTIME_MARKER_DIR,
                "qmt_runtime_version_file": QMT_RUNTIME_VERSION_FILE,
                "market": market,
                "market_role": "trade",
                "market_route_parent_bridge_id": parent_bridge_id,
                "market_routing_enabled": True,
                "qmt_log_language": WEB_CONFIG.qmt_log_language() if WEB_CONFIG is not None else "zh",
                "qmt_log_enabled": WEB_CONFIG.qmt_log_enabled() if WEB_CONFIG is not None else True,
                "updated_at": time.time(),
                "updated_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "source": "cfquant_web_account_market_binding",
            }
            path = os.path.join(core_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=True, indent=2, sort_keys=True)
            result.update({
                "written": True,
                "path": path,
                "core_dir": core_dir,
                "script_dir": normalize_optional_path(target.get("script_dir")),
                "channels": channels,
                "accounts": accounts,
            })
        except Exception as e:
            result["error"] = str(e)
            safe_print(
                "cfquant QMT market bridge identity write failed market=%s bridge_id=%s qmt_dir=%s error=%s"
                % (market, bridge_id, qmt_dir, e)
            )
        results.append(result)
    return results


def _auto_deploy_qmt_core_result_summary(results):
    results = [item for item in (results or []) if isinstance(item, dict)]
    updated = [item for item in results if item.get("updated")]
    skipped = [item for item in results if item.get("skipped")]
    errors = [item for item in results if item.get("error")]
    warnings = [item for item in results if item.get("warning")]
    restart_required = any(
        isinstance(item.get("qmt_restart_required"), dict)
        and item["qmt_restart_required"].get("required")
        for item in results
    )
    if errors:
        message = "cfquant 核心包自动复制部分失败：%s" % "；".join(
            "%s(%s)" % (item.get("qmt_role") or item.get("market") or "QMT", item.get("error"))
            for item in errors[:3]
        )
    elif updated:
        message = "cfquant 核心包已自动复制到 %d 个 QMT 目录" % len(updated)
    elif skipped:
        message = "cfquant 核心包无需复制或已跳过"
    elif warnings:
        message = "cfquant 核心包自动复制有提示：%s" % "；".join(
            item.get("warning") or item.get("message") or ""
            for item in warnings[:3]
        )
    else:
        message = "没有可自动复制的 QMT 目录"
    return {
        "ok": not errors,
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "restart_required": restart_required,
        "message": message,
    }


def auto_deploy_qmt_core_for_account(row, enabled=True):
    row = row or {}
    enabled = parse_config_bool(enabled, True)
    targets = []

    def add_target(qmt_dir, qmt_role, bridge_id=None, account_keys=None, market=""):
        qmt_dir = normalize_optional_path(qmt_dir)
        if not qmt_dir:
            return
        resolved_dir = qmt_dir
        try:
            if UPDATER is not None:
                target = UPDATER._target_paths(qmt_dir)
                resolved_dir = normalize_optional_path(target.get("python_dir") or qmt_dir)
        except Exception:
            resolved_dir = qmt_dir
        key = os.path.normcase(os.path.abspath(os.path.normpath(resolved_dir)))
        for target in targets:
            if target["key"] == key:
                if account_keys:
                    target.setdefault("account_keys", []).extend(
                        item for item in account_keys if item not in target.setdefault("account_keys", [])
                    )
                return
        targets.append({
            "key": key,
            "qmt_dir": qmt_dir,
            "qmt_role": qmt_role,
            "bridge_id": normalize_bridge_id(bridge_id or row.get("bridge_id") or DEFAULT_BRIDGE_ID),
            "account_keys": list(account_keys or []),
            "market": market,
        })

    account_key = str(row.get("account_key") or "").strip()
    account_keys = [account_key] if account_key else []
    add_target(row.get("qmt_dir") or row.get("python_dir"), "normal", row.get("bridge_id"), account_keys)
    if normalize_transport_mode(row.get("mode") or "ctypes") == "lttx":
        add_target(
            row.get("qmt_trade_dir")
            or row.get("trade_qmt_dir")
            or row.get("advanced_qmt_dir")
            or row.get("qmt_trade_core_dir"),
            "trade",
            row.get("bridge_id"),
            account_keys,
        )
    if parse_config_bool(row.get("market_routing_enabled"), False):
        routes = normalize_market_bridge_config(
            row.get("market_bridges") or {},
            account_id=row.get("account_id"),
            account_type=row.get("account_type") or "STOCK",
            parent_bridge_id=row.get("bridge_id") or DEFAULT_BRIDGE_ID,
            enabled=True,
        )
        for market, route in routes.items():
            if route.get("enabled", True) is False:
                continue
            add_target(
                route.get("qmt_dir"),
                "market_%s" % market,
                route.get("bridge_id") or row.get("bridge_id"),
                account_keys,
                market=market,
            )

    if not enabled:
        results = [{
            "updated": False,
            "skipped": True,
            "warning": "已按请求跳过 cfquant 核心包自动复制",
            "message": "已按请求跳过 cfquant 核心包自动复制",
        }]
        return {
            "enabled": False,
            "results": results,
            "summary": _auto_deploy_qmt_core_result_summary(results),
        }

    results = []
    if not targets:
        result = {
            "updated": False,
            "skipped": True,
            "warning": "QMT 目录未填写，已跳过 cfquant 核心包自动复制",
            "message": "QMT 目录未填写，已跳过 cfquant 核心包自动复制",
        }
        results.append(result)
    else:
        for target in targets:
            if UPDATER is None:
                results.append({
                    "updated": False,
                    "skipped": False,
                    "qmt_role": target.get("qmt_role") or "normal",
                    "bridge_id": target.get("bridge_id") or DEFAULT_BRIDGE_ID,
                    "qmt_dir": target.get("qmt_dir") or "",
                    "error": "更新器未初始化，无法自动复制 cfquant 核心包",
                    "message": "更新器未初始化，无法自动复制 cfquant 核心包",
                })
                continue
            result = UPDATER.install_local_core_to_qmt_dir(
                target.get("qmt_dir"),
                bridge_id=target.get("bridge_id"),
                qmt_role=target.get("qmt_role") or "normal",
                account_keys=target.get("account_keys") or [],
            )
            if target.get("market"):
                result["market"] = target.get("market")
            results.append(result)
    return {
        "enabled": True,
        "results": results,
        "summary": _auto_deploy_qmt_core_result_summary(results),
    }


def sync_qmt_bridge_identities():
    results = []
    try:
        configs = WEB_CONFIG.account_configs() if WEB_CONFIG is not None else {}
        for row in configs.values():
            if not isinstance(row, dict):
                continue
            has_main_qmt_dir = bool(normalize_optional_path(row.get("qmt_dir") or row.get("python_dir")))
            has_market_qmt_dir = any(
                normalize_optional_path((route or {}).get("qmt_dir"))
                for route in (row.get("market_bridges") or {}).values()
                if isinstance(route, dict)
            )
            if not has_main_qmt_dir and not has_market_qmt_dir:
                continue
            if has_main_qmt_dir:
                result = write_qmt_bridge_identity(row)
                results.append(result)
                if result.get("written"):
                    safe_print(
                        "cfquant QMT bridge identity synced bridge_id=%s path=%s"
                        % (result.get("bridge_id"), result.get("path"))
                    )
                elif result.get("error"):
                    safe_print(
                        "cfquant QMT bridge identity sync failed bridge_id=%s error=%s"
                        % (result.get("bridge_id"), result.get("error"))
                    )
            market_results = write_qmt_market_bridge_identities(row)
            results.extend(market_results)
            for market_result in market_results:
                if market_result.get("written"):
                    safe_print(
                        "cfquant QMT market bridge identity synced market=%s bridge_id=%s path=%s"
                        % (market_result.get("market"), market_result.get("bridge_id"), market_result.get("path"))
                    )
                elif market_result.get("error"):
                    safe_print(
                        "cfquant QMT market bridge identity sync failed market=%s bridge_id=%s error=%s"
                        % (market_result.get("market"), market_result.get("bridge_id"), market_result.get("error"))
                    )
        return results
    except Exception as e:
        safe_print("cfquant QMT bridge identity sync failed: %s" % e)
        return results


sync_qmt_bridge_identities()


def tcp_port_open(host, port, timeout=0.35):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(float(timeout))
    try:
        return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _hidden_subprocess_kwargs():
    if os.name != "nt":
        return {}
    kwargs = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def run_powershell_json(script, timeout=3.0):
    if os.name != "nt":
        return []
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + script,
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout),
            **_hidden_subprocess_kwargs()
        )
    except subprocess.TimeoutExpired:
        safe_print("powershell query timed out after %.1fs" % float(timeout))
        return []
    except Exception as e:
        safe_print("powershell query failed: %s" % e)
        return []
    if completed.returncode != 0:
        safe_print("powershell query failed: %s" % completed.stderr.strip())
        return []
    raw = (completed.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception as e:
        safe_print("powershell json parse failed: %s raw=%s" % (e, raw[:300]))
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def netstat_port_processes(port):
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2.5,
            **_hidden_subprocess_kwargs()
        )
    except Exception as e:
        safe_print("netstat query failed: %s" % e)
        return []
    if completed.returncode != 0:
        safe_print("netstat query failed: %s" % (completed.stderr or "").strip())
        return []

    rows = []
    suffix = ":%d" % int(port)
    for line in (completed.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local_address = parts[1]
        state = parts[3]
        if state.upper() != "LISTENING" or not local_address.endswith(suffix):
            continue
        try:
            pid = int(parts[-1])
        except Exception:
            continue
        rows.append({
            "pid": pid,
            "name": "",
            "command_line": "",
            "executable_path": "",
            "local_address": local_address,
            "local_port": int(port),
            "state": "Listen",
        })
    return rows


def process_details_by_pid(pids):
    normalized_pids = []
    for pid in pids:
        try:
            pid_int = int(pid)
        except Exception:
            continue
        if pid_int > 0 and pid_int not in normalized_pids:
            normalized_pids.append(pid_int)
    if not normalized_pids:
        return {}

    details = {}
    if psutil is not None:
        for pid in normalized_pids:
            try:
                proc = psutil.Process(pid)
                with proc.oneshot():
                    try:
                        name = proc.name() or ""
                    except Exception:
                        name = ""
                    try:
                        command_line = " ".join(str(part) for part in (proc.cmdline() or []))
                    except Exception:
                        command_line = ""
                    try:
                        executable_path = proc.exe() or ""
                    except Exception:
                        executable_path = ""
                if name or command_line or executable_path:
                    details[pid] = {
                        "pid": pid,
                        "name": name,
                        "command_line": command_line,
                        "executable_path": executable_path,
                    }
            except (
                getattr(psutil, "NoSuchProcess", Exception),
                getattr(psutil, "AccessDenied", Exception),
                getattr(psutil, "ZombieProcess", Exception),
            ):
                continue
            except Exception as e:
                safe_print("psutil process detail query failed pid=%s: %s" % (pid, e))
        if len(details) == len(normalized_pids):
            return details

    fallback_pids = [pid for pid in normalized_pids if pid not in details]
    if not fallback_pids:
        return details
    ids = ",".join(str(pid) for pid in fallback_pids)
    script = r"""
$ids = @(%s)
$rows = foreach ($id in $ids) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $id) -ErrorAction SilentlyContinue
    if ($proc) {
        [pscustomobject]@{
            pid = $proc.ProcessId
            name = $proc.Name
            command_line = $proc.CommandLine
            executable_path = $proc.ExecutablePath
        }
    }
}
if ($null -eq $rows) { "[]" } else { @($rows) | ConvertTo-Json -Compress }
""" % ids
    rows = run_powershell_json(script, timeout=1.0)
    for row in rows:
        try:
            pid = int(row.get("pid") or 0)
        except Exception:
            pid = 0
        if pid:
            details[pid] = row
    return details


def lttx_port_processes():
    rows = netstat_port_processes(LTTX_PORT)
    details = process_details_by_pid([row["pid"] for row in rows])
    normalized = []
    for row in rows:
        try:
            pid = int(row.get("pid") or row.get("OwningProcess") or 0)
        except Exception:
            pid = 0
        if not pid:
            continue
        detail = details.get(pid) or {}
        normalized.append({
            "pid": pid,
            "name": detail.get("name") or row.get("name") or "",
            "command_line": detail.get("command_line") or row.get("command_line") or "",
            "executable_path": detail.get("executable_path") or row.get("executable_path") or "",
            "local_address": row.get("local_address") or "",
            "local_port": row.get("local_port") or LTTX_PORT,
            "state": row.get("state") or "Listen",
        })
    return normalized


def is_lttx_managed_process(row):
    command_line = (row.get("command_line") or "").lower()
    executable_path = (row.get("executable_path") or "").lower()
    haystack = command_line + " " + executable_path
    script_names = ("lttx_server.py", "lttx_serverv2.py", "new_server.py")
    return any(name in haystack for name in script_names)


def lttx_status():
    processes = lttx_port_processes()
    port_open = tcp_port_open(LTTX_HOST, LTTX_PORT)
    running = bool(processes) or port_open
    managed_pids = [row["pid"] for row in processes if is_lttx_managed_process(row)]
    now = time.time()
    return {
        "host": LTTX_HOST,
        "port": LTTX_PORT,
        "running": running,
        "managed": bool(managed_pids),
        "can_start": not running,
        "can_stop": bool(managed_pids),
        "managed_pids": managed_pids,
        "processes": processes,
        "entry": os.path.abspath(LTTX_ENTRY),
        "purpose": "cfquant Python 库自动发现与 Web 统一路由入口",
        "stop_policy": "Web 重启和定时重启保留 LTtx；完整退出 cfquant 时停止 LTtx",
        "checked_at": now,
        "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
    }


def refresh_global_tx_client():
    return refresh_tx_client()


def refresh_tx_client(mode=None):
    mode = normalize_transport_mode(mode or default_runtime_client_mode())
    CLIENTS.close(mode)
    try:
        CLIENTS.start(mode)
        return {"ok": True, "mode": mode, "reply_channel": CLIENTS.client_id}
    except Exception as e:
        CLIENTS.close(mode)
        safe_print("cfquant web %s tx restart failed: %s" % (mode, e))
        return {"ok": False, "mode": mode, "error": str(e), "reply_channel": CLIENTS.client_id}


def start_lttx_server():
    before = lttx_status()
    if before["running"]:
        return {
            "started": False,
            "reason": "LTtx port %s is already listening" % LTTX_PORT,
            "status": before,
        }
    entry = os.path.abspath(LTTX_ENTRY)
    cwd = os.path.abspath(LTTX_DIR)
    if not os.path.isfile(entry):
        raise RuntimeError("LTtx entry not found: %s" % entry)

    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    popen_kwargs = {"creationflags": creationflags, "close_fds": False if os.name == "nt" else True}
    if os.name == "nt":
        hidden_kwargs = _hidden_subprocess_kwargs()
        popen_kwargs.update(hidden_kwargs)
        popen_kwargs["creationflags"] = creationflags | int(hidden_kwargs.get("creationflags") or 0)
    env = os.environ.copy()
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("CFQUANT_LOG_DIR", LOG_DIR)
    env.setdefault("CFQUANT_LOG_RETENTION_DAYS", str(LOG_RETENTION_DAYS))
    env.setdefault("CFQUANT_RUNTIME_DIR", RUNTIME_DIR)
    env.setdefault("CFQUANT_LTTX_RUNTIME_DIR", RUNTIME_LTTX_DIR)
    env.setdefault("CFQUANT_LTTX_BACKGROUND", "1")
    stdout = open(LTTX_STDOUT_LOG, "a", encoding="utf-8", buffering=1)
    stderr = open(LTTX_STDERR_LOG, "a", encoding="utf-8", buffering=1)
    try:
        process = subprocess.Popen(
            [sys.executable, entry],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=env,
            **popen_kwargs
        )
    except Exception:
        try:
            stdout.close()
            stderr.close()
        except Exception:
            pass
        raise
    try:
        stdout.close()
        stderr.close()
    except Exception:
        pass

    time.sleep(1.0)
    status = lttx_status()
    client = refresh_tx_client("lttx") if status["running"] else {"ok": False, "mode": "lttx", "error": "LTtx not ready"}
    return {
        "started": True,
        "pid": process.pid,
        "status": status,
        "client": client,
        "stdout_log": LTTX_STDOUT_LOG,
        "stderr_log": LTTX_STDERR_LOG,
    }


def ensure_lttx_started(reason="默认预启动"):
    status = lttx_status()
    if status.get("running"):
        safe_print("cfquant %s，LTtx 已在运行，跳过自动启动" % reason)
        return {
            "started": False,
            "reason": "LTtx port %s is already listening" % LTTX_PORT,
            "status": status,
        }
    try:
        result = start_lttx_server()
        safe_print("cfquant %s，LTtx 自动启动结果=%s" % (reason, bool(result.get("started"))))
        return result
    except Exception as e:
        safe_print("cfquant %s，LTtx 自动启动失败: %s" % (reason, e))
        return {
            "started": False,
            "ok": False,
            "error": str(e),
            "status": status,
        }


def stop_lttx_server(full_exit=False):
    before = lttx_status()
    allow_manual_stop = str(os.environ.get("CFQUANT_ALLOW_LTTX_MANUAL_STOP") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not full_exit and not allow_manual_stop:
        return {
            "stopped": False,
            "blocked": True,
            "reason": "LTtx 会在 Web 重启和定时重启期间保持运行；请使用 stop_cfquant.bat 完整退出时再停止 LTtx。",
            "status": before,
        }
    if not before["running"]:
        return {
            "stopped": False,
            "reason": "LTtx port %s is not listening" % LTTX_PORT,
            "status": before,
        }
    managed = [row for row in before["processes"] if is_lttx_managed_process(row)]
    if not managed:
        raise RuntimeError("port %s is occupied by an unknown process; stop was refused" % LTTX_PORT)

    results = []
    for row in managed:
        pid = int(row["pid"])
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6.0,
            **_hidden_subprocess_kwargs()
        )
        results.append({
            "pid": pid,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        })
    time.sleep(0.8)
    CLIENTS.close("lttx")
    return {
        "stopped": True,
        "results": results,
        "status": lttx_status(),
    }


def account_payload(account_id, account_type="STOCK"):
    account_id = str(account_id or "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    return {"account": {"account_id": account_id, "account_type": normalize_account_type(account_type)}}


def normalize_stock_code(stock_code):
    value = str(stock_code or "").strip().upper()
    if not value:
        raise ValueError("stock_code is required")
    if "." in value:
        code, market = value.split(".", 1)
        market = market.strip().upper()
    else:
        code = value
        market = "SH" if value.startswith("6") else "SZ"
    code = code.strip()
    if not code:
        raise ValueError("stock_code is required")
    if code.isdigit() and len(code) <= 6:
        number = int(code)
        if number < 0 or number > 999999:
            raise ValueError("stock_code numeric part is out of range: %s" % code)
        if market not in ("SH", "SZ", "BJ"):
            raise ValueError("market suffix must be SH, SZ or BJ")
        return "%06d.%s" % (number, market)
    allowed_markets = ("SH", "SZ", "SHO", "SZO", "SF", "DF", "ZF", "IF", "INE", "GF")
    if market not in allowed_markets:
        raise ValueError("market suffix must be SH, SZ, SHO, SZO, SF, DF, ZF, IF, INE or GF")
    if not re.match(r"^[A-Z0-9_-]+$", code):
        raise ValueError("stock_code contains unsupported characters before market suffix")
    return "%s.%s" % (code, market)


def normalize_channel(value, default="normal"):
    value = (value or default or "normal").strip().lower()
    if value not in ("normal", "trade"):
        raise ValueError("unknown channel: %s" % value)
    return value


def web_request_channel(value=None, default="normal"):
    default = normalize_channel(default, "normal")
    if is_ctypes_transport_mode(WEB_CONFIG.transport_mode()):
        return default
    return normalize_channel(value, default)


def parse_sections(value):
    if not value:
        return ["asset", "positions", "orders", "trades"]
    result = []
    for item in value.split(","):
        item = item.strip().lower()
        if item:
            result.append(item)
    return result


def parse_bool(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def request_timeout_value(value, default=12.0, minimum=0.5, maximum=180.0):
    try:
        timeout = float(value)
    except Exception:
        timeout = float(default)
    return max(float(minimum), min(float(maximum), timeout))


def probe_bridge_status(bridge_id=DEFAULT_BRIDGE_ID, timeout=STATUS_PROBE_TIMEOUT_SECONDS, client=None, mode=None):
    result = {}
    channels = bridge_channels(bridge_id)
    for name in ("normal", "trade"):
        result[name] = probe_bridge_channel_status(
            bridge_id,
            name,
            channels[name],
            timeout=timeout,
            client=client,
            mode=mode,
        )
    return result


def probe_bridge_channel_status(
    bridge_id,
    channel_key,
    channel,
    timeout=STATUS_PROBE_TIMEOUT_SECONDS,
    client=None,
    mode=None,
):
    started = time.perf_counter()
    use_global_client = client is None
    client = client or CLIENTS

    def request(action):
        if use_global_client:
            return client.request(
                bridge_id,
                channel_key,
                action,
                {},
                timeout=timeout,
                mark_offline_on_timeout=True,
                ignore_cooldown=True,
                mode=mode,
            )
        return client.request(
            action,
            {},
            timeout=timeout,
            request_channel=channel,
        )

    try:
        status = request("cfquant.status")
        runtime_report = RUNTIME_VERSIONS.update_from_status(
            bridge_id,
            channel_key,
            status,
            mode=mode or default_runtime_client_mode(),
        )
        return {
            "online": True,
            "channel": channel,
            "status": status,
            "runtime_report": runtime_report or {},
            "probe_action": "cfquant.status",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except CfquantTimeout as e:
        return {
            "online": False,
            "channel": channel,
            "error": str(e),
            "probe_action": "cfquant.status",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except CfquantError as status_error:
        status_elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if not _status_probe_can_fallback(status_error):
            return {
                "online": False,
                "channel": channel,
                "error": str(status_error),
                "probe_action": "cfquant.status",
                "latency_ms": status_elapsed_ms,
        }
        try:
            ping_started = time.perf_counter()
            ping = request("cfquant.ping")
            return {
                "online": True,
                "channel": channel,
                "ping": ping,
                "status": {"status_error": str(status_error)},
                "probe_action": "cfquant.ping",
                "status_probe_ms": status_elapsed_ms,
                "latency_ms": round((time.perf_counter() - ping_started) * 1000, 2),
            }
        except Exception as ping_error:
            return {
                "online": False,
                "channel": channel,
                "error": str(ping_error),
                "status_error": str(status_error),
                "probe_action": "cfquant.status/cfquant.ping",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
    except Exception as e:
        return {
            "online": False,
            "channel": channel,
            "error": str(e),
            "probe_action": "cfquant.status",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def _status_probe_can_fallback(error):
    text = str(error or "").lower()
    unsupported_markers = (
        "unsupported",
        "not support",
        "not supported",
        "暂不支持",
        "unknown action",
        "unsupported action",
    )
    return any(marker in text for marker in unsupported_markers)


class ChannelStatusMonitor(object):
    def __init__(self, interval=STATUS_CHECK_INTERVAL_SECONDS, timeout=STATUS_PROBE_TIMEOUT_SECONDS):
        self.interval = float(interval)
        self.timeout = float(timeout)
        self._lock = threading.RLock()
        self._snapshots = {}
        self._thread = None
        self._running = False
        self._stop_event = threading.Event()

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()
        safe_print("cfquant channel status monitor started interval=%ss" % self.interval)

    def close(self):
        self._running = False
        self._stop_event.set()

    def wake(self):
        self._stop_event.set()

    def forget(self, bridge_id):
        bridge_id = normalize_bridge_id(bridge_id)
        with self._lock:
            self._snapshots.pop(bridge_id, None)

    def latest(self, bridge_id=DEFAULT_BRIDGE_ID, mode=None):
        bridge_id = normalize_bridge_id(bridge_id)
        requested_mode = normalize_transport_mode(
            mode or ("lttx" if bridge_has_lttx_account(bridge_id) else "ctypes")
        )
        cache_key = "ctypes" if is_ctypes_transport_mode(requested_mode) else "lttx"
        channels = bridge_channels(bridge_id)
        with self._lock:
            snapshots = self._snapshots.get(bridge_id) or {}
            cached = snapshots.get(cache_key)
            if cached:
                return dict(cached)
        now = time.time()
        return {
            "bridge_id": bridge_id,
            "bridge_name": bridge_config(bridge_id)["name"],
            "normal": {
                "online": False,
                "channel": channels["normal"],
                "error": "channel status monitor is starting",
            },
            "trade": {
                "online": False,
                "channel": channels["trade"],
                "error": "channel status monitor is starting",
            },
            "checked_at": now,
            "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "monitor": {
                "running": self._running,
                "interval_seconds": self.interval,
                "cached": True,
                "ready": False,
                "transport_mode": cache_key,
            },
        }

    def _loop(self):
        while self._running:
            started = time.time()
            try:
                for bridge_id in current_bridges():
                    snapshots = {}
                    for mode in ("ctypes", "lttx"):
                        if mode == "lttx" and not bridge_has_lttx_account(bridge_id):
                            continue
                        bridge_started = time.time()
                        try:
                            if mode == "ctypes":
                                snapshot = ctypes_bridge_status(bridge_id)
                            else:
                                snapshot = probe_bridge_status(bridge_id=bridge_id, timeout=self.timeout, mode="lttx")
                            snapshot["bridge_id"] = bridge_id
                            snapshot["bridge_name"] = bridge_config(bridge_id)["name"]
                            snapshot["checked_at"] = time.time()
                            snapshot["checked_at_text"] = time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(snapshot["checked_at"]),
                            )
                            snapshot["monitor"] = {
                                "running": self._running,
                                "interval_seconds": self.interval,
                                "cached": True,
                                "ready": True,
                                "transport_mode": mode,
                                "probe_ms": round((time.time() - bridge_started) * 1000, 2),
                            }
                        except Exception as error:
                            channels = bridge_channels(bridge_id)
                            snapshot = {
                                "bridge_id": bridge_id,
                                "bridge_name": bridge_config(bridge_id)["name"],
                                "normal": {
                                    "online": False,
                                    "channel": channels["normal"],
                                    "error": str(error),
                                },
                                "trade": {
                                    "online": False,
                                    "channel": channels["trade"],
                                    "error": str(error),
                                },
                                "checked_at": time.time(),
                                "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "monitor": {
                                    "running": self._running,
                                    "interval_seconds": self.interval,
                                    "cached": True,
                                    "ready": True,
                                    "transport_mode": mode,
                                    "probe_ms": round((time.time() - bridge_started) * 1000, 2),
                                },
                            }
                        snapshots[mode] = snapshot
                    with self._lock:
                        self._snapshots[bridge_id] = snapshots
            except Exception as e:
                safe_print("channel status monitor probe failed: %s" % e)
            elapsed = time.time() - started
            delay = max(0.5, self.interval - elapsed)
            self._stop_event.wait(delay)
            self._stop_event.clear()


STATUS_MONITOR = ChannelStatusMonitor()


class LogCleanupManager(object):
    def __init__(self, interval=LOG_CLEANUP_INTERVAL_SECONDS):
        self.interval = float(interval)
        self._lock = threading.RLock()
        self._last_result = None
        self._thread = None
        self._running = False
        self._wake_event = threading.Event()

    def start(self):
        if self._running:
            return
        self._running = True
        self._wake_event.clear()
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()
        safe_print("cfquant log cleanup started retention_days=%s interval=%ss" % (LOG_RETENTION_DAYS, self.interval))

    def close(self):
        self._running = False
        self._wake_event.set()

    def wake(self):
        self._wake_event.set()

    def status(self):
        with self._lock:
            last_result = json.loads(json.dumps(self._last_result, ensure_ascii=False)) if self._last_result else None
        info = WEB_CONFIG.log_cleanup_info()
        info.update({
            "running": self._running,
            "interval_seconds": self.interval,
            "last_result": last_result,
        })
        return info

    def run_once(self, reason="manual"):
        result = {
            "reason": reason,
            "retention_days": LOG_RETENTION_DAYS,
            "started_at": time.time(),
            "started_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
            "local": None,
            "qmt": {
                "enabled": WEB_CONFIG.qmt_userdata_log_cleanup_enabled(),
                "bridges": [],
            },
        }
        try:
            result["local"] = cleanup_cfquant_local_logs(LOG_RETENTION_DAYS)
        except Exception as e:
            result["local"] = {"error": str(e)}
            safe_print("cfquant local log cleanup failed: %s" % e)

        if WEB_CONFIG.qmt_userdata_log_cleanup_enabled():
            result["qmt"] = self._cleanup_qmt_userdata_logs()

        result["finished_at"] = time.time()
        result["finished_at_text"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(result["finished_at"]))
        result["elapsed_ms"] = round((result["finished_at"] - result["started_at"]) * 1000, 2)
        with self._lock:
            self._last_result = result
        return result

    def _loop(self):
        while self._running:
            started = time.time()
            try:
                self.run_once(reason="auto")
            except Exception as e:
                safe_print("cfquant log cleanup loop failed: %s" % e)
            elapsed = time.time() - started
            delay = max(10.0, self.interval - elapsed)
            self._wake_event.wait(delay)
            self._wake_event.clear()

    def _cleanup_qmt_userdata_logs(self):
        result = {
            "enabled": True,
            "retention_days": LOG_RETENTION_DAYS,
            "bridges": [],
        }
        for bridge_id in current_bridges():
            bridge_result = {"bridge_id": bridge_id, "channels": {}}
            for channel in ("normal", "trade"):
                if channel_online(bridge_id, channel) is not True:
                    bridge_result["channels"][channel] = {"skipped": True, "reason": "channel is not online"}
                    continue
                try:
                    cleanup_result = CLIENTS.request(
                        bridge_id,
                        channel,
                        "cfquant.cleanup_qmt_logs",
                        {"retention_days": LOG_RETENTION_DAYS},
                        timeout=8.0,
                    )
                    bridge_result["channels"][channel] = cleanup_result
                except Exception as e:
                    bridge_result["channels"][channel] = {"error": str(e)}
            result["bridges"].append(bridge_result)
        return result


LOG_CLEANUP = LogCleanupManager()


def query_account_live(bridge_id, channel, account_id, sections, timeout=ACCOUNT_QUERY_TIMEOUT_SECONDS, account_type="STOCK", account_key=None):
    account_type = normalize_account_type(account_type)
    payload = account_payload(account_id, account_type)
    result = {
        "bridge_id": bridge_id,
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
        "channel": channel,
    }
    for section in sections:
        action = ACCOUNT_ACTIONS.get(section)
        if not action:
            result[section] = {"error": "unknown section: %s" % section}
            continue
        started = time.perf_counter()
        try:
            route = account_request(
                account_id,
                bridge_id,
                channel,
                action,
                payload,
                default_channel=channel,
                timeout=timeout,
                mark_offline_on_timeout=False,
                account_type=account_type,
                account_key=account_key,
            )
            data = route["result"]
            refresh_latency_ms = round((time.perf_counter() - started) * 1000, 2)
            result[section] = {
                "ok": True,
                "data": data,
                "mode": route["mode"],
                "channel": route["channel"],
                "fallback": route["fallback"],
                "fallback_reason": route["fallback_reason"],
                # latency_ms is retained for compatibility. It measures the
                # background QMT refresh, not a later cache-hit HTTP response.
                "latency_ms": refresh_latency_ms,
                "refresh_latency_ms": refresh_latency_ms,
                "transport_attempts": route.get("attempts") or [],
            }
        except Exception as e:
            refresh_latency_ms = round((time.perf_counter() - started) * 1000, 2)
            result[section] = {
                "ok": False,
                "error": str(e),
                "latency_ms": refresh_latency_ms,
                "refresh_latency_ms": refresh_latency_ms,
            }
    return result


def account_section_ok(section):
    return isinstance(section, dict) and bool(section.get("ok"))


def account_section_data(section):
    if not isinstance(section, dict):
        return None
    return section.get("data")


def account_data_has_value(value):
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict, str)):
        return bool(value)
    return True


def market_row_with_source(row, market, bridge_id):
    if isinstance(row, dict):
        result = dict(row)
    else:
        result = {"value": row}
    result.setdefault("market", market)
    result.setdefault("source_market", market)
    result.setdefault("bridge_id", bridge_id)
    result.setdefault("source_bridge_id", bridge_id)
    return result


def market_section_rows(data, market, bridge_id, filter_market=False):
    if data is None:
        return []
    if isinstance(data, list):
        rows = data
    else:
        rows = [data]
    result = []
    for row in rows:
        if filter_market:
            row_market = market_account_row_market(row)
            if row_market and market and row_market != market:
                continue
        result.append(market_row_with_source(row, market, bridge_id))
    return result


def market_section_error(section):
    if not isinstance(section, dict):
        return "missing section"
    return str(section.get("error") or "query failed")


def merge_market_account_section(section, child_results, started_at):
    successes = []
    errors = []
    market_results = {}
    market_counts = {}
    max_latency = 0.0
    warming_up = False
    for child in child_results:
        market = child.get("market") or ""
        bridge_id = normalize_bridge_id(child.get("bridge_id") or "")
        row = child.get(section) if isinstance(child, dict) else None
        if row is None and isinstance(child, dict) and child.get("error"):
            row = {"ok": False, "error": child.get("error")}
        if isinstance(row, dict):
            row = dict(row)
            row.setdefault("market", market)
            row.setdefault("bridge_id", bridge_id)
            if row.get("warming_up"):
                warming_up = True
            try:
                max_latency = max(max_latency, float(row.get("latency_ms") or 0))
            except Exception:
                pass
        else:
            row = {"ok": False, "error": "missing section", "market": market, "bridge_id": bridge_id}
        market_results[market] = row
        if account_section_ok(row):
            data = account_section_data(row)
            rows = None
            if section in MARKET_ACCOUNT_ROW_SECTIONS:
                rows = market_section_rows(data, market, bridge_id, filter_market=True)
                market_counts[market] = len(rows)
            else:
                market_counts[market] = len(data) if isinstance(data, list) else (1 if account_data_has_value(data) else 0)
            successes.append((market, bridge_id, row, rows))
        else:
            errors.append("%s/%s: %s" % (market or "-", bridge_id or "-", market_section_error(row)))
            market_counts[market] = 0

    base = {
        "market_routing": True,
        "market_results": market_results,
        "market_counts": market_counts,
        "latency_ms": round(max(max_latency, (time.perf_counter() - started_at) * 1000), 2),
    }
    base["refresh_latency_ms"] = base["latency_ms"]
    if section == "asset":
        chosen = None
        for item in successes:
            if account_data_has_value(account_section_data(item[2])):
                chosen = item
                break
        if chosen is None and successes:
            chosen = successes[0]
        if chosen is None:
            base.update({
                "ok": False,
                "error": "; ".join(errors) or "market routed account asset is warming up",
                "cached": any(isinstance(row, dict) and row.get("cached") for row in market_results.values()),
                "warming_up": warming_up,
            })
            return base
        market, bridge_id, row, _rows = chosen
        result = dict(row)
        result.update(base)
        result["ok"] = True
        result["source_market"] = market
        result["source_bridge_id"] = bridge_id
        if errors:
            result["partial_errors"] = errors
        return result

    merged = []
    for market, bridge_id, row, rows in successes:
        if rows is None:
            rows = market_section_rows(account_section_data(row), market, bridge_id)
        merged.extend(rows)
    if not successes:
        base.update({
            "ok": False,
            "data": [],
            "error": "; ".join(errors) or "market routed account data is warming up",
            "cached": any(isinstance(row, dict) and row.get("cached") for row in market_results.values()),
            "warming_up": warming_up,
        })
        return base
    base.update({
        "ok": True,
        "data": merged,
        "source_markets": [market for market, _bridge_id, _row, _rows in successes],
        "cached": all(isinstance(row, dict) and row.get("cached") for _market, _bridge_id, row, _rows in successes),
    })
    if errors:
        base["partial_errors"] = errors
    return base


def merge_market_account_results(base_bridge_id, channel, account_id, sections, child_results, force=False, refresh_queued=False, account_type="STOCK", account_key=None):
    started_at = time.perf_counter()
    account_type = normalize_account_type(account_type)
    account_key = account_key or account_key_for(account_id, account_type, base_bridge_id)
    result = {
        "bridge_id": base_bridge_id,
        "bridge_name": bridge_config(base_bridge_id)["name"],
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "account_key": account_key,
        "channel": channel,
        "market_routing": True,
        "market_account_query": True,
        "market_routes": {
            child.get("market"): {
                "market": child.get("market"),
                "bridge_id": child.get("bridge_id"),
                "channel": child.get("channel") or channel,
                "ok": not bool(child.get("error")),
                "error": child.get("error", ""),
            }
            for child in child_results
        },
        "cache": {
            "enabled": any(bool((child.get("cache") or {}).get("enabled")) for child in child_results if isinstance(child, dict)),
            "force": bool(force),
            "refresh_queued": bool(refresh_queued) or any(bool((child.get("cache") or {}).get("refresh_queued")) for child in child_results if isinstance(child, dict)),
        },
    }
    checked_times = []
    max_age = 0.0
    for child in child_results:
        cache = child.get("cache") if isinstance(child, dict) else {}
        if not isinstance(cache, dict):
            continue
        if cache.get("interval_seconds") is not None:
            result["cache"]["interval_seconds"] = cache.get("interval_seconds")
        if cache.get("checked_at_text"):
            checked_times.append(cache.get("checked_at_text"))
        try:
            max_age = max(max_age, float(cache.get("max_age_ms") or 0))
        except Exception:
            pass
    if checked_times:
        result["cache"]["checked_at_text"] = min(checked_times)
    if max_age:
        result["cache"]["max_age_ms"] = round(max_age, 2)
    for section in sections:
        result[section] = merge_market_account_section(section, child_results, started_at)
    return result


def market_child_section_count(child, section, market):
    if not isinstance(child, dict):
        return 0
    row = child.get(section)
    if not account_section_ok(row):
        return 0
    data = account_section_data(row)
    if section in MARKET_ACCOUNT_ROW_SECTIONS:
        return len(market_section_rows(data, market, child.get("bridge_id"), filter_market=True))
    return len(data) if isinstance(data, list) else (1 if account_data_has_value(data) else 0)


def market_child_needs_normal_probe(child, sections, market):
    if not isinstance(child, dict) or child.get("error"):
        return True
    for section in sections:
        row = child.get(section)
        if not account_section_ok(row):
            return True
        if section == "positions" and market_child_section_count(child, section, market) <= 0:
            return True
    return False


def merge_market_child_channel_results(primary, fallback, market, sections):
    if not isinstance(primary, dict):
        return fallback if isinstance(fallback, dict) else primary
    if not isinstance(fallback, dict):
        return primary
    result = dict(primary)
    primary_error = str(primary.get("error") or "")
    fallback_error = str(fallback.get("error") or "")
    primary_channel = primary.get("channel") or "trade"
    fallback_channel = fallback.get("channel") or "normal"
    result["channel_attempts"] = [
        {
            "channel": primary_channel,
            "ok": not bool(primary_error),
            "error": primary_error,
        },
        {
            "channel": fallback_channel,
            "ok": not bool(fallback_error),
            "error": fallback_error,
        },
    ]
    result["normal_probe"] = True
    used_fallback = False
    if primary_error and not fallback_error:
        result.update(fallback)
        used_fallback = True
    for section in sections:
        primary_row = primary.get(section)
        fallback_row = fallback.get(section)
        if not isinstance(fallback_row, dict):
            continue
        use_fallback = False
        if not account_section_ok(primary_row) and account_section_ok(fallback_row):
            use_fallback = True
        elif section == "positions" and account_section_ok(primary_row) and account_section_ok(fallback_row):
            primary_count = market_child_section_count(primary, section, market)
            fallback_count = market_child_section_count(fallback, section, market)
            use_fallback = fallback_count > primary_count
        if use_fallback:
            result[section] = fallback_row
            result.setdefault("section_channels", {})[section] = fallback_channel
            used_fallback = True
        elif not account_section_ok(fallback_row):
            result.setdefault("fallback_channel_errors", {})[section] = market_section_error(fallback_row)
    if used_fallback and primary_channel != fallback_channel:
        result["channel"] = "%s/%s" % (primary_channel, fallback_channel)
    return result


class AccountDataCache(object):
    def __init__(self, interval=ACCOUNT_CACHE_REFRESH_SECONDS, background_timeout=ACCOUNT_CACHE_BACKGROUND_TIMEOUT_SECONDS):
        self.interval = float(interval)
        self.background_timeout = float(background_timeout)
        self._lock = threading.RLock()
        self._entries = {}
        self._subscriptions = {}
        self._prewarm_subscriptions = {}
        self._thread = None
        self._running = False
        self._stop_event = threading.Event()

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        prewarm = self.prime_configured_accounts()
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()
        safe_print(
            "cfquant account data cache started interval=%ss background_timeout=%ss prewarm_accounts=%s prewarm_subscriptions=%s"
            % (
                self.interval,
                self.background_timeout,
                prewarm["account_count"],
                prewarm["subscription_count"],
            )
        )

    def close(self):
        self._running = False
        self._stop_event.set()

    def get(self, bridge_id, channel, account_id, sections, force=False, subscribe=True, account_type="STOCK", account_key=None, timeout=ACCOUNT_QUERY_TIMEOUT_SECONDS):
        bridge_id = normalize_bridge_id(bridge_id)
        account_type = normalize_account_type(account_type)
        account_key = account_key or account_key_for(account_id, account_type, bridge_id)
        sections = [section for section in sections if section in ACCOUNT_ACTIONS]
        if not sections:
            return {"bridge_id": bridge_id, "account_id": account_id, "account_type": account_type, "account_key": account_key, "channel": channel}
        if not subscribe:
            live = query_account_live(bridge_id, channel, account_id, sections, timeout=timeout, account_type=account_type, account_key=account_key)
            live["cache"] = {
                "enabled": False,
                "force": bool(force),
                "subscribed": False,
            }
            return live
        self._subscribe(bridge_id, channel, account_id, sections, account_type=account_type, account_key=account_key)
        if force:
            live = query_account_live(bridge_id, channel, account_id, sections, timeout=timeout, account_type=account_type, account_key=account_key)
            self._store_result(bridge_id, channel, account_id, live, sections, account_type=account_type, account_key=account_key)
            return self._build_result(bridge_id, channel, account_id, sections, force=True, account_type=account_type, account_key=account_key)

        missing = self._missing_sections(bridge_id, channel, account_id, sections, account_type=account_type, account_key=account_key)
        if missing:
            self._wake()
            return self._build_result(
                bridge_id,
                channel,
                account_id,
                sections,
                force=False,
                refresh_queued=True,
                account_type=account_type,
                account_key=account_key,
            )
        elif self._needs_refresh(bridge_id, channel, account_id, sections, account_type=account_type, account_key=account_key):
            self._wake()
        return self._build_result(bridge_id, channel, account_id, sections, force=False, account_type=account_type, account_key=account_key)

    def get_market_routed(self, bridge_id, channel, account_id, sections, force=False, subscribe=True, account_type="STOCK", account_key=None, timeout=ACCOUNT_QUERY_TIMEOUT_SECONDS):
        base_bridge_id = normalize_bridge_id(bridge_id)
        account_type = normalize_account_type(account_type)
        base_config, entries = account_market_route_entries(
            account_id=account_id,
            account_type=account_type,
            bridge_id=base_bridge_id,
            account_key=account_key,
        )
        account_key = account_key or (base_config or {}).get("account_key") or account_key_for(account_id, account_type, base_bridge_id)
        sections = [section for section in sections if section in ACCOUNT_ACTIONS]
        channel = account_cache_channel_for_sections(
            account_id,
            requested_channel=channel,
            default=channel,
            account_type=account_type,
            bridge_id=base_bridge_id,
            account_key=account_key,
            sections=sections,
        )
        if not entries or not sections:
            return self.get(
                base_bridge_id,
                channel,
                account_id,
                sections,
                force=force,
                subscribe=subscribe,
                account_type=account_type,
                account_key=account_key,
                timeout=timeout,
            )
        child_results = []
        refresh_queued = False
        for entry in entries:
            child_bridge_id = normalize_bridge_id(entry.get("bridge_id") or "")
            market = entry.get("market") or ""
            child_channel = "trade"
            if not child_bridge_id:
                continue
            try:
                bridge_config(child_bridge_id)
                child = self.get(
                    child_bridge_id,
                    child_channel,
                    account_id,
                    sections,
                    force=force,
                    subscribe=subscribe,
                    account_type=account_type,
                    account_key=account_key,
                    timeout=timeout,
                )
                if child_channel != "normal" and market_child_needs_normal_probe(child, sections, market):
                    try:
                        normal_probe = self.get(
                            child_bridge_id,
                            "normal",
                            account_id,
                            sections,
                            force=force,
                            subscribe=subscribe,
                            account_type=account_type,
                            account_key=account_key,
                            timeout=timeout,
                        )
                        child = merge_market_child_channel_results(child, normal_probe, market, sections)
                    except Exception as normal_error:
                        if isinstance(child, dict):
                            child = dict(child)
                            child.setdefault("fallback_channel_errors", {})["normal"] = str(normal_error)
                if isinstance(child, dict):
                    child = dict(child)
                    child["market"] = market
                    child["base_bridge_id"] = base_bridge_id
                    child_results.append(child)
                    refresh_queued = refresh_queued or bool((child.get("cache") or {}).get("refresh_queued"))
            except Exception as e:
                child_results.append({
                    "market": market,
                    "bridge_id": child_bridge_id,
                    "base_bridge_id": base_bridge_id,
                    "channel": child_channel,
                    "error": str(e),
                    "cache": {"enabled": bool(subscribe), "force": bool(force)},
                })
        if not child_results:
            return self.get(
                base_bridge_id,
                channel,
                account_id,
                sections,
                force=force,
                subscribe=subscribe,
                account_type=account_type,
                account_key=account_key,
                timeout=timeout,
            )
        return merge_market_account_results(
            base_bridge_id,
            "trade",
            account_id,
            sections,
            child_results,
            force=force,
            refresh_queued=refresh_queued,
            account_type=account_type,
            account_key=account_key,
        )

    def _cache_key(self, bridge_id, channel, account_id, section=None, account_type="STOCK", account_key=None):
        account_type = normalize_account_type(account_type)
        account_key = account_key or account_key_for(account_id, account_type, bridge_id)
        base = (bridge_id, channel, account_key, account_id, account_type)
        return base + ((section,) if section is not None else ())

    def _subscribe(self, bridge_id, channel, account_id, sections, account_type="STOCK", account_key=None):
        key = self._cache_key(bridge_id, channel, account_id, account_type=account_type, account_key=account_key)
        with self._lock:
            current = self._subscriptions.setdefault(key, set())
            current.update(sections)

    def prime_configured_accounts(self, sections=None):
        sections = sections if sections is not None else ACCOUNT_CACHE_PREWARM_SECTIONS
        if isinstance(sections, str):
            sections = sections.split(",")
        sections = sorted(set(
            str(section or "").strip().lower()
            for section in sections
            if str(section or "").strip().lower() in ACCOUNT_ACTIONS
        ))
        desired = {}
        account_count = 0
        for configured_key, config in enabled_account_configs().items():
            config = config if isinstance(config, dict) else {}
            account_id = str(config.get("account_id") or "").strip()
            if not account_id:
                continue
            account_type = normalize_account_type(config.get("account_type") or "STOCK")
            bridge_id = normalize_bridge_id(config.get("bridge_id") or DEFAULT_BRIDGE_ID)
            account_key = str(config.get("account_key") or configured_key or "").strip()
            account_key = account_key or account_key_for(account_id, account_type, bridge_id)
            try:
                bridge_config(bridge_id)
            except Exception as error:
                safe_print(
                    "account data cache prewarm skipped invalid bridge=%s account=%s type=%s error=%s"
                    % (bridge_id, account_id, account_type, error)
                )
                continue

            _config, routes = account_market_route_entries(
                account_id=account_id,
                account_type=account_type,
                bridge_id=bridge_id,
                account_key=account_key,
            )
            targets = []
            if routes:
                for route in routes:
                    route_bridge_id = normalize_bridge_id(route.get("bridge_id") or "")
                    if not route_bridge_id:
                        continue
                    try:
                        bridge_config(route_bridge_id)
                    except Exception as error:
                        safe_print(
                            "account data cache prewarm skipped invalid route bridge=%s account=%s type=%s error=%s"
                            % (route_bridge_id, account_id, account_type, error)
                        )
                        continue
                    if route_bridge_id:
                        targets.append((route_bridge_id, "trade"))
            if not targets:
                targets.append((
                    bridge_id,
                    account_cache_channel_for_sections(
                        account_id,
                        requested_channel="normal",
                        default="normal",
                        mode=config.get("mode") or None,
                        account_type=account_type,
                        bridge_id=bridge_id,
                        account_key=account_key,
                        sections=sections,
                    ),
                ))

            account_count += 1
            for target_bridge_id, channel in targets:
                key = self._cache_key(
                    target_bridge_id,
                    channel,
                    account_id,
                    account_type=account_type,
                    account_key=account_key,
                )
                desired.setdefault(key, set()).update(sections)

        with self._lock:
            self._prewarm_subscriptions = desired
        self._wake()
        return {
            "account_count": account_count,
            "subscription_count": len(desired),
            "sections": list(sections),
        }

    def _missing_sections(self, bridge_id, channel, account_id, sections, account_type="STOCK", account_key=None):
        with self._lock:
            return [
                section
                for section in sections
                if self._cache_key(bridge_id, channel, account_id, section, account_type=account_type, account_key=account_key) not in self._entries
            ]

    def _needs_refresh(self, bridge_id, channel, account_id, sections, account_type="STOCK", account_key=None):
        now = time.time()
        with self._lock:
            for section in sections:
                entry = self._entries.get(self._cache_key(bridge_id, channel, account_id, section, account_type=account_type, account_key=account_key))
                if not entry or now - entry.get("checked_at", 0) >= self.interval:
                    return True
        return False

    def _wake(self):
        self._stop_event.set()

    def _store_result(self, bridge_id, channel, account_id, result, sections, account_type="STOCK", account_key=None):
        now = time.time()
        checked_at_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        account_type = normalize_account_type(account_type)
        account_key = account_key or account_key_for(account_id, account_type, bridge_id)
        with self._lock:
            for section in sections:
                row = result.get(section)
                if row is None:
                    continue
                cache_key = self._cache_key(bridge_id, channel, account_id, section, account_type=account_type, account_key=account_key)
                if isinstance(row, dict) and not row.get("ok") and is_pipe_client_closed_error(row.get("error")):
                    previous = self._entries.get(cache_key)
                    if isinstance(previous, dict) and is_pipe_client_closed_error(previous.get("error")):
                        self._entries.pop(cache_key, None)
                    continue
                stored = dict(row)
                stored["checked_at"] = now
                stored["checked_at_text"] = checked_at_text
                stored["account_type"] = account_type
                stored["account_key"] = account_key
                self._entries[cache_key] = stored

    def _build_result(self, bridge_id, channel, account_id, sections, force=False, refresh_queued=False, account_type="STOCK", account_key=None):
        now = time.time()
        account_type = normalize_account_type(account_type)
        account_key = account_key or account_key_for(account_id, account_type, bridge_id)
        result = {
            "bridge_id": bridge_id,
            "bridge_name": bridge_config(bridge_id)["name"],
            "account_id": account_id,
            "account_type": account_type,
            "account_type_label": account_type_label(account_type),
            "account_key": account_key,
            "channel": channel,
            "cache": {
                "enabled": True,
                "force": bool(force),
                "interval_seconds": self.interval,
                "background_timeout_seconds": self.background_timeout,
                "refresh_queued": bool(refresh_queued),
            },
        }
        ages = []
        with self._lock:
            for section in sections:
                entry = self._entries.get(self._cache_key(bridge_id, channel, account_id, section, account_type=account_type, account_key=account_key))
                if not entry:
                    result[section] = {
                        "ok": False,
                        "error": "account data cache is warming up",
                        "cached": True,
                        "warming_up": True,
                    }
                    continue
                age = max(0, now - entry.get("checked_at", now))
                ages.append(age)
                row = dict(entry)
                row["cached"] = True
                row.setdefault("refresh_latency_ms", row.get("latency_ms"))
                row["cache_age_ms"] = round(age * 1000, 2)
                result[section] = row
        if ages:
            result["cache"]["max_age_ms"] = round(max(ages) * 1000, 2)
            checked_times = [
                result[section].get("checked_at_text", "")
                for section in sections
                if isinstance(result.get(section), dict) and result[section].get("checked_at_text")
            ]
            if checked_times:
                result["cache"]["checked_at_text"] = min(checked_times)
        return result

    def _loop(self):
        while self._running:
            self._stop_event.clear()
            self._refresh_subscriptions()
            self._stop_event.wait(self.interval)

    def _refresh_subscriptions(self):
        with self._lock:
            combined = {}
            for subscriptions_by_key in (self._prewarm_subscriptions, self._subscriptions):
                for key, sections in subscriptions_by_key.items():
                    combined.setdefault(key, set()).update(sections)
            subscriptions = [
                (bridge_id, channel, account_key, account_id, account_type, sorted(sections))
                for (bridge_id, channel, account_key, account_id, account_type), sections in combined.items()
                if account_id and sections
            ]
        for bridge_id, channel, account_key, account_id, account_type, sections in subscriptions:
            if not self._running:
                break
            try:
                live = query_account_live(
                    bridge_id,
                    channel,
                    account_id,
                    sections,
                    timeout=self.background_timeout,
                    account_type=account_type,
                    account_key=account_key,
                )
                self._store_result(bridge_id, channel, account_id, live, sections, account_type=account_type, account_key=account_key)
            except Exception as e:
                safe_print(
                    "account data cache refresh failed bridge=%s channel=%s account=%s type=%s error=%s"
                    % (bridge_id, channel, account_id, account_type, e)
                )


ACCOUNT_CACHE = AccountDataCache()


def submit_order(body, credit_only=False):
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or ("CREDIT" if credit_only else "STOCK"))
    if credit_only and account_type != "CREDIT":
        raise ValueError("credit order requires account_type=CREDIT")
    account_key = str(body.get("account_key") or "").strip()
    bridge_id = resolve_bridge_id(account_id=account_id, account_type=account_type, account_key=account_key, bridge_id=body.get("bridge_id"))
    bridge_config(bridge_id)
    stock_code = normalize_stock_code(body.get("stock_code"))
    side = str(body.get("side") or "").strip().lower()
    credit_action = body.get("credit_action") or body.get("credit_business") or body.get("action")
    order_action = (
        body.get("order_action")
        or body.get("future_action")
        or body.get("future_business")
        or body.get("stock_option_action")
        or body.get("future_option_action")
        or body.get("option_action")
        or body.get("option_business")
        or body.get("derivative_action")
        or (body.get("business_type") if account_type in DERIVATIVE_ACCOUNT_TYPES else None)
        or (body.get("action") if account_type in DERIVATIVE_ACCOUNT_TYPES else None)
    )
    price = float(body.get("price"))
    volume = int(body.get("volume"))
    price_type = int(body.get("price_type") or FIX_PRICE)
    confirm_text = str(body.get("confirm_text") or "").strip()
    if account_type == "STOCK" and side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if not stock_code:
        raise ValueError("stock_code is required")
    if volume <= 0:
        raise ValueError("volume must be positive")
    if price < 0:
        raise ValueError("price must be non-negative")
    if price_type == FIX_PRICE and price <= 0:
        raise ValueError("price must be positive")

    action_info = resolve_order_action(
        account_type,
        side,
        credit_action=credit_action,
        order_action=order_action,
        explicit_order_type=body.get("order_type", body.get("optype")),
    )
    side = action_info["side"] or side
    allow_legacy_credit_confirmation = (
        account_type == "CREDIT"
        and credit_action in (None, "")
        and action_info["credit_action"] in ("credit_buy", "credit_sell")
    )
    expected_values = order_confirmation_options(
        account_type,
        side,
        stock_code,
        volume,
        price,
        credit_action=action_info["credit_action"],
        order_action=action_info["order_action"],
        order_type=action_info["order_type"],
        allow_legacy_side=allow_legacy_credit_confirmation,
    )
    if confirm_text not in expected_values:
        raise ValueError("confirmation mismatch, expected: %s" % " or ".join(expected_values))

    remark = (
        body.get("order_remark")
        or body.get("remark")
        or body.get("strategy_name")
        or "cfquant_web_%s" % int(time.time() * 1000)
    )
    params = {
        "account": {"account_id": account_id, "account_type": account_type},
        "stock_code": stock_code,
        "order_type": action_info["order_type"],
        "order_volume": volume,
        "price_type": price_type,
        "price": price,
        "qmt_order_type": int(body.get("qmt_order_type") or 1101),
        "quick_trade": int(body.get("quick_trade") or 2),
        "strategy_name": body.get("strategy_name") or "cfquant_web",
        "order_remark": remark,
    }
    if action_info["credit_action"]:
        params["credit_action"] = action_info["credit_action"]
    if action_info["order_action"]:
        params["order_action"] = action_info["order_action"]
    started = time.perf_counter()
    timeout = request_timeout_value(body.get("timeout"), default=12.0, maximum=60.0)
    route = account_request(
        account_id,
        bridge_id,
        body.get("channel"),
        "xttrader.order_stock",
        params,
        default_channel="trade",
        timeout=timeout,
        account_type=account_type,
        account_key=account_key,
    )
    return {
        "bridge_id": route["bridge_id"],
        "account_id": account_id,
        "account_type": account_type,
        "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
        "channel": route["channel"],
        "mode": route["mode"],
        "fallback": route["fallback"],
        "fallback_reason": route["fallback_reason"],
        "market_route": route.get("market_route") or {},
        "side": side,
        "order_type": action_info["order_type"],
        "credit_action": action_info["credit_action"],
        "credit_action_label": action_info["credit_action_label"],
        "order_action": action_info["order_action"],
        "order_action_label": action_info["order_action_label"],
        "confirm_text_options": expected_values,
        "result": route["result"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "order_remark": remark,
    }


def submit_credit_order(body):
    body = dict(body or {})
    body.setdefault("account_type", "CREDIT")
    return submit_order(body, credit_only=True)


def submit_typed_order(body, account_type):
    body = dict(body or {})
    expected = normalize_account_type(account_type)
    if body.get("account_type") not in (None, "") and normalize_account_type(body.get("account_type")) != expected:
        raise ValueError("%s order requires account_type=%s" % (expected.lower(), expected))
    body["account_type"] = expected
    return submit_order(body)


def submit_future_order(body):
    return submit_typed_order(body, "FUTURE")


def submit_future_option_order(body):
    return submit_typed_order(body, "FUTURE_OPTION")


def submit_stock_option_order(body):
    return submit_typed_order(body, "STOCK_OPTION")


def submit_batch_orders(body, credit_only=False):
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or ("CREDIT" if credit_only else "STOCK"))
    if credit_only and account_type != "CREDIT":
        raise ValueError("credit batch order requires account_type=CREDIT")
    account_key = str(body.get("account_key") or "").strip()
    bridge_id = resolve_bridge_id(account_id=account_id, account_type=account_type, account_key=account_key, bridge_id=body.get("bridge_id"))
    bridge_config(bridge_id)
    raw_orders = body.get("orders") or []
    if not isinstance(raw_orders, list) or not raw_orders:
        raise ValueError("orders must be a non-empty list")
    confirm_text = str(body.get("confirm_text") or "").strip()
    expected = "BATCH %s" % len(raw_orders)
    if confirm_text != expected:
        raise ValueError("confirmation mismatch, expected: %s" % expected)
    body_order_action = (
        body.get("order_action")
        or body.get("future_action")
        or body.get("future_business")
        or body.get("stock_option_action")
        or body.get("future_option_action")
        or body.get("option_action")
        or body.get("option_business")
        or body.get("derivative_action")
        or (body.get("business_type") if account_type in DERIVATIVE_ACCOUNT_TYPES else None)
        or (body.get("action") if account_type in DERIVATIVE_ACCOUNT_TYPES else None)
    )
    orders = []
    for index, row in enumerate(raw_orders):
        if not isinstance(row, dict):
            raise ValueError("orders[%s] must be an object" % index)
        row_credit_action = (
            row.get("credit_action")
            or row.get("credit_business")
            or row.get("action")
            or body.get("credit_action")
            or body.get("credit_business")
            or body.get("action")
        )
        row_order_action = (
            row.get("order_action")
            or row.get("future_action")
            or row.get("future_business")
            or row.get("stock_option_action")
            or row.get("future_option_action")
            or row.get("option_action")
            or row.get("option_business")
            or row.get("derivative_action")
            or (row.get("business_type") if account_type in DERIVATIVE_ACCOUNT_TYPES else None)
            or (row.get("action") if account_type in DERIVATIVE_ACCOUNT_TYPES else None)
            or body_order_action
        )
        side = str(row.get("side") or body.get("side") or ("buy" if account_type != "CREDIT" else "")).strip().lower()
        if account_type == "STOCK" and side not in ("buy", "sell"):
            raise ValueError("orders[%s].side must be buy or sell" % index)
        price = float(row.get("price"))
        price_type = int(row.get("price_type") or body.get("price_type") or FIX_PRICE)
        volume = int(row.get("volume") or row.get("order_volume"))
        if price < 0:
            raise ValueError("orders[%s].price must be non-negative" % index)
        if price_type == FIX_PRICE and price <= 0:
            raise ValueError("orders[%s].price must be positive" % index)
        if volume <= 0:
            raise ValueError("orders[%s].volume must be positive" % index)
        action_info = resolve_order_action(
            account_type,
            side,
            credit_action=row_credit_action,
            order_action=row_order_action,
            explicit_order_type=row.get("order_type", row.get("optype")),
        )
        orders.append({
            "stock_code": normalize_stock_code(row.get("stock_code") or row.get("code")),
            "side": action_info["side"] or side,
            "order_type": action_info["order_type"],
            "order_volume": volume,
            "price_type": price_type,
            "price": price,
            "qmt_order_type": int(row.get("qmt_order_type") or body.get("qmt_order_type") or 1101),
            "quick_trade": int(row.get("quick_trade") or body.get("quick_trade") or 2),
            "strategy_name": row.get("strategy_name") or body.get("strategy_name") or "cfquant_web_batch",
            "order_remark": row.get("order_remark") or "cfquant_batch_%s_%s" % (int(time.time() * 1000), index + 1),
            "credit_action": action_info["credit_action"],
            "credit_action_label": action_info["credit_action_label"],
            "order_action": action_info["order_action"],
            "order_action_label": action_info["order_action_label"],
        })
    params = {
        "account": {"account_id": account_id, "account_type": account_type},
        "orders": orders,
        "stop_on_error": parse_bool(body.get("stop_on_error")),
        "order_remark": body.get("order_remark") or "cfquant_batch_%s" % int(time.time() * 1000),
    }
    started = time.perf_counter()
    timeout = request_timeout_value(
        body.get("timeout"),
        default=max(12.0, len(orders) * 3.0),
        maximum=120.0,
    )
    route = account_batch_order_request(
        account_id,
        bridge_id,
        body.get("channel"),
        params,
        default_channel="trade",
        timeout=timeout,
        account_type=account_type,
        account_key=account_key,
    )
    return {
        "bridge_id": route["bridge_id"],
        "channel": route["channel"],
        "mode": route["mode"],
        "fallback": route["fallback"],
        "fallback_reason": route["fallback_reason"],
        "market_route": route.get("market_route") or {},
        "account_id": account_id,
        "account_type": account_type,
        "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
        "result": route["result"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def submit_credit_batch_orders(body):
    body = dict(body or {})
    body.setdefault("account_type", "CREDIT")
    return submit_batch_orders(body, credit_only=True)


def submit_typed_batch_orders(body, account_type):
    body = dict(body or {})
    expected = normalize_account_type(account_type)
    if body.get("account_type") not in (None, "") and normalize_account_type(body.get("account_type")) != expected:
        raise ValueError("%s batch order requires account_type=%s" % (expected.lower(), expected))
    body["account_type"] = expected
    return submit_batch_orders(body)


def submit_future_batch_orders(body):
    return submit_typed_batch_orders(body, "FUTURE")


def submit_future_option_batch_orders(body):
    return submit_typed_batch_orders(body, "FUTURE_OPTION")


def submit_stock_option_batch_orders(body):
    return submit_typed_batch_orders(body, "STOCK_OPTION")


def cancel_order(body):
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
    account_key = str(body.get("account_key") or "").strip()
    bridge_id = resolve_bridge_id(account_id=account_id, account_type=account_type, account_key=account_key, bridge_id=body.get("bridge_id"))
    bridge_config(bridge_id)
    order_id = str(body.get("order_id") or "").strip()
    confirm_text = str(body.get("confirm_text") or "").strip()
    if not order_id:
        raise ValueError("order_id is required")
    expected = "CANCEL %s" % order_id
    if confirm_text != expected:
        raise ValueError("confirmation mismatch, expected: %s" % expected)
    params = {
        "account": {"account_id": account_id, "account_type": account_type},
        "order_id": order_id,
    }
    started = time.perf_counter()
    timeout = request_timeout_value(body.get("timeout"), default=12.0, maximum=60.0)
    route = account_request(
        account_id,
        bridge_id,
        body.get("channel"),
        "xttrader.cancel_order_stock",
        params,
        default_channel="trade",
        timeout=timeout,
        account_type=account_type,
        account_key=account_key,
    )
    return {
        "bridge_id": route["bridge_id"],
        "account_id": account_id,
        "account_type": account_type,
        "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
        "channel": route["channel"],
        "mode": route["mode"],
        "fallback": route["fallback"],
        "fallback_reason": route["fallback_reason"],
        "result": route["result"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def save_bridge_config(body):
    row = WEB_CONFIG.save_bridge(body or {})
    STATUS_MONITOR.wake()
    ACCOUNT_CACHE.prime_configured_accounts()
    CALLBACKS.refresh_channels(callback_channels())
    return {
        "bridge": row,
        "bridges": WEB_CONFIG.bridges(),
    }


def delete_bridge_config(body):
    bridge_id = (body or {}).get("bridge_id") or (body or {}).get("id")
    WEB_CONFIG.delete_bridge(bridge_id)
    STATUS_MONITOR.forget(bridge_id)
    STATUS_MONITOR.wake()
    ACCOUNT_CACHE.prime_configured_accounts()
    CALLBACKS.refresh_channels(callback_channels())
    return {
        "bridges": WEB_CONFIG.bridges(),
        "account_pairs": WEB_CONFIG.account_pairs(),
    }


def save_user_profile(body):
    body = body or {}
    profile = WEB_CONFIG.set_user_profile(
        display_name=body.get("display_name") if "display_name" in body else None,
        avatar_url=body.get("avatar_url") if "avatar_url" in body else None,
    )
    return user_profile_response(profile)


def save_account_pair(body):
    display_name = (body or {}).get("display_name") if "display_name" in (body or {}) else (body or {}).get("account_name")
    row = WEB_CONFIG.save_pair(
        (body or {}).get("account_id"),
        (body or {}).get("bridge_id"),
        account_type=(body or {}).get("account_type") or "STOCK",
        account_key=(body or {}).get("account_key"),
        display_name=display_name,
    )
    STATUS_MONITOR.wake()
    ACCOUNT_CACHE.prime_configured_accounts()
    return {
        "pair": row,
        "account_pairs": WEB_CONFIG.account_pairs(),
    }


def ensure_account_runtime(mode):
    mode = normalize_transport_mode(mode)
    results = {"mode": mode, "ctypes": None, "lttx": None}
    results["lttx"] = ensure_lttx_started("账号运行配置预启动")
    try:
        results["ctypes"] = start_pipe_hub()
    except Exception as error:
        results["ctypes"] = {"ok": False, "error": str(error)}
        safe_print("cfquant account config ctypes runtime start failed: %s" % error)
    try:
        CLIENTS.start(mode)
    except Exception as error:
        results["client"] = {"ok": False, "error": str(error)}
        safe_print("cfquant account config %s client start failed: %s" % (mode, error))
    else:
        results["client"] = {"ok": True, "mode": mode}
    return results


def save_account_runtime_config(body):
    body = body or {}
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
    bridge_id = body.get("bridge_id")
    display_name = body.get("display_name") if "display_name" in body else body.get("account_name")
    qmt_dir = body.get("qmt_dir") or body.get("python_dir")
    qmt_trade_dir = (
        body.get("qmt_trade_dir")
        or body.get("trade_qmt_dir")
        or body.get("advanced_qmt_dir")
        or body.get("qmt_trade_core_dir")
    )
    mode = body.get("mode") or body.get("transport_mode") or "ctypes"
    market_bridges = body.get("market_bridges") if "market_bridges" in body else body.get("market_routes") if "market_routes" in body else None
    market_routing_enabled = body.get("market_routing_enabled") if "market_routing_enabled" in body else None
    row = WEB_CONFIG.save_account_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=bridge_id,
        display_name=display_name,
        qmt_dir=qmt_dir,
        qmt_trade_dir=qmt_trade_dir,
        mode=mode,
        data_provider=parse_bool(body.get("data_provider")),
        enabled=body.get("enabled", True) is not False,
        market_routing_enabled=market_routing_enabled,
        market_bridges=market_bridges,
    )
    qmt_core_deploy = auto_deploy_qmt_core_for_account(
        row,
        enabled=body.get("auto_deploy_qmt_core", True),
    )
    identity = write_qmt_bridge_identity(row)
    identity["market_identities"] = write_qmt_market_bridge_identities(row)
    runtime = ensure_account_runtime(row["mode"])
    ACCOUNT_CACHE.prime_configured_accounts()
    STATUS_MONITOR.wake()
    CALLBACKS.refresh_channels(callback_channels())
    return {
        "account": row,
        "qmt_core_deploy": qmt_core_deploy,
        "qmt_bridge_identity": identity,
        "runtime": runtime,
        "setup": WEB_CONFIG.setup_info(),
        "account_pairs": WEB_CONFIG.account_pairs(),
        "account_configs": WEB_CONFIG.account_configs(),
        "bridges": WEB_CONFIG.bridges(),
    }


def delete_account_runtime_config(body):
    account_id = str((body or {}).get("account_id") or "").strip()
    account_type = normalize_account_type((body or {}).get("account_type") or "STOCK")
    account_key = str((body or {}).get("account_key") or "").strip()
    if not account_id and not account_key:
        raise ValueError("account_id or account_key is required")
    WEB_CONFIG.delete_pair(account_id=account_id, account_type=account_type, bridge_id=(body or {}).get("bridge_id"), account_key=account_key)
    with WEB_CONFIG._lock:
        configs = WEB_CONFIG._data.setdefault("account_configs", {})
        key = WEB_CONFIG._coerce_account_key_locked(
            account_key=account_key,
            account_id=account_id,
            account_type=account_type,
            bridge_id=(body or {}).get("bridge_id"),
        ) or account_key
        configs.pop(key, None)
        if WEB_CONFIG._data.get("data_provider_account_key") == key:
            WEB_CONFIG._data["data_provider_account_key"] = ""
            WEB_CONFIG._data["data_provider_account_id"] = ""
            WEB_CONFIG._data["data_provider_account_type"] = "STOCK"
        if not configs:
            WEB_CONFIG._data["initialized"] = False
            WEB_CONFIG._data["default_account_id"] = DEFAULT_ACCOUNT_ID
            WEB_CONFIG._data["default_account_type"] = "STOCK"
            WEB_CONFIG._data["default_account_key"] = ""
            WEB_CONFIG._data["transport_mode"] = "ctypes"
            WEB_CONFIG._save_settings_locked({"transport_mode": "ctypes"})
        elif WEB_CONFIG._data.get("default_account_key") == key:
            next_key = next(iter(configs.keys()))
            next_row = configs[next_key]
            WEB_CONFIG._data["default_account_key"] = next_key
            WEB_CONFIG._data["default_account_id"] = str(next_row.get("account_id") or DEFAULT_ACCOUNT_ID).strip() or DEFAULT_ACCOUNT_ID
            WEB_CONFIG._data["default_account_type"] = normalize_account_type(next_row.get("account_type") or "STOCK")
        WEB_CONFIG._save_locked()
    ACCOUNT_CACHE.prime_configured_accounts()
    STATUS_MONITOR.wake()
    CALLBACKS.refresh_channels(callback_channels())
    return {
        "setup": WEB_CONFIG.setup_info(),
        "account_pairs": WEB_CONFIG.account_pairs(),
        "account_configs": WEB_CONFIG.account_configs(),
    }


def initialize_web_setup(body):
    body = body or {}
    account_id = str(body.get("account_id") or DEFAULT_ACCOUNT_ID).strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
    display_name = body.get("display_name") if "display_name" in body else body.get("account_name")
    if not account_id:
        raise ValueError("account_id is required")
    auth_info = WEB_CONFIG.web_auth_info(include_username=True)
    admin_username = str(
        body.get("admin_username") or body.get("web_auth_username") or "admin"
    ).strip()
    admin_password = str(
        body.get("admin_password") or body.get("web_auth_password") or ""
    )
    admin_password_confirm = str(
        body.get("admin_password_confirm") or body.get("web_auth_password_confirm") or ""
    )
    should_register_admin = not auth_info.get("configured")
    if should_register_admin:
        if not admin_username:
            raise ValueError("admin username is required")
        if not admin_password:
            raise ValueError("admin password is required")
        if len(admin_password) < 6:
            raise ValueError("admin password must be at least 6 characters")
        if not admin_password_confirm:
            raise ValueError("admin password confirmation is required")
        if admin_password != admin_password_confirm:
            raise ValueError("admin passwords do not match")
    row = WEB_CONFIG.save_account_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=body.get("bridge_id"),
        display_name=display_name,
        qmt_dir=body.get("qmt_dir") or body.get("python_dir"),
        qmt_trade_dir=(
            body.get("qmt_trade_dir")
            or body.get("trade_qmt_dir")
            or body.get("advanced_qmt_dir")
            or body.get("qmt_trade_core_dir")
        ),
        mode=body.get("mode") or "ctypes",
        data_provider=True,
        enabled=True,
        market_routing_enabled=body.get("market_routing_enabled") if "market_routing_enabled" in body else None,
        market_bridges=body.get("market_bridges") if "market_bridges" in body else body.get("market_routes") if "market_routes" in body else None,
    )
    qmt_core_deploy = auto_deploy_qmt_core_for_account(
        row,
        enabled=body.get("auto_deploy_qmt_core", True),
    )
    identity = write_qmt_bridge_identity(row)
    identity["market_identities"] = write_qmt_market_bridge_identities(row)
    runtime = ensure_account_runtime(row["mode"])
    web_auth = None
    server_access = None
    if should_register_admin:
        server_access = WEB_CONFIG.set_server_access_settings(
            web_auth_enabled=True,
            web_auth_username=admin_username,
            web_auth_password=admin_password,
        )
        token = issue_web_auth_token(admin_username, remember=True)
        web_auth = web_auth_status(token)
        web_auth["token"] = token
        web_auth["remember"] = True
    return {
        "initialized": True,
        "account": row,
        "qmt_core_deploy": qmt_core_deploy,
        "qmt_bridge_identity": identity,
        "runtime": runtime,
        "setup": WEB_CONFIG.setup_info(),
        "server_access": server_access or server_access_info(include_auth_details=True),
        "web_auth": web_auth or WEB_CONFIG.web_auth_info(include_username=True),
        "bridges": WEB_CONFIG.bridges(),
        "account_pairs": WEB_CONFIG.account_pairs(),
        "account_configs": WEB_CONFIG.account_configs(),
    }


def reset_web_setup():
    return WEB_CONFIG.reset_setup()


def set_data_provider(body):
    body = body or {}
    return WEB_CONFIG.set_data_provider_account_id(
        account_id=body.get("account_id"),
        account_type=body.get("account_type") or "STOCK",
        bridge_id=body.get("bridge_id"),
        account_key=body.get("account_key"),
    )


def delete_account_pair(body):
    WEB_CONFIG.delete_pair(
        account_id=(body or {}).get("account_id"),
        account_type=(body or {}).get("account_type") or "STOCK",
        bridge_id=(body or {}).get("bridge_id"),
        account_key=(body or {}).get("account_key"),
    )
    return {
        "account_pairs": WEB_CONFIG.account_pairs(),
    }


def verify_account_pair(body):
    account_id = str((body or {}).get("account_id") or "").strip()
    account_type = normalize_account_type((body or {}).get("account_type") or "STOCK")
    account_key = str((body or {}).get("account_key") or "").strip()
    bridge_id = resolve_bridge_id(
        account_id=account_id,
        account_type=account_type,
        account_key=account_key,
        bridge_id=(body or {}).get("bridge_id"),
    )
    channel = (body or {}).get("channel") or "normal"
    if not account_id:
        raise ValueError("account_id is required")
    bridge_config(bridge_id)
    status = account_route_status(account_id, bridge_id=bridge_id, account_type=account_type, account_key=account_key)
    account = ACCOUNT_CACHE.get_market_routed(
        bridge_id,
        channel,
        account_id,
        ["asset", "positions"],
        force=parse_bool((body or {}).get("force") or "1"),
        account_type=account_type,
        account_key=account_key,
    )
    return {
        "bridge_id": bridge_id,
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
        "channel": channel,
        "status": status,
        "account": account,
    }


def query_credit_account(body):
    body = body or {}
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "CREDIT")
    account_key = str(body.get("account_key") or "").strip()
    if account_type != "CREDIT":
        raise ValueError("credit query requires account_type=CREDIT")
    if not account_id:
        raise ValueError("account_id is required")
    action_key = str(body.get("action") or body.get("query") or "detail").strip().lower()
    action = CREDIT_ACTIONS.get(action_key)
    if not action:
        raise ValueError("unknown credit query action: %s" % action_key)
    bridge_id = resolve_bridge_id(
        account_id=account_id,
        account_type=account_type,
        account_key=account_key,
        bridge_id=body.get("bridge_id"),
    )
    params = account_payload(account_id, account_type)
    started = time.perf_counter()
    route = account_request(
        account_id,
        bridge_id,
        body.get("channel"),
        action,
        params,
        default_channel="normal",
        timeout=float(body.get("timeout") or ACCOUNT_QUERY_TIMEOUT_SECONDS),
        mark_offline_on_timeout=False,
        account_type=account_type,
        account_key=account_key,
    )
    return {
        "bridge_id": route["bridge_id"],
        "bridge_name": bridge_config(route["bridge_id"])["name"],
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "account_key": account_key or account_key_for(account_id, account_type, route["bridge_id"]),
        "action": action,
        "query": action_key,
        "channel": route["channel"],
        "mode": route["mode"],
        "fallback": route["fallback"],
        "fallback_reason": route["fallback_reason"],
        "result": route["result"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "attempts": route.get("attempts") or [],
    }


def probe_credit_account(body):
    body = body or {}
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "CREDIT")
    account_key = str(body.get("account_key") or "").strip()
    if account_type != "CREDIT":
        raise ValueError("credit probe requires account_type=CREDIT")
    if not account_id:
        raise ValueError("account_id is required")
    bridge_id = resolve_bridge_id(
        account_id=account_id,
        account_type=account_type,
        account_key=account_key,
        bridge_id=body.get("bridge_id"),
    )
    timeout = float(body.get("timeout") or min(ACCOUNT_QUERY_TIMEOUT_SECONDS, 5.0))
    params = account_payload(account_id, account_type)
    checks = []
    capabilities = {}
    started = time.perf_counter()
    for name, action in CREDIT_PROBE_ACTIONS:
        item_started = time.perf_counter()
        try:
            route = account_request(
                account_id,
                bridge_id,
                body.get("channel"),
                action,
                params,
                default_channel="normal",
                timeout=timeout,
                mark_offline_on_timeout=False,
                ignore_cooldown=True,
                account_type=account_type,
                account_key=account_key,
            )
            capabilities[name] = True
            checks.append({
                "name": name,
                "action": action,
                "ok": True,
                "mode": route.get("mode"),
                "channel": route.get("channel"),
                "latency_ms": round((time.perf_counter() - item_started) * 1000, 2),
            })
        except Exception as error:
            capabilities[name] = False
            checks.append({
                "name": name,
                "action": action,
                "ok": False,
                "error": str(error),
                "latency_ms": round((time.perf_counter() - item_started) * 1000, 2),
            })
    return {
        "bridge_id": bridge_id,
        "bridge_name": bridge_config(bridge_id)["name"],
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
        "capabilities": capabilities,
        "checks": checks,
        "supported_count": sum(1 for value in capabilities.values() if value),
        "total_count": len(capabilities),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def parse_export_user_param(value):
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("user_param must be a JSON object")
        return parsed
    raise ValueError("user_param must be an object")


def export_trade_data(body):
    body = body or {}
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
    account_key = str(body.get("account_key") or "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    result_path = str(body.get("result_path") or "").strip()
    data_type = str(body.get("data_type") or "").strip()
    start_time = str(body.get("start_time") or "").strip() or None
    end_time = str(body.get("end_time") or "").strip() or None
    user_param = parse_export_user_param(body.get("user_param"))
    job_id = str(body.get("job_id") or "").strip()
    if not result_path:
        raise ValueError("result_path is required")
    if not data_type:
        raise ValueError("data_type is required")
    bridge_id = resolve_bridge_id(
        account_id=account_id,
        account_type=account_type,
        account_key=account_key,
        bridge_id=body.get("bridge_id"),
    )
    params = {
        "account": {"account_id": account_id, "account_type": account_type},
        "args": [result_path, data_type, start_time, end_time, user_param],
    }
    started = time.perf_counter()
    route = account_request(
        account_id,
        bridge_id,
        body.get("channel"),
        "xttrader.export_data",
        params,
        default_channel="trade",
        timeout=float(body.get("timeout") or 120.0),
        mark_offline_on_timeout=False,
        account_type=account_type,
        account_key=account_key,
    )
    return {
        "job_id": job_id,
        "bridge_id": route["bridge_id"],
        "account_id": account_id,
        "account_type": account_type,
        "account_key": account_key or account_key_for(account_id, account_type, route["bridge_id"]),
        "channel": route["channel"],
        "mode": route["mode"],
        "fallback": route["fallback"],
        "fallback_reason": route["fallback_reason"],
        "result_path": result_path,
        "data_type": data_type,
        "result": route["result"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "attempts": route.get("attempts") or [],
    }


def api_key_info(include_secret=True):
    return WEB_CONFIG.api_key_info(include_secret=include_secret)


def save_api_key(body):
    body = body or {}
    if parse_bool(body.get("generate")):
        return WEB_CONFIG.generate_api_key()
    return WEB_CONFIG.set_api_key(body.get("api_key"))


def server_access_info(include_auth_details=True):
    return WEB_CONFIG.server_access_info(
        bound_host=WEB_BOUND_HOST,
        bound_port=WEB_BOUND_PORT,
        include_auth_details=include_auth_details,
    )


def transport_info():
    mode = default_runtime_client_mode()
    return {
        "transport": WEB_CONFIG.transport_info(),
        "client": {
            "mode": mode,
            "request_channel": CHANNELS["normal"],
        },
    }


def save_transport(body):
    body = body or {}
    mode = body.get("mode") or body.get("transport") or body.get("transport_mode")
    bridge_id = body.get("bridge_id") or DEFAULT_BRIDGE_ID
    mode = normalize_transport_mode(mode)
    lttx = ensure_lttx_started("运行模式切换预启动")
    if mode == "lttx":
        readiness = _advanced_mode_readiness(bridge_id)
        if not readiness["ready"]:
            missing = "、".join(readiness["missing"]) or "普通通道、交易通道"
            raise RuntimeError("高级模式需要%s都在线后才能启用，当前缺少：%s" % ("普通通道和交易通道", missing))
    info = WEB_CONFIG.set_transport_mode(mode)
    # 高级模式也保留 PipeHub，账号级 LTtx 失败时需要无感回退到 ctypes。
    hub = start_pipe_hub()
    CLIENTS.close(mode)
    CLIENTS.start(mode)
    STATUS_MONITOR.wake()
    CALLBACKS.refresh_channels(callback_channels())
    return {
        "transport": info,
        "client": transport_info()["client"],
        "readiness": _advanced_mode_readiness(bridge_id) if mode == "lttx" else {"ready": True, "mode": mode},
        "pipe_hub": hub,
        "lttx": lttx,
    }


def pipe_hub_info():
    return PIPE_HUB.status()


def start_pipe_hub():
    return PIPE_HUB.start()


def stop_pipe_hub():
    return PIPE_HUB.stop()


def save_server_access(body):
    body = body or {}
    allow_remote = parse_bool(body.get("allow_remote")) if "allow_remote" in body else None
    web_auth_enabled = parse_bool(body.get("web_auth_enabled")) if "web_auth_enabled" in body else None
    web_auth_password = body.get("web_auth_password") if "web_auth_password" in body else None
    return WEB_CONFIG.set_server_access_settings(
        allow_remote=allow_remote,
        api_base_url=body.get("api_base_url") if "api_base_url" in body else None,
        web_port=body.get("web_port") if "web_port" in body else body.get("port"),
        allowed_domains=(
            body.get("allowed_domains")
            if "allowed_domains" in body
            else body.get("domain_whitelist") if "domain_whitelist" in body else None
        ),
        web_auth_enabled=web_auth_enabled,
        web_auth_username=body.get("web_auth_username") if "web_auth_username" in body else body.get("username"),
        web_auth_password=web_auth_password,
    )


def web_auth_status(token=None):
    enabled = WEB_CONFIG.web_auth_enabled()
    token_info = web_auth_token_info(token)
    authenticated = bool(token_info)
    return {
        "enabled": enabled,
        "authenticated": authenticated,
        "username": token_info.get("username") if token_info else "",
        "created_at": token_info.get("created_at") if token_info else 0,
        "expires_at": token_info.get("expires_at") if token_info else 0,
        "persistent": bool(token_info.get("persistent")) if token_info else False,
    }


def web_auth_login(body):
    body = body or {}
    if not WEB_CONFIG.web_auth_enabled():
        return web_auth_status()
    username = str(body.get("username") or body.get("web_auth_username") or "").strip()
    password = str(body.get("password") or body.get("web_auth_password") or "")
    if not WEB_CONFIG.verify_web_auth(username, password):
        raise PermissionError("invalid username or password")
    remember = True
    token = issue_web_auth_token(username, remember=remember)
    result = web_auth_status(token)
    result["token"] = token
    result["remember"] = remember
    return result


def web_auth_logout(token):
    revoke_web_auth_token(token)
    return web_auth_status()


def web_reload_info(reason="settings"):
    access = server_access_info()
    return {
        "restarting": True,
        "reason": reason,
        "requested_at": time.time(),
        "next_url": access.get("next_url") or access.get("configured_local_url") or "",
        "server_access": access,
    }


def schedule_web_reload(server, reload_info):
    global WEB_RESTART_REQUEST
    if server is None:
        raise RuntimeError("web server instance is not available")
    with WEB_RESTART_LOCK:
        WEB_RESTART_REQUEST = dict(reload_info or {})

    def shutdown_later():
        time.sleep(0.7)
        try:
            server.shutdown()
        except Exception as e:
            safe_print("cfquant web reload shutdown failed: %s" % e)

    thread = threading.Thread(target=shutdown_later)
    thread.daemon = True
    thread.start()


def log_cleanup_info():
    return LOG_CLEANUP.status()


def save_log_cleanup_settings(body):
    body = body or {}
    WEB_CONFIG.set_log_cleanup_settings(
        cleanup_qmt_userdata_logs=parse_bool(body.get("qmt_userdata_log_cleanup_enabled")),
    )
    LOG_CLEANUP.wake()
    return LOG_CLEANUP.status()


def run_log_cleanup(body):
    body = body or {}
    if "qmt_userdata_log_cleanup_enabled" in body:
        WEB_CONFIG.set_log_cleanup_settings(
            cleanup_qmt_userdata_logs=parse_bool(body.get("qmt_userdata_log_cleanup_enabled")),
        )
    return LOG_CLEANUP.run_once(reason="manual")


def qmt_log_language_info():
    return WEB_CONFIG.qmt_log_language_info()


def save_qmt_log_language(body):
    body = body or {}
    enabled = body.get("enabled") if "enabled" in body else body.get("show")
    info = WEB_CONFIG.set_qmt_log_language(body.get("language") or body.get("lang"), enabled=enabled)
    bridge_id = body.get("bridge_id")
    targets = [normalize_bridge_id(bridge_id)] if bridge_id else list(current_bridges().keys())
    results = []
    for target_bridge_id in targets:
        for channel in ("normal", "trade"):
            try:
                language_result = CLIENTS.request(
                    target_bridge_id,
                    channel,
                    "cfquant.set_log_language",
                    {"language": info["language"]},
                    timeout=3.0,
                    ignore_cooldown=True,
                )
                enabled_result = CLIENTS.request(
                    target_bridge_id,
                    channel,
                    "cfquant.set_log_enabled",
                    {"enabled": info["enabled"]},
                    timeout=3.0,
                    ignore_cooldown=True,
                )
                results.append({
                    "bridge_id": target_bridge_id,
                    "channel": channel,
                    "ok": True,
                    "result": {
                        "language": language_result,
                        "enabled": enabled_result,
                    },
                })
            except Exception as e:
                results.append({
                    "bridge_id": target_bridge_id,
                    "channel": channel,
                    "ok": False,
                    "error": str(e),
                })
    info["dispatch_results"] = results
    try:
        info["identity_results"] = sync_qmt_bridge_identities()
    except Exception as e:
        info["identity_error"] = str(e)
    return info


def bridge_update_status(bridge_id=None, repo_url=None, ref=None):
    return UPDATER.status(bridge_id or DEFAULT_BRIDGE_ID, repo_url=repo_url, ref=ref)


def lttx_server_reachable(timeout=0.35):
    try:
        sock = socket.create_connection((LTTX_HOST, int(LTTX_PORT)), timeout=float(timeout))
        sock.close()
        return True
    except Exception:
        return False


def read_lttx_runtime_report(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    if not lttx_server_reachable():
        return None
    tx = None
    latest = None
    try:
        tx = txl(LTTX_HOST, LTTX_PORT, "LTtx", show=False)
        tx.start_tx(mode="probe")
        base_key = "cfquant.qmt.runtime.%s" % bridge_id
        for key in ("%s.normal" % base_key, "%s.trade" % base_key, base_key):
            value = tx.get(key)
            if isinstance(value, str):
                try:
                    data = json.loads(value)
                except Exception:
                    data = {}
            elif isinstance(value, dict):
                data = value
            else:
                data = {}
            if not isinstance(data, dict) or not data.get("core_version"):
                continue
            report = RUNTIME_VERSIONS.update_from_event({
                "type": "event",
                "event": "cfquant.runtime",
                "bridge_id": bridge_id,
                "data": data,
                "meta": {"bridge_id": bridge_id, "source": "lttx_registry"},
            })
            latest = report or latest
        return latest
    except Exception:
        return None
    finally:
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass


def read_qmt_runtime_marker_reports(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    latest = None
    try:
        for data in read_qmt_runtime_marker_files([QMT_RUNTIME_MARKER_DIR], max_files=256):
            item_bridge_id = normalize_bridge_id(data.get("bridge_id") or DEFAULT_BRIDGE_ID)
            if item_bridge_id != bridge_id:
                continue
            report = RUNTIME_VERSIONS.update_from_event({
                "type": "event",
                "event": "cfquant.runtime",
                "bridge_id": item_bridge_id,
                "data": data,
                "meta": {"bridge_id": item_bridge_id, "source": "qmt_runtime_marker"},
            })
            if not report:
                continue
            if latest is None or float(report.get("reported_at") or 0) > float(latest.get("reported_at") or 0):
                latest = report
    except Exception as e:
        safe_print("qmt runtime marker read failed: %s" % e)
    return latest


def runtime_probe_modes(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    modes = []
    for config in enabled_account_configs().values():
        if normalize_bridge_id(config.get("bridge_id") or DEFAULT_BRIDGE_ID) != bridge_id:
            continue
        if not config.get("enabled", True):
            continue
        try:
            mode = normalize_transport_mode(config.get("mode") or default_runtime_client_mode())
        except Exception:
            continue
        if mode not in modes:
            modes.append(mode)
    if bridge_has_lttx_account(bridge_id) and "lttx" not in modes:
        modes.append("lttx")
    if not modes:
        modes.append(default_runtime_client_mode())
    if not any(is_ctypes_transport_mode(item) for item in modes):
        modes.append("ctypes")
    return modes


def refresh_runtime_version_report(bridge_id=None, timeout=1.6):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    errors = []
    read_qmt_runtime_marker_reports(bridge_id)
    read_lttx_runtime_report(bridge_id)
    for mode in runtime_probe_modes(bridge_id):
        if is_ctypes_transport_mode(mode):
            try:
                if not PIPE_HUB.status().get("running"):
                    errors.append("ctypes: PipeHub 未运行")
                    continue
            except Exception as e:
                errors.append("ctypes: %s" % e)
                continue
        for channel_key in ("normal", "trade"):
            try:
                status = CLIENTS.request(
                    bridge_id,
                    channel_key,
                    "cfquant.status",
                    {},
                    timeout=timeout,
                    mark_offline_on_timeout=False,
                    ignore_cooldown=True,
                    mode=mode,
                )
                report = RUNTIME_VERSIONS.update_from_status(
                    bridge_id,
                    channel_key,
                    status,
                    mode=mode,
                    source="cfquant.status.refresh",
                )
                if not report:
                    errors.append("%s/%s: QMT 已响应但未包含运行时版本字段" % (mode, channel_key))
            except Exception as e:
                errors.append("%s/%s: %s" % (mode, channel_key, e))
    report = RUNTIME_VERSIONS.latest(bridge_id)
    report["probe_attempted"] = True
    report["probe_errors"] = errors[-6:]
    if not report.get("reported") and any("未包含运行时版本字段" in item for item in errors):
        report["message"] = "QMT 已响应，但当前运行入口未上报版本；请重启已更新的 QMT 桥接脚本后再查看"
    return report


_PROJECT_VERSION_CACHE = {}
_PROJECT_VERSION_LOCK = threading.RLock()


def _read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _extract_latest_changelog(changelog_text):
    result = {
        "version": "",
        "body": "",
        "items": [],
    }
    if not changelog_text:
        return result
    match = re.search(r"(?m)^##\s+版本日志\s*$", changelog_text)
    if not match:
        return result
    section = changelog_text[match.end():]
    next_section = re.search(r"(?m)^##\s+", section)
    if next_section:
        section = section[:next_section.start()]
    heading = re.search(r"(?m)^###\s+(.+?)\s*$", section)
    if not heading:
        return result
    body = section[heading.end():]
    next_heading = re.search(r"(?m)^###\s+", body)
    if next_heading:
        body = body[:next_heading.start()]
    items = []
    for line in body.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("- "):
            text = text[2:].strip()
        items.append(text)
    heading_text = heading.group(1).strip()
    version_match = re.search(r"\b(?:core|web)_\d{8}(?:[_-]\d+)?\b", heading_text)
    result["version"] = version_match.group(0) if version_match else heading_text
    result["body"] = body.strip()
    result["items"] = items[:12]
    return result


def _parse_github_repo_name(repo_url):
    value = str(repo_url or "").strip()
    value = re.sub(r"\.git$", "", value)
    patterns = [
        r"github\.com[:/]+([^/\s]+)/([^/\s#?]+)",
        r"^([^/\s]+)/([^/\s#?]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1), match.group(2)
    raise ValueError("无法识别 GitHub 仓库地址: %s" % repo_url)


def _github_raw_file_url(repo_url, ref, path):
    owner, repo = _parse_github_repo_name(repo_url)
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    ref_q = urllib.parse.quote(str(ref or "main").strip() or "main", safe="/")
    path_q = "/".join(urllib.parse.quote(part, safe="") for part in str(path or "").replace("\\", "/").split("/") if part)
    return "https://raw.githubusercontent.com/%s/%s/%s/%s" % (owner_q, repo_q, ref_q, path_q)


def _github_raw_readme_url(repo_url, ref):
    return _github_raw_file_url(repo_url, ref, "README.md")


def _github_raw_changelog_url(repo_url, ref):
    return _github_raw_file_url(repo_url, ref, "docs/版本日志.md")


def _version_sort_key(version):
    match = re.search(r"(\d{8})(?:[_-](\d+))?", str(version or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def _compare_project_versions(current_version, remote_version):
    current = str(current_version or "").strip()
    remote = str(remote_version or "").strip()
    if not remote:
        return "unknown"
    if current == remote:
        return "same"
    current_key = _version_sort_key(current)
    remote_key = _version_sort_key(remote)
    if current_key and remote_key:
        if remote_key > current_key:
            return "newer"
        if remote_key < current_key:
            return "older"
    return "different"


def _local_project_version_info():
    changelog_path = os.path.join(BASE_DIR, "docs", "版本日志.md")
    changelog_text = _read_text_file(changelog_path)
    if not changelog_text:
        changelog_path = os.path.join(BASE_DIR, "README.md")
        changelog_text = _read_text_file(changelog_path)
    changelog = _extract_latest_changelog(changelog_text)
    core_info = current_core_version_info()
    version = core_info["version"]
    return {
        "version": version,
        "changelog_version": changelog.get("version") or "",
        "source": core_info["source"],
        "version_path": core_info["path"],
        "file_version": core_info["file_version"],
        "imported_version": core_info["imported_version"],
        "import_stale": core_info["import_stale"],
        "checked_at": core_info["checked_at"],
        "checked_at_text": core_info["checked_at_text"],
        "changelog_path": changelog_path,
        "matches_changelog": (changelog.get("version") or "") == version if changelog.get("version") else None,
        "changelog": changelog,
    }


def _remote_project_version_info(repo_url=None, ref=None, force=False):
    repo_url = str(repo_url or DEFAULT_UPDATE_REPO_URL).strip()
    ref = str(ref or DEFAULT_UPDATE_REF).strip() or "main"
    site_url = normalize_official_site_url()
    cache_key = "%s#%s#%s" % (site_url, repo_url, ref)
    now = time.time()
    if not force:
        with _PROJECT_VERSION_LOCK:
            cached = _PROJECT_VERSION_CACHE.get(cache_key)
            if cached and now - float(cached.get("checked_at") or 0) < UPDATE_REMOTE_CACHE_SECONDS:
                result = dict(cached)
                result["cached"] = True
                return result
    result = {
        "repo_url": repo_url,
        "official_site_url": DEFAULT_OFFICIAL_SITE_URL,
        "ref": ref,
        "site_url": site_url,
        "changelog_url": "",
        "version": "",
        "core_version": "",
        "web_version": "",
        "checked_at": now,
        "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "cached": False,
        "error": "",
        "source": "",
        "download_url": "",
        "sha256": "",
        "fallback_error": "",
        "changelog": {
            "version": "",
            "body": "",
            "items": [],
        },
    }
    try:
        release = official_release_info(site_url)
        changelog = release.get("changelog") if isinstance(release.get("changelog"), dict) else {}
        core_version = str(release.get("core_version") or release.get("version") or "")
        web_version = str(release.get("web_version") or "")
        result.update({
            "version": core_version,
            "core_version": core_version,
            "web_version": web_version,
            "source": "cfquant.org",
            "download_url": str(release.get("download_url") or ""),
            "sha256": str(release.get("sha256") or ""),
            "changelog": {
                "version": changelog.get("version") or release.get("version") or "",
                "body": changelog.get("body") or release.get("notes") or "",
                "items": changelog.get("items") if isinstance(changelog.get("items"), list) else [],
            },
        })
        if not result["version"]:
            result["error"] = "官网未返回版本号"
    except Exception as e:
        result["fallback_error"] = str(e) or repr(e)
    if result.get("error") or not result.get("version"):
        if not repo_url:
            result["error"] = "官网不可用且未配置 GitHub 仓库: %s" % (result.get("fallback_error") or "")
            return result
        errors = []
        for path, url_factory in (
            ("docs/版本日志.md", _github_raw_changelog_url),
            ("README.md", _github_raw_readme_url),
        ):
            try:
                url = url_factory(repo_url, ref)
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "cfquant-web/%s" % current_core_version()},
                )
                with urllib.request.urlopen(request, timeout=UPDATE_REMOTE_TIMEOUT_SECONDS) as response:
                    raw = response.read(512 * 1024)
                text = raw.decode("utf-8", errors="replace")
                changelog = _extract_latest_changelog(text)
                if not changelog.get("version"):
                    errors.append("%s 未解析到版本日志" % path)
                    continue
                result["changelog_url"] = url
                result["changelog"] = changelog
                result["version"] = changelog.get("version") or ""
                result["source"] = "github"
                break
            except Exception as e:
                errors.append("%s: %s" % (path, str(e) or repr(e)))
        if not result["version"]:
            result["error"] = "远端未解析到版本日志：%s" % "; ".join(errors)
    with _PROJECT_VERSION_LOCK:
        _PROJECT_VERSION_CACHE[cache_key] = dict(result)
    return result


def project_version_info(include_remote=False, force=False, repo_url=None, ref=None, bridge_id=None):
    repo_url = str(repo_url or DEFAULT_UPDATE_REPO_URL).strip()
    ref = str(ref or DEFAULT_UPDATE_REF).strip() or "main"
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    local = _local_project_version_info()
    core_version = local.get("version") or current_core_version()
    read_qmt_runtime_marker_reports(bridge_id)
    qmt_runtime = refresh_runtime_version_report(bridge_id, timeout=1.2) if force else RUNTIME_VERSIONS.latest(bridge_id)
    qmt_runtime_version = qmt_runtime.get("version") if qmt_runtime.get("reported") else ""
    latest_qmt_core_version = qmt_runtime.get("version") if qmt_runtime.get("has_report") else ""
    data = {
        "current_version": core_version,
        "core_version": core_version,
        "imported_core_version": CORE_VERSION,
        "core_version_source": local.get("source") or "",
        "core_version_path": local.get("version_path") or "",
        "core_version_import_stale": bool(local.get("import_stale")),
        "web_version": WEB_VERSION,
        "frontend_version": WEB_VERSION,
        "qmt_runtime": qmt_runtime,
        "qmt_runtime_version": qmt_runtime_version,
        "qmt_runtime_reported": bool(qmt_runtime.get("reported")),
        "latest_qmt_core_version": latest_qmt_core_version,
        "qmt_builtin_version": latest_qmt_core_version,
        "qmt_saved_report": qmt_runtime if qmt_runtime.get("has_report") else {},
        "qmt_runtime_stale": bool(qmt_runtime.get("stale")),
        "bridge_id": bridge_id,
        "repo_url": repo_url,
        "ref": ref,
        "local": local,
        "remote": None,
        "comparison": "unchecked",
        "update_available": None,
    }
    if include_remote:
        remote = _remote_project_version_info(repo_url=repo_url, ref=ref, force=force)
        comparison = _compare_project_versions(core_version, remote.get("core_version") or remote.get("version"))
        web_comparison = _compare_project_versions(WEB_VERSION, remote.get("web_version")) if remote.get("web_version") else "unknown"
        if web_comparison in ("newer", "different") and comparison in ("same", "unknown"):
            comparison = web_comparison
        data["remote"] = remote
        data["comparison"] = comparison
        data["web_comparison"] = web_comparison
        data["update_available"] = comparison in ("newer", "different") or web_comparison in ("newer", "different")
        qmt_runtime_comparison = _compare_project_versions(qmt_runtime_version, remote.get("core_version") or remote.get("version")) if qmt_runtime_version else "unknown"
        qmt_saved_comparison = _compare_project_versions(latest_qmt_core_version, remote.get("core_version") or remote.get("version")) if latest_qmt_core_version else "unknown"
        qmt_version_comparison = qmt_runtime_comparison if qmt_runtime_version else qmt_saved_comparison
        data["qmt_runtime_comparison"] = qmt_runtime_comparison
        data["qmt_saved_comparison"] = qmt_saved_comparison
        data["qmt_version_comparison"] = qmt_version_comparison
        data["qmt_update_available"] = qmt_version_comparison in ("newer", "different")
    return data


def bridge_update_github(body):
    body = body or {}
    bridge_id = normalize_bridge_id(body.get("bridge_id") or DEFAULT_BRIDGE_ID)
    repo_url = body.get("repo_url") or body.get("url") or DEFAULT_UPDATE_REPO_URL
    ref = body.get("ref") or body.get("branch") or body.get("tag") or DEFAULT_UPDATE_REF
    return UPDATER.update_from_github(
        bridge_id,
        repo_url,
        ref,
    )


def bridge_update_official(body):
    body = body or {}
    bridge_id = normalize_bridge_id(body.get("bridge_id") or DEFAULT_BRIDGE_ID)
    return UPDATER.update_from_official(
        bridge_id,
        site_url=body.get("site_url") or body.get("official_site_url") or DEFAULT_OFFICIAL_SITE_URL,
        fallback_repo_url=body.get("repo_url") or body.get("url") or DEFAULT_UPDATE_REPO_URL,
        fallback_ref=body.get("ref") or body.get("branch") or body.get("tag") or DEFAULT_UPDATE_REF,
    )


def bridge_update_rollback(body):
    body = body or {}
    bridge_id = normalize_bridge_id(body.get("bridge_id") or DEFAULT_BRIDGE_ID)
    return UPDATER.rollback(bridge_id, body.get("backup") or body.get("backup_name"))


def project_update_status(repo_url=None, ref=None, include_remote=True):
    return PROJECT_UPDATER.status(repo_url=repo_url, ref=ref, include_remote=include_remote)


def project_update_github(body):
    body = body or {}
    repo_url = body.get("repo_url") or body.get("url") or DEFAULT_UPDATE_REPO_URL
    ref = body.get("ref") or body.get("branch") or body.get("tag") or DEFAULT_UPDATE_REF
    return PROJECT_UPDATER.update_from_github(repo_url, ref)


def project_update_official(body):
    body = body or {}
    return PROJECT_UPDATER.update_from_official(
        site_url=body.get("site_url") or body.get("official_site_url") or DEFAULT_OFFICIAL_SITE_URL,
        fallback_repo_url=body.get("repo_url") or body.get("url") or DEFAULT_UPDATE_REPO_URL,
        fallback_ref=body.get("ref") or body.get("branch") or body.get("tag") or DEFAULT_UPDATE_REF,
    )


def project_update_rollback(body):
    body = body or {}
    return PROJECT_UPDATER.rollback(body.get("backup") or body.get("backup_name"))


def quote_status():
    return QUOTES.status()


def subscribe_whole_quote(body):
    return QUOTES.subscribe_whole(body or {})


def unsubscribe_quote(body):
    return QUOTES.unsubscribe(body or {})


def parse_csv_list(value):
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def channel_online(bridge_id, channel):
    try:
        snapshot = STATUS_MONITOR.latest(bridge_id=bridge_id)
        monitor = snapshot.get("monitor") if isinstance(snapshot, dict) else {}
        if monitor and not monitor.get("ready", False):
            return None
        info = snapshot.get(channel) if isinstance(snapshot, dict) else None
        if not isinstance(info, dict):
            return None
        return bool(info.get("online"))
    except Exception:
        return None


def data_channel_request(body, action, params, default_channel="trade", force_channel=None):
    body = body or {}
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
    account_key = str(body.get("account_key") or "").strip()
    preferred_channel = force_channel or body.get("channel")
    timeout = request_timeout_value(body.get("timeout"), default=12.0)
    started = time.perf_counter()
    requested_default = force_channel or preferred_channel or default_channel
    if account_id:
        route = routed_xtdata_account_request(
            account_id,
            body.get("bridge_id"),
            preferred_channel,
            action,
            params,
            default_channel=requested_default,
            timeout=timeout,
            mark_offline_on_timeout=True,
            account_type=account_type,
            account_key=account_key,
        )
        provider_account_id = account_id
        provider_account_type = account_type
        provider_account_key = account_key or account_key_for(account_id, account_type, route["bridge_id"])
        provider_fallback = bool(route.get("fallback"))
        provider_attempts = route.get("attempts") or []
    else:
        route = data_provider_request(
            action,
            params,
            requested_channel=preferred_channel,
            default_channel=requested_default,
            timeout=timeout,
            bridge_id=body.get("bridge_id"),
        )
        provider_account_id = route.get("data_provider") or configured_default_account_id()
        provider_account_type = route.get("data_provider_account_type") or configured_default_account_type()
        provider_account_key = route.get("data_provider_account_key") or ""
        provider_fallback = bool(route.get("provider_fallback"))
        provider_attempts = route.get("provider_attempts") or []
    return {
        "bridge_id": route["bridge_id"],
        "account_id": provider_account_id,
        "account_type": provider_account_type,
        "account_key": provider_account_key,
        "preferred_channel": preferred_channel or default_channel,
        "channel": route["channel"],
        "mode": route["mode"],
        "fallback": route["fallback"],
        "fallback_reason": route["fallback_reason"],
        "data_provider": not account_id,
        "provider_fallback": provider_fallback,
        "provider_attempts": provider_attempts,
        "action": action,
        "result": route["result"],
        "attempts": route["attempts"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def financial_stock_list(body):
    stock_list = parse_csv_list(
        body.get("stock_list")
        or body.get("code_list")
        or body.get("stock_code")
    )
    if not stock_list:
        raise ValueError("stock_code or stock_list is required")
    return stock_list


def financial_field_list(body):
    fields = parse_csv_list(
        body.get("field_list")
        or body.get("fields")
        or body.get("financial_fields")
    )
    tables = financial_table_list(body)
    if len(tables) == 1:
        table = tables[0]
        fields = [
            field if "." in field or "。" in field else "%s.%s" % (table, field)
            for field in fields
        ]
    return fields


def financial_table_list(body):
    return parse_csv_list(
        body.get("table_list")
        or body.get("tables")
        or body.get("table")
        or body.get("financial_table")
    )


def default_financial_field(table):
    table = str(table or "").strip().upper()
    defaults = {
        "ASHAREBALANCESHEET": "fix_assets",
        "ASHAREINCOME": "net_profit_excl_min_int_inc",
        "ASHARECASHFLOW": "net_cash_flows_oper_act",
        "CAPITALSTRUCTURE": "capital",
        "PERSHAREINDEX": "eps",
    }
    return defaults.get(table, "fix_assets")


def financial_probe_field_list(body):
    fields = financial_field_list(body)
    if fields:
        return fields
    tables = financial_table_list(body) or ["ASHAREBALANCESHEET"]
    return ["%s.%s" % (tables[0], default_financial_field(tables[0]))]


def summarize_data_result(value):
    if value is None:
        return {"type": "None", "empty": True}
    type_name = value.__class__.__name__
    if type_name == "DataFrame":
        shape = list(getattr(value, "shape", []) or [])
        columns = [str(item) for item in list(getattr(value, "columns", []) or [])[:20]]
        return {
            "type": "DataFrame",
            "shape": shape,
            "columns": columns,
            "empty": bool(getattr(value, "empty", False)),
        }
    if type_name == "Series":
        size = int(getattr(value, "size", 0) or 0)
        return {"type": "Series", "count": size, "empty": size <= 0}
    if isinstance(value, dict):
        keys = [str(item) for item in list(value.keys())[:20]]
        return {
            "type": "dict",
            "count": len(value),
            "keys": keys,
            "empty": len(value) <= 0,
        }
    if isinstance(value, (list, tuple, set)):
        return {
            "type": type_name,
            "count": len(value),
            "empty": len(value) <= 0,
        }
    return {
        "type": type_name,
        "preview": str(value)[:200],
        "empty": False,
    }


def get_full_tick(body):
    body = body or {}
    return data_channel_request(body, "xtdata.get_full_tick", {
        "code_list": parse_csv_list(body.get("code_list") or body.get("stock_list")),
    })


def get_market_data(body, ex=False):
    body = body or {}
    params = {
        "field_list": parse_csv_list(body.get("field_list")),
        "stock_list": parse_csv_list(body.get("stock_list") or body.get("code_list")),
        "period": str(body.get("period") or "1d"),
        "start_time": str(body.get("start_time") or ""),
        "end_time": str(body.get("end_time") or ""),
        "count": int(body.get("count") if str(body.get("count") or "") else -1),
        "dividend_type": str(body.get("dividend_type") or "none"),
        "fill_data": parse_bool(body.get("fill_data") if body.get("fill_data") is not None else True),
    }
    return data_channel_request(body, "xtdata.get_market_data_ex" if ex else "xtdata.get_market_data", params)


def subscribe_single_quote(body):
    body = body or {}
    stock_code = str(body.get("stock_code") or "").strip()
    if not stock_code:
        raise ValueError("stock_code is required")
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
    account_key = str(body.get("account_key") or "").strip()
    timeout = request_timeout_value(body.get("timeout"), default=12.0)
    started = time.perf_counter()
    QUOTES.start()
    params = {
        "stock_code": stock_code,
        "period": str(body.get("period") or "1d"),
        "start_time": str(body.get("start_time") or ""),
        "end_time": str(body.get("end_time") or ""),
        "count": int(body.get("count") if str(body.get("count") or "") else 0),
        "dividend_type": str(body.get("dividend_type") or "none"),
    }
    if account_id:
        route = routed_xtdata_account_request(
            account_id,
            body.get("bridge_id"),
            body.get("channel"),
            "xtdata.subscribe_quote",
            params,
            default_channel="normal",
            timeout=timeout,
            mark_offline_on_timeout=True,
            ignore_cooldown=True,
            account_type=account_type,
            account_key=account_key,
        )
        provider_account_id = account_id
        provider_account_type = account_type
        provider_account_key = account_key or account_key_for(account_id, account_type, route["bridge_id"])
    else:
        route = data_provider_request(
            "xtdata.subscribe_quote",
            params,
            requested_channel=body.get("channel"),
            default_channel="normal",
            timeout=timeout,
            bridge_id=body.get("bridge_id"),
        )
        provider_account_id = route.get("data_provider") or configured_default_account_id()
        provider_account_type = route.get("data_provider_account_type") or configured_default_account_type()
        provider_account_key = route.get("data_provider_account_key") or ""
    result = route["result"]
    channel = route["channel"]
    bridge_id = route["bridge_id"]
    subscribe_id = str(result.get("subscribe_id") if isinstance(result, dict) else result)
    with QUOTES._lock:
        QUOTES._subscriptions[subscribe_id] = {
            "subscribe_id": subscribe_id,
            "bridge_id": bridge_id,
            "channel": channel,
            "mode": route["mode"],
            "account_id": provider_account_id,
            "account_type": provider_account_type,
            "account_key": provider_account_key,
            "kind": "quote",
            "stock_code": stock_code,
            "period": str(body.get("period") or "1d"),
            "created_at": time.time(),
            "event_count": 0,
        }
    return {
        "subscribe_id": subscribe_id,
        "bridge_id": bridge_id,
        "channel": channel,
        "mode": route["mode"],
        "account_id": provider_account_id,
        "account_type": provider_account_type,
        "account_key": provider_account_key,
        "fallback": route["fallback"],
        "kind": "quote",
        "stock_code": stock_code,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def get_instrument_detail(body):
    body = body or {}
    stock_code = str(body.get("stock_code") or "").strip()
    if not stock_code:
        raise ValueError("stock_code is required")
    return data_channel_request(body, "xtdata.get_instrument_detail", {
        "stock_code": stock_code,
        "iscomplete": parse_bool(body.get("iscomplete")),
    })


def get_stock_list_in_sector(body):
    body = body or {}
    return data_channel_request(body, "xtdata.get_stock_list_in_sector", {
        "sector_name": str(body.get("sector_name") or ""),
    })


def download_job_id(body, prefix):
    value = str((body or {}).get("job_id") or (body or {}).get("download_job_id") or "").strip()
    return value or new_id(prefix)


def download_progress_path(job_id, bridge_id="", account_id=""):
    query = urllib.parse.urlencode({
        key: value
        for key, value in {
            "event_prefix": DOWNLOAD_EVENT_PREFIX,
            "job_id": job_id,
            "bridge_id": bridge_id,
            "account_id": account_id,
        }.items()
        if value
    })
    return "/ws/callbacks?%s" % query if query else "/ws/callbacks"


def with_download_response(route, job_id, download_type, fallback_note=""):
    route["job_id"] = job_id
    route["download_type"] = download_type
    route["callback_event"] = DOWNLOAD_CALLBACK_EVENT
    route["progress_event_prefix"] = DOWNLOAD_EVENT_PREFIX
    route["progress_ws_path"] = download_progress_path(
        job_id,
        bridge_id=route.get("bridge_id") or "",
    )
    route["progress_supported"] = True
    if fallback_note:
        route["progress_note"] = fallback_note
    return route


def emit_download_progress(job_id, download_type, stage, data=None, bridge_id="", account_id=""):
    meta = {
        "download": True,
        "download_kind": download_type,
        "stage": stage,
        "job_id": str(job_id or ""),
        "source": "web",
    }
    if bridge_id:
        meta["bridge_id"] = bridge_id
    event = {
        "type": "event",
        "event": DOWNLOAD_CALLBACK_EVENT,
        "bridge_id": bridge_id,
        "account_id": str(account_id or ""),
        "data": data if data is not None else {},
        "meta": meta,
    }
    CALLBACKS._append(event)
    return event


def download_cached_event_count(job_id, bridge_id="", account_id=""):
    return len(CALLBACKS.latest(
        since=0,
        limit=20,
        bridge_id=bridge_id,
        account_id=account_id,
        event_prefix=DOWNLOAD_EVENT_PREFIX,
        job_id=job_id,
    ))


def should_fallback_history_download(error):
    text = str(error or "").lower()
    if "download_history_data2" not in text and "down_history_data2" not in text:
        return False
    return (
        "not found" in text
        or "not implemented" in text
        or "notimplemented" in text
        or "未提供" in text
        or "不支持" in text
        or "argument" in text
        or "positional" in text
        or "takes" in text
        or "参数" in text
    )


def download_history_data(body):
    body = body or {}
    stock_code = str(body.get("stock_code") or "").strip()
    if not stock_code:
        raise ValueError("stock_code is required")
    job_id = download_job_id(body, "download_history")
    stock_list = parse_csv_list(body.get("stock_list") or body.get("code_list") or stock_code)
    common = {
        "period": str(body.get("period") or "1d"),
        "start_time": str(body.get("start_time") or ""),
        "end_time": str(body.get("end_time") or ""),
        "incrementally": body.get("incrementally"),
        "callback_event": DOWNLOAD_CALLBACK_EVENT,
        "download_job_id": job_id,
        "download_emit_lifecycle": True,
    }
    params2 = dict(common)
    params2.update({
        "stock_code": stock_code,
        "stock_list": stock_list or [stock_code],
    })
    try:
        route = data_channel_request(body, "xtdata.download_history_data2", params2, force_channel="normal")
        if not download_cached_event_count(job_id, bridge_id=route.get("bridge_id") or ""):
            emit_download_progress(job_id, "history", "submitted", {
                "stage": "submitted",
                "message": "历史数据下载请求已提交。",
            }, bridge_id=route.get("bridge_id") or "", account_id=route.get("account_id") or "")
            emit_download_progress(job_id, "history", "request_done", {
                "stage": "request_done",
                "message": "历史数据下载请求已返回。",
                "result": route.get("result"),
            }, bridge_id=route.get("bridge_id") or "", account_id=route.get("account_id") or "")
        return with_download_response(route, job_id, "history")
    except Exception as error:
        if not should_fallback_history_download(error):
            raise
    params = dict(common)
    params.update({
        "stock_code": stock_code,
    })
    route = data_channel_request(body, "xtdata.download_history_data", params, force_channel="normal")
    if not download_cached_event_count(job_id, bridge_id=route.get("bridge_id") or ""):
        emit_download_progress(job_id, "history", "submitted", {
            "stage": "submitted",
            "message": "历史数据下载请求已提交。",
        }, bridge_id=route.get("bridge_id") or "", account_id=route.get("account_id") or "")
        emit_download_progress(job_id, "history", "request_done", {
            "stage": "request_done",
            "message": "历史数据下载请求已返回。当前 QMT 旧接口未提供百分比进度。",
            "result": route.get("result"),
        }, bridge_id=route.get("bridge_id") or "", account_id=route.get("account_id") or "")
    return with_download_response(
        route,
        job_id,
        "history",
        fallback_note="当前 QMT 未提供 download_history_data2，已回退到旧下载接口；只能显示请求生命周期，无法保证底层提供逐步进度。",
    )


def get_financial_data(body):
    body = body or {}
    mode = str(body.get("mode") or body.get("financial_mode") or "").strip().lower()
    raw = parse_bool(body.get("raw")) or mode in ("raw", "origin", "original")
    field_list = financial_field_list(body)
    table_list = financial_table_list(body)
    if not field_list:
        raise ValueError("financial fields or field_list is required for QMT financial query")
    params = {
        "field_list": field_list,
        "table_list": table_list,
        "stock_list": financial_stock_list(body),
        "start_time": str(body.get("start_time") or body.get("start_date") or ""),
        "end_time": str(body.get("end_time") or body.get("end_date") or ""),
        "report_type": str(body.get("report_type") or ("announce_time" if field_list else "report_time")),
    }
    action = "xtdata.get_raw_financial_data" if raw else "xtdata.get_financial_data"
    return data_channel_request(body, action, params)


def download_financial_data(body):
    body = body or {}
    job_id = download_job_id(body, "download_financial")
    mode = str(body.get("mode") or body.get("financial_mode") or "raw").strip().lower()
    raw = parse_bool(body.get("raw")) or mode in ("raw", "origin", "original", "ori")
    field_list = financial_probe_field_list(body)
    table_list = financial_table_list(body) or ["ASHAREBALANCESHEET"]
    params = {
        "stock_list": financial_stock_list(body),
        "field_list": field_list,
        "table_list": table_list,
        "start_time": str(body.get("start_time") or body.get("start_date") or ""),
        "end_time": str(body.get("end_time") or body.get("end_date") or ""),
        "report_type": str(body.get("report_type") or "report_time"),
    }
    bridge_id = resolve_bridge_id(
        account_id=str(body.get("account_id") or "").strip(),
        bridge_id=body.get("bridge_id"),
    )
    emit_download_progress(job_id, "financial_check", "submitted", {
        "stage": "submitted",
        "message": "开始校验本地财务数据。QMT 官方脚本接口不提供财务下载，请先在 QMT 客户端的数据管理中下载财务数据。",
        "stock_list": params["stock_list"],
        "table_list": table_list,
        "field_list": field_list,
    }, bridge_id=bridge_id)
    action = "xtdata.get_raw_financial_data" if raw else "xtdata.get_financial_data"
    try:
        route = data_channel_request(body, action, params, force_channel="normal")
    except Exception as error:
        emit_download_progress(job_id, "financial_check", "error", {
            "stage": "error",
            "error": str(error),
            "message": "本地财务数据校验失败，请先确认 QMT 客户端已下载财务数据。",
        }, bridge_id=bridge_id)
        raise
    summary = summarize_data_result(route.get("result"))
    route["query_summary"] = summary
    route["result"] = True
    route["replacement"] = True
    route["download_supported"] = False
    route["manual_download_required"] = True
    route["manual_download_hint"] = "QMT 官方脚本侧未提供财务数据下载函数；请在 QMT 客户端 数据管理 - 财务数据下载 中先下载，再用本接口校验本地数据。"
    route["query_action"] = action
    route["field_list"] = field_list
    route["table_list"] = table_list
    route["stock_list"] = params["stock_list"]
    emit_download_progress(job_id, "financial_check", "request_done", {
        "stage": "request_done",
        "message": "本地财务数据校验已返回。",
        "summary": summary,
        "available": not bool(summary.get("empty")),
    }, bridge_id=route.get("bridge_id") or bridge_id, account_id=route.get("account_id") or "")
    return with_download_response(
        route,
        job_id,
        "financial_check",
        fallback_note="QMT 官方脚本侧未提供财务数据下载函数；此入口已替换为本地财务数据校验/预加载读取。",
    )


class CfquantWebHandler(BaseHTTPRequestHandler):
    server_version = WEB_VERSION

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if not self._request_allowed():
            self._write_json(fail("request host is not allowed", 403), status=403)
            return
        if parsed.path == "/ws/callbacks":
            self._handle_ws_callbacks(parsed)
        elif parsed.path == "/ws/quotes":
            self._handle_ws_quotes(parsed)
        elif parsed.path.startswith("/media/"):
            self._serve_runtime_media(parsed.path)
        elif parsed.path.startswith("/api/"):
            self._handle_api_get(parsed)
        else:
            self._serve_static(parsed.path)

    def do_OPTIONS(self):
        parsed = urllib.parse.urlparse(self.path)
        if not self._request_allowed():
            self._write_json(fail("request host is not allowed", 403), status=403)
            return
        if not parsed.path.startswith("/api/"):
            self._write_json(fail("not found", 404), status=404)
            return
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if not self._request_allowed():
            self._write_json(fail("request host is not allowed", 403), status=403)
            return
        if not parsed.path.startswith("/api/"):
            self._write_json(fail("not found", 404), status=404)
            return
        if parsed.path == "/api/web-auth/login":
            try:
                body = self._read_json_body()
                result = web_auth_login(body)
                self._write_json(ok(result), extra_headers=self._web_auth_cookie_headers(result.get("token") or ""))
            except PermissionError as e:
                self._write_json(fail(e, 401), status=401)
            except Exception as e:
                self._write_json(fail(e, 400), status=400)
            return
        if not self._authorized(parsed):
            self._write_json(fail("invalid credentials", 401), status=401)
            return
        if parsed.path == "/api/user-profile/avatar":
            self._handle_avatar_upload(parsed)
            return
        if parsed.path == "/api/updates/upload":
            self._handle_update_upload(parsed)
            return
        if parsed.path == "/api/project-updates/upload":
            self._handle_project_update_upload(parsed)
            return
        try:
            body = self._read_json_body()
        except Exception as e:
            self._write_json(fail("invalid json: %s" % e, 400), status=400)
            return
        try:
            if parsed.path == "/api/order":
                self._write_json(ok(submit_order(body)))
            elif parsed.path == "/api/credit/order":
                self._write_json(ok(submit_credit_order(body)))
            elif parsed.path == "/api/future/order":
                self._write_json(ok(submit_future_order(body)))
            elif parsed.path == "/api/future-option/order":
                self._write_json(ok(submit_future_option_order(body)))
            elif parsed.path == "/api/stock-option/order":
                self._write_json(ok(submit_stock_option_order(body)))
            elif parsed.path == "/api/orders/batch":
                self._write_json(ok(submit_batch_orders(body)))
            elif parsed.path == "/api/credit/orders/batch":
                self._write_json(ok(submit_credit_batch_orders(body)))
            elif parsed.path == "/api/future/orders/batch":
                self._write_json(ok(submit_future_batch_orders(body)))
            elif parsed.path == "/api/future-option/orders/batch":
                self._write_json(ok(submit_future_option_batch_orders(body)))
            elif parsed.path == "/api/stock-option/orders/batch":
                self._write_json(ok(submit_stock_option_batch_orders(body)))
            elif parsed.path == "/api/cancel":
                self._write_json(ok(cancel_order(body)))
            elif parsed.path == "/api/credit/query":
                self._write_json(ok(query_credit_account(body)))
            elif parsed.path == "/api/credit/probe":
                self._write_json(ok(probe_credit_account(body)))
            elif parsed.path == "/api/apikey":
                self._write_json(ok(save_api_key(body)))
            elif parsed.path == "/api/server-access":
                result = save_server_access(body)
                reload_requested = parse_bool(body.get("reload"))
                if reload_requested:
                    result["reload"] = web_reload_info(reason="settings")
                self._write_json(ok(result))
                if reload_requested:
                    schedule_web_reload(self.server, result["reload"])
            elif parsed.path == "/api/user-profile":
                self._write_json(ok(save_user_profile(body)))
            elif parsed.path == "/api/transport":
                self._write_json(ok(save_transport(body)))
            elif parsed.path == "/api/pipe-hub/start":
                self._write_json(ok(start_pipe_hub()))
            elif parsed.path == "/api/pipe-hub/stop":
                self._write_json(ok(stop_pipe_hub()))
            elif parsed.path == "/api/log-cleanup":
                self._write_json(ok(save_log_cleanup_settings(body)))
            elif parsed.path == "/api/qmt-log-language":
                self._write_json(ok(save_qmt_log_language(body)))
            elif parsed.path == "/api/log-cleanup/run":
                self._write_json(ok(run_log_cleanup(body)))
            elif parsed.path == "/api/updates/github":
                self._write_json(ok(bridge_update_github(body)))
            elif parsed.path == "/api/updates/official":
                self._write_json(ok(bridge_update_official(body)))
            elif parsed.path == "/api/updates/rollback":
                self._write_json(ok(bridge_update_rollback(body)))
            elif parsed.path == "/api/project-updates/github":
                result = project_update_github(body)
                reload_requested = parse_bool(body.get("reload")) if "reload" in body else True
                if reload_requested:
                    result["reload"] = web_reload_info(reason="project-update")
                self._write_json(ok(result))
                if reload_requested:
                    schedule_web_reload(self.server, result["reload"])
            elif parsed.path == "/api/project-updates/official":
                result = project_update_official(body)
                reload_requested = parse_bool(body.get("reload")) if "reload" in body else True
                if reload_requested:
                    result["reload"] = web_reload_info(reason="project-update")
                self._write_json(ok(result))
                if reload_requested:
                    schedule_web_reload(self.server, result["reload"])
            elif parsed.path == "/api/project-updates/rollback":
                result = project_update_rollback(body)
                reload_requested = parse_bool(body.get("reload")) if "reload" in body else True
                if reload_requested:
                    result["reload"] = web_reload_info(reason="project-rollback")
                self._write_json(ok(result))
                if reload_requested:
                    schedule_web_reload(self.server, result["reload"])
            elif parsed.path == "/api/quotes/whole/subscribe":
                self._write_json(ok(subscribe_whole_quote(body)))
            elif parsed.path == "/api/quotes/subscribe":
                self._write_json(ok(subscribe_single_quote(body)))
            elif parsed.path == "/api/quotes/unsubscribe":
                self._write_json(ok(unsubscribe_quote(body)))
            elif parsed.path == "/api/data/full-tick":
                self._write_json(ok(get_full_tick(body)))
            elif parsed.path == "/api/data/market":
                self._write_json(ok(get_market_data(body, ex=False)))
            elif parsed.path == "/api/data/market-ex":
                self._write_json(ok(get_market_data(body, ex=True)))
            elif parsed.path == "/api/data/instrument":
                self._write_json(ok(get_instrument_detail(body)))
            elif parsed.path == "/api/data/sector":
                self._write_json(ok(get_stock_list_in_sector(body)))
            elif parsed.path == "/api/data/history/download":
                self._write_json(ok(download_history_data(body)))
            elif parsed.path == "/api/data/financial":
                self._write_json(ok(get_financial_data(body)))
            elif parsed.path == "/api/data/financial/download":
                self._write_json(ok(download_financial_data(body)))
            elif parsed.path == "/api/trade/export-data":
                self._write_json(ok(export_trade_data(body)))
            elif parsed.path == "/api/lttx/start":
                self._write_json(ok(start_lttx_server()))
            elif parsed.path == "/api/lttx/stop":
                self._write_json(ok(stop_lttx_server(full_exit=parse_bool(body.get("full_exit")))))
            elif parsed.path == "/api/bridges":
                self._write_json(ok(save_bridge_config(body)))
            elif parsed.path == "/api/bridges/delete":
                self._write_json(ok(delete_bridge_config(body)))
            elif parsed.path == "/api/account-pairs":
                self._write_json(ok(save_account_pair(body)))
            elif parsed.path == "/api/account-pairs/delete":
                self._write_json(ok(delete_account_pair(body)))
            elif parsed.path == "/api/account-pairs/verify":
                self._write_json(ok(verify_account_pair(body)))
            elif parsed.path == "/api/account-config":
                self._write_json(ok(save_account_runtime_config(body)))
            elif parsed.path == "/api/account-config/delete":
                self._write_json(ok(delete_account_runtime_config(body)))
            elif parsed.path == "/api/setup/initialize":
                result = initialize_web_setup(body)
                token = ((result.get("web_auth") or {}).get("token") or "")
                self._write_json(ok(result), extra_headers=self._web_auth_cookie_headers(token))
            elif parsed.path == "/api/setup/reset":
                self._write_json(ok(reset_web_setup()))
            elif parsed.path == "/api/setup/data-provider":
                self._write_json(ok(set_data_provider(body)))
            elif parsed.path == "/api/web-auth/logout":
                self._write_json(
                    ok(web_auth_logout(self._provided_web_token(parsed))),
                    extra_headers=self._web_auth_clear_cookie_headers(),
                )
            else:
                self._write_json(fail("not found", 404), status=404)
        except Exception as e:
            self._write_json(fail(e, 400), status=400)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _request_allowed(self):
        allow_remote = WEB_CONFIG.allow_remote()
        domains = WEB_CONFIG.allowed_domains()
        hosts = [
            extract_host_name(self.headers.get("Host") or ""),
            extract_host_name(self.headers.get("Origin") or ""),
        ]
        for host in [item for item in hosts if item]:
            if is_loopback_host(host):
                continue
            if not allow_remote:
                return False
            if domains and not host_matches_patterns(host, domains):
                return False
        return True

    def _provided_api_key(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        provided = (
            self.headers.get("X-API-Key")
            or self.headers.get("x-api-key")
            or (query.get("apikey") or query.get("api_key") or [""])[0]
        )
        auth = self.headers.get("Authorization") or ""
        if not provided and auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
        return str(provided or "").strip()

    def _provided_web_token(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        provided = (
            self.headers.get("X-CFQUANT-WEB-TOKEN")
            or self.headers.get("x-cfquant-web-token")
            or (query.get("web_token") or query.get("web_auth_token") or [""])[0]
            or self._provided_web_cookie_token()
        )
        return str(provided or "").strip()

    def _provided_web_cookie_token(self):
        raw = self.headers.get("Cookie") or ""
        if not raw:
            return ""
        try:
            jar = cookies.SimpleCookie()
            jar.load(raw)
            item = jar.get(WEB_AUTH_COOKIE_NAME)
            return item.value if item else ""
        except Exception:
            return ""

    def _web_auth_cookie_headers(self, token):
        token = str(token or "").strip()
        if not token:
            return []
        max_age = max(1, int(WEB_AUTH_SESSION_TTL_SECONDS))
        return [(
            "Set-Cookie",
            "%s=%s; Path=/; Max-Age=%s; SameSite=Lax; HttpOnly"
            % (WEB_AUTH_COOKIE_NAME, token, max_age),
        )]

    def _web_auth_clear_cookie_headers(self):
        return [(
            "Set-Cookie",
            "%s=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly" % WEB_AUTH_COOKIE_NAME,
        )]

    def _api_key_valid(self, parsed):
        api_key = WEB_CONFIG.api_key()
        provided = self._provided_api_key(parsed)
        return bool(api_key and provided) and secrets.compare_digest(provided, api_key)

    def _web_token_valid(self, parsed):
        return bool(web_auth_token_info(self._provided_web_token(parsed)))

    def _has_access_token(self, parsed):
        return self._web_token_valid(parsed) or self._api_key_valid(parsed)

    def _authorized(self, parsed):
        if parsed.path == "/api/config":
            return True
        if parsed.path == "/api/apikey" and not WEB_CONFIG.web_auth_enabled():
            return True
        if WEB_CONFIG.web_auth_enabled():
            return self._has_access_token(parsed)
        api_key = WEB_CONFIG.api_key()
        if not api_key:
            return True
        return self._api_key_valid(parsed)

    def _handle_update_upload(self, parsed):
        try:
            content_type = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in content_type.lower():
                self._write_json(fail("multipart/form-data is required", 400), status=400)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                self._write_json(fail("empty upload", 400), status=400)
                return
            if length > UPDATE_UPLOAD_MAX_BYTES:
                self._write_json(fail("upload too large: %s bytes" % length, 400), status=400)
                return
            raw = self.rfile.read(length)
            fields, files = self._parse_multipart(content_type, raw)
            bridge_id = normalize_bridge_id(fields.get("bridge_id") or DEFAULT_BRIDGE_ID)
            file_item = files.get("file") or files.get("zip")
            if not file_item:
                self._write_json(fail("file is required", 400), status=400)
                return
            result = UPDATER.update_from_zip(bridge_id, file_item.get("filename") or "upload.zip", file_item.get("content") or b"")
            self._write_json(ok(result))
        except Exception as e:
            self._write_json(fail(e, 400), status=400)

    def _handle_project_update_upload(self, parsed):
        try:
            content_type = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in content_type.lower():
                self._write_json(fail("multipart/form-data is required", 400), status=400)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                self._write_json(fail("empty upload", 400), status=400)
                return
            if length > UPDATE_UPLOAD_MAX_BYTES:
                self._write_json(fail("upload too large: %s bytes" % length, 400), status=400)
                return
            raw = self.rfile.read(length)
            fields, files = self._parse_multipart(content_type, raw)
            file_item = files.get("file") or files.get("zip")
            if not file_item:
                self._write_json(fail("file is required", 400), status=400)
                return
            result = PROJECT_UPDATER.update_from_zip(
                file_item.get("filename") or "upload.zip",
                file_item.get("content") or b"",
            )
            reload_requested = parse_bool(fields.get("reload")) if "reload" in fields else True
            if reload_requested:
                result["reload"] = web_reload_info(reason="project-update-upload")
            self._write_json(ok(result))
            if reload_requested:
                schedule_web_reload(self.server, result["reload"])
        except Exception as e:
            self._write_json(fail(e, 400), status=400)

    def _handle_avatar_upload(self, parsed):
        try:
            content_type = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in content_type.lower():
                self._write_json(fail("multipart/form-data is required", 400), status=400)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                self._write_json(fail("empty upload", 400), status=400)
                return
            if length > AVATAR_UPLOAD_MAX_BYTES:
                self._write_json(fail("avatar upload too large: %s bytes" % length, 400), status=400)
                return
            raw = self.rfile.read(length)
            fields, files = self._parse_multipart(content_type, raw)
            file_item = files.get("file") or files.get("avatar")
            if not file_item:
                self._write_json(fail("file is required", 400), status=400)
                return
            content = file_item.get("content") or b""
            if not content:
                self._write_json(fail("empty avatar file", 400), status=400)
                return
            ext = detect_avatar_extension(file_item.get("filename"), file_item.get("content_type"), content)
            os.makedirs(RUNTIME_AVATAR_DIR, exist_ok=True)
            filename = "avatar-%s-%s%s" % (int(time.time()), secrets.token_hex(6), ext)
            full_path = os.path.abspath(os.path.join(RUNTIME_AVATAR_DIR, filename))
            avatar_root = os.path.abspath(RUNTIME_AVATAR_DIR)
            if os.path.commonpath([avatar_root, full_path]) != avatar_root:
                raise ValueError("invalid avatar path")
            with open(full_path, "wb") as f:
                f.write(content)
            profile = WEB_CONFIG.set_user_profile(
                display_name=fields.get("display_name") if "display_name" in fields else None,
                avatar_url=AVATAR_UPLOAD_URL_PREFIX + filename,
            )
            self._write_json(ok(user_profile_response(profile)))
        except Exception as e:
            self._write_json(fail(e, 400), status=400)

    def _parse_multipart(self, content_type, raw):
        header = "Content-Type: %s\r\nMIME-Version: 1.0\r\n\r\n" % content_type
        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(header.encode("utf-8") + raw)
        fields = {}
        files = {}
        if not message.is_multipart():
            raise ValueError("invalid multipart body")
        for part in message.iter_parts():
            disposition = part.get("Content-Disposition") or ""
            if not disposition.lower().startswith("form-data"):
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                files[name] = {"filename": filename, "content": payload, "content_type": part.get_content_type()}
            else:
                charset = part.get_content_charset() or "utf-8"
                fields[name] = payload.decode(charset, errors="replace")
        return fields, files

    def _handle_api_get(self, parsed):
        if not self._authorized(parsed):
            self._write_json(fail("invalid credentials", 401), status=401)
            return
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/config":
                has_access = self._has_access_token(parsed)
                auth_required = WEB_CONFIG.web_auth_enabled() and not has_access
                if auth_required:
                    access = server_access_info(include_auth_details=False)
                    self._write_json(ok({
                        "auth_required": True,
                        "server_access": access,
                        "web_auth": access.get("web_auth") or {},
                        "api_key": api_key_info(include_secret=False),
                        "transport": WEB_CONFIG.transport_info(),
                        "pipe_hub": PIPE_HUB.status(),
                        "qmt_log_language": WEB_CONFIG.qmt_log_language_info(),
                        "version": project_version_info(include_remote=False),
                    }))
                    return
                self._write_json(ok({
                    "default_account_id": configured_default_account_id(),
                    "default_bridge_id": DEFAULT_BRIDGE_ID,
                    "bridges": WEB_CONFIG.bridges(),
                    "env_bridges": ENV_BRIDGES,
                    "account_pairs": WEB_CONFIG.account_pairs(),
                    "account_configs": WEB_CONFIG.account_configs(),
                    "setup": WEB_CONFIG.setup_info(),
                    "channels": bridge_channels(DEFAULT_BRIDGE_ID),
                    "reply_channel": CLIENTS.client_id,
                    "api_key": WEB_CONFIG.api_key_info(include_secret=True),
                    "server_access": server_access_info(include_auth_details=True),
                    "web_auth": WEB_CONFIG.web_auth_info(include_username=True),
                    "user_profile": user_profile_response(),
                    "transport": WEB_CONFIG.transport_info(),
                    "pipe_hub": PIPE_HUB.status(),
                    "log_cleanup": log_cleanup_info(),
                    "qmt_log_language": qmt_log_language_info(),
                    "version": project_version_info(include_remote=False),
                }))
            elif parsed.path == "/api/apikey":
                self._write_json(ok(api_key_info()))
            elif parsed.path == "/api/server-access":
                self._write_json(ok(server_access_info()))
            elif parsed.path == "/api/user-profile":
                self._write_json(ok(user_profile_response()))
            elif parsed.path == "/api/transport":
                self._write_json(ok(transport_info()))
            elif parsed.path == "/api/pipe-hub":
                self._write_json(ok(pipe_hub_info()))
            elif parsed.path == "/api/credit/actions":
                self._write_json(ok(credit_actions_info()))
            elif parsed.path == "/api/order/actions":
                self._write_json(ok(order_actions_info()))
            elif parsed.path == "/api/web-auth/status":
                self._write_json(ok(web_auth_status(self._provided_web_token(parsed))))
            elif parsed.path == "/api/log-cleanup":
                self._write_json(ok(log_cleanup_info()))
            elif parsed.path == "/api/qmt-log-language":
                self._write_json(ok(qmt_log_language_info()))
            elif parsed.path == "/api/qmt-scripts/source":
                raw_names = []
                for key in ("name", "names", "script"):
                    for value in query.get(key) or []:
                        raw_names.extend(part.strip() for part in str(value).split(",") if part.strip())
                if not raw_names:
                    raise ValueError("QMT script name is required")
                self._write_json(ok({"scripts": qmt_entry_script_sources(raw_names)}))
            elif parsed.path == "/api/updates/status":
                bridge_id = normalize_bridge_id((query.get("bridge_id") or [DEFAULT_BRIDGE_ID])[0])
                repo_url = (query.get("repo_url") or query.get("url") or [""])[0]
                ref = (query.get("ref") or query.get("branch") or query.get("tag") or [""])[0]
                self._write_json(ok(bridge_update_status(bridge_id, repo_url=repo_url, ref=ref)))
            elif parsed.path == "/api/project-updates/status":
                repo_url = (query.get("repo_url") or query.get("url") or [""])[0]
                ref = (query.get("ref") or query.get("branch") or query.get("tag") or [""])[0]
                include_remote = parse_bool((query.get("remote") or ["1"])[0])
                self._write_json(ok(project_update_status(
                    repo_url=repo_url,
                    ref=ref,
                    include_remote=include_remote,
                )))
            elif parsed.path == "/api/version":
                include_remote = parse_bool((query.get("remote") or ["1"])[0])
                force = parse_bool((query.get("force") or ["0"])[0])
                repo_url = (query.get("repo_url") or query.get("url") or [""])[0]
                ref = (query.get("ref") or query.get("branch") or query.get("tag") or [""])[0]
                bridge_id = (query.get("bridge_id") or [""])[0]
                self._write_json(ok(project_version_info(
                    include_remote=include_remote,
                    force=force,
                    repo_url=repo_url,
                    ref=ref,
                    bridge_id=bridge_id,
                )))
            elif parsed.path == "/api/quotes/status":
                self._write_json(ok(quote_status()))
            elif parsed.path == "/api/quotes/latest":
                since = int((query.get("since") or ["0"])[0] or 0)
                limit = int((query.get("limit") or ["200"])[0] or 200)
                subscribe_id = (query.get("subscribe_id") or [""])[0]
                self._write_json(ok({
                    "events": QUOTES.latest(since=since, limit=limit, subscribe_id=subscribe_id),
                    "status": QUOTES.status(),
                }))
            elif parsed.path == "/api/lttx":
                self._write_json(ok(lttx_status()))
            elif parsed.path == "/api/status":
                account_id = str((query.get("account_id") or [""])[0] or "").strip()
                account_type = normalize_account_type((query.get("account_type") or [configured_default_account_type()])[0])
                account_key = str((query.get("account_key") or [""])[0] or "").strip()
                bridge_id = resolve_bridge_id(
                    account_id=account_id,
                    account_type=account_type,
                    account_key=account_key,
                    bridge_id=(query.get("bridge_id") or [""])[0],
                )
                bridge_config(bridge_id)
                self._write_json(ok(
                    account_route_status(account_id, bridge_id=bridge_id, account_type=account_type, account_key=account_key)
                    if account_id else STATUS_MONITOR.latest(bridge_id=bridge_id)
                ))
            elif parsed.path == "/api/bindings/status":
                self._write_json(ok(binding_status_snapshot()))
            elif parsed.path == "/api/callbacks":
                account_id = (query.get("account_id") or [""])[0]
                account_type = normalize_account_type((query.get("account_type") or ["STOCK"])[0]) if query.get("account_type") else ""
                account_key = str((query.get("account_key") or [""])[0] or "").strip()
                bridge_id = resolve_bridge_id(
                    account_id=account_id,
                    account_type=account_type or None,
                    account_key=account_key,
                    bridge_id=(query.get("bridge_id") or [""])[0],
                )
                bridge = bridge_config(bridge_id)
                since = int((query.get("since") or ["0"])[0] or 0)
                limit = int((query.get("limit") or ["200"])[0] or 200)
                event_name = (query.get("event") or [""])[0]
                event_prefix = (query.get("event_prefix") or [""])[0]
                job_id = (query.get("job_id") or [""])[0]
                self._write_json(ok({
                    "bridge_id": bridge_id,
                    "account_id": account_id,
                    "account_type": account_type,
                    "account_key": account_key,
                    "channel": bridge["channels"]["callback"],
                    "event": event_name,
                    "event_prefix": event_prefix,
                    "job_id": job_id,
                    "events": CALLBACKS.latest(
                        since=since,
                        limit=limit,
                        bridge_id=bridge_id,
                        account_id=account_id,
                        account_type=account_type,
                        account_key=account_key,
                        event_name=event_name,
                        event_prefix=event_prefix,
                        job_id=job_id,
                    ),
                }))
            elif parsed.path == "/api/account":
                account_request_started = time.perf_counter()
                account_id = (query.get("account_id") or [configured_default_account_id()])[0]
                account_type = normalize_account_type((query.get("account_type") or [configured_default_account_type()])[0])
                account_key = str((query.get("account_key") or [""])[0] or "").strip()
                bridge_id = resolve_bridge_id(
                    account_id=account_id,
                    account_type=account_type,
                    account_key=account_key,
                    bridge_id=(query.get("bridge_id") or [""])[0],
                )
                bridge_config(bridge_id)
                channel = (query.get("channel") or ["normal"])[0]
                sections = parse_sections((query.get("sections") or [""])[0])
                force = parse_bool((query.get("force") or ["0"])[0])
                subscribe = parse_bool((query.get("subscribe") or ["1"])[0])
                timeout = request_timeout_value(
                    (query.get("timeout") or [""])[0],
                    default=ACCOUNT_QUERY_TIMEOUT_SECONDS,
                    maximum=max(ACCOUNT_QUERY_TIMEOUT_SECONDS, 180.0),
                )
                account_result = ACCOUNT_CACHE.get_market_routed(
                    bridge_id,
                    channel,
                    account_id,
                    sections,
                    force=force,
                    subscribe=subscribe,
                    account_type=account_type,
                    account_key=account_key,
                    timeout=timeout,
                )
                cache_meta = account_result.setdefault("cache", {})
                cache_meta["response_latency_ms"] = round(
                    (time.perf_counter() - account_request_started) * 1000,
                    2,
                )
                self._write_json(ok(account_result))
            else:
                self._write_json(fail("not found", 404), status=404)
        except Exception as e:
            self._write_json(fail(e, 400), status=400)

    def _handle_ws_callbacks(self, parsed):
        if not self._authorized(parsed):
            self.send_response(401)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(fail("invalid credentials", 401), ensure_ascii=False).encode("utf-8"))
            return
        key = self.headers.get("Sec-WebSocket-Key")
        upgrade = (self.headers.get("Upgrade") or "").lower()
        if upgrade != "websocket" or not key:
            self.send_response(400)
            self.end_headers()
            return
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        query = urllib.parse.parse_qs(parsed.query)
        account_id = (query.get("account_id") or [""])[0]
        account_type = normalize_account_type((query.get("account_type") or ["STOCK"])[0]) if query.get("account_type") else ""
        account_key = str((query.get("account_key") or [""])[0] or "").strip()
        event_name = (query.get("event") or [""])[0]
        event_prefix = (query.get("event_prefix") or [""])[0]
        job_id = (query.get("job_id") or [""])[0]
        bridge_id = resolve_bridge_id(
            account_id=account_id,
            account_type=account_type or None,
            account_key=account_key,
            bridge_id=(query.get("bridge_id") or [""])[0],
        ) if account_id or account_key or query.get("bridge_id") else ""
        client = WebSocketCallbackClient(
            self.request,
            bridge_id=bridge_id,
            account_id=account_id,
            account_type=account_type,
            account_key=account_key,
            event_name=event_name,
            event_prefix=event_prefix,
            job_id=job_id,
        )
        WS_CALLBACKS.add(client)
        safe_print(
            "websocket callbacks connected bridge=%s account=%s event=%s prefix=%s job=%s clients=%s"
            % (bridge_id or "*", account_id or "*", event_name or "*", event_prefix or "*", job_id or "*", WS_CALLBACKS.count())
        )
        try:
            client.send_json({
                "type": "hello",
                "channel": "callbacks",
                "bridge_id": bridge_id,
                "account_id": account_id,
                "account_type": account_type,
                "account_key": account_key,
                "event": event_name,
                "event_prefix": event_prefix,
                "job_id": job_id,
                "clients": WS_CALLBACKS.count(),
            })
            cached_events = CALLBACKS.latest(
                since=0,
                limit=100,
                bridge_id=bridge_id,
                account_id=account_id,
                account_type=account_type,
                account_key=account_key,
                event_name=event_name,
                event_prefix=event_prefix,
                job_id=job_id,
            )
            for event in cached_events:
                client.send_json({
                    "type": "callback",
                    "channel": "callbacks",
                    "cached": True,
                    "event": event,
                })
            self.request.settimeout(30)
            while client.alive:
                frame = self._read_ws_frame()
                if frame is None:
                    continue
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._send_ws_control(0xA, payload)
        except Exception as e:
            safe_print("websocket callbacks closed: %s" % e)
        finally:
            WS_CALLBACKS.remove(client)
            self.close_connection = True

    def _handle_ws_quotes(self, parsed):
        if not self._authorized(parsed):
            self.send_response(401)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(fail("invalid credentials", 401), ensure_ascii=False).encode("utf-8"))
            return
        key = self.headers.get("Sec-WebSocket-Key")
        upgrade = (self.headers.get("Upgrade") or "").lower()
        if upgrade != "websocket" or not key:
            self.send_response(400)
            self.end_headers()
            return
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        query = urllib.parse.parse_qs(parsed.query)
        subscribe_id = (query.get("subscribe_id") or [""])[0]
        client = WebSocketQuoteClient(self.request, subscribe_id=subscribe_id)
        WS_QUOTES.add(client)
        safe_print(
            "websocket quotes connected subscribe_id=%s clients=%s"
            % (subscribe_id or "*", WS_QUOTES.count())
        )
        try:
            client.send_json({
                "type": "hello",
                "channel": "quotes",
                "subscribe_id": subscribe_id,
                "clients": WS_QUOTES.count(),
                "status": QUOTES.status(),
            })
            self.request.settimeout(30)
            while client.alive:
                frame = self._read_ws_frame()
                if frame is None:
                    continue
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._send_ws_control(0xA, payload)
        except Exception as e:
            safe_print("websocket quotes closed: %s" % e)
        finally:
            WS_QUOTES.remove(client)
            self.close_connection = True

    def _read_ws_frame(self):
        try:
            header = self._recv_ws_bytes(2, allow_idle=True)
            if header is None:
                return None
            if not header:
                return 0x8, b""
            b1, b2 = header[0], header[1]
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                raw_length = self._recv_ws_bytes(2)
                if not raw_length:
                    return 0x8, b""
                length = int.from_bytes(raw_length, "big")
            elif length == 127:
                raw_length = self._recv_ws_bytes(8)
                if not raw_length:
                    return 0x8, b""
                length = int.from_bytes(raw_length, "big")
            mask = self._recv_ws_bytes(4) if masked else b""
            if masked and not mask:
                return 0x8, b""
            payload = self._recv_ws_bytes(length) if length else b""
            if length and not payload:
                return 0x8, b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            return opcode, payload
        except socket.timeout:
            return None

    def _recv_ws_bytes(self, length, allow_idle=False):
        remaining = int(length or 0)
        chunks = []
        while remaining > 0:
            try:
                chunk = self.request.recv(remaining)
            except socket.timeout:
                if allow_idle and not chunks:
                    return None
                raise
            if not chunk:
                return b""
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send_ws_control(self, opcode, payload=b""):
        payload = payload or b""
        length = len(payload)
        if length > 125:
            payload = payload[:125]
            length = 125
        self.request.sendall(bytes([0x80 | opcode, length]) + payload)

    def _serve_static(self, path):
        try:
            rel_path, raw = read_static_asset(path)
        except PermissionError:
            self._write_json(fail("forbidden", 403), status=403)
            return
        if raw is None:
            self._write_json(fail("not found", 404), status=404)
            return
        content_type = mimetypes.guess_type(rel_path)[0] or "application/octet-stream"
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as e:
            safe_print("client disconnected while writing static response: %s" % e)

    def _serve_runtime_media(self, path):
        path = posixpath.normpath(urllib.parse.unquote(path or ""))
        if not path.startswith(AVATAR_UPLOAD_URL_PREFIX):
            self._write_json(fail("not found", 404), status=404)
            return
        filename = posixpath.basename(path)
        if not filename or filename != path[len(AVATAR_UPLOAD_URL_PREFIX):] or not re.match(r"^[A-Za-z0-9_.-]+$", filename):
            self._write_json(fail("forbidden", 403), status=403)
            return
        if os.path.splitext(filename)[1].lower() not in AVATAR_UPLOAD_EXTENSIONS:
            self._write_json(fail("forbidden", 403), status=403)
            return
        full_path = os.path.abspath(os.path.join(RUNTIME_AVATAR_DIR, filename))
        avatar_root = os.path.abspath(RUNTIME_AVATAR_DIR)
        if os.path.commonpath([avatar_root, full_path]) != avatar_root:
            self._write_json(fail("forbidden", 403), status=403)
            return
        if not os.path.isfile(full_path):
            self._write_json(fail("not found", 404), status=404)
            return
        content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        with open(full_path, "rb") as f:
            data = f.read()
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as e:
            safe_print("client disconnected while writing media response: %s" % e)

    def _write_json(self, payload, status=200, extra_headers=None):
        raw = json.dumps(to_jsonable(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            for key, value in extra_headers or []:
                self.send_header(str(key), str(value))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as e:
            safe_print("client disconnected while writing json response: %s" % e)

    def log_message(self, fmt, *args):
        safe_print("%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args))

    def _send_cors_headers(self):
        origin = self.headers.get("Origin") or ""
        if origin and self._request_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif not origin:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, X-CFQUANT-WEB-TOKEN, Authorization")
        self.send_header("Access-Control-Max-Age", "600")


def spawn_reloaded_web_server(reload_request):
    reload_request = reload_request or {}
    command = [sys.executable, os.path.abspath(__file__)]
    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    popen_kwargs = {"creationflags": creationflags, "close_fds": False if os.name == "nt" else True}
    if os.name == "nt":
        hidden_kwargs = _hidden_subprocess_kwargs()
        popen_kwargs.update(hidden_kwargs)
        popen_kwargs["creationflags"] = creationflags | int(hidden_kwargs.get("creationflags") or 0)
    safe_print("cfquant web reload spawning next process url=%s" % (reload_request.get("next_url") or ""))
    try:
        process = subprocess.Popen(
            command,
            cwd=STATE_DIR if os.path.isdir(STATE_DIR) else BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs
        )
        safe_print("cfquant web reload spawned pid=%s" % process.pid)
        return {"pid": process.pid, "command": command}
    except Exception as e:
        safe_print("cfquant web reload spawn failed: %s" % e)
        return {"error": str(e), "command": command}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run cfquant local web dashboard.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    if not args.host:
        args.host = os.environ.get("CFQUANT_WEB_HOST") or ("0.0.0.0" if WEB_CONFIG.allow_remote() else "127.0.0.1")
    if args.port is None:
        args.port = normalize_web_port(os.environ.get("CFQUANT_WEB_PORT"), default=WEB_CONFIG.web_port())
    else:
        args.port = normalize_web_port(args.port, default=WEB_CONFIG.web_port(), strict=True)

    if not static_assets_available():
        raise RuntimeError("static assets not found: %s or package %s" % (STATIC_DIR, PACKAGE_STATIC_NAME))
    configured_modes = configured_runtime_modes()
    ensure_lttx_started("Web 启动预启动")
    global WEB_BOUND_HOST, WEB_BOUND_PORT
    WEB_BOUND_HOST = args.host
    WEB_BOUND_PORT = args.port
    probe_host = "127.0.0.1" if args.host in ("", "0.0.0.0") else args.host
    if tcp_port_open(probe_host, args.port):
        raise RuntimeError("cfquant web port %s is already listening, skip duplicate start" % args.port)
    server = ThreadingHTTPServer((args.host, args.port), CfquantWebHandler)
    try:
        if "lttx" in configured_modes:
            # 高级模式故障时需要立即回退到 ctypes，因此即使没有独立通用账号也要启动 PipeHub。
            if not any(is_ctypes_transport_mode(mode) for mode in configured_modes):
                configured_modes.add("ctypes")
        if any(is_ctypes_transport_mode(mode) for mode in configured_modes):
            try:
                safe_print("cfquant ctypes 通用版模式已启用，正在启动 PipeHub")
                PIPE_HUB.start()
            except Exception as e:
                safe_print("cfquant PipeHub 自动启动失败: %s" % e)
        for client_mode in configured_modes:
            try:
                CLIENTS.start(client_mode)
            except Exception as e:
                safe_print("cfquant %s client start failed: %s" % (client_mode, e))
        LTTX_WEB_ROUTE.start()
        safe_print("cfquant web global tx started reply_channel=%s" % CLIENTS.client_id)
    except Exception as e:
        LTTX_WEB_ROUTE.close()
        CLIENTS.close()
        safe_print("cfquant web global tx start failed: %s" % e)
    STATUS_MONITOR.start()
    ACCOUNT_CACHE.start()
    CALLBACKS.start()
    QUOTES.start()
    LOG_CLEANUP.start()
    safe_print("cfquant web dashboard listening on http://%s:%s" % (args.host, args.port))
    try:
        server.serve_forever()
    finally:
        LOG_CLEANUP.close()
        STATUS_MONITOR.close()
        ACCOUNT_CACHE.close()
        CALLBACKS.close()
        QUOTES.close()
        LTTX_WEB_ROUTE.close()
        CLIENTS.close()
        server.server_close()
        restart_request = None
        with WEB_RESTART_LOCK:
            if WEB_RESTART_REQUEST:
                restart_request = dict(WEB_RESTART_REQUEST)
        if restart_request:
            spawn_reloaded_web_server(restart_request)


if __name__ == "__main__":
    raise SystemExit(main())
