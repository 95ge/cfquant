# -*- coding: utf-8 -*-
import itertools
import os
import threading
import atexit

from .client import LTtxRpcClient
from .config import get_config
from .channels import channels_for_bridge
from .protocol import new_id
from . import xtconstant
from .xttype import (
    XtAsset,
    XtAccountStatus,
    XtBankTransferResponse,
    XtCancelOrderResponse,
    XtCancelError,
    XtOrder,
    XtOrderError,
    XtOrderResponse,
    XtPosition,
    XtSmtAppointmentResponse,
    XtTrade,
    to_objects,
)


_trade_client = None
_trade_client_lock = threading.Lock()


def get_trade_client():
    global _trade_client

    with _trade_client_lock:
        if _trade_client is None:
            _trade_client = _new_trade_client()
        return _trade_client


def close_trade_client():
    global _trade_client

    with _trade_client_lock:
        client = _trade_client
        _trade_client = None
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _trade_request(action, params=None, timeout=None):
    return get_trade_client().request(action, params or {}, timeout=timeout)


def _new_trade_client(client_id=None):
    cfg = get_config()
    trade_channel = os.environ.get(
        "CFQUANT_TRADE_REQUEST_CHANNEL",
        channels_for_bridge(cfg.get("bridge_id"))["trade"],
    )
    return LTtxRpcClient(
        host=cfg["host"],
        port=cfg["port"],
        token=cfg["token"],
        request_channel=trade_channel,
        timeout=cfg["timeout"],
        client_id=client_id or new_id("trade_client"),
    )


atexit.register(close_trade_client)


class XtQuantTraderCallback(object):
    def on_connected(self):
        pass

    def on_disconnected(self):
        pass

    def on_account_status(self, status):
        pass

    def on_stock_asset(self, asset):
        pass

    def on_stock_order(self, order):
        pass

    def on_stock_trade(self, trade):
        pass

    def on_stock_position(self, position):
        pass

    def on_order_error(self, order_error):
        pass

    def on_cancel_error(self, cancel_error):
        pass

    def on_order_stock_async_response(self, response):
        pass

    def on_cancel_order_stock_async_response(self, response):
        pass

    def on_bank_transfer_async_response(self, response):
        pass

    def on_ctp_internal_transfer_async_response(self, response):
        pass

    def on_smt_appointment_async_response(self, response):
        pass


