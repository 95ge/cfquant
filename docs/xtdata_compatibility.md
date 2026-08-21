# xtquant.xtdata 平替追踪

更新时间：2026-08-13

## 总体结论

- 原版 `xtquant.xtdata` 当前检测到 138 个公开函数。
- `cfquant.xtdata` 当前采用三层策略：核心能力实装、边缘能力同名条件转发、MiniQMT 客户端/本地文件语义不放进 QMT 桥接主链路。
- 当前已经覆盖行情查询、订阅、历史下载、财务数据读取、基础资料、交易日历、ETF/期权/因子等常用能力。
- 交易时段、板块维护、公式、L2、表格数据和下载类补充接口已补同名条件入口；只有当前运行的 QMT 环境暴露对应 callable 时才可用。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| 已平替 | 已有同名函数，并通过普通 QMT、极速交易端或 ctypes 通用版桥接到实际能力。 |
| 部分平替 | 已有入口，但签名或返回结构与原版仍存在差异。 |
| Web 已开放 | Web 接口页面已经提供对应 HTTP/WebSocket 调试入口。 |
| 未平替 | 原版有该类能力，cfquant 当前还没有同名封装。 |

## 已平替接口

| 接口 | 当前实现 |
| --- | --- |
| `get_market_data` | 查询行情数据，数据查询默认极速交易端优先，失败或离线时回退普通 QMT。 |
| `get_market_data_ex` | 查询扩展行情数据，数据查询默认极速交易端优先，失败或离线时回退普通 QMT。 |
| `get_full_tick` | 查询实时 tick / 全推快照。 |
| `get_local_data` | 已接入本机 QMT callable。`data_dir` 作为兼容参数保留，但不真正接管本地目录。 |
| `subscribe_quote` | 订阅单只证券行情，回调通过桥接事件转发。 |
| `subscribe_quote2` | 订阅单只证券行情，支持 `dividend_type` 参数。 |
| `subscribe_whole_quote` | 订阅全推行情。当前 Web 侧限制为普通 QMT，同一时间只允许一个外部全推订阅。 |
| `unsubscribe_quote` | 取消行情订阅并移除本地 callback。 |
| `download_history_data` | 下载单只证券历史行情数据。 |
| `download_history_data2` | 批量下载历史行情数据，支持 `callback_event` 事件转发。 |
| `get_instrument_detail` | 查询证券合约详情。 |
| `get_stock_list_in_sector` | 查询板块成分。 |
| `get_trading_dates` | 查询交易日历。 |
| `is_stock` / `is_fund` / `is_future` | 证券类型判断。 |
| `get_stock_type` / `get_stock_name` / `get_open_date` | 基础资料查询。 |
| `get_contract_expire_date` / `get_contract_multiplier` | 合约到期日和乘数查询。 |
| `get_weight_in_index` / `get_turnover_rate` | 指数权重和换手率查询。 |
| `get_ETF_list` / `get_etf_list` | ETF 列表查询。 |
| `get_option_detail_data` / `get_option_list` / `get_option_undl` / `get_option_undl_data` | 期权详情、列表和标的查询。 |
| `get_his_st_data` / `get_his_index_data` | 历史 ST 状态和历史指数权重查询。 |
| `get_factor_data` | 因子数据查询。 |
| `get_financial_data` / `get_financial_data_ori` / `get_raw_financial_data` | 财务数据查询。 |
| `download_financial_data` / `download_financial_data2` | 兼容入口。大 QMT 官网脚本侧未提供财务下载函数，当前降级为读取/校验本地已下载财务数据。 |
| `get_client` | 获取 cfquant 客户端。 |
| `run` | 启动客户端并保持运行。 |
| `configure` | 配置 cfquant 客户端连接参数。 |

## 部分平替接口

