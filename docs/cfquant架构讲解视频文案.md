# cfquant 架构讲解视频文案

本文案用于交给 AI 视频制作工具生成项目架构讲解视频。内容基于 `docs/项目架构图.md` 和 `docs/cfquant_qmt_architecture_and_callbacks.md`，重点讲清楚 cfquant 的请求链路、部署模式、回调机制和连接生命周期。

## 视频定位

| 项目 | 建议 |
|---|---|
| 视频标题 | cfquant 架构说明：外部 Python 如何稳定调用大 QMT |
| 推荐时长 | 4 分 20 秒到 4 分 40 秒 |
| 目标观众 | 准备接入 cfquant 的量化开发者、运维人员、策略开发人员 |
| 讲解风格 | 技术讲解，语速中等，关键概念前后有停顿 |
| 画面风格 | 干净的技术架构图、节点流转动画、日志片段、代码片段、路由高亮 |
| 配音要求 | 中文普通话，稳重、清晰、有层次；讲到风险和验证时语气更谨慎 |
| 字幕要求 | 中文字幕常驻底部，关键术语可高亮，例如 `auto`、`LTtx`、`Web 统一路由`、`PipeHub`、`subscribe(account)` |

## 视频总提示词

请制作一个中文技术讲解视频，主题是“cfquant 如何把大 QMT 的行情、查询、下单、撤单和回调能力稳定接出来”。视频需要包含架构图、链路动画、代码片段、日志片段、中文字幕和中文配音。

画面要像工程架构说明，不要做成营销片。整体风格清爽、专业，背景可以使用浅色网格、白色画布、深色代码块和少量蓝绿橙紫色链路高亮。每次讲到请求链路时，用一个小光点或数据包沿着节点移动，表现请求从外部 Python 到 QMT 内部桥，再返回调用者。讲到回调时，用广播扩散效果表现账号级回调会推送给所有已订阅客户端。

配音语气要清楚、有证据感。遇到“先停一下”“这里最容易混”“这个细节很重要”等句子时，请加入 0.5 到 0.8 秒的自然停顿。不要夸大功能，不要说 cfquant 会替用户做交易判断，只强调它提供稳定、可观察、可排查的本地接口。

## 核心讲解主线

1. cfquant 不是交易决策系统，而是把大 QMT 的能力稳定桥接出来。
2. 外部 Python 先进入 cfquant 兼容 API，再进入 RPC 协议层。
3. 默认 `auto` 模式优先通过 LTtx 发现 Web 统一路由。
4. Web 根据账号、账号类型、运行模式、bridge 和市场路由，把请求转给通用模式或高级模式。
5. 通用模式主要通过 PipeHub 进入 QMT，部署更简单。
6. 高级模式把普通桥和低延迟交易桥拆开，适合更细的交易链路控制。
7. 请求响应只返回给发起请求的 client，账号级交易回调要广播给所有已订阅该账号的客户端。
8. `import cfquant` 不会立即连接 LTtx，第一次请求或 `start/connect/subscribe` 才建立底层连接。
9. 排查问题时要按层确认：外部连接模式、Web 路由、PipeHub 或 LTtx、QMT 回调注册、原始回调是否到达桥。

## 分镜脚本

### 01 项目总览

| 项目 | 内容 |
|---|---|
| 建议时长 | 18 秒 |
| 画面 | 出现 cfquant 标识，背景是大 QMT、外部 Python、Web 控制台、行情和交易回调的简化节点。 |
| 动画 | 多个能力标签从 QMT 侧浮出：行情、查询、下单、撤单、回调，然后汇聚到 cfquant。 |
| 旁白 | 你好，这支视频，我们不讲口号，直接讲 cfquant 的运行逻辑。先停一下。它做的事情很明确：把大 QMT 里的行情、查询、下单、撤单和回调，整理成外部 Python 和网页都能稳定使用的一套本地能力。 |
| 字幕 | cfquant 把大 QMT 的行情、查询、下单、撤单和回调，整理成外部 Python 与网页都能稳定使用的本地能力。 |

