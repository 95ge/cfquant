# miniQMT 迁移到大 QMT 指南

本文面向已经使用 `miniQMT` / `xtquant` 的策略系统，说明如何用 `cfquant` 把交易、查询和行情能力迁移到大 QMT。

## 适用场景

适合迁移的能力：

- 买入、卖出、撤单。
- 信用、期货、期货期权、股票期权委托。
- 委托、成交、持仓、资金查询。
- 行情快照、K 线、订阅和全推行情。
- 外部 Python 多进程访问同一个资金账号。
- 多账号、多 QMT、普通、信用、期货、期货期权和股票期权账户分开绑定。

不建议直接迁移到桥接链路的能力：

- 大批量历史数据回测读取。
- 高频反复读取本地文件型行情数据。
- miniQMT 客户端连接管理类接口，例如行情服务器管理、本地数据目录工具。

`cfquant` 的定位是把大 QMT 的实时交易、查询、行情和回调能力转接给外部系统，不是替代本地数据库或回测数据引擎。策略回测需要的大批量数据建议先落到本地数据库，回测直接读库，实盘交易和少量实时查询再走 `cfquant`。

## 总体架构

迁移后的请求链路：

```text
外部策略进程
  -> cfquant Python SDK / HTTP API / Web 控制台
  -> cfquant Web 统一路由
  -> PipeHub 或 LTtx
  -> QMT 入口脚本
  -> 大 QMT 交易、查询、行情能力
```

和 miniQMT 的区别：

| 项目 | miniQMT 常见方式 | cfquant 大 QMT 方式 |
| --- | --- | --- |
| 运行位置 | 外部程序直接连接 miniQMT 客户端 | 大 QMT 内运行桥接脚本，外部程序请求本地 cfquant 服务 |
| 账号识别 | 常见做法是用 `session_id` 区分连接 | 用 Web 绑定生成的 `account_key`、`bridge_id` 和账号类型路由 |
| 多进程访问 | 多进程各自创建 trader/session | 多进程统一请求本机 cfquant 服务，再由 PipeHub/LTtx 路由 |
| 数据读取 | miniQMT 本地 `xtquant` 读取较快 | 通过桥接跨进程、跨 QMT 上下文，批量读取不适合做回测主链路 |
| 低延迟交易 | 依赖 miniQMT 和券商环境 | 通用模式可用 ctypes 低延迟单文件入口，高级模式可接极速交易端 |

## 模式选择

### 通用模式

适合大多数迁移验证和单 QMT 部署。

QMT 侧只需要加载：

```text
qmt_scripts/CFQUANT_CTYPE_ALL_LOWLAT.py
```

特点：

- 一个 QMT、一个入口脚本即可运行。
- 外部请求通过 PipeHub named pipe 进入 QMT。
- 普通查询和交易请求分通道处理，部署成本低。
- 适合先验证买卖、撤单、资金、持仓、委托、成交等核心能力。

### 高级模式

适合明确追求更低交易链路延迟，并且已经具备普通 QMT + 极速交易端环境的用户。

QMT 侧需要两个入口：

```text
普通 QMT：qmt_scripts/CFQUANT.py
极速交易端 QMT：qmt_scripts/CFQUANT_TRADE_LOWLAT.py
```

特点：

- 普通 QMT 承接普通查询、行情和回调。
- 极速交易端 QMT 承接下单、撤单和交易查询。
- 账号配置为高级模式后，Web 会优先走高级通道；高级通道不可用时回退到该账号的 ctypes 通用桥。
- 真实耗时受 QMT、券商柜台、网络、交易时段和 QMT 内部调度影响，不能只看单次请求。

## 迁移步骤

### 1. 梳理原 miniQMT 调用

先列出当前系统实际用到的接口，不要按“整个 xtquant 全量平替”推进。

建议至少整理：

| 类型 | 常见接口 |
| --- | --- |
| 下单 | `order_stock`、`order_stock_async`，普通/信用/期货/期货期权/股票期权均保持 MiniQMT 入参签名 |
| 撤单 | `cancel_order_stock`、`cancel_order_stock_async`、`cancel_order_stock_sysid` |
| 资金 | `query_stock_asset` |
| 持仓 | `query_stock_positions`、`query_stock_position` |
| 委托 | `query_stock_orders`、`query_stock_order` |
| 成交 | `query_stock_trades` |
| 行情 | `get_full_tick`、`get_market_data`、`get_market_data_ex`、`subscribe_quote`、`subscribe_whole_quote` |

完整兼容情况见：

- [xttrader 兼容说明](xttrader平替追踪.md)
- [xtdata 兼容说明](xtdata平替追踪.md)

### 2. 部署并启动 cfquant

在固定目录解压或拉取项目后启动：

```powershell
cd D:\cfquant
start_cfquant.bat
```

打开 Web 控制台：

```text
http://127.0.0.1:8765/
```

首次使用建议按“新手初始化向导”完成账号、模式和 QMT 核心目录配置。

