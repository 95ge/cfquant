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
from cfquant.protocol import new_id
from tx import txl


BASE_DIR = _PROJECT_DIR
STATIC_DIR = os.path.join(BASE_DIR, "web_dashboard")
LOG_FILE = os.path.join(BASE_DIR, "cfquant_web_server.runtime.log")
LOG_RETENTION_DAYS = int(os.environ.get("CFQUANT_LOG_RETENTION_DAYS", "5"))
LOG_CLEANUP_INTERVAL_SECONDS = float(os.environ.get("CFQUANT_LOG_CLEANUP_INTERVAL_SECONDS", "21600"))
LTTX_HOST = os.environ.get("CFQUANT_LTTX_HOST", "127.0.0.1")
LTTX_PORT = int(os.environ.get("CFQUANT_LTTX_PORT", "2049"))
LTTX_DIR = os.path.join(BASE_DIR, "LTtx", "tx")
LTTX_ENTRY = os.environ.get("CFQUANT_LTTX_ENTRY") or os.path.join(LTTX_DIR, "LTtx_server.py")
LTTX_STDOUT_LOG = os.path.join(BASE_DIR, "lttx_server.stdout.log")
LTTX_STDERR_LOG = os.path.join(BASE_DIR, "lttx_server.stderr.log")
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
WEB_BOUND_HOST = None
WEB_BOUND_PORT = None
WEB_RESTART_REQUEST = None
WEB_RESTART_LOCK = threading.RLock()
WEB_AUTH_TOKENS = {}
WEB_AUTH_LOCK = threading.RLock()
STOCK_BUY = 23
STOCK_SELL = 24
FIX_PRICE = 11
ACCOUNT_ACTIONS = {
    "asset": "xttrader.query_stock_asset",
    "positions": "xttrader.query_stock_positions",
    "orders": "xttrader.query_stock_orders",
    "trades": "xttrader.query_stock_trades",
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


def issue_web_auth_token(username):
    token = secrets.token_urlsafe(32)
    with WEB_AUTH_LOCK:
        WEB_AUTH_TOKENS[token] = {
            "username": str(username or ""),
            "created_at": time.time(),
        }
    return token


def web_auth_token_info(token):
    token = str(token or "").strip()
    if not token:
        return None
    with WEB_AUTH_LOCK:
        return dict(WEB_AUTH_TOKENS.get(token) or {}) or None


def revoke_web_auth_token(token):
    token = str(token or "").strip()
    if not token:
        return
    with WEB_AUTH_LOCK:
        WEB_AUTH_TOKENS.pop(token, None)


class WebRuntimeConfig(object):
    def __init__(self, path, settings_db_path=None):
        self.path = path
        self.settings_db_path = settings_db_path or WEB_SETTINGS_DB_FILE
        self._lock = threading.RLock()
        self._data = {
            "bridges": {},
            "account_pairs": {},
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

    def delete_bridge(self, bridge_id):
        bridge_id = normalize_bridge_id(bridge_id)
        if bridge_id in ENV_BRIDGES:
            raise ValueError("environment bridge cannot be deleted from web: %s" % bridge_id)
        with self._lock:
            self._data.setdefault("bridges", {}).pop(bridge_id, None)
            pairs = self._data.setdefault("account_pairs", {})
            for account_id, pair in list(pairs.items()):
                if normalize_bridge_id(pair.get("bridge_id")) == bridge_id:
                    pairs.pop(account_id, None)
            self._save_locked()

    def save_pair(self, account_id, bridge_id):
        account_id = str(account_id or "").strip()
        bridge_id = normalize_bridge_id(bridge_id)
        if not account_id:
            raise ValueError("account_id is required")
        if bridge_id not in self.bridges():
            raise ValueError("unknown bridge_id: %s" % bridge_id)
        row = {
            "account_id": account_id,
            "bridge_id": bridge_id,
            "updated_at": time.time(),
        }
        with self._lock:
            self._data.setdefault("account_pairs", {})[account_id] = row
            self._save_locked()
        return row

    def delete_pair(self, account_id):
        account_id = str(account_id or "").strip()
        with self._lock:
            self._data.setdefault("account_pairs", {}).pop(account_id, None)
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
            items = value.values()
        else:
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            account_id = str(item.get("account_id") or "").strip()
            bridge_id = normalize_bridge_id(item.get("bridge_id"))
            if account_id and bridge_id:
                result[account_id] = {
                    "account_id": account_id,
                    "bridge_id": bridge_id,
                    "updated_at": float(item.get("updated_at") or 0),
                }
        return result


WEB_CONFIG = None


def current_bridges():
    if WEB_CONFIG is not None:
        return WEB_CONFIG.bridges()
    return dict(ENV_BRIDGES)


def bridge_config(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
    bridges = current_bridges()
    if bridge_id not in bridges:
        raise ValueError("unknown bridge_id: %s" % bridge_id)
    return bridges[bridge_id]


def bridge_channels(bridge_id=None):
    return bridge_config(bridge_id)["channels"]


def resolve_bridge_id(account_id=None, bridge_id=None):
    raw_bridge_id = str(bridge_id or "").strip()
    if raw_bridge_id:
        return normalize_bridge_id(raw_bridge_id)
    account_id = str(account_id or "").strip()
    if account_id:
        pair = WEB_CONFIG.account_pairs().get(account_id)
        if pair and pair.get("bridge_id"):
            return normalize_bridge_id(pair.get("bridge_id"))
    return DEFAULT_BRIDGE_ID


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
        self._client = None
        self.client_id = os.environ.get("CFQUANT_WEB_CLIENT_ID") or new_id("cfquant_web")
        self._cooldown_until = {}
        self._last_error = {}

    def start(self):
        self._get_client().start()

    def request(self, bridge_id, channel_key, action, params=None, timeout=8.0, mark_offline_on_timeout=False, ignore_cooldown=False):
        channels = bridge_channels(bridge_id)
        if channel_key not in ("normal", "trade"):
            raise ValueError("unknown channel: %s" % channel_key)
        cooldown_key = (normalize_bridge_id(bridge_id), channel_key)
        if not ignore_cooldown:
            self._check_cooldown(cooldown_key)
        client = self._get_client()
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
            self.close()
            raise

    def close(self):
        with self._lock:
            client = self._client
            self._client = None
        if client is not None:
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
                "bridge %s channel %s is in reconnect cooldown %.1fs: %s"
                % (cooldown_key[0], cooldown_key[1], cooldown_until - now, last_error)
            )

    def _get_client(self):
        with self._lock:
            if self._client is None:
                self._client = LTtxRpcClient(
                    request_channel=CHANNELS["normal"],
                    client_id=self.client_id,
                )
            return self._client

    def _mark_failed(self, cooldown_key, error=None):
        self._cooldown_until[cooldown_key] = time.time() + RECONNECT_COOLDOWN_SECONDS
        if error is not None:
            self._last_error[cooldown_key] = str(error)

    def add_callback(self, event, callback):
        self._get_client().add_callback(event, callback)

    def remove_callback(self, event, callback):
        client = self._client
        if client is not None:
            client.remove_callback(event, callback)


CLIENTS = GlobalTxClient()


class WebSocketCallbackClient(object):
    def __init__(self, sock, bridge_id="", account_id=""):
        self.sock = sock
        self.bridge_id = normalize_bridge_id(bridge_id) if bridge_id else ""
        self.account_id = str(account_id or "").strip()
        self._lock = threading.RLock()
        self.alive = True

    def matches(self, event):
        if self.bridge_id and normalize_bridge_id(event.get("bridge_id") or "default") != self.bridge_id:
            return False
        if self.account_id and CallbackEventStore.event_account_id_static(event) != self.account_id:
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
        bridge_id = normalize_bridge_id(body.get("bridge_id") or DEFAULT_BRIDGE_ID)
        markets = self._normalize_markets(body.get("markets") or body.get("code_list") or ["SH", "SZ"])
        channel = normalize_channel(body.get("channel"), "normal")
        if channel != "normal":
            raise ValueError("subscribe whole quote only supports normal QMT channel")
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
                    return {
                        "subscribe_id": existing_id,
                        "bridge_id": row.get("bridge_id") or bridge_id,
                        "channel": row.get("channel") or "normal",
                        "kind": "whole_quote",
                        "markets": row.get("markets") or markets,
                        "already_subscribed": True,
                        "event_count": row.get("event_count", 0),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
            if existing_id is None:
                self._clear_events_locked(None)
        result = CLIENTS.request(
            bridge_id,
            channel,
            "xtdata.subscribe_whole_quote",
            {"code_list": markets},
            timeout=12.0,
            mark_offline_on_timeout=True,
            ignore_cooldown=True,
        )
        subscribe_id = str(result.get("subscribe_id") if isinstance(result, dict) else result)
        with self._lock:
            self._subscriptions[subscribe_id] = {
                "subscribe_id": subscribe_id,
                "bridge_id": bridge_id,
                "channel": channel,
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
            "kind": "whole_quote",
            "markets": markets,
            "already_subscribed": False,
            "publish_existing": bool(result.get("publish_existing")) if isinstance(result, dict) else False,
            "internal_subscribe_id": result.get("internal_subscribe_id") if isinstance(result, dict) else None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def unsubscribe(self, body):
        subscribe_id = str((body or {}).get("subscribe_id") or "").strip()
        bridge_id = normalize_bridge_id((body or {}).get("bridge_id") or DEFAULT_BRIDGE_ID)
        channel = normalize_channel((body or {}).get("channel"), "normal")
        if not subscribe_id:
            raise ValueError("subscribe_id is required")
        result = self._request_unsubscribe(bridge_id, channel, subscribe_id, timeout=8.0)
        with self._lock:
            self._remove_subscription_locked(subscribe_id)
        return {
            "subscribe_id": subscribe_id,
            "bridge_id": bridge_id,
            "channel": channel,
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
            result = self._request_unsubscribe(bridge_id, channel, subscribe_id, timeout=5.0)
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

    def _request_unsubscribe(self, bridge_id, channel, subscribe_id, timeout=8.0):
        return CLIENTS.request(
            bridge_id,
            channel,
            "xtdata.unsubscribe_quote",
            {"subscribe_id": subscribe_id},
            timeout=timeout,
            ignore_cooldown=True,
        )

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

    def start(self):
        if self._running:
            return
        self._running = True
        try:
            self._tx = txl("127.0.0.1", 2049, "LTtx")
            self._tx.start_txg("@".join(self.channels))
            self._thread = threading.Thread(target=self._loop)
            self._thread.daemon = True
            self._thread.start()
            safe_print("cfquant callback listener started channels=%s" % ",".join(self.channels))
        except Exception as e:
            self._running = False
            safe_print("cfquant callback listener start failed: %s" % e)

    def close(self):
        self._running = False
        tx = self._tx
        self._tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass

    def refresh_channels(self, channels):
        channels = channels or callback_channels()
        if channels == self.channels and self._running:
            return
        self.close()
        self.channels = channels
        self.start()

    def latest(self, since=0, limit=200, bridge_id=None, account_id=None):
        bridge_id = normalize_bridge_id(bridge_id) if bridge_id else None
        account_id = str(account_id or "").strip()
        with self._lock:
            rows = [row for row in self._events if row.get("seq", 0) > since]
            if bridge_id:
                rows = [
                    row
                    for row in rows
                    if normalize_bridge_id(row.get("bridge_id") or "default") == bridge_id
                ]
            if account_id:
                rows = [
                    row
                    for row in rows
                    if self._event_account_id(row) == account_id
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
            row["seq"] = self._seq
            row["received_at"] = time.time()
            self._events.append(row)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]
        WS_CALLBACKS.broadcast(row)

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


CALLBACKS = CallbackEventStore()


def normalize_optional_path(value):
    value = str(value or "").strip().strip('"').strip("'")
    if not value:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))


def safe_print(message):
    line = str(message)
    try:
        print(line)
    except Exception:
        pass
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
        (BASE_DIR, ["*.log"], False),
        (os.path.join(BASE_DIR, "log_data"), ["*.log", "*.csv", "*.txt"], True),
        (os.path.join(BASE_DIR, "tx_log"), ["*.log", "*.csv", "*.txt"], True),
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
            result["errors"].append("桥接端未设置 Python 目录")
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
                result["errors"].append("Python 目录不存在: %s" % target["python_dir"])
            if not os.path.isdir(target["project_dir"]):
                result["errors"].append("项目目录不存在: %s" % target["project_dir"])
            if not os.path.isdir(target["current_core"]):
                result["errors"].append("核心代码目录不存在: %s" % target["current_core"])
            if os.path.isfile(target["entry_file"]):
                result["entry_file"] = target["entry_file"]
            else:
                result["warnings"].append("未找到 CFQUANT.py，常规核心更新仍可继续")
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
            return {
                "bridge_id": target["bridge_id"],
                "python_dir": target["python_dir"],
                "restored_backup": selected,
                "rollback_backup": rollback_backup,
                "removed_backups": removed,
                "current_version": self._read_version(current),
                "backups": self._list_backups(target["backup_dir"]),
            }

    def _target_paths(self, python_dir):
        python_dir = normalize_optional_path(python_dir)
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
            "python_dir": python_dir,
            "project_dir": project_dir,
            "current_core": current_core,
            "updates_dir": updates_dir,
            "backup_dir": os.path.join(updates_dir, "backups"),
            "entry_file": os.path.join(python_dir, "CFQUANT.py"),
        }

    def _require_ready_target(self, bridge_id):
        bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        bridge = bridge_config(bridge_id)
        python_dir = normalize_optional_path(bridge.get("python_dir"))
        if not python_dir:
            raise RuntimeError("桥接端未设置 Python 目录")
        target = self._target_paths(python_dir)
        target["bridge_id"] = bridge_id
        if not os.path.isdir(target["python_dir"]):
            raise RuntimeError("Python 目录不存在: %s" % target["python_dir"])
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
        init_path = os.path.join(core_dir, "__init__.py")
        if not os.path.isfile(init_path):
            return ""
        try:
            with open(init_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(4096)
            match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
            return match.group(1) if match else ""
        except Exception:
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


UPDATER = CfquantUpdater(WEB_CONFIG)


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
    CLIENTS.close()
    try:
        CLIENTS.start()
        return {"ok": True, "reply_channel": CLIENTS.client_id}
    except Exception as e:
        CLIENTS.close()
        safe_print("cfquant web global tx restart failed: %s" % e)
        return {"ok": False, "error": str(e), "reply_channel": CLIENTS.client_id}


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
    stdout = open(LTTX_STDOUT_LOG, "a", encoding="utf-8", buffering=1)
    stderr = open(LTTX_STDERR_LOG, "a", encoding="utf-8", buffering=1)
    try:
        process = subprocess.Popen(
            [sys.executable, entry],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
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
    client = refresh_global_tx_client() if status["running"] else {"ok": False, "error": "LTtx not ready"}
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
    CLIENTS.close()
    return {
        "stopped": True,
        "results": results,
        "status": lttx_status(),
    }


def account_payload(account_id):
    account_id = str(account_id or "").strip()
    if not account_id:
        raise ValueError("account_id is required")
    return {"account": {"account_id": account_id, "account_type": "STOCK"}}


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


def probe_bridge_status(bridge_id=DEFAULT_BRIDGE_ID, timeout=STATUS_PROBE_TIMEOUT_SECONDS):
    result = {}
    channels = bridge_channels(bridge_id)
    for name in ("normal", "trade"):
        result[name] = probe_bridge_channel_status(bridge_id, name, channels[name], timeout=timeout)
    return result


def probe_bridge_channel_status(bridge_id, channel_key, channel, timeout=STATUS_PROBE_TIMEOUT_SECONDS):
    started = time.perf_counter()
    try:
        status = CLIENTS.request(
            bridge_id,
            channel_key,
            "cfquant.status",
            {},
            timeout=timeout,
            mark_offline_on_timeout=True,
            ignore_cooldown=True,
        )
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
            ping = CLIENTS.request(
                bridge_id,
                channel_key,
                "cfquant.ping",
                {},
                timeout=timeout,
                mark_offline_on_timeout=True,
                ignore_cooldown=True,
            )
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
                    snapshot = probe_bridge_status(bridge_id=bridge_id, timeout=self.timeout)
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


def query_account_live(bridge_id, channel, account_id, sections, timeout=ACCOUNT_QUERY_TIMEOUT_SECONDS):
    payload = account_payload(account_id)
    result = {"bridge_id": bridge_id, "account_id": account_id, "channel": channel}
    for section in sections:
        action = ACCOUNT_ACTIONS.get(section)
        if not action:
            result[section] = {"error": "unknown section: %s" % section}
            continue
        started = time.perf_counter()
        try:
            data = CLIENTS.request(
                bridge_id,
                channel,
                action,
                payload,
                timeout=timeout,
                mark_offline_on_timeout=False,
            )
            result[section] = {
                "ok": True,
                "data": data,
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

    def get(self, bridge_id, channel, account_id, sections, force=False):
        bridge_id = normalize_bridge_id(bridge_id)
        sections = [section for section in sections if section in ACCOUNT_ACTIONS]
        if not sections:
            return {"bridge_id": bridge_id, "account_id": account_id, "channel": channel}
        self._subscribe(bridge_id, channel, account_id, sections)
        if force:
            live = query_account_live(bridge_id, channel, account_id, sections)
            self._store_result(bridge_id, channel, account_id, live, sections)
            return self._build_result(bridge_id, channel, account_id, sections, force=True)

        missing = self._missing_sections(bridge_id, channel, account_id, sections)
        if missing:
            self._wake()
            return self._build_result(
                bridge_id,
                channel,
                account_id,
                sections,
                force=False,
                refresh_queued=True,
            )
        elif self._needs_refresh(bridge_id, channel, account_id, sections):
            self._wake()
        return self._build_result(bridge_id, channel, account_id, sections, force=False)

    def _subscribe(self, bridge_id, channel, account_id, sections):
        key = (bridge_id, channel, account_id)
        with self._lock:
            current = self._subscriptions.setdefault(key, set())
            current.update(sections)

    def _missing_sections(self, bridge_id, channel, account_id, sections):
        with self._lock:
            return [
                section
                for section in sections
                if (bridge_id, channel, account_id, section) not in self._entries
            ]

    def _needs_refresh(self, bridge_id, channel, account_id, sections):
        now = time.time()
        with self._lock:
            for section in sections:
                entry = self._entries.get((bridge_id, channel, account_id, section))
                if not entry or now - entry.get("checked_at", 0) >= self.interval:
                    return True
        return False

    def _wake(self):
        self._stop_event.set()

    def _store_result(self, bridge_id, channel, account_id, result, sections):
        now = time.time()
        checked_at_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        with self._lock:
            for section in sections:
                row = result.get(section)
                if row is None:
                    continue
                stored = dict(row)
                stored["checked_at"] = now
                stored["checked_at_text"] = checked_at_text
                self._entries[(bridge_id, channel, account_id, section)] = stored

    def _build_result(self, bridge_id, channel, account_id, sections, force=False, refresh_queued=False):
        now = time.time()
        result = {
            "bridge_id": bridge_id,
            "bridge_name": bridge_config(bridge_id)["name"],
            "account_id": account_id,
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
                entry = self._entries.get((bridge_id, channel, account_id, section))
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
                (bridge_id, channel, account_id, sorted(sections))
                for (bridge_id, channel, account_id), sections in self._subscriptions.items()
                if account_id and sections
            ]
        for bridge_id, channel, account_id, sections in subscriptions:
            if not self._running:
                break
            try:
                live = query_account_live(bridge_id, channel, account_id, sections)
                self._store_result(bridge_id, channel, account_id, live, sections)
            except Exception as e:
                safe_print(
                    "account data cache refresh failed bridge=%s channel=%s account=%s error=%s"
                    % (bridge_id, channel, account_id, e)
                )


ACCOUNT_CACHE = AccountDataCache()


def submit_order(body):
    channel = normalize_channel(body.get("channel"), "trade")
    account_id = str(body.get("account_id") or "").strip()
    bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=body.get("bridge_id"))
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
        "account": {"account_id": account_id, "account_type": "STOCK"},
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
    result = CLIENTS.request(bridge_id, channel, "xttrader.order_stock", params, timeout=12.0)
    return {
        "bridge_id": bridge_id,
        "channel": channel,
        "result": result,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "order_remark": remark,
    }


def submit_batch_orders(body):
    channel = normalize_channel(body.get("channel"), "trade")
    account_id = str(body.get("account_id") or "").strip()
    bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=body.get("bridge_id"))
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
        "account": {"account_id": account_id, "account_type": "STOCK"},
        "orders": orders,
        "stop_on_error": parse_bool(body.get("stop_on_error")),
        "order_remark": body.get("order_remark") or "cfquant_batch_%s" % int(time.time() * 1000),
    }
    started = time.perf_counter()
    result = CLIENTS.request(bridge_id, channel, "xttrader.order_stock_batch", params, timeout=max(12.0, len(orders) * 3.0))
    return {
        "bridge_id": bridge_id,
        "channel": channel,
        "account_id": account_id,
        "result": result,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def cancel_order(body):
    channel = normalize_channel(body.get("channel"), "trade")
    account_id = str(body.get("account_id") or "").strip()
    bridge_id = resolve_bridge_id(account_id=account_id, bridge_id=body.get("bridge_id"))
    bridge_config(bridge_id)
    order_id = str(body.get("order_id") or "").strip()
    confirm_text = str(body.get("confirm_text") or "").strip()
    if not order_id:
        raise ValueError("order_id is required")
    expected = "CANCEL %s" % order_id
    if confirm_text != expected:
        raise ValueError("confirmation mismatch, expected: %s" % expected)
    params = {
        "account": {"account_id": account_id, "account_type": "STOCK"},
        "order_id": order_id,
    }
    started = time.perf_counter()
    result = CLIENTS.request(bridge_id, channel, "xttrader.cancel_order_stock", params, timeout=12.0)
    return {
        "bridge_id": bridge_id,
        "channel": channel,
        "result": result,
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
    row = WEB_CONFIG.save_pair((body or {}).get("account_id"), (body or {}).get("bridge_id"))
    STATUS_MONITOR.wake()
    return {
        "pair": row,
        "account_pairs": WEB_CONFIG.account_pairs(),
    }


def delete_account_pair(body):
    WEB_CONFIG.delete_pair((body or {}).get("account_id"))
    return {
        "account_pairs": WEB_CONFIG.account_pairs(),
    }


def verify_account_pair(body):
    account_id = str((body or {}).get("account_id") or "").strip()
    bridge_id = normalize_bridge_id((body or {}).get("bridge_id") or DEFAULT_BRIDGE_ID)
    channel = normalize_channel((body or {}).get("channel"), "normal")
    if not account_id:
        raise ValueError("account_id is required")
    bridge_config(bridge_id)
    status = STATUS_MONITOR.latest(bridge_id=bridge_id)
    account = ACCOUNT_CACHE.get(
        bridge_id,
        channel,
        account_id,
        ["asset", "positions"],
        force=parse_bool((body or {}).get("force") or "1"),
    )
    return {
        "bridge_id": bridge_id,
        "account_id": account_id,
        "channel": channel,
        "status": status,
        "account": account,
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
    }


def web_auth_login(body):
    body = body or {}
    if not WEB_CONFIG.web_auth_enabled():
        return web_auth_status()
    username = str(body.get("username") or body.get("web_auth_username") or "").strip()
    password = str(body.get("password") or body.get("web_auth_password") or "")
    if not WEB_CONFIG.verify_web_auth(username, password):
        raise PermissionError("invalid username or password")
    token = issue_web_auth_token(username)
    result = web_auth_status(token)
    result["token"] = token
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


def bridge_update_status(bridge_id=None, repo_url=None, ref=None):
    return UPDATER.status(bridge_id or DEFAULT_BRIDGE_ID, repo_url=repo_url, ref=ref)


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


def data_channel_request(body, action, params):
    body = body or {}
    bridge_id = normalize_bridge_id(body.get("bridge_id") or DEFAULT_BRIDGE_ID)
    preferred_channel = normalize_channel(body.get("channel"), "trade")
    timeout = float(body.get("timeout") or 12.0)
    started = time.perf_counter()
    attempts = []
    skipped = []
    if preferred_channel == "trade":
        online = channel_online(bridge_id, "trade")
        if online is False:
            skipped.append({
                "channel": "trade",
                "reason": "trade channel is offline",
            })
            attempts.append("normal")
        else:
            attempts.extend(["trade", "normal"])
    else:
        attempts.append("normal")

    errors = []
    for channel in attempts:
        attempt_started = time.perf_counter()
        try:
            result = CLIENTS.request(
                bridge_id,
                channel,
                action,
                params,
                timeout=timeout,
                mark_offline_on_timeout=True,
            )
            fallback_reason = ""
            if channel != preferred_channel:
                if skipped:
                    fallback_reason = skipped[-1].get("reason", "")
                elif errors:
                    fallback_reason = errors[-1].get("error", "")
            return {
                "bridge_id": bridge_id,
                "preferred_channel": preferred_channel,
                "channel": channel,
                "fallback": channel != preferred_channel,
                "fallback_reason": fallback_reason,
                "action": action,
                "result": result,
                "attempts": skipped + errors + [{
                    "channel": channel,
                    "ok": True,
                    "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 2),
                }],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except Exception as e:
            errors.append({
                "channel": channel,
                "ok": False,
                "error": str(e),
                "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 2),
            })
            if channel == "normal":
                break

    details = "; ".join(
        "%s: %s" % (row.get("channel"), row.get("reason") or row.get("error"))
        for row in (skipped + errors)
    )
    raise RuntimeError("%s failed on data channels: %s" % (action, details or "no channel attempted"))


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
    bridge_id = normalize_bridge_id(body.get("bridge_id") or DEFAULT_BRIDGE_ID)
    channel = normalize_channel(body.get("channel"), "normal")
    started = time.perf_counter()
    QUOTES.start()
    result = CLIENTS.request(
        bridge_id,
        channel,
        "xtdata.subscribe_quote",
        {
            "stock_code": stock_code,
            "period": str(body.get("period") or "1d"),
            "start_time": str(body.get("start_time") or ""),
            "end_time": str(body.get("end_time") or ""),
            "count": int(body.get("count") if str(body.get("count") or "") else 0),
            "dividend_type": str(body.get("dividend_type") or "none"),
        },
        timeout=12.0,
        mark_offline_on_timeout=True,
        ignore_cooldown=True,
    )
    subscribe_id = str(result.get("subscribe_id") if isinstance(result, dict) else result)
    with QUOTES._lock:
        QUOTES._subscriptions[subscribe_id] = {
            "subscribe_id": subscribe_id,
            "bridge_id": bridge_id,
            "channel": channel,
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


def download_history_data(body):
    body = body or {}
    stock_code = str(body.get("stock_code") or "").strip()
    if not stock_code:
        raise ValueError("stock_code is required")
    return data_channel_request(body, "xtdata.download_history_data", {
        "stock_code": stock_code,
        "period": str(body.get("period") or "1d"),
        "start_time": str(body.get("start_time") or ""),
        "end_time": str(body.get("end_time") or ""),
        "incrementally": body.get("incrementally"),
    })


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
    params = {
        "stock_list": financial_stock_list(body),
        "table_list": financial_table_list(body),
        "start_time": str(body.get("start_time") or body.get("start_date") or ""),
        "end_time": str(body.get("end_time") or body.get("end_date") or ""),
    }
    return data_channel_request(body, "xtdata.download_financial_data", params)


class CfquantWebHandler(BaseHTTPRequestHandler):
    server_version = "cfquant-web/0.1"

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
                self._write_json(ok(web_auth_login(body)))
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
            elif parsed.path == "/api/log-cleanup":
                self._write_json(ok(save_log_cleanup_settings(body)))
            elif parsed.path == "/api/log-cleanup/run":
                self._write_json(ok(run_log_cleanup(body)))
            elif parsed.path == "/api/updates/github":
                self._write_json(ok(bridge_update_github(body)))
            elif parsed.path == "/api/updates/rollback":
                self._write_json(ok(bridge_update_rollback(body)))
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
            elif parsed.path == "/api/web-auth/logout":
                self._write_json(ok(web_auth_logout(self._provided_web_token(parsed))))
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
        )
        return str(provided or "").strip()

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
                    }))
                    return
                self._write_json(ok({
                    "default_account_id": DEFAULT_ACCOUNT_ID,
                    "default_bridge_id": DEFAULT_BRIDGE_ID,
                    "bridges": WEB_CONFIG.bridges(),
                    "env_bridges": ENV_BRIDGES,
                    "account_pairs": WEB_CONFIG.account_pairs(),
                    "channels": bridge_channels(DEFAULT_BRIDGE_ID),
                    "reply_channel": CLIENTS.client_id,
                    "api_key": WEB_CONFIG.api_key_info(include_secret=True),
                    "server_access": server_access_info(include_auth_details=True),
                    "web_auth": WEB_CONFIG.web_auth_info(include_username=True),
                    "log_cleanup": log_cleanup_info(),
                }))
            elif parsed.path == "/api/apikey":
                self._write_json(ok(api_key_info()))
            elif parsed.path == "/api/server-access":
                self._write_json(ok(server_access_info()))
            elif parsed.path == "/api/web-auth/status":
                self._write_json(ok(web_auth_status(self._provided_web_token(parsed))))
            elif parsed.path == "/api/log-cleanup":
                self._write_json(ok(log_cleanup_info()))
            elif parsed.path == "/api/updates/status":
                bridge_id = normalize_bridge_id((query.get("bridge_id") or [DEFAULT_BRIDGE_ID])[0])
                repo_url = (query.get("repo_url") or query.get("url") or [""])[0]
                ref = (query.get("ref") or query.get("branch") or query.get("tag") or [""])[0]
                self._write_json(ok(bridge_update_status(bridge_id, repo_url=repo_url, ref=ref)))
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
                bridge_id = normalize_bridge_id((query.get("bridge_id") or [DEFAULT_BRIDGE_ID])[0])
                bridge_config(bridge_id)
                self._write_json(ok(STATUS_MONITOR.latest(bridge_id=bridge_id)))
            elif parsed.path == "/api/callbacks":
                account_id = (query.get("account_id") or [""])[0]
                bridge_id = resolve_bridge_id(
                    account_id=account_id,
                    bridge_id=(query.get("bridge_id") or [""])[0],
                )
                bridge = bridge_config(bridge_id)
                since = int((query.get("since") or ["0"])[0] or 0)
                limit = int((query.get("limit") or ["200"])[0] or 200)
                self._write_json(ok({
                    "bridge_id": bridge_id,
                    "account_id": account_id,
                    "channel": bridge["channels"]["callback"],
                    "events": CALLBACKS.latest(
                        since=since,
                        limit=limit,
                        bridge_id=bridge_id,
                        account_id=account_id,
                    ),
                }))
            elif parsed.path == "/api/account":
                account_id = (query.get("account_id") or [DEFAULT_ACCOUNT_ID])[0]
                bridge_id = resolve_bridge_id(
                    account_id=account_id,
                    bridge_id=(query.get("bridge_id") or [""])[0],
                )
                bridge_config(bridge_id)
                channel = normalize_channel((query.get("channel") or ["normal"])[0], "normal")
                sections = parse_sections((query.get("sections") or [""])[0])
                force = parse_bool((query.get("force") or ["0"])[0])
                self._write_json(ok(ACCOUNT_CACHE.get(bridge_id, channel, account_id, sections, force=force)))
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
        bridge_id = resolve_bridge_id(
            account_id=account_id,
            bridge_id=(query.get("bridge_id") or [""])[0],
        ) if account_id or query.get("bridge_id") else ""
        client = WebSocketCallbackClient(self.request, bridge_id=bridge_id, account_id=account_id)
        WS_CALLBACKS.add(client)
        safe_print(
            "websocket callbacks connected bridge=%s account=%s clients=%s"
            % (bridge_id or "*", account_id or "*", WS_CALLBACKS.count())
        )
        try:
            client.send_json({
                "type": "hello",
                "channel": "callbacks",
                "bridge_id": bridge_id,
                "account_id": account_id,
                "clients": WS_CALLBACKS.count(),
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

    def _write_json(self, payload, status=200):
        raw = json.dumps(to_jsonable(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
        CLIENTS.start()
        safe_print("cfquant web global tx started reply_channel=%s" % CLIENTS.client_id)
    except Exception as e:
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
