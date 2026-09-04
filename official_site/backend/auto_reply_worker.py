#!/usr/bin/env python3
"""Auto reply worker for the cfquant official site.

The worker is intentionally conservative:
- it only replies to content that matches cfquant/QMT/project keywords;
- it skips unrelated or vague content;
- it replies at most once for the same user activity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BOT_USERNAME = "95ge"
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "cfquant_site.sqlite3"

PROJECT_CATEGORIES = {
    "deployment",
    "quote",
    "trade",
    "download",
    "update",
    "api",
}

STRONG_PROJECT_KEYWORDS = {
    "cfquant",
    "qmt",
    "xtquant",
    "xtdata",
    "xttrader",
    "迅投",
    "大qmt",
    "miniqmt",
    "国金",
    "券商",
    "pipe",
    "websocket",
    "winerror",
    "readfile",
    "ctypes",
    "lttx",
    "python",
    "api",
    "github",
    "cfquant_pipe_hub",
    "cfquant_ctype_all_lowlat",
    "cfquant.py",
}

WEAK_PROJECT_KEYWORDS = {
    "本地网站",
    "网站",
    "网页",
    "控制台",
    "部署",
    "安装",
    "更新",
    "下载",
    "版本",
    "日志",
    "报错",
    "错误",
    "模块",
    "启动",
    "重启",
    "桥接",
    "通用端",
    "高级模式",
    "低延迟",
    "行情",
    "订阅",
    "回调",
    "交易",
    "委托",
    "撤单",
    "持仓",
    "成交",
    "资金",
    "账号",
    "账户",
    "权限",
    "超时",
    "timeout",
}

UNRELATED_KEYWORDS = {
    "广告",
    "博彩",
    "彩票",
    "贷款",
    "网贷",
    "返利",
    "兼职",
    "推广",
    "SEO",
    "加群",
    "色情",
}


@dataclass(frozen=True)
class ForumActivity:
    thread_id: int
    thread_title: str
    category_slug: str
    thread_user_id: int | None
    source_id: int
    source_user_id: int | None
    source_parent_id: int | None
    source_body: str
    source_created_at: str
    bot_replied_after_source: bool


@dataclass(frozen=True)
class FeedbackActivity:
    feedback_id: int
    user_id: int | None
    title: str
    body: str
    status: str
    category_slug: str
    reply_count: int
    created_at: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def content_hash(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dict_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def ensure_state_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS auto_reply_state (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          target_type TEXT NOT NULL,
          target_id INTEGER NOT NULL,
          source_id INTEGER NOT NULL DEFAULT 0,
          source_hash TEXT NOT NULL,
          reply_id INTEGER,
          created_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_reply_state_source
        ON auto_reply_state(target_type, target_id, source_hash);
        """
    )


def is_project_related(title: str, body: str, category_slug: str = "") -> bool:
    text = normalize_text(f"{title}\n{body}")
    if not text:
        return False

    has_strong = any(keyword in text for keyword in STRONG_PROJECT_KEYWORDS)
    if has_strong:
        return True

    if any(keyword.lower() in text for keyword in UNRELATED_KEYWORDS):
        return False

    weak_hits = sum(1 for keyword in WEAK_PROJECT_KEYWORDS if keyword in text)
    if category_slug in PROJECT_CATEGORIES and weak_hits >= 1:
        return True
    return weak_hits >= 2


