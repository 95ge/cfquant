"""Webhook settings and delivery shared by account messages and monitoring."""

import base64
import hashlib
import hmac
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from .qmt_proxy import public_qmt_proxy


PROVIDERS = ("wecom", "dingtalk", "feishu", "generic")


class WebhookError(RuntimeError):
    """Delivery failed; messages deliberately exclude URLs, tokens and responses."""


def validate_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Webhook 地址必须是 HTTP(S) URL")
    value = value.strip()
    try:
        parsed = urllib.parse.urlsplit(value)
        valid = (parsed.scheme in ("http", "https") and parsed.hostname
                 and not parsed.username and not parsed.password and not parsed.fragment)
        parsed.port
    except ValueError:
        valid = False
    if not valid or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("Webhook 地址必须是有效的 HTTP(S) URL，不能包含登录信息或片段")
    return value


def normalize_webhook(value=None, previous=None):
    old = dict(previous or {})
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("notification_webhook 必须是对象")
    if value.get("clear") is True:
        return {"enabled": False, "provider": "wecom", "url": "", "secret": ""}
    enabled = value.get("enabled", old.get("enabled", False))
    if type(enabled) is not bool:
        raise ValueError("Webhook 启用状态必须是布尔值")
    provider = str(value.get("provider", old.get("provider", "wecom"))).strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("provider 必须是 wecom、dingtalk、feishu 或 generic")
    url = value.get("url") or old.get("url") or ""
    if url:
        url = validate_url(url)
    if provider != old.get("provider", provider) and not value.get("url"):
        url = ""
    if enabled and not url:
        raise ValueError("启用账号推送时请填写 Webhook 地址；更换平台需重新填写地址")
    changed = url != old.get("url", "") or provider != old.get("provider", provider)
    secret = value.get("secret") or ("" if changed else old.get("secret", ""))
    if value.get("clear_secret") is True or provider not in ("dingtalk", "feishu"):
        secret = ""
    if not isinstance(secret, str) or len(secret) > 1024:
        raise ValueError("Webhook 加签密钥格式无效")
    return {"enabled": enabled, "provider": provider, "url": url, "secret": secret.strip()}


def public_webhook(value):
    value = value or {}
    return {"enabled": value.get("enabled", False), "provider": value.get("provider", "wecom"),
            "url": "", "secret": "", "url_configured": bool(value.get("url")),
            "secret_configured": bool(value.get("secret"))}


def public_binding(row):
    if row is None:
        return None
    result = dict(row)
    result["notification_webhook"] = public_webhook(row.get("notification_webhook"))
    result["qmt_proxy"] = public_qmt_proxy(row.get("qmt_proxy"))
    return result


def validate_message(message, title="", timeout=8):
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message 必须是非空字符串")
    if not isinstance(title, str) or len(title) > 200:
        raise ValueError("title 必须是最多 200 字符的字符串")
    if len(message.encode("utf-8")) > 20000:
        raise ValueError("message 不能超过 20000 个 UTF-8 字节")
    if isinstance(timeout, bool):
        raise ValueError("timeout 必须在 1–30 秒之间")
    timeout = float(timeout)
    if not math.isfinite(timeout) or not 1 <= timeout <= 30:
        raise ValueError("timeout 必须在 1–30 秒之间")
    return timeout


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_webhook(config, message, *, title="", timeout=8, payload=None):
    """Send once and check the platform acknowledgement. Never retry implicitly."""
    timeout = validate_message(message, title, timeout)
    provider = config.get("provider") or config.get("type") or "generic"
    if provider not in PROVIDERS:
        raise ValueError("不支持的 Webhook 平台")
    url = validate_url(config.get("url"))
    secret = config.get("secret") or ""
    text = "%s\n%s" % (title, message) if title else message
    if provider == "wecom" and len(text.encode("utf-8")) > 2048:
        raise ValueError("企业微信文本消息（含标题）不能超过 2048 个 UTF-8 字节")
    if provider == "feishu":
        body = {"msg_type": "text", "content": {"text": text}}
        if secret:
            timestamp = str(int(time.time()))
            key = (timestamp + "\n" + secret).encode("utf-8")
            body.update(timestamp=timestamp, sign=base64.b64encode(
                hmac.new(key, b"", hashlib.sha256).digest()).decode("ascii"))
    elif provider in ("wecom", "dingtalk"):
        body = {"msgtype": "text", "text": {"content": text}}
    else:
        body = payload if payload is not None else {"title": title, "message": message}
    if provider == "dingtalk" and secret:
        timestamp = str(int(time.time() * 1000))
        sign = base64.b64encode(hmac.new(secret.encode("utf-8"),
            (timestamp + "\n" + secret).encode("utf-8"), hashlib.sha256).digest()).decode("ascii")
        parts = urllib.parse.urlsplit(url)
        query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
                 if k not in ("timestamp", "sign")]
        query.extend((("timestamp", timestamp), ("sign", sign)))
        url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "cfquant-webhook"}, method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            status = response.status
            raw = response.read(65537)
    except Exception:
        raise WebhookError("Webhook 请求失败或超时，投递结果可能未知；请检查网络、地址及接收端记录") from None
    if not 200 <= status < 300:
        raise WebhookError("Webhook HTTP 请求失败（状态 %s）" % status)
    if provider != "generic":
        try:
            result = json.loads(raw.decode("utf-8"))
            codes = [result[key] for key in ("errcode", "code", "StatusCode") if key in result]
            if not isinstance(result, dict) or not codes or any(str(code) != "0" for code in codes):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise WebhookError("Webhook 平台未确认成功，请检查机器人地址、加签、关键词及平台频率限制") from None
    return {"sent": True, "provider": provider, "http_status": status}
