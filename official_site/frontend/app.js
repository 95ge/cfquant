const SITE_TOKEN_KEY = 'cfquant_site_token';
const SITE_USER_KEY = 'cfquant_site_user';

function readStoredUser() {
  try {
    const user = JSON.parse(localStorage.getItem(SITE_USER_KEY) || 'null');
    return user && typeof user === 'object' ? user : null;
  } catch (_error) {
    localStorage.removeItem(SITE_USER_KEY);
    return null;
  }
}

const state = {
  token: localStorage.getItem(SITE_TOKEN_KEY) || '',
  user: readStoredUser(),
  categories: [],
  activeCategory: '',
  selectedThreadId: null,
  currentThread: null,
  currentReplies: [],
  expandedReplyIds: new Set(),
  replyComposeParentId: null,
  replyFiles: {},
  replyPreviewUrls: {},
  imageModalObjectUrl: '',
  authMode: 'register',
  feedbackFiles: [],
  feedbackPreviewUrls: [],
  feedbackInlineImageUrls: {},
  feedbackPanel: 'public',
  featurePanel: 'public',
  projectSlide: 0,
  projectTimer: null,
  projectPaused: false,
  architectureInitialized: false,
  archRoute: 'overview',
  archStep: 0,
  archTimer: null,
  flowMode: 'request',
  flowStep: 0,
  flowTimer: null,
  flowResizeTimer: 0,
  builtinAvatars: [],
  avatarUploadLimit: 2 * 1024 * 1024,
};

const $ = (id) => document.getElementById(id);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const CONFIG = window.CFQUANT_SITE_CONFIG || {};
const API_BASE = String(CONFIG.apiBase || '').replace(/\/$/, '');
const LOGIN_MEMORY_KEY = 'cfquant_site_login_memory';
const MAX_REPLY_IMAGES = 10;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DEFAULT_AVATAR_URL = '/avatars/market-blue.svg';
const DEFAULT_BUILTIN_AVATARS = [
  { id: 'market-blue', name: 'Market Blue', url: '/avatars/market-blue.svg' },
  { id: 'signal-green', name: 'Signal Green', url: '/avatars/signal-green.svg' },
  { id: 'copper-grid', name: 'Copper Grid', url: '/avatars/copper-grid.svg' },
  { id: 'violet-node', name: 'Violet Node', url: '/avatars/violet-node.svg' },
  { id: 'slate-wave', name: 'Slate Wave', url: '/avatars/slate-wave.svg' },
  { id: 'amber-pulse', name: 'Amber Pulse', url: '/avatars/amber-pulse.svg' },
  { id: 'teal-orbit', name: 'Teal Orbit', url: '/avatars/teal-orbit.svg' },
  { id: 'rose-circuit', name: 'Rose Circuit', url: '/avatars/rose-circuit.svg' },
];
const REDUCE_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const MAIN_VIEWS = ['forum', 'downloads', 'project', 'architecture', 'features', 'feedback', 'center', 'docs'];
const FEATURE_STATUS_LABELS = {
  open: '待评估',
  reviewing: '评估中',
  planned: '已排期',
  done: '已完成',
  declined: '暂不采纳',
};
const FEATURE_MODULE_LABELS = {
  bridge: '桥接运行',
  quote: '行情数据',
  trade: '交易接口',
  web: '官网 / 控制台',
  docs: '文档示例',
  other: '其它',
};
const FEATURE_PRIORITY_LABELS = {
  low: '低',
  normal: '常规',
  high: '高',
};
const MODE_COPY = {
  normal: {
    qmt: '加载 <code>CFQUANT_CTYPE_ALL_LOWLAT.py</code>',
    python: '读取行情、查询持仓、提交交易请求。',
    script: 'Web / Python -> PipeHub -> ctypes 单文件桥 -> QMT',
    use: '适合快速部署、单账号验证和多数常规使用。',
  },
  lite: {
    qmt: '加载 <code>CFQUANT_LITE.py</code>',
    python: '外部调用保持轻量，QMT 侧入口自包含。',
    script: 'QMT 侧入口自包含，不依赖导入 cfquant 核心包',
    use: '适合白名单限制严格的 QMT 环境。',
  },
  advanced: {
    qmt: '普通 QMT + 极速交易端 QMT',
    python: '查询与交易请求分工，降低职责混用。',
    script: 'CFQUANT.py + CFQUANT_TRADE_LOWLAT.py',
    use: '适合追求更低下单、撤单延迟的场景。',
  },
};
const ARCH_NODES = {
  user: { label: '外部 Python', layer: '外部调用', path: '策略、测试脚本、业务程序', body: '发起 order_stock、query、xtdata 等请求，也负责接收响应和订阅后的事件。' },
  xttrader: { label: 'xttrader.py', layer: 'API 层', path: 'cfquant/xttrader.py', body: '模拟 xtquant.xttrader，负责账号订阅、下单、撤单、交易查询和交易回调派发。' },
  xtdata: { label: 'xtdata.py', layer: 'API 层', path: 'cfquant/xtdata.py', body: '提供行情查询、行情订阅、数据下载和条件兼容接口。' },
  xttype: { label: '类型常量', layer: 'API 层', path: 'cfquant/xttype.py / cfquant/xtconstant.py', body: '提供 StockAccount、资产、委托、成交、持仓对象和交易常量，保证旧接口兼容。' },
  config: { label: 'config', layer: '客户端协议', path: 'cfquant/config.py / cfquant/channels.py', body: '维护 host、port、token、transport、pipe name 和 bridge_id，并生成 normal、trade、callback 频道名。' },
  rpc: { label: 'client.py', layer: '客户端协议', path: 'cfquant/client.py', body: '根据 transport=auto、ctypes、lttx 或 web_lttx 创建 PipeRpcClient、LTtxRpcClient 或 WebLttxRpcClient。' },
  protocol: { label: 'protocol', layer: '客户端协议', path: 'cfquant/protocol.py', body: '统一封装 request、response 和 event，并处理对象、DataFrame、Series 的序列化。' },
  web: { label: 'Web 路由', layer: '本地服务', path: 'cfquant_web_server.py', body: '承载 Web 控制台、账号配置、统一路由、运行时注册、PipeHub 与 LTtx 启停，以及 callback 监听。' },
  pipehub: { label: 'PipeHub', layer: '本地服务', path: 'cfquant_pipe_hub.py / cfquant/pipe_hub.py', body: '作为外部 Python、Web 和 QMT Pipe 桥之间的 named pipe 消息代理，负责请求转发、响应配对和事件投递。' },
  lttx: { label: 'LTtx', layer: '本地服务', path: 'LTtx/tx/LTtx_server.py', body: '提供本机 socket 发布订阅，用于 Web route、运行时发现和高级模式直连。' },
  runtime: { label: 'runtime', layer: '本地服务', path: 'runtime/config/cfquant_web_config.json', body: '保存账号、账号类型、bridge、运行模式、市场路由和 Web 端口，是 Web 统一路由的决策来源。' },
  'ctype-entry': { label: '通用入口', layer: 'QMT 入口', path: 'qmt_scripts/CFQUANT_CTYPE_ALL_LOWLAT.py', body: '在单个 QMT 策略内启动 normal 和 trade 两个 Pipe 通道，覆盖通用模式主要请求。' },
  'lite-entry': { label: '极致入口', layer: 'QMT 入口', path: 'qmt_scripts/CFQUANT_LITE.py', body: '自包含 QMT 入口，适配无法正常导入 cfquant 项目包的本地终端环境。' },
  'normal-entry': { label: '普通桥入口', layer: 'QMT 入口', path: 'qmt_scripts/CFQUANT.py', body: '高级模式普通入口，负责普通查询、行情订阅和账号级交易回调。' },
  'trade-entry': { label: '交易桥入口', layer: 'QMT 入口', path: 'qmt_scripts/CFQUANT_TRADE_LOWLAT.py', body: '高级模式低延迟交易入口，只处理下单、撤单和交易查询，不承接 QMT 原始账号回调。' },
  'market-entry': { label: '市场拆分', layer: 'QMT 入口', path: 'qmt_scripts/同账号独立市场/*.py', body: '包装根入口并设置沪深市场配置，让 Web 可把同一账号不同市场拆到不同 bridge。' },
  'pipe-bridge': { label: 'Pipe 桥', layer: 'QMT 桥', path: 'cfquant/pipe_bridge.py', body: '把 NormalQmtBridge 和 TxTradeBridge 包装成通过 PipeHub 通信的 QMT 侧桥。' },
  'normal-bridge': { label: '普通桥', layer: 'QMT 桥', path: 'cfquant/normal_bridge.py', body: '处理普通请求队列、行情订阅转发、callback event 通道和 QMT 原始交易回调发布。' },
  'trade-bridge': { label: '交易桥', layer: 'QMT 桥', path: 'cfquant/tx_trade_bridge.py', body: '分发 passorder、cancel、交易查询、行情兼容查询、账号订阅和请求级事件。' },
  'qmt-native': { label: 'QMT 原生', layer: '原生能力', path: 'ContextInfo / passorder / cancel / get_trade_detail_data', body: '最终调用大 QMT 原生能力，并把同步调用结果按原路径返回。' },
  'callback-event': { label: '回调事件', layer: '原生能力', path: 'trader:on_* / quote:<subscribe_id>', body: '账号级交易回调按 bridge_id、account_type、account_id 广播；请求级响应只回到发起 client_id。' },
};
const ARCH_ROUTES = {
  overview: { type: '总体架构', summaryTitle: '七层调用结构', title: '总体架构', lead: '从外部 Python 到 QMT 原生能力，中间只保留用户需要理解的决策节点。', summary: '外部 Python 通过 cfquant API 进入客户端选择层，再由 Web、PipeHub 或 LTtx 投递到 QMT 内部桥。', decision: '核心判断：transport 与 Web route 是否在线。', steps: ['user', 'xttrader', 'rpc', 'web', 'runtime', 'pipehub', 'pipe-bridge', 'qmt-native'] },
  auto: { type: '默认推荐', summaryTitle: 'auto 走 Web 统一路由', title: '默认 auto 链路', lead: 'Web 在线并写入 cfquant.runtime 时，外部调用先进入 LTtx，再交给 Web 统一选择账号、模式和桥。', summary: '这条链路最适合普通用户和多账号部署，Web 负责账号路由、模式选择、fallback 和回调转发。', decision: '判断顺序：发现 Web route -> 读取账号配置 -> 选择 PipeHub 或 LTtx QMT 桥。', steps: ['user', 'xttrader', 'rpc', 'lttx', 'web', 'runtime', 'pipehub', 'pipe-bridge', 'trade-bridge', 'qmt-native'] },
  ctypes: { type: '短链路', summaryTitle: 'ctypes 直连 PipeHub', title: '强制 ctypes 链路', lead: '调用方设置 configure(transport="ctypes") 后绕过 Web 和 LTtx，直接进入 PipeHub。', summary: '链路更短，但调用方需要自己维护账号、bridge、模式和市场路由关系。', decision: '适用前提：单账号或固定 bridge 已清楚，且不依赖 Web 统一路由。', steps: ['user', 'xttrader', 'rpc', 'pipehub', 'pipe-bridge', 'ctype-entry', 'trade-bridge', 'qmt-native'] },
  lttx: { type: '高级直连', summaryTitle: 'lttx 直连高级桥', title: '强制 lttx 链路', lead: '调用方设置 configure(transport="lttx") 后直接连接 LTtx 请求频道，绕过 Web 账号路由。', summary: '适合固定高级模式和明确频道的场景，不具备 Web 的账号自动路由与 fallback。', decision: '适用前提：普通桥和交易桥入口已经在 QMT 内按预期运行。', steps: ['user', 'xttrader', 'rpc', 'lttx', 'normal-entry', 'trade-entry', 'normal-bridge', 'trade-bridge', 'qmt-native'] },
  callback: { type: '事件回流', summaryTitle: '回调从 QMT 回到订阅者', title: '回调广播链路', lead: '账号级回调按账号订阅广播，请求级响应只回到发起请求的 client_id。', summary: 'QMT 原始回调先进入入口脚本与普通桥，再经 PipeHub、Web、LTtx 或直连 Pipe 送回外部客户端。', decision: '关键规则：CFQUANT_TRADE_LOWLAT.py 是纯交易请求桥，不承接 QMT 原始账号回调。', steps: ['qmt-native', 'callback-event', 'normal-entry', 'normal-bridge', 'pipehub', 'web', 'lttx', 'rpc', 'user'] },
  modes: { type: '模式对比', summaryTitle: '三种模式不是同一条线', title: '模式架构对比', lead: '通用模式经 PipeHub，极致模式自包含，高级模式把普通桥与低延迟交易桥拆开。', summary: '这张视图把三种部署模式放在一张图中，帮助用户先选择环境，再看对应入口脚本。', decision: '选择逻辑：环境限制优先，其次是账号路由需求，最后才是链路长度。', steps: ['web', 'pipehub', 'ctype-entry', 'lite-entry', 'lttx', 'normal-entry', 'trade-entry', 'market-entry'] },
  runtime: { type: '排障数据', summaryTitle: '运行时配置决定路由', title: '关键运行时数据', lead: '账号配置、pipe 名称、LTtx 地址和频道名决定请求能否到达正确桥。', summary: '排障时先确认运行时配置和频道名是否一致，再判断 Web、PipeHub、LTtx 或 QMT 桥是否断链。', decision: '重点字段：cfquant.runtime、cfquant.web.request、normal、trade、callback 频道。', steps: ['runtime', 'config', 'web', 'lttx', 'pipehub', 'protocol', 'rpc'] },
};
const LIFE_COPY = {
  imported: { status: '未连接', title: '导入 cfquant', body: '仅导入包不会连接 LTtx，也不会创建 PipeHub 连接。真正连接发生在 start、connect、subscribe 或首次请求。' },
  object: { status: '准备中', title: '创建账号或交易对象', body: '创建 StockAccount 或 XtQuantTrader 只是准备调用参数，仍不会主动连接服务。' },
  connect: { status: '首次请求', title: '触发连接', body: 'start、connect、subscribe、request 或 xtdata 首次请求会触发客户端选择和连接创建。' },
  route: { status: '路由选择', title: '选择 Web、Pipe 或 LTtx', body: 'auto 会优先发现 Web route；ctypes 或 lite 连接 PipeHub；lttx 连接 LTtx 请求频道。' },
  running: { status: '持续运行', title: '保持接收线程', body: 'WebLttx、Direct LTtx 和 Pipe 都会保持连接与接收线程，用于响应和事件回流。' },
  closed: { status: '已关闭', title: '主动或进程退出关闭', body: 'stop、disconnect、close、configure 重置或进程退出会结束连接，后续请求会重新进入选择流程。' },
};
const FLOW_NODE_LABELS = {
  caller: '外部 Python',
  api: 'API 兼容层',
  client: 'RPC 客户端',
  route: 'Web / LTtx',
  hub: 'PipeHub',
  entry: 'QMT 入口',
  bridge: 'QMT 桥',
  native: 'QMT 原生',
};
const FLOW_EDGES = [
  ['caller', 'api', 'caller-api'],
  ['api', 'client', 'api-client'],
  ['client', 'route', 'client-route'],
  ['route', 'hub', 'route-hub'],
  ['hub', 'entry', 'hub-entry'],
  ['entry', 'bridge', 'entry-bridge'],
  ['bridge', 'native', 'bridge-native'],
];
const FLOW_LINK_MAP = {
  'caller>api': 'caller-api', 'api>caller': 'caller-api',
  'api>client': 'api-client', 'client>api': 'api-client',
  'client>route': 'client-route', 'route>client': 'client-route',
  'route>hub': 'route-hub', 'hub>route': 'route-hub',
  'hub>entry': 'hub-entry', 'entry>hub': 'hub-entry',
  'entry>bridge': 'entry-bridge', 'bridge>entry': 'entry-bridge',
  'bridge>native': 'bridge-native', 'native>bridge': 'bridge-native',
};
const FLOW_MODES = {
  request: { status: '实时演示', title: '默认请求流', lead: '外部 Python 发起请求后，经 API、客户端选择和 Web 路由进入 QMT 桥，再把响应原路返回。', payloadType: 'request', payloadTitle: 'order_stock 请求', payloadCopy: '请求从外部 Python 进入 API 层，最终由 QMT 原生交易函数处理，响应只回给发起请求的 client_id。', channel: 'cfquant.web.request', payload: 'request.order_stock', rule: '按 client_id 返回', steps: ['caller', 'api', 'client', 'route', 'hub', 'entry', 'bridge', 'native'], events: ['策略进程发起 order_stock', 'xttrader 组装兼容请求', 'client.py 选择 WebLttx', 'Web route 读取 runtime 配置', 'PipeHub 投递 named pipe', '入口脚本进入当前模式', '交易桥调用 passorder', 'QMT 原生返回同步结果'] },
  market: { status: '订阅演示', title: '行情订阅流', lead: '行情订阅先按请求链路进入 QMT 原生行情函数，订阅后 quote 事件沿客户端接收线程持续回到外部程序。', payloadType: 'quote', payloadTitle: '行情 quote 事件', payloadCopy: '行情数据由 xtdata 发起订阅，后续事件以 quote:<subscribe_id> 形式回流，适合解释 on_tick 和消费队列。', channel: 'cfquant.normal.request', payload: 'quote:<subscribe_id>', rule: '订阅后持续投递', steps: ['caller', 'api', 'client', 'route', 'hub', 'entry', 'bridge', 'native'], events: ['xtdata 发起订阅请求', '协议层写入 subscribe_id', 'auto 选择当前传输', 'Web route 选择账号桥', 'PipeHub 投递 normal 通道', '入口脚本注册行情处理', '普通桥绑定行情订阅', 'QMT 行情函数开始推送'] },
  'trade-callback': { status: '回流演示', title: '交易回调流', lead: 'QMT 原始交易回调不会从交易低延迟入口直接承接，而是由普通桥发布并按账号订阅关系广播。', payloadType: 'event', payloadTitle: 'trader:on_stock_trade', payloadCopy: '账号级交易回调按 bridge_id、account_type、account_id 匹配订阅者；请求级响应仍只回给发起请求的 client_id。', channel: 'cfquant.callback.event', payload: 'trader:on_stock_trade', rule: '按账号订阅广播', steps: ['native', 'bridge', 'entry', 'hub', 'route', 'client', 'api', 'caller'], events: ['QMT 触发原始交易回调', '普通桥发布 trader:on_*', '入口脚本携带账号信息', 'PipeHub 接收 callback event', 'Web 匹配外部订阅者', 'LTtx 推送到 client_id', 'xttrader 派发回调方法', '外部 Callback 收到事件'] },
  download: { status: '进度演示', title: '数据下载进度流', lead: '数据下载请求属于普通请求，但进度 callback 要被持续派发，页面用队列方式展示请求和进度之间的关系。', payloadType: 'progress', payloadTitle: 'download_history_data', payloadCopy: '下载请求进入 normal 通道，进度事件随 callback 返回发起方，适合解释为什么下载不是一次性响应。', channel: 'cfquant.normal.request', payload: 'download.progress', rule: '进度事件回发起方', steps: ['caller', 'api', 'client', 'route', 'hub', 'entry', 'bridge', 'native'], events: ['外部调用下载历史数据', 'xtdata 写入下载参数', 'client.py 创建 request', 'Web route 选择 normal 桥', 'PipeHub 维持请求配对', '入口脚本投递下载任务', '普通桥转发进度事件', 'QMT 数据函数持续返回进度'] },
  heartbeat: { status: '发现演示', title: '运行心跳与发现流', lead: 'Web 服务把运行时状态写入 LTtx，外部 auto 通过 cfquant.runtime 判断是否进入 Web 统一路由。', payloadType: 'runtime', payloadTitle: 'cfquant.runtime', payloadCopy: '这条流不代表一次交易请求，而是说明 auto 如何发现 Web route、端口、账号配置和可用桥。', channel: 'cfquant.runtime', payload: 'runtime.discovery', rule: '只用于发现和路由', steps: ['route', 'client', 'api', 'caller'], events: ['Web 服务发布 runtime 信息', 'LTtx 保存发现 key', 'client.py 读取 cfquant.runtime', '外部 auto 决定走 Web route'] },
};

