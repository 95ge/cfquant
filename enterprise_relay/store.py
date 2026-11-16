"""Persistent state and authentication for the Enterprise Relay Server.

The store deliberately keeps relay payloads opaque. It persists only the
encrypted envelope supplied by a node and the metadata required to route it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple, Union


class RelayError(Exception):
    """An expected API error with an HTTP status code."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> float:
    return time.time()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _password_hash(password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    if not isinstance(password, str) or len(password) < 10 or len(password) > 256:
        raise RelayError("invalid_password", "密码长度必须为 10 到 256 个字符")
    salt = salt or os.urandom(16)
    value = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex(), value.hex()


def _check_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    try:
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected_hex)


def _identifier(value: Any, field: str, maximum: int = 96) -> str:
    value = str(value or "").strip()
    if not value or len(value) > maximum:
        raise RelayError("invalid_input", "%s 无效" % field)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    if any(char not in allowed for char in value):
        raise RelayError("invalid_input", "%s 包含不支持的字符" % field)
    return value


def _text(value: Any, field: str, maximum: int = 160, required: bool = True) -> str:
    value = str(value or "").strip()
    if required and not value:
        raise RelayError("invalid_input", "%s 不能为空" % field)
    if len(value) > maximum:
        raise RelayError("invalid_input", "%s 超出长度限制" % field)
    return value


