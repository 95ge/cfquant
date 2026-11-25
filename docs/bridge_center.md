# 独立桥接中心与 LTtx 频道接入

本文适用于已同步升级桥接中心、QMT 脚本和 Python SDK 的源码部署。旧发布包需先升级，不能只更新其中一个进程。

## 数据路径

```text
大 QMT 内部全推 → ctypes / 命名管道 → 独立桥接中心 A
                                            ↓ txl.push
                                   LTtx：all_gp_hq
                                    ├─ SDK 行情订阅
                                    ├─ 原生 tx.py 客户端
                                    └─ A 的展示订阅 → 浏览器
```

A 负责核心收发与后台业务。收发进程承载 PipeHub、QMT 路由和 LTtx 分发，独立业务工作进程负责算法/条件任务、账号配置、QMT 自动登录与恢复、监控通知、更新和清理。A 管理该工作进程的启动、退出和异常恢复。Web 只提供可选展示，页面操作调用 A 的 API；SDK 不经过 Web。当前源码支持此结构，0.2.83 发布包尚不包含这次职责迁移。

QMT 保留一份内部全推订阅。每个收到的原生批次交给 A，再由 A 使用 `txl.push('quote', payload, 'all_gp_hq')` 发布。增加 SDK 或浏览器消费者只增加 LTtx 订阅，不再发起新的全推订阅 RPC。没有消费者时也走同一发布入口。

默认内部范围为 SH、SZ、BJ。客户端的证券列表用于本地筛选，不会扩大源端范围；其他市场需要源端已提供相应行情。多个 QMT 在线时，公共频道只接受配置的数据提供者。可用 `CFQUANT_QUOTE_BRIDGE_ID` 在 A 上显式指定来源桥接 ID。

## SDK 使用

原有 API 保持不变：

```python
from cfquant import configure, xtdata

configure(host='127.0.0.1', port=2049, token='LTtx', transport='center')

def on_quote(quotes):
    # quotes 仍是 {证券代码: 行情字典}，不混入诊断元数据。
    process_quotes(quotes)

subscription_id = xtdata.subscribe_whole_quote(['SH', 'SZ'], callback=on_quote)
try:
    xtdata.run()
finally:
    xtdata.unsubscribe_quote(subscription_id)
```

示例中的 `process_quotes` 替换为业务处理函数。当前源码中，`transport='auto'` 与 `'center'` 均固定使用 A 的 `cfquant.center.request`。旧的 `web` / `web_lttx` 等配置也兼容映射到 A。A 不可用时请求报错或超时，不会改道 Web 或直连 PipeHub；启动顺序和登记过期不会改变已有 SDK 客户端的入口。0.2.82/0.2.83 发布包仍保留旧回退逻辑，使用这些版本时请在创建客户端前显式配置 `transport='center'`。

全推订阅本身始终直接连接 LTtx 的 `all_gp_hq`，不经过 RPC 客户端的通用回调分发器。每个订阅拥有独立连接、LTtx 接收内存队列和处理线程。多个订阅并行，同一个订阅按接收顺序串行执行回调，避免批次乱序。取消一个订阅只关闭它自己的接收端；`configure()`、`close_client()` 和程序退出也会释放本进程的行情订阅。

## 直接使用 tx.py

复制独立 `tx.py` 的程序可用 `from tx import txl`；安装 SDK 的程序可用下面的导入：

```python
import json
from cfquant.tx import txl

tx = txl('127.0.0.1', 2049, 'LTtx', show=False)
try:
    tx.start_txg('all_gp_hq')
    while True:
        key, raw = tx.Q.get().split('|', 1)
        if key != 'quote' or not raw.startswith('cfquant:'):
            continue
        event = json.loads(raw[len('cfquant:'):])
        batch = event['data']
        quotes = batch['quotes']
        print(batch['sequence'], len(quotes))
finally:
    tx.close()
```

外层是 CFQuant 事件协议，事件名为 `all_gp_hq`。批次使用 `schema='cfquant.quote_latency.v1'`，包含 `quotes`、`bridge_id`、`generation`、`sequence`、`qmt_callback_at_ms` 和 `qmt_push_at_ms`。`sequence` 在同一次桥接运行内递增；程序重启后结合 `generation` 区分。普通 QMT 行情直接编码为 JSON；如果业务使用协议扩展值，应使用 `cfquant.protocol.decode_value` 或标准 SDK 解码。

`push` 返回成功表示提交到 LTtx 发送队列，不能当作所有订阅者处理成功的确认。

