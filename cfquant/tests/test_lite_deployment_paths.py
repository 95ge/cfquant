"""Verify the bytes copied and imported for Lite across binding/update paths."""

import ast
import json
from pathlib import Path
import shutil

import pytest

from cfquant.qmt_strategy_deploy import QmtStrategyManager
from cfquant.qmt_strategy_package import _cipher
from cfquant.tests.test_qmt_strategy_deploy import deployment, finish_import, models, SCRIPTS


def embedded_source(package):
    content = json.loads(_cipher().decrypt(package.read_bytes()).decode("utf-8", "surrogateescape"))["content"]
    return next(node.args[0].value for node in ast.walk(ast.parse(content))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "compile" and isinstance(node.args[0], ast.Constant))


def assert_lite_package(manager, root):
    job = next(job for job in manager.jobs.values() if job.get("enabled"))
    assert job["mode"] == "lite"
    for role in job["roles"]:
        source = embedded_source(root / "formulas" / (role["name"] + ".rzrk"))
        assert "LITE_ENTRY_VERSION =" in source
        assert "def account_route_client_ids(" in source
        assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cfquant")
                       for node in ast.walk(ast.parse(source)))
        assert Path(role["source"]).name.startswith("CFQUANT_LITE")
    return job


@pytest.fixture
def web_deployment(deployment, tmp_path, monkeypatch):
    import cfquant_web_server as web
    manager, row, infos, running, root = deployment
    config = web.WebRuntimeConfig(str(tmp_path / "web.json"), str(tmp_path / "web.db"))
    config._data["account_configs"] = {row["account_key"]: row}
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "BASE_DIR", str(SCRIPTS.parent))
    monkeypatch.setattr(web, "QMT_STRATEGIES", manager)
    updater = web.CfquantUpdater(config)
    monkeypatch.setattr(updater, "install_local_core_to_qmt_dir", lambda *args, **kwargs: {"skipped": True})
    monkeypatch.setattr(web, "UPDATER", updater)
    monkeypatch.setattr(web, "write_qmt_bridge_identity", lambda row: dict(infos[0]))
    monkeypatch.setattr(web, "write_qmt_market_bridge_identities", lambda row: [])
    monkeypatch.setattr(web, "sync_qmt_bridge_identities", lambda: [])
    monkeypatch.setattr(web, "qmt_process_preflight", lambda **kwargs: None)
    monkeypatch.setattr(web, "qmt_auto_login_apply_for_account", lambda *args, **kwargs: {})
    monkeypatch.setattr(web, "ensure_account_runtime", lambda mode: {})
    monkeypatch.setattr(web.ACCOUNT_CACHE, "prime_configured_accounts", lambda: None)
    monkeypatch.setattr(web.STATUS_MONITOR, "wake", lambda: None)
    monkeypatch.setattr(web.CALLBACKS, "refresh_channels", lambda channels: None)
    return web, manager, row, infos, root


@pytest.mark.parametrize("action", ["bind", "account_update", "project_update", "startup"])
def test_selected_lite_replaces_imported_generic_code(action, web_deployment, monkeypatch):
    web, manager, row, infos, root = web_deployment
    manager.configure(row, infos)
    finish_import(manager, root)
    manager.process_once()
    generic_name = next(iter(manager.jobs.values()))["roles"][0]["name"]
    # Simulate an older installation with a Lite binding and a generic import.
    row["mode"] = "lite"
    if action == "bind":
        result = web.save_account_runtime_config({
            key: row[key] for key in ("account_id", "account_type", "bridge_id", "qmt_dir", "mode")})
        assert result["account"]["mode"] == "lite"
        assert not result["qmt_strategy_deploy"].get("error")
    elif action == "account_update":
        monkeypatch.setattr(web, "account_config_for_request", lambda body: row)
        result = web.update_account_qmt_core({"account_key": row["account_key"]})
        assert not result["qmt_strategy_deploy"].get("error")
    elif action == "project_update":
        result = web.auto_deploy_qmt_core_for_all_accounts(str(SCRIPTS.parent), sync_entry_scripts=True)
        assert result["summary"]["ok"]
    else:
        # Persisted jobs must be repaired on first start after an old updater.
        manager = QmtStrategyManager(manager.path, SCRIPTS, lambda root: False)
        monkeypatch.setattr(web, "QMT_STRATEGIES", manager)
        result = web.refresh_bound_qmt_strategies()
        assert not result[0].get("error")
    assert_lite_package(manager, root)
    assert models(root)[generic_name].getAttribute("startupAutorun") == "0"
    if action != "startup":
        assert (root / "python" / "CFQUANT_LITE.py").read_bytes() == (SCRIPTS / "CFQUANT_LITE.py").read_bytes()


