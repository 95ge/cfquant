# xtquant 原版接口适配清单

更新时间：2026-09-10

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
| `xtdata` 正文接口 | 43 | 7 | 11 | 18 | 7 |
| `xtdata` 官网补充提及 | 5 | 1 | 0 | 1 | 3 |
| `XtQuantTrader` 正文接口，含构造函数 | 38 | 16 | 12 | 9 | 1 |
| `XtQuantTrader` 官网补充提及 | 3 | 2 | 1 | 0 | 0 |
| `XtQuantTraderCallback` 正文回调 | 8 | 5 | 2 | 1 | 0 |
| 官网交易数据结构及账号对象 | 18 | 15 | 2 | 0 | 1 |

2026-09-09 首批改动覆盖高级模式、通用模式使用的共用桥及 SDK。独立内嵌桥实现的 `CFQUANT_LITE.py` 和其沪深分市场版本，以及旧 `CfquantQmtBridge` 不在本批新增能力覆盖范围内。新增代码已经过模拟终端回归，但未完成券商终端实测；下列状态不能作为所有模式、所有终端均可调用的保证。

2026-09-10 的 Level2 改动另行覆盖了上述全部桥实现，包含六个真实行情周期的查询、订阅、首包回调和原生退订；不代表首批其他接口也已移植到独立入口。逐项功能和千档限制见 [Level2 行情适配说明](Level2行情适配说明.md)。数据周期不重复计入官网接口数量。

## xtdata：正文接口

本节接口通过 `cfquant.xtdata` 调用，顺序对应官网“接口说明”。

### 行情接口