function apiUrl(path) {
  if (!API_BASE) return path;
  return `${API_BASE}${path}`;
}

function assetUrl(path) {
  const value = String(path || '').trim();
  if (!value) return '';
  if (/^(https?:|data:|blob:)/i.test(value)) return value;
  if (value.startsWith('/api/')) return apiUrl(value);
  return value;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function safeColor(value, fallback = '#1f6feb') {
  const text = String(value || '').trim();
  return /^#[0-9A-Fa-f]{6}$/.test(text) ? text : fallback;
}

function safeAvatarUrl(value) {
  const text = String(value || '').trim();
  if (!text) return DEFAULT_AVATAR_URL;
  if (text.startsWith('/avatars/') || text.startsWith('/api/user-avatars/')) return text;
  return DEFAULT_AVATAR_URL;
}

function avatarInitial(user = {}) {
  const label = String(user.display_name || user.username || 'C').trim();
  return (label[0] || 'C').toUpperCase();
}

function avatarHtml(user = {}, className = '') {
  const url = safeAvatarUrl(user.avatar_url);
  const color = safeColor(user.avatar_color);
  const initial = avatarInitial(user);
  const classes = ['avatar-badge', className].filter(Boolean).join(' ');
  return `
    <span class="${classes}" style="--avatar-color:${escapeHtml(color)}">
      <img src="${escapeHtml(assetUrl(url))}" alt="" loading="lazy">
      <span>${escapeHtml(initial)}</span>
    </span>
  `;
}

function avatarOptionsFor(user = {}) {
  const avatars = state.builtinAvatars.length ? state.builtinAvatars : DEFAULT_BUILTIN_AVATARS;
  const current = safeAvatarUrl(user.avatar_url);
  const options = avatars.map((item) => ({ ...item, url: safeAvatarUrl(item.url) }));
  if (current.startsWith('/api/user-avatars/') && !options.some((item) => item.url === current)) {
    options.unshift({ id: 'current-upload', name: '当前上传头像', url: current });
  }
  return options;
}

function renderAvatarPicker(selectedUrl) {
  const selected = safeAvatarUrl(selectedUrl);
  return avatarOptionsFor(state.user).map((avatar) => {
    const url = safeAvatarUrl(avatar.url);
    const active = url === selected;
    return `
      <button class="avatar-option${active ? ' is-active' : ''}" type="button" data-profile-avatar="${escapeHtml(url)}" aria-pressed="${active ? 'true' : 'false'}" title="${escapeHtml(avatar.name || '内置头像')}">
        <img src="${escapeHtml(assetUrl(url))}" alt="">
      </button>
    `;
  }).join('');
}

function formatTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function excerpt(value, max = 150) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function formatSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return '-';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatCount(value) {
  return new Intl.NumberFormat('zh-CN').format(Number(value || 0));
}

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

function renderReleaseSummary(release, error = '') {
  if (!document.getElementById('releaseCoreSummary')) return;
  if (!release) {
    setText('releaseCoreSummary', '待登记');
    setText('releaseWebSummary', '待登记');
    setText('releaseUpdatedSummary', error ? '检查失败' : '待同步');
    setText('releaseDownloadsSummary', '0');
    return;
  }
  setText('releaseCoreSummary', release.core_version || release.version || '--');
  setText('releaseWebSummary', release.web_version || '--');
  setText('releaseUpdatedSummary', formatTime(release.updated_at));
  setText('releaseDownloadsSummary', formatCount(release.download_count));
}

async function loadReleaseSummary() {
  try {
    const data = await api('/api/releases/latest');
    renderReleaseSummary(data.release || null);
  } catch (error) {
    renderReleaseSummary(null, error.message);
  }
}

function isValidEmail(value) {
  return EMAIL_PATTERN.test(String(value || '').trim().toLowerCase());
}

function fileToAttachment(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve({
        name: file.name,
        type: file.type,
        size: file.size,
        data: String(reader.result || ''),
      });
    };
    reader.onerror = () => reject(new Error('截图读取失败'));
    reader.readAsDataURL(file);
  });
}

function normalizeImageFile(file, index = 0) {
  if (file.name) return file;
  const ext = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/webp': 'webp',
    'image/gif': 'gif',
  }[file.type] || 'png';
  return new File([file], `clipboard-${Date.now()}-${index + 1}.${ext}`, {
    type: file.type || 'image/png',
    lastModified: Date.now(),
  });
}

function validateImageFiles(files, label = '图片') {
  const allowed = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
  const selected = Array.from(files || []).filter(Boolean).map(normalizeImageFile);
  for (const file of selected) {
    if (!allowed.has(file.type)) {
      toast(`${label}只支持 png、jpg、webp、gif`);
      return [];
    }
    if (file.size > 3 * 1024 * 1024) {
      toast(`单张${label}不能超过 3MB`);
      return [];
    }
  }
  return selected;
}

function validateFeedbackFiles(files) {
  return validateImageFiles(files, '截图');
}

function validateAvatarFile(file) {
  const selected = Array.from(file ? [file] : []).filter(Boolean).map(normalizeImageFile);
  const avatar = selected[0];
  if (!avatar) return null;
  const allowed = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
  if (!allowed.has(avatar.type)) {
    toast('头像只支持 png、jpg、webp、gif');
    return null;
  }
  if (avatar.size > state.avatarUploadLimit) {
    toast(`头像不能超过 ${formatSize(state.avatarUploadLimit)}`);
    return null;
  }
  return avatar;
}

function setFeedbackFiles(files, options = {}) {
  const selected = validateFeedbackFiles(files);
  if (!selected.length) return;
  const append = options.append === true;
  const current = append ? state.feedbackFiles : [];
  const capacity = 4 - current.length;
  if (capacity <= 0) {
    toast('最多上传 4 张截图');
    return;
  }
  const kept = selected.slice(0, capacity);
  if (selected.length > capacity) {
    toast(`最多上传 4 张截图，已保留 ${capacity} 张`);
  }
  state.feedbackFiles = [...current, ...kept];
  renderFeedbackPreview();
}

function revokeFeedbackPreviewUrls() {
  state.feedbackPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  state.feedbackPreviewUrls = [];
}

function renderFeedbackPreview() {
  const target = $('feedbackPreview');
  if (!target) return;
  revokeFeedbackPreviewUrls();
  state.feedbackPreviewUrls = state.feedbackFiles.map((file) => URL.createObjectURL(file));
  target.innerHTML = state.feedbackFiles.map((file, index) => `
    <figure class="screenshot-item">
      <img src="${escapeHtml(state.feedbackPreviewUrls[index])}" alt="${escapeHtml(file.name)}">
      <figcaption>
        <span>${escapeHtml(file.name)}</span>
        <button class="icon-button" type="button" data-remove-screenshot="${index}" aria-label="移除截图">X</button>
      </figcaption>
    </figure>
  `).join('');
}

function syncFeedbackEmailRequirement() {
  const input = $('feedbackContact');
  if (!input) return;
  const hasAccountEmail = Boolean(state.user?.email);
  input.required = !hasAccountEmail;
  input.placeholder = hasAccountEmail
    ? `默认使用账号邮箱：${state.user.email}`
    : '请输入邮箱，用于接收处理回复';
}