def build_reply(title: str, body: str, category_slug: str = "") -> str | None:
    if not is_project_related(title, body, category_slug):
        return None

    text = normalize_text(f"{title}\n{body}")

    if "no module named" in text or "no mudule named" in text or "没找到" in text and "cfquant" in text:
        return (
            "这是 QMT 没找到 cfquant 包。请确认 QMT 脚本目录旁边有完整的 cfquant 文件夹，"
            "不要只复制单个 .py 文件；复制完成后重启 QMT 再运行脚本。"
        )

    if "websocket callbacks closed" in text or "cannot read from timed out object" in text:
        return (
            "这个一般是网页回调 WebSocket 空闲超时后关闭。只要页面会自动重连、数据还能刷新，"
            "通常不影响行情查询、交易和持仓查询。"
        )

    if "winerror=233" in text or "readfile failed" in text:
        return (
            "winerror=233 表示 Pipe 连接被对端关闭后重新连接，单独出现一般不用紧张。"
            "如果同时有查询超时，先按顺序启动本地网站，再重启 QMT 脚本，并确认没有重复实例。"
        )

    if "pipe request timeout" in text or "timeout" in text or "超时" in text:
        return (
            "这个是网页请求没有及时收到 QMT 端回应。先看右上角通用端是否在线，"
            "再检查 QMT 是否有弹窗、卡住或脚本重复启动；恢复后点一次刷新验证。"
        )

    if "权限" in text or "读取" in text:
        return (
            "这类问题先确认当前券商 QMT 是否开放对应查询权限。可以先跑资金、持仓、成交三个只读查询，"
            "如果都失败，把最近 30 秒 QMT 日志贴出来。"
        )

    if "行情" in text or "订阅" in text or category_slug == "quote":
        return (
            "行情问题先确认 QMT 已登录并且普通桥在线，再重新订阅一次。"
            "如果页面还能刷新，偶发回调断开通常可以先观察。"
        )

    if any(keyword in text for keyword in ("交易", "委托", "撤单", "持仓", "成交", "资金")) or category_slug == "trade":
        return (
            "交易相关先用资金、持仓、成交查询确认通路正常，再测委托/撤单。"
            "如果查询都超时，优先检查 QMT 脚本是否在线和是否重复启动。"
        )

    if any(keyword in text for keyword in ("安装", "部署", "启动", "重启", "桥接", "通用端")):
        return (
            "部署问题建议按顺序排查：先启动本地网站，再启动或重启 QMT 脚本，"
            "最后确认右上角通用端在线。仍异常时贴完整报错和启动日志。"
        )

    if any(keyword in text for keyword in ("更新", "下载", "版本", "github")):
        return (
            "更新问题优先用官网下载页的最新包；GitHub 不稳定时也可以走官网镜像。"
            "更新后记得重启本地网站和 QMT 脚本。"
        )

    return (
        "这个看起来和 cfquant 使用有关。请补充 QMT 版本、券商、运行模式、完整报错和复现步骤，"
        "我们再继续定位。"
    )


