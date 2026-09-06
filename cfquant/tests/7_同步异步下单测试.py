# -*- coding: utf-8 -*-
"""cfquant 同步/异步下单、回调、委托查询和撤单综合测试。"""

import json
import threading
import time
from datetime import datetime

from _helpers import configure_stdout

from cfquant import configure, xtconstant
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback, close_trade_client
from cfquant.xttype import StockAccount, is_cancelable_order


# ======================== 用户配置区 ========================
# 直接修改以下参数，运行脚本后会立即按这些配置执行下单测试。
ACCOUNT_ID = "8885060548"
ACCOUNT_TYPE = "STOCK"
BRIDGE_ID = "default"
TRANSPORT = "auto"

STOCK_CODE = "002649.SZ"
SIDE = "sell"                 # buy=买入，sell=卖出
PRICE = 10.2
VOLUME = 100
PRICE_TYPE = xtconstant.FIX_PRICE

ORDER_MODE = "both"           # sync=仅同步，async=仅异步，both=两者都测试
STRATEGY_NAME = "cfquant_order_api_test"
ORDER_REMARK_PREFIX = "cfquant_order_test"

AUTO_CANCEL = True            # 委托仍可撤时，测试结束前自动撤单
CALLBACK_TIMEOUT = 5.0
QUERY_TIMEOUT = 5.0
QUERY_INTERVAL = 0.05
REQUEST_TIMEOUT = 15.0
# ===========================================================


PRINT_LOCK = threading.RLock()


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def value_of(obj, *names):
    for name in names:
        try:
            value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name)
        except Exception:
            continue
        if value not in (None, ""):
            return value
    return None


def plain_object(value):
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return value


def print_step(step, message, **fields):
    suffix = ""
    if fields:
        suffix = " | " + " ".join(
            "%s=%s" % (key, json.dumps(value, ensure_ascii=False, default=str))
            for key, value in fields.items()
        )
    with PRINT_LOCK:
        label = "回调" if step == "回调" else "第%s步" % step
        print("[%s] %s：%s%s" % (now_text(), label, message, suffix), flush=True)


def normalize_stock_code(value):
    code = str(value or "").strip().upper()
    if not code or "." in code:
        return code
    return "%s.%s" % (code, "SH" if code.startswith(("5", "6", "9")) else "SZ")


def status_name(value):
    names = {
        xtconstant.ORDER_UNREPORTED: "未报",
        xtconstant.ORDER_WAIT_REPORTING: "待报",
        xtconstant.ORDER_REPORTED: "已报",
        xtconstant.ORDER_REPORTED_CANCEL: "已报待撤",
        xtconstant.ORDER_PARTSUCC_CANCEL: "部成待撤",
        xtconstant.ORDER_PART_CANCEL: "部撤",
        xtconstant.ORDER_CANCELED: "已撤",
        xtconstant.ORDER_PART_SUCC: "部分成交",
        xtconstant.ORDER_SUCCEEDED: "已成",
        xtconstant.ORDER_JUNK: "废单",
        xtconstant.ORDER_UNKNOWN: "未知",
    }
    try:
        value = int(value)
    except Exception:
        return str(value)
    return names.get(value, str(value))


def order_summary(order):
    if order is None:
        return None
    status = value_of(order, "order_status", "m_nOrderStatus", "m_nOrderState")
    return {
        "account_id": value_of(order, "account_id", "m_strAccountID"),
        "stock_code": value_of(order, "stock_code", "m_strInstrumentID"),
        "order_id": value_of(order, "order_id", "m_nRef", "m_nOrderID", "m_strOrderRef"),
        "order_sysid": value_of(order, "order_sysid", "m_strOrderSysID"),
        "order_type": value_of(order, "order_type", "m_nOrderType"),
        "order_volume": value_of(order, "order_volume", "m_nVolumeTotalOriginal"),
        "price": value_of(order, "price", "m_dLimitPrice", "m_dOrderPrice"),
        "traded_volume": value_of(order, "traded_volume", "m_nVolumeTraded"),
        "traded_price": value_of(order, "traded_price", "m_dTradedPrice"),
        "order_status": status,
        "order_status_name": status_name(status),
        "status_msg": value_of(order, "status_msg", "m_strErrorMsg", "m_strStatusMsg"),
        "strategy_name": value_of(order, "strategy_name", "m_strStrategyName"),
        "order_remark": value_of(order, "order_remark", "m_strRemark", "m_strOrderRemark"),
    }


