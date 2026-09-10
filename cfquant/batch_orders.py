"""Batch wire contract and QMT execution, compatible with embedded Python 3.6."""

import math
import os
import time
from collections.abc import Mapping
from numbers import Integral, Real


CFTRADER_BATCH_ACTIONS = frozenset(("cftrader.order_stock_batch", "cftrader.order_stock_batch_async"))
_BATCH_ORDER_FIELDS = {"stock_code", "order_type", "order_volume", "price_type", "price",
                       "strategy_name", "order_remark"}
_BATCH_REQUIRED_FIELDS = {"stock_code", "order_type", "order_volume", "price_type", "price"}


def batch_positive_id(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, Integral):
        return value > 0
    return isinstance(value, str) and value.isdigit() and int(value) > 0


def prepare_batch_orders(orders, batch_id, strategy_name="", order_remark="", stop_on_error=False):
    if not isinstance(stop_on_error, bool):
        raise ValueError("stop_on_error must be a boolean")
    for name, value in (("batch_id", batch_id), ("strategy_name", strategy_name), ("order_remark", order_remark)):
        if not isinstance(value, str):
            raise ValueError("%s must be a string" % name)
    if not batch_id:
        raise ValueError("batch_id is required")
    if not isinstance(orders, (list, tuple)) or not orders:
        raise ValueError("orders must be a non-empty list or tuple of mappings")
    rows, correlations = [], set()
    for index, order in enumerate(orders):
        label = "orders[%s]" % index
        if not isinstance(order, Mapping):
            raise ValueError("%s must be a mapping" % label)
        missing = _BATCH_REQUIRED_FIELDS - order.keys()
        unexpected = order.keys() - _BATCH_ORDER_FIELDS
        if missing or unexpected:
            raise ValueError("%s: missing fields=%s; unexpected fields=%s" %
                             (label, sorted(missing), sorted(str(key) for key in unexpected)))
        row = dict(order)
        if not isinstance(row["stock_code"], str) or not row["stock_code"].strip():
            raise ValueError("%s.stock_code is required" % label)
        row["stock_code"] = row["stock_code"].strip()
        for name in ("order_type", "order_volume", "price_type"):
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError("%s.%s must be an integer" % (label, name))
            row[name] = int(value)
        if row["order_volume"] <= 0:
            raise ValueError("%s.order_volume must be positive" % label)
        price = row["price"]
        try:
            finite = isinstance(price, Real) and not isinstance(price, bool) and math.isfinite(price)
        except (OverflowError, ValueError):
            finite = False
        if not finite:
            raise ValueError("%s.price must be a finite number" % label)
        row["price"] = float(price)
        row.setdefault("strategy_name", strategy_name)
        row.setdefault("order_remark", "")
        for name in ("strategy_name", "order_remark"):
            if not isinstance(row[name], str):
                raise ValueError("%s.%s must be a string" % (label, name))
        row["order_remark"] = row["order_remark"] or "%s_%s" % (order_remark or batch_id, index + 1)
        # QMT callbacks can omit the exchange suffix from instrument codes.
        correlation = (row["stock_code"].upper().split(".", 1)[0], row["order_remark"])
        if correlation in correlations:
            raise ValueError("%s repeats stock_code and order_remark; use distinct remarks" % label)
        correlations.add(correlation)
        rows.append(row)
    return rows


def prepare_batch_request(params, asynchronous):
    account = params.get("account")
    if not isinstance(account, dict) or not str(account.get("account_id") or "").strip():
        raise ValueError("account_id is required")
    rows = prepare_batch_orders(params.get("orders"), params.get("batch_id"),
                                params.get("strategy_name", ""), params.get("order_remark", ""),
                                params.get("stop_on_error", False))
    seqs = params.get("seqs", [])
    if asynchronous:
        if (not isinstance(seqs, list) or len(seqs) != len(rows)
                or any(isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0 for seq in seqs)
                or len(set(seqs)) != len(seqs)):
            raise ValueError("seqs must contain one distinct positive integer per order")
    elif seqs:
        raise ValueError("synchronous batches must not include seqs")
    return rows


def batch_result_rows(orders, seqs=None):
    return [{"index": index, "stock_code": row["stock_code"], "status": "skipped", "ok": None,
             "order_id": None, "seq": seqs[index] if seqs else None,
             "strategy_name": row["strategy_name"], "order_remark": row["order_remark"], "error": ""}
            for index, row in enumerate(orders)]


def batch_result(account, batch_id, asynchronous, results):
    counts = {name: sum(row["status"] == name for row in results)
              for name in ("submitted", "failed", "unknown", "skipped")}
    return dict(counts, batch_id=batch_id, account=account, asynchronous=asynchronous,
                execution="qmt", total=len(results), attempted=len(results) - counts["skipped"],
                ok=counts["submitted"] == len(results), results=results)


def batch_unknown(rows, error):
    for row in rows:
        row.update(status="unknown", ok=None, error=str(error) or type(error).__name__)