### 02 先看证据

| 项目 | 内容 |
|---|---|
| 建议时长 | 18 秒 |
| 画面 | 展示一张横向架构图：外部 API、RPC 客户端、Web 服务、LTtx、PipeHub、QMT 内部桥、QMT 原生能力。 |
| 动画 | 镜头从左到右扫过，每扫到一层，该层边框高亮。 |
| 旁白 | 先看架构证据。这里不是一个简单接口封装。从外部 API，到 RPC 客户端，再到 Web、LTtx、PipeHub，最后进入 QMT 内部桥。每一层都有明确职责，所以出问题时，也能按层排查。 |
| 字幕 | 从外部 API 到 QMT 内部桥，每一层都有明确职责。这也是后续排查和扩展的基础。 |

### 03 总体架构

| 项目 | 内容 |
|---|---|
| 建议时长 | 25 秒 |
| 画面 | 用流程图展示：外部 Python -> cfquant API -> RPC 协议层 -> 本地服务层 -> QMT 入口脚本 -> QMT 内部桥 -> QMT 原生函数。 |
| 动画 | 请求数据包沿链路移动，到 QMT 原生函数后再沿原路返回 response。 |
| 旁白 | 总体上，外部 Python 先进入 cfquant 的兼容 API。`xttrader` 负责交易，`xtdata` 负责行情。然后由 `client` 和 `protocol` 处理请求、响应和事件。再往下，是本地 Web 服务、LTtx 和 PipeHub。最后，QMT 里的入口脚本把请求交给内部桥，调用原生 QMT 能力。 |
| 字幕 | 外部 Python -> cfquant API -> RPC 协议层 -> 本地服务层 -> QMT 桥。QMT 原生能力仍在 QMT 内部执行。 |

### 04 默认 auto 链路

| 项目 | 内容 |
|---|---|
| 建议时长 | 25 秒 |
| 画面 | 展示默认链路：外部 Python -> LTtx Runtime -> Web 统一路由 -> Account Routing -> 目标桥。 |
| 动画 | 先高亮 `cfquant.runtime`，再高亮 `cfquant.web.request`，最后根据账号配置分叉到不同桥。 |
| 旁白 | 默认 `transport` 等于 `auto`。只要 Web 服务在线，它会通过 LTtx 发布 `cfquant.runtime`。外部 Python 第一次请求时，会连接 LTtx，发现 Web 统一路由，然后把请求交给 Web。Web 再根据账号、账号类型、`bridge_id` 和市场，把请求送到对应模式。 |
| 字幕 | 默认 auto：外部 Python 先通过 LTtx 发现 Web 统一路由。Web 再按账号、模式、bridge 和市场做转发。 |

### 05 通用模式

| 项目 | 内容 |
|---|---|
| 建议时长 | 22 秒 |
| 画面 | 展示通用模式链路：Web 或外部 Python -> PipeHub -> `CFQUANT_CTYPE_ALL_LOWLAT.py` -> PipeNormalQmtBridge / PipeTradeBridge -> QMT。 |
| 动画 | Web 路由节点把请求交给 PipeHub，PipeHub 再分发到 normal 和 trade 两条 pipe。 |
| 旁白 | 通用模式下，一个 QMT 加载 `CFQUANT_CTYPE_ALL_LOWLAT.py`。网页请求先到 Web，再到 PipeHub；外部 Python 默认 `auto` 也是先到 Web，再落到 PipeHub。QMT 落地这一段不依赖 LTtx，所以部署更简单。 |
| 字幕 | 通用模式：Web / Python -> Web 路由 -> PipeHub -> ctypes 通用端 -> QMT。QMT 落地段不依赖 LTtx，部署更简单。 |

### 06 高级模式

