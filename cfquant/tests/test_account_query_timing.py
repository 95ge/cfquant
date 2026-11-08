"""Query diagnostics against fake native calls and real RPC serialization."""
from types import SimpleNamespace
import time

import pytest

import cfquant_web_server as web
from cfquant import normal_bridge, protocol, tx_trade_bridge as core
from cfquant.tests.test_market_timing import Clock, implementation, rpc
from cfquant.tests.test_lite_qmt_dispatch import lite, enqueue


@pytest.mark.parametrize("detail,action", [("account", "asset"), ("position", "positions")])
def test_account_native_time_excludes_queue_and_formatting(implementation, monkeypatch, detail, action):
    cls, _, clock = implementation
    native_calls = []

    def native(*args):
        native_calls.append(args)
        clock.advance(20)
        return [{"available": 100}]

    def format_row(row, kind):
        assert kind == detail
        clock.advance(7)
        return dict(row)

    bridge = cls(SimpleNamespace(get_trade_detail_data=native), show=False)
    monkeypatch.setattr(bridge, "_format_trade_detail", format_row)
    msg = {"id": "timed-account", "_received_monotonic": clock.now - .2}
    result = bridge._dispatch("xttrader.query_stock_" + action, {"account_id": "paper"}, msg)
    qmt = msg["_response_meta"]["timing"]["qmt"]
    assert native_calls == [("paper", "stock", detail)]
    assert (qmt["queue_ms"], qmt["native_ms"], qmt["execute_ms"]) == (200, 20, 27)
    assert result[0]["available"] == 100 and result[0]["account_id"] == "paper"


def test_account_native_error_keeps_timing_and_request_log(implementation, monkeypatch):
    cls, _, clock = implementation
    logs, responses = [], []

    def native(*args):
        clock.advance(73)
        raise ValueError("native offline")

    bridge = cls(SimpleNamespace(get_trade_detail_data=native), show=False)
    monkeypatch.setattr(bridge, "_log", logs.append)
    bridge.tx = SimpleNamespace(push=lambda kind, raw, client: responses.append(protocol.loads_message(raw)))
    bridge._handle_raw(protocol.pack_request("xttrader.query_stock_asset", {"account_id": "paper"},
                                            client_id="offline", request_id="native-error"))
    row = responses[0]
    assert not row["ok"]
    assert row["meta"]["timing"]["qmt"]["native_ms"] == 73
    assert any("account_query_start" in line and "native-error" in line for line in logs)
    assert any("account_query_done" in line and "native-error" in line for line in logs)


def test_lite_embedded_account_query_has_native_diagnostics(lite):
    enqueue(lite, "xttrader.query_stock_asset", params={"account_id": "TEST_ONLY"})
    lite.ns["cfquant_ctype_trade_timer"](lite.context)
    response = lite.tx.responses[0]
    assert response["ok"] is True
    qmt = response["meta"]["timing"]["qmt"]
    assert qmt["queue_ms"] >= 0 and qmt["execute_ms"] >= qmt["native_ms"] >= 0
    assert qmt["native_calls"][0]["method"] == "get_trade_detail_data"


@pytest.mark.parametrize("error", [False, True])
def test_coalesced_queries_keep_individual_ids_and_queue_times(monkeypatch, error):
    clock = Clock()
    fake_time = SimpleNamespace(**dict(vars(time), perf_counter=clock.perf_counter))
    monkeypatch.setattr(core, "time", fake_time)
    monkeypatch.setattr(normal_bridge, "time", fake_time)
    calls, sent = [], []

    def native(*args):
        calls.append(args)
        clock.advance(7)
        if error:
            raise ValueError("native failed")
        return []

    bridge = normal_bridge.NormalQmtBridge(SimpleNamespace(get_trade_detail_data=native), show=False, order_meta_enabled=False)
    bridge.tx = SimpleNamespace(push=lambda kind, raw, client: sent.append(protocol.loads_message(raw)))
    for name in ("first", "second"):
        bridge._handle_raw_from_thread(protocol.pack_request("xttrader.query_stock_asset", {"account_id": "paper"},
                                                             client_id="offline", request_id=name))
        clock.advance(100)
    msg, received, key = bridge.request_queue.get_nowait()
    bridge._drain_coalesced_request("test", msg, received, key)
    assert len(calls) == 1 and len(sent) == 2
    assert [row["id"] for row in sent] == ["first", "second"]
    assert [row["meta"]["timing"]["qmt"]["queue_ms"] for row in sent] == [200, 100]
    assert all(row["meta"]["timing"]["qmt"]["native_ms"] == 7 for row in sent)
    assert all(row["ok"] is not error for row in sent)