class XtQuantTrader(object):
    _seq = itertools.count(1)
    _event_types = {
        "on_connected": None,
        "on_disconnected": None,
        "on_account_status": XtAccountStatus,
        "on_stock_asset": XtAsset,
        "on_stock_order": XtOrder,
        "on_stock_trade": XtTrade,
        "on_stock_position": XtPosition,
        "on_order_error": XtOrderError,
        "on_cancel_error": XtCancelError,
        "on_order_stock_async_response": XtOrderResponse,
        "on_cancel_order_stock_async_response": XtCancelOrderResponse,
        "on_bank_transfer_async_response": XtBankTransferResponse,
        "on_ctp_internal_transfer_async_response": XtBankTransferResponse,
        "on_smt_appointment_async_response": XtSmtAppointmentResponse,
    }

    def __init__(self, path="", session_id=0, callback=None, account=None):
        self.path = path
        self.session_id = session_id
        self.callback = callback or XtQuantTraderCallback()
        self.account = account
        self.account_id = _account_id(account)
        self.client_id = new_id("trade_client_%s" % _safe_client_part(self.account_id))
        self._client = None
        self.connected = False
        self._registered_events = set()
        self._subscribed_accounts = set()
        self.timeout = 0
        self.relaxed_response_order_enabled = False

    def start(self):
        self._get_client().start()
        self._register_trader_events()
        if self.account is not None and self.account_id not in self._subscribed_accounts:
            self.subscribe(self.account)
        self.connected = True

    def stop(self):
        was_connected = self.connected
        self.connected = False
        for account_id in list(self._subscribed_accounts):
            try:
                self._trade_request("xttrader.unsubscribe", {
                    "account": {
                        "account_id": account_id,
                        "account_type": xtconstant.SECURITY_ACCOUNT,
                    },
                }, timeout=2)
            except Exception:
                pass
        self._subscribed_accounts.clear()
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        if was_connected:
            self._emit_noarg_callback("on_disconnected")

    def connect(self):
        try:
            self.start()
            self._trade_request("cfquant.ping", timeout=3)
            self.connected = True
            self._emit_noarg_callback("on_connected")
            return 0
        except Exception:
            self.connected = False
            return -1

    def disconnect(self):
        self.stop()
        return 0

    def register_callback(self, callback):
        self.callback = callback
        self._register_trader_events()

    def subscribe(self, account):
        account = self._resolve_account(account)
        result = self._trade_request("xttrader.subscribe", {
            "account": _account_payload(account),
        })
        self._subscribed_accounts.add(_account_id(account))
        return result

    def unsubscribe(self, account):
        account = self._resolve_account(account)
        result = self._trade_request("xttrader.unsubscribe", {
            "account": _account_payload(account),
        })
        self._subscribed_accounts.discard(_account_id(account))
        return result

    def set_timeout(self, timeout=0):
        self.timeout = timeout
        client = self._client
        if client is not None and timeout:
            client.timeout = float(timeout)

    def set_relaxed_response_order_enabled(self, enabled):
        self.relaxed_response_order_enabled = bool(enabled)

    def sleep(self, time):
        import time as _time

        _time.sleep(time)

    def common_op_sync_with_seq(self, seq, callable):
        func = callable[0]
        args = callable[1:]
        return func(*args)

    def common_op_async_with_seq(self, seq, callable, callback):
        result = self.common_op_sync_with_seq(seq, callable)
        if callable_callback(callback):
            callback(result)
        return seq

    def order_stock(
        self,
        account,
        stock_code,
        order_type,
        order_volume,
        price_type,
        price,
        strategy_name="",
        order_remark="",
    ):
        result = self._trade_request("xttrader.order_stock", {
            "account": _account_payload(account),
            "stock_code": stock_code,
            "order_type": order_type,
            "order_volume": order_volume,
            "price_type": price_type,
            "price": price,
            "strategy_name": strategy_name,
            "order_remark": order_remark,
        })
        if isinstance(result, dict):
            return result.get("order_id", -1)
        return result

    def order_stock_async(self, account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""):
        seq = next(self._seq)
        self._trade_request("xttrader.order_stock_async", {
            "account": _account_payload(account),
            "stock_code": stock_code,
            "order_type": order_type,
            "order_volume": order_volume,
            "price_type": price_type,
            "price": price,
            "strategy_name": strategy_name,
            "order_remark": order_remark,
            "seq": seq,
        })
        return seq

    def cancel_order_stock(self, account, order_id):
        result = self._trade_request("xttrader.cancel_order_stock", {
            "account": _account_payload(account),
            "order_id": order_id,
        })
        if isinstance(result, dict):
            return result.get("cancel_result", -1)
        return result

    def cancel_order_stock_async(self, account, order_id):
        seq = next(self._seq)
        self._trade_request("xttrader.cancel_order_stock_async", {
            "account": _account_payload(account),
            "order_id": order_id,
            "seq": seq,
        })
        return seq

    def cancel_order_stock_sysid(self, account, market, sysid):
        result = self._trade_request("xttrader.cancel_order_stock_sysid", {
            "account": _account_payload(account),
            "market": market,
            "sysid": sysid,
        })
        if isinstance(result, dict):
            return result.get("cancel_result", -1)
        return result

    def cancel_order_stock_sysid_async(self, account, market, sysid):
        seq = next(self._seq)
        self._trade_request("xttrader.cancel_order_stock_sysid_async", {
            "account": _account_payload(account),
            "market": market,
            "sysid": sysid,
            "seq": seq,
        })
        return seq

    def query_stock_asset(self, account):
        result = self._trade_request("xttrader.query_stock_asset", {
            "account": _account_payload(account),
        })
        return XtAsset.from_any(result)

    def query_stock_asset_async(self, account, callback):
        result = self.query_stock_asset(account)
        if callable_callback(callback):
            callback(result)
        return None

    def query_stock_orders(self, account, cancelable_only=False):
        result = self._trade_request("xttrader.query_stock_orders", {
            "account": _account_payload(account),
            "cancelable_only": cancelable_only,
        })
        return to_objects(result, XtOrder)

    def query_stock_orders_async(self, account, callback, cancelable_only=False):
        seq = next(self._seq)
        result = self.query_stock_orders(account, cancelable_only=cancelable_only)
        if callable_callback(callback):
            callback(result)
        return seq

    def query_stock_order(self, account, order_id):
        orders = self.query_stock_orders(account) or []
        for order in orders:
            if getattr(order, "order_id", None) == order_id or getattr(order, "m_strOrderSysID", None) == str(order_id):
                return order
        return None

    def query_stock_trades(self, account):
        result = self._trade_request("xttrader.query_stock_trades", {
            "account": _account_payload(account),
        })
        return to_objects(result, XtTrade)

    def query_stock_trades_async(self, account, callback):
        seq = next(self._seq)
        result = self.query_stock_trades(account)
        if callable_callback(callback):
            callback(result)
        return seq

    def query_stock_positions(self, account):
        result = self._trade_request("xttrader.query_stock_positions", {
            "account": _account_payload(account),
        })
        return to_objects(result, XtPosition)

    def query_stock_positions_async(self, account, callback):
        seq = next(self._seq)
        result = self.query_stock_positions(account)
        if callable_callback(callback):
            callback(result)
        return seq

    def query_stock_position(self, account, stock_code):
        positions = self.query_stock_positions(account) or []
        for position in positions:
            if getattr(position, "stock_code", None) == stock_code:
                return position
            qmt_code = "%s.%s" % (getattr(position, "m_strInstrumentID", ""), getattr(position, "m_strExchangeID", ""))
            if qmt_code == stock_code:
                return position
        return None

    def query_account_info(self):
        return self._compat_request("query_account_info")

    def query_account_infos(self):
        return self._compat_request("query_account_infos")

    def query_account_infos_async(self, callback):
        return self._async_compat_request("query_account_infos", {}, callback)

    def query_account_status(self):
        return self._compat_request("query_account_status")

    def query_account_status_async(self, callback):
        return self._async_compat_request("query_account_status", {}, callback)

    def query_com_fund(self, account):
        return self._compat_account_request("query_com_fund", account)

    def query_com_position(self, account):
        return self._compat_account_request("query_com_position", account)

    def query_position_statistics(self, account):
        return self._compat_account_request("query_position_statistics", account)

    def query_secu_account(self, account):
        return self._compat_account_request("query_secu_account", account)

    def query_credit_detail(self, account):
        return self._compat_account_request("query_credit_detail", account)

    def query_credit_detail_async(self, account, callback):
        return self._async_compat_request("query_credit_detail", self._account_params(account), callback)

    def query_credit_subjects(self, account):
        return self._compat_account_request("query_credit_subjects", account)

    def query_credit_subjects_async(self, account, callback):
        return self._async_compat_request("query_credit_subjects", self._account_params(account), callback)

    def query_credit_slo_code(self, account):
        return self._compat_account_request("query_credit_slo_code", account)

    def query_credit_slo_code_async(self, account, callback):
        return self._async_compat_request("query_credit_slo_code", self._account_params(account), callback)

    def query_credit_assure(self, account):
        return self._compat_account_request("query_credit_assure", account)

    def query_credit_assure_async(self, account, callback):
        return self._async_compat_request("query_credit_assure", self._account_params(account), callback)

    def query_stk_compacts(self, account):
        return self._compat_account_request("query_stk_compacts", account)

    def query_stk_compacts_async(self, account, callback):
        return self._async_compat_request("query_stk_compacts", self._account_params(account), callback)

    def query_ipo_data(self):
        return self._compat_request("query_ipo_data")

    def query_ipo_data_async(self, callback):
        return self._async_compat_request("query_ipo_data", {}, callback)

    def query_new_purchase_limit(self, account):
        return self._compat_account_request("query_new_purchase_limit", account)

    def query_new_purchase_limit_async(self, account, callback):
        return self._async_compat_request("query_new_purchase_limit", self._account_params(account), callback)

    def query_bank_info(self, account):
        return self._compat_account_request("query_bank_info", account)

    def query_bank_amount(self, account, bank_no, bank_account, bank_pwd):
        return self._compat_account_request("query_bank_amount", account, [bank_no, bank_account, bank_pwd])

    def query_bank_transfer_stream(self, account, start_date, end_date, bank_no="", bank_account=""):
        return self._compat_account_request("query_bank_transfer_stream", account, [start_date, end_date, bank_no, bank_account])

    def bank_transfer_in(self, account, bank_no, bank_account, balance, bank_pwd="", fund_pwd=""):
        return self._compat_account_request("bank_transfer_in", account, [bank_no, bank_account, balance, bank_pwd, fund_pwd])

    def bank_transfer_in_async(self, account, bank_no, bank_account, balance, bank_pwd="", fund_pwd=""):
        return self._async_compat_request(
            "bank_transfer_in",
            self._account_params(account, [bank_no, bank_account, balance, bank_pwd, fund_pwd]),
            self._object_callback("on_bank_transfer_async_response", XtBankTransferResponse),
        )

    def bank_transfer_out(self, account, bank_no, bank_account, balance, bank_pwd="", fund_pwd=""):
        return self._compat_account_request("bank_transfer_out", account, [bank_no, bank_account, balance, bank_pwd, fund_pwd])

    def bank_transfer_out_async(self, account, bank_no, bank_account, balance, bank_pwd="", fund_pwd=""):
        return self._async_compat_request(
            "bank_transfer_out",
            self._account_params(account, [bank_no, bank_account, balance, bank_pwd, fund_pwd]),
            self._object_callback("on_bank_transfer_async_response", XtBankTransferResponse),
        )

    def fund_transfer(self, account, transfer_direction, price):
        return self._compat_account_request("fund_transfer", account, [transfer_direction, price])

    def secu_transfer(self, account, transfer_direction, stock_code, volume, transfer_type):
        return self._compat_account_request("secu_transfer", account, [transfer_direction, stock_code, volume, transfer_type])

    def ctp_transfer_future_to_option(self, opt_account_id, ft_account_id, balance):
        return self._compat_request("ctp_transfer_future_to_option", {"args": [opt_account_id, ft_account_id, balance]})

    def ctp_transfer_future_to_option_async(self, opt_account_id, ft_account_id, balance):
        return self._async_compat_request(
            "ctp_transfer_future_to_option",
            {"args": [opt_account_id, ft_account_id, balance]},
            self._object_callback("on_ctp_internal_transfer_async_response", XtBankTransferResponse),
        )

    def ctp_transfer_option_to_future(self, opt_account_id, ft_account_id, balance):
        return self._compat_request("ctp_transfer_option_to_future", {"args": [opt_account_id, ft_account_id, balance]})

    def ctp_transfer_option_to_future_async(self, opt_account_id, ft_account_id, balance):
        return self._async_compat_request(
            "ctp_transfer_option_to_future",
            {"args": [opt_account_id, ft_account_id, balance]},
            self._object_callback("on_ctp_internal_transfer_async_response", XtBankTransferResponse),
        )

    def query_data(self, account, result_path, data_type, start_time=None, end_time=None, user_param={}):
        return self._compat_account_request("query_data", account, [result_path, data_type, start_time, end_time, user_param])

    def export_data(self, account, result_path, data_type, start_time=None, end_time=None, user_param={}):
        return self._compat_account_request("export_data", account, [result_path, data_type, start_time, end_time, user_param])

    def sync_transaction_from_external(self, operation, data_type, account, deal_list):
        return self._compat_account_request("sync_transaction_from_external", account, [operation, data_type, deal_list])

    def smt_query_compact(self, account):
        return self._compat_account_request("smt_query_compact", account)

    def smt_query_order(self, account):
        return self._compat_account_request("smt_query_order", account)

    def smt_query_quoter(self, account):
        return self._compat_account_request("smt_query_quoter", account)

    def smt_appointment_order_async(self, account, order_code, date, amount, apply_rate):
        return self._async_compat_request(
            "smt_appointment_order",
            self._account_params(account, [order_code, date, amount, apply_rate]),
            self._object_callback("on_smt_appointment_async_response", XtSmtAppointmentResponse),
        )

    def smt_appointment_cancel_async(self, account, apply_id):
        return self._async_compat_request(
            "smt_appointment_cancel",
            self._account_params(account, [apply_id]),
            self._object_callback("on_smt_appointment_async_response", XtSmtAppointmentResponse),
        )

    def smt_negotiate_order_async(self, account, src_group_id, order_code, date, amount, apply_rate, dict_param={}):
        return self._async_compat_request(
            "smt_negotiate_order",
            self._account_params(account, [src_group_id, order_code, date, amount, apply_rate, dict_param]),
            self._object_callback("on_smt_appointment_async_response", XtSmtAppointmentResponse),
        )

    def smt_compact_return_async(self, account, src_group_id, cash_compact_id, order_code, occur_amount):
        return self._async_compat_request(
            "smt_compact_return",
            self._account_params(account, [src_group_id, cash_compact_id, order_code, occur_amount]),
            self._object_callback("on_smt_appointment_async_response", XtSmtAppointmentResponse),
        )

    def smt_compact_renewal_async(self, account, cash_compact_id, order_code, defer_days, defer_num, apply_rate):
        return self._async_compat_request(
            "smt_compact_renewal",
            self._account_params(account, [cash_compact_id, order_code, defer_days, defer_num, apply_rate]),
            self._object_callback("on_smt_appointment_async_response", XtSmtAppointmentResponse),
        )

    def run_forever(self):
        import time

        self.start()
        while True:
            time.sleep(1)

    def _register_trader_events(self):
        client = self._get_client()
        for name in self._event_types:
            event_name = "trader:%s" % name
            if event_name in self._registered_events:
                continue
            client.add_callback(event_name, self._make_trader_handler(name))
            self._registered_events.add(event_name)

    def _make_trader_handler(self, name):
        def handler(data):
            data_account_id = _event_account_id(data)
            if self.account_id and data_account_id and data_account_id != self.account_id:
                return
            cls = self._event_types.get(name)
            if cls is not None:
                data = cls.from_any(data)
            func = getattr(self.callback, name, None)
            if callable(func):
                if name in ("on_connected", "on_disconnected"):
                    func()
                else:
                    func(data)

        return handler

    def _emit_noarg_callback(self, name):
        func = getattr(self.callback, name, None)
        if callable(func):
            try:
                func()
            except Exception:
                pass

    def _object_callback(self, name, cls):
        func = getattr(self.callback, name, None)
        if not callable(func):
            return None

        def handler(data):
            func(cls.from_any(data))

        return handler

    def _get_client(self):
        if self._client is None:
            self._client = _new_trade_client(client_id=self.client_id)
        return self._client

    def _trade_request(self, action, params=None, timeout=None):
        return self._get_client().request(action, params or {}, timeout=timeout)

    def _resolve_account(self, account):
        account = account or self.account
        if account is None:
            raise ValueError("account is required")
        return account

    def _compat_request(self, method, params=None):
        return self._trade_request("xttrader.%s" % method, params or {})

    def _compat_account_request(self, method, account, args=None, kwargs=None):
        return self._compat_request(method, self._account_params(account, args=args, kwargs=kwargs))

    def _account_params(self, account, args=None, kwargs=None):
        return {
            "account": _account_payload(account),
            "args": list(args or []),
            "kwargs": kwargs or {},
        }

    def _async_compat_request(self, method, params=None, callback=None):
        seq = next(self._seq)
        body = dict(params or {})
        body["seq"] = seq
        result = self._compat_request(method, body)
        if callable_callback(callback):
            callback(result)
        return seq


