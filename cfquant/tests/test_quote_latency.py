import datetime
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfquant import diagnostics, xtdata
from cfquant.protocol import loads_message, pack_request
import cfquant_web_server as web


STAMP = 1792112400000.0


def envelope(count=2):
    return {"schema": diagnostics.SCHEMA, "qmt_callback_at_ms": STAMP + 10,
            "qmt_push_at_ms": STAMP + 12,
            "quotes": {"%06d.SZ" % i: {"time": STAMP, "lastPrice": 10 + i, "volume": i}
                       for i in range(count)}}


@pytest.mark.parametrize("scale", [1, 0.001, 1000, 1000000])
def test_quote_epoch_units(scale):
    assert diagnostics.quote_time_ms(str(int(STAMP * scale))) == STAMP


@pytest.mark.parametrize("fmt", ["%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S"])
def test_calendar_time_uses_china_timezone(fmt):
    date = datetime.datetime.fromtimestamp(STAMP / 1000, diagnostics._SHANGHAI)
    assert diagnostics.quote_time_ms(date.strftime(fmt)) == STAMP
    assert diagnostics.quote_time_ms(date.strftime("%Y%m%d%H%M%S") + "123") == STAMP + 123


@pytest.mark.parametrize("value", [None, True, "", "09:30:00", "20261016", 0, "bad", "nan", "inf", "20261301100000"])
def test_unknown_time_not_reported_as_zero(value):
    assert diagnostics.quote_time_ms(value) is None


def test_report_endpoints_fallback_clock_skew_and_bounded_samples():
    payload = envelope(100)
    payload["quotes"]["000000.SZ"] = {"time": "bad", "stime": STAMP - 1000}
    payload["quotes"]["000001.SZ"] = {"lastPrice": 123}
    report = diagnostics.latency_report(payload, STAMP + 32, sample_limit=2)
    assert report["internal_latency_ms"] == 20
    assert report["qmt_prepare_ms"] == 2
    assert report["samples"][0]["quote_latency_ms"] == 1032
    assert report["samples"][0]["qmt_quote_latency_ms"] == 1010
    assert report["samples"][0]["quote_time_field"] == "stime"
    assert report["samples"][1]["quote_latency_ms"] is None
    assert report["samples"][1]["qmt_quote_latency_ms"] is None
    assert report["code_count"] == 100 and len(report["samples"]) == 2
    assert diagnostics.latency_report(payload, STAMP)["internal_latency_ms"] == -12
    assert "schema" not in payload["quotes"]["000000.SZ"]


def test_default_report_covers_full_market_and_tail_changes_statistics():
    payload = envelope(26475)
    payload['quotes']['026474.SZ']['time'] = STAMP - 1000
    payload['qmt_encode_ms'] = 7.5
    report = diagnostics.latency_report(payload, STAMP + 32)
    assert len(report['samples']) == report['code_count'] == 26475
    assert report['samples'][-1]['quote_latency_ms'] == 1032
    assert report['summary']['quote_latency'] == {
        'count': 26475, 'min_ms': 32, 'max_ms': 1032, 'avg_ms': 32.038, 'p95_ms': 32}
    assert report['summary']['qmt_quote_latency']['max_ms'] == 1010
    assert report['qmt_encode_ms'] == 7.5 and report['analysis_ms'] >= 0


@pytest.mark.parametrize("quote_offset", [0, -20343000, 100])
def test_qmt_quote_time_difference_uses_original_callback_time_for_each_quote(quote_offset):
    payload = envelope()
    payload["quotes"]["000000.SZ"]["time"] = STAMP + quote_offset
    first = diagnostics.latency_report(payload, STAMP + 32)
    delayed = diagnostics.latency_report(payload, STAMP + 5032)
    for index, expected in enumerate((10 - quote_offset, 10)):
        assert first["samples"][index]["qmt_quote_latency_ms"] == expected
        assert delayed["samples"][index]["qmt_quote_latency_ms"] == expected
        row = delayed["samples"][index]
        assert row["quote_latency_ms"] == pytest.approx(
            row["qmt_quote_latency_ms"] + delayed["qmt_prepare_ms"] + delayed["internal_latency_ms"], abs=0.002)


@pytest.mark.parametrize("timestamp", [None, "bad", 0])
def test_missing_qmt_callback_timestamp_does_not_substitute_receiver_time(timestamp):
    payload = envelope()
    payload["qmt_callback_at_ms"] = timestamp
    report = diagnostics.latency_report(payload, STAMP + 32)
    assert report["samples"][0]["qmt_quote_latency_ms"] is None
    assert report["samples"][0]["quote_latency_ms"] == 32
    assert report["qmt_prepare_ms"] is None
    assert report["internal_latency_ms"] == 20


def test_sdk_diagnostic_callback_measures_before_user_work_and_unsubscribes(monkeypatch):
    calls, callbacks, received = [], {}, []
    def request(action, params):
        calls.append((action, dict(params)))
        return {"subscribe_id": 99, "callback_event": params["callback_event"]} if action == diagnostics.ACTION else True
    client = SimpleNamespace(request=request, add_callback=lambda name, cb: callbacks.update({name: cb}),
                             remove_callback=lambda name, cb: callbacks.pop(name))
    monkeypatch.setattr(xtdata, "get_client", lambda: client)
    monkeypatch.setattr(diagnostics.time, "time", lambda: (STAMP + 40) / 1000)
    sub = diagnostics.subscribe_whole_quote(["SZ"], received.append)
    assert calls[0][0] == diagnostics.ACTION
    next(iter(callbacks.values()))(envelope())
    assert received[0]["internal_latency_ms"] == 28
    assert received[0]["samples"][0]["quote_latency_ms"] == 40
    assert received[0]["samples"][0]["qmt_quote_latency_ms"] == 10
    assert xtdata.unsubscribe_quote(sub) is True
    assert callbacks == {}


