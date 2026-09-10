"""Web account configuration integration with isolated state and deployment."""

import pytest


@pytest.fixture
def web_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CFQUANT_RUNTIME_DIR", str(tmp_path / "runtime"))
    import cfquant_web_server as web
    config = web.WebRuntimeConfig(str(tmp_path / "web.json"), str(tmp_path / "settings.db"))
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    return web, config


def test_web_persists_strategy_flags_and_preserves_them_for_older_clients(web_config, tmp_path):
    web, config = web_config
    row = config.save_account_config("1000000001", qmt_dir=str(tmp_path), qmt_strategy={
        "enabled": True, "live": True, "autorun": False})
    saved = config.save_account_config("1000000001", qmt_dir=str(tmp_path), display_name="Updated")
    assert saved["qmt_strategy"] == row["qmt_strategy"]
    reloaded = web.WebRuntimeConfig(config.path, config.settings_db_path)
    assert reloaded.account_configs()[row["account_key"]]["qmt_strategy"] == row["qmt_strategy"]


def test_same_qmt_same_fund_has_one_mode_across_path_aliases_and_bindings(web_config, tmp_path):
    web, config = web_config
    first = config.save_account_config("1000000001", bridge_id="first", qmt_dir=str(tmp_path), data_provider=True)
    other = config.save_account_config("1000000002", bridge_id="other", qmt_dir=str(tmp_path))
    second = config.save_account_config("1000000001", bridge_id="second", qmt_dir=str(tmp_path / "bin.x64"), mode="lite")
    rows = config.account_configs()
    assert rows[first["account_key"]]["enabled"] is False
    assert rows[first["account_key"]]["data_provider"] is False
    assert config.account_pairs()[first["account_key"]]["enabled"] is False
    assert rows[second["account_key"]]["enabled"] is True
    assert rows[other["account_key"]]["enabled"] is True
    assert config.setup_info()["default_account_key"] != first["account_key"]


def test_advanced_mode_cannot_use_two_aliases_for_one_qmt(web_config, tmp_path):
    _, config = web_config
    with pytest.raises(ValueError, match="QMT"):
        config.save_account_config("1000000001", mode="lttx", qmt_dir=str(tmp_path),
                                   qmt_trade_dir=str(tmp_path / "bin.x64"))


def test_managed_accounts_in_one_qmt_get_distinct_channels(web_config, tmp_path):
    _, config = web_config
    first = config.save_account_config("1000000001", qmt_dir=str(tmp_path), qmt_strategy={"enabled": True})
    second = config.save_account_config("1000000002", qmt_dir=str(tmp_path), qmt_strategy={"enabled": True})
    assert first["bridge_id"] != second["bridge_id"]
    assert all(row["enabled"] for row in config.account_configs().values())


def test_managed_market_routes_require_directories_before_saving(web_config, tmp_path):
    _, config = web_config
    original = config.save_account_config("1000000001", qmt_dir=str(tmp_path),
                                          qmt_strategy={"enabled": True})
    with pytest.raises(ValueError, match="SH/SZ"):
        config.save_account_config("1000000001", qmt_dir=str(tmp_path),
                                   market_routing_enabled=True, market_bridges={},
                                   qmt_strategy={"enabled": True})
    assert config.account_configs()[original["account_key"]] == original
    with pytest.raises(ValueError, match="SZ"):
        config.save_account_config("1000000001", qmt_dir=str(tmp_path),
                                   market_routing_enabled=True,
                                   market_bridges={"SH": {"qmt_dir": str(tmp_path)}})
    assert config.account_configs()[original["account_key"]] == original


def test_market_routes_can_be_disabled_without_resending_route_details(web_config, tmp_path):
    _, config = web_config
    original = config.save_account_config("1000000001", qmt_dir=str(tmp_path),
        market_routing_enabled=True,
        market_bridges={market: {"qmt_dir": str(tmp_path)} for market in ("SH", "SZ")},
        qmt_strategy={"enabled": True})
    unchanged = config.save_account_config("1000000001", qmt_dir=str(tmp_path))
    assert unchanged["market_bridges"] == original["market_bridges"]
    assert unchanged["market_routing_enabled"] is True
    disabled = config.save_account_config("1000000001", qmt_dir=str(tmp_path), market_routing_enabled=False)
    assert disabled["market_routing_enabled"] is False
    assert disabled["market_bridges"] == {}
    assert disabled["qmt_strategy"]["enabled"] is True


def test_save_and_delete_call_deployment_manager(web_config, monkeypatch):
    web, config = web_config
    calls = []
    class Manager:
        def reconcile(self, accounts):
            calls.append(("reconcile", set(accounts)))
        def configure(self, row, identities):
            calls.append(("configure", row["qmt_strategy"], identities))
            return {"enabled": True, "targets": [{"state": "waiting_exit"}]}
    monkeypatch.setattr(web, "QMT_STRATEGIES", Manager())
    monkeypatch.setattr(web, "auto_deploy_qmt_core_for_account", lambda *args, **kwargs: {})
    monkeypatch.setattr(web, "write_qmt_bridge_identity", lambda row: {"written": True, "path": "fake"})
    monkeypatch.setattr(web, "write_qmt_market_bridge_identities", lambda row: [])
    monkeypatch.setattr(web, "ensure_account_runtime", lambda mode: {})
    monkeypatch.setattr(web.ACCOUNT_CACHE, "prime_configured_accounts", lambda: None)
    monkeypatch.setattr(web.STATUS_MONITOR, "wake", lambda: None)
    monkeypatch.setattr(web.CALLBACKS, "refresh_channels", lambda channels: None)
    data = web.save_account_runtime_config({"account_id": "1000000001", "qmt_dir": "D:/FAKE-QMT",
                                           "qmt_strategy": {"enabled": True, "live": False, "autorun": True}})
    assert data["qmt_strategy_deploy"]["targets"][0]["state"] == "waiting_exit"
    assert calls[1][0] == "configure"
    assert calls[1][1]["autorun"] is True
    web.delete_account_runtime_config({"account_key": data["account"]["account_key"]})
    assert calls[-1] == ("reconcile", set())
