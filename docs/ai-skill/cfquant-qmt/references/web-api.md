# Web API Reference

This reference summarizes public Web API behavior documented for the local `cfquant` Web Console and API debug surface. Endpoint fields and return-field notes are from the shipped API-debug metadata; do not infer additional private or ignored runtime behavior.

## General Shape

The local Web Console normally runs on:

```text
http://127.0.0.1:8765/
```

Responses use a JSON envelope:

```json
{"ok": true, "data": {}}
```

Errors use:

```json
{"ok": false, "error": "message", "status": 400}
```

When authentication is enabled, the Web API can require Web auth or an API key. Public examples should keep auth generic:

- `X-API-Key: <api-key>` header.
- `Authorization: Bearer <api-key>` header.
- `apikey=<api-key>` query parameter for WebSocket or simple clients.

## Common Parameters

| Parameter | Meaning |
| --- | --- |
| `bridge_id` | Internal QMT bridge id. Account APIs usually do not need it when Web account binding is configured. |
| `account_id` | Fund/account id. Use placeholders in examples. |
| `account_type` | `STOCK`, `CREDIT`, `FUTURE`, `FUTURE_OPTION`, or `STOCK_OPTION`. These match ordinary securities, margin/credit, futures, futures option, and stock/ETF option accounts. |
| `account_key` | Account binding key used by Web routing when configured. |
| `channel` | In advanced mode, `normal` means ordinary QMT and `trade` means fast trade terminal. In general mode the backend routes through the ctypes bridge. |
| `timeout` | Per-call timeout in seconds. Docs commonly use around 12 seconds for debugging. |

## Data And Quote Endpoints

| Endpoint | Status | Purpose | Typical request/query fields |
| --- | --- | --- | --- |
| `POST /api/data/full-tick` | Implemented | Real-time tick/full-push snapshot. | `code_list`, optional `bridge_id`, `channel`, `timeout`. |
| `POST /api/data/market` | Implemented | Market data query. | `field_list`, `stock_list`, `period`, `start_time`, `end_time`, `count`, `dividend_type`, `fill_data`, optional routing fields. |
| `POST /api/data/market-ex` | Implemented | Extended market data query. | Same as `/api/data/market`. |
| `POST /api/data/instrument` | Implemented | Instrument/security detail. | `stock_code`, `iscomplete`, optional routing fields. |
| `POST /api/data/sector` | Implemented | Sector constituent list. | `sector_name`, optional routing fields. |
| `POST /api/data/history/download` | Implemented | Trigger single-security historical data download. | `stock_code`, `period`, `start_time`, `end_time`, `incrementally`, optional routing fields. |
| `POST /api/data/history/download-batch` | Not implemented in public docs | Proposed Web page addition for batch historical download. | Corresponds to `xtdata.download_history_data2` if later added. |
| `POST /api/data/financial` | Implemented | Financial data read. | `stock_code` or stock list, `table`, `fields`, `mode`, `start_time`, `end_time`, `report_type`, optional routing fields. |
| `POST /api/data/financial/download` | Implemented compatibility entry | Validate/preload local already-downloaded financial data. | Same financial fields as read endpoint; explain manual QMT client download requirement. |
| `POST /api/quotes/whole/subscribe` | Implemented | Subscribe full-push market quotes. | `markets` or `code_list`, optional `bridge_id`, `channel`, `timeout`. |
| `POST /api/quotes/subscribe` | Implemented | Subscribe single-security quote events. | `stock_code`, `period`, `start_time`, `end_time`, `count`, `dividend_type`, optional routing fields. |
| `POST /api/quotes/unsubscribe` | Implemented | Cancel quote subscription. | `subscribe_id`, optional routing fields. |
| `GET /api/quotes/latest` | Implemented | Read cached quote events. | `since`, `limit`, optional `subscribe_id`. |
| `WS /ws/quotes` | Implemented | Receive quote events in real time. | Optional `subscribe_id`, auth query if needed. |

Financial download caveat: public docs say big-QMT official script side does not expose a true financial download function. Users must first use QMT client data management to download financial data, then this endpoint validates/reads local data.

## Trade And Account Endpoints

