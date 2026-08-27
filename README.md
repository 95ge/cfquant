# cfquant

## 官网与反馈

官网地址：[https://cfquant.org](https://cfquant.org)

友情提示：使用过程中如果遇到问题，或者有改进建议，欢迎在官网中向我们反馈。

cfquant 是面向大 QMT 的本地转接层，目标是替代 miniQMT 的常见接入方式，把大 QMT 已有的行情、查询、交易和回调能力转接给 Web 控制台与外部 Python 程序使用。

项目重点能力：

- **miniQMT 无缝切换**：外部程序可按接近 `xtquant` 的方式导入 `cfquant`，默认自动识别通用模式或高级模式。
- **大 QMT 功能转接**：通过 QMT 策略脚本承接行情订阅、账户查询、委托成交、下单撤单和回调事件。
- **多账号运行**：支持单账号快速部署，也支持普通账户、信用账户、多账号、多 QMT 独立绑定，并可指定共享行情数据源。
- **低延迟链路**：通用模式使用 ctypes named pipe；高级模式可接入极速交易端，进一步压低下单和撤单耗时。

新用户默认推荐使用**通用模式**：一个 QMT、一个入口脚本即可跑通。需要进一步压低下单、撤单延迟时，再切换到**高级模式**。

## 先看这里

| 你要做什么 | 推荐入口 |
|---|---|
| 第一次部署和验证 | 打开 Web 后按“新手初始化向导”操作 |
| 单账号快速跑通 | 使用通用模式，QMT 加载 `CFQUANT_CTYPE_ALL_LOWLAT.py` |
| QMT 白名单限制无法导入核心包 | 使用极致模式，QMT 只加载 `CFQUANT_LITE.py` |
| 普通/信用账户、多账号、多 QMT | 在 Web“绑定”页逐个配置账号类型、账号和 QMT 核心目录 |
| 追求更低交易延迟 | 使用高级模式，需要普通 QMT + 极速交易端 QMT |
| 从 miniQMT / `xtquant` 切换 | 看 [miniQMT 迁移到大 QMT 指南](docs/miniqmt_to_bigqmt_migration.md)、[外部 Python 接入](docs/README_外部Python接入.md) |
| 日志、重启、更新、回滚 | 看 [运维与更新](docs/README_运维与更新.md) |

## 模式区别

| 模式 | QMT 侧部署 | 通信链路 | 适合场景 |
|---|---|---|---|
| 通用模式 | 一个 QMT 加载 `CFQUANT_CTYPE_ALL_LOWLAT.py` | Web / 外部 Python -> PipeHub -> ctypes 单文件桥 -> QMT | 快速部署、单账号验证、多数常规使用 |
| 极致模式 | 一个 QMT 加载 `CFQUANT_LITE.py` | Web / 外部 Python -> PipeHub -> 纯 ctypes 自包含桥 -> QMT | QMT 白名单限制、无法导入 `cfquant` 核心包的环境 |
| 高级模式 | 两个 QMT：普通 QMT 加载 `CFQUANT.py`，极速交易端 QMT 加载 `CFQUANT_TRADE_LOWLAT.py` | Web / 外部 Python -> LTtx -> 普通桥 + 极速交易桥 -> QMT | 追求更低下单、撤单延迟 |

关键规则：

- 通用模式不经过 LTtx，请求走 PipeHub named pipe。
- 极致模式同样走 PipeHub named pipe，但 QMT 入口脚本完全自包含，不需要导入 `cfquant` 包。
- 本地服务默认仍会启动 LTtx，方便高级模式、旧客户端和外部自动发现接入。
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

3. 打开 Web 控制台：

   ```text
   http://127.0.0.1:8765/
   ```

4. 首次打开网页后，按“新手初始化向导”完成账号、模式和 QMT 目录配置。

5. 在 QMT 中加载对应入口脚本，再回到网页验证资金、持仓、委托和行情。

常用运维脚本：

```text
start_cfquant.bat      启动本地服务
stop_cfquant.bat       停止本地服务
restart_cfquant.bat    重启本地服务
启动cfquant.bat        中文启动脚本
停止cfquant.bat        中文停止脚本
重启cfquant.bat        中文重启脚本
```

## 文档导航

| 分类 | 文档 |
|---|---|
| 部署教程 | [通用模式部署指南](docs/通用模式部署指南.md)、[极致模式部署指南](docs/极致模式部署指南.md)、[高级模式部署指南](docs/高级模式部署指南.md) |
| 账号配置 | [账号运行配置说明](docs/web_account_runtime_configuration.md) |
| 信用账户 | [信用账户支持方案](docs/信用账户支持方案.md) |
| 外部接入 | [miniQMT 迁移到大 QMT 指南](docs/miniqmt_to_bigqmt_migration.md)、[外部 Python 接入](docs/README_外部Python接入.md) |
| 运维更新 | [运维与更新](docs/README_运维与更新.md) |
| 接口兼容 | [xtdata 兼容说明](docs/xtdata_compatibility.md)、[xttrader 兼容说明](docs/xttrader_compatibility.md) |
| 能力矩阵 | [QMT 接口能力矩阵](docs/qmt_function_capability_matrix.md) |
| 测试报告 | [延迟测试报告](docs/ctypes_pipe_vs_lttx_latency_20260813.md) |
| 项目背景 | [微信文章思路整理](docs/wechat_article_cfquant_intro.md) |

更详细的图文部署教程也可以直接在 Web 控制台的“教程”页面查看。README 只保留入口说明，避免首次阅读成本过高。

## Web 控制台

Web 控制台主要页面：

- 首页：账号选择、资金和持仓概览。
- 绑定：单账号、多账号、QMT 核心目录、模式和共享行情数据源配置。
- 交易：下单、批量下单、撤单、委托、成交、持仓。
- 行情：快照、K 线、全推订阅。
- 接口调试：按接口生成请求并查看返回。
- 教程：通用模式和高级模式的部署引导。
- 设置：通信模式、日志清理、QMT 日志语言、Web 更新和 QMT 核心更新。

全推行情不会在非必要页面默认推送到浏览器。只有进入相关界面或主动订阅后，网页才会接收实时行情，避免长时间打开首页造成浏览器卡顿。

## 外部 Python

安装后可以直接用 `cfquant` 替代常见 `xtquant` 导入：

```powershell
cd D:\cfquant
pip install -e .
```

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

tick = xtdata.get_full_tick(["000001.SZ"])
print(tick)
```

默认 `transport=auto`，通常不需要手动调用 `configure()`。详细路由规则、强制指定通道和环境变量见 [外部 Python 接入](docs/README_外部Python接入.md)。

## 实测延迟

测试环境为同一台本地机器和同一套 QMT 环境，仅用于判断量级，不代表固定承诺。

交易时间真实下单撤单测试中，普通 QMT 下单约 `175.897 ms`，极速交易端约 `1.026 ms`，ctypes 交易通道约 `20.147 ms`。非交易时间、午间休市或首次启动时，行情源、柜台连接、本地缓存和 QMT 回调节奏可能不活跃，请求耗时会明显高于交易时间。

完整交易时间、非交易时间、行情快照、查询、下单和撤单数据见 [延迟测试报告](docs/ctypes_pipe_vs_lttx_latency_20260813.md)。

## 目录结构

```text
cfquant/
  cfquant/             核心 Python 包
  qmt_scripts/         QMT 入口脚本
  web_dashboard/       Web 控制台静态资源
  docs/                部署、兼容、运维和测试文档
  LTtx/                高级模式和旧 socket 客户端依赖
  cfquant_web_server.py
                       Web 控制台后端
  cfquant_pipe_hub.py  通用模式 PipeHub
  start_cfquant.bat    一键启动
  stop_cfquant.bat     一键停止
  restart_cfquant.bat  一键重启
```

## 版本日志

### core_20260828_01

- 新增 `CFQUANT_LITE.py` 极致模式入口，QMT 侧只依赖标准库和 `ctypes`，用于白名单限制导致无法导入 `cfquant` 核心包的环境。
- 极致模式启动日志改为优先中文输出，并修复 QMT 以 `<string>` 执行时 `__file__` 不存在导致运行版本上报失败的问题。
- QMT 启动后会向网页端上报核心版本、入口脚本、入口版本和运行模式，版本弹窗可直接看到当前 QMT 加载的是 `CFQUANT_LITE.py` 还是其他入口。
- Web 控制台新增极致模式选项和网页端部署教程，静态资源版本参数同步更新为 `web_20260828_01`。

### web_20260827_01

- Web 后端后台 PowerShell 状态探测改为隐藏窗口执行，避免部署运行后定时弹出 PowerShell 窗口。
- 同步 Web 控制台版本为 `web_20260827_01`，静态资源版本参数同步更新。

### core_20260821_02

- `xtdata` 新增一批同名条件平替入口，覆盖交易时段、板块维护、公式系统、L2 行情、表格数据和下载类补充接口。
- QMT 桥接层新增通用 `xtdata.*` callable 转发：当前运行的 QMT 暴露对应函数时直接调用；未暴露时返回明确的不支持错误。
- 订阅类条件入口支持通过 `callback_event` 转发回调事件，适配公式订阅和 L2 订阅等长期 callback 场景。
- 接口页“xtquant 平替说明”改为“已实装 / 条件平替 / 不建议强行平替”三类，避免把 MiniQMT 客户端连接管理误标为可桥接能力。
- 同步 Web 控制台版本为 `web_20260821_03`，静态资源版本参数同步更新。

### core_20260821_01

- QMT 通用模式和高级模式入口新增运行时核心版本上报，桥接启动和 ContextInfo 就绪时都会上报当前运行的 `cfquant` 核心版本。
- Web 版本检测改为以 QMT 运行时上报为准，不再用磁盘 `version.py` 判断“当前运行的 QMT 核心版本”。
- 未收到运行时上报时，版本页明确提示用户先运行或重启对应 QMT 桥接脚本后再查看。
- 顶部版本弹窗和设置页版本信息简化展示，突出 QMT 运行时、磁盘核心、远端版本和对比状态。
- 同步 Web 控制台版本为 `web_20260821_02`。

### core_20260818_01

- 新增信用账户第一阶段支持：账号绑定、初始化向导、首页账号下拉、状态查询、资金持仓、委托成交、下单撤单和回调过滤均贯通 `account_type=STOCK/CREDIT`。
- 后端账号路由升级为 `account_key = bridge_id:account_type:account_id`，支持一个 QMT 实例同时承载多个普通账户和多个信用账户，并兼容历史普通账户配置。
- 新增 `POST /api/credit/query` 和 `POST /api/credit/probe`，用于信用专项查询和只读能力探测；信用专项委托动作暂不开放，需先完成券商 QMT 常量验证。
- 前端版本同步为 `web_20260818_01`，接口调试页新增信用查询和信用能力探测入口。

### core_20260817_13

- 修复 QMT 以 `<string>` 方式执行入口脚本时 `__file__` 不存在导致通用模式启动失败的问题。
- 通用模式和高级模式三个 QMT 入口脚本统一入口目录识别逻辑，优先使用配置目录、当前工作目录和有效核心目录。
- 修复入口脚本路径前置顺序，避免同级旧 `cfquant` 包抢先导入。

### core_20260817_12

- QMT 核心更新后的重启提醒改为自定义弹窗，替代浏览器原生 alert。
- 页面内更新提醒改为结构化卡片，显示目标目录、版本、重启步骤和入口文件处理说明。
- 同步前端版本为 `web_20260817_12`，方便通过版本弹窗判断浏览器缓存和服务端版本。

### core_20260817_11

- 左上角版本信息弹窗拆分显示核心版本、前端版本、GitHub 版本和版本状态。
- 前端版本同时显示浏览器端与服务端版本，便于判断浏览器是否仍在使用旧缓存。
- 统一 Web 服务、LTtx 注册信息和版本接口中的前端版本字段。

### core_20260817_10

- 优化左上角版本信息弹窗，拆分为版本摘要、更新日志和操作区，降低信息堆叠感。
- 版本弹窗滚动区域改为深色同色系滚动条，并适配窄屏显示。
- 更新静态资源版本参数，避免浏览器缓存旧版弹窗样式。

### core_20260817_09

- QMT 核心更新新增进度窗口，覆盖 GitHub 更新、zip 更新和回滚流程。
- zip 更新显示浏览器上传进度；更新完成或失败后保留窗口状态，方便用户确认当前步骤。
- 更新完成后继续显示 QMT 重启和入口文件手动更新提醒，减少用户遗漏后续操作。

### core_20260817_08

- QMT 侧日志翻译规则补齐，覆盖高级模式普通桥、极速交易桥、交易明细查询和普通桥合并响应等英文日志。
- Web“QMT 日志”设置新增日志显示开关，默认开启，可同时保存语言和是否输出桥接日志。
- 账号绑定写入的 `cfquant_bridge_config.json` 新增 QMT 日志语言和日志开关，QMT 入口重启后可继续沿用网页配置。

### core_20260817_07

- README 改为入口型结构，突出 miniQMT 替代、大 QMT 功能转接、多账号、低延迟和 `xtquant` 无缝切换能力。
- 将外部 Python 接入说明迁移到 `docs/README_外部Python接入.md`。
- 将启停、日志、版本探测、在线更新和回滚说明迁移到 `docs/README_运维与更新.md`。

### core_20260817_06

- 更新成功后增加 QMT 侧重启提醒：QMT 核心更新、zip 更新和回滚完成后，明确提示用户停止并重新启动对应 QMT 入口脚本。
- Web 项目更新/回滚会检测 `qmt_scripts/CFQUANT*.py` 是否发生变化；如果涉及入口脚本，提示用户手动更新 QMT 加密入口文件后再启动。
- 更新结果页新增中文运维提示区，避免用户只看到 JSON 结果而遗漏后续操作。

### core_20260817_05

- 左上角版本徽标在远端检查时显示“检查中...”和转动状态点，避免用户误以为点击无响应。
- 版本弹层新增“重新检查”“立即更新 Web”“更新 QMT 核心”“更新设置”操作入口。
- 设置页更新模块拆分为 Web 项目更新和 QMT 核心更新；Web 项目更新支持 GitHub、zip、备份、回滚和更新后自动重启。
- Web 项目更新默认保留本地配置、数据库、日志、运行缓存和 LTtx 本地配置，失败时按更新前备份恢复。

### core_20260817_04

- 版本探测适配内网环境：GitHub 不可访问时仅在网页顶部提示“版本探测失败”，不影响交易、行情、账号路由和本地功能。
- 版本徽标继续保留本地版本和本地更新日志展示；远端检查失败原因可在悬停弹层中查看。

### core_20260817_03

- Web 左上角新增版本徽标，支持悬停查看当前版本、版本日志和远端检查结果。
- 新增 `/api/version` 项目版本接口，可从本地 README 解析当前更新日志，并异步探测 GitHub README 中的新版本日志。
- 版本检查增加短时缓存，GitHub 不可访问时只显示检查失败原因，不影响交易、行情和账号路由。

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
