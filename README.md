# cfquant

<p>
  <a href="https://github.com/95ge/cfquant/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/95ge/cfquant?style=flat&logo=github&label=Stars" height="18" /></a>
  <a href="https://github.com/95ge/cfquant/network/members"><img alt="GitHub forks" src="https://img.shields.io/github/forks/95ge/cfquant?style=flat&logo=github&label=Forks" /></a>
  <a href="https://github.com/95ge/cfquant/issues"><img alt="GitHub issues" src="https://img.shields.io/github/issues/95ge/cfquant?style=flat&logo=github&label=Issues" /></a>
  <a href="https://github.com/95ge/cfquant/commits/main"><img alt="GitHub last commit" src="https://img.shields.io/github/last-commit/95ge/cfquant?style=flat&logo=git&label=Last%20commit" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat" /></a>
  <a href="https://pypi.org/project/cfquant/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/cfquant?style=flat&logo=pypi&logoColor=white" /></a>
  <img alt="Python 3.8 to 3.12" src="https://img.shields.io/badge/Python-3.8--3.12-blue?style=flat&logo=python&logoColor=white" />
</p>

#### 1、cfquant 是将大QMT转为类miniqmt来使用。它让外部 Python 程序和 Web 控制台可以使用大 QMT 的行情、查询、交易和回调能力，并尽量保持接近 `xtquant` 的调用方式。

#### 2、支持交易委托，交易回调，全推行情推送，行情查询，数据下载等功能。

#### 3、高兼容miniqmt，几乎不用改您原来的miniqmt策略，还是一样的使用。

#### 3、总之，您可以在部署项目后在您的程序中无感使用miniqmt。

#### 4、部署稍微比较复杂，请您耐心~~~，欢迎提功能与需求，让miniqmt再一次伟大！

#### 5、官网与反馈：[www.cfquant.org](https://cfquant.org)

## 快速开始

### 环境要求

- Windows
- 已安装并登录大 QMT
- Python `3.8` - `3.12`，生产环境优先使用 `3.10` 或 `3.12`

### 安装方式

#### 方式一：源码包部署（推荐）

新用户和生产环境优先使用源码包部署。原因很简单：cfquant 的 Web 控制台、QMT 入口脚本和本地配置是一起工作的，源码包保留完整项目目录，后续在网页里检查更新、更新 Web、回滚版本、提示 QMT 入口脚本变更都更方便。

1. 将项目解压到固定目录，例如 `D:\cfquant`。
2. 在项目目录安装依赖：

   ```powershell
   cd D:\cfquant
   python -m pip install -r requirements.txt
   ```

3. 运行 `start_cfquant.bat`。

启动后打开 <http://127.0.0.1:8765/>，按网页中的“新手初始化向导”完成账号、模式和 QMT 目录配置。然后在 QMT 中加载对应的入口脚本，回到网页验证资金、持仓、委托和行情。

重点：

- 源码部署后，网页里的“版本/更新”功能会按完整项目目录更新，适合从官网或 GitHub 拉取新版本。
- 更新时会尽量保留本地配置、数据库、日志和运行目录，便于日常升级和回滚。
- 如果新版本修改了 `qmt_scripts/` 里的入口脚本，网页会提示你重新更新 QMT 侧脚本并重启对应 QMT 策略。
- 建议把源码目录固定下来，例如 `D:\cfquant`，不要频繁挪动目录。

新用户建议先使用**通用模式**。一个 QMT 加载一个入口脚本即可完成大多数部署。

#### 方式二：PyPI 安装（仅推荐库调用或临时体验）

PyPI 适合外部 Python 策略只安装 `cfquant` 库，或者临时体验命令行启动方式；不建议把它作为完整 Web 部署的主要方式。pip 安装后的项目文件位于当前 Python 环境的 `site-packages`，网页里的项目更新、源码回滚和入口脚本同步不如源码包部署直观。

```powershell
python -m pip install -U cfquant
```

After installation, you can start the local Web Console:

```powershell
cfquant --open-browser
```

如果使用 pip 安装，QMT 侧仍需要加载入口脚本。查看 pip 包内置的 QMT 入口脚本目录：

```powershell
cfquant qmt-scripts
```

在 Windows 资源管理器中打开脚本目录：

```powershell
cfquant qmt-scripts --open
```

把入口脚本复制到 QMT 可加载目录：

```powershell
cfquant qmt-scripts --output D:\QMT\cfquant
```

后续升级 pip 包需要回到命令行执行：

```powershell
python -m pip install -U cfquant
cfquant qmt-scripts --output D:\QMT\cfquant --force
```

升级后建议重启本地 `cfquant` 服务，并在 QMT 中重新加载入口脚本，确保 Web、本地 Python 库和 QMT 侧入口属于同一版本。

验证安装版本和脚本目录：

```powershell
cfquant version
```

## 模式选择

| 模式 | QMT 入口 | 适用场景 |
|---|---|---|
| 通用模式 | `CFQUANT_CTYPE_ALL_LOWLAT.py` | 默认选择，适合大多数用户和单账号部署 |
| 极致模式 | `CFQUANT_LITE.py` | QMT 有白名单限制、无法导入 `cfquant` 包时使用 |
| 高级模式 | 普通 QMT 加载 `CFQUANT.py`，极速交易端加载 `CFQUANT_TRADE_LOWLAT.py` | 需要进一步降低下单、撤单延迟时使用 |

高级模式需要同时打开两个 QMT，不能在同一个 QMT 中同时加载两个入口。

## Python 接入

从 PyPI 安装并在外部策略中调用：

```powershell
pip install cfquant
```

示例：

```python
from cfquant import xtdata

tick = xtdata.get_full_tick(["000001.SZ"])
print(tick)
```

`cfquant` 默认使用 `transport=auto`，通常不需要手动配置通信通道。完整导入方式、路由规则和特殊部署方式见[外部 Python 接入](docs/外部Python接入.md)。

## Web Console

The Web Console provides account binding, cash and positions, order fills, order placement and cancellation, market subscriptions, API debugging, deployment guides, and update management.

Common scripts:

```text
start_cfquant.bat       Start
stop_cfquant.bat        Stop
restart_cfquant.bat     Restart
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
| 日志、更新和回滚 | [运维与更新](docs/运维与更新.md) |
| 版本变化 | [版本日志](docs/版本日志.md) |

More detailed tutorials are also available on the Web Console "Tutorials" page.

## Star History

<a href="https://star-history.com/#95ge/cfquant&Date"><img src="https://api.star-history.com/svg?repos=95ge%2Fcfquant&type=Date" alt="Star History Chart" width="500" /></a>



## 项目交流群
<img src="ba67bb2fcfa8a067d2c8249656248449.jpg" alt="cfquant 项目交流群二维码" width="280" />


## 联系作者
- #### 地球号:shcfquant,请注明来意
- #### 邮箱:litaoflyme@163.com


## 许可证

本项目采用 [MIT License](LICENSE) 开源。
