# cftrader 批量交易

`cfquant.cftrader` 是项目扩展的下单接口。它复用已有 `XtQuantTrader` 实例，提供单笔同步、单笔异步、批量同步和批量异步下单。连接、账号订阅、查询、撤单以及交易回调继续由原实例管理。

**批量的执行位置在大 QMT 内部。** 外部 Python 完整校验 `orders` 后，通过一个批量 RPC 将整批订单发送到 QMT；QMT 内部连续调用 `passorder`。100 笔订单对应一次批量通信、100 次本地下单，减少逐笔请求和响应的通信往返。

```python
from cfquant import cftrader
from cfquant.xttrader import XtQuantTrader

trader = XtQuantTrader("", 0)
orders_api = cftrader.CfQuantTrader(trader)
```

也可以使用 `from cfquant.cftrader import CfQuantTrader`。构造 `CfQuantTrader` 不创建连接，不启动线程，不注册另一套回调。

## 接口与参数

| 方法 | 参数 | 返回 |
| --- | --- | --- |
| `order_stock` | `account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""` | 与原接口一致的订单号 |
| `order_stock_async` | 与 `order_stock` 相同 | 与原接口一致的请求序号 `seq` |
| `order_stock_batch` | `account, orders, strategy_name="", order_remark="", stop_on_error=False` | 逐笔订单号及批量结果字典 |
| `order_stock_batch_async` | 与 `order_stock_batch` 相同 | 逐笔请求序号及批量结果字典 |

批量调用的 `account` 使用原来的 `StockAccount` 或账号字典；传 `None` 时使用原 `XtQuantTrader` 构造时绑定的账号。每次批量对应一个账号，多账号分别调用即可。`orders` 是非空列表或元组，每笔使用原接口字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `stock_code` | 是 | 证券或合约代码，保留大小写，例如 `600000.SH`、`rb2610.SF` |
| `order_type` | 是 | 原 `xtconstant` 下单常量，整数 |
| `order_volume` | 是 | 正整数数量，与对应市场、品种的单位一致 |
| `price_type` | 是 | 原 `xtconstant` 报价类型常量，整数 |
| `price` | 是 | 有限数值；行情价模式也显式传入原接口要求的占位价格 |
| `strategy_name` | 否 | 覆盖批次默认策略名；显式空字符串保留为空 |
| `order_remark` | 否 | 非空值原样使用；缺失或为空时使用“批次备注或自动批次 ID + 行号” |

`stop_on_error` 必须为布尔值。不会在行内接受 `account`、`bridge_id` 或拼错的下单字段。参数错误、空批次、非有限价格、非整数数量，以及批次内重复的“代码 + 备注”都会在发送任何订单前抛出 `ValueError`。账号、品种和业务权限由现有 QMT 路径继续校验。

## 批量同步下单

示例默认只打印参数；与已有交易教程一致，修改账号、品种、价格和 `ENABLE_TRADING` 后才会提交。

```python
from cfquant import cftrader, xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

ENABLE_TRADING = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
orders = [
    dict(stock_code="600000.SH", order_type=xtconstant.STOCK_BUY,
         order_volume=100, price_type=xtconstant.FIX_PRICE, price=10.0),
    dict(stock_code="000001.SZ", order_type=xtconstant.STOCK_BUY,
         order_volume=100, price_type=xtconstant.FIX_PRICE, price=9.0),
]
trader = XtQuantTrader("", 0)
orders_api = cftrader.CfQuantTrader(trader)
if ENABLE_TRADING:
    try:
        trader.start()
        if trader.connect() != 0 or trader.subscribe(account) != 0:
            raise RuntimeError("Connection or subscription failed")
        result = orders_api.order_stock_batch(
            account, orders, strategy_name="rebalance", stop_on_error=True,
        )
        for row in result["results"]:
            print(row["index"], row["status"], row["order_id"], row["error"])
    finally:
        trader.stop()
else:
    print("Preview only:", orders)
```

同步批量使用 `cftrader.order_stock_batch` RPC。QMT 先连续提交整批，再集中解析订单号，不在两笔 `passorder` 之间轮询等待编号。直接返回的有效订单号立即保留，其余按“代码 + 备注”匹配委托查询；整批共用一个等待窗口，默认 2 秒，由 QMT 环境变量 `CFQUANT_ORDER_ID_WAIT_SECONDS` 配置。查询前已有的订单号和有歧义的匹配不会被关联。

