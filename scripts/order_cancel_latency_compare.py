# -*- coding: utf-8 -*-
import argparse
import csv
import json
import os
import sys
import time


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from cfquant.channels import channels_for_bridge, normalize_bridge_id
from cfquant.pipe_client import PipeRpcClient
from compare_three_transports_latency import RawLttxRpcClient, LTTX_HOST, LTTX_PORT


ACCOUNT_TYPE_STOCK = 2
STOCK_BUY = 23
STOCK_SELL = 24
FIX_PRICE = 11
CONFIRM_PREFIX = "SEND_REAL_ORDER"


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_stamp():
    return "%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), os.getpid())


def elapsed_ms(started):
    return round((time.perf_counter() - started) * 1000.0, 3)


def account_payload(account_id):
    return {"account_id": str(account_id), "account_type": ACCOUNT_TYPE_STOCK}


def make_order_params(args, order_remark):
    order_type = STOCK_BUY if args.side == "buy" else STOCK_SELL
    return {
        "account": account_payload(args.account_id),
        "stock_code": args.stock_code,
        "order_type": order_type,
        "order_volume": int(args.volume),
        "price_type": FIX_PRICE,
        "price": float(args.price),
        "strategy_name": args.strategy_name,
        "order_remark": order_remark,
        "quick_trade": int(args.quick_trade),
        "find_order_wait": float(args.find_order_wait),
    }


def request_timed(client, action, params, timeout):
    started = time.perf_counter()
    try:
        result = client.request(action, params, timeout=timeout)
        return {
            "ok": True,
            "latency_ms": elapsed_ms(started),
            "result": result,
            "error_type": "",
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "latency_ms": elapsed_ms(started),
            "result": None,
            "error_type": type(e).__name__,
            "error": str(e),
        }


def is_usable_order_id(value):
    return value not in (None, "", 0, "0", -1, "-1")


def extract_order_id(order_result):
    if isinstance(order_result, dict):
        for key in ("m_strOrderSysID", "m_nOrderID", "order_id", "m_strOrderID"):
            value = order_result.get(key)
            if is_usable_order_id(value):
                return value
        value = order_result.get("request_result")
        if is_usable_order_id(value):
            return value
    elif is_usable_order_id(order_result):
        return order_result
    return None


def pick_value(row, *names):
    if not isinstance(row, dict):
        return None
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


ORDER_STATUS_MAP = {
    "48": "未报",
    "49": "待报",
    "50": "已报",
    "51": "已报待撤",
    "52": "部成待撤",
    "53": "部撤",
    "54": "已撤",
    "55": "部成",
    "56": "已成",
    "57": "废单",
}


def normalize_status(value):
    if value is None:
        return ""
    return str(value)


def status_label(value):
    value = normalize_status(value)
    if not value:
        return ""
    return ORDER_STATUS_MAP.get(value, value)


def is_cancel_done_status(value):
    return normalize_status(value) in ("53", "54")


def find_order_by_remark(client, args, order_remark):
    started = time.perf_counter()
    deadline = started + max(float(args.find_order_wait), 0.0)
    last_call = None
    last_error = ""
    while True:
        call = request_timed(
            client,
            "xttrader.query_stock_orders",
            {"account": account_payload(args.account_id), "strategy_name": args.strategy_name},
            args.timeout,
        )
        last_call = call
        if call["ok"]:
            orders = call["result"] if isinstance(call["result"], list) else []
            for order in orders:
                remark = pick_value(order, "m_strRemark", "order_remark", "remark")
                if remark != order_remark:
                    continue
                order_id = extract_order_id(order)
                return {
                    "ok": order_id is not None,
                    "latency_ms": elapsed_ms(started),
                    "query_latency_ms": call["latency_ms"],
                    "order_id": order_id,
                    "order": order,
                    "orders_count": len(orders),
                    "error": "" if order_id is not None else "matched order has no usable order id",
                }
        else:
            last_error = call["error"]
        if time.perf_counter() >= deadline:
            break
        time.sleep(0.05)
    return {
        "ok": False,
        "latency_ms": elapsed_ms(started),
        "query_latency_ms": last_call["latency_ms"] if last_call else None,
        "order_id": None,
        "order": None,
        "orders_count": "",
        "error": last_error or "order not found by remark: %s" % order_remark,
    }


