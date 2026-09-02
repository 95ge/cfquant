# -*- coding: utf-8 -*-
import argparse
import contextlib
import io
import json
import signal
import threading
import time
from datetime import datetime

from _helpers import configure_cfquant, configure_stdout, default_account_id, print_json as _print_json

from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback, close_trade_client
from cfquant.xttype import StockAccount


DEFAULT_TRANSPORT = "auto"
LOG_PREFIX = "【回调测试】"
JSON_OUTPUT_ENABLED = False
LOG_LOCK = threading.RLock()


def now_text():
    return datetime.now().isoformat(timespec="milliseconds")


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
    if key == "payload":
        return str(value)
    if isinstance(value, float):
        return format_log_number(value, digits=6)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    text = str(value)
    if any(char.isspace() for char in text):
        return json.dumps(text, ensure_ascii=False)
    return text


def print_info(message, **fields):
    with LOG_LOCK:
        if not fields:
            print("%s%s" % (LOG_PREFIX, message), flush=True)
            return
        parts = ["%s=%s" % (key, format_log_value(key, value)) for key, value in fields.items()]
        print("%s%s | %s" % (LOG_PREFIX, message, " ".join(parts)), flush=True)


def print_json(payload):
    if JSON_OUTPUT_ENABLED:
        with LOG_LOCK:
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
    owned_lines = []
    external_lines = []
    for stream_name, line in captured or []:
        if line.startswith(LOG_PREFIX) or (JSON_OUTPUT_ENABLED and line.startswith("{")):
            owned_lines.append(line)
        else:
            external_lines.append((stream_name, line))
    for line in owned_lines:
        with LOG_LOCK:
            print(line, flush=True)
    if not external_lines:
        return
    if not show:
        print_info("外部日志已收起", stage=stage, lines=len(external_lines), show_with="--show-transport-log")
        return
    for stream_name, line in external_lines:
        print_info("外部日志", stage=stage, stream=stream_name, line=line)


def payload_to_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {"value": value}


def pick(payload, *names):
    for name in names:
        value = payload.get(name)
        if value not in (None, ""):
            return value
    return None


def payload_json(payload, limit=0):
    text = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True, indent=2)
    if limit and len(text) > limit:
        return "%s\n... truncated,total_chars=%s" % (text[:limit], len(text))
    return text


def print_payload_block(title, event_name, seq, payload, limit=0):
    text = payload_json(payload, limit=limit)
    lines = text.splitlines() or ["{}"]
    field_count = "-"
    if isinstance(payload, dict):
        inner_payload = payload.get("payload")
        field_count = len(inner_payload) if isinstance(inner_payload, dict) else len(payload)
    with LOG_LOCK:
        print(
            "%s%s开始 | event=%s seq=%s field_count=%s"
            % (LOG_PREFIX, title, event_name, seq, field_count),
            flush=True,
        )
        for line in lines:
            print("%s%s" % (LOG_PREFIX, line), flush=True)
        print("%s%s结束 | event=%s seq=%s" % (LOG_PREFIX, title, event_name, seq), flush=True)


def event_title(event_name):
    titles = {
        "on_stock_order": "收到委托回调",
        "on_stock_trade": "收到成交回调",
        "on_order_error": "收到委托错误回调",
        "on_cancel_error": "收到撤单错误回调",
        "on_connected": "交易通道已连接",
        "on_disconnected": "交易通道已断开",
    }
    return titles.get(event_name, "收到交易回调")


def order_fields(payload):
    return {
        "account_id": pick(payload, "account_id", "m_strAccountID"),
        "stock_code": pick(payload, "stock_code", "code", "m_strInstrumentID"),
        "order_id": pick(payload, "order_id", "m_nOrderID", "m_strOrderID"),
        "order_sysid": pick(payload, "order_sysid", "m_strOrderSysID", "sysid"),
        "order_time": pick(payload, "order_time", "m_strOrderTime", "m_strEntrustTime", "m_nOrderTime"),
        "order_type": pick(payload, "order_type", "m_nOrderType", "m_nBusinessType"),
        "order_volume": pick(payload, "order_volume", "m_nOrderVolume", "m_nVolumeTotalOriginal"),
        "price": pick(payload, "price", "m_dOrderPrice", "m_dLimitPrice"),
        "traded_volume": pick(payload, "traded_volume", "m_nTradedVolume", "m_nVolumeTraded"),
        "traded_price": pick(payload, "traded_price", "m_dTradedPrice", "m_dAveragePrice"),
        "order_status": pick(payload, "order_status", "m_nOrderStatus", "m_nOrderState"),
        "status_msg": pick(payload, "status_msg", "m_strStatusMsg", "m_strStatus"),
        "strategy_name": pick(payload, "strategy_name", "m_strStrategyName"),
        "order_remark": pick(payload, "order_remark", "m_strRemark", "m_strOrderRemark"),
    }


