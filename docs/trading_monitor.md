# 交易监控

客户端左侧「监控」集中显示 QMT 通道在线情况、交易回报、异常记录、交易流速和请求延迟。支持按北京时间日期范围、部署、账号和账号类型筛选；单次查询最多 31 天，明细每页 50 条。

监控默认关闭。点击左侧「监控」时先读取开关状态；未开启则弹窗说明采集与延迟影响，点击「开启并进入」保存成功后才进入监控页，取消或开启失败留在原页面。已开启时直接进入。恢复上次停留的监控页面也遵循同样流程。

监控页右上角「监控设置」可开启/关闭采集、选择全部或指定的已绑定 QMT 账号，并设置运行时序保留天数（1–3650 天，默认 30 天）；默认全部，包含后续新增绑定。指定账号可多选，以部署、账号类型、账号号共同区分，同号不同部署/类型独立选择；包括所选账号的沪深等市场路由子部署。选择范围会实际过滤新增委托、成交、异常、请求记录及相关 QMT 通道采样。解绑后停止对应账号采集，不会自动回退到全部账号。开启指定范围时至少选择一个账号；暂无绑定时可选择全部，等待新增绑定。

设置保存后立即生效，保存在 `runtime/config/trading_monitor.json`，Web 服务重启后沿用；没有配置或配置无效时保持关闭。旧版本只有 `enabled` 的配置兼容为全部已绑定账号。开启后页面关闭也会持续采集，「自动刷新」只控制页面显示更新。开关和账号范围仅影响新增采集，不删除已有数据；已接收的队列记录继续保存，历史记录仍按日期、账号查询。在页面内关闭后可继续查看历史；离开后再次进入会提示开启。

关闭开关后不再接收新监控记录，后台继续保存已经入队的记录；已有历史数据仍可查询。首次使用且未开启时，不创建监控数据库或写入线程。默认数据库位于 `runtime/db/trading_monitor.sqlite3`，遵循 `CFQUANT_HOME` / `CFQUANT_RUNTIME_DIR` 的运行目录配置。首次安装本功能的代码后需重启 Web 服务加载新代码。

## 对交易延迟的影响

有少量额外开销。开启时，交易请求返回路径增加计时、字段提取、账号筛选和有界队列入队；回调线程增加账号筛选、事件复制和入队。绑定变更时提前生成账号匹配集合，交易采集路径不读取配置文件。SQLite 写入在后台线程执行，交易线程不等待数据库提交。关闭时直接跳过这些采集工作，仅保留开关判断。

2026-11-03 本机离线测试（Windows 10，Python 3.12.4，AMD64 Family 25 Model 117）：7 轮，每个测试项每轮 2,000 次，共 14,000 样本/项，包含账号范围匹配，后台使用实际 SQLite 数据库，模拟交易返回，不连接 QMT、不下真实委托。

| 测试项 | 中位数 | 均值 | P95 | P99 | 单次最大 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 未加监控包装的模拟请求 | 0.0002 ms | 0.00023 ms | 0.0005 ms | 0.0006 ms | 0.0170 ms |
| 监控关闭的模拟请求路径 | 0.0003 ms | 0.00029 ms | 0.0005 ms | 0.0005 ms | 0.0052 ms |
| 监控开启的模拟请求路径 | 0.0083 ms | 0.01045 ms | 0.0152 ms | 0.0311 ms | 0.1911 ms |
| 开启后的回调筛选与入队 | 0.0055 ms | 0.00674 ms | 0.0097 ms | 0.0182 ms | 0.5073 ms |

各轮请求中位数相减，开启相对关闭额外增加约 **0.0078–0.0112 ms/次**，页面取近似范围 **0.008–0.011 ms/次**。这些值只表示同步采集开销，不是实盘端到端交易耗时，也不是上限。后台写库、页面查询与交易共享 CPU、内存和磁盘，高并发或机器繁忙时可能出现更大尾延迟；停用监控可避免新增的持续采集负载。页面中的「交易请求延迟」记录 QMT 请求往返时间，不包含返回后的监控入队开销。

复测命令：`python tools/benchmark_trading_monitor.py --output runtime/reports/trading-monitor-overhead.json`。脚本使用独立临时运行目录和模拟交易接口，统计期间验证无队列丢失。不同机器应以自身测量结果为准。

## 统计口径

