"""Asynchronous notifications for trading and QMT monitoring events.

The service deliberately owns only delivery and policy.  TradingMonitor keeps
the durable event history; callers submit small structured events here and
never perform SMTP or HTTP work on a QMT callback/status thread.
"""

import copy
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import queue
import smtplib
import ssl
import tempfile
import threading
import time
from .webhook import send_webhook


SHANGHAI = timezone(timedelta(hours=8))
EVENT_TYPES = (
    "order",
    "trade",
    "order_error",
    "cancel_error",
    "qmt_reconnect",
    "qmt_restart",
    "qmt_unresponsive",
    "system_error",
    "heartbeat",
)
EVENT_LABELS = {
    "order": "\u59d4\u6258",
    "trade": "\u6210\u4ea4",
    "order_error": "\u59d4\u6258\u5f02\u5e38",
    "cancel_error": "\u64a4\u5355\u5f02\u5e38",
    "qmt_reconnect": "QMT \u91cd\u8fde",
    "qmt_restart": "QMT \u91cd\u542f",
    "qmt_unresponsive": "QMT \u65e0\u54cd\u5e94",
    "system_error": "\u7cfb\u7edf\u5f02\u5e38",
    "heartbeat": "\u7cfb\u7edf\u5fc3\u8df3",
}
WEBHOOK_TYPES = ("generic", "dingtalk", "wecom", "feishu")
WEEKDAYS = set(range(7))
DEFAULT_HEARTBEAT_SECONDS = 300
MAX_HEARTBEAT_SECONDS = 86400
MAX_WEBHOOKS = 20
MAX_EVENT_TEXT = 4000


def _default_config():
    return {
        "enabled": False,
        "event_types": ["order", "trade", "order_error", "cancel_error", "qmt_reconnect",
                        "qmt_restart", "qmt_unresponsive", "system_error"],
        "dedup_seconds": 300,
        "email": {
            "enabled": False,
            "host": "",
            "port": 465,
            "username": "",
            "password": "",
            "from": "",
            "to": [],
            "use_ssl": True,
            "use_tls": False,
        },
        "webhooks": [],
        "heartbeat": {"enabled": False, "interval_seconds": DEFAULT_HEARTBEAT_SECONDS},
        "schedule": {
            "mode": "always",
            "weekdays": [0, 1, 2, 3, 4],
            "windows": [{"start": "09:00", "end": "15:00"}],
        },
    }


def _text(value, limit=MAX_EVENT_TEXT):
    return str(value or "").strip()[:limit]


def _bool(value, default=False):
    return value if type(value) is bool else default


def _time_text(value, default="00:00"):
    text = str(value or default).strip()
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
    except (TypeError, ValueError):
        raise ValueError("time must be HH:MM")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("time must be HH:MM")
    return "%02d:%02d" % (hour, minute)


def _normalize_windows(value):
    if value is None:
        return [{"start": "09:00", "end": "15:00"}]
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("schedule.windows must be a list")
    result = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("schedule.windows entries must be objects")
        start, end = _time_text(row.get("start"), "00:00"), _time_text(row.get("end"), "23:59")
        if start == end:
            raise ValueError("schedule window cannot be empty")
        result.append({"start": start, "end": end})
    return result


def _normalize_schedule(value):
    value = value if isinstance(value, dict) else {}
    mode = str(value.get("mode") or "always").strip().lower()
    if mode not in ("always", "trading_days", "trading_hours", "custom"):
        raise ValueError("schedule.mode must be always, trading_days, trading_hours or custom")
    weekdays = value.get("weekdays", [0, 1, 2, 3, 4])
    if not isinstance(weekdays, list) or any(type(item) is not int or item not in WEEKDAYS for item in weekdays):
        raise ValueError("schedule.weekdays must contain numbers from 0 to 6")
    return {"mode": mode, "weekdays": sorted(set(weekdays)), "windows": _normalize_windows(value.get("windows"))}


