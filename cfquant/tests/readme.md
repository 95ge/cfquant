# cfquant 手工测试脚本

这个目录包含部署后的手工验证脚本和独立的 pytest 自动化测试。用户把 `cfquant` 部署到 QMT/Python 环境后，可以运行手工脚本，确认行情、数据下载、数据读取、交易只读查询等功能是否正常。

## 大 QMT 接口自动化回归

[`17_大QMT接口适配测试.py`](17_大QMT接口适配测试.py)使用模拟终端及真实协议编解码，不要求启动 QMT、PipeHub 或网页，不执行真实交易和板块写入，也不接收下文手工脚本的通信参数。

```powershell
python -X utf8 -m pytest "cfquant/tests/17_大QMT接口适配测试.py" -q
```

覆盖旧名称详情、可转债部分字段、除权因子日期筛选、板块管理、批量模型、期货持仓统计、三类两融查询及交易桥优先路由。通过自动化回归不代表券商终端数据和权限已验证。

## 手工脚本环境

脚本默认走 `auto` 自动路由模式，普通用户不需要选择通信模式。`cfquant` 会优先自动发现 Web LTtx 统一路由；如果现场只有旧的通用 PipeHub，再回退到 `ctypes`。

使用默认模式时要求：

- 当前 Python 能导入本项目的 `cfquant` 包。
- Web 控制台或 QMT 侧桥接已启动，并且至少有一种可用通信入口在线。

所有脚本都支持这些通用参数：

- `--transport auto`：通信模式，默认 `auto`。排查问题时才需要显式传 `ctypes`、`web_lttx` 或 `lttx`。
- `--bridge-id default`：桥接 ID，默认 `default`。
- `--timeout 15`：请求超时时间，单位秒。

## 1. 行情接收测试

全推行情回调测试，写法接近 xtquant：

```python
xtdata.subscribe_whole_quote(["SH", "SZ"], callback=on_whole_quote)
```

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

常用参数：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\1_行情接收测试.py --markets SH,SZ --sample-codes 3
```

同时验证全推和单证券订阅：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\1_行情接收测试.py --seconds 20 --include-single-quote --include-single-quote2 --stock-code 000001.SZ
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

常用参数：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\2_数据获取测试.py --stock-list 000001.SZ,600000.SH --stock-code 000001.SZ --period 1d --count 5
```

如果要验证因子或期权接口，需要传入当前 QMT 环境可用的字段和合约：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\2_数据获取测试.py --stock-code 000001.SZ --factor-fields your_factor --option-code 10000000.SH --option-date 202609
```

## 3. 数据下载测试

提交历史行情下载请求，并在下载后读取本地行情做验证。

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\3_数据下载测试.py --stock-list 000001.SZ --period 1d
```

脚本会先尝试 `download_history_data2`。如果当前 QMT 环境没有这个接口，会自动回退到旧版
`download_history_data`，然后继续读取本地行情验证。

如果需要指定区间：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\3_数据下载测试.py --stock-list 000001.SZ --period 1d --start-time 20260101 --end-time 20260821
```

同时演示财务数据下载/读取：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\3_数据下载测试.py --stock-list 000001.SZ --period 1d --include-financial --financial-tables ASHAREBALANCESHEET --financial-fields ASHAREBALANCESHEET.fix_assets
```

财务下载能力依赖当前 QMT 是否暴露对应 callable。部分 QMT 环境需要先在客户端“数据管理 - 财务数据下载”中下载财务数据，再运行读取验证。

## 4. 交易委托查询测试

只读查询资金、持仓、委托、成交，不会提交委托，不会撤单。

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

也可以显式传入账号：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\4_交易委托查询测试.py --account-id 你的资金账号 --account-type STOCK
```

信用账号只读查询：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\4_交易委托查询测试.py --account-id 你的信用资金账号 --account-type CREDIT
```

指定单笔持仓、单笔委托和 async 查询示例：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\4_交易委托查询测试.py --account-id 你的资金账号 --stock-code 000001.SZ --order-id 123456 --include-async
```

## 结果判断

脚本输出为一行一条 JSON，方便复制或重定向保存。

- `"ok": true`：该测试项调用成功。
- `"summary"`：返回数据摘要，包含类型、条数、字段和样例。
- `"example"`：该测试项对应的 Python 调用写法。
- `"skipped": true`：该示例需要额外参数或现场数据，当前已跳过。
- `"error"`：调用失败时的错误信息。
- 行情脚本中的 `heartbeat.delta_events > 0` 表示回调仍在持续进入。
- 行情脚本出现 `gap_warning` 才表示指定时间内没有收到新回调。

## 7. 同步/异步下单与回调综合测试

`7_同步异步下单测试.py` 将同步下单、异步下单、交易回调、委托查询、JSON 序列化检查和自动撤单放在一个流程中。可直接修改脚本顶部“用户配置区”的账号、标的、买卖方向、价格、数量和测试模式。

修改完成后直接运行脚本，程序会立即按照代码中的配置连接交易通道并执行测试：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\7_同步异步下单测试.py
```

默认会自动撤销测试结束时仍可撤的委托。将顶部 `AUTO_CANCEL` 改为 `False` 会保留委托；使用前需注意，市价附近的委托可能在撤单前已经成交。

## 18. 高级模式实机联调

`18_高级模式实机联调.py` 检查高级模式桥、数据查询、交易查询和回调，并将中文报告与原始事件写入指定目录。需要默认启用账号处于高级模式，两侧 QMT 桥均已启动。模拟账号属性由操作者确认，脚本不能独立鉴别模拟或实盘。

复测优先使用不下单模式；此模式仍会建立并释放行情订阅、尝试小范围历史行情下载，但不提交或撤销委托、不修改板块：

```powershell
python -X utf8 .\cfquant\tests\18_高级模式实机联调.py --account-id 你的模拟账号 --skip-order --output-dir .\private_docs\高级模式复测
```

只有显式传入与 `--account-id` 一致的 `--confirm-simulation`，且不传 `--skip-order`，才会尝试一笔 `000001.SZ`、100股、11.6元限价买入，并在发送开始10秒后尝试撤单。撤单不能保证阻止此前已发生的成交。委托通过固定高级交易桥发送，避免跨传输重试；该流程不代表网页下单路径已验证。同一个结果目录存在订单标记时拒绝再次下单，每次复测应使用新的结果目录保留证据。

结果中的 `PASS` 仅代表具体检查条件成立；历史语义、字段枚举、真正异步时序及盘中行情回调需要分别核验。`19_实机联调判定测试.py` 是纯离线判定回归测试，不连接 QMT、不下单。

## 20. 联调问题修复回归

`20_联调问题修复测试.py` 全部使用本地假桥和假账号，不连接 QMT、不下单。覆盖委托价格枚举、异步查询和回调线程、账号快照、异常隔离、停止清理、本地行情只读参数、旧模块识别和高级模式路由。

```powershell
python -X utf8 -m pytest -q .\cfquant\tests\20_联调问题修复测试.py
```

查询类 `_async` 现在立即返回请求序号，通过后台线程取得结果，在独立线程调用回调。调用方应等待事件或保持进程运行，不再假设方法返回时列表已经填充。调用 `trader.stop()` 清理工作线程；查询失败与回调异常记录在 `cfquant.xttrader` 日志中，不触发伪造的成功回调。
