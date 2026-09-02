# cfquant 到大 QMT 的通信链路与回调机制

本文梳理外部 Python 调用 `cfquant` 时，下单、撤单、委托查询、成交查询、资金/持仓查询、行情查询、行情订阅和交易回调在不同部署模式下如何进入大 QMT。

## 先说结论

1. 外部调用者只是 `import cfquant`、创建 `StockAccount` 或创建 `XtQuantTrader` 对象时，不会立即持续连接 LTtx。
2. 第一次调用 `xtdata.*`、`XtQuantTrader.start()`、`XtQuantTrader.connect()`、`XtQuantTrader.subscribe()`、下单或查询时，客户端才会启动底层连接。
3. 默认 `CFQUANT_TRANSPORT=auto` 时，如果本机 Web 服务在线并通过 LTtx 发布了 `cfquant.runtime` 注册信息，外部 Python 会连接 LTtx 的 Web 统一路由频道 `cfquant.web.request`，并持续保持该 LTtx 客户端连接和接收线程，直到进程退出、调用 `close()`/`stop()` 或 `configure()` 重置客户端。
4. 如果强制 `transport="ctypes"`，或者 `auto` 没有发现 Web 路由并回退到 ctypes，外部 Python 不直接连接 LTtx，而是持续连接 `cfquant_pipe_hub` named pipe。
5. 如果强制 `transport="lttx"`，外部 Python 会绕过 Web 路由，直接持续连接 LTtx，并把请求发送到对应桥的 `normal` 或 `trade` 请求频道。
6. Web 服务自身默认会启动并维护 LTtx，用来做运行时发现和 Web 统一路由；这不等同于每个外部调用者都直连 QMT 桥。

## 核心组件

### 外部 Python 侧

- `cfquant.xttype.StockAccount(account_id, account_type="STOCK", bridge_id=None)`：只保存账号、账号类型和可选桥 ID，不建立网络连接。
- `cfquant.xttrader.XtQuantTrader(...)`：创建交易对象。连接发生在 `start()`、`connect()` 或第一次交易请求时。
- `cfquant.xtdata`：模块级行情接口。第一次 `get_client().request(...)` 时创建全局客户端。
- `cfquant.configure(...)`：修改默认 host、port、transport、pipe name、bridge id 等配置，并关闭旧的默认客户端。

### 外部 RPC 客户端

- `WebLttxRpcClient`：外部 Python 到 Web 统一路由。请求频道通常是 `cfquant.web.request`。这是默认 `auto` 成功发现 Web 服务后的路径。
- `LTtxRpcClient`：外部 Python 到 LTtx 频道的直连客户端。启动时调用 `start_tx()` 并订阅自己的 `client_id` 回复频道。
- `PipeRpcClient`：外部 Python 到 `cfquant_pipe_hub` 的 named pipe 客户端。启动时建立 `api_rx` 和 `api_tx` 两条 pipe 连接，并用后台线程接收响应/事件。

### 本地 Web 服务

`cfquant_web_server.py` 承担四件事：

- 启动/维护 LTtx 服务，用 `cfquant.runtime` 发布运行时注册信息。
- 在 `cfquant.web.request` 上运行 Web 统一路由，把外部请求按账号配置转发到 ctypes/lite 或 lttx 桥。
- 在通用/极致模式需要时启动 `cfquant_pipe_hub`。
- 监听 callback 通道和底层客户端事件，把交易回调、行情回调转发给 Web 页面和外部 Web LTtx 调用者。

### 大 QMT 侧入口

- `qmt_scripts/CFQUANT_CTYPE_ALL_LOWLAT.py`：通用模式入口。一个 QMT 策略内同时启动普通 Pipe 桥和低延迟交易 Pipe 桥。
- `qmt_scripts/CFQUANT.py`：高级模式里的普通 QMT 桥。主要承担行情、普通查询、账户回调广播。
- `qmt_scripts/CFQUANT_TRADE_LOWLAT.py`：高级模式里的纯交易请求桥。只处理低延迟交易请求，不承接 QMT 原始交易回调函数。
- `qmt_scripts/CFQUANT_LITE.py`：极致模式入口。自包含版本，不依赖 QMT 侧导入项目里的 `cfquant` 包。
- `qmt_scripts/同账号独立市场/*.py`：独立市场完整入口，内置对应主入口代码，用于同一账号按沪/深市场拆到不同 bridge。

### 大 QMT 侧桥类

