# cfquant 大 QMT 函数封装能力清单

更新时间：2026-09-05

## 定位说明

cfquant 的本质是把外部程序、Web 控制台和大 QMT 策略环境连起来，封装大 QMT 里已经存在的 `ContextInfo` 方法或策略脚本全局函数。

当前桥接端查找 callable 的来源是：

- QMT 策略脚本全局函数，例如 `passorder`、`cancel`、`get_trade_detail_data`
- `ContextInfo` 暴露的方法
- `ContextInfo.context` 暴露的方法

当前主链路不再兜底导入 MiniQMT `xtquant.xtdata` 来补能力。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| 已实现 | 外部入口、桥接分发和大 QMT callable 调用链已经打通。 |
| 部分实现 | 已有入口，但 Web 入口、返回结构或真实 QMT 版本兼容性还不完整。 |
| 条件可实现 | 只有用户所在大 QMT 版本或策略环境暴露对应 callable 时才能封装。 |
| 不能实现/不应实现 | 大 QMT 策略环境没有对应能力，或该能力属于 MiniQMT 客户端/行情服务器管理，不应放进主链路。 |

## 已实现

### 本地服务与通信模式

| 能力 | 外部入口 | 说明 |
| --- | --- | --- |
| 桥接连通检测 | `cfquant.ping` / `GET /api/status` | 普通桥、极速桥都支持。 |
| 桥接状态查询 | `cfquant.status` / `GET /api/status` | 返回 context、tx、通道、队列等状态。 |
| 通信模式切换 | `GET /api/transport` / `POST /api/transport` | 支持通用模式 `ctypes` 和高级模式 `lttx`；高级模式要求普通 QMT、极速交易端同时在线。 |
| PipeHub 状态 | `GET /api/pipe-hub` / `POST /api/pipe-hub/start` / `POST /api/pipe-hub/stop` | 通用模式使用；负责单文件 ctypes 双通道的请求、响应和回调转发。 |
| 多账号路由 | Web 账号绑定 / `account_key` | 同一 QMT 的多个普通、信用、期货、期货期权、股票期权账户共用一个 `bridge_id`，请求按 `bridge_id:account_type:account_id` 路由；多个 QMT 使用不同 `bridge_id` 和对应频道。 |
| QMT 日志语言设置 | `cfquant.set_log_language` | 用于桥接脚本日志中英文切换。 |
| QMT userdata/log 清理 | `cfquant.cleanup_qmt_logs` | 清理 QMT 用户日志目录的过期日志。 |

### 交易

| 能力 | 外部入口 | 大 QMT 侧依赖 | 当前状态 |
| --- | --- | --- | --- |
| 账号订阅 | `xttrader.subscribe` | `ContextInfo.set_account` | 已实现。 |
| 账号取消订阅 | `xttrader.unsubscribe` | 账号路由状态 | 已实现。 |
| 查资金 | `query_stock_asset` / `/api/account?sections=asset` | `get_trade_detail_data(account, type, "account")` | 已实现。 |
| 查持仓 | `query_stock_positions` / `/api/account?sections=positions` | `get_trade_detail_data(..., "position")` | 已实现。 |
| 查委托 | `query_stock_orders` / `/api/account?sections=orders` | `get_trade_detail_data(..., "order")` | 已实现。 |
| 查成交 | `query_stock_trades` / `/api/account?sections=trades` | `get_trade_detail_data(..., "deal")` | 已实现。 |
| 股票下单 | `order_stock` / `POST /api/order` | `passorder` | 已实现；通用模式走 ctypes 交易通道，高级模式默认走极速交易端。 |
| 批量下单 | `order_stock_batch` / `POST /api/orders/batch` | `passorder` | 已实现，逐笔提交。 |
| 信用委托 | `order_stock` / `POST /api/credit/order` / `POST /api/credit/orders/batch` / `GET /api/credit/actions` | `passorder` | 已实现；支持担保品买卖、融资买入、融券卖出、买券还券、直接还券、卖券还款、直接还款及专项动作，并把 MiniQMT 信用常量映射到大 QMT opType。 |
| 期货/期货期权委托 | `order_stock` / `POST /api/future/order` / `POST /api/future-option/order` / 对应批量接口 | `passorder` | 已实现；输入保持 MiniQMT `FUTURE_*` 常量语义，期货期权额外支持 `OPTION_FUTURE_OPTION_EXERCISE=100`。 |
| 股票期权委托 | `order_stock` / `POST /api/stock-option/order` / `POST /api/stock-option/orders/batch` | `passorder` | 已实现；输入保持 MiniQMT `STOCK_OPTION_*` 常量 48-57，桥接到大 QMT ETF 期权 opType 50-59。 |
| 股票撤单 | `cancel_order_stock` / `POST /api/cancel` | `cancel` | 已实现。 |
| 异步下单响应 | `order_stock_async` | `passorder` + 本地事件转发 | 已实现为桥接事件。 |
| 异步撤单响应 | `cancel_order_stock_async` | `cancel` + 本地事件转发 | 已实现为桥接事件。 |
| 交易回调转发 | WebSocket `/ws/callbacks` | QMT 策略回调函数 | 已实现资金、持仓、委托、成交、错误等回调转发。 |
| 信用专项查询 | `query_credit_detail` / `query_credit_subjects` / `query_credit_slo_code` / `query_credit_assure` / `query_stk_compacts` / `POST /api/credit/query` | QMT 信用账户 callable 候选 | 已实现；实际可用性取决于当前券商 QMT 是否暴露对应 callable。 |
| 信用能力探测 | `POST /api/credit/probe` | 只读调用资产、持仓、委托、成交和信用专项查询 | 已实现；用于部署后确认当前信用账户能力，不触发交易委托。 |

