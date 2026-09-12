# -*- coding: utf-8 -*-
"""Cross-QMT order metadata helpers.

The advanced trading path may place orders from a low-latency QMT while order
callbacks arrive in a normal bridge QMT. Some QMT callback objects omit
strategy_name/order_remark for orders placed by a different QMT process. This
module keeps the custom userOrderId metadata in memory and LTtx only; it does
not use local files.
"""

import json
import re
import threading
import time


ORDER_META_PUSH_KEY = "cfquant.order_meta.upsert"
ORDER_META_DELETE_KEY = "cfquant.order_meta.delete"
ORDER_META_KEY_PREFIX = "cfquant.order_meta."

STORE_USER_PREFIX = "u:"
STORE_REF_PREFIX = "r:"
DEFAULT_BRIDGE_ID = "default"
DEFAULT_ACCOUNT_TYPE = "STOCK"
PENDING_MATCH_TTL_SECONDS = 10 * 60
ORDER_REF_FIELDS = (
    "order_ref",
    "m_strOrderRef",
    "m_strOrderID",
    "m_nRef",
    "m_nOrderID",
    "order_id",
    "m_strOrderSysID",
    "order_sysid",
)


def current_trade_day(ts=None):
    if ts is None:
        ts = time.time()
    return time.strftime("%Y%m%d", time.localtime(ts))


def safe_key_part(value):
    text = "" if value is None else str(value).strip()
    if not text:
        text = DEFAULT_BRIDGE_ID
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", text)


def normalize_account_type(value):
    if value is None or value == "":
        return DEFAULT_ACCOUNT_TYPE
    text = str(value).strip().upper()
    aliases = {
        "2": "STOCK",
        "STOCK": "STOCK",
        "SECURITY": "STOCK",
        "SECURITY_ACCOUNT": "STOCK",
        "0": "FUTURE",
        "FUTURE": "FUTURE",
        "FUTURES": "FUTURE",
        "CREDIT": "CREDIT",
        "MARGIN": "CREDIT",
    }
    return aliases.get(text, text)


def normalize_bridge_id(bridge_id):
    return safe_key_part(bridge_id or DEFAULT_BRIDGE_ID)


def account_meta_channel(bridge_id, account_type, account_id):
    return "cfquant.%s.order_meta.%s.%s" % (
        normalize_bridge_id(bridge_id),
        safe_key_part(normalize_account_type(account_type)),
        safe_key_part(account_id),
    )


def account_store_key(bridge_id, account_type, account_id):
    return "cfquant.order_meta.store.%s.%s.%s" % (
        normalize_bridge_id(bridge_id),
        safe_key_part(normalize_account_type(account_type)),
        safe_key_part(account_id),
    )


def store_user_key(user_order_id):
    user_order_id = normalize_text(user_order_id)
    return STORE_USER_PREFIX + user_order_id if user_order_id else ""


def store_order_ref_key(order_ref):
    order_ref = normalize_order_ref(order_ref)
    return STORE_REF_PREFIX + order_ref if order_ref else ""


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("none", "null", "nan"):
        return ""
    return text


def is_empty(value):
    return normalize_text(value) == ""


def normalize_order_ref(value):
    text = normalize_text(value)
    if not text:
        return ""
    try:
        if isinstance(value, float) and value.is_integer():
            text = str(int(value))
    except Exception:
        pass
    if text in ("0", "-1"):
        return ""
    return text


def stock_code_base(value):
    text = normalize_text(value)
    if not text:
        return ""
    return text.split(".", 1)[0].upper()


def first_value(mapping, names):
    if not isinstance(mapping, dict):
        return ""
    for name in names:
        value = mapping.get(name)
        if not is_empty(value):
            return value
    return ""


def plain_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("gbk", errors="replace")
    if isinstance(value, (list, tuple)):
        return [plain_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain_value(val) for key, val in value.items()}
    return str(value)