| Endpoint | Status | Purpose | Typical request/query fields |
| --- | --- | --- | --- |
| `GET /api/account` | Implemented | Query account sections. | `account_id`, `account_type`, `sections=asset|positions|orders|trades`, optional `force`, `subscribe`, `timeout`, routing fields. |
| `POST /api/order` | Implemented | Submit one order for ordinary, credit, futures, futures-option, or stock-option accounts. | `account_id`, `account_type`, `side=buy|sell`, `stock_code`, `price_type`, `price`, `volume`, `confirm_text`, optional `credit_action`, `order_action`, `strategy_name`, `order_remark`, `timeout`. |
| `POST /api/orders/batch` | Implemented | Submit batch orders for ordinary, credit, futures, futures-option, or stock-option accounts. | `account_id`, `account_type`, `orders` array, `confirm_text`, optional `credit_action`, `order_action`, `price_type`, `stop_on_error`, `timeout`. |
| `POST /api/cancel` | Implemented | Cancel an order. | `account_id`, `account_type`, `order_id`, `confirm_text`, `timeout`. |
| `GET /api/callbacks` | Implemented | Pull cached trade callback events. | `account_id`, `account_type`, `since`, `limit`, optional `event`, `event_prefix`, `job_id`, routing fields. |
| `WS /ws/callbacks` | Implemented | Receive trade callback events in real time. | `account_id`, `account_type`, optional `event`, `event_prefix`, `job_id`, auth query if needed. |
| `GET /api/order/actions` | Implemented | Return supported credit, futures, futures-option, and stock-option order actions. | No required fields. |
| `GET /api/credit/actions` | Implemented | Return supported credit query actions and credit order actions. | No required fields. |
| `POST /api/credit/query` | Implemented | Credit account query. | `account_id`, `account_type=CREDIT`, `action=detail|subjects|slo_code|assure|compacts`, optional routing fields. |
| `POST /api/credit/probe` | Implemented | Read-only credit capability probe. | `account_id`, `account_type=CREDIT`, optional routing fields. |
| `POST /api/credit/order` | Implemented | Submit one credit business order. | `account_id`, `account_type=CREDIT`, `credit_action`, `stock_code`, `price_type`, `price`, `volume`, `confirm_text`, optional routing fields. |
| `POST /api/credit/orders/batch` | Implemented | Submit batch credit business orders. | Same as `/api/orders/batch`, with default or per-row `credit_action`. |
| `POST /api/future/order` | Implemented | Submit one futures business order. | `account_id`, `account_type=FUTURE`, `order_action`, `stock_code`, `price_type`, `price`, `volume`, `confirm_text`, optional routing fields. |
| `POST /api/future/orders/batch` | Implemented | Submit batch futures business orders. | Same as `/api/orders/batch`, with default or per-row `order_action`. |
| `POST /api/future-option/order` | Implemented | Submit one futures-option business order. | `account_id`, `account_type=FUTURE_OPTION`, `order_action`, `stock_code`, `price_type`, `price`, `volume`, `confirm_text`, optional routing fields. |
| `POST /api/future-option/orders/batch` | Implemented | Submit batch futures-option business orders. | Same as `/api/orders/batch`, with default or per-row `order_action`. |
| `POST /api/stock-option/order` | Implemented | Submit one stock/ETF option business order. | `account_id`, `account_type=STOCK_OPTION`, `order_action`, `stock_code`, `price_type`, `price`, `volume`, `confirm_text`, optional routing fields. |
| `POST /api/stock-option/orders/batch` | Implemented | Submit batch stock/ETF option business orders. | Same as `/api/orders/batch`, with default or per-row `order_action`. |

Trade safety from public Web behavior:

- `POST /api/order` requires exact confirmation text. Ordinary stock examples use `BUY code volume @ price` or `SELL code volume @ price`; credit and derivative examples use `ACTION code volume @ price`, for example `CREDIT_FIN_BUY 000001.SZ 100 @ 10.000` or `FUTURE_OPEN_LONG IF2601.IF 1 @ 4200.000`.
- `POST /api/orders/batch` requires `confirm_text` like `BATCH 2`.
- `POST /api/cancel` requires `confirm_text` like `CANCEL order_id`.
- Do not auto-generate real account ids, prices, or quantities for live use.

Order action semantics:

- Credit accounts can use `credit_action`, such as `credit_buy`, `credit_fin_buy`, `credit_slo_sell`, `credit_direct_cash_repay`, and special variants.
- Futures and futures-option accounts can use `order_action`, such as `future_open_long`, `future_open_short`, `future_close_long_today`, and `future_option_exercise`.
- Stock-option accounts can use `order_action`, such as `stock_option_buy_open`, `stock_option_sell_close`, `stock_option_sell_open`, `stock_option_buy_close`, covered open/close, exercise, lock, and unlock actions.
- `price_type` uses MiniQMT numeric values, defaulting to `FIX_PRICE=11`. Fixed-price orders require `price > 0`; latest/market-style price types can use `price=0`.

## System And Transport Endpoints

