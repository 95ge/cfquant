"""Independently authored migration examples for the offline Python reference."""

from textwrap import indent


PARAMETERS = {
    "stock_code": "证券代码字符串，包含市场后缀，例如 600000.SH。",
    "stockcode": "证券代码字符串；此拼写与 stock_code 不同，按当前签名传参。",
    "stock_list": "证券代码列表，例如 ['600000.SH', '000001.SZ']。",
    "stock_codes": "批量计算使用的证券代码列表。",
    "code_list": "证券代码或市场列表；全推接口可使用 SH、SZ。",
    "period": "数据周期，例如 tick、1m、5m、1d；其他周期需终端及数据权限支持。",
    "start_time": "起始日期或时间，常用 YYYYMMDD、YYYYMMDDHHMMSS；空串使用接口默认范围。",
    "end_time": "结束日期或时间，格式与 start_time 对应。",
    "start_date": "起始日期字符串，例如 20260101。",
    "end_date": "结束日期字符串，例如 20260331。",
    "count": "记录条数。历史查询常用 -1 表示不按条数截断，具体默认值见签名。",
    "callback": "Python 可调用对象；行情接收数据，异步查询接收查询结果，交易使用回调类。",
    "seq": "订阅或请求返回的序号；不是交易委托编号。",
    "subID": "模型订阅返回的标识。",
    "field_list": "要读取的字段名列表；财务接口在 cfquant 中需使用终端支持的表名.字段名。",
    "table_list": "财务表名列表，例如 Balance、Income；不等于 cfquant 的 field_list。",
    "dividend_type": "复权选项：none、front、back、front_ratio、back_ratio。",
    "fill_data": "是否按接口规则补齐缺少的行情记录。",
    "data_dir": "原版本地数据目录；cfquant 不实现 MiniQMT 目录切换。",
    "incrementally": "是否增量下载；None 使用终端/接口的默认策略。",
    "iscomplete": "是否请求完整合约字段；具体字段可用性取决于终端。",
    "report_type": "财务日期口径：report_time 按报告期，announce_time 按披露时间。",
    "market": "行情通常用 SH/SZ 字符串；交易使用 xtconstant 的市场枚举。",
    "sector_name": "终端中的板块名称；修改时使用已确认的自定义板块。",
    "parent_node": "板块树父节点名称。",
    "folder_name": "待创建的板块目录名称。",
    "overwrite": "遇到同名板块或目录时是否允许覆盖。",
    "real_timetag": "历史成分时点，整数毫秒时间戳；-1 读取当前成分。",
    "index_code": "指数代码，含市场后缀。",
    "formula_name": "终端中已存在的 VBA 模型名称。",
    "formula_names": "批量调用的模型名称列表。",
    "extend_param": "模型扩展参数字典。",
    "extend_params": "批量模型使用的扩展参数列表。",
    "formula_param": "模型运行参数字典。",
    "fill_mode": "因子空值填充方式。",
    "fill_value": "因子结果的空值替代值。",
    "result_path": "原版接口输出文件所在的路径。",
    "path": "原版 MiniQMT 的 userdata_mini 路径；cfquant 保留该参数但使用桥配置连接。",
    "session_id": "会话整数标识；cfquant 传 0 时会生成正整数。",
    "account": "StockAccount 对象，账号和账户类型必须与当前运行的桥绑定一致。",
    "account_id": "字符串形式的资金账号，保留可能存在的前导零。",
    "account_type": "账户类型，例如 STOCK、CREDIT、FUTURE。",
    "enabled": "布尔开关；是否实现开关控制的行为需看下方适配状态。",
    "order_type": "买卖类型枚举，例如 xtconstant.STOCK_BUY。",
    "order_volume": "委托数量，使用证券业务规定的数量单位。",
    "price_type": "报价类型枚举，例如 xtconstant.FIX_PRICE。",
    "price": "委托价格；资金划拨接口中表示划拨金额。",
    "strategy_name": "策略标识字符串，用于识别本策略委托。",
    "order_remark": "委托备注字符串，宜使用可追踪且不重复的标识。",
    "order_id": "真实委托编号；应从委托查询或委托回报获得，不可用异步 seq 代替。",
    "order_sysid": "柜台合同编号；cfquant 当前关键字为 sysid，市场和编号语义部分适配。",
    "sysid": "柜台合同编号；请核对当前桥和券商的识别规则。",
    "cancelable_only": "True 只查询可撤委托，False 查询当日全部委托。",
    "transfer_direction": "资金划拨方向枚举。",
    "operation": "外部成交导入操作类型。",
    "data_type": "终端支持的查询、导出或导入业务类型。",
    "deal_list": "外部成交记录列表，记录字段按目标业务定义。",
    "user_param": "通用业务接口的扩展参数字典。",
    "src_group_id": "约券券源分组标识。",
    "order_code": "约券证券代码。",
    "date": "约券业务使用的日期或期限参数，以对应业务原文为准。",
    "amount": "业务申请数量；行情字段中表示成交额。",
    "apply_rate": "约券申请费率。",
    "dict_param": "约券业务附加参数字典。",
    "data": "事件数据对象；可用字段见对应交易数据结构。",
    "time": "整数时间戳，行情常用毫秒。",
    "lastPrice": "最新成交价。", "open": "开盘价。", "high": "区间最高价。",
    "low": "区间最低价。", "close": "收盘价。", "lastClose": "前收盘价。",
    "volume": "成交量；单位按数据周期和业务定义核对。",
    "cash": "可用资金。", "total_asset": "总资产。", "market_value": "持仓市值。",
    "stockCode": "证券代码。", "bondConvPrice": "转股价格。",
}


