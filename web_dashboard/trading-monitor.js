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
  let saving = false, collector = {enabled:false}, entryAttempt = 0, enterView = null, settingsMode = false;
  root.innerHTML = `
    <div class="monitor-heading"><div><span class="monitor-kicker">运行观测 / 交易风控</span><h2>交易监控</h2><p>集中查看各 QMT 通道、交易回报与执行质量。</p></div><div class="monitor-heading-actions"><span id="monitorFreshness" role="status">等待采集</span><button id="monitorSettings" type="button">监控设置</button></div></div>
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
    <div id="monitorStats" class="monitor-stats" aria-label="交易汇总"></div>
    <div class="monitor-detail-grid">
      <section class="panel monitor-trend"><div class="panel-head"><h3>交易流速</h3><span id="monitorBucket" class="metric-note"></span></div><div class="monitor-legend"><span>委托</span><span>成交</span><span>撤成</span></div><div id="monitorChart"></div><p class="monitor-note">按首次采集时间聚合；重连补发可能形成峰值。图中速率为每个时间桶的笔数 ÷ 桶宽。</p></section>
      <section class="panel"><div class="panel-head"><h3>交易请求延迟</h3><span class="metric-note">Web → QMT → Web</span></div><dl id="monitorLatency" class="monitor-latency"></dl><p class="monitor-note">统计经过 Web 统一路由的报单、撤单请求。包含排队与失败请求，不代表交易所确认耗时。</p></section>
    </div>
    <section class="panel"><div class="panel-head"><h3>QMT 通道在线情况</h3><span id="monitorNodeSummary" class="metric-note"></span></div><p id="monitorNodeNote" class="monitor-note"></p><div class="monitor-table-wrap"><table><thead><tr><th>部署</th><th>模式</th><th>通道</th><th>连接状态</th><th>探测往返</th><th>采样时间</th><th>说明</th></tr></thead><tbody id="monitorNodes"></tbody></table></div></section>
    <section class="panel"><div class="panel-head"><h3>交易与异常记录</h3><label class="monitor-kind">事件类型 <select id="monitorKind" aria-label="监控事件类型"><option value="">全部事件</option><option value="order">委托回报</option><option value="trade">成交</option><option value="abnormal">异常记录</option><option value="order_request">报单请求</option><option value="cancel_request">撤单请求</option></select></label></div><div class="monitor-table-wrap"><table><thead><tr><th>采集时间</th><th>业务日期</th><th>部署 / 账号</th><th>类型</th><th>证券 / 委托号</th><th>状态 / 成交量</th><th>说明</th></tr></thead><tbody id="monitorEvents"></tbody></table></div><div class="monitor-pagination"><span id="monitorPageText"></span><button id="monitorPrev" type="button">上一页</button><button id="monitorNext" type="button">下一页</button></div></section>
    <details class="monitor-definitions"><summary>指标口径与采集范围</summary><p>委托笔数按业务日期、部署、账号类型、账号、证券和委托号去重；成交笔数按成交编号去重。缺少编号时可能无法可靠去重，缺少日期时使用北京时间采集日期。</p><p>成交率 = 至少部分成交的委托笔数 ÷ 委托笔数。撤单率 = 实际撤成（含部撤）委托数 ÷ 委托笔数；报撤比 = 委托笔数 ÷ 撤成笔数。分母为零显示 —。撤单请求按 RPC 请求次数统计，批量调用计一次。</p><p>异常记录包含废单回报、委托/撤单错误及请求失败，同一业务单可能有多条异常记录。这里提供观测与留痕，不增加自动拦单规则。</p><p>开启监控后，服务运行期间持续采集，不依赖页面打开；「自动刷新」仅控制页面更新。仅包含本服务收到的回调和探测；关闭监控或停机期间不会自动补齐，历史查询单次最多 31 天。当前采集不等同于券商全量对账。</p><p id="monitorStorage"></p></details>`;
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
  function renderControl(value) {
    collector = value;
    $('monitorControlStatus').textContent = value.draining ? '已停止新增采集，正在保存队列记录…' : value.enabled ? '监控已开启' : '监控已关闭 · 历史记录保留';
    $('monitorScopeSummary').textContent = value.account_keys == null ? '采集范围：全部已绑定账号' : `采集范围：指定 ${value.account_keys.length} 个账号`;
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
  schedule();
})();
