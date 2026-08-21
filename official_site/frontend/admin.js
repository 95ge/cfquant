const ADMIN_TOKEN_KEY = 'cfquant_admin_token';

const adminState = {
  token: localStorage.getItem(ADMIN_TOKEN_KEY) || '',
  section: 'overview',
  editingUserId: 0,
  selectedThreadId: 0,
  users: [],
  threads: [],
};

const $ = (id) => document.getElementById(id);
const CONFIG = window.CFQUANT_SITE_CONFIG || {};
const API_BASE = String(CONFIG.apiBase || '').replace(/\/$/, '');

const SECTION_META = {
  overview: { title: '运营总览', eyebrow: 'Operations' },
  users: { title: '用户管理', eyebrow: 'Users' },
  threads: { title: '讨论管理', eyebrow: 'Forum' },
  feedback: { title: '反馈处理', eyebrow: 'Feedback' },
  downloads: { title: '更新包', eyebrow: 'Packages' },
  notifications: { title: '站内通知', eyebrow: 'Broadcast' },
};

const USER_STATUS_LABELS = {
  active: '正常',
  suspended: '禁用',
  blocked: '拉黑',
};

const THREAD_STATUS_LABELS = {
  open: '开放',
  locked: '锁定',
};

const FEEDBACK_STATUS_LABELS = {
  open: '待处理',
  processing: '处理中',
  closed: '已关闭',
};

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

function encodeAttrJson(value) {
  return escapeHtml(JSON.stringify(value));
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

function shortText(value, max = 80) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text || '-';
  return `${text.slice(0, max)}...`;
}

function statusLabel(value, labels = USER_STATUS_LABELS) {
  return labels[String(value || '').toLowerCase()] || value || '-';
}

function statusClass(value) {
  return `status-${String(value || '').toLowerCase()}`;
}

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    const text = String(value || '').trim();
    if (text) search.set(key, text);
  });
  const query = search.toString();
  return query ? `?${query}` : '';
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
      localStorage.removeItem(ADMIN_TOKEN_KEY);
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

function table(headers, rows) {
  if (!rows.length) return '<div class="empty-state compact"><span>暂无数据</span></div>';
  return `
    <table>
      <thead>
        <tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join('')}</tr>
      </thead>
      <tbody>${rows.join('')}</tbody>
    </table>
  `;
}

function setSection(section, shouldLoad = true) {
  adminState.section = section;
  const meta = SECTION_META[section] || SECTION_META.overview;
  $('adminPageTitle').textContent = meta.title;
  $('adminBreadcrumb').textContent = meta.eyebrow;
  document.querySelectorAll('[data-admin-section]').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.adminSection === section);
  });
  document.querySelectorAll('[data-admin-view]').forEach((view) => {
    view.classList.toggle('is-active', view.dataset.adminView === section);
  });
  if (shouldLoad) refreshCurrent().catch((error) => toast(error.message));
}

async function refreshCurrent() {
  if (!adminState.token) return;
  if (adminState.section === 'overview') await loadOverview();
  if (adminState.section === 'users') await loadUsers();
  if (adminState.section === 'threads') await loadThreads();
  if (adminState.section === 'feedback') await loadFeedback();
  if (adminState.section === 'downloads') await loadDownloads();
}

