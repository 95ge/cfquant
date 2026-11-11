# -*- coding: utf-8 -*-
"""Run a short live full-quote latency measurement.

The measurement is taken by ``cfquant.diagnostics`` at callback entry.  This
script only aggregates the reports and prints periodic JSON snapshots, so
console output is kept out of the quote callback path.

Example (conda base):
    python -X utf8 scripts/whole_quote_latency_test.py --seconds 30
For a direct local bridge, add --transport ctypes --bridge-id YOUR_BRIDGE_ID.
Exit codes: 0 = measured, 1 = request/report/cleanup error, 2 = no data.
"""

import argparse
import json
import math
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cfquant import __version__, configure, diagnostics, get_client, xtdata


def print_json(payload):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")), flush=True)


def parse_markets(value):
    items = [item.strip().upper() for item in str(value).split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("markets/code list cannot be empty")
    return items


class LatencyWindow:
    """Keep a bounded sample window while retaining the total observation count."""

    def __init__(self, max_samples):
        self.values = deque(maxlen=max_samples)
        self.observed = 0

    def add(self, value):
        if value is None:
            return
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        self.values.append(value)
        self.observed += 1

    def capture(self):
        return self.observed, list(self.values)

    @staticmethod
    def summarize(captured, unit="ms"):
        observed, samples = captured
        values = sorted(samples)
        if not values:
            return {"observed": observed, "window": 0}
        result = {
            "observed": observed,
            "window": len(values),
            "truncated": observed > len(values),
            "negative_samples": sum(value < 0 for value in values),
        }
        stats = {"min": values[0], "avg": sum(values) / len(values), "max": values[-1]}
        for percentile in (50, 95, 99):
            stats["p%d" % percentile] = values[max(0, (len(values) * percentile + 99) // 100 - 1)]
        result.update({key + ("_" + unit if unit else ""): round(value, 3)
                       for key, value in stats.items()})
        return result


class Measurement:
    def __init__(self, max_samples, sample_codes):
        self.lock = threading.Lock()
        self.batches = 0
        self.dropped = 0
        self.last_error = None
        self.accepting = False
        self.has_started = False
        self.deadline = None
        self.warmup_batches = 0
        self.quote_updates = 0
        self.codes = set()
        self.last = None
        self.code_counts = LatencyWindow(max_samples)
        self.quote_latency = LatencyWindow(max_samples)
        self.qmt_quote_latency = LatencyWindow(max_samples)
        self.internal_latency = LatencyWindow(max_samples)
        self.callback_latency = LatencyWindow(max_samples)
        self.qmt_prepare = LatencyWindow(max_samples)
        self.qmt_encode = LatencyWindow(max_samples)
        self.analysis = LatencyWindow(max_samples)
        self.sample_codes = max(0, sample_codes)

    def start(self, seconds):
        with self.lock:
            started = time.monotonic()
            self.deadline = started + seconds if seconds else None
            self.accepting = True
            self.has_started = True
            return started

    def stop(self):
        with self.lock:
            self.accepting = False

    def add(self, report):
        with self.lock:
            if not self.accepting:
                if not self.has_started:
                    self.warmup_batches += 1
                return
            if self.deadline is not None and time.monotonic() >= self.deadline:
                return
            self.batches += 1
            self.internal_latency.add(report.get("internal_latency_ms"))
            entered = report.get("qmt_callback_at_ms")
            received = report.get("received_at_ms")
            if entered is not None and received is not None:
                self.callback_latency.add(received - entered)
            self.qmt_prepare.add(report.get("qmt_prepare_ms"))
            self.qmt_encode.add(report.get("qmt_encode_ms"))
            self.analysis.add(report.get("analysis_ms"))
            code_count = report.get("code_count")
            self.code_counts.add(code_count)
            self.quote_updates += code_count or 0
            for row in report.get("samples") or ():
                self.codes.add(row["code"])
                self.quote_latency.add(row.get("quote_latency_ms"))
                self.qmt_quote_latency.add(row.get("qmt_quote_latency_ms"))
            samples = list(report.get("samples") or ())[: self.sample_codes]
            self.last = {
                "received_at_ms": report.get("received_at_ms"),
                "qmt_callback_at_ms": report.get("qmt_callback_at_ms"),
                "qmt_push_at_ms": report.get("qmt_push_at_ms"),
                "internal_latency_ms": report.get("internal_latency_ms"),
                "qmt_prepare_ms": report.get("qmt_prepare_ms"),
                "qmt_encode_ms": report.get("qmt_encode_ms"),
                "qmt_encoding": report.get("qmt_encoding"),
                "code_count": code_count,
                "summary": report.get("summary"),
                "samples": samples,
            }

    def snapshot(self):
        with self.lock:
            result = {
                "batches": self.batches,
                "report_errors": self.dropped,
                "last_report_error": self.last_error,
                "warmup_batches": self.warmup_batches,
                "quote_updates": self.quote_updates,
                "unique_codes": len(self.codes),
                "latest": self.last,
            }
            captured = {
                "batch_code_count": self.code_counts.capture(),
                "行情到程序_ms": self.quote_latency.capture(),
                "行情到QMT_ms": self.qmt_quote_latency.capture(),
                "cfquant内部_ms": self.internal_latency.capture(),
                "QMT回调到程序_ms": self.callback_latency.capture(),
                "QMT准备_ms": self.qmt_prepare.capture(),
                "QMT编码_ms": self.qmt_encode.capture(),
                "诊断分析_ms": self.analysis.capture(),
            }
        # Never hold the callback lock while sorting a large statistics window.
        result.update({name: LatencyWindow.summarize(values, "" if name == "batch_code_count" else "ms")
                       for name, values in captured.items()})
        return result


def build_parser():
    parser = argparse.ArgumentParser(
        description="Measure live full-quote latency from QMT/cfquant to this Python process."
    )
    parser.add_argument("--seconds", type=float, default=30.0,
                        help="Measurement duration after subscribing/warmup; 0 runs until Ctrl+C (default: 30).")
    parser.add_argument("--warmup", type=float, default=2.0,
                        help="Exclude this many seconds after subscribing (default: 2).")
    parser.add_argument("--markets", type=parse_markets, default=parse_markets("SH,SZ,BJ"),
                        help="Comma-separated markets or symbols (default: SH,SZ,BJ).")
    parser.add_argument("--transport", default=os.environ.get("CFQUANT_TRANSPORT", "auto"),
                        help="cfquant transport, such as auto, pipe, ctypes or lttx.")
    parser.add_argument("--bridge-id", default=os.environ.get("CFQUANT_BRIDGE_ID", "default"))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--print-interval", type=float, default=10.0,
                        help="Seconds between progress snapshots (default: 10).")
    parser.add_argument("--sample-codes", type=int, default=3,
                        help="Number of latest quote rows to print per batch (default: 3).")
    parser.add_argument("--max-samples", type=int, default=200000,
                        help="Most recent samples retained per metric; truncation is reported (default: 200000).")
    parser.add_argument("--output", type=Path,
                        default=ROOT_DIR / "runtime" / "reports" / ("whole_quote_latency_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"),
                        help="Final JSON report (default: timestamped file in runtime/reports).")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds < 0:
        raise SystemExit("--seconds must be >= 0")
    if not math.isfinite(args.warmup) or args.warmup < 0:
        raise SystemExit("--warmup must be >= 0")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise SystemExit("--timeout must be > 0")
    if not math.isfinite(args.print_interval) or args.print_interval <= 0:
        raise SystemExit("--print-interval must be > 0")
    if args.max_samples <= 0:
        raise SystemExit("--max-samples must be > 0")

    configure(transport=args.transport, bridge_id=args.bridge_id, timeout=args.timeout)
    measurement = Measurement(args.max_samples, args.sample_codes)
    run_started = time.monotonic()
    started = None
    measured_s = 0.0
    started_at = None
    finished_at = None
    subscribe_id = None
    stopped_by_interrupt = False
    error = None
    cleanup_errors = []
    client = None
    route = None
    callback_status = None

    def on_report(report):
        try:
            measurement.add(report)
        except Exception as exc:
            with measurement.lock:
                measurement.dropped += 1
                measurement.last_error = str(exc)

    print_json({
        "event": "start",
        "seconds": args.seconds,
        "warmup_s": args.warmup,
        "markets": args.markets,
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "说明": "行情到程序=Python回调接收时间-原行情时间；行情到QMT=QMT回调入口时间-原行情时间；cfquant内部=Python接收时间-QMT发送前时间。单位 ms。跨机器测试前请同步系统时钟。",
    })
    try:
        client = get_client()
        route = {"client_class": type(client).__name__,
                 "request_channel": getattr(client, "request_channel", None)}
        subscribe_id = diagnostics.subscribe_whole_quote(args.markets, on_report)
        print_json({"event": "subscribed", "subscribe_id": subscribe_id, "route": route})
        time.sleep(args.warmup)
        started_at = datetime.now().astimezone().isoformat()
        started = measurement.start(args.seconds)
        deadline = measurement.deadline
        while deadline is None or time.monotonic() < deadline:
            time.sleep(min(args.print_interval, max(0, deadline - time.monotonic())) if deadline else args.print_interval)
            if deadline is not None and time.monotonic() >= deadline:
                break
            snapshot = measurement.snapshot()
            snapshot.update({"event": "progress", "elapsed_s": round(time.monotonic() - started, 3)})
            print_json(snapshot)
    except KeyboardInterrupt:
        stopped_by_interrupt = True
        print_json({"event": "interrupt"})
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        print_json({"event": "error", **error})
    finally:
        measurement.stop()
        finished_at = datetime.now().astimezone().isoformat()
        if started is not None:
            measured_s = time.monotonic() - started
            if args.seconds:
                measured_s = min(args.seconds, measured_s)
        if client is not None and hasattr(client, "callback_status"):
            try:
                callback_status = client.callback_status()
            except Exception as exc:
                cleanup_errors.append("callback_status: " + str(exc))
        if subscribe_id is not None:
            try:
                xtdata.unsubscribe_quote(subscribe_id)
            except Exception as exc:
                cleanup_errors.append("unsubscribe: " + str(exc))
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                cleanup_errors.append("close: " + str(exc))

    final = measurement.snapshot()
    final.update({
        "event": "final",
        "status": "error" if error or cleanup_errors or final["report_errors"] else ("ok" if final["batches"] else "no_data"),
        "error": error,
        "cleanup_errors": cleanup_errors,
        "elapsed_s": round(measured_s, 3),
        "total_elapsed_s": round(time.monotonic() - run_started, 3),
        "started_at": started_at,
        "finished_at": finished_at,
        "warmup_s": args.warmup,
        "batches_per_second": round(final["batches"] / measured_s, 3) if measured_s else None,
        "route": route,
        "sdk_version": __version__,
        "callback_status_at_stop": callback_status,
        "stopped_by_interrupt": stopped_by_interrupt,
        "subscribe_id": subscribe_id,
        "markets": args.markets,
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "output": str(args.output.resolve()),
        "statistics_scope": "内部延迟按批次等权；行情时间差按每条证券更新等权。统计使用最近 max_samples 个有效样本，truncated=true 表示窗口已截断。P50/P95/P99 使用 nearest-rank。预热及退订期间不计入。",
        "interpretation": "cfquant内部从QMT发送前到Python诊断回调入口，含编码/传输/解码/回调排队；QMT编码是其中一部分，不应重复相加。行情时间差可能含旧快照和源时间粒度，不等于传输耗时。独立诊断订阅会增加一定负载；report_errors不是网络丢包数。",
    })
    print_json(final)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(final, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 1 if error or cleanup_errors or final["report_errors"] else (0 if final["batches"] else 2)


if __name__ == "__main__":
    raise SystemExit(main())