| Endpoint | Status | Purpose |
| --- | --- | --- |
| `GET /api/status` | Implemented | Bridge status. With account fields, resolves account route status; without account, returns latest bridge monitor status. |
| `GET /api/transport` | Implemented | Read current transport mode and client route. |
| `POST /api/transport` | Implemented | Switch Web transport mode. Advanced mode requires ordinary and trade channels online before enabling. |
| `GET /api/pipe-hub` | Implemented | PipeHub status for general ctypes mode. |
| `POST /api/pipe-hub/start` | Implemented | Start PipeHub. |
| `POST /api/pipe-hub/stop` | Implemented | Stop PipeHub. |

## WebSocket Event Shapes

Callback WebSocket sends an initial hello message, then callback messages:

```json
{
  "type": "callback",
  "channel": "callbacks",
  "event": {
    "seq": 12,
    "event": "trader:on_stock_order",
    "account_id": "YOUR_ACCOUNT_ID",
    "bridge_id": "default",
    "received_at": 1783440000.123,
    "data": {
      "stock_code": "000001.SZ",
      "m_strOrderSysID": "123456789"
    }
  }
}
```

Documented callback event names include:

- `trader:on_stock_asset`
- `trader:on_stock_position`
- `trader:on_stock_order`
- `trader:on_stock_trade`
- `trader:on_order_error`
- `trader:on_cancel_error`
- `trader:on_order_stock_async_response`
- `trader:on_cancel_order_stock_async_response`
- `xtdata:download_progress`

Common callback data fields include `stock_code`, `m_strAccountID`, `m_strInstrumentID`, `m_strExchangeID`, `m_strInstrumentName`, `m_nOrderType`, `m_nBusinessType`, `m_nDirection`, `m_nOffsetFlag`, `m_nPriceType`, `m_nOrderPriceType`, `m_nVolumeTotalOriginal`, `m_nVolumeTraded`, `m_nVolume`, `m_nFrozenVolume`, `m_nOnRoadVolume`, `m_nYesterdayVolume`, `m_dPrice`, `m_dLimitPrice`, `m_dOrderPrice`, `m_dTradeAmount`, `m_dCommission`, `m_dLastPrice`, `m_dProfitRate`, `m_nOrderStatus`, `m_strOrderSysID`, `m_strOrderID`, `m_nOrderID`, `m_strStatusMsg`, `m_dBalance`, `m_dAvailable`, `m_dInstrumentValue`, and download `meta.*` fields such as `meta.job_id`, `meta.stage`, and `meta.download_kind`.

## Example Request Bodies

Tick:

```json
{
  "code_list": ["000001.SZ", "600000.SH"],
  "channel": "trade",
  "timeout": 12
}
```

Market data:

```json
{
  "field_list": ["open", "high", "low", "close", "volume"],
  "stock_list": ["000001.SZ"],
  "period": "1d",
  "start_time": "20240101",
  "end_time": "20241231",
  "count": -1,
  "dividend_type": "none",
  "fill_data": true,
  "timeout": 12
}
```

Read account asset:

```text
GET /api/account?account_id=YOUR_ACCOUNT_ID&account_type=STOCK&sections=asset&force=1&subscribe=0&timeout=12
```

Illustrative order body:

```json
{
  "account_id": "YOUR_ACCOUNT_ID",
  "account_type": "STOCK",
  "side": "buy",
  "stock_code": "000001.SZ",
  "price": 10.0,
  "volume": 100,
  "confirm_text": "BUY 000001.SZ 100 @ 10.000",
  "timeout": 12
}
```

Illustrative futures order body:

```json
{
  "account_id": "YOUR_FUTURE_ACCOUNT_ID",
  "account_type": "FUTURE",
  "order_action": "future_open_long",
  "stock_code": "IF2601.IF",
  "price_type": 11,
  "price": 4200.0,
  "volume": 1,
  "confirm_text": "FUTURE_OPEN_LONG IF2601.IF 1 @ 4200.000",
  "timeout": 12
}
```

Illustrative stock-option order body:

```json
{
  "account_id": "YOUR_OPTION_ACCOUNT_ID",
  "account_type": "STOCK_OPTION",
  "order_action": "stock_option_buy_open",
  "stock_code": "10000001.SH",
  "price_type": 11,
  "price": 0.1,
  "volume": 1,
  "confirm_text": "STOCK_OPTION_BUY_OPEN 10000001.SH 1 @ 0.100",
  "timeout": 12
}
```

Credit probe:

```json
{
  "account_id": "YOUR_CREDIT_ACCOUNT_ID",
  "account_type": "CREDIT",
  "timeout": 5
}
```
