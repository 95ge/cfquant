"""Web account configuration integration with isolated state and deployment."""

import os

import pytest


@pytest.fixture
def web_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CFQUANT_RUNTIME_DIR", str(tmp_path / "runtime"))
    import cfquant_web_server as web
    config = web.WebRuntimeConfig(str(tmp_path / "web.json"), str(tmp_path / "settings.db"))
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    return web, config


def test_initialize_web_setup_can_skip_optional_admin_registration(web_config, monkeypatch, tmp_path):
    web, config = web_config
    monkeypatch.setattr(web, "auto_deploy_qmt_core_for_account", lambda *args, **kwargs: {
        "summary": {"ok": True},
        "results": [],
    })
    monkeypatch.setattr(web, "write_qmt_bridge_identity", lambda row: {"written": True, "path": "fake"})
    monkeypatch.setattr(web, "write_qmt_market_bridge_identities", lambda row: [])
    monkeypatch.setattr(web, "configure_account_qmt_strategies", lambda row, identity: {})
    monkeypatch.setattr(web, "qmt_auto_login_apply_for_account", lambda row, request=None: {
        "enabled": False,
    })
    monkeypatch.setattr(web, "ensure_account_runtime", lambda mode: {"mode": mode})

    data = web.initialize_web_setup({
        "account_id": "1000000001",
        "qmt_dir": str(tmp_path / "bin.x64"),
        "web_auth_enabled": False,
    })

    assert config.web_auth_enabled() is False
    assert data["server_access"]["web_auth_enabled"] is False
    assert data["web_auth"]["configured"] is False
    assert data["web_auth"]["username"] == ""
    assert data["setup"]["setup_required"] is False


def test_initialize_web_setup_persists_custom_python_environment(web_config, monkeypatch, tmp_path):
    web, config = web_config
    python_exe = tmp_path / "python.exe"
    python_exe.write_bytes(b"")
    monkeypatch.setattr(web, "auto_deploy_qmt_core_for_account", lambda *args, **kwargs: {"summary": {"ok": True}, "results": []})
    monkeypatch.setattr(web, "write_qmt_bridge_identity", lambda row: {"written": True})
    monkeypatch.setattr(web, "write_qmt_market_bridge_identities", lambda row: [])
    monkeypatch.setattr(web, "configure_account_qmt_strategies", lambda row, identity: {})
    monkeypatch.setattr(web, "qmt_auto_login_apply_for_account", lambda row, request=None: {"enabled": False})
    monkeypatch.setattr(web, "ensure_account_runtime", lambda mode: {"mode": mode})
    result = web.initialize_web_setup({
        "account_id": "1000000001",
        "python_environment": {"mode": "custom", "python_executable": str(python_exe)},
        "qmt_dir": str(tmp_path / "bin.x64"),
        "web_auth_enabled": False,
    })
    assert result["python_environment"]["mode"] == "custom"
    assert config.python_executable() == str(python_exe)
    assert web.PIPE_HUB._python_exe() == str(python_exe)


def test_web_reload_info_uses_target_port_and_preserves_previous_listener(web_config, monkeypatch):
    web, _ = web_config
    monkeypatch.setattr(web, "WEB_BOUND_HOST", "127.0.0.1")
    monkeypatch.setattr(web, "WEB_BOUND_PORT", 8765)
    monkeypatch.setattr(web, "server_access_info", lambda: {
        "configured_host": "0.0.0.0",
        "configured_port": 9876,
        "next_url": "http://127.0.0.1:9876/",
    })

    info = web.web_reload_info(reason="settings")

    assert info["host"] == "0.0.0.0"
    assert info["port"] == 9876
    assert info["previous_host"] == "127.0.0.1"
    assert info["previous_port"] == 8765


