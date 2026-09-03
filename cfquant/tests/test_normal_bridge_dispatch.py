import threading

from cfquant.normal_bridge import NormalQmtBridge
from cfquant.protocol import loads_message, pack_request


class RecordingTx(object):
    def __init__(self):
        self.responses = []

    def push(self, kind, payload, client_id):
        self.responses.append((kind, payload, client_id))


def _query_bridge(calls):
    bridge = NormalQmtBridge(
        object(),
        show=False,
        globals_dict={
            "get_trade_detail_data": lambda *args: calls.append(
                (threading.current_thread().name, args)
            ) or [{"m_dAvailable": 123.45}],
        },
        schedule_timer=False,
        dispatch_on_qmt_thread=True,
    )
    bridge.running = True
    bridge.tx = RecordingTx()
    return bridge


def test_qmt_thread_dispatch_pump_executes_query_on_caller_thread():
    calls = []
    bridge = _query_bridge(calls)

    bridge._handle_raw_from_thread(pack_request(
        "xttrader.query_stock_asset",
        params={
            "account": {
                "account_id": "A123",
                "account_type": "STOCK",
            },
        },
        client_id="web-client",
        request_id="request-1",
    ))

    assert bridge.worker_thread is None
    assert bridge.pump() == 1
    assert calls[0][0] == threading.current_thread().name
    assert calls[0][1] == ("A123", "stock", "account")
    response = loads_message(bridge.tx.responses[0][1])
    assert response["ok"] is True
    assert response["id"] == "request-1"


def test_qmt_thread_dispatch_timer_drains_coalesced_query_queue():
    calls = []
    bridge = _query_bridge(calls)

    for request_id in ("request-1", "request-2"):
        bridge._handle_raw_from_thread(pack_request(
            "xttrader.query_stock_positions",
            params={
                "account": {
                    "account_id": "A123",
                    "account_type": "STOCK",
                },
            },
            client_id="web-client",
            request_id=request_id,
        ))

    bridge.on_timer()

    assert len(calls) == 1
    assert len(bridge.tx.responses) == 2
    assert {loads_message(item[1])["id"] for item in bridge.tx.responses} == {
        "request-1",
        "request-2",
    }
