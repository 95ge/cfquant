# cfquant

cfquant 是面向 QMT 的本地桥接项目，用于把 Web 控制台、外部 Python 程序和 QMT 策略脚本连接起来，统一转发行情订阅、交易请求、账户查询和回调事件。

## 目录结构

```text
cfquant/
  cfquant/          核心 Python 包
  qmt_scripts/      需要放入 QMT Python 策略目录的入口脚本
  LTtx/             本地通信依赖
  web_dashboard/    Web 控制台静态资源
  docs/             部署与兼容说明
```

## 基本部署

1. 将 `cfquant/`、`LTtx/`、`qmt_scripts/CFQUANT.py`、`qmt_scripts/CFQUANT_TRADE_LOWLAT.py`、`qmt_scripts/tx.py` 放到 QMT 的 Python 策略目录。
2. 在 QMT 中加载 `CFQUANT.py` 和 `CFQUANT_TRADE_LOWLAT.py`。
3. 启动本地 Web 服务后，在 Web 控制台完成桥接端和账号绑定。

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
