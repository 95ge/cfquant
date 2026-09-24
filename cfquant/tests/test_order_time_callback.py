import datetime
import json

from cfquant.normal_bridge import NormalQmtBridge
from cfquant.xttype import XtOrder


class RecordingTx(object):
    def __init__(self):
        self.pushes = []

    def push(self, kind, payload, key):
        self.pushes.append((kind, payload, key))


def _expected_timestamp(hour=21, minute=24, second=23):
    timezone = datetime.timezone(datetime.timedelta(hours=8))
    value = datetime.datetime(2026, 9, 24, hour, minute, second, tzinfo=timezone)
    return int(value.timestamp())


def test_order_callback_skips_zero_placeholder_time():
    raw = {
        "time": 0,
        "order_time": 0,
        "m_strOrderTime": "212423",
        "m_strOrderDate": "20260924",
        "m_strAccountID": "A123",
        "m_strInstrumentID": "000001",
        "m_strExchangeID": "SZ",
    }
    bridge = NormalQmtBridge(None, show=False, schedule_timer=False, order_meta_enabled=False)
    tx = RecordingTx()
    bridge.tx = tx
    try:
        bridge.publish_callback_event("trader:on_stock_order", raw)
        payload = json.loads(tx.pushes[-1][1])
        assert payload["data"]["order_time"] == "212423"
        assert XtOrder.from_any(payload["data"]).order_time == _expected_timestamp()
    finally:
        bridge.close()


def test_order_time_conversion_skips_zero_before_valid_qmt_time():
    raw = {
        "time": 0,
        "m_strOrderTime": "212423",
        "order_date": 0,
        "m_strOrderDate": "20260924",
    }
    assert XtOrder.from_any(raw).order_time == _expected_timestamp()


def test_order_callback_uses_insert_time_and_insert_date():
    raw = {
        "time": 0,
        "m_strOrderTime": None,
        "m_strInsertTime": "112021",
        "m_strInsertDate": "20260924",
        "m_strAccountID": "A123",
        "m_strInstrumentID": "688051",
        "m_strExchangeID": "SH",
    }
    bridge = NormalQmtBridge(None, show=False, schedule_timer=False, order_meta_enabled=False)
    try:
        row = bridge._format_trade_detail(raw, "order")
        assert row["order_time"] == "112021"
        assert row["order_date"] == "20260924"
        assert XtOrder.from_any(row).order_time == _expected_timestamp(11, 20, 21)
    finally:
        bridge.close()
