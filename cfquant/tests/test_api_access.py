from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import http.client
from http.server import ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

import pytest

from cfquant.api_access import ApiAccessStore, AccessDenied
import cfquant_web_server as web


A = "bridge-a:STOCK:10001"
B = "bridge-b:STOCK:10001"
C = "bridge-a:CREDIT:10001"


@pytest.fixture
def store(tmp_path):
    return ApiAccessStore(tmp_path / "config" / "keys.sqlite3", tmp_path / "audit" / "keys.sqlite3",
                          protect=lambda value, entropy: value[::-1], unprotect=lambda value, entropy: value[::-1])


def create(store, **changes):
    body = dict(name="test-client", permissions=["query"], account_keys=[A], all_accounts=False,
                limits={"requests_per_minute": 60, "requests_per_second": 5, "trades_per_minute": 10})
    body.update(changes)
    row = store.save(body, {A, B, C})
    return row, store.reveal(row["id"])


def test_key_storage_reveal_edit_and_delete_keep_history(store):
    row, token = create(store)
    assert token.startswith("cfqm_") and token not in json.dumps(row)
    assert token.encode() not in store.path.read_bytes()
    assert store.audit_path != store.path
    audit_id = store.begin_audit(row, "POST", "/api/order", "127.0.0.1", "trade", [A], {"api_key": token, "volume": 100})
    store.finish_audit(audit_id, 403, "permission_denied")
    store.save({"id":row["id"], "name":"renamed", "enabled":False}, {A})
    assert store.reveal(row["id"]) == token
    assert store.authenticate(token)["enabled"] is False
    store.delete(row["id"])
    assert store.list_keys() == []
    assert store.authenticate(token)["deleted"] is True
    with pytest.raises(ValueError):
        store.reveal(row["id"])
    records = store.audit(row["id"])
    assert records["total"] == 1
    assert records["items"][0]["outcome"] == "denied"
    assert token not in json.dumps(records)


@pytest.mark.parametrize("changes", [
    {"permissions":["admin"]}, {"permissions":[]}, {"account_keys":[]},
    {"account_keys":["invented"]}, {"limits":{"requests_per_second":0}},
    {"limits":{"requests_per_minute":True}}, {"limits":{"unknown":2}}, {"enabled":"false"},
])
def test_invalid_grants_rejected(store, changes):
    with pytest.raises(ValueError):
        create(store, **changes)


def test_durable_rate_windows_and_weighted_batch(store):
    now = [1000.0]
    store.clock = lambda: now[0]
    row, token = create(store, permissions=["query", "trade"], limits={
        "requests_per_second":2, "requests_per_minute":3, "trades_per_minute":3})
    store.consume(row, "query")
    store.consume(row, "trade", weight=2)
    with pytest.raises(AccessDenied) as error:
        store.consume(row, "query")
    assert error.value.status == 429 and error.value.retry_after == 1
    now[0] += 2
    restarted = ApiAccessStore(store.path, store.audit_path, clock=lambda:now[0])
    key = restarted.authenticate(token)
    with pytest.raises(AccessDenied):
        restarted.consume(key, "trade", weight=2)
    restarted.consume(key, "trade", weight=1)
    with pytest.raises(AccessDenied):
        restarted.consume(key, "query")
    now[0] += 61
    restarted.consume(key, "trade", weight=3)


def test_concurrent_rate_limit_is_atomic(store):
    store.clock = lambda: 1000
    row, _ = create(store)
    def attempt(_):
        try:
            store.consume(row, "query")
            return True
        except AccessDenied:
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(attempt, range(20))) == 5


