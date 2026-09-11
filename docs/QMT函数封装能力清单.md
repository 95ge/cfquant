# cfquant 大 QMT 函数封装能力清单

更新时间：2026-09-08

## 定位说明

cfquant 的本质是把外部程序、Web 控制台和大 QMT 策略环境连起来，封装大 QMT 里已经存在的 `ContextInfo` 方法或策略脚本全局函数。

当前桥接端查找 callable 的来源是：

- QMT 策略脚本全局函数，例如 `passorder`、`cancel`、`get_trade_detail_data`
- `ContextInfo` 暴露的方法
- `ContextInfo.context` 暴露的方法

当前主链路不再兜底导入 MiniQMT `xtquant.xtdata` 来补能力。文档里提到的“原生 xtquant”能力，如果大 QMT 内置策略环境没有暴露同名 callable，就只能标记为条件可实现或不应实现。

## 本次比对结论

1. 高级模式下，低延迟只读 `xtdata` 请求默认优先走极速交易桥，例如 `get_full_tick`、`get_market_data`、`get_instrument_detail`；如果交易桥缺少 callable，会在同一轮回退到普通桥。
2. `xtdata.get_instrument_detail` 已增加降级实现：优先调用 QMT 原生 `get_instrument_detail`，缺失时用 `get_stock_name`、`get_stock_type`、`get_open_date` 等基础 callable 合成部分字段。
3. `xtdata.download_holiday_data` 不能按“大 QMT 内置策略函数”承诺可用。ThinkTrader 内置文档对交易日历的说明是：内置环境需要通过界面端“节假日数据 - 下载”，原生 xtquant 才调用 `xtdata.download_holiday_data()`。
4. ETF、期权、ST、指数历史、因子、L2、公式、板块维护等入口，cfquant 侧已有分发或泛化转发，但真实可用性取决于券商 QMT 是否在策略环境里暴露对应 callable。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| 已实现 | 外部入口、桥接分发和大 QMT callable 调用链已经打通；真实数据仍以 QMT 返回为准。 |
| 已实现（含降级） | 优先调用 QMT 原生 callable，缺失时 cfquant 会用可用的基础能力返回兼容结果，并标记部分字段。 |
| 部分实现 | 已有入口，但参数语义、Web 入口、返回结构或真实 QMT 版本兼容性还不完整。 |
| 条件可实现 | cfquant 已有入口或泛化转发，只有用户所在大 QMT 版本、券商插件或策略环境暴露对应 callable 时才能工作。 |
| 不能实现/不应实现 | 大 QMT 策略环境没有对应能力，或该能力属于 MiniQMT 客户端/行情服务器管理，不应放进主链路。 |

## 已实现

### 本地服务与通信模式

| 能力 | 外部入口 | 说明 |
| --- | --- | --- |
| 桥接连通检测 | `cfquant.ping` / `GET /api/status` | 普通桥、极速桥都支持。 |
| 桥接状态查询 | `cfquant.status` / `GET /api/status` | 返回 context、tx、通道、队列等状态。 |
| 通信模式切换 | `GET /api/transport` / `POST /api/transport` | 支持通用模式 `ctypes`、高级模式 `lttx`、极致模式 `lite`；高级模式要求普通 QMT、极速交易端同时在线。 |
| `xtdata` 高级模式路由 | Web 请求路由 / 客户端请求路由 | 只读 `xtdata` 默认极速交易桥优先、普通桥回退；订阅、下载、callback/event 类 `xtdata` 固定普通桥。 |
| PipeHub 状态 | `GET /api/pipe-hub` / `POST /api/pipe-hub/start` / `POST /api/pipe-hub/stop` | 通用模式使用；负责单文件 ctypes 双通道的请求、响应和回调转发。 |
| 多账号路由 | Web 账号绑定 / `account_key` | 同一 QMT 的多个普通、信用、期货、期货期权、股票期权账户共用一个 `bridge_id`，请求按 `bridge_id:account_type:account_id` 路由；多个 QMT 使用不同 `bridge_id` 和对应频道。 |
| QMT 核心更新 | `POST /api/account-config/update-core` | 将当前项目里的 cfquant 核心文件同步到绑定 QMT 目录，用于客户侧更新桥脚本。 |
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
| 批量撤单 | `cftrader.cancel_order_stock_batch` / `cftrader.cancel_order_stock_batch_async` | `cancel` | 已实现；一次批量 RPC 发到 QMT，QMT 内连续调用 `cancel`，支持同步和异步返回。 |
| 交易回调转发 | WebSocket `/ws/callbacks` | QMT 策略回调函数 | 已实现资金、持仓、委托、成交、错误等回调转发。 |
| 信用资金明细 | `query_credit_detail` / `query_credit_detail_async` / `POST /api/credit/query` (`action=detail`) | `get_trade_detail_data(account_id, "credit", "account")` | SDK 返回 `XtCreditDetail`，Web 返回 JSON；校验账号和信用类型，映射负债、市值别名，标记缺失字段；缓存已用额度单独保存在 `cfquant_qmt_fields`，不当作官网冻结额度。不主动发起柜台异步查询。 |
| 信用负债合约 | `query_stk_compacts` / `query_stk_compacts_async` | `get_unclosed_compacts(account_id, "CREDIT")`，缺失时使用旧 `get_debt_contract(account_id)` | SDK 返回 `StkCompacts`；保留合约编号和缺失字段，不混入已了结合约，不猜算旧终端缺失的息费。 |
| 其他信用专项查询 | `query_credit_subjects` / `query_credit_slo_code` / `query_credit_assure` | `get_assure_contract` / `get_enable_short_contract` | 返回对应专用对象，统一账号校验和缺失字段标记；实际范围、券源枚举仍需券商终端核对。 |
| 信用能力探测 | `POST /api/credit/probe` | 只读调用资产、持仓、委托、成交和信用专项查询 | 已实现；用于部署后确认当前信用账户能力，不触发交易委托。 |