function syncFeatureEmailRequirement() {
  const input = $('featureContact');
  if (!input) return;
  const hasAccountEmail = Boolean(state.user?.email);
  input.required = !hasAccountEmail;
  input.placeholder = hasAccountEmail
    ? `默认使用账号邮箱：${state.user.email}`
    : '请输入邮箱，用于接收状态更新';
}

function pastedImageFiles(event) {
  const clipboard = event.clipboardData;
  if (!clipboard) return [];
  const itemFiles = Array.from(clipboard.items || [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter(Boolean);
  if (itemFiles.length) return itemFiles;
  return Array.from(clipboard.files || []).filter((file) => file.type.startsWith('image/'));
}

function handleFeedbackPaste(event) {
  const view = $('view-feedback');
  if (!view || !view.classList.contains('is-active')) return;
  const form = $('feedbackForm');
  if (state.feedbackPanel !== 'submit' && !form?.matches(':focus-within')) return;
  const files = pastedImageFiles(event);
  if (!files.length) return;
  event.preventDefault();
  setFeedbackFiles(files, { append: true });
  const hint = $('feedbackDropHint');
  if (!hint) return;
  hint.classList.add('is-active');
  clearTimeout(handleFeedbackPaste.timer);
  handleFeedbackPaste.timer = setTimeout(() => hint.classList.remove('is-active'), 1200);
}

function replyKey(parentId = null) {
  return parentId ? String(parentId) : 'root';
}

function replyFiles(parentId = null) {
  return state.replyFiles[replyKey(parentId)] || [];
}

function revokeReplyPreviewUrls(key) {
  (state.replyPreviewUrls[key] || []).forEach((url) => URL.revokeObjectURL(url));
  state.replyPreviewUrls[key] = [];
}

function renderReplyImagePreview(parentId = null) {
  const key = replyKey(parentId);
  const files = replyFiles(parentId);
  revokeReplyPreviewUrls(key);
  state.replyPreviewUrls[key] = files.map((file) => URL.createObjectURL(file));
  return files.map((file, index) => `
    <figure class="reply-image-item">
      <button
        class="reply-image-preview-button"
        type="button"
        data-preview-reply-image="${index}"
        aria-label="查看图片：${escapeHtml(file.name)}"
      >
        <img src="${escapeHtml(state.replyPreviewUrls[key][index])}" alt="${escapeHtml(file.name)}">
      </button>
      <figcaption>
        <span>${escapeHtml(file.name)}</span>
        <button class="icon-button" type="button" data-remove-reply-image="${index}" aria-label="移除图片">X</button>
      </figcaption>
    </figure>
  `).join('');
}

function updateReplyImagePreview(parentId = null) {
  const key = replyKey(parentId);
  const target = document.querySelector(`[data-reply-preview="${key}"]`);
  if (!target) return;
  target.innerHTML = renderReplyImagePreview(parentId);
  target.classList.toggle('is-empty', !replyFiles(parentId).length);
}

function setReplyFiles(parentId, files, options = {}) {
  const selected = validateImageFiles(files, '图片');
  if (!selected.length) return;
  const key = replyKey(parentId);
  const append = options.append === true;
  const current = append ? replyFiles(parentId) : [];
  const capacity = MAX_REPLY_IMAGES - current.length;
  if (capacity <= 0) {
    toast(`单次回复最多上传 ${MAX_REPLY_IMAGES} 张图片`);
    return;
  }
  const kept = selected.slice(0, capacity);
  if (selected.length > capacity) {
    toast(`单次回复最多上传 ${MAX_REPLY_IMAGES} 张图片，已保留 ${capacity} 张`);
  }
  state.replyFiles[key] = [...current, ...kept];
  updateReplyImagePreview(parentId);
}

function clearReplyFiles(parentId = null) {
  const key = replyKey(parentId);
  revokeReplyPreviewUrls(key);
  delete state.replyFiles[key];
  delete state.replyPreviewUrls[key];
}

function clearAllReplyFiles() {
  Object.keys(state.replyPreviewUrls).forEach(revokeReplyPreviewUrls);
  state.replyFiles = {};
  state.replyPreviewUrls = {};
}

function parentIdFromReplyForm(form) {
  const value = form?.dataset.parentId || '';
  return value ? Number(value) : null;
}

function handleReplyPaste(event) {
  const view = $('view-thread');
  if (!view || !view.classList.contains('is-active')) return;
  const target = event.target instanceof Element ? event.target : null;
  const form = target?.closest('[data-reply-form]') || document.querySelector('[data-reply-form]:focus-within');
  if (!form) return;
  const files = pastedImageFiles(event);
  if (!files.length) return;
  event.preventDefault();
  setReplyFiles(parentIdFromReplyForm(form), files, { append: true });
}

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  return headers;
}

async function api(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    if (response.status === 401 && state.token) {
      clearSession();
      updateAuthUi();
    }
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.classList.remove('hidden');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.add('hidden'), 2600);
}

function setFeedbackSubmitSuccess(message = '') {
  const node = $('feedbackSubmitSuccess');
  if (!node) return;
  const text = String(message || '').trim();
  node.textContent = text;
  node.classList.toggle('hidden', !text);
}

function setFeatureSubmitSuccess(message = '') {
  const node = $('featureSubmitSuccess');
  if (!node) return;
  const text = String(message || '').trim();
  node.textContent = text;
  node.classList.toggle('hidden', !text);
}

function track(event, target = '') {
  api('/api/track', {
    method: 'POST',
    body: JSON.stringify({
      event,
      target,
      path: `${location.pathname}${location.hash || ''}`,
      referrer: document.referrer || '',
    }),
  }).catch(() => {});
}

async function loadAvatarOptions() {
  state.builtinAvatars = DEFAULT_BUILTIN_AVATARS;
  try {
    const data = await api('/api/avatar-options');
    if (Array.isArray(data.avatars) && data.avatars.length) {
      state.builtinAvatars = data.avatars.map((item) => ({
        id: String(item.id || ''),
        name: String(item.name || '内置头像'),
        url: safeAvatarUrl(item.url),
      }));
    }
    if (data.upload && Number(data.upload.max_bytes)) {
      state.avatarUploadLimit = Number(data.upload.max_bytes);
    }
  } catch (_error) {
    state.builtinAvatars = DEFAULT_BUILTIN_AVATARS;
  }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  localStorage.setItem('cfquant_site_theme', theme);
  const toggle = $('themeToggle');
  const nextLabel = theme === 'dark' ? '切换浅色主题' : '切换深色主题';
  toggle.title = nextLabel;
  toggle.setAttribute('aria-label', nextLabel);
  toggle.querySelector('.theme-icon').textContent = theme === 'dark' ? 'L' : 'D';
}

function initTheme() {
  const saved = localStorage.getItem('cfquant_site_theme');
  const preferred = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  setTheme(saved || preferred);
}

function emptyLoginMemory() {
  return { account: '', remember: true };
}

function encodeLoginMemory(value) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(value))));
}

function decodeLoginMemory(value) {
  return JSON.parse(decodeURIComponent(escape(atob(value))));
}

function readLoginMemory() {
  const raw = localStorage.getItem(LOGIN_MEMORY_KEY);
  if (!raw) return emptyLoginMemory();
  try {
    const data = decodeLoginMemory(raw);
    const memory = {
      account: String(data.account || ''),
      remember: data.remember !== false,
    };
    if (data.password || Object.prototype.hasOwnProperty.call(data, 'autoLogin')) {
      writeLoginMemory(memory);
    }
    return memory;
  } catch (_error) {
    localStorage.removeItem(LOGIN_MEMORY_KEY);
    return emptyLoginMemory();
  }
}

function writeLoginMemory(data) {
  if (!data.remember) {
    localStorage.removeItem(LOGIN_MEMORY_KEY);
    return;
  }
  localStorage.setItem(LOGIN_MEMORY_KEY, encodeLoginMemory({
    account: String(data.account || '').trim(),
    remember: true,
  }));
}

function fillLoginFormFromMemory() {
  const accountInput = $('loginAccount');
  const passwordInput = $('loginPassword');
  const rememberInput = $('loginRemember');
  const autoLoginInput = $('loginAutoLogin');
  if (!accountInput || !passwordInput || !rememberInput || !autoLoginInput) return;
  const memory = readLoginMemory();
  if (memory.account && !accountInput.value) accountInput.value = memory.account;
  rememberInput.checked = memory.remember;
  autoLoginInput.checked = true;
  autoLoginInput.disabled = true;
}

function saveLoginMemoryFromForm() {
  const rememberInput = $('loginRemember');
  const autoLoginInput = $('loginAutoLogin');
  if (!rememberInput || !autoLoginInput) return;
  writeLoginMemory({
    account: $('loginAccount').value,
    remember: rememberInput.checked,
  });
}

function disableRememberedAutoLogin() {
  fillLoginFormFromMemory();
}

function bindLoginMemoryControls() {
  fillLoginFormFromMemory();
  $('loginRemember').addEventListener('change', () => {
    $('loginAutoLogin').checked = true;
    $('loginAutoLogin').disabled = true;
    saveLoginMemoryFromForm();
  });
  $('loginAutoLogin').addEventListener('change', saveLoginMemoryFromForm);
}

function setMode(mode) {
  const data = MODE_COPY[mode] || MODE_COPY.normal;
  $$('[data-mode]').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.mode === mode);
  });
  const qmt = $('modeQmt');
  if (qmt) qmt.innerHTML = data.qmt;
  setText('modePython', data.python);
  setText('modeScript', data.script);
  setText('modeUse', data.use);
  const panel = $('mode-detail-panel');
  if (panel && !REDUCE_MOTION) {
    panel.animate([{ transform: 'translateY(6px)', opacity: 0.72 }, { transform: 'translateY(0)', opacity: 1 }], {
      duration: 220,
      easing: 'cubic-bezier(.16,1,.3,1)',
    });
  }
}

function showArchDetail(id) {
  const data = ARCH_NODES[id];
  if (!data) return;
  setText('archDetailLayer', data.layer);
  setText('archDetailTitle', data.label);
  setText('archDetailPath', data.path);
  setText('archDetailBody', data.body);
  setText('archStepLabel', data.body);
}

function renderArchChain(steps) {
  const chain = $('archCurrentChain');
  if (!chain) return;
  chain.replaceChildren();
  steps.forEach((id, index) => {
    const item = document.createElement('span');
    item.className = index === state.archStep ? 'is-current' : '';
    item.textContent = ARCH_NODES[id]?.label || id;
    chain.appendChild(item);
  });
}

function renderArchSteps(steps) {
  const list = $('archStepList');
  if (!list) return;
  list.replaceChildren();
  steps.forEach((id, index) => {
    const item = document.createElement('div');
    item.className = `arch-step-item${index === state.archStep ? ' is-current' : ''}`;
    const marker = document.createElement('i');
    marker.textContent = String(index + 1);
    const copy = document.createElement('p');
    copy.className = 'help';
    copy.textContent = ARCH_NODES[id]?.body || id;
    item.append(marker, copy);
    list.appendChild(item);
  });
}

function setArchRoute(route, step = 0) {
  const data = ARCH_ROUTES[route] || ARCH_ROUTES.overview;
  state.archRoute = ARCH_ROUTES[route] ? route : 'overview';
  state.archStep = Math.max(0, Math.min(step, data.steps.length - 1));
  const currentNode = data.steps[state.archStep];
  const activeIds = new Set(data.steps);
  const progress = data.steps.length <= 1 ? 1 : (state.archStep + 1) / data.steps.length;

  $$('.arch-route-btn').forEach((button) => {
    const active = button.dataset.archRoute === state.archRoute;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', String(active));
  });
  setText('archRouteType', data.type);
  setText('archRouteSummaryTitle', data.summaryTitle);
  setText('archRouteSummary', data.summary);
  setText('archRouteDecision', data.decision);
  setText('archRouteTitle', data.title);
  setText('archRouteLead', data.lead);
  setText('archStepIndicator', `${state.archStep + 1} / ${data.steps.length}`);
  setText('archStatus', state.archRoute === 'callback' ? '事件流' : state.archRoute === 'runtime' ? '配置视图' : '可交互');
  const progressBar = $('archProgress');
  if (progressBar) progressBar.style.transform = `scaleX(${progress})`;

  $$('.arch-node').forEach((node) => {
    const id = node.dataset.archNode;
    const inRoute = activeIds.has(id);
    const current = id === currentNode;
    node.classList.toggle('is-in-route', inRoute);
    node.classList.toggle('is-current', current);
    node.classList.toggle('is-muted', !inRoute);
    node.setAttribute('aria-pressed', String(current));
  });

  showArchDetail(currentNode);
  renderArchChain(data.steps);
  renderArchSteps(data.steps);
}

function stopArch() {
  if (!state.archTimer) return;
  clearInterval(state.archTimer);
  state.archTimer = null;
  setText('archPlay', '播放');
}

function moveArchStep(delta) {
  stopArch();
  const steps = ARCH_ROUTES[state.archRoute].steps;
  setArchRoute(state.archRoute, Math.max(0, Math.min(state.archStep + delta, steps.length - 1)));
}

function toggleArchPlayback() {
  if (state.archTimer) {
    stopArch();
    return;
  }
  const steps = ARCH_ROUTES[state.archRoute].steps;
  if (state.archStep >= steps.length - 1) setArchRoute(state.archRoute, 0);
  setText('archPlay', '暂停');
  state.archTimer = setInterval(() => {
    const routeSteps = ARCH_ROUTES[state.archRoute].steps;
    if (state.archStep >= routeSteps.length - 1) {
      stopArch();
      return;
    }
    setArchRoute(state.archRoute, state.archStep + 1);
  }, REDUCE_MOTION ? 900 : 1150);
}

