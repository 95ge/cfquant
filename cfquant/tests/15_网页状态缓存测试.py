# -*- coding: utf-8 -*-
import json
import subprocess
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request
from urllib.parse import urlparse

import cfquant_web_server as web


def _status(online, mode):
    return {
        "normal": {"online": online, "channel": "%s.normal" % mode},
        "trade": {"online": online, "channel": "%s.trade" % mode},
        "monitor": {"ready": True, "cached": True, "transport_mode": mode},
    }


def _handler(headers=None):
    handler = object.__new__(web.CfquantWebHandler)
    handler.headers = dict(headers or {})
    return handler


def test_internal_api_key_is_generated_once_and_persisted(monkeypatch, tmp_path):
    key_file = tmp_path / "cfquant_internal_api_key"
    monkeypatch.delenv("CFQUANT_INTERNAL_API_KEY", raising=False)
    monkeypatch.setattr(web, "INTERNAL_API_KEY_FILE", str(key_file))
    monkeypatch.setattr(web, "_INTERNAL_API_KEY", None)

    first = web.internal_api_key()
    second = web.internal_api_key()

    assert first.startswith("cfqi_")
    assert second == first
    assert key_file.read_text(encoding="ascii").strip() == first


def test_internal_api_key_only_authorizes_allowlisted_paths(monkeypatch):
    config = SimpleNamespace(
        web_auth_enabled=lambda: True,
        api_key=lambda: "primary-secret",
    )
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "internal_api_key", lambda: "internal-secret")
    monkeypatch.setattr(web, "web_auth_token_info", lambda token: None)
    handler = _handler({web.INTERNAL_API_KEY_HEADER: "internal-secret"})

    assert handler._authorized(urlparse("/api/internal/runtime-route")) is True
    assert handler._authorized(urlparse("/api/health")) is True
    assert handler._authorized(urlparse("/api/order")) is False
    assert handler._internal_api_key_valid(urlparse("/api/config")) is False
    assert handler._has_access_token(urlparse("/api/config")) is False


def test_internal_api_still_requires_its_key_when_primary_auth_is_disabled(monkeypatch):
    config = SimpleNamespace(
        web_auth_enabled=lambda: False,
        api_key=lambda: "",
    )
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "internal_api_key", lambda: "internal-secret")
    monkeypatch.setattr(web, "web_auth_token_info", lambda token: None)

    assert _handler()._authorized(urlparse("/api/internal/runtime-route")) is False
    assert _handler({web.INTERNAL_API_KEY_HEADER: "wrong"})._authorized(
        urlparse("/api/internal/runtime-route")
    ) is False
    assert _handler({web.INTERNAL_API_KEY_HEADER: "internal-secret"})._authorized(
        urlparse("/api/internal/runtime-route")
    ) is True


def test_internal_runtime_route_redacts_account_details(monkeypatch):
    provider = {
        "account_key": "bridge-a:STOCK:123456",
        "account_id": "123456",
        "account_type": "STOCK",
        "bridge_id": "bridge-a",
        "mode": "lite",
        "qmt_dir": r"D:\\broker\\bin.x64",
        "enabled": True,
    }
    config = SimpleNamespace(
        account_configs=lambda: {provider["account_key"]: provider},
        data_provider_account_key=lambda: provider["account_key"],
        setup_info=lambda: {"default_account_key": provider["account_key"]},
        transport_mode=lambda: "ctypes",
    )
    monitor = SimpleNamespace(latest=lambda bridge_id, mode=None: {
        "normal": {"online": True, "channel": "cfquant.bridge-a.normal.request"},
        "checked_at": 123.0,
    })
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "STATUS_MONITOR", monitor)

    result = web.internal_runtime_route_info()
    serialized = json.dumps(result, ensure_ascii=False)

    assert result == {
        "available": True,
        "source": "configured_data_provider",
        "bridge_id": "bridge-a",
        "mode": "lite",
        "transport": "ctypes",
        "channel": "cfquant.bridge-a.normal.request",
        "online": True,
        "checked_at": 123.0,
    }
    assert "123456" not in serialized
    assert "broker" not in serialized


