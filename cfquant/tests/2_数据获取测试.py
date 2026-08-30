# -*- coding: utf-8 -*-
import argparse

from _helpers import (
    add_runtime_args,
    close_default_client,
    configure_cfquant,
    configure_stdout,
    emit_call,
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
    parser.add_argument("--sector-name", default="沪深A股", help="板块名称，默认 沪深A股。")
    args = parser.parse_args()
    configure_cfquant(args)

    stock_list = parse_csv(args.stock_list, default=["000001.SZ", "600000.SH"], upper=True)
    stock_code = str(args.stock_code or stock_list[0]).strip().upper()

    print_json({
        "type": "start",
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "stock_list": stock_list,
        "stock_code": stock_code,
    })
    try:
        emit_call("get_full_tick", lambda: xtdata.get_full_tick(stock_list))
        emit_call(
            "get_market_data",
            lambda: xtdata.get_market_data(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=args.period,
                count=args.count,
                dividend_type="none",
                fill_data=True,
            ),
        )
        emit_call(
            "get_market_data_ex",
            lambda: xtdata.get_market_data_ex(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code],
                period=args.period,
                count=args.count,
                dividend_type="none",
                fill_data=True,
            ),
        )
        emit_call("get_instrument_detail", lambda: xtdata.get_instrument_detail(stock_code, False))
        emit_call("get_stock_list_in_sector", lambda: xtdata.get_stock_list_in_sector(args.sector_name))
    finally:
        close_default_client()
    print_json({"type": "summary", "ok": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

