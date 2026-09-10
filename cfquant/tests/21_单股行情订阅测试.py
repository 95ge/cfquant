# -*- coding: utf-8 -*-
from types import SimpleNamespace
import signal
import threading
import time

from _helpers import close_default_client, compact_value, configure_stdout, print_json

from cfquant import configure, get_client, xtdata


# ======================== 用户配置区 ========================
# 直接修改下面的配置，然后运行本文件；不读取命令行参数。
TRANSPORT = "auto"       # auto 自动发现；也可填写 ctypes、web_lttx 或 lttx
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0    # 请求超时，单位秒
HOST = None              # None 使用 cfquant 默认配置
PORT = None
TOKEN = None             # 优先使用运行时配置，不要提交凭据到 Git
STOCK_CODE = "000001.SZ"
PERIOD = "tick"           # 也可填写 1d、1m 等
START_TIME = ""
END_TIME = ""
COUNT = 0
SECONDS = 12.0
USE_QUOTE2 = False        # True 改用 subscribe_quote2
DIVIDEND_TYPE = "none"
SAMPLE_CODES = 3
HEARTBEAT_SECONDS = 3.0   # 0 关闭心跳统计
GAP_WARNING_SECONDS = 5.0 # 0 关闭无回调提示
# ===========================================================


def _summarize_quote_payload(payload, sample_codes=3):
    if not isinstance(payload, dict):
        return {
            "payload_type": type(payload).__name__,
            "payload": repr(payload)[:500],
        }

    samples = {}
    for code, row in list(payload.items())[: int(sample_codes)]:
        code = str(code)
        if isinstance(row, dict):
            keys = [
                "time",
                "stime",
                "timetag",
                "lastPrice",
                "open",
                "high",
                "low",
                "lastClose",
                "amount",
                "volume",
            ]
            samples[code] = {key: compact_value(row.get(key)) for key in keys if key in row}
            if not samples[code]:
                samples[code] = {str(k): compact_value(v) for k, v in list(row.items())[:8]}
        else:
            samples[code] = compact_value(row)

    return {
        "code_count": len(payload),
        "sample": samples,
    }


def _stats_template():
    return {
        "single_callbacks": 0,
        "generic_quote_events": 0,
        "wire_quote_events": 0,
        "total_codes": 0,
        "first_at": 0.0,
        "last_at": 0.0,
        "last_gap_warning_at": 0.0,
    }


