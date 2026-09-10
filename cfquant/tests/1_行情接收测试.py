# -*- coding: utf-8 -*-
from types import SimpleNamespace
import signal
import threading
import time

from _helpers import (
    close_default_client,
    compact_value,
    configure_cfquant,
    configure_stdout,
    parse_csv,
    print_json,
)

from cfquant import xtdata


# ======================== 用户配置区 ========================
# 直接修改下面的配置，然后运行本文件；不读取命令行参数。
TRANSPORT = "auto"       # auto 自动发现；也可填写 ctypes、web_lttx 或 lttx
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0    # 请求超时，单位秒
MARKETS = "SH,SZ"         # 市场或证券代码用逗号分隔，例如 SH,SZ,BJ 或 rb2610.SF
STOCK_CODE = "000001.SZ"  # 仅 INCLUDE_SINGLE_QUOTE/INCLUDE_SINGLE_QUOTE2 为 True 时使用
SINGLE_PERIOD = "1d"
DIVIDEND_TYPE = "none"
INCLUDE_SINGLE_QUOTE = False
INCLUDE_SINGLE_QUOTE2 = False
SECONDS = 0.0            # 0 表示持续运行，直到 Ctrl+C
SAMPLE_CODES = 3
HEARTBEAT_SECONDS = 5.0   # 0 关闭心跳统计
GAP_WARNING_SECONDS = 8.0 # 0 关闭无回调提示
# ===========================================================


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


def detect_market(code):
    value = str(code or "").strip().upper()
    if "." in value:
        return value.rsplit(".", 1)[-1] or "UNKNOWN"
    if value.endswith(".SH") or value.startswith("SH"):
        return "SH"
    if value.endswith(".SZ") or value.startswith("SZ"):
        return "SZ"
    return "UNKNOWN"


def count_markets(codes):
    counts = {}
    for code in codes:
        market = detect_market(code)
        counts[market] = counts.get(market, 0) + 1
    return counts


