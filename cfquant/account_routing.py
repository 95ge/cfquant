# -*- coding: utf-8 -*-
import threading


_lock = threading.RLock()
_subscribers = {}
_client_accounts = {}


def _account_type(account_type):
    value = str(account_type or "STOCK").strip().upper()
    mapping = {
        "1": "FUTURE",
        "FUTURE_ACCOUNT": "FUTURE",
        "2": "STOCK",
        "SECURITY": "STOCK",
        "SECURITY_ACCOUNT": "STOCK",
        "STOCK_ACCOUNT": "STOCK",
        "3": "CREDIT",
        "CREDIT_ACCOUNT": "CREDIT",
        "MARGIN": "CREDIT",
        "5": "FUTURE_OPTION",
        "FUTURE_OPTION_ACCOUNT": "FUTURE_OPTION",
        "FUTUREOPTION": "FUTURE_OPTION",
        "6": "STOCK_OPTION",
        "STOCK_OPTION_ACCOUNT": "STOCK_OPTION",
        "STOCKOPTION": "STOCK_OPTION",
        "OPTION": "STOCK_OPTION",
    }
    return mapping.get(value, value or "STOCK")


def _key(bridge_id, account_id, account_type=None):
    return (
        str(bridge_id or "default").strip(),
        _account_type(account_type),
        str(account_id or "").strip(),
    )


def subscribe(bridge_id, account_id, client_id, account_type=None):
    bridge_id, account_type, account_id = _key(bridge_id, account_id, account_type)
    client_id = str(client_id or "").strip()
    if not account_id or not client_id:
        return
    with _lock:
        _subscribers.setdefault((bridge_id, account_type, account_id), set()).add(client_id)
        _client_accounts.setdefault((bridge_id, client_id), set()).add((account_type, account_id))


def unsubscribe(bridge_id, account_id=None, client_id=None, account_type=None):
    bridge_id = str(bridge_id or "default").strip()
    account_type = _account_type(account_type) if account_type not in (None, "") else ""
    account_id = str(account_id or "").strip()
    client_id = str(client_id or "").strip()
    with _lock:
        if account_id and client_id:
            if account_type:
                _remove_pair(bridge_id, account_id, client_id, account_type)
            else:
                for item_type in _account_types_for_account_locked(bridge_id, account_id):
                    _remove_pair(bridge_id, account_id, client_id, item_type)
            return
        if client_id:
            accounts = _client_accounts.pop((bridge_id, client_id), set())
            for item in accounts:
                if isinstance(item, tuple):
                    item_type, item_account_id = item
                else:
                    item_type, item_account_id = "STOCK", item
                subscribers = _subscribers.get((bridge_id, item_type, item_account_id))
                if subscribers:
                    subscribers.discard(client_id)
                    if not subscribers:
                        _subscribers.pop((bridge_id, item_type, item_account_id), None)
            return
        if account_id:
            types = [account_type] if account_type else _account_types_for_account_locked(bridge_id, account_id)
            for item_type in types:
                subscribers = _subscribers.pop((bridge_id, item_type, account_id), set())
                for item in subscribers:
                    accounts = _client_accounts.get((bridge_id, item))
                    if accounts:
                        accounts.discard((item_type, account_id))
                        accounts.discard(account_id)
                        if not accounts:
                            _client_accounts.pop((bridge_id, item), None)


def client_ids(bridge_id, account_id, account_type=None):
    bridge_id, account_type, account_id = _key(bridge_id, account_id, account_type)
    if not account_id:
        return []
    with _lock:
        return sorted(_subscribers.get((bridge_id, account_type, account_id), set()))


def status(bridge_id):
    bridge_id = str(bridge_id or "default").strip()
    with _lock:
        return dict(
            ("%s:%s" % (account_type, account_id), len(client_ids))
            for (item_bridge_id, account_type, account_id), client_ids in _subscribers.items()
            if item_bridge_id == bridge_id
        )


def _account_types_for_account_locked(bridge_id, account_id):
    return [
        account_type
        for item_bridge_id, account_type, item_account_id in _subscribers.keys()
        if item_bridge_id == bridge_id and item_account_id == account_id
    ] or ["STOCK"]


def _remove_pair(bridge_id, account_id, client_id, account_type="STOCK"):
    account_type = _account_type(account_type)
    subscribers = _subscribers.get((bridge_id, account_type, account_id))
    if subscribers:
        subscribers.discard(client_id)
        if not subscribers:
            _subscribers.pop((bridge_id, account_type, account_id), None)
    accounts = _client_accounts.get((bridge_id, client_id))
    if accounts:
        accounts.discard((account_type, account_id))
        accounts.discard(account_id)
        if not accounts:
            _client_accounts.pop((bridge_id, client_id), None)
