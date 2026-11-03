"""SDK liveness for shared quote leases, independent of user callback speed."""
import atexit
import threading


_lock = threading.RLock()
_subscriptions = {}
_stop = threading.Event()
_thread = None


def remember(client, subscribe_id):
    global _thread
    with _lock:
        _subscriptions[(id(client), str(subscribe_id))] = (client, subscribe_id)
        if _thread is None:
            _thread = threading.Thread(target=_run, name="cfquant-quote-lease", daemon=True)
            _thread.start()


def forget(client, subscribe_id):
    with _lock:
        _subscriptions.pop((id(client), str(subscribe_id)), None)


def heartbeat():
    with _lock:
        rows = list(_subscriptions.values())
    clients = {}
    for client, subscribe_id in rows:
        if getattr(client, "_closed", False):
            forget(client, subscribe_id)
            continue
        clients.setdefault(id(client), (client, []))[1].append(subscribe_id)
    for client, ids in clients.values():
        try:
            client.request("cfquant.quote_heartbeat", {"subscribe_ids": ids}, timeout=3)
        except Exception:
            # Never allocate a new subscription in response to an uncertain
            # heartbeat. The service expires it if this process disappears.
            pass


def close_client_leases(client):
    with _lock:
        rows = [row for row in _subscriptions.values() if row[0] is client]
    for _, subscribe_id in rows:
        try:
            if not getattr(client, "_closed", False):
                client.request("xtdata.unsubscribe_quote", {"subscribe_id": subscribe_id}, timeout=2)
        except Exception:
            pass
        forget(client, subscribe_id)


def _run():
    while not _stop.wait(10):
        heartbeat()


def close():
    _stop.set()
    with _lock:
        clients = {id(row[0]): row[0] for row in _subscriptions.values()}
    for client in clients.values():
        close_client_leases(client)


atexit.register(close)
