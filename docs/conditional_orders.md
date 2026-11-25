# 条件单、仓位计算与下单计划

这些接口属于 `cfquant.cftrader`，与 [TWAP / VWAP / POV](algorithm_trading.md) 共用 A 的执行服务、账户路由、共享全推行情及持久化任务库。网页“接口 / 文档 → 算法交易”提供每个接口的 Python 和 HTTP 示例；关闭页面不影响任务执行。

首版支持沪、深、北市场现金股票的普通买入及已有持仓卖出，不支持融券、期货、杠杆或 ETF。条件单保护已有多头持仓；同一组内任一条件满足即触发一次退出，多个条件共用同一份保护数量。条件单不是交易所原生止损单，A、LTtx 和 QMT 桥必须在线。

## 仓位计算：2% 是账户风险预算

给定账户总资产 10 万元、计划买入价 10 元、止损参考价 9 元、账户风险比例 2%，不计费用时为 `100000 × 0.02 / (10 - 9) = 2000` 股。按下述默认费用估算并向下取整，普通主板股票最终为 **1900 股**。

`entry_price` 是计划买入价 / 买入最高限价，不特指每日开盘价。`risk_percent=0.02` 表示按止损价成交时的预计损失预算为账户总资产的 2%；`allocation_percent=0.02` 则表示拿计算基数的 2% 投入买入，两者含义不同。

```python
from cfquant.cftrader import calculate_position

result = calculate_position(
    stock_code="600000.SH", method="risk_percent",
    total_asset=100000, available_cash=50000,
    entry_price=10, stop_price=9, risk_percent=0.02,
    take_profit_price=12, max_position_percent=0.30,
)
print(result["quantity"], result["estimated_loss"], result["limiting_reasons"])
```

`calculate_position` 是纯函数，不登录、不查询账户、不下单，也可通过 `CfQuantTrader.calculate_position(...)` 调用。所有参数均使用关键字。

| method | 必填的计算参数 | 计算口径 |
| --- | --- | --- |
| `risk_amount` | `entry_price`, `stop_price`, `risk_amount` | 固定预计止损金额 |
| `risk_percent`（默认） | `entry_price`, `stop_price`, `total_asset`, `risk_percent` | 总资产 × 风险比例 |
| `cash_amount` | `entry_price`, `cash_amount` | 固定投入金额，包含买入费用 |
| `allocation_percent` | `entry_price`, `allocation_percent`，对应基数 | `allocation_base="total_asset"`（默认）或 `"available_cash"` |
| `target_weight` | `entry_price`, `total_asset`, `target_weight` | 扣除 `current_volume` 和 `pending_buy_volume` 后的买入差额；已超配时返回 0，不自动卖出 |

所有比例用小数表示，如 `0.05` = 5%。买入量同时受下列约束：

- `available_cash - reserved_cash`：可用资金；纯计算可省略资金上限，下单计划一定从账户读取。
- `max_position_percent`：买入后该股票的总持仓与待买数量上限；`max_volume`：本次最大买入股数。
- `stop_price` 必须大于 0 且小于 `entry_price`；入场、止损和止盈参考价必须符合价格步长。
- 默认普通沪深股票最少 100 股、100 股递增；科创板最少 200 股、1 股递增；北交所最少 100 股、1 股递增。纯计算可显式覆盖 `min_volume`、`volume_step`、`price_tick`，服务端计划使用其股票规则及行情源提供的价格步长。
- 数量只向下取合法值；连最低申报量都不满足时返回 `quantity=0` 和 `below_minimum_order`，不会凑整超预算。

费用参数：`commission_rate=0.0003`、`min_commission=5`（买卖两侧分别估算）、`sell_tax_rate=0.0005`、`transfer_fee_rate=0.00001`（双侧）、`slippage_per_share=0`（每股往返滑点金额合计）。这些是可配置的估算参数，应替换成账户实际费率。佣金存在最低收费，计算器用搜索校验最终数量，不只计算一次除法。默认按一次买入、一次卖出估算；拆单或多次退出的最低佣金可能增加实际费用。

返回字段包括 `quantity`、`theoretical_quantity`、`notional`、`cash_required`、`risk_budget`、`estimated_loss`、`risk_percent`、`position_percent`、买卖费用、滑点金额、`limiting_reasons`、`rules` 和 `assumptions`。提供 `take_profit_price` 时还返回 `estimated_profit` 与扣费后的 `reward_risk_ratio`。没有止损参考价时，损失和风险收益比返回 `None`。