| 指标 | 定义 |
| --- | --- |
| 委托笔数 | 按业务日期、部署、账号、账号类型、证券和委托号去重后的委托回报数 |
| 成交笔数 | 按业务日期、部署、账号类型、账号、证券和成交编号去重后的成交回报数 |
| 成交率 | 有成交回报或累计成交量大于零（含部分成交）的委托数 / 委托数 |
| 撤成笔数 | 状态为部撤或已撤的委托数；已报待撤、部成待撤不计入 |
| 撤单率 | 撤成笔数 / 委托笔数 |
| 报撤比 | 委托笔数 / 撤成笔数 |
| 异常记录 | 废单委托数 + 委托/撤单错误回报数 + 失败交易 RPC 次数；同一业务可能产生多条记录 |
| 委托、成交流速 | 最近 60 秒首次收到的去重委托、成交笔数 / 60；历史日期显示 — |
| 流速曲线 | 按首次采集时间聚合；每个时间桶的笔数 / 桶宽。单日为 1 分钟，长范围自动增大桶宽 |
| 请求延迟 | 经过 Web 统一路由的报单、撤单请求往返耗时，包含失败请求；提供均值、P95（nearest rank）、最大值和样本数 |
| 通道在线状态 | 复用后台通道探测；超过 3 个探测周期（至少 30 秒）未更新时标记过期 |

分母为零或没有延迟样本时显示 `—`。请求次数与实际委托笔数分别统计，批量 RPC 计一次请求；请求成功不等同于交易所确认。通用模式基于 PipeHub 连接状态判断在线，其本地读取耗时不作为 QMT 延迟。

## 数据范围与运行方式

- 采集来源为本 Web 服务收到的 `trader:on_stock_order`、`trader:on_stock_trade`、`trader:on_order_error`、`trader:on_cancel_error`，以及经过 `GlobalTxClient.request` 的交易请求和 `ChannelStatusMonitor` 后台探测。
- 交易数据按回报业务日期归档；缺少业务日期时使用可识别的时间戳或北京时间接收日期。没有有效委托编号的回报保留在明细中，不计入去重委托总数。
- 有业务编号的重复回调在数据库内去重，重启后仍有效。缺少业务编号的事件无法保证可靠去重。重连补发可能增加当前采集流速，不会伪造历史接收时间。
- 成交回报早于委托回报时，后续委托仍能关联已保存的成交。状态回报乱序不会清除已有成交、撤成或废单标记。
- 异步写入使用有界队列、单写入线程、SQLite WAL 和批量事务。数据库锁定时后台重试；队列满或事件损坏时显式展示丢失数量，避免阻塞交易线程。
- 只保存统计所需字段，不保存完整请求参数或认证凭据。监控接口沿用现有 Web 登录/API Key 鉴权。
- 关闭监控或停机期间没有主动采集或历史补录；监控数据不等同于券商对账。交易历史查询单次最多 31 天，历史 QMT 状态是所选日期内最后一次采样；运行时序详情支持更长范围和全部历史。节点状态按部署筛选，不受查询表单中的交易账号筛选影响；设置中的账号范围决定哪些部署继续采样。移出范围的历史节点标记「未纳入采集」，不计入当前在线率或过期告警。
- 「运行诊断」页可点击 QMT 运行实例打开居中的时序弹窗，弹窗用指标卡片汇总 CPU、RSS 内存、回调速率、请求速率和行情分发速率，并将这 5 项指标同时分卡绘制；鼠标移动到任一曲线上可查看对应时间点的数值。页面支持当前查询、7/30/90 天、1 年和全部历史范围。时序全天写入（交易时段和休市时段均采集），同一分钟按 QMT 部署和运行模式覆盖更新；默认保留 30 天，超过设置的保留天数由后台自动清理，选择全部保留则不自动删除。弹窗可手动清理过期时序或清空全部时序。
- 本功能提供观测与历史留痕，不修改现有交易风控、下单、撤单或自动重试策略。

## 查询接口

运行时序弹窗的明细每页显示 100 条，默认定位到最新一页，可用“上一页 / 下一页”查看同次查询的其他记录；图表和指标汇总仍覆盖本次查询的全部样本。查询最多返回最新 10,000 条，达到上限时会提示缩小日期范围。翻页不重新读取数据库。

时序详情支持最近 5/30/60/120 分钟、6/24 小时，以及自定义最近 N 分钟；保留原有按天、当前查询和全部历史选项。分钟范围以服务端当前时间为截止点，每次刷新重新计算，支持跨日查询。N 须为正整数，最大 5,256,000 分钟（与日期查询上限一致）；单次仍最多返回最新 10,000 条样本。

