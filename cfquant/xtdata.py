# -*- coding: utf-8 -*-
import time

from .client import configure, get_client


_subscription_callbacks = {}


def get_market_data(
    field_list=[],
    stock_list=[],
    period="1d",
    start_time="",
    end_time="",
    count=-1,
    dividend_type="none",
    fill_data=True,
):
    return get_client().request("xtdata.get_market_data", {
        "field_list": field_list,
        "stock_list": stock_list,
        "period": period,
        "start_time": start_time,
        "end_time": end_time,
        "count": count,
        "dividend_type": dividend_type,
        "fill_data": fill_data,
    })


def get_market_data_ex(
    field_list=[],
    stock_list=[],
    period="1d",
    start_time="",
    end_time="",
    count=-1,
    dividend_type="none",
    fill_data=True,
):
    return get_client().request("xtdata.get_market_data_ex", {
        "field_list": field_list,
        "stock_list": stock_list,
        "period": period,
        "start_time": start_time,
        "end_time": end_time,
        "count": count,
        "dividend_type": dividend_type,
        "fill_data": fill_data,
    })


def get_full_tick(code_list):
    return get_client().request("xtdata.get_full_tick", {
        "code_list": code_list,
    })


def get_local_data(
    field_list=[],
    stock_list=[],
    period="1d",
    start_time="",
    end_time="",
    count=-1,
    dividend_type="none",
    fill_data=True,
    data_dir=None,
    stock_code="",
    divid_type=None,
):
    return get_client().request("xtdata.get_local_data", {
        "field_list": field_list,
        "stock_list": stock_list,
        "stock_code": stock_code,
        "period": period,
        "start_time": start_time,
        "end_time": end_time,
        "count": count,
        "dividend_type": dividend_type,
        "divid_type": divid_type if divid_type is not None else dividend_type,
        "fill_data": fill_data,
        "data_dir": data_dir,
    })


def subscribe_quote(stock_code, period="1d", start_time="", end_time="", count=0, callback=None):
    result = get_client().request("xtdata.subscribe_quote", {
        "stock_code": stock_code,
        "period": period,
        "start_time": start_time,
        "end_time": end_time,
        "count": count,
    })
    subscribe_id = result.get("subscribe_id") if isinstance(result, dict) else result
    if callback and subscribe_id is not None:
        event_name = "quote:%s" % subscribe_id
        _subscription_callbacks[subscribe_id] = (event_name, callback)
        get_client().add_callback(event_name, callback)
    return subscribe_id


def subscribe_whole_quote(code_list, callback=None):
    result = get_client().request("xtdata.subscribe_whole_quote", {
        "code_list": code_list,
    })
    subscribe_id = result.get("subscribe_id") if isinstance(result, dict) else result
    if callback and subscribe_id is not None:
        event_name = "quote:%s" % subscribe_id
        _subscription_callbacks[subscribe_id] = (event_name, callback)
        get_client().add_callback(event_name, callback)
    return subscribe_id


def subscribe_quote2(stock_code, period="1d", start_time="", end_time="", count=0, dividend_type=None, callback=None):
    result = get_client().request("xtdata.subscribe_quote", {
        "stock_code": stock_code,
        "period": period,
        "start_time": start_time,
        "end_time": end_time,
        "count": count,
        "dividend_type": dividend_type,
    })
    subscribe_id = result.get("subscribe_id") if isinstance(result, dict) else result
    if callback and subscribe_id is not None:
        event_name = "quote:%s" % subscribe_id
        _subscription_callbacks[subscribe_id] = (event_name, callback)
        get_client().add_callback(event_name, callback)
    return subscribe_id


def unsubscribe_quote(seq):
    item = _subscription_callbacks.pop(seq, None)
    if item:
        event_name, callback = item
        get_client().remove_callback(event_name, callback)
    return get_client().request("xtdata.unsubscribe_quote", {
        "subscribe_id": seq,
    })


def download_history_data(stock_code, period, start_time="", end_time="", incrementally=None, callback=None):
    if callback:
        return download_history_data2([stock_code], period, start_time, end_time, callback=callback, incrementally=incrementally)
    return get_client().request("xtdata.download_history_data", {
        "stock_code": stock_code,
        "period": period,
        "start_time": start_time,
        "end_time": end_time,
        "incrementally": incrementally,
    })


