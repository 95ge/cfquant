# cfquant 手工测试脚本

这个目录包含部署后的手工验证脚本和独立的 pytest 自动化测试。手工示例统一采用**修改顶部“用户配置区”，然后直接运行文件**的方式，不读取命令行参数。可以直接点击 IDE 的运行按钮，无需在文件名后添加参数。

**5、7、31 号保留原有下单默认行为，运行前务必核对配置。排查连接时先把 5 号的 `CONNECT_ONLY` 改为 `True`；4 号默认只读，18 号默认跳过下单。**

## 大 QMT 接口自动化回归

[`17_大QMT接口适配测试.py`](17_大QMT接口适配测试.py)使用模拟终端及真实协议编解码，不要求启动 QMT、PipeHub 或网页，不执行真实交易和板块写入，也不接收下文手工脚本的通信参数。

```powershell
python -X utf8 -m pytest "cfquant/tests/17_大QMT接口适配测试.py" -q
```

覆盖旧名称详情、可转债部分字段、除权因子日期筛选、板块管理、批量模型、期货持仓统计、三类两融查询及交易桥优先路由。通过自动化回归不代表券商终端数据和权限已验证。

## 手工脚本环境

Level2 专项：[`29_Level2行情测试.py`](29_Level2行情测试.py) 是只读手工测试，修改顶部 `STOCK_CODE/PERIODS/SECONDS/TEST_THOUSAND` 后直接运行，不添加参数。覆盖六类周期的查询和订阅，记录有效/异常回调、查询样本及退订结果，报告写入 `log/level2_test_时间.json`。无回调或查询为空标记为待确认，不判成功；不包含任何交易操作。

[`28_Level2接口适配测试.py`](28_Level2接口适配测试.py) 是对应离线回归，包含 SDK、Web 首包转发、共用桥、旧桥及三份 LITE 内嵌实现。参见 [Level2 行情适配说明](../../docs/Level2行情适配说明.md)。

脚本默认走 `auto` 自动路由模式，普通用户不需要选择通信模式。`cfquant` 会优先自动发现 Web LTtx 统一路由；如果现场只有旧的通用 PipeHub，再回退到 `ctypes`。

使用默认模式时要求：

- 当前 Python 能导入本项目的 `cfquant` 包。
- Web 控制台或 QMT 侧桥接已启动，并且至少有一种可用通信入口在线。

多数手工脚本在顶部提供这些通信配置，时间配置均以秒为单位：

```python
TRANSPORT = "auto"
BRIDGE_ID = "default"
REQUEST_TIMEOUT = 15.0
```

排查链路时在代码中修改 `TRANSPORT` 为 `ctypes`、`web_lttx` 或 `lttx`。18 号脚本专用于高级模式，固定检查默认账号的交易桥和普通桥。4、6、8 号的 `ACCOUNT_ID` 留空时，在运行时读取环境变量或 Web 默认账号；填写则优先使用代码配置。

## 1. 行情接收测试

全推行情回调测试，写法接近 xtquant：

```python
xtdata.subscribe_whole_quote(["SH", "SZ"], callback=on_whole_quote)
```

全推不设市场或证券代码白名单，列表会传给 QMT。例如可以把 `MARKETS` 改为 `"SH,SZ,BJ"`，或用 `xtdata.subscribe_whole_quote(["830799.BJ"], callback=on_whole_quote)` 订阅单只证券的全推。具体可用市场、代码和行情权限由券商 QMT 决定；期货等代码的大小写应按 QMT 要求填写。返回订阅号不代表当前时段一定有行情回调。

离线回归见 [`26_全推订阅测试.py`](26_全推订阅测试.py) 和 [`27_全推订阅页面测试.py`](27_全推订阅页面测试.py)，覆盖高级、通用、自包含极致模式以及网页参数提交，不执行真实交易。

需要单证券订阅时，也可以在同一个脚本里演示：

```python
xtdata.subscribe_quote("000001.SZ", period="1d", callback=on_single_quote)
xtdata.subscribe_quote2("000001.SZ", period="1d", dividend_type="none", callback=on_single_quote2)
```

