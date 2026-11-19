"""Scoped HTTP credentials, durable sliding-window limits and isolated audit.

Secrets are recoverable only by the Windows user that created them (DPAPI).
The web layer supplies its own current account routing and admin authentication.
"""

from contextlib import contextmanager
import hashlib
import json
import math
import re
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from .qmt_credentials import _protect, _unprotect


DEFAULT_LIMITS = {"requests_per_minute": 60, "requests_per_second": 5, "trades_per_minute": 10}
QUERY_GET = frozenset(("/api/health", "/api/config", "/api/account", "/api/order/actions", "/api/credit/actions"))
QUERY_POST = frozenset((
    "/api/data/full-tick", "/api/data/market", "/api/data/market-ex", "/api/data/instrument",
    "/api/data/sector", "/api/data/trading-dates", "/api/data/financial", "/api/credit/query",
))
TRADE_POST = frozenset((
    "/api/order", "/api/order_async", "/api/credit/order", "/api/credit/order_async",
    "/api/future/order", "/api/future/order_async", "/api/future-option/order",
    "/api/future-option/order_async", "/api/stock-option/order", "/api/stock-option/order_async",
    "/api/orders/batch", "/api/credit/orders/batch", "/api/future/orders/batch",
    "/api/future-option/orders/batch", "/api/stock-option/orders/batch", "/api/cancel",
))
ACCOUNT_OPTIONAL = frozenset(("/api/health", "/api/config", "/api/order/actions", "/api/credit/actions"))
# Only business fields are journaled. Never serialize arbitrary request bodies,
# authentication headers, URLs with query strings, credentials or responses.
AUDIT_FIELDS = frozenset(("stock_code", "code_list", "stock_list", "side", "volume", "price",
                          "price_type", "order_id", "order_remark", "order_type", "credit_action",
                          "account_id", "account_key", "account_type", "bridge_id", "name",
                          "permissions", "account_keys", "all_accounts", "enabled", "limits"))


class AccessDenied(Exception):
    def __init__(self, code, message, status=403, retry_after=0):
        super().__init__(message)
        self.code, self.status, self.retry_after = code, status, retry_after


def permission_for(method, path):
    if method == "GET" and path in QUERY_GET or method == "POST" and path in QUERY_POST:
        return "query"
    if method == "POST" and path in TRADE_POST:
        return "trade"
    return ""


def audit_parameters(payload):
    def safe(value):
        if isinstance(value, str):
            return re.sub(r"cfqm_[A-Za-z0-9_-]+", "[REDACTED]", value[:512])
        if value is None or type(value) in (int, float, bool):
            return value
        if isinstance(value, list):
            return [safe(item) for item in value[:100] if not isinstance(item, (dict, list))]
        return "[invalid value]"
    result = {key: safe(payload[key]) for key in AUDIT_FIELDS if key in payload}
    if isinstance(payload.get("limits"), dict):
        result["limits"] = {field: safe(value) for field, value in payload["limits"].items() if field in DEFAULT_LIMITS}
    # A bounded summary of batch children retains trade evidence without secrets.
    if isinstance(payload.get("orders"), list):
        result["order_count"] = len(payload["orders"])
        result["orders"] = [audit_parameters(row) for row in payload["orders"][:100] if isinstance(row, dict)]
    return result


def audit_result(value, depth=0):
    """Keep bounded identifiers/status from scalar or batch responses only."""
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        fields = {"order_id", "order_ids", "order_remark", "asynchronous", "result", "results",
                  "orders", "seq", "status", "error_id", "success", "index", "ok"}
        return {field: audit_result(item, depth+1) for field, item in value.items() if field in fields}
    if isinstance(value, list):
        return [audit_result(item, depth+1) for item in value[:100]]
    if isinstance(value, str):
        return re.sub(r"cfqm_[A-Za-z0-9_-]+", "[REDACTED]", value[:160])
    return value if value is None or type(value) in (int, float, bool) else None


