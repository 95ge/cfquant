# cfquant

cfquant 是面向 QMT 的本地桥接项目。它把 Web 控制台、外部 Python 程序和 QMT 策略脚本连接起来，统一转发行情订阅、账户查询、交易指令和回调事件。

默认推荐使用**通用模式**：一个 QMT、一个入口脚本即可跑通。需要更低交易延迟时，再切换到**高级模式**。

## 快速选择

| 模式 | QMT 侧部署 | 通信链路 | 适合场景 |
|---|---|---|---|
| 通用模式 | 一个 QMT 加载 `CFQUANT_CTYPE_ALL_LOWLAT.py` | Web -> PipeHub -> ctypes 单文件桥 -> QMT | 快速部署、单账号验证、多数常规使用 |
| 高级模式 | 两个 QMT：普通 QMT 加载 `CFQUANT.py`，极速交易端 QMT 加载 `CFQUANT_TRADE_LOWLAT.py` | Web / 外部 Python -> LTtx -> 普通桥 + 极速交易桥 -> QMT | 追求更低下单、撤单延迟 |

关键规则：

- 通用模式不经过 LTtx，请求走 PipeHub named pipe。
- 本地服务默认仍会预启动 LTtx，方便高级模式或旧客户端随时接入。
- 外部 Python 默认先通过 LTtx 读取 Web 写入的运行注册信息，再进入 Web 统一路由；不依赖 `8765` HTTP 端口。
- 高级模式必须打开两个 QMT。不要在同一个 QMT 里同时运行 `CFQUANT.py` 和 `CFQUANT_TRADE_LOWLAT.py`。
- 通用模式和高级模式里的普通 QMT 可以部署在同一个 QMT；高级模式的极速交易端需要单独打开另一个 QMT。
- 账号配置为高级模式时，系统优先走高级通道；高级通道不可用时自动回退到该账号的 ctypes 通用桥。

## 快速启动

1. 解压项目到固定目录，例如：

   ```text
   D:\cfquant
   ```

2. 双击运行：

   ```text
   start_cfquant.bat
   ```

   默认打开：

   ```text
   http://127.0.0.1:8765/
   ```

3. 首次打开网页后，先完成初始化向导：

   - 填写默认资金账号；
   - 新用户选择通用模式；
   - QMT 核心目录建议填写为 QMT 安装目录下的 `bin.x64`，例如 `D:\国金证券QMT交易端\bin.x64`；
   - 目录可留空，但自动更新、脚本定位和多 QMT 身份写入会失效。

4. 在 QMT 中加载对应入口脚本，然后回到网页验证资金、持仓、委托和行情。

运维脚本：

```text
start_cfquant.bat      启动本地服务
stop_cfquant.bat       停止本地服务
restart_cfquant.bat    重启本地服务
启动cfquant.bat        中文启动脚本
停止cfquant.bat        中文停止脚本
重启cfquant.bat        中文重启脚本
```

## QMT 部署

QMT 核心目录指 QMT 安装目录里的 `bin.x64`。推荐目录结构如下。

通用模式：

```text
QMT安装目录/
  bin.x64/
    cfquant/
    cfquant_bridge_config.json   可由网页账号绑定自动写入
  python/
    CFQUANT_CTYPE_ALL_LOWLAT.py
```

高级模式普通 QMT：

```text
普通QMT安装目录/
  bin.x64/
    cfquant/
    cfquant_bridge_config.json
  python/
    CFQUANT.py
```

高级模式极速交易端 QMT：

```text
极速交易端QMT安装目录/
  bin.x64/
    cfquant/
    cfquant_bridge_config.json
  python/
    CFQUANT_TRADE_LOWLAT.py
```

说明：

- `cfquant/` 核心包复制到目标 QMT 的 `bin.x64/cfquant/`。
- QMT 入口脚本来自项目 `qmt_scripts/` 目录。
- `tx.py` 已内置为 `cfquant.tx`，不需要单独复制到 QMT 的 `python/` 目录。
- 网页保存账号绑定后，会把该 QMT 的 `bridge_id` 写入 `bin.x64/cfquant_bridge_config.json`。

## 账号绑定

默认是单账号、单 QMT：使用 `default` 内部通道即可。

需要多账号时，在网页“绑定”页面为每个账号配置：

- 资金账号；
- QMT 核心目录，建议填写；
- 通用模式或高级模式；
- 是否作为共享行情数据源。

多账号区分规则：

- 同一个 QMT 登录多个账号：多个账号共用同一个内部通道，请求按 `account_id` 执行。
- 多个 QMT 分别运行不同账号：每个 QMT 使用独立内部通道，网页根据 QMT 核心目录自动分配 `bridge_id`。
- 多账号行情默认只选一个共享数据源，避免重复订阅全推行情。

