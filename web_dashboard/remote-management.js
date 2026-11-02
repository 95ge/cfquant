/* Uses the dashboard's authenticated API client. Never persist cloud secrets in the browser. */
(() => {
  const form = document.getElementById('remoteConnectionForm');
  if (!form) return;
  const message = document.getElementById('remoteConnectionMessage');
  let loaded = false;
  let configured = false;
  const labels = {disabled: '未启用', connected: '已连接官网', connecting: '正在连接', disconnected: '连接中断', credential_unavailable: '无法解密配置'};
  function render(data, fill) {
    document.getElementById('remoteConnectionStatus').textContent = [labels[data.state] || data.state, data.name,
      data.instance_id, data.key_prefix ? `Key：${data.key_prefix}…` : '', data.error_code].filter(Boolean).join(' · ');
    const project = document.getElementById('remoteProjectInfo');
    project.hidden = !data.name;
    project.textContent = [data.name ? `已绑定项目：${data.name}` : '', data.note].filter(Boolean).join(' · ');
    if (!fill) return;
    configured = !!data.configured;
    form.elements.enabled.checked = !!data.enabled;
    form.elements.api_key.placeholder = configured ? '已保存 Key；留空保留，填写新 Key 可更换' : '粘贴官网创建的 cfqr_…';
    document.getElementById('remoteKeyHint').textContent = configured ? 'Key 已加密保存在本机。留空可保留现有 Key；项目名称、备注及 Key 轮换请在官网管理。' : '请先在官网添加部署并复制 Key。本地不需要输入官网账号密码；此 Key 与本地交易接口 API Key 不同。';
    for (const key of ['queries', 'service_control', 'qmt_control']) form.elements[key].checked = !!data.permissions?.[key];
    loaded = true;
  }
  async function load(fill = false) {
    try { render(await api('/api/remote-management'), fill || !loaded); }
    catch (e) { message.textContent = e.message; }
  }
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('[type=submit]');
    const body = {enabled: form.elements.enabled.checked, permissions: {}};
    if (body.enabled) {
      body.api_key = form.elements.api_key.value.trim();
      if (!body.api_key && !configured) { message.textContent = '请先在官网创建部署，再填写对应的项目 API Key。';form.elements.api_key.focus();return; }
      for (const key of ['queries', 'service_control', 'qmt_control']) body.permissions[key] = form.elements[key].checked;
    }
    button.disabled = true;
    message.textContent = '正在保存…';
    try {
      render(await api('/api/remote-management', {method: 'POST', body: JSON.stringify(body)}), true);
      message.textContent = body.enabled ? '接入配置已保存，连接状态将在数秒内更新。' : '远程接入已关闭。';
    } catch (e) { message.textContent = `${e.message}${e.payload?.code ? `（${e.payload.code}）` : ''}`; }
    finally {
      form.elements.api_key.value = ''; button.disabled = false;
    }
  });
  document.getElementById('remoteRefresh').addEventListener('click', () => load(false));
  document.querySelector('[data-settings-tab="remote-management"].settings-menu-item').addEventListener('click', () => load(!loaded));
  setInterval(() => {
    if (!document.hidden && document.body.dataset.settingsTab === 'remote-management') load(false);
  }, 10000);
  if (document.body.dataset.settingsTab === 'remote-management') load(true);
})();