def parameter_help(name, fallback="参数取值和业务限制见对应讯投原文。"):
    return PARAMETERS.get(name, fallback)


def trader_example(body, account_type="STOCK", callback="", wait=False):
    code = 'import time\nfrom cfquant import xtconstant\nfrom cfquant.xttrader import XtQuantTrader, XtQuantTraderCallback\nfrom cfquant.xttype import StockAccount\n\n'
    if callback:
        code += callback + "\n\n"
    code += 'account = StockAccount("YOUR_ACCOUNT_ID", "' + account_type + '")\n'
    code += 'trader = XtQuantTrader("", int(time.time()))\ntry:\n'
    if callback:
        code += '    trader.register_callback(Callback())\n'
    code += '    trader.start()\n    if trader.connect() != 0:\n        raise RuntimeError("cfquant bridge connection failed")\n    if trader.subscribe(account) != 0:\n        raise RuntimeError("account subscription failed")\n'
    code += indent(body, "    ") + "\n"
    if wait:
        code += '    trader.run_forever()\nexcept KeyboardInterrupt:\n    pass\n'
    code += 'finally:\n    trader.stop()'
    return code


MARKET_BODIES = {
    "get_full_tick": 'ticks = xtdata.get_full_tick(["600000.SH", "000001.SZ"])\nfor code, tick in (ticks or {}).items():\n    print(code, tick.get("lastPrice"), tick.get("time"))',
    "get_market_data": 'data = xtdata.get_market_data(\n    field_list=["open", "close", "volume"], stock_list=["600000.SH"],\n    period="1d", count=10)\n# Inspect the bridge result before indexing: field layout may differ.\nprint(type(data), data)',
    "get_market_data_ex": 'data = xtdata.get_market_data_ex(\n    field_list=["open", "close", "volume"], stock_list=["600000.SH"],\n    period="1d", count=10)\nfor code, frame in (data or {}).items():\n    print(code, frame.tail() if hasattr(frame, "tail") else frame)',
    "get_local_data": 'data = xtdata.get_local_data(\n    field_list=["close"], stock_list=["600000.SH"],\n    period="1d", start_time="20260101", end_time="20260131")\n# Empty local data stays empty; this read does not subscribe.\nprint(data)',
    "get_divid_factors": 'factors = xtdata.get_divid_factors(\n    "600000.SH", start_time="20250101", end_time="20261231")\nprint(factors)\nprint(factors.index.dtype, list(factors.columns))',
    "download_history_data": 'result = xtdata.download_history_data(\n    "600000.SH", "1d", start_time="20260101", end_time="20260131")\nprint("download:", result)\nprint(xtdata.get_market_data_ex(\n    stock_list=["600000.SH"], period="1d",\n    start_time="20260101", end_time="20260131"))',
    "download_history_data2": 'def on_progress(event):\n    # cfquant also reports lifecycle events; inspect their actual fields.\n    print("download event:", event)\n\nresult = xtdata.download_history_data2(\n    ["600000.SH", "000001.SZ"], "1d",\n    start_time="20260101", end_time="20260131", callback=on_progress)\nprint("download result:", result)',
    "get_instrument_detail": 'detail = xtdata.get_instrument_detail("600000.SH", iscomplete=False)\nprint(detail)\nif detail:\n    print("partial:", detail.get("cfquant_detail_partial"))\n    print("fallback:", detail.get("cfquant_detail_fallback"))',
    "get_cb_info": 'info = xtdata.get_cb_info("113042.SH")\nif info:\n    print(info.get("stockCode"), info.get("bondConvPrice"))\n    print("partial:", info.get("cfquant_partial"))\nelse:\n    print("No current bond information")',
    "get_sector_list": 'sectors = xtdata.get_sector_list()\nprint(sectors)',
    "get_stock_list_in_sector": 'stocks = xtdata.get_stock_list_in_sector("沪深A股", real_timetag=-1)\nprint(stocks)',
    "get_trading_dates": 'dates = xtdata.get_trading_dates(\n    stockcode="600000.SH", start_date="20260101",\n    end_date="20260131", count=-1, period="1d")\nprint(dates)',
    "get_financial_data": 'data = xtdata.get_financial_data(\n    field_list=["ASHAREBALANCESHEET.fix_assets"],\n    stock_list=["600000.SH"], start_time="20240101", end_time="20251231",\n    report_type="announce_time")\n# Field identifiers come from the target QMT financial database.\nprint(type(data), data)',
    "reset_sector": 'ENABLE_SECTOR_WRITE = False\nif not ENABLE_SECTOR_WRITE:\n    raise RuntimeError("Confirm the custom sector before enabling writes")\nresult = xtdata.reset_sector("CFQUANT_DEMO", ["600000.SH", "000001.SZ"])\nprint("reset result:", result)\nprint(xtdata.get_stock_list_in_sector("CFQUANT_DEMO"))',
    "remove_stock_from_sector": 'ENABLE_SECTOR_WRITE = False\nif not ENABLE_SECTOR_WRITE:\n    raise RuntimeError("Confirm the custom sector before enabling writes")\ntry:\n    print(xtdata.remove_stock_from_sector("CFQUANT_DEMO", ["600000.SH"]))\nfinally:\n    # A failure may follow partial changes. Check actual membership.\n    print(xtdata.get_stock_list_in_sector("CFQUANT_DEMO"))',
}

