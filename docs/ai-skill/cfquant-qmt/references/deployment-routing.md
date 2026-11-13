# Deployment And Routing

This reference summarizes the public docs for the single supported deployment mode, binding accounts, routing external Python calls, and migrating MiniQMT strategies.

## Project Positioning

`cfquant` converts the big-QMT strategy environment into a MiniQMT/`xtquant`-compatible bridge for external Python programs. It connects those programs, the local Web Console, and big QMT, wrapping `ContextInfo` methods or strategy-script global functions that already exist in the running QMT environment.

The bridge callable lookup boundary in the docs:

- QMT strategy script globals such as `passorder`, `cancel`, and `get_trade_detail_data`.
- Methods exposed by `ContextInfo`.
- Methods exposed by `ContextInfo.context`.

The main chain no longer falls back to importing MiniQMT `xtquant.xtdata` to fill missing capability.

## Runtime Mode

| Mode | QMT entry script | Current behavior |
| --- | --- | --- |
| Lite/extreme mode | `qmt_scripts/CFQUANT_LITE.py` | The only supported mode. After binding, the Web Console installs the QMT runtime, starts QMT, and deploys the self-contained entry script. |

Users do not choose between general and advanced modes. Complete the Web binding and wait for the extreme-mode channels to become online.

## First-Time Setup Flow

1. Deploy source package to a fixed directory, for example `D:\cfquant`.
2. Install dependencies and run `start_cfquant.bat`.
3. Open `http://127.0.0.1:8765/`.
4. Use the Web initialization wizard.
5. Bind account information in Web Console.
6. Wait for the Web Console to install the QMT runtime, start QMT, and deploy the extreme-mode entry script.
7. Validate status, asset, positions, orders, trades, and quote query through Web API debug or external Python.

For PyPI-only library usage, the Web Console still needs to complete account binding so it can install the QMT runtime and deploy the QMT-side entry script.

## Account Binding And Routing

Public docs define account routing around Web binding rather than MiniQMT `session_id`.

Important concepts:

- `account_id`: fund/account id.
- `account_type`: `STOCK`, `CREDIT`, `FUTURE`, `FUTURE_OPTION`, or `STOCK_OPTION`.
- `bridge_id`: internal QMT bridge id. Same QMT can host multiple account bindings; multiple QMT instances should use different `bridge_id` values.
- `account_key`: stable binding key generated/used by Web routing.
- `session_id`: compatibility argument only. If omitted or set to `0`, `cfquant` auto-assigns a positive integer for the trader instance. Do not treat it as the main route key in `cfquant`.

Multi-account guidance:

- Configure each real account in Web "binding" first.
- For multiple ordinary, credit, futures, futures-option, or stock-option accounts in one QMT, requests are routed by `bridge_id:account_type:account_id`.
- For multiple QMT terminals or brokers, assign different `bridge_id` values and load the matching entry script configuration in each QMT.
- External strategies should pass the real `StockAccount` and let Web auto routing choose the internal channel.

## Runtime Dependencies

Extreme mode requires the managed PipeHub and QMT loaded with the self-contained `CFQUANT_LITE.py` entry. The Web Console installs the QMT runtime, starts the client, and deploys this entry after binding.

External discovery:

- The local Web service defaults to keeping LTtx available for runtime registration.
- External `transport=auto` reads runtime registration and routes through Web when available.
- Directly probing the Web HTTP port is not recommended for external programs because users may change the port; LTtx registration is described as more stable.

## Migration Strategy From MiniQMT

The intended migration is backend replacement: keep the strategy's business logic and familiar `xtdata`/`XtQuantTrader` calls, install `cfquant` in the strategy interpreter, usually change the external import prefix from `xtquant` to `cfquant`, then bind the big-QMT account and load the matching bridge entry script. Do not rewrite the strategy around Web endpoints unless the user specifically needs an HTTP integration.

Start by listing the actual interfaces the existing strategy uses. Do not migrate by trying to replace the entire `xtquant` surface at once.

Recommended migration order:

1. Read-only queries: asset, positions, orders, trades.
2. Cancel and small test order flows. For derivatives, validate the exact account type and order action/order type mapping before production use.
3. Callback events for async order/cancel and trade report.
4. Real-time tick and quote subscription.
5. Multi-process same-account pressure testing.
6. Remove MiniQMT dependency and field compatibility branches only after production validation.

Public docs recommend splitting data paths:

```text
Backtest / batch analysis: local database, file cache, offline data service
Live trading / small real-time query: cfquant -> big QMT
```

Do not route heavy backtest data reads or high-frequency local file reads through the bridge as the main data path.

## Latency Validation

Do not promise a fixed latency target from docs alone. Measure in the user's real trading environment:

- `order_stock` / `order_stock_async`
- `cancel_order_stock` / `cancel_order_stock_async`
- `query_stock_asset`
- `query_stock_positions`
- `query_stock_orders`
- `query_stock_trades`
- `get_full_tick`

For latency tests, include the actual account class being deployed. `order_stock` covers ordinary stock, credit, futures, futures-option, and stock-option accounts, but exchange, broker gateway, and account permission differences can dominate measured latency.

Report at least min, p50, p95, max, timeout count, and recovery after QMT restart or disconnect.

## Common Troubleshooting Points

- Web account binding is missing or the wrong account type was selected.
- QMT entry script was not restarted after changing `bridge_id`, account binding, or QMT directory.
- Multiple QMTs all report `default`, meaning the entry script did not load its intended bridge config.
- The user assumed MiniQMT return fields are identical to `cfquant` bridge objects.
- Batch historical/backtest reads were placed on the bridge path, causing migration slowdown.
