# -*- coding: utf-8 -*-
import os
import sys
import threading
import time

from .protocol import loads_message, pack_event, pack_response
from . import account_routing
from .logging_i18n import get_log_enabled, get_log_language, set_log_enabled, set_log_language, translate_log


XTTRADER_COMPAT_CANDIDATES = {
    "query_account_info": ("query_account_info", "get_account_info"),
    "query_account_infos": ("query_account_infos", "get_account_infos", "query_account_info", "get_account_info"),
    "query_account_status": ("query_account_status", "get_account_status"),
    "query_position_statistics": ("query_position_statistics", "get_position_statistics"),
    "query_secu_account": ("query_secu_account", "get_secu_account"),
    "query_credit_detail": ("query_credit_detail", "get_credit_detail"),
    "query_credit_subjects": ("query_credit_subjects", "get_credit_subjects"),
    "query_credit_slo_code": ("query_credit_slo_code", "get_credit_slo_code"),
    "query_credit_assure": ("query_credit_assure", "get_credit_assure"),
    "query_stk_compacts": ("query_stk_compacts", "get_stk_compacts"),
    "query_ipo_data": ("query_ipo_data", "get_ipo_data"),
    "query_new_purchase_limit": ("query_new_purchase_limit", "get_new_purchase_limit"),
    "query_bank_info": ("query_bank_info", "get_bank_info"),
    "query_bank_amount": ("query_bank_amount", "get_bank_amount"),
    "query_bank_transfer_stream": ("query_bank_transfer_stream", "get_bank_transfer_stream"),
    "bank_transfer_in": ("bank_transfer_in", "transfer_bank_to_security"),
    "bank_transfer_out": ("bank_transfer_out", "transfer_security_to_bank"),
    "fund_transfer": ("fund_transfer",),
    "secu_transfer": ("secu_transfer",),
    "ctp_transfer_future_to_option": ("ctp_transfer_future_to_option",),
    "ctp_transfer_option_to_future": ("ctp_transfer_option_to_future",),
    "query_data": ("query_data",),
    "export_data": ("export_data",),
    "sync_transaction_from_external": ("sync_transaction_from_external",),
    "smt_query_compact": ("smt_query_compact",),
    "smt_query_order": ("smt_query_order",),
    "smt_query_quoter": ("smt_query_quoter",),
    "smt_appointment_order": ("smt_appointment_order",),
    "smt_appointment_cancel": ("smt_appointment_cancel",),
    "smt_negotiate_order": ("smt_negotiate_order",),
    "smt_compact_return": ("smt_compact_return",),
    "smt_compact_renewal": ("smt_compact_renewal",),
}