def test_internal_http_api_enforces_its_own_scope(monkeypatch):
    provider = {
        "account_key": "bridge-a:STOCK:123456",
        "account_id": "123456",
        "account_type": "STOCK",
        "bridge_id": "bridge-a",
        "mode": "lite",
        "enabled": True,
    }
    config = SimpleNamespace(
        allow_remote=lambda: False,
        allowed_domains=lambda: [],
        web_auth_enabled=lambda: True,
        api_key=lambda: "primary-secret",
        account_configs=lambda: {provider["account_key"]: provider},
        data_provider_account_key=lambda: provider["account_key"],
        setup_info=lambda: {"default_account_key": provider["account_key"]},
        transport_mode=lambda: "ctypes",
        transport_info=lambda: {"mode": "ctypes"},
        qmt_log_language_info=lambda: {"language": "zh"},
        api_key_info=lambda include_secret=True: {"enabled": True, "masked": "cfq_***", "api_key": ""},
    )
    monitor = SimpleNamespace(latest=lambda bridge_id, mode=None: {
        "normal": {"online": True, "channel": "cfquant.bridge-a.normal.request"},
        "checked_at": 123.0,
    })
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "STATUS_MONITOR", monitor)
    monkeypatch.setattr(web, "PIPE_HUB", SimpleNamespace(status=lambda: {"running": True}))
    monkeypatch.setattr(web, "internal_api_key", lambda: "internal-secret")
    monkeypatch.setattr(web, "web_auth_token_info", lambda token: None)
    monkeypatch.setattr(
        web,
        "server_access_info",
        lambda include_auth_details=False: {"web_auth": {"enabled": True}},
    )
    monkeypatch.setattr(web, "project_version_info", lambda include_remote=False: {"version": "test"})

    server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.CfquantWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://127.0.0.1:%s" % server.server_address[1]
    monkeypatch.setenv("CFQUANT_INTERNAL_API_KEY", "internal-secret")
    monkeypatch.setenv("CFQUANT_WEB_INTERNAL_URL", base_url)

    def get(path, key=None):
        headers = {web.INTERNAL_API_KEY_HEADER: key} if key else {}
        request = urllib.request.Request(base_url + path, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    try:
        health_status, health = get("/api/health")
        denied_status, _ = get("/api/internal/runtime-route")
        route_status, route = get("/api/internal/runtime-route", "internal-secret")
        order_status, _ = get("/api/order", "internal-secret")
        config_status, public_config = get("/api/config", "internal-secret")
        from cfquant.tests import _helpers as test_helpers
        discovered_route = test_helpers.discover_data_provider_route()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert health_status == 200
    assert health["data"] == {"status": "ok"}
    assert denied_status == 401
    assert route_status == 200
    assert route["data"]["mode"] == "lite"
    assert discovered_route == route["data"]
    assert order_status == 401
    assert config_status == 200
    assert public_config["data"]["auth_required"] is True
    assert "account_configs" not in public_config["data"]


def test_channel_status_monitor_keeps_ctypes_and_lttx_snapshots_separate():
    monitor = web.ChannelStatusMonitor()
    monitor._snapshots["default"] = {
        "ctypes": _status(True, "ctypes"),
        "lttx": _status(False, "lttx"),
    }

    assert monitor.latest("default", mode="ctypes")["normal"]["online"] is True
    assert monitor.latest("default", mode="lttx")["normal"]["online"] is False


def test_runtime_version_registry_keeps_newer_lttx_report_for_same_channel(tmp_path):
    now = time.time()
    persist_file = tmp_path / "qmt_runtime_versions.json"
    current = {
        "bridge_id": "default",
        "channel_key": "trade",
        "version": "core_20260904_01",
        "core_version": "core_20260904_01",
        "mode": "lttx",
        "transport": "lttx",
        "reported_at": now - 5,
        "reported_at_text": "2026-09-04 10:28:31",
    }
    old = {
        "bridge_id": "default",
        "channel_key": "trade",
        "version": "core_20260903_04",
        "core_version": "core_20260903_04",
        "mode": "ctypes",
        "transport": "pipe",
        "reported_at": now - 86400,
        "reported_at_text": "2026-09-03 16:07:18",
    }
    persist_file.write_text(
        json.dumps({"reports": [current, old]}, ensure_ascii=False),
        encoding="utf-8",
    )

    registry = web.RuntimeVersionRegistry(ttl_seconds=120, persist_file=str(persist_file))
    registry.update_from_event({
        "event": "cfquant.runtime",
        "bridge_id": "default",
        "data": old,
        "meta": {"source": "qmt_runtime_marker"},
    })

    report = registry.latest("default")
    trade_report = next(item for item in report["reports"] if item["channel_key"] == "trade")
    assert trade_report["mode"] == "lttx"
    assert trade_report["version"] == "core_20260904_01"


def test_auto_deploy_local_core_resolves_qmt_install_dir(tmp_path):
    source = tmp_path / "source"
    source_core = source / "cfquant"
    source_core.mkdir(parents=True)
    (source_core / "__init__.py").write_text("__version__ = 'test_auto'\n", encoding="utf-8")
    (source_core / "client.py").write_text("# client\n", encoding="utf-8")
    (source_core / "protocol.py").write_text("# protocol\n", encoding="utf-8")
    (source_core / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")
    qmt_root = tmp_path / "QMT"
    bin_dir = qmt_root / "bin.x64"
    bin_dir.mkdir(parents=True)

    updater = web.CfquantUpdater(None)
    result = updater.install_local_core_to_qmt_dir(
        str(qmt_root),
        bridge_id="demo",
        source_dir=str(source),
    )

    assert result["updated"] is True
    assert result["python_dir"] == str(bin_dir)
    assert (bin_dir / "cfquant" / "extra.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert result["current_version"] == "test_auto"


def test_auto_deploy_local_core_skips_when_target_matches(tmp_path):
    source = tmp_path / "source"
    source_core = source / "cfquant"
    target_core = tmp_path / "QMT" / "bin.x64" / "cfquant"
    source_core.mkdir(parents=True)
    target_core.mkdir(parents=True)
    for root in (source_core, target_core):
        (root / "__init__.py").write_text("__version__ = 'same'\n", encoding="utf-8")
        (root / "client.py").write_text("# client\n", encoding="utf-8")
        (root / "protocol.py").write_text("# protocol\n", encoding="utf-8")

    updater = web.CfquantUpdater(None)
    result = updater.install_local_core_to_qmt_dir(
        str(tmp_path / "QMT" / "bin.x64"),
        bridge_id="demo",
        source_dir=str(source),
    )

    assert result["skipped"] is True
    assert result["updated"] is False
    assert result["current_version"] == "same"
    assert not (tmp_path / "QMT" / "bin.x64" / ".cfquant_updates").exists()


def test_powershell_process_detail_timeout_is_nonfatal(monkeypatch):
    monkeypatch.setattr(web.os, "name", "nt")
    monkeypatch.setattr(web, "psutil", None)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(web.subprocess, "run", fake_run)

    assert web.run_powershell_json('"[]"', timeout=0.01) == []
    assert web.process_details_by_pid([15792]) == {}


def test_process_details_by_pid_uses_psutil_before_powershell(monkeypatch):
    monkeypatch.setattr(web.os, "name", "nt")

    class FakeProcess(object):
        def __init__(self, pid):
            self.pid = pid

        def oneshot(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def name(self):
            return "python.exe"

        def cmdline(self):
            return ["python", "LTtx_server.py"]

        def exe(self):
            return r"D:\Python\python.exe"

    class FakePsutil(object):
        NoSuchProcess = RuntimeError
        AccessDenied = PermissionError
        ZombieProcess = RuntimeError

        @staticmethod
        def Process(pid):
            return FakeProcess(pid)

    def fail_run(*args, **kwargs):
        raise AssertionError("PowerShell fallback should not be used")

    monkeypatch.setattr(web, "psutil", FakePsutil)
    monkeypatch.setattr(web.subprocess, "run", fail_run)

    assert web.process_details_by_pid([15792]) == {
        15792: {
            "pid": 15792,
            "name": "python.exe",
            "command_line": "python LTtx_server.py",
            "executable_path": r"D:\Python\python.exe",
        }
    }


def test_account_route_status_reads_monitor_cache_without_sync_probe(monkeypatch):
    ctypes_snapshot = _status(True, "ctypes")
    lttx_snapshot = _status(True, "lttx")
    calls = []

    class FakeMonitor(object):
        def latest(self, bridge_id, mode=None):
            calls.append((bridge_id, mode))
            return lttx_snapshot if mode == "lttx" else ctypes_snapshot

    fake_config = SimpleNamespace(
        account_config=lambda **kwargs: {
            "account_key": "default:STOCK:8885060548",
            "bridge_id": "default",
            "mode": "lttx",
        },
        data_provider_account_key=lambda: "",
    )

    monkeypatch.setattr(web, "WEB_CONFIG", fake_config)
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "default")
    monkeypatch.setattr(web, "resolve_account_mode", lambda *args, **kwargs: "lttx")
    monkeypatch.setattr(web, "account_market_route_config", lambda **kwargs: ({}, {}))
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})
    monkeypatch.setattr(web, "STATUS_MONITOR", FakeMonitor())
    monkeypatch.setattr(
        web,
        "ctypes_bridge_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync ctypes probe")),
    )
    monkeypatch.setattr(
        web,
        "probe_bridge_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync LTtx probe")),
    )

    result = web.account_route_status(
        "8885060548",
        bridge_id="default",
        account_type="STOCK",
        account_key="default:STOCK:8885060548",
    )

    assert result["ready"] is True
    assert result["effective_mode"] == "lttx"
    assert ("default", "ctypes") in calls
    assert ("default", "lttx") in calls


