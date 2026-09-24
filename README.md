# cfquant

<p>
  <a href="https://github.com/95ge/cfquant/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/95ge/cfquant?style=flat&logo=github&label=Stars" height="18" /></a>
  <a href="https://github.com/95ge/cfquant/network/members"><img alt="GitHub forks" src="https://img.shields.io/github/forks/95ge/cfquant?style=flat&logo=github&label=Forks" /></a>
  <a href="https://github.com/95ge/cfquant/issues"><img alt="GitHub issues" src="https://img.shields.io/github/issues/95ge/cfquant?style=flat&logo=github&label=Issues" /></a>
  <a href="https://github.com/95ge/cfquant/commits/main"><img alt="GitHub last commit" src="https://img.shields.io/github/last-commit/95ge/cfquant?style=flat&logo=git&label=Last%20commit" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat" /></a>
  <img alt="Python 3.8 to 3.12" src="https://img.shields.io/badge/Python-3.8--3.12-blue?style=flat&logo=python&logoColor=white" />
</p>

## 项目简介

> **CFQuant 是 MiniQMT 的开源替代方案：让原有 `xtquant` / 外部 Python 策略低成本接入大 QMT。**

### 1. 项目定位

`cfquant` 是面向大 QMT 的本地桥接层，专注解决 MiniQMT 迁移、大 QMT 外部 Python 调用、账号路由、交易回调和 Web 可观测这些实际问题。它不会替代 QMT 终端本身，而是把大 QMT 已有的行情、查询、交易和回调能力整理成更接近 `miniQMT` / `xtquant` 的调用方式，让旧策略可以更低成本迁移到大 QMT 环境。

### 2. 核心能力

| 能力 | 解决的问题 |
|---|---|
| MiniQMT / `xtquant` 兼容调用 | 原有外部 Python 策略可以沿用接近 `xtdata`、`XtQuantTrader`、`StockAccount` 的写法，降低迁移成本。 |
| 大 QMT 本地桥接 | 把大 QMT 内部的行情、查询、交易、撤单和回调能力桥接给外部 Python 程序和 Web 控制台。 |
| Web 控制台 | 在浏览器里完成账号绑定、QMT 入口脚本指引、在线检测、接口调试、版本更新和回滚。 |
| 多账号 / 多 QMT 路由 | 按 `bridge_id`、`account_type`、`account_id` 路由请求，适配多资金账号、普通账户、信用账户和多 QMT 终端。 |
| 通用、极致、高级三种模式 | 普通环境快速跑通；受限 QMT 使用自包含入口；低延迟场景可拆分普通桥和交易桥。 |
| 交易回调与行情推送 | 接收委托、成交、账号状态和行情事件，方便外部策略处理异步结果。 |
| 部署与排障闭环 | 通过日志、状态检查、教程、反馈和论坛沉淀接入问题，减少部署和维护成本。 |

### 3. 兼容方式

项目尽量保持 `miniQMT` / `xtquant` 常用接口的调用习惯。已有外部 Python 策略通常只需要调整连接方式或少量配置，不需要重写主要的行情和交易逻辑。具体接口能力和兼容边界请以项目文档为准。

### 4. 使用方式

完成部署后，QMT 负责运行桥接策略，`cfquant` 负责提供本地通信和接口转发。外部 Python 程序可以继续使用熟悉的接口访问 QMT 能力，Web 控制台则用于账号绑定、状态检查、接口测试、策略部署和日常运维。

### 5. 部署建议

部署需要同时配置本地 Python 环境、QMT 目录、账号绑定和 QMT 入口策略。建议第一次使用时优先选择**通用模式**，按 [QMT 部署教程](docs/QMT部署教程.md) 和 Web 控制台中的初始化向导逐步完成；高级模式和两地多中心需要额外配置多个 QMT 或多个市场入口。

### 6. 官方资源

