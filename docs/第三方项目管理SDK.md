# 第三方项目管理 SDK

第三方 Python 项目可以通过 `cfquant.management.RuntimeManager` 在后台运行 cfquant，完成初始化、账号绑定、更新和回滚，不必打开网页。行情与交易继续使用 `cfquant.xtdata` 和 `XtQuantTrader`。

## 最小接入

先在第三方项目的 Python 环境安装支持管理 SDK 的 cfquant。首次部署时关闭目标 QMT；下面的示例不会下单。

调用方 SDK 和后台服务都需要包含所用接口。升级后台不会替换第三方进程已经导入的 SDK；升级 SDK 后需重启调用方进程，升级后台后需重启后台服务。

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

## 外部程序恢复 QMT 托管策略

与 `runtime.initialize()`、`runtime.accounts.upsert()` 绑定账号一样，直接在同一个管理对象上调用 `runtime.recover_strategy()`，对一个绑定执行一次即时检测和恢复。`runtime.accounts.recover_strategy()` 保留为等价入口。本地托管实例自动使用原有管理凭据，程序无需自行构造 HTTP 请求或填写 API Key。

复用绑定时的 `runtime` 对象即可；重新创建对象时，`home` 和端口必须与绑定时一致：

```python
from cfquant.management import RuntimeManager

runtime = RuntimeManager(home=r"D:\MyApp\cfquant", port=8765)
# 复用与绑定相同的后台服务；绑定已经存在时无需再次 initialize/upsert。
runtime.start(auto_start_qmt=None)
result = runtime.recover_strategy(
    "YOUR_ACCOUNT_ID", account_type="STOCK", timeout=180,
)
print(result["state"], result["running"], result["start_requested"])

# 对同账号的多个绑定，指定 bridge_id，或直接使用完整 account_key：
# result = runtime.recover_strategy(account_key="YOUR_ACCOUNT_KEY")

# 已提交启动不等于已经恢复通信；需要通信就绪时，再等待桥接确认。
if result["state"] in ("start_requested", "running"):
    runtime.wait_ready(result["account_id"], account_type=result["account_type"],
                       bridge_id=result["bridge_id"], timeout=60)
else:
    for target in result["targets"]:
        print(target["recovery"])
```

方法由 SDK 调用后台服务，QMT 桥接策略停止、命名管道未连接时也能请求；后台服务仍需运行。接入已有的独立服务时，沿用绑定时使用的 `RuntimeManager(base_url=..., api_key=...)` 对象，同样调用 `runtime.recover_strategy(...)`。QMT 需已启动并登录，绑定需启用“自动导入策略”和“策略自动运行”，且已完成部署。服务启动策略禁止 QMT 自动化时，此方法也遵循该设置。

升级已有部署时，调用程序和后台服务都需要加载包含此接口的新代码；更新文件后重启相应进程，避免调用方已有新方法而旧后台仍未加载恢复路由。

方法参数：`account_id=None`、`account_type=None`、`bridge_id=None`、`account_key=None`、`timeout=180`。必须提供资金账号或完整绑定 Key；多个账号类型或多个桥接使用同一账号时，需补充限定字段使结果唯一。传入的标识必须相互匹配，未知 Key 不会回退到默认账号。`timeout` 是客户端 HTTP 等待秒数，不会修改服务端恢复规则。

结果中 `running=true` 表示当前绑定全部目标模型已确认运行；`bridge_confirmed=true` 还要求同进程、同部署代次的近期通信确认。`start_requested=true` 仅表示本次提交过启动。每个 `targets` 项包含 `root`、`generation` 和详细的 `recovery` 状态。顶层 `state` 为各目标共同状态；不同目标状态不一致时为 `partial`，应逐项检查。

| `state` | 含义 |
|---|---|
| `running` | 模型已运行，不重复启动；通信是否正常另看 `bridge_confirmed` |
| `start_requested` | 已提交启动，等待后续检测及桥接回连 |
| `ineligible` | 不满足恢复条件，具体原因在 `reason`、`message`；例如 `deployment_pending`、`automation_disabled` |
| `waiting_whitelist` | QMT 白名单尚未就绪，等待后续检测 |
| `backoff` / `retry_exhausted` | 正在冷却或已达到重试上限，接口不会重置重试计数 |
| `detection_only` / `unsupported` | 当前终端缺少启动接口或核心查询接口 |
| `binding_changed` / `unavailable` | 绑定变化或本次原生操作不可用，查看详细状态与错误 |
| `cancelled` | 服务正在停止，此目标未执行恢复 |

