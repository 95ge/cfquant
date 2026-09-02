# -*- coding: utf-8 -*-
from . import xtconstant


class DictObject(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    @classmethod
    def from_any(cls, value):
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if hasattr(value, "__dict__"):
            return cls(**vars(value))
        if isinstance(value, dict):
            return cls(**value)
        return value

    def __repr__(self):
        return "%s(%s)" % (
            type(self).__name__,
            ", ".join("%s=%r" % item for item in sorted(self.__dict__.items())),
        )


_MISSING = object()


def _dict_from_any(value):
    if value is None:
        return None
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    if isinstance(value, dict):
        return dict(value)
    return None


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _first_value(data, names, default=_MISSING):
    for name in names:
        if name not in data:
            continue
        value = data.get(name)
        if not _is_empty(value):
            return value
    return default


def _set_first(data, target, names, default=_MISSING):
    if target in data and not _is_empty(data.get(target)):
        return
    value = _first_value(data, names, default)
    if value is not _MISSING:
        data[target] = value


_CANCELABLE_ORDER_STATUS_VALUES = frozenset((
    getattr(xtconstant, "ORDER_UNREPORTED", 48),
    getattr(xtconstant, "ORDER_WAIT_REPORTING", 49),
    getattr(xtconstant, "ORDER_REPORTED", 50),
    getattr(xtconstant, "ORDER_PART_SUCC", 55),
))

_ORDER_STATUS_FIELD_NAMES = (
    "order_status",
    "m_nOrderStatus",
    "m_nOrderState",
    "m_strOrderStatus",
    "m_strStatus",
)


def _normalize_order_status(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        number = float(text)
        if number.is_integer():
            return int(number)
    except Exception:
        pass
    aliases = {
        "ORDER_UNREPORTED": getattr(xtconstant, "ORDER_UNREPORTED", 48),
        "ORDER_WAIT_REPORTING": getattr(xtconstant, "ORDER_WAIT_REPORTING", 49),
        "ORDER_REPORTED": getattr(xtconstant, "ORDER_REPORTED", 50),
        "ORDER_PART_SUCC": getattr(xtconstant, "ORDER_PART_SUCC", 55),
    }
    return aliases.get(text.upper())


def order_status_from_any(value):
    data = _dict_from_any(value)
    if data is None:
        return None
    status = _first_value(data, _ORDER_STATUS_FIELD_NAMES, default=None)
    return _normalize_order_status(status)


def is_cancelable_order_status(value):
    return _normalize_order_status(value) in _CANCELABLE_ORDER_STATUS_VALUES


def is_cancelable_order(value):
    return order_status_from_any(value) in _CANCELABLE_ORDER_STATUS_VALUES


def filter_cancelable_orders(values):
    if values is None:
        return None
    if isinstance(values, list):
        return [value for value in values if is_cancelable_order(value)]
    return values if is_cancelable_order(values) else None


def _normalize_account_type(value):
    if _is_empty(value):
        return xtconstant.SECURITY_ACCOUNT
    if isinstance(value, str):
        text = value.strip().upper()
        if text.isdigit():
            return int(text)
        aliases = {
            "SECURITY": xtconstant.SECURITY_ACCOUNT,
            "SECURITY_ACCOUNT": xtconstant.SECURITY_ACCOUNT,
            "STOCK_ACCOUNT": xtconstant.SECURITY_ACCOUNT,
            "MARGIN": xtconstant.CREDIT_ACCOUNT,
            "CREDIT_ACCOUNT": xtconstant.CREDIT_ACCOUNT,
        }
        if text in aliases:
            return aliases[text]
        for int_type, str_type in xtconstant.ACCOUNT_TYPE_DICT.items():
            if text == str(str_type).upper():
                return int_type
    return value


def _apply_common_account_fields(data):
    _set_first(data, "account_id", (
        "m_strAccountID",
        "m_strAccountId",
        "m_strAccount",
        "m_accountID",
        "fund_account",
    ), default="")
    account_type = _first_value(data, (
        "account_type",
        "m_nAccountType",
        "m_strAccountType",
    ), default=xtconstant.SECURITY_ACCOUNT)
    data["account_type"] = _normalize_account_type(account_type)


def _exchange_suffix(value):
    if _is_empty(value):
        return ""
    if isinstance(value, int):
        return {0: "SH", 1: "SZ", 70: "BJ"}.get(value, str(value))
    text = str(value).strip().upper()
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
    }
    return aliases.get(text, text)


def _stock_code(data):
    code = _first_value(data, ("stock_code", "code", "ticker"), default="")
    if not _is_empty(code):
        return str(code)
    instrument_id = _first_value(data, (
        "m_strInstrumentID",
        "instrument_id",
        "m_strStockCode",
        "stock_id",
    ), default="")
    if _is_empty(instrument_id):
        return ""
    instrument_id = str(instrument_id)
    if "." in instrument_id:
        return instrument_id
    exchange_id = _exchange_suffix(_first_value(data, (
        "m_strExchangeID",
        "exchange_id",
        "market",
        "m_strMarket",
    ), default=""))
    if exchange_id:
        return "%s.%s" % (instrument_id, exchange_id)
    return instrument_id


def _apply_stock_code_field(data):
    if _is_empty(data.get("stock_code")):
        data["stock_code"] = _stock_code(data)


class StockAccount(object):
    def __new__(cls, account_id, account_type="STOCK", bridge_id=None):
        if not isinstance(account_id, str):
            return "资金账号必须为字符串类型"
        return super(StockAccount, cls).__new__(cls)

    def __init__(self, account_id, account_type="STOCK", bridge_id=None):
        account_type = account_type.upper()
        for int_type, str_type in xtconstant.ACCOUNT_TYPE_DICT.items():
            if account_type == str_type:
                self.account_type = int_type
                self.account_id = account_id
                self.bridge_id = str(bridge_id or "").strip()
                return
        raise Exception("不支持的账号类型：{}！".format(account_type))


class XtAsset(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first(data, "cash", (
            "available",
            "m_dAvailable",
            "m_dEnableBalance",
        ), default=0.0)
        _set_first(data, "frozen_cash", (
            "frozen",
            "frozen_balance",
            "m_dFrozenCash",
            "m_dFrozenBalance",
        ), default=0.0)
        _set_first(data, "market_value", (
            "m_dInstrumentValue",
            "m_dMarketValue",
            "m_dStockValue",
        ), default=0.0)
        _set_first(data, "total_asset", (
            "balance",
            "m_dBalance",
            "assure_asset",
            "m_dAssureAsset",
        ), default=0.0)
        _set_first(data, "fetch_balance", (
            "m_dFetchBalance",
            "fetch_balance",
            "available",
            "m_dAvailable",
            "cash",
        ), default=0.0)
        return cls(**data)


class XtOrder(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _apply_stock_code_field(data)
        _set_first(data, "order_id", (
            "m_nOrderID",
            "m_strOrderID",
        ), default=-1)
        _set_first(data, "order_sysid", (
            "m_strOrderSysID",
            "sysid",
            "m_strOrderID",
        ), default="")
        _set_first(data, "order_time", (
            "entrust_time",
            "insert_time",
            "m_strOrderTime",
            "m_strEntrustTime",
            "m_strInsertTime",
            "m_nOrderTime",
            "m_nEntrustTime",
            "m_nInsertTime",
        ), default="")
        _set_first(data, "order_type", (
            "m_nOrderType",
            "m_nBusinessType",
        ), default=0)
        _set_first(data, "order_volume", (
            "m_nVolumeTotalOriginal",
            "m_nOrderVolume",
            "m_nVolume",
        ), default=0)
        _set_first(data, "price_type", (
            "m_nPriceType",
            "m_nOrderPriceType",
        ), default=0)
        _set_first(data, "price", (
            "m_dLimitPrice",
            "m_dOrderPrice",
            "m_dPrice",
        ), default=0.0)
        _set_first(data, "traded_volume", (
            "m_nVolumeTraded",
            "m_nTradedVolume",
        ), default=0)
        _set_first(data, "traded_price", (
            "m_dTradedPrice",
            "m_dAveragePrice",
        ), default=0.0)
        _set_first(data, "order_status", (
            "m_nOrderStatus",
            "m_nOrderState",
        ), default=getattr(xtconstant, "ORDER_UNKNOWN", 255))
        _set_first(data, "status_msg", (
            "m_strStatusMsg",
            "m_strStatus",
            "m_strOrderStatus",
        ), default="")
        _set_first(data, "strategy_name", (
            "m_strStrategyName",
        ), default="")
        _set_first(data, "order_remark", (
            "m_strRemark",
            "m_strOrderRemark",
        ), default="")
        _set_first(data, "direction", (
            "m_nDirection",
        ), default=0)
        _set_first(data, "offset_flag", (
            "m_nOffsetFlag",
        ), default=0)
        _set_first(data, "secu_account", (
            "m_strSecuAccount",
            "m_strSecurityAccount",
        ), default="")
        _set_first(data, "instrument_name", (
            "m_strInstrumentName",
            "name",
        ), default="")
        return cls(**data)


class XtTrade(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _apply_stock_code_field(data)
        _set_first(data, "order_type", (
            "m_nOrderType",
            "m_nBusinessType",
        ), default=0)
        _set_first(data, "traded_id", (
            "trade_id",
            "deal_id",
            "m_strTradeID",
            "m_strDealID",
            "m_nTradeID",
        ), default="")
        _set_first(data, "traded_time", (
            "trade_time",
            "deal_time",
            "m_strTradeTime",
            "m_strDealTime",
            "m_nTradeTime",
            "m_nDealTime",
        ), default="")
        _set_first(data, "traded_price", (
            "price",
            "m_dPrice",
            "m_dTradedPrice",
        ), default=0.0)
        _set_first(data, "traded_volume", (
            "volume",
            "m_nVolume",
            "m_nVolumeTraded",
        ), default=0)
        _set_first(data, "traded_amount", (
            "trade_amount",
            "m_dTradeAmount",
            "m_dTradedAmount",
        ), default=0.0)
        _set_first(data, "order_id", (
            "m_nOrderID",
            "m_strOrderID",
        ), default=-1)
        _set_first(data, "order_sysid", (
            "m_strOrderSysID",
            "sysid",
            "m_strOrderID",
        ), default="")
        _set_first(data, "strategy_name", (
            "m_strStrategyName",
        ), default="")
        _set_first(data, "order_remark", (
            "m_strRemark",
            "m_strOrderRemark",
        ), default="")
        _set_first(data, "direction", (
            "m_nDirection",
        ), default=0)
        _set_first(data, "offset_flag", (
            "m_nOffsetFlag",
        ), default=0)
        _set_first(data, "commission", (
            "m_dCommission",
        ), default=0.0)
        _set_first(data, "secu_account", (
            "m_strSecuAccount",
            "m_strSecurityAccount",
        ), default="")
        _set_first(data, "instrument_name", (
            "m_strInstrumentName",
            "name",
        ), default="")
        return cls(**data)


class XtPosition(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _apply_stock_code_field(data)
        _set_first(data, "volume", (
            "m_nVolume",
            "m_nPosition",
        ), default=0)
        _set_first(data, "can_use_volume", (
            "m_nCanUseVolume",
            "m_nAvailableVolume",
        ), default=0)
        _set_first(data, "open_price", (
            "m_dOpenPrice",
        ), default=0.0)
        _set_first(data, "market_value", (
            "m_dInstrumentValue",
            "m_dMarketValue",
        ), default=0.0)
        _set_first(data, "frozen_volume", (
            "m_nFrozenVolume",
            "m_nFreezeVolume",
        ), default=0)
        _set_first(data, "on_road_volume", (
            "m_nOnRoadVolume",
            "m_nUncomeVolume",
        ), default=0)
        _set_first(data, "yesterday_volume", (
            "m_nYesterdayVolume",
            "m_nYdPosition",
        ), default=0)
        _set_first(data, "avg_price", (
            "position_cost",
            "m_dPositionCost",
            "m_dAvgPrice",
        ), default=0.0)
        _set_first(data, "direction", (
            "m_nDirection",
        ), default=0)
        _set_first(data, "last_price", (
            "m_dLastPrice",
        ), default=0.0)
        _set_first(data, "profit_rate", (
            "m_dProfitRate",
        ), default=0.0)
        _set_first(data, "secu_account", (
            "m_strSecuAccount",
            "m_strSecurityAccount",
        ), default="")
        _set_first(data, "instrument_name", (
            "m_strInstrumentName",
            "name",
        ), default="")
        return cls(**data)


class XtOrderError(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first(data, "order_id", ("m_nOrderID", "m_strOrderID"), default=-1)
        _set_first(data, "error_id", ("m_nErrorID", "error_code"), default=None)
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        _set_first(data, "strategy_name", ("m_strStrategyName",), default="")
        _set_first(data, "order_remark", ("m_strRemark", "m_strOrderRemark"), default="")
        return cls(**data)


class XtCancelError(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first(data, "order_id", ("m_nOrderID", "m_strOrderID"), default=-1)
        _set_first(data, "market", ("m_nMarket", "m_strExchangeID"), default="")
        _set_first(data, "order_sysid", ("m_strOrderSysID", "sysid", "m_strOrderID"), default="")
        _set_first(data, "error_id", ("m_nErrorID", "error_code"), default=None)
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        return cls(**data)


class XtOrderResponse(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first(data, "order_id", ("m_nOrderID", "m_strOrderID"), default=-1)
        _set_first(data, "strategy_name", ("m_strStrategyName",), default="")
        _set_first(data, "order_remark", ("m_strRemark", "m_strOrderRemark"), default="")
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        _set_first(data, "seq", ("m_nSeq", "request_id"), default=None)
        return cls(**data)


class XtCancelOrderResponse(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first(data, "cancel_result", ("result", "m_nCancelResult"), default=-1)
        _set_first(data, "order_id", ("m_nOrderID", "m_strOrderID"), default=-1)
        _set_first(data, "order_sysid", ("m_strOrderSysID", "sysid", "m_strOrderID"), default="")
        _set_first(data, "seq", ("m_nSeq", "request_id"), default=None)
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        return cls(**data)


class XtAccountStatus(DictObject):
    pass


class XtBankTransferResponse(DictObject):
    pass


class XtSmtAppointmentResponse(DictObject):
    pass


def to_objects(values, cls=DictObject):
    if values is None:
        return None
    if isinstance(values, list):
        return [cls.from_any(v) for v in values]
    return cls.from_any(values)