def download_history_data2(
    stock_list,
    period,
    start_time="",
    end_time="",
    callback=None,
    incrementally=None,
    job_id=None,
    keep_callback=False,
):
    event_name = None
    if callback:
        event_name = "download_history:%s:%s" % (period, int(time.time() * 1000))
        get_client().add_callback(event_name, callback)
    try:
        return get_client().request("xtdata.download_history_data2", {
            "stock_list": stock_list,
            "period": period,
            "start_time": start_time,
            "end_time": end_time,
            "incrementally": incrementally,
            "callback_event": event_name,
            "download_job_id": job_id,
            "download_emit_lifecycle": bool(event_name),
        })
    finally:
        if event_name and callback and not keep_callback:
            get_client().remove_callback(event_name, callback)


def get_instrument_detail(stock_code, iscomplete=False):
    return get_client().request("xtdata.get_instrument_detail", {
        "stock_code": stock_code,
        "iscomplete": iscomplete,
    })


def get_stock_list_in_sector(sector_name):
    return get_client().request("xtdata.get_stock_list_in_sector", {
        "sector_name": sector_name,
    })


def get_financial_data(field_list, stock_list, start_time="", end_time="", report_type="announce_time"):
    return get_client().request("xtdata.get_financial_data", {
        "field_list": field_list,
        "stock_list": stock_list,
        "start_time": start_time,
        "end_time": end_time,
        "report_type": report_type,
    })


def get_financial_data_ori(field_list, stock_list, start_time="", end_time="", report_type="announce_time"):
    return get_client().request("xtdata.get_financial_data_ori", {
        "field_list": field_list,
        "stock_list": stock_list,
        "start_time": start_time,
        "end_time": end_time,
        "report_type": report_type,
    })


def get_raw_financial_data(field_list, stock_list, start_time="", end_time="", report_type="announce_time"):
    return get_financial_data_ori(field_list, stock_list, start_time, end_time, report_type)


def download_financial_data(stock_list, table_list=None, start_time="", end_time="", callback=None, job_id=None, keep_callback=False):
    event_name = None
    if callback:
        event_name = "download_financial:%s" % int(time.time() * 1000)
        get_client().add_callback(event_name, callback)
    try:
        return get_client().request("xtdata.download_financial_data", {
            "stock_list": stock_list,
            "table_list": table_list or [],
            "start_time": start_time,
            "end_time": end_time,
            "callback_event": event_name,
            "download_job_id": job_id,
            "download_emit_lifecycle": bool(event_name),
        })
    finally:
        if event_name and callback and not keep_callback:
            get_client().remove_callback(event_name, callback)


def download_financial_data2(stock_list, table_list=None, start_time="", end_time="", callback=None, job_id=None, keep_callback=False):
    return download_financial_data(stock_list, table_list, start_time, end_time, callback, job_id, keep_callback)


def get_trading_dates(stockcode, start_date="", end_date="", count=-1, period="1d"):
    return get_client().request("xtdata.get_trading_dates", {
        "stockcode": stockcode,
        "start_date": start_date,
        "end_date": end_date,
        "count": count,
        "period": period,
    })


def is_stock(stock_code):
    return _stock_basic_request("is_stock", stock_code)


def is_fund(stock_code):
    return _stock_basic_request("is_fund", stock_code)


def is_future(stock_code):
    return _stock_basic_request("is_future", stock_code)


def get_stock_type(stock_code):
    return _stock_basic_request("get_stock_type", stock_code)


def get_stock_name(stock_code):
    return _stock_basic_request("get_stock_name", stock_code)


def get_open_date(stock_code):
    return _stock_basic_request("get_open_date", stock_code)


def get_contract_expire_date(stock_code):
    return _stock_basic_request("get_contract_expire_date", stock_code)


def get_contract_multiplier(stock_code):
    return _stock_basic_request("get_contract_multiplier", stock_code)


def get_weight_in_index(mtkindexcode, stockcode):
    return get_client().request("xtdata.get_weight_in_index", {
        "mtkindexcode": mtkindexcode,
        "stockcode": stockcode,
    })


def get_turnover_rate(stock_code, start_time="", end_time=""):
    return get_client().request("xtdata.get_turnover_rate", {
        "stock_code": stock_code,
        "start_time": start_time,
        "end_time": end_time,
    })


