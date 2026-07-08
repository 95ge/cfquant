const state = {
  accountId: '',
  bridgeId: 'default',
  queryChannel: 'normal',
  currentView: 'overview',
  refreshTimer: null,
  statusTimer: null,
  lastOrderConfirm: '',
  callbackSeq: 0,
  orderSnapshot: new Map(),
  callbackEvents: [],
  lttxStatus: null,
  bridges: {},
  accountPairs: {},
  envBridges: {},
  apiEndpointId: 'quote_subscribe_whole',
  apiKey: '',
  apiSocket: null,
  serverAccess: null,
  apiOpenGroups: new Set(['data', 'trade', 'system']),
  quoteRows: new Map(),
  quoteSeq: 0,
  quoteEventCount: 0,
  quoteSubscribeId: '',
  quoteConnectionText: '未连接',
  quoteLiveActive: false,
};

const $ = (id) => document.getElementById(id);
const ACCOUNT_PAIR_KEY = 'cfquant.account_bridge_pairs';
const TUTORIAL_TOPIC_KEY = 'cfquant.tutorial_topic';
const API_OPEN_GROUPS_KEY = 'cfquant.api_open_groups';

const API_GROUPS = [
  { id: 'data', title: '数据' },
  { id: 'trade', title: '交易' },
  { id: 'system', title: '系统' },
];

const API_ENDPOINTS = [
  {
    id: 'quote_subscribe_whole',
    group: 'data',
    title: '订阅全推行情',
    method: 'POST',
    path: '/api/quotes/whole/subscribe',
    desc: '打开普通 QMT 已订阅全推行情的外部推送。同一时间只允许一个全推订阅，成功后可通过 WebSocket 实时接收行情事件。',
    defaults: { channel: 'normal', markets: 'SH,SZ' },
    fields: ['bridge_id', 'whole_quote_channel', 'markets'],
  },
  {
    id: 'quote_latest',
    group: 'data',
    title: '读取行情事件',
    method: 'GET',
    path: '/api/quotes/latest',
    desc: '读取服务端缓存的最新行情事件，可按订阅 ID 过滤。',
    defaults: { since: '0', limit: '50' },
    fields: ['quote_subscribe_id', 'since', 'limit'],
  },
  {
    id: 'full_tick',
    group: 'data',
    title: '实时 Tick',
    method: 'POST',
    path: '/api/data/full-tick',
    desc: '查询指定证券的实时全推快照。数据查询默认极速优先，极速离线或失败时回退普通 QMT。',
    defaults: { channel: 'trade', code_list: '000001.SZ,600000.SH' },
    fields: ['bridge_id', 'channel', 'code_list'],
  },
  {
    id: 'market_data',
    group: 'data',
    title: '行情数据',
    method: 'POST',
    path: '/api/data/market',
    desc: '查询行情数据，字段、证券列表、周期和区间可配置。数据查询默认极速优先，极速离线或失败时回退普通 QMT。',
    defaults: { channel: 'trade', field_list: 'open,high,low,close,volume', stock_list: '000001.SZ', period: '1d', count: '-1', dividend_type: 'none', fill_data: '1' },
    fields: ['bridge_id', 'channel', 'field_list', 'stock_list', 'period', 'start_time', 'end_time', 'count', 'dividend_type', 'fill_data'],
  },
  {
    id: 'market_data_ex',
    group: 'data',
    title: '扩展行情数据',
    method: 'POST',
    path: '/api/data/market-ex',
    desc: '调用 QMT get_market_data_ex，适合读取本地缓存行情数据。数据查询默认极速优先，极速离线或失败时回退普通 QMT。',
    defaults: { channel: 'trade', field_list: 'open,high,low,close,volume', stock_list: '000001.SZ', period: '1d', count: '-1', dividend_type: 'none', fill_data: '1' },
    fields: ['bridge_id', 'channel', 'field_list', 'stock_list', 'period', 'start_time', 'end_time', 'count', 'dividend_type', 'fill_data'],
  },
  {
    id: 'quote_subscribe_single',
    group: 'data',
    title: '订阅单股行情',
    method: 'POST',
    path: '/api/quotes/subscribe',
    desc: '订阅单只证券行情，订阅事件同样通过 WebSocket 行情接收。',
    defaults: { channel: 'normal', stock_code: '000001.SZ', period: '1d', count: '0' },
    fields: ['bridge_id', 'channel', 'stock_code', 'period', 'start_time', 'end_time', 'count', 'dividend_type'],
  },
  {
    id: 'ws_quotes',
    group: 'data',
    title: 'WebSocket 行情',
    method: 'WS',
    path: '/ws/quotes',
    desc: '实时接收全推行情事件，可按订阅 ID 过滤。',
    fields: ['quote_subscribe_id'],
  },
  {
    id: 'instrument_detail',
    group: 'data',
    title: '合约详情',
    method: 'POST',
    path: '/api/data/instrument',
    desc: '查询证券合约详情。数据查询默认极速优先，极速离线或失败时回退普通 QMT。',
    defaults: { channel: 'trade', stock_code: '000001.SZ', iscomplete: '0' },
    fields: ['bridge_id', 'channel', 'stock_code', 'iscomplete'],
  },
  {
    id: 'sector_stocks',
    group: 'data',
    title: '板块成分',
    method: 'POST',
    path: '/api/data/sector',
    desc: '查询指定板块的证券列表。数据查询默认极速优先，极速离线或失败时回退普通 QMT。',
    defaults: { channel: 'trade', sector_name: '沪深A股' },
    fields: ['bridge_id', 'channel', 'sector_name'],
  },
  {
    id: 'history_download',
    group: 'data',
    title: '下载历史数据',
    method: 'POST',
    path: '/api/data/history/download',
    desc: '触发 QMT 下载指定证券历史行情数据。数据查询默认极速优先，极速离线或失败时回退普通 QMT。',
    defaults: { channel: 'trade', stock_code: '000001.SZ', period: '1d', incrementally: '' },
    fields: ['bridge_id', 'channel', 'stock_code', 'period', 'start_time', 'end_time', 'incrementally'],
  },
  {
    id: 'financial_data',
    group: 'data',
    title: '财务数据',
    method: 'POST',
    path: '/api/data/financial',
    desc: '读取财务数据，支持填充数据和原始数据两种模式。数据查询默认极速优先，极速离线或失败时回退普通 QMT。',
    defaults: { channel: 'trade', stock_code: '000001.SZ', table: 'ASHAREBALANCESHEET', fields: 'fix_assets', mode: 'filled', report_type: 'announce_time' },
    fields: ['bridge_id', 'channel', 'stock_code', 'financial_table', 'financial_fields', 'financial_mode', 'start_time', 'end_time', 'report_type'],
  },
  {
    id: 'financial_download',
    group: 'data',
    title: '下载财务数据',
    method: 'POST',
    path: '/api/data/financial/download',
    desc: '触发 QMT 补充本地财务数据。财务查询依赖本地已有数据，缺失时先下载。',
    defaults: { channel: 'trade', stock_code: '000001.SZ', table: 'ASHAREBALANCESHEET' },
    fields: ['bridge_id', 'channel', 'stock_code', 'financial_table', 'start_time', 'end_time'],
  },
  {
    id: 'quote_unsubscribe',
    group: 'data',
    title: '取消行情订阅',
    method: 'POST',
    path: '/api/quotes/unsubscribe',
    desc: '取消指定的行情订阅。',
    defaults: { channel: 'normal' },
    fields: ['bridge_id', 'channel', 'quote_subscribe_id'],
  },
  {
    id: 'quote_status',
    group: 'data',
    title: '行情订阅状态',
    method: 'GET',
    path: '/api/quotes/status',
    desc: '查看当前 Web 服务内的行情订阅、事件缓存和 WebSocket 客户端数量。',
    fields: [],
  },
  {
    id: 'asset',
    group: 'trade',
    title: '查资金',
    method: 'GET',
    path: '/api/account',
    desc: '查询指定账号的资金信息。',
    defaults: { sections: 'asset', force: '1' },
    fields: ['account_id'],
  },
  {
    id: 'positions',
    group: 'trade',
    title: '查持仓',
    method: 'GET',
    path: '/api/account',
    desc: '查询指定账号的持仓列表。',
    defaults: { sections: 'positions', force: '1' },
    fields: ['account_id'],
  },
  {
    id: 'orders',
    group: 'trade',
    title: '查委托',
    method: 'GET',
    path: '/api/account',
    desc: '查询指定账号的委托列表。',
    defaults: { sections: 'orders', force: '1' },
    fields: ['account_id'],
  },
  {
    id: 'trades',
    group: 'trade',
    title: '查成交',
    method: 'GET',
    path: '/api/account',
    desc: '查询指定账号的成交列表。',
    defaults: { sections: 'trades', force: '1' },
    fields: ['account_id'],
  },
  {
    id: 'xttrader_compat',
    group: 'system',
    title: 'xtquant 平替说明',
    method: 'DOC',
    path: 'cfquant/docs/xttrader_compatibility.md / cfquant/docs/xtdata_compatibility.md',
    desc: '说明 cfquant 对 xtquant.xttrader 和 xtquant.xtdata 的平替进度、已实装接口和当前限制。',
    fields: [],
  },
  {
    id: 'status',
    group: 'system',
    title: '通道状态',
    method: 'GET',
    path: '/api/status',
    desc: '查看桥接端普通 QMT 和极速交易端状态。',
    fields: ['bridge_id'],
  },
  {
    id: 'callbacks',
    group: 'trade',
    title: '查回调',
    method: 'GET',
    path: '/api/callbacks',
    desc: '按账号拉取委托/成交回调事件，桥接端由账号绑定自动决定。',
    defaults: { since: '0', limit: '50' },
    fields: ['account_id', 'since', 'limit'],
  },
  {
    id: 'ws_callbacks',
    group: 'trade',
    title: 'WebSocket 回调',
    method: 'WS',
    path: '/ws/callbacks',
    desc: '按账号实时接收委托/成交等回调事件。API Key 会通过 apikey 查询参数传入。',
    fields: ['account_id'],
  },
  {
    id: 'order',
    group: 'trade',
    title: '提交委托',
    method: 'POST',
    path: '/api/order',
    desc: '按账号绑定的桥接端提交买入或卖出委托。后端要求确认文本完全匹配。',
    fields: ['account_id', 'side', 'stock_code', 'price', 'volume', 'confirm_text'],
  },
  {
    id: 'batch_order',
    group: 'trade',
    title: '批量委托',
    method: 'POST',
    path: '/api/orders/batch',
    desc: '按账号绑定的桥接端批量提交委托。orders 使用 JSON 数组，后端内部逐笔调用 QMT 下单。',
    defaults: {
      orders_json: '[{"stock_code":"000001.SZ","price":10.0,"volume":100},{"stock_code":"600000.SH","price":8.5,"volume":200}]',
      confirm_text: 'BATCH 2',
    },
    fields: ['account_id', 'batch_orders_json', 'batch_confirm_text'],
  },
  {
    id: 'cancel',
    group: 'trade',
    title: '撤单',
    method: 'POST',
    path: '/api/cancel',
    desc: '按账号绑定的桥接端撤销指定委托。后端要求确认文本完全匹配。',
    fields: ['account_id', 'order_id', 'cancel_confirm_text'],
  },
  {
    id: 'lttx',
    group: 'system',
    title: 'LTtx 状态',
    method: 'GET',
    path: '/api/lttx',
    desc: '查看 LTtx 服务是否运行。',
    fields: [],
  },
];

const API_FIELD_META = {
  bridge_id: { label: '桥接端', type: 'bridge' },
  account_id: { label: '账号', type: 'text', placeholder: '2220009880' },
  channel: { label: '查询通道', type: 'channel' },
  whole_quote_channel: { label: '订阅通道', type: 'fixed_channel', param: 'channel' },
  trade_channel: { label: '交易通道', type: 'trade_channel', param: 'channel' },
  side: { label: '方向', type: 'side' },
  stock_code: { label: '证券代码', type: 'text', placeholder: '000001.SZ' },
  price: { label: '价格', type: 'number', placeholder: '10.000', step: '0.001' },
  volume: { label: '数量', type: 'number', placeholder: '100', step: '100' },
  confirm_text: { label: '确认文本', type: 'text', placeholder: 'BUY 000001.SZ 100 @ 10.000', wide: true },
  batch_confirm_text: { label: '确认文本', type: 'text', placeholder: 'BATCH 2', param: 'confirm_text', wide: true },
  batch_orders_json: { label: '委托列表 JSON', type: 'textarea', placeholder: '[{"stock_code":"000001.SZ","price":10.0,"volume":100}]', param: 'orders_json', wide: true },
  cancel_confirm_text: { label: '确认文本', type: 'text', placeholder: 'CANCEL 委托编号', param: 'confirm_text', wide: true },
  order_id: { label: '委托编号', type: 'text' },
  since: { label: '起始序号', type: 'number', placeholder: '0' },
  limit: { label: '条数', type: 'number', placeholder: '50' },
  markets: { label: '市场', type: 'text', placeholder: 'SH,SZ' },
  quote_subscribe_id: { label: '订阅 ID', type: 'text', placeholder: '订阅成功后返回的 subscribe_id', param: 'subscribe_id' },
  code_list: { label: '证券列表', type: 'text', placeholder: '000001.SZ,600000.SH' },
  stock_list: { label: '证券列表', type: 'text', placeholder: '000001.SZ,600000.SH' },
  field_list: { label: '字段列表', type: 'text', placeholder: 'open,high,low,close,volume' },
  period: { label: '周期', type: 'text', placeholder: '1d' },
  start_time: { label: '开始时间', type: 'text', placeholder: '20240101' },
  end_time: { label: '结束时间', type: 'text', placeholder: '20241231' },
  count: { label: '数量', type: 'number', placeholder: '-1' },
  dividend_type: { label: '复权方式', type: 'text', placeholder: 'none' },
  fill_data: { label: '填充数据', type: 'text', placeholder: '1' },
  iscomplete: { label: '完整信息', type: 'text', placeholder: '0' },
  sector_name: { label: '板块名称', type: 'text', placeholder: '沪深A股' },
  incrementally: { label: '增量下载', type: 'text', placeholder: '留空/1/0' },
  financial_table: { label: '财务表', type: 'text', placeholder: 'ASHAREBALANCESHEET', param: 'table' },
  financial_fields: { label: '财务字段', type: 'text', placeholder: 'fix_assets 或 ASHAREBALANCESHEET.fix_assets', param: 'fields' },
  financial_mode: { label: '财务模式', type: 'financial_mode', param: 'mode' },
  report_type: { label: '报表时间', type: 'report_type' },
};