`results` 与输入等长、顺序一致，`index` 从 0 开始。QMT 明确拒绝记录为 `failed`；已提交但未能确认编号记录为 `unknown`。同步编号解析发生在整批提交之后，因此某笔编号未确认，不代表后面的订单未提交。

## 批量异步下单与原回调

```python
from cfquant import cftrader, xtconstant
from cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from cfquant.xttype import StockAccount

class Callback(XtQuantTraderCallback):
    def on_order_stock_async_response(self, response):
        print("response:", response.seq, response.order_id, response.order_remark)

    def on_stock_order(self, order):
        print("order:", order.order_id, order.order_status)

    def on_stock_trade(self, trade):
        print("trade:", trade.order_id, trade.traded_volume)

    def on_order_error(self, error):
        print("error:", error)

ENABLE_TRADING = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
orders = [
    dict(stock_code="600000.SH", order_type=xtconstant.STOCK_BUY,
         order_volume=100, price_type=xtconstant.FIX_PRICE, price=10.0),
    dict(stock_code="000001.SZ", order_type=xtconstant.STOCK_BUY,
         order_volume=100, price_type=xtconstant.FIX_PRICE, price=9.0),
]
trader = XtQuantTrader("", 0)
orders_api = cftrader.CfQuantTrader(trader)
if ENABLE_TRADING:
    try:
        trader.register_callback(Callback())
        trader.start()
        if trader.connect() != 0 or trader.subscribe(account) != 0:
            raise RuntimeError("Connection or subscription failed")
        result = orders_api.order_stock_batch_async(
            account, orders, strategy_name="rebalance", stop_on_error=False,
        )
        for row in result["results"]:
            print(row["index"], row["status"], row["seq"], row["order_remark"])
        trader.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        trader.stop()
else:
    print("Preview only:", orders)
```

异步批量使用 `cftrader.order_stock_batch_async` RPC。SDK 先从原请求序号生成器分配逐笔 `seq` 并注册关联，再一次性发送整批；QMT 连续提交后返回逐笔受理状态，不等待订单号或成交。批次返回后，进程仍需运行才能持续接收回调。原回调有可能早于批量方法返回；可先用 `order_remark` 关联，再以 `seq`、`order_id` 核对。原单笔异步和批量异步共用请求序号生成器及回调去重逻辑。

信用账户使用 `StockAccount("YOUR_CREDIT_ACCOUNT_ID", "CREDIT")`，每笔的 `order_type` 改用原信用常量，例如融资买入 `xtconstant.CREDIT_FIN_BUY`、担保品卖出 `xtconstant.CREDIT_SELL`。同步、异步批量使用相同字段；期货、期货期权和股票期权也沿用原账号类型及对应下单常量。

## 返回值与失败处理

顶层字段包含 `batch_id`、`account`、`asynchronous`、`ok`、`total`、`attempted`、`submitted`、`failed`、`unknown`、`skipped` 和 `results`。四种状态计数之和等于 `total`，`attempted = total - skipped`；顶层 `ok` 仅在所有行都是 `submitted` 时为真。

`execution="qmt"` 标明批量采用 QMT 内执行协议。获得正常回包时，`qmt_submit_ms` 是 QMT 内部提交循环耗时，不含通信和同步编号解析耗时；并非成交延迟。整批请求失败时另有 `request_error`。回包丢失时无法确定真实执行笔数，`attempted` 包含执行情况未确认的订单，不能当作实际已下单数量。

每行包含 `index`、`stock_code`、`status`、`ok`、`order_id`、`seq`、`strategy_name`、`order_remark`、`error`。同步成功行填充 `order_id`。异步所有行保留预分配的 `seq`，即使该行失败、未提交或结果未确认也可用于关联；只有 `status="submitted"` 才代表 QMT 已确认受理。另一种编号字段为 `None`。

| 状态 | 行内 `ok` | 含义及后续处理 |
| --- | --- | --- |
| `submitted` | `True` | 已获得订单号或有效请求序号；不表示已成交，最终状态继续看原委托、成交、错误回调 |
| `failed` | `False` | QMT 下单明确拒绝，同步、异步均适用；`stop_on_error=False` 时继续，否则后续行标记 `skipped` |
| `unknown` | `None` | 同步编号未确认、整批回包异常或本地下单抛出异常；先通过原查询和回调核对 |
| `skipped` | `None` | 本次没有调用该行下单；不会自动补发 |

