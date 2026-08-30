# -*- coding: utf-8 -*-
import argparse

from _helpers import (
    add_runtime_args,
    configure_cfquant,
    configure_stdout,
    default_account_id,
    emit_call,
    print_json,
)

from cfquant.xttrader import XtQuantTrader, close_trade_client
from cfquant.xttype import StockAccount


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="cfquant 交易和委托只读查询测试，不会下单。")
    add_runtime_args(parser)
    parser.add_argument("--account-id", default=default_account_id(), help="资金账号。默认读取 CFQUANT_ACCOUNT_ID 或 runtime/config/cfquant_web_config.json。")
    parser.add_argument("--account-type", default="STOCK", help="账号类型，默认 STOCK，可填 CREDIT。")
    parser.add_argument("--cancelable-only", action="store_true", help="委托查询只返回可撤单委托。")
    args = parser.parse_args()
    configure_cfquant(args)

    account_id = str(args.account_id or "").strip()
    if not account_id:
        print_json({
            "type": "error",
            "message": "缺少资金账号。请传 --account-id 你的资金账号，或设置环境变量 CFQUANT_ACCOUNT_ID。",
        })
        return 2

    account_type = str(args.account_type or "STOCK").strip().upper()
    account = StockAccount(account_id, account_type, args.bridge_id)
    trader = XtQuantTrader(account=account)

    print_json({
        "type": "start",
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "account_id": account_id,
        "account_type": account_type,
        "safe_mode": "只查询资金、持仓、委托、成交，不会提交委托或撤单。",
    })
    try:
        connect_result = trader.connect()
        print_json({"case": "connect", "ok": connect_result == 0, "result": connect_result})
        if connect_result != 0:
            return 1
        emit_call("query_stock_asset", lambda: trader.query_stock_asset(account))
        emit_call("query_stock_positions", lambda: trader.query_stock_positions(account))
        emit_call("query_stock_orders", lambda: trader.query_stock_orders(account, cancelable_only=args.cancelable_only))
        emit_call("query_stock_trades", lambda: trader.query_stock_trades(account))
    finally:
        try:
            trader.disconnect()
        except Exception:
            pass
        close_trade_client()
    print_json({"type": "summary", "ok": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
