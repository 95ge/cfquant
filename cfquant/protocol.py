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
    if "|" in raw:
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


def pack_response(request_id, ok=True, result=None, error=None, meta=None):
    return dumps_message({
        "type": "response",
        "id": request_id,
        "ok": bool(ok),
        "result": encode_value(result),
        "error": encode_error(error),
        "meta": meta or {},
    })


def pack_event(event, data=None, client_id=None, subscription_id=None, meta=None):
    return dumps_message({
        "type": "event",
        "event": event,
        "client_id": client_id,
        "subscription_id": subscription_id,
        "data": encode_value(data),
        "meta": meta or {},
    })


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
        return encode_value(value.tolist())
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


def _encode_dataframe(value):
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
    index_name = getattr(getattr(value, "index", None), "name", None)
    return {
        "__cf_type__": "dataframe",
        "columns": [str(c) for c in getattr(value, "columns", [])],
        "index": [str(i) for i in getattr(value, "index", [])],
        "data": rows,
        "index_name": str(index_name) if index_name is not None else None,
        "object_columns": [str(name) for name, dtype in getattr(value, "dtypes", {}).items()
                           if str(dtype) == "object" or str(dtype).startswith(("Int", "UInt"))],
    }


def _encode_series(value):
    try:
        raw_values = value.values.tolist()
    except Exception:
        raw_values = []
    return {
        "__cf_type__": "series",
        "index": [str(i) for i in getattr(value, "index", [])],
        "data": [_clean_cell(v) for v in raw_values],
        "name": str(value.name) if getattr(value, "name", None) is not None else None,
    }


def decode_value(value):
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    if not isinstance(value, dict):
        return value

    value_type = value.get("__cf_type__")
    if value_type == "bytes":
        return base64.b64decode(value.get("data", ""))
    if value_type == "dataframe":
        import pandas as pd
        columns = value.get("columns", [])
        rows = [[decode_value(cell) for cell in row] for row in value.get("data", [])]
        object_columns = value.get("object_columns", [])
        if object_columns and columns:
            # Construct columns independently, preserving duplicate field labels too.
            df = pd.concat([pd.Series([row[i] for row in rows], dtype=object if name in object_columns else None)
                            for i, name in enumerate(columns)], axis=1)
            df.columns = columns
        else:
            df = pd.DataFrame(rows, columns=columns)
        index = value.get("index", [])
        if len(index) == len(df):
            df.index = index
        if value.get("index_name"):
            df.index.name = value.get("index_name")
        return df
    if value_type == "series":
        import pandas as pd
        return pd.Series(
            [decode_value(v) for v in value.get("data", [])],
            index=value.get("index", []),
            name=value.get("name"),
        )
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
