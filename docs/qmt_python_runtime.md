# QMT Python 运行时管理接口

`cfquant.qmt_python_runtime.QmtPythonRuntime` 用独立类管理 QMT 自带的
Python 3.6/3.12 运行时。它读取 QMT 官方 `update36.cfg` 或
`updateQMT312.cfg`，支持 HTTP Range
断点续传、MD5 校验、压缩包安全解压、旧目录备份、账号运行时切换和 QMT
重启。下载阶段不会改动正在运行的 `bin.x64/python312`。

此管理接口应在外部 cfquant 服务或 Python 3.8+ 程序中调用。被管理的 QMT
仍可使用 Python 3.6；QMT 策略加载桥接模块时不会导入或导出这组管理类，
避免管理模块使用的新版 Python 语法和 `dataclasses` 阻断策略启动。

```python
from cfquant import QmtPythonRuntime

qmt = QmtPythonRuntime(
    r"D:\国金QMT交易端模拟",
    account_id="55009948",
)

print(qmt.inspect("py312"))
result = qmt.download_and_switch(
    "py312",
    restart=True,
    progress_callback=lambda event: print(event),
)
```

`download_and_switch` 的顺序是：读取远端配置 → 下载并校验 → 停止同一
QMT → 原子替换 `bin.x64/python312`（旧目录留在备份目录）→ 修改账号
`Config.xml` 的 `libs_path` 和 `m_nPythonVersion` → 启动 QMT。账号已有
cfquant 自动登录配置时，Web 服务会优先使用自动登录/策略恢复回调。

Web 服务提供三个受保护接口：

* `GET /api/qmt/python-runtime?qmt_dir=...&account_id=55009948&runtime=py312`
  查询本地安装、远端版本、MD5 和下载包状态。
* `POST /api/qmt/python-runtime/download` 启动后台流程。请求体至少包含
  `qmt_dir`（或唯一的 `account_id`），可选 `runtime`、`restart`、`job_id`。
* `GET /api/qmt/python-runtime/jobs?job_id=...` 查询任务状态和进度。任务
  也会通过既有 `xtdata:download_progress` 回调事件发送阶段和字节进度。

网页“接口 → 系统 → QMT Python 库下载”已经接入这条任务接口。提交后，
网页会通过 `/ws/callbacks` 实时显示下载百分比、已下载/总字节数、速度、
预计剩余时间和安装/重启阶段；WebSocket 断开时仍可用任务查询接口恢复状态。

编辑或新增绑定时，填写账号和 QMT 目录会自动执行本地检测；如果运行库缺失，
绑定弹窗会显示下载按钮和同样的实时进度。检测失败只显示提示，不会阻止保存绑定。

保存 QMT 绑定时，`/api/account-config` 的响应会额外返回
`qmt_python_runtime`。该字段根据账号 `Config.xml` 识别当前选择的运行时，
并检查 `python36.dll`/`Lib` 或 `python.exe`/`python312.dll`/`Lib` 是否存在。
`state=ready` 表示已下载且可用，`state=python_library_missing` 表示应先下载；
检查只读本地文件，不会因为下载服务器暂时不可用而阻止绑定。

绑定检测会读取账号 `Config.xml` 中的版本，并优先读取 `XtItClient.exe` 的文件版本。
低于 `2.1.33.0` 的 QMT（以及版本无法识别的客户端）固定使用默认 py36，
接口只返回 `available_runtimes=["py36"]`，不会误提示或切换 py312。当前配置
如果误指向 py312，检测结果仍以实际可用的 py36 为准，同时保留
`configured_runtime` 供页面提示。

py36 仍可通过 `inspect` 和 `download` 查询/下载。它的安装目录是 QMT 的
`bin.x64` 根目录；安装流程会逐个备份将被替换的 Python 文件，再合并解压包，
并写入 QMT 使用的 `config/pythonlibDownloadInfo.txt`，不会替换 QMT 客户端自身
文件。`download_and_switch("py312")` 在旧版 QMT 上会明确拒绝并提示使用 py36。