`estimated_loss` 是按输入止损价成交的估计值，不是最大亏损保证。跳空、流动性、价格限制和 T+1 均可能使实际亏损更大。

## 条件类型与保护组

`order_condition(account, stock_code, conditions, execution, **options)` 返回 `condition_...` 形式的 `algo_id`。`conditions` 是规则数组，按数组顺序记录首次触发原因。下面每行是一个可放入数组的规则：

| type | 规则示例 | 行为 |
| --- | --- | --- |
| `stop_loss` | `{"type":"stop_loss","price":9}` | 价格小于等于 9 时退出；也可用 `percent:0.05` 相对固定参考价下跌 5% |
| `take_profit` | `{"type":"take_profit","percent":0.1}` | 相对参考价上涨 10% 时退出；也可直接指定 `price` |
| `time_exit` | `{"type":"time_exit","at":"2026-11-06T14:50:00+08:00"}` | 到指定时间退出；加 `only_if_loss:true` 时在到期后的首个可执行、新鲜行情上检查一次亏损条件 |
| `holding_exit` | `{"type":"holding_exit","opened_at":"2026-11-05T10:00:00+08:00","seconds":3600}` | 持仓满自然秒数退出，包括午休和非交易时段 |
| `holding_exit` | `{"type":"holding_exit","opened_at":"2026-11-05T10:00:00+08:00","trading_days":3,"exit_time":"14:50"}` | 从开仓日之后的第 3 个交易日指定时间退出；依据交易日历，不用工作日猜测节假日 |
| `trailing_stop` | `{"type":"trailing_stop","drawdown_percent":0.05}` | 从监控后实际观测到的最高价回落 5% 时退出；也可用 `drawdown_amount` |
| `trailing_stop` | `{"type":"trailing_stop","activation_percent":0.1,"drawdown_percent":0.03}` | 盈利 10% 后启用高点回撤 3% 保护；也可用 `activation_price` |
| `breakeven_stop` | `{"type":"breakeven_stop","activation_percent":0.05,"offset_amount":0.02}` | 盈利 5% 后保护参考价加 0.02 元；也可用 `offset_percent` 或显式 `protect_price` |
| `step_stop` | `{"type":"step_stop","steps":[{"gain_percent":0.05,"protect_percent":0},{"gain_percent":0.1,"protect_percent":0.05}]}` | 盈利 5% 后保本、盈利 10% 后保护 5% 收益，保护价只上移 |

百分比规则、保本、阶梯以及亏损定时退出需要显式 `reference_price`，创建后固定，不随账户平均成本或手动增仓变化。保本偏移可包含自行估算的费用，不保证实际成交保本。高点只来自监控 / 激活后的有效行情快照，断线和暂停期间未观测到的高点不会补造。

保护数量三选一：`order_volume` 固定股数；`position_percent` 按当前未被其他活动保护组占用的持仓比例取整；`all_sellable=True` 按创建时可卖且未占用的持仓取快照。之后的新买入不会自动加入独立保护组。同账户同股票的活动保护组不能重复认领同一持仓数量。

```python
from cfquant import cftrader
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

ENABLE_TRADING = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
orders_api = cftrader.CfQuantTrader(XtQuantTrader("", 0))

if ENABLE_TRADING:
    algo_id = orders_api.order_condition(
        account, "600000.SH", order_volume=1000, reference_price=10,
        conditions=[
            {"type": "stop_loss", "price": 9},
            {"type": "take_profit", "price": 12},
            {"type": "trailing_stop", "activation_percent": 0.10, "drawdown_percent": 0.05},
        ],
        execution={"algo": "LIMIT", "limit_price": 8.80},
        request_key="my-protection-001",
    )
    print(orders_api.query_algo(algo_id))
```

`execution.limit_price` 为卖出最低接受价，独立于触发价；触发后价格已经跌破该值时，可能挂单等待而无法成交。`execution.algo` 可选 `LIMIT`（默认）、`TWAP`、`VWAP`、`POV`。所有方式都通过原有母单 / 子单核对机制执行，`LIMIT` 表示立即尝试执行全部合法数量的限价任务。可传 `duration_seconds`（每轮默认 300 秒）、`interval_seconds`、`max_child_volume`、`child_timeout_seconds`、`price_mode`、`participation_rate`、`volume_profile`、`lookback_days`、`strategy_name`。

