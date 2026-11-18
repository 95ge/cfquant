"""Binding-level proxy settings used when starting a QMT process.

The native QMT client owns its remote sockets.  This module therefore keeps
the proxy profile separate from the account binding and exposes a safe,
sanitized representation to the Web UI.  Standard proxy environment
variables are applied to the child process; QMT builds that do not read those
variables must still use their own native proxy settings or a transparent
TUN/WFP adapter.
"""

import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import threading

SUPPORTED_PROXY_TYPES = ("none", "http", "https", "socks5", "ssh")
SUPPORTED_UDP_POLICIES = ("direct", "proxy")
DEFAULT_BYPASS = ("127.0.0.1", "localhost", "::1")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,253}$")
_LOCK = threading.RLock()


def _bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "enable", "enabled"):
        return True
    if text in ("0", "false", "no", "off", "disable", "disabled"):
        return False
    return bool(default)


def _host(value, field="host", required=False):
    value = str(value or "").strip()
    if not value:
        if required:
            raise ValueError("%s is required when proxy is enabled" % field)
        return ""
    if len(value) > 255 or any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError("%s must be a hostname or IP address" % field)
    # Accept IPv4/IPv6 literals and ordinary DNS names.  Brackets are only
    # needed in a URL and are intentionally removed from the stored value.
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if not _HOST_RE.fullmatch(value) or value.startswith(".") or value.endswith("."):
            raise ValueError("%s must be a hostname or IP address" % field)
    return value


def _port(value, field, default=0, required=False):
    if value in (None, ""):
        value = default
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be between 1 and 65535" % field) from None
    if required and not 1 <= value <= 65535:
        raise ValueError("%s must be between 1 and 65535" % field)
    if value and not 1 <= value <= 65535:
        raise ValueError("%s must be between 1 and 65535" % field)
    return value