更完整的配置说明见 [web_account_runtime_configuration.md](docs/web_account_runtime_configuration.md)。

## 外部 Python

安装：

```powershell
cd D:\cfquant
pip install -e .
```

替代原生 `xtquant` 导入：

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
```

默认不需要调用 `configure()`。外部 `cfquant` 的默认 `transport=auto`，会先通过 LTtx 的 `tx.get("cfquant.runtime")` 读取 Web 服务写入的运行注册信息；如果 Web 已注册统一路由频道，请求会发到 `cfquant.web.request`，由 Web 根据账号配置自动选择通用模式或高级模式。

```python
from cfquant import xtdata

tick = xtdata.get_full_tick(["000001.SZ"])
print(tick)
```

需要强制指定接入方式时再调用 `configure()`。

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
configure(
    transport="lttx",
    host="127.0.0.1",
    port=2049,
    token="LTtx",
    timeout=15,
)
```

相关环境变量：

```text
CFQUANT_TRANSPORT=auto
CFQUANT_DISCOVERY_KEY=cfquant.runtime
CFQUANT_WEB_REQUEST_CHANNEL=cfquant.web.request
CFQUANT_LTTX_HOST=127.0.0.1
CFQUANT_LTTX_PORT=2049
CFQUANT_LTTX_TOKEN=LTtx
```

示例：

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

tick = xtdata.get_full_tick(["000001.SZ"])
print(tick)

account = StockAccount("2220009880")
trader = XtQuantTrader("", 0, account=account)
trader.start()

asset = trader.query_stock_asset(account)
positions = trader.query_stock_positions(account)
print(asset, positions)
```

外部 Python 默认不再需要读取 `8765` HTTP 端口。Web 服务会把当前模式、版本、账号绑定、共享数据源和统一请求频道维护到 LTtx 变量中；外部 `cfquant` 启动时读取这些变量并走统一路由。如果没有读到 Web 注册信息，`auto` 会回退直连通用 PipeHub。

## Web 功能

Web 控制台包含：

- 首页：账号选择、模式状态、资金和持仓概览；
- 绑定：单账号、多账号、QMT 核心目录和共享数据源配置；
- 交易：下单、批量下单、撤单、委托、成交、持仓；
- 行情：快照、K 线、全推订阅；
- 接口调试：按接口生成请求并查看返回；
- 教程：通用模式和高级模式的部署引导；
- 设置：通信模式、日志清理、QMT 日志语言、更新管理。

全推行情不会在非必要页面默认推送到浏览器。只有进入相关界面或主动订阅后，网页才会接收实时行情，避免长时间打开首页造成浏览器卡顿。

## 数据下载

- 历史行情：已接入 `xtdata.download_history_data` 和 `download_history_data2`。
- 下载进度：如果 QMT 提供 `download_history_data2`，网页可通过回调事件显示进度；如果只能回退旧接口，只能显示请求生命周期。
- 财务数据：大 QMT 官网脚本侧未提供可直接调用的财务下载函数。`download_financial_data` 和网页财务下载入口目前用于读取、校验本地已下载财务数据；真实财务下载仍需要先在 QMT 客户端“数据管理 - 财务数据下载”中完成。

能力矩阵见 [qmt_function_capability_matrix.md](docs/qmt_function_capability_matrix.md)。

## 日志运维

本地服务日志统一写入项目根目录 `log/`：

```text
log/
  cfquant_web_server.runtime.log
  cfquant_pipe_hub.stdout.log
  cfquant_pipe_hub.stderr.log
  lttx_server.stdout.log
  lttx_server.stderr.log
  cfquant_qmt_bridge.log
  tx_log/
  lttx/