- `NormalQmtBridge`：普通桥，继承 `TxTradeBridge`。支持交易/行情/查询请求排队、行情订阅转发、callback event 通道、QMT 原始交易回调发布。
- `TxTradeBridge`：交易请求桥。支持 `passorder`、`cancel`、`get_trade_detail_data`、部分行情/兼容查询、账号订阅表和向订阅账号的 client 推送 trader event。
- `PipeNormalQmtBridge` / `PipeTradeBridge`：把上述桥接到 `cfquant_pipe_hub`。

## 请求协议

外部请求统一打包为：

```text
type=request
id=req_...
action=xttrader.order_stock / xttrader.query_stock_orders / xtdata.get_market_data ...
params={...}
client_id=trade_client_...
reply_channel=trade_client_...
```

QMT 或 Web 路由处理完成后，按请求里的 `client_id/reply_channel` 原路返回：

```text
type=response
id=原 request id
ok=true/false
result=...
error=...
```

这个响应只返回给发起该请求的调用者，不广播给同账号的其他订阅者。

## 下单和撤单链路

### 默认 auto + Web 服务在线

这是推荐路径。

```text
外部 Python
  -> WebLttxRpcClient
  -> LTtx: cfquant.web.request
  -> Web 统一路由 route_external_lttx_request
  -> account_request 按账号配置选模式
  -> ctypes/lite: PipeRpcClient -> PipeHub -> QMT PipeTradeBridge
     或 lttx: LTtxRpcClient -> QMT TxTradeBridge
  -> QMT passorder/cancel
  -> response 原路返回外部 client_id
```

Web 路由里，下单、批量下单、撤单默认走 `trade` 通道：

- `xttrader.order_stock`
- `xttrader.order_stock_async`
- `xttrader.order_stock_batch`
- `xttrader.cancel_order_stock`
- `xttrader.cancel_order_stock_async`
- `xttrader.cancel_order_stock_sysid`
- `xttrader.cancel_order_stock_sysid_async`

如果账号配置为高级模式但高级 LTtx 桥不可用，Web 会尝试回退到该账号的 ctypes/lite 桥。

### 强制 ctypes

```text
外部 Python
  -> PipeRpcClient
  -> cfquant_pipe_hub
  -> QMT PipeTradeBridge
  -> QMT passorder/cancel
  -> PipeHub 原路返回 response
```

外部调用者不直接连接 LTtx。

### 强制 lttx

```text
外部 Python
  -> LTtxRpcClient
  -> LTtx: cfquant.trade.request
  -> QMT TxTradeBridge / 低延迟交易桥
  -> QMT passorder/cancel
  -> LTtx 原路返回 response
```

这条链路绕过 Web 账号路由，也没有 Web 侧自动回退能力。

## 委托、成交、资金、持仓查询链路

外部 `XtQuantTrader` 查询接口会转换为 `xttrader.*` RPC：

- `query_stock_asset` -> `xttrader.query_stock_asset`
- `query_stock_orders` -> `xttrader.query_stock_orders`
- `query_stock_trades` -> `xttrader.query_stock_trades`
- `query_stock_positions` -> `xttrader.query_stock_positions`

QMT 侧最终调用：

```text
get_trade_detail_data(account_id, account_type.lower(), detail_type.lower())
```

其中 `detail_type` 通常是 `account/order/deal/position`。

在 Web 统一路由下，交易查询默认走 `normal` 通道；下单和撤单默认走 `trade` 通道。  
在强制直连 `XtQuantTrader` 的场景下，`XtQuantTrader` 会优先使用当前 bridge 的 `trade` 请求频道，因此交易查询也可能直接进入 `trade` 桥。当前通用低延迟入口中 `PipeTradeBridge` 支持这些查询。

## 行情查询和行情订阅链路

### 同步行情查询

`cfquant.xtdata` 的同步接口会转换为 `xtdata.*` RPC，例如：

- `get_market_data`
- `get_market_data_ex`
- `get_full_tick`
- `get_local_data`
- `get_instrument_detail`
- `get_stock_list_in_sector`
- 财务数据、交易日、ETF、期权、因子等兼容接口

Web 统一路由下，如果请求里没有明确账号，Web 会选择配置中的行情数据源账号，再转发到对应桥；如果请求里带账号，则按该账号路由。

QMT 侧由 `NormalQmtBridge` 或 `TxTradeBridge` 调用 `ContextInfo` 或 QMT 全局函数里的对应行情函数。

### 行情订阅回调

外部调用：

