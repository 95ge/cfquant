# 第三方项目管理 SDK

第三方 Python 项目可以通过 `cfquant.management.RuntimeManager` 在后台运行 cfquant，完成初始化、账号绑定、更新和回滚，不必打开网页。行情与交易继续使用 `cfquant.xtdata` 和 `XtQuantTrader`。

## 最小接入

先在第三方项目的 Python 环境安装支持管理 SDK 的 cfquant。首次部署时关闭目标 QMT；下面的示例不会下单。

本次为同版本号源码更新，可下载官网最新 ZIP，解压后在第三方的 Python 环境中执行 `python -m pip install --force-reinstall --no-deps <解压目录>` 更新 SDK（依赖已安装时）。仅依据 PyPI 的 `0.2.45` 版本号无法确认是否包含本次管理接口，可通过 `from cfquant.management import RuntimeManager` 验证。

```python
from cfquant.management import RuntimeManager, ManagementError

runtime = RuntimeManager(home=r"D:\MyApp\cfquant", port=8765)

# 首次调用把服务代码复制到 home/service；后续调用复用现有文件。
# start() 也会自动执行这一步。
runtime.ensure_installed()

# 隐藏子进程启动，不打开浏览器。None 表示遵循各账号保存的设置。
runtime.start(auto_start_qmt=None)

result = runtime.initialize(
    account_id="YOUR_ACCOUNT_ID",
    account_type="STOCK",       # 信用账号使用 CREDIT
    qmt_dir=r"D:\QMT",
    mode="ctypes",              # ctypes 通用模式；lite 极致模式；lttx 高级模式
    auto_start_qmt=False,        # 调用者决定是否由 cfquant 自动启动 QMT
    deploy_strategy=True,
    strategy_autorun=True,      # 用户启动并登录 QMT 后自动运行桥接策略
    live=False,                 # 按实际账号选择模拟/实盘；True 为实盘
)

# auto_start_qmt=False 时，请用户自行启动并登录 QMT。
# 初始化返回包含 qmt_core_deploy、qmt_strategy_deploy 等部署结果；
# 初始化保存成功不等于桥接已经在线。
try:
    binding = runtime.wait_ready("YOUR_ACCOUNT_ID", timeout=120)
except ManagementError as error:
    print(error.code, str(error))
else:
    # 配置当前进程的 SDK 连接到此后台服务的 LTtx 路由。
    runtime.configure_client()
    from cfquant import xtdata
    print(xtdata.get_full_tick(["000001.SZ"]))
```

QMT 的安装、登录、必要的终端组件下载和权限仍需完成。`strategy_autorun` 控制桥接策略自运行，`auto_start_qmt` 控制 QMT 进程启动，两者独立。自动启动不表示自动处理验证码或登录密码。

## QMT 启动策略

| 调用 | 行为 |
|---|---|
| `runtime.start(auto_start_qmt=None)` | 遵循账号绑定里的自动启动设置，默认值 |
| `runtime.start(auto_start_qmt=False)` | 本次后台服务禁止自动启动和定时重启 QMT |
| `runtime.start(auto_start_qmt=True)` | 自动启动已启用绑定的主 QMT 目录 |
| `runtime.accounts.upsert(..., auto_start_qmt=True)` | 保存该账号自动启动设置，并在服务启动策略允许时尝试启动 |
| `runtime.restart(auto_start_qmt=None)` | 重启服务，恢复遵循各账号设置 |
| `runtime.restart()` | 保留本次服务的启动策略 |

服务启动时的统一策略优先于账号设置；不会修改账号保存的设置。若现有服务策略与 `start()` 请求不同，会返回 `policy_mismatch`，需显式调用 `restart()`。多个绑定使用同一 QMT 目录时，启动阶段会去重。高级模式的独立交易终端仍按既有部署规则配置。

命令行也支持：

```text
cfquant serve --no-auto-start-qmt
cfquant serve --auto-start-qmt
```

命令行占用当前进程；管理 SDK 使用隐藏子进程。两者默认均不打开浏览器。

## 账号配置

```python
accounts = runtime.accounts.list()  # 按 account_key 返回配置字典
status = runtime.accounts.status()  # bindings 列表，包含路由和部署状态

runtime.accounts.upsert(
    "SECOND_ACCOUNT", r"D:\QMT2",
    account_type="CREDIT", mode="lite", auto_start_qmt=True,
    live=False, strategy_autorun=True,
)

# 修改同一账号的配置；不同 bridge_id 的同账号绑定需明确 bridge_id。
runtime.accounts.upsert(
    "SECOND_ACCOUNT", r"D:\QMT2",
    account_type="CREDIT", mode="lite", auto_start_qmt=False,
    live=False, strategy_autorun=True,
)

# 删除绑定不会关闭用户的 QMT 进程。
# runtime.accounts.delete("SECOND_ACCOUNT", account_type="CREDIT")
```