def brief_result(value, max_chars=600):
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...(truncated)"


def read_pipe_hub_status():
    path = os.path.join(ROOT_DIR, "cfquant_pipe_hub_status.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def build_routes(args):
    bridge_id = normalize_bridge_id(args.bridge_id)
    channels = channels_for_bridge(bridge_id)
    selected = set(item.strip().lower() for item in args.routes.split(",") if item.strip())
    if "all" in selected:
        selected = {"normal", "fast", "ctypes"}
    route_defs = [
        {
            "key": "normal",
            "name": "普通QMT",
            "channel": channels["normal"],
            "transport": "LTtx",
            "client": RawLttxRpcClient(channels["normal"], timeout=args.timeout),
        },
        {
            "key": "fast",
            "name": "极速交易端",
            "channel": channels["trade"],
            "transport": "LTtx",
            "client": RawLttxRpcClient(channels["trade"], timeout=args.timeout),
        },
        {
            "key": "ctypes",
            "name": "ctypes交易通道",
            "channel": channels["trade"],
            "transport": "NamedPipe",
            "client": PipeRpcClient(
                pipe_name=args.pipe_name,
                request_channel=channels["trade"],
                timeout=args.timeout,
            ),
        },
    ]
    return [item for item in route_defs if item["key"] in selected], channels


def preflight_route(route, args):
    client = route["client"]
    checks = []
    checks.append({
        "action": "cfquant.status",
        **request_timed(client, "cfquant.status", {}, args.timeout),
    })
    checks.append({
        "action": "xtdata.get_full_tick",
        **request_timed(client, "xtdata.get_full_tick", {"code_list": [args.stock_code]}, args.timeout),
    })
    checks.append({
        "action": "xttrader.query_stock_orders",
        **request_timed(
            client,
            "xttrader.query_stock_orders",
            {"account": account_payload(args.account_id)},
            args.timeout,
        ),
    })
    return checks


def run_real_route(route, args, route_index):
    client = route["client"]
    route_started = time.perf_counter()
    order_remark = "oclat_%s_%s_%s" % (args.stock_code.replace(".", ""), route["key"], int(time.time() * 1000))
    order_params = make_order_params(args, order_remark)
    row = {
        "route": route["name"],
        "route_key": route["key"],
        "transport": route["transport"],
        "channel": route["channel"],
        "stock_code": args.stock_code,
        "side": args.side,
        "price": args.price,
        "volume": args.volume,
        "cancel_delay_s": args.cancel_delay,
        "order_remark": order_remark,
        "order_ok": False,
        "order_latency_ms": None,
        "order_id": "",
        "order_lookup_ok": False,
        "order_lookup_latency_ms": None,
        "order_lookup_query_ms": None,
        "order_lookup_orders_count": "",
        "real_order_id": "",
        "real_order_status": "",
        "real_order_status_label": "",
        "real_traded_volume": "",
        "order_result": "",
        "cancel_ok": False,
        "cancel_latency_ms": None,
        "cancel_result": "",
        "after_cancel_lookup_ok": False,
        "after_cancel_lookup_latency_ms": None,
        "after_cancel_status": "",
        "after_cancel_status_label": "",
        "after_cancel_traded_volume": "",
        "cancel_confirmed": False,
        "wait_actual_ms": None,
        "query_after_cancel_ok": False,
        "query_after_cancel_latency_ms": None,
        "query_after_cancel_size": "",
        "total_elapsed_ms": None,
        "error": "",
    }

    order_call = request_timed(client, "xttrader.order_stock", order_params, args.timeout)
    row["order_ok"] = order_call["ok"]
    row["order_latency_ms"] = order_call["latency_ms"]
    row["order_result"] = brief_result(order_call["result"] if order_call["ok"] else order_call["error"])
    order_id = extract_order_id(order_call["result"])
    if order_id is not None:
        row["order_id"] = str(order_id)
    if not order_call["ok"]:
        row["error"] = order_call["error"]
        row["total_elapsed_ms"] = elapsed_ms(route_started)
        return row
    lookup = find_order_by_remark(client, args, order_remark)
    row["order_lookup_ok"] = lookup["ok"]
    row["order_lookup_latency_ms"] = lookup["latency_ms"]
    row["order_lookup_query_ms"] = lookup["query_latency_ms"]
    row["order_lookup_orders_count"] = lookup["orders_count"]
    if lookup.get("order"):
        row["real_order_status"] = pick_value(lookup["order"], "order_status", "m_nOrderStatus", "m_strOrderStatus", "m_strStatus")
        row["real_order_status_label"] = status_label(row["real_order_status"])
        row["real_traded_volume"] = pick_value(lookup["order"], "traded_volume", "m_nVolumeTraded")
    if lookup["order_id"] is not None:
        row["real_order_id"] = str(lookup["order_id"])
        order_id = lookup["order_id"]
    if order_id is None:
        row["error"] = "委托返回中没有可用于撤单的 order_id"
        row["total_elapsed_ms"] = elapsed_ms(route_started)
        return row

    wait_started = time.perf_counter()
    time.sleep(float(args.cancel_delay))
    row["wait_actual_ms"] = elapsed_ms(wait_started)

    cancel_params = {
        "account": account_payload(args.account_id),
        "order_id": str(order_id),
    }
    cancel_call = request_timed(client, "xttrader.cancel_order_stock", cancel_params, args.timeout)
    row["cancel_ok"] = cancel_call["ok"]
    row["cancel_latency_ms"] = cancel_call["latency_ms"]
    row["cancel_result"] = brief_result(cancel_call["result"] if cancel_call["ok"] else cancel_call["error"])
    if not cancel_call["ok"]:
        row["error"] = cancel_call["error"]

    after_cancel = find_order_by_remark(client, args, order_remark)
    row["after_cancel_lookup_ok"] = after_cancel["ok"]
    row["after_cancel_lookup_latency_ms"] = after_cancel["latency_ms"]
    if after_cancel.get("order"):
        row["after_cancel_status"] = pick_value(after_cancel["order"], "order_status", "m_nOrderStatus", "m_strOrderStatus", "m_strStatus")
        row["after_cancel_status_label"] = status_label(row["after_cancel_status"])
        row["after_cancel_traded_volume"] = pick_value(after_cancel["order"], "traded_volume", "m_nVolumeTraded")
        row["cancel_confirmed"] = is_cancel_done_status(row["after_cancel_status"])
    elif not row["error"]:
        row["error"] = after_cancel["error"]

    query_call = request_timed(
        client,
        "xttrader.query_stock_orders",
        {"account": account_payload(args.account_id), "strategy_name": args.strategy_name},
        args.timeout,
    )
    row["query_after_cancel_ok"] = query_call["ok"]
    row["query_after_cancel_latency_ms"] = query_call["latency_ms"]
    if isinstance(query_call["result"], (list, tuple, dict)):
        row["query_after_cancel_size"] = len(query_call["result"])
    elif not query_call["ok"] and not row["error"]:
        row["error"] = query_call["error"]

    row["total_elapsed_ms"] = elapsed_ms(route_started)
    return row


def write_csv(path, rows):
    fields = [
        "route",
        "route_key",
        "transport",
        "channel",
        "stock_code",
        "side",
        "price",
        "volume",
        "cancel_delay_s",
        "order_remark",
        "order_ok",
        "order_latency_ms",
        "order_id",
        "order_lookup_ok",
        "order_lookup_latency_ms",
        "order_lookup_query_ms",
        "order_lookup_orders_count",
        "real_order_id",
        "real_order_status",
        "real_order_status_label",
        "real_traded_volume",
        "cancel_ok",
        "cancel_latency_ms",
        "after_cancel_lookup_ok",
        "after_cancel_lookup_latency_ms",
        "after_cancel_status",
        "after_cancel_status_label",
        "after_cancel_traded_volume",
        "cancel_confirmed",
        "wait_actual_ms",
        "query_after_cancel_ok",
        "query_after_cancel_latency_ms",
        "query_after_cancel_size",
        "total_elapsed_ms",
        "error",
        "order_result",
        "cancel_result",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def write_markdown(path, payload):
    args = payload["args"]
    mode_text = "真实下单测试" if payload["real_order"] else "预检模式（未真实下单）"
    lines = [
        "# 下单撤单延迟对比",
        "",
        "- 测试时间：`%s`" % payload["finished_at_text"],
        "- 模式：`%s`" % mode_text,
        "- 标的：`%s`" % args["stock_code"],
        "- 方向：`%s`" % ("买入" if args["side"] == "buy" else "卖出"),
        "- 价格：`%s`" % args["price"],
        "- 数量：`%s`" % args["volume"],
        "- 下单后撤单等待：`%s 秒`" % args["cancel_delay"],
        "- 账号：`%s`" % args["account_id"],
        "- LTtx：`%s:%s`" % (LTTX_HOST, LTTX_PORT),
        "- Pipe：`%s`" % args["pipe_name"],
        "",
        "## 路径说明",
        "",
        "| 路径 | 传输 | 请求通道 |",
        "|---|---|---|",
    ]
    for route in payload["routes"]:
        lines.append("| `%s` | `%s` | `%s` |" % (route["name"], route["transport"], route["channel"]))

    lines.extend([
        "",
        "## Pipe Hub 状态",
        "",
        "```json",
        json.dumps(payload["pipe_hub_status"], ensure_ascii=False, indent=2),
        "```",
        "",
    ])

    if not payload["real_order"]:
        lines.extend([
            "## 预检结果",
            "",
            "| 路径 | 动作 | 成功 | 用时 ms | 结果类型/数量 | 错误 |",
            "|---|---|---:|---:|---|---|",
        ])
        for item in payload["preflight"]:
            result = item.get("result")
            if isinstance(result, (list, tuple, dict)):
                result_note = "%s/%s" % (type(result).__name__, len(result))
            else:
                result_note = type(result).__name__ if result is not None else ""
            lines.append(
                "| `%s` | `%s` | %s | %s | %s | %s |"
                % (
                    item["route"],
                    item["action"],
                    "是" if item["ok"] else "否",
                    item["latency_ms"],
                    result_note,
                    item.get("error") or "",
                )
            )
        lines.extend([
            "",
            "本次未发送真实委托。需要真实测试时，在交易终端确认账号和风险后，由人工运行带确认短语的命令。",
        ])
    else:
        lines.extend([
            "## 真实下单撤单结果",
            "",
            "| 路径 | 下单成功 | 下单 ms | 原始order_id | 真实委托号 | 定位委托 ms | 下单后状态 | 等待 ms | 撤单请求成功 | 撤单请求 ms | 撤单后状态 | 撤单确认 | 总耗时 ms | 错误 |",
            "|---|---:|---:|---|---|---:|---|---:|---:|---:|---|---:|---:|---|",
        ])
        for row in payload["rows"]:
            lines.append(
                "| `%s` | %s | %s | `%s` | `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                % (
                    row["route"],
                    "是" if row["order_ok"] else "否",
                    row["order_latency_ms"],
                    row["order_id"],
                    row.get("real_order_id") or "",
                    row.get("order_lookup_latency_ms") if row.get("order_lookup_latency_ms") is not None else "",
                    row.get("real_order_status_label") or row.get("real_order_status") or "",
                    row["wait_actual_ms"] if row["wait_actual_ms"] is not None else "",
                    "是" if row["cancel_ok"] else "否",
                    row["cancel_latency_ms"] if row["cancel_latency_ms"] is not None else "",
                    row.get("after_cancel_status_label") or row.get("after_cancel_status") or "",
                    "是" if row.get("cancel_confirmed") else "否",
                    row["total_elapsed_ms"],
                    row.get("error") or "",
                )
            )

    lines.extend([
        "",
        "## 文件",
        "",
        "- JSON：`%s`" % os.path.basename(payload["json_path"]),
        "- CSV：`%s`" % os.path.basename(payload["csv_path"]),
        "",
    ])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def parse_args():
    parser = argparse.ArgumentParser(description="Compare order/cancel latency across normal QMT, fast trade endpoint and ctypes pipe.")
    parser.add_argument("--bridge-id", default="default")
    parser.add_argument("--routes", default="all", help="Comma-separated: normal,fast,ctypes,all")
    parser.add_argument("--stock-code", default="000001.SZ")
    parser.add_argument("--side", choices=("buy", "sell"), default="buy")
    parser.add_argument("--price", type=float, default=11.1)
    parser.add_argument("--volume", type=int, default=100)
    parser.add_argument("--cancel-delay", type=float, default=3.0)
    parser.add_argument("--account-id", default="8885060548")
    parser.add_argument("--strategy-name", default="cfquant_latency")
    parser.add_argument("--quick-trade", type=int, default=2)
    parser.add_argument("--find-order-wait", type=float, default=0.3)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--out-dir", default=os.path.join(ROOT_DIR, "reports", "latency"))
    parser.add_argument("--pipe-name", default=r"\\.\pipe\cfquant_pipe_hub")
    parser.add_argument("--real-order", action="store_true", help="Actually send order and cancel it after --cancel-delay seconds.")
    parser.add_argument("--confirm", default="", help="Required with --real-order. Exact value is printed in dry-run output.")
    return parser.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    routes, channels = build_routes(args)
    if not routes:
        raise SystemExit("没有匹配的测试路径，请检查 --routes")

    expected_confirm = "%s_%s_%s_%s_%s" % (
        CONFIRM_PREFIX,
        args.stock_code,
        args.side.upper(),
        args.volume,
        args.price,
    )
    real_order = bool(args.real_order)
    if real_order and args.confirm != expected_confirm:
        raise SystemExit(
            "真实下单已被阻止。若确认要人工发起真实委托，请追加：--confirm %s" % expected_confirm
        )

    stamp = now_stamp()
    prefix = "order_cancel_latency_%s_%s_%s" % (
        "real" if real_order else "dryrun",
        normalize_bridge_id(args.bridge_id),
        stamp,
    )
    json_path = os.path.join(args.out_dir, prefix + ".json")
    csv_path = os.path.join(args.out_dir, prefix + ".csv")
    md_path = os.path.join(args.out_dir, prefix + ".md")

    preflight = []
    rows = []
    clients = []
    try:
        for route in routes:
            clients.append(route["client"])
            print("预检 %s ..." % route["name"], flush=True)
            for check in preflight_route(route, args):
                check["route"] = route["name"]
                check["route_key"] = route["key"]
                preflight.append(check)
                print(
                    "%s %s %s %.3f ms"
                    % (route["name"], check["action"], "OK" if check["ok"] else "ERR", check["latency_ms"]),
                    flush=True,
                )
            if not real_order:
                continue
            print("真实委托 %s：%s %s %s股 @ %s，%s秒后撤单" % (
                route["name"],
                "买入" if args.side == "buy" else "卖出",
                args.stock_code,
                args.volume,
                args.price,
                args.cancel_delay,
            ), flush=True)
            row = run_real_route(route, args, len(rows) + 1)
            rows.append(row)
            print(
                "%s 下单 %s %.3f ms，真实委托号 %s，撤单 %s %s ms，撤单确认 %s，总耗时 %.3f ms"
                % (
                    route["name"],
                    "OK" if row["order_ok"] else "ERR",
                    row["order_latency_ms"] or 0.0,
                    row.get("real_order_id") or row.get("order_id") or "",
                    "OK" if row["cancel_ok"] else "ERR",
                    row["cancel_latency_ms"] if row["cancel_latency_ms"] is not None else "",
                    "OK" if row.get("cancel_confirmed") else "NO",
                    row["total_elapsed_ms"] or 0.0,
                ),
                flush=True,
            )
            time.sleep(0.5)
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass

    payload = {
        "real_order": real_order,
        "args": vars(args),
        "channels": channels,
        "routes": [{k: v for k, v in route.items() if k != "client"} for route in routes],
        "expected_confirm": expected_confirm,
        "pipe_hub_status": read_pipe_hub_status(),
        "preflight": preflight,
        "rows": rows,
        "finished_at": time.time(),
        "finished_at_text": now_text(),
        "json_path": json_path,
        "csv_path": csv_path,
        "md_path": md_path,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    write_csv(csv_path, rows)
    write_markdown(md_path, payload)

    print("结果已保存：%s" % md_path, flush=True)
    if not real_order:
        print("本次是预检模式，没有真实下单。真实测试确认短语：%s" % expected_confirm, flush=True)


if __name__ == "__main__":
    main()