来源：[行情接口](https://dict.thinktrader.net/nativeApi/xtdata.html#行情接口)。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `subscribe_quote` | 按证券和周期订阅行情，通过回调接收更新 | ✅ 已适配 | 已使用真实 QMT 周期订阅，包括六个 Level2 周期，不再从全推 tick 模拟单股周期回调；SDK 回调为证券到记录列表的字典。历史预取与回调时序边界见 Level2 说明。 |
| `subscribe_whole_quote` | 订阅指定证券或整个市场的最新分笔推送 | ✅ 已适配 | 支持证券列表、市场代码及全推回调。 |
| `unsubscribe_quote` | 根据订阅号停止行情推送 | ✅ 已适配 | 释放真实 QMT 订阅并清理本地回调；失败保留订阅供重试，成功后忽略迟到回调。 |
| `run` | 持续等待，以便接收行情回调 | ✅ 部分适配 | 已保持客户端运行；未复刻官网所述断线时抛异常退出循环的行为。 |
| `subscribe_formula` | 订阅 VBA 模型的计算结果 | ❌ 条件待验证 | 已有转发及回调入口；需要终端暴露模型订阅函数，不能据此认定投研端模型功能已适配。 |
| `unsubscribe_formula` | 停止指定模型订阅 | ❌ 条件待验证 | 依赖终端模型反订阅函数。 |
| `call_formula` | 运行指定证券、周期和参数的 VBA 模型 | ❌ 条件待验证 | 仅转发底层同名函数，需验证模型运行环境及结果结构。 |
| `call_formula_batch` | 一次执行多组模型与证券组合 | ❌ 条件待验证 | 已补显式参数入口及大 QMT 批量模型调用，不再依赖单模型入口；不猜测旧版签名，模型环境、数据权限及真实结果仍待终端验证。 |
| `generate_index_data` | 批量计算模型因子并输出本地文件 | ❌ 未适配 | 尚无官网所述因子生成和文件输出流程。 |
| `get_market_data` | 按字段、证券和时间范围读取 K 线或分笔数据 | ✅ 部分适配 | 已映射大 QMT 行情查询；直接返回底层结构，缺少该函数时还会回退到扩展查询，未统一保证官网的按字段组织结构。 |
| `get_local_data` | 批量读取本地已有历史行情 | ✅ 部分适配 | 优先使用大 QMT `get_market_data_ex(..., subscribe=False)` 读取本地数据；已知不支持该签名的旧接口走本地读取，保留空结果，不用自动订阅掩盖缺失数据。`data_dir` 不实现 MiniQMT 本地目录切换语义。 |
| `get_full_tick` | 查询证券或市场当前的最新分笔快照 | ✅ 已适配 | 已接入实时 tick 查询；高级模式优先交易桥，失败后尝试普通桥。 |
| `get_divid_factors` | 查询分红、配股等除权数据及因子 | ✅ 部分适配 | 已将大 QMT 的时间戳字典转换成七列 DataFrame，按毫秒时间戳排序，以北京时间筛选日期区间；索引固定为整数毫秒，尚未与原版真实返回逐项比对。 |
| `download_history_data` | 补充单只证券指定周期的历史行情 | ✅ 已适配 | 已接入历史行情补充流程。 |
| `download_history_data2` | 批量补充历史行情，并通过回调报告进度 | ✅ 部分适配 | 已有批量任务和事件回调；进度及生命周期事件还包含 cfquant 扩展语义。 |
| `download_history_contracts` | 补充已到期或退市合约的基础资料 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `get_holidays` | 读取已保存的节假日日期 | ❌ 未适配 | 尚无读取节假日的同名入口。 |
| `get_trading_calendar` | 查询指定市场在日期区间内的交易日历 | ❌ 条件待验证 | 依赖终端日历函数及已有节假日数据；不是 `get_trading_dates` 的直接别名。 |
| `download_cb_data` | 更新可转债基础资料 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `get_cb_info` | 查询指定可转债的基础资料 | ✅ 部分适配 | 已映射 `get_convert_bond_info`，转换为 `stockCode`、`bondConvPrice`，附带查询代码 `bondCode` 和 `cfquant_partial=True`；仅存续期转债的部分资料，不包含发行规模、余额、条款等完整数据。 |
| `get_ipo_info` | 查询日期范围内的新股发行和申购资料 | ❌ 未适配 | 交易侧当日新股查询不能直接替代此行情接口。 |
| `get_period_list` | 查询当前数据服务支持的数据周期 | ❌ 条件待验证 | 仅转发终端同名函数。 |
| `download_etf_info` | 更新 ETF 申购赎回清单资料 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `get_etf_info` | 查询 ETF 申购赎回清单资料 | ❌ 未适配 | ETF 代码列表入口不等于 ETF 申赎清单查询。 |
| `download_holiday_data` | 更新本地节假日数据 | ❌ 条件待验证 | 已有入口，但需要终端暴露 `download_holiday_data` 或 `down_holiday_data`；用户已提供缺少这两个函数的报错。通过 QMT 界面下载不等于此 Python 接口已实现。 |
| `get_full_kline` | 获取最新交易日的 K 线快照 | ❌ 未适配 | 已有普通行情查询，但未实现官网这个独立接口。 |

#### 可转债接口的对应关系

[官方函数检索表](https://dict.thinktrader.net/VBA/check_sheet.html)同时列有内置 Python 和 VBA 函数：`ContextInfo.get_convert_bond_info(bondcode)` 返回字典，其中 `stockcode` 是正股代码，`convert_price` 是最新转股价，适用范围为存续期内可转债。cfquant 已将其映射为[原生可转债字典](https://dict.thinktrader.net/dictionary/bond.html#获取可转债信息)的 `stockCode`、`bondConvPrice`，返回 `cfquant_source="get_convert_bond_info"` 和部分资料标志。底层返回 `None` 或空字典时保持无数据，不伪造缺失字段；尚未在目标终端实测。

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
| `get_instrument_detail` | 查询合约的市场、名称、上市日期等基础字段 | ✅ 部分适配 | 依次尝试新版名称、旧版 `get_instrumentdetail`、基础字段合成。旧版结果标记 `cfquant_detail_partial` 和来源；合成结果还标记 `cfquant_detail_fallback`。真实业务错误不会触发旧名称回退。 |
| `get_instrument_type` | 判断合约所属证券类型 | ❌ 未适配 | `is_stock`、`is_fund` 等扩展入口不等于官网接口及其返回结构。 |
| `get_trading_dates` | 查询某市场在日期区间内的交易日列表 | ✅ 部分适配 | 官网参数是 `market/start_time/end_time`；cfquant 使用大 QMT 的 `stockcode/start_date/end_date/period`，参数和市场语义需要转换。 |
| `get_sector_list` | 列出可查询的板块名称 | ✅ 部分适配 | 已按大 QMT 节点名称遍历板块树，输出去重后的扁平板块列表，防止循环目录；同名目录及终端分类覆盖仍待实测。 |
| `get_stock_list_in_sector` | 查询某个板块包含的证券代码 | ✅ 已适配 | 已增加 `real_timetag=-1` 参数；指定历史毫秒时间戳时传给大 QMT 的 `realtime`，旧终端不接受该参数时直接报错，不退回当前成分。 |
| `download_sector_data` | 更新板块分类和成分信息 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |
| `create_sector_folder` | 在板块树中创建目录 | ❌ 条件待验证 | 已补显式入口，准确传递父节点、目录名和覆盖标志，保留实际创建名称；不进行副作用调用重试，实际目录写入仍待终端验证。 |
| `create_sector` | 在指定目录下建立板块 | ❌ 条件待验证 | 已改为固定签名调用，保留覆盖标志与实际创建名称，不再尝试多种写入参数组合；实际板块写入仍待终端验证。 |
| `add_sector` | 添加自定义板块及其证券列表 | ❌ 条件待验证 | 仅转发终端同名函数。 |
| `remove_stock_from_sector` | 从板块中移除指定证券 | ✅ 部分适配 | 已将列表拆成大 QMT 单证券删除，全部成功才返回 `True`；部分失败仍处理剩余证券。非原子操作，异常可能发生在部分修改之后，不提供回滚。 |
| `remove_sector` | 删除指定自定义板块 | ❌ 条件待验证 | 仅转发终端同名函数。 |
| `reset_sector` | 用新证券列表替换板块成分 | ✅ 已适配 | 已映射大 QMT `reset_sector_stock_list(sector, stock_list)`，保留布尔结果，支持空列表；调用前校验列表，不进行写入重试。 |
| `get_index_weight` | 查询指数成分及对应权重 | ❌ 未适配 | 扩展接口 `get_weight_in_index` 查询单个成分权重，不能直接替代官网的整组返回。 |
| `download_index_weight` | 更新指数成分权重数据 | ❌ 条件待验证 | 仅尝试终端对应下载函数。 |

## xtdata：官网补充提及

这些名称见于 [行情模块版本信息](https://dict.thinktrader.net/nativeApi/xtdata.html#版本信息)，本次读取的“接口说明”没有为其提供独立完整章节。保留它们是因为官网明确提及，而不是因为本机 Python 包中存在这些名称。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `get_market_data_ex` | 以扩展结构查询行情及周期数据 | ✅ 已适配 | 已映射大 QMT 扩展行情查询及六类 Level2 周期，保留逐笔整数编号和深度数组，不前值填充 Level2 数据；ETF 清单、历史主力合约等其他产品仍需分别确认。 |
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
| `cancel_order_stock_async` | 按委托编号撤单并反馈异步结果 | ✅ 已适配 | 已提供请求序号、`XtCancelOrderResponse` 转换、回报去重；桥明确拒绝时返回 `-1`。 |
| `cancel_order_stock_sysid_async` | 按柜台合同编号撤单并反馈异步结果 | ✅ 部分适配 | 已提供请求序号、市场/柜台合同号透传、`XtCancelOrderResponse` 转换和重复回报过滤；底层仍复用 QMT `cancel`，真实 `sysid` 格式需按 QMT 版本验证。 |
| `fund_transfer` | 在指定方向进行资金划拨 | ❌ 条件待验证 | 仅转发终端资金划拨函数。 |
| `sync_transaction_from_external` | 将外部成交记录导入交易系统 | ❌ 条件待验证 | 仅转发对应录入函数；此功能不是数据导出。 |

### 股票查询接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_stock_asset` | 查询账号资金及总资产 | ✅ 已适配 | 读取大 QMT 资金明细并转换为 `XtAsset`。 |
| `query_stock_orders` | 查询当日委托，可只返回可撤委托 | ✅ 已适配 | 读取委托明细，支持 `cancelable_only` 筛选并转换为 `XtOrder`。 |
| `query_stock_trades` | 查询当日成交记录 | ✅ 已适配 | 读取成交明细并转换为 `XtTrade`。 |
| `query_stock_positions` | 查询账号证券持仓 | ✅ 已适配 | 读取持仓明细并转换为 `XtPosition`。 |
| `query_position_statistics` | 查询期货持仓的汇总统计 | ✅ 已适配 | 已接入 `get_trade_detail_data(account_id, 'future', 'position_statistics')` 并转换为 `XtPositionStatistics`；校验期货账号类型，保留无数据和空列表的区别。 |

### 信用查询接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_credit_detail` | 查询信用账号资产及融资融券资金情况 | ✅ 部分适配 | 使用 `get_trade_detail_data(account_id, "credit", "account")`；SDK 同步及 async 返回 `XtCreditDetail` 列表或 `None`。映射总负债和市值别名，校验账号及信用类型；缓存不含的官网字段列入 `cfquant_missing_fields`，不主动发起柜台异步刷新。 |
| `query_stk_compacts` | 查询融资融券负债合约 | ✅ 部分适配 | 优先调用 `get_unclosed_compacts(account_id, "CREDIT")`，函数缺失时兼容旧 `get_debt_contract(account_id)`，返回 `StkCompacts` 列表或 `None`。映射官网合约、数量、余额、息费字段；旧接口缺失的字段不补零，不混入已了结合约。 |
| `query_credit_subjects` | 查询融资融券业务的标的证券 | ✅ 部分适配 | 已使用 `get_assure_contract(account_id)` 返回 `CreditSubjects`，映射融资融券状态和比例；保留底层全部标的和状态，不推断未提供的字段，与原版标的范围仍待核对。 |
| `query_credit_slo_code` | 查询可用于融券的证券及相关信息 | ✅ 部分适配 | 已使用 `get_enable_short_contract(account_id)` 返回 `CreditSloCode`，映射可融数量及普通/专项来源；不同柜台的券源覆盖、来源语义仍待实测。 |
| `query_credit_assure` | 查询担保证券及担保品信息 | ✅ 部分适配 | 已使用 `get_assure_contract(account_id)` 返回 `CreditAssure`，映射担保状态及折算比例；保留底层全部记录，终端返回范围仍待核对。 |

### 其他查询接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_new_purchase_limit` | 查询账号可用的新股申购额度 | ✅ 部分适配 | 优先固定调用 `get_new_purchase_limit(account_id)`，不再先把账号字典传给此大 QMT 函数；保留终端字典，市场键和额度范围仍待实测。 |
| `query_ipo_data` | 查询当日可申购的新股和新债 | ✅ 部分适配 | 优先固定无参数调用大 QMT `get_ipo_data()`；保留终端字典，返回字段完整性仍待实测，不等价于历史新股资料查询。 |
| `query_account_infos` | 查询可使用的资金账号信息 | ❌ 条件待验证 | 仅尝试终端账号查询函数；尚未统一转换为 `XtAccountInfo`。 |
| `query_account_status` | 查询资金账号当前状态 | ❌ 条件待验证 | 仅尝试终端账号状态查询函数，结果未统一规范。 |
| `query_com_fund` | 查询划拨业务中普通柜台的资金 | ✅ 部分适配 | 当前复用大 QMT 账号资金明细，尚未保证区分官网所述普通柜台资金。 |
| `query_com_position` | 查询划拨业务中普通柜台的持仓 | ✅ 部分适配 | 当前复用大 QMT 持仓明细，尚未保证区分官网所述普通柜台持仓。 |
| `export_data` | 按数据类型和时间范围导出数据文件 | ❌ 条件待验证 | 仅转发同名函数，文件生成及字段依赖终端实现。 |
| `query_data` | 借助导出流程查询指定业务数据 | ❌ 条件待验证 | 当前仅转发查询函数，没有独立实现官网所述导出、读取、删除文件流程。 |

### 约券相关接口

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `smt_query_quoter` | 查询可申请的券源及报价 | ❌ 条件待验证 | 校验信用账号及字典列表返回结构；仍需终端提供券源查询扩展函数，内置 API 未提供可确认的对应入口。 |
| `smt_negotiate_order_async` | 提交库存券约券申请并接收反馈 | ❌ 条件待验证 | 仅支持扩展 `smt_negotiate_order` 返回明确业务结果的终端，经交易事件派发回报并关联本地 seq；仅有受理编号时报告结果未知，不伪造成功、不重试提交。调用仍等待扩展函数返回，不等价于原生异步受理及后续回报协议。 |
| `smt_query_compact` | 查询已形成的约券合约 | ❌ 条件待验证 | 校验信用账号及字典列表返回结构；仍需终端提供约券合约查询扩展函数。 |

## XtQuantTrader：官网补充提及

来源：交易文档的 [创建策略示例](https://dict.thinktrader.net/nativeApi/xttrader.html#创建策略)及 [开启主动请求接口的专用线程](https://dict.thinktrader.net/nativeApi/xttrader.html#开启主动请求接口的专用线程)备注。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `query_stock_order` | 按委托编号查询一笔委托 | ✅ 已适配 | 官网快速入门示例使用；cfquant 从委托列表匹配目标委托。 |
| `query_stock_position` | 查询指定证券的持仓 | ✅ 已适配 | 官网快速入门示例使用；cfquant 从持仓列表匹配证券代码。 |
| `query_stock_orders_async` | 通过回调取得委托查询结果 | ✅ 部分适配 | 官网专用线程章节备注提及；已改为后台查询、立即返回请求序号，独立线程按查询顺序派发回调。属于 cfquant 异步适配，不保证原版底层调度与专用响应线程开关语义。 |

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
| `on_order_stock_async_response` | 接收异步报单请求对应的委托结果 | ✅ 已适配 | 已实现请求序号与委托回报关联；独立应答缺失时，SDK可从匹配的委托事件补发，不等同于原生应答已经送达。 |
| `on_smt_appointment_async_response` | 接收约券申请等异步业务反馈 | ❌ 条件待验证 | 已接入桥交易事件并转换 `XtSmtAppointmentResponse`，仅派发具有 success、msg、apply_id 的业务回报；终端原生 SMT 回调协议尚未接入，不能将请求受理应答当成业务回报。 |

## 官网交易数据结构及账号对象

来源：[XtQuant数据结构说明](https://dict.thinktrader.net/nativeApi/xttrader.html#xtquant数据结构说明)，另含官网快速入门使用的 `StockAccount`。这些条目是输入或返回对象，不计入前面的函数数量；只返回字典不等于已适配官网的对象属性访问。

| 原版接口 | 功能释义 | 适配 | 适配情况 |
| --- | --- | --- | --- |
| `StockAccount` | 指定资金账号及账号类型 | ✅ 已适配 | 已提供账号对象，并扩展桥路由信息。 |
| `XtAsset` | 表示现金、冻结资金、市值和总资产 | ✅ 已适配 | 已实现常用资金字段映射。 |
| `XtOrder` | 表示委托编号、价格、数量和状态 | ✅ 已适配 | 已实现常用字段映射；查询与回调统一转换有明确对应关系的价格枚举，例如大 QMT限价50转SDK限价11，保留原始字段；无法唯一映射的市价类型不猜测。 |
| `XtTrade` | 表示成交证券、价格、数量及关联委托 | ✅ 已适配 | 已实现常用成交字段映射。 |
| `XtPosition` | 表示持仓数量、可用数量、成本和市值 | ✅ 已适配 | 已实现常用持仓字段映射。 |
| `XtPositionStatistics` | 表示期货持仓汇总及相关统计 | ✅ 已适配 | 已映射官网对应的持仓、成本、盈亏、保证金等字段，包含旧拼写 `m_nYestodayPosition`，缺失字段不补零。 |
| `XtOrderResponse` | 表示异步报单的请求序号和委托编号 | ✅ 已适配 | 已提供对象及请求序号、委托关联字段。 |
| `XtCancelOrderResponse` | 表示异步撤单请求的处理结果 | ✅ 已适配 | 已提供对象及常用撤单结果字段转换。 |
| `XtOrderError` | 表示报单失败的编号和原因 | ✅ 已适配 | 已提供对象及错误字段转换。 |
| `XtCancelError` | 表示撤单失败的委托标识和原因 | ✅ 已适配 | 已提供对象及错误字段转换。 |
| `XtCreditDetail` | 表示信用账号资产、负债和额度 | ✅ 部分适配 | 已提供专用对象及官网字段映射，缓存未提供的字段保持缺失；缓存的已用额度与官网同名冻结额度语义不同，保存在 `cfquant_qmt_fields` 中。 |
| `StkCompacts` | 表示融资融券负债合约 | ✅ 已适配 | 已提供专用对象，映射官网合约字段及原样拼写 `businessFare`，保留合约编号字符串及缺失字段；旧终端可提供的字段范围仍取决于源接口。 |
| `CreditSubjects` | 表示融资融券标的及其业务属性 | ✅ 已适配 | 已映射账号、市场枚举、证券代码、融资融券状态和保证金比例，保留缺失字段的缺失状态。 |
| `CreditSloCode` | 表示可融券证券及可用券源信息 | ✅ 已适配 | 已映射账号、市场枚举、证券代码、可融数量及头寸来源，不填充已被内置接口移除的比例字段。 |
| `CreditAssure` | 表示担保证券及担保品属性 | ✅ 已适配 | 已映射账号、市场枚举、证券代码、担保状态和折算比例。 |
| `XtAccountStatus` | 表示账号及当前连接状态 | ✅ 部分适配 | 目前为通用属性对象，未实现专用字段规范化。 |
| `XtAccountInfo` | 表示账号类型、账号标识等账号资料 | ❌ 未适配 | 目前未提供对应专用对象及字段映射。 |
| `XtSmtAppointmentResponse` | 表示约券业务请求的异步反馈 | ✅ 已适配 | 已映射 seq、success、msg、apply_id 及扩展终端字段别名，不填充虚构结果；对象映射不代表终端约券业务已可用。 |

## 信用查询的字段边界

- 五类信用查询统一验证 `CREDIT` 类型及返回账号。SDK 返回对应对象列表，Web 返回对象字段的 JSON 列表；`None` 与空列表分别保留。记录带有 `cfquant_source` 和 `cfquant_missing_fields`，用于识别来源及缺失的官网字段。
- [大 QMT 缓存信用结构](https://dict.thinktrader.net/innerApi/data_structure.html)的 `m_dTotalDebit`、`m_dInstrumentValue` 分别映射为 `m_dTotalDebt`、`m_dMarketValue`。缓存 `m_dFinUsedQuota`、`m_dSloUsedQuota` 表示已用额度，官网同名字段定义为冻结额度，因此缓存值放入 `cfquant_qmt_fields`，不直接充当官网字段。
- [大 QMT 交易函数](https://dict.thinktrader.net/innerApi/trading_function.html)的 `get_unclosed_compacts` 用于未了结负债；旧 `get_debt_contract` 缺少的息费字段不通过本金或利息猜算。`query_credit_account` 的柜台刷新及其回调尚未接入，当前资金明细来自终端缓存。
- 约券申请、撤销、提前归还和展期统一使用上述结果校验。未提供对应扩展 callable 的终端会明确报未支持；整数受理编号不能证明成功，结果未知时需先核对柜台记录再决定是否重试。
- 信用回归见 [信用兼容测试](../cfquant/tests/test_credit_compat.py)，覆盖四类共用桥、同步及异步对象、空结果、账号校验和模拟约券业务回报；不执行真实约券、撤销或还款。2026-09-10 在本机信用模拟终端重启后，五类 Web 查询及 SDK 同步、异步共十项调用通过；全部记录账号和字段标记校验通过，负债编号及息费映射核验通过。信用资金仍有十个官网字段因缓存缺失或语义不同而保持缺失；本次结果不保证其他券商的范围及权限。

## 使用边界与维护依据

- 高级模式下，低延迟只读 `xtdata` 请求默认交易桥优先、普通桥回退；订阅、反订阅、下载及携带回调的请求走普通桥。路由改变不会补出终端本来没有的函数。
- 条件入口必须在目标终端确认函数存在，并核对官网参数、返回字段和回调行为后，才能改为已适配。仅成功导入、存在同名方法、通过本地 mock 测试，均不足以确认条件接口可用。
- Level2 的 `l2quote/l2quoteaux/l2order/l2transaction/l2transactioncount/l2orderqueue` 已实现查询和原生订阅适配，仍需终端支持和行情权限。千档是独立能力：三个千档入口仅在存在真实 callable 时转发，不能用一档队列替代，继续标为条件待验证。ETF 清单、期权及投研特色数据不因本次改动变为已适配。
- 股票资金、委托、持仓、成交及兼容层只读 `query_*_async` 已使用后台查询和独立回调线程，立即返回请求序号。包含三类新增两融查询；底层QMT能力和对象转换限制不因此消失。查询或回调异常记录到 `cfquant.xttrader` 日志，不伪造成功结果；停止后未开始的旧任务及旧结果不再派发，已经进入的回调可以执行完毕。
- 本批自动化验证见 [大QMT接口适配测试](../cfquant/tests/17_大QMT接口适配测试.py)，未执行真实板块修改。升级信用对象及桥模块后需完整退出并重启 QMT 进程，同时重启使用 SDK 的外部 Python 进程；仅重启网页或重新运行策略不能保证替换已加载的模块。官网后续增加或更名的接口，应以官网章节为依据更新清单，不再通过枚举 Python 包自动扩大统计范围。
- 核对入口：[行情兼容层](../cfquant/xtdata.py)、[交易兼容层](../cfquant/xttrader.py)、[交易数据对象](../cfquant/xttype.py)、[QMT 桥能力映射](../cfquant/tx_trade_bridge.py)、[服务端路由](../cfquant_web_server.py)。更详细的大 QMT 能力边界见 [QMT函数封装能力清单](QMT函数封装能力清单.md)。