def main():
    configure_stdout()
    config = SimpleNamespace(
        transport=TRANSPORT,
        bridge_id=BRIDGE_ID,
        timeout=REQUEST_TIMEOUT,
        markets=MARKETS,
        stock_code=STOCK_CODE,
        single_period=SINGLE_PERIOD,
        dividend_type=DIVIDEND_TYPE,
        include_single_quote=INCLUDE_SINGLE_QUOTE,
        include_single_quote2=INCLUDE_SINGLE_QUOTE2,
        seconds=SECONDS,
        sample_codes=SAMPLE_CODES,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        gap_warning_seconds=GAP_WARNING_SECONDS,
    )
    configure_cfquant(config)

    markets = parse_csv(config.markets, default=["SH", "SZ"])
    stock_code = str(config.stock_code or "").strip().upper()
    stop_event = threading.Event()
    stats_lock = threading.Lock()
    stats = {
        "events": 0,
        "total_codes": 0,
        "first_at": 0.0,
        "last_at": 0.0,
        "last_gap_warning_at": 0.0,
        "unique_codes": set(),
    }

    def snapshot():
        with stats_lock:
            current = dict(stats)
            unique_codes = sorted(current.pop("unique_codes", set()))
        current["unique_code_count"] = len(unique_codes)
        current["unique_market_counts"] = count_markets(unique_codes)
        current["unique_sample"] = unique_codes[: max(1, int(config.sample_codes))]
        return current

    def emit_quote_callback(source, data):
        # 三类订阅的回调都汇总到同一套统计里，方便比较是否持续收到行情事件。
        now = time.time()
        code_count = len(data) if isinstance(data, dict) else 0
        codes = [str(code) for code in data.keys()] if isinstance(data, dict) else []
        with stats_lock:
            stats["events"] += 1
            stats["total_codes"] += code_count
            stats["unique_codes"].update(codes)
            stats["first_at"] = stats["first_at"] or now
            stats["last_at"] = now
            event_no = stats["events"]
            unique_codes = sorted(stats["unique_codes"])
        row = {
            "type": "callback",
            "source": source,
            "event_no": event_no,
            "received_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "callback_market_counts": count_markets(codes),
            "unique_code_count": len(unique_codes),
            "unique_market_counts": count_markets(unique_codes),
            "unique_sample": unique_codes[: max(1, int(config.sample_codes))],
        }
        row.update(summarize_quote_payload(data, sample_codes=config.sample_codes))
        print_json(row)

    def on_whole_quote(data):
        emit_quote_callback("subscribe_whole_quote", data)

    def on_single_quote(data):
        emit_quote_callback("subscribe_quote", data)

    def on_single_quote2(data):
        emit_quote_callback("subscribe_quote2", data)

    def request_stop(signum=None, frame=None):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    try:
        signal.signal(signal.SIGTERM, request_stop)
    except Exception:
        pass

    started_at = time.time()
    next_heartbeat_at = started_at + max(0.1, config.heartbeat_seconds)
    previous_events = 0
    previous_codes = 0
    subscribe_items = []

    print_json({
        "type": "start",
        "transport": config.transport,
        "bridge_id": config.bridge_id,
        "markets": markets,
        "subscription": "whole_quote",
        "single_quote_example_stock_code": stock_code,
        "single_period": config.single_period,
        "seconds": config.seconds,
        "callback_style": "xtdata.subscribe_whole_quote(markets, callback=on_whole_quote)",
        "extra_examples": {
            "subscribe_quote": bool(config.include_single_quote),
            "subscribe_quote2": bool(config.include_single_quote2),
        },
    })
    try:
        # 全推行情订阅：适合验证 QMT 到外部 Python 的长连接回调链路。
        subscribe_id = xtdata.subscribe_whole_quote(markets, callback=on_whole_quote)
        subscribe_items.append(("subscribe_whole_quote", subscribe_id))
        print_json({
            "type": "subscribed",
            "source": "subscribe_whole_quote",
            "subscribe_id": subscribe_id,
            "example": "xtdata.subscribe_whole_quote(markets, callback=on_whole_quote)",
            "hint": "按 Ctrl+C 停止测试。",
        })

        # 单证券订阅默认不开启，需要时设置 INCLUDE_SINGLE_QUOTE = True。
        if config.include_single_quote:
            single_subscribe_id = xtdata.subscribe_quote(
                stock_code,
                period=config.single_period,
                callback=on_single_quote,
            )
            subscribe_items.append(("subscribe_quote", single_subscribe_id))
            print_json({
                "type": "subscribed",
                "source": "subscribe_quote",
                "subscribe_id": single_subscribe_id,
                "example": "xtdata.subscribe_quote(stock_code, period=single_period, callback=on_single_quote)",
            })

        # subscribe_quote2 与 subscribe_quote 类似，额外演示 dividend_type 参数。
        if config.include_single_quote2:
            single_subscribe2_id = xtdata.subscribe_quote2(
                stock_code,
                period=config.single_period,
                dividend_type=config.dividend_type,
                callback=on_single_quote2,
            )
            subscribe_items.append(("subscribe_quote2", single_subscribe2_id))
            print_json({
                "type": "subscribed",
                "source": "subscribe_quote2",
                "subscribe_id": single_subscribe2_id,
                "example": "xtdata.subscribe_quote2(stock_code, period=single_period, dividend_type=dividend_type, callback=on_single_quote2)",
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
                        "events": current["events"],
                        "seconds_since_last_callback": round(gap, 2),
                        "last_callback_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_at)),
                    })
            if config.heartbeat_seconds > 0 and now >= next_heartbeat_at:
                elapsed = max(0.001, now - started_at)
                print_json({
                    "type": "heartbeat",
                    "elapsed_seconds": round(elapsed, 2),
                    "events": current["events"],
                    "delta_events": current["events"] - previous_events,
                    "total_codes": current["total_codes"],
                    "delta_codes": current["total_codes"] - previous_codes,
                    "unique_code_count": current["unique_code_count"],
                    "unique_market_counts": current["unique_market_counts"],
                    "unique_sample": current["unique_sample"],
                    "events_per_second": round(current["events"] / elapsed, 4),
                    "seconds_since_last_callback": round(now - last_at, 2) if last_at else None,
                })
                previous_events = current["events"]
                previous_codes = current["total_codes"]
                next_heartbeat_at = now + config.heartbeat_seconds
            time.sleep(0.2)
    finally:
        # 退出时逐个取消订阅，并移除本地 callback，避免下次运行收到旧订阅事件。
        for source, subscribe_id in reversed(subscribe_items):
            if subscribe_id is None:
                continue
            try:
                result = xtdata.unsubscribe_quote(subscribe_id)
                print_json({"type": "unsubscribed", "source": source, "subscribe_id": subscribe_id, "result": result})
            except Exception as error:
                print_json({"type": "unsubscribe_failed", "source": source, "subscribe_id": subscribe_id, "error": str(error)})
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
