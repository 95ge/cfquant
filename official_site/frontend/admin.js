const adminState = {
  token: localStorage.getItem('cfquant_admin_token') || '',
};

const $ = (id) => document.getElementById(id);
const CONFIG = window.CFQUANT_SITE_CONFIG || {};
const API_BASE = String(CONFIG.apiBase || '').replace(/\/$/, '');

function apiUrl(path) {
  if (!API_BASE) return path;
  return `${API_BASE}${path}`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return '-';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (adminState.token) headers.Authorization = `Bearer ${adminState.token}`;
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      ...headers,
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    if (response.status === 401) {
      adminState.token = '';
      localStorage.removeItem('cfquant_admin_token');
      updateAuthUi();
    }
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

async function openAdminAttachment(attachmentId) {
  const headers = {};
  if (adminState.token) headers.Authorization = `Bearer ${adminState.token}`;
  const response = await fetch(apiUrl(`/api/admin/feedback/attachments/${attachmentId}`), { headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `附件打开失败：${response.status}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank', 'noopener,noreferrer');
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.classList.remove('hidden');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.add('hidden'), 2600);
}

function updateAuthUi() {
  const authed = Boolean(adminState.token);
  $('adminLoginPanel').classList.toggle('hidden', authed);
  $('adminWorkspace').classList.toggle('hidden', !authed);
  $('adminLogout').classList.toggle('hidden', !authed);
}

function statusClass(value) {
  return `status-${String(value || '').toLowerCase()}`;
}

function table(headers, rows) {
  if (!rows.length) return '<div class="empty-state"><span>暂无数据</span></div>';
  return `
    <table>
      <thead>
        <tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join('')}</tr>
      </thead>
      <tbody>${rows.join('')}</tbody>
    </table>
  `;
}

async function loadOverview() {
  if (!adminState.token) return;
  const data = await api('/api/admin/overview');
  const statLabels = [
    ['用户', data.stats.users],
    ['活跃用户', data.stats.active_users],
    ['帖子', data.stats.threads],
    ['回复', data.stats.replies],
    ['未处理反馈', data.stats.feedback_open],
    ['点击', data.stats.clicks],
    ['下载', data.stats.downloads],
  ];
  $('adminStats').innerHTML = statLabels.map(([label, value]) => `
    <div><dt>${escapeHtml(value)}</dt><dd>${escapeHtml(label)}</dd></div>
  `).join('');

  $('topPaths').innerHTML = table(
    ['路径', '事件', '次数'],
    (data.top_paths || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.path)}</td>
        <td>${escapeHtml(item.event)}</td>
        <td>${escapeHtml(item.count)}</td>
      </tr>
    `),
  );

  $('recentUsers').innerHTML = table(
    ['用户', '手机号', '状态', '注册时间'],
    (data.recent_users || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.display_name)}</td>
        <td>${escapeHtml(item.phone)}</td>
        <td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td>
        <td>${formatTime(item.created_at)}</td>
      </tr>
    `),
  );

  $('recentThreads').innerHTML = table(
    ['标题', '作者', '状态', '回复', '最后活跃'],
    (data.recent_threads || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.author_name)}</td>
        <td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td>
        <td>${escapeHtml(item.reply_count)}</td>
        <td>${formatTime(item.last_activity_at)}</td>
      </tr>
    `),
  );

  $('recentFeedback').innerHTML = table(
    ['标题', '提交人', '状态', '时间'],
    (data.feedback || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.reporter)}</td>
        <td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td>
        <td>${formatTime(item.created_at)}</td>
      </tr>
    `),
  );
}

async function loadUsers() {
  const data = await api('/api/admin/users');
  $('userTable').innerHTML = table(
    ['ID', '昵称', '手机号', '邮箱', '状态', '发帖', '回复', '操作'],
    (data.users || []).map((item) => `
      <tr>
        <td>${item.id}</td>
        <td>${escapeHtml(item.display_name)}</td>
        <td>${escapeHtml(item.phone)}</td>
        <td>${escapeHtml(item.email || '-')}</td>
        <td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td>
        <td>${item.thread_count}</td>
        <td>${item.reply_count}</td>
        <td><button class="ghost-button" type="button" data-toggle-user="${item.id}">${item.status === 'active' ? '停用' : '恢复'}</button></td>
      </tr>
    `),
  );
}

async function loadThreads() {
  const data = await api('/api/admin/threads');
  $('threadTable').innerHTML = table(
    ['ID', '标题', '分类', '作者', '状态', '浏览', '回复', '操作'],
    (data.threads || []).map((item) => `
      <tr>
        <td>${item.id}</td>
        <td>${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.category_name || '-')}</td>
        <td>${escapeHtml(item.author_name)}</td>
        <td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td>
        <td>${item.views}</td>
        <td>${item.reply_count}</td>
        <td><button class="ghost-button" type="button" data-lock-thread="${item.id}">${item.status === 'open' ? '锁定' : '解锁'}</button></td>
      </tr>
    `),
  );
}

async function loadFeedback() {
  const data = await api('/api/admin/feedback');
  $('feedbackTable').innerHTML = table(
    ['ID', '标题', '提交人', '联系方式', '状态', '公开', '截图', '内容', '操作'],
    (data.feedback || []).map((item) => `
      <tr>
        <td>${item.id}</td>
        <td>${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.user_name || '匿名')}</td>
        <td>${escapeHtml(item.user_phone || item.user_email || item.contact || '-')}</td>
        <td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td>
        <td>
          <span class="${item.is_public ? 'status-active' : 'status-suspended'}">${item.is_public ? '公开' : '私有'}</span>
        </td>
        <td>
          <div class="attachment-list">
            ${(item.attachments || []).map((attachment) => `
              <button class="ghost-button" type="button" data-open-attachment="${attachment.id}">
                ${escapeHtml(attachment.file_name)} · ${formatSize(attachment.file_size)}
              </button>
            `).join('') || '-'}
          </div>
        </td>
        <td>${escapeHtml(item.body)}</td>
        <td>
          <select data-feedback-status="${item.id}">
            <option value="open" ${item.status === 'open' ? 'selected' : ''}>open</option>
            <option value="processing" ${item.status === 'processing' ? 'selected' : ''}>processing</option>
            <option value="closed" ${item.status === 'closed' ? 'selected' : ''}>closed</option>
          </select>
          <button class="ghost-button" type="button" data-toggle-feedback-public="${item.id}">
            ${item.is_public ? '隐藏' : '公开'}
          </button>
        </td>
      </tr>
    `),
  );
}

async function loadDownloads() {
  const data = await api('/api/admin/downloads');
  $('downloadTable').innerHTML = table(
    ['ID', '标题', '版本', '渠道', '文件', '状态', '下载', '更新时间', '操作'],
    (data.downloads || []).map((item) => `
      <tr>
        <td>${item.id}</td>
        <td>${escapeHtml(item.title)}</td>
        <td>${escapeHtml(item.version)}</td>
        <td>${escapeHtml(item.channel)}</td>
        <td>
          <strong>${escapeHtml(item.file_name || '-')}</strong><br>
          <span class="${item.file_exists ? 'status-active' : 'status-closed'}">${item.file_name ? (item.file_exists ? `已找到 · ${formatSize(item.file_size)}` : '文件不存在') : '未配置本地文件'}</span>
          ${item.external_url ? `<br><span>${escapeHtml(item.external_url)}</span>` : ''}
        </td>
        <td class="${item.is_active ? 'status-active' : 'status-suspended'}">${item.is_active ? '启用' : '下架'}</td>
        <td>${item.download_count}</td>
        <td>${formatTime(item.updated_at)}</td>
        <td>
          <button class="ghost-button" type="button" data-edit-download='${escapeHtml(JSON.stringify(item))}'>编辑</button>
          <button class="ghost-button" type="button" data-toggle-download="${item.id}">${item.is_active ? '下架' : '启用'}</button>
          <button class="danger-button" type="button" data-delete-download="${item.id}">删除</button>
        </td>
      </tr>
    `),
  );
}

function clearDownloadForm() {
  $('downloadId').value = '';
  $('downloadTitle').value = 'cfquant 更新包';
  $('downloadVersion').value = '';
  $('downloadFile').value = '';
  $('downloadUrl').value = '';
  $('downloadNotes').value = '';
}

function fillDownloadForm(item) {
  $('downloadId').value = item.id || '';
  $('downloadTitle').value = item.title || '';
  $('downloadVersion').value = item.version || '';
  $('downloadFile').value = item.file_name || '';
  $('downloadUrl').value = item.external_url || '';
  $('downloadNotes').value = item.notes || '';
  $('downloadTitle').focus();
}

function bindEvents() {
  $('adminLoginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await api('/api/admin/login', {
        method: 'POST',
        body: JSON.stringify({
          username: $('adminUsername').value,
          password: $('adminPassword').value,
        }),
      });
      adminState.token = data.token;
      localStorage.setItem('cfquant_admin_token', data.token);
      updateAuthUi();
      await Promise.all([loadOverview(), loadDownloads()]);
      toast('已登录后台');
    } catch (error) {
      toast(error.message);
    }
  });

  $('adminLogout').addEventListener('click', () => {
    adminState.token = '';
    localStorage.removeItem('cfquant_admin_token');
    updateAuthUi();
  });

  $('adminRefresh').addEventListener('click', () => {
    loadOverview().catch((error) => toast(error.message));
  });

  $('loadUsers').addEventListener('click', () => loadUsers().catch((error) => toast(error.message)));
  $('loadThreads').addEventListener('click', () => loadThreads().catch((error) => toast(error.message)));
  $('loadFeedback').addEventListener('click', () => loadFeedback().catch((error) => toast(error.message)));
  $('loadDownloads').addEventListener('click', () => loadDownloads().catch((error) => toast(error.message)));
  $('clearDownloadForm').addEventListener('click', clearDownloadForm);

  $('userTable').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-toggle-user]');
    if (!button) return;
    try {
      await api(`/api/admin/users/${button.dataset.toggleUser}/toggle`, { method: 'POST', body: '{}' });
      await Promise.all([loadOverview(), loadUsers()]);
      toast('用户状态已更新');
    } catch (error) {
      toast(error.message);
    }
  });

  $('threadTable').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-lock-thread]');
    if (!button) return;
    try {
      await api(`/api/admin/threads/${button.dataset.lockThread}/lock`, { method: 'POST', body: '{}' });
      await Promise.all([loadOverview(), loadThreads()]);
      toast('帖子状态已更新');
    } catch (error) {
      toast(error.message);
    }
  });

  $('feedbackTable').addEventListener('change', async (event) => {
    const select = event.target.closest('[data-feedback-status]');
    if (!select) return;
    try {
      await api(`/api/admin/feedback/${select.dataset.feedbackStatus}/status`, {
        method: 'POST',
        body: JSON.stringify({ status: select.value }),
      });
      await Promise.all([loadOverview(), loadFeedback()]);
      toast('反馈状态已更新');
    } catch (error) {
      toast(error.message);
    }
  });

  $('feedbackTable').addEventListener('click', async (event) => {
    const toggleButton = event.target.closest('[data-toggle-feedback-public]');
    if (toggleButton) {
      try {
        await api(`/api/admin/feedback/${toggleButton.dataset.toggleFeedbackPublic}/public`, {
          method: 'POST',
          body: '{}',
        });
        await Promise.all([loadOverview(), loadFeedback()]);
        toast('反馈公开状态已更新');
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const button = event.target.closest('[data-open-attachment]');
    if (!button) return;
    try {
      await openAdminAttachment(button.dataset.openAttachment);
    } catch (error) {
      toast(error.message);
    }
  });

  $('downloadTable').addEventListener('click', async (event) => {
    const editButton = event.target.closest('[data-edit-download]');
    if (editButton) {
      try {
        fillDownloadForm(JSON.parse(editButton.dataset.editDownload));
      } catch (_error) {
        toast('更新包数据解析失败');
      }
      return;
    }
    const toggleButton = event.target.closest('[data-toggle-download]');
    if (toggleButton) {
      try {
        await api(`/api/admin/downloads/${toggleButton.dataset.toggleDownload}/toggle`, { method: 'POST', body: '{}' });
        await Promise.all([loadOverview(), loadDownloads()]);
        toast('更新包状态已更新');
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const deleteButton = event.target.closest('[data-delete-download]');
    if (deleteButton) {
      if (!confirm('确认删除这条更新包记录？不会删除 packages 目录里的文件。')) return;
      try {
        await api(`/api/admin/downloads/${deleteButton.dataset.deleteDownload}/delete`, { method: 'POST', body: '{}' });
        await Promise.all([loadOverview(), loadDownloads()]);
        toast('更新包记录已删除');
      } catch (error) {
        toast(error.message);
      }
    }
  });

  $('downloadForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/api/admin/downloads', {
        method: 'POST',
        body: JSON.stringify({
          id: $('downloadId').value,
          title: $('downloadTitle').value,
          version: $('downloadVersion').value,
          file_name: $('downloadFile').value,
          external_url: $('downloadUrl').value,
          notes: $('downloadNotes').value,
          is_active: true,
        }),
      });
      clearDownloadForm();
      await Promise.all([loadOverview(), loadDownloads()]);
      toast('更新包已保存');
    } catch (error) {
      toast(error.message);
    }
  });

  $('broadcastForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await api('/api/admin/notifications/broadcast', {
        method: 'POST',
        body: JSON.stringify({
          title: $('broadcastTitle').value,
          body: $('broadcastBody').value,
        }),
      });
      event.target.reset();
      toast(`已发送 ${data.sent} 条通知`);
    } catch (error) {
      toast(error.message);
    }
  });
}

async function init() {
  bindEvents();
  updateAuthUi();
  if (adminState.token) {
    try {
      await Promise.all([loadOverview(), loadDownloads()]);
    } catch (error) {
      toast(error.message);
    }
  }
}

init();