- 官网与问题反馈：[www.cfquant.org](https://cfquant.org)
- 版本更新日志：[docs/版本日志.md](docs/版本日志.md)
- 完整部署、模式选择和接口说明见下方“文档”目录

## 新用户先看这里

如果你第一次使用 cfquant，只需要先完成下面这条路径：

1. 安装 Python 3.8–3.12，生产环境建议 Python 3.10 或 3.12；使用 Anaconda/Miniconda 时，先确定实际运行策略的环境名称。
2. 按下方“安装方式”选择源码包或 PyPI。第一次部署、需要 Web 更新和 QMT 脚本管理时，优先选择源码包。
3. 启动 `start_cfquant.bat`，或在已安装包的环境中执行 `cfquant run`。
4. 打开 <http://127.0.0.1:8765/>，按初始化向导填写 QMT 目录、账号和运行模式。
5. 在绑定页导入并运行 QMT 入口策略，等待页面显示通道在线。
6. 先用“接口测试”验证行情、资金和持仓，再接入自己的策略。

### 我应该选择哪种方式？

| 你的情况 | 推荐做法 |
|---|---|
| 第一次部署，希望系统自动管理 Web、QMT 脚本和更新 | 源码包 + 通用模式 |
| 已有 Python 项目，只需要调用 `xtdata` / `xttrader` | PyPI 安装 |
| 使用 Anaconda/Miniconda | 激活目标环境后执行 `python -m pip` 安装 |
| QMT 无法导入 `cfquant` 或受 Python 包白名单限制 | 极致模式 |
| 需要拆分行情与低延迟交易链路 | 高级模式，准备两个 QMT 环境 |

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
- QMT 已登录，绑定页显示入口策略运行中。
- 接口测试可以返回至少一只证券的行情，以及资金或持仓查询结果。
- 外部 Python 能够导入 `cfquant`，并且使用的解释器路径与安装包的解释器一致。

## 快速开始

### 环境要求

- Windows
- 已安装并登录大 QMT
- Python `3.8` - `3.12`，生产环境优先使用 `3.10` 或 `3.12`

### 模式选择

部署前先根据 QMT 环境选择模式：

| 模式 | QMT 入口 | 适用场景 |
|---|---|---|
| 通用模式 | `CFQUANT_CTYPE_ALL_LOWLAT.py` | 默认选择，适合大多数用户、单账号和常规 QMT 环境 |
| 极致模式 | `CFQUANT_LITE.py` | 适合国泰君安、国泰海通的君弘君智，以及其他存在 Python 包白名单或导入限制的 QMT |
| 高级模式 | 普通 QMT 加载 `CFQUANT.py`，极速交易端加载 `CFQUANT_TRADE_LOWLAT.py` | 需要进一步降低下单、撤单延迟，并且能够准备两个 QMT 时使用 |

选择建议：

- 不确定时优先使用**通用模式**。
- 如果 QMT 无法导入 `cfquant`，或受到 Python 包白名单限制，选择**极致模式**。
- **高级模式**需要两个不同的 QMT，不能在同一个 QMT 中同时加载普通入口和极速交易入口。

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

Web 控制台启动后，请在初始化配置中确认或修改 Python 解释器路径。后续启动会优先使用已保存的路径；启动选择结果和失败原因记录在 `log\cfquant_startup.log`。

自动安装失败时，启动窗口会保持打开，并把安装日志写入 `log\cfquant_startup.log`，修复 Python、网络或权限问题后重新启动即可。

项目默认使用清华 PyPI 镜像安装依赖，适合中国大陆网络环境。启动脚本、网页源码更新、`requirements.txt` 安装以及 LTtx 缺失依赖自动安装都会遵循这个设置。需要切换到企业私有源或其他镜像时，可在启动前设置 `CFQUANT_PIP_INDEX_URL` 环境变量。

#### 方式二：PyPI 安装（适合外部 Python 或不需要源码更新的环境）

PyPI 安装只负责安装 `cfquant` Python 包及其依赖，不会自动把 QMT 入口策略导入 QMT，也不会创建源码包中的 `start_cfquant.bat`。建议在目标 Python 环境中使用 `python -m pip`，避免把包装到另一个解释器：

```powershell
python -m pip install --upgrade cfquant
# 需要 ZMQ 能力时：
python -m pip install --upgrade "cfquant[zmq]"
```

安装完成后，可以直接启动 Web 控制台：

```powershell
cfquant run
```

也可以使用 `cfquant serve` 或 `cfquant-web`；三者启动的是同一个本地 Web 服务。首次启动后访问 <http://127.0.0.1:8765/>，在初始化向导中配置 QMT 目录、账号和运行模式。需要 QMT 入口脚本时，使用已安装包导出到 QMT 策略目录：

```powershell
cfquant qmt-scripts --output D:\QMT\cfquant
```

#### 方式三：Conda / Anaconda 环境

Conda 环境可以直接安装 PyPI 包。请先激活实际运行策略的环境，再执行安装和启动命令：

```powershell
conda activate quant
python -m pip install --upgrade cfquant
cfquant run
```

如果使用源码包，直接运行项目目录中的 `start_cfquant.bat`。即使 Conda 没有加入系统 PATH，启动脚本也会探测常见 Conda 目录；无法探测时可设置 `CFQUANT_PYTHON_EXE` 指向该环境的 `python.exe`。Web 初始化后请保存同一个解释器路径，避免 Web、外部策略和 QMT 使用不同环境。

#### 选择建议

- 需要 Web 控制台、QMT 入口脚本、网页更新和回滚：使用**源码包部署**。
- 只需要在已有 Python 项目中调用 `cfquant.xtdata` 或 `cfquant.xttrader`：使用 **PyPI 安装**。
- 使用 Anaconda/Miniconda：优先在目标 Conda 环境中执行 `python -m pip install`，不要使用未激活环境的裸 `pip`。
- 源码包和 PyPI 包不要在同一个解释器中反复混用；源码开发时使用 `python -m pip install --editable .`，正式使用时使用 PyPI 版本。

启动后打开 <http://127.0.0.1:8765/>，按网页中的“新手初始化向导”完成账号、模式和 QMT 目录配置。开启“自动导入并管理 QMT 策略”可配置账号、模拟/实盘及 QMT 启动自运行；按绑定页进度完成 QMT 导入和重启，再验证资金、持仓、委托和行情。流程及模式互斥规则见 [Web 账号运行配置说明](docs/Web账号运行配置说明.md)。

重点：

- 源码部署后，网页里的“版本/更新”功能会按完整项目目录更新，适合从官网或 GitHub 拉取新版本。
- 更新时会尽量保留本地配置、数据库、日志和运行目录，便于日常升级和回滚。
- 如果新版本修改了 `qmt_scripts/` 里的入口脚本，网页会提示你重新更新 QMT 侧脚本并重启对应 QMT 策略。
- 建议把源码目录固定下来，例如 `D:\cfquant`，不要频繁挪动目录。

新用户建议先使用**通用模式**。所有部署配置都在 Web 控制台完成，保存绑定后系统会自动准备并管理 QMT 托管策略。

### Web 控制台绑定与初始化流程

1. 在初始化向导或“绑定”页面填写资金账号、账户类型、模式和 QMT 目录，勾选“自动导入并管理 QMT 策略”，确认模拟／实盘与策略自动运行设置。
2. 保存后系统自动部署核心包、身份配置和托管策略，弹窗显示部署结果及启动提醒，无需复制代码或手工新建策略。
3. 按提示重启并登录 QMT。如果勾选了“自动启动 QMT”，在启动后的 QMT 中登录即可；QMT 自身已设置自动登录时，等待自动登录完成。**国金证券 QMT 目前不支持自动登录，每次启动后需手动输入密码登录。**
4. 若提示等待退出，正常退出 QMT，保持 cfquant 运行，等待模型配置完成后再启动。若部署失败，修正目录、权限或模型账号 Key 后重新保存。
5. “知道了”直接关闭提醒；“检测连接”可进入通道检测，随后查询资金或持仓确认账号数据。

“自动启动 QMT”负责启动客户端；“QMT 启动后自动运行”负责运行托管策略。未勾选策略自动运行时，登录后需在“模型交易”运行已导入的托管策略。编辑已有绑定会保留这些选项，不会自动开启。

cfquant Web 每次启动时都会读取已保存的绑定：只要账号处于启用状态并勾选了“自动启动 QMT”，就会检查对应 QMT 是否已经运行；未运行时自动拉起对应的 `XtItClient.exe`，已经运行的实例不会重复启动。首次登录、密码输入和 QMT 内的策略运行仍按页面提示完成。

| 模式 | 自动部署目标 | 在线检测要求 |
|---|---|---|
| 通用模式 | 单个 QMT 中的通用托管策略 | 查询通道和交易通道都在线 |
| 极致模式 | 单个 QMT 中的自包含托管策略 | 查询通道和交易通道都在线 |
| 高级模式 | 普通端与极速交易端两个不同的 QMT | 两端都在线 |
| 同账号独立市场 | 对应上海和深圳市场的 QMT | 沪市和深市交易通道都在线 |

多 QMT 部署需分别完成各终端登录，自动启动选项仅启动绑定的主 QMT 目录。同一资金账号在同一个 QMT 中只允许一种模式。完整配置及状态说明见 [Web 账号运行配置说明](docs/Web账号运行配置说明.md)。

## 常见问题先查哪里

| 现象 | 优先检查 |
|---|---|
| 双击启动窗口后立即退出 | 查看 `log\cfquant_startup.log`；确认 Python 路径存在，或设置 `CFQUANT_PYTHON_EXE`。 |
| 页面打不开 | 查看最新的 `log\cfquant_web_server.*.stderr.log`；确认 8765 端口没有被其他程序占用。 |
| 页面在线但 QMT 不在线 | 确认 QMT 已登录、QMT 目录正确，并按绑定页提示重新导入或启动入口策略。 |
| `ModuleNotFoundError: cfquant` | 在运行策略的同一个解释器中执行 `python -m pip install --upgrade cfquant`，再用 `python -c "import cfquant; print(cfquant.__file__)"` 验证。 |
| 行情为空 | 先用页面接口测试确认证券代码、周期和行情权限；标准行情异常时可对照 `xtdata.get_market_data_ex`。 |
| 不确定应该使用哪种模式 | 先选通用模式；极致模式用于 QMT 导入受限的情况，高级模式需要额外准备两个 QMT 环境。 |

完整日志位于项目的 `log` 目录。提交问题时，请附上启动日志、页面状态和使用的 Python 版本，删除账号、密码、Token、订单和持仓等敏感信息后再提交。

## 从 `xtquant` 迁移到 `cfquant`

安装和初始化完成后，通常不需要重写原有策略。先把外部策略中指向 `xtquant` 的导入改成 `cfquant` 对应模块，再按下面的顺序验证。cfquant 负责外部 Python 与 QMT 之间的桥接，QMT 仍然需要登录并运行 Web 绑定页部署的入口策略。

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

默认路由是 `auto`，外部策略通常不需要手工选择 Pipe、LTtx 或高级模式。需要固定传输方式时，再使用 `cfquant.configure(...)`；具体路由说明见 [外部 Python 接入](docs/外部Python接入.md)。

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

批量接口用于组合调仓、批量止盈止损和撤掉一组未成委托。它的原理是外部 Python 只发一次批量 RPC，Web/LTtx/ctypes 将整批请求路由到 QMT 后，由 QMT 本地连续调用 `passorder` 或 `cancel`，减少逐笔跨进程往返。`cftrader` 目前提供 `order_stock_batch`、`order_stock_batch_async`、`cancel_order_stock_batch` 和 `cancel_order_stock_batch_async`；批量返回只表示请求提交情况，最终成交或撤成仍以委托查询和回调为准。

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
| 通用模式部署 | [通用模式部署指南](docs/通用模式部署指南.md) |
| 极致模式部署 | [极致模式部署指南](docs/极致模式部署指南.md) |
| 高级模式部署 | [高级模式部署指南](docs/高级模式部署指南.md) |
| 账号和 QMT 目录配置 | [Web 账号运行配置说明](docs/Web账号运行配置说明.md) |
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
