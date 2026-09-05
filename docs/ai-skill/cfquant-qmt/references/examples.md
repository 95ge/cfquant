# Examples

Use placeholders for accounts and keep trade examples illustrative. Do not represent these examples as live-trade recommendations.

## Query Real-Time Tick

```python
from cfquant import xtdata

tick = xtdata.get_full_tick(["000001.SZ"])
print(tick)
```

## Query Asset And Positions

```python
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
trader = XtQuantTrader("", account=account)
trader.start()

asset = trader.query_stock_asset(account)
positions = trader.query_stock_positions(account)
print(asset)
print(positions)
```

## Subscribe Trade Callback

```python
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount


class Callback(XtQuantTraderCallback):
    def on_stock_order(self, order):
        print("order", order)

    def on_stock_trade(self, trade):
        print("trade", trade)

    def on_order_error(self, error):
        print("order error", error)


account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
trader = XtQuantTrader("", callback=Callback(), account=account)
trader.start()
trader.subscribe(account)
trader.run_forever()
```

## Illustrative Stock Order

```python
from cfquant import xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
trader = XtQuantTrader("", account=account)
trader.start()

order_id = trader.order_stock(
    account,
    "000001.SZ",
    xtconstant.STOCK_BUY,
    100,
    xtconstant.FIX_PRICE,
    10.0,
    strategy_name="demo_strategy",
    order_remark="demo_order",
)
print(order_id)
```

Before adapting this to production, the user should explicitly confirm account, side, code, volume, price, and trading environment.

## Illustrative Futures Order

```python
from cfquant import xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("YOUR_FUTURE_ACCOUNT_ID", "FUTURE")
trader = XtQuantTrader("", account=account)
trader.start()

order_id = trader.order_stock(
    account,
    "IF2601.IF",
    xtconstant.FUTURE_OPEN_LONG,
    1,
    xtconstant.FIX_PRICE,
    4200.0,
    strategy_name="demo_future",
    order_remark="demo_future_order",
)
print(order_id)
```

## Illustrative Stock Option Order

```python
from cfquant import xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("YOUR_OPTION_ACCOUNT_ID", "STOCK_OPTION")
trader = XtQuantTrader("", account=account)
trader.start()

order_id = trader.order_stock(
    account,
    "10000001.SH",
    xtconstant.STOCK_OPTION_BUY_OPEN,
    1,
    xtconstant.FIX_PRICE,
    0.100,
    strategy_name="demo_option",
    order_remark="demo_option_order",
)
print(order_id)
```

For stock-option accounts, callers keep using MiniQMT `STOCK_OPTION_*` constants. The bridge maps them to the big-QMT ETF-option `passorder` opTypes.

## Query Market Data

```python
from cfquant import xtdata

data = xtdata.get_market_data(
    field_list=["open", "high", "low", "close", "volume"],
    stock_list=["000001.SZ"],
    period="1d",
    start_time="20240101",
    end_time="20241231",
    count=-1,
    dividend_type="none",
    fill_data=True,
)
print(data)
```

## Download Historical Data With Progress Callback

```python
from cfquant import xtdata


def on_progress(event):
    print("download progress", event)


result = xtdata.download_history_data2(
    ["000001.SZ", "600000.SH"],
    period="1d",
    start_time="20240101",
    end_time="20241231",
    callback=on_progress,
)
print(result)
```

## Query Financial Data

```python
from cfquant import xtdata

result = xtdata.get_financial_data(
    ["ASHAREBALANCESHEET.fix_assets"],
    ["000001.SZ"],
    start_time="20240101",
    end_time="20241231",
    report_type="announce_time",
)
print(result)
```

For financial download questions, explain that public docs require financial data to be downloaded first through QMT client data management; `cfquant` validates/preloads already-downloaded data rather than triggering a guaranteed script-side download.

## HTTP Tick Request

```powershell
$body = @{
  code_list = @("000001.SZ", "600000.SH")
  channel = "trade"
  timeout = 12
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/api/data/full-tick" `
  -ContentType "application/json" `
  -Body $body
```

## HTTP Account Query

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/api/account?account_id=YOUR_ACCOUNT_ID&account_type=STOCK&sections=asset&force=1&subscribe=0&timeout=12"
```

## HTTP Illustrative Order

```powershell
$body = @{
  account_id = "YOUR_ACCOUNT_ID"
  account_type = "STOCK"
  side = "buy"
  stock_code = "000001.SZ"
  price = 10.0
  volume = 100
  confirm_text = "BUY 000001.SZ 100 @ 10.000"
  timeout = 12
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/api/order" `
  -ContentType "application/json" `
  -Body $body
```

## HTTP Illustrative Futures Order

```powershell
$body = @{
  account_id = "YOUR_FUTURE_ACCOUNT_ID"
  account_type = "FUTURE"
  order_action = "future_open_long"
  stock_code = "IF2601.IF"
  price_type = 11
  price = 4200.0
  volume = 1
  confirm_text = "FUTURE_OPEN_LONG IF2601.IF 1 @ 4200.000"
  timeout = 12
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/api/future/order" `
  -ContentType "application/json" `
  -Body $body
```

## HTTP Illustrative Stock Option Order

```powershell
$body = @{
  account_id = "YOUR_OPTION_ACCOUNT_ID"
  account_type = "STOCK_OPTION"
  order_action = "stock_option_buy_open"
  stock_code = "10000001.SH"
  price_type = 11
  price = 0.1
  volume = 1
  confirm_text = "STOCK_OPTION_BUY_OPEN 10000001.SH 1 @ 0.100"
  timeout = 12
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/api/stock-option/order" `
  -ContentType "application/json" `
  -Body $body
```

## MiniQMT Migration Rewrite

Before:

```python
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
```

After:

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
```

Migration advice:

- Keep strategy-level `strategy_id` or client order id in the user's own system.
- Write attribution fields into `strategy_name` or `order_remark`.
- Validate query return fields against the user's actual QMT/broker environment before removing old compatibility code.
