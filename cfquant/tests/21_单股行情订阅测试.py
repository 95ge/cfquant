# -*- coding: utf-8 -*-
import argparse
import signal
import threading
import time

from _helpers import close_default_client, compact_value, configure_stdout, print_json

from cfquant import configure, get_client, xtdata


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
    parser = argparse.ArgumentParser(description="cfquant 单股行情订阅回调测试")
    parser.add_argument("--stock-code", default="000001.SZ", help="订阅证券代码，默认 000001.SZ。")
    parser.add_argument("--period", default="tick", help="订阅周期，默认 tick；也可传 1d、1m 等。")
    parser.add_argument("--start-time", default="", help="开始时间，默认空。")
    parser.add_argument("--end-time", default="", help="结束时间，默认空。")
    parser.add_argument("--count", type=int, default=0, help="订阅数量参数，默认 0。")
    parser.add_argument("--seconds", type=float, default=12.0, help="测试运行秒数，默认 12 秒。")
    parser.add_argument("--transport", default="auto", help="通信模式，默认 auto；跨机器建议 web_lttx。")
    parser.add_argument("--host", default=None, help="LTtx 地址；不传则使用 cfquant 默认配置。")
    parser.add_argument("--port", type=int, default=None, help="LTtx 端口；不传则使用 cfquant 默认配置。")
    parser.add_argument("--token", default=None, help="LTtx token；不传则使用 cfquant 默认配置。")
    parser.add_argument("--bridge-id", default="default", help="桥接 ID，默认 default。")
    parser.add_argument("--timeout", type=float, default=15.0, help="请求超时秒数，默认 15。")
    parser.add_argument("--use-quote2", action="store_true", help="改用 xtdata.subscribe_quote2。")
    parser.add_argument("--dividend-type", default="none", help="subscribe_quote2 的复权参数，默认 none。")
    parser.add_argument("--sample-codes", type=int, default=3, help="每次回调打印几个样例代码，默认 3。")
    parser.add_argument("--heartbeat-seconds", type=float, default=3.0, help="心跳统计间隔，默认 3 秒；0 表示关闭。")
    parser.add_argument("--gap-warning-seconds", type=float, default=5.0, help="超过多少秒无回调时提示，默认 5 秒；0 表示关闭。")
    args = parser.parse_args()

    configure_kwargs = {
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "timeout": args.timeout,
    }
    if args.host is not None:
        configure_kwargs["host"] = args.host
    if args.port is not None:
        configure_kwargs["port"] = args.port
    if args.token is not None:
        configure_kwargs["token"] = args.token
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
        row.update(_summarize_quote_payload(payload, sample_codes=args.sample_codes))
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
    next_heartbeat_at = started_at + max(0.1, args.heartbeat_seconds)
    previous = snapshot()

    print_json({
        "type": "start",
        "transport": args.transport,
        "host": args.host,
        "port": args.port,
        "bridge_id": args.bridge_id,
        "stock_code": args.stock_code,
        "period": args.period,
        "seconds": args.seconds,
        "api": "xtdata.subscribe_quote2" if args.use_quote2 else "xtdata.subscribe_quote",
    })

    try:
        if args.use_quote2:
            subscribe_id = xtdata.subscribe_quote2(
                args.stock_code,
                period=args.period,
                start_time=args.start_time,
                end_time=args.end_time,
                count=args.count,
                dividend_type=args.dividend_type,
                callback=on_single_quote,
            )
        else:
            subscribe_id = xtdata.subscribe_quote(
                args.stock_code,
                period=args.period,
                start_time=args.start_time,
                end_time=args.end_time,
                count=args.count,
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
                        "seconds_since_last_event": round(gap, 2),
                        "last_event_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_at)),
                    })
            if args.heartbeat_seconds > 0 and now >= next_heartbeat_at:
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
                next_heartbeat_at = now + args.heartbeat_seconds
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
