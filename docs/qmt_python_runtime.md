# QMT Python 运行时管理接口

`cfquant.qmt_python_runtime.QmtPythonRuntime` 用独立类管理 QMT 自带的
Python 3.6/3.12 运行时。它读取 QMT 官方 `update36.cfg` 或
`updateQMT312.cfg`，支持 HTTP Range
断点续传、MD5 校验、压缩包安全解压、旧目录备份、账号运行时切换和 QMT
重启。下载阶段不会改动正在运行的 `bin.x64/python312`。

此管理接口应在外部 cfquant 服务或 Python 3.8+ 程序中调用。被管理的 QMT
仍可使用 Python 3.6；QMT 策略加载桥接模块时不会导入或导出这组管理类，
避免管理模块使用的新版 Python 语法和 `dataclasses` 阻断策略启动。

QMT 内的 Python 3.6 和 3.12 均可加载日志、桥接及消息通知模块。代理配置的
读取与脱敏不加载自动登录或 pywin32 依赖；只有外部服务实际保存、解密代理密码时，
才加载这些组件。外部 cfquant 服务的 Python 3.8+ 要求不变。

如果升级后，QMT 在 `_install_logging_compat` 阶段提示
`ModuleNotFoundError: No module named 'importlib.metadata'`，请更新包含兼容性修复的
cfquant，并将修复同步到报错堆栈指向的实际包目录（例如 `bin.x64/cfquant`）。
停止并重新启动桥接策略；若仍加载旧模块，请重启对应 QMT，使进程内的模块缓存失效。
仅更新外部 Python 环境中的安装包不会替换 QMT 目录内的副本；此次修复无需升级
QMT 的 Python 3.6，也无需在其中额外安装 `importlib-metadata`。

## 官网镜像和故障切换

运行库下载器会先访问 `https://cfquant.org` 的运行库镜像状态接口。接口使用
固定的 `X-CFQuant-Runtime-Key` 应用鉴权，并返回 Python 3.6/3.12 的版本、文件名、
大小、MD5、SHA-256 和当前下载连接数。官网同时下载达到 20 个连接时，客户端改用
讯投原始地址；讯投连接失败、返回错误状态或完整性校验失败时，会强制请求官网镜像。
强制请求只接受与当前运行库 MD5 相同的文件，避免官网切换版本期间把不同 ZIP 接在
同一个断点文件上。

官网接口为：

* `GET /api/qmt/python-runtime/status`：返回连接数和两个包的元数据；
* `GET /api/qmt/python-runtime/download?runtime=py36&md5=...`：支持 Range 断点续传；
  讯投失败后的强制回退追加 `force=1`。

接口有 5 秒窗口的 IP 访问限制；短时间内超过 10 次返回 `429`，持续的大量访问会
临时封禁 IP。单个 IP 同时最多 4 个运行库下载连接。每个流在完成、客户端断开或
校验失败时都会释放连接计数并写入官网运行日志。ZIP 包由官网单独保存，manifest
在两个文件完成 SHA-256 校验后才原子替换，下载过程不会暴露半成品。

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
首次绑定且启用了 cfquant 内置策略时，Web 服务会执行一次初始化引导：
先启动 QMT 并等待自动登录生成真实的 `Config.xml`/模型账号 Key，随后正常
关闭 QMT，应用运行时配置并完成策略部署，再第二次启动 QMT。未启用自动
填写登录时会保留首次启动窗口，用户完成登录后再次启动即可继续部署。

Web 服务提供三个受保护接口：

* `GET /api/qmt/python-runtime?qmt_dir=...&account_id=55009948&runtime=py312`
  查询本地安装、远端版本、MD5 和下载包状态。
* `POST /api/qmt/python-runtime/download` 启动后台流程。请求体至少包含
  `qmt_dir`（或唯一的 `account_id`），可选 `runtime`、`restart`、`job_id`。
  `reuse_installed=true` 时复用本地已安装的所选运行库，直接切换账号配置并重启；
  缺失时仍执行下载、校验、安装。默认 `false` 保留主动下载更新行为。
  新账号尚未生成 `Config.xml` 时可传 `allow_missing_account_config=true`。普通
  Python API 在没有 `restart_callback` 时仅下载并安装运行库并保持 QMT 停止；
  Web 绑定提供回调时会按上述初始化引导完成首次登录、账号切换和二次启动。
  Python API 的 `download_and_switch(..., reuse_installed=True)` 支持相同选项。
* `GET /api/qmt/python-runtime/jobs?job_id=...` 查询任务状态和进度。任务
  也会通过既有 `xtdata:download_progress` 回调事件发送阶段和字节进度。

任务查询以 `state=done` / `state=error` 为终态；成功时同时返回完整的 `result`
以及 `progress.phase=done`、`progress.percent=100`。`installed` 只表示安装步骤
完成，后续切换或重启可能仍在执行。`result.account_config_required=true` 表示
运行库已安装，但账号需要首次登录后才能应用执行器，不表示安装失败。
Web 初始化引导完成后会返回 `account_config_bootstrapped=true` 并将该字段改为
`false`。引导的 `result.restarted` 中还会记录 `bootstrap_completed`、首次
启动 PID、正常退出结果和最终运行时切换结果。
通知发送失败不会中断安装或改变任务结果，页面通过 HTTP 轮询补齐完成状态；
保存绑定前还会复查任务，避免页面错过完成通知后一直提示“正在配置”。
服务重启导致任务记录失效时，页面提示重新检测，不会仅凭文件存在宣告任务成功。
后台日志记录任务完成、失败及通知发送异常，均包含任务 ID 便于排查。

网页“接口 → 系统 → QMT Python 库下载”已经接入这条任务接口。提交后，
网页会通过 `/ws/callbacks` 实时显示下载百分比、已下载/总字节数、速度、
预计剩余时间和安装/重启阶段；WebSocket 断开时仍可用任务查询接口恢复状态。

编辑或新增绑定时，填写 QMT 目录会自动检测版本与两套本地运行库。支持
Python 3.12 的 QMT 显示 Python 3.6 / Python 3.12 下拉选择，默认使用账号的
当前配置；旧版或版本未知时只显示 Python 3.6。切换选项只改变待应用选择，
不会立即重启或修改 QMT。

所选运行库缺失时，点击“下载并使用”可沿用实时下载进度；已安装但未配置时，
点击“切换到 … 并重启 QMT”直接复用本地库。任务将所选执行器写入此账号的
`Config.xml`，停止、切换和重启完成后再保存绑定。新账号还没有生成
`Config.xml` 时，页面允许先下载并安装运行库，任务不会伪造账号配置；安装完成
后可保存绑定并启动 QMT，首次登录后再重新检测并应用执行器。未找到模型账号
Key 时会允许 QMT 先登录，策略部署保持等待；登录成功后正常退出 QMT，下一次
启动前继续读取真实绑定键并完成模型配置。其他部署错误仍会阻止自动启动。
不要仅选择新值便关闭弹窗；
有未应用选择或任务尚未完成时，页面会提示先完成配置。再次编辑时以 QMT
配置中的执行器为准。

检测失败只显示提示，不会阻止未更改执行器的绑定保存。更换账号或目录后会
立即清除旧检测结果，重新确认支持的版本；同一 QMT 不允许并发运行多个
Python 库任务。后台接口也会校验版本，不能通过直接请求给旧版 QMT 切换 3.12。

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
