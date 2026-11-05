# Python API 教程维护

网页手册的接口范围和适配状态来自 `docs/xtquant原版接口适配清单.md`。
`python_api_examples.py` 维护本项目编写的新旧调用示例及参数解释；
`build_python_api_reference.py` 提取官方页面的接口签名、字段和枚举等技术资料，
结合当前 SDK 源码生成 `web_dashboard/python-api-data.js`。
官方文章正文通过页面内的“讯投在线原文”阅读，不随生成数据保存。

普通用户阅读教程不需要联网或运行生成器，也不需要先配置账号。
只有展开在线原文或打开来源链接时才访问讯投网站。

## 更新数据

生成器的开发依赖为 `beautifulsoup4`，不增加应用运行依赖。
在项目根目录使用 PowerShell 执行：

```powershell
python -m pip install beautifulsoup4
New-Item -ItemType Directory -Force .tmp_pytest_python_reference
curl.exe -L --fail https://dict.thinktrader.net/nativeApi/start_now.html -o .tmp_pytest_python_reference/start_now.html
curl.exe -L --fail https://dict.thinktrader.net/nativeApi/xtdata.html -o .tmp_pytest_python_reference/xtdata.html
curl.exe -L --fail https://dict.thinktrader.net/nativeApi/xttrader.html -o .tmp_pytest_python_reference/xttrader.html
python -X utf8 tools/build_python_api_reference.py --source-dir .tmp_pytest_python_reference
python -m pytest -q cfquant/tests/test_python_api_reference.py cfquant/tests/test_tutorial_reader.py
```

浏览器回归另需 `playwright` 和 Chromium。测试使用本地静态服务器和模拟 API，
不会登录真实账号、修改配置、连接 QMT 或提交委托。

调整支持状态时先核对实现并更新适配清单；“条件待验证”仍显示尚未支持。
生成器会拒绝缺少示例的已适配条目，并在官方正文接口签名无法解析时停止。
字段和枚举表是原版协议参考，不能据此推断当前桥已提供全部字段。
板块修改及下单、撤单示例默认关闭写入开关。
提交更新时包含生成的 JS，并更新 `index.html` 中两个 Python 文档脚本的版本参数。

## 大 QMT 内置接口目录

`QmtInnerApi` 的网页目录独立维护在 `web_dashboard/qmt-inner-api-data.js`，同时供“接口”页和 Python API 参考使用。顶层只有“大 QMT 内置接口”，下设系统与会话、行情与数据、交易、交易回调、扩展数据与因子五个子组。源方法清单取自 `cfquant/qmt_inner_catalog.py`，显式签名取自 `cfquant/qmt_inner.py`，项目示例由 `tools/qmt_inner_examples.py` 维护。纳入范围以外部调用价值为准，排除项和理由见 `docs/大QMT内置接口.md`。

将官方 `innerApi` 目录下的 `system_function.html`、`data_function.html`、`trading_function.html`、`callback_function.html`、`quote_function.html` 保存到本地目录后执行：

```powershell
python -X utf8 tools/build_qmt_inner_reference.py --source-dir runtime/reports/inner_api_docs
python -X utf8 tools/build_qmt_inner_reference.py --source-dir runtime/reports/inner_api_docs --check
python -m pytest -q cfquant/tests/test_qmt_inner_reference.py
```

生成器仅提取原生函数标题与原型，不保存官方文章正文。网页区分“Python 调用示例”和“能力检查示例”；复杂重载或模型接口的具体调用参数需对照链接的原生文档。目录状态为“原生调用 · 依终端能力”，不把已登记等同于全部实测通过。

提交生成数据时同步更新 `index.html` 中相应脚本版本。静态目录从磁盘按请求读取，已有页面刷新即可获得新目录；这与更新 QMT 正在运行的桥接代码需要重启策略是两件事。

## 条件单、仓位计算与下单计划

扩展目录在 `web_dashboard/smart-order-api-data.js`，由接口页、文档页及 Python API 参考共同使用。它在 `cftrader-api-data.js` 之后加载，不改写原生 xtquant 接口目录。业务说明为 `docs/conditional_orders.md`，SDK 方法在 `cfquant/cftrader.py`，纯计算器在 `cfquant/position_sizing.py`。

修改参数时同时更新网页签名、参数帮助、Python 示例和等价 HTTP 请求。`calculate_position` 为静态方法，参数均为关键字；其余条件 / 计划方法通过共享 Web 服务执行。以下测试使用本地假账户、行情和委托，浏览器测试还检查手机布局与复制内容，不向 QMT 下单：

```powershell
python -m pytest -q cfquant/tests/test_smart_orders.py cfquant/tests/test_smart_orders_api.py
python -m pytest -q cfquant/tests/test_smart_orders_docs.py cfquant/tests/test_cftrader_tutorial.py
```
