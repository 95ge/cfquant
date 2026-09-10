/* Project-owned SDK entries, separate from the xtquant compatibility inventory. */
(() => {
  'use strict';
  const parameter = (name, help, value = '必填') => ({ name, help, default: value });
  const account = parameter('account', '原 StockAccount 或账号字典；None 使用原 trader 绑定的账号。每批对应一个账号。');
  const strategy = parameter('strategy_name', '策略名称；批量调用时可由每笔的同名字段覆盖。', '""');
  const remark = parameter('order_remark', '委托备注；批量中非空的逐笔备注原样保留，缺失或为空时追加行号。', '""');
  const orderFields = [
    parameter('stock_code', '证券或合约代码，保留大小写。'),
    parameter('order_type', '原 xtconstant 下单类型常量，例如 STOCK_BUY、CREDIT_FIN_BUY。'),
    parameter('order_volume', '正整数数量，单位沿用原品种约定。'),
    parameter('price_type', '原 xtconstant 报价类型常量，例如 FIX_PRICE。'),
    parameter('price', '有限数值；市价模式也显式传入原接口要求的占位价格。'),
  ];
  const batchReturns = [
    ['batch_id / account / asynchronous', '批次 ID、账号和是否异步。'],
    ['ok / total / attempted', '全部提交成功时 ok 为 True；总笔数和已尝试笔数。'],
    ['submitted / failed / unknown / skipped', '四种逐笔状态的数量，合计等于 total。'],
    ['results', '与输入等长、顺序一致。每行包含 index、stock_code、status、ok、order_id、seq、strategy_name、order_remark、error。'],
    ['submitted', '获得有效订单号或 seq，不代表成交；最终状态继续看原回调。'],
    ['execution / qmt_submit_ms', 'execution 为 qmt；正常回包中的 qmt_submit_ms 是 QMT 提交循环耗时，不含通信及编号解析。'],
    ['failed', 'QMT 明确拒绝，同步、异步均适用；stop_on_error=True 时停止后续提交。'],
    ['unknown', '同步编号未确认、整批回包异常或本地下单异常；先核对原查询和回调。编号未确认时后续订单可能已提交。'],
    ['skipped', '本次未调用该笔下单，不会自动补发。'],
  ];
  function example(method, batch, asynchronous) {
    const callback = asynchronous ? `
class Callback(XtQuantTraderCallback):
    def on_order_stock_async_response(self, response):
        print("response:", response.seq, response.order_id, response.order_remark)

    def on_stock_order(self, order):
        print("order:", order.order_id, order.order_status)

    def on_stock_trade(self, trade):
        print("trade:", trade.order_id, trade.traded_volume)

    def on_order_error(self, error):
        print("error:", error)
` : '';
    const argumentsCode = batch ? `account, orders, strategy_name="rebalance", stop_on_error=True` : `account, "600000.SH", xtconstant.STOCK_BUY, 100,
            xtconstant.FIX_PRICE, 10.0, strategy_name="example"`;
    return `from cfquant import cftrader, xtconstant
from cfquant.xttrader import XtQuantTrader${asynchronous ? ', XtQuantTraderCallback' : ''}
from cfquant.xttype import StockAccount
${callback}
ENABLE_TRADING = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
${batch ? `orders = [
    dict(stock_code="600000.SH", order_type=xtconstant.STOCK_BUY,
         order_volume=100, price_type=xtconstant.FIX_PRICE, price=10.0),
    dict(stock_code="000001.SZ", order_type=xtconstant.STOCK_BUY,
         order_volume=100, price_type=xtconstant.FIX_PRICE, price=9.0),
]
` : ''}trader = XtQuantTrader("", 0)
orders_api = cftrader.CfQuantTrader(trader)
if ENABLE_TRADING:
    try:
${asynchronous ? '        trader.register_callback(Callback())\n' : ''}        trader.start()
        if trader.connect() != 0 or trader.subscribe(account) != 0:
            raise RuntimeError("Connection or subscription failed")
        result = orders_api.${method}(
            ${argumentsCode},
        )
        print(result)
${asynchronous ? '        trader.run_forever()\n    except KeyboardInterrupt:\n        pass\n' : ''}    finally:
        trader.stop()
else:
    print("Preview only; trading is disabled")`;
  }
  window.CFQUANT_CFTRADER_API = [
    ['order_stock_batch', '批量同步下单', true, false],
    ['order_stock_batch_async', '批量异步下单', true, true],
    ['order_stock', '单笔同步下单', false, false],
    ['order_stock_async', '单笔异步下单', false, true],
  ].map(([method, title, batch, asynchronous]) => ({
    id: 'cftrader.' + method,
    name: method,
    module: 'cftrader',
    group: '独立下单接口',
    status: 'extension',
    title,
    description: batch
      ? `一次批量 RPC 将整批订单发送到大 QMT，QMT 内部连续下单。${asynchronous ? '提交后返回逐笔 seq 和受理状态，订单号继续走原回调。' : '整批提交后集中解析订单号，返回逐笔结果。'}`
      : `使用原 XtQuantTrader.${method} 的参数和返回值。`,
    signature: `CfQuantTrader.${method}(${batch ? 'account, orders, strategy_name="", order_remark="", stop_on_error=False' : 'account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""'})`,
    parameters: batch
      ? [account, parameter('orders', '非空列表或元组，每笔为下列字段组成的字典；完整校验通过后一次性发送到 QMT。'), strategy, remark, parameter('stop_on_error', '布尔值；QMT 明确拒绝时是否停止。下单抛出异常总是停止；同步编号解析在整批提交之后。', 'False')]
      : [account, ...orderFields, strategy, remark],
    orderFields: batch ? [...orderFields, strategy, remark] : [],
    resultRows: batch ? batchReturns : [[asynchronous ? 'seq' : 'order_id', '沿用原单笔接口的返回值及错误语义。']],
    resultHelp: batch
      ? `同步成功行填充 order_id；异步所有行保留预分配 seq，另一编号字段为 None；index 从 0 开始。只有 submitted 代表确认受理，不代表成交。异步回调可能早于批次返回，使用 order_remark、seq 和 order_id 关联。`
      : `返回${asynchronous ? '请求序号 seq' : '订单号 order_id'}；最终委托、成交和错误仍从原 XtQuantTraderCallback 接收。`,
    note: batch
      ? '需更新并重启 Web 服务及 QMT 桥。SDK 发送一个批量请求，QMT 本地执行整批，同步编号集中解析。整批超时后 QMT 可能仍在执行，结果标为 unknown；不自动重试或切换通道重发。已提交订单不回滚，不保证原子性或同时成交。独立市场路由按输入顺序分段，每个连续目标 QMT 段发送一个批量请求。'
      : 'cfquant 自有 Python SDK 扩展，单笔下单直接复用原 trader。',
    usage: 'from cfquant import cftrader 后，用 cftrader.CfQuantTrader(trader) 包装已有 XtQuantTrader。连接、订阅、查询、撤单和回调继续由原 trader 管理。信用账号使用 CREDIT 及原信用下单常量；期货、期权沿用原账号类型和业务常量。',
    example: example(method, batch, asynchronous),
    related: batch ? ['cftrader.order_stock_batch', 'cftrader.order_stock_batch_async'].filter(id => id !== 'cftrader.' + method) : ['cftrader.order_stock_batch', 'cftrader.order_stock_batch_async'],
  }));
})();