def _account_payload(account):
    if isinstance(account, dict):
        return {
            "account_id": account.get("account_id") or account.get("m_strAccountID") or "",
            "account_type": account.get("account_type", xtconstant.SECURITY_ACCOUNT),
        }
    return {
        "account_id": account.account_id,
        "account_type": getattr(account, "account_type", xtconstant.SECURITY_ACCOUNT),
    }


def _account_id(account):
    if account is None:
        return ""
    if isinstance(account, dict):
        return str(account.get("account_id") or account.get("m_strAccountID") or "").strip()
    return str(getattr(account, "account_id", "") or getattr(account, "m_strAccountID", "") or "").strip()


def _safe_client_part(value):
    text = str(value or "account").strip()
    result = []
    for char in text:
        result.append(char if char.isalnum() else "_")
    return "".join(result) or "account"


def callable_callback(callback):
    return callback is not None and callable(callback)


def _event_account_id(data):
    if isinstance(data, dict):
        for key in ("account_id", "m_strAccountID", "m_strAccountId", "m_strAccount", "m_accountID"):
            value = data.get(key)
            if value:
                return str(value).strip()
    for name in ("account_id", "m_strAccountID", "m_strAccountId", "m_strAccount", "m_accountID"):
        value = getattr(data, name, None)
        if value:
            return str(value).strip()
    return ""
