# -*- coding: utf-8 -*-
"""cftrader simulation-account benchmark for real QMT submission paths.

This script submits orders to the configured simulation account. Keep
CONFIRM_SIMULATION_ACCOUNT equal to ACCOUNT_ID before running.
"""

from __future__ import print_function

import json
import math
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from cfquant import configure, xtconstant, xtdata
from cfquant.cftrader import CfQuantTrader
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback, close_trade_client
from cfquant.xttype import StockAccount, is_cancelable_order


# ======================== 用户配置区 ========================
# 会直接向模拟账号提交委托。运行前核对账号、标的、买卖方向、数量和价格。
ACCOUNT_ID = "900010001595"
ACCOUNT_TYPE = "CREDIT"
BRIDGE_ID = "acct_4b2b38c167"
TRANSPORT = "auto"
CONFIRM_SIMULATION_ACCOUNT = "900010001595"

STOCK_CODE = "600000.SH"
SIDE = "buy"                         # buy=买入，sell=卖出
ORDER_COUNT = 100
VOLUME = 100
PRICE_TYPE = xtconstant.FIX_PRICE
PRICE = None                         # None 时按行情参考价自动计算
AUTO_PRICE_FACTOR = 0.95             # 买入用 95% 最新价，卖出用 105% 最新价
FALLBACK_PRICE = 10.0

RUN_MODES = ("batch_sync", "sync", "batch_async", "async")
STRATEGY_PREFIX = "cfq_batch_sim"
ORDER_REMARK_PREFIX = "cfqsim"
STOP_ON_ERROR = False

REQUEST_TIMEOUT = 30.0
ASYNC_RESPONSE_TIMEOUT = 8.0
QUERY_TIMEOUT = 8.0
QUERY_INTERVAL = 0.1
AUTO_CANCEL = True
CANCEL_INTERVAL = 0.02
SHOW_ORDER_SAMPLES = 3
REPORT_DIR = Path(__file__).resolve().parent / "log"
# ===========================================================


LOG_PREFIX = "【cftrader模拟批量下单测试】"
PRINT_LOCK = threading.RLock()


def configure_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def elapsed_ms(started, ended=None):
    ended = time.perf_counter() if ended is None else ended
    return round((ended - started) * 1000.0, 3)


def print_info(message, **fields):
    suffix = ""
    if fields:
        parts = []
        for key, value in fields.items():
            if isinstance(value, (dict, list, tuple)):
                text = json.dumps(value, ensure_ascii=False, default=str)
            else:
                text = str(value)
            parts.append("%s=%s" % (key, text))
        suffix = " | " + " ".join(parts)
    with PRINT_LOCK:
        print("%s%s %s%s" % (LOG_PREFIX, now_text(), message, suffix), flush=True)


def value_of(obj, *names):
    if obj is None:
        return None
    for name in names:
        try:
            value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name)
        except Exception:
            continue
        if value not in (None, ""):
            return value
    return None