function filterArchModules() {
  const input = $('archModuleSearch');
  const layerFilter = $('archLayerFilter');
  if (!input || !layerFilter) return;
  const query = input.value.trim().toLowerCase();
  const layer = layerFilter.value;
  let visible = 0;
  $$('.arch-module-row').forEach((row) => {
    const matched = (layer === 'all' || row.dataset.layer === layer) && (!query || row.dataset.search.toLowerCase().includes(query));
    row.hidden = !matched;
    if (matched) visible += 1;
  });
  setText('archModuleCount', `${visible} 个模块`);
  const empty = $('archModuleEmpty');
  if (empty) empty.hidden = visible !== 0;
}

function clearArchModules() {
  const search = $('archModuleSearch');
  const filter = $('archLayerFilter');
  if (search) search.value = '';
  if (filter) filter.value = 'all';
  filterArchModules();
}

function setLifeState(key) {
  const data = LIFE_COPY[key] || LIFE_COPY.imported;
  $$('.life-step').forEach((step) => {
    step.classList.toggle('is-active', step.dataset.life === key);
  });
  setText('lifeStatus', data.status);
  setText('lifeTitle', data.title);
  setText('lifeBody', data.body);
}

function flowNode(id) {
  return document.querySelector(`[data-flow-node="${id}"]`);
}

function flowPoint(rect, bounds) {
  return {
    x: rect.left - bounds.left + rect.width / 2,
    y: rect.top - bounds.top + rect.height / 2,
  };
}

function flowPath(start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const midX = start.x + dx / 2;
  const midY = start.y + dy / 2;
  const n = (value) => Math.round(value * 10) / 10;
  if (Math.abs(dx) >= Math.abs(dy)) {
    return `M ${n(start.x)} ${n(start.y)} C ${n(midX)} ${n(start.y)}, ${n(midX)} ${n(end.y)}, ${n(end.x)} ${n(end.y)}`;
  }
  return `M ${n(start.x)} ${n(start.y)} C ${n(start.x)} ${n(midY)}, ${n(end.x)} ${n(midY)}, ${n(end.x)} ${n(end.y)}`;
}

function getFlowSegment(fromId, toId) {
  const network = document.querySelector('.flow-network');
  const fromEl = flowNode(fromId);
  const toEl = flowNode(toId);
  if (!network || !fromEl || !toEl) return null;
  const bounds = network.getBoundingClientRect();
  if (bounds.width < 1 || bounds.height < 1) return null;
  const start = flowPoint(fromEl.getBoundingClientRect(), bounds);
  const end = flowPoint(toEl.getBoundingClientRect(), bounds);
  return { start, end, path: flowPath(start, end) };
}

function drawFlowGeometry() {
  const network = document.querySelector('.flow-network');
  const svg = document.querySelector('.flow-svg');
  if (!network || !svg) return false;
  const bounds = network.getBoundingClientRect();
  if (bounds.width < 1 || bounds.height < 1) return false;
  svg.setAttribute('viewBox', `0 0 ${Math.round(bounds.width)} ${Math.round(bounds.height)}`);
  FLOW_EDGES.forEach(([from, to, key]) => {
    const path = document.querySelector(`[data-flow-link="${key}"]`);
    const segment = getFlowSegment(from, to);
    if (path && segment) path.setAttribute('d', segment.path);
  });
  return true;
}

function setFlowPacketPoint(point) {
  const packet = $('flowPacket');
  if (!packet || !point) return;
  packet.style.setProperty('--packet-x', `${point.x}px`);
  packet.style.setProperty('--packet-y', `${point.y}px`);
}

function placeFlowPacket(data, step) {
  const currentNode = data.steps[step];
  const nextNode = data.steps[step + 1];
  const previousNode = data.steps[step - 1];
  const segment = previousNode
    ? getFlowSegment(previousNode, currentNode)
    : nextNode
      ? getFlowSegment(currentNode, nextNode)
      : null;
  if (!segment) return;
  setFlowPacketPoint(previousNode ? segment.end : segment.start);
}

function animateFlowPacket(fromId, toId) {
  const packet = $('flowPacket');
  const segment = getFlowSegment(fromId, toId);
  if (!packet || !segment || typeof packet.animate !== 'function') return false;
  packet.getAnimations().forEach((animation) => animation.cancel());
  const startTransform = `translate3d(${segment.start.x}px, ${segment.start.y}px, 0) translate(-50%, -50%) scale(.9)`;
  const endTransform = `translate3d(${segment.end.x}px, ${segment.end.y}px, 0) translate(-50%, -50%) scale(1)`;
  setFlowPacketPoint(segment.end);
  packet.animate(
    [
      { opacity: 0.18, transform: startTransform },
      { opacity: 1, transform: startTransform, offset: 0.18 },
      { opacity: 1, transform: endTransform },
    ],
    { duration: 680, easing: 'cubic-bezier(.16,1,.3,1)' },
  );
  return true;
}

function renderFlowTimeline(steps) {
  const timeline = $('flowTimeline');
  if (!timeline) return;
  timeline.replaceChildren();
  steps.forEach((id, index) => {
    const item = document.createElement('span');
    item.className = index === state.flowStep ? 'is-current' : '';
    item.textContent = FLOW_NODE_LABELS[id] || id;
    timeline.appendChild(item);
  });
}

function renderFlowEvents(events) {
  const list = $('flowEvents');
  if (!list) return;
  list.replaceChildren();
  events.forEach((eventLabel, index) => {
    const row = document.createElement('div');
    row.className = `event-row${index === state.flowStep ? ' is-current' : ''}`;
    const marker = document.createElement('i');
    marker.textContent = String(index + 1);
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = eventLabel;
    const meta = document.createElement('span');
    meta.textContent = index <= state.flowStep ? '已进入当前演示链路' : '等待下一跳';
    body.append(title, meta);
    row.append(marker, body);
    list.appendChild(row);
  });
}

function setDataFlow(mode, step = 0, options = {}) {
  const data = FLOW_MODES[mode] || FLOW_MODES.request;
  state.flowMode = FLOW_MODES[mode] ? mode : 'request';
  state.flowStep = Math.max(0, Math.min(step, data.steps.length - 1));
  const currentNode = data.steps[state.flowStep];
  const activeNodes = new Set(data.steps);
  const activeLinks = new Set();
  const currentPair = options.animateFrom && options.animateFrom !== currentNode
    ? `${options.animateFrom}>${currentNode}`
    : state.flowStep > 0
      ? `${data.steps[state.flowStep - 1]}>${currentNode}`
      : `${currentNode}>${data.steps[state.flowStep + 1] || currentNode}`;
  const currentLink = FLOW_LINK_MAP[currentPair];

  for (let i = 0; i < data.steps.length - 1; i += 1) {
    if (i < state.flowStep) {
      const link = FLOW_LINK_MAP[`${data.steps[i]}>${data.steps[i + 1]}`];
      if (link) activeLinks.add(link);
    }
  }
  if (currentLink) activeLinks.add(currentLink);

  $$('.flow-mode-btn').forEach((button) => {
    const active = button.dataset.flowMode === state.flowMode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', String(active));
  });
  setText('flowStatus', data.status);
  setText('flowTitle', data.title);
  setText('flowLead', data.lead);
  setText('flowPayloadType', data.payloadType);
  setText('flowPayloadTitle', data.payloadTitle);
  setText('flowPayloadCopy', data.payloadCopy);
  setText('flowChannel', data.channel);
  setText('flowPayload', data.payload);
  setText('flowHop', FLOW_NODE_LABELS[currentNode] || currentNode);
  setText('flowRule', data.rule);
  setText('flowEventCount', `${state.flowStep + 1} / ${data.steps.length}`);

  $$('.flow-system-node').forEach((node) => {
    const id = node.dataset.flowNode;
    const current = id === currentNode;
    const inFlow = activeNodes.has(id);
    node.classList.toggle('is-current', current);
    node.classList.toggle('is-in-flow', inFlow);
    node.classList.toggle('is-muted', !inFlow);
    node.setAttribute('aria-pressed', String(current));
  });
  $$('.flow-link').forEach((link) => {
    const active = activeLinks.has(link.dataset.flowLink);
    const current = link.dataset.flowLink === currentLink;
    const reverse = current && link.dataset.from && link.dataset.to && `${link.dataset.from}>${link.dataset.to}` !== currentPair;
    link.classList.toggle('is-active', active);
    link.classList.toggle('is-current', current);
    link.classList.toggle('is-reverse', reverse);
  });

  drawFlowGeometry();
  const shouldAnimate = !REDUCE_MOTION && options.animateFrom && options.animateFrom !== currentNode;
  if (!shouldAnimate || !animateFlowPacket(options.animateFrom, currentNode)) placeFlowPacket(data, state.flowStep);
  renderFlowTimeline(data.steps);
  renderFlowEvents(data.events);
}

function stopDataFlow() {
  if (!state.flowTimer) return;
  clearInterval(state.flowTimer);
  state.flowTimer = null;
  setText('flowPlay', '播放流动');
}

function advanceDataFlow() {
  const data = FLOW_MODES[state.flowMode] || FLOW_MODES.request;
  const fromNode = data.steps[state.flowStep];
  const wrapped = state.flowStep >= data.steps.length - 1;
  const next = wrapped ? 0 : state.flowStep + 1;
  setDataFlow(state.flowMode, next, { animateFrom: wrapped ? null : fromNode });
}

function startDataFlow() {
  if (state.flowTimer || REDUCE_MOTION) {
    if (REDUCE_MOTION) setText('flowPlay', '播放流动');
    return;
  }
  setText('flowPlay', '暂停流动');
  advanceDataFlow();
  state.flowTimer = setInterval(advanceDataFlow, 980);
}

function toggleDataFlow() {
  if (REDUCE_MOTION) {
    toast('已按系统设置停用自动流动，可用下一跳查看。');
    return;
  }
  if (state.flowTimer) stopDataFlow();
  else startDataFlow();
}

function nextDataFlowStep() {
  stopDataFlow();
  advanceDataFlow();
}

function initArchitectureWorkbench() {
  if (!$('view-architecture')) return;
  if (!state.architectureInitialized) {
    state.architectureInitialized = true;
    $$('.arch-route-btn').forEach((button) => {
      button.addEventListener('click', () => {
        stopArch();
        setArchRoute(button.dataset.archRoute, 0);
      });
    });
    $('archPrev')?.addEventListener('click', () => moveArchStep(-1));
    $('archNext')?.addEventListener('click', () => moveArchStep(1));
    $('archPlay')?.addEventListener('click', toggleArchPlayback);
    $$('.arch-node').forEach((button) => {
      button.addEventListener('click', () => {
        stopArch();
        const id = button.dataset.archNode;
        const index = ARCH_ROUTES[state.archRoute].steps.indexOf(id);
        if (index >= 0) setArchRoute(state.archRoute, index);
        else showArchDetail(id);
      });
    });
    $('archModuleSearch')?.addEventListener('input', filterArchModules);
    $('archLayerFilter')?.addEventListener('change', filterArchModules);
    $('archModuleClear')?.addEventListener('click', clearArchModules);
    $$('.life-step').forEach((button) => {
      button.addEventListener('click', () => setLifeState(button.dataset.life));
    });
    $$('.flow-mode-btn').forEach((button) => {
      button.addEventListener('click', () => {
        setDataFlow(button.dataset.flowMode, 0);
        startDataFlow();
      });
    });
    $('flowPlay')?.addEventListener('click', toggleDataFlow);
    $('flowNext')?.addEventListener('click', nextDataFlowStep);
    $$('.flow-system-node').forEach((button) => {
      button.addEventListener('click', () => {
        const index = FLOW_MODES[state.flowMode].steps.indexOf(button.dataset.flowNode);
        if (index >= 0) {
          stopDataFlow();
          setDataFlow(state.flowMode, index);
        } else {
          toast('当前数据流不经过这个节点');
        }
      });
    });
    window.addEventListener('resize', () => {
      clearTimeout(state.flowResizeTimer);
      state.flowResizeTimer = setTimeout(() => setDataFlow(state.flowMode, state.flowStep), 80);
    });
  }
  setArchRoute(state.archRoute, state.archStep);
  filterArchModules();
  setLifeState($$('.life-step.is-active')[0]?.dataset.life || 'imported');
  setDataFlow(state.flowMode, state.flowStep);
}

function setFeedbackPanel(panel = 'public', options = {}) {
  const next = ['public', 'submit', 'mine'].includes(panel) ? panel : 'public';
  state.feedbackPanel = next;
  if (next === 'submit') setFeedbackSubmitSuccess('');
  syncFeedbackEmailRequirement();
  document.querySelectorAll('[data-feedback-panel]').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.feedbackPanel === next);
  });
  document.querySelectorAll('[data-feedback-panel-view]').forEach((section) => {
    section.classList.toggle('is-active', section.dataset.feedbackPanelView === next);
  });
  if (options.skipLoad) return;
  if (next === 'public') {
    loadPublicFeedback().catch((error) => toast(error.message));
  } else if (next === 'mine') {
    loadMyFeedback().catch((error) => toast(error.message));
  }
}

function setFeaturePanel(panel = 'public', options = {}) {
  const next = ['public', 'submit', 'mine'].includes(panel) ? panel : 'public';
  state.featurePanel = next;
  if (next === 'submit') setFeatureSubmitSuccess('');
  syncFeatureEmailRequirement();
  document.querySelectorAll('[data-feature-panel]').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.featurePanel === next);
  });
  document.querySelectorAll('[data-feature-panel-view]').forEach((section) => {
    section.classList.toggle('is-active', section.dataset.featurePanelView === next);
  });
  if (options.skipLoad) return;
  if (next === 'public') {
    loadPublicFeatures().catch((error) => toast(error.message));
  } else if (next === 'mine') {
    loadMyFeatures().catch((error) => toast(error.message));
  }
}

