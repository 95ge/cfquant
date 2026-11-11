"""User-authored messages: explicit Webhook first, otherwise account binding."""

import atexit
import threading

from .webhook import WebhookError, normalize_webhook, send_webhook, validate_message

_client = None
_client_lock = threading.Lock()


def close():
    """Release the notification RPC connection; the next call reconnects."""
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is not None:
        client.close()


atexit.register(close)


def send(message, account_id=None, *, title="", webhook_url=None, provider=None,
         secret=None, account_type=None, account_key=None, bridge_id=None, timeout=8):
    """Send text synchronously; returns sent/provider/source, or raises on failure.

    webhook_url and provider must be supplied together and override the binding
    completely (including its secret). Account-based sends require cfquant Web
    and LTtx, but do not require QMT to be online. No automatic retry is performed.
    """
    timeout = validate_message(message, title, timeout)
    if webhook_url is not None or provider is not None or secret is not None:
        if not webhook_url or not provider:
            raise ValueError("调用时覆盖推送配置必须同时提供 webhook_url 和 provider")
        config = normalize_webhook({"enabled": True, "url": webhook_url, "provider": provider, "secret": secret})
        return dict(send_webhook(config, message, title=title, timeout=timeout), source="explicit")
    if not str(account_id or "").strip() and not str(account_key or "").strip():
        raise ValueError("请指定资金账号 account_id 或 account_key，或提供 webhook_url 和 provider")
    params = {"message": message, "title": title, "timeout": timeout}
    params.update({key: value for key, value in dict(account_id=account_id, account_type=account_type,
        account_key=account_key, bridge_id=bridge_id).items() if value is not None})
    global _client
    with _client_lock:
        if _client is None:
            from .client import create_rpc_client
            _client = create_rpc_client(transport="web_lttx")
        client = _client
    return client.request("cfquant.notify.send", params, timeout=timeout + 5)


__all__ = ["send", "close", "WebhookError"]
