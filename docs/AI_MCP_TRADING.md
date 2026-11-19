# AI 通过 MCP 查询与交易

## 适用场景与接入方式

当你希望在支持 MCP 的 AI 客户端里用自然语言查询行情、资金、持仓，并在确认后下单，选择这条路径。AI 通过工具调用操作已绑定的大 QMT，不需要改写已有策略。

```text
用户指令 → AI 客户端 → MCP 适配服务 → CFQuant HTTP API（默认 8765）
         → 已绑定的大 QMT → 查询结果、委托状态、成交结果
```

**当前 CFQuant 没有内置 MCP 服务端，也没有默认的 `/mcp` 地址。** 8765 是 Web 控制台和 HTTP API 服务；将 `http://127.0.0.1:8765` 直接填成 MCP 地址无法连接。下面提供一个需要自行保存、配置和运行的适配示例，使用 stdio 与 AI 客户端通信，再访问 CFQuant HTTP API。

如果已有自己的 MCP 服务，也可以按下面的接口和流程封装工具。只想让 AI 修改策略代码，请阅读 [AI 策略迁移指南](AI_STRATEGY_MIGRATION.md)。

## 第一步：准备 CFQuant 和账号

1. 启动 CFQuant，打开本地控制台，完成资金账号、账号类型和大 QMT 目录绑定。
2. 确认 QMT 已登录、桥接在线，先在网页里查询行情、资金和持仓。
3. 从对应绑定记录确认 `account_id`、`account_type` 和 `bridge_id`，不要用其他券商或同名账号的路由。
4. 进入“系统设置 → API Key”，先配置管理员 Key 或启用网页登录，再为每个 MCP 客户端创建独立 Key。默认选择“查询”，勾选该客户端可访问的具体绑定账号；需要下单撤单时再增加“交易”。不要将管理员 Key 交给 AI。
5. 下列适配示例仅支持普通股票账户 `STOCK` 的限价买入；信用、期货和期权需要单独设计业务参数，不能照搬普通买入工具。

单 QMT 默认极致模式即可。高级模式使用两个 QMT：普通端负责行情与回调，交易端负责委托、撤单和账户查询；通信可选 ctypes 或 socket，默认 ctypes。MCP 工具仍调用统一 HTTP API，不手工选择底层通信通道。

## 第二步：建立独立的 MCP Python 环境

MCP 适配进程运行在外部 Python 中，不安装到 QMT 内部 Python。下面使用 Python 3.11 和官方 MCP Python SDK 的 v1 接口，固定 `<2`，避免混用 v2 的类名和启动方法。

```powershell
py -3.11 -m venv D:\cfquant-mcp\.venv
D:\cfquant-mcp\.venv\Scripts\python.exe -m pip install "mcp>=1.28,<2" requests
```