const API_PARAM_DOCS = {
  bridge_id: '桥接端 ID。账号接口通常不用填，会按账号绑定自动决定。',
  account_id: '资金账号。',
  channel: '请求通道，normal 为普通 QMT，trade 为极速交易端。数据查询选择 trade 时会极速优先并在失败或离线时回退普通 QMT；全推订阅固定使用 normal。',
  sections: '账号数据段，asset/positions/orders/trades。',
  force: '是否强制刷新缓存，1 表示立即查询。',
  since: '回调起始序号。',
  limit: '返回条数上限。',
  side: '委托方向，buy 或 sell。',
  stock_code: '证券代码，格式如 000001.SZ。',
  price: '委托价格。',
  volume: '委托数量。',
  confirm_text: '确认文本，下单格式为 BUY/SELL code volume @ price，撤单格式为 CANCEL order_id。',
  orders_json: '批量委托数组，每项包含 stock_code、price、volume，可选 side，默认 buy。',
  order_id: '委托编号。',
  markets: '全推行情市场列表，支持 SH、SZ，多个市场用英文逗号分隔。',
  subscribe_id: '行情订阅 ID，由订阅接口返回；为空时读取或接收全部行情事件。',
  code_list: '证券代码列表，多个代码用英文逗号分隔。',
  stock_list: '证券代码列表，多个代码用英文逗号分隔。',
  field_list: '行情字段列表，多个字段用英文逗号分隔。',
  period: '行情周期，例如 tick、1m、5m、1d。',
  start_time: '开始时间，按 QMT 接口要求填写。',
  end_time: '结束时间，按 QMT 接口要求填写。',
  count: '返回数量，-1 表示按区间返回。',
  dividend_type: '复权方式，例如 none/front/back，按 QMT 环境支持为准。',
  fill_data: '是否填充数据，1 表示填充，0 表示不填充。',
  iscomplete: '是否查询完整合约信息，1 表示完整。',
  sector_name: '板块名称。',
  incrementally: '历史数据是否增量下载，留空表示使用 QMT 默认行为。',
  table: '财务数据表名，例如 ASHAREBALANCESHEET、ASHAREINCOME、ASHARECASHFLOW、CAPITALSTRUCTURE、PERSHAREINDEX。',
  fields: '财务字段列表，多个字段用英文逗号分隔。可填 fix_assets，服务端会与 table 组合；也可直接填 ASHAREBALANCESHEET.fix_assets。',
  mode: '财务查询模式，filled 调用 get_financial_data，raw 调用 get_raw_financial_data。',
  report_type: '报表时间类型，announce_time 按公告日期，report_time 按报告期。',
};

const API_RETURN_DOCS = {
  quote_subscribe_whole: [
    ['subscribe_id', '行情订阅 ID'],
    ['markets', '已订阅市场'],
    ['latency_ms', '请求耗时'],
  ],
  quote_latest: [
    ['events[]', '行情事件列表'],
    ['events[].subscribe_id', '行情订阅 ID'],
    ['events[].data', '行情数据'],
    ['status.subscriptions', '当前订阅列表'],
  ],
  full_tick: [
    ['result', '实时 tick 快照'],
    ['latency_ms', '请求耗时'],
  ],
  market_data: [
    ['result', '行情数据结果'],
    ['latency_ms', '请求耗时'],
  ],
  market_data_ex: [
    ['result', '扩展行情数据结果'],
    ['latency_ms', '请求耗时'],
  ],
  quote_subscribe_single: [
    ['subscribe_id', '行情订阅 ID'],
    ['stock_code', '证券代码'],
    ['latency_ms', '请求耗时'],
  ],
  ws_quotes: [
    ['type', '消息类型。hello 表示连接成功，quote 表示行情事件。'],
    ['event.subscribe_id', '行情订阅 ID'],
    ['event.data', '行情数据'],
  ],
  instrument_detail: [
    ['result', '合约详情'],
    ['latency_ms', '请求耗时'],
  ],
  sector_stocks: [
    ['result', '板块证券列表'],
    ['latency_ms', '请求耗时'],
  ],
  history_download: [
    ['result', '下载任务返回值'],
    ['latency_ms', '请求耗时'],
  ],
  financial_data: [
    ['result', '财务数据结果'],
    ['channel', '实际调用通道'],
    ['fallback', '是否从极速回退到普通 QMT'],
  ],
  financial_download: [
    ['result', '底层下载函数返回值'],
    ['channel', '实际调用通道'],
    ['fallback', '是否从极速回退到普通 QMT'],
  ],
  quote_unsubscribe: [
    ['subscribe_id', '已取消的订阅 ID'],
    ['result', '底层取消订阅返回值'],
  ],
  quote_status: [
    ['subscriptions', '当前订阅列表'],
    ['event_count', '服务端缓存事件数'],
    ['websocket_clients', 'WebSocket 客户端数量'],
  ],
  asset: [
    ['balance', '总资产'],
    ['available', '可用资金'],
    ['market_value', '总市值'],
    ['position_profit', '持仓盈亏'],
  ],
  positions: [
    ['stock_code', '证券代码'],
    ['instrument_name', '证券名称'],
    ['volume', '持仓数量'],
    ['can_use_volume', '可用数量'],
    ['market_value', '市值'],
  ],
  orders: [
    ['order_time', '委托时间'],
    ['stock_code', '证券代码'],
    ['instrument_name', '证券名称'],
    ['order_volume', '委托数量'],
    ['traded_volume', '成交数量'],
    ['order_status', '委托状态'],
    ['m_strOrderSysID', '委托编号'],
  ],
  trades: [
    ['trade_time', '成交时间'],
    ['stock_code', '证券代码'],
    ['instrument_name', '证券名称'],
    ['price', '成交价格'],
    ['volume', '成交数量'],
    ['trade_amount', '成交金额'],
  ],
  status: [
    ['normal.online', '普通 QMT 是否在线'],
    ['trade.online', '极速交易端是否在线'],
    ['checked_at_text', '检测时间'],
  ],
  callbacks: [
    ['events[].event', '回调类型'],
    ['events[].account_id', '账号'],
    ['events[].data', '回调数据'],
  ],
  ws_callbacks: [
    ['type', '消息类型。hello 表示连接成功，callback 表示实时回调。'],
    ['channel', 'hello 消息中的通道名称，固定为 callbacks。'],
    ['bridge_id', '当前连接过滤的桥接端。按账号连接时由后端自动解析。'],
    ['account_id', '当前连接过滤的账号。为空表示不过滤账号。'],
    ['event.seq', '服务端回调序号，用于排序和断点拉取。'],
    ['event.event', '回调事件名，例如 trader:on_stock_order。'],
    ['event.account_id', '回调所属账号。'],
    ['event.bridge_id', '回调所属桥接端。'],
    ['event.received_at', '服务端收到回调的时间戳，单位秒。'],
    ['event.data', 'QMT 回调对象转换后的字段数据。'],
  ],
  order: [
    ['order_id', '委托编号'],
    ['order_remark', '委托备注'],
    ['latency_ms', '请求耗时'],
  ],
  batch_order: [
    ['result.total', '请求委托总数'],
    ['result.submitted', '提交成功数量'],
    ['result.failed', '失败数量'],
    ['result.results[]', '每笔委托结果，包含 index、ok、stock_code、result/error'],
    ['latency_ms', '请求耗时'],
  ],
  cancel: [
    ['cancel_result', '撤单结果'],
    ['order_id', '委托编号'],
    ['latency_ms', '请求耗时'],
  ],
  lttx: [
    ['running', 'LTtx 是否运行'],
    ['port', 'LTtx 端口'],
    ['managed_pids', '可管理进程 PID'],
  ],
};

const WS_CALLBACK_EVENT_DOCS = [
  ['trader:on_stock_asset', '资金变化回调'],
  ['trader:on_stock_position', '持仓变化回调'],
  ['trader:on_stock_order', '委托状态回调'],
  ['trader:on_stock_trade', '成交回调'],
  ['trader:on_order_error', '下单错误回调'],
  ['trader:on_cancel_error', '撤单错误回调'],
  ['trader:on_order_stock_async_response', '异步下单响应'],
  ['trader:on_cancel_order_stock_async_response', '异步撤单响应'],
];

const WS_CALLBACK_DATA_DOCS = [
  ['stock_code', '证券代码，系统根据 m_strInstrumentID + m_strExchangeID 组合生成。'],
  ['m_strAccountID', '资金账号。'],
  ['m_strInstrumentID', '证券代码主体。'],
  ['m_strExchangeID', '交易所代码。'],
  ['m_strInstrumentName', '证券名称。'],
  ['m_nVolumeTotalOriginal', '原始委托数量。'],
  ['m_nVolumeTraded', '已成交数量。'],
  ['m_nVolume', '成交数量或持仓数量，取决于事件类型。'],
  ['m_dPrice', '成交价格或委托价格，取决于事件类型。'],
  ['m_dTradeAmount', '成交金额。'],
  ['m_nOrderStatus', '委托状态数字。'],
  ['m_strOrderSysID', '柜台委托编号。'],
  ['m_strOrderID', '委托编号。'],
  ['m_nOrderID', 'QMT 本地委托编号。'],
  ['m_strStatusMsg', '状态或错误说明。'],
  ['m_dBalance', '总资产。'],
  ['m_dAvailable', '可用资金。'],
  ['m_dInstrumentValue', '证券市值。'],
  ['m_dPositionProfit', '持仓盈亏。'],
];

const WS_CALLBACK_EXAMPLE = {
  type: 'callback',
  event: {
    seq: 12,
    event: 'trader:on_stock_order',
    account_id: '2220009880',
    bridge_id: 'default',
    received_at: 1783440000.123,
    data: {
      stock_code: '000001.SZ',
      m_strAccountID: '2220009880',
      m_strInstrumentID: '000001',
      m_strExchangeID: 'SZ',
      m_strInstrumentName: '平安银行',
      m_nVolumeTotalOriginal: 100,
      m_nVolumeTraded: 0,
      m_nOrderStatus: 50,
      m_strOrderSysID: '123456789',
    },
  },
};

