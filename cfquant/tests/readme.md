# cfquant 手工测试脚本

这个目录用于放置部署后的手工验证脚本。用户把 `cfquant` 部署到 QMT/Python 环境后，可以直接运行这里的脚本，确认行情、数据下载、数据读取、交易只读查询等功能是否正常。

脚本默认走 `ctypes` 通用 PipeHub 模式，要求：

- QMT 中已经加载并运行 cfquant 通用桥接脚本。
- 本机 `cfquant_pipe_hub.py` 正在运行。
- 当前 Python 能导入本项目的 `cfquant` 包。

所有脚本都支持这些通用参数：

- `--transport ctypes`：通信模式，默认 `ctypes`。如需测试自动路由，可传 `--transport auto`。
- `--bridge-id default`：桥接 ID，默认 `default`。
- `--timeout 15`：请求超时时间，单位秒。

## 1. 行情接收测试

全推行情回调测试，写法接近 xtquant：

```python
xtdata.subscribe_whole_quote(["SH", "SZ"], callback=on_whole_quote)
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

## 2. 数据获取测试

测试实时 Tick、历史/本地行情读取、合约详情、板块成分查询。

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\2_数据获取测试.py
```

常用参数：

```powershell
D:\ProgramData\anaconda3\python.exe .\cfquant\tests\2_数据获取测试.py --stock-list 000001.SZ,600000.SH --stock-code 000001.SZ --period 1d --count 5
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

## 4. 交易委托查询测试

只读查询资金、持仓、委托、成交，不会提交委托，不会撤单。

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

## 结果判断

脚本输出为一行一条 JSON，方便复制或重定向保存。

- `"ok": true`：该测试项调用成功。
- `"summary"`：返回数据摘要，包含类型、条数、字段和样例。
- `"error"`：调用失败时的错误信息。
- 行情脚本中的 `heartbeat.delta_events > 0` 表示回调仍在持续进入。
- 行情脚本出现 `gap_warning` 才表示指定时间内没有收到新回调。
