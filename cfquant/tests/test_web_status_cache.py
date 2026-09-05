# -*- coding: utf-8 -*-
import json
import subprocess
import time
from types import SimpleNamespace

import cfquant_web_server as web


def _status(online, mode):
    return {
        "normal": {"online": online, "channel": "%s.normal" % mode},
        "trade": {"online": online, "channel": "%s.trade" % mode},
        "monitor": {"ready": True, "cached": True, "transport_mode": mode},
    }


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
