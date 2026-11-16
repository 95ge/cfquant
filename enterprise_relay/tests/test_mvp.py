import pytest
import json
import threading
from urllib.request import Request, urlopen

from enterprise_relay.server import RelayApplication, RelayHTTPServer
from enterprise_relay.store import RelayError, RelayStore


def _app(tmp_path, market=True):
    store = RelayStore(
        tmp_path / "relay.sqlite3",
        activation_code="activation-code-123",
        entitlement={
            "plan": "enterprise",
            "relay_mode": "self_hosted",
            "features": {"market_forwarding": market, "trade_routing": True},
            "limits": {"max_nodes": 10, "max_market_bps": None},
        },
    )
    return RelayApplication(store)


def _admin(app):
    app.dispatch("POST", "/api/v1/auth/bootstrap", {
        "activation_code": "activation-code-123",
        "username": "owner",
        "password": "a-strong-test-password",
    })
    result = app.dispatch("POST", "/api/v1/auth/login", {
        "username": "owner", "password": "a-strong-test-password",
    })
    return result["data"]["access_token"]


def _header(token):
    return {"Authorization": "Bearer " + token}


def test_bootstrap_is_one_time_and_admin_session_is_required(tmp_path):
    app = _app(tmp_path)
    assert app.dispatch("GET", "/api/v1/health")["data"]["activated"] is False
    token = _admin(app)
    with pytest.raises(RelayError) as error:
        app.dispatch("POST", "/api/v1/auth/bootstrap", {
            "activation_code": "activation-code-123",
            "username": "another",
            "password": "another-strong-password",
        })
    assert error.value.code == "already_activated"
    status = app.dispatch("GET", "/api/v1/admin/status", headers=_header(token))
    assert status["data"]["plan"] == "enterprise"


def test_pair_nodes_heartbeat_and_route_opaque_message(tmp_path):
    app = _app(tmp_path)
    admin_token = _admin(app)
    pairing = app.dispatch("POST", "/api/v1/admin/pairing", headers=_header(admin_token))
    node_a = app.dispatch("POST", "/api/v1/nodes/claim", {
        "pairing_code": pairing["data"]["pairing_code"],
        "node_id": "node_a",
        "name": "A",
        "public_key": "public-key-a",
        "version": "0.1.0",
        "capabilities": ["market", "trade"],
    })["data"]
    pairing_b = app.dispatch("POST", "/api/v1/admin/pairing", headers=_header(admin_token))
    node_b = app.dispatch("POST", "/api/v1/nodes/claim", {
        "pairing_code": pairing_b["data"]["pairing_code"],
        "node_id": "node_b",
        "name": "B",
        "public_key": "public-key-b",
        "version": "0.1.0",
        "capabilities": ["market"],
    })["data"]
    for node in (node_a, node_b):
        app.dispatch("POST", "/api/v1/nodes/heartbeat", {
            "version": "0.1.0", "snapshot": {"healthy": True}
        }, headers=_header(node["node_token"]))
    queued = app.dispatch("POST", "/api/v1/messages/send", {
        "target_node_id": "node_b",
        "channel": "market",
        "ttl_seconds": 30,
        "envelope": {"message_id": "m1", "ciphertext": "opaque-ciphertext"},
    }, headers=_header(node_a["node_token"]))
    assert queued["data"]["message_id"].startswith("msg_")
    messages = app.dispatch("POST", "/api/v1/messages/poll", {"limit": 10},
                            headers=_header(node_b["node_token"]))["data"]["messages"]
    assert messages[0]["sender_node_id"] == "node_a"
    assert messages[0]["envelope"] == {"message_id": "m1", "ciphertext": "opaque-ciphertext"}
    assert app.dispatch("POST", "/api/v1/messages/poll", {"limit": 10},
                        headers=_header(node_b["node_token"]))["data"]["messages"] == []


def test_market_forwarding_is_server_side_entitlement(tmp_path):
    app = _app(tmp_path, market=False)
    admin_token = _admin(app)
    pairing = app.dispatch("POST", "/api/v1/admin/pairing", headers=_header(admin_token))
    node = app.dispatch("POST", "/api/v1/nodes/claim", {
        "pairing_code": pairing["data"]["pairing_code"], "node_id": "node_a",
        "name": "A", "public_key": "public-key-a", "version": "0.1.0",
    })["data"]
    with pytest.raises(RelayError) as error:
        app.dispatch("POST", "/api/v1/messages/send", {
            "target_node_id": "node_a", "channel": "market",
            "envelope": {"ciphertext": "opaque"},
        }, headers=_header(node["node_token"]))
    assert error.value.code == "feature_not_entitled"


def test_http_server_exposes_json_health_and_bootstrap(tmp_path):
    app = _app(tmp_path)
    server = RelayHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%s" % server.server_address[1]

    def request(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(base + path, data=body, method="GET" if body is None else "POST")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        assert request("/api/v1/health")["ok"] is True
        result = request("/api/v1/auth/bootstrap", {
            "activation_code": "activation-code-123", "username": "owner",
            "password": "a-strong-test-password",
        })
        assert result["data"]["username"] == "owner"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