def test_web_retains_failure_request_id_and_logs_without_inventing_qmt_time(rpc, monkeypatch):
    clients = web.GlobalTxClient()
    monkeypatch.setattr(clients, "_get_client", lambda mode: rpc.client)
    monkeypatch.setattr(web, "bridge_channels", lambda bridge_id: {"normal": "offline.normal"})
    logs = []
    monkeypatch.setattr(web, "safe_print", logs.append)

    def request(account_id, bridge_id, channel, action, params, **kwargs):
        try:
            value = clients.request(bridge_id, channel, action, params, mode="lite", timeout=.001)
        except Exception as error:
            raise RuntimeError("wrapped asset failure: %s" % error) from error
        return {"result": value, "mode": "lite", "channel": channel, "fallback": False, "fallback_reason": ""}

    monkeypatch.setattr(web, "account_request", request)
    rpc.respond = False
    failed = web.query_account_live("offline", "normal", "paper", ["asset", "positions"], account_key="paper:STOCK")
    ids = []
    for name in ("asset", "positions"):
        row = failed[name]
        assert row["ok"] is False
        timing = row["request_timings"][0]
        ids.append(timing["request_id"])
        assert timing["qmt"] == {"available": False, "reason": "no_response"}
        assert timing["rpc"]["response_received"] is False and timing["started_at"] > 0
        assert timing["rpc"]["sent_at"] >= timing["started_at"]
        assert timing["rpc"]["response_wait_ms"] > 0
        assert any(timing["request_id"] in line and "account_query_timing" in line for line in logs)
    assert len(set(ids)) == 2 and web._account_timing_attempts.get() is None
    rpc.respond = True
    rpc.old = True
    row = web.query_account_live("offline", "normal", "paper", ["asset"], account_key="paper:STOCK")["asset"]
    assert row["ok"] is True
    assert row["request_timings"][0]["qmt"]["reason"] == "bridge_timing_unavailable"


def test_configured_pipe_account_fails_fast_when_channel_is_not_ready(monkeypatch):
    config = SimpleNamespace(
        account_config=lambda **kwargs: {
            "account_key": "acct:STOCK:paper",
            "account_id": "paper",
            "account_type": "STOCK",
            "bridge_id": "acct",
            "mode": "ctypes",
            "enabled": True,
        },
    )
    monkeypatch.setattr(web, "WEB_CONFIG", config)
    monkeypatch.setattr(web, "resolve_account_mode", lambda *args, **kwargs: "ctypes")
    monkeypatch.setattr(web, "bridge_channels", lambda bridge_id: {
        "normal": "cfquant.acct.normal.request",
        "trade": "cfquant.acct.trade.request",
    })
    monkeypatch.setattr(web, "PIPE_HUB", SimpleNamespace(status=lambda: {
        "status": {"qmt_ready_channels": [], "qmt_channel_states": {}},
    }))

    def unexpected_request(*args, **kwargs):
        raise AssertionError("offline account must not reach the RPC client")

    monkeypatch.setattr(web, "account_request", unexpected_request)
    row = web.query_account_live(
        "acct",
        "normal",
        "paper",
        ["asset"],
        account_key="acct:STOCK:paper",
    )["asset"]

    assert row["ok"] is False
    assert row["error_code"] == "QMT_BRIDGE_NOT_CONNECTED"
    assert row["bridge_ready"] is False
    assert row["request_timings"][0]["qmt"]["reason"] == "bridge_not_ready"
    assert row["refresh_latency_ms"] < 100
