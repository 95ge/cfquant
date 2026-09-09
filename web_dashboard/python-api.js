/* Offline Python reference; no setup, authentication or live trading requests. */
(() => {
  'use strict';
  const data = window.CFQUANT_PYTHON_API;
  if (!data) return;
  const entries = [...data.entries, ...data.references];
  const byId = new Map(entries.map(entry => [entry.id, entry]));
  const modules = { xtdata: 'XtData 行情', trader: 'XtQuantTrader 交易', callback: 'XtQuantTraderCallback', type: '交易数据结构', reference: '概述与附录' };
  const labels = { supported: '已适配', partial: '部分适配', unverified: '尚未支持 · 条件待验证', unsupported: '尚未支持', reference: '参考资料' };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const inline = value => esc(value).replace(/`([^`]+)`/g, '<code>$1</code>');
  let root, nav, doc, legacy, article, current = 'guide', query = '', filter = '', codeIndex = 0;
  const codeValues = new Map();
  const codeBlock = (value, title) => {
    const id = String(++codeIndex);
    codeValues.set(id, value);
    return `<div class="python-code"><div class="python-code-head"><span>${esc(title)}</span><button type="button" data-python-copy="${id}" aria-label="复制${esc(title)}">复制</button></div><pre class="guide-code" data-language="python" tabindex="0"><code>${esc(value)}</code></pre></div>`;
  };
  const badge = entry => `<span class="python-status ${entry.status}">${labels[entry.status]}</span>`;

  function sourceBlock(entry) {
    return `<details class="python-original"><summary>讯投在线原文</summary><p><a href="${esc(entry.source)}" target="_blank" rel="noopener noreferrer">在讯投文档中打开本节</a></p><div data-python-original="${esc(entry.source)}" data-original-name="${esc(entry.name)}"></div></details>`;
  }

  function table(headers, rows) {
    return `<div class="guide-table-wrap"><table><thead><tr>${headers.map(h => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${inline(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }

  function renderDocument(entry) {
    codeValues.clear();
    codeIndex = 0;
    const api = entry.module !== 'reference';
    const supported = ['supported', 'partial'].includes(entry.status);
    let reference = `<p>${inline(entry.description)}</p>`;
    if (entry.signature) reference += codeBlock(entry.signature, '原版接口签名');
    if (entry.parameters?.length) reference += '<h4>原版参数</h4>' + table(['参数', '默认值', '含义'], entry.parameters.map(p => ['`' + p.name + '`', '`' + p.default + '`', p.help]));
    if (entry.fields?.length) reference += '<h4>原版字段 / 类型</h4>' + table(['字段', '类型 / 含义'], entry.fields.map(row => ['`' + row[0] + '`', row[1]]));
    if (entry.originalReturns) reference += `<h4>原版返回</h4><p>${inline(entry.originalReturns)}</p>`;
    if (api && !entry.signature && entry.module !== 'type') reference += '<p class="python-muted">官方在版本说明或示例中提及此名称，未提供独立的完整签名。下方 cfquant 签名来自当前 SDK。</p>';
    if (entry.originalExample) reference += `<details class="python-old-example"><summary>原来：xtquant 调用示例</summary>${codeBlock(entry.originalExample, 'xtquant 示例')}</details>`;
    reference += sourceBlock(entry);
    let solution = `<div class="python-section-title"><h3>cfquant 解决方案</h3>${badge(entry)}</div>`;
    if (entry.note) solution += `<p class="python-compat-note ${entry.status}">${inline(entry.note)}</p>`;
    if (entry.sdkSignature) solution += codeBlock(entry.sdkSignature, '当前 cfquant 签名');
    if (entry.resultHelp) solution += `<h4>返回值与处理</h4><p>${inline(entry.resultHelp)}</p>`;
    solution += `<p>${inline(entry.usage)}</p>`;
    if (entry.example) solution += codeBlock(entry.example, '现在：cfquant 示例');
    if (api && !supported) solution += '<p class="python-unavailable">尚未支持</p>';
    if (entry.related?.length) solution += `<div class="python-related">${entry.related.map(id => `<button type="button" data-python-entry="${esc(id)}">${esc(byId.get(id)?.name || id)}</button>`).join('')}</div>`;
    const index = entries.indexOf(entry);
    doc.innerHTML = `<header class="python-document-head"><div class="python-breadcrumb">${esc(modules[entry.module])} / ${esc(entry.group)}</div><h2 tabindex="-1">${esc(entry.name)}</h2>${entry.title ? `<p>${esc(entry.title)}</p>` : ''}<div class="python-document-meta">${badge(entry)}<a href="${esc(entry.source)}" target="_blank" rel="noopener noreferrer">讯投来源</a><button type="button" data-python-link>复制链接</button></div></header><section class="python-reference-section"><h3>讯投 API 参考</h3>${reference}</section><section class="python-reference-section python-solution">${solution}</section><footer class="python-document-footer">${index > 0 ? `<button type="button" data-python-entry="${esc(entries[index - 1].id)}">上一节：${esc(entries[index - 1].name)}</button>` : '<span></span>'}${index < entries.length - 1 ? `<button type="button" data-python-entry="${esc(entries[index + 1].id)}">下一节：${esc(entries[index + 1].name)}</button>` : ''}</footer>`;
    doc.querySelectorAll('.python-original').forEach(details => details.addEventListener('toggle', () => {
      const holder = details.querySelector('[data-python-original]');
      if (!details.open || holder.firstChild) return;
      const frame = document.createElement('iframe');
      frame.src = holder.dataset.pythonOriginal;
      frame.title = '讯投原文：' + holder.dataset.originalName;
      frame.referrerPolicy = 'no-referrer';
      frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-popups');
      holder.append(frame);
    }));
  }

  function matches(entry) {
    const statusMatch = !filter || (filter === 'unavailable' ? ['unverified', 'unsupported'].includes(entry.status) : entry.status === filter);
    const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const haystack = [entry.name, entry.title, entry.description, entry.note, entry.group, modules[entry.module]].join(' ').toLowerCase();
    return statusMatch && words.every(word => haystack.includes(word));
  }

  function renderNav() {
    const visible = entries.filter(matches);
    const groups = new Map();
    for (const entry of visible) {
      const key = modules[entry.module] + ' / ' + entry.group;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(entry);
    }
    nav.innerHTML = `<button type="button" class="python-nav-entry ${current === 'guide' ? 'active' : ''}" data-python-entry="guide" ${current === 'guide' ? 'aria-current="page"' : ''}><strong>接入与迁移</strong><span>安装、查询、交易及多账号示例</span></button><p class="python-nav-count" role="status">${visible.length} 个条目</p>` + (visible.length ? [...groups].map(([name, list]) => `<details class="python-nav-group" open><summary>${esc(name)} <span>${list.length}</span></summary>${list.map(entry => `<button type="button" class="python-nav-entry ${current === entry.id ? 'active' : ''}" data-python-entry="${esc(entry.id)}" ${current === entry.id ? 'aria-current="page"' : ''}><strong><i class="python-status-dot ${entry.status}" aria-label="${labels[entry.status]}"></i>${esc(entry.name)}</strong><span>${esc(entry.title || entry.description)}</span></button>`).join('')}</details>`).join('') : '<p class="python-empty">没有匹配的接口</p><button type="button" data-python-reset>清除筛选</button>');
  }

  function select(id, { focus = true, history = true } = {}) {
    if (id !== 'guide' && !byId.has(id)) id = 'guide';
    current = id;
    legacy.hidden = id !== 'guide';
    doc.hidden = id === 'guide';
    if (id !== 'guide') renderDocument(byId.get(id));
    renderNav();
    root.classList.remove('python-nav-open');
    root.querySelector('[data-python-menu]').setAttribute('aria-expanded', 'false');
    const scroller = root.querySelector('.python-reading-pane');
    scroller.scrollTop = 0;
    if (focus) {
      const heading = (id === 'guide' ? legacy : doc).querySelector('h2, h3');
      heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    }
    if (history) {
      const url = new URL(location.href);
      url.hash = 'python-api=' + encodeURIComponent(id);
      window.history.pushState(null, '', url);
    }
  }

  async function copy(text, button) {
    const label = button.textContent;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else throw new Error('Clipboard fallback');
    } catch {
      const input = document.createElement('textarea');
      input.value = text;
      input.className = 'python-clipboard-fallback';
      root.append(input);
      input.select();
      const ok = document.execCommand('copy');
      input.remove();
      button.focus({ preventScroll: true });
      if (!ok) {
        button.textContent = '复制失败';
        setTimeout(() => { button.textContent = label; }, 1800);
        return;
      }
    }
    button.textContent = '已复制';
    setTimeout(() => { button.textContent = label; }, 1800);
  }

  function idFromHash() {
    if (!location.hash.startsWith('#python-api=')) return null;
    try { return decodeURIComponent(location.hash.slice(12)); } catch { return 'guide'; }
  }

  function mount() {
    if (root) return;
    article = document.querySelector('[data-guide-panel="python"]');
    if (!article) return;
    legacy = document.createElement('div');
    legacy.className = 'python-legacy';
    while (article.firstChild) legacy.append(article.firstChild);
    const counts = data.entries.reduce((result, entry) => { result[entry.status] = (result[entry.status] || 0) + 1; return result; }, {});
    root = document.createElement('div');
    root.className = 'python-reference';
    root.innerHTML = `<header class="python-reference-head"><button type="button" data-python-back>返回教程</button><h2>Python 接入</h2><span class="python-reference-version">适配清单 ${esc(data.updated)}</span><button type="button" data-python-menu aria-expanded="false" aria-controls="pythonReferenceSidebar">API 目录</button></header><div class="python-reference-body"><aside id="pythonReferenceSidebar" class="python-reference-sidebar"><div class="python-search"><label for="pythonApiSearch">API 文档</label><input id="pythonApiSearch" type="search" placeholder="搜索接口或中文功能" autocomplete="off"><label class="python-filter-label" for="pythonApiFilter">适配状态</label><select id="pythonApiFilter"><option value="">全部状态</option><option value="supported">已适配 (${counts.supported || 0})</option><option value="partial">部分适配 (${counts.partial || 0})</option><option value="unavailable">尚未支持 (${(counts.unverified || 0) + (counts.unsupported || 0)})</option><option value="reference">概述与附录</option></select></div><nav class="python-api-nav" aria-label="Python API 目录"></nav></aside><div class="python-reading-pane"><div class="python-reference-scope">${data.entries.length} 个接口、回调与数据结构。${counts.supported || 0} 已适配，${counts.partial || 0} 部分适配，${(counts.unverified || 0) + (counts.unsupported || 0)} 尚未支持。当前清单覆盖高级 / 通用模式共用桥，独立内嵌旧桥另行核对。</div><div class="python-api-document"></div></div></div>`;
    article.append(root);
    nav = root.querySelector('.python-api-nav');
    doc = root.querySelector('.python-api-document');
    doc.before(legacy);
    root.querySelector('#pythonApiSearch').addEventListener('input', event => { query = event.target.value; renderNav(); });
    root.querySelector('#pythonApiFilter').addEventListener('change', event => { filter = event.target.value; renderNav(); });
    root.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.hasAttribute('data-python-entry')) select(button.dataset.pythonEntry);
      else if (button.hasAttribute('data-python-copy')) copy(codeValues.get(button.dataset.pythonCopy), button);
      else if (button.hasAttribute('data-python-link')) copy(location.href, button);
      else if (button.hasAttribute('data-python-back')) {
        setTutorialTopic('deploy');
        document.querySelector('.tutorial-menu-item[data-guide="python"]')?.focus({ preventScroll: true });
      } else if (button.hasAttribute('data-python-menu')) {
        const open = root.classList.toggle('python-nav-open');
        button.setAttribute('aria-expanded', String(open));
        if (open) root.querySelector('#pythonApiSearch').focus();
      } else if (button.hasAttribute('data-python-reset')) {
        query = filter = '';
        root.querySelector('#pythonApiSearch').value = '';
        root.querySelector('#pythonApiFilter').value = '';
        renderNav();
      }
    });
    select(idFromHash() || 'guide', { focus: false, history: false });
  }

  window.addEventListener('hashchange', () => {
    const id = idFromHash();
    if (id === null) return;
    setTutorialTopic('python');
    mount();
    select(id, { history: false });
  });
  window.CfquantPythonReference = { mount, idFromHash };
})();