def encode_record(record):
    return json.dumps(plain_value(record or {}), ensure_ascii=False, separators=(",", ":"))


def decode_record_payload(payload):
    if payload is None:
        return None
    if isinstance(payload, dict):
        return plain_value(payload)
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except Exception:
            payload = payload.decode("gbk", errors="replace")
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        try:
            decoded = json.loads(text)
        except Exception:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def split_push_message(raw):
    if raw is None:
        return None, None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            raw = raw.decode("gbk", errors="replace")
    raw = str(raw)
    if "|" not in raw:
        return None, None
    key, payload = raw.split("|", 1)
    if not key.startswith(ORDER_META_KEY_PREFIX):
        return None, None
    return key, payload


def user_order_id_from_data(data):
    return normalize_text(
        first_value(
            data,
            (
                "user_order_id",
                "client_order_id",
                "order_remark",
                "remark",
                "m_strRemark",
                "m_strOrderRemark",
            ),
        )
    )


def order_ref_from_data(data):
    refs = order_ref_candidates_from_data(data)
    return refs[0] if refs else ""


def order_ref_candidates_from_data(data):
    if not isinstance(data, dict):
        return []
    values = []
    for name in ORDER_REF_FIELDS:
        value = data.get(name)
        if not is_empty(value):
            values.append(value)
    existing = data.get("order_refs")
    if isinstance(existing, (list, tuple, set)):
        values.extend(existing)
    elif not is_empty(existing):
        values.append(existing)
    refs = []
    seen = set()
    for value in values:
        ref = normalize_order_ref(value)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def merge_order_ref_candidates(record, refs):
    if not isinstance(record, dict):
        return []
    values = order_ref_candidates_from_data(record)
    if isinstance(refs, (list, tuple, set)):
        values.extend(refs)
    elif not is_empty(refs):
        values.append(refs)
    merged = []
    seen = set()
    for value in values:
        ref = normalize_order_ref(value)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        merged.append(ref)
    if merged:
        record["order_refs"] = merged
    return merged


def normalize_record(record, bridge_id=None, account_type=None, account_id=None, now=None):
    now = time.time() if now is None else now
    data = plain_value(record or {})
    if not isinstance(data, dict):
        data = {}
    data = dict(data)

    if bridge_id is not None:
        data["bridge_id"] = normalize_bridge_id(bridge_id)
    else:
        data["bridge_id"] = normalize_bridge_id(data.get("bridge_id") or DEFAULT_BRIDGE_ID)

    if account_type is not None:
        data["account_type"] = normalize_account_type(account_type)
    else:
        data["account_type"] = normalize_account_type(data.get("account_type"))

    if account_id is not None:
        data["account_id"] = normalize_text(account_id)
    else:
        data["account_id"] = normalize_text(data.get("account_id"))

    user_order_id = user_order_id_from_data(data)
    if user_order_id:
        data["user_order_id"] = user_order_id
        data.setdefault("client_order_id", user_order_id)
        if is_empty(data.get("order_remark")):
            data["order_remark"] = user_order_id

    order_refs = order_ref_candidates_from_data(data)
    order_ref = order_refs[0] if order_refs else ""
    if order_ref:
        data["order_ref"] = order_ref
        if is_empty(data.get("m_strOrderRef")):
            data["m_strOrderRef"] = order_ref
    if order_refs:
        data["order_refs"] = order_refs

    stock_code = normalize_text(first_value(data, ("stock_code", "code", "m_strInstrumentID", "m_strStockCode")))
    if stock_code:
        data["stock_code"] = stock_code
        data["stock_code_base"] = stock_code_base(stock_code)

    if is_empty(data.get("trade_day")):
        data["trade_day"] = current_trade_day(now)
    if data.get("created_at") is None:
        data["created_at"] = now
    data["updated_at"] = now
    if is_empty(data.get("status")):
        data["status"] = "pending"
    return data


