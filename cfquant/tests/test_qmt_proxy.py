import json
from types import SimpleNamespace

import pytest

from cfquant.qmt_proxy import QmtProxyCredentialStore, normalize_qmt_proxy_settings, qmt_proxy_environment


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


@pytest.fixture
def credentials(tmp_path, monkeypatch):
    from cfquant import qmt_dependencies

    store = QmtProxyCredentialStore(tmp_path / "config.json")
    calls = []

    def protect(data, description, entropy, reserved, prompt, flags):
        calls.append(("protect", entropy))
        assert data == b"test-password"
        return b"encrypted-fixture"

    def unprotect(data, entropy, reserved, prompt, flags):
        calls.append(("unprotect", entropy))
        assert data == b"encrypted-fixture"
        return "CFQuant QMT proxy", b"test-password"

    def load(name):
        assert name == "win32crypt"
        return SimpleNamespace(CryptProtectData=protect, CryptUnprotectData=unprotect)

    monkeypatch.setattr(qmt_dependencies, "import_login_module", load)
    return store, calls


def test_credentials_still_encrypt_and_decrypt_after_lazy_import(credentials):
    store, calls = credentials
    store.save("account", "test-password")
    raw = store.path.read_text(encoding="utf-8")
    assert "test-password" not in raw
    assert json.loads(raw)["account"]["secret"]
    assert store.password("account") == "test-password"
    assert calls == [("protect", store._entropy("account")),
                     ("unprotect", store._entropy("account"))]
    store.clear("account")
    assert store.password("account") == ""
    assert len(calls) == 2


@pytest.mark.parametrize("operation", ["save", "password"])
@pytest.mark.parametrize("dependency_error", [True, False])
def test_credentials_preserve_dependency_errors_and_hide_other_failures(
        credentials, monkeypatch, operation, dependency_error):
    from cfquant import qmt_dependencies

    store, _ = credentials
    store.save("account", "test-password")
    original = store.path.read_bytes()
    error = (qmt_dependencies.QmtDependencyError("login dependency unavailable")
             if dependency_error else OSError("private-native-error"))

    def fail(name):
        raise error

    monkeypatch.setattr(qmt_dependencies, "import_login_module", fail)
    with pytest.raises(RuntimeError) as caught:
        if operation == "save":
            store.save("account", "replacement")
        else:
            store.password("account")
    if dependency_error:
        assert caught.value is error
    else:
        assert "private-native-error" not in str(caught.value)
    assert store.path.read_bytes() == original
