# -*- coding: utf-8 -*-
import base64
import json
import math
import time
import uuid


PROTOCOL_VERSION = 1
MESSAGE_PREFIX = "cfquant:"
_pd = None
_pd_loaded = False


def now_ms():
    return int(time.time() * 1000)


def new_id(prefix="req"):
    return "%s_%s_%s" % (prefix, now_ms(), uuid.uuid4().hex[:12])


def normalize_json_value(value, path="message", _active=None):
    """Normalize numeric scalars without guessing the meaning of arbitrary objects."""
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("%s: NaN and infinity are not valid JSON numbers" % path)
        return value
    value_type = type(value)
    if value_type.__module__.split(".", 1)[0] == "numpy" and getattr(value, "ndim", None) == 0:
        kind = getattr(getattr(value, "dtype", None), "kind", None)
        convert = {"b": bool, "i": int, "u": int, "f": float, "U": str}.get(kind)
        if convert is not None:
            return normalize_json_value(convert(value), path)
    if not isinstance(value, (dict, list, tuple)):
        raise TypeError(
            "%s: unsupported JSON type %s.%s; select a scalar with .at/.iat/.item(), "
            "or explicitly convert a collection to a list/dict for collection-valued parameters"
            % (path, value_type.__module__, value_type.__name__)
        )
    active = set() if _active is None else _active
    identity = id(value)
    if identity in active:
        raise ValueError("%s: circular reference is not valid JSON data" % path)
    active.add(identity)
    try:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized_key = normalize_json_value(key, "%s.<key>" % path, active)
                if normalized_key is not None and not isinstance(normalized_key, (str, int, float, bool)):
                    raise TypeError("%s: JSON object keys must be strings or scalar numbers" % path)
                item_path = "%s.%s" % (path, normalized_key) if isinstance(normalized_key, str) else "%s[%r]" % (path, normalized_key)
                result[normalized_key] = normalize_json_value(item, item_path, active)
            return result
        return [normalize_json_value(item, "%s[%s]" % (path, index), active) for index, item in enumerate(value)]
    finally:
        active.remove(identity)