运行：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\1_行情接收测试.py
```

默认一直运行并打印每条回调，按 `Ctrl+C` 停止。停止时会自动取消订阅。

常用代码配置：

```python
MARKETS = "SH,SZ"
SAMPLE_CODES = 3
```

同时验证全推和单证券订阅时，修改配置后直接运行文件：

```python
SECONDS = 20.0
INCLUDE_SINGLE_QUOTE = True
INCLUDE_SINGLE_QUOTE2 = True
STOCK_CODE = "000001.SZ"
```

## 2. 数据获取测试

测试实时 Tick、历史/本地行情读取、合约详情、板块成分、交易日、基础资料、指数权重、换手率、ETF、财务、因子和期权相关接口。

脚本里包含这些典型调用：

```python
xtdata.get_full_tick(stock_list)
xtdata.get_market_data(field_list, [stock_code], period, start_time, end_time, count)
xtdata.get_market_data_ex(field_list, [stock_code], period, start_time, end_time, count)
xtdata.get_local_data(field_list, [stock_code], period, start_time, end_time, count)
xtdata.get_instrument_detail(stock_code, False)
xtdata.get_stock_list_in_sector(sector_name)
xtdata.get_trading_dates(stock_code, start_date, end_date, count, period)
xtdata.get_stock_name(stock_code)
xtdata.get_financial_data(financial_fields, [stock_code], start_time, end_time)
```

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\2_数据获取测试.py
```

常用代码配置：

```python
STOCK_LIST = "000001.SZ,600000.SH"
STOCK_CODE = "000001.SZ"
PERIOD = "1d"
COUNT = 5
JSON_OUTPUT = False
```

验证因子或期权接口时，在顶部填写当前 QMT 环境可用的 `FACTOR_FIELDS`、`OPTION_CODE`、`OPTION_UNDERLYING` 和 `OPTION_DATE`。多个证券或字段用逗号分隔；缺少必要配置的项目会跳过。

## 3. 数据下载测试

提交历史行情下载请求，并在下载后读取本地行情做验证。

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\3_数据下载测试.py
```

脚本会先尝试 `download_history_data2`。如果当前 QMT 环境没有这个接口，会自动回退到旧版
`download_history_data`，然后继续读取本地行情验证。

需要指定区间时，修改顶部配置：

```python
STOCK_LIST = "000001.SZ"
PERIOD = "1d"
START_TIME = "20260101"
END_TIME = "20260821"
```

同时演示财务数据下载/读取：

```python
INCLUDE_FINANCIAL = True
FINANCIAL_TABLES = "ASHAREBALANCESHEET"
FINANCIAL_FIELDS = "ASHAREBALANCESHEET.fix_assets"
```

财务下载能力依赖当前 QMT 是否暴露对应 callable。部分 QMT 环境需要先在客户端“数据管理 - 财务数据下载”中下载财务数据，再运行读取验证。

## 4. 交易委托查询测试

默认只读查询资金、持仓、委托、成交，不下单、不撤单。可选下单由 `ORDER_ACCOUNT_ID`、`ORDER_SIDE`、`ORDER_STOCK_CODE`、`ORDER_VOLUME`、`ORDER_PRICE` 等配置控制；只有 `SUBMIT_ORDER = True` 且 `ORDER_CONFIRM_TEXT` 与预览输出的 `required_confirm_text` 一致才会提交，不会自动撤单。

脚本会演示这些只读调用：

```python
trader.query_stock_asset(account)
trader.query_stock_positions(account)
trader.query_stock_orders(account, cancelable_only=False)
trader.query_stock_trades(account)
trader.query_stock_position(account, stock_code)
trader.query_stock_order(account, order_id)
trader.query_account_status()
trader.query_new_purchase_limit(account)
```

如果 `runtime/config/cfquant_web_config.json` 中有默认账号，可以直接运行：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\4_交易委托查询测试.py
```

也可以在顶部明确填写账号：

```python
ACCOUNT_ID = "你的资金账号"
ACCOUNT_TYPE = "STOCK"
SUBMIT_ORDER = False
```

信用账号只读查询：

```python
ACCOUNT_ID = "你的信用资金账号"
ACCOUNT_TYPE = "CREDIT"
```

