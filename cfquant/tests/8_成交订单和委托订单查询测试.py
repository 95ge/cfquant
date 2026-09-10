# -*- coding: utf-8 -*-
"""查询成交和委托记录，并检查每条记录是否能正常返回 order_id。"""

from types import SimpleNamespace

from _helpers import (
    configure_cfquant,
    configure_stdout,
    default_account_id,
    print_json,
)

from cfquant.xttrader import XtQuantTrader, close_trade_client
from cfquant.xttype import StockAccount


# ======================== 用户配置区 ========================
# 直接修改下面的配置，然后运行本文件；不读取命令行参数。
TRANSPORT = "auto"       # auto 自动发现；也可填写 ctypes、web_lttx 或 lttx
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0    # 请求超时，单位秒
ACCOUNT_ID = ""           # 留空读取 CFQUANT_ACCOUNT_ID 或 Web 默认账号
ACCOUNT_TYPE = "STOCK"
ORDER_ID = ""             # 留空显示全部，否则按委托号或系统编号筛选
CANCELABLE_ONLY = False
MAX_ROWS = 100            # 每类显示条数，0 不显示明细
# ===========================================================


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
    config = SimpleNamespace(
        transport=TRANSPORT,
        bridge_id=BRIDGE_ID,
        timeout=REQUEST_TIMEOUT,
        account_id=ACCOUNT_ID,
        account_type=ACCOUNT_TYPE,
        order_id=ORDER_ID,
        cancelable_only=CANCELABLE_ONLY,
        max_rows=MAX_ROWS,
    )
    config.account_id = str(config.account_id or "").strip() or default_account_id()
    if config.max_rows < 0:
        print_json({"case": "配置检查", "ok": False, "error": "MAX_ROWS 不能小于 0"})
        return 2

    account_id = str(config.account_id or "").strip()
    if not account_id:
        print_json({
            "case": "参数检查",
            "ok": False,
            "error": "缺少资金账号，请在顶部用户配置区填写 ACCOUNT_ID。",
        })
        return 2

    configure_cfquant(config)
    account_type = str(config.account_type or "STOCK").strip().upper()
    account = StockAccount(account_id, account_type, config.bridge_id)
    trader = XtQuantTrader(account=account)
    print_json({
        "case": "开始",
        "ok": True,
        "transport": config.transport,
        "bridge_id": config.bridge_id,
        "account_id": account_id,
        "account_type": account_type,
        "order_id_filter": str(config.order_id or "").strip(),
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
                cancelable_only=config.cancelable_only,
            ),
            order_id_filter=config.order_id,
            max_rows=config.max_rows,
        )
        trade_result = query_and_print(
            "成交订单",
            lambda: trader.query_stock_trades(account),
            order_id_filter=config.order_id,
            max_rows=config.max_rows,
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