相同配置重复调用返回 `unchanged=True`，不会重复部署。可用 `force=True` 显式重新部署。`qmt_strategy`、`qmt_auto_login`、`bridge_id`、`qmt_trade_dir`、`market_bridges` 等附加参数沿用现有账号配置接口；SDK 的明确布尔参数优先于嵌套配置中的对应值。

需要修改部署文件时，正在运行的 QMT 会导致 `ManagementError(code="qmt_running", status=409)`。调用者可以提示用户先关闭 QMT 再重试，也可显式传入 `auto_close_qmt=True`，授权关闭目标 QMT 后部署。默认不会自动关闭。

## 查询版本与按需自动更新

```python
# 默认同时查询远端；force=True 绕过远端元数据缓存，不探测或启动 QMT。
versions = runtime.version_info(force=True)
print(versions["running_version"])       # 后台进程实际加载的核心版本
print(versions["installed_version"])     # 磁盘上已安装的核心版本
print(versions["latest_version"])        # 远端核心版本，查询不到时为 None
print(versions["web_version"])           # 后台进程加载的 Web 版本
print(versions["latest_web_version"])    # 远端 Web 版本
print(versions["restart_required"])      # 更新后尚未重启，包括同版本号补丁

local = runtime.version_info(include_remote=False)  # 完全不查询远端
check = runtime.updates.check(force=True)           # 只检查，不执行更新
print(check["available"], check["reason"], check["latest_version"])

# 一次调用完成重新检查、必要时安装和重启。默认不会关闭 QMT。
result = runtime.updates.ensure_latest(auto_close_qmt=False)
print(result["status"], result["message"])
```

| `status` | 含义 |
|---|---|
| `up_to_date` | 已是最新版本；无需下载安装，不触碰 QMT；已有待生效更新时可能只执行服务重启 |
| `updated` | 已安装更新；默认等待后台服务重启完成 |
| `local_newer` | 本地版本更高，跳过自动更新，不自动降级 |
| `check_failed` | 网络或版本信息不足，无法判断；不执行更新，也不会当成已是最新 |
| `restart_required` | 最新文件已安装但未生效；指定 `restart=False` 时由调用方重启 |
| `update_incomplete` | 服务文件已更新，但部分 QMT 部署未完成，需查看 `update` 详情 |

返回还包含 `updated`、`current_version`（已安装版本）、`running_version`（进程版本）、`latest_version`、`restart_required`、`check`（检查详情）、`update`（实际安装详情，无安装时为 None）；SDK 执行重启后附带 `service`。`updated=False` 只表示此次没有安装文件，不能单独据此判断检查成功。查询失败查看 `check.remote.error`。已有更新正在执行、QMT 未关闭、下载或安装失败等执行错误仍抛出 `ManagementError`。

`ensure_latest()` 使用默认官方发布渠道，每次重新拉取远端版本信息，复用官网不可用时的 GitHub 回退规则。无需更新时，即使传了 `auto_close_qmt=True` 也不会关闭 QMT。需要更新时可显式使用 `auto_close_qmt=True` 授权关闭目标 QMT；`restart=False` 只更新文件。重复调用会比较保存的安装包哈希，避免反复下载同一份版本；首次从 wheel/源码复制的服务尚无发布包哈希，会先安装一次已公布的对应包。调用方如需定时检查，可自行定时调用此方法，SDK 不会创建额外的自动更新定时任务。

`runtime.status()` 也包含版本字段：`core_version` / `installed_core_version` 为磁盘版本，`running_core_version` 为实际运行版本，`web_version` 为运行中的 Web 版本。第三方进程自身导入的 SDK 版本仍可通过 `cfquant.version.__version__` 查询，它可能与独立后台服务不同。

## 指定更新与回滚

```python
update = runtime.updates.check()
if update["available"]:
    # 默认要求用户已关闭相关 QMT；更新后自动重启后台服务并等待新实例就绪。
    result = runtime.updates.apply(source="official", auto_close_qmt=False)
    print(result["current_version"], result["backup"])
    print(result.get("update_completed"), result.get("qmt_restart_required"))

# 指定 GitHub 分支、标签或提交：
# result = runtime.updates.apply(source="github", ref="main")

# 指定备份名称回滚：
# result = runtime.updates.rollback("BACKUP_NAME")
```

更新覆盖独立服务目录，复用现有官网 ZIP 下载与哈希校验、备份、QMT 核心同步和回滚逻辑。默认使用官网，官网失败时沿用现有 GitHub 回退策略。`restart=False` 只完成文件更新，随后可显式调用 `runtime.restart()`。如果部分 QMT 部署失败，结果中的 `update_completed` 为假，调用者应检查详情。

`check()` 同时比较官网包的 SHA256，能检测不增加版本号的修复。首次从已安装包复制服务时尚无官网包哈希，`sha256_known=False`；有官网包哈希时会保守提示可更新，成功安装后保存哈希。回滚后哈希回到未知状态，会保守提示可更新。远程检查失败时 `available=None`，应检查返回的 `remote.error`。

管理模式拒绝安装或回滚到不含管理接口的旧版本，避免更新后丢失管理能力。因此首次发布此功能之前的官网包不能用于管理模式升级。

