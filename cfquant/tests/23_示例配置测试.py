# -*- coding: utf-8 -*-
"""Offline example configuration checks; no QMT connection or real orders."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


DIRECTORY = Path(__file__).parent
MANUAL_NUMBERS = (1, 2, 3, 4, 5, 6, 7, 8, 18, 21, 29)


def source_path(number):
    return next(DIRECTORY.glob("%s_*.py" % number))


def load_script(number, monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    spec = importlib.util.spec_from_file_location("manual_config_%s" % number, source_path(number))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "configure_stdout"):
        monkeypatch.setattr(module, "configure_stdout", lambda: None)
    return module


@pytest.mark.parametrize("number", MANUAL_NUMBERS)
def test_manual_examples_do_not_read_command_line(number):
    source = source_path(number).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "用户配置区" in source
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "argparse" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "argparse"
            assert not (node.module == "sys" and any(alias.name == "argv" for alias in node.names))
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("parse_args", "parse_known_args", "argv")


class ConfigurationCaptured(Exception):
    pass


@pytest.mark.parametrize("number", (1, 2, 3, 4, 5, 6, 8, 21))
def test_main_uses_edited_configuration_and_ignores_argv(number, monkeypatch):
    module = load_script(number, monkeypatch)
    monkeypatch.setattr(module, "TRANSPORT", "ctypes")
    monkeypatch.setattr(module, "BRIDGE_ID", "test_bridge")
    monkeypatch.setattr(module, "REQUEST_TIMEOUT", 2.5)
    if hasattr(module, "ACCOUNT_ID"):
        monkeypatch.setattr(module, "ACCOUNT_ID", "test_account")
    if hasattr(module, "default_account_id"):
        monkeypatch.setattr(module, "default_account_id", lambda: pytest.fail("explicit code account must win"))
    if hasattr(module, "discover_data_provider_route"):
        monkeypatch.setattr(module, "discover_data_provider_route", lambda: pytest.fail("explicit transport must win"))
    monkeypatch.setattr(sys, "argv", ["manual.py", "--obsolete-option"])
    captured = {}

    def capture(config=None, **kwargs):
        captured.update(vars(config) if config is not None else kwargs)
        raise ConfigurationCaptured()

    monkeypatch.setattr(module, "configure" if number == 21 else "configure_cfquant", capture)
    with pytest.raises(ConfigurationCaptured):
        module.main()
    assert captured["transport"] == "ctypes"
    assert captured["bridge_id"] == "test_bridge"
    assert captured["timeout"] == 2.5
    if number != 21:
        tree = ast.parse(source_path(number).read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        snapshot = next(node for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "SimpleNamespace")
        for keyword in snapshot.keywords:
            assert captured[keyword.arg] == getattr(module, keyword.value.id)


def test_order_preview_reflects_code_values_without_connecting(monkeypatch, capsys):
    module = load_script(5, monkeypatch)
    for name, value in {
        "ACCOUNT_ID": "paper-test", "STOCK_CODE": "600000.SH", "SIDE": "sell",
        "PRICE": 7.25, "VOLUME": 200, "DRY_RUN": True, "JSON_OUTPUT": True,
        "REQUIRE_CONFIRM": True, "CONFIRM_TEXT": "", "REQUEST_TIMEOUT": 2.5,
    }.items():
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module, "configure_cfquant", lambda config: pytest.fail("preview must not configure a client"))
    monkeypatch.setattr(module, "XtQuantTrader", lambda **kwargs: pytest.fail("preview must not create a trader"))
    assert module.main() == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    config = next(row["order_config"] for row in records if row.get("type") == "start")
    assert (config["account_id"], config["stock_code"], config["side"]) == ("paper-test", "600000.SH", "sell")
    assert (config["price"], config["volume"], config["request_timeout_ms"]) == (7.25, 200, 2500.0)


@pytest.mark.parametrize("overrides", [
    {"SIDE": "invalid"}, {"PRICE": 0}, {"VOLUME": 0}, {"ACCOUNT_ID": ""},
    {"REQUIRE_CONFIRM": True, "CONFIRM_TEXT": "mismatch"},
])
def test_order_validation_and_confirmation_prevent_connection(overrides, monkeypatch):
    module = load_script(5, monkeypatch)
    for name, value in overrides.items():
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module, "configure_cfquant", lambda config: pytest.fail("invalid config must not connect"))
    monkeypatch.setattr(module, "XtQuantTrader", lambda **kwargs: pytest.fail("invalid config must not create a trader"))
    assert module.main() == 2


@pytest.mark.parametrize("submit,confirmed,expected_result,expected_orders", [
    (False, False, 0, 0), (True, False, 2, 0), (True, True, 0, 1),
])
def test_optional_order_requires_both_code_guards(submit, confirmed, expected_result, expected_orders, monkeypatch):
    module = load_script(4, monkeypatch)
    calls = []
    disconnected = []

    class FakeTrader:
        def __init__(self, **kwargs):
            pass

        def connect(self):
            return 0

        def disconnect(self):
            disconnected.append(True)

        def order_stock(self, *args):
            calls.append(args)
            return "fake-order"

        def __getattr__(self, name):
            assert name.startswith("query_")
            return lambda *args, **kwargs: []

    for name, value in {
        "ACCOUNT_ID": "paper-test", "SUBMIT_ORDER": submit, "ORDER_STOCK_CODE": "000001.SZ",
        "ORDER_PRICE": 11.6, "ORDER_VOLUME": 100,
        "ORDER_CONFIRM_TEXT": "ORDER BUY 000001.SZ 100 @ 11.600" if confirmed else "",
    }.items():
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module, "configure_cfquant", lambda config: None)
    monkeypatch.setattr(module, "close_trade_client", lambda: None)
    monkeypatch.setattr(module, "XtQuantTrader", FakeTrader)
    assert module.main() == expected_result
    assert len(calls) == expected_orders
    assert disconnected == [True]
    if calls:
        account, stock, side, volume, price_type, price, *_ = calls[0]
        assert account.account_id == "paper-test"
        assert (stock, side, volume, price_type, price) == ("000001.SZ", module.STOCK_BUY, 100, module.FIX_PRICE, 11.6)


def test_negative_query_row_limit_is_rejected_without_connecting(monkeypatch):
    module = load_script(8, monkeypatch)
    monkeypatch.setattr(module, "ACCOUNT_ID", "paper-test")
    monkeypatch.setattr(module, "MAX_ROWS", -1)
    monkeypatch.setattr(module, "configure_cfquant", lambda config: pytest.fail("invalid config must not connect"))
    assert module.main() == 2


@pytest.mark.parametrize("account,skip,confirmation", [("", True, ""), ("paper-test", False, "mismatch")])
def test_integration_requires_explicit_account_and_paper_confirmation(account, skip, confirmation, monkeypatch):
    module = load_script(18, monkeypatch)
    assert module.SKIP_ORDER is True
    monkeypatch.setattr(module, "ACCOUNT_ID", account)
    monkeypatch.setattr(module, "SKIP_ORDER", skip)
    monkeypatch.setattr(module, "CONFIRM_SIMULATION", confirmation)
    monkeypatch.setattr(module, "configure", lambda **kwargs: pytest.fail("invalid config must not connect"))
    with pytest.raises(ValueError):
        module.main()


def test_integration_auto_report_directories_are_unique_and_preserved(monkeypatch, tmp_path):
    module = load_script(18, monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "ACCOUNT_ID", "paper-test")
    monkeypatch.setattr(module.sys, "stdout", SimpleNamespace(reconfigure=lambda **kwargs: None))
    path = tmp_path / "runtime/config/cfquant_web_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "default_account_id": "paper-test",
        "account_configs": {"default:STOCK:paper-test": {"mode": "lttx", "enabled": True}},
    }), encoding="utf-8")
    runs = []
    original_run = module.Run

    def capture_run(directory, account_id):
        run = original_run(directory, account_id)
        runs.append(run)
        return run

    def stop_before_connect(**kwargs):
        raise ConfigurationCaptured()

    monkeypatch.setattr(module, "Run", capture_run)
    monkeypatch.setattr(module, "configure", stop_before_connect)
    for _ in range(2):
        with pytest.raises(ConfigurationCaptured):
            module.main()
    assert runs[0].directory != runs[1].directory
    for run in runs:
        assert run.directory.parent == tmp_path / "private_docs"
        assert run.order["simulation_confirmed"] is False
        assert run.order["submitted"] is False
        run.save()
        report = (run.directory / "高级模式接口与回调测试报告.md").read_text(encoding="utf-8")
        assert "本次未确认模拟账号属性" in report
    monkeypatch.setattr(module, "OUTPUT_DIR", str(runs[0].directory))
    with pytest.raises(ValueError, match="preserve"):
        module.main()