指定单笔持仓、单笔委托和 async 查询示例：

```python
STOCK_CODE = "000001.SZ"
ORDER_ID = "123456"
INCLUDE_ASYNC = True
```

## 结果判断

行情和查询脚本主要输出逐行 JSON；2、5、6 号也支持中文输出，可用顶部 `JSON_OUTPUT` 切换。18 号会保存独立报告。

- `"ok": true`：该测试项调用成功。
- `"summary"`：返回数据摘要，包含类型、条数、字段和样例。
- `"example"`：该测试项对应的 Python 调用写法。
- `"skipped": true`：该示例需要额外参数或现场数据，当前已跳过。
- `"error"`：调用失败时的错误信息。
- 行情脚本中的 `heartbeat.delta_events > 0` 表示回调仍在持续进入。
- 行情脚本出现 `gap_warning` 才表示指定时间内没有收到新回调。

## 5. 连接失败诊断

排查5号脚本连接失败时，先在顶部配置只检查连接，不提交或撤销委托：

```python
CONNECT_ONLY = True
DRY_RUN = False
SHOW_TRANSPORT_LOG = True
```

然后直接运行：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\5_真实下单测试.py
```

`DRY_RUN = True` 优先只预览配置，不连接，不能验证链路。`CONNECT_ONLY = True` 会连接、订阅账号并在结束时断开；连接失败时，即使 `SHOW_TRANSPORT_LOG = False`，也会显示 `last_connect_error`、异常类型及失败阶段。`connect()` 仍返回 `0/-1`，详细原因保存在交易对象上。

下单前在顶部核对 `ACCOUNT_ID`、`STOCK_CODE`、`SIDE`、`PRICE`、`VOLUME`、`PRICE_TYPE`、`STRATEGY_NAME` 和 `ORDER_REMARK`。`DRY_RUN` 和 `CONNECT_ONLY` 同时为 `False` 时会实际下单。需要确认保护时设置 `REQUIRE_CONFIRM = True` 并填写匹配的 `CONFIRM_TEXT`。

## 6. 交易回调监听

`6_回调测试.py` 连接账号并打印委托、成交和错误等回调，本脚本不主动下单。修改顶部 `ACCOUNT_ID`、`ACCOUNT_TYPE`、`DURATION` 和 `HEARTBEAT_INTERVAL` 后直接运行。

`DURATION = 0` 持续监听，`PAYLOAD_LIMIT = 0` 不截断回调内容。`DRY_RUN = True` 只预览配置，`SHOW_TRANSPORT_LOG = True` 显示通信日志。

## 7. 同步/异步下单与回调综合测试

`7_同步异步下单测试.py` 将同步下单、异步下单、交易回调、委托查询、JSON 序列化检查和自动撤单放在一个流程中。可直接修改脚本顶部“用户配置区”的账号、标的、买卖方向、价格、数量和测试模式。

修改完成后直接运行脚本，程序会立即按照代码中的配置连接交易通道并执行测试：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\7_同步异步下单测试.py
```

默认会自动撤销测试结束时仍可撤的委托。将顶部 `AUTO_CANCEL` 改为 `False` 会保留委托；使用前需注意，市价附近的委托可能在撤单前已经成交。

## 8. 委托及成交查询

`8_成交订单和委托订单查询测试.py` 只读查询并核对每条记录的 `order_id`。修改顶部 `ACCOUNT_ID`、`ACCOUNT_TYPE`、`ORDER_ID`、`CANCELABLE_ONLY` 和 `MAX_ROWS` 后直接运行。

`ORDER_ID` 留空不筛选；`MAX_ROWS = 0` 不打印明细；`CANCELABLE_ONLY = True` 只查询可撤委托，不执行撤单。

## 18. 高级模式实机联调

`18_高级模式实机联调.py` 检查高级模式桥、数据查询、交易查询和回调，并将中文报告与原始事件写入指定目录。需要默认启用账号处于高级模式，两侧 QMT 桥均已启动。模拟账号属性由操作者确认，脚本不能独立鉴别模拟或实盘。