def trade_fields(payload):
    return {
        "account_id": pick(payload, "account_id", "m_strAccountID"),
        "stock_code": pick(payload, "stock_code", "code", "m_strInstrumentID"),
        "traded_id": pick(payload, "traded_id", "trade_id", "deal_id", "m_strTradeID", "m_strDealID"),
        "traded_time": pick(payload, "traded_time", "trade_time", "deal_time", "m_strTradeTime", "m_strDealTime"),
        "order_id": pick(payload, "order_id", "m_nOrderID", "m_strOrderID"),
        "order_sysid": pick(payload, "order_sysid", "m_strOrderSysID", "sysid"),
        "order_type": pick(payload, "order_type", "m_nOrderType", "m_nBusinessType"),
        "traded_volume": pick(payload, "traded_volume", "volume", "m_nVolume", "m_nVolumeTraded"),
        "traded_price": pick(payload, "traded_price", "price", "m_dPrice", "m_dTradedPrice"),
        "traded_amount": pick(payload, "traded_amount", "trade_amount", "m_dTradeAmount", "m_dTradedAmount"),
        "strategy_name": pick(payload, "strategy_name", "m_strStrategyName"),
        "order_remark": pick(payload, "order_remark", "m_strRemark", "m_strOrderRemark"),
    }


def error_fields(payload):
    return {
        "account_id": pick(payload, "account_id", "m_strAccountID"),
        "stock_code": pick(payload, "stock_code", "code", "m_strInstrumentID"),
        "order_id": pick(payload, "order_id", "m_nOrderID", "m_strOrderID"),
        "order_sysid": pick(payload, "order_sysid", "m_strOrderSysID", "sysid"),
        "error_id": pick(payload, "error_id", "m_nErrorID", "error_code"),
        "error_msg": pick(payload, "error_msg", "m_strErrorMsg", "message", "msg"),
        "strategy_name": pick(payload, "strategy_name", "m_strStrategyName"),
        "order_remark": pick(payload, "order_remark", "m_strRemark", "m_strOrderRemark"),
    }


def event_fields(event_name, payload):
    if event_name == "on_stock_order":
        return order_fields(payload)
    if event_name == "on_stock_trade":
        return trade_fields(payload)
    if event_name in ("on_order_error", "on_cancel_error"):
        return error_fields(payload)
    return {}


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


class CallbackPrinter(XtQuantTraderCallback):
    def __init__(self, payload_limit=0):
        self.payload_limit = int(payload_limit or 0)
        self.started_perf = time.perf_counter()
        self.counts = {}
        self.lock = threading.RLock()

    def on_connected(self):
        self._emit_no_payload("on_connected")

    def on_disconnected(self):
        self._emit_no_payload("on_disconnected")

    def on_stock_order(self, order):
        self._emit_payload("on_stock_order", order)

    def on_stock_trade(self, trade):
        self._emit_payload("on_stock_trade", trade)

    def on_order_error(self, order_error):
        self._emit_payload("on_order_error", order_error)

    def on_cancel_error(self, cancel_error):
        self._emit_payload("on_cancel_error", cancel_error)

    def _next_seq(self, event_name):
        with self.lock:
            self.counts[event_name] = self.counts.get(event_name, 0) + 1
            return self.counts[event_name]

    def _base_fields(self, event_name):
        return {
            "received_at": now_text(),
            "event": event_name,
            "seq": self._next_seq(event_name),
            "uptime_ms": elapsed_ms(self.started_perf),
        }

    def _emit_no_payload(self, event_name):
        fields = self._base_fields(event_name)
        print_info(event_title(event_name), **fields)
        print_json({
            "type": "callback",
            "event": event_name,
            "received_at": fields["received_at"],
            "seq": fields["seq"],
            "uptime_ms": fields["uptime_ms"],
        })

    def _emit_payload(self, event_name, obj):
        payload = payload_to_dict(obj)
        fields = self._base_fields(event_name)
        summary = event_fields(event_name, payload)
        fields.update(summary)
        print_info(event_title(event_name), **fields)
        full_event = {
            "type": "callback",
            "event": event_name,
            "received_at": fields["received_at"],
            "seq": fields["seq"],
            "uptime_ms": fields["uptime_ms"],
            "callback_object_type": type(obj).__name__,
            "summary": summary,
            "payload": payload,
        }
        print_payload_block(
            "%s完整信息" % event_title(event_name).replace("收到", ""),
            event_name,
            fields["seq"],
            full_event,
            limit=self.payload_limit,
        )
        print_json(full_event)

    def summary(self):
        with self.lock:
            return dict(self.counts)


