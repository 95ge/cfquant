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
- 内部接口：按接口要求使用 `X-CFQuant-Internal-Key`。
- `/api/health`、`/api/config` 等公开读取接口不要求认证；交易、配置、远程管理和生命周期接口必须认证。

## MCP / 多 API Key 管理

“系统设置 → API Key”支持独立 Key 的创建、编辑、启用、停用、查看、复制和删除。每个客户端建议使用不同 Key，通过 `X-API-Key` 或 `Authorization: Bearer` 传入；原有管理员 Key 保留兼容，拥有完整权限，应仅用于可信管理，不能作为 AI 客户端日常凭据。

管理接口只允许管理员网页登录会话或管理员 Key；未启用网页登录时本机控制台可管理。首次创建独立 Key 前，必须先配置管理员 Key 或启用网页登录。受限 Key 即使与有效网页 Cookie 同时传入也不会继承管理员权限。

- `GET /api/access-keys`：列表、可授权账号及默认限流；不返回密钥明文。
- `POST /api/access-keys`：不含 `id` 为新建，含 `id` 为编辑；未传的字段保留原值。
- `POST /api/access-keys/reveal`：提交 `{"id":"KEY_ID"}`，管理员查看密钥；此操作也审计，响应禁止缓存。
- `POST /api/access-keys/delete`：提交 `{"id":"KEY_ID"}`，立即撤销密钥，保留历史审计。
- `GET /api/access-keys/audit?key_id=KEY_ID&offset=0&limit=50`：按 Key 分页查询，省略 `key_id` 为全部（含已删除 Key）；`limit` 上限 200。

创建示例：

```json
{
  "name": "行情研究助手",
  "permissions": ["query"],
  "account_keys": ["YOUR_BRIDGE_ID:STOCK:YOUR_ACCOUNT_ID"],
  "all_accounts": false,
  "enabled": true,
  "limits": {
    "requests_per_minute": 60,
    "requests_per_second": 5,
    "trades_per_minute": 10
  }
}
```

`account_keys` 来自已有绑定，不能自行猜测；`all_accounts=true` 表示明确授权全部当前及未来绑定。未选全部时必须至少选一个账号。相同资金账号的不同 `bridge_id` 或 `account_type` 分开授权。请求选择器必须一致；只指定已授权 `account_key` 可以补齐其他选择器，多个候选绑定时拒绝猜测。自定义内部通道禁止传入，批次内也不能覆盖账号。

`query` 可用接口：`GET /api/health`、`/api/config`、`/api/account`、`/api/order/actions`、`/api/credit/actions`；以及 `POST /api/data/full-tick`、`/api/data/market`、`/api/data/market-ex`、`/api/data/instrument`、`/api/data/sector`、`/api/data/trading-dates`、`/api/data/financial`、`/api/credit/query`。

`trade` 可用接口：普通、信用、期货、期货期权、股票期权的 `/api/.../order`、`/api/.../order_async`、`/api/.../orders/batch`，以及 `/api/cancel`。单独授予交易不会自动授予查询；常见交易助手应同时选择两项以便核查委托。受限 Key 暂不开放算法单、条件单、订单计划、订阅、WebSocket、cftrader 批量封装、数据下载及管理操作。

受限 Key 的 `/api/config` 仅返回已授权绑定的基本路由字段、权限及限流；不返回其他账号、QMT 路径、管理员 Key、密码或系统配置。其他账户查询按授权绑定读取。

速率为持久化滑动窗口，默认总请求 60 次/分钟、5 次/秒，交易 10 笔/分钟；每项可设 1 到 100000，三个窗口同时生效。批量最多 100 笔并按实际笔数消耗交易额度，额度不足整批拒绝。被拒绝的请求不会派发；不提供异步排队补执行。服务端返回 `429` 和 `Retry-After`；账号或权限拒绝为 `403`，无效、停用或已删除 Key 为 `401`。

密钥保存在 `runtime/config/api_keys.sqlite3`，明文经创建它的 Windows 用户 DPAPI 加密。审计独立保存到 `runtime/audit/api_keys.sqlite3`，记录受限 Key 调用及 Key 创建、编辑、明文查看、删除；不保存密钥或认证头，不随普通日志清理或 Key 删除而清除。路径以实际运行状态目录为准；管理员 Key 的兼容业务调用不属于受限 Key 审计与限流，应给 MCP 使用独立 Key。

审计在派发前持久化为 `pending`，完成后记录 HTTP 状态及允许的业务结果字段。无法建立审计记录时返回 `503`，不执行操作；执行后无法补写结果时也返回 `503` 并提示核查。`pending` 或异常返回不能据此断言未提交，须核查委托与成交。审计“接口成功”也不代表已成交。

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
