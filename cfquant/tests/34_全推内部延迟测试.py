# -*- coding: utf-8 -*-
"""修改下方配置后直接运行。只订阅行情，不下单；Ctrl+C 退订并退出。"""
from collections import deque
from types import SimpleNamespace
import threading
import time

from _helpers import close_default_client, configure_cfquant, configure_stdout, parse_csv, print_json
from cfquant import diagnostics, xtdata


TRANSPORT = "auto"  # 直接连本机极致模式可用 ctypes；auto 按项目配置路由
BRIDGE_ID = "default"  # 改为要测试的绑定桥 ID
MARKETS = "SH,SZ,BJ"  # 默认全市场；也可改为证券代码列表缩小订阅范围
REQUEST_TIMEOUT = 15.0
SECONDS = 0.0  # 0 表示持续运行，Ctrl+C 停止
PRINT_INTERVAL = 1.0  # 回调内不打印，避免控制台阻塞行情接收
SAMPLE_CODES = 3  # 只限制控制台打印行数；设为 None 打印整批。统计始终覆盖整批。


def summarize(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"count": 0}
    return {"count": len(values), "min_ms": values[0], "avg_ms": round(sum(values) / len(values), 3),
            "p95_ms": values[max(0, (len(values) * 95 + 99) // 100 - 1)], "max_ms": values[-1]}


def main():
    configure_stdout()
    configure_cfquant(SimpleNamespace(transport=TRANSPORT, bridge_id=BRIDGE_ID, timeout=REQUEST_TIMEOUT))
    lock = threading.Lock()
    state = {"events": 0, "last": None}
    internal = deque(maxlen=600)

    def on_quote(report):
        # diagnostics 已在回调入口记录接收时间，此处只存测量结果。
        with lock:
            state["events"] += 1
            state["last"] = report
            internal.append(report["internal_latency_ms"])

    subscribe_id = None
    started = time.monotonic()
    try:
        subscribe_id = diagnostics.subscribe_whole_quote(parse_csv(MARKETS), on_quote)
        print_json({"subscribe_id": subscribe_id, "bridge_id": BRIDGE_ID, "markets": MARKETS,
                    "说明": "行情到QMT=QMT回调入口时间-原行情时间；行情到程序=接收时间-原行情时间；内部=接收时间-QMT发送前时间。单位 ms。行情到程序=行情到QMT+QMT准备+内部。跨机需校时；旧快照会使行情时间差变大。"})
        stop = threading.Event()
        while not SECONDS or time.monotonic() - started < SECONDS:
            stop.wait(max(0.1, PRINT_INTERVAL))
            with lock:
                snapshot = dict(state)
                inside = list(internal)
            report = snapshot["last"]
            displayed = dict(report, samples=report["samples"][:SAMPLE_CODES]) if report else None
            print_json({"events": snapshot["events"], "elapsed_s": round(time.monotonic() - started, 1),
                        "本批实际接收标的数": snapshot["last"]["code_count"] if snapshot["last"] else 0,
                        "本批展示样本数": len(displayed["samples"]) if displayed else 0,
                        "内部延迟_最近600批": summarize(inside),
                        "行情到程序_本批全部": report["summary"]["quote_latency"] if report else None,
                        "行情到QMT_本批全部": report["summary"]["qmt_quote_latency"] if report else None,
                        "最新数据": displayed,
                        "距最后推送_ms": round(time.time() * 1000 - snapshot["last"]["received_at_ms"], 3) if snapshot["last"] else None,
                        "状态": "已接收" if snapshot["last"] else "等待行情；非交易时间或无变化时可能没有推送"})
    except KeyboardInterrupt:
        print("停止测试，正在退订。", flush=True)
    finally:
        try:
            if subscribe_id is not None:
                xtdata.unsubscribe_quote(subscribe_id)
        finally:
            close_default_client()


if __name__ == "__main__":
    main()
