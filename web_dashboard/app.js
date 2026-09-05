const FRONTEND_VERSION = 'web_20260905_14';

const state = {
  accountId: '',
  accountType: 'STOCK',
  accountKey: '',
  defaultAccountId: '',
  defaultAccountType: 'STOCK',
  defaultAccountKey: '',
  bridgeId: 'default',
  defaultBridgeId: 'default',
  queryChannel: 'normal',
  currentView: 'overview',
  settingsTab: 'api-key',
  statusTimer: null,
  lastOrderConfirm: '',
  callbackSeq: 0,
  orderSnapshot: new Map(),
  orderSnapshotReady: false,
  orderHighlights: new Map(),
  orderHighlightTimer: null,
  orderCallbackSocket: null,
  orderCallbackKey: '',
  orderCallbackSocketState: 'idle',
  orderCallbackSocketDetail: '',
  orderCallbackHello: null,
  orderCallbackReconnectTimer: null,
  orderCallbackRefreshTimer: null,
  orderCallbackRefreshInFlight: false,
  orderCallbackRefreshPending: false,
  orderCallbackRefreshSections: new Set(),
  orderCallbackMeta: new Map(),
  latestOrders: [],
  orderSort: { key: 'time', direction: 'desc' },
  cfquantOrderIds: new Set(),
  cfquantOrderRemarks: new Set(),
  callbackEvents: [],
  callbackLastEventAt: '',
  callbackLastEventName: '',
  lttxStatus: null,
  bridges: {},
  accountPairs: {},
  accountConfigs: {},
  setup: null,
  accountRouteMode: null,
  accountRouteFallback: false,
  envBridges: {},
  apiEndpointId: 'quote_subscribe_whole',
  apiKey: '',
  apiSocket: null,
  apiDebugRequestSeq: 0,
  downloadSocket: null,
  downloadJobId: '',
  downloadJobStatus: 'idle',
  downloadEvents: [],
  downloadStartedAt: 0,
  downloadRequestDoneAt: 0,
  downloadProgressTimer: null,
  taskProgressKind: 'download',
  serverAccess: null,
  webAuthToken: '',
  webAuthStatus: null,
  userProfile: null,
  builtinAvatars: [],
  profileSelectedAvatarUrl: '',
  profileUploadLimit: 2 * 1024 * 1024,
  appStarted: false,
  logCleanup: null,
  qmtLogLanguage: null,
  transportMode: 'ctypes',
  bridgeStatus: null,
  pipeHubStatus: null,
  updateStatus: null,
  updateBusy: false,
  qmtUpdateProgress: null,
  qmtUpdateProgressTimer: null,
  updateRestartNotice: null,
  versionInfo: null,
  versionCheckInFlight: false,
  versionRemoteChecked: false,
  versionUpdateBusy: false,
  projectUpdateStatus: null,
  projectUpdateBusy: false,
  apiOpenGroups: new Set(['data', 'trade', 'system', 'transport']),
  quoteRows: new Map(),
  quoteSeq: 0,
  quoteEventCount: 0,
  quoteSubscribeId: '',
  quoteConnectionText: '未连接',
  quoteLiveActive: false,
  quoteRenderTimer: null,
  quoteSocketLogCount: 0,
  quoteSocketMessageCount: 0,
  apiDebugBusy: false,
  onboardingStep: 'intro',
  onboardingDoneSteps: new Set(),
  lastLogKey: '',
  lastLogAt: 0,
  lastLogNode: null,
  lastLogRepeat: 0,
  statusRefreshInFlight: false,
  callbackRefreshInFlight: false,
  bindingStatusRefreshInFlight: false,
  bindingStatusRetryTimer: null,
  bindingStatusSnapshot: null,
  bindingVerifyBusyKey: '',
  bindingNoticeTimer: null,
  qmtScriptSourceCache: {},
  qmtScriptSourcePromises: {},
  qmtScriptRenderToken: 0,
  bindingQmtGuideValues: null,
  bindingQmtGuideDeploy: null,
  bindingQmtGuideContext: '',
  onboardingBindingValues: null,
  onboardingBindingFlowContext: '',
  onboardingBindingFlowReturnTarget: '',
  onboardingBindingFlowActive: false,
  onboardingBridgeCheckInFlight: false,
  onboardingBridgeCheckToken: 0,
  onboardingBridgeCheckAttempt: 0,
};

const $ = (id) => document.getElementById(id);
const ACCOUNT_PAIR_KEY = 'cfquant.account_bridge_pairs';
const ACCOUNT_SELECTION_KEY = 'cfquant.account_key';
const TUTORIAL_TOPIC_KEY = 'cfquant.tutorial_topic';
const DEPLOY_MODE_TAB_KEY = 'cfquant.deploy_mode_tab';
const ONBOARDING_AUTO_SHOWN_KEY = 'cfquant.onboarding_auto_shown.v3';
const SETTINGS_TAB_KEY = 'cfquant.settings_tab';
const API_OPEN_GROUPS_KEY = 'cfquant.api_open_groups';
const ACCOUNT_CONFIG_CACHE_KEY = 'cfquant.account_config_cache.v1';
const WEB_AUTH_TOKEN_KEY = 'cfquant.web_auth_token';
const WEB_AUTH_SESSION_TOKEN_KEY = 'cfquant.web_auth_session_token';
const WEB_AUTH_REMEMBER_KEY = 'cfquant.web_auth_remember';
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
const CREDIT_ORDER_ACTIONS = [
  { value: 'credit_buy', label: '担保品买入', side: 'buy' },
  { value: 'credit_sell', label: '担保品卖出', side: 'sell' },
  { value: 'credit_fin_buy', label: '融资买入', side: 'buy' },
  { value: 'credit_slo_sell', label: '融券卖出', side: 'sell' },
  { value: 'credit_buy_secu_repay', label: '买券还券', side: 'buy' },
  { value: 'credit_direct_secu_repay', label: '直接还券', side: 'buy' },
  { value: 'credit_sell_secu_repay', label: '卖券还款', side: 'sell' },
  { value: 'credit_direct_cash_repay', label: '直接还款', side: 'sell' },
  { value: 'credit_fin_buy_special', label: '专项融资买入', side: 'buy' },
  { value: 'credit_slo_sell_special', label: '专项融券卖出', side: 'sell' },
  { value: 'credit_buy_secu_repay_special', label: '专项买券还券', side: 'buy' },
  { value: 'credit_direct_secu_repay_special', label: '专项直接还券', side: 'buy' },
  { value: 'credit_sell_secu_repay_special', label: '专项卖券还款', side: 'sell' },
  { value: 'credit_direct_cash_repay_special', label: '专项直接还款', side: 'sell' },
];
const CREDIT_ORDER_ACTION_MAP = new Map(CREDIT_ORDER_ACTIONS.map((item) => [item.value, item]));
const FIX_PRICE = 11;
const ACCOUNT_TYPE_OPTIONS = [
  { value: 'STOCK', label: '普通证券账户' },
  { value: 'CREDIT', label: '信用账户' },
  { value: 'FUTURE', label: '期货账户' },
  { value: 'FUTURE_OPTION', label: '期货期权账户' },
  { value: 'STOCK_OPTION', label: '股票期权账户' },
];
const ACCOUNT_TYPE_LABELS = {
  STOCK: '普通',
  CREDIT: '信用',
  FUTURE: '期货',
  FUTURE_OPTION: '期货期权',
  STOCK_OPTION: '股票期权',
};
const PRICE_TYPE_OPTIONS = [
  { value: '11', label: 'FIX_PRICE 11' },
  { value: '5', label: 'LATEST_PRICE 5' },
  { value: '12', label: 'PRTP_MARKET 12' },
  { value: '18', label: 'MARKET_BEST 18' },
  { value: '19', label: 'MARKET_CANCEL 19' },
  { value: '20', label: 'MARKET_CANCEL_ALL 20' },
  { value: '21', label: 'MARKET_CANCEL_1 21' },
  { value: '22', label: 'MARKET_CANCEL_5 22' },
  { value: '23', label: 'MARKET_CONVERT_1 23' },
  { value: '24', label: 'MARKET_CONVERT_5 24' },
  { value: '42', label: 'MARKET_SH_CONVERT_5_CANCEL 42' },
  { value: '43', label: 'MARKET_SH_CONVERT_5_LIMIT 43' },
  { value: '44', label: 'MARKET_PEER_PRICE_FIRST 44' },
  { value: '45', label: 'MARKET_MINE_PRICE_FIRST 45' },
  { value: '46', label: 'MARKET_SZ_INSTBUSI_RESTCANCEL 46' },
  { value: '47', label: 'MARKET_SZ_CONVERT_5_CANCEL 47' },
  { value: '48', label: 'MARKET_SZ_FULL_OR_CANCEL 48' },
];
const FUTURE_ORDER_ACTIONS = [
  { value: 'future_open_long', label: '期货开多', side: 'buy', order_type: 0 },
  { value: 'future_close_long_history', label: '期货平昨多', side: 'sell', order_type: 1 },
  { value: 'future_close_long_today', label: '期货平今多', side: 'sell', order_type: 2 },
  { value: 'future_open_short', label: '期货开空', side: 'sell', order_type: 3 },
  { value: 'future_close_short_history', label: '期货平昨空', side: 'buy', order_type: 4 },
  { value: 'future_close_short_today', label: '期货平今空', side: 'buy', order_type: 5 },
  { value: 'future_close_long_today_first', label: '期货平多今优先', side: 'sell', order_type: 6 },
  { value: 'future_close_long_history_first', label: '期货平多昨优先', side: 'sell', order_type: 7 },
  { value: 'future_close_short_today_first', label: '期货平空今优先', side: 'buy', order_type: 8 },
  { value: 'future_close_short_history_first', label: '期货平空昨优先', side: 'buy', order_type: 9 },
  { value: 'future_close_long_today_history_then_open_short', label: '平多今昨后开空', side: 'sell', order_type: 10 },
  { value: 'future_close_long_history_today_then_open_short', label: '平多昨今后开空', side: 'sell', order_type: 11 },
  { value: 'future_close_short_today_history_then_open_long', label: '平空今昨后开多', side: 'buy', order_type: 12 },
  { value: 'future_close_short_history_today_then_open_long', label: '平空昨今后开多', side: 'buy', order_type: 13 },
  { value: 'future_open', label: '期货开仓', side: '', order_type: 14 },
  { value: 'future_close', label: '期货平仓', side: '', order_type: 15 },
  { value: 'future_arbitrage_open', label: '期货套利开仓', side: '', order_type: 16 },
  { value: 'future_arbitrage_close_history_first', label: '套利平仓昨优先', side: '', order_type: 17 },
  { value: 'future_arbitrage_close_today_first', label: '套利平仓今优先', side: '', order_type: 18 },
  { value: 'future_renew_long_close_history_first', label: '多头换月平昨优先', side: 'sell', order_type: 19 },
  { value: 'future_renew_long_close_today_first', label: '多头换月平今优先', side: 'sell', order_type: 20 },
  { value: 'future_renew_short_close_history_first', label: '空头换月平昨优先', side: 'buy', order_type: 21 },
  { value: 'future_renew_short_close_today_first', label: '空头换月平今优先', side: 'buy', order_type: 22 },
];
const FUTURE_OPTION_ORDER_ACTIONS = [
  ...FUTURE_ORDER_ACTIONS,
  { value: 'future_option_exercise', label: '期货期权行权', side: '', order_type: 100 },
];
const STOCK_OPTION_ORDER_ACTIONS = [
  { value: 'stock_option_buy_open', label: '股票期权买入开仓', side: 'buy', order_type: 48, qmt_order_type: 50 },
  { value: 'stock_option_sell_close', label: '股票期权卖出平仓', side: 'sell', order_type: 49, qmt_order_type: 51 },
  { value: 'stock_option_sell_open', label: '股票期权卖出开仓', side: 'sell', order_type: 50, qmt_order_type: 52 },
  { value: 'stock_option_buy_close', label: '股票期权买入平仓', side: 'buy', order_type: 51, qmt_order_type: 53 },
  { value: 'stock_option_covered_open', label: '股票期权备兑开仓', side: 'sell', order_type: 52, qmt_order_type: 54 },
  { value: 'stock_option_covered_close', label: '股票期权备兑平仓', side: 'buy', order_type: 53, qmt_order_type: 55 },
  { value: 'stock_option_call_exercise', label: '股票期权认购行权', side: '', order_type: 54, qmt_order_type: 56 },
  { value: 'stock_option_put_exercise', label: '股票期权认沽行权', side: '', order_type: 55, qmt_order_type: 57 },
  { value: 'stock_option_secu_lock', label: '股票期权证券锁定', side: '', order_type: 56, qmt_order_type: 58 },
  { value: 'stock_option_secu_unlock', label: '股票期权证券解锁', side: '', order_type: 57, qmt_order_type: 59 },
];
const DERIVATIVE_ORDER_ACTIONS_BY_ACCOUNT_TYPE = {
  FUTURE: FUTURE_ORDER_ACTIONS,
  FUTURE_OPTION: FUTURE_OPTION_ORDER_ACTIONS,
  STOCK_OPTION: STOCK_OPTION_ORDER_ACTIONS,
};
const DERIVATIVE_ACCOUNT_TYPES = new Set(Object.keys(DERIVATIVE_ORDER_ACTIONS_BY_ACCOUNT_TYPE));
const DERIVATIVE_ORDER_ACTION_MAPS = Object.fromEntries(
  Object.entries(DERIVATIVE_ORDER_ACTIONS_BY_ACCOUNT_TYPE).map(([accountType, actions]) => [
    accountType,
    new Map(actions.map((item) => [item.value, item])),
  ])
);
const DEFAULT_UPDATE_REPO_URL = 'https://github.com/95ge/cfquant.git';
const DEFAULT_OFFICIAL_SITE_URL = 'https://cfquant.org';
const API_DEBUG_TIMEOUT_MS = 18000;
const API_DEBUG_QMT_TIMEOUT_SECONDS = 12;
let mermaidRendererReady = false;
let forceCloseVersionPopover = () => {};

function normalizeTransportMode(mode) {
  const value = String(mode || 'ctypes').trim().toLowerCase();
  if (['lite', 'extreme', 'extreme_lite', 'lite_extreme', 'lite_extreme_pipe', 'extreme_pipe', 'cfquant_lite', 'ultimate'].includes(value)) return 'lite';
  if (['lttx', 'socket', 'normal', 'default'].includes(value)) return 'lttx';
  return 'ctypes';
}

function isCtypesTransportMode(mode) {
  return normalizeTransportMode(mode) !== 'lttx';
}

function transportModeLabel(mode, short = false) {
  const value = normalizeTransportMode(mode);
  if (value === 'lite') return short ? '极致' : '极致模式';
  if (value === 'lttx') return short ? '高级' : '高级模式';
  return short ? '通用' : '通用模式';
}

function transportModeDetailLabel(mode) {
  const value = normalizeTransportMode(mode);
  if (value === 'lite') return '纯 ctypes 自包含版';
  if (value === 'lttx') return 'LTtx 普通/极速双桥';
  return 'ctypes 通用版';
}

function transportModeRequestScope(mode) {
  const value = normalizeTransportMode(mode);
  if (value === 'lite') return '纯 ctypes 单文件双通道';
  if (value === 'lttx') return '普通桥 + 交易桥';
  return '单文件双通道';
}

function qmtEntryScriptForMode(mode) {
  const value = normalizeTransportMode(mode);
  if (value === 'lite') return 'CFQUANT_LITE.py';
  if (value === 'lttx') return 'CFQUANT.py';
  return 'CFQUANT_CTYPE_ALL_LOWLAT.py';
}

const QMT_MARKET_SCRIPT_DIR = '\u540c\u8d26\u53f7\u72ec\u7acb\u5e02\u573a';
const QMT_MARKET_LABELS = { SH: '\u4e0a\u6d77', SZ: '\u6df1\u5733' };

function qmtMarketEntryScriptForMode(mode, market) {
  const suffix = String(market || '').toUpperCase() === 'SH' ? 'SH' : 'SZ';
  const value = normalizeTransportMode(mode);
  const base = value === 'lite'
    ? 'CFQUANT_LITE'
    : (value === 'lttx' ? 'CFQUANT_TRADE_LOWLAT' : 'CFQUANT_CTYPE_ALL_LOWLAT');
  return `${QMT_MARKET_SCRIPT_DIR}/${base}_${suffix}.py`;
}

function qmtScriptTargetPath(qmtDir, scriptPath) {
  const pythonDir = qmtPythonDirPath(qmtDir);
  const fileName = String(scriptPath || '').split('/').pop();
  return pythonDir ? joinWinPath(pythonDir, fileName) : '\u8bf7\u5148\u586b\u5199 QMT \u76ee\u5f55';
}

function qmtScriptPlan(values = {}) {
  const mode = normalizeTransportMode(values.mode);
  const marketRoutingEnabled = values.marketRoutingEnabled !== undefined
    ? !!values.marketRoutingEnabled
    : !!values.market_routing_enabled;
  const routes = normalizeMarketRoutes({
    ...values,
    market_bridges: values.marketBridges || values.market_bridges || {},
  });
  const scripts = [];
  const addScript = (role, path, qmtDir, note = '') => scripts.push({
    role,
    path,
    name: path.split('/').pop(),
    target: qmtScriptTargetPath(qmtDir, path),
    note,
  });

  if (marketRoutingEnabled) {
    ['SH', 'SZ'].forEach((market) => {
      const marketLabel = QMT_MARKET_LABELS[market];
      const role = mode === 'lttx' ? `${marketLabel}\u6781\u901f\u4ea4\u6613\u7aef` : `${marketLabel}\u4ea4\u6613\u7aef`;
      const note = `${marketLabel} QMT \u53ea\u52a0\u8f7d ${qmtMarketEntryScriptForMode(mode, market).split('/').pop()}\uff0c\u4e0d\u8981\u52a0\u8f7d\u666e\u901a\u5165\u53e3\u3002`;
      addScript(role, qmtMarketEntryScriptForMode(mode, market), routes[market].qmt_dir, note);
    });
  } else if (mode === 'lttx') {
    addScript('\u666e\u901a\u7aef QMT', 'CFQUANT.py', values.qmt_dir, '\u666e\u901a\u7aef\u8d1f\u8d23\u8c03\u7528\u548c\u666e\u901a\u901a\u9053\u3002');
    addScript('\u6781\u901f\u4ea4\u6613\u7aef QMT', 'CFQUANT_TRADE_LOWLAT.py', values.qmt_trade_dir, '\u8bf7\u653e\u5728\u4e0e\u666e\u901a\u7aef\u4e0d\u540c\u7684 QMT \u4e2d\u52a0\u8f7d\u3002');
  } else {
    const entryScript = qmtEntryScriptForMode(mode);
    addScript(`${transportModeLabel(mode)} QMT`, entryScript, values.qmt_dir, '\u4fdd\u5b58\u540e\u5c06\u8fd9\u4e00\u4efd\u811a\u672c\u52a0\u8f7d\u5230 QMT\u3002');
  }

  let notice = '';
  if (marketRoutingEnabled) {
    notice = '\u5df2\u6309\u4e24\u5730\u591a\u4e2d\u5fc3\uff0f\u540c\u8d26\u53f7\u72ec\u7acb\u5e02\u573a\u8def\u7531\u5c55\u793a\u3002\u4e0a\u6d77 QMT \u8fd0\u884c _SH \u811a\u672c\uff0c\u6df1\u5733 QMT \u8fd0\u884c _SZ \u811a\u672c\uff1b\u4e0d\u8981\u628a\u666e\u901a\u5165\u53e3\u590d\u5236\u5230\u5e02\u573a\u4ea4\u6613\u7aef\u3002';
  } else if (mode === 'lttx') {
    notice = '\u9ad8\u7ea7\u6a21\u5f0f\u9700\u8981\u5728\u4e24\u4e2a\u4e0d\u540c\u7684 QMT \u4e2d\u5206\u522b\u52a0\u8f7d\u666e\u901a\u7aef\u548c\u6781\u901f\u4ea4\u6613\u7aef\u811a\u672c\u3002';
  } else {
    notice = `\u5f53\u524d\u4e3a${transportModeLabel(mode)}\uff0c\u53ea\u9700\u52a0\u8f7d\u6e05\u5355\u4e2d\u8fd9\u4e00\u4efd\u811a\u672c\u3002`;
  }
  return { mode, marketRoutingEnabled, scripts, notice };
}

function bindingScriptValuesFromSelectedAccount() {
  const info = selectedAccountInfo();
  const config = info.config || {};
  return {
    account_id: info.accountId || '',
    account_type: info.accountType || 'STOCK',
    qmt_dir: config.qmt_dir || '',
    qmt_trade_dir: accountConfigQmtTradeDir(config),
    mode: config.mode || 'ctypes',
    marketRoutingEnabled: isMarketRoutingEnabled(config),
    marketBridges: normalizeMarketRoutes(config),
  };
}

function renderQmtScriptCards(list, plan, sourceByPath = {}, includeSource = true) {
  if (!list) return;
  list.innerHTML = plan.scripts.map((script) => {
    const source = sourceByPath[script.path];
    const code = includeSource
      ? (source ? `<pre class="binding-script-code"><code>${esc(source.source || '')}</code></pre>` : '<div class="binding-script-loading">\u6b63\u5728\u8bfb\u53d6\u811a\u672c\u6e90\u7801\u2026</div>')
      : '';
    return `<article class="binding-script-card">
      <div class="binding-script-card-head">
        <div class="binding-script-card-title"><strong>${esc(script.role)}</strong><code>${esc(script.name)}</code></div>
        <button type="button" data-qmt-script-copy="${esc(script.path)}">\u590d\u5236\u8fd9\u4efd\u4ee3\u7801</button>
      </div>
      <div class="binding-script-meta"><span>\u653e\u5165</span><code>${esc(script.target)}</code></div>
      <div class="binding-script-note">${esc(script.note)}</div>
      ${code}
    </article>`;
  }).join('');
}

async function loadQmtScriptSources(paths) {
  const wanted = Array.from(new Set(paths.filter(Boolean)));
  const missing = wanted.filter((path) => !state.qmtScriptSourceCache[path]);
  if (missing.length) {
    const requestKey = missing.slice().sort().join('\n');
    let request = state.qmtScriptSourcePromises[requestKey];
    if (!request) {
      const params = new URLSearchParams();
      missing.forEach((path) => params.append('name', path));
      request = api(`/api/qmt-scripts/source?${params.toString()}`)
        .then((data) => {
          (data.scripts || []).forEach((script) => {
            state.qmtScriptSourceCache[script.path] = script;
          });
        })
        .finally(() => {
          delete state.qmtScriptSourcePromises[requestKey];
        });
      state.qmtScriptSourcePromises[requestKey] = request;
    }
    await request;
  }
  return Object.fromEntries(wanted.map((path) => [path, state.qmtScriptSourceCache[path]]));
}

async function renderQmtScriptPanel({ listId, guideId, summaryId, values, includeSource = true } = {}) {
  const list = $(listId);
  if (!list) return;
  const plan = qmtScriptPlan(values || {});
  const token = ++state.qmtScriptRenderToken;
  const guide = $(guideId);
  const summary = $(summaryId);
  if (guide) guide.textContent = plan.notice;
  if (summary) summary.textContent = `${plan.scripts.length} \u4efd QMT \u811a\u672c\uff0c\u6309\u5f53\u524d\u6a21\u5f0f\u751f\u6210`;
  renderQmtScriptCards(list, plan, {}, includeSource);
  if (!includeSource) return;
  try {
    const sourceByPath = await loadQmtScriptSources(plan.scripts.map((script) => script.path));
    if (token !== state.qmtScriptRenderToken) return;
    renderQmtScriptCards(list, plan, sourceByPath, true);
  } catch (error) {
    if (token !== state.qmtScriptRenderToken) return;
    list.innerHTML = `<div class="binding-script-error">\u811a\u672c\u6e90\u7801\u8bfb\u53d6\u5931\u8d25\uff1a${esc(error.message)}</div>`;
  }
}

async function copyQmtScript(path, statusId = 'bindingQmtScriptSummary') {
  try {
    const sourceByPath = await loadQmtScriptSources([path]);
    const source = sourceByPath[path];
    if (!source) throw new Error('\u672a\u627e\u5230\u811a\u672c\u6e90\u7801');
    await navigator.clipboard.writeText(source.source || '');
    const status = $(statusId);
    if (status) status.textContent = `${source.name} \u5df2\u590d\u5236\uff0c\u53ef\u76f4\u63a5\u7c98\u8d34\u5230 QMT\u3002`;
  } catch (error) {
    setBindingNotice(`QMT \u811a\u672c\u590d\u5236\u5931\u8d25\uff1a${error.message}`, 'error', { autoHide: false });
  }
}

async function copyQmtScriptPlan(values, statusId = 'bindingQmtScriptSummary') {
  const plan = qmtScriptPlan(values || {});
  try {
    const sourceByPath = await loadQmtScriptSources(plan.scripts.map((script) => script.path));
    const text = plan.scripts.map((script) => {
      const source = sourceByPath[script.path];
      return `# ${script.role} / ${script.name}\n${source ? source.source : ''}`;
    }).join('\n\n# ==============================\n\n');
    await navigator.clipboard.writeText(text);
    const status = $(statusId);
    if (status) status.textContent = `已复制 ${plan.scripts.length} 份 QMT 代码（按文件分隔）。`;
  } catch (error) {
    setBindingNotice(`QMT 脚本复制失败：${error.message}`, 'error', { autoHide: false });
  }
}

function renderBindingQmtScriptPanel() {
  const values = bindingScriptValuesFromSelectedAccount();
  const list = $('bindingQmtScriptList');
  if (!values.account_id && !values.qmt_dir && !values.qmt_trade_dir) {
    const guide = $('bindingQmtScriptGuide');
    const summary = $('bindingQmtScriptSummary');
    if (guide) guide.textContent = '\u4fdd\u5b58\u4e00\u4e2a\u8d26\u53f7\u7ed1\u5b9a\u540e\uff0c\u8fd9\u91cc\u4f1a\u6309\u5f53\u524d\u6a21\u5f0f\u5c55\u793a\u5e94\u8be5\u590d\u5236\u5230 QMT \u7684\u5165\u53e3\u811a\u672c\u3002';
    if (summary) summary.textContent = '\u6682\u65e0\u5df2\u4fdd\u5b58\u7684\u8d26\u53f7\u914d\u7f6e';
    if (list) list.innerHTML = '';
    return;
  }
  return renderQmtScriptPanel({
    listId: 'bindingQmtScriptList',
    guideId: 'bindingQmtScriptGuide',
    summaryId: 'bindingQmtScriptSummary',
    values,
    includeSource: true,
  });
}

function wireQmtScriptCopyList(listId, statusId) {
  const list = $(listId);
  if (!list || list.dataset.qmtScriptCopyWired === '1') return;
  list.dataset.qmtScriptCopyWired = '1';
  list.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-qmt-script-copy]');
    if (!button) return;
    copyQmtScript(button.dataset.qmtScriptCopy || '', statusId);
  });
}

function bindingQmtDeployRoleLabel(item = {}) {
  const market = String(item.market || '').toUpperCase();
  if (market === 'SH') return '\u4e0a\u6d77 QMT \u6838\u5fc3\u5305';
  if (market === 'SZ') return '\u6df1\u5733 QMT \u6838\u5fc3\u5305';
  if (item.qmt_role === 'trade') return '\u6781\u901f\u4ea4\u6613\u7aef QMT \u6838\u5fc3\u5305';
  return '\u666e\u901a\u7aef QMT \u6838\u5fc3\u5305';
}

function bindingQmtDeployStatusHtml(deploy) {
  const results = deploy && Array.isArray(deploy.results) ? deploy.results : [];
  const summary = deploy && deploy.summary ? deploy.summary : null;
  if (!results.length) {
    return `<div class="binding-qmt-status-row is-warn"><strong>QMT \u6838\u5fc3\u5305</strong><span>\u672a\u6267\u884c\u81ea\u52a8\u590d\u5236\uff0c\u8bf7\u6838\u5bf9 QMT \u76ee\u5f55\u540e\u624b\u5de5\u590d\u5236\u3002</span></div>`;
  }
  const rows = results.map((item) => {
    const status = item.error ? 'error' : (item.updated ? 'success' : (item.warning ? 'warn' : 'info'));
    const label = item.error
      ? '\u590d\u5236\u5931\u8d25'
      : (item.updated ? '\u5df2\u590d\u5236' : (item.skipped ? '\u65e0\u9700\u590d\u5236' : '\u5df2\u5904\u7406'));
    const detail = item.error || item.warning || item.message || label;
    const target = item.python_dir || item.configured_dir || item.qmt_dir || '';
    return `<div class="binding-qmt-status-row is-${status}">
      <strong>${esc(bindingQmtDeployRoleLabel(item))}</strong>
      <span><b>${esc(label)}</b>${target ? ` <code>${esc(target)}</code>` : ''}${detail && detail !== label ? ` <small>${esc(detail)}</small>` : ''}</span>
    </div>`;
  }).join('');
  const summaryRow = summary && summary.message
    ? `<div class="binding-qmt-status-summary">${esc(summary.message)}</div>`
    : '';
  return `${summaryRow}${rows}`;
}

function bindingQmtGuideInstruction(values = {}) {
  const plan = qmtScriptPlan(values);
  if (plan.marketRoutingEnabled) {
    return '\u8fd9\u662f\u4e24\u5730\u591a\u4e2d\u5fc3\uff0f\u540c\u8d26\u53f7\u72ec\u7acb\u5e02\u573a\u914d\u7f6e\u3002\u8bf7\u5728\u5bf9\u5e94 QMT \u4e2d\u5206\u522b\u65b0\u5efa\u7b56\u7565\uff1a\u4e0a\u6d77\u7aef\u53ea\u8fd0\u884c _SH\uff0c\u6df1\u5733\u7aef\u53ea\u8fd0\u884c _SZ\u3002';
  }
  if (plan.mode === 'lttx') {
    return '\u9ad8\u7ea7\u6a21\u5f0f\u9700\u8981\u914d\u7f6e\u4e24\u4e2a QMT\uff1a\u666e\u901a\u7aef\u548c\u6781\u901f\u4ea4\u6613\u7aef\u5404\u65b0\u5efa\u4e00\u4e2a\u7b56\u7565\uff0c\u5206\u522b\u7c98\u8d34\u5bf9\u5e94\u4ee3\u7801\u540e\u4fdd\u5b58\u5e76\u8fd0\u884c\u3002';
  }
  return '\u8bf7\u5728\u5bf9\u5e94 QMT \u4e2d\u65b0\u5efa\u7b56\u7565\uff0c\u5c06\u4e0b\u65b9\u4ee3\u7801\u5168\u90e8\u7c98\u8d34\u8fdb\u53bb\uff0c\u7136\u540e\u4fdd\u5b58\u5e76\u8fd0\u884c\u3002';
}

function closeBindingQmtGuide() {
  const overlay = $('bindingQmtGuideOverlay');
  if (!overlay) return;
  const guideContext = state.bindingQmtGuideContext;
  const guideValues = state.bindingQmtGuideValues;
  const continueBindingFlow = guideContext === 'onboarding' || guideContext === 'binding';
  state.bindingQmtGuideContext = '';
  overlay.classList.add('hidden');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('binding-dialog-open');
  if (continueBindingFlow) {
    window.setTimeout(() => beginOnboardingRestartFlow(guideValues, {
      context: guideContext,
      returnTarget: 'qmt-guide',
    }), 0);
  }
}

function showBindingQmtGuide(values, deploy, options = {}) {
  const overlay = $('bindingQmtGuideOverlay');
  if (!overlay) return;
  state.bindingQmtGuideValues = values || {};
  if (deploy !== undefined) state.bindingQmtGuideDeploy = deploy;
  state.bindingQmtGuideContext = options.context || '';
  const title = $('bindingQmtGuideTitle');
  const subtitle = $('bindingQmtGuideSubtitle');
  const instruction = $('bindingQmtGuideInstruction');
  const status = $('bindingQmtGuideStatus');
  const backButton = $('backBindingQmtGuideBtn');
  const bottomButton = $('closeBindingQmtGuideBottomBtn');
  const plan = qmtScriptPlan(values || {});
  if (title) title.textContent = '\u7ed1\u5b9a\u5df2\u4fdd\u5b58\uff0c\u5b8c\u6210 QMT \u7b56\u7565\u52a0\u8f7d';
  if (subtitle) subtitle.textContent = values && values.account_id ? `${values.account_id} / ${transportModeLabel(values.mode)}` : '\u8bf7\u5b8c\u6210 QMT \u7b56\u7565\u52a0\u8f7d';
  if (instruction) instruction.textContent = bindingQmtGuideInstruction(values || {});
  if (status) status.innerHTML = bindingQmtDeployStatusHtml(
    deploy !== undefined ? deploy : state.bindingQmtGuideDeploy
  );
  if (backButton) {
    backButton.textContent = state.bindingQmtGuideContext === 'onboarding'
      ? '返回账号配置'
      : '返回绑定配置';
  }
  if (bottomButton) {
    bottomButton.textContent = state.bindingQmtGuideContext === 'onboarding'
      ? '我已复制代码，下一步'
      : '我已完成，关闭指引';
  }
  overlay.classList.remove('hidden');
  overlay.setAttribute('aria-hidden', 'false');
  document.body.classList.add('binding-dialog-open');
  renderQmtScriptPanel({
    listId: 'bindingQmtGuideScriptList',
    guideId: 'bindingQmtGuideModeNotice',
    summaryId: 'bindingQmtGuideSummary',
    values,
    includeSource: true,
  });
  const modeNotice = $('bindingQmtGuideModeNotice');
  if (modeNotice) modeNotice.textContent = `${plan.notice} \u8bf7\u6309\u6bcf\u4e00\u4efd\u811a\u672c\u53f3\u4fa7\u6309\u94ae\u590d\u5236\u3002`;
  window.setTimeout(() => {
    const close = $('closeBindingQmtGuideBtn');
    if (close) close.focus();
  }, 0);
}
const DEFAULT_UPDATE_REF = 'main';
const QUOTE_RENDER_INTERVAL_MS = 500;
const QUOTE_RESPONSE_LOG_LIMIT = 20;
const QUOTE_EVENT_PROCESS_LIMIT = 160;
const LOG_ENTRY_LIMIT = 180;
const LOG_REPEAT_WINDOW_MS = 5000;
const STATUS_REFRESH_INTERVAL_MS = 30000;
const ONBOARDING_BRIDGE_POLL_MS = 3000;
const CALLBACK_POLL_INTERVAL_MS = 3000;
const ORDER_SNAPSHOT_LIMIT = 500;
const ORDER_HIGHLIGHT_MS = 6500;
const DOWNLOAD_EVENT_PREFIX = 'xtdata:download';
const DOWNLOAD_EVENT_LIMIT = 80;

const API_GROUPS = [
  { id: 'data', title: '数据' },
  { id: 'trade', title: '交易' },
  { id: 'system', title: '系统' },
  { id: 'transport', title: '通信' },
];

const API_ENDPOINTS = [
  {
    id: 'quote_subscribe_whole',
    group: 'data',
    title: '订阅全推行情',
    method: 'POST',
    path: '/api/quotes/whole/subscribe',
    desc: '通过当前模式订阅全推行情。同一时间只允许一个全推订阅，成功后可通过 WebSocket 实时接收行情事件；通用模式由 ctypes 单桥统一转发。',
    defaults: { channel: 'normal', markets: 'SH,SZ', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'whole_quote_channel', 'markets', 'timeout'],
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
    desc: '查询指定证券的实时全推快照。通用模式走 ctypes 单桥， 高级模式按所选通道请求。',
    defaults: { channel: 'trade', code_list: '000001.SZ,600000.SH', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'code_list', 'timeout'],
  },
  {
    id: 'market_data',
    group: 'data',
    title: '行情数据',
    method: 'POST',
    path: '/api/data/market',
    desc: '查询行情数据，字段、证券列表、周期和区间可配置。通用模式走 ctypes 单桥，高级模式支持极速优先并回退普通 QMT。',
    defaults: { channel: 'trade', field_list: 'open,high,low,close,volume', stock_list: '000001.SZ', period: '1d', count: '-1', dividend_type: 'none', fill_data: '1', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'field_list', 'stock_list', 'period', 'start_time', 'end_time', 'count', 'dividend_type', 'fill_data', 'timeout'],
  },
  {
    id: 'market_data_ex',
    group: 'data',
    title: '扩展行情数据',
    method: 'POST',
    path: '/api/data/market-ex',
    desc: '调用 QMT get_market_data_ex，适合读取本地缓存行情数据。通用模式走 ctypes 单桥，高级模式支持极速优先并回退普通 QMT。',
    defaults: { channel: 'trade', field_list: 'open,high,low,close,volume', stock_list: '000001.SZ', period: '1d', count: '-1', dividend_type: 'none', fill_data: '1', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'field_list', 'stock_list', 'period', 'start_time', 'end_time', 'count', 'dividend_type', 'fill_data', 'timeout'],
  },
  {
    id: 'quote_subscribe_single',
    group: 'data',
    title: '订阅单股行情',
    method: 'POST',
    path: '/api/quotes/subscribe',
    desc: '通过当前模式订阅单只证券行情，订阅事件同样通过 WebSocket 行情接收。',
    defaults: { channel: 'normal', stock_code: '000001.SZ', period: '1d', count: '0', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'stock_code', 'period', 'start_time', 'end_time', 'count', 'dividend_type', 'timeout'],
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
    desc: '查询证券合约详情。通用模式走 ctypes 单桥，高级模式支持极速优先并回退普通 QMT。',
    defaults: { channel: 'trade', stock_code: '000001.SZ', iscomplete: '0', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'stock_code', 'iscomplete', 'timeout'],
  },
  {
    id: 'sector_stocks',
    group: 'data',
    title: '板块成分',
    method: 'POST',
    path: '/api/data/sector',
    desc: '查询指定板块的证券列表。通用模式走 ctypes 单桥，高级模式支持极速优先并回退普通 QMT。',
    defaults: { channel: 'trade', sector_name: '沪深A股', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'sector_name', 'timeout'],
  },
  {
    id: 'history_download',
    group: 'data',
    title: '下载历史数据',
    method: 'POST',
    path: '/api/data/history/download',
    desc: '触发 QMT 下载指定证券历史行情数据。下载请求固定通过普通 QMT 发送，便于接收下载进度回调。',
    defaults: { channel: 'normal', stock_code: '000001.SZ', period: '1d', incrementally: '', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'stock_code', 'period', 'start_time', 'end_time', 'incrementally', 'timeout'],
  },
  {
    id: 'financial_data',
    group: 'data',
    title: '财务数据',
    method: 'POST',
    path: '/api/data/financial',
    desc: '读取财务数据，支持填充数据和原始数据两种模式。通用模式走 ctypes 单桥，高级模式支持极速优先并回退普通 QMT。',
    defaults: { channel: 'trade', stock_code: '000001.SZ', table: 'ASHAREBALANCESHEET', fields: 'fix_assets', mode: 'filled', report_type: 'announce_time', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'stock_code', 'financial_table', 'financial_fields', 'financial_mode', 'start_time', 'end_time', 'report_type', 'timeout'],
  },
  {
    id: 'financial_download',
    group: 'data',
    title: '校验财务本地数据',
    method: 'POST',
    path: '/api/data/financial/download',
    desc: '按大 QMT 官方能力读取并校验本地财务数据。财务数据需要先在 QMT 客户端“数据管理 - 财务数据下载”中下载，脚本侧不提供真正下载函数。',
    defaults: { channel: 'normal', stock_code: '000001.SZ', table: 'ASHAREBALANCESHEET', fields: 'fix_assets', mode: 'raw', report_type: 'report_time', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'stock_code', 'financial_table', 'financial_fields', 'financial_mode', 'start_time', 'end_time', 'report_type', 'timeout'],
  },
  {
    id: 'data_export',
    group: 'data',
    title: '导出交易数据',
    method: 'POST',
    path: '/api/trade/export-data',
    desc: '调用 QMT xttrader.export_data 导出指定账号的数据。导出耗时较长时会显示任务进度，避免误判为失败。',
    defaults: { channel: 'trade', result_path: 'D:\\cfquant_export', data_type: 'order', user_param_json: '{}', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'trade_channel', 'account_id', 'account_type', 'export_result_path', 'export_data_type', 'start_time', 'end_time', 'export_user_param_json', 'timeout'],
  },
  {
    id: 'quote_unsubscribe',
    group: 'data',
    title: '取消行情订阅',
    method: 'POST',
    path: '/api/quotes/unsubscribe',
    desc: '取消指定的行情订阅。',
    defaults: { channel: 'normal', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['bridge_id', 'channel', 'quote_subscribe_id', 'timeout'],
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
    desc: '实时查询指定账号的资金信息。接口测试默认直连交易端，不使用账户缓存。',
    defaults: { sections: 'asset', force: '1', subscribe: '0', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'timeout'],
  },
  {
    id: 'positions',
    group: 'trade',
    title: '查持仓',
    method: 'GET',
    path: '/api/account',
    desc: '实时查询指定账号的持仓列表。接口测试默认直连交易端，不使用账户缓存。',
    defaults: { sections: 'positions', force: '1', subscribe: '0', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'timeout'],
  },
  {
    id: 'orders',
    group: 'trade',
    title: '查委托',
    method: 'GET',
    path: '/api/account',
    desc: '实时查询指定账号的委托列表。接口测试默认直连交易端，不使用账户缓存。',
    defaults: { sections: 'orders', force: '1', subscribe: '0', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'timeout'],
  },
  {
    id: 'trades',
    group: 'trade',
    title: '查成交',
    method: 'GET',
    path: '/api/account',
    desc: '实时查询指定账号的成交列表。接口测试默认直连交易端，不使用账户缓存。',
    defaults: { sections: 'trades', force: '1', subscribe: '0', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'timeout'],
  },
  {
    id: 'credit_query',
    group: 'trade',
    title: '信用查询',
    method: 'POST',
    path: '/api/credit/query',
    desc: '查询信用账户专用信息，包括融资融券明细、可融券标的、担保品和合约负债。需要选择或填写信用账户。',
    defaults: { account_type: 'CREDIT', credit_query_action: 'detail', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'credit_query_action', 'timeout'],
  },
  {
    id: 'credit_probe',
    group: 'trade',
    title: '信用能力探测',
    method: 'POST',
    path: '/api/credit/probe',
    desc: '只读探测信用账户在当前 QMT 下可用的资产、持仓、委托、成交和信用专项查询能力。',
    defaults: { account_type: 'CREDIT', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'timeout'],
  },
  {
    id: 'credit_actions',
    group: 'trade',
    title: '信用动作',
    method: 'GET',
    path: '/api/credit/actions',
    desc: '查看内置信用账户查询动作和信用委托业务动作清单。',
    fields: [],
  },
  {
    id: 'order_actions',
    group: 'trade',
    title: '委托动作',
    method: 'GET',
    path: '/api/order/actions',
    desc: '查看信用、期货、期货期权和股票期权委托动作清单。',
    fields: [],
  },
  {
    id: 'xttrader_compat',
    group: 'system',
    title: 'xtquant 平替说明',
    method: 'DOC',
    path: 'cfquant/docs/xttrader平替追踪.md / cfquant/docs/xtdata平替追踪.md',
    desc: '说明 cfquant 对 xtquant.xttrader 和 xtquant.xtdata 的平替进度、已实装接口和当前限制。',
    fields: [],
  },
  {
    id: 'transport_mode',
    group: 'transport',
    title: '通信模式',
    method: 'GET',
    path: '/api/transport',
    desc: '查看或切换当前网页通信模式：通用模式使用 ctypes 单桥，极致模式使用纯 ctypes 自包含脚本，高级模式使用两个 QMT 终端的普通桥和极速交易桥。',
    fields: [],
  },
  {
    id: 'pipe_hub',
    group: 'transport',
    title: 'PipeHub 状态',
    method: 'GET',
    path: '/api/pipe-hub',
    desc: '查看 ctypes 通用版 PipeHub 是否在线，以及当前 pipe 状态文件内容。',
    fields: [],
  },
  {
    id: 'status',
    group: 'system',
    title: '通道状态',
    method: 'GET',
    path: '/api/status',
    desc: '查看高级模式所需的普通 QMT 和极速交易端状态；通用模式仍可通过 PipeHub 状态确认单桥是否接入。',
    fields: ['bridge_id'],
  },
  {
    id: 'callbacks',
    group: 'trade',
    title: '查回调',
    method: 'GET',
    path: '/api/callbacks',
    desc: '按账号拉取委托/成交回调事件，内部通道由账号配置自动决定。',
    defaults: { since: '0', limit: '50' },
    fields: ['account_id', 'account_type', 'since', 'limit'],
  },
  {
    id: 'ws_callbacks',
    group: 'trade',
    title: 'WebSocket 回调',
    method: 'WS',
    path: '/ws/callbacks',
    desc: '按账号实时接收委托/成交等回调事件。API Key 会通过 apikey 查询参数传入。',
    fields: ['account_id', 'account_type'],
  },
  {
    id: 'order',
    group: 'trade',
    title: '提交委托',
    method: 'POST',
    path: '/api/order',
    desc: '按账号配置对应的内部通道提交委托。信用账户可指定信用业务动作，期货和期权账户可指定 MiniQMT 业务动作，后端要求确认文本完全匹配。',
    defaults: { timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'side', 'credit_order_action', 'order_action', 'stock_code', 'price_type', 'price', 'volume', 'confirm_text', 'timeout'],
  },
  {
    id: 'credit_order',
    group: 'trade',
    title: '信用委托',
    method: 'POST',
    path: '/api/credit/order',
    desc: '提交信用账户专用业务委托，包括担保品买卖、融资买入、融券卖出和还款还券。',
    defaults: { account_type: 'CREDIT', credit_order_action: 'credit_buy', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'credit_order_action', 'stock_code', 'price_type', 'price', 'volume', 'confirm_text', 'timeout'],
  },
  {
    id: 'future_order',
    group: 'trade',
    title: '期货委托',
    method: 'POST',
    path: '/api/future/order',
    desc: '提交期货账户业务委托，order_action 使用 MiniQMT FUTURE_* 语义。',
    defaults: { account_type: 'FUTURE', order_action: 'future_open_long', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'order_action', 'stock_code', 'price_type', 'price', 'volume', 'confirm_text', 'timeout'],
  },
  {
    id: 'future_option_order',
    group: 'trade',
    title: '期货期权委托',
    method: 'POST',
    path: '/api/future-option/order',
    desc: '提交期货期权账户业务委托，兼容 MiniQMT 期货方向动作并支持期权行权。',
    defaults: { account_type: 'FUTURE_OPTION', order_action: 'future_open_long', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'order_action', 'stock_code', 'price_type', 'price', 'volume', 'confirm_text', 'timeout'],
  },
  {
    id: 'stock_option_order',
    group: 'trade',
    title: '股票期权委托',
    method: 'POST',
    path: '/api/stock-option/order',
    desc: '提交股票期权账户业务委托，输入保持 MiniQMT STOCK_OPTION_* order_type 语义，桥接层转换为大 QMT passorder opType。',
    defaults: { account_type: 'STOCK_OPTION', order_action: 'stock_option_buy_open', timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'order_action', 'stock_code', 'price_type', 'price', 'volume', 'confirm_text', 'timeout'],
  },
  {
    id: 'batch_order',
    group: 'trade',
    title: '批量委托',
    method: 'POST',
    path: '/api/orders/batch',
    desc: '按账号配置对应的内部通道批量提交委托。orders 使用 JSON 数组，后端内部逐笔调用 QMT 下单。',
    defaults: {
      orders_json: '[{"stock_code":"000001.SZ","price":10.0,"volume":100},{"stock_code":"600000.SH","price":8.5,"volume":200}]',
      confirm_text: 'BATCH 2',
      timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS),
    },
    fields: ['account_id', 'account_type', 'credit_order_action', 'order_action', 'price_type', 'batch_orders_json', 'batch_confirm_text', 'timeout'],
  },
  {
    id: 'credit_batch_order',
    group: 'trade',
    title: '批量信用委托',
    method: 'POST',
    path: '/api/credit/orders/batch',
    desc: '批量提交信用账户业务委托。每条委托可单独携带 credit_action，未携带时使用默认信用业务。',
    defaults: {
      account_type: 'CREDIT',
      credit_order_action: 'credit_buy',
      orders_json: '[{"credit_action":"credit_fin_buy","stock_code":"000001.SZ","price":10.0,"volume":100}]',
      confirm_text: 'BATCH 1',
      timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS),
    },
    fields: ['account_id', 'account_type', 'credit_order_action', 'price_type', 'batch_orders_json', 'batch_confirm_text', 'timeout'],
  },
  {
    id: 'future_batch_order',
    group: 'trade',
    title: '批量期货委托',
    method: 'POST',
    path: '/api/future/orders/batch',
    desc: '批量提交期货账户业务委托。每条委托可单独携带 order_action。',
    defaults: {
      account_type: 'FUTURE',
      order_action: 'future_open_long',
      orders_json: '[{"order_action":"future_open_long","stock_code":"IF2601.IF","price":4200.0,"volume":1}]',
      confirm_text: 'BATCH 1',
      timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS),
    },
    fields: ['account_id', 'account_type', 'order_action', 'price_type', 'batch_orders_json', 'batch_confirm_text', 'timeout'],
  },
  {
    id: 'future_option_batch_order',
    group: 'trade',
    title: '批量期货期权委托',
    method: 'POST',
    path: '/api/future-option/orders/batch',
    desc: '批量提交期货期权账户业务委托。每条委托可单独携带 order_action。',
    defaults: {
      account_type: 'FUTURE_OPTION',
      order_action: 'future_open_long',
      orders_json: '[{"order_action":"future_open_long","stock_code":"IO2601-C-4200.IF","price":100.0,"volume":1}]',
      confirm_text: 'BATCH 1',
      timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS),
    },
    fields: ['account_id', 'account_type', 'order_action', 'price_type', 'batch_orders_json', 'batch_confirm_text', 'timeout'],
  },
  {
    id: 'stock_option_batch_order',
    group: 'trade',
    title: '批量股票期权委托',
    method: 'POST',
    path: '/api/stock-option/orders/batch',
    desc: '批量提交股票期权账户业务委托。每条委托可单独携带 order_action。',
    defaults: {
      account_type: 'STOCK_OPTION',
      order_action: 'stock_option_buy_open',
      orders_json: '[{"order_action":"stock_option_buy_open","stock_code":"10000001.SH","price":0.100,"volume":1}]',
      confirm_text: 'BATCH 1',
      timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS),
    },
    fields: ['account_id', 'account_type', 'order_action', 'price_type', 'batch_orders_json', 'batch_confirm_text', 'timeout'],
  },
  {
    id: 'cancel',
    group: 'trade',
    title: '撤单',
    method: 'POST',
    path: '/api/cancel',
    desc: '按账号配置对应的内部通道撤销指定委托。后端要求确认文本完全匹配。',
    defaults: { timeout: String(API_DEBUG_QMT_TIMEOUT_SECONDS) },
    fields: ['account_id', 'account_type', 'order_id', 'cancel_confirm_text', 'timeout'],
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
  bridge_id: { label: '内部通道', type: 'bridge' },
  account_id: { label: '账号', type: 'text', placeholder: '请输入资金账号' },
  account_type: { label: '账户类型', type: 'account_type' },
  credit_query_action: { label: '信用查询', type: 'credit_query_action', param: 'action' },
  credit_order_action: { label: '信用业务', type: 'credit_order_action', param: 'credit_action' },
  order_action: { label: '交易业务', type: 'order_action' },
  channel: { label: '查询通道', type: 'channel' },
  timeout: { label: '超时秒数', type: 'number', placeholder: '12' },
  whole_quote_channel: { label: '订阅通道', type: 'fixed_channel', param: 'channel' },
  trade_channel: { label: '交易通道', type: 'trade_channel', param: 'channel' },
  side: { label: '方向', type: 'side' },
  stock_code: { label: '证券代码', type: 'text', placeholder: '000001.SZ' },
  price_type: { label: '报价类型', type: 'price_type' },
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
  export_result_path: { label: '导出目录', type: 'text', placeholder: 'D:\\cfquant_export', param: 'result_path', wide: true },
  export_data_type: { label: '导出数据类型', type: 'text', placeholder: 'order / deal / position / account', param: 'data_type' },
  export_user_param_json: { label: '导出参数 JSON', type: 'textarea', placeholder: '{"remark":"cfquant"}', param: 'user_param_json', wide: true },
  transport_mode: { label: '通信模式', type: 'transport_mode' },
};

const API_PARAM_DOCS = {
  bridge_id: '内部通道 ID。账号接口通常不用填，会按账号配置自动决定。',
  account_id: '资金账号。',
  account_type: '账户类型。普通证券账户填 STOCK，信用账户填 CREDIT，期货填 FUTURE，期货期权填 FUTURE_OPTION，股票期权填 STOCK_OPTION。',
  action: '信用查询动作，detail/subjects/slo_code/assure/compacts。',
  credit_action: '信用委托动作，例如 credit_buy、credit_fin_buy、credit_slo_sell、credit_direct_cash_repay。',
  order_action: '期货、期货期权或股票期权委托动作，例如 future_open_long、future_open_short、stock_option_buy_open。',
  channel: '高级模式下 normal 为普通 QMT，trade 为极速交易端；通用模式由后端按操作类型自动路由到 ctypes 单桥。',
  timeout: '本次调试等待 QMT 响应的秒数。网络或桥接异常时建议保持 12 秒，避免页面长时间请求中。',
  sections: '账号数据段，asset/positions/orders/trades。',
  force: '是否强制刷新缓存，1 表示立即查询。',
  subscribe: '是否订阅账户缓存。接口测试中的账户查询默认为 0，表示直接查询 QMT/交易端。',
  since: '回调起始序号。',
  limit: '返回条数上限。',
  side: '普通账户委托方向，buy 或 sell；信用账户未指定信用业务时用于默认担保品买卖。',
  stock_code: '证券代码，格式如 000001.SZ。',
  price_type: '报价类型，保持 MiniQMT order_stock 的 price_type 数值，默认 FIX_PRICE=11。',
  price: '委托价格。price_type=11 固定价时必须大于 0，市价或最新价类报价可为 0。',
  volume: '委托数量。',
  confirm_text: '确认文本；普通下单格式为 BUY/SELL code volume @ price，信用和派生品下单格式为 ACTION code volume @ price，撤单格式为 CANCEL order_id。',
  orders_json: '批量委托数组，每项包含 stock_code、price、volume；信用账户可选 credit_action，期货和期权账户可选 order_action。',
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
  result_path: '导出结果目录，必须是 QMT 所在机器可访问的本地路径。',
  data_type: '导出数据类型，按 QMT export_data 支持值填写，例如 order、deal、position、account 等。',
  user_param: '导出附加参数 JSON 对象，不需要时填 {}。',
  user_param_json: '导出附加参数 JSON 对象，不需要时填 {}。页面会在发送前转换为 user_param。',
  transport_mode: '通信模式，ctypes 表示通用模式单文件桥，lite 表示极致模式纯 ctypes 自包含脚本，lttx 表示高级模式两个 QMT 终端双桥。',
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
    ['job_id', '下载任务 ID，用于匹配实时进度回调'],
    ['callback_event', '下载进度事件名，当前为 xtdata:download_progress'],
    ['progress_ws_path', '本次任务对应的 WebSocket 进度地址'],
    ['result', '下载任务返回值'],
    ['latency_ms', '请求耗时'],
  ],
  financial_data: [
    ['result', '财务数据结果'],
    ['channel', '实际调用通道'],
    ['fallback', '是否从极速回退到普通 QMT'],
  ],
  financial_download: [
    ['job_id', '校验任务 ID，用于匹配实时进度回调'],
    ['download_supported', '固定为 false，表示 QMT 官方脚本侧没有财务下载函数'],
    ['manual_download_required', '是否需要先在 QMT 客户端手工下载财务数据'],
    ['manual_download_hint', '手工下载提示'],
    ['query_action', '实际调用的本地财务读取接口'],
    ['query_summary', '本地财务数据返回摘要'],
    ['callback_event', '进度事件名，当前为 xtdata:download_progress'],
    ['progress_ws_path', '本次任务对应的 WebSocket 进度地址'],
    ['channel', '实际调用通道'],
    ['fallback', '是否从极速回退到普通 QMT'],
  ],
  data_export: [
    ['job_id', '导出任务 ID，用于页面进度展示'],
    ['result_path', 'QMT 侧导出的目标目录'],
    ['data_type', '导出的数据类型'],
    ['result', '底层 export_data 返回值'],
    ['latency_ms', '请求耗时'],
    ['channel', '实际调用通道'],
    ['fallback', '是否从高级模式回退'],
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
    ['cache.response_latency_ms', '本次 Web 缓存响应耗时（毫秒）'],
    ['asset.refresh_latency_ms', '后台刷新资金数据耗时（毫秒）'],
    ['balance', '总资产'],
    ['available', '可用资金'],
    ['market_value', '总市值'],
    ['position_profit', '持仓盈亏'],
  ],
  positions: [
    ['cache.response_latency_ms', '本次 Web 缓存响应耗时（毫秒）'],
    ['positions.refresh_latency_ms', '后台刷新持仓数据耗时（毫秒）'],
    ['stock_code', '证券代码'],
    ['instrument_name', '证券名称'],
    ['volume', '持仓数量'],
    ['can_use_volume', '可用数量'],
    ['market_value', '市值'],
  ],
  orders: [
    ['cache.response_latency_ms', '本次 Web 缓存响应耗时（毫秒）'],
    ['orders.refresh_latency_ms', '后台刷新委托数据耗时（毫秒）'],
    ['order_time', '委托时间'],
    ['order_source', '委托来源：cfquant 或 其他'],
    ['stock_code', '证券代码'],
    ['instrument_name', '证券名称'],
    ['order_volume', '委托数量'],
    ['traded_volume', '成交数量'],
    ['order_status', '委托状态'],
    ['m_strOrderSysID', '委托编号'],
  ],
  trades: [
    ['cache.response_latency_ms', '本次 Web 缓存响应耗时（毫秒）'],
    ['trades.refresh_latency_ms', '后台刷新成交数据耗时（毫秒）'],
    ['trade_time', '成交时间'],
    ['stock_code', '证券代码'],
    ['instrument_name', '证券名称'],
    ['price', '成交价格'],
    ['volume', '成交数量'],
    ['trade_amount', '成交金额'],
  ],
  credit_query: [
    ['account_type', '固定为 CREDIT'],
    ['query', '信用查询动作'],
    ['result', 'QMT 返回的信用账户查询结果'],
    ['latency_ms', '请求耗时'],
  ],
  credit_probe: [
    ['account_type', '固定为 CREDIT'],
    ['capabilities', '各信用查询能力是否可用'],
    ['checks', '每个探测项的耗时、通道和错误信息'],
    ['supported_count', '可用能力数量'],
  ],
  credit_actions: [
    ['orders[]', '信用委托动作清单，包含 action、label、side 和 order_type'],
    ['queries[]', '信用查询动作清单'],
  ],
  order_actions: [
    ['credit_orders[]', '信用委托动作清单'],
    ['future_orders[]', '期货委托动作清单，order_type 与 MiniQMT FUTURE_* 常量一致'],
    ['future_option_orders[]', '期货期权委托动作清单'],
    ['stock_option_orders[]', '股票期权委托动作清单，包含 MiniQMT order_type 和大 QMT qmt_order_type'],
  ],
  status: [
    ['normal.online', '普通 QMT 是否在线'],
    ['trade.online', '极速交易端是否在线'],
    ['checked_at_text', '检测时间'],
  ],
  transport_mode: [
    ['transport.mode', '当前通信模式，ctypes、lite 或 lttx'],
    ['transport.label', '展示名称'],
    ['client.mode', '请求客户端模式'],
    ['client.request_channel', '默认请求频道'],
  ],
  pipe_hub: [
    ['running', 'PipeHub 是否运行'],
    ['pipe_name', '命名管道名称'],
    ['status.pipe_name', '状态文件中的管道名'],
    ['status.qmt_connected', '是否已连接 QMT 桥'],
    ['status.pending_count', '待处理请求数'],
  ],
  callbacks: [
    ['events[].event', '回调类型'],
    ['events[].account_id', '账号'],
    ['events[].data', '回调数据'],
  ],
  ws_callbacks: [
    ['type', '消息类型。hello 表示连接成功，callback 表示实时回调。'],
    ['channel', 'hello 消息中的通道名称，固定为 callbacks。'],
    ['bridge_id', '当前连接过滤的内部通道。按账号连接时由后端自动解析。'],
    ['account_id', '当前连接过滤的账号。为空表示不过滤账号。'],
    ['event.seq', '服务端回调序号，用于排序和断点拉取。'],
    ['event.event', '回调事件名，例如 trader:on_stock_order。'],
    ['event.account_id', '回调所属账号。'],
    ['event.bridge_id', '回调所属内部通道。'],
    ['event.received_at', '服务端收到回调的时间戳，单位秒。'],
    ['event.data', 'QMT 回调对象转换后的字段数据。'],
  ],
  order: [
    ['order_id', '委托编号'],
    ['order_type', '最终传入 QMT passorder 的 opType'],
    ['credit_action', '信用账户业务动作；普通账户为空'],
    ['order_action', '期货或期权账户业务动作；普通和信用账户为空'],
    ['order_remark', '委托备注'],
    ['latency_ms', '请求耗时'],
  ],
  credit_order: [
    ['order_id', '委托编号'],
    ['order_type', '最终传入 QMT passorder 的信用 opType'],
    ['credit_action', '信用账户业务动作'],
    ['credit_action_label', '信用业务中文名称'],
    ['latency_ms', '请求耗时'],
  ],
  batch_order: [
    ['result.total', '请求委托总数'],
    ['result.submitted', '提交成功数量'],
    ['result.failed', '失败数量'],
    ['result.results[]', '每笔委托结果，包含 index、ok、stock_code、result/error'],
    ['latency_ms', '请求耗时'],
  ],
  credit_batch_order: [
    ['result.total', '请求委托总数'],
    ['result.submitted', '提交成功数量'],
    ['result.failed', '失败数量'],
    ['result.results[]', '每笔信用委托结果，包含 action、order_type 和 result/error'],
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

['future_order', 'future_option_order', 'stock_option_order'].forEach((id) => {
  API_RETURN_DOCS[id] = API_RETURN_DOCS.order;
});
['future_batch_order', 'future_option_batch_order', 'stock_option_batch_order'].forEach((id) => {
  API_RETURN_DOCS[id] = API_RETURN_DOCS.batch_order;
});

const WS_CALLBACK_EVENT_DOCS = [
  ['trader:on_stock_asset', '资金变化回调'],
  ['trader:on_stock_position', '持仓变化回调'],
  ['trader:on_stock_order', '委托状态回调'],
  ['trader:on_stock_trade', '成交回调'],
  ['trader:on_order_error', '下单错误回调'],
  ['trader:on_cancel_error', '撤单错误回调'],
  ['trader:on_order_stock_async_response', '异步下单响应'],
  ['trader:on_cancel_order_stock_async_response', '异步撤单响应'],
    ['xtdata:download_progress', '历史下载进度或财务本地校验进度回调，按 meta.job_id 匹配任务'],
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
  ['meta.job_id', '下载任务 ID，仅下载进度事件使用。'],
  ['meta.stage', '下载阶段，例如 submitted、progress、request_done、error。'],
    ['meta.download_kind', '任务类型，例如 history、financial_check。'],
];

const WS_CALLBACK_EXAMPLE = {
  type: 'callback',
  event: {
    seq: 12,
    event: 'trader:on_stock_order',
    account_id: 'YOUR_ACCOUNT_ID',
    bridge_id: 'default',
    received_at: 1783440000.123,
    data: {
      stock_code: '000001.SZ',
      m_strAccountID: 'YOUR_ACCOUNT_ID',
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
  const number = typeof value === 'string'
    ? Number.parseFloat(value.replace(/,/g, '').replace(/%$/, ''))
    : Number(value);
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
  const url = new URL(`${base.protocol}//${base.host}${path}`);
  const token = state.webAuthToken || '';
  if (webAuthEnabled() && token) {
    url.searchParams.set('web_token', token);
  } else if (!webAuthEnabled() && state.apiKey) {
    url.searchParams.set('apikey', state.apiKey);
  }
  return url.toString();
}

function log(message, data) {
  const box = $('logBox');
  if (!box) return;
  let suffix = '';
  if (data !== undefined) {
    try {
      suffix = ` ${JSON.stringify(data)}`;
    } catch (error) {
      suffix = ` ${String(data)}`;
    }
    if (suffix.length > 1200) {
      suffix = `${suffix.slice(0, 1200)}...`;
    }
  }
  const key = `${message}${suffix}`;
  const now = Date.now();
  if (
    state.lastLogKey === key
    && state.lastLogNode
    && state.lastLogNode.parentNode === box
    && now - state.lastLogAt <= LOG_REPEAT_WINDOW_MS
  ) {
    state.lastLogRepeat += 1;
    state.lastLogAt = now;
    state.lastLogNode.textContent = `[${nowText()}] ${message}${suffix}（重复 ${state.lastLogRepeat} 次）`;
    return;
  }
  const line = document.createElement('div');
  line.className = 'log-entry';
  line.textContent = `[${nowText()}] ${message}${suffix}`;
  box.prepend(line);
  state.lastLogKey = key;
  state.lastLogAt = now;
  state.lastLogNode = line;
  state.lastLogRepeat = 1;
  while (box.children.length > LOG_ENTRY_LIMIT) {
    box.removeChild(box.lastElementChild);
  }
}

function setBindingNotice(message = '', level = 'info', options = {}) {
  const nodes = [$('bindingPageNotice'), $('bindingSaveStatus')].filter(Boolean);
  if (!nodes.length) return;
  if (state.bindingNoticeTimer) {
    window.clearTimeout(state.bindingNoticeTimer);
    state.bindingNoticeTimer = null;
  }
  const safeLevel = ['info', 'success', 'warn', 'error', 'busy'].includes(level) ? level : 'info';
  nodes.forEach((node) => {
    node.textContent = message || '';
    node.classList.toggle('hidden', !message);
    ['is-info', 'is-success', 'is-warn', 'is-error', 'is-busy'].forEach((name) => node.classList.remove(name));
    if (message) node.classList.add(`is-${safeLevel}`);
  });
  if (message && options.autoHide !== false) {
    state.bindingNoticeTimer = window.setTimeout(() => setBindingNotice(''), options.duration || 6500);
  }
}

function setBindingSaveBusy(isBusy, text = '保存中...') {
  const form = $('bindingForm');
  const submitBtn = form ? form.querySelector('button[type="submit"]') : null;
  if (submitBtn) {
    if (!submitBtn.dataset.defaultText) submitBtn.dataset.defaultText = submitBtn.textContent || '保存绑定';
    submitBtn.disabled = !!isBusy;
    submitBtn.textContent = isBusy ? text : submitBtn.dataset.defaultText;
  }
  const savePairBtn = $('savePairBtn');
  if (savePairBtn) {
    if (!savePairBtn.dataset.defaultText) savePairBtn.dataset.defaultText = savePairBtn.textContent || '保存当前账号';
    savePairBtn.disabled = !!isBusy;
    savePairBtn.textContent = isBusy ? text : savePairBtn.dataset.defaultText;
  }
}

function bindingMarketRouteHasMissingDir(enabled, routes = {}) {
  if (!enabled) return false;
  return ['SH', 'SZ'].some((market) => !String(routes[market] && routes[market].qmt_dir || '').trim());
}

function syncAdvancedQmtDirField(inputId, mode) {
  const input = $(inputId);
  if (!input) return;
  const field = input.closest('.field');
  const advanced = normalizeTransportMode(mode) === 'lttx';
  if (field) field.classList.toggle('hidden', !advanced);
  input.required = advanced;
}

function qmtDirsAreSame(first, second) {
  const normalize = (value) => String(value || '').trim().replace(/[\\/]+$/, '').toLowerCase();
  return normalize(first) && normalize(first) === normalize(second);
}

function qmtCoreDeploySummaryText(deploy) {
  const summary = deploy && deploy.summary ? deploy.summary : null;
  if (!summary) return '';
  return String(summary.message || '').trim();
}

function qmtCoreDeployHasIssues(deploy) {
  const summary = deploy && deploy.summary ? deploy.summary : null;
  return !!(summary && (summary.error_count || summary.warning_count));
}

function qmtCoreDeployLogPayload(deploy) {
  if (!deploy || typeof deploy !== 'object') return null;
  return {
    summary: deploy.summary || null,
    results: (deploy.results || []).map((item) => ({
      qmt_role: item.qmt_role || '',
      market: item.market || '',
      bridge_id: item.bridge_id || '',
      qmt_dir: item.configured_dir || item.qmt_dir || '',
      python_dir: item.python_dir || '',
      current_core: item.current_core || '',
      updated: !!item.updated,
      skipped: !!item.skipped,
      error: item.error || '',
      warning: item.warning || '',
    })),
  };
}

function bindingSaveSummary({
  accountId,
  accountType,
  displayName,
  mode,
  qmtDir,
  qmtTradeDir,
  dataProvider,
  marketRoutingEnabled,
  marketBridges,
  legacyFallback,
  qmtCoreDeploy,
} = {}) {
  const name = displayName ? `${displayName} / ${accountId}` : accountId;
  const parts = [
    `绑定已保存：${name || '未命名账号'}`,
    accountTypeLabel(accountType || 'STOCK'),
    `${transportModeLabel(mode || 'ctypes', true)}模式`,
  ];
  if (marketRoutingEnabled) {
    const missing = ['SH', 'SZ'].filter((market) => !String(marketBridges && marketBridges[market] && marketBridges[market].qmt_dir || '').trim());
    parts.push(missing.length ? `市场路由已启用，${missing.join('/')}目录未填写` : '市场路由已启用，SH/SZ目录已记录');
  } else {
    parts.push(qmtDir ? 'QMT目录已记录' : 'QMT目录未填写');
  }
  if (normalizeTransportMode(mode) === 'lttx') {
    parts.push(qmtDir && qmtTradeDir ? '高级模式两个 QMT 目录已记录' : '高级模式需要两个 QMT 目录');
  }
  if (dataProvider) parts.push('共享行情源');
  if (legacyFallback) parts.push('后端使用兼容保存，重启 Web 后可保存完整运行配置');
  const deployMessage = qmtCoreDeploySummaryText(qmtCoreDeploy);
  if (deployMessage) parts.push(deployMessage);
  return parts.join('，');
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json' };
  Object.assign(headers, authHeaders());
  const response = await fetch(path, {
    headers,
    ...options,
  });
  const payload = await response.json();
  if (response.status === 401 && webAuthEnabled()) {
    clearWebAuthToken();
    showWebAuthOverlay('请先登录');
  }
  if (!payload.ok) {
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload.data;
}

function versionCompareText(value, remoteError = '') {
  if (value === 'same') return '已是最新';
  if (value === 'newer' || value === 'different') return '发现新版本';
  if (value === 'older') return '本地版本较新';
  if (remoteError) return '远端检查失败';
  return '未检查远端';
}

function projectVersionClass(info) {
  if (state.versionCheckInFlight) return 'status-checking';
  const remote = info && info.remote ? info.remote : {};
  if (remote.error) return 'status-error';
  const comparison = info && info.comparison ? info.comparison : 'unknown';
  if (comparison === 'same') return 'status-same';
  if (comparison === 'newer') return 'status-newer';
  if (comparison === 'different') return 'status-different';
  if (comparison === 'older') return 'status-older';
  return 'status-unknown';
}

function renderVersionLog(changelog, title) {
  const info = changelog || {};
  const items = Array.isArray(info.items) ? info.items : [];
  const version = info.version ? ` / ${info.version}` : '';
  if (!items.length) {
    return `<section class="version-log"><span>${esc(title)}${esc(version)}</span><ul><li>暂无更新日志</li></ul></section>`;
  }
  return `<section class="version-log"><span>${esc(title)}${esc(version)}</span><ul>${items.map((item) => `<li>${esc(item)}</li>`).join('')}</ul></section>`;
}

function qmtRuntimeLabel(report = {}) {
  if (report.reported && report.version) return report.version;
  if (report.has_report) return '未运行';
  return '未上报';
}

function qmtKnownVersion(info = {}, report = {}) {
  return info.latest_qmt_core_version
    || info.qmt_builtin_version
    || report.saved_core_version
    || report.saved_version
    || (report.has_report ? report.version : '')
    || '';
}

function qmtKnownDetail(report = {}) {
  const reportedAt = report.reported_at_text || report.saved_reported_at_text || '--';
  if (report.reported && report.version) {
    return `当前在线，上报时间 ${reportedAt}。`;
  }
  if (report.has_report && report.version) {
    return `最近一次上报 ${reportedAt}，当前上报已过期，仅用于版本识别和对比。`;
  }
  return '尚未保存 QMT 内置核心版本；运行 QMT 桥接脚本后会自动记录。';
}

function qmtRuntimeDetail(report = {}) {
  const reportedAt = report.reported_at_text || report.saved_reported_at_text || '--';
  if (report.reported && report.version) {
    const source = report.source || 'QMT 运行时';
    const modeName = report.runtime_mode || report.mode || '';
    const mode = modeName ? ` / ${transportModeLabel(modeName) || modeName}` : '';
    const entry = report.entry_version
      ? ` / 入口 ${report.entry_script || 'QMT 脚本'} ${report.entry_version}`
      : (report.entry_script ? ` / 入口 ${report.entry_script}` : '');
    const checked = reportedAt !== '--' ? ` / ${reportedAt}` : '';
    return `来源：${source}${mode}${entry}${checked}`;
  }
  if (report.has_report && report.version) {
    return `最近已知版本 ${report.version}，上报时间 ${reportedAt}；当前未收到新的在线上报。`;
  }
  return report.message || '未收到 QMT 运行时版本上报，请先运行对应 QMT 桥接脚本后再查看。';
}

function renderProjectVersion(info) {
  state.versionInfo = info || state.versionInfo || null;
  const data = state.versionInfo || {};
  const qmtRuntime = data.qmt_runtime || data.qmt_saved_report || {};
  const qmtReported = Boolean(qmtRuntime.reported && qmtRuntime.version);
  const qmtSavedVersion = qmtKnownVersion(data, qmtRuntime);
  const qmtVersion = qmtSavedVersion || qmtRuntimeLabel(qmtRuntime);
  const webCoreVersion = data.core_version || data.current_version || (data.local && data.local.version) || '--';
  const serverFrontendVersion = data.frontend_version || data.web_version || '--';
  const browserFrontendVersion = FRONTEND_VERSION;
  const widget = $('versionWidget');
  const badge = $('versionBadge');
  const label = $('versionBadgeLabel');
  const badgeState = $('versionBadgeState');
  const badgeEntry = $('versionBadgeEntry');
  const badgeMeta = $('versionBadgeMeta');
  const checkState = $('versionCheckState');
  const body = $('versionPopoverBody');
  const alert = $('versionAlert');
  const runtimeEntryScript = qmtRuntime.entry_script || qmtRuntime.qmt_runtime_entry_script || '';
  const runtimeEntryVersion = qmtRuntime.entry_version || qmtRuntime.runtime_entry_version || qmtRuntime.qmt_runtime_entry_version || '';
  const runtimeMode = qmtRuntime.runtime_mode || qmtRuntime.mode || qmtRuntime.transport || '';
  const runtimeReportedAt = qmtRuntime.reported_at_text || qmtRuntime.saved_reported_at_text || '';
  const badgeStatusText = state.versionCheckInFlight
    ? '正在检查版本'
    : qmtReported
      ? 'QMT 正在运行'
      : (qmtSavedVersion ? '最近上报已过期' : '等待 QMT 上报');
  const badgeEntryText = runtimeEntryScript
    ? `入口 ${runtimeEntryScript}${runtimeEntryVersion ? ` / ${runtimeEntryVersion}` : ''}`
    : (qmtSavedVersion ? '未记录入口脚本' : '入口脚本待上报');
  const badgeMetaText = state.versionCheckInFlight
    ? '正在同步本地、QMT 和远端版本'
    : qmtReported
      ? (runtimeReportedAt ? `最近上报 ${runtimeReportedAt}` : '已收到运行时版本上报')
      : (qmtSavedVersion
        ? (runtimeReportedAt ? `最后上报 ${runtimeReportedAt}` : '保存的运行版本')
        : '运行 QMT 桥接脚本后会自动同步');
  if (label) label.textContent = qmtSavedVersion || '--';
  if (badgeState) badgeState.textContent = badgeStatusText;
  if (badgeEntry) badgeEntry.textContent = badgeEntryText;
  if (badgeMeta) {
    badgeMeta.textContent = badgeMetaText;
  }
  if (badge) {
    badge.setAttribute(
      'aria-label',
      `QMT 核心版本 ${qmtSavedVersion || '未上报'}，${badgeStatusText}。${badgeEntryText}`,
    );
  }
  const qmtComparison = data.qmt_version_comparison || data.qmt_runtime_comparison || data.qmt_saved_comparison || data.comparison;
  const qmtClassData = { ...data, comparison: qmtComparison, update_available: data.qmt_update_available };
  if (widget) {
    widget.classList.remove(
      'status-same',
      'status-newer',
      'status-different',
      'status-older',
      'status-error',
      'status-checking',
      'status-unknown',
    );
    widget.classList.add(state.versionCheckInFlight ? 'status-checking' : (qmtSavedVersion ? projectVersionClass(qmtClassData) : 'status-unknown'));
  }
  const remote = data.remote || {};
  const remoteVersionText = remote.web_version
    ? `${remote.version || remote.core_version || '--'} / ${remote.web_version}`
    : (remote.version || remote.core_version || '--');
  const compareText = versionCompareText(qmtComparison, remote.error);
  if (checkState) {
    checkState.textContent = state.versionCheckInFlight
      ? '正在检查'
      : (qmtSavedVersion ? compareText : '等待 QMT 上报');
  }
  if (alert) {
    const showAlert = !!(remote.error && !state.versionCheckInFlight);
    alert.classList.toggle('hidden', !showAlert);
    alert.textContent = showAlert ? `版本探测失败：${remote.error}` : '版本探测失败，不影响交易和行情功能';
    alert.title = showAlert ? remote.error : '';
  }
  if (!body) return;
  const local = data.local || {};
  const importedCoreVersion = data.imported_core_version || local.imported_version || '';
  const coreImportStale = Boolean(data.core_version_import_stale || local.import_stale);
  const runtimeDetail = qmtRuntimeDetail(qmtRuntime);
  const webDetail = coreImportStale
    ? `磁盘 ${webCoreVersion} / Web 进程 ${importedCoreVersion || '--'}，重启 Web 后端后生效`
    : `Web 后端 ${webCoreVersion} / 前端 ${browserFrontendVersion}`;
  const remoteDetail = remote.error
    ? `检查失败：${remote.error}`
    : remote.version
      ? remoteUpdateDetail(remote, data.repo_url || DEFAULT_UPDATE_REPO_URL)
      : '尚未检查官网版本';
  const actionBusy = state.versionCheckInFlight || state.projectUpdateBusy || state.versionUpdateBusy;
  const updateDisabled = state.projectUpdateBusy ? ' disabled' : '';
  const recheckDisabled = state.versionCheckInFlight ? ' disabled' : '';
  const displayCompareText = qmtSavedVersion ? compareText : '无法判断';
  const stateDetail = qmtReported
    ? (data.qmt_update_available ? '官网有不同的 QMT 核心版本，设置页可执行更新。' : '当前 QMT 运行时未发现需要更新。')
    : (qmtSavedVersion ? 'QMT 暂未在线，正在使用最近一次保存的内置版本做对比。' : '当前无法确认 QMT 内部实际加载版本，请先运行 QMT 桥接脚本。');
  const runtimeStateText = state.versionCheckInFlight
    ? '正在检查'
    : qmtReported
      ? '运行中'
      : (qmtSavedVersion ? '上次运行记录' : '未上报');
  const runtimeStateClass = state.versionCheckInFlight
    ? 'is-checking'
    : qmtReported
      ? 'is-ok'
      : (qmtSavedVersion ? 'is-stale' : 'is-wait');
  const runtimeModeText = runtimeMode ? (transportModeLabel(runtimeMode) || runtimeMode) : '--';
  const runtimeEntryText = runtimeEntryScript || '--';
  const runtimeEntryVersionText = runtimeEntryVersion || '--';
  const runtimeReportedText = runtimeReportedAt || '--';
  body.innerHTML = `
    <section class="version-runtime-hero ${runtimeStateClass}">
      <div class="version-runtime-head">
        <div>
          <span class="version-section-label">当前 QMT 运行时</span>
          <strong>${esc(runtimeStateText)}</strong>
        </div>
        <span class="version-runtime-status">${esc(qmtReported ? '在线上报' : (qmtSavedVersion ? '历史记录' : '等待连接'))}</span>
      </div>
      <div class="version-runtime-value">
        <span>核心版本</span>
        <strong>${esc(qmtVersion)}</strong>
      </div>
      <dl class="version-runtime-facts">
        <div><dt>入口脚本</dt><dd>${esc(runtimeEntryText)}</dd></div>
        <div><dt>入口版本</dt><dd>${esc(runtimeEntryVersionText)}</dd></div>
        <div><dt>运行模式</dt><dd>${esc(runtimeModeText)}</dd></div>
        <div><dt>最近上报</dt><dd>${esc(runtimeReportedText)}</dd></div>
      </dl>
      <p>${esc(runtimeDetail)}</p>
    </section>
    <section class="version-compare-section">
      <div class="version-section-head">
        <span>版本对比</span>
        <strong>${esc(state.versionCheckInFlight ? '检查中' : displayCompareText)}</strong>
      </div>
      <div class="version-compare-row">
        <div>
          <span>${esc(remoteUpdateSourceLabel(remote))}</span>
          <strong>${esc(remoteVersionText)}</strong>
        </div>
        <small>${esc(remoteDetail)}</small>
      </div>
      <div class="version-compare-row">
        <div>
          <span>Web 控制台</span>
          <strong>${esc(webCoreVersion)} / ${esc(browserFrontendVersion)}</strong>
        </div>
        <small>${esc(coreImportStale ? webDetail : '后端核心版本 / 浏览器前端版本')}</small>
      </div>
    </section>
    <details class="version-details">
      <summary>详细版本</summary>
      <div class="version-detail-list">
        <div><span>Web 项目</span><strong>${esc(webCoreVersion)}</strong><small>${esc(webDetail)}</small></div>
        <div><span>服务端前端</span><strong>${esc(serverFrontendVersion)}</strong><small>${esc(serverFrontendVersion !== browserFrontendVersion ? '浏览器可能仍在使用旧静态资源，建议强制刷新页面。' : '前后端静态资源版本一致。')}</small></div>
      </div>
      <div class="version-log-wrap">
        ${renderVersionLog(local.changelog, '当前更新日志')}
        ${remote.version || remote.error ? renderVersionLog(remote.changelog, `${remoteUpdateSourceLabel(remote)}更新日志`) : ''}
      </div>
    </details>
    <div class="version-actions">
      <button type="button" data-version-action="recheck"${recheckDisabled}>重新检查</button>
      <button type="button" class="primary" data-version-action="project-update"${updateDisabled}>更新 Web</button>
      <button type="button" data-version-action="qmt-update"${actionBusy ? ' disabled' : ''}>更新 QMT</button>
      <button type="button" data-version-action="open-update">更新设置</button>
    </div>
    <div class="version-action-status">${esc(state.versionCheckInFlight ? '正在连接官网和 QMT 运行时...' : stateDetail)}</div>`;
}

function renderProjectVersionLegacy(info) {
  state.versionInfo = info || state.versionInfo || null;
  const data = state.versionInfo || {};
  const coreVersion = data.core_version || data.current_version || (data.local && data.local.version) || '--';
  const serverFrontendVersion = data.frontend_version || data.web_version || '--';
  const browserFrontendVersion = FRONTEND_VERSION;
  const widget = $('versionWidget');
  const label = $('versionBadgeLabel');
  const checkState = $('versionCheckState');
  const body = $('versionPopoverBody');
  const alert = $('versionAlert');
  if (label) label.textContent = state.versionCheckInFlight ? '检查中...' : `v ${coreVersion}`;
  if (widget) {
    widget.classList.remove(
      'status-same',
      'status-newer',
      'status-different',
      'status-older',
      'status-error',
      'status-checking',
      'status-unknown',
    );
    widget.classList.add(projectVersionClass(data));
  }
  const remote = data.remote || {};
  const remoteVersionText = remote.web_version
    ? `${remote.version || remote.core_version || '--'} / ${remote.web_version}`
    : (remote.version || remote.core_version || '--');
  const stateText = state.versionCheckInFlight ? '正在检查远端' : versionCompareText(data.comparison, remote.error);
  if (checkState) checkState.textContent = stateText;
  if (alert) {
    const showAlert = !!(remote.error && !state.versionCheckInFlight);
    alert.classList.toggle('hidden', !showAlert);
    alert.textContent = showAlert
      ? '版本探测失败：当前网络可能无法访问官网或 GitHub，不影响交易和行情功能'
      : '版本探测失败，不影响交易和行情功能';
    alert.title = showAlert ? `版本探测失败：${remote.error}` : '';
  }
  if (!body) return;
  const local = data.local || {};
  const importedCoreVersion = data.imported_core_version || local.imported_version || '';
  const coreImportStale = Boolean(data.core_version_import_stale || local.import_stale);
  const coreSource = data.core_version_source || local.source || '本地版本文件';
  const readmeNote = coreImportStale
    ? `磁盘版本 ${coreVersion} / Web进程导入 ${importedCoreVersion || '--'}，建议重启 Web 后端完成运行态切换`
    : (local.matches_readme === false
      ? `版本日志版本为 ${local.changelog_version || '--'}，与核心版本不一致`
      : `来源：${coreSource}${local.checked_at_text ? ` / ${local.checked_at_text}` : ''}`);
  const frontendNote = serverFrontendVersion && serverFrontendVersion !== '--' && serverFrontendVersion !== browserFrontendVersion
    ? `浏览器 ${browserFrontendVersion} / 服务端 ${serverFrontendVersion}，建议强制刷新页面`
    : `浏览器前端 ${browserFrontendVersion}${serverFrontendVersion && serverFrontendVersion !== '--' ? ` / 服务端 ${serverFrontendVersion}` : ''}`;
  const remoteNote = remote.error
    ? `检查失败：${remote.error}`
    : remote.version
      ? remoteUpdateDetail(remote, data.repo_url || DEFAULT_UPDATE_REPO_URL)
      : '尚未检查官网版本';
  const actionBusy = state.versionCheckInFlight || state.projectUpdateBusy || state.versionUpdateBusy;
  const updateDisabled = state.projectUpdateBusy ? ' disabled' : '';
  const recheckDisabled = state.versionCheckInFlight ? ' disabled' : '';
  const actionStatus = state.projectUpdateBusy
    ? 'Web 项目正在更新，完成后会自动重启。'
    : state.versionCheckInFlight
      ? '正在连接远端版本源...'
      : (remote.error ? '当前远端不可达，可以稍后重新检查。' : '可在这里直接更新 Web 项目，或进入设置页处理 QMT 核心更新。');
  body.innerHTML = `
    <div class="version-summary">
      <div class="version-info-row">
        <span>核心版本</span>
        <strong>${esc(coreVersion)}</strong>
        <small>${esc(readmeNote)}</small>
      </div>
      <div class="version-info-row">
        <span>前端版本</span>
        <strong>${esc(browserFrontendVersion)}</strong>
        <small>${esc(frontendNote)}</small>
      </div>
      <div class="version-info-row">
        <span>${esc(remoteUpdateSourceLabel(remote))}</span>
        <strong>${esc(remoteVersionText)}</strong>
        <small>${esc(remoteNote)}</small>
      </div>
      <div class="version-info-row">
        <span>版本状态</span>
        <strong>${esc(stateText)}</strong>
        <small>${esc(data.update_available ? '远端有新版本，进入设置页可执行更新。' : '基于官网发布包或版本日志判断。')}</small>
      </div>
    </div>
    <div class="version-log-wrap">
      ${renderVersionLog(local.changelog, '当前更新日志')}
      ${remote.version || remote.error ? renderVersionLog(remote.changelog, `${remoteUpdateSourceLabel(remote)}更新日志`) : ''}
    </div>
    <div class="version-actions">
      <button type="button" data-version-action="recheck"${recheckDisabled}>重新检查</button>
      <button type="button" class="primary" data-version-action="project-update"${updateDisabled}>立即更新 Web</button>
      <button type="button" data-version-action="qmt-update"${actionBusy ? ' disabled' : ''}>更新 QMT 核心</button>
      <button type="button" data-version-action="open-update">更新设置</button>
    </div>
    <div class="version-action-status">${esc(actionStatus)}</div>`;
}

async function refreshProjectVersion(options = {}) {
  if (state.versionCheckInFlight) return state.versionInfo;
  if (state.versionRemoteChecked && !options.force) return state.versionInfo;
  state.versionCheckInFlight = true;
  renderProjectVersion(state.versionInfo);
  try {
    const remote = options.remote !== false;
    const force = !!options.force;
    const data = await api(`/api/version?remote=${remote ? '1' : '0'}&force=${force ? '1' : '0'}&bridge_id=${encodeURIComponent(selectedBridge())}`);
    state.versionRemoteChecked = remote || state.versionRemoteChecked;
    renderProjectVersion(data);
    if (options.log) {
      log('版本状态已刷新', {
        current_version: data.current_version || '',
        remote_version: data.remote && data.remote.version ? data.remote.version : '',
        comparison: data.comparison || '',
      });
    }
    return data;
  } catch (error) {
    const fallback = state.versionInfo || { current_version: '--', comparison: 'unknown', remote: {} };
    fallback.remote = { ...(fallback.remote || {}), error: error.message };
    renderProjectVersion(fallback);
    if (options.log !== false) log('版本状态刷新失败', { error: error.message });
    return fallback;
  } finally {
    state.versionCheckInFlight = false;
    renderProjectVersion(state.versionInfo);
  }
}

function wireVersionBadge() {
  const widget = $('versionWidget');
  const badge = $('versionBadge');
  const popover = $('versionPopover');
  let popoverPinned = false;
  let closePopover = () => {};
  if (widget) {
    let closeTimer = null;
    const check = () => {
      refreshProjectVersion({ remote: true, log: false }).catch((error) => log('版本状态刷新失败', { error: error.message }));
    };
    const openPopover = () => {
      if (closeTimer) {
        window.clearTimeout(closeTimer);
        closeTimer = null;
      }
      widget.classList.add('open');
      if (badge) badge.setAttribute('aria-expanded', 'true');
      check();
    };
    closePopover = (force = false) => {
      if (popoverPinned && !force) return;
      widget.classList.remove('open');
      if (badge) badge.setAttribute('aria-expanded', 'false');
    };
    forceCloseVersionPopover = () => {
      popoverPinned = false;
      closePopover(true);
    };
    const pointerInsideVersionArea = () => (
      widget.matches(':hover')
      || (popover && popover.matches(':hover'))
      || widget.contains(document.activeElement)
      || (popover && popover.contains(document.activeElement))
    );
    const scheduleClose = () => {
      if (closeTimer) window.clearTimeout(closeTimer);
      closeTimer = window.setTimeout(() => {
        if (pointerInsideVersionArea()) return;
        closePopover();
      }, 260);
    };
    widget.addEventListener('mouseenter', openPopover);
    widget.addEventListener('mouseleave', scheduleClose);
    widget.addEventListener('focusin', openPopover);
    widget.addEventListener('focusout', scheduleClose);
    if (popover) {
      popover.addEventListener('mouseenter', openPopover);
      popover.addEventListener('mouseleave', scheduleClose);
      popover.addEventListener('focusin', openPopover);
      popover.addEventListener('focusout', scheduleClose);
    }
    widget.addEventListener('click', (event) => {
      const action = event.target.closest('[data-version-action]');
      if (!action) return;
      event.preventDefault();
      event.stopPropagation();
      if (action.dataset.versionAction === 'recheck') {
        refreshProjectVersion({ remote: true, force: true, log: true }).catch((error) => log('版本状态刷新失败', { error: error.message }));
      } else if (action.dataset.versionAction === 'project-update') {
        runProjectGithubUpdateFromUi({ source: 'version-popover' }).catch((error) => log('Web 项目更新失败', { error: error.message }));
      } else if (action.dataset.versionAction === 'qmt-update') {
        runGithubUpdateFromUi({ source: 'version-popover' }).catch((error) => log('QMT 核心更新失败', { error: error.message }));
      } else if (action.dataset.versionAction === 'open-update') {
        setView('settings');
        setSettingsTab('update');
      }
    });
  }
  if (badge) {
    badge.addEventListener('click', (event) => {
      event.preventDefault();
      if (widget) {
        popoverPinned = !popoverPinned;
        if (popoverPinned) {
          widget.classList.add('open');
          badge.setAttribute('aria-expanded', 'true');
        } else {
          closePopover(true);
        }
      }
      refreshProjectVersion({ remote: true, force: true, log: true }).catch((error) => log('版本状态刷新失败', { error: error.message }));
    });
  }
  document.addEventListener('click', (event) => {
    if (!widget || widget.contains(event.target) || (popover && popover.contains(event.target))) return;
    popoverPinned = false;
    closePopover(true);
  });
}

function webAuthEnabled() {
  if (state.serverAccess && Object.prototype.hasOwnProperty.call(state.serverAccess, 'web_auth_enabled')) {
    return !!state.serverAccess.web_auth_enabled;
  }
  return !!state.webAuthToken;
}

function authHeaders() {
  if (webAuthEnabled()) {
    return state.webAuthToken ? { 'X-CFQUANT-WEB-TOKEN': state.webAuthToken } : {};
  }
  return state.apiKey ? { 'X-API-Key': state.apiKey } : {};
}

function authQueryString() {
  const params = new URLSearchParams();
  if (webAuthEnabled() && state.webAuthToken) {
    params.set('web_token', state.webAuthToken);
  } else if (!webAuthEnabled() && state.apiKey) {
    params.set('apikey', state.apiKey);
  }
  return params.toString();
}

function safeAvatarUrl(url) {
  const value = String(url || '').trim();
  if (value.startsWith('/avatars/') || value.startsWith('/media/avatars/')) return value;
  return DEFAULT_AVATAR_URL;
}

function userProfileLabel(profile = state.userProfile) {
  const row = profile || {};
  return row.display_name || row.display_label || row.username || '管理员';
}

function setUserProfileStatus(message, type = '') {
  const node = $('userProfileStatus');
  if (!node) return;
  node.textContent = message || '';
  node.classList.toggle('is-ok', type === 'ok');
  node.classList.toggle('is-error', type === 'error');
  node.classList.toggle('is-busy', type === 'busy');
}

function renderBuiltinAvatarGrid() {
  const grid = $('builtinAvatarGrid');
  if (!grid) return;
  const avatars = state.builtinAvatars.length ? state.builtinAvatars : DEFAULT_BUILTIN_AVATARS;
  const selected = safeAvatarUrl(state.profileSelectedAvatarUrl || (state.userProfile && state.userProfile.avatar_url));
  grid.innerHTML = avatars.map((avatar) => {
    const url = safeAvatarUrl(avatar.url);
    const active = url === selected;
    return `<button type="button" class="builtin-avatar-option${active ? ' active' : ''}" data-avatar-url="${esc(url)}" aria-pressed="${active ? 'true' : 'false'}" title="${esc(avatar.name || '内置头像')}">
      <img src="${esc(url)}" alt="">
    </button>`;
  }).join('');
}

function renderUserProfile(payload = {}) {
  const profile = payload.profile || payload.user_profile || payload || {};
  const avatars = payload.avatars || payload.builtin_avatars || [];
  if (avatars.length) state.builtinAvatars = avatars;
  else if (!state.builtinAvatars.length) state.builtinAvatars = DEFAULT_BUILTIN_AVATARS;
  if (payload.upload && payload.upload.max_bytes) state.profileUploadLimit = Number(payload.upload.max_bytes) || state.profileUploadLimit;
  const normalized = {
    display_name: String(profile.display_name || '').trim(),
    username: String(profile.username || '').trim(),
    display_label: String(profile.display_label || '').trim(),
    avatar_url: safeAvatarUrl(profile.avatar_url),
    avatar_kind: profile.avatar_kind || (String(profile.avatar_url || '').startsWith('/media/avatars/') ? 'upload' : 'builtin'),
  };
  normalized.display_label = userProfileLabel(normalized);
  state.userProfile = normalized;
  state.profileSelectedAvatarUrl = normalized.avatar_url;

  const topbarImg = $('topbarAvatarImg');
  const previewImg = $('profileAvatarPreview');
  if (topbarImg) topbarImg.src = normalized.avatar_url;
  if (previewImg) previewImg.src = normalized.avatar_url;
  const topbarName = $('topbarProfileName');
  const previewName = $('profilePreviewName');
  if (topbarName) topbarName.textContent = normalized.display_label;
  if (previewName) previewName.textContent = normalized.display_label;
  const displayInput = $('profileDisplayNameInput');
  if (displayInput && document.activeElement !== displayInput) displayInput.value = normalized.display_name;
  const meta = $('profileAvatarMeta');
  if (meta) meta.textContent = normalized.avatar_kind === 'upload' ? '自定义上传头像' : '内置头像';
  renderBuiltinAvatarGrid();
}

function selectUserProfileAvatar(url) {
  state.profileSelectedAvatarUrl = safeAvatarUrl(url);
  if (state.userProfile) {
    state.userProfile.avatar_url = state.profileSelectedAvatarUrl;
    state.userProfile.avatar_kind = state.profileSelectedAvatarUrl.startsWith('/media/avatars/') ? 'upload' : 'builtin';
  }
  const previewImg = $('profileAvatarPreview');
  if (previewImg) previewImg.src = state.profileSelectedAvatarUrl;
  const meta = $('profileAvatarMeta');
  if (meta) meta.textContent = state.profileSelectedAvatarUrl.startsWith('/media/avatars/') ? '自定义上传头像' : '内置头像';
  renderBuiltinAvatarGrid();
}

async function saveUserProfileFromUi(event) {
  if (event) event.preventDefault();
  const displayName = $('profileDisplayNameInput') ? $('profileDisplayNameInput').value.trim() : '';
  const avatarUrl = safeAvatarUrl(state.profileSelectedAvatarUrl || (state.userProfile && state.userProfile.avatar_url));
  setUserProfileStatus('正在保存资料...', 'busy');
  try {
    const data = await api('/api/user-profile', {
      method: 'POST',
      body: JSON.stringify({ display_name: displayName, avatar_url: avatarUrl }),
    });
    renderUserProfile(data);
    setUserProfileStatus('资料已保存。', 'ok');
    log('用户资料已保存', { display_name: displayName, avatar_url: avatarUrl });
  } catch (error) {
    setUserProfileStatus(`保存失败：${error.message}`, 'error');
    log('用户资料保存失败', { error: error.message });
  }
}

async function uploadUserAvatarFromUi() {
  const input = $('profileAvatarFileInput');
  const file = input && input.files ? input.files[0] : null;
  if (!file) {
    setUserProfileStatus('请选择头像图片。', 'error');
    return;
  }
  if (file.size > state.profileUploadLimit) {
    setUserProfileStatus(`头像不能超过 ${Math.round(state.profileUploadLimit / 1024 / 1024)}MB。`, 'error');
    return;
  }
  const allowedTypes = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
  if (file.type && !allowedTypes.has(file.type)) {
    setUserProfileStatus('只支持 PNG、JPG、WEBP 或 GIF。', 'error');
    return;
  }
  const formData = new FormData();
  formData.append('file', file);
  const displayName = $('profileDisplayNameInput') ? $('profileDisplayNameInput').value.trim() : '';
  formData.append('display_name', displayName);
  setUserProfileStatus('正在上传头像...', 'busy');
  try {
    const response = await fetch('/api/user-profile/avatar', {
      method: 'POST',
      headers: authHeaders(),
      body: formData,
    });
    const payload = await response.json();
    if (response.status === 401 && webAuthEnabled()) {
      clearWebAuthToken();
      showWebAuthOverlay('请先登录');
    }
    if (!payload.ok) {
      const error = new Error(payload.error || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    renderUserProfile(payload.data);
    if (input) input.value = '';
    setUserProfileStatus('头像已上传。', 'ok');
    log('用户头像已上传', { avatar_url: payload.data && payload.data.profile && payload.data.profile.avatar_url });
  } catch (error) {
    setUserProfileStatus(`上传失败：${error.message}`, 'error');
    log('用户头像上传失败', { error: error.message });
  }
}

function savedWebAuthTokenInfo() {
  const persistentToken = localStorage.getItem(WEB_AUTH_TOKEN_KEY) || '';
  if (persistentToken) return { token: persistentToken, remember: true };
  const sessionToken = sessionStorage.getItem(WEB_AUTH_SESSION_TOKEN_KEY) || '';
  if (sessionToken) return { token: sessionToken, remember: false };
  return { token: state.webAuthToken || '', remember: savedWebAuthRememberPreference() };
}

function savedWebAuthToken() {
  return savedWebAuthTokenInfo().token;
}

function savedWebAuthRememberPreference() {
  return localStorage.getItem(WEB_AUTH_REMEMBER_KEY) !== '0';
}

function setWebAuthToken(token, options = {}) {
  const remember = options.remember !== false;
  state.webAuthToken = String(token || '');
  if (state.webAuthToken) {
    if (remember) {
      localStorage.setItem(WEB_AUTH_TOKEN_KEY, state.webAuthToken);
      localStorage.setItem(WEB_AUTH_REMEMBER_KEY, '1');
      sessionStorage.removeItem(WEB_AUTH_SESSION_TOKEN_KEY);
    } else {
      sessionStorage.setItem(WEB_AUTH_SESSION_TOKEN_KEY, state.webAuthToken);
      localStorage.removeItem(WEB_AUTH_TOKEN_KEY);
      localStorage.setItem(WEB_AUTH_REMEMBER_KEY, '0');
    }
  } else {
    localStorage.removeItem(WEB_AUTH_TOKEN_KEY);
    sessionStorage.removeItem(WEB_AUTH_SESSION_TOKEN_KEY);
  }
}

function clearWebAuthToken() {
  setWebAuthToken('');
}

function setWebAuthLoginStatus(message = '', stateName = 'info') {
  const status = $('webAuthLoginStatus');
  if (!status) return;
  status.textContent = message || '';
  status.dataset.state = stateName || 'info';
  status.classList.toggle('visible', !!message);
}

function setWebAuthLoginBusy(busy) {
  const button = $('webAuthLoginBtn');
  if (!button) return;
  button.disabled = !!busy;
  button.classList.toggle('is-loading', !!busy);
}

function setupRequiresAdminRegistration() {
  const auth = state.serverAccess && state.serverAccess.web_auth ? state.serverAccess.web_auth : null;
  return !(auth && auth.configured);
}

function apiEndpointById(id) {
  return API_ENDPOINTS.find((item) => item.id === id) || API_ENDPOINTS[0];
}

function isQuoteEndpoint(endpoint) {
  return !!endpoint && (endpoint.group || '') === 'data' && (endpoint.id.includes('quote') || endpoint.id === 'full_tick');
}

function isDownloadEndpoint(endpoint) {
  return !!endpoint && (endpoint.id === 'history_download' || endpoint.id === 'financial_download');
}

function isExportEndpoint(endpoint) {
  return !!endpoint && endpoint.id === 'data_export';
}

function isTaskProgressEndpoint(endpoint) {
  return isDownloadEndpoint(endpoint) || isExportEndpoint(endpoint);
}

function isQuoteSubscriptionEndpoint(endpoint) {
  return !!endpoint && ['quote_subscribe_whole', 'quote_subscribe_single', 'quote_unsubscribe'].includes(endpoint.id);
}

function endpointHasChannelField(endpoint) {
  return !!endpoint && (endpoint.fields || []).some((field) => {
    const meta = API_FIELD_META[field] || {};
    const name = meta.param || field;
    return name === 'channel';
  });
}

function returnFromBindingQmtGuide() {
  const overlay = $('bindingQmtGuideOverlay');
  const values = state.bindingQmtGuideValues || {};
  const context = state.bindingQmtGuideContext || 'binding';
  if (!overlay || !values.account_id) return;
  overlay.classList.add('hidden');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('binding-dialog-open');
  state.bindingQmtGuideContext = '';
  if (context === 'onboarding') {
    state.accountId = values.account_id;
    state.accountType = normalizeAccountType(values.account_type || state.accountType);
    state.accountKey = values.account_key || state.accountKey;
    state.onboardingBindingValues = { ...values };
    state.onboardingBindingFlowContext = 'onboarding';
    state.onboardingBindingFlowReturnTarget = '';
    state.onboardingBindingFlowActive = false;
    state.onboardingBridgeCheckInFlight = false;
    state.onboardingBridgeCheckToken += 1;
    state.onboardingStep = 'config';
    showOnboardingModal({ force: true });
    setOnboardingStatus('onboardingConfigStatus', '已返回账号配置，可修改后重新保存。', 'warn');
    return;
  }
  openBindingDialog({
    accountKey: values.account_key || '',
    accountId: values.account_id,
    accountType: values.account_type,
    qmtDir: values.qmt_dir,
    qmtTradeDir: values.qmt_trade_dir,
    mode: values.mode,
    dataProvider: values.data_provider !== false,
    marketRoutingEnabled: !!values.marketRoutingEnabled,
    marketBridges: values.marketBridges || {},
  });
}

function apiEndpointChannel(endpoint) {
  if (!endpoint || endpoint.method === 'WS' || endpoint.method === 'DOC') return '';
  if (endpoint.id === 'callbacks') return '';
  if (isDownloadEndpoint(endpoint) || isQuoteSubscriptionEndpoint(endpoint)) return 'normal';
  if (isExportEndpoint(endpoint) || (endpoint.group || '') === 'trade') return 'trade';
  return endpointHasChannelField(endpoint) ? selectedChannel() : '';
}

function applyApiEndpointChannel(endpoint, params) {
  const channel = apiEndpointChannel(endpoint);
  if (channel) params.channel = channel;
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
      state.apiOpenGroups = new Set(['data', 'trade', 'system', 'transport']);
    }
  } catch (error) {
    state.apiOpenGroups = new Set(['data', 'trade', 'system', 'transport']);
  }
}

function renderApiDocs(endpointId = state.apiEndpointId, options = {}) {
  const list = $('apiEndpointList');
  const form = $('apiForm');
  if (!list || !form) return;
  const endpoint = apiEndpointById(endpointId);
  const previousEndpointId = state.apiEndpointId;
  state.apiEndpointId = endpoint.id;
  if (previousEndpointId !== endpoint.id) state.apiDebugRequestSeq += 1;
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
    const submitLabel = endpoint.method === 'WS' ? '连接 WebSocket' : '发送请求';
    actions.innerHTML = `<button class="primary api-submit-btn" type="submit" data-default-label="${esc(submitLabel)}"><span class="button-spinner" aria-hidden="true"></span><span class="api-submit-label">${esc(submitLabel)}</span></button><button id="apiResetBtn" type="button">重置参数</button>`;
    form.appendChild(actions);
    setApiDefaults(endpoint);
  }
  renderApiDocDetail(endpoint);
  updateQuoteLivePanel(endpoint);
  updateDownloadProgressPanel(endpoint);
  renderApiResponseLatency(null, endpoint);
  updateApiRequestPreview();
}

function updateQuoteLivePanel(endpoint) {
  const panel = $('quoteLivePanel');
  if (!panel) return;
  const show = isQuoteEndpoint(endpoint);
  panel.classList.toggle('hidden', !show);
  if (!show) {
    stopQuoteLive();
    return;
  }
  renderQuoteLiveTable();
}

function updateDownloadProgressPanel(endpoint) {
  const panel = $('downloadProgressPanel');
  if (!panel) return;
  const show = isTaskProgressEndpoint(endpoint) || !!state.downloadJobId;
  panel.classList.toggle('hidden', !show);
  if (show) renderDownloadProgress();
}

function newDownloadJobId(endpointId) {
  return `${endpointId || 'download'}_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
}

function clearTaskProgressTimer() {
  if (!state.downloadProgressTimer) return;
  window.clearInterval(state.downloadProgressTimer);
  state.downloadProgressTimer = null;
}

function closeDownloadSocket() {
  if (!state.downloadSocket) return;
  try {
    state.downloadSocket.close();
  } catch (error) {
    // ignore stale sockets
  }
  state.downloadSocket = null;
}

function beginDownloadProgress(jobId, requestBody = {}, endpoint = apiEndpointById(state.apiEndpointId)) {
  closeDownloadSocket();
  clearTaskProgressTimer();
  state.taskProgressKind = 'download';
  state.downloadJobId = String(jobId || '');
  state.downloadJobStatus = 'connecting';
  state.downloadEvents = [];
  state.downloadStartedAt = Date.now();
  state.downloadRequestDoneAt = 0;
  updateDownloadProgressPanel(endpoint);
  renderDownloadProgress();
  if (!state.downloadJobId) return;

  const params = new URLSearchParams();
  params.set('event_prefix', DOWNLOAD_EVENT_PREFIX);
  params.set('job_id', state.downloadJobId);
  if (requestBody.bridge_id) params.set('bridge_id', requestBody.bridge_id);
  if (requestBody.account_id) params.set('account_id', requestBody.account_id);
  if (requestBody.account_type) params.set('account_type', requestBody.account_type);
  if (requestBody.account_key) params.set('account_key', requestBody.account_key);
  const url = apiWsUrl(`/ws/callbacks?${params.toString()}`);
  const socket = new WebSocket(url);
  state.downloadSocket = socket;
  socket.onopen = () => {
    if (state.downloadSocket !== socket) return;
    state.downloadJobStatus = 'waiting';
    renderDownloadProgress();
  };
  socket.onmessage = (event) => {
    if (state.downloadSocket !== socket) return;
    try {
      handleDownloadSocketPayload(JSON.parse(event.data));
    } catch (error) {
      appendDownloadEvent({
        event: 'download:raw',
        data: { raw: event.data },
        received_at: Date.now() / 1000,
      });
    }
  };
  socket.onerror = () => {
    if (state.downloadSocket !== socket) return;
    state.downloadJobStatus = 'socket_error';
    renderDownloadProgress();
  };
  socket.onclose = () => {
    if (state.downloadSocket !== socket) return;
    state.downloadSocket = null;
    if (!downloadStatusIsTerminal(state.downloadJobStatus)) {
      state.downloadJobStatus = 'socket_closed';
      renderDownloadProgress();
    }
  };
}

function beginExportProgress(jobId, requestBody = {}, endpoint = apiEndpointById(state.apiEndpointId)) {
  closeDownloadSocket();
  clearTaskProgressTimer();
  state.taskProgressKind = 'export';
  state.downloadJobId = String(jobId || '');
  state.downloadJobStatus = 'running';
  state.downloadEvents = [{
    event: 'xttrader:export_progress',
    meta: {
      job_id: state.downloadJobId,
      stage: 'running',
      task_kind: 'export',
      bridge_id: requestBody.bridge_id || selectedBridge(),
      account_id: requestBody.account_id || '',
    },
    data: {
      percent: 8,
      message: '导出请求已提交，等待 QMT 返回结果。',
    },
    received_at: Date.now() / 1000,
  }];
  state.downloadStartedAt = Date.now();
  state.downloadRequestDoneAt = 0;
  updateDownloadProgressPanel(endpoint);
  renderDownloadProgress();
  state.downloadProgressTimer = window.setInterval(() => {
    if (downloadStatusIsTerminal(state.downloadJobStatus)) {
      clearTaskProgressTimer();
      return;
    }
    const latest = state.downloadEvents[0];
    if (!latest || !latest.data) return;
    const current = Number(latest.data.percent || 0);
    latest.data.percent = Math.min(92, current + Math.max(1, Math.round((92 - current) * 0.08)));
    latest.data.message = 'QMT 正在导出数据，页面会在完成后自动更新。';
    latest.received_at = Date.now() / 1000;
    renderDownloadProgress();
  }, 900);
}

function handleDownloadSocketPayload(payload) {
  if (!payload || payload.type === 'hello') {
    renderDownloadProgress();
    return;
  }
  if (payload.type === 'history' && Array.isArray(payload.events)) {
    payload.events.forEach((event) => appendDownloadEvent(event));
    return;
  }
  if (payload.type === 'callback' && payload.event) {
    appendDownloadEvent(payload.event);
  }
}

function appendDownloadEvent(event) {
  if (!event || typeof event !== 'object') return;
  const jobId = downloadEventJobId(event);
  if (state.downloadJobId && jobId && jobId !== state.downloadJobId) return;
  const eventKey = downloadEventKey(event);
  if (eventKey && state.downloadEvents.some((row) => downloadEventKey(row) === eventKey)) return;
  state.downloadEvents.unshift(event);
  state.downloadEvents = state.downloadEvents.slice(0, DOWNLOAD_EVENT_LIMIT);
  const stage = downloadEventStage(event);
  if (stage === 'error' || stage === 'failed' || stage === 'fail') {
    state.downloadJobStatus = 'error';
  } else if (['done', 'finished', 'complete', 'completed', 'success', 'request_done'].includes(stage)) {
    state.downloadJobStatus = 'done';
    state.downloadRequestDoneAt = Date.now();
  } else {
    state.downloadJobStatus = 'running';
  }
  renderDownloadProgress();
}

function downloadEventKey(event) {
  if (!event || typeof event !== 'object') return '';
  if (event.seq !== undefined && event.seq !== null) return `seq:${event.seq}`;
  const meta = event.meta && typeof event.meta === 'object' ? event.meta : {};
  const data = event.data && typeof event.data === 'object' && !Array.isArray(event.data) ? event.data : {};
  return [
    event.event || '',
    meta.job_id || data.job_id || '',
    meta.stage || data.stage || '',
    event.received_at || '',
  ].join('|');
}

async function refreshDownloadProgressEvents(source = {}) {
  if (!state.downloadJobId) return;
  const params = new URLSearchParams();
  params.set('event_prefix', DOWNLOAD_EVENT_PREFIX);
  params.set('job_id', state.downloadJobId);
  const data = source && source.data && typeof source.data === 'object' ? source.data : source;
  const bridgeId = data.bridge_id || selectedBridge();
  const accountId = data.account_id || '';
  if (bridgeId) params.set('bridge_id', bridgeId);
  if (accountId) params.set('account_id', accountId);
  const payload = await api(`/api/callbacks?${params.toString()}`);
  (payload.events || []).forEach((event) => appendDownloadEvent(event));
}

function finishDownloadRequest(payload, error = null) {
  if (!state.downloadJobId) return;
  state.downloadRequestDoneAt = Date.now();
  if (error) {
    state.downloadJobStatus = 'error';
    appendDownloadEvent({
      event: 'xtdata:download_progress',
      meta: { job_id: state.downloadJobId, stage: 'error' },
      data: { error: error.message },
      received_at: Date.now() / 1000,
    });
    return;
  }
  if (!state.downloadEvents.length || !downloadStatusIsTerminal(state.downloadJobStatus)) {
    state.downloadJobStatus = payload && payload.ok === false ? 'error' : 'request_done';
    renderDownloadProgress();
  }
  refreshDownloadProgressEvents(payload && payload.data ? payload.data : {})
    .catch((pollError) => log('下载进度拉取失败', { error: pollError.message }));
}

function finishExportProgress(payload, error = null) {
  if (!state.downloadJobId) return;
  clearTaskProgressTimer();
  state.downloadRequestDoneAt = Date.now();
  appendDownloadEvent({
    event: 'xttrader:export_progress',
    meta: {
      job_id: state.downloadJobId,
      stage: error || (payload && payload.ok === false) ? 'error' : 'done',
      task_kind: 'export',
    },
    data: error ? {
      percent: 100,
      error: error.message,
    } : {
      percent: 100,
      message: '导出请求已返回，结果已写入 QMT 侧指定目录。',
    },
    received_at: Date.now() / 1000,
  });
}

function clearDownloadProgress() {
  closeDownloadSocket();
  clearTaskProgressTimer();
  state.downloadJobId = '';
  state.downloadJobStatus = 'idle';
  state.downloadEvents = [];
  state.downloadStartedAt = 0;
  state.downloadRequestDoneAt = 0;
  state.taskProgressKind = 'download';
  renderDownloadProgress();
  updateDownloadProgressPanel(apiEndpointById(state.apiEndpointId));
}

function downloadStatusIsTerminal(status) {
  return ['done', 'error'].includes(String(status || ''));
}

function downloadEventJobId(event) {
  const meta = event && event.meta && typeof event.meta === 'object' ? event.meta : {};
  const data = event && event.data && typeof event.data === 'object' && !Array.isArray(event.data) ? event.data : {};
  return String(event.job_id || event.download_job_id || meta.job_id || meta.download_job_id || data.job_id || data.download_job_id || '');
}

function downloadEventStage(event) {
  const meta = event && event.meta && typeof event.meta === 'object' ? event.meta : {};
  const data = event && event.data && typeof event.data === 'object' && !Array.isArray(event.data) ? event.data : {};
  return String(meta.stage || data.stage || data.status || data.progress_status || event.event || '').trim().toLowerCase();
}

function downloadEventPercent(event) {
  const meta = event && event.meta && typeof event.meta === 'object' ? event.meta : {};
  const data = event && event.data && typeof event.data === 'object' && !Array.isArray(event.data) ? event.data : {};
  const direct = [
    data.percent,
    data.percentage,
    data.progress,
    data.rate,
    data.finished_percent,
    meta.percent,
    meta.progress,
  ].find((value) => value !== undefined && value !== null && value !== '');
  if (direct !== undefined) {
    const number = Number(String(direct).replace('%', ''));
    if (Number.isFinite(number)) return Math.max(0, Math.min(100, number <= 1 ? number * 100 : number));
  }
  const done = Number(data.done ?? data.finished ?? data.current ?? data.completed ?? data.downloaded);
  const total = Number(data.total ?? data.count ?? data.all ?? data.task_count);
  if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
    return Math.max(0, Math.min(100, (done / total) * 100));
  }
  const stage = downloadEventStage(event);
  if (['done', 'finished', 'complete', 'completed', 'success', 'request_done'].includes(stage)) return 100;
  return null;
}

function downloadEventSummary(event) {
  const meta = event && event.meta && typeof event.meta === 'object' ? event.meta : {};
  const data = event && event.data !== undefined ? event.data : {};
  const parts = [];
  const stage = downloadEventStage(event);
  if (stage) parts.push(stage);
  if (meta.download_kind) parts.push(meta.download_kind);
  if (meta.stock_code) parts.push(meta.stock_code);
  if (Array.isArray(meta.stock_list) && meta.stock_list.length) parts.push(meta.stock_list.slice(0, 3).join(','));
  if (Array.isArray(meta.table_list) && meta.table_list.length) parts.push(meta.table_list.slice(0, 3).join(','));
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const message = data.message || data.msg || data.error || data.status_msg || '';
    if (message) parts.push(message);
  }
  if (!parts.length) {
    try {
      parts.push(JSON.stringify(data).slice(0, 160));
    } catch (error) {
      parts.push(String(data).slice(0, 160));
    }
  }
  return parts.filter(Boolean).join(' / ');
}

function downloadStatusText() {
  if (state.taskProgressKind === 'export') {
    const map = {
      idle: '未开始',
      running: '导出中',
      request_done: '导出请求已返回',
      done: '导出已完成',
      error: '导出失败',
      socket_error: '进度连接错误',
      socket_closed: '进度连接已断开',
    };
    return map[state.downloadJobStatus] || state.downloadJobStatus || '未开始';
  }
  const map = {
    idle: '未开始',
    connecting: '正在连接进度回调',
    waiting: '等待 QMT 回调',
    running: '下载中',
    request_done: '请求已返回，等待底层进度回调',
    done: '已完成或底层请求已返回',
    error: '失败',
    socket_error: '进度连接错误',
    socket_closed: '进度连接已断开',
  };
  return map[state.downloadJobStatus] || state.downloadJobStatus || '未开始';
}

function renderDownloadProgress() {
  const panel = $('downloadProgressPanel');
  if (!panel) return;
  const progressTitle = panel.querySelector('.download-progress-head h3');
  const status = $('downloadProgressStatus');
  const job = $('downloadProgressJob');
  const meta = $('downloadProgressMeta');
  const bar = $('downloadProgressBar');
  const eventsBox = $('downloadProgressEvents');
  const isExport = state.taskProgressKind === 'export';
  const latest = state.downloadEvents[0] || null;
  const percent = latest ? downloadEventPercent(latest) : null;
  if (progressTitle) progressTitle.textContent = isExport ? '导出进度' : '任务进度';
  if (status) status.textContent = downloadStatusText();
  if (job) job.textContent = state.downloadJobId || '--';
  if (bar) {
    bar.style.width = percent === null ? '0%' : `${percent.toFixed(0)}%`;
    bar.classList.toggle('is-indeterminate', percent === null && ['connecting', 'waiting', 'running', 'request_done'].includes(state.downloadJobStatus));
    bar.classList.toggle('is-done', state.downloadJobStatus === 'done');
    bar.classList.toggle('is-error', state.downloadJobStatus === 'error');
  }
  if (meta) {
    const elapsed = state.downloadStartedAt ? `${((Date.now() - state.downloadStartedAt) / 1000).toFixed(1)}s` : '--';
    const percentText = percent === null ? '未返回百分比' : `${percent.toFixed(0)}%`;
    meta.textContent = `耗时 ${elapsed}，事件 ${state.downloadEvents.length} 条，进度 ${percentText}`;
  }
  if (eventsBox) {
    eventsBox.innerHTML = state.downloadEvents.slice(0, 8).map((event) => {
      const time = event.received_at ? new Date(Number(event.received_at) * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : nowText();
      return `<div><span>${esc(time)}</span><strong>${esc(downloadEventSummary(event))}</strong></div>`;
    }).join('') || `<div><span>--</span><strong>${isExport ? '等待导出任务开始' : '暂无下载回调'}</strong></div>`;
  }
}

function resetQuoteLive(subscribeId = '', options = {}) {
  if (state.quoteRenderTimer) {
    clearTimeout(state.quoteRenderTimer);
    state.quoteRenderTimer = null;
  }
  state.quoteRows.clear();
  state.quoteSeq = 0;
  state.quoteEventCount = 0;
  state.quoteSocketLogCount = 0;
  state.quoteSocketMessageCount = 0;
  state.quoteSubscribeId = String(subscribeId || '');
  state.quoteLiveActive = !!(options.active && subscribeId);
  state.quoteConnectionText = subscribeId
    ? (state.quoteLiveActive ? `连接中 #${subscribeId}` : `已订阅，未推送 #${subscribeId}`)
    : '未订阅';
  renderQuoteLiveTable();
}

function renderApiDocDetail(endpoint) {
  const box = $('apiDocDetail');
  if (!box) return;
  if (endpoint.id === 'xttrader_compat') {
    box.innerHTML = xttraderCompatDocHtml();
    return;
  }
  if (endpoint.id === 'transport_mode') {
    box.innerHTML = `
      <div class="api-doc-extra">
        <h3>模式说明</h3>
        <p>通用模式加载 <code>CFQUANT_CTYPE_ALL_LOWLAT.py</code>；极致模式加载 <code>CFQUANT_LITE.py</code>，不依赖 <code>cfquant</code> 包导入；高级模式使用两个 QMT 终端。</p>
        <p>高级模式需要两个 QMT 终端：普通 QMT 运行查询桥，极速交易端 QMT 运行交易桥。只有两者都在线时才允许启用，适合追求更低交易延迟和分别控制请求通道的场景。</p>
      </div>
      <div class="api-doc-extra">
        <h3>返回字段</h3>
        ${apiDocTable(API_RETURN_DOCS.transport_mode)}
      </div>`;
    return;
  }
  if (endpoint.id === 'pipe_hub') {
    box.innerHTML = `
      <div class="api-doc-extra">
        <h3>说明</h3>
        <p>PipeHub 只在通用模式下有意义。它负责把 QMT 端 named pipe 的请求、响应和回调转成 Web 能识别的标准事件。</p>
        <p>如果这里显示未运行，说明通用版还没启动，或 QMT 端桥接脚本没有连上 PipeHub。</p>
      </div>
      <div class="api-doc-extra">
        <h3>返回字段</h3>
        ${apiDocTable(API_RETURN_DOCS.pipe_hub)}
      </div>`;
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
      <p>只填写 <code>account_id</code> 时，后端会按账号配置自动找到内部通道。启用 API Key 后，浏览器 WebSocket 会通过 <code>apikey</code> 查询参数传入。</p>
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
      <p>先调用订阅全推行情或订阅单股行情接口获取 <code>subscribe_id</code>，再点击实时行情里的“连接推送”。</p>
      <p>网页调试端不会自动连接行情 WebSocket，也不允许空 <code>subscribe_id</code> 接收全部行情，避免全推行情长时间压垮浏览器。</p>
      <p>程序化调用仍可直接连接 <code>/ws/quotes</code>；浏览器页面只保留少量连接日志，实时表格按固定频率批量刷新。</p>
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
    ['历史下载/财务校验', 'download_history_data、download_history_data2；财务按官方脚本能力通过 get_financial_data、get_raw_financial_data 读取本地已下载数据'],
    ['基础资料', 'get_instrument_detail、get_stock_list_in_sector、get_trading_dates'],
    ['证券/合约基础', 'is_stock、is_fund、is_future、get_stock_type、get_stock_name、get_open_date、get_contract_expire_date、get_contract_multiplier'],
    ['ETF/期权/因子', 'get_ETF_list、get_etf_list、get_option_detail_data、get_option_list、get_option_undl、get_option_undl_data、get_weight_in_index、get_turnover_rate、get_his_st_data、get_his_index_data、get_factor_data'],
    ['运行/客户端', 'get_client、run；额外提供 configure 用于配置 cfquant 客户端'],
  ];
  const dataConditionalRows = [
    ['交易日历/交易时段', 'get_trading_calendar、get_trading_period、get_kline_trading_period、get_all_trading_periods、get_period_list 已补同名条件入口；当前 QMT 暴露对应 callable 时可直接转发。'],
    ['板块维护', 'create_sector、add_sector、remove_sector、reset_sector、remove_stock_from_sector 已补同名条件入口；实际可用性取决于 QMT 策略环境权限和 callable。'],
    ['公式系统', 'create_formula、call_formula、subscribe_formula、unsubscribe_formula、get_formula_result 已补同名条件入口；订阅类 callback 会通过 cfquant 事件通道转发。'],
    ['L2 行情', 'get_l2_quote、get_l2_order、get_l2_transaction、subscribe_l2thousand、get_l2thousand_queue 已补同名条件入口；需要券商 QMT 环境本身支持 L2 callable。'],
    ['下载类补充', 'download_sector_data、download_index_weight、download_history_contracts、download_holiday_data、download_etf_info、download_cb_data、download_his_st_data、download_metatable_data、download_tabular_data 已补同名条件入口。'],
    ['外部/表格数据', 'get_tabular_data、push_custom_data 已补同名条件入口；read_feather、write_feather 属于本地文件工具，暂不放入 QMT 桥接主链路。'],
  ];
  const dataWebRows = [
    ['实时行情', 'POST /api/data/full-tick、POST /api/data/market、POST /api/data/market-ex'],
    ['基础资料', 'POST /api/data/instrument、POST /api/data/sector'],
    ['历史下载/财务读取', 'POST /api/data/history/download、POST /api/data/financial、POST /api/data/financial/download'],
    ['订阅推送', 'POST /api/quotes/whole/subscribe、POST /api/quotes/subscribe、POST /api/quotes/unsubscribe、GET /api/quotes/latest、WS /ws/quotes'],
  ];
  const dataMissingRows = [
    ['行情服务器连接管理', 'connect、disconnect、reconnect、get_quote_server_status、watch_quote_server_status 属于 MiniQMT 客户端连接控制，不等价于大 QMT 策略桥接；当前用 cfquant.status / Web 状态页表达桥接状态。'],
    ['本地数据目录/文件工具', 'get_data_dir、read_feather、write_feather 属于 MiniQMT 本地目录或文件工具语义，不应强行映射到 QMT 运行端；后续可作为独立本地工具补充。'],
  ];
  return `
    <div class="api-doc-extra xt-compat-doc">
      <section>
        <h3>总体进度</h3>
        <p><code>xttrader</code> 已补齐原版 75 个公开方法的同名入口，签名已对齐；已补齐 <code>XtQuantTraderCallback</code> 原版 14 个公开回调方法。</p>
        <p><code>xtdata</code> 原版函数数量较多，cfquant 当前分为三类处理：核心行情/交易数据已实装；部分边缘能力已补同名条件入口；MiniQMT 客户端连接管理和本地文件工具不放进 QMT 桥接主链路。</p>
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
        <h3>xtdata 条件平替</h3>
        ${apiDocTable(dataConditionalRows)}
      </section>
      <section>
        <h3>xtdata 不建议强行平替</h3>
        ${apiDocTable(dataMissingRows)}
      </section>
      <section>
        <h3>追踪文档</h3>
        <p><code>cfquant/docs/xttrader平替追踪.md</code></p>
        <p><code>cfquant/docs/xtdata平替追踪.md</code></p>
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

function renderServerAccessLegacy(info) {
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

async function saveServerAccessFromUiLegacy(source = 'api') {
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

function setServerAccessStatus(message = '', level = '') {
  const status = $('apiServerStatus');
  if (!status) return;
  status.textContent = message;
  status.classList.remove('is-ok', 'is-error', 'is-busy');
  if (level) status.classList.add(`is-${level}`);
}

function setServerAccessBusy(busy, mode = 'save') {
  const activeId = mode === 'reload' ? 'reloadWebServerBtn' : 'saveApiServerBtn';
  ['saveApiServerBtn', 'reloadWebServerBtn'].forEach((id) => {
    const button = $(id);
    if (!button) return;
    if (!button.dataset.idleText) button.dataset.idleText = button.textContent;
    button.disabled = !!busy;
    if (button.id === activeId) {
      button.textContent = busy
        ? (mode === 'reload' ? '正在重载...' : '正在保存...')
        : button.dataset.idleText;
    } else if (!busy) {
      button.textContent = button.dataset.idleText;
    }
  });
}

function renderServerAccess(info) {
  state.serverAccess = info || {};
  const allowRemote = !!state.serverAccess.allow_remote;
  const configuredHost = state.serverAccess.configured_host || (allowRemote ? '0.0.0.0' : '127.0.0.1');
  const boundHost = state.serverAccess.bound_host || configuredHost;
  const configuredPort = state.serverAccess.configured_port || state.serverAccess.web_port || 8765;
  const boundPort = state.serverAccess.bound_port || window.location.port || configuredPort;
  const domains = state.serverAccess.allowed_domains || [];
  const authEnabled = !!state.serverAccess.web_auth_enabled;
  const restartRequired = !!(state.serverAccess.requires_restart || state.serverAccess.restart_required);
  const statusParts = [
    `当前监听 ${boundHost}${boundPort ? `:${boundPort}` : ''}`,
    `配置端口 ${configuredPort}`,
    allowRemote ? '外网访问已开启' : '仅本机访问',
    domains.length ? `白名单 ${domains.join(',')}` : '未设置白名单',
    authEnabled ? '网页登录已启用' : '网页登录未启用',
  ];
  if (restartRequired) statusParts.push('需要重载');

  const listenText = `${boundHost}${boundPort ? `:${boundPort}` : ''}`;
  const scopeText = allowRemote ? '允许外网访问' : '仅本机访问';
  const authText = authEnabled ? '已启用' : '未启用';
  const currentListenValue = $('webCurrentListenValue');
  if (currentListenValue) currentListenValue.textContent = listenText;
  const configuredPortValue = $('webConfiguredPortValue');
  if (configuredPortValue) configuredPortValue.textContent = String(configuredPort);
  const accessScopeValue = $('webAccessScopeValue');
  if (accessScopeValue) accessScopeValue.textContent = domains.length ? `${scopeText}，${domains.length} 条白名单` : scopeText;
  const authStateValue = $('webAuthStateValue');
  if (authStateValue) authStateValue.textContent = authText;
  const logoutBtn = $('webAuthLogoutBtn');
  if (logoutBtn) logoutBtn.classList.toggle('hidden', !authEnabled);

  const overviewToggle = $('allowRemoteAccess');
  if (overviewToggle) overviewToggle.checked = allowRemote;
  const apiToggle = $('allowApiRemoteAccess');
  if (apiToggle) apiToggle.checked = allowRemote;
  const portInput = $('webPortInput');
  if (portInput) portInput.value = configuredPort;
  const domainsInput = $('webAllowedDomainsInput');
  if (domainsInput) domainsInput.value = state.serverAccess.allowed_domains_text || domains.join(',');
  const authToggle = $('webAuthEnabledInput');
  if (authToggle) authToggle.checked = authEnabled;
  const usernameInput = $('webAuthUsernameInput');
  if (usernameInput) {
    usernameInput.value = state.serverAccess.web_auth_username || (state.serverAccess.web_auth && state.serverAccess.web_auth.username) || '';
  }
  const passwordInput = $('webAuthPasswordInput');
  if (passwordInput && !passwordInput.matches(':focus')) passwordInput.value = '';

  const overviewStatus = $('serverAccessStatus');
  if (overviewStatus) overviewStatus.textContent = statusParts.join('；');
  const apiStatus = $('apiServerStatus');
  if (apiStatus && !apiStatus.textContent) {
    setServerAccessStatus(statusParts.join('；'));
  }

  const baseInput = $('apiBaseUrlInput');
  if (baseInput && !baseInput.value.trim()) {
    const currentUrl = state.serverAccess.api_base_url || state.serverAccess.local_url || window.location.origin;
    baseInput.value = normalizeApiBaseUrl(currentUrl);
  }
  if (!authEnabled) {
    clearWebAuthToken();
    hideWebAuthOverlay();
  }
  updateApiRequestPreview();
}

function bindTransportControls() {
  const select1 = $('transportModeSelect');
  const select2 = $('transportModeSelect2');
  const saveBtn = $('saveTransportModeBtn');
  const startBtn = $('startPipeHubBtn');
  const stopBtn = $('stopPipeHubBtn');
  if (select1) {
    select1.addEventListener('change', () => {
      if (select2) select2.value = select1.value;
    });
  }
  if (select2) {
    select2.addEventListener('change', () => {
      if (select1) select1.value = select2.value;
    });
  }
  if (saveBtn) {
    saveBtn.addEventListener('click', () => {
      saveTransportModeFromUi().catch((error) => log('通信模式保存失败', { error: error.message }));
    });
  }
  if (startBtn) {
    startBtn.addEventListener('click', () => {
      api('/api/pipe-hub/start', { method: 'POST', body: '{}' })
        .then((data) => {
          renderPipeHub(data);
          log('PipeHub 已启动', data);
        })
        .catch((error) => log('PipeHub 启动失败', { error: error.message }));
    });
  }
  if (stopBtn) {
    stopBtn.addEventListener('click', () => {
      api('/api/pipe-hub/stop', { method: 'POST', body: '{}' })
        .then((data) => {
          renderPipeHub(data);
          log('PipeHub 已停止', data);
        })
        .catch((error) => log('PipeHub 停止失败', { error: error.message }));
    });
  }
}

function renderTransport(info) {
  const transport = (info && info.transport) || info || {};
  const nextMode = transport.mode || info && info.mode;
  if (nextMode) {
    state.transportMode = normalizeTransportMode(nextMode);
  }
  if (!state.transportMode) {
    state.transportMode = 'ctypes';
  }
  const currentMode = normalizeTransportMode(state.transportMode);
  syncTopStatusDisplay();
  const label = transport.label || transportModeLabel(currentMode);
  const detailLabel = transport.detail_label || transportModeDetailLabel(currentMode);
  const summary = transport.summary || {};
  const transportStatus = $('transportStatus');
  if (transportStatus) {
    const pipeStatus = state.pipeHubStatus && state.pipeHubStatus.status;
    const pipeReady = !!(
      state.pipeHubStatus
      && state.pipeHubStatus.running
      && pipeStatus
      && pipeStatus.qmt_connected
    );
    const advancedReady = !!(
      state.bridgeStatus
      && (
        (state.bridgeStatus.modes
          && state.bridgeStatus.modes.lttx
          && state.bridgeStatus.modes.lttx.ready)
        || (
          state.bridgeStatus.normal
          && state.bridgeStatus.normal.online
          && state.bridgeStatus.trade
          && state.bridgeStatus.trade.online
        )
      )
    );
    const ctypesReady = !!(
      (state.bridgeStatus
        && state.bridgeStatus.modes
        && state.bridgeStatus.modes.ctypes
        && state.bridgeStatus.modes.ctypes.ready)
      || pipeReady
    );
    const online = isCtypesTransportMode(activeAccountMode()) ? ctypesReady : advancedReady;
    setStatus('transportStatus', online, `${label}：${detailLabel}\n${summary.request_scope || ''}`);
    const labelNode = $('transportStatusLabel');
    if (labelNode) labelNode.textContent = isCtypesTransportMode(currentMode) ? `${transportModeLabel(currentMode, true)}端` : '高级模式';
  }
  const select1 = $('transportModeSelect');
  const select2 = $('transportModeSelect2');
  [select1, select2].forEach((select) => {
    if (select) select.value = currentMode;
  });
  const statusText = $('transportStatusText');
  if (statusText) {
    const requestScope = summary.request_scope || transportModeRequestScope(currentMode);
    statusText.textContent = `${label}（${detailLabel}），${requestScope}`;
  }
  const startPipeHubBtn = $('startPipeHubBtn');
  const stopPipeHubBtn = $('stopPipeHubBtn');
  [startPipeHubBtn, stopPipeHubBtn].forEach((button) => {
    if (button) button.disabled = button.dataset.runtimeDisabled === 'true';
  });
  const startLttxBtn = $('lttxStartBtn');
  const stopLttxBtn = $('lttxStopBtn');
  if (startLttxBtn) startLttxBtn.disabled = startLttxBtn.dataset.runtimeDisabled === 'true';
  if (stopLttxBtn) stopLttxBtn.disabled = stopLttxBtn.dataset.runtimeDisabled === 'true';
  const lttxLabel = $('lttxStatusLabel');
  if (lttxLabel) lttxLabel.textContent = 'LTtx（库通信）';
  syncTransportChannelControls();
}

function syncTopStatusDisplay() {
  const universal = isCtypesTransportMode(activeAccountMode());
  ['lttxStatus', 'normalStatus', 'tradeStatus'].forEach((id) => {
    const node = $(id);
    if (node) node.style.display = universal && id !== 'lttxStatus' ? 'none' : '';
  });
}

function syncTransportChannelControls() {
  const mode = activeAccountMode();
  const universal = isCtypesTransportMode(mode);
  const lttx = normalizeTransportMode(mode) === 'lttx';
  const modeLabel = transportModeLabel(mode);
  const query = $('queryChannel');
  const trade = $('tradeChannel');
  [query, trade].forEach((node) => {
    if (!node) return;
    node.disabled = universal || lttx;
    node.title = universal
      ? `${modeLabel}由 ctypes 单桥自动路由`
      : '高级模式交易和账户查询固定走交易端；下载和行情订阅固定走普通 QMT';
  });
  if (universal) {
    if (query) query.value = 'normal';
    if (trade) trade.value = 'trade';
  } else if (lttx) {
    if (query) query.value = 'trade';
    if (trade) trade.value = 'trade';
  }
}

function renderPipeHub(info) {
  state.pipeHubStatus = info || null;
  const box = $('pipeHubStatusBox');
  if (!box) return;
  const lines = [
    `运行：${info && info.running ? '是' : '否'}`,
    `管道：${info && info.pipe_name ? info.pipe_name : '--'}`,
    `进程：${info && info.process_pid ? info.process_pid : '--'}`,
    `QMT 连接：${info && info.status && info.status.qmt_connected ? '是' : '否'}`,
    `待处理请求：${info && info.status && info.status.pending_count !== undefined ? info.status.pending_count : '--'}`,
  ];
  const span = box.querySelector('span');
  if (span) span.textContent = lines.join('；');
}

async function saveServerAccessFromUi(source = 'api', options = {}) {
  const mode = options.reload ? 'reload' : 'save';
  const allowToggle = source === 'overview' ? $('allowRemoteAccess') : $('allowApiRemoteAccess');
  const allowRemote = !!(allowToggle && allowToggle.checked);
  const portInput = $('webPortInput');
  const configuredPort = Number(portInput && portInput.value ? portInput.value : 8765);
  if (!Number.isInteger(configuredPort) || configuredPort < 1 || configuredPort > 65535) {
    setServerAccessStatus('保存失败：网页端口必须是 1 到 65535。', 'error');
    if (portInput) portInput.focus();
    log('网页端口无效', { port: portInput ? portInput.value : '' });
    return;
  }
  const baseInput = $('apiBaseUrlInput');
  let apiBaseUrl = '';
  if (baseInput) {
    const normalized = normalizeApiBaseUrl(baseInput.value);
    baseInput.value = normalized;
    apiBaseUrl = normalized;
  }
  const authEnabled = !!($('webAuthEnabledInput') && $('webAuthEnabledInput').checked);
  const authUsername = $('webAuthUsernameInput') ? $('webAuthUsernameInput').value.trim() : '';
  const authPassword = $('webAuthPasswordInput') ? $('webAuthPasswordInput').value : '';
  const authConfigured = !!(state.serverAccess && state.serverAccess.web_auth && state.serverAccess.web_auth.configured);
  if (authEnabled && !authConfigured && !authPassword) {
    setServerAccessStatus('保存失败：首次启用网页登录需要填写密码。', 'error');
    const passwordInput = $('webAuthPasswordInput');
    if (passwordInput) passwordInput.focus();
    log('首次启用网页登录需要填写密码');
    return;
  }
  const previousAuthEnabled = !!(state.serverAccess && state.serverAccess.web_auth_enabled);
  const previousAuthUsername = state.serverAccess ? (state.serverAccess.web_auth_username || '') : '';
  const authChanged = previousAuthEnabled !== authEnabled || (authEnabled && authUsername && authUsername !== previousAuthUsername) || !!authPassword;
  const body = {
    allow_remote: allowRemote,
    api_base_url: apiBaseUrl,
    web_port: configuredPort,
    allowed_domains: $('webAllowedDomainsInput') ? $('webAllowedDomainsInput').value.trim() : '',
    web_auth_enabled: authEnabled,
    web_auth_username: authUsername,
    web_auth_password: authPassword,
    reload: !!options.reload,
  };
  setServerAccessBusy(true, mode);
  setServerAccessStatus(options.reload ? '正在保存设置并重载 Web 服务...' : '正在保存设置...', 'busy');
  try {
    const data = await api('/api/server-access', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if ($('webAuthPasswordInput')) $('webAuthPasswordInput').value = '';
    if (authChanged) clearWebAuthToken();
    renderServerAccess(data);
    const reloadInfo = data.reload || null;
    if (reloadInfo) {
      const nextUrl = reloadInfo.next_url || data.next_url || '';
      setServerAccessStatus(nextUrl ? `已保存，Web 正在重载；稍后跳转到 ${nextUrl}` : '已保存，Web 正在重载；请稍后刷新页面。', 'ok');
    } else {
      const restartText = data.requires_restart || data.restart_required ? '，端口或监听地址变更需重载后生效。' : '。';
      setServerAccessStatus(`已保存${restartText}`, 'ok');
    }
    log(reloadInfo ? '访问设置已保存，Web 正在重载' : '访问设置已保存', {
      allow_remote: !!data.allow_remote,
      web_port: data.web_port || data.configured_port,
      requires_restart: !!data.requires_restart,
    });
    if (reloadInfo && reloadInfo.next_url) {
      setTimeout(() => {
        window.location.href = reloadInfo.next_url;
      }, 1200);
      return;
    }
    if (authEnabled && authChanged) {
      showWebAuthOverlay('请使用当前账号密码登录');
    }
  } catch (error) {
    setServerAccessStatus(`保存失败：${error.message}`, 'error');
    log(options.reload ? 'Web 重载失败' : '访问设置保存失败', { error: error.message });
  } finally {
    setServerAccessBusy(false, mode);
  }
}

async function saveTransportModeFromUi() {
  const mode = ($('transportModeSelect2') && $('transportModeSelect2').value) || ($('transportModeSelect') && $('transportModeSelect').value) || 'ctypes';
  const data = await api('/api/transport', {
    method: 'POST',
    body: JSON.stringify({ mode, bridge_id: selectedBridge() }),
  });
  renderPipeHub(await api('/api/pipe-hub').catch(() => null));
  renderTransport(data);
  await refreshStatus().catch((error) => log('通信模式保存后状态刷新失败', { error: error.message }));
  log('通信模式已保存', { mode });
}

async function refreshTransport() {
  try {
    const data = await api('/api/transport');
    const pipeHub = await api('/api/pipe-hub').catch(() => null);
    renderPipeHub(pipeHub);
    renderTransport(data);
    return data;
  } catch (error) {
    setStatus('transportStatus', false, error.message);
    const statusText = $('transportStatusText');
    if (statusText) statusText.textContent = error.message;
    return null;
  }
}

function showWebAuthOverlay(message = '') {
  const overlay = $('webAuthOverlay');
  if (!overlay) return;
  overlay.classList.remove('hidden');
  overlay.scrollTop = 0;
  window.scrollTo({ top: 0, left: 0 });
  setWebAuthLoginBusy(false);
  setWebAuthLoginStatus(message, message ? 'info' : 'info');
  const userInput = $('webAuthLoginUserInput');
  if (userInput && !userInput.value) {
    userInput.value = state.serverAccess && state.serverAccess.web_auth_username ? state.serverAccess.web_auth_username : '';
  }
  const passwordInput = $('webAuthLoginPasswordInput');
  if (passwordInput) passwordInput.value = '';
  if (userInput) userInput.focus();
}

function hideWebAuthOverlay() {
  const overlay = $('webAuthOverlay');
  if (overlay) overlay.classList.add('hidden');
}

async function logoutWebAuth() {
  try {
    await api('/api/web-auth/logout', { method: 'POST', body: '{}' });
  } catch (error) {
    log('网页登录退出失败', { error: error.message });
  } finally {
    clearWebAuthToken();
    state.webAuthStatus = null;
    showWebAuthOverlay('已退出登录');
  }
}

async function loginWebAuth(event) {
  if (event) event.preventDefault();
  const username = $('webAuthLoginUserInput') ? $('webAuthLoginUserInput').value.trim() : '';
  const password = $('webAuthLoginPasswordInput') ? $('webAuthLoginPasswordInput').value : '';
  const remember = true;
  if (!username) {
    setWebAuthLoginStatus('请输入管理员账号', 'error');
    const input = $('webAuthLoginUserInput');
    if (input) input.focus();
    return;
  }
  if (!password) {
    setWebAuthLoginStatus('请输入管理员密码', 'error');
    const input = $('webAuthLoginPasswordInput');
    if (input) input.focus();
    return;
  }
  setWebAuthLoginBusy(true);
  setWebAuthLoginStatus('正在校验账号密码...', 'info');
  try {
    const response = await fetch('/api/web-auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, remember }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    const persistent = payload.data.remember !== false;
    setWebAuthToken(payload.data.token || '', { remember: persistent });
    state.webAuthStatus = payload.data;
    setWebAuthLoginStatus('登录成功，正在进入控制台...', 'ok');
    hideWebAuthOverlay();
    await loadConfig();
    await continueAfterConfig();
    log('网页登录成功', { username: payload.data.username || username, remember: persistent });
  } catch (error) {
    clearWebAuthToken();
    setWebAuthLoginStatus(error.message, 'error');
  } finally {
    setWebAuthLoginBusy(false);
  }
}

function showSetupOverlay(message = '') {
  const overlay = $('setupOverlay');
  if (!overlay) return;
  overlay.classList.remove('hidden');
  const accountInput = $('setupAccountId');
  const accountTypeInput = $('setupAccountType');
  const qmtDirInput = $('setupQmtDir');
  const qmtTradeDirInput = $('setupQmtTradeDir');
  const modeInput = $('setupMode');
  const adminFields = $('setupAdminFields');
  const adminUsernameInput = $('setupAdminUsername');
  const adminPasswordInput = $('setupAdminPassword');
  const adminPasswordConfirmInput = $('setupAdminPasswordConfirm');
  const adminRequired = setupRequiresAdminRegistration();
  const setup = state.setup || {};
  const defaultKey = setup.default_account_key || state.defaultAccountKey || setup.default_account_id;
  const defaultConfig = setup.account_configs && setup.account_configs[defaultKey];
  if (adminFields) adminFields.classList.toggle('hidden', !adminRequired);
  if (adminUsernameInput && adminRequired && !adminUsernameInput.value) {
    adminUsernameInput.value = (state.serverAccess && state.serverAccess.web_auth_username) || 'admin';
  }
  if (adminPasswordInput) adminPasswordInput.value = '';
  if (adminPasswordConfirmInput) adminPasswordConfirmInput.value = '';
  if (accountTypeInput) {
    accountTypeInput.value = normalizeAccountType(setup.default_account_type || state.defaultAccountType || (defaultConfig && defaultConfig.account_type) || 'STOCK');
  }
  if (qmtDirInput && !qmtDirInput.value) {
    qmtDirInput.value = setup.default_qmt_dir || (defaultConfig && defaultConfig.qmt_dir) || '';
  }
  if (modeInput) modeInput.value = setup.default_mode || (defaultConfig && defaultConfig.mode) || 'ctypes';
  if (qmtTradeDirInput && !qmtTradeDirInput.value) {
    qmtTradeDirInput.value = setup.default_qmt_trade_dir || (defaultConfig && defaultConfig.qmt_trade_dir) || '';
  }
  syncAdvancedQmtDirField('setupQmtTradeDir', modeInput && modeInput.value);
  updateSetupSteps('config');
  const status = $('setupStatus');
  if (status) status.textContent = message;
  overlay.scrollTop = 0;
  const card = overlay.querySelector('.setup-card');
  if (card) card.scrollTop = 0;
  const focusTarget = [
    adminRequired ? adminUsernameInput : null,
    accountInput,
    qmtDirInput,
  ].find((input) => input && !input.value.trim()) || accountInput;
  if (focusTarget) window.requestAnimationFrame(() => focusTarget.focus());
}

function clearOnboardingAutoShown() {
  for (let index = localStorage.length - 1; index >= 0; index -= 1) {
    const key = localStorage.key(index);
    if (key && key.indexOf('cfquant.onboarding_auto_shown') === 0) {
      localStorage.removeItem(key);
    }
  }
}

function onboardingAutoShownKey() {
  const setup = state.setup || {};
  const accountId = setup.default_account_id || state.defaultAccountId || state.accountId || 'default';
  const accountType = normalizeAccountType(setup.default_account_type || state.defaultAccountType || state.accountType || 'STOCK');
  const mode = setup.default_mode || activeAccountMode() || 'ctypes';
  return `${ONBOARDING_AUTO_SHOWN_KEY}.${accountType}.${accountId}.${mode}`;
}

function updateSetupSteps(activeStep) {
  const order = ['config', 'identity', 'qmt'];
  const activeIndex = Math.max(0, order.indexOf(activeStep));
  document.querySelectorAll('[data-setup-step]').forEach((node) => {
    const index = order.indexOf(node.dataset.setupStep);
    node.classList.toggle('done', index >= 0 && index < activeIndex);
    node.classList.toggle('active', index === activeIndex);
  });
}

function hideSetupOverlay() {
  const overlay = $('setupOverlay');
  if (overlay) overlay.classList.add('hidden');
}

async function submitSetupForm(event) {
  if (event) event.preventDefault();
  const status = $('setupStatus');
  const adminRequired = setupRequiresAdminRegistration();
  const body = {
    account_id: $('setupAccountId') ? $('setupAccountId').value.trim() : '',
    account_type: $('setupAccountType') ? $('setupAccountType').value : 'STOCK',
    qmt_dir: $('setupQmtDir') ? $('setupQmtDir').value.trim() : '',
    qmt_trade_dir: $('setupQmtTradeDir') ? $('setupQmtTradeDir').value.trim() : '',
    mode: $('setupMode') ? $('setupMode').value : 'ctypes',
  };
  if (adminRequired) {
    const adminUsername = $('setupAdminUsername') ? $('setupAdminUsername').value.trim() : '';
    const adminPassword = $('setupAdminPassword') ? $('setupAdminPassword').value : '';
    const adminPasswordConfirm = $('setupAdminPasswordConfirm') ? $('setupAdminPasswordConfirm').value : '';
    if (!adminUsername) {
      if (status) status.textContent = '管理员账号不能为空';
      const input = $('setupAdminUsername');
      if (input) input.focus();
      return;
    }
    if (!adminPassword) {
      if (status) status.textContent = '管理员密码不能为空';
      const input = $('setupAdminPassword');
      if (input) input.focus();
      return;
    }
    if (adminPassword.length < 6) {
      if (status) status.textContent = '管理员密码至少 6 位';
      const input = $('setupAdminPassword');
      if (input) input.focus();
      return;
    }
    if (adminPassword !== adminPasswordConfirm) {
      if (status) status.textContent = '两次输入的管理员密码不一致';
      const input = $('setupAdminPasswordConfirm');
      if (input) input.focus();
      return;
    }
    body.admin_username = adminUsername;
    body.admin_password = adminPassword;
    body.admin_password_confirm = adminPasswordConfirm;
  }
  if (!body.account_id) {
    if (status) status.textContent = '账号不能为空';
    const input = $('setupAccountId');
    if (input) input.focus();
    return;
  }
  if (normalizeTransportMode(body.mode) === 'lttx') {
    if (!body.qmt_dir || !body.qmt_trade_dir) {
      if (status) status.textContent = '请填写两个 QMT 目录';
      const input = body.qmt_dir ? $('setupQmtTradeDir') : $('setupQmtDir');
      if (input) input.focus();
      return;
    }
    if (qmtDirsAreSame(body.qmt_dir, body.qmt_trade_dir)) {
      if (status) status.textContent = '两个 QMT 目录不能相同';
      const input = $('setupQmtTradeDir');
      if (input) input.focus();
      return;
    }
  }
  if (status) status.textContent = '正在保存...';
  updateSetupSteps('identity');
  try {
    const data = await api('/api/setup/initialize', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    updateSetupSteps('qmt');
    state.setup = data.setup || null;
    state.accountPairs = data.account_pairs || {};
    state.accountConfigs = data.account_configs || {};
    state.bridges = data.bridges || state.bridges;
    if (data.web_auth && data.web_auth.token) {
      const persistent = data.web_auth.remember !== false;
      setWebAuthToken(data.web_auth.token, { remember: persistent });
      state.webAuthStatus = data.web_auth;
    }
    if (data.server_access) {
      renderServerAccess(data.server_access);
    }
    await loadConfig();
    hideSetupOverlay();
    await startAuthenticatedApp();
    localStorage.setItem(onboardingAutoShownKey(), '1');
    showBindingQmtGuide({
      account_id: body.account_id,
      account_type: body.account_type,
      qmt_dir: body.qmt_dir,
      qmt_trade_dir: body.qmt_trade_dir,
      mode: body.mode,
    }, data.qmt_core_deploy, { context: 'onboarding' });
    if (qmtCoreDeployHasIssues(data.qmt_core_deploy)) {
      setView('bindings');
      setBindingNotice(qmtCoreDeploySummaryText(data.qmt_core_deploy) || 'cfquant 核心包自动复制失败，请检查 QMT 目录和权限。', 'warn', { autoHide: false });
    }
    log('初始化配置已保存', {
      account_id: body.account_id,
      account_type: body.account_type,
      mode: body.mode,
      qmt_dir_configured: !!body.qmt_dir,
      qmt_trade_dir_configured: !!body.qmt_trade_dir,
      admin_registered: adminRequired,
      qmt_core_deploy: data.qmt_core_deploy ? qmtCoreDeployLogPayload(data.qmt_core_deploy) : null,
      bridge_identity: data.qmt_bridge_identity || null,
    });
  } catch (error) {
    updateSetupSteps('config');
    if (status) status.textContent = error.message;
    log('初始化配置保存失败', { error: error.message });
  }
}

async function reinitializeSetup() {
  if (!window.confirm('重新初始化会清空账号运行配置，需要重新输入默认账号、QMT目录和模式。确认继续吗？')) {
    return;
  }
  try {
    await api('/api/setup/reset', { method: 'POST', body: '{}' });
    clearOnboardingAutoShown();
    clearAccountConfigCache();
    window.location.reload();
  } catch (error) {
    log('重新初始化失败', { error: error.message });
  }
}

async function continueAfterConfig() {
  if (state.setup && state.setup.setup_required) {
    showSetupOverlay('请完成初始化配置');
    return;
  }
  hideSetupOverlay();
  await startAuthenticatedApp();
  maybeAutoOpenOnboardingGuide();
}

async function ensureWebAuth() {
  if (!webAuthEnabled()) {
    clearWebAuthToken();
    hideWebAuthOverlay();
    return true;
  }
  const savedTokenInfo = savedWebAuthTokenInfo();
  const savedToken = savedTokenInfo.token;
  if (savedToken) {
    setWebAuthToken(savedToken, { remember: savedTokenInfo.remember });
  }
  try {
    state.webAuthStatus = await api('/api/web-auth/status');
    hideWebAuthOverlay();
    return true;
  } catch (error) {
    clearWebAuthToken();
    showWebAuthOverlay('登录已失效');
    return false;
  }
}

function renderLogCleanup(info) {
  state.logCleanup = info || {};
  const enabled = !!state.logCleanup.qmt_userdata_log_cleanup_enabled;
  const toggle = $('cleanupQmtUserdataLogs');
  if (toggle) toggle.checked = enabled;
  const status = $('logCleanupStatus');
  if (!status) return;
  const retentionDays = state.logCleanup.retention_days || 30;
  const parts = [
    `本地保留 ${retentionDays} 天`,
    enabled ? 'QMT 清理已启用' : 'QMT 清理未启用',
  ];
  const last = state.logCleanup.last_result;
  if (last && last.finished_at_text) {
    parts.push(`上次 ${last.finished_at_text}`);
  }
  status.textContent = parts.join('，');
}

function renderQmtLogLanguage(info) {
  state.qmtLogLanguage = info || {};
  const language = state.qmtLogLanguage.language || 'zh';
  const enabled = state.qmtLogLanguage.enabled !== false;
  const toggle = $('qmtLogEnabled');
  if (toggle) toggle.checked = enabled;
  const select = $('qmtLogLanguageSelect');
  if (select) select.value = language;
  const status = $('qmtLogLanguageStatus');
  if (status) status.textContent = `当前：${enabled ? '日志开启' : '日志关闭'}，${language === 'en' ? 'English' : '中文'}`;
}

async function saveQmtLogLanguageFromUi() {
  const select = $('qmtLogLanguageSelect');
  const toggle = $('qmtLogEnabled');
  const language = select ? select.value : 'zh';
  const data = await api('/api/qmt-log-language', {
    method: 'POST',
    body: JSON.stringify({ language, enabled: !!(toggle && toggle.checked) }),
  });
  renderQmtLogLanguage(data);
  log('QMT 日志设置已保存', {
    language: data.language,
    enabled: data.enabled,
    dispatch_results: data.dispatch_results || [],
  });
}

async function saveLogCleanupFromUi() {
  const toggle = $('cleanupQmtUserdataLogs');
  const data = await api('/api/log-cleanup', {
    method: 'POST',
    body: JSON.stringify({ qmt_userdata_log_cleanup_enabled: !!(toggle && toggle.checked) }),
  });
  renderLogCleanup(data);
  log('日志清理设置已保存', { qmt_userdata_log_cleanup_enabled: !!data.qmt_userdata_log_cleanup_enabled });
}

async function runLogCleanupFromUi() {
  const toggle = $('cleanupQmtUserdataLogs');
  const data = await api('/api/log-cleanup/run', {
    method: 'POST',
    body: JSON.stringify({ qmt_userdata_log_cleanup_enabled: !!(toggle && toggle.checked) }),
  });
  const status = await api('/api/log-cleanup');
  renderLogCleanup(status);
  log('日志清理已执行', data);
}

function updateLayoutText(layout) {
  if (layout === 'nested') return '旧嵌套目录';
  if (layout === 'single') return '当前单层目录';
  return '';
}

function setUpdateControlsBusy(busy = state.updateBusy) {
  state.updateBusy = !!busy;
  const ready = !!(state.updateStatus && state.updateStatus.ready);
  const backups = state.updateStatus && Array.isArray(state.updateStatus.backups) ? state.updateStatus.backups : [];
  const actionIds = ['runGithubUpdateBtn', 'uploadZipUpdateBtn'];
  actionIds.forEach((id) => {
    const button = $(id);
    if (button) button.disabled = state.updateBusy || !ready;
  });
  const refreshButton = $('refreshUpdateStatusBtn');
  if (refreshButton) refreshButton.disabled = state.updateBusy;
  const rollbackButton = $('rollbackUpdateBtn');
  if (rollbackButton) rollbackButton.disabled = state.updateBusy || !ready || !backups.length;
}

function setProjectUpdateControlsBusy(busy = state.projectUpdateBusy) {
  state.projectUpdateBusy = !!busy;
  const ready = !!(state.projectUpdateStatus && state.projectUpdateStatus.ready);
  const backups = state.projectUpdateStatus && Array.isArray(state.projectUpdateStatus.backups)
    ? state.projectUpdateStatus.backups
    : [];
  ['runProjectGithubUpdateBtn', 'uploadProjectZipUpdateBtn'].forEach((id) => {
    const button = $(id);
    if (button) button.disabled = state.projectUpdateBusy || !ready;
  });
  const refreshButton = $('refreshProjectUpdateStatusBtn');
  if (refreshButton) refreshButton.disabled = state.projectUpdateBusy;
  const rollbackButton = $('rollbackProjectUpdateBtn');
  if (rollbackButton) rollbackButton.disabled = state.projectUpdateBusy || !ready || !backups.length;
  renderProjectVersion(state.versionInfo);
}

function qmtUpdateProgressSteps(kind) {
  if (kind === 'project-upload') {
    return [
      { key: 'prepare', label: '确认 Web 更新目标', percent: 8 },
      { key: 'upload', label: '上传项目源码 zip', percent: 42 },
      { key: 'backup', label: '备份当前 Web 项目', percent: 58 },
      { key: 'install', label: '替换 Web 项目文件', percent: 82 },
      { key: 'restart', label: '重启 Web 服务', percent: 94 },
      { key: 'done', label: '更新完成', percent: 100 },
    ];
  }
  if (kind === 'project-rollback') {
    return [
      { key: 'prepare', label: '确认 Web 回滚目标', percent: 12 },
      { key: 'backup', label: '备份当前 Web 项目', percent: 36 },
      { key: 'restore', label: '恢复选中备份', percent: 76 },
      { key: 'restart', label: '重启 Web 服务', percent: 94 },
      { key: 'done', label: '回滚完成', percent: 100 },
    ];
  }
  if (kind === 'project-official') {
    return [
      { key: 'prepare', label: '确认 Web 更新目标', percent: 8 },
      { key: 'download', label: '连接官网并下载发布包', percent: 38 },
      { key: 'backup', label: '备份当前 Web 项目', percent: 58 },
      { key: 'install', label: '替换 Web 项目文件', percent: 82 },
      { key: 'restart', label: '重启 Web 服务', percent: 94 },
      { key: 'done', label: '更新完成', percent: 100 },
    ];
  }
  if (kind === 'upload') {
    return [
      { key: 'prepare', label: '确认更新目标', percent: 8 },
      { key: 'upload', label: '上传源码 zip', percent: 42 },
      { key: 'backup', label: '备份当前 QMT 核心包', percent: 58 },
      { key: 'install', label: '替换 cfquant 核心包', percent: 82 },
      { key: 'refresh', label: '刷新更新状态', percent: 94 },
      { key: 'done', label: '更新完成', percent: 100 },
    ];
  }
  if (kind === 'rollback') {
    return [
      { key: 'prepare', label: '确认回滚目标', percent: 12 },
      { key: 'backup', label: '备份当前 QMT 核心包', percent: 36 },
      { key: 'restore', label: '恢复选中备份', percent: 76 },
      { key: 'refresh', label: '刷新更新状态', percent: 94 },
      { key: 'done', label: '回滚完成', percent: 100 },
    ];
  }
  return [
    { key: 'prepare', label: '确认更新目标', percent: 8 },
    { key: 'download', label: '连接官网并下载源码', percent: 38 },
    { key: 'backup', label: '备份当前 QMT 核心包', percent: 58 },
    { key: 'install', label: '替换 cfquant 核心包', percent: 82 },
    { key: 'refresh', label: '刷新更新状态', percent: 94 },
    { key: 'done', label: '更新完成', percent: 100 },
  ];
}

function clearQmtUpdateProgressTimer() {
  if (state.qmtUpdateProgressTimer) {
    window.clearInterval(state.qmtUpdateProgressTimer);
    state.qmtUpdateProgressTimer = null;
  }
}

function renderQmtUpdateProgress() {
  const progress = state.qmtUpdateProgress;
  const overlay = $('qmtUpdateProgressOverlay');
  if (!overlay) return;
  overlay.classList.toggle('hidden', !progress);
  overlay.setAttribute('aria-hidden', progress ? 'false' : 'true');
  if (!progress) return;
  const title = $('qmtUpdateProgressTitle');
  const percentText = $('qmtUpdateProgressPercent');
  const bar = $('qmtUpdateProgressBar');
  const detail = $('qmtUpdateProgressDetail');
  const stepsBox = $('qmtUpdateProgressSteps');
  const closeBtn = $('qmtUpdateProgressCloseBtn');
  const closeBottomBtn = $('qmtUpdateProgressCloseBottomBtn');
  const percent = Math.max(0, Math.min(100, Number(progress.percent) || 0));
  if (title) title.textContent = progress.title || '系统更新进度';
  if (percentText) percentText.textContent = `${Math.round(percent)}%`;
  if (bar) {
    bar.style.width = `${percent}%`;
    bar.classList.toggle('failed', progress.status === 'error');
    bar.classList.toggle('done', progress.status === 'done');
  }
  if (detail) detail.textContent = progress.detail || '';
  if (stepsBox) {
    const currentIndex = progress.stepIndex || 0;
    stepsBox.innerHTML = (progress.steps || []).map((step, index) => {
      const cls = index < currentIndex ? 'done' : (index === currentIndex ? 'active' : '');
      return `<li class="${cls}"><span>${index + 1}</span><strong>${esc(step.label)}</strong></li>`;
    }).join('');
  }
  const canClose = progress.status === 'done' || progress.status === 'error';
  [closeBtn, closeBottomBtn].forEach((button) => {
    if (button) button.disabled = !canClose;
  });
}

function openQmtUpdateProgress(kind, title, detail) {
  clearQmtUpdateProgressTimer();
  forceCloseVersionPopover();
  const steps = qmtUpdateProgressSteps(kind);
  state.qmtUpdateProgress = {
    kind,
    title: title || '系统更新进度',
    detail: detail || '',
    status: 'running',
    stepIndex: 0,
    percent: steps[0] ? steps[0].percent : 0,
    steps,
    startedAt: Date.now(),
  };
  renderQmtUpdateProgress();
  state.qmtUpdateProgressTimer = window.setInterval(() => {
    const progress = state.qmtUpdateProgress;
    if (!progress || progress.status !== 'running') return;
    const maxIndex = Math.max(0, (progress.steps || []).length - 2);
    const nextIndex = Math.min(maxIndex, (progress.stepIndex || 0) + 1);
    if (nextIndex !== progress.stepIndex) {
      progress.stepIndex = nextIndex;
      progress.percent = Math.max(progress.percent || 0, progress.steps[nextIndex].percent);
      renderQmtUpdateProgress();
    }
  }, 1400);
}

function setQmtUpdateProgressStep(stepKey, detail, percent) {
  const progress = state.qmtUpdateProgress;
  if (!progress) return;
  const index = (progress.steps || []).findIndex((step) => step.key === stepKey);
  if (index >= 0) progress.stepIndex = index;
  if (detail) progress.detail = detail;
  if (percent !== undefined && percent !== null) {
    progress.percent = Math.max(progress.percent || 0, Math.min(100, Number(percent) || 0));
  } else if (index >= 0) {
    progress.percent = Math.max(progress.percent || 0, progress.steps[index].percent);
  }
  renderQmtUpdateProgress();
}

function finishQmtUpdateProgress(payload, detail) {
  const progress = state.qmtUpdateProgress;
  if (!progress) return;
  clearQmtUpdateProgressTimer();
  progress.status = 'done';
  progress.stepIndex = Math.max(0, (progress.steps || []).length - 1);
  progress.percent = 100;
  const version = payload && payload.current_version ? `，当前版本 ${payload.current_version}` : '';
  progress.detail = detail || `操作完成${version}。请按页面提示重启 QMT 入口脚本。`;
  renderQmtUpdateProgress();
}

function failQmtUpdateProgress(error) {
  const progress = state.qmtUpdateProgress;
  if (!progress) return;
  clearQmtUpdateProgressTimer();
  progress.status = 'error';
  progress.detail = `操作失败：${error && error.message ? error.message : error}`;
  progress.percent = Math.max(progress.percent || 0, 12);
  renderQmtUpdateProgress();
}

function closeQmtUpdateProgress() {
  const progress = state.qmtUpdateProgress;
  if (progress && progress.status === 'running') return;
  clearQmtUpdateProgressTimer();
  state.qmtUpdateProgress = null;
  renderQmtUpdateProgress();
}

function syncUpdateResultDetails(box, payload) {
  const details = box && box.closest ? box.closest('.update-result-details') : null;
  if (details) details.open = !!payload;
}

function renderUpdateResult(payload) {
  const box = $('updateResultBox');
  if (!box) return;
  renderUpdateNotice('updateNoticeBox', payload, { forceQmtRestart: true });
  box.textContent = payload ? JSON.stringify(payload, null, 2) : '';
  syncUpdateResultDetails(box, payload);
}

function renderProjectUpdateResult(payload) {
  const box = $('projectUpdateResultBox');
  if (!box) return;
  renderUpdateNotice('projectUpdateNoticeBox', payload, { forceQmtRestart: false });
  box.textContent = payload ? JSON.stringify(payload, null, 2) : '';
  syncUpdateResultDetails(box, payload);
}

function buildUpdateNoticeLines(payload, options = {}) {
  if (!payload) return [];
  const restart = payload.qmt_restart_required || {};
  const entry = payload.entry_manual_update || restart.entry_manual_update || {};
  const restartRequired = !!restart.required || !!options.forceQmtRestart;
  const entryRequired = !!entry.required;
  if (!restartRequired && !entryRequired) return [];
  const lines = [];
  if (restartRequired) {
    lines.push({
      strong: 'QMT 侧需要重启',
      text: restart.message || '更新完成后，请停止并重新启动对应 QMT 入口脚本，让 QMT 加载最新代码。',
    });
  }
  if (entryRequired) {
    const files = Array.isArray(entry.entry_files) && entry.entry_files.length
      ? `涉及入口：${entry.entry_files.join('、')}`
      : '涉及 QMT 入口脚本';
    lines.push({
      strong: '入口文件需要手动更新',
      text: `${entry.message || 'QMT 入口文件需要手动更新后再启动。'} ${files}`,
    });
  } else if (restartRequired) {
    lines.push({
      strong: '入口文件',
      text: '本次未检测到入口脚本变更。如果版本说明提到入口文件变化，请手动更新 QMT 里的加密入口文件后再启动。',
    });
  }
  return lines;
}

function buildUpdateNoticeModel(payload, options = {}) {
  const lines = buildUpdateNoticeLines(payload, options);
  if (!lines.length) return null;
  const restart = payload.qmt_restart_required || {};
  const entry = payload.entry_manual_update || restart.entry_manual_update || {};
  const entryFiles = Array.isArray(entry.entry_files) ? entry.entry_files.filter(Boolean) : [];
  const version = payload.current_version || payload.version || '';
  const targetDir = payload.python_dir || payload.target_dir || '';
  const restartRequired = !!restart.required || !!options.forceQmtRestart;
  const entryRequired = !!entry.required;
  const modeFiles = entry.mode_files && typeof entry.mode_files === 'object' ? entry.mode_files : {};
  const steps = entryRequired
    ? [
      '停止 QMT 里正在运行的 cfquant 入口脚本。',
      `手动更新入口文件${entryFiles.length ? `：${entryFiles.join('、')}` : '。'}`,
      '重新启动对应 QMT 入口脚本，让新代码重新加载。',
      '回到网页刷新状态，确认通道在线。',
    ]
    : [
      '停止 QMT 里正在运行的 cfquant 桥接脚本。',
      '重新启动对应入口脚本，让 QMT 加载最新核心包。',
      '回到网页刷新状态，确认通道在线。',
    ];
  return {
    title: entryRequired ? 'QMT 入口文件需要手动更新' : 'QMT 侧需要重启',
    subtitle: entryRequired
      ? '本次更新涉及 QMT 入口脚本。由于入口文件通常是加密文件，需要手动替换后再启动。'
      : '核心文件已经写入磁盘，但 QMT 运行中的脚本不会自动加载新代码。',
    lines,
    steps,
    version,
    targetDir,
    bridgeId: payload.bridge_id || '',
    restartRequired,
    entryRequired,
    entryFiles,
    modeFiles,
  };
}

function renderUpdateNoticeCard(model, options = {}) {
  if (!model) return '';
  const meta = [
    model.version ? `版本 ${model.version}` : '',
    model.bridgeId ? `桥接 ${model.bridgeId}` : '',
  ].filter(Boolean);
  const entryText = model.entryFiles.length ? `入口：${model.entryFiles.join('、')}` : '';
  const compactClass = options.compact ? ' compact' : '';
  const primaryLine = model.entryRequired
    ? (model.lines.find((line) => line.strong.includes('入口')) || model.lines[0] || null)
    : (model.lines[0] || null);
  const secondaryLine = primaryLine
    ? model.lines.find((line) => line !== primaryLine && line.strong !== primaryLine.strong)
    : null;
  return `
    <div class="update-notice-card${compactClass}">
      <div class="update-notice-head">
        <div>
          <strong>${esc(model.title)}</strong>
          <span>${esc(primaryLine ? primaryLine.text : model.subtitle)}</span>
        </div>
        <em>${esc(model.entryRequired ? '需手动处理' : '需重启')}</em>
      </div>
      ${meta.length ? `<div class="update-notice-meta">${meta.map((item) => `<span>${esc(item)}</span>`).join('')}</div>` : ''}
      ${(secondaryLine || entryText) ? `<div class="update-notice-mode-files">
        ${secondaryLine ? `<span><strong>${esc(secondaryLine.strong)}</strong>${esc(secondaryLine.text)}</span>` : ''}
        ${entryText ? `<span>${esc(entryText)}</span>` : ''}
      </div>` : ''}
    </div>`;
}

function renderUpdateNotice(boxId, payload, options = {}) {
  const box = $(boxId);
  if (!box) return;
  const model = buildUpdateNoticeModel(payload, options);
  box.classList.toggle('hidden', !model);
  box.innerHTML = model ? renderUpdateNoticeCard(model, { compact: true }) : '';
}

function renderUpdateRestartNoticeModal() {
  const overlay = $('updateRestartNoticeOverlay');
  if (!overlay) return;
  const model = state.updateRestartNotice;
  overlay.classList.toggle('hidden', !model);
  overlay.setAttribute('aria-hidden', model ? 'false' : 'true');
  if (!model) return;
  const title = $('updateRestartNoticeTitle');
  const summary = $('updateRestartNoticeSummary');
  const body = $('updateRestartNoticeBody');
  if (title) title.textContent = model.title;
  if (summary) summary.textContent = model.subtitle;
  if (body) body.innerHTML = renderUpdateNoticeCard(model);
}

function openUpdateRestartNotice(payload, options = {}) {
  const model = buildUpdateNoticeModel(payload, options);
  if (!model) return false;
  state.updateRestartNotice = model;
  renderUpdateRestartNoticeModal();
  const closeBtn = $('updateRestartNoticeCloseBottomBtn') || $('updateRestartNoticeCloseBtn');
  if (closeBtn) window.setTimeout(() => closeBtn.focus(), 0);
  return true;
}

function closeUpdateRestartNotice() {
  state.updateRestartNotice = null;
  renderUpdateRestartNoticeModal();
}

function wireUpdateRestartNotice() {
  ['updateRestartNoticeCloseBtn', 'updateRestartNoticeCloseBottomBtn'].forEach((id) => {
    const button = $(id);
    if (button) button.addEventListener('click', closeUpdateRestartNotice);
  });
  const settingsBtn = $('updateRestartNoticeSettingsBtn');
  if (settingsBtn) {
    settingsBtn.addEventListener('click', () => {
      closeUpdateRestartNotice();
      setView('settings');
      setSettingsTab('update');
    });
  }
  const overlay = $('updateRestartNoticeOverlay');
  if (overlay) {
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) closeUpdateRestartNotice();
    });
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.updateRestartNotice) closeUpdateRestartNotice();
  });
}

function alertUpdateNotice(payload, options = {}) {
  const lines = buildUpdateNoticeLines(payload, options);
  if (!lines.length) return;
  if (openUpdateRestartNotice(payload, options)) return;
  window.alert(lines.map((line) => `${line.strong}\n${line.text}`).join('\n\n'));
}

function updateVersionLabel(info) {
  if (!info) return '--';
  const parts = [];
  if (info.version) parts.push(`版本 ${info.version}`);
  if (info.short_commit) parts.push(`commit ${info.short_commit}`);
  if (info.updated_at_text) parts.push(info.updated_at_text);
  return parts.length ? parts.join(' / ') : '--';
}

function updateCompareText(value) {
  if (value === true) return '一致';
  if (value === false) return '可更新';
  return '无法判断';
}

function updateCompareClass(value) {
  if (value === true) return 'match';
  if (value === false) return 'diff';
  return 'unknown';
}

function remoteUpdateSourceLabel(remote = {}) {
  const source = String(remote.source || '').toLowerCase();
  if (source.includes('cfquant') || source.includes('official')) return '官网版本';
  if (source.includes('github') || remote.repo_url) return 'GitHub 版本';
  return '远端版本';
}

function remoteUpdateDetail(remote = {}, fallback = DEFAULT_UPDATE_REPO_URL) {
  if (remote.error) return `获取失败：${remote.error}`;
  const source = String(remote.source || '').toLowerCase();
  const base = source.includes('cfquant') || remote.download_url
    ? (remote.site_url || DEFAULT_OFFICIAL_SITE_URL)
    : (remote.repo_url || fallback);
  const suffix = remote.ref && !source.includes('cfquant') ? `#${remote.ref}` : '';
  const checked = remote.checked_at_text ? ` / ${remote.checked_at_text}` : '';
  const cached = remote.cached ? ' / 缓存' : '';
  const fallbackNote = remote.fallback_error && source.includes('github') ? ` / 官网失败后回退：${remote.fallback_error}` : '';
  return `${base || '--'}${suffix}${checked}${cached}${fallbackNote}`;
}

function renderUpdateVersionInfo(data) {
  const box = $('updateVersionInfo');
  if (!box) return;
  if (!data) {
    box.innerHTML = '<div class="update-version-empty">等待刷新</div>';
    return;
  }
  const version = data && data.version_status ? data.version_status : {};
  const current = version.current || {};
  const remote = version.remote || {};
  const report = (data && (data.runtime_report || data.qmt_saved_report))
    || current.runtime_report
    || current.qmt_saved_report
    || {};
  const runtimeReported = Boolean((data && data.runtime_reported) || current.runtime_reported || (report.reported && report.version));
  const runtimeVersion = (data && data.runtime_version) || current.runtime_version || (report.reported ? report.version : '') || '';
  const latestQmtVersion = (data && data.latest_qmt_core_version)
    || current.latest_qmt_core_version
    || current.qmt_builtin_version
    || qmtKnownVersion(data || {}, report);
  const fileVersion = (data && data.file_version) || current.file_version || '';
  const qmtComparison = version.qmt_version_comparison
    || version.saved_qmt_comparison
    || version.runtime_comparison
    || (version.matches_remote === true ? 'same' : (version.matches_remote === false ? 'different' : 'unknown'));
  const compareClass = projectUpdateCompareClass(qmtComparison, remote.error);
  const qmtMainVersion = runtimeVersion || latestQmtVersion || fileVersion || '--';
  const qmtDetails = [
    runtimeVersion ? `运行 ${runtimeVersion}` : (runtimeReported ? '运行时为空' : '运行未上报'),
    latestQmtVersion && latestQmtVersion !== runtimeVersion ? `已知 ${latestQmtVersion}` : '',
    fileVersion && fileVersion !== runtimeVersion && fileVersion !== latestQmtVersion ? `磁盘 ${fileVersion}` : '',
  ].filter(Boolean).join(' / ');
  const compareSource = version.compare_source === 'qmt_runtime'
    ? '按运行时判断'
    : (latestQmtVersion ? '按最近已知版本判断' : '缺少 QMT 上报');
  box.innerHTML = `
    <div class="update-version-item">
      <span>当前 QMT</span>
      <strong>${esc(qmtMainVersion)}</strong>
      <small>${esc(qmtDetails)}</small>
    </div>
    <div class="update-version-item">
      <span>远端</span>
      <strong>${esc(updateVersionLabel(remote))}</strong>
      <small>${esc(remoteUpdateDetail(remote))}</small>
    </div>
    <div class="update-version-item update-version-compare ${compareClass}">
      <span>状态</span>
      <strong>${esc(projectUpdateCompareText(qmtComparison, remote.error))}</strong>
      <small>${esc(compareSource)}</small>
    </div>`;
}

function renderUpdateVersionInfoLegacy(data) {
  const box = $('updateVersionInfo');
  if (!box) return;
  const version = data && data.version_status ? data.version_status : {};
  const current = version.current || {};
  const remote = version.remote || {};
  const compareClass = updateCompareClass(version.matches_remote);
  const remoteDetail = remoteUpdateDetail(remote);
  box.innerHTML = `
    <div class="update-version-item">
      <span>当前版本</span>
      <strong>${esc(updateVersionLabel(current))}</strong>
      <small>${esc(current.source ? `来源：${current.source}` : '未检测到本地版本号或更新记录')}</small>
    </div>
    <div class="update-version-item">
      <span>${esc(remoteUpdateSourceLabel(remote))}</span>
      <strong>${esc(updateVersionLabel(remote))}</strong>
      <small>${esc(remoteDetail)}</small>
    </div>
    <div class="update-version-item update-version-compare ${compareClass}">
      <span>版本对比</span>
      <strong>${esc(updateCompareText(version.matches_remote))}</strong>
      <small>${version.matches_remote === false ? '远端有不同版本' : '优先基于官网包版本判断，回退时基于 commit 判断'}</small>
    </div>`;
}

function projectUpdateCompareText(value, remoteError = '') {
  if (value === 'same') return '一致';
  if (value === 'newer' || value === 'different') return '可更新';
  if (value === 'older') return '本地较新';
  if (remoteError) return '远端不可达';
  return '无法判断';
}

function projectUpdateCompareClass(value, remoteError = '') {
  if (remoteError) return 'unknown';
  if (value === 'same') return 'match';
  if (value === 'newer' || value === 'different') return 'diff';
  return 'unknown';
}

function renderProjectUpdateVersionInfo(data) {
  const box = $('projectUpdateVersionInfo');
  if (!box) return;
  if (!data) {
    box.innerHTML = '<div class="update-version-empty">等待刷新</div>';
    return;
  }
  const version = data && data.version_info ? data.version_info : {};
  const local = version.local || {};
  const remote = version.remote || {};
  const projectRemoteVersion = remote.web_version
    ? `${remote.version || remote.core_version || '--'} / ${remote.web_version}`
    : (remote.version || remote.core_version || '--');
  const currentVersion = version.current_version || local.version || data && data.current_version || '--';
  const webVersion = version.web_version || version.frontend_version || '--';
  const browserFrontendVersion = FRONTEND_VERSION;
  const localDetail = local.matches_changelog === false
    ? `版本日志版本为 ${local.changelog_version || '--'}，与核心版本不一致`
    : `来源：${local.source || '本地项目'}`;
  const webDetail = webVersion !== browserFrontendVersion
    ? `前端 ${browserFrontendVersion} / 服务端 ${webVersion}`
    : `Web ${webVersion}`;
  const remoteDetail = remoteUpdateDetail(remote);
  const compareClass = projectUpdateCompareClass(version.comparison, remote.error);
  box.innerHTML = `
    <div class="update-version-item">
      <span>当前 Web</span>
      <strong>${esc(currentVersion)}</strong>
      <small>${esc(webVersion !== '--' ? webDetail : localDetail)}</small>
    </div>
    <div class="update-version-item">
      <span>远端</span>
      <strong>${esc(projectRemoteVersion)}</strong>
      <small>${esc(remote.version || remote.error ? remoteDetail : '未检查远端版本')}</small>
    </div>
    <div class="update-version-item update-version-compare ${compareClass}">
      <span>状态</span>
      <strong>${esc(projectUpdateCompareText(version.comparison, remote.error))}</strong>
      <small>${remote.error ? '远端不可达' : '官网优先'}</small>
    </div>`;
}

function renderProjectUpdateStatus(data) {
  state.projectUpdateStatus = data || null;
  const status = $('projectUpdateStatus');
  const select = $('projectRollbackBackupSelect');
  const backups = data && Array.isArray(data.backups) ? data.backups : [];
  const repoInput = $('projectUpdateRepoInput');
  const refInput = $('projectUpdateRefInput');
  const defaultRepo = (data && data.default_repo_url) || DEFAULT_UPDATE_REPO_URL;
  const defaultRef = (data && data.default_ref) || DEFAULT_UPDATE_REF;
  if (repoInput && !repoInput.value.trim()) repoInput.value = defaultRepo;
  if (refInput && !refInput.value.trim()) refInput.value = defaultRef;
  if (select) {
    select.innerHTML = backups.length
      ? backups.map((row) => {
          const version = row.version ? ` / ${row.version}` : '';
          const count = row.file_count ? ` / ${row.file_count} 文件` : '';
          const label = `${row.created_at_text || row.name}${version}${count}`;
          return `<option value="${esc(row.name)}">${esc(label)}</option>`;
        }).join('')
      : '<option value="">暂无项目备份</option>';
    select.disabled = !backups.length;
  }
  if (status) {
    if (!data) {
      status.textContent = '未加载项目更新状态';
      status.title = '';
    } else {
      const version = data.version_info || {};
      const remote = version.remote || {};
      const compareText = version.comparison ? projectUpdateCompareText(version.comparison, remote.error) : '';
      const parts = [
        data.ready ? '可更新' : '未就绪',
        data.current_version ? `当前 ${data.current_version}` : '',
        compareText || '',
        `备份 ${backups.length}`,
      ].filter(Boolean);
      if (data.errors && data.errors.length) parts.push(`错误：${data.errors.join('；')}`);
      if (data.warnings && data.warnings.length) parts.push(`提示：${data.warnings.join('；')}`);
      status.textContent = parts.join(' · ');
      status.title = JSON.stringify(data, null, 2);
    }
  }
  renderProjectUpdateVersionInfo(data);
  setProjectUpdateControlsBusy(false);
}

function handleProjectReload(reloadInfo, message) {
  if (!reloadInfo) return;
  const nextUrl = reloadInfo.next_url || window.location.href;
  log(message || 'Web 正在重启', { next_url: nextUrl });
  const delayMs = state.qmtUpdateProgress && state.qmtUpdateProgress.status === 'done' ? 4200 : 2600;
  window.setTimeout(() => {
    window.location.href = nextUrl || window.location.href;
  }, delayMs);
}

function projectReloadProgressText(data, actionText) {
  const reloadInfo = data && data.reload;
  const version = data && data.current_version ? `，当前版本 ${data.current_version}` : '';
  if (reloadInfo) return `${actionText}${version}。Web 服务即将重启，页面会自动跳转。`;
  return `${actionText}${version}。`;
}

function uploadProjectUpdateZip(formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/project-updates/upload');
    Object.entries(authHeaders()).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') xhr.setRequestHeader(key, value);
    });
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || typeof onProgress !== 'function') return;
      onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      let payload = null;
      try {
        payload = JSON.parse(xhr.responseText || '{}');
      } catch (error) {
        reject(new Error(`项目更新接口返回无法解析：${error.message}`));
        return;
      }
      if (xhr.status === 401 && webAuthEnabled()) {
        clearWebAuthToken();
        showWebAuthOverlay('请先登录');
      }
      if (!payload.ok) {
        reject(new Error((payload && payload.error) || `HTTP ${xhr.status}`));
        return;
      }
      resolve(payload.data);
    };
    xhr.onerror = () => reject(new Error('上传项目 zip 更新请求失败'));
    xhr.onabort = () => reject(new Error('上传项目 zip 更新请求已中断'));
    xhr.send(formData);
  });
}

async function refreshProjectUpdateStatus(options = {}) {
  const status = $('projectUpdateStatus');
  if (status) status.textContent = '正在检查项目更新状态...';
  const repoInput = $('projectUpdateRepoInput');
  const refInput = $('projectUpdateRefInput');
  const repoUrl = (repoInput && repoInput.value.trim()) || DEFAULT_UPDATE_REPO_URL;
  const ref = (refInput && refInput.value.trim()) || DEFAULT_UPDATE_REF;
  const remote = options.remote !== false;
  const data = await api(`/api/project-updates/status?repo_url=${encodeURIComponent(repoUrl)}&ref=${encodeURIComponent(ref)}&remote=${remote ? '1' : '0'}`);
  renderProjectUpdateStatus(data);
  if (options.log !== false) {
    log('Web 项目更新状态已刷新', {
      ready: !!data.ready,
      target_dir: data.target_dir || '',
      version: data.current_version || '',
    });
  }
  return data;
}

async function runProjectGithubUpdateFromUi(options = {}) {
  const repoInput = $('projectUpdateRepoInput');
  const refInput = $('projectUpdateRefInput');
  const repoUrl = (repoInput && repoInput.value.trim())
    || (state.projectUpdateStatus && state.projectUpdateStatus.default_repo_url)
    || DEFAULT_UPDATE_REPO_URL;
  const ref = (refInput && refInput.value.trim())
    || (state.projectUpdateStatus && state.projectUpdateStatus.default_ref)
    || DEFAULT_UPDATE_REF;
  if (repoInput && !repoInput.value.trim()) repoInput.value = repoUrl;
  if (refInput && !refInput.value.trim()) refInput.value = ref;
  if (!repoUrl) {
    log('官网和 GitHub 回退源均不可用，无法更新 Web 项目');
    return;
  }
  const versionInfo = state.versionInfo || {};
  const remoteInfo = versionInfo.remote || {};
  let confirmText = '确认从官网优先源更新当前 Web 项目并自动重启？本地配置、数据库和日志会保留；官网不可用时会回退 GitHub。';
  if (versionInfo.comparison === 'older') {
    confirmText = '当前本地版本显示比远端更新，继续会用远端当前内容覆盖 Web 项目。确认继续？本地配置、数据库和日志会保留。';
  } else if (remoteInfo.error) {
    confirmText = `当前版本探测失败：${remoteInfo.error}\n仍要尝试从官网优先源更新 Web 项目吗？`;
  }
  const confirmed = window.confirm(confirmText);
  if (!confirmed) return;
  openQmtUpdateProgress(
    'project-official',
    'Web 项目更新',
    '正在准备从官网优先源更新 Web 项目...'
  );
  state.versionUpdateBusy = true;
  setProjectUpdateControlsBusy(true);
  renderProjectVersion(state.versionInfo);
  try {
    setQmtUpdateProgressStep('download', '正在连接官网并下载 Web 项目发布包...');
    const data = await api('/api/project-updates/official', {
      method: 'POST',
      body: JSON.stringify({ site_url: DEFAULT_OFFICIAL_SITE_URL, repo_url: repoUrl, ref, reload: true }),
    });
    setQmtUpdateProgressStep('restart', data.reload ? 'Web 项目已替换，正在准备重启 Web 服务...' : 'Web 项目已替换，正在刷新页面状态...');
    renderProjectUpdateResult(data);
    alertUpdateNotice(data, { forceQmtRestart: false });
    finishQmtUpdateProgress(data, projectReloadProgressText(data, 'Web 项目更新完成'));
    log('Web 项目已从官网优先更新', {
      version: data.current_version || '',
      copied_files: data.copied_files || 0,
      source: options.source || 'settings',
    });
    handleProjectReload(data.reload, 'Web 项目已更新，正在重启');
  } catch (error) {
    failQmtUpdateProgress(error);
    throw error;
  } finally {
    state.versionUpdateBusy = false;
    setProjectUpdateControlsBusy(false);
    renderProjectVersion(state.versionInfo);
  }
}

async function uploadProjectZipUpdateFromUi() {
  const input = $('projectUpdateZipInput');
  const file = input && input.files && input.files[0];
  if (!file) {
    log('未选择项目 zip 文件，无法更新 Web 项目');
    return;
  }
  const confirmed = window.confirm('确认上传 zip 更新当前 Web 项目并自动重启？本地配置、数据库和日志会保留。');
  if (!confirmed) return;
  const formData = new FormData();
  formData.append('reload', '1');
  formData.append('file', file, file.name);
  openQmtUpdateProgress(
    'project-upload',
    'Web 项目 zip 更新',
    `正在上传项目源码 zip：${file.name}`
  );
  state.versionUpdateBusy = true;
  setProjectUpdateControlsBusy(true);
  renderProjectVersion(state.versionInfo);
  try {
    const data = await uploadProjectUpdateZip(formData, (loaded, total) => {
      const uploadPercent = total > 0 ? Math.round((loaded / total) * 100) : 0;
      const mapped = 8 + Math.min(34, Math.round(uploadPercent * 0.34));
      setQmtUpdateProgressStep('upload', `正在上传项目源码 zip：${uploadPercent}%`, mapped);
    });
    setQmtUpdateProgressStep('restart', data.reload ? 'Web 项目已替换，正在准备重启 Web 服务...' : 'Web 项目已替换，正在刷新页面状态...');
    renderProjectUpdateResult(data);
    alertUpdateNotice(data, { forceQmtRestart: false });
    finishQmtUpdateProgress(data, projectReloadProgressText(data, 'Web 项目 zip 更新完成'));
    log('Web 项目已通过 zip 更新', {
      version: data.current_version || '',
      copied_files: data.copied_files || 0,
    });
    handleProjectReload(data.reload, 'Web 项目 zip 更新完成，正在重启');
  } catch (error) {
    failQmtUpdateProgress(error);
    throw error;
  } finally {
    state.versionUpdateBusy = false;
    setProjectUpdateControlsBusy(false);
    renderProjectVersion(state.versionInfo);
  }
}

async function rollbackProjectUpdateFromUi() {
  const select = $('projectRollbackBackupSelect');
  const backup = select ? select.value : '';
  if (!backup) {
    log('没有可回滚的项目备份');
    return;
  }
  const confirmed = window.confirm(`确认回滚 Web 项目到备份 ${backup} 并自动重启？`);
  if (!confirmed) return;
  openQmtUpdateProgress(
    'project-rollback',
    'Web 项目回滚',
    `正在回滚 Web 项目到备份 ${backup}`
  );
  state.versionUpdateBusy = true;
  setProjectUpdateControlsBusy(true);
  renderProjectVersion(state.versionInfo);
  try {
    setQmtUpdateProgressStep('restore', '正在备份当前 Web 项目并恢复选中备份...');
    const data = await api('/api/project-updates/rollback', {
      method: 'POST',
      body: JSON.stringify({ backup, reload: true }),
    });
    setQmtUpdateProgressStep('restart', data.reload ? 'Web 项目已回滚，正在准备重启 Web 服务...' : 'Web 项目已回滚，正在刷新页面状态...');
    renderProjectUpdateResult(data);
    alertUpdateNotice(data, { forceQmtRestart: false });
    finishQmtUpdateProgress(data, projectReloadProgressText(data, 'Web 项目回滚完成'));
    log('Web 项目已回滚', { version: data.current_version || '', backup });
    handleProjectReload(data.reload, 'Web 项目已回滚，正在重启');
  } catch (error) {
    failQmtUpdateProgress(error);
    throw error;
  } finally {
    state.versionUpdateBusy = false;
    setProjectUpdateControlsBusy(false);
    renderProjectVersion(state.versionInfo);
  }
}

function renderUpdateStatus(data) {
  state.updateStatus = data || null;
  const status = $('updateStatus');
  const select = $('rollbackBackupSelect');
  const backups = data && Array.isArray(data.backups) ? data.backups : [];
  const repoInput = $('updateRepoInput');
  const refInput = $('updateRefInput');
  const defaultRepo = (data && data.default_repo_url) || DEFAULT_UPDATE_REPO_URL;
  const defaultRef = (data && data.default_ref) || DEFAULT_UPDATE_REF;
  if (repoInput && !repoInput.value.trim()) repoInput.value = defaultRepo;
  if (refInput && !refInput.value.trim()) refInput.value = defaultRef;
  if (select) {
    select.innerHTML = backups.length
      ? backups.map((row) => {
          const version = row.version ? ` / ${row.version}` : '';
          const label = `${row.created_at_text || row.name}${version}`;
          return `<option value="${esc(row.name)}">${esc(label)}</option>`;
        }).join('')
      : '<option value="">暂无备份</option>';
    select.disabled = !backups.length;
  }
  if (status) {
    if (!data) {
      status.textContent = '未加载更新状态';
      status.title = '';
    } else {
      const qmtCompare = data.version_status && data.version_status.qmt_version_comparison
        ? projectUpdateCompareText(data.version_status.qmt_version_comparison, (data.version_status.remote || {}).error)
        : '';
      const parts = [
        `${selectedAccount() || data.bridge_name || data.bridge_id || selectedBridge()}：${data.ready ? '可更新' : '未就绪'}`,
      ];
      if (data.advanced_mode) {
        parts.push(data.qmt_trade_dir ? '高级模式' : '缺少第二个 QMT 目录');
      }
      if (data.current_version) parts.push(`运行时 ${data.current_version}`);
      else parts.push(data.runtime_reported ? '运行时为空' : '运行未上报');
      if (qmtCompare) parts.push(qmtCompare);
      parts.push(`备份 ${backups.length}`);
      if (data.errors && data.errors.length) parts.push(`错误：${data.errors.join('；')}`);
      if (data.warnings && data.warnings.length) parts.push(`提示：${data.warnings.join('；')}`);
      status.textContent = parts.join(' · ');
      status.title = JSON.stringify(data, null, 2);
    }
  }
  renderUpdateVersionInfo(data);
  setUpdateControlsBusy(false);
}

async function refreshUpdateStatus(options = {}) {
  const status = $('updateStatus');
  if (status) status.textContent = '正在检查更新状态...';
  const repoInput = $('updateRepoInput');
  const refInput = $('updateRefInput');
  const repoUrl = (repoInput && repoInput.value.trim()) || DEFAULT_UPDATE_REPO_URL;
  const ref = (refInput && refInput.value.trim()) || DEFAULT_UPDATE_REF;
  const data = await api(`/api/updates/status?bridge_id=${encodeURIComponent(selectedBridge())}&repo_url=${encodeURIComponent(repoUrl)}&ref=${encodeURIComponent(ref)}`);
  renderUpdateStatus(data);
  if (options.log !== false) {
    log('更新状态已刷新', { bridge_id: data.bridge_id, ready: !!data.ready, python_dir: data.python_dir || '' });
  }
  return data;
}

function uploadQmtCoreZip(formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/updates/upload');
    Object.entries(authHeaders()).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') xhr.setRequestHeader(key, value);
    });
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || typeof onProgress !== 'function') return;
      onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      let payload = null;
      try {
        payload = JSON.parse(xhr.responseText || '{}');
      } catch (error) {
        reject(new Error(`更新接口返回无法解析：${error.message}`));
        return;
      }
      if (xhr.status === 401 && webAuthEnabled()) {
        clearWebAuthToken();
        showWebAuthOverlay('请先登录');
      }
      if (!payload.ok) {
        reject(new Error((payload && payload.error) || `HTTP ${xhr.status}`));
        return;
      }
      resolve(payload.data);
    };
    xhr.onerror = () => reject(new Error('上传 zip 更新请求失败'));
    xhr.onabort = () => reject(new Error('上传 zip 更新请求已中断'));
    xhr.send(formData);
  });
}

async function runGithubUpdateFromUi() {
  const repoInput = $('updateRepoInput');
  const refInput = $('updateRefInput');
  const repoUrl = (repoInput && repoInput.value.trim()) || (state.updateStatus && state.updateStatus.default_repo_url) || DEFAULT_UPDATE_REPO_URL;
  const ref = (refInput && refInput.value.trim()) || (state.updateStatus && state.updateStatus.default_ref) || DEFAULT_UPDATE_REF;
  if (repoInput && !repoInput.value.trim()) repoInput.value = repoUrl;
  if (refInput && !refInput.value.trim()) refInput.value = ref;
  if (!repoUrl) {
    log('官网和 GitHub 回退源均不可用，无法更新');
    return;
  }
  const confirmed = window.confirm('确认从官网优先源更新当前账号 QMT 目录中的核心代码？官网不可用时会回退 GitHub，更新完成后需要重启 QMT 桥接脚本。');
  if (!confirmed) return;
  openQmtUpdateProgress(
    'official',
    'QMT 核心更新',
    `正在从官网优先源更新 ${selectedAccount() || selectedBridge()} 的 QMT 核心包`
  );
  setUpdateControlsBusy(true);
  try {
    setQmtUpdateProgressStep('download', '正在连接官网并下载源码包...');
    const data = await api('/api/updates/official', {
      method: 'POST',
      body: JSON.stringify({ bridge_id: selectedBridge(), site_url: DEFAULT_OFFICIAL_SITE_URL, repo_url: repoUrl, ref }),
    });
    setQmtUpdateProgressStep('refresh', '核心包已替换，正在刷新更新状态...');
    renderUpdateResult(data);
    alertUpdateNotice(data, { forceQmtRestart: true });
    try {
      await refreshUpdateStatus({ log: false });
    } catch (refreshError) {
      log('核心更新后刷新状态失败', { error: refreshError.message });
    }
    finishQmtUpdateProgress(data);
    log('核心代码已从官网优先源更新', { bridge_id: data.bridge_id, version: data.current_version || '' });
  } catch (error) {
    failQmtUpdateProgress(error);
    throw error;
  } finally {
    setUpdateControlsBusy(false);
  }
}

async function uploadZipUpdateFromUi() {
  const input = $('updateZipInput');
  const file = input && input.files && input.files[0];
  if (!file) {
    log('未选择 zip 文件，无法更新');
    return;
  }
  const confirmed = window.confirm('确认上传 zip 并更新当前账号 QMT 目录中的核心代码？更新完成后需要重启 QMT 桥接脚本。');
  if (!confirmed) return;
  const formData = new FormData();
  formData.append('bridge_id', selectedBridge());
  formData.append('file', file, file.name);
  openQmtUpdateProgress(
    'upload',
    'QMT 核心 zip 更新',
    `正在上传 ${file.name}，目标 ${selectedAccount() || selectedBridge()} 的 QMT 核心包`
  );
  setUpdateControlsBusy(true);
  try {
    const data = await uploadQmtCoreZip(formData, (loaded, total) => {
      const uploadPercent = total > 0 ? Math.round((loaded / total) * 100) : 0;
      const mapped = 8 + Math.min(34, Math.round(uploadPercent * 0.34));
      setQmtUpdateProgressStep('upload', `正在上传源码 zip：${uploadPercent}%`, mapped);
    });
    setQmtUpdateProgressStep('refresh', '核心包已替换，正在刷新更新状态...');
    renderUpdateResult(data);
    alertUpdateNotice(data, { forceQmtRestart: true });
    try {
      await refreshUpdateStatus({ log: false });
    } catch (refreshError) {
      log('zip 更新后刷新状态失败', { error: refreshError.message });
    }
    finishQmtUpdateProgress(data);
    log('核心代码已通过 zip 更新', { bridge_id: data.bridge_id, version: data.current_version || '' });
  } catch (error) {
    failQmtUpdateProgress(error);
    throw error;
  } finally {
    setUpdateControlsBusy(false);
  }
}

async function rollbackUpdateFromUi() {
  const select = $('rollbackBackupSelect');
  const backup = select ? select.value : '';
  if (!backup) {
    log('没有可回滚的备份');
    return;
  }
  const confirmed = window.confirm(`确认回滚到备份 ${backup}？回滚完成后需要重启 QMT 桥接脚本。`);
  if (!confirmed) return;
  openQmtUpdateProgress(
    'rollback',
    'QMT 核心回滚',
    `正在回滚 ${selectedAccount() || selectedBridge()} 到备份 ${backup}`
  );
  setUpdateControlsBusy(true);
  try {
    setQmtUpdateProgressStep('restore', '正在备份当前核心并恢复选中备份...');
    const data = await api('/api/updates/rollback', {
      method: 'POST',
      body: JSON.stringify({ bridge_id: selectedBridge(), backup }),
    });
    setQmtUpdateProgressStep('refresh', '核心包已回滚，正在刷新更新状态...');
    renderUpdateResult(data);
    alertUpdateNotice(data, { forceQmtRestart: true });
    try {
      await refreshUpdateStatus({ log: false });
    } catch (refreshError) {
      log('核心回滚后刷新状态失败', { error: refreshError.message });
    }
    finishQmtUpdateProgress(data, `回滚完成，当前版本 ${data.current_version || '--'}。请按页面提示重启 QMT 入口脚本。`);
    log('核心代码已回滚', { bridge_id: data.bridge_id, version: data.current_version || '' });
  } catch (error) {
    failQmtUpdateProgress(error);
    throw error;
  } finally {
    setUpdateControlsBusy(false);
  }
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
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="normal">普通 QMT 请求</option><option value="trade">交易端请求</option></select></label>`;
  }
  if (meta.type === 'fixed_channel') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><input name="${esc(name)}" data-field="${esc(fieldName)}" type="text" value="normal" readonly><small>通用模式由 ctypes 单桥统一转发；高级模式全推由普通 QMT 推送</small></label>`;
  }
  if (meta.type === 'trade_channel') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="trade">交易端请求</option><option value="normal">普通 QMT 请求</option></select></label>`;
  }
  if (meta.type === 'financial_mode') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="filled">填充数据</option><option value="raw">原始数据</option></select></label>`;
  }
  if (meta.type === 'transport_mode') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="ctypes">通用模式（ctypes 单桥）</option><option value="lite">极致模式（纯 ctypes 自包含）</option><option value="lttx">高级模式（两个 QMT）</option></select></label>`;
  }
  if (meta.type === 'account_type') {
    const options = ACCOUNT_TYPE_OPTIONS
      .map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`)
      .join('');
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}">${options}</select></label>`;
  }
  if (meta.type === 'credit_query_action') {
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}"><option value="detail">信用明细</option><option value="subjects">可融券标的</option><option value="slo_code">可融券代码</option><option value="assure">担保品信息</option><option value="compacts">合约负债</option></select></label>`;
  }
  if (meta.type === 'credit_order_action') {
    const options = CREDIT_ORDER_ACTIONS.map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join('');
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}">${options}</select></label>`;
  }
  if (meta.type === 'order_action') {
    const options = Object.entries(DERIVATIVE_ORDER_ACTIONS_BY_ACCOUNT_TYPE)
      .flatMap(([accountType, actions]) => actions.map((item) => (
        `<option value="${esc(item.value)}">${esc(accountTypeLabel(accountType))} - ${esc(item.label)}</option>`
      )))
      .join('');
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}">${options}</select></label>`;
  }
  if (meta.type === 'price_type') {
    const options = PRICE_TYPE_OPTIONS
      .map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`)
      .join('');
    return `<label class="field${wide}"><span>${esc(meta.label)}</span><select name="${esc(name)}" data-field="${esc(fieldName)}">${options}</select></label>`;
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
  const endpointChannel = apiEndpointChannel(endpoint);
  const values = {
    bridge_id: selectedBridge(),
    account_id: selectedAccount(),
    account_type: selectedAccountType(),
    account_key: selectedAccountKey(),
    channel: endpointChannel || selectedChannel(),
    whole_quote_channel: 'normal',
    trade_channel: endpointChannel || selectedTradeChannel(),
    transport_mode: state.transportMode,
    side: 'buy',
    price_type: '11',
    since: '0',
    limit: '50',
    markets: 'SH,SZ',
    quote_subscribe_id: state.quoteSubscribeId || '',
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
    if (fieldName === 'channel' || fieldName === 'trade_channel') {
      const locked = !!endpointChannel;
      element.disabled = locked;
      element.title = locked ? '该接口按后端路由规则固定通道' : '';
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
  if (params.account_id && params.account_type && !params.account_key) {
    const currentAccountId = selectedAccount();
    const currentAccountType = selectedAccountType();
    if (String(params.account_id) === currentAccountId && normalizeAccountType(params.account_type) === currentAccountType) {
      params.account_key = selectedAccountKey();
    }
  }
  applyApiEndpointChannel(endpoint, params);
  if (['batch_order', 'credit_batch_order', 'future_batch_order', 'future_option_batch_order', 'stock_option_batch_order'].includes(endpoint.id)) {
    try {
      params.orders = params.orders_json ? JSON.parse(params.orders_json) : [];
      delete params.orders_json;
    } catch (error) {
      params.orders = [];
      params.orders_json_error = error.message;
    }
  }
  delete params.credit_order_action;
  if (endpoint.id === 'quote_subscribe_whole') {
    params.channel = 'normal';
    params.markets = String(params.markets || 'SH,SZ')
      .split(',')
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
  }
  if (endpoint.id === 'data_export') {
    try {
      params.user_param = params.user_param_json ? JSON.parse(params.user_param_json) : {};
      delete params.user_param_json;
    } catch (error) {
      params.user_param = {};
      params.user_param_json_error = error.message;
    }
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
  ['count', 'timeout', 'price_type', 'price', 'volume'].forEach((name) => {
    if (params[name] !== undefined && params[name] !== '') params[name] = Number(params[name]);
  });
  ['fill_data', 'iscomplete'].forEach((name) => {
    if (params[name] !== undefined && params[name] !== '') params[name] = ['1', 'true', 'yes', 'on'].includes(String(params[name]).toLowerCase());
  });
  if (params.incrementally === '') delete params.incrementally;
  if (endpoint.method === 'WS') {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') query.set(key, value);
    });
    return {
      method: endpoint.method,
      endpointId: endpoint.id,
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
      endpointId: endpoint.id,
      url: apiUrl(`${endpoint.path}${query.toString() ? `?${query.toString()}` : ''}`),
      headers: apiPreviewHeaders(),
      body: null,
    };
  }
  return {
    method: endpoint.method,
    endpointId: endpoint.id,
    url: apiUrl(endpoint.path),
    headers: apiPreviewHeaders(),
    body: params,
  };
}

function apiPreviewHeaders() {
  if (webAuthEnabled() && state.webAuthToken) {
    return { 'X-CFQUANT-WEB-TOKEN': maskApiKey(state.webAuthToken) };
  }
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

function apiDebugTimeoutMs(request) {
  let seconds = 0;
  if (request && request.body && request.body.timeout !== undefined && request.body.timeout !== '') {
    seconds = Number(request.body.timeout);
  }
  if (!seconds && request && request.url) {
    try {
      const parsed = new URL(request.url);
      seconds = Number(parsed.searchParams.get('timeout') || 0);
    } catch (error) {
      seconds = 0;
    }
  }
  if (!Number.isFinite(seconds) || seconds <= 0) return API_DEBUG_TIMEOUT_MS;
  return Math.max(8000, Math.min(120000, Math.round((seconds + 6) * 1000)));
}

function setApiDebugBusy(busy, label = '') {
  state.apiDebugBusy = !!busy;
  const form = $('apiForm');
  if (!form) return;
  const submit = form.querySelector('button[type="submit"]');
  const reset = $('apiResetBtn');
  if (submit) {
    const defaultLabel = submit.dataset.defaultLabel || submit.textContent || '发送请求';
    submit.disabled = !!busy;
    submit.classList.toggle('is-loading', !!busy);
    const labelNode = submit.querySelector('.api-submit-label');
    if (labelNode) labelNode.textContent = busy ? (label || '请求中') : defaultLabel;
  }
  if (reset) reset.disabled = !!busy;
}

function apiDebugElapsedMs(startedAt) {
  return Math.round(Math.max(0, performance.now() - startedAt));
}

function toLatencyMs(value) {
  const latency = Number(value);
  return Number.isFinite(latency) && latency >= 0 ? latency : null;
}

function formatLatencyMs(value) {
  const latency = toLatencyMs(value);
  if (latency === null) return '--';
  if (latency >= 1000) return `${(latency / 1000).toFixed(2)} s`;
  if (latency >= 100) return `${latency.toFixed(0)} ms`;
  if (latency >= 10) return `${latency.toFixed(1)} ms`;
  return `${latency.toFixed(2)} ms`;
}

function apiResponseLatency(payload, endpoint) {
  const data = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload.data
    : null;
  const accountQueryIds = new Set(['asset', 'positions', 'orders', 'trades']);
  const isAccountQuery = !!(endpoint && accountQueryIds.has(endpoint.id));
  const section = isAccountQuery && data && typeof data === 'object'
    ? data[endpoint.id]
    : null;
  const sectionLatency = toLatencyMs(section && typeof section === 'object'
    ? (section.refresh_latency_ms !== undefined ? section.refresh_latency_ms : section.latency_ms)
    : undefined);
  const cacheResponseLatency = toLatencyMs(data && data.cache && data.cache.response_latency_ms);
  if (isAccountQuery && (cacheResponseLatency !== null || sectionLatency !== null)) {
    return {
      latency: cacheResponseLatency !== null ? cacheResponseLatency : sectionLatency,
      source: cacheResponseLatency !== null ? '本次接口响应耗时' : `${endpoint.title}查询耗时`,
      refreshLatency: sectionLatency,
      cached: !!(section && section.cached),
      force: !!(data && data.cache && data.cache.force),
      cacheAgeMs: toLatencyMs(section && section.cache_age_ms),
    };
  }
  const topLevelLatency = toLatencyMs(data && typeof data === 'object' ? data.latency_ms : undefined);
  if (topLevelLatency !== null) {
    return {
      latency: topLevelLatency,
      source: '服务端处理耗时',
      cached: false,
    };
  }
  return null;
}

function renderApiResponseLatency(payload, endpoint, clientElapsedMs = null) {
  const panel = $('apiResponseLatency');
  const labelNode = $('apiResponseLatencyLabel');
  const valueNode = $('apiResponseLatencyValue');
  const metaNode = $('apiResponseLatencyMeta');
  if (!panel || !labelNode || !valueNode || !metaNode) return;
  const group = endpoint && (endpoint.group || '');
  const supportsLatency = endpoint && ['data', 'trade'].includes(group) && endpoint.method !== 'WS';
  const metrics = supportsLatency ? apiResponseLatency(payload, endpoint) : null;
  const clientElapsed = toLatencyMs(clientElapsedMs);
  if (!supportsLatency || (!metrics && clientElapsed === null)) {
    panel.classList.add('hidden');
    labelNode.textContent = '接口耗时';
    valueNode.textContent = '--';
    metaNode.textContent = '';
    return;
  }
  panel.classList.remove('hidden');
  labelNode.textContent = group === 'data' ? '数据接口耗时' : '交易接口耗时';
  if (metrics) {
    const cacheHit = metrics.cached && !metrics.force;
    valueNode.textContent = formatLatencyMs(metrics.latency);
    const details = [metrics.source];
    if (metrics.force) {
      details.push('本次强制刷新');
    } else if (metrics.cached) {
      details.push('来自账户缓存');
    }
    if (cacheHit && metrics.refreshLatency !== null && Math.abs(metrics.refreshLatency - metrics.latency) > 0.01) {
      details.push(`后台刷新 ${formatLatencyMs(metrics.refreshLatency)}`);
    }
    if (cacheHit && metrics.cacheAgeMs !== null) {
      details.push(`缓存年龄 ${formatLatencyMs(metrics.cacheAgeMs)}`);
    }
    if (clientElapsed !== null) details.push(`页面往返 ${formatLatencyMs(clientElapsed)}`);
    metaNode.textContent = details.join(' · ');
  } else {
    valueNode.textContent = formatLatencyMs(clientElapsed);
    metaNode.textContent = '页面往返耗时，服务端未返回 latency_ms';
  }
}

function apiDebugOutput(payload, request, startedAt, extra = {}) {
  const debug = {
    endpoint: request.endpointId || state.apiEndpointId,
    method: request.method,
    elapsed_ms: apiDebugElapsedMs(startedAt),
    ...extra,
  };
  if (typeof payload === 'string') {
    return `${payload}\n\n调试信息：${JSON.stringify(debug)}`;
  }
  return JSON.stringify({ ...payload, debug }, null, 2);
}

function isCurrentApiDebugRequest(seq, endpoint) {
  return seq === state.apiDebugRequestSeq && endpoint && state.apiEndpointId === endpoint.id;
}

async function sendApiDebugRequest(event) {
  event.preventDefault();
  if (state.apiDebugBusy) return;
  const request = currentApiRequest();
  const endpoint = apiEndpointById(state.apiEndpointId);
  const requestSeq = ++state.apiDebugRequestSeq;
  renderApiResponseLatency(null, endpoint);
  if (request.method === 'DOC') {
    return;
  }
  if (request.method === 'WS') {
    if (request.endpointId === 'ws_quotes') {
      const subscribeId = String(($('apiForm').elements.subscribe_id || {}).value || state.quoteSubscribeId || '').trim();
      if (!subscribeId) {
        $('apiResponseBox').textContent = JSON.stringify({
          ok: false,
          error: '网页调试不允许空订阅 ID 接收全部行情。请先订阅行情获取 subscribe_id，再连接推送。',
        }, null, 2);
        return;
      }
      state.quoteSubscribeId = subscribeId;
      connectQuoteWebSocket(subscribeId);
      return;
    }
    connectApiWebSocket(request);
    return;
  }
  if (request.body && (request.body.orders_json_error || request.body.user_param_json_error)) {
    $('apiResponseBox').textContent = JSON.stringify({ ok: false, error: request.body.orders_json_error || request.body.user_param_json_error }, null, 2);
    return;
  }
  const startedAt = performance.now();
  const timeoutMs = apiDebugTimeoutMs(request);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  setApiDebugBusy(true, request.method === 'WS' ? '连接中' : '请求中');
  if (isDownloadEndpoint(endpoint)) {
    request.body = request.body || {};
    request.body.job_id = request.body.job_id || newDownloadJobId(endpoint.id);
    beginDownloadProgress(request.body.job_id, request.body, endpoint);
    $('apiRequestPreview').textContent = JSON.stringify(request, null, 2);
    $('apiResponseBox').textContent = `请求中...\n已开始监听下载进度 job_id=${request.body.job_id}\n前端调试超时 ${Math.round(timeoutMs / 1000)} 秒`;
  } else if (isExportEndpoint(endpoint)) {
    request.body = request.body || {};
    request.body.job_id = request.body.job_id || newDownloadJobId(endpoint.id);
    beginExportProgress(request.body.job_id, request.body, endpoint);
    $('apiRequestPreview').textContent = JSON.stringify(request, null, 2);
    $('apiResponseBox').textContent = `导出中...\n任务 ID=${request.body.job_id}\n结果会写入 QMT 侧 result_path 指定目录。\n前端调试超时 ${Math.round(timeoutMs / 1000)} 秒`;
  } else {
    $('apiResponseBox').textContent = `请求中...\n前端调试超时 ${Math.round(timeoutMs / 1000)} 秒`;
  }
  try {
    const response = await fetch(request.url, {
      method: request.method,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
      },
      body: request.body ? JSON.stringify(request.body) : undefined,
      signal: controller.signal,
    });
    const text = await response.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch (error) {
      payload = text;
    }
    if (!isCurrentApiDebugRequest(requestSeq, endpoint)) return;
    renderApiResponseLatency(payload, endpoint, apiDebugElapsedMs(startedAt));
    $('apiResponseBox').textContent = apiDebugOutput(payload, request, startedAt, { http_status: response.status });
    handleApiDebugPayload(payload);
    if (isDownloadEndpoint(endpoint)) {
      finishDownloadRequest(payload);
    } else if (isExportEndpoint(endpoint)) {
      finishExportProgress(payload, payload && payload.ok === false ? new Error(payload.error || '导出失败') : null);
    }
  } catch (error) {
    const aborted = error && error.name === 'AbortError';
    const message = aborted
      ? `前端调试超时 ${Math.round(timeoutMs / 1000)} 秒，后端或 QMT 可能仍在处理。请先检查绑定状态里的 SH/SZ 子桥是否在线，再缩小调试接口范围或调大 timeout。`
      : error.message;
    if (!isCurrentApiDebugRequest(requestSeq, endpoint)) return;
    renderApiResponseLatency(null, endpoint, apiDebugElapsedMs(startedAt));
    $('apiResponseBox').textContent = apiDebugOutput({ ok: false, error: message }, request, startedAt, { aborted });
    if (isDownloadEndpoint(endpoint)) {
      finishDownloadRequest(null, error);
    } else if (isExportEndpoint(endpoint)) {
      finishExportProgress(null, error);
    }
  } finally {
    window.clearTimeout(timeoutId);
    setApiDebugBusy(false);
  }
}

function handleApiDebugPayload(payload) {
  if (!payload || !payload.ok || !payload.data) return;
  const endpoint = apiEndpointById(state.apiEndpointId);
  if (endpoint.id === 'quote_subscribe_whole' || endpoint.id === 'quote_subscribe_single') {
    const subscribeId = payload.data.subscribe_id || '';
    if (subscribeId) {
      resetQuoteLive(subscribeId, { active: false });
      const field = $('apiForm').elements.subscribe_id;
      if (field) field.value = subscribeId;
      $('apiResponseBox').textContent = `${JSON.stringify(payload, null, 2)}\n\n已获取订阅 ID。网页端不会自动连接全推行情，请点击“连接推送”后再查看实时行情。`;
    }
  }
  if (endpoint.id === 'quote_latest') {
    (payload.data.events || []).forEach((event) => handleQuoteEvent(event, { force: true }));
    scheduleQuoteRender(true);
  }
  if (endpoint.id === 'quote_unsubscribe') {
    stopQuoteLive({ unsubscribe: false });
  }
  if (isDownloadEndpoint(endpoint)) {
    const jobId = payload.data.job_id || state.downloadJobId || '';
    if (jobId) {
      state.downloadJobId = String(jobId);
      renderDownloadProgress();
      $('apiResponseBox').textContent = `${JSON.stringify(payload, null, 2)}\n\n已开始监听下载进度，job_id=${jobId}`;
    }
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
  if (state.quoteRenderTimer) {
    clearTimeout(state.quoteRenderTimer);
    state.quoteRenderTimer = null;
  }
  state.quoteRows.clear();
  state.quoteSeq = 0;
  state.quoteEventCount = 0;
  state.quoteSocketLogCount = 0;
  state.quoteSocketMessageCount = 0;
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
      const authQuery = authQueryString();
      const url = apiUrl(`/api/quotes/unsubscribe${authQuery ? `?${authQuery}` : ''}`);
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
      ...authHeaders(),
    },
    body: JSON.stringify(body),
    keepalive: !!options.beacon,
  }).catch((error) => log('行情订阅释放失败', { subscribe_id: subscribeId, error: error.message }));
}

function connectQuoteWebSocket(subscribeId = '') {
  subscribeId = String(subscribeId || state.quoteSubscribeId || '').trim();
  if (!subscribeId) {
    $('apiResponseBox').textContent = JSON.stringify({
      ok: false,
      error: '请先订阅行情获取 subscribe_id，再连接网页实时推送。',
    }, null, 2);
    return;
  }
  const params = new URLSearchParams();
  if (subscribeId) params.set('subscribe_id', subscribeId);
  state.quoteSubscribeId = subscribeId;
  state.quoteLiveActive = true;
  state.quoteSocketLogCount = 0;
  state.quoteSocketMessageCount = 0;
  state.quoteConnectionText = `连接中 #${subscribeId}`;
  renderQuoteLiveTable();
  const request = {
    method: 'WS',
    endpointId: 'ws_quotes',
    quoteStream: true,
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
  const append = (message, options = {}) => {
    const box = $('apiResponseBox');
    if (!options.force && request.quoteStream) {
      if (state.quoteSocketLogCount >= QUOTE_RESPONSE_LOG_LIMIT) return;
      state.quoteSocketLogCount += 1;
    }
    box.textContent = `${box.textContent}\n${message}`;
    if (box.textContent.length > 20000) {
      box.textContent = box.textContent.slice(-20000);
    }
    box.scrollTop = box.scrollHeight;
  };
  socket.onopen = () => {
    if (state.apiSocket !== socket) return;
    state.quoteConnectionText = state.quoteLiveActive ? '已连接' : '未订阅';
    renderQuoteLiveTable();
    append('WebSocket 已连接');
  };
  socket.onmessage = (event) => {
    if (state.apiSocket !== socket) return;
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'quote' && payload.event && state.quoteLiveActive) {
        state.quoteSocketMessageCount += 1;
        handleQuoteEvent(payload.event);
        if (request.quoteStream && state.quoteSocketMessageCount % 200 === 0) {
          append(`已接收 ${state.quoteSocketMessageCount} 条行情推送，实时表格按 ${QUOTE_RENDER_INTERVAL_MS}ms 限频刷新。`);
        }
        if (request.quoteStream) return;
      }
      append(JSON.stringify(payload, null, 2));
    } catch (error) {
      append(event.data);
    }
  };
  socket.onerror = () => {
    if (state.apiSocket !== socket) return;
    state.quoteConnectionText = '连接错误';
    if (request.quoteStream) state.quoteLiveActive = false;
    renderQuoteLiveTable();
    append('WebSocket 连接错误');
  };
  socket.onclose = () => {
    if (state.apiSocket !== socket) return;
    if (request.quoteStream) state.quoteLiveActive = false;
    state.quoteConnectionText = request.quoteStream && state.quoteSubscribeId ? '已断开' : '未订阅';
    state.apiSocket = null;
    renderQuoteLiveTable();
    append('WebSocket 已关闭');
  };
}

function handleQuoteEvent(event, options = {}) {
  if (!state.quoteLiveActive && !options.force) return;
  if (state.quoteSubscribeId && String(event.subscribe_id || '') !== String(state.quoteSubscribeId)) return;
  const panel = $('quoteLivePanel');
  if (panel) panel.classList.remove('hidden');
  state.quoteEventCount += 1;
  state.quoteSeq = Math.max(state.quoteSeq, Number(event.seq || state.quoteSeq || 0));
  const data = event.data || {};
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    Object.entries(data).slice(0, QUOTE_EVENT_PROCESS_LIMIT).forEach(([code, value]) => {
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
  scheduleQuoteRender(!!options.force);
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
    <td class="num ${signedClass(row.pct)}">${plain(row.pct)}</td>
    <td class="num">${plain(row.volume)}</td>
    <td>${plain(row.time)}</td>
  </tr>`).join('') || '<tr><td colspan="5">等待行情推送</td></tr>';
  if (status) {
    const subText = state.quoteSubscribeId ? ` #${state.quoteSubscribeId}` : '';
    status.textContent = `${state.quoteConnectionText}${state.quoteConnectionText.includes('#') ? '' : subText} · ${state.quoteEventCount || 0} 次推送 · ${rows.length} 条 / seq ${state.quoteSeq || 0}`;
  }
  const connectBtn = $('quoteConnectBtn');
  const stopBtn = $('quoteStopBtn');
  if (connectBtn) connectBtn.disabled = !state.quoteSubscribeId || state.quoteLiveActive;
  if (stopBtn) stopBtn.disabled = !state.quoteSubscribeId && !state.quoteLiveActive;
}

function scheduleQuoteRender(force = false) {
  if (force) {
    if (state.quoteRenderTimer) {
      clearTimeout(state.quoteRenderTimer);
      state.quoteRenderTimer = null;
    }
    renderQuoteLiveTable();
    return;
  }
  if (state.quoteRenderTimer) return;
  state.quoteRenderTimer = setTimeout(() => {
    state.quoteRenderTimer = null;
    renderQuoteLiveTable();
  }, QUOTE_RENDER_INTERVAL_MS);
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
    overview: '首页',
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
  syncHomeToolbar();
  if (view === 'settings') {
    setSettingsTab(state.settingsTab || localStorage.getItem(SETTINGS_TAB_KEY) || 'api-key', false);
  }
  if (state.appStarted && view === 'status') {
    refreshStatus().catch((error) => log('状态刷新失败', { error: error.message }));
  }
  if (state.appStarted && view === 'bindings') {
    renderBindingQmtScriptPanel();
    renderCachedBindingStatuses();
    if (!state.bindingStatusRefreshInFlight) {
      state.bindingStatusRefreshInFlight = true;
      refreshBindingStatuses()
        .catch((error) => log('绑定状态刷新失败', { error: error.message }))
        .finally(() => {
          state.bindingStatusRefreshInFlight = false;
        });
    }
  }
  if (state.appStarted && view === 'callbacks') {
    connectOrderCallbackSocket();
    refreshCallbacks().catch((error) => log('回调刷新失败', { error: error.message }));
  }
  if (view === 'tutorial') {
    renderActiveTutorialMermaid();
  }
}

function syncHomeToolbar() {
  const home = state.currentView === 'overview';
  const toolbar = document.querySelector('.toolbar');
  if (toolbar) toolbar.style.display = state.currentView === 'bindings' ? 'none' : '';
  const bridgeField = $('bridgeField');
  if (bridgeField) bridgeField.style.display = 'none';
  [
    'queryChannelField',
    'tradeChannelField',
    'refreshBtn',
    'autoRefreshField',
  ].forEach((id) => {
    const node = $(id);
    if (node) node.style.display = home ? 'none' : '';
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
    refreshAccount('orders', { force: true, subscribe: false }).catch((error) => log('委托刷新失败', { error: error.message }));
  }
}

function normalizeAccountType(value = 'STOCK') {
  const text = String(value || 'STOCK').trim().toUpperCase();
  if (['1', 'FUTURE', 'FUTURE_ACCOUNT'].includes(text)) return 'FUTURE';
  if (['3', 'CREDIT', 'CREDIT_ACCOUNT', 'MARGIN', 'MARGIN_TRADING'].includes(text)) return 'CREDIT';
  if (['5', 'FUTURE_OPTION', 'FUTURE_OPTION_ACCOUNT', 'FUTUREOPTION'].includes(text)) return 'FUTURE_OPTION';
  if (['6', 'STOCK_OPTION', 'STOCK_OPTION_ACCOUNT', 'STOCKOPTION', 'OPTION'].includes(text)) return 'STOCK_OPTION';
  return 'STOCK';
}

function accountTypeLabel(value = 'STOCK') {
  const accountType = normalizeAccountType(value);
  return ACCOUNT_TYPE_LABELS[accountType] || accountType;
}

function creditOrderActionMeta(value = '', side = 'buy') {
  let action = String(value || '').trim().toLowerCase();
  if (!action) action = String(side || '').trim().toLowerCase() === 'sell' ? 'credit_sell' : 'credit_buy';
  if (!action.startsWith('credit_')) action = `credit_${action}`;
  return CREDIT_ORDER_ACTION_MAP.get(action) || CREDIT_ORDER_ACTION_MAP.get('credit_buy');
}

function fillCreditOrderSelect(select) {
  if (!select || select.dataset.loaded === '1') return;
  select.innerHTML = CREDIT_ORDER_ACTIONS
    .map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`)
    .join('');
  select.dataset.loaded = '1';
}

function isDerivativeAccountType(value = 'STOCK') {
  return DERIVATIVE_ACCOUNT_TYPES.has(normalizeAccountType(value));
}

function derivativeActionsForAccountType(value = 'FUTURE') {
  return DERIVATIVE_ORDER_ACTIONS_BY_ACCOUNT_TYPE[normalizeAccountType(value)] || [];
}

function derivativeDefaultOrderAction(accountType = 'FUTURE', side = 'buy') {
  accountType = normalizeAccountType(accountType);
  const actions = derivativeActionsForAccountType(accountType);
  const wantedSide = String(side || '').trim().toLowerCase();
  return (actions.find((item) => item.side === wantedSide) || actions[0] || {}).value || '';
}

function derivativeOrderActionMeta(accountType = 'FUTURE', value = '', side = 'buy') {
  accountType = normalizeAccountType(accountType);
  const actions = derivativeActionsForAccountType(accountType);
  const map = DERIVATIVE_ORDER_ACTION_MAPS[accountType] || new Map();
  let action = String(value || '').trim().toLowerCase();
  if (!action) action = derivativeDefaultOrderAction(accountType, side);
  return map.get(action) || actions[0] || { value: '', label: '', side: '' };
}

function fillDerivativeOrderSelect(select, accountType = 'FUTURE') {
  if (!select) return;
  accountType = normalizeAccountType(accountType);
  if (select.dataset.loaded === '1' && select.dataset.accountType === accountType) return;
  select.innerHTML = derivativeActionsForAccountType(accountType)
    .map((item) => {
      const orderType = item.qmt_order_type !== undefined
        ? `${item.order_type}->${item.qmt_order_type}`
        : String(item.order_type);
      return `<option value="${esc(item.value)}">${esc(item.label)} (${esc(orderType)})</option>`;
    })
    .join('');
  select.dataset.loaded = '1';
  select.dataset.accountType = accountType;
}

function setTradeTabSide(side) {
  const value = String(side || 'buy').trim().toLowerCase() === 'sell' ? 'sell' : 'buy';
  document.querySelectorAll('.trade-tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.side === value);
  });
}

function syncCreditOrderControls() {
  const accountType = normalizeAccountType(state.accountType || 'STOCK');
  const credit = accountType === 'CREDIT';
  const derivative = isDerivativeAccountType(accountType);
  const orderForm = $('orderForm');
  const orderField = $('creditOrderActionField');
  const derivativeField = $('derivativeOrderActionField');
  const batchForm = $('batchOrderForm');
  const batchField = $('batchCreditOrderActionField');
  const batchDerivativeField = $('batchDerivativeOrderActionField');
  const orderFieldWasHidden = orderField && orderField.classList.contains('hidden');
  const derivativeFieldWasHidden = derivativeField && derivativeField.classList.contains('hidden');

  if (orderForm && orderForm.credit_action) {
    fillCreditOrderSelect(orderForm.credit_action);
    if (!orderForm.credit_action.value || (credit && orderFieldWasHidden)) {
      orderForm.credit_action.value = orderForm.side.value === 'sell' ? 'credit_sell' : 'credit_buy';
    }
    if (credit) {
      const action = creditOrderActionMeta(orderForm.credit_action.value, orderForm.side.value);
      orderForm.side.value = action.side;
      setTradeTabSide(action.side);
    }
  }
  if (orderField) orderField.classList.toggle('hidden', !credit);

  if (orderForm && orderForm.order_action) {
    const previousType = orderForm.order_action.dataset.accountType || '';
    fillDerivativeOrderSelect(orderForm.order_action, accountType);
    if (!orderForm.order_action.value || previousType !== accountType || (derivative && derivativeFieldWasHidden)) {
      orderForm.order_action.value = derivativeDefaultOrderAction(accountType, orderForm.side.value);
    }
    if (derivative) {
      const action = derivativeOrderActionMeta(accountType, orderForm.order_action.value, orderForm.side.value);
      if (action.side) {
        orderForm.side.value = action.side;
        setTradeTabSide(action.side);
      }
    }
  }
  if (derivativeField) derivativeField.classList.toggle('hidden', !derivative);

  if (batchForm && batchForm.credit_action) {
    fillCreditOrderSelect(batchForm.credit_action);
    if (!batchForm.credit_action.value) batchForm.credit_action.value = 'credit_buy';
  }
  if (batchField) batchField.classList.toggle('hidden', !credit);

  if (batchForm && batchForm.order_action) {
    const previousType = batchForm.order_action.dataset.accountType || '';
    fillDerivativeOrderSelect(batchForm.order_action, accountType);
    if (!batchForm.order_action.value || previousType !== accountType) {
      batchForm.order_action.value = derivativeDefaultOrderAction(accountType, orderForm ? orderForm.side.value : 'buy');
    }
  }
  if (batchDerivativeField) batchDerivativeField.classList.toggle('hidden', !derivative);

  if (orderForm) {
    const expected = buildOrderConfirmation(orderForm);
    if ($('orderHint')) $('orderHint').textContent = expected;
    if (orderForm.confirm_text && (!orderForm.confirm_text.value || orderForm.confirm_text.value === state.lastOrderConfirm)) {
      orderForm.confirm_text.value = expected;
    }
    state.lastOrderConfirm = expected;
  }
  if (batchForm) updateBatchOrderHint();
}

function makeAccountKey(accountId, accountType = 'STOCK', bridgeId = 'default') {
  const id = String(accountId || '').trim();
  if (!id) return '';
  return `${String(bridgeId || 'default').trim()}:${normalizeAccountType(accountType)}:${id}`;
}

function accountConfigKey(rawKey, config = {}) {
  return String((config && config.account_key) || rawKey || '').trim()
    || makeAccountKey(config.account_id, config.account_type, config.bridge_id || state.defaultBridgeId || 'default');
}

function accountPairDisplayName(accountKey, accountId = '', accountType = 'STOCK', bridgeId = '') {
  accountKey = String(accountKey || '').trim();
  accountId = String(accountId || '').trim();
  accountType = normalizeAccountType(accountType || 'STOCK');
  bridgeId = String(bridgeId || state.defaultBridgeId || 'default').trim();
  const pairs = state.accountPairs || {};
  const directKeys = [accountKey, makeAccountKey(accountId, accountType, bridgeId), accountId].filter(Boolean);
  for (const key of directKeys) {
    const pair = pairs[key];
    if (pair && typeof pair === 'object') {
      const name = String(pair.display_name || pair.account_name || '').trim();
      if (name) return name;
    }
  }
  for (const [rawKey, pair] of Object.entries(pairs)) {
    if (!pair || typeof pair !== 'object') continue;
    const pairAccountType = normalizeAccountType(pair.account_type || 'STOCK');
    const pairBridgeId = String(pair.bridge_id || state.defaultBridgeId || 'default').trim();
    const pairAccountId = String(pair.account_id || rawKey || '').trim();
    const pairKey = accountConfigKey(rawKey, pair);
    const sameKey = accountKey && pairKey === accountKey;
    const sameAccount = accountId && pairAccountId === accountId && pairAccountType === accountType && (!bridgeId || pairBridgeId === bridgeId);
    if (sameKey || sameAccount) {
      const name = String(pair.display_name || pair.account_name || '').trim();
      if (name) return name;
    }
  }
  return '';
}

function normalizeMarketRoutes(config = {}) {
  const raw = config && typeof config === 'object'
    ? (config.market_bridges || config.market_routes || {})
    : {};
  const routes = {};
  ['SH', 'SZ'].forEach((market) => {
    const row = (raw && (raw[market] || raw[market.toLowerCase()])) || {};
    routes[market] = row && typeof row === 'object'
      ? {
        market,
        bridge_id: String(row.bridge_id || row.id || '').trim(),
        qmt_dir: String(row.qmt_dir || row.python_dir || '').trim(),
        enabled: row.enabled !== false,
      }
      : { market, bridge_id: '', qmt_dir: '', enabled: true };
  });
  return routes;
}

function isMarketRoutingEnabled(config = {}) {
  if (!config || typeof config !== 'object') return false;
  if (config.market_routing_enabled === true) return true;
  if (String(config.market_routing_enabled || '').toLowerCase() === 'true') return true;
  const routes = normalizeMarketRoutes(config);
  return Object.values(routes).some((route) => route.bridge_id || route.qmt_dir);
}

function marketRouteSummary(config = {}) {
  if (!isMarketRoutingEnabled(config)) return '';
  const routes = normalizeMarketRoutes(config);
  return ['SH', 'SZ'].map((market) => {
    const route = routes[market] || {};
    return `${market}: ${route.bridge_id || '自动'}${route.qmt_dir ? ` / ${route.qmt_dir}` : ''}`;
  }).join(' | ');
}

function mergeSavedAccountDisplayName({ accountKey, accountId, accountType = 'STOCK', bridgeId = '', displayName = '', account = null, qmtDir = '', qmtTradeDir = '', mode = 'ctypes', dataProvider = false, marketRoutingEnabled = false, marketBridges = null }) {
  accountId = String(accountId || (account && account.account_id) || '').trim();
  accountType = normalizeAccountType(accountType || (account && account.account_type) || 'STOCK');
  bridgeId = String(bridgeId || (account && account.bridge_id) || state.defaultBridgeId || 'default').trim();
  accountKey = String(accountKey || (account && account.account_key) || makeAccountKey(accountId, accountType, bridgeId)).trim();
  displayName = String(displayName == null ? ((account && (account.display_name || account.account_name)) || '') : displayName).trim();
  if (!accountId || !accountKey) return;

  const currentConfigs = state.accountConfigs || {};
  const currentConfig = currentConfigs[accountKey] || {};
  state.accountConfigs = {
    ...currentConfigs,
    [accountKey]: {
      ...currentConfig,
      ...(account && typeof account === 'object' ? account : {}),
      account_key: accountKey,
      account_id: accountId,
      account_type: accountType,
      bridge_id: bridgeId,
      display_name: displayName,
      qmt_dir: (account && account.qmt_dir) || currentConfig.qmt_dir || qmtDir || '',
      qmt_trade_dir: (account && account.qmt_trade_dir) || currentConfig.qmt_trade_dir || qmtTradeDir || '',
      mode: (account && account.mode) || currentConfig.mode || mode || 'ctypes',
      data_provider: (account && Object.prototype.hasOwnProperty.call(account, 'data_provider'))
        ? !!account.data_provider
        : (Object.prototype.hasOwnProperty.call(currentConfig, 'data_provider') ? !!currentConfig.data_provider : !!dataProvider),
      market_routing_enabled: (account && Object.prototype.hasOwnProperty.call(account, 'market_routing_enabled'))
        ? !!account.market_routing_enabled
        : (Object.prototype.hasOwnProperty.call(currentConfig, 'market_routing_enabled') ? !!currentConfig.market_routing_enabled : !!marketRoutingEnabled),
      market_bridges: (account && account.market_bridges)
        || marketBridges
        || currentConfig.market_bridges
        || {},
    },
  };

  const currentPairs = state.accountPairs || {};
  const currentPair = currentPairs[accountKey] && typeof currentPairs[accountKey] === 'object' ? currentPairs[accountKey] : {};
  state.accountPairs = {
    ...currentPairs,
    [accountKey]: {
      ...currentPair,
      account_key: accountKey,
      account_id: accountId,
      account_type: accountType,
      bridge_id: bridgeId,
      display_name: displayName,
      market_routing_enabled: (account && Object.prototype.hasOwnProperty.call(account, 'market_routing_enabled'))
        ? !!account.market_routing_enabled
        : !!marketRoutingEnabled,
      market_bridges: (account && account.market_bridges) || marketBridges || currentPair.market_bridges || {},
    },
  };
}

function findAccountConfigByKey(accountKey) {
  accountKey = String(accountKey || '').trim();
  if (!accountKey) return null;
  const direct = state.accountConfigs && state.accountConfigs[accountKey];
  if (direct) return direct;
  return accountConfigEntries().find((item) => item.accountKey === accountKey)?.config || null;
}

function findAccountEntryById(accountId, accountType = '') {
  accountId = String(accountId || '').trim();
  const wantedType = accountType ? normalizeAccountType(accountType) : '';
  return accountConfigEntries().find(({ accountId: id, accountType: type }) => (
    id === accountId && (!wantedType || type === wantedType)
  )) || null;
}

function selectedAccountInfo() {
  const select = $('accountInput');
  const selectedKey = String((select && select.value) || state.accountKey || '').trim();
  const config = findAccountConfigByKey(selectedKey);
  if (config) {
    const accountType = normalizeAccountType(config.account_type || 'STOCK');
    const bridgeId = config.bridge_id || state.defaultBridgeId || 'default';
    return {
      accountKey: accountConfigKey(selectedKey, config),
      accountId: String(config.account_id || '').trim(),
      accountType,
      bridgeId,
      config,
    };
  }
  const fallbackId = String(state.accountId || state.defaultAccountId || '').trim();
  const fallbackType = normalizeAccountType(state.accountType || state.defaultAccountType || 'STOCK');
  const fallbackBridge = state.bridgeId || state.defaultBridgeId || 'default';
  return {
    accountKey: selectedKey || makeAccountKey(fallbackId, fallbackType, fallbackBridge),
    accountId: fallbackId,
    accountType: fallbackType,
    bridgeId: fallbackBridge,
    config: null,
  };
}

function loadAccountPairs() {
  const pairs = {};
  Object.entries(state.accountPairs || {}).forEach(([rawKey, pair]) => {
    if (pair && typeof pair === 'object') {
      const key = accountConfigKey(rawKey, pair);
      pairs[key] = pair.bridge_id;
      if (pair.account_id && !pairs[pair.account_id]) pairs[pair.account_id] = pair.bridge_id;
    } else {
      pairs[rawKey] = pair;
    }
  });
  if (Object.keys(pairs).length) return pairs;
  try {
    const value = JSON.parse(localStorage.getItem(ACCOUNT_PAIR_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch (error) {
    return {};
  }
}

function bindingEntriesFromState() {
  const configEntries = accountConfigEntries().map((item) => ({ ...item, kind: 'pair' }));
  const known = new Set(configEntries.map((item) => item.accountKey));
  const pairEntries = accountPairEntries()
    .filter((item) => !known.has(item.accountKey))
    .map((item) => ({
      ...item,
      kind: 'pair',
      config: {
        account_id: item.accountId,
        account_type: item.accountType,
        account_key: item.accountKey,
        bridge_id: item.bridgeId,
        display_name: item.displayName || '',
      },
    }));
  return [...configEntries, ...pairEntries].filter((item) => item.accountId);
}

function saveAccountConfigCache(data = {}) {
  const cache = {
    saved_at: Date.now(),
    default_account_id: data.default_account_id || state.defaultAccountId || '',
    default_account_type: normalizeAccountType(data.default_account_type || state.defaultAccountType || 'STOCK'),
    default_account_key: data.default_account_key || state.defaultAccountKey || '',
    default_bridge_id: data.default_bridge_id || state.defaultBridgeId || 'default',
    bridges: data.bridges || state.bridges || {},
    account_pairs: data.account_pairs || state.accountPairs || {},
    account_configs: data.account_configs || state.accountConfigs || {},
    binding_status_snapshot: data.binding_status_snapshot || state.bindingStatusSnapshot || null,
    setup: data.setup || state.setup || null,
  };
  try {
    localStorage.setItem(ACCOUNT_CONFIG_CACHE_KEY, JSON.stringify(cache));
  } catch (error) {
    log('账号配置缓存保存失败', { error: error.message });
  }
}

function loadAccountConfigCache() {
  try {
    const cache = JSON.parse(localStorage.getItem(ACCOUNT_CONFIG_CACHE_KEY) || '{}');
    return cache && typeof cache === 'object' ? cache : null;
  } catch (error) {
    return null;
  }
}

function clearAccountConfigCache() {
  localStorage.removeItem(ACCOUNT_CONFIG_CACHE_KEY);
}

function hydrateAccountConfigFromCache() {
  const cache = loadAccountConfigCache();
  if (!cache || !cache.account_configs) return false;
  state.defaultAccountId = cache.default_account_id || state.defaultAccountId || '';
  state.defaultAccountType = normalizeAccountType(cache.default_account_type || state.defaultAccountType || 'STOCK');
  state.defaultAccountKey = cache.default_account_key || state.defaultAccountKey || '';
  state.defaultBridgeId = cache.default_bridge_id || state.defaultBridgeId || 'default';
  state.bridges = cache.bridges || state.bridges || {};
  state.accountPairs = cache.account_pairs || state.accountPairs || {};
  state.accountConfigs = cache.account_configs || state.accountConfigs || {};
  state.bindingStatusSnapshot = cache.binding_status_snapshot || state.bindingStatusSnapshot || null;
  state.setup = cache.setup || state.setup || null;
  return true;
}

function accountPairEntries() {
  return Object.entries(state.accountPairs || {})
    .map(([rawKey, pair]) => {
      const bridgeId = pair && typeof pair === 'object' ? pair.bridge_id : pair;
      const accountId = pair && typeof pair === 'object' ? pair.account_id : rawKey;
      const accountType = normalizeAccountType(pair && typeof pair === 'object' ? pair.account_type : 'STOCK');
      const displayName = pair && typeof pair === 'object' ? String(pair.display_name || pair.account_name || '').trim() : '';
      const accountKey = pair && typeof pair === 'object'
        ? accountConfigKey(rawKey, pair)
        : makeAccountKey(accountId, accountType, bridgeId);
      return {
        accountKey,
        accountId: String(accountId || '').trim(),
        accountType,
        bridgeId: String(bridgeId || '').trim(),
        displayName,
      };
    })
    .filter((item) => item.accountId && item.bridgeId);
}

function accountConfigEntries() {
  return Object.entries(state.accountConfigs || {})
    .map(([rawKey, config]) => {
      const row = config && typeof config === 'object' ? config : {};
      const accountType = normalizeAccountType(row.account_type || 'STOCK');
      const bridgeId = row.bridge_id || state.defaultBridgeId || 'default';
      const accountId = String(row.account_id || rawKey || '').trim();
      const accountKey = accountConfigKey(rawKey, row);
      const pairDisplayName = accountPairDisplayName(accountKey, accountId, accountType, bridgeId);
      const displayName = String(row.display_name || row.account_name || pairDisplayName || '').trim();
      return {
        accountKey,
        accountId,
        accountType,
        bridgeId,
        displayName,
        config: displayName && !row.display_name ? { ...row, display_name: displayName } : row,
      };
    })
    .filter((item) => item.accountId);
}

function activeAccountMode() {
  const info = selectedAccountInfo();
  const config = info.config;
  return state.accountRouteMode
    || (config && config.mode)
    || state.transportMode
    || 'ctypes';
}

function preferredAccountMode() {
  const info = selectedAccountInfo();
  const config = info.config;
  return (config && config.mode)
    || state.transportMode
    || 'ctypes';
}

function shouldUseLttxStatus() {
  return preferredAccountMode() === 'lttx';
}

function bridgeIdForAccount(accountId, accountType = state.accountType) {
  accountId = String(accountId || '').trim();
  const entry = findAccountEntryById(accountId, accountType);
  const config = entry ? entry.config : null;
  const pairBridge = entry ? entry.bridgeId : (accountId ? loadAccountPairs()[accountId] : '');
  return (config && config.bridge_id)
    || pairBridge
    || state.defaultBridgeId
    || 'default';
}

async function saveAccountConfigRequest(body) {
  try {
    return await api('/api/account-config', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (error.status !== 404 && error.message !== 'not found') {
      throw error;
    }
    const legacyBridgeId = bridgeIdForAccount(body.account_id, body.account_type || 'STOCK') || state.defaultBridgeId || 'default';
    const data = await api('/api/account-pairs', {
      method: 'POST',
      body: JSON.stringify({
        account_id: body.account_id,
        account_type: body.account_type || 'STOCK',
        account_key: body.account_key || '',
        bridge_id: legacyBridgeId,
        display_name: body.display_name || '',
      }),
    });
    log('当前 Web 后端未加载账号配置接口，已按旧账号绑定保存；重启 Web 后可保存 QMT 目录、模式和共享行情源', {
      account_id: body.account_id,
      bridge_id: legacyBridgeId,
    });
    return {
      ...data,
      account: data.account || {
        account_id: body.account_id,
        account_type: body.account_type || 'STOCK',
        account_key: body.account_key || makeAccountKey(body.account_id, body.account_type || 'STOCK', legacyBridgeId),
        bridge_id: legacyBridgeId,
        display_name: body.display_name || '',
        qmt_dir: body.qmt_dir || '',
        qmt_trade_dir: body.qmt_trade_dir || '',
        mode: body.mode || 'ctypes',
        data_provider: !!body.data_provider,
      },
      account_pairs: data.account_pairs || state.accountPairs || {},
      account_configs: data.account_configs || state.accountConfigs || {},
      bridges: data.bridges || state.bridges || {},
      setup: data.setup || state.setup,
      legacy_fallback: true,
    };
  }
}

async function deleteAccountConfigRequest(accountId, accountType = 'STOCK', accountKey = '') {
  try {
    return await api('/api/account-config/delete', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId, account_type: accountType, account_key: accountKey }),
    });
  } catch (error) {
    if (error.status !== 404 && error.message !== 'not found') {
      throw error;
    }
    const data = await api('/api/account-pairs/delete', {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId, account_type: accountType, account_key: accountKey }),
    });
    log('当前 Web 后端未加载账号配置删除接口，已按旧账号绑定删除；重启 Web 后完整配置删除会生效', {
      account_id: accountId,
    });
    const nextConfigs = { ...(state.accountConfigs || {}) };
    delete nextConfigs[accountKey || accountId];
    return {
      ...data,
      account_pairs: data.account_pairs || {},
      account_configs: data.account_configs || nextConfigs,
      setup: data.setup || state.setup,
      legacy_fallback: true,
    };
  }
}

function renderAccountSelect(defaultAccountId = state.defaultAccountId) {
  const select = $('accountInput');
  if (!select) return;
  const current = String(state.accountKey || select.value || '').trim();
  const accountMap = new Map();
  const defaultId = String(defaultAccountId || '').trim();
  const defaultKey = String(state.defaultAccountKey || '').trim();
  const defaultBridgeId = state.defaultBridgeId || 'default';

  if (defaultId) {
    const key = defaultKey || makeAccountKey(defaultId, state.defaultAccountType || 'STOCK', defaultBridgeId);
    accountMap.set(key, {
      accountId: defaultId,
      accountType: normalizeAccountType(state.defaultAccountType || 'STOCK'),
      bridgeId: loadAccountPairs()[key] || loadAccountPairs()[defaultId] || defaultBridgeId,
      defaultAccount: true,
    });
  }
  accountPairEntries().forEach(({ accountKey, accountId, accountType, bridgeId, displayName }) => {
    accountMap.set(accountKey, {
      accountId,
      accountType,
      bridgeId,
      defaultAccount: accountKey === defaultKey || (!defaultKey && accountId === defaultId),
      name: displayName,
    });
  });
  accountConfigEntries().forEach(({ accountKey, accountId, accountType, displayName, config }) => {
    accountMap.set(accountKey, {
      accountId,
      accountType,
      bridgeId: config.bridge_id || loadAccountPairs()[accountKey] || loadAccountPairs()[accountId] || defaultBridgeId,
      defaultAccount: accountKey === defaultKey || (!defaultKey && accountId === defaultId),
      mode: config.mode || 'ctypes',
      provider: !!config.data_provider,
      marketRouting: isMarketRoutingEnabled(config),
      name: displayName,
    });
  });
  const options = Array.from(accountMap.entries()).map(([accountKey, info]) => {
    const modeLabel = transportModeLabel(info.mode, true);
    const providerLabel = info.provider ? '，数据源' : '';
    const typeLabel = accountTypeLabel(info.accountType);
    const bridgeName = (state.bridges && state.bridges[info.bridgeId] && state.bridges[info.bridgeId].name) || info.bridgeId || 'default';
    const suffix = info.defaultAccount
      ? `（默认，${typeLabel}，${modeLabel}${providerLabel}，${bridgeName}）`
      : `（${typeLabel}，${modeLabel}${providerLabel}，${bridgeName}）`;
    const label = info.name || info.accountId;
    return `<option value="${plain(accountKey)}">${plain(`${label} / ${info.accountId} ${suffix}`)}</option>`;
  }).join('');

  select.innerHTML = options || '<option value="">暂无可用账号</option>';
  const selected = accountMap.has(current)
    ? current
    : (defaultKey && accountMap.has(defaultKey) ? defaultKey : (accountMap.keys().next().value || ''));
  select.value = selected;
  const info = accountMap.get(selected) || {};
  state.accountKey = selected;
  state.accountId = info.accountId || '';
  state.accountType = normalizeAccountType(info.accountType || 'STOCK');
  state.accountRouteMode = (info && info.mode) || state.transportMode || 'ctypes';
  state.accountRouteFallback = false;
  syncCreditOrderControls();
}

function saveAccountPairs(pairs) {
  localStorage.setItem(ACCOUNT_PAIR_KEY, JSON.stringify(pairs || {}));
}

function bridgeOptionExists(bridgeId) {
  const select = $('bridgeSelect');
  if (!select) return false;
  return Array.from(select.options).some((option) => option.value === bridgeId);
}

function renderAccountPairs() {
  const overviewList = $('accountPairList');
  const bindingList = $('bindingAccountConfigList');
  const configEntries = accountConfigEntries().map(({ accountKey, accountId, accountType, bridgeId, config }) => ({
    accountKey,
    accountId,
    accountType,
    bridgeId: config.bridge_id || bridgeId,
    config,
  }));
  const seen = new Set(configEntries.map((item) => item.accountKey));
  const legacyEntries = accountPairEntries()
    .filter(({ accountKey }) => !seen.has(accountKey))
    .map(({ accountKey, accountId, accountType, bridgeId }) => ({
      accountKey,
      accountId,
      accountType,
      bridgeId,
      config: { account_key: accountKey, account_id: accountId, account_type: accountType, bridge_id: bridgeId, mode: 'ctypes', qmt_dir: '', data_provider: false },
    }));
  const entries = [...configEntries, ...legacyEntries].filter((item) => item.accountId);
  renderAccountSelect();
  $('accountPairCount').textContent = `${entries.length} 个账号`;
  if (overviewList) overviewList.innerHTML = '';
  if (bindingList) bindingList.innerHTML = '';
  if (!entries.length) {
    const empty = document.createElement('div');
    empty.className = 'metric-note';
    empty.textContent = '暂无账号配置';
    if (overviewList) overviewList.appendChild(empty.cloneNode(true));
    if (bindingList) bindingList.appendChild(empty);
    return;
  }
  entries.forEach(({ accountKey, accountId, accountType, bridgeId, config }) => {
    const row = document.createElement('div');
    row.className = 'pair-row';
    const label = document.createElement('span');
    const modeLabel = transportModeLabel(config.mode);
    const providerLabel = config.data_provider ? ' / 共享行情源' : '';
    const bridgeName = (state.bridges && state.bridges[bridgeId] && state.bridges[bridgeId].name) || bridgeId || 'default';
    label.textContent = `${accountId} / ${accountTypeLabel(accountType)} / ${bridgeName} / ${modeLabel}${providerLabel}`;
    const useBtn = document.createElement('button');
    useBtn.type = 'button';
    useBtn.textContent = '使用';
    useBtn.dataset.accountKey = accountKey;
    useBtn.dataset.accountId = accountId;
    useBtn.dataset.accountType = accountType;
    useBtn.dataset.bridgeId = bridgeId;
    row.appendChild(label);
    row.appendChild(useBtn);
    if (overviewList) overviewList.appendChild(row);

    if (bindingList) {
      const configRow = document.createElement('div');
      configRow.className = 'config-row';
      const info = document.createElement('div');
      info.className = 'config-info';
      const strong = document.createElement('strong');
      strong.textContent = `${accountId} / ${accountTypeLabel(accountType)}`;
      const summary = document.createElement('div');
      summary.className = 'config-summary';
      const modeLine = document.createElement('small');
      modeLine.textContent = `模式：${modeLabel}${providerLabel}`;
      const dirLine = document.createElement('small');
      dirLine.textContent = config.qmt_dir
        ? `QMT 核心目录：${config.qmt_dir}`
        : 'QMT 核心目录未填写，自动复制和自动更新不可用';
      summary.appendChild(modeLine);
      summary.appendChild(dirLine);
      const marketSummary = marketRouteSummary(config);
      if (marketSummary) {
        const marketLine = document.createElement('small');
        marketLine.textContent = `市场路由：${marketSummary}`;
        summary.appendChild(marketLine);
      }
      info.appendChild(strong);
      info.appendChild(summary);
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.textContent = '编辑';
      editBtn.dataset.accountKey = accountKey;
      editBtn.dataset.accountId = accountId;
      editBtn.dataset.accountType = accountType;
      editBtn.dataset.bridgeId = bridgeId;
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.textContent = '删除';
      deleteBtn.dataset.accountKey = accountKey;
      deleteBtn.dataset.accountId = accountId;
      deleteBtn.dataset.accountType = accountType;
      deleteBtn.dataset.bridgeId = bridgeId;
      deleteBtn.dataset.action = 'delete-account';
      configRow.appendChild(info);
      configRow.appendChild(editBtn);
      configRow.appendChild(deleteBtn);
      bindingList.appendChild(configRow);
    }
  });
}

function renderBindingEmptyRows() {
  const body = $('bindingStatusBody');
  const overviewBody = $('overviewBindingBody');
  if (body) {
    body.innerHTML = `<tr class="binding-empty-row"><td colspan="9">
      <div class="binding-empty">
        <strong>暂无账号绑定</strong>
        <span>添加账号后，这里会显示绑定信息、运行状态和验证入口。</span>
        <button class="primary" type="button" data-binding-action="add">添加绑定</button>
      </div>
    </td></tr>`;
  }
  if (overviewBody) overviewBody.innerHTML = '<tr><td colspan="5">暂无账号配置</td></tr>';
  if ($('overviewBindingCount')) $('overviewBindingCount').textContent = '0 组';
  if ($('bindingCount')) $('bindingCount').textContent = '0 个绑定';
  renderPairVerification(null);
}

function renderBindingRows(rows) {
  const body = $('bindingStatusBody');
  const overviewBody = $('overviewBindingBody');
  if (body) {
    body.innerHTML = rows.map(({ item, status, error, pending, stale }) => bindingStatusRowHtml(item, status, error, true, { pending, stale })).join('');
    if ($('bindingCount')) $('bindingCount').textContent = `${rows.length} 个绑定`;
  }
  if (overviewBody) {
    const overviewRows = rows.filter(({ item }) => item.kind === 'pair');
    overviewBody.innerHTML = overviewRows.length
      ? overviewRows.map(({ item, status, error, pending, stale }) => bindingStatusRowHtml(item, status, error, false, { pending, stale })).join('')
      : '<tr><td colspan="5">暂无账号配置</td></tr>';
    if ($('overviewBindingCount')) $('overviewBindingCount').textContent = `${overviewRows.length} 组`;
  }
}

function renderCachedBindingStatuses() {
  const entries = bindingEntriesFromState();
  if (!entries.length) {
    renderBindingEmptyRows();
    return [];
  }
  const snapshot = state.bindingStatusSnapshot || {};
  if (Array.isArray(snapshot.bindings)) {
    const statusByKey = new Map();
    const statusByIdentity = new Map();
    snapshot.bindings.forEach((row) => {
      const accountKey = String(row.account_key || '').trim();
      const identity = [
        String(row.bridge_id || '').trim(),
        normalizeAccountType(row.account_type || 'STOCK'),
        String(row.account_id || '').trim(),
      ].join('|');
      if (accountKey) statusByKey.set(accountKey, row);
      if (identity) statusByIdentity.set(identity, row);
    });
    const rows = entries.map((item) => {
      const identity = [
        String(item.bridgeId || '').trim(),
        normalizeAccountType(item.accountType || 'STOCK'),
        String(item.accountId || '').trim(),
      ].join('|');
      const row = statusByKey.get(item.accountKey) || statusByIdentity.get(identity);
      if (!row) return { item, status: null, error: null, pending: true };
      if (row.error) return { item, error: new Error(row.error) };
      return { item, status: row.status || null, stale: true };
    });
    renderBindingRows(rows);
    return rows;
  }
  const rows = entries.map((item) => ({ item, status: null, error: null, pending: true }));
  renderBindingRows(rows);
  return rows;
}

async function saveCurrentAccountPair() {
  const accountId = selectedAccount();
  const accountType = selectedAccountType();
  const accountKey = selectedAccountKey();
  const form = $('bindingForm');
  const qmtDir = form && form.qmt_dir ? form.qmt_dir.value.trim() : '';
  const qmtTradeDir = form && form.qmt_trade_dir ? form.qmt_trade_dir.value.trim() : '';
  const mode = form && form.mode ? form.mode.value : 'ctypes';
  const dataProvider = !!(form && form.data_provider && form.data_provider.checked);
  const marketRoutingEnabled = !!(form && form.market_routing_enabled && form.market_routing_enabled.checked);
  const marketBridges = {
    SH: {
      bridge_id: form && form.market_sh_bridge_id ? form.market_sh_bridge_id.value.trim() : '',
      qmt_dir: form && form.market_sh_qmt_dir ? form.market_sh_qmt_dir.value.trim() : '',
    },
    SZ: {
      bridge_id: form && form.market_sz_bridge_id ? form.market_sz_bridge_id.value.trim() : '',
      qmt_dir: form && form.market_sz_qmt_dir ? form.market_sz_qmt_dir.value.trim() : '',
    },
  };
  if (!accountId) {
    setBindingNotice('请先选择或填写资金账号，再保存绑定。', 'error', { autoHide: false });
    log('账号为空，无法保存配对');
    return;
  }
  if (normalizeTransportMode(mode) === 'lttx') {
    if (!qmtDir || !qmtTradeDir) {
      setBindingNotice('高级模式必须填写普通端和极速交易端两个 QMT 核心目录。', 'error', { autoHide: false });
      return;
    }
    if (qmtDirsAreSame(qmtDir, qmtTradeDir)) {
      setBindingNotice('高级模式的两个 QMT 核心目录必须不同。', 'error', { autoHide: false });
      return;
    }
  }
  setBindingSaveBusy(true);
  setBindingNotice('正在保存账号绑定并刷新连接状态...', 'busy', { autoHide: false });
  try {
    const data = await saveAccountConfigRequest({
      account_id: accountId,
      account_type: accountType,
      account_key: accountKey,
      qmt_dir: qmtDir,
      qmt_trade_dir: qmtTradeDir,
      mode,
      data_provider: dataProvider,
      market_routing_enabled: marketRoutingEnabled,
      market_bridges: marketBridges,
    });
    state.accountPairs = data.account_pairs || {};
    state.accountConfigs = data.account_configs || state.accountConfigs;
    state.setup = data.setup || state.setup;
    state.defaultAccountId = (data.setup && data.setup.default_account_id) || state.defaultAccountId;
    state.bridges = data.bridges || state.bridges;
    state.accountId = accountId;
    state.accountType = accountType;
    state.accountKey = (data.account && data.account.account_key) || accountKey;
    renderBridgeSelect(state.bridges);
    renderAccountSelect();
    applyAccountPair(state.accountKey || accountId);
    syncBindingForm();
    renderAccountPairs();
    renderCachedBindingStatuses();
    saveAccountConfigCache(data);
    let refreshError = null;
    try {
      await refreshBindingStatuses();
    } catch (error) {
      refreshError = error;
      log('绑定状态刷新失败', { error: error.message });
    }
    const deployIssue = qmtCoreDeployHasIssues(data.qmt_core_deploy);
    const noticeLevel = refreshError || deployIssue || data.legacy_fallback || bindingMarketRouteHasMissingDir(marketRoutingEnabled, marketBridges) ? 'warn' : 'success';
    const noticeMessage = bindingSaveSummary({
      accountId,
      accountType,
      mode,
      qmtDir,
      qmtTradeDir,
      dataProvider,
      marketRoutingEnabled,
      marketBridges,
      legacyFallback: !!data.legacy_fallback,
      qmtCoreDeploy: data.qmt_core_deploy,
    });
    setBindingNotice(refreshError ? `${noticeMessage}，连接状态刷新失败：${refreshError.message}` : noticeMessage, noticeLevel);
    log('账号配置已保存', { account_id: accountId, account_type: accountType, mode, data_provider: dataProvider, qmt_dir_configured: !!qmtDir });
    showBindingQmtGuide({
      account_id: accountId,
      account_type: accountType,
      qmt_dir: qmtDir,
      qmt_trade_dir: qmtTradeDir,
      mode,
      marketRoutingEnabled,
      marketBridges,
    }, data.qmt_core_deploy, { context: 'binding' });
    if (data.qmt_core_deploy) {
      log('QMT 核心包自动复制已处理', qmtCoreDeployLogPayload(data.qmt_core_deploy));
    }
    if (data.qmt_bridge_identity) {
      log('ctypes 身份配置已处理', data.qmt_bridge_identity);
    }
    if (!qmtDir) log('QMT 核心目录未填写，该账号自动复制和自动更新不可用', { account_id: accountId, account_type: accountType });
  } catch (error) {
    setBindingNotice(`保存失败：${error.message}`, 'error', { autoHide: false });
    log('账号配置保存失败', { error: error.message });
  } finally {
    setBindingSaveBusy(false);
  }
}

async function removeCurrentAccountPair() {
  const accountId = selectedAccount();
  const accountType = selectedAccountType();
  const accountKey = selectedAccountKey();
  if (!accountId) return;
  const data = await deleteAccountConfigRequest(accountId, accountType, accountKey);
  state.accountPairs = data.account_pairs || {};
  state.accountConfigs = data.account_configs || {};
  state.setup = data.setup || state.setup;
  state.defaultAccountId = (data.setup && data.setup.default_account_id) || state.defaultAccountId;
  state.defaultAccountType = normalizeAccountType((data.setup && data.setup.default_account_type) || state.defaultAccountType || 'STOCK');
  state.defaultAccountKey = (data.setup && data.setup.default_account_key) || state.defaultAccountKey || '';
  if ((accountKey && state.accountKey === accountKey) || (!accountKey && state.accountId === accountId && state.accountType === accountType)) {
    state.accountId = '';
    state.accountKey = '';
  }
  renderAccountPairs();
  if (!state.accountId) {
    state.accountId = state.defaultAccountId || '';
    state.accountType = state.defaultAccountType || 'STOCK';
    state.accountKey = state.defaultAccountKey || '';
    renderAccountSelect();
    applyAccountPair(state.accountKey || state.accountId);
    syncBindingForm();
  }
  renderCachedBindingStatuses();
  saveAccountConfigCache(data);
  await refreshBindingStatuses();
  log('账号配置已删除', { account_id: accountId, account_type: accountType });
}

function applyAccountPair(accountKeyOrId) {
  const value = String(accountKeyOrId || '').trim();
  if (!value) return false;
  const config = findAccountConfigByKey(value);
  const entry = config ? {
    accountKey: accountConfigKey(value, config),
    accountId: config.account_id,
    accountType: normalizeAccountType(config.account_type || 'STOCK'),
    bridgeId: config.bridge_id || state.defaultBridgeId || 'default',
  } : (findAccountEntryById(value, state.accountType) || null);
  const bridgeId = (entry && entry.bridgeId) || bridgeIdForAccount(value, entry && entry.accountType);
  const select = $('bridgeSelect');
  if (select && bridgeOptionExists(bridgeId)) {
    select.value = bridgeId;
  }
  if (entry) {
    state.accountKey = entry.accountKey || value;
    state.accountId = entry.accountId || value;
    state.accountType = normalizeAccountType(entry.accountType || 'STOCK');
  }
  selectedBridge();
  return !!entry || !!loadAccountPairs()[value];
}

function syncBindingForm() {
  const form = $('bindingForm');
  if (!form) return;
  const info = selectedAccountInfo();
  form.account_id.value = info.accountId || '';
  form.dataset.accountKey = info.accountKey || '';
  form.dataset.bridgeId = info.bridgeId || '';
  if (form.account_type) form.account_type.value = normalizeAccountType(info.accountType || 'STOCK');
  const config = info.config;
  if (form.display_name) form.display_name.value = config ? String(config.display_name || config.account_name || '') : '';
  if (form.qmt_dir) form.qmt_dir.value = config && config.qmt_dir ? config.qmt_dir : '';
  if (form.mode) form.mode.value = config && config.mode ? config.mode : 'ctypes';
  if (form.qmt_trade_dir) form.qmt_trade_dir.value = config && config.qmt_trade_dir ? config.qmt_trade_dir : '';
  syncAdvancedQmtDirField('bindingQmtTradeDir', form.mode ? form.mode.value : 'ctypes');
  if (form.data_provider) form.data_provider.checked = !!(config && config.data_provider);
  const routes = normalizeMarketRoutes(config || {});
  if (form.market_routing_enabled) form.market_routing_enabled.checked = isMarketRoutingEnabled(config || {});
  if (form.market_sh_qmt_dir) form.market_sh_qmt_dir.value = routes.SH.qmt_dir || '';
  if (form.market_sh_bridge_id) form.market_sh_bridge_id.value = routes.SH.bridge_id || '';
  if (form.market_sz_qmt_dir) form.market_sz_qmt_dir.value = routes.SZ.qmt_dir || '';
  if (form.market_sz_bridge_id) form.market_sz_bridge_id.value = routes.SZ.bridge_id || '';
  renderBindingQmtScriptPanel();
}

function closeBindingDialog() {
  const overlay = $('bindingDialogOverlay');
  if (!overlay) return;
  overlay.classList.add('hidden');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('binding-dialog-open');
}

function fillBindingForm(values = {}) {
  const form = $('bindingForm');
  if (!form) return;
  form.dataset.accountKey = values.accountKey || '';
  form.dataset.bridgeId = values.bridgeId || '';
  if (form.display_name) form.display_name.value = values.displayName || '';
  form.account_id.value = values.accountId || '';
  if (form.account_type) form.account_type.value = normalizeAccountType(values.accountType || 'STOCK');
  if (form.qmt_dir) form.qmt_dir.value = values.qmtDir || '';
  if (form.mode) form.mode.value = values.mode || 'ctypes';
  if (form.qmt_trade_dir) form.qmt_trade_dir.value = values.qmtTradeDir || '';
  syncAdvancedQmtDirField('bindingQmtTradeDir', form.mode ? form.mode.value : 'ctypes');
  if (form.data_provider) form.data_provider.checked = !!values.dataProvider;
  const routes = normalizeMarketRoutes({ market_bridges: values.marketBridges || {} });
  if (form.market_routing_enabled) form.market_routing_enabled.checked = !!values.marketRoutingEnabled;
  if (form.market_sh_qmt_dir) form.market_sh_qmt_dir.value = routes.SH.qmt_dir || '';
  if (form.market_sh_bridge_id) form.market_sh_bridge_id.value = routes.SH.bridge_id || '';
  if (form.market_sz_qmt_dir) form.market_sz_qmt_dir.value = routes.SZ.qmt_dir || '';
  if (form.market_sz_bridge_id) form.market_sz_bridge_id.value = routes.SZ.bridge_id || '';
}

function openBindingDialog(options = {}) {
  const overlay = $('bindingDialogOverlay');
  const form = $('bindingForm');
  if (!overlay || !form) return;
  const accountKey = String(options.accountKey || '').trim();
  const config = accountKey ? findAccountConfigByKey(accountKey) : null;
  const accountId = String(options.accountId || (config && config.account_id) || '').trim();
  const accountType = normalizeAccountType(options.accountType || (config && config.account_type) || 'STOCK');
  const bridgeId = String(options.bridgeId || (config && config.bridge_id) || '').trim();
  const displayName = String(options.displayName || (config && (config.display_name || config.account_name)) || '').trim();
  fillBindingForm({
    accountKey,
    accountId,
    accountType,
    bridgeId,
    displayName,
    qmtDir: config && config.qmt_dir ? config.qmt_dir : (options.qmtDir || ''),
    qmtTradeDir: config && config.qmt_trade_dir ? config.qmt_trade_dir : (options.qmtTradeDir || ''),
    mode: config && config.mode ? config.mode : (options.mode || 'ctypes'),
    dataProvider: config ? !!config.data_provider : !!options.dataProvider,
    marketRoutingEnabled: config ? isMarketRoutingEnabled(config) : !!options.marketRoutingEnabled,
    marketBridges: config ? normalizeMarketRoutes(config) : (options.marketBridges || {}),
  });
  const editing = !!accountId;
  const title = $('bindingDialogTitle');
  const subtitle = $('bindingDialogSubtitle');
  const hint = $('bindingDialogHint');
  if (title) title.textContent = editing ? '编辑账号绑定' : '添加账号绑定';
  if (subtitle) {
    subtitle.textContent = editing
      ? `${displayName || accountId} / ${accountTypeLabel(accountType)}`
      : '填写账号名称、资金账号、账户类型、运行模式和 QMT 目录。';
  }
  if (hint) {
    hint.textContent = bridgeId ? `内部通道：${bridgeId}` : '保存后自动分配内部通道';
  }
  overlay.classList.remove('hidden');
  overlay.setAttribute('aria-hidden', 'false');
  document.body.classList.add('binding-dialog-open');
  window.setTimeout(() => form.account_id && form.account_id.focus(), 0);
}

function selectAccountPair(accountId, bridgeId, accountType = 'STOCK', accountKey = '') {
  if (accountId) {
    state.accountId = accountId;
    state.accountType = normalizeAccountType(accountType);
    state.accountKey = accountKey || makeAccountKey(accountId, state.accountType, bridgeId || state.defaultBridgeId || 'default');
    renderAccountSelect();
    selectedAccount();
    applyAccountPair(state.accountKey);
  }
  if (!accountId && bridgeId && $('bridgeSelect') && bridgeOptionExists(bridgeId)) {
    $('bridgeSelect').value = bridgeId;
    selectedBridge();
  }
  syncBindingForm();
  resetSelectionState();
  restartOrderCallbackSocket();
  refreshStatus().catch((error) => log('账号配置状态刷新失败', { error: error.message }));
  refreshAccount('asset,positions').catch((error) => log('账号配置资产刷新失败', { error: error.message }));
  refreshAccount('orders', { force: true, subscribe: false }).catch((error) => log('账号配置委托刷新失败', { error: error.message }));
  refreshAccount('trades').catch((error) => log('账号配置成交刷新失败', { error: error.message }));
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
    const label = document.createElement('div');
    label.className = 'config-info';
    const strong = document.createElement('strong');
    strong.textContent = `${plain(bridge.name || bridgeId)} (${plain(bridgeId)})`;
    label.appendChild(strong);
    const channels = bridge.channels || {};
    const summary = document.createElement('div');
    summary.className = 'config-summary';
    const normalLine = document.createElement('small');
    normalLine.textContent = `普通通道：${channels.normal || '--'}`;
    const tradeLine = document.createElement('small');
    tradeLine.textContent = `极速通道：${channels.trade || '--'}`;
    const normalDirLine = document.createElement('small');
    normalDirLine.textContent = bridge.python_dir ? `普通 QMT 目录：${bridge.python_dir}` : '普通 QMT 目录未设置';
    const tradeDirLine = document.createElement('small');
    tradeDirLine.textContent = bridge.python_dir ? `极速交易端目录：${bridge.python_dir}` : '极速交易端目录未设置';
    summary.appendChild(normalLine);
    summary.appendChild(tradeLine);
    summary.appendChild(normalDirLine);
    summary.appendChild(tradeDirLine);
    label.appendChild(summary);
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
  form.python_dir.value = bridge.python_dir || '';
}

async function submitBridgeForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = {
    id: form.id.value.trim(),
    name: form.name.value.trim(),
    python_dir: form.python_dir.value.trim(),
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
  const displayName = form.display_name ? form.display_name.value.trim() : '';
  const accountType = normalizeAccountType(form.account_type ? form.account_type.value : 'STOCK');
  const qmtDir = form.qmt_dir ? form.qmt_dir.value.trim() : '';
  const qmtTradeDir = form.qmt_trade_dir ? form.qmt_trade_dir.value.trim() : '';
  const mode = form.mode ? form.mode.value : 'ctypes';
  const dataProvider = !!(form.data_provider && form.data_provider.checked);
  if (normalizeTransportMode(mode) === 'lttx') {
    if (!qmtDir || !qmtTradeDir) {
      setBindingNotice('高级模式必须填写普通端和极速交易端两个 QMT 核心目录。', 'error', { autoHide: false });
      return;
    }
    if (qmtDirsAreSame(qmtDir, qmtTradeDir)) {
      setBindingNotice('高级模式的两个 QMT 核心目录必须不同。', 'error', { autoHide: false });
      return;
    }
  }
  const bridgeId = String(form.dataset.bridgeId || '').trim();
  const marketRoutingEnabled = !!(form.market_routing_enabled && form.market_routing_enabled.checked);
  const marketBridges = {
    SH: {
      bridge_id: form.market_sh_bridge_id ? form.market_sh_bridge_id.value.trim() : '',
      qmt_dir: form.market_sh_qmt_dir ? form.market_sh_qmt_dir.value.trim() : '',
    },
    SZ: {
      bridge_id: form.market_sz_bridge_id ? form.market_sz_bridge_id.value.trim() : '',
      qmt_dir: form.market_sz_qmt_dir ? form.market_sz_qmt_dir.value.trim() : '',
    },
  };
  if (!accountId) {
    setBindingNotice('请填写资金账号后再保存绑定。', 'error', { autoHide: false });
    if (form.account_id) form.account_id.focus();
    log('账号为空，无法保存绑定');
    return;
  }
  setBindingSaveBusy(true);
  setBindingNotice('正在保存绑定并刷新连接状态...', 'busy', { autoHide: false });
  try {
    const data = await saveAccountConfigRequest({
      account_id: accountId,
      display_name: displayName,
      account_type: accountType,
      bridge_id: bridgeId || undefined,
      qmt_dir: qmtDir,
      qmt_trade_dir: qmtTradeDir,
      mode,
      data_provider: dataProvider,
      market_routing_enabled: marketRoutingEnabled,
      market_bridges: marketBridges,
    });
    const responseAccount = data.account && typeof data.account === 'object' ? data.account : {};
    const savedBridgeId = responseAccount.bridge_id || bridgeId || state.defaultBridgeId || 'default';
    const savedAccountKey = responseAccount.account_key || form.dataset.accountKey || makeAccountKey(accountId, accountType, savedBridgeId);
    state.accountPairs = data.account_pairs || {};
    state.accountConfigs = data.account_configs || {};
    mergeSavedAccountDisplayName({
      accountKey: savedAccountKey,
      accountId,
      accountType,
      bridgeId: savedBridgeId,
      displayName,
      account: responseAccount,
      qmtDir,
      qmtTradeDir,
      mode,
      dataProvider,
      marketRoutingEnabled,
      marketBridges,
    });
    state.setup = data.setup || state.setup;
    state.bridges = data.bridges || state.bridges;
    state.accountId = accountId;
    state.accountType = accountType;
    state.accountKey = savedAccountKey;
    renderBridgeSelect(state.bridges);
    renderAccountSelect();
    selectedAccount();
    applyAccountPair(state.accountKey);
    syncBindingForm();
    renderAccountPairs();
    renderCachedBindingStatuses();
    saveAccountConfigCache(data);
    let refreshError = null;
    try {
      await refreshBindingStatuses();
    } catch (error) {
      refreshError = error;
      log('绑定状态刷新失败', { error: error.message });
    }
    closeBindingDialog();
    const deployIssue = qmtCoreDeployHasIssues(data.qmt_core_deploy);
    const noticeLevel = refreshError || deployIssue || data.legacy_fallback || bindingMarketRouteHasMissingDir(marketRoutingEnabled, marketBridges) ? 'warn' : 'success';
    const noticeMessage = bindingSaveSummary({
      accountId,
      accountType,
      displayName,
      mode,
      qmtDir,
      qmtTradeDir,
      dataProvider,
      marketRoutingEnabled,
      marketBridges,
      legacyFallback: !!data.legacy_fallback,
      qmtCoreDeploy: data.qmt_core_deploy,
    });
    setBindingNotice(refreshError ? `${noticeMessage}，连接状态刷新失败：${refreshError.message}` : noticeMessage, noticeLevel);
    log('账号配置已保存', { account_id: accountId, display_name: displayName, account_type: accountType, mode, data_provider: dataProvider, qmt_dir_configured: !!qmtDir });
    showBindingQmtGuide({
      account_id: accountId,
      account_type: accountType,
      qmt_dir: qmtDir,
      qmt_trade_dir: qmtTradeDir,
      mode,
      marketRoutingEnabled,
      marketBridges,
    }, data.qmt_core_deploy, { context: 'binding' });
    if (data.qmt_core_deploy) {
      log('QMT 核心包自动复制已处理', qmtCoreDeployLogPayload(data.qmt_core_deploy));
    }
    if (data.qmt_bridge_identity) {
      log('ctypes 身份配置已处理', data.qmt_bridge_identity);
    }
    if (!qmtDir) log('QMT 核心目录未填写，该账号自动复制和自动更新不可用', { account_id: accountId, account_type: accountType });
  } catch (error) {
    setBindingNotice(`保存失败：${error.message}`, 'error', { autoHide: false });
    log('账号配置保存失败', { error: error.message });
  } finally {
    setBindingSaveBusy(false);
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
    renderCachedBindingStatuses();
    saveAccountConfigCache(data);
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
  state.accountConfigs = data.account_configs || {};
  state.setup = data.setup || null;
  state.defaultAccountId = data.default_account_id || (data.setup && data.setup.default_account_id) || state.defaultAccountId;
  state.defaultAccountType = normalizeAccountType(data.default_account_type || (data.setup && data.setup.default_account_type) || state.defaultAccountType || 'STOCK');
  state.defaultAccountKey = data.default_account_key || (data.setup && data.setup.default_account_key) || state.defaultAccountKey || '';
  state.bridgeId = data.bridges && data.bridges[currentBridgeId] ? currentBridgeId : (data.default_bridge_id || Object.keys(data.bridges || {})[0] || 'default');
  renderBridgeSelect(data.bridges || {});
  renderAccountPairs();
  renderBridgeConfigList();
  renderApiDocs(state.apiEndpointId);
  renderCachedBindingStatuses();
  saveAccountConfigCache(data);
  await refreshBindingStatuses();
  await refreshUpdateStatus({ log: false }).catch((error) => log('更新状态刷新失败', { error: error.message }));
}

async function refreshBindingStatuses() {
  const entries = bindingEntriesFromState();
  if (!entries.length) {
    renderBindingEmptyRows();
    if (state.bindingStatusRetryTimer) {
      clearTimeout(state.bindingStatusRetryTimer);
      state.bindingStatusRetryTimer = null;
    }
    return;
  }
  let snapshot;
  try {
    snapshot = await api('/api/bindings/status');
  } catch (error) {
    snapshot = await legacyBindingStatusSnapshot(entries);
    log('绑定状态批量接口不可用，已使用兼容查询', { error: error.message });
  }
  state.bindingStatusSnapshot = snapshot;
  saveAccountConfigCache();
  const statusByKey = new Map();
  const statusByIdentity = new Map();
  (snapshot.bindings || []).forEach((row) => {
    const accountKey = String(row.account_key || '').trim();
    const identity = [
      String(row.bridge_id || '').trim(),
      normalizeAccountType(row.account_type || 'STOCK'),
      String(row.account_id || '').trim(),
    ].join('|');
    if (accountKey) statusByKey.set(accountKey, row);
    if (identity) statusByIdentity.set(identity, row);
  });
  const rows = entries.map((item) => {
    const identity = [
      String(item.bridgeId || '').trim(),
      normalizeAccountType(item.accountType || 'STOCK'),
      String(item.accountId || '').trim(),
    ].join('|');
    const row = statusByKey.get(item.accountKey) || statusByIdentity.get(identity);
    if (snapshot.error) return { item, error: snapshot.error };
    if (!row) return { item, error: new Error('绑定状态未返回') };
    if (row.error) return { item, error: new Error(row.error) };
    return { item, status: row.status || null };
  });
  renderBindingRows(rows);
  const monitorWarmingUp = rows.some(({ status }) => {
    const selected = status && status.status ? status.status : status;
    return !!(selected && selected.monitor && selected.monitor.ready === false);
  });
  if (monitorWarmingUp && !state.bindingStatusRetryTimer) {
    state.bindingStatusRetryTimer = setTimeout(() => {
      state.bindingStatusRetryTimer = null;
      refreshBindingStatuses().catch((error) => log('绑定状态初始化重试失败', { error: error.message }));
    }, 1200);
  } else if (!monitorWarmingUp && state.bindingStatusRetryTimer) {
    clearTimeout(state.bindingStatusRetryTimer);
    state.bindingStatusRetryTimer = null;
  }
}

async function legacyBindingStatusSnapshot(entries) {
  const bindings = await Promise.all(entries.map(async (item) => {
    const params = new URLSearchParams();
    params.set('account_id', item.accountId || '');
    params.set('account_type', normalizeAccountType(item.accountType || 'STOCK'));
    params.set('account_key', item.accountKey || '');
    params.set('bridge_id', item.bridgeId || '');
    try {
      return {
        account_key: item.accountKey || '',
        account_id: item.accountId || '',
        account_type: normalizeAccountType(item.accountType || 'STOCK'),
        bridge_id: item.bridgeId || '',
        status: await api(`/api/status?${params.toString()}`),
      };
    } catch (error) {
      return {
        account_key: item.accountKey || '',
        account_id: item.accountId || '',
        account_type: normalizeAccountType(item.accountType || 'STOCK'),
        bridge_id: item.bridgeId || '',
        error: error.message,
      };
    }
  }));
  return { bindings, cached: false, compatibility_fallback: true };
}

function bindingVerifyKey(accountId, bridgeId, accountType = 'STOCK', accountKey = '') {
  return [
    String(accountKey || '').trim(),
    String(bridgeId || '').trim(),
    normalizeAccountType(accountType),
    String(accountId || '').trim(),
  ].join('|');
}

function updateBindingVerifyButtons() {
  const busyKey = state.bindingVerifyBusyKey;
  document.querySelectorAll('.verify-pair-btn').forEach((button) => {
    const buttonKey = bindingVerifyKey(
      button.dataset.accountId,
      button.dataset.bridgeId,
      button.dataset.accountType,
      button.dataset.accountKey,
    );
    const loading = !!busyKey && busyKey === buttonKey;
    button.disabled = !!busyKey;
    button.classList.toggle('is-loading', loading);
    if (loading) {
      button.setAttribute('aria-busy', 'true');
    } else {
      button.removeAttribute('aria-busy');
    }
    const label = button.querySelector('.binding-verify-label');
    if (label) label.textContent = loading ? '验证中' : '验证';
  });
}

function setBindingVerifyBusy(accountId, bridgeId, accountType = 'STOCK', accountKey = '', busy = true) {
  const key = bindingVerifyKey(accountId, bridgeId, accountType, accountKey);
  state.bindingVerifyBusyKey = busy ? key : '';
  updateBindingVerifyButtons();
}

function bindingStatusRowHtml(item, status, error, withVerify, options = {}) {
  const pending = !!options.pending && !status && !error;
  const stale = !!options.stale && !pending && !error;
  const selected = status && status.status ? status.status : status;
  const normalOnline = !!(selected && selected.normal && selected.normal.online);
  const tradeOnline = !!(selected && selected.trade && selected.trade.online);
  const config = item.config || findAccountConfigByKey(item.accountKey) || {};
  const preferred = (status && status.preferred_mode) || (config && config.mode) || 'ctypes';
  const effective = (status && status.effective_mode) || preferred;
  const provider = (status && status.data_provider) || (config && config.data_provider);
  const marketEnabled = !!((status && status.market_routing_enabled) || isMarketRoutingEnabled(config));
  const marketRoutes = normalizeMarketRoutes(config || {});
  const marketRouteStatuses = (status && status.market_routes) || {};
  const marketLines = ['SH', 'SZ'].map((market) => {
    const routeStatus = marketRouteStatuses[market] || {};
    const routeConfig = marketRoutes[market] || {};
    const tradeStatus = routeStatus.status && routeStatus.status.trade ? routeStatus.status.trade : {};
    const online = !!(routeStatus.ready || tradeStatus.online);
    const routeBridgeId = routeStatus.bridge_id || routeConfig.bridge_id || '';
    return {
      market,
      online,
      bridgeId: routeBridgeId,
      qmtDir: routeStatus.qmt_dir || routeConfig.qmt_dir || '',
      text: `${market}${online ? '在线' : '离线'}${routeBridgeId ? `(${routeBridgeId})` : ''}`,
    };
  });
  const configuredMarketLines = marketLines.filter((row) => row.bridgeId || row.qmtDir || marketEnabled);
  const marketReadyCount = configuredMarketLines.filter((row) => row.online).length;
  const marketStatusText = configuredMarketLines.map((row) => row.text).join(' / ');
  const qmtDirText = config && config.qmt_dir ? config.qmt_dir : '未填写（自动更新不可用）';
  const qmtTradeDirText = config && config.qmt_trade_dir ? config.qmt_trade_dir : '';
  const qmtDisplayText = normalizeTransportMode(preferred) === 'lttx'
    ? `${qmtDirText} / 极速端：${qmtTradeDirText || '未填写'}`
    : qmtDirText;
  const title = error ? error.message : (stale ? '上次状态，正在后台刷新' : '');
  const accountText = item.accountId || item.account_id || '未绑定';
  const accountType = normalizeAccountType(item.accountType || item.account_type || (config && config.account_type) || 'STOCK');
  const displayName = String(item.displayName || item.display_name || (config && (config.display_name || config.account_name)) || '').trim();
  const accountTitle = displayName || accountText;
  const accountSubtext = displayName ? `${accountText} / ${accountTypeLabel(accountType)}` : accountTypeLabel(accountType);
  const accountKey = item.accountKey || item.account_key || accountConfigKey('', config);
  const bridgeId = item.bridgeId || item.bridge_id || (config && config.bridge_id) || '';
  const bridgeName = (state.bridges && state.bridges[bridgeId] && state.bridges[bridgeId].name) || bridgeId || 'default';
  const verifyKey = bindingVerifyKey(accountText, bridgeId, accountType, accountKey);
  const verifying = !!state.bindingVerifyBusyKey && state.bindingVerifyBusyKey === verifyKey;
  const verifyDisabled = state.bindingVerifyBusyKey ? ' disabled' : '';
  const verifyBusy = verifying ? ' aria-busy="true"' : '';
  const verifyClass = verifying ? ' verify-pair-btn is-loading' : ' verify-pair-btn';
  const verifyLabel = verifying ? '验证中' : '验证';
  const preferredLabel = transportModeLabel(preferred, true);
  const effectiveLabel = transportModeLabel(effective, true);
  const statusClass = pending ? 'warn' : (error ? 'offline' : (marketEnabled
    ? (marketReadyCount >= 2 ? 'online' : (marketReadyCount > 0 ? 'warn' : 'offline'))
    : (normalOnline && tradeOnline ? 'online' : (normalOnline || tradeOnline ? 'warn' : 'offline'))));
  const statusLabel = pending ? '刷新中' : (error ? '状态失败' : (marketEnabled
    ? (marketReadyCount >= 2 ? '市场路由在线' : (marketReadyCount > 0 ? '市场路由部分在线' : '市场路由离线'))
    : (normalOnline && tradeOnline ? '全部在线' : (normalOnline || tradeOnline ? '部分在线' : '离线'))));
  const mainBridgeLabel = normalOnline || tradeOnline ? '在线' : (marketEnabled && marketReadyCount > 0 ? '未启用' : '离线');
  let connectionLines = pending
    ? ['状态后台刷新中']
    : (marketEnabled && configuredMarketLines.length
    ? [`主桥 ${mainBridgeLabel}`, ...configuredMarketLines.map((row) => row.text)]
    : [`普通${normalOnline ? '在线' : '离线'}`, `极速${tradeOnline ? '在线' : '离线'}`]);
  if (stale) connectionLines = ['上次状态，后台刷新中', ...connectionLines];
  const connectionHtml = connectionLines
    .map((line) => `<small class="binding-cell-note binding-status-line">${esc(line)}</small>`)
    .join('');
  const actionAttrs = `data-account-id="${esc(accountText)}" data-account-type="${esc(accountType)}" data-account-key="${esc(accountKey)}" data-bridge-id="${esc(bridgeId)}" data-display-name="${esc(displayName)}"`;
  if (!withVerify) {
    return `<tr title="${esc(title)}">
      <td>${esc(accountTitle)}<br><small>${esc(accountSubtext)}</small></td>
      <td>${esc(preferredLabel)}</td>
      <td><span class="status-dot ${esc(statusClass)}">${esc(pending ? '待刷新' : effectiveLabel)}${status && status.fallback ? '（已回退）' : ''}</span></td>
      <td>${esc(qmtDisplayText)}</td>
      <td>${provider ? '共享行情源' : '--'}</td>
    </tr>`;
  }
  return `<tr class="binding-list-row" title="${esc(title)}">
    <td data-label="操作">
      <div class="binding-row-actions">
        <button type="button" class="${verifyClass.trim()}" data-binding-action="verify" ${actionAttrs}${verifyDisabled}${verifyBusy}>
          <span class="button-spinner" aria-hidden="true"></span><span class="binding-verify-label">${esc(verifyLabel)}</span>
        </button>
        <button type="button" data-binding-action="edit" ${actionAttrs}>编辑</button>
        <button type="button" class="binding-delete-btn" data-binding-action="delete" ${actionAttrs}>删除</button>
      </div>
    </td>
    <td class="binding-name-cell" data-label="账号名称">
      <strong>${esc(displayName || '--')}</strong>
    </td>
    <td class="binding-account-cell" data-label="资金账号">
      <strong>${esc(accountText)}</strong>
      <small>${esc(accountTypeLabel(accountType))}</small>
    </td>
    <td class="binding-status-cell" data-label="连接状态">
      <span class="status-dot ${esc(statusClass)}">${esc(statusLabel)}</span>
      ${connectionHtml}
    </td>
    <td data-label="首选模式">${esc(preferredLabel)}模式</td>
    <td data-label="实际模式"><span class="status-dot ${esc(statusClass)}">${esc(pending ? '待刷新' : `${effectiveLabel}模式`)}${status && status.fallback ? '（已回退）' : ''}</span></td>
    <td class="binding-channel-cell" data-label="内部通道">
      <strong class="binding-bridge-name">${esc(bridgeName)}</strong>
      <small class="binding-cell-note">${esc(bridgeId || 'default')}</small>
      ${marketEnabled && marketStatusText ? `<small class="binding-cell-note">${esc(marketStatusText)}</small>` : ''}
    </td>
    <td class="binding-dir-cell" data-label="QMT 目录" title="${esc(qmtDisplayText)}">${esc(qmtDisplayText)}</td>
    <td data-label="数据源">${provider ? '<span class="source-pill source-cfquant">共享行情源</span>' : '<span class="binding-muted">普通绑定</span>'}</td>
  </tr>`;
}

async function verifyPair(accountId, bridgeId, accountType = 'STOCK', accountKey = '') {
  accountType = normalizeAccountType(accountType);
  if (state.bindingVerifyBusyKey) return;
  setBindingVerifyBusy(accountId, bridgeId, accountType, accountKey, true);
  const note = $('pairVerifyNote');
  if (note) note.textContent = `正在验证 ${accountId}...`;
  try {
    const data = await api('/api/account-pairs/verify', {
      method: 'POST',
      body: JSON.stringify({
        account_id: accountId,
        account_type: accountType,
        account_key: accountKey,
        bridge_id: bridgeId || bridgeIdForAccount(accountId, accountType),
        channel: selectedChannel(),
        force: 1,
      }),
    });
    renderPairVerification(data);
    if (note) note.textContent = `验证完成：${accountId}`;
    log('账号验证完成', { account_id: accountId, account_type: accountType });
  } catch (error) {
    renderPairVerification(null);
    if (note) note.textContent = `验证失败：${error.message}`;
    log('账号验证失败', { account_id: accountId, account_type: accountType, error: error.message });
  } finally {
    setBindingVerifyBusy(accountId, bridgeId, accountType, accountKey, false);
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
    return `<tr>
      <td>${esc(row.stock_code || `${row.m_strInstrumentID || ''}.${row.m_strExchangeID || ''}`)}</td>
      <td>${esc(row.instrument_name || row.m_strInstrumentName)}</td>
      <td class="num">${esc(row.volume ?? row.m_nVolume)}</td>
      <td class="num">${esc(row.can_use_volume ?? row.m_nCanUseVolume)}</td>
      <td class="num">${money(row.market_value ?? row.m_dInstrumentValue)}</td>
    </tr>`;
  }).join('');
  $('pairPositionsBody').innerHTML = html || '<tr><td colspan="5">无持仓数据</td></tr>';
}

function setStatus(id, online, detail) {
  const node = $(id);
  node.classList.toggle('online', !!online);
  node.classList.toggle('offline', !online);
  const text = Array.isArray(detail) ? detail.filter(Boolean).join('\n') : (detail || '');
  node.title = text;
  if (text) {
    node.setAttribute('data-tooltip', text);
    node.setAttribute('tabindex', '0');
  } else {
    node.removeAttribute('data-tooltip');
    node.removeAttribute('tabindex');
  }
}

function boolText(value) {
  if (value === true) return '是';
  if (value === false) return '否';
  return '--';
}

function statusTooltipLines(label, info, snapshot) {
  const data = info || {};
  const bridge = snapshot || {};
  const lines = [
    `${label}：${data.online ? '在线' : '离线或检测超时'}`,
    `内部通道：${bridge.bridge_name || bridge.bridge_id || selectedBridge()}`,
    `请求频道：${data.channel || '--'}`,
    `检测动作：${data.probe_action || '--'}`,
    `检测耗时：${data.latency_ms === undefined ? '--' : `${data.latency_ms} ms`}`,
    `检测时间：${bridge.checked_at_text || '--'}`,
  ];
  if (bridge.monitor && bridge.monitor.cached) {
    lines.push(`状态缓存：已缓存，监控间隔 ${bridge.monitor.interval_seconds || '--'} 秒`);
  }
  const status = data.status || {};
  if (status.bridge || status.request_channel || status.context_ready !== undefined || status.tx_ready !== undefined) {
    lines.push(`桥接类型：${status.bridge || '--'}`);
    lines.push(`Context：${boolText(status.context_ready)}，TX：${boolText(status.tx_ready)}`);
    if (status.request_queue_size !== undefined) {
      lines.push(`请求队列：${status.request_queue_size}`);
    }
  }
  if (data.status_error || (status && status.status_error)) {
    lines.push(`状态探测提示：${data.status_error || status.status_error}`);
  }
  if (data.error) {
    lines.push(`错误：${data.error}`);
  }
  if (label === '普通 QMT') {
    lines.push('');
    lines.push('提示：非交易时间普通 QMT 的回调触发可能较慢，状态检测或委托查询可能短暂超时并进入 cooldown；通常不影响使用，稍后刷新即可。');
  }
  return lines;
}

function renderBridgeSelect(bridges) {
  state.bridges = bridges || {};
  const bridgeSelect = $('bridgeSelect');
  if (!bridgeSelect) return;
  const current = bridgeIdForAccount(state.accountId, state.accountType) || bridgeSelect.value || state.bridgeId;
  const optionsHtml = Object.keys(state.bridges).map((id) => {
    const bridge = state.bridges[id] || {};
    return `<option value="${plain(id)}">${plain(bridge.name || id)}</option>`;
  }).join('');
  bridgeSelect.innerHTML = optionsHtml;
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
  const managed = !!(data && data.managed);
  const active = shouldUseLttxStatus();
  const processes = data && Array.isArray(data.processes) ? data.processes : [];
  const processText = processes.map((item) => `${item.pid || ''} ${item.name || ''}`.trim()).filter(Boolean).join(', ');
  const addressText = data ? `${data.host}:${data.port}` : '--';
  const pidText = processes.map((item) => item.pid).filter(Boolean).join(', ')
    || ((data && data.managed_pids || []).join(', '))
    || (running ? '端口已监听' : '--');
  const roleText = active ? '高级双桥 / 库入口' : '库入口 / 自动发现';
  const policyText = '重启保留';
  const detail = data ? [
    `状态：${running ? '运行中' : '未运行'}`,
    `地址：${addressText}`,
    `PID：${pidText}`,
    `本系统进程：${managed ? '是' : '未确认'}`,
    `用途：cfquant Python 库自动发现与 Web 统一路由入口`,
    `策略：Web 重启和定时重启保留 LTtx，完整退出时停止`,
    processText ? `进程：${processText}` : '',
  ] : ['LTtx 状态未知', '用途：cfquant Python 库自动发现与 Web 统一路由入口'];
  setStatus('lttxStatus', running, detail);

  const addressNode = $('lttxAddress');
  const pidNode = $('lttxPid');
  const libraryNode = $('lttxLibraryStatus');
  const policyNode = $('lttxRestartPolicy');
  if (addressNode) addressNode.textContent = addressText;
  if (pidNode) pidNode.textContent = pidText;
  if (libraryNode) libraryNode.textContent = running ? (managed ? roleText : '端口已监听') : '不可用';
  if (policyNode) policyNode.textContent = running ? policyText : '启动补齐';

  const startBtn = $('lttxStartBtn');
  const stopBtn = $('lttxStopBtn');
  if (startBtn) {
    startBtn.dataset.runtimeDisabled = (data && !data.can_start) ? 'true' : 'false';
    startBtn.disabled = startBtn.dataset.runtimeDisabled === 'true';
  }
  if (stopBtn) {
    stopBtn.dataset.runtimeDisabled = 'true';
    stopBtn.title = 'LTtx 在 Web 重启和定时重启时保持运行，完整退出 cfquant 时停止。';
    stopBtn.disabled = stopBtn.dataset.runtimeDisabled === 'true';
  }

  const runtime = $('lttxRuntime');
  if (!runtime) return;
  if (running && managed) {
    runtime.textContent = `LTtx 运行中，cfquant Python 库可通过 ${addressText} 发现 Web 统一路由。Web 重启和定时重启会保留 LTtx。`;
  } else if (running) {
    runtime.textContent = `${addressText} 已监听，但无法确认是本系统启动的 LTtx；cfquant Python 库会尝试通过该端口发现 Web 统一路由。`;
  } else if (!data) {
    runtime.textContent = 'LTtx 状态未知';
  } else {
    runtime.textContent = `LTtx 未运行，cfquant Python 库自动发现不可用；可通过网页或 cfquant\\start_cfquant.bat 启动。`;
  }
}

async function refreshLttxStatus(options = {}) {
  try {
    const data = await api('/api/lttx');
    renderLttxStatus(data);
    return data;
  } catch (error) {
    setStatus('lttxStatus', false, error.message);
    if (options.keepRuntimeMessage) {
      state.lttxStatus = null;
      const runtime = $('lttxRuntime');
      if (runtime) runtime.textContent = options.keepRuntimeMessage;
    } else {
      renderLttxStatus(null);
    }
    if (options.log !== false) {
      log('LTtx 状态检查失败', { error: error.message });
    }
    return null;
  }
}

async function loadConfigLegacy() {
  const data = await api('/api/config');
  state.defaultAccountId = data.default_account_id || '';
  state.defaultAccountType = normalizeAccountType(data.default_account_type || (data.setup && data.setup.default_account_type) || 'STOCK');
  state.defaultAccountKey = data.default_account_key || (data.setup && data.setup.default_account_key) || '';
  const bridges = data.bridges || {};
  state.envBridges = data.env_bridges || {};
  state.accountPairs = data.account_pairs || {};
  state.accountConfigs = data.account_configs || {};
  state.setup = data.setup || null;
  state.defaultAccountId = data.default_account_id || state.defaultAccountId;
  state.defaultBridgeId = data.default_bridge_id || 'default';
  state.accountKey = localStorage.getItem(ACCOUNT_SELECTION_KEY) || state.defaultAccountKey || '';
  state.accountId = localStorage.getItem('cfquant.account') || state.defaultAccountId || '';
  state.accountType = state.defaultAccountType || 'STOCK';
  state.bridgeId = localStorage.getItem('cfquant.bridge_id') || state.defaultBridgeId;
  if (!bridges[state.bridgeId]) {
    state.bridgeId = state.defaultBridgeId || Object.keys(bridges)[0] || 'default';
  }
  renderBridgeSelect(bridges);
  renderAccountSelect(state.defaultAccountId);
  applyAccountPair(state.accountKey || state.accountId);
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
  syncTransportChannelControls();
  selectedChannel();
  selectedTradeChannel();
  renderAccountPairs();
  renderBridgeConfigList();
  renderCachedBindingStatuses();
  renderApiKeyStatus(data.api_key);
  const apiBaseInput = $('apiBaseUrlInput');
  if (apiBaseInput) {
    const savedBaseUrl = data.server_access && data.server_access.api_base_url
      ? data.server_access.api_base_url
      : window.location.origin;
    apiBaseInput.value = normalizeApiBaseUrl(savedBaseUrl);
  }
  renderServerAccess(data.server_access);
  renderUserProfile(data.user_profile);
  renderLogCleanup(data.log_cleanup);
  renderQmtLogLanguage(data.qmt_log_language);
  renderProjectVersion(data.version);
  if (!data.auth_required) {
    refreshProjectVersion({ remote: true, log: false }).catch((error) => log('版本状态初始化失败', { error: error.message }));
    refreshProjectUpdateStatus({ remote: false, log: false }).catch((error) => log('Web 项目更新状态初始化失败', { error: error.message }));
  }
  refreshUpdateStatus({ log: false }).catch((error) => log('更新状态初始化失败', { error: error.message }));
  refreshBindingStatuses().catch((error) => log('绑定状态初始化失败', { error: error.message }));
  log('Web TX', { reply_channel: data.reply_channel });
}

async function loadConfig() {
  const data = await api('/api/config');
  state.defaultAccountId = data.default_account_id || '';
  state.defaultAccountType = normalizeAccountType(data.default_account_type || (data.setup && data.setup.default_account_type) || 'STOCK');
  state.defaultAccountKey = data.default_account_key || (data.setup && data.setup.default_account_key) || '';
  const bridges = data.bridges || {};
  state.envBridges = data.env_bridges || {};
  state.accountPairs = data.account_pairs || {};
  state.accountConfigs = data.account_configs || {};
  state.setup = data.setup || null;
  state.defaultAccountId = data.default_account_id || state.defaultAccountId;
  state.defaultBridgeId = data.default_bridge_id || 'default';
  state.accountKey = localStorage.getItem(ACCOUNT_SELECTION_KEY) || state.defaultAccountKey || '';
  state.accountId = localStorage.getItem('cfquant.account') || state.defaultAccountId || '';
  state.accountType = state.defaultAccountType || 'STOCK';
  state.bridgeId = localStorage.getItem('cfquant.bridge_id') || state.defaultBridgeId;
  if (!bridges[state.bridgeId]) {
    state.bridgeId = state.defaultBridgeId || Object.keys(bridges)[0] || 'default';
  }
  renderBridgeSelect(bridges);
  renderAccountSelect(state.defaultAccountId);
  applyAccountPair(state.accountKey || state.accountId);
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
  syncTransportChannelControls();
  selectedChannel();
  selectedTradeChannel();
  renderAccountPairs();
  renderBridgeConfigList();
  renderCachedBindingStatuses();
  renderApiKeyStatus(data.api_key);
  const apiBaseInput = $('apiBaseUrlInput');
  if (apiBaseInput && !apiBaseInput.value.trim()) {
    const savedBaseUrl = data.server_access && data.server_access.api_base_url
      ? data.server_access.api_base_url
      : window.location.origin;
    apiBaseInput.value = normalizeApiBaseUrl(savedBaseUrl);
  }
  renderServerAccess(data.server_access);
  renderUserProfile(data.user_profile);
  renderPipeHub(data.pipe_hub);
  renderTransport(data.transport);
  renderLogCleanup(data.log_cleanup);
  renderQmtLogLanguage(data.qmt_log_language);
  renderProjectVersion(data.version);
  if (!data.auth_required) {
    refreshProjectVersion({ remote: true, log: false }).catch((error) => log('版本状态初始化失败', { error: error.message }));
    refreshProjectUpdateStatus({ remote: false, log: false }).catch((error) => log('Web 项目更新状态初始化失败', { error: error.message }));
  }
  syncOnboardingWizard();
  if (!data.auth_required) saveAccountConfigCache(data);
  log('Web TX', { reply_channel: data.reply_channel || '', auth_required: !!data.auth_required });
  return data;
}

async function startAuthenticatedApp() {
  if (state.appStarted) return;
  state.appStarted = true;
  renderApiDocs();
  if (!state.bindingStatusRefreshInFlight) {
    state.bindingStatusRefreshInFlight = true;
    refreshBindingStatuses()
      .catch((error) => log('绑定状态初始化失败', { error: error.message }))
      .finally(() => {
        state.bindingStatusRefreshInFlight = false;
      });
  }
  refreshStatus().catch((error) => log('状态初始化失败', { error: error.message }));
  refreshProjectVersion({ remote: true, log: false }).catch((error) => log('版本状态初始化失败', { error: error.message }));
  refreshProjectUpdateStatus({ remote: false, log: false }).catch((error) => log('Web 项目更新状态初始化失败', { error: error.message }));
  refreshInitialAccountData().catch((error) => log('账号数据初始化失败', { error: error.message }));
  refreshUpdateStatus({ log: false }).catch((error) => log('更新状态初始化失败', { error: error.message }));
  connectOrderCallbackSocket({ force: true });
  startTimers();
}

async function refreshInitialAccountData() {
  const requests = [
    {
      sections: 'asset,positions',
      options: undefined,
      error: '初始化查询失败',
    },
    {
      sections: 'orders',
      options: { force: true, subscribe: false },
      error: '委托初始化失败',
    },
    {
      sections: 'trades',
      options: undefined,
      error: '成交初始化失败',
    },
  ];
  for (const request of requests) {
    try {
      await refreshAccount(request.sections, request.options);
    } catch (error) {
      log(request.error, { error: error.message });
    }
  }
}

async function refreshStatus() {
  const lttxPromise = refreshLttxStatus({ log: false });
  const transportPromise = refreshTransport();
  try {
    const params = new URLSearchParams();
    params.set('account_id', selectedAccount());
    params.set('account_type', selectedAccountType());
    params.set('account_key', selectedAccountKey());
    params.set('bridge_id', selectedBridge());
    const data = await api(`/api/status?${params.toString()}`);
    state.bridgeStatus = data;
    const lttx = await lttxPromise;
    const transport = await transportPromise;
    renderTransport(transport);
    state.accountRouteMode = data.effective_mode || data.preferred_mode || state.accountRouteMode || state.transportMode || 'ctypes';
    state.accountRouteFallback = !!data.fallback;
    syncTopStatusDisplay();
    syncTransportChannelControls();
    const routeMode = state.accountRouteMode;
    const routeIsPipe = isCtypesTransportMode(routeMode);
    const pipeLabel = transportModeLabel(routeMode, true);
    const normalLabel = routeIsPipe ? `${pipeLabel}查询通道` : '高级模式·普通 QMT';
    const tradeLabel = routeIsPipe ? `${pipeLabel}交易通道` : '高级模式·极速交易端';
    const normalLabelNode = $('normalStatusLabel');
    const tradeLabelNode = $('tradeStatusLabel');
    if (normalLabelNode) normalLabelNode.textContent = routeIsPipe ? `${pipeLabel}查询通道` : '普通 QMT';
    if (tradeLabelNode) tradeLabelNode.textContent = routeIsPipe ? `${pipeLabel}交易通道` : '极速交易端';
    const status = data.status || data;
    setStatus('normalStatus', !!(status.normal && status.normal.online), statusTooltipLines(normalLabel, status.normal || {}, data));
    setStatus('tradeStatus', !!(status.trade && status.trade.online), statusTooltipLines(tradeLabel, status.trade || {}, data));
    $('statusDetail').textContent = JSON.stringify({ lttx, bridge: data }, null, 2);
  } catch (error) {
    const lttx = await lttxPromise;
    const transport = await transportPromise;
    state.bridgeStatus = null;
    renderTransport(transport);
    state.accountRouteMode = activeAccountMode();
    state.accountRouteFallback = false;
    syncTopStatusDisplay();
    syncTransportChannelControls();
    const routeMode = state.accountRouteMode;
    const routeIsPipe = isCtypesTransportMode(routeMode);
    const pipeLabel = transportModeLabel(routeMode, true);
    const normalLabel = routeIsPipe ? `${pipeLabel}查询通道` : '高级模式·普通 QMT';
    const tradeLabel = routeIsPipe ? `${pipeLabel}交易通道` : '高级模式·极速交易端';
    const normalLabelNode = $('normalStatusLabel');
    const tradeLabelNode = $('tradeStatusLabel');
    if (normalLabelNode) normalLabelNode.textContent = routeIsPipe ? `${pipeLabel}查询通道` : '普通 QMT';
    if (tradeLabelNode) tradeLabelNode.textContent = routeIsPipe ? `${pipeLabel}交易通道` : '极速交易端';
    setStatus('normalStatus', false, [
      `${normalLabel}：状态检查失败`,
      `内部通道：${selectedBridge()}`,
      `错误：${error.message}`,
      '',
      '提示：非交易时间普通 QMT 的回调触发可能较慢，状态检测或委托查询可能短暂超时并进入 cooldown；通常不影响使用，稍后刷新即可。',
    ]);
    setStatus('tradeStatus', false, [
      `${tradeLabel}：状态检查失败`,
      `内部通道：${selectedBridge()}`,
      `错误：${error.message}`,
    ]);
    $('statusDetail').textContent = JSON.stringify({ lttx, error: error.message }, null, 2);
    log('状态检查失败', { error: error.message });
  }
}

async function startLttx() {
  const startBtn = $('lttxStartBtn');
  const stopBtn = $('lttxStopBtn');
  const runtime = $('lttxRuntime');
  const originalText = startBtn ? startBtn.textContent : '';
  if (startBtn) startBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = true;
  if (startBtn) startBtn.textContent = '启动中...';
  if (runtime) runtime.textContent = '正在启动 LTtx，请稍候...';
  setStatus('lttxStatus', false, 'LTtx 正在启动');
  try {
    const data = await api('/api/lttx/start', { method: 'POST', body: '{}' });
    renderLttxStatus(data.status);
    if (runtime) {
      const status = data.status || {};
      const addressText = status.host && status.port ? `${status.host}:${status.port}` : '';
      runtime.textContent = data.started
        ? `LTtx 已启动${addressText ? `，监听 ${addressText}` : ''}。`
        : (data.reason || 'LTtx 已在运行。');
    }
    log(data.started ? 'LTtx 已启动' : 'LTtx 已在运行', data);
    await refreshStatus();
  } catch (error) {
    if (runtime) runtime.textContent = `LTtx 启动失败：${error.message}`;
    setStatus('lttxStatus', false, `LTtx 启动失败：${error.message}`);
    log('LTtx 启动失败', { error: error.message });
    await refreshLttxStatus({ log: false, keepRuntimeMessage: `LTtx 启动失败：${error.message}` });
  } finally {
    if (startBtn) {
      startBtn.textContent = originalText || '启动 LTtx';
      startBtn.disabled = startBtn.dataset.runtimeDisabled === 'true';
    }
    if (stopBtn) stopBtn.disabled = stopBtn.dataset.runtimeDisabled === 'true';
  }
}

async function stopLttx() {
  await refreshLttxStatus({ log: false });
  log('LTtx 会随 cfquant 完整退出停止，Web 重启和定时重启不会停止 LTtx');
}

function selectedAccount() {
  const info = selectedAccountInfo();
  state.accountKey = info.accountKey || '';
  state.accountId = info.accountId || '';
  state.accountType = normalizeAccountType(info.accountType || 'STOCK');
  if (state.accountKey) localStorage.setItem(ACCOUNT_SELECTION_KEY, state.accountKey);
  if (state.accountId) localStorage.setItem('cfquant.account', state.accountId);
  return state.accountId;
}

function selectedAccountType() {
  selectedAccount();
  return normalizeAccountType(state.accountType || 'STOCK');
}

function selectedAccountKey() {
  selectedAccount();
  return state.accountKey || makeAccountKey(state.accountId, state.accountType, selectedBridge());
}

function selectedBridge() {
  const select = $('bridgeSelect');
  const info = selectedAccountInfo();
  const accountBridgeId = info.bridgeId || bridgeIdForAccount(info.accountId, info.accountType);
  const bridgeId = accountBridgeId || (select ? select.value : '') || state.bridgeId || 'default';
  if (select && state.bridges && state.bridges[bridgeId]) {
    select.value = bridgeId;
  }
  localStorage.setItem('cfquant.bridge_id', bridgeId);
  state.bridgeId = bridgeId;
  return bridgeId;
}

function selectedChannel() {
  const mode = activeAccountMode();
  state.queryChannel = isCtypesTransportMode(mode) ? 'normal' : 'trade';
  if ($('queryChannel')) $('queryChannel').value = state.queryChannel;
  localStorage.setItem('cfquant.query_channel', state.queryChannel);
  return state.queryChannel;
}

function selectedTradeChannel() {
  const mode = activeAccountMode();
  const channel = isCtypesTransportMode(mode) || normalizeTransportMode(mode) === 'lttx'
    ? 'trade'
    : (($('tradeChannel') && $('tradeChannel').value) || 'trade');
  if ($('tradeChannel')) $('tradeChannel').value = channel;
  localStorage.setItem('cfquant.trade_channel', channel);
  return channel;
}

function resetSelectionState() {
  state.callbackSeq = 0;
  state.callbackEvents = [];
  state.callbackLastEventAt = '';
  state.callbackLastEventName = '';
  state.orderSnapshot.clear();
  state.orderSnapshotReady = false;
  state.orderHighlights.clear();
  state.orderCallbackMeta.clear();
  state.cfquantOrderIds.clear();
  state.cfquantOrderRemarks.clear();
  state.orderCallbackRefreshSections.clear();
  state.orderCallbackRefreshPending = false;
  if (state.orderHighlightTimer) {
    window.clearTimeout(state.orderHighlightTimer);
    state.orderHighlightTimer = null;
  }
  if (state.orderCallbackRefreshTimer) {
    window.clearTimeout(state.orderCallbackRefreshTimer);
    state.orderCallbackRefreshTimer = null;
  }
  renderCallbacks();
}

function refreshCurrentSelection(reason) {
  restartOrderCallbackSocket();
  refreshStatus().catch((error) => log(`${reason}状态刷新失败`, { error: error.message }));
  refreshAccount('asset,positions').catch((error) => log(`${reason}资产刷新失败`, { error: error.message }));
  refreshAccount('orders', { force: true, subscribe: false }).catch((error) => log(`${reason}委托刷新失败`, { error: error.message }));
  refreshAccount('trades').catch((error) => log(`${reason}成交刷新失败`, { error: error.message }));
}

function handleBridgeChange() {
  selectedBridge();
  syncBindingForm();
  resetSelectionState();
  refreshCurrentSelection('桥接端');
  refreshUpdateStatus({ log: false }).catch((error) => log('桥接端更新状态刷新失败', { error: error.message }));
}

function handleAccountChange() {
  const accountId = selectedAccount();
  if (!accountId) {
    log('请选择账号');
    return;
  }
  const info = selectedAccountInfo();
  applyAccountPair(info.accountKey || accountId);
  state.accountRouteMode = (info.config && info.config.mode) || state.transportMode || 'ctypes';
  state.accountRouteFallback = false;
  syncBindingForm();
  resetSelectionState();
  syncTopStatusDisplay();
  syncTransportChannelControls();
  syncCreditOrderControls();
  refreshCurrentSelection('账号');
}

function switchAccountFromToolbar() {
  const accountId = selectedAccount();
  if (!accountId) {
    log('账号为空，无法切换');
    return;
  }
  handleAccountChange();
  log('账号已切换', { account_id: accountId, account_type: selectedAccountType(), account_key: selectedAccountKey() });
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
  const counts = section && section.market_counts ? section.market_counts : null;
  const countParts = counts
    ? ['SH', 'SZ'].filter((market) => Object.prototype.hasOwnProperty.call(counts, market)).map((market) => `${market} ${counts[market]}`)
    : [];
  const routeText = countParts.length ? `（${countParts.join(' / ')}）` : '';
  const countNode = $('positionCount');
  countNode.textContent = `${rows.length} 条${routeText}`;
  countNode.title = section && Array.isArray(section.partial_errors) ? section.partial_errors.join('\n') : '';
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

function meaningfulOrderId(...values) {
  for (const value of values) {
    if (!hasValue(value)) continue;
    const text = String(value).trim();
    if (!text || text === '-' || text === '--' || text === '-1') continue;
    return text;
  }
  return '';
}

function orderKey(row) {
  if (!row || typeof row !== 'object') return '';
  return meaningfulOrderId(
    row.order_sysid,
    row.m_strOrderSysID,
    row.order_id,
    row.m_strOrderID,
    row.m_nOrderID,
    row.entrust_no,
    row.contract_no,
    row.m_strContractNo,
  );
}

function orderCode(row) {
  return row.stock_code || `${row.m_strInstrumentID || ''}.${row.m_strExchangeID || ''}`;
}

function orderName(row) {
  return row.instrument_name || row.m_strInstrumentName || row.stock_name || row.name || '';
}

function orderRemark(row) {
  return firstField(row, [
    'order_remark',
    'remark',
    'strategy_name',
    'm_strRemark',
    'm_strOrderRemark',
    'm_strStrategyName',
  ]);
}

function isCfquantOrder(row) {
  const id = orderKey(row);
  if (id && state.cfquantOrderIds.has(id)) return true;
  const explicitSource = String(row.order_source || row.source || '').trim().toLowerCase();
  if (explicitSource === 'cfquant') return true;
  const remark = String(orderRemark(row) || '').trim();
  if (remark && state.cfquantOrderRemarks.has(remark)) return true;
  return /^cfquant(?:_|$)/i.test(remark) || /(?:^|[_\-\s])cfquant(?:[_\-\s]|$)/i.test(remark);
}

function orderSource(row) {
  return isCfquantOrder(row) ? 'cfquant' : '其他';
}

function orderSourceClass(row) {
  return isCfquantOrder(row) ? 'source-cfquant' : 'source-other';
}

function rememberCfquantOrder(value) {
  if (!value) return;
  if (Array.isArray(value)) {
    value.forEach((item) => rememberCfquantOrder(item));
    return;
  }
  if (typeof value !== 'object') return;
  const id = meaningfulOrderId(
    value.order_sysid,
    value.m_strOrderSysID,
    value.order_id,
    value.m_strOrderID,
    value.m_nOrderID,
    value.entrust_no,
    value.contract_no,
  );
  const remark = String(
    value.order_remark
    || value.remark
    || value.m_strRemark
    || value.m_strOrderRemark
    || '',
  ).trim();
  if (id) state.cfquantOrderIds.add(id);
  if (remark) state.cfquantOrderRemarks.add(remark);
  if (value.result) rememberCfquantOrder(value.result);
  if (value.results) rememberCfquantOrder(value.results);
  if (value.request_result && typeof value.request_result === 'object') rememberCfquantOrder(value.request_result);
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

const ORDER_SORT_COLUMNS = {
  time: { type: 'number', defaultDirection: 'desc' },
  source: { type: 'text', defaultDirection: 'asc' },
  code: { type: 'text', defaultDirection: 'asc' },
  name: { type: 'text', defaultDirection: 'asc' },
  volume: { type: 'number', defaultDirection: 'desc' },
  traded: { type: 'number', defaultDirection: 'desc' },
  status: { type: 'text', defaultDirection: 'asc' },
  id: { type: 'text', defaultDirection: 'asc' },
};

function dateDigitsForSort(value) {
  if (!hasValue(value)) return '';
  const digits = String(value).trim().replace(/\D/g, '');
  return digits.length >= 8 ? digits.slice(0, 8) : '';
}

function clockDigitsForSort(value) {
  if (!hasValue(value)) return '';
  const text = String(value).trim();
  const clockMatch = text.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if (clockMatch) {
    return `${clockMatch[1].padStart(2, '0')}${clockMatch[2]}${clockMatch[3] || '00'}`;
  }
  const digits = text.replace(/\D/g, '');
  return digits && digits.length <= 6 ? digits.padStart(6, '0') : '';
}

function tradeDataTimeSortValue(value, dateValue) {
  if (!hasValue(value)) return null;
  const text = String(value).trim();
  const digits = text.replace(/\D/g, '');
  if (digits.length === 13 && digits.startsWith('1')) return Number(digits);
  if (digits.length === 10 && digits.startsWith('1')) return Number(digits) * 1000;
  if (digits.length >= 14) return Number(digits.slice(0, 14));
  if (digits.length === 12) return Number(`${digits}00`);

  const clock = clockDigitsForSort(text);
  if (clock) {
    const date = dateDigitsForSort(dateValue);
    return Number(date ? `${date}${clock}` : clock);
  }
  return null;
}

function orderTimeSortValue(row) {
  return tradeDataTimeSortValue(firstField(row, ORDER_TIME_FIELDS), firstField(row, ORDER_DATE_FIELDS));
}

function orderSortValue(row, key) {
  if (key === 'time') return orderTimeSortValue(row);
  if (key === 'source') return orderSource(row);
  if (key === 'code') return orderCode(row);
  if (key === 'name') return orderName(row);
  if (key === 'volume') return orderVolume(row);
  if (key === 'traded') return tradedVolume(row);
  if (key === 'status') return orderStatus(row);
  if (key === 'id') return orderKey(row);
  return '';
}

function compareOrderSortValues(left, right, column, direction) {
  const type = column.type;
  const leftMissing = type === 'number' ? !Number.isFinite(Number(left)) : !hasValue(left);
  const rightMissing = type === 'number' ? !Number.isFinite(Number(right)) : !hasValue(right);
  if (leftMissing && rightMissing) return 0;
  if (leftMissing) return 1;
  if (rightMissing) return -1;

  let result = 0;
  if (type === 'number') {
    result = Number(left) - Number(right);
  } else {
    result = String(left).localeCompare(String(right), 'zh-CN', { numeric: true, sensitivity: 'base' });
  }
  return direction === 'desc' ? -result : result;
}

function sortedOrderRows(rows) {
  const sort = state.orderSort || { key: 'time', direction: 'desc' };
  const column = ORDER_SORT_COLUMNS[sort.key] || ORDER_SORT_COLUMNS.time;
  const direction = sort.direction === 'asc' ? 'asc' : 'desc';
  return rows.map((row, index) => ({ row, index })).sort((left, right) => {
    const result = compareOrderSortValues(
      orderSortValue(left.row, sort.key),
      orderSortValue(right.row, sort.key),
      column,
      direction,
    );
    if (result !== 0) return result;
    return direction === 'desc' ? right.index - left.index : left.index - right.index;
  }).map((item) => item.row);
}

function renderOrderSortHeaders() {
  document.querySelectorAll('[data-order-sort]').forEach((button) => {
    const active = button.dataset.orderSort === state.orderSort.key;
    const mark = button.querySelector('.sort-mark');
    button.classList.toggle('active', active);
    button.dataset.direction = active ? state.orderSort.direction : '';
    if (mark) mark.textContent = active ? (state.orderSort.direction === 'asc' ? '↑' : '↓') : '';
  });
}

function setOrderSort(key) {
  const column = ORDER_SORT_COLUMNS[key];
  if (!column) return;
  const current = state.orderSort || {};
  const direction = current.key === key
    ? (current.direction === 'asc' ? 'desc' : 'asc')
    : column.defaultDirection;
  state.orderSort = { key, direction };
  renderOrderSortHeaders();
  renderOrders({ data: state.latestOrders || [] });
}

function wireOrderSortHeaders() {
  document.querySelectorAll('[data-order-sort]').forEach((button) => {
    button.addEventListener('click', () => setOrderSort(button.dataset.orderSort));
  });
  renderOrderSortHeaders();
}

function pruneOrderHighlights(now = Date.now()) {
  let changed = false;
  state.orderHighlights.forEach((highlight, id) => {
    if (!highlight || highlight.expiresAt <= now) {
      state.orderHighlights.delete(id);
      changed = true;
    }
  });
  return changed;
}

function scheduleOrderHighlightCleanup() {
  if (state.orderHighlightTimer) {
    window.clearTimeout(state.orderHighlightTimer);
    state.orderHighlightTimer = null;
  }
  const expires = Array.from(state.orderHighlights.values()).map((item) => item.expiresAt);
  if (!expires.length) return;
  const nextExpiresAt = Math.min(...expires);
  const delay = Math.max(120, nextExpiresAt - Date.now() + 40);
  state.orderHighlightTimer = window.setTimeout(() => {
    state.orderHighlightTimer = null;
    const changed = pruneOrderHighlights();
    if (changed) renderOrders({ data: state.latestOrders || [] });
    if (state.orderHighlights.size) scheduleOrderHighlightCleanup();
  }, delay);
}

function markOrderHighlight(id, type) {
  if (!id) return;
  state.orderHighlights.set(id, {
    type,
    expiresAt: Date.now() + ORDER_HIGHLIGHT_MS,
  });
  scheduleOrderHighlightCleanup();
}

function orderHighlightType(row) {
  const id = orderKey(row);
  if (!id) return '';
  const highlight = state.orderHighlights.get(id);
  if (!highlight) return '';
  if (highlight.expiresAt <= Date.now()) {
    state.orderHighlights.delete(id);
    return '';
  }
  return highlight.type || 'updated';
}

function trackOrderEvents(rows) {
  const shouldHighlight = state.orderSnapshotReady;
  rows.forEach((row) => {
    const id = orderKey(row);
    if (!id) return;
    const snapshot = {
      code: orderCode(row),
      name: orderName(row),
      order_id: id,
      time: orderTime(row),
      source: orderSource(row),
      volume: row.order_volume ?? row.m_nVolumeTotalOriginal,
      traded: row.traded_volume ?? row.m_nVolumeTraded,
      status: orderStatus(row),
    };
    const previous = state.orderSnapshot.get(id);
    const changed = !previous || JSON.stringify(previous) !== JSON.stringify(snapshot);
    if (changed) {
      state.orderSnapshot.set(id, snapshot);
      if (shouldHighlight) markOrderHighlight(id, previous ? 'updated' : 'new');
    }
  });
  state.orderSnapshotReady = true;
  while (state.orderSnapshot.size > ORDER_SNAPSHOT_LIMIT) {
    const oldest = state.orderSnapshot.keys().next().value;
    if (!oldest) break;
    state.orderSnapshot.delete(oldest);
    state.orderHighlights.delete(oldest);
  }
  pruneOrderHighlights();
}

function timestampMs(value) {
  if (!hasValue(value)) return 0;
  if (value instanceof Date) return value.getTime();
  const text = String(value).trim();
  if (!text) return 0;
  if (!/^-?\d+(\.\d+)?$/.test(text)) {
    const parsed = Date.parse(text);
    return Number.isNaN(parsed) ? 0 : parsed;
  }
  const number = Number(text);
  if (!Number.isFinite(number) || number <= 0) return 0;
  if (number > 100000000000) return Math.round(number);
  if (number > 100000000) return Math.round(number * 1000);
  return 0;
}

function formatDateTimeMs(value) {
  const ms = timestampMs(value);
  if (!ms) return nowText();
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return nowText();
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}.${String(date.getMilliseconds()).padStart(3, '0')}`;
}

function callbackEventRawName(event) {
  if (!event || typeof event !== 'object') return '';
  if (typeof event.event === 'string') return event.event;
  if (typeof event.type === 'string') return event.type;
  return '';
}

function callbackEventName(event) {
  return callbackEventRawName(event).toLowerCase();
}

function callbackEventLabel(eventName) {
  const name = String(eventName || '').toLowerCase();
  if (name.includes('on_order_error')) return '下单错误';
  if (name.includes('on_cancel_error')) return '撤单错误';
  if (name.includes('on_stock_trade') || name.includes('deal')) return '成交回调';
  if (name.includes('on_stock_order')) return '委托回调';
  if (name.includes('on_stock_asset') || name.includes('account')) return '资金回调';
  if (name.includes('on_stock_position') || name.includes('position')) return '持仓回调';
  if (name.includes('async_response')) return '异步响应';
  return eventName || '回调事件';
}

function callbackEventClass(eventName) {
  const name = String(eventName || '').toLowerCase();
  if (name.includes('error')) return 'callback-event-error';
  if (name.includes('trade') || name.includes('deal')) return 'callback-event-trade';
  if (name.includes('order') || name.includes('cancel')) return 'callback-event-order';
  return 'callback-event-other';
}

function callbackEventData(event) {
  let data = event && event.data !== undefined
    ? event.data
    : (event && event.payload !== undefined ? event.payload : null);
  if ((data === null || data === undefined) && event && event.result !== undefined) {
    data = event.result;
  }
  if (data === null || data === undefined) data = event;
  if (data && typeof data === 'object' && data.__cf_type__ === 'object' && data.attrs) {
    return data.attrs;
  }
  if (Array.isArray(data)) return { items: data };
  return data && typeof data === 'object' ? data : {};
}

function callbackReceivedMs(event) {
  return timestampMs(event && event.received_at)
    || timestampMs(event && event.ts)
    || timestampMs(event && event.timestamp)
    || Date.now();
}

function callbackStockCode(data) {
  const direct = firstField(data, ['stock_code', 'security_code', 'code', 'm_strStockCode']);
  if (direct) return direct;
  const instrument = firstField(data, ['m_strInstrumentID', 'instrument_id']);
  const exchange = firstField(data, ['m_strExchangeID', 'exchange_id', 'market']);
  if (instrument && exchange) return `${instrument}.${exchange}`;
  return instrument || '';
}

function callbackOrderId(data) {
  return meaningfulOrderId(
    data.order_sysid,
    data.m_strOrderSysID,
    data.order_id,
    data.orderId,
    data.m_strOrderID,
    data.m_nOrderID,
    data.entrust_no,
    data.contract_no,
    data.m_strContractNo,
  );
}

function callbackSource(event, data) {
  const source = firstField(event || {}, ['source', 'channel'])
    || firstField(data || {}, ['source', 'order_source', 'callback_source']);
  if (!source) return 'callback';
  if (source === '__client__') return 'web';
  return source;
}

function callbackStatus(data) {
  return orderStatus(data)
    || data.status_msg
    || data.m_strStatusMsg
    || data.error_msg
    || data.err_msg
    || data.msg
    || data.message
    || '';
}

function normalizeCallbackEvent(event) {
  const data = callbackEventData(event);
  const rawName = callbackEventRawName(event) || 'callback';
  const receivedMs = callbackReceivedMs(event);
  const accountId = firstField(event || {}, ['account_id', 'm_strAccountID'])
    || firstField(data, ['account_id', 'm_strAccountID']);
  const accountType = firstField(event || {}, ['account_type'])
    || firstField(data, ['account_type']);
  const volume = firstField(data, ['order_volume', 'm_nVolumeTotalOriginal', 'volume', 'm_nVolume']);
  const traded = firstField(data, ['traded_volume', 'm_nVolumeTraded', 'deal_volume', 'm_nDealVolume']);
  const price = firstField(data, ['price', 'entrust_price', 'm_dPrice', 'm_dOrderPrice', 'traded_price', 'm_dTradedPrice']);
  const row = {
    seq: Number(event.seq || 0),
    received_ms: receivedMs,
    time: formatDateTimeMs(receivedMs),
    type: rawName,
    label: callbackEventLabel(rawName),
    className: callbackEventClass(rawName),
    cached: !!event.cached,
    bridge_id: firstField(event || {}, ['bridge_id']) || firstField(data, ['bridge_id']),
    account_id: accountId,
    account_type: accountType,
    source: callbackSource(event, data),
    code: callbackStockCode(data),
    name: firstField(data, ['instrument_name', 'm_strInstrumentName', 'stock_name', 'name']),
    order_id: callbackOrderId(data),
    volume,
    traded,
    price,
    status: callbackStatus(data),
    payload_fields: data && typeof data === 'object' ? Object.keys(data).length : 0,
    payload: data,
    raw: event,
  };
  row.summary = [
    row.code,
    row.name,
    row.order_id ? `编号 ${row.order_id}` : '',
    hasValue(row.volume) ? `数量 ${row.volume}` : '',
    hasValue(row.traded) ? `成交 ${row.traded}` : '',
    row.status,
  ].filter(Boolean).join(' / ');
  return row;
}

function updateCallbackStatusUi() {
  const status = $('callbackSocketStatus');
  const stateMap = {
    idle: '未连接',
    connecting: '连接中',
    open: '已连接',
    closed: '已断开',
    disabled: '已关闭',
    error: '异常',
  };
  if (status) {
    const label = stateMap[state.orderCallbackSocketState] || state.orderCallbackSocketState || '未连接';
    status.textContent = state.orderCallbackSocketDetail ? `${label} / ${state.orderCallbackSocketDetail}` : label;
    status.className = state.orderCallbackSocketState === 'open' ? 'is-ok' : (state.orderCallbackSocketState === 'error' ? 'is-error' : '');
  }
  const filter = $('callbackFilterStatus');
  if (filter) {
    const accountId = selectedAccount() || '--';
    filter.textContent = `${selectedBridge()} / ${accountTypeLabel(selectedAccountType())} / ${accountId} / trader:*`;
  }
  const last = $('callbackLastEventStatus');
  if (last) {
    last.textContent = state.callbackLastEventAt
      ? `${state.callbackLastEventAt} / ${state.callbackLastEventName || '回调'}`
      : '尚未收到真实回调';
  }
  const seq = $('callbackSeqStatus');
  if (seq) {
    const hello = state.orderCallbackHello || {};
    const clientCount = hello.clients ?? hello.client_count;
    const clients = hasValue(clientCount) ? ` / clients ${clientCount}` : '';
    seq.textContent = `seq ${state.callbackSeq || 0}${clients}`;
  }
  const reconnectBtn = $('callbackReconnectBtn');
  if (reconnectBtn) reconnectBtn.disabled = !state.appStarted || !realtimeOrdersEnabled();
}

function setOrderCallbackSocketState(status, detail = '') {
  state.orderCallbackSocketState = status;
  state.orderCallbackSocketDetail = detail;
  updateCallbackStatusUi();
}

function formatCallbackJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (error) {
    return String(value);
  }
}

function appendServerCallbackEvent(event, options = {}) {
  if (!event || typeof event !== 'object') return false;
  const seq = Number(event.seq || 0);
  if (seq && seq <= state.callbackSeq) return false;
  if (seq) state.callbackSeq = Math.max(state.callbackSeq, seq);
  const row = normalizeCallbackEvent(event);
  state.callbackEvents.unshift(row);
  state.callbackEvents = state.callbackEvents.slice(0, 200);
  state.callbackLastEventAt = row.time;
  state.callbackLastEventName = row.label;
  const count = $('callbackCount');
  if (count) count.textContent = `${state.callbackEvents.length} 条真实回调`;
  updateCallbackStatusUi();
  if (options.render !== false && state.currentView === 'callbacks') {
    renderCallbacks();
  }
  return row;
}

function callbackEventIsTradeRelated(event) {
  const name = callbackEventName(event);
  return name.includes('order') || name.includes('trade') || name.includes('cancel');
}

function callbackEventIsOrderRow(event) {
  return callbackEventName(event).includes('on_stock_order');
}

function orderRowFromCallbackEvent(event) {
  if (!callbackEventIsOrderRow(event)) return null;
  const data = callbackEventData(event);
  if (!data || typeof data !== 'object') return null;
  const row = { ...data };
  if (!hasValue(firstField(row, ORDER_TIME_FIELDS)) && hasValue(event.received_at)) {
    row.order_time = callbackReceivedMs(event);
  }
  return orderKey(row) ? row : null;
}

function rememberOrderCallbackMeta(row) {
  if (!row || !row.order_id) return;
  if (state.orderCallbackMeta.has(row.order_id)) state.orderCallbackMeta.delete(row.order_id);
  state.orderCallbackMeta.set(row.order_id, {
    label: row.label,
    type: row.type,
    className: row.className,
    time: row.time,
    seq: row.seq,
    status: row.status,
  });
  while (state.orderCallbackMeta.size > ORDER_SNAPSHOT_LIMIT) {
    const oldest = state.orderCallbackMeta.keys().next().value;
    if (!oldest) break;
    state.orderCallbackMeta.delete(oldest);
  }
}

function orderCallbackMetaForRow(row) {
  const id = orderKey(row);
  return id ? state.orderCallbackMeta.get(id) : null;
}

function mergeOrderCallbackRow(row) {
  if (!row) return false;
  const id = orderKey(row);
  if (!id) return false;
  if (isCfquantOrder(row)) rememberCfquantOrder(row);
  const rows = (state.latestOrders || []).slice();
  const index = rows.findIndex((item) => orderKey(item) === id);
  if (index >= 0) rows[index] = { ...rows[index], ...row };
  else rows.push(row);
  markOrderHighlight(id, index >= 0 ? 'updated' : 'new');
  renderOrders({ data: rows });
  return true;
}

function runOrderCallbackRefresh() {
  state.orderCallbackRefreshTimer = null;
  if (state.orderCallbackRefreshInFlight) {
    state.orderCallbackRefreshPending = true;
    return;
  }
  const sections = Array.from(state.orderCallbackRefreshSections);
  state.orderCallbackRefreshSections.clear();
  if (!sections.length) return;
  state.orderCallbackRefreshInFlight = true;
  refreshAccount(sections.join(','), { force: true, subscribe: false })
    .catch((error) => log('回调刷新交易数据失败', { sections, error: error.message }))
    .finally(() => {
      state.orderCallbackRefreshInFlight = false;
      if (state.orderCallbackRefreshPending || state.orderCallbackRefreshSections.size) {
        state.orderCallbackRefreshPending = false;
        scheduleOrderCallbackRefresh();
      }
    });
}

function scheduleOrderCallbackRefresh(sections = 'orders') {
  String(sections || 'orders').split(',').forEach((section) => {
    const value = section.trim();
    if (value) state.orderCallbackRefreshSections.add(value);
  });
  if (state.orderCallbackRefreshTimer) return;
  state.orderCallbackRefreshTimer = window.setTimeout(runOrderCallbackRefresh, 180);
}

function handleOrderCallbackEvent(event, options = {}) {
  const row = appendServerCallbackEvent(event, { render: false });
  if (!row) return;
  const data = callbackEventData(event);
  rememberCfquantOrder(data);
  rememberOrderCallbackMeta(row);
  const merged = mergeOrderCallbackRow(orderRowFromCallbackEvent(event));
  const name = callbackEventName(event);
  if (name.includes('stock_trade')) {
    scheduleOrderCallbackRefresh('asset,positions,orders,trades');
  } else if (!merged && callbackEventIsTradeRelated(event)) {
    scheduleOrderCallbackRefresh('orders');
  }
  if (options.render !== false && state.currentView === 'callbacks') {
    renderCallbacks();
  }
}

function handleOrderCallbackPayload(payload) {
  if (!payload) return;
  if (payload.type === 'hello') {
    state.orderCallbackHello = payload;
    const clientText = hasValue(payload.clients) ? `clients ${payload.clients}` : '';
    const prefixText = payload.event_prefix || 'trader:*';
    setOrderCallbackSocketState('open', [prefixText, clientText].filter(Boolean).join(' / '));
    return;
  }
  if (payload.type === 'history' && Array.isArray(payload.events)) {
    payload.events.forEach((event) => handleOrderCallbackEvent(event, { render: false }));
    if (state.currentView === 'callbacks') renderCallbacks();
    return;
  }
  if (payload.type === 'callback' && payload.event) {
    const event = payload.cached && payload.event && typeof payload.event === 'object'
      ? { ...payload.event, cached: true }
      : payload.event;
    handleOrderCallbackEvent(event);
  }
}

function realtimeOrdersEnabled() {
  const control = $('autoRefresh');
  return !control || control.checked;
}

function closeOrderCallbackSocket() {
  if (state.orderCallbackReconnectTimer) {
    window.clearTimeout(state.orderCallbackReconnectTimer);
    state.orderCallbackReconnectTimer = null;
  }
  const socket = state.orderCallbackSocket;
  state.orderCallbackSocket = null;
  state.orderCallbackKey = '';
  if (socket) {
    try {
      socket.close();
    } catch (error) {
      // ignore stale sockets
    }
  }
  setOrderCallbackSocketState(realtimeOrdersEnabled() ? 'closed' : 'disabled', realtimeOrdersEnabled() ? '' : '实时回调开关关闭');
}

function connectOrderCallbackSocket(options = {}) {
  if (!state.appStarted || !realtimeOrdersEnabled()) {
    closeOrderCallbackSocket();
    setOrderCallbackSocketState(realtimeOrdersEnabled() ? 'idle' : 'disabled', realtimeOrdersEnabled() ? '应用尚未启动' : '实时回调开关关闭');
    return;
  }
  const accountId = selectedAccount();
  if (!accountId) {
    closeOrderCallbackSocket();
    setOrderCallbackSocketState('idle', '未选择账号');
    return;
  }
  const bridgeId = selectedBridge();
  const accountType = selectedAccountType();
  const accountKey = selectedAccountKey();
  const socketKey = `${bridgeId}|${accountType}|${accountKey || accountId}`;
  if (!options.force && state.orderCallbackSocket && state.orderCallbackKey === socketKey) return;
  closeOrderCallbackSocket();

  const params = new URLSearchParams();
  params.set('bridge_id', bridgeId);
  params.set('account_id', accountId);
  params.set('account_type', accountType);
  if (accountKey) params.set('account_key', accountKey);
  params.set('event_prefix', 'trader:');
  const socket = new WebSocket(apiWsUrl(`/ws/callbacks?${params.toString()}`));
  state.orderCallbackSocket = socket;
  state.orderCallbackKey = socketKey;
  setOrderCallbackSocketState('connecting', `${accountTypeLabel(accountType)} ${accountId}`);
  socket.onopen = () => {
    if (state.orderCallbackSocket !== socket) return;
    setOrderCallbackSocketState('open', `${accountTypeLabel(accountType)} ${accountId}`);
  };
  socket.onmessage = (event) => {
    if (state.orderCallbackSocket !== socket) return;
    try {
      handleOrderCallbackPayload(JSON.parse(event.data));
    } catch (error) {
      log('委托回调消息解析失败', { error: error.message });
    }
  };
  socket.onerror = () => {
    if (state.orderCallbackSocket === socket) {
      setOrderCallbackSocketState('error', 'WebSocket 异常');
      log('委托回调 WebSocket 异常');
    }
  };
  socket.onclose = () => {
    if (state.orderCallbackSocket !== socket) return;
    state.orderCallbackSocket = null;
    state.orderCallbackKey = '';
    setOrderCallbackSocketState('closed', '等待重连');
    if (!state.appStarted || !realtimeOrdersEnabled() || document.hidden) return;
    state.orderCallbackReconnectTimer = window.setTimeout(() => {
      state.orderCallbackReconnectTimer = null;
      connectOrderCallbackSocket({ force: true });
    }, 2000);
  };
}

function restartOrderCallbackSocket() {
  closeOrderCallbackSocket();
  connectOrderCallbackSocket({ force: true });
}

async function refreshCallbacks() {
  try {
    const params = new URLSearchParams();
    params.set('bridge_id', selectedBridge());
    params.set('account_id', selectedAccount());
    params.set('account_type', selectedAccountType());
    const accountKey = selectedAccountKey();
    if (accountKey) params.set('account_key', accountKey);
    params.set('event_prefix', 'trader:');
    params.set('since', state.callbackSeq);
    params.set('limit', 200);
    const payload = await api(`/api/callbacks?${params.toString()}`);
    const events = payload.events || [];
    if (!events.length) return;
    events.forEach((event) => handleOrderCallbackEvent(event, { render: false }));
    if (state.currentView === 'callbacks') {
      renderCallbacks();
    }
  } catch (error) {
    log('回调拉取失败', { error: error.message });
  }
}

function renderCallbacks() {
  const count = $('callbackCount');
  if (count) count.textContent = `${state.callbackEvents.length} 条真实回调`;
  updateCallbackStatusUi();
  const body = $('callbacksBody');
  if (!body) return;
  const html = state.callbackEvents.map((row) => `<tr>
    <td>${esc(row.time)}</td>
    <td>
      <span class="callback-event-pill ${esc(row.className || '')}">${esc(row.label)}</span>
      <small class="callback-raw-event">${esc(row.type)}</small>
    </td>
    <td>
      <strong>${esc(row.account_id)}</strong>
      <small>${esc(accountTypeLabel(row.account_type || selectedAccountType()))}</small>
    </td>
    <td>
      <strong>${esc(row.code)}</strong>
      <small>${esc(row.name)}</small>
    </td>
    <td>${esc(row.order_id)}</td>
    <td class="num">${money(row.price)}</td>
    <td class="num">${esc(row.volume)}</td>
    <td class="num">${esc(row.traded)}</td>
    <td class="callback-summary-cell">
      <strong>${esc(row.status)}</strong>
      <small>${esc(row.summary || `字段 ${row.payload_fields || 0}`)}</small>
    </td>
    <td>
      <span>${esc(row.source)}</span>
      ${row.cached ? '<small>缓存</small>' : ''}
    </td>
    <td>
      <details class="callback-detail">
        <summary>完整 JSON</summary>
        <pre>${esc(formatCallbackJson(row.raw))}</pre>
      </details>
    </td>
  </tr>`).join('');
  body.innerHTML = html || '<tr><td colspan="11">暂无真实回调事件。请确认 QMT 端已启用交易主推并加载 cfquant 回调桥。</td></tr>';
}

function renderOrders(section) {
  const rows = (section && Array.isArray(section.data)) ? section.data : [];
  state.latestOrders = rows.slice();
  trackOrderEvents(rows);
  const cancelableCount = rows.filter(isCancelableOrder).length;
  $('orderCount').textContent = `${rows.length} 条 / ${cancelableCount} 条可撤`;
  const sortedRows = sortedOrderRows(rows);
  const html = orderRowsHtml(sortedRows, { includeTime: true });
  $('ordersBody').innerHTML = html || '<tr><td colspan="11">无委托数据</td></tr>';
  const tradeBody = $('tradeOrdersBody');
  if (tradeBody) {
    tradeBody.innerHTML = html || '<tr><td colspan="11">无委托数据</td></tr>';
  }
  $('selectAllOrders').checked = false;
  const tradeSelectAll = $('selectAllTradeOrders');
  if (tradeSelectAll) tradeSelectAll.checked = false;
  renderOrderSortHeaders();
}

function orderCallbackCellHtml(row) {
  const meta = orderCallbackMetaForRow(row);
  if (!meta) return '<span class="order-callback-empty">未收到</span>';
  return `<span class="order-callback-tag ${esc(meta.className || '')}">${esc(meta.label)}</span><small>${esc(meta.time)}${meta.seq ? ` / seq ${esc(meta.seq)}` : ''}</small>`;
}

function orderRowsHtml(rows, options = {}) {
  const includeTime = !!options.includeTime;
  return rows.map((row, index) => {
    const code = orderCode(row);
    const orderId = orderKey(row);
    const cancelable = isCancelableOrder(row);
    const highlightType = orderHighlightType(row);
    const highlightClass = highlightType ? ` order-row-highlight order-row-${highlightType}` : '';
    return `<tr class="clickable${highlightClass}" data-order-id="${esc(orderId)}" data-code="${esc(code)}" data-cancelable="${cancelable ? '1' : '0'}">
      <td><input class="order-select" type="checkbox" data-order-id="${esc(orderId)}"${cancelable ? '' : ' disabled'}></td>
      <td class="num">${index + 1}</td>
      ${includeTime ? `<td>${esc(orderTime(row))}</td>` : ''}
      <td><span class="source-pill ${orderSourceClass(row)}">${esc(orderSource(row))}</span></td>
      <td>${esc(code)}</td>
      <td>${esc(orderName(row))}</td>
      <td class="num">${esc(orderVolume(row))}</td>
      <td class="num">${esc(tradedVolume(row))}</td>
      <td>${esc(orderStatus(row))}</td>
      <td class="order-callback-cell">${orderCallbackCellHtml(row)}</td>
      <td>${esc(orderId)}</td>
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
  const accountType = selectedAccountType();
  const accountKey = selectedAccountKey();
  const channel = selectedChannel();
  if (!accountId) {
    log('账号为空');
    return;
  }
  const params = new URLSearchParams();
  params.set('bridge_id', selectedBridge());
  params.set('account_id', accountId);
  params.set('account_type', accountType);
  if (accountKey) params.set('account_key', accountKey);
  params.set('channel', channel);
  params.set('sections', sections);
  if (options.force) params.set('force', '1');
  if (options.subscribe === false) params.set('subscribe', '0');
  const data = await api(`/api/account?${params.toString()}`);
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
  const accountType = normalizeAccountType(state.accountType || 'STOCK');
  let action = form.side.value;
  if (accountType === 'CREDIT' && form.credit_action) {
    action = creditOrderActionMeta(form.credit_action.value, form.side.value).value;
  } else if (isDerivativeAccountType(accountType) && form.order_action) {
    action = derivativeOrderActionMeta(accountType, form.order_action.value, form.side.value).value;
  }
  const code = normalizeStockCode(form.stock_code.value);
  const volume = Number(form.volume.value || 0);
  const priceType = Number((form.price_type && form.price_type.value) || FIX_PRICE);
  const price = Number(form.price.value || 0);
  if (!code || !volume || (priceType === FIX_PRICE && !price)) return '';
  return `${String(action || '').toUpperCase()} ${code} ${volume} @ ${price.toFixed(3)}`;
}

function buildCancelConfirmation(form) {
  const orderId = form.order_id.value.trim();
  return orderId ? `CANCEL ${orderId}` : '';
}

async function submitOrder(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const accountType = selectedAccountType();
  const creditAction = accountType === 'CREDIT' && form.credit_action
    ? creditOrderActionMeta(form.credit_action.value, form.side.value).value
    : '';
  const derivativeAction = isDerivativeAccountType(accountType) && form.order_action
    ? derivativeOrderActionMeta(accountType, form.order_action.value, form.side.value).value
    : '';
  const body = {
    bridge_id: selectedBridge(),
    channel: selectedTradeChannel(),
    account_id: selectedAccount(),
    account_type: accountType,
    account_key: selectedAccountKey(),
    side: form.side.value,
    stock_code: normalizeStockCode(form.stock_code.value),
    price_type: Number((form.price_type && form.price_type.value) || FIX_PRICE),
    price: Number(form.price.value),
    volume: Number(form.volume.value),
    confirm_text: form.confirm_text.value.trim(),
  };
  if (creditAction) body.credit_action = creditAction;
  if (derivativeAction) body.order_action = derivativeAction;
  try {
    const data = await api('/api/order', { method: 'POST', body: JSON.stringify(body) });
    rememberCfquantOrder(data);
    log('委托已提交', data);
    await refreshAccount('asset,positions', { force: true });
    await refreshAccount('orders', { force: true, subscribe: false });
  } catch (error) {
    log('委托失败', { error: error.message });
  }
}

function parseBatchOrders(text) {
  const lines = String(text || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return lines.map((line, index) => {
    const parts = line.split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
    if (parts.length < 3) {
      throw new Error(`第 ${index + 1} 行格式应为：代码,价格,数量`);
    }
    const row = {
      side: 'buy',
      stock_code: normalizeStockCode(parts[0]),
      price: Number(parts[1]),
      volume: Number(parts[2]),
    };
    const extra = String(parts[3] || '').trim();
    if (extra) {
      const normalized = extra.toLowerCase();
      if (normalized === 'buy' || normalized === 'sell') row.side = normalized;
      else {
        row.credit_action = normalized;
        row.order_action = normalized;
      }
    }
    return row;
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
    const accountType = selectedAccountType();
    const creditAction = accountType === 'CREDIT' && form.credit_action
      ? creditOrderActionMeta(form.credit_action.value).value
      : '';
    const derivativeAction = isDerivativeAccountType(accountType) && form.order_action
      ? derivativeOrderActionMeta(accountType, form.order_action.value).value
      : '';
    const body = {
      bridge_id: selectedBridge(),
      channel: selectedTradeChannel(),
      account_id: selectedAccount(),
      account_type: accountType,
      account_key: selectedAccountKey(),
      price_type: Number((form.price_type && form.price_type.value) || FIX_PRICE),
      orders,
      confirm_text: form.confirm_text.value.trim(),
    };
    if (creditAction) body.credit_action = creditAction;
    if (derivativeAction) body.order_action = derivativeAction;
    const data = await api('/api/orders/batch', { method: 'POST', body: JSON.stringify(body) });
    rememberCfquantOrder(data);
    log('批量委托已提交', data);
    await refreshAccount('asset,positions', { force: true });
    await refreshAccount('orders', { force: true, subscribe: false });
  } catch (error) {
    log('批量委托失败', { error: error.message });
  }
}

async function sendCancel(orderId, channel) {
  const body = {
    bridge_id: selectedBridge(),
    channel: channel || selectedTradeChannel(),
    account_id: selectedAccount(),
    account_type: selectedAccountType(),
    account_key: selectedAccountKey(),
    order_id: String(orderId || '').trim(),
    confirm_text: `CANCEL ${String(orderId || '').trim()}`,
  };
  const data = await api('/api/cancel', { method: 'POST', body: JSON.stringify(body) });
  log('撤单已提交', data);
  await refreshAccount('orders', { force: true, subscribe: false });
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
  await refreshAccount('orders', { force: true, subscribe: false });
}

function wireForms() {
  const orderForm = $('orderForm');
  const refreshOrderHint = () => {
    const expected = buildOrderConfirmation(orderForm);
    $('orderHint').textContent = expected;
    if (!orderForm.confirm_text.value || orderForm.confirm_text.value === state.lastOrderConfirm) {
      orderForm.confirm_text.value = expected;
    }
    state.lastOrderConfirm = expected;
  };
  orderForm.addEventListener('input', refreshOrderHint);
  orderForm.addEventListener('submit', submitOrder);
  if (orderForm.credit_action) {
    orderForm.credit_action.addEventListener('change', () => {
      const action = creditOrderActionMeta(orderForm.credit_action.value, orderForm.side.value);
      orderForm.side.value = action.side;
      setTradeTabSide(action.side);
      refreshOrderHint();
    });
  }
  if (orderForm.order_action) {
    orderForm.order_action.addEventListener('change', () => {
      const accountType = normalizeAccountType(state.accountType || selectedAccountType());
      const action = derivativeOrderActionMeta(accountType, orderForm.order_action.value, orderForm.side.value);
      if (action.side) {
        orderForm.side.value = action.side;
        setTradeTabSide(action.side);
      }
      refreshOrderHint();
    });
  }
  if (orderForm.price_type) {
    orderForm.price_type.addEventListener('change', refreshOrderHint);
  }
  const batchOrderForm = $('batchOrderForm');
  batchOrderForm.addEventListener('input', updateBatchOrderHint);
  batchOrderForm.addEventListener('submit', submitBatchOrders);
  if (batchOrderForm.credit_action) {
    batchOrderForm.credit_action.addEventListener('change', updateBatchOrderHint);
  }
  if (batchOrderForm.order_action) {
    batchOrderForm.order_action.addEventListener('change', updateBatchOrderHint);
  }
  if (batchOrderForm.price_type) {
    batchOrderForm.price_type.addEventListener('change', updateBatchOrderHint);
  }
  document.querySelectorAll('.trade-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const side = tab.dataset.side === 'sell' ? 'sell' : 'buy';
      orderForm.side.value = side;
      if (normalizeAccountType(state.accountType || selectedAccountType()) === 'CREDIT' && orderForm.credit_action) {
        orderForm.credit_action.value = side === 'sell' ? 'credit_sell' : 'credit_buy';
      }
      if (isDerivativeAccountType(state.accountType || selectedAccountType()) && orderForm.order_action) {
        const accountType = normalizeAccountType(state.accountType || selectedAccountType());
        orderForm.order_action.value = derivativeDefaultOrderAction(accountType, side);
      }
      setTradeTabSide(side);
      refreshOrderHint();
    });
  });
  syncCreditOrderControls();
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
  wireOrderSortHeaders();
}

function wireNavigation() {
  document.querySelectorAll('.nav-item').forEach((node) => {
    node.addEventListener('click', () => setView(node.dataset.view));
  });
  window.addEventListener('pagehide', () => {
    stopQuoteLive({ beacon: true });
    closeDownloadSocket();
    closeOrderCallbackSocket();
  });
  window.addEventListener('beforeunload', () => {
    stopQuoteLive({ beacon: true });
    closeDownloadSocket();
    closeOrderCallbackSocket();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopQuoteLive({ beacon: true });
    else connectOrderCallbackSocket();
  });
}

function wireDataTabs() {
  document.querySelectorAll('.data-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      setDataTab(tab.dataset.tab);
    });
  });
}

function setOnboardingStatus(id, message = '', level = '') {
  const node = $(id);
  if (!node) return;
  node.textContent = message;
  node.classList.remove('is-ok', 'is-error', 'is-busy', 'is-warn');
  if (level) node.classList.add(`is-${level}`);
}

function joinWinPath(base, child) {
  base = String(base || '').trim().replace(/[\\\/]+$/, '');
  child = String(child || '').trim().replace(/^[\\\/]+/, '');
  if (!base) return child || '--';
  return child ? `${base}\\${child}` : base;
}

function parentWinPath(path) {
  path = String(path || '').trim().replace(/[\\\/]+$/, '');
  const index = Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/'));
  return index > 0 ? path.slice(0, index) : '';
}

function qmtCoreDirPath(path) {
  path = String(path || '').trim().replace(/[\\\/]+$/, '');
  if (!path) return '';
  const last = path.slice(Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/')) + 1).toLowerCase();
  if (last === 'bin.x64') return path;
  if (last === 'python') {
    const parent = parentWinPath(path);
    return parent ? joinWinPath(parent, 'bin.x64') : path;
  }
  return joinWinPath(path, 'bin.x64');
}

function qmtPythonDirPath(path) {
  path = String(path || '').trim().replace(/[\\\/]+$/, '');
  if (!path) return '';
  const last = path.slice(Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/')) + 1).toLowerCase();
  if (last === 'python') return path;
  const installDir = last === 'bin.x64' ? parentWinPath(path) : path;
  return installDir ? joinWinPath(installDir, 'python') : '';
}

function accountConfigQmtTradeDir(config = {}) {
  return String(config.qmt_trade_dir
    || config.trade_qmt_dir
    || config.advanced_qmt_dir
    || config.qmt_trade_core_dir
    || '').trim();
}

function onboardingCurrentConfig() {
  const selectedInfo = selectedAccountInfo();
  const selectedConfig = selectedInfo && selectedInfo.config ? selectedInfo.config : null;
  const accountId = ($('onboardingAccountId') && $('onboardingAccountId').value.trim())
    || (selectedInfo && selectedInfo.accountId)
    || state.accountId
    || state.defaultAccountId
    || (state.setup && state.setup.default_account_id)
    || '';
  const accountType = normalizeAccountType(
    ($('onboardingAccountType') && $('onboardingAccountType').value)
    || (selectedInfo && selectedInfo.accountType)
    || state.accountType
    || state.defaultAccountType
    || (state.setup && state.setup.default_account_type)
    || 'STOCK'
  );
  const selectedKey = selectedInfo && selectedInfo.accountKey ? selectedInfo.accountKey : '';
  const exact = accountId ? accountConfigEntries().find((item) => (
    item.accountId === accountId && item.accountType === accountType
  )) : null;
  const existing = exact ? exact.config : null;
  const setupKey = state.setup && (state.setup.default_account_key || state.setup.default_account_id);
  const setupConfig = state.setup && state.setup.account_configs
    ? state.setup.account_configs[setupKey]
    : null;
  const selectedKeyConfig = selectedKey ? findAccountConfigByKey(selectedKey) : null;
  return existing || selectedKeyConfig || selectedConfig || setupConfig || {};
}

function onboardingSavedQmtTradeDir(config = onboardingCurrentConfig()) {
  const direct = accountConfigQmtTradeDir(config);
  if (direct) return direct;
  const setupDefault = String(state.setup && state.setup.default_qmt_trade_dir || '').trim();
  if (setupDefault) return setupDefault;
  const valuesAccountId = ($('onboardingAccountId') && $('onboardingAccountId').value.trim())
    || config.account_id
    || state.accountId
    || state.defaultAccountId
    || '';
  const valuesAccountType = normalizeAccountType(
    ($('onboardingAccountType') && $('onboardingAccountType').value)
    || config.account_type
    || state.accountType
    || state.defaultAccountType
    || 'STOCK'
  );
  const entries = accountConfigEntries();
  const exact = entries.find((item) => (
    item.accountId === valuesAccountId
    && item.accountType === valuesAccountType
    && accountConfigQmtTradeDir(item.config)
  ));
  if (exact) return accountConfigQmtTradeDir(exact.config);
  const selected = selectedAccountInfo();
  const selectedTradeDir = accountConfigQmtTradeDir(selected && selected.config || {});
  if (selectedTradeDir) return selectedTradeDir;
  const advanced = entries.filter((item) => (
    normalizeTransportMode(item.config && item.config.mode) === 'lttx'
    && accountConfigQmtTradeDir(item.config)
  ));
  return advanced.length === 1 ? accountConfigQmtTradeDir(advanced[0].config) : '';
}

function fillOnboardingQmtTradeDirFromSaved() {
  const input = $('onboardingQmtTradeDir');
  const modeInput = $('onboardingMode');
  if (!input || normalizeTransportMode(modeInput && modeInput.value) !== 'lttx') return false;
  if (input.value.trim()) return false;
  const saved = onboardingSavedQmtTradeDir();
  if (!saved) return false;
  input.value = saved;
  return true;
}

function onboardingValues() {
  const config = onboardingCurrentConfig();
  const accountId = $('onboardingAccountId')
    ? $('onboardingAccountId').value.trim()
    : (config.account_id || state.accountId || state.defaultAccountId || '');
  const accountType = normalizeAccountType(
    $('onboardingAccountType')
      ? $('onboardingAccountType').value
      : (config.account_type || state.accountType || state.defaultAccountType || 'STOCK')
  );
  return {
    account_id: accountId,
    account_type: accountType,
    account_key: config.account_key || makeAccountKey(accountId, accountType, config.bridge_id || state.defaultBridgeId || 'default'),
    qmt_dir: $('onboardingQmtDir') ? $('onboardingQmtDir').value.trim() : (config.qmt_dir || ''),
    qmt_trade_dir: $('onboardingQmtTradeDir') ? $('onboardingQmtTradeDir').value.trim() : accountConfigQmtTradeDir(config),
    mode: $('onboardingMode') ? $('onboardingMode').value : (config.mode || 'ctypes'),
    data_provider: $('onboardingDataProvider') ? $('onboardingDataProvider').checked : !!config.data_provider,
  };
}

function onboardingDeployPlan(values = onboardingValues()) {
  const mode = normalizeTransportMode(values.mode);
  const qmtDir = values.qmt_dir || '';
  const qmtTradeDir = values.qmt_trade_dir || '';
  const qmtCoreDir = qmtCoreDirPath(qmtDir);
  const pythonDir = qmtPythonDirPath(qmtDir);
  const tradeCoreDir = qmtCoreDirPath(qmtTradeDir);
  const tradePythonDir = qmtPythonDirPath(qmtTradeDir);
  const entryScript = qmtEntryScriptForMode(mode);
  const baseRows = [
    ['资金账号', values.account_id || '--'],
    ['QMT 目录', qmtDir || '未填写'],
    ['自动复制核心包到', qmtCoreDir ? joinWinPath(qmtCoreDir, 'cfquant') : '请先填写 QMT 目录'],
  ];
  if (mode === 'lttx') {
    return [
      ...baseRows,
      ['普通 QMT 加载', pythonDir ? joinWinPath(pythonDir, 'CFQUANT.py') : '请先填写普通 QMT 目录'],
      ['极速 QMT 目录', qmtTradeDir || '请先填写第二个 QMT 目录'],
      ['极速核心包到', tradeCoreDir ? joinWinPath(tradeCoreDir, 'cfquant') : '请先填写第二个 QMT 目录'],
      ['极速 QMT 加载', tradePythonDir ? joinWinPath(tradePythonDir, 'CFQUANT_TRADE_LOWLAT.py') : '请先填写第二个 QMT 目录'],
    ];
  }
  return [
    ...baseRows,
    ['QMT 加载', pythonDir ? joinWinPath(pythonDir, entryScript) : '请先填写 QMT 目录'],
    ['脚本数量', `一个 QMT，一个${transportModeLabel(mode)}脚本`],
  ];
}

function renderOnboardingDeployPlan() {
  const box = $('onboardingDeployPaths');
  if (!box) return;
  const values = onboardingValues();
  box.innerHTML = onboardingDeployPlan(values).map(([label, value]) => (
    `<div class="onboarding-deploy-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`
  )).join('');
  const notice = $('onboardingDeployNotice');
  if (notice) {
    const mode = normalizeTransportMode(values.mode);
    const advanced = mode === 'lttx';
    const entryScript = qmtEntryScriptForMode(mode);
    notice.classList.toggle('warning', advanced);
    notice.innerHTML = advanced
      ? '<strong>高级模式</strong><span>普通 QMT 加载 <code>CFQUANT.py</code>，极速交易端加载 <code>CFQUANT_TRADE_LOWLAT.py</code>。</span>'
      : `<strong>${esc(transportModeLabel(mode))}</strong><span>只加载 <code>${esc(entryScript)}</code>。</span>`;
  }
  renderQmtScriptPanel({
    listId: 'onboardingQmtScriptList',
    guideId: 'onboardingQmtScriptGuide',
    summaryId: 'onboardingQmtScriptSummary',
    values,
    includeSource: true,
  });
}

function currentOnboardingBindingValues() {
  const values = state.onboardingBindingValues || onboardingValues();
  const config = onboardingCurrentConfig();
  return {
    ...values,
    marketRoutingEnabled: values.marketRoutingEnabled !== undefined
      ? !!values.marketRoutingEnabled
      : isMarketRoutingEnabled(config),
    marketBridges: values.marketBridges || normalizeMarketRoutes(config),
  };
}

function onboardingBridgeReadiness(data, values = currentOnboardingBindingValues()) {
  const mode = normalizeTransportMode(values.mode);
  const marketRoutingEnabled = !!(
    values.marketRoutingEnabled
    || values.market_routing_enabled
    || (data && data.market_routing_enabled)
  );
  if (marketRoutingEnabled) {
    const marketRoutes = data && data.market_routes ? data.market_routes : {};
    const requirements = ['SH', 'SZ'].map((market) => {
      const route = marketRoutes[market] || {};
      const modeStatus = mode === 'lttx'
        ? (((route.modes || {}).lttx || {}).status || {})
        : (((route.modes || {}).ctypes || {}).status || route.status || {});
      const online = !!(modeStatus.trade && modeStatus.trade.online);
      return {
        label: `${QMT_MARKET_LABELS[market]} QMT`,
        detail: mode === 'lttx' ? '极速交易通道' : '交易通道',
        online,
      };
    });
    return { ready: requirements.every((item) => item.online), requirements };
  }

  const modeStatus = mode === 'lttx'
    ? ((((data || {}).modes || {}).lttx || {}).status || ((data || {}).status || {}))
    : ((((data || {}).modes || {}).ctypes || {}).status || ((data || {}).status || data || {}));
  const requirements = mode === 'lttx'
    ? [
      { label: '普通端 QMT', detail: '查询通道', online: !!(modeStatus.normal && modeStatus.normal.online) },
      { label: '极速交易端 QMT', detail: '交易通道', online: !!(modeStatus.trade && modeStatus.trade.online) },
    ]
    : [
      { label: `${transportModeLabel(mode)} QMT`, detail: '查询通道', online: !!(modeStatus.normal && modeStatus.normal.online) },
      { label: `${transportModeLabel(mode)} QMT`, detail: '交易通道', online: !!(modeStatus.trade && modeStatus.trade.online) },
    ];
  return { ready: requirements.every((item) => item.online), requirements };
}

function renderOnboardingRestartChecklist(values = currentOnboardingBindingValues()) {
  const box = $('onboardingRestartChecklist');
  if (!box) return;
  const plan = qmtScriptPlan(values);
  box.innerHTML = plan.scripts.map((script, index) => (
    `<div class="onboarding-restart-row">
      <span>${index + 1}</span>
      <div><strong>${esc(script.role)}</strong><small>重启 QMT，打开并运行 <code>${esc(script.name)}</code></small><code>${esc(script.target)}</code></div>
    </div>`
  )).join('');
}

function renderOnboardingBridgeSummary(data = state.bridgeStatus, error = null) {
  const box = $('onboardingBridgeSummary');
  if (!box) return;
  const values = currentOnboardingBindingValues();
  const readiness = onboardingBridgeReadiness(data, values);
  const rows = [
    ['资金账号', values.account_id || '--'],
    ['账户类型', accountTypeLabel(values.account_type)],
    ['检测次数', state.onboardingBridgeCheckAttempt ? `第 ${state.onboardingBridgeCheckAttempt} 次` : '尚未开始'],
    ...readiness.requirements.map((item) => [
      item.label,
      error ? `检测失败：${error.message}` : `${item.detail}：${item.online ? '在线' : '等待上线'}`,
    ]),
  ];
  box.innerHTML = rows.map(([label, value]) => (
    `<div class="onboarding-summary-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`
  )).join('');
}

function onboardingSectionRows(section) {
  if (!section || typeof section !== 'object') return [];
  if (Array.isArray(section.data)) return section.data;
  if (Array.isArray(section.rows)) return section.rows;
  return [];
}

function renderOnboardingDataSummary(payload = null, error = null) {
  const box = $('onboardingDataSummary');
  if (!box) return;
  const values = currentOnboardingBindingValues();
  const assetOk = !!(payload && payload.asset && payload.asset.ok);
  const positionData = onboardingSectionRows(payload && payload.positions);
  const positionsOk = !!(payload && payload.positions && payload.positions.ok);
  const positionsRows = positionData.length;
  const rows = [
    ['资金账号', values.account_id || '--'],
    ['账户类型', accountTypeLabel(values.account_type)],
    ['资产查询', error ? `失败：${error.message}` : (payload ? (assetOk ? '成功' : '未返回资产') : '尚未查询')],
    ['持仓查询', error ? `失败：${error.message}` : (payload ? (positionsOk ? '成功' : '未返回持仓') : '尚未查询')],
    ['持仓数量', payload ? `${positionsRows} 条` : '尚未查询'],
    ['下一步', assetOk || positionsRows ? '基础初始化完成，可以接入外部程序' : '先确认 QMT 已登录账号并加载通用端脚本'],
  ];
  box.innerHTML = rows.map(([label, value]) => (
    `<div class="onboarding-summary-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`
  )).join('');
}

function showOnboardingSuccess(payload = null) {
  const modal = $('onboardingSuccess');
  if (!modal) return;
  const values = currentOnboardingBindingValues();
  const modeText = transportModeLabel(values.mode);
  const positionsRows = onboardingSectionRows(payload && payload.positions).length;
  const assetOk = !!(payload && payload.asset && payload.asset.ok);
  const positionsOk = !!(payload && payload.positions && payload.positions.ok);
  const text = $('onboardingSuccessText');
  if (text) {
    text.textContent = `账号 ${values.account_id || '--'} 的 ${modeText} 已完成基础验证，资金查询${assetOk ? '成功' : '未返回'}，持仓查询${positionsOk ? `成功（${positionsRows} 条）` : '未返回'}。`;
  }
  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');
  window.setTimeout(() => {
    const button = $('onboardingSuccessHomeBtn');
    if (button) button.focus();
  }, 0);
}

function hideOnboardingSuccess() {
  const modal = $('onboardingSuccess');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.setAttribute('aria-hidden', 'true');
}

function setOnboardingStep(name) {
  if (state.onboardingBindingFlowActive && name !== 'bridge') {
    setOnboardingStatus(
      'onboardingBridgeStatus',
      'QMT 在线检测完成前不能跳过此步骤；如需退出，请使用“强制关闭本次绑定流程”。',
      'warn'
    );
    return false;
  }
  state.onboardingStep = name || 'config';
  document.querySelectorAll('[data-onboarding-step]').forEach((button) => {
    const step = button.dataset.onboardingStep;
    button.classList.toggle('active', step === state.onboardingStep);
    button.classList.toggle('done', state.onboardingDoneSteps.has(step));
  });
  document.querySelectorAll('[data-onboarding-panel]').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.onboardingPanel === state.onboardingStep);
  });
  syncOnboardingBindingFlowControls();
  return true;
}

function returnOnboardingToPreviousStep() {
  if (state.onboardingBridgeCheckInFlight) {
    setOnboardingStatus(
      'onboardingBridgeStatus',
      '在线检测进行中，暂时不能返回上一步；如需退出，请使用“强制关闭本次绑定流程”。',
      'warn'
    );
    return false;
  }
  if (state.onboardingStep === 'config') {
    return setOnboardingStep('intro');
  }
  if (state.onboardingStep === 'deploy') {
    return setOnboardingStep('config');
  }
  if (state.onboardingStep === 'data') {
    return setOnboardingStep('bridge');
  }
  if (state.onboardingStep !== 'bridge') return false;

  const target = state.onboardingBindingFlowReturnTarget || 'deploy';
  const context = state.onboardingBindingFlowContext || 'onboarding';
  const values = state.onboardingBindingValues || null;
  state.onboardingBindingFlowActive = false;
  state.onboardingBridgeCheckInFlight = false;
  state.onboardingBridgeCheckToken += 1;
  syncOnboardingBindingFlowControls();
  if (target === 'qmt-guide' && values && values.account_id) {
    hideOnboardingModal({ force: true });
    showBindingQmtGuide(values, undefined, { context });
    return true;
  }
  state.onboardingBindingFlowReturnTarget = '';
  return setOnboardingStep('deploy');
}

function markOnboardingStepDone(name) {
  if (name) state.onboardingDoneSteps.add(name);
  setOnboardingStep(state.onboardingStep);
}

function resetOnboardingRunState() {
  state.onboardingBridgeCheckToken += 1;
  state.onboardingBindingValues = null;
  state.onboardingBindingFlowContext = '';
  state.onboardingBindingFlowReturnTarget = '';
  state.onboardingBindingFlowActive = false;
  state.onboardingBridgeCheckInFlight = false;
  state.onboardingBridgeCheckAttempt = 0;
  state.onboardingStep = 'intro';
  state.onboardingDoneSteps = new Set();
  const config = onboardingCurrentConfig();
  if (config && config.account_id) {
    state.onboardingDoneSteps.add('config');
  }
  [
    'onboardingConfigStatus',
    'onboardingDeployStatus',
    'onboardingBridgeStatus',
    'onboardingDataStatus',
  ].forEach((id) => setOnboardingStatus(id, '', ''));
  hideOnboardingSuccess();
  renderOnboardingBridgeSummary(null);
  renderOnboardingDataSummary(null);
  syncOnboardingBindingFlowControls();
}

function syncOnboardingWizard(options = {}) {
  const config = onboardingCurrentConfig();
  const shouldFill = !!options.force;
  const accountInput = $('onboardingAccountId');
  if (accountInput && (shouldFill || !accountInput.value.trim())) {
    accountInput.value = config.account_id || state.accountId || state.defaultAccountId || '';
  }
  const accountTypeInput = $('onboardingAccountType');
  if (accountTypeInput) {
    accountTypeInput.value = normalizeAccountType(config.account_type || state.accountType || state.defaultAccountType || 'STOCK');
  }
  const qmtInput = $('onboardingQmtDir');
  if (qmtInput && (shouldFill || !qmtInput.value.trim())) {
    qmtInput.value = config.qmt_dir || (state.setup && state.setup.default_qmt_dir) || '';
  }
  const qmtTradeInput = $('onboardingQmtTradeDir');
  if (qmtTradeInput && (shouldFill || !qmtTradeInput.value.trim())) {
    qmtTradeInput.value = accountConfigQmtTradeDir(config) || (state.setup && state.setup.default_qmt_trade_dir) || '';
  }
  const modeInput = $('onboardingMode');
  if (modeInput) {
    modeInput.value = config.mode || (state.setup && state.setup.default_mode) || 'ctypes';
  }
  syncAdvancedQmtDirField('onboardingQmtTradeDir', modeInput && modeInput.value);
  fillOnboardingQmtTradeDirFromSaved();
  const providerInput = $('onboardingDataProvider');
  if (providerInput) {
    providerInput.checked = config.data_provider !== false;
  }
  if (config.account_id) {
    state.onboardingDoneSteps.add('config');
  }
  renderOnboardingDeployPlan();
  renderOnboardingRestartChecklist();
  renderOnboardingBridgeSummary();
  renderOnboardingDataSummary();
  setOnboardingStep(state.onboardingStep || 'config');
  syncOnboardingBindingFlowControls();
}

async function saveOnboardingConfig(event) {
  if (event) event.preventDefault();
  const values = onboardingValues();
  if (normalizeTransportMode(values.mode) === 'lttx') {
    if (!values.qmt_dir || !values.qmt_trade_dir) {
      setOnboardingStatus('onboardingConfigStatus', '高级模式必须填写普通端和极速交易端两个 QMT 核心目录。', 'error');
      return;
    }
    if (qmtDirsAreSame(values.qmt_dir, values.qmt_trade_dir)) {
      setOnboardingStatus('onboardingConfigStatus', '高级模式的两个 QMT 核心目录必须不同。', 'error');
      return;
    }
  }
  if (!values.account_id) {
    setOnboardingStatus('onboardingConfigStatus', '请先填写资金账号。', 'error');
    return;
  }
  setOnboardingStatus('onboardingConfigStatus', '正在保存账号配置...', 'busy');
  try {
    const data = state.setup && state.setup.setup_required
      ? await api('/api/setup/initialize', { method: 'POST', body: JSON.stringify(values) })
      : await saveAccountConfigRequest(values);
    state.accountPairs = data.account_pairs || {};
    state.accountConfigs = data.account_configs || state.accountConfigs;
    state.setup = data.setup || state.setup;
    state.bridges = data.bridges || state.bridges;
    state.defaultAccountId = (state.setup && state.setup.default_account_id) || state.defaultAccountId;
    state.defaultAccountType = normalizeAccountType((state.setup && state.setup.default_account_type) || state.defaultAccountType || values.account_type);
    state.defaultAccountKey = (state.setup && state.setup.default_account_key) || state.defaultAccountKey || values.account_key;
    state.accountId = values.account_id;
    state.accountType = normalizeAccountType(values.account_type);
    state.accountKey = (data.account && data.account.account_key) || values.account_key;
    renderBridgeSelect(state.bridges);
    renderAccountSelect();
    applyAccountPair(state.accountKey || values.account_id);
    syncBindingForm();
    renderAccountPairs();
    markOnboardingStepDone('config');
    syncOnboardingWizard({ force: true });
    setOnboardingStatus('onboardingConfigStatus', '账号配置已保存。', 'ok');
    const deployMessage = qmtCoreDeploySummaryText(data.qmt_core_deploy);
    if (data.qmt_bridge_identity && data.qmt_bridge_identity.error) {
      setOnboardingStatus('onboardingDeployStatus', `身份文件写入失败：${data.qmt_bridge_identity.error}`, 'error');
    } else if (qmtCoreDeployHasIssues(data.qmt_core_deploy)) {
      setOnboardingStatus('onboardingDeployStatus', deployMessage || 'cfquant 核心包自动复制失败，请检查 QMT 目录和权限。', 'warn');
    } else if (deployMessage) {
      setOnboardingStatus('onboardingDeployStatus', `${deployMessage}，可继续部署 QMT 脚本。`, 'ok');
    } else if (data.qmt_bridge_identity) {
      setOnboardingStatus('onboardingDeployStatus', '身份配置已写入，可继续部署 QMT 脚本。', 'ok');
    }
    await refreshBindingStatuses();
    setOnboardingStep('deploy');
    hideOnboardingModal();
    showBindingQmtGuide(values, data.qmt_core_deploy, { context: 'onboarding' });
    log('新手引导账号配置已保存', {
      account_id: values.account_id,
      account_type: values.account_type,
      mode: values.mode,
      qmt_dir_configured: !!values.qmt_dir,
      qmt_core_deploy: data.qmt_core_deploy ? qmtCoreDeployLogPayload(data.qmt_core_deploy) : null,
    });
  } catch (error) {
    setOnboardingStatus('onboardingConfigStatus', `保存失败：${error.message}`, 'error');
    log('新手引导账号配置保存失败', { error: error.message });
  }
}

async function copyOnboardingDeployPlan() {
  const text = onboardingDeployPlan().map(([label, value]) => `${label}: ${value}`).join('\n');
  try {
    await navigator.clipboard.writeText(text);
    setOnboardingStatus('onboardingDeployStatus', '部署清单已复制。', 'ok');
  } catch (error) {
    setOnboardingStatus('onboardingDeployStatus', '复制失败，请直接按页面清单部署。', 'error');
  }
}

function syncOnboardingBindingFlowControls() {
  const active = !!state.onboardingBindingFlowActive;
  const checking = !!state.onboardingBridgeCheckInFlight;
  const wizard = $('onboardingWizard');
  const closeButton = $('closeOnboardingBtn');
  const checkButton = $('onboardingRefreshBridgeBtn');
  const waiting = $('onboardingBridgeWaiting');
  const waitingText = $('onboardingBridgeWaitingText');
  if (wizard) {
    wizard.classList.toggle('is-binding-locked', active);
    wizard.setAttribute('aria-busy', checking ? 'true' : 'false');
  }
  if (closeButton) {
    closeButton.disabled = active;
    closeButton.title = active ? '完成在线检测或使用“强制关闭本次绑定流程”' : '';
  }
  document.querySelectorAll('[data-onboarding-step]').forEach((button) => {
    button.disabled = active;
  });
  if (checkButton) {
    checkButton.disabled = checking;
    checkButton.textContent = checking ? '正在持续检测...' : '我已重启并运行，开始检测';
  }
  if (waiting) waiting.classList.toggle('hidden', !checking);
  if (waitingText && checking) {
    waitingText.textContent = state.onboardingBridgeCheckAttempt
      ? `已检测 ${state.onboardingBridgeCheckAttempt} 次，未全部在线时每 ${ONBOARDING_BRIDGE_POLL_MS / 1000} 秒自动重试。`
      : '正在发起首次检测，请保持本页面打开。';
  }
  document.querySelectorAll('.onboarding-back-step').forEach((button) => {
    button.disabled = checking;
  });
}

function beginOnboardingRestartFlow(values = onboardingValues(), options = {}) {
  state.onboardingBridgeCheckToken += 1;
  state.onboardingBindingValues = { ...(values || {}) };
  state.onboardingBindingFlowContext = options.context || 'onboarding';
  state.onboardingBindingFlowReturnTarget = options.returnTarget || 'deploy';
  state.onboardingBindingFlowActive = true;
  state.onboardingBridgeCheckInFlight = false;
  state.onboardingBridgeCheckAttempt = 0;
  state.onboardingDoneSteps.add('config');
  state.onboardingDoneSteps.add('deploy');
  state.onboardingStep = 'bridge';
  showOnboardingModal({ force: true });
  renderOnboardingRestartChecklist(state.onboardingBindingValues);
  renderOnboardingBridgeSummary(null);
  setOnboardingStatus(
    'onboardingBridgeStatus',
    '请先重启对应 QMT，并运行刚刚保存的策略。完成后点击“我已重启并运行，开始检测”。',
    'warn'
  );
  setOnboardingStatus('onboardingDataStatus', '', '');
  syncOnboardingBindingFlowControls();
}

function forceCloseOnboardingBindingFlow() {
  const confirmed = window.confirm(
    '确认强制关闭本次绑定流程吗？账号绑定配置会保留，但 QMT 在线状态尚未验证，可以稍后重新打开新手引导继续检测。'
  );
  if (!confirmed) return;
  state.onboardingBindingFlowActive = false;
  state.onboardingBridgeCheckInFlight = false;
  state.onboardingBridgeCheckToken += 1;
  state.onboardingBindingValues = null;
  state.onboardingBindingFlowContext = '';
  state.onboardingBindingFlowReturnTarget = '';
  syncOnboardingBindingFlowControls();
  hideOnboardingModal({ force: true });
  setView('bindings');
  setBindingNotice('已强制结束本次绑定引导；账号绑定已保留，QMT 在线状态尚未验证。', 'warn', { autoHide: false });
}

async function refreshOnboardingBridge() {
  const values = currentOnboardingBindingValues();
  if (!values.account_id) {
    setOnboardingStatus('onboardingBridgeStatus', '请先填写并保存资金账号。', 'error');
    return;
  }
  if (state.onboardingBridgeCheckInFlight) return;

  state.onboardingBindingValues = { ...values };
  state.onboardingBindingFlowActive = true;
  state.onboardingBridgeCheckInFlight = true;
  state.onboardingBridgeCheckAttempt = 0;
  const token = ++state.onboardingBridgeCheckToken;
  state.accountId = values.account_id;
  state.accountType = normalizeAccountType(values.account_type);
  state.accountKey = values.account_key || state.accountKey;
  renderAccountSelect();
  applyAccountPair(state.accountKey || values.account_id);
  syncOnboardingBindingFlowControls();

  try {
    while (state.onboardingBindingFlowActive && token === state.onboardingBridgeCheckToken) {
      state.onboardingBridgeCheckAttempt += 1;
      setOnboardingStatus(
        'onboardingBridgeStatus',
        `第 ${state.onboardingBridgeCheckAttempt} 次检测中，请不要关闭本页面...`,
        'busy'
      );
      syncOnboardingBindingFlowControls();
      try {
        const params = new URLSearchParams();
        params.set('account_id', values.account_id);
        params.set('account_type', values.account_type);
        if (values.account_key) params.set('account_key', values.account_key);
        params.set('bridge_id', bridgeIdForAccount(values.account_id, values.account_type) || selectedBridge());
        const data = await api(`/api/status?${params.toString()}`);
        if (!state.onboardingBindingFlowActive || token !== state.onboardingBridgeCheckToken) return;
        state.bridgeStatus = data;
        const readiness = onboardingBridgeReadiness(data, values);
        renderOnboardingBridgeSummary(data);
        if (readiness.ready) {
          state.onboardingBindingFlowActive = false;
          state.onboardingBridgeCheckInFlight = false;
          markOnboardingStepDone('bridge');
          setOnboardingStatus('onboardingBridgeStatus', '所有必需的 QMT 通道均已在线。', 'ok');
          setOnboardingStatus(
            'onboardingDataStatus',
            'QMT 已在线。建议打开“查资金”接口并点击“发送请求”，确认当前账号能够返回数据。',
            'ok'
          );
          syncOnboardingBindingFlowControls();
          setOnboardingStep('data');
          renderOnboardingDataSummary(null);
          refreshStatus().catch((error) => log('新手引导在线后状态刷新失败', { error: error.message }));
          refreshBindingStatuses().catch((error) => log('新手引导在线后绑定状态刷新失败', { error: error.message }));
          log('新手引导 QMT 通道检测通过', {
            account_id: values.account_id,
            mode: values.mode,
            attempts: state.onboardingBridgeCheckAttempt,
          });
          return;
        }
        setOnboardingStatus(
          'onboardingBridgeStatus',
          `第 ${state.onboardingBridgeCheckAttempt} 次检测：仍有 QMT 通道未在线，${ONBOARDING_BRIDGE_POLL_MS / 1000} 秒后自动重试。`,
          'warn'
        );
      } catch (error) {
        if (!state.onboardingBindingFlowActive || token !== state.onboardingBridgeCheckToken) return;
        renderOnboardingBridgeSummary(null, error);
        setOnboardingStatus(
          'onboardingBridgeStatus',
          `第 ${state.onboardingBridgeCheckAttempt} 次检测失败：${error.message}。系统将自动重试。`,
          'warn'
        );
      }
      syncOnboardingBindingFlowControls();
      await new Promise((resolve) => window.setTimeout(resolve, ONBOARDING_BRIDGE_POLL_MS));
    }
  } finally {
    if (token === state.onboardingBridgeCheckToken) {
      state.onboardingBridgeCheckInFlight = false;
      syncOnboardingBindingFlowControls();
    }
  }
}

function openOnboardingApiTest() {
  const values = currentOnboardingBindingValues();
  state.accountId = values.account_id || state.accountId;
  state.accountType = normalizeAccountType(values.account_type || state.accountType);
  state.accountKey = values.account_key || state.accountKey;
  state.onboardingBindingValues = null;
  state.onboardingBindingFlowContext = '';
  state.onboardingBindingFlowReturnTarget = '';
  hideOnboardingModal({ force: true });
  setView('api');
  renderApiDocs('asset', { ensureGroupOpen: true });
  window.setTimeout(() => {
    const submit = $('apiForm') && $('apiForm').querySelector('button[type="submit"]');
    if (submit) submit.focus();
  }, 0);
}

async function verifyOnboardingData() {
  const values = currentOnboardingBindingValues();
  if (!values.account_id) {
    setOnboardingStatus('onboardingDataStatus', '请先填写并保存资金账号。', 'error');
    setOnboardingStep('config');
    return;
  }
  state.accountId = values.account_id;
  state.accountType = normalizeAccountType(values.account_type);
  state.accountKey = values.account_key || state.accountKey;
  renderAccountSelect();
  applyAccountPair(state.accountKey || values.account_id);
  setOnboardingStatus('onboardingDataStatus', '正在查询资金和持仓...', 'busy');
  try {
    const channel = selectedChannel();
    const bridgeId = bridgeIdForAccount(values.account_id, values.account_type) || selectedBridge();
    const params = new URLSearchParams();
    params.set('bridge_id', bridgeId);
    params.set('account_id', values.account_id);
    params.set('account_type', values.account_type);
    if (values.account_key) params.set('account_key', values.account_key);
    params.set('channel', channel);
    params.set('sections', 'asset,positions');
    params.set('force', '1');
    const data = await api(`/api/account?${params.toString()}`);
    renderOnboardingDataSummary(data);
    if (data.asset && data.asset.ok) renderAsset(data.asset);
    if (data.positions && data.positions.ok) renderPositions(data.positions);
    const verified = !!((data.asset && data.asset.ok) || (data.positions && data.positions.ok));
    if (verified) {
      markOnboardingStepDone('data');
      setOnboardingStatus('onboardingDataStatus', '验证完成，基础初始化已跑通。', 'ok');
      showOnboardingSuccess(data);
      log('新手引导数据验证完成', { account_id: values.account_id });
    } else {
      setOnboardingStatus('onboardingDataStatus', '验证未通过：资金和持仓都未成功返回。', 'error');
      log('新手引导数据验证未通过', { account_id: values.account_id });
    }
  } catch (error) {
    renderOnboardingDataSummary(null, error);
    setOnboardingStatus('onboardingDataStatus', `验证失败：${error.message}`, 'error');
    log('新手引导数据验证失败', { account_id: values.account_id, error: error.message });
  }
}

function wireOnboardingGuide() {
  document.querySelectorAll('[data-onboarding-step]').forEach((button) => {
    button.addEventListener('click', () => setOnboardingStep(button.dataset.onboardingStep));
  });
  const form = $('onboardingConfigForm');
  if (form) form.addEventListener('submit', saveOnboardingConfig);
  const startConfigBtn = $('onboardingStartConfigBtn');
  if (startConfigBtn) startConfigBtn.addEventListener('click', () => {
    markOnboardingStepDone('intro');
    setOnboardingStep('config');
  });
  const backConfigBtn = $('onboardingBackConfigBtn');
  if (backConfigBtn) backConfigBtn.addEventListener('click', returnOnboardingToPreviousStep);
  const backDeployBtn = $('onboardingBackDeployBtn');
  if (backDeployBtn) backDeployBtn.addEventListener('click', returnOnboardingToPreviousStep);
  const backBridgeBtn = $('onboardingBackBridgeBtn');
  if (backBridgeBtn) backBridgeBtn.addEventListener('click', returnOnboardingToPreviousStep);
  const backDataBtn = $('onboardingBackDataBtn');
  if (backDataBtn) backDataBtn.addEventListener('click', returnOnboardingToPreviousStep);
  ['onboardingAccountId', 'onboardingAccountType', 'onboardingQmtDir', 'onboardingQmtTradeDir', 'onboardingMode', 'onboardingDataProvider'].forEach((id) => {
    const input = $(id);
    if (input) input.addEventListener('input', renderOnboardingDeployPlan);
    if (input) input.addEventListener('change', renderOnboardingDeployPlan);
  });
  const onboardingMode = $('onboardingMode');
  if (onboardingMode) {
    onboardingMode.addEventListener('change', () => {
      syncAdvancedQmtDirField('onboardingQmtTradeDir', onboardingMode.value);
      fillOnboardingQmtTradeDirFromSaved();
      renderOnboardingDeployPlan();
    });
  }
  const useCurrent = $('onboardingUseCurrentBtn');
  if (useCurrent) useCurrent.addEventListener('click', () => {
    syncOnboardingWizard({ force: true });
    setOnboardingStatus('onboardingConfigStatus', '已读取当前账号配置。', 'ok');
  });
  const copyBtn = $('onboardingCopyDeployBtn');
  if (copyBtn) copyBtn.addEventListener('click', () => copyOnboardingDeployPlan());
  const copyQmtScriptBtn = $('onboardingCopyQmtScriptBtn');
  if (copyQmtScriptBtn) copyQmtScriptBtn.addEventListener('click', () => copyQmtScriptPlan(onboardingValues(), 'onboardingDeployStatus'));
  const goBridgeBtn = $('onboardingGoBridgeBtn');
  if (goBridgeBtn) goBridgeBtn.addEventListener('click', () => {
    beginOnboardingRestartFlow(onboardingValues(), { context: 'onboarding', returnTarget: 'deploy' });
  });
  const refreshBridgeBtn = $('onboardingRefreshBridgeBtn');
  if (refreshBridgeBtn) refreshBridgeBtn.addEventListener('click', refreshOnboardingBridge);
  const forceCloseBtn = $('onboardingForceCloseBtn');
  if (forceCloseBtn) forceCloseBtn.addEventListener('click', forceCloseOnboardingBindingFlow);
  const verifyDataBtn = $('onboardingVerifyDataBtn');
  if (verifyDataBtn) verifyDataBtn.addEventListener('click', verifyOnboardingData);
  const openHomeBtn = $('onboardingOpenHomeBtn');
  if (openHomeBtn) openHomeBtn.addEventListener('click', () => {
    hideOnboardingModal();
    setView('overview');
  });
  const openApiBtn = $('onboardingOpenApiBtn');
  if (openApiBtn) openApiBtn.addEventListener('click', openOnboardingApiTest);
  const successHomeBtn = $('onboardingSuccessHomeBtn');
  if (successHomeBtn) successHomeBtn.addEventListener('click', () => {
    hideOnboardingSuccess();
    hideOnboardingModal();
    setView('overview');
  });
  const successApiBtn = $('onboardingSuccessApiBtn');
  if (successApiBtn) successApiBtn.addEventListener('click', () => {
    hideOnboardingSuccess();
    hideOnboardingModal();
    setView('api');
  });
  const successBindingsBtn = $('onboardingSuccessBindingsBtn');
  if (successBindingsBtn) successBindingsBtn.addEventListener('click', () => {
    hideOnboardingSuccess();
    hideOnboardingModal();
    setView('bindings');
  });
  const inlineBtn = $('openOnboardingInlineBtn');
  if (inlineBtn) inlineBtn.addEventListener('click', () => openOnboardingGuide({ manual: true }));
  const closeBtn = $('closeOnboardingBtn');
  if (closeBtn) closeBtn.addEventListener('click', hideOnboardingModal);
  const backdrop = $('onboardingBackdrop');
  if (backdrop) backdrop.addEventListener('click', hideOnboardingModal);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && $('onboardingSuccess') && !$('onboardingSuccess').classList.contains('hidden')) {
      hideOnboardingSuccess();
      return;
    }
    if (event.key === 'Escape' && $('onboardingWizard') && !$('onboardingWizard').classList.contains('hidden')) {
      hideOnboardingModal();
    }
  });
  syncOnboardingWizard();
}

function setTutorialTopic(name) {
  const tutorialAliases = {
    deploy_guide: 'deploy',
    deploy_guide_lite: 'deploy',
    deploy_guide_advanced: 'deploy',
  };
  const deployTabAliases = {
    deploy_guide: 'ctypes',
    deploy_guide_lite: 'lite',
    deploy_guide_advanced: 'advanced',
  };
  const deployTab = deployTabAliases[name] || '';
  name = tutorialAliases[name] || name;
  if (!document.querySelector(`.tutorial-menu-item[data-guide="${name}"]`)) {
    name = 'deploy';
  }
  localStorage.setItem(TUTORIAL_TOPIC_KEY, name);
  document.querySelectorAll('.tutorial-menu-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.guide === name);
  });
  document.querySelectorAll('.tutorial-topic').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.guidePanel === name);
  });
  if (name === 'deploy') {
    setDeployModeTab(deployTab || localStorage.getItem(DEPLOY_MODE_TAB_KEY) || 'ctypes');
  }
  if (name === 'onboarding') syncOnboardingWizard();
  if (state.currentView === 'tutorial') renderActiveTutorialMermaid();
}

function setDeployModeTab(mode) {
  const aliases = {
    common: 'ctypes',
    universal: 'ctypes',
    ctypes: 'ctypes',
    lite: 'lite',
    extreme: 'lite',
    advanced: 'advanced',
    lttx: 'advanced',
  };
  mode = aliases[mode] || 'ctypes';
  if (!document.querySelector(`[data-deploy-mode="${mode}"]`)) {
    mode = 'ctypes';
  }
  localStorage.setItem(DEPLOY_MODE_TAB_KEY, mode);
  document.querySelectorAll('[data-deploy-mode]').forEach((button) => {
    const active = button.dataset.deployMode === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
    button.setAttribute('tabindex', active ? '0' : '-1');
  });
  document.querySelectorAll('[data-deploy-mode-panel]').forEach((panel) => {
    const active = panel.dataset.deployModePanel === mode;
    panel.classList.toggle('active', active);
    if (active) {
      panel.removeAttribute('hidden');
    } else {
      panel.setAttribute('hidden', '');
    }
  });
}

function initializeMermaidRenderer() {
  if (!window.mermaid) return false;
  if (mermaidRendererReady) return true;
  window.mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'loose',
    theme: 'base',
    themeVariables: {
      fontFamily: '"Segoe UI", "Microsoft YaHei", Arial, sans-serif',
      primaryColor: '#eef5ff',
      primaryTextColor: '#17202a',
      primaryBorderColor: '#b9d3fb',
      lineColor: '#7d8b9a',
      secondaryColor: '#f1f8f4',
      tertiaryColor: '#fff8ec',
      noteBkgColor: '#fff8ec',
      noteBorderColor: '#efc48e',
      actorBkg: '#eef5ff',
      actorBorder: '#b9d3fb',
      actorTextColor: '#17202a',
      labelBoxBkgColor: '#fbfcfd',
      labelBoxBorderColor: '#dce3ea',
      labelTextColor: '#17202a',
    },
    flowchart: {
      useMaxWidth: true,
      htmlLabels: true,
      curve: 'basis',
    },
    sequence: {
      useMaxWidth: true,
      mirrorActors: false,
      showSequenceNumbers: false,
    },
  });
  mermaidRendererReady = true;
  return true;
}

function markMermaidFallback(node, error) {
  const card = node && node.closest ? node.closest('.guide-mermaid-card') : null;
  if (!card) return;
  card.classList.add('mermaid-fallback');
  if (!card.querySelector('.mermaid-fallback-note')) {
    const note = document.createElement('div');
    note.className = 'mermaid-fallback-note';
    note.textContent = error ? `Mermaid 架构图渲染失败：${error}` : 'Mermaid 渲染脚本未加载，暂时显示图表源码。';
    card.insertBefore(note, card.firstChild);
  }
}

function renderMermaidDiagrams(scope) {
  const root = scope || document;
  const nodes = Array.from(root.querySelectorAll('.mermaid')).filter((node) => !node.dataset.processed);
  if (!nodes.length) return;
  if (!initializeMermaidRenderer()) {
    nodes.forEach((node) => markMermaidFallback(node));
    return;
  }
  window.setTimeout(() => {
    window.mermaid.run({ nodes }).catch((error) => {
      nodes.forEach((node) => markMermaidFallback(node, error.message || String(error)));
      log('Mermaid 架构图渲染失败', { error: error.message || String(error) });
    });
  }, 0);
}

function renderActiveTutorialMermaid() {
  const panel = document.querySelector('.tutorial-topic.active');
  if (!panel || !panel.querySelector('.mermaid')) return;
  window.requestAnimationFrame(() => renderMermaidDiagrams(panel));
}

function ensureOnboardingModalRoot() {
  const backdrop = $('onboardingBackdrop');
  const wizard = $('onboardingWizard');
  if (backdrop && backdrop.parentElement !== document.body) {
    document.body.appendChild(backdrop);
  }
  if (wizard && wizard.parentElement !== document.body) {
    document.body.appendChild(wizard);
  }
}

function syncOnboardingFlowHeading() {
  const binding = state.onboardingBindingFlowContext === 'binding';
  const title = $('onboardingWizardTitle');
  const subtitle = $('onboardingWizardSubtitle');
  const closeButton = $('closeOnboardingBtn');
  const progress = document.querySelector('.onboarding-progress');
  if (title) title.textContent = binding ? 'QMT 绑定检测' : '新手初始化向导';
  if (subtitle) subtitle.textContent = binding ? '确认对应 QMT 已启动并运行策略。' : '只保留启动必需项。';
  if (closeButton) {
    closeButton.setAttribute('aria-label', binding ? '关闭 QMT 绑定检测' : '关闭新手初始化向导');
  }
  if (progress) {
    progress.setAttribute('aria-label', binding ? 'QMT 绑定检测步骤' : '新手初始化步骤');
  }
}

function showOnboardingModal(options = {}) {
  ensureOnboardingModalRoot();
  syncOnboardingFlowHeading();
  syncOnboardingWizard({ force: !!options.force });
  const wizard = $('onboardingWizard');
  const backdrop = $('onboardingBackdrop');
  if (!wizard || !backdrop) return;
  backdrop.classList.remove('hidden');
  wizard.classList.remove('hidden');
  wizard.setAttribute('aria-hidden', 'false');
  wizard.scrollTop = 0;
  document.body.classList.add('onboarding-modal-open');
  syncOnboardingBindingFlowControls();
  const firstInput = $('onboardingAccountId');
  window.setTimeout(() => {
    if (state.onboardingBindingFlowActive && $('onboardingRefreshBridgeBtn')) {
      $('onboardingRefreshBridgeBtn').focus();
    } else if (firstInput && state.onboardingStep === 'config') firstInput.focus();
    else {
      const activeButton = wizard.querySelector('[data-onboarding-step].active');
      if (activeButton) activeButton.focus();
    }
  }, 0);
  if (options.auto) {
    log('已自动打开新手引导', { reason: options.reason || 'first_start' });
  }
}

function hideOnboardingModal(options = {}) {
  if (state.onboardingBindingFlowActive && !options.force) {
    setOnboardingStatus(
      'onboardingBridgeStatus',
      '当前正在等待 QMT 上线，不能直接关闭。可以继续等待，或使用“强制关闭本次绑定流程”。',
      'warn'
    );
    return false;
  }
  hideOnboardingSuccess();
  const wizard = $('onboardingWizard');
  const backdrop = $('onboardingBackdrop');
  if (wizard) {
    wizard.classList.add('hidden');
    wizard.setAttribute('aria-hidden', 'true');
  }
  if (backdrop) backdrop.classList.add('hidden');
  document.body.classList.remove('onboarding-modal-open');
  return true;
}

function openOnboardingGuide(options = {}) {
  if (options.reset !== false) {
    resetOnboardingRunState();
  }
  state.onboardingStep = options.step || 'intro';
  setTutorialTopic('onboarding');
  localStorage.setItem(onboardingAutoShownKey(), '1');
  showOnboardingModal(options);
}

function maybeAutoOpenOnboardingGuide() {
  if (state.setup && state.setup.setup_required) {
    return false;
  }
  if (localStorage.getItem(onboardingAutoShownKey()) === '1') {
    return false;
  }
  window.setTimeout(() => openOnboardingGuide({ auto: true, reason: 'first_start', step: 'intro' }), 0);
  return true;
}

function setSettingsTab(name, shouldPersist = true) {
  if (!document.querySelector(`.settings-menu-item[data-settings-tab="${name}"]`)) {
    name = 'api-key';
  }
  state.settingsTab = name;
  if (shouldPersist) {
    localStorage.setItem(SETTINGS_TAB_KEY, name);
  }
  document.body.dataset.settingsTab = name;
  document.querySelectorAll('.settings-menu-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.settingsTab === name);
    item.setAttribute('aria-pressed', item.dataset.settingsTab === name ? 'true' : 'false');
  });
  document.querySelectorAll('.settings-section').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.settingsTab === name);
  });
}

function wireTutorialNavigation() {
  document.querySelectorAll('.tutorial-menu-item').forEach((item) => {
    item.addEventListener('click', () => {
      if (item.dataset.guide === 'onboarding') {
        openOnboardingGuide({ manual: true });
      } else {
        setTutorialTopic(item.dataset.guide);
      }
    });
  });
  setTutorialTopic(localStorage.getItem(TUTORIAL_TOPIC_KEY) || 'deploy');
}

function wireDeployModeNavigation() {
  document.querySelectorAll('[data-deploy-mode]').forEach((button) => {
    button.addEventListener('click', () => {
      setDeployModeTab(button.dataset.deployMode);
    });
  });
  setDeployModeTab(localStorage.getItem(DEPLOY_MODE_TAB_KEY) || 'ctypes');
}

function wireViewShortcuts() {
  document.querySelectorAll('[data-view-jump]').forEach((node) => {
    node.addEventListener('click', () => {
      const view = node.dataset.viewJump || 'overview';
      setView(view);
      if (view === 'tutorial' && node.dataset.guide) {
        setTutorialTopic(node.dataset.guide);
      }
    });
  });
}

function wireSettingsNavigation() {
  document.querySelectorAll('.settings-menu-item').forEach((item) => {
    item.addEventListener('click', () => setSettingsTab(item.dataset.settingsTab));
  });
  setSettingsTab(localStorage.getItem(SETTINGS_TAB_KEY) || 'api-key');
}

function wireUserProfile() {
  const profileBtn = $('topbarProfileBtn');
  if (profileBtn) {
    profileBtn.addEventListener('click', () => {
      setView('settings');
      setSettingsTab('profile');
    });
  }
  const form = $('userProfileForm');
  if (form) form.addEventListener('submit', saveUserProfileFromUi);
  const uploadBtn = $('uploadUserAvatarBtn');
  if (uploadBtn) uploadBtn.addEventListener('click', uploadUserAvatarFromUi);
  const grid = $('builtinAvatarGrid');
  if (grid) {
    grid.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-avatar-url]');
      if (!button) return;
      selectUserProfileAvatar(button.dataset.avatarUrl);
    });
  }
  renderUserProfile();
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

function visiblePage() {
  return !document.hidden;
}

function shouldPollRouteStatus() {
  return visiblePage();
}

function shouldPollCallbacks() {
  return visiblePage() && state.currentView === 'callbacks';
}

function shouldPollBindingStatuses() {
  return visiblePage() && state.currentView === 'bindings';
}

function startTimers() {
  if (state.statusTimer) return;
  setInterval(() => {
    $('clock').textContent = nowText();
  }, 1000);
  state.statusTimer = setInterval(() => {
    if (shouldPollRouteStatus() && !state.statusRefreshInFlight) {
      state.statusRefreshInFlight = true;
      refreshStatus()
        .catch((error) => log('状态定时刷新失败', { error: error.message }))
        .finally(() => {
          state.statusRefreshInFlight = false;
        });
    }
    if (shouldPollBindingStatuses() && !state.bindingStatusRefreshInFlight) {
      state.bindingStatusRefreshInFlight = true;
      refreshBindingStatuses()
        .catch((error) => log('绑定状态定时刷新失败', { error: error.message }))
        .finally(() => {
          state.bindingStatusRefreshInFlight = false;
        });
    }
  }, STATUS_REFRESH_INTERVAL_MS);
  setInterval(() => {
    if (!shouldPollCallbacks() || state.callbackRefreshInFlight) return;
    state.callbackRefreshInFlight = true;
    refreshCallbacks().finally(() => {
      state.callbackRefreshInFlight = false;
    });
  }, CALLBACK_POLL_INTERVAL_MS);
}

async function boot() {
  wireForms();
  renderProjectUpdateStatus(null);
  renderUpdateStatus(null);
  wireNavigation();
  wireDataTabs();
  wireTutorialNavigation();
  wireDeployModeNavigation();
  wireViewShortcuts();
  wireOnboardingGuide();
  wireSettingsNavigation();
  wireUserProfile();
  wireImageLightbox();
  wireVersionBadge();
  wireUpdateRestartNotice();
  renderCallbacks();
  renderProjectVersion(null);
  setDataTab(localStorage.getItem('cfquant.trade_tab') || 'positions', false);
  setView(localStorage.getItem('cfquant.view') || 'overview');
  if (hydrateAccountConfigFromCache()) {
    renderBridgeSelect(state.bridges);
    renderAccountSelect(state.defaultAccountId);
    applyAccountPair(state.accountKey || state.accountId);
    syncBindingForm();
    renderAccountPairs();
    renderBridgeConfigList();
    renderCachedBindingStatuses();
  }
  $('refreshBtn').addEventListener('click', async () => {
    try {
      await refreshAccount('asset,positions', { force: true });
      await refreshAccount('orders', { force: true, subscribe: false });
      await refreshAccount('trades', { force: true });
    } catch (error) {
      log('刷新失败', { error: error.message });
    }
  });
  $('switchAccountBtn').addEventListener('click', switchAccountFromToolbar);
  $('statusBtn').addEventListener('click', refreshStatus);
  $('lttxStartBtn').addEventListener('click', startLttx);
  $('lttxStopBtn').addEventListener('click', stopLttx);
  $('openAccessSettingsBtn').addEventListener('click', () => setView('settings'));
  const openOnboardingGlobalBtn = $('openOnboardingGlobalBtn');
  if (openOnboardingGlobalBtn) {
    openOnboardingGlobalBtn.addEventListener('click', () => openOnboardingGuide({ manual: true }));
  }
  $('savePairBtn').addEventListener('click', () => saveCurrentAccountPair().catch((error) => log('账号配置保存失败', { error: error.message })));
  $('removePairBtn').addEventListener('click', () => removeCurrentAccountPair().catch((error) => log('账号配置删除失败', { error: error.message })));
  $('accountPairList').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-account-id]');
    if (!button) return;
    selectAccountPair(button.dataset.accountId, button.dataset.bridgeId, button.dataset.accountType, button.dataset.accountKey);
  });
  const bindingConfigList = $('bindingAccountConfigList');
  if (bindingConfigList) {
    bindingConfigList.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-account-id]');
      if (!button) return;
      if (button.dataset.action === 'delete-account') {
        state.accountId = button.dataset.accountId || state.accountId;
        state.accountType = normalizeAccountType(button.dataset.accountType || state.accountType);
        state.accountKey = button.dataset.accountKey || state.accountKey;
        renderAccountSelect();
        removeCurrentAccountPair().catch((error) => log('账号配置删除失败', { error: error.message }));
        return;
      }
      selectAccountPair(button.dataset.accountId, button.dataset.bridgeId, button.dataset.accountType, button.dataset.accountKey);
    });
  }
  const bridgeForm = $('bridgeForm');
  if (bridgeForm) bridgeForm.addEventListener('submit', submitBridgeForm);
  $('bindingForm').addEventListener('submit', submitBindingForm);
  const bindingMode = $('bindingMode');
  if (bindingMode) {
    bindingMode.addEventListener('change', () => {
      syncAdvancedQmtDirField('bindingQmtTradeDir', bindingMode.value);
    });
  }
  wireQmtScriptCopyList('bindingQmtScriptList', 'bindingQmtScriptSummary');
  wireQmtScriptCopyList('onboardingQmtScriptList', 'onboardingDeployStatus');
  const refreshBindingQmtScriptBtn = $('refreshBindingQmtScriptBtn');
  if (refreshBindingQmtScriptBtn) refreshBindingQmtScriptBtn.addEventListener('click', () => renderBindingQmtScriptPanel());
  const copyBindingQmtScriptBtn = $('copyBindingQmtScriptBtn');
  if (copyBindingQmtScriptBtn) copyBindingQmtScriptBtn.addEventListener('click', () => copyQmtScriptPlan(bindingScriptValuesFromSelectedAccount(), 'bindingQmtScriptSummary'));
  const openOnboardingGuideBtn = $('openOnboardingGuideBtn');
  if (openOnboardingGuideBtn) {
    openOnboardingGuideBtn.addEventListener('click', () => openOnboardingGuide({ manual: true }));
  }
  const openBindingDialogBtn = $('openBindingDialogBtn');
  if (openBindingDialogBtn) openBindingDialogBtn.addEventListener('click', () => openBindingDialog());
  const closeBindingDialogBtn = $('closeBindingDialogBtn');
  if (closeBindingDialogBtn) closeBindingDialogBtn.addEventListener('click', closeBindingDialog);
  const cancelBindingDialogBtn = $('cancelBindingDialogBtn');
  if (cancelBindingDialogBtn) cancelBindingDialogBtn.addEventListener('click', closeBindingDialog);
  const bindingDialogOverlay = $('bindingDialogOverlay');
  if (bindingDialogOverlay) {
    bindingDialogOverlay.addEventListener('click', (event) => {
      if (event.target === bindingDialogOverlay) closeBindingDialog();
    });
  }
  const bindingQmtGuideOverlay = $('bindingQmtGuideOverlay');
  if (bindingQmtGuideOverlay) {
    bindingQmtGuideOverlay.addEventListener('click', (event) => {
      if (event.target === bindingQmtGuideOverlay) closeBindingQmtGuide();
    });
  }
  const closeBindingQmtGuideBtn = $('closeBindingQmtGuideBtn');
  if (closeBindingQmtGuideBtn) closeBindingQmtGuideBtn.addEventListener('click', closeBindingQmtGuide);
  const backBindingQmtGuideBtn = $('backBindingQmtGuideBtn');
  if (backBindingQmtGuideBtn) backBindingQmtGuideBtn.addEventListener('click', returnFromBindingQmtGuide);
  const closeBindingQmtGuideBottomBtn = $('closeBindingQmtGuideBottomBtn');
  if (closeBindingQmtGuideBottomBtn) closeBindingQmtGuideBottomBtn.addEventListener('click', closeBindingQmtGuide);
  const copyBindingQmtGuideBtn = $('copyBindingQmtGuideBtn');
  if (copyBindingQmtGuideBtn) copyBindingQmtGuideBtn.addEventListener('click', () => copyQmtScriptPlan(state.bindingQmtGuideValues || {}, 'bindingQmtGuideSummary'));
  wireQmtScriptCopyList('bindingQmtGuideScriptList', 'bindingQmtGuideSummary');
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && bindingDialogOverlay && !bindingDialogOverlay.classList.contains('hidden')) {
      closeBindingDialog();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && bindingQmtGuideOverlay && !bindingQmtGuideOverlay.classList.contains('hidden')) {
      closeBindingQmtGuide();
    }
  });
  const bridgeConfigList = $('bridgeConfigList');
  if (bridgeConfigList) {
    bridgeConfigList.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-bridge-id]');
      if (!button) return;
      if (button.dataset.action === 'edit') fillBridgeForm(button.dataset.bridgeId);
      if (button.dataset.action === 'delete') deleteBridge(button.dataset.bridgeId);
    });
  }
  const refreshBindingsBtn = $('refreshBindingsBtn');
  if (refreshBindingsBtn) {
    refreshBindingsBtn.addEventListener('click', () => refreshBindingStatuses().catch((error) => log('绑定状态刷新失败', { error: error.message })));
  }
  $('bindingStatusBody').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-binding-action]');
    if (!button) return;
    const action = button.dataset.bindingAction;
    if (action === 'add') {
      openBindingDialog();
      return;
    }
    if (action === 'edit') {
      openBindingDialog({
        accountId: button.dataset.accountId,
        accountType: button.dataset.accountType,
        accountKey: button.dataset.accountKey,
        bridgeId: button.dataset.bridgeId,
        displayName: button.dataset.displayName,
      });
      return;
    }
    if (action === 'delete') {
      state.accountId = button.dataset.accountId || state.accountId;
      state.accountType = normalizeAccountType(button.dataset.accountType || state.accountType);
      state.accountKey = button.dataset.accountKey || state.accountKey;
      renderAccountSelect();
      removeCurrentAccountPair().catch((error) => log('账号配置删除失败', { error: error.message }));
      return;
    }
    if (action === 'verify') {
      verifyPair(button.dataset.accountId, button.dataset.bridgeId, button.dataset.accountType, button.dataset.accountKey);
    }
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
    if (button.dataset.endpointId !== state.apiEndpointId && !isQuoteEndpoint(apiEndpointById(button.dataset.endpointId))) {
      stopQuoteLive();
    }
    renderApiDocs(button.dataset.endpointId, { ensureGroupOpen: true });
  });
  $('quoteConnectBtn').addEventListener('click', () => connectQuoteWebSocket(state.quoteSubscribeId));
  $('quoteStopBtn').addEventListener('click', () => stopQuoteLive());
  const downloadClearBtn = $('downloadProgressClearBtn');
  if (downloadClearBtn) downloadClearBtn.addEventListener('click', clearDownloadProgress);
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
  $('reloadWebServerBtn').addEventListener('click', () => {
    saveServerAccessFromUi('api', { reload: true }).catch((error) => log('Web 重载失败', { error: error.message }));
  });
  $('webAuthForm').addEventListener('submit', loginWebAuth);
  const logoutBtn = $('webAuthLogoutBtn');
  if (logoutBtn) logoutBtn.addEventListener('click', () => logoutWebAuth());
  $('setupForm').addEventListener('submit', submitSetupForm);
  const setupMode = $('setupMode');
  if (setupMode) {
    setupMode.addEventListener('change', () => syncAdvancedQmtDirField('setupQmtTradeDir', setupMode.value));
  }
  $('reinitializeSetupBtn').addEventListener('click', reinitializeSetup);
  $('logCleanupForm').addEventListener('submit', (event) => {
    event.preventDefault();
    saveLogCleanupFromUi().catch((error) => log('日志清理设置保存失败', { error: error.message }));
  });
  const qmtLogLanguageForm = $('qmtLogLanguageForm');
  if (qmtLogLanguageForm) {
    qmtLogLanguageForm.addEventListener('submit', (event) => {
      event.preventDefault();
      saveQmtLogLanguageFromUi().catch((error) => log('QMT 日志设置保存失败', { error: error.message }));
    });
  }
  $('runLogCleanupBtn').addEventListener('click', () => {
    runLogCleanupFromUi().catch((error) => log('日志清理执行失败', { error: error.message }));
  });
  $('refreshProjectUpdateStatusBtn').addEventListener('click', () => {
    refreshProjectUpdateStatus({ remote: true }).catch((error) => log('Web 项目更新状态刷新失败', { error: error.message }));
  });
  $('runProjectGithubUpdateBtn').addEventListener('click', () => {
    runProjectGithubUpdateFromUi({ source: 'settings' }).catch((error) => {
      renderProjectUpdateResult({ error: error.message });
      log('Web 项目官网优先更新失败', { error: error.message });
    });
  });
  $('uploadProjectZipUpdateBtn').addEventListener('click', () => {
    uploadProjectZipUpdateFromUi().catch((error) => {
      renderProjectUpdateResult({ error: error.message });
      log('Web 项目 zip 更新失败', { error: error.message });
    });
  });
  $('rollbackProjectUpdateBtn').addEventListener('click', () => {
    rollbackProjectUpdateFromUi().catch((error) => {
      renderProjectUpdateResult({ error: error.message });
      log('Web 项目回滚失败', { error: error.message });
    });
  });
  $('refreshUpdateStatusBtn').addEventListener('click', () => {
    refreshUpdateStatus().catch((error) => log('更新状态刷新失败', { error: error.message }));
  });
  $('runGithubUpdateBtn').addEventListener('click', () => {
    runGithubUpdateFromUi().catch((error) => {
      renderUpdateResult({ error: error.message });
      log('官网优先更新失败', { error: error.message });
    });
  });
  $('uploadZipUpdateBtn').addEventListener('click', () => {
    uploadZipUpdateFromUi().catch((error) => {
      renderUpdateResult({ error: error.message });
      log('zip 更新失败', { error: error.message });
    });
  });
  $('rollbackUpdateBtn').addEventListener('click', () => {
    rollbackUpdateFromUi().catch((error) => {
      renderUpdateResult({ error: error.message });
      log('核心代码回滚失败', { error: error.message });
    });
  });
  const qmtUpdateProgressCloseBtn = $('qmtUpdateProgressCloseBtn');
  if (qmtUpdateProgressCloseBtn) qmtUpdateProgressCloseBtn.addEventListener('click', closeQmtUpdateProgress);
  const qmtUpdateProgressCloseBottomBtn = $('qmtUpdateProgressCloseBottomBtn');
  if (qmtUpdateProgressCloseBottomBtn) qmtUpdateProgressCloseBottomBtn.addEventListener('click', closeQmtUpdateProgress);
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
  $('ordersBtn').addEventListener('click', () => refreshAccount('orders', { force: true, subscribe: false }).catch((error) => log('委托刷新失败', { error: error.message })));
  const realtimeOrdersToggle = $('autoRefresh');
  if (realtimeOrdersToggle) {
    realtimeOrdersToggle.addEventListener('change', () => {
      if (realtimeOrdersToggle.checked) connectOrderCallbackSocket({ force: true });
      else closeOrderCallbackSocket();
    });
  }
  const callbackRefreshBtn = $('callbackRefreshBtn');
  if (callbackRefreshBtn) {
    callbackRefreshBtn.addEventListener('click', () => refreshCallbacks().catch((error) => log('回调刷新失败', { error: error.message })));
  }
  const callbackReconnectBtn = $('callbackReconnectBtn');
  if (callbackReconnectBtn) {
    callbackReconnectBtn.addEventListener('click', () => restartOrderCallbackSocket());
  }
  const callbackClearBtn = $('callbackClearBtn');
  if (callbackClearBtn) {
    callbackClearBtn.addEventListener('click', () => {
      state.callbackEvents = [];
      state.callbackLastEventAt = '';
      state.callbackLastEventName = '';
      renderCallbacks();
    });
  }
  $('clearLogBtn').addEventListener('click', () => { $('logBox').innerHTML = ''; });
  $('bridgeSelect').addEventListener('change', handleBridgeChange);
  $('accountInput').addEventListener('change', handleAccountChange);
  $('queryChannel').addEventListener('change', selectedChannel);
  $('tradeChannel').addEventListener('change', selectedTradeChannel);
  bindTransportControls();
  state.webAuthToken = savedWebAuthToken();
  await loadConfig();
  loadApiOpenGroups();
  renderApiDocs();
  if (await ensureWebAuth()) {
    await continueAfterConfig();
  }
}

boot().catch((error) => log('启动失败', { error: error.message }));
