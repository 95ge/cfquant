# -*- coding: utf-8 -*-
import argparse
import os
import statistics
import sys
import time


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from cfquant import configure, xtdata
from cfquant.channels import channels_for_bridge, normalize_bridge_id
from cfquant.client import get_client
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount


def _stats(values):
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "count": len(values),
        "min_ms": min(values),
        "avg_ms": statistics.mean(values),
        "p50_ms": ordered[int((len(ordered) - 1) * 0.50)],
        "p95_ms": ordered[int((len(ordered) - 1) * 0.95)],
        "max_ms": max(values),
    }


def _print_stats(name, values):
    stats = _stats(values)
    if not stats:
        print("%s: no samples" % name)
        return
    print(
        "%s: count=%s min=%.3f avg=%.3f p50=%.3f p95=%.3f max=%.3f ms"
        % (
            name,
            stats["count"],
            stats["min_ms"],
            stats["avg_ms"],
            stats["p50_ms"],
            stats["p95_ms"],
            stats["max_ms"],
        )
    )


def _bench(name, count, func):
    values = []
    for _ in range(count):
        start = time.perf_counter()
        func()
        values.append((time.perf_counter() - start) * 1000.0)
    _print_stats(name, values)


def main():
    parser = argparse.ArgumentParser(description="Benchmark cfquant ctypes/named-pipe transport latency.")
    parser.add_argument("--pipe-name", default=None)
    parser.add_argument("--bridge-id", default="default")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--stock-code", default="000001.SZ")
    parser.add_argument("--account-id", default="")
    parser.add_argument("--trade", action="store_true", help="Also test trade channel queries.")
    parser.add_argument("--order-test", action="store_true", help="Send a real order_stock request. Use with care.")
    parser.add_argument("--order-volume", type=int, default=100)
    parser.add_argument("--order-price", type=float, default=0.0)
    parser.add_argument("--order-type", type=int, default=23)
    parser.add_argument("--price-type", type=int, default=5)
    args = parser.parse_args()

    bridge_id = normalize_bridge_id(args.bridge_id)
    channels = channels_for_bridge(bridge_id)
    configure(
        transport="pipe",
        pipe_name=args.pipe_name,
        bridge_id=bridge_id,
        request_channel=channels["normal"],
        timeout=15,
    )

    client = get_client()
    _bench("normal cfquant.ping", args.count, lambda: client.request("cfquant.ping"))
    _bench("xtdata.get_full_tick", args.count, lambda: xtdata.get_full_tick([args.stock_code]))

    if args.trade or args.order_test:
        if not args.account_id:
            raise SystemExit("--account-id is required for trade tests")
        account = StockAccount(args.account_id, bridge_id=bridge_id)
        trader = XtQuantTrader("", 0, account=account)
        trader.start()
        _bench("trade query_stock_asset", args.count, lambda: trader.query_stock_asset(account))
        if args.order_test:
            remark = "cfpipe_latency_%s" % int(time.time() * 1000)

            def send_order():
                return trader.order_stock(
                    account,
                    args.stock_code,
                    args.order_type,
                    args.order_volume,
                    args.price_type,
                    args.order_price,
                    "cfpipe_latency",
                    remark,
                )

            _bench("trade order_stock REAL", 1, send_order)


if __name__ == "__main__":
    main()