function setRouteHash(route) {
  const next = String(route || 'project').replace(/^#\/?/, '').trim() || 'project';
  const nextUrl = `/#${next}`;
  if (window.history && typeof window.history.pushState === 'function') {
    if (`${location.pathname}${location.hash}` !== nextUrl) {
      window.history.pushState({}, '', nextUrl);
    }
    return;
  }
  location.hash = next;
}

function switchView(view, options = {}) {
  const navView = view === 'thread' ? 'forum' : view;
  document.querySelector('.site-shell')?.classList.toggle('project-mode', view === 'project');
  if (view === 'architecture') initArchitectureWorkbench();
  document.querySelectorAll('.nav-tab').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.view === navView);
  });
  document.querySelectorAll('.view').forEach((section) => {
    section.classList.toggle('is-active', section.id === `view-${view}`);
  });
  if (!options.skipHash) {
    setRouteHash(options.hash || view);
  }
  $('siteLinks')?.classList.remove('is-open');
  $('mobileToggle')?.setAttribute('aria-expanded', 'false');
  track('nav', options.hash || view);
  if (view === 'downloads') loadDownloads();
  if (view === 'center') renderCenter();
  if (view === 'forum') loadThreads();
  if (view === 'features') {
    setFeaturePanel('public', { skipLoad: true });
    loadFeaturePanels().catch((error) => toast(error.message));
  }
  if (view === 'feedback') {
    setFeedbackPanel('public', { skipLoad: true });
    loadFeedbackPanels().catch((error) => toast(error.message));
  }
  if (view === 'architecture') {
    requestAnimationFrame(() => {
      setDataFlow(state.flowMode, state.flowStep);
      startDataFlow();
    });
  } else {
    stopArch();
    stopDataFlow();
  }
  if (view === 'project') startProjectCarousel();
  if (view !== 'project') stopProjectCarousel();
  if (view !== 'project') loadPublic().catch((error) => toast(error.message));
}

async function loadPublic() {
  const data = await api('/api/public');
  $('statUsers').textContent = formatCount(data.stats.users);
  $('statThreads').textContent = formatCount(data.stats.threads);
  $('statReplies').textContent = formatCount(data.stats.replies);
  $('statDownloads').textContent = formatCount(data.stats.downloads);
  $('hotThreads').innerHTML = (data.hot_threads || []).map((thread) => `
    <div class="compact-item">
      <button type="button" data-hot-thread="${thread.id}">${escapeHtml(thread.title)}</button>
      <span>${escapeHtml(thread.category_name || '')} · ${thread.reply_count} 回复 · ${thread.views} 浏览</span>
    </div>
  `).join('') || '<div class="empty-state"><span>暂无讨论</span></div>';
}

async function loadCategories() {
  const data = await api('/api/forum/categories');
  state.categories = data.categories || [];
  const tabs = [
    `<button type="button" class="${state.activeCategory ? '' : 'is-active'}" data-category="">全部</button>`,
    ...state.categories.map((item) => `
      <button type="button" class="${state.activeCategory === item.slug ? 'is-active' : ''}" data-category="${escapeHtml(item.slug)}">${escapeHtml(item.name)}</button>
    `),
  ];
  $('categoryTabs').innerHTML = tabs.join('');
  $('threadCategory').innerHTML = state.categories.map((item) => `
    <option value="${escapeHtml(item.slug)}">${escapeHtml(item.name)}</option>
  `).join('');
}

async function loadThreads() {
  const params = new URLSearchParams();
  if (state.activeCategory) params.set('category', state.activeCategory);
  const q = $('threadSearch').value.trim();
  if (q) params.set('q', q);
  const data = await api(`/api/forum/threads?${params.toString()}`);
  renderThreads(data.threads || []);
}

function renderThreads(threads) {
  if (!threads.length) {
    $('threadList').innerHTML = '<div class="empty-state"><strong>暂无匹配讨论</strong><span>换个关键词或发起新问题。</span></div>';
    return;
  }
  $('threadList').innerHTML = threads.map((thread) => {
    const tags = String(thread.tags || '').split(',').map((tag) => tag.trim()).filter(Boolean);
    return `
      <article class="thread-card" role="button" tabindex="0" data-thread-id="${thread.id}" aria-label="进入讨论：${escapeHtml(thread.title)}">
        <h2>${escapeHtml(thread.title)}</h2>
        <p>${escapeHtml(excerpt(thread.body))}</p>
        <div class="tag-line">
          <span class="status-pill ${thread.status === 'locked' ? 'locked' : ''}">${thread.status === 'locked' ? '已锁定' : '开放'}</span>
          ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
        </div>
        <div class="meta-line">
          <span>${escapeHtml(thread.category_name || '')}</span>
          <span class="author-inline">${avatarHtml({
            display_name: thread.author_name,
            avatar_url: thread.author_avatar_url,
            avatar_color: thread.author_color,
          }, 'avatar-badge-tiny')}${escapeHtml(thread.author_name || '')}</span>
          <span>${thread.reply_count} 回复</span>
          <span>${thread.views} 浏览</span>
          <span>${formatTime(thread.last_activity_at)}</span>
        </div>
      </article>
    `;
  }).join('');
}

async function openThread(threadId, options = {}) {
  const changedThread = String(state.selectedThreadId || '') !== String(threadId);
  state.selectedThreadId = threadId;
  if (changedThread) {
    state.expandedReplyIds.clear();
    state.replyComposeParentId = null;
    clearAllReplyFiles();
  }
  const data = await api(`/api/forum/threads/${threadId}`);
  const thread = data.thread;
  const replies = data.replies || [];
  state.currentThread = thread;
  state.currentReplies = replies;
  renderThreadPage(thread, replies);
  switchView('thread', { hash: `thread-${threadId}` });
  if (!options.skipTrack) track('thread_open', String(threadId));
}

function renderThreadPage(thread, replies) {
  const tags = String(thread.tags || '').split(',').map((tag) => tag.trim()).filter(Boolean);
  const { roots, childrenByParent } = groupReplies(replies);
  $('threadPageContent').innerHTML = `
    <article class="thread-article">
      <div class="detail-head">
        <p class="eyebrow">${escapeHtml(thread.category_name || 'Forum')}</p>
        <h2>${escapeHtml(thread.title)}</h2>
        <div class="meta-line">
          <span class="author-inline">${avatarHtml({
            display_name: thread.author_name,
            avatar_url: thread.author_avatar_url,
            avatar_color: thread.author_color,
          }, 'avatar-badge-tiny')}${escapeHtml(thread.author_name || '')}</span>
          <span>${formatTime(thread.created_at)}</span>
          <span>${thread.views} 浏览</span>
          <span>${replies.length} 回复</span>
        </div>
        <div class="tag-line">
          <span class="status-pill ${thread.status === 'locked' ? 'locked' : ''}">${thread.status === 'locked' ? '已锁定' : '开放'}</span>
          ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
        </div>
      </div>
      <div class="detail-body">${escapeHtml(thread.body)}</div>
    </article>
    <section class="conversation-card">
      <div class="panel-head">
        <h3>交流回复</h3>
        <span class="meta-line">${replies.length} 条回复</span>
      </div>
      <div class="reply-list">
        ${roots.map((reply) => renderReplyThread(reply, childrenByParent.get(Number(reply.id)) || [], thread)).join('') || '<div class="empty-state"><span>还没有回复</span></div>'}
      </div>
      ${renderReplyForm(thread)}
    </section>
  `;
}

function groupReplies(replies) {
  const byId = new Map(replies.map((reply) => [Number(reply.id), reply]));
  const roots = [];
  const childrenByParent = new Map();
  replies.forEach((reply) => {
    const parentId = Number(reply.parent_id || 0);
    if (!parentId || !byId.has(parentId)) {
      roots.push(reply);
      return;
    }
    const parent = byId.get(parentId);
    const rootId = Number(parent.parent_id || parentId);
    if (!childrenByParent.has(rootId)) childrenByParent.set(rootId, []);
    childrenByParent.get(rootId).push(reply);
  });
  return { roots, childrenByParent };
}

function renderReplyAttachments(attachments = []) {
  if (!attachments.length) return '';
  return `
    <div class="reply-attachments">
      ${attachments.map((attachment) => `
        <button
          class="reply-image-thumb"
          type="button"
          data-reply-attachment-url="${escapeHtml(attachment.url || '')}"
          data-reply-attachment-name="${escapeHtml(attachment.file_name || '回复图片')}"
          aria-label="查看图片：${escapeHtml(attachment.file_name || '回复图片')}"
        >
          <img src="${escapeHtml(apiUrl(attachment.url || ''))}" alt="${escapeHtml(attachment.file_name || '回复图片')}">
        </button>
      `).join('')}
    </div>
  `;
}

function renderReplyBody(reply) {
  return `
    <div class="reply-author">
      <span class="author-inline">${avatarHtml({
        display_name: reply.author_name,
        avatar_url: reply.author_avatar_url,
        avatar_color: reply.author_color,
      }, 'avatar-badge-tiny')}${escapeHtml(reply.author_name || '')}</span>
      <span>${formatTime(reply.created_at)}</span>
    </div>
    ${reply.body ? `<div class="reply-body">${escapeHtml(reply.body)}</div>` : ''}
    ${renderReplyAttachments(reply.attachments || [])}
  `;
}

function renderReplyActions(reply, thread) {
  if (thread.status === 'locked') return '';
  return `
    <div class="reply-actions">
      <button class="reply-link-button" type="button" data-reply-parent-id="${reply.id}">回复</button>
    </div>
  `;
}

function renderChildReply(reply, thread) {
  const parentId = Number(reply.id);
  return `
    <article class="reply-item reply-child" data-reply-id="${parentId}">
      ${renderReplyBody(reply)}
      ${renderReplyActions(reply, thread)}
      ${state.replyComposeParentId === parentId ? renderReplyForm(thread, parentId) : ''}
    </article>
  `;
}

function renderReplyThread(reply, children, thread) {
  const replyId = Number(reply.id);
  const expanded = state.expandedReplyIds.has(replyId);
  return `
    <article class="reply-item reply-root" data-reply-id="${replyId}">
      ${renderReplyBody(reply)}
      ${renderReplyActions(reply, thread)}
      ${state.replyComposeParentId === replyId ? renderReplyForm(thread, replyId) : ''}
      ${children.length ? `
        <button class="reply-expand" type="button" data-toggle-replies="${replyId}" data-child-count="${children.length}">
          ${expanded ? '收起回复' : `展开 ${children.length} 条回复`}
        </button>
        <div class="child-replies ${expanded ? '' : 'hidden'}" data-child-replies="${replyId}">
          ${children.map((child) => renderChildReply(child, thread)).join('')}
        </div>
      ` : ''}
    </article>
  `;
}

function renderReplyForm(thread, parentId = null) {
  if (thread.status === 'locked') {
    return '<div class="empty-state"><span>帖子已锁定，暂不能继续回复。</span></div>';
  }
  if (!state.user) {
    return '<button class="primary-button full" type="button" data-open-auth>登录后回复</button>';
  }
  const key = replyKey(parentId);
  const childClass = parentId ? ' is-child-form' : '';
  const previewClass = replyFiles(parentId).length ? '' : ' is-empty';
  return `
    <form class="reply-form${childClass}" data-reply-form data-parent-id="${parentId || ''}">
      <label class="reply-editor-label">
        <span>${parentId ? '回复这条讨论' : '回复内容'}</span>
        <div class="reply-editor-box">
          <textarea name="body" rows="${parentId ? 3 : 4}"></textarea>
          <div class="reply-image-preview${previewClass}" data-reply-preview="${key}">
            ${renderReplyImagePreview(parentId)}
          </div>
        </div>
      </label>
      <div class="reply-tool-row">
        <label class="reply-image-picker" title="选择图片，或在回复框中粘贴图片">
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple data-reply-upload>
          <span>图片</span>
        </label>
        ${parentId ? '<button class="ghost-button" type="button" data-cancel-reply>取消</button>' : ''}
        <button class="primary-button" type="submit">提交回复</button>
      </div>
    </form>
  `;
}

async function loadDownloads() {
  const [data, releaseResult] = await Promise.all([
    api('/api/downloads'),
    api('/api/releases/latest').catch((error) => ({ error: error.message })),
  ]);
  const latestRelease = releaseResult && releaseResult.release ? releaseResult.release : null;
  renderReleaseSummary(latestRelease, releaseResult && releaseResult.error);
  renderLatestRelease(latestRelease, releaseResult && releaseResult.error);
  const downloads = data.downloads || [];
  $('downloadList').innerHTML = downloads.map((item) => `
    <article class="download-card">
      <div>
        <span class="tag">${escapeHtml(item.channel || 'stable')}</span>
      </div>
      <h2>${escapeHtml(item.title)}</h2>
      <p>核心：${escapeHtml(item.core_version || item.version)}${item.web_version ? ` · Web：${escapeHtml(item.web_version)}` : ''} · 大小：${formatSize(item.file_size)} · 下载次数：${formatCount(item.download_count)}</p>
      <p>${escapeHtml(item.notes || '')}</p>
      ${item.sha256 ? `<code class="hash-line" title="${escapeHtml(item.sha256)}">SHA256 ${escapeHtml(item.sha256.slice(0, 16))}...</code>` : ''}
      <div class="form-actions">
        <a class="primary-button" href="${escapeHtml(apiUrl(`/api/downloads/${item.id}/download`))}" data-download-id="${item.id}">下载</a>
        ${item.external_url ? `<a class="ghost-button" href="${escapeHtml(item.external_url)}" target="_blank" rel="noreferrer">外部链接</a>` : ''}
      </div>
    </article>
  `).join('') || '<div class="empty-state"><strong>暂无更新包</strong><span>管理员可在后台登记本地包或镜像链接。</span></div>';
}