执行轮次不跨午休或收盘。委托全部核对完毕后，未完成的保护数量可在下一轮 / 下一交易时段继续执行；拒单会暂停保护组，需要检查 `last_error` 和子任务后显式恢复。未知委托或撤单结果未确认时不会补发。零股余量仅在本组剩余量恰好等于全部可卖余量时尝试一次性卖出。

其他选项：`quote_field="lastPrice"`（或 `bid1` / `ask1`）、`max_quote_age=15`、`trigger_on_create=True`、`expires_at`。默认首个有效快照已经满足条件就触发；设 `trigger_on_create=False` 后，价格规则需先观察到不满足，再观察到满足。时间规则始终按到期判断。

时间接受 Unix 秒或 ISO 日期时间；不带时区按北京时间解释。只在交易日 09:30–11:30、13:00–14:57 评估 / 提交；午休、非交易日、断线或行情过期则等待。错过到点时间时，顺延至首个可执行且行情新鲜的时刻。亏损定时规则当时未亏损则该条不再触发。未来交易日历尚未覆盖持仓天数时创建失败，不猜测日期。

也提供快捷 Python 接口：`order_stop_loss`、`order_take_profit`、`order_trailing_stop`、`order_breakeven_stop`、`order_time_exit`。复杂条件和多条件组合使用 `order_condition`。快捷方法的参数及等价 HTTP 请求可在网页接口参考中查看。

## 下单计划：预览、复核、提交、保护成交数量

`preview_order_plan` 从绑定账户获取资产、持仓和待买委托，计算数量并保存预览，不提交委托。提交时再次检查可用资金、当前卖一价、价格上限、有效交易时段和风险额度；最终量只会保持或减小，不超过用户预览时的数量。

```python
from cfquant import cftrader
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount

ENABLE_REQUESTS = False
SUBMIT_ORDER = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
orders_api = cftrader.CfQuantTrader(XtQuantTrader("", 0))

if ENABLE_REQUESTS:
    plan = orders_api.preview_order_plan(
        account, "600000.SH",
        sizing={"method": "risk_percent", "entry_price": 10, "stop_price": 9,
                "risk_percent": 0.02, "max_position_percent": 0.30},
        execution={"algo": "LIMIT", "limit_price": 10},
        protection={"conditions": [{"type": "stop_loss", "price": 9},
                                   {"type": "take_profit", "price": 12}],
                    "execution": {"limit_price": 8.80}},
        expires_seconds=180, request_key="my-entry-plan-001",
    )
    print(plan["preview"])
    if SUBMIT_ORDER:
        submitted = orders_api.submit_order_plan(plan["algo_id"])
        print(submitted["entry_id"], submitted["protection_id"])
        print(orders_api.query_order_plan(plan["algo_id"]))
```

计划的 `sizing` 接收计算器参数，但账号资产、现金、当前持仓、待买数量及证券数量 / 价格步长由服务端提供，不允许调用方覆盖。入场 `execution.limit_price` 必须等于 `sizing.entry_price`；省略入场 `execution` 时自动使用这个价格的 `LIMIT` 任务。

`protection` 可省略；填写时使用条件组的 `conditions` 和 `execution`，可选固定 `reference_price`（默认计划入场价）、`quote_field`、`trigger_on_create`、`expires_at`。保护配置在入场允许执行前持久化，仅保护已确认成交的股数；部分成交逐步计入。保护触发后同时请求撤销入场剩余委托，撤单过程中新增的确认成交仍纳入保护。可卖不足时进入 `WAITING_SELLABLE`，不会把 T+1 不可卖的股份报为已平仓。

`expires_seconds` 默认 180 秒，最大 3600 秒，限制预览提交有效期。提交因行情尚未就绪失败时可在有效期内重试同一计划。`submit_order_plan` 使用 `plan_id` 本身幂等，响应丢失后重复提交不会新建第二份入场。

同一服务内各已提交计划在账户锁下预留资金，直到入场最终核对完毕；同股票尚未完成的计划数量也计入目标权重和持仓上限。预留量可能与券商冻结资金 / 待买量重叠，选择保守减少可下数量。可选 `portfolio_risk_cap` 为本次提交允许的、该账户所有计划尚未释放的**名义止损风险总额**；要求提供 `stop_price`。该值是本次检查阈值，不会设置全局账户规则。没有止损参考价的其他计划无法计入此风险金额。

资金和风险预留不覆盖用户直接下单、其他服务实例及账户内已有的非计划持仓。入场结束后，已成交未平仓部分继续占用计划风险；只有关联保护单确认退出的数量会释放。手动平仓不会自动猜测归属、释放这部分风险。若省略保护，计划显示 `HOLDING`；风险测算本身不会创建实际止损。

