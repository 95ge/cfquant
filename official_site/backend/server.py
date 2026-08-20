#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfquant official site backend.

This server intentionally uses only Python standard-library modules so it can be
started on a clean QMT machine without installing a web framework.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import traceback
import zipfile
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"
PACKAGE_DIR = BASE_DIR / "packages"
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
FEEDBACK_UPLOAD_DIR = UPLOAD_DIR / "feedback"
DB_PATH = DATA_DIR / "cfquant_site.sqlite3"
PROJECT_REPO_URL = os.getenv("CFQUANT_PROJECT_REPO_URL", "https://github.com/95ge/cfquant.git")

ADMIN_USERNAME = os.getenv("CFQUANT_SITE_ADMIN_USER", "root")
ADMIN_PASSWORD = os.getenv("CFQUANT_SITE_ADMIN_PASSWORD", "root123456")

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
TOKEN_TTL_DAYS = 30
PASSWORD_MIN_LENGTH = 6
PASSWORD_HASH_ITERATIONS = 240_000
MAX_FEEDBACK_ATTACHMENTS = 4
MAX_FEEDBACK_ATTACHMENT_BYTES = 3 * 1024 * 1024
ALLOWED_FEEDBACK_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def changelog_from_notes(version: str, notes: str) -> dict[str, Any]:
    text = str(notes or "").strip()
    items = []
    for line in text.splitlines():
        item = re.sub(r"^\s*[-*]\s*", "", line).strip()
        if item:
            items.append(item)
    if not items and text:
        items = [text]
    return {
        "version": str(version or "").strip(),
        "body": text,
        "items": items,
    }


def extract_latest_readme_changelog(readme_text: str) -> dict[str, Any]:
    result = {"version": "", "body": "", "items": []}
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


def read_zip_text(zf: zipfile.ZipFile, candidates: list[str]) -> str:
    names = zf.namelist()
    normalized = {name.replace("\\", "/"): name for name in names}
    for candidate in candidates:
        key = candidate.replace("\\", "/").strip("/")
        if key in normalized:
            return zf.read(normalized[key]).decode("utf-8", errors="replace")
    suffixes = ["/" + item.replace("\\", "/").strip("/") for item in candidates]
    for name in names:
        clean = name.replace("\\", "/")
        if any(clean.endswith(suffix) for suffix in suffixes):
            return zf.read(name).decode("utf-8", errors="replace")
    return ""


def parse_assignment(text: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]", text or "")
    return match.group(1).strip() if match else ""


