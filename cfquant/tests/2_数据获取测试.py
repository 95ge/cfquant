# -*- coding: utf-8 -*-
import argparse

from _helpers import (
    add_runtime_args,
    close_default_client,
    configure_cfquant,
    configure_stdout,
    emit_call,
    emit_skip,
    parse_csv,
    print_json,
)

from cfquant import xtdata


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="cfquant 行情和基础数据获取测试。")
    add_runtime_args(parser)
    parser.add_argument("--stock-list", default="000001.SZ,600000.SH", help="证券列表，逗号分隔。")
    parser.add_argument("--stock-code", default="000001.SZ", help="用于合约详情和日线查询的单个证券。")
    parser.add_argument("--period", default="1d", help="周期，默认 1d。")
    parser.add_argument("--count", type=int, default=5, help="返回条数，默认 5。")
    parser.add_argument("--start-time", default="", help="开始时间，例如 20260101；留空表示由 QMT 使用默认范围。")
    parser.add_argument("--end-time", default="", help="结束时间，例如 20260821；留空表示由 QMT 使用默认范围。")
    parser.add_argument("--sector-name", default="沪深A股", help="板块名称，默认 沪深A股。")
    parser.add_argument("--index-code", default="000300.SH", help="指数权重示例使用的指数代码，默认 000300.SH。")
    parser.add_argument("--etf-market", default="SH", help="ETF 列表示例使用的市场，默认 SH。")
    parser.add_argument("--financial-fields", default="ASHAREBALANCESHEET.fix_assets", help="财务查询字段，逗号分隔；留空则跳过财务示例。")
    parser.add_argument("--financial-report-type", default="announce_time", help="财务查询报告口径，默认 announce_time。")
    parser.add_argument("--factor-fields", default="", help="因子字段，逗号分隔；留空则跳过因子示例。")
    parser.add_argument("--option-code", default="", help="期权详情示例使用的期权代码；留空则跳过期权详情。")
    parser.add_argument("--option-underlying", default="510050.SH", help="期权列表示例使用的标的代码，默认 510050.SH。")
    parser.add_argument("--option-date", default="", help="期权列表到期月份，例如 202609；留空则跳过期权列表示例。")
    args = parser.parse_args()
    configure_cfquant(args)

    stock_list = parse_csv(args.stock_list, default=["000001.SZ", "600000.SH"], upper=True)
    stock_code = str(args.stock_code or stock_list[0]).strip().upper()
    financial_fields = parse_csv(args.financial_fields, default=[])
    factor_fields = parse_csv(args.factor_fields, default=[])
    option_code = str(args.option_code or "").strip().upper()
    option_date = str(args.option_date or "").strip()

    print_json({
        "type": "start",
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "stock_list": stock_list,
        "stock_code": stock_code,
        "period": args.period,
        "count": args.count,
        "start_time": args.start_time,
        "end_time": args.end_time,
    })
    try:
        # 1. 实时快照：常用于盘中快速取一批证券的最新 tick。
        emit_call(
            "get_full_tick",
            lambda: xtdata.get_full_tick(stock_list),
            example="xtdata.get_full_tick(stock_list)",
        )

        # 2. K 线读取：get_market_data 与 get_market_data_ex 是最常用的历史/本地行情入口。
        emit_call(
            "get_market_data",
            lambda: xtdata.get_market_data(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=args.period,
                start_time=args.start_time,
                end_time=args.end_time,
                count=args.count,
                dividend_type="none",
                fill_data=True,
            ),
            example="xtdata.get_market_data(field_list, [stock_code], period, start_time, end_time, count)",
        )
        emit_call(
            "get_market_data_ex",
            lambda: xtdata.get_market_data_ex(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=args.period,
                start_time=args.start_time,
                end_time=args.end_time,
                count=args.count,
                dividend_type="none",
                fill_data=True,
            ),
            example="xtdata.get_market_data_ex(field_list, [stock_code], period, start_time, end_time, count)",
        )
        emit_call(
            "get_local_data",
            lambda: xtdata.get_local_data(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=args.period,
                start_time=args.start_time,
                end_time=args.end_time,
                count=args.count,
                dividend_type="none",
                fill_data=True,
            ),
            example="xtdata.get_local_data(field_list, [stock_code], period, start_time, end_time, count)",
        )

        # 3. 基础资料：适合检查 QMT 侧证券基础库、交易日历和板块数据是否可用。
        emit_call(
            "get_instrument_detail",
            lambda: xtdata.get_instrument_detail(stock_code, False),
            example="xtdata.get_instrument_detail(stock_code, False)",
        )
        emit_call(
            "get_stock_list_in_sector",
            lambda: xtdata.get_stock_list_in_sector(args.sector_name),
            example="xtdata.get_stock_list_in_sector(sector_name)",
        )
        emit_call(
            "get_trading_dates",
            lambda: xtdata.get_trading_dates(
                stock_code,
                start_date=args.start_time,
                end_date=args.end_time,
                count=args.count,
                period=args.period,
            ),
            example="xtdata.get_trading_dates(stock_code, start_date, end_date, count, period)",
        )
        emit_call("is_stock", lambda: xtdata.is_stock(stock_code), example="xtdata.is_stock(stock_code)")
        emit_call("is_fund", lambda: xtdata.is_fund(stock_code), example="xtdata.is_fund(stock_code)")
        emit_call("is_future", lambda: xtdata.is_future(stock_code), example="xtdata.is_future(stock_code)")
        emit_call("get_stock_type", lambda: xtdata.get_stock_type(stock_code), example="xtdata.get_stock_type(stock_code)")
        emit_call("get_stock_name", lambda: xtdata.get_stock_name(stock_code), example="xtdata.get_stock_name(stock_code)")
        emit_call("get_open_date", lambda: xtdata.get_open_date(stock_code), example="xtdata.get_open_date(stock_code)")

        # 4. 衍生的市场资料：部分券商 QMT 版本可能没有暴露对应 callable，失败时会打印错误但不中断。
        emit_call(
            "get_weight_in_index",
            lambda: xtdata.get_weight_in_index(args.index_code, stock_code),
            example="xtdata.get_weight_in_index(index_code, stock_code)",
        )
        emit_call(
            "get_turnover_rate",
            lambda: xtdata.get_turnover_rate(stock_code, start_time=args.start_time, end_time=args.end_time),
            example="xtdata.get_turnover_rate(stock_code, start_time, end_time)",
        )
        emit_call(
            "get_ETF_list",
            lambda: xtdata.get_ETF_list(market=args.etf_market),
            example="xtdata.get_ETF_list(market='SH')",
        )

        # 5. 财务和因子数据：需要 QMT 本地已经下载好相应数据。
        if financial_fields:
            emit_call(
                "get_financial_data",
                lambda: xtdata.get_financial_data(
                    financial_fields,
                    [stock_code],
                    start_time=args.start_time,
                    end_time=args.end_time,
                    report_type=args.financial_report_type,
                ),
                example="xtdata.get_financial_data(financial_fields, [stock_code], start_time, end_time)",
            )
        else:
            emit_skip("get_financial_data", "未传 --financial-fields，跳过财务查询示例。")
        if factor_fields:
            emit_call(
                "get_factor_data",
                lambda: xtdata.get_factor_data(
                    factor_fields,
                    [stock_code],
                    start_date=args.start_time,
                    end_date=args.end_time,
                ),
                example="xtdata.get_factor_data(factor_fields, [stock_code], start_date, end_date)",
            )
        else:
            emit_skip("get_factor_data", "未传 --factor-fields，跳过因子查询示例。")

        # 6. 期权示例默认关闭，因为需要传入现场有效的期权合约和到期月份。
        if option_code:
            emit_call(
                "get_option_detail_data",
                lambda: xtdata.get_option_detail_data(option_code),
                example="xtdata.get_option_detail_data(option_code)",
            )
            emit_call(
                "get_option_undl",
                lambda: xtdata.get_option_undl(option_code),
                example="xtdata.get_option_undl(option_code)",
            )
        else:
            emit_skip("get_option_detail_data", "未传 --option-code，跳过期权详情示例。")
            emit_skip("get_option_undl", "未传 --option-code，跳过期权标的示例。")
        if option_date:
            emit_call(
                "get_option_list",
                lambda: xtdata.get_option_list(args.option_underlying, option_date),
                example="xtdata.get_option_list(option_underlying, option_date)",
            )
            emit_call(
                "get_option_undl_data",
                lambda: xtdata.get_option_undl_data(args.option_underlying),
                example="xtdata.get_option_undl_data(option_underlying)",
            )
        else:
            emit_skip("get_option_list", "未传 --option-date，跳过期权列表示例。")
            emit_skip("get_option_undl_data", "未传 --option-date，跳过期权标的数据示例。")
    finally:
        close_default_client()
    print_json({"type": "summary", "ok": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
