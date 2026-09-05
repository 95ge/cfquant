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

### 1. 项目定位

`cfquant` 是面向大 QMT 的本地桥接层。它把大 QMT 已有的行情、查询、交易和回调能力整理出来，提供接近 `miniQMT` / `xtquant` 的外部调用方式。
- 部署前请务必读完本教程。
- 部署前请务必读完本教程。
- 部署前请务必读完本教程。

### 2. 主要能力

- 交易委托、撤单、委托查询和成交查询
- 交易回调和全推行情推送
- 行情查询、资金查询、持仓查询
- 数据下载、数据读取和接口调试
- Web 控制台、外部 Python 程序和 QMT 策略之间的本地通信

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
2. 直接双击项目目录中的 `start_cfquant.bat`。启动脚本会使用项目 `.venv`（如果存在）或当前 Python，自动安装 `requirements.txt` 中的项目依赖，并安装当前源码版本的 `cfquant`，不需要用户手动执行安装命令。

自动安装失败时，启动窗口会保持打开，并把安装日志写入 `log\cfquant_startup.log`，修复 Python、网络或权限问题后重新启动即可。

启动后打开 <http://127.0.0.1:8765/>，按网页中的“新手初始化向导”完成账号、模式和 QMT 目录配置。然后在 QMT 中加载对应的入口脚本，回到网页验证资金、持仓、委托和行情。

重点：

- 源码部署后，网页里的“版本/更新”功能会按完整项目目录更新，适合从官网或 GitHub 拉取新版本。
- 更新时会尽量保留本地配置、数据库、日志和运行目录，便于日常升级和回滚。
- 如果新版本修改了 `qmt_scripts/` 里的入口脚本，网页会提示你重新更新 QMT 侧脚本并重启对应 QMT 策略。
- 建议把源码目录固定下来，例如 `D:\cfquant`，不要频繁挪动目录。

新用户建议先使用**通用模式**。一个 QMT 加载一个入口脚本即可完成大多数部署。

### Web 控制台绑定与初始化流程

完成源码部署并启动 Web 控制台后，账号绑定和首次初始化都按下面的顺序进行：

1. 在“新手初始化向导”或“绑定”页面填写资金账号、账户类型、运行模式和 QMT 目录。QMT 目录可以填写 QMT 安装目录、`bin.x64`，也可以填写对应的 `python` 目录。
2. 点击保存后，系统会显示 QMT 核心包复制状态。通用模式和高级模式会自动复制 `cfquant` 到对应 QMT 的 `bin.x64\cfquant`；极致模式的入口脚本自包含，但仍建议填写 QMT 目录，以便写入身份配置和显示准确的策略路径。
3. 保存完成后，页面会显示与当前模式匹配的 QMT 策略代码。点击每份策略右侧的复制按钮，在 QMT 的模型研究中选择“新建策略”->“新建 Python 策略”，粘贴代码后保存。
4. 关闭代码指引后，页面会进入“重启 QMT 并运行策略”步骤。重启对应的 QMT，在策略列表中运行刚刚保存的策略，然后点击“我已重启并运行，开始检测”。
5. 系统会持续检测 QMT 通道是否在线。检测过程中不能跳过或直接关闭，可以使用“返回上一步”回到代码指引重新复制；只有“强制关闭本次绑定流程”会结束本次检测，但已经保存的账号绑定不会丢失。
6. 所有必需通道上线后，页面进入接口测试步骤，并可直接打开“查资金”接口，点击“发送请求”确认 QMT 返回当前账号数据。

初始化向导和普通绑定使用同一套复制状态、重启提示和在线检测流程。编辑已有账号时，编辑窗口只显示账号配置，不显示策略源码；修改并保存后，页面会重新打开对应的代码指引。

#### 不同模式需要加载的入口脚本

| 模式 | QMT 中需要新建并运行的策略 | 在线检测要求 |
|---|---|---|
| 通用模式 | `qmt_scripts/CFQUANT_CTYPE_ALL_LOWLAT.py` | 同一个 QMT 的查询通道和交易通道都在线 |
| 极致模式 | `qmt_scripts/CFQUANT_LITE.py` | 同一个 QMT 的查询通道和交易通道都在线 |
| 高级模式 | 普通 QMT：`qmt_scripts/CFQUANT.py`；极速交易端 QMT：`qmt_scripts/CFQUANT_TRADE_LOWLAT.py` | 普通端和极速交易端都在线 |

例如极致模式的策略文件通常位于：

```text
D:\中信证券QMT交易终端\python\CFQUANT_LITE.py
```

高级模式必须使用两个不同的 QMT 目录，不能在一个 QMT 中同时加载普通入口和极速交易入口。

#### 两地多中心 / 同账号独立市场

开启同账号独立市场路由后，不能继续使用普通入口文件。页面会根据模式显示上海、深圳两份策略：

- 通用模式：`CFQUANT_CTYPE_ALL_LOWLAT_SH.py`、`CFQUANT_CTYPE_ALL_LOWLAT_SZ.py`
- 极致模式：`CFQUANT_LITE_SH.py`、`CFQUANT_LITE_SZ.py`
- 高级模式：`CFQUANT_TRADE_LOWLAT_SH.py`、`CFQUANT_TRADE_LOWLAT_SZ.py`

上海 QMT 只运行 `_SH.py`，深圳 QMT 只运行 `_SZ.py`。该模式只有沪市和深市两个交易通道都在线后，绑定检测才会通过。完整文件说明见[同账号独立市场说明](qmt_scripts/同账号独立市场/readme.md)。

## Web 控制台

Web 控制台提供账号绑定、资金和持仓查询、委托和成交查询、下单和撤单、行情订阅、接口调试、部署指引以及版本更新管理。

常用脚本：

```text
start_cfquant.bat       启动
stop_cfquant.bat        停止
restart_cfquant.bat     重启
```

## 文档

| 需求 | 文档 |
|---|---|
| QMT 综合部署教程 | [QMT 部署教程](docs/QMT部署教程.md) |
| 通用模式部署 | [通用模式部署指南](docs/通用模式部署指南.md) |
| 极致模式部署 | [极致模式部署指南](docs/极致模式部署指南.md) |
| 高级模式部署 | [高级模式部署指南](docs/高级模式部署指南.md) |
| 账号和 QMT 目录配置 | [Web 账号运行配置说明](docs/Web账号运行配置说明.md) |
| 从 miniQMT 迁移 | [miniQMT 迁移到大 QMT 指南](docs/miniQMT迁移到大QMT指南.md) |
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
<img src="ba67bb2fcfa8a067d2c8249656248449.jpg" alt="cfquant 项目交流群二维码" width="280" />


## 联系作者
- #### 地球号:shcfquant,请注明来意
- #### 邮箱:litaoflyme@163.com


## 许可证

本项目采用 [MIT License](LICENSE) 开源。