function money(value) {
  if (value === null || value === undefined || value === '') return '--';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function plain(value) {
  if (value === null || value === undefined || value === '') return '--';
  return String(value);
}

function esc(value) {
  return plain(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const ORDER_STATUS_MAP = {
  '48': '未报',
  '49': '待报',
  '50': '已报',
  '51': '已报待撤',
  '52': '部成待撤',
  '53': '部撤',
  '54': '已撤',
  '55': '部成',
  '56': '已成',
  '57': '废单',
};

const SUBMIT_STATUS_MAP = {
  '48': '已经提交',
  '49': '撤单已经提交',
  '50': '修改已经提交',
  '51': '已经接受',
  '52': '报单已经被拒绝',
  '53': '撤单已经被拒绝',
  '54': '改单已经被拒绝',
};

const LOCAL_STATUS_MAP = {
  submitted: '已提交',
  cancel_requested: '撤单已提交',
};

function hasValue(value) {
  return value !== null && value !== undefined && value !== '';
}

function mappedStatus(value, map) {
  if (!hasValue(value)) return '';
  const text = String(value).trim();
  return LOCAL_STATUS_MAP[text] || map[text] || text;
}

function signedClass(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return '';
  return number > 0 ? 'positive' : 'negative';
}

function nowText() {
  return new Date().toLocaleString('zh-CN', { hour12: false });
}

function pad2(value) {
  return String(value).padStart(2, '0');
}

function formatDateTime(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
}

function parseCompactDateTime(value) {
  const text = String(value || '').trim();
  let match = text.match(/^(\d{4})(\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/);
  if (!match) {
    match = text.match(/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$/);
  }
  if (!match) return '';
  const [, year, month, day, hour, minute, second] = match;
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

function formatQuoteTime(value, event) {
  if (value !== null && value !== undefined && value !== '') {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return formatDateTime(new Date(value > 100000000000 ? value : value * 1000));
    }
    const text = String(value).trim();
    const compact = parseCompactDateTime(text);
    if (compact) return compact;
    if (/^\d+$/.test(text)) {
      const number = Number(text);
      if (Number.isFinite(number)) {
        return formatDateTime(new Date(text.length >= 13 ? number : number * 1000));
      }
    }
    const parsed = new Date(text);
    const formatted = formatDateTime(parsed);
    if (formatted) return formatted;
    return text;
  }
  if (event && event.received_at) {
    return formatDateTime(new Date(Number(event.received_at) * 1000));
  }
  return formatDateTime(new Date());
}

function normalizeApiBaseUrl(value) {
  value = String(value || '').trim();
  if (!value) return window.location.origin;
  if (!/^https?:\/\//i.test(value)) value = `http://${value}`;
  try {
    const url = new URL(value);
    return url.origin;
  } catch (error) {
    return window.location.origin;
  }
}

function currentApiBaseUrl() {
  const input = $('apiBaseUrlInput');
  if (input && input.value.trim()) return normalizeApiBaseUrl(input.value);
  return normalizeApiBaseUrl(window.location.origin);
}

function apiUrl(path) {
  return `${currentApiBaseUrl()}${path}`;
}

function apiWsUrl(path) {
  const base = new URL(currentApiBaseUrl());
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${base.protocol}//${base.host}${path}`;
}

function log(message, data) {
  const box = $('logBox');
  const line = document.createElement('div');
  line.className = 'log-entry';
  const suffix = data === undefined ? '' : ` ${JSON.stringify(data)}`;
  line.textContent = `[${nowText()}] ${message}${suffix}`;
  box.prepend(line);
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const apiKey = state.apiKey || '';
  if (apiKey) headers['X-API-Key'] = apiKey;
  const response = await fetch(path, {
    headers,
    ...options,
  });
  const payload = await response.json();
  if (!payload.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload.data;
}

function apiEndpointById(id) {
  return API_ENDPOINTS.find((item) => item.id === id) || API_ENDPOINTS[0];
}

function apiGroupForEndpoint(endpointId) {
  const endpoint = apiEndpointById(endpointId);
  return endpoint.group || 'trade';
}

function saveApiOpenGroups() {
  localStorage.setItem(API_OPEN_GROUPS_KEY, JSON.stringify([...state.apiOpenGroups]));
}

function loadApiOpenGroups() {
  try {
    const raw = localStorage.getItem(API_OPEN_GROUPS_KEY);
    if (raw !== null) {
      const saved = JSON.parse(raw);
      const validGroups = new Set(API_GROUPS.map((group) => group.id));
      state.apiOpenGroups = new Set(saved.filter((id) => validGroups.has(id)));
    } else {
      state.apiOpenGroups = new Set(['data', 'trade', 'system']);
    }
  } catch (error) {
    state.apiOpenGroups = new Set(['data', 'trade', 'system']);
  }
}

function renderApiDocs(endpointId = state.apiEndpointId, options = {}) {
  const list = $('apiEndpointList');
  const form = $('apiForm');
  if (!list || !form) return;
  const endpoint = apiEndpointById(endpointId);
  state.apiEndpointId = endpoint.id;
  if (options.ensureGroupOpen) {
    state.apiOpenGroups.add(endpoint.group || 'trade');
  }
  saveApiOpenGroups();
  list.innerHTML = '';
  API_GROUPS.forEach((group) => {
    const groupEndpoints = API_ENDPOINTS.filter((item) => (item.group || 'trade') === group.id);
    if (!groupEndpoints.length) return;
    const open = state.apiOpenGroups.has(group.id);
    const wrap = document.createElement('div');
    wrap.className = `api-group${open ? ' open' : ''}${(endpoint.group || 'trade') === group.id ? ' active' : ''}`;
    const header = document.createElement('button');
    header.type = 'button';
    header.className = 'api-group-head';
    header.dataset.apiGroup = group.id;
    header.setAttribute('aria-expanded', open ? 'true' : 'false');
    header.innerHTML = `<span>${esc(group.title)}</span><span>${open ? '▾' : '▸'}</span>`;
    wrap.appendChild(header);
    const body = document.createElement('div');
    body.className = 'api-group-body';
    if (!open) body.hidden = true;
    groupEndpoints.forEach((item) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `api-endpoint${item.id === endpoint.id ? ' active' : ''}`;
      button.dataset.endpointId = item.id;
      button.innerHTML = `<span class="api-method">${esc(item.method)}</span><span>${esc(item.title)}</span>`;
      body.appendChild(button);
    });
    wrap.appendChild(body);
    list.appendChild(wrap);
  });
  $('apiTitle').textContent = endpoint.title;
  $('apiDesc').textContent = endpoint.desc;
  $('apiRoute').textContent = `${endpoint.method} ${endpoint.path}`;
  form.innerHTML = endpoint.fields.map((fieldName) => apiFieldHtml(fieldName)).join('');
  if (endpoint.method !== 'DOC') {
    const actions = document.createElement('div');
    actions.className = 'api-form-actions field wide';
    actions.innerHTML = `<button class="primary" type="submit">${endpoint.method === 'WS' ? '连接 WebSocket' : '发送请求'}</button><button id="apiResetBtn" type="button">重置参数</button>`;
    form.appendChild(actions);
    setApiDefaults(endpoint);
  }
  renderApiDocDetail(endpoint);
  updateQuoteLivePanel(endpoint);
  updateApiRequestPreview();
}

function updateQuoteLivePanel(endpoint) {
  const panel = $('quoteLivePanel');
  if (!panel) return;
  const show = (endpoint.group || '') === 'data' && (endpoint.id.includes('quote') || endpoint.id === 'full_tick');
  panel.classList.toggle('hidden', !show);
  if (!show) {
    resetQuoteLive('');
    return;
  }
  if (!state.quoteLiveActive) {
    resetQuoteLive('');
  } else {
    renderQuoteLiveTable();
  }
}

function resetQuoteLive(subscribeId = '') {
  state.quoteRows.clear();
  state.quoteSeq = 0;
  state.quoteEventCount = 0;
  state.quoteSubscribeId = String(subscribeId || '');
  state.quoteLiveActive = !!subscribeId;
  state.quoteConnectionText = subscribeId ? `连接中 #${subscribeId}` : '未订阅';
  renderQuoteLiveTable();
}

function renderApiDocDetail(endpoint) {
  const box = $('apiDocDetail');
  if (!box) return;
  if (endpoint.id === 'xttrader_compat') {
    box.innerHTML = xttraderCompatDocHtml();
    return;
  }
  const paramRows = [];
  const seen = new Set();
  endpoint.fields.forEach((fieldName) => {
    const meta = API_FIELD_META[fieldName] || {};
    const name = meta.param || fieldName;
    if (seen.has(name)) return;
    seen.add(name);
    paramRows.push([name, API_PARAM_DOCS[name] || API_PARAM_DOCS[fieldName] || meta.label || name]);
  });
  Object.keys(endpoint.defaults || {}).forEach((name) => {
    if (seen.has(name)) return;
    seen.add(name);
    paramRows.push([name, API_PARAM_DOCS[name] || name]);
  });
  const returnRows = API_RETURN_DOCS[endpoint.id] || [['ok', '请求是否成功'], ['data', '返回数据']];
  box.innerHTML = `
    <div>
      <h3>参数说明</h3>
      ${apiDocTable(paramRows)}
    </div>
    <div>
      <h3>返回字段</h3>
      ${apiDocTable(returnRows)}
    </div>
    ${endpoint.id === 'ws_callbacks' ? wsCallbackDocHtml() : ''}
    ${endpoint.id === 'ws_quotes' ? wsQuoteDocHtml() : ''}`;
}

function apiDocTable(rows) {
  if (!rows.length) return '<div class="metric-note">无参数</div>';
  return `<table><thead><tr><th>字段</th><th>说明</th></tr></thead><tbody>${rows.map(([name, desc]) => `<tr><td><code>${esc(name)}</code></td><td>${esc(desc)}</td></tr>`).join('')}</tbody></table>`;
}

function wsCallbackDocHtml() {
  return `
    <div class="api-doc-extra">
      <h3>连接说明</h3>
      <p>连接成功后会先收到 <code>hello</code> 消息。后续 QMT 有委托、成交、资金、持仓等回调时，会收到 <code>callback</code> 消息。</p>
      <p>只填写 <code>account_id</code> 时，后端会按账号绑定自动找到桥接端。启用 API Key 后，浏览器 WebSocket 会通过 <code>apikey</code> 查询参数传入。</p>
    </div>
    <div class="api-doc-extra">
      <h3>事件类型</h3>
      ${apiDocTable(WS_CALLBACK_EVENT_DOCS)}
    </div>
    <div class="api-doc-extra">
      <h3>data 常见字段</h3>
      ${apiDocTable(WS_CALLBACK_DATA_DOCS)}
    </div>
    <div class="api-doc-extra">
      <h3>消息示例</h3>
      <pre class="guide-code">${esc(JSON.stringify(WS_CALLBACK_EXAMPLE, null, 2))}</pre>
    </div>`;
}

function wsQuoteDocHtml() {
  return `
    <div class="api-doc-extra">
      <h3>接收说明</h3>
      <p>先调用订阅全推行情接口获取 <code>subscribe_id</code>。WebSocket 连接成功后会先收到 <code>hello</code> 消息，后续行情推送会收到 <code>quote</code> 消息。</p>
      <p><code>subscribe_id</code> 为空时接收当前 Web 服务内全部行情订阅事件；填写后只接收对应订阅。</p>
    </div>`;
}

function xttraderCompatDocHtml() {
  const traderImplementedRows = [
    ['生命周期/连接', 'start、stop、connect、run_forever、register_callback'],
    ['账号订阅', 'subscribe、unsubscribe'],
    ['股票交易', 'order_stock、order_stock_async'],
    ['股票撤单', 'cancel_order_stock、cancel_order_stock_async'],
    ['股票查询', 'query_stock_asset、query_stock_orders、query_stock_order、query_stock_trades、query_stock_positions、query_stock_position'],
    ['交易回调', 'XtQuantTraderCallback 原版 14 个公开回调方法已补齐'],
  ];
  const traderPartialRows = [
    ['系统编号撤单', 'cancel_order_stock_sysid、cancel_order_stock_sysid_async 已接入，底层复用当前 QMT cancel 能力，仍需真实系统编号验证。'],
    ['综合资金/持仓', 'query_com_fund、query_com_position 已映射到 QMT 交易明细，字段结构可能与原生 xtquant 不完全一致。'],
    ['非交易 async', '部分 async 方法当前是同步请求完成后触发 callback，并返回本地 seq，不完全等价原生异步队列。'],
  ];
  const traderExposedRows = [
    ['账号信息', 'query_account_info、query_account_infos、query_account_status 及 async 入口'],
    ['信用业务', 'query_credit_detail、query_credit_subjects、query_credit_slo_code、query_credit_assure、query_stk_compacts 及 async 入口'],
    ['新股申购', 'query_ipo_data、query_new_purchase_limit 及 async 入口'],
    ['银证/划转', 'query_bank_info、query_bank_amount、bank_transfer_in/out、fund_transfer、secu_transfer、CTP 内转'],
    ['数据/SMT', 'query_data、export_data、sync_transaction_from_external、SMT 查询和 async 入口'],
  ];
  const dataImplementedRows = [
    ['行情查询', 'get_market_data、get_market_data_ex、get_full_tick、get_local_data'],
    ['行情订阅', 'subscribe_quote、subscribe_quote2、subscribe_whole_quote、unsubscribe_quote'],
    ['历史数据', 'download_history_data、download_history_data2'],
    ['基础资料', 'get_instrument_detail、get_stock_list_in_sector'],
    ['运行/客户端', 'get_client、run；额外提供 configure 用于配置 cfquant 客户端'],
  ];
  const dataWebRows = [
    ['实时行情', 'POST /api/data/full-tick、POST /api/data/market、POST /api/data/market-ex'],
    ['基础资料', 'POST /api/data/instrument、POST /api/data/sector'],
    ['历史/财务', 'POST /api/data/history/download、POST /api/data/financial、POST /api/data/financial/download'],
    ['订阅推送', 'POST /api/quotes/whole/subscribe、POST /api/quotes/subscribe、POST /api/quotes/unsubscribe、GET /api/quotes/latest、WS /ws/quotes'],
  ];
  const dataMissingRows = [
    ['财务数据 Python 封装', 'get_financial_data、get_financial_data_ori、download_financial_data、download_financial_data2 尚未在 cfquant.cfquant.xtdata 中补齐；Web 端已通过桥接端直接开放财务查询/下载。'],
    ['交易日历/交易时段', 'get_trading_dates、get_trading_calendar、get_trading_period、get_kline_trading_period 等未平替。'],
    ['L2/ETF/期权/可转债', 'get_l2_quote、get_l2_order、get_etf_info、get_option_list、bnd_get_* 等未平替。'],
    ['板块维护/公式系统', 'create_sector、add_sector、create_formula、call_formula、subscribe_formula 等未平替。'],
    ['行情服务器/外部数据', 'connect、disconnect、reconnect、get_quote_server_status、read_feather、write_feather、push_custom_data 等未平替。'],
  ];
  return `
    <div class="api-doc-extra xt-compat-doc">
      <section>
        <h3>总体进度</h3>
        <p><code>xttrader</code> 已补齐原版 75 个公开方法的同名入口，签名已对齐；已补齐 <code>XtQuantTraderCallback</code> 原版 14 个公开回调方法。</p>
        <p><code>xtdata</code> 原版当前检测到 138 个公开函数，cfquant 当前暴露 15 个公开函数，其中 14 个与原版同名。核心行情查询、订阅、历史下载、合约和板块能力已覆盖，但还没有做到全量平替。</p>
      </section>
      <section>
        <h3>xttrader 已平替</h3>
        ${apiDocTable(traderImplementedRows)}
      </section>
      <section>
        <h3>xttrader 部分平替</h3>
        ${apiDocTable(traderPartialRows)}
      </section>
      <section>
        <h3>xttrader 兼容入口</h3>
        ${apiDocTable(traderExposedRows)}
      </section>
      <section>
        <h3>xtdata 已平替/已覆盖</h3>
        ${apiDocTable(dataImplementedRows)}
      </section>
      <section>
        <h3>xtdata Web 已开放</h3>
        ${apiDocTable(dataWebRows)}
      </section>
      <section>
        <h3>xtdata 未全量平替</h3>
        ${apiDocTable(dataMissingRows)}
      </section>
      <section>
        <h3>追踪文档</h3>
        <p><code>cfquant/docs/xttrader_compatibility.md</code></p>
        <p><code>cfquant/docs/xtdata_compatibility.md</code></p>
      </section>
    </div>`;
}

function renderApiKeyStatus(info) {
  const input = $('apiKeyInput');
  const status = $('apiKeyStatus');
  if (!input || !status) return;
  if (info && Object.prototype.hasOwnProperty.call(info, 'api_key')) {
    state.apiKey = info.api_key || '';
  }
  if (state.apiKey) {
    input.value = state.apiKey;
  }
  if (info && info.enabled) {
    status.textContent = `已启用 ${info.masked || ''}`;
  } else {
    status.textContent = '未启用';
  }
}

async function saveApiKey(options = {}) {
  const input = $('apiKeyInput');
  const body = options.generate ? { generate: true } : { api_key: input.value.trim() };
  const data = await api('/api/apikey', { method: 'POST', body: JSON.stringify(body) });
  const apiKey = data.api_key || body.api_key || '';
  state.apiKey = apiKey;
  if (apiKey) {
    input.value = apiKey;
  } else {
    input.value = '';
  }
  renderApiKeyStatus(data);
  updateApiRequestPreview();
  log(options.generate ? 'API Key 已随机生成' : 'API Key 已保存', { enabled: !!apiKey });
}

function toggleApiKeyVisible() {
  const input = $('apiKeyInput');
  const button = $('toggleApiKeyBtn');
  const visible = input.type === 'text';
  input.type = visible ? 'password' : 'text';
  button.textContent = visible ? '显示' : '隐藏';
}

async function copyApiKey() {
  const value = $('apiKeyInput').value.trim();
  if (!value) {
    log('API Key 为空，无法复制');
    return;
  }
  await navigator.clipboard.writeText(value);
  log('API Key 已复制');
}

function renderServerAccess(info) {
  state.serverAccess = info || {};
  const allowRemote = !!state.serverAccess.allow_remote;
  const configuredHost = state.serverAccess.configured_host || (allowRemote ? '0.0.0.0' : '127.0.0.1');
  const boundHost = state.serverAccess.bound_host || configuredHost;
  const boundPort = state.serverAccess.bound_port || window.location.port || '';
  const statusParts = [
    `当前监听 ${boundHost}${boundPort ? `:${boundPort}` : ''}`,
    allowRemote ? '已允许外部 IP 访问' : '仅本机 127.0.0.1 访问',
  ];
  if (state.serverAccess.requires_restart) {
    statusParts.push('重启 Web 服务后生效');
  }

  const overviewToggle = $('allowRemoteAccess');
  if (overviewToggle) overviewToggle.checked = allowRemote;
  const apiToggle = $('allowApiRemoteAccess');
  if (apiToggle) apiToggle.checked = allowRemote;
  const overviewStatus = $('serverAccessStatus');
  if (overviewStatus) overviewStatus.textContent = statusParts.join('；');
  const apiStatus = $('apiServerStatus');
  if (apiStatus) apiStatus.textContent = statusParts.join('；');

  const baseInput = $('apiBaseUrlInput');
  if (baseInput && !baseInput.value.trim()) {
    baseInput.value = normalizeApiBaseUrl(state.serverAccess.api_base_url || window.location.origin);
  }
  updateApiRequestPreview();
}

async function saveServerAccessFromUi(source = 'api') {
  const allowToggle = source === 'overview' ? $('allowRemoteAccess') : $('allowApiRemoteAccess');
  const allowRemote = !!(allowToggle && allowToggle.checked);
  const baseInput = $('apiBaseUrlInput');
  let apiBaseUrl = '';
  if (baseInput) {
    const normalized = normalizeApiBaseUrl(baseInput.value);
    baseInput.value = normalized;
    apiBaseUrl = normalized;
  }
  const data = await api('/api/server-access', {
    method: 'POST',
    body: JSON.stringify({ allow_remote: allowRemote, api_base_url: apiBaseUrl }),
  });
  renderServerAccess(data);
  log('访问设置已保存', { allow_remote: !!data.allow_remote, api_base_url: data.api_base_url || '', requires_restart: !!data.requires_restart });
}

function apiFieldHtml(fieldName) {
  const meta = API_FIELD_META[fieldName] || { label: fieldName, type: 'text' };
  const name = meta.param || fieldName;
  const wide = meta.wide ? ' wide' : '';
  if (meta.type === 'bridge') {
    const options = Object.keys(state.bridges || {}).map((id) => `<option value="${esc(id)}">${esc((state.bridges[id] || {}).name || id)}</option>`).join('');
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}">${options}</select></label>`;
  }
  if (meta.type === 'channel') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="normal">普通 QMT</option><option value="trade">极速交易端</option></select></label>`;
  }
  if (meta.type === 'fixed_channel') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><input name="${esc(name)}" data-field="${esc(fieldName)}" type="text" value="normal" readonly><small>全推行情只能通过普通 QMT 推送</small></label>`;
  }
  if (meta.type === 'trade_channel') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="trade">极速交易端</option><option value="normal">普通 QMT</option></select></label>`;
  }
  if (meta.type === 'financial_mode') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="filled">填充数据</option><option value="raw">原始数据</option></select></label>`;
  }
  if (meta.type === 'report_type') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="announce_time">公告日期</option><option value="report_time">报告期</option></select></label>`;
  }
  if (meta.type === 'side') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="buy">买入</option><option value="sell">卖出</option></select></label>`;
  }
  if (meta.type === 'textarea') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><textarea name="${esc(name)}" data-field="${esc(fieldName)}" class="code-textarea" placeholder="${esc(meta.placeholder || '')}"></textarea></label>`;
  }
  const inputType = meta.type === 'number' ? 'number' : 'text';
  const step = meta.step ? ` step="${esc(meta.step)}"` : '';
  return `<label class="field${wide}"><span>${esc(meta.label)}</span><input name="${esc(name)}" data-field="${esc(fieldName)}" type="${inputType}"${step} placeholder="${esc(meta.placeholder || '')}" autocomplete="off"></label>`;
}

function setApiDefaults(endpoint) {
  const form = $('apiForm');
  if (!form) return;
  const values = {
    bridge_id: selectedBridge(),
    account_id: selectedAccount(),
    channel: selectedChannel(),
    whole_quote_channel: 'normal',
    trade_channel: selectedTradeChannel(),
    side: 'buy',
    since: '0',
    limit: '50',
    markets: 'SH,SZ',
    quote_subscribe_id: '',
    ...(endpoint.defaults || {}),
  };
  Array.from(form.elements).forEach((element) => {
    const fieldName = element.dataset ? element.dataset.field : '';
    if (!fieldName) return;
    if (values[fieldName] !== undefined) {
      element.value = values[fieldName];
    } else if (values[element.name] !== undefined) {
      element.value = values[element.name];
    }
  });
}

function currentApiRequest() {
  const endpoint = apiEndpointById(state.apiEndpointId);
  if (endpoint.method === 'DOC') {
    return {
      method: 'DOC',
      url: endpoint.path,
      headers: {},
      body: null,
    };
  }
  const params = { ...(endpoint.defaults || {}) };
  const form = $('apiForm');
  Array.from(form.elements).forEach((element) => {
    if (!element.name || element.tagName === 'BUTTON') return;
    params[element.name] = element.value;
  });
  if (endpoint.id === 'batch_order') {
    try {
      params.orders = params.orders_json ? JSON.parse(params.orders_json) : [];
      delete params.orders_json;
    } catch (error) {
      params.orders = [];
      params.orders_json_error = error.message;
    }
  }
  if (endpoint.id === 'quote_subscribe_whole') {
    params.channel = 'normal';
    params.markets = String(params.markets || 'SH,SZ')
      .split(',')
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
  }
  ['code_list', 'stock_list', 'field_list'].forEach((name) => {
    if (params[name] !== undefined && typeof params[name] === 'string') {
      params[name] = params[name].split(',').map((item) => item.trim()).filter(Boolean);
    }
  });
  ['fields', 'table'].forEach((name) => {
    if (params[name] !== undefined && typeof params[name] === 'string' && params[name].includes(',')) {
      params[name] = params[name].split(',').map((item) => item.trim()).filter(Boolean);
    }
  });
  ['count'].forEach((name) => {
    if (params[name] !== undefined && params[name] !== '') params[name] = Number(params[name]);
  });
  ['fill_data', 'iscomplete'].forEach((name) => {
    if (params[name] !== undefined && params[name] !== '') params[name] = ['1', 'true', 'yes', 'on'].includes(String(params[name]).toLowerCase());
  });
  if (params.incrementally === '') delete params.incrementally;
  if (endpoint.method === 'WS') {
    if (state.apiKey) params.apikey = state.apiKey;
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') query.set(key, value);
    });
    return {
      method: endpoint.method,
      url: apiWsUrl(`${endpoint.path}${query.toString() ? `?${query.toString()}` : ''}`),
      headers: {},
      body: null,
    };
  }
  if (endpoint.method === 'GET') {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') query.set(key, value);
    });
    return {
      method: endpoint.method,
      url: apiUrl(`${endpoint.path}${query.toString() ? `?${query.toString()}` : ''}`),
      headers: apiPreviewHeaders(),
      body: null,
    };
  }
  return {
    method: endpoint.method,
    url: apiUrl(endpoint.path),
    headers: apiPreviewHeaders(),
    body: params,
  };
}

function apiPreviewHeaders() {
  return state.apiKey ? { 'X-API-Key': maskApiKey(state.apiKey) } : {};
}

function maskApiKey(value) {
  value = String(value || '');
  if (!value) return '';
  if (value.length <= 8) return '*'.repeat(value.length);
  return `${value.slice(0, 4)}${'*'.repeat(value.length - 8)}${value.slice(-4)}`;
}

function updateApiRequestPreview() {
  const request = currentApiRequest();
  $('apiRequestPreview').textContent = JSON.stringify(request, null, 2);
}

async function sendApiDebugRequest(event) {
  event.preventDefault();
  const request = currentApiRequest();
  if (request.method === 'DOC') {
    return;
  }
  if (request.method === 'WS') {
    connectApiWebSocket(request);
    return;
  }
  if (request.body && request.body.orders_json_error) {
    $('apiResponseBox').textContent = JSON.stringify({ ok: false, error: request.body.orders_json_error }, null, 2);
    return;
  }
  $('apiResponseBox').textContent = '请求中...';
  try {
    const response = await fetch(request.url, {
      method: request.method,
      headers: {
        'Content-Type': 'application/json',
        ...(state.apiKey ? { 'X-API-Key': state.apiKey } : {}),
      },
      body: request.body ? JSON.stringify(request.body) : undefined,
    });
    const text = await response.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch (error) {
      payload = text;
    }
    $('apiResponseBox').textContent = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
    handleApiDebugPayload(payload);
  } catch (error) {
    $('apiResponseBox').textContent = JSON.stringify({ ok: false, error: error.message }, null, 2);
  }
}

function handleApiDebugPayload(payload) {
  if (!payload || !payload.ok || !payload.data) return;
  const endpoint = apiEndpointById(state.apiEndpointId);
  if (endpoint.id === 'quote_subscribe_whole' || endpoint.id === 'quote_subscribe_single') {
    const subscribeId = payload.data.subscribe_id || '';
    if (subscribeId) {
      resetQuoteLive(subscribeId);
      connectQuoteWebSocket(subscribeId);
    }
  }
  if (endpoint.id === 'quote_latest') {
    (payload.data.events || []).forEach((event) => handleQuoteEvent(event));
  }
  if (endpoint.id === 'quote_unsubscribe') {
    stopQuoteLive({ unsubscribe: false });
  }
}

function closeApiSocket() {
  if (!state.apiSocket) return;
  try {
    state.apiSocket.close();
  } catch (error) {
    // ignore stale sockets
  }
  state.apiSocket = null;
}

function stopQuoteLive(options = {}) {
  const subscribeId = String(state.quoteSubscribeId || '');
  const shouldUnsubscribe = !!subscribeId && options.unsubscribe !== false;
  closeApiSocket();
  state.quoteRows.clear();
  state.quoteSeq = 0;
  state.quoteEventCount = 0;
  state.quoteSubscribeId = '';
  state.quoteLiveActive = false;
  state.quoteConnectionText = '未订阅';
  renderQuoteLiveTable();
  if (!shouldUnsubscribe) return;
  const body = {
    bridge_id: selectedBridge(),
    channel: 'normal',
    subscribe_id: subscribeId,
  };
  if (options.beacon && navigator.sendBeacon) {
    try {
      const url = apiUrl(`/api/quotes/unsubscribe${state.apiKey ? `?apikey=${encodeURIComponent(state.apiKey)}` : ''}`);
      const blob = new Blob([JSON.stringify(body)], { type: 'application/json' });
      navigator.sendBeacon(url, blob);
      return;
    } catch (error) {
      // fall through to fetch
    }
  }
  fetch(apiUrl('/api/quotes/unsubscribe'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(state.apiKey ? { 'X-API-Key': state.apiKey } : {}),
    },
    body: JSON.stringify(body),
    keepalive: !!options.beacon,
  }).catch((error) => log('行情订阅释放失败', { subscribe_id: subscribeId, error: error.message }));
}

function connectQuoteWebSocket(subscribeId = '') {
  const params = new URLSearchParams();
  if (subscribeId) params.set('subscribe_id', subscribeId);
  if (state.apiKey) params.set('apikey', state.apiKey);
  state.quoteLiveActive = !!subscribeId;
  const request = {
    method: 'WS',
    url: apiWsUrl(`/ws/quotes${params.toString() ? `?${params.toString()}` : ''}`),
  };
  connectApiWebSocket(request);
}

function connectApiWebSocket(request) {
  if (state.apiSocket) {
    try {
      state.apiSocket.close();
    } catch (error) {
      // ignore stale sockets
    }
  }
  $('apiResponseBox').textContent = `连接中...\n${request.url}`;
  const socket = new WebSocket(request.url);
  state.apiSocket = socket;
  const append = (message) => {
    const box = $('apiResponseBox');
    box.textContent = `${box.textContent}\n${message}`;
    box.scrollTop = box.scrollHeight;
  };
  socket.onopen = () => {
    state.quoteConnectionText = state.quoteLiveActive ? '已连接' : '未订阅';
    renderQuoteLiveTable();
    append('WebSocket 已连接');
  };
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      append(JSON.stringify(payload, null, 2));
      if (payload.type === 'quote' && payload.event && state.quoteLiveActive) {
        handleQuoteEvent(payload.event);
      }
    } catch (error) {
      append(event.data);
    }
  };
  socket.onerror = () => {
    state.quoteConnectionText = '连接错误';
    renderQuoteLiveTable();
    append('WebSocket 连接错误');
  };
  socket.onclose = () => {
    state.quoteConnectionText = state.quoteLiveActive ? '已关闭' : '未订阅';
    renderQuoteLiveTable();
    append('WebSocket 已关闭');
  };
}

function handleQuoteEvent(event) {
  if (!state.quoteLiveActive) return;
  if (state.quoteSubscribeId && String(event.subscribe_id || '') !== String(state.quoteSubscribeId)) return;
  const panel = $('quoteLivePanel');
  if (panel) panel.classList.remove('hidden');
  state.quoteEventCount += 1;
  state.quoteSeq = Math.max(state.quoteSeq, Number(event.seq || state.quoteSeq || 0));
  const data = event.data || {};
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    Object.entries(data).forEach(([code, value]) => {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        upsertQuoteRow(code, value, event);
      }
    });
    if (!Object.keys(data).length) {
      upsertQuoteRow(event.subscribe_id || '--', data, event);
    }
  } else {
    upsertQuoteRow(event.subscribe_id || '--', { value: data }, event);
  }
  renderQuoteLiveTable();
}

function upsertQuoteRow(code, quote, event) {
  const normalized = {
    code,
    updatedAt: Date.now(),
    price: quote.lastPrice ?? quote.last_price ?? quote.price ?? quote.close ?? quote.now ?? quote.value ?? '',
    pct: quote.ratio ?? quote.pct_chg ?? quote.changeRatio ?? quote.change_ratio ?? quote['涨跌幅'] ?? '',
    volume: quote.volume ?? quote.vol ?? quote['成交量'] ?? '',
    time: formatQuoteTime(quote.time ?? quote.timetag ?? quote.datetime ?? quote.updateTime ?? quote.update_time, event),
    raw: quote,
  };
  state.quoteRows.set(String(code), normalized);
  trimQuoteRows();
}

function trimQuoteRows(maxRows = 80) {
  if (state.quoteRows.size <= maxRows) return;
  const keep = Array.from(state.quoteRows.entries())
    .sort((a, b) => (b[1].updatedAt || 0) - (a[1].updatedAt || 0))
    .slice(0, maxRows);
  state.quoteRows = new Map(keep);
}

function renderQuoteLiveTable() {
  const body = $('quoteLiveBody');
  const status = $('quoteLiveStatus');
  if (!body) return;
  const rows = Array.from(state.quoteRows.values())
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, 80);
  body.innerHTML = rows.map((row) => `<tr>
    <td>${esc(row.code)}</td>
    <td class="num">${plain(row.price)}</td>
    <td class="num">${plain(row.pct)}</td>
    <td class="num">${plain(row.volume)}</td>
    <td>${plain(row.time)}</td>
  </tr>`).join('') || '<tr><td colspan="5">等待行情推送</td></tr>';
  if (status) {
    const subText = state.quoteSubscribeId ? ` #${state.quoteSubscribeId}` : '';
    status.textContent = `${state.quoteConnectionText}${subText} · ${state.quoteEventCount || 0} 次推送 · ${rows.length} 条 / seq ${state.quoteSeq || 0}`;
  }
}

