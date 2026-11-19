# 用 AI 将原有策略适配到 CFQuant

## 适用场景与完成目标

当你已有基于 MiniQMT / `xtquant` 的 Python 策略，希望让 AI 修改代码，使其通过 CFQuant 接入大 QMT，选择这条路径。最终交付物是可以在外部 Python 中运行的策略代码、修改说明和验证结果。

```text
原有策略代码 → AI 梳理接口与兼容性 → 修改导入和连接配置
             → 只读验证 → 回调验证 → 用户批准后验证交易
```

这条路径使用 CFQuant Python SDK；不要求安装 MCP，也不要求向 CFQuant 填写模型账号 Key。你使用的 AI 编程工具自行管理其模型连接。希望直接在 AI 对话里调用交易工具，请阅读 [AI MCP 交易指南](AI_MCP_TRADING.md)。

## 第一步：交给 AI 的材料

- 原策略入口、依赖文件和相关模块，尤其是行情获取、交易对象初始化、下单撤单、回调处理和持久化代码。
- Python 版本与运行方式：命令行、IDE、定时任务或自己的策略管理器。
- 账户类型和目标绑定的 `bridge_id`，资金账号通过环境变量传入；不提供 QMT 登录密码、访问密钥或模型密钥。
- 当前实际使用的接口清单，以及希望保留的交易规则、风控阈值和运行时间。

不要只给 AI 一段下单函数就让它宣称迁移完成。策略往往还依赖历史数据目录、行情订阅、异步回报、断线恢复和原来的配置加载方式，需要一起检查。

## 第二步：明确哪些要改

- 导入：将 SDK 相关的 `xtquant` 导入改成 `cfquant`，常见模块是 `xtdata`、`xtconstant`、`xttrader`、`xttype`。
- 连接：改为已绑定的大 QMT 桥接路由；`userdata_mini` 是旧客户端路径，不填入大 QMT 绑定目录。
- 账号：普通账号 `STOCK`、信用账号 `CREDIT`，其他账号按实际类型配置；同账号在多个券商或通道出现时，要明确 `bridge_id`。
- 业务逻辑：保持信号条件、买卖方向、仓位、价格类型、数量、交易时间和风控规则。
- 特殊接口：逐项核对实际调用和返回字段；条件适配、未适配接口不能仅替换导入就当作完全兼容。不要编造不存在的 cfquant 方法。

CFQuant 默认单 QMT 极致模式。需要两个 QMT 分离行情/回调与交易时选择高级模式，默认 ctypes，也可 socket；策略通过已绑定的统一路由访问，不自己同时连接两个 QMT 目录。高级模式下两个 QMT 的内部 Python 环境需分别检查。

## 示例一：改造前后的基础写法

原 MiniQMT 策略中常见的初始化片段：

```python
from xtquant import xtdata, xtconstant
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
trader = XtQuantTrader(r"D:\MiniQMT\userdata_mini", 123456)
trader.start()
if trader.connect() != 0:
    raise RuntimeError("MiniQMT connect failed")
trader.subscribe(account)
```

CFQuant 改造后的初始化片段：

```python
import os

from cfquant import configure, xtdata, xtconstant
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

# Use the bridge_id from the target Web binding, not an invented channel name.
bridge_id = os.environ["CFQUANT_BRIDGE_ID"]
configure(bridge_id=bridge_id)
account = StockAccount(os.environ["CFQUANT_ACCOUNT_ID"], "STOCK", bridge_id=bridge_id)
trader = XtQuantTrader("", 123456, account=account)
trader.start()
if trader.connect() != 0:
    raise RuntimeError(trader.last_connect_error or "CFQuant connect failed")
if trader.subscribe(account) not in (0, None):
    raise RuntimeError("CFQuant account subscription failed")
```

`configure()` 不是 HTTP API 客户端配置；不要给它编造 `base_url` 或 `api_key` 参数。SDK 默认按本机桥接配置选择连接方式，跨机器部署需要按实际传输与网络配置单独验证。多账号策略不要在任务执行中反复切换全局行情路由，先确认共享行情源与每个交易账号的明确路由。

## 示例二：可运行的只读验证脚本

先在原策略使用的解释器中安装 CFQuant，并确认实际导入位置：

```powershell
python -m pip install cfquant
python -c "import sys, cfquant; print(sys.executable); print(cfquant.__version__); print(cfquant.__file__)"
```

如果使用源码开发环境，在项目根目录执行 `python -m pip install -e .`。外部策略环境和 QMT 内部 Python 环境是两件事，不要把外部依赖安装到 QMT 目录来代替 SDK 配置。

通过运行环境设置 `CFQUANT_ACCOUNT_ID`、`CFQUANT_BRIDGE_ID` 后，将下面代码保存为 `verify_cfquant_readonly.py`。此脚本只查询，不包含下单撤单。