QUERY_BODIES = {
    "query_stock_asset": 'asset = trader.query_stock_asset(account)\nif asset is None:\n    print("No asset record")\nelse:\n    print(asset.account_id, asset.cash, asset.total_asset)',
    "query_stock_orders": 'orders = trader.query_stock_orders(account, cancelable_only=False)\nfor order in orders or []:\n    print(order.order_id, order.stock_code, order.order_status)',
    "query_stock_trades": 'for trade in trader.query_stock_trades(account) or []:\n    print(trade.order_id, trade.stock_code, trade.traded_price, trade.traded_volume)',
    "query_stock_positions": 'for position in trader.query_stock_positions(account) or []:\n    print(position.stock_code, position.volume, position.can_use_volume)',
    "query_stock_order": 'order = trader.query_stock_order(account, "YOUR_ORDER_ID")\nprint(order)',
    "query_stock_position": 'position = trader.query_stock_position(account, "600000.SH")\nprint(position)',
    "query_stock_orders_async": 'from threading import Event\nfinished = Event()\n\ndef on_result(orders):\n    print("orders:", orders)\n    finished.set()\n\nseq = trader.query_stock_orders_async(account, on_result, cancelable_only=True)\nprint("request seq:", seq)\nif not finished.wait(15):\n    raise TimeoutError("No query callback; inspect cfquant.xttrader logs")',
    "query_position_statistics": 'records = trader.query_position_statistics(account)\nif records is None:\n    print("No result from the terminal")\nelse:\n    for record in records:\n        print(getattr(record, "instrument_id", None),\n              getattr(record, "position", None),\n              getattr(record, "position_profit", None))',
    "query_credit_subjects": 'for item in trader.query_credit_subjects(account) or []:\n    print(getattr(item, "instrument_id", None),\n          getattr(item, "fin_status", None), getattr(item, "slo_status", None))',
    "query_credit_slo_code": 'for item in trader.query_credit_slo_code(account) or []:\n    print(getattr(item, "instrument_id", None),\n          getattr(item, "enable_amount", None), getattr(item, "cashgroup_prop", None))',
    "query_credit_assure": 'for item in trader.query_credit_assure(account) or []:\n    print(getattr(item, "instrument_id", None),\n          getattr(item, "assure_status", None), getattr(item, "assure_ratio", None))',
    "query_new_purchase_limit": 'limits = trader.query_new_purchase_limit(account)\nprint(type(limits), limits)',
    "query_ipo_data": 'ipos = trader.query_ipo_data()\nprint(type(ipos), ipos)',
    "query_com_fund": 'fund = trader.query_com_fund(account)\nprint(type(fund), fund)',
    "query_com_position": 'positions = trader.query_com_position(account)\nprint(type(positions), positions)',
}

