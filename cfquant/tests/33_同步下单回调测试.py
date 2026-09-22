# -*- coding: utf-8 -*-
"""测试同步下单返回值与委托回调是否一致。

运行：python -X utf8 "cfquant/tests/33_同步下单回调测试.py"
"""

import json
import sys
import threading
import time
import uuid

from _helpers import PROJECT_ROOT, configure_stdout
from cfquant import configure, xtconstant
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount


CONFIG_FILE = PROJECT_ROOT / "runtime/config/cfquant_web_config.json"
BRIDGE_ID = "default"
TRANSPORT = "auto"
STOCK_CODE = "000001.SZ"
ORDER_TYPE = xtconstant.STOCK_BUY
ORDER_VOLUME = 100
PRICE_TYPE = xtconstant.FIX_PRICE
PRICE = 10.0
REQUEST_TIMEOUT = 15.0
CALLBACK_TIMEOUT = 30.0
STRATEGY_NAME = "cfquant_sync33"


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str), flush=True)


def value_of(value, *names):
    for name in names:
        item = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if item not in (None, ""):
            return item
    return None


def plain(value):
    return dict(value) if isinstance(value, dict) else dict(vars(value))


def load_default_account():
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    key = str(data.get("default_account_key") or "default:STOCK:").strip()
    configs = data.get("account_configs") or {}
    row = configs.get(key)
    if not row:
        matches = [item for item in configs.values()
                   if item.get("bridge_id") == BRIDGE_ID and item.get("enabled") is not False]
        if len(matches) != 1:
            raise RuntimeError("无法唯一确定 default 启用账号")
        row = matches[0]
    if row.get("bridge_id") != BRIDGE_ID or row.get("account_type", "").upper() != "STOCK":
        raise RuntimeError("default 配置不是 STOCK 账号")
    return row


class Callback(XtQuantTraderCallback):
    def __init__(self):
        self.lock = threading.Lock()
        self.orders = []
        self.trades = []
        self.errors = []

    def on_stock_order(self, order):
        row = plain(order)
        with self.lock:
            self.orders.append(row)
        emit("委托回调", order_id=value_of(row, "order_id", "m_nRef", "m_nOrderID"),
             order_remark=value_of(row, "order_remark", "m_strRemark", "m_strOrderRemark"),
             order_status=value_of(row, "order_status", "m_nOrderStatus", "m_nOrderState"))

    def on_stock_trade(self, trade):
        row = plain(trade)
        with self.lock:
            self.trades.append(row)
        emit("成交回调", order_id=value_of(row, "order_id", "m_nRef", "m_nOrderID"),
             traded_volume=value_of(row, "traded_volume", "volume", "m_nVolume"))

    def on_order_error(self, error):
        row = plain(error)
        with self.lock:
            self.errors.append(row)
        emit("下单错误回调", **row)

    def snapshot(self):
        with self.lock:
            return list(self.orders), list(self.trades), list(self.errors)


def main():
    configure_stdout()
    account_row = load_default_account()
    account_id = str(account_row["account_id"])
    remark = "sync33_%s" % uuid.uuid4().hex[:10]
    emit("测试配置", account_id=account_id, account_type=account_row.get("account_type"),
         stock_code=STOCK_CODE, volume=ORDER_VOLUME, price=PRICE, order_remark=remark)

    configure(transport=TRANSPORT, bridge_id=BRIDGE_ID, timeout=REQUEST_TIMEOUT)
    account = StockAccount(account_id, account_row["account_type"], BRIDGE_ID)
    callback = Callback()
    trader = XtQuantTrader(callback=callback, account=account)
    trader.set_timeout(REQUEST_TIMEOUT)
    order_id = -1
    try:
        trader.start()
        if trader.connect() != 0:
            raise RuntimeError("交易连接失败")
        if trader.subscribe(account) != 0:
            raise RuntimeError("账号订阅失败")

        order_id = trader.order_stock(
            account, STOCK_CODE, ORDER_TYPE, ORDER_VOLUME,
            PRICE_TYPE, PRICE, STRATEGY_NAME, remark,
        )
        emit("同步下单返回", order_id=order_id,
             accepted=order_id not in (None, -1, "-1"))

        deadline = time.time() + CALLBACK_TIMEOUT
        matched = None
        while time.time() < deadline:
            orders, _, _ = callback.snapshot()
            for order in orders:
                callback_id = value_of(order, "order_id", "m_nRef", "m_nOrderID", "m_strOrderRef")
                callback_remark = value_of(order, "order_remark", "m_strRemark", "m_strOrderRemark")
                if (order_id not in (None, -1, "-1") and str(callback_id) == str(order_id)) or callback_remark == remark:
                    matched = order
                    break
            if matched is not None:
                break
            time.sleep(0.1)
    finally:
        orders, trades, errors = callback.snapshot()
        matched = matched if "matched" in locals() else None
        summary = {
            "order_id": order_id,
            "order_returned": order_id not in (None, -1, "-1"),
            "order_callback_count": len(orders),
            "matched_order_callback": matched is not None,
            "trade_callback_count": len(trades),
            "order_error_count": len(errors),
            "order_remark": remark,
        }
        report_path = PROJECT_ROOT / "log" / ("sync33_%s.json" % uuid.uuid4().hex[:10])
        report_path.write_text(json.dumps({"summary": summary, "orders": orders,
                                           "trades": trades, "errors": errors},
                                          ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        emit("测试汇总", **summary, report=str(report_path))
        trader.stop()
    return 0 if summary["order_returned"] and summary["matched_order_callback"] else 1


if __name__ == "__main__":
    sys.exit(main())
