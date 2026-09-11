/* Shared inline HTTP testing for Python API reference entries. */
(() => {
  'use strict';
  const routes = {
    'xtdata.get_full_tick': ['full_tick'],
    'xtdata.get_market_data': ['market_data'],
    'xtdata.get_market_data_ex': ['market_data_ex'],
    'xtdata.get_instrument_detail': ['instrument_detail'],
    'xtdata.get_stock_list_in_sector': ['sector_stocks'],
    'xtdata.get_financial_data': ['financial_data'],
    'xtdata.download_history_data': ['history_download'],
    'xtdata.subscribe_quote': ['quote_subscribe_single'],
    'xtdata.subscribe_whole_quote': ['quote_subscribe_whole'],
    'xtdata.unsubscribe_quote': ['quote_unsubscribe'],
    'trader.order_stock': ['cftrader.order_stock'],
    'trader.order_stock_async': ['cftrader.order_stock_async'],
    'trader.cancel_order_stock': ['cancel'],
    'trader.query_stock_asset': ['asset'],
    'trader.query_stock_positions': ['positions'],
    'trader.query_stock_orders': ['orders'],
    'trader.query_stock_trades': ['trades'],
    'trader.query_credit_detail': ['credit_query', { credit_query_action: 'detail' }],
    'trader.query_stk_compacts': ['credit_query', { credit_query_action: 'compacts' }],
    'trader.query_credit_subjects': ['credit_query', { credit_query_action: 'subjects' }],
    'trader.query_credit_slo_code': ['credit_query', { credit_query_action: 'slo_code' }],
    'trader.query_credit_assure': ['credit_query', { credit_query_action: 'assure' }],
  };
  const records = new Map();
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  function endpointFor(entry) {
    if (!entry) return null;
    let route = routes[entry.id];
    if (entry.module === 'cftrader') route = [entry.id];
    if (entry.module === 'callback') route = ['callbacks', { event_name: `trader:${entry.name}` }];
    if (!route || !['supported', 'partial', 'extension'].includes(entry.status)) return null;
    const endpoint = API_ENDPOINTS.find(item => item.id === route[0]);
    return endpoint ? { ...endpoint, defaults: { ...endpoint.defaults, ...route[1] } } : null;
  }

  function button(entry) {
    if (endpointFor(entry)) return `<button type="button" class="primary" data-python-test aria-expanded="false">${entry.module === 'callback' ? '查看回调' : '在线测试'}</button>`;
    if (['trader', 'xtdata'].includes(entry.module)) return '<button type="button" disabled title="此接口尚未提供网页测试入口">仅 Python 调用</button>';
    return '';
  }

  function resultSummary(payload, elapsed, httpStatus) {
    const data = payload?.data;
    const result = data?.result;
    const metrics = [['页面往返', formatLatencyMs(elapsed)]];
    if (httpStatus) metrics.unshift(['HTTP', httpStatus]);
    if (data?.latency_ms != null) metrics.push(['服务端', formatLatencyMs(data.latency_ms)]);
    if (result?.qmt_submit_ms != null) metrics.push(['QMT 内部提交', formatLatencyMs(result.qmt_submit_ms)]);
    if (Array.isArray(result?.results)) {
      for (const [key, label] of [['total', '总笔数'], ['submitted', '已提交'], ['failed', '失败'], ['unknown', '待确认'], ['skipped', '未提交']]) metrics.push([label, result[key] ?? 0]);
    }
    let html = `<dl class="api-test-metrics">${metrics.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>`;
    if (Array.isArray(result?.results)) {
      const labels = { submitted: '已提交', failed: '失败', unknown: '待确认', skipped: '未提交' };
      const operation = result.operation === 'cancel' ? '撤单' : '委托';
      html += `<div class="api-test-orders" role="region" aria-label="逐笔${operation}结果" tabindex="0"><table><thead><tr><th>序号</th><th>证券 / 市场</th><th>状态</th><th>order_id</th><th>seq</th><th>结果 / 备注 / 错误</th></tr></thead><tbody>${result.results.map(row => `<tr><td>${escape(Number(row.index) + 1)}</td><td>${escape(row.stock_code || row.market || '--')}</td><td>${escape(labels[row.status] || row.status)}</td><td>${escape(row.order_id ?? '--')}</td><td>${escape(row.seq ?? '--')}</td><td>${escape(row.error || row.order_remark || (row.cancel_result ?? ''))}</td></tr>`).join('')}</tbody></table></div>`;
    }
    return html;
  }

  function outcome(payload, httpStatus) {
    if (!httpStatus) return '结果待确认';
    if (httpStatus >= 400 || payload?.ok === false) return '请求失败';
    if (payload?.data?.result?.unknown) return '存在待确认委托';
    if (payload?.data?.result?.ok === false) return '部分或全部委托未提交';
    if (payload?.data?.result?.accepted === false || payload?.data?.result?.order_id === -1) return '委托未确认';
    return '请求完成';
  }

  async function copyText(text, button) {
    const label = button.textContent;
    try { await navigator.clipboard.writeText(text); button.textContent = '已复制'; }
    catch { button.textContent = '复制失败'; }
    setTimeout(() => { button.textContent = label; }, 1500);
  }

  function mount(host, entry) {
    const endpoint = endpointFor(entry);
    if (!endpoint) return;
    host.hidden = false;
    if (host.dataset.mounted) return;
    host.dataset.mounted = entry.id;
    const record = records.get(entry.id) || { busy: false, listeners: new Set() };
    records.set(entry.id, record);
    const sdkSubmitLabel = entry.name && entry.name.startsWith('cancel_order_stock_batch') ? '测试撤单' : '测试下单';
    host.innerHTML = `<div class="api-test-heading"><h3 tabindex="-1">${entry.module === 'callback' ? '回调记录' : '在线测试'}</h3><code>${escape(endpoint.method)} ${escape(endpoint.path)}</code></div>
      <form class="api-form api-inline-form"><fieldset class="api-test-fields"></fieldset><div class="api-test-actions"><button class="primary" type="submit">${endpoint.sdkEntry ? sdkSubmitLabel : '发送请求'}</button><button type="button" data-test-reset>重置参数</button><button type="button" data-test-stop disabled>停止等待</button></div></form>
      <details class="api-test-request"><summary>请求预览</summary><pre class="json-box" data-test-request></pre></details>
      <div class="api-test-result-heading"><strong data-test-status role="status" tabindex="-1">尚未测试</strong><span data-test-time></span><button type="button" data-test-copy disabled>复制结果</button><button type="button" data-test-clear disabled>清空结果</button></div>
      <div data-test-metrics></div><pre class="json-box api-test-output" data-test-output tabindex="0"></pre>`;
    const form = host.querySelector('form');
    const fields = host.querySelector('fieldset');
    fields.innerHTML = endpoint.fields.map(apiFieldHtml).join('');
    const bound = accountConfigEntries().filter(row => row.enabled);
    if (form.elements.account_id && bound.length) {
      const label = document.createElement('label');
      label.className = 'field wide';
      label.innerHTML = `<span>已绑定账号</span><select data-test-binding><option value="">手动填写</option>${bound.map(row => `<option value="${escape(row.accountKey)}">${escape(row.displayName || row.accountId)} · ${escape(row.accountType)} · ${escape(row.bridgeId)}</option>`).join('')}</select>`;
      fields.prepend(label);
      const key = document.createElement('input');
      key.type = 'hidden'; key.name = 'account_key'; fields.append(key);
      label.querySelector('select').addEventListener('change', event => {
        const row = bound.find(item => item.accountKey === event.target.value);
        key.value = row?.accountKey || '';
        if (row) { form.elements.account_id.value = row.accountId; form.elements.account_type.value = row.accountType; }
        preview();
      });
      for (const name of ['account_id', 'account_type']) form.elements[name].addEventListener('input', () => {
        key.value = ''; label.querySelector('select').value = '';
      });
    }
    setApiDefaults(endpoint, form);
    if (entry.id.startsWith('trader.query_credit') || entry.id === 'trader.query_stk_compacts') {
      if (form.elements.action) form.elements.action.disabled = true;
    }
    const output = host.querySelector('[data-test-output]');
    function preview() {
      const request = currentApiRequest(endpoint, form);
      host.querySelector('[data-test-request]').textContent = JSON.stringify(request, null, 2);
      updateSdkConfirmation(endpoint, form, request);
    }
    function render() {
      const hadFocus = host.contains(document.activeElement);
      fields.disabled = record.busy;
      form.querySelector('[type="submit"]').disabled = record.busy;
      host.querySelector('[data-test-reset]').disabled = record.busy;
      host.querySelector('[data-test-stop]').disabled = !record.busy;
      host.querySelector('[data-test-copy]').disabled = !record.output;
      host.querySelector('[data-test-clear]').disabled = record.busy || !record.output;
      host.querySelector('[data-test-status]').textContent = record.busy ? '请求中…' : record.status || '尚未测试';
      host.querySelector('[data-test-time]').textContent = record.at || '';
      host.querySelector('[data-test-metrics]').innerHTML = record.metrics || '';
      output.textContent = record.output || '';
      if (hadFocus && !host.contains(document.activeElement)) host.querySelector('[data-test-status]').focus({ preventScroll: true });
    }
    record.listeners.add({ host, render });
    function notify() {
      for (const listener of record.listeners) {
        if (listener.host.isConnected) listener.render();
        else record.listeners.delete(listener);
      }
    }
    form.addEventListener('input', preview);
    form.addEventListener('change', preview);
    host.querySelector('[data-test-reset]').addEventListener('click', () => { form.reset(); setApiDefaults(endpoint, form); preview(); });
    host.querySelector('[data-test-copy]').addEventListener('click', event => copyText(record.output, event.currentTarget));
    host.querySelector('[data-test-clear]').addEventListener('click', () => { Object.assign(record, { output: '', metrics: '', at: '', status: '' }); notify(); });
    host.querySelector('[data-test-stop]').addEventListener('click', () => record.controller?.abort());
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (record.busy) return;
      const request = currentApiRequest(endpoint, form);
      const error = apiTestValidation(endpoint, request);
      if (error) {
        Object.assign(record, { output: JSON.stringify({ ok: false, error }, null, 2), status: '参数有误', metrics: '', at: '' });
        notify(); return;
      }
      const controller = new AbortController();
      Object.assign(record, { busy: true, controller, metrics: '', output: '', at: new Date().toLocaleString() });
      notify();
      const started = performance.now();
      const timer = setTimeout(() => controller.abort(), apiDebugTimeoutMs(request));
      try {
        const response = await fetch(request.url, { method: request.method,
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: request.body ? JSON.stringify(request.body) : undefined, signal: controller.signal });
        const text = await response.text();
        let payload;
        try { payload = JSON.parse(text); } catch { payload = { ok: false, error: text }; }
        record.output = apiDebugOutput(payload, request, started, { http_status: response.status });
        record.metrics = resultSummary(payload, performance.now() - started, response.status);
        record.status = outcome(payload, response.status);
      } catch (error) {
        const uncertain = endpoint.sdkEntry || ['order', 'cancel', 'batch_order'].includes(endpoint.id);
        const message = error.name === 'AbortError' ? '已停止等待，服务端或 QMT 可能仍在处理。' : error.message;
        record.output = apiDebugOutput({ ok: false, error: message + (uncertain ? ' 请先核对委托与回调，避免重复提交。' : '') }, request, started);
        record.status = uncertain ? '结果待确认' : '请求未完成';
        record.metrics = resultSummary(null, performance.now() - started);
      } finally { clearTimeout(timer); record.busy = false; record.controller = null; notify(); }
    });
    preview(); render();
  }

  document.addEventListener('click', event => {
    if (event.target.closest('#apiCopyResultBtn')) copyText(document.getElementById('apiResponseBox').textContent, event.target.closest('button'));
    if (event.target.closest('#apiClearResultBtn') && !state.apiDebugBusy) {
      document.getElementById('apiResponseBox').textContent = '';
      document.getElementById('apiResultSummary').innerHTML = '';
      renderApiResponseLatency(null, apiEndpointById(state.apiEndpointId));
    }
  });
  window.CfquantApiTester = { button, mount, endpointFor, resultSummary };
})();