### 3. 在 Web 绑定账号

进入 Web“绑定”页，至少填写：

- 账号名称，可选，用来在列表中识别客户或券商。
- 资金账号。
- 账户类型，普通账户选 `STOCK`，信用账户选 `CREDIT`，期货账户选 `FUTURE`，期货期权账户选 `FUTURE_OPTION`，股票期权账户选 `STOCK_OPTION`。
- QMT 核心目录，建议填大 QMT 的 `bin.x64` 目录。
- 账号模式，先用通用模式验证，低延迟交易再切高级模式。
- 是否作为共享行情数据提供商。

多 QMT 或多券商时，每个账号会生成独立的 `bridge_id`。QMT 入口脚本启动时会读取对应目录下的 `cfquant_bridge_config.json`，并注册到对应通道。外部策略不要手工猜通道名，优先让 Web 按账号配置路由。

### 4. 在 QMT 中加载入口脚本

通用模式只加载：

```text
CFQUANT_CTYPE_ALL_LOWLAT.py
```

高级模式加载：

```text
普通 QMT：CFQUANT.py
极速交易端 QMT：CFQUANT_TRADE_LOWLAT.py
```

注意：

- 不要在同一个 QMT 里同时运行普通入口和极速交易入口。
- 修改绑定、`bridge_id` 或 QMT 目录后，需要重启对应 QMT 入口脚本。
- 如果 QMT 关闭或重启后外部请求超时，先确认 QMT 入口脚本已重新运行；新版本 Web/PipeHub 会在断线后清理旧连接并尝试重连。

### 5. 外部 Python 接入

安装本地包：

```powershell
cd D:\cfquant
pip install -e .
```

原 miniQMT 代码一般类似：

```python
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
```

迁移到 `cfquant` 后：

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("2220009880")
trader = XtQuantTrader("", 0, account=account)
trader.start()

asset = trader.query_stock_asset(account)
positions = trader.query_stock_positions(account)
print(asset, positions)
```

默认 `transport=auto`。只要本地 Web 服务和 QMT 入口在线，外部程序通常不需要手动配置 PipeHub、LTtx 或 HTTP 端口。

详细外部接入规则见 [外部 Python 接入](外部Python接入.md)。

## 交易账号和常量映射

`cfquant` 对外仍使用 MiniQMT 风格的 `StockAccount` 和 `order_stock`，账号类型决定业务语义：

| 账号类型 | 适用业务 | `order_type` 处理 |
| --- | --- | --- |
| `STOCK` | 普通证券买卖 | `STOCK_BUY=23`、`STOCK_SELL=24` 原样传入大 QMT `passorder`。 |
| `CREDIT` | 信用账户担保品买卖、融资融券、还款还券、专项业务 | MiniQMT 信用常量会映射到大 QMT 信用 opType；也可通过 `credit_action` 指定业务。 |
| `FUTURE` | 期货开平仓、套利、换月等 | MiniQMT `FUTURE_*` 常量 0-22 原样传入大 QMT `passorder`。 |
| `FUTURE_OPTION` | 期货期权开平仓、行权 | 期货类 `FUTURE_*` 常量原样传入；`OPTION_FUTURE_OPTION_EXERCISE=100` 原样传入。 |
| `STOCK_OPTION` | ETF/股票期权买开卖平、卖开买平、备兑、行权、锁券/解锁 | 外部传 MiniQMT `STOCK_OPTION_*` 常量 48-57，桥接层转换为大 QMT ETF 期权 opType 50-59。 |

Web/API 下单也遵循同一套规则：普通账户可继续传 `side=buy|sell`；信用账户可传 `credit_action`；期货和期权账户可传 `order_action`，例如 `future_open_long`、`future_open_short`、`stock_option_buy_open`。`price_type` 保持 MiniQMT 数值，默认 `FIX_PRICE=11`；固定价时 `price` 必须大于 0，市价/最新价类报价可以传 0。

## 多进程访问同一个账户

miniQMT 里经常通过不同 `session_id` 管理多个进程或多个策略实例。迁移到 `cfquant` 后，不建议继续把 `session_id` 当成主路由依据。

推荐方式：

1. 在 Web 里把真实资金账号绑定好。
2. 外部多个策略进程都使用同一个资金账号创建 `StockAccount`。
3. 多个进程统一请求本地 `cfquant` 服务。
4. Web 根据 `account_key`、`bridge_id`、账号类型和账号模式选择通道。

示例：

```python
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("2220009880")