function setView(view) {
  if (!document.querySelector(`.nav-item[data-view="${view}"]`)) {
    view = 'overview';
  }
  const leavingApi = state.currentView === 'api' && view !== 'api';
  if (leavingApi) {
    stopQuoteLive();
  }
  state.currentView = view;
  localStorage.setItem('cfquant.view', view);
  document.body.dataset.view = view;
  const titleMap = {
    overview: '概览',
    trade: '交易',
    orders: '委托',
    status: '状态',
    bindings: '绑定',
    callbacks: '回调',
    api: '接口',
    settings: '设置',
    tutorial: '教程',
  };
  $('viewTitle').textContent = titleMap[view] || view;
  document.querySelectorAll('.nav-item').forEach((node) => {
    node.classList.toggle('active', node.dataset.view === view);
  });
  document.querySelectorAll('.view-panel').forEach((node) => {
    node.classList.toggle('hidden', !node.classList.contains(`view-${view}`));
  });
}

function setDataTab(name, shouldRefresh = true) {
  if (!document.querySelector(`.data-tab[data-tab="${name}"]`)) {
    name = 'positions';
  }
  localStorage.setItem('cfquant.trade_tab', name);
  document.querySelectorAll('.data-tab').forEach((item) => {
    item.classList.toggle('active', item.dataset.tab === name);
  });
  document.querySelectorAll('.tab-pane').forEach((pane) => {
    pane.classList.toggle('active', pane.dataset.pane === name);
  });
  if (shouldRefresh && name === 'trades') {
    refreshAccount('trades').catch((error) => log('成交刷新失败', { error: error.message }));
  }
  if (shouldRefresh && name === 'orders') {
    refreshAccount('orders').catch((error) => log('委托刷新失败', { error: error.message }));
  }
}

