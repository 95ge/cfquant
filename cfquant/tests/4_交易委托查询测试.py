# -*- coding: utf-8 -*-
from types import SimpleNamespace

from _helpers import (
    configure_cfquant,
    configure_stdout,
    default_account_id,
    emit_call,
    emit_skip,
    print_json,
    summarize,
)

from cfquant.xttrader import XtQuantTrader, close_trade_client
from cfquant.xtconstant import FIX_PRICE, STOCK_BUY, STOCK_SELL
from cfquant.xttype import StockAccount


# ======================== 用户配置区 ========================
# 直接修改下面的配置，然后运行本文件；不读取命令行参数。
TRANSPORT = "auto"       # auto 自动发现；也可填写 ctypes、web_lttx 或 lttx
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0    # 请求超时，单位秒
ACCOUNT_ID = ""           # 留空读取 CFQUANT_ACCOUNT_ID 或 Web 默认账号
ACCOUNT_TYPE = "STOCK"    # STOCK 或 CREDIT
CANCELABLE_ONLY = False
STOCK_CODE = ""           # 留空从当前持仓取一个证券
ORDER_ID = ""             # 留空从当前委托取一个编号
INCLUDE_CREDIT = False
INCLUDE_ASYNC = False
# 默认只读；提交委托须同时开启 SUBMIT_ORDER 并填写匹配的确认文本。
SUBMIT_ORDER = False
ORDER_CONFIRM_TEXT = ""   # 必须等于输出中的 required_confirm_text
ORDER_ACCOUNT_ID = ""     # 留空使用 ACCOUNT_ID
ORDER_ACCOUNT_TYPE = ""   # 留空使用 ACCOUNT_TYPE
ORDER_SIDE = "buy"        # buy=买入，sell=卖出
ORDER_STOCK_CODE = ""
ORDER_VOLUME = 0
ORDER_PRICE = 0.0
ORDER_PRICE_TYPE = FIX_PRICE
STRATEGY_NAME = "cfquant_test_4"
ORDER_REMARK = ""         # 留空使用 STRATEGY_NAME
# ===========================================================


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


def build_order_confirmation(side, stock_code, volume, price):
    return "ORDER %s %s %s @ %.3f" % (str(side or "").upper(), stock_code, volume, price)


def order_id_from_result(result):
    if result not in (None, "", -1, "-1") and not isinstance(result, dict):
        return str(result)
    if isinstance(result, dict):
        for key in ("order_id", "m_strOrderSysID", "m_strOrderID", "m_nOrderID"):
            value = result.get(key)
            if value not in (None, "", -1, "-1"):
                return str(value)
        nested = result.get("result") or result.get("request_result")
        if nested is not result:
            return order_id_from_result(nested)
    return ""