### 行情与基础数据

| 能力 | 外部入口 | 大 QMT 侧依赖 | 当前状态 |
| --- | --- | --- | --- |
| 实时 tick/全推快照 | `xtdata.get_full_tick` / `/api/data/full-tick` | `ContextInfo.get_full_tick` | 已实现；高级模式默认交易桥优先，保证低延迟。 |
| 行情查询 | `xtdata.get_market_data` / `/api/data/market` | `get_market_data` 或 `get_market_data_ex` | 已实现；高级模式默认交易桥优先、普通桥回退。 |
| 扩展行情查询 | `xtdata.get_market_data_ex` / `/api/data/market-ex` | `get_market_data_ex` | 已实现；高级模式默认交易桥优先、普通桥回退。 |
| 本地数据查询 | `xtdata.get_local_data` | `get_local_data`，缺失时降级到 `get_market_data_ex` | 已实现，但 `data_dir` 仅保留兼容参数，未真正接管本地目录。 |
| 单股行情订阅 | `xtdata.subscribe_quote` / `/api/quotes/subscribe` | 普通桥内部全推订阅与过滤 | 已实现。 |
| 全推行情订阅 | `xtdata.subscribe_whole_quote` / `/api/quotes/whole/subscribe` | `ContextInfo.subscribe_whole_quote` | 已实现；通用模式走 ctypes 单文件桥，高级模式固定普通 QMT 桥。 |
| 取消行情订阅 | `xtdata.unsubscribe_quote` / `/api/quotes/unsubscribe` | 普通桥订阅状态 | 已实现。 |
| 证券合约详情 | `xtdata.get_instrument_detail` / `/api/data/instrument` | `get_instrument_detail`；缺失时用基础属性 callable 合成 | 已实现（含降级）；高级模式默认交易桥优先、普通桥回退。降级结果带 `cfquant_detail_fallback=True` 和 `cfquant_detail_partial=True`，价格涨跌停等深度字段不能保证。 |
| 板块成分 | `xtdata.get_stock_list_in_sector` / `/api/data/sector` | `ContextInfo.get_stock_list_in_sector` | 已实现，但参数集仍较简化。 |
| 交易日期 | `xtdata.get_trading_dates` | `ContextInfo.get_trading_dates(...)` | 已实现。 |
| 证券类型/基础属性 | `xtdata.is_stock`、`is_fund`、`is_future`、`get_stock_type`、`get_stock_name`、`get_open_date` | 同名大 QMT callable | 已实现；如果券商 QMT 不暴露对应 callable，会返回明确的 `not found`。 |
| 合约到期日/乘数 | `xtdata.get_contract_expire_date`、`get_contract_multiplier` | 同名大 QMT callable | 已实现；真实可用性取决于当前 QMT callable。 |
| 指数成分权重/换手率 | `xtdata.get_weight_in_index`、`get_turnover_rate` | 同名大 QMT callable | 已实现；真实可用性取决于当前 QMT callable。 |
| ETF / 期权 / ST / 因子 | `xtdata.get_ETF_list`、`get_etf_list`、`get_option_detail_data`、`get_option_list`、`get_option_undl`、`get_option_undl_data`、`get_his_st_data`、`get_his_index_data`、`get_factor_data` | 同名大 QMT callable | 条件可实现；cfquant 已有专门分发和参数适配，但需要当前 QMT 暴露对应 callable。 |