# 未显式传 session_id 或传 0 时，cfquant 会自动分配一个正整数。
trader = XtQuantTrader("", account=account)
trader.start()
```

如果一个外部系统里有多个策略共享同一账户，建议在上层系统保留自己的 `strategy_id` / `client_order_id`，并写入 `strategy_name` 或 `order_remark`，方便委托和成交回查后做归属映射。

## 字段映射

迁移时不要假设 `cfquant` 返回字段和 miniQMT 完全一致。建议做一层适配层，把桥接返回对象转换成你们系统内部的稳定模型。

重点检查：

| 类别 | 需要确认的字段 |
| --- | --- |
| 下单返回 | 本地 `order_id`、异步响应序号、错误信息 |
| 撤单返回 | 撤单结果、原委托编号、系统编号撤单是否可用 |
| 委托查询 | 委托编号、合同编号、证券代码、买卖方向、价格、数量、已成数量、状态、时间 |
| 成交查询 | 成交编号、委托编号、证券代码、成交价格、成交数量、成交时间 |
| 持仓查询 | 证券代码、证券名称、持仓数量、可用数量、成本价、市值、盈亏 |
| 资金查询 | 总资产、可用资金、冻结资金、持仓市值 |
| 派生品扩展字段 | `direction`、`offset_flag`、`order_type`、`price_type`、`commission`、冻结数量、在途数量、昨仓、最新价、收益率 |

建议迁移时先把 `query_stock_orders`、`query_stock_trades`、`query_stock_positions`、`query_stock_asset` 的原始返回保存一份，再对照 miniQMT 当前字段做映射。不同券商 QMT 版本的字段名和状态枚举可能存在差异。

## 数据读取和回测建议

如果策略需要大量历史 K 线、tick、财务数据或板块数据，建议拆成两条链路：

```text
回测 / 批量分析：本地数据库、文件缓存、离线数据服务
实盘交易 / 小量实时查询：cfquant -> 大 QMT
```

原因：

- miniQMT 的本地 `xtquant` 读取本地数据通常很快。
- 大 QMT 桥接需要跨 Web、PipeHub/LTtx、QMT 策略上下文和序列化层。
- 批量历史数据读取会放大桥接开销，容易出现“策略回测慢了很多”的体感。

实盘里建议 `cfquant` 负责：

- 下单、撤单。
- 资金、持仓、委托、成交查询。
- 实时行情快照和订阅。
- QMT 回调事件转发。

不建议 `cfquant` 负责：

- 每次回测都从 QMT 批量读取全市场历史数据。
- 高频轮询大表并直接用于回测。
- 替代数据仓库。

## 延迟验证方法

不要只看一次接口耗时。建议在真实交易时段分别统计：

- `order_stock` / `order_stock_async`
- `cancel_order_stock` / `cancel_order_stock_async`
- `query_stock_asset`
- `query_stock_positions`
- `query_stock_orders`
- `query_stock_trades`
- `get_full_tick`

至少看：

- `min`
- `p50`
- `p95`
- `max`
- 超时次数
- QMT 重启或断线后的恢复情况

真实环境延迟报告单独放在本地私有文档目录维护，公开文档只保留验证方法和指标口径。

如果客户有极速柜台权限，可以优先对比通用模式和高级模式的下单、撤单、交易查询耗时，再决定是否把生产账号切到高级模式。

## 推荐迁移顺序

1. 只迁移查询接口，验证资金、持仓、委托、成交字段。
2. 迁移撤单和小额测试下单，验证返回编号和状态流转。
3. 接入回调事件，确认异步下单、异步撤单和成交回报。
4. 迁移实时行情快照和订阅。
5. 多进程压测同一账号，确认并发请求、超时和断线恢复。
6. 再决定是否切到高级模式或极速交易端。
7. 最后清理 miniQMT 依赖和字段兼容分支。

## 常见问题

### cfquant 能完全等价替代 miniQMT 吗？

不能简单理解成完全等价。交易、查询和常用行情可以按 miniQMT 习惯做平替，但 QMT 客户端连接管理、本地数据目录、批量回测数据读取等语义不适合放到大 QMT 桥接主链路。

### 多进程访问一个账户是否支持？

支持。多个外部进程可以同时请求同一个本地 `cfquant` 服务，由 Web 和 PipeHub/LTtx 统一路由到对应账户。迁移时建议把原来的 `session_id` 只作为兼容参数或策略侧标识，真实路由以账号绑定为准。

### 下单能否做到 50ms 以下？

需要实测。通用模式和高级模式都有低延迟路径，但最终耗时受 QMT、券商柜台、极速柜台权限、交易时段、网络和 QMT 内部调度影响。建议在客户真实环境里跑 `p50 / p95 / max`，再判断能否满足生产要求。

### 回测速度变慢怎么办？

不要把回测所需的大批量数据读取放在桥接链路上。建议提前落本地库，回测读库，`cfquant` 只负责实盘交易、实时查询和必要行情。

### 迁移时最容易踩坑的地方是什么？

- 没有在 Web 里正确绑定账号和 QMT 核心目录。
- QMT 入口脚本没有重启，导致还在使用旧 `bridge_id` 或旧配置。
- 多 QMT 都显示 `default`，说明入口脚本没有读到对应 `cfquant_bridge_config.json`。
- 把 miniQMT 的字段结构原样假设到 cfquant 返回，导致订单编号、合同编号或状态枚举映射错误。
- 把批量历史数据和回测读取也放到桥接里，导致迁移后整体速度下降。

