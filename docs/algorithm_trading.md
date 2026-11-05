# cftrader 算法交易与共享全推行情

`CfQuantTrader` 提供 TWAP、基础 VWAP 和 POV 执行接口。算法任务运行在 `cfquant_web_server.py` 服务中，自动使用项目共享全推行情，用户无需先调用 `xtdata.subscribe_whole_quote()`。

现在还提供止盈止损、定时 / 持仓期限退出、回撤 / 保本 / 阶梯保护，以及按风险金额、风险比例和资金分配计算仓位的接口。完整参数、保护组和“预览 → 提交 → 保护成交数量”的用法见 [条件单、仓位计算与下单计划](conditional_orders.md)。

网页入口：在 8765 控制台的“接口 → 算法交易 · TWAP / VWAP / POV”或“文档 → 接口分类 → 算法交易”查看各方法的 Python / HTTP 示例；在“教程 → 算法交易 · TWAP / VWAP / POV”阅读完整教程，包含三种算法和任务管理的可复制示例。文档页和 Python API 参考中的算法方法也可直接跳转到此教程。

## 行情只订阅一份

同一服务实例、同一已配置行情源下，Web 行情页、行情诊断、通过 Web LTtx 接入的 SDK 订阅和算法任务复用一个上游全推订阅、一份最新行情缓存。默认覆盖 SH、SZ、BJ。每个使用者持有独立订阅 ID 或内部引用，取消用户订阅不会中断仍在运行的算法。

QMT 桥接层也合并全推请求，普通全推、诊断和内部全推使用同一个原生订阅。已有直连 SDK 的全推请求也能在同一个 QMT 桥接实例内复用原生订阅；若直连另一台 QMT 或启动另一套服务，则不属于同一行情源，无法跨实例合并。算法接口始终连接 Web 执行服务。

- 第一个使用者到来时订阅；最后一个使用者离开后等待 5 秒再退订，避免频繁开关。
- 多个算法读取同一缓存；行情增量按证券合并，缓存保留接收时间、行情时间和连接代次。
- 订阅范围扩大时先退旧订阅再订新订阅，期间暂停基于旧行情下单；不会同时保留两条上游订阅。
- 已有活动使用者时固定行情源，冲突的来源请求报错。不会因订阅回包超时而盲目切换另一行情源重复订阅。
- 新版 SDK 每 10 秒续租；异常退出后约 45 秒加检查周期释放其引用。正常 `close_client()` 或进程退出会主动释放。算法引用由服务管理，不依赖调用者心跳。
- 服务定期检查原生订阅，发现连接丢失会清空旧缓存并恢复订阅。SDK 自身与服务之间长时间断开、服务重启导致 SDK 引用过期时，调用方需要重新订阅；持久化算法任务会自行恢复引用。
- 用户回调在各自的线程中处理，缓慢回调只保留待处理证券的最新值；诊断保留一个待处理完整批次。它们是快照流，不保证逐笔行情不丢失。

## 三种算法

| 算法 | 数量计划 | 数据依赖 |
| --- | --- | --- |
| TWAP | 按有效交易时间均匀分配，在每个时间片开始时尝试执行该片数量 | 新鲜行情、交易日历、证券规则 |
| VWAP | 按历史分钟成交量曲线或调用方给定的权重分配 | TWAP 的数据，加历史分钟量或 `volume_profile` |
| POV | 按启动后观察到的市场成交量增量乘参与率分配 | 新鲜行情中的累计成交量 |

基础 VWAP 的目标是跟随成交量分布，不保证成交价格等于市场 VWAP。POV 的 `participation_rate=0.1` 表示观察到的市场成交量增量的 10%；该口径包含市场行情中的自身成交。启动、恢复以及行情连接代次变化时重新建立基准，不追赶断线期间无法确认的成交量。

## Python 调用

先启动新版 Web 服务及对应的新版 QMT 脚本，配置可用的行情账号和交易账号。下列代码默认只展示用法；开启后会提交交易任务。

```python
from cfquant import cftrader, xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

ENABLE_TRADING = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
trader = XtQuantTrader("", 0)
orders_api = cftrader.CfQuantTrader(trader)

if ENABLE_TRADING:
    algo_id = orders_api.order_twap(
        account, "600000.SH", xtconstant.STOCK_BUY,
        order_volume=1000, limit_price=10.00,
        duration_seconds=600, interval_seconds=60,
        max_child_volume=200,
        request_key="my-strategy-20261103-buy-001",
    )
    print(orders_api.query_algo(algo_id))
    # orders_api.pause_algo(algo_id)
    # orders_api.resume_algo(algo_id)
    # orders_api.cancel_algo(algo_id)
    print(orders_api.list_algos(account))
else:
    print("Preview only; trading is disabled")
```

替换创建方法即可选择另一个算法：

```python
from cfquant import cftrader, xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

ENABLE_TRADING = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
orders_api = cftrader.CfQuantTrader(XtQuantTrader("", 0))

if ENABLE_TRADING:
    vwap_id = orders_api.order_vwap(
        account, "600000.SH", xtconstant.STOCK_BUY, 1000, 10.00,
        duration_seconds=600, interval_seconds=60,
        volume_profile=[5, 3, 2],  # 三个等长有效交易时间段，归一化为 50%、30%、20%
        request_key="my-vwap-001",
    )
    pov_id = orders_api.order_pov(
        account, "000001.SZ", xtconstant.STOCK_SELL, 1000, 9.00,
        participation_rate=0.1, duration_seconds=600,
        interval_seconds=10, max_child_volume=200,
        request_key="my-pov-001",
    )
```