def requested_transport_text(transport):
    mode = str(transport or "").strip().lower()
    if mode in ("pipe", "ctypes", "named_pipe", "named-pipe"):
        return "请求通信模式：ctypes/PipeHub，本机 Python 通过 named pipe 连接 cfquant_pipe_hub。"
    if mode in ("lttx", "tx", "socket"):
        return "请求通信模式：LTtx，本机 Python 通过 LTtx 连接 QMT 交易桥。"
    if mode in ("web", "web_lttx", "lttx_web", "web-lttx", "lttx-web"):
        return "请求通信模式：Web LTtx，本机 Python 先通过 LTtx 到 Web 统一路由，再由 Web 按账号选择实际交易桥。"
    if mode == "auto":
        return "请求通信模式：auto，cfquant 会按运行时发现和账号路由选择实际链路。"
    return "请求通信模式：%s，未识别为内置说明类型。" % (transport or "")


def install_signal_handlers(stop_event):
    def handler(signum, _frame):
        print_info("收到退出信号", signal=signum, time=now_text())
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, handler)
        except Exception:
            pass


def wait_forever(stop_event, callback, heartbeat_interval=30.0, duration=0.0):
    started = time.perf_counter()
    heartbeat_interval = max(float(heartbeat_interval or 0), 0.0)
    duration = max(float(duration or 0), 0.0)
    deadline = started + duration if duration > 0 else None
    next_heartbeat = started + heartbeat_interval if heartbeat_interval > 0 else None

    while not stop_event.is_set():
        now = time.perf_counter()
        if deadline is not None and now >= deadline:
            print_info("达到运行时长，准备退出", duration_ms=seconds_to_ms(duration))
            break
        if next_heartbeat is not None and now >= next_heartbeat:
            counts = callback.summary()
            print_info(
                "连接保持中",
                time=now_text(),
                uptime_ms=elapsed_ms(started, now),
                stock_order_callbacks=counts.get("on_stock_order", 0),
                stock_trade_callbacks=counts.get("on_stock_trade", 0),
                order_error_callbacks=counts.get("on_order_error", 0),
                cancel_error_callbacks=counts.get("on_cancel_error", 0),
            )
            next_heartbeat = now + heartbeat_interval
        wait_timeout = 0.2
        if deadline is not None:
            wait_timeout = min(wait_timeout, max(deadline - now, 0.0))
        if next_heartbeat is not None:
            wait_timeout = min(wait_timeout, max(next_heartbeat - now, 0.0))
        stop_event.wait(max(wait_timeout, 0.01))


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="cfquant 交易回调监听测试；连接后常驻，收到委托/成交回调时打印内容和本地时间。")
    parser.add_argument("--transport", default=DEFAULT_TRANSPORT, help="cfquant 通信模式，默认 auto；可传 ctypes、web_lttx 或 lttx。")
    parser.add_argument("--bridge-id", default="default", help="桥接 ID，默认 default。")
    parser.add_argument("--timeout", type=float, default=15.0, help="请求超时时间，输入单位秒，输出显示为毫秒。")
    parser.add_argument("--account-id", default=default_account_id(), help="资金账号；默认读取 CFQUANT_ACCOUNT_ID 或 runtime/config/cfquant_web_config.json。")
    parser.add_argument("--account-type", default="STOCK", help="账号类型，默认 STOCK，可填 CREDIT。")
    parser.add_argument("--heartbeat-interval", type=float, default=30.0, help="心跳日志间隔，输入单位秒，输出显示为毫秒；传 0 关闭。")
    parser.add_argument("--duration", type=float, default=0.0, help="运行时长，输入单位秒，0 表示一直运行。")
    parser.add_argument("--payload-limit", type=int, default=0, help="单条回调完整内容最大打印字符数，默认 0 表示不截断。")
    parser.add_argument("--json", action="store_true", help="同时输出机器可读 JSON 行；默认只输出标准化人工日志。")
    parser.add_argument("--show-transport-log", action="store_true", help="显示 LTtx/PipeHub 等底层库原始输出；默认收起。")
    parser.add_argument("--dry-run", action="store_true", help="只打印监听配置，不连接。")
    args = parser.parse_args()

    global JSON_OUTPUT_ENABLED
    JSON_OUTPUT_ENABLED = bool(args.json)

    requested_transport = str(args.transport or "").strip().lower() or DEFAULT_TRANSPORT
    args.transport = requested_transport
    account_id = str(args.account_id or "").strip()
    account_type = str(args.account_type or "STOCK").strip().upper()

    print_json({
        "type": "start",
        "api": "cfquant.xttrader.XtQuantTrader callbacks",
        "transport": args.transport,
        "bridge_id": args.bridge_id,
        "account_id": account_id,
        "account_type": account_type,
        "request_timeout_ms": seconds_to_ms(args.timeout),
        "heartbeat_interval_ms": seconds_to_ms(args.heartbeat_interval),
        "duration_ms": seconds_to_ms(args.duration),
        "payload_limit": args.payload_limit,
        "json_output": bool(args.json),
        "show_transport_log": bool(args.show_transport_log),
        "dry_run": bool(args.dry_run),
    })
    print_info(
        "回调监听启动",
        api="XtQuantTraderCallback",
        account_id=account_id,
        account_type=account_type,
        transport=args.transport,
        bridge_id=args.bridge_id,
        payload_limit=args.payload_limit,
        json_output=bool(args.json),
        show_transport_log=bool(args.show_transport_log),
        dry_run=bool(args.dry_run),
    )
    print_info(
        "计时参数",
        request_timeout_ms=seconds_to_ms(args.timeout),
        heartbeat_interval_ms=seconds_to_ms(args.heartbeat_interval),
        duration_ms=seconds_to_ms(args.duration),
    )
    print_info(requested_transport_text(args.transport))

    if not account_id:
        print_info("参数校验失败：资金账号为空，请传 --account-id 或设置 CFQUANT_ACCOUNT_ID")
        print_json({"case": "validate", "ok": False, "error": "account_id is required"})
        return 2
    if args.dry_run:
        print_info("dry-run 模式：只打印监听配置，不连接")
        print_json({"case": "dry_run", "ok": True, "message": "callback listener was not connected"})
        return 0

    configure_cfquant(args)
    account = StockAccount(account_id, account_type, args.bridge_id)
    callback = CallbackPrinter(payload_limit=args.payload_limit)
    trader = XtQuantTrader(callback=callback, account=account)
    stop_event = threading.Event()
    install_signal_handlers(stop_event)

    try:
        print_info("开始连接 cfquant 交易通道")
        connect_started = time.perf_counter()
        with capture_external_output() as external_logs:
            connect_result = trader.connect()
        print_external_logs("connect", external_logs, show=args.show_transport_log)
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
        })
        if connect_result != 0:
            print_info("连接失败，停止监听")
            return 1

        print_info("已订阅账号交易回调，等待委托/成交事件", account_id=account_id, account_type=account_type)
        print_info("保持连接中，按 Ctrl+C 退出", time=now_text())
        wait_forever(
            stop_event,
            callback,
            heartbeat_interval=args.heartbeat_interval,
            duration=args.duration,
        )
        counts = callback.summary()
        print_info(
            "监听结束",
            stock_order_callbacks=counts.get("on_stock_order", 0),
            stock_trade_callbacks=counts.get("on_stock_trade", 0),
            order_error_callbacks=counts.get("on_order_error", 0),
            cancel_error_callbacks=counts.get("on_cancel_error", 0),
        )
        print_json({"type": "summary", "ok": True, "callback_counts": counts})
        return 0
    finally:
        external_logs = []
        try:
            with capture_external_output() as external_logs:
                trader.disconnect()
        except Exception:
            pass
        print_external_logs("disconnect", external_logs, show=args.show_transport_log)
        external_logs = []
        try:
            with capture_external_output() as external_logs:
                close_trade_client()
        finally:
            print_external_logs("close_trade_client", external_logs, show=args.show_transport_log)


if __name__ == "__main__":
    raise SystemExit(main())
