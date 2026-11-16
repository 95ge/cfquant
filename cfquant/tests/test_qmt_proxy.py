import pytest

from cfquant.qmt_proxy import normalize_qmt_proxy_settings, qmt_proxy_environment


def test_proxy_defaults_keep_localhost_outside_proxy():
    value = normalize_qmt_proxy_settings()
    assert value["enabled"] is False
    assert value["type"] == "none"
    assert {"127.0.0.1", "localhost", "::1"}.issubset(value["bypass"])


def test_socks5_proxy_normalizes_bypass_and_environment():
    value = normalize_qmt_proxy_settings({
        "enabled": True,
        "type": "socks5",
        "host": "proxy.example.com",
        "port": 1080,
        "username": "demo",
        "bypass": ["10.0.0.0/8", "broker.example.com"],
        "udp_policy": "proxy",
    }, strict=True)
    env = qmt_proxy_environment(value, "secret")
    assert env["ALL_PROXY"] == "socks5h://demo:secret@proxy.example.com:1080"
    assert "127.0.0.1" in env["NO_PROXY"]
    assert "10.0.0.0/8" in env["NO_PROXY"]


def test_http_proxy_rejects_native_udp_proxying():
    with pytest.raises(ValueError, match="cannot carry native UDP"):
        normalize_qmt_proxy_settings({
            "enabled": True, "type": "http", "host": "127.0.0.1",
            "port": 8080, "udp_policy": "proxy",
        }, strict=True)
