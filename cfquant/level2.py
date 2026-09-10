"""Level2 data adapters shared by the SDK and QMT bridges."""

L2_PERIODS = (
    "l2quote", "l2quoteaux", "l2order", "l2transaction",
    "l2transactioncount", "l2orderqueue",
)
L2_GET_PERIODS = {
    "get_l2_quote": "l2quote",
    "get_l2_order": "l2order",
    "get_l2_transaction": "l2transaction",
}
L2_THOUSAND_SUBSCRIPTIONS = ("subscribe_l2thousand", "subscribe_l2thousand_queue")


def quote_plain(value):
    if type(value).__module__.startswith("pandas.") and type(value).__name__ in ("NAType", "NaTType"):
        return None
    if isinstance(value, dict):
        return {key: quote_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [quote_plain(item) for item in value]
    if hasattr(value, "tolist"):
        return quote_plain(value.tolist())
    if hasattr(value, "item"):
        return quote_plain(value.item())
    return value


def quote_records(value):
    if hasattr(value, "columns") and hasattr(value, "to_dict"):
        # DataFrame.values can round large integer IDs in a mixed float/int table.
        return quote_plain(value.to_dict("records"))
    names = getattr(getattr(value, "dtype", None), "names", None)
    if names:
        return [{name: quote_plain(row[name]) for name in names} for row in value]
    if isinstance(value, dict):
        return [quote_plain(value)] if value else []
    if isinstance(value, (list, tuple)):
        if not all(isinstance(row, dict) for row in value):
            raise ValueError("QMT quote rows must be dictionaries")
        return quote_plain(value)
    if value is None:
        return []
    raise ValueError("unsupported QMT quote data type: %s" % type(value).__name__)


def quote_callback_data(data):
    if not isinstance(data, dict):
        raise ValueError("QMT quote callback must be a stock-code dictionary")
    return {code: quote_records(value) for code, value in data.items()}


def require_l2_callable(func, method):
    if not callable(func):
        raise NotImplementedError(
            "xtdata.%s requires the native QMT callable %s; "
            "ordinary Level2 quotes/order queues cannot substitute for this data product"
            % (method, method)
        )
    return func


def thousand_price(params):
    price = params.get("price")
    return tuple(price) if params.get("price_is_range") and price is not None else price


def l2_query(func, period, params):
    if not callable(func):
        raise NotImplementedError("Level2 %s requires QMT get_market_data_ex" % period)

    def bind(field_list=None, stock_code="", start_time="", end_time="", count=-1):
        return field_list or [], stock_code, start_time, end_time, count

    if "args" in params or "kwargs" in params:
        fields, code, start, end, count = bind(*(params.get("args") or []), **(params.get("kwargs") or {}))
    else:
        fields, code, start, end, count = bind(**{key: params[key] for key in
            ("field_list", "stock_code", "start_time", "end_time", "count") if key in params})
    if not isinstance(code, str) or not code:
        raise ValueError("stock_code is required for Level2 queries")
    # Exact period, no forward filling, and no fallback to Level1 data.
    result = func(fields, [code], period, start, end, count, "none", False)
    if result is None or (isinstance(result, dict) and not result):
        return None
    if not isinstance(result, dict):
        raise ValueError("QMT get_market_data_ex must return a stock-code dictionary")
    value = result.get(code)
    if value is None:
        return None
    rows = quote_records(value)
    columns = list(getattr(value, "columns", []))
    if not columns:
        columns = list(getattr(getattr(value, "dtype", None), "names", None) or [])
    if not columns:
        columns = list(dict.fromkeys(name for row in rows for name in row))
    if fields:
        missing = [field for field in fields if columns and field not in columns]
        if missing:
            raise ValueError("QMT Level2 data is missing requested fields: %s" % ", ".join(missing))
        columns = list(fields)
        rows = [{key: row[key] for key in columns if key in row} for row in rows]
    return {"columns": columns, "records": rows}


def l2_array(result):
    if result is None:
        return None
    import numpy as np

    columns, rows = result["columns"], result["records"]
    arrays = []
    for name in columns:
        values = [row.get(name) for row in rows]
        if not values or any(value is None or isinstance(value, (dict, list, tuple)) for value in values):
            array = np.empty(len(values), dtype=object)
            array[:] = values
        else:
            array = np.asarray(values)
            if array.dtype.kind == "f" and any(isinstance(value, int) and abs(value) > 2 ** 53 for value in values):
                array = np.asarray(values, dtype=object)
        arrays.append(array)
    data = np.empty(len(rows), dtype=[(name, array.dtype) for name, array in zip(columns, arrays)])
    for name, array in zip(columns, arrays):
        data[name] = array
    return data
