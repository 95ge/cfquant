# 外部 Python 接入

本文说明外部程序如何通过 `cfquant` 调用 QMT 行情、查询和交易能力。新用户建议先在 Web 控制台完成初始化向导，并确认 QMT 侧入口脚本在线。

## 安装

在项目目录执行：

```powershell
cd D:\cfquant
pip install -e .
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
trader = XtQuantTrader("", 0, account=account)
trader.start()

asset = trader.query_stock_asset(account)
positions = trader.query_stock_positions(account)
print(asset, positions)
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
- 外部自动发现依赖 LTtx 变量，因此本地服务默认会启动 LTtx。
- 不建议外部程序直接探测 `8765` HTTP 端口；端口可能被用户改掉，LTtx 注册信息更稳定。
- 多账号时请先在 Web“绑定”页配置资金账号、QMT 核心目录、模式和共享行情数据源。