async function loadOverview() {
  const data = await api('/api/admin/overview');
  const statLabels = [
    ['用户', data.stats.users],
    ['活跃用户', data.stats.active_users],
    ['帖子', data.stats.threads],
    ['回复', data.stats.replies],
    ['待处理反馈', data.stats.feedback_open],
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
        <td class="${statusClass(item.status)}">${escapeHtml(statusLabel(item.status))}</td>
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
        <td class="${statusClass(item.status)}">${escapeHtml(statusLabel(item.status, THREAD_STATUS_LABELS))}</td>
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
        <td class="${statusClass(item.status)}">${escapeHtml(statusLabel(item.status, FEEDBACK_STATUS_LABELS))}</td>
        <td>${formatTime(item.created_at)}</td>
      </tr>
    `),
  );
}

async function loadUsers() {
  const query = buildQuery({
    q: $('userSearch').value,
    status: $('userStatusFilter').value,
  });
  const data = await api(`/api/admin/users${query}`);
  adminState.users = data.users || [];
  $('userTable').innerHTML = table(
    ['ID', '昵称', '用户名', '手机号', '邮箱', '状态', '内容', '操作'],
    adminState.users.map((item) => {
      const quickStatus = item.status === 'active' ? 'suspended' : 'active';
      const quickLabel = item.status === 'active' ? '禁用' : '恢复';
      return `
        <tr>
          <td>${item.id}</td>
          <td>${escapeHtml(item.display_name)}</td>
          <td>${escapeHtml(item.username || '-')}</td>
          <td>${escapeHtml(item.phone)}</td>
          <td>${escapeHtml(item.email || '-')}</td>
          <td class="${statusClass(item.status)}">${escapeHtml(statusLabel(item.status))}</td>
          <td>${item.thread_count} 帖 / ${item.reply_count} 回复</td>
          <td>
            <div class="table-actions">
              <button class="ghost-button" type="button" data-edit-user='${encodeAttrJson(item)}'>编辑</button>
              <button class="ghost-button" type="button" data-set-user-status="${item.id}" data-user-status="${quickStatus}">${quickLabel}</button>
              <button class="danger-button" type="button" data-set-user-status="${item.id}" data-user-status="blocked" ${item.status === 'blocked' ? 'disabled' : ''}>拉黑</button>
            </div>
          </td>
        </tr>
      `;
    }),
  );
  if (adminState.editingUserId) {
    const selected = adminState.users.find((item) => Number(item.id) === Number(adminState.editingUserId));
    if (selected) fillUserForm(selected);
  }
}

function clearUserForm() {
  adminState.editingUserId = 0;
  $('userEditEmpty').classList.remove('hidden');
  $('userEditForm').classList.add('hidden');
  $('userEditForm').reset();
}

function fillUserForm(item) {
  adminState.editingUserId = Number(item.id || 0);
  $('userEditEmpty').classList.add('hidden');
  $('userEditForm').classList.remove('hidden');
  $('userId').value = item.id || '';
  $('userUsername').value = item.username || '';
  $('userDisplayName').value = item.display_name || '';
  $('userPhone').value = item.phone || '';
  $('userEmail').value = item.email || '';
  $('userStatus').value = item.status || 'active';
  $('userAvatarColor').value = /^#[0-9A-Fa-f]{6}$/.test(item.avatar_color || '') ? item.avatar_color : '#1f6feb';
  $('userPassword').value = '';
  $('userUsername').focus();
}

async function setUserStatus(userId, status) {
  await api(`/api/admin/users/${userId}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
  await Promise.all([loadOverview(), loadUsers()]);
  toast('用户状态已更新');
}

async function loadThreads() {
  const query = buildQuery({
    q: $('threadSearch').value,
    status: $('threadStatusFilter').value,
  });
  const data = await api(`/api/admin/threads${query}`);
  adminState.threads = data.threads || [];
  $('threadTable').innerHTML = table(
    ['ID', '标题', '作者', '状态', '回复', '操作'],
    adminState.threads.map((item) => `
      <tr>
        <td>${item.id}</td>
        <td>
          <strong>${escapeHtml(item.title)}</strong>
          <div class="admin-row-note">${escapeHtml(item.category_name || '-')} · ${escapeHtml(shortText(item.body, 96))}</div>
        </td>
        <td>
          ${escapeHtml(item.author_name)}
          <div class="admin-row-note">${formatTime(item.last_activity_at)}</div>
        </td>
        <td class="${statusClass(item.status)}">${escapeHtml(statusLabel(item.status, THREAD_STATUS_LABELS))}</td>
        <td>${item.reply_count}<div class="admin-row-note">${item.views} 浏览</div></td>
        <td>
          <div class="table-actions">
            <button class="ghost-button" type="button" data-view-replies="${item.id}">回复</button>
            <button class="ghost-button" type="button" data-lock-thread="${item.id}">${item.status === 'open' ? '锁定' : '解锁'}</button>
            <button class="danger-button" type="button" data-delete-thread="${item.id}">删除</button>
          </div>
        </td>
      </tr>
    `),
  );
  if (adminState.selectedThreadId) {
    const selected = adminState.threads.find((item) => Number(item.id) === Number(adminState.selectedThreadId));
    if (selected) {
      await loadThreadReplies(adminState.selectedThreadId);
    } else {
      clearThreadReplies();
    }
  }
}

function clearThreadReplies() {
  adminState.selectedThreadId = 0;
  $('threadReplyTitle').textContent = '请选择帖子';
  $('threadReplyMeta').textContent = '';
  $('replyTable').innerHTML = '<div class="empty-state compact"><span>从左侧帖子列表选择一条记录</span></div>';
}

async function loadThreadReplies(threadId) {
  const data = await api(`/api/admin/threads/${threadId}/replies`);
  adminState.selectedThreadId = Number(threadId);
  $('threadReplyTitle').textContent = data.thread.title;
  $('threadReplyMeta').textContent = `${statusLabel(data.thread.status, THREAD_STATUS_LABELS)} · ${data.replies.length} 条回复`;
  if (!data.replies.length) {
    $('replyTable').innerHTML = '<div class="empty-state compact"><span>暂无回复</span></div>';
    return;
  }
  $('replyTable').innerHTML = data.replies.map((reply) => `
    <article class="admin-reply-item ${reply.parent_id ? 'is-child' : ''}">
      <div class="reply-author">
        <span>#${reply.id} · ${escapeHtml(reply.author_name)}${reply.parent_id ? ` · 回复 #${reply.parent_id}` : ''}</span>
        <span>${formatTime(reply.created_at)}</span>
      </div>
      <p>${escapeHtml(reply.body || '[图片回复]')}</p>
      ${(reply.attachments || []).length ? `
        <div class="admin-row-note">
          ${(reply.attachments || []).map((item) => `${escapeHtml(item.file_name)} · ${formatSize(item.file_size)}`).join('，')}
        </div>
      ` : ''}
      <div class="table-actions">
        <button class="danger-button" type="button" data-delete-reply="${reply.id}">删除回复</button>
      </div>
    </article>
  `).join('');
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
        <td class="${statusClass(item.status)}">${escapeHtml(statusLabel(item.status, FEEDBACK_STATUS_LABELS))}</td>
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
        <td>${escapeHtml(shortText(item.body, 120))}</td>
        <td>
          <div class="table-actions">
            <select data-feedback-status="${item.id}">
              <option value="open" ${item.status === 'open' ? 'selected' : ''}>待处理</option>
              <option value="processing" ${item.status === 'processing' ? 'selected' : ''}>处理中</option>
              <option value="closed" ${item.status === 'closed' ? 'selected' : ''}>已关闭</option>
            </select>
            <button class="ghost-button" type="button" data-toggle-feedback-public="${item.id}">
              ${item.is_public ? '隐藏' : '公开'}
            </button>
          </div>
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
          <span class="${item.file_exists ? 'status-active' : 'status-closed'}">
            ${item.file_name ? (item.file_exists ? `已找到 · ${formatSize(item.file_size)}` : '文件不存在') : '未配置本地文件'}
          </span>
          ${item.external_url ? `<br><span>${escapeHtml(item.external_url)}</span>` : ''}
        </td>
        <td class="${item.is_active ? 'status-active' : 'status-suspended'}">${item.is_active ? '启用' : '下架'}</td>
        <td>${item.download_count}</td>
        <td>${formatTime(item.updated_at)}</td>
        <td>
          <div class="table-actions">
            <button class="ghost-button" type="button" data-edit-download='${encodeAttrJson(item)}'>编辑</button>
            <button class="ghost-button" type="button" data-toggle-download="${item.id}">${item.is_active ? '下架' : '启用'}</button>
            <button class="danger-button" type="button" data-delete-download="${item.id}">删除</button>
          </div>
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
  setSection('downloads', false);
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
      localStorage.setItem(ADMIN_TOKEN_KEY, data.token);
      updateAuthUi();
      setSection('overview');
      toast('已登录后台');
    } catch (error) {
      toast(error.message);
    }
  });

  $('adminLogout').addEventListener('click', async () => {
    await api('/api/auth/logout', { method: 'POST', body: '{}' }).catch(() => {});
    adminState.token = '';
    localStorage.removeItem(ADMIN_TOKEN_KEY);
    updateAuthUi();
  });

  $('adminRefresh').addEventListener('click', () => {
    refreshCurrent().catch((error) => toast(error.message));
  });

  document.querySelectorAll('[data-admin-section]').forEach((button) => {
    button.addEventListener('click', () => setSection(button.dataset.adminSection));
  });

  $('userFilterForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    await loadUsers().catch((error) => toast(error.message));
  });

  $('userTable').addEventListener('click', async (event) => {
    const editButton = event.target.closest('[data-edit-user]');
    if (editButton) {
      try {
        fillUserForm(JSON.parse(editButton.dataset.editUser));
      } catch (_error) {
        toast('用户数据解析失败');
      }
      return;
    }
    const statusButton = event.target.closest('[data-set-user-status]');
    if (!statusButton) return;
    const targetStatus = statusButton.dataset.userStatus;
    const label = statusLabel(targetStatus);
    if (targetStatus !== 'active' && !confirm(`确认将该用户设为${label}？`)) return;
    await setUserStatus(statusButton.dataset.setUserStatus, targetStatus).catch((error) => toast(error.message));
  });

  $('userEditForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const userId = $('userId').value;
    if (!userId) return;
    const payload = {
      username: $('userUsername').value,
      display_name: $('userDisplayName').value,
      phone: $('userPhone').value,
      email: $('userEmail').value,
      status: $('userStatus').value,
      avatar_color: $('userAvatarColor').value,
    };
    if ($('userPassword').value) payload.password = $('userPassword').value;
    try {
      const data = await api(`/api/admin/users/${userId}`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      fillUserForm(data.user);
      await Promise.all([loadOverview(), loadUsers()]);
      toast('用户信息已保存');
    } catch (error) {
      toast(error.message);
    }
  });

  $('threadFilterForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    await loadThreads().catch((error) => toast(error.message));
  });

  $('threadTable').addEventListener('click', async (event) => {
    const replyButton = event.target.closest('[data-view-replies]');
    if (replyButton) {
      await loadThreadReplies(replyButton.dataset.viewReplies).catch((error) => toast(error.message));
      return;
    }
    const lockButton = event.target.closest('[data-lock-thread]');
    if (lockButton) {
      try {
        await api(`/api/admin/threads/${lockButton.dataset.lockThread}/lock`, { method: 'POST', body: '{}' });
        await Promise.all([loadOverview(), loadThreads()]);
        toast('帖子状态已更新');
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const deleteButton = event.target.closest('[data-delete-thread]');
    if (!deleteButton) return;
    if (!confirm('确认删除该帖子及其全部回复？该操作不可撤销。')) return;
    try {
      await api(`/api/admin/threads/${deleteButton.dataset.deleteThread}/delete`, { method: 'POST', body: '{}' });
      if (Number(adminState.selectedThreadId) === Number(deleteButton.dataset.deleteThread)) clearThreadReplies();
      await Promise.all([loadOverview(), loadThreads()]);
      toast('帖子已删除');
    } catch (error) {
      toast(error.message);
    }
  });

  $('replyTable').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-delete-reply]');
    if (!button) return;
    if (!confirm('确认删除该回复及其子回复？')) return;
    try {
      await api(`/api/admin/replies/${button.dataset.deleteReply}/delete`, { method: 'POST', body: '{}' });
      await Promise.all([loadOverview(), loadThreads()]);
      if (adminState.selectedThreadId) await loadThreadReplies(adminState.selectedThreadId);
      toast('回复已删除');
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

  $('clearDownloadForm').addEventListener('click', clearDownloadForm);

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
  clearThreadReplies();
  if (adminState.token) {
    try {
      setSection('overview');
    } catch (error) {
      toast(error.message);
    }
  }
}

init();
