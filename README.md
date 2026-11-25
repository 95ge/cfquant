# cfquant

## 文档入口

- [项目指南](docs/PROJECT_GUIDE.md)：部署、运行组成和配置原则
- [Web API 参考](docs/API_REFERENCE.md)：认证、行情、交易与生命周期接口
- [AI Agent 接入指南](docs/AI_AGENT_INTEGRATION.md)：权限分级、安全边界和 Python 调用示例
- [MiniQMT 迁移指南](docs/miniQMT迁移到大QMT指南.md)：从原有策略迁移到大 QMT 的步骤和兼容边界
- [CFQuant QMT Agent Skill](docs/ai-skill/cfquant-qmt/SKILL.md)：供 Codex 或兼容 agent 使用的标准技能

<p>
  <a href="https://github.com/95ge/cfquant/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/95ge/cfquant?style=flat&logo=github&label=Stars" height="18" /></a>
  <a href="https://github.com/95ge/cfquant/network/members"><img alt="GitHub forks" src="https://img.shields.io/github/forks/95ge/cfquant?style=flat&logo=github&label=Forks" /></a>
  <a href="https://github.com/95ge/cfquant/issues"><img alt="GitHub issues" src="https://img.shields.io/github/issues/95ge/cfquant?style=flat&logo=github&label=Issues" /></a>
  <a href="https://github.com/95ge/cfquant/commits/main"><img alt="GitHub last commit" src="https://img.shields.io/github/last-commit/95ge/cfquant?style=flat&logo=git&label=Last%20commit" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat" /></a>
  <img alt="Python 3.8 to 3.12" src="https://img.shields.io/badge/Python-3.8--3.12-blue?style=flat&logo=python&logoColor=white" />
</p>

## 项目简介

> **CFQuant 是“大 QMT → MiniQMT”桥接兼容层：让原有 MiniQMT / `xtquant` 策略以熟悉的接口接入大 QMT，尽量做到低成本、少改代码、平滑迁移。**

### 1. 项目定位

`cfquant` 是把大 QMT 能力整理成 MiniQMT/`xtquant` 使用体验的本地桥接层。它不会替代 QMT 终端本身，也不是另一个独立行情或交易柜台：大 QMT 负责客户端运行、行情源和交易执行，CFQuant 负责协议转换、进程通信、账户路由、对象/回调兼容以及策略接入。

项目的核心目标是**让已经在 MiniQMT 上运行的策略低成本切换到大 QMT**。原有的 `xtdata` 行情函数、`XtQuantTrader` 交易对象、`StockAccount` 账户对象、常量、查询结果和交易回调尽量保持原来的函数名、参数顺序和调用习惯。迁移时通常只需要安装 `cfquant`、配置 QMT 账户和桥接入口，并将外部包导入从 `xtquant` 调整为 `cfquant`（已经使用 `cfquant` 兼容入口的策略可以继续沿用原调用代码）；策略的主要行情、交易和回调逻辑无需重写。具体差异以[接口适配清单](docs/xtquant原版接口适配清单.md)为准。

### 2. 核心能力

| 能力 | 解决的问题 |
|---|---|
| MiniQMT / `xtquant` 兼容调用 | 保留 `xtdata`、`XtQuantTrader`、`StockAccount`、`xtconstant` 等常用入口的调用方式，让 MiniQMT 策略低成本切换到大 QMT。 |
| 大 QMT → MiniQMT 协议桥 | 把大 QMT 内部的行情、查询、交易、撤单和回调转换为外部策略熟悉的 MiniQMT/`xtquant` 兼容协议。 |
| 大 QMT 原生接口类 | 独立的 `QmtInnerApi` 面向外部数据查询、研究和实盘交易，按系统、行情、交易、回调、扩展数据与因子细分，保留原生函数名与参数，详见 [内置接口说明](docs/大QMT内置接口.md)。 |
| Web 控制台 | 在浏览器里完成账号绑定、QMT 入口脚本指引、在线检测、接口调试、版本更新和回滚。 |
| 多账号 / 多 QMT 路由 | 按 `bridge_id`、`account_type`、`account_id` 路由请求，适配多资金账号、普通账户、信用账户和多 QMT 终端。 |
| 极致模式 | 当前唯一支持的运行方式，使用自包含桥接入口，自动完成 QMT 侧环境准备和策略托管。 |
| 交易回调与行情推送 | 接收委托、成交、账号状态和行情事件，方便外部策略处理异步结果。 |
| 部署与排障闭环 | 通过日志、状态检查、教程、反馈和论坛沉淀接入问题，减少部署和维护成本。 |