def _normalize_email(value, previous=None):
    value = value if isinstance(value, dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    to = value.get("to", previous.get("to", []))
    if isinstance(to, str):
        to = [item.strip() for item in to.replace(";", ",").split(",") if item.strip()]
    if not isinstance(to, list) or any(not str(item).strip() for item in to):
        raise ValueError("email.to must be a list or comma-separated string")
    password = value.get("password")
    if password in (None, "", "******"):
        password = previous.get("password", "")
    try:
        port = int(value.get("port", previous.get("port", 465)))
    except (TypeError, ValueError):
        raise ValueError("email.port must be an integer")
    if not 1 <= port <= 65535:
        raise ValueError("email.port is out of range")
    return {
        "enabled": _bool(value.get("enabled"), _bool(previous.get("enabled"))),
        "host": _text(value.get("host", previous.get("host", "")), 255),
        "port": port,
        "username": _text(value.get("username", previous.get("username", "")), 255),
        "password": str(password or ""),
        "from": _text(value.get("from", previous.get("from", "")), 255),
        "to": sorted(set(str(item).strip() for item in to)),
        "use_ssl": _bool(value.get("use_ssl"), _bool(previous.get("use_ssl"), True)),
        "use_tls": _bool(value.get("use_tls"), _bool(previous.get("use_tls"))),
    }


def _normalize_webhooks(value, previous=None):
    if value is None:
        return copy.deepcopy(previous or [])
    if not isinstance(value, list) or len(value) > MAX_WEBHOOKS:
        raise ValueError("webhooks must be a list")
    previous_by_id = {str(row.get("id")): row for row in (previous or []) if isinstance(row, dict)}
    result = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError("webhooks entries must be objects")
        item_id = _text(raw.get("id") or "webhook-%d" % (index + 1), 80)
        old = previous_by_id.get(item_id) or {}
        kind = str(raw.get("type") or old.get("type") or "generic").strip().lower()
        if kind not in WEBHOOK_TYPES:
            raise ValueError("webhook.type must be generic, dingtalk, wecom or feishu")
        url = str(raw.get("url") or "").strip()
        if not url:
            url = str(old.get("url") or "").strip()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("webhook.url must start with http:// or https://")
        result.append({
            "id": item_id,
            "name": _text(raw.get("name") or old.get("name") or item_id, 120),
            "type": kind,
            "url": url,
            "enabled": _bool(raw.get("enabled"), _bool(old.get("enabled"), True)),
            "secret": str(raw.get("secret") or old.get("secret") or "").strip(),
        })
    return result


def normalize_config(value, previous=None):
    value = value if isinstance(value, dict) else {}
    previous = previous if isinstance(previous, dict) else _default_config()
    events = value.get("event_types", previous.get("event_types"))
    if not isinstance(events, list):
        raise ValueError("event_types must be a list")
    events = list(dict.fromkeys(str(item).strip().lower() for item in events))
    if any(item not in EVENT_TYPES for item in events):
        raise ValueError("unsupported monitor notification event type")
    try:
        dedup = int(value.get("dedup_seconds", previous.get("dedup_seconds", 300)))
    except (TypeError, ValueError):
        raise ValueError("dedup_seconds must be an integer")
    if not 0 <= dedup <= 86400:
        raise ValueError("dedup_seconds is out of range")
    previous_heartbeat = previous.get("heartbeat") if isinstance(previous.get("heartbeat"), dict) else {}
    heartbeat_raw = value.get("heartbeat") if "heartbeat" in value else previous_heartbeat
    heartbeat_raw = heartbeat_raw if isinstance(heartbeat_raw, dict) else {}
    try:
        heartbeat_interval = int(heartbeat_raw.get("interval_seconds", previous_heartbeat.get("interval_seconds", DEFAULT_HEARTBEAT_SECONDS)))
    except (TypeError, ValueError):
        raise ValueError("heartbeat.interval_seconds must be an integer")
    if not 10 <= heartbeat_interval <= MAX_HEARTBEAT_SECONDS:
        raise ValueError("heartbeat.interval_seconds must be between 10 and 86400")
    heartbeat_enabled = _bool(heartbeat_raw.get("enabled"), _bool(previous_heartbeat.get("enabled")))
    if heartbeat_enabled and "heartbeat" not in events:
        events.append("heartbeat")
    previous_schedule = previous.get("schedule") if isinstance(previous.get("schedule"), dict) else {}
    schedule_raw = value.get("schedule") if "schedule" in value else previous_schedule
    if "schedule" in value and isinstance(value.get("schedule"), dict):
        schedule_raw = dict(previous_schedule, **value["schedule"])
    return {
        "enabled": _bool(value.get("enabled"), _bool(previous.get("enabled"))),
        "event_types": events,
        "dedup_seconds": dedup,
        "email": _normalize_email(value.get("email") if "email" in value else previous.get("email"), previous.get("email")),
        "webhooks": _normalize_webhooks(value.get("webhooks") if "webhooks" in value else None, previous.get("webhooks")),
        "heartbeat": {
            "enabled": heartbeat_enabled,
            "interval_seconds": heartbeat_interval,
        },
        "schedule": _normalize_schedule(schedule_raw),
    }


class MonitorNotificationService:
    def __init__(self, path, heartbeat_provider=None, queue_size=2000):
        self.path = Path(path).resolve()
        self.heartbeat_provider = heartbeat_provider
        self._lock = threading.RLock()
        self._config = _default_config()
        self._queue = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._closed = False
        self._thread = None
        self.last_error = ""
        self.last_sent_at = None
        self.last_event = ""
        self.dropped = 0
        self._dedup = {}
        self._last_heartbeat = 0.0

    def _save_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(self.path.parent),
                                             prefix=".monitor-notify-", suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                json.dump(self._config, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, str(self.path))
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def restore(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            config = normalize_config(raw)
        except FileNotFoundError:
            return self.settings()
        except (ValueError, OSError, TypeError) as error:
            self.last_error = "notification settings invalid: %s" % error
            return self.settings()
        with self._lock:
            self._config = config
        if config["enabled"]:
            self.start()
        return self.settings()

    def configure(self, value):
        if not isinstance(value, dict):
            raise ValueError("notification settings must be an object")
        with self._lock:
            config = normalize_config(value, self._config)
            self._config = config
            self._save_locked()
        if config["enabled"]:
            self.start()
        else:
            self.close()
        return self.settings()

    def settings(self):
        with self._lock:
            result = copy.deepcopy(self._config)
            result["email"]["password_set"] = bool(result["email"].pop("password", ""))
            result["email"]["password"] = "******" if result["email"]["password_set"] else ""
            for webhook in result["webhooks"]:
                url = webhook.pop("url", "")
                secret = webhook.pop("secret", "")
                webhook["url_configured"] = bool(url)
                webhook["url"] = self._mask_url(url)
                webhook["secret_configured"] = bool(secret)
            result["health"] = {
                "enabled": bool(result["enabled"]),
                "running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
                "pending": self._queue.unfinished_tasks,
                "dropped": self.dropped,
                "error": self.last_error,
                "last_sent_at": self.last_sent_at,
                "last_event": self.last_event,
            }
            return result

    def is_enabled(self):
        with self._lock:
            return bool(self._config.get("enabled"))

    @staticmethod
    def _mask_url(url):
        url = str(url or "")
        if not url:
            return ""
        if len(url) <= 20:
            return url[:6] + "..."
        return url[:12] + "..." + url[-8:]

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._closed = False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="cfquant-monitor-notify", daemon=True)
            self._thread.start()

    def close(self):
        with self._lock:
            self._closed = True
            self._stop.set()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(5)

    def _allowed_now(self, timestamp=None):
        timestamp = time.time() if timestamp is None else timestamp
        now = datetime.fromtimestamp(timestamp, SHANGHAI)
        with self._lock:
            schedule = copy.deepcopy(self._config.get("schedule") or {})
        mode = schedule.get("mode", "always")
        if mode == "always":
            return True
        if mode in ("trading_days", "trading_hours"):
            try:
                from .trading_calendar import is_trading_day
                if not is_trading_day(now.date()):
                    return False
            except Exception:
                if now.weekday() >= 5:
                    return False
        elif now.weekday() not in set(schedule.get("weekdays") or []):
            return False
        if mode == "trading_days":
            return True
        windows = schedule.get("windows") or [{"start": "00:00", "end": "23:59"}]
        minute = now.hour * 60 + now.minute
        for row in windows:
            start = sum(int(part) * factor for part, factor in zip(row["start"].split(":"), (60, 1)))
            end = sum(int(part) * factor for part, factor in zip(row["end"].split(":"), (60, 1)))
            if start < end and start <= minute < end:
                return True
            if start > end and (minute >= start or minute < end):
                return True
        return False

    def notify(self, event_type, title="", message="", payload=None, force=False):
        event_type = str(event_type or "").strip().lower()
        if event_type not in EVENT_TYPES:
            return False
        with self._lock:
            if self._closed or not self._config.get("enabled") or (not force and event_type not in self._config.get("event_types", [])):
                return False
            config = copy.deepcopy(self._config)
        if not force and not self._allowed_now():
            return False
        event = {
            "event_type": event_type,
            "title": _text(title or EVENT_LABELS.get(event_type, event_type), 200),
            "message": _text(message, MAX_EVENT_TEXT),
            "payload": payload if isinstance(payload, dict) else {},
            "occurred_at": time.time(),
        }
        fingerprint = hashlib.sha256(json.dumps(
            [event_type, event["title"], event["message"], event["payload"]],
            ensure_ascii=False, sort_keys=True, default=str,
        ).encode("utf-8")).hexdigest()
        dedup_seconds = int(config.get("dedup_seconds") or 0)
        now = time.time()
        with self._lock:
            if not force and dedup_seconds and now - self._dedup.get(fingerprint, 0) < dedup_seconds:
                return False
            self._dedup[fingerprint] = now
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                self.dropped += 1
                return False
        self.start()
        return True

    def record_callback(self, event):
        event_name = str((event or {}).get("event") or "")
        kind = event_name.rsplit(":", 1)[-1]
        if kind not in ("on_stock_order", "on_stock_trade", "on_order_error", "on_cancel_error"):
            return False
        event_type = {
            "on_stock_order": "order",
            "on_stock_trade": "trade",
            "on_order_error": "order_error",
            "on_cancel_error": "cancel_error",
        }[kind]
        data = (event or {}).get("data") if isinstance((event or {}).get("data"), dict) else {}
        account = str((event or {}).get("account_id") or data.get("account_id") or "")
        symbol = str(data.get("stock_code") or data.get("m_strInstrumentID") or "")
        title = EVENT_LABELS.get(event_type, event_type)
        message = "%s account=%s symbol=%s order=%s status=%s" % (
            title, account or "--", symbol or "--", data.get("order_id") or data.get("m_nOrderID") or "--",
            data.get("order_status") or data.get("m_nOrderStatus") or "--",
        )
        return self.notify(event_type, title, message, {"event": event_name, "event_data": data,
                          "account_id": account, "account_type": event.get("account_type", ""),
                          "bridge_id": event.get("bridge_id", "")})

    def record_request(self, bridge, action, params, elapsed_ms, result=None, error=None):
        action = str(action or "")
        if not ("order_" in action or "cancel_" in action):
            return False
        account = params.get("account") if isinstance(params, dict) else ""
        if isinstance(account, dict):
            account = account.get("account_id")
        account = str(account or (params or {}).get("account_id") or "")
        failed = bool(error) or (isinstance(result, dict) and (result.get("ok") is False or result.get("accepted") is False))
        title = "\u64a4\u5355\u8bf7\u6c42" if "cancel_" in action else "\u59d4\u6258\u8bf7\u6c42"
        message = "%s account=%s result=%s latency=%.2fms" % (title, account or "--", "failed" if failed else "accepted", float(elapsed_ms or 0))
        event_type = "cancel_error" if failed and "cancel_" in action else "order_error" if failed else "order"
        return self.notify(event_type, title, message,
                           {"action": action, "bridge_id": bridge, "account_id": account,
                            "failed": failed, "error": str(error or ""), "result": result if isinstance(result, dict) else {}})

    def record_status(self, bridge_id, channel, previous, current, mode=""):
        previous = bool(previous)
        current = bool(current)
        if previous == current:
            return False
        event_type = "qmt_reconnect" if current else "qmt_unresponsive"
        title = EVENT_LABELS[event_type]
        message = "%s bridge=%s mode=%s channel=%s" % (title, bridge_id or "--", mode or "--", channel or "--")
        return self.notify(event_type, title, message, {"bridge_id": bridge_id, "mode": mode, "channel": channel, "online": current})

    def record_qmt_restart(self, account_key="", phase="started", result=None):
        title = EVENT_LABELS["qmt_restart"]
        return self.notify("qmt_restart", title, "%s account=%s" % (phase, account_key or "--"),
                           {"account_key": account_key, "phase": phase, "result": result if isinstance(result, dict) else {}})

    def record_system_error(self, message, payload=None):
        return self.notify("system_error", EVENT_LABELS["system_error"], _text(message), payload or {})

    def test_channel(self, channel_id=""):
        with self._lock:
            config = copy.deepcopy(self._config)
        event = {"event_type": "system_error", "title": "\u901a\u77e5\u6d4b\u8bd5", "message": "cfquant \u76d1\u63a7\u901a\u77e5\u6d4b\u8bd5",
                 "payload": {"test": True}, "occurred_at": time.time()}
        targets = []
        if channel_id in ("", "email"):
            if config["email"].get("enabled"):
                targets.append(("email", config["email"]))
        for webhook in config["webhooks"]:
            if webhook.get("enabled") and (not channel_id or channel_id == webhook.get("id")):
                targets.append(("webhook", webhook))
        if channel_id and not targets:
            raise ValueError("notification channel not found or disabled")
        errors = []
        for kind, target in targets:
            try:
                self._deliver(kind, target, event)
            except Exception as error:
                errors.append(str(error))
        return {"sent": len(targets) - len(errors), "failed": len(errors), "errors": errors}

    def _maybe_heartbeat(self):
        with self._lock:
            heartbeat = copy.deepcopy(self._config.get("heartbeat") or {})
        if not heartbeat.get("enabled") or time.time() - self._last_heartbeat < int(heartbeat.get("interval_seconds") or DEFAULT_HEARTBEAT_SECONDS):
            return
        self._last_heartbeat = time.time()
        payload = self.heartbeat_provider() if callable(self.heartbeat_provider) else {}
        self.notify("heartbeat", EVENT_LABELS["heartbeat"], "cfquant monitor heartbeat", payload)

    def _run(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.5)
            except queue.Empty:
                self._maybe_heartbeat()
                continue
            try:
                with self._lock:
                    config = copy.deepcopy(self._config)
                targets = []
                if config.get("email", {}).get("enabled"):
                    targets.append(("email", config["email"]))
                targets.extend(("webhook", row) for row in config.get("webhooks", []) if row.get("enabled"))
                for kind, target in targets:
                    try:
                        self._deliver(kind, target, event)
                    except Exception as error:
                        self.last_error = "%s: %s" % (kind, error)
                self.last_event = event.get("event_type", "")
                self.last_sent_at = time.time()
            finally:
                self._queue.task_done()
            self._maybe_heartbeat()

    @staticmethod
    def _format_text(event):
        stamp = datetime.fromtimestamp(event["occurred_at"], SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
        body = event.get("message") or ""
        payload = event.get("payload") or {}
        if payload:
            body += "\n" + json.dumps(payload, ensure_ascii=False, default=str)[:2500]
        return "[%s] %s\n%s" % (stamp, event.get("title") or "cfquant", body)

    def _deliver(self, kind, target, event):
        if kind == "email":
            self._send_email(target, event)
        else:
            self._send_webhook(target, event)

    def _send_email(self, config, event):
        host = str(config.get("host") or "").strip()
        recipients = [str(item).strip() for item in config.get("to") or [] if str(item).strip()]
        if not host or not recipients:
            raise ValueError("email host and recipients are required")
        msg = EmailMessage()
        msg["Subject"] = "[cfquant] %s" % event.get("title", "monitor")
        msg["From"] = config.get("from") or config.get("username") or recipients[0]
        msg["To"] = ", ".join(recipients)
        msg.set_content(self._format_text(event))
        context = ssl.create_default_context()
        if config.get("use_ssl"):
            with smtplib.SMTP_SSL(host, int(config.get("port") or 465), timeout=8, context=context) as server:
                if config.get("username"):
                    server.login(config.get("username"), config.get("password") or "")
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, int(config.get("port") or 25), timeout=8) as server:
                server.ehlo()
                if config.get("use_tls"):
                    server.starttls(context=context)
                    server.ehlo()
                if config.get("username"):
                    server.login(config.get("username"), config.get("password") or "")
                server.send_message(msg)

    def _send_webhook(self, config, event):
        payload = {key: event.get(key) for key in ("event_type", "title", "message", "payload", "occurred_at")}
        return send_webhook(config, self._format_text(event), payload=payload)