### 行情与基础数据

| 能力 | 外部入口 | 大 QMT 侧依赖 | 当前状态 |
| --- | --- | --- | --- |
| 实时 tick/全推快照 | `xtdata.get_full_tick` / `/api/data/full-tick` | `ContextInfo.get_full_tick` | 已实现。 |
| 行情查询 | `xtdata.get_market_data` / `/api/data/market` | `get_market_data` 或 `get_market_data_ex` | 已实现。 |
| 扩展行情查询 | `xtdata.get_market_data_ex` / `/api/data/market-ex` | `get_market_data_ex` | 已实现。 |
| 本地数据查询 | `xtdata.get_local_data` | `get_local_data` | 已实现，但 `data_dir` 仅保留兼容参数，未真正接管本地目录。 |
| 单股行情订阅 | `xtdata.subscribe_quote` / `/api/quotes/subscribe` | 普通桥内部全推订阅与过滤 | 已实现。 |
| 全推行情订阅 | `xtdata.subscribe_whole_quote` / `/api/quotes/whole/subscribe` | `ContextInfo.subscribe_whole_quote` | 已实现；通用模式走 ctypes 单文件桥，高级模式走普通 QMT 桥。 |
| 取消行情订阅 | `xtdata.unsubscribe_quote` / `/api/quotes/unsubscribe` | 普通桥订阅状态 | 已实现。 |
| 证券合约详情 | `xtdata.get_instrument_detail` / `/api/data/instrument` | `get_instrument_detail` | 已实现。 |
| 板块成分 | `xtdata.get_stock_list_in_sector` / `/api/data/sector` | `ContextInfo.get_stock_list_in_sector` | 已实现，但参数集仍较简化。 |
| 交易日历 | `xtdata.get_trading_dates` | `ContextInfo.get_trading_dates(...)` | 已实现。 |
| 证券类型/基础属性 | `xtdata.is_stock`、`is_fund`、`is_future`、`get_stock_type`、`get_stock_name`、`get_open_date` | 大 QMT callable | 已实现。 |
| 合约到期日/乘数 | `xtdata.get_contract_expire_date`、`get_contract_multiplier` | 大 QMT callable | 已实现。 |
| 指数成分权重/换手率 | `xtdata.get_weight_in_index`、`get_turnover_rate` | 大 QMT callable | 已实现。 |
| ETF / 期权 / ST / 因子 | `xtdata.get_ETF_list`、`get_etf_list`、`get_option_detail_data`、`get_option_list`、`get_option_undl`、`get_option_undl_data`、`get_his_st_data`、`get_his_index_data`、`get_factor_data` | 大 QMT callable | 已实现。 |

### 数据下载