def get_ETF_list(market="", stockcode="", typeList=None):
    return get_client().request("xtdata.get_ETF_list", {
        "market": market,
        "stockcode": stockcode,
        "typeList": typeList or [],
    })


def get_etf_list(market="", stockcode="", type_list=None):
    return get_ETF_list(market, stockcode, type_list)


def get_option_detail_data(stockcode):
    return get_client().request("xtdata.get_option_detail_data", {
        "stockcode": stockcode,
    })


def get_option_list(object, dedate, opttype="", isavailavle=False):
    return get_client().request("xtdata.get_option_list", {
        "object": object,
        "dedate": dedate,
        "opttype": opttype,
        "isavailavle": isavailavle,
    })


def get_option_undl(opt_code):
    return get_client().request("xtdata.get_option_undl", {
        "opt_code": opt_code,
    })


def get_option_undl_data(undl_code_ref=""):
    return get_client().request("xtdata.get_option_undl_data", {
        "undl_code_ref": undl_code_ref,
    })


def get_his_st_data(stockCode):
    return get_client().request("xtdata.get_his_st_data", {
        "stockCode": stockCode,
    })


def get_his_index_data(stockCode):
    return get_client().request("xtdata.get_his_index_data", {
        "stockCode": stockCode,
    })


def get_factor_data(field_list, stock_list, start_date="", end_date=""):
    return get_client().request("xtdata.get_factor_data", {
        "field_list": field_list,
        "stock_list": stock_list,
        "start_date": start_date,
        "end_date": end_date,
    })


def _callback_placeholder():
    return {"__cfquant_callback_arg__": True}


def _generic_xtdata_request(action, *args, **kwargs):
    timeout = kwargs.pop("timeout", None)
    keep_callback = bool(kwargs.pop("keep_callback", str(action).startswith("subscribe_")))
    callback_name = str(kwargs.pop("callback_name", "callback") or "callback")
    callback = kwargs.pop(callback_name, None)
    callback_positions = []
    wire_args = []
    for index, value in enumerate(args):
        if callable(value):
            if callback is not None:
                raise TypeError("only one callback can be passed to xtdata.%s" % action)
            callback = value
            callback_positions.append(index)
            wire_args.append(_callback_placeholder())
        else:
            wire_args.append(value)
    event_name = None
    if callback is not None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        event_name = "xtdata:%s:%s" % (action, int(time.time() * 1000))
        get_client().add_callback(event_name, callback)
    try:
        return get_client().request("xtdata.%s" % action, {
            "args": wire_args,
            "kwargs": kwargs,
            "callback_event": event_name,
            "callback_positions": callback_positions,
            "callback_name": callback_name,
        }, timeout=timeout)
    finally:
        if event_name and callback and not keep_callback:
            get_client().remove_callback(event_name, callback)


def _make_generic_xtdata_func(action):
    def func(*args, **kwargs):
        return _generic_xtdata_request(action, *args, **kwargs)
    func.__name__ = action
    func.__qualname__ = action
    func.__doc__ = (
        "Conditional xtdata compatibility wrapper. "
        "It forwards to the same-named QMT callable when the running QMT environment exposes it."
    )
    return func


_CONDITIONAL_XTDATA_METHODS = [
    "get_trading_calendar",
    "get_trading_period",
    "get_kline_trading_period",
    "get_all_trading_periods",
    "get_period_list",
    "create_sector",
    "add_sector",
    "remove_sector",
    "reset_sector",
    "remove_stock_from_sector",
    "create_formula",
    "call_formula",
    "subscribe_formula",
    "unsubscribe_formula",
    "get_formula_result",
    "get_l2_quote",
    "get_l2_order",
    "get_l2_transaction",
    "subscribe_l2thousand",
    "get_l2thousand_queue",
    "get_tabular_data",
    "download_tabular_data",
    "push_custom_data",
    "download_sector_data",
    "download_index_weight",
    "download_history_contracts",
    "download_holiday_data",
    "download_etf_info",
    "download_cb_data",
    "download_his_st_data",
    "download_metatable_data",
]

for _method in _CONDITIONAL_XTDATA_METHODS:
    globals()[_method] = _make_generic_xtdata_func(_method)
del _method


def _stock_basic_request(action, stock_code):
    return get_client().request("xtdata.%s" % action, {
        "stock_code": stock_code,
    })


def run():
    get_client().start()
    while True:
        time.sleep(1)