CALLBACK_FIELDS = {
    "on_disconnected": None,
    "on_account_status": ["account_id", "status"],
    "on_stock_order": ["order_id", "stock_code", "order_status"],
    "on_stock_trade": ["order_id", "stock_code", "traded_price", "traded_volume"],
    "on_order_error": ["order_id", "error_id", "error_msg"],
    "on_cancel_error": ["order_id", "error_id", "error_msg"],
    "on_order_stock_async_response": ["seq", "order_id", "order_remark"],
    "on_cancel_order_stock_async_response": ["seq", "order_id", "cancel_result"],
}


def callback_class(name):
    fields = CALLBACK_FIELDS[name]
    params = "self, data" if fields else "self"
    body = 'print("' + name + '")'
    if fields:
        body += '\n        print(' + ',\n              '.join('getattr(data, "' + f + '", None)' for f in fields) + ')'
    return 'class Callback(XtQuantTraderCallback):\n    def ' + name + '(' + params + '):\n        ' + body


TYPE_QUERIES = {
    "XtAsset": "query_stock_asset", "XtOrder": "query_stock_orders", "XtTrade": "query_stock_trades",
    "XtPosition": "query_stock_positions", "XtPositionStatistics": "query_position_statistics",
    "CreditSubjects": "query_credit_subjects", "CreditSloCode": "query_credit_slo_code", "CreditAssure": "query_credit_assure",
}
TYPE_CALLBACKS = {
    "XtOrderResponse": "on_order_stock_async_response", "XtCancelOrderResponse": "on_cancel_order_stock_async_response",
    "XtOrderError": "on_order_error", "XtCancelError": "on_cancel_error",
}


def original_example(code, name):
    code = code.replace("from cfquant", "from xtquant").replace('XtQuantTrader("",', 'XtQuantTrader(r"D:\\QMT\\userdata_mini",')
    code = code.replace("cfquant bridge connection failed", "MiniQMT connection failed")
    if name == "get_financial_data":
        code = 'from xtquant import xtdata\n\ndata = xtdata.get_financial_data(\n    stock_list=["600000.SH"], table_list=["Balance"],\n    start_time="20240101", end_time="20251231", report_type="announce_time")\nprint(data)'
    elif name == "get_trading_dates":
        code = 'from xtquant import xtdata\n\ndates = xtdata.get_trading_dates(\n    market="SH", start_time="20260101", end_time="20260131", count=-1)\nprint(dates)'
    elif name in ("cancel_order_stock_sysid", "cancel_order_stock_sysid_async"):
        code = code.replace("sysid=", "order_sysid=")
    return code