function loadAccountPairs() {
  const pairs = {};
  Object.entries(state.accountPairs || {}).forEach(([accountId, pair]) => {
    if (pair && typeof pair === 'object') pairs[accountId] = pair.bridge_id;
    else pairs[accountId] = pair;
  });
  if (Object.keys(pairs).length) return pairs;
  try {
    const value = JSON.parse(localStorage.getItem(ACCOUNT_PAIR_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch (error) {
    return {};
  }
}

function saveAccountPairs(pairs) {
  localStorage.setItem(ACCOUNT_PAIR_KEY, JSON.stringify(pairs || {}));
}

function bridgeOptionExists(bridgeId) {
  const select = $('bridgeSelect');
  return Array.from(select.options).some((option) => option.value === bridgeId);
}

function renderAccountPairs() {
  const list = $('accountPairList');
  if (!list) return;
  const pairs = loadAccountPairs();
  const entries = Object.entries(pairs).filter(([accountId, bridgeId]) => accountId && bridgeId);
  $('accountPairCount').textContent = `${entries.length} 组`;
  list.innerHTML = '';
  if (!entries.length) {
    const empty = document.createElement('div');
    empty.className = 'metric-note';
    empty.textContent = '暂无配对';
    list.appendChild(empty);
    return;
  }
  entries.forEach(([accountId, bridgeId]) => {
    const row = document.createElement('div');
    row.className = 'pair-row';
    const label = document.createElement('span');
    label.textContent = `${accountId} -> ${bridgeId}`;
    const useBtn = document.createElement('button');
    useBtn.type = 'button';
    useBtn.textContent = '使用';
    useBtn.dataset.accountId = accountId;
    useBtn.dataset.bridgeId = bridgeId;
    row.appendChild(label);
    row.appendChild(useBtn);
    list.appendChild(row);
  });
}

async function saveCurrentAccountPair() {
  const accountId = selectedAccount();
  const bridgeId = selectedBridge();
  if (!accountId) {
    log('账号为空，无法保存配对');
    return;
  }
  const data = await api('/api/account-pairs', {
    method: 'POST',
    body: JSON.stringify({ account_id: accountId, bridge_id: bridgeId }),
  });
  state.accountPairs = data.account_pairs || {};
  renderAccountPairs();
  await refreshBindingStatuses();
  log('账号配对已保存', { account_id: accountId, bridge_id: bridgeId });
}

async function removeCurrentAccountPair() {
  const accountId = selectedAccount();
  if (!accountId) return;
  const data = await api('/api/account-pairs/delete', {
    method: 'POST',
    body: JSON.stringify({ account_id: accountId }),
  });
  state.accountPairs = data.account_pairs || {};
  renderAccountPairs();
  await refreshBindingStatuses();
  log('账号配对已移除', { account_id: accountId });
}

function applyAccountPair(accountId) {
  accountId = String(accountId || '').trim();
  if (!accountId) return false;
  const bridgeId = loadAccountPairs()[accountId];
  if (!bridgeId || !bridgeOptionExists(bridgeId)) return false;
  $('bridgeSelect').value = bridgeId;
  selectedBridge();
  return true;
}

function syncBindingForm() {
  const form = $('bindingForm');
  if (!form) return;
  form.account_id.value = $('accountInput').value.trim();
  if (bridgeOptionExists(selectedBridge())) {
    form.bridge_id.value = selectedBridge();
  }
}

function selectAccountPair(accountId, bridgeId) {
  if (accountId) {
    $('accountInput').value = accountId;
    selectedAccount();
  }
  if (bridgeId && bridgeOptionExists(bridgeId)) {
    $('bridgeSelect').value = bridgeId;
    selectedBridge();
  }
  syncBindingForm();
  resetSelectionState();
  refreshStatus().catch((error) => log('账号配对状态刷新失败', { error: error.message }));
  refreshAccount('asset,positions').catch((error) => log('账号配对资产刷新失败', { error: error.message }));
  refreshAccount('orders').catch((error) => log('账号配对委托刷新失败', { error: error.message }));
  refreshAccount('trades').catch((error) => log('账号配对成交刷新失败', { error: error.message }));
}

function renderBridgeConfigList() {
  const list = $('bridgeConfigList');
  if (!list) return;
  const bridges = state.bridges || {};
  const envBridgeIds = new Set(Object.keys(state.envBridges || {}));
  list.innerHTML = '';
  Object.entries(bridges).forEach(([bridgeId, bridge]) => {
    const row = document.createElement('div');
    row.className = 'config-row';
    const label = document.createElement('span');
    const strong = document.createElement('strong');
    strong.textContent = `${plain(bridge.name || bridgeId)} (${plain(bridgeId)})`;
    label.appendChild(strong);
    label.appendChild(document.createTextNode('自动频道'));
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.textContent = '编辑';
    editBtn.dataset.action = 'edit';
    editBtn.dataset.bridgeId = bridgeId;
    row.appendChild(label);
    row.appendChild(editBtn);
    if (!envBridgeIds.has(bridgeId)) {
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.textContent = '删除';
      deleteBtn.dataset.action = 'delete';
      deleteBtn.dataset.bridgeId = bridgeId;
      row.appendChild(deleteBtn);
    }
    list.appendChild(row);
  });
}

function fillBridgeForm(bridgeId) {
  const bridge = (state.bridges || {})[bridgeId];
  if (!bridge) return;
  const form = $('bridgeForm');
  form.id.value = bridgeId;
  form.name.value = bridge.name || bridgeId;
}

async function submitBridgeForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = {
    id: form.id.value.trim(),
    name: form.name.value.trim(),
    channels: {},
  };
  try {
    const data = await api('/api/bridges', { method: 'POST', body: JSON.stringify(body) });
    if (data.bridges) state.bridges = data.bridges;
    renderBridgeConfigList();
    await refreshConfig();
    log('桥接端已保存', { bridge_id: body.id });
  } catch (error) {
    log('桥接端保存失败', { error: error.message });
  }
}

async function submitBindingForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const accountId = form.account_id.value.trim();
  const bridgeId = form.bridge_id.value;
  if (!accountId) {
    log('账号为空，无法保存绑定');
    return;
  }
  try {
    const data = await api('/api/account-pairs', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId, bridge_id: bridgeId }),
    });
    state.accountPairs = data.account_pairs || {};
    $('accountInput').value = accountId;
    selectedAccount();
    if (bridgeId && bridgeOptionExists(bridgeId)) {
      $('bridgeSelect').value = bridgeId;
      selectedBridge();
    }
    renderAccountPairs();
    await refreshBindingStatuses();
    log('账号绑定已保存', { account_id: accountId, bridge_id: bridgeId });
  } catch (error) {
    log('账号绑定保存失败', { error: error.message });
  }
}

async function deleteBridge(bridgeId) {
  const confirmed = window.confirm(`确认删除桥接端 ${bridgeId}？相关账号配对也会移除。`);
  if (!confirmed) return;
  try {
    const data = await api('/api/bridges/delete', {
      method: 'POST',
      body: JSON.stringify({ bridge_id: bridgeId }),
    });
    renderBridgeSelect(data.bridges || {});
    state.accountPairs = data.account_pairs || {};
    renderAccountPairs();
    renderBridgeConfigList();
    await refreshBindingStatuses();
    log('桥接端已删除', { bridge_id: bridgeId });
  } catch (error) {
    log('桥接端删除失败', { bridge_id: bridgeId, error: error.message });
  }
}

async function refreshConfig() {
  const currentBridgeId = selectedBridge();
  const data = await api('/api/config');
  state.envBridges = data.env_bridges || {};
  state.accountPairs = data.account_pairs || {};
  state.bridgeId = data.bridges && data.bridges[currentBridgeId] ? currentBridgeId : (data.default_bridge_id || Object.keys(data.bridges || {})[0] || 'default');
  renderBridgeSelect(data.bridges || {});
  renderAccountPairs();
  renderBridgeConfigList();
  renderApiDocs(state.apiEndpointId);
  await refreshBindingStatuses();
}

async function refreshBindingStatuses() {
  const body = $('bindingStatusBody');
  const overviewBody = $('overviewBindingBody');
  const pairs = state.accountPairs || {};
  const pairEntries = Object.values(pairs).filter((pair) => pair && pair.account_id && pair.bridge_id);
  const bridgeIds = new Set(Object.keys(state.bridges || {}));
  pairEntries.forEach((pair) => bridgeIds.add(pair.bridge_id));
  bridgeIds.add('default');
  const entries = [
    ...pairEntries.map((pair) => ({ kind: 'pair', pair, bridge_id: pair.bridge_id, account_id: pair.account_id })),
    ...Array.from(bridgeIds)
      .filter((bridgeId) => !pairEntries.some((pair) => pair.bridge_id === bridgeId))
      .map((bridgeId) => ({ kind: 'bridge', bridge_id: bridgeId, account_id: '' })),
  ].filter((item) => state.bridges[item.bridge_id]);
  if (!entries.length) {
    if (body) body.innerHTML = '<tr><td colspan="5">暂无账号配对</td></tr>';
    if (overviewBody) overviewBody.innerHTML = '<tr><td colspan="4">暂无账号配对</td></tr>';
    $('overviewBindingCount').textContent = '0 组';
    renderPairVerification(null);
    return;
  }
  const rows = await Promise.all(entries.map(async (entry) => {
    try {
      const status = await api(`/api/status?bridge_id=${encodeURIComponent(entry.bridge_id)}`);
      return { item: entry, status };
    } catch (error) {
      return { item: entry, error };
    }
  }));
  if (body) {
    body.innerHTML = rows.map(({ item, status, error }) => bindingStatusRowHtml(item, status, error, true)).join('');
  }
  if (overviewBody) {
    const overviewRows = rows.filter(({ item }) => item.kind === 'pair');
    overviewBody.innerHTML = overviewRows.length
      ? overviewRows.map(({ item, status, error }) => bindingStatusRowHtml(item, status, error, false)).join('')
      : '<tr><td colspan="4">暂无账号配对</td></tr>';
    $('overviewBindingCount').textContent = `${overviewRows.length} 组`;
  }
}

