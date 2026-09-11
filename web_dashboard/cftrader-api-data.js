/* Project-owned SDK entries, separate from the xtquant compatibility inventory. */
(() => {
  'use strict';

  const parameter = (name, help, value = '必填') => ({ name, help, default: value });
  const account = parameter('account', '原 StockAccount 或账号字典；None 使用原 trader 绑定的账号。每批对应一个账号。');
  const strategy = parameter('strategy_name', '策略名称；批量下单时可由每笔的同名字段覆盖。', '""');
  const remark = parameter('order_remark', '委托备注；批量下单中非空的逐笔备注原样保留，缺失或为空时追加行号。', '""');
  const stopOnError = parameter('stop_on_error', '布尔值；QMT 明确拒绝某一笔时是否停止后续提交。整批通信异常总是停止；已经提交的委托或撤单不会自动回滚。', 'False');
  const orderFields = [
    parameter('stock_code', '证券或合约代码，保留大小写。'),
    parameter('order_type', '原 xtconstant 下单类型常量，例如 STOCK_BUY、CREDIT_FIN_BUY。'),
    parameter('order_volume', '正整数数量，单位沿用原品种约定。'),
    parameter('price_type', '原 xtconstant 报价类型常量，例如 FIX_PRICE。'),
    parameter('price', '有限数值；市价模式也显式传入原接口要求的占位价格。'),
  ];
  const cancelList = parameter(
    'order_ids',
    '非空列表或元组；可直接传委托号，也可传 dict(order_id="...", stock_code="000001.SZ") 或 dict(order_id="...", market="SZ")。同账号独立市场路由建议带 stock_code 或 market。'
  );
  const batchOrderReturns = [
    ['batch_id / account / asynchronous', '批次 ID、账号和是否异步。'],
    ['ok / total / attempted', '全部提交成功时 ok 为 True；总笔数和已尝试笔数。'],
    ['submitted / failed / unknown / skipped', '四种逐笔状态的数量，合计等于 total。'],
    ['results', '与输入等长、顺序一致。每行包含 index、stock_code、status、ok、order_id、seq、strategy_name、order_remark、error。'],
    ['submitted', '获得有效订单号或 seq，不代表成交；最终状态继续看原回调。'],
    ['execution / qmt_submit_ms', 'execution 为 qmt；qmt_submit_ms 是 QMT 内部提交循环耗时，不含通信及同步编号解析。'],
    ['failed', 'QMT 明确拒绝；stop_on_error=True 时停止后续提交。'],
    ['unknown', '同步编号未确认、整批回包异常或本地下单异常；先核对原查询和回调。'],
    ['skipped', '本次未调用该笔下单，不会自动补发。'],
  ];
  const batchCancelReturns = [
    ['batch_id / account / asynchronous', '批次 ID、账号和是否异步。'],
    ['ok / total / attempted', '全部撤单请求提交成功时 ok 为 True；总笔数和已尝试笔数。'],
    ['submitted / failed / unknown / skipped', '四种逐笔状态的数量，合计等于 total。'],
    ['results', '与输入等长、顺序一致。每行包含 index、order_id、stock_code、market、status、ok、seq、cancel_result、error。'],
    ['submitted', 'QMT 已确认撤单请求调用成功；最终是否撤成仍以委托状态或撤单错误回调为准。'],
    ['cancel_result', '同步和异步行都会保留 QMT 撤单调用结果；当前大 QMT cancel 返回 True 时映射为 0。'],
    ['unknown', '回包丢失或 QMT 本地异常时无法确定真实执行情况；先查委托状态再重试。'],
  ];
  const benchmarkNote = '100 单本机假 QMT 基准（2026-09-11，Python 3.12.4，5 次预热、30 次采样）：批量同步中位 4.802 ms，单笔同步循环中位 9.169 ms；批量异步中位 7.093 ms，单笔异步循环中位 9.053 ms。该基准不连接真实 QMT，不代表券商柜台耗时。模拟账号 900010001595 实测（Web LTtx 路由，600000.SH，100 股路径）：批量同步 963.252 ms，单笔同步循环 23250.174 ms；批量异步 52.578 ms，单笔异步循环 2952.912 ms，四组均 submitted=100，复核 400 单均已撤。';

  function orderExample(method, batch, asynchronous) {
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
    const argumentsCode = batch
      ? `account, orders, strategy_name="rebalance", stop_on_error=True`
      : `account, "600000.SH", xtconstant.STOCK_BUY, 100,
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

  function cancelExample(method, asynchronous) {
    const callback = asynchronous ? `
class Callback(XtQuantTraderCallback):
    def on_cancel_order_stock_async_response(self, response):
        print("cancel response:", response.seq, response.order_id, response.cancel_result)

    def on_cancel_error(self, error):
        print("cancel error:", error)
` : '';
    return `from cfquant import cftrader
from cfquant.xttrader import XtQuantTrader${asynchronous ? ', XtQuantTraderCallback' : ''}
from cfquant.xttype import StockAccount
${callback}
ENABLE_TRADING = False
account = StockAccount("YOUR_ACCOUNT_ID", "STOCK")
order_ids = [
    dict(order_id="1001", stock_code="600000.SH"),
    dict(order_id="1002", market="SZ"),
]
trader = XtQuantTrader("", 0)
orders_api = cftrader.CfQuantTrader(trader)
if ENABLE_TRADING:
    try:
${asynchronous ? '        trader.register_callback(Callback())\n' : ''}        trader.start()
        if trader.connect() != 0 or trader.subscribe(account) != 0:
            raise RuntimeError("Connection or subscription failed")
        result = orders_api.${method}(
            account, order_ids, stop_on_error=False,
        )
        print(result)
${asynchronous ? '        trader.run_forever()\n    except KeyboardInterrupt:\n        pass\n' : ''}    finally:
        trader.stop()
else:
    print("Preview only; trading is disabled")`;
  }

  const entries = [
    { method: 'order_stock_batch', title: '批量同步下单', batch: true, asynchronous: false, operation: 'order' },
    { method: 'order_stock_batch_async', title: '批量异步下单', batch: true, asynchronous: true, operation: 'order' },
    { method: 'cancel_order_stock_batch', title: '批量同步撤单', batch: true, asynchronous: false, operation: 'cancel' },
    { method: 'cancel_order_stock_batch_async', title: '批量异步撤单', batch: true, asynchronous: true, operation: 'cancel' },
    { method: 'order_stock', title: '单笔同步下单', batch: false, asynchronous: false, operation: 'order' },
    { method: 'order_stock_async', title: '单笔异步下单', batch: false, asynchronous: true, operation: 'order' },
  ];

  window.CFQUANT_CFTRADER_API = entries.map(({ method, title, batch, asynchronous, operation }) => {
    const cancel = operation === 'cancel';
    const batchSignature = cancel
      ? 'account, order_ids, stop_on_error=False'
      : 'account, orders, strategy_name="", order_remark="", stop_on_error=False';
    const singleSignature = 'account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""';
    return {
      id: 'cftrader.' + method,
      name: method,
      module: 'cftrader',
      group: '独立下单与撤单接口',
      status: 'extension',
      operation,
      title,
      description: batch
        ? (cancel
          ? `一次批量 RPC 将整批撤单请求发送到大 QMT，QMT 内部连续调用 cancel。${asynchronous ? '提交后返回逐笔 seq 和受理状态，撤单反馈继续走原回调。' : '整批提交后返回逐笔撤单调用结果。'}`
          : `一次批量 RPC 将整批订单发送到大 QMT，QMT 内部连续调用 passorder。${asynchronous ? '提交后返回逐笔 seq 和受理状态，订单号继续走原回调。' : '整批提交后集中解析订单号，返回逐笔结果。'}`)
        : `使用原 XtQuantTrader.${method} 的参数和返回值。`,
      signature: `CfQuantTrader.${method}(${batch ? batchSignature : singleSignature})`,
      parameters: batch
        ? (cancel ? [account, cancelList, stopOnError] : [account, parameter('orders', '非空列表或元组，每笔为下单字段组成的字典；完整校验通过后一次性发送到 QMT。'), strategy, remark, stopOnError])
        : [account, ...orderFields, strategy, remark],
      orderFields: batch && !cancel ? [...orderFields, strategy, remark] : [],
      resultRows: batch ? (cancel ? batchCancelReturns : batchOrderReturns) : [[asynchronous ? 'seq' : 'order_id', '沿用原单笔接口的返回值及错误语义。']],
      resultHelp: batch
        ? (cancel
          ? `同步和异步批量撤单都会返回逐笔状态；异步行保留预分配 seq，并继续触发原 on_cancel_order_stock_async_response。只有 submitted 代表撤单请求已被 QMT 调用接受，不代表原委托已经处于已撤状态。`
          : `同步成功行填充 order_id；异步所有行保留预分配 seq，另一个编号字段为 None，index 从 0 开始。只要 submitted 代表确认受理，不代表成交。异步回调可能早于批量返回，使用 order_remark、seq 和 order_id 关联。`)
        : `返回${asynchronous ? '请求序号 seq' : '订单号 order_id'}；最终委托、成交和错误仍从原 XtQuantTraderCallback 接收。`,
      note: batch
        ? `${benchmarkNote} 批量接口的目的，是减少外部 Python 与 Web/LTtx/ctypes/QMT 之间逐笔往返，把循环执行放到 QMT 本地。批量不是柜台原子事务，已提交请求不会因后续失败自动撤回；超时或回包丢失时标记 unknown，先查询委托和回调再重试。独立市场路由按输入顺序分段，每个连续目标市场段发往对应 QMT。`
        : `${benchmarkNote} cfquant 自有 Python SDK 扩展，单笔下单直接复用原 trader。`,
      usage: 'from cfquant import cftrader 后，用 cftrader.CfQuantTrader(trader) 包装已有 XtQuantTrader。连接、订阅、查询、单笔撤单和回调继续由原 trader 管理；批量下单和批量撤单通过 cftrader 的扩展方法进入 QMT 内部批量执行协议。',
      example: cancel ? cancelExample(method, asynchronous) : orderExample(method, batch, asynchronous),
      related: batch
        ? entries.filter(item => item.batch && item.operation === operation && item.method !== method).map(item => 'cftrader.' + item.method)
        : ['cftrader.order_stock_batch', 'cftrader.order_stock_batch_async', 'cftrader.cancel_order_stock_batch', 'cftrader.cancel_order_stock_batch_async'],
    };
  });
})();