`order_algo(account, stock_code, order_type, order_volume, algo, limit_price, duration_seconds=3600, interval_seconds=60, **options)` 是统一入口，返回持久化的 `algo_id`。创建回包丢失时，用**相同账号、相同参数和相同 `request_key`**重试会返回原任务；同一个 key 搭配不同参数会报错。省略 key 时 SDK 每次调用生成一个新 key，因此调用方要实现跨调用重试时应自行提供稳定 key。

| 参数 | 默认值 / 说明 |
| --- | --- |
| `limit_price` | 必填；买单最高价、卖单最低价，所有子单均为限价单 |
| `duration_seconds` | 3600；有效交易时间，不计午休，须能放进当日可用时段 |
| `interval_seconds` | 60；最小子单提交间隔，也是 TWAP 时间片长度 |
| `start_time` / `end_time` | Unix 秒或 ISO 时间字符串；未带时区按北京时间；可明确指定结束时刻，届时以起止窗口为准 |
| `sessions` | 默认 09:30–11:30、13:00–14:57，跳过午休和尾盘集合竞价；自定义时传 `[["09:30", "11:30"], ["13:00", "14:57"]]` |
| `max_child_volume` | 默认母单总量；限制每笔子单最大量 |
| `child_timeout_seconds` | 60；子单超时请求撤单，确认结果后再决定是否补量 |
| `max_quote_age` | 15 秒；同时检查本地接收时间和行情时间，行情过期停止新增子单 |
| `price_mode` | `opponent` 对手一档；可选 `passive` 本方一档或 `limit` 直接使用限价，均受限价边界约束 |
| `volume_profile` | VWAP 可选非负权重列表，至少一项为正；覆盖等长有效交易时间段 |
| `lookback_days` | VWAP 默认取已有历史中的最近 20 个交易日；不包含执行日。没有合适的历史分钟量时拒绝创建，需先下载数据或提供曲线 |
| `participation_rate` | POV 必填，范围 `(0, 1]` |
| `volume_multiplier` | 默认 100，将股票行情 `volume` 的手数换算为股；其他数据源或品种须显式确认并调整 |
| `price_tick` | 默认读取证券 `PriceTick`，也可显式指定 |
| `min_child_volume` / `volume_step` | 普通 A 股默认 100/100；科创板 200/1；北交所 100/1；其他品种须显式指定并核实交易规则 |
| `strategy_name` / `order_remark` | 前者作为子单策略名称；后者保存在母单请求中，子单备注由引擎生成唯一标识用于恢复核对 |

首版适配 SH/SZ/BJ 股票或信用账号的普通买卖（23/24）；融资融券专用指令、港股通、期货和跨日执行未纳入此适配器。不自动拆出违反最小数量规则的尾单；部分成交形成的不可提交余量可能在到期时保留未完成状态。

## 生命周期与结果

`query_algo(algo_id, account=None)` 返回母单、配置、子单记录、`filled_volume`、`remaining_volume`、`reserved_volume`、`average_price` 和 `last_error`。`list_algos(account=None)` 返回该账号的任务列表。当前 SDK 实例能记住新建任务的账号；新进程查询或控制已有任务时显式传 `account`，或使用 trader 已绑定的账号。

- `WAITING_MARKET` / `WAITING_SESSION`：等待新鲜行情或交易时段。
- `RUNNING`：按计划执行，仍受资金、可卖持仓、限价和数量约束。
- `PAUSED`：停止新增子单并请求撤销已有子单。恢复后仍等待未确认撤单完成；原截止时间不顺延。
- `CANCELLING`：已要求撤销母单，或已到期，但子单结果尚未全部确认。
- `COMPLETED` / `CANCELLED` / `EXPIRED` / `FAILED`：终态。成交量仍以实际成交统计为准，不等于每个终态都完成了目标量。

子单发送前持久化意图。下单回包丢失后保留未知状态及全部未成交占用量，按唯一备注核对券商委托，不自动重发。撤单请求成功也不代表已经撤成；需要委托查询确认。若券商查询已无法返回原订单，任务会保留未知占用并停止继续执行，需人工核对实际委托。

任务保存在运行目录的 `algorithm_tasks.sqlite3`，同一个数据库只允许一个执行引擎持有。服务重启后先核对委托再恢复；调用脚本退出或 `trader.stop()` **不会撤销母单**。需要停止任务时调用 `cancel_algo()`。服务停止期间无法继续调度，但已经发到券商的子单仍可能成交。

## HTTP 接口

通过现有 Web 服务访问以下 POST 接口，沿用服务已有的访问控制和返回格式：

| 路径 | JSON 参数 |
| --- | --- |
| `/api/trade/algo/submit` | `account` 账号字典，以及统一创建入口的参数 |
| `/api/trade/algo/query` | `account`、`algo_id` |
| `/api/trade/algo/list` | `account` |
| `/api/trade/algo/pause` | `account`、`algo_id` |
| `/api/trade/algo/resume` | `account`、`algo_id` |
| `/api/trade/algo/cancel` | `account`、`algo_id` |

共享行情、时间分片、异常恢复和接口测试使用本地假 QMT/假券商运行，不会下真实订单。接入具体券商前仍需在其模拟环境验证成交量单位、申报数量限制、委托字段和实际行情时效。