@pytest.fixture
def http_api(monkeypatch, store):
    configs = {
        key: {"account_key":key, "account_id":"10001", "account_type":kind, "bridge_id":bridge,
              "enabled":True, "qmt_password":"must-not-leak"}
        for key, kind, bridge in ((A,"STOCK","bridge-a"), (B,"STOCK","bridge-b"), (C,"CREDIT","bridge-a"))
    }
    config = SimpleNamespace(api_key=lambda:"master-secret", web_auth_enabled=lambda:True,
                             allow_remote=lambda:False, allowed_domains=lambda:[], account_configs=lambda:configs)
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "ACCESS_KEYS", store)
    monkeypatch.setattr(web, "web_auth_token_info", lambda token: {"username":"admin"} if token == "admin-session" else None)
    monkeypatch.setattr(web, "PROJECT_UPDATER", SimpleNamespace(trade_request=lambda path:nullcontext()))
    dispatched = []
    def order(body):
        dispatched.append(body)
        return {"result":1234, "order_remark":body.get("order_remark", "")}
    monkeypatch.setattr(web, "submit_order", order)
    monkeypatch.setattr(web, "get_full_tick", lambda body: {"account_key":body["account_key"], "result":{}})
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs:kwargs.get("bridge_id") or "bridge-a")
    monkeypatch.setattr(web, "bridge_config", lambda bridge: {})
    monkeypatch.setattr(web, "ACCOUNT_CACHE", SimpleNamespace(get_market_routed=lambda *a, **k:{"asset":{}, "cache":{}}))
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.CfquantWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(method, path, token="", body=None, extra_headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        headers = {"Content-Type":"application/json"}
        if token:
            headers["X-API-Key"] = token
        headers.update(extra_headers or {})
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        conn.close()
        return result
    yield request, dispatched, config
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_http_query_key_cannot_trade_or_manage(http_api, store):
    request, dispatched, _ = http_api
    row, token = create(store)
    for method, path, body in (("POST","/api/order",{"account_key":A}),
                                ("POST","/api/apikey",{"api_key":"new-master"}),
                                ("GET","/api/access-keys",None),
                                ("GET","/api/internal/runtime-route",None)):
        assert request(method, path, token, body)[0] == 403
    assert dispatched == []
    records = store.audit(row["id"])["items"]
    assert len(records) == 4 and all(item["outcome"] == "denied" for item in records)


def test_http_scoped_config_is_redacted_and_account_specific(http_api, store):
    request, _, _ = http_api
    _, token = create(store)
    status, payload, _ = request("GET", "/api/config", token)
    assert status == 200
    assert list(payload["data"]["account_configs"]) == [A]
    assert "must-not-leak" not in json.dumps(payload)
    assert "api_key" not in payload["data"]
    assert "bridges" not in payload["data"]
    assert request("GET", "/api/account?account_key="+A, token)[0] == 200


@pytest.mark.parametrize("selectors", [
    {"account_key":B}, {"account_key":A,"account_id":"99999"},
    {"account_key":A,"bridge_id":"bridge-b"}, {"account_key":A,"account_type":"CREDIT"},
    {"account_key":A,"channel":"arbitrary.private.channel"},
    {"account_key":A,"orders":[{"account_key":B,"volume":100}]},
])
def test_http_cross_account_and_selector_conflicts_rejected(http_api, store, selectors):
    request, dispatched, _ = http_api
    _, token = create(store, permissions=["query","trade"])
    assert request("POST", "/api/order", token, selectors)[0] == 403
    assert not dispatched


def test_http_trade_scope_dispatch_and_audit(http_api, store):
    request, dispatched, _ = http_api
    row, token = create(store, permissions=["trade"])
    status, payload, _ = request("POST", "/api/order", token, {"account_key":A, "volume":100, "stock_code":"000001.SZ"})
    assert status == 200 and payload["data"]["result"] == 1234
    assert dispatched[0]["account_id"] == "10001" and dispatched[0]["bridge_id"] == "bridge-a"
    assert request("GET", "/api/account?account_key="+A, token)[0] == 403
    record = next(r for r in store.audit(row["id"])["items"] if r["path"] == "/api/order")
    assert record["accounts"] == [A] and record["parameters"]["volume"] == 100
    assert record["result"]["result"] == 1234


def test_http_rate_and_revocation_have_no_dispatch(http_api, store):
    request, dispatched, _ = http_api
    row, token = create(store, permissions=["query","trade"], limits={"requests_per_second":1})
    assert request("POST", "/api/order", token, {"account_key":A})[0] == 200
    status, body, headers = request("POST", "/api/order", token, {"account_key":A})
    assert status == 429 and int(headers["Retry-After"]) >= 1
    store.save({"id":row["id"],"enabled":False}, {A})
    assert request("POST", "/api/order", token, {"account_key":A})[0] == 401
    store.delete(row["id"])
    assert request("POST", "/api/order", token, {"account_key":A})[0] == 401
    assert len(dispatched) == 1
    assert store.audit(row["id"])["total"] == 4


def test_http_key_admin_requires_admin_and_reveal_is_audited(http_api, store):
    request, _, _ = http_api
    body = {"name":"client", "permissions":["query"], "account_keys":[A]}
    assert request("POST", "/api/access-keys", body=body)[0] == 403
    status, data, _ = request("POST", "/api/access-keys", "master-secret", body)
    assert status == 200
    key_id = data["data"]["id"]
    assert "api_key" not in data["data"]
    status, data, headers = request("POST", "/api/access-keys/reveal", body={"id":key_id}, extra_headers={"X-CFQUANT-WEB-TOKEN":"admin-session"})
    assert status == 200 and data["data"]["api_key"].startswith("cfqm_")
    assert headers["Cache-Control"] == "no-store"
    assert {item["action"] for item in store.audit(key_id)["items"]} == {"key.create", "key.reveal"}


def test_http_audit_failure_prevents_trade(http_api, store, monkeypatch):
    request, dispatched, _ = http_api
    _, token = create(store, permissions=["trade"])
    def failed(*args, **kwargs):
        raise OSError("audit disk failure")
    monkeypatch.setattr(store, "begin_audit", failed)
    assert request("POST", "/api/order", token, {"account_key":A})[0] == 503
    assert not dispatched


def test_http_unknown_key_never_inherits_browser_admin(http_api):
    request, dispatched, _ = http_api
    assert request("POST", "/api/order", "cfqm_invalid", {"account_key":A},
                   {"X-CFQUANT-WEB-TOKEN":"admin-session"})[0] == 401
    assert not dispatched


@pytest.mark.parametrize("path", ["/api/future/order", "/api/future/orders/batch", "/api/future-option/order_async", "/api/stock-option/order", "/api/credit/query"])
def test_http_typed_endpoint_cannot_override_authorized_account_type(http_api, store, path):
    request, dispatched, _ = http_api
    _, token = create(store, permissions=["query", "trade"])
    assert request("POST", path, token, {"account_key":A})[0] == 403
    assert not dispatched


def test_http_trade_batch_cannot_hide_from_trade_rate(http_api, store):
    request, dispatched, _ = http_api
    _, token = create(store, permissions=["trade"], limits={"trades_per_minute":2})
    status, _, _ = request("POST", "/api/orders/batch", token, {"account_key":A, "orders":[{"volume":100}]*3})
    assert status == 429
    assert not dispatched


def test_http_rate_limit_applies_to_denied_calls(http_api, store):
    request, _, _ = http_api
    _, token = create(store, limits={"requests_per_second":1})
    assert request("POST", "/api/order", token, {"account_key":B})[0] == 403
    assert request("GET", "/api/health", token)[0] == 429


def test_http_audit_failure_after_dispatch_warns_of_uncertain_result(http_api, store, monkeypatch):
    request, dispatched, _ = http_api
    row, token = create(store, permissions=["trade"])
    def fail(*args, **kwargs):
        raise OSError("audit finalization failure")
    monkeypatch.setattr(store, "finish_audit", fail)
    status, payload, _ = request("POST", "/api/order", token, {"account_key":A})
    assert status == 503 and payload["code"] == "audit_write_failed"
    assert len(dispatched) == 1
    assert store.audit(row["id"])["items"][0]["outcome"] == "pending"


def test_http_bearer_and_query_key_never_appear_in_audit_or_runtime_logs(http_api, store, monkeypatch):
    request, _, _ = http_api
    row, token = create(store)
    messages = []
    monkeypatch.setattr(web, "safe_print", lambda value:messages.append(value))
    assert request("GET", "/api/config", extra_headers={"Authorization":"Bearer "+token})[0] == 200
    assert request("GET", "/api/config?apikey="+token)[0] == 200
    assert token not in json.dumps(store.audit(row["id"]))
    assert token not in str(messages)


def test_http_valid_scoped_key_with_admin_cookie_cannot_escalate(http_api, store):
    request, dispatched, _ = http_api
    _, token = create(store)
    headers = {"X-CFQUANT-WEB-TOKEN":"admin-session"}
    assert request("POST", "/api/access-keys/reveal", token, {"id":"any"}, headers)[0] == 403
    assert request("POST", "/api/order", token, {"account_key":A}, headers)[0] == 403
    assert not dispatched


def test_http_multiple_authorized_accounts_require_explicit_selection(http_api, store):
    request, _, config = http_api
    row, token = create(store, all_accounts=True, account_keys=[])
    assert request("GET", "/api/account", token)[0] == 403
    assert request("GET", "/api/account?account_key="+B, token)[0] == 200
    config.account_configs()[B]["enabled"] = False
    assert request("GET", "/api/account?account_key="+B, token)[0] == 403
    assert store.audit(row["id"])["total"] == 3


def test_audit_redacts_tokens_even_in_allowed_business_fields(store):
    from cfquant.api_access import audit_result
    token = "cfqm_not-a-real-secret"
    request_id = store.begin_audit({"id":"example", "name":token}, "POST", "/api/"+token,
                                  "127.0.0.1", "trade", payload={"order_remark":token,"api_key":token})
    summary = audit_result({"result":[{"order_id":123,"api_key":token,"order_remark":token}]})
    store.finish_audit(request_id, 200, result=summary)
    data = store.audit()
    assert token not in json.dumps(data)
    assert data["items"][0]["result"]["result"][0]["order_id"] == 123