| 项目 | 内容 |
|---|---|
| 建议时长 | 26 秒 |
| 画面 | 左侧是普通 QMT，运行 `CFQUANT.py`；右侧是极速交易 QMT，运行 `CFQUANT_TRADE_LOWLAT.py`。中间用 LTtx 连接。 |
| 动画 | 查询、行情、回调流向普通桥；下单、撤单和交易查询流向极速交易桥。 |
| 旁白 | 高级模式适合追求交易端低延迟。它需要两个 QMT：普通 QMT 跑 `CFQUANT.py`，负责查询、行情和账号级回调；极速交易端跑 `CFQUANT_TRADE_LOWLAT.py`，只处理下单、撤单和交易查询。这里要注意，纯交易桥不承接 QMT 原始账号回调。 |
| 字幕 | 高级模式：普通 QMT 负责查询、行情和账号级回调。极速交易端只负责低延迟下单、撤单和交易查询。 |

### 07 回调机制

| 项目 | 内容 |
|---|---|
| 建议时长 | 25 秒 |
| 画面 | 分成两部分。左边是“请求级 response”，右边是“账号级回调广播”。 |
| 动画 | 左边 response 只沿原路回到发起请求的 client_id；右边 `on_stock_order`、`on_stock_trade` 用广播效果推送到多个订阅客户端。 |
| 旁白 | 回调这里最容易混。先停一下。同步下单、撤单、查询的 `response`，只回给发起请求的 `client_id`。可是委托、成交、资产、持仓这类账号级回调，会按 `bridge_id`、`account_type`、`account_id`，广播给所有已经 `subscribe` 这个账号的外部客户端。 |
| 字幕 | 请求级 response：只回给发起请求的 client_id。账号级回调：广播给所有已 subscribe(account) 的客户端。 |

### 08 行情链路

| 项目 | 内容 |
|---|---|
| 建议时长 | 19 秒 |
| 画面 | 展示行情查询和行情订阅两条线：同步查询返回数据表，订阅行情返回 quote event。 |
| 动画 | 查询请求回到调用者；订阅事件按 `quote:<subscribe_id>` 定向推送。 |
| 旁白 | 行情也是一样的路由原则。同步查询会按账号或共享行情源选择 QMT 桥。订阅行情时，外部 callback 绑定到 `quote` 加 `subscribe_id`，事件按订阅 ID 定向推送，不是账号级广播。 |
| 字幕 | 行情查询按账号或共享行情源选择 QMT 桥。行情订阅事件按 subscribe_id 定向推送。 |

### 09 多账号路由

| 项目 | 内容 |
|---|---|
| 建议时长 | 22 秒 |
| 画面 | 展示 Web 配置表：账号、账号类型、运行模式、bridge_id、市场。右侧连接多个 QMT 实例。 |
| 动画 | 一个请求进入 Web 后，根据账号 A、账号 B、沪市、深市分别流向不同桥。 |
| 旁白 | 多账号场景里，用户不应该手工记一堆通道。Web 保存账号、账号类型、运行模式、QMT 目录、`bridge_id` 和市场拆分关系。请求进来以后，路由表决定走哪个 PipeHub、哪个 LTtx 桥、哪个 QMT。 |
| 字幕 | 多账号核心：账号配置和路由表。请求由 Web 统一选择 PipeHub、LTtx 桥和目标 QMT。 |

### 10 连接生命周期

| 项目 | 内容 |
|---|---|
| 建议时长 | 26 秒 |
| 画面 | 状态图：import cfquant -> 创建对象 -> start/connect/request/subscribe -> 建立底层连接 -> stop/close/进程退出。 |
| 动画 | `import cfquant` 和 `StockAccount` 节点保持灰色“不连接”；第一次请求后，连接线点亮。 |
| 旁白 | 再停一下，这个细节很重要。只 `import cfquant`，或者只创建 `StockAccount`，不会连接 LTtx。真正建立连接，是第一次请求，或者 `trader.start`、`connect`、`subscribe`。默认 `auto` 命中 Web route 后，会保持 LTtx 客户端连接；强制 `ctypes` 时，保持的是 named pipe 连接。 |
| 字幕 | import cfquant / 创建 StockAccount 不会立即连接 LTtx。第一次请求或 trader.start/connect/subscribe 才建立底层连接。 |

### 11 验证与排查

