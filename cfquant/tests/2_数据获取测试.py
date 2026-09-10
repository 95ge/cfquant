# -*- coding: utf-8 -*-
from types import SimpleNamespace
import json
import time

from _helpers import (
    close_default_client,
    configure_cfquant,
    configure_stdout,
    discover_data_provider_route,
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
STOCK_LIST = "000001.SZ,600000.SH"  # 多个证券用逗号分隔
STOCK_CODE = "000001.SZ"
PERIOD = "1d"
COUNT = 5
START_TIME = ""           # 例如 20260101；留空使用 QMT 默认范围
END_TIME = ""
SECTOR_NAME = "沪深A股"
INDEX_CODE = "000300.SH"
ETF_MARKET = "SH"
FINANCIAL_FIELDS = "ASHAREBALANCESHEET.fix_assets"  # 逗号分隔，留空跳过
FINANCIAL_REPORT_TYPE = "announce_time"
FACTOR_FIELDS = ""        # 逗号分隔，留空跳过因子查询
OPTION_CODE = ""          # 留空跳过期权详情
OPTION_UNDERLYING = "510050.SH"
OPTION_DATE = ""          # 例如 202609；留空跳过期权列表
JSON_OUTPUT = False
# ===========================================================


TOTAL_CASES = 22


class ChineseReporter:
    """为手工测试提供易读中文输出，同时保留逐行 JSON 模式。"""

    def __init__(self, json_output=False):
        self.json_output = json_output
        self.current = 0
        self.success_count = 0
        self.failure_count = 0
        self.skipped_count = 0
        self.started_at = time.perf_counter()

    @staticmethod
    def _write(message=""):
        print(message, flush=True)

    def start(self, payload):
        if self.json_output:
            print_json(payload)
            return

        self._write("=" * 72)
        self._write("cfquant 数据获取测试")
        self._write("=" * 72)
        self._write(f"通信配置：{payload['transport']} / 桥接 ID {payload['bridge_id']}")
        route = payload.get("runtime_route") or {}
        if route:
            mode_labels = {"ctypes": "通用模式", "lite": "极致模式", "lttx": "高级模式"}
            mode = str(route.get("mode") or "未知")
            self._write(
                f"行情源识别：Web 已识别为{mode_labels.get(mode, mode)}，"
                f"桥接 ID {route.get('bridge_id') or 'default'}"
            )
            self._write(f"行情通道：{'在线' if route.get('online') else '未在线或状态尚未刷新'}")
        elif payload["transport"] == "auto":
            self._write("行情源识别：未从 Web 读取到路由，将继续使用 cfquant 自动发现。")
        self._write(f"测试证券：{', '.join(payload['stock_list'])}")
        self._write(f"主要证券：{payload['stock_code']}")
        self._write(f"行情参数：周期 {payload['period']}，最多 {payload['count']} 条")
        time_range = f"{payload['start_time'] or '默认开始时间'} 至 {payload['end_time'] or '默认结束时间'}"
        self._write(f"时间范围：{time_range}")
        self._write(f"计划检查：{TOTAL_CASES} 个接口（部分接口可能因未提供参数而跳过）")

    def section(self, number, title, description):
        if self.json_output:
            return
        self._write()
        self._write("-" * 72)
        self._write(f"第 {number} 阶段：{title}")
        self._write(f"目的：{description}")
        self._write("-" * 72)

    def call(self, name, title, description, func, example=None):
        self.current += 1
        if not self.json_output:
            self._write()
            self._write(f"[{self.current:02d}/{TOTAL_CASES}] {title}")
            self._write(f"  说明：{description}")
            if example:
                self._write(f"  调用：{example}")
            self._write("  状态：正在请求数据...")

        started = time.perf_counter()
        try:
            result = func()
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            self.success_count += 1
            result_summary = summarize(result)
            if self.json_output:
                payload = {
                    "case": name,
                    "ok": True,
                    "latency_ms": latency_ms,
                    "summary": result_summary,
                }
                if example:
                    payload["example"] = example
                print_json(payload)
            else:
                self._write(f"  状态：成功，耗时 {latency_ms:.2f} 毫秒")
                self._print_result_summary(result_summary)
            return result
        except Exception as error:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            self.failure_count += 1
            if self.json_output:
                payload = {
                    "case": name,
                    "ok": False,
                    "latency_ms": latency_ms,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                if example:
                    payload["example"] = example
                print_json(payload)
            else:
                self._write(f"  状态：失败，耗时 {latency_ms:.2f} 毫秒")
                self._write(f"  错误：{type(error).__name__}: {error}")
                self._write("  提示：已记录本项错误，将继续执行后续测试。")
            return None

    def skip(self, name, title, reason, example=None):
        self.current += 1
        self.skipped_count += 1
        if self.json_output:
            payload = {
                "case": name,
                "ok": False,
                "skipped": True,
                "reason": reason,
            }
            if example:
                payload["example"] = example
            print_json(payload)
            return

        self._write()
        self._write(f"[{self.current:02d}/{TOTAL_CASES}] {title}")
        self._write("  状态：已跳过")
        self._write(f"  原因：{reason}")

    def finish(self):
        elapsed = round(time.perf_counter() - self.started_at, 2)
        summary = {
            "type": "summary",
            "ok": self.failure_count == 0,
            "success": self.success_count,
            "failed": self.failure_count,
            "skipped": self.skipped_count,
            "elapsed_seconds": elapsed,
        }
        if self.json_output:
            print_json(summary)
            return

        self._write()
        self._write("=" * 72)
        self._write("测试完成")
        self._write("=" * 72)
        self._write(
            f"执行结果：成功 {self.success_count} 项，失败 {self.failure_count} 项，"
            f"跳过 {self.skipped_count} 项"
        )
        self._write(f"总耗时：{elapsed:.2f} 秒")
        if self.failure_count:
            self._write("结论：存在调用失败，请根据对应步骤中的错误信息检查 QMT 环境或接口支持情况。")
        else:
            self._write("结论：所有已执行的数据获取接口均调用成功。")

    def _print_result_summary(self, summary):
        result_type = summary.get("type", "未知")
        if result_type == "None":
            self._write("  返回：空值（None）")
            return
        if "shape" in summary:
            shape = " x ".join(str(item) for item in summary["shape"])
            self._write(f"  返回：{result_type}，数据形状 {shape}")
            if summary.get("columns"):
                self._write(f"  字段：{', '.join(summary['columns'])}")
            if summary.get("head"):
                self._write("  前两行：")
                for line in str(summary["head"]).splitlines():
                    self._write(f"    {line}")
            return
        if result_type == "dict":
            self._write(f"  返回：字典，共 {summary.get('len', 0)} 项")
            if summary.get("keys"):
                self._write(f"  键名：{', '.join(summary['keys'])}")
        elif result_type == "list":
            self._write(f"  返回：列表，共 {summary.get('len', 0)} 项")
        else:
            self._write(f"  返回：{result_type}")

        preview = summary.get("sample")
        if preview:
            self._write("  样例：")
            preview_text = json.dumps(preview, ensure_ascii=False, default=str, indent=2)
            for line in preview_text.splitlines():
                self._write(f"    {line}")
        elif "repr" in summary:
            self._write(f"  内容：{summary['repr']}")


def main():
    configure_stdout()
    config = SimpleNamespace(
        transport=TRANSPORT,
        bridge_id=BRIDGE_ID,
        timeout=REQUEST_TIMEOUT,
        stock_list=STOCK_LIST,
        stock_code=STOCK_CODE,
        period=PERIOD,
        count=COUNT,
        start_time=START_TIME,
        end_time=END_TIME,
        sector_name=SECTOR_NAME,
        index_code=INDEX_CODE,
        etf_market=ETF_MARKET,
        financial_fields=FINANCIAL_FIELDS,
        financial_report_type=FINANCIAL_REPORT_TYPE,
        factor_fields=FACTOR_FIELDS,
        option_code=OPTION_CODE,
        option_underlying=OPTION_UNDERLYING,
        option_date=OPTION_DATE,
        json=JSON_OUTPUT,
    )
    runtime_route = discover_data_provider_route() if config.transport == "auto" else {}
    if runtime_route.get("bridge_id") and config.bridge_id == "default":
        config.bridge_id = runtime_route["bridge_id"]
    configure_cfquant(config)

    stock_list = parse_csv(config.stock_list, default=["000001.SZ", "600000.SH"], upper=True)
    stock_code = str(config.stock_code or stock_list[0]).strip().upper()
    financial_fields = parse_csv(config.financial_fields, default=[])
    factor_fields = parse_csv(config.factor_fields, default=[])
    option_code = str(config.option_code or "").strip().upper()
    option_date = str(config.option_date or "").strip()

    reporter = ChineseReporter(json_output=config.json)
    reporter.start({
        "type": "start",
        "transport": config.transport,
        "bridge_id": config.bridge_id,
        "runtime_route": runtime_route,
        "stock_list": stock_list,
        "stock_code": stock_code,
        "period": config.period,
        "count": config.count,
        "start_time": config.start_time,
        "end_time": config.end_time,
    })
    try:
        reporter.section(1, "实时行情快照", "检查能否一次获取多只证券的最新 Tick 数据。")
        reporter.call(
            "get_full_tick",
            "获取实时行情快照",
            f"查询 {', '.join(stock_list)} 的最新 Tick 数据。",
            lambda: xtdata.get_full_tick(stock_list),
            example="xtdata.get_full_tick(stock_list)",
        )

        reporter.section(2, "K 线行情读取", "分别验证标准、扩展和本地三个历史行情读取入口。")
        reporter.call(
            "get_market_data",
            "读取标准 K 线数据",
            f"读取 {stock_code} 的 {config.period} 行情，字段为开高低收和成交量。",
            lambda: xtdata.get_market_data(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=config.period,
                start_time=config.start_time,
                end_time=config.end_time,
                count=config.count,
                dividend_type="none",
                fill_data=True,
            ),
            example="xtdata.get_market_data(field_list, [stock_code], period, start_time, end_time, count)",
        )
        reporter.call(
            "get_market_data_ex",
            "读取扩展 K 线数据",
            "使用扩展接口读取相同行情，以检查按证券组织的数据结构。",
            lambda: xtdata.get_market_data_ex(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=config.period,
                start_time=config.start_time,
                end_time=config.end_time,
                count=config.count,
                dividend_type="none",
                fill_data=True,
            ),
            example="xtdata.get_market_data_ex(field_list, [stock_code], period, start_time, end_time, count)",
        )
        reporter.call(
            "get_local_data",
            "读取本地 K 线数据",
            "只读取 QMT 本地已有行情，用于确认数据是否已正确落盘。",
            lambda: xtdata.get_local_data(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=config.period,
                start_time=config.start_time,
                end_time=config.end_time,
                count=config.count,
                dividend_type="none",
                fill_data=True,
            ),
            example="xtdata.get_local_data(field_list, [stock_code], period, start_time, end_time, count)",
        )

        reporter.section(3, "证券基础资料", "检查证券资料库、板块成分和交易日历等基础数据。")
        reporter.call(
            "get_instrument_detail",
            "查询证券合约详情",
            f"读取 {stock_code} 的名称、市场、上市日期等合约信息。",
            lambda: xtdata.get_instrument_detail(stock_code, False),
            example="xtdata.get_instrument_detail(stock_code, False)",
        )
        reporter.call(
            "get_stock_list_in_sector",
            "查询板块成分股",
            f"获取“{config.sector_name}”板块中的证券列表。",
            lambda: xtdata.get_stock_list_in_sector(config.sector_name),
            example="xtdata.get_stock_list_in_sector(sector_name)",
        )
        reporter.call(
            "get_trading_dates",
            "查询交易日历",
            f"获取 {stock_code} 对应市场最近的交易日期。",
            lambda: xtdata.get_trading_dates(
                stock_code,
                start_date=config.start_time,
                end_date=config.end_time,
                count=config.count,
                period=config.period,
            ),
            example="xtdata.get_trading_dates(stock_code, start_date, end_date, count, period)",
        )
        reporter.call(
            "is_stock",
            "判断是否为股票",
            f"判断 {stock_code} 是否属于股票品种。",
            lambda: xtdata.is_stock(stock_code),
            example="xtdata.is_stock(stock_code)",
        )
        reporter.call(
            "is_fund",
            "判断是否为基金",
            f"判断 {stock_code} 是否属于基金品种。",
            lambda: xtdata.is_fund(stock_code),
            example="xtdata.is_fund(stock_code)",
        )
        reporter.call(
            "is_future",
            "判断是否为期货",
            f"判断 {stock_code} 是否属于期货品种。",
            lambda: xtdata.is_future(stock_code),
            example="xtdata.is_future(stock_code)",
        )
        reporter.call(
            "get_stock_type",
            "查询证券类型",
            f"获取 {stock_code} 的证券类型标识。",
            lambda: xtdata.get_stock_type(stock_code),
            example="xtdata.get_stock_type(stock_code)",
        )
        reporter.call(
            "get_stock_name",
            "查询证券名称",
            f"获取 {stock_code} 对应的中文证券名称。",
            lambda: xtdata.get_stock_name(stock_code),
            example="xtdata.get_stock_name(stock_code)",
        )
        reporter.call(
            "get_open_date",
            "查询上市日期",
            f"获取 {stock_code} 的上市日期。",
            lambda: xtdata.get_open_date(stock_code),
            example="xtdata.get_open_date(stock_code)",
        )

        reporter.section(4, "衍生市场资料", "检查指数权重、换手率和 ETF 列表等扩展数据。")
        reporter.call(
            "get_weight_in_index",
            "查询指数成分权重",
            f"查询 {stock_code} 在指数 {config.index_code} 中的权重。",
            lambda: xtdata.get_weight_in_index(config.index_code, stock_code),
            example="xtdata.get_weight_in_index(index_code, stock_code)",
        )
        reporter.call(
            "get_turnover_rate",
            "查询换手率",
            f"查询 {stock_code} 在指定时间范围内的换手率。",
            lambda: xtdata.get_turnover_rate(stock_code, start_time=config.start_time, end_time=config.end_time),
            example="xtdata.get_turnover_rate(stock_code, start_time, end_time)",
        )
        reporter.call(
            "get_ETF_list",
            "查询 ETF 列表",
            f"获取 {config.etf_market} 市场的 ETF 证券列表。",
            lambda: xtdata.get_ETF_list(market=config.etf_market),
            example="xtdata.get_ETF_list(market=etf_market)",
        )

        reporter.section(5, "财务与因子数据", "检查 QMT 本地已下载的财务数据和因子数据。")
        if financial_fields:
            reporter.call(
                "get_financial_data",
                "读取财务数据",
                f"查询 {stock_code} 的财务字段：{', '.join(financial_fields)}。",
                lambda: xtdata.get_financial_data(
                    financial_fields,
                    [stock_code],
                    start_time=config.start_time,
                    end_time=config.end_time,
                    report_type=config.financial_report_type,
                ),
                example="xtdata.get_financial_data(financial_fields, [stock_code], start_time, end_time)",
            )
        else:
            reporter.skip("get_financial_data", "读取财务数据", "FINANCIAL_FIELDS 为空，无法确定要查询的财务字段。")
        if factor_fields:
            reporter.call(
                "get_factor_data",
                "读取因子数据",
                f"查询 {stock_code} 的因子字段：{', '.join(factor_fields)}。",
                lambda: xtdata.get_factor_data(
                    factor_fields,
                    [stock_code],
                    start_date=config.start_time,
                    end_date=config.end_time,
                ),
                example="xtdata.get_factor_data(factor_fields, [stock_code], start_date, end_date)",
            )
        else:
            reporter.skip("get_factor_data", "读取因子数据", "FACTOR_FIELDS 为空，无法确定要查询的因子字段。")

        reporter.section(6, "期权数据", "使用现场有效的期权合约检查期权详情、标的和合约列表。")
        if option_code:
            reporter.call(
                "get_option_detail_data",
                "查询期权合约详情",
                f"读取期权合约 {option_code} 的详细资料。",
                lambda: xtdata.get_option_detail_data(option_code),
                example="xtdata.get_option_detail_data(option_code)",
            )
            reporter.call(
                "get_option_undl",
                "查询期权对应标的",
                f"查询期权合约 {option_code} 对应的标的证券。",
                lambda: xtdata.get_option_undl(option_code),
                example="xtdata.get_option_undl(option_code)",
            )
        else:
            reporter.skip("get_option_detail_data", "查询期权合约详情", "OPTION_CODE 为空，无法确定期权合约。")
            reporter.skip("get_option_undl", "查询期权对应标的", "OPTION_CODE 为空，无法确定期权合约。")
        if option_date:
            reporter.call(
                "get_option_list",
                "查询期权合约列表",
                f"查询标的 {config.option_underlying} 在 {option_date} 到期的期权合约。",
                lambda: xtdata.get_option_list(config.option_underlying, option_date),
                example="xtdata.get_option_list(option_underlying, option_date)",
            )
            reporter.call(
                "get_option_undl_data",
                "查询期权标的资料",
                f"读取期权标的 {config.option_underlying} 的相关资料。",
                lambda: xtdata.get_option_undl_data(config.option_underlying),
                example="xtdata.get_option_undl_data(option_underlying)",
            )
        else:
            reporter.skip("get_option_list", "查询期权合约列表", "OPTION_DATE 为空，无法确定期权到期月份。")
            reporter.skip("get_option_undl_data", "查询期权标的资料", "OPTION_DATE 为空，本组期权列表示例不执行。")
    finally:
        close_default_client()
    reporter.finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