| 能力 | 外部入口 | 大 QMT 侧依赖 | 当前状态 |
| --- | --- | --- | --- |
| 单证券历史行情下载 | `xtdata.download_history_data` / `/api/data/history/download` | `download_history_data` 或 `down_history_data` | 已实现；通用模式走 ctypes 普通通道，高级模式固定普通 QMT。 |
| 批量历史行情下载 | `xtdata.download_history_data2` | `download_history_data2` 或 `down_history_data2` | 已实现，支持 `callback_event` 事件转发。 |
| 财务数据查询 | `xtdata.get_financial_data` / `get_financial_data_ori` / `get_raw_financial_data` / `/api/data/financial` | `get_financial_data` 或 `get_raw_financial_data` | 已实现。 |
| 财务本地校验 | `xtdata.download_financial_data` / `download_financial_data2` / `/api/data/financial/download` | `get_financial_data` 或 `get_raw_financial_data` | 大 QMT 官网脚本侧未提供财务下载函数；兼容入口降级为读取/校验本地已下载财务数据，并提示用户先在 QMT 客户端“数据管理 - 财务数据下载”中下载。 |
| 交易时段补充 | `get_trading_calendar` / `get_trading_period` / `get_kline_trading_period` / `get_all_trading_periods` / `get_period_list` | 同名 QMT callable | 条件实现；当前 QMT 暴露对应 callable 时直接转发。 |
| 板块维护 | `create_sector` / `add_sector` / `remove_sector` / `reset_sector` / `remove_stock_from_sector` | 同名 QMT callable | 条件实现；实际取决于 QMT 策略环境权限和 callable。 |
| 公式系统 | `create_formula` / `call_formula` / `subscribe_formula` / `unsubscribe_formula` / `get_formula_result` | 同名 QMT callable | 条件实现；订阅 callback 通过 cfquant 事件通道转发。 |
| L2 行情 | `get_l2_quote` / `get_l2_order` / `get_l2_transaction` / `subscribe_l2thousand` / `get_l2thousand_queue` | 同名 QMT callable | 条件实现；需要券商 QMT 本身支持 L2。 |
| 下载类补充 | `download_sector_data` / `download_index_weight` / `download_history_contracts` / `download_holiday_data` / `download_etf_info` / `download_cb_data` / `download_his_st_data` / `download_metatable_data` / `download_tabular_data` | 同名或 `down_*` QMT callable | 条件实现；返回结构以 QMT callable 为准。 |

## 部分实现或待补强

| 能力 | 当前情况 | 后续建议 |
| --- | --- | --- |
| `get_local_data` 的原版目录参数 | 兼容参数 `data_dir` 还保留在 Python 层，但桥接层不真正接管本地目录。 | 如果后续要严格复刻原版，再补本地数据目录语义。 |
| `get_stock_list_in_sector` 的原版参数 | 当前只保留常用参数，`real_timetag` 还未完整暴露。 | 需要时补齐参数并按真实 QMT 返回验证。 |
| `download_history_data2` 的 Web 入口 | 底层桥接已能接收 `callback_event` 并转发事件；Web 单证券下载会优先走 `download_history_data2`。 | 如需页面批量下载，再增加 `/api/data/history/download-batch`。 |
| 财务数据脚本下载 | 官网未提供等价脚本 callable，当前不能保证由脚本触发真实下载。 | 保留 `/api/data/financial/download` 兼容入口，内部改为本地财务数据校验；真实下载仍由 QMT 客户端数据管理完成。 |
| 条件实现接口的签名精度 | 部分边缘接口目前通过 `*args/**kwargs` 同名转发，未逐一固化原版签名。 | 用真实 QMT 版本逐项验证后，再把高频接口升级为明确签名和 Web 表单。 |
| 系统编号撤单 | 当前复用 `cancel(order_id, account_id, account_type, context)`。 | 需要真实系统编号撤单验证不同 QMT 版本参数。 |
| 交易兼容入口 | `xttrader` 已补齐大量同名方法，但很多是候选 callable 转发。 | 用真实大 QMT 版本逐项确认 callable 名称和返回结构。 |

## 不应在主链路实现