def example_for(entry):
    name, module = entry["name"], entry["module"]
    if entry["status"] not in ("supported", "partial"):
        return {"example": "", "originalExample": "", "usage": "尚未支持。当前不提供可用的 cfquant 替代调用；条件入口也不视为已完成适配。"}
    code, usage = "", "示例运行前需完成 Web 账号绑定，并在大 QMT 中启动对应桥策略。"
    if module == "xtdata":
        if name in ("subscribe_quote", "subscribe_whole_quote", "unsubscribe_quote", "run"):
            call = 'xtdata.subscribe_whole_quote(["600000.SH", "000001.SZ"], callback=on_quote)' if name == "subscribe_whole_quote" else 'xtdata.subscribe_quote("600000.SH", period="tick", callback=on_quote)'
            body = 'def on_quote(data):\n    print(data)\n\nseq = ' + call + '\nif seq is None or int(seq) <= 0:\n    raise RuntimeError("Quote subscription failed")\ntry:\n    xtdata.run()\nexcept KeyboardInterrupt:\n    pass\nfinally:\n    xtdata.unsubscribe_quote(seq)'
            usage += " 行情变化通过 on_quote 到达；退出时按订阅号清理订阅。"
        else:
            body = MARKET_BODIES[name]
        code = 'from cfquant import xtdata\n\n' + body
    elif module == "callback":
        code = trader_example('print("Waiting for account events")', callback=callback_class(name), wait=True)
        usage += " 回调由事件触发，注册和订阅本身不会生成成交或报错事件；异步报单回报只关联本实例提交的异步订单。"
    elif module == "trader":
        if name in QUERY_BODIES:
            account_type = "FUTURE" if name == "query_position_statistics" else "CREDIT" if name.startswith("query_credit_") else "STOCK"
            code = trader_example(QUERY_BODIES[name], account_type=account_type)
        elif name.startswith("order_stock"):
            body = 'ENABLE_TRADING = False\nif not ENABLE_TRADING:\n    raise RuntimeError("Confirm account, security, volume and price before enabling trading")\n'
            body += 'result = trader.' + name + '(\n    account, "600000.SH", xtconstant.STOCK_BUY, 100,\n    xtconstant.FIX_PRICE, 10.00, "cfquant_demo", "manual_confirmed")\nprint("' + ("request seq" if name.endswith("async") else "order id") + ':", result)'
            code = trader_example(body, callback=callback_class("on_order_stock_async_response" if name.endswith("async") else "on_stock_order"), wait=True)
            usage += " 示例默认禁止报单。启用后会提交真实委托，示例价格不是投资建议；异步返回 seq，成交以回报为准。"
        elif name.startswith("cancel_order_stock"):
            body = 'ENABLE_CANCEL = False\nTARGET_ORDER_ID = "YOUR_ORDER_ID"\norders = trader.query_stock_orders(account, cancelable_only=True) or []\ntarget = next((o for o in orders if str(o.order_id) == TARGET_ORDER_ID), None)\nif target is None:\n    raise RuntimeError("Target is not in this account cancellable orders")\nif not ENABLE_CANCEL:\n    raise RuntimeError("Confirm this order before enabling cancellation")\n'
            if "sysid" in name:
                body += 'sysid = getattr(target, "order_sysid", "")\nif not sysid:\n    raise RuntimeError("Missing confirmed counter order identifier")\n# This example is limited to a confirmed SH-market order.\nif not target.stock_code.endswith(".SH"):\n    raise RuntimeError("Market does not match this example")\nresult = trader.' + name + '(account, market=xtconstant.SH_MARKET, sysid=sysid)'
            else:
                body += 'result = trader.' + name + '(account, target.order_id)'
            body += '\nprint("cancel request result:", result)'
            code = trader_example(body, callback=callback_class("on_cancel_order_stock_async_response" if name.endswith("async") else "on_stock_order"), wait=True)
            usage += " 示例默认禁止撤单。撤单返回值表示请求结果，最终状态需核对委托回报。"
        else:
            body = {"XtQuantTrader": 'print("session:", trader.session_id)',
                    "register_callback": 'print("Callback registered before start")',
                    "start": 'print("API started and connected")',
                    "connect": 'print("Bridge connection succeeded")',
                    "stop": 'print("The finally block stops the trader")',
                    "run_forever": 'print("Waiting; interrupt the process to stop")',
                    "subscribe": 'print("Account subscribed:", account.account_id)',
                    "unsubscribe": 'print("unsubscribe:", trader.unsubscribe(account))'}[name]
            code = trader_example(body, callback=callback_class("on_stock_order") if name == "register_callback" else "", wait=name in ("register_callback", "run_forever"))
    elif module == "type":
        usage = "这些字段属于返回对象或输入账号对象。数据结构已适配不代表所有返回它的业务接口均已适配；缺失字段不能当作数值 0。"
        if name == "StockAccount":
            code = 'from cfquant.xttype import StockAccount\n\naccount = StockAccount("YOUR_ACCOUNT_ID", "STOCK")\ncredit = StockAccount("YOUR_CREDIT_ACCOUNT_ID", "CREDIT")\nprint(account.account_id, account.account_type)\nprint(credit.account_id, credit.account_type)'
        elif name in TYPE_QUERIES:
            query = TYPE_QUERIES[name]
            code = trader_example(QUERY_BODIES[query], account_type="FUTURE" if name == "XtPositionStatistics" else "CREDIT" if name.startswith("Credit") else "STOCK")
        elif name in TYPE_CALLBACKS:
            code = trader_example('print("Waiting for events carrying ' + name + '")', callback=callback_class(TYPE_CALLBACKS[name]), wait=True)
        else:
            code = 'from cfquant.xttype import ' + name + '\n\n# Local object demonstration only; this does not submit a business request.\nraw = {"account_id": "DEMO_ACCOUNT"}\nrecord = ' + name + '.from_any(raw)\nprint(record.account_id)\nprint(vars(record))'
            usage += " 下方仅演示本地对象包装，不模拟终端成功回报。"
    result_help = {
        "subscribe_quote": "返回订阅号，正整数表示成功。回调的数据按证券代码组织；保存订阅号用于反订阅。",
        "subscribe_whole_quote": "返回订阅号。行情变化由回调接收，非交易时间没有变化时可能没有推送。",
        "unsubscribe_quote": "取消远端订阅并清理本地回调；不要继续使用已取消的订阅号。",
        "run": "保持行情事件接收，通常不主动返回；cfquant 不保证断线时抛异常退出。",
        "get_full_tick": "按证券代码组织的字典；每个证券对应一条快照。空字典或缺少某证券时不要构造虚假的最新价。",
        "get_market_data": "直接保留当前桥的底层返回结构；不能假定始终是原版按字段组织的 DataFrame 字典。",
        "get_market_data_ex": "扩展行情通常按证券代码组织 DataFrame。没有相应本地数据、订阅或权限时，可能得到空结果。",
        "get_local_data": "保留本地查询结果与空数据状态。data_dir 不会切换到某个 MiniQMT 数据目录。",
        "get_divid_factors": "七列 pandas.DataFrame，以整数毫秒时间戳为索引；日期边界按北京时间解释。",
        "get_cb_info": "有数据时返回字典，可能仅含 stockCode、bondConvPrice 及来源/部分资料标记。没有数据时保留 None 或空字典。",
        "get_sector_list": "扁平且去重的板块名称列表。终端目录范围可能与 MiniQMT 不同。",
        "get_stock_list_in_sector": "证券代码列表。指定历史时点而旧终端不接受参数时会报错，不会退回当前成分。",
        "get_trading_dates": "使用大 QMT 对应证券和周期的交易日结果；迁移前需确认与原版市场日历的业务含义一致。",
        "get_financial_data": "返回底层财务查询结果。cfquant 的字段级查询不等同于原版返回整张财务表，先检查实际结构再提取字段。",
        "reset_sector": "保留底层布尔结果。空列表意味着清空成分，应先确认目标是可修改的自定义板块。",
        "remove_stock_from_sector": "全部删除成功才返回 True。异常或失败可能发生在部分修改之后，需重新查询成分核实。",
        "connect": "0 表示连接探测成功，-1 表示失败。连接成功后仍需检查目标账号订阅。",
        "subscribe": "账号订阅结果；示例按 0 检查成功。账号必须在对应桥配置中存在。",
        "query_stock_asset": "XtAsset 对象；没有资产记录时可能为 None。",
        "query_stock_orders": "XtOrder 列表；cancelable_only=True 会过滤不可撤委托。",
        "query_stock_trades": "XtTrade 列表；成交记录和委托记录是不同对象。",
        "query_stock_positions": "XtPosition 列表，volume 为持仓量，can_use_volume 为可用量。",
        "query_stock_order": "匹配到的一笔 XtOrder，找不到时为 None。",
        "query_stock_position": "匹配证券的 XtPosition，找不到时为 None。",
        "query_stock_orders_async": "立即返回请求序号，随后在独立回调线程交付查询结果。错误写入日志；超时未收到回调不等于空委托列表。",
        "query_position_statistics": "XtPositionStatistics 列表；仅限 FUTURE 账号，None 与空列表含义不同，缺失字段不补零。",
        "order_stock": "返回真实委托编号或失败结果；提交被受理不代表已经成交，后续检查委托和成交回报。",
        "order_stock_async": "返回请求序号 seq，通过 on_order_stock_async_response 关联真实 order_id；seq 不能用于撤单。",
    }.get(name, "")
    if module == "callback":
        result_help = "回调由事件系统调用，无需向终端返回业务结果。回调内尽快完成处理，耗时任务交给独立队列。"
    elif name.startswith("cancel_order_stock"):
        result_help = "异步形式返回请求序号，通过撤单应答与委托事件确认结果；同步形式返回撤单请求结果，最终是否撤成仍以委托状态为准。"
    elif name.startswith("query_credit_"):
        result_help = "返回对应的 Credit 数据对象列表。未提供的字段保持缺失；状态和券源覆盖仍需按目标券商核对。"
    return {"example": code, "originalExample": original_example(code, name) if module != "type" or name == "StockAccount" else "", "usage": usage, "resultHelp": result_help}


