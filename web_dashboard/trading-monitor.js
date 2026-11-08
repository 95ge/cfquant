/* Passive monitor: uses the existing authenticated API client. */
(() => {
  const root = document.getElementById('tradingMonitor');
  if (!root) return;
  const today = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const e = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const n = (value, digits = 0) => value == null ? '—' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits: digits});
  const percent = value => value == null ? '—' : `${n(value * 100, 2)}%`;
  const stamp = value => value ? new Date(value * 1000).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) : '—';
  const labels = {order:'委托回报', trade:'成交', order_error:'委托异常', cancel_error:'撤单异常', order_request:'报单请求', cancel_request:'撤单请求'};
  const statuses = {48:'未报',49:'待报',50:'已报',51:'已报待撤',52:'部成待撤',53:'部撤',54:'已撤',55:'部成',56:'已成',57:'废单'};
  let page = 1, timer, busy = false, rerun = false, last = null, applied = null, sequence = 0, followToday = true;
  let saving = false, collector = {enabled:false}, entryAttempt = 0, enterView = null, settingsMode = false, configuredRetentionDays = 30;
  root.innerHTML = `
    <div class="monitor-heading"><div><span class="monitor-kicker">运行观测 / 交易风控</span><h2>交易监控</h2><p>集中查看各 QMT 通道、交易回报与执行质量。</p></div><div class="monitor-heading-actions"><span id="monitorFreshness" role="status">等待采集</span><button id="monitorSettings" type="button">监控设置</button><button id="monitorNotificationSettings" type="button">\u901a\u77e5\u8bbe\u7f6e</button></div></div>
    <div class="monitor-control-head"><span id="monitorControlStatus" role="status">正在读取采集状态…</span><span id="monitorScopeSummary" class="monitor-note"></span></div>
    <template id="monitorImpactTemplate"><div class="monitor-control">
      <p>设置会保存，重启后沿用。开关和账号范围仅影响新增采集，历史记录保留，可按日期、账号查询；页面关闭不影响已开启的采集。</p>
      <p id="monitorImpact">延迟影响：本机离线基准中，每次交易请求额外同步开销约 0.008–0.011 ms（中位数），单条回调筛选与入队约 0.006 ms。数据库在后台写入，交易请求不等待落盘；CPU、磁盘争用仍可能增加尾延迟，实际增量取决于机器与流量。</p>
      <details class="monitor-benchmark"><summary>基准测试范围</summary><p>2026-11-03，Windows / Python 3.12.4；7 轮 × 2,000 次，含账号范围筛选与实际 SQLite 后台写入，交易调用使用离线替身，无真实下单。开启路径 P95 为 0.015 ms、单次最大 0.191 ms；回调筛选与入队单次最大 0.507 ms。以上只测同步采集路径，不是实盘端到端耗时或延迟上限。关闭后跳过计时、事件复制及入队，仅保留开关判断；已入队记录会继续保存。</p></details>
    </div></template>
    <form id="monitorFilters" class="monitor-filters">
      <label>开始日期<input name="start" type="date" required value="${today()}" aria-label="监控开始日期"></label>
      <label>结束日期<input name="end" type="date" required value="${today()}" aria-label="监控结束日期"></label>
      <label>QMT 部署<select name="bridge_id" aria-label="监控部署"><option value="">全部部署</option></select></label>
      <label>账号<select name="account" aria-label="监控账号"><option value="">全部账号</option></select></label>
      <button class="primary" type="submit">查询</button><button id="monitorToday" type="button">今天</button>
      <label class="monitor-auto"><input id="monitorAuto" type="checkbox" checked>自动刷新</label>
    </form>
    <div id="monitorError" class="monitor-alert hidden" role="alert"></div>
    <div id="monitorHealth" class="monitor-health" role="status">正在读取监控记录…</div>
    <div class="monitor-tabs" role="tablist" aria-label="监控内容"><button id="monitorTabTrading" class="monitor-tab is-active" type="button" role="tab" aria-selected="true" aria-controls="monitorTradingPanel" tabindex="0">交易监控</button><button id="monitorTabRuntime" class="monitor-tab" type="button" role="tab" aria-selected="false" aria-controls="monitorRuntimePanel" tabindex="-1">运行诊断</button></div>
    <section id="monitorTradingPanel" class="monitor-tab-panel" role="tabpanel" aria-labelledby="monitorTabTrading">
      <div id="monitorStats" class="monitor-stats" aria-label="交易汇总"></div>
      <div class="monitor-detail-grid">
      <section class="panel monitor-trend"><div class="panel-head"><h3>交易流速</h3><span id="monitorBucket" class="metric-note"></span></div><div class="monitor-legend"><span>委托</span><span>成交</span><span>撤成</span></div><div id="monitorChart"></div><p class="monitor-note">按首次采集时间聚合；重连补发可能形成峰值。图中速率为每个时间桶的笔数 ÷ 桶宽。</p></section>
      <section class="panel"><div class="panel-head"><h3>交易请求延迟</h3><span class="metric-note">Web → QMT → Web</span></div><dl id="monitorLatency" class="monitor-latency"></dl><p class="monitor-note">统计经过 Web 统一路由的报单、撤单请求。包含排队与失败请求，不代表交易所确认耗时。</p></section>
      </div>
      <section class="panel"><div class="panel-head"><h3>QMT 通道在线情况</h3><span id="monitorNodeSummary" class="metric-note"></span></div><p id="monitorNodeNote" class="monitor-note"></p><div class="monitor-table-wrap"><table><thead><tr><th>部署</th><th>模式</th><th>通道</th><th>连接状态</th><th>探测往返</th><th>采样时间</th><th>说明</th></tr></thead><tbody id="monitorNodes"></tbody></table></div></section>
      <section class="panel"><div class="panel-head"><h3>交易与异常记录</h3><label class="monitor-kind">事件类型 <select id="monitorKind" aria-label="监控事件类型"><option value="">全部事件</option><option value="order">委托回报</option><option value="trade">成交</option><option value="abnormal">异常记录</option><option value="order_request">报单请求</option><option value="cancel_request">撤单请求</option></select></label></div><div class="monitor-table-wrap"><table><thead><tr><th>采集时间</th><th>业务日期</th><th>部署 / 账号</th><th>类型</th><th>证券 / 委托号</th><th>状态 / 成交量</th><th>说明</th></tr></thead><tbody id="monitorEvents"></tbody></table></div><div class="monitor-pagination"><span id="monitorPageText"></span><button id="monitorPrev" type="button">上一页</button><button id="monitorNext" type="button">下一页</button></div></section>
      <details class="monitor-definitions"><summary>指标口径与采集范围</summary><p>委托笔数按业务日期、部署、账号类型、账号、证券和委托号去重；成交笔数按成交编号去重。缺少编号时可能无法可靠去重，缺少日期时使用北京时间采集日期。</p><p>成交率 = 至少部分成交的委托笔数 ÷ 委托笔数。撤单率 = 实际撤成（含部撤）委托数 ÷ 委托笔数；报撤比 = 委托笔数 ÷ 撤成笔数。分母为零显示 —。撤单请求按 RPC 请求次数统计，批量调用计一次。</p><p>异常记录包含废单回报、委托/撤单错误及请求失败，同一业务单可能有多条异常记录。这里提供观测与留痕，不增加自动拦单规则。</p><p>开启监控后，服务运行期间持续采集，不依赖页面打开；「自动刷新」仅控制页面更新。仅包含本服务收到的回调和探测；关闭监控或停机期间不会自动补齐，历史查询单次最多 31 天。当前采集不等同于券商全量对账。</p><p id="monitorStorage"></p></details>
    </section>
    <section id="monitorRuntimePanel" class="monitor-tab-panel" role="tabpanel" aria-labelledby="monitorTabRuntime" hidden>
      <section class="panel"><div class="panel-head"><h3>QMT 运行实例</h3><span class="metric-note">点击查看分钟时序</span></div><p class="monitor-note">运行时序全天按分钟保存，交易时段和休市时段都可用于判断 QMT 进程、桥接和通道是否健康。选择一个 QMT 实例默认查看全部历史，可切换日期范围、指标和明细。</p><div id="monitorRuntimeTargets" class="monitor-runtime-targets"></div></section>
      <dialog id="monitorRuntimeDetail" class="panel monitor-runtime-dialog monitor-runtime-detail" aria-labelledby="monitorRuntimeDetailTitle"><div class="panel-head"><h3 id="monitorRuntimeDetailTitle">QMT 时序详情</h3><div class="panel-actions"><button id="monitorRuntimeCleanup" type="button">清理过期时序</button><button id="monitorRuntimeClearAll" type="button">清空全部时序</button><button id="monitorRuntimeDetailClose" type="button">关闭详情</button></div></div><p id="monitorRuntimeDetailNote" class="monitor-note"></p><div id="monitorRuntimeMetricCards" class="monitor-runtime-metric-cards" aria-label="运行时序指标摘要"></div><div class="monitor-runtime-chart-toolbar"><label>历史范围<select id="monitorRuntimeRange" aria-label="运行时序历史范围"><option value="all" selected>全部历史</option><option value="selected">当前查询</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option><option value="365">最近 1 年</option></select></label><button id="monitorRuntimeReload" type="button">刷新时序</button></div><div id="monitorRuntimeCharts" class="monitor-runtime-chart-grid" aria-label="运行时序图表"></div><div class="monitor-table-wrap"><table><thead><tr><th>采样时间</th><th>进程</th><th>CPU</th><th>内存</th><th>回调</th><th>行情回调</th><th>行情分发</th><th>请求</th></tr></thead><tbody id="monitorRuntimeSamples"></tbody></table></div></dialog>
      <section class="panel monitor-performance"><div class="panel-head"><h3>cfquant 处理效率与 QMT 资源</h3><span class="metric-note">按部署 / 运行实例采样</span></div>
        <p id="monitorPerformanceNote" class="monitor-note"></p><div id="monitorPerformance"></div>
        <details class="monitor-definitions"><summary>运行指标口径</summary><p>累计值从 QMT 桥接实例启动时开始；速率由相邻两次有效采样计算，首次采样显示 —。这些指标属于整个桥接实例，不按上方交易账号筛选。QMT 数据回调合计包含交易回调和原生行情回调，不含定时器；全推由多个用户共享时仅计一次。</p><p>行情分发统计交给发送层的批次，多订阅者可能形成多批；不代表用户已收到。无人订阅时，行情回调可继续增长而分发为零。请求耗时包含 QMT 端排队与处理，不含 Web 网络往返；状态/存活探测不计入请求完成数。</p><p>CPU 为本机 QMT 进程占整机逻辑处理器容量的比例，内存为驻留内存 RSS；同 PID 的查询和交易通道共享资源，不能重复相加。历史查询展示所选日期内最后一次采样。</p></details>
      </section>

    </section>`;
  const $ = id => document.getElementById(id);
  const dialog = document.createElement('dialog');
  dialog.id = 'monitorSettingsDialog';
  dialog.className = 'monitor-dialog';
  dialog.setAttribute('aria-labelledby', 'monitorDialogTitle');
  dialog.innerHTML = `<form id="monitorSettingsForm">
    <h2 id="monitorDialogTitle">开启交易监控？</h2>
    <p id="monitorDialogIntro"></p>
    <div id="monitorSettingsFields" hidden>
      <label class="monitor-switch"><input id="monitorEnabled" type="checkbox" role="switch" aria-describedby="monitorImpact">开启交易监控</label>
      <label class="monitor-retention">运行时序保留<select id="monitorRuntimeRetentionPreset" aria-label="运行时序保留预设"><option value="5">5 天</option><option value="7">7 天</option><option value="30">30 天（默认）</option><option value="90">90 天</option><option value="365">1 年</option><option value="custom">自定义天数</option><option value="all">全部保留</option></select><input id="monitorRuntimeRetentionDays" type="number" min="1" max="3650" step="1" inputmode="numeric" list="monitorRetentionSuggestions"><datalist id="monitorRetentionSuggestions"><option value="5"><option value="7"><option value="30"><option value="90"><option value="365"></datalist><small>默认 30 天，到期自动清理；选择“全部保留”表示不自动删除。这里保存全天的分钟采样。</small></label>
      <fieldset class="monitor-account-scope"><legend>监控账号</legend>
        <label><input type="radio" name="monitorScope" value="all" checked>全部已绑定账号（默认）</label>
        <label><input type="radio" name="monitorScope" value="selected">指定账号</label>
        <p class="monitor-note">全部账号会自动包含后续新增绑定；指定账号仅采集勾选的账号及其关联 QMT 通道。</p>
        <div id="monitorAccounts" class="monitor-accounts"></div>
        <p id="monitorMissingAccounts" class="monitor-note"></p>
      </fieldset>
    </div>
    ${$('monitorImpactTemplate').innerHTML}
    <p id="monitorSettingsError" class="monitor-error-text" role="alert" hidden></p>
    <div class="monitor-dialog-actions"><button id="monitorDialogCancel" type="button">取消</button><button id="monitorAdjustSettings" type="button">调整设置</button><button id="monitorDialogSave" type="submit" class="primary">开启并进入</button></div>
  </form>`;
  document.body.append(dialog);
  const form = $('monitorFilters');
  $('monitorEvents').closest('.monitor-table-wrap').classList.add('monitor-events-scroll');
  const monitorTabs = [
    {button: $('monitorTabTrading'), panel: $('monitorTradingPanel')},
    {button: $('monitorTabRuntime'), panel: $('monitorRuntimePanel')},
  ];
  function setMonitorTab(name, focus = false) {
    const runtime = name === 'runtime';
    if (!runtime) {
      const detail = $('monitorRuntimeDetail');
      if (detail && detail.open) detail.close();
    }
    monitorTabs.forEach(({button, panel}) => {
      const active = runtime === (button.id === 'monitorTabRuntime');
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
      if (active && focus) button.focus();
    });
  }
  monitorTabs.forEach(({button}) => {
    button.addEventListener('click', () => setMonitorTab(button.id === 'monitorTabRuntime' ? 'runtime' : 'trading'));
    button.addEventListener('keydown', event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      setMonitorTab(button.id === 'monitorTabRuntime' ? 'trading' : 'runtime', true);
    });
  });
  function renderControl(value) {
    collector = value;
    const retention = Number(value.runtime_retention_days) === 0 ? '全部保留' : `${value.runtime_retention_days || 30} 天`;
    $('monitorControlStatus').textContent = value.draining ? '已停止新增采集，正在保存队列记录…' : value.enabled ? '监控已开启' : '监控已关闭 · 历史记录保留';
    $('monitorScopeSummary').textContent = (value.account_keys == null ? '采集范围：全部已绑定账号' : `采集范围：指定 ${value.account_keys.length} 个账号`) + ` · 时序保留 ${retention}`;
  }
  function showError(message) {
    $('monitorSettingsError').textContent = message;
    $('monitorSettingsError').hidden = !message;
  }
  function setSaving(value) {
    saving = value;
    dialog.querySelectorAll('button, input').forEach(node => { node.disabled = value; });
    if (!value) syncScope();
    dialog.setAttribute('aria-busy', String(value));
  }
  function syncScope() {
    const all = $('monitorSettingsForm').elements.monitorScope.value === 'all';
    dialog.querySelectorAll('[name=monitorAccount]').forEach(node => { node.disabled = saving || all; });
  }
  function populateSettings(value) {
    renderControl(value);
    $('monitorEnabled').checked = !!value.enabled;
    configuredRetentionDays = Number.isInteger(value.runtime_retention_days) ? value.runtime_retention_days : 30;
    const preset = $('monitorRuntimeRetentionPreset');
    const knownPresets = new Set(['5', '7', '30', '90', '365', 'all']);
    preset.value = configuredRetentionDays === 0 ? 'all' : knownPresets.has(String(configuredRetentionDays)) ? String(configuredRetentionDays) : 'custom';
    $('monitorRuntimeRetentionDays').value = configuredRetentionDays === 0 ? 30 : configuredRetentionDays;
    $('monitorSettingsForm').elements.monitorScope.value = value.account_keys == null ? 'all' : 'selected';
    const selected = new Set(value.account_keys || []), accounts = value.accounts || [];
    $('monitorAccounts').innerHTML = accounts.length ? accounts.map(row => `<label class="monitor-account"><input type="checkbox" name="monitorAccount" value="${e(row.account_key)}" ${selected.has(row.account_key) || value.account_keys == null ? 'checked' : ''}><span><strong>${e(row.display_name || row.account_id)}</strong><small>${e(row.account_id)} · ${e(row.account_type)} · ${e(row.bridge_id)}${row.binding_enabled === false ? ' · 绑定已停用' : ''}</small></span></label>`).join('') : '<p class="monitor-note">暂无已绑定的 QMT 账号。选择全部账号后，新增绑定将自动纳入监控。</p>';
    const missing = [...selected].filter(key => !accounts.some(row => row.account_key === key)).length;
    $('monitorMissingAccounts').textContent = missing ? `${missing} 个此前选择的账号已解绑，不再采集；保存时将移除这些选择。` : '';
    syncScope();
  }
  function showDialog(settings) {
    settingsMode = settings;
    $('monitorDialogTitle').textContent = settings ? '交易监控设置' : '开启交易监控？';
    $('monitorDialogIntro').textContent = settings ? '选择是否采集，以及需要监控的已绑定 QMT 账号。保存后立即生效。' : `交易监控当前未开启。确认后进入监控界面，并持续记录${collector.account_keys == null ? '全部已绑定账号' : '此前选择的账号'}的交易情况与 QMT 通道状态。`;
    $('monitorSettingsFields').hidden = !settings;
    $('monitorAdjustSettings').hidden = settings;
    $('monitorDialogSave').textContent = settings ? '保存设置' : '开启并进入';
    showError('');
    if (!dialog.open) dialog.showModal();
  }
  function cancelEntry() {
    entryAttempt++;
    enterView = null;
    if (dialog.open && !saving) dialog.close();
  }
  async function enter(commit) {
    if (saving) return;
    const attempt = ++entryAttempt;
    enterView = commit;
    try {
      const value = await api('/api/monitor/settings', {signal:AbortSignal.timeout(15000)});
      if (attempt !== entryAttempt) return;
      setSaving(false); populateSettings(value);
      if (value.enabled) { enterView = null; commit(); }
      else showDialog(false);
    } catch (error) {
      if (attempt !== entryAttempt) return;
      setSaving(false); showDialog(false);
      showError(`无法读取监控设置：${error.message}。请取消后重试。`);
      $('monitorDialogSave').disabled = $('monitorAdjustSettings').disabled = true;
    }
  }
  window.CfquantMonitor = {enter, cancelEntry};
  $('monitorDialogCancel').addEventListener('click', cancelEntry);
  dialog.addEventListener('cancel', event => { event.preventDefault(); if (!saving) cancelEntry(); });
  $('monitorAdjustSettings').addEventListener('click', () => { showDialog(true); $('monitorEnabled').checked = true; });
  $('monitorSettingsForm').elements.monitorScope.forEach(node => node.addEventListener('change', syncScope));
  $('monitorRuntimeRetentionPreset').addEventListener('change', event => {
    if (event.target.value !== 'custom' && event.target.value !== 'all') {
      $('monitorRuntimeRetentionDays').value = event.target.value;
    }
  });
  $('monitorRuntimeRetentionDays').addEventListener('input', () => {
    $('monitorRuntimeRetentionPreset').value = 'custom';
  });
  $('monitorSettings').addEventListener('click', async () => {
    enterView = null;
    showDialog(true); setSaving(true);
    try {
      populateSettings(await api('/api/monitor/settings', {signal:AbortSignal.timeout(15000)}));
      setSaving(false);
    } catch (error) {
      setSaving(false);
      showError(`无法读取监控设置：${error.message}。请关闭后重试。`);
      $('monitorDialogSave').disabled = true;
    }
  });
  $('monitorSettingsForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || $('monitorDialogSave').disabled) return;
    const enabled = settingsMode ? $('monitorEnabled').checked : true;
    const payload = {enabled};
    if (settingsMode) {
      payload.account_keys = $('monitorSettingsForm').elements.monitorScope.value === 'all' ? null : [...dialog.querySelectorAll('[name=monitorAccount]:checked')].map(node => node.value);
      if (enabled && payload.account_keys?.length === 0) { showError('请至少选择一个已绑定的 QMT 账号，或选择全部账号。'); return; }
      const preset = $('monitorRuntimeRetentionPreset').value;
      const retention = preset === 'all' ? 0 : Number($('monitorRuntimeRetentionDays').value);
      if (retention !== 0 && (!Number.isInteger(retention) || retention < 1 || retention > 3650)) { showError('运行时序保留天数必须是 1 到 3650 的整数，或选择全部保留。'); return; }
      if (retention !== configuredRetentionDays) payload.runtime_retention_days = retention;
    }
    setSaving(true); showError(''); sequence++;
    try {
      const value = await api('/api/monitor/settings', {method:'POST', body:JSON.stringify(payload), signal:AbortSignal.timeout(20000)});
      renderControl(value);
      dialog.close();
      const commit = enterView; enterView = null;
      if (commit && value.enabled) commit();
      else refresh();
    } catch (error) {
      showError(`设置保存失败：${error.message}。请重试；如请求超时，可取消后重新打开确认状态。`);
    } finally { setSaving(false); }
  });
  function filters() {
    const values = new FormData(form), account = JSON.parse(values.get('account') || '[]');
    return {start: values.get('start'), end: values.get('end'), bridge_id: values.get('bridge_id'), account_id: account[0] || '', account_type: account[1] || ''};
  }
  function setOptions(select, rows, label) {
    const value = select.value;
    select.innerHTML = `<option value="">${label}</option>` + rows.map(row => `<option value="${e(row[0])}">${e(row[1])}</option>`).join('');
    if (value && !rows.some(row => row[0] === value)) select.add(new Option(value, value));
    select.value = value;
  }
  function render(data) {
    last = data;
    const s = data.stats, c = data.collector;
    renderControl(c);
    renderPerformance(data);
    const issues = [];
    if (c.enabled && !c.running) issues.push('采集器未运行');
    if (c.error) issues.push(c.error);
    if (c.dropped) issues.push(`有 ${c.dropped} 条事件未保存，统计可能不完整`);
    if (c.pending > 1000) issues.push(`有 ${c.pending} 条记录等待入库`);
    const activeNodes = data.nodes.filter(node => node.collecting !== false);
    const badNodes = activeNodes.filter(node => !node.online || node.stale);
    if (s.abnormal_count) issues.push(`所选期间有 ${s.abnormal_count} 条异常记录`);
    if (data.live && c.enabled && badNodes.length) issues.push(`${badNodes.length} 个通道离线或采样过期`);
    $('monitorHealth').classList.toggle('has-issues', issues.length > 0);
    $('monitorHealth').textContent = issues.join('；') || (!c.enabled ? '监控已关闭，当前展示已有历史记录；开启后开始新增采集。' : data.nodes.length ? '已采集记录中未发现异常。' : '等待通道采样；收到交易回调后将自动记录。');
    $('monitorFreshness').textContent = `${!c.enabled ? '采集关闭 / 历史记录' : data.live ? '实时观测' : '历史回看'} · ${stamp(data.generated_at)}`;
    const metrics = [
      ['委托笔数', n(s.order_count), '去重后的委托'], ['成交笔数', n(s.trade_count), '独立成交回报'],
      ['异常记录', n(s.abnormal_count), `废单 ${n(s.rejected_count)} · 错误回调 ${n(s.error_count)} · 请求失败 ${n(s.failed_request_count)}`],
      ['撤成笔数', n(s.canceled_count), `撤单请求 ${n(s.cancel_request_count)} 次`],
      ['成交率', percent(s.fill_ratio), '含部分成交委托'], ['撤单率 / 报撤比', `${percent(s.cancel_ratio)} / ${n(s.report_cancel_ratio, 2)}`, '撤成 / 委托 · 委托 / 撤成'],
      ['委托流速', `${n(s.order_rate, 3)}${s.order_rate == null ? '' : ' 笔/s'}`, '最近 60 秒平均'],
      ['成交流速', `${n(s.trade_rate, 3)}${s.trade_rate == null ? '' : ' 笔/s'}`, '最近 60 秒平均'],
    ];
    $('monitorStats').innerHTML = metrics.map(([label, value, note], i) => `<div class="monitor-stat ${i === 2 && s.abnormal_count ? 'has-issues' : ''}"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('');
    $('monitorLatency').innerHTML = [['平均',s.latency.avg_ms],['P95',s.latency.p95_ms],['最大',s.latency.max_ms]].map(([label, value]) => `<div><dt>${label}</dt><dd>${n(value, 2)} <small>ms</small></dd></div>`).join('') + `<div><dt>请求样本</dt><dd>${n(s.latency.count)} <small>次</small></dd></div>`;
    $('monitorBucket').textContent = `${n(data.bucket_seconds / 60)} 分钟 / 桶`;
    renderChart(data);
    $('monitorNodeSummary').textContent = data.live && c.enabled ? `${activeNodes.filter(node => node.online && !node.stale).length} / ${activeNodes.length} 个采集中通道在线` : `${data.nodes.length} 个通道的最后采样`;
    $('monitorNodeNote').textContent = data.live && c.enabled ? '按部署、模式与查询/交易通道展示；无心跳更新超过 3 个采样周期（至少 30 秒）标为过期。未纳入采集的通道仅保留历史采样。通用模式仅判断连接，不提供探测往返耗时。' : '以下状态来自所选日期范围内的最后采样，不表示当前在线状态。';
    $('monitorNodes').innerHTML = data.nodes.length ? data.nodes.map(node => `<tr><td>${e(node.name || node.bridge_id)}<small>${e(node.bridge_id)}</small></td><td>${e({ctypes:'通用', lttx:'高级', lite:'轻量'}[node.mode] || node.mode)}</td><td>${node.channel === 'normal' ? '查询' : '交易'}</td><td>${nodeState(node, data.live && c.enabled)}</td><td>${n(node.latency_ms, 2)} ms</td><td>${stamp(node.checked_at)}</td><td>${e(node.message) || '—'}</td></tr>`).join('') : '<tr><td colspan="7" class="monitor-empty">所选日期暂无 QMT 通道采样。</td></tr>';
    $('monitorEvents').innerHTML = data.events.length ? data.events.map(row => `<tr><td>${stamp(row.received_at)}</td><td>${e(row.trade_date)}</td><td>${e(row.bridge_id) || '—'}<small>${e(row.account_id) || '未提供账号'} · ${e(row.account_type)}</small></td><td><span class="${row.failed ? 'monitor-error-text' : ''}">${labels[row.kind] || e(row.kind)}</span></td><td>${e(row.symbol) || '—'}<small>${e(row.order_id) || '—'}</small></td><td>${row.kind === 'order' ? e(statuses[row.status] || row.status) : row.kind === 'trade' ? n(row.volume) : row.failed ? '失败 / 待核实' : '已返回'}${row.latency_ms == null ? '' : `<small>${n(row.latency_ms, 2)} ms</small>`}</td><td>${e(row.message) || '—'}</td></tr>`).join('') : '<tr><td colspan="7" class="monitor-empty">所选条件下没有记录。服务收到回调后会自动保存，可切换日期或事件类型查看。</td></tr>';
    $('monitorPageText').textContent = `共 ${n(data.total)} 条 · 第 ${data.page} / ${Math.max(1, Math.ceil(data.total / data.page_size))} 页`;
    $('monitorPrev').disabled = data.page <= 1;
    $('monitorNext').disabled = data.page * data.page_size >= data.total;
    $('monitorStorage').textContent = `保存位置：runtime/db/${c.database}；开始采集：${stamp(data.started_at)}；待写入 ${n(c.pending)} 条。`;
    const bridges = new Map(data.nodes.map(row => [row.bridge_id, row.name || row.bridge_id]));
    data.options.forEach(row => bridges.set(row.bridge_id, bridges.get(row.bridge_id) || row.bridge_id));
    setOptions(form.elements.bridge_id, [...bridges].filter(row => row[0]), '全部部署');
    const accounts = new Map(data.options.filter(row => row.account_id).map(row => [JSON.stringify([row.account_id, row.account_type]), `${row.account_id} · ${row.account_type}`]));
    setOptions(form.elements.account, [...accounts], '全部账号');
  }
  function nodeState(node, live) {
    if (live && node.collecting === false) return '<span class="monitor-state">未纳入采集</span>';
    if (!live) return `<span class="monitor-state">采样时${node.online ? '在线' : '离线'}</span>`;
    return `<span class="monitor-state ${node.stale || !node.online ? 'is-bad' : 'is-good'}">${node.stale ? '采样过期' : node.online ? '在线' : '离线'}</span>`;
  }
  function renderPerformance(data) {
    const live = data.live && data.collector.enabled;
    $('monitorPerformanceNote').textContent = live
      ? '随现有状态采样更新。排队、当前动作和发送积压可帮助定位订阅恢复超时；休市期间没有行情回调属于正常情况。'
      : '以下是所选日期内最后一次保存的运行采样，不代表当前负载。';
    const seen = new Set();
    const rows = data.nodes.filter(node => {
      const p = node.performance || {};
      if (!p.available) return node.channel === 'normal' || p.process?.available;
      const key = JSON.stringify([node.bridge_id, node.mode, p.pid, p.started_at]);
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });
    $('monitorPerformance').innerHTML = rows.length ? rows.map(node => {
      const p = node.performance || {}, r = p.rates || {}, proc = p.process || {}, send = p.send_queue || {};
      const stale = p.stale || node.stale || !node.online || node.collecting === false;
      const fresh = !live || !stale;
      const rate = key => fresh ? n(r[key], 2) : '—';
      const issues = [];
      if (live && stale) issues.push('采样已失效或通道未在线，下面保留最后观测值');
      if (p.request_oldest_ms >= 1000) issues.push(`请求排队已达 ${n(p.request_oldest_ms, 0)} ms`);
      if (p.active_ms >= 5000) issues.push(`当前动作执行 ${n(p.active_ms / 1000, 1)} 秒`);
      if (send.oldest_age_ms >= 1000) issues.push(`发送积压已达 ${n(send.oldest_age_ms, 0)} ms`);
      if (send.error) issues.push(`发送错误：${send.error}`);
      const cards = [
        ['请求完成速率', `${rate('request_completed_per_second')} 次/s`, `累计 ${n(p.request_completed)} 次 · 失败 ${n(p.request_failed)} 次`],
        ['请求平均耗时', `${rate('request_avg_ms')} ms`, `采样间隔 ${n(r.window_seconds, 1)} s · 累计最大 ${n(p.request_max_ms, 1)} ms`],
        ['QMT 数据回调合计', n(p.qmt_callback_total), `交易 ${n(p.callback_total)} 次 · ${rate('callback_total_per_second')} 次/s`],
        ['原生行情回调', n(p.quote_callback_batches), `${rate('quote_callback_batches_per_second')} 批/s · 累计 ${n(p.quote_callback_symbols)} 条证券更新`],
        ['行情分发', `${rate('quote_distribution_batches_per_second')} 批/s`, `累计 ${n(p.quote_distribution_batches)} 批 · 发送失败 ${n(p.quote_push_failed)} 次`],
        ['请求 / 发送队列', `${n(p.request_queue_size)} / ${n(send.queued_frames)}`, `最早排队 ${n(p.request_oldest_ms, 1)} ms · 发送缓冲 ${n(send.buffered_bytes == null ? null : send.buffered_bytes / 1048576, 2)} MiB`],
        ['QMT 进程 CPU', `${n(proc.cpu_percent, 2)}%`, proc.available ? `PID ${n(proc.pid)} · ${n(proc.threads)} 线程` : `资源暂不可用：${e(proc.reason || '等待进程标识')}`],
        ['QMT 驻留内存', `${n(proc.rss_bytes == null ? null : proc.rss_bytes / 1048576, 1)} MiB`, `${n(proc.memory_percent, 2)}% 物理内存 · ${e(proc.name || '等待进程采样')}`],
      ];
      return `<article class="monitor-runtime"><div class="monitor-runtime-heading"><strong>${e(node.name || node.bridge_id)} · ${e({ctypes:'通用',lttx:'高级',lite:'轻量'}[node.mode] || node.mode)} · ${node.channel === 'normal' ? '查询/回调' : '交易'}</strong><small>${live && !stale ? '运行采样' : '最后采样'} ${stamp(p.sampled_at || node.checked_at)}</small></div>
        ${issues.length ? `<p class="monitor-runtime-issue">${issues.map(e).join('；')}</p>` : ''}
        ${!p.available ? '<p class="monitor-note">此实例尚未上报处理指标。更新并重新运行 QMT 桥接脚本后可查看；未采集字段显示 —。</p>' : ''}
        <div class="monitor-stats">${cards.map(([label,value,note]) => `<div class="monitor-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('')}</div>
        <p class="monitor-note">当前动作：${e(p.active_action || (p.available ? '空闲' : '—'))} · 执行 ${n(p.active_ms, 1)} ms · 全推保持：${p.available ? (p.whole_quote_anchor ? '是' : '否') : '—'} · 用户行情订阅 ${n(p.quote_subscription_count)} 个<br>最近行情回调：${stamp(p.last_quote_callback_at)} · 最近交易回调：${stamp(p.last_callback_at)} · 实例启动：${stamp(p.started_at)}</p></article>`;
    }).join('') : '<p class="monitor-empty">等待运行指标采样；开启监控并运行 QMT 桥接后显示。</p>';
    const targets = new Map();
    rows.forEach(node => {
      const key = `${node.bridge_id}|${node.mode}`;
      if (!targets.has(key)) targets.set(key, node);
    });
    $('monitorRuntimeTargets').innerHTML = targets.size ? [...targets.entries()].map(([key, node]) => {
      const p = node.performance || {}, proc = p.process || {};
      return `<button class="monitor-runtime-target" type="button" data-runtime-key="${e(key)}"><strong>${e(node.name || node.bridge_id)}</strong><span>${e(node.bridge_id)} · ${e({ctypes:'通用',lttx:'高级',lite:'轻量'}[node.mode] || node.mode)}</span><small>PID ${proc.pid ? n(proc.pid) : '—'} · CPU ${n(proc.cpu_percent, 2)}% · 内存 ${n(proc.rss_bytes == null ? null : proc.rss_bytes / 1048576, 1)} MiB</small></button>`;
    }).join('') : '<p class="monitor-empty">暂无可查看的 QMT 运行实例。</p>';
    $('monitorRuntimeTargets').querySelectorAll('[data-runtime-key]').forEach(button => button.addEventListener('click', () => {
      const [bridgeId, mode] = button.dataset.runtimeKey.split('|');
      openRuntimeDetail(bridgeId, mode, button.querySelector('strong')?.textContent || bridgeId);
    }));
  }
  let runtimeDetailKey = '', runtimeDetailTitle = '', runtimeDetailData = null;
  const runtimeMetricDefinitions = [
    {key:'cpu', label:'CPU', unit:'%', digits:2},
    {key:'memory', label:'内存', unit:'MiB', digits:1},
    {key:'request_rate', label:'请求速率', unit:'次/s', digits:2},
    {key:'callback_rate', label:'回调速率', unit:'次/s', digits:2},
    {key:'distribution_rate', label:'行情分发速率', unit:'批/s', digits:2},
  ];
  function runtimeMetricValue(sample, metric) {
    const p = sample.normal && Object.keys(sample.normal).length ? sample.normal : (sample.trade || {});
    const proc = p.process || (sample.process || {}).normal || {};
    const rates = p.rates || {};
    const values = {
      cpu: proc.cpu_percent,
      memory: proc.rss_bytes == null ? null : proc.rss_bytes / 1048576,
      request_rate: rates.request_completed_per_second,
      callback_rate: rates.callback_total_per_second,
      distribution_rate: rates.quote_distribution_batches_per_second,
    };
    const value = Number(values[metric]);
    return Number.isFinite(value) ? value : null;
  }
  function renderRuntimeMetricCards(samples) {
    const rows = samples || [];
    $('monitorRuntimeMetricCards').innerHTML = runtimeMetricDefinitions.map(definition => {
      const values = rows.map(sample => runtimeMetricValue(sample, definition.key)).filter(value => value != null);
      const latest = values.length ? values[values.length - 1] : null;
      const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
      const peak = values.length ? Math.max(...values) : null;
      return '<button class="monitor-runtime-metric-card" type="button" data-runtime-metric="' + definition.key + '"><span>' + e(definition.label) + '</span><strong>' + n(latest, definition.digits) + (latest == null ? '' : ' ' + e(definition.unit)) + '</strong><small>' + (values.length ? '均值 ' + n(average, definition.digits) + ' · 峰值 ' + n(peak, definition.digits) + ' · ' + n(values.length) + ' 个样本' : '暂无可用样本') + '</small></button>';
    }).join('');
    $('monitorRuntimeMetricCards').querySelectorAll('[data-runtime-metric]').forEach(card => card.addEventListener('click', () => {
      const chart = $('monitorRuntimeCharts').querySelector('[data-runtime-chart="' + card.dataset.runtimeMetric + '"]');
      if (chart) chart.scrollIntoView({behavior:'smooth', block:'nearest'});
    }));
  }
  function renderRuntimeChart(samples, definition, target) {
    const {label, unit, digits} = definition;
    let rows = (samples || []).map(sample => ({
      time: Number(sample.sampled_at),
      value: runtimeMetricValue(sample, definition.key),
    })).filter(row => Number.isFinite(row.time) && row.value != null);
    if (!rows.length) {
      target.innerHTML = '<div class="monitor-empty monitor-chart-empty">暂无可绘制的 ' + e(label) + ' 时序<br><small>该指标可能尚未上报，或所选范围没有采样。</small></div>';
      return;
    }
    if (rows.length > 360) {
      const step = Math.ceil(rows.length / 360);
      rows = rows.filter((row, index) => index === 0 || index === rows.length - 1 || index % step === 0);
    }
    const values = rows.map(row => row.value);
    const min = Math.min(...values), max = Math.max(...values);
    const span = max - min || Math.max(Math.abs(max) * .1, 1);
    const low = Math.max(0, min - span * .12), high = max + span * .12;
    const x = time => 62 + (time - rows[0].time) / (rows[rows.length - 1].time - rows[0].time || 1) * 816;
    const y = value => 184 - (value - low) / (high - low) * 142;
    const points = rows.map(row => x(row.time).toFixed(2) + ',' + y(row.value).toFixed(2)).join(' ');
    const grid = [0, .5, 1].map(ratio => {
      const value = high - (high - low) * ratio;
      return '<line class="monitor-gridline" x1="62" x2="878" y1="' + y(value) + '" y2="' + y(value) + '"/><text x="54" y="' + (y(value) + 4) + '" text-anchor="end">' + n(value, 2) + '</text>';
    }).join('');
    target.innerHTML = '<svg viewBox="0 0 920 232" role="img" aria-label="' + e(label) + '历史时序图" tabindex="0"><title>' + e(label) + '历史时序图（' + e(unit) + '）</title>' + grid + '<polyline class="monitor-runtime-line" points="' + points + '"/><line class="monitor-runtime-hover-line" x1="62" x2="62" y1="26" y2="184" hidden/><circle class="monitor-runtime-hover-dot" cx="62" cy="184" r="4" hidden/><text x="62" y="216">' + e(stamp(rows[0].time)) + '</text><text x="878" y="216" text-anchor="end">' + e(stamp(rows[rows.length - 1].time)) + '</text><text x="878" y="26" text-anchor="end">' + e(label) + ' · ' + e(unit) + '</text></svg><div class="monitor-runtime-chart-tooltip" hidden></div>';
    const svg = target.querySelector('svg');
    const hoverLine = target.querySelector('.monitor-runtime-hover-line');
    const hoverDot = target.querySelector('.monitor-runtime-hover-dot');
    const tooltip = target.querySelector('.monitor-runtime-chart-tooltip');
    const hideHover = () => { hoverLine.hidden = true; hoverDot.hidden = true; tooltip.hidden = true; };
    const updateHover = event => {
      const rect = svg.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
      const index = Math.round(ratio * (rows.length - 1));
      const row = rows[index];
      const plotX = x(row.time), plotY = y(row.value);
      hoverLine.setAttribute('x1', plotX); hoverLine.setAttribute('x2', plotX); hoverLine.hidden = false;
      hoverDot.setAttribute('cx', plotX); hoverDot.setAttribute('cy', plotY); hoverDot.hidden = false;
      tooltip.innerHTML = '<strong>' + e(stamp(row.time)) + '</strong><span>' + e(label) + ' ' + n(row.value, digits) + ' ' + e(unit) + '</span>';
      tooltip.hidden = false;
      const left = Math.max(8, Math.min(target.clientWidth - 178, plotX / 920 * target.clientWidth - 78));
      tooltip.style.left = left + 'px';
    };
    svg.addEventListener('pointermove', updateHover);
    svg.addEventListener('pointerleave', hideHover);
    svg.addEventListener('focus', event => { if (event.target === svg) updateHover({clientX: svg.getBoundingClientRect().left + svg.getBoundingClientRect().width / 2}); });
    svg.addEventListener('blur', hideHover);
  }
  function renderRuntimeCharts(samples) {
    const target = $('monitorRuntimeCharts');
    target.innerHTML = runtimeMetricDefinitions.map(definition => '<article class="monitor-runtime-chart-card" data-runtime-chart="' + definition.key + '"><div class="monitor-runtime-chart-card-head"><strong>' + e(definition.label) + '</strong><span>' + e(definition.unit) + '</span></div><div class="monitor-runtime-chart" data-runtime-chart-canvas="' + definition.key + '"></div></article>').join('');
    runtimeMetricDefinitions.forEach(definition => {
      const chart = target.querySelector('[data-runtime-chart-canvas="' + definition.key + '"]');
      renderRuntimeChart(samples, definition, chart);
    });
  }
  function renderRuntimeDetail(data, title) {
    runtimeDetailData = data || {samples: []};
    runtimeDetailTitle = title;
    const samples = runtimeDetailData.samples || [];
    $('monitorRuntimeDetailTitle').textContent = title + ' · 分钟时序';
    const retention = Number(runtimeDetailData.retention_days) === 0 ? '全部保留' : n(runtimeDetailData.retention_days) + ' 天';
    const range = runtimeDetailData.start === 'all' ? '全部历史' : runtimeDetailData.start + ' 至 ' + runtimeDetailData.end;
    $('monitorRuntimeDetailNote').textContent = '查询 ' + range + '，共 ' + n(samples.length) + ' 个样本；当前保留期 ' + retention + (samples.length >= 10000 ? '；结果达到单次查询上限，请缩小范围查看完整明细' : '') + '。';
    renderRuntimeMetricCards(samples);
    renderRuntimeCharts(samples);
    $('monitorRuntimeSamples').innerHTML = samples.length ? samples.map(sample => {
      const p = sample.normal && Object.keys(sample.normal).length ? sample.normal : (sample.trade || {});
      const proc = p.process || (sample.process || {}).normal || {};
      const rates = p.rates || {};
      return '<tr><td>' + stamp(sample.sampled_at) + '</td><td>PID ' + n(proc.pid) + '<small>' + e(proc.name || '—') + '</small></td><td>' + n(proc.cpu_percent, 2) + '%</td><td>' + n(proc.rss_bytes == null ? null : proc.rss_bytes / 1048576, 1) + ' MiB<small>' + n(proc.memory_percent, 2) + '%</small></td><td>' + n(p.qmt_callback_total) + '<small>' + n(rates.callback_total_per_second, 2) + ' 次/s</small></td><td>' + n(p.quote_callback_batches) + '<small>' + n(rates.quote_callback_batches_per_second, 2) + ' 批/s</small></td><td>' + n(p.quote_distribution_batches) + '<small>' + n(rates.quote_distribution_batches_per_second, 2) + ' 批/s</small></td><td>' + n(p.request_completed) + '<small>' + n(rates.request_completed_per_second, 2) + ' 次/s</small></td></tr>';
    }).join('') : '<tr><td colspan="8" class="monitor-empty">该日期和 QMT 暂无分钟采样。</td></tr>';
  }
  function runtimeRangeQuery(bridgeId, mode) {
    const values = applied || filters();
    const range = $('monitorRuntimeRange').value;
    let start = values.start, end = values.end;
    if (range === 'all') {
      start = 'all'; end = today();
    } else if (range !== 'selected') {
      const days = Number(range);
      const endDate = new Date();
      const beginDate = new Date(endDate.getTime() - Math.max(1, days - 1) * 86400000);
      start = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(beginDate);
      end = today();
    }
    return new URLSearchParams({start, end, bridge_id: bridgeId, mode, limit: '10000'});
  }
  async function openRuntimeDetail(bridgeId, mode, title) {
    runtimeDetailKey = bridgeId + '|' + mode;
    runtimeDetailTitle = title;
    if (!$('monitorRuntimeDetail').open) $('monitorRuntimeDetail').showModal();
    $('monitorRuntimeDetailNote').textContent = '正在读取分钟时序…';
    try {
      const query = runtimeRangeQuery(bridgeId, mode);
      const data = await api('/api/monitor/runtime?' + query, {signal: AbortSignal.timeout(15000)});
      if (runtimeDetailKey !== bridgeId + '|' + mode) return;
      renderRuntimeDetail(data, title);
    } catch (error) {
      if (runtimeDetailKey !== bridgeId + '|' + mode) return;
      $('monitorRuntimeDetailNote').textContent = '时序读取失败：' + error.message;
      $('monitorRuntimeCharts').innerHTML = '<div class="monitor-empty monitor-chart-empty">暂时无法读取时序数据。</div>';
      $('monitorRuntimeSamples').innerHTML = '<tr><td colspan="8" class="monitor-empty">暂时无法读取时序数据。</td></tr>';
    }
  }
  async function cleanupRuntime(scope) {
    const all = scope === 'all';
    const message = all ? '这会删除所有 QMT 运行时序，并尝试压缩 SQLite 文件。交易回报和异常记录不会删除。继续吗？' : '这会删除当前保留策略已经过期的 QMT 运行时序。交易回报和异常记录不会删除。继续吗？';
    if (!window.confirm(message)) return;
    try {
      const result = await api('/api/monitor/runtime/cleanup', {
        method: 'POST',
        body: JSON.stringify({scope}),
        signal: AbortSignal.timeout(20000),
      });
      $('monitorRuntimeDetailNote').textContent = '清理完成：删除 ' + n(result.deleted) + ' 个样本，剩余 ' + n(result.remaining) + ' 个。';
      if (all) {
        runtimeDetailData = {samples: []};
        renderRuntimeMetricCards([]);
        renderRuntimeCharts([]);
        $('monitorRuntimeSamples').innerHTML = '<tr><td colspan="8" class="monitor-empty">历史时序已清空。</td></tr>';
      } else if (runtimeDetailKey) {
        const [bridgeId, mode] = runtimeDetailKey.split('|');
        await openRuntimeDetail(bridgeId, mode, runtimeDetailTitle);
      }
    } catch (error) {
      $('monitorRuntimeDetailNote').textContent = '清理失败：' + error.message;
    }
  }
  $('monitorRuntimeRange').addEventListener('change', () => {
    if (!runtimeDetailKey) return;
    const [bridgeId, mode] = runtimeDetailKey.split('|');
    openRuntimeDetail(bridgeId, mode, runtimeDetailTitle);
  });
  $('monitorRuntimeReload').addEventListener('click', () => {
    if (!runtimeDetailKey) return;
    const [bridgeId, mode] = runtimeDetailKey.split('|');
    openRuntimeDetail(bridgeId, mode, runtimeDetailTitle);
  });
  $('monitorRuntimeCleanup').addEventListener('click', () => cleanupRuntime('expired'));
  $('monitorRuntimeClearAll').addEventListener('click', () => cleanupRuntime('all'));
  $('monitorRuntimeDetailClose').addEventListener('click', () => {
    if ($('monitorRuntimeDetail').open) $('monitorRuntimeDetail').close();
  });
  $('monitorRuntimeDetail').addEventListener('close', () => {
    runtimeDetailKey = '';
    runtimeDetailData = null;
  });
  function renderChart(data) {
    if (!data.series.length) {
      $('monitorChart').innerHTML = '<div class="monitor-empty monitor-chart-empty">暂无交易流速数据<br><small>委托、成交及撤成回报到达后将在这里显示。</small></div>';
      return;
    }
    const step = data.bucket_seconds, points = [];
    let start = data.series[0].time - step, end = data.series[data.series.length - 1].time + step;
    const buckets = new Map(data.series.map(row => [row.time, row]));
    for (let t = start; t <= end; t += step) points.push(buckets.get(t) || {time:t, orders:0, trades:0, cancels:0});
    const peak = Math.max(...points.flatMap(row => [row.orders, row.trades, row.cancels])) / step || 1;
    const x = t => 58 + (t - start) / (end - start || 1) * 820;
    const y = v => 177 - v / peak * 145;
    const paths = ['orders','trades','cancels'].map((key, index) => `<polyline class="monitor-line line-${index}" points="${points.map(row => `${x(row.time)},${y(row[key]/step)}`).join(' ')}"/>`).join('');
    $('monitorChart').innerHTML = `<svg viewBox="0 0 920 224" role="img" aria-label="委托、成交和撤成每秒平均流速，最高 ${n(peak,3)} 笔每秒"><title>交易流速；${n(step / 60)} 分钟聚合</title>${[0,.5,1].map(t => `<line class="monitor-gridline" x1="58" x2="878" y1="${y(peak*t)}" y2="${y(peak*t)}"/><text x="48" y="${y(peak*t)+4}" text-anchor="end">${n(peak*t,3)}</text>`).join('')}${paths}<text x="58" y="211">${e(stamp(start))}</text><text x="878" y="211" text-anchor="end">${e(stamp(end))}</text></svg>`;
  }
  async function refresh() {
    if (document.body.dataset.view !== 'monitor' || document.hidden) return;
    if (busy) { rerun = true; return; }
    applied ||= filters();
    if (followToday && applied.start !== today()) {
      form.elements.start.value = form.elements.end.value = today(); applied = filters(); page = 1;
    }
    const current = sequence;
    busy = true;
    root.setAttribute('aria-busy', 'true');
    try {
      const data = await api(`/api/monitor?${new URLSearchParams({...applied, kind:$('monitorKind').value, page})}`, {signal: AbortSignal.timeout(15000)});
      if (current !== sequence) return;
      $('monitorError').classList.add('hidden');
      render(data);
    } catch (error) {
      if (current !== sequence) return;
      $('monitorError').textContent = `监控读取失败：${error.message}${last ? '。下方保留上次结果。' : ''}`;
      $('monitorError').classList.remove('hidden');
      $('monitorFreshness').textContent = '刷新失败 · 数据未更新';
      if (!last) $('monitorHealth').textContent = '暂无可用监控数据，请重试。';
      try { const value = await api('/api/monitor/settings'); if (current === sequence) renderControl(value); } catch (_) { /* Keep the switch disabled until its actual state is known. */ }
    } finally {
      busy = false; root.setAttribute('aria-busy', 'false');
      if (rerun) { rerun = false; refresh(); }
    }
  }
  function schedule() {
    clearInterval(timer);
    if (document.body.dataset.view === 'monitor' && !document.hidden) {
      refresh();
      if ($('monitorAuto').checked) timer = setInterval(() => { if (applied?.end >= today()) refresh(); }, 5000);
    }
  }
  form.addEventListener('submit', event => {
    event.preventDefault(); applied = filters(); followToday = applied.start === today() && applied.end === today();
    page = 1; sequence++; refresh();
  });
  $('monitorToday').addEventListener('click', () => { form.elements.start.value = form.elements.end.value = today(); form.requestSubmit(); });
  $('monitorAuto').addEventListener('change', schedule);
  $('monitorKind').addEventListener('change', () => { page = 1; sequence++; refresh(); });
  $('monitorPrev').addEventListener('click', () => { page = Math.max(1, page - 1); sequence++; refresh(); });
  $('monitorNext').addEventListener('click', () => { page++; sequence++; refresh(); });
  new MutationObserver(schedule).observe(document.body, {attributes:true, attributeFilter:['data-view']});
  document.addEventListener('visibilitychange', schedule);

  // Notification policy is kept in its own dialog so collector settings remain
  // small and existing monitor workflows keep the same API contract.
  const notificationDialog = document.createElement('dialog');
  notificationDialog.id = 'monitorNotificationDialog';
  notificationDialog.className = 'monitor-dialog monitor-notification-dialog';
  notificationDialog.setAttribute('aria-labelledby', 'monitorNotificationTitle');
  notificationDialog.innerHTML = `<form id="monitorNotificationForm">
    <h2 id="monitorNotificationTitle">\u901a\u77e5\u8bbe\u7f6e</h2>
    <p>\u914d\u7f6e\u59d4\u6258\u3001\u6210\u4ea4\u3001QMT\u72b6\u6001\u548c\u7cfb\u7edf\u5f02\u5e38\u901a\u77e5\u3002\u53d1\u9001\u5728\u540e\u53f0\u961f\u5217\u6267\u884c\uff0c\u4e0d\u963b\u585e\u4ea4\u6613\u56de\u8c03\u3002</p>
    <label class="monitor-switch"><input id="monitorNotificationEnabled" type="checkbox" role="switch">\u542f\u7528\u76d1\u63a7\u901a\u77e5</label>
    <fieldset class="monitor-notification-fieldset"><legend>\u6d88\u606f\u7c7b\u578b</legend><div id="monitorNotificationEvents" class="monitor-notification-events"></div></fieldset>
    <fieldset class="monitor-notification-fieldset"><legend>\u90ae\u7bb1\uff08\u53ef\u9009\uff09</legend>
      <label class="monitor-notification-field"><span>SMTP \u4e3b\u673a</span><input id="monitorNotificationEmailHost" type="text" autocomplete="off"></label>
      <div class="monitor-notification-grid"><label class="monitor-notification-field"><span>\u7aef\u53e3</span><input id="monitorNotificationEmailPort" type="number" min="1" max="65535"></label><label class="monitor-notification-field"><span>\u53d1\u4ef6\u4eba</span><input id="monitorNotificationEmailFrom" type="email"></label></div>
      <div class="monitor-notification-grid"><label class="monitor-notification-field"><span>\u7528\u6237\u540d</span><input id="monitorNotificationEmailUser" type="text" autocomplete="username"></label><label class="monitor-notification-field"><span>\u5bc6\u7801</span><input id="monitorNotificationEmailPassword" type="password" autocomplete="new-password" placeholder="\u7559\u7a7a\u4fdd\u6301\u539f\u5bc6\u7801"></label></div>
      <label class="monitor-notification-field"><span>\u6536\u4ef6\u4eba\uff08\u9017\u53f7\u5206\u9694\uff09</span><input id="monitorNotificationEmailTo" type="text" placeholder="you@example.com"></label>
      <label class="monitor-notification-inline"><input id="monitorNotificationEmailEnabled" type="checkbox" >\u542f\u7528\u90ae\u7bb1 <input id="monitorNotificationEmailSSL" type="checkbox">SSL <input id="monitorNotificationEmailTLS" type="checkbox">STARTTLS</label>
    </fieldset>
    <fieldset class="monitor-notification-fieldset"><legend>Webhook\uff08\u9489\u9489 / \u4f01\u4e1a\u5fae\u4fe1 / \u98de\u4e66 / \u901a\u7528\uff09</legend><div id="monitorNotificationWebhooks"></div><button id="monitorNotificationAddWebhook" type="button">\u6dfb\u52a0 Webhook</button></fieldset>
    <fieldset class="monitor-notification-fieldset"><legend>\u5fc3\u8df3\u4e0e\u63a8\u9001\u65f6\u95f4</legend>
      <label class="monitor-notification-inline"><input id="monitorNotificationHeartbeat" type="checkbox">\u63a8\u9001\u7cfb\u7edf\u5fc3\u8df3\uff0c\u6bcf <input id="monitorNotificationHeartbeatInterval" type="number" min="10" max="86400" step="1"> \u79d2</label>
      <label class="monitor-notification-field"><span>\u76f8\u540c\u4e8b\u4ef6\u6291\u5236\u65f6\u95f4\uff08\u79d2\uff09</span><input id="monitorNotificationDedup" type="number" min="0" max="86400" step="1"></label>
      <label class="monitor-notification-field"><span>\u63a8\u9001\u65f6\u95f4\u7b56\u7565</span><select id="monitorNotificationScheduleMode"><option value="always">\u59cb\u7ec8\u5141\u8bb8</option><option value="trading_days">\u4ea4\u6613\u65e5</option><option value="trading_hours">\u4ea4\u6613\u65e5\u4ea4\u6613\u65f6\u95f4</option><option value="custom">\u81ea\u5b9a\u4e49\u661f\u671f\u548c\u65f6\u95f4\u6bb5</option></select></label>
      <div id="monitorNotificationCustomSchedule"><span class="monitor-notification-caption" >\u661f\u671f\uff080=\u5468\u4e00\uff09</span><div id="monitorNotificationWeekdays" class="monitor-notification-weekdays"></div><label class="monitor-notification-field"><span>\u65f6\u95f4\u6bb5\uff08\u6bcf\u884c HH:MM-HH:MM\uff09</span><textarea id="monitorNotificationWindows" rows="3" placeholder="09:00-11:30\n13:00-15:00"></textarea></label></div>
    </fieldset>
    <p id="monitorNotificationError" class="monitor-error-text" role="alert" hidden></p>
    <div class="monitor-dialog-actions"><button id="monitorNotificationClose" type="button">\u5173\u95ed</button><button id="monitorNotificationTest" type="button">\u53d1\u9001\u6d4b\u8bd5</button><button id="monitorNotificationSave" type="submit" class="primary">\u4fdd\u5b58</button></div>
  </form>`;
  document.body.append(notificationDialog);
  const notificationEvents = {
    order: '\u59d4\u6258\u56de\u62a5', trade: '\u6210\u4ea4\u56de\u62a5', order_error: '\u59d4\u6258\u5f02\u5e38', cancel_error: '\u64a4\u5355\u5f02\u5e38',
    qmt_reconnect: 'QMT \u91cd\u8fde', qmt_restart: 'QMT \u91cd\u542f', qmt_unresponsive: 'QMT \u65e0\u54cd\u5e94',
    system_error: '\u7cfb\u7edf\u5f02\u5e38', heartbeat: '\u7cfb\u7edf\u5fc3\u8df3',
  };
  $('monitorNotificationEvents').innerHTML = Object.entries(notificationEvents).map(([key, label]) => `<label><input type="checkbox" data-notification-event="${key}"> <span>${label}</span></label>`).join('');
  $('monitorNotificationWeekdays').innerHTML = ['\u5468\u4e00','\u5468\u4e8c','\u5468\u4e09','\u5468\u56db','\u5468\u4e94','\u5468\u516d','\u5468\u65e5'].map((label, index) => `<label><input type="checkbox" data-notification-weekday="${index}">${label}</label>`).join('');
  let notificationSaving = false, notificationValue = null;
  const notificationError = message => { $('monitorNotificationError').textContent = message || ''; $('monitorNotificationError').hidden = !message; };
  const notificationBusy = busyValue => {
    notificationSaving = busyValue;
    notificationDialog.querySelectorAll('button,input,select,textarea').forEach(node => { node.disabled = busyValue; });
    $('monitorNotificationClose').disabled = false;
    notificationDialog.setAttribute('aria-busy', String(busyValue));
  };
  const parseWindows = value => String(value || '').split(/[,\n]+/).map(item => item.trim()).filter(Boolean).map(item => {
    const parts = item.split('-').map(part => part.trim());
    return parts.length === 2 ? {start: parts[0], end: parts[1]} : null;
  }).filter(Boolean);
  const renderNotificationWebhooks = rows => {
    const list = Array.isArray(rows) ? rows : [];
    $('monitorNotificationWebhooks').innerHTML = list.map((row, index) => `<div class="monitor-notification-webhook" data-webhook-index="${index}" data-webhook-id="${e(row.id || `webhook-${index + 1}`)}">
      <div class="monitor-notification-grid"><label class="monitor-notification-field"><span>\u540d\u79f0</span><input data-webhook-name value="${e(row.name || `webhook-${index + 1}`)}"></label><label class="monitor-notification-field"><span>\u7c7b\u578b</span><select data-webhook-type><option value="generic">\u901a\u7528</option><option value="dingtalk">\u9489\u9489</option><option value="wecom">\u4f01\u4e1a\u5fae\u4fe1</option><option value="feishu">\u98de\u4e66</option></select></label></div>
      <label class="monitor-notification-field"><span>URL</span><input data-webhook-url type="url" value="" placeholder="${row.url_configured ? '\u5df2\u914d\u7f6e\uff0c\u7559\u7a7a\u4fdd\u6301\u539f URL' : 'https://...'}"></label>
      <label class="monitor-notification-field"><span>\u7b7e\u540d\u5bc6\u94a5\uff08\u53ef\u9009\uff09</span><input data-webhook-secret type="password" value="" placeholder="${row.secret_configured ? '\u5df2\u914d\u7f6e\uff0c\u7559\u7a7a\u4fdd\u6301\u539f\u5bc6\u94a5' : '\u53ef\u9009'}"></label>
      <label class="monitor-notification-inline"><input data-webhook-enabled type="checkbox">\u542f\u7528 <button data-webhook-remove type="button" >\u79fb\u9664</button></label>
    </div>`).join('');
    list.forEach((row, index) => {
      const root = $('monitorNotificationWebhooks').querySelector(`[data-webhook-index="${index}"]`);
      if (!root) return;
      root.querySelector('[data-webhook-type]').value = row.type || 'generic';
      root.querySelector('[data-webhook-enabled]').checked = row.enabled !== false;
      root.querySelector('[data-webhook-remove]').addEventListener('click', () => root.remove());
    });
  };
  const renderNotification = value => {
    notificationValue = value || {};
    $('monitorNotificationEnabled').checked = !!value.enabled;
    const selected = new Set(value.event_types || Object.keys(notificationEvents));
    notificationDialog.querySelectorAll('[data-notification-event]').forEach(node => { node.checked = selected.has(node.dataset.notificationEvent); });
    const email = value.email || {};
    $('monitorNotificationEmailEnabled').checked = !!email.enabled;
    $('monitorNotificationEmailHost').value = email.host || '';
    $('monitorNotificationEmailPort').value = email.port || 465;
    $('monitorNotificationEmailFrom').value = email.from || '';
    $('monitorNotificationEmailUser').value = email.username || '';
    $('monitorNotificationEmailPassword').value = '';
    $('monitorNotificationEmailPassword').placeholder = email.password_set ? '\u5df2\u914d\u7f6e\uff0c\u7559\u7a7a\u4fdd\u6301\u539f\u5bc6\u7801' : 'SMTP \u5bc6\u7801';
    $('monitorNotificationEmailTo').value = Array.isArray(email.to) ? email.to.join(', ') : (email.to || '');
    $('monitorNotificationEmailSSL').checked = email.use_ssl !== false;
    $('monitorNotificationEmailTLS').checked = !!email.use_tls;
    renderNotificationWebhooks(value.webhooks || []);
    const heartbeat = value.heartbeat || {};
    $('monitorNotificationHeartbeat').checked = !!heartbeat.enabled;
    $('monitorNotificationHeartbeatInterval').value = heartbeat.interval_seconds || 300;
    $('monitorNotificationDedup').value = value.dedup_seconds ?? 300;
    const schedule = value.schedule || {};
    $('monitorNotificationScheduleMode').value = schedule.mode || 'always';
    const weekdays = new Set(schedule.weekdays || [0,1,2,3,4]);
    notificationDialog.querySelectorAll('[data-notification-weekday]').forEach(node => { node.checked = weekdays.has(Number(node.dataset.notificationWeekday)); });
    $('monitorNotificationWindows').value = (schedule.windows || [{start:'09:00', end:'15:00'}]).map(row => `${row.start}-${row.end}`).join('\n');
    $('monitorNotificationCustomSchedule').hidden = schedule.mode === 'always' || schedule.mode === 'trading_days';
  };
  const notificationPayload = () => {
    const events = [...notificationDialog.querySelectorAll('[data-notification-event]:checked')].map(node => node.dataset.notificationEvent);
    const webhooks = [...$('monitorNotificationWebhooks').querySelectorAll('.monitor-notification-webhook')].map((row, index) => ({
      id: row.dataset.webhookId || `webhook-${index + 1}`,
      name: row.querySelector('[data-webhook-name]').value.trim(), type: row.querySelector('[data-webhook-type]').value,
      url: row.querySelector('[data-webhook-url]').value.trim(), secret: row.querySelector('[data-webhook-secret]').value,
      enabled: row.querySelector('[data-webhook-enabled]').checked,
    }));
    const emailTo = $('monitorNotificationEmailTo').value.split(/[,;]+/).map(item => item.trim()).filter(Boolean);
    const mode = $('monitorNotificationScheduleMode').value;
    return {
      enabled: $('monitorNotificationEnabled').checked, event_types: events,
      dedup_seconds: Number($('monitorNotificationDedup').value || 0),
      email: {enabled: $('monitorNotificationEmailEnabled').checked, host: $('monitorNotificationEmailHost').value.trim(), port: Number($('monitorNotificationEmailPort').value || 465), username: $('monitorNotificationEmailUser').value.trim(), password: $('monitorNotificationEmailPassword').value, from: $('monitorNotificationEmailFrom').value.trim(), to: emailTo, use_ssl: $('monitorNotificationEmailSSL').checked, use_tls: $('monitorNotificationEmailTLS').checked},
      webhooks,
      heartbeat: {enabled: $('monitorNotificationHeartbeat').checked, interval_seconds: Number($('monitorNotificationHeartbeatInterval').value || 300)},
      schedule: {mode, weekdays: [...notificationDialog.querySelectorAll('[data-notification-weekday]:checked')].map(node => Number(node.dataset.notificationWeekday)), windows: parseWindows($('monitorNotificationWindows').value)},
    };
  };
  const loadNotifications = async () => {
    const value = await api('/api/monitor/notifications', {signal: AbortSignal.timeout(15000)});
    renderNotification(value);
  };
  $('monitorNotificationScheduleMode').addEventListener('change', event => { $('monitorNotificationCustomSchedule').hidden = ['always','trading_days'].includes(event.target.value); });
  $('monitorNotificationAddWebhook').addEventListener('click', () => {
    const rows = [...$('monitorNotificationWebhooks').querySelectorAll('.monitor-notification-webhook')].map(row => ({id: row.dataset.webhookId, name: row.querySelector('[data-webhook-name]').value, type: row.querySelector('[data-webhook-type]').value, enabled: row.querySelector('[data-webhook-enabled]').checked}));
    rows.push({name: `webhook-${rows.length + 1}`, type: 'generic', enabled: true});
    renderNotificationWebhooks(rows);
  });
  $('monitorNotificationClose').addEventListener('click', () => { if (!notificationSaving) notificationDialog.close(); });
  notificationDialog.addEventListener('cancel', event => { event.preventDefault(); if (!notificationSaving) notificationDialog.close(); });
  $('monitorNotificationSettings').addEventListener('click', async () => {
    notificationError(''); notificationBusy(true); if (!notificationDialog.open) notificationDialog.showModal();
    try { await loadNotifications(); } catch (error) { notificationError(`\u8bfb\u53d6\u901a\u77e5\u914d\u7f6e\u5931\u8d25\uff1a${error.message}`); } finally { notificationBusy(false); }
  });
  $('monitorNotificationForm').addEventListener('submit', async event => {
    event.preventDefault(); if (notificationSaving) return; notificationError(''); notificationBusy(true);
    try { renderNotification(await api('/api/monitor/notifications', {method:'POST', body: JSON.stringify(notificationPayload()), signal: AbortSignal.timeout(20000)})); notificationDialog.close(); }
    catch (error) { notificationError(`\u901a\u77e5\u914d\u7f6e\u4fdd\u5b58\u5931\u8d25\uff1a${error.message}`); } finally { notificationBusy(false); }
  });
  $('monitorNotificationTest').addEventListener('click', async () => {
    if (notificationSaving) return; notificationError(''); notificationBusy(true);
    try { const result = await api('/api/monitor/notifications/test', {method:'POST', body:'{}', signal: AbortSignal.timeout(30000)}); notificationError(`\u6d4b\u8bd5\u5b8c\u6210\uff1a\u6210\u529f ${result.sent || 0}\uff0c\u5931\u8d25 ${result.failed || 0}${result.errors?.length ? `\uff1b${result.errors.join('\uff1b')}` : ''}`); }
    catch (error) { notificationError(`\u6d4b\u8bd5\u53d1\u9001\u5931\u8d25\uff1a${error.message}`); } finally { notificationBusy(false); }
  });
  schedule();
})();