调用与后台检测共用执行锁和恢复状态。后台正忙或另一请求正在执行时，HTTP 返回 `409`、`code="strategy_recovery_busy"`，SDK 抛出 `ManagementError`；调用者可稍后查询状态或重试。即时检测会跳过常规轮询等待，但保留失败冷却、重试上限、绑定核对和 QMT 自身的白名单校验。旧 QMT 缺少独立白名单就绪查询时，仍可使用其原生策略启动接口；支持该查询且明确返回未就绪时等待。请求超时不代表服务端尚未执行，应先用 `runtime.accounts.status()`（HTTP `GET /api/bindings/status`）查看对应绑定的 `qmt_strategy_deploy.targets[].recovery`，避免循环重发。

账号存在当前启用的部署任务时，恢复结果仅汇总这些任务，历史已停用的目录或模式不会让成功恢复显示为 `partial`。当前部署全部停用时，返回 `ineligible` 及停用原因。

此接口恢复当前绑定的托管策略，不重启 QMT、不重新导入策略、不强制重启已运行模型。有关兼容性和部署条件，见 [QMT 策略自动恢复](QMT策略自动恢复.md)。

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
| GET | `/api/account-config/proxy?account_key=...` | 读取指定绑定的脱敏代理配置 |
| POST | `/api/account-config/proxy` | 更新绑定代理、白名单和 UDP 策略；`restart=true` 时重启 QMT |
| POST | `/api/account-config/delete` | 删除指定账号绑定 |
| GET | `/api/bindings/status` | 账号桥接就绪状态 |
| POST | `/api/qmt/strategies/recover` | 指定账号绑定，即时检测并尝试恢复已停止的托管策略 |
| GET | `/api/project-updates/status?remote=1&force=1` | 更新状态、远程版本、备份列表；`force=1` 绕过远端缓存 |
| POST | `/api/project-updates/ensure-latest` | 检查后按需更新，返回上述 `status`；支持布尔参数 `auto_close_qmt`、`reload` |
| POST | `/api/project-updates/official` | 官网更新，支持 `auto_close_qmt`、`reload` |
| POST | `/api/project-updates/github` | GitHub 更新，另支持 `ref`、`repo_url` |
| POST | `/api/project-updates/rollback` | 回滚，指定 `backup` 名称 |
| POST | `/api/management/restart` | 重启，支持 `auto_start_qmt` 布尔值或 null |
| POST | `/api/management/stop` | 停止后台服务 |

代理配置可以随账号绑定一起提交 `qmt_proxy`，也可以单独更新：

```json
{
  "account_key": "bridge:STOCK:1000000001",
  "qmt_proxy": {
    "enabled": true,
    "type": "socks5",
    "host": "127.0.0.1",
    "port": 1080,
    "username": "proxy-user",
    "password": "请求中提交，服务端使用 Windows DPAPI 加密保存",
    "bypass": ["127.0.0.1", "localhost", "::1", "10.0.0.0/8"],
    "udp_policy": "direct"
  },
  "restart": true
}
```

响应只返回 `password_saved`，不会返回代理密码。`udp_policy=proxy` 只允许 SOCKS5 或 SSH；HTTP/HTTPS 代理只能让 UDP 直连。启动 QMT 时服务会注入 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和 `NO_PROXY`；具体 QMT 版本是否读取这些变量需要在目标客户端上抓包确认。

托管实例使用 `X-CFQuant-Management-Key` 请求头，值取自该实例的 `home/management.key`；已有服务也可使用配置的 `X-API-Key`。管理接口始终要求凭据。账号配置的自动启动字段为 `"qmt_auto_login": {"enabled": false}`，服务级启动策略具有优先权。HTTP 更新接口默认触发重启，需自行通过 `boot_id` 变化确认新实例就绪；Python SDK 已封装此等待过程。

策略恢复请求示例（该接口始终要求凭据）：

```http
POST /api/qmt/strategies/recover HTTP/1.1
Host: 127.0.0.1:8765
X-API-Key: YOUR_API_KEY
Content-Type: application/json

{"account_id":"YOUR_ACCOUNT_ID","account_type":"STOCK"}
```

HTTP `200` 和 `ok=true` 表示本次检查已执行，恢复是否完成需读取 `data.state`、`data.running`、`data.bridge_confirmed`。参数缺失、绑定不存在或定位不唯一返回 `400`；未鉴权返回 `401`；恢复执行忙或项目正在更新返回 `409`。

按需更新 HTTP 接口也始终要求凭据。它在确有安装或待生效更新时才触发重启，返回 JSON 后执行重启；此时响应中的 `restart_required` 仍为 true，`reload` 包含重启安排。Python 的 `ensure_latest()` 会等待新实例就绪后再将 `restart_required` 置为 false。