复测优先使用不下单模式；此模式仍会建立并释放行情订阅、尝试小范围历史行情下载，但不提交或撤销委托、不修改板块：

修改顶部代码配置后直接运行文件：

```python
ACCOUNT_ID = "你的模拟账号"
SKIP_ORDER = True
CONFIRM_SIMULATION = ""
OUTPUT_DIR = ""
```

`OUTPUT_DIR` 留空时，在项目 `private_docs` 下自动创建带时间及唯一标识的中文报告目录；也可填写路径，但必须是新的空目录，已有报告不会覆盖。

只有 `SKIP_ORDER = False` 且 `CONFIRM_SIMULATION` 与 `ACCOUNT_ID` 完全一致，才会尝试一笔 `000001.SZ`、100股、11.6元限价买入，并在发送开始10秒后尝试撤单。撤单不能保证阻止此前已发生的成交。委托通过固定高级交易桥发送，避免跨传输重试；该流程不代表网页下单路径已验证。同一个结果目录存在订单标记时拒绝再次下单。

结果中的 `PASS` 仅代表具体检查条件成立；历史语义、字段枚举、真正异步时序及盘中行情回调需要分别核验。`19_实机联调判定测试.py` 是纯离线判定回归测试，不连接 QMT、不下单。

## 20. 联调问题修复回归

`20_联调问题修复测试.py` 全部使用本地假桥和假账号，不连接 QMT、不下单。覆盖委托价格枚举、异步查询和回调线程、账号快照、异常隔离、停止清理、本地行情只读参数、旧模块识别和高级模式路由。

```powershell
python -X utf8 -m pytest -q .\cfquant\tests\20_联调问题修复测试.py
```

查询类 `_async` 现在立即返回请求序号，通过后台线程取得结果，在独立线程调用回调。调用方应等待事件或保持进程运行，不再假设方法返回时列表已经填充。调用 `trader.stop()` 清理工作线程；查询失败与回调异常记录在 `cfquant.xttrader` 日志中，不触发伪造的成功回调。

## 21. 单股行情订阅

`21_单股行情订阅测试.py` 分别统计单股回调、通用行情事件和原始事件，默认订阅 `000001.SZ` 的 `tick` 并观察 12 秒。修改顶部 `STOCK_CODE`、`PERIOD`、`SECONDS` 和 `USE_QUOTE2` 后直接运行。

跨机器连接可配置 `TRANSPORT`、`HOST` 和 `PORT`。`TOKEN = None` 使用运行时配置，不要把真实凭据提交到 Git。

## 30. cftrader 批量下单性能基准

`30_cftrader批量下单性能基准.py` 使用本地假 QMT 交易桥复测 100 单的批量同步、100 次单笔同步、批量异步和 100 次单笔异步耗时。不连接 Web、LTtx、PipeHub 或真实 QMT，不产生真实委托；结果用于观察 SDK 到桥接分发和本地 `passorder` 循环的协议开销。

```powershell
python -X utf8 .\cfquant\tests\30_cftrader批量下单性能基准.py
```

## 31. cftrader 模拟账号批量下单测试

`31_cftrader模拟账号批量下单测试.py` 会直接调用模拟信用账号 `900010001595`，按批量同步、100 次单笔同步、批量异步和 100 次单笔异步四条路径提交委托并统计耗时。脚本默认桥接 ID 为 `acct_4b2b38c167`，默认测试 `600000.SH`，每笔 100 股，价格按行情参考价自动折算；运行结束会按本次备注前缀查询委托并撤掉可撤订单。

```powershell
python -X utf8 .\cfquant\tests\31_cftrader模拟账号批量下单测试.py
```

## 代码配置回归

9 至 17、19、20、22、23 号、30 号以及 `test_*.py` 是自动化测试，不是连接账号的手工示例。pytest 运行方式保持不变，正式产品的 CLI 及其测试不受本次调整影响。

`22_连接诊断测试.py` 和 `23_示例配置测试.py` 使用替身客户端检查代码配置、连接诊断和下单保护，不连接 QMT、不提交委托：

```powershell
python -m pytest -q "cfquant/tests/22_连接诊断测试.py" "cfquant/tests/23_示例配置测试.py"
```
