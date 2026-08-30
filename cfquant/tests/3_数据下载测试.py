# -*- coding: utf-8 -*-
import argparse
import time

from _helpers import (
    add_runtime_args,
    close_default_client,
    configure_cfquant,
    configure_stdout,
    parse_csv,
    print_json,
    summarize,
)

from cfquant import xtdata


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="cfquant 历史行情下载测试。")
    add_runtime_args(parser)
    parser.add_argument("--stock-list", default="000001.SZ", help="要下载的证券列表，逗号分隔。")
    parser.add_argument("--period", default="1d", help="周期，默认 1d。")
    parser.add_argument("--start-time", default="", help="开始时间，例如 20260101，可留空。")
    parser.add_argument("--end-time", default="", help="结束时间，例如 20260821，可留空。")
    parser.add_argument("--wait-seconds", type=float, default=5.0, help="提交下载后继续等待回调的秒数。")
    parser.add_argument("--verify-count", type=int, default=5, help="下载后读取几条本地数据验证。0 表示不验证。")
    args = parser.parse_args()
    configure_cfquant(args)

    stock_list = parse_csv(args.stock_list, default=["000001.SZ"], upper=True)
    progress_events = []

    def on_download_progress(data):
        progress_events.append(data)
        print_json({
            "type": "download_callback",
            "event_no": len(progress_events),
            "summary": summarize(data, sample_size=1),
        })

    print_json({
        "type": "start",
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "stock_list": stock_list,
        "period": args.period,
        "start_time": args.start_time,
        "end_time": args.end_time,
    })
    try:
        download_ok = False
        result = None
        started = time.perf_counter()
        try:
            result = xtdata.download_history_data2(
                stock_list,
                args.period,
                start_time=args.start_time,
                end_time=args.end_time,
                callback=on_download_progress,
                keep_callback=True,
            )
            download_ok = True
            print_json({
                "case": "download_history_data2",
                "ok": True,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "summary": summarize(result),
            })
        except Exception as error:
            message = str(error)
            print_json({
                "case": "download_history_data2",
                "ok": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": type(error).__name__,
                "error": message,
                "fallback": "download_history_data",
            })
            if not stock_list:
                raise
            started = time.perf_counter()
            try:
                result = xtdata.download_history_data(
                    stock_list[0],
                    args.period,
                    start_time=args.start_time,
                    end_time=args.end_time,
                )
                download_ok = True
                print_json({
                    "case": "download_history_data",
                    "ok": True,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "stock_code": stock_list[0],
                    "summary": summarize(result),
                })
            except Exception as fallback_error:
                print_json({
                    "case": "download_history_data",
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "stock_code": stock_list[0],
                    "error_type": type(fallback_error).__name__,
                    "error": str(fallback_error),
                })
        if args.wait_seconds > 0:
            print_json({"type": "wait_callbacks", "seconds": args.wait_seconds})
            time.sleep(args.wait_seconds)
        if args.verify_count > 0 and stock_list:
            started = time.perf_counter()
            try:
                verify_result = xtdata.get_market_data(
                    field_list=["open", "high", "low", "close", "volume"],
                    stock_list=[stock_list[0]],
                    period=args.period,
                    count=args.verify_count,
                    dividend_type="none",
                    fill_data=True,
                )
                print_json({
                    "case": "verify_get_market_data",
                    "ok": True,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "summary": summarize(verify_result),
                })
            except Exception as error:
                print_json({
                    "case": "verify_get_market_data",
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error_type": type(error).__name__,
                    "error": str(error),
                })
        print_json({
            "type": "summary",
            "ok": download_ok,
            "download_result": summarize(result),
            "download_callback_events": len(progress_events),
        })
    finally:
        close_default_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