def plain_object(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return value


def positive_int(value):
    if isinstance(value, bool) or value in (None, ""):
        return False
    try:
        return int(value) > 0
    except Exception:
        return False


def normalize_stock_code(value):
    code = str(value or "").strip().upper()
    if not code or "." in code:
        return code
    market = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return "%s.%s" % (code, market)


def order_type_for_side(side, account_type):
    side = str(side or "").strip().lower()
    if side == "buy":
        return xtconstant.CREDIT_BUY if str(account_type).upper() == "CREDIT" else xtconstant.STOCK_BUY
    if side == "sell":
        return xtconstant.CREDIT_SELL if str(account_type).upper() == "CREDIT" else xtconstant.STOCK_SELL
    raise ValueError("SIDE 只能配置为 buy 或 sell")


def pick_quote_row(result, stock_code):
    if isinstance(result, dict):
        if stock_code in result:
            return result[stock_code]
        raw_code = stock_code.split(".", 1)[0]
        if raw_code in result:
            return result[raw_code]
        for value in result.values():
            if isinstance(value, dict):
                return value
    if isinstance(result, (list, tuple)) and result:
        return result[0]
    return result


def number_from_quote(row):
    if not isinstance(row, dict):
        return None
    for key in (
        "lastPrice",
        "last_price",
        "LastPrice",
        "price",
        "last",
        "m_dLastPrice",
        "open",
        "Open",
        "preClose",
        "pre_close",
    ):
        value = row.get(key)
        try:
            number = float(value)
        except Exception:
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def calc_order_price(stock_code, side):
    if PRICE is not None:
        return round(float(PRICE), 3), {"source": "fixed", "reference_price": None}
    started = time.perf_counter()
    try:
        quote = xtdata.get_full_tick([stock_code])
        row = pick_quote_row(quote, stock_code)
        reference = number_from_quote(row)
        if reference:
            factor = float(AUTO_PRICE_FACTOR)
            if str(side).strip().lower() == "sell" and factor < 1:
                factor = 2.0 - factor
            price = max(0.01, reference * factor)
            return round(price + 1e-9, 2), {
                "source": "xtdata.get_full_tick",
                "reference_price": round(reference, 4),
                "latency_ms": elapsed_ms(started),
            }
        print_info("行情返回中没有可用参考价，使用备用价格", quote_summary=plain_object(row))
    except Exception as error:
        print_info("读取行情参考价失败，使用备用价格", error_type=type(error).__name__, error=str(error))
    return round(float(FALLBACK_PRICE), 2), {"source": "fallback", "reference_price": None}


def make_orders(mode_key, run_id, order_type, price):
    strategy_name = "%s_%s" % (STRATEGY_PREFIX, mode_key)
    return [
        {
            "stock_code": normalize_stock_code(STOCK_CODE),
            "order_type": int(order_type),
            "order_volume": int(VOLUME),
            "price_type": int(PRICE_TYPE),
            "price": float(price),
            "strategy_name": strategy_name,
            "order_remark": "%s_%s_%03d" % (run_id, mode_key, index + 1),
        }
        for index in range(int(ORDER_COUNT))
    ]


def order_summary(order):
    data = plain_object(order) or {}
    return {
        "account_id": value_of(data, "account_id", "m_strAccountID"),
        "stock_code": value_of(data, "stock_code", "m_strInstrumentID"),
        "order_id": value_of(data, "order_id", "m_nRef", "m_nOrderID", "m_strOrderRef"),
        "order_sysid": value_of(data, "order_sysid", "m_strOrderSysID", "m_strOrderID"),
        "order_status": value_of(data, "order_status", "m_nOrderStatus", "m_nOrderState"),
        "order_remark": value_of(data, "order_remark", "m_strRemark", "m_strOrderRemark"),
        "strategy_name": value_of(data, "strategy_name", "m_strStrategyName"),
        "traded_volume": value_of(data, "traded_volume", "m_nVolumeTraded"),
        "price": value_of(data, "price", "m_dLimitPrice", "m_dOrderPrice"),
    }


def order_matches(order, remark_prefix, strategy_name):
    summary = order_summary(order)
    remark = str(summary.get("order_remark") or "")
    current_strategy = str(summary.get("strategy_name") or "")
    return remark.startswith(remark_prefix) or current_strategy == strategy_name


class BenchmarkCallback(XtQuantTraderCallback):
    def __init__(self):
        self.lock = threading.RLock()
        self.changed = threading.Event()
        self.stock_orders = []
        self.stock_trades = []
        self.order_errors = []
        self.cancel_errors = []
        self.async_responses = []
        self.async_cancel_responses = []

    def _append(self, target, value):
        with self.lock:
            target.append((time.perf_counter(), plain_object(value)))
            self.changed.set()

    def on_connected(self):
        print_info("收到 on_connected")

    def on_disconnected(self):
        print_info("收到 on_disconnected")

    def on_stock_order(self, order):
        self._append(self.stock_orders, order)

    def on_stock_trade(self, trade):
        self._append(self.stock_trades, trade)

    def on_order_error(self, error):
        self._append(self.order_errors, error)

    def on_cancel_error(self, error):
        self._append(self.cancel_errors, error)

    def on_order_stock_async_response(self, response):
        self._append(self.async_responses, response)

    def on_cancel_order_stock_async_response(self, response):
        self._append(self.async_cancel_responses, response)

    def counts(self):
        with self.lock:
            return {
                "stock_order_callbacks": len(self.stock_orders),
                "stock_trade_callbacks": len(self.stock_trades),
                "order_error_callbacks": len(self.order_errors),
                "cancel_error_callbacks": len(self.cancel_errors),
                "async_order_responses": len(self.async_responses),
                "async_cancel_responses": len(self.async_cancel_responses),
            }

    def wait_async_responses(self, previous_count, expected_new, timeout):
        deadline = time.time() + max(0.0, float(timeout))
        target = previous_count + expected_new
        while time.time() < deadline:
            with self.lock:
                current = len(self.async_responses)
                if current >= target:
                    return current - previous_count
            self.changed.wait(min(0.1, max(0.0, deadline - time.time())))
            self.changed.clear()
        with self.lock:
            return max(0, len(self.async_responses) - previous_count)


def client_connection_info(trader):
    try:
        client = trader._get_client()
    except Exception as error:
        return {"error": str(error), "error_type": type(error).__name__}
    return {
        "client_class": type(client).__name__,
        "request_channel": getattr(client, "request_channel", ""),
        "host": getattr(client, "host", ""),
        "port": getattr(client, "port", ""),
        "pipe_name": getattr(client, "pipe_name", ""),
        "client_id": getattr(client, "client_id", ""),
    }


def summarize_batch_result(result):
    rows = result.get("results") if isinstance(result, dict) else []
    rows = rows if isinstance(rows, list) else []
    return {
        "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "submitted": int(result.get("submitted") or 0) if isinstance(result, dict) else 0,
        "failed": int(result.get("failed") or 0) if isinstance(result, dict) else 0,
        "unknown": int(result.get("unknown") or 0) if isinstance(result, dict) else 0,
        "skipped": int(result.get("skipped") or 0) if isinstance(result, dict) else 0,
        "qmt_submit_ms": result.get("qmt_submit_ms") if isinstance(result, dict) else None,
        "sample": rows[:SHOW_ORDER_SAMPLES],
    }


def summarize_single_rows(rows, asynchronous):
    field = "seq" if asynchronous else "order_id"
    return {
        "ok": all(item.get("ok") for item in rows),
        "submitted": sum(1 for item in rows if item.get("ok")),
        "failed": sum(1 for item in rows if not item.get("ok")),
        "unknown": 0,
        "skipped": 0,
        "qmt_submit_ms": None,
        "sample": rows[:SHOW_ORDER_SAMPLES],
        field + "s": [item.get(field) for item in rows if positive_int(item.get(field))][:SHOW_ORDER_SAMPLES],
    }


def query_matching_orders(trader, account, remark_prefix, strategy_name, expected_count):
    deadline = time.time() + max(0.0, float(QUERY_TIMEOUT))
    last_error = ""
    attempts = 0
    matched = []
    started = time.perf_counter()
    while time.time() < deadline:
        attempts += 1
        try:
            orders = trader.query_stock_orders(account, cancelable_only=False) or []
            matched = [order for order in orders if order_matches(order, remark_prefix, strategy_name)]
            if len(matched) >= expected_count:
                break
        except Exception as error:
            last_error = "%s: %s" % (type(error).__name__, error)
        time.sleep(max(0.01, float(QUERY_INTERVAL)))
    return {
        "attempts": attempts,
        "latency_ms": elapsed_ms(started),
        "matched_count": len(matched),
        "error": last_error,
        "orders": matched,
        "sample": [order_summary(order) for order in matched[:SHOW_ORDER_SAMPLES]],
    }


def cancel_orders(trader, account, orders):
    started = time.perf_counter()
    attempted = 0
    succeeded = 0
    skipped = 0
    errors = []
    seen = set()
    for order in orders:
        summary = order_summary(order)
        order_id = summary.get("order_id")
        if not positive_int(order_id) or str(order_id) in seen:
            skipped += 1
            continue
        seen.add(str(order_id))
        if not is_cancelable_order(order):
            skipped += 1
            continue
        attempted += 1
        try:
            result = trader.cancel_order_stock(account, order_id)
            if str(result).strip().lower() not in ("", "-1", "false", "none"):
                succeeded += 1
        except Exception as error:
            errors.append({"order_id": order_id, "error_type": type(error).__name__, "error": str(error)})
        if attempted and attempted % 20 == 0:
            print_info("撤单进度", attempted=attempted, succeeded=succeeded, errors=len(errors))
        time.sleep(max(0.0, float(CANCEL_INTERVAL)))
    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "skipped": skipped,
        "errors": errors[:SHOW_ORDER_SAMPLES],
        "latency_ms": elapsed_ms(started),
    }


