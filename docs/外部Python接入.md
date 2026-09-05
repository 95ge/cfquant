# 外部 Python 接入

本文说明外部程序如何通过 `cfquant` 调用 QMT 行情、查询和交易能力。新用户建议先在 Web 控制台完成初始化向导，并确认 QMT 侧入口脚本在线。

## 安装

推荐直接从 PyPI 安装：

```powershell
pip install cfquant
```

如果需要 LTtx 的 ZMQ 模式：
```powershell
pip install "cfquant[zmq]"
```

源码开发或本地调试时，在项目目录执行：

```powershell
cd D:\cfquant
pip install -e .
```

安装后可直接启动本地控制台：

```powershell
cfquant --help
cfquant --host 127.0.0.1 --port 8765 --open-browser
```

使用 `--home D:\cfquant-data` 可固定配置、SQLite 数据库、日志和运行状态目录。pip 安装后，QMT 加载脚本位于当前 Python 环境的 `site-packages/qmt_scripts/` 目录，可用命令查看、打开或导出：

```powershell
cfquant qmt-scripts
cfquant qmt-scripts --open
cfquant qmt-scripts --output D:\QMT\cfquant
```

兼容入口仍可使用：

```powershell
cfquant-web
cfquant-pipe-hub
```

## 推荐用法

外部程序可以按接近 `xtquant` 的方式导入：

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
```

行情查询示例：

```python
from cfquant import xtdata

tick = xtdata.get_full_tick(["000001.SZ"])
print(tick)
```

账号查询示例：

```python
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("2220009880")
trader = XtQuantTrader("", account=account)
trader.start()

asset = trader.query_stock_asset(account)
positions = trader.query_stock_positions(account)
print(asset, positions)
```

未显式传入或传 `0` 时，`trader.session_id` 会自动生成一个正整数，外部系统可以直接读取这个属性做实例归属。

交易账号类型：

| 账号类型 | 说明 |
| --- | --- |
| `STOCK` | 普通证券账户。 |
| `CREDIT` | 信用账户，支持担保品买卖、融资买入、融券卖出、还款还券及专项业务。 |
| `FUTURE` | 期货账户，支持 MiniQMT `FUTURE_*` 下单常量。 |
| `FUTURE_OPTION` | 期货期权账户，支持期货开平仓动作和 `OPTION_FUTURE_OPTION_EXERCISE=100`。 |
| `STOCK_OPTION` | 股票/ETF 期权账户，外部使用 MiniQMT `STOCK_OPTION_*` 常量 48-57，桥接层转换为大 QMT opType 50-59。 |

下单接口保持 MiniQMT 签名：

```python
order_id = trader.order_stock(
    account,
    stock_code,
    order_type,
    order_volume,
    price_type,
    price,
    strategy_name="strategy_name",
    order_remark="client_order_id",
)
```

期货下单示例：

```python
from cfquant import xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("YOUR_FUTURE_ACCOUNT_ID", "FUTURE")
trader = XtQuantTrader("", 0, account=account)
trader.start()

order_id = trader.order_stock(
    account,
    "IF2601.IF",
    xtconstant.FUTURE_OPEN_LONG,
    1,
    xtconstant.FIX_PRICE,
    4200.0,
    strategy_name="demo_future",
    order_remark="demo_future_order",
)
```

股票期权下单示例：

```python
from cfquant import xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("YOUR_OPTION_ACCOUNT_ID", "STOCK_OPTION")
trader = XtQuantTrader("", 0, account=account)
trader.start()

order_id = trader.order_stock(
    account,
    "10000001.SH",
    xtconstant.STOCK_OPTION_BUY_OPEN,
    1,
    xtconstant.FIX_PRICE,
    0.100,
    strategy_name="demo_option",
    order_remark="demo_option_order",
)
```

## 默认路由

默认 `CFQUANT_TRANSPORT=auto`，通常不需要手动调用 `configure()`。

自动路由规则：

- Web 服务启动后，会通过 LTtx 的 `tx.put()` 写入 `cfquant.runtime`。
- 外部 `cfquant` 启动时，会通过 `tx.get("cfquant.runtime")` 读取运行注册信息。
- 如果读取成功，请求会进入 Web 统一路由频道 `cfquant.web.request`。
- Web 根据账号绑定自动选择通用模式或高级模式。
- 如果账号配置了高级模式，但高级通道不可用，会自动回退到该账号的 ctypes 通用桥。
- 如果没有读到 Web 注册信息，`auto` 会回退为直连通用 PipeHub。

这样外部代码通常不需要关心当前运行的是通用模式还是高级模式。

## 强制指定通道

一般不建议新用户强制指定通道。排查问题或特殊部署时可以使用。

强制走 Web 统一路由：

```python
from cfquant import configure

configure(
    transport="web_lttx",
    host="127.0.0.1",
    port=2049,
    token="LTtx",
    web_request_channel="cfquant.web.request",
)
```

强制直连通用 PipeHub：

```python
from cfquant import configure

configure(
    transport="ctypes",
    pipe_name=r"\\.\pipe\cfquant_pipe_hub",
    timeout=15,
)
```

强制直连高级模式或旧 LTtx 通道：

```python
from cfquant import configure

configure(
    transport="lttx",
    host="127.0.0.1",
    port=2049,
    token="LTtx",
    timeout=15,
)
```

## 环境变量

```text
CFQUANT_TRANSPORT=auto
CFQUANT_DISCOVERY_KEY=cfquant.runtime
CFQUANT_WEB_REQUEST_CHANNEL=cfquant.web.request
CFQUANT_LTTX_HOST=127.0.0.1
CFQUANT_LTTX_PORT=2049
CFQUANT_LTTX_TOKEN=LTtx
```

## 排查要点

- 通用模式下，需要 `cfquant_pipe_hub.py` 和 QMT 里的 `CFQUANT_CTYPE_ALL_LOWLAT.py` 在线。
- 高级模式下，需要普通 QMT 的 `CFQUANT.py` 和极速交易端 QMT 的 `CFQUANT_TRADE_LOWLAT.py` 在线。
- 外部自动发现依赖 LTtx 变量，因此本地服务默认会启动 LTtx；Web 重启和定时重启会保留 LTtx，避免外部 `cfquant` Python 库通信入口中断。
- 不建议外部程序直接探测 `8765` HTTP 端口；端口可能被用户改掉，LTtx 注册信息更稳定。
- 多账号时请先在 Web“绑定”页配置资金账号、QMT 核心目录、模式和共享行情数据源。