## 请求与交易事件

- SDK 请求通过 `cfquant.center.request` 进入 A，由 A 根据资金账号、账号类型、桥接 ID 和市场配置路由到 QMT；响应进入请求方的专属频道。
- `XtQuantTrader.subscribe(account)` 自动订阅对应账号事件频道，并通过 A 维护共享的原生账号注册。同账号多个 SDK 使用同一上游注册身份；一个 SDK 取消订阅不会退掉其他消费者的注册。
- 账号事件频道为 `cfquant.account.<身份摘要>`，身份由桥接 ID、资金账号和账号类型组成。委托、成交、错误、账户状态在同一有序流中以 `event` 区分，SDK 保持原有回调 API。
- Web 的默认交易事件监听也通过 LTtx；A 同时转发桥接实例的 callback 频道，供管理界面接收账户状态和运行事件。
- 多市场批量请求由 A 按已配置的市场桥接拆分。结果不确定的下单或撤单不会自动重发。

账号事件频道名用于路由，不代替 LTtx 接入权限。断线期间没有持久事件重放，恢复后应通过查询核对委托与成交。算法交易、条件单管理和通知同样通过 SDK 的 A 入口，由 A 调用独立业务工作进程。内部业务频道有额外认证，直接订阅频道不授予管理权限。

## 独立启动与展示开关

```powershell
# A + 可选网页展示；旧的 cfquant serve/start_cfquant.bat 入口保持兼容。
cfquant center

# 不提供页面，核心服务、LTtx 接入和管理 API 继续运行。
cfquant center --no-web
```

`cfquant_web_server.py` 保留为兼容启动入口，实际启动 A。业务实现位于 `cfquant/runtime_services.py`，生命周期由 A 管理；`cfquant/web_view.py` 负责静态页面响应。无页面模式不要求安装或加载页面资源。管理 API 保留原有认证、账号权限和端口配置。

页面监听配置重载只替换 HTTP 监听器，不停止算法任务、QMT 守护或清理任务。管理接口的服务重启和项目更新后的重启都会重新加载 A 及其业务工作进程，确保收发进程也使用新代码。日常管理重启保留 QMT 和 LTtx；完整项目更新会重启能核实归属到当前运行目录的 LTtx，QMT 按更新流程完成部署和恢复。停止中心服务不会主动退出 QMT。工作进程异常恢复会保留 QMT 进程，任务恢复沿用原有委托核对机制，不自动重放下单/撤单请求。

启动参数中的 LTtx 地址、端口、QMT 命名管道和运行目录会同步给 A 与业务进程；相对路径在切换工作目录前转为绝对路径。多个实例须分别使用不同的 LTtx 端点和 QMT 命名管道，单独改 LTtx 端口不会解除命名管道冲突。启动被拒绝的实例不会覆盖正常实例的状态文件。

页面监听地址修改成功后，业务进程的异常恢复继续使用新地址。记录绑定到 A 的 PID 和创建时间，下一次完整启动不会误用旧进程记录。A 退出时业务进程会结束；若业务进程仍阻塞在启动或关闭阶段，父进程监测最多等待约 5 秒后强制退出它，QMT 不因此被关闭。

业务就绪状态同时检查 A 和业务进程各自的 LTtx 连接与频道状态。SDK 账号频道建立期间允许关闭操作取消连接；并发订阅同一账号复用频道消费线程。

## 并发与积压观察

核心查询、交易、控制探测以及业务任务各用独立的有界执行队列。交易与任务按账号维护必要的顺序；不同账号可以并行。默认核心查询 8 个工作线程、交易 8 个、控制探测 2 个；算法服务 6 个、通知 4 个，业务工作进程内也分开处理算法和通知。队列满时立即报错，排队超时的请求在执行前拒绝，防止调用方超时后又执行尚未开始的写操作。已开始执行的交易不会因客户端超时而自动撤销。

HTTP 使用独立连接处理上限，默认 64，可通过 `CFQUANT_HTTP_WORKERS` 调整。慢页面连接不会占用 A 的 LTtx 请求执行器。全推仍沿用独立的 LTtx 内存消费队列；这些队列的内存边界见下节，不应与有界 RPC 队列混淆。

- `GET /api/pipe-hub` 的中心状态包含 `requests`、`trade_requests`、`control_requests`、`service_requests` 和业务工作进程 `services` 状态。
- `GET /api/lttx` 的 `application_queues` 包含工作进程连接状态，以及算法、通知和控制队列。
- 执行器指标包括排队数、执行中数量、最旧等待时间、最长执行中耗时、最近排队/执行耗时、完成数与拒绝数。
- A 的业务日志位于 `log/center/services.log`，按日期或大小滚动，并由 A 的维护任务按保留规则清理。