```

默认保留最近 30 天日志。Web 服务后台会定期自动清理，也可以在“设置 - 日志清理”中手动执行。

根目录历史遗留的 `*.log`、`log_data/`、`tx_log/` 也纳入清理和 Git 忽略。QMT `userdata/log` 清理默认关闭，需要用户在网页里显式启用。

常用环境变量：

```text
CFQUANT_LOG_DIR=D:\cfquant\log
CFQUANT_LOG_RETENTION_DAYS=30
CFQUANT_LOG_CLEANUP_INTERVAL_SECONDS=21600
CFQUANT_PIPE_HUB_VERBOSE_EVENTS=0
```

`CFQUANT_PIPE_HUB_VERBOSE_EVENTS=1` 可打开 PipeHub 高频事件日志，只建议排查问题时临时使用。

## 实测延迟

测试环境为同一台本地机器和同一套 QMT 环境，仅用于判断量级，不代表固定承诺。

交易时间稳定版测试时间：`2026-08-13 13:50` 至 `14:06`。

| 方案 | 心跳 avg | 行情快照 avg | 资产查询 avg | 委托查询 avg |
|---|---:|---:|---:|---:|
| 普通 QMT / LTtx 普通通道 | 69.936 ms | 102.775 ms | 255.245 ms | 259.459 ms |
| 极速交易端 / LTtx 交易通道 | 2.137 ms | 1.344 ms | 1.789 ms | 3.585 ms |
| ctypes 普通通道 | 39.515 ms | 78.952 ms | 240.572 ms | 256.987 ms |
| ctypes 交易通道 | 35.659 ms | 42.791 ms | 186.919 ms | 182.323 ms |

真实下单撤单测试时间：`2026-08-13 14:40`，标的 `000001.SZ`，买入 `100` 股，限价 `11.1`，下单后等待 `3` 秒撤单。

| 方案 | 下单请求 | 定位真实委托号 | 撤单请求 |
|---|---:|---:|---:|
| 普通 QMT | 175.897 ms | 326.104 ms | 128.918 ms |
| 极速交易端 | 1.026 ms | 57.016 ms | 1.290 ms |
| ctypes 交易通道 | 20.147 ms | 201.088 ms | 24.098 ms |

非交易时间、午间休市或首次启动时，行情源、柜台连接、本地缓存和 QMT 回调节奏可能不活跃，请求耗时会明显高于交易时间。完整数据见 [ctypes_pipe_vs_lttx_latency_20260813.md](docs/ctypes_pipe_vs_lttx_latency_20260813.md)。

## 目录结构

```text
cfquant/
  cfquant/             核心 Python 包
  qmt_scripts/         QMT 入口脚本
  web_dashboard/       Web 控制台静态资源
  docs/                部署、兼容和测试文档
  LTtx/                高级模式和旧 socket 客户端依赖
  cfquant_web_server.py
                       Web 控制台后端
  cfquant_pipe_hub.py  通用模式 PipeHub
  start_cfquant.bat    一键启动
  stop_cfquant.bat     一键停止
  restart_cfquant.bat  一键重启
```

## 更多文档

- [通用模式部署指南](docs/通用模式部署指南.md)
- [高级模式部署指南](docs/高级模式部署指南.md)
- [账号运行配置说明](docs/web_account_runtime_configuration.md)
- [xtdata 兼容说明](docs/xtdata_compatibility.md)
- [xttrader 兼容说明](docs/xttrader_compatibility.md)
- [QMT 接口能力矩阵](docs/qmt_function_capability_matrix.md)
- [延迟测试报告](docs/ctypes_pipe_vs_lttx_latency_20260813.md)

## 版本日志

### core_20260817_02

- 外部 `cfquant` 默认接入方式改为 `transport=auto`。
- Web 服务启动后通过 LTtx 的 `tx.put()` 维护 `cfquant.runtime` 注册信息，包含系统版本、当前模式、账号绑定、共享数据源、桥接端和统一请求频道。
- 外部 Python 通过 LTtx 的 `tx.get()` 读取注册信息，优先把请求发送到 `cfquant.web.request`，由 Web 统一完成通用模式/高级模式识别、账号路由和高级失败回退。
- 不再依赖 `8765` HTTP 端口探测；只有强制直连 PipeHub、强制直连 LTtx 或特殊部署时才需要调用 `configure()`。

### core_20260817_01

- 新增 ctypes named pipe 通用模式，默认推荐单账号、单 QMT、单文件部署。
- 新增 PipeHub，本地 Web、外部 Python 和 QMT 通用桥通过 named pipe 通信。
- 高级模式保留普通 QMT + 极速交易端双桥方案，并支持账号级高级优先、ctypes 自动回退。
- Web 端新增首次初始化向导、账号绑定、多账号内部通道、共享行情数据源和通用端状态展示。
- 完成 xtdata/xttrader 多个查询、行情订阅、历史数据下载、交易下单撤单兼容接入；财务下载降级为本地数据校验。
- 增加实测延迟文档和 README 延迟对比，覆盖交易时间、非交易时间、真实下单撤单。
- 优化全推行情 WebSocket 推送策略，非必要页面不主动推送全量行情，降低浏览器长时间停留导致的卡顿风险。
- 日志统一写入 `log/` 目录，默认保留最近 30 天，并纳入 Git 忽略；PipeHub 高频事件日志默认关闭，需要排查时设置 `CFQUANT_PIPE_HUB_VERBOSE_EVENTS=1`。