`cancel_order_plan` 只撤入场剩余部分，已成交部分的保护保留。取消保护必须显式 `cancel_algo(protection_id)`，暂停 / 恢复保护使用 `pause_algo` / `resume_algo`。

## 查询、状态和日志

| 对象 | 查询与控制 | 重要字段 |
| --- | --- | --- |
| 条件组 | `query_algo`、`list_algos`、`pause_algo`、`resume_algo`、`cancel_algo` | `kind="condition"`、`states`（高点 / 激活 / 保护价）、`trigger`、`exits`（执行母单 ID）、成交 / 剩余 / 在途数量 |
| 下单计划 | `query_order_plan`、`list_order_plans`、`cancel_order_plan` | `kind="plan"`、`preview`、提交后 `sizing`、账户快照、`entry_id`、`protection_id`、`reserved_cash`、`reserved_risk` |
| 执行母单 | 原有 `query_algo` 等 | `children`、`order_id`、`filled_volume`、`reserved_volume`、`last_error` |

条件组状态包括 `MONITORING`、`WAITING_FILL`、`WAITING_SESSION`、`WAITING_MARKET`、`WAITING_SELLABLE`、`EXECUTING`、`PAUSED`、`CANCELLING` 及终态 `COMPLETED/CANCELLED/EXPIRED`。计划从 `PREVIEW` 到 `SUBMITTING/SUBMITTED`，成交后进入 `PROTECTED` 或 `HOLDING`；退出后才完成。任务接受、条件触发、委托提交和最终成交是不同阶段。

`events` 保存最近 200 条生命周期事件，包含唯一事件 ID、时间、触发原因和关联任务；同时写入服务日志。查询当前状态是确认处理结果的依据，没有新增或伪造 `on_stock_order` 回调。实际委托继续使用原有订单回调与查询接口。

状态存于 `runtime` 的算法任务 SQLite 库，调用脚本退出不撤单。A 的业务工作进程恢复后自动加载并核对委托，未知提交不自动重放；跨日无法查到旧委托时保持待确认，需要人工核对。存储写入失败后执行器停止新增执行，修复存储并重启服务后恢复。不要删除任务库来“重试”未知委托。

## HTTP / RPC 对照

全部为 POST，JSON 请求；沿用现有服务的认证方式。成功响应为 `{"ok":true,"data":...}`。账号字段为 `account` 对象，可携带 `account_id`、`account_type`、`bridge_id`、`account_key`。

| HTTP 路径 | RPC action / Python 方法 | 请求核心字段 |
| --- | --- | --- |
| `/api/trade/position/calculate` | `cftrader.calculate_position` | 计算器关键字参数；不需要账号 |
| `/api/trade/condition/submit` | `cftrader.order_condition` | `account`, `stock_code`, `conditions`, `execution`，保护数量选项 |
| `/api/trade/plan/preview` | `cftrader.preview_order_plan` | `account`, `stock_code`, `sizing`，可选 `execution/protection` |
| `/api/trade/plan/submit` | `cftrader.submit_order_plan` | `account`, `plan_id`（预览返回的 `algo_id`） |
| `/api/trade/plan/query` | `cftrader.query_order_plan` | `account`, `plan_id` |
| `/api/trade/plan/list` | `cftrader.list_order_plans` | `account` |
| `/api/trade/plan/cancel` | `cftrader.cancel_order_plan` | `account`, `plan_id` |
| `/api/trade/algo/query`、`list`、`pause`、`resume`、`cancel` | 对应原有算法管理 action | `account`, `algo_id`（list 不需要 ID） |

```json
{
  "account": {"account_id": "YOUR_ACCOUNT_ID", "account_type": "STOCK"},
  "stock_code": "600000.SH", "order_volume": 1000, "reference_price": 10,
  "conditions": [{"type": "stop_loss", "price": 9}, {"type": "take_profit", "price": 12}],
  "execution": {"algo": "LIMIT", "limit_price": 8.8},
  "request_key": "my-protection-001"
}
```

上例发送至 `/api/trade/condition/submit`。新建条件组 / 预览计划重试时应保留同一 `request_key` 与完整参数；同 key 改参数会报错。SDK 默认生成 key，业务重试时建议自己保存并传入稳定 key。Python 快捷条件方法映射到同一个条件组 HTTP 接口。
