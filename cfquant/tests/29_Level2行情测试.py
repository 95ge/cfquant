# -*- coding: utf-8 -*-
"""Read-only Level2 smoke test. Edit configuration below and run this file."""
from datetime import datetime
import json
from pathlib import Path
import threading
import time

from _helpers import close_default_client, compact_value, configure_stdout
from cfquant import configure, xtdata


# ======================== 用户配置区 ========================
TRANSPORT = "auto"
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0
STOCK_CODE = "000001.SZ"
PERIODS = ["l2quote", "l2quoteaux", "l2order", "l2transaction", "l2transactioncount", "l2orderqueue"]
COUNT = 10
SECONDS = 15.0
TEST_THOUSAND = False       # 仅限终端确实提供原生千档接口的情况
GEAR_NUM = 10
REPORT_DIR = Path(__file__).resolve().parents[2] / "log"
# ===========================================================


def main():
    configure_stdout()
    if SECONDS <= 0 or COUNT <= 0 or not STOCK_CODE or not PERIODS:
        raise ValueError("SECONDS/COUNT 必须大于 0，STOCK_CODE/PERIODS 不能为空")
    configure(transport=TRANSPORT, bridge_id=BRIDGE_ID, timeout=REQUEST_TIMEOUT)
    report = {"started_at": datetime.now().isoformat(), "stock_code": STOCK_CODE, "periods": {}}
    subscriptions = []
    lock = threading.RLock()

    def callback_for(name):
        def callback(data):
            with lock:
                row = report["periods"][name]
                row["callback_count"] += 1
                records = data.get(STOCK_CODE) if isinstance(data, dict) else None
                if not isinstance(records, list) or not records or not all(isinstance(item, dict) and item for item in records):
                    row["invalid_callback_count"] += 1
                else:
                    row["valid_callback_count"] += 1
                    row["last_callback_sample"] = compact_value(records[-1])
        return callback

    def add_subscription(name, subscribe):
        report["periods"][name] = {"callback_count": 0, "valid_callback_count": 0, "invalid_callback_count": 0}
        try:
            sid = subscribe(callback_for(name))
            subscriptions.append((name, sid))
            report["periods"][name]["subscribe_id"] = sid
        except Exception as error:
            report["periods"][name]["subscribe_error"] = str(error)

    def query(name, function):
        row = report["periods"][name]
        try:
            data = function()
            value = data.get(STOCK_CODE) if isinstance(data, dict) else data
            row["query_rows"] = len(value) if value is not None else 0
            row["query_sample"] = compact_value(data)
        except Exception as error:
            row["query_error"] = str(error)

    try:
        for period in dict.fromkeys(PERIODS):
            add_subscription(period, lambda cb, p=period: xtdata.subscribe_quote(STOCK_CODE, period=p, callback=cb))
        if TEST_THOUSAND:
            add_subscription("l2thousand", lambda cb: xtdata.subscribe_l2thousand(STOCK_CODE, gear_num=GEAR_NUM, callback=cb))
            add_subscription("l2thousand_queue", lambda cb: xtdata.subscribe_l2thousand_queue(STOCK_CODE, callback=cb, gear_num=GEAR_NUM))
        print("Level2 订阅建立阶段结束，观察 %.1f 秒；本脚本不进行交易。" % SECONDS)
        time.sleep(SECONDS)
        methods = {"l2quote": xtdata.get_l2_quote, "l2order": xtdata.get_l2_order, "l2transaction": xtdata.get_l2_transaction}
        for period in dict.fromkeys(PERIODS):
            query(period, lambda p=period: xtdata.get_market_data_ex([], [STOCK_CODE], period=p, count=COUNT, fill_data=False))
            if period in methods:
                name = "get_" + period
                report["periods"][name] = {}
                query(name, lambda p=period: methods[p](stock_code=STOCK_CODE, count=COUNT))
        if TEST_THOUSAND:
            query("l2thousand_queue", lambda: xtdata.get_l2thousand_queue(STOCK_CODE, gear_num=GEAR_NUM))
    except KeyboardInterrupt:
        report["interrupted"] = True
    finally:
        for name, sid in reversed(subscriptions):
            try:
                result = xtdata.unsubscribe_quote(sid)
                report["periods"][name]["unsubscribe_ok"] = result is not False and not (isinstance(result, (int, float)) and result < 0)
            except Exception as error:
                report["periods"][name]["unsubscribe_error"] = str(error)
        close_default_client()
        report["finished_at"] = datetime.now().isoformat()
        with lock:
            for row in report["periods"].values():
                if any(key.endswith("error") for key in row) or row.get("invalid_callback_count") or row.get("unsubscribe_ok") is False:
                    row["status"] = "失败，查看错误"
                elif ("callback_count" in row and not row.get("valid_callback_count")) or ("query_rows" in row and not row["query_rows"]):
                    row["status"] = "待确认：无有效回调或查询为空"
                else:
                    row["status"] = "已收到数据，字段与实时性仍需按终端核对"
            content = json.dumps(report, ensure_ascii=False, indent=2)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / ("level2_test_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        path.write_text(content, encoding="utf-8")
        print(content)
        print("报告：%s" % path)
    return report


if __name__ == "__main__":
    main()