class DiagnosticService:
    def __init__(self):
        self.released = []
        self.callback = None
    def acquire(self, key, codes, callback, **kwargs):
        assert kwargs["diagnostic"]
        self.callback = callback
        callback(dict(envelope(100), shared_received_at_ms=STAMP + 32))
        return 101
    def release(self, lease):
        self.released.append(lease)
        return True
    def status(self):
        return {"source": {"bridge_id": "test-bridge", "channel": "normal"}}


def test_web_diagnostics_shared_routes_receive_time_and_cleanup():
    broadcasts = []
    service = DiagnosticService()
    manager = SimpleNamespace(count=lambda *args: 1, broadcast=broadcasts.append)
    store = web.QuoteSubscriptionStore(diagnostic=True, manager=manager, max_events=2, shared_service=service)
    try:
        result = store.subscribe_whole({"markets": ["SZ"], "bridge_id": "test-bridge"})
        assert result["kind"] == "whole_quote_latency"
        assert result["shared"]
        for _ in range(3):
            service.callback(dict(envelope(100), shared_received_at_ms=STAMP + 32))
        assert len(store.latest()) == 2
        event = broadcasts[-1]
        assert event["latency"]["internal_latency_ms"] == 20
        assert event["latency"]["samples"][0]["quote_latency_ms"] == 32
        assert event["latency"]["samples"][0]["qmt_quote_latency_ms"] == 10
        assert len(event["data"]) == event["code_count"] == 100
        count = len(broadcasts)
        store._on_quote({"subscription_id":101, "event":"quote:other", "data":envelope()})
        assert len(broadcasts) == count
        assert store.unsubscribe({"subscribe_id":101})["result"] is True
        assert service.released == [101]
        assert store.latest() == []
        service.callback(envelope())
        assert len(broadcasts) == count
    finally:
        store.close()


def test_web_keeps_early_snapshot_receive_timestamp():
    service = DiagnosticService()
    manager = SimpleNamespace(count=lambda *args:1, broadcast=lambda event:None)
    store = web.QuoteSubscriptionStore(diagnostic=True, manager=manager, shared_service=service)
    try:
        store.subscribe_whole({"markets":["SZ"]})
        report = store.latest()[0]["latency"]
        assert report["internal_latency_ms"] == 20
        assert report["received_at_ms"] == STAMP + 32
        assert report["samples"][0]["qmt_quote_latency_ms"] == 10
    finally:
        store.close()


def test_print_script_reports_and_cleans_up_on_keyboard_interrupt(monkeypatch, capsys):
    path = next(Path(__file__).parent.glob('34_*.py'))
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location('latency_print_script', path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    closed, unsubscribed = [], []
    monkeypatch.setattr(script, 'configure_stdout', lambda: None)
    monkeypatch.setattr(script, 'configure_cfquant', lambda config: None)
    monkeypatch.setattr(script, 'close_default_client', lambda: closed.append(True))
    monkeypatch.setattr(script.xtdata, 'unsubscribe_quote', unsubscribed.append)
    def subscribe(codes, callback, **kwargs):
        callback(diagnostics.latency_report(envelope(), STAMP + 32))
        return 102
    monkeypatch.setattr(script.diagnostics, 'subscribe_whole_quote', subscribe)
    class Stop:
        calls = 0
        def wait(self, timeout):
            self.calls += 1
            if self.calls > 1:
                raise KeyboardInterrupt
    monkeypatch.setattr(script.threading, 'Event', Stop)
    script.main()
    assert unsubscribed == [102] and closed == [True]
    output = capsys.readouterr().out
    assert '"internal_latency_ms": 20' in output
    assert '"qmt_quote_latency_ms": 10' in output
    assert '"行情到QMT_本批全部": {"count": 2, "min_ms": 10.0' in output


def test_web_lttx_forwards_diagnostic_envelope_and_unsubscribes(monkeypatch):
    messages = []
    router = web.LttxWebRouteServer()
    router.tx = SimpleNamespace(push=lambda kind, payload, channel: messages.append((kind, loads_message(payload), channel)))
    packet = envelope()
    def acquire(key, codes, callback, **kwargs):
        assert kwargs['diagnostic']
        callback(packet)
        return 42
    released = []
    monkeypatch.setattr(web, 'PROJECT_QUOTES', SimpleNamespace(
        acquire=acquire, status=lambda:{'source':{'bridge_id':'test', 'channel':'normal', 'mode':'lite'}},
        release=lambda lease:released.append(lease) or True))
    router._handle_raw(pack_request(diagnostics.ACTION, {'code_list': ['SZ'], 'callback_event': 'quote:sdk'}, client_id='sdk'))
    assert [message[0] for message in messages] == ['event', 'response']
    assert messages[0][1]['data'] == packet
    assert not messages[0][1].get('meta', {}).get('quote_json_plain')
    assert messages[0][1]['event'] == 'quote:sdk'
    assert messages[0][2] == 'sdk'
    sid = messages[-1][1]['result']['subscribe_id']
    router._handle_raw(pack_request('xtdata.unsubscribe_quote', {'subscribe_id': sid}, client_id='sdk'))
    assert released == [42]
    assert router._quote_routes == {} and router._quote_event_routes == {}
