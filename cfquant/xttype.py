# -*- coding: utf-8 -*-
import datetime
import re

from . import xtconstant
from .stock_connect import connect_account_type


_QMT_COMPACT_PREFIXES = (
    ("mstr", "m_str"),
    ("md", "m_d"),
    ("mn", "m_n"),
    ("me", "m_e"),
    ("mb", "m_b"),
)


def _compact_qmt_alias(name):
    if not isinstance(name, str) or not name.startswith("m_"):
        return ""
    for _, expanded in _QMT_COMPACT_PREFIXES:
        if name.startswith(expanded) and len(name) > len(expanded):
            suffix = name[len(expanded):]
            if suffix and suffix[0].isupper():
                return "m%s%s" % (expanded[2:], suffix)
    return ""


def _expanded_qmt_alias(name):
    if not isinstance(name, str) or not name.startswith("m"):
        return ""
    for compact, expanded in _QMT_COMPACT_PREFIXES:
        if name.startswith(compact) and len(name) > len(compact):
            suffix = name[len(compact):]
            if suffix and suffix[0].isupper():
                return "%s%s" % (expanded, suffix)
    return ""


def _unique_names(values):
    result = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _with_qmt_compact_aliases(*names):
    values = []
    for name in names:
        if not name:
            continue
        values.append(name)
        values.append(_compact_qmt_alias(name))
        values.append(_expanded_qmt_alias(name))
    return _unique_names(values)


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

    def __getattr__(self, name):
        for alias in (_expanded_qmt_alias(name), _compact_qmt_alias(name)):
            if alias and alias in self.__dict__:
                return self.__dict__[alias]
        raise AttributeError("'%s' object has no attribute '%s'" % (type(self).__name__, name))


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
    for name in _with_qmt_compact_aliases(*names):
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


def _set_first_order_id(data, names, default=-1):
    current = data.get("order_id", _MISSING)
    if current is not _MISSING and not _is_empty(current) and current not in (0, "0", -1, "-1"):
        return
    for name in names:
        if name not in data:
            continue
        value = data.get(name)
        if _is_empty(value) or value in (0, "0", -1, "-1"):
            continue
        data["order_id"] = value
        return
    data["order_id"] = default


def _normalize_order_id_field(data):
    value = data.get("order_id")
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            data["order_id"] = int(text)


def _coerce_int(value, default=0):
    """Normalize canonical xtquant integer fields without touching raw QMT fields."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else default
    text = str(value).strip()
    if not text:
        return default
    try:
        number = float(text)
    except (TypeError, ValueError):
        return default
    return int(number) if number.is_integer() else default


def _coerce_float(value, default=0.0):
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _coerce_text(value, default=""):
    if value is None:
        return default
    return str(value)


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "ok", "success", "accepted"):
        return True
    if text in ("0", "false", "no", "off", "", "none", "null"):
        return False
    return default


def _coerce_timestamp(value, date_value=None, default=0):
    """Convert QMT's display time to MiniQMT's Unix timestamp in seconds."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        if value >= 100000000000:
            return value // 1000
        if value >= 100000000:
            return value
        text = str(value)
    elif isinstance(value, float):
        if value >= 100000000000:
            return int(value / 1000)
        if value >= 100000000:
            return int(value)
        text = str(int(value)) if value.is_integer() else str(value)
    else:
        text = str(value).strip()
    if not text:
        return default
    if re.fullmatch(r"[+-]?\d{9,}", text):
        try:
            number = int(text)
            return number // 1000 if number >= 100000000000 else number
        except ValueError:
            return default
    digits = re.sub(r"\D", "", text)
    if not digits:
        return default
    # HHMMSS / HHMMSSmmm values need the trading date before they can
    # represent the same Unix timestamp exposed by native xtquant.
    if len(digits) not in (5, 6, 8, 9):
        return default
    if len(digits) == 5:
        digits = "0" + digits
    hour, minute, second = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    microsecond = int((digits[6:] + "000000")[:6]) if len(digits) > 6 else 0
    date_text = re.sub(r"\D", "", str(date_value or ""))
    if len(date_text) != 8:
        return default
    try:
        dt = datetime.datetime.strptime(date_text, "%Y%m%d").replace(
            hour=hour, minute=minute, second=second, microsecond=microsecond,
            tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
        )
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return default


