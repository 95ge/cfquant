# -*- coding: utf-8 -*-
from types import SimpleNamespace
import contextlib
import io
import json
import threading
import time

from _helpers import configure_cfquant, configure_stdout, print_json as _print_json, summarize

from cfquant.xtconstant import FIX_PRICE, STOCK_BUY, STOCK_SELL
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback, close_trade_client
from cfquant.xttype import StockAccount


# ======================== 用户配置区 ========================
# 直接修改下面的配置，然后运行本文件；不读取命令行参数。
TRANSPORT = "auto"       # auto 自动发现；也可填写 ctypes、web_lttx 或 lttx
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0    # 请求超时，单位秒
ACCOUNT_ID = "8885060548"
ACCOUNT_TYPE = "STOCK"
STOCK_CODE = "000001.SZ"
SIDE = "buy"              # buy=买入，sell=卖出
PRICE = 11.5
VOLUME = 100
PRICE_TYPE = FIX_PRICE
STRATEGY_NAME = "cfquant_real_order_latency"
ORDER_REMARK = ""         # 留空自动生成唯一备注
FIND_ORDER_TIMEOUT = 5.0
CALLBACK_TIMEOUT = 5.0
QUERY_INTERVAL = 0.05
JSON_OUTPUT = False
SHOW_TRANSPORT_LOG = False
DRY_RUN = False           # True 只预览配置，不连接
CONNECT_ONLY = False      # True 只连接并订阅账号，不下单、不撤单
REQUIRE_CONFIRM = False   # True 开启确认文本保护
CONFIRM_TEXT = ""         # 开启保护时须匹配 required_confirm_text
ALLOW_STOCK_FALLBACK = False  # 无订单号和备注时是否按账号+证券匹配
# 注意：DRY_RUN 和 CONNECT_ONLY 都为 False 时会按以上配置提交真实委托。
# ===========================================================


LOG_PREFIX = "【真实下单测试】"
JSON_OUTPUT_ENABLED = False


def elapsed_ms(started, ended=None):
    ended = time.perf_counter() if ended is None else ended
    return round((ended - started) * 1000, 3)


def seconds_to_ms(value):
    return round(float(value or 0) * 1000, 3)


