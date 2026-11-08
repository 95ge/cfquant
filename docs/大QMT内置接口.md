# 大 QMT 内置接口：QmtInnerApi

`from cfquant import QmtInnerApi` 提供独立的大 QMT 内置接口会话，不依赖 `XtQuantTrader` 实例。分类依据 [迅投内置 Python 文档](https://dict.thinktrader.net/innerApi/start_now.html)，函数名、参数顺序、交易枚举和原始字段沿用内置接口。

## 分类与入口

网页左侧“接口”页只有一个“大 QMT 内置接口”顶层分组，展开后再按系统与会话、行情与数据、交易、交易回调、扩展数据与因子细分。“教程 → Python 接入”的 API 目录使用相同层级，可搜索 `QmtInnerApi` 或原生函数名。目录更新后刷新网页即可看到，无需为文档更新重启服务或 QMT。网页提供参数、原生原型、官方来源及可复制示例，当前这些入口通过外部 Python 调用。

| 文档分类 | 外部对象 | 示例 |
| --- | --- | --- |
| [系统函数](https://dict.thinktrader.net/innerApi/system_function.html) | `qmt.system` / `QmtSystem` | `is_last_bar`、`schedule_run`、`get_stock_name`、`create_sector` |
| [行情函数](https://dict.thinktrader.net/innerApi/data_function.html) | `qmt.market` / `QmtMarket` | `get_market_data_ex`、`get_full_tick`、`get_financial_data`、`get_option_list` |
| [交易函数](https://dict.thinktrader.net/innerApi/trading_function.html) | `qmt.trade` / `QmtTrade` | `passorder`、`cancel`、`get_trade_detail_data`、`get_unclosed_compacts` |
| [成交回报实时主推函数](https://dict.thinktrader.net/innerApi/callback_function.html) | `qmt.callbacks` / `QmtCallbacks` | `account_callback`、`order_callback`、`deal_callback`、`orderError_callback` |
| [引用函数中的扩展数据与因子](https://dict.thinktrader.net/innerApi/quote_function.html) | `qmt.reference` / `QmtReference` | `ext_data`、`ext_data_rank`、`get_factor_value`、`get_factor_rank` |

当前保留 80 个原生方法（系统 13、行情 36、交易 25、扩展数据与因子 6）和 8 个交易回调注册入口，另提供 3 个会话管理文档条目。`set_account`、`set_universe`、`get_universe` 归入系统类，便于管理账号订阅和证券池。`dir(qmt.market)` 等可查看对应方法；`qmt.capabilities()` 在 QMT 内只探测函数是否存在，不实际调用交易或修改数据。

## 纳入范围

本接口面向外部 Python 的数据查询、研究和实盘交易。2026-11-06 从最初的完整候选清单中移除了下列 31 个方法；Python 类、桥接调用白名单、能力列表和网页目录同步收敛。

| 不纳入的用途 | 移除方法 | 理由与替代方式 |
| --- | --- | --- |
| 指标属性与图表绘制 | `set_output_index_property`、`paint`、`draw_text`、`draw_number`、`draw_vertline`、`draw_icon` | 操作 QMT 图表显示，不属于外部数据与交易调用。 |
| K 线事件状态 | `is_last_bar`、`is_new_bar`、`get_bar_timetag` | 对应桥接策略的 K 线驱动状态；外部策略使用订阅行情的时间和回调。 |
| 按 QMT 脚本函数名定时 | `run_time` | 依赖 QMT 脚本内已定义的函数；外部回调统一使用可清理的 `schedule_run`。 |
| 仅回测可用的委托函数 | `order_lots`、`order_value`、`order_percent`、`order_target_value`、`order_target_percent`、`order_shares`、`buy_open`、`buy_close_tdayfirst`、`buy_close_ydayfirst`、`sell_open`、`sell_close_tdayfirst`、`sell_close_ydayfirst` | 桥接会话不提供外部回测引擎；原生实盘委托保留 `passorder` 等入口。 |
| 模型与 VBA 执行 | `subscribe_formula`、`unsubscribe_formula`、`call_formula`、`call_formula_batch`、`call_vba`、`get_vba_func_result` | 依赖终端模型配置和执行环境，当前不维护这类远程模型功能。 |
| 已有替代的旧行情入口 | `get_history_data`、`get_market_data` | 使用 `get_market_data_ex` 获取结构更统一的行情结果。 |
| 已弃用的负债查询 | `get_debt_contract` | 使用 `get_unclosed_compacts` / `get_closed_compacts` 查询负债合约。 |

保留 `get_local_data`，因为它提供只读取 QMT 本地行情的语义；使用前需要完成数据下载。保留扩展数据和因子读取，因为它们可用于外部选股、排序和研究，但需要终端已配置相应数据，K 线偏移仍相对于桥接策略上下文。终端暂时缺失某个有用接口，不等于该接口应被删除，例如历史交易明细查询仍保留并按能力表报错。

## 接入与查询

先更新 cfquant 核心及 QMT 入口脚本，再重新运行桥接策略。通用入口、高级模式普通入口，以及三个 Lite 单文件入口均包含分发/回调支持。旧的运行中脚本不会因外部包更新而自动获得新接口。

示例中的 `YOUR_ACCOUNT_ID` 是占位符，请替换为 cfquant 网页“账号绑定”中登记的券商资金账号，以字符串传入并保留前导零。例如，绑定中的资金账号是 `12345678`，则填写 `account_id="12345678"`（此号码仅为格式示例）。`account_id` 也可以省略；省略时 Web 路由使用当前设置的行情源。`account_type` 应与该绑定一致：普通证券账户填 `"STOCK"`，信用账户填 `"CREDIT"`。

这些账号路由参数在创建 `QmtInnerApi(...)` 时设置，之后调用 `qmt.market.get_bvol(...)` 等方法共用此账号绑定。接口页面和 Python API 目录中的每个内置接口都提供这段账号说明。

```python
from cfquant import QmtInnerApi

# YOUR_ACCOUNT_ID 替换为“账号绑定”中的券商资金账号
with QmtInnerApi(account_id="YOUR_ACCOUNT_ID", account_type="STOCK") as qmt:
    print(qmt.capabilities()["market"]["get_market_data_ex"])
    ticks = qmt.market.get_full_tick(["000001.SZ"])
    bars = qmt.market.get_market_data_ex(
        fields=["open", "close"], stock_code=["000001.SZ"],
        period="1d", count=10, subscribe=False,
    )
    print(bars["000001.SZ"])  # pandas.DataFrame
```

默认沿用 cfquant 的自动通信选择。可传 `transport="ctypes"`、`"lttx"`、`"web_lttx"`，也可注入已有 RPC `client`。实例仅关闭自己创建的连接。通过 Web 路由时优先按 `account_id`、`account_type`、`account_key` 选择绑定；直连时才需要用 `bridge_id` 或 `request_channel` 指定内部通道。

通过 Web 路由时，构造参数 `account_id`、`account_type`、`account_key` 用于选择绑定，路由层会自动找到对应的 `bridge_id`；`bridge_id` 只作为直连或同账号多绑定时的显式覆盖。交易函数中的 `accountid` 等参数仍需按大 QMT 文档传入。会话按账号绑定选定桥接策略，不自动换行情提供者，也不在失败后换传输重发。

## 原生参数与 ContextInfo

```python
with QmtInnerApi(account_id="YOUR_ACCOUNT", account_type="STOCK") as qmt:
    rows = qmt.trade.get_trade_detail_data("YOUR_ACCOUNT", "stock", "position")
    for row in rows:
        print(row.m_strInstrumentID, row.m_nVolume)
        print(row["m_nVolume"])  # 也支持字典访问

    dates = qmt.market.get_trading_dates("000001.SZ", "20260101", "20261105", 10, "1d")
```

交易对象保留大 QMT 的 `m_...` 字段，外部使用支持属性访问的 `QmtRecord` 字典；不转换为 `XtOrder` / `XtPosition`。DataFrame、Series 和 NumPy 数组沿用现有协议恢复。旧版 pandas.Panel 不支持跨进程传输，会明确报错；可缩小查询到单证券或采用新版数据接口。

`get_trading_dates` 沿用原生的证券代码、时间范围、数量及 K 线周期参数，结果取自内置 QMT。`get_market_data_ex` 的默认周期/复权为原生 `follow`。

调用需要 `ContextInfo` 的全局函数时，末尾的 `ContextInfo` 可省略，由桥接端补入。也可显式传 `qmt.context`；它指向当前绑定的桥接策略。

```python
# 以下仅展示参数顺序；接入有效账户后调用会提交原生委托。
# qmt.trade.passorder(23, 1101, accountid, "000001.SZ", 11, 10.0, 100,
#                     "strategy", 2, "remark")
# qmt.trade.cancel(orderId, accountid, "stock")
```

常用方法提供显式签名；其他重载接口保留 `*args, **kwargs` 转发。为兼容不同券商版本的 Boost.Python 绑定，重载参数推荐按原文档顺序传入，`passorder` 的可选参数使用位置参数。也可用 `qmt.call("trade", "algo_passorder", ...)` 调用已登记的方法。

`passorder` 返回 QMT 原始结果（通常为 `None`），不推测委托编号。查询与回调负责确认委托状态。接口错误或超时不会自动重试交易；超时后应先核对实际委托情况。

## 回调与定时器

```python
import threading
from datetime import datetime, timedelta
from cfquant import QmtInnerApi

with QmtInnerApi(account_id="YOUR_ACCOUNT_ID", account_type="STOCK") as qmt:
    qmt.system.set_account("YOUR_ACCOUNT")

    def order_callback(C, orderInfo):
        print(orderInfo.m_strOrderSysID)

    qmt.callbacks.order_callback(order_callback)
    # 等价：qmt.callbacks.register("order_callback", order_callback)
    sub_id = qmt.market.subscribe_quote("000001.SZ", period="tick", callback=print)
    task_id = qmt.system.schedule_run(
        lambda C: print(C.get_full_tick(["000001.SZ"])),
        datetime.now(), -1, timedelta(seconds=30), "external_quotes",
    )
    threading.Event().wait(60)  # 外部进程保持运行以接收推送
    qmt.market.unsubscribe_quote(sub_id)
    qmt.system.cancel_schedule_run(task_id)
    qmt.callbacks.unregister("order_callback")
```

回调运行于外部 Python 的 cfquant 回调线程。交易回调保留 `(C, 原生参数...)` 的顺序，`C` 是当前会话的 `qmt.context` 代理；行情回调接收原生数据。代理支持已登记的 ContextInfo 方法，以及 `barpos`、`stockcode`、`market`、`period` 等只读属性。每次读取会查询桥接策略当时的状态，并非事件发生时的属性快照。

支持注册 `account_callback`、`task_callback`、`order_callback`、`deal_callback`、`position_callback`、`orderError_callback`、`credit_account_callback`、`credit_opvolume_callback`。回调订阅范围是当前桥接策略接收的原生事件；多账号策略需要自行按原始账号字段筛选。旧的兼容层事件继续独立处理。

`close()` 清理本会话创建的行情订阅、`schedule_run` 定时器及外部回调。清理失败时保留状态并抛出异常，可再次 `close()`。进程被强制终止无法执行清理，需重启对应桥接策略释放遗留资源。外部 Python 定时回调使用 `schedule_run`。

默认 `QmtInnerApi` 保持原生订阅 ID 语义，不会把行情订阅写入持久化清单。默认 Web 路径下如需在 cfquant/QMT 重启后恢复行情订阅，可显式创建 `QmtInnerApi(recovery='lease')`；该模式使用 SQLite 清单和 45 秒租约，重连后按当前会话重新确认并恢复，返回的是稳定的 cfquant 逻辑 ID。数据库不会保存 Python 回调函数；外部程序自身重启后仍需重新注册回调。下单、撤单和 `schedule_run` 不进入自动恢复。

## 运行边界与维护

- 外部会话共享选定桥接策略的 ContextInfo、证券池、账号订阅和图表状态；创建实例不会创建独立策略或回测环境。
- `init`、`after_init`、`handlebar`、`stop` 是 QMT 驱动的生命周期入口，不能作为普通远程函数手动调用。
- 不提供图表绘制、模型/VBA 执行或回测下单；扩展数据与因子读取需要对应终端数据和策略上下文。
- 方法存在性依赖券商 QMT 版本和运行环境；能力表为 `False` 时调用会明确报缺失，不导入 MiniQMT 补齐、不改用含义不同的函数。
- 新增接口时更新 `qmt_inner_catalog.py` 的分类及原生归属；需要特定参数适配时更新 `qmt_inner.py`。桥接执行与原始数据编码由 `qmt_inner_runtime.py` 维护。
- 修改桥接后运行 `python tools/sync_qmt_inner.py` 和 `python tools/sync_qmt_release.py`，并用对应 `--check` 确认单文件入口一致。

自动测试覆盖参数、重载、原生对象字段、回调、资源清理、Web 路由及单文件同步，包括原生类型缺少 `__module__` / `__dict__` 的情况。

## 华泰模拟终端实测

2026-11-05，在华泰证券 QMT 模拟终端的信用账户上完成托管 Lite 策略更新、QMT 重启、自动登录和策略恢复，并从外部 Python 调用本接口。

| 通道 | 检查结果 | 实际收到的回调 |
| --- | --- | --- |
| `ctypes` 直连 | 25 项通过，0 项失败 | 行情订阅、`schedule_run` 定时器 |
| `web_lttx` 转发 | 25 项通过，0 项失败 | 行情订阅、`schedule_run` 定时器 |
| 默认自动选择 | 行情、持仓及原生属性访问通过 | 使用当前注册的 Web 通道 |

检查包含证券信息、ContextInfo 属性、K 线 DataFrame、板块、交易日、除权数据、ETF 信息、资金/持仓/委托/成交查询、新股信息、回调注册/注销、订阅/定时器取消及会话关闭。交易查询保留 `m_...` 字段，并支持字典和属性访问。本次未提交买卖或撤单请求，未验证实际委托/成交回报推送，也未执行依赖图表或回测环境的绘图、引用和回测接口。

上述记录对应裁剪前的验证版本：当时 111 个候选方法中有 104 个存在。缺失的 7 个中，指标绘制、模型和 VBA 相关的 6 个现已移除，历史交易明细查询 `get_history_trade_detail_data` 仍保留。历史存在性探测不代表当前全部方法均已实测；其他券商和终端版本应重新检查 `capabilities()`。

2026-11-06 将裁剪后的策略更新到同一华泰模拟终端并恢复运行：`ctypes` 和 `web_lttx` 均确认当前能力表只包含 80 个方法，其中 79 个存在；持仓查询及原生属性访问正常。使用底层 RPC 请求已移除的指标属性和回测下单方法，也会被桥接端拒绝。此次为范围收敛复核，没有重新实测全部保留方法。
