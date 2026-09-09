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
