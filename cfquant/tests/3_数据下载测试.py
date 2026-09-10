# -*- coding: utf-8 -*-
from types import SimpleNamespace
import time

from _helpers import (
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


# ======================== 用户配置区 ========================
# 直接修改下面的配置，然后运行本文件；不读取命令行参数。
TRANSPORT = "auto"       # auto 自动发现；也可填写 ctypes、web_lttx 或 lttx
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0    # 请求超时，单位秒
STOCK_LIST = "000001.SZ"   # 多个证券用逗号分隔
PERIOD = "1d"
START_TIME = ""           # 例如 20260101；留空使用 QMT 默认范围
END_TIME = ""
WAIT_SECONDS = 5.0        # 提交下载后等待回调的秒数
VERIFY_COUNT = 5          # 下载后读取的本地数据条数，0 不验证
INCLUDE_FINANCIAL = False
FINANCIAL_TABLES = "ASHAREBALANCESHEET"  # 多个表名用逗号分隔
FINANCIAL_FIELDS = "ASHAREBALANCESHEET.fix_assets"  # 留空只下载不读取
FINANCIAL_REPORT_TYPE = "announce_time"
# ===========================================================


def main():
    configure_stdout()
    config = SimpleNamespace(
        transport=TRANSPORT,
        bridge_id=BRIDGE_ID,
        timeout=REQUEST_TIMEOUT,
        stock_list=STOCK_LIST,
        period=PERIOD,
        start_time=START_TIME,
        end_time=END_TIME,
        wait_seconds=WAIT_SECONDS,
        verify_count=VERIFY_COUNT,
        include_financial=INCLUDE_FINANCIAL,
        financial_tables=FINANCIAL_TABLES,
        financial_fields=FINANCIAL_FIELDS,
        financial_report_type=FINANCIAL_REPORT_TYPE,
    )
    configure_cfquant(config)

    stock_list = parse_csv(config.stock_list, default=["000001.SZ"], upper=True)
    financial_tables = parse_csv(config.financial_tables, default=[])
    financial_fields = parse_csv(config.financial_fields, default=[])
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
        "transport": config.transport,
        "bridge_id": config.bridge_id,
        "stock_list": stock_list,
        "period": config.period,
        "start_time": config.start_time,
        "end_time": config.end_time,
    })
    try:
        download_ok = False
        result = None
        started = time.perf_counter()
        try:
            # 优先演示批量下载接口，和 xtquant.download_history_data2 的调用方式保持接近。
            result = xtdata.download_history_data2(
                stock_list,
                config.period,
                start_time=config.start_time,
                end_time=config.end_time,
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
                    config.period,
                    start_time=config.start_time,
                    end_time=config.end_time,
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
        if config.wait_seconds > 0:
            print_json({"type": "wait_callbacks", "seconds": config.wait_seconds})
            time.sleep(config.wait_seconds)
        if config.verify_count > 0 and stock_list:
            started = time.perf_counter()
            try:
                # 下载完成后立即读本地行情做验证，返回非空通常说明 QMT 本地数据已落地。
                verify_result = xtdata.get_market_data(
                    field_list=["open", "high", "low", "close", "volume"],
                    stock_list=[stock_list[0]],
                    period=config.period,
                    count=config.verify_count,
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
        if config.include_financial and stock_list:
            emit_call(
                "download_financial_data",
                lambda: xtdata.download_financial_data(
                    stock_list,
                    table_list=financial_tables,
                    start_time=config.start_time,
                    end_time=config.end_time,
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
                        start_time=config.start_time,
                        end_time=config.end_time,
                        report_type=config.financial_report_type,
                    ),
                    example="xtdata.get_financial_data(financial_fields, stock_list, start_time, end_time)",
                )
            else:
                emit_skip("get_financial_data", "FINANCIAL_FIELDS 为空，财务读取验证已跳过。")
        else:
            emit_skip(
                "download_financial_data",
                "INCLUDE_FINANCIAL = False，默认只测试历史行情下载。",
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