| 项目 | 内容 |
|---|---|
| 建议时长 | 23 秒 |
| 画面 | 展示测试日志片段：`client_class=WebLttxRpcClient`、`transport=Web LTtx route`、`latency_ms`、回调计数。 |
| 动画 | 排查清单逐条打勾：外部连接模式、QMT 回调注册、raw callback、Web/PipeHub 转发。 |
| 旁白 | 验证时，不要只看最后有没有回调。先看外部客户端实际连的是 WebLttx、Pipe 还是 LTtx；再看 QMT 是否启用了 `set_auto_trade_callback`；最后看 raw callback 有没有到达桥，再有没有被 Web 或 PipeHub 转发。 |
| 字幕 | 排查顺序：外部连接模式 -> QMT 回调注册 -> raw callback -> Web/PipeHub 转发。真实下单和回调测试日志统一按毫秒口径观察。 |

### 12 总结

| 项目 | 内容 |
|---|---|
| 建议时长 | 20 秒 |
| 画面 | 回到总架构图，所有链路以低亮度显示，最终高亮 cfquant、Web 统一路由、QMT 内部桥三个核心点。 |
| 动画 | 架构图逐层收束成一句总结：更好调用、更好观察、更好排查。 |
| 旁白 | 最后收一下。cfquant 不是替你做交易判断，而是把 QMT 能力变成更清楚、更稳定、更可观察的本地接口。实盘前，请先在自己的账号、自己的网络和自己的 QMT 环境里，把完整流程验证稳。 |
| 字幕 | cfquant 让 QMT 更好调用、更好观察、更好排查。实盘前，请在自己的环境里充分验证完整流程。 |

## 完整旁白稿

你好，这支视频，我们不讲口号，直接讲 cfquant 的运行逻辑。先停一下。它做的事情很明确：把大 QMT 里的行情、查询、下单、撤单和回调，整理成外部 Python 和网页都能稳定使用的一套本地能力。

先看架构证据。这里不是一个简单接口封装。从外部 API，到 RPC 客户端，再到 Web、LTtx、PipeHub，最后进入 QMT 内部桥。每一层都有明确职责，所以出问题时，也能按层排查。

总体上，外部 Python 先进入 cfquant 的兼容 API。`xttrader` 负责交易，`xtdata` 负责行情。然后由 `client` 和 `protocol` 处理请求、响应和事件。再往下，是本地 Web 服务、LTtx 和 PipeHub。最后，QMT 里的入口脚本把请求交给内部桥，调用原生 QMT 能力。

默认 `transport` 等于 `auto`。只要 Web 服务在线，它会通过 LTtx 发布 `cfquant.runtime`。外部 Python 第一次请求时，会连接 LTtx，发现 Web 统一路由，然后把请求交给 Web。Web 再根据账号、账号类型、`bridge_id` 和市场，把请求送到对应模式。

通用模式下，一个 QMT 加载 `CFQUANT_CTYPE_ALL_LOWLAT.py`。网页请求先到 Web，再到 PipeHub；外部 Python 默认 `auto` 也是先到 Web，再落到 PipeHub。QMT 落地这一段不依赖 LTtx，所以部署更简单。

高级模式适合追求交易端低延迟。它需要两个 QMT：普通 QMT 跑 `CFQUANT.py`，负责查询、行情和账号级回调；极速交易端跑 `CFQUANT_TRADE_LOWLAT.py`，只处理下单、撤单和交易查询。这里要注意，纯交易桥不承接 QMT 原始账号回调。

回调这里最容易混。先停一下。同步下单、撤单、查询的 `response`，只回给发起请求的 `client_id`。可是委托、成交、资产、持仓这类账号级回调，会按 `bridge_id`、`account_type`、`account_id`，广播给所有已经 `subscribe` 这个账号的外部客户端。

行情也是一样的路由原则。同步查询会按账号或共享行情源选择 QMT 桥。订阅行情时，外部 callback 绑定到 `quote` 加 `subscribe_id`，事件按订阅 ID 定向推送，不是账号级广播。

