# Python SDK Reference

This reference summarizes the public docs for external Python usage, `xtdata`, `XtQuantTrader`, callback handling, and compatibility limits.

## Requirements

The public docs describe `cfquant` as a Windows-oriented local bridge for big QMT:

- Windows.
- Big QMT installed and logged in.
- Python 3.8 to 3.12. Production use prefers Python 3.10 or 3.12.
- QMT-side entry script must be loaded and online before external calls can succeed.
- New users should finish the Web Console initialization wizard before writing external strategy code.

## Installation And Startup

Source deployment is recommended for complete Web Console usage:

```powershell
cd D:\cfquant
python -m pip install -r requirements.txt
start_cfquant.bat
```

PyPI install is documented for library calls or temporary experience:

```powershell
python -m pip install -U cfquant
cfquant --open-browser
```

QMT scripts bundled in the installed Python environment can be inspected or exported:

```powershell
cfquant qmt-scripts
cfquant qmt-scripts --open
cfquant qmt-scripts --output D:\QMT\cfquant
```

Optional ZMQ/LTtx dependency:

```powershell
pip install "cfquant[zmq]"
```

## Imports

External code should import `cfquant` in an `xtquant`-like style:

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
```

`StockAccount(account_id, account_type="STOCK", bridge_id=None)` is the documented account object shape. Public docs use:

- `STOCK` for ordinary securities accounts.
- `CREDIT` for margin/credit accounts.
- `FUTURE` for futures accounts.
- `FUTURE_OPTION` for futures-option accounts.
- `STOCK_OPTION` for stock/ETF option accounts.

`session_id` is retained as a compatibility constructor argument in `XtQuantTrader`. If it is omitted or set to `0`, `cfquant` auto-assigns a positive integer for the trader instance. Real routing still comes from Web account binding, account type, account key, and `bridge_id`.

## Default Routing

Default behavior is `CFQUANT_TRANSPORT=auto`; most users should not call `configure()` manually.

Auto route flow from the docs:

1. Web service starts and writes runtime registration to LTtx.
2. External `cfquant` reads that registration when it starts.
3. If discovery succeeds, requests enter the Web unified route channel.
4. Web chooses general or advanced routing based on account binding.
5. If advanced mode is configured but unavailable, Web falls back to that account's general ctypes bridge.
6. If Web discovery fails, `auto` falls back to direct general PipeHub.

Relevant environment variables:

```text
CFQUANT_TRANSPORT=auto
CFQUANT_DISCOVERY_KEY=cfquant.runtime
CFQUANT_WEB_REQUEST_CHANNEL=cfquant.web.request
CFQUANT_LTTX_HOST=127.0.0.1
CFQUANT_LTTX_PORT=2049
CFQUANT_LTTX_TOKEN=LTtx
```

Manual routing should be treated as troubleshooting or special deployment.

Web unified route:

```python
from cfquant import configure

configure(
    transport="web_lttx",
    host="127.0.0.1",
    port=2049,
    token="LTtx",
    web_request_channel="cfquant.web.request",
)
```

Direct general PipeHub:

```python
from cfquant import configure

configure(
    transport="ctypes",
    pipe_name=r"\\.\pipe\cfquant_pipe_hub",
    timeout=15,
)
```

Direct advanced/legacy LTtx:

```python
from cfquant import configure

