/* Session diagnostics: account/function filters and recoverable incidents. */
(() => {
  'use strict';

  const limit = 180;
  const categories = { account: '账号查询', callbacks: '回调事件', trade: '交易操作', system: '系统运行' };
  const pageCategories = {
    callbacks: ['callbacks'], status: ['system'],
    trade: ['account', 'trade', 'callbacks'], orders: ['account', 'trade', 'callbacks'],
  };
  const entries = [];
  const operations = new Map();
  let context = { view: 'overview', account: {} };
  let sequence = 0;

  const $ = id => document.getElementById(id);
  const stamp = time => new Date(time).toLocaleString('zh-CN', { hour12: false });
  const scope = entry => JSON.stringify([
    entry.category, entry.account.key || '', entry.account.type || '', entry.account.bridge || '', entry.account.channel || '',
  ]);
  function snapshot(data) {
    if (data === undefined) return '';
    try { return JSON.stringify(data, null, 2).slice(0, 6000); }
    catch (_) { return String(data).slice(0, 6000); }
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function visible(entry) {
    const category = $('logCategoryFilter')?.value || 'current';
    const allowed = category === 'current' ? pageCategories[context.view] : [category];
    if (category !== 'all' && allowed && !allowed.includes(entry.category)) return false;
    if (($('logAccountFilter')?.value || 'current') === 'all') return true;
    return !entry.account.key || entry.account.key === context.account.key;
  }
  function remove(entry) {
    for (const [key, value] of operations) if (value.entry === entry) operations.delete(key);
    const index = entries.indexOf(entry);
    if (index >= 0) entries.splice(index, 1);
  }
  function create(message, data, options) {
    const now = Date.now();
    const entry = {
      id: ++sequence, category: options.category || 'system', account: { ...(options.account || {}) },
      message, detail: snapshot(data), firstAt: now, lastAt: now, count: 0,
      status: 'info', members: new Map(), expanded: false,
    };
    entries.unshift(entry);
    while (entries.length > limit) remove(entries[entries.length - 1]);
    return entry;
  }
  function detach(key, status) {
    const previous = operations.get(key);
    if (!previous) return;
    operations.delete(key);
    previous.member.status = status;
    previous.member.finishedAt = Date.now();
    const entry = previous.entry;
    entry.lastAt = Date.now();
    if (![...entry.members.values()].some(member => member.status === 'active')) {
      entry.status = [...entry.members.values()].every(member => member.status === 'recovered') ? 'recovered' : 'changed';
    }
  }
  function add(message, data, options = {}) {
    const incident = options.incident;
    const base = { category: options.category || 'system', account: options.account || {} };
    if (incident) {
      const operationKey = JSON.stringify([scope(base), incident.operation]);
      const previous = operations.get(operationKey);
      if (incident.resolved) {
        if (!previous) return;
        detach(operationKey, 'recovered');
      } else {
        const reason = incident.reason || message;
        const group = JSON.stringify([scope(base), reason]);
        if (previous?.entry.group === group && previous.member.attempt === incident.attempt) return;
        if (previous && previous.entry.group !== group) detach(operationKey, 'changed');
        let entry = entries.find(row => row.group === group && row.status === 'active');
        if (!entry) {
          entry = create(incident.summary || message, undefined, options);
          entry.group = group;
          entry.recoveredSummary = incident.recoveredSummary;
          entry.status = 'active';
        }
        const member = entry.members.get(incident.operation) || { label: incident.label || message, count: 0 };
        Object.assign(member, { status: 'active', attempt: incident.attempt, detail: snapshot(data) });
        member.count += 1;
        entry.members.set(incident.operation, member);
        operations.set(operationKey, { entry, member });
        entry.count += 1;
        entry.lastAt = Date.now();
      }
    } else {
      const detail = snapshot(data);
      let entry = entries.find(row => !row.group && row.message === message && row.detail === detail
        && scope(row) === scope(base) && Date.now() - row.lastAt <= 5000);
      if (!entry) entry = create(message, data, options);
      entry.count += 1;
      entry.lastAt = Date.now();
    }
    render();
  }
  function render() {
    const box = $('logBox');
    if (!box) return;
    const scrollTop = box.scrollTop;
    const rows = entries.filter(visible).sort((a, b) => b.lastAt - a.lastAt || b.id - a.id);
    const fragment = document.createDocumentFragment();
    for (const entry of rows) {
      const row = element('div', 'log-entry');
      row.dataset.status = entry.status;
      row.dataset.category = entry.category;
      row.dataset.accountKey = entry.account.key || '';
      const head = element('div', 'log-entry-head');
      head.append(element('span', 'log-category', categories[entry.category] || entry.category));
      head.append(element('span', 'log-account', entry.account.label || entry.account.id || '系统'));
      if (entry.account.channel) head.append(element('span', 'log-channel', entry.account.channel === 'trade' ? '交易通道' : '普通通道'));
      const states = { active: '待恢复', recovered: '已恢复', changed: '原因已变化' };
      if (states[entry.status]) head.append(element('span', 'log-state', states[entry.status]));
      const title = entry.status === 'recovered'
        ? entry.recoveredSummary || `${entry.category === 'account' ? '账号查询' : categories[entry.category]}已恢复` : entry.message;
      row.append(head, element('div', 'log-message', title));
      const members = [...entry.members.values()];
      const pending = members.filter(member => member.status === 'active');
      if (members.length) {
        row.append(element('div', 'log-affected', `涉及：${members.map(member => member.label).join('、')}`
          + (pending.length && pending.length !== members.length ? `；待恢复：${pending.map(member => member.label).join('、')}` : '')));
      }
      row.append(element('div', 'log-meta', `${entry.group ? '失败累计' : '记录'} ${entry.count} 次 · 首次 ${stamp(entry.firstAt)} · ${entry.status === 'recovered' ? '恢复' : '最近'} ${stamp(entry.lastAt)}`));
      const detail = entry.group
        ? `${entry.message}\n\n` + members.map(member => `${member.label}（${member.count} 次；${states[member.status]}）\n${member.detail}`).join('\n\n')
        : entry.detail;
      if (detail) {
        const disclosure = element('details', 'log-detail');
        disclosure.open = entry.expanded;
        disclosure.append(element('summary', '', '查看详情'), element('pre', '', detail));
        disclosure.addEventListener('toggle', () => { entry.expanded = disclosure.open; });
        row.append(disclosure);
      }
      fragment.append(row);
    }
    if (!rows.length) fragment.append(element('div', 'log-empty', '当前筛选下暂无日志，可切换功能或账号范围查看其他记录。'));
    box.replaceChildren(fragment);
    box.scrollTop = scrollTop;
    if ($('logCount')) $('logCount').textContent = `${rows.length} 条 / 共 ${entries.length} 条`;
  }
  function clearVisible() {
    const removed = entries.filter(visible);
    removed.forEach(remove);
    render();
    return removed.map(({ category, account }) => ({ category, account }));
  }
  function setContext(next) {
    context = next;
    render();
  }
  for (const id of ['logCategoryFilter', 'logAccountFilter']) $(id)?.addEventListener('change', render);
  window.CfquantActivityLog = { add, setContext, clearVisible };
})();
