"""Synchronize standalone Lite bridge behavior with the shared QMT bridge.

The Lite entry points cannot import ``cfquant.tx_trade_bridge`` in some QMT
installations, so this keeps the compatible adapter code embedded in the GBK
scripts.  It is intentionally separate from the batch-order synchronizer:
these adapters are part of the public query/data contract.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
try:
    from tools.sync_qmt_fileless import updated_source as update_fileless_source
    from tools.sync_qmt_latency import updated_source as update_latency_source
except ImportError:
    from sync_qmt_fileless import updated_source as update_fileless_source
    from sync_qmt_latency import updated_source as update_latency_source


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "cfquant" / "tx_trade_bridge.py"
LITE_PATHS = sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py"))


def _class_node(source, class_name="TxTradeBridge"):
    tree = ast.parse(source)
    return next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )


def _method_source(source, class_name, method_name):
    tree = ast.parse(source)
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    return "".join(source.splitlines(keepends=True)[method.lineno - 1:method.end_lineno])


def _replace_method(source, class_name, method_name, replacement):
    cls = _class_node(source, class_name)
    method = next(
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    lines = source.splitlines(keepends=True)
    lines[method.lineno - 1:method.end_lineno] = replacement.splitlines(keepends=True)
    return "".join(lines)


def _insert_method(source, replacement, anchor="    def _dispatch_xttrader_compat("):
    if not replacement.strip():
        return source
    name = next(
        line.strip()[4:].split("(", 1)[0]
        for line in replacement.splitlines()
        if line.startswith("    def ")
    )
    if ("    def %s(" % name) in source:
        return source
    index = source.index(anchor)
    return source[:index] + replacement.rstrip() + "\n\n" + source[index:]


def _upsert_method(source, replacement):
    """Replace an embedded adapter when its generator source changes."""
    replacement = replacement.rstrip("\n") + "\n"
    name = next(
        line.strip()[4:].split("(", 1)[0]
        for line in replacement.splitlines()
        if line.startswith("    def ")
    )
    if "    def %s(" % name in source:
        return _replace_method(source, "TxTradeBridge", name, replacement)
    return _insert_method(source, replacement)


def _ensure_top_level(source, marker, text, anchor="class TxTradeBridge(object):"):
    if marker in source:
        return source
    index = source.index(anchor)
    return source[:index] + text.rstrip() + "\n\n" + source[index:]


def _credit_adapter_source():
    return r'''    def _query_account_id(self, params):
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")
        return account_id

    def _call_trade_detail_data(self, func, account_id, account_type, detail_type):
        variants = [
            ((account_id, account_type, detail_type), {}),
            ((account_id, account_type, detail_type, ""), {}),
        ]
        last_error = None
        for args, kwargs in variants:
            try:
                return func(*args, **kwargs)
            except TypeError as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise RuntimeError("no available trade detail call variant")

    def _credit_account_id(self, params):
        account_id = self._query_account_id(params)
        account = params.get("account") or {}
        account_type = self._account_type_name(
            account.get("account_type") or params.get("account_type")
        )
        if account_type.upper() != "CREDIT":
            raise ValueError("credit query requires a CREDIT account")
        return account_id

    def _credit_row_data(self, row, aliases):
        if isinstance(row, dict):
            return self._plain_value(row)
        data = {}
        names = {"account_id", "account_type", "m_strAccountID", "m_nAccountType", "m_strAccountType", "m_nBrokerType"}
        names.update(aliases.keys())
        for values in aliases.values():
            names.update(values)
        for name in names:
            value = self._get_value(row, name)
            if value is not None:
                data[name] = value
        if not data:
            try:
                for name in dir(row):
                    if name.startswith("_"):
                        continue
                    value = getattr(row, name)
                    if not callable(value):
                        data[name] = self._plain_value(value)
            except Exception:
                pass
        return data

    def _credit_field_value(self, data, names):
        for name in names:
            if name in data and data.get(name) is not None:
                return data.get(name)
            if name.startswith("m_"):
                compact = name[:1] + name[2:]
                if compact in data and data.get(compact) is not None:
                    return data.get(compact)
        return None

    def _format_credit_rows(self, rows, params, kind, source):
        account_id = self._credit_account_id(params)
        if rows is None:
            return None
        if isinstance(rows, (str, bytes, dict)):
            raise ValueError("%s returned an invalid credit query result" % source)
        aliases = _LITE_CREDIT_FIELD_ALIASES.get(kind, {})
        result = []
        for row in rows:
            data = self._credit_row_data(row, aliases)
            if not data:
                raise ValueError("%s returned an invalid credit account row" % source)
            for name in ("account_id", "m_strAccountID"):
                value = data.get(name)
                if value not in (None, "", account_id):
                    raise ValueError("%s returned a different account" % source)
            for name in ("account_type", "m_nAccountType", "m_strAccountType", "m_nBrokerType"):
                value = data.get(name)
                if value not in (None, "") and str(value).upper() not in ("3", "CREDIT"):
                    raise ValueError("%s returned a non-CREDIT account" % source)
            for target, names in aliases.items():
                value = self._credit_field_value(data, (target,) + tuple(names))
                if value is not None:
                    data[target] = value
            data["account_id"] = account_id
            data["account_type"] = 3
            if kind == "detail" and source == "get_trade_detail_data":
                raw_quotas = {
                    name: data.pop(name)
                    for name in ("m_dFinUsedQuota", "m_dSloUsedQuota")
                    if name in data
                }
                if raw_quotas:
                    data["cfquant_qmt_fields"] = raw_quotas
            data["cfquant_source"] = source
            data["cfquant_missing_fields"] = [
                target for target, names in aliases.items()
                if self._credit_field_value(data, (target,) + tuple(names)) is None
            ]
            result.append(data)
        return result

    def _query_credit_detail(self, params):
        account_id = self._credit_account_id(params)
        func = self._get_callable("get_trade_detail_data")
        if func:
            rows = self._call_trade_detail_data(func, account_id, "credit", "account")
            return self._format_credit_rows(rows, params, "detail", "get_trade_detail_data")
        rows = self._generic_xttrader_call("query_credit_detail", params)
        return self._format_credit_rows(rows, params, "detail", "query_credit_detail")

    def _query_qmt_objects(self, params, kind, source):
        account_id = self._credit_account_id(params)
        func = self._get_callable(source)
        if not func:
            raise NotImplementedError("%s not found" % source)
        rows = func(account_id)
        return self._format_credit_rows(rows, params, kind, source)

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
        return self._format_credit_rows(rows, params, "compact", source)
'''


_CREDIT_ALIASES = '''
_LITE_CREDIT_FIELD_ALIASES = {
    "detail": {
        "m_nStatus": (), "m_nUpdateTime": (), "m_nCalcConfig": (),
        "m_dFrozenCash": (), "m_dBalance": (), "m_dAvailable": (),
        "m_dPositionProfit": (), "m_dMarketValue": ("m_dInstrumentValue",),
        "m_dFetchBalance": (), "m_dStockValue": (), "m_dFundValue": (),
        "m_dTotalDebt": ("m_dTotalDebit",), "m_dEnableBailBalance": (),
        "m_dPerAssurescaleValue": (), "m_dAssureAsset": (), "m_dFinDebt": (),
        "m_dFinDealAvl": (), "m_dFinFee": (), "m_dSloDebt": (),
        "m_dSloMarketValue": (), "m_dSloFee": (), "m_dOtherFare": (),
        "m_dFinMaxQuota": (), "m_dFinEnableQuota": (), "m_dFinUsedQuota": (),
        "m_dSloMaxQuota": (), "m_dSloEnableQuota": (), "m_dSloUsedQuota": (),
        "m_dSloSellBalance": (), "m_dUsedSloSellBalance": (),
        "m_dSurplusSloSellBalance": (),
    },
    "compact": {
        "compact_type": ("m_eCompactType",), "cashgroup_prop": ("m_eCashgroupProp",),
        "exchange_id": ("m_strExchangeID",), "open_date": ("m_nOpenDate",),
        "business_vol": ("m_nBusinessVol",), "real_compact_vol": ("m_nRealCompactVol",),
        "ret_end_date": ("m_nRetEndDate",), "business_balance": ("m_dBusinessBalance",),
        "businessFare": ("m_dBusinessFare",), "real_compact_balance": ("m_dRealCompactBalance",),
        "real_compact_fare": ("m_dRealCompactFare",), "repaid_fare": ("m_dRepaidFare",),
        "repaid_balance": ("m_dRepaidBalance",), "instrument_id": ("m_strInstrumentID",),
        "compact_id": ("m_strCompactId", "m_strCompactID"), "position_str": ("m_strPositionStr",),
    },
    "subjects": {
        "exchange_id": ("m_strExchangeID",), "instrument_id": ("m_strInstrumentID",),
        "slo_status": ("m_eSloStatus",), "fin_status": ("m_eFinStatus",),
        "slo_ratio": ("m_dSloRatio",), "fin_ratio": ("m_dFinRatio",),
    },
    "assure": {
        "exchange_id": ("m_strExchangeID",), "instrument_id": ("m_strInstrumentID",),
        "assure_status": ("m_eAssureStatus",), "assure_ratio": ("m_dAssureRatio",),
    },
    "slo_code": {
        "exchange_id": ("m_strExchangeID",), "instrument_id": ("m_strInstrumentID",),
        "cashgroup_prop": ("m_eCashgroupProp", "m_eQuerySloType"),
        "enable_amount": ("m_nEnableAmount",),
    },
}
'''


def _patch_source(source, core):
    protocol = (ROOT / "cfquant" / "protocol.py").read_text(encoding="utf-8")
    for node in ast.parse(protocol).body:
        if isinstance(node, ast.FunctionDef) and node.name in ("_quote_json_default", "pack_quote_latency_event", "pack_whole_quote_event"):
            replacement = "".join(protocol.splitlines(True)[node.lineno - 1:node.end_lineno])
            existing = next((item for item in ast.parse(source).body
                             if isinstance(item, ast.FunctionDef) and item.name == node.name), None)
            if existing:
                lines = source.splitlines(True)
                lines[existing.lineno - 1:existing.end_lineno] = [replacement]
                source = "".join(lines)
            else:
                source = _ensure_top_level(source, "def %s(" % node.name, replacement)
    # The generated scripts are checked in as standalone files.  Normalize
    # this import before inserting it so running the synchronizer repeatedly
    # is stable even after an interrupted or older run. Anchor on json, since
    # the fileless synchronizer removes the obsolete io import.
    source = re.sub(r"(?m)^import inspect\n", "", source)
    source = source.replace("import json\n", "import inspect\nimport json\n", 1)
    source = _ensure_top_level(
        source,
        "def market_data_result_needs_fallback(",
        '''def market_data_result_needs_fallback(result):
    if result is None:
        return True
    if isinstance(result, dict):
        return not result or all(getattr(value, "empty", False) for value in result.values())
    if getattr(result, "empty", False):
        return True
    return not hasattr(result, "columns") and not hasattr(result, "to_records")
''',
        anchor="class TxTradeBridge(object):",
    )
    source = _ensure_top_level(
        source,
        "SMT_ASYNC_ARGUMENT_COUNTS =",
        '''SMT_ASYNC_ARGUMENT_COUNTS = {
    "smt_appointment_order": 4,
    "smt_appointment_cancel": 1,
    "smt_negotiate_order": 6,
    "smt_compact_return": 4,
    "smt_compact_renewal": 5,
}

XTTRADER_TRANSFER_RESULT_METHODS = {
    "bank_transfer_in", "bank_transfer_out", "fund_transfer", "secu_transfer",
    "ctp_transfer_future_to_option", "ctp_transfer_option_to_future",
}

LITE_OBJECT_QUERY_METHODS = {
    "query_account_info", "query_account_infos", "query_account_status",
    "query_secu_account", "query_bank_info", "query_bank_amount",
    "query_bank_transfer_stream",
}
''',
        anchor="class TxTradeBridge(object):",
    )
    source = _ensure_top_level(
        source,
        "LITE_OBJECT_QUERY_METHODS =",
        '''LITE_OBJECT_QUERY_METHODS = {
    "query_account_info", "query_account_infos", "query_account_status",
    "query_secu_account", "query_bank_info", "query_bank_amount",
    "query_bank_transfer_stream",
}
''',
        anchor="class TxTradeBridge(object):",
    )
    source = _ensure_top_level(source, "_LITE_CREDIT_FIELD_ALIASES =", _CREDIT_ALIASES)

    # These methods have no package-only dependencies and can follow the
    # shared bridge exactly.
    for name in (
        "_handle_raw",
        "_dispatch",
        "_dispatch_timed_market_data",
        "_timed_market_call",
        "_legacy_market_result",
        "_get_market_data",
        "_get_market_data_ex",
        "_get_local_data",
        "_call_local_data",
        "_get_instrument_detail",
        "_require_qmt_callable",
        "_get_cb_info",
        "_get_divid_factors",
        "_get_stock_list_in_sector",
        "_get_sector_list",
        "_create_sector_folder",
        "_create_sector",
        "_validate_sector_stocks",
        "_reset_sector",
        "_remove_stock_from_sector",
        "_call_formula_batch",
        "_instrument_detail_callable_missing",
        "_fallback_instrument_detail",
        "_instrument_code_info",
        "_infer_stock_exchange_id",
        "_stock_code_candidates",
        "_optional_stock_callable",
        "_optional_stock_bool",
        "_coerce_optional_bool",
        "_fallback_product_id",
        "_format_compat_query_objects",
        "_format_compat_query_object",
        "_known_query_fields",
        "_plain_object",
        "_first_present",
        "_smt_response_data",
        "_smt_request",
    ):
        source = _replace_method(source, "TxTradeBridge", name, _method_source(core, "TxTradeBridge", name)) if "    def %s(" % name in source else _insert_method(source, _method_source(core, "TxTradeBridge", name))

    normal = (ROOT / "cfquant" / "normal_bridge.py").read_text(encoding="utf-8")
    for name in ("_send_response", "_send_error", "_dispatch", "_subscribe_native_quote", "_subscribe_internal_whole_quote"):
        source = _replace_method(source, "NormalQmtBridge", name, _method_source(normal, "NormalQmtBridge", name))

    xtdata_dispatch = _method_source(core, "TxTradeBridge", "_dispatch_xtdata_compat")
    xtdata_dispatch = xtdata_dispatch.replace(
        '        source = module_source_state(__file__, _LOADED_SOURCE_SHA256, self.started_at)\n'
        '        hint = ""\n'
        '        raise NotImplementedError("xtdata.%s is not implemented by cfquant QMT bridge%s" % (method, hint))\n',
        '        raise NotImplementedError("xtdata.%s is not implemented by cfquant QMT bridge" % method)\n',
    )
    # The current shared source has a one-line hint expression; keep Lite
    # standalone and remove that package-only source-state branch robustly.
    for marker in ("        source = module_source_state", "        source = self._source_state()"):
        if marker in xtdata_dispatch:
            start = xtdata_dispatch.index(marker)
            xtdata_dispatch = xtdata_dispatch[:start] + '        raise NotImplementedError("xtdata.%s is not implemented by cfquant QMT bridge" % method)\n'
    source = _replace_method(source, "TxTradeBridge", "_dispatch_xtdata_compat", xtdata_dispatch)

    # Credit/query compatibility is deliberately plain-dict based in Lite;
    # the external SDK restores the documented query objects after the wire.
    for replacement in (_credit_adapter_source(),):
        blocks = re.split(r"(?m)(?=^    def )", replacement.strip("\n"))
        for block in blocks:
            if not block.strip():
                continue
            source = _upsert_method(source, block)

    dispatch = _method_source(source, "TxTradeBridge", "_dispatch_xttrader_compat")
    dispatch = '''    def _dispatch_xttrader_compat(self, action, params, msg):
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
        if method in LITE_OBJECT_QUERY_METHODS:
            rows = self._generic_xttrader_call(method, params)
            return self._format_compat_query_objects(rows, force_list=True)
        if method == "query_position_statistics":
            account_id = self._query_account_id(params)
            account = params.get("account") or {}
            account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
            if account_type.upper() != "FUTURE":
                raise ValueError("query_position_statistics requires a FUTURE account")
            func = self._get_callable("get_trade_detail_data")
            if func:
                rows = self._call_trade_detail_data(func, account_id, "future", "position_statistics")
            else:
                rows = self._generic_xttrader_call(method, params)
            return self._format_compat_query_objects(rows, force_list=True)
        if method == "query_credit_detail":
            return self._query_credit_detail(params)
        if method == "query_stk_compacts":
            return self._query_stk_compacts(params)
        if method in ("query_credit_assure", "query_credit_subjects", "query_credit_slo_code"):
            kind, native = {
                "query_credit_assure": ("assure", "get_assure_contract"),
                "query_credit_subjects": ("subjects", "get_assure_contract"),
                "query_credit_slo_code": ("slo_code", "get_enable_short_contract"),
            }[method]
            self._credit_account_id(params)
            if self._get_callable(native):
                return self._query_qmt_objects(params, kind, native)
            rows = self._generic_xttrader_call(method, params)
            return self._format_credit_rows(rows, params, kind, method)
        if method == "query_position_statistics" and self._get_callable("get_trade_detail_data"):
            account_id = self._query_account_id(params)
            account = params.get("account") or {}
            account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
            if account_type.upper() != "FUTURE":
                raise ValueError("query_position_statistics requires a FUTURE account")
            return self._query_trade_detail(params, "position")
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
        if method in XTTRADER_TRANSFER_RESULT_METHODS:
            result = self._generic_xttrader_call(method, params)
            return self._format_transfer_result(result, params)
        return self._generic_xttrader_call(method, params)
'''
    source = _replace_method(source, "TxTradeBridge", "_dispatch_xttrader_compat", dispatch)

    source = _upsert_method(source, '''    def _format_transfer_result(self, result, params):
        seq = params.get("seq")
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            return {"seq": seq, "success": self._plain_value(result[0]), "msg": self._plain_value(result[1])}
        data = result if isinstance(result, dict) else self._credit_row_data(result, {})
        if isinstance(data, dict):
            return {
                "seq": seq if seq is not None else self._first_present(data, ("seq", "m_nSeq", "request_id")),
                "success": self._first_present(data, ("success", "m_bSuccess", "ok", "accepted")),
                "msg": self._first_present(data, ("msg", "m_strMsg", "m_strError", "message", "error", "error_msg"), ""),
            }
        return data
''')

    source = source.replace(
        '        if action == "xtdata.get_stock_list_in_sector":\n            return self.context.get_stock_list_in_sector(params.get("sector_name", ""))\n',
        '        if action == "xtdata.get_stock_list_in_sector":\n            return self._get_stock_list_in_sector(params)\n',
    )
    source = source.replace(
        '            rows = func(query_account_id, account_type.lower(), detail_type.lower()) or []',
        '            rows = self._call_trade_detail_data(func, query_account_id, account_type.lower(), detail_type.lower()) or []',
    )
    source = source.replace(
        '                rows = func(account_id, account_type.lower(), detail_type.lower()) or []',
        '                rows = self._call_trade_detail_data(func, account_id, account_type.lower(), detail_type.lower()) or []',
    )
    source = source.replace(
        '            rows = func(account_id, account_type.lower(), detail_type.lower()) or []',
        '            rows = self._call_trade_detail_data(func, account_id, account_type.lower(), detail_type.lower()) or []',
    )
    ast.parse(source, feature_version=(3, 6))
    return update_latency_source(source)


def main():
    core = CORE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    outdated = []
    for path in LITE_PATHS:
        raw = path.read_bytes()
        source = raw.decode("gbk").replace("\r\n", "\n")
        updated = update_fileless_source(_patch_source(source, core), lite=True)
        if updated == source:
            continue
        outdated.append(str(path.relative_to(ROOT)))
        newline = "\r\n" if raw.count(b"\r\n") > raw.count(b"\n") / 2 else "\n"
        path.write_bytes(updated.replace("\n", newline).encode("gbk"))
    for item in outdated:
        print("Updated: " + item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