def dumps_message(payload):
    data = dict(payload)
    data.setdefault("protocol", "cfquant")
    data.setdefault("version", PROTOCOL_VERSION)
    data.setdefault("ts", now_ms())
    return MESSAGE_PREFIX + json.dumps(normalize_json_value(data), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def loads_message(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    if not raw.startswith(MESSAGE_PREFIX) and "|" in raw:
        _, raw = raw.split("|", 1)
    if not raw.startswith(MESSAGE_PREFIX):
        return None
    try:
        data = json.loads(raw[len(MESSAGE_PREFIX):])
    except Exception:
        return None
    if data.get("protocol") != "cfquant":
        return None
    return data


def pack_request(action, params=None, reply_channel=None, client_id=None, request_id=None, timeout=None):
    payload = {
        "type": "request",
        "id": request_id or new_id("req"),
        "action": action,
        "params": {} if params is None else params,
        "reply_channel": reply_channel,
        "client_id": client_id,
    }
    if timeout is not None:
        payload["timeout"] = float(timeout)
    return dumps_message(payload)


def encode_response_result(result):
    """Freeze one response body for reuse; include all serialization work."""
    started = time.perf_counter()
    encoded = encode_value(result)
    converted = time.perf_counter()
    normalized = normalize_json_value(encoded, "result")
    normalized_at = time.perf_counter()
    body = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    finished = time.perf_counter()
    return body, {"encode_value_ms": round((converted - started) * 1000, 3),
                  "normalize_ms": round((normalized_at - converted) * 1000, 3),
                  "json_encode_ms": round((finished - normalized_at) * 1000, 3),
                  "encode_ms": round((finished - started) * 1000, 3)}


def pack_response(request_id, ok=True, result=None, error=None, meta=None, encoded_result=None):
    body, encoding_timing = encode_response_result(result) if encoded_result is None else encoded_result
    meta = dict(meta or {})
    timing = meta.get("timing")
    if isinstance(timing, dict) and isinstance(timing.get("qmt"), dict):
        timing = dict(timing, qmt=dict(timing["qmt"], **encoding_timing))
        meta["timing"] = timing
    header = dumps_message({
        "type": "response",
        "id": request_id,
        "ok": bool(ok),
        "error": encode_error(error),
        "meta": meta,
    })
    return header[:-1] + ',"result":' + body + '}'


def pack_event(event, data=None, client_id=None, subscription_id=None, meta=None):
    return dumps_message({
        "type": "event",
        "event": event,
        "client_id": client_id,
        "subscription_id": subscription_id,
        "data": encode_value(data),
        "meta": meta or {},
    })


def is_readonly_request(action):
    # Only known query families. Downloads, subscriptions and all writes retain
    # their existing execution semantics, including on an ambiguous timeout.
    return (str(action).startswith(("xtdata.get_", "xttrader.query_"))
            or action in ("cfquant.ping", "cfquant.status", "cfquant.query_info"))


def request_expired(msg, now=None):
    if not is_readonly_request(msg.get("action")):
        return False
    received = msg.get("_received_monotonic")
    timeout = msg.get("timeout")
    if received is None or timeout is None:
        return False
    return (time.perf_counter() if now is None else now) - received >= max(0.0, float(timeout))


def _quote_json_default(value):
    """Box only uncommon quote scalars; ordinary dict/list traversal stays in JSON's C encoder."""
    if type(value).__module__.startswith("pandas.") and type(value).__name__ in ("NAType", "NaTType"):
        return None
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError("unsupported quote JSON type: %s" % type(value).__name__)


def pack_whole_quote_event(event, data, client_id=None, subscription_id=None):
    """Serialize a whole-quote batch without recursive Python preprocessing.

    Only the event metadata carries the encoding marker; callback data keeps
    its stock-code dictionary shape. Unsupported values require the caller's
    compatibility fallback, just as for diagnostic snapshots.
    """
    quotes_json = json.dumps(data, default=_quote_json_default,
                             ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    header = dumps_message({"type": "event", "event": event, "client_id": client_id,
                           "subscription_id": subscription_id, "meta": {"quote_json_plain": True}})
    return header[:-1] + ',"data":' + quotes_json + '}'


def pack_quote_latency_event(event, data, client_id=None, subscription_id=None):
    """Encode the complete diagnostic snapshot once, without recursive Python preprocessing.

    Nonfinite or unusual payloads raise and use the bridge's existing compatibility
    encoder. The wire format remains ordinary strict JSON, consumable by old receivers.
    """
    started = time.perf_counter()
    quotes_json = json.dumps(data["quotes"], default=_quote_json_default,
                             ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    metadata = {key: value for key, value in data.items() if key != "quotes"}
    metadata["qmt_encode_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    metadata["qmt_encoding"] = "direct_json"
    header = dumps_message({"type": "event", "event": event, "client_id": client_id,
                           "subscription_id": subscription_id, "meta": {"quote_json_plain": True}})
    details = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return header[:-1] + ',"data":' + details[:-1] + ',"quotes":' + quotes_json + '}}'


def encode_error(error):
    if error is None:
        return None
    if isinstance(error, dict):
        return error
    return {
        "type": type(error).__name__,
        "message": str(error),
    }


def encode_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if type(value).__module__.startswith("pandas.") and type(value).__name__ in ("NAType", "NaTType"):
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, bytes):
        return {
            "__cf_type__": "bytes",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, dict):
        return {str(k): encode_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [encode_value(v) for v in value]
    if type(value).__module__.split(".", 1)[0] == "numpy":
        if type(value).__name__ == "ndarray":
            return _encode_ndarray(value)
        item = getattr(value, "item", None)
        return encode_value(item() if callable(item) else value.tolist())
    if _looks_like_dataframe(value):
        return _encode_dataframe(value)
    if _looks_like_series(value):
        return _encode_series(value)
    pd = _get_pandas()
    if pd is not None and isinstance(value, pd.DataFrame):
        return _encode_dataframe(value)
    if pd is not None and isinstance(value, pd.Series):
        return _encode_series(value)
    if hasattr(value, "__dict__"):
        return {
            "__cf_type__": "object",
            "class": type(value).__name__,
            "attrs": encode_value(vars(value)),
        }
    return str(value)


def _get_pandas():
    global _pd, _pd_loaded
    if _pd_loaded:
        return _pd
    _pd_loaded = True
    try:
        import pandas as pd
        _pd = pd
    except Exception:
        _pd = None
    return _pd


def _looks_like_dataframe(value):
    return (
        hasattr(value, "columns")
        and hasattr(value, "index")
        and hasattr(value, "values")
        and hasattr(value, "to_dict")
    )


def _looks_like_series(value):
    return (
        hasattr(value, "index")
        and hasattr(value, "values")
        and hasattr(value, "name")
        and not hasattr(value, "columns")
    )


def _clean_cell(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return encode_value(value)


def dataframe_numeric_rows(value):
    """Bulk rows for plain numeric frames; None keeps pandas' other semantics."""
    columns = getattr(value, "columns", None)
    dtypes = getattr(value, "dtypes", None)
    if columns is None or not len(columns) or dtypes is None or not getattr(columns, "is_unique", False):
        return None
    # Nullable, object and date-like columns need pandas' scalar boxing rules.
    # Restrict this fast path so callers keep their existing null/date behavior.
    for dtype in dtypes:
        if (type(dtype).__module__.split(".", 1)[0] != "numpy"
                or dtype.kind not in ("b", "i", "u", "f") or dtype.itemsize > 8):
            return None
    # Combining mixed numeric blocks before this cast can round large IDs.
    return value.astype(object, copy=False).values.tolist()


def _encode_dataframe(value):
    try:
        # itertuples builds a Series per column, which is expensive for QMT's
        # stock-by-date history frames. Cast BEFORE combining the blocks: using
        # values directly can round int64/uint64 IDs in mixed float/int frames.
        # astype also works with QMT's pandas 0.22 (which has no to_numpy).
        raw_rows = value.astype(object, copy=False).values.tolist() if len(value.columns) else []
    except Exception:
        try:
            raw_rows = list(value.itertuples(index=False, name=None))
        except Exception:
            try:
                raw_rows = value.values.tolist()
            except Exception:
                raw_rows = []
    rows = []
    for row in raw_rows:
        rows.append([_clean_cell(v) for v in row])
    # Thousands of date columns usually share one dtype. Formatting its name
    # repeatedly can cost more than extracting the actual values.
    dtype_flags = {}
    object_columns = []
    for name, dtype in getattr(value, "dtypes", {}).items():
        is_object = dtype_flags.get(dtype)
        if is_object is None:
            dtype_name = str(dtype)
            is_object = dtype_name == "object" or dtype_name.startswith(("Int", "UInt"))
            dtype_flags[dtype] = is_object
        if is_object:
            object_columns.append(_encode_label(name))
    index_name = getattr(getattr(value, "index", None), "name", None)
    return {
        "__cf_type__": "dataframe",
        "columns": [_encode_label(c) for c in getattr(value, "columns", [])],
        "index": [_encode_label(i) for i in getattr(value, "index", [])],
        "data": rows,
        "index_name": _encode_label(index_name) if index_name is not None else None,
        "object_columns": object_columns,
    }


def _encode_label(value):
    if isinstance(value, tuple):
        return {
            "__cf_type__": "tuple",
            "data": [_encode_label(item) for item in value],
        }
    return encode_value(value)


def _encode_ndarray(value):
    dtype = getattr(value, "dtype", None)
    names = getattr(dtype, "names", None)
    payload = {
        "__cf_type__": "ndarray",
        "shape": list(getattr(value, "shape", ())),
        "data": encode_value(value.tolist()),
    }
    if names:
        payload["dtype_descr"] = encode_value(dtype.descr)
    elif dtype is not None:
        payload["dtype"] = str(dtype)
    return payload


def _encode_series(value):
    try:
        raw_values = value.values.tolist()
    except Exception:
        raw_values = []
    return {
        "__cf_type__": "series",
        "index": [_encode_label(i) for i in getattr(value, "index", [])],
        "data": [_clean_cell(v) for v in raw_values],
        "name": _encode_label(value.name) if getattr(value, "name", None) is not None else None,
    }


def decode_value(value):
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    if not isinstance(value, dict):
        return value

    value_type = value.get("__cf_type__")
    if value_type == "bytes":
        return base64.b64decode(value.get("data", ""))
    if value_type == "tuple":
        return tuple(decode_value(item) for item in value.get("data", []))
    if value_type == "dataframe":
        import pandas as pd
        columns = [decode_value(item) for item in value.get("columns", [])]
        rows = [[decode_value(cell) for cell in row] for row in value.get("data", [])]
        object_columns = [decode_value(item) for item in value.get("object_columns", [])]
        if object_columns and columns:
            # Construct columns independently, preserving duplicate field labels too.
            df = pd.concat([pd.Series([row[i] for row in rows], dtype=object if name in object_columns else None)
                            for i, name in enumerate(columns)], axis=1)
            df.columns = columns
        else:
            df = pd.DataFrame(rows, columns=columns)
        index = [decode_value(item) for item in value.get("index", [])]
        if len(index) == len(df):
            df.index = index
        if value.get("index_name") is not None:
            df.index.name = decode_value(value.get("index_name"))
        return df
    if value_type == "series":
        import pandas as pd
        return pd.Series(
            [decode_value(v) for v in value.get("data", [])],
            index=[decode_value(item) for item in value.get("index", [])],
            name=decode_value(value.get("name")),
        )
    if value_type == "ndarray":
        import numpy as np
        data = decode_value(value.get("data"))
        dtype = None
        if value.get("dtype_descr"):
            dtype_descr = []
            for item in value.get("dtype_descr", []):
                parts = list(item)
                if len(parts) >= 3 and isinstance(parts[2], list):
                    parts[2] = tuple(parts[2])
                dtype_descr.append(tuple(parts))
            dtype = np.dtype(dtype_descr)
            # JSON turns each structured record tuple into a list. NumPy
            # treats that list as another array dimension unless restored.
            def record_tuples(items, dimensions):
                if dimensions == 0:
                    return tuple(items)
                return [record_tuples(item, dimensions - 1) for item in items]
            data = record_tuples(data, len(value.get("shape", [len(data)])))
        elif value.get("dtype"):
            try:
                dtype = np.dtype(value.get("dtype"))
            except Exception:
                dtype = None
        result = np.asarray(data, dtype=dtype)
        shape = value.get("shape")
        if shape is not None:
            try:
                result = result.reshape(tuple(shape))
            except Exception:
                pass
        return result
    if value_type == "object":
        return SimpleObject(**decode_value(value.get("attrs", {})))
    return {k: decode_value(v) for k, v in value.items()}


class SimpleObject(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return "%s(%s)" % (
            type(self).__name__,
            ", ".join("%s=%r" % item for item in sorted(self.__dict__.items())),
        )