def main():
    configure_stdout()
    config = SimpleNamespace(
        transport=TRANSPORT,
        bridge_id=BRIDGE_ID,
        timeout=REQUEST_TIMEOUT,
        host=HOST,
        port=PORT,
        token=TOKEN,
        stock_code=STOCK_CODE,
        period=PERIOD,
        start_time=START_TIME,
        end_time=END_TIME,
        count=COUNT,
        seconds=SECONDS,
        use_quote2=USE_QUOTE2,
        dividend_type=DIVIDEND_TYPE,
        sample_codes=SAMPLE_CODES,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        gap_warning_seconds=GAP_WARNING_SECONDS,
    )

    configure_kwargs = {
        "transport": config.transport,
        "bridge_id": config.bridge_id,
        "timeout": config.timeout,
    }
    if config.host is not None:
        configure_kwargs["host"] = config.host
    if config.port is not None:
        configure_kwargs["port"] = config.port
    if config.token is not None:
        configure_kwargs["token"] = config.token
    configure(**configure_kwargs)

    stop_event = threading.Event()
    stats_lock = threading.Lock()
    stats = _stats_template()
    subscribe_id_box = {"value": None}

    def snapshot():
        with stats_lock:
            return dict(stats)

    def remember_event(kind, payload):
        now = time.time()
        code_count = len(payload) if isinstance(payload, dict) else 0
        with stats_lock:
            stats[kind] += 1
            stats["total_codes"] += code_count
            stats["first_at"] = stats["first_at"] or now
            stats["last_at"] = now
            event_no = stats[kind]
        row = {
            "type": kind,
            "event_no": event_no,
            "received_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        }
        row.update(_summarize_quote_payload(payload, sample_codes=config.sample_codes))
        print_json(row)

    def on_single_quote(data):
        remember_event("single_callbacks", data)

    def on_generic_quote(msg):
        subscribe_id = str(msg.get("subscribe_id") or msg.get("subscription_id") or "")
        expected_id = str(subscribe_id_box.get("value") or "")
        if expected_id and subscribe_id != expected_id:
            return
        remember_event("generic_quote_events", msg.get("data"))

    def on_wire_event(msg):
        subscribe_id = str(msg.get("subscribe_id") or msg.get("subscription_id") or "")
        expected_id = str(subscribe_id_box.get("value") or "")
        event_name = str(msg.get("event") or "")
        if expected_id and subscribe_id != expected_id and event_name != "quote:%s" % expected_id:
            return
        if not event_name.startswith("quote:"):
            return
        remember_event("wire_quote_events", msg.get("data"))

    def request_stop(signum=None, frame=None):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    try:
        signal.signal(signal.SIGTERM, request_stop)
    except Exception:
        pass

    client = get_client()
    client.add_callback("quote", on_generic_quote)
    client.add_callback("__event__", on_wire_event)

    started_at = time.time()
    next_heartbeat_at = started_at + max(0.1, config.heartbeat_seconds)
    previous = snapshot()

    print_json({
        "type": "start",
        "transport": config.transport,
        "host": config.host,
        "port": config.port,
        "bridge_id": config.bridge_id,
        "stock_code": config.stock_code,
        "period": config.period,
        "seconds": config.seconds,
        "api": "xtdata.subscribe_quote2" if config.use_quote2 else "xtdata.subscribe_quote",
    })

    try:
        if config.use_quote2:
            subscribe_id = xtdata.subscribe_quote2(
                config.stock_code,
                period=config.period,
                start_time=config.start_time,
                end_time=config.end_time,
                count=config.count,
                dividend_type=config.dividend_type,
                callback=on_single_quote,
            )
        else:
            subscribe_id = xtdata.subscribe_quote(
                config.stock_code,
                period=config.period,
                start_time=config.start_time,
                end_time=config.end_time,
                count=config.count,
                callback=on_single_quote,
            )
        subscribe_id_box["value"] = subscribe_id
        print_json({
            "type": "subscribed",
            "subscribe_id": subscribe_id,
            "event": "quote:%s" % subscribe_id,
        })

        while not stop_event.is_set():
            now = time.time()
            if config.seconds > 0 and now - started_at >= config.seconds:
                break
            current = snapshot()
            last_at = float(current.get("last_at") or 0)
            if config.gap_warning_seconds > 0 and last_at:
                gap = now - last_at
                if gap >= config.gap_warning_seconds and now - current.get("last_gap_warning_at", 0) >= config.gap_warning_seconds:
                    with stats_lock:
                        stats["last_gap_warning_at"] = now
                    print_json({
                        "type": "gap_warning",
                        "seconds_since_last_event": round(gap, 2),
                        "last_event_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_at)),
                    })
            if config.heartbeat_seconds > 0 and now >= next_heartbeat_at:
                elapsed = max(0.001, now - started_at)
                print_json({
                    "type": "heartbeat",
                    "elapsed_seconds": round(elapsed, 2),
                    "single_callbacks": current["single_callbacks"],
                    "delta_single_callbacks": current["single_callbacks"] - previous["single_callbacks"],
                    "generic_quote_events": current["generic_quote_events"],
                    "delta_generic_quote_events": current["generic_quote_events"] - previous["generic_quote_events"],
                    "wire_quote_events": current["wire_quote_events"],
                    "delta_wire_quote_events": current["wire_quote_events"] - previous["wire_quote_events"],
                    "seconds_since_last_event": round(now - last_at, 2) if last_at else None,
                })
                previous = current
                next_heartbeat_at = now + config.heartbeat_seconds
            time.sleep(0.2)
    finally:
        subscribe_id = subscribe_id_box.get("value")
        if subscribe_id is not None:
            try:
                result = xtdata.unsubscribe_quote(subscribe_id)
                print_json({"type": "unsubscribed", "subscribe_id": subscribe_id, "result": result})
            except Exception as error:
                print_json({
                    "type": "unsubscribe_failed",
                    "subscribe_id": subscribe_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                })
        try:
            client.remove_callback("quote", on_generic_quote)
            client.remove_callback("__event__", on_wire_event)
        except Exception:
            pass
        close_default_client()

    summary = snapshot()
    summary.pop("last_gap_warning_at", None)
    elapsed = max(0.001, time.time() - started_at)
    summary.update({
        "type": "summary",
        "elapsed_seconds": round(elapsed, 2),
        "events_per_second": round(
            (
                summary["single_callbacks"]
                + summary["generic_quote_events"]
                + summary["wire_quote_events"]
            ) / elapsed,
            4,
        ),
        "ok": summary["single_callbacks"] > 0,
    })
    print_json(summary)
    return 0 if summary["single_callbacks"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
