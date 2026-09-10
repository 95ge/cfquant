# -*- coding: utf-8 -*-
"""Offline connection and code-configuration guards; no real RPC or orders."""
import importlib.util
import json
from pathlib import Path

import pytest

from cfquant.client import CfquantError, CfquantTimeout
from cfquant.xttrader import XtQuantTrader


@pytest.mark.parametrize("failure_stage,error", [
    ("start", CfquantError("xttrader.subscribe: reconnect cooldown 23.6s")),
    ("start", TypeError("super(type, obj): obj must be an instance or subtype of type")),
    ("ping", CfquantTimeout("cfquant.ping timeout")),
])
def test_connect_exposes_failure_without_changing_return_contract(failure_stage, error):
    trader = XtQuantTrader()

    def start():
        if failure_stage == "start":
            raise error

    def request(action, timeout=None):
        assert action == "cfquant.ping"
        assert timeout == 3
        raise error

    trader.start = start
    trader._trade_request = request
    try:
        assert trader.connect() == -1
        assert trader.connected is False
        assert trader.last_connect_error == str(error)
        assert trader.last_connect_error_type == type(error).__name__
        assert trader.last_connect_stage == failure_stage
        trader.start = lambda: None
        trader._trade_request = lambda *args, **kwargs: {"pong": True}
        assert trader.connect() == 0
        assert trader.connected is True
        assert trader.last_connect_error == ""
        assert trader.last_connect_error_type == ""
        assert trader.last_connect_stage == ""
    finally:
        trader.stop()


@pytest.fixture
def script(monkeypatch):
    directory = Path(__file__).parent
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("real_order_connection_test", directory / "5_真实下单测试.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configure_stdout", lambda: None)
    monkeypatch.setattr(module, "configure_cfquant", lambda args: None)
    monkeypatch.setattr(module, "close_trade_client", lambda: None)
    monkeypatch.setattr(module, "client_connection_info", lambda trader: {"client_class": "FakeClient"})
    return module


@pytest.mark.parametrize("result,connect_only,require_confirm", [
    (0, True, False),
    (0, True, True),
    (-1, True, False),
    (-1, False, False),
])
def test_connection_diagnostic_never_orders_and_always_disconnects(script, monkeypatch, capsys, result, connect_only, require_confirm):
    calls = []
    error = "xttrader.subscribe: reconnect cooldown 23.6s" if result else ""

    class FakeTrader:
        last_connect_error = error
        last_connect_error_type = "CfquantError" if result else ""
        last_connect_stage = "start" if result else ""

        def __init__(self, **kwargs):
            pass

        def connect(self):
            calls.append("connect")
            print("transport output")
            return result

        def order_stock(self, *args, **kwargs):
            pytest.fail("must not submit an order")

        def disconnect(self):
            calls.append("disconnect")

    monkeypatch.setattr(script, "XtQuantTrader", FakeTrader)
    monkeypatch.setattr(script, "JSON_OUTPUT", True)
    monkeypatch.setattr(script, "CONNECT_ONLY", connect_only)
    monkeypatch.setattr(script, "REQUIRE_CONFIRM", require_confirm)
    assert script.main() == (0 if result == 0 else 1)
    assert calls == ["connect", "disconnect"]
    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    connection = next(row for row in records if row.get("case") == "connect")
    assert connection["error"] == error
    if result != 0:
        assert "连接失败，未提交委托" in output
        assert error in output
    else:
        assert any(row.get("case") == "connect_only" and row["order_submitted"] is False for row in records)


def test_dry_run_still_does_not_connect(script, monkeypatch):
    monkeypatch.setattr(script, "XtQuantTrader", lambda **kwargs: pytest.fail("dry run must not connect"))
    monkeypatch.setattr(script, "DRY_RUN", True)
    monkeypatch.setattr(script, "CONNECT_ONLY", True)
    assert script.main() == 0
