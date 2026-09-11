# coding: utf-8
"""Local benchmark for cftrader 100-order submission paths.

This script uses an in-process fake QMT trade bridge. It does not connect to
Web, LTtx, PipeHub or a real QMT terminal, and it never sends real orders.
"""

from __future__ import print_function

import gc
import json
import platform
import statistics
import sys
import time

from cfquant import cftrader, xtconstant
from cfquant.protocol import decode_value, loads_message, pack_request, pack_response
from cfquant.tx_trade_bridge import TxTradeBridge
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount


ORDER_COUNT = 100
REPETITIONS = 30
WARMUPS = 5

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_orders(count=ORDER_COUNT):
    return [
        dict(
            stock_code="600000.SH",
            order_type=xtconstant.STOCK_BUY,
            order_volume=100,
            price_type=xtconstant.FIX_PRICE,
            price=10.0,
            strategy_name="cfquant_bench",
            order_remark="cfquant_bench_%03d" % index,
        )
        for index in range(count)
    ]


class FakeClient(object):
    def __init__(self, trader, bridge):
        self.trader = trader
        self.bridge = bridge
        self.handlers = {}
        self.request_count = 0

    def add_callback(self, event, handler):
        self.handlers[event] = handler

    def request(self, action, params, timeout=None):
        self.request_count += 1
        message = loads_message(pack_request(action, params, client_id=self.trader.client_id))
        result = self.bridge._dispatch(action, message["params"], message)
        response = loads_message(pack_response(message["id"], result=result))
        return decode_value(response["result"])

    def start(self):
        pass

    def close(self):
        pass


class BenchEnvironment(object):
    def __init__(self):
        self.account = StockAccount("TEST_ONLY", "STOCK")
        self.account.bridge_id = "bench_bridge"
        self.native_calls = []
        self.callback_count = 0
        self.bridge = TxTradeBridge(
            None,
            show=False,
            globals_dict={"passorder": self.passorder},
        )
        self.bridge.order_meta_enabled = False
        callback = XtQuantTraderCallback()
        callback.on_order_stock_async_response = self.on_async_response
        self.trader = XtQuantTrader(callback=callback, account=self.account)
        self.client = FakeClient(self.trader, self.bridge)
        self.trader._get_client = lambda bridge_id=None: self.client
        self.bridge._send_trader_event = self.push_event
        self.api = cftrader.CfQuantTrader(self.trader)

    def passorder(self, *args):
        self.native_calls.append(args)
        return 100000 + len(self.native_calls)

    def on_async_response(self, response):
        self.callback_count += 1

    def push_event(self, client_id, name, data):
        handler = self.client.handlers.get("trader:" + name)
        if handler is not None:
            handler(data)

    def close(self):
        self.bridge.close()
        self.trader.stop()


def run_batch_sync(env, orders):
    return env.api.order_stock_batch(env.account, orders, strategy_name="cfquant_bench")


def run_sync_loop(env, orders):
    return [
        env.api.order_stock(
            env.account,
            row["stock_code"],
            row["order_type"],
            row["order_volume"],
            row["price_type"],
            row["price"],
            row["strategy_name"],
            row["order_remark"],
        )
        for row in orders
    ]


def run_batch_async(env, orders):
    return env.api.order_stock_batch_async(env.account, orders, strategy_name="cfquant_bench")


def run_async_loop(env, orders):
    return [
        env.api.order_stock_async(
            env.account,
            row["stock_code"],
            row["order_type"],
            row["order_volume"],
            row["price_type"],
            row["price"],
            row["strategy_name"],
            row["order_remark"],
        )
        for row in orders
    ]


def summarize(samples):
    samples = sorted(samples)
    return {
        "min_ms": round(samples[0], 3),
        "median_ms": round(statistics.median(samples), 3),
        "mean_ms": round(statistics.mean(samples), 3),
        "max_ms": round(samples[-1], 3),
    }


def measure(label, function):
    samples = []
    last = None
    for index in range(WARMUPS + REPETITIONS):
        env = BenchEnvironment()
        orders = make_orders()
        try:
            if index == WARMUPS:
                gc.collect()
            start = time.perf_counter()
            result = function(env, orders)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if index >= WARMUPS:
                samples.append(elapsed_ms)
                last = {
                    "native_calls": len(env.native_calls),
                    "rpc_requests": env.client.request_count,
                    "callbacks": env.callback_count,
                    "result_type": type(result).__name__,
                }
        finally:
            env.close()
    row = summarize(samples)
    row.update(last or {})
    row["label"] = label
    return row


def main():
    cases = [
        ("批量同步 order_stock_batch", run_batch_sync),
        ("单笔同步循环 order_stock x100", run_sync_loop),
        ("批量异步 order_stock_batch_async", run_batch_async),
        ("单笔异步循环 order_stock_async x100", run_async_loop),
    ]
    results = [measure(label, function) for label, function in cases]
    payload = {
        "orders": ORDER_COUNT,
        "warmups": WARMUPS,
        "repetitions": REPETITIONS,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print()
    print("| 路径 | RPC 次数 | QMT 本地下单次数 | 异步回调数 | 中位耗时 | 平均耗时 | 最小-最大 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in results:
        print(
            "| {label} | {rpc_requests} | {native_calls} | {callbacks} | {median_ms:.3f} ms | "
            "{mean_ms:.3f} ms | {min_ms:.3f}-{max_ms:.3f} ms |".format(**row)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