function bindingStatusRowHtml(item, status, error, withVerify) {
  const normalOnline = status && status.normal && status.normal.online;
  const tradeOnline = status && status.trade && status.trade.online;
  const title = error ? error.message : '';
  const accountText = item.account_id || '未绑定';
  const verifyCell = withVerify
    ? `<td>${item.account_id ? `<button class="verify-pair-btn" data-account-id="${esc(item.account_id)}" data-bridge-id="${esc(item.bridge_id)}">查资金/持仓</button>` : '--'}</td>`
    : '';
  return `<tr title="${esc(title)}">
    <td>${esc(accountText)}</td>
    <td>${esc(item.bridge_id)}</td>
    <td><span class="status-dot ${normalOnline ? 'online' : 'offline'}">${normalOnline ? '在线' : '离线'}</span></td>
    <td><span class="status-dot ${tradeOnline ? 'online' : 'offline'}">${tradeOnline ? '在线' : '离线'}</span></td>
    ${verifyCell}
  </tr>`;
}

async function verifyPair(accountId, bridgeId) {
  $('pairVerifyNote').textContent = `${accountId} / ${bridgeId}`;
  try {
    const data = await api('/api/account-pairs/verify', {
      method: 'POST',
      body: JSON.stringify({
        account_id: accountId,
        bridge_id: bridgeId,
        channel: selectedChannel(),
        force: 1,
      }),
    });
    renderPairVerification(data);
    log('账号配对验证完成', { account_id: accountId, bridge_id: bridgeId });
  } catch (error) {
    renderPairVerification(null);
    $('pairVerifyNote').textContent = `验证失败：${error.message}`;
    log('账号配对验证失败', { account_id: accountId, bridge_id: bridgeId, error: error.message });
  }
}

function renderPairVerification(payload) {
  const asset = payload && payload.account && payload.account.asset;
  const assetRow = firstRow(asset);
  const values = [
    assetRow.balance ?? assetRow.m_dBalance,
    assetRow.available ?? assetRow.m_dAvailable,
    assetRow.market_value ?? assetRow.m_dInstrumentValue,
    assetRow.position_profit ?? assetRow.m_dPositionProfit,
  ];
  const assetGrid = $('pairAssetGrid');
  if (assetGrid) {
    const cells = assetGrid.querySelectorAll('strong');
    values.forEach((value, index) => {
      cells[index].textContent = money(value);
      cells[index].className = index === 3 ? signedClass(value) : '';
    });
  }
  const positions = payload && payload.account && payload.account.positions && Array.isArray(payload.account.positions.data)
    ? payload.account.positions.data
    : [];
  const html = positions.map((row) => {
    const profit = row.position_profit ?? row.m_dPositionProfit;
    return `<tr>
      <td>${esc(row.stock_code || `${row.m_strInstrumentID || ''}.${row.m_strExchangeID || ''}`)}</td>
      <td>${esc(row.instrument_name || row.m_strInstrumentName)}</td>
      <td class="num">${esc(row.volume ?? row.m_nVolume)}</td>
      <td class="num">${esc(row.can_use_volume ?? row.m_nCanUseVolume)}</td>
      <td class="num ${signedClass(profit)}">${money(row.market_value ?? row.m_dInstrumentValue)}</td>
    </tr>`;
  }).join('');
  $('pairPositionsBody').innerHTML = html || '<tr><td colspan="5">无持仓数据</td></tr>';
}

function setStatus(id, online, detail) {
  const node = $(id);
  node.classList.toggle('online', !!online);
  node.classList.toggle('offline', !online);
  node.title = detail || '';
}

function renderBridgeSelect(bridges) {
  state.bridges = bridges || {};
  const bridgeSelect = $('bridgeSelect');
  const current = bridgeSelect.value || state.bridgeId;
  const optionsHtml = Object.keys(state.bridges).map((id) => {
    const bridge = state.bridges[id] || {};
    return `<option value="${plain(id)}">${plain(bridge.name || id)}</option>`;
  }).join('');
  bridgeSelect.innerHTML = optionsHtml;
  const bindingBridgeSelect = $('bindingBridgeSelect');
  const bindingCurrent = bindingBridgeSelect ? bindingBridgeSelect.value : '';
  if (bindingBridgeSelect) {
    bindingBridgeSelect.innerHTML = optionsHtml;
    if (bindingCurrent && state.bridges[bindingCurrent]) {
      bindingBridgeSelect.value = bindingCurrent;
    }
  }
  if (current && state.bridges[current]) {
    bridgeSelect.value = current;
    state.bridgeId = current;
  } else if (state.bridges[state.bridgeId]) {
    bridgeSelect.value = state.bridgeId;
  } else {
    state.bridgeId = Object.keys(state.bridges)[0] || 'default';
    bridgeSelect.value = state.bridgeId;
  }
}

function renderLttxStatus(data) {
  state.lttxStatus = data || null;
  const running = !!(data && data.running);
  const processes = data && Array.isArray(data.processes) ? data.processes : [];
  const processText = processes.map((item) => `${item.pid || ''} ${item.name || ''}`.trim()).filter(Boolean).join(', ');
  const detail = data ? `${data.host}:${data.port} ${running ? '运行中' : '未运行'}${processText ? ` / ${processText}` : ''}` : '';
  setStatus('lttxStatus', running, detail);

  const startBtn = $('lttxStartBtn');
  const stopBtn = $('lttxStopBtn');
  if (startBtn) startBtn.disabled = !!(data && !data.can_start);
  if (stopBtn) stopBtn.disabled = !(data && data.can_stop);

  const runtime = $('lttxRuntime');
  if (!runtime) return;
  if (!data) {
    runtime.textContent = 'LTtx 状态未知';
  } else if (!running) {
    runtime.textContent = `LTtx 未运行，可通过网页或 cfquant\\start_cfquant.bat 启动。`;
  } else if (data.can_stop) {
    runtime.textContent = `LTtx 运行中，可管理 PID：${(data.managed_pids || []).join(', ') || '--'}。`;
  } else {
    runtime.textContent = `2049 已监听，但无法确认是本系统启动的 LTtx，网页不会强制停止它。`;
  }
}

async function refreshLttxStatus(options = {}) {
  try {
    const data = await api('/api/lttx');
    renderLttxStatus(data);
    return data;
  } catch (error) {
    setStatus('lttxStatus', false, error.message);
    renderLttxStatus(null);
    if (options.log !== false) {
      log('LTtx 状态检查失败', { error: error.message });
    }
    return null;
  }
}

async function loadConfig() {
  const data = await api('/api/config');
  state.accountId = localStorage.getItem('cfquant.account') || data.default_account_id || '';
  $('accountInput').value = state.accountId;
  const bridges = data.bridges || {};
  state.envBridges = data.env_bridges || {};
  state.accountPairs = data.account_pairs || {};
  state.bridgeId = localStorage.getItem('cfquant.bridge_id') || data.default_bridge_id || 'default';
  if (!bridges[state.bridgeId]) {
    state.bridgeId = data.default_bridge_id || Object.keys(bridges)[0] || 'default';
  }
  renderBridgeSelect(bridges);
  applyAccountPair(state.accountId);
  syncBindingForm();
  const queryChannel = localStorage.getItem('cfquant.query_channel');
  if (queryChannel && $('queryChannel').querySelector(`option[value="${queryChannel}"]`)) {
    $('queryChannel').value = queryChannel;
    state.queryChannel = queryChannel;
  }
  const tradeChannel = localStorage.getItem('cfquant.trade_channel');
  if (tradeChannel && $('tradeChannel').querySelector(`option[value="${tradeChannel}"]`)) {
    $('tradeChannel').value = tradeChannel;
  }
  renderAccountPairs();
  renderBridgeConfigList();
  renderApiKeyStatus(data.api_key);
  const apiBaseInput = $('apiBaseUrlInput');
  if (apiBaseInput) {
    const savedBaseUrl = data.server_access && data.server_access.api_base_url
      ? data.server_access.api_base_url
      : window.location.origin;
    apiBaseInput.value = normalizeApiBaseUrl(savedBaseUrl);
  }
  renderServerAccess(data.server_access);
  refreshBindingStatuses().catch((error) => log('绑定状态初始化失败', { error: error.message }));
  log('Web TX', { reply_channel: data.reply_channel });
}

async function refreshStatus() {
  const lttxPromise = refreshLttxStatus({ log: false });
  try {
    const data = await api(`/api/status?bridge_id=${encodeURIComponent(selectedBridge())}`);
    const lttx = await lttxPromise;
    setStatus('normalStatus', data.normal.online, data.normal.error || data.normal.channel);
    setStatus('tradeStatus', data.trade.online, data.trade.error || data.trade.channel);
    $('statusDetail').textContent = JSON.stringify({ lttx, bridge: data }, null, 2);
  } catch (error) {
    const lttx = await lttxPromise;
    setStatus('normalStatus', false, error.message);
    setStatus('tradeStatus', false, error.message);
    $('statusDetail').textContent = JSON.stringify({ lttx, error: error.message }, null, 2);
    log('状态检查失败', { error: error.message });
  }
}

async function startLttx() {
  const startBtn = $('lttxStartBtn');
  const stopBtn = $('lttxStopBtn');
  if (startBtn) startBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = true;
  try {
    const data = await api('/api/lttx/start', { method: 'POST', body: '{}' });
    renderLttxStatus(data.status);
    log(data.started ? 'LTtx 已启动' : 'LTtx 已在运行', data);
    await refreshStatus();
  } catch (error) {
    log('LTtx 启动失败', { error: error.message });
    await refreshLttxStatus({ log: false });
  }
}

async function stopLttx() {
  const confirmed = window.confirm('确认停止 LTtx 服务？停止后桥接通道会离线。');
  if (!confirmed) return;
  const startBtn = $('lttxStartBtn');
  const stopBtn = $('lttxStopBtn');
  if (startBtn) startBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = true;
  try {
    const data = await api('/api/lttx/stop', { method: 'POST', body: '{}' });
    renderLttxStatus(data.status);
    log(data.stopped ? 'LTtx 已停止' : 'LTtx 未运行', data);
    await refreshStatus();
  } catch (error) {
    log('LTtx 停止失败', { error: error.message });
    await refreshLttxStatus({ log: false });
  }
}

function selectedAccount() {
  const accountId = $('accountInput').value.trim();
  localStorage.setItem('cfquant.account', accountId);
  state.accountId = accountId;
  return accountId;
}

function selectedBridge() {
  const bridgeId = $('bridgeSelect').value || state.bridgeId || 'default';
  localStorage.setItem('cfquant.bridge_id', bridgeId);
  state.bridgeId = bridgeId;
  return bridgeId;
}

function selectedChannel() {
  state.queryChannel = $('queryChannel').value;
  localStorage.setItem('cfquant.query_channel', state.queryChannel);
  return state.queryChannel;
}

function selectedTradeChannel() {
  const channel = $('tradeChannel').value || 'trade';
  localStorage.setItem('cfquant.trade_channel', channel);
  return channel;
}

function resetSelectionState() {
  state.callbackSeq = 0;
  state.callbackEvents = [];
  state.orderSnapshot.clear();
  renderCallbacks();
}

function refreshCurrentSelection(reason) {
  refreshStatus().catch((error) => log(`${reason}状态刷新失败`, { error: error.message }));
  refreshAccount('asset,positions').catch((error) => log(`${reason}资产刷新失败`, { error: error.message }));
  refreshAccount('orders').catch((error) => log(`${reason}委托刷新失败`, { error: error.message }));
  refreshAccount('trades').catch((error) => log(`${reason}成交刷新失败`, { error: error.message }));
}

function handleBridgeChange() {
  selectedBridge();
  syncBindingForm();
  resetSelectionState();
  refreshCurrentSelection('桥接端');
}

function handleAccountChange() {
  const accountId = selectedAccount();
  applyAccountPair(accountId);
  syncBindingForm();
  resetSelectionState();
  refreshCurrentSelection('账号');
}

function firstRow(section) {
  const data = section && section.data;
  if (Array.isArray(data)) return data[0] || {};
  return data || {};
}

function renderAsset(section) {
  const row = firstRow(section);
  const values = [
    row.balance ?? row.m_dBalance,
    row.available ?? row.m_dAvailable,
    row.market_value ?? row.m_dInstrumentValue,
    row.position_profit ?? row.m_dPositionProfit,
  ];
  const cells = $('assetGrid').querySelectorAll('strong');
  values.forEach((value, index) => {
    cells[index].textContent = money(value);
    cells[index].className = index === 3 ? signedClass(value) : '';
  });
  $('assetLatency').textContent = section && section.latency_ms ? `${section.latency_ms} ms` : '';
}

function renderPositions(section) {
  const rows = (section && Array.isArray(section.data)) ? section.data : [];
  $('positionCount').textContent = `${rows.length} 条`;
  const html = positionRowsHtml(rows);
  $('positionsBody').innerHTML = html || '<tr><td colspan="7">无持仓数据</td></tr>';
  const tradeBody = $('tradePositionsBody');
  if (tradeBody) {
    tradeBody.innerHTML = html || '<tr><td colspan="7">无持仓数据</td></tr>';
  }
}

function positionRowsHtml(rows) {
  return rows.map((row) => {
    const profit = row.position_profit ?? row.m_dPositionProfit;
    return `<tr>
      <td>${plain(row.stock_code || `${row.m_strInstrumentID || ''}.${row.m_strExchangeID || ''}`)}</td>
      <td>${plain(row.instrument_name || row.m_strInstrumentName)}</td>
      <td class="num">${plain(row.volume ?? row.m_nVolume)}</td>
      <td class="num">${plain(row.can_use_volume ?? row.m_nCanUseVolume)}</td>
      <td class="num">${money(row.open_price ?? row.m_dOpenPrice)}</td>
      <td class="num">${money(row.market_value ?? row.m_dInstrumentValue)}</td>
      <td class="num ${signedClass(profit)}">${money(profit)}</td>
    </tr>`;
  }).join('');
}

function orderKey(row) {
  return String(row.m_strOrderSysID || row.m_strOrderID || row.order_id || row.m_nOrderID || '');
}