账号配置与算法任务恢复状态仍需持久保存；全推行情分发不因此改为落盘缓冲。

## 内存、历史展示与监控

新的全推接收和分发链路不创建回调缓冲临时文件。Web 的行情历史展示缓存也改为纯内存，按批次数和字节上限淘汰最旧记录；淘汰历史记录不会取消实时频道发布。`CFQUANT_WEB_QUOTE_HISTORY_BYTES` 控制展示缓存容量，默认 64 MiB。超过该容量的单个展示记录不会留存。

SDK 队列沿用 LTtx 的内存排队方式，不合并原始批次，也不通过扩大磁盘缓存掩盖消费不足。当前行情队列没有硬性内存上限：长期消费不足仍会增长内存，需要根据监控调整消费者吞吐或拆分独立订阅。纯内存不等于无限容量，也不提供持久历史回放。关闭订阅会清空其未执行队列；已经进入用户函数的回调无法强制中止。

Web 的 `GET /api/lttx` 增加 `whole_quote_queues`，包括：

| 字段 | 含义 |
| --- | --- |
| `queued_callbacks` | 当前队列内待处理消息数，不含正在执行的回调 |
| `estimated_memory_bytes` | 排队原始消息对象的估算字节数，不是进程总内存 |
| `oldest_age_ms` | 队列中最旧消息已等待的时间 |
| `last_queue_ms` | 最近取出的消息在队列中的等待时间 |
| `last_callback_ms` | 最近一次成功回调执行时间 |
| `received_messages` / `processed` | 接收队列入队数量 / 成功执行回调数量 |
| `failures` / `error` | 消费异常次数 / 最近异常 |
| `spooled_bytes` | 此频道队列固定为 0 |

PipeHub 状态中的 `center` 提供 LTtx 连接状态、已提交全推批次数、最近全推时间、发送队列数量、发布失败次数和请求队列状态。Web 历史状态提供 `evicted_batches`，其 `disk_bytes`、`disk_live_bytes` 固定为 0。

日志、配置、订阅意图数据库与行情缓冲是不同用途。本次没有移除通用 RPC 对其他事件的兼容缓冲；旧 SDK、显式直连旧桥接入口也不自动获得新全推路径，需要同步升级。

## 启动与升级

原有启动脚本现在启动 A，由 A 的业务工作进程按需启动 LTtx。关闭浏览器不会停止后台任务；停止 A 则停止其业务工作进程，保留 QMT。需要自行管理 LTtx 时，可以先启动 LTtx，再在保存配置的运行目录启动 A：

```powershell
python -m LTtx.tx.LTtx_server
```

在另一个终端启动 A：

```powershell
cfquant-pipe-hub --home D:\cfquant-data
```

A 默认读取 `runtime/config/cfquant_web_config.json`，`--home` 会选择对应状态目录；自定义路径可用 `CFQUANT_WEB_CONFIG_FILE` 指定。LTtx 与 A、SDK 必须使用一致的 `CFQUANT_LTTX_HOST`、`CFQUANT_LTTX_PORT`、`CFQUANT_LTTX_TOKEN`。也可用 `python -m cfquant_pipe_hub` 启动 A。

一次升级需要同步完成：

1. 保存账号和数据提供者配置，在维护窗口更新源代码/安装包。
2. 更新 QMT 托管策略包或自包含脚本，包含主 `CFQUANT_LITE.py` 及使用中的 SH/SZ 入口；重载对应桥接运行时。
3. 重启 A 加载新频道发布代码，再重启 Web 和使用 SDK 的 Python 程序。仅重启 Web 不会替换仍在运行的旧 A。
4. 用不启动 Web 的 SDK 或 tx.py 订阅验证行情，再核对 `center.quote_batches`、本地队列年龄和交易查询/回调。

同一 LTtx 请求频道只部署一个活动 A。程序在同一 Windows 会话、同一配置端点下拒绝重复 A；这不是跨机器或跨会话的分布式锁，部署时仍需保持单实例。

离线回归使用独立端口的真实 LTtx 和模拟 QMT 命名管道，覆盖多消费者、纯 tx.py 接入、行情/交易隔离和共享账号事件。实际 QMT 全天吞吐、断线恢复及不同券商运行时仍需在目标环境进行持续验收。
