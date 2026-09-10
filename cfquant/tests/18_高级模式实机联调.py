# -*- coding: utf-8 -*-
"""Explicit opt-in live bridge checks. Orders are restricted to the confirmed paper account."""
from types import SimpleNamespace
import datetime as dt
import json
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cfquant import configure, get_client, xtconstant, xtdata
from cfquant.client import LTtxRpcClient
from cfquant.protocol import encode_value
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount, XtAsset, XtOrder, XtPosition, XtTrade


# ======================== 用户配置区 ========================
# 直接修改下面的配置，然后运行本文件；不读取命令行参数。
ACCOUNT_ID = ""          # 必填，须与 Web 中默认启用的高级模式账号一致
SKIP_ORDER = True        # 默认仅查询、订阅和下载，不下单、不撤单
CONFIRM_SIMULATION = ""  # 下单前确认是模拟账号，并在这里填写同一个 ACCOUNT_ID
OUTPUT_DIR = ""          # 留空在 private_docs 下自动创建唯一报告目录
# 关闭 SKIP_ORDER 后：买入 000001.SZ 100 股，限价 11.6，10 秒后尝试撤单。
# ===========================================================


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def check_output_directory(directory):
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise ValueError("Use a new empty output directory to preserve previous test evidence")


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if hasattr(value, "columns"):
        return encode_value(value)
    if hasattr(value, "__dict__"):
        return plain(vars(value))
    return encode_value(value)


def sample(value):
    if hasattr(value, "columns"):
        return {"type": type(value).__name__, "shape": list(value.shape), "head": plain(value.head(3))}
    if isinstance(value, list):
        return {"type": "list", "count": len(value), "sample": plain(value[:3])}
    if isinstance(value, dict):
        keys = list(value)
        return {"type": "dict", "count": len(value), "sample": {str(k): sample(value[k]) if isinstance(value[k], (dict, list)) or hasattr(value[k], "columns") else plain(value[k]) for k in keys[:6]}}
    return {"type": type(value).__name__, "value": plain(value)}


