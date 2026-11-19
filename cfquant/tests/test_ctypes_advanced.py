"""Two-terminal ctypes deployments, using disposable QMT trees only."""

import ast
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cfquant.qmt_strategy_deploy import account_qmt_roots, read_entry_source, PipeStrategyController, strategy_request_channel
from cfquant.tests.test_qmt_strategy_deploy import deployment, SCRIPTS, _write_json
from cfquant.tests.test_lite_deployment_paths import package_source
from cfquant.tests.test_qmt_strategy_web import web_config


@pytest.mark.parametrize("action,expected", [
    ("xtdata.get_full_tick", "normal"),
    ("xtdata.download_history_data", "normal"),
    ("xtdata.subscribe_quote", "normal"),
    ("xttrader.subscribe", "normal"),
    ("xttrader.unsubscribe", "normal"),
    ("cfquant.account_subscription_status", "normal"),
    ("xttrader.order_stock", "trade"),
    ("xttrader.cancel_order_stock", "trade"),
    ("xttrader.query_stock_positions", "trade"),
    ("cfquant.query_info", "trade"),
])
def test_split_routing_overrides_user_channel(web_config, action, expected):
    web, _ = web_config
    assert web.transport_client_mode("lite_advanced") == "ctypes"
    assert web.route_channel_for_account("test", requested_channel="trade" if expected == "normal" else "normal",
        mode="lite_advanced", action=action) == expected
    assert web.action_channel_attempts(action, None, expected, mode="lite_advanced") == [expected]


def test_split_config_roundtrip_and_two_identity_files(web_config, tmp_path, monkeypatch):
    web, config = web_config
    normal, trade = tmp_path / "normal", tmp_path / "trade"
    normal.mkdir()
    trade.mkdir()
    monkeypatch.setattr(web, "UPDATER", SimpleNamespace(_target_paths=lambda directory: {"python_dir": directory}))
    kwargs = dict(account_id="fixture", qmt_dir=str(normal), qmt_trade_dir=str(trade),
        mode="lite_advanced", qmt_auto_login={"enabled": False}, qmt_strategy={"enabled": False})
    row = config.save_account_config(**kwargs)
    assert config.account_config(account_key=row["account_key"])["mode"] == "lite_advanced"
    assert web.default_runtime_client_mode() == "lite_advanced"
    assert len(account_qmt_roots(row)) == 2
    targets = []
    def install(directory, **kwargs):
        targets.append(dict(kwargs, qmt_dir=directory))
        return {"updated": True}
    monkeypatch.setattr(web.UPDATER, "install_local_core_to_qmt_dir", install, raising=False)
    monkeypatch.setattr(web, "_deploy_qmt_entry_for_target", lambda *args: None)
    web.auto_deploy_qmt_core_for_account(row)
    assert {target["qmt_role"] for target in targets} == {"normal", "trade"}
    identity = web.write_qmt_bridge_identity(row)
    for role, info in (("normal", identity), ("trade", identity["trade_identity"])):
        assert info["written"]
        payload = json.loads(Path(info["path"]).read_text(encoding="utf-8"))
        assert payload["qmt_role"] == role
        assert payload["mode"] == "lite_advanced"
    with pytest.raises(ValueError, match="不同"):
        config.save_account_config(**dict(kwargs, qmt_trade_dir=str(normal)))
    with pytest.raises(ValueError, match="交易端"):
        config.save_account_config(**dict(kwargs, qmt_trade_dir=""))
    with pytest.raises(ValueError, match="独立市场"):
        config.save_account_config(**dict(kwargs, market_routing_enabled=True))
    # Legacy socket configurations keep their existing transport and entry files.
    socket = config.save_account_config(**dict(kwargs, mode="lttx"))
    assert web.qmt_entry_script_name_for_target(socket["mode"], "trade") == "CFQUANT_TRADE_LOWLAT.py"


def test_two_generated_packages_embed_distinct_roles(deployment):
    manager, row, infos, _, root = deployment
    trade = root.parent / "trade"
    shutil.copytree(root, trade)
    row.update(mode="lite_advanced", qmt_trade_dir=str(trade / "bin.x64"))
    first = json.loads(Path(infos[0]["path"]).read_text(encoding="utf-8"))
    first.update(mode="lite_advanced", qmt_role="normal", qmt_trade_dir=row["qmt_trade_dir"])
    _write_json(infos[0]["path"], first)
    trade_identity = trade / "bin.x64" / "cfquant_bridge_config.json"
    _write_json(trade_identity, dict(first, qmt_role="trade"))
    infos.append(dict(written=True, core_dir=str(trade / "bin.x64"), path=str(trade_identity), qmt_role="trade"))
    manager.configure(row, infos)
    assert len(manager.jobs) == 2
    roles = set()
    for job in manager.jobs.values():
        assert job["mode"] == "lite_advanced"
        role = job["roles"][0]
        roles.add(role["role"])
        source = package_source(Path(role["package_path"]))
        tree = ast.parse(source, feature_version=(3, 6))
        config = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "EMBEDDED_RUNTIME_CONFIG" for target in node.targets))
        assert config["qmt_role"] == role["role"]
        assert config["mode"] == "lite_advanced"
        assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cfquant") for node in ast.walk(tree))
    assert roles == {"normal", "trade"}