def _is_zero_time_value(value):
    """Return whether a time field contains the provider's empty value."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value == 0
    text = str(value).strip()
    if not text:
        return True
    # QMT uses both numeric zero and display forms such as 00:00:00 for an
    # unavailable order/trade time.  Do not discard values such as 000001.
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        try:
            return float(text) == 0
        except (TypeError, ValueError):
            return False
    digits = re.sub(r"\D", "", text)
    return bool(digits) and not set(digits) - {"0"}


def _time_field_timestamp(data, time_names, date_names):
    date_value = None
    for name in _with_qmt_compact_aliases(*date_names):
        if name not in data:
            continue
        candidate = data.get(name)
        if _is_empty(candidate) or _is_zero_time_value(candidate):
            continue
        date_value = candidate
        break
    # A callback can expose a generic ``time``/canonical field as 0 while a
    # later QMT field (for example m_strOrderTime) contains the real value.
    # Try every candidate instead of letting the zero placeholder win.
    for name in _with_qmt_compact_aliases(*time_names):
        if name not in data:
            continue
        value = data.get(name)
        if _is_empty(value) or _is_zero_time_value(value):
            continue
        timestamp = _coerce_timestamp(value, date_value)
        if timestamp:
            return timestamp
    return 0


def normalize_order_price_type(value, market=""):
    """Translate documented QMT broker price enums, preserving unknown values."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return value
    if str(number) != str(value).strip():
        return value
    mapping = {
        50: xtconstant.FIX_PRICE,
        84: xtconstant.MARKET_PEER_PRICE_FIRST,
        86: xtconstant.MARKET_MINE_PRICE_FIRST,
    }
    exchange = _exchange_suffix(market)
    if exchange in ("SH", "BJ"):
        mapping.update({85: xtconstant.MARKET_SH_CONVERT_5_LIMIT, 88: xtconstant.MARKET_SH_CONVERT_5_CANCEL})
    elif exchange == "SZ":
        mapping.update({87: xtconstant.MARKET_SZ_INSTBUSI_RESTCANCEL, 88: xtconstant.MARKET_SZ_CONVERT_5_CANCEL, 89: xtconstant.MARKET_SZ_FULL_OR_CANCEL})
    # Broker ANY (49) does not identify a specific SDK market-order instruction.
    return mapping.get(number, value)


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
        text = connect_account_type(value)
        if text.isdigit():
            return int(text)
        aliases = {
            "FUTURE": xtconstant.FUTURE_ACCOUNT,
            "FUTURE_ACCOUNT": xtconstant.FUTURE_ACCOUNT,
            "SECURITY": xtconstant.SECURITY_ACCOUNT,
            "SECURITY_ACCOUNT": xtconstant.SECURITY_ACCOUNT,
            "STOCK_ACCOUNT": xtconstant.SECURITY_ACCOUNT,
            "MARGIN": xtconstant.CREDIT_ACCOUNT,
            "CREDIT_ACCOUNT": xtconstant.CREDIT_ACCOUNT,
            "FUTURE_OPTION": xtconstant.FUTURE_OPTION_ACCOUNT,
            "FUTURE_OPTION_ACCOUNT": xtconstant.FUTURE_OPTION_ACCOUNT,
            "FUTUREOPTION": xtconstant.FUTURE_OPTION_ACCOUNT,
            "STOCK_OPTION": xtconstant.STOCK_OPTION_ACCOUNT,
            "STOCK_OPTION_ACCOUNT": xtconstant.STOCK_OPTION_ACCOUNT,
            "STOCKOPTION": xtconstant.STOCK_OPTION_ACCOUNT,
            "OPTION": xtconstant.STOCK_OPTION_ACCOUNT,
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
        "broker_type",
        "m_nBrokerType",
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
        account_type = connect_account_type(account_type)
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
        for name in ("cash", "frozen_cash", "market_value", "total_asset", "fetch_balance"):
            data[name] = _coerce_float(data.get(name))
        return cls(**data)


class XtOrder(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _apply_stock_code_field(data)
        _set_first_order_id(data, (
            "m_nRef",
            "m_nOrderID",
            "m_strOrderRef",
            "m_strOrderID",
        ))
        _normalize_order_id_field(data)
        _set_first(data, "order_sysid", (
            "m_strOrderSysID",
            "sysid",
            "m_strOrderID",
        ), default="")
        _set_first(data, "order_time", (
            "time",
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
        data["price_type"] = normalize_order_price_type(
            data["price_type"], data["stock_code"].rsplit(".", 1)[-1],
        )
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
            "m_strErrorMsg",
            "m_strCancelInfo",
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
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["stock_code"] = _coerce_text(data.get("stock_code"))
        data["order_id"] = _coerce_int(data.get("order_id"), -1)
        data["order_sysid"] = _coerce_text(data.get("order_sysid"))
        data["order_time"] = _time_field_timestamp(
            data,
            ("order_time", "time", "entrust_time", "insert_time", "m_strOrderTime", "m_strEntrustTime", "m_strInsertTime", "m_nOrderTime", "m_nEntrustTime", "m_nInsertTime"),
            ("order_date", "entrust_date", "insert_date", "m_strOrderDate", "m_strEntrustDate", "m_strInsertDate", "m_strTradingDay", "m_nOrderDate", "m_nEntrustDate", "m_nInsertDate"),
        )
        for name in ("order_type", "order_volume", "price_type", "traded_volume", "order_status", "direction", "offset_flag"):
            data[name] = _coerce_int(data.get(name))
        for name in ("price", "traded_price"):
            data[name] = _coerce_float(data.get(name))
        for name in ("status_msg", "strategy_name", "order_remark", "secu_account", "instrument_name"):
            data[name] = _coerce_text(data.get(name))
        return cls(**data)


class XtCreditOrder(XtOrder):
    """MiniQMT credit-account order structure."""

    @classmethod
    def from_any(cls, value):
        base = XtOrder.from_any(value)
        if not hasattr(base, "__dict__"):
            return base
        data = vars(base)
        contract_no = _first_value(data, (
            "contract_no",
            "m_strCompactNo",
            "m_strContractNo",
            "m_strCompactID",
            "compact_id",
        ), default="")
        stock_code1 = _first_value(data, (
            "stock_code1",
            "m_stockCode",
            "m_strStockCode1",
            "m_strUnderCode",
        ), default=data.get("stock_code", ""))
        return cls(
            account_id=_coerce_text(data.get("account_id")),
            stock_code=_coerce_text(data.get("stock_code")),
            order_id=_coerce_int(data.get("order_id"), -1),
            order_time=data.get("order_time", 0),
            order_type=_coerce_int(data.get("order_type")),
            order_volume=_coerce_int(data.get("order_volume")),
            price_type=_coerce_int(data.get("price_type")),
            price=_coerce_float(data.get("price")),
            traded_volume=_coerce_int(data.get("traded_volume")),
            traded_price=_coerce_float(data.get("traded_price")),
            order_status=_coerce_int(data.get("order_status")),
            status_msg=_coerce_text(data.get("status_msg")),
            order_remark=_coerce_text(data.get("order_remark")),
            contract_no=_coerce_text(contract_no),
            stock_code1=_coerce_text(stock_code1),
        )

    def __init__(self, account_id, stock_code, order_id, order_time, order_type,
                 order_volume, price_type, price, traded_volume, traded_price,
                 order_status, status_msg, order_remark, contract_no, stock_code1):
        self.account_type = xtconstant.CREDIT_ACCOUNT
        self.account_id = account_id
        self.stock_code = stock_code
        self.order_id = order_id
        self.order_time = order_time
        self.order_type = order_type
        self.order_volume = order_volume
        self.price_type = price_type
        self.price = price
        self.traded_volume = traded_volume
        self.traded_price = traded_price
        self.order_status = order_status
        self.status_msg = status_msg
        self.order_remark = order_remark
        self.contract_no = contract_no
        self.stock_code1 = stock_code1


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
        if data.get("order_type") in (None, "", 0, "0"):
            try:
                offset_flag = int(data.get("m_nOffsetFlag"))
            except (TypeError, ValueError):
                offset_flag = None
            if offset_flag in (48, 49):
                data["order_type"] = xtconstant.STOCK_BUY if offset_flag == 48 else xtconstant.STOCK_SELL
        _set_first(data, "traded_id", (
            "trade_id",
            "deal_id",
            "m_strTradeID",
            "m_strDealID",
            "m_nTradeID",
            "m_nDealID",
        ), default="")
        _set_first(data, "traded_time", (
            "time",
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
        _set_first_order_id(data, (
            "m_nRef",
            "m_nOrderID",
            "m_strOrderRef",
            "m_strOrderID",
        ))
        _normalize_order_id_field(data)
        _set_first(data, "order_sysid", (
            "m_strOrderSysID",
            "sysid",
            "m_strOrderRef",
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
            "m_dComssion",
        ), default=0.0)
        _set_first(data, "secu_account", (
            "m_strSecuAccount",
            "m_strSecurityAccount",
        ), default="")
        _set_first(data, "instrument_name", (
            "m_strInstrumentName",
            "name",
        ), default="")
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["stock_code"] = _coerce_text(data.get("stock_code"))
        data["order_type"] = _coerce_int(data.get("order_type"))
        data["traded_id"] = _coerce_text(data.get("traded_id"))
        data["traded_time"] = _time_field_timestamp(
            data,
            ("traded_time", "time", "trade_time", "deal_time", "m_strTradeTime", "m_strDealTime", "m_nTradeTime", "m_nDealTime"),
            ("trade_date", "deal_date", "m_strTradeDate", "m_strDealDate", "m_strTradingDay", "m_nTradeDate", "m_nDealDate"),
        )
        for name in ("traded_volume",):
            data[name] = _coerce_int(data.get(name))
        for name in ("traded_price", "traded_amount", "commission"):
            data[name] = _coerce_float(data.get(name))
        data["order_id"] = _coerce_int(data.get("order_id"), -1)
        data["order_sysid"] = _coerce_text(data.get("order_sysid"))
        for name in ("direction", "offset_flag"):
            data[name] = _coerce_int(data.get(name))
        for name in ("strategy_name", "order_remark", "secu_account", "instrument_name"):
            data[name] = _coerce_text(data.get(name))
        return cls(**data)


class XtCreditDeal(DictObject):
    """MiniQMT credit-account trade structure."""

    @classmethod
    def from_any(cls, value):
        base = XtTrade.from_any(value)
        if not hasattr(base, "__dict__"):
            return base
        data = vars(base)
        contract_no = _first_value(data, (
            "contract_no",
            "m_strCompactNo",
            "m_strContractNo",
            "m_strCompactID",
            "compact_id",
        ), default="")
        stock_code1 = _first_value(data, (
            "stock_code1",
            "m_stockCode",
            "m_strStockCode1",
            "m_strUnderCode",
        ), default=data.get("stock_code", ""))
        return cls(
            account_id=_coerce_text(data.get("account_id")),
            stock_code=_coerce_text(data.get("stock_code")),
            traded_id=_coerce_text(data.get("traded_id")),
            traded_time=data.get("traded_time", 0),
            traded_price=_coerce_float(data.get("traded_price")),
            traded_volume=_coerce_int(data.get("traded_volume")),
            order_id=_coerce_int(data.get("order_id"), -1),
            contract_no=_coerce_text(contract_no),
            stock_code1=_coerce_text(stock_code1),
        )

    def __init__(self, account_id, stock_code, traded_id, traded_time,
                 traded_price, traded_volume, order_id, contract_no, stock_code1):
        self.account_type = xtconstant.CREDIT_ACCOUNT
        self.account_id = account_id
        self.stock_code = stock_code
        self.traded_id = traded_id
        self.traded_time = traded_time
        self.traded_price = traded_price
        self.traded_volume = traded_volume
        self.order_id = order_id
        self.contract_no = contract_no
        self.stock_code1 = stock_code1


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
            "m_strStockHolder",
            "m_strSecuAccount",
            "m_strSecurityAccount",
        ), default="")
        _set_first(data, "stock_holder", (
            "m_strStockHolder",
            "m_strShareholderID",
            "m_strShareHolder",
            "m_strSecuAccount",
            "m_strSecurityAccount",
            "m_strStockAccount",
        ), default=data.get("secu_account", ""))
        _set_first(data, "branch_id", (
            "m_strBranchID",
            "m_nBranchID",
            "m_strBranch",
            "m_nBranch",
        ), default="")
        _set_first(data, "branch_name", (
            "m_strBranchName",
        ), default="")
        _set_first(data, "instrument_name", (
            "m_strInstrumentName",
            "name",
        ), default="")
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["stock_code"] = _coerce_text(data.get("stock_code"))
        for name in ("volume", "can_use_volume", "frozen_volume", "on_road_volume", "yesterday_volume", "direction"):
            data[name] = _coerce_int(data.get(name))
        for name in ("open_price", "market_value", "avg_price", "last_price", "profit_rate"):
            data[name] = _coerce_float(data.get(name))
        for name in ("secu_account", "stock_holder", "branch_id", "branch_name", "instrument_name"):
            data[name] = _coerce_text(data.get(name))
        return cls(**data)


class _QmtQueryObject(DictObject):
    _field_aliases = {}
    _extra_aliases = {}
    _account_type = xtconstant.CREDIT_ACCOUNT

    @classmethod
    def _expanded_aliases(cls, aliases):
        expanded = {}
        for target, sources in aliases.items():
            expanded[target] = tuple(_with_qmt_compact_aliases(target, *(sources or ())))
        return expanded

    @classmethod
    def known_field_names(cls):
        names = [
            "account_id",
            "account_type",
            "m_strAccountID",
            "m_nAccountType",
            "m_strAccountType",
            "m_nBrokerType",
        ]
        for aliases in (cls._field_aliases, cls._extra_aliases):
            for target, sources in aliases.items():
                names.extend(_with_qmt_compact_aliases(target, *(sources or ())))
        return set(_unique_names(names))

    @classmethod
    def from_any(cls, value, normalize=None):
        if value is None:
            return None
        data = _dict_from_any(value)
        field_aliases = cls._expanded_aliases(cls._field_aliases)
        extra_aliases = cls._expanded_aliases(cls._extra_aliases)
        names = ["account_id", "account_type", "m_strAccountID", "m_nAccountType", "m_strAccountType"]
        for aliases in (field_aliases, extra_aliases):
            for target, sources in aliases.items():
                names.append(target)
                names.extend(sources)
        names = _unique_names(names)
        # Embedded QMT objects may expose C++ properties without a __dict__.
        if not isinstance(value, dict):
            data = data or {}
            for name in names:
                field = getattr(value, name, _MISSING)
                if field is not _MISSING:
                    data[name] = field
        if data is None or not data:
            return value
        if normalize is not None:
            for name in names:
                if name in data:
                    data[name] = normalize(data[name])
        if not any(name in data for name in ("account_type", "m_nAccountType", "m_strAccountType", "broker_type", "m_nBrokerType")):
            data["account_type"] = cls._account_type
        _apply_common_account_fields(data)
        for target, sources in field_aliases.items():
            _set_first(data, target, sources)
        for target, sources in extra_aliases.items():
            _set_first(data, target, sources)
        if cls._account_type == xtconstant.CREDIT_ACCOUNT and "exchange_id" in data:
            market = _exchange_suffix(data["exchange_id"])
            data["exchange_id"] = xtconstant.MARKET_STR_TO_ENUM_MAPPING.get(market, data["exchange_id"])
        return cls(**data)


class XtPositionStatistics(_QmtQueryObject):
    _account_type = xtconstant.FUTURE_ACCOUNT
    _field_aliases = {
        "exchange_id": ("m_strExchangeID",),
        "exchange_name": ("m_strExchangeName",),
        "product_id": ("m_strProductID",),
        "instrument_id": ("m_strInstrumentID",),
        "instrument_name": ("m_strInstrumentName",),
        "direction": ("m_nDirection",),
        "hedge_flag": ("m_nHedgeFlag",),
        "position": ("m_nPosition",),
        "yesterday_position": ("m_nYestodayPosition",),
        "today_position": ("m_nTodayPosition",),
        "can_close_vol": ("m_nCanCloseVol",),
        "position_cost": ("m_dPositionCost",),
        "avg_price": ("m_dAvgPrice",),
        "position_profit": ("m_dPositionProfit",),
        "float_profit": ("m_dFloatProfit",),
        "open_price": ("m_dOpenPrice",),
        "open_cost": ("m_dOpenCost",),
        "used_margin": ("m_dUsedMargin",),
        "used_commission": ("m_dUsedCommission",),
        "frozen_margin": ("m_dFrozenMargin",),
        "frozen_commission": ("m_dFrozenCommission",),
        "instrument_value": ("m_dInstrumentValue",),
        "open_times": ("m_nOpenTimes",),
        "open_volume": ("m_nOpenVolume",),
        "cancel_times": ("m_nCancelTimes",),
        "last_price": ("m_dLastPrice",),
        "rise_ratio": ("m_dRiseRatio",),
        "product_name": ("m_strProductName",),
        "royalty": ("m_dRoyalty",),
        "expire_date": ("m_strExpireDate",),
        "assest_weight": ("m_dAssestWeight",),
        "increase_by_settlement": ("m_dIncreaseBySettlement",),
        "margin_ratio": ("m_dMarginRatio",),
        "float_profit_divide_by_used_margin": ("m_dFloatProfitDivideByUsedMargin",),
        "float_profit_divide_by_balance": ("m_dFloatProfitDivideByBalance",),
        "today_profit_loss": ("m_dTodayProfitLoss",),
        "yesterday_init_position": ("m_nYestodayInitPosition",),
        "frozen_royalty": ("m_dFrozenRoyalty",),
        "today_close_profit_loss": ("m_dTodayCloseProfitLoss",),
        "close_profit": ("m_dCloseProfit",),
        "ft_product_name": ("m_strFtProductName",),
    }


class XtCreditDetail(_QmtQueryObject):
    _field_aliases = {
        "m_nStatus": (),
        "m_nUpdateTime": (),
        "m_nCalcConfig": (),
        "m_dFrozenCash": (),
        "m_dBalance": (),
        "m_dAvailable": (),
        "m_dPositionProfit": (),
        "m_dMarketValue": ("m_dInstrumentValue",),
        "m_dFetchBalance": (),
        "m_dStockValue": (),
        "m_dFundValue": (),
        "m_dTotalDebt": ("m_dTotalDebit",),
        "m_dEnableBailBalance": (),
        "m_dPerAssurescaleValue": (),
        "m_dAssureAsset": (),
        "m_dFinDebt": (),
        "m_dFinDealAvl": (),
        "m_dFinFee": (),
        "m_dSloDebt": (),
        "m_dSloMarketValue": (),
        "m_dSloFee": (),
        "m_dOtherFare": (),
        "m_dFinMaxQuota": (),
        "m_dFinEnableQuota": (),
        "m_dFinUsedQuota": (),
        "m_dSloMaxQuota": (),
        "m_dSloEnableQuota": (),
        "m_dSloUsedQuota": (),
        "m_dSloSellBalance": (),
        "m_dUsedSloSellBalance": (),
        "m_dSurplusSloSellBalance": (),
    }


class StkCompacts(_QmtQueryObject):
    _field_aliases = {
        "compact_type": ("m_eCompactType",),
        "cashgroup_prop": ("m_eCashgroupProp",),
        "exchange_id": ("m_strExchangeID",),
        "open_date": ("m_nOpenDate",),
        "business_vol": ("m_nBusinessVol",),
        "real_compact_vol": ("m_nRealCompactVol",),
        "ret_end_date": ("m_nRetEndDate",),
        "business_balance": ("m_dBusinessBalance",),
        "businessFare": ("m_dBusinessFare",),
        "real_compact_balance": ("m_dRealCompactBalance",),
        "real_compact_fare": ("m_dRealCompactFare",),
        "repaid_fare": ("m_dRepaidFare",),
        "repaid_balance": ("m_dRepaidBalance",),
        "instrument_id": ("m_strInstrumentID",),
        "compact_id": ("m_strCompactId", "m_strCompactID"),
        "position_str": ("m_strPositionStr",),
    }


class CreditSubjects(_QmtQueryObject):
    _field_aliases = {
        "exchange_id": ("m_strExchangeID",),
        "instrument_id": ("m_strInstrumentID",),
        "slo_status": ("m_eSloStatus",),
        "fin_status": ("m_eFinStatus",),
        "slo_ratio": ("m_dSloRatio",),
        "fin_ratio": ("m_dFinRatio",),
    }


class CreditAssure(_QmtQueryObject):
    _field_aliases = {
        "exchange_id": ("m_strExchangeID",),
        "instrument_id": ("m_strInstrumentID",),
        "assure_status": ("m_eAssureStatus",),
        "assure_ratio": ("m_dAssureRatio",),
    }


class CreditSloCode(_QmtQueryObject):
    _field_aliases = {
        "exchange_id": ("m_strExchangeID",),
        "instrument_id": ("m_strInstrumentID",),
        "cashgroup_prop": ("m_eCashgroupProp", "m_eQuerySloType"),
        "enable_amount": ("m_nEnableAmount",),
    }


class XtOrderError(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first_order_id(data, (
            "m_nRef",
            "m_nOrderID",
            "m_strOrderRef",
            "m_strOrderID",
        ))
        _set_first(data, "error_id", ("m_nErrorID", "error_code"), default=None)
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        _set_first(data, "strategy_name", ("m_strStrategyName",), default="")
        _set_first(data, "order_remark", ("m_strRemark", "m_strOrderRemark"), default="")
        _normalize_order_id_field(data)
        # 大 QMT 的 orderError_callback 只提供错误文本，柜台错误码和股票代码
        # 常以内嵌字段出现，例如 [251005]... [p_stock_code=518880,...]。
        # 仅在标准字段缺失时补充，保留 MiniQMT 原生字段优先级。
        if data.get("error_id") in (None, "", 0, "0"):
            for token in re.findall(r"\[(\d+)\]", str(data.get("error_msg") or "")):
                if int(token):
                    data["error_id"] = int(token)
                    break
        if not data.get("stock_code"):
            match = re.search(
                r"(?:^|[\[,;\s])p_stock_code\s*=\s*([A-Za-z0-9_.-]+)",
                str(data.get("error_msg") or ""),
                re.IGNORECASE,
            )
            if match:
                data["stock_code"] = match.group(1)
        if data.get("order_id") in (0, "0", -1, "-1"):
            data["order_id"] = -1
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["order_id"] = _coerce_int(data.get("order_id"), -1)
        data["error_id"] = _coerce_int(data.get("error_id"), None)
        for name in ("error_msg", "strategy_name", "order_remark"):
            data[name] = _coerce_text(data.get(name))
        return cls(**data)


class XtCancelError(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _apply_stock_code_field(data)
        _set_first_order_id(data, (
            "m_nRef",
            "m_nOrderID",
            "m_strOrderRef",
            "m_strOrderID",
        ))
        _set_first(data, "market", ("m_nMarket", "m_strExchangeID"), default="")
        _set_first(data, "order_sysid", ("m_strOrderSysID", "sysid", "m_strOrderID"), default="")
        _set_first(data, "error_id", ("m_nErrorID", "error_code"), default=None)
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        _set_first(data, "strategy_name", ("m_strStrategyName",), default="")
        _set_first(data, "order_remark", ("m_strRemark", "m_strOrderRemark"), default="")
        _normalize_order_id_field(data)
        if data.get("order_id") in (0, "0", -1, "-1"):
            data["order_id"] = -1
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["stock_code"] = _coerce_text(data.get("stock_code"))
        data["order_id"] = _coerce_int(data.get("order_id"), -1)
        market = data.get("market")
        if isinstance(market, str) and not market.strip().lstrip("+-").isdigit():
            market = xtconstant.MARKET_STR_TO_ENUM_MAPPING.get(_exchange_suffix(market), market)
        data["market"] = _coerce_int(market, 0)
        data["order_sysid"] = _coerce_text(data.get("order_sysid"))
        data["error_id"] = _coerce_int(data.get("error_id"), None)
        for name in ("error_msg", "strategy_name", "order_remark"):
            data[name] = _coerce_text(data.get(name))
        return cls(**data)


class XtOrderResponse(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first_order_id(data, (
            "m_nRef",
            "m_nOrderID",
            "m_strOrderRef",
            "m_strOrderID",
        ))
        _normalize_order_id_field(data)
        _set_first(data, "strategy_name", ("m_strStrategyName",), default="")
        _set_first(data, "order_remark", ("m_strRemark", "m_strOrderRemark"), default="")
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        _set_first(data, "seq", ("m_nSeq", "request_id"), default=None)
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["order_id"] = _coerce_int(data.get("order_id"), -1)
        data["seq"] = _coerce_int(data.get("seq"), None)
        for name in ("strategy_name", "order_remark", "error_msg"):
            data[name] = _coerce_text(data.get(name))
        return cls(**data)


class XtCancelOrderResponse(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first(data, "cancel_result", ("result", "m_nCancelResult"), default=-1)
        _set_first_order_id(data, (
            "m_nRef",
            "m_nOrderID",
            "m_strOrderRef",
            "m_strOrderID",
        ))
        _set_first(data, "order_sysid", ("m_strOrderSysID", "sysid", "m_strOrderID"), default="")
        _set_first(data, "seq", ("m_nSeq", "request_id"), default=None)
        _set_first(data, "error_msg", ("m_strErrorMsg", "message", "msg"), default="")
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["cancel_result"] = _coerce_int(data.get("cancel_result"), -1)
        data["order_id"] = _coerce_int(data.get("order_id"), -1)
        data["order_sysid"] = _coerce_text(data.get("order_sysid"))
        data["seq"] = _coerce_int(data.get("seq"), None)
        data["error_msg"] = _coerce_text(data.get("error_msg"))
        return cls(**data)


class XtAccountStatus(DictObject):
    @classmethod
    def from_any(cls, value):
        data = _dict_from_any(value)
        if data is None:
            return value
        _apply_common_account_fields(data)
        _set_first(data, "status", (
            "m_nStatus",
            "m_nLoginStatus",
            "login_status",
        ), default=None)
        data["account_id"] = _coerce_text(data.get("account_id"))
        data["status"] = _coerce_int(data.get("status"), None)
        return cls(**data)


class XtAccountInfo(_QmtQueryObject):
    _account_type = xtconstant.SECURITY_ACCOUNT
    _field_aliases = {
        "broker_type": ("m_nBrokerType",),
        "platform_id": ("m_nPlatformID",),
        "account_classification": ("m_nAccountClassification",),
        "login_status": ("m_nLoginStatus", "m_nStatus", "status"),
    }


class XtBankTransferResponse(DictObject):
    @classmethod
    def from_any(cls, value):
        if value is None:
            return None
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return cls(seq=None, success=_coerce_bool(value[0], False), msg=_coerce_text(value[1]))
        data = _dict_from_any(value)
        if data is None:
            return value
        _set_first(data, "seq", ("m_nSeq", "request_id"), default=None)
        _set_first(data, "success", ("m_bSuccess", "ok", "accepted"), default=None)
        _set_first(data, "msg", ("m_strMsg", "m_strError", "message", "error", "error_msg"), default="")
        data["seq"] = _coerce_int(data.get("seq"), None)
        data["success"] = _coerce_bool(data.get("success"), False)
        data["msg"] = _coerce_text(data.get("msg"))
        return cls(**data)


class XtSmtAppointmentResponse(DictObject):
    @classmethod
    def from_any(cls, value):
        if value is None:
            return None
        data = _dict_from_any(value) or {}
        aliases = {
            "seq": ("m_nSeq",),
            "success": ("m_bSuccess",),
            "msg": ("m_strMsg", "m_strError", "error"),
            "apply_id": ("m_strApplyID", "m_strApplyId", "applyId"),
        }
        if not isinstance(value, dict):
            for name in [name for target, sources in aliases.items() for name in (target,) + sources]:
                field = getattr(value, name, _MISSING)
                if field is not _MISSING:
                    data[name] = field
        if not data:
            return value
        for target, sources in aliases.items():
            _set_first(data, target, sources)
        data["seq"] = _coerce_int(data.get("seq"), None)
        data["success"] = _coerce_bool(data.get("success"), False)
        data["msg"] = _coerce_text(data.get("msg"))
        data["apply_id"] = _coerce_text(data.get("apply_id"))
        return cls(**data)


def to_objects(values, cls=DictObject):
    if values is None:
        return None
    if isinstance(values, (list, tuple)):
        return [cls.from_any(v) for v in values]
    return cls.from_any(values)
