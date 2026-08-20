# -*- coding: utf-8 -*-
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
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_LTTX_TX_DIR = os.path.join(_PROJECT_DIR, "LTtx", "tx")


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
from cfquant.channels import configured_bridges, normalize_bridge_id
from cfquant.config import get_config as get_cfquant_config
from cfquant.logging_i18n import normalize_log_enabled, normalize_log_language
from cfquant.pipe_transport import DEFAULT_PIPE_NAME, normalize_pipe_name
from cfquant.protocol import loads_message, new_id, pack_event, pack_response
from cfquant.version import __version__ as CORE_VERSION
from tx import txl


WEB_VERSION = "web_20260820_01"
BASE_DIR = _PROJECT_DIR
CORE_VERSION_PATH = os.path.join(BASE_DIR, "cfquant", "version.py")
STATIC_DIR = os.path.join(BASE_DIR, "web_dashboard")
LOG_DIR = os.path.abspath(os.environ.get("CFQUANT_LOG_DIR") or os.path.join(BASE_DIR, "log"))
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception:
    LOG_DIR = BASE_DIR
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


LTTX_HOST = os.environ.get("CFQUANT_LTTX_HOST", "127.0.0.1")
LTTX_PORT = int(os.environ.get("CFQUANT_LTTX_PORT", "2049"))
LTTX_DIR = os.path.join(BASE_DIR, "LTtx", "tx")
LTTX_ENTRY = os.environ.get("CFQUANT_LTTX_ENTRY") or os.path.join(LTTX_DIR, "LTtx_server.py")
LTTX_STDOUT_LOG = os.path.join(LOG_DIR, "lttx_server.stdout.log")
LTTX_STDERR_LOG = os.path.join(LOG_DIR, "lttx_server.stderr.log")
PIPE_HUB_ENTRY = os.environ.get("CFQUANT_PIPE_HUB_ENTRY") or os.path.join(BASE_DIR, "cfquant_pipe_hub.py")
PIPE_HUB_STDOUT_LOG = os.path.join(LOG_DIR, "cfquant_pipe_hub.stdout.log")
PIPE_HUB_STDERR_LOG = os.path.join(LOG_DIR, "cfquant_pipe_hub.stderr.log")
PIPE_HUB_STATUS_FILE = os.path.join(BASE_DIR, "cfquant_pipe_hub_status.json")
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
DEFAULT_ACCOUNT_ID = os.environ.get("CFQUANT_ACCOUNT_ID", "2220009880")
WEB_CONFIG_FILE = os.environ.get("CFQUANT_WEB_CONFIG_FILE") or os.path.join(BASE_DIR, "cfquant_web_config.json")
WEB_SETTINGS_DB_FILE = os.environ.get("CFQUANT_WEB_SETTINGS_DB_FILE") or os.path.join(BASE_DIR, "cfquant_web_config.db")
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
ACCOUNT_CACHE_REFRESH_SECONDS = float(os.environ.get("CFQUANT_WEB_ACCOUNT_CACHE_INTERVAL", "5"))
ACCOUNT_QUERY_TIMEOUT_SECONDS = float(os.environ.get("CFQUANT_WEB_ACCOUNT_QUERY_TIMEOUT", "30"))
UPDATE_UPLOAD_MAX_BYTES = int(os.environ.get("CFQUANT_UPDATE_UPLOAD_MAX_BYTES", str(80 * 1024 * 1024)))
DEFAULT_UPDATE_REPO_URL = os.environ.get("CFQUANT_UPDATE_REPO_URL", "https://github.com/95ge/cfquant.git").strip()
DEFAULT_UPDATE_REF = os.environ.get("CFQUANT_UPDATE_REF", "main").strip()
UPDATE_REMOTE_CACHE_SECONDS = float(os.environ.get("CFQUANT_UPDATE_REMOTE_CACHE_SECONDS", "300"))
UPDATE_REMOTE_TIMEOUT_SECONDS = float(os.environ.get("CFQUANT_UPDATE_REMOTE_TIMEOUT_SECONDS", "12"))
PROJECT_UPDATE_DIR = os.path.join(BASE_DIR, ".cfquant_project_updates")
PROJECT_UPDATE_BACKUP_KEEP = int(os.environ.get("CFQUANT_PROJECT_UPDATE_BACKUP_KEEP", "2"))
QMT_ENTRY_SCRIPT_NAMES = (
    "CFQUANT_CTYPE_ALL_LOWLAT.py",
    "CFQUANT.py",
    "CFQUANT_TRADE_LOWLAT.py",
)
WEB_BOUND_HOST = None
WEB_BOUND_PORT = None
WEB_RESTART_REQUEST = None
WEB_RESTART_LOCK = threading.RLock()
WEB_AUTH_TOKENS = {}
WEB_AUTH_LOCK = threading.RLock()
WEB_AUTH_COOKIE_NAME = "cfquant_web_token"
WEB_AUTH_SESSION_TTL_SECONDS = float(os.environ.get("CFQUANT_WEB_AUTH_SESSION_TTL_SECONDS", str(30 * 24 * 3600)))
STOCK_BUY = 23
STOCK_SELL = 24
FIX_PRICE = 11
ACCOUNT_ACTIONS = {
    "asset": "xttrader.query_stock_asset",
    "positions": "xttrader.query_stock_positions",
    "orders": "xttrader.query_stock_orders",
    "trades": "xttrader.query_stock_trades",
}
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
}
DOWNLOAD_CALLBACK_EVENT = "xtdata:download_progress"
DOWNLOAD_EVENT_PREFIX = "xtdata:download"


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
        "3": "CREDIT",
        "CREDIT": "CREDIT",
        "MARGIN": "CREDIT",
        "MARGIN_TRADING": "CREDIT",
        "CREDIT_ACCOUNT": "CREDIT",
        "信用": "CREDIT",
        "信用账户": "CREDIT",
        "融资融券": "CREDIT",
    }
    account_type = aliases.get(upper) or aliases.get(text) or upper
    if account_type not in ("STOCK", "CREDIT"):
        raise ValueError("unsupported account_type: %s" % text)
    return account_type


def account_type_label(account_type):
    return ACCOUNT_TYPE_LABELS.get(normalize_account_type(account_type), normalize_account_type(account_type))


