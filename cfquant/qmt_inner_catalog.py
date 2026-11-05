"""Allowlisted built-in QMT API, grouped like the official innerApi manual.

Keep this module compatible with QMT's Python 3.6. It is also embedded in Lite.
Targets are deliberately explicit: a global function is not a ContextInfo method.
"""

INNER_DOC_ROOT = "https://dict.thinktrader.net/innerApi/"
INNER_CATEGORIES = {
    "system": "system_function.html",
    "market": "data_function.html",
    "trade": "trading_function.html",
    "callbacks": "callback_function.html",
    "reference": "quote_function.html",
}

# (category, native owner, names). 'context_arg' appends the bound ContextInfo.
# Scope: external data/research and live trading. Chart rendering, bar lifecycle,
# backtest orders, model/VBA execution and superseded APIs are not exposed.
_INNER_GROUPS = [
    ("system", "context", "get_stock_name get_open_date schedule_run cancel_schedule_run "
     "set_account set_universe get_universe"),
    ("system", "global", "create_sector create_sector_folder get_sector_list "
     "reset_sector_stock_list remove_stock_from_sector add_stock_to_sector"),
    ("market", "context", "get_market_data_ex get_full_tick subscribe_quote subscribe_whole_quote "
     "unsubscribe_quote get_svol get_bvol get_turnover_rate get_longhubang get_north_finance_change "
     "get_hkt_details get_hkt_statistics get_local_data "
     "get_financial_data get_raw_financial_data get_last_volume get_total_share get_instrument_detail "
     "get_his_st_data get_main_contract get_contract_multiplier get_contract_expire_date "
     "get_his_contract_list get_option_detail_data get_option_list get_option_undl_data bsm_price bsm_iv "
     "get_divid_factors get_weight_in_index get_stock_list_in_sector get_trading_dates"),
    ("market", "global", "download_history_data get_etf_info get_etf_iopv get_st_status"),
    ("trade", "global", "get_smart_algo_param get_basket set_basket get_trade_detail_data "
     "get_history_trade_detail_data get_ipo_data get_new_purchase_limit get_value_by_order_id "
     "get_last_order_id get_assure_contract get_enable_short_contract get_option_subject_position "
     "get_comb_option get_unclosed_compacts get_closed_compacts get_hkt_exchange_rate"),
    ("trade", "context_arg", "passorder algo_passorder smart_algo_passorder cancel cancel_task "
     "pause_task resume_task query_credit_account query_credit_opvolume"),
    ("reference", "context_arg", "ext_data ext_data_rank ext_data_rank_range ext_data_range "
     "get_factor_value get_factor_rank"),
]
INNER_METHODS = {(category, name): owner for category, owner, names in _INNER_GROUPS for name in names.split()}
INNER_CALLBACKS = (
    "account_callback", "task_callback", "order_callback", "deal_callback", "position_callback",
    "orderError_callback", "credit_account_callback", "credit_opvolume_callback",
)
INNER_CONTEXT_ATTRIBUTES = (
    "barpos", "stockcode", "market", "period", "start", "end", "capital", "benchmark",
)


def inner_method_owner(category, name):
    try:
        return INNER_METHODS[(category, name)]
    except KeyError:
        raise ValueError("Undocumented or unsupported built-in QMT method: %s.%s" % (category, name))
