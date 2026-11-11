"""Regression checks for bounded historical download requests."""

from types import SimpleNamespace

from cfquant.qmt_bridge import CfquantQmtBridge
from cfquant.tx_trade_bridge import TxTradeBridge


def _run_download(bridge_cls):
    calls = []
    events = []

    def download(stock_list, period, start_time, end_time, callback, incrementally):
        calls.append((list(stock_list), period, start_time, end_time, incrementally))
        for index, stock_code in enumerate(stock_list, 1):
            callback({
                "finished": index,
                "total": len(stock_list),
                "stockcode": stock_code,
                "message": "",
            })

    bridge = bridge_cls(
        SimpleNamespace(),
        show=False,
        globals_dict={"download_history_data2": download},
    )
    bridge._send_event = lambda client, event, data, **kwargs: events.append((event, data, kwargs))
    result = bridge._download_history_data2({
        "stock_list": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"],
        "period": "1m",
        "callback_event": "download:history",
        "download_emit_lifecycle": True,
        "download_batch_size": 2,
        "incrementally": True,
    }, {"client_id": "client-1"})
    return result, calls, events


def test_tx_trade_history_download_is_serially_batched_and_progress_is_aggregated():
    result, calls, events = _run_download(TxTradeBridge)

    assert result is None
    assert [call[0] for call in calls] == [
        ["000001.SZ", "000002.SZ"],
        ["000003.SZ", "000004.SZ"],
        ["000005.SZ"],
    ]
    progress = [data for _, data, meta in events if meta["meta"]["stage"] == "progress"]
    assert progress[-1]["finished"] == 5
    assert progress[-1]["total"] == 5
    request_done = [data for _, data, meta in events if meta["meta"]["stage"] == "request_done"]
    assert len(request_done) == 1
    assert request_done[0]["finished"] == 5


def test_legacy_qmt_bridge_uses_the_same_download_guard():
    _, calls, _ = _run_download(CfquantQmtBridge)
    assert [call[0] for call in calls] == [
        ["000001.SZ", "000002.SZ"],
        ["000003.SZ", "000004.SZ"],
        ["000005.SZ"],
    ]


def test_minute_download_defaults_to_a_small_batch():
    assert TxTradeBridge._history_download_batch_size({"period": "1m"}) == 50
    assert TxTradeBridge._history_download_batch_size({"period": "1d"}) == 200
