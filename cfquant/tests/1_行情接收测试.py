# -*- coding: utf-8 -*-
import argparse
import signal
import threading
import time

from _helpers import (
    add_runtime_args,
    close_default_client,
    compact_value,
    configure_cfquant,
    configure_stdout,
    parse_csv,
    print_json,
)

from cfquant import xtdata


def summarize_quote_payload(payload, sample_codes=3):
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


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="cfquant 全推行情接收测试，回调用法接近 xtquant。")
    add_runtime_args(parser)
    parser.add_argument("--markets", default="SH,SZ", help="订阅市场，默认 SH,SZ。")
    parser.add_argument("--seconds", type=float, default=0.0, help="运行秒数。默认 0 表示一直运行，直到 Ctrl+C。")
    parser.add_argument("--sample-codes", type=int, default=3, help="每条回调打印几个样例代码。")
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0, help="心跳统计间隔。0 表示关闭。")
    parser.add_argument("--gap-warning-seconds", type=float, default=8.0, help="超过多少秒无回调时提示。0 表示关闭。")
    args = parser.parse_args()
    configure_cfquant(args)

    markets = parse_csv(args.markets, default=["SH", "SZ"], upper=True)
    stop_event = threading.Event()
    stats_lock = threading.Lock()
    stats = {
        "events": 0,
        "total_codes": 0,
        "first_at": 0.0,
        "last_at": 0.0,
        "last_gap_warning_at": 0.0,
    }

    def snapshot():
        with stats_lock:
            return dict(stats)

    def on_whole_quote(data):
        now = time.time()
        code_count = len(data) if isinstance(data, dict) else 0
        with stats_lock:
            stats["events"] += 1
            stats["total_codes"] += code_count
            stats["first_at"] = stats["first_at"] or now
            stats["last_at"] = now
            event_no = stats["events"]
        row = {
            "type": "callback",
            "event_no": event_no,
            "received_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        }
        row.update(summarize_quote_payload(data, sample_codes=args.sample_codes))
        print_json(row)

    def request_stop(signum=None, frame=None):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    try:
        signal.signal(signal.SIGTERM, request_stop)
    except Exception:
        pass

    started_at = time.time()
    next_heartbeat_at = started_at + max(0.1, args.heartbeat_seconds)
    previous_events = 0
    previous_codes = 0
    subscribe_id = None

    print_json({
        "type": "start",
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "markets": markets,
        "seconds": args.seconds,
        "callback_style": "xtdata.subscribe_whole_quote(markets, callback=on_whole_quote)",
    })
    try:
        subscribe_id = xtdata.subscribe_whole_quote(markets, callback=on_whole_quote)
        print_json({
            "type": "subscribed",
            "subscribe_id": subscribe_id,
            "hint": "按 Ctrl+C 停止测试。",
        })
        while not stop_event.is_set():
            now = time.time()
            if args.seconds > 0 and now - started_at >= args.seconds:
                break
            current = snapshot()
            last_at = float(current.get("last_at") or 0)
            if args.gap_warning_seconds > 0 and last_at:
                gap = now - last_at
                if gap >= args.gap_warning_seconds and now - current.get("last_gap_warning_at", 0) >= args.gap_warning_seconds:
                    with stats_lock:
                        stats["last_gap_warning_at"] = now
                    print_json({
                        "type": "gap_warning",
                        "events": current["events"],
                        "seconds_since_last_callback": round(gap, 2),
                        "last_callback_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_at)),
                    })
            if args.heartbeat_seconds > 0 and now >= next_heartbeat_at:
                elapsed = max(0.001, now - started_at)
                print_json({
                    "type": "heartbeat",
                    "elapsed_seconds": round(elapsed, 2),
                    "events": current["events"],
                    "delta_events": current["events"] - previous_events,
                    "total_codes": current["total_codes"],
                    "delta_codes": current["total_codes"] - previous_codes,
                    "events_per_second": round(current["events"] / elapsed, 4),
                    "seconds_since_last_callback": round(now - last_at, 2) if last_at else None,
                })
                previous_events = current["events"]
                previous_codes = current["total_codes"]
                next_heartbeat_at = now + args.heartbeat_seconds
            time.sleep(0.2)
    finally:
        if subscribe_id is not None:
            try:
                result = xtdata.unsubscribe_quote(subscribe_id)
                print_json({"type": "unsubscribed", "subscribe_id": subscribe_id, "result": result})
            except Exception as error:
                print_json({"type": "unsubscribe_failed", "subscribe_id": subscribe_id, "error": str(error)})
        close_default_client()

    summary = snapshot()
    summary.pop("last_gap_warning_at", None)
    elapsed = max(0.001, time.time() - started_at)
    summary.update({
        "type": "summary",
        "elapsed_seconds": round(elapsed, 2),
        "events_per_second": round(summary["events"] / elapsed, 4),
        "avg_codes_per_event": round(summary["total_codes"] / summary["events"], 2) if summary["events"] else 0,
    })
    print_json(summary)
    return 0 if summary["events"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