function renderLatestRelease(release, error = '') {
  const panel = $('releasePanel');
  if (!panel) return;
  if (!release) {
    panel.innerHTML = `
      <article class="release-card release-placeholder">
        <div class="release-main">
          <span class="tag">fallback</span>
          <h2>官网镜像包待登记</h2>
          <p>后台登记 official_site/packages 里的 zip 后，这里会显示版本、大小、SHA256 和更新日志。</p>
          ${error ? `<p class="meta-line">${escapeHtml(error)}</p>` : ''}
        </div>
        <div class="release-actions">
          <a class="ghost-button" href="https://github.com/95ge/cfquant" target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </article>`;
    return;
  }
  const changelog = release.changelog || {};
  const items = Array.isArray(changelog.items) ? changelog.items : [];
  panel.innerHTML = `
    <article class="release-card">
      <div class="release-main">
        <span class="tag">${escapeHtml(release.channel || 'project')}</span>
        <h2>${escapeHtml(release.title || 'cfquant 项目包')}</h2>
        <div class="release-meta">
          <span>核心 ${escapeHtml(release.core_version || release.version || '--')}</span>
          ${release.web_version ? `<span>Web ${escapeHtml(release.web_version)}</span>` : ''}
          <span>大小 ${formatSize(release.file_size)}</span>
          <span>更新 ${escapeHtml(formatTime(release.updated_at))}</span>
          <span>下载 ${formatCount(release.download_count)}</span>
        </div>
        ${release.sha256 ? `<code class="hash-line" title="${escapeHtml(release.sha256)}">SHA256 ${escapeHtml(release.sha256)}</code>` : ''}
      </div>
      <div class="release-actions">
        <a class="primary-button" href="${escapeHtml(apiUrl('/api/releases/latest/download'))}" data-download-id="${release.id || 'latest'}">下载最新项目</a>
        ${release.repo_url ? `<a class="ghost-button" href="${escapeHtml(release.repo_url)}" target="_blank" rel="noreferrer">GitHub</a>` : ''}
      </div>
      <div class="release-log">
        <h3>更新日志</h3>
        <ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('') || '<li>暂无更新日志</li>'}</ul>
      </div>
    </article>`;
}

function feedbackStatusLabel(value) {
  return {
    open: '待处理',
    processing: '处理中',
    closed: '已关闭',
  }[value] || value || '-';
}

function feedbackStatusClass(value) {
  return String(value || 'open').replace(/[^a-z0-9_-]/gi, '').toLowerCase();
}

function renderFeedbackAttachments(attachments = []) {
  if (!attachments.length) return '';
  return `
    <div class="feedback-attachments">
      ${attachments.map((attachment) => `
        <button
          class="feedback-image-thumb"
          type="button"
          data-feedback-attachment-url="${escapeHtml(attachment.url || '')}"
          data-feedback-attachment-name="${escapeHtml(attachment.file_name || '反馈图片')}"
          aria-label="查看图片：${escapeHtml(attachment.file_name || '反馈图片')}"
        >
          <img data-feedback-image-src="${escapeHtml(attachment.url || '')}" alt="${escapeHtml(attachment.file_name || '反馈图片')}">
          <span>${escapeHtml(attachment.file_name || '截图')} · ${formatSize(attachment.file_size)}</span>
        </button>
      `).join('')}
    </div>
  `;
}

function renderFeedbackReplies(replies = []) {
  if (!replies.length) return '';
  return `
    <div class="feedback-replies">
      <strong>处理回复</strong>
      ${replies.map((reply) => `
        <article class="feedback-reply">
          <div class="reply-author">
            <span>${reply.author_role === 'admin' ? '管理员' : '用户'}</span>
            <span>${formatTime(reply.created_at)}</span>
          </div>
          ${reply.body ? `<p>${escapeHtml(reply.body)}</p>` : '<p>[图片回复]</p>'}
          ${renderFeedbackAttachments(reply.attachments || [])}
        </article>
      `).join('')}
    </div>
  `;
}

function revokeFeedbackInlineImages(targetId) {
  (state.feedbackInlineImageUrls[targetId] || []).forEach((url) => URL.revokeObjectURL(url));
  state.feedbackInlineImageUrls[targetId] = [];
}

async function hydrateFeedbackImages(root, targetId) {
  const images = Array.from(root.querySelectorAll('img[data-feedback-image-src]'));
  await Promise.all(images.map(async (image) => {
    try {
      const url = await fetchFeedbackImage(image.dataset.feedbackImageSrc);
      state.feedbackInlineImageUrls[targetId].push(url);
      image.src = url;
      image.classList.add('is-loaded');
    } catch (_error) {
      image.alt = '图片加载失败';
      image.classList.add('is-error');
    }
  }));
}

function renderFeedbackFeed(targetId, items, options = {}) {
  const target = $(targetId);
  if (!target) return;
  revokeFeedbackInlineImages(targetId);
  if (options.kind === 'mine' && !state.user) {
    target.innerHTML = `
      <div class="empty-state">
        <strong>登录后查看处理进度</strong>
        <span>已注册用户提交的问题会自动汇总到这里。</span>
        <button class="ghost-button" type="button" data-open-auth>注册 / 登录</button>
      </div>
    `;
    return;
  }
  if (!items.length) {
    target.innerHTML = options.kind === 'mine'
      ? '<div class="empty-state"><span>暂未提交反馈</span></div>'
      : '<div class="empty-state"><span>暂无公开反馈</span></div>';
    return;
  }
  target.innerHTML = items.map((item) => {
    const isPublic = Boolean(Number(item.is_public));
    return `
      <article class="feedback-item">
        <div class="feedback-item-head">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <span>#${escapeHtml(item.id)} · ${formatTime(item.created_at)}</span>
          </div>
          <div class="feedback-state-line">
            <span class="status-pill ${feedbackStatusClass(item.status)}">${feedbackStatusLabel(item.status)}</span>
            ${options.showVisibility ? `<span class="visibility-pill ${isPublic ? 'is-public' : ''}">${isPublic ? '已公开' : '未公开'}</span>` : ''}
          </div>
        </div>
        ${options.showReporter ? `<div class="meta-line"><span>${escapeHtml(item.reporter || '匿名用户')}</span></div>` : ''}
        <p>${escapeHtml(excerpt(item.body, 180))}</p>
        ${renderFeedbackAttachments(item.attachments || [])}
        ${renderFeedbackReplies(item.replies || [])}
        <div class="meta-line">
          <span>更新：${formatTime(item.updated_at)}</span>
        </div>
      </article>
    `;
  }).join('');
  hydrateFeedbackImages(target, targetId).catch(() => {});
}

async function loadMyFeedback() {
  if (!state.user) {
    renderFeedbackFeed('myFeedbackList', [], { kind: 'mine', showVisibility: true });
    return;
  }
  const data = await api('/api/feedback/mine');
  renderFeedbackFeed('myFeedbackList', data.feedback || [], { kind: 'mine', showVisibility: true });
}

async function loadPublicFeedback() {
  const data = await api('/api/feedback/public');
  renderFeedbackFeed('publicFeedbackList', data.feedback || [], { kind: 'public', showReporter: true });
}

async function loadFeedbackPanels() {
  await Promise.all([loadPublicFeedback(), loadMyFeedback()]);
}

function featureStatusLabel(value) {
  return FEATURE_STATUS_LABELS[String(value || '').toLowerCase()] || value || '-';
}

function featureStatusClass(value) {
  return String(value || 'open').replace(/[^a-z0-9_-]/gi, '').toLowerCase();
}

function featureModuleLabel(value) {
  return FEATURE_MODULE_LABELS[String(value || '').toLowerCase()] || value || '其它';
}

function featurePriorityLabel(value) {
  return FEATURE_PRIORITY_LABELS[String(value || '').toLowerCase()] || value || '常规';
}

function renderFeatureFeed(targetId, items, options = {}) {
  const target = $(targetId);
  if (!target) return;
  if (options.kind === 'mine' && !state.user) {
    target.innerHTML = `
      <div class="empty-state">
        <strong>登录后查看建议状态</strong>
        <span>已注册用户提交的建议会自动归档到这里。</span>
        <button class="ghost-button" type="button" data-open-auth>注册 / 登录</button>
      </div>
    `;
    return;
  }
  if (!items.length) {
    target.innerHTML = options.kind === 'mine'
      ? '<div class="empty-state"><span>暂未提交功能建议</span></div>'
      : '<div class="empty-state"><span>暂无功能建议</span></div>';
    return;
  }
  target.innerHTML = items.map((item) => `
    <article class="feedback-item feature-item">
      <div class="feedback-item-head feature-item-head">
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <span>#${escapeHtml(item.id)} · ${formatTime(item.created_at)}</span>
        </div>
        <div class="feedback-state-line feature-state-line">
          <span class="status-pill ${featureStatusClass(item.status)}">${escapeHtml(featureStatusLabel(item.status))}</span>
          <button class="btn btn-secondary feature-vote-button" type="button" data-feature-vote="${escapeHtml(item.id)}">投票 ${formatCount(item.vote_count || 0)}</button>
        </div>
      </div>
      <div class="feature-meta-grid">
        <span>模块：${escapeHtml(featureModuleLabel(item.module))}</span>
        <span>优先级：${escapeHtml(featurePriorityLabel(item.priority))}</span>
        ${options.showReporter ? `<span>提交人：${escapeHtml(item.reporter || '匿名用户')}</span>` : ''}
      </div>
      ${item.use_case ? `<p><strong>场景：</strong>${escapeHtml(excerpt(item.use_case, 180))}</p>` : ''}
      <p>${escapeHtml(excerpt(item.body, 220))}</p>
      <div class="meta-line">
        <span>更新：${formatTime(item.updated_at)}</span>
      </div>
    </article>
  `).join('');
}

async function loadPublicFeatures() {
  const data = await api('/api/features');
  renderFeatureFeed('featureList', data.features || [], { kind: 'public', showReporter: true });
}

async function loadMyFeatures() {
  if (!state.user) {
    renderFeatureFeed('myFeatureList', [], { kind: 'mine' });
    return;
  }
  const data = await api('/api/features/mine');
  renderFeatureFeed('myFeatureList', data.features || [], { kind: 'mine' });
}

async function loadFeaturePanels() {
  await Promise.all([loadPublicFeatures(), loadMyFeatures()]);
}

function hideImageModal() {
  const modal = $('imageModal');
  const image = $('imageModalImage');
  if (!modal || !image) return;
  modal.classList.add('hidden');
  image.removeAttribute('src');
  image.alt = '图片预览';
  if (state.imageModalObjectUrl) {
    URL.revokeObjectURL(state.imageModalObjectUrl);
    state.imageModalObjectUrl = '';
  }
}

function showImageModal(src, title = '图片预览', options = {}) {
  const modal = $('imageModal');
  const image = $('imageModalImage');
  const titleNode = $('imageModalTitle');
  if (!modal || !image || !titleNode || !src) return;
  if (state.imageModalObjectUrl && state.imageModalObjectUrl !== src) {
    URL.revokeObjectURL(state.imageModalObjectUrl);
    state.imageModalObjectUrl = '';
  }
  state.imageModalObjectUrl = options.objectUrl ? src : '';
  titleNode.textContent = title || '图片预览';
  image.src = src;
  image.alt = title || '图片预览';
  modal.classList.remove('hidden');
}

async function fetchFeedbackImage(url) {
  if (!url) return;
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(apiUrl(url), { headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `附件打开失败：${response.status}`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

function openReplyAttachment(url, title = '回复图片') {
  if (!url) return;
  showImageModal(apiUrl(url), title || '回复图片');
}

async function openFeedbackAttachment(url, title = '反馈图片') {
  const objectUrl = await fetchFeedbackImage(url);
  showImageModal(objectUrl, title || '反馈图片', { objectUrl: true });
}

function showAuth(mode = 'register') {
  state.authMode = mode;
  document.querySelectorAll('.switch-tab').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.authMode === mode);
  });
  $('registerForm').classList.toggle('hidden', mode !== 'register');
  $('loginForm').classList.toggle('hidden', mode !== 'login');
  if (mode === 'login') fillLoginFormFromMemory();
  $('authModal').classList.remove('hidden');
}

function hideAuth() {
  $('authModal').classList.add('hidden');
}

function saveSession(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem(SITE_TOKEN_KEY, token);
  localStorage.setItem(SITE_USER_KEY, JSON.stringify(user || null));
  updateAuthUi();
}

function clearSession() {
  state.token = '';
  state.user = null;
  localStorage.removeItem(SITE_TOKEN_KEY);
  localStorage.removeItem(SITE_USER_KEY);
}

function updateAuthUi() {
  syncFeedbackEmailRequirement();
  syncFeatureEmailRequirement();
  if (state.user) {
    $('authButton').classList.add('hidden');
    $('userButton').classList.remove('hidden');
    $('userButton').innerHTML = `
      ${avatarHtml(state.user, 'avatar-badge-small')}
      <span>${escapeHtml(state.user.display_name)}${state.user.unread_count ? ` · ${state.user.unread_count}` : ''}</span>
    `;
  } else {
    $('authButton').classList.remove('hidden');
    $('userButton').classList.add('hidden');
    $('userButton').innerHTML = '';
  }
}

async function refreshMe() {
  if (!state.token) {
    updateAuthUi();
    return;
  }
  try {
    const data = await api('/api/me');
    saveSession(state.token, data.user);
  } catch (_error) {
    clearSession();
  }
  updateAuthUi();
}

async function refreshActiveAuthViews() {
  if ($('view-center').classList.contains('is-active')) {
    await renderCenter();
  }
  if ($('view-feedback').classList.contains('is-active')) {
    await loadMyFeedback();
  }
  if ($('view-features').classList.contains('is-active')) {
    await loadMyFeatures();
  }
  if ($('view-thread').classList.contains('is-active') && state.selectedThreadId) {
    await openThread(state.selectedThreadId, { skipTrack: true });
  }
}

