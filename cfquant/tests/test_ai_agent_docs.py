from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cfquant import runtime_services as web


ROOT = Path(__file__).resolve().parents[2]
GUIDES = ("AI_AGENT_INTEGRATION.md", "AI_MCP_TRADING.md", "AI_STRATEGY_MIGRATION.md", "API_REFERENCE.md")


@pytest.mark.parametrize("name", GUIDES)
def test_bundled_ai_guides_match_public_sources(name):
    """Installations must get the current guides, including relative API links."""
    expected = (ROOT / "docs" / name).read_bytes()
    assert (ROOT / "web_dashboard" / "docs" / name).read_bytes() == expected
    assert "\ufffd" not in expected.decode("utf-8")


@pytest.mark.parametrize("name", GUIDES)
def test_ai_guides_available_without_source_checkout(monkeypatch, tmp_path, name):
    monkeypatch.setattr(web, "_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setattr(web, "STATIC_DIR", str(tmp_path / "missing"))
    path, raw = web.read_static_asset("/docs/" + name)
    assert path == "docs/" + name
    assert raw == (ROOT / "docs" / name).read_bytes()


def test_document_route_does_not_expose_other_source_files(monkeypatch, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "secret.md").write_text("private", encoding="utf-8")
    monkeypatch.setattr(web, "_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setattr(web, "STATIC_DIR", str(tmp_path / "missing"))
    assert web.read_static_asset("/docs/secret.md")[1] is None
    assert web.read_static_asset("/private/secret.md")[1] is None


def python_examples(name):
    return re.findall(r"```python\n(.*?)\n```", (ROOT / "docs" / name).read_text(encoding="utf-8"), re.S)


@pytest.mark.parametrize("name", ("AI_MCP_TRADING.md", "AI_STRATEGY_MIGRATION.md"))
def test_ai_guide_python_examples_compile(name):
    examples = python_examples(name)
    assert examples
    for source in examples:
        compile(source, name, "exec")


@pytest.mark.parametrize("enable_trading", (False, True))
def test_mcp_example_tools_and_order_payload(monkeypatch, enable_trading):
    """Run the actual documented adapter against a fake HTTP client only."""
    import requests

    tools = {}

    class FakeMCP:
        def __init__(self, name):
            pass

        def tool(self):
            def register(function):
                tools[function.__name__] = function
                return function
            return register

    monkeypatch.setitem(sys.modules, "mcp", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "mcp.server", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", SimpleNamespace(FastMCP=FakeMCP))
    for key, value in {
        "CFQUANT_API_KEY": "test-only-key", "CFQUANT_ACCOUNT_ID": "test-account",
        "CFQUANT_BRIDGE_ID": "test-bridge", "CFQUANT_BASE_URL": "http://example.invalid",
        "CFQUANT_MCP_ENABLE_TRADING": str(int(enable_trading)),
    }.items():
        monkeypatch.setenv(key, value)
    response = Mock()
    response.json.return_value = {"ok": True, "data": {"test": True}}
    request = Mock(return_value=response)
    monkeypatch.setattr(requests, "request", request)
    namespace = {"__name__": "document_example"}
    exec(compile(python_examples("AI_MCP_TRADING.md")[0], "mcp_example", "exec"), namespace)
    assert request.call_count == 0  # Starting the adapter never submits anything.
    assert set(tools) == {"cfquant_health", "cfquant_quote", "cfquant_account"} | (
        {"cfquant_buy_stock"} if enable_trading else set())
    assert tools["cfquant_account"]() == {"test": True}
    payload = request.call_args.kwargs["params"]
    assert payload["account_id"] == "test-account"
    assert payload["bridge_id"] == "test-bridge"
    assert payload["sections"] == "asset,positions,orders,trades"
    tools["cfquant_quote"]("000001.sz")
    assert request.call_args.kwargs["json"]["code_list"] == ["000001.SZ"]
    if enable_trading:
        buy = tools["cfquant_buy_stock"]
        with pytest.raises(ValueError, match="Expected confirmation"):
            buy("000001.SZ", 100, 10.0, "wrong", "doc-test-001")
        assert request.call_count == 2
        buy("000001.SZ", 100, 10.0, "BUY 000001.SZ 100 @ 10.000", "doc-test-001")
        payload = request.call_args.kwargs["json"]
        assert payload["confirm_text"] in web.order_confirmation_options(
            "STOCK", "buy", payload["stock_code"], payload["volume"], payload["price"])
        assert request.call_args.args == ("POST", "http://example.invalid/api/order")
        request.reset_mock()
        request.side_effect = requests.Timeout("simulated uncertain submission")
        with pytest.raises(requests.Timeout):
            buy("000001.SZ", 100, 10.0, "BUY 000001.SZ 100 @ 10.000", "doc-test-002")
        assert request.call_count == 1  # No automatic resubmission on timeout.


@pytest.mark.parametrize("connect_result", (0, -1))
def test_migration_readonly_example_cleans_up_without_trading(monkeypatch, connect_result):
    import cfquant

    source = next(source for source in python_examples("AI_STRATEGY_MIGRATION.md") if "def main():" in source)
    trader = Mock(last_connect_error="test connection failure")
    trader.connect.return_value = connect_result
    trader.subscribe.return_value = 0
    trader.query_stock_positions.return_value = []
    trader.query_stock_orders.return_value = []
    monkeypatch.setenv("CFQUANT_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("CFQUANT_BRIDGE_ID", "test-bridge")
    monkeypatch.setattr(cfquant, "configure", Mock())
    monkeypatch.setattr(cfquant.xttrader, "XtQuantTrader", Mock(return_value=trader))
    monkeypatch.setattr(cfquant.xtdata, "get_full_tick", Mock(return_value={"000001.SZ": {"lastPrice": 10}}))
    namespace = {"__name__": "document_example"}
    exec(compile(source, "migration_example", "exec"), namespace)
    if connect_result:
        with pytest.raises(RuntimeError, match="test connection failure"):
            namespace["main"]()
    else:
        namespace["main"]()
        trader.query_stock_asset.assert_called_once()
    trader.stop.assert_called_once()
    trader.order_stock.assert_not_called()
    trader.cancel_order_stock.assert_not_called()
