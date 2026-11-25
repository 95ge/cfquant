"""Project-authored native QMT examples; no live requests at generation time."""
import textwrap

PARAMETER_HELP = {
    'bridge_id': '内部通道覆盖项；仅直连或同账号多绑定时使用。通过独立中心 A 通常不需要填写。',
    'account_id': '可选字符串，填写 cfquant“账号绑定”中登记的券商资金账号。例如 "12345678"（仅格式示例），请保留账号的前导零；省略时使用当前设置的行情源。',
    'account_type': '账号类型：普通证券账户填 "STOCK"，信用账户填 "CREDIT"；应与 cfquant“账号绑定”中的类型一致。',
    'account_key': '可选的完整绑定键；同一资金账号有多个绑定时，用它指定具体绑定。通常填写 account_id 和 account_type 即可。',
    'transport': '默认 auto 与 center 均通过 LTtx 连接独立中心 A；旧的 web_lttx 等别名映射到 A。ctypes、lttx 仅供显式直连。',
    'request_channel': '直连时需要明确指定普通桥频道；通过独立中心 A 通常自动选择。',
    'timeout': '单次 RPC 等待秒数；超时不会自动重发交易。',
    'client': '可注入已有 RPC 客户端；关闭会话时不关闭外部传入的连接。',
    'accountid': 'QMT 原生账号 ID。', 'accountID': 'QMT 原生账号 ID。', 'accountId': 'QMT 原生账号 ID。',
    'strAccountType': '原生账号类型，如 stock、credit。', 'accountType': '原生账号类型，如 stock、credit。',
    'strDatatype': '查询类别，如 account、position、order、deal。',
    'strategyName': '按策略名称过滤；省略时使用原生三参数重载。',
    'fields': '需要的行情字段列表，例如 close、volume。',
    'stock_code': '证券代码或列表，具体形式按方法要求，如 000001.SZ。',
    'stockcode': '带市场后缀的证券代码，如 000001.SZ。',
    'code_list': '全推订阅使用的市场或证券列表。',
    'period': '原生 K 线周期；follow 跟随桥接策略周期。',
    'start_time': '查询开始时间；空字符串由原生接口解释。',
    'end_time': '查询结束时间；空字符串由原生接口解释。',
    'start_date': '开始日期，例如 20260101。', 'end_date': '结束日期，例如 20261105。',
    'count': '返回条数；-1 的含义沿用对应 QMT 接口。',
    'dividend_type': '原生复权方式；follow 跟随策略设置。', 'fill_data': '是否填充缺失行情。',
    'subscribe': '是否同时订阅行情更新。', 'callback': '外部 Python 回调函数。',
    'result_type': '沿用终端支持的行情回调结果类型。', 'subId': '本会话订阅返回的订阅编号。',
    'func': '定时回调，接收当前 qmt.context 代理。',
    'time_point': '首次触发的本地时间；datetime 不应带时区。',
    'repeat_times': '首次触发后的重复次数；-1 为持续重复。',
    'interval': '重复间隔，使用 datetime.timedelta。', 'name': '定时任务组名称。',
    'key': 'schedule_run 返回的任务编号，或需取消的任务组名。',
    'opType': '大 QMT 原生交易操作类型。', 'orderType': '大 QMT 原生委托方式。',
    'orderCode': '证券、组合或合约代码。', 'prType': '大 QMT 原生报价类型。',
    'price': '原生报价参数。', 'volume': '数量、金额或比例，含义由 orderType 决定。',
    'orderId': '从原生委托查询或回调取得的委托编号。',
}

SESSION_HELP = ('以下参数在创建 QmtInnerApi(...) 时传入，该会话下的所有接口共用。'
                'account_id 可省略；省略时独立中心 A 使用当前设置的行情源。'
                '填写时请使用 cfquant“账号绑定”中的券商资金账号。')
ACCOUNT_EXAMPLE_COMMENT = ('# 将 YOUR_ACCOUNT_ID 替换为 cfquant“账号绑定”中的券商资金账号（字符串，保留前导零）\n'
                           '# account_type 与绑定一致：普通证券账户 STOCK，信用账户 CREDIT\n')

