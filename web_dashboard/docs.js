/* cfquant API documentation, examples and data-interface test bench. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inline = value => esc(value).replace(/`([^`]+)`/g, '<code>$1</code>');
  const entries = () => [
    ...(window.CFQUANT_CFTRADER_API || []).filter(item => item.operation === 'algorithm'),
    ...(window.CFQUANT_PYTHON_API?.entries || []).filter(item => item.module === 'xtdata'),
  ];
  let host;

  function table(headers, rows) {
    return `<div class="guide-table-wrap"><table><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${inline(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }

  function render(entry) {
    const algorithm = entry.operation === 'algorithm';
    const params = entry.parameters || [];
    const fields = entry.resultRows || entry.fields || [];
    const test = window.CfquantApiTester?.button(entry) || '';
    const httpExample = entry.http ? `${entry.http.method} ${entry.http.path}\nContent-Type: application/json\nX-API-Key: YOUR_API_KEY\n\n${JSON.stringify(entry.http.body, null, 2)}` : '';
    host.querySelector('.docs-article').innerHTML = `
      <header class="docs-article-head"><div><span class="docs-kicker">cfquant / ${algorithm ? '算法交易' : 'xtdata'}</span><h2>${esc(entry.name)}</h2><p>${inline(entry.title || entry.description)}</p></div>
        <div class="docs-actions">${test}${algorithm ? '<button type="button" data-doc-algorithm-guide>算法交易完整教程</button>' : `<a href="${esc(entry.source || '#')}" target="_blank" rel="noopener">原版文档</a>`}</div></header>
      <div class="docs-signature"><code>${esc(entry.sdkSignature || entry.signature || entry.name)}</code></div>
      ${algorithm ? `<p>${inline(entry.description)}</p><p>${inline(entry.usage)}</p>` : ''}
      ${params.length ? `<h3>参数</h3>${table(['参数', '默认值', '说明'], params.map(p => ['`' + p.name + '`', '`' + p.default + '`', p.help]))}` : ''}
      ${fields.length ? `<h3>返回字段</h3>${table(['字段', '类型 / 含义'], fields.map(row => ['`' + row[0] + '`', row[1]]))}` : ''}
      <section class="docs-compat"><span class="python-status ${esc(entry.status)}">${esc({ extension: 'cfquant 扩展', supported: '已适配', partial: '部分适配', unsupported: '尚未支持', unverified: '待验证' }[entry.status] || entry.status)}</span><p>${inline(entry.note || entry.resultHelp || '由 cfquant 桥接大 QMT 提供。')}</p>${entry.resultHelp && entry.note ? `<p>${inline(entry.resultHelp)}</p>` : ''}</section>
      ${entry.example ? `<h3>Python 调用示例</h3><button type="button" data-doc-copy="python">复制 Python 示例</button><pre class="guide-code" data-language="python" tabindex="0">${esc(entry.example)}</pre>` : ''}
      ${httpExample ? `<h3>HTTP 请求示例</h3><p>默认服务地址为 http://127.0.0.1:8765。请替换账号、API Key 与任务参数。</p><button type="button" data-doc-copy="http">复制 HTTP 示例</button><pre class="guide-code" data-language="http" tabindex="0">${esc(httpExample)}</pre>` : ''}
      <div class="docs-test-host" hidden></div>`;
    const button = host.querySelector('[data-python-test]');
    const testHost = host.querySelector('.docs-test-host');
    button?.addEventListener('click', () => {
      const open = testHost.hidden;
      if (open) window.CfquantApiTester.mount(testHost, entry);
      testHost.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
    });
    host.querySelector('[data-doc-algorithm-guide]')?.addEventListener('click', openAlgorithmGuide);
    host.querySelectorAll('[data-doc-copy]').forEach(button => {
      button.addEventListener('click', () => copyDocumentCode(button,
        button.dataset.docCopy === 'http' ? httpExample : entry.example));
    });
  }

  function openAlgorithmGuide() {
    setView('tutorial');
    setTutorialTopic('algorithm');
  }

  function mount() {
    host = document.querySelector('#cfquantDocs');
    if (!host) return;
    const list = entries();
    host.innerHTML = `<header class="docs-head"><div><span class="docs-kicker">CFQUANT API REFERENCE</span><h2>接口文档与调用示例</h2><p>查看执行算法、止盈止损、仓位计算、下单计划及行情数据接口的参数、返回值和示例。行情接口可在当前页面测试。</p><button type="button" data-doc-algorithm-intro>算法交易入门与完整示例</button></div><div class="docs-head-meta"><strong>${list.length}</strong><span>个接口</span></div></header>
      <div class="docs-layout"><aside class="docs-sidebar"><label for="docsGroup">接口分类</label><select id="docsGroup"><option value="all">全部接口</option><option value="algorithm">算法交易 · 条件单 / 仓位 / TWAP</option><option value="xtdata">行情 / 数据</option></select><label for="docsSearch">搜索接口</label><input id="docsSearch" type="search" placeholder="止损、仓位、TWAP 或接口名称"><nav aria-label="算法交易与行情数据接口"></nav></aside><article class="docs-article"><p class="docs-empty">请选择左侧接口</p></article></div>`;
    const nav = host.querySelector('nav');
    const drawNav = () => {
      const query = host.querySelector('#docsSearch').value.trim().toLowerCase();
      const group = host.querySelector('#docsGroup').value;
      const visible = list.filter(item => (group === 'all' || (group === 'algorithm' ? item.operation === 'algorithm' : item.module === 'xtdata'))
        && [item.name, item.title, item.description, item.group].join(' ').toLowerCase().includes(query));
      nav.innerHTML = visible.map((item, index) => `<button type="button" class="docs-nav-item${index === 0 ? ' active' : ''}" data-doc-id="${esc(item.id)}"><span>${esc(item.name)}</span><small>${esc(item.title || item.description || '')}</small></button>`).join('') || '<p class="docs-empty">没有匹配接口</p>';
      nav.querySelectorAll('[data-doc-id]').forEach(button => button.addEventListener('click', () => {
        nav.querySelectorAll('.docs-nav-item').forEach(node => node.classList.toggle('active', node === button));
        render(list.find(item => item.id === button.dataset.docId));
      }));
      if (visible[0]) render(visible[0]);
      else host.querySelector('.docs-article').innerHTML = '<p class="docs-empty">没有匹配接口，请调整分类或搜索内容。</p>';
    };
    host.querySelector('#docsSearch').addEventListener('input', drawNav);
    host.querySelector('#docsGroup').addEventListener('change', drawNav);
    host.querySelector('[data-doc-algorithm-intro]').addEventListener('click', openAlgorithmGuide);
    drawNav();
  }
  document.addEventListener('DOMContentLoaded', mount);
})();