def inspect_project_package(path: Path) -> dict[str, Any]:
    result = {
        "core_version": "",
        "web_version": "",
        "changelog": {},
    }
    if not path.is_file() or path.suffix.lower() != ".zip":
        return result
    try:
        with zipfile.ZipFile(path, "r") as zf:
            core_text = read_zip_text(zf, ["cfquant/version.py", "cfquant/__init__.py"])
            web_text = read_zip_text(zf, ["cfquant_web_server.py"])
            readme_text = read_zip_text(zf, ["README.md"])
        result["core_version"] = parse_assignment(core_text, "__version__")
        result["web_version"] = parse_assignment(web_text, "WEB_VERSION")
        result["changelog"] = extract_latest_readme_changelog(readme_text)
    except Exception:
        pass
    return result


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_username(value: Any) -> str:
    return str(value or "").strip().lower()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt_hex, digest_hex = str(encoded or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def json_dumps(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def dict_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phone TEXT UNIQUE NOT NULL,
                  username TEXT UNIQUE,
                  email TEXT UNIQUE,
                  display_name TEXT NOT NULL,
                  password_hash TEXT,
                  avatar_color TEXT NOT NULL DEFAULT '#1f6feb',
                  role TEXT NOT NULL DEFAULT 'user',
                  status TEXT NOT NULL DEFAULT 'active',
                  created_at TEXT NOT NULL,
                  last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  role TEXT NOT NULL,
                  token_hash TEXT NOT NULL UNIQUE,
                  expires_at TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS categories (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  slug TEXT NOT NULL UNIQUE,
                  name TEXT NOT NULL,
                  description TEXT NOT NULL DEFAULT '',
                  sort_order INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS threads (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  category_id INTEGER,
                  title TEXT NOT NULL,
                  body TEXT NOT NULL,
                  tags TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'open',
                  views INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  last_activity_at TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
                  FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS replies (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  thread_id INTEGER NOT NULL,
                  user_id INTEGER,
                  body TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS feedback (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  contact TEXT NOT NULL DEFAULT '',
                  title TEXT NOT NULL,
                  body TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'open',
                  is_public INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS feedback_attachments (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  feedback_id INTEGER NOT NULL,
                  file_name TEXT NOT NULL,
                  stored_name TEXT NOT NULL UNIQUE,
                  content_type TEXT NOT NULL,
                  file_size INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(feedback_id) REFERENCES feedback(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notifications (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  title TEXT NOT NULL,
                  body TEXT NOT NULL,
                  kind TEXT NOT NULL DEFAULT 'site',
                  read_at TEXT,
                  created_at TEXT NOT NULL,
                  metadata TEXT NOT NULL DEFAULT '{}',
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS download_packages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT NOT NULL,
                  version TEXT NOT NULL,
                  channel TEXT NOT NULL DEFAULT 'stable',
                  file_name TEXT NOT NULL DEFAULT '',
                  file_path TEXT NOT NULL DEFAULT '',
                  external_url TEXT NOT NULL DEFAULT '',
                  notes TEXT NOT NULL DEFAULT '',
                  is_active INTEGER NOT NULL DEFAULT 1,
                  download_count INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS click_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  path TEXT NOT NULL,
                  event TEXT NOT NULL,
                  target TEXT NOT NULL DEFAULT '',
                  ip TEXT NOT NULL DEFAULT '',
                  user_agent TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_threads_activity ON threads(last_activity_at DESC);
                CREATE INDEX IF NOT EXISTS idx_replies_thread ON replies(thread_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_feedback_attachments_feedback ON feedback_attachments(feedback_id);
                CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_click_events_created ON click_events(created_at DESC);
                """
            )
            self._migrate(conn)
            self._seed(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        user_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "username" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        if "password_hash" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        legacy_users = conn.execute(
            "SELECT id FROM users WHERE username IS NULL OR TRIM(username) = ''"
        ).fetchall()
        for row in legacy_users:
            conn.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (f"cfuser{row['id']}", row["id"]),
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )

        feedback_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(feedback)").fetchall()
        }
        if "is_public" not in feedback_columns:
            conn.execute("ALTER TABLE feedback ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0")

    def _seed(self, conn: sqlite3.Connection) -> None:
        categories = [
            ("deployment", "部署安装", "QMT 配置、启动脚本、更新包安装与环境问题", 10),
            ("quote", "行情订阅", "快照、全推订阅、延迟、行情源与数据质量问题", 20),
            ("trade", "交易接口", "下单、撤单、委托、成交、账号路由与实盘风控", 30),
            ("dev", "外部接入", "Socket、Pipe、Python API、兼容 xtquant 的接入讨论", 40),
        ]
        for slug, name, description, sort_order in categories:
            conn.execute(
                """
                INSERT OR IGNORE INTO categories(slug, name, description, sort_order)
                VALUES(?, ?, ?, ?)
                """,
                (slug, name, description, sort_order),
            )

        thread_count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        if thread_count == 0:
            category_id = conn.execute(
                "SELECT id FROM categories WHERE slug = 'deployment'"
            ).fetchone()[0]
            ts = now_iso()
            conn.execute(
                """
                INSERT INTO threads(
                  user_id, category_id, title, body, tags, status, views,
                  created_at, updated_at, last_activity_at
                )
                VALUES(NULL, ?, ?, ?, ?, 'open', 0, ?, ?, ?)
                """,
                (
                    category_id,
                    "欢迎在这里反馈 cfquant 使用问题",
                    "可以把部署环境、QMT 版本、运行模式、报错日志和复现步骤发到论坛。我们会优先跟踪影响行情订阅、交易请求转发和更新安装的问题。",
                    "公告,反馈",
                    ts,
                    ts,
                    ts,
                ),
            )

        package_count = conn.execute("SELECT COUNT(*) FROM download_packages").fetchone()[0]
        if package_count == 0:
            ts = now_iso()
            conn.execute(
                """
                INSERT INTO download_packages(
                  title, version, channel, file_name, file_path, external_url,
                  notes, is_active, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    "cfquant 更新包镜像位",
                    "latest",
                    "stable",
                    "",
                    "",
                    "https://github.com/95ge/cfquant",
                    "正式上线后可把 zip 更新包放入 official_site/packages，并在后台登记文件名；GitHub 不可访问时用户可从这里下载镜像包。",
                    ts,
                    ts,
                ),
            )


db = Database(DB_PATH)


class SiteHandler(SimpleHTTPRequestHandler):
    server_version = "cfquant-site/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_HEAD(self) -> None:
        self._handle_request("HEAD")

    def do_POST(self) -> None:
        self._handle_request("POST")

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _handle_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path.startswith("/api/"):
                self._dispatch_api(method, path, parsed.query)
                return
            if path != "/downloads/" and path.startswith("/downloads/"):
                self._serve_package_file(path)
                return
            self._serve_frontend(path)
        except ApiError as exc:
            self._send_json({"ok": False, "error": exc.message}, status=exc.status)
        except Exception as exc:  # pragma: no cover - useful during local operation
            traceback.print_exc()
            self._send_json({"ok": False, "error": f"server error: {exc}"}, status=500)

    def _dispatch_api(self, method: str, path: str, query: str) -> None:
        if method == "GET" and path == "/api/health":
            self._send_json({"ok": True, "service": "cfquant official site", "time": now_iso()})
            return
        if method == "GET" and path == "/api/public":
            self._api_public()
            return
        if method == "POST" and path == "/api/track":
            self._api_track()
            return
        if method == "POST" and path == "/api/auth/register":
            self._api_register()
            return
        if method == "POST" and path == "/api/auth/login":
            self._api_login()
            return
        if method == "POST" and path == "/api/auth/password":
            self._api_set_password()
            return
        if method == "POST" and path == "/api/auth/logout":
            self._api_logout()
            return
        if method == "GET" and path == "/api/me":
            self._api_me()
            return
        if method == "GET" and path == "/api/downloads":
            self._api_downloads()
            return
        if method == "GET" and path == "/api/releases/latest":
            self._api_latest_release()
            return
        if method == "GET" and path == "/api/releases/latest/download":
            self._api_download_latest_release()
            return
        match = re.fullmatch(r"/api/downloads/(\d+)/download", path)
        if method == "GET" and match:
            self._api_download_package(int(match.group(1)))
            return
        if method == "GET" and path == "/api/forum/categories":
            self._api_forum_categories()
            return
        if method == "GET" and path == "/api/forum/threads":
            self._api_forum_threads(query)
            return
        if method == "POST" and path == "/api/forum/threads":
            self._api_create_thread()
            return
        match = re.fullmatch(r"/api/forum/threads/(\d+)", path)
        if method == "GET" and match:
            self._api_thread_detail(int(match.group(1)))
            return
        match = re.fullmatch(r"/api/forum/threads/(\d+)/replies", path)
        if method == "POST" and match:
            self._api_create_reply(int(match.group(1)))
            return
        if method == "POST" and path == "/api/feedback":
            self._api_feedback()
            return
        if method == "GET" and path == "/api/feedback/mine":
            self._api_feedback_mine()
            return
        if method == "GET" and path == "/api/feedback/public":
            self._api_feedback_public()
            return
        match = re.fullmatch(r"/api/feedback/attachments/(\d+)", path)
        if method == "GET" and match:
            self._api_feedback_attachment(int(match.group(1)))
            return
        if method == "GET" and path == "/api/notifications":
            self._api_notifications()
            return
        match = re.fullmatch(r"/api/notifications/(\d+)/read", path)
        if method == "POST" and match:
            self._api_notification_read(int(match.group(1)))
            return
        if method == "POST" and path == "/api/notifications/read-all":
            self._api_notifications_read_all()
            return
        if method == "POST" and path == "/api/admin/login":
            self._api_admin_login()
            return
        if method == "GET" and path == "/api/admin/overview":
            self._api_admin_overview()
            return
        if method == "GET" and path == "/api/admin/users":
            self._api_admin_users()
            return
        match = re.fullmatch(r"/api/admin/users/(\d+)/toggle", path)
        if method == "POST" and match:
            self._api_admin_toggle_user(int(match.group(1)))
            return
        if method == "GET" and path == "/api/admin/threads":
            self._api_admin_threads()
            return
        match = re.fullmatch(r"/api/admin/threads/(\d+)/lock", path)
        if method == "POST" and match:
            self._api_admin_lock_thread(int(match.group(1)))
            return
        if method == "GET" and path == "/api/admin/feedback":
            self._api_admin_feedback_list()
            return
        match = re.fullmatch(r"/api/admin/feedback/attachments/(\d+)", path)
        if method == "GET" and match:
            self._api_admin_feedback_attachment(int(match.group(1)))
            return
        match = re.fullmatch(r"/api/admin/feedback/(\d+)/status", path)
        if method == "POST" and match:
            self._api_admin_feedback_status(int(match.group(1)))
            return
        match = re.fullmatch(r"/api/admin/feedback/(\d+)/public", path)
        if method == "POST" and match:
            self._api_admin_feedback_public(int(match.group(1)))
            return
        if method == "GET" and path == "/api/admin/downloads":
            self._api_admin_downloads()
            return
        if method == "POST" and path == "/api/admin/downloads":
            self._api_admin_save_download()
            return
        match = re.fullmatch(r"/api/admin/downloads/(\d+)/toggle", path)
        if method == "POST" and match:
            self._api_admin_toggle_download(int(match.group(1)))
            return
        match = re.fullmatch(r"/api/admin/downloads/(\d+)/delete", path)
        if method == "POST" and match:
            self._api_admin_delete_download(int(match.group(1)))
            return
        if method == "POST" and path == "/api/admin/notifications/broadcast":
            self._api_admin_broadcast()
            return
        raise ApiError(404, "API not found")

    def _parse_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                raise ApiError(400, "invalid JSON body")
            if not isinstance(data, dict):
                raise ApiError(400, "request body must be an object")
            return data
        if "application/x-www-form-urlencoded" in content_type:
            parsed = parse_qs(raw.decode("utf-8"))
            return {key: values[-1] if values else "" for key, values in parsed.items()}
        raise ApiError(415, "unsupported content type")

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json_dumps(data)
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command == "HEAD":
            return
        self.wfile.write(body)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _read_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def _current_session(self, role: str | None = None, required: bool = True) -> dict[str, Any] | None:
        token = self._read_token()
        if not token:
            if required:
                raise ApiError(401, "需要先登录")
            return None
        token_hash = hash_token(token)
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT s.*, u.username, u.phone, u.email, u.display_name,
                       u.status AS user_status, u.role AS user_role
                FROM sessions s
                LEFT JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                if required:
                    raise ApiError(401, "登录已失效")
                return None
            session = dict_from_row(row)
            assert session is not None
            if role and session["role"] != role:
                raise ApiError(403, "权限不足")
            expires_at = datetime.fromisoformat(session["expires_at"])
            if expires_at < datetime.now(timezone.utc):
                conn.execute("DELETE FROM sessions WHERE id = ?", (session["id"],))
                if required:
                    raise ApiError(401, "登录已过期")
                return None
            if session["role"] == "user":
                if session["user_status"] != "active" or session["user_role"] != "user":
                    raise ApiError(403, "账号已被限制")
            conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now_iso(), session["id"]))
            return session

    def _create_session(self, conn: sqlite3.Connection, user_id: int | None, role: str) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS)).isoformat(timespec="seconds")
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO sessions(user_id, role, token_hash, expires_at, created_at, last_seen_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (user_id, role, hash_token(token), expires_at, ts, ts),
        )
        return token

    def _user_payload(self, conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT id, username, phone, email, display_name, avatar_color, status,
                   created_at, last_login_at,
                   CASE WHEN password_hash IS NULL OR password_hash = '' THEN 0 ELSE 1 END AS has_password
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise ApiError(404, "user not found")
        payload = dict_from_row(row)
        assert payload is not None
        unread = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
            (user_id,),
        ).fetchone()[0]
        payload["unread_count"] = unread
        return payload

    def _api_public(self) -> None:
        with db.connect() as conn:
            stats = {
                "users": conn.execute("SELECT COUNT(*) FROM users WHERE role = 'user'").fetchone()[0],
                "threads": conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0],
                "replies": conn.execute("SELECT COUNT(*) FROM replies").fetchone()[0],
                "downloads": conn.execute("SELECT COALESCE(SUM(download_count), 0) FROM download_packages").fetchone()[0],
            }
            hot_threads = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT t.id, t.title, t.views, t.last_activity_at,
                           COALESCE(u.display_name, 'cfquant 官方') AS author_name,
                           c.name AS category_name,
                           COUNT(r.id) AS reply_count
                    FROM threads t
                    LEFT JOIN users u ON u.id = t.user_id
                    LEFT JOIN categories c ON c.id = t.category_id
                    LEFT JOIN replies r ON r.thread_id = t.id
                    GROUP BY t.id
                    ORDER BY t.views DESC, t.last_activity_at DESC
                    LIMIT 5
                    """
                )
            ]
        self._send_json(
            {
                "ok": True,
                "stats": stats,
                "hot_threads": hot_threads,
                "project": {
                    "domain": "cfquant.org",
                    "name": "cfquant",
                    "tagline": "面向大 QMT 的本地交易与行情桥接层",
                },
            }
        )

    def _api_track(self) -> None:
        data = self._parse_json()
        session = self._current_session(required=False)
        user_id = session["user_id"] if session and session["role"] == "user" else None
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO click_events(user_id, path, event, target, ip, user_agent, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    str(data.get("path") or "")[:300],
                    str(data.get("event") or "click")[:80],
                    str(data.get("target") or "")[:200],
                    self.client_address[0] if self.client_address else "",
                    self.headers.get("User-Agent", "")[:300],
                    now_iso(),
                ),
            )
        self._send_json({"ok": True})

    def _api_register(self) -> None:
        data = self._parse_json()
        username = normalize_username(data.get("username"))
        phone = str(data.get("phone") or "").strip()
        email = normalize_email(data.get("email"))
        display_name = str(data.get("display_name") or "").strip()
        password = str(data.get("password") or "")
        if not USERNAME_RE.fullmatch(username):
            raise ApiError(400, "用户名为 3-32 位字母、数字、下划线、点或短横线")
        if not PHONE_RE.fullmatch(phone):
            raise ApiError(400, "请输入有效的 11 位手机号")
        if email and not EMAIL_RE.fullmatch(email):
            raise ApiError(400, "邮箱格式不正确")
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ApiError(400, f"密码至少需要 {PASSWORD_MIN_LENGTH} 位")
        if len(password) > 128:
            raise ApiError(400, "密码不能超过 128 位")
        if not display_name:
            display_name = username
        display_name = display_name[:32]
        colors = ["#1f6feb", "#147d64", "#a15c07", "#7c3aed", "#b42318", "#0f766e"]
        avatar_color = colors[int(phone[-1]) % len(colors)]
        encoded_password = password_hash(password)
        ts = now_iso()
        with db.connect() as conn:
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ApiError(409, "用户名已注册")
            if conn.execute("SELECT 1 FROM users WHERE phone = ?", (phone,)).fetchone():
                raise ApiError(409, "手机号已注册")
            if email and conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise ApiError(409, "邮箱已注册")
            cur = conn.execute(
                """
                INSERT INTO users(username, phone, email, display_name, password_hash, avatar_color, role, status, created_at, last_login_at)
                VALUES(?, ?, ?, ?, ?, ?, 'user', 'active', ?, ?)
                """,
                (username, phone, email or None, display_name, encoded_password, avatar_color, ts, ts),
            )
            user_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO notifications(user_id, title, body, kind, created_at)
                VALUES(?, ?, ?, 'site', ?)
                """,
                (
                    user_id,
                    "欢迎加入 cfquant 社区",
                    "你可以在论坛提问、反馈下载或部署问题，并在用户中心查看回复提醒和站内通知。",
                    ts,
                ),
            )
            token = self._create_session(conn, user_id, "user")
            user = self._user_payload(conn, user_id)
        self._send_json({"ok": True, "token": token, "user": user})

    def _api_login(self) -> None:
        data = self._parse_json()
        account = str(data.get("account") or "").strip()
        password = str(data.get("password") or "")
        if not account:
            raise ApiError(400, "请输入用户名、手机号或邮箱")
        if not password:
            raise ApiError(400, "请输入密码")
        username = normalize_username(account)
        email = normalize_email(account)
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM users
                WHERE role = 'user' AND (username = ? OR phone = ? OR email = ?)
                """,
                (username, account, email),
            ).fetchone()
            if row is None:
                raise ApiError(401, "账号或密码错误")
            if row["status"] != "active":
                raise ApiError(403, "账号已被限制")
            if not row["password_hash"]:
                raise ApiError(403, "该账号尚未设置密码，请使用已有登录会话在用户中心设置密码")
            if not password_matches(password, row["password_hash"]):
                raise ApiError(401, "账号或密码错误")
            ts = now_iso()
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (ts, row["id"]))
            token = self._create_session(conn, int(row["id"]), "user")
            user = self._user_payload(conn, int(row["id"]))
        self._send_json({"ok": True, "token": token, "user": user})

    def _api_set_password(self) -> None:
        session = self._current_session(role="user")
        assert session is not None
        data = self._parse_json()
        password = str(data.get("password") or "")
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ApiError(400, f"密码至少需要 {PASSWORD_MIN_LENGTH} 位")
        if len(password) > 128:
            raise ApiError(400, "密码不能超过 128 位")
        with db.connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash(password), int(session["user_id"])),
            )
            user = self._user_payload(conn, int(session["user_id"]))
        self._send_json({"ok": True, "user": user})

    def _api_logout(self) -> None:
        token = self._read_token()
        if token:
            with db.connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        self._send_json({"ok": True})

    def _api_me(self) -> None:
        session = self._current_session(role="user")
        with db.connect() as conn:
            user = self._user_payload(conn, int(session["user_id"]))
        self._send_json({"ok": True, "user": user})

    def _api_downloads(self) -> None:
        with db.connect() as conn:
            packages = []
            for row in conn.execute(
                    """
                    SELECT id, title, version, channel, file_name, external_url, notes,
                           is_active, download_count, created_at, updated_at
                    FROM download_packages
                    WHERE is_active = 1
                    ORDER BY updated_at DESC, id DESC
                    """
            ):
                item = self._download_package_payload(dict_from_row(row))
                if item:
                    packages.append(item)
        self._send_json({"ok": True, "downloads": packages})

    def _api_latest_release(self) -> None:
        package = self._latest_release_payload()
        if not package:
            raise ApiError(404, "暂未发布项目更新包")
        self._send_json({
            "ok": True,
            "release": package,
            "version": package.get("version") or "",
            "changelog": package.get("changelog") or {},
            "repo_url": PROJECT_REPO_URL,
        })

    def _api_download_latest_release(self) -> None:
        with db.connect() as conn:
            package = self._latest_release_payload(conn)
            if not package:
                raise ApiError(404, "暂未发布项目更新包")
            package_id = int(package["id"])
        self._api_download_package(package_id)

    def _api_download_package(self, package_id: int) -> None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM download_packages WHERE id = ? AND is_active = 1",
                (package_id,),
            ).fetchone()
            if row is None:
                raise ApiError(404, "更新包不存在")
            conn.execute("UPDATE download_packages SET download_count = download_count + 1 WHERE id = ?", (package_id,))
            package = dict_from_row(row)
        assert package is not None
        file_path = self._resolve_package_path(package.get("file_path") or package.get("file_name") or "")
        if file_path and file_path.is_file():
            self._send_file(file_path, download_name=package.get("file_name") or file_path.name)
            return
        external_url = str(package.get("external_url") or "")
        if external_url:
            self.send_response(302)
            self.send_header("Location", external_url)
            self.end_headers()
            return
        raise ApiError(404, "后台尚未配置本地更新包文件")

    def _latest_release_payload(self, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        should_close = conn is None
        conn = conn or db.connect()
        try:
            for row in conn.execute(
            """
            SELECT id, title, version, channel, file_name, file_path, external_url,
                   notes, is_active, download_count, created_at, updated_at
            FROM download_packages
            WHERE is_active = 1
            ORDER BY
              CASE
                WHEN channel = 'project' THEN 0
                WHEN channel = 'stable' THEN 1
                ELSE 2
              END,
              updated_at DESC,
              id DESC
            """
            ):
                payload = self._download_package_payload(dict_from_row(row), include_changelog=True)
                if payload and self._is_release_package(payload):
                    return payload
            return None
        finally:
            if should_close:
                conn.close()

    def _is_release_package(self, package: dict[str, Any]) -> bool:
        if package.get("file_exists"):
            return True
        external_url = str(package.get("external_url") or "").lower()
        return external_url.startswith(("http://", "https://")) and ".zip" in external_url.split("?", 1)[0]

    def _download_package_payload(self, package: dict[str, Any] | None, include_changelog: bool = False) -> dict[str, Any] | None:
        if not package:
            return None
        item = dict(package)
        package_id = int(item.get("id") or 0)
        file_path = self._resolve_package_path(item.get("file_path") or item.get("file_name") or "")
        file_exists = bool(file_path and file_path.is_file())
        item["file_exists"] = file_exists
        item["file_size"] = file_path.stat().st_size if file_exists else 0
        item["sha256"] = file_sha256(file_path) if file_exists else ""
        package_info = inspect_project_package(file_path) if file_exists and file_path else {}
        item["release_version"] = item.get("version") or ""
        item["core_version"] = package_info.get("core_version") or item.get("version") or ""
        item["web_version"] = package_info.get("web_version") or ""
        item["version"] = item["core_version"] or item["release_version"]
        item["download_url"] = self._absolute_url(f"/api/downloads/{package_id}/download") if package_id else ""
        item["latest_download_url"] = self._absolute_url("/api/releases/latest/download")
        item["repo_url"] = PROJECT_REPO_URL
        if include_changelog:
            item["changelog"] = package_info.get("changelog") or changelog_from_notes(item.get("version") or "", item.get("notes") or "")
        return item

    def _absolute_url(self, path: str) -> str:
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "cfquant.org"
        proto = self.headers.get("X-Forwarded-Proto") or ("https" if host == "cfquant.org" else "http")
        return f"{proto}://{host}{path}"

    def _api_forum_categories(self) -> None:
        with db.connect() as conn:
            categories = [
                dict_from_row(row)
                for row in conn.execute(
                    "SELECT id, slug, name, description FROM categories ORDER BY sort_order ASC, id ASC"
                )
            ]
        self._send_json({"ok": True, "categories": categories})

    def _api_forum_threads(self, query: str) -> None:
        params = parse_qs(query)
        category = (params.get("category") or [""])[0]
        keyword = (params.get("q") or [""])[0].strip()
        clauses: list[str] = []
        values: list[Any] = []
        if category:
            clauses.append("c.slug = ?")
            values.append(category)
        if keyword:
            clauses.append("(t.title LIKE ? OR t.body LIKE ? OR t.tags LIKE ?)")
            like = f"%{keyword}%"
            values.extend([like, like, like])
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT t.id, t.title, t.body, t.tags, t.status, t.views,
                   t.created_at, t.updated_at, t.last_activity_at,
                   COALESCE(u.display_name, 'cfquant 官方') AS author_name,
                   u.avatar_color AS author_color,
                   c.name AS category_name,
                   c.slug AS category_slug,
                   COUNT(r.id) AS reply_count
            FROM threads t
            LEFT JOIN users u ON u.id = t.user_id
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN replies r ON r.thread_id = t.id
            {where}
            GROUP BY t.id
            ORDER BY t.last_activity_at DESC
            LIMIT 80
        """
        with db.connect() as conn:
            threads = [dict_from_row(row) for row in conn.execute(sql, values)]
        self._send_json({"ok": True, "threads": threads})

    def _api_create_thread(self) -> None:
        session = self._current_session(role="user")
        data = self._parse_json()
        title = str(data.get("title") or "").strip()
        body = str(data.get("body") or "").strip()
        category_slug = str(data.get("category") or "deployment").strip()
        tags = str(data.get("tags") or "").strip()[:120]
        if len(title) < 6:
            raise ApiError(400, "标题至少 6 个字")
        if len(body) < 10:
            raise ApiError(400, "问题描述至少 10 个字")
        ts = now_iso()
        with db.connect() as conn:
            category = conn.execute("SELECT id FROM categories WHERE slug = ?", (category_slug,)).fetchone()
            if category is None:
                raise ApiError(400, "讨论分类不存在")
            cur = conn.execute(
                """
                INSERT INTO threads(
                  user_id, category_id, title, body, tags, status, views,
                  created_at, updated_at, last_activity_at
                )
                VALUES(?, ?, ?, ?, ?, 'open', 0, ?, ?, ?)
                """,
                (session["user_id"], category["id"], title[:120], body[:5000], tags, ts, ts, ts),
            )
            thread_id = int(cur.lastrowid)
        self._send_json({"ok": True, "thread_id": thread_id}, status=201)

    def _api_thread_detail(self, thread_id: int) -> None:
        with db.connect() as conn:
            conn.execute("UPDATE threads SET views = views + 1 WHERE id = ?", (thread_id,))
            thread = conn.execute(
                """
                SELECT t.*, COALESCE(u.display_name, 'cfquant 官方') AS author_name,
                       u.avatar_color AS author_color,
                       c.name AS category_name, c.slug AS category_slug
                FROM threads t
                LEFT JOIN users u ON u.id = t.user_id
                LEFT JOIN categories c ON c.id = t.category_id
                WHERE t.id = ?
                """,
                (thread_id,),
            ).fetchone()
            if thread is None:
                raise ApiError(404, "帖子不存在")
            replies = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT r.id, r.body, r.created_at,
                           COALESCE(u.display_name, 'cfquant 用户') AS author_name,
                           u.avatar_color AS author_color
                    FROM replies r
                    LEFT JOIN users u ON u.id = r.user_id
                    WHERE r.thread_id = ?
                    ORDER BY r.created_at ASC, r.id ASC
                    """,
                    (thread_id,),
                )
            ]
            payload = dict_from_row(thread)
            assert payload is not None
        self._send_json({"ok": True, "thread": payload, "replies": replies})

    def _api_create_reply(self, thread_id: int) -> None:
        session = self._current_session(role="user")
        data = self._parse_json()
        body = str(data.get("body") or "").strip()
        if len(body) < 2:
            raise ApiError(400, "回复内容不能为空")
        ts = now_iso()
        with db.connect() as conn:
            thread = conn.execute("SELECT id, user_id, title, status FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if thread is None:
                raise ApiError(404, "帖子不存在")
            if thread["status"] == "locked":
                raise ApiError(423, "帖子已锁定")
            cur = conn.execute(
                "INSERT INTO replies(thread_id, user_id, body, created_at) VALUES(?, ?, ?, ?)",
                (thread_id, session["user_id"], body[:5000], ts),
            )
            conn.execute(
                "UPDATE threads SET updated_at = ?, last_activity_at = ? WHERE id = ?",
                (ts, ts, thread_id),
            )
            if thread["user_id"] and int(thread["user_id"]) != int(session["user_id"]):
                conn.execute(
                    """
                    INSERT INTO notifications(user_id, title, body, kind, created_at, metadata)
                    VALUES(?, ?, ?, 'reply', ?, ?)
                    """,
                    (
                        thread["user_id"],
                        "你的帖子有新回复",
                        f"《{thread['title']}》收到一条新回复。",
                        ts,
                        json.dumps({"thread_id": thread_id, "reply_id": int(cur.lastrowid)}, ensure_ascii=False),
                    ),
                )
        self._send_json({"ok": True}, status=201)

    def _api_feedback(self) -> None:
        session = self._current_session(required=False)
        data = self._parse_json()
        title = str(data.get("title") or "").strip()
        body = str(data.get("body") or "").strip()
        contact = str(data.get("contact") or "").strip()
        attachments = data.get("attachments") or []
        user_id = session["user_id"] if session and session["role"] == "user" else None
        if len(title) < 3:
            raise ApiError(400, "反馈标题至少 3 个字")
        if len(body) < 8:
            raise ApiError(400, "请补充问题描述")
        if user_id is None and not contact:
            raise ApiError(400, "未登录反馈请填写联系方式")
        ts = now_iso()
        with db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO feedback(user_id, contact, title, body, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, 'open', ?, ?)
                """,
                (user_id, contact[:120], title[:120], body[:5000], ts, ts),
            )
            feedback_id = int(cur.lastrowid)
            self._save_feedback_attachments(conn, feedback_id, attachments, ts)
        self._send_json({"ok": True}, status=201)

    def _save_feedback_attachments(
        self,
        conn: sqlite3.Connection,
        feedback_id: int,
        attachments: Any,
        ts: str,
    ) -> None:
        if not attachments:
            return
        if not isinstance(attachments, list):
            raise ApiError(400, "截图附件格式不正确")
        if len(attachments) > MAX_FEEDBACK_ATTACHMENTS:
            raise ApiError(400, f"最多上传 {MAX_FEEDBACK_ATTACHMENTS} 张截图")
        FEEDBACK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for item in attachments:
            if not isinstance(item, dict):
                raise ApiError(400, "截图附件格式不正确")
            original_name = Path(str(item.get("name") or "screenshot.png")).name[:120]
            content_type = str(item.get("type") or "").lower().strip()
            if content_type not in ALLOWED_FEEDBACK_IMAGE_TYPES:
                raise ApiError(400, "截图只支持 png、jpg、webp、gif")
            payload = str(item.get("data") or "")
            if "," in payload and payload.startswith("data:"):
                payload = payload.split(",", 1)[1]
            try:
                raw = base64.b64decode(payload, validate=True)
            except (binascii.Error, ValueError):
                raise ApiError(400, "截图数据无法解析")
            if not raw:
                raise ApiError(400, "截图文件为空")
            if len(raw) > MAX_FEEDBACK_ATTACHMENT_BYTES:
                raise ApiError(400, "单张截图不能超过 3MB")
            ext = ALLOWED_FEEDBACK_IMAGE_TYPES[content_type]
            stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(8)}{ext}"
            target = (FEEDBACK_UPLOAD_DIR / stored_name).resolve()
            if FEEDBACK_UPLOAD_DIR.resolve() not in target.parents:
                raise ApiError(400, "截图路径无效")
            target.write_bytes(raw)
            conn.execute(
                """
                INSERT INTO feedback_attachments(
                  feedback_id, file_name, stored_name, content_type, file_size, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (feedback_id, original_name, stored_name, content_type, len(raw), ts),
            )

    def _with_feedback_attachments(
        self,
        conn: sqlite3.Connection,
        feedback: list[dict[str, Any] | None],
        admin: bool = False,
    ) -> list[dict[str, Any]]:
        result = [item for item in feedback if item is not None]
        for item in result:
            item["attachments"] = []
        if not result:
            return result
        feedback_by_id = {int(item["id"]): item for item in result}
        placeholders = ",".join("?" for _ in feedback_by_id)
        prefix = "/api/admin/feedback/attachments" if admin else "/api/feedback/attachments"
        for row in conn.execute(
            f"""
            SELECT id, feedback_id, file_name, content_type, file_size, created_at
            FROM feedback_attachments
            WHERE feedback_id IN ({placeholders})
            ORDER BY id ASC
            """,
            list(feedback_by_id.keys()),
        ):
            attachment = dict_from_row(row)
            assert attachment is not None
            attachment["url"] = f"{prefix}/{attachment['id']}"
            feedback_by_id[int(attachment["feedback_id"])]["attachments"].append(attachment)
        return result

    def _api_feedback_mine(self) -> None:
        session = self._current_session(role="user")
        with db.connect() as conn:
            feedback = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT id, title, body, status, is_public, created_at, updated_at
                    FROM feedback
                    WHERE user_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 100
                    """,
                    (session["user_id"],),
                )
            ]
            feedback = self._with_feedback_attachments(conn, feedback)
        self._send_json({"ok": True, "feedback": feedback})

    def _api_feedback_public(self) -> None:
        with db.connect() as conn:
            feedback = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT f.id, f.title, f.body, f.status, f.is_public,
                           f.created_at, f.updated_at,
                           COALESCE(u.display_name, '匿名用户') AS reporter
                    FROM feedback f
                    LEFT JOIN users u ON u.id = f.user_id
                    WHERE f.is_public = 1
                    ORDER BY f.updated_at DESC, f.id DESC
                    LIMIT 80
                    """
                )
            ]
            feedback = self._with_feedback_attachments(conn, feedback)
        self._send_json({"ok": True, "feedback": feedback})

    def _api_feedback_attachment(self, attachment_id: int) -> None:
        session = self._current_session(required=False)
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT a.stored_name, f.user_id, f.is_public
                FROM feedback_attachments a
                JOIN feedback f ON f.id = a.feedback_id
                WHERE a.id = ?
                """,
                (attachment_id,),
            ).fetchone()
            if row is None:
                raise ApiError(404, "附件不存在")
            can_view = bool(row["is_public"])
            if not can_view and session and session["role"] == "user":
                can_view = row["user_id"] is not None and int(row["user_id"]) == int(session["user_id"])
            if not can_view:
                raise ApiError(403, "附件不可访问")
        target = (FEEDBACK_UPLOAD_DIR / row["stored_name"]).resolve()
        if FEEDBACK_UPLOAD_DIR.resolve() not in target.parents:
            raise ApiError(403, "附件路径无效")
        self._send_file(target)

    def _api_notifications(self) -> None:
        session = self._current_session(role="user")
        with db.connect() as conn:
            rows = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT id, title, body, kind, read_at, created_at, metadata
                    FROM notifications
                    WHERE user_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 80
                    """,
                    (session["user_id"],),
                )
            ]
        self._send_json({"ok": True, "notifications": rows})

    def _api_notification_read(self, notification_id: int) -> None:
        session = self._current_session(role="user")
        with db.connect() as conn:
            conn.execute(
                "UPDATE notifications SET read_at = COALESCE(read_at, ?) WHERE id = ? AND user_id = ?",
                (now_iso(), notification_id, session["user_id"]),
            )
        self._send_json({"ok": True})

    def _api_notifications_read_all(self) -> None:
        session = self._current_session(role="user")
        with db.connect() as conn:
            conn.execute(
                "UPDATE notifications SET read_at = COALESCE(read_at, ?) WHERE user_id = ?",
                (now_iso(), session["user_id"]),
            )
        self._send_json({"ok": True})

    def _api_admin_login(self) -> None:
        data = self._parse_json()
        username = str(data.get("username") or "")
        password = str(data.get("password") or "")
        if not (
            hmac.compare_digest(username, ADMIN_USERNAME)
            and hmac.compare_digest(password, ADMIN_PASSWORD)
        ):
            raise ApiError(401, "管理员账号或密码错误")
        with db.connect() as conn:
            token = self._create_session(conn, None, "admin")
        self._send_json({"ok": True, "token": token, "admin": {"username": ADMIN_USERNAME}})

    def _require_admin(self) -> dict[str, Any]:
        session = self._current_session(role="admin")
        assert session is not None
        return session

    def _api_admin_overview(self) -> None:
        self._require_admin()
        with db.connect() as conn:
            stats = {
                "users": conn.execute("SELECT COUNT(*) FROM users WHERE role = 'user'").fetchone()[0],
                "active_users": conn.execute("SELECT COUNT(*) FROM users WHERE role = 'user' AND status = 'active'").fetchone()[0],
                "threads": conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0],
                "replies": conn.execute("SELECT COUNT(*) FROM replies").fetchone()[0],
                "feedback_open": conn.execute("SELECT COUNT(*) FROM feedback WHERE status = 'open'").fetchone()[0],
                "clicks": conn.execute("SELECT COUNT(*) FROM click_events").fetchone()[0],
                "downloads": conn.execute("SELECT COALESCE(SUM(download_count), 0) FROM download_packages").fetchone()[0],
            }
            top_paths = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT path, event, COUNT(*) AS count
                    FROM click_events
                    GROUP BY path, event
                    ORDER BY count DESC
                    LIMIT 10
                    """
                )
            ]
            recent_users = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT id, username, phone, email, display_name, status, created_at, last_login_at
                    FROM users
                    WHERE role = 'user'
                    ORDER BY created_at DESC
                    LIMIT 8
                    """
                )
            ]
            recent_threads = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT t.id, t.title, t.status, t.views, t.created_at, t.last_activity_at,
                           COALESCE(u.display_name, 'cfquant 官方') AS author_name,
                           c.name AS category_name,
                           COUNT(r.id) AS reply_count
                    FROM threads t
                    LEFT JOIN users u ON u.id = t.user_id
                    LEFT JOIN categories c ON c.id = t.category_id
                    LEFT JOIN replies r ON r.thread_id = t.id
                    GROUP BY t.id
                    ORDER BY t.last_activity_at DESC
                    LIMIT 8
                    """
                )
            ]
            feedback = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT f.id, f.title, f.status, f.created_at,
                           COALESCE(u.display_name, f.contact, '匿名用户') AS reporter
                    FROM feedback f
                    LEFT JOIN users u ON u.id = f.user_id
                    ORDER BY f.created_at DESC
                    LIMIT 8
                    """
                )
            ]
        self._send_json(
            {
                "ok": True,
                "stats": stats,
                "top_paths": top_paths,
                "recent_users": recent_users,
                "recent_threads": recent_threads,
                "feedback": feedback,
            }
        )

    def _api_admin_users(self) -> None:
        self._require_admin()
        with db.connect() as conn:
            users = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT u.id, u.username, u.phone, u.email, u.display_name, u.status, u.created_at,
                           u.last_login_at,
                           COUNT(DISTINCT t.id) AS thread_count,
                           COUNT(DISTINCT r.id) AS reply_count
                    FROM users u
                    LEFT JOIN threads t ON t.user_id = u.id
                    LEFT JOIN replies r ON r.user_id = u.id
                    WHERE u.role = 'user'
                    GROUP BY u.id
                    ORDER BY u.created_at DESC
                    LIMIT 200
                    """
                )
            ]
        self._send_json({"ok": True, "users": users})

    def _api_admin_toggle_user(self, user_id: int) -> None:
        self._require_admin()
        with db.connect() as conn:
            row = conn.execute("SELECT status FROM users WHERE id = ? AND role = 'user'", (user_id,)).fetchone()
            if row is None:
                raise ApiError(404, "用户不存在")
            next_status = "suspended" if row["status"] == "active" else "active"
            conn.execute("UPDATE users SET status = ? WHERE id = ?", (next_status, user_id))
            if next_status == "suspended":
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self._send_json({"ok": True, "status": next_status})

    def _api_admin_threads(self) -> None:
        self._require_admin()
        with db.connect() as conn:
            threads = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT t.id, t.title, t.status, t.views, t.tags, t.created_at, t.last_activity_at,
                           COALESCE(u.display_name, 'cfquant 官方') AS author_name,
                           c.name AS category_name,
                           COUNT(r.id) AS reply_count
                    FROM threads t
                    LEFT JOIN users u ON u.id = t.user_id
                    LEFT JOIN categories c ON c.id = t.category_id
                    LEFT JOIN replies r ON r.thread_id = t.id
                    GROUP BY t.id
                    ORDER BY t.last_activity_at DESC
                    LIMIT 200
                    """
                )
            ]
        self._send_json({"ok": True, "threads": threads})

    def _api_admin_lock_thread(self, thread_id: int) -> None:
        self._require_admin()
        with db.connect() as conn:
            row = conn.execute("SELECT status FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if row is None:
                raise ApiError(404, "帖子不存在")
            next_status = "locked" if row["status"] == "open" else "open"
            conn.execute("UPDATE threads SET status = ?, updated_at = ? WHERE id = ?", (next_status, now_iso(), thread_id))
        self._send_json({"ok": True, "status": next_status})

    def _api_admin_feedback_list(self) -> None:
        self._require_admin()
        with db.connect() as conn:
            feedback = [
                dict_from_row(row)
                for row in conn.execute(
                    """
                    SELECT f.*, COALESCE(u.display_name, '') AS user_name,
                           COALESCE(u.phone, '') AS user_phone,
                           COALESCE(u.email, '') AS user_email
                    FROM feedback f
                    LEFT JOIN users u ON u.id = f.user_id
                    ORDER BY f.created_at DESC
                    LIMIT 200
                    """
                )
            ]
            feedback = self._with_feedback_attachments(conn, feedback, admin=True)
        self._send_json({"ok": True, "feedback": feedback})

    def _api_admin_feedback_attachment(self, attachment_id: int) -> None:
        self._require_admin()
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT stored_name
                FROM feedback_attachments
                WHERE id = ?
                """,
                (attachment_id,),
            ).fetchone()
            if row is None:
                raise ApiError(404, "附件不存在")
        target = (FEEDBACK_UPLOAD_DIR / row["stored_name"]).resolve()
        if FEEDBACK_UPLOAD_DIR.resolve() not in target.parents:
            raise ApiError(403, "附件路径无效")
        self._send_file(target)

    def _api_admin_feedback_status(self, feedback_id: int) -> None:
        self._require_admin()
        data = self._parse_json()
        status = str(data.get("status") or "").strip()
        if status not in {"open", "processing", "closed"}:
            raise ApiError(400, "状态只能是 open/processing/closed")
        with db.connect() as conn:
            cur = conn.execute(
                "UPDATE feedback SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), feedback_id),
            )
            if cur.rowcount == 0:
                raise ApiError(404, "反馈不存在")
        self._send_json({"ok": True, "status": status})

    def _api_admin_feedback_public(self, feedback_id: int) -> None:
        self._require_admin()
        with db.connect() as conn:
            row = conn.execute("SELECT is_public FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
            if row is None:
                raise ApiError(404, "反馈不存在")
            next_public = 0 if int(row["is_public"]) else 1
            conn.execute(
                "UPDATE feedback SET is_public = ?, updated_at = ? WHERE id = ?",
                (next_public, now_iso(), feedback_id),
            )
        self._send_json({"ok": True, "is_public": bool(next_public)})

    def _api_admin_downloads(self) -> None:
        self._require_admin()
        with db.connect() as conn:
            downloads: list[dict[str, Any]] = []
            for row in conn.execute(
                """
                SELECT id, title, version, channel, file_name, file_path,
                       external_url, notes, is_active, download_count,
                       created_at, updated_at
                FROM download_packages
                ORDER BY updated_at DESC, id DESC
                LIMIT 200
                """
            ):
                item = dict_from_row(row)
                assert item is not None
                package_path = self._resolve_package_path(item.get("file_path") or item.get("file_name") or "")
                if package_path and package_path.is_file():
                    item["file_exists"] = True
                    item["file_size"] = package_path.stat().st_size
                else:
                    item["file_exists"] = False
                    item["file_size"] = 0
                downloads.append(item)
        self._send_json({"ok": True, "downloads": downloads})

    def _api_admin_save_download(self) -> None:
        self._require_admin()
        data = self._parse_json()
        title = str(data.get("title") or "").strip()
        version = str(data.get("version") or "").strip()
        channel = str(data.get("channel") or "stable").strip()[:40]
        file_name = Path(str(data.get("file_name") or "").strip()).name
        external_url = str(data.get("external_url") or "").strip()
        notes = str(data.get("notes") or "").strip()
        is_active = 1 if data.get("is_active", True) else 0
        package_id = int(data.get("id") or 0)
        if not title or not version:
            raise ApiError(400, "标题和版本不能为空")
        if file_name:
            file_path = str((PACKAGE_DIR / file_name).resolve())
        else:
            file_path = ""
        ts = now_iso()
        with db.connect() as conn:
            if package_id:
                cur = conn.execute(
                    """
                    UPDATE download_packages
                    SET title = ?, version = ?, channel = ?, file_name = ?, file_path = ?,
                        external_url = ?, notes = ?, is_active = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (title[:120], version[:60], channel, file_name, file_path, external_url, notes[:2000], is_active, ts, package_id),
                )
                if cur.rowcount == 0:
                    raise ApiError(404, "更新包记录不存在")
            else:
                conn.execute(
                    """
                    INSERT INTO download_packages(
                      title, version, channel, file_name, file_path, external_url,
                      notes, is_active, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (title[:120], version[:60], channel, file_name, file_path, external_url, notes[:2000], is_active, ts, ts),
                )
        self._send_json({"ok": True})

    def _api_admin_toggle_download(self, package_id: int) -> None:
        self._require_admin()
        with db.connect() as conn:
            row = conn.execute("SELECT is_active FROM download_packages WHERE id = ?", (package_id,)).fetchone()
            if row is None:
                raise ApiError(404, "更新包记录不存在")
            next_active = 0 if int(row["is_active"]) else 1
            conn.execute(
                "UPDATE download_packages SET is_active = ?, updated_at = ? WHERE id = ?",
                (next_active, now_iso(), package_id),
            )
        self._send_json({"ok": True, "is_active": bool(next_active)})

    def _api_admin_delete_download(self, package_id: int) -> None:
        self._require_admin()
        with db.connect() as conn:
            cur = conn.execute("DELETE FROM download_packages WHERE id = ?", (package_id,))
            if cur.rowcount == 0:
                raise ApiError(404, "更新包记录不存在")
        self._send_json({"ok": True})

    def _api_admin_broadcast(self) -> None:
        self._require_admin()
        data = self._parse_json()
        title = str(data.get("title") or "").strip()
        body = str(data.get("body") or "").strip()
        if len(title) < 2 or len(body) < 2:
            raise ApiError(400, "通知标题和内容不能为空")
        ts = now_iso()
        with db.connect() as conn:
            users = conn.execute("SELECT id FROM users WHERE role = 'user' AND status = 'active'").fetchall()
            conn.executemany(
                """
                INSERT INTO notifications(user_id, title, body, kind, created_at)
                VALUES(?, ?, ?, 'site', ?)
                """,
                [(row["id"], title[:120], body[:1000], ts) for row in users],
            )
        self._send_json({"ok": True, "sent": len(users)})

    def _serve_frontend(self, path: str) -> None:
        if path in {"", "/"}:
            target = FRONTEND_DIR / "index.html"
            self._record_pageview(path)
            self._send_file(target)
            return
        if path in {"/95ge", "/95ge/"}:
            target = FRONTEND_DIR / "admin.html"
            self._record_pageview(path)
            self._send_file(target)
            return
        safe_path = path.lstrip("/").replace("\\", "/")
        if safe_path.startswith("../"):
            raise ApiError(403, "forbidden")
        target = (FRONTEND_DIR / safe_path).resolve()
        if FRONTEND_DIR.resolve() not in target.parents and target != FRONTEND_DIR.resolve():
            raise ApiError(403, "forbidden")
        if target.is_file():
            self._send_file(target)
            return
        if self._is_spa_route(path):
            self._record_pageview(path)
            self._send_file(FRONTEND_DIR / "index.html")
            return
        self._send_response_text("Not found", status=404)

    def _is_spa_route(self, path: str) -> bool:
        clean_path = path.strip("/")
        if not clean_path:
            return True
        if clean_path in {"forum", "downloads", "project", "feedback", "center"}:
            return True
        return bool(re.fullmatch(r"thread-\d+", clean_path))

    def _serve_package_file(self, path: str) -> None:
        file_name = Path(path.removeprefix("/downloads/")).name
        target = self._resolve_package_path(file_name)
        if target and target.is_file():
            self._send_file(target, download_name=file_name)
            return
        self._send_response_text("Package not found", status=404)

    def _resolve_package_path(self, value: str) -> Path | None:
        if not value:
            return None
        candidate = Path(value)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (PACKAGE_DIR / candidate.name).resolve()
        package_root = PACKAGE_DIR.resolve()
        if resolved != package_root and package_root not in resolved.parents:
            return None
        return resolved

    def _send_file(self, target: Path, download_name: str | None = None) -> None:
        if not target.is_file():
            raise ApiError(404, "file not found")
        content_type, _encoding = mimetypes.guess_type(str(target))
        content_type = content_type or "application/octet-stream"
        file_size = target.stat().st_size
        self.send_response(200)
        if target.suffix.lower() in {".html", ".css", ".js", ".svg"}:
            if "charset" not in content_type:
                content_type = f"{content_type}; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_size))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        if self.command == "HEAD":
            return
        with target.open("rb") as file_obj:
            while True:
                chunk = file_obj.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _send_response_text(self, text: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command == "HEAD":
            return
        self.wfile.write(body)

    def _record_pageview(self, path: str) -> None:
        try:
            session = self._current_session(required=False)
            user_id = session["user_id"] if session and session["role"] == "user" else None
            with db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO click_events(user_id, path, event, target, ip, user_agent, created_at)
                    VALUES(?, ?, 'pageview', '', ?, ?, ?)
                    """,
                    (
                        user_id,
                        path or "/",
                        self.client_address[0] if self.client_address else "",
                        self.headers.get("User-Agent", "")[:300],
                        now_iso(),
                    ),
                )
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cfquant official site backend")
    parser.add_argument("--host", default=os.getenv("CFQUANT_SITE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CFQUANT_SITE_PORT", "8780")))
    return parser.parse_args()


def main() -> None:
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    FEEDBACK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    db.initialize()
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), SiteHandler)
    print(f"cfquant official site: http://{args.host}:{args.port}/")
    print(f"admin: http://{args.host}:{args.port}/95ge")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