async function renderCenter() {
  const target = $('centerContent');
  if (!state.user) {
    target.innerHTML = `
      <div class="profile-panel">
        <h2>未登录</h2>
        <p class="meta-line">注册或登录后可查看互动通知与站内通知。</p>
        <button class="primary-button" type="button" data-open-auth>注册 / 登录</button>
      </div>
    `;
    return;
  }
  const data = await api('/api/notifications');
  const notifications = data.notifications || [];
  const wantsFeedbackEmail = state.user.email_notify_feedback !== 0 && state.user.email_notify_feedback !== false;
  const wantsThreadEmail = state.user.email_notify_thread !== 0 && state.user.email_notify_thread !== false;
  const currentAvatarUrl = safeAvatarUrl(state.user.avatar_url);
  target.innerHTML = `
    <aside class="profile-panel">
      <div class="profile-summary">
        <div data-profile-avatar-preview>${avatarHtml(state.user, 'avatar-badge-large')}</div>
        <div>
          <h2>${escapeHtml(state.user.display_name)}</h2>
          <p class="meta-line">用户名：${escapeHtml(state.user.username || '未设置')}</p>
          <p class="meta-line">手机号：${escapeHtml(state.user.phone)}</p>
          <p class="meta-line">邮箱：${escapeHtml(state.user.email || '未填写')}</p>
          <p class="meta-line">注册时间：${formatTime(state.user.created_at)}</p>
        </div>
      </div>
      <form class="auth-form account-profile-form" data-profile-form>
        <label>
          <span>昵称</span>
          <input name="display_name" type="text" maxlength="32" autocomplete="nickname" value="${escapeHtml(state.user.display_name || '')}" required>
        </label>
        <input name="avatar_url" type="hidden" value="${escapeHtml(currentAvatarUrl)}">
        <div class="avatar-picker">
          <div class="avatar-picker-head">
            <span>头像</span>
            <label class="ghost-button avatar-upload-button">
              <span>上传头像</span>
              <input name="avatar_file" type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-avatar-upload>
            </label>
          </div>
          <div class="avatar-grid" data-avatar-grid>
            ${renderAvatarPicker(currentAvatarUrl)}
          </div>
          <p class="meta-line">支持 png、jpg、webp、gif，最大 ${formatSize(state.avatarUploadLimit)}。</p>
        </div>
        <button class="ghost-button" type="submit">保存个人资料</button>
      </form>
      <form class="auth-form account-email-form" data-email-preference-form>
        <label>
          <span>通知邮箱</span>
          <input name="email" type="email" autocomplete="email" value="${escapeHtml(state.user.email || '')}" placeholder="用于接收反馈和帖子回复通知">
        </label>
        <div class="email-preference-list">
          <label class="check-field">
            <input name="email_notify_feedback" type="checkbox" ${wantsFeedbackEmail ? 'checked' : ''}>
            <span>反馈有处理回复时发邮件</span>
          </label>
          <label class="check-field">
            <input name="email_notify_thread" type="checkbox" ${wantsThreadEmail ? 'checked' : ''}>
            <span>帖子或评论有回复时发邮件</span>
          </label>
        </div>
        <button class="ghost-button" type="submit">保存邮箱通知</button>
      </form>
      <form class="auth-form account-password-form" data-password-form>
        <input name="username" type="text" autocomplete="username" value="${escapeHtml(state.user.username || '')}" hidden>
        <label>
          <span>${state.user.has_password ? '更新登录密码' : '设置登录密码'}</span>
          <input name="password" type="password" minlength="6" maxlength="128" autocomplete="new-password" required>
        </label>
        <label>
          <span>确认密码</span>
          <input name="passwordConfirm" type="password" minlength="6" maxlength="128" autocomplete="new-password" required>
        </label>
        <button class="ghost-button" type="submit">${state.user.has_password ? '更新密码' : '设置密码'}</button>
      </form>
      <div class="form-actions">
        <button class="ghost-button" type="button" data-logout>退出登录</button>
      </div>
    </aside>
    <section class="notifications-panel">
      <div class="panel-head">
        <h2>通知</h2>
        <button class="ghost-button" type="button" data-read-all>全部已读</button>
      </div>
      <div class="notification-list">
        ${notifications.map((item) => `
          <article class="notification-item ${item.read_at ? '' : 'unread'}">
            <div class="panel-head">
              <strong>${escapeHtml(item.title)}</strong>
              <span class="meta-line">${item.read_at ? '已读' : '未读'}</span>
            </div>
            <p>${escapeHtml(item.body)}</p>
            <div class="meta-line">
              <span>${formatTime(item.created_at)}</span>
              ${item.read_at ? '' : `<button class="ghost-button" type="button" data-read-notice="${item.id}">标记已读</button>`}
            </div>
          </article>
        `).join('') || '<div class="empty-state"><span>暂无通知</span></div>'}
      </div>
    </section>
  `;
}

function renderProjectDots() {
  const target = $('projectDots');
  if (!target) return;
  const slides = Array.from(document.querySelectorAll('.project-slide'));
  target.innerHTML = slides.map((_, index) => `
    <button class="${index === state.projectSlide ? 'is-active' : ''}" type="button" data-project-slide="${index}" aria-label="第 ${index + 1} 张"></button>
  `).join('');
}

function setProjectSlide(nextIndex) {
  const slides = Array.from(document.querySelectorAll('.project-slide'));
  if (!slides.length) return;
  state.projectSlide = (nextIndex + slides.length) % slides.length;
  slides.forEach((slide, index) => {
    slide.classList.toggle('is-active', index === state.projectSlide);
  });
  renderProjectDots();
}

function nextProjectSlide(delta = 1) {
  setProjectSlide(state.projectSlide + delta);
}