def _bypass(value):
    if value is None:
        values = list(DEFAULT_BYPASS)
    elif isinstance(value, str):
        values = re.split(r"[,;\n\r\t ]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        raise ValueError("bypass must be a list or a comma-separated string")
    result = []
    seen = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > 255 or any(ord(char) < 33 or ord(char) == 127 for char in text):
            raise ValueError("bypass entries must be hostnames, IPs or CIDR ranges")
        candidate = text[1:] if text.startswith(".") else text
        try:
            ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            # A leading * is accepted for a domain suffix and translated to
            # the NO_PROXY form without the wildcard.
            candidate = candidate[1:] if candidate.startswith("*") else candidate
            if not _HOST_RE.fullmatch(candidate.lstrip(".")):
                raise ValueError("invalid bypass entry: %s" % text)
        key = text.lower()
        if key not in seen:
            seen.add(key)
            result.append(text)
    for item in DEFAULT_BYPASS:
        if item.lower() not in seen:
            result.append(item)
    return result


def normalize_qmt_proxy_settings(value=None, existing=None, strict=False):
    """Normalize a private binding proxy profile.

    Passwords are deliberately not part of the returned object.  Callers can
    persist a supplied password through :class:`QmtProxyCredentialStore`.
    """
    old = dict(existing or {}) if isinstance(existing, dict) else {}
    source = old if value is None else value
    if source is None:
        source = {}
    if not isinstance(source, dict):
        source = {"enabled": source}
    enabled = _bool(source.get("enabled"), _bool(old.get("enabled"), False))
    proxy_type = str(source.get("type", source.get("proxy_type", old.get("type", "none"))) or "none").strip().lower()
    aliases = {"http_proxy": "http", "https_proxy": "https", "socks": "socks5", "socks5h": "socks5", "disabled": "none"}
    proxy_type = aliases.get(proxy_type, proxy_type)
    if proxy_type not in SUPPORTED_PROXY_TYPES:
        raise ValueError("proxy type must be none, http, https, socks5 or ssh")
    if not enabled:
        proxy_type = "none"
    host = _host(source.get("host", source.get("ip", old.get("host", ""))), required=enabled)
    default_port = 22 if proxy_type == "ssh" else 0
    port = _port(source.get("port", old.get("port", default_port)), "port", default=default_port, required=enabled)
    username = str(source.get("username", source.get("user", old.get("username", ""))) or "").strip()
    if len(username) > 256 or any(ord(char) < 32 for char in username):
        raise ValueError("proxy username is invalid")
    bypass = _bypass(source.get("bypass", source.get("no_proxy", old.get("bypass"))))
    udp_policy = str(source.get("udp_policy", old.get("udp_policy", "direct")) or "direct").strip().lower()
    if udp_policy not in SUPPORTED_UDP_POLICIES:
        raise ValueError("udp_policy must be direct or proxy")
    if udp_policy == "proxy" and proxy_type not in ("socks5", "ssh"):
        raise ValueError("HTTP/HTTPS proxies cannot carry native UDP; use direct UDP or SOCKS5")
    ssh_remote_host = _host(source.get("ssh_remote_host", old.get("ssh_remote_host", "")), "ssh_remote_host")
    ssh_remote_port = _port(source.get("ssh_remote_port", old.get("ssh_remote_port", 0)), "ssh_remote_port")
    local_bind_port = _port(source.get("local_bind_port", old.get("local_bind_port", 10800)), "local_bind_port", default=10800)
    password_saved = _bool(source.get("password_saved"), _bool(old.get("password_saved"), False))
    password = source.get("password")
    if password is not None:
        if not isinstance(password, str) or len(password) > 4096:
            raise ValueError("proxy password is invalid")
        if password:
            password_saved = True
    if source.get("clear_password") is True:
        password_saved = False
    return {
        "enabled": bool(enabled),
        "type": proxy_type,
        "host": host,
        "port": port,
        "username": username,
        "password_saved": bool(password_saved),
        "bypass": bypass,
        "udp_policy": udp_policy,
        "ssh_remote_host": ssh_remote_host,
        "ssh_remote_port": ssh_remote_port,
        "local_bind_port": local_bind_port,
    }


def public_qmt_proxy(value=None):
    """Return the UI/API representation without a password or secret."""
    return normalize_qmt_proxy_settings(value)


def qmt_proxy_environment(settings, password=""):
    """Build standard environment variables for a QMT child process.

    NO_PROXY is emitted even when the proxy is disabled so localhost and the
    configured bypass list remain explicit.  Native QMT builds may ignore
    these variables; callers should report that limitation to operators.
    """
    settings = normalize_qmt_proxy_settings(settings)
    bypass = ",".join(settings["bypass"])
    env = {"NO_PROXY": bypass, "no_proxy": bypass}
    if not settings["enabled"] or settings["type"] == "none":
        return env
    host = settings["host"]
    port = settings["port"]
    username = settings.get("username") or ""
    auth = ""
    if username:
        from urllib.parse import quote
        auth = quote(username, safe="") + (":" + quote(password, safe="") if password else "") + "@"
    scheme = "socks5h" if settings["type"] in ("socks5", "ssh") else settings["type"]
    host_for_url = "[%s]" % host if ":" in host and not host.startswith("[") else host
    endpoint = "%s://%s%s:%s" % (scheme, auth, host_for_url, port)
    if settings["type"] == "ssh":
        endpoint = "socks5h://127.0.0.1:%s" % settings["local_bind_port"]
    env.update({"HTTP_PROXY": endpoint, "HTTPS_PROXY": endpoint, "ALL_PROXY": endpoint,
                "http_proxy": endpoint, "https_proxy": endpoint, "all_proxy": endpoint})
    return env


class QmtProxyCredentialStore:
    """DPAPI-protected proxy passwords keyed by the binding account key."""

    def __init__(self, config_path):
        self.path = Path(config_path).with_name("qmt_proxy_credentials.json")

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _entropy(account_key):
        return hashlib.sha256(("cfquant-qmt-proxy:" + str(account_key)).encode("utf-8")).digest()

    def save(self, account_key, password):
        key = str(account_key or "").strip()
        if not key:
            raise ValueError("account_key is required for a proxy password")
        if not isinstance(password, str) or not password or len(password) > 4096:
            raise ValueError("proxy password cannot be empty or exceed 4096 characters")
        # Public proxy settings are also imported by QMT's Python 3.6 bridge.
        # Load the external login/pywin32 runtime only for credential access.
        from .qmt_dependencies import QmtDependencyError, import_login_module

        try:
            encrypted = import_login_module("win32crypt").CryptProtectData(
                password.encode("utf-8"), "CFQuant QMT proxy", self._entropy(key), None, None, 1)
        except QmtDependencyError:
            raise
        except Exception:
            raise RuntimeError("unable to encrypt the proxy password with the current Windows user") from None
        with _LOCK:
            data = self._read()
            data[key] = {"secret": base64.b64encode(encrypted).decode("ascii")}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".%s.tmp" % os.getpid())
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(str(temp), str(self.path))

    def password(self, account_key):
        key = str(account_key or "").strip()
        with _LOCK:
            entry = self._read().get(key, {})
        if not isinstance(entry, dict) or not entry.get("secret"):
            return ""
        from .qmt_dependencies import QmtDependencyError, import_login_module

        try:
            raw = base64.b64decode(entry["secret"])
            return import_login_module("win32crypt").CryptUnprotectData(
                raw, self._entropy(key), None, None, 1)[1].decode("utf-8")
        except QmtDependencyError:
            raise
        except Exception:
            raise RuntimeError("unable to decrypt the proxy password; save it again under this Windows user") from None

    def clear(self, account_key):
        key = str(account_key or "").strip()
        if not key:
            return
        with _LOCK:
            data = self._read()
            if key not in data:
                return
            data.pop(key, None)
            temp = self.path.with_suffix(".%s.tmp" % os.getpid())
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(str(temp), str(self.path))