def ensure_callback_text_fields(data):
    if not isinstance(data, dict):
        return data
    for name in (
        "strategy_name",
        "order_remark",
        "m_strStrategyName",
        "m_strRemark",
        "m_strOrderRemark",
    ):
        if data.get(name) is None:
            data[name] = ""
    return data


def apply_record_to_callback(data, record, match_info=None):
    if not isinstance(data, dict):
        return data
    ensure_callback_text_fields(data)
    if not record:
        return data

    strategy_name = normalize_text(record.get("strategy_name"))
    order_remark = normalize_text(record.get("order_remark") or record.get("client_order_id") or record.get("user_order_id"))
    user_order_id = normalize_text(record.get("user_order_id") or order_remark)

    if strategy_name:
        for name in ("strategy_name", "m_strStrategyName"):
            if is_empty(data.get(name)):
                data[name] = strategy_name
    if order_remark:
        for name in ("order_remark", "m_strRemark", "m_strOrderRemark"):
            if is_empty(data.get(name)):
                data[name] = order_remark
    if user_order_id and is_empty(data.get("user_order_id")):
        data["user_order_id"] = user_order_id
    if not is_empty(record.get("client_order_id")) and is_empty(data.get("client_order_id")):
        data["client_order_id"] = normalize_text(record.get("client_order_id"))

    order_id_ref = normalize_order_ref(record.get("order_id"))
    if order_id_ref:
        order_id = int(order_id_ref) if order_id_ref.isdigit() else record.get("order_id")
        if not normalize_order_ref(data.get("order_id")):
            data["order_id"] = order_id
        for name in ("m_nRef", "m_nOrderID"):
            if not normalize_order_ref(data.get(name)):
                data[name] = order_id
        for name in ("m_strOrderRef", "m_strOrderID"):
            if is_empty(data.get(name)) or normalize_order_ref(data.get(name)) in ("0", "-1"):
                data[name] = order_id_ref

    if is_empty(data.get("order_source")) or normalize_text(data.get("order_source")).lower() == "other":
        data["order_source"] = "cfquant"
    data["cfquant_order_meta_hit"] = True
    data["cfquant_order_meta_status"] = normalize_text(record.get("status"))
    if match_info and match_info.get("match_confidence"):
        data["cfquant_order_meta_match"] = match_info.get("match_confidence")
    return data


def store_entries_for_record(record):
    record = normalize_record(record)
    payload = encode_record(record)
    entries = []
    user_key = store_user_key(record.get("user_order_id"))
    if user_key:
        entries.append((user_key, payload))
    for ref in order_ref_candidates_from_data(record):
        ref_key = store_order_ref_key(ref)
        if ref_key:
            entries.append((ref_key, payload))
    return entries