更新不会替换第三方进程中已经导入的 `cfquant`，不会执行 pip，也不会改变第三方项目的依赖锁定。若需要升级第三方自身使用的 SDK，请由第三方的依赖管理流程执行，并重启第三方进程。服务默认复用调用者的 Python 解释器及已安装依赖，也可指定 `python_executable` 使用专用虚拟环境；新版本增加依赖时需先在该解释器中安装依赖。

## 生命周期、鉴权和目录

```python
runtime.status()             # 服务状态，含版本、boot_id、账号配置
runtime.start()              # 同目录、同端口、同启动策略时复用现有实例
runtime.restart()            # 等待 boot_id 改变且新服务就绪
runtime.stop()               # 停止 HTTP/账号路由服务，不关闭 QMT

# 接入由其他进程管理的服务，需支持本 SDK 的管理接口：
remote = RuntimeManager(base_url="http://127.0.0.1:8765", api_key="YOUR_API_KEY")
remote.status()
```

本地托管默认监听 `127.0.0.1`，首次创建 `home/management.key`，通过请求头完成管理鉴权；不要提交或输出此文件。配置与状态位于 `home/runtime`，日志统一位于 `home/log` 的组件子目录，启动故障查看 `home/log/startup/management-service.log`，重启日志查看 `home/log/startup/cfquant_web_reload.log`。

`stop()` 保留可被复用的 LTtx/PipeHub，不终止用户 QMT。独立部署多个服务时，需要分别指定 `port`、`lttx_port`、`pipe_name`，并为各服务绑定不同的 QMT 实例；仅改变 HTTP 端口不会隔离交易路由。

```python
runtime = RuntimeManager(
    home=r"D:\MyApp\cfquant",
    port=8877,
    lttx_port=2149,
    pipe_name=r"\\.\pipe\myapp_cfquant",
    python_executable=r"D:\MyApp\.venv\Scripts\python.exe",
)
```

`ManagementError` 提供 `code`、`status`、`details`，常用错误码为 `authentication_failed`、`instance_mismatch`、`policy_mismatch`、`service_exited`、`service_timeout`、`qmt_running`、`qmt_not_ready`、`project_update_busy`。更新进行中会拒绝停止或重启请求。更新请求超时后应查询 `updates.check()["status"]["operation"]` 确认服务端进度，不应立即重复提交更新。

## 其他语言调用 HTTP 接口

可选官网接入使用 `runtime.remote.configure(api_key=..., permissions=...)` 和 `runtime.remote.status()`。用户需先在官网创建部署和项目 API Key，本地不接受官网账号密码，也不创建项目。接入与三类操作权限默认关闭，多套部署分别配置。完整示例和权限说明见 [官网远程管理使用说明](官网远程管理使用说明.md)。

服务启动后，非 Python 项目也可调用以下接口。请求体使用 UTF-8 JSON；响应格式为 `{"ok": true, "data": ...}`，错误包含 `error`，部分错误附带 `code`。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/management/status` | 版本、启动标识、初始化状态、账号配置 |
| GET | `/api/version?remote=1&force_remote=1` | 运行、已安装与远端版本；`remote=0` 只查本地 |
| POST | `/api/setup/initialize` | 首次初始化，参数沿用账号配置接口 |
| POST | `/api/account-config` | 保存账号、QMT 路径、模式和策略配置 |
| POST | `/api/account-config/delete` | 删除指定账号绑定 |
| GET | `/api/bindings/status` | 账号桥接就绪状态 |
| GET | `/api/project-updates/status?remote=1&force=1` | 更新状态、远程版本、备份列表；`force=1` 绕过远端缓存 |
| POST | `/api/project-updates/ensure-latest` | 检查后按需更新，返回上述 `status`；支持布尔参数 `auto_close_qmt`、`reload` |
| POST | `/api/project-updates/official` | 官网更新，支持 `auto_close_qmt`、`reload` |
| POST | `/api/project-updates/github` | GitHub 更新，另支持 `ref`、`repo_url` |
| POST | `/api/project-updates/rollback` | 回滚，指定 `backup` 名称 |
| POST | `/api/management/restart` | 重启，支持 `auto_start_qmt` 布尔值或 null |
| POST | `/api/management/stop` | 停止后台服务 |

托管实例使用 `X-CFQuant-Management-Key` 请求头，值取自该实例的 `home/management.key`；已有服务也可使用配置的 `X-API-Key`。管理接口始终要求凭据。账号配置的自动启动字段为 `"qmt_auto_login": {"enabled": false}`，服务级启动策略具有优先权。HTTP 更新接口默认触发重启，需自行通过 `boot_id` 变化确认新实例就绪；Python SDK 已封装此等待过程。

按需更新 HTTP 接口也始终要求凭据。它在确有安装或待生效更新时才触发重启，返回 JSON 后执行重启；此时响应中的 `restart_required` 仍为 true，`reload` 包含重启安排。Python 的 `ensure_latest()` 会等待新实例就绪后再将 `restart_required` 置为 false。