def main():
    configure_stdout()
    config = SimpleNamespace(
        transport=TRANSPORT,
        bridge_id=BRIDGE_ID,
        timeout=REQUEST_TIMEOUT,
        account_id=ACCOUNT_ID,
        account_type=ACCOUNT_TYPE,
        cancelable_only=CANCELABLE_ONLY,
        stock_code=STOCK_CODE,
        order_id=ORDER_ID,
        include_credit=INCLUDE_CREDIT,
        include_async=INCLUDE_ASYNC,
        submit_order=SUBMIT_ORDER,
        order_confirm_text=ORDER_CONFIRM_TEXT,
        order_account_id=ORDER_ACCOUNT_ID,
        order_account_type=ORDER_ACCOUNT_TYPE,
        order_side=ORDER_SIDE,
        order_stock_code=ORDER_STOCK_CODE,
        order_volume=ORDER_VOLUME,
        order_price=ORDER_PRICE,
        order_price_type=ORDER_PRICE_TYPE,
        strategy_name=STRATEGY_NAME,
        order_remark=ORDER_REMARK,
    )
    config.account_id = str(config.account_id or "").strip() or default_account_id()
    configure_cfquant(config)

    account_id = str(config.account_id or "").strip()
    if not account_id:
        print_json({
            "type": "error",
            "message": "缺少资金账号。请在顶部用户配置区填写 ACCOUNT_ID。",
        })
        return 2

    account_type = str(config.account_type or "STOCK").strip().upper()
    account = StockAccount(account_id, account_type, config.bridge_id)
    order_account_id = str(config.order_account_id or account_id).strip()
    order_account_type = str(config.order_account_type or account_type).strip().upper()
    order_account = StockAccount(order_account_id, order_account_type, config.bridge_id)
    order_stock_code = str(config.order_stock_code or "").strip().upper()
    order_side = str(config.order_side or "buy").strip().lower()
    if order_side not in ("buy", "sell"):
        print_json({"case": "validate", "ok": False, "error": "ORDER_SIDE must be buy or sell"})
        return 2
    order_volume = int(config.order_volume or 0)
    order_price = float(config.order_price or 0)
    order_strategy_name = str(config.strategy_name or "").strip() or "cfquant_test_4"
    order_remark = str(config.order_remark or "").strip()
    order_required_confirm = (
        build_order_confirmation(order_side, order_stock_code, order_volume, order_price)
        if order_stock_code and order_volume > 0 and order_price > 0
        else ""
    )
    trader = XtQuantTrader(account=account)

    print_json({
        "type": "start",
        "transport": config.transport,
        "bridge_id": config.bridge_id,
        "account_id": account_id,
        "account_type": account_type,
        "stock_code": config.stock_code,
        "order_id": config.order_id,
        "order_config": {
            "submit_order": bool(config.submit_order),
            "account_id": order_account_id,
            "account_type": order_account_type,
            "side": order_side,
            "stock_code": order_stock_code,
            "volume": order_volume,
            "price": order_price,
            "price_type": config.order_price_type,
            "strategy_name": order_strategy_name,
            "order_remark": order_remark or order_strategy_name,
            "required_confirm_text": order_required_confirm,
        },
        "safe_mode": "默认只查询资金、持仓、委托、成交；只有 SUBMIT_ORDER = True 且 ORDER_CONFIRM_TEXT 匹配时才会提交真实委托，不会自动撤单。",
    })
    try:
        # connect 会注册交易回调并向桥接端 ping 一次，返回 0 表示链路可用。
        connect_result = trader.connect()
        print_json({"case": "connect", "ok": connect_result == 0, "result": connect_result})
        if connect_result != 0:
            return 1

        # 1. 最常用的股票账户查询，返回值会尽量映射成 xtquant 风格对象。
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
        submitted_order_id = ""
        order_preview = {
            "account_id": order_account_id,
            "account_type": order_account_type,
            "side": order_side,
            "stock_code": order_stock_code,
            "volume": order_volume,
            "price_type": config.order_price_type,
            "price": order_price,
            "strategy_name": order_strategy_name,
            "order_remark": order_remark or order_strategy_name,
            "required_confirm_text": order_required_confirm,
        }
        print_json({
            "case": "order_stock_preview",
            "ok": bool(order_required_confirm),
            "skipped": not bool(config.submit_order),
            "summary": order_preview,
            "example": "trader.order_stock(order_account, order_stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark)",
        })
        if config.submit_order:
            if not order_account_id:
                print_json({"case": "order_stock", "ok": False, "error": "order account_id is required"})
                return 2
            if not order_required_confirm:
                print_json({"case": "order_stock", "ok": False, "error": "order stock_code, volume and price are required"})
                return 2
            if str(config.order_confirm_text or "").strip() != order_required_confirm:
                print_json({
                    "case": "order_stock",
                    "ok": False,
                    "error": "confirmation mismatch",
                    "required_confirm_text": order_required_confirm,
                })
                return 2
            order_type = STOCK_BUY if order_side == "buy" else STOCK_SELL
            order_result = emit_call(
                "order_stock",
                lambda: trader.order_stock(
                    order_account,
                    order_stock_code,
                    order_type,
                    order_volume,
                    config.order_price_type,
                    order_price,
                    order_strategy_name,
                    order_remark or order_strategy_name,
                ),
                example="trader.order_stock(order_account, order_stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark)",
            )
            submitted_order_id = order_id_from_result(order_result)
        orders = emit_call(
            "query_stock_orders",
            lambda: trader.query_stock_orders(order_account if config.submit_order else account, cancelable_only=config.cancelable_only),
            example="trader.query_stock_orders(account, cancelable_only=False)",
        )
        emit_call(
            "query_stock_trades",
            lambda: trader.query_stock_trades(order_account if config.submit_order else account),
            example="trader.query_stock_trades(account)",
        )

        # 2. 单笔查询示例：没有手工传入时，自动从本次列表结果里取第一条样例。
        position_code = str(config.stock_code or "").strip().upper() or first_attr(positions, "stock_code")
        if position_code:
            emit_call(
                "query_stock_position",
                lambda: trader.query_stock_position(account, position_code),
                example="trader.query_stock_position(account, stock_code)",
            )
        else:
            emit_skip("query_stock_position", "STOCK_CODE 为空且当前持仓列表为空，无法构造单持仓查询示例。")

        order_id = str(config.order_id or "").strip() or submitted_order_id or first_attr(orders, "order_id", "order_sysid", "m_strOrderSysID")
        if order_id:
            emit_call(
                "query_stock_order",
                lambda: trader.query_stock_order(order_account if config.submit_order else account, order_id),
                example="trader.query_stock_order(account, order_id)",
            )
        else:
            emit_skip("query_stock_order", "ORDER_ID 为空且当前委托列表为空，无法构造单委托查询示例。")

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

        # 4. 信用账户专项只读查询。普通账号默认跳过，需要时设置 INCLUDE_CREDIT = True。
        if account_type == "CREDIT" or config.include_credit:
            emit_call("query_credit_detail", lambda: trader.query_credit_detail(account), example="trader.query_credit_detail(account)")
            emit_call("query_credit_subjects", lambda: trader.query_credit_subjects(account), example="trader.query_credit_subjects(account)")
            emit_call("query_credit_slo_code", lambda: trader.query_credit_slo_code(account), example="trader.query_credit_slo_code(account)")
            emit_call("query_credit_assure", lambda: trader.query_credit_assure(account), example="trader.query_credit_assure(account)")
            emit_call("query_stk_compacts", lambda: trader.query_stk_compacts(account), example="trader.query_stk_compacts(account)")
        else:
            emit_skip("credit_query_examples", "当前不是 CREDIT 账号，信用专项查询已跳过；可设置 INCLUDE_CREDIT = True 强制验证。")

        # 5. async 查询示例只在需要时开启，callback 会立即打印 async_callback JSON。
        if config.include_async:
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
                    cancelable_only=config.cancelable_only,
                ),
                example="trader.query_stock_orders_async(account, callback, cancelable_only=False)",
            )
            emit_call(
                "query_stock_trades_async",
                lambda: trader.query_stock_trades_async(account, make_async_printer("query_stock_trades_async")),
                example="trader.query_stock_trades_async(account, callback)",
            )
        else:
            emit_skip("async_query_examples", "INCLUDE_ASYNC = False，默认只运行同步查询示例。")
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
