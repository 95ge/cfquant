# -*- coding: utf-8 -*-
"""default 账号多笔并发异步下单及回调数量核对。

运行：python -X utf8 "cfquant/tests/32_异步下单测试.py"
"""
import json
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from _helpers import PROJECT_ROOT, configure_stdout
from cfquant import configure, xtconstant
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount


CONFIG_FILE = PROJECT_ROOT / "runtime/config/cfquant_web_config.json"
BRIDGE_ID = "default"
TRANSPORT = "auto"
ORDER_COUNT = 10
MAX_WORKERS = 5
STOCK_CODE = "000001.SZ"
ORDER_TYPE = xtconstant.STOCK_BUY
ORDER_VOLUME = 100
PRICE_TYPE = xtconstant.FIX_PRICE
PRICE = 10.0
REQUEST_TIMEOUT = 15.0
CALLBACK_TIMEOUT = 30.0
EXTRA_OBSERVE_SECONDS = 3.0
STRATEGY_NAME = "cfquant_async32"
DRY_RUN = False

PRINT_LOCK = threading.Lock()


def emit(event, **fields):
    with PRINT_LOCK:
        print(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str), flush=True)


def plain(value):
    return dict(value) if isinstance(value, dict) else dict(vars(value))


def value_of(value, *names):
    for name in names:
        item = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if item not in (None, ""):
            return item
    return None


def load_default_account():
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    key = str(data.get("default_account_key") or "default:STOCK:").strip()
    configs = data.get("account_configs") or {}
    row = configs.get(key)
    if not row:
        matches = [item for item in configs.values() if item.get("bridge_id") == BRIDGE_ID and item.get("enabled") is not False]
        if len(matches) != 1:
            raise RuntimeError("无法唯一确定 default 启用账号")
        row = matches[0]
    if row.get("bridge_id") != BRIDGE_ID or row.get("account_type", "").upper() != "STOCK":
        raise RuntimeError("default 配置不是启用的 STOCK 账号")
    return row


class Callback(XtQuantTraderCallback):
    def __init__(self, account_id):
        self.account_id = str(account_id)
        self.lock = threading.Lock()
        self.responses = []
        self.errors = []

    def on_order_stock_async_response(self, response):
        row = plain(response)
        with self.lock:
            self.responses.append(row)
        emit("异步委托回调", seq=row.get("seq"), order_id=row.get("order_id"), order_remark=row.get("order_remark"))

    def on_order_error(self, error):
        row = plain(error)
        with self.lock:
            self.errors.append(row)
        emit("下单错误回调", **row)

    def snapshot(self):
        with self.lock:
            return list(self.responses), list(self.errors)


def main():
    configure_stdout()
    account_row = load_default_account()
    account_id = str(account_row["account_id"])
    remarks = ["async32_%s_%02d" % (uuid.uuid4().hex[:8], index + 1) for index in range(ORDER_COUNT)]
    emit("测试配置", account_id=account_id, account_type=account_row.get("account_type"), bridge_id=BRIDGE_ID,
         order_count=ORDER_COUNT, stock_code=STOCK_CODE, order_volume=ORDER_VOLUME, price=PRICE, dry_run=DRY_RUN)
    if DRY_RUN:
        return 0

    configure(transport=TRANSPORT, bridge_id=BRIDGE_ID, timeout=REQUEST_TIMEOUT)
    account = StockAccount(account_id, account_row["account_type"], BRIDGE_ID)
    callback = Callback(account_id)
    trader = XtQuantTrader(callback=callback, account=account)
    trader.set_timeout(REQUEST_TIMEOUT)
    submissions = []

    def submit(index):
        remark = remarks[index]
        row = {"index": index + 1, "order_remark": remark}
        try:
            seq = trader.order_stock_async(account, STOCK_CODE, ORDER_TYPE, ORDER_VOLUME,
                                           PRICE_TYPE, PRICE, STRATEGY_NAME, remark)
            row.update(seq=seq, status="submitted" if seq not in (None, -1, "-1") else "rejected")
        except Exception as error:
            row.update(status="unknown", error="%s: %s" % (type(error).__name__, error))
        emit("异步下单返回", **row)
        return row

    report_path = PROJECT_ROOT / "log" / ("async32_%s.json" % uuid.uuid4().hex[:10])
    try:
        trader.start()
        if trader.connect() != 0:
            raise RuntimeError("交易连接失败")
        if trader.subscribe(account) != 0:
            raise RuntimeError("账号订阅失败")
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, ORDER_COUNT)) as pool:
            futures = [pool.submit(submit, index) for index in range(ORDER_COUNT)]
            submissions = [future.result() for future in as_completed(futures)]

        expected = {str(row["seq"]) for row in submissions if row["status"] == "submitted"}
        deadline = time.time() + CALLBACK_TIMEOUT
        while time.time() < deadline:
            responses, _ = callback.snapshot()
            received = {str(value_of(row, "seq", "m_nSeq")) for row in responses}
            if expected.issubset(received):
                break
            time.sleep(0.1)
        time.sleep(EXTRA_OBSERVE_SECONDS)
    finally:
        responses, errors = callback.snapshot()
        expected = {str(row["seq"]) for row in submissions if row.get("status") == "submitted"}
        received = [row for row in responses if str(value_of(row, "seq", "m_nSeq")) in expected]
        counts = {}
        for row in received:
            seq = str(value_of(row, "seq", "m_nSeq"))
            counts[seq] = counts.get(seq, 0) + 1
        summary = {
            "planned": ORDER_COUNT,
            "submitted": len(expected),
            "rejected": sum(row.get("status") == "rejected" for row in submissions),
            "unknown": sum(row.get("status") == "unknown" for row in submissions),
            "callback_count": len(received),
            "missing_seqs": sorted(expected - set(counts)),
            "duplicate_seqs": {seq: count for seq, count in counts.items() if count > 1},
            "invalid_order_id_count": sum(value_of(row, "order_id", "m_nRef", "m_nOrderID") in (None, "", -1, "-1") for row in received),
        }
        summary["count_consistent"] = (
            summary["submitted"] == summary["callback_count"]
            and not summary["missing_seqs"]
            and not summary["duplicate_seqs"]
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"summary": summary, "submissions": submissions,
                                           "responses": responses, "errors": errors}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        emit("测试汇总", **summary, report=str(report_path))
        trader.stop()
    return 0 if summary["count_consistent"] else 1


if __name__ == "__main__":
    sys.exit(main())