QUERIES = {
    'system.get_stock_name': 'qmt.system.get_stock_name("000001.SZ")',
    'system.get_open_date': 'qmt.system.get_open_date("000001.SZ")',
    'system.get_universe': 'qmt.system.get_universe()',
    'system.get_sector_list': 'qmt.system.get_sector_list("")',
    'market.get_full_tick': 'qmt.market.get_full_tick(["000001.SZ", "600000.SH"])',
    'market.get_market_data_ex': 'qmt.market.get_market_data_ex(["close", "volume"], ["000001.SZ"], period="1d", count=3, subscribe=False)',
    'market.get_instrument_detail': 'qmt.market.get_instrument_detail("000001.SZ")',
    'market.get_stock_list_in_sector': 'qmt.market.get_stock_list_in_sector("沪深A股")',
    'market.get_trading_dates': 'qmt.market.get_trading_dates("000001.SZ", "20261101", "20261105", 5)',
    'market.get_divid_factors': 'qmt.market.get_divid_factors("000001.SZ")',
    'market.get_etf_info': 'qmt.market.get_etf_info("510050.SH")',
    'trade.get_ipo_data': 'qmt.trade.get_ipo_data()',
    'trade.get_new_purchase_limit': 'qmt.trade.get_new_purchase_limit("YOUR_ACCOUNT_ID")',
}


def session(body, imports=''):
    return ('from cfquant import QmtInnerApi\n' + imports + '\n' + ACCOUNT_EXAMPLE_COMMENT +
            'with QmtInnerApi(account_id="YOUR_ACCOUNT_ID", account_type="STOCK") as qmt:\n'
            + textwrap.indent(body, '    '))


def example_for(category, name):
    key = category + '.' + name
    if key in QUERIES:
        return session('result = ' + QUERIES[key] + '\nprint(result)'), 'Python 调用示例'
    if name in ('QmtInnerApi', 'capabilities'):
        return session('capabilities = qmt.capabilities()\nprint(capabilities)\n'
                       'print(qmt.market.get_full_tick(["000001.SZ"]))'), '连接与能力查询示例'
    if name == 'close':
        return ('from cfquant import QmtInnerApi\n\n' + ACCOUNT_EXAMPLE_COMMENT +
                'qmt = QmtInnerApi(account_id="YOUR_ACCOUNT_ID", account_type="STOCK")\n'
                'try:\n    print(qmt.capabilities())\nfinally:\n    qmt.close()'), '会话清理示例'
    if name == 'get_trade_detail_data':
        return session('rows = qmt.trade.get_trade_detail_data("YOUR_ACCOUNT_ID", "stock", "position")\n'
                       'for row in rows:\n    print(row.m_strInstrumentID, row.m_nVolume)'), '原生持仓查询示例'
    if name in ('subscribe_quote', 'subscribe_whole_quote', 'unsubscribe_quote'):
        subscribe = ('qmt.market.subscribe_whole_quote(["000001.SZ"], callback=print)' if name == 'subscribe_whole_quote'
                     else 'qmt.market.subscribe_quote("000001.SZ", period="tick", callback=print)')
        return session('sub_id = ' + subscribe + '\ntry:\n    threading.Event().wait(10)\n'
                       'finally:\n    qmt.market.unsubscribe_quote(sub_id)', 'import threading\n'), '行情订阅与清理示例'
    if name in ('schedule_run', 'cancel_schedule_run'):
        return session('task_id = qmt.system.schedule_run(\n'
                       '    lambda C: print(C.barpos), datetime.now(), -1, timedelta(seconds=2), "external_timer")\n'
                       'try:\n    threading.Event().wait(6)\nfinally:\n    qmt.system.cancel_schedule_run(task_id)',
                       'import threading\nfrom datetime import datetime, timedelta\n'), '定时回调与清理示例'
    if category == 'callbacks':
        return session('def on_event(C, *native_args):\n    print(native_args)\n\n'
                       'qmt.callbacks.' + name + '(on_event)\n'
                       'try:\n    threading.Event().wait(60)\nfinally:\n'
                       '    qmt.callbacks.unregister("' + name + '")', 'import threading\n'), '原生回调注册示例'
    if name in ('passorder', 'cancel'):
        operation = ('qmt.trade.passorder(23, 1101, "YOUR_ACCOUNT_ID", "000001.SZ", 11, 10.0, 100)' if name == 'passorder'
                     else 'qmt.trade.cancel("ORDER_ID_FROM_QUERY", "YOUR_ACCOUNT_ID", "stock")')
        return session('ENABLE_TRADING = False\nif ENABLE_TRADING:\n    result = ' + operation + '\n    print(result)'), '交易调用示例（默认关闭）'
    # A runnable capability check is explicit about its scope. Do not invent
    # arguments for terminal-specific models, overloads or trading operations.
    return session('available = qmt.capabilities()["' + category + '"]["' + name + '"]\n'
                   'print("' + key + '", available)'), '能力检查示例（不执行该函数）'
