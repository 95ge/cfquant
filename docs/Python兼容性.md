# Python 运行环境兼容性

外部 CFQuant Web 服务与 QMT 内置桥接策略使用各自的 Python，依赖要求不同。
外部服务支持 Python 3.8–3.12，生产部署优先选用 Python 3.12。
QMT 内置 Python 3.6、3.12 的桥接导入不需要安装 Frida 或自动登录依赖。

## 0.2.80 的兼容修复

- 外部 Python 3.8–3.10 使用 `typing_extensions>=4.4` 加载 Frida 的类型标注。
  Python 3.8 额外处理 `list[T]` 等泛型标注；无需修改 Frida 安装文件或 Python 标准库。
- 外部 Python 3.8、3.9 使用 `pandas-market-calendars==5.2.2`，避开 5.2.3、5.2.4
  在旧 Python 中求值 `Timestamp | None` 引起的导入错误；Python 3.8 同时安装
  `backports.zoneinfo>=0.2.1`。Python 3.10 及以上使用 `pandas-market-calendars>=5.2.2`。
- Python 3.8 的远程代理接口使用兼容的前缀处理方式，避免请求返回“本地操作失败”。

升级后请重启 CFQuant。通过 `start_cfquant.bat` 启动时，项目版本变化会触发安装更新后的
依赖；直接从源码运行的用户应先在实际运行 Web 的 Python 环境执行：

```powershell
python -m pip install -e .
```

需要确保此命令中的 Python 与 Web 显示的解释器路径一致。不要只覆盖 Python 源文件而
保留不兼容的日历依赖，也不要在 Python 3.8、3.9 中单独升级日历包绕过项目的版本约束。

旧 Python 所用日历包含本次验证需要的 2026 年上交所假日数据。日历数据随依赖包发布，
并非实时从交易所获取；请求年份超出已记录的上交所假日范围时，接口继续报错提示，
不会静默推测未来交易日。后续年份应随项目验证结果更新依赖或迁移到较新的外部 Python。

## 验证范围

本次使用 Windows x64 的 Python 3.8.10、3.9.0、3.10.0、3.11.0、3.12.4、3.13.9、3.14.2
检查 Frida 同步和异步模块、自动登录依赖检测、Web/PipeHub/Relay 模块导入、交易日历调用
和远程代理请求分支，并复查 QMT Python 3.6.8、3.12.10 的桥接冷导入。

3.13、3.14 属于额外兼容检查，不据此扩大完整业务的正式支持承诺。这些检查不等同于
在所有券商终端、Windows 版本和桌面会话下完成真实登录及交易验证。