def test_strategy_control_uses_the_trade_process_endpoint(monkeypatch):
    from cfquant import pipe_client
    client_factory = Mock()
    monkeypatch.setattr(pipe_client, "PipeRpcClient", client_factory)
    controller = PipeStrategyController()
    identity = dict(mode="lite_advanced", qmt_role="trade", pipe_name="test",
        channels={"normal": "quotes", "trade": "orders"})
    assert strategy_request_channel(identity) == "orders"
    assert strategy_request_channel(dict(identity, qmt_role="normal")) == "quotes"
    controller(identity, {"enabled": True})
    assert client_factory.call_args.kwargs["request_channel"] == "orders"
    client_factory.return_value.request.assert_called_once_with("cfquant.strategy.control", {"enabled": True})


@pytest.mark.parametrize("path", sorted(SCRIPTS.rglob("CFQUANT_LITE*.py")), ids=lambda path: path.stem)
def test_channel_ownership_and_callback_deduplication(path):
    tree = ast.parse(read_entry_source(path))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name in ("lite_role_settings", "configure_lite_role_callbacks")]
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    layout = namespace["lite_role_settings"]
    channels = {"normal": "quotes", "trade": "orders"}
    assert layout({"mode": "lite"}, channels) == ("combined", "quotes")
    assert layout({"mode": "lite_advanced", "qmt_role": "normal"}, channels) == ("normal", "quotes")
    assert layout({"mode": "lite_advanced", "qmt_role": "trade"}, channels) == ("trade", "orders")
    with pytest.raises(ValueError):
        layout({"mode": "lite_advanced", "qmt_role": "unknown"}, channels)
    normal, trade = Mock(), Mock()
    configure = namespace["configure_lite_role_callbacks"]
    configure(normal, "normal")
    normal.publish_callback_event("trader:on_stock_order", {})
    normal.publish_callback_event.assert_called_once()
    public_callback = trade.publish_callback_event
    configure(trade, "trade")
    trade.publish_callback_event("trader:on_stock_order", {})
    trade._resolve_pending_sync_order_callback.assert_called_once()
    trade._handle_async_order_callback.assert_called_once()
    trade.publish_callback_event("trader:on_stock_trade", {})
    public_callback.assert_not_called()


@pytest.mark.parametrize("path", sorted(SCRIPTS.rglob("CFQUANT_LITE*.py")), ids=lambda path: path.stem)
@pytest.mark.parametrize("mode,role,channel", [
    ("lite", "normal", "quotes"),
    ("lite_advanced", "normal", "quotes"),
    ("lite_advanced", "trade", "orders"),
])
def test_real_entry_startup_owns_only_its_assigned_channel(path, mode, role, channel):
    tree = ast.parse(read_entry_source(path))
    start = next(index for index, node in enumerate(tree.body) if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Tuple)
        and any(isinstance(target, ast.Name) and target.id == "_LITE_ROLE" for target in node.targets[0].elts))
    startup = tree.body[start:]
    end = next(index for index, node in enumerate(startup) if isinstance(node, ast.Try))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name in ("lite_role_settings", "configure_lite_role_callbacks")]
    normal_factory, trade_factory = Mock(), Mock()
    namespace = dict(RUNTIME_CONFIG={"mode": mode, "qmt_role": role},
        BRIDGE_CHANNELS={"normal": "quotes", "trade": "orders", "callback": "callbacks"},
        ManagedPipeRuntime=Mock(), start_pipe_normal_bridge=normal_factory, start_pipe_trade_bridge=trade_factory,
        PIPE_NAME="test", BRIDGE_ID="test", DEFAULT_ACCOUNT_ID="test", DEFAULT_ACCOUNT_TYPE="STOCK",
        NORMAL_PUMP_MAX_COUNT=20, NORMAL_PUMP_MAX_MS=0, PIPE_CONNECT_TIMEOUT_MS=100)
    exec(compile(ast.Module(body=functions + startup[:end + 1], type_ignores=[]), str(path), "exec"), namespace)
    assert normal_factory.call_args.kwargs["request_channel"] == channel
    assert normal_factory.call_args.kwargs["request_channels"] == [channel]
    assert trade_factory.call_count == (1 if mode == "lite" else 0)
    if mode == "lite_advanced":
        assert namespace["_trade_bridge"] is None
