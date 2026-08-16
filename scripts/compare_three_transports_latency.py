# -*- coding: utf-8 -*-
import argparse
import csv
import json
import os
import queue
import socket
import statistics
import struct
import sys
import threading
import time


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from cfquant.channels import channels_for_bridge, normalize_bridge_id
from cfquant.pipe_client import PipeRpcClient
from cfquant.protocol import decode_value, dumps_message, loads_message, new_id, pack_request


ACCOUNT_TYPE_STOCK = 2
LTTX_TOKEN = "LTtx"
LTTX_HOST = "127.0.0.1"
LTTX_PORT = 2049


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_stamp():
    return "%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), os.getpid())


def send_framed(sock, payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    sock.sendall(struct.pack("Q", len(payload)))
    sock.sendall(payload)


def recv_exact(sock, size):
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed while receiving frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_framed(sock):
    header = recv_exact(sock, 8)
    size = struct.unpack("Q", header)[0]
    raw = recv_exact(sock, size)
    return raw.decode("utf-8", errors="replace")


class RawLttxRpcClient(object):
    def __init__(self, request_channel, host=LTTX_HOST, port=LTTX_PORT, token=LTTX_TOKEN, timeout=8.0, client_id=None):
        self.request_channel = request_channel
        self.host = host
        self.port = int(port)
        self.token = token
        self.timeout = float(timeout)
        self.client_id = client_id or new_id("raw_lttx")
        self.reply_channel = self.client_id
        self.put_sock = None
        self.sub_sock = None
        self.pending = {}
        self.pending_lock = threading.RLock()
        self.running = False
        self.recv_thread = None

    def start(self):
        if self.running:
            return
        self.put_sock = self._connect_put()
        self.sub_sock = self._connect_push(self.reply_channel)
        self.running = True
        self.recv_thread = threading.Thread(target=self._recv_loop)
        self.recv_thread.daemon = True
        self.recv_thread.start()

    def close(self):
        self.running = False
        for sock in (self.put_sock, self.sub_sock):
            if sock is None:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
        self.put_sock = None
        self.sub_sock = None
        with self.pending_lock:
            for q in list(self.pending.values()):
                try:
                    q.put_nowait({"ok": False, "error": {"message": "client closed"}})
                except Exception:
                    pass
            self.pending.clear()

    def request(self, action, params=None, timeout=None):
        self.start()
        request_id = new_id("req")
        q = queue.Queue(maxsize=1)
        with self.pending_lock:
            self.pending[request_id] = q
        raw = pack_request(
            action,
            params=params or {},
            reply_channel=self.reply_channel,
            client_id=self.client_id,
            request_id=request_id,
        )
        self._push("request", raw, self.request_channel)
        try:
            msg = q.get(timeout=float(timeout or self.timeout))
        except queue.Empty:
            with self.pending_lock:
                self.pending.pop(request_id, None)
            raise TimeoutError("raw LTtx request timeout: %s" % action)
        if not msg.get("ok"):
            err = msg.get("error") or {}
            raise RuntimeError(err.get("message") or str(err))
        return decode_value(msg.get("result"))

    def _connect_put(self):
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        hello = {
            "con_type": "put_mode",
            "tocken": self.token,
            "local_ip": "127.0.0.1",
            "current_file": __file__,
            "current_dir": ROOT_DIR,
        }
        sock.sendall(json.dumps(hello).encode("utf-8"))
        reply = sock.recv(1024)
        data = json.loads(reply.decode("utf-8", errors="replace"))
        if data.get("code") != 0:
            raise RuntimeError("LTtx put connect failed: %s" % data)
        sock.settimeout(self.timeout)
        return sock

    def _connect_push(self, channel):
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        hello = {
            "con_type": "push_mode",
            "who": channel,
            "pwd": "",
            "tocken": self.token,
            "client_version": 2,
            "local_ip": "127.0.0.1",
            "current_file": __file__,
            "current_dir": ROOT_DIR,
        }
        sock.sendall(json.dumps(hello).encode("utf-8"))
        reply = sock.recv(1024)
        data = json.loads(reply.decode("utf-8", errors="replace"))
        if data.get("code") != 0:
            raise RuntimeError("LTtx push connect failed: %s" % data)
        sock.settimeout(self.timeout)
        return sock

    def _push(self, key, payload, channel):
        msg = json.dumps({"func": "push", "value": "%s|%s" % (key, payload), "who": channel}, ensure_ascii=False)
        send_framed(self.put_sock, msg)

    def _recv_loop(self):
        while self.running:
            try:
                raw = recv_framed(self.sub_sock)
                try:
                    decoded = json.loads(raw)
                    if isinstance(decoded, str):
                        raw = decoded
                except Exception:
                    pass
                if not raw or raw == "1":
                    continue
                if "|" not in raw:
                    continue
                key, payload = raw.split("|", 1)
                if key != "response" and key != "event":
                    continue
                msg = loads_message(payload)
                if not msg:
                    continue
                if msg.get("type") == "response":
                    with self.pending_lock:
                        q = self.pending.pop(msg.get("id"), None)
                    if q:
                        q.put(msg)
            except Exception:
                if self.running:
                    time.sleep(0.02)


def percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    return sorted_values[int((len(sorted_values) - 1) * fraction)]


def summarize(samples):
    grouped = {}
    for row in samples:
        grouped.setdefault(row["case"], {"ok": [], "errors": []})
        if row["ok"]:
            grouped[row["case"]]["ok"].append(row["latency_ms"])
        else:
            grouped[row["case"]]["errors"].append(row)
    result = {}
    for case, data in grouped.items():
        ok = data["ok"]
        ordered = sorted(ok)
        item = {
            "count": len(ok) + len(data["errors"]),
            "ok_count": len(ok),
            "error_count": len(data["errors"]),
            "min_ms": round(min(ok), 3) if ok else None,
            "avg_ms": round(statistics.mean(ok), 3) if ok else None,
            "p50_ms": round(percentile(ordered, 0.50), 3) if ok else None,
            "p95_ms": round(percentile(ordered, 0.95), 3) if ok else None,
            "max_ms": round(max(ok), 3) if ok else None,
            "first_error": data["errors"][0]["error"] if data["errors"] else "",
        }
        result[case] = item
    return result


def record_call(samples, route, name, func, index, timeout_note=""):
    started = time.perf_counter()
    row = {
        "route": route,
        "case": "%s.%s" % (route, name),
        "name": name,
        "index": index,
        "ok": False,
        "latency_ms": None,
        "error_type": "",
        "error": "",
        "result_type": "",
        "result_size": "",
        "started_at": time.time(),
        "timeout_note": timeout_note,
    }
    try:
        result = func()
        row["ok"] = True
        row["result_type"] = type(result).__name__
        if isinstance(result, (dict, list, tuple)):
            row["result_size"] = len(result)
    except Exception as e:
        row["error_type"] = type(e).__name__
        row["error"] = str(e)
    row["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    samples.append(row)
    return row


def query_params(account_id):
    return {"account": {"account_id": account_id, "account_type": ACCOUNT_TYPE_STOCK}}


def full_tick_params(stock_code):
    return {"code_list": [stock_code]}


def run_route(samples, route, client, count, stock_code, account_id, timeout, sleep_seconds):
    actions = [
        ("ping", "cfquant.ping", {}, count),
        ("status", "cfquant.status", {}, min(count, 10)),
        ("full_tick", "xtdata.get_full_tick", full_tick_params(stock_code), count),
        ("query_asset", "xttrader.query_stock_asset", query_params(account_id), count),
        ("query_positions", "xttrader.query_stock_positions", query_params(account_id), count),
        ("query_orders", "xttrader.query_stock_orders", query_params(account_id), count),
        ("query_trades", "xttrader.query_stock_trades", query_params(account_id), count),
    ]
    for name, action, params, action_count in actions:
        for index in range(1, action_count + 1):
            row = record_call(samples, route, name, lambda a=action, p=params: client.request(a, p, timeout=timeout), index)
            print(
                "%s.%s #%s %s %.3f ms"
                % (route, name, index, "OK" if row["ok"] else "ERR", row["latency_ms"]),
                flush=True,
            )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)


def read_pipe_hub_status():
    path = os.path.join(ROOT_DIR, "cfquant_pipe_hub_status.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def write_csv(path, rows):
    fields = [
        "route",
        "case",
        "name",
        "index",
        "ok",
        "latency_ms",
        "error_type",
        "error",
        "result_type",
        "result_size",
        "started_at",
        "timeout_note",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def md_value(value):
    return "-" if value is None else value


def write_markdown(path, payload):
    lines = [
        "# 三种通道延迟对比",
        "",
        "- 测试时间：`%s`" % payload["finished_at_text"],
        "- 股票代码：`%s`" % payload["stock_code"],
        "- 账号：`%s`" % payload["account_id"],
        "- 单项样本数：`%s`" % payload["count"],
        "- LTtx：`%s:%s`" % (LTTX_HOST, LTTX_PORT),
        "- Pipe：`%s`" % payload["pipe_name"],
        "",
        "## 路径说明",
        "",
        "| 路径 | 请求通道 | 说明 |",
        "|---|---|---|",
        "| `普通QMT` | `cfquant.normal.request` | LTtx 普通桥，QMT 普通路径 |",
        "| `极速交易端` | `cfquant.trade.request` | LTtx 交易桥，极速交易端路径 |",
        "| `ctypes` | `cfquant.normal.request` / `cfquant.trade.request` | named pipe 单文件 ctypes 桥 |",
        "",
        "## Pipe Hub 状态",
        "",
        "```json",
        json.dumps(payload["pipe_hub_status"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 汇总",
        "",
        "| 测试项 | 样本 | 成功 | 失败 | min ms | avg ms | p50 ms | p95 ms | max ms | 首个错误 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for case, item in payload["summary"].items():
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                case,
                item["count"],
                item["ok_count"],
                item["error_count"],
                md_value(item["min_ms"]),
                md_value(item["avg_ms"]),
                md_value(item["p50_ms"]),
                md_value(item["p95_ms"]),
                md_value(item["max_ms"]),
                item.get("first_error") or "",
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


def main():
    parser = argparse.ArgumentParser(description="Compare normal QMT, low-latency trade endpoint and ctypes pipe latency.")
    parser.add_argument("--bridge-id", default="default")
    parser.add_argument("--stock-code", default="603881.SH")
    parser.add_argument("--account-id", default="8885060548")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--sleep", type=float, default=0.02)
    parser.add_argument("--out-dir", default=os.path.join(ROOT_DIR, "reports", "latency"))
    parser.add_argument("--pipe-name", default=r"\\.\pipe\cfquant_pipe_hub")
    parser.add_argument(
        "--routes",
        default="normal,fast,ctypes",
        help="Comma-separated routes: normal,fast,ctypes",
    )
    args = parser.parse_args()

    bridge_id = normalize_bridge_id(args.bridge_id)
    channels = channels_for_bridge(bridge_id)
    os.makedirs(args.out_dir, exist_ok=True)
    stamp = now_stamp()
    prefix = "three_transport_latency_%s_%s" % (bridge_id, stamp)
    json_path = os.path.join(args.out_dir, prefix + ".json")
    csv_path = os.path.join(args.out_dir, prefix + ".csv")
    md_path = os.path.join(args.out_dir, prefix + ".md")

    samples = []
    clients = []
    requested_routes = set(item.strip().lower() for item in args.routes.split(",") if item.strip())
    route_defs = [
        ("普通QMT", RawLttxRpcClient(channels["normal"], timeout=args.timeout)),
        ("极速交易端", RawLttxRpcClient(channels["trade"], timeout=args.timeout)),
        ("ctypes.normal", PipeRpcClient(pipe_name=args.pipe_name, request_channel=channels["normal"], timeout=args.timeout)),
        ("ctypes.trade", PipeRpcClient(pipe_name=args.pipe_name, request_channel=channels["trade"], timeout=args.timeout)),
    ]
    route_alias = {
        "普通QMT": "normal",
        "极速交易端": "fast",
        "ctypes.normal": "ctypes",
        "ctypes.trade": "ctypes",
    }
    routes = [
        item for item in route_defs
        if route_alias.get(item[0]) in requested_routes or item[0].lower() in requested_routes
    ]
    try:
        for route, client in routes:
            clients.append(client)
            run_route(samples, route, client, args.count, args.stock_code, args.account_id, args.timeout, args.sleep)
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass

    payload = {
        "bridge_id": bridge_id,
        "channels": channels,
        "stock_code": args.stock_code,
        "account_id": args.account_id,
        "count": args.count,
        "timeout": args.timeout,
        "pipe_name": args.pipe_name,
        "pipe_hub_status": read_pipe_hub_status(),
        "finished_at": time.time(),
        "finished_at_text": now_text(),
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
    for case, item in payload["summary"].items():
        print(
            "%s count=%s ok=%s err=%s avg=%s p50=%s p95=%s max=%s"
            % (
                case,
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