| 接口 | 当前差异 |
| --- | --- |
| `get_local_data` | 已接入，但仍保留兼容参数写法，和原版 `data_dir` 的本地目录语义不完全一致。 |
| `get_stock_list_in_sector` | 当前支持常用参数，原版还有 `real_timetag` 等参数。 |
| 交易日历/交易时段 | `get_trading_calendar`、`get_trading_period`、`get_kline_trading_period`、`get_all_trading_periods`、`get_period_list` 已补同名条件入口；实际依赖 QMT 是否暴露对应 callable。 |
| 板块维护 | `create_sector`、`add_sector`、`remove_sector`、`reset_sector`、`remove_stock_from_sector` 已补同名条件入口；实际依赖 QMT 权限和 callable。 |
| 公式系统 | `create_formula`、`call_formula`、`subscribe_formula`、`unsubscribe_formula`、`get_formula_result` 已补同名条件入口；订阅 callback 会通过 cfquant 事件通道转发。 |
| L2 行情 | `get_l2_quote`、`get_l2_order`、`get_l2_transaction`、`subscribe_l2thousand`、`get_l2thousand_queue` 已补同名条件入口；需要券商 QMT 环境本身支持 L2 能力。 |
| 表格/外部数据 | `get_tabular_data`、`download_tabular_data`、`push_custom_data` 已补同名条件入口；返回结构以 QMT 原 callable 为准。 |
| 下载类补充 | `download_sector_data`、`download_index_weight`、`download_history_contracts`、`download_holiday_data`、`download_etf_info`、`download_cb_data`、`download_his_st_data`、`download_metatable_data` 已补同名条件入口。 |

## Web 已开放的数据接口

| Web 接口 | 对应 xtdata 能力 |
| --- | --- |
| `POST /api/data/full-tick` | `get_full_tick` |
| `POST /api/data/market` | `get_market_data` |
| `POST /api/data/market-ex` | `get_market_data_ex` |
| `POST /api/data/instrument` | `get_instrument_detail` |
| `POST /api/data/sector` | `get_stock_list_in_sector` |
| `POST /api/data/history/download` | `download_history_data` |
| `POST /api/data/financial` | `get_financial_data` / `get_raw_financial_data` |
| `POST /api/data/financial/download` | 财务本地数据校验/预加载读取；真实财务下载需先在 QMT 客户端“数据管理 - 财务数据下载”中完成。 |
| `POST /api/quotes/whole/subscribe` | `subscribe_whole_quote` |
| `POST /api/quotes/subscribe` | `subscribe_quote` / `subscribe_quote2` |
| `POST /api/quotes/unsubscribe` | `unsubscribe_quote` |
| `GET /api/quotes/latest` / `WS /ws/quotes` | 读取或接收行情推送事件。 |

## 不建议强行平替的大类

| 大类 | 代表接口 |
| --- | --- |
| 行情服务器管理 | `connect`, `disconnect`, `reconnect`, `get_quote_server_status`, `watch_quote_server_status`, `get_quote_server_config` |
| 本地数据目录/文件工具 | `get_data_dir`, `read_feather`, `write_feather` |

这些接口属于 MiniQMT 客户端连接状态或本地文件工具语义，不等价于大 QMT 策略桥接。当前建议用 `cfquant.status`、Web 状态页和独立本地文件工具替代。

## 当前验证记录

```powershell
@'
import inspect
import xtquant.xtdata as native
import cfquant.xtdata as cf
native_funcs = {name: str(inspect.signature(obj)) for name, obj in inspect.getmembers(native, inspect.isfunction) if not name.startswith('_')}
cf_funcs = {name: str(inspect.signature(obj)) for name, obj in inspect.getmembers(cf, inspect.isfunction) if not name.startswith('_')}
print(len(native_funcs), len(cf_funcs), len(native_funcs.keys() & cf_funcs.keys()))
print(sorted(cf_funcs.keys() - native_funcs.keys()))
'@ | python -
```

结果：原版 138 个公开函数，`cfquant` 40 个公开函数，其中 24 个与原版同名；额外提供 16 个辅助/别名函数。