class Run:
    def __init__(self, directory, account_id):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.account_id = account_id
        self.started = now()
        self.origin = time.monotonic()
        self.rows = []
        self.events = []
        self.lock = threading.RLock()
        self.order = {"authorized_simulation_account": account_id, "stock_code": "000001.SZ", "volume": 100, "price": 11.6, "cancel_after_seconds": 10, "submitted": False}
        self.environment = {}
        self.journal = self.directory / "原始事件.jsonl"

    def append(self, record):
        with self.lock:
            with self.journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def event(self, name, data=None, source="callback"):
        record = {"kind": "event", "name": name, "at": now(), "elapsed_seconds": round(time.monotonic() - self.origin, 6), "thread": threading.current_thread().name, "source": source, "payload": plain(data)}
        with self.lock:
            self.events.append(record)
            self.append(record)

    def note(self, name, status, detail, **extra):
        row = {"kind": "case", "name": name, "status": status, "detail": detail, "at": now()}
        row.update(extra)
        with self.lock:
            self.rows.append(row)
            self.append(row)
        print("[%s] %s: %s" % (status, name, detail), flush=True)
        return row

    def call(self, name, function, validate=None):
        begin = time.perf_counter()
        try:
            value = function()
            status, detail = validate(value) if validate else ("OBSERVED", "调用返回，未据此认定语义完整兼容")
            self.note(name, status, detail, latency_ms=round((time.perf_counter() - begin) * 1000, 3), result=sample(value))
            return value
        except Exception as error:
            self.note(name, "FAIL", "%s: %s" % (type(error).__name__, error), latency_ms=round((time.perf_counter() - begin) * 1000, 3))
            return None

    def save(self):
        report = {"started_at": self.started, "finished_at": now(), "environment": self.environment, "order": self.order, "cases": self.rows, "events": self.events}
        (self.directory / "联调结果.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        counts = {}
        for row in self.rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        lines = ["# 高级模式接口与回调实机联调报告", "", "- 开始时间：" + self.started, "- 结束时间：" + report["finished_at"], "- 账号：" + self.account_id + ("，操作者通过代码配置确认是模拟账号。" if self.order.get("simulation_confirmed") else "，本次未确认模拟账号属性。"), "- 当前测试包含非交易时段；无推送不自动等于回调损坏。", "- 结果计数：" + json.dumps(counts, ensure_ascii=False), "", "## 模拟委托", "", "```json", json.dumps(self.order, ensure_ascii=False, indent=2, default=str), "```", "", "## 接口结果", "", "| 接口或检查 | 结果 | 耗时毫秒 | 说明 |", "| --- | --- | ---: | --- |"]
        for row in self.rows:
            detail = str(row["detail"]).replace("|", "/").replace("\n", " ")
            lines.append("| `%s` | %s | %s | %s |" % (row["name"], row["status"], row.get("latency_ms", ""), detail))
        lines.extend(["", "## 回调记录", "", "| 回调 | 来源 | 数量 |", "| --- | --- | ---: |"])
        grouped = {}
        for event in self.events:
            key = (event["name"], event["source"])
            grouped[key] = grouped.get(key, 0) + 1
        for (name, source), count in sorted(grouped.items()):
            lines.append("| `%s` | %s | %s |" % (name, source, count))
        lines.extend(["", "## 判定边界", "", "- PASS：本次检查条件成立，不代表所有字段、版本和时段全面兼容。", "- PARTIAL：已观察到部分结果或已知的模拟回调/降级行为。", "- OBSERVED：只证明调用返回，尚无充分语义校验。", "- UNVERIFIED：缺少行情变化、成交或其他前置条件，尚无法验证。", "- FAIL：实际调用或本次断言失败，应结合错误详情定位。", "- SKIP：未执行；信用、期货查询不向普通股票账号强行发送。", "- 委托发送固定直达高级模式交易桥，避免统一路由的跨传输自动重试；本次不是网页下单路径测试。", "- 委托错误/成交回调仅在对应事件确实发生时才应出现；没有成交不应要求成交回调。", "- `on_connected/on_disconnected`是 SDK 本地生命周期回调，不能证明 QMT 原生连接主推正常。", "- 查询方法带 `_async` 不代表真正异步；报告另外记录回调线程和是否在方法返回前执行。", "- 未创建或修改板块，未进行资金划转，未补单或修改用户指定价格。", "- 完整字段、事件时间、线程和原始信封见[联调结果.json](联调结果.json)与[原始事件.jsonl](原始事件.jsonl)。", ""])
        (self.directory / "高级模式接口与回调测试报告.md").write_text("\n".join(lines), encoding="utf-8")


def typed(cls):
    def check(value):
        values = value if isinstance(value, list) else [value]
        if value is None:
            return "UNVERIFIED", "底层返回 None"
        return ("PASS", "返回类型符合 " + cls.__name__) if all(isinstance(item, cls) for item in values) else ("FAIL", "返回类型不符合 " + cls.__name__)
    return check


def nonempty(value):
    if value is None or (hasattr(value, "__len__") and len(value) == 0):
        return "UNVERIFIED", "返回为空，无法验证有效数据"
    if isinstance(value, dict) and not any(nonempty(item)[0] == "PASS" for item in value.values()):
        return "UNVERIFIED", "外层容器存在，但内部没有有效数据"
    return "PASS", "返回非空数据；不代表所有字段或时间语义完整兼容"


def history_observation(value):
    status, detail = nonempty(value)
    if status != "PASS":
        return status, detail
    return "OBSERVED", "已返回板块成分；尚未用历史基准验证 real_timetag 是否实际生效"


def query_callback_semantics(received):
    if len(received) != 1 or not received[0]["valid"]:
        return "FAIL", "回调次数或返回类型不符合预期：%s" % received
    if received[0]["before_return"] and received[0]["thread"] == "MainThread":
        return "PARTIAL", "同步返回前在主线程执行回调，不是真正异步调度：%s" % received
    return "OBSERVED", "已收到一次类型正确的回调，异步时序与请求关联仍需验证：%s" % received


def make_trader_callback(run):
    callback = XtQuantTraderCallback()
    for name in XtQuantTrader._event_types:
        def receive(data=None, name=name):
            run.event(name, data, "sdk_local" if name in ("on_connected", "on_disconnected") else "trader_callback")
        setattr(callback, name, receive)
    return callback


def matching_orders(trader, account, remark):
    return [row for row in (trader.query_stock_orders(account) or []) if getattr(row, "order_remark", "") == remark]


def paper_order(run, trader, account, direct, confirmation):
    if confirmation != account.account_id:
        run.note("paper_order", "SKIP", "未提供当前模拟账号的显式确认，不下单")
        return
    if (run.directory / "订单已提交标记.json").exists():
        raise RuntimeError("This report directory already contains an order attempt; refusing another order")
    original_request = trader._trade_request

    def fixed_trade_request(action, params=None, timeout=None):
        if action in ("xttrader.order_stock_async", "xttrader.cancel_order_stock_async", "xttrader.cancel_order_stock"):
            return direct.request(action, params or {}, timeout=5)
        return original_request(action, params, timeout)

    trader._trade_request = fixed_trade_request
    for name in XtQuantTrader._event_types:
        direct.add_callback("trader:" + name, trader._make_trader_handler(name))
    remark = "cfqtest_" + uuid.uuid4().hex[:14]
    run.order["remark"] = remark
    state = {"order_id": None, "cancel_seq": None}
    state_lock = threading.RLock()
    cancel_finished = threading.Event()
    t0 = time.monotonic()
    run.order.update({"submitted": True, "submission_started_at": now(), "route": "direct_lttx/trade; no order transport fallback"})
    with (run.directory / "订单已提交标记.json").open("x", encoding="utf-8") as stream:
        json.dump(run.order, stream, ensure_ascii=False, indent=2)

    def find_id():
        with state_lock:
            if state["order_id"] is not None:
                return state["order_id"]
        with run.lock:
            candidates = list(run.events)
        for event in candidates:
            row = event.get("payload") or {}
            if not isinstance(row, dict) or row.get("order_remark") != remark:
                continue
            if str(row.get("account_id", "")) != account.account_id:
                continue
            value = row.get("order_id")
            if value not in (None, "", 0, -1, "-1", "0"):
                with state_lock:
                    state["order_id"] = value
                return value
        return None

    def cancel_after_deadline():
        try:
            time.sleep(max(0, t0 + 10 - time.monotonic()))
            order_id = find_id()
            if order_id is None:
                rows = matching_orders(trader, account, remark)
                if len(rows) == 1:
                    order_id = rows[0].order_id
            if order_id in (None, "", -1, 0, "-1", "0"):
                run.note("cancel_at_10_seconds", "FAIL", "10秒到时仍无法唯一确定本次委托编号，未撤其他订单")
                return
            with state_lock:
                state["order_id"] = order_id
            run.order["order_id"] = order_id
            run.order["cancel_started_at"] = now()
            run.order["cancel_delay_seconds"] = round(time.monotonic() - t0, 6)
            state["cancel_seq"] = run.call("cancel_order_stock_async", lambda: trader.cancel_order_stock_async(account, order_id), lambda value: ("PASS", "撤单请求序号已返回；仍需核对终态") if isinstance(value, int) and value > 0 else ("FAIL", "未返回有效撤单请求序号"))
            run.order["cancel_seq"] = state["cancel_seq"]
        except Exception as error:
            run.note("cancel_watchdog", "FAIL", str(error))
        finally:
            cancel_finished.set()
            run.save()

    timer = threading.Thread(target=cancel_after_deadline, name="paper-order-cancel-watchdog")
    timer.start()
    try:
        seq = run.call("order_stock_async", lambda: trader.order_stock_async(account, "000001.SZ", xtconstant.STOCK_BUY, 100, xtconstant.FIX_PRICE, 11.6, "cfquant_integration", remark), lambda value: ("PASS", "异步委托请求序号已返回；不是成交确认") if isinstance(value, int) and value > 0 else ("FAIL", "未返回有效委托请求序号"))
        run.order["order_seq"] = seq
        rows = run.call("order_query_before_cancel", lambda: matching_orders(trader, account, remark), nonempty)
        if rows and len(rows) == 1:
            row = rows[0]
            matches = row.stock_code == "000001.SZ" and row.order_volume == 100 and abs(float(row.price) - 11.6) < 1e-8 and row.account_id == account.account_id
            run.note("order_parameters", "PASS" if matches else "FAIL", "核对账号、证券、100股和11.6限价", order=plain(row))
            with state_lock:
                state["order_id"] = row.order_id
            run.order["before_cancel"] = plain(row)
        elif rows and len(rows) != 1:
            run.note("order_uniqueness", "FAIL", "发现多笔相同测试标记的委托，需要人工核查")
        cancel_finished.wait(25)
        timer.join()
        final = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            rows = matching_orders(trader, account, remark)
            if len(rows) == 1:
                final = rows[0]
                if final.order_status in (53, 54, 56, 57):
                    break
            time.sleep(0.5)
        if final and final.order_status not in (53, 54, 56, 57):
            run.call("cancel_order_stock_cleanup", lambda: trader.cancel_order_stock(account, final.order_id))
            time.sleep(2)
            rows = matching_orders(trader, account, remark)
            final = rows[0] if len(rows) == 1 else final
        run.order["final_order"] = plain(final)
        if final is not None:
            matches = final.stock_code == "000001.SZ" and final.order_volume == 100 and abs(float(final.price) - 11.6) < 1e-8 and final.account_id == account.account_id and final.order_type == xtconstant.STOCK_BUY
            run.note("order_final_parameters", "PASS" if matches else "FAIL", "核对终态委托账号、买入方向、证券、100股和11.6限价")
            run.note("order_price_type_compatibility", "PASS" if final.price_type == xtconstant.FIX_PRICE else "FAIL", "输入限价枚举=%s，查询返回=%s" % (xtconstant.FIX_PRICE, final.price_type))
        if final is None:
            run.note("order_final_state", "FAIL", "未查到唯一测试委托，不能声称已撤单")
        elif final.order_status in (53, 54):
            run.note("order_final_state", "PASS", "主动查询确认撤单终态，status=%s，成交数量=%s" % (final.order_status, final.traded_volume))
        elif final.order_status == 56:
            run.note("order_final_state", "PARTIAL", "订单已成交，不能再撤回成交；模拟持仓可能已增加")
        elif final.order_status == 57:
            run.note("order_final_state", "PARTIAL", "订单被拒绝/废单，没有验证到正常已报后撤单流程")
        else:
            run.note("order_final_state", "FAIL", "测试委托仍未确认终态，需要人工处理")
        run.call("query_stock_order_test_order", lambda: trader.query_stock_order(account, state["order_id"]), typed(XtOrder))
        run.call("query_stock_trades_test_order", lambda: [row for row in (trader.query_stock_trades(account) or []) if str(row.order_id) == str(state["order_id"])], typed(XtTrade))
        time.sleep(2)
        for name, seq_key in (("on_order_stock_async_response", "order_seq"), ("on_cancel_order_stock_async_response", "cancel_seq")):
            events = [event for event in run.events if event["name"] == name and isinstance(event["payload"], dict) and event["payload"].get("seq") == run.order.get(seq_key)]
            valid = [event for event in events if str(event["payload"].get("order_id")) == str(state["order_id"]) and event["payload"].get("account_id") == account.account_id]
            run.note(name + "_correlation", "PASS" if valid else "FAIL", "按请求序号、委托编号和账号核对；匹配数量=%s" % len(valid))
        updates = [event for event in run.events if event["name"] == "on_stock_order" and str((event["payload"] or {}).get("order_id")) == str(state["order_id"])]
        statuses = [(event["payload"] or {}).get("order_status") for event in updates]
        run.order["callback_order_statuses"] = statuses
        run.note("on_stock_order_final_consistency", "PASS" if final and final.order_status in statuses else "FAIL", "回调状态序列=%s；查询终态=%s" % (statuses, getattr(final, "order_status", None)))
        trades = [event for event in run.events if event["name"] == "on_stock_trade" and str((event["payload"] or {}).get("order_id")) == str(state["order_id"])]
        run.note("on_stock_trade_expectation", "PASS" if final and final.traded_volume == 0 and not trades else "OBSERVED", "成交数量=%s，本次委托成交回调=%s；未成交时无成交回调符合预期" % (getattr(final, "traded_volume", None), len(trades)))
    finally:
        timer.join()
        trader._trade_request = original_request
        run.save()


def readonly_checks(run, trader, account):
    run.call("get_full_tick", lambda: xtdata.get_full_tick(["000001.SZ", "600000.SH"]), nonempty)
    run.call("get_instrument_detail", lambda: xtdata.get_instrument_detail("000001.SZ"), lambda value: ("PARTIAL" if value and value.get("cfquant_detail_partial") else "PASS", "合约字段及降级标记见原始结果") if value else ("UNVERIFIED", "无详情"))
    run.call("get_instrument_detail_complete", lambda: xtdata.get_instrument_detail("000001.SZ", True), nonempty)
    run.call("get_cb_info", lambda: xtdata.get_cb_info("123219.SZ"), lambda value: ("PARTIAL", "只校验正股代码和转股价；不声称完整转债资料") if isinstance(value, dict) and "stockCode" in value and "bondConvPrice" in value else ("UNVERIFIED", "转债无有效两字段资料"))
    run.call("get_divid_factors", lambda: xtdata.get_divid_factors("600000.SH"), lambda value: ("PASS", "七列DataFrame且时间戳升序") if hasattr(value, "columns") and len(value.columns) == 7 and value.index.is_monotonic_increasing and len(value) else ("UNVERIFIED", "无有效除权记录或结构不匹配"))
    run.call("get_divid_factors_range", lambda: xtdata.get_divid_factors("600000.SH", "20230101", "20260909"), nonempty)
    run.call("get_sector_list", xtdata.get_sector_list, lambda value: ("PASS", "非空、无重复的扁平板块名称列表，共%s项" % len(value)) if isinstance(value, list) and value and all(isinstance(item, str) for item in value) and len(value) == len(set(value)) else ("FAIL", "板块列表结构不符合预期"))
    run.call("get_stock_list_in_sector", lambda: xtdata.get_stock_list_in_sector("沪深300"), nonempty)
    run.call("get_stock_list_in_sector_history", lambda: xtdata.get_stock_list_in_sector("沪深300", xtdata._divid_time_bound("20240909")), history_observation)
    run.call("get_market_data_ex", lambda: xtdata.get_market_data_ex(["close"], ["000001.SZ"], "1d", count=3), nonempty)
    run.call("get_local_data", lambda: xtdata.get_local_data(["close"], ["000001.SZ"], "1d", count=3), nonempty)
    run.call("call_formula_batch", lambda: xtdata.call_formula_batch(["MA"], ["000001.SZ"], "1d", count=3), nonempty)
    run.call("query_stock_asset", lambda: trader.query_stock_asset(account), typed(XtAsset))
    run.call("query_stock_positions", lambda: trader.query_stock_positions(account), typed(XtPosition))
    run.call("query_stock_orders", lambda: trader.query_stock_orders(account), typed(XtOrder))
    run.call("query_stock_orders_cancelable", lambda: trader.query_stock_orders(account, True), lambda value: ("PASS", "所有返回委托均属于可撤状态") if isinstance(value, list) and all(item.order_status in (48, 49, 50, 55) for item in value) else ("FAIL", "可撤筛选不符合预期"))
    run.call("query_stock_trades", lambda: trader.query_stock_trades(account), typed(XtTrade))
    run.call("query_ipo_data", trader.query_ipo_data, lambda value: ("PARTIAL", "返回申购资料；purchaseDate需与目标交易日核对") if nonempty(value)[0] == "PASS" else nonempty(value))
    run.call("query_new_purchase_limit", lambda: trader.query_new_purchase_limit(account), nonempty)
    run.call("query_account_infos", trader.query_account_infos, nonempty)
    run.call("query_account_status", trader.query_account_status, nonempty)
    for method in ("query_position_statistics", "query_credit_assure", "query_credit_subjects", "query_credit_slo_code", "query_credit_detail", "query_stk_compacts"):
        run.note(method, "SKIP", "当前仅授权普通股票模拟账号，不具备所需期货/信用账号")
    for method in ("create_sector_folder", "create_sector", "reset_sector", "remove_stock_from_sector"):
        run.note(method, "SKIP", "本次未授权具体测试板块，不改写用户已有板块")
    for method, cls in (("query_stock_asset_async", XtAsset), ("query_stock_orders_async", XtOrder), ("query_stock_positions_async", XtPosition), ("query_stock_trades_async", XtTrade)):
        received = []
        returned = {"done": False}
        callback_received = threading.Event()
        def callback(data, method=method, received=received, returned=returned, cls=cls, callback_received=callback_received):
            received.append({"before_return": not returned["done"], "thread": threading.current_thread().name, "valid": typed(cls)(data)[0] == "PASS"})
            run.event(method, data, "query_callback")
            callback_received.set()
        run.call(method, lambda method=method: getattr(trader, method)(account, callback))
        returned["done"] = True
        callback_received.wait(2)
        status, detail = query_callback_semantics(received)
        run.note(method + "_callback_semantics", status, detail)


def main():
    settings = SimpleNamespace(
        account_id=str(ACCOUNT_ID or "").strip(),
        skip_order=SKIP_ORDER,
        confirm_simulation=str(CONFIRM_SIMULATION or "").strip(),
        output_dir=OUTPUT_DIR,
    )
    if not settings.account_id:
        raise ValueError("请在顶部用户配置区填写 ACCOUNT_ID")
    if not settings.skip_order and settings.confirm_simulation != settings.account_id:
        raise ValueError("下单测试须确认模拟账号，并将 CONFIRM_SIMULATION 设置为同一个 ACCOUNT_ID")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = json.loads((ROOT / "runtime/config/cfquant_web_config.json").read_text(encoding="utf-8"))
    selected = (config.get("account_configs") or {}).get("default:STOCK:" + settings.account_id, {})
    if settings.account_id != config.get("default_account_id") or selected.get("mode") != "lttx" or not selected.get("enabled"):
        raise RuntimeError("Default enabled account and advanced mode do not match the explicit test target")
    output_dir = str(settings.output_dir or "").strip()
    directory = Path(output_dir).expanduser() if output_dir else ROOT / "private_docs" / (
        "高级模式联调_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    )
    check_output_directory(directory)
    run = Run(directory, settings.account_id)
    run.order["simulation_confirmed"] = settings.confirm_simulation == settings.account_id
    configure(transport="auto", bridge_id="default", timeout=12)
    account = StockAccount(settings.account_id, "STOCK", bridge_id="default")
    trader = XtQuantTrader(account=account, callback=make_trader_callback(run))
    trader.set_timeout(8)
    direct = LTtxRpcClient(request_channel="cfquant.trade.request", timeout=6)
    normal = LTtxRpcClient(request_channel="cfquant.normal.request", timeout=6)
    quote_subscriptions = []
    formula_subscription = None
    try:
        for channel, client in (("trade", direct), ("normal", normal)):
            status = run.call("bridge_status_" + channel, lambda client=client: client.request("cfquant.status", {}), nonempty)
            run.environment[channel] = status
            if not status or (status.get("runtime") or {}).get("account_id") != settings.account_id:
                raise RuntimeError("Bridge account identity does not match")
        run.environment["sdk_client"] = type(get_client()).__name__
        if run.environment["sdk_client"] != "WebLttxRpcClient":
            raise RuntimeError("Advanced mode web routing registry was not discovered")
        get_client().add_callback("__event__", lambda event: run.event(str(event.get("event")), event, "quote_wire"))
        direct.add_callback("__event__", lambda event: run.event(str(event.get("event")), event, "direct_trade_wire"))
        connected = run.call("trader_connect", trader.connect, lambda value: ("PASS", "连接成功") if value == 0 else ("FAIL", "连接失败"))
        if connected != 0:
            raise RuntimeError("Trader connection failed")
        trader._get_client().add_callback("__event__", lambda event: run.event(str(event.get("event")), event, "trader_web_wire"))
        before = run.call("asset_before_order", lambda: trader.query_stock_asset(account), typed(XtAsset))
        if not settings.skip_order:
            if before is None or before.account_id != settings.account_id or float(before.cash) < 1160:
                raise RuntimeError("Paper account identity or available cash check failed")
            paper_order(run, trader, account, direct, settings.confirm_simulation)
        for label, subscribe in (
            ("subscribe_quote_tick", lambda: xtdata.subscribe_quote("000001.SZ", "tick", callback=lambda data: run.event("quote_tick", data))),
            ("subscribe_whole_quote", lambda: xtdata.subscribe_whole_quote(["000001.SZ"], callback=lambda data: run.event("whole_quote", data))),
        ):
            sub_id = run.call(label, subscribe, lambda value: ("PASS", "订阅号=%s；回调另行观察" % value) if isinstance(value, int) and value > 0 else ("FAIL", "没有有效订阅号"))
            if isinstance(sub_id, int) and sub_id > 0:
                quote_subscriptions.append(sub_id)
        formula_subscription = run.call("subscribe_formula", lambda: xtdata.subscribe_formula("MA", "000001.SZ", "1d", "", "", 3, "none", {}, callback=lambda data: run.event("formula", data)), lambda value: ("PASS", "模型订阅号=%s" % value) if isinstance(value, int) and value > 0 else ("FAIL", "没有有效模型订阅号"))
        readonly_checks(run, trader, account)
        today = dt.datetime.now().date()
        run.call("download_history_data2_callback", lambda: xtdata.download_history_data2(["000001.SZ"], "1d", (today - dt.timedelta(days=7)).strftime("%Y%m%d"), today.strftime("%Y%m%d"), callback=lambda data: run.event("download_history", data), keep_callback=True))
        time.sleep(15)
        for name in ("quote_tick", "whole_quote", "formula", "download_history", "on_stock_asset", "on_stock_position", "on_account_status"):
            events = [event for event in run.events if event["name"] == name]
            run.note(name + "_callback_observation", "OBSERVED" if events else "UNVERIFIED", "观察到%s次回调；实时变化/原生回调属性需结合信封及数据时间判断" % len(events))
    except Exception as error:
        run.note("run_exception", "FAIL", "%s: %s" % (type(error).__name__, error))
    finally:
        for sub_id in quote_subscriptions:
            run.call("unsubscribe_quote_%s" % sub_id, lambda sub_id=sub_id: xtdata.unsubscribe_quote(sub_id))
        if isinstance(formula_subscription, int) and formula_subscription > 0:
            run.call("unsubscribe_formula", lambda: xtdata.unsubscribe_formula(formula_subscription))
        trader.stop()
        direct.close()
        normal.close()
        get_client().close()
        run.save()
        print("REPORT=" + str(run.directory / "高级模式接口与回调测试报告.md"), flush=True)


if __name__ == "__main__":
    main()