```python
subscribe_id = xtdata.subscribe_quote("000001.SZ", callback=on_quote)
whole_id = xtdata.subscribe_whole_quote(["SH", "SZ"], callback=on_whole_quote)
```

外部 Python 会在本地把 callback 绑定到事件名：

```text
quote:<subscribe_id>
```

通用/极致模式下，QMT 普通桥内部订阅全推行情，然后按外部订阅表过滤并推送 `quote:<subscribe_id>` 事件。Web 统一路由会记住外部 `subscribe_id -> client_id` 的关系，把底层收到的行情事件再转发回外部调用者。

行情订阅事件是按 `subscribe_id` 定向推送，不是按账号广播。

## 交易回调机制

### 外部订阅

外部调用者要收到委托/成交等交易回调，必须让 `XtQuantTrader` 注册本地事件处理，并向 QMT/Web 订阅账号：

```python
account = StockAccount("8885060548")
trader = XtQuantTrader(callback=callback, account=account)
trader.start()      # start() 会自动 subscribe(account)
# 或 trader.connect()
# 或手动 trader.subscribe(account)
```

`XtQuantTrader` 本地会监听以下事件：

- `trader:on_stock_asset`
- `trader:on_stock_order`
- `trader:on_stock_trade`
- `trader:on_stock_position`
- `trader:on_order_error`
- `trader:on_cancel_error`
- `trader:on_order_stock_async_response`
- `trader:on_cancel_order_stock_async_response`
- 其他兼容异步响应事件

收到事件后，外部对象再调用用户传入的 `XtQuantTraderCallback.on_*` 方法。

### 大 QMT 侧注册

通用桥、普通桥、lite 桥会在 QMT 策略入口中做两类注册：

```text
ContextInfo.register_callback(0)
ContextInfo.set_auto_trade_callback(True)
```

然后由 QMT 策略加载器触发这些函数：

- `account_callback`
- `order_callback`
- `deal_callback`
- `position_callback`
- `orderError_callback`

当前脚本也保留了 `trade_callback`、`order_error_callback`、`cancel_error_callback`、`cancelError_callback` 等兼容别名，但是否会被调用取决于具体 QMT 策略加载器是否绑定这些名字。已知常见大 QMT 加载器会绑定 `orderError_callback`，不一定会绑定 snake_case 的错误回调或撤单错误回调。

### 回调广播

当 QMT 原始回调到达后：

```text
QMT 原始回调
  -> qmt_scripts 中的 order_callback/deal_callback/...
  -> NormalQmtBridge.publish_callback_event(...)
  -> 1. 推送 trader:on_* 给当前桥内所有订阅该账号的 client_id
  -> 2. 推送完整 callback event 到 callback_event_channel
  -> Web CallbackEventStore 记录/展示/转发
  -> Web LTTX route 再转发给通过 Web route 订阅该账号的外部 client_id
```

因此，账户级交易回调的设计目标是：同一个 `bridge_id + account_type + account_id` 下，所有已经 `subscribe(account)` 的外部调用者都能收到委托/成交回调；某一笔具体请求的同步 response 仍只返回给发起者。

## 不同模式下的回调能力

| 模式 | QMT 入口 | 账号级委托/成交回调 | 行情订阅回调 | 异步下单/撤单响应 | 外部调用者是否持续连 LTtx |
|---|---|---|---|---|---|
| 通用模式 ctypes | `CFQUANT_CTYPE_ALL_LOWLAT.py` | 支持。由普通 Pipe 桥接收 QMT 原始回调并广播 | 支持。普通 Pipe 桥转发 `quote:<subscribe_id>` | 支持。桥生成并只发给调用者 | 默认 auto + Web 在线时：是，连 Web LTtx；强制 ctypes 时：否，连 PipeHub |
| 极致模式 lite | `CFQUANT_LITE.py` | 支持，前提是 QMT 环境触发对应策略回调 | 支持 | 支持 | 默认 auto + Web 在线时：是；强制 lite/ctypes 时：否 |
| 高级模式 lttx | `CFQUANT.py` + `CFQUANT_TRADE_LOWLAT.py` | 支持，但由 `CFQUANT.py` 普通桥负责；纯交易桥不接 QMT 原始回调 | 支持，由普通桥负责 | 支持，交易桥可给调用者发请求级异步响应 | auto/Web 或强制 lttx 时：是 |
| 纯交易低延迟桥 | `CFQUANT_TRADE_LOWLAT.py` | 不支持 QMT 原始账号回调。按当前设计它只处理交易请求 | 不支持 | 支持请求级异步响应 | 强制 lttx 或 Web 高级路由到 trade 桥时：底层使用 LTtx |
| 独立市场模式 | `同账号独立市场/*.py` | 取决于内置的主入口；ctype/lite 具备回调，trade-only 不接原始回调 | 取决于内置的主入口 | 支持 | 取决于外部 transport 和账号路由 |

