# -*- coding: utf-8 -*-
import os
import inspect
import json
import sys
import threading
import time

from .protocol import loads_message, pack_event, pack_response
from .batch_orders import CFTRADER_BATCH_ACTIONS, execute_qmt_batch
from .level2 import L2_GET_PERIODS, L2_PERIODS, l2_query, quote_plain, require_l2_callable, thousand_price
from .version import __version__ as CORE_VERSION
from . import account_routing
from . import order_meta
from .logging_i18n import get_log_enabled, get_log_language, set_log_enabled, set_log_language, translate_log
from .runtime_report import build_qmt_runtime_report, module_source_state, source_sha256, write_qmt_runtime_marker
from .xttype import (
    CreditAssure, CreditSloCode, CreditSubjects, StkCompacts, XtCreditDetail, XtPositionStatistics,
    XtSmtAppointmentResponse,
    filter_cancelable_orders, normalize_order_price_type,
)


_LOADED_SOURCE_SHA256 = source_sha256(__file__)


# A single all-in-one QMT entry can create both a normal bridge and a trade
# bridge against the same ContextInfo. QMT treats every
# set_auto_trade_callback(True) call as a new registration, so keep the
# registration state shared across bridge instances.
_AUTO_TRADE_CALLBACK_LOCK = threading.RLock()
_AUTO_TRADE_CALLBACK_REGISTRY = {}


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


SMT_ASYNC_ARGUMENT_COUNTS = {
    "smt_appointment_order": 4,
    "smt_appointment_cancel": 1,
    "smt_negotiate_order": 6,
    "smt_compact_return": 4,
    "smt_compact_renewal": 5,
}


XTDATA_COMPAT_CANDIDATES = {
    "get_trading_calendar": ("get_trading_calendar",),
    "get_trading_period": ("get_trading_period",),
    "get_kline_trading_period": ("get_kline_trading_period",),
    "get_all_trading_periods": ("get_all_trading_periods",),
    "get_period_list": ("get_period_list",),
    "create_sector": ("create_sector",),
    "add_sector": ("add_sector",),
    "remove_sector": ("remove_sector",),
    "reset_sector": ("reset_sector",),
    "remove_stock_from_sector": ("remove_stock_from_sector",),
    "create_formula": ("create_formula",),
    "call_formula": ("call_formula",),
    "subscribe_formula": ("subscribe_formula",),
    "unsubscribe_formula": ("unsubscribe_formula",),
    "get_formula_result": ("get_formula_result",),
    "get_tabular_data": ("get_tabular_data",),
    "download_tabular_data": ("download_tabular_data", "down_tabular_data"),
    "push_custom_data": ("push_custom_data",),
    "download_sector_data": ("download_sector_data", "down_sector_data"),
    "download_index_weight": ("download_index_weight", "down_index_weight"),
    "download_history_contracts": ("download_history_contracts", "down_history_contracts"),
    "download_holiday_data": ("download_holiday_data", "down_holiday_data"),
    "download_etf_info": ("download_etf_info", "down_etf_info"),
    "download_cb_data": ("download_cb_data", "down_cb_data"),
    "download_his_st_data": ("download_his_st_data", "down_his_st_data"),
    "download_metatable_data": ("download_metatable_data", "down_metatable_data"),
}