class TxTradeBridge(object):
    def __init__(
        self,
        context,
        ip="127.0.0.1",
        port=2049,
        token="LTtx",
        request_channel="cfquant.request",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
    ):
        self.context = context
        self.ip = ip
        self.port = int(port)
        self.token = token
        self.request_channel = request_channel
        self.bridge_id = bridge_id or "default"
        self.account_id = account_id
        self.show = show
        self.globals_dict = globals_dict or {}
        self.running = False
        self.tx = None
        self.log_file = self._default_log_file()
        self.account_subscribers = {}
        self.client_accounts = {}
        self.subscriber_lock = threading.RLock()

    def set_context(self, context):
        self.context = context
        self._log("tx trade bridge context ready")

    def start(self):
        if self.running:
            return self
        self.running = True
        txl = self._load_txl()
        self.tx = txl(self.ip, self.port, self.token)
        self.tx.start_tx()
        self.tx.start_txg(self.request_channel)
        self._log(
            "tx trade bridge started LTtx=%s:%s request_channel=%s"
            % (self.ip, self.port, self.request_channel)
        )
        return self

    def close(self):
        self.running = False
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass
        self._log("tx trade bridge stopped")

    def run_forever(self, sleep_seconds=0.05):
        self.start()
        while self.running:
            self.poll(max_messages=100, timeout=sleep_seconds)

    def poll(self, max_messages=100, timeout=0):
        self.start()
        count = 0
        while self.running and count < max_messages:
            try:
                raw = self.tx.Q.get(timeout=timeout if count == 0 else 0)
            except Exception:
                break
            if raw is None:
                break
            self._handle_raw(raw)
            count += 1
        return count

    def _handle_raw(self, raw):
        received_at = time.time()
        msg = loads_message(raw)
        if not msg or msg.get("type") != "request":
            return
        request_id = msg.get("id")
        action = msg.get("action")
        client_id = msg.get("client_id") or msg.get("reply_channel")
        try:
            result = self._dispatch(action, msg.get("params") or {}, msg)
            response = pack_response(request_id, ok=True, result=result)
            self._log("tx trade response_ready action=%s id=%s" % (action, request_id))
        except Exception as e:
            response = pack_response(request_id, ok=False, error=e)
            self._log("tx trade request_error action=%s id=%s error=%s" % (action, request_id, e))
        if client_id:
            self.tx.push("response", response, client_id)
            self._log(
                "tx trade response_sent action=%s id=%s client_id=%s total_ms=%.2f"
                % (action, request_id, client_id, (time.time() - received_at) * 1000)
            )

    def _dispatch(self, action, params, msg):
        if action == "cfquant.ping":
            return {
                "pong": True,
                "ts": time.time(),
                "request_channel": self.request_channel,
                "bridge_id": self.bridge_id,
            }
        if action == "cfquant.status":
            return self._status()
        if action == "cfquant.set_log_language":
            return self._set_log_language(params)
        if action == "cfquant.get_log_language":
            return {"language": get_log_language()}
        if action == "cfquant.set_log_enabled":
            return self._set_log_enabled(params)
        if action == "cfquant.get_log_enabled":
            return {"enabled": get_log_enabled()}
        if action == "cfquant.cleanup_qmt_logs":
            return self._cleanup_qmt_userdata_logs(params)
        if action == "cfquant.query_info":
            return self._query_info(params)
        if action == "xttrader.subscribe":
            return self._subscribe_account(params, msg)
        if action == "xttrader.unsubscribe":
            return self._unsubscribe_account(params, msg)
        if action == "xttrader.query_stock_positions":
            return self._query_trade_detail(params, "position")
        if action == "xttrader.query_stock_orders":
            return self._query_trade_detail(params, "order")
        if action == "xttrader.query_stock_trades":
            return self._query_trade_detail(params, "deal")
        if action == "xttrader.query_stock_asset":
            return self._query_trade_detail(params, "account")
        if action == "xttrader.order_stock":
            return self._order_stock(params, msg)
        if action == "xttrader.order_stock_batch":
            return self._order_stock_batch(params, msg)
        if action == "xttrader.order_stock_async":
            return self._order_stock_async(params, msg)
        if action == "xttrader.cancel_order_stock":
            return self._cancel_order_stock(params)
        if action == "xttrader.cancel_order_stock_async":
            return self._cancel_order_stock_async(params, msg)
        if action == "xttrader.cancel_order_stock_sysid":
            return self._cancel_order_stock_sysid(params)
        if action == "xttrader.cancel_order_stock_sysid_async":
            return self._cancel_order_stock_sysid_async(params, msg)
        if action == "xtdata.get_market_data":
            return self._get_market_data(params)
        if action == "xtdata.get_market_data_ex":
            return self._get_market_data_ex(params)
        if action == "xtdata.get_full_tick":
            return self.context.get_full_tick(params.get("code_list", []))
        if action == "xtdata.get_local_data":
            return self._get_local_data(params)
        if action == "xtdata.download_history_data":
            return self._download_history_data(params, msg)
        if action == "xtdata.download_history_data2":
            return self._download_history_data2(params, msg)
        if action == "xtdata.get_financial_data":
            return self._get_financial_data(params)
        if action == "xtdata.get_raw_financial_data":
            return self._get_raw_financial_data(params)
        if action == "xtdata.download_financial_data":
            return self._download_financial_data(params, msg)
        if action == "xtdata.download_financial_data2":
            return self._download_financial_data(params, msg)
        if action == "xtdata.get_instrument_detail":
            return self._get_instrument_detail(params)
        if action == "xtdata.get_stock_list_in_sector":
            return self.context.get_stock_list_in_sector(params.get("sector_name", ""))
        if action.startswith("xtdata."):
            return self._dispatch_xtdata_compat(action, params, msg)
        if action.startswith("xttrader."):
            return self._dispatch_xttrader_compat(action, params, msg)
        raise ValueError("unsupported action: %s" % action)

    def _status(self):
        status = {
            "bridge": type(self).__name__,
            "bridge_id": self.bridge_id,
            "running": self.running,
            "request_channel": self.request_channel,
            "account_id": self.account_id,
            "account_subscribers": self._account_subscriber_status(),
            "log_language": get_log_language(),
            "log_enabled": get_log_enabled(),
            "context_ready": self.context is not None,
            "tx_ready": self.tx is not None,
            "ts": time.time(),
        }
        try:
            extra = self._status_extra()
            if extra:
                status.update(extra)
        except Exception as e:
            status["status_extra_error"] = str(e)
        return status

    def _status_extra(self):
        return {}

    def _set_log_language(self, params):
        params = params or {}
        lang = set_log_language(params.get("language") or params.get("lang"))
        self._log("QMT日志语言已切换为:%s" % ("中文" if lang == "zh" else "English"))
        return {"language": lang}

    def _set_log_enabled(self, params):
        params = params or {}
        if "enabled" in params:
            value = params.get("enabled")
        else:
            value = params.get("show")
        enabled = set_log_enabled(value)
        self.show = True
        self._log("QMT log output enabled=%s" % ("1" if enabled else "0"), force=True)
        return {"enabled": enabled}

    def _cleanup_qmt_userdata_logs(self, params):
        params = params or {}
        retention_days = self._retention_days(params.get("retention_days"), default=5)
        dry_run = str(params.get("dry_run") or "").strip().lower() in ("1", "true", "yes", "on")
        log_dir, candidate_dirs, python_dir, entry_file = self._qmt_userdata_log_dir()
        result = {
            "bridge_id": self.bridge_id,
            "request_channel": self.request_channel,
            "retention_days": retention_days,
            "dry_run": dry_run,
            "entry_file": entry_file,
            "python_dir": python_dir,
            "log_dir": log_dir,
            "candidate_dirs": candidate_dirs,
            "exists": bool(log_dir and os.path.isdir(log_dir)),
            "scanned_files": 0,
            "kept_files": 0,
            "deleted_files": 0,
            "would_delete_files": 0,
            "failed_files": 0,
            "deleted_bytes": 0,
            "errors": [],
            "ts": time.time(),
        }
        if not result["exists"]:
            return result

        cutoff = time.time() - retention_days * 86400
        for current_root, dirs, files in os.walk(log_dir):
            for name in files:
                path = os.path.join(current_root, name)
                result["scanned_files"] += 1
                try:
                    stat_result = os.stat(path)
                    if stat_result.st_mtime >= cutoff:
                        result["kept_files"] += 1
                        continue
                    if dry_run:
                        result["would_delete_files"] += 1
                        result["deleted_bytes"] += stat_result.st_size
                    else:
                        os.remove(path)
                        result["deleted_files"] += 1
                        result["deleted_bytes"] += stat_result.st_size
                except Exception as e:
                    result["failed_files"] += 1
                    result["errors"].append("%s: %s" % (path, e))
        self._log(
            "qmt userdata log cleanup log_dir=%s retention_days=%s deleted=%s failed=%s dry_run=%s"
            % (log_dir, retention_days, result["deleted_files"], result["failed_files"], dry_run)
        )
        return result

    def _qmt_userdata_log_dir(self):
        entry_file = self.globals_dict.get("__file__") or ""
        if entry_file:
            entry_file = os.path.abspath(entry_file)
            python_dir = os.path.dirname(entry_file)
        else:
            python_dir = os.path.abspath(os.getcwd())
        candidate_dirs = []
        if os.path.basename(python_dir).lower() == "python":
            candidate_dirs.append(os.path.join(os.path.dirname(python_dir), "userdata", "log"))
        candidate_dirs.append(os.path.join(python_dir, "userdata", "log"))

        normalized = []
        seen = set()
        for path in candidate_dirs:
            path = os.path.abspath(path)
            key = path.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(path)
        for path in normalized:
            if os.path.isdir(path):
                return path, normalized, python_dir, entry_file
        return normalized[0] if normalized else "", normalized, python_dir, entry_file

    def _retention_days(self, value, default=5):
        try:
            days = int(value)
        except Exception:
            days = int(default)
        if days < 1:
            days = 1
        if days > 3650:
            days = 3650
        return days

    def _query_info(self, params):
        return {
            "orders": self._query_trade_detail(params, "order"),
            "deals": self._query_trade_detail(params, "deal"),
            "positions": self._query_trade_detail(params, "position"),
            "accounts": self._query_trade_detail(params, "account"),
        }

    def _query_trade_detail(self, params, detail_type):
        func = self._get_callable("get_trade_detail_data")
        if not func:
            raise NotImplementedError("get_trade_detail_data not found")
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        if not account_id:
            raise ValueError("account_id is required")
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        self._log(
            "query_trade_detail start account=%s account_type=%s detail_type=%s"
            % (account_id, account_type.lower(), detail_type.lower())
        )
        try:
            rows = func(account_id, account_type.lower(), detail_type.lower()) or []
        except Exception as e:
            self._log(
                "query_trade_detail call failed account=%s detail_type=%s error=%s"
                % (account_id, detail_type, e)
            )
            raise

        result = []
        for index, row in enumerate(rows):
            try:
                result.append(self._format_trade_detail(row, detail_type))
            except Exception as e:
                self._log(
                    "query_trade_detail format failed detail_type=%s index=%s type=%s error=%s"
                    % (detail_type, index, type(row).__name__, e)
                )
                result.append({
                    "format_error": str(e),
                    "raw_type": type(row).__name__,
                })
        self._log(
            "query_trade_detail done detail_type=%s count=%s"
            % (detail_type, len(result))
        )
        return result

    def _order_stock(self, params, msg):
        passorder = self._get_callable("passorder")
        if not passorder:
            raise NotImplementedError("passorder not found")
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        order_type = params.get("optype", params.get("order_type"))
        if not account_id:
            raise ValueError("account_id is required")
        if isinstance(order_type, str):
            order_type = 23 if order_type.lower() == "buy" else 24
        price_type = params.get("price_type", 11)
        order_remark = params.get("order_remark", msg.get("id", "tx_order"))
        result = passorder(
            order_type,
            params.get("qmt_order_type", 1101),
            account_id,
            params.get("stock_code", params.get("code", "")),
            price_type,
            params.get("price", 0),
            params.get("order_volume", params.get("num", 0)),
            params.get("strategy_name", "1"),
            params.get("quick_trade", 2),
            order_remark,
            self.context,
        )
        return {"request_result": result, "order_id": result, "order_remark": order_remark}

    def _order_stock_async(self, params, msg):
        result = self._order_stock(params, msg)
        data = {
            "seq": params.get("seq"),
            "account_id": (params.get("account") or {}).get("account_id", params.get("account_id", "")),
            "account_type": self._account_type_name((params.get("account") or {}).get("account_type") or params.get("account_type")).upper(),
            "order_id": result.get("order_id", -1) if isinstance(result, dict) else result,
            "order_remark": result.get("order_remark", params.get("order_remark", "")) if isinstance(result, dict) else params.get("order_remark", ""),
        }
        self._send_trader_event(msg.get("client_id"), "on_order_stock_async_response", data)
        return result

    def _order_stock_batch(self, params, msg):
        orders = params.get("orders") or []
        if not isinstance(orders, list) or not orders:
            raise ValueError("orders must be a non-empty list")
        common_account = params.get("account") or {}
        stop_on_error = bool(params.get("stop_on_error"))
        results = []
        for index, order in enumerate(orders):
            row = dict(params)
            row.pop("orders", None)
            row.update(order or {})
            if common_account and not row.get("account"):
                row["account"] = common_account
            if not row.get("order_remark"):
                row["order_remark"] = "%s_%s" % (params.get("order_remark") or msg.get("id", "batch_order"), index + 1)
            try:
                result = self._order_stock(row, msg)
                results.append({
                    "index": index,
                    "ok": True,
                    "stock_code": row.get("stock_code", row.get("code", "")),
                    "result": result,
                })
            except Exception as e:
                results.append({
                    "index": index,
                    "ok": False,
                    "stock_code": row.get("stock_code", row.get("code", "")),
                    "error": str(e),
                })
                if stop_on_error:
                    break
        return {
            "total": len(orders),
            "submitted": len([item for item in results if item.get("ok")]),
            "failed": len([item for item in results if not item.get("ok")]),
            "results": results,
        }

    def _cancel_order_stock(self, params):
        cancel_func = self._get_callable("cancel")
        if not cancel_func:
            raise NotImplementedError("cancel not found")
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        order_id = str(params.get("order_id", ""))
        if not account_id:
            raise ValueError("account_id is required")
        if not order_id:
            raise ValueError("order_id is required")
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        result = cancel_func(order_id, account_id, account_type, self.context)
        return {"cancel_result": 0 if result else -1, "request_result": result, "order_id": order_id}

    def _cancel_order_stock_async(self, params, msg):
        result = self._cancel_order_stock(params)
        data = {
            "seq": params.get("seq"),
            "account_id": (params.get("account") or {}).get("account_id", params.get("account_id", "")),
            "account_type": self._account_type_name((params.get("account") or {}).get("account_type") or params.get("account_type")).upper(),
            "order_id": params.get("order_id"),
            "cancel_result": result.get("cancel_result", -1) if isinstance(result, dict) else result,
        }
        self._send_trader_event(msg.get("client_id"), "on_cancel_order_stock_async_response", data)
        return result

    def _cancel_order_stock_sysid(self, params):
        row = dict(params)
        row["order_id"] = params.get("sysid", params.get("order_id", ""))
        result = self._cancel_order_stock(row)
        result["market"] = params.get("market")
        result["sysid"] = params.get("sysid")
        return result

    def _cancel_order_stock_sysid_async(self, params, msg):
        result = self._cancel_order_stock_sysid(params)
        data = {
            "seq": params.get("seq"),
            "account_id": (params.get("account") or {}).get("account_id", params.get("account_id", "")),
            "order_id": params.get("sysid", params.get("order_id")),
            "cancel_result": result.get("cancel_result", -1) if isinstance(result, dict) else result,
        }
        self._send_trader_event(msg.get("client_id"), "on_cancel_order_stock_async_response", data)
        return result

    def _dispatch_xttrader_compat(self, action, params, msg):
        method = action.split(".", 1)[1]
        if method == "query_com_fund":
            rows = self._query_trade_detail(params, "account")
            return rows[0] if rows else {}
        if method == "query_com_position":
            return self._query_trade_detail(params, "position")
        if method == "query_stock_asset_async":
            return self._query_trade_detail(params, "account")
        if method == "query_stock_orders_async":
            return self._query_trade_detail(params, "order")
        if method == "query_stock_trades_async":
            return self._query_trade_detail(params, "deal")
        if method == "query_stock_positions_async":
            return self._query_trade_detail(params, "position")
        return self._generic_xttrader_call(method, params)

    def _dispatch_xtdata_compat(self, action, params, msg):
        method = action.split(".", 1)[1]
        if method == "get_trading_dates":
            return self._get_trading_dates(params)
        if method in (
            "is_stock",
            "is_fund",
            "is_future",
            "get_stock_type",
            "get_stock_name",
            "get_open_date",
            "get_contract_expire_date",
            "get_contract_multiplier",
        ):
            return self._call_stock_callable(method, params)
        if method == "get_weight_in_index":
            return self._get_weight_in_index(params)
        if method == "get_turnover_rate":
            return self._get_turnover_rate(params)
        if method in ("get_ETF_list", "get_etf_list"):
            return self._get_etf_list(params)
        if method == "get_option_detail_data":
            return self._get_option_detail_data(params)
        if method == "get_option_list":
            return self._get_option_list(params)
        if method == "get_option_undl":
            return self._get_option_undl(params)
        if method == "get_option_undl_data":
            return self._get_option_undl_data(params)
        if method == "get_his_st_data":
            return self._get_his_st_data(params)
        if method == "get_his_index_data":
            return self._get_his_index_data(params)
        if method == "get_factor_data":
            return self._get_factor_data(params)
        if method in ("get_financial_data_ori", "get_financial_data_raw"):
            return self._get_raw_financial_data(params)
        raise NotImplementedError("xtdata.%s is not implemented by cfquant QMT bridge" % method)

    def _generic_xttrader_call(self, method, params):
        candidates = XTTRADER_COMPAT_CANDIDATES.get(method, (method,))
        func = self._get_callable(*candidates)
        if not func:
            raise NotImplementedError(
                "xttrader.%s requires QMT callable: %s"
                % (method, ", ".join(candidates))
            )
        args = list(params.get("args") or [])
        kwargs = dict(params.get("kwargs") or {})
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        account_type_value = account.get("account_type") or params.get("account_type")
        account_type = self._account_type_name(account_type_value)
        variants = []
        if account:
            variants.extend([
                ((account,) + tuple(args), kwargs),
                ((account_id,) + tuple(args), kwargs),
                ((account_id, account_type.lower()) + tuple(args), kwargs),
                ((account_id, account_type) + tuple(args), kwargs),
                ((account_id, account_type_value) + tuple(args), kwargs),
            ])
        variants.extend([
            (tuple(args), kwargs),
            ((params,), {}),
        ])
        return self._call_variants(func, variants)

    def _get_market_data(self, params):
        func = self._get_callable("get_market_data")
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
        func = self._get_callable("get_market_data_ex")
        if not func:
            raise NotImplementedError("get_market_data_ex not found")
        return func(
            params.get("field_list", []),
            params.get("stock_list", []),
            params.get("period", "1d"),
            params.get("start_time", ""),
            params.get("end_time", ""),
            params.get("count", -1),
            params.get("dividend_type", "none"),
            params.get("fill_data", True),
        )

    def _get_local_data(self, params):
        func = self._get_callable("get_local_data")
        if not func:
            return self._get_market_data_ex(params)
        stock_code = self._first_param(params, ("stock_code", "stockcode", "stock", "code"), "")
        stock_list = self._list_param(params.get("stock_list", params.get("code_list", [])))
        if not stock_code and stock_list:
            return dict((code, self._call_local_data(func, code, params)) for code in stock_list)
        return self._call_local_data(func, stock_code, params)

    def _call_local_data(self, func, stock_code, params):
        return self._call_variants(func, [
            ((
                stock_code,
                params.get("start_time", params.get("start_date", "19700101")),
                params.get("end_time", params.get("end_date", "22010101")),
                params.get("period", "follow"),
                params.get("divid_type", params.get("dividend_type", "none")),
                params.get("count", -1),
            ), {}),
            ((
                stock_code,
                params.get("start_time", params.get("start_date", "19700101")),
                params.get("end_time", params.get("end_date", "22010101")),
                params.get("period", "follow"),
                params.get("divid_type", params.get("dividend_type", "none")),
            ), {}),
            ((
                stock_code,
                params.get("start_time", params.get("start_date", "19700101")),
                params.get("end_time", params.get("end_date", "22010101")),
            ), {}),
            ((stock_code,), {}),
        ])

    def _download_event_meta(self, params, kind, stage):
        meta = {
            "download": True,
            "download_kind": kind,
            "stage": stage,
            "bridge_id": self.bridge_id,
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
                    "error": "download_history_data not found",
                })
            raise NotImplementedError("download_history_data not found")
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
                    "error": "download_history_data2 not found",
                })
            raise NotImplementedError("download_history_data2 not found")

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
        func = self._get_callable("get_instrument_detail")
        if not func:
            raise NotImplementedError("get_instrument_detail not found")
        return func(params.get("stock_code", ""))

    def _get_financial_data(self, params):
        func = self._get_callable("get_financial_data")
        if not func:
            raise NotImplementedError("get_financial_data not found")
        fields = params.get("field_list") or []
        stock_list = params.get("stock_list", params.get("code_list", []))
        table_list = params.get("table_list") or []
        start_time = params.get("start_time", params.get("start_date", ""))
        end_time = params.get("end_time", params.get("end_date", ""))
        report_type = params.get("report_type") or ("announce_time" if fields else "report_time")
        variants = []
        if fields:
            variants.append(((fields, stock_list, start_time, end_time, report_type), {}))
            variants.append(((fields, stock_list, start_time, end_time), {}))
        if not variants:
            raise ValueError("field_list is required")
        return self._call_variants(func, variants)

    def _get_raw_financial_data(self, params):
        func = self._get_callable("get_raw_financial_data")
        if not func:
            raise NotImplementedError("get_raw_financial_data not found")
        fields = params.get("field_list") or []
        stock_list = params.get("stock_list", params.get("code_list", []))
        if not fields:
            raise ValueError("field_list is required for get_raw_financial_data")
        return self._call_variants(func, [
            ((
                fields,
                stock_list,
                params.get("start_time", params.get("start_date", "")),
                params.get("end_time", params.get("end_date", "")),
                params.get("report_type") or "announce_time",
            ), {}),
            ((
                fields,
                stock_list,
                params.get("start_time", params.get("start_date", "")),
                params.get("end_time", params.get("end_date", "")),
            ), {}),
        ])

    def _default_financial_field(self, table):
        table = str(table or "").strip().upper()
        defaults = {
            "ASHAREBALANCESHEET": "fix_assets",
            "ASHAREINCOME": "net_profit_excl_min_int_inc",
            "ASHARECASHFLOW": "net_cash_flows_oper_act",
            "CAPITALSTRUCTURE": "capital",
            "PERSHAREINDEX": "eps",
        }
        return defaults.get(table, "fix_assets")

    def _financial_probe_fields(self, params):
        fields = self._list_param(params.get("field_list") or params.get("fields"))
        tables = self._list_param(params.get("table_list") or params.get("tables") or params.get("table"))
        if not tables:
            tables = ["ASHAREBALANCESHEET"]
        if not fields:
            fields = [self._default_financial_field(tables[0])]
        if len(tables) == 1:
            table = tables[0]
            fields = [
                field if "." in str(field) or "。" in str(field) else "%s.%s" % (table, field)
                for field in fields
            ]
        return fields

    def _summarize_data_result(self, value):
        if value is None:
            return {"type": "None", "empty": True}
        type_name = value.__class__.__name__
        if type_name == "DataFrame":
            shape = list(getattr(value, "shape", []) or [])
            columns = [str(item) for item in list(getattr(value, "columns", []) or [])[:20]]
            return {
                "type": "DataFrame",
                "shape": shape,
                "columns": columns,
                "empty": bool(getattr(value, "empty", False)),
            }
        if type_name == "Series":
            size = int(getattr(value, "size", 0) or 0)
            return {"type": "Series", "count": size, "empty": size <= 0}
        if isinstance(value, dict):
            return {
                "type": "dict",
                "count": len(value),
                "keys": [str(item) for item in list(value.keys())[:20]],
                "empty": len(value) <= 0,
            }
        if isinstance(value, (list, tuple, set)):
            return {"type": type_name, "count": len(value), "empty": len(value) <= 0}
        return {"type": type_name, "preview": str(value)[:200], "empty": False}

    def _check_local_financial_data(self, params):
        fields = self._financial_probe_fields(params)
        stock_list = params.get("stock_list", params.get("code_list", []))
        start_time = params.get("start_time", params.get("start_date", ""))
        end_time = params.get("end_time", params.get("end_date", ""))
        report_type = params.get("report_type") or "report_time"
        func = self._get_callable("get_raw_financial_data")
        action = "get_raw_financial_data"
        if not func:
            func = self._get_callable("get_financial_data")
            action = "get_financial_data"
        if not func:
            raise NotImplementedError("get_raw_financial_data/get_financial_data not found")
        result = self._call_variants(func, [
            ((fields, stock_list, start_time, end_time, report_type), {}),
            ((fields, stock_list, start_time, end_time), {}),
        ])
        return {
            "download_supported": False,
            "manual_download_required": True,
            "manual_download_hint": "QMT官方脚本侧未提供财务数据下载函数；请先在QMT客户端 数据管理 - 财务数据下载 中下载，再读取本地财务数据。",
            "query_action": action,
            "field_list": fields,
            "stock_list": stock_list,
            "query_summary": self._summarize_data_result(result),
            "result": True,
        }

    def _download_financial_data(self, params, msg=None):
        stock_list = params.get("stock_list", params.get("code_list", []))
        table_list = params.get("table_list") or []
        start_time = params.get("start_time", params.get("start_date", ""))
        end_time = params.get("end_time", params.get("end_date", ""))
        callback_event = params.get("callback_event")
        client_id = msg.get("client_id") if msg else None
        emit_lifecycle = bool(params.get("download_emit_lifecycle"))
        func = self._get_callable("download_financial_data2", "down_financial_data2")
        if func:
            def callback(data):
                if callback_event and client_id:
                    self._send_event(
                        client_id,
                        callback_event,
                        data,
                        meta=self._download_event_meta(params, "financial", "progress"),
                    )

            callback_func = callback if callback_event else None
            variants = [
                ((stock_list, table_list, start_time, end_time, callback_func), {}),
                ((stock_list, table_list, start_time, end_time), {}),
            ]
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial", "submitted", {
                    "stage": "submitted",
                    "message": "financial download request submitted",
                })
            try:
                result = self._call_variants(func, variants)
            except Exception as e:
                if emit_lifecycle:
                    self._send_download_event(client_id, params, "financial", "error", {
                        "stage": "error",
                        "error": str(e),
                    })
                raise
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial", "request_done", {
                    "stage": "request_done",
                    "result": result,
                })
            return result
        func = self._get_callable("download_financial_data", "down_financial_data")
        if not func:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial_check", "submitted", {
                    "stage": "submitted",
                    "message": "开始校验本地财务数据，QMT官方脚本侧未提供财务下载函数。",
                })
            try:
                result = self._check_local_financial_data(params)
            except Exception as e:
                if emit_lifecycle:
                    self._send_download_event(client_id, params, "financial_check", "error", {
                        "stage": "error",
                        "error": str(e),
                    })
                raise
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial_check", "request_done", {
                    "stage": "request_done",
                    "message": "本地财务数据校验已返回。",
                    "summary": result.get("query_summary"),
                    "available": not bool((result.get("query_summary") or {}).get("empty")),
                })
            return result
        if emit_lifecycle:
            self._send_download_event(client_id, params, "financial", "submitted", {
                "stage": "submitted",
                "message": "financial download request submitted",
            })
        try:
            result = self._call_variants(func, [
                ((stock_list, table_list), {}),
                ((stock_list,), {}),
            ])
        except Exception as e:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial", "error", {
                    "stage": "error",
                    "error": str(e),
                })
            raise
        if emit_lifecycle:
            self._send_download_event(client_id, params, "financial", "request_done", {
                "stage": "request_done",
                "result": result,
            })
        return result

    def _get_trading_dates(self, params):
        func = self._get_callable("get_trading_dates")
        if not func:
            raise NotImplementedError("get_trading_dates not found")
        return func(
            self._first_param(params, ("stockcode", "stock_code", "stock", "code"), ""),
            params.get("start_date", params.get("start_time", "")),
            params.get("end_date", params.get("end_time", "")),
            params.get("count", -1),
            params.get("period", "1d"),
        )

    def _call_stock_callable(self, method, params):
        func = self._get_callable(method)
        if not func:
            raise NotImplementedError("%s not found" % method)
        return func(self._first_param(params, ("stock_code", "stockcode", "stock", "code"), ""))

    def _get_weight_in_index(self, params):
        func = self._get_callable("get_weight_in_index")
        if not func:
            raise NotImplementedError("get_weight_in_index not found")
        return func(
            self._first_param(params, ("mtkindexcode", "index_code", "index", "index_code_ref"), ""),
            self._first_param(params, ("stockcode", "stock_code", "stock", "code"), ""),
        )

    def _get_turnover_rate(self, params):
        func = self._get_callable("get_turnover_rate")
        if not func:
            raise NotImplementedError("get_turnover_rate not found")
        return func(
            self._first_param(params, ("stock_code", "stockcode", "stock", "code"), ""),
            params.get("start_time", params.get("start_date", "")),
            params.get("end_time", params.get("end_date", "")),
        )

    def _get_etf_list(self, params):
        func = self._get_callable("get_ETF_list", "get_etf_list")
        if not func:
            raise NotImplementedError("get_ETF_list not found")
        return func(
            params.get("market", ""),
            self._first_param(params, ("stockcode", "stock_code", "stock", "code"), ""),
            self._list_param(params.get("typeList", params.get("type_list", []))),
        )

    def _get_option_detail_data(self, params):
        func = self._get_callable("get_option_detail_data")
        if not func:
            raise NotImplementedError("get_option_detail_data not found")
        return func(self._first_param(params, ("stockcode", "stock_code", "opt_code", "code"), ""))

    def _get_option_list(self, params):
        func = self._get_callable("get_option_list")
        if not func:
            raise NotImplementedError("get_option_list not found")
        return func(
            self._first_param(params, ("object", "underlying_code", "undl_code", "stock_code", "code"), ""),
            params.get("dedate", params.get("expire_date", "")),
            params.get("opttype", params.get("option_type", "")),
            params.get("isavailavle", params.get("is_available", params.get("available", False))),
        )

    def _get_option_undl(self, params):
        func = self._get_callable("get_option_undl")
        if not func:
            raise NotImplementedError("get_option_undl not found")
        return func(self._first_param(params, ("opt_code", "stock_code", "stockcode", "code"), ""))

    def _get_option_undl_data(self, params):
        func = self._get_callable("get_option_undl_data")
        if not func:
            raise NotImplementedError("get_option_undl_data not found")
        return self._call_variants(func, [
            ((self._first_param(params, ("undl_code_ref", "undl_code", "underlying_code", "stock_code", "code"), ""),), {}),
            ((), {}),
        ])

    def _get_his_st_data(self, params):
        func = self._get_callable("get_his_st_data")
        if not func:
            raise NotImplementedError("get_his_st_data not found")
        return func(self._first_param(params, ("stockCode", "stock_code", "stockcode", "code"), ""))

    def _get_his_index_data(self, params):
        func = self._get_callable("get_his_index_data")
        if not func:
            raise NotImplementedError("get_his_index_data not found")
        return func(self._first_param(params, ("stockCode", "stock_code", "stockcode", "code"), ""))

    def _get_factor_data(self, params):
        func = self._get_callable("get_factor_data")
        if not func:
            raise NotImplementedError("get_factor_data not found")
        return func(
            params.get("field_list", params.get("fields", [])),
            params.get("stock_list", params.get("code_list", [])),
            params.get("start_date", params.get("start_time", "")),
            params.get("end_date", params.get("end_time", "")),
        )

    def _subscribe_account(self, params, msg=None):
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        if not account_id:
            raise ValueError("account_id is required")
        account_id = str(account_id).strip()
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        self.account_id = account_id
        subscriber_key = (account_type.upper(), account_id)
        client_id = ""
        if msg:
            client_id = msg.get("client_id") or msg.get("reply_channel") or ""
        if client_id:
            with self.subscriber_lock:
                self.account_subscribers.setdefault(subscriber_key, set()).add(client_id)
                self.client_accounts.setdefault(client_id, set()).add(subscriber_key)
            account_routing.subscribe(self.bridge_id, account_id, client_id, account_type=account_type)
        if self.context is not None:
            try:
                self.context.set_account(account_id, account_type.upper())
            except Exception:
                self.context.set_account(account_id)
        self._log("account subscribed account=%s client_id=%s" % (account_id, client_id or "-"))
        return 0

    def _unsubscribe_account(self, params, msg=None):
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id")
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        subscriber_key = None
        client_id = ""
        if msg:
            client_id = msg.get("client_id") or msg.get("reply_channel") or ""
        if account_id:
            account_id = str(account_id).strip()
            subscriber_key = (account_type.upper(), account_id)
        with self.subscriber_lock:
            if account_id and client_id:
                subscribers = self.account_subscribers.get(subscriber_key)
                if subscribers:
                    subscribers.discard(client_id)
                    if not subscribers:
                        self.account_subscribers.pop(subscriber_key, None)
                accounts = self.client_accounts.get(client_id)
                if accounts:
                    accounts.discard(subscriber_key)
                    accounts.discard(account_id)
                    if not accounts:
                        self.client_accounts.pop(client_id, None)
            elif client_id:
                accounts = self.client_accounts.pop(client_id, set())
                for item in accounts:
                    subscribers = self.account_subscribers.get(item)
                    if subscribers:
                        subscribers.discard(client_id)
                        if not subscribers:
                            self.account_subscribers.pop(item, None)
        account_routing.unsubscribe(self.bridge_id, account_id=account_id, client_id=client_id, account_type=account_type if account_id else None)
        if account_id and account_id == self.account_id:
            self.account_id = ""
        self._log("account unsubscribed account=%s client_id=%s" % (account_id or "-", client_id or "-"))
        return 0

    def _format_trade_detail(self, obj, detail_type):
        detail_type = str(detail_type).lower()
        if detail_type == "order":
            return {
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "order_source": self._order_source(obj),
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
                "offset_flag": self._get_value(obj, "m_nOffsetFlag"),
                "order_volume": self._get_value(obj, "m_nVolumeTotalOriginal"),
                "traded_price": self._get_value(obj, "m_dTradedPrice"),
                "traded_volume": self._get_value(obj, "m_nVolumeTraded"),
                "trade_amount": self._get_value(obj, "m_dTradeAmount"),
                "order_status": self._get_value(obj, "m_nOrderStatus"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nOffsetFlag": self._get_value(obj, "m_nOffsetFlag"),
                "m_nVolumeTotalOriginal": self._get_value(obj, "m_nVolumeTotalOriginal"),
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
        if detail_type == "deal":
            return {
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "trade_time": self._first_value(obj, (
                    "trade_time",
                    "deal_time",
                    "m_strTradeTime",
                    "m_strDealTime",
                    "m_nTradeTime",
                    "m_nDealTime",
                )),
                "trade_date": self._first_value(obj, (
                    "trade_date",
                    "deal_date",
                    "m_strTradeDate",
                    "m_strDealDate",
                    "m_strTradingDay",
                    "m_nTradeDate",
                    "m_nDealDate",
                )),
                "offset_flag": self._get_value(obj, "m_nOffsetFlag"),
                "price": self._get_value(obj, "m_dPrice"),
                "volume": self._get_value(obj, "m_nVolume"),
                "trade_amount": self._get_value(obj, "m_dTradeAmount"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nOffsetFlag": self._get_value(obj, "m_nOffsetFlag"),
                "m_dPrice": self._get_value(obj, "m_dPrice"),
                "m_nVolume": self._get_value(obj, "m_nVolume"),
                "m_dTradeAmount": self._get_value(obj, "m_dTradeAmount"),
                "m_strTradeTime": self._get_value(obj, "m_strTradeTime"),
                "m_strDealTime": self._get_value(obj, "m_strDealTime"),
                "m_nTradeTime": self._get_value(obj, "m_nTradeTime"),
                "m_nDealTime": self._get_value(obj, "m_nDealTime"),
                "m_strTradeDate": self._get_value(obj, "m_strTradeDate"),
                "m_strDealDate": self._get_value(obj, "m_strDealDate"),
                "m_strTradingDay": self._get_value(obj, "m_strTradingDay"),
            }
        if detail_type == "position":
            return {
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "volume": self._get_value(obj, "m_nVolume"),
                "can_use_volume": self._get_value(obj, "m_nCanUseVolume"),
                "open_price": self._get_value(obj, "m_dOpenPrice"),
                "market_value": self._get_value(obj, "m_dInstrumentValue"),
                "position_cost": self._get_value(obj, "m_dPositionCost"),
                "position_profit": self._get_value(obj, "m_dPositionProfit"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nVolume": self._get_value(obj, "m_nVolume"),
                "m_nCanUseVolume": self._get_value(obj, "m_nCanUseVolume"),
                "m_dOpenPrice": self._get_value(obj, "m_dOpenPrice"),
                "m_dInstrumentValue": self._get_value(obj, "m_dInstrumentValue"),
                "m_dPositionCost": self._get_value(obj, "m_dPositionCost"),
                "m_dPositionProfit": self._get_value(obj, "m_dPositionProfit"),
            }
        if detail_type == "account":
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
        return {"value": str(obj)}

    def _first_value(self, obj, names):
        for name in names:
            value = self._get_value(obj, name)
            if value is not None and value != "":
                return value
        return None

    def _stock_code(self, obj):
        instrument_id = self._get_value(obj, "m_strInstrumentID")
        exchange_id = self._get_value(obj, "m_strExchangeID")
        if instrument_id and exchange_id:
            return "%s.%s" % (instrument_id, exchange_id)
        return instrument_id

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

    def _get_value(self, obj, name):
        if obj is None:
            return None
        try:
            return self._plain_value(getattr(obj, name))
        except AttributeError:
            pass
        except Exception as e:
            self._log(
                "trade detail getattr failed type=%s field=%s error=%s"
                % (type(obj).__name__, name, e)
            )
        try:
            getter = getattr(obj, "get", None)
            if callable(getter):
                return self._plain_value(getter(name))
        except AttributeError:
            pass
        except Exception as e:
            self._log(
                "trade detail get failed type=%s field=%s error=%s"
                % (type(obj).__name__, name, e)
            )
        return None

    def _plain_value(self, value):
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return str(value)
        try:
            item = getattr(value, "item", None)
            if callable(item):
                return item()
        except Exception:
            pass
        if isinstance(value, (list, tuple)):
            return [self._plain_value(item) for item in value]
        if isinstance(value, dict):
            return dict((str(k), self._plain_value(v)) for k, v in value.items())
        return str(value)

    def _first_param(self, params, names, default=None):
        for name in names:
            value = params.get(name)
            if value is not None and value != "":
                return value
        return default

    def _list_param(self, value):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value]

    def _account_type_name(self, account_type):
        mapping = {
            1: "future",
            2: "stock",
            3: "credit",
            5: "future_option",
            6: "stock_option",
            7: "hugangtong",
            10: "new3board",
            11: "shengangtong",
        }
        if isinstance(account_type, str):
            return account_type
        return mapping.get(account_type, "stock")

    def _send_trader_event(self, client_id, name, data):
        if client_id:
            self._send_event(client_id, "trader:%s" % name, data)

    def _client_ids_for_account(self, account_id, account_type=None):
        account_id = str(account_id or "").strip()
        if not account_id:
            return []
        account_type = self._account_type_name(account_type).upper() if account_type not in (None, "") else ""
        with self.subscriber_lock:
            if account_type:
                client_ids = set(self.account_subscribers.get((account_type, account_id), set()))
            else:
                client_ids = set()
                for key, ids in self.account_subscribers.items():
                    if isinstance(key, tuple) and len(key) == 2 and key[1] == account_id:
                        client_ids.update(ids)
                    elif key == account_id:
                        client_ids.update(ids)
        if account_type:
            client_ids.update(account_routing.client_ids(self.bridge_id, account_id, account_type=account_type))
        return sorted(client_ids)

    def _send_trader_event_to_account(self, account_id, name, data, account_type=None):
        if account_type and isinstance(data, dict):
            data.setdefault("account_type", self._account_type_name(account_type).upper())
        for client_id in self._client_ids_for_account(account_id, account_type=account_type):
            self._send_trader_event(client_id, name, data)

    def _account_subscriber_status(self):
        with self.subscriber_lock:
            status = {}
            for key, client_ids in self.account_subscribers.items():
                if isinstance(key, tuple) and len(key) == 2:
                    label = "%s:%s" % (key[0], key[1])
                else:
                    label = "STOCK:%s" % key
                status[label] = len(client_ids)
        for account_id, count in account_routing.status(self.bridge_id).items():
            status[account_id] = max(status.get(account_id, 0), count)
        return status

    def _send_event(self, client_id, name, data, subscription_id=None, meta=None):
        if not client_id or self.tx is None:
            return
        event = pack_event(name, data=data, client_id=client_id, subscription_id=subscription_id, meta=meta)
        self.tx.push("event", event, client_id)

    def _call_variants(self, func, variants):
        last_error = None
        for args, kwargs in variants:
            try:
                return func(*args, **kwargs)
            except TypeError as e:
                last_error = e
                continue
        if last_error:
            raise last_error
        return func()

    def _get_callable(self, *names):
        owners = [self.globals_dict]
        if self.context is not None:
            owners.append(self.context)
            inner_context = getattr(self.context, "context", None)
            if inner_context is not None and inner_context is not self.context:
                owners.append(inner_context)
        for owner in owners:
            for name in names:
                if isinstance(owner, dict):
                    func = owner.get(name)
                else:
                    func = getattr(owner, name, None)
                if callable(func):
                    return func
        return None

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
            raise RuntimeError(
                "failed to import txl from cfquant.tx or tx.py: %s; fallback: %s"
                % (package_error, path_error)
            )

    def _default_log_file(self):
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

    def _log(self, msg, force=False):
        if not force and not get_log_enabled():
            return
        msg = translate_log(msg)
        line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if self.show:
            print(msg)


def start_tx_trade_bridge(
    context,
    ip="127.0.0.1",
    port=2049,
    token="LTtx",
    request_channel="cfquant.request",
    bridge_id="default",
    account_id="",
    show=True,
):
    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return TxTradeBridge(
        context,
        ip=ip,
        port=port,
        token=token,
        request_channel=request_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
    )
