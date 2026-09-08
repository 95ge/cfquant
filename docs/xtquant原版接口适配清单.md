# xtquant 原版接口适配清单

更新时间：2026-09-08

本清单以 [ThinkTrader 原生 Python API 文档](https://dict.thinktrader.net/nativeApi/start_now.html?id=I3DJ97)公开介绍的接口和功能为基准，对照当前 `cfquant` 实现整理。接口范围来自官网文档，不再通过枚举本机 `xtquant` Python 包的函数名确定。

## 范围与标记

- 主要来源：[XtData 行情模块](https://dict.thinktrader.net/nativeApi/xtdata.html)的“接口说明”，以及 [XtQuant 交易模块](https://dict.thinktrader.net/nativeApi/xttrader.html)的“XtQuant API说明”和“XtQuant数据结构说明”。功能释义按这些章节概括。
- 同一章节中的多个接口分别列出，例如 `download_history_data` 和 `download_history_data2`。仅在官网版本说明、备注或示例中出现的接口单独列出，并注明出处。
- 不收录官网没有介绍的包内辅助函数、内部回调包装器、快捷别名及 `cfquant` 扩展入口。常量枚举、行情字段和业务示例函数不作为独立调用接口计数。
- ✅ **已适配**：已实现对应功能的桥接或本地兼容逻辑。✅ **部分适配**：已实现部分功能，但参数、返回值、字段或行为存在明确差异，不能直接视为原版完整替换。
- ❌ **条件待验证**：只有候选函数转发或依赖底层能力的入口，尚不能确认目标大 QMT 能完成官网所述功能。❌ **未适配**：缺少对应入口或功能实现。条件入口不计入已适配。
- 标记依据是当前代码实现，不代表所有券商终端、数据权限和参数组合均已实测。数据结构的标记单独统计，也不代表返回该结构的业务接口已经可用。

## 汇总

以下数量只统计下方逐项表格；“已适配”与“部分适配”分列，避免把部分兼容当作完整实现。

| 范围 | 官网条目数 | ✅ 已适配 | ✅ 部分适配 | ❌ 条件待验证 | ❌ 未适配 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `xtdata` 正文接口 | 43 | 5 | 8 | 18 | 12 |
| `xtdata` 官网补充提及 | 5 | 1 | 0 | 1 | 3 |
| `XtQuantTrader` 正文接口，含构造函数 | 38 | 15 | 5 | 17 | 1 |
| `XtQuantTrader` 官网补充提及 | 3 | 2 | 1 | 0 | 0 |
| `XtQuantTraderCallback` 正文回调 | 8 | 5 | 2 | 1 | 0 |
| 官网交易数据结构及账号对象 | 18 | 9 | 2 | 0 | 7 |

## xtdata：正文接口

本节接口通过 `cfquant.xtdata` 调用，顺序对应官网“接口说明”。

### 行情接口

来源：[行情接口](https://dict.thinktrader.net/nativeApi/xtdata.html#行情接口)。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `subscribe_quote` | 按证券和周期订阅行情，通过回调接收更新 | ✅ 已适配 | 订阅号和行情回调已接入桥事件通道。 |
| `subscribe_whole_quote` | 订阅指定证券或整个市场的最新分笔推送 | ✅ 已适配 | 支持证券列表、市场代码及全推回调。 |
| `unsubscribe_quote` | 根据订阅号停止行情推送 | ✅ 已适配 | 同时清理本地订阅回调。 |
| `run` | 持续等待，以便接收行情回调 | ✅ 部分适配 | 已保持客户端运行；未复刻官网所述断线时抛异常退出循环的行为。 |
| `subscribe_formula` | 订阅 VBA 模型的计算结果 | ❌ 条件待验证 | 已有转发及回调入口；需要终端暴露模型订阅函数，不能据此认定投研端模型功能已适配。 |
| `unsubscribe_formula` | 停止指定模型订阅 | ❌ 条件待验证 | 依赖终端模型反订阅函数。 |
| `call_formula` | 运行指定证券、周期和参数的 VBA 模型 | ❌ 条件待验证 | 仅转发底层同名函数，需验证模型运行环境及结果结构。 |
| `call_formula_batch` | 一次执行多组模型与证券组合 | ❌ 未适配 | 尚无批量模型调用入口；不能用单模型入口的存在代替此项。 |
| `generate_index_data` | 批量计算模型因子并输出本地文件 | ❌ 未适配 | 尚无官网所述因子生成和文件输出流程。 |
| `get_market_data` | 按字段、证券和时间范围读取 K 线或分笔数据 | ✅ 部分适配 | 已映射大 QMT 行情查询；直接返回底层结构，缺少该函数时还会回退到扩展查询，未统一保证官网的按字段组织结构。 |
| `get_local_data` | 批量读取本地已有历史行情 | ✅ 部分适配 | 可读取大 QMT 本地数据或回退扩展查询；`data_dir` 不实现 MiniQMT 本地目录切换语义。 |
| `get_full_tick` | 查询证券或市场当前的最新分笔快照 | ✅ 已适配 | 已接入实时 tick 查询；高级模式优先交易桥，失败后尝试普通桥。 |
| `get_divid_factors` | 查询分红、配股等除权数据及因子 | ❌ 未适配 | 尚无对应查询入口；行情查询的复权参数不等于此接口。 |
| `download_history_data` | 补充单只证券指定周期的历史行情 | ✅ 已适配 | 已接入历史行情补充流程。 |
| `download_history_data2` | 批量补充历史行情，并通过回调报告进度 | ✅ 部分适配 | 已有批量任务和事件回调；进度及生命周期事件还包含 cfquant 扩展语义。 |
| `download_history_contracts` | 补充已到期或退市合约的基础资料 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `get_holidays` | 读取已保存的节假日日期 | ❌ 未适配 | 尚无读取节假日的同名入口。 |
| `get_trading_calendar` | 查询指定市场在日期区间内的交易日历 | ❌ 条件待验证 | 依赖终端日历函数及已有节假日数据；不是 `get_trading_dates` 的直接别名。 |
| `download_cb_data` | 更新可转债基础资料 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `get_cb_info` | 查询指定可转债的基础资料 | ❌ 未适配 | cfquant 尚未接入。大 QMT 有 `ContextInfo.get_convert_bond_info(bondcode)`，可返回存续期转债的正股代码和最新转股价，可作为部分适配来源；完整资料不能直接视为等价，见下方说明。 |
| `get_ipo_info` | 查询日期范围内的新股发行和申购资料 | ❌ 未适配 | 交易侧当日新股查询不能直接替代此行情接口。 |
| `get_period_list` | 查询当前数据服务支持的数据周期 | ❌ 条件待验证 | 仅转发终端同名函数。 |
| `download_etf_info` | 更新 ETF 申购赎回清单资料 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `get_etf_info` | 查询 ETF 申购赎回清单资料 | ❌ 未适配 | ETF 代码列表入口不等于 ETF 申赎清单查询。 |
| `download_holiday_data` | 更新本地节假日数据 | ❌ 条件待验证 | 已有入口，但需要终端暴露 `download_holiday_data` 或 `down_holiday_data`；用户已提供缺少这两个函数的报错。通过 QMT 界面下载不等于此 Python 接口已实现。 |
| `get_full_kline` | 获取最新交易日的 K 线快照 | ❌ 未适配 | 已有普通行情查询，但未实现官网这个独立接口。 |

#### 可转债接口的对应关系

[官方函数检索表](https://dict.thinktrader.net/VBA/check_sheet.html)同时列有内置 Python 和 VBA 函数：`ContextInfo.get_convert_bond_info(bondcode)` 返回字典，其中 `stockcode` 是正股代码，`convert_price` 是最新转股价，适用范围为存续期内可转债。该能力可以作为 `get_cb_info` 的部分数据来源，但当前 cfquant 尚未映射，也未在目标终端实测。

同一检索表中的 VBA `get_cb_info(转债代码, 字段号)`、`get_cb_info_num(转债代码, 字段号)` 按字段返回字符串或数值，可查询发行总额、债券余额、转股价等。它们不等同于原生 Python `xtdata.get_cb_info(stockcode)` 返回完整资料字典的接口；要作为完整适配来源，还需验证 Python 到 VBA 的调用路径并逐项转换字段。[官方教程的接口对照表](https://dict.thinktrader.net/freshman/rookie.html#其他vip数据)对原生 `xtdata.get_cb_info` 的内置 Python 对应项标为 `None`，不能据此否定上述较小范围的内置查询能力。

### 财务数据接口

来源：[财务数据接口](https://dict.thinktrader.net/nativeApi/xtdata.html#财务数据接口)。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `get_financial_data` | 按证券、财务表和日期范围查询财务数据 | ✅ 部分适配 | 官网使用 `stock_list, table_list`；cfquant 使用 `field_list, stock_list`，默认 `report_type` 也不同，需要调整调用，不能原样替换。 |
| `download_financial_data` | 下载指定证券的财务表数据 | ❌ 条件待验证 | 有底层下载函数才会真实下载；缺失时仅校验本地数据，并返回 `download_supported=False`、`manual_download_required=True`。 |
| `download_financial_data2` | 下载指定时间范围的财务数据并报告进度 | ❌ 条件待验证 | 复用财务下载流程及事件回调；底层缺少下载能力时仍只是本地校验。 |

### 基础行情信息

来源：[基础行情信息](https://dict.thinktrader.net/nativeApi/xtdata.html#基础行情信息)。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `get_instrument_detail` | 查询合约的市场、名称、上市日期等基础字段 | ✅ 部分适配 | 优先调用终端详情函数；缺失时合成部分基础字段，并标记 `cfquant_detail_fallback`、`cfquant_detail_partial`，不保证完整详情字段。 |
| `get_instrument_type` | 判断合约所属证券类型 | ❌ 未适配 | `is_stock`、`is_fund` 等扩展入口不等于官网接口及其返回结构。 |
| `get_trading_dates` | 查询某市场在日期区间内的交易日列表 | ✅ 部分适配 | 官网参数是 `market/start_time/end_time`；cfquant 使用大 QMT 的 `stockcode/start_date/end_date/period`，参数和市场语义需要转换。 |
| `get_sector_list` | 列出可查询的板块名称 | ❌ 未适配 | 尚无板块目录查询入口。 |
| `get_stock_list_in_sector` | 查询某个板块包含的证券代码 | ✅ 部分适配 | 常用板块查询已接入；官网版本说明提到的 `real_timetag` 参数尚未支持。 |
| `download_sector_data` | 更新板块分类和成分信息 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `create_sector_folder` | 在板块树中创建目录 | ❌ 未适配 | 尚无板块目录创建入口。 |
| `create_sector` | 在指定目录下建立板块 | ❌ 条件待验证 | 已有同名转发，父节点、覆盖参数等语义需终端支持并验证。 |
| `add_sector` | 添加自定义板块及其证券列表 | ❌ 条件待验证 | 仅转发终端同名函数。 |
| `remove_stock_from_sector` | 从板块中移除指定证券 | ❌ 条件待验证 | 仅转发终端同名函数；此项是删除成分股，不是创建板块。 |
| `remove_sector` | 删除指定自定义板块 | ❌ 条件待验证 | 仅转发终端同名函数。 |
| `reset_sector` | 用新证券列表替换板块成分 | ❌ 条件待验证 | 仅转发终端同名函数。 |
| `get_index_weight` | 查询指数成分及对应权重 | ❌ 未适配 | 扩展接口 `get_weight_in_index` 查询单个成分权重，不能直接替代官网的整组返回。 |
| `download_index_weight` | 更新指数成分权重数据 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |

## xtdata：官网补充提及

这些名称见于 [行情模块版本信息](https://dict.thinktrader.net/nativeApi/xtdata.html#版本信息)，本次读取的“接口说明”没有为其提供独立完整章节。保留它们是因为官网明确提及，而不是因为本机 Python 包中存在这些名称。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `get_market_data_ex` | 以扩展结构查询行情及周期数据 | ✅ 已适配 | 已映射大 QMT 扩展行情查询；官网还提及 ETF 清单、历史主力合约等周期，这些数据源是否可用需分别确认。 |
| `get_option_detail_data` | 查询期权合约基础资料 | ❌ 条件待验证 | 有专门转发入口，依赖大 QMT 的对应函数；官网 2024-01-19 说明提及商品期权支持。 |
| `get_trading_time` | 查询证券交易时段 | ❌ 未适配 | 官网 2024-01-22 说明使用此名；现有 `get_trading_period` 等入口不能据此认定已实现本接口。 |
| `get_trade_times` | 查询交易时段的历史接口名 | ❌ 未适配 | 官网说明已改名为 `get_trading_time`；作为历史名称列出，不代表另一项独立功能。 |
| `reconnect` | 切换并连接指定地址的行情服务 | ❌ 未适配 | 官网 2023-02-06 提及；cfquant 的桥连接配置不实现此 MiniQMT 连接接口。 |

## XtQuantTrader：正文接口

以下方法属于 `cfquant.xttrader.XtQuantTrader`，对应官网 [XtQuant API说明](https://dict.thinktrader.net/nativeApi/xttrader.html#xtquant-api说明)。构造函数也作为一个调用接口列出。

### 系统设置接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `XtQuantTrader(path, session_id)` | 创建交易 API 对象并指定会话 | ✅ 部分适配 | 可构造 cfquant 交易对象；`path` 被保留，但不连接该路径下的 MiniQMT，连接使用 cfquant 桥配置。 |
| `register_callback` | 注册交易推送的回调对象 | ✅ 已适配 | 已注册账号及交易事件处理函数。 |
| `start` | 启动 API 所需的后台处理环境 | ✅ 已适配 | 启动桥客户端并注册事件。 |
| `connect` | 建立交易连接并返回连接结果 | ✅ 已适配 | 连接并探测 cfquant 桥，成功返回 `0`，失败返回 `-1`。 |
| `stop` | 停止 API 及后台处理 | ✅ 已适配 | 清理账号订阅并关闭桥客户端。 |
| `run_forever` | 保持当前线程等待，直到停止 | ✅ 已适配 | 已提供阻塞等待循环。 |
| `set_relaxed_response_order_enabled` | 控制同步请求返回是否使用额外专用线程 | ❌ 未适配 | 当前只保存布尔标志，没有实现该标志控制的线程调度；不能标为功能已适配。 |

### 操作接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `subscribe` | 订阅账号的委托、成交等交易变化 | ✅ 已适配 | 已接入账号级事件订阅。 |
| `unsubscribe` | 取消账号交易事件订阅 | ✅ 已适配 | 已取消远端订阅并清理本地记录。 |
| `order_stock` | 同步提交证券委托并取得委托编号 | ✅ 已适配 | 已映射大 QMT `passorder` 及委托编号关联流程。 |
| `order_stock_async` | 提交异步委托，通过请求序号关联回报 | ✅ 已适配 | 已实现请求序号、委托关联和异步回报事件。 |
| `cancel_order_stock` | 按委托编号提交撤单 | ✅ 已适配 | 已映射大 QMT `cancel`。 |
| `cancel_order_stock_sysid` | 按市场及柜台合同编号提交撤单 | ✅ 部分适配 | 目前将 `sysid` 交给普通撤单流程；市场区分及柜台编号识别尚需验证，关键字名也与官网的 `order_sysid` 不同。 |
| `cancel_order_stock_async` | 按委托编号撤单并反馈异步结果 | ✅ 已适配 | 已提供请求序号和桥撤单响应事件。 |
| `cancel_order_stock_sysid_async` | 按柜台合同编号撤单并反馈异步结果 | ✅ 部分适配 | 具备回报事件，但沿用上述 `sysid` 撤单的限制。 |
| `fund_transfer` | 在指定方向进行资金划拨 | ❌ 条件待验证 | 仅转发终端资金划拨函数。 |
| `sync_transaction_from_external` | 将外部成交记录导入交易系统 | ❌ 条件待验证 | 仅转发对应录入函数；此功能不是数据导出。 |

### 股票查询接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_stock_asset` | 查询账号资金及总资产 | ✅ 已适配 | 读取大 QMT 资金明细并转换为 `XtAsset`。 |
| `query_stock_orders` | 查询当日委托，可只返回可撤委托 | ✅ 已适配 | 读取委托明细，支持 `cancelable_only` 筛选并转换为 `XtOrder`。 |
| `query_stock_trades` | 查询当日成交记录 | ✅ 已适配 | 读取成交明细并转换为 `XtTrade`。 |
| `query_stock_positions` | 查询账号证券持仓 | ✅ 已适配 | 读取持仓明细并转换为 `XtPosition`。 |
| `query_position_statistics` | 查询期货持仓的汇总统计 | ❌ 条件待验证 | 仅尝试底层统计查询函数；尚无专用 `XtPositionStatistics` 结构适配。 |

### 信用查询接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_credit_detail` | 查询信用账号资产及融资融券资金情况 | ❌ 条件待验证 | 仅尝试候选信用查询函数，未统一转换为官网信用资产结构。 |
| `query_stk_compacts` | 查询融资融券负债合约 | ❌ 条件待验证 | 仅尝试候选负债查询函数，未统一转换为官网负债合约结构。 |
| `query_credit_subjects` | 查询融资融券业务的标的证券 | ❌ 条件待验证 | 依赖终端候选查询函数及其结果结构。 |
| `query_credit_slo_code` | 查询可用于融券的证券及相关信息 | ❌ 条件待验证 | 依赖终端候选查询函数及其结果结构。 |
| `query_credit_assure` | 查询担保证券及担保品信息 | ❌ 条件待验证 | 依赖终端候选查询函数及其结果结构。 |

### 其他查询接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_new_purchase_limit` | 查询账号可用的新股申购额度 | ❌ 条件待验证 | 仅尝试终端候选查询函数。 |
| `query_ipo_data` | 查询当日可申购的新股和新债 | ❌ 条件待验证 | 仅尝试终端候选查询函数。 |
| `query_account_infos` | 查询可使用的资金账号信息 | ❌ 条件待验证 | 仅尝试终端账号查询函数；尚未统一转换为 `XtAccountInfo`。 |
| `query_account_status` | 查询资金账号当前状态 | ❌ 条件待验证 | 仅尝试终端账号状态查询函数，结果未统一规范。 |
| `query_com_fund` | 查询划拨业务中普通柜台的资金 | ✅ 部分适配 | 当前复用大 QMT 账号资金明细，尚未保证区分官网所述普通柜台资金。 |
| `query_com_position` | 查询划拨业务中普通柜台的持仓 | ✅ 部分适配 | 当前复用大 QMT 持仓明细，尚未保证区分官网所述普通柜台持仓。 |
| `export_data` | 按数据类型和时间范围导出数据文件 | ❌ 条件待验证 | 仅转发同名函数，文件生成及字段依赖终端实现。 |
| `query_data` | 借助导出流程查询指定业务数据 | ❌ 条件待验证 | 当前仅转发查询函数，没有独立实现官网所述导出、读取、删除文件流程。 |

### 约券相关接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `smt_query_quoter` | 查询可申请的券源及报价 | ❌ 条件待验证 | 仅转发终端券源查询函数。 |
| `smt_negotiate_order_async` | 提交库存券约券申请并接收反馈 | ❌ 条件待验证 | 当前尝试 `smt_negotiate_order` 后在本地调用反馈函数，未保证官网的异步受理和后续回报语义。 |
| `smt_query_compact` | 查询已形成的约券合约 | ❌ 条件待验证 | 仅转发终端约券合约查询函数。 |

## XtQuantTrader：官网补充提及

来源：交易文档的 [创建策略示例](https://dict.thinktrader.net/nativeApi/xttrader.html#创建策略)及 [开启主动请求接口的专用线程](https://dict.thinktrader.net/nativeApi/xttrader.html#开启主动请求接口的专用线程)备注。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_stock_order` | 按委托编号查询一笔委托 | ✅ 已适配 | 官网快速入门示例使用；cfquant 从委托列表匹配目标委托。 |
| `query_stock_position` | 查询指定证券的持仓 | ✅ 已适配 | 官网快速入门示例使用；cfquant 从持仓列表匹配证券代码。 |
| `query_stock_orders_async` | 通过回调取得委托查询结果 | ✅ 部分适配 | 官网专用线程章节备注提及；当前同步查询后直接调用 callback，不是原版异步查询调度。 |

官网版本说明将约券申请写作 `smt_negotiate_order`，正文给出的调用签名是 `smt_negotiate_order_async`。本清单按正文签名列一项，不将版本说明中的名称额外计数或认定为可调用别名。

## XtQuantTraderCallback：正文回调

来源：[回调类](https://dict.thinktrader.net/nativeApi/xttrader.html#回调类)。可继承 `cfquant.xttrader.XtQuantTraderCallback` 实现以下处理函数；本表只列官网该章节明确命名的八个回调。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `on_disconnected` | 在交易连接断开时收到通知 | ✅ 部分适配 | 本地 `stop()` 会触发，且可接收同名桥事件；未保证自动覆盖底层所有异常断线场景。 |
| `on_account_status` | 接收资金账号状态变化 | ✅ 部分适配 | 已有事件入口和对象包装，但 `XtAccountStatus` 未统一账号状态字段映射。 |
| `on_stock_order` | 接收委托状态及成交数量变化 | ✅ 已适配 | 已接入大 QMT 委托回调并进行订单字段转换。 |
| `on_stock_trade` | 接收新增成交记录 | ✅ 已适配 | 已接入大 QMT 成交回调并进行成交字段转换。 |
| `on_order_error` | 接收委托提交失败的信息 | ✅ 已适配 | 已有错误事件和 `XtOrderError` 对象转换。 |
| `on_cancel_error` | 接收撤单失败的信息 | ✅ 已适配 | 已有错误事件和 `XtCancelError` 对象转换。 |
| `on_order_stock_async_response` | 接收异步报单请求对应的委托结果 | ✅ 已适配 | 已实现请求序号与委托回报关联。 |
| `on_smt_appointment_async_response` | 接收约券申请等异步业务反馈 | ❌ 条件待验证 | 已有回调入口；约券业务本身及异步受理语义仍依赖终端，不能按存在回调方法认定完成。 |

## 官网交易数据结构及账号对象

来源：[XtQuant数据结构说明](https://dict.thinktrader.net/nativeApi/xttrader.html#xtquant数据结构说明)，另含官网快速入门使用的 `StockAccount`。这些条目是输入或返回对象，不计入前面的函数数量；只返回字典不等于已适配官网的对象属性访问。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `StockAccount` | 指定资金账号及账号类型 | ✅ 已适配 | 已提供账号对象，并扩展桥路由信息。 |
| `XtAsset` | 表示现金、冻结资金、市值和总资产 | ✅ 已适配 | 已实现常用资金字段映射。 |
| `XtOrder` | 表示委托编号、价格、数量和状态 | ✅ 已适配 | 已实现常用委托字段和大 QMT 字段映射。 |
| `XtTrade` | 表示成交证券、价格、数量及关联委托 | ✅ 已适配 | 已实现常用成交字段映射。 |
| `XtPosition` | 表示持仓数量、可用数量、成本和市值 | ✅ 已适配 | 已实现常用持仓字段映射。 |
| `XtPositionStatistics` | 表示期货持仓汇总及相关统计 | ❌ 未适配 | 尚无专用对象及字段转换。 |
| `XtOrderResponse` | 表示异步报单的请求序号和委托编号 | ✅ 已适配 | 已提供对象及请求序号、委托关联字段。 |
| `XtCancelOrderResponse` | 表示异步撤单请求的处理结果 | ✅ 已适配 | 已提供对象及常用撤单结果字段转换。 |
| `XtOrderError` | 表示报单失败的编号和原因 | ✅ 已适配 | 已提供对象及错误字段转换。 |
| `XtCancelError` | 表示撤单失败的委托标识和原因 | ✅ 已适配 | 已提供对象及错误字段转换。 |
| `XtCreditDetail` | 表示信用账号资产、负债和额度 | ❌ 未适配 | 目前未提供对应专用对象及字段映射。 |
| `StkCompacts` | 表示融资融券负债合约 | ❌ 未适配 | 目前未提供对应专用对象及字段映射。 |
| `CreditSubjects` | 表示融资融券标的及其业务属性 | ❌ 未适配 | 目前未提供对应专用对象及字段映射。 |
| `CreditSloCode` | 表示可融券证券及可用券源信息 | ❌ 未适配 | 目前未提供对应专用对象及字段映射。 |
| `CreditAssure` | 表示担保证券及担保品属性 | ❌ 未适配 | 目前未提供对应专用对象及字段映射。 |
| `XtAccountStatus` | 表示账号及当前连接状态 | ✅ 部分适配 | 目前为通用属性对象，未实现专用字段规范化。 |
| `XtAccountInfo` | 表示账号类型、账号标识等账号资料 | ❌ 未适配 | 目前未提供对应专用对象及字段映射。 |
| `XtSmtAppointmentResponse` | 表示约券业务请求的异步反馈 | ✅ 部分适配 | 目前为通用属性对象，未实现专用字段规范化；不代表约券业务已可用。 |

## 使用边界与维护依据

- 高级模式下，低延迟只读 `xtdata` 请求默认交易桥优先、普通桥回退；订阅、反订阅、下载及携带回调的请求走普通桥。路由改变不会补出终端本来没有的函数。
- 条件入口必须在目标终端确认函数存在，并核对官网参数、返回字段和回调行为后，才能改为已适配。仅成功导入、存在同名方法、通过本地 mock 测试，均不足以确认条件接口可用。
- 已适配通用行情查询不意味着其所有 `period` 对应的数据产品均可用；官网提及的 Level2、千档、ETF 清单、期权和投研特色数据仍需对应终端支持及数据权限。
- 本次为文档和代码对照，未重新执行客户终端联调。官网后续增加或更名的接口，应以官网章节为依据更新清单，不再通过枚举 Python 包自动扩大统计范围。
- 核对入口：[行情兼容层](../cfquant/xtdata.py)、[交易兼容层](../cfquant/xttrader.py)、[交易数据对象](../cfquant/xttype.py)、[QMT 桥能力映射](../cfquant/tx_trade_bridge.py)、[服务端路由](../cfquant_web_server.py)。更详细的大 QMT 能力边界见 [QMT函数封装能力清单](QMT函数封装能力清单.md)。
