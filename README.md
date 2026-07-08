# cfquant

cfquant 是面向 QMT 的本地桥接项目，用于把 Web 控制台、外部 Python 程序和 QMT 策略脚本连接起来，统一转发行情订阅、交易请求、账户查询和回调事件。

## 快速开始

1. 从 GitHub 下载源码 zip，解压到一个固定目录，例如：

   ```text
   D:\cfquant
   ```

2. Windows 下可以直接双击运行：

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

4. 打开 Web 控制台后，进入“绑定”页面维护桥接端和账号绑定；进入“更新”页面时，可以为每个桥接端设置对应的 QMT Python 策略目录。

5. 接入 QMT 时，把下面这些文件复制到 QMT 的 Python 策略目录：

   ```text
   cfquant/
   LTtx/
   qmt_scripts/CFQUANT.py
   qmt_scripts/CFQUANT_TRADE_LOWLAT.py
   qmt_scripts/tx.py
   ```

   复制后，`CFQUANT.py`、`CFQUANT_TRADE_LOWLAT.py`、`tx.py` 应和 `cfquant/`、`LTtx/` 位于同一个 QMT Python 目录下。

6. 在 QMT 中加载 `CFQUANT.py` 和 `CFQUANT_TRADE_LOWLAT.py`，然后回到 Web 控制台检查桥接端状态并完成账号绑定。

## 目录结构

```text
cfquant/
  cfquant/          核心 Python 包
  qmt_scripts/      需要放入 QMT Python 策略目录的入口脚本
  LTtx/             本地通信依赖
  web_dashboard/    Web 控制台静态资源
  cfquant_web_server.py
                    Web 控制台后端入口
  start_cfquant.bat Windows 一键启动脚本
  docs/             部署与兼容说明
```

## 基本部署

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
cfquant/cfquant/
```

不会覆盖 `CFQUANT.py`、`CFQUANT_TRADE_LOWLAT.py` 等入口脚本。更新前会备份旧版本，默认只保留最近 2 个备份，便于失败后回滚。

## 说明

部署和接口细节见 `docs/` 目录。