def validate_batch_response(result, params, asynchronous):
    expected = params["orders"]
    if (not isinstance(result, dict) or result.get("execution") != "qmt"
            or result.get("batch_id") != params["batch_id"] or result.get("asynchronous") is not asynchronous
            or result.get("account") != params["account"]
            or not isinstance(result.get("results"), list) or len(result["results"]) != len(expected)):
        raise ValueError("Invalid QMT batch response; update the Web service and QMT bridge")
    for index, (row, order) in enumerate(zip(result["results"], expected)):
        if (not isinstance(row, dict) or row.get("index") != index
                or row.get("stock_code") != order["stock_code"] or row.get("order_remark") != order["order_remark"]
                or row.get("strategy_name") != order["strategy_name"]
                or not {"ok", "seq", "order_id", "error"}.issubset(row)
                or row.get("status") not in ("submitted", "failed", "unknown", "skipped")):
            raise ValueError("Invalid QMT batch row; reconcile orders before retrying")
        if row["ok"] is not {"submitted": True, "failed": False, "unknown": None, "skipped": None}[row["status"]]:
            raise ValueError("QMT batch returned an inconsistent row status")
        if asynchronous and (isinstance(row["seq"], bool) or row["seq"] != params["seqs"][index]):
            raise ValueError("QMT batch returned a different seq")
        if row["status"] == "submitted" and not batch_positive_id(row.get("seq" if asynchronous else "order_id")):
            raise ValueError("QMT batch returned an invalid order ID or seq")
    verified = batch_result(params["account"], params["batch_id"], asynchronous, result["results"])
    if "qmt_submit_ms" in result:
        verified["qmt_submit_ms"] = result["qmt_submit_ms"]
    return verified


def execute_qmt_batch(bridge, params, msg, asynchronous):
    orders = prepare_batch_request(params, asynchronous)
    account = params["account"]
    results = batch_result_rows(orders, params.get("seqs") if asynchronous else None)
    # Resolve every operation before submitting anything, including credit/derivative enums.
    account_type = bridge._account_type_name(account.get("account_type"))
    for order in orders:
        bridge._passorder_optype(order, account_type)
    before_ids = None
    if not asynchronous:
        try:
            before_ids = {bridge._order_id_from_detail(row) for row in bridge._query_trade_detail({"account": account}, "order") or []}
        except Exception:
            pass
    unresolved = []
    started = time.perf_counter()
    for index, (order, row) in enumerate(zip(orders, results)):
        request = dict(order, account=account)
        if asynchronous:
            request["seq"] = params["seqs"][index]
        try:
            native = bridge._order_stock(request, msg, resolve_order_id=False, capture_previous_id=False)
            if bridge._is_failed_order_result(native.get("request_result")):
                row.update(status="failed", ok=False, error="QMT rejected the order request")
            elif asynchronous:
                pending = bridge._async_order_record(request, msg, native)
                order_id = bridge._normalize_order_id(native.get("order_id"))
                if order_id is not None:
                    bridge._send_async_order_response(pending, order_id)
                else:
                    bridge._register_pending_async_order(pending)
                row.update(status="submitted", ok=True)
            elif batch_positive_id(native.get("order_id")):
                row.update(status="submitted", ok=True, order_id=native["order_id"])
            else:
                row.update(status="unknown", order_id=-1, error="Order submitted; order ID not yet confirmed")
                unresolved.append(row)
        except Exception as error:
            batch_unknown([row], error)
            break
        if row["status"] == "failed" and params.get("stop_on_error", False):
            break
    submit_ms = round((time.perf_counter() - started) * 1000, 3)
    # Native submission is complete before any polling. Never use the account's
    # last order ID for a batch: several rows can otherwise acquire the same ID.
    if unresolved and before_ids is not None:
        try:
            _resolve_batch_order_ids(bridge, account, unresolved, before_ids)
        except Exception as error:
            batch_unknown(unresolved, "Order ID resolution failed: %s" % error)
    result = batch_result(account, params["batch_id"], asynchronous, results)
    result["qmt_submit_ms"] = submit_ms
    return result


def _resolve_batch_order_ids(bridge, account, pending, before_ids):
    try:
        wait = max(0.0, float(os.environ.get("CFQUANT_ORDER_ID_WAIT_SECONDS", "2.0")))
    except (TypeError, ValueError):
        wait = 2.0
    if not math.isfinite(wait):
        wait = 2.0
    deadline = time.monotonic() + wait
    while pending:
        try:
            orders = bridge._query_trade_detail({"account": account}, "order") or []
        except Exception:
            return
        matches = {}
        for order in orders:
            order_id = bridge._order_id_from_detail(order)
            if not batch_positive_id(order_id) or order_id in before_ids:
                continue
            code = str(bridge._first_value(order, ("stock_code", "m_strInstrumentID")) or "").upper().split(".", 1)[0]
            remark = str(bridge._first_value(order, ("order_remark", "m_strRemark", "m_strOrderRemark")) or "")
            matches.setdefault((code, remark), set()).add(order_id)
        for row in list(pending):
            ids = matches.get((row["stock_code"].upper().split(".", 1)[0], row["order_remark"]), set())
            if len(ids) == 1:
                row.update(status="submitted", ok=True, order_id=next(iter(ids)), error="")
                pending.remove(row)
        remaining = deadline - time.monotonic()
        if not pending or remaining <= 0:
            return
        time.sleep(min(0.05, remaining))
