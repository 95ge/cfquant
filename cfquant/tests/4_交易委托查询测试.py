# -*- coding: utf-8 -*-
import argparse

from _helpers import (
    add_runtime_args,
    configure_cfquant,
    configure_stdout,
    default_account_id,
    emit_call,
    emit_skip,
    print_json,
    summarize,
)

from cfquant.xttrader import XtQuantTrader, close_trade_client
from cfquant.xttype import StockAccount


def first_attr(items, *names):
    # 从查询结果对象里取第一条可用字段，用于构造单笔持仓/委托查询示例。
    for item in items or []:
        for name in names:
            value = getattr(item, name, None)
            if value not in (None, ""):
                return str(value)
    return ""


def make_async_printer(case):
    # async 查询会把结果传给 callback，这里统一打印成 JSON，便于和同步查询结果对照。
    def callback(result):
        print_json({
            "type": "async_callback",
            "case": case,
            "summary": summarize(result),
        })

    return callback


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="cfquant 交易和委托只读查询测试，不会下单。")
    add_runtime_args(parser)
    parser.add_argument("--account-id", default=default_account_id(), help="资金账号。默认读取 CFQUANT_ACCOUNT_ID 或 runtime/config/cfquant_web_config.json。")
    parser.add_argument("--account-type", default="STOCK", help="账号类型，默认 STOCK，可填 CREDIT。")
    parser.add_argument("--cancelable-only", action="store_true", help="委托查询只返回可撤单委托。")
    parser.add_argument("--stock-code", default="", help="单笔持仓查询使用的证券代码；留空则从持仓列表取第一条。")
    parser.add_argument("--order-id", default="", help="单笔委托查询使用的委托编号或系统编号；留空则从委托列表取第一条。")
    parser.add_argument("--include-credit", action="store_true", help="即使 account-type 不是 CREDIT，也尝试信用专项只读查询。")
    parser.add_argument("--include-async", action="store_true", help="同时演示资产、持仓、委托、成交的 async 查询写法。")
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
        "stock_code": args.stock_code,
        "order_id": args.order_id,
        "safe_mode": "只查询资金、持仓、委托、成交，不会提交委托或撤单。",
    })
    try:
        # connect 会注册交易回调并向桥接端 ping 一次，返回 0 表示链路可用。
        connect_result = trader.connect()
        print_json({"case": "connect", "ok": connect_result == 0, "result": connect_result})
        if connect_result != 0:
            return 1

        # 1. 最常用的股票账户只读查询，返回值会尽量映射成 xtquant 风格对象。
        emit_call(
            "query_stock_asset",
            lambda: trader.query_stock_asset(account),
            example="trader.query_stock_asset(account)",
        )
        positions = emit_call(
            "query_stock_positions",
            lambda: trader.query_stock_positions(account),
            example="trader.query_stock_positions(account)",
        )
        orders = emit_call(
            "query_stock_orders",
            lambda: trader.query_stock_orders(account, cancelable_only=args.cancelable_only),
            example="trader.query_stock_orders(account, cancelable_only=False)",
        )
        emit_call(
            "query_stock_trades",
            lambda: trader.query_stock_trades(account),
            example="trader.query_stock_trades(account)",
        )

        # 2. 单笔查询示例：没有手工传入时，自动从本次列表结果里取第一条样例。
        position_code = str(args.stock_code or "").strip().upper() or first_attr(positions, "stock_code")
        if position_code:
            emit_call(
                "query_stock_position",
                lambda: trader.query_stock_position(account, position_code),
                example="trader.query_stock_position(account, stock_code)",
            )
        else:
            emit_skip("query_stock_position", "未传 --stock-code 且当前持仓列表为空，无法构造单持仓查询示例。")

        order_id = str(args.order_id or "").strip() or first_attr(orders, "order_id", "order_sysid", "m_strOrderSysID")
        if order_id:
            emit_call(
                "query_stock_order",
                lambda: trader.query_stock_order(account, order_id),
                example="trader.query_stock_order(account, order_id)",
            )
        else:
            emit_skip("query_stock_order", "未传 --order-id 且当前委托列表为空，无法构造单委托查询示例。")

        # 3. 账号状态、新股申购、综合资金/持仓等兼容入口，是否可用取决于券商 QMT 环境。
        emit_call("query_account_info", lambda: trader.query_account_info(), example="trader.query_account_info()")
        emit_call("query_account_infos", lambda: trader.query_account_infos(), example="trader.query_account_infos()")
        emit_call("query_account_status", lambda: trader.query_account_status(), example="trader.query_account_status()")
        emit_call("query_com_fund", lambda: trader.query_com_fund(account), example="trader.query_com_fund(account)")
        emit_call("query_com_position", lambda: trader.query_com_position(account), example="trader.query_com_position(account)")
        emit_call(
            "query_position_statistics",
            lambda: trader.query_position_statistics(account),
            example="trader.query_position_statistics(account)",
        )
        emit_call("query_secu_account", lambda: trader.query_secu_account(account), example="trader.query_secu_account(account)")
        emit_call("query_ipo_data", lambda: trader.query_ipo_data(), example="trader.query_ipo_data()")
        emit_call(
            "query_new_purchase_limit",
            lambda: trader.query_new_purchase_limit(account),
            example="trader.query_new_purchase_limit(account)",
        )

        # 4. 信用账户专项只读查询。普通账号默认跳过，需要强制验证时加 --include-credit。
        if account_type == "CREDIT" or args.include_credit:
            emit_call("query_credit_detail", lambda: trader.query_credit_detail(account), example="trader.query_credit_detail(account)")
            emit_call("query_credit_subjects", lambda: trader.query_credit_subjects(account), example="trader.query_credit_subjects(account)")
            emit_call("query_credit_slo_code", lambda: trader.query_credit_slo_code(account), example="trader.query_credit_slo_code(account)")
            emit_call("query_credit_assure", lambda: trader.query_credit_assure(account), example="trader.query_credit_assure(account)")
            emit_call("query_stk_compacts", lambda: trader.query_stk_compacts(account), example="trader.query_stk_compacts(account)")
        else:
            emit_skip("credit_query_examples", "当前不是 CREDIT 账号，信用专项查询已跳过；可加 --include-credit 强制验证。")

        # 5. async 查询示例只在需要时开启，callback 会立即打印 async_callback JSON。
        if args.include_async:
            emit_call(
                "query_stock_asset_async",
                lambda: trader.query_stock_asset_async(account, make_async_printer("query_stock_asset_async")),
                example="trader.query_stock_asset_async(account, callback)",
            )
            emit_call(
                "query_stock_positions_async",
                lambda: trader.query_stock_positions_async(account, make_async_printer("query_stock_positions_async")),
                example="trader.query_stock_positions_async(account, callback)",
            )
            emit_call(
                "query_stock_orders_async",
                lambda: trader.query_stock_orders_async(
                    account,
                    make_async_printer("query_stock_orders_async"),
                    cancelable_only=args.cancelable_only,
                ),
                example="trader.query_stock_orders_async(account, callback, cancelable_only=False)",
            )
            emit_call(
                "query_stock_trades_async",
                lambda: trader.query_stock_trades_async(account, make_async_printer("query_stock_trades_async")),
                example="trader.query_stock_trades_async(account, callback)",
            )
        else:
            emit_skip("async_query_examples", "未传 --include-async，默认只运行同步查询示例。")
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
