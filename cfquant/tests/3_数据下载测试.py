# -*- coding: utf-8 -*-
import argparse
import time

from _helpers import (
    add_runtime_args,
    close_default_client,
    configure_cfquant,
    configure_stdout,
    emit_call,
    emit_skip,
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
    parser.add_argument("--include-financial", action="store_true", help="同时演示财务数据下载/读取调用。")
    parser.add_argument("--financial-tables", default="ASHAREBALANCESHEET", help="财务下载表名，逗号分隔，默认 ASHAREBALANCESHEET。")
    parser.add_argument("--financial-fields", default="ASHAREBALANCESHEET.fix_assets", help="财务读取字段，逗号分隔；留空则只演示下载。")
    parser.add_argument("--financial-report-type", default="announce_time", help="财务读取报告口径，默认 announce_time。")
    args = parser.parse_args()
    configure_cfquant(args)

    stock_list = parse_csv(args.stock_list, default=["000001.SZ"], upper=True)
    financial_tables = parse_csv(args.financial_tables, default=[])
    financial_fields = parse_csv(args.financial_fields, default=[])
    progress_events = []
    financial_progress_events = []

    def on_download_progress(data):
        # 历史行情下载的进度回调由 QMT 侧推回，适合检查长任务事件链路。
        progress_events.append(data)
        print_json({
            "type": "download_callback",
            "event_no": len(progress_events),
            "summary": summarize(data, sample_size=1),
        })

    def on_financial_progress(data):
        # 财务下载能力取决于当前 QMT 环境；有回调时同样按 JSON 行输出。
        financial_progress_events.append(data)
        print_json({
            "type": "financial_download_callback",
            "event_no": len(financial_progress_events),
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
            # 优先演示批量下载接口，和 xtquant.download_history_data2 的调用方式保持接近。
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
                "example": "xtdata.download_history_data2(stock_list, period, start_time, end_time, callback=on_download_progress)",
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
                "example": "xtdata.download_history_data2(stock_list, period, start_time, end_time, callback=on_download_progress)",
            })
            if not stock_list:
                raise
            started = time.perf_counter()
            try:
                # 兼容老版本 QMT：批量接口不可用时，用单证券 download_history_data 兜底。
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
                    "example": "xtdata.download_history_data(stock_code, period, start_time, end_time)",
                })
            except Exception as fallback_error:
                print_json({
                    "case": "download_history_data",
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "stock_code": stock_list[0],
                    "error_type": type(fallback_error).__name__,
                    "error": str(fallback_error),
                    "example": "xtdata.download_history_data(stock_code, period, start_time, end_time)",
                })
        if args.wait_seconds > 0:
            print_json({"type": "wait_callbacks", "seconds": args.wait_seconds})
            time.sleep(args.wait_seconds)
        if args.verify_count > 0 and stock_list:
            started = time.perf_counter()
            try:
                # 下载完成后立即读本地行情做验证，返回非空通常说明 QMT 本地数据已落地。
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
                    "example": "xtdata.get_market_data(field_list, [stock_code], period, count=verify_count)",
                })
            except Exception as error:
                print_json({
                    "case": "verify_get_market_data",
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "example": "xtdata.get_market_data(field_list, [stock_code], period, count=verify_count)",
                })
        if args.include_financial and stock_list:
            emit_call(
                "download_financial_data",
                lambda: xtdata.download_financial_data(
                    stock_list,
                    table_list=financial_tables,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    callback=on_financial_progress,
                    keep_callback=True,
                ),
                example="xtdata.download_financial_data(stock_list, table_list, start_time, end_time, callback=on_financial_progress)",
            )
            if financial_fields:
                emit_call(
                    "get_financial_data",
                    lambda: xtdata.get_financial_data(
                        financial_fields,
                        stock_list,
                        start_time=args.start_time,
                        end_time=args.end_time,
                        report_type=args.financial_report_type,
                    ),
                    example="xtdata.get_financial_data(financial_fields, stock_list, start_time, end_time)",
                )
            else:
                emit_skip("get_financial_data", "未传 --financial-fields，财务读取验证已跳过。")
        else:
            emit_skip(
                "download_financial_data",
                "未传 --include-financial，默认只测试历史行情下载。",
                example="xtdata.download_financial_data(stock_list, table_list, start_time, end_time, callback=on_financial_progress)",
            )
        print_json({
            "type": "summary",
            "ok": download_ok,
            "download_result": summarize(result),
            "download_callback_events": len(progress_events),
            "financial_download_callback_events": len(financial_progress_events),
        })
    finally:
        close_default_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
