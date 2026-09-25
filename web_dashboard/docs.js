/* cfquant documentation and data-interface test bench. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inline = value => esc(value).replace(/`([^`]+)`/g, '<code>$1</code>');
  const entries = () => (window.CFQUANT_PYTHON_API?.entries || []).filter(item => item.module === 'xtdata');
  let host;

  function table(headers, rows) {
    return `<div class="guide-table-wrap"><table><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${inline(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }

  function render(entry) {
    const params = entry.parameters || [];
    const fields = entry.fields || [];
    const test = window.CfquantApiTester?.button(entry) || '';
    host.querySelector('.docs-article').innerHTML = `<header class="docs-article-head"><div><span class="docs-kicker">cfquant / xtdata</span><h2>${esc(entry.name)}</h2><p>${inline(entry.description || entry.title)}</p></div><div class="docs-actions">${test}<a href="${esc(entry.source || '#')}" target="_blank" rel="noopener">原版文档</a></div></header><div class="docs-signature"><code>${esc(entry.sdkSignature || entry.signature || entry.name)}</code></div>${params.length ? `<h3>参数</h3>${table(['参数', '默认值', '说明'], params.map(p => ['`' + p.name + '`', '`' + p.default + '`', p.help]))}` : ''}${fields.length ? `<h3>返回字段</h3>${table(['字段', '类型 / 含义'], fields.map(row => ['`' + row[0] + '`', row[1]]))}` : ''}<section class="docs-compat"><span class="python-status ${esc(entry.status)}">${esc({ supported: '已适配', partial: '部分适配', unsupported: '尚未支持', unverified: '待验证' }[entry.status] || entry.status)}</span><p>${inline(entry.note || entry.resultHelp || '由 cfquant 桥接大 QMT 提供。')}</p>${entry.resultHelp && entry.note ? `<p>${inline(entry.resultHelp)}</p>` : ''}</section>${entry.example ? `<h3>cfquant 调用示例</h3><pre class="guide-code" data-language="python">${esc(entry.example)}</pre>` : ''}<div class="docs-test-host" hidden></div>`;
    const button = host.querySelector('[data-python-test]');
    const testHost = host.querySelector('.docs-test-host');
    button?.addEventListener('click', () => {
      const open = testHost.hidden;
      if (open) window.CfquantApiTester.mount(testHost, entry);
      testHost.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
    });
  }

  function mount() {
    host = document.querySelector('#cfquantDocs');
    if (!host) return;
    const list = entries();
    host.innerHTML = `<header class="docs-head"><div><span class="docs-kicker">CFQUANT DATA REFERENCE</span><h2>行情 / 数据接口文档</h2><p>按 xtquant 的接口结构整理 cfquant 适配结果。选择接口后可直接在当前页面发起测试，便于定位参数、通道和返回值问题。</p></div><div class="docs-head-meta"><strong>${list.length}</strong><span>个数据接口</span></div></header><div class="docs-layout"><aside class="docs-sidebar"><label for="docsSearch">搜索接口</label><input id="docsSearch" type="search" placeholder="名称或中文功能"><nav aria-label="行情数据接口"></nav></aside><article class="docs-article"><p class="docs-empty">请选择左侧接口</p></article></div>`;
    const nav = host.querySelector('nav');
    const drawNav = () => {
      const query = host.querySelector('#docsSearch').value.trim().toLowerCase();
      const visible = list.filter(item => [item.name, item.title, item.description, item.group].join(' ').toLowerCase().includes(query));
      nav.innerHTML = visible.map((item, index) => `<button type="button" class="docs-nav-item${index === 0 ? ' active' : ''}" data-doc-id="${esc(item.id)}"><span>${esc(item.name)}</span><small>${esc(item.title || item.description || '')}</small></button>`).join('') || '<p class="docs-empty">没有匹配接口</p>';
      nav.querySelectorAll('[data-doc-id]').forEach(button => button.addEventListener('click', () => {
        nav.querySelectorAll('.docs-nav-item').forEach(node => node.classList.toggle('active', node === button));
        render(list.find(item => item.id === button.dataset.docId));
      }));
      if (visible[0]) render(visible[0]);
    };
    host.querySelector('#docsSearch').addEventListener('input', drawNav);
    drawNav();
  }
  document.addEventListener('DOMContentLoaded', mount);
})();