### 数据下载

| 能力 | 外部入口 | 大 QMT 侧依赖 | 当前状态 |
| --- | --- | --- | --- |
| 单证券历史行情下载 | `xtdata.download_history_data` / `/api/data/history/download` | `download_history_data` 或 `down_history_data` | 已实现；所有模式都固定普通 QMT 桥。 |
| 批量历史行情下载 | `xtdata.download_history_data2` | `download_history_data2` 或 `down_history_data2` | 已实现，支持 `callback_event` 事件转发。 |
| 财务数据查询 | `xtdata.get_financial_data` / `get_financial_data_ori` / `get_raw_financial_data` / `/api/data/financial` | `get_financial_data` 或 `get_raw_financial_data` | 已实现。 |
| 财务本地校验 | `xtdata.download_financial_data` / `download_financial_data2` / `/api/data/financial/download` | `download_financial_data2`、`down_financial_data2`，或降级到 `get_financial_data` / `get_raw_financial_data` | 部分实现；若 QMT 暴露下载 callable 则转发，否则降级为读取/校验本地已下载财务数据，并提示用户先在 QMT 客户端“数据管理 - 财务数据下载”中下载。 |
| 交易日历下载 | `xtdata.download_holiday_data` | `download_holiday_data` 或 `down_holiday_data` | 条件可实现；大 QMT 内置文档说明内置环境通过界面端“节假日数据 - 下载”，原生 xtquant 才调用 `xtdata.download_holiday_data()`。当前 QMT 不暴露 callable 时，报错 `requires QMT callable: download_holiday_data, down_holiday_data` 是预期结果。 |
| 交易日历/交易时段补充 | `get_trading_calendar` / `get_trading_period` / `get_kline_trading_period` / `get_all_trading_periods` / `get_period_list` | 同名 QMT callable | 条件可实现；`get_trading_calendar` 还依赖本地节假日数据是否已通过 QMT 界面或原生 xtquant 下载。 |
| 板块维护 | `create_sector` / `add_sector` / `remove_sector` / `reset_sector` / `remove_stock_from_sector` | 同名 QMT callable | 条件可实现；实际取决于 QMT 策略环境权限和 callable。 |
| 公式系统 | `create_formula` / `call_formula` / `subscribe_formula` / `unsubscribe_formula` / `get_formula_result` | 同名 QMT callable | 条件可实现；订阅 callback 通过 cfquant 事件通道转发。 |
| L2 行情 | `get_l2_quote` / `get_l2_order` / `get_l2_transaction`；`get_market_data_ex`、`subscribe_quote` 的六类 L2 周期 | `ContextInfo.get_market_data_ex` / `subscribe_quote` / `unsubscribe_quote` | 已实现周期查询、原生订阅及回调、真实退订；保留大整数与深度数组，仍需券商行情权限。见 [Level2 行情适配说明](Level2行情适配说明.md)。 |
| 千档盘口与队列 | `subscribe_l2thousand` / `subscribe_l2thousand_queue` / `get_l2thousand_queue` | 终端实际暴露的原生 callable | 条件待验证；已提供参数、回调与退订链路，但大 QMT 内置文档无已确认的等价来源。缺失时报错，不用一档队列替代。 |
| 其他下载类补充 | `download_sector_data` / `download_index_weight` / `download_history_contracts` / `download_etf_info` / `download_cb_data` / `download_his_st_data` / `download_metatable_data` / `download_tabular_data` | 同名或 `down_*` QMT callable | 条件可实现；返回结构以 QMT callable 为准。 |

## 条件实现与兼容入口

| 能力 | 当前情况 | 后续建议 |
| --- | --- | --- |
| `xttrader` 扩展查询 | `query_account_info`、`query_account_infos`、`query_account_status`、`query_secu_account`、`query_data`、`export_data` 等已通过候选 callable 转发。 | 用真实券商 QMT 逐项确认 callable 名称、参数和返回结构；稳定后再提升为明确签名。 |
| 银证/资金/证券划转 | `query_bank_info`、`query_bank_amount`、`query_bank_transfer_stream`、`bank_transfer_in`、`bank_transfer_out`、`fund_transfer`、`secu_transfer`、CTP 相关划转入口已有转发。 | 只在客户 QMT 明确暴露对应 callable 且已完成小额验证后开放给页面操作。 |
| SMT 兼容入口 | 查询要求字典列表；申请、撤销、归还和展期仅在扩展函数返回明确业务结果时派发 `XtSmtAppointmentResponse`，关联本地 seq，不自动重复提交。 | 内置 API 尚无可确认的对应调用及异步协议；缺失函数明确报未支持，仅有受理编号报结果未知。不能视为原生 SMT 完整适配。 |
| `xtdata` 泛化条件入口 | `cfquant.xtdata` 已导出公式、L2、表格、板块维护、若干下载类条件方法，桥接端用 `*args/**kwargs` 透传到 QMT callable。 | 高频接口应在真实 QMT 验证后补明确签名、错误提示和 Web 表单。 |