def format_log_number(value, digits=3):
    text = ("%%.%df" % digits) % float(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_log_value(key, value):
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if str(key).endswith("_ms"):
        try:
            return "%sms" % format_log_number(value, digits=3)
        except Exception:
            return "%sms" % value
    if isinstance(value, float):
        return format_log_number(value, digits=6)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    text = str(value)
    if any(char.isspace() for char in text):
        return json.dumps(text, ensure_ascii=False)
    return text


def print_info(message, **fields):
    if not fields:
        print("%s%s" % (LOG_PREFIX, message), flush=True)
        return
    parts = ["%s=%s" % (key, format_log_value(key, value)) for key, value in fields.items()]
    print("%s%s | %s" % (LOG_PREFIX, message, " ".join(parts)), flush=True)


def print_json(payload):
    if JSON_OUTPUT_ENABLED:
        _print_json(payload)


def _append_captured_lines(captured, stream_name, text):
    for line in str(text or "").splitlines():
        line = line.strip()
        if line:
            captured.append((stream_name, line))


@contextlib.contextmanager
def capture_external_output():
    captured = []
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            yield captured
    finally:
        _append_captured_lines(captured, "stdout", stdout_buffer.getvalue())
        _append_captured_lines(captured, "stderr", stderr_buffer.getvalue())


def print_external_logs(stage, captured, show=False):
    if not captured:
        return
    if not show:
        print_info("外部日志已收起", stage=stage, lines=len(captured), show_with="SHOW_TRANSPORT_LOG = True")
        return
    for stream_name, line in captured:
        print_info("外部日志", stage=stage, stream=stream_name, line=line)


def requested_transport_text(transport):
    mode = str(transport or "").strip().lower()
    if mode in ("pipe", "ctypes", "named_pipe", "named-pipe"):
        return "请求通信模式：ctypes/PipeHub，本机 Python 通过 named pipe 连接 cfquant_pipe_hub，不经过 LTtx。"
    if mode in ("lttx", "tx", "socket"):
        return "请求通信模式：LTtx，本机 Python 通过 LTtx 连接 QMT 交易桥。"
    if mode in ("web", "web_lttx", "lttx_web", "web-lttx", "lttx-web"):
        return "请求通信模式：Web LTtx，本机 Python 先通过 LTtx 到 Web 统一路由，再由 Web 按账号选择实际交易桥。"
    if mode == "auto":
        return "请求通信模式：auto，cfquant 会先探测 Web LTtx 路由；没有可用路由时通常回退到 ctypes/PipeHub。"
    return "请求通信模式：%s，未识别为内置说明类型。" % (transport or "")


def client_connection_info(trader):
    try:
        client = trader._get_client()
    except Exception:
        client = getattr(trader, "_client", None)
    if client is None:
        return {"client_class": ""}

    class_name = type(client).__name__
    info = {
        "client_class": class_name,
        "client_id": getattr(client, "client_id", ""),
        "request_channel": getattr(client, "request_channel", ""),
        "reply_channel": getattr(client, "reply_channel", ""),
    }
    if hasattr(client, "pipe_name"):
        info.update({
            "transport_name": "ctypes/PipeHub named pipe",
            "pipe_name": getattr(client, "pipe_name", ""),
            "connect_timeout_ms": getattr(client, "connect_timeout_ms", ""),
        })
    elif class_name == "WebLttxRpcClient":
        info.update({
            "transport_name": "Web LTtx route",
            "lttx_host": getattr(client, "host", ""),
            "lttx_port": getattr(client, "port", ""),
        })
    elif hasattr(client, "host") and hasattr(client, "port"):
        info.update({
            "transport_name": "LTtx direct",
            "lttx_host": getattr(client, "host", ""),
            "lttx_port": getattr(client, "port", ""),
        })
    else:
        info["transport_name"] = class_name
    return info


def print_connection_info(info):
    class_name = info.get("client_class") or "未知"
    transport_name = info.get("transport_name") or class_name
    print_info(
        "实际连接通道",
        client_class=class_name,
        transport=transport_name,
        request_channel=info.get("request_channel", ""),
        client_id=info.get("client_id", ""),
    )
    if info.get("pipe_name"):
        print_info("PipeHub 连接信息", pipe_name=info.get("pipe_name"), connect_timeout_ms=info.get("connect_timeout_ms"))
    if info.get("lttx_host") or info.get("lttx_port"):
        print_info("LTtx 连接信息", host=info.get("lttx_host"), port=info.get("lttx_port"))


def pick_value(obj, *names):
    if obj is None:
        return None
    for name in names:
        try:
            if isinstance(obj, dict) and name in obj:
                value = obj.get(name)
            else:
                value = getattr(obj, name)
        except Exception:
            continue
        if value not in (None, ""):
            return value
    return None


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in ("", "-1", "None", "none") else text


def normalize_stock_code(stock_code):
    stock_code = str(stock_code or "").strip().upper()
    if "." in stock_code or not stock_code:
        return stock_code
    if stock_code.startswith(("5", "6", "9")):
        return "%s.SH" % stock_code
    return "%s.SZ" % stock_code


def stock_code_from_obj(obj):
    stock_code = normalize_text(pick_value(obj, "stock_code", "code"))
    if stock_code:
        return normalize_stock_code(stock_code)
    instrument_id = normalize_text(pick_value(obj, "m_strInstrumentID", "instrument_id"))
    exchange_id = normalize_text(pick_value(obj, "m_strExchangeID", "exchange_id", "market"))
    if instrument_id and exchange_id:
        return normalize_stock_code("%s.%s" % (instrument_id, exchange_id))
    return normalize_stock_code(instrument_id)


def build_confirm_text(side, account_id, stock_code, volume, price):
    return "REAL_ORDER %s %s %s %s @ %.3f" % (
        str(side or "").upper(),
        account_id,
        stock_code,
        volume,
        price,
    )


def order_type_for_side(side):
    return STOCK_BUY if str(side or "").strip().lower() == "buy" else STOCK_SELL


def order_snapshot(order):
    fields = [
        "account_id",
        "account_type",
        "stock_code",
        "order_id",
        "order_sysid",
        "order_time",
        "order_type",
        "order_volume",
        "price",
        "traded_volume",
        "traded_price",
        "order_status",
        "status_msg",
        "strategy_name",
        "order_remark",
        "error_id",
        "error_msg",
        "m_strAccountID",
        "m_strInstrumentID",
        "m_strExchangeID",
        "m_nOrderID",
        "m_strOrderID",
        "m_strOrderSysID",
        "m_strRemark",
        "m_strOrderRemark",
        "m_strStrategyName",
        "m_nOrderStatus",
        "m_strStatus",
        "m_strStatusMsg",
        "m_nErrorID",
        "m_strErrorMsg",
    ]
    data = {}
    for field in fields:
        value = pick_value(order, field)
        if value not in (None, ""):
            data[field] = value
    derived_code = stock_code_from_obj(order)
    if derived_code:
        data.setdefault("stock_code", derived_code)
    return data


def order_id_candidates(obj):
    return [
        normalize_text(pick_value(obj, "order_id", "m_nOrderID", "m_strOrderID")),
        normalize_text(pick_value(obj, "order_sysid", "m_strOrderSysID", "sysid")),
    ]


def match_order(obj, account_id, stock_code, order_id, order_remark, allow_stock_fallback=False):
    event_account_id = normalize_text(
        pick_value(obj, "account_id", "m_strAccountID", "m_strAccountId", "m_strAccount", "m_accountID")
    )
    if event_account_id and account_id and event_account_id != account_id:
        return ""

    target_order_id = normalize_text(order_id)
    if target_order_id:
        for candidate in order_id_candidates(obj):
            if candidate and candidate == target_order_id:
                return "order_id"

    target_remark = normalize_text(order_remark)
    candidate_remark = normalize_text(pick_value(obj, "order_remark", "remark", "m_strRemark", "m_strOrderRemark"))
    if target_remark and candidate_remark == target_remark:
        return "order_remark"

    candidate_stock_code = stock_code_from_obj(obj)
    if allow_stock_fallback and candidate_stock_code and candidate_stock_code == stock_code:
        return "stock_code_fallback"
    return ""


class OrderLatencyCallback(XtQuantTraderCallback):
    def __init__(self, account_id, stock_code, order_remark, allow_stock_fallback=False):
        self.account_id = account_id
        self.stock_code = stock_code
        self.order_remark = order_remark
        self.allow_stock_fallback = bool(allow_stock_fallback)
        self.order_id = ""
        self.submit_started_at = None
        self.order_returned_at = None
        self.events = []
        self.lock = threading.RLock()
        self.changed = threading.Event()

    def mark_submit_started(self, started_at):
        with self.lock:
            self.submit_started_at = started_at
            self.events = []
            self.changed.clear()

    def mark_order_returned(self, order_id, returned_at):
        with self.lock:
            self.order_id = normalize_text(order_id)
            self.order_returned_at = returned_at
            for event in self.events:
                if event.get("latency_from_order_return_ms") is None:
                    event["latency_from_order_return_ms"] = elapsed_ms(returned_at, event["at_perf"])

    def on_stock_order(self, order):
        self._capture("on_stock_order", order)

    def on_order_error(self, order_error):
        self._capture("on_order_error", order_error)

    def on_stock_trade(self, trade):
        self._capture("on_stock_trade", trade)

    def _capture(self, event_name, data):
        now = time.perf_counter()
        with self.lock:
            if self.submit_started_at is None:
                return
            matched_by = match_order(
                data,
                self.account_id,
                self.stock_code,
                self.order_id,
                self.order_remark,
                allow_stock_fallback=self.allow_stock_fallback,
            )
            if not matched_by:
                return
            event = {
                "event": event_name,
                "matched_by": matched_by,
                "at_perf": now,
                "latency_from_submit_ms": elapsed_ms(self.submit_started_at, now),
                "latency_from_order_return_ms": (
                    elapsed_ms(self.order_returned_at, now)
                    if self.order_returned_at is not None
                    else None
                ),
                "data": order_snapshot(data),
            }
            self.events.append(event)
            self.changed.set()

    def first_event(self, event_name=None):
        with self.lock:
            for event in self.events:
                if event_name is None or event.get("event") == event_name:
                    return public_event(event)
        return None

    def wait_first(self, event_name, deadline_perf):
        while True:
            event = self.first_event(event_name)
            if event is not None:
                return event
            remaining = deadline_perf - time.perf_counter()
            if remaining <= 0:
                return None
            self.changed.wait(min(remaining, 0.05))
            self.changed.clear()

    def all_events(self):
        with self.lock:
            return [public_event(event) for event in self.events]


def public_event(event):
    data = dict(event)
    data.pop("at_perf", None)
    return data


def find_order_match(orders, account_id, stock_code, order_id, order_remark, allow_stock_fallback=False):
    for order in orders or []:
        matched_by = match_order(
            order,
            account_id,
            stock_code,
            order_id,
            order_remark,
            allow_stock_fallback=allow_stock_fallback,
        )
        if matched_by:
            return order, matched_by
    return None, ""


def query_until_order_visible(
    trader,
    account,
    account_id,
    stock_code,
    order_id,
    order_remark,
    order_started_at,
    order_returned_at,
    timeout,
    interval,
    allow_stock_fallback=False,
):
    deadline = time.perf_counter() + max(float(timeout or 0), 0.0)
    attempts = 0
    last_latency_ms = None
    last_count = 0
    last_error = ""

    while True:
        attempts += 1
        query_started = time.perf_counter()
        try:
            orders = trader.query_stock_orders(account, cancelable_only=False) or []
            query_ended = time.perf_counter()
            last_latency_ms = elapsed_ms(query_started, query_ended)
            last_count = len(orders)
            matched_order, matched_by = find_order_match(
                orders,
                account_id,
                stock_code,
                order_id,
                order_remark,
                allow_stock_fallback=allow_stock_fallback,
            )
            if matched_order is not None:
                return {
                    "ok": True,
                    "latency_from_submit_ms": elapsed_ms(order_started_at, query_ended),
                    "latency_from_order_return_ms": elapsed_ms(order_returned_at, query_ended),
                    "query_loop_latency_ms": last_latency_ms,
                    "attempts": attempts,
                    "orders_count": len(orders),
                    "matched_by": matched_by,
                    "matched_order": order_snapshot(matched_order),
                }
        except Exception as error:
            last_error = str(error)
            last_latency_ms = elapsed_ms(query_started)

        if time.perf_counter() >= deadline:
            return {
                "ok": False,
                "latency_from_submit_ms": elapsed_ms(order_started_at),
                "latency_from_order_return_ms": elapsed_ms(order_returned_at),
                "last_query_latency_ms": last_latency_ms,
                "attempts": attempts,
                "orders_count": last_count,
                "error": last_error or "order not found by order_id or order_remark",
            }
        time.sleep(max(float(interval or 0), 0.0))


def print_callback_result(callback, event_name, deadline_perf):
    event = callback.wait_first(event_name, deadline_perf)
    if event is not None:
        print_info(
            "已收到回调 %s" % event_name,
            latency_from_submit_ms=event.get("latency_from_submit_ms"),
            latency_from_order_return_ms=event.get("latency_from_order_return_ms"),
            matched_by=event.get("matched_by"),
        )
    else:
        print_info("未在超时时间内收到回调 %s" % event_name)
    print_json({
        "case": "callback_%s" % event_name,
        "ok": event is not None,
        "skipped": event is None,
        "event": event,
    })
    return event


def main():
    configure_stdout()
    config = SimpleNamespace(
        transport=TRANSPORT,
        bridge_id=BRIDGE_ID,
        timeout=REQUEST_TIMEOUT,
        account_id=ACCOUNT_ID,
        account_type=ACCOUNT_TYPE,
        stock_code=STOCK_CODE,
        side=SIDE,
        price=PRICE,
        volume=VOLUME,
        price_type=PRICE_TYPE,
        strategy_name=STRATEGY_NAME,
        order_remark=ORDER_REMARK,
        find_order_timeout=FIND_ORDER_TIMEOUT,
        callback_timeout=CALLBACK_TIMEOUT,
        query_interval=QUERY_INTERVAL,
        json=JSON_OUTPUT,
        show_transport_log=SHOW_TRANSPORT_LOG,
        dry_run=DRY_RUN,
        connect_only=CONNECT_ONLY,
        require_confirm=REQUIRE_CONFIRM,
        confirm_text=CONFIRM_TEXT,
        allow_stock_fallback=ALLOW_STOCK_FALLBACK,
    )
    global JSON_OUTPUT_ENABLED
    JSON_OUTPUT_ENABLED = bool(config.json)

    requested_transport = str(config.transport or "").strip().lower() or "auto"
    config.transport = requested_transport

    account_id = str(config.account_id or "").strip()
    account_type = str(config.account_type or "STOCK").strip().upper()
    side = str(config.side or "buy").strip().lower()
    stock_code = normalize_stock_code(config.stock_code)
    price = float(config.price or 0)
    volume = int(config.volume or 0)
    strategy_name = str(config.strategy_name or "cfquant_real_order_latency").strip()
    order_remark = str(config.order_remark or "").strip()
    if not order_remark:
        order_remark = "real_order_%s_%s" % (stock_code.replace(".", ""), int(time.time() * 1000))
    required_confirm_text = build_confirm_text(side, account_id, stock_code, volume, price)

    order_config = {
        "api": "cfquant.xttrader.XtQuantTrader.connect" if config.connect_only else "cfquant.xttrader.XtQuantTrader.order_stock",
        "account_id": account_id,
        "account_type": account_type,
        "bridge_id": config.bridge_id,
        "transport": config.transport,
        "requested_transport": requested_transport,
        "default_transport": "auto",
        "side": side,
        "stock_code": stock_code,
        "price": price,
        "volume": volume,
        "price_type": config.price_type,
        "strategy_name": strategy_name,
        "order_remark": order_remark,
        "required_confirm_text": required_confirm_text,
        "request_timeout_ms": seconds_to_ms(config.timeout),
        "find_order_timeout_ms": seconds_to_ms(config.find_order_timeout),
        "callback_timeout_ms": seconds_to_ms(config.callback_timeout),
        "query_interval_ms": seconds_to_ms(config.query_interval),
        "json_output": bool(config.json),
        "show_transport_log": bool(config.show_transport_log),
        "dry_run": bool(config.dry_run),
        "connect_only": bool(config.connect_only),
        "require_confirm": bool(config.require_confirm),
        "allow_stock_fallback": bool(config.allow_stock_fallback),
    }
    print_json({"type": "start", "order_config": order_config})
    print_info(
        "测试启动",
        api="XtQuantTrader.connect" if config.connect_only else "XtQuantTrader.order_stock",
        json_output=bool(config.json),
        show_transport_log=bool(config.show_transport_log),
        dry_run=bool(config.dry_run),
        connect_only=bool(config.connect_only),
    )
    print_info(
        "委托参数",
        account_id=account_id,
        account_type=account_type,
        side=side,
        stock_code=stock_code,
        price=price,
        volume=volume,
        strategy_name=strategy_name,
        order_remark=order_remark,
    )
    print_info(
        "计时参数",
        request_timeout_ms=seconds_to_ms(config.timeout),
        find_order_timeout_ms=seconds_to_ms(config.find_order_timeout),
        callback_timeout_ms=seconds_to_ms(config.callback_timeout),
        query_interval_ms=seconds_to_ms(config.query_interval),
    )
    if config.transport == "auto":
        print_info("通信模式使用默认 auto，将按 cfquant 运行时自动发现和账号路由选择实际链路", transport=config.transport)
    else:
        print_info("通信模式使用代码配置值", transport=config.transport)
    print_info(requested_transport_text(config.transport))

    if side not in ("buy", "sell"):
        print_info("配置校验失败：SIDE 必须为 buy 或 sell")
        print_json({"case": "validate", "ok": False, "error": "SIDE must be buy or sell"})
        return 2
    if not account_id:
        print_info("参数校验失败：资金账号为空")
        print_json({"case": "validate", "ok": False, "error": "account_id is required"})
        return 2
    if not stock_code:
        print_info("参数校验失败：证券代码为空")
        print_json({"case": "validate", "ok": False, "error": "stock_code is required"})
        return 2
    if volume <= 0:
        print_info("参数校验失败：委托数量必须大于 0")
        print_json({"case": "validate", "ok": False, "error": "volume must be positive"})
        return 2
    if price <= 0:
        print_info("参数校验失败：委托价格必须大于 0")
        print_json({"case": "validate", "ok": False, "error": "price must be positive"})
        return 2
    if config.dry_run:
        print_info("DRY_RUN = True：只打印配置，不连接也不下单")
        print_json({"case": "dry_run", "ok": True, "message": "real order was not submitted"})
        return 0
    if not config.connect_only and config.require_confirm and str(config.confirm_text or "").strip() != required_confirm_text:
        print_info("确认文本不匹配，未提交真实委托", required_confirm_text=required_confirm_text)
        print_json({
            "case": "confirmation",
            "ok": False,
            "skipped": True,
            "error": "confirmation mismatch; real order was not submitted",
            "required_confirm_text": required_confirm_text,
        })
        return 2

    configure_cfquant(config)
    account = StockAccount(account_id, account_type, config.bridge_id)
    callback = OrderLatencyCallback(
        account_id,
        stock_code,
        order_remark,
        allow_stock_fallback=config.allow_stock_fallback,
    )
    trader = XtQuantTrader(callback=callback, account=account)

    try:
        print_info("开始连接 cfquant 交易通道")
        connect_started = time.perf_counter()
        with capture_external_output() as external_logs:
            connect_result = trader.connect()
        print_external_logs("connect", external_logs, show=config.show_transport_log)
        connect_latency = elapsed_ms(connect_started)
        connection_info = client_connection_info(trader)
        print_connection_info(connection_info)
        print_info(
            "连接结果",
            ok=connect_result == 0,
            result=connect_result,
            latency_ms=connect_latency,
        )
        print_json({
            "case": "connect",
            "ok": connect_result == 0,
            "result": connect_result,
            "latency_ms": connect_latency,
            "connection": connection_info,
            "error": trader.last_connect_error,
            "error_type": trader.last_connect_error_type,
            "stage": trader.last_connect_stage,
        })
        if connect_result != 0:
            print_info(
                "连接失败，未提交委托",
                stage=trader.last_connect_stage,
                error_type=trader.last_connect_error_type,
                error=trader.last_connect_error or "未提供底层异常详情",
            )
            return 1
        if config.connect_only:
            print_info("连接检查完成，未下单、未撤单")
            print_json({"case": "connect_only", "ok": True, "order_submitted": False})
            return 0

        print_info(
            "开始调用 cfquant 下单接口",
            api="XtQuantTrader.order_stock",
            stock_code=stock_code,
            price=price,
            volume=volume,
        )
        order_started = time.perf_counter()
        callback.mark_submit_started(order_started)
        try:
            with capture_external_output() as external_logs:
                order_id = trader.order_stock(
                    account,
                    stock_code,
                    order_type_for_side(side),
                    volume,
                    config.price_type,
                    price,
                    strategy_name,
                    order_remark,
                )
            print_external_logs("order_stock", external_logs, show=config.show_transport_log)
            order_ended = time.perf_counter()
            callback.mark_order_returned(order_id, order_ended)
        except Exception as error:
            failed_at = time.perf_counter()
            print_external_logs("order_stock", external_logs, show=config.show_transport_log)
            print_info(
                "下单接口异常",
                latency_ms=elapsed_ms(order_started, failed_at),
                error_type=type(error).__name__,
                error=str(error),
            )
            print_json({
                "case": "order_stock",
                "ok": False,
                "latency_ms": elapsed_ms(order_started, failed_at),
                "error_type": type(error).__name__,
                "error": str(error),
                "order_remark": order_remark,
            })
            return 1

        order_call_latency = elapsed_ms(order_started, order_ended)
        print_info(
            "下单接口已返回",
            latency_ms=order_call_latency,
            order_id=order_id,
            order_remark=order_remark,
        )
        print_json({
            "case": "order_stock",
            "ok": normalize_text(order_id) != "",
            "latency_ms": order_call_latency,
            "order_id": order_id,
            "order_remark": order_remark,
            "strategy_name": strategy_name,
            "summary": summarize(order_id),
        })

        print_info(
            "开始轮询委托表，统计从下单发起到查询到委托的耗时",
            timeout_ms=seconds_to_ms(config.find_order_timeout),
            interval_ms=seconds_to_ms(config.query_interval),
        )
        with capture_external_output() as external_logs:
            visible = query_until_order_visible(
                trader,
                account,
                account_id,
                stock_code,
                order_id,
                order_remark,
                order_started,
                order_ended,
                config.find_order_timeout,
                config.query_interval,
                allow_stock_fallback=config.allow_stock_fallback,
            )
        print_external_logs("query_stock_orders", external_logs, show=config.show_transport_log)
        if visible.get("ok"):
            print_info(
                "委托表已查询到本次委托",
                latency_from_submit_ms=visible.get("latency_from_submit_ms"),
                latency_from_order_return_ms=visible.get("latency_from_order_return_ms"),
                attempts=visible.get("attempts"),
                matched_by=visible.get("matched_by"),
            )
        else:
            print_info(
                "委托表未在超时时间内查询到本次委托",
                latency_from_submit_ms=visible.get("latency_from_submit_ms"),
                attempts=visible.get("attempts"),
                error=visible.get("error"),
            )
        print_json({"case": "query_stock_orders_until_found", **visible})

        callback_deadline = order_started + max(float(config.callback_timeout or 0), 0.0)
        print_info("等待委托回调 on_stock_order", timeout_ms=seconds_to_ms(config.callback_timeout))
        stock_order_event = print_callback_result(callback, "on_stock_order", callback_deadline)
        order_error_event = callback.first_event("on_order_error")
        trade_event = callback.first_event("on_stock_trade")
        if order_error_event is not None:
            print_info(
                "收到下单错误回调",
                latency_from_submit_ms=order_error_event.get("latency_from_submit_ms"),
                error_msg=(order_error_event.get("data") or {}).get("error_msg") or (order_error_event.get("data") or {}).get("m_strErrorMsg"),
            )
        else:
            print_info("未收到下单错误回调")
        print_json({
            "case": "callback_on_order_error",
            "ok": order_error_event is not None,
            "skipped": order_error_event is None,
            "event": order_error_event,
        })
        if trade_event is not None:
            print_info(
                "收到成交回调",
                latency_from_submit_ms=trade_event.get("latency_from_submit_ms"),
                latency_from_order_return_ms=trade_event.get("latency_from_order_return_ms"),
            )
        else:
            print_info("未收到成交回调")
        print_json({
            "case": "callback_on_stock_trade",
            "ok": trade_event is not None,
            "skipped": trade_event is None,
            "event": trade_event,
        })

        print_info(
            "测试汇总",
            ok=bool(visible.get("ok") or stock_order_event is not None),
            order_latency_ms=order_call_latency,
            callback_from_submit_ms=stock_order_event.get("latency_from_submit_ms") if stock_order_event else None,
            query_from_submit_ms=visible.get("latency_from_submit_ms"),
            order_id=order_id,
        )
        print_json({
            "type": "summary",
            "ok": bool(visible.get("ok") or stock_order_event is not None),
            "api": "cfquant.xttrader.XtQuantTrader.order_stock",
            "order_latency_ms": order_call_latency,
            "callback_latency_from_submit_ms": (
                stock_order_event.get("latency_from_submit_ms") if stock_order_event else None
            ),
            "callback_latency_from_order_return_ms": (
                stock_order_event.get("latency_from_order_return_ms") if stock_order_event else None
            ),
            "query_latency_from_submit_ms": visible.get("latency_from_submit_ms"),
            "query_latency_from_order_return_ms": visible.get("latency_from_order_return_ms"),
            "order_id": order_id,
            "order_remark": order_remark,
            "all_matched_callback_events": callback.all_events(),
        })
        return 0 if visible.get("ok") or stock_order_event is not None else 1
    finally:
        external_logs = []
        try:
            with capture_external_output() as external_logs:
                trader.disconnect()
        except Exception:
            pass
        print_external_logs("disconnect", external_logs, show=config.show_transport_log)
        external_logs = []
        try:
            with capture_external_output() as external_logs:
                close_trade_client()
        finally:
            print_external_logs("close_trade_client", external_logs, show=config.show_transport_log)


if __name__ == "__main__":
    raise SystemExit(main())