configure(
    transport="lttx",
    host="127.0.0.1",
    port=2049,
    token="LTtx",
    timeout=15,
)
```

## Documented `xtdata` Capabilities

Core implemented groups:

| API group | Public-doc status and notes |
| --- | --- |
| `get_full_tick` | Implemented real-time tick/full-push snapshot. |
| `get_market_data`, `get_market_data_ex` | Implemented market data query. Advanced mode may prefer trade/fast channel and fall back to ordinary QMT. |
| `get_local_data` | Implemented against QMT callable, but `data_dir` is only a compatibility parameter; `cfquant` does not take over MiniQMT local directory semantics. |
| `subscribe_quote`, `subscribe_quote2`, `subscribe_whole_quote`, `unsubscribe_quote` | Implemented quote subscription and event forwarding. Public docs note a single active external full-push subscription on the Web side. |
| `download_history_data`, `download_history_data2` | Implemented historical data download. Batch download supports progress callback event forwarding. |
| `get_instrument_detail`, `get_stock_list_in_sector` | Implemented instrument detail and sector constituent lookup. Sector parameters remain simplified. |
| `get_trading_dates` | Implemented trading calendar query. |
| `is_stock`, `is_fund`, `is_future`, `get_stock_type`, `get_stock_name`, `get_open_date` | Implemented security type and basic attribute helpers when QMT callable exists. |
| `get_contract_expire_date`, `get_contract_multiplier` | Implemented contract expiry and multiplier helpers. |
| `get_weight_in_index`, `get_turnover_rate` | Implemented index weight and turnover-rate helpers. |
| `get_ETF_list`, `get_etf_list` | Implemented ETF list helpers. |
| `get_option_detail_data`, `get_option_list`, `get_option_undl`, `get_option_undl_data` | Implemented option detail/list/underlying helpers. |
| `get_his_st_data`, `get_his_index_data`, `get_factor_data` | Implemented historical ST, historical index data, and factor data helpers. |
| `get_financial_data`, `get_financial_data_ori`, `get_raw_financial_data` | Implemented financial data reading. |
| `download_financial_data`, `download_financial_data2` | Compatibility entry only. Public docs state big-QMT official scripts do not provide a financial download callable; this degrades to local already-downloaded financial data validation/preload and instructs users to download through QMT client data management first. |

Conditionally forwarded `xtdata` groups:

- Trading calendar/period additions: `get_trading_calendar`, `get_trading_period`, `get_kline_trading_period`, `get_all_trading_periods`, `get_period_list`.
- Sector maintenance: `create_sector`, `add_sector`, `remove_sector`, `reset_sector`, `remove_stock_from_sector`.
- Formula system: `create_formula`, `call_formula`, `subscribe_formula`, `unsubscribe_formula`, `get_formula_result`.
- L2 market data: `get_l2_quote`, `get_l2_order`, `get_l2_transaction`, `subscribe_l2thousand`, `get_l2thousand_queue`.
- Tabular/external data: `get_tabular_data`, `download_tabular_data`, `push_custom_data`.
- Download additions: `download_sector_data`, `download_index_weight`, `download_history_contracts`, `download_holiday_data`, `download_etf_info`, `download_cb_data`, `download_his_st_data`, `download_metatable_data`.

For conditionally forwarded APIs, say they are available only if the running QMT environment exposes the corresponding callable and permissions. Return shapes follow the underlying QMT callable unless public docs specify a wrapper.

## Documented `XtQuantTrader` Capabilities

The public docs say `cfquant` has completed the main trading/query chain for ordinary stock, credit, futures, futures-option, and stock-option accounts while keeping the original `XtQuantTrader` public method set aligned. `disconnect()` is additionally retained for actively closing the local bridge connection.

Implemented main chain:

| API | Public-doc behavior |
| --- | --- |
| `start`, `stop`, `connect`, `run_forever` | Manage local RPC client lifecycle and trade callback registration. |
| `register_callback` | Register callback object and map QMT bridge events to `XtQuantTraderCallback`. |
| `subscribe`, `unsubscribe` | Subscribe/unsubscribe account-level trade callback forwarding. |
| `order_stock`, `order_stock_async` | Submit ordinary, credit, futures, futures-option, or stock-option orders through QMT `passorder`; async path emits bridge events. The public Python signature remains MiniQMT-compatible: `account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark`. |
| `cancel_order_stock`, `cancel_order_stock_async` | Cancel orders through QMT `cancel`; account type is routed for ordinary, credit, futures, futures-option, and stock-option accounts. Async path emits bridge events. |
| `query_stock_asset` | Read account detail and wrap as `XtAsset`. |
| `query_stock_orders`, `query_stock_order` | Read order details and wrap as `XtOrder`; single-order lookup matches known order-id fields. |
| `query_stock_trades` | Read trade details and wrap as `XtTrade`. |
| `query_stock_positions`, `query_stock_position` | Read position details and wrap as `XtPosition`. |
| `query_stock_asset_async`, `query_stock_orders_async`, `query_stock_trades_async`, `query_stock_positions_async` | Compatibility async entries; public docs note some async methods execute synchronously then call callback and return a local seq. |
| `set_timeout`, `set_relaxed_response_order_enabled`, `sleep` | Compatibility helpers. |
| `common_op_sync_with_seq`, `common_op_async_with_seq` | Local callable compatibility helpers. |

Partially implemented or requiring real-QMT verification:

- `cancel_order_stock_sysid`, `cancel_order_stock_sysid_async`: entry is present, but system-ID cancel parameters may differ across QMT versions and require real environment verification.
- `query_com_fund`, `query_com_position`: mapped to account/position detail, but field names may differ from native `xtquant`.

Compatibility entries that depend on QMT callable availability:

- Account information: `query_account_info`, `query_account_infos`, async variants, account status variants.
- Composite queries: `query_position_statistics`, `query_secu_account`.
- Credit business: `query_credit_detail`, `query_credit_subjects`, `query_credit_slo_code`, `query_credit_assure`, `query_stk_compacts`, plus async variants.
- IPO/new purchase: `query_ipo_data`, `query_new_purchase_limit`, plus async variants.
- Bank/security transfer: bank info/amount/stream, bank transfer in/out, fund transfer, security transfer.
- CTP option/future internal transfer.
- Data sync/export: `query_data`, `export_data`, `sync_transaction_from_external`.
- SMT entries: compact/order/quoter query and appointment/negotiate/return/renewal async calls.

For these entries, answer that missing QMT callables produce clear not-implemented errors similar to `xttrader.xxx requires QMT callable: ...`.

Order type and account semantics:

- `STOCK`: `STOCK_BUY=23` and `STOCK_SELL=24` are passed through to big-QMT `passorder`.
- `CREDIT`: MiniQMT credit constants and `credit_action` values are mapped to big-QMT credit opTypes.
- `FUTURE`: MiniQMT `FUTURE_*` constants 0-22 are passed through.
- `FUTURE_OPTION`: MiniQMT futures-style constants are passed through, and `OPTION_FUTURE_OPTION_EXERCISE=100` is supported.
- `STOCK_OPTION`: callers use MiniQMT `STOCK_OPTION_*` constants 48-57; the bridge maps them to big-QMT ETF option opTypes 50-59.
- Web-facing derivative requests may use `order_action` names such as `future_open_long`, `future_open_short`, `stock_option_buy_open`, or `stock_option_sell_open`; Python callers can continue passing numeric `order_type` values.

## Callback Model

`XtQuantTraderCallback` public docs list 14 callback methods, all present in `cfquant`:

- Connection: `on_connected`, `on_disconnected`.
- Account/trade data: `on_account_status`, `on_stock_asset`, `on_stock_order`, `on_stock_trade`, `on_stock_position`.
- Errors: `on_order_error`, `on_cancel_error`.
- Async responses: `on_order_stock_async_response`, `on_cancel_order_stock_async_response`, `on_bank_transfer_async_response`, `on_ctp_internal_transfer_async_response`, `on_smt_appointment_async_response`.

Bridge/Web event names are generally `trader:<callback_method>`, for example `trader:on_stock_order`.

## Field Mapping Guidance

Migration docs warn users not to assume every return field exactly matches MiniQMT. Recommend an internal adapter layer and verify at least:

- Order: local order id, system/counter id, stock or contract code, side, `direction`, `offset_flag`, `order_type`, `price_type`, price, volume, traded volume, status, time, remark.
- Trade: trade id, order id, stock or contract code, `direction`, `offset_flag`, traded price, traded volume, traded time, amount, commission.
- Position: stock or contract code/name, total volume, available volume, frozen/on-road/yesterday volume, `direction`, cost/average price, latest price, market value, profit, profit rate.
- Asset: total asset, available cash, frozen cash, market value.

For production migration, first save sample raw returns from the user's broker/QMT environment and map them into the user's own stable model.