## 部分实现或待补强

| 能力 | 当前情况 | 后续建议 |
| --- | --- | --- |
| `get_local_data` 的原版目录参数 | 兼容参数 `data_dir` 还保留在 Python 层，但桥接层不真正接管本地目录。 | 如果后续要严格复刻原版，再补本地数据目录语义。 |
| `get_stock_list_in_sector` 的原版参数 | 当前只保留常用参数，`real_timetag` 还未完整暴露。 | 需要时补齐参数并按真实 QMT 返回验证。 |
| `get_instrument_detail` 深度字段 | 原生 callable 缺失时可以返回基础兼容结构，但涨跌停、昨收、保证金、状态等深度字段只能填默认值。 | 客户 QMT 如果暴露 `get_instrument_detail`，优先使用原生结果；否则调用方要识别 `cfquant_detail_partial=True`。 |
| `download_history_data2` 的 Web 入口 | 底层桥接已能接收 `callback_event` 并转发事件；Web 单证券下载会优先走 `download_history_data2`。 | 如需页面批量下载，再增加 `/api/data/history/download-batch`。 |
| 财务数据脚本下载 | 大 QMT 内置环境不一定提供等价脚本 callable，当前不能保证由脚本触发真实下载。 | 保留 `/api/data/financial/download` 兼容入口，内部降级为本地财务数据校验；真实下载仍由 QMT 客户端数据管理完成。 |
| 交易日历脚本下载 | 内置文档指向界面端下载，客户侧 QMT 不暴露 `download_holiday_data` 时 cfquant 不能强行触发。 | 文档、页面和错误提示都应引导用户在 QMT 界面下载节假日数据；只把原生 xtquant callable 作为条件能力。 |
| 系统编号撤单 | 当前复用 `cancel(order_id, account_id, account_type, context)`。 | 需要真实系统编号撤单验证不同 QMT 版本参数。 |

## 不应在主链路实现

| 能力 | 原因 | 处理建议 |
| --- | --- | --- |
| MiniQMT 行情服务器连接管理：`connect` / `disconnect` / `reconnect` | 这是 MiniQMT `xtquant.xtdata` 客户端连接控制，不属于大 QMT `ContextInfo` 函数封装。 | 不放入 cfquant 主链路。 |
| MiniQMT 行情服务器状态：`get_quote_server_status` / `watch_quote_server_status` / `get_quote_server_config` | 依赖 MiniQMT 客户端连接状态，不等价于大 QMT 桥接状态。 | 当前用 `cfquant.status` 表示桥接状态。 |
| MiniQMT 数据目录控制：`get_data_dir` / 修改 `xtdata.data_dir` | 属于 MiniQMT 本地数据路径语义，不应影响大 QMT 封装链路。 | 不作为主链路接口。 |
| MiniQMT 本地文件读写：`read_feather` / `write_feather` | 这是 MiniQMT 本地数据文件访问能力，不是大 QMT 策略 callable。 | 不放入 cfquant 主链路。 |
| 直接导入 `xtquant.xtdata` 作为兜底实现 | 会把 cfquant 从“大 QMT 函数封装”变成“MiniQMT SDK 代理”。 | 已从旧桥 `_get_callable` 移除该兜底。 |
| 大 QMT 未暴露且无等价 callable 的接口 | 桥接层没有真实可调用对象，无法保证行为。 | 返回明确未实现错误，并在文档中标记为条件可实现或不能实现。 |

## Web 接口开放状态

本表只列和 QMT 函数封装直接相关的接口，不覆盖登录、配置、版本检查、项目更新等全部管理接口。

