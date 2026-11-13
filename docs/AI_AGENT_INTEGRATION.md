# CFQuant AI Agent 接入指南

本指南面向能执行 HTTP 请求或 Python 代码的 agent。CFQuant 的 agent 接入重点有两类：帮助用户把已有 MiniQMT 策略切换到大 QMT，以及在桥接完成后读取状态、配置账户和调用兼容 API。推荐先把 agent 限定为“读取与迁移建议”，用户确认后再开放配置、交易和生命周期权限。

## MiniQMT 策略迁移任务

agent 处理迁移时应保持策略业务代码不变，优先检查：

1. 策略是否使用 `xtdata`、`XtQuantTrader`、`StockAccount` 和 `xtconstant` 等兼容入口。
2. 目标 Python 环境是否安装 `cfquant`，并确认 `python -c "import cfquant; print(cfquant.__version__)"` 的解释器就是运行策略的解释器。
3. Web 控制台是否已经绑定大 QMT 目录、账户类型和资金账号；当前运行方式固定为极致模式。
4. 是否需要把 `from xtquant ...` 改为 `from cfquant ...`；函数名、参数顺序、回调注册方式通常保持不变。
5. 先用行情、资金和持仓只读调用验证路由，再请求用户确认真实交易。

不要把原 MiniQMT 的 `userdata_mini` 目录直接填成大 QMT 目录，也不要为了“兼容”自动改写策略的交易数量、价格或买卖方向。

## 最小接入流程

```text
health -> config -> server-access/auth -> data probe -> user confirmation -> action -> status verification
```

1. `GET /api/health` 确认服务在线。
2. `GET /api/config` 获取 `bridge_id`、账户键、传输层、大 QMT 桥接状态和绑定信息；不要向用户展示响应中的密钥。
3. 使用 `X-API-Key` 或 Web Token 建立认证。密钥从环境变量或操作系统密钥存储读取，禁止写入仓库。
4. 先执行只读行情、资金或持仓查询，确认账户路由正确。
5. 对下单、撤单、启动/停止、更新、重置等副作用操作，向用户展示即将执行的账户、标的、数量、价格和影响，并等待明确确认。
6. 调用后轮询查询接口，报告真实状态；不要仅依据 HTTP 200 判断成交或启动成功。

## 推荐 agent 工具

```python
import os, requests

BASE = os.getenv("CFQUANT_BASE_URL", "http://127.0.0.1:8765")
HEADERS = {"X-API-Key": os.environ["CFQUANT_API_KEY"]}

def cfquant_get(path, **params):
    response = requests.get(BASE + path, headers=HEADERS, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

def cfquant_post(path, body):
    response = requests.post(BASE + path, headers=HEADERS, json=body, timeout=20)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "CFQuant request failed"))
    return result.get("data")
```

## 权限分级

- `read`: health、config、version、行情、资金、持仓、日志状态。
- `configure`: 账户绑定、Python 环境、传输层、通知和监控设置。
- `trade`: 委托、撤单、条件单、算法单和订单计划。
- `lifecycle`: 启停 QMT、重启 Web、更新、回滚和策略恢复。

默认只授予 `read`。将 `trade` 与 `lifecycle` 作为每次任务的临时权限；执行前必须回显关键参数，执行后必须验证状态。

## 安全边界

- 不读取、猜测或输出账户密码、API Key、Web Token 和内部密钥。
- 不把远程管理接口暴露到公网；优先 loopback、VPN 或防火墙白名单。
- 不在没有用户确认时发送真实订单，即使用户消息只说“测试一下”。模拟盘也要明确账户类型。
- 遇到 `401/409` 时先报告原因并读取状态，不通过重复请求绕过保护。
- 配置变更前保存 `/api/config`；失败时只恢复本次变更涉及的字段。

## 任务模板

agent 应在每次任务中记录：目标账户、账户类型、bridge_id、数据时间、请求路径、脱敏后的参数、返回 code，以及最终状态。完整接口清单见 [API_REFERENCE.md](API_REFERENCE.md)。