function startProjectCarousel() {
  if (!document.querySelector('.project-slide')) {
    stopProjectCarousel();
    return;
  }
  renderProjectDots();
  stopProjectCarousel();
  if (state.projectPaused || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  state.projectTimer = setInterval(() => nextProjectSlide(1), 5200);
}

function stopProjectCarousel() {
  if (!state.projectTimer) return;
  clearInterval(state.projectTimer);
  state.projectTimer = null;
}

function toggleProjectAutoplay() {
  const button = $('projectPause');
  if (!button) return;
  state.projectPaused = !state.projectPaused;
  button.textContent = state.projectPaused ? '▶' : 'Ⅱ';
  button.title = state.projectPaused ? '继续轮播' : '暂停轮播';
  button.setAttribute('aria-label', button.title);
  if (state.projectPaused) stopProjectCarousel();
  else startProjectCarousel();
}

async function handleRoute() {
  const route = currentRoute();
  if (/^thread-\d+$/.test(route)) {
    await openThread(route.replace('thread-', ''));
    return;
  }
  if (MAIN_VIEWS.includes(route)) {
    switchView(route, { skipHash: true });
  }
}

function currentRoute() {
  const hashRoute = (location.hash || '').replace(/^#\/?/, '').trim();
  if (hashRoute) return hashRoute;
  const pathRoute = location.pathname.replace(/^\/+|\/+$/g, '').trim();
  if (MAIN_VIEWS.includes(pathRoute)) return pathRoute;
  if (/^thread-\d+$/.test(pathRoute)) return pathRoute;
  return 'project';
}

function bindEvents() {
  bindLoginMemoryControls();

  $('themeToggle').addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    track('theme_toggle', document.documentElement.dataset.theme);
  });

  document.querySelectorAll('.nav-tab').forEach((button) => {
    button.addEventListener('click', () => switchView(button.dataset.view));
  });

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-jump-view]');
    if (!button) return;
    event.preventDefault();
    switchView(button.dataset.jumpView);
  });

  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-copy]');
    if (!button) return;
    const message = button.dataset.copy || '内容已复制';
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(message);
      }
    } catch (_error) {
      // Copy feedback is non-critical; the toast still gives the user the text.
    }
    toast(message);
  });

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-feedback-panel]');
    if (!button || button.closest('#feedbackMenu')) return;
    setFeedbackPanel(button.dataset.feedbackPanel);
  });

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-feature-panel]');
    if (!button || button.closest('#featureMenu')) return;
    setFeaturePanel(button.dataset.featurePanel);
  });

  const mobileToggle = $('mobileToggle');
  if (mobileToggle) {
    mobileToggle.addEventListener('click', () => {
      const links = $('siteLinks');
      const open = !links.classList.contains('is-open');
      links.classList.toggle('is-open', open);
      mobileToggle.setAttribute('aria-expanded', String(open));
    });
  }

  document.querySelectorAll('[data-mode]').forEach((button) => {
    button.addEventListener('click', () => setMode(button.dataset.mode));
  });

  const projectPrev = $('projectPrev');
  if (projectPrev) {
    projectPrev.addEventListener('click', () => {
      nextProjectSlide(-1);
      startProjectCarousel();
    });
  }

  const projectNext = $('projectNext');
  if (projectNext) {
    projectNext.addEventListener('click', () => {
      nextProjectSlide(1);
      startProjectCarousel();
    });
  }

  const projectPause = $('projectPause');
  if (projectPause) projectPause.addEventListener('click', toggleProjectAutoplay);

  const projectDots = $('projectDots');
  if (projectDots) {
    projectDots.addEventListener('click', (event) => {
      const button = event.target.closest('[data-project-slide]');
      if (!button) return;
      setProjectSlide(Number(button.dataset.projectSlide));
      startProjectCarousel();
    });
  }

  $('authButton').addEventListener('click', () => showAuth('register'));
  $('userButton').addEventListener('click', () => switchView('center'));
  $('closeAuth').addEventListener('click', hideAuth);
  $('authModal').addEventListener('click', (event) => {
    if (event.target === $('authModal')) hideAuth();
  });
  $('closeImageModal').addEventListener('click', hideImageModal);
  $('imageModal').addEventListener('click', (event) => {
    if (event.target === $('imageModal')) hideImageModal();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (!$('imageModal').classList.contains('hidden')) {
      hideImageModal();
    }
  });

  document.addEventListener('error', (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    const avatar = image.closest('.avatar-badge');
    if (avatar) avatar.classList.add('is-fallback');
  }, true);

  document.querySelectorAll('.switch-tab').forEach((button) => {
    button.addEventListener('click', () => showAuth(button.dataset.authMode));
  });

  $('feedbackMenu').addEventListener('click', (event) => {
    const button = event.target.closest('[data-feedback-panel]');
    if (!button) return;
    setFeedbackPanel(button.dataset.feedbackPanel);
    track('feedback_panel', button.dataset.feedbackPanel);
  });

  $('featureMenu').addEventListener('click', (event) => {
    const button = event.target.closest('[data-feature-panel]');
    if (!button) return;
    setFeaturePanel(button.dataset.featurePanel);
    track('feature_panel', button.dataset.featurePanel);
  });

  $('categoryTabs').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-category]');
    if (!button) return;
    state.activeCategory = button.dataset.category;
    loadCategories();
    loadThreads();
    track('forum_category', state.activeCategory || 'all');
  });

  let searchTimer = 0;
  $('threadSearch').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadThreads, 260);
  });

  $('threadList').addEventListener('click', (event) => {
    const card = event.target.closest('[data-thread-id]');
    if (!card) return;
    openThread(card.dataset.threadId).catch((error) => toast(error.message));
  });

  $('threadList').addEventListener('keydown', (event) => {
    if (!['Enter', ' '].includes(event.key)) return;
    const card = event.target.closest('[data-thread-id]');
    if (!card) return;
    event.preventDefault();
    openThread(card.dataset.threadId).catch((error) => toast(error.message));
  });

  $('hotThreads').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-hot-thread]');
    if (!button) return;
    switchView('forum');
    openThread(button.dataset.hotThread).catch((error) => toast(error.message));
  });

  $('backToForumButton').addEventListener('click', () => switchView('forum'));

  $('newThreadButton').addEventListener('click', () => {
    if (!state.user) {
      showAuth('register');
      return;
    }
    $('threadForm').classList.toggle('hidden');
    track('thread_compose_open');
  });

  $('cancelThreadButton').addEventListener('click', () => $('threadForm').classList.add('hidden'));

  $('threadForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!state.user) {
      showAuth('register');
      return;
    }
    try {
      const data = await api('/api/forum/threads', {
        method: 'POST',
        body: JSON.stringify({
          category: $('threadCategory').value,
          tags: $('threadTags').value,
          title: $('threadTitle').value,
          body: $('threadBody').value,
        }),
      });
      event.target.reset();
      $('threadForm').classList.add('hidden');
      await loadPublic();
      await loadThreads();
      await openThread(data.thread_id);
      toast('帖子已发布');
    } catch (error) {
      toast(error.message);
    }
  });

  $('threadPageContent').addEventListener('click', (event) => {
    if (event.target.closest('[data-open-auth]')) {
      showAuth('login');
      return;
    }
    const expandButton = event.target.closest('[data-toggle-replies]');
    if (expandButton) {
      const replyId = Number(expandButton.dataset.toggleReplies);
      const children = document.querySelector(`[data-child-replies="${replyId}"]`);
      if (!children) return;
      const nextExpanded = children.classList.contains('hidden');
      children.classList.toggle('hidden', !nextExpanded);
      if (nextExpanded) state.expandedReplyIds.add(replyId);
      else state.expandedReplyIds.delete(replyId);
      expandButton.textContent = nextExpanded ? '收起回复' : `展开 ${expandButton.dataset.childCount} 条回复`;
      return;
    }
    const replyButton = event.target.closest('[data-reply-parent-id]');
    if (replyButton) {
      if (!state.user) {
        showAuth('login');
        return;
      }
      const parentId = Number(replyButton.dataset.replyParentId);
      if (state.replyComposeParentId && state.replyComposeParentId !== parentId) {
        clearReplyFiles(state.replyComposeParentId);
      }
      state.replyComposeParentId = state.replyComposeParentId === parentId ? null : parentId;
      if (state.replyComposeParentId) {
        const parentReply = state.currentReplies.find((reply) => Number(reply.id) === parentId);
        const rootId = Number(parentReply?.parent_id || parentId);
        state.expandedReplyIds.add(rootId);
      }
      renderThreadPage(state.currentThread, state.currentReplies);
      return;
    }
    if (event.target.closest('[data-cancel-reply]')) {
      if (state.replyComposeParentId) clearReplyFiles(state.replyComposeParentId);
      state.replyComposeParentId = null;
      renderThreadPage(state.currentThread, state.currentReplies);
      return;
    }
    const removeImageButton = event.target.closest('[data-remove-reply-image]');
    if (removeImageButton) {
      const form = removeImageButton.closest('[data-reply-form]');
      const parentId = parentIdFromReplyForm(form);
      const files = replyFiles(parentId);
      files.splice(Number(removeImageButton.dataset.removeReplyImage), 1);
      state.replyFiles[replyKey(parentId)] = files;
      updateReplyImagePreview(parentId);
      return;
    }
    const previewImageButton = event.target.closest('[data-preview-reply-image]');
    if (previewImageButton) {
      const form = previewImageButton.closest('[data-reply-form]');
      const parentId = parentIdFromReplyForm(form);
      const index = Number(previewImageButton.dataset.previewReplyImage);
      const file = replyFiles(parentId)[index];
      const url = state.replyPreviewUrls[replyKey(parentId)]?.[index];
      if (url) showImageModal(url, file?.name || '回复图片');
      return;
    }
    const attachment = event.target.closest('[data-reply-attachment-url]');
    if (attachment) {
      openReplyAttachment(attachment.dataset.replyAttachmentUrl, attachment.dataset.replyAttachmentName);
    }
  });

  $('threadPageContent').addEventListener('change', (event) => {
    const input = event.target.closest('[data-reply-upload]');
    if (!input) return;
    const form = input.closest('[data-reply-form]');
    setReplyFiles(parentIdFromReplyForm(form), input.files, { append: true });
    input.value = '';
  });

  $('threadPageContent').addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-reply-form]');
    if (!form) return;
    event.preventDefault();
    const parentId = parentIdFromReplyForm(form);
    const body = form.elements.body.value;
    const files = replyFiles(parentId);
    if (body.trim().length < 2 && !files.length) {
      toast('回复内容不能为空');
      return;
    }
    try {
      const parentReply = parentId ? state.currentReplies.find((reply) => Number(reply.id) === parentId) : null;
      const rootId = parentId ? Number(parentReply?.parent_id || parentId) : null;
      const attachments = await Promise.all(files.map(fileToAttachment));
      await api(`/api/forum/threads/${state.selectedThreadId}/replies`, {
        method: 'POST',
        body: JSON.stringify({ body, parent_id: parentId, attachments }),
      });
      form.reset();
      clearReplyFiles(parentId);
      if (rootId) state.expandedReplyIds.add(rootId);
      state.replyComposeParentId = null;
      await loadPublic();
      await loadThreads();
      await openThread(state.selectedThreadId);
      toast('回复已提交');
    } catch (error) {
      toast(error.message);
    }
  });

  $('downloadList').addEventListener('click', (event) => {
    const link = event.target.closest('[data-download-id]');
    if (link) track('download', link.dataset.downloadId);
  });

  $('feedbackScreenshots').addEventListener('change', (event) => {
    setFeedbackFiles(event.target.files, { append: true });
    event.target.value = '';
  });

  $('feedbackPreview').addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-screenshot]');
    if (!button) return;
    state.feedbackFiles.splice(Number(button.dataset.removeScreenshot), 1);
    $('feedbackScreenshots').value = '';
    renderFeedbackPreview();
  });

  document.addEventListener('paste', handleFeedbackPaste);
  document.addEventListener('paste', handleReplyPaste);

  $('refreshMyFeedback').addEventListener('click', () => {
    loadMyFeedback().catch((error) => toast(error.message));
  });

  $('refreshPublicFeedback').addEventListener('click', () => {
    loadPublicFeedback().catch((error) => toast(error.message));
  });

  $('refreshPublicFeatures').addEventListener('click', () => {
    loadPublicFeatures().catch((error) => toast(error.message));
  });

  $('refreshMyFeatures').addEventListener('click', () => {
    loadMyFeatures().catch((error) => toast(error.message));
  });

  $('view-feedback').addEventListener('click', async (event) => {
    if (event.target.closest('[data-open-auth]')) {
      showAuth('register');
      return;
    }
    const attachment = event.target.closest('[data-feedback-attachment-url]');
    if (!attachment) return;
    try {
      await openFeedbackAttachment(attachment.dataset.feedbackAttachmentUrl, attachment.dataset.feedbackAttachmentName);
    } catch (error) {
      toast(error.message);
    }
  });

  $('view-features').addEventListener('click', async (event) => {
    if (event.target.closest('[data-open-auth]')) {
      showAuth('register');
      return;
    }
    const voteButton = event.target.closest('[data-feature-vote]');
    if (!voteButton) return;
    try {
      const data = await api(`/api/features/${voteButton.dataset.featureVote}/vote`, {
        method: 'POST',
        body: '{}',
      });
      await loadPublicFeatures();
      if (state.user) await loadMyFeatures();
      toast(data.voted ? '已记录投票' : '这个建议已经投过票');
    } catch (error) {
      toast(error.message);
    }
  });

  $('feedbackForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const contactEmail = $('feedbackContact').value.trim().toLowerCase();
    if (contactEmail && !isValidEmail(contactEmail)) {
      toast('请填写有效的联系邮箱');
      $('feedbackContact').focus();
      return;
    }
    if (!state.user?.email && !contactEmail) {
      toast('请先填写联系邮箱，方便接收处理回复');
      $('feedbackContact').focus();
      return;
    }
    try {
      const attachments = await Promise.all(state.feedbackFiles.map(fileToAttachment));
      const data = await api('/api/feedback', {
        method: 'POST',
        body: JSON.stringify({
          title: $('feedbackTitle').value,
          contact: contactEmail,
          body: $('feedbackBody').value,
          attachments,
        }),
      });
      if (data.user && state.token) {
        saveSession(state.token, data.user);
      }
      event.target.reset();
      state.feedbackFiles = [];
      renderFeedbackPreview();
      syncFeedbackEmailRequirement();
      await loadFeedbackPanels();
      setFeedbackPanel('public', { skipLoad: true });
      setFeedbackSubmitSuccess(`反馈 #${data.feedback_id} 已提交成功，管理员处理后会在这里同步更新。`);
      toast('反馈已提交并公开展示');
    } catch (error) {
      toast(error.message);
    }
  });

  $('featureForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const contactEmail = $('featureContact').value.trim().toLowerCase();
    if (contactEmail && !isValidEmail(contactEmail)) {
      toast('请填写有效的联系邮箱');
      $('featureContact').focus();
      return;
    }
    if (!state.user?.email && !contactEmail) {
      toast('请先填写联系邮箱，方便接收状态更新');
      $('featureContact').focus();
      return;
    }
    try {
      const data = await api('/api/features', {
        method: 'POST',
        body: JSON.stringify({
          title: $('featureTitle').value,
          module: $('featureModule').value,
          priority: $('featurePriority').value,
          contact: contactEmail,
          use_case: $('featureUseCase').value,
          body: $('featureBody').value,
        }),
      });
      if (data.user && state.token) {
        saveSession(state.token, data.user);
      }
      event.target.reset();
      syncFeatureEmailRequirement();
      await loadFeaturePanels();
      setFeaturePanel('public', { skipLoad: true });
      setFeatureSubmitSuccess(`建议 #${data.feature_id} 已提交成功，后续状态会在需求池同步。`);
      toast('功能建议已提交');
    } catch (error) {
      toast(error.message);
    }
  });

  $('centerContent').addEventListener('click', async (event) => {
    if (event.target.closest('[data-open-auth]')) {
      showAuth('register');
      return;
    }
    const avatarButton = event.target.closest('[data-profile-avatar]');
    if (avatarButton) {
      const form = avatarButton.closest('[data-profile-form]');
      const avatarUrl = safeAvatarUrl(avatarButton.dataset.profileAvatar);
      if (form?.elements.avatar_url) form.elements.avatar_url.value = avatarUrl;
      form?.querySelectorAll('[data-profile-avatar]').forEach((button) => {
        const active = safeAvatarUrl(button.dataset.profileAvatar) === avatarUrl;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      const preview = document.querySelector('[data-profile-avatar-preview]');
      if (preview) preview.innerHTML = avatarHtml({ ...state.user, avatar_url: avatarUrl }, 'avatar-badge-large');
      return;
    }
    if (event.target.closest('[data-logout]')) {
      await api('/api/auth/logout', { method: 'POST', body: '{}' }).catch(() => {});
      clearSession();
      disableRememberedAutoLogin();
      updateAuthUi();
      await refreshActiveAuthViews();
      toast('已退出登录');
      return;
    }
    const noticeButton = event.target.closest('[data-read-notice]');
    if (noticeButton) {
      await api(`/api/notifications/${noticeButton.dataset.readNotice}/read`, { method: 'POST', body: '{}' });
      await refreshMe();
      await renderCenter();
      return;
    }
    if (event.target.closest('[data-read-all]')) {
      await api('/api/notifications/read-all', { method: 'POST', body: '{}' });
      await refreshMe();
      await renderCenter();
    }
  });

  $('centerContent').addEventListener('change', async (event) => {
    const input = event.target.closest('[data-avatar-upload]');
    if (!input) return;
    const avatar = validateAvatarFile(input.files?.[0]);
    input.value = '';
    if (!avatar) return;
    try {
      const payload = await fileToAttachment(avatar);
      const data = await api('/api/me/avatar-upload', {
        method: 'POST',
        body: JSON.stringify({ avatar: payload }),
      });
      saveSession(state.token, data.user);
      await refreshActiveAuthViews();
      toast('头像已上传');
    } catch (error) {
      toast(error.message);
    }
  });

  $('centerContent').addEventListener('submit', async (event) => {
    const profileForm = event.target.closest('[data-profile-form]');
    if (profileForm) {
      event.preventDefault();
      const displayName = profileForm.elements.display_name.value.trim();
      if (!displayName) {
        toast('昵称不能为空');
        profileForm.elements.display_name.focus();
        return;
      }
      try {
        const data = await api('/api/me/profile', {
          method: 'POST',
          body: JSON.stringify({
            display_name: displayName,
            avatar_url: profileForm.elements.avatar_url.value,
          }),
        });
        saveSession(state.token, data.user);
        await refreshActiveAuthViews();
        toast('个人资料已保存');
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const emailForm = event.target.closest('[data-email-preference-form]');
    if (emailForm) {
      event.preventDefault();
      const email = emailForm.elements.email.value.trim().toLowerCase();
      const emailNotifyFeedback = emailForm.elements.email_notify_feedback.checked;
      const emailNotifyThread = emailForm.elements.email_notify_thread.checked;
      if (email && !isValidEmail(email)) {
        toast('邮箱格式不正确');
        emailForm.elements.email.focus();
        return;
      }
      if (!email && (emailNotifyFeedback || emailNotifyThread)) {
        toast('请填写邮箱，或关闭全部邮件通知');
        emailForm.elements.email.focus();
        return;
      }
      try {
        const data = await api('/api/me/preferences', {
          method: 'POST',
          body: JSON.stringify({
            email,
            email_notify_feedback: emailNotifyFeedback,
            email_notify_thread: emailNotifyThread,
          }),
        });
        saveSession(state.token, data.user);
        await renderCenter();
        toast('邮箱通知设置已保存');
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const form = event.target.closest('[data-password-form]');
    if (!form) return;
    event.preventDefault();
    const password = form.elements.password.value;
    if (password !== form.elements.passwordConfirm.value) {
      toast('两次输入的密码不一致');
      return;
    }
    try {
      const data = await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      state.user = data.user;
      updateAuthUi();
      await renderCenter();
      toast('登录密码已更新');
    } catch (error) {
      toast(error.message);
    }
  });

  $('registerForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if ($('registerPassword').value !== $('registerPasswordConfirm').value) {
      toast('两次输入的密码不一致');
      return;
    }
    try {
      const data = await api('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          username: $('registerUsername').value,
          phone: $('registerPhone').value,
          email: $('registerEmail').value,
          display_name: $('registerName').value,
          password: $('registerPassword').value,
        }),
      });
      saveSession(data.token, data.user);
      hideAuth();
      toast('注册成功');
      await refreshActiveAuthViews();
    } catch (error) {
      toast(error.message);
    }
  });

  $('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          account: $('loginAccount').value,
          password: $('loginPassword').value,
        }),
      });
      saveSession(data.token, data.user);
      saveLoginMemoryFromForm();
      hideAuth();
      toast('登录成功');
      await refreshActiveAuthViews();
    } catch (error) {
      toast(error.message);
    }
  });

  const routeChangeHandler = () => {
    handleRoute().catch((error) => toast(error.message));
  };
  window.addEventListener('hashchange', routeChangeHandler);
  window.addEventListener('popstate', routeChangeHandler);
}

async function init() {
  initTheme();
  bindEvents();
  setMode('normal');
  initArchitectureWorkbench();
  updateAuthUi();
  await Promise.all([loadAvatarOptions(), loadPublic(), loadReleaseSummary(), loadCategories(), loadThreads(), refreshMe()]);
  await handleRoute();
}

init().catch((error) => toast(error.message));
