# Level2 行情适配说明

更新时间：2026-09-10

## 功能范围

本次按 [原生行情文档](https://dict.thinktrader.net/nativeApi/xtdata.html)的数据周期和 [大 QMT 行情函数](https://dict.thinktrader.net/innerApi/data_function.html)、[官方 Level2 查询与订阅示例](https://dict.thinktrader.net/innerApi/code_examples.html)实现，不再仅尝试同名函数。下表的“已适配”表示代码已实现并通过离线协议回归，不代表当前券商已开通行情权限。

| 数据周期 | 功能释义 | 查询 | 实时订阅与回调 |
| --- | --- | --- | --- |
| `l2quote` | Level2 十档行情快照 | ✅ 已适配 | ✅ 已适配 |
| `l2quoteaux` | 行情补充，包括总买总卖与撤单汇总 | ✅ 已适配 | ✅ 已适配 |
| `l2order` | 逐笔委托及委托方向、类型 | ✅ 已适配 | ✅ 已适配 |
| `l2transaction` | 逐笔成交及买卖委托关联编号 | ✅ 已适配 | ✅ 已适配 |
| `l2transactioncount` | Level2 大单统计，大 QMT 示例明确提供 | ✅ 已适配 | ✅ 已适配 |
| `l2orderqueue` | 最优买卖价的一档委托队列 | ✅ 已适配 | ✅ 已适配 |

这些数据统一通过 `get_market_data_ex(..., period=...)` 查询，通过 `subscribe_quote(..., period=..., callback=...)` 或 `subscribe_quote2` 订阅，使用 `unsubscribe_quote` 退订。证券代码不设本地白名单，是否有对应市场、证券和数据权限由 QMT 决定。

## 接口对应

| SDK 入口 | 大 QMT 来源 | 返回或回调格式 |
| --- | --- | --- |
| `get_market_data_ex`，上述六个周期 | `ContextInfo.get_market_data_ex` | `{证券代码: pandas.DataFrame}` |
| `get_l2_quote` | `get_market_data_ex` 的 `l2quote` | 单证券结构化 `numpy.ndarray`，无证券数据时为 `None` |
| `get_l2_order` | `get_market_data_ex` 的 `l2order` | 同上 |
| `get_l2_transaction` | `get_market_data_ex` 的 `l2transaction` | 同上 |
| `subscribe_quote` / `subscribe_quote2` | `ContextInfo.subscribe_quote`，实际传递周期、复权参数与 `result_type='dict'` | 回调统一为 `{证券代码: [记录字典, ...]}` |
| `unsubscribe_quote` | `ContextInfo.unsubscribe_quote` | 使用桥订阅号查找真实 QMT 订阅号并释放，不只是删除 Python 回调 |

三个 `get_l2_*` 入口的参数顺序为 `field_list, stock_code, start_time, end_time, count`。字段过滤、时间区间和条数交给 QMT 查询；`field_list=[]` 保留终端返回的字段，不自行拼造缺失字段。空表保持空表/空数组，`None` 不转换成有效行情。

SDK 的这些兼容入口是使用方式说明，不额外算作官网“接口说明”章节中的独立接口数量。功能覆盖以六个真实数据周期为准。

## 千档边界

| 入口 | 功能释义 | 状态 |
| --- | --- | --- |
| `subscribe_l2thousand` | 千档盘口订阅 | ❌ 条件待验证：已接入原生函数转发、回调及退订，但要求终端实际暴露该 callable |
| `subscribe_l2thousand_queue` | 按档位或价格范围订阅千档委托队列 | ❌ 条件待验证：同上 |
| `get_l2thousand_queue` | 查询千档委托队列 | ❌ 条件待验证：同上 |

[官方版本说明](https://dict.thinktrader.net/nativeApi/download_xtquant.html)提及千档队列接口，但当前大 QMT 内置 Python 文档没有可确认的等价入口。普通 `l2orderqueue` 只有一档队列，不能替代千档；缺少原生 callable 时明确报能力不足，不会回退到普通 tick、十档或一档队列并声称成功。

千档队列的 `price` 列表表示多个指定价格，元组表示价格区间，RPC 往返保留二者区别。订阅时 `gear_num` 与 `price` 不能同时指定。终端暴露函数只是必要条件，其权限、真实字段和推送完整性仍需单独验证。

## 数据与回调

- 不将逐笔编号先转换为浮点数，避免大整数精度丢失；盘口和队列数组保留为数组内容。SDK 查询和回调通过 Python 协议往返验证，网页 JavaScript 数字展示不在此精度保证范围内。
- 不补齐不存在的档位，不用前值填充 Level2 记录，不换算源数据的价格或数量单位；字段单位和枚举以对应终端数据字典为准。
- 不按时间戳去重，保留同一毫秒内多笔记录及源顺序。
- SDK 在发送订阅请求前登记唯一回调事件，桥缓冲订阅建立过程中的首包，Web 路由也提前登记接收方。失败订阅清理回调；退订失败则保留订阅供重试；成功退订后忽略迟到事件。
- Web 为外部 SDK 分配独立订阅号，记录建立订阅时的桥、通道与通信模式。不同数据源的相同 QMT 订阅号不会互相覆盖；退订定向发送给原始桥，不重新选择其他数据源。
- 回调应快速返回，耗时处理放入自己的队列。首包保护不等于断线重放或保证行情零丢包；底层网络、终端缓存与权限仍影响接收结果。
- `start_time/end_time/count` 非默认值时，订阅前先请求相应历史缓存；不伪造历史回调，也不承诺大 QMT 与 MiniQMT 的补历史推送时序完全相同。普通查询时间字符串使用 QMT 的 `YYYYMMDD` 或 `YYYYMMDDHHMMSS` 格式。
- Level2 是独立数据产品。`download_history_data` 不因此获得所有 Level2 历史下载能力；过往交易日缓存、非交易时间空结果和千档权限须另行确认。

## 模式与升级

高级模式、通用模式、极致模式三份自包含入口（含 SH/SZ 分市场版本）和旧 `CfquantQmtBridge` 已同步本次 Level2 逻辑。

高级模式的 `get_l2_*`、`get_market_data_ex` 和 `get_full_tick` 等只读请求保持交易桥优先、普通桥回退；订阅、退订及携带回调的请求走普通桥，不增加实时 tick 的普通桥绕行。

升级时同步 SDK、Web 服务和 QMT 入口/核心文件。重启 Web 后，需要退出并重新启动 QMT 进程及外部 Python 进程，避免旧模块缓存；极致模式应重新部署所用的 LITE 文件。只刷新网页不能替换正在运行的桥代码。

## 验证

离线回归：[28_Level2接口适配测试.py](../cfquant/tests/28_Level2接口适配测试.py)。使用模拟 QMT 与真实协议编解码，覆盖六周期、字段/编号/数组、首包、退订、千档能力边界、模式路由和 LITE 内嵌代码，不连接交易账号。

本次连同普通行情、安装、交易兼容及文档等离线回归共 638 项通过、7 项跳过。跳过项是纯交易桥的订阅用例，订阅由普通桥负责，不代表缺失七个数据功能。另通过 SDK Python 3.8、三份 GBK LITE Python 3.6 语法检查及网页 JavaScript 语法检查。

只读实测：[29_Level2行情测试.py](../cfquant/tests/29_Level2行情测试.py)。修改文件顶部“用户配置区”后直接运行，分别记录查询、有效回调、异常数据和退订结果，报告写入 `log/`。默认不测试千档，可按终端能力打开开关；脚本不包含下单、撤单或资金操作。

实机验收需要开通对应行情源并在有行情的时段执行。订阅号正常但查询为空、观察期内无回调，应记录为“待确认”，不能当作行情接收通过。本次开发只完成离线验证，未重启用户终端或执行实盘行情验收。