class RelayStore:
    """SQLite-backed state for one Relay Server instance."""

    SESSION_TTL = 8 * 60 * 60
    PAIRING_TTL = 10 * 60
    NODE_OFFLINE_SECONDS = 60
    MESSAGE_TTL = 120
    MAX_SNAPSHOT_BYTES = 64 * 1024
    MAX_ENVELOPE_BYTES = 1024 * 1024
    MAX_QUEUED_MESSAGES = 10000

    def __init__(self, database: Union[Path, str], *, activation_code: Optional[str] = None,
                 entitlement: Optional[Dict[str, Any]] = None, clock=_now):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.activation_code = activation_code or ""
        self.clock = clock
        self.entitlement_defaults = entitlement or {
            "plan": "enterprise",
            "relay_mode": "self_hosted",
            "features": {"market_forwarding": False, "trade_routing": False},
            "limits": {"max_nodes": 50, "max_market_bps": None},
        }
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database), timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    admin_id INTEGER NOT NULL REFERENCES admins(id),
                    created REAL NOT NULL,
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    created REAL NOT NULL,
                    expires REAL NOT NULL,
                    used REAL
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    version TEXT NOT NULL,
                    capabilities TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created REAL NOT NULL,
                    updated REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    snapshot TEXT NOT NULL,
                    revoked REAL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL REFERENCES nodes(id),
                    target_id TEXT NOT NULL REFERENCES nodes(id),
                    channel TEXT NOT NULL,
                    envelope TEXT NOT NULL,
                    created REAL NOT NULL,
                    expires REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_target ON messages(target_id, expires, created);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_created ON audit(created);
                """
            )
            if self._meta(connection, "entitlement") is None:
                connection.execute(
                    "INSERT INTO meta(key,value) VALUES('entitlement',?)",
                    (_json(self.entitlement_defaults),),
                )
            if self._meta(connection, "activated") is None:
                connection.execute("INSERT INTO meta(key,value) VALUES('activated','0')")

    @staticmethod
    def _meta(connection: sqlite3.Connection, key: str) -> Optional[str]:
        row = connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    def _audit(self, connection: sqlite3.Connection, actor: str, action: str,
               target: str = "", detail: Optional[Dict[str, Any]] = None) -> None:
        connection.execute(
            "INSERT INTO audit(actor,action,target,detail,created) VALUES(?,?,?,?,?)",
            (actor, action, target, _json(detail or {}), self.clock()),
        )

    def activated(self) -> bool:
        with self._connect() as connection:
            return self._meta(connection, "activated") == "1"

    def entitlement(self) -> Dict[str, Any]:
        with self._connect() as connection:
            value = self._meta(connection, "entitlement") or "{}"
        try:
            result = json.loads(value)
        except (TypeError, ValueError):
            result = {}
        return result if isinstance(result, dict) else {}

    def bootstrap(self, activation_code: str, username: str, password: str) -> Dict[str, Any]:
        username = _identifier(username, "username", 80)
        if not self.activation_code or not hmac.compare_digest(str(activation_code or ""), self.activation_code):
            raise RelayError("activation_invalid", "激活码无效或已失效", 403)
        salt, password_hash = _password_hash(password)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._meta(connection, "activated") == "1" or connection.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
                raise RelayError("already_activated", "Relay 服务端已经完成激活", 409)
            cursor = connection.execute(
                "INSERT INTO admins(username,salt,password_hash,role,created) VALUES(?,?,?,?,?)",
                (username, salt, password_hash, "owner", now),
            )
            self._set_meta(connection, "activated", "1")
            self._audit(connection, "bootstrap", "activate", username)
            return {"admin_id": cursor.lastrowid, "username": username, "role": "owner"}

    def login(self, username: str, password: str) -> Dict[str, Any]:
        username = _identifier(username, "username", 80)
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
            if not row or row["disabled"] or not _check_password(password, row["salt"], row["password_hash"]):
                raise RelayError("invalid_credentials", "用户名或密码错误", 401)
            token = "cfrs_" + secrets.token_urlsafe(32)
            now = self.clock()
            connection.execute(
                "INSERT INTO sessions(token_hash,admin_id,created,expires) VALUES(?,?,?,?)",
                (_digest(token), row["id"], now, now + self.SESSION_TTL),
            )
            self._audit(connection, "admin:%s" % row["id"], "login", username)
            return {"access_token": token, "expires_in": self.SESSION_TTL,
                    "admin": {"id": row["id"], "username": username, "role": row["role"]}}

    def logout(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(token),))

    def authenticate_admin(self, token: str) -> Dict[str, Any]:
        if not token:
            raise RelayError("authentication_required", "需要服务端管理员登录", 401)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT a.id,a.username,a.role,a.disabled,s.expires FROM sessions s "
                "JOIN admins a ON a.id=s.admin_id WHERE s.token_hash=?",
                (_digest(token),),
            ).fetchone()
            if not row or row["disabled"] or row["expires"] <= self.clock():
                raise RelayError("authentication_required", "管理员会话已失效", 401)
            return {"id": row["id"], "username": row["username"], "role": row["role"]}

    def create_pairing(self, admin: Dict[str, Any], ttl: int = PAIRING_TTL) -> Dict[str, Any]:
        try:
            ttl = max(60, min(int(ttl), 30 * 60))
        except (TypeError, ValueError):
            ttl = self.PAIRING_TTL
        code = "pair_" + secrets.token_urlsafe(18)
        now = self.clock()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO pairing_codes(code_hash,created,expires) VALUES(?,?,?)",
                (_digest(code), now, now + ttl),
            )
            self._audit(connection, "admin:%s" % admin["id"], "create_pairing", "", {"ttl": ttl})
        return {"pairing_code": code, "expires_in": ttl}

    def claim_node(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        code = _text(payload.get("pairing_code"), "pairing_code", 256)
        node_id = _identifier(payload.get("node_id"), "node_id")
        name = _text(payload.get("name") or node_id, "name", 120)
        public_key = _text(payload.get("public_key"), "public_key", 4096)
        version = _text(payload.get("version") or "unknown", "version", 80)
        capabilities = payload.get("capabilities") or []
        if not isinstance(capabilities, list) or len(capabilities) > 100:
            raise RelayError("invalid_input", "capabilities 无效")
        now = self.clock()
        token = "cfrn_" + secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            pairing = connection.execute(
                "SELECT * FROM pairing_codes WHERE code_hash=? AND used IS NULL", (_digest(code),)
            ).fetchone()
            if not pairing or pairing["expires"] <= now:
                raise RelayError("pairing_invalid", "配对码无效或已过期", 403)
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (node_id,)).fetchone():
                raise RelayError("node_exists", "节点身份已存在，请执行迁移或撤销后重新接入", 409)
            limits = self.entitlement().get("limits")
            limits = limits if isinstance(limits, dict) else {}
            try:
                max_nodes = max(1, int(limits.get("max_nodes", 50)))
            except (TypeError, ValueError):
                max_nodes = 50
            active_nodes = connection.execute("SELECT count(*) FROM nodes WHERE revoked IS NULL").fetchone()[0]
            if active_nodes >= max_nodes:
                raise RelayError("node_limit", "已达到企业授权的节点数量上限", 409)
            snapshot = {"status": "claimed", "capabilities": capabilities}
            connection.execute(
                "INSERT INTO nodes(id,name,public_key,version,capabilities,token_hash,created,updated,last_seen,snapshot) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (node_id, name, public_key, version, _json(capabilities), _digest(token), now, now, now, _json(snapshot)),
            )
            connection.execute("UPDATE pairing_codes SET used=? WHERE code_hash=?", (now, _digest(code)))
            self._audit(connection, "node:%s" % node_id, "claim", node_id, {"version": version})
        return {"node_token": token, "node": self._node_view_from_values(
            node_id, name, version, capabilities, now, snapshot, None, now
        )}

    @staticmethod
    def _node_view_from_values(node_id: str, name: str, version: str, capabilities: List[Any],
                               last_seen: float, snapshot: Dict[str, Any], revoked: Any,
                               now: float) -> Dict[str, Any]:
        return {
            "id": node_id,
            "name": name,
            "version": version,
            "capabilities": capabilities,
            "last_seen": last_seen,
            "status": "revoked" if revoked else "online" if now - last_seen <= RelayStore.NODE_OFFLINE_SECONDS else "offline",
            "snapshot": snapshot,
        }

    def authenticate_node(self, token: str) -> Dict[str, Any]:
        if not token:
            raise RelayError("authentication_required", "需要节点凭据", 401)
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM nodes WHERE token_hash=?", (_digest(token),)).fetchone()
            if not row or row["revoked"]:
                raise RelayError("node_authentication_failed", "节点凭据无效或已撤销", 401)
            return dict(row)

    def heartbeat(self, node: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = payload.get("snapshot") or {}
        if not isinstance(snapshot, dict):
            raise RelayError("invalid_input", "snapshot 必须是对象")
        snapshot_json = _json(snapshot)
        if len(snapshot_json.encode("utf-8")) > self.MAX_SNAPSHOT_BYTES:
            raise RelayError("payload_too_large", "snapshot 超出大小限制", 413)
        version = _text(payload.get("version") or node["version"], "version", 80)
        now = self.clock()
        with self._connect() as connection:
            connection.execute(
                "UPDATE nodes SET version=?,updated=?,last_seen=?,snapshot=? WHERE id=? AND revoked IS NULL",
                (version, now, now, snapshot_json, node["id"]),
            )
            self._audit(connection, "node:%s" % node["id"], "heartbeat", node["id"], {"version": version})
        return {"node_id": node["id"], "server_time": now, "entitlement": self.entitlement()}

    def _require_target(self, connection: sqlite3.Connection, target_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM nodes WHERE id=? AND revoked IS NULL", (target_id,)).fetchone()
        if not row:
            raise RelayError("target_not_found", "目标节点不存在或已撤销", 404)
        if row["last_seen"] <= self.clock() - self.NODE_OFFLINE_SECONDS:
            raise RelayError("target_offline", "目标节点当前离线", 409)
        return row

    def send_message(self, node: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        target_id = _identifier(payload.get("target_node_id"), "target_node_id")
        channel = _identifier(payload.get("channel"), "channel", 32)
        if channel not in ("market", "trade"):
            raise RelayError("invalid_channel", "channel 只能是 market 或 trade")
        entitlement = self.entitlement()
        features = entitlement.get("features") if isinstance(entitlement.get("features"), dict) else {}
        if channel == "market" and (
            entitlement.get("plan") != "enterprise" or not features.get("market_forwarding", False)
        ):
            raise RelayError("feature_not_entitled", "当前 Relay 授权不包含行情转发", 403)
        if channel == "trade" and not features.get("trade_routing", False):
            raise RelayError("feature_not_entitled", "当前 Relay 授权不包含交易路由", 403)
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict) or not isinstance(envelope.get("ciphertext"), str) or not envelope.get("ciphertext"):
            raise RelayError("invalid_envelope", "必须提交包含 ciphertext 的加密消息")
        envelope_json = _json(envelope)
        if len(envelope_json.encode("utf-8")) > self.MAX_ENVELOPE_BYTES:
            raise RelayError("payload_too_large", "加密消息超出大小限制", 413)
        try:
            ttl = max(1, min(int(payload.get("ttl_seconds", 30)), self.MESSAGE_TTL))
        except (TypeError, ValueError):
            ttl = 30
        now = self.clock()
        message_id = "msg_" + secrets.token_urlsafe(18)
        with self._connect() as connection:
            self._require_target(connection, target_id)
            queued = connection.execute(
                "SELECT count(*) FROM messages WHERE expires>?", (now,)
            ).fetchone()[0]
            if queued >= self.MAX_QUEUED_MESSAGES:
                raise RelayError("relay_overloaded", "Relay 消息队列已达到上限", 429)
            connection.execute(
                "INSERT INTO messages(id,sender_id,target_id,channel,envelope,created,expires) VALUES(?,?,?,?,?,?,?)",
                (message_id, node["id"], target_id, channel, envelope_json, now, now + ttl),
            )
            self._audit(connection, "node:%s" % node["id"], "message_send", target_id,
                        {"channel": channel, "message_id": message_id, "bytes": len(envelope_json.encode("utf-8"))})
        return {"message_id": message_id, "queued_at": now, "expires_at": now + ttl}

    def poll_messages(self, node: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            limit = max(1, min(int(payload.get("limit", 50)), 100))
        except (TypeError, ValueError):
            limit = 50
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM messages WHERE expires<=?", (now,))
            rows = connection.execute(
                "SELECT * FROM messages WHERE target_id=? AND expires>? ORDER BY created LIMIT ?",
                (node["id"], now, limit),
            ).fetchall()
            messages = []
            for row in rows:
                try:
                    envelope = json.loads(row["envelope"])
                except (TypeError, ValueError):
                    envelope = {"ciphertext": ""}
                messages.append({
                    "message_id": row["id"], "sender_node_id": row["sender_id"],
                    "channel": row["channel"], "envelope": envelope,
                    "created_at": row["created"], "expires_at": row["expires"],
                })
                connection.execute("DELETE FROM messages WHERE id=?", (row["id"],))
            self._audit(connection, "node:%s" % node["id"], "message_poll", node["id"], {"count": len(messages)})
        return {"messages": messages, "server_time": now}

    def list_nodes(self) -> List[Dict[str, Any]]:
        now = self.clock()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM nodes ORDER BY created").fetchall()
        result = []
        for row in rows:
            try:
                capabilities = json.loads(row["capabilities"])
            except (TypeError, ValueError):
                capabilities = []
            try:
                snapshot = json.loads(row["snapshot"])
            except (TypeError, ValueError):
                snapshot = {}
            result.append(self._node_view_from_values(
                row["id"], row["name"], row["version"], capabilities,
                row["last_seen"], snapshot, row["revoked"], now,
            ))
        return result

    def revoke_node(self, admin: Dict[str, Any], node_id: str) -> None:
        node_id = _identifier(node_id, "node_id")
        now = self.clock()
        with self._connect() as connection:
            cursor = connection.execute("UPDATE nodes SET revoked=? WHERE id=? AND revoked IS NULL", (now, node_id))
            if not cursor.rowcount:
                raise RelayError("node_not_found", "节点不存在或已经撤销", 404)
            self._audit(connection, "admin:%s" % admin["id"], "revoke_node", node_id)

    def status(self) -> Dict[str, Any]:
        now = self.clock()
        with self._connect() as connection:
            total = connection.execute("SELECT count(*) FROM nodes WHERE revoked IS NULL").fetchone()[0]
            online = connection.execute(
                "SELECT count(*) FROM nodes WHERE revoked IS NULL AND last_seen>?", (now - self.NODE_OFFLINE_SECONDS,)
            ).fetchone()[0]
            messages = connection.execute("SELECT count(*) FROM messages WHERE expires>?", (now,)).fetchone()[0]
        entitlement = self.entitlement()
        return {
            "activated": self.activated(),
            "plan": entitlement.get("plan"),
            "relay_mode": entitlement.get("relay_mode"),
            "features": entitlement.get("features", {}),
            "nodes_total": total,
            "nodes_online": online,
            "queued_messages": messages,
            "server_time": now,
        }