def run_case(mode_key, api, trader, account, callback, run_id, order_type, price):
    orders = make_orders(mode_key, run_id, order_type, price)
    remark_prefix = "%s_%s" % (run_id, mode_key)
    strategy_name = "%s_%s" % (STRATEGY_PREFIX, mode_key)
    label_map = {
        "batch_sync": "批量同步 order_stock_batch",
        "sync": "单笔同步循环 order_stock x100",
        "batch_async": "批量异步 order_stock_batch_async",
        "async": "单笔异步循环 order_stock_async x100",
    }
    print_info("开始测试路径", mode=mode_key, label=label_map.get(mode_key), order_count=len(orders))
    before_async = callback.counts()["async_order_responses"]
    started = time.perf_counter()
    raw_result = None
    error = None
    single_rows = []
    try:
        if mode_key == "batch_sync":
            raw_result = api.order_stock_batch(account, orders, strategy_name=STRATEGY_PREFIX, stop_on_error=STOP_ON_ERROR)
            summary = summarize_batch_result(raw_result)
            rpc_requests = 1
        elif mode_key == "batch_async":
            raw_result = api.order_stock_batch_async(account, orders, strategy_name=STRATEGY_PREFIX, stop_on_error=STOP_ON_ERROR)
            summary = summarize_batch_result(raw_result)
            rpc_requests = 1
        elif mode_key == "sync":
            for index, row in enumerate(orders):
                try:
                    order_id = api.order_stock(
                        account,
                        row["stock_code"],
                        row["order_type"],
                        row["order_volume"],
                        row["price_type"],
                        row["price"],
                        row["strategy_name"],
                        row["order_remark"],
                    )
                    single_rows.append({"index": index, "ok": positive_int(order_id), "order_id": order_id, "error": ""})
                except Exception as item_error:
                    single_rows.append({
                        "index": index,
                        "ok": False,
                        "order_id": None,
                        "error": "%s: %s" % (type(item_error).__name__, item_error),
                    })
            summary = summarize_single_rows(single_rows, asynchronous=False)
            rpc_requests = len(orders)
        elif mode_key == "async":
            for index, row in enumerate(orders):
                try:
                    seq = api.order_stock_async(
                        account,
                        row["stock_code"],
                        row["order_type"],
                        row["order_volume"],
                        row["price_type"],
                        row["price"],
                        row["strategy_name"],
                        row["order_remark"],
                    )
                    single_rows.append({"index": index, "ok": positive_int(seq), "seq": seq, "error": ""})
                except Exception as item_error:
                    single_rows.append({
                        "index": index,
                        "ok": False,
                        "seq": None,
                        "error": "%s: %s" % (type(item_error).__name__, item_error),
                    })
            summary = summarize_single_rows(single_rows, asynchronous=True)
            rpc_requests = len(orders)
        else:
            raise ValueError("unknown RUN_MODES item: %s" % mode_key)
    except Exception as run_error:
        error = "%s: %s" % (type(run_error).__name__, run_error)
        summary = {
            "ok": False,
            "submitted": 0,
            "failed": len(orders),
            "unknown": 0,
            "skipped": 0,
            "qmt_submit_ms": None,
            "sample": [],
        }
        rpc_requests = 1 if mode_key.startswith("batch_") else len(orders)
    submit_ms = elapsed_ms(started)
    async_received = 0
    if mode_key in ("batch_async", "async"):
        async_received = callback.wait_async_responses(before_async, len(orders), ASYNC_RESPONSE_TIMEOUT)
    query = query_matching_orders(
        trader,
        account,
        remark_prefix,
        strategy_name,
        min(len(orders), max(0, int(summary.get("submitted") or 0))),
    )
    cancel = cancel_orders(trader, account, query["orders"]) if AUTO_CANCEL else {"attempted": 0, "succeeded": 0, "skipped": 0, "errors": [], "latency_ms": 0.0}
    case_result = {
        "mode": mode_key,
        "label": label_map.get(mode_key, mode_key),
        "account_id": ACCOUNT_ID,
        "account_type": ACCOUNT_TYPE,
        "bridge_id": BRIDGE_ID,
        "stock_code": normalize_stock_code(STOCK_CODE),
        "side": SIDE,
        "price": price,
        "volume": VOLUME,
        "order_count": len(orders),
        "rpc_requests": rpc_requests,
        "submit_elapsed_ms": submit_ms,
        "per_order_submit_ms": round(submit_ms / float(len(orders)), 4),
        "async_responses_received": async_received,
        "result": summary,
        "query": {key: value for key, value in query.items() if key != "orders"},
        "cancel": cancel,
        "callback_counts": callback.counts(),
        "error": error,
    }
    print_info(
        "路径测试完成",
        mode=mode_key,
        submit_elapsed_ms=case_result["submit_elapsed_ms"],
        per_order_submit_ms=case_result["per_order_submit_ms"],
        submitted=summary.get("submitted"),
        failed=summary.get("failed"),
        unknown=summary.get("unknown"),
        matched=query.get("matched_count"),
        cancel_attempted=cancel.get("attempted"),
        async_responses=async_received,
        error=error or "",
    )
    return case_result