### 3. 兼容方式

项目保留 MiniQMT/`xtquant` 常用模块和函数的调用习惯，但兼容不等于所有终端、所有数据权限下的行为完全一致。已有策略通常只需调整导入前缀和连接配置，不需要重写主要行情、交易和回调逻辑。尚未完整适配、参数或返回结构存在差异的接口，会在[接口适配清单](docs/xtquant原版接口适配清单.md)中标明。

### 4. 使用方式

完成部署后，大 QMT 负责运行桥接入口和实际交易，独立中心 A 负责通信分发、账号配置、算法任务及后台维护。外部 Python 程序使用 MiniQMT 风格的接口，经 LTtx 连接 A；Web 控制台提供配置、状态和操作展示。关闭页面不停止后台任务，架构与并发说明见 [独立桥接中心](docs/bridge_center.md)。

### 5. 部署建议

部署只需准备 Python、QMT 安装目录和账号绑定。当前统一使用**极致模式**，按 Web 控制台中的初始化向导完成绑定后，系统会自动启动 QMT、安装所需运行环境并部署桥接策略。

### 6. 官方资源

- 官网与问题反馈：[www.cfquant.org](https://cfquant.org)
- 版本更新日志：[docs/版本日志.md](docs/版本日志.md)
- 完整部署、极致模式和接口说明见下方“文档”目录

## 新用户先看这里

如果你第一次使用 cfquant，只需要先完成下面这条路径：

1. 在 Windows 下载并安装 QMT，无需预先登录 QMT。
2. 安装 Python 3.8–3.12；使用 Anaconda/Miniconda 时，准备运行策略的目标环境。
3. 按下方“安装方式”安装并启动 CFQuant，打开 <http://127.0.0.1:8765/>。
4. 在前端初始化向导中填写 QMT 目录、账户和运行配置，保存绑定。
5. 系统自动启动 QMT，安装 QMT 所需 Python 运行环境，并部署极致模式桥接策略。
6. 等待页面显示通道在线，先用接口测试验证行情、资金和持仓，再接入 MiniQMT 策略。

### MiniQMT 策略迁移

原有策略的迁移目标是保留业务逻辑，只替换运行后端：

```python
# 原 MiniQMT / xtquant 风格
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

# CFQuant 兼容入口
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
```

两种入口中的主要函数名、参数顺序和对象调用方式保持一致，例如 `xtdata.get_market_data`、`xtdata.subscribe_quote`、`XtQuantTrader.connect`、`XtQuantTrader.order_stock`、`query_stock_positions` 以及交易回调。迁移后只需在 Web 控制台绑定大 QMT 账户和桥接目录；不要把 MiniQMT 的本地 `userdata_mini` 路径当作大 QMT 连接地址。兼容边界、部分适配项和返回结构差异请先查阅[适配清单](docs/xtquant原版接口适配清单.md)。

### 安装方式怎么选？

| 你的情况 | 推荐做法 |
|---|---|
| 第一次部署，希望前端自动管理 Web、QMT 启动和运行环境 | 源码包部署 |
| 已有 Python 项目，只需要调用 `xtdata` / `xttrader` | PyPI 安装 |
| 使用 Anaconda/Miniconda | 激活目标环境后执行 `python -m pip` 安装 |
| QMT 无法导入 `cfquant` 或受 Python 包白名单限制 | 仍使用极致模式，由系统部署自包含入口 |

### 这几个 Python 环境分别做什么？

外部 Python 用来运行 Web 控制台、`cfquant` SDK 和你的外部策略；QMT 内部 Python 用来运行导入 QMT 的入口策略。两者可以不是同一个解释器，但 Web 配置中的 Python 路径、外部策略使用的 Python、以及你执行 `python -m pip install` 的 Python 必须对应清楚。遇到 `ModuleNotFoundError` 时，优先用同一个解释器执行：

```powershell
python -c "import sys; print(sys.executable)"
python -m pip show cfquant
```

### 怎样判断部署完成？

以下条件同时满足，才算完成基础部署：

- 浏览器可以打开 `http://127.0.0.1:8765/`。
- Web 页面状态中的 Web、LTtx 和需要的 PipeHub 通道在线。
- QMT 已由系统自动启动，绑定页显示极致模式入口策略运行中。
- 接口测试可以返回至少一只证券的行情，以及资金或持仓查询结果。
- 外部 Python 能够导入 `cfquant`，并且使用的解释器路径与安装包的解释器一致。

## 快速开始

### 环境要求

- Windows
- 已下载并安装大 QMT（无需预先登录）
- Python `3.8` - `3.12`，生产环境优先使用 `3.10` 或 `3.12`

### 运行方式

当前仅支持**极致模式**。它使用自包含的 QMT 桥接入口，避免依赖 QMT 内部导入 `cfquant`，适配存在 Python 包白名单或导入限制的 QMT 环境。用户无需手工选择通用、高级或其他模式；完成前端绑定后，系统会自动准备 QMT 运行环境并部署对应入口。

### 安装方式

#### 方式一：源码包部署（推荐）

开始前请先阅读 [QMT 部署教程](docs/QMT部署教程.md)。

新用户和生产环境优先使用源码包部署。原因很简单：cfquant 的 Web 控制台、QMT 入口脚本和本地配置是一起工作的，源码包保留完整项目目录，后续在网页里检查更新、更新 Web、回滚版本、提示 QMT 入口脚本变更都更方便。

1. 将项目解压到固定目录，例如 `D:\cfquant`。
2. 直接双击项目目录中的 `start_cfquant.bat`。启动脚本会使用项目 `.venv`（如果存在）或当前 Python，先检查当前环境是否已经安装 `cfquant`；已通过 PyPI 或其他方式安装时直接跳过，缺失时会用等价于 `python -m pip install --editable .` 的参数列表自动安装当前源码版本，不需要用户手动执行安装命令。若 Web 端口上已经运行 cfquant，会直接复用已有实例并打开页面；若端口被其他程序占用，会提示换端口或停止占用进程。

首次启动时，Web 配置中可能还没有保存 Python 解释器。此时不需要先手工填写配置：`start_cfquant.bat` 会先寻找项目 `.venv`、`CFQUANT_PYTHON_EXE`、当前或常见 Conda 安装目录，以及 `%USERPROFILE%\.conda\environments.txt` 中登记的环境，找到后用该解释器启动 Web 控制台。

如果 Anaconda/Miniconda 没有加入系统 PATH，首次启动仍可以自动识别常见安装位置。自动识别不到时，可以在启动前指定实际环境的 Python：

```bat
set CFQUANT_PYTHON_EXE=C:\Users\用户名\anaconda3\envs\quant\python.exe
start_cfquant.bat
```

Web 控制台首次启动时，如果尚无账号绑定，会直接进入“账号绑定”并打开新增窗口，使用与后续添加账号相同的配置流程。已有绑定时不再自动弹出新手向导。需要修改 Web 服务使用的 Python 解释器时，请在系统设置中保存路径；后续启动会优先使用已保存的路径，启动选择结果和失败原因记录在 `log\startup\cfquant_startup.log`。

新安装的 QMT 在前端绑定过程中会自动下载并安装 Python 运行库。安装完成后，绑定窗口会显示环境准备进度；保存绑定后系统自动启动 QMT 并应用桥接执行器，无需用户先登录或手工导入策略。

自动安装失败时，启动窗口会保持打开，并把安装日志写入 `log\startup\cfquant_startup.log`，修复 Python、网络或权限问题后重新启动即可。

项目默认使用清华 PyPI 镜像安装依赖，适合中国大陆网络环境。启动脚本、网页源码更新、`requirements.txt` 安装以及 LTtx 缺失依赖自动安装都会遵循这个设置。需要切换到企业私有源或其他镜像时，可在启动前设置 `CFQUANT_PIP_INDEX_URL` 环境变量。

#### 方式二：PyPI 安装（适合外部 Python 或不需要源码更新的环境）

PyPI 安装只负责安装 `cfquant` Python 包及其依赖，不会自动把 QMT 入口策略导入 QMT，也不会创建源码包中的 `start_cfquant.bat`。建议在目标 Python 环境中使用 `python -m pip`，避免把包装到另一个解释器：

```powershell
python -m pip install --upgrade cfquant
# 需要 ZMQ 能力时：
python -m pip install --upgrade "cfquant[zmq]"
```

安装完成后，可以直接启动带可选 Web 展示的独立中心 A：

```powershell
cfquant run
```

也可以使用 `cfquant serve`、`cfquant center` 或 `cfquant-web`，这些入口均启动独立中心 A。仅运行后台可用 `cfquant center --no-web`，管理 API 仍可调用。首次部署通常保留页面，访问 <http://127.0.0.1:8765/> 配置 QMT 目录和账号；保存绑定后，由 A 自动启动 QMT、安装运行环境并部署极致模式入口，无需手工导出或导入 QMT 策略：

```powershell
cfquant qmt-scripts --output D:\QMT\cfquant
```

上面的导出命令仅用于查看或备份入口脚本，正常部署不需要手工执行。

#### 方式三：Conda / Anaconda 环境

Conda 环境可以直接安装 PyPI 包。请先激活实际运行策略的环境，再执行安装和启动命令：

```powershell
conda activate quant
python -m pip install --upgrade cfquant
cfquant run
```

如果使用源码包，直接运行项目目录中的 `start_cfquant.bat`。即使 Conda 没有加入系统 PATH，启动脚本也会探测常见 Conda 目录；无法探测时可设置 `CFQUANT_PYTHON_EXE` 指向该环境的 `python.exe`。Web 初始化后请保存同一个解释器路径，避免 Web、外部策略和 QMT 使用不同环境。

如果 Python 环境中的 `win32api`、`win32gui` 报“DLL load failed / 找不到指定的程序”，通常是 pip 更新了组件，而 Conda 或以前安装留下的旧 `pywintypes` DLL 仍被优先加载。CFQuant 会在导入相关组件前加载当前安装包清单中的配套 DLL，并在检测详情中显示实际路径，无需手工复制 DLL。如果当前进程已经加载了不同版本，会显示冲突路径；停止 CFQuant，按检测页面生成的 PowerShell 命令逐行修复后重新启动。修复命令按实际包来源选择 pip 或 Conda；`pywin32-ctypes` 是另一个包，不表示 pywin32 由 Conda 管理。不要在 Conda 环境运行 `pywin32_postinstall`。

#### 选择建议

- 需要 Web 控制台、QMT 入口脚本、网页更新和回滚：使用**源码包部署**。
- 只需要在已有 Python 项目中调用 `cfquant.xtdata` 或 `cfquant.xttrader`：使用 **PyPI 安装**。
- 使用 Anaconda/Miniconda：优先在目标 Conda 环境中执行 `python -m pip install`，不要使用未激活环境的裸 `pip`。
- 源码包和 PyPI 包不要在同一个解释器中反复混用；源码开发时使用 `python -m pip install --editable .`，正式使用时使用 PyPI 版本。

启动后打开 <http://127.0.0.1:8765/>，按网页中的“新手初始化向导”完成账号和 QMT 目录配置。保存绑定后，A 自动安装 QMT Python 环境、启动 QMT 并部署极致模式入口，再验证资金、持仓、委托和行情。流程见 [Web 账号运行配置说明](docs/Web账号运行配置说明.md)。

重点：

- 源码部署后，网页里的“版本/更新”功能会按完整项目目录更新，适合从官网或 GitHub 拉取新版本。
- 更新时会尽量保留本地配置、数据库、日志和运行目录，便于日常升级和回滚。
- 完整项目更新会先关闭已绑定且正在运行的 QMT，按极致模式更新 `qmt_scripts/` 里的自包含入口脚本，然后自动重启对应 QMT 策略。
- 建议把源码目录固定下来，例如 `D:\cfquant`，不要频繁挪动目录。

当前仅支持**极致模式**。所有部署配置都在 Web 控制台完成，保存绑定后系统会自动准备环境、启动 QMT 并管理托管策略。

### Web 控制台绑定与初始化流程

1. 在初始化向导或“绑定”页面填写资金账号、账户类型和 QMT 目录，确认模拟／实盘及策略自动运行设置；系统固定使用极致模式。
2. 保存后系统自动部署核心包、身份配置和极致模式托管策略，弹窗显示环境安装和启动进度，无需复制代码或手工新建策略。
3. 系统自动启动 QMT 并应用入口策略，用户等待页面提示完成即可。
4. 若提示等待退出，按页面提示关闭占用中的 QMT，保持 cfquant 运行，等待环境配置完成后系统会继续启动。若部署失败，修正目录、权限或账号配置后重新保存。
5. “检测连接”可进入通道检测，随后查询资金或持仓确认账号数据。

系统负责启动 QMT 并运行极致模式托管策略；用户不需要预先登录或手工运行 QMT 模型。

cfquant Web 每次启动时都会读取已保存的绑定：只要账号处于启用状态，就会检查对应 QMT 是否已经运行；未运行时自动拉起对应的 `XtItClient.exe`，并准备极致模式运行环境和入口策略，已经运行的实例不会重复启动。

| 运行方式 | 自动部署目标 | 在线检测要求 |
|---|---|---|
| 极致模式 | 单个 QMT 中的自包含托管策略 | 查询通道和交易通道都在线 |
| 同账号独立市场 | 对应上海和深圳市场的 QMT | 沪市和深市交易通道都在线 |

多 QMT 部署需分别在前端完成绑定，系统会按绑定的 QMT 目录自动启动对应实例。完整配置及状态说明见 [Web 账号运行配置说明](docs/Web账号运行配置说明.md)。

## 常见问题先查哪里

| 现象 | 优先检查 |
|---|---|
| 双击启动窗口后立即退出 | 查看 `log\startup\cfquant_startup.log`；确认 Python 路径存在，或设置 `CFQUANT_PYTHON_EXE`。 |
| 页面打不开 | 查看最新的 `log\web\cfquant_web_server.*.stderr.log`；确认 8765 端口没有被其他程序占用。 |
| 页面在线但 QMT 不在线 | 确认 QMT 已安装、QMT 目录正确，并在绑定页重新保存配置触发自动启动。 |
| `ModuleNotFoundError: cfquant` | 在运行策略的同一个解释器中执行 `python -m pip install --upgrade cfquant`，再用 `python -c "import cfquant; print(cfquant.__file__)"` 验证。 |
| 行情为空 | 先用页面接口测试确认证券代码、周期和行情权限；标准行情异常时可对照 `xtdata.get_market_data_ex`。 |
| 不确定运行方式 | 当前仅支持极致模式，完成前端绑定后由系统自动部署。 |

完整日志位于项目的 `log` 目录。提交问题时，请附上启动日志、页面状态和使用的 Python 版本，删除账号、密码、Token、订单和持仓等敏感信息后再提交。

## 第三方项目自动化接入

`cfquant.management.RuntimeManager` 支持隐藏启动后台服务、通过代码初始化及绑定账号、配置是否自动启动 QMT，并通过官网或 GitHub 更新服务和回滚。无需打开网页，后台服务使用独立目录，更新不会覆盖第三方进程已经导入的 SDK。

```python
from cfquant.management import RuntimeManager

runtime = RuntimeManager(home=r"D:\MyApp\cfquant")
runtime.start()  # 隐藏启动；遵循各账号保存的 QMT 启动设置
runtime.initialize(
    account_id="YOUR_ACCOUNT_ID", account_type="STOCK",
    qmt_dir=r"D:\QMT", mode="lite",
    auto_start_qmt=True, strategy_autorun=True, live=False,
)
# 保存绑定后，系统自动启动 QMT 并准备极致模式运行环境。
runtime.wait_ready("YOUR_ACCOUNT_ID", timeout=120)
runtime.configure_client()

# 用户关闭 QMT 后，可通过 runtime.updates.apply() 更新后台服务。
```

查询当前运行版本、已安装版本和远端版本，以及按需自动更新：

```python
versions = runtime.version_info(force=True)
print(versions["running_version"], versions["installed_version"], versions["latest_version"])

result = runtime.updates.ensure_latest()  # 重新检查；有更新才安装并重启后台服务
print(result["status"], result["message"])
# up_to_date / 已是最新版本：不会下载、重启或关闭 QMT。
# updated / 已更新；check_failed / 无法确认远端版本；local_newer / 本地版本更高。
```

`version_info(include_remote=False)` 只查询本地版本；`updates.check(force=True)` 只检查更新。按需更新也识别同版本号的安装包变化，首次安装包哈希未知时会执行一次更新以建立记录。真正需要更新时，默认要求先关闭相关 QMT；也可显式传入 `auto_close_qmt=True` 允许自动关闭。`restart=False` 可留待调用方重启。部分 QMT 部署失败返回 `update_incomplete`，已安装但尚未重启返回 `restart_required`；执行更新失败会抛出 `ManagementError`。

外部程序复用绑定时的 `runtime` 对象，直接调用 `runtime.recover_strategy("YOUR_ACCOUNT_ID", account_type="STOCK")` 即可检测并尝试恢复已停止的 QMT 托管策略。本地托管实例由 SDK 自动读取管理凭据。也支持 `runtime.accounts.recover_strategy(...)` 和鉴权后的 `POST /api/qmt/strategies/recover`。返回值区分已提交启动、模型运行和通信确认，具体条件及示例见 [策略恢复接口](docs/第三方项目管理SDK.md#外部程序恢复-qmt-托管策略)。

模拟／实盘参数需与实际账号一致。完整的启动策略、更新接口、重复绑定行为与错误处理见 [第三方项目管理 SDK](docs/第三方项目管理SDK.md)。

## 从 `xtquant` 迁移到 `cfquant`

安装和初始化完成后，通常不需要重写原有策略。先把外部策略中指向 `xtquant` 的导入改成 `cfquant` 对应模块，再按下面的顺序验证。cfquant 负责外部 Python 与 QMT 之间的桥接，前端绑定会自动启动 QMT 并运行部署的入口策略。

### 最小改动

```python
# 原来的写法
from xtquant import xtdata, xtconstant
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

# 替换为 cfquant
from cfquant import xtdata, xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
```

默认路由是 `auto`，外部策略通常不需要手工选择 Pipe 或 LTtx。需要固定传输方式时，再使用 `cfquant.configure(...)`；具体路由说明见 [外部 Python 接入](docs/外部Python接入.md)。

### 先验证行情

```python
from cfquant import xtdata

data = xtdata.get_market_data_ex(
    field_list=["open", "close", "volume"],
    stock_list=["000001.SZ"],
    period="1d",
    count=5,
)
print(data)
```

`get_market_data_ex` 返回按证券代码组织的结果，适合先确认本地行情、证券代码和 QMT 行情权限。原有代码使用 `get_market_data` 时可以继续使用；如果某个 QMT 版本对标准接口返回空结果，cfquant 会尝试用扩展接口读取并转换结果。

### 再验证交易连接

```python
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
trader = XtQuantTrader("", account=account)

if trader.connect() != 0:
    raise RuntimeError(trader.last_connect_error or "cfquant connect failed")

print(trader.query_stock_asset(account))
print(trader.query_stock_positions(account))
trader.disconnect()
```

先完成行情、资金和持仓查询，再在模拟账号中验证委托和撤单。不要把第一次验证直接放在实盘账号上。

### 回调和接口差异

`XtQuantTrader`、`StockAccount`、常用行情查询和交易方法保持接近 `xtquant` 的调用方式，原有回调类通常可以继续使用。仍有部分 QMT 专有接口、字段和返回结构存在兼容边界，使用前请查看 [xtquant 原版接口适配清单](docs/xtquant原版接口适配清单.md) 和 [QMT 函数封装能力清单](docs/QMT函数封装能力清单.md)。

账号订阅成功后，SDK 会在后台约每两秒重新确认订阅。用户程序保持运行时，QMT、独立中心 A 或通信服务重启后，待桥接策略恢复授权、通道可用，SDK 会自动恢复该账号的新回调；默认 A 路由和显式配置的 Pipe/LTtx 直连均适用。主动 `unsubscribe(account)` 后不会再恢复该账号，`stop()` / `disconnect()` 会停止后台恢复。此机制只恢复账号订阅，不补发停机期间的回调，也不重试委托或撤单。升级 SDK 后需先重启一次用户程序加载新代码，此后无需随 QMT 重启用户程序。

推荐迁移顺序：**行情查询 → 资金/持仓 → 回调 → 模拟委托 → 模拟撤单 → 正式策略**。每一步都先在 Web 控制台接口测试和日志中确认，再进入下一步。

## Web 控制台

Web 控制台提供账号绑定、资金和持仓查询、委托和成交查询、下单和撤单、行情订阅、接口调试、部署指引以及版本更新管理。

常用脚本：

```text
start_cfquant.bat       启动
stop_cfquant.bat        停止
restart_cfquant.bat     重启
```

## 性能参考（进阶）

下面的测试用于帮助有性能需求的用户理解批量接口和不同链路的开销，不是安装或迁移成功的判断标准。

### cftrader 100 单本地基准

2026-09-11 使用本地假 QMT 交易桥复测 100 单，5 次预热、30 次采样；该基准不连接 Web、LTtx、PipeHub 或真实 QMT，不产生真实委托，只衡量 SDK 到桥接分发和本地 `passorder` 循环的协议开销。

| 路径 | RPC 次数 | 中位耗时 | 平均耗时 |
|---|---:|---:|---:|
| 批量同步 `order_stock_batch` | 1 | 4.802 ms | 4.901 ms |
| 单笔同步循环 `order_stock` x100 | 100 | 9.169 ms | 8.930 ms |
| 批量异步 `order_stock_batch_async` | 1 | 7.093 ms | 7.122 ms |
| 单笔异步循环 `order_stock_async` x100 | 100 | 9.053 ms | 9.186 ms |

批量接口用于组合调仓、批量止盈止损和撤掉一组未成委托。它的原理是外部 Python 只发一次批量 RPC，默认通过 LTtx 交给独立中心 A 路由到 QMT 后，由 QMT 本地连续调用 `passorder` 或 `cancel`，减少逐笔跨进程往返。`cftrader` 目前提供 `order_stock_batch`、`order_stock_batch_async`、`cancel_order_stock_batch` 和 `cancel_order_stock_batch_async`；批量返回只表示请求提交情况，最终成交或撤成仍以委托查询和回调为准。

## cftrader 模拟账号实测

2026-09-11 02:45 使用模拟信用账号 `900010001595` 通过 Web LTtx 统一路由连接 `acct_4b2b38c167`，对 `600000.SH` 以 8.88 元买入价、每笔 100 股测试。四条路径各提交 100 单，均返回 `submitted=100`；02:48 只读复核该批 400 笔委托状态均为 `54`（已撤），可撤数量为 0。

| 路径 | RPC 次数 | 提交耗时 | 单笔均摊 |
|---|---:|---:|---:|
| 批量同步 `order_stock_batch` | 1 | 963.252 ms | 9.6325 ms |
| 单笔同步循环 `order_stock` x100 | 100 | 23250.174 ms | 232.5017 ms |
| 批量异步 `order_stock_batch_async` | 1 | 52.578 ms | 0.5258 ms |
| 单笔异步循环 `order_stock_async` x100 | 100 | 2952.912 ms | 29.5291 ms |

## 文档

| 需求 | 文档 |
|---|---|
| QMT 综合部署教程 | [QMT 部署教程](docs/QMT部署教程.md) |
| cftrader 批量同步/异步下单与撤单 | [cftrader 批量交易与撤单](docs/cftrader批量交易.md)，含 100 单本地基准 |
| cftrader TWAP / VWAP / POV | [算法交易与共享全推行情](docs/algorithm_trading.md)，含自动订阅、生命周期和接口示例 |
| 条件单 / 仓位计算 / 下单计划 | [条件单、仓位计算与下单计划](docs/conditional_orders.md)，含止盈止损、到时平仓、回撤 / 保本保护、风险仓位及 Python / HTTP 接口 |
| 极致模式部署 | [极致模式部署指南](docs/极致模式部署指南.md) |
| 账号和 QMT 目录配置 | [Web 账号运行配置说明](docs/Web账号运行配置说明.md) |
| 虚拟机检测适配与 MAC 注入 | [QMT 启动设置](docs/qmt_launch_settings.md)，按绑定配置，默认关闭 |
| 从 miniQMT 迁移 | [miniQMT 迁移到大 QMT 指南](docs/miniQMT迁移到大QMT指南.md) |
| 官网 nativeApi 接口功能及适配状态 | [xtquant 原版接口适配清单](docs/xtquant原版接口适配清单.md) |
| Level2 六类行情、订阅回调与千档边界 | [Level2 行情适配说明](docs/Level2行情适配说明.md) |
| `xtdata` 兼容性 | [xtdata 平替追踪](docs/xtdata平替追踪.md) |
| `xttrader` 兼容性 | [xttrader 平替追踪](docs/xttrader平替追踪.md) |
| 接口能力范围 | [QMT 函数封装能力清单](docs/QMT函数封装能力清单.md) |
| AI 接口 Skill | [cfquant-qmt skill](docs/ai-skill/cfquant-qmt/SKILL.md) |
| 日志、更新和回滚 | [运维与更新](docs/运维与更新.md) |
| 版本更新日志 | [版本日志](docs/版本日志.md) |

更详细的教程也可以在 Web 控制台的“教程”页面查看。

## Star History

<a href="https://star-history.com/#95ge/cfquant&Date"><img src="https://api.star-history.com/svg?repos=95ge%2Fcfquant&type=Date" alt="Star History Chart" width="500" /></a>



## 项目交流群
<img src="docs/f5f1d14256e57023dd67513481f16718.jpg" alt="cfquant 项目交流群二维码" width="280" />


## 联系作者
- #### 地球号:shcfquant,请注明来意
- #### 邮箱:litaoflyme@163.com


## 许可证

本项目采用 [MIT License](LICENSE) 开源。