def account_key_for(account_id, account_type=None, bridge_id=None):
    account_id = str(account_id or "").strip()
    if not account_id:
        return ""
    return "%s:%s:%s" % (
        normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID),
        normalize_account_type(account_type),
        account_id,
    )


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
        return {
            "initialized": initialized,
            "setup_required": not initialized,
            "default_account_id": default_account_id,
            "default_account_type": default_account_type,
            "default_account_key": default_account_key,
            "default_qmt_dir": default_config.get("qmt_dir") or "",
            "default_mode": normalize_transport_mode(
                default_config.get("mode") or self.transport_mode()
            ),
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
        qmt_dir=None,
        mode="ctypes",
        data_provider=False,
        enabled=True,
    ):
        account_id = str(account_id or "").strip()
        if not account_id:
            raise ValueError("account_id is required")
        account_type = normalize_account_type(account_type)
        qmt_dir = normalize_optional_path(qmt_dir)
        mode = normalize_transport_mode(mode)
        now = time.time()
        with self._lock:
            configs = self._data.setdefault("account_configs", {})
            bridge_id = self._account_bridge_id_locked(account_id, account_type, bridge_id, qmt_dir)
            account_key = account_key_for(account_id, account_type, bridge_id)
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
            row = {
                "account_key": account_key,
                "account_id": account_id,
                "account_type": account_type,
                "account_type_label": account_type_label(account_type),
                "bridge_id": bridge_id,
                "qmt_dir": qmt_dir,
                "mode": mode,
                "data_provider": bool(data_provider),
                "enabled": bool(enabled),
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

    def save_pair(self, account_id, bridge_id, account_type="STOCK", account_key=None):
        account_id = str(account_id or "").strip()
        account_type = normalize_account_type(account_type)
        bridge_id = normalize_bridge_id(bridge_id)
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
            account_key = str(item.get("account_key") or "").strip() or account_key_for(account_id, account_type, bridge_id)
            result[account_key] = {
                "account_key": account_key,
                "account_id": account_id,
                "account_type": account_type,
                "account_type_label": account_type_label(account_type),
                "bridge_id": bridge_id,
                "qmt_dir": qmt_dir,
                "mode": normalize_transport_mode(item.get("mode") or "ctypes"),
                "data_provider": bool(item.get("data_provider")),
                "enabled": item.get("enabled", True) is not False,
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
    if value in ("lttx", "socket", "normal", "default"):
        return "lttx"
    raise ValueError("unknown transport mode: %s" % value)


def transport_mode_label(mode):
    mode = normalize_transport_mode(mode)
    return "通用模式" if mode == "ctypes" else "高级模式"


def transport_mode_detail_label(mode):
    mode = normalize_transport_mode(mode)
    return "ctypes 通用版" if mode == "ctypes" else "LTtx 普通/极速双桥"


def transport_mode_summary(mode):
    mode = normalize_transport_mode(mode)
    return {
        "mode": mode,
        "label": transport_mode_label(mode),
        "detail_label": transport_mode_detail_label(mode),
        "request_scope": "单文件双通道" if mode == "ctypes" else "普通桥 + 交易桥",
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


def resolve_bridge_id(account_id=None, bridge_id=None, account_type=None, account_key=None):
    account_id = str(account_id or "").strip()
    account_key = str(account_key or "").strip()
    if account_id or account_key:
        runtime = WEB_CONFIG.account_config(
            account_id=account_id,
            account_type=account_type,
            bridge_id=bridge_id,
            account_key=account_key,
        ) if WEB_CONFIG is not None else None
        if runtime and runtime.get("bridge_id"):
            return normalize_bridge_id(runtime.get("bridge_id"))
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
    raw_bridge_id = str(bridge_id or "").strip()
    if raw_bridge_id:
        return normalize_bridge_id(raw_bridge_id)
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
    return "ctypes"


def route_channel_for_account(account_id, requested_channel=None, default="normal", mode=None, account_type=None, bridge_id=None, account_key=None):
    default = normalize_channel(default, "normal")
    mode = normalize_transport_mode(mode or resolve_account_mode(account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key))
    if mode == "ctypes":
        return default
    return normalize_channel(requested_channel, default)


def callback_channels():
    channels = []
    for bridge in current_bridges().values():
        channel = bridge["channels"]["callback"]
        if channel not in channels:
            channels.append(channel)
    return channels


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
        except CfquantError:
            raise
        except CfquantTimeout as e:
            if mark_offline_on_timeout:
                self._mark_failed(cooldown_key, e)
            raise
        except Exception as e:
            self._mark_failed(cooldown_key, e)
            self.close(mode)
            raise

    def close(self, mode=None):
        modes = [normalize_transport_mode(mode)] if mode else ["ctypes", "lttx"]
        with self._lock:
            clients = [self._clients.pop(item, None) for item in modes]
        for client in clients:
            if client is None:
                continue
            try:
                client.close()
            except Exception:
                pass

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
        with self._lock:
            client = self._clients.get(mode)
            if client is None:
                if mode == "ctypes":
                    cfg = get_cfquant_config()
                    from cfquant.pipe_client import PipeRpcClient

                    client = PipeRpcClient(
                        pipe_name=os.environ.get("CFQUANT_PIPE_NAME") or cfg.get("pipe_name") or DEFAULT_PIPE_NAME,
                        request_channel=CHANNELS["normal"],
                        timeout=cfg.get("timeout"),
                        client_id="%s_ctypes" % self.client_id,
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
):
    account_id = str(account_id or "").strip()
    request_params = params if isinstance(params, dict) else {}
    request_account = request_params.get("account") if isinstance(request_params.get("account"), dict) else {}
    account_type = normalize_account_type(account_type or request_account.get("account_type") or request_params.get("account_type") or "STOCK")
    bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=bridge_id, account_type=account_type, account_key=account_key)
    preferred_mode = resolve_account_mode(account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key)
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
            account_key=account_key,
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
                "account_id": account_id,
                "account_type": account_type,
                "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
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
        result.append({
            "account_key": account_key_for(configured_default_account_id(), configured_default_account_type(), DEFAULT_BRIDGE_ID),
            "account_id": configured_default_account_id(),
            "account_type": configured_default_account_type(),
            "bridge_id": DEFAULT_BRIDGE_ID,
        })
    return result


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
        target_bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=bridge_id or account.get("bridge_id"), account_type=account_type, account_key=account_key)
        try:
            route = account_request(
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
            route["data_provider_account_key"] = account_key
            route["provider_fallback"] = bool(attempts)
            route["provider_attempts"] = attempts + [{
                "account_id": account_id,
                "account_type": account_type,
                "account_key": account_key,
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
                "ok": False,
                "error": str(error),
            })
    detail = "; ".join(
        "%s/%s: %s" % (row["account_id"], row.get("account_type") or "STOCK", row.get("error") or "")
        for row in attempts
    )
    raise RuntimeError(
        "%s failed for all data providers: %s" % (action, detail or str(last_error or "no provider"))
    )


def account_route_status(account_id, bridge_id=None, account_type=None, account_key=None):
    account_id = str(account_id or "").strip() or configured_default_account_id()
    account_type = normalize_account_type(account_type or configured_default_account_type())
    bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=bridge_id, account_type=account_type, account_key=account_key)
    account_key = account_key or account_key_for(account_id, account_type, bridge_id)
    preferred_mode = resolve_account_mode(account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key)
    ctypes_status = ctypes_bridge_status(bridge_id)
    if preferred_mode == "lttx":
        advanced = _advanced_mode_readiness(bridge_id)
    else:
        advanced = {
            "bridge_id": bridge_id,
            "bridge_name": bridge_config(bridge_id)["name"],
            "ready": False,
            "missing": [],
            "skipped": True,
            "reason": "当前账号为通用模式，LTtx 不参与状态探测",
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
    return {
        "account_id": account_id,
        "account_type": account_type,
        "account_type_label": account_type_label(account_type),
        "account_key": account_key,
        "bridge_id": bridge_id,
        "preferred_mode": preferred_mode,
        "effective_mode": effective_mode,
        "fallback": fallback,
        "qmt_dir": (WEB_CONFIG.account_config(account_id=account_id, account_type=account_type, bridge_id=bridge_id, account_key=account_key) or {}).get("qmt_dir", ""),
        "data_provider": account_key == (WEB_CONFIG.data_provider_account_key() if WEB_CONFIG else ""),
        "ready": advanced_ready if effective_mode == "lttx" else ctypes_ready,
        "status": selected,
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


class PipeHubManager(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._status = None
        self._last_error = ""

    def _python_exe(self):
        return sys.executable

    def status(self):
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
                if os.path.basename(os.path.abspath(PIPE_HUB_ENTRY)).lower() in status_command.lower():
                    process_pid = status_pid
                    running = True
        if not running:
            entry_name = os.path.basename(os.path.abspath(PIPE_HUB_ENTRY)).lower()
            rows = run_powershell_json(
                "$name='%s'; "
                "$rows=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
                "Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -and $_.CommandLine.ToLower().Contains($name) } | "
                "ForEach-Object { [pscustomobject]@{ pid=$_.ProcessId; command_line=$_.CommandLine } }); "
                "if ($null -eq $rows) { '[]' } else { @($rows) | ConvertTo-Json -Compress }"
                % entry_name.replace("'", "''"),
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
        return {
            "running": running,
            "pipe_name": (self._status or {}).get("pipe_name") or normalize_pipe_name(os.environ.get("CFQUANT_PIPE_NAME") or DEFAULT_PIPE_NAME),
            "status_file": PIPE_HUB_STATUS_FILE,
            "process_pid": process_pid,
            "last_error": self._last_error,
            "status": self._status or {},
            "entry": os.path.abspath(PIPE_HUB_ENTRY),
            "checked_at": time.time(),
        }

    def start(self):
        with self._lock:
            if self._process is not None and getattr(self._process, "poll", lambda: 1)() is None:
                return self.status()
            current = self.status()
            if current.get("running"):
                return current
            entry = os.path.abspath(PIPE_HUB_ENTRY)
            if not os.path.isfile(entry):
                raise RuntimeError("pipe hub entry not found: %s" % entry)
            creationflags = 0
            if os.name == "nt":
                creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            env = os.environ.copy()
            env.setdefault("CFQUANT_LOG_DIR", LOG_DIR)
            env.setdefault("CFQUANT_LOG_RETENTION_DAYS", str(LOG_RETENTION_DAYS))
            env.setdefault("CFQUANT_PIPE_HUB_STATUS_FILE", PIPE_HUB_STATUS_FILE)
            stdout = open(PIPE_HUB_STDOUT_LOG, "a", encoding="utf-8", buffering=1)
            stderr = open(PIPE_HUB_STDERR_LOG, "a", encoding="utf-8", buffering=1)
            try:
                self._process = subprocess.Popen(
                    [self._python_exe(), entry],
                    cwd=BASE_DIR,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    env=env,
                    creationflags=creationflags,
                    close_fds=False if os.name == "nt" else True,
                )
            finally:
                try:
                    stdout.close()
                    stderr.close()
                except Exception:
                    pass
            time.sleep(0.8)
            return self.status()

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
                )
                if completed.returncode != 0:
                    self._last_error = (completed.stderr or completed.stdout or "").strip()
            except Exception as e:
                self._last_error = str(e)
        return self.status()

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
    if action in {
        "xtdata.subscribe_quote",
        "xtdata.subscribe_whole_quote",
        "xtdata.unsubscribe_quote",
        "xtdata.download_history_data",
        "xtdata.download_history_data2",
        "xtdata.download_financial_data",
        "xtdata.download_financial_data2",
    }:
        return "normal"
    if action.startswith("xttrader."):
        return "normal"
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
            route = account_request(
                account_id,
                params.get("bridge_id"),
                requested_channel,
                action,
                params,
                default_channel=default_channel,
                timeout=timeout,
                mark_offline_on_timeout=True,
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
            account_key = _external_account_key(params) or account_key_for(
                account_id,
                account_type,
                params.get("bridge_id") or resolve_bridge_id(account_id=account_id, account_type=account_type),
            )
            if account_id:
                with self._lock:
                    self._account_subscribers.setdefault(account_key, set()).add(client_id)
        elif action == "xttrader.unsubscribe":
            account_id = _external_account_id(params)
            account_type = _external_account_type(params)
            account_key = _external_account_key(params)
            if account_id and not account_key:
                account_key = account_key_for(
                    account_id,
                    account_type,
                    params.get("bridge_id") or resolve_bridge_id(account_id=account_id, account_type=account_type),
                )
            with self._lock:
                if account_key:
                    subscribers = self._account_subscribers.get(account_key)
                    if subscribers:
                        subscribers.discard(client_id)
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
        account_key = account_key_for(account_id, account_type, bridge_id) if account_id else ""
        with self._lock:
            client_ids = sorted(self._account_subscribers.get(account_key, set()))
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


def ctypes_bridge_status(bridge_id=DEFAULT_BRIDGE_ID):
    bridge_id = normalize_bridge_id(bridge_id)
    channels = bridge_channels(bridge_id)
    hub = PIPE_HUB.status()
    hub_status = hub.get("status") or {}
    connected_channels = set(hub_status.get("qmt_channels") or [])
    now = time.time()
    result = {
        "bridge_id": bridge_id,
        "bridge_name": bridge_config(bridge_id)["name"],
        "normal": {
            "online": bool(hub.get("running") and channels["normal"] in connected_channels),
            "channel": channels["normal"],
            "probe_action": "pipe_hub.status",
            "status": {
                "bridge": "PipeNormalQmtBridge",
                "transport": "pipe",
                "pipe_name": hub.get("pipe_name"),
                "request_channel": channels["normal"],
                "pipe_connected": channels["normal"] in connected_channels,
            },
        },
        "trade": {
            "online": bool(hub.get("running") and channels["trade"] in connected_channels),
            "channel": channels["trade"],
            "probe_action": "pipe_hub.status",
            "status": {
                "bridge": "PipeTradeBridge",
                "transport": "pipe",
                "pipe_name": hub.get("pipe_name"),
                "request_channel": channels["trade"],
                "pipe_connected": channels["trade"] in connected_channels,
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
    def __init__(self, sock, bridge_id="", account_id="", account_type="", event_name="", event_prefix="", job_id=""):
        self.sock = sock
        self.bridge_id = normalize_bridge_id(bridge_id) if bridge_id else ""
        self.account_id = str(account_id or "").strip()
        self.account_type = normalize_account_type(account_type) if account_type not in ("", None) else ""
        self.event_name = str(event_name or "").strip()
        self.event_prefix = str(event_prefix or "").strip()
        self.job_id = str(job_id or "").strip()
        self._lock = threading.RLock()
        self.alive = True

    def matches(self, event):
        if self.bridge_id and normalize_bridge_id(CallbackEventStore.event_bridge_id_static(event) or "default") != self.bridge_id:
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
            timeout=12.0,
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
            timeout=8.0,
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
            safe_print("cfquant callback listeners started in mixed mode")
        except Exception as e:
            self._running = False
            safe_print("cfquant callback listener start failed: %s" % e)

    def close(self):
        self._running = False
        try:
            CLIENTS.remove_callback("__event__", self._on_client_event)
        except Exception:
            pass
        for client in list(self._pipe_clients.values()):
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

    def latest(self, since=0, limit=200, bridge_id=None, account_id=None, account_type=None, event_name=None, event_prefix=None, job_id=None):
        bridge_id = normalize_bridge_id(bridge_id) if bridge_id else None
        account_id = str(account_id or "").strip()
        account_type = normalize_account_type(account_type) if account_type not in ("", None) else ""
        event_name = str(event_name or "").strip()
        event_prefix = str(event_prefix or "").strip()
        job_id = str(job_id or "").strip()
        with self._lock:
            rows = [row for row in self._events if row.get("seq", 0) > since]
            if bridge_id:
                rows = [
                    row
                    for row in rows
                    if normalize_bridge_id(self.event_bridge_id_static(row) or "default") == bridge_id
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
                    if self.event_account_type_static(row) == account_type
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
                    self._append(event)
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
        try:
            payload = json.loads(value)
        except Exception:
            payload = {"raw": value}
        if isinstance(payload, dict):
            payload.setdefault("key", key)
            return payload
        return {"key": key, "data": payload}

    def _append(self, event):
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
            self._events.append(row)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]
        WS_CALLBACKS.broadcast(row)

    def _on_client_event(self, event):
        if not isinstance(event, dict):
            return
        if event.get("type") != "event":
            return
        self._append(event)

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
                client.add_callback("__event__", self._on_client_event)
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
            if normalize_bridge_id(config.get("bridge_id") or DEFAULT_BRIDGE_ID) != bridge_id:
                continue
            if str(config.get("account_id") or "").strip() != account_id:
                continue
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
        repo_url = str(repo_url or DEFAULT_UPDATE_REPO_URL).strip()
        ref = str(ref or DEFAULT_UPDATE_REF).strip()
        result = {
            "bridge_id": bridge_id,
            "bridge_name": bridge.get("name") or bridge_id,
            "python_dir": python_dir,
            "configured": bool(python_dir),
            "ready": False,
            "errors": [],
            "warnings": [],
            "targets": {},
            "backups": [],
            "current_version": "",
            "last_update": {},
            "version_status": self._build_version_status(None, "", {}, repo_url, ref),
            "default_repo_url": repo_url,
            "default_ref": ref,
        }
        if not python_dir:
            result["errors"].append("桥接端未设置 QMT 核心目录")
            return result
        try:
            target = self._target_paths(python_dir)
            result["targets"] = target
            result["backups"] = self._list_backups(target["backup_dir"])
            result["current_version"] = self._read_version(target["current_core"])
            result["last_update"] = self._read_install_meta(target["updates_dir"])
            result["version_status"] = self._build_version_status(
                target,
                result["current_version"],
                result["last_update"],
                repo_url,
                ref,
            )
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

    def rollback(self, bridge_id, backup_name=None):
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

    def _require_ready_target(self, bridge_id):
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

    def _install_source(self, bridge_id, source_dir, meta):
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

    def _build_version_status(self, target, current_version, last_update, repo_url, ref):
        current = self._current_version_info(target, current_version, last_update)
        remote = self._remote_version_info(repo_url, ref)
        matches_remote = None
        current_commit = (current.get("commit") or "").lower()
        remote_commit = (remote.get("commit") or "").lower()
        if current_commit and remote_commit:
            matches_remote = current_commit == remote_commit
        return {
            "current": current,
            "remote": remote,
            "matches_remote": matches_remote,
        }

    def _current_version_info(self, target, current_version, last_update):
        last_update = last_update if isinstance(last_update, dict) else {}
        source = last_update.get("source") if isinstance(last_update.get("source"), dict) else {}
        fetch = source.get("fetch") if isinstance(source.get("fetch"), dict) else {}
        commit = str(fetch.get("commit") or source.get("commit") or last_update.get("commit") or "").strip()
        source_name = "last_update" if commit else ""
        if not commit and target:
            commit = self._git_commit_near(target.get("project_dir") or target.get("python_dir") or "")
            if commit:
                source_name = "git"
        updated_at_text = str(last_update.get("updated_at_text") or "").strip()
        return {
            "version": str(current_version or "").strip(),
            "commit": commit,
            "short_commit": self._short_commit(commit),
            "source": source_name,
            "updated_at_text": updated_at_text,
        }

    def _remote_version_info(self, repo_url, ref):
        repo_url = str(repo_url or "").strip()
        ref = str(ref or "").strip()
        cache_key = "%s#%s" % (repo_url, ref)
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
            "commit": "",
            "short_commit": "",
            "checked_at": now,
            "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "cached": False,
            "error": "",
        }
        if not repo_url:
            result["error"] = "未配置 GitHub 仓库"
        else:
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
                    )
                    output = (completed.stdout or "").strip()
                    if completed.returncode == 0 and output:
                        first = output.splitlines()[0].split()
                        if first:
                            result["commit"] = first[0]
                            result["short_commit"] = self._short_commit(first[0])
                            result["remote_ref"] = first[1] if len(first) > 1 else ref_name
                            result["source"] = "git ls-remote"
                            break
                    message = (completed.stderr or completed.stdout or "").strip()
                    errors.append("%s: %s" % (ref_name, message or ("exit %s" % completed.returncode)))
                except Exception as e:
                    errors.append("%s: %s" % (ref_name, str(e) or repr(e)))
            if not result["commit"]:
                result["error"] = "; ".join(errors) or "未获取到远端版本"
        with self._remote_lock:
            self._remote_cache[cache_key] = dict(result)
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
        if "CFQUANT.py" in entries or "CFQUANT_TRADE_LOWLAT.py" in entries:
            raise RuntimeError("源码核心目录包含入口脚本，已拒绝覆盖")

    def _copy_core(self, source_core, target_core):
        self._remove_tree(target_core)
        shutil.copytree(
            source_core,
            target_core,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache"),
        )

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
        "pic",
        "remotion_intro",
    }
    PRESERVED_REL_PATHS = {
        "AGENTS.md",
        ".env",
        "cfquant_web_config.json",
        "cfquant_web_config.db",
        "cfquant_pipe_hub_status.json",
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


def write_qmt_bridge_identity(row):
    row = row or {}
    bridge_id = normalize_bridge_id(row.get("bridge_id") or DEFAULT_BRIDGE_ID)
    qmt_dir = normalize_optional_path(row.get("qmt_dir") or row.get("python_dir"))
    account_type = normalize_account_type(row.get("account_type") or "STOCK")
    result = {
        "written": False,
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
            "pipe_name": normalize_pipe_name(os.environ.get("CFQUANT_PIPE_NAME") or DEFAULT_PIPE_NAME),
            "channels": channels,
            "qmt_log_language": WEB_CONFIG.qmt_log_language() if WEB_CONFIG is not None else "zh",
            "qmt_log_enabled": WEB_CONFIG.qmt_log_enabled() if WEB_CONFIG is not None else True,
            "updated_at": time.time(),
            "updated_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "source": "cfquant_web_account_binding",
        }
        path = os.path.join(core_dir, QMT_BRIDGE_CONFIG_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
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


def sync_qmt_bridge_identities():
    results = []
    try:
        configs = WEB_CONFIG.account_configs() if WEB_CONFIG is not None else {}
        for row in configs.values():
            if not isinstance(row, dict):
                continue
            if not normalize_optional_path(row.get("qmt_dir") or row.get("python_dir")):
                continue
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
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=float(timeout),
    )
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
    pids = [int(pid) for pid in pids if int(pid) > 0]
    if not pids:
        return {}
    ids = ",".join(str(pid) for pid in pids)
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
    rows = run_powershell_json(script, timeout=5.0)
    details = {}
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
    env = os.environ.copy()
    env.setdefault("CFQUANT_LOG_DIR", LOG_DIR)
    env.setdefault("CFQUANT_LOG_RETENTION_DAYS", str(LOG_RETENTION_DAYS))
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
            creationflags=creationflags,
            close_fds=False if os.name == "nt" else True,
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


def stop_lttx_server():
    before = lttx_status()
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
    if not code.isdigit():
        raise ValueError("stock_code must be numeric before market suffix")
    number = int(code)
    if number < 0 or number > 999999:
        raise ValueError("stock_code numeric part is out of range: %s" % code)
    if market not in ("SH", "SZ"):
        raise ValueError("market suffix must be SH or SZ")
    return "%06d.%s" % (number, market)


def normalize_channel(value, default="normal"):
    value = (value or default or "normal").strip().lower()
    if value not in ("normal", "trade"):
        raise ValueError("unknown channel: %s" % value)
    return value


def web_request_channel(value=None, default="normal"):
    default = normalize_channel(default, "normal")
    if WEB_CONFIG.transport_mode() == "ctypes":
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
        return {
            "online": True,
            "channel": channel,
            "status": status,
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

    def latest(self, bridge_id=DEFAULT_BRIDGE_ID):
        bridge_id = normalize_bridge_id(bridge_id)
        if not bridge_has_lttx_account(bridge_id):
            return ctypes_bridge_status(bridge_id)
        channels = bridge_channels(bridge_id)
        with self._lock:
            if bridge_id in self._snapshots:
                return self._snapshots[bridge_id]
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
            },
        }

    def _loop(self):
        while self._running:
            started = time.time()
            try:
                for bridge_id in current_bridges():
                    bridge_started = time.time()
                    if not bridge_has_lttx_account(bridge_id):
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
                        "probe_ms": round((time.time() - bridge_started) * 1000, 2),
                    }
                    with self._lock:
                        self._snapshots[bridge_id] = snapshot
            except Exception as e:
                safe_print("channel status monitor probe failed: %s" % e)
            elapsed = time.time() - started
            delay = max(0.5, self.interval - elapsed)
            self._stop_event.wait(delay)


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
                timeout=timeout,
                mark_offline_on_timeout=False,
                account_type=account_type,
                account_key=account_key,
            )
            data = route["result"]
            result[section] = {
                "ok": True,
                "data": data,
                "mode": route["mode"],
                "channel": route["channel"],
                "fallback": route["fallback"],
                "fallback_reason": route["fallback_reason"],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except Exception as e:
            result[section] = {
                "ok": False,
                "error": str(e),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
    return result


class AccountDataCache(object):
    def __init__(self, interval=ACCOUNT_CACHE_REFRESH_SECONDS):
        self.interval = float(interval)
        self._lock = threading.RLock()
        self._entries = {}
        self._subscriptions = {}
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
        safe_print("cfquant account data cache started interval=%ss" % self.interval)

    def close(self):
        self._running = False
        self._stop_event.set()

    def get(self, bridge_id, channel, account_id, sections, force=False, subscribe=True, account_type="STOCK", account_key=None):
        bridge_id = normalize_bridge_id(bridge_id)
        account_type = normalize_account_type(account_type)
        account_key = account_key or account_key_for(account_id, account_type, bridge_id)
        sections = [section for section in sections if section in ACCOUNT_ACTIONS]
        if not sections:
            return {"bridge_id": bridge_id, "account_id": account_id, "account_type": account_type, "account_key": account_key, "channel": channel}
        if not subscribe:
            live = query_account_live(bridge_id, channel, account_id, sections, account_type=account_type, account_key=account_key)
            live["cache"] = {
                "enabled": False,
                "force": bool(force),
                "subscribed": False,
            }
            return live
        self._subscribe(bridge_id, channel, account_id, sections, account_type=account_type, account_key=account_key)
        if force:
            live = query_account_live(bridge_id, channel, account_id, sections, account_type=account_type, account_key=account_key)
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
                stored = dict(row)
                stored["checked_at"] = now
                stored["checked_at_text"] = checked_at_text
                stored["account_type"] = account_type
                stored["account_key"] = account_key
                self._entries[self._cache_key(bridge_id, channel, account_id, section, account_type=account_type, account_key=account_key)] = stored

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
            subscriptions = [
                (bridge_id, channel, account_key, account_id, account_type, sorted(sections))
                for (bridge_id, channel, account_key, account_id, account_type), sections in self._subscriptions.items()
                if account_id and sections
            ]
        for bridge_id, channel, account_key, account_id, account_type, sections in subscriptions:
            if not self._running:
                break
            try:
                live = query_account_live(bridge_id, channel, account_id, sections, account_type=account_type, account_key=account_key)
                self._store_result(bridge_id, channel, account_id, live, sections, account_type=account_type, account_key=account_key)
            except Exception as e:
                safe_print(
                    "account data cache refresh failed bridge=%s channel=%s account=%s type=%s error=%s"
                    % (bridge_id, channel, account_id, account_type, e)
                )


ACCOUNT_CACHE = AccountDataCache()


def submit_order(body):
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
    account_key = str(body.get("account_key") or "").strip()
    bridge_id = resolve_bridge_id(account_id=account_id, account_type=account_type, account_key=account_key, bridge_id=body.get("bridge_id"))
    bridge_config(bridge_id)
    stock_code = normalize_stock_code(body.get("stock_code"))
    side = str(body.get("side") or "").strip().lower()
    price = float(body.get("price"))
    volume = int(body.get("volume"))
    confirm_text = str(body.get("confirm_text") or "").strip()
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if not stock_code:
        raise ValueError("stock_code is required")
    if volume <= 0:
        raise ValueError("volume must be positive")
    if price <= 0:
        raise ValueError("price must be positive")

    expected = "%s %s %s @ %.3f" % (side.upper(), stock_code, volume, price)
    if confirm_text != expected:
        raise ValueError("confirmation mismatch, expected: %s" % expected)

    order_type = STOCK_BUY if side == "buy" else STOCK_SELL
    remark = body.get("order_remark") or "cfquant_web_%s" % int(time.time() * 1000)
    params = {
        "account": {"account_id": account_id, "account_type": account_type},
        "stock_code": stock_code,
        "order_type": order_type,
        "order_volume": volume,
        "price_type": int(body.get("price_type") or FIX_PRICE),
        "price": price,
        "qmt_order_type": int(body.get("qmt_order_type") or 1101),
        "quick_trade": int(body.get("quick_trade") or 2),
        "strategy_name": body.get("strategy_name") or "cfquant_web",
        "order_remark": remark,
    }
    started = time.perf_counter()
    route = account_request(
        account_id,
        bridge_id,
        body.get("channel"),
        "xttrader.order_stock",
        params,
        default_channel="trade",
        timeout=12.0,
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
        "order_remark": remark,
    }


def submit_batch_orders(body):
    account_id = str(body.get("account_id") or "").strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
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
    orders = []
    for index, row in enumerate(raw_orders):
        if not isinstance(row, dict):
            raise ValueError("orders[%s] must be an object" % index)
        side = str(row.get("side") or body.get("side") or "buy").strip().lower()
        if side not in ("buy", "sell"):
            raise ValueError("orders[%s].side must be buy or sell" % index)
        price = float(row.get("price"))
        volume = int(row.get("volume") or row.get("order_volume"))
        if price <= 0:
            raise ValueError("orders[%s].price must be positive" % index)
        if volume <= 0:
            raise ValueError("orders[%s].volume must be positive" % index)
        orders.append({
            "stock_code": normalize_stock_code(row.get("stock_code") or row.get("code")),
            "order_type": STOCK_BUY if side == "buy" else STOCK_SELL,
            "order_volume": volume,
            "price_type": int(row.get("price_type") or body.get("price_type") or FIX_PRICE),
            "price": price,
            "qmt_order_type": int(row.get("qmt_order_type") or body.get("qmt_order_type") or 1101),
            "quick_trade": int(row.get("quick_trade") or body.get("quick_trade") or 2),
            "strategy_name": row.get("strategy_name") or body.get("strategy_name") or "cfquant_web_batch",
            "order_remark": row.get("order_remark") or "cfquant_batch_%s_%s" % (int(time.time() * 1000), index + 1),
        })
    params = {
        "account": {"account_id": account_id, "account_type": account_type},
        "orders": orders,
        "stop_on_error": parse_bool(body.get("stop_on_error")),
        "order_remark": body.get("order_remark") or "cfquant_batch_%s" % int(time.time() * 1000),
    }
    started = time.perf_counter()
    route = account_request(
        account_id,
        bridge_id,
        body.get("channel"),
        "xttrader.order_stock_batch",
        params,
        default_channel="trade",
        timeout=max(12.0, len(orders) * 3.0),
        account_type=account_type,
        account_key=account_key,
    )
    return {
        "bridge_id": route["bridge_id"],
        "channel": route["channel"],
        "mode": route["mode"],
        "fallback": route["fallback"],
        "fallback_reason": route["fallback_reason"],
        "account_id": account_id,
        "account_type": account_type,
        "account_key": account_key or account_key_for(account_id, account_type, bridge_id),
        "result": route["result"],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


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
    route = account_request(
        account_id,
        bridge_id,
        body.get("channel"),
        "xttrader.cancel_order_stock",
        params,
        default_channel="trade",
        timeout=12.0,
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
    CALLBACKS.refresh_channels(callback_channels())
    return {
        "bridges": WEB_CONFIG.bridges(),
        "account_pairs": WEB_CONFIG.account_pairs(),
    }


def save_account_pair(body):
    row = WEB_CONFIG.save_pair(
        (body or {}).get("account_id"),
        (body or {}).get("bridge_id"),
        account_type=(body or {}).get("account_type") or "STOCK",
        account_key=(body or {}).get("account_key"),
    )
    STATUS_MONITOR.wake()
    return {
        "pair": row,
        "account_pairs": WEB_CONFIG.account_pairs(),
    }


def ensure_account_runtime(mode):
    mode = normalize_transport_mode(mode)
    results = {"mode": mode, "ctypes": None, "lttx": None}
    try:
        results["ctypes"] = start_pipe_hub()
    except Exception as error:
        results["ctypes"] = {"ok": False, "error": str(error)}
        safe_print("cfquant account config ctypes runtime start failed: %s" % error)
    if mode == "lttx":
        try:
            status = lttx_status()
            results["lttx"] = (
                {"started": False, "status": status}
                if status.get("running")
                else start_lttx_server()
            )
        except Exception as error:
            results["lttx"] = {"ok": False, "error": str(error)}
            safe_print("cfquant account config LTtx runtime start failed: %s" % error)
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
    qmt_dir = body.get("qmt_dir") or body.get("python_dir")
    mode = body.get("mode") or body.get("transport_mode") or "ctypes"
    row = WEB_CONFIG.save_account_config(
        account_id=account_id,
        account_type=account_type,
        bridge_id=bridge_id,
        qmt_dir=qmt_dir,
        mode=mode,
        data_provider=parse_bool(body.get("data_provider")),
        enabled=body.get("enabled", True) is not False,
    )
    identity = write_qmt_bridge_identity(row)
    STATUS_MONITOR.wake()
    CALLBACKS.refresh_channels(callback_channels())
    return {
        "account": row,
        "qmt_bridge_identity": identity,
        "runtime": ensure_account_runtime(row["mode"]),
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
    return {
        "setup": WEB_CONFIG.setup_info(),
        "account_pairs": WEB_CONFIG.account_pairs(),
        "account_configs": WEB_CONFIG.account_configs(),
    }


def initialize_web_setup(body):
    body = body or {}
    account_id = str(body.get("account_id") or DEFAULT_ACCOUNT_ID).strip()
    account_type = normalize_account_type(body.get("account_type") or "STOCK")
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
        qmt_dir=body.get("qmt_dir") or body.get("python_dir"),
        mode=body.get("mode") or "ctypes",
        data_provider=True,
        enabled=True,
    )
    identity = write_qmt_bridge_identity(row)
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
    account = ACCOUNT_CACHE.get(
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
    if mode == "lttx":
        lttx_started = False
        if not lttx_status().get("running"):
            start_lttx_server()
            lttx_started = True
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
        "readiness": _advanced_mode_readiness(bridge_id) if mode == "lttx" else {"ready": True, "mode": "ctypes"},
        "pipe_hub": hub,
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


_PROJECT_VERSION_CACHE = {}
_PROJECT_VERSION_LOCK = threading.RLock()


def _read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _extract_latest_changelog(readme_text):
    result = {
        "version": "",
        "body": "",
        "items": [],
    }
    if not readme_text:
        return result
    match = re.search(r"(?m)^##\s+版本日志\s*$", readme_text)
    if not match:
        return result
    section = readme_text[match.end():]
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
    result["version"] = heading.group(1).strip()
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


def _github_raw_readme_url(repo_url, ref):
    owner, repo = _parse_github_repo_name(repo_url)
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    ref_q = urllib.parse.quote(str(ref or "main").strip() or "main", safe="/")
    return "https://raw.githubusercontent.com/%s/%s/%s/README.md" % (owner_q, repo_q, ref_q)


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
    readme_path = os.path.join(BASE_DIR, "README.md")
    changelog = _extract_latest_changelog(_read_text_file(readme_path))
    core_info = current_core_version_info()
    version = core_info["version"]
    return {
        "version": version,
        "readme_version": changelog.get("version") or "",
        "source": core_info["source"],
        "version_path": core_info["path"],
        "file_version": core_info["file_version"],
        "imported_version": core_info["imported_version"],
        "import_stale": core_info["import_stale"],
        "checked_at": core_info["checked_at"],
        "checked_at_text": core_info["checked_at_text"],
        "readme_path": readme_path,
        "matches_readme": (changelog.get("version") or "") == version if changelog.get("version") else None,
        "changelog": changelog,
    }


def _remote_project_version_info(repo_url=None, ref=None, force=False):
    repo_url = str(repo_url or DEFAULT_UPDATE_REPO_URL).strip()
    ref = str(ref or DEFAULT_UPDATE_REF).strip() or "main"
    cache_key = "%s#%s" % (repo_url, ref)
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
        "ref": ref,
        "readme_url": "",
        "version": "",
        "checked_at": now,
        "checked_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "cached": False,
        "error": "",
        "changelog": {
            "version": "",
            "body": "",
            "items": [],
        },
    }
    if not repo_url:
        result["error"] = "未配置 GitHub 仓库"
        return result
    try:
        result["readme_url"] = _github_raw_readme_url(repo_url, ref)
        request = urllib.request.Request(
            result["readme_url"],
            headers={"User-Agent": "cfquant-web/%s" % current_core_version()},
        )
        with urllib.request.urlopen(request, timeout=UPDATE_REMOTE_TIMEOUT_SECONDS) as response:
            raw = response.read(512 * 1024)
        text = raw.decode("utf-8", errors="replace")
        result["changelog"] = _extract_latest_changelog(text)
        result["version"] = result["changelog"].get("version") or ""
        if not result["version"]:
            result["error"] = "远端 README 未解析到版本日志"
    except Exception as e:
        result["error"] = str(e) or repr(e)
    with _PROJECT_VERSION_LOCK:
        _PROJECT_VERSION_CACHE[cache_key] = dict(result)
    return result


def project_version_info(include_remote=False, force=False, repo_url=None, ref=None):
    repo_url = str(repo_url or DEFAULT_UPDATE_REPO_URL).strip()
    ref = str(ref or DEFAULT_UPDATE_REF).strip() or "main"
    local = _local_project_version_info()
    core_version = local.get("version") or current_core_version()
    data = {
        "current_version": core_version,
        "core_version": core_version,
        "imported_core_version": CORE_VERSION,
        "core_version_source": local.get("source") or "",
        "core_version_path": local.get("version_path") or "",
        "core_version_import_stale": bool(local.get("import_stale")),
        "web_version": WEB_VERSION,
        "frontend_version": WEB_VERSION,
        "repo_url": repo_url,
        "ref": ref,
        "local": local,
        "remote": None,
        "comparison": "unchecked",
        "update_available": None,
    }
    if include_remote:
        remote = _remote_project_version_info(repo_url=repo_url, ref=ref, force=force)
        comparison = _compare_project_versions(core_version, remote.get("version"))
        data["remote"] = remote
        data["comparison"] = comparison
        data["update_available"] = comparison in ("newer", "different")
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
    timeout = float(body.get("timeout") or 12.0)
    started = time.perf_counter()
    requested_default = force_channel or preferred_channel or default_channel
    if account_id:
        route = account_request(
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
        provider_fallback = False
        provider_attempts = []
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
        route = account_request(
            account_id,
            body.get("bridge_id"),
            body.get("channel"),
            "xtdata.subscribe_quote",
            params,
            default_channel="normal",
            timeout=12.0,
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
            timeout=12.0,
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
            elif parsed.path == "/api/orders/batch":
                self._write_json(ok(submit_batch_orders(body)))
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
                self._write_json(ok(stop_lttx_server()))
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
                files[name] = {"filename": filename, "content": payload}
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
            elif parsed.path == "/api/transport":
                self._write_json(ok(transport_info()))
            elif parsed.path == "/api/pipe-hub":
                self._write_json(ok(pipe_hub_info()))
            elif parsed.path == "/api/web-auth/status":
                self._write_json(ok(web_auth_status(self._provided_web_token(parsed))))
            elif parsed.path == "/api/log-cleanup":
                self._write_json(ok(log_cleanup_info()))
            elif parsed.path == "/api/qmt-log-language":
                self._write_json(ok(qmt_log_language_info()))
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
                self._write_json(ok(project_version_info(
                    include_remote=include_remote,
                    force=force,
                    repo_url=repo_url,
                    ref=ref,
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
                        event_name=event_name,
                        event_prefix=event_prefix,
                        job_id=job_id,
                    ),
                }))
            elif parsed.path == "/api/account":
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
                self._write_json(ok(ACCOUNT_CACHE.get(
                    bridge_id,
                    channel,
                    account_id,
                    sections,
                    force=force,
                    subscribe=subscribe,
                    account_type=account_type,
                    account_key=account_key,
                )))
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
            header = self.rfile.read(2)
            if not header:
                return None
            b1, b2 = header[0], header[1]
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = int.from_bytes(self.rfile.read(2), "big")
            elif length == 127:
                length = int.from_bytes(self.rfile.read(8), "big")
            mask = self.rfile.read(4) if masked else b""
            payload = self.rfile.read(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            return opcode, payload
        except socket.timeout:
            return None

    def _send_ws_control(self, opcode, payload=b""):
        payload = payload or b""
        length = len(payload)
        if length > 125:
            payload = payload[:125]
            length = 125
        self.request.sendall(bytes([0x80 | opcode, length]) + payload)

    def _serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        path = posixpath.normpath(urllib.parse.unquote(path))
        path = path.lstrip("/")
        full_path = os.path.abspath(os.path.join(STATIC_DIR, path))
        if not full_path.startswith(os.path.abspath(STATIC_DIR)):
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
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as e:
            safe_print("client disconnected while writing static response: %s" % e)

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
    safe_print("cfquant web reload spawning next process url=%s" % (reload_request.get("next_url") or ""))
    try:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=False if os.name == "nt" else True,
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

    if not os.path.isdir(STATIC_DIR):
        raise RuntimeError("static directory not found: %s" % STATIC_DIR)
    global WEB_BOUND_HOST, WEB_BOUND_PORT
    WEB_BOUND_HOST = args.host
    WEB_BOUND_PORT = args.port
    probe_host = "127.0.0.1" if args.host in ("", "0.0.0.0") else args.host
    if tcp_port_open(probe_host, args.port):
        raise RuntimeError("cfquant web port %s is already listening, skip duplicate start" % args.port)
    server = ThreadingHTTPServer((args.host, args.port), CfquantWebHandler)
    try:
        configured_modes = configured_runtime_modes()
        if "lttx" in configured_modes:
            # 高级模式故障时需要立即回退到 ctypes，因此即使没有独立通用账号也要启动 PipeHub。
            configured_modes.add("ctypes")
        if "ctypes" in configured_modes:
            try:
                safe_print("cfquant ctypes 通用版模式已启用，正在启动 PipeHub")
                PIPE_HUB.start()
            except Exception as e:
                safe_print("cfquant PipeHub 自动启动失败: %s" % e)
        auto_start_lttx = str(os.environ.get("CFQUANT_AUTO_START_LTTX", "1")).strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        if auto_start_lttx or "lttx" in configured_modes:
            try:
                lttx = lttx_status()
                if not lttx.get("running"):
                    started = start_lttx_server()
                    reason = "高级模式已启用" if "lttx" in configured_modes else "默认预启动"
                    safe_print("cfquant %s，LTtx 自动启动结果=%s" % (reason, bool(started.get("started"))))
                else:
                    safe_print("cfquant LTtx 已在运行，跳过自动启动")
            except Exception as e:
                safe_print("cfquant LTtx 自动启动失败: %s" % e)
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