class ApiAccessStore:
    def __init__(self, path, audit_path, clock=time.time, protect=None, unprotect=None):
        self.path, self.audit_path = Path(path), Path(audit_path)
        self.clock = clock
        self.protect, self.unprotect = protect or _protect, unprotect or _unprotect
        self._initialized = False

    @contextmanager
    def _db(self, audit=False):
        path = self.audit_path if audit else self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _init(self):
        if self._initialized:
            return
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT UNIQUE NOT NULL,
                    secret BLOB NOT NULL, prefix TEXT NOT NULL, permissions TEXT NOT NULL,
                    account_keys TEXT NOT NULL, all_accounts INTEGER NOT NULL,
                    limits TEXT NOT NULL, enabled INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, last_used_at REAL);
                CREATE TABLE IF NOT EXISTS rate_events (key_id TEXT NOT NULL, at REAL NOT NULL, weight INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS rate_events_key_at ON rate_events(key_id, at);
            """)
        with self._db(audit=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS api_audit (
                    id TEXT PRIMARY KEY, at REAL NOT NULL, completed_at REAL,
                    key_id TEXT NOT NULL, key_name TEXT NOT NULL, method TEXT NOT NULL,
                    path TEXT NOT NULL, ip TEXT NOT NULL, action TEXT NOT NULL,
                    accounts TEXT NOT NULL, parameters TEXT NOT NULL, status INTEGER,
                    outcome TEXT NOT NULL, code TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS api_audit_key_at ON api_audit(key_id, at);
            """)
        self._initialized = True

    @staticmethod
    def _public(row):
        return {
            "id": row["id"], "name": row["name"], "masked": row["prefix"] + "…",
            "permissions": json.loads(row["permissions"]), "account_keys": json.loads(row["account_keys"]),
            "all_accounts": bool(row["all_accounts"]), "limits": json.loads(row["limits"]),
            "enabled": bool(row["enabled"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"], "last_used_at": row["last_used_at"],
        }

    def list_keys(self):
        self._init()
        with self._db() as db:
            return [self._public(row) for row in db.execute("SELECT * FROM api_keys WHERE deleted=0 ORDER BY created_at DESC")]

    def has_keys(self):
        return bool(self.list_keys())

    def save(self, body, valid_accounts):
        self._init()
        key_id = str(body.get("id") or "")
        with self._db() as db:
            old = db.execute("SELECT * FROM api_keys WHERE id=? AND deleted=0", (key_id,)).fetchone() if key_id else None
        if key_id and old is None:
            raise ValueError("API Key 不存在或已删除")
        previous = self._public(old) if old else {}
        name = str(body.get("name", previous.get("name", ""))).strip()
        if not name or len(name) > 80:
            raise ValueError("Key 名称必填，最长 80 字符")
        permissions = body.get("permissions", previous.get("permissions", ["query"]))
        if not isinstance(permissions, list) or not permissions or any(p not in ("query", "trade") for p in permissions):
            raise ValueError("请选择查询或交易权限")
        accounts = body.get("account_keys", previous.get("account_keys", []))
        all_accounts = body.get("all_accounts", previous.get("all_accounts", False))
        enabled = body.get("enabled", previous.get("enabled", True))
        if type(all_accounts) is not bool or type(enabled) is not bool:
            raise ValueError("启用状态和全部账号必须为布尔值")
        if not isinstance(accounts, list) or any(not isinstance(key, str) for key in accounts):
            raise ValueError("账号范围格式无效")
        if not all_accounts and not accounts:
            raise ValueError("至少选择一个账号，或明确授权全部账号")
        # Existing removed bindings may remain on a disabled key, but cannot be newly granted.
        if any(key not in valid_accounts and key not in previous.get("account_keys", []) for key in accounts):
            raise ValueError("授权账号必须来自已有绑定")
        limits = dict(previous.get("limits", DEFAULT_LIMITS))
        updates = body.get("limits", {})
        if not isinstance(updates, dict) or set(updates) - set(DEFAULT_LIMITS):
            raise ValueError("速率配置无效")
        limits.update(updates)
        for field, value in limits.items():
            if type(value) is not int or not 1 <= value <= 100000:
                raise ValueError("速率限制必须为 1 到 100000 的整数")
        now = self.clock()
        if old:
            with self._db() as db:
                db.execute("""UPDATE api_keys SET name=?,permissions=?,account_keys=?,all_accounts=?,limits=?,enabled=?,updated_at=?
                              WHERE id=? AND deleted=0""",
                           (name, json.dumps(sorted(set(permissions))), json.dumps(sorted(set(accounts))),
                            int(all_accounts), json.dumps(limits), int(enabled), now, key_id))
        else:
            key_id = uuid.uuid4().hex
            token = "cfqm_" + secrets.token_urlsafe(32)
            try:
                encrypted = self.protect(token.encode("utf-8"), key_id.encode("ascii"))
            except Exception:
                raise RuntimeError("无法加密 API Key，请检查当前 Windows 用户的 DPAPI/pywin32 环境") from None
            with self._db() as db:
                db.execute("""INSERT INTO api_keys (id,name,digest,secret,prefix,permissions,account_keys,
                              all_accounts,limits,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (key_id, name, hashlib.sha256(token.encode()).hexdigest(), encrypted, token[:12],
                            json.dumps(sorted(set(permissions))), json.dumps(sorted(set(accounts))), int(all_accounts),
                            json.dumps(limits), int(enabled), now, now))
        return next(row for row in self.list_keys() if row["id"] == key_id)

    def reveal(self, key_id):
        self._init()
        with self._db() as db:
            row = db.execute("SELECT * FROM api_keys WHERE id=? AND deleted=0", (key_id,)).fetchone()
        if row is None:
            raise ValueError("API Key 不存在或已删除")
        try:
            return self.unprotect(row["secret"], row["id"].encode("ascii")).decode("utf-8")
        except Exception:
            raise RuntimeError("无法解密 API Key，请使用创建时的 Windows 用户运行") from None

    def delete(self, key_id):
        self._init()
        with self._db() as db:
            cursor = db.execute("UPDATE api_keys SET deleted=1,enabled=0,secret=X'' WHERE id=? AND deleted=0", (key_id,))
            if not cursor.rowcount:
                raise ValueError("API Key 不存在或已删除")

    def authenticate(self, token):
        self._init()
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._db() as db:
            row = db.execute("SELECT * FROM api_keys WHERE digest=?", (digest,)).fetchone()
        if row is None:
            return None
        result = self._public(row)
        result["deleted"] = bool(row["deleted"])
        return result

    def consume(self, key, action, weight=1):
        if not key["enabled"]:
            raise AccessDenied("key_disabled", "API Key 已停用", 401)
        now, limits = self.clock(), key["limits"]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM rate_events WHERE at<=?", (now - 60,))
            rows = db.execute("SELECT at,weight FROM rate_events WHERE key_id=? ORDER BY at", (key["id"],)).fetchall()
            for period, limit, trade_only in ((1, limits["requests_per_second"], False),
                                               (60, limits["requests_per_minute"], False),
                                               (60, limits["trades_per_minute"], True)):
                relevant = [row for row in rows if row["at"] > now-period and (not trade_only or row["weight"])]
                usage = sum(row["weight"] for row in relevant) if trade_only else len(relevant)
                cost = weight if trade_only else 1
                if trade_only and action != "trade":
                    continue
                if usage + cost > limit:
                    wait = max(1, math.ceil(relevant[0]["at"] + period-now)) if relevant else period
                    raise AccessDenied("rate_limited", "请求过于频繁，请稍后重试", 429, wait)
            db.execute("INSERT INTO rate_events VALUES (?,?,?)", (key["id"], now, weight if action == "trade" else 0))
            db.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now, key["id"]))

    def begin_audit(self, key, method, path, ip, action, accounts=(), payload=None):
        self._init()
        request_id = uuid.uuid4().hex
        parameters = json.dumps(audit_parameters(payload or {}), ensure_ascii=False, default=str)
        with self._db(audit=True) as db:
            db.execute("""INSERT INTO api_audit (id,at,key_id,key_name,method,path,ip,action,accounts,parameters,outcome,code)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (request_id, self.clock(), key.get("id", "unknown"),
                        re.sub(r"cfqm_[A-Za-z0-9_-]+", "[REDACTED]", key.get("name", "无效 Key")[:80]),
                        method, re.sub(r"cfqm_[A-Za-z0-9_-]+", "[REDACTED]", path[:512]), ip, action,
                        json.dumps(list(accounts)), parameters, "pending", ""))
        return request_id

    def finish_audit(self, request_id, status, code="", result=None, business_ok=True):
        outcome = "succeeded" if status < 400 and business_ok else "denied" if status in (401, 403, 429) else "failed"
        with self._db(audit=True) as db:
            db.execute("UPDATE api_audit SET completed_at=?,status=?,outcome=?,code=?,result=? WHERE id=?",
                       (self.clock(), status, outcome, str(code)[:100], json.dumps(result or {}, default=str), request_id))

    def audit(self, key_id="", offset=0, limit=50):
        self._init()
        offset, limit = max(0, int(offset)), min(200, max(1, int(limit)))
        where, args = (" WHERE key_id=?", (key_id,)) if key_id else ("", ())
        with self._db(audit=True) as db:
            total = db.execute("SELECT COUNT(*) FROM api_audit"+where, args).fetchone()[0]
            rows = db.execute("SELECT * FROM api_audit"+where+" ORDER BY at DESC, id DESC LIMIT ? OFFSET ?", args+(limit, offset)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            for field in ("accounts", "parameters", "result"):
                item[field] = json.loads(item[field])
            items.append(item)
        return {"items": items, "total": total, "offset": offset, "limit": limit}