def write_reports(payload):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / ("cftrader模拟账号批量下单测试_%s.json" % stamp)
    md_path = REPORT_DIR / ("cftrader模拟账号批量下单测试_%s.md" % stamp)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# cftrader 模拟账号批量下单测试",
        "",
        "- 时间：%s" % payload["started_at"],
        "- 账号：%s / %s / %s" % (payload["account_id"], payload["account_type"], payload["bridge_id"]),
        "- 标的：%s，方向：%s，价格：%s，单笔数量：%s，单路径笔数：%s" % (
            payload["stock_code"],
            payload["side"],
            payload["price"],
            payload["volume"],
            payload["order_count"],
        ),
        "",
        "| 路径 | RPC 次数 | 提交耗时 | 单笔均摊 | submitted | failed | unknown | 异步反馈 | 查询匹配 | 撤单尝试 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["results"]:
        result = row["result"]
        lines.append(
            "| {label} | {rpc_requests} | {submit_elapsed_ms:.3f} ms | {per_order_submit_ms:.4f} ms | "
            "{submitted} | {failed} | {unknown} | {async_responses_received} | {matched} | {cancel_attempted} |".format(
                label=row["label"],
                rpc_requests=row["rpc_requests"],
                submit_elapsed_ms=row["submit_elapsed_ms"],
                per_order_submit_ms=row["per_order_submit_ms"],
                submitted=result.get("submitted"),
                failed=result.get("failed"),
                unknown=result.get("unknown"),
                async_responses_received=row["async_responses_received"],
                matched=row["query"].get("matched_count"),
                cancel_attempted=row["cancel"].get("attempted"),
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def validate_config():
    if str(CONFIRM_SIMULATION_ACCOUNT).strip() != str(ACCOUNT_ID).strip():
        raise ValueError("CONFIRM_SIMULATION_ACCOUNT 必须等于 ACCOUNT_ID，避免误下单")
    if str(ACCOUNT_ID).strip() != "900010001595":
        raise ValueError("本脚本仅用于模拟账号 900010001595")
    if str(ACCOUNT_TYPE).strip().upper() != "CREDIT":
        raise ValueError("本机配置中 900010001595 是 CREDIT 信用账号")
    if int(ORDER_COUNT) <= 0 or int(VOLUME) <= 0:
        raise ValueError("ORDER_COUNT 和 VOLUME 必须大于 0")
    if not RUN_MODES:
        raise ValueError("RUN_MODES 不能为空")


def main():
    configure_stdout()
    validate_config()
    stock_code = normalize_stock_code(STOCK_CODE)
    configure(transport=TRANSPORT, bridge_id=BRIDGE_ID, timeout=REQUEST_TIMEOUT)
    price, price_info = calc_order_price(stock_code, SIDE)
    order_type = order_type_for_side(SIDE, ACCOUNT_TYPE)
    run_id = "%s_%s" % (ORDER_REMARK_PREFIX, datetime.now().strftime("%H%M%S"))
    payload = {
        "started_at": datetime.now().isoformat(timespec="milliseconds"),
        "account_id": ACCOUNT_ID,
        "account_type": ACCOUNT_TYPE,
        "bridge_id": BRIDGE_ID,
        "transport": TRANSPORT,
        "stock_code": stock_code,
        "side": SIDE,
        "order_type": order_type,
        "price": price,
        "price_info": price_info,
        "volume": VOLUME,
        "order_count": ORDER_COUNT,
        "run_modes": list(RUN_MODES),
        "results": [],
    }
    print_info("测试启动", config=payload)
    account = StockAccount(ACCOUNT_ID, ACCOUNT_TYPE, BRIDGE_ID)
    callback = BenchmarkCallback()
    trader = XtQuantTrader(callback=callback, account=account)
    trader.set_timeout(REQUEST_TIMEOUT)
    api = CfQuantTrader(trader)
    try:
        print_info("开始连接交易通道")
        started = time.perf_counter()
        connect_result = trader.connect()
        payload["connect"] = {
            "result": connect_result,
            "latency_ms": elapsed_ms(started),
            "connection": client_connection_info(trader),
            "last_error": trader.last_connect_error,
            "last_error_type": trader.last_connect_error_type,
            "last_stage": trader.last_connect_stage,
        }
        print_info("连接完成", connect=payload["connect"])
        if connect_result != 0:
            raise RuntimeError("交易通道连接失败：%s" % (trader.last_connect_error or trader.last_connect_stage))
        for mode_key in RUN_MODES:
            result = run_case(mode_key, api, trader, account, callback, run_id, order_type, price)
            payload["results"].append(result)
            time.sleep(0.5)
        payload["finished_at"] = datetime.now().isoformat(timespec="milliseconds")
        payload["final_callback_counts"] = callback.counts()
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), flush=True)
        json_path, md_path = write_reports(payload)
        print_info("报告已写入", json=str(json_path), markdown=str(md_path))
        return 0
    finally:
        print_info("断开交易通道并释放资源")
        try:
            trader.disconnect()
        finally:
            close_trade_client()


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = int(main() or 0)
    except SystemExit as exc:
        try:
            exit_code = int(exc.code or 0)
        except Exception:
            exit_code = 1
    except Exception:
        traceback.print_exc()
        exit_code = 1
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(exit_code)