function orderCode(row) {
  return row.stock_code || `${row.m_strInstrumentID || ''}.${row.m_strExchangeID || ''}`;
}

function orderName(row) {
  return row.instrument_name || row.m_strInstrumentName || row.stock_name || row.name || '';
}

function orderVolume(row) {
  return Number(row.order_volume ?? row.m_nVolumeTotalOriginal ?? 0);
}

function tradedVolume(row) {
  return Number(row.traded_volume ?? row.m_nVolumeTraded ?? 0);
}

function rawOrderStatus(row) {
  return row.order_status ?? row.m_nOrderStatus ?? row.m_strOrderStatus ?? row.m_nOrderState ?? row.m_strStatus ?? '';
}

function isCancelableOrder(row) {
  const id = orderKey(row);
  const volume = orderVolume(row);
  const traded = tradedVolume(row);
  if (!id || volume <= 0 || traded >= volume) return false;

  const status = mappedStatus(rawOrderStatus(row), ORDER_STATUS_MAP);
  const nonCancelableStatuses = new Set([
    '已报待撤',
    '部成待撤',
    '部撤',
    '已撤',
    '已成',
    '废单',
  ]);
  return !nonCancelableStatuses.has(status);
}

function orderStatus(row) {
  const orderValue = rawOrderStatus(row);
  if (hasValue(orderValue)) return mappedStatus(orderValue, ORDER_STATUS_MAP);

  const submitValue = row.order_submit_status ?? row.entrust_submit_status ?? row.m_nSubmitStatus ?? row.m_nEntrustSubmitStatus;
  if (hasValue(submitValue)) return mappedStatus(submitValue, SUBMIT_STATUS_MAP);

  return row.m_strStatusMsg || '';
}

const ORDER_TIME_FIELDS = [
  'order_time',
  'entrust_time',
  'insert_time',
  'm_strOrderTime',
  'm_strEntrustTime',
  'm_strInsertTime',
  'm_nOrderTime',
  'm_nEntrustTime',
  'm_nInsertTime',
];

const ORDER_DATE_FIELDS = [
  'order_date',
  'entrust_date',
  'm_strOrderDate',
  'm_strEntrustDate',
  'm_strTradingDay',
  'm_nOrderDate',
  'm_nEntrustDate',
];

const TRADE_TIME_FIELDS = [
  'trade_time',
  'deal_time',
  'm_strTradeTime',
  'm_strDealTime',
  'm_nTradeTime',
  'm_nDealTime',
];

const TRADE_DATE_FIELDS = [
  'trade_date',
  'deal_date',
  'm_strTradeDate',
  'm_strDealDate',
  'm_strTradingDay',
  'm_nTradeDate',
  'm_nDealDate',
];

function firstField(row, fields) {
  for (const field of fields) {
    if (hasValue(row[field])) return row[field];
  }
  return '';
}

function formatDatePart(value) {
  if (!hasValue(value)) return '';
  const digits = String(value).trim().replace(/\D/g, '');
  if (digits.length < 8) return '';
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
}

function formatClockPart(value) {
  if (!hasValue(value)) return '';
  const text = String(value).trim();
  if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(text)) {
    return text.length === 5 ? `${text}:00` : text;
  }
  const digits = text.replace(/\D/g, '');
  if (!digits) return '';
  if (digits.length <= 6) {
    const padded = digits.padStart(6, '0');
    return `${padded.slice(0, 2)}:${padded.slice(2, 4)}:${padded.slice(4, 6)}`;
  }
  return '';
}

function formatTradeDataTime(value, dateValue) {
  if (!hasValue(value)) return '--';
  const text = String(value).trim();
  if (/^\d{4}[-/]\d{1,2}[-/]\d{1,2}/.test(text)) {
    return text.replace('T', ' ').replace(/\//g, '-').slice(0, 19);
  }
  const digits = text.replace(/\D/g, '');
  if (digits.length === 13 && digits.startsWith('1')) {
    return new Date(Number(digits)).toLocaleString('zh-CN', { hour12: false });
  }
  if (digits.length === 10 && digits.startsWith('1')) {
    return new Date(Number(digits) * 1000).toLocaleString('zh-CN', { hour12: false });
  }
  if (digits.length >= 14) {
    return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)} ${digits.slice(8, 10)}:${digits.slice(10, 12)}:${digits.slice(12, 14)}`;
  }
  if (digits.length === 12) {
    return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)} ${digits.slice(8, 10)}:${digits.slice(10, 12)}:00`;
  }
  const clock = formatClockPart(text);
  if (clock) {
    const date = formatDatePart(dateValue);
    return date ? `${date} ${clock}` : clock;
  }
  return text;
}

function orderTime(row) {
  return formatTradeDataTime(firstField(row, ORDER_TIME_FIELDS), firstField(row, ORDER_DATE_FIELDS));
}

function tradeTime(row) {
  return formatTradeDataTime(firstField(row, TRADE_TIME_FIELDS), firstField(row, TRADE_DATE_FIELDS));
}

function trackOrderEvents(rows) {
  rows.forEach((row) => {
    const id = orderKey(row);
    if (!id) return;
    const snapshot = {
      code: orderCode(row),
      order_id: id,
      volume: row.order_volume ?? row.m_nVolumeTotalOriginal,
      traded: row.traded_volume ?? row.m_nVolumeTraded,
      status: orderStatus(row),
    };
    const previous = state.orderSnapshot.get(id);
    const changed = !previous || JSON.stringify(previous) !== JSON.stringify(snapshot);
    if (changed) {
      state.orderSnapshot.set(id, snapshot);
      addCallbackEvent(previous ? '委托更新' : '委托出现', snapshot);
    }
  });
}

function addCallbackEvent(type, data) {
  state.callbackEvents.unshift({
    time: nowText(),
    type,
    ...data,
  });
  state.callbackEvents = state.callbackEvents.slice(0, 200);
  renderCallbacks();
}

function normalizeCallbackEvent(event) {
  const data = event.data || event;
  const eventName = event.event || event.type || 'callback';
  return {
    time: event.received_at ? new Date(event.received_at * 1000).toLocaleString('zh-CN', { hour12: false }) : nowText(),
    type: eventName,
    code: data.stock_code || `${data.m_strInstrumentID || ''}.${data.m_strExchangeID || ''}`,
    order_id: data.m_strOrderSysID || data.m_strOrderID || data.m_nOrderID || '',
    volume: data.m_nVolumeTotalOriginal ?? data.m_nVolume ?? '',
    traded: data.m_nVolumeTraded ?? '',
    status: orderStatus(data) || data.m_strStatusMsg || '',
  };
}

async function refreshCallbacks() {
  try {
    const payload = await api(`/api/callbacks?bridge_id=${encodeURIComponent(selectedBridge())}&account_id=${encodeURIComponent(selectedAccount())}&since=${state.callbackSeq}&limit=200`);
    const events = payload.events || [];
    if (!events.length) return;
    events.forEach((event) => {
      state.callbackSeq = Math.max(state.callbackSeq, Number(event.seq || 0));
      const normalized = normalizeCallbackEvent(event);
      state.callbackEvents.unshift(normalized);
    });
    state.callbackEvents = state.callbackEvents.slice(0, 200);
    renderCallbacks();
    const shouldRefreshOrders = events.some((event) => String(event.event || '').includes('order') || String(event.event || '').includes('trade'));
    if (shouldRefreshOrders) {
      refreshAccount('orders').catch((error) => log('回调刷新委托失败', { error: error.message }));
    }
  } catch (error) {
    log('回调拉取失败', { error: error.message });
  }
}

function renderCallbacks() {
  $('callbackCount').textContent = `${state.callbackEvents.length} 条`;
  const html = state.callbackEvents.map((row) => `<tr>
    <td>${plain(row.time)}</td>
    <td>${plain(row.type)}</td>
    <td>${plain(row.code)}</td>
    <td>${plain(row.order_id)}</td>
    <td class="num">${plain(row.volume)}</td>
    <td class="num">${plain(row.traded)}</td>
    <td>${plain(row.status)}</td>
  </tr>`).join('');
  $('callbacksBody').innerHTML = html || '<tr><td colspan="7">暂无回调事件</td></tr>';
}

function renderOrders(section) {
  const rows = (section && Array.isArray(section.data)) ? section.data : [];
  trackOrderEvents(rows);
  const cancelableCount = rows.filter(isCancelableOrder).length;
  $('orderCount').textContent = `${rows.length} 条 / ${cancelableCount} 条可撤`;
  const html = orderRowsHtml(rows);
  $('ordersBody').innerHTML = html || '<tr><td colspan="8">无委托数据</td></tr>';
  const tradeBody = $('tradeOrdersBody');
  if (tradeBody) {
    tradeBody.innerHTML = orderRowsHtml(rows, { includeTime: true }) || '<tr><td colspan="9">无委托数据</td></tr>';
  }
  $('selectAllOrders').checked = false;
  const tradeSelectAll = $('selectAllTradeOrders');
  if (tradeSelectAll) tradeSelectAll.checked = false;
}

function orderRowsHtml(rows, options = {}) {
  const includeTime = !!options.includeTime;
  return rows.slice().reverse().map((row, index) => {
    const code = orderCode(row);
    const orderId = orderKey(row);
    const cancelable = isCancelableOrder(row);
    return `<tr class="clickable" data-order-id="${plain(orderId)}" data-code="${plain(code)}" data-cancelable="${cancelable ? '1' : '0'}">
      <td><input class="order-select" type="checkbox" data-order-id="${plain(orderId)}"${cancelable ? '' : ' disabled'}></td>
      <td class="num">${index + 1}</td>
      ${includeTime ? `<td>${plain(orderTime(row))}</td>` : ''}
      <td>${plain(code)}</td>
      <td>${plain(orderName(row))}</td>
      <td class="num">${plain(orderVolume(row))}</td>
      <td class="num">${plain(tradedVolume(row))}</td>
      <td>${plain(orderStatus(row))}</td>
      <td>${plain(orderId)}</td>
    </tr>`;
  }).join('');
}

function renderTrades(section) {
  const rows = (section && Array.isArray(section.data)) ? section.data : [];
  const html = rows.slice().reverse().map((row) => `<tr>
    <td>${plain(tradeTime(row))}</td>
    <td>${plain(row.stock_code || `${row.m_strInstrumentID || ''}.${row.m_strExchangeID || ''}`)}</td>
    <td>${plain(row.instrument_name || row.m_strInstrumentName)}</td>
    <td class="num">${money(row.price ?? row.m_dPrice)}</td>
    <td class="num">${plain(row.volume ?? row.m_nVolume)}</td>
    <td class="num">${money(row.trade_amount ?? row.m_dTradeAmount)}</td>
  </tr>`).join('');
  const body = $('tradeTradesBody');
  if (body) {
    body.innerHTML = html || '<tr><td colspan="6">无成交数据</td></tr>';
  }
}

async function refreshAccount(sections = 'asset,positions', options = {}) {
  const accountId = selectedAccount();
  const channel = selectedChannel();
  if (!accountId) {
    log('账号为空');
    return;
  }
  const force = options.force ? '&force=1' : '';
  const data = await api(`/api/account?bridge_id=${encodeURIComponent(selectedBridge())}&account_id=${encodeURIComponent(accountId)}&channel=${channel}&sections=${sections}${force}`);
  if (data.asset) {
    if (data.asset.ok) renderAsset(data.asset);
    else log('资产查询失败', data.asset);
  }
  if (data.positions) {
    if (data.positions.ok) renderPositions(data.positions);
    else log('持仓查询失败', data.positions);
  }
  if (data.orders) {
    if (data.orders.ok) renderOrders(data.orders);
    else log('委托查询失败', data.orders);
  }
  if (data.trades) {
    if (data.trades.ok) renderTrades(data.trades);
    else log('成交查询失败', data.trades);
  }
  $('lastRefresh').textContent = data.cache && data.cache.checked_at_text ? data.cache.checked_at_text : nowText();
}

function normalizeStockCode(value) {
  const raw = String(value || '').trim().toUpperCase();
  if (!raw) return '';
  const parts = raw.split('.');
  let code = parts[0] || '';
  let market = parts[1] || '';
  if (!/^\d+$/.test(code)) return raw;
  const number = Number(code);
  if (!Number.isInteger(number) || number < 0 || number > 999999) return raw;
  code = String(number).padStart(6, '0');
  if (!market) market = code.startsWith('6') ? 'SH' : 'SZ';
  if (market !== 'SH' && market !== 'SZ') return raw;
  return `${code}.${market}`;
}

function buildOrderConfirmation(form) {
  const side = form.side.value.toUpperCase();
  const code = normalizeStockCode(form.stock_code.value);
  const volume = Number(form.volume.value || 0);
  const price = Number(form.price.value || 0);
  if (!code || !volume || !price) return '';
  return `${side} ${code} ${volume} @ ${price.toFixed(3)}`;
}

function buildCancelConfirmation(form) {
  const orderId = form.order_id.value.trim();
  return orderId ? `CANCEL ${orderId}` : '';
}

async function submitOrder(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = {
    bridge_id: selectedBridge(),
    channel: selectedTradeChannel(),
    account_id: selectedAccount(),
    side: form.side.value,
    stock_code: normalizeStockCode(form.stock_code.value),
    price: Number(form.price.value),
    volume: Number(form.volume.value),
    confirm_text: form.confirm_text.value.trim(),
  };
  try {
    const data = await api('/api/order', { method: 'POST', body: JSON.stringify(body) });
    log('委托已提交', data);
    addCallbackEvent('提交委托', {
      code: body.stock_code,
      order_id: data.result && (data.result.order_id || data.result.m_strOrderSysID),
      volume: body.volume,
      traded: 0,
      status: 'submitted',
    });
    await refreshAccount('asset,positions', { force: true });
    await refreshAccount('orders', { force: true });
  } catch (error) {
    log('委托失败', { error: error.message });
  }
}

function parseBatchOrders(text) {
  return String(text || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line, index) => {
    const parts = line.split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
    if (parts.length < 3) {
      throw new Error(`第 ${index + 1} 行格式应为：代码,价格,数量`);
    }
    return {
      side: 'buy',
      stock_code: normalizeStockCode(parts[0]),
      price: Number(parts[1]),
      volume: Number(parts[2]),
    };
  });
}

