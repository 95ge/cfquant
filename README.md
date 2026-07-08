# cfquant

cfquant 是面向 QMT 的本地桥接项目，用于把 Web 控制台、外部 Python 程序和 QMT 策略脚本连接起来，统一转发行情订阅、交易请求、账户查询和回调事件。

## 快速开始

1. 从 GitHub 下载源码 zip，解压到一个固定目录，例如：

   ```text
   D:\cfquant
   ```

2. Windows 下双击运行：

   ```text
   start_cfquant.bat
   ```

   脚本会启动本地 `LTtx_server.py` 和 Web 控制台，并打开：

   ```text
   http://127.0.0.1:8765/
   ```

3. 如果不使用一键脚本，也可以手动分步启动：

   ```powershell
   cd D:\cfquant
   python .\LTtx\tx\LTtx_server.py
   ```

   另开一个终端：

   ```powershell
   cd D:\cfquant
   python .\cfquant_web_server.py --host 127.0.0.1 --port 8765
   ```

4. 打开 Web 控制台后，进入“绑定”页面维护桥接端和账号绑定。

5. 接入 QMT 时，把下面这些文件复制到 QMT 的 Python 策略目录：

   ```text
   cfquant/
   LTtx/
   qmt_scripts/CFQUANT.py
   qmt_scripts/CFQUANT_TRADE_LOWLAT.py
   qmt_scripts/tx.py
   ```

   复制后，`CFQUANT.py`、`CFQUANT_TRADE_LOWLAT.py`、`tx.py` 应和 `cfquant/`、`LTtx/` 位于同一个 QMT Python 目录中。

6. 在 QMT 中加载 `CFQUANT.py` 和 `CFQUANT_TRADE_LOWLAT.py`，然后回到 Web 控制台检查桥接端状态并完成账号绑定。

## 外部 Python 使用

外部 Python 程序可以把 cfquant 当作 `xtquant` 兼容层使用。使用前需要先保证本地 `start_cfquant.bat` 已启动，QMT 侧桥接脚本已加载，并且 Web 控制台里已经完成账号和桥接端绑定。

### 安装方式

如果 cfquant 已发布到 PyPI 或你的内部 pip 源，可以直接安装：

```powershell
pip install cfquant
```

当前源码仓库也支持从 GitHub 或本地目录安装：

```powershell
pip install git+https://github.com/95ge/cfquant.git
```

开发调试时推荐使用 editable 安装：

```powershell
cd D:\cfquant
pip install -e .
```

如果不想使用 pip，也可以把源码里的 `cfquant/` 和 `LTtx/` 两个目录直接复制到你的 Python 项目根目录，或复制到当前 Python 环境的 `site-packages` 目录。复制后应能在目标 Python 中执行：

```python
import cfquant
from cfquant import xtdata
```

### 替代 xtquant 导入

原来使用原生 `xtquant` 的代码：

```python
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
```

可以改成：

```python
from cfquant import xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount
```

如果原项目里大量使用 `import xtquant`，也可以用别名方式减少改动：

```python
import cfquant as xtquant

data = xtquant.xtdata.get_full_tick(["000001.SZ"])
```

### 连接配置

默认连接本机 LTtx：

```python
from cfquant import configure

configure(
    host="127.0.0.1",
    port=2049,
    token="LTtx",
    bridge_id="default",
    timeout=15,
)
```

也可以通过环境变量配置：

```text
CFQUANT_LTTX_HOST=127.0.0.1
CFQUANT_LTTX_PORT=2049
CFQUANT_LTTX_TOKEN=LTtx
CFQUANT_BRIDGE_ID=default
CFQUANT_TIMEOUT=15
```

### 行情查询示例

```python
from cfquant import configure, xtdata

configure(bridge_id="default")

tick = xtdata.get_full_tick(["000001.SZ", "600000.SH"])
print(tick)

bars = xtdata.get_market_data(
    field_list=["open", "high", "low", "close", "volume"],
    stock_list=["000001.SZ"],
    period="1d",
    count=5,
)
print(bars)
```

### 交易查询示例

```python
from cfquant import configure
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

configure(bridge_id="default")

account = StockAccount("2220009880")
trader = XtQuantTrader("", 0, account=account)
trader.start()

asset = trader.query_stock_asset(account)
positions = trader.query_stock_positions(account)

print(asset)
print(positions)
```

## 目录结构

```text
cfquant/
  cfquant/          核心 Python 包，提供 xtdata、xttrader、xttype 等兼容入口
  LTtx/             本地通信依赖，外部 Python 客户端也需要它导入 txl
  qmt_scripts/      需要放入 QMT Python 策略目录的入口脚本
  web_dashboard/    Web 控制台静态资源
  cfquant_web_server.py
                    Web 控制台后端入口
  start_cfquant.bat Windows 一键启动脚本
  docs/             部署与兼容说明
```

## QMT 部署

本地服务先运行在用户电脑上，负责启动 LTtx 和 Web 控制台；QMT 侧只需要加载桥接脚本。

QMT Python 策略目录最终应包含：

```text
CFQUANT.py
CFQUANT_TRADE_LOWLAT.py
tx.py
cfquant/
LTtx/
```

其中 `CFQUANT.py` 是普通桥入口，`CFQUANT_TRADE_LOWLAT.py` 是极速交易桥入口，`tx.py` 和 `LTtx/` 负责本地通信。

## 多桥接端

多 QMT 场景下，每个 QMT 终端应配置不同的 `bridge_id`，并在 Web 控制台“绑定”页面维护账号到桥接端的关系。

## 更新机制

Web 端支持为桥接端配置 Python 目录，并通过 GitHub 或 zip 源码更新核心代码。常规更新只替换目标目录中的：

```text
cfquant/
LTtx/
```

不会覆盖 `CFQUANT.py`、`CFQUANT_TRADE_LOWLAT.py` 等入口脚本。更新前会备份旧版本，默认只保留最近 2 个备份，便于失败后回滚。

## 说明

详细教程以 Web 控制台的“教程”页面为准；`docs/` 目录保留部分兼容说明和补充文档。