def test_lttx_routes_xttrader_queries_to_trade_channel():
    assert web.route_channel_for_account(
        "8885060548",
        requested_channel="normal",
        default="normal",
        mode="lttx",
        action="xttrader.query_stock_positions",
    ) == "trade"
    assert web.route_channel_for_account(
        "8885060548",
        requested_channel="trade",
        default="trade",
        mode="lttx",
        action="xtdata.download_history_data2",
    ) == "normal"


def test_account_request_forces_trade_channel_for_lttx_queries(monkeypatch):
    calls = []

    class FakeClients(object):
        def request(self, bridge_id, channel, action, params=None, **kwargs):
            calls.append({
                "bridge_id": bridge_id,
                "channel": channel,
                "action": action,
                "mode": kwargs.get("mode"),
            })
            return {"ok": True}

    fake_config = SimpleNamespace(account_config=lambda **kwargs: {"account_key": "default:STOCK:8885060548"})
    monkeypatch.setattr(web, "WEB_CONFIG", fake_config)
    monkeypatch.setattr(web, "CLIENTS", FakeClients())
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: kwargs.get("bridge_id") or "default")
    monkeypatch.setattr(web, "resolve_market_route_for_request", lambda **kwargs: (kwargs["bridge_id"], {}))
    monkeypatch.setattr(web, "resolve_account_mode", lambda *args, **kwargs: "lttx")

    route = web.account_request(
        "8885060548",
        "default",
        "normal",
        "xttrader.query_stock_orders",
        {"account": {"account_id": "8885060548", "account_type": "STOCK"}},
        default_channel="normal",
        account_type="STOCK",
        account_key="default:STOCK:8885060548",
    )

    assert route["channel"] == "trade"
    assert calls == [{
        "bridge_id": "default",
        "channel": "trade",
        "action": "xttrader.query_stock_orders",
        "mode": "lttx",
    }]


