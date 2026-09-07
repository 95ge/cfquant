# -*- coding: utf-8 -*-
"""查询成交和委托记录，并检查每条记录是否能正常返回 order_id。"""

import argparse

from _helpers import (
    add_runtime_args,
    configure_cfquant,
    configure_stdout,
    default_account_id,
    print_json,
)

from cfquant.xttrader import XtQuantTrader, close_trade_client
from cfquant.xttype import StockAccount


ORDER_ID_FIELDS = (
    "order_id",
    "m_nRef",
    "m_nOrderID",
    "m_strOrderRef",
    "m_strOrderID",
)
ORDER_SYSID_FIELDS = ("order_sysid", "m_strOrderSysID", "sysid")


def value_of(item, *names):
    """兼容标准化对象、原始对象和字典三种返回形式。"""
    for name in names:
        try:
            value = item.get(name) if isinstance(item, dict) else getattr(item, name)
        except (AttributeError, KeyError, TypeError):
            continue
        if value not in (None, ""):
            return value
    return None


def usable_order_id(value):
    """过滤 QMT 常见的无效订单号占位值。"""
    return value not in (None, "", -1, "-1", 0, "0")


def order_id_of(item):
    for field in ORDER_ID_FIELDS:
        value = value_of(item, field)
        if usable_order_id(value):
            return str(value)
    return ""


def order_id_matches(item, target):
    target = str(target or "").strip()
    if not target:
        return True
    values = [value_of(item, field) for field in ORDER_ID_FIELDS + ORDER_SYSID_FIELDS]
    return any(usable_order_id(value) and str(value) == target for value in values)


def as_records(result):
    """查询接口正常返回列表；兼容单对象返回，便于定位桥接端问题。"""
    if result is None:
        return None
    if isinstance(result, list):
        return result
    if isinstance(result, tuple):
        return list(result)
    return [result]


def record_summary(kind, index, item):
    summary = {
        "type": kind,
        "index": index,
        "order_id": order_id_of(item),
        "order_sysid": value_of(item, *ORDER_SYSID_FIELDS),
        "account_id": value_of(item, "account_id", "m_strAccountID"),
        "stock_code": value_of(item, "stock_code", "m_strInstrumentID", "m_strStockCode"),
    }
    if kind == "委托":
        summary.update({
            "order_status": value_of(item, "order_status", "m_nOrderStatus", "m_nOrderState"),
            "order_volume": value_of(item, "order_volume", "m_nVolumeTotalOriginal", "m_nOrderVolume"),
            "traded_volume": value_of(item, "traded_volume", "m_nVolumeTraded"),
            "price": value_of(item, "price", "m_dLimitPrice", "m_dOrderPrice"),
        })
    else:
        summary.update({
            "traded_id": value_of(item, "traded_id", "trade_id", "m_strTradeID", "m_strDealID"),
            "traded_volume": value_of(item, "traded_volume", "volume", "m_nVolume"),
            "traded_price": value_of(item, "traded_price", "price", "m_dPrice", "m_dTradedPrice"),
            "traded_time": value_of(item, "traded_time", "trade_time", "m_strTradeTime", "m_strDealTime"),
        })
    return summary


def query_and_print(name, query, order_id_filter="", max_rows=100):
    """执行一个只读查询，打印数量、order_id 和关键字段。"""
    try:
        raw_result = query()
        records = as_records(raw_result)
        if records is None:
            print_json({
                "case": name,
                "ok": False,
                "returned": False,
                "error": "查询接口返回 None",
            })
            return {"ok": False, "records": []}

        target = str(order_id_filter or "").strip()
        if target:
            records = [item for item in records if order_id_matches(item, target)]

        rows = [record_summary(name, index, item) for index, item in enumerate(records[:max_rows], 1)]
        missing_order_ids = sum(1 for item in records if not order_id_of(item))
        print_json({
            "case": name,
            "ok": True,
            "returned": True,
            "result_type": type(raw_result).__name__,
            "count": len(records),
            "displayed": len(rows),
            "order_id_filter": target,
            "missing_order_id_count": missing_order_ids,
            "records": rows,
            "message": "查询成功，但当前没有记录" if not records else "查询成功",
        })
        return {"ok": True, "records": records, "missing_order_ids": missing_order_ids}
    except Exception as error:
        print_json({
            "case": name,
            "ok": False,
            "returned": False,
            "error_type": type(error).__name__,
            "error": str(error),
        })
        return {"ok": False, "records": []}


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(
        description="只读查询指定账号的成交和委托记录，显示每条记录的 order_id。"
    )
    add_runtime_args(parser)
    parser.add_argument(
        "--account-id",
        default=default_account_id(),
        help="资金账号；默认读取 CFQUANT_ACCOUNT_ID 或 Web 配置。",
    )
    parser.add_argument(
        "--account-type",
        default="STOCK",
        help="账号类型，默认 STOCK，也可填写 CREDIT。",
    )
    parser.add_argument(
        "--order-id",
        default="",
        help="可选，只显示该 order_id 对应的委托和成交记录。",
    )
    parser.add_argument(
        "--cancelable-only",
        action="store_true",
        help="委托查询只返回当前可撤单的委托。",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=100,
        help="每类最多显示多少条记录，默认 100；0 表示不显示明细。",
    )
    args = parser.parse_args()
    if args.max_rows < 0:
        parser.error("--max-rows 不能小于 0")

    account_id = str(args.account_id or "").strip()
    if not account_id:
        print_json({
            "case": "参数检查",
            "ok": False,
            "error": "缺少 account_id，请传 --account-id 或设置 CFQUANT_ACCOUNT_ID。",
        })
        return 2

    configure_cfquant(args)
    account_type = str(args.account_type or "STOCK").strip().upper()
    account = StockAccount(account_id, account_type, args.bridge_id)
    trader = XtQuantTrader(account=account)
    print_json({
        "case": "开始",
        "ok": True,
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "account_id": account_id,
        "account_type": account_type,
        "order_id_filter": str(args.order_id or "").strip(),
        "read_only": True,
    })

    try:
        connect_result = trader.connect()
        print_json({
            "case": "连接交易通道",
            "ok": connect_result == 0,
            "result": connect_result,
        })
        if connect_result != 0:
            return 1

        order_result = query_and_print(
            "委托订单",
            lambda: trader.query_stock_orders(
                account,
                cancelable_only=args.cancelable_only,
            ),
            order_id_filter=args.order_id,
            max_rows=args.max_rows,
        )
        trade_result = query_and_print(
            "成交订单",
            lambda: trader.query_stock_trades(account),
            order_id_filter=args.order_id,
            max_rows=args.max_rows,
        )
        overall_ok = bool(
            order_result["ok"]
            and trade_result["ok"]
            and order_result.get("missing_order_ids", 0) == 0
            and trade_result.get("missing_order_ids", 0) == 0
        )
        print_json({
            "case": "汇总",
            "ok": overall_ok,
            "委托查询正常": bool(order_result["ok"]),
            "成交查询正常": bool(trade_result["ok"]),
            "委托记录数": len(order_result["records"]),
            "成交记录数": len(trade_result["records"]),
            "委托缺少order_id": order_result.get("missing_order_ids", 0),
            "成交缺少order_id": trade_result.get("missing_order_ids", 0),
        })
        return 0 if overall_ok else 1
    finally:
        try:
            trader.disconnect()
        except Exception:
            pass
        close_trade_client()


if __name__ == "__main__":
    raise SystemExit(main())