| Web 接口 | 状态 | 说明 |
| --- | --- | --- |
| `GET /api/health` | 已实现 | 无鉴权健康检查。 |
| `GET /api/status` | 已实现 | 桥接端状态。 |
| `GET /api/transport` / `POST /api/transport` | 已实现 | 通用模式、高级模式、极致模式查看和切换；高级模式切换前检查双桥。 |
| `GET /api/pipe-hub` / `POST /api/pipe-hub/start` / `POST /api/pipe-hub/stop` | 已实现 | 通用模式 PipeHub 管理。 |
| `POST /api/account-config/update-core` | 已实现 | 将 cfquant 核心同步到绑定 QMT 目录。 |
| `POST /api/data/full-tick` | 已实现 | 实时 tick/快照。 |
| `POST /api/data/market` | 已实现 | 行情数据。 |
| `POST /api/data/market-ex` | 已实现 | 扩展行情数据。 |
| `POST /api/data/instrument` | 已实现 | 合约详情；原生 callable 缺失时返回降级结构。 |
| `POST /api/data/sector` | 已实现 | 板块成分。 |
| `POST /api/data/history/download` | 已实现 | 单证券历史下载，固定普通 QMT。 |
| `POST /api/data/history/download-batch` | 未实现 | 底层 `download_history_data2` 已有事件转发；页面批量入口尚未开放。 |
| `POST /api/data/financial` | 已实现 | 财务查询。 |
| `POST /api/data/financial/download` | 部分实现 | 财务本地数据校验/预加载读取，支持任务进度事件；真实财务下载需先在 QMT 客户端完成，除非 QMT 暴露下载 callable。 |
| `POST /api/quotes/whole/subscribe` | 已实现 | 全推订阅。 |
| `POST /api/quotes/subscribe` | 已实现 | 单股行情事件。 |
| `POST /api/quotes/unsubscribe` | 已实现 | 取消订阅。 |
| `GET /api/quotes/latest` / `WS /ws/quotes` | 已实现 | 行情事件读取/推送。 |
| `GET /api/account` | 已实现 | 资金、持仓、委托、成交。 |
| `POST /api/order` | 已实现 | 单笔下单。 |
| `POST /api/orders/batch` | 已实现 | 批量下单。 |
| `POST /api/cftrader/cancel_order_stock_batch` / `POST /api/cftrader/cancel_order_stock_batch_async` | 已实现 | cftrader 批量同步/异步撤单。 |
| `GET /api/order/actions` | 已实现 | 返回信用、期货、期货期权、股票期权委托动作和别名。 |
| `GET /api/credit/actions` | 已实现 | 返回信用查询动作、信用委托动作和别名。 |
| `POST /api/credit/query` / `POST /api/credit/probe` | 已实现 | 信用专项查询和只读能力探测。 |
| `POST /api/credit/order` | 已实现 | 信用账户单笔业务委托，确认文本使用 `CREDIT_* 代码 数量 @ 价格`。 |
| `POST /api/credit/orders/batch` | 已实现 | 信用账户批量业务委托；每行可单独携带 `credit_action`。 |
| `POST /api/future/order` / `POST /api/future/orders/batch` | 已实现 | 期货账户单笔/批量业务委托；每笔可携带 `order_action`。 |
| `POST /api/future-option/order` / `POST /api/future-option/orders/batch` | 已实现 | 期货期权账户单笔/批量业务委托；每笔可携带 `order_action`。 |
| `POST /api/stock-option/order` / `POST /api/stock-option/orders/batch` | 已实现 | 股票期权账户单笔/批量业务委托；MiniQMT order_type 自动映射到大 QMT opType。 |
| `POST /api/cancel` | 已实现 | 撤单。 |
| `GET /api/callbacks` / `WS /ws/callbacks` | 已实现 | 交易回调事件。 |

## 代码比对摘要

| 代码位置 | 已核对内容 |
| --- | --- |
| `cfquant/xtdata.py` | 明确导出稳定封装函数、基础属性函数和 `_CONDITIONAL_XTDATA_METHODS` 条件函数。 |
| `cfquant/tx_trade_bridge.py` | `_dispatch_xtdata_compat` 覆盖稳定函数、基础属性函数、ETF/期权/ST/因子分发、泛化条件转发和 MiniQMT 不支持清单。 |
| `cfquant_web_server.py` | `forced_channel_for_action()` 只把订阅、下载、callback/event 类 `xtdata` 固定到 `normal`；高级模式低延迟只读 `xtdata` 走 `trade -> normal`。数据类 Web 接口集中在 `/api/data/*` 和 `/api/quotes/*`。 |

## 下一步建议

1. 对客户文档明确：交易日历/节假日数据优先让用户在 QMT 客户端界面下载，不承诺 `download_holiday_data` 在大 QMT 内置环境可用。
2. 收集不同券商 QMT 的 callable 探测结果，把稳定出现的条件接口升级为明确签名和更友好的错误提示。
3. 如果后续要把批量历史下载做成网页动作，再补 `/api/data/history/download-batch`。