def test_edit_without_mode_preserves_lite_binding_and_payload(web_deployment):
    web, manager, row, _, root = web_deployment
    row["mode"] = "lite"
    result = web.save_account_runtime_config({
        key: row[key] for key in ("account_id", "account_type", "bridge_id", "qmt_dir")})
    assert result["account"]["mode"] == "lite"
    assert_lite_package(manager, root)


def test_edit_advanced_binding_to_lite_retires_both_advanced_models(web_deployment):
    web, manager, row, infos, root = web_deployment
    trade_root = root.with_name("QMT_trade")
    shutil.copytree(root, trade_root)
    row.update(mode="lttx", qmt_trade_dir=str(trade_root / "bin.x64"))
    row["qmt_strategy"]["autorun"] = True
    trade_info = dict(infos[0], qmt_role="trade", core_dir=str(trade_root / "bin.x64"),
                      path=str(trade_root / "bin.x64" / "cfquant_bridge_config.json"))
    manager.configure(row, infos + [trade_info])
    advanced_name = "CFQ_%s_LTTX" % row["account_id"]
    assert models(root)[advanced_name].getAttribute("startupAutorun") == "1"
    assert models(trade_root)[advanced_name].getAttribute("startupAutorun") == "1"

    body = {key: row[key] for key in ("account_id", "account_type", "bridge_id", "qmt_dir")}
    result = web.save_account_runtime_config(dict(body, mode="lite", qmt_trade_dir=""))

    assert result["account"]["mode"] == "lite"
    assert result["account"]["qmt_trade_dir"] == ""
    assert not result["qmt_strategy_deploy"].get("error")
    job = assert_lite_package(manager, root)
    assert job["roles"][0]["name"] == "CFQ_%s_LITE" % row["account_id"]
    assert models(root)[job["roles"][0]["name"]].getAttribute("startupAutorun") == "1"
    assert models(root)[advanced_name].getAttribute("startupAutorun") == "0"
    assert models(trade_root)[advanced_name].getAttribute("startupAutorun") == "0"
    trade_job = next(job for job in manager.jobs.values() if job["root"] == str(trade_root))
    assert trade_job["enabled"] is False
    assert trade_job["state"] == "disabled"


@pytest.mark.parametrize("single_account", [False, True])
def test_shared_qmt_directory_does_not_drop_lite_market_entries(single_account, web_deployment):
    web, _, row, _, root = web_deployment
    row.update(mode="lite", market_routing_enabled=True,
               qmt_strategy={"enabled": False}, market_bridges={
                   market: {"qmt_dir": str(root), "bridge_id": "bridge_" + market}
                   for market in ("SH", "SZ")})
    if single_account:
        result = web.auto_deploy_qmt_core_for_account(row)
    else:
        # The earlier binding must not win solely because it shares a directory.
        generic = dict(row, account_key="generic", account_id="222", mode="ctypes", market_routing_enabled=False)
        web.WEB_CONFIG._data["account_configs"] = {"generic": generic, row["account_key"]: row}
        result = web.auto_deploy_qmt_core_for_all_accounts(str(SCRIPTS.parent), sync_entry_scripts=True)
    assert result["summary"]["ok"]
    for name, directory in (("CFQUANT_LITE.py", SCRIPTS),
                            ("CFQUANT_LITE_SH.py", SCRIPTS / "同账号独立市场"),
                            ("CFQUANT_LITE_SZ.py", SCRIPTS / "同账号独立市场")):
        assert (root / "python" / name).read_bytes() == (directory / name).read_bytes()


def test_update_uses_new_source_and_rejects_mislabeled_generic_entry(web_deployment, tmp_path):
    web, manager, row, _, root = web_deployment
    row["mode"] = "lite"
    source = tmp_path / "updated_project"
    (source / "qmt_scripts").mkdir(parents=True)
    entry = source / "qmt_scripts" / "CFQUANT_LITE.py"
    entry.write_bytes((SCRIPTS / entry.name).read_bytes() + b'\nRELEASE_TEST_MARKER = "new-source"\n')
    result = web.auto_deploy_qmt_core_for_all_accounts(str(source), sync_entry_scripts=True)
    assert result["summary"]["ok"]
    job = assert_lite_package(manager, root)
    assert 'RELEASE_TEST_MARKER = "new-source"' in embedded_source(
        root / "formulas" / (job["roles"][0]["name"] + ".rzrk"))
    previous = (root / "python" / entry.name).read_bytes()
    shutil.copyfile(SCRIPTS / "CFQUANT_CTYPE_ALL_LOWLAT.py", entry)
    result = web.auto_deploy_qmt_core_for_all_accounts(str(source), sync_entry_scripts=True)
    assert not result["summary"]["ok"]
    assert result["summary"]["strategy_error_count"] == 1
    assert "通用模式代码" in result["summary"]["message"]
    assert (root / "python" / entry.name).read_bytes() == previous