## 哪些回调一定不是广播

以下事件是请求级或订阅级事件，不是账号级广播：

- `order_stock` 同步 response：只返回给发起该笔请求的调用者。
- `cancel_order_stock` 同步 response：只返回给发起者。
- `on_order_stock_async_response`：由桥按 async 请求的 `client_id` 发送，只给发起者。
- `on_cancel_order_stock_async_response`：同上。
- `download_history_data2`、`download_financial_data` 的 progress callback：按调用时生成的 `callback_event` 发给发起者。
- `quote:<subscribe_id>` 行情事件：按行情订阅 ID 发给对应订阅者。

账号级的 `on_stock_order`、`on_stock_trade`、`on_stock_asset`、`on_stock_position` 才应该按账号订阅表广播。

## 常见误区

### 只创建 trader 对象不会建立长期连接

```python
trader = XtQuantTrader(callback=callback, account=account)
```

这一步只初始化对象。真正连接发生在：

- `trader.start()`
- `trader.connect()`
- `trader.subscribe(account)`
- `trader.order_stock(...)`
- `trader.query_stock_orders(...)`
- 其他触发 `_trade_request(...)` 的调用

### 使用默认 auto 时，大多数情况下会持续连接 LTtx

只要 Web 服务在线，`auto` 会先通过 LTtx 读取 `cfquant.runtime`，发现 Web route 后创建 `WebLttxRpcClient`。这个客户端会持续订阅自己的 `client_id` 回复频道，所以外部进程会持续连接 LTtx。

如果希望外部调用者完全不连 LTtx，需要显式：

```python
from cfquant import configure

configure(transport="ctypes")
```

这样外部 Python 直连 `cfquant_pipe_hub`。但 Web 服务本身仍可能为了注册发现和控制台功能维护 LTtx。

### 高级模式不要指望纯交易桥发原始委托/成交回调

`CFQUANT_TRADE_LOWLAT.py` 的职责是低延迟交易请求。它不定义 QMT 原始 `order_callback/deal_callback`。高级模式下，账号级委托/成交广播应由普通 QMT 桥 `CFQUANT.py` 负责。因此高级模式至少需要：

- 普通 QMT 运行 `CFQUANT.py`
- 交易 QMT 运行 `CFQUANT_TRADE_LOWLAT.py`
- Web 账号配置把该账号设为高级模式，并绑定正确 bridge

### 没有 subscribe 就不会收到账号级交易回调

外部调用者只有在 `trader.start()` 自动订阅，或手动 `trader.subscribe(account)` 后，才会进入账号订阅表。否则即使 QMT 收到了原始回调，也不会向该调用者广播账号级交易回调。

### QMT 脚本必须实际加载新版

如果 QMT 策略编辑器里运行的是旧的复制内容，磁盘上的 `qmt_scripts/*.py` 更新不会自动生效。需要重新导入、复制、保存并重启对应策略。启动后日志应能看到类似：

```text
cfquant ... qmt trade callback registered
auto trade callback enabled
```

收到委托/成交时应能看到类似：

```text
cfquant ... raw qmt callback received event=trader:on_stock_order
cfquant ... callback event sent event=trader:on_stock_order account=...
```

## 排查顺序

1. 外部 `6_回调测试.py` 是否打印实际连接通道：`WebLttxRpcClient`、`PipeRpcClient` 还是 `LTtxRpcClient`。
2. 外部是否调用了 `trader.start()` 或 `trader.subscribe(account)`。
3. QMT 日志是否有 `qmt trade callback registered` 和 `auto trade callback enabled`。
4. 下单/撤单发生时，QMT 日志是否有 `raw qmt callback received`。
5. 如果 QMT 有 raw callback 但外部没有收到，再看 Web route 或 PipeHub 是否记录了 callback event 转发。
6. 高级模式下确认 `CFQUANT.py` 普通桥在线；不要只启动 `CFQUANT_TRADE_LOWLAT.py`。
7. 多账号或信用账号下，确认 `account_type` 一致，避免同一个资金账号在不同账号类型下被 Web 过滤。