function updateBatchOrderHint() {
  const form = $('batchOrderForm');
  try {
    const orders = parseBatchOrders(form.orders_text.value);
    const expected = orders.length ? `BATCH ${orders.length}` : '';
    $('batchOrderHint').textContent = expected;
    if (!form.confirm_text.value || /^BATCH\s+\d+$/.test(form.confirm_text.value.trim())) {
      form.confirm_text.value = expected;
    }
  } catch (error) {
    $('batchOrderHint').textContent = error.message;
  }
}

async function submitBatchOrders(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const orders = parseBatchOrders(form.orders_text.value);
    if (!orders.length) {
      log('批量委托为空');
      return;
    }
    const body = {
      account_id: selectedAccount(),
      orders,
      confirm_text: form.confirm_text.value.trim(),
    };
    const data = await api('/api/orders/batch', { method: 'POST', body: JSON.stringify(body) });
    log('批量委托已提交', data);
    await refreshAccount('asset,positions', { force: true });
    await refreshAccount('orders', { force: true });
  } catch (error) {
    log('批量委托失败', { error: error.message });
  }
}

async function sendCancel(orderId, channel) {
  const body = {
    bridge_id: selectedBridge(),
    channel: channel || selectedTradeChannel(),
    account_id: selectedAccount(),
    order_id: String(orderId || '').trim(),
    confirm_text: `CANCEL ${String(orderId || '').trim()}`,
  };
  const data = await api('/api/cancel', { method: 'POST', body: JSON.stringify(body) });
  log('撤单已提交', data);
  addCallbackEvent('提交撤单', {
    code: '',
    order_id: body.order_id,
    volume: '',
    traded: '',
    status: 'cancel_requested',
  });
  await refreshAccount('orders', { force: true });
}

async function cancelOrder(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await sendCancel(form.order_id.value.trim(), form.channel.value);
  } catch (error) {
    log('撤单失败', { error: error.message });
  }
}

async function cancelOrderFromRow(row) {
  const orderId = row.dataset.orderId;
  if (!orderId || orderId === '--') return;
  if (row.dataset.cancelable !== '1') return;
  const channel = selectedTradeChannel();
  const confirmed = window.confirm(`确认撤单 ${orderId}？`);
  if (!confirmed) return;
  try {
    await sendCancel(orderId, channel);
  } catch (error) {
    log('双击撤单失败', { order_id: orderId, error: error.message });
  }
}

async function cancelSelectedOrders() {
  const checked = Array.from(document.querySelectorAll('.order-select:not(:disabled):checked'));
  const ids = [...new Set(checked.map((item) => item.dataset.orderId).filter(Boolean))];
  if (!ids.length) {
    log('未选择可撤委托');
    return;
  }
  const confirmed = window.confirm(`确认撤销 ${ids.length} 笔委托？`);
  if (!confirmed) return;
  const channel = selectedTradeChannel();
  for (const orderId of ids) {
    try {
      await sendCancel(orderId, channel);
    } catch (error) {
      log('批量撤单失败', { order_id: orderId, error: error.message });
    }
  }
  await refreshAccount('orders', { force: true });
}

function wireForms() {
  const orderForm = $('orderForm');
  orderForm.addEventListener('input', () => {
    const expected = buildOrderConfirmation(orderForm);
    $('orderHint').textContent = expected;
    if (!orderForm.confirm_text.value || orderForm.confirm_text.value === state.lastOrderConfirm) {
      orderForm.confirm_text.value = expected;
    }
    state.lastOrderConfirm = expected;
  });
  orderForm.addEventListener('submit', submitOrder);
  const batchOrderForm = $('batchOrderForm');
  batchOrderForm.addEventListener('input', updateBatchOrderHint);
  batchOrderForm.addEventListener('submit', submitBatchOrders);
  document.querySelectorAll('.trade-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      orderForm.side.value = tab.dataset.side;
      document.querySelectorAll('.trade-tab').forEach((item) => {
        item.classList.toggle('active', item === tab);
      });
      orderForm.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });
  $('ordersBody').addEventListener('dblclick', (event) => {
    const row = event.target.closest('tr[data-order-id]');
    if (row) cancelOrderFromRow(row);
  });
  $('selectAllOrders').addEventListener('change', (event) => {
    document.querySelectorAll('.order-select:not(:disabled)').forEach((item) => {
      item.checked = event.target.checked;
    });
  });
  $('selectAllTradeOrders').addEventListener('change', (event) => {
    document.querySelectorAll('.order-select:not(:disabled)').forEach((item) => {
      item.checked = event.target.checked;
    });
  });
  $('cancelSelectedBtn').addEventListener('click', cancelSelectedOrders);
}

function wireNavigation() {
  document.querySelectorAll('.nav-item').forEach((node) => {
    node.addEventListener('click', () => setView(node.dataset.view));
  });
  window.addEventListener('pagehide', () => stopQuoteLive({ beacon: true }));
  window.addEventListener('beforeunload', () => stopQuoteLive({ beacon: true }));
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopQuoteLive({ beacon: true });
  });
}

function wireDataTabs() {
  document.querySelectorAll('.data-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      setDataTab(tab.dataset.tab);
    });
  });
}

function setTutorialTopic(name) {
  if (!document.querySelector(`.tutorial-menu-item[data-guide="${name}"]`)) {
    name = 'project';
  }
  localStorage.setItem(TUTORIAL_TOPIC_KEY, name);
  document.querySelectorAll('.tutorial-menu-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.guide === name);
  });
  document.querySelectorAll('.tutorial-topic').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.guidePanel === name);
  });
}

function wireTutorialNavigation() {
  document.querySelectorAll('.tutorial-menu-item').forEach((item) => {
    item.addEventListener('click', () => setTutorialTopic(item.dataset.guide));
  });
  setTutorialTopic(localStorage.getItem(TUTORIAL_TOPIC_KEY) || 'project');
}

function closeImageLightbox() {
  const box = $('imageLightbox');
  const img = $('imageLightboxImg');
  const caption = $('imageLightboxCaption');
  if (!box || !img || !caption) return;
  box.classList.remove('open');
  box.setAttribute('aria-hidden', 'true');
  img.removeAttribute('src');
  img.alt = '';
  caption.textContent = '';
}

function openImageLightbox(imgNode) {
  const box = $('imageLightbox');
  const img = $('imageLightboxImg');
  const caption = $('imageLightboxCaption');
  if (!box || !img || !caption || !imgNode) return;
  img.src = imgNode.currentSrc || imgNode.src;
  img.alt = imgNode.alt || '图片预览';
  const figureCaption = imgNode.closest('figure') && imgNode.closest('figure').querySelector('figcaption');
  caption.textContent = figureCaption ? figureCaption.textContent.trim() : img.alt;
  box.classList.add('open');
  box.setAttribute('aria-hidden', 'false');
}

function wireImageLightbox() {
  document.addEventListener('click', (event) => {
    const img = event.target.closest('.guide-image-card img');
    if (img) {
      openImageLightbox(img);
      return;
    }
    const box = $('imageLightbox');
    if (box && event.target === box) closeImageLightbox();
  });
  const closeBtn = $('imageLightboxClose');
  if (closeBtn) closeBtn.addEventListener('click', closeImageLightbox);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeImageLightbox();
  });
}

function startTimers() {
  setInterval(() => {
    $('clock').textContent = nowText();
  }, 1000);
  state.statusTimer = setInterval(() => {
    refreshStatus().catch((error) => log('状态定时刷新失败', { error: error.message }));
    refreshBindingStatuses().catch((error) => log('绑定状态定时刷新失败', { error: error.message }));
  }, 15000);
  setInterval(refreshCallbacks, 1500);
  state.refreshTimer = setInterval(() => {
    if ($('autoRefresh').checked) {
      refreshAccount('orders').catch((error) => log('实时委托刷新失败', { error: error.message }));
    }
  }, 4000);
}

async function boot() {
  wireForms();
  wireNavigation();
  wireDataTabs();
  wireTutorialNavigation();
  wireImageLightbox();
  renderCallbacks();
  setDataTab(localStorage.getItem('cfquant.trade_tab') || 'positions', false);
  setView(localStorage.getItem('cfquant.view') || 'overview');
  $('refreshBtn').addEventListener('click', async () => {
    try {
      await refreshAccount('asset,positions', { force: true });
      await refreshAccount('orders', { force: true });
      await refreshAccount('trades', { force: true });
    } catch (error) {
      log('刷新失败', { error: error.message });
    }
  });
  $('statusBtn').addEventListener('click', refreshStatus);
  $('lttxStartBtn').addEventListener('click', startLttx);
  $('lttxStopBtn').addEventListener('click', stopLttx);
  $('openAccessSettingsBtn').addEventListener('click', () => setView('settings'));
  $('savePairBtn').addEventListener('click', () => saveCurrentAccountPair().catch((error) => log('账号配对保存失败', { error: error.message })));
  $('removePairBtn').addEventListener('click', () => removeCurrentAccountPair().catch((error) => log('账号配对移除失败', { error: error.message })));
  $('accountPairList').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-account-id]');
    if (!button) return;
    selectAccountPair(button.dataset.accountId, button.dataset.bridgeId);
  });
  $('bridgeForm').addEventListener('submit', submitBridgeForm);
  $('bindingForm').addEventListener('submit', submitBindingForm);
  $('bridgeConfigList').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-bridge-id]');
    if (!button) return;
    if (button.dataset.action === 'edit') fillBridgeForm(button.dataset.bridgeId);
    if (button.dataset.action === 'delete') deleteBridge(button.dataset.bridgeId);
  });
  $('refreshBindingsBtn').addEventListener('click', () => refreshBindingStatuses().catch((error) => log('绑定状态刷新失败', { error: error.message })));
  $('bindingStatusBody').addEventListener('click', (event) => {
    const button = event.target.closest('.verify-pair-btn');
    if (!button) return;
    verifyPair(button.dataset.accountId, button.dataset.bridgeId);
  });
  $('apiEndpointList').addEventListener('click', (event) => {
    const groupButton = event.target.closest('button[data-api-group]');
    if (groupButton) {
      const groupId = groupButton.dataset.apiGroup;
      if (state.apiOpenGroups.has(groupId)) state.apiOpenGroups.delete(groupId);
      else state.apiOpenGroups.add(groupId);
      saveApiOpenGroups();
      renderApiDocs(state.apiEndpointId);
      return;
    }
    const button = event.target.closest('button[data-endpoint-id]');
    if (!button) return;
    if (button.dataset.endpointId !== state.apiEndpointId) {
      stopQuoteLive();
    }
    renderApiDocs(button.dataset.endpointId, { ensureGroupOpen: true });
  });
  $('apiForm').addEventListener('input', updateApiRequestPreview);
  $('apiForm').addEventListener('change', updateApiRequestPreview);
  $('apiForm').addEventListener('submit', sendApiDebugRequest);
  $('apiForm').addEventListener('click', (event) => {
    if (event.target.id === 'apiResetBtn') {
      renderApiDocs(state.apiEndpointId);
    }
  });
  $('openSettingsBtn').addEventListener('click', () => setView('settings'));
  $('generateApiKeyBtn').addEventListener('click', () => saveApiKey({ generate: true }).catch((error) => log('API Key 生成失败', { error: error.message })));
  $('saveApiKeyBtn').addEventListener('click', () => saveApiKey().catch((error) => log('API Key 保存失败', { error: error.message })));
  $('toggleApiKeyBtn').addEventListener('click', toggleApiKeyVisible);
  $('copyApiKeyBtn').addEventListener('click', () => copyApiKey().catch((error) => log('API Key 复制失败', { error: error.message })));
  $('apiKeyForm').addEventListener('submit', (event) => {
    event.preventDefault();
    saveApiKey().catch((error) => log('API Key 保存失败', { error: error.message }));
  });
  $('apiServerForm').addEventListener('submit', (event) => {
    event.preventDefault();
    saveServerAccessFromUi('api').catch((error) => log('访问设置保存失败', { error: error.message }));
  });
  $('useCurrentOriginBtn').addEventListener('click', () => {
    $('apiBaseUrlInput').value = window.location.origin;
    updateApiRequestPreview();
  });
  $('useLanOriginBtn').addEventListener('click', () => {
    const target = state.serverAccess && state.serverAccess.lan_url ? state.serverAccess.lan_url : window.location.origin;
    const normalized = normalizeApiBaseUrl(target);
    $('apiBaseUrlInput').value = normalized;
    updateApiRequestPreview();
  });
  $('apiBaseUrlInput').addEventListener('input', updateApiRequestPreview);
  $('allowApiRemoteAccess').addEventListener('change', () => {
    const overviewToggle = $('allowRemoteAccess');
    if (overviewToggle) overviewToggle.checked = $('allowApiRemoteAccess').checked;
  });
  const overviewRemoteToggle = $('allowRemoteAccess');
  if (overviewRemoteToggle) {
    overviewRemoteToggle.addEventListener('change', () => {
      const apiToggle = $('allowApiRemoteAccess');
      if (apiToggle) apiToggle.checked = overviewRemoteToggle.checked;
    });
  }
  $('ordersBtn').addEventListener('click', () => refreshAccount('orders', { force: true }).catch((error) => log('委托刷新失败', { error: error.message })));
  $('clearLogBtn').addEventListener('click', () => { $('logBox').innerHTML = ''; });
  $('bridgeSelect').addEventListener('change', handleBridgeChange);
  $('accountInput').addEventListener('change', handleAccountChange);
  $('queryChannel').addEventListener('change', selectedChannel);
  $('tradeChannel').addEventListener('change', selectedTradeChannel);
  await loadConfig();
  loadApiOpenGroups();
  renderApiDocs();
  await refreshStatus();
  await refreshAccount('asset,positions').catch((error) => log('初始化查询失败', { error: error.message }));
  refreshAccount('orders').catch((error) => log('委托初始化失败', { error: error.message }));
  refreshAccount('trades').catch((error) => log('成交初始化失败', { error: error.message }));
  startTimers();
}

boot().catch((error) => log('启动失败', { error: error.message }));