XTDATA_MAINCHAIN_UNSUPPORTED = {
    "connect",
    "disconnect",
    "reconnect",
    "get_quote_server_status",
    "watch_quote_server_status",
    "get_quote_server_config",
    "get_data_dir",
    "set_data_dir",
    "read_feather",
    "write_feather",
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
        order_meta_enabled=True,
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
        self.started_at = 0.0
        self.account_type = ""
        self.auto_trade_callback_enabled = False
        self.pending_async_orders = []
        self.pending_async_orders_lock = threading.RLock()
        self.order_request_metadata = {}
        self.order_request_metadata_lock = threading.RLock()
        self.order_meta_enabled = bool(order_meta_enabled)
        self.order_meta_cache = order_meta.OrderMetaCache(self.bridge_id)
        self.order_meta_store_lock = threading.RLock()
        self.order_meta_store_initialized = set()

    def set_context(self, context):
        if self.context is not None and self.context is not context:
            self._release_auto_trade_callback(self.context)
        self.context = context
        if self.account_id:
            self._set_context_account(self.account_id, self.account_type)
        self._enable_auto_trade_callback()
        self._log("tx trade bridge context ready")
        self._publish_runtime_report("context_ready")

    def start(self):
        if self.running:
            return self
        self.running = True
        if not self.started_at:
            self.started_at = time.time()
        txl = self._load_txl()
        self.tx = txl(self.ip, self.port, self.token)
        self.tx.start_tx()
        self.tx.start_txg(self.request_channel)
        self._log(
            "tx trade bridge started LTtx=%s:%s request_channel=%s"
            % (self.ip, self.port, self.request_channel)
        )
        self._publish_runtime_report("start")
        return self

    def close(self):
        self.running = False
        self._release_auto_trade_callback()
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
        if action in CFTRADER_BATCH_ACTIONS:
            return execute_qmt_batch(self, params, msg, action.endswith("_async"))
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
            return self._get_stock_list_in_sector(params)
        if action.startswith("xtdata."):
            return self._dispatch_xtdata_compat(action, params, msg)
        if action.startswith("xttrader."):
            return self._dispatch_xttrader_compat(action, params, msg)
        raise ValueError("unsupported action: %s" % action)

    def _status(self):
        runtime = self._runtime_info()
        status = {
            "bridge": type(self).__name__,
            "bridge_id": self.bridge_id,
            "running": self.running,
            "request_channel": self.request_channel,
            "account_id": self.account_id,
            "version": CORE_VERSION,
            "core_version": CORE_VERSION,
            "runtime_core_version": CORE_VERSION,
            "qmt_runtime_core_version": CORE_VERSION,
            "runtime": runtime,
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

    def _runtime_info(self):
        globals_dict = self.globals_dict or {}
        config = globals_dict.get("RUNTIME_CONFIG") if isinstance(globals_dict.get("RUNTIME_CONFIG"), dict) else {}
        channels = globals_dict.get("BRIDGE_CHANNELS") if isinstance(globals_dict.get("BRIDGE_CHANNELS"), dict) else {}
        if not channels and isinstance(config.get("channels"), dict):
            channels = config.get("channels")
        channel_key = "normal" if "normal" in str(self.request_channel or "").lower() else "trade"
        transport = "pipe" if getattr(self, "pipe_name", "") else "lttx"
        entry_file = ""
        try:
            entry_file = str(globals_dict.get("__file__") or "")
        except Exception:
            entry_file = ""
        return build_qmt_runtime_report(
            reason="status",
            version=CORE_VERSION,
            core_version=CORE_VERSION,
            bridge=type(self).__name__,
            bridge_id=self.bridge_id,
            account_id=self.account_id,
            account_type=self.account_type or config.get("account_type") or globals_dict.get("DEFAULT_ACCOUNT_TYPE"),
            account_key=config.get("account_key"),
            mode=config.get("mode") or transport,
            transport=transport,
            runtime_mode=type(self).__name__,
            channel_key=channel_key,
            request_channel=self.request_channel,
            channels=channels,
            pipe_name=getattr(self, "pipe_name", ""),
            market=config.get("market") or globals_dict.get("QMT_MARKET"),
            market_role=config.get("market_role"),
            market_route_parent_bridge_id=config.get("market_route_parent_bridge_id"),
            config=config,
            globals_dict=globals_dict,
            entry_file=entry_file,
            module_file=__file__,
            started_at=self.started_at,
            extra=module_source_state(__file__, _LOADED_SOURCE_SHA256, self.started_at),
        )

    def _publish_runtime_report(self, reason):
        try:
            channel_key = "normal" if "normal" in str(self.request_channel or "").lower() else "trade"
            if not self.started_at:
                self.started_at = time.time()
            data = self._runtime_info()
            data.update({
                "reason": reason,
                "transport": "pipe" if getattr(self, "pipe_name", "") else "lttx",
                "channel_key": channel_key,
            })
            try:
                config = self.globals_dict.get("RUNTIME_CONFIG") if isinstance(self.globals_dict.get("RUNTIME_CONFIG"), dict) else {}
                entry_file = str((self.globals_dict or {}).get("__file__") or "")
                entry_base_dir = os.path.dirname(os.path.abspath(entry_file)) if entry_file and not entry_file.startswith("<") else ""
                marker = write_qmt_runtime_marker(data, config=config, entry_base_dir=entry_base_dir)
                if marker.get("ok"):
                    self._log(
                        "qmt runtime marker written version=%s reason=%s file=%s"
                        % (data.get("core_version") or "-", reason, marker.get("primary_file") or "")
                    )
                elif marker.get("errors"):
                    self._log("qmt runtime marker write failed reason=%s error=%s" % (reason, "; ".join(marker.get("errors") or [])))
            except Exception as e:
                self._log("qmt runtime marker write failed reason=%s error=%s" % (reason, e))

            tx = self.tx
            if tx is None or not hasattr(tx, "put"):
                return
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            key = "cfquant.qmt.runtime.%s" % self.bridge_id
            tx.put(key, payload)
            tx.put("%s.%s" % (key, channel_key), payload)
            tx.put("%s.version" % key, CORE_VERSION)
            self._log("tx trade runtime report published version=%s reason=%s" % (CORE_VERSION, reason))
        except Exception as e:
            self._log("tx trade runtime report failed:%s" % e)

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
            rows = self._call_trade_detail_data(
                func,
                account_id,
                account_type.lower(),
                detail_type.lower(),
            ) or []
        except Exception as e:
            self._log(
                "query_trade_detail call failed account=%s detail_type=%s error=%s"
                % (account_id, detail_type, e)
            )
            raise

        result = []
        for index, row in enumerate(rows):
            try:
                formatted = self._format_trade_detail(row, detail_type)
                if isinstance(formatted, dict):
                    if not formatted.get("account_id"):
                        formatted["account_id"] = account_id
                    if formatted.get("account_type") in (None, ""):
                        formatted["account_type"] = (
                            account.get("account_type") or params.get("account_type") or account_type.upper()
                        )
                    if detail_type.lower() == "order":
                        self._enrich_order_request_fields(formatted)
                result.append(formatted)
            except Exception as e:
                self._log(
                    "query_trade_detail format failed detail_type=%s index=%s type=%s error=%s"
                    % (detail_type, index, type(row).__name__, e)
                )
                result.append({
                    "format_error": str(e),
                    "raw_type": type(row).__name__,
                })
        if detail_type.lower() == "order" and self._truthy_param(params.get("cancelable_only")):
            result = filter_cancelable_orders(result)
        self._log(
            "query_trade_detail done detail_type=%s count=%s"
            % (detail_type, len(result))
        )
        return result

    def _call_trade_detail_data(self, func, account_id, account_type, detail_type):
        # QMT's fourth argument is strategyname, not ContextInfo.
        variants = [
            ((account_id, account_type, detail_type), {}),
            ((account_id, account_type, detail_type, ""), {}),
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

    def _order_stock(self, params, msg, resolve_order_id=True, capture_previous_id=True):
        passorder = self._get_callable("passorder")
        if not passorder:
            raise NotImplementedError("passorder not found")
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        order_type = self._passorder_optype(params, account_type)
        if not account_id:
            raise ValueError("account_id is required")
        price_type = params.get("price_type", 11)
        order_remark = self._first_param(
            params,
            ("order_remark", "remark", "strategy_name"),
            msg.get("id", "tx_order"),
        )
        strategy_name = params.get("strategy_name", "")
        order_meta_record = None
        if self.order_meta_enabled:
            order_meta_record = self._build_order_meta_record(
                params,
                msg,
                account_id,
                account_type,
                order_type,
                price_type,
                order_remark,
                strategy_name,
            )
            self._publish_order_meta_record(order_meta_record, push=True, persist=True)
        previous_order_id = self._get_last_order_id(account_id, account_type, strategy_name) if capture_previous_id else None
        if order_meta_record is not None:
            order_meta_record["previous_order_id"] = previous_order_id
        try:
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
        except Exception as e:
            if order_meta_record is not None:
                order_meta_record.update({
                    "status": "failed",
                    "error": str(e),
                })
                self._publish_order_meta_record(order_meta_record, push=True, persist=True)
            raise

        failed = self._is_failed_order_result(result)
        order_id = self._normalize_order_id(result)
        if order_meta_record is not None:
            order_meta_record["request_result"] = self._plain_value(result)
            if order_id is not None:
                order_meta_record["order_ref"] = str(order_id)
        if failed:
            if order_meta_record is not None:
                order_meta_record["status"] = "failed"
                self._publish_order_meta_record(order_meta_record, push=True, persist=True)
        else:
            if order_meta_record is not None:
                order_meta_record["status"] = "accepted"
                self._publish_order_meta_record(order_meta_record, push=True, persist=True)
            self._remember_order_request(
                account_id,
                params.get("stock_code", params.get("code", "")),
                order_remark,
                strategy_name,
            )
        if resolve_order_id and order_id is None and not failed:
            order_id = self._find_order_id(
                account_id,
                account_type,
                order_remark,
                strategy_name,
                previous_order_id,
                params,
            )
            if order_meta_record is not None and order_id is not None:
                order_meta_record["order_ref"] = str(order_id)
                order_meta_record["status"] = "bound"
                self._publish_order_meta_record(order_meta_record, push=True, persist=True)
        return {
            "request_result": result,
            "order_id": order_id if order_id is not None else -1,
            "order_remark": order_remark,
            "order_type": order_type,
            "account_type": str(account_type or "").upper(),
            "previous_order_id": previous_order_id,
        }

    def _get_last_order_id(self, account_id, account_type, strategy_name=""):
        func = self._get_callable("get_last_order_id")
        if not func:
            return None
        args = (account_id, str(account_type or "stock").lower(), "order")
        try:
            if strategy_name:
                return self._normalize_order_id(func(*(args + (strategy_name,))))
            return self._normalize_order_id(func(*args))
        except TypeError:
            try:
                return self._normalize_order_id(func(*args))
            except Exception:
                return None
        except Exception:
            return None

    def _find_order_id(self, account_id, account_type, order_remark, strategy_name, previous_order_id, params):
        wait_seconds = params.get("find_order_wait", os.environ.get("CFQUANT_ORDER_ID_WAIT_SECONDS", 2.0))
        try:
            wait_seconds = max(0.0, float(wait_seconds or 0))
        except Exception:
            wait_seconds = 2.0
        deadline = time.time() + wait_seconds
        while True:
            try:
                orders = self._query_trade_detail({
                    "account": {"account_id": account_id, "account_type": account_type},
                }, "order")
                for order in reversed(orders or []):
                    if str(self._first_value(order, ("order_remark", "m_strRemark", "m_strOrderRemark")) or "") != str(order_remark or ""):
                        continue
                    stock_code = str(params.get("stock_code", params.get("code", "")) or "").upper()
                    candidate_code = str(self._first_value(order, ("stock_code", "m_strInstrumentID")) or "").upper()
                    if (
                        stock_code
                        and candidate_code
                        and stock_code != candidate_code
                        and stock_code.split(".", 1)[0] != candidate_code.split(".", 1)[0]
                    ):
                        continue
                    order_id = self._order_id_from_detail(order)
                    if order_id is not None and order_id != previous_order_id:
                        return order_id
            except Exception:
                pass
            # QMT's latest order number is a broker sysid, not the internal ID
            # returned by order queries/callbacks. Wait for the matching detail.
            if time.time() >= deadline:
                return None
            time.sleep(0.05)

    def _order_id_from_detail(self, order):
        for name in ("order_id", "m_nRef", "m_nOrderID", "m_strOrderRef", "m_strOrderID"):
            order_id = self._normalize_order_id(self._get_value(order, name))
            if order_id is not None:
                return order_id
        return None

    def _normalize_order_id(self, value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            if value <= 0:
                return None
            return int(value) if int(value) == value else value
        text = str(value).strip()
        if not text or text in ("0", "-1"):
            return None
        try:
            number = int(text)
            return number if number > 0 else None
        except Exception:
            return None

    def _is_failed_order_result(self, value):
        if value is False:
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value < 0
        return str(value).strip() == "-1" if value is not None else False

    def _build_order_meta_record(
        self,
        params,
        msg,
        account_id,
        account_type,
        order_type,
        price_type,
        order_remark,
        strategy_name,
    ):
        return order_meta.normalize_record(
            {
                "bridge_id": self.bridge_id,
                "account_id": account_id,
                "account_type": str(account_type or "").upper(),
                "stock_code": params.get("stock_code", params.get("code", "")),
                "order_type": order_type,
                "price_type": price_type,
                "price": params.get("price", 0),
                "order_volume": params.get("order_volume", params.get("num", 0)),
                "strategy_name": strategy_name,
                "order_remark": order_remark,
                "user_order_id": order_remark,
                "client_order_id": order_remark,
                "quick_trade": params.get("quick_trade", 2),
                "request_id": (msg or {}).get("id", ""),
                "request_channel": self.request_channel,
                "status": "pending",
                "created_at": time.time(),
            },
            bridge_id=self.bridge_id,
            account_type=account_type,
            account_id=account_id,
        )

    def _publish_order_meta_record(self, record, push=True, persist=True):
        if not self.order_meta_enabled:
            return record
        record = order_meta.normalize_record(record, bridge_id=self.bridge_id)
        self.order_meta_cache.upsert(record)
        payload = order_meta.encode_record(record)
        tx = self.tx
        if tx is None:
            return record
        if push:
            try:
                channel = order_meta.account_meta_channel(
                    record.get("bridge_id") or self.bridge_id,
                    record.get("account_type"),
                    record.get("account_id"),
                )
                tx.push(order_meta.ORDER_META_PUSH_KEY, payload, channel)
            except Exception as e:
                self._log("order meta push failed:%s" % e)
        if persist:
            self._persist_order_meta_record(record, payload=payload)
        return record

    def _persist_order_meta_record(self, record, payload=None):
        if not self.order_meta_enabled:
            return False
        tx = self.tx
        if tx is None:
            return False
        store_key = order_meta.account_store_key(
            record.get("bridge_id") or self.bridge_id,
            record.get("account_type"),
            record.get("account_id"),
        )
        if not store_key:
            return False
        if not self._ensure_order_meta_store(store_key):
            return False
        payload = payload or order_meta.encode_record(record)
        dict_change = getattr(tx, "dict_change", None)
        if not callable(dict_change):
            return False
        ok = False
        for item_key, _ in order_meta.store_entries_for_record(record):
            if not item_key:
                continue
            try:
                dict_change(store_key, item_key, payload)
                ok = True
            except Exception as e:
                self._log("order meta dict_change failed key=%s error=%s" % (store_key, e))
        return ok

    def _ensure_order_meta_store(self, store_key):
        with self.order_meta_store_lock:
            if store_key in self.order_meta_store_initialized:
                return True
            tx = self.tx
            if tx is None:
                return False
            get_func = getattr(tx, "get", None)
            put_func = getattr(tx, "put", None)
            store_value = None
            if callable(get_func):
                try:
                    store_value = get_func(store_key)
                except Exception as e:
                    self._log("order meta get store failed key=%s error=%s" % (store_key, e))
            decoded = store_value if isinstance(store_value, dict) else order_meta.decode_record_payload(store_value)
            if not isinstance(decoded, dict) and callable(put_func):
                try:
                    put_func(store_key, {})
                except Exception as e:
                    self._log("order meta init store failed key=%s error=%s" % (store_key, e))
                    return False
            self.order_meta_store_initialized.add(store_key)
            return True

    def _load_order_meta_store(self, account_id, account_type):
        if not self.order_meta_enabled:
            return {"loaded": 0, "stale": 0}
        tx = self.tx
        if tx is None or not account_id:
            return {"loaded": 0, "stale": 0}
        store_key = order_meta.account_store_key(self.bridge_id, account_type, account_id)
        get_func = getattr(tx, "get", None)
        put_func = getattr(tx, "put", None)
        if not callable(get_func):
            return {"loaded": 0, "stale": 0}
        try:
            store_value = get_func(store_key)
        except Exception as e:
            self._log("order meta load store failed key=%s error=%s" % (store_key, e))
            return {"loaded": 0, "stale": 0}
        if store_value in (None, ""):
            if callable(put_func):
                try:
                    put_func(store_key, {})
                    with self.order_meta_store_lock:
                        self.order_meta_store_initialized.add(store_key)
                except Exception:
                    pass
            return {"loaded": 0, "stale": 0}
        info = self.order_meta_cache.load_store(
            store_value,
            bridge_id=self.bridge_id,
            account_type=account_type,
            account_id=account_id,
        )
        with self.order_meta_store_lock:
            self.order_meta_store_initialized.add(store_key)
        if info.get("loaded") or info.get("stale"):
            self._log(
                "order meta store loaded account=%s type=%s loaded=%s stale=%s"
                % (account_id, str(account_type or "").upper(), info.get("loaded"), info.get("stale"))
            )
        return info

    def _reset_order_meta_store(self, account_id, account_type, reason="manual"):
        if not self.order_meta_enabled:
            return False
        tx = self.tx
        if tx is None or not account_id:
            return False
        store_key = order_meta.account_store_key(self.bridge_id, account_type, account_id)
        put_func = getattr(tx, "put", None)
        if not callable(put_func):
            return False
        try:
            put_func(store_key, {})
            self.order_meta_cache.clear_account(self.bridge_id, account_type, account_id)
            with self.order_meta_store_lock:
                self.order_meta_store_initialized.add(store_key)
            self._log(
                "order meta store reset account=%s type=%s reason=%s"
                % (account_id, str(account_type or "").upper(), reason)
            )
            return True
        except Exception as e:
            self._log("order meta reset failed key=%s error=%s" % (store_key, e))
            return False

    def _order_stock_async(self, params, msg):
        seq = params.get("seq")
        result = self._order_stock(params, msg, resolve_order_id=False)
        request_result = result.get("request_result")
        accepted = not self._is_failed_order_result(request_result)
        if not accepted:
            return {"seq": -1, "accepted": False, "request_result": request_result}

        pending = self._async_order_record(params, msg, result)
        order_id = self._normalize_order_id(result.get("order_id"))
        if order_id is not None:
            self._send_async_order_response(pending, order_id)
        else:
            self._register_pending_async_order(pending)
        return {"seq": seq, "accepted": True, "request_result": request_result}

    def _async_order_record(self, params, msg, result):
        account = params.get("account") or {}
        return {
            "seq": params.get("seq"),
            "client_id": msg.get("client_id") or msg.get("reply_channel"),
            "account_id": account.get("account_id") or params.get("account_id") or self.account_id,
            "account_type": result.get("account_type") or self._account_type_name(
                account.get("account_type") or params.get("account_type")
            ).upper(),
            "stock_code": str(params.get("stock_code", params.get("code", "")) or "").upper(),
            "strategy_name": params.get("strategy_name", ""),
            "order_remark": result.get("order_remark", params.get("order_remark", "")),
            "previous_order_id": result.get("previous_order_id"),
            "created_at": time.time(),
        }

    def _register_pending_async_order(self, record):
        with self.pending_async_orders_lock:
            self._prune_pending_async_orders_locked()
            self.pending_async_orders.append(record)

    def _remember_order_request(self, account_id, stock_code, order_remark, strategy_name):
        key = (
            str(account_id or "").strip(),
            str(stock_code or "").strip().upper().split(".", 1)[0],
            str(order_remark or ""),
        )
        if not key[0] or not key[2]:
            return
        with self.order_request_metadata_lock:
            self.order_request_metadata[key] = str(strategy_name or "")
            while len(self.order_request_metadata) > 1000:
                self.order_request_metadata.pop(next(iter(self.order_request_metadata)))

    def _enrich_order_request_fields(self, order):
        if not isinstance(order, dict):
            return order
        key = (
            str(self._first_value(order, ("account_id", "m_strAccountID")) or "").strip(),
            str(self._first_value(order, ("stock_code", "m_strInstrumentID")) or "").strip().upper().split(".", 1)[0],
            str(self._first_value(order, ("order_remark", "m_strRemark", "m_strOrderRemark")) or ""),
        )
        with self.order_request_metadata_lock:
            strategy_name = self.order_request_metadata.get(key)
        if strategy_name is not None and not order.get("strategy_name"):
            order["strategy_name"] = strategy_name
            if not order.get("m_strStrategyName"):
                order["m_strStrategyName"] = strategy_name
        return order

    def _prune_pending_async_orders_locked(self):
        wait_seconds = os.environ.get("CFQUANT_ASYNC_ORDER_RESPONSE_WAIT_SECONDS", 60.0)
        try:
            wait_seconds = max(1.0, float(wait_seconds or 60.0))
        except Exception:
            wait_seconds = 60.0
        cutoff = time.time() - wait_seconds
        self.pending_async_orders[:] = [
            item for item in self.pending_async_orders
            if item.get("created_at", 0) >= cutoff
        ]

    def _consume_pending_async_order(self, order):
        order_id = self._order_id_from_detail(order)
        if order_id is None:
            return None
        account_id = str(self._first_value(order, ("account_id", "m_strAccountID")) or "").strip()
        order_remark = str(self._first_value(order, ("order_remark", "m_strRemark", "m_strOrderRemark")) or "")
        strategy_name = str(self._first_value(order, ("strategy_name", "m_strStrategyName")) or "")
        stock_code = str(self._first_value(order, ("stock_code", "m_strInstrumentID")) or "").upper()
        stock_code_base = stock_code.split(".", 1)[0]
        with self.pending_async_orders_lock:
            self._prune_pending_async_orders_locked()
            for index, item in enumerate(self.pending_async_orders):
                if account_id and str(item.get("account_id") or "").strip() != account_id:
                    continue
                if item.get("previous_order_id") is not None and order_id == item.get("previous_order_id"):
                    continue
                expected_remark = str(item.get("order_remark") or "")
                expected_strategy = str(item.get("strategy_name") or "")
                if order_remark and expected_remark and order_remark != expected_remark:
                    continue
                if not order_remark and strategy_name and expected_strategy and strategy_name != expected_strategy:
                    continue
                expected_code = str(item.get("stock_code") or "").upper()
                if (
                    expected_code
                    and stock_code
                    and expected_code != stock_code
                    and expected_code.split(".", 1)[0] != stock_code_base
                ):
                    continue
                return self.pending_async_orders.pop(index), order_id
        return None

    def _handle_async_order_callback(self, order):
        matched = self._consume_pending_async_order(order)
        if not matched:
            return False
        record, order_id = matched
        if isinstance(order, dict):
            order["order_remark"] = record.get("order_remark", "")
            order["strategy_name"] = record.get("strategy_name", "")
            if not order.get("m_strRemark"):
                order["m_strRemark"] = record.get("order_remark", "")
            if not order.get("m_strStrategyName"):
                order["m_strStrategyName"] = record.get("strategy_name", "")
        self._send_async_order_response(record, order_id)
        return True

    def _send_async_order_response(self, record, order_id):
        data = {
            "account_type": record.get("account_type"),
            "account_id": record.get("account_id", ""),
            "order_id": order_id,
            "strategy_name": record.get("strategy_name", ""),
            "order_remark": record.get("order_remark", ""),
            "seq": record.get("seq"),
        }
        self._send_trader_event(record.get("client_id"), "on_order_stock_async_response", data)

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
            if self._first_param(row, ("order_remark", "remark", "strategy_name")) is None:
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
        if method in SMT_ASYNC_ARGUMENT_COUNTS:
            return self._smt_request(params, msg, method)
        if method in ("smt_query_quoter", "smt_query_compact", "smt_query_order"):
            self._credit_account_id(params)
            rows = self._generic_xttrader_call(method, params)
            if rows is None:
                return None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("%s requires a list of SMT result dictionaries" % method)
            return self._plain_value(rows)
        if method == "query_position_statistics":
            if self._get_callable("get_trade_detail_data"):
                return self._query_qmt_objects(params, XtPositionStatistics, "get_trade_detail_data", "FUTURE")
            return self._generic_xttrader_call(method, params)
        if method == "query_credit_detail":
            return self._query_credit_detail(params)
        if method == "query_stk_compacts":
            return self._query_stk_compacts(params)
        if method in ("query_credit_assure", "query_credit_subjects", "query_credit_slo_code"):
            self._credit_account_id(params)
            cls, source = {
                "query_credit_assure": (CreditAssure, "get_assure_contract"),
                "query_credit_subjects": (CreditSubjects, "get_assure_contract"),
                "query_credit_slo_code": (CreditSloCode, "get_enable_short_contract"),
            }[method]
            if self._get_callable(source):
                return self._query_qmt_objects(params, cls, source, "CREDIT")
            rows = self._generic_xttrader_call(method, params)
            return self._format_credit_rows(rows, params, cls, method)
        if method == "query_new_purchase_limit":
            func = self._get_callable("get_new_purchase_limit")
            if func:
                return func(self._query_account_id(params))
        if method == "query_ipo_data":
            func = self._get_callable("get_ipo_data")
            if func:
                return func()
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

    def _query_account_id(self, params):
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")
        return account_id

    def _query_credit_detail(self, params):
        account_id = self._credit_account_id(params)
        func = self._get_callable("get_trade_detail_data")
        if not func:
            rows = self._generic_xttrader_call("query_credit_detail", params)
            return self._format_credit_rows(rows, params, XtCreditDetail, "query_credit_detail")
        rows = self._call_trade_detail_data(func, account_id, "credit", "account")
        return self._format_credit_rows(rows, params, XtCreditDetail, "get_trade_detail_data")

    def _smt_request(self, params, msg, method):
        account_id = self._credit_account_id(params)
        seq = params.get("seq")
        client_id = msg.get("client_id") or msg.get("reply_channel")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0 or not client_id:
            raise ValueError("SMT request requires a positive seq and client_id")
        args = list(params.get("args") or [])
        if len(args) != SMT_ASYNC_ARGUMENT_COUNTS[method] or params.get("kwargs"):
            raise ValueError("invalid arguments for %s" % method)
        func = self._get_callable(method)
        if not func:
            raise NotImplementedError(
                "xttrader.%s_async is unavailable: this QMT does not expose %s with a final SMT business response"
                % (method, method)
            )
        # A broker extension must return its final business response. Do not
        # retry a mutating call with alternative signatures or treat an ACK as success.
        raw = func(account_id, *args)
        if raw is False or (isinstance(raw, int) and not isinstance(raw, bool) and raw == -1):
            return {"seq": -1, "accepted": False}
        response = XtSmtAppointmentResponse.from_any(raw)
        if not isinstance(response, XtSmtAppointmentResponse):
            raise RuntimeError("%s returned no final business response; outcome unknown, reconcile before retrying" % method)
        data = self._plain_value(vars(response))
        for name in ("account_id", "m_strAccountID"):
            if data.get(name) not in (None, "", account_id):
                raise ValueError("%s returned a different account" % method)
        for name in ("account_type", "m_nAccountType", "m_strAccountType", "m_nBrokerType"):
            if data.get(name) not in (None, "") and str(data[name]).upper() not in ("3", "CREDIT"):
                raise ValueError("%s returned a non-CREDIT account" % method)
        apply_id = data.get("apply_id")
        valid_apply_id = isinstance(apply_id, str) and bool(apply_id.strip())
        if isinstance(apply_id, int) and not isinstance(apply_id, bool) and apply_id == -1:
            valid_apply_id = data.get("success") is False
        if (not isinstance(data.get("success"), bool)
                or not valid_apply_id
                or not isinstance(data.get("msg"), str)):
            raise RuntimeError("%s returned an incomplete business response; outcome unknown, reconcile before retrying" % method)
        if data["success"] and str(data["apply_id"]) == "-1":
            raise RuntimeError("%s returned success without a valid apply_id" % method)
        data.update(seq=seq, account_id=account_id, account_type=3)
        self._send_trader_event(client_id, "on_smt_appointment_async_response", data)
        return {"seq": seq, "accepted": True}

    def _credit_account_id(self, params):
        account_id = self._query_account_id(params)
        account = params.get("account") or {}
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        if account_type.upper() != "CREDIT":
            raise ValueError("credit query requires a CREDIT account")
        return account_id

    def _query_stk_compacts(self, params):
        account_id = self._credit_account_id(params)
        func = self._get_callable("get_unclosed_compacts")
        if func:
            rows = func(account_id, "CREDIT")
            source = "get_unclosed_compacts"
        else:
            func = self._get_callable("get_debt_contract")
            if func:
                rows = func(account_id)
                source = "get_debt_contract"
            else:
                rows = self._generic_xttrader_call("query_stk_compacts", params)
                source = "query_stk_compacts"
        return self._format_credit_rows(rows, params, StkCompacts, source)

    def _format_credit_rows(self, rows, params, cls, source):
        account_id = self._credit_account_id(params)
        if rows is None:
            return None
        if isinstance(rows, (str, bytes, dict)):
            raise ValueError("%s returned an invalid credit query result" % source)
        result = []
        for row in rows:
            if isinstance(row, dict):
                data = self._plain_value(row)
            else:
                data = {}
                for name in dir(row):
                    if not name.startswith("m_") and name not in ("account_id", "account_type") and name not in cls._field_aliases:
                        continue
                    value = getattr(row, name)
                    if not callable(value):
                        data[name] = self._plain_value(value)
            if not data:
                raise ValueError("%s returned an invalid credit account row" % source)
            for name in ("account_id", "m_strAccountID"):
                if data.get(name) not in (None, "", account_id):
                    raise ValueError("%s returned a different account" % source)
            for name in ("account_type", "m_nAccountType", "m_strAccountType", "m_nBrokerType"):
                if data.get(name) not in (None, "") and str(data[name]).upper() not in ("3", "CREDIT"):
                    raise ValueError("%s returned a non-CREDIT account" % source)
            data["account_id"] = account_id
            data["account_type"] = 3
            if cls is XtCreditDetail and source == "get_trade_detail_data":
                # Cached QMT quotas mean "used", whereas XtCreditDetail defines
                # these two names as "frozen". Preserve them outside SDK fields.
                raw_quotas = {name: data.pop(name) for name in ("m_dFinUsedQuota", "m_dSloUsedQuota") if name in data}
                if raw_quotas:
                    data["cfquant_qmt_fields"] = raw_quotas
            data = dict(vars(cls.from_any(data)))
            data["cfquant_source"] = source
            data["cfquant_missing_fields"] = [name for name in cls._field_aliases if data.get(name) is None]
            result.append(data)
        return result

    def _query_qmt_objects(self, params, cls, source, required_account_type):
        account_id = self._query_account_id(params)
        account = params.get("account") or {}
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        if account_type.upper() != required_account_type:
            raise ValueError("%s requires a %s account" % (cls.__name__, required_account_type))
        func = self._get_callable(source)
        if not func:
            raise NotImplementedError("%s not found" % source)
        if cls is XtPositionStatistics:
            rows = self._call_trade_detail_data(func, account_id, "future", "position_statistics")
        else:
            rows = func(account_id)
        if required_account_type == "CREDIT":
            return self._format_credit_rows(rows, params, cls, source)
        if rows is None:
            return None
        result = []
        for row in rows:
            obj = cls.from_any(row, normalize=self._plain_value)
            if not isinstance(obj, cls):
                raise ValueError("%s returned an invalid query row" % source)
            data = dict(vars(obj))
            if not data.get("account_id"):
                data["account_id"] = account_id
            if str(data["account_id"]) != account_id:
                raise ValueError("%s returned a different account" % source)
            result.append(data)
        return result

    def _dispatch_xtdata_compat(self, action, params, msg):
        method = action.split(".", 1)[1]
        if method in L2_GET_PERIODS:
            return l2_query(self._get_callable("get_market_data_ex"), L2_GET_PERIODS[method], params)
        if method == "get_l2thousand_queue":
            func = require_l2_callable(self._get_callable(method), method)
            return quote_plain(func(params.get("stock_code", ""), gear_num=params.get("gear_num"), price=thousand_price(params)))
        adapters = {
            "get_cb_info": self._get_cb_info,
            "get_divid_factors": self._get_divid_factors,
            "get_sector_list": self._get_sector_list,
            "create_sector_folder": self._create_sector_folder,
            "create_sector": self._create_sector,
            "reset_sector": self._reset_sector,
            "remove_stock_from_sector": self._remove_stock_from_sector,
            "call_formula_batch": self._call_formula_batch,
        }
        if method in adapters:
            return adapters[method](*(params.get("args") or []), **(params.get("kwargs") or {}))
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
        if method in XTDATA_MAINCHAIN_UNSUPPORTED:
            raise NotImplementedError(
                "xtdata.%s belongs to MiniQMT client/local data-dir management and is not implemented in cfquant QMT bridge"
                % method
            )
        if method in XTDATA_COMPAT_CANDIDATES:
            return self._generic_xtdata_call(method, params, msg)
        source = module_source_state(__file__, _LOADED_SOURCE_SHA256, self.started_at)
        hint = "; bridge source changed on disk, restart the QMT process to load the updated module" if source["restart_required"] else ""
        raise NotImplementedError("xtdata.%s is not implemented by cfquant QMT bridge%s" % (method, hint))

    def _generic_xtdata_call(self, method, params, msg=None):
        candidates = XTDATA_COMPAT_CANDIDATES.get(method, (method,))
        func = self._get_callable(*candidates)
        if not func:
            raise NotImplementedError(
                "xtdata.%s requires QMT callable: %s"
                % (method, ", ".join(candidates))
            )
        args = list(params.get("args") or [])
        kwargs = dict(params.get("kwargs") or {})
        callback_event = params.get("callback_event")
        callback_positions = []
        for item in params.get("callback_positions") or []:
            try:
                callback_positions.append(int(item))
            except Exception:
                pass
        client_id = msg.get("client_id") if msg else None

        variants = []
        if callback_event and client_id:
            def callback(data):
                self._send_event(
                    client_id,
                    callback_event,
                    data,
                    meta=self._generic_xtdata_event_meta(params, method, "callback"),
                )

            callback_args = list(args)
            for index in callback_positions:
                if 0 <= index < len(callback_args):
                    callback_args[index] = callback
            if callback_positions:
                variants.append((tuple(callback_args), dict(kwargs)))
            callback_kwargs = dict(kwargs)
            callback_kwargs.setdefault(params.get("callback_name") or "callback", callback)
            variants.append((tuple(args), callback_kwargs))
            variants.append((tuple(args) + (callback,), dict(kwargs)))
        variants.extend([
            (tuple(args), dict(kwargs)),
            ((params,), {}),
            ((), {}),
        ])
        return self._call_variants(func, variants)

    def _generic_xtdata_event_meta(self, params, method, stage):
        meta = {
            "xtdata_generic": True,
            "method": method,
            "stage": stage,
            "bridge_id": self.bridge_id,
        }
        for key in ("job_id", "download_job_id", "stock_code", "stockcode", "period", "start_time", "end_time"):
            value = params.get(key)
            if value not in (None, ""):
                meta[key] = value
        return meta

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
        if params.get("period") in L2_PERIODS:
            return self._get_market_data_ex(params)
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
            False if params.get("period") in L2_PERIODS else params.get("fill_data", True),
        )

    def _get_local_data(self, params):
        modern = self._get_callable("get_market_data_ex")
        if modern:
            # The ninth QMT argument disables subscription and reads local data.
            arguments = (
                params.get("field_list", []),
                params.get("stock_list") or params.get("code_list") or ([params["stock_code"]] if params.get("stock_code") else []),
                params.get("period", "1d"),
                params.get("start_time", ""),
                params.get("end_time", ""),
                params.get("count", -1),
                params.get("dividend_type", "none"),
                params.get("fill_data", True),
                False,
            )
            try:
                signature = inspect.signature(modern)
            except (TypeError, ValueError):
                signature = None
            if signature is not None:
                try:
                    signature.bind(*arguments)
                except TypeError:
                    modern = None
            if modern is not None:
                return modern(*arguments)
        func = self._get_callable("get_local_data")
        if not func:
            raise NotImplementedError("get_local_data requires local QMT data access")
        stock_code = self._first_param(params, ("stock_code", "stockcode", "stock", "code"), "")
        stock_list = self._list_param(params.get("stock_list", params.get("code_list", [])))
        if not stock_code and stock_list:
            return dict((code, self._call_local_data(func, code, params)) for code in stock_list)
        return self._call_local_data(func, stock_code, params)

    def _call_local_data(self, func, stock_code, params):
        start_time = params.get("start_time") or params.get("start_date") or "19700101"
        end_time = params.get("end_time") or params.get("end_date") or "22010101"
        return self._call_variants(func, [
            ((
                stock_code,
                start_time,
                end_time,
                params.get("period", "follow"),
                params.get("divid_type", params.get("dividend_type", "none")),
                params.get("count", -1),
            ), {}),
            ((
                stock_code,
                start_time,
                end_time,
                params.get("period", "follow"),
                params.get("divid_type", params.get("dividend_type", "none")),
            ), {}),
            ((
                stock_code,
                start_time,
                end_time,
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
        params = params or {}
        stock_code = self._first_param(params, ("stock_code", "stockcode", "stock", "code"), "")
        iscomplete = params.get("iscomplete", params.get("is_complete", params.get("complete", False)))
        for name in ("get_instrument_detail", "get_instrumentdetail"):
            func = self._get_callable(name)
            if not func:
                continue
            try:
                if name == "get_instrumentdetail":
                    result = func(stock_code)
                    if isinstance(result, dict):
                        result = dict(result)
                        result["cfquant_detail_partial"] = True
                        result["cfquant_detail_source"] = name
                    return result
                return self._call_variants(func, [((stock_code, iscomplete), {}), ((stock_code,), {})])
            except Exception as e:
                if not self._instrument_detail_callable_missing(e):
                    raise
                self._log("%s unavailable: %s" % (name, e))
        self._log("get_instrument_detail not found, using fallback")
        return self._fallback_instrument_detail(params, stock_code)

    def _require_qmt_callable(self, *names):
        func = self._get_callable(*names)
        if not func:
            raise NotImplementedError("requires QMT callable: %s" % ", ".join(names))
        return func

    def _get_cb_info(self, stockcode):
        # The Python source supplies two fields, not the similarly named VBA API.
        data = self._require_qmt_callable("get_convert_bond_info")(stockcode)
        if data is None or data == {}:
            return data
        if not isinstance(data, dict):
            raise ValueError("QMT get_convert_bond_info must return a dictionary")
        result = {
            "bondCode": stockcode,
            "cfquant_partial": True,
            "cfquant_source": "get_convert_bond_info",
        }
        for source, target in (("stockcode", "stockCode"), ("convert_price", "bondConvPrice")):
            if source in data:
                result[target] = data[source]
        return result

    def _get_divid_factors(self, stock_code):
        return self._require_qmt_callable("get_divid_factors")(stock_code)

    def _get_stock_list_in_sector(self, params):
        func = self._require_qmt_callable("get_stock_list_in_sector")
        sector = params.get("sector_name", "")
        timetag = params.get("real_timetag", -1)
        if timetag == -1:
            return func(sector)
        # Never retry without a requested historical timestamp.
        return func(sector, timetag)

    def _get_sector_list(self):
        func = self._require_qmt_callable("get_sector_list")
        pending, visited, sectors, seen = [""], set(), [], set()
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            if len(visited) > 10000:
                raise ValueError("QMT sector tree exceeds 10000 nodes")
            info = func(node)
            if not isinstance(info, (list, tuple)) or len(info) != 2:
                raise ValueError("QMT get_sector_list must return [sectors, folders]")
            if any(not isinstance(items, (list, tuple)) for items in info):
                raise ValueError("invalid QMT sector tree node")
            if any(not isinstance(name, str) or not name for items in info for name in items):
                raise ValueError("invalid QMT sector or folder name")
            for sector in info[0]:
                if sector not in seen:
                    seen.add(sector)
                    sectors.append(sector)
            pending.extend(reversed(info[1]))
        return sectors

    def _create_sector_folder(self, parent_node, folder_name, overwrite=True):
        return self._require_qmt_callable("create_sector_folder")(parent_node, folder_name, overwrite)

    def _create_sector(self, parent_node, sector_name, overwrite=True):
        return self._require_qmt_callable("create_sector")(parent_node, sector_name, overwrite)

    def _validate_sector_stocks(self, sector_name, stock_list):
        if not isinstance(sector_name, str) or not sector_name.strip():
            raise ValueError("sector_name must be a non-empty string")
        if not isinstance(stock_list, (list, tuple)) or any(
            not isinstance(code, str) or not code.strip() for code in stock_list
        ):
            raise ValueError("stock_list must be a list of non-empty stock codes")

    def _reset_sector(self, sector_name, stock_list):
        self._validate_sector_stocks(sector_name, stock_list)
        return self._require_qmt_callable("reset_sector_stock_list", "reset_sector")(sector_name, list(stock_list))

    def _remove_stock_from_sector(self, sector_name, stock_list):
        self._validate_sector_stocks(sector_name, stock_list)
        func = self._require_qmt_callable("remove_stock_from_sector")
        succeeded = True
        for code in dict.fromkeys(stock_list):
            # Evaluate every deletion; False must not short-circuit the remaining stocks.
            if not func(sector_name, code):
                succeeded = False
        return succeeded

    def _call_formula_batch(self, formula_names, stock_codes, period, start_time="", end_time="",
                            count=-1, dividend_type="none", extend_params=None):
        return self._require_qmt_callable("call_formula_batch")(
            formula_names, stock_codes, period, start_time, end_time, count, dividend_type,
            [] if extend_params is None else extend_params,
        )

    def _instrument_detail_callable_missing(self, error):
        if isinstance(error, NotImplementedError):
            return True
        text = str(error or "").strip().lower().replace("_", " ")
        if not text:
            return False
        missing_markers = ("not found", "not implemented", "unsupported", "no attribute")
        is_detail = "get instrument detail" in text or "get instrumentdetail" in text
        return is_detail and any(marker in text for marker in missing_markers)

    def _fallback_instrument_detail(self, params, stock_code):
        code_info = self._instrument_code_info(stock_code)
        candidates = self._stock_code_candidates(code_info)
        stock_name = self._optional_stock_callable("get_stock_name", candidates)
        stock_type = self._optional_stock_callable("get_stock_type", candidates)
        open_date = self._optional_stock_callable("get_open_date", candidates, prefer_nonzero=True)
        expire_date = self._optional_stock_callable("get_contract_expire_date", candidates, prefer_nonzero=True)
        multiplier = self._optional_stock_callable("get_contract_multiplier", candidates, prefer_nonzero=True)
        is_stock = self._optional_stock_bool("is_stock", candidates)
        is_fund = self._optional_stock_bool("is_fund", candidates)
        is_future = self._optional_stock_bool("is_future", candidates)
        product_id = self._fallback_product_id(code_info, is_stock, is_fund, is_future)
        canonical_code = code_info.get("canonical") or code_info.get("raw") or ""

        detail = {
            "ExchangeID": code_info.get("exchange_id", ""),
            "InstrumentID": code_info.get("instrument_id", ""),
            "InstrumentName": stock_name if stock_name is not None else "",
            "ProductID": product_id,
            "ProductName": product_id,
            "ExchangeCode": code_info.get("exchange_id", ""),
            "RzrkCode": "",
            "UniCode": canonical_code,
            "CreateDate": "",
            "OpenDate": open_date if open_date is not None else "",
            "ExpireDate": expire_date if expire_date is not None else "",
            "TradingDay": time.strftime("%Y%m%d"),
            "PreClose": 0.0,
            "SettlementPrice": 0.0,
            "UpStopPrice": 0.0,
            "DownStopPrice": 0.0,
            "FloatVolumn": 0,
            "TotalVolumn": 0,
            "FloatVolume": 0,
            "TotalVolume": 0,
            "LongMarginRatio": 0.0,
            "ShortMarginRatio": 0.0,
            "PriceTick": 0.0,
            "VolumeMultiple": multiplier if multiplier is not None else 0,
            "MainContract": 0,
            "LastVolume": 0,
            "InstrumentStatus": 0,
            "IsTrading": False,
            "IsRecent": False,
            "HSGTFlag": "",
            "StockCode": canonical_code,
            "stock_code": canonical_code,
            "InputStockCode": code_info.get("raw", ""),
            "cfquant_detail_fallback": True,
            "cfquant_detail_partial": True,
        }
        if stock_type is not None:
            detail["StockType"] = stock_type
        if is_stock is not None:
            detail["IsStock"] = is_stock
        if is_fund is not None:
            detail["IsFund"] = is_fund
        if is_future is not None:
            detail["IsFuture"] = is_future
        return detail

    def _instrument_code_info(self, stock_code):
        raw = str(stock_code or "").strip().upper()
        instrument_id = raw
        exchange_id = ""
        if "." in raw:
            left, right = raw.rsplit(".", 1)
            instrument_id = left.strip()
            exchange_id = self._market_suffix(right.strip())
        elif len(raw) > 2 and raw[:2] in ("SH", "SZ", "BJ") and raw[2:].isdigit():
            exchange_id = self._market_suffix(raw[:2])
            instrument_id = raw[2:]
        elif len(raw) > 2 and raw[-2:] in ("SH", "SZ", "BJ") and raw[:-2].isdigit():
            exchange_id = self._market_suffix(raw[-2:])
            instrument_id = raw[:-2]
        else:
            exchange_id = self._infer_stock_exchange_id(raw)
        canonical = "%s.%s" % (instrument_id, exchange_id) if instrument_id and exchange_id else raw
        return {
            "raw": raw,
            "instrument_id": instrument_id,
            "exchange_id": exchange_id,
            "canonical": canonical,
        }

    def _infer_stock_exchange_id(self, instrument_id):
        code = str(instrument_id or "").strip().upper()
        if not code:
            return ""
        if code.startswith(("43", "83", "87", "88", "92")) and len(code) == 6:
            return "BJ"
        if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
            return "SH"
        if code.startswith(("510", "511", "512", "513", "515", "516", "517", "518", "519", "588", "589")):
            return "SH"
        if code.startswith(("000", "001", "002", "003", "159", "184", "200", "300", "301", "399")):
            return "SZ"
        return ""

    def _stock_code_candidates(self, code_info):
        raw = code_info.get("raw", "")
        instrument_id = code_info.get("instrument_id", "")
        exchange_id = code_info.get("exchange_id", "")
        canonical = code_info.get("canonical", "")
        prefixed = "%s%s" % (exchange_id, instrument_id) if exchange_id in ("SH", "SZ", "BJ") and instrument_id else ""
        values = []
        for value in (raw, canonical, prefixed, instrument_id):
            if value and value not in values:
                values.append(value)
        return values

    def _optional_stock_callable(self, method, candidates, prefer_nonzero=False):
        func = self._get_callable(method)
        if not func:
            return None
        fallback_value = None
        for stock_code in candidates:
            try:
                value = self._plain_value(func(stock_code))
            except Exception:
                continue
            if value is None or value == "":
                continue
            if prefer_nonzero and value in (0, "0", False):
                fallback_value = value
                continue
            return value
        return fallback_value

    def _optional_stock_bool(self, method, candidates):
        func = self._get_callable(method)
        if not func:
            return None
        fallback_value = None
        for stock_code in candidates:
            try:
                value = self._plain_value(func(stock_code))
            except Exception:
                continue
            if value is None or value == "":
                continue
            bool_value = self._coerce_optional_bool(value)
            if bool_value is True:
                return True
            if bool_value is False:
                fallback_value = False
        return fallback_value

    def _coerce_optional_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "y", "on"):
            return True
        if text in ("0", "false", "no", "n", "off"):
            return False
        return bool(text)

    def _fallback_product_id(self, code_info, is_stock, is_fund, is_future):
        if is_fund:
            return "FUND"
        if is_future:
            return "FUTURE"
        if is_stock:
            return "STOCK"
        exchange_id = code_info.get("exchange_id", "")
        instrument_id = code_info.get("instrument_id", "")
        if exchange_id in ("IF", "SF", "DF", "ZF", "INE", "GF"):
            return "FUTURE"
        if instrument_id.startswith(("510", "511", "512", "513", "515", "516", "517", "518", "519", "588", "589", "159")):
            return "FUND"
        if exchange_id in ("SH", "SZ", "BJ"):
            return "STOCK"
        return ""

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
        self.account_type = account_type
        subscriber_key = (account_type.upper(), account_id)
        client_id = ""
        if msg:
            client_id = msg.get("client_id") or msg.get("reply_channel") or ""
        if client_id:
            with self.subscriber_lock:
                self.account_subscribers.setdefault(subscriber_key, set()).add(client_id)
                self.client_accounts.setdefault(client_id, set()).add(subscriber_key)
            account_routing.subscribe(self.bridge_id, account_id, client_id, account_type=account_type)
        self._set_context_account(account_id, account_type)
        self._enable_auto_trade_callback()
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
            self.account_type = ""
        self._log("account unsubscribed account=%s client_id=%s" % (account_id or "-", client_id or "-"))
        return 0

    def _format_trade_detail(self, obj, detail_type):
        detail_type = str(detail_type).lower()
        if detail_type == "order":
            return {
                "account_id": self._get_value(obj, "m_strAccountID"),
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "order_source": self._order_source(obj),
                "order_id": self._first_value(obj, ("m_nRef", "m_nOrderID", "m_strOrderRef", "m_strOrderID")),
                "order_sysid": self._get_value(obj, "m_strOrderSysID"),
                "order_type": self._stock_order_type(obj),
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
                "price_type": normalize_order_price_type(
                    self._first_value(obj, ("price_type", "m_nPriceType", "m_nOrderPriceType")),
                    self._get_value(obj, "m_strExchangeID"),
                ),
                "price": self._first_value(obj, ("m_dLimitPrice", "m_dOrderPrice", "m_dPrice")),
                "traded_price": self._get_value(obj, "m_dTradedPrice"),
                "traded_volume": self._get_value(obj, "m_nVolumeTraded"),
                "trade_amount": self._get_value(obj, "m_dTradeAmount"),
                "order_status": self._get_value(obj, "m_nOrderStatus"),
                "status_msg": self._first_value(obj, ("m_strStatusMsg", "m_strErrorMsg", "m_strCancelInfo", "m_strStatus", "m_strOrderStatus")),
                "strategy_name": self._get_value(obj, "m_strStrategyName"),
                "order_remark": self._first_value(obj, ("m_strRemark", "m_strOrderRemark")),
                "m_strAccountID": self._get_value(obj, "m_strAccountID"),
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
                "m_nRef": self._get_value(obj, "m_nRef"),
                "m_strOrderRef": self._get_value(obj, "m_strOrderRef"),
                "m_nOrderID": self._first_value(obj, ("m_nOrderID", "m_nRef")),
                "m_strOrderID": self._first_value(obj, ("m_strOrderID", "m_strOrderRef")),
                "m_nOrderStatus": self._get_value(obj, "m_nOrderStatus"),
                "m_nOrderSubmitStatus": self._get_value(obj, "m_nOrderSubmitStatus"),
                "m_nVolumeTotal": self._get_value(obj, "m_nVolumeTotal"),
                "m_nErrorID": self._get_value(obj, "m_nErrorID"),
                "m_strErrorMsg": self._get_value(obj, "m_strErrorMsg"),
                "m_strCancelInfo": self._get_value(obj, "m_strCancelInfo"),
                "m_strOptName": self._get_value(obj, "m_strOptName"),
                "m_strOrderStatus": self._get_value(obj, "m_strOrderStatus"),
                "m_nOrderState": self._get_value(obj, "m_nOrderState"),
                "m_strStatus": self._get_value(obj, "m_strStatus"),
                "m_strOrderTime": self._get_value(obj, "m_strOrderTime"),
                "m_strEntrustTime": self._get_value(obj, "m_strEntrustTime"),
                "m_strInsertTime": self._get_value(obj, "m_strInsertTime"),
                "m_strInsertDate": self._get_value(obj, "m_strInsertDate"),
                "m_nOrderTime": self._get_value(obj, "m_nOrderTime"),
                "m_nEntrustTime": self._get_value(obj, "m_nEntrustTime"),
                "m_nInsertTime": self._get_value(obj, "m_nInsertTime"),
                "m_strOrderDate": self._get_value(obj, "m_strOrderDate"),
                "m_strEntrustDate": self._get_value(obj, "m_strEntrustDate"),
                "m_strTradingDay": self._get_value(obj, "m_strTradingDay"),
            }
        if detail_type == "deal":
            return {
                "account_id": self._get_value(obj, "m_strAccountID"),
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "order_type": self._stock_order_type(obj),
                "order_id": self._first_value(obj, ("m_nRef", "m_nOrderID", "m_strOrderRef", "m_strOrderID")),
                "order_sysid": self._get_value(obj, "m_strOrderSysID"),
                "traded_id": self._first_value(obj, ("m_strTradeID", "m_strDealID", "m_nTradeID")),
                "strategy_name": self._get_value(obj, "m_strStrategyName"),
                "order_remark": self._first_value(obj, ("m_strRemark", "m_strOrderRemark")),
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
                "m_strAccountID": self._get_value(obj, "m_strAccountID"),
                "m_nRef": self._get_value(obj, "m_nRef"),
                "m_strOrderRef": self._get_value(obj, "m_strOrderRef"),
                "m_nOrderID": self._first_value(obj, ("m_nOrderID", "m_nRef")),
                "m_strOrderID": self._first_value(obj, ("m_strOrderID", "m_strOrderRef")),
                "m_strOrderSysID": self._get_value(obj, "m_strOrderSysID"),
                "m_strTradeID": self._get_value(obj, "m_strTradeID"),
                "m_strDealID": self._get_value(obj, "m_strDealID"),
                "m_strStrategyName": self._get_value(obj, "m_strStrategyName"),
                "m_strRemark": self._get_value(obj, "m_strRemark"),
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

    def _stock_order_type(self, obj):
        order_type = self._first_value(obj, ("m_nOrderType", "m_nBusinessType"))
        if order_type not in (None, "", 0, "0"):
            return order_type
        market = self._market_suffix(self._get_value(obj, "m_strExchangeID"))
        if market not in ("SH", "SZ", "BJ"):
            return order_type
        try:
            offset_flag = int(self._get_value(obj, "m_nOffsetFlag"))
        except Exception:
            return order_type
        return {48: 23, 49: 24}.get(offset_flag, order_type)

    def _stock_code(self, obj):
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
            for encoding in ("utf-8", "gbk"):
                try:
                    return value.decode(encoding)
                except Exception:
                    pass
            return value.decode("utf-8", errors="replace")
        try:
            item = getattr(value, "item", None)
            if callable(item):
                return self._plain_value(item())
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

    def _truthy_param(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(value)

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

    def _set_context_account(self, account_id, account_type=None):
        if self.context is None or not account_id:
            return
        account_id = str(account_id).strip()
        account_type_text = str(account_type or "").strip().upper()
        try:
            if account_type_text:
                self.context.set_account(account_id, account_type_text)
                self._log("context account set account=%s account_type=%s mode=with_type" % (account_id, account_type_text))
            else:
                self.context.set_account(account_id)
                self._log("context account set account=%s account_type=%s mode=account_only" % (account_id, account_type_text or "-"))
        except Exception as e:
            try:
                self.context.set_account(account_id)
                self._log("context account set account=%s account_type=%s mode=fallback error=%s" % (account_id, account_type_text or "-", e))
            except Exception as fallback_error:
                self._log("context account set failed account=%s account_type=%s error=%s fallback_error=%s" % (account_id, account_type_text or "-", e, fallback_error))
                raise

    def _release_auto_trade_callback(self, context=None):
        context = context or self.context
        if context is None:
            self.auto_trade_callback_enabled = False
            return
        context_key = id(context)
        owner_key = id(self)
        with _AUTO_TRADE_CALLBACK_LOCK:
            record = _AUTO_TRADE_CALLBACK_REGISTRY.get(context_key)
            if record is not None and record.get("context") is context:
                owners = record.get("owners") or set()
                owners.discard(owner_key)
                # There is no portable QMT API to unregister this callback.
                # Keep the enabled marker even when all bridge objects close,
                # so a later bridge for the same ContextInfo does not register
                # the QMT callback a second time.
                record["owners"] = owners
        self.auto_trade_callback_enabled = False

    def _enable_auto_trade_callback(self):
        if self.context is None or self.auto_trade_callback_enabled:
            return

        context = self.context
        context_key = id(context)
        owner_key = id(self)
        with _AUTO_TRADE_CALLBACK_LOCK:
            record = _AUTO_TRADE_CALLBACK_REGISTRY.get(context_key)
            if record is not None and record.get("context") is context and record.get("enabled"):
                record.setdefault("owners", set()).add(owner_key)
                self.auto_trade_callback_enabled = True
                self._log("auto trade callback already enabled; reused shared registration")
                return
            if record is not None and record.get("context") is not context:
                _AUTO_TRADE_CALLBACK_REGISTRY.pop(context_key, None)

            func = getattr(context, "set_auto_trade_callback", None)
            call_with_context = False
            if not callable(func):
                func = self._get_callable("set_auto_trade_callback")
                call_with_context = True
            if not callable(func):
                self._log("auto trade callback enable skipped: set_auto_trade_callback not found")
                return

            try:
                if call_with_context:
                    try:
                        result = func(context, True)
                    except TypeError:
                        result = func(True)
                else:
                    result = func(True)
            except Exception as e:
                self._log("auto trade callback enable failed:%s" % e)
                return

            _AUTO_TRADE_CALLBACK_REGISTRY[context_key] = {
                "context": context,
                "enabled": True,
                "owners": {owner_key},
            }
            self.auto_trade_callback_enabled = True
            self._log("auto trade callback enabled result=%s" % result)

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