def test_account_cache_channel_uses_trade_for_lttx_account_sections():
    assert web.account_cache_channel_for_sections(
        "8885060548",
        requested_channel="normal",
        default="normal",
        mode="lttx",
        sections=["asset", "positions"],
    ) == "trade"


def test_market_account_row_market_uses_qmt_numeric_exchange_mapping():
    assert web.normalize_market_code("0") == "SH"
    assert web.normalize_market_code("1") == "SZ"
    assert web.market_account_row_market({
        "stock_code": "000001.SZ",
        "market": "1",
        "m_strExchangeID": "1",
    }) == "SZ"
    assert web.market_account_row_market({
        "stock_code": "000001.SZ",
        "m_nMarket": 1,
        "m_strExchangeID": "",
    }) == "SZ"


def test_market_bridge_config_preserves_position_query_account():
    sh_key = "2____10501____98101____49____77557115____"
    sz_key = "2____10502____98102____49____77557115____"

    assert web.looks_like_qmt_account_unit_key(sh_key)
    assert not web.looks_like_qmt_account_unit_key("0800514969")

    routes = web.normalize_market_bridge_config(
        {
            "SH": {
                "bridge_id": "acct_sh",
                "qmt_dir": r"D:\\qmt-sh",
                "position_account_key": sh_key,
                "shareholder_account_id": "B885307113",
            },
            "SZ": {"bridge_id": "acct_sz", "qmt_dir": r"D:\\qmt-sz", "query_account_id": sz_key},
        },
        account_id="77557115",
        account_type="STOCK",
        parent_bridge_id="acct_parent",
        enabled=True,
    )

    assert routes["SH"]["position_account_key"] == sh_key
    assert routes["SH"]["query_account_key"] == sh_key
    assert routes["SH"]["account_unit_key"] == sh_key
    assert routes["SH"]["position_account_id"] == "B885307113"
    assert routes["SH"]["query_account_id"] == "B885307113"
    assert routes["SZ"]["position_account_key"] == sz_key
    assert routes["SZ"]["query_account_key"] == sz_key
    assert routes["SZ"]["account_unit_key"] == sz_key
    assert routes["SZ"]["position_account_id"] == sz_key
    assert routes["SZ"]["query_account_id"] == sz_key