| 能力 | 原因 | 处理建议 |
| --- | --- | --- |
| MiniQMT 行情服务器连接管理：`connect` / `disconnect` / `reconnect` | 这是 MiniQMT `xtquant.xtdata` 客户端连接控制，不属于大 QMT `ContextInfo` 函数封装。 | 不放入 cfquant 主链路。 |
| MiniQMT 行情服务器状态：`get_quote_server_status` / `watch_quote_server_status` / `get_quote_server_config` | 依赖 MiniQMT 客户端连接状态，不等价于大 QMT 桥接状态。 | 当前用 `cfquant.status` 表示桥接状态。 |
| MiniQMT 数据目录控制：`get_data_dir` / 修改 `xtdata.data_dir` | 属于 MiniQMT 本地数据路径语义，不应影响大 QMT 封装链路。 | 不作为主链路接口。 |
| 直接导入 `xtquant.xtdata` 作为兜底实现 | 会把 cfquant 从“大 QMT 函数封装”变成“MiniQMT SDK 代理”。 | 已从旧桥 `_get_callable` 移除该兜底。 |
| 大 QMT 未暴露且无等价 callable 的接口 | 桥接层没有真实可调用对象，无法保证行为。 | 返回明确未实现错误，并在文档中标记为条件可实现或不能实现。 |

## Web 接口开放状态

| Web 接口 | 状态 | 说明 |
| --- | --- | --- |
| `GET /api/status` | 已实现 | 桥接端状态。 |
| `GET /api/transport` / `POST /api/transport` | 已实现 | 通用模式和高级模式查看、切换；高级模式切换前检查双桥。 |
| `GET /api/pipe-hub` / `POST /api/pipe-hub/start` / `POST /api/pipe-hub/stop` | 已实现 | 通用模式 PipeHub 管理。 |
| `POST /api/data/full-tick` | 已实现 | 实时 tick/快照。 |
| `POST /api/data/market` | 已实现 | 行情数据。 |
| `POST /api/data/market-ex` | 已实现 | 扩展行情数据。 |
| `POST /api/data/instrument` | 已实现 | 合约详情。 |
| `POST /api/data/sector` | 已实现 | 板块成分。 |
| `POST /api/data/history/download` | 已实现 | 单证券历史下载，固定普通 QMT。 |
| `POST /api/data/history/download-batch` | 未实现 | 建议补，对应 `download_history_data2`。 |
| `POST /api/data/financial` | 已实现 | 财务查询。 |
| `POST /api/data/financial/download` | 已实现 | 财务本地数据校验/预加载读取，支持任务进度事件；真实财务下载需先在 QMT 客户端完成。 |
| `POST /api/quotes/whole/subscribe` | 已实现 | 全推订阅。 |
| `POST /api/quotes/subscribe` | 已实现 | 单股行情事件。 |
| `POST /api/quotes/unsubscribe` | 已实现 | 取消订阅。 |
| `GET /api/quotes/latest` / `WS /ws/quotes` | 已实现 | 行情事件读取/推送。 |
| `GET /api/account` | 已实现 | 资金、持仓、委托、成交。 |
| `POST /api/order` | 已实现 | 单笔下单。 |
| `POST /api/orders/batch` | 已实现 | 批量下单。 |
| `GET /api/order/actions` | 已实现 | 返回信用、期货、期货期权、股票期权委托动作和别名。 |
| `GET /api/credit/actions` | 已实现 | 返回信用查询动作、信用委托动作和别名。 |
| `POST /api/credit/order` | 已实现 | 信用账户单笔业务委托，确认文本使用 `CREDIT_* 代码 数量 @ 价格`。 |
| `POST /api/credit/orders/batch` | 已实现 | 信用账户批量业务委托；每行可单独携带 `credit_action`。 |
| `POST /api/future/order` / `POST /api/future/orders/batch` | 已实现 | 期货账户单笔/批量业务委托；每笔可携带 `order_action`。 |
| `POST /api/future-option/order` / `POST /api/future-option/orders/batch` | 已实现 | 期货期权账户单笔/批量业务委托；每笔可携带 `order_action`。 |
| `POST /api/stock-option/order` / `POST /api/stock-option/orders/batch` | 已实现 | 股票期权账户单笔/批量业务委托；MiniQMT order_type 自动映射到大 QMT opType。 |
| `POST /api/cancel` | 已实现 | 撤单。 |
| `GET /api/callbacks` / `WS /ws/callbacks` | 已实现 | 交易回调事件。 |

## 下一步建议

1. 用真实 QMT 版本继续校验 `get_local_data`、`get_stock_list_in_sector`、系统编号撤单等边缘签名。
2. 如果后续要把批量历史下载也做成网页动作，再补 `/api/data/history/download-batch`。
3. 通用模式作为默认部署入口；需要更低交易延迟时，再在网页中切换高级模式并同时部署普通 QMT、极速交易端双桥。
