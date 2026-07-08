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
):
    return get_market_data_ex(
        field_list=field_list,
        stock_list=stock_list,
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=count,
        dividend_type=dividend_type,
        fill_data=fill_data,
    )


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


def download_history_data(stock_code, period, start_time="", end_time="", incrementally=None):
    return get_client().request("xtdata.download_history_data", {
        "stock_code": stock_code,
        "period": period,
        "start_time": start_time,
        "end_time": end_time,
        "incrementally": incrementally,
    })


def download_history_data2(stock_list, period, start_time="", end_time="", callback=None, incrementally=None):
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
        })
    finally:
        if event_name and callback:
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


def run():
    get_client().start()
    while True:
        time.sleep(1)