def test_market_account_positions_merge_keeps_numeric_sz_rows():
    result = web.merge_market_account_section(
        "positions",
        [
            {
                "market": "SH",
                "bridge_id": "acct_sh",
                "positions": {
                    "ok": True,
                    "data": [
                        {
                            "stock_code": "600000.SH",
                            "market": "0",
                            "volume": 100,
                        },
                    ],
                },
            },
            {
                "market": "SZ",
                "bridge_id": "acct_sz",
                "positions": {
                    "ok": True,
                    "data": [
                        {
                            "stock_code": "000001.SZ",
                            "market": "1",
                            "volume": 200,
                        },
                    ],
                },
            },
        ],
        time.perf_counter(),
    )

    assert result["ok"] is True
    assert result["market_counts"] == {"SH": 1, "SZ": 1}
    assert [row["stock_code"] for row in result["data"]] == ["600000.SH", "000001.SZ"]
    assert [row["source_market"] for row in result["data"]] == ["SH", "SZ"]


def test_account_data_cache_prewarm_tracks_configured_accounts_separately(monkeypatch):
    cache = web.AccountDataCache(interval=5, background_timeout=2)
    stale_key = ("old", "normal", "old:STOCK:000001", "000001", "STOCK")
    page_key = ("default", "normal", "default:STOCK:8885060548", "8885060548", "STOCK")
    cache._prewarm_subscriptions[stale_key] = {"asset"}
    cache._subscriptions[page_key] = {"orders"}
    monkeypatch.setattr(
        web,
        "enabled_account_configs",
        lambda: {
            "default:STOCK:8885060548": {
                "account_key": "default:STOCK:8885060548",
                "account_id": "8885060548",
                "account_type": "STOCK",
                "bridge_id": "default",
                "enabled": True,
                "mode": "ctypes",
            },
        },
    )
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})
    monkeypatch.setattr(web, "account_market_route_entries", lambda **kwargs: ({}, []))

    result = cache.prime_configured_accounts(sections=["asset", "positions"])
    key = ("default", "normal", "default:STOCK:8885060548", "8885060548", "STOCK")

    assert result == {
        "account_count": 1,
        "subscription_count": 1,
        "sections": ["asset", "positions"],
    }
    assert cache._prewarm_subscriptions[key] == {"asset", "positions"}
    assert stale_key not in cache._prewarm_subscriptions
    assert cache._subscriptions[page_key] == {"orders"}


def test_account_data_cache_prewarm_uses_trade_for_lttx_accounts(monkeypatch):
    cache = web.AccountDataCache(interval=5, background_timeout=2)
    monkeypatch.setattr(
        web,
        "enabled_account_configs",
        lambda: {
            "default:STOCK:8885060548": {
                "account_key": "default:STOCK:8885060548",
                "account_id": "8885060548",
                "account_type": "STOCK",
                "bridge_id": "default",
                "enabled": True,
                "mode": "lttx",
            },
        },
    )
    monkeypatch.setattr(web, "bridge_config", lambda bridge_id: {"name": bridge_id})
    monkeypatch.setattr(web, "account_market_route_entries", lambda **kwargs: ({}, []))

    result = cache.prime_configured_accounts(sections=["asset", "positions"])
    key = ("default", "trade", "default:STOCK:8885060548", "8885060548", "STOCK")

    assert result == {
        "account_count": 1,
        "subscription_count": 1,
        "sections": ["asset", "positions"],
    }
    assert cache._prewarm_subscriptions[key] == {"asset", "positions"}


def test_account_data_cache_uses_short_background_timeout(monkeypatch):
    cache = web.AccountDataCache(interval=5, background_timeout=2.5)
    cache._running = True
    cache._prewarm_subscriptions[("default", "normal", "default:STOCK:8885060548", "8885060548", "STOCK")] = {"asset"}
    calls = []

    def fake_query(bridge_id, channel, account_id, sections, **kwargs):
        calls.append((bridge_id, channel, account_id, list(sections), kwargs["timeout"]))
        return {"asset": {"ok": True, "data": {}}}

    monkeypatch.setattr(web, "query_account_live", fake_query)
    monkeypatch.setattr(cache, "_store_result", lambda *args, **kwargs: None)

    cache._refresh_subscriptions()

    assert calls == [("default", "normal", "8885060548", ["asset"], 2.5)]
