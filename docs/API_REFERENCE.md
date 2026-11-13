# CFQuant API 参考：MiniQMT 兼容层与 Web 控制接口

CFQuant 有两层 API：

1. **Python 兼容 API（策略首选）**：`cfquant.xtdata`、`cfquant.xttrader`、`cfquant.xttype`、`cfquant.xtconstant`，面向从 MiniQMT/`xtquant` 迁移的策略，保留常用函数名、参数和回调习惯。
2. **Web API（控制与自动化）**：本页下文列出的 HTTP 接口，用于配置桥接、检查状态、查询数据和在授权后执行操作。

如果目标是迁移原有 MiniQMT 策略，先看[xtquant 原版接口适配清单](xtquant原版接口适配清单.md)，不要直接把 Web API 当作 Python SDK 的一对一替代。

## Python 兼容 API 快速入口

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

bars = xtdata.get_market_data(
    field_list=["open", "close"], stock_list=["000001.SZ"],
    period="1d", count=10,
)

trader = XtQuantTrader("strategy-session")
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
trader.connect()
trader.subscribe(account)
```

`cfquant` 的兼容入口使用已在 Web 控制台绑定的桥接大 QMT；原版 MiniQMT 的 `userdata_mini` 路径参数不应被当作大 QMT 目录。`get_market_data`、订阅、交易、查询和回调的逐项状态见适配清单。

基础地址默认为 `http://127.0.0.1:8765`。请求体使用 UTF-8 JSON，成功响应通常为 `{"ok": true, "data": ...}`，失败响应为 `{"ok": false, "error": ..., "code": ...}`。

## 认证

- 浏览器会话：使用初始化接口返回的 Web Token，放在 `X-CFQUANT-WEB-TOKEN` 或 HttpOnly Cookie。
- API 客户端：使用 `X-API-Key: <key>`，也接受 `Authorization: Bearer <key>`。
- 内部接口：按接口要求使用 `X-CFQUANT-INTERNAL-API-KEY`。
- `/api/health`、`/api/config` 等公开读取接口不要求认证；交易、配置、远程管理和生命周期接口必须认证。

## 只读接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 服务健康检查 |
| GET | `/api/config` | 当前运行配置、账户和通道状态 |
| GET | `/api/version` | 版本与可选远程版本检查 |
| GET | `/api/server-access` | 监听地址、远程访问和认证状态 |
| GET | `/api/transport` | 传输层状态 |
| GET | `/api/pipe-hub` | PipeHub 状态 |
| POST | `/api/data/market` | 行情查询 |
| POST | `/api/data/market-ex` | 扩展行情查询 |
| POST | `/api/data/full-tick` | 全量 Tick |
| POST | `/api/data/instrument` | 合约详情 |
| POST | `/api/data/sector` | 板块成分 |
| POST | `/api/data/trading-dates` | 交易日 |
| POST | `/api/data/financial` | 财务数据 |
| GET | `/api/config` | 账户绑定、桥接和运行配置（完整配置视认证状态而定） |

## 行情与数据操作（POST）

`/api/quotes/subscribe`、`/api/quotes/whole/subscribe`、`/api/quotes/unsubscribe` 用于订阅；`/api/data/history/download` 和 `/api/data/financial/download` 用于下载数据。请求字段以对应函数的 JSON 参数为准，先用 `/api/config` 获取可用 `bridge_id` 和账户键。

## 交易操作（POST）

- `/api/order`、`/api/order_async`：普通股票委托。
- `/api/orders/batch`：批量委托。
- `/api/cancel`：撤单。
- `/api/credit/order`、`/api/credit/orders/batch`：信用账户。
- `/api/future/order`、`/api/future-option/order`、`/api/stock-option/order`：期货及期权。
- `/api/trade/algo/submit|query|list|pause|resume|cancel`：算法单。
- `/api/trade/plan/preview|submit|query|list|cancel`：订单计划。
- `/api/trade/condition/submit`：条件单。

交易请求应包含账户标识、标的、方向、数量和价格字段；异步接口返回任务或委托标识，必须继续查询状态，不应把“请求已接受”当作成交。

## 配置与生命周期操作（POST）

`/api/account-config`、`/api/account-config/delete`、`/api/setup/initialize`、`/api/setup/reset`、`/api/python-environment`、`/api/transport`、`/api/server-access`、`/api/pipe-hub/start`、`/api/pipe-hub/stop`、`/api/qmt/processes/start`、`/api/qmt/processes/stop`、`/api/management/restart`、`/api/management/stop`。

这些接口可能重启服务、启动或停止 QMT，agent 只能在用户确认后调用，并应在调用前保存 `/api/config` 快照。

## 错误与幂等

`400` 表示参数或业务校验失败，`401` 表示认证失败，`404` 表示路径不存在，`409` 表示更新、交易或策略恢复正在进行。网络重试前先查询状态；下单和启动类请求不要盲目重试。

