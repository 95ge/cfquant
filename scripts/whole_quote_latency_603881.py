# -*- coding: utf-8 -*-
import argparse
import json
import os
import sys
import time
from datetime import datetime


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from cfquant import configure, xtdata


def fmt_ts_ms(ts_ms):
    try:
        ts_ms = int(ts_ms)
    except Exception:
        return "-"
    if ts_ms <= 0:
        return "-"
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def quote_time_ms(quote):
    value = quote.get("time")
    try:
        value = int(value)
    except Exception:
        return None
    if value < 10**12:
        value *= 1000
    return value


def brief_quote(quote):
    fields = [
        "time",
        "timetag",
        "stime",
        "lastPrice",
        "open",
        "high",
        "low",
        "lastClose",
        "amount",
        "volume",
        "pvolume",
        "askPrice",
        "bidPrice",
        "askVol",
        "bidVol",
    ]
    return {key: quote.get(key) for key in fields if key in quote}


def main():
    parser = argparse.ArgumentParser(description="Subscribe whole quote and print latency for one symbol.")
    parser.add_argument("--symbol", default="603881.SH", help="Symbol to display, default: 603881.SH")
    parser.add_argument("--bridge-id", default="default")
    parser.add_argument("--transport", default="pipe", choices=["pipe", "lttx"])
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--raw", action="store_true", help="Print the full quote dict for the symbol.")
    parser.add_argument("--miss-log-interval", type=int, default=200, help="Print one miss summary every N callbacks; 0 disables.")
    args = parser.parse_args()

    configure(
        transport=args.transport,
        bridge_id=args.bridge_id,
        timeout=args.timeout,
    )

    state = {
        "callbacks": 0,
        "hits": 0,
        "last_recv_ms": None,
    }

    def on_quote(data):
        recv_ms = int(time.time() * 1000)
        state["callbacks"] += 1
        callback_index = state["callbacks"]
        interval_ms = None
        if state["last_recv_ms"] is not None:
            interval_ms = recv_ms - state["last_recv_ms"]
        state["last_recv_ms"] = recv_ms

        if not isinstance(data, dict):
            print("[%s] callback=%s non-dict data=%r" % (fmt_ts_ms(recv_ms), callback_index, data), flush=True)
            return

        quote = data.get(args.symbol)
        if quote is None:
            if args.miss_log_interval and callback_index % args.miss_log_interval == 0:
                print(
                    "[%s] callback=%s miss symbol=%s batch_size=%s interval_ms=%s"
                    % (fmt_ts_ms(recv_ms), callback_index, args.symbol, len(data), interval_ms),
                    flush=True,
                )
            return

        state["hits"] += 1
        q_ms = quote_time_ms(quote)
        delay_ms = recv_ms - q_ms if q_ms is not None else None
        payload = quote if args.raw else brief_quote(quote)
        print(
            "[%s] hit=%s callback=%s symbol=%s quote_time=%s delay_ms=%s interval_ms=%s batch_size=%s"
            % (
                fmt_ts_ms(recv_ms),
                state["hits"],
                callback_index,
                args.symbol,
                fmt_ts_ms(q_ms) if q_ms else "-",
                delay_ms if delay_ms is not None else "-",
                interval_ms if interval_ms is not None else "-",
                len(data),
            ),
            flush=True,
        )
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)

    print(
        "subscribe_whole_quote start transport=%s bridge_id=%s symbol=%s"
        % (args.transport, args.bridge_id, args.symbol),
        flush=True,
    )
    sub_id = xtdata.subscribe_whole_quote(["SH", "SZ"], callback=on_quote)
    print("subscribe_whole_quote sub_id=%s, press Ctrl+C to stop" % sub_id, flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("stopping...", flush=True)
    finally:
        try:
            xtdata.unsubscribe_quote(sub_id)
        except Exception as e:
            print("unsubscribe failed: %s" % e, flush=True)
        print(
            "done callbacks=%s hits=%s symbol=%s"
            % (state["callbacks"], state["hits"], args.symbol),
            flush=True,
        )


if __name__ == "__main__":
    main()
