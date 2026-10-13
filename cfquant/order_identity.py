"""Per-submission QMT remarks, compatible with embedded Python 3.6.

The public remark is user data, never a unique order key. Keep a UUID in the
native remark so independent QMT processes and restarts can recover both.
"""

import re
import threading
import time
import uuid
from collections import OrderedDict


_ORDER_REMARK_SUFFIX = re.compile(r"__cfq_([0-9a-f]{32})$")
_STRATEGY_NAME_SUFFIX = re.compile(r"(?:&&&_cfq_|^cfq_)[0-9a-f]{12}\Z")


def restore_strategy_name(data):
    """Remove our request token only at the public callback/object boundary.

    Keep the full strategy until error-context matching has finished. Match
    the generated suffix precisely so user underscores and delimiters survive.
    """
    if isinstance(data, dict):
        for name in ("strategy_name", "m_strStrategyName", "mstrStrategyName", "strategyName"):
            value = data.get(name)
            if isinstance(value, str):
                match = _STRATEGY_NAME_SUFFIX.search(value)
                if match:
                    data[name] = value[:match.start()]
    return data


def original_order_remark(value):
    text = str(value or "")
    match = _ORDER_REMARK_SUFFIX.search(text)
    return text[:match.start()] if match else text


def is_unique_order_remark(value):
    return bool(_ORDER_REMARK_SUFFIX.search(str(value or "")))


def prepare_order_remark(params, fallback=""):
    original = next((params[name] for name in ("order_remark", "remark", "strategy_name")
                     if params.get(name) not in (None, "")), "")
    original = str(original or "")
    internal = params.get("cfquant_order_remark")
    if not (is_unique_order_remark(internal) and
            original_order_remark(internal) in (original, original or str(fallback or ""))):
        original = original or str(fallback or "")
        internal = original + "__cfq_" + uuid.uuid4().hex
    params["cfquant_order_remark"] = internal
    return internal


def order_remark_key(data):
    getter = data.get if isinstance(data, dict) else lambda name: getattr(data, name, None)
    values = [getter(name) for name in (
        "cfquant_order_remark", "user_order_id", "client_order_id",
        "order_remark", "m_strRemark", "m_strOrderRemark", "remark",
    )]
    for value in values:
        if is_unique_order_remark(value):
            return str(value)
    return next((str(value) for value in values if value not in (None, "")), "")


def restore_order_remark(data):
    if isinstance(data, dict):
        internal = order_remark_key(data)
        if is_unique_order_remark(internal):
            data["cfquant_order_remark"] = internal
            data["order_remark"] = original_order_remark(internal)
    return data


def order_remark_matches_reference(expected, actual):
    """Compare remarks only AFTER an order reference has matched.

    Some DEAL reports echo the public remark without our UUID. A different
    UUID still identifies a different submission, even with the same text.
    """
    return (not actual or expected == actual or
            (is_unique_order_remark(expected) and
             not is_unique_order_remark(actual) and
             original_order_remark(expected) == actual))


class OrderCallbackCache(object):
    """Bounded, daily order metadata indexed by separate local/broker IDs."""

    def __init__(self, max_orders=4096):
        self.max_orders = max_orders
        self.lock = threading.RLock()
        self.day = ""
        self.records = OrderedDict()
        self.by_ref = {}

    def _identity(self, data, account_type):
        day = time.strftime("%Y%m%d")
        if day != self.day:
            self.records.clear()
            self.by_ref.clear()
            self.day = day
        # Historical query rows must not seed today's broker-ID mapping.
        for name in ("order_date", "trade_date", "m_strInsertDate", "m_strTradeDate", "m_strTradingDay"):
            value = str(data.get(name) or "").replace("-", "").replace("/", "")
            if len(value) == 8 and value.isdigit() and value != day:
                return None, set()
        account = str(data.get("account_id") or data.get("m_strAccountID") or "").strip()
        stock = str(data.get("stock_code") or data.get("m_strInstrumentID") or "").strip().upper()
        market = str(data.get("market") or data.get("m_strExchangeID") or "").strip().upper()
        if "." in stock:
            stock, market = stock.rsplit(".", 1)
        if not account or not stock:
            return None, set()
        scope = (account_type, account, stock, market)
        refs = set()
        for name in ("order_id", "m_nRef", "m_nOrderID", "m_strOrderRef", "m_strOrderID"):
            value = str(data.get(name) or "").strip()
            if value.isdigit() and int(value) > 0:
                refs.add(("local", str(int(value))))
        for name in ("order_sysid", "m_strOrderSysID"):
            value = str(data.get(name) or "").strip()
            if value and value not in ("0", "-1"):
                refs.add(("broker", value))
        return scope, refs

    def _matches(self, scope, refs, data):
        groups = [self.by_ref[(scope, ref)] for ref in refs if (scope, ref) in self.by_ref]
        candidates = set.intersection(*groups) if groups else set()
        matches = []
        for key in candidates:
            record = self.records[key]
            expected, actual = order_remark_key(record["data"]), order_remark_key(data)
            if expected and not order_remark_matches_reference(expected, actual):
                continue
            local = {ref for ref in refs if ref[0] == "local"}
            known = {ref for ref in record["refs"] if ref[0] == "local"}
            if local and known and not local.intersection(known):
                continue
            matches.append(key)
        return matches

    def remember(self, data, account_type):
        if not (data.get("strategy_name") or data.get("m_strStrategyName") or order_remark_key(data)):
            return
        with self.lock:
            scope, refs = self._identity(data, account_type)
            if scope is None or not refs:
                return
            matches = self._matches(scope, refs, data)
            remark = order_remark_key(data)
            local = sorted(ref for ref in refs if ref[0] == "local")
            identity = ("remark", remark) if is_unique_order_remark(remark) else (local or sorted(refs))[0]
            key = (scope, identity)
            if len(matches) == 1:
                key = matches[0]
            record = self.records.get(key, {"data": {}, "refs": set()})
            record["data"].update({name: value for name, value in data.items() if value not in (None, "")})
            record["refs"].update(refs)
            self.records[key] = record
            self.records.move_to_end(key)
            for ref in refs:
                self.by_ref.setdefault((scope, ref), set()).add(key)
            while len(self.records) > self.max_orders:
                old_key, old = self.records.popitem(last=False)
                for ref in old["refs"]:
                    index = (old_key[0], ref)
                    self.by_ref[index].discard(old_key)
                    if not self.by_ref[index]:
                        del self.by_ref[index]

    def enrich(self, data, account_type):
        with self.lock:
            scope, refs = self._identity(data, account_type)
            matches = self._matches(scope, refs, data) if scope is not None else []
            if len(matches) != 1:
                return data
            saved = self.records[matches[0]]["data"]
            strategy = saved.get("strategy_name") or saved.get("m_strStrategyName")
            remark = order_remark_key(saved)
            for name, value in (("strategy_name", strategy), ("m_strStrategyName", strategy),
                                ("order_remark", remark), ("m_strRemark", remark), ("m_strOrderRemark", remark)):
                if value and not data.get(name):
                    data[name] = value
            if is_unique_order_remark(remark):
                data["cfquant_order_remark"] = remark
        return restore_order_remark(data)