def get_bot_user_id(conn: sqlite3.Connection, username: str) -> int:
    row = conn.execute(
        """
        SELECT id
        FROM users
        WHERE username = ? AND role = 'user' AND status = 'active'
        """,
        (username,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"bot user {username!r} not found or inactive")
    return int(row["id"])


def latest_forum_activity(
    conn: sqlite3.Connection,
    thread: sqlite3.Row,
    bot_user_id: int,
) -> ForumActivity | None:
    replies = [
        dict_from_row(row)
        for row in conn.execute(
            """
            SELECT id, user_id, parent_id, body, created_at
            FROM replies
            WHERE thread_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (thread["id"],),
        )
    ]
    clean_replies = [reply for reply in replies if reply is not None]
    bot_reply_times = [
        str(reply["created_at"])
        for reply in clean_replies
        if reply.get("user_id") is not None and int(reply["user_id"]) == bot_user_id
    ]
    user_replies = [
        reply
        for reply in clean_replies
        if reply.get("user_id") is not None and int(reply["user_id"]) != bot_user_id
    ]

    source: dict[str, Any] | None = None
    if user_replies:
        source = user_replies[-1]
    elif thread["user_id"] is not None and int(thread["user_id"]) != bot_user_id:
        source = {
            "id": 0,
            "user_id": int(thread["user_id"]),
            "parent_id": None,
            "body": thread["body"] or "",
            "created_at": thread["created_at"],
        }
    else:
        return None

    source_created_at = str(source["created_at"])
    return ForumActivity(
        thread_id=int(thread["id"]),
        thread_title=str(thread["title"] or ""),
        category_slug=str(thread["category_slug"] or ""),
        thread_user_id=int(thread["user_id"]) if thread["user_id"] is not None else None,
        source_id=int(source["id"] or 0),
        source_user_id=int(source["user_id"]) if source.get("user_id") is not None else None,
        source_parent_id=int(source["parent_id"]) if source.get("parent_id") else None,
        source_body=str(source["body"] or ""),
        source_created_at=source_created_at,
        bot_replied_after_source=any(created_at >= source_created_at for created_at in bot_reply_times),
    )


def state_exists(conn: sqlite3.Connection, target_type: str, target_id: int, source_hash: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM auto_reply_state
        WHERE target_type = ? AND target_id = ? AND source_hash = ?
        """,
        (target_type, target_id, source_hash),
    ).fetchone()
    return row is not None


def save_state(
    conn: sqlite3.Connection,
    target_type: str,
    target_id: int,
    source_id: int,
    source_hash: str,
    reply_id: int | None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO auto_reply_state(
          target_type, target_id, source_id, source_hash, reply_id, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (target_type, target_id, source_id, source_hash, reply_id, now_iso()),
    )


def notify_user(
    conn: sqlite3.Connection,
    user_id: int | None,
    title: str,
    body: str,
    kind: str,
    metadata: dict[str, Any],
) -> None:
    if not user_id:
        return
    conn.execute(
        """
        INSERT INTO notifications(user_id, title, body, kind, created_at, metadata)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (int(user_id), title, body, kind, now_iso(), json.dumps(metadata, ensure_ascii=False)),
    )


def reply_to_forum_activity(
    conn: sqlite3.Connection,
    activity: ForumActivity,
    bot_user_id: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_hash = content_hash(
        "forum",
        activity.thread_id,
        activity.source_id,
        activity.source_created_at,
        activity.thread_title,
        activity.source_body,
    )
    if activity.bot_replied_after_source or state_exists(conn, "forum", activity.thread_id, source_hash):
        return {"target": "forum", "id": activity.thread_id, "action": "skip", "reason": "already_replied"}

    reply_body = build_reply(activity.thread_title, activity.source_body, activity.category_slug)
    if not reply_body:
        save_state(conn, "forum", activity.thread_id, activity.source_id, source_hash, None)
        return {"target": "forum", "id": activity.thread_id, "action": "skip", "reason": "unrelated"}

    parent_id = None
    if activity.source_id:
        parent_id = activity.source_parent_id or activity.source_id

    if dry_run:
        return {
            "target": "forum",
            "id": activity.thread_id,
            "action": "would_reply",
            "parent_id": parent_id,
            "body": reply_body,
        }

    ts = now_iso()
    cur = conn.execute(
        """
        INSERT INTO replies(thread_id, user_id, parent_id, body, created_at)
        VALUES(?, ?, ?, ?, ?)
        """,
        (activity.thread_id, bot_user_id, parent_id, reply_body[:5000], ts),
    )
    reply_id = int(cur.lastrowid)
    conn.execute(
        "UPDATE threads SET updated_at = ?, last_activity_at = ? WHERE id = ?",
        (ts, ts, activity.thread_id),
    )

    notified: set[int] = set()
    if activity.thread_user_id and activity.thread_user_id != bot_user_id:
        notify_user(
            conn,
            activity.thread_user_id,
            "你的帖子有新回复",
            f"《{activity.thread_title}》收到一条新回复。",
            "reply",
            {"thread_id": activity.thread_id, "reply_id": reply_id},
        )
        notified.add(activity.thread_user_id)
    if activity.source_user_id and activity.source_user_id != bot_user_id and activity.source_user_id not in notified:
        notify_user(
            conn,
            activity.source_user_id,
            "你的回复有新评论",
            f"《{activity.thread_title}》中有新的回复。",
            "reply",
            {"thread_id": activity.thread_id, "reply_id": reply_id, "parent_id": parent_id},
        )
    save_state(conn, "forum", activity.thread_id, activity.source_id, source_hash, reply_id)
    return {"target": "forum", "id": activity.thread_id, "action": "replied", "reply_id": reply_id}


def iter_forum_activities(conn: sqlite3.Connection, bot_user_id: int, limit: int) -> list[ForumActivity]:
    threads = conn.execute(
        """
        SELECT t.id, t.user_id, t.title, t.body, t.status, t.created_at,
               c.slug AS category_slug
        FROM threads t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.status = 'open'
        ORDER BY t.last_activity_at DESC, t.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    activities: list[ForumActivity] = []
    for thread in threads:
        activity = latest_forum_activity(conn, thread, bot_user_id)
        if activity is not None:
            activities.append(activity)
    return activities


def iter_feedback_activities(conn: sqlite3.Connection, limit: int) -> list[FeedbackActivity]:
    rows = conn.execute(
        """
        SELECT f.id, f.user_id, f.title, f.body, f.status, f.created_at,
               COUNT(fr.id) AS reply_count
        FROM feedback f
        LEFT JOIN feedback_replies fr ON fr.feedback_id = f.id
        WHERE f.status IN ('open', 'processing')
        GROUP BY f.id
        ORDER BY f.created_at DESC, f.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        FeedbackActivity(
            feedback_id=int(row["id"]),
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
            title=str(row["title"] or ""),
            body=str(row["body"] or ""),
            status=str(row["status"] or "open"),
            category_slug="",
            reply_count=int(row["reply_count"] or 0),
            created_at=str(row["created_at"] or ""),
        )
        for row in rows
    ]


def reply_to_feedback_activity(
    conn: sqlite3.Connection,
    activity: FeedbackActivity,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_hash = content_hash(
        "feedback",
        activity.feedback_id,
        activity.created_at,
        activity.title,
        activity.body,
    )
    if activity.reply_count > 0 or state_exists(conn, "feedback", activity.feedback_id, source_hash):
        return {"target": "feedback", "id": activity.feedback_id, "action": "skip", "reason": "already_replied"}

    reply_body = build_reply(activity.title, activity.body, activity.category_slug)
    if not reply_body:
        save_state(conn, "feedback", activity.feedback_id, 0, source_hash, None)
        return {"target": "feedback", "id": activity.feedback_id, "action": "skip", "reason": "unrelated"}

    if dry_run:
        return {"target": "feedback", "id": activity.feedback_id, "action": "would_reply", "body": reply_body}

    ts = now_iso()
    cur = conn.execute(
        """
        INSERT INTO feedback_replies(feedback_id, author_role, body, created_at)
        VALUES(?, 'admin', ?, ?)
        """,
        (activity.feedback_id, reply_body[:5000], ts),
    )
    reply_id = int(cur.lastrowid)
    next_status = "processing" if activity.status == "open" else activity.status
    conn.execute(
        "UPDATE feedback SET status = ?, updated_at = ? WHERE id = ?",
        (next_status, ts, activity.feedback_id),
    )
    notify_user(
        conn,
        activity.user_id,
        "你的反馈有新的处理回复",
        f"《{activity.title}》收到一条处理回复。",
        "feedback",
        {"feedback_id": activity.feedback_id, "reply_id": reply_id},
    )
    save_state(conn, "feedback", activity.feedback_id, 0, source_hash, reply_id)
    return {"target": "feedback", "id": activity.feedback_id, "action": "replied", "reply_id": reply_id}


def run_once(db_path: Path, bot_username: str, limit: int, dry_run: bool = False) -> list[dict[str, Any]]:
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")

    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_state_table(conn)
        bot_user_id = get_bot_user_id(conn, bot_username)
        results: list[dict[str, Any]] = []

        for activity in iter_forum_activities(conn, bot_user_id, limit):
            results.append(reply_to_forum_activity(conn, activity, bot_user_id, dry_run=dry_run))

        for activity in iter_feedback_activities(conn, limit):
            results.append(reply_to_feedback_activity(conn, activity, dry_run=dry_run))

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        return results
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cfquant official site auto replies once")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--bot-user", default=DEFAULT_BOT_USERNAME, help="forum bot username")
    parser.add_argument("--limit", type=int, default=80, help="max recent records per scan")
    parser.add_argument("--dry-run", action="store_true", help="show actions without writing")
    parser.add_argument("--verbose", action="store_true", help="enable info logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    results = run_once(args.db, args.bot_user, max(args.limit, 1), dry_run=args.dry_run)
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