弹窗默认开启独立的「自动刷新（5 秒）」开关，每次请求结束后等待 5 秒再次查询，不叠加未完成请求。刷新保留当前明细页和滚动位置，数据未变化时不重绘图表；失败保留上次结果并自动重试。后台采集按原设置继续运行，分钟采样粒度不变，同一分钟样本可被新采样覆盖。暂停自动刷新后仍可手动刷新。

打开详情期间暂停被弹窗覆盖的监控主页自动刷新，关闭后按主页开关恢复。浏览器标签页隐藏时暂停弹窗刷新，恢复可见后继续；关闭弹窗或离开监控页会停止定时器、取消未完成请求并释放图表和明细。图表悬停更新按浏览器帧合并。

`GET /api/monitor/runtime?minutes=60&bridge_id=qmt-one&mode=lite` 按服务端当前时刻查询最近 60 分钟，`minutes` 优先于 `start/end`；返回 `minutes`、`window_start/window_end` 时间戳和带北京时间时区的 `start/end`，包含窗口起止时刻。未指定 `minutes` 时仍沿用日期查询语义和鉴权。

`GET /api/monitor?start=2026-11-03&end=2026-11-03&bridge_id=...&account_id=...&account_type=STOCK&kind=abnormal&page=1`

`start`、`end` 默认今天；其余筛选项可省略。`kind` 支持 `order`、`trade`、`abnormal`、`order_request`、`cancel_request`。返回标准 `{ok, data}` 包装，`data` 包含 `stats`、`series`、`nodes`、`events`、分页信息与 `collector` 采集健康状态。

`GET /api/monitor/settings` 返回采集开关、运行状态、`account_keys`、`runtime_retention_days` 与 `accounts` 已绑定账号列表，不依赖数据库可读，不返回路径、密码或其他绑定私密配置。`POST /api/monitor/settings` 接收严格布尔值 `enabled`，可选 `account_keys` 和 `runtime_retention_days`；例如 `{"enabled":true,"account_keys":null,"runtime_retention_days":30}` 表示采集全部账号并保留 30 天，`{"enabled":true,"account_keys":["qmt-one:STOCK:paper"],"runtime_retention_days":7}` 表示指定账号并保留 7 天，`runtime_retention_days:0` 表示全部保留。省略可选字段保留原设置；未知账号、无效类型、无效保留天数或开启时空列表会被拒绝。`GET /api/monitor/runtime?start=2026-11-03&end=2026-11-03&bridge_id=qmt-one&mode=lite` 返回所选 QMT 运行实例的分钟样本，`start=all` 可查询全部历史（最多返回 10000 条样本）。`POST /api/monitor/runtime/cleanup` 接收 `{"scope":"expired"}` 清理已过期时序，或 `{"scope":"all"}` 清空全部时序并尝试压缩数据库。接口均沿用现有鉴权，`enabled`、`running`、`draining` 分别表示采集开启、线程运行、关闭后正在保存队列。

验证：`python -m pytest cfquant/tests/test_trading_monitor.py cfquant/tests/test_trading_monitor_browser.py -q`。浏览器测试使用现有 Playwright/Chromium 环境与独立临时 SQLite 数据库，不连接实际交易服务。


## Notification settings

用户程序主动发送自定义消息请参阅 [SDK 自定义消息推送](notifications.md)。账号绑定中的 Webhook 是 `cfquant.notify.send` 的默认接收地址，与本节监控事件的通知策略分别配置。

The monitor page has a separate notification settings dialog. It stores its policy in `runtime/config/monitor_notifications.json` and keeps SMTP passwords, webhook URLs, and secrets out of API responses. Delivery runs on a background queue, so callback and QMT status threads never wait on SMTP or HTTP.

`GET /api/monitor/notifications` returns the masked notification policy. `POST /api/monitor/notifications` accepts `enabled`, `event_types`, `email`, `webhooks`, `heartbeat`, and `schedule`. Webhook types are `generic`, `dingtalk`, `wecom`, and `feishu`. `POST /api/monitor/notifications/test` accepts an optional `{"channel_id":"email"}` or webhook id and sends a test message directly to the configured target.

Event types are `order`, `trade`, `order_error`, `cancel_error`, `qmt_reconnect`, `qmt_restart`, `qmt_unresponsive`, `system_error`, and `heartbeat`. The schedule modes are `always`, `trading_days`, `trading_hours`, and `custom`; custom schedules use weekday numbers (`0` for Monday) and `HH:MM` windows. Identical events are deduplicated for the configured `dedup_seconds` period.