```python
import os

from cfquant import configure, xtdata
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount


def main():
    bridge_id = os.environ["CFQUANT_BRIDGE_ID"]
    configure(bridge_id=bridge_id)
    account = StockAccount(os.environ["CFQUANT_ACCOUNT_ID"], "STOCK", bridge_id=bridge_id)
    trader = XtQuantTrader("", 123456, account=account)
    try:
        trader.start()
        if trader.connect() != 0:
            raise RuntimeError(trader.last_connect_error or "Connection failed")
        if trader.subscribe(account) not in (0, None):
            raise RuntimeError("Account subscription failed")

        tick = xtdata.get_full_tick(["000001.SZ"])
        if not tick:
            raise RuntimeError("No quote returned; check market session and quote source")
        print("Quote:", tick)

        asset = trader.query_stock_asset(account)
        if asset is None:
            raise RuntimeError("No asset data returned")
        print("Cash:", getattr(asset, "cash", None))
        print("Positions:", len(trader.query_stock_positions(account) or []))
        print("Orders:", len(trader.query_stock_orders(account) or []))
    finally:
        trader.stop()


if __name__ == "__main__":
    main()
```

```powershell
python verify_cfquant_readonly.py
```

需要检查行情时间、资金字段与目标账号是否一致；持仓为空可以是正常结果，不能用“非空”作为所有查询的成功标准。行情无数据时检查交易时段、证券代码、行情权限与共享行情源。不要让 AI 为了让脚本通过而伪造行情、资金或委托结果。

## 示例三：保留交易签名与回调

原策略已有的下单调用通常保留签名，只改来源和连接初始化。下面定义一个显式函数，导入或运行这段定义不会自动下单；只有用户批准后的策略执行路径才调用它。

```python
from cfquant import xtconstant
from cfquant.xttrader import XtQuantTraderCallback


class StrategyCallback(XtQuantTraderCallback):
    def on_stock_order(self, order):
        print("Order:", getattr(order, "order_id", None),
              getattr(order, "order_status", None))

    def on_stock_trade(self, trade):
        print("Trade:", getattr(trade, "order_id", None),
              getattr(trade, "traded_volume", None))

    def on_order_error(self, error):
        print("Order error:", getattr(error, "error_msg", None))


def submit_approved_limit_buy(trader, account, stock_code, volume, limit_price):
    return trader.order_stock(
        account, stock_code, xtconstant.STOCK_BUY, volume,
        xtconstant.FIX_PRICE, limit_price,
        strategy_name="migrated_strategy", order_remark="approved_order",
    )
```

在前面的初始化代码中，启动前调用 `trader.register_callback(StrategyCallback())`。长期策略保留原来的事件循环，不能查询后立即 `stop()` 就期待持续接收回调；退出时再释放连接。不要把只读验证脚本直接当作完整实盘策略。

同步下单的返回值用于识别委托提交结果，不表示已经成交；异步下单返回的序号也不能当成交易所委托编号。结合委托查询、成交查询和回调判断最终状态。迁移原有异步策略时还要保留异步响应回调、撤单回报及错误处理，不能统一改成同步调用来掩盖问题。

## 可以直接交给 AI 的任务说明

```text
请将我提供的 MiniQMT / xtquant 策略迁移到 cfquant。
目标：使用已在 Web 控制台绑定的大 QMT，保留原策略交易逻辑。

请按以下步骤工作：
1. 阅读 AI 策略迁移指南，梳理实际使用的 xtquant 接口、配置与依赖。
2. 列出可直接迁移、需条件验证、无法迁移的调用，不编造兼容方法。
3. 将导入替换为 cfquant，按目标 bridge_id 和账户类型初始化。
4. 保留信号、仓位、数量、方向、价格类型、风控、时间和回调语义。
5. 提供最小代码修改、依赖调整和配置说明，不读取或输出密码及密钥。
6. 先做语法、导入、行情、资金和持仓验证，不执行真实下单撤单。
7. 输出验证结果和未验证项。需要交易验证时先展示参数并等待我确认。
8. 对提交超时先核对委托和成交，不增加自动重下单逻辑。

交付：修改后的代码、接口兼容清单、运行命令、验证结果与剩余限制。
```

## 验收与常见问题

1. 实际运行的解释器能导入正确版本的 cfquant，未被同名文件遮蔽。
2. 账号类型、资金账号和 `bridge_id` 都来自目标绑定，账户查询与网页一致。
3. 行情字段、时间、复权、周期与原策略预期一致；历史下载和本地数据目录语义单独验证。
4. 回调只注册一次，策略进程持续运行；断线后能按原设计恢复，不重复触发交易。
5. 普通、信用、期货和期权业务按实际账户单独验证，不把普通股票示例套用到其他业务。
6. 交易验证有用户批准、可核对的委托备注与结果；没有实测的接口明确标记未验证。

仅替换导入后报错：定位具体函数、参数和返回字段，逐项检查兼容状态。`userdata_mini` 或本地历史数据路径报错：梳理原本依赖的客户端数据能力，必要时使用独立本地数据源。查询成功但没有回调：检查订阅结果、账号路由、进程生命周期，以及双 QMT 的普通端是否在线。

需要整体接口入口时阅读 [API 参考](API_REFERENCE.md)。完整迁移应以实际策略使用到的 SDK 源码、当前版本兼容说明和真实验证为准，不能承诺所有 xtquant 接口完全兼容。