class TestCallback(XtQuantTraderCallback):
    def __init__(self):
        self.lock = threading.RLock()
        self.changed = threading.Event()
        self.orders = []
        self.trades = []
        self.order_errors = []
        self.cancel_errors = []
        self.async_order_responses = []
        self.async_cancel_responses = []

    def _append(self, target, value):
        with self.lock:
            target.append(value)
            self.changed.set()

    def on_connected(self):
        print_step("回调", "收到 on_connected，交易通道已连接")

    def on_disconnected(self):
        print_step("回调", "收到 on_disconnected，交易通道已断开")

    def on_stock_order(self, order):
        self._append(self.orders, order)
        data = order_summary(order)
        print_step(
            "回调",
            "收到 on_stock_order 委托回调",
            order_id=data.get("order_id"),
            stock_code=data.get("stock_code"),
            status=data.get("order_status_name"),
            strategy_name=data.get("strategy_name"),
            order_remark=data.get("order_remark"),
        )

    def on_stock_trade(self, trade):
        self._append(self.trades, trade)
        print_step(
            "回调",
            "收到 on_stock_trade 成交回调",
            order_id=value_of(trade, "order_id", "m_nRef", "m_nOrderID"),
            traded_id=value_of(trade, "traded_id", "m_strTradeID"),
            traded_volume=value_of(trade, "traded_volume", "volume", "m_nVolume"),
            traded_price=value_of(trade, "traded_price", "price", "m_dPrice"),
        )

    def on_order_error(self, error):
        self._append(self.order_errors, error)
        print_step(
            "回调",
            "收到 on_order_error 下单错误回调",
            order_id=value_of(error, "order_id", "m_nRef", "m_nOrderID"),
            error_id=value_of(error, "error_id", "m_nErrorID"),
            error_msg=value_of(error, "error_msg", "m_strErrorMsg"),
        )

    def on_cancel_error(self, error):
        self._append(self.cancel_errors, error)
        print_step(
            "回调",
            "收到 on_cancel_error 撤单错误回调",
            order_id=value_of(error, "order_id", "m_nRef", "m_nOrderID"),
            error_id=value_of(error, "error_id", "m_nErrorID"),
            error_msg=value_of(error, "error_msg", "m_strErrorMsg"),
        )

    def on_order_stock_async_response(self, response):
        self._append(self.async_order_responses, response)
        print_step(
            "回调",
            "收到 on_order_stock_async_response 异步委托反馈",
            seq=value_of(response, "seq", "m_nSeq"),
            order_id=value_of(response, "order_id", "m_nRef", "m_nOrderID"),
            strategy_name=value_of(response, "strategy_name", "m_strStrategyName"),
            order_remark=value_of(response, "order_remark", "m_strRemark"),
        )

    def on_cancel_order_stock_async_response(self, response):
        self._append(self.async_cancel_responses, response)
        print_step(
            "回调",
            "收到 on_cancel_order_stock_async_response 异步撤单反馈",
            seq=value_of(response, "seq", "m_nSeq"),
            order_id=value_of(response, "order_id", "m_nOrderID"),
            cancel_result=value_of(response, "cancel_result", "m_nCancelResult"),
        )

    def wait_async_order_response(self, seq, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for response in self.async_order_responses:
                    if value_of(response, "seq", "m_nSeq") == seq:
                        return response
            self.changed.wait(min(0.05, max(0.0, deadline - time.time())))
            self.changed.clear()
        return None


def strict_json_check(orders):
    payload = [plain_object(order) for order in orders or []]
    text = json.dumps(payload, ensure_ascii=False)
    json.loads(text)
    return len(text)


def query_order_until_found(trader, account, order_id, order_remark, timeout, interval):
    deadline = time.time() + timeout
    attempts = 0
    json_size = 0
    json_error = None
    while time.time() < deadline:
        attempts += 1
        orders = trader.query_stock_orders(account, cancelable_only=False) or []
        try:
            json_size = strict_json_check(orders)
            json_error = None
        except Exception as error:
            json_error = "%s: %s" % (type(error).__name__, error)
        for order in orders:
            current_id = value_of(order, "order_id", "m_nRef", "m_nOrderID", "m_strOrderRef")
            current_remark = value_of(order, "order_remark", "m_strRemark", "m_strOrderRemark")
            if order_id not in (None, "", -1, "-1") and str(current_id) == str(order_id):
                return order, attempts, json_size, json_error
            if order_remark and current_remark == order_remark:
                return order, attempts, json_size, json_error
        time.sleep(interval)
    return None, attempts, json_size, json_error


def wait_order_final(trader, account, order_id, timeout, interval):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        latest, _, _, _ = query_order_until_found(
            trader, account, order_id, "", min(0.3, max(0.05, deadline - time.time())), interval
        )
        if latest is not None and not is_cancelable_order(latest):
            return latest
        time.sleep(interval)
    return latest


def cancel_test_order(trader, account, order, auto_cancel, step, timeout, interval):
    if order is None:
        print_step(step, "未查询到委托，无法判断是否需要撤单")
        return
    order_id = value_of(order, "order_id", "m_nRef", "m_nOrderID", "m_strOrderRef")
    if not is_cancelable_order(order):
        print_step(
            step,
            "委托当前不可撤，不执行撤单",
            order_id=order_id,
            status=status_name(value_of(order, "order_status", "m_nOrderStatus")),
        )
        return
    if not auto_cancel:
        print_step(step, "自动撤单已关闭，委托将保留", order_id=order_id)
        return
    result = trader.cancel_order_stock(account, order_id)
    print_step(step, "已调用同步撤单接口", order_id=order_id, cancel_result=result)
    final_order = wait_order_final(trader, account, order_id, timeout, interval)
    final_status = value_of(final_order, "order_status", "m_nOrderStatus")
    print_step(
        step,
        "撤单后的最终状态",
        order_id=order_id,
        status=final_status,
        status_name=status_name(final_status),
    )


def submit_sync(trader, account, config, callback):
    remark = "%s_sync_%s" % (config["remark_prefix"], int(time.time() * 1000))
    print_step(
        "4A",
        "开始调用同步 order_stock",
        stock_code=config["stock_code"],
        side=config["side"],
        price=config["price"],
        volume=config["volume"],
        order_remark=remark,
    )
    started = time.perf_counter()
    order_id = trader.order_stock(
        account,
        config["stock_code"],
        config["order_type"],
        config["volume"],
        config["price_type"],
        config["price"],
        config["strategy_name"] + "_sync",
        remark,
    )
    print_step(
        "4A",
        "同步接口已返回本地委托编号",
        order_id=order_id,
        return_type=type(order_id).__name__,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    order, attempts, json_size, json_error = query_order_until_found(
        trader, account, order_id, remark, config["query_timeout"], config["query_interval"]
    )
    print_step(
        "4A",
        "query_stock_orders 查询完成",
        found=order is not None,
        attempts=attempts,
        json_parse_ok=json_error is None,
        json_error=json_error,
        json_chars=json_size,
        order=order_summary(order),
    )
    time.sleep(min(0.5, config["callback_timeout"]))
    cancel_test_order(
        trader, account, order, config["auto_cancel"], "4A", config["query_timeout"], config["query_interval"]
    )
    return order_id, order


def submit_async(trader, account, config, callback):
    remark = "%s_async_%s" % (config["remark_prefix"], int(time.time() * 1000))
    print_step(
        "4B",
        "开始调用异步 order_stock_async",
        stock_code=config["stock_code"],
        side=config["side"],
        price=config["price"],
        volume=config["volume"],
        order_remark=remark,
    )
    started = time.perf_counter()
    seq = trader.order_stock_async(
        account,
        config["stock_code"],
        config["order_type"],
        config["volume"],
        config["price_type"],
        config["price"],
        config["strategy_name"] + "_async",
        remark,
    )
    print_step(
        "4B",
        "异步接口已返回请求序号；该值不是委托编号",
        seq=seq,
        return_type=type(seq).__name__,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    response = callback.wait_async_order_response(seq, config["callback_timeout"])
    order_id = value_of(response, "order_id", "m_nRef", "m_nOrderID")
    print_step(
        "4B",
        "异步委托反馈等待完成",
        received=response is not None,
        seq=seq,
        order_id=order_id,
        response=plain_object(response) if response else None,
    )
    order, attempts, json_size, json_error = query_order_until_found(
        trader, account, order_id, remark, config["query_timeout"], config["query_interval"]
    )
    if order_id in (None, "", -1, "-1") and order is not None:
        order_id = value_of(order, "order_id", "m_nRef", "m_nOrderID", "m_strOrderRef")
    print_step(
        "4B",
        "query_stock_orders 查询完成",
        found=order is not None,
        attempts=attempts,
        json_parse_ok=json_error is None,
        json_error=json_error,
        json_chars=json_size,
        order_id=order_id,
        order=order_summary(order),
    )
    cancel_test_order(
        trader, account, order, config["auto_cancel"], "4B", config["query_timeout"], config["query_interval"]
    )
    return seq, order_id, order


def main():
    configure_stdout()
    stock_code = normalize_stock_code(STOCK_CODE)
    side = str(SIDE).strip().lower()
    mode = str(ORDER_MODE).strip().lower()
    config = {
        "account_id": str(ACCOUNT_ID).strip(),
        "account_type": str(ACCOUNT_TYPE).strip().upper(),
        "bridge_id": str(BRIDGE_ID).strip(),
        "transport": str(TRANSPORT).strip(),
        "stock_code": stock_code,
        "side": side,
        "order_type": xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL,
        "price": float(PRICE),
        "volume": int(VOLUME),
        "price_type": int(PRICE_TYPE),
        "mode": mode,
        "strategy_name": str(STRATEGY_NAME).strip(),
        "remark_prefix": str(ORDER_REMARK_PREFIX).strip(),
        "callback_timeout": max(0.1, float(CALLBACK_TIMEOUT)),
        "query_timeout": max(0.1, float(QUERY_TIMEOUT)),
        "query_interval": max(0.01, float(QUERY_INTERVAL)),
        "auto_cancel": bool(AUTO_CANCEL),
    }

    print_step("1", "读取并校验代码中的测试参数", **config)
    if not config["account_id"] or not stock_code:
        raise ValueError("账号和证券代码不能为空")
    if config["price"] <= 0 or config["volume"] <= 0:
        raise ValueError("委托价格和数量必须大于 0")
    if side not in ("buy", "sell"):
        raise ValueError("SIDE 只能配置为 buy 或 sell")
    if mode not in ("sync", "async", "both"):
        raise ValueError("ORDER_MODE 只能配置为 sync、async 或 both")

    configure(transport=config["transport"], bridge_id=config["bridge_id"], timeout=REQUEST_TIMEOUT)
    account = StockAccount(config["account_id"], config["account_type"], config["bridge_id"])
    callback = TestCallback()
    trader = XtQuantTrader(callback=callback, account=account)
    trader.set_timeout(REQUEST_TIMEOUT)
    results = {}
    try:
        print_step("2", "连接 cfquant 交易通道并注册交易回调")
        started = time.perf_counter()
        connect_result = trader.connect()
        print_step(
            "2",
            "交易通道连接完成",
            connect_result=connect_result,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        if connect_result != 0:
            raise RuntimeError("交易通道连接失败")

        print_step("3", "下单前查询资金和目标证券持仓")
        asset = trader.query_stock_asset(account)
        position = trader.query_stock_position(account, stock_code)
        print_step(
            "3",
            "下单前检查完成",
            available_cash=value_of(asset, "cash", "available", "m_dAvailable"),
            position_volume=value_of(position, "volume", "m_nVolume") if position else 0,
            can_use_volume=value_of(position, "can_use_volume", "m_nCanUseVolume") if position else 0,
        )

        if config["mode"] in ("sync", "both"):
            results["sync"] = submit_sync(trader, account, config, callback)
        if config["mode"] == "both":
            time.sleep(0.5)
        if config["mode"] in ("async", "both"):
            results["async"] = submit_async(trader, account, config, callback)

        print_step(
            "5",
            "测试流程完成",
            sync_order_id=results.get("sync", (None,))[0] if "sync" in results else None,
            async_seq=results.get("async", (None,))[0] if "async" in results else None,
            async_order_id=results.get("async", (None, None))[1] if "async" in results else None,
            order_callbacks=len(callback.orders),
            trade_callbacks=len(callback.trades),
            order_errors=len(callback.order_errors),
            cancel_errors=len(callback.cancel_errors),
        )
        return 0
    finally:
        print_step("6", "断开交易通道并释放资源")
        try:
            trader.disconnect()
        finally:
            close_trade_client()


if __name__ == "__main__":
    raise SystemExit(main())
