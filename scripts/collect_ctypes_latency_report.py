# -*- coding: utf-8 -*-
import argparse
import csv
import json
import os
import statistics
import sys
import time


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from cfquant import configure, xtdata
from cfquant.channels import channels_for_bridge, normalize_bridge_id
from cfquant.pipe_client import PipeRpcClient
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount


def now_stamp():
    return time.strftime("%Y%m%d_%H%M%S")


def stats(values):
    if not values:
        return {
            "count": 0,
            "ok_count": 0,
            "error_count": 0,
            "min_ms": None,
            "avg_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
        }
    ordered = sorted(values)
    return {
        "count": len(values),
        "ok_count": len(values),
        "error_count": 0,
        "min_ms": min(values),
        "avg_ms": statistics.mean(values),
        "p50_ms": ordered[int((len(ordered) - 1) * 0.50)],
        "p95_ms": ordered[int((len(ordered) - 1) * 0.95)],
        "max_ms": max(values),
    }


def rounded(value):
    return None if value is None else round(float(value), 3)


def summarize(samples):
    grouped = {}
    for row in samples:
        key = row["case"]
        grouped.setdefault(key, {"ok": [], "errors": []})
        if row["ok"]:
            grouped[key]["ok"].append(row["latency_ms"])
        else:
            grouped[key]["errors"].append(row)
    result = {}
    for key, data in grouped.items():
        item = stats(data["ok"])
        item["count"] = len(data["ok"]) + len(data["errors"])
        item["ok_count"] = len(data["ok"])
        item["error_count"] = len(data["errors"])
        for stat_key in ("min_ms", "avg_ms", "p50_ms", "p95_ms", "max_ms"):
            item[stat_key] = rounded(item[stat_key])
        result[key] = item
    return result


