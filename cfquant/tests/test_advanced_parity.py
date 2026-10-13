"""Offline regressions for split-QMT account setup and downloaded data."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import tokenize

import pandas as pd
import pytest

import cfquant_web_server as web
from cfquant.normal_bridge import NormalQmtBridge
from cfquant.pipe_bridge import PipeNormalQmtBridge, PipeTradeBridge
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.tests.test_lite_parity import LITE_PATHS, _lite_bridge_class


ROOT = Path(__file__).resolve().parents[2]
TRADE_ENTRIES = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_TRADE_LOWLAT*.py"))


@pytest.mark.parametrize("path", TRADE_ENTRIES, ids=lambda path: path.stem)
@pytest.mark.parametrize("source", ["runtime", "environment"])
def test_advanced_trade_entry_binds_credit_account_before_init(monkeypatch, path, source):
    for name in ("CFQUANT_ACCOUNT_ID", "CFQUANT_ACCOUNT_TYPE"):
        monkeypatch.delenv(name, raising=False)
    identity = {"account_id": "C123", "account_type": "CREDIT"}
    if source == "environment":
        for name, value in identity.items():
            monkeypatch.setenv("CFQUANT_" + name.upper(), value)
    with tokenize.open(str(path)) as stream:
        tree = ast.parse(stream.read())
    bridge = SimpleNamespace(account_type="", run_forever=lambda **kwargs: None)
    bound = []
    bridge.set_context = lambda context: bound.append((bridge.account_id, bridge.account_type))

    def start(context, **kwargs):
        bridge.account_id = kwargs["account_id"]
        return bridge

    namespace = dict(os=os, BRIDGE_ID="test", RUNTIME_CONFIG={}, RUNTIME_CHANNELS={},
                     QMT_MARKET="", USER_BRIDGE_ID="default", BRIDGE_CHANNELS={"trade": "trade"},
                     _load_runtime_config=lambda: identity if source == "runtime" else {},
                     _env_allows_runtime_override=lambda *args: True,
                     _print_log=lambda *args: None, _ENTRY_VERSION="test",
                     start_tx_trade_bridge=start)
    # Execute account setup and bridge construction from each shipped entry,
    # omitting imports and transport startup so this cannot contact a live QMT.
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in ("DEFAULT_ACCOUNT_ID", "DEFAULT_ACCOUNT_TYPE")
            for target in node.targets
        ):
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in ("_apply_runtime_config", "_config_bool", "init"):
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    namespace["_apply_runtime_config"]()
    nodes = [node for node in tree.body if (
        isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name) and node.value.func.id == "start_tx_trade_bridge"
    ) or (isinstance(node, ast.If) and "DEFAULT_ACCOUNT_TYPE" in ast.unparse(node.test))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    namespace["init"](object())
    assert bound == [("C123", "CREDIT")]


@pytest.mark.parametrize("mode", ["lttx", "ctypes"])
@pytest.mark.parametrize("requested_channel", [None, "trade"])
@pytest.mark.parametrize("read_action", [
    "get_local_data", "get_market_data", "get_market_data_ex", "get_financial_data",
    "get_financial_data_ori", "get_financial_data_raw",
])
def test_download_then_read_uses_same_qmt_storage(monkeypatch, mode, requested_channel, read_action):
    stores = {"normal": {}, "trade": {}}
    if mode == "ctypes":
        stores["trade"] = stores["normal"]
    frames = {"000001.SZ": pd.DataFrame({"close": [11.6]})}

    def functions(store):
        return {
            "download_history_data": lambda *args: store.update(history=frames),
            "download_financial_data": lambda *args: store.update(financial=frames),
            "get_market_data_ex": lambda *args: store.get("history", {}),
            "get_financial_data": lambda *args: store.get("financial", {}),
            "get_raw_financial_data": lambda *args: store.get("financial", {}),
        }

    normal_cls, trade_cls = (NormalQmtBridge, TxTradeBridge) if mode == "lttx" else (PipeNormalQmtBridge, PipeTradeBridge)
    bridges = {channel: cls(object(), globals_dict=functions(stores[channel]), show=False)
               for channel, cls in (("normal", normal_cls), ("trade", trade_cls))}
    monkeypatch.setattr(web, "WEB_CONFIG", None)
    monkeypatch.setattr(web, "resolve_bridge_id", lambda **kwargs: "test")
    monkeypatch.setattr(web, "resolve_account_mode", lambda *args, **kwargs: mode)
    monkeypatch.setattr(web, "resolve_market_route_for_request", lambda **kwargs: ("test", None))
    calls = []

    def request(bridge_id, channel, action, params, **kwargs):
        calls.append((action, channel))
        return bridges[channel]._dispatch(action, params, {"client_id": "offline"})

    monkeypatch.setattr(web.CLIENTS, "request", request)
    params = {"stock_code": "000001.SZ", "stock_list": ["000001.SZ"],
              "field_list": ["close"], "period": "1d"}
    download = "download_financial_data" if "financial" in read_action else "download_history_data"
    web.account_request("C123", "test", requested_channel, "xtdata." + download, params)
    result = web.account_request("C123", "test", requested_channel, "xtdata." + read_action, params)["result"]
    assert result, calls
    assert calls == [("xtdata." + download, "normal"), ("xtdata." + read_action, "normal")]


@pytest.mark.parametrize("action", ["xtdata.get_market_data", "xtdata.get_market_data_ex"])
@pytest.mark.parametrize("period", ["l2quote", "l2order", "l2transaction"])
def test_level2_market_reads_keep_trade_channel(action, period):
    assert web.route_channel_for_account("C123", mode="lttx", action=action,
                                         params={"period": period}) == "trade"


BRIDGES = [TxTradeBridge, NormalQmtBridge, PipeTradeBridge, PipeNormalQmtBridge]
BRIDGES += [_lite_bridge_class(path) for path in LITE_PATHS]


@pytest.mark.parametrize("bridge_cls", BRIDGES)
@pytest.mark.parametrize("raw", [
    {"success": "false", "msg": "rejected", "apply_id": "-1"},
    {"success": True, "msg": "accepted", "apply_id": []},
    {"success": True, "msg": "accepted", "apply_id": True},
    {"success": True, "apply_id": "A1"},
])
def test_all_modes_reject_malformed_smt_response(bridge_cls, raw):
    bridge = bridge_cls(object(), show=False, globals_dict={"smt_appointment_cancel": lambda *args: raw})
    bridge._send_trader_event = lambda *args: pytest.fail("malformed response delivered")
    with pytest.raises(RuntimeError, match="business response"):
        bridge._dispatch("xttrader.smt_appointment_cancel", {
            "account": {"account_id": "C123", "account_type": "CREDIT"}, "seq": 1, "args": ["A1"],
        }, {"client_id": "offline"})


@pytest.mark.parametrize("bridge_cls", BRIDGES)
def test_all_modes_accept_native_smt_fields(bridge_cls):
    raw = type("BrokerResponse", (), dict(__slots__=(), m_bSuccess=True,
               m_strMsg="accepted", m_strApplyID="000123", m_nSeq=987))()
    bridge = bridge_cls(object(), show=False, globals_dict={"smt_appointment_cancel": lambda *args: raw})
    events = []
    bridge._send_trader_event = lambda client, event, data: events.append(data)
    result = bridge._dispatch("xttrader.smt_appointment_cancel", {
        "account": {"account_id": "C123", "account_type": "CREDIT"}, "seq": 1, "args": ["A1"],
    }, {"client_id": "offline"})
    assert result == {"seq": 1, "accepted": True}
    assert len(events) == 1
    assert events[0]["success"] is True and events[0]["apply_id"] == "000123"
    assert events[0]["seq"] == 1
