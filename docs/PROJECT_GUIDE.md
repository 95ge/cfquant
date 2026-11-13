# CFQuant 项目指南

CFQuant 是把大 QMT 桥接成 MiniQMT/`xtquant` 使用方式的兼容层。它把大 QMT 的行情、数据查询、交易、回调和账户能力转换给原有 MiniQMT 风格的外部 Python 策略、Web 控制台和自动化 agent。用户只需下载并安装 QMT，无需预先登录；CFQuant 前端完成绑定后会自动启动 QMT、安装运行环境并部署桥接策略。

## 核心迁移目标

MiniQMT 策略的主要业务逻辑可以继续保留。CFQuant 兼容 `xtdata`、`XtQuantTrader`、`StockAccount`、`xtconstant` 和常用回调的接口形状，通常只需将外部导入从 `xtquant` 切换为 `cfquant`，再配置大 QMT 账户和桥接入口。接口不完整或返回结构有差异的项目，以[xtquant 适配清单](xtquant原版接口适配清单.md)为准。

## 运行组成

- **Web 控制台**：默认监听 `127.0.0.1:8765`，用于初始化、账户绑定、状态检查、脚本管理和诊断。
- **QMT 入口脚本**：位于 `qmt_scripts/`，由 QMT 内部 Python 解释器运行。
- **MiniQMT 兼容 SDK**：`cfquant.xtdata`、`cfquant.xttrader`、`cfquant.xttype`、`cfquant.xtconstant` 等模块，供原有策略或 agent 调用。
- **大 QMT 原生扩展**：`cfquant.QmtInnerApi` 用于需要直接访问大 QMT 内置接口的高级场景；它不是 MiniQMT 兼容层的必需入口。
- **PipeHub/传输层**：在 Web、外部 Python 和 QMT 之间转发请求、回调和行情事件。

## 首次部署

1. 在 Windows 下载并安装 QMT，无需预先登录。
2. 安装 Python 3.8--3.12；已有 MiniQMT 策略项目可在目标环境执行 `python -m pip install --upgrade cfquant`。
3. 源码部署运行 `start_cfquant.bat`，或在已安装包的环境中执行 `cfquant run`。
4. 打开 `http://127.0.0.1:8765/`，完成大 QMT 目录、账户和账户类型绑定；当前固定使用极致模式。
5. 保存绑定后，前端自动启动 QMT、安装所需 Python 运行环境并部署自包含桥接入口。
6. 在“接口测试”中验证行情、资金、持仓和委托，然后接入策略。

## 配置原则

- 外部 Python、Web 服务和 QMT 桥接策略必须明确各自解释器，并配置正确的 `qmt_dir`；外部策略只需确保 `cfquant` 安装在它实际运行的解释器中。
- 多账户通过 `bridge_id`、`account_type`、`account_id` 路由；不要把账户密码写入策略代码、日志或 agent prompt。
- 远程访问默认关闭。开启前配置 Web Auth 或 API Key，并限制允许域名；生产环境优先使用 loopback 或受控内网。
- 任何会下单、撤单、启动 QMT 或更新项目的自动化操作，都必须先读取状态并得到用户明确指令。

## 常用命令

```powershell
python -m pip install --upgrade cfquant
cfquant run
cfquant qmt-scripts --output D:\QMT\cfquant
```

更多接口见 [API_REFERENCE.md](API_REFERENCE.md)，agent 接入见 [AI_AGENT_INTEGRATION.md](AI_AGENT_INTEGRATION.md)。