def call_case(samples, case_name, count, func, sleep_seconds=0.02):
    for index in range(1, count + 1):
        started = time.perf_counter()
        row = {
            "case": case_name,
            "index": index,
            "ok": False,
            "latency_ms": None,
            "error_type": "",
            "error": "",
            "started_at": time.time(),
        }
        try:
            result = func()
            row["ok"] = True
            row["result_type"] = type(result).__name__
            if isinstance(result, dict):
                row["result_size"] = len(result)
                row["result_keys"] = ",".join(sorted(str(key) for key in result.keys())[:20])
            elif isinstance(result, (list, tuple)):
                row["result_size"] = len(result)
                row["result_keys"] = ""
            else:
                row["result_size"] = ""
                row["result_keys"] = ""
        except Exception as e:
            row["error_type"] = type(e).__name__
            row["error"] = str(e)
            row["result_type"] = ""
            row["result_size"] = ""
            row["result_keys"] = ""
        row["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        samples.append(row)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)


def safe_request(client, action, timeout=5):
    return client.request(action, timeout=timeout)


def read_hub_status():
    path = os.path.join(ROOT_DIR, "cfquant_pipe_hub_status.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e), "path": path}


def write_csv(path, samples):
    fields = [
        "case",
        "index",
        "ok",
        "latency_ms",
        "error_type",
        "error",
        "result_type",
        "result_size",
        "result_keys",
        "started_at",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in samples:
            writer.writerow({key: row.get(key, "") for key in fields})


def write_markdown(path, payload):
    lines = []
    lines.append("# ctypes Pipe 延迟测试报告")
    lines.append("")
    lines.append("- 测试时间：`%s`" % payload["finished_at_text"])
    lines.append("- 桥接 ID：`%s`" % payload["bridge_id"])
    lines.append("- 股票代码：`%s`" % payload["stock_code"])
    lines.append("- 账号：`%s`" % (payload["account_id"] or "-"))
    lines.append("- 单项样本数：`%s`" % payload["count"])
    lines.append("")
    lines.append("## Hub 状态")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload["hub_status"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 测试项 | 样本 | 成功 | 失败 | min ms | avg ms | p50 ms | p95 ms | max ms |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for case_name, item in payload["summary"].items():
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                case_name,
                item["count"],
                item["ok_count"],
                item["error_count"],
                item["min_ms"],
                item["avg_ms"],
                item["p50_ms"],
                item["p95_ms"],
                item["max_ms"],
            )
        )
    lines.append("")
    lines.append("## 文件")
    lines.append("")
    lines.append("- JSON：`%s`" % os.path.basename(payload["json_path"]))
    lines.append("- CSV：`%s`" % os.path.basename(payload["csv_path"]))
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Collect ctypes Pipe latency report.")
    parser.add_argument("--bridge-id", default="default")
    parser.add_argument("--pipe-name", default=None)
    parser.add_argument("--stock-code", default="603881.SH")
    parser.add_argument("--account-id", default="")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--out-dir", default=os.path.join(ROOT_DIR, "reports", "latency"))
    parser.add_argument("--skip-normal", action="store_true")
    parser.add_argument("--skip-trade", action="store_true")
    parser.add_argument("--skip-trade-queries", action="store_true")
    args = parser.parse_args()

    bridge_id = normalize_bridge_id(args.bridge_id)
    channels = channels_for_bridge(bridge_id)
    configure(
        transport="pipe",
        pipe_name=args.pipe_name,
        bridge_id=bridge_id,
        request_channel=channels["normal"],
        timeout=args.timeout,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = now_stamp()
    prefix = "ctypes_pipe_%s_%s" % (bridge_id, stamp)
    json_path = os.path.join(args.out_dir, prefix + ".json")
    csv_path = os.path.join(args.out_dir, prefix + ".csv")
    md_path = os.path.join(args.out_dir, prefix + ".md")

    samples = []
    normal_client = PipeRpcClient(
        pipe_name=args.pipe_name,
        request_channel=channels["normal"],
        timeout=args.timeout,
    )
    trade_client = PipeRpcClient(
        pipe_name=args.pipe_name,
        request_channel=channels["trade"],
        timeout=args.timeout,
    )

    if not args.skip_normal:
        call_case(samples, "normal.cfquant.ping", args.count, lambda: safe_request(normal_client, "cfquant.ping", args.timeout))
        call_case(samples, "normal.cfquant.status", min(args.count, 10), lambda: safe_request(normal_client, "cfquant.status", args.timeout))
        call_case(samples, "normal.xtdata.get_full_tick", args.count, lambda: xtdata.get_full_tick([args.stock_code]))

    if not args.skip_trade:
        call_case(samples, "trade.cfquant.ping", args.count, lambda: safe_request(trade_client, "cfquant.ping", args.timeout))
        call_case(samples, "trade.cfquant.status", min(args.count, 10), lambda: safe_request(trade_client, "cfquant.status", args.timeout))
        if args.account_id and not args.skip_trade_queries:
            account = StockAccount(args.account_id, bridge_id=bridge_id)
            trader = XtQuantTrader("", 0, account=account)
            trader.start()
            call_case(samples, "trade.query_stock_asset", args.count, lambda: trader.query_stock_asset(account))
            call_case(samples, "trade.query_stock_positions", args.count, lambda: trader.query_stock_positions(account))
            call_case(samples, "trade.query_stock_orders", args.count, lambda: trader.query_stock_orders(account))
            call_case(samples, "trade.query_stock_trades", args.count, lambda: trader.query_stock_trades(account))

    try:
        normal_client.close()
    except Exception:
        pass
    try:
        trade_client.close()
    except Exception:
        pass

    payload = {
        "bridge_id": bridge_id,
        "stock_code": args.stock_code,
        "account_id": args.account_id,
        "count": args.count,
        "timeout": args.timeout,
        "channels": channels,
        "hub_status": read_hub_status(),
        "started_at_text": stamp,
        "finished_at": time.time(),
        "finished_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summarize(samples),
        "samples": samples,
        "json_path": json_path,
        "csv_path": csv_path,
        "md_path": md_path,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    write_csv(csv_path, samples)
    write_markdown(md_path, payload)

    print("saved json: %s" % json_path)
    print("saved csv : %s" % csv_path)
    print("saved md  : %s" % md_path)
    for case_name, item in payload["summary"].items():
        print(
            "%s count=%s ok=%s err=%s avg=%s p50=%s p95=%s max=%s ms"
            % (
                case_name,
                item["count"],
                item["ok_count"],
                item["error_count"],
                item["avg_ms"],
                item["p50_ms"],
                item["p95_ms"],
                item["max_ms"],
            )
        )


if __name__ == "__main__":
    main()
