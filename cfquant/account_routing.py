# -*- coding: utf-8 -*-
import threading


_lock = threading.RLock()
_subscribers = {}
_client_accounts = {}


def _key(bridge_id, account_id):
    return str(bridge_id or "default").strip(), str(account_id or "").strip()


def subscribe(bridge_id, account_id, client_id):
    bridge_id, account_id = _key(bridge_id, account_id)
    client_id = str(client_id or "").strip()
    if not account_id or not client_id:
        return
    with _lock:
        _subscribers.setdefault((bridge_id, account_id), set()).add(client_id)
        _client_accounts.setdefault((bridge_id, client_id), set()).add(account_id)


def unsubscribe(bridge_id, account_id=None, client_id=None):
    bridge_id = str(bridge_id or "default").strip()
    account_id = str(account_id or "").strip()
    client_id = str(client_id or "").strip()
    with _lock:
        if account_id and client_id:
            _remove_pair(bridge_id, account_id, client_id)
            return
        if client_id:
            accounts = _client_accounts.pop((bridge_id, client_id), set())
            for item in accounts:
                subscribers = _subscribers.get((bridge_id, item))
                if subscribers:
                    subscribers.discard(client_id)
                    if not subscribers:
                        _subscribers.pop((bridge_id, item), None)
            return
        if account_id:
            subscribers = _subscribers.pop((bridge_id, account_id), set())
            for item in subscribers:
                accounts = _client_accounts.get((bridge_id, item))
                if accounts:
                    accounts.discard(account_id)
                    if not accounts:
                        _client_accounts.pop((bridge_id, item), None)


def client_ids(bridge_id, account_id):
    bridge_id, account_id = _key(bridge_id, account_id)
    if not account_id:
        return []
    with _lock:
        return sorted(_subscribers.get((bridge_id, account_id), set()))


def status(bridge_id):
    bridge_id = str(bridge_id or "default").strip()
    with _lock:
        return dict(
            (account_id, len(client_ids))
            for (item_bridge_id, account_id), client_ids in _subscribers.items()
            if item_bridge_id == bridge_id
        )


def _remove_pair(bridge_id, account_id, client_id):
    subscribers = _subscribers.get((bridge_id, account_id))
    if subscribers:
        subscribers.discard(client_id)
        if not subscribers:
            _subscribers.pop((bridge_id, account_id), None)
    accounts = _client_accounts.get((bridge_id, client_id))
    if accounts:
        accounts.discard(account_id)
        if not accounts:
            _client_accounts.pop((bridge_id, client_id), None)
