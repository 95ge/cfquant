# CFQuant 文档目录

`docs/` 只保存已经整理、可以面向用户或公开开发者发布的文档。产品方案、架构草案、实现计划、性能诊断、安全授权设计和未发布功能统一放在本地内部文档目录，不随公开源码发布。

## 入门与 API

- [项目指南](PROJECT_GUIDE.md)：CFQuant 组成、首次部署和基本配置。
- [API 参考](API_REFERENCE.md)：Python 兼容 API 和 Web API。
- [AI 接入总览](AI_AGENT_INTEGRATION.md)：区分 MCP 工具调用和策略代码迁移。
- [AI MCP 交易指南](AI_MCP_TRADING.md)：MCP 适配示例、客户端配置、查询与交易确认。
- [AI 策略迁移指南](AI_STRATEGY_MIGRATION.md)：改造前后代码、只读验证、回调和 AI 任务示例。
- [外部 Python 接入](外部Python接入.md)：在用户项目中使用 CFQuant。
- [第三方项目管理 SDK](第三方项目管理SDK.md)：项目生命周期和管理接口。

## 部署与运维

- [QMT 部署教程（当前版）](QMT部署教程-整理版.md)
- [QMT Python 运行时管理接口](qmt_python_runtime.md)
- [QMT 虚拟机与 MAC 设置](qmt_launch_settings.md)
- [运维与更新](运维与更新.md)
- [官网远程管理使用说明](官网远程管理使用说明.md)
- [Web 账号运行配置说明](Web账号运行配置说明.md)
- [QMT 策略自动恢复](QMT策略自动恢复.md)
- [QMT 交易日自动重启与登录](QMT交易日自动重启与登录.md)

## 兼容性与数据能力

- [miniQMT 迁移到大 QMT 指南](miniQMT迁移到大QMT指南.md)
- [xtquant 原版接口适配清单](xtquant原版接口适配清单.md)
- [xtdata 平替追踪](xtdata平替追踪.md)
- [xttrader 平替追踪](xttrader平替追踪.md)
- [QMT 函数封装能力清单](QMT函数封装能力清单.md)
- [Level2 行情适配说明](Level2行情适配说明.md)
- [算法交易与共享全推行情](algorithm_trading.md)
- [交易监控](trading_monitor.md)

## 交易功能

- [批量交易与撤单](cftrader批量交易.md)
- [条件单、仓位计算与下单计划](conditional_orders.md)
- [自定义消息推送](notifications.md)
- [沪港通与深港通](沪港通与深港通.md)

## 版本与历史说明

- [版本日志](版本日志.md)
- [高级模式部署指南](高级模式部署指南.md)
- [通用模式部署指南（已废弃）](通用模式部署指南.md)
- [文档维护规范](文档维护规范.md)

内部文档需要转为公开内容时，先删除账号、路径、密钥、内部服务和未发布实现细节，再将经过评审的用户说明放入本目录。内部文档的归档和公开化流程由项目维护规范统一定义。
