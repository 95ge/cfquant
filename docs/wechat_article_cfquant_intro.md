# cfquant：把 QMT、Python 策略和 Web 控制台连接起来

如果你用过 QMT 做量化交易，大概率会遇到一个问题：
QMT 本身能交易、能取行情，但外部 Python 程序、Web 页面、自动化工具想和它稳定协作，并没有那么顺手。

比如：

- 策略程序想在 QMT 外部运行，但又要调用 QMT 的行情和交易能力。
- 多个资金账号、多个 QMT 终端同时运行时，请求要准确发到对应终端。
- 想用浏览器查看桥接状态、资产、持仓、委托、成交和回调。
- 想让原来接近 `xtquant` 写法的 Python 代码尽量少改。

`cfquant` 就是为了解决这些问题做的一套本地桥接项目。

## 一句话理解 cfquant

`cfquant` 是一个运行在用户本机的 QMT 桥接工具。

它把三类东西连接起来：

1. 已经登录好的 QMT 交易终端
2. 外部 Python 策略程序
3. 浏览器里的 Web 控制台

可以把它理解成一个“本地中转站”：
外部程序不直接碰柜台，而是把请求交给 `cfquant`，再由 `cfquant` 转发给 QMT 里的桥接脚本，最后由 QMT 完成真正的行情查询、账号查询和交易操作。

整体流程可以简单理解为：

```text
外部 Python 程序 / Web 控制台
          |
          v
cfquant 本地服务 + LTtx 通信
          |
          v
QMT 侧桥接脚本
          |
          v
QMT 终端和券商柜台
```

## 它主要解决什么问题

### 1. 让外部 Python 更容易使用 QMT 能力

很多策略并不想完全写在 QMT 策略编辑器里，而是希望放在自己熟悉的 Python 项目中运行。

`cfquant` 提供了接近 `xtquant` 的兼容入口，例如：

```python
from cfquant import xtdata

tick = xtdata.get_full_tick(["000001.SZ", "600000.SH"])
print(tick)
```

交易查询也可以使用类似的方式：

```python
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("你的资金账号")
trader = XtQuantTrader("", 0, account=account)
trader.start()

asset = trader.query_stock_asset(account)
positions = trader.query_stock_positions(account)

print(asset)
print(positions)
```

对于已经写过 `xtquant` 代码的用户来说，迁移成本会更低。

### 2. 用 Web 控制台管理桥接状态

项目自带一个本地 Web 控制台，默认地址是：

```text
http://127.0.0.1:8765/
```

在这个控制台里，可以做几类常用操作：

- 查看 LTtx、普通 QMT 桥、极速交易桥是否在线
- 维护资金账号和桥接端的绑定关系
- 查询资产、持仓、委托、成交
- 进行下单、撤单等交易操作
- 查看交易回调和行情订阅数据
- 使用接口调试和教程页面辅助部署
- 对核心代码做更新和回滚

这样一来，QMT 侧是否连通、账号是否绑定、请求是否走错桥接端，都可以在浏览器里直接看到。

### 3. 支持多账号、多 QMT 场景

单账号、单 QMT 时，请求路由比较简单。
但如果一台机器上同时运行多个 QMT，或者一个系统要管理多个资金账号，就需要明确知道：

- 哪个账号属于哪个 QMT
- 哪个请求应该发给哪个桥接端
- 哪个回调是从哪个终端返回的

`cfquant` 引入了“桥接端”和“账号绑定”的概念。

简单说：

- 桥接端：代表一套 QMT 入口，通常对应一个正在运行的 QMT 客户端。
- 账号绑定：代表某个资金账号应该走哪个桥接端。

这样外部程序只需要带上资金账号，系统就可以根据绑定关系把请求转发到正确的 QMT。

## 项目由哪些部分组成

`cfquant` 不是一个单独脚本，而是一套本地工具。核心部分包括：

```text
cfquant/
  cfquant/          Python 兼容层，提供 xtdata、xttrader、xttype 等入口
  LTtx/             本地通信依赖，负责消息传输
  qmt_scripts/      放到 QMT Python 策略目录里的入口脚本
  web_dashboard/    Web 控制台页面
  cfquant_web_server.py
                    Web 控制台后端服务
  start_cfquant.bat Windows 一键启动脚本
  docs/             部署和兼容说明
```

其中，QMT 侧最关键的是三个入口：

- `CFQUANT.py`：普通桥接入口，主要负责行情、查询等能力。
- `CFQUANT_TRADE_LOWLAT.py`：极速交易桥入口，主要负责下单、撤单和交易回调。
- `tx.py`：LTtx 通信客户端，负责 Socket 连接、消息收发、心跳和日志等底层通信能力。

## 使用方式很简单

本地启动时，Windows 下可以直接双击：

```text
start_cfquant.bat
```

它会启动两个服务：

- `2049` 端口：LTtx 本地通信服务
- `8765` 端口：Web 控制台

接入 QMT 时，需要把相关目录和脚本放进 QMT 的 Python 策略目录，然后在 QMT 中加载：

```text
CFQUANT.py
CFQUANT_TRADE_LOWLAT.py
```

加载完成后，回到 Web 控制台完成账号绑定，并检查普通桥和极速交易桥是否在线。

## 适合哪些人使用

`cfquant` 比较适合这些场景：

- 已经在使用 QMT，希望把策略程序放到外部 Python 项目里运行
- 需要用 Web 页面统一查看资产、持仓、委托、成交和回调
- 需要管理多个资金账号或多个 QMT 终端
- 希望保留接近 `xtquant` 的代码写法，减少迁移成本
- 希望本地部署、本地转发，不把交易链路做成复杂的远程系统

## 需要注意什么

`cfquant` 是本地桥接工具，不是脱离 QMT 的独立交易客户端。

也就是说：

- QMT 必须正常登录账号
- QMT 侧桥接脚本必须保持运行
- 实际行情和交易能力仍然来自 QMT 和券商柜台
- 下单、撤单等交易操作需要先在测试环境或小资金场景充分验证
- 本项目不构成任何投资建议，也不保证策略收益

对于交易系统来说，最重要的不是“能下单”，而是每一次请求都能被正确路由、正确执行、正确回传，并且出现异常时能够快速定位。

这也是 `cfquant` 项目关注的重点：
把连接、转发、绑定、回调、日志和可观测性这些基础环节做好，让策略开发者可以把更多精力放在策略本身。

## 总结

简单来说，`cfquant` 做的是一件事：

让 QMT 不再只是一个独立运行的交易终端，而是可以被外部 Python 程序和 Web 控制台更方便地调用和管理。

它通过本地服务、QMT 桥接脚本和兼容接口，把行情、交易、账号查询、回调事件串成一条完整链路。

对于希望基于 QMT 搭建自动化交易工具、策略研究平台或多账号管理系统的用户来说，`cfquant` 可以作为一个实用的本地桥接基础设施。

---

发布前可选配图：

- Web 控制台首页截图
- 桥接端在线状态截图
- 账号绑定页面截图
- QMT 中加载 `CFQUANT.py` 和 `CFQUANT_TRADE_LOWLAT.py` 的截图
