/* Conditional orders and position sizing in the shared API reference. */
(() => {
  'use strict';
  const account = { account_id: 'YOUR_ACCOUNT_ID', account_type: 'STOCK' };
  const sizing = { method: 'risk_percent', entry_price: 10, stop_price: 9, risk_percent: 0.02, max_position_percent: 0.30 };
  const conditions = [{ type: 'stop_loss', price: 9 }, { type: 'take_profit', price: 12 },
    { type: 'trailing_stop', activation_percent: 0.1, drawdown_percent: 0.05 }];
  const protection = { conditions, execution: { algo: 'LIMIT', limit_price: 8.8 } };
  const base = { account, stock_code: '600000.SH', order_volume: 1000, reference_price: 10,
    ...protection, request_key: 'my-protection-001' };
  const definitions = [
    ['calculate_position', '仓位计算 · 风险金额、风险比例、资金分配', 'position/calculate',
      { stock_code: '600000.SH', ...sizing, total_asset: 100000, available_cash: 50000 },
      '*, stock_code, entry_price, method="risk_percent", stop_price=None, total_asset=None, available_cash=None, risk_amount=None, risk_percent=None, cash_amount=None, allocation_percent=None, allocation_base="total_asset", target_weight=None, current_volume=0, pending_buy_volume=0, max_position_percent=None, max_volume=None, reserved_cash=0, commission_rate=0.0003, min_commission=5, sell_tax_rate=0.0005, transfer_fee_rate=0.00001, slippage_per_share=0, take_profit_price=None, min_volume=None, volume_step=None, price_tick=0.01',
      'stock_code="600000.SH", entry_price=10, stop_price=9,\n        method="risk_percent", risk_percent=0.02, total_asset=100000, available_cash=50000',
      '纯计算，不连接账户、不下单。账户风险 2% 表示按止损价成交时预计损失为总资产 2%；资金投入 2% 是另一种计算口径。'],
    ['order_condition', '条件保护组 · 止盈止损、期限、回撤、阶梯', 'condition/submit', base,
      'account, stock_code, conditions, execution, **options',
      'account, "600000.SH", order_volume=1000, reference_price=10,\n        conditions=[{"type": "stop_loss", "price": 9}, {"type": "take_profit", "price": 12}],\n        execution={"algo": "LIMIT", "limit_price": 8.8}, request_key="my-protection-001"',
      '同组的条件共用一份保护数量，任一满足即退出。支持固定 / 百分比止盈止损、定时、持仓秒数 / 交易日、高点回撤、保本和阶梯保护。'],
    ['order_stop_loss', '到价止损', 'condition/submit', { ...base, conditions: [{ type: 'stop_loss', price: 9 }] },
      'account, stock_code, order_volume, stop_price, limit_price, **options',
      'account, "600000.SH", 1000, 9, 8.8, request_key="my-stop-001"', '价格小于等于止损价时触发，卖出最低接受价独立指定。'],
    ['order_take_profit', '到价止盈', 'condition/submit', { ...base, conditions: [{ type: 'take_profit', price: 12 }], execution: { limit_price: 11.8 } },
      'account, stock_code, order_volume, take_profit_price, limit_price, **options',
      'account, "600000.SH", 1000, 12, 11.8, request_key="my-profit-001"', '达到止盈价时触发。与止损组合时应使用一个 order_condition 保护组。'],
    ['order_trailing_stop', '高点回撤 · 可设置盈利激活价', 'condition/submit',
      { ...base, conditions: [{ type: 'trailing_stop', drawdown_percent: 0.05, activation_price: 11 }] },
      'account, stock_code, order_volume, drawdown_percent, limit_price, activation_price=None, **options',
      'account, "600000.SH", 1000, 0.05, 8.8, activation_price=11, request_key="my-trail-001"',
      '从激活后实际观测到的高点回落指定比例触发。重启保留高点，断线期间未观测的高点不会补造。'],
    ['order_breakeven_stop', '保本止损 · 盈利后保护成本与偏移', 'condition/submit',
      { ...base, conditions: [{ type: 'breakeven_stop', activation_percent: 0.05, offset_amount: 0.02 }], execution: { limit_price: 9.8 } },
      'account, stock_code, order_volume, reference_price, activation_percent, limit_price, offset_amount=0, **options',
      'account, "600000.SH", 1000, 10, 0.05, 9.8, offset_amount=0.02, request_key="my-breakeven-001"',
      '盈利达到门槛后，回落到固定参考价加偏移时触发。偏移可计入预计费用，不保证实际成交保本。'],
    ['order_time_exit', '定时平仓 / 定时亏损退出', 'condition/submit',
      { ...base, conditions: [{ type: 'time_exit', at: '2026-11-06T14:50:00+08:00', only_if_loss: false }] },
      'account, stock_code, order_volume, at, limit_price, only_if_loss=False, **options',
      'account, "600000.SH", 1000, "2026-11-06T14:50:00+08:00", 8.8,\n        only_if_loss=False, request_key="my-time-exit-001"',
      '到期后首个可执行且行情新鲜的时刻退出。only_if_loss=True 需要 reference_price，只在该时刻判断一次；请替换示例日期。'],
    ['preview_order_plan', '下单计划 · 查询账户并预览数量', 'plan/preview',
      { account, stock_code: '600000.SH', sizing, protection, expires_seconds: 180, request_key: 'my-entry-plan-001' },
      'account, stock_code, sizing, **options',
      'account, "600000.SH",\n        sizing={"method": "risk_percent", "entry_price": 10, "stop_price": 9, "risk_percent": 0.02},\n        protection={"conditions": [{"type": "stop_loss", "price": 9}], "execution": {"limit_price": 8.8}},\n        expires_seconds=180, request_key="my-entry-plan-001"',
      '读取账户总资产、可用资金、持仓和待买委托，保存数量与费用预览；此步骤不下单。'],
    ['submit_order_plan', '下单计划 · 复核、预留资金并提交', 'plan/submit', { account, plan_id: 'YOUR_PLAN_ID' },
      'plan_id, account=None', '"YOUR_PLAN_ID", account=account',
      '复核报价、现金及风险额度，数量不超过预览值。同 plan_id 重复提交幂等；先安装保护，再允许入场执行，保护量按确认成交增长。'],
    ['query_order_plan', '查询下单计划', 'plan/query', { account, plan_id: 'YOUR_PLAN_ID' },
      'plan_id, account=None', '"YOUR_PLAN_ID", account=account', '查询预览 / 提交数量、预留资金和风险、入场与保护任务 ID。'],
    ['list_order_plans', '列出账户下单计划', 'plan/list', { account },
      'account=None', 'account=account', '列出指定绑定账户的持久化计划。'],
    ['cancel_order_plan', '撤销计划入场余量 · 保留成交保护', 'plan/cancel', { account, plan_id: 'YOUR_PLAN_ID' },
      'plan_id, account=None', '"YOUR_PLAN_ID", account=account',
      '撤销入场剩余委托，保留已成交股份的保护。取消保护需显式调用 cancel_algo(protection_id)。'],
  ];
  const help = {
    account: 'StockAccount 或账号字典，支持绑定路由；新进程控制已有任务时显式传入。', stock_code: 'SH / SZ / BJ 现金股票，不支持 ETF、期货或融券。',
    entry_price: '计划买入最高价，须符合价格步长。', method: 'risk_amount / risk_percent / cash_amount / allocation_percent / target_weight。',
    stop_price: '止损参考价，须低于买入价。', order_volume: '保护股数，不重复认领其他活动组的持仓。', take_profit_price: '止盈触发价。',
    limit_price: '卖出最低接受价，跌破时可能无法成交。', reference_price: '固定参考成本，不随持仓平均成本变化。',
    drawdown_percent: '回撤比例，0.05 表示 5%。', activation_percent: '相对参考价的盈利激活比例。', activation_price: '达到后激活；省略则立即监控高点。',
    offset_amount: '每股保护偏移，可加入预计费用。', at: 'ISO 日期时间或 Unix 秒，不带时区按北京时间解释。', only_if_loss: '到期可执行时检查一次亏损条件，需要 reference_price。',
    conditions: '规则数组：stop_loss / take_profit / time_exit / holding_exit / trailing_stop / breakeven_stop / step_stop；任一满足触发。',
    execution: '必填 limit_price；algo 可选 LIMIT、TWAP、VWAP、POV，可带时长、间隔、参与率、成交量曲线等参数。',
    sizing: '计算器参数对象；账户资产、现金、持仓、待买数量和证券规则由服务端提供，不允许覆盖。', plan_id: '预览返回对象中的 algo_id。',
    total_asset: '账户总资产，风险比例和目标权重的计算基数。', available_cash: '可用现金；纯计算省略时不施加现金上限。', risk_amount: '固定预计止损预算金额。', risk_percent: '预计止损占总资产比例，0.02 = 2%。', cash_amount: '固定投入金额，包含买入费用。', allocation_percent: '投入资金比例，0.1 = 10%。', allocation_base: 'total_asset 或 available_cash。', target_weight: '目标持仓占总资产比例，已超配返回 0。', current_volume: '已有持仓股数。', pending_buy_volume: '在途待买股数。', max_position_percent: '买入后该股票持仓与待买数量上限。', max_volume: '本次最大买入量。', reserved_cash: '其他计划已预留的现金。', commission_rate: '单侧佣金率。', min_commission: '每侧最低佣金。', sell_tax_rate: '卖出税费率。', transfer_fee_rate: '双侧过户费用估算率。', slippage_per_share: '每股往返滑点金额合计。', min_volume: '最小买入量，默认按股票市场规则。', volume_step: '数量递增步长，默认按股票市场规则。', price_tick: '价格最小变动单位。',
    options: '条件组：request_key、order_volume / position_percent / all_sellable 三选一、reference_price、quote_field、max_quote_age、trigger_on_create、expires_at。计划：execution、protection、expires_seconds（默认 180）、portfolio_risk_cap。',
    sizing_options: 'risk_amount、risk_percent、cash_amount、allocation_percent、allocation_base、target_weight；total_asset、available_cash、current_volume、pending_buy_volume、reserved_cash、max_position_percent、max_volume；commission_rate、min_commission、sell_tax_rate、transfer_fee_rate、slippage_per_share；take_profit_price、min_volume、volume_step、price_tick。完整默认值见 docs/conditional_orders.md。',
  };
  for (const [name, title, route, body, signature, call, description] of definitions) {
    const pure = name === 'calculate_position';
    const example = pure
      ? `from cfquant.cftrader import calculate_position\n\nresult = calculate_position(\n        ${call},\n)\nprint(result)`
      : `from cfquant import cftrader\nfrom cfquant.xttrader import XtQuantTrader\nfrom cfquant.xttype import StockAccount\n\nENABLE_REQUESTS = False\naccount = StockAccount("YOUR_ACCOUNT_ID", "STOCK")\norders_api = cftrader.CfQuantTrader(XtQuantTrader("", 0))\n\nif ENABLE_REQUESTS:\n    result = orders_api.${name}(\n        ${call},\n    )\n    print(result)\nelse:\n    print("Example only; requests are disabled")`;
    window.CFQUANT_CFTRADER_API.push({
      id: 'cftrader.' + name, name, module: 'cftrader', group: '条件单与仓位计划', operation: 'algorithm', status: 'extension',
      title, description, signature: `CfQuantTrader.${name}(${signature})`, example,
      http: { method: 'POST', path: '/api/trade/' + route, body },
      parameters: signature.split(', ').filter(item => item !== '*').map(item => {
        const [raw, fallback] = item.split('='); const key = raw.replace('**', '');
        return { name: key, help: help[key] || key, default: fallback ?? (raw.startsWith('**') ? '{}' : '必填') };
      }), orderFields: [],
      resultRows: pure ? [['quantity / theoretical_quantity', '合法数量 / 理论数量，未达最低量返回 0。'], ['cash_required / estimated_loss', '资金需求 / 按止损价成交的预计损失。'], ['limiting_reasons / rules / assumptions', '约束原因、证券规则、资金和费率假设。']]
        : name.startsWith('order_') ? [['algo_id', '持久化保护组 ID；用 query_algo、pause_algo、resume_algo、cancel_algo 管理。']]
        : [['algo_id / status', '计划 ID 与 PREVIEW / SUBMITTED / PROTECTED / HOLDING 等状态。'], ['preview / sizing', '预览 / 提交复核后的数量与费用。'], ['entry_id / protection_id', '入场与保护任务 ID，可用 query_algo 追踪。'], ['reserved_cash / reserved_risk', '计划预留现金与名义止损风险。']],
      resultHelp: '条件组查询包含 trigger、states（高点 / 激活 / 保护价）、exits、events 及 last_error。T+1 不可卖时为 WAITING_SELLABLE。计划预览返回的 algo_id 用作 plan_id。',
      usage: pure ? '直接导入 calculate_position，不需要启动交易服务。HTTP 计算使用 Web 服务。' : '任务由 Web 服务持久化运行，复用共享行情。保护组只卖出指定数量，计划只保护已确认成交数量。',
      note: '比例用小数（0.02 = 2%）。预计止损金额不保证最大亏损，跳空、流动性和 T+1 可能扩大损失。未知委托不盲目重发。完整规则和参数见 docs/conditional_orders.md。',
      related: ['cftrader.calculate_position', 'cftrader.order_condition', 'cftrader.preview_order_plan', 'cftrader.submit_order_plan', 'cftrader.query_algo'].filter(id => id !== 'cftrader.' + name),
    });
  }
})();