def test_spawn_reloaded_web_server_preserves_host_port_and_wait_env(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    calls = []

    class FakePopen:
        pid = 4321

        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))

    monkeypatch.setattr(web.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(web, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(web, "STATE_DIR", str(tmp_path))

    result = web.spawn_reloaded_web_server({
        "host": "0.0.0.0",
        "port": 9876,
        "next_url": "http://127.0.0.1:9876/",
    })

    assert result["pid"] == 4321
    command, kwargs = calls[0]
    assert command[0]
    if web.os.name == "nt" and os.path.isfile(os.path.join(web.BASE_DIR, "restart_cfquant.bat")):
        assert command[0].lower().endswith("cmd.exe")
        assert "restart_cfquant.bat" in command[-1]
    else:
        assert command[1].endswith("cfquant_web_server.py")
        assert command[command.index("--host") + 1] == "0.0.0.0"
        assert command[command.index("--port") + 1] == "9876"
    env = kwargs["env"]
    assert env["CFQUANT_WEB_HOST"] == "0.0.0.0"
    assert env["CFQUANT_WEB_PORT"] == "9876"
    assert env[web.WEB_RELOAD_WAIT_HOST_ENV] == "0.0.0.0"
    assert env[web.WEB_RELOAD_WAIT_PORT_ENV] == "9876"
    if web.os.name == "nt" and os.path.isfile(os.path.join(web.BASE_DIR, "restart_cfquant.bat")):
        assert env["CFQUANT_RESTART_NO_PAUSE"] == "1"
        assert env["CFQUANT_START_NO_PAUSE"] == "1"


def test_web_persists_strategy_flags_and_preserves_them_for_older_clients(web_config, tmp_path):
    web, config = web_config
    row = config.save_account_config("1000000001", qmt_dir=str(tmp_path), qmt_strategy={
        "enabled": True, "live": True, "autorun": False})
    saved = config.save_account_config("1000000001", qmt_dir=str(tmp_path), display_name="Updated")
    assert saved["qmt_strategy"] == row["qmt_strategy"]
    reloaded = web.WebRuntimeConfig(config.path, config.settings_db_path)
    assert reloaded.account_configs()[row["account_key"]]["qmt_strategy"] == row["qmt_strategy"]


def test_new_binding_defaults_strategy_to_live_mode(web_config, tmp_path):
    _, config = web_config
    row = config.save_account_config("1000000001", qmt_dir=str(tmp_path),
                                     qmt_strategy={"enabled": True})
    assert row["qmt_strategy"]["live"] is True


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


def test_set_data_provider_returns_complete_account_payload(web_config, tmp_path, monkeypatch):
    web, config = web_config
    first = config.save_account_config("1000000001", bridge_id="first", qmt_dir=str(tmp_path), data_provider=True)
    second = config.save_account_config("8885060548", bridge_id="default", qmt_dir=str(tmp_path / "guojin"))
    monkeypatch.setattr(web.ACCOUNT_CACHE, "prime_configured_accounts", lambda: None)
    monkeypatch.setattr(web.STATUS_MONITOR, "wake", lambda: None)
    monkeypatch.setattr(web.CALLBACKS, "refresh_channels", lambda channels: None)

    data = web.set_data_provider({"account_key": second["account_key"]})

    assert data["setup"]["data_provider_account_key"] == second["account_key"]
    assert data["account"]["account_id"] == "8885060548"
    assert data["account_configs"][first["account_key"]]["data_provider"] is False
    assert data["account_configs"][second["account_key"]]["data_provider"] is True
    assert data["bridges"]["default"]["python_dir"] == str(tmp_path / "guojin")


def test_disabled_account_cannot_be_set_as_data_provider(web_config, tmp_path, monkeypatch):
    web, config = web_config
    disabled = config.save_account_config("8885060548", qmt_dir=str(tmp_path), enabled=False)
    monkeypatch.setattr(web.ACCOUNT_CACHE, "prime_configured_accounts", lambda: None)
    monkeypatch.setattr(web.STATUS_MONITOR, "wake", lambda: None)
    monkeypatch.setattr(web.CALLBACKS, "refresh_channels", lambda channels: None)

    with pytest.raises(ValueError, match="disabled account"):
        web.set_data_provider({"account_key": disabled["account_key"]})


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


def test_save_can_start_qmt_auto_login_and_persist_restart_times(web_config, monkeypatch):
    web, config = web_config
    calls = []
    monkeypatch.setattr(web, "auto_deploy_qmt_core_for_account", lambda *args, **kwargs: {})
    monkeypatch.setattr(web, "write_qmt_bridge_identity", lambda row: {"written": True, "path": "fake"})
    monkeypatch.setattr(web, "write_qmt_market_bridge_identities", lambda row: [])
    monkeypatch.setattr(web, "configure_account_qmt_strategies", lambda row, identity: {})
    monkeypatch.setattr(web, "ensure_account_runtime", lambda mode: {})
    monkeypatch.setattr(web.ACCOUNT_CACHE, "prime_configured_accounts", lambda: None)
    monkeypatch.setattr(web.STATUS_MONITOR, "wake", lambda: None)
    monkeypatch.setattr(web.CALLBACKS, "refresh_channels", lambda channels: None)

    def apply(row, request=None):
        calls.append((row["account_id"], request, row["qmt_auto_login"]))
        return {"enabled": True, "started": True, "pid": 1234,
                "restart_times": row["qmt_auto_login"]["restart_times"]}

    monkeypatch.setattr(web, "qmt_auto_login_apply_for_account", apply)
    data = web.save_account_runtime_config({
        "account_id": "8885060548",
        "display_name": "国金证券",
        "qmt_dir": r"D:\国金证券QMT交易端\bin.x64",
        "qmt_auto_login": {"enabled": True, "restart_times": ["6:30", "06:30", "18:05"]},
    })
    assert data["qmt_auto_login"]["pid"] == 1234
    assert data["account"]["qmt_auto_login"] == {"enabled": True, "restart_times": ["06:30", "18:05"]}
    assert calls == [("8885060548", {"enabled": True, "restart_times": ["6:30", "06:30", "18:05"]},
                      {"enabled": True, "restart_times": ["06:30", "18:05"]})]


def test_complete_qmt_auto_login_restarts_saved_account(web_config, monkeypatch, tmp_path):
    web, config = web_config
    row = config.save_account_config(
        "8885060548",
        qmt_dir=str(tmp_path),
        display_name="国金证券",
        qmt_auto_login={"enabled": True, "restart_times": ["07:30"]},
    )
    calls = []
    monkeypatch.setattr(web, "qmt_auto_login_restart_for_account",
                        lambda account, request=None, reason="manual": calls.append((account["account_key"], request, reason)) or {"restarted": True})
    data = web.complete_qmt_auto_login({"account_key": row["account_key"]})
    assert data["restarted"] is True
    assert calls == [(row["account_key"], {"enabled": True, "restart_times": ["07:30"]}, "manual")]


def test_reset_web_auth_password_writes_file_and_revokes_old_session(web_config, monkeypatch, tmp_path):
    web, config = web_config
    monkeypatch.setattr(web, "BASE_DIR", str(tmp_path / "project"))
    config.set_server_access_settings(
        web_auth_enabled=True,
        web_auth_username="operator",
        web_auth_password="old-password",
    )
    token = web.issue_web_auth_token("operator", remember=True)
    assert config.verify_web_auth("operator", "old-password")
    assert web.web_auth_token_info(token)

    result = config.reset_web_auth_password()

    password_file = tmp_path / "project" / "cfquant_web_reset_password.txt"
    assert result["password_file"] == str(password_file)
    assert config.server_access_info()["web_auth_password_file"] == str(password_file)
    assert password_file.is_file()
    content = password_file.read_text(encoding="utf-8")
    new_password = content.split("新密码: ", 1)[1].splitlines()[0]
    assert len(new_password) == 18
    assert new_password != "old-password"
    assert not config.verify_web_auth("operator", "old-password")
    assert config.verify_web_auth("operator", new_password)
    assert web.web_auth_token_info(token) is None


def test_reset_web_auth_password_enables_auth_when_it_was_not_configured(web_config, monkeypatch, tmp_path):
    web, config = web_config
    monkeypatch.setattr(web, "BASE_DIR", str(tmp_path / "project"))
    result = config.reset_web_auth_password()
    password_file = tmp_path / "project" / "cfquant_web_reset_password.txt"
    new_password = password_file.read_text(encoding="utf-8").split("新密码: ", 1)[1].splitlines()[0]
    assert result["username"] == "admin"
    assert config.web_auth_enabled()
    assert config.verify_web_auth("admin", new_password)


def test_qmt_process_snapshot_matches_directory_and_reports_pids(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    qmt_bin = tmp_path / "QMT" / "bin.x64"
    qmt_bin.mkdir(parents=True)
    (qmt_bin / "XtItClient.exe").write_bytes(b"")
    monkeypatch.setattr(web, "_qmt_auto_login_processes", lambda path: [{
        "pid": 2718,
        "name": "XtItClient.exe",
        "executable_path": os.path.join(str(path), "XtItClient.exe"),
    }])
    result = web.qmt_process_snapshot(str(qmt_bin.parent))
    assert result["running"] is True
    assert result["pids"] == [2718]
    assert result["exe_path"].lower().endswith("bin.x64\\xtitclient.exe")


def test_qmt_process_preflight_rejects_running_strategy_before_mutation(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    calls = []
    monkeypatch.setattr(web, "qmt_process_snapshots_for_request", lambda **kwargs: [{
        "qmt_dir": str(tmp_path), "running": True, "pids": [1234],
    }])
    with pytest.raises(RuntimeError, match="PID 1234"):
        web.qmt_process_preflight(body={
            "qmt_dir": str(tmp_path),
            "qmt_strategy": {"enabled": True},
        })
    assert calls == []


def test_qmt_process_snapshot_request_uses_saved_row_when_body_has_only_account_key(web_config, monkeypatch, tmp_path):
    web, _ = web_config
    captured = []
    monkeypatch.setattr(web, "qmt_process_snapshot", lambda path: captured.append(path) or {"running": False})
    web.qmt_process_snapshots_for_request(
        body={"account_key": "900010001595"},
        row={"qmt_dir": str(tmp_path / "QMT")},
    )
    assert captured == [web.normalize_optional_path(str(tmp_path / "QMT"))]
