# 普通 QMT、极速交易端与 ctypes Pipe 接口耗时对比

测试时间：2026-08-13 11:29
测试目录：`D:\兴业证券SMT-Q\python\cfquant2`
测试账号：`8885060548`
交易查询单项样本数：30 次
`ping/status` 样本数：10 次

## 测试对象

- **LTtx 普通 QMT 通道**：`CFQUANT.py`，请求通道 `cfquant.normal.request`
- **LTtx 极速交易通道**：`CFQUANT_TRADE_LOWLAT.py`，请求通道 `cfquant.trade.request`
- **ctypes Pipe 单桥通道**：`CFQUANT_CTYPE_ALL.py`，请求通道 `cfquant.trade.request`
- **Pipe Hub**：`cfquant_pipe_hub.py`

本次统计的是外部 Python 调用接口到收到 QMT 回包的端到端耗时。测试通过底层 RPC 客户端显式指定通道，避免 `XtQuantTrader` 自动路由导致普通/极速口径混淆。

## 测试结果

| 接口 | 模式 | min ms | avg ms | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|
| `cfquant.ping` | LTtx 普通 QMT | 48.268 | 122.652 | 54.536 | 109.964 | 655.420 |
| `cfquant.ping` | LTtx 极速交易端 | 0.472 | 61.485 | 0.524 | 2.004 | 608.198 |
| `cfquant.ping` | ctypes Pipe 单桥 | 6.521 | 62.119 | 49.422 | 100.689 | 154.530 |
| `cfquant.status` | LTtx 普通 QMT | 30.408 | 62.730 | 55.747 | 86.693 | 97.081 |
| `cfquant.status` | LTtx 极速交易端 | 0.471 | 0.549 | 0.528 | 0.602 | 0.776 |
| `cfquant.status` | ctypes Pipe 单桥 | 8.596 | 54.686 | 43.742 | 98.273 | 106.974 |
| `xttrader.query_stock_asset` | LTtx 普通 QMT | 105.044 | 275.601 | 243.382 | 434.756 | 488.681 |
| `xttrader.query_stock_asset` | LTtx 极速交易端 | 0.803 | 1.077 | 0.999 | 1.522 | 1.771 |
| `xttrader.query_stock_asset` | ctypes Pipe 单桥 | 156.306 | 261.621 | 245.814 | 381.566 | 466.891 |
| `xttrader.query_stock_positions` | LTtx 普通 QMT | 160.029 | 285.023 | 283.979 | 389.801 | 404.678 |
| `xttrader.query_stock_positions` | LTtx 极速交易端 | 1.338 | 1.790 | 1.694 | 2.427 | 2.535 |
| `xttrader.query_stock_positions` | ctypes Pipe 单桥 | 110.824 | 294.223 | 262.382 | 451.955 | 544.733 |
| `xttrader.query_stock_orders` | LTtx 普通 QMT | 154.785 | 261.415 | 232.208 | 404.606 | 437.551 |
| `xttrader.query_stock_orders` | LTtx 极速交易端 | 1.625 | 2.290 | 2.226 | 3.091 | 3.389 |
| `xttrader.query_stock_orders` | ctypes Pipe 单桥 | 191.669 | 286.816 | 253.292 | 406.740 | 494.549 |
| `xttrader.query_stock_trades` | LTtx 普通 QMT | 159.386 | 284.761 | 259.975 | 404.057 | 590.007 |
| `xttrader.query_stock_trades` | LTtx 极速交易端 | 1.313 | 1.892 | 1.719 | 2.681 | 2.936 |
| `xttrader.query_stock_trades` | ctypes Pipe 单桥 | 153.344 | 283.455 | 242.598 | 499.862 | 600.662 |

## 结论

1. **LTtx 极速交易端确实是低延迟路径**
   四个交易查询接口平均 `1-3ms`，明显快于 LTtx 普通 QMT 和 ctypes Pipe 单桥。之前看到的 `1-3ms` 来自 `cfquant.trade.request` 极速交易通道，不是普通 QMT 通道。

2. **LTtx 普通 QMT 与 ctypes Pipe 单桥交易查询属于同一量级**
   普通 QMT 通道平均约 `261-285ms`，ctypes Pipe 单桥平均约 `262-294ms`，差异不大。两者主要耗时都在普通桥队列、QMT 查询接口和序列化，不在传输层。

3. **ctypes Pipe 单桥不等价于极速交易端**
   当前 `CFQUANT_CTYPE_ALL.py` 为部署方便，把 normal/trade 两个通道都交给 `PipeNormalQmtBridge`。它能验证 ctypes 通信和单文件部署，但交易请求没有走独立低延迟交易循环。

4. **行情全推仍适合 ctypes Pipe**
   全推订阅脚本观察到的数据延迟较低，说明 ctypes Pipe 用于实时行情推送是可行的。同步交易查询的慢，不代表行情推送慢。

## 建议

- 行情全推：优先 ctypes Pipe。
- 同步行情查询：LTtx 普通和 ctypes Pipe 都可用，差距预计不大。
- 交易查询/下单/撤单：当前优先 LTtx 极速交易端。
- ctypes 后续优化方向：做“单文件双内核”入口。一个文件内同时启动普通 Pipe 桥和低延迟交易 Pipe 桥，部署仍是单文件，但交易请求必须走独立交易处理路径，而不是普通桥队列。

## ctypes 低延迟单文件入口

已新增 `qmt_scripts/CFQUANT_CTYPE_ALL_LOWLAT.py`，用于测试 ctypes 的单文件双内核方案。

- 普通行情和普通查询：注册到 `cfquant.normal.request`，由 `PipeNormalQmtBridge` 处理。
- 交易查询、下单和撤单：注册到 `cfquant.trade.request`，由 `PipeTradeBridge` 独立处理。
- 交易处理循环默认运行在后台线程，`init()` 会正常返回，QMT 侧仍然只需要加载一个脚本。
- 回调事件仍通过普通 Pipe 桥发布到 callback 通道。

部署测试时，只加载 `CFQUANT_CTYPE_ALL_LOWLAT.py` 这一个 ctypes QMT 脚本即可；不要同时加载 `CFQUANT_CTYPE_ALL.py`、`CFQUANT_CTYPE.py` 或 `CFQUANT_TRADE_CTYPE_LOWLAT.py`，否则同一个请求通道会被后加载的桥覆盖。

当前单文件 ctypes 入口优先保证部署简单和行情/交易同时可用。交易循环在后台线程内以 `CFQUANT_CTYPE_TRADE_SLEEP_SECONDS=0.001` 轮询，实际交易延迟需要部署后复测确认。
