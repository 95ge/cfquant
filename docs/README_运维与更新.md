# 运维与更新

本文说明 cfquant 的本地服务启停、日志清理、版本检查和更新策略。

## 启停脚本

项目根目录提供以下脚本：

```text
start_cfquant.bat      启动本地服务
stop_cfquant.bat       停止本地服务
restart_cfquant.bat    重启本地服务
启动cfquant.bat        中文启动脚本
停止cfquant.bat        中文停止脚本
重启cfquant.bat        中文重启脚本
```

通常日常运维只需要使用 `restart_cfquant.bat` 或 `重启cfquant.bat`。

## 日志目录

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

`CFQUANT_PIPE_HUB_VERBOSE_EVENTS=1` 会打开 PipeHub 高频事件日志，只建议排查问题时临时使用。

## 版本检查

Web 左上角会显示当前版本号。鼠标悬停后可以查看：

- 当前本地版本；
- 本地更新日志；
- 远端是否存在新版本；
- 新版本更新日志；
- 版本检查失败原因。

内网或无法访问 GitHub 时，版本探测失败只会在页面顶部提示，不影响交易、行情、账号路由和本地功能。

## 更新策略

Web“设置 - 更新管理”中分为两类更新。

Web 项目更新：

- 可从 GitHub 拉取项目 zip；
- 也可以上传本地 zip；
- 更新前会生成备份；
- 失败时按更新前备份恢复；
- 更新后会自动重启 Web 服务。

QMT 核心更新：

- 面向每个已绑定 QMT 的 `bin.x64/cfquant/`；
- 用于更新 QMT 侧可导入的 `cfquant` 核心包；
- 不直接替换 QMT 里的加密入口脚本。

更新后的提醒：

- 只要更新了 QMT 核心包，用户需要停止并重新启动对应 QMT 入口脚本。
- 如果本次更新涉及 `qmt_scripts/CFQUANT*.py`，需要用户手动更新 QMT 里的入口文件后再启动。
- QMT 入口启动文件如果已经加密，项目无法自动替换，只能由用户自己更新。

## 回滚

Web 项目更新会保留更新前备份。发生问题时可以在 Web“设置 - 更新管理”中选择备份回滚。

回滚后同样需要注意：

- Web 项目会自动重启；
- 如果回滚涉及 QMT 核心包，需要重启 QMT 侧入口脚本；
- 如果回滚涉及 `qmt_scripts/CFQUANT*.py`，需要用户手动同步入口文件。