QMT 本地下单抛出异常时，停止该批尚未执行的订单。已提交的订单不会因后续失败被撤回。`cftrader` 批量不保证原子提交、并行提交或同一时刻成交。

`trader.set_timeout()` 对整批 RPC 生效。整批通信超时后，QMT 可能已经执行或仍在执行整批，SDK 将所有未确认行标为 `unknown`，保留异步关联以接收迟到回调。该协议在 SDK 和 Web 路由中均不自动重试、不在错误后切换通道重发，也不会降级为 SDK 逐笔发送；核对原委托查询及回调后再决定后续操作。

未启用独立市场路由时，同一账号的沪深订单可一起发到一个 QMT。启用 SH/SZ 独立终端时，Web 按输入顺序将连续同目标市场的订单分段，每段一个批量请求，例如 SH、SH、SZ、SZ 对应两段，SH、SZ、SH 对应三段。各段均在对应 QMT 内部批量执行；前段失败并要求停止，或前段结果不确定时，尚未发送的段标为 `skipped`。

## 部署与教程入口

需要同时更新外部 Python SDK、Web 服务和 QMT 核心并重启加载。通用、高级模式加载新的 `cfquant/batch_orders.py` 与桥接模块；极致模式重新导入已同步新协议的 `CFQUANT_LITE*.py`。旧 QMT 桥不认识批量动作时会返回错误，不会自动拆成单笔请求。独立内嵌旧桥 `CfquantQmtBridge` 不支持此扩展。现有 `xttrader` 调用方式保持兼容。

- “接口 → cftrader 独立下单接口”：查看四种下单方法的签名、参数、返回状态和 Python 示例，也可填写参数并点击“测试下单”；点击“教程与可复制示例”进入对应的 API 文档。
- “教程 → Python 接入”：搜索 `cftrader`、`order_stock_batch` 或“批量”，也可筛选“cfquant 独立接口”。
- “教程 → cftrader 批量交易”：查看完整接入流程、同步与异步示例以及原回调处理。

## 网页在线测试

“教程 → Python 接入”的接口详情提供“在线测试”按钮。已提供 HTTP 路由的行情、账户、信用查询和下单接口可直接填写参数、发送请求，并查看、复制或清空结果。回调接口通过“查看回调”读取原回调记录；没有网页路由的 Python 接口显示“仅 Python 调用”。打开文档不会自动执行测试。

`cftrader` 四种下单方法均有对应的网页测试路由，沿用网页的鉴权和账号绑定配置：

| 方法 | HTTP 路由 |
| --- | --- |
| 单笔同步 | `POST /api/cftrader/order_stock` |
| 单笔异步 | `POST /api/cftrader/order_stock_async` |
| 批量同步 | `POST /api/cftrader/order_stock_batch` |
| 批量异步 | `POST /api/cftrader/order_stock_batch_async` |

请求使用 `account_id`、`account_type` 和可选的绑定 `account_key`。单笔参数沿用 SDK 的 `stock_code`、`order_type`、`order_volume`、`price_type`、`price`、`strategy_name`、`order_remark`；批量使用 `orders` 数组和布尔值 `stop_on_error`，公共策略名和备注仍可选填。`timeout` 默认 30 秒，上限 120 秒。

下单测试会向所选账号提交委托。必须手动填写 `confirm_text="CFTRADER 账号 笔数"`，例如测试账号 `TEST_ONLY` 的两笔委托填写 `CFTRADER TEST_ONLY 2`。账号类型、绑定及确认笔数不匹配时，服务端在发送前拒绝请求。网页不会预填确认文本。

响应的 `data.result` 为下单结果。批量页面同时显示逐笔状态、`order_id` 或 `seq`、失败原因、页面往返时间、服务端时间以及 QMT 内部提交耗时。异步 `seq` 由服务端分配，委托、成交、错误和异步下单回报继续进入原回调路径，可在回调界面查看。

“停止等待”仅终止浏览器等待，不能取消已经发送的委托。超时或断线后先查询委托与回调，核对后再决定是否重试。网页不会自动补发。批量路由使用上述 QMT 内部批量协议；原“交易 → 批量委托”的 `POST /api/orders/batch` 仍保留，其字段和返回结构以原 HTTP 文档为准。