class OrderMetaCache(object):
    def __init__(self, bridge_id=None, pending_ttl_seconds=PENDING_MATCH_TTL_SECONDS):
        self.bridge_id = normalize_bridge_id(bridge_id or DEFAULT_BRIDGE_ID)
        self.pending_ttl_seconds = pending_ttl_seconds
        self.lock = threading.RLock()
        self.by_user = {}
        self.by_ref = {}
        self.pending = []

    def _ctx(self, record):
        return (
            normalize_bridge_id(record.get("bridge_id") or self.bridge_id),
            normalize_account_type(record.get("account_type")),
            normalize_text(record.get("account_id")),
        )

    def _user_key(self, record):
        user_order_id = normalize_text(record.get("user_order_id"))
        if not user_order_id:
            return None
        return self._ctx(record) + (user_order_id,)

    def _ref_key(self, record):
        refs = self._ref_keys(record)
        if not refs:
            return None
        return refs[0]

    def _ref_keys(self, record):
        return [self._ctx(record) + (ref,) for ref in order_ref_candidates_from_data(record)]

    @staticmethod
    def _callback_bound(record):
        if not isinstance(record, dict):
            return False
        status = normalize_text(record.get("status")).lower()
        return bool(record.get("callback_bound_at")) or status in ("callback_bound", "callback_seen")

    def prune(self, trade_day=None, now=None):
        trade_day = current_trade_day(now) if trade_day is None else trade_day
        now = time.time() if now is None else now
        with self.lock:
            self._prune_locked(trade_day, now)

    def _prune_locked(self, trade_day, now):
        def keep(record, pending=False):
            if normalize_text(record.get("trade_day")) != trade_day:
                return False
            if pending:
                try:
                    return now - float(record.get("created_at") or now) <= self.pending_ttl_seconds
                except Exception:
                    return True
            return True

        self.by_user = {key: value for key, value in self.by_user.items() if keep(value)}
        self.by_ref = {key: value for key, value in self.by_ref.items() if keep(value)}
        self.pending = [record for record in self.pending if keep(record, pending=True)]

    def upsert(self, record):
        record = normalize_record(record, bridge_id=self.bridge_id)
        with self.lock:
            return self._upsert_locked(record)

    def _upsert_locked(self, record):
        trade_day = current_trade_day()
        self._prune_locked(trade_day, time.time())
        status = normalize_text(record.get("status")).lower()
        if status in ("delete", "deleted", "failed", "cancelled"):
            self._remove_locked(record)
            return record

        user_key = self._user_key(record)
        ref_keys = self._ref_keys(record)
        if user_key:
            self.by_user[user_key] = record
        for ref_key in ref_keys:
            self.by_ref[ref_key] = record

        self._remove_pending_locked(record)
        if user_key and not self._callback_bound(record):
            self.pending.append(record)
        return record

    def remove(self, record):
        record = normalize_record(record, bridge_id=self.bridge_id)
        with self.lock:
            self._remove_locked(record)

    def clear_account(self, bridge_id=None, account_type=None, account_id=None):
        ctx = (
            normalize_bridge_id(bridge_id or self.bridge_id),
            normalize_account_type(account_type),
            normalize_text(account_id),
        )
        with self.lock:
            self.by_user = {key: value for key, value in self.by_user.items() if key[:3] != ctx}
            self.by_ref = {key: value for key, value in self.by_ref.items() if key[:3] != ctx}
            self.pending = [record for record in self.pending if self._ctx(record) != ctx]

    def _remove_locked(self, record):
        user_key = self._user_key(record)
        ref_keys = self._ref_keys(record)
        if user_key:
            self.by_user.pop(user_key, None)
        for ref_key in ref_keys:
            self.by_ref.pop(ref_key, None)
        self._remove_pending_locked(record)

    def _remove_pending_locked(self, record):
        user_key = self._user_key(record)
        ref_keys = set(self._ref_keys(record))
        next_pending = []
        for item in self.pending:
            if user_key and self._user_key(item) == user_key:
                continue
            item_ref_keys = set(self._ref_keys(item))
            if ref_keys and item_ref_keys and ref_keys.intersection(item_ref_keys):
                continue
            next_pending.append(item)
        self.pending = next_pending

    def load_store(self, store_value, bridge_id=None, account_type=None, account_id=None, trade_day=None):
        store = decode_record_payload(store_value) if not isinstance(store_value, dict) else store_value
        if not isinstance(store, dict):
            return {"loaded": 0, "stale": 0}
        trade_day = current_trade_day() if trade_day is None else trade_day
        loaded = 0
        stale = 0
        for key, payload in list(store.items()):
            if str(key).startswith("_"):
                continue
            record = decode_record_payload(payload)
            if not isinstance(record, dict):
                continue
            record = normalize_record(
                record,
                bridge_id=bridge_id or record.get("bridge_id") or self.bridge_id,
                account_type=account_type or record.get("account_type"),
                account_id=account_id or record.get("account_id"),
            )
            if normalize_text(record.get("trade_day")) != trade_day:
                stale += 1
                continue
            self.upsert(record)
            loaded += 1
        return {"loaded": loaded, "stale": stale}

    def resolve_callback(self, data, bridge_id=None, account_type=None, account_id=None, allow_pending=True):
        callback_record = normalize_record(
            data,
            bridge_id=bridge_id or self.bridge_id,
            account_type=account_type or data.get("account_type"),
            account_id=account_id or data.get("account_id"),
        )
        with self.lock:
            self._prune_locked(current_trade_day(), time.time())
            record = None
            confidence = ""
            order_refs = order_ref_candidates_from_data(callback_record)
            user_order_id = normalize_text(callback_record.get("user_order_id"))
            for order_ref in order_refs:
                record = self.by_ref.get(self._ctx(callback_record) + (order_ref,))
                if record:
                    confidence = "order_ref"
                    break
            if record is None and user_order_id:
                record = self.by_user.get(self._ctx(callback_record) + (user_order_id,))
                if record:
                    confidence = "user_order_id"
            if record is None and allow_pending:
                record, confidence = self._match_pending_locked(callback_record)
            if record is None:
                record, confidence = self._match_known_locked(callback_record, order_refs)

            bound_order_ref = ""
            bound_order_refs = []
            if record and order_refs:
                existing_refs = order_ref_candidates_from_data(record)
                existing_set = set(existing_refs)
                bound_order_refs = [ref for ref in order_refs if ref not in existing_set]
                merged_refs = merge_order_ref_candidates(record, order_refs)
                if confidence == "pending_fifo" or not normalize_order_ref(record.get("order_ref")):
                    record["order_ref"] = order_refs[0]
                    record["m_strOrderRef"] = order_refs[0]
                elif is_empty(record.get("m_strOrderRef")):
                    record["m_strOrderRef"] = normalize_order_ref(record.get("order_ref"))
                if confidence in ("pending_fifo", "order_ref", "user_order_id"):
                    record["status"] = "callback_bound"
                    record["callback_bound_at"] = time.time()
                record["updated_at"] = time.time()
                bound_order_ref = order_refs[0] if bound_order_refs or merged_refs else ""
                self._upsert_locked(record)

            return record, {
                "bound_order_ref": bound_order_ref,
                "bound_order_refs": bound_order_refs,
                "match_confidence": confidence,
            }

    def _unique_records_locked(self):
        records = []
        seen = set()
        for mapping in (self.by_ref, self.by_user):
            for record in mapping.values():
                ident = id(record)
                if ident in seen:
                    continue
                seen.add(ident)
                records.append(record)
        for record in self.pending:
            ident = id(record)
            if ident in seen:
                continue
            seen.add(ident)
            records.append(record)
        return records

    def _match_known_locked(self, callback_record, order_refs=None):
        ctx = self._ctx(callback_record)
        callback_refs = set(order_refs or order_ref_candidates_from_data(callback_record))
        candidates = []
        for record in self._unique_records_locked():
            if self._ctx(record) != ctx:
                continue
            if normalize_text(record.get("trade_day")) != current_trade_day():
                continue
            if not self._has_callback_metadata(record):
                continue
            evidence = self._context_match_evidence(record, callback_record)
            if evidence < 0:
                continue
            record_refs = set(order_ref_candidates_from_data(record))
            ref_hit = bool(callback_refs and record_refs and callback_refs.intersection(record_refs))
            if not ref_hit:
                if not self._has_stock_context_match(record, callback_record):
                    continue
                if evidence < 3:
                    continue
            updated_at = self._record_timestamp(record)
            score = (100 if ref_hit else 0) + evidence
            candidates.append((record, score, ref_hit, updated_at))
        if not candidates:
            return None, ""
        candidates.sort(key=lambda item: (item[1], item[3]), reverse=True)
        top_score = candidates[0][1]
        top = [item for item in candidates if item[1] == top_score]
        if top[0][2]:
            return top[0][0], "record_ref_scan"
        if len(top) == 1:
            return top[0][0], "record_context"
        meta_keys = set(self._record_meta_identity(item[0]) for item in top)
        if len(meta_keys) == 1:
            return top[0][0], "record_context_shared_meta"
        return None, ""

    def _match_pending_locked(self, callback_record):
        ctx = self._ctx(callback_record)
        callback_stock = stock_code_base(callback_record.get("stock_code") or callback_record.get("stock_code_base"))
        now = time.time()
        matches = []
        for record in self.pending:
            if self._ctx(record) != ctx:
                continue
            try:
                if now - float(record.get("created_at") or now) > self.pending_ttl_seconds:
                    continue
            except Exception:
                pass
            record_stock = stock_code_base(record.get("stock_code") or record.get("stock_code_base"))
            if callback_stock and record_stock and callback_stock != record_stock:
                continue
            if not self._compatible_value(record.get("order_type"), callback_record.get("order_type")):
                continue
            if not self._compatible_number(record.get("order_volume"), callback_record.get("order_volume")):
                continue
            if not self._compatible_number(record.get("price"), callback_record.get("price")):
                continue
            matches.append(record)
        if not matches:
            return None, ""
        matches.sort(key=lambda item: float(item.get("created_at") or 0))
        return matches[0], "pending_fifo"

    @staticmethod
    def _has_callback_metadata(record):
        return bool(
            normalize_text(record.get("strategy_name"))
            or normalize_text(record.get("order_remark"))
            or normalize_text(record.get("user_order_id"))
            or normalize_text(record.get("client_order_id"))
        )

    def _context_match_evidence(self, record, callback_record):
        evidence = 0
        record_stock = stock_code_base(record.get("stock_code") or record.get("stock_code_base"))
        callback_stock = stock_code_base(callback_record.get("stock_code") or callback_record.get("stock_code_base"))
        if callback_stock and record_stock:
            if callback_stock != record_stock:
                return -1
            evidence += 1
        if not self._compatible_value(record.get("order_type"), callback_record.get("order_type")):
            return -1
        if not is_empty(record.get("order_type")) and not is_empty(callback_record.get("order_type")):
            evidence += 1
        if not self._compatible_number(record.get("order_volume"), callback_record.get("order_volume")):
            return -1
        if not is_empty(record.get("order_volume")) and not is_empty(callback_record.get("order_volume")):
            evidence += 1
        if not self._compatible_number(record.get("price"), callback_record.get("price")):
            return -1
        if not is_empty(record.get("price")) and not is_empty(callback_record.get("price")):
            evidence += 1
        return evidence

    @staticmethod
    def _has_stock_context_match(record, callback_record):
        record_stock = stock_code_base(record.get("stock_code") or record.get("stock_code_base"))
        callback_stock = stock_code_base(callback_record.get("stock_code") or callback_record.get("stock_code_base"))
        return bool(callback_stock and record_stock and callback_stock == record_stock)

    @staticmethod
    def _record_timestamp(record):
        for name in ("updated_at", "callback_bound_at", "created_at"):
            try:
                return float(record.get(name) or 0)
            except Exception:
                continue
        return 0.0

    @staticmethod
    def _record_meta_identity(record):
        return (
            normalize_text(record.get("strategy_name")),
            normalize_text(record.get("order_remark")),
            normalize_text(record.get("user_order_id")),
            normalize_text(record.get("client_order_id")),
        )

    @staticmethod
    def _compatible_value(left, right):
        if is_empty(left) or is_empty(right):
            return True
        return normalize_text(left) == normalize_text(right)

    @staticmethod
    def _compatible_number(left, right):
        if is_empty(left) or is_empty(right):
            return True
        try:
            return abs(float(left) - float(right)) <= 1e-8
        except Exception:
            return normalize_text(left) == normalize_text(right)
