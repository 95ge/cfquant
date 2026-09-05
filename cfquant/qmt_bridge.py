# -*- coding: utf-8 -*-
import os
import queue
import sys
import threading
import time

from .config import get_config
from .logging_i18n import get_log_language, set_log_language, translate_log
from .protocol import loads_message, pack_event, pack_response
from .xttype import filter_cancelable_orders


class CfquantQmtBridge(object):
    """
    大 QMT 内置端 LTtx/TX 桥接器。

    - 大 QMT 固定订阅 request_channel。
    - 外部 cfquant 请求里携带 client_id。
    - 响应和回调事件统一推送到 client_id 对应的 LTtx 频道。
    """

    def __init__(
        self,
        context,
        ip=None,
        port=None,
        token=None,
        request_channel=None,
        show=True,
        globals_dict=None,
    ):
        cfg = get_config()
        self.context = context
        self.ip = ip or cfg["host"]
        self.port = int(port or cfg["port"])
        self.token = token or cfg["token"]
        self.request_channel = request_channel or cfg["request_channel"]
        self.show = show
        self.globals_dict = globals_dict or {}
        self.running = False
        self.tx = None
        self.connect_thread = None
        self.recv_thread = None
        self.log_lock = threading.RLock()
        self.log_file = self._default_log_file()
        self.log_queue = queue.Queue(maxsize=10000)
        self.log_thread = None
        self.main_thread_queue = queue.Queue(maxsize=10000)
        self.subscriptions = {}
        self.client_subscriptions = {}
        self.auto_trade_callback_enabled = False

    def start(self):
        if self.running:
            return self
        self.running = True
        self._start_log_thread()
        self._enable_auto_trade_callback()
        self.connect_thread = threading.Thread(target=self._connect_loop)
        self.connect_thread.daemon = True
        self.connect_thread.start()
        self._log(
            "cfquant QMT TX桥接已启动，LTtx=%s:%s request_channel=%s"
            % (self.ip, self.port, self.request_channel)
        )
        self._log("cfquant QMT桥接文件日志:%s" % self.log_file)
        return self

    def set_context(self, context):
        self.context = context
        self._enable_auto_trade_callback()
        self._log("cfquant context poll loop started")
        while self.running:
            self.poll(max_messages=100)
            time.sleep(0.001)
        self._log("cfquant桥接ContextInfo已绑定")

    def close(self):
        self.running = False
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.Q.put(None)
            except Exception:
                pass
            try:
                tx.close()
            except Exception:
                pass
        self._log("cfquant QMT TX桥接已关闭")

    def poll(self, max_messages=20):
        count = 0
        while count < max_messages:
            try:
                raw, received_at = self.main_thread_queue.get_nowait()
            except queue.Empty:
                break
            self._process_and_reply(raw, received_at, qmt_thread=True)
            count += 1
        return count

    def _connect_loop(self):
        while self.running:
            tx = None
            try:
                txl = self._load_txl()
                tx = txl(self.ip, self.port, self.token)
                tx.start_tx()
                tx.start_txg(self.request_channel)
                self.tx = tx
                self._log("cfquant QMT桥接已订阅请求频道:%s" % self.request_channel)
                self._recv_loop(tx)
            except Exception as e:
                if self.running:
                    self._log("cfquant QMT TX桥接连接异常:%s，1秒后重试" % e)
                    time.sleep(1)
            finally:
                if self.tx is tx:
                    self.tx = None
                if tx is not None:
                    try:
                        tx.close()
                    except Exception:
                        pass

    def _recv_loop(self, tx):
        while self.running and self.tx is tx:
            try:
                raw = tx.Q.get()
                if raw is None:
                    break
                received_at = time.perf_counter()
                self._log("stage=request_dequeued raw=%s" % self._brief(raw))
                self._process_and_reply(raw, received_at)
            except Exception as e:
                if self.running:
                    self._log("cfquant接收请求异常:%s" % e)
                time.sleep(0.05)

    def _process_and_reply(self, raw, received_at, qmt_thread=False):
        parse_start = time.perf_counter()
        msg = loads_message(raw)
        parse_ms = self._elapsed_ms(parse_start)
        if not msg:
            self._log("stage=parse_invalid parse_ms=%.2f raw=%s" % (parse_ms, self._brief(raw)))
            return
        if msg.get("type") != "request":
            self._log("cfquant桥接忽略消息 type=%s" % msg.get("type"))
            return
        client_id = msg.get("client_id")
        request_id = msg.get("id")
        action = msg.get("action")
        if not qmt_thread and self._requires_qmt_thread(action):
            try:
                self.main_thread_queue.put_nowait((raw, received_at))
                self._log("stage=request_enqueued_qmt_thread action=%s id=%s" % (action, request_id))
            except queue.Full as e:
                if client_id:
                    response = pack_response(request_id, ok=False, error=e)
                    self._push("response", response, client_id)
            return
        response = self._handle_request(msg, received_at, parse_ms)
        if not client_id:
            self._log("cfquant请求缺少client_id，无法回包 action=%s id=%s" % (action, request_id))
            return
        self._push("response", response, client_id)
        self._log(
            "stage=response_sent action=%s id=%s client_id=%s total_ms=%.2f"
            % (action, request_id, client_id, self._elapsed_ms(received_at))
        )

    def _requires_qmt_thread(self, action):
        return action in {
            "xttrader.query_stock_asset",
            "xttrader.query_stock_orders",
            "xttrader.query_stock_trades",
            "xttrader.query_stock_positions",
            "xttrader.order_stock",
            "xttrader.order_stock_async",
            "xttrader.cancel_order_stock",
            "xttrader.cancel_order_stock_async",
        }

    def _handle_request(self, msg, received_at=None, parse_ms=0.0):
        request_id = msg.get("id")
        action = msg.get("action")
        dispatch_ms = 0.0
        try:
            self._log(
                "stage=request_received action=%s id=%s parse_ms=%.2f params=%s"
                % (action, request_id, parse_ms, self._brief(msg.get("params") or {}))
            )
            dispatch_start = time.perf_counter()
            result = self._dispatch(action, msg.get("params") or {}, msg)
            dispatch_ms = self._elapsed_ms(dispatch_start)
            response = pack_response(request_id, ok=True, result=result)
            self._log(
                "stage=response_ready action=%s id=%s dispatch_ms=%.2f result=%s"
                % (action, request_id, dispatch_ms, self._brief(result))
            )
            return response
        except Exception as e:
            self._log("cfquant桥接命令处理失败 action=%s id=%s error=%s" % (action, request_id, e))
            return pack_response(request_id, ok=False, error=e)

    def _dispatch(self, action, params, msg):
        if action == "cfquant.ping":
            return {"pong": True, "ts": time.time(), "request_channel": self.request_channel}
        if action == "cfquant.set_log_language":
            lang = set_log_language(params.get("language") or params.get("lang"))
            self._log("QMT日志语言已切换为:%s" % ("中文" if lang == "zh" else "English"))
            return {"language": lang}
        if action == "cfquant.get_log_language":
            return {"language": get_log_language()}
        if action == "cfquant.status":
            return {
                "bridge": type(self).__name__,
                "running": self.running,
                "request_channel": self.request_channel,
                "log_language": get_log_language(),
                "context_ready": self.context is not None,
                "tx_ready": self.tx is not None,
                "subscriptions": len(self.subscriptions),
                "ts": time.time(),
            }
        if self.context is None:
            raise RuntimeError("QMT ContextInfo尚未绑定")
        if action == "xtdata.get_market_data":
            return self._get_market_data(params)
        if action == "xtdata.get_market_data_ex":
            return self._get_market_data_ex(params)
        if action == "xtdata.get_full_tick":
            return self.context.get_full_tick(params.get("code_list", []))
        if action == "xtdata.subscribe_quote":
            return self._subscribe_quote(params, msg)
        if action == "xtdata.subscribe_whole_quote":
            return self._subscribe_whole_quote(params, msg)
        if action == "xtdata.unsubscribe_quote":
            return self._unsubscribe_quote(params)
        if action == "xtdata.download_history_data":
            return self._download_history_data(params, msg)
        if action == "xtdata.download_history_data2":
            return self._download_history_data2(params, msg)
        if action == "xtdata.get_instrument_detail":
            return self._get_instrument_detail(params)
        if action == "xtdata.get_stock_list_in_sector":
            return self.context.get_stock_list_in_sector(params.get("sector_name", ""))
        if action == "xttrader.subscribe":
            return 0
        if action == "xttrader.unsubscribe":
            return 0
        if action == "xttrader.order_stock":
            return self._order_stock(params)
        if action == "xttrader.order_stock_async":
            return self._order_stock_async(params, msg)
        if action == "xttrader.cancel_order_stock":
            return self._cancel_order_stock(params)
        if action == "xttrader.cancel_order_stock_async":
            return self._cancel_order_stock_async(params, msg)
        if action == "xttrader.query_stock_asset":
            return self._query_trade_detail(params, "ACCOUNT")
        if action == "xttrader.query_stock_orders":
            return self._query_trade_detail(params, "ORDER")
        if action == "xttrader.query_stock_trades":
            return self._query_trade_detail(params, "DEAL")
        if action == "xttrader.query_stock_positions":
            return self._query_trade_detail(params, "POSITION")
        raise ValueError("暂不支持的cfquant动作:%s" % action)

    def _get_market_data(self, params):
        func = getattr(self.context, "get_market_data", None)
        if not func:
            return self._get_market_data_ex(params)
        return func(
            params.get("field_list", []),
            params.get("stock_list", []),
            params.get("start_time", ""),
            params.get("end_time", ""),
            params.get("skip_paused", params.get("fill_data", True)),
            params.get("period", "1d"),
            params.get("dividend_type", "none"),
            params.get("count", -1),
        )

    def _get_market_data_ex(self, params):
        return self.context.get_market_data_ex(
            params.get("field_list", []),
            params.get("stock_list", []),
            params.get("period", "1d"),
            params.get("start_time", ""),
            params.get("end_time", ""),
            params.get("count", -1),
            params.get("dividend_type", "none"),
            params.get("fill_data", True),
        )

    def _subscribe_quote(self, params, msg):
        stock_code = params.get("stock_code", "")
        period = params.get("period", "1d")
        dividend_type = params.get("dividend_type") or "none"
        client_id = msg.get("client_id")
        holder = {"id": None}

        def callback(data):
            subscribe_id = holder.get("id")
            event = pack_event(
                "quote:%s" % subscribe_id,
                data=data,
                client_id=client_id,
                subscription_id=subscribe_id,
            )
            self._push("event", event, client_id)

        func = getattr(self.context, "subscribe_quote")
        subscribe_id = self._call_variants(
            func,
            [
                ((stock_code, period, dividend_type, "", callback), {}),
                ((stock_code, period, params.get("start_time", ""), params.get("end_time", ""), params.get("count", 0), callback), {}),
                ((stock_code, period, callback), {}),
            ],
        )
        holder["id"] = subscribe_id
        self._remember_subscription(subscribe_id, client_id, "quote", params)
        return {"subscribe_id": subscribe_id}

    def _subscribe_whole_quote(self, params, msg):
        code_list = params.get("code_list", params.get("stock_list", []))
        client_id = msg.get("client_id")
        holder = {"id": None}

        def callback(data):
            subscribe_id = holder.get("id")
            event = pack_event(
                "quote:%s" % subscribe_id,
                data=data,
                client_id=client_id,
                subscription_id=subscribe_id,
            )
            self._push("event", event, client_id)

        func = getattr(self.context, "subscribe_whole_quote")
        subscribe_id = self._call_variants(
            func,
            [
                ((code_list,), {"callback": callback}),
                ((code_list, callback), {}),
            ],
        )
        holder["id"] = subscribe_id
        self._remember_subscription(subscribe_id, client_id, "whole_quote", params)
        return {"subscribe_id": subscribe_id}

    def _remember_subscription(self, subscribe_id, client_id, kind, params):
        self.subscriptions[subscribe_id] = {
            "client_id": client_id,
            "kind": kind,
            "params": params,
        }
        self.client_subscriptions.setdefault(client_id, set()).add(subscribe_id)

    def _unsubscribe_quote(self, params):
        subscribe_id = params.get("subscribe_id")
        try:
            func = getattr(self.context, "unsubscribe_quote")
            result = func(subscribe_id)
        finally:
            info = self.subscriptions.pop(subscribe_id, None)
            if info:
                client_id = info.get("client_id")
                if client_id in self.client_subscriptions:
                    self.client_subscriptions[client_id].discard(subscribe_id)
        return result

    def _download_event_meta(self, params, kind, stage):
        meta = {
            "download": True,
            "download_kind": kind,
            "stage": stage,
            "bridge_id": getattr(self, "bridge_id", "default"),
        }
        job_id = params.get("download_job_id") or params.get("job_id")
        if job_id:
            meta["job_id"] = str(job_id)
        for name in ("stock_code", "period", "start_time", "end_time"):
            value = params.get(name)
            if value not in (None, ""):
                meta[name] = value
        for name in ("stock_list", "code_list", "table_list"):
            value = params.get(name)
            if value:
                meta[name] = value
        return meta

    def _send_download_event(self, client_id, params, kind, stage, data=None):
        callback_event = params.get("callback_event")
        if not callback_event or not client_id:
            return
        self._send_event(
            client_id,
            callback_event,
            data if data is not None else {},
            meta=self._download_event_meta(params, kind, stage),
        )

    def _download_history_data(self, params, msg=None):
        client_id = msg.get("client_id") if msg else None
        emit_lifecycle = bool(params.get("download_emit_lifecycle"))
        func = self._get_callable("download_history_data", "down_history_data")
        if not func:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": "当前QMT内置ContextInfo未提供download_history_data",
                })
            raise NotImplementedError("当前QMT内置ContextInfo未提供download_history_data")
        variants = []
        incrementally = params.get("incrementally")
        if incrementally is not None:
            variants.append((
                (
                    params.get("stock_code", ""),
                    params.get("period", "1d"),
                    params.get("start_time", ""),
                    params.get("end_time", ""),
                    incrementally,
                ),
                {},
            ))
        variants.append((
            (
                params.get("stock_code", ""),
                params.get("period", "1d"),
                params.get("start_time", ""),
                params.get("end_time", ""),
            ),
            {},
        ))
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "submitted", {
                "stage": "submitted",
                "message": "history download request submitted",
            })
        try:
            result = self._call_variants(func, variants)
        except Exception as e:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": str(e),
                })
            raise
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "request_done", {
                "stage": "request_done",
                "result": result,
            })
        return result

    def _download_history_data2(self, params, msg):
        client_id = msg.get("client_id")
        callback_event = params.get("callback_event")
        emit_lifecycle = bool(params.get("download_emit_lifecycle"))
        func = self._get_callable("download_history_data2", "down_history_data2")
        if not func:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": "当前QMT环境未提供download_history_data2",
                })
            raise NotImplementedError("当前QMT环境未提供download_history_data2")

        def callback(data):
            if callback_event and client_id:
                self._send_event(
                    client_id,
                    callback_event,
                    data,
                    meta=self._download_event_meta(params, "history", "progress"),
                )

        callback_func = callback if callback_event else None
        variants = []
        incrementally = params.get("incrementally")
        if incrementally is not None:
            variants.append((
                (
                    params.get("stock_list", params.get("code_list", [])),
                    params.get("period", "1d"),
                    params.get("start_time", ""),
                    params.get("end_time", ""),
                    callback_func,
                    incrementally,
                ),
                {},
            ))
        variants.append((
            (
                params.get("stock_list", params.get("code_list", [])),
                params.get("period", "1d"),
                params.get("start_time", ""),
                params.get("end_time", ""),
                callback_func,
            ),
            {},
        ))
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "submitted", {
                "stage": "submitted",
                "message": "history download request submitted",
            })
        try:
            result = self._call_variants(func, variants)
        except Exception as e:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": str(e),
                })
            raise
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "request_done", {
                "stage": "request_done",
                "result": result,
            })
        return result

    def _get_instrument_detail(self, params):
        func = getattr(self.context, "get_instrument_detail")
        return func(params.get("stock_code", ""))

    def _passorder_optype(self, params, account_type):
        qmt_optype = self._first_param(params, ("qmt_optype", "passorder_optype"))
        if qmt_optype is not None:
            return self._coerce_optype(qmt_optype)
        account_type_text = str(account_type or "").strip().upper()
        credit_action_names = ("credit_action", "credit_business")
        if account_type_text == "CREDIT":
            credit_action_names += ("order_action", "business_type", "action")
        credit_action = self._first_param(params, credit_action_names)
        if credit_action is not None:
            return self._credit_action_optype(credit_action)
        derivative_action = self._first_param(params, (
            "future_action",
            "future_business",
            "stock_option_action",
            "future_option_action",
            "option_action",
            "option_business",
            "derivative_action",
            "business_type",
            "order_action",
            "action",
        ))
        if derivative_action is not None:
            return self._derivative_action_optype(account_type_text, derivative_action)
        order_type = params.get("optype", params.get("order_type"))
        if isinstance(order_type, str):
            text = order_type.strip().lower()
            if text in ("buy", "stock_buy"):
                return 33 if account_type_text == "CREDIT" else 23
            if text in ("sell", "stock_sell"):
                return 34 if account_type_text == "CREDIT" else 24
            if text in self._credit_action_optype_map():
                return self._credit_action_optype(text)
            if account_type_text in ("FUTURE", "FUTURE_OPTION", "STOCK_OPTION"):
                return self._derivative_action_optype(account_type_text, text)
        order_type = self._coerce_optype(order_type)
        if order_type is None:
            raise ValueError("order_type is required")
        return self._qmt_account_optype(order_type, account_type_text)

    def _coerce_optype(self, value):
        if isinstance(value, str):
            text = value.strip()
            if text.lstrip("+-").isdigit():
                return int(text)
        return value

    def _credit_action_optype(self, value):
        text = str(value or "").strip().lower()
        key = text if text.startswith("credit_") else self._credit_action_aliases().get(text) or "credit_%s" % text
        actions = self._credit_action_optype_map()
        if key not in actions:
            raise ValueError("unknown credit order action: %s" % value)
        return actions[key]

    def _qmt_credit_optype(self, order_type):
        mapping = {
            23: 33,
            24: 34,
            40: 70,
            41: 71,
            42: 72,
            43: 73,
            44: 74,
            45: 75,
        }
        return mapping.get(order_type, order_type)

    def _qmt_stock_option_optype(self, order_type):
        mapping = {
            48: 50,
            49: 51,
            50: 52,
            51: 53,
            52: 54,
            53: 55,
            54: 56,
            55: 57,
            56: 58,
            57: 59,
        }
        return mapping.get(order_type, order_type)

    def _qmt_account_optype(self, order_type, account_type):
        account_type = str(account_type or "").strip().upper()
        if account_type == "CREDIT":
            return self._qmt_credit_optype(order_type)
        if account_type == "STOCK_OPTION":
            return self._qmt_stock_option_optype(order_type)
        return order_type

    def _derivative_action_optype(self, account_type, value):
        account_type = str(account_type or "").strip().upper()
        coerced = self._coerce_optype(value)
        if isinstance(coerced, int):
            return self._qmt_account_optype(coerced, account_type)
        text = str(value or "").strip().lower()
        if account_type in ("FUTURE", "FUTURE_OPTION"):
            aliases = self._future_action_aliases()
            actions = self._future_action_optype_map()
            if account_type == "FUTURE_OPTION":
                actions = dict(actions, **self._future_option_action_optype_map())
            key = text if text in actions else aliases.get(text)
            if key is None and not text.startswith("future_") and ("future_%s" % text) in actions:
                key = "future_%s" % text
            if key in actions:
                return actions[key]
        if account_type == "STOCK_OPTION":
            aliases = self._stock_option_action_aliases()
            actions = self._stock_option_action_optype_map()
            key = text if text in actions else aliases.get(text)
            if key is None and not text.startswith("stock_option_") and ("stock_option_%s" % text) in actions:
                key = "stock_option_%s" % text
            if key in actions:
                return actions[key]
        raise ValueError("unknown %s order action: %s" % (account_type or "derivative", value))

    def _credit_action_aliases(self):
        return {
            "buy": "credit_buy",
            "collateral_buy": "credit_buy",
            "assure_buy": "credit_buy",
            "sell": "credit_sell",
            "collateral_sell": "credit_sell",
            "assure_sell": "credit_sell",
            "fin_buy": "credit_fin_buy",
            "finance_buy": "credit_fin_buy",
            "margin_buy": "credit_fin_buy",
            "slo_sell": "credit_slo_sell",
            "short_sell": "credit_slo_sell",
            "buy_secu_repay": "credit_buy_secu_repay",
            "buy_security_repay": "credit_buy_secu_repay",
            "direct_secu_repay": "credit_direct_secu_repay",
            "direct_security_repay": "credit_direct_secu_repay",
            "sell_secu_repay": "credit_sell_secu_repay",
            "sell_security_repay": "credit_sell_secu_repay",
            "direct_cash_repay": "credit_direct_cash_repay",
            "cash_repay": "credit_direct_cash_repay",
            "fin_buy_special": "credit_fin_buy_special",
            "finance_buy_special": "credit_fin_buy_special",
            "margin_buy_special": "credit_fin_buy_special",
            "slo_sell_special": "credit_slo_sell_special",
            "short_sell_special": "credit_slo_sell_special",
            "buy_secu_repay_special": "credit_buy_secu_repay_special",
            "direct_secu_repay_special": "credit_direct_secu_repay_special",
            "sell_secu_repay_special": "credit_sell_secu_repay_special",
            "direct_cash_repay_special": "credit_direct_cash_repay_special",
        }

    def _credit_action_optype_map(self):
        return {
            "credit_buy": 33,
            "credit_sell": 34,
            "credit_fin_buy": 27,
            "credit_slo_sell": 28,
            "credit_buy_secu_repay": 29,
            "credit_direct_secu_repay": 30,
            "credit_sell_secu_repay": 31,
            "credit_direct_cash_repay": 32,
            "credit_fin_buy_special": 70,
            "credit_slo_sell_special": 71,
            "credit_buy_secu_repay_special": 72,
            "credit_direct_secu_repay_special": 73,
            "credit_sell_secu_repay_special": 74,
            "credit_direct_cash_repay_special": 75,
        }

    def _future_action_aliases(self):
        return {
            "open_long": "future_open_long",
            "buy_open": "future_open_long",
            "close_long": "future_close_long_history_first",
            "sell_close": "future_close_long_history_first",
            "close_long_history": "future_close_long_history",
            "close_long_today": "future_close_long_today",
            "open_short": "future_open_short",
            "sell_open": "future_open_short",
            "close_short": "future_close_short_history_first",
            "buy_close": "future_close_short_history_first",
            "close_short_history": "future_close_short_history",
            "close_short_today": "future_close_short_today",
            "open": "future_open",
            "close": "future_close",
            "exercise": "future_option_exercise",
            "future_option_exercise": "future_option_exercise",
            "option_future_option_exercise": "future_option_exercise",
        }

    def _future_action_optype_map(self):
        return {
            "future_open_long": 0,
            "future_close_long_history": 1,
            "future_close_long_today": 2,
            "future_open_short": 3,
            "future_close_short_history": 4,
            "future_close_short_today": 5,
            "future_close_long_today_first": 6,
            "future_close_long_history_first": 7,
            "future_close_short_today_first": 8,
            "future_close_short_history_first": 9,
            "future_close_long_today_history_then_open_short": 10,
            "future_close_long_history_today_then_open_short": 11,
            "future_close_short_today_history_then_open_long": 12,
            "future_close_short_history_today_then_open_long": 13,
            "future_open": 14,
            "future_close": 15,
            "future_arbitrage_open": 16,
            "future_arbitrage_close_history_first": 17,
            "future_arbitrage_close_today_first": 18,
            "future_renew_long_close_history_first": 19,
            "future_renew_long_close_today_first": 20,
            "future_renew_short_close_history_first": 21,
            "future_renew_short_close_today_first": 22,
            "future_hedge": 400,
        }

    def _future_option_action_optype_map(self):
        return {
            "future_option_exercise": 100,
        }

    def _stock_option_action_aliases(self):
        return {
            "buy_open": "stock_option_buy_open",
            "open_long": "stock_option_buy_open",
            "sell_close": "stock_option_sell_close",
            "close_long": "stock_option_sell_close",
            "sell_open": "stock_option_sell_open",
            "open_short": "stock_option_sell_open",
            "buy_close": "stock_option_buy_close",
            "close_short": "stock_option_buy_close",
            "covered_open": "stock_option_covered_open",
            "covered_close": "stock_option_covered_close",
            "call_exercise": "stock_option_call_exercise",
            "put_exercise": "stock_option_put_exercise",
            "secu_lock": "stock_option_secu_lock",
            "secu_unlock": "stock_option_secu_unlock",
            "lock": "stock_option_secu_lock",
            "unlock": "stock_option_secu_unlock",
        }

    def _stock_option_action_optype_map(self):
        return {
            "stock_option_buy_open": 50,
            "stock_option_sell_close": 51,
            "stock_option_sell_open": 52,
            "stock_option_buy_close": 53,
            "stock_option_covered_open": 54,
            "stock_option_covered_close": 55,
            "stock_option_call_exercise": 56,
            "stock_option_put_exercise": 57,
            "stock_option_secu_lock": 58,
            "stock_option_secu_unlock": 59,
        }

    def _order_stock(self, params):
        account = params.get("account") or {}
        account_id = account.get("account_id", "")
        account_type = self._account_type_name(account.get("account_type"))
        order_type = self._passorder_optype(params, account_type)
        user_order_id = self._first_param(
            params,
            ("order_remark", "remark", "strategy_name"),
            "cfquant_%s" % int(time.time() * 1000),
        )
        args = (
            order_type,
            params.get("qmt_order_type", 1101),
            account_id,
            params.get("stock_code", ""),
            params.get("price_type"),
            params.get("price"),
            params.get("order_volume"),
            params.get("strategy_name", ""),
            params.get("quick_trade", 2),
            user_order_id,
        )
        passorder = getattr(self.context, "passorder", None) or self._get_global_func("passorder")
        if passorder is None:
            raise NotImplementedError("当前QMT环境未找到passorder函数")
        try:
            result = passorder(*args, self.context)
        except TypeError:
            result = passorder(*args)
        order_id = result if isinstance(result, (int, str)) else None
        if order_id is None:
            order_id = self._find_order_id(
                account_id,
                account_type,
                user_order_id,
                params.get("strategy_name", ""),
                params.get("find_order_wait", 0.3),
            )
        return {
            "order_id": order_id if order_id is not None else -1,
            "request_result": result,
            "order_remark": user_order_id,
            "order_type": order_type,
            "account_type": str(account_type or "").upper(),
        }

    def _order_stock_async(self, params, msg):
        seq = params.get("seq")
        client_id = msg.get("client_id")
        try:
            result = self._order_stock(params)
            data = dict(result)
            data.update({
                "seq": seq,
                "account_id": (params.get("account") or {}).get("account_id", ""),
                "strategy_name": params.get("strategy_name", ""),
                "order_remark": result.get("order_remark", params.get("order_remark", "")),
            })
            self._send_trader_event(client_id, "on_order_stock_async_response", data)
            return {"seq": seq, "request_result": result}
        except Exception as e:
            data = {
                "seq": seq,
                "account_id": (params.get("account") or {}).get("account_id", ""),
                "order_id": -1,
                "error_msg": str(e),
            }
            self._send_trader_event(client_id, "on_order_stock_async_response", data)
            raise

    def _cancel_order_stock(self, params):
        cancel_func = self._get_global_func("cancel")
        if cancel_func is None:
            raise NotImplementedError("当前QMT环境未找到cancel函数，暂不能撤单")
        account = params.get("account") or {}
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        result = cancel_func(str(params.get("order_id")), account.get("account_id", ""), account_type, self.context)
        return {"cancel_result": 0 if result else -1, "request_result": result, "account_type": str(account_type or "").upper()}

    def _cancel_order_stock_async(self, params, msg):
        seq = params.get("seq")
        client_id = msg.get("client_id")
        result = self._cancel_order_stock(params)
        data = dict(result)
        data.update({
            "seq": seq,
            "account_id": (params.get("account") or {}).get("account_id", ""),
            "order_id": params.get("order_id"),
        })
        self._send_trader_event(client_id, "on_cancel_order_stock_async_response", data)
        return {"seq": seq, "request_result": result}

    def _query_trade_detail(self, params, datatype):
        account = params.get("account") or {}
        func = self._get_global_func("get_trade_detail_data")
        if not func and hasattr(self.context, "get_trade_detail_data"):
            func = self.context.get_trade_detail_data
        if not func:
            raise NotImplementedError("当前QMT环境未找到get_trade_detail_data函数")
        result = self._call_trade_detail_data(
            func,
            account.get("account_id", ""),
            self._account_type_name(account.get("account_type")).lower(),
            str(datatype).lower(),
        )
        rows = self._format_trade_detail_rows(result, datatype)
        if str(datatype).upper() == "ORDER" and self._truthy_param(params.get("cancelable_only")):
            rows = filter_cancelable_orders(rows)
        return rows

    def _call_trade_detail_data(self, func, account_id, account_type, datatype):
        # QMT's fourth argument is strategyname, not ContextInfo.
        variants = [
            ((account_id, account_type, datatype), {}),
            ((account_id, account_type, datatype, ""), {}),
        ]
        last_error = None
        for args, kwargs in variants:
            try:
                return func(*args, **kwargs)
            except TypeError as e:
                last_error = e
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("no available trade detail call variant")

    def _format_trade_detail_rows(self, rows, datatype):
        datatype = str(datatype).upper()
        rows = rows or []
        return [self._format_trade_detail(row, datatype) for row in rows]

    def _format_trade_detail(self, obj, datatype):
        if datatype == "ORDER":
            return {
                "stock_code": self._stock_code_from_trade_obj(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "order_source": self._order_source(obj),
                "order_type": self._first_value(obj, ("m_nOrderType", "m_nBusinessType")),
                "order_time": self._first_value(obj, (
                    "order_time",
                    "entrust_time",
                    "insert_time",
                    "m_strOrderTime",
                    "m_strEntrustTime",
                    "m_strInsertTime",
                    "m_nOrderTime",
                    "m_nEntrustTime",
                    "m_nInsertTime",
                )),
                "order_date": self._first_value(obj, (
                    "order_date",
                    "entrust_date",
                    "m_strOrderDate",
                    "m_strEntrustDate",
                    "m_strTradingDay",
                    "m_nOrderDate",
                    "m_nEntrustDate",
                )),
                "direction": self._get_value(obj, "m_nDirection"),
                "offset_flag": self._get_value(obj, "m_nOffsetFlag"),
                "order_volume": self._get_value(obj, "m_nVolumeTotalOriginal"),
                "price_type": self._first_value(obj, ("m_nPriceType", "m_nOrderPriceType")),
                "price": self._first_value(obj, ("m_dLimitPrice", "m_dOrderPrice", "m_dPrice")),
                "traded_price": self._get_value(obj, "m_dTradedPrice"),
                "traded_volume": self._get_value(obj, "m_nVolumeTraded"),
                "trade_amount": self._get_value(obj, "m_dTradeAmount"),
                "order_status": self._get_value(obj, "m_nOrderStatus"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nOrderType": self._get_value(obj, "m_nOrderType"),
                "m_nBusinessType": self._get_value(obj, "m_nBusinessType"),
                "m_nDirection": self._get_value(obj, "m_nDirection"),
                "m_nOffsetFlag": self._get_value(obj, "m_nOffsetFlag"),
                "m_nVolumeTotalOriginal": self._get_value(obj, "m_nVolumeTotalOriginal"),
                "m_nPriceType": self._get_value(obj, "m_nPriceType"),
                "m_nOrderPriceType": self._get_value(obj, "m_nOrderPriceType"),
                "m_dLimitPrice": self._get_value(obj, "m_dLimitPrice"),
                "m_dOrderPrice": self._get_value(obj, "m_dOrderPrice"),
                "m_dPrice": self._get_value(obj, "m_dPrice"),
                "m_dTradedPrice": self._get_value(obj, "m_dTradedPrice"),
                "m_nVolumeTraded": self._get_value(obj, "m_nVolumeTraded"),
                "m_dTradeAmount": self._get_value(obj, "m_dTradeAmount"),
                "m_strRemark": self._get_value(obj, "m_strRemark"),
                "m_strStrategyName": self._get_value(obj, "m_strStrategyName"),
                "m_strOrderSysID": self._get_value(obj, "m_strOrderSysID"),
                "m_nOrderID": self._get_value(obj, "m_nOrderID"),
                "m_strOrderID": self._get_value(obj, "m_strOrderID"),
                "m_nOrderStatus": self._get_value(obj, "m_nOrderStatus"),
                "m_strOrderStatus": self._get_value(obj, "m_strOrderStatus"),
                "m_nOrderState": self._get_value(obj, "m_nOrderState"),
                "m_strStatus": self._get_value(obj, "m_strStatus"),
                "m_strOrderTime": self._get_value(obj, "m_strOrderTime"),
                "m_strEntrustTime": self._get_value(obj, "m_strEntrustTime"),
                "m_strInsertTime": self._get_value(obj, "m_strInsertTime"),
                "m_nOrderTime": self._get_value(obj, "m_nOrderTime"),
                "m_nEntrustTime": self._get_value(obj, "m_nEntrustTime"),
                "m_nInsertTime": self._get_value(obj, "m_nInsertTime"),
                "m_strOrderDate": self._get_value(obj, "m_strOrderDate"),
                "m_strEntrustDate": self._get_value(obj, "m_strEntrustDate"),
                "m_strTradingDay": self._get_value(obj, "m_strTradingDay"),
            }
        if datatype == "DEAL":
            return {
                "stock_code": self._stock_code_from_trade_obj(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "order_type": self._first_value(obj, ("m_nOrderType", "m_nBusinessType")),
                "direction": self._get_value(obj, "m_nDirection"),
                "offset_flag": self._get_value(obj, "m_nOffsetFlag"),
                "price": self._get_value(obj, "m_dPrice"),
                "volume": self._get_value(obj, "m_nVolume"),
                "trade_amount": self._get_value(obj, "m_dTradeAmount"),
                "commission": self._get_value(obj, "m_dCommission"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nOrderType": self._get_value(obj, "m_nOrderType"),
                "m_nBusinessType": self._get_value(obj, "m_nBusinessType"),
                "m_nDirection": self._get_value(obj, "m_nDirection"),
                "m_nOffsetFlag": self._get_value(obj, "m_nOffsetFlag"),
                "m_dPrice": self._get_value(obj, "m_dPrice"),
                "m_nVolume": self._get_value(obj, "m_nVolume"),
                "m_dTradeAmount": self._get_value(obj, "m_dTradeAmount"),
                "m_dCommission": self._get_value(obj, "m_dCommission"),
            }
        if datatype == "POSITION":
            return {
                "stock_code": self._stock_code_from_trade_obj(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "volume": self._get_value(obj, "m_nVolume"),
                "can_use_volume": self._get_value(obj, "m_nCanUseVolume"),
                "open_price": self._get_value(obj, "m_dOpenPrice"),
                "market_value": self._get_value(obj, "m_dInstrumentValue"),
                "position_cost": self._get_value(obj, "m_dPositionCost"),
                "position_profit": self._get_value(obj, "m_dPositionProfit"),
                "direction": self._get_value(obj, "m_nDirection"),
                "frozen_volume": self._get_value(obj, "m_nFrozenVolume"),
                "on_road_volume": self._get_value(obj, "m_nOnRoadVolume"),
                "yesterday_volume": self._get_value(obj, "m_nYesterdayVolume"),
                "last_price": self._get_value(obj, "m_dLastPrice"),
                "profit_rate": self._get_value(obj, "m_dProfitRate"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nDirection": self._get_value(obj, "m_nDirection"),
                "m_nVolume": self._get_value(obj, "m_nVolume"),
                "m_nCanUseVolume": self._get_value(obj, "m_nCanUseVolume"),
                "m_nFrozenVolume": self._get_value(obj, "m_nFrozenVolume"),
                "m_nOnRoadVolume": self._get_value(obj, "m_nOnRoadVolume"),
                "m_nYesterdayVolume": self._get_value(obj, "m_nYesterdayVolume"),
                "m_dOpenPrice": self._get_value(obj, "m_dOpenPrice"),
                "m_dInstrumentValue": self._get_value(obj, "m_dInstrumentValue"),
                "m_dPositionCost": self._get_value(obj, "m_dPositionCost"),
                "m_dPositionProfit": self._get_value(obj, "m_dPositionProfit"),
                "m_dLastPrice": self._get_value(obj, "m_dLastPrice"),
                "m_dProfitRate": self._get_value(obj, "m_dProfitRate"),
            }
        if datatype == "ACCOUNT":
            return {
                "balance": self._get_value(obj, "m_dBalance"),
                "assure_asset": self._get_value(obj, "m_dAssureAsset"),
                "market_value": self._get_value(obj, "m_dInstrumentValue"),
                "total_debit": self._get_value(obj, "m_dTotalDebit"),
                "available": self._get_value(obj, "m_dAvailable"),
                "position_profit": self._get_value(obj, "m_dPositionProfit"),
                "m_dBalance": self._get_value(obj, "m_dBalance"),
                "m_dAssureAsset": self._get_value(obj, "m_dAssureAsset"),
                "m_dInstrumentValue": self._get_value(obj, "m_dInstrumentValue"),
                "m_dTotalDebit": self._get_value(obj, "m_dTotalDebit"),
                "m_dAvailable": self._get_value(obj, "m_dAvailable"),
                "m_dPositionProfit": self._get_value(obj, "m_dPositionProfit"),
            }
        return self._object_to_dict(obj)

    def _stock_code_from_trade_obj(self, obj):
        instrument_id = self._get_value(obj, "m_strInstrumentID")
        exchange_id = self._get_value(obj, "m_strExchangeID")
        if instrument_id and exchange_id:
            return "%s.%s" % (instrument_id, self._market_suffix(exchange_id))
        return instrument_id

    def _market_suffix(self, value):
        text = str(value or "").strip().upper()
        aliases = {
            "0": "SH",
            "SH": "SH",
            "SSE": "SH",
            "SHSE": "SH",
            "1": "SZ",
            "SZ": "SZ",
            "SZSE": "SZ",
            "70": "BJ",
            "BJ": "BJ",
            "BSE": "BJ",
            "3": "SF",
            "SF": "SF",
            "SHFE": "SF",
            "SHF": "SF",
            "4": "DF",
            "DF": "DF",
            "DCE": "DF",
            "DLCE": "DF",
            "5": "ZF",
            "ZF": "ZF",
            "CZCE": "ZF",
            "ZCE": "ZF",
            "2": "IF",
            "IF": "IF",
            "CFFEX": "IF",
            "CFX": "IF",
            "6": "INE",
            "INE": "INE",
            "75": "GF",
            "GF": "GF",
            "GFEX": "GF",
            "7": "SHO",
            "SHO": "SHO",
            "SSEOPTION": "SHO",
            "SSE_OPTION": "SHO",
            "67": "SZO",
            "SZO": "SZO",
            "SZSEOPTION": "SZO",
            "SZSE_OPTION": "SZO",
        }
        return aliases.get(text, text)

    def _order_source(self, obj):
        values = [
            self._get_value(obj, name)
            for name in (
                "order_source",
                "source",
                "order_remark",
                "strategy_name",
                "m_strRemark",
                "m_strOrderRemark",
                "m_strStrategyName",
            )
        ]
        text = " ".join(str(value or "") for value in values).strip().lower()
        return "cfquant" if "cfquant" in text else "other"

    def _first_value(self, obj, names):
        for name in names:
            value = self._get_value(obj, name)
            if value is not None and value != "":
                return value
        return None

    def _object_to_dict(self, obj):
        if hasattr(obj, "items"):
            return dict(obj)
        if hasattr(obj, "__dict__"):
            return dict(vars(obj))
        return {"value": str(obj)}

    def _find_order_id(self, account_id, account_type, user_order_id, strategy_name="", wait_seconds=0.3):
        wait_seconds = float(wait_seconds or 0)
        deadline = time.time() + wait_seconds
        while time.time() <= deadline:
            try:
                orders = self._query_trade_detail(
                    {"account": {"account_id": account_id, "account_type": account_type}, "strategy_name": strategy_name},
                    "ORDER",
                )
                for order in orders or []:
                    remark = self._get_value(order, "m_strRemark")
                    if remark != user_order_id:
                        continue
                    for attr in ("m_strOrderSysID", "m_nOrderID", "order_id", "m_strOrderID"):
                        value = self._get_value(order, attr)
                        if value is not None:
                            return value
            except Exception:
                pass
            if wait_seconds <= 0:
                break
            time.sleep(0.05)
        return None

    def _send_trader_event(self, client_id, name, data):
        self._send_event(client_id, "trader:%s" % name, data)

    def _send_event(self, client_id, name, data, subscription_id=None, meta=None):
        event = pack_event(
            name,
            data=data,
            client_id=client_id,
            subscription_id=subscription_id,
            meta=meta,
        )
        self._push("event", event, client_id)

    def _push(self, key, payload, channel):
        if not channel:
            self._log("cfquant推送缺少channel key=%s payload=%s" % (key, self._brief(payload)))
            return
        tx = self.tx
        if tx is None:
            self._log("cfquant TX未连接，无法推送 channel=%s key=%s" % (channel, key))
            return
        result = tx.push(key, payload, channel)
        if isinstance(result, dict) and result.get("code", 0) != 0:
            self._log("cfquant TX推送失败 channel=%s result=%s" % (channel, result))

    def _call_variants(self, func, variants):
        last_error = None
        for args, kwargs in variants:
            try:
                return func(*args, **kwargs)
            except TypeError as e:
                last_error = e
        if last_error is not None:
            raise last_error
        raise RuntimeError("没有可用调用参数")

    def _get_callable(self, *names):
        for owner in (self.context, getattr(self.context, "context", None)):
            if owner is None:
                continue
            for name in names:
                func = getattr(owner, name, None)
                if callable(func):
                    return func
        for name in names:
            func = self._get_global_func(name)
            if callable(func):
                return func
        return None

    def _enable_auto_trade_callback(self):
        if self.context is None or self.auto_trade_callback_enabled:
            return
        func = getattr(self.context, "set_auto_trade_callback", None)
        if callable(func):
            try:
                result = func(True)
                self.auto_trade_callback_enabled = True
                self._log("auto trade callback enabled result=%s" % result)
                return
            except Exception as e:
                self._log("auto trade callback enable failed:%s" % e)
                return
        func = self._get_callable("set_auto_trade_callback")
        if not callable(func):
            self._log("auto trade callback enable skipped: set_auto_trade_callback not found")
            return
        try:
            result = func(self.context, True)
            self.auto_trade_callback_enabled = True
            self._log("auto trade callback enabled result=%s" % result)
        except TypeError:
            try:
                result = func(True)
                self.auto_trade_callback_enabled = True
                self._log("auto trade callback enabled result=%s" % result)
            except Exception as e:
                self._log("auto trade callback enable failed:%s" % e)
        except Exception as e:
            self._log("auto trade callback enable failed:%s" % e)

    def _get_global_func(self, name):
        func = self.globals_dict.get(name)
        if callable(func):
            return func
        return None

    def _get_value(self, obj, name):
        if hasattr(obj, name):
            return getattr(obj, name)
        if hasattr(obj, "get"):
            return obj.get(name)
        return None

    def _first_param(self, params, names, default=None):
        for name in names:
            value = params.get(name)
            if value is not None and value != "":
                return value
        return default

    def _truthy_param(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(value)

    def _account_type_name(self, account_type):
        mapping = {
            1: "FUTURE",
            2: "STOCK",
            3: "CREDIT",
            5: "FUTURE_OPTION",
            6: "STOCK_OPTION",
            7: "HUGANGTONG",
            10: "NEW3BOARD",
            11: "SHENGANGTONG",
        }
        if isinstance(account_type, str):
            return account_type
        return mapping.get(account_type, "STOCK")

    def _load_txl(self):
        package_error = None
        try:
            from .tx import txl
            return txl
        except Exception as e:
            package_error = e
        try:
            from tx import txl
            return txl
        except Exception as path_error:
            raise RuntimeError("无法导入 LTtx txl，请确认 cfquant 包完整或 tx.py 在 QMT Python 路径中: %s; fallback: %s" % (package_error, path_error))

    def _log(self, msg):
        msg = translate_log(msg)
        line = "%s %s" % (self._timestamp_ms(), msg)
        try:
            self.log_queue.put_nowait(line)
        except Exception:
            pass
        if self.show and self._should_print(msg):
            print(msg)

    def _start_log_thread(self):
        if self.log_thread is not None and self.log_thread.is_alive():
            return
        self.log_thread = threading.Thread(target=self._log_loop)
        self.log_thread.daemon = True
        self.log_thread.start()

    def _log_loop(self):
        buffer = []
        while self.running or not self.log_queue.empty():
            try:
                line = self.log_queue.get(timeout=0.5)
                buffer.append(line)
                while len(buffer) < 100:
                    try:
                        buffer.append(self.log_queue.get_nowait())
                    except Exception:
                        break
            except Exception:
                pass
            if not buffer:
                continue
            try:
                with self.log_lock:
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write("\n".join(buffer) + "\n")
            except Exception:
                pass
            buffer = []

    def _should_print(self, msg):
        if msg.startswith("stage="):
            return False
        if " action=" in msg and " id=" in msg:
            return False
        return True

    def _default_log_file(self):
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        except Exception:
            base_dir = os.getcwd()
        log_dir = (
            os.environ.get("CFQUANT_QMT_LOG_DIR")
            or os.environ.get("CFQUANT_LOG_DIR")
            or os.path.join(base_dir, "log")
        )
        log_dir = os.path.abspath(log_dir)
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            log_dir = base_dir
        return os.path.join(log_dir, "cfquant_qmt_bridge.log")

    def _timestamp_ms(self):
        now = time.time()
        local = time.localtime(now)
        return "%s.%03d" % (time.strftime("%Y-%m-%d %H:%M:%S", local), int((now - int(now)) * 1000))

    def _elapsed_ms(self, start, end=None):
        if end is None:
            end = time.perf_counter()
        return (end - start) * 1000.0

    def _brief(self, value, limit=500):
        try:
            text = repr(value)
        except Exception:
            text = "<unrepresentable>"
        if len(text) > limit:
            text = text[:limit] + "...(%s chars)" % len(text)
        return text

    def _safe_qsize(self, q):
        try:
            return q.qsize()
        except Exception:
            return -1


def start_cfquant_bridge(
    context,
    ip=None,
    port=None,
    token=None,
    request_channel=None,
    show=True,
):
    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return CfquantQmtBridge(
        context,
        ip=ip,
        port=port,
        token=token,
        request_channel=request_channel,
        show=show,
        globals_dict=globals_dict,
    ).start()