多账号场景里，用户不应该手工记一堆通道。Web 保存账号、账号类型、运行模式、QMT 目录、`bridge_id` 和市场拆分关系。请求进来以后，路由表决定走哪个 PipeHub、哪个 LTtx 桥、哪个 QMT。

再停一下，这个细节很重要。只 `import cfquant`，或者只创建 `StockAccount`，不会连接 LTtx。真正建立连接，是第一次请求，或者 `trader.start`、`connect`、`subscribe`。默认 `auto` 命中 Web route 后，会保持 LTtx 客户端连接；强制 `ctypes` 时，保持的是 named pipe 连接。

验证时，不要只看最后有没有回调。先看外部客户端实际连的是 WebLttx、Pipe 还是 LTtx；再看 QMT 是否启用了 `set_auto_trade_callback`；最后看 raw callback 有没有到达桥，再有没有被 Web 或 PipeHub 转发。

最后收一下。cfquant 不是替你做交易判断，而是把 QMT 能力变成更清楚、更稳定、更可观察的本地接口。实盘前，请先在自己的账号、自己的网络和自己的 QMT 环境里，把完整流程验证稳。

## 关键画面素材清单

| 画面 | 内容建议 |
|---|---|
| 总体架构图 | 外部 Python、cfquant API、RPC 协议层、本地 Web 服务、LTtx、PipeHub、QMT 入口脚本、QMT 内部桥、QMT 原生能力 |
| 默认 auto 链路 | 突出 `cfquant.runtime`、`cfquant.web.request`、Web 统一路由、账号路由 |
| 通用模式图 | 突出 PipeHub、`CFQUANT_CTYPE_ALL_LOWLAT.py`、normal/trade 双通道 |
| 高级模式图 | 突出 `CFQUANT.py` 和 `CFQUANT_TRADE_LOWLAT.py` 分工 |
| 回调机制图 | 左侧请求级 response，右侧账号级广播 callback |
| 行情链路图 | 同步查询、订阅行情、`quote:<subscribe_id>` |
| 连接生命周期图 | `import cfquant` 不连接，首次请求或 `start/connect/subscribe` 后连接 |
| 排查画面 | 真实日志片段、回调计数、`latency_ms`、连接模式 |

## 术语显示规范

| 术语 | 建议屏幕显示 |
|---|---|
| 大 QMT | 大 QMT |
| Web 统一路由 | Web Route / Web 统一路由 |
| LTtx | LTtx |
| PipeHub | cfquant_pipe_hub / PipeHub |
| 通用模式 | 通用模式 ctypes |
| 高级模式 | 高级模式 lttx |
| 极致模式 | lite / 极致模式 |
| 请求响应 | request / response |
| 账号级回调 | account callback broadcast |
| 行情订阅事件 | quote event / quote:&lt;subscribe_id&gt; |

## 配音停顿和情绪标记

| 位置 | 处理方式 |
|---|---|
| “先停一下” | 停顿 0.5 到 0.8 秒，语气稍微放慢 |
| “这里最容易混” | 停顿 0.6 秒，语气强调，画面切到左右对比 |
| “这个细节很重要” | 停顿 0.6 秒，字幕加粗或高亮 |
| “不要只看最后有没有回调” | 语气谨慎，配合排查清单动画 |
| “实盘前” | 语气收稳，强调验证和风险控制 |

## 制作注意事项

1. 不要把 cfquant 描述成替代 QMT 的系统，它是 QMT 能力的外部桥接和兼容访问层。
2. 不要说所有模式都会一直连接 LTtx。正确说法是：默认 `auto + Web 在线` 后，外部客户端会持续连接 LTtx 的 Web route；强制 `ctypes` 时持续连接 PipeHub named pipe。
3. 不要把请求响应和账号回调混在一起。请求响应只回给发起者，账号级回调广播给订阅该账号的客户端。
4. 不要说高级模式的纯交易桥负责原始账号回调。账号级回调由普通桥承接。
5. 所有字幕中的代码名、通道名、函数名要保持英文原样，不要翻译。
