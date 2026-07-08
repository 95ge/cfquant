# xtquant.xtdata 平替追踪

更新时间：2026-07-08

## 总体结论

- 原版 `xtquant.xtdata` 当前检测到 138 个公开函数。
- `cfquant.cfquant.xtdata` 当前暴露 15 个公开函数，其中 14 个与原版同名，额外提供 `configure()` 用于配置 cfquant 客户端。
- 当前已覆盖核心行情查询、单股/全推订阅、取消订阅、历史数据下载、合约详情、板块成分和运行保持。
- 当前没有做到 `xtdata` 全量平替；L2、ETF、期权、可转债、交易日历、板块维护、公式、外部数据读写、行情服务器管理等大量原版函数还未补齐。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| 已平替 | 已有同名函数，并通过普通 QMT 或极速交易端桥接到实际能力。 |
| 部分平替 | 已有入口，但签名或返回结构与原版仍存在差异。 |
| Web 已开放 | Web 接口页面已经提供对应 HTTP/WebSocket 调试入口。 |
| 未平替 | 原版有该类能力，cfquant 当前还没有同名封装。 |

## 已平替接口

| 接口 | 当前实现 |
| --- | --- |
| `get_market_data` | 查询行情数据。Web 数据查询默认极速交易端优先，失败或离线时回退普通 QMT。 |
| `get_market_data_ex` | 查询扩展行情数据。Web 数据查询默认极速交易端优先，失败或离线时回退普通 QMT。 |
| `get_full_tick` | 查询实时 tick/全推快照。 |
| `subscribe_quote` | 订阅单只证券行情，回调通过 LTtx 事件转发。 |
| `subscribe_quote2` | 订阅单只证券行情，支持 `dividend_type` 参数。 |
| `subscribe_whole_quote` | 订阅全推行情。当前 Web 侧限制为普通 QMT，同一时间只允许一个全推外部订阅。 |
| `unsubscribe_quote` | 取消行情订阅并移除本地 callback。 |
| `download_history_data` | 下载单只证券历史行情数据。 |
| `download_history_data2` | 批量下载历史行情数据，支持 callback 事件转发。 |
| `get_instrument_detail` | 查询证券合约详情。 |
| `get_client` | 获取 cfquant LTtx 客户端。 |
| `run` | 启动客户端并保持运行。 |

## 部分平替接口

| 接口 | 当前差异 |
| --- | --- |
| `get_local_data` | 当前映射到 `get_market_data_ex`，原版签名里有 `data_dir` 参数，cfquant 当前未暴露该参数。 |
| `get_stock_list_in_sector` | 当前支持 `sector_name`，原版还有 `real_timetag` 参数，cfquant 当前未暴露该参数。 |

## Web 已开放的数据接口

| Web 接口 | 对应 xtdata 能力 |
| --- | --- |
| `POST /api/data/full-tick` | `get_full_tick` |
| `POST /api/data/market` | `get_market_data` |
| `POST /api/data/market-ex` | `get_market_data_ex` |
| `POST /api/data/instrument` | `get_instrument_detail` |
| `POST /api/data/sector` | `get_stock_list_in_sector` |
| `POST /api/data/history/download` | `download_history_data` |
| `POST /api/data/financial` | 桥接端直接调用 QMT `get_financial_data` / `get_raw_financial_data`，`cfquant.cfquant.xtdata` 尚未提供同名 Python 封装。 |
| `POST /api/data/financial/download` | 桥接端直接调用 QMT `download_financial_data` / `download_financial_data2`，`cfquant.cfquant.xtdata` 尚未提供同名 Python 封装。 |
| `POST /api/quotes/whole/subscribe` | `subscribe_whole_quote` |
| `POST /api/quotes/subscribe` | `subscribe_quote` / `subscribe_quote2` |
| `POST /api/quotes/unsubscribe` | `unsubscribe_quote` |
| `GET /api/quotes/latest` / `WS /ws/quotes` | 读取或接收行情推送事件。 |

## 未平替大类

| 大类 | 代表接口 |
| --- | --- |
| 财务数据 Python 封装 | `get_financial_data`, `get_financial_data_ori`, `download_financial_data`, `download_financial_data2` |
| 交易日历/交易时段 | `get_trading_dates`, `get_trading_calendar`, `get_trading_period`, `get_kline_trading_period` |
| 板块维护 | `create_sector`, `add_sector`, `remove_sector`, `reset_sector`, `remove_stock_from_sector` |
| 公式系统 | `create_formula`, `call_formula`, `subscribe_formula`, `unsubscribe_formula`, `get_formula_result` |
| L2 行情 | `get_l2_quote`, `get_l2_order`, `get_l2_transaction`, `subscribe_l2thousand`, `get_l2thousand_queue` |
| ETF/期权/可转债 | `get_etf_info`, `get_option_list`, `get_option_detail_data`, `bnd_get_*` |
| 行情服务器管理 | `connect`, `disconnect`, `reconnect`, `get_quote_server_status`, `watch_quote_server_status` |
| 外部数据/表格数据 | `get_tabular_data`, `download_tabular_data`, `read_feather`, `write_feather`, `push_custom_data` |

## 当前验证记录

```powershell
@'
import inspect
import xtquant.xtdata as native
import cfquant.cfquant.xtdata as cf
native_funcs = {name: str(inspect.signature(obj)) for name, obj in inspect.getmembers(native, inspect.isfunction) if not name.startswith('_')}
cf_funcs = {name: str(inspect.signature(obj)) for name, obj in inspect.getmembers(cf, inspect.isfunction) if not name.startswith('_')}
print(len(native_funcs), len(cf_funcs), len(native_funcs.keys() & cf_funcs.keys()))
print(sorted(native_funcs.keys() - cf_funcs.keys()))
'@ | python -
```

结果：原版 138 个公开函数，`cfquant` 15 个公开函数，其中 14 个与原版同名；原版未覆盖 124 个公开函数。
