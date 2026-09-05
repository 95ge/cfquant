# Compatibility And Boundaries

This reference captures how public docs classify API support and where `cfquant` intentionally differs from MiniQMT/`xtquant`.

## Status Terms

Use these terms consistently:

| Term | Meaning |
| --- | --- |
| `已实现` | External entry, bridge dispatch, and big-QMT callable call chain are wired. |
| `部分实现` / `部分平替` | Entry exists, but Web entry, return shape, signature precision, or real QMT version compatibility is still incomplete or needs verification. |
| `条件可实现` / `兼容入口` | Entry exists or can be forwarded only when the user's big-QMT version, broker environment, permissions, or strategy context exposes the needed callable. |
| `不能实现/不应实现` | Big-QMT strategy environment lacks equivalent ability, or the capability belongs to MiniQMT client/server/local-file management and should not be on the main bridge path. |

## Big-QMT Bridge Boundary

Say:

> `cfquant` wraps capabilities exposed by the running big-QMT strategy environment and provides xtquant-like external Python and Web access.

Do not say:

> `cfquant` fully replaces all MiniQMT local client behavior.

The public docs are explicit that the bridge should not become a MiniQMT SDK proxy by importing `xtquant.xtdata` as a fallback.

## Fully Supported Main Chain

Public docs mark these as the current main chain:

- Bridge status and health.
- Transport mode query/switch.
- PipeHub status/start/stop for general mode.
- Multi-account routing through Web binding.
- Stock account subscribe/unsubscribe.
- Asset, positions, orders, and trades query.
- Ordinary stock, credit, futures, futures-option, and stock-option order/cancel, including async response event forwarding.
- Trade callback forwarding.
- Credit order actions plus credit query/probe entries, subject to broker/QMT callable availability for the read-only special queries.
- Real-time tick/full-push snapshot.
- Market data and extended market data.
- Local data query with limited `data_dir` semantics.
- Single quote subscription, whole quote subscription, unsubscribe, latest quote events, quote WebSocket.
- Instrument detail and sector constituent query.
- Trading dates, security basic attributes, contract expiry/multiplier, index weight/turnover, ETF, option, ST, index, factor, and financial data read.
- Historical data download and progress event forwarding.
- Financial data local validation/preload compatibility entry.

Supported order account types in the public docs:

- `STOCK`: ordinary stock buy/sell.
- `CREDIT`: collateral buy/sell, margin buy, short sell, cash/security repayment, and special credit variants.
- `FUTURE`: MiniQMT `FUTURE_*` constants 0-22.
- `FUTURE_OPTION`: futures-style actions plus `OPTION_FUTURE_OPTION_EXERCISE=100`.
- `STOCK_OPTION`: MiniQMT `STOCK_OPTION_*` constants 48-57, mapped by the bridge to big-QMT ETF option opTypes 50-59.

## Partial Or Follow-Up Areas

The public docs call out these weak spots:

- `get_local_data` retains `data_dir` as a compatibility parameter but does not fully reproduce MiniQMT local directory semantics.
- `get_stock_list_in_sector` keeps common parameters; `real_timetag` and other original details are not fully exposed in public docs.
- Web batch historical download endpoint is listed as a possible future addition.
- Script-triggered true financial data download is not guaranteed because big-QMT official scripts do not expose a matching callable.
- Some edge `xtdata` methods are forwarded with `*args/**kwargs`; exact signatures are not fully fixed in the public docs.
- `cancel_order_stock_sysid` needs real-QMT verification across versions.
- Many `xttrader` compatibility entries forward to same-name/candidate callables; actual availability depends on QMT.
- Non-stock business return models such as credit, bank, SMT, transfer, and export can be raw QMT results rather than fully wrapped native `xtquant` objects.
- Some async entries call the synchronous result path then invoke callback, so they are not equivalent to a native async queue.

## Not Recommended Or Out Of Scope

Do not recommend putting these on the `cfquant` main bridge path:

- MiniQMT quote server connection management such as `connect`, `disconnect`, and `reconnect` under `xtdata`.
- MiniQMT quote server status/config watchers.
- MiniQMT local data directory control, including `get_data_dir` and mutable `xtdata.data_dir` semantics.
- Local file helpers such as `read_feather` and `write_feather`.
- Heavy backtest reads, repeated whole-market local file scans, or using the bridge as a data warehouse.
- Any big-QMT API that is not exposed by `ContextInfo`, `ContextInfo.context`, or the QMT strategy script globals.

Use `cfquant.status`, Web status pages, local databases, or dedicated file tools as alternatives where appropriate.

## Credit Account Boundary

Public docs document credit account order, query, and probe support. Order opType mapping is implemented in the bridge. Read-only special query capability still depends on broker QMT exposure.

Supported query action names for Web-facing discussion:

- `detail`
- `subjects`
- `slo_code`
- `assure`
- `compacts`

Credit probe is read-only and checks asset, positions, orders, trades, and credit special queries. It should not trigger trading orders.

## Derivative Trading Boundary

Futures, futures-option, and stock-option orders are implemented through the same MiniQMT-compatible `order_stock` surface and big-QMT `passorder` bridge. Public docs mark the routing, input parameters, order actions, return action fields, callback field forwarding, and Web endpoints as implemented.

Do not claim that a user's account can actually trade a derivative contract unless their broker QMT login has the corresponding account, permission, product, and contract available. Real order acceptance, rejection codes, and some exchange-specific details still come from the broker/QMT environment.

## Answer Patterns

When a user asks "Can cfquant do X?":

- If X is in the implemented main chain, say it is implemented and mention the entrypoint.
- If X is in conditional groups, say it has a compatibility/conditional entry and depends on the user's QMT callable availability.
- If X is a MiniQMT client/local-file/server-management behavior, say it is outside the big-QMT bridge scope and suggest the documented alternative.
- If X is not in this skill, say the published public docs do not cover it.

When a user asks for exact signatures for conditional edge APIs, do not invent them. Say those public docs describe conditional same-name forwarding and exact signature validation remains a follow-up item.
