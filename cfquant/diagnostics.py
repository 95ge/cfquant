# -*- coding: utf-8 -*-
"""Opt-in whole-quote latency diagnostics; ordinary xtdata payloads are unchanged."""
import datetime
import math
import time

from . import xtdata


SCHEMA = "cfquant.quote_latency.v1"
ACTION = "xtdata.subscribe_whole_quote_latency"
_SHANGHAI = datetime.timezone(datetime.timedelta(hours=8))


def quote_time_ms(value):
    """Accept epoch seconds/ms/us/ns and QMT calendar strings (China time).

    Time-only and date-only fields are deliberately not assigned today's date.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.isdigit() and len(text) in (14, 17) and text[:2] in ("19", "20"):
        try:
            stamp = datetime.datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=_SHANGHAI)
            return stamp.timestamp() * 1000.0 + (int(text[14:]) if len(text) == 17 else 0)
        except ValueError:
            return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S.%f", "%Y%m%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(text, fmt).replace(tzinfo=_SHANGHAI).timestamp() * 1000.0
            except ValueError:
                pass
        return None
    if not math.isfinite(number) or number < 1000000000:
        return None
    if number >= 1e17:
        number /= 1e6
    elif number >= 1e14:
        number /= 1e3
    elif number < 1e11:
        number *= 1000.0
    # Reject short dates and implausible timestamps rather than report bogus latency.
    return number if 946684800000 <= number < 4102444800000 else None


def latency_stats(values):
    values = sorted(value for value in values if value is not None and math.isfinite(value))
    if not values:
        return {"count": 0, "min_ms": None, "max_ms": None, "avg_ms": None, "p95_ms": None}
    return {"count": len(values), "min_ms": values[0], "max_ms": values[-1],
            "avg_ms": round(sum(values) / len(values), 3),
            "p95_ms": values[max(0, (len(values) * 95 + 99) // 100 - 1)]}


def latency_report(payload, received_at_ms=None, sample_limit=None):
    """Measure at callback entry, before reporting/rendering. Never clamp negative deltas."""
    received_at_ms = time.time() * 1000.0 if received_at_ms is None else received_at_ms
    analysis_started = time.perf_counter()
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("not a cfquant whole-quote latency event; update the QMT entry script")
    quotes = payload.get("quotes") or {}
    pushed = quote_time_ms(payload.get("qmt_push_at_ms"))
    entered = quote_time_ms(payload.get("qmt_callback_at_ms"))

    def delta(end, start):
        return round(end - start, 3) if end is not None and start is not None else None

    sample_limit = None if sample_limit is None else max(1, int(sample_limit))
    samples = []
    for code, quote in quotes.items():
        if sample_limit is not None and len(samples) >= sample_limit:
            break
        if not isinstance(quote, dict):
            continue
        stamp, field, raw = None, None, None
        for name in ("time", "stime", "timetag", "datetime", "updateTime", "update_time"):
            candidate = quote.get(name)
            if raw is None and candidate is not None:
                field, raw = name, candidate
            stamp = quote_time_ms(candidate)
            if stamp is not None:
                field, raw = name, candidate
                break
        samples.append({
            "code": str(code), "quote_time_field": field, "quote_time_raw": raw,
            "quote_at_ms": stamp, "quote_latency_ms": delta(received_at_ms, stamp),
            # Use the timestamp captured at QMT callback entry, before locking
            # or conversion; receiver/formatting time must not affect this value.
            "qmt_quote_latency_ms": delta(entered, stamp),
            "last_price": quote.get("lastPrice", quote.get("last_price")),
            "volume": quote.get("volume"), "amount": quote.get("amount"),
        })
    summary = {
        "quote_latency": latency_stats(row["quote_latency_ms"] for row in samples),
        "qmt_quote_latency": latency_stats(row["qmt_quote_latency_ms"] for row in samples),
    }
    return {
        "schema": SCHEMA, "received_at_ms": received_at_ms,
        "qmt_callback_at_ms": entered, "qmt_push_at_ms": pushed,
        "internal_latency_ms": delta(received_at_ms, pushed),
        "qmt_prepare_ms": delta(pushed, entered),
        "qmt_encode_ms": payload.get("qmt_encode_ms"), "qmt_encoding": payload.get("qmt_encoding"),
        "code_count": len(quotes), "samples": samples, "summary": summary,
        "analysis_ms": round((time.perf_counter() - analysis_started) * 1000, 3),
    }


def subscribe_whole_quote(code_list, callback, sample_limit=None):
    """Independent diagnostic subscription. Callback receives a measured report.

    Use xtdata.unsubscribe_quote(id) to stop. Internal latency includes encoding,
    transport, decoding and callback scheduling, ending at this Python callback.
    """
    if not callable(callback):
        raise TypeError("callback must be callable")
    sample_limit = None if sample_limit is None else max(1, int(sample_limit))

    def on_quote(payload):
        received_at_ms = time.time() * 1000.0
        callback(latency_report(payload, received_at_ms, sample_limit))

    return xtdata._subscribe_quote_request(ACTION, {"code_list": code_list}, on_quote)