def reference_solution(ref):
    name = ref["name"].lower()
    result = {"description": "本节保留对应官方章节入口。下列字段标识用于查阅原版协议；cfquant 的业务支持范围由各接口的适配条目说明。",
              "usage": "请结合实际桥返回的数据核对字段；查询入口可用不代表所有字段、数据周期或终端权限均已具备。",
              "related": [], "example": ""}
    if ref["group"] == "快速开始" or "运行逻辑" in name or name == "创建策略":
        result.update(description="原版外部 Python 通过 MiniQMT 访问行情与交易。cfquant 外部 Python 通过已配置的桥接大 QMT；网页账号绑定和 QMT 入口策略负责连接配置。",
                      related=["trader.XtQuantTrader", "trader.connect", "xtdata.get_full_tick"],
                      example=trader_example(QUERY_BODIES["query_stock_asset"]))
    elif "时间戳" in name:
        result.update(description="行情中的毫秒时间戳转换为北京时间时应显式指定 UTC+8，避免使用运行机器的默认时区。",
                      related=["xtdata.get_full_tick", "xtdata.get_divid_factors"],
                      example='from datetime import datetime, timedelta, timezone\n\ndef beijing_time(milliseconds):\n    return datetime.fromtimestamp(milliseconds / 1000, timezone(timedelta(hours=8)))\n\nprint(beijing_time(1767225600000).isoformat())')
    elif "财务" in name or any(word in name for word in ("balance", "income", "cashflow", "pershareindex", "capital", "holder")):
        result.update(description="官方财务表与大 QMT 财务字段标识存在差异。迁移时需将表级查询转换为当前终端支持的字段列表，并明确报告期或披露时间口径。",
                      related=["xtdata.get_financial_data", "xtdata.download_financial_data"],
                      example='from cfquant import xtdata\n\n' + MARKET_BODIES["get_financial_data"])
    elif "level2" in name or "l2" in name or "现金替代" in name:
        result.update(usage="尚未支持完整替代保证。清单未确认本节数据产品及全部字段的适配，普通行情接口已适配不能代替 Level2 或 ETF 清单能力验证。",
                      related=["xtdata.get_market_data_ex", "xtdata.get_etf_info"])
    elif "合约信息" in name:
        result.update(related=["xtdata.get_instrument_detail"], example='from cfquant import xtdata\n\n' + MARKET_BODIES["get_instrument_detail"])
    elif "融券状态" in name:
        result.update(description="融资与融券的业务状态应分别读取，字段缺失与禁止交易不是同一种情况。",
                      related=["trader.query_credit_subjects", "type.CreditSubjects"],
                      example=trader_example(QUERY_BODIES["query_credit_subjects"], account_type="CREDIT"))
    elif ref["group"] == "行情概述与附录":
        query = "get_divid_factors" if "除权" in name else "get_market_data_ex" if "k线" in name else "get_full_tick"
        result.update(related=["xtdata." + query], example='from cfquant import xtdata\n\n' + MARKET_BODIES[query])
    else:
        result.update(description="原版交易常量与对象字段用于解释委托、账号和成交事件。cfquant 提供 xtconstant 兼容模块，业务接口状态仍需单独核对。",
                      related=["type.XtOrder", "callback.on_stock_order"],
                      example='from cfquant import xtconstant\n\nprint("SH market:", xtconstant.SH_MARKET)\nprint("buy:", xtconstant.STOCK_BUY)\nprint("fixed price:", xtconstant.FIX_PRICE)')
    return result