接口依据：[官方 MCP Python SDK v1 文档](https://py.sdk.modelcontextprotocol.io/v1/)。示例依赖由这个独立环境安装，不改变 CFQuant 或 QMT 的现有环境。

## 第三步：保存 MCP 适配示例

将下面完整代码保存为 `D:\cfquant-mcp\cfquant_mcp.py`。默认注册三个只读工具；只有启动环境明确设置 `CFQUANT_MCP_ENABLE_TRADING=1` 时才注册买入工具。本地开关只控制工具是否可见，服务端仍按 Key 的 `query`、`trade` 和账号范围校验；即使修改适配脚本也不能扩大 Key 的服务端权限。

```python
import math
import os
import re

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("CFQuant")
BASE = os.getenv("CFQUANT_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
API_KEY = os.environ["CFQUANT_API_KEY"]
ACCOUNT = {
    "account_id": os.environ["CFQUANT_ACCOUNT_ID"],
    "account_type": "STOCK",
    "bridge_id": os.environ["CFQUANT_BRIDGE_ID"],
}


def request(method, path, payload=None):
    # No automatic retries: a timeout after submission may hide a real order.
    response = requests.request(
        method, BASE + path,
        headers={"X-API-Key": API_KEY},
        params=payload if method == "GET" else None,
        json=payload if method == "POST" else None,
        timeout=(3, 30),
    )
    response.raise_for_status()
    result = response.json()
    if result.get("ok") is not True:
        raise RuntimeError("CFQuant rejected the request")
    return result.get("data")


@mcp.tool()
def cfquant_health() -> dict:
    """Read service health. This does not prove QMT or the broker is ready."""
    return request("GET", "/api/health")


@mcp.tool()
def cfquant_quote(stock_code: str) -> dict:
    """Read a quote, e.g. 000001.SZ. Report its timestamp and freshness."""
    return request("POST", "/api/data/full-tick", {
        **ACCOUNT, "code_list": [stock_code.upper()],
    })


@mcp.tool()
def cfquant_account() -> dict:
    """Read this configured account's assets, positions, orders and trades."""
    return request("GET", "/api/account", {
        **ACCOUNT, "sections": "asset,positions,orders,trades", "force": "1",
    })


if os.getenv("CFQUANT_MCP_ENABLE_TRADING", "0") == "1":
    @mcp.tool()
    def cfquant_buy_stock(stock_code: str, volume: int, price: float,
                          confirm_text: str, order_remark: str) -> dict:
        """Submit ONE real STOCK limit buy only after explicit user approval.

        Show account, bridge, symbol, volume, price and remark before approval.
        A timeout must be reconciled using cfquant_account, never auto-retried.
        """
        code = stock_code.upper()
        if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
            raise ValueError("Expected a stock code such as 000001.SZ")
        if type(volume) is not int or volume <= 0:
            raise ValueError("volume must be a positive integer")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be finite and positive")
        if not order_remark.strip():
            raise ValueError("A unique order_remark is required")
        expected = f"BUY {code} {volume} @ {price:.3f}"
        if confirm_text != expected:
            raise ValueError(f"Expected confirmation: {expected}")
        return request("POST", "/api/order", {
            **ACCOUNT, "stock_code": code, "side": "buy", "volume": volume,
            "price": price, "confirm_text": confirm_text,
            "order_remark": order_remark,
        })


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

`confirm_text` 是 HTTP 订单参数校验，AI 也能生成同样的字符串，**它不能代替用户批准**。在 AI 客户端里为交易工具开启每次调用人工确认；不要仅依赖工具描述或提示词限制真实交易。示例没有卖出、撤单、批量下单和服务启停工具，需要这些能力时按实际业务单独扩展。

## 第四步：在 AI 客户端添加 MCP 服务

使用客户端的本地 stdio MCP 配置，命令为独立环境的 Python，参数为脚本绝对路径。下面是常见 `mcpServers` 格式；不同客户端的配置入口和外层字段可能不同，以所用客户端要求为准。

```json
{
  "mcpServers": {
    "cfquant": {
      "command": "D:\\cfquant-mcp\\.venv\\Scripts\\python.exe",
      "args": ["D:\\cfquant-mcp\\cfquant_mcp.py"],
      "env": {
        "CFQUANT_BASE_URL": "http://127.0.0.1:8765",
        "CFQUANT_ACCOUNT_ID": "YOUR_ACCOUNT_ID",
        "CFQUANT_BRIDGE_ID": "YOUR_BRIDGE_ID",
        "CFQUANT_MCP_ENABLE_TRADING": "0"
      }
    }
  }
}
```

`YOUR_ACCOUNT_ID` 和 `YOUR_BRIDGE_ID` 必须换成该绑定记录的真实值。示例故意不放 API Key：通过客户端的本地密钥配置或启动进程环境提供 `CFQUANT_API_KEY`，并确认 MCP 子进程能继承该变量。没有传入时会在启动时报缺少环境变量，而不是悄悄使用其他账号。

本地 stdio MCP 服务无需单独填写 HTTP MCP URL。连接后应看到 `cfquant_health`、`cfquant_quote`、`cfquant_account` 三个工具。缺少工具时先看 MCP 客户端的启动日志；不要把业务调试内容 `print()` 到 stdio 标准输出，以免破坏协议通信。

## 示例一：先让 AI 做只读检查

把下面这段指令交给 AI：

```text
使用 CFQuant MCP，只执行查询，不执行交易或配置修改。
1. 调用 cfquant_health 检查服务。
2. 调用 cfquant_account，列出资金、持仓和当前委托。
3. 调用 cfquant_quote 查询 000001.SZ，说明行情时间和是否陈旧。
4. 报告实际账户、bridge_id、查询时间；账号展示时脱敏。
5. 如果任一工具失败，停止并说明原因，不改账号、不猜价格。
```

`health` 成功只代表 Web 服务在线；只有账户和行情查询都成功，才能说明相关桥接链路可用。还要检查返回的缓存、时间和错误信息，不能仅凭 HTTP 200 判断就绪。

## 示例二：确认后提交一笔限价委托

先在 Key 管理中授予目标账号的查询和交易权限，再由用户在本地将 `CFQUANT_MCP_ENABLE_TRADING` 改成 `1`，重启 MCP 子进程，并开启交易工具的人工审批。下面参数仅用于说明字段，不是交易建议，也不会因为阅读本页自动执行。

```text
请先查询我的指定账户和 000001.SZ 最新行情，再准备一笔普通账户限价买入：
数量 100 股，限价 10.00 元，备注 mcp_demo_20261119_001。
请展示账户、bridge_id、标的、方向、数量、限价和预计委托金额，等待我明确确认。
确认后只提交一次。若超时，查询委托和成交核对备注，不自动重下。
```

用户批准后的工具参数形态为：

```json
{
  "stock_code": "000001.SZ",
  "volume": 100,
  "price": 10.0,
  "confirm_text": "BUY 000001.SZ 100 @ 10.000",
  "order_remark": "mcp_demo_20261119_001"
}
```

提交后调用 `cfquant_account`，结合 `orders`、`trades`、委托编号和备注核对实际状态。区分已接收、已报、部分成交、全部成交、已撤和废单；以柜台返回为准。备注用于核对，不是服务端幂等键，相同备注重复提交仍可能产生多笔委托。最小成交单位、可用资金、价格档位和交易时段也必须满足对应市场与券商规则。

## 管理 Key、速率限制与操作留痕

一个 AI 客户端使用一个 Key，便于单独停用、调额和追查。管理员可编辑名称、查询/交易权限、账号范围和速率，也可随时查看、复制或删除已创建的 Key。Key 明文用当前 Windows 用户的 DPAPI 加密保存；普通列表只返回脱敏信息，查看明文本身也留痕。

账号授权使用完整的 `bridge_id:account_type:account_id` 绑定标识。相同资金账号在不同券商、桥接或账户类型下不是同一个授权对象。可选择具体绑定，或明确授权“全部账号（含后续新增）”。未指定账号时，只有授权范围内恰好一个可用绑定才会自动补全；多个绑定时必须明确指定。已停用或删除的绑定不可调用。

默认限制如下，可由管理员按 Key 修改为 1 到 100000 的整数：

- 每分钟总请求：60 次。
- 每秒总请求：5 次。
- 每分钟交易：10 笔，含撤单；批量委托按其中的实际笔数计数。

限制使用持久化滑动窗口，多个线程共享额度，重启适配进程或 Web 服务不会清零尚未过期的窗口。三个窗口同时生效；超限返回 `429` 和 `Retry-After` 秒数，服务端不会排队稍后补执行。查询可等待后再次读取；交易超时、断线或结果不明时仍须先核对委托，不能统一自动重试。

每次受限 Key 调用会在派发前写入独立审计库，之后补写接口结果。记录 Key 标识、时间、来源 IP、方法与路径、账号范围、业务参数、结果编号、拒绝或限流原因。参数只记录允许的业务字段，不保存 API Key、登录密码、认证头或完整返回数据。

在 Key 管理页面可按 Key 筛选、分页查看记录。审计文件位于运行状态目录下的 `runtime/audit/api_keys.sqlite3`，与普通运行日志分离，普通日志清理不会删除它；Key 删除后历史继续保留。备份核查时请保留审计库。`pending` 表示没有完成结果，可能仍在执行或进程中断；审计“接口成功”也不代表委托已成交。

服务端只开放文档列出的查询和基础委托/撤单接口。受限 Key 不能管理 Key、读取管理员密钥、修改配置、更新服务、控制 QMT 生命周期或访问未开放接口，也不支持 WebSocket；新增工具前核对 [API 参考](API_REFERENCE.md) 中的范围。

## 常见问题

- MCP 连不上：确认配置的是 stdio 脚本，而不是把 8765 当成 MCP 地址；检查解释器、脚本绝对路径、环境变量和 SDK 版本。
- `401`：检查 API Key 和访问策略，不让 AI 猜测、输出或替换密钥。
- `403`：检查 Key 的查询/交易权限，以及目标账号、类型、`bridge_id` 是否属于授权绑定；不要让 AI 切换到其他账号绕过限制。
- `429`：已经达到该 Key 的窗口限制，等待 `Retry-After`，需要提高额度时由管理员调整。
- 服务在线但查询超时：检查对应 QMT 登录、桥接状态和绑定路由；双 QMT 模式检查两个端的内部 Python 环境与脚本。
- 看不到买入工具：默认关闭，需本地明确开启并重启适配进程。
- 提交超时或连接中断：可能已提交，先按账号、标的、备注和时间查询委托与成交，结果不明时交给用户核对。
- AI 在远程设备：`127.0.0.1` 指向 MCP 进程所在设备；根据实际网络部署设置访问策略，不直接暴露未受保护的交易接口。

更多 HTTP 接口见 [API 参考](API_REFERENCE.md)，另一条接入路径见 [AI 策略迁移指南](AI_STRATEGY_MIGRATION.md)。
