const ADMIN_TOKEN_KEY = 'cfquant_admin_token';

const adminState = {
  token: localStorage.getItem(ADMIN_TOKEN_KEY) || '',
  section: 'overview',
  editingUserId: 0,
  selectedThreadId: 0,
  selectedFeedbackId: 0,
  editingFeedbackReplyId: 0,
  users: [],
  threads: [],
  feedback: [],
  features: [],
  feedbackDetail: null,
  emailSettings: null,
  emailUsers: [],
  emailLogs: [],
  feedbackReplyFiles: [],
  feedbackReplyPreviewUrls: [],
  inlineImageUrls: [],
  imageModalObjectUrl: '',
};

const $ = (id) => document.getElementById(id);
const CONFIG = window.CFQUANT_SITE_CONFIG || {};
const API_BASE = String(CONFIG.apiBase || '').replace(/\/$/, '');
const MAX_FEEDBACK_REPLY_IMAGES = 10;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DEFAULT_AVATAR_URL = '/avatars/market-blue.svg';

const SECTION_META = {
  overview: { title: '运营总览', eyebrow: 'Operations' },
  users: { title: '用户管理', eyebrow: 'Users' },
  threads: { title: '讨论管理', eyebrow: 'Forum' },
  feedback: { title: '反馈处理', eyebrow: 'Feedback' },
  features: { title: '需求建议', eyebrow: 'Feature Requests' },
  downloads: { title: '更新包', eyebrow: 'Packages' },
  email: { title: '邮件服务', eyebrow: 'Email' },
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

const FEATURE_STATUS_LABELS = {
  open: '待评估',
  reviewing: '评估中',
  planned: '已排期',
  done: '已完成',
  declined: '暂不采纳',
};

const FEATURE_MODULE_LABELS = {
  bridge: '桥接运行',
  quote: '行情数据',
  trade: '交易接口',
  web: '官网 / 控制台',
  docs: '文档示例',
  other: '其它',
};

const FEATURE_PRIORITY_LABELS = {
  low: '低',
  normal: '常规',
  high: '高',
};

const EMAIL_STATUS_LABELS = {
  pending: '发送中',
  sent: '已发送',
  failed: '失败',
  skipped: '跳过',
};

function apiUrl(path) {
  if (!API_BASE) return path;
  return `${API_BASE}${path}`;
}

function assetUrl(path) {
  const value = String(path || '').trim();
  if (!value) return '';
  if (/^(https?:|data:|blob:)/i.test(value)) return value;
  if (value.startsWith('/api/')) return apiUrl(value);
  return value;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function safeColor(value, fallback = '#1f6feb') {
  const text = String(value || '').trim();
  return /^#[0-9A-Fa-f]{6}$/.test(text) ? text : fallback;
}

function safeAvatarUrl(value) {
  const text = String(value || '').trim();
  if (!text) return DEFAULT_AVATAR_URL;
  if (text.startsWith('/avatars/') || text.startsWith('/api/user-avatars/')) return text;
  return DEFAULT_AVATAR_URL;
}

function avatarInitial(user = {}) {
  const label = String(user.display_name || user.username || 'C').trim();
  return (label[0] || 'C').toUpperCase();
}

function avatarHtml(user = {}, className = '') {
  const classes = ['avatar-badge', className].filter(Boolean).join(' ');
  return `
    <span class="${classes}" style="--avatar-color:${escapeHtml(safeColor(user.avatar_color))}">
      <img src="${escapeHtml(assetUrl(safeAvatarUrl(user.avatar_url)))}" alt="" loading="lazy">
      <span>${escapeHtml(avatarInitial(user))}</span>
    </span>
  `;
}

function isValidEmail(value) {
  return EMAIL_PATTERN.test(String(value || '').trim().toLowerCase());
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

function fileToAttachment(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve({
        name: file.name,
        type: file.type,
        size: file.size,
        data: String(reader.result || ''),
      });
    };
    reader.onerror = () => reject(new Error('截图读取失败'));
    reader.readAsDataURL(file);
  });
}

function normalizeImageFile(file, index = 0) {
  if (file.name) return file;
  const ext = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/webp': 'webp',
    'image/gif': 'gif',
  }[file.type] || 'png';
  return new File([file], `clipboard-${Date.now()}-${index + 1}.${ext}`, {
    type: file.type || 'image/png',
    lastModified: Date.now(),
  });
}

function validateImageFiles(files, label = '截图') {
  const allowed = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
  const selected = Array.from(files || []).filter(Boolean).map(normalizeImageFile);
  for (const file of selected) {
    if (!allowed.has(file.type)) {
      toast(`${label}只支持 png、jpg、webp、gif`);
      return [];
    }
    if (file.size > 3 * 1024 * 1024) {
      toast(`单张${label}不能超过 3MB`);
      return [];
    }
  }
  return selected;
}

function pastedImageFiles(event) {
  const clipboard = event.clipboardData;
  if (!clipboard) return [];
  const itemFiles = Array.from(clipboard.items || [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter(Boolean);
  if (itemFiles.length) return itemFiles;
  return Array.from(clipboard.files || []).filter((file) => file.type.startsWith('image/'));
}

function handleAdminFeedbackReplyPaste(event) {
  const view = $('adminViewFeedback');
  if (!view || !view.classList.contains('is-active')) return;
  const target = event.target instanceof Element ? event.target : null;
  const detail = $('feedbackDetail');
  const form = target?.closest('[data-feedback-reply-form]')
    || (target && detail?.contains(target) ? detail.querySelector('[data-feedback-reply-form]') : null)
    || document.querySelector('[data-feedback-reply-form]:focus-within');
  if (!form) return;
  const files = pastedImageFiles(event);
  if (!files.length) return;
  event.preventDefault();
  setFeedbackReplyFiles(files, { append: true });
  form.querySelector('[name="body"]')?.focus();
  const preview = form.querySelector('[data-feedback-reply-preview]');
  if (preview) {
    preview.classList.add('is-flashing');
    clearTimeout(handleAdminFeedbackReplyPaste.timer);
    handleAdminFeedbackReplyPaste.timer = setTimeout(() => preview.classList.remove('is-flashing'), 1000);
  }
  toast(`已添加 ${files.length} 张截图`);
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

async function fetchAdminImage(path) {
  const headers = {};
  if (adminState.token) headers.Authorization = `Bearer ${adminState.token}`;
  const response = await fetch(apiUrl(path), { headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `图片打开失败：${response.status}`);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

function revokeInlineImages() {
  adminState.inlineImageUrls.forEach((url) => URL.revokeObjectURL(url));
  adminState.inlineImageUrls = [];
}

async function hydrateAdminImages(root = document) {
  const images = Array.from(root.querySelectorAll('img[data-auth-image-src]'));
  await Promise.all(images.map(async (image) => {
    try {
      const url = await fetchAdminImage(image.dataset.authImageSrc);
      adminState.inlineImageUrls.push(url);
      image.src = url;
      image.classList.add('is-loaded');
    } catch (_error) {
      image.alt = '图片加载失败';
      image.classList.add('is-error');
    }
  }));
}

function hideAdminImageModal() {
  const modal = $('adminImageModal');
  const image = $('adminImageModalImage');
  if (!modal || !image) return;
  modal.classList.add('hidden');
  image.removeAttribute('src');
  image.alt = '图片预览';
  if (adminState.imageModalObjectUrl) {
    URL.revokeObjectURL(adminState.imageModalObjectUrl);
    adminState.imageModalObjectUrl = '';
  }
}

async function openAdminImage(path, title = '图片预览') {
  if (!path) return;
  const modal = $('adminImageModal');
  const image = $('adminImageModalImage');
  const titleNode = $('adminImageModalTitle');
  if (!modal || !image || !titleNode) return;
  if (adminState.imageModalObjectUrl) {
    URL.revokeObjectURL(adminState.imageModalObjectUrl);
    adminState.imageModalObjectUrl = '';
  }
  const url = await fetchAdminImage(path);
  adminState.imageModalObjectUrl = url;
  titleNode.textContent = title || '图片预览';
  image.src = url;
  image.alt = title || '图片预览';
  modal.classList.remove('hidden');
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
  if (adminState.section === 'features') await loadFeatures();
  if (adminState.section === 'downloads') await loadDownloads();
  if (adminState.section === 'email') await loadEmail();
}

async function loadOverview() {
  const data = await api('/api/admin/overview');
  const statLabels = [
    ['用户', data.stats.users],
    ['活跃用户', data.stats.active_users],
    ['帖子', data.stats.threads],
    ['回复', data.stats.replies],
    ['待处理反馈', data.stats.feedback_open],
    ['待评估建议', data.stats.feature_open],
    ['总访问事件', data.stats.clicks],
    ['30 天访客', data.stats.visitors_30d],
    ['30 天 IP', data.stats.ips_30d],
    ['下载', data.stats.downloads],
  ];
  $('adminStats').innerHTML = statLabels.map(([label, value]) => `
    <div><dt>${escapeHtml(value)}</dt><dd>${escapeHtml(label)}</dd></div>
  `).join('');

  $('topPaths').innerHTML = table(
    ['路径', '事件', 'PV', '访客', '最后访问'],
    (data.top_paths || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.path)}</td>
        <td>${escapeHtml(item.events)}</td>
        <td>${escapeHtml(item.pageviews)}</td>
        <td>${escapeHtml(item.visitors)}</td>
        <td>${formatTime(item.last_seen)}</td>
      </tr>
    `),
  );

  const analytics = data.analytics || {};
  $('topIps').innerHTML = table(
    ['IP', '事件', 'PV', '路径数', '最近访问'],
    (analytics.top_ips || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.ip)}</td>
        <td>${escapeHtml(item.events)}</td>
        <td>${escapeHtml(item.pageviews)}</td>
        <td>${escapeHtml(item.path_count)}</td>
        <td>${formatTime(item.last_seen)}</td>
      </tr>
    `),
  );

  $('topReferrers').innerHTML = table(
    ['来源', '事件', '最近访问'],
    (analytics.top_referrers || []).map((item) => `
      <tr>
        <td>${escapeHtml(shortText(item.referrer, 90))}</td>
        <td>${escapeHtml(item.events)}</td>
        <td>${formatTime(item.last_seen)}</td>
      </tr>
    `),
  );

  $('dailyVisits').innerHTML = table(
    ['日期', 'PV', '访客', 'IP'],
    (analytics.daily || []).slice(-14).reverse().map((item) => `
      <tr>
        <td>${escapeHtml(item.day)}</td>
        <td>${escapeHtml(item.pageviews)}</td>
        <td>${escapeHtml(item.visitors)}</td>
        <td>${escapeHtml(item.unique_ips)}</td>
      </tr>
    `),
  );

  $('recentVisits').innerHTML = table(
    ['时间', 'IP', '路径', '事件', '来源'],
    (analytics.recent_events || []).slice(0, 14).map((item) => `
      <tr>
        <td>${formatTime(item.created_at)}</td>
        <td>${escapeHtml(item.ip || '-')}</td>
        <td>${escapeHtml(shortText(item.path, 70))}</td>
        <td>${escapeHtml(item.event || '-')}</td>
        <td>${escapeHtml(shortText(item.referrer || '直接访问', 70))}</td>
      </tr>
    `),
  );

  $('recentUsers').innerHTML = table(
    ['用户', '手机号', '状态', '注册时间'],
    (data.recent_users || []).map((item) => `
      <tr>
        <td>
          <div class="admin-user-cell compact">
            ${avatarHtml(item, 'avatar-badge-small')}
            <div>
              <strong>${escapeHtml(item.display_name)}</strong>
              <div class="admin-row-note">${escapeHtml(item.username || '-')}</div>
            </div>
          </div>
        </td>
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
        <td>
          <span class="author-inline">${avatarHtml({
            display_name: item.author_name,
            avatar_url: item.author_avatar_url,
          }, 'avatar-badge-tiny')}${escapeHtml(item.author_name)}</span>
        </td>
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
    ['ID', '用户', '手机号', '邮箱', '状态', '内容', '操作'],
    adminState.users.map((item) => {
      const quickStatus = item.status === 'active' ? 'suspended' : 'active';
      const quickLabel = item.status === 'active' ? '禁用' : '恢复';
      return `
        <tr>
          <td>${item.id}</td>
          <td>
            <div class="admin-user-cell">
              ${avatarHtml(item, 'avatar-badge-small')}
              <div>
                <strong>${escapeHtml(item.display_name)}</strong>
                <div class="admin-row-note">${escapeHtml(item.username || '-')}</div>
              </div>
            </div>
          </td>
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
  $('userAvatarUrl').value = safeAvatarUrl(item.avatar_url);
  renderUserAvatarPreview();
  $('userPassword').value = '';
  $('userUsername').focus();
}

function renderUserAvatarPreview() {
  const target = $('userAvatarPreview');
  if (!target) return;
  target.innerHTML = avatarHtml({
    display_name: $('userDisplayName')?.value || '',
    username: $('userUsername')?.value || '',
    avatar_color: $('userAvatarColor')?.value || '#1f6feb',
    avatar_url: $('userAvatarUrl')?.value || DEFAULT_AVATAR_URL,
  }, 'avatar-badge-large');
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
          <div class="admin-user-cell compact">
            ${avatarHtml({
              display_name: item.author_name,
              username: item.author_username,
              avatar_url: item.author_avatar_url,
            }, 'avatar-badge-small')}
            <div>
              <strong>${escapeHtml(item.author_name)}</strong>
              <div class="admin-row-note">${formatTime(item.last_activity_at)}</div>
            </div>
          </div>
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
        <span class="author-inline">${avatarHtml({
          display_name: reply.author_name,
          username: reply.author_username,
          avatar_url: reply.author_avatar_url,
          avatar_color: reply.author_color,
        }, 'avatar-badge-tiny')}#${reply.id} · ${escapeHtml(reply.author_name)}${reply.parent_id ? ` · 回复 #${reply.parent_id}` : ''}</span>
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

function clearFeedbackReplyFiles() {
  adminState.feedbackReplyPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  adminState.feedbackReplyFiles = [];
  adminState.feedbackReplyPreviewUrls = [];
}

function setFeedbackReplyFiles(files, options = {}) {
  const selected = validateImageFiles(files, '截图');
  if (!selected.length) return;
  const current = options.append === true ? adminState.feedbackReplyFiles : [];
  const capacity = MAX_FEEDBACK_REPLY_IMAGES - current.length;
  if (capacity <= 0) {
    toast(`单次回复最多上传 ${MAX_FEEDBACK_REPLY_IMAGES} 张截图`);
    return;
  }
  const kept = selected.slice(0, capacity);
  if (selected.length > capacity) {
    toast(`单次回复最多上传 ${MAX_FEEDBACK_REPLY_IMAGES} 张截图，已保留 ${capacity} 张`);
  }
  adminState.feedbackReplyFiles = [...current, ...kept];
  renderFeedbackReplyPreview();
}

function renderFeedbackReplyPreview() {
  const target = document.querySelector('[data-feedback-reply-preview]');
  if (!target) return;
  adminState.feedbackReplyPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  adminState.feedbackReplyPreviewUrls = adminState.feedbackReplyFiles.map((file) => URL.createObjectURL(file));
  target.innerHTML = adminState.feedbackReplyFiles.map((file, index) => `
    <figure class="reply-image-item">
      <button
        class="reply-image-preview-button"
        type="button"
        data-preview-feedback-reply-image="${index}"
        aria-label="查看截图：${escapeHtml(file.name)}"
      >
        <img src="${escapeHtml(adminState.feedbackReplyPreviewUrls[index])}" alt="${escapeHtml(file.name)}">
      </button>
      <figcaption>
        <span>${escapeHtml(file.name)}</span>
        <button class="icon-button" type="button" data-remove-feedback-reply-image="${index}" aria-label="移除截图">X</button>
      </figcaption>
    </figure>
  `).join('');
  target.classList.toggle('is-empty', !adminState.feedbackReplyFiles.length);
}

function renderAdminImageGrid(attachments = [], emptyText = '无截图') {
  if (!attachments.length) return `<div class="empty-state compact"><span>${emptyText}</span></div>`;
  return `
    <div class="admin-image-grid">
      ${attachments.map((attachment) => `
        <figure class="admin-image-card">
          <button
            type="button"
            data-open-admin-image="${escapeHtml(attachment.url || '')}"
            data-admin-image-name="${escapeHtml(attachment.file_name || '反馈图片')}"
            aria-label="查看图片：${escapeHtml(attachment.file_name || '反馈图片')}"
          >
            <img data-auth-image-src="${escapeHtml(attachment.url || '')}" alt="${escapeHtml(attachment.file_name || '反馈图片')}">
          </button>
          <figcaption>
            <span>${escapeHtml(attachment.file_name || '截图')}</span>
            <small>${formatSize(attachment.file_size)}</small>
          </figcaption>
        </figure>
      `).join('')}
    </div>
  `;
}

function renderFeedbackReplies(replies = []) {
  if (!replies.length) {
    return '<div class="empty-state compact"><span>暂无处理回复</span></div>';
  }
  return replies.map((reply) => {
    const isEditing = Number(adminState.editingFeedbackReplyId) === Number(reply.id);
    return `
      <article class="admin-reply-item">
        <div class="reply-author">
          <span>#${reply.id} · ${reply.author_role === 'admin' ? '管理员' : '用户'}</span>
          <span>${formatTime(reply.created_at)}</span>
        </div>
        ${isEditing ? `
          <form
            class="admin-inline-edit"
            data-feedback-reply-edit-form="${reply.id}"
            data-feedback-reply-has-attachments="${(reply.attachments || []).length ? '1' : '0'}"
          >
            <textarea name="body" rows="4" maxlength="5000">${escapeHtml(reply.body || '')}</textarea>
            <div class="reply-tool-row">
              <button class="primary-button" type="submit">保存修改</button>
              <button class="ghost-button" type="button" data-cancel-feedback-reply-edit>取消</button>
            </div>
          </form>
        ` : `${reply.body ? `<p>${escapeHtml(reply.body)}</p>` : '<p>[图片回复]</p>'}`}
        ${renderAdminImageGrid(reply.attachments || [], '无回复截图')}
        <div class="admin-reply-actions">
          <button class="ghost-button" type="button" data-edit-feedback-reply="${reply.id}">修改</button>
          <button class="danger-button" type="button" data-delete-feedback-reply="${reply.id}">删除</button>
        </div>
      </article>
    `;
  }).join('');
}

function renderFeedbackDetail(feedback) {
  const target = $('feedbackDetail');
  if (!target) return;
  adminState.feedbackDetail = feedback || null;
  const contact = feedback.user_phone || feedback.user_email || feedback.contact || '-';
  target.innerHTML = `
    <article class="feedback-detail-card">
      <div class="feedback-detail-head">
        <div>
          <span class="meta-line">#${feedback.id} · ${formatTime(feedback.created_at)}</span>
          <h3>${escapeHtml(feedback.title)}</h3>
        </div>
        <span class="status-pill ${statusClass(feedback.status)}">${escapeHtml(statusLabel(feedback.status, FEEDBACK_STATUS_LABELS))}</span>
      </div>
      <div class="feedback-detail-meta">
        <span>提交人：${escapeHtml(feedback.user_name || '匿名')}</span>
        <span>联系方式：${escapeHtml(contact)}</span>
        <span>公开状态：${feedback.is_public ? '公开' : '私有'}</span>
        <span>更新：${formatTime(feedback.updated_at)}</span>
      </div>
      <p class="feedback-detail-body">${escapeHtml(feedback.body)}</p>
      <div class="feedback-detail-actions">
        <label>
          <span>处理状态</span>
          <select data-feedback-detail-status="${feedback.id}">
            <option value="open" ${feedback.status === 'open' ? 'selected' : ''}>待处理</option>
            <option value="processing" ${feedback.status === 'processing' ? 'selected' : ''}>处理中</option>
            <option value="closed" ${feedback.status === 'closed' ? 'selected' : ''}>已关闭</option>
          </select>
        </label>
        <button class="ghost-button" type="button" data-toggle-feedback-public="${feedback.id}">
          ${feedback.is_public ? '隐藏反馈' : '公开反馈'}
        </button>
      </div>
    </article>

    <section class="feedback-detail-card">
      <div class="panel-head">
        <h3>反馈截图</h3>
      </div>
      ${renderAdminImageGrid(feedback.attachments || [], '这条反馈没有截图')}
    </section>

    <section class="feedback-detail-card">
      <div class="panel-head">
        <h3>处理回复</h3>
        <span class="meta-line">${(feedback.replies || []).length} 条</span>
      </div>
      <div class="admin-reply-list">
        ${renderFeedbackReplies(feedback.replies || [])}
      </div>
    </section>

    <form id="feedbackReplyForm" class="reply-form feedback-reply-form" data-feedback-reply-form>
      <label class="reply-editor-label">
        <span>新增处理回复</span>
        <div class="reply-editor-box">
          <textarea name="body" rows="5" placeholder="填写处理进度、解决方案或需要用户补充的信息；可直接 Ctrl+V 粘贴截图"></textarea>
          <div class="reply-image-preview is-empty" data-feedback-reply-preview></div>
        </div>
      </label>
      <div class="reply-tool-row">
        <label class="reply-image-picker" title="选择截图，或在回复框中粘贴图片">
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple data-feedback-reply-upload>
          <span>添加截图</span>
        </label>
        <button class="primary-button" type="submit">提交回复</button>
      </div>
    </form>
  `;
  renderFeedbackReplyPreview();
  hydrateAdminImages(target).catch(() => {});
}

function clearFeedbackDetail(message = '从左侧反馈列表选择一条记录') {
  adminState.selectedFeedbackId = 0;
  adminState.editingFeedbackReplyId = 0;
  adminState.feedbackDetail = null;
  clearFeedbackReplyFiles();
  const target = $('feedbackDetail');
  if (!target) return;
  target.innerHTML = `<div class="empty-state compact"><span>${message}</span></div>`;
}

async function loadFeedbackDetail(feedbackId) {
  const data = await api(`/api/admin/feedback/${feedbackId}`);
  adminState.selectedFeedbackId = Number(feedbackId);
  adminState.editingFeedbackReplyId = 0;
  renderFeedbackDetail(data.feedback);
  document.querySelectorAll('[data-feedback-row]').forEach((row) => {
    row.classList.toggle('is-active', Number(row.dataset.feedbackRow) === Number(feedbackId));
  });
}

async function loadFeedback() {
  const data = await api('/api/admin/feedback');
  revokeInlineImages();
  adminState.feedback = data.feedback || [];
  const target = $('feedbackTable');
  if (!target) return;
  if (!adminState.feedback.length) {
    target.innerHTML = '<div class="empty-state compact"><span>暂无反馈</span></div>';
    clearFeedbackDetail('暂无可处理反馈');
    return;
  }
  target.innerHTML = adminState.feedback.map((item) => `
    <article class="admin-feedback-item ${Number(item.id) === Number(adminState.selectedFeedbackId) ? 'is-active' : ''}" data-feedback-row="${item.id}" tabindex="0">
      <div class="admin-feedback-item-head">
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <span>#${item.id} · ${formatTime(item.created_at)}</span>
        </div>
        <span class="status-pill ${statusClass(item.status)}">${escapeHtml(statusLabel(item.status, FEEDBACK_STATUS_LABELS))}</span>
      </div>
      <p>${escapeHtml(shortText(item.body, 120))}</p>
      ${renderAdminImageGrid((item.attachments || []).slice(0, 4), '无截图')}
      <div class="feedback-list-meta">
        <span>${escapeHtml(item.user_name || '匿名')}</span>
        <span>${escapeHtml(item.user_phone || item.user_email || item.contact || '-')}</span>
        <span>${item.is_public ? '公开' : '私有'}</span>
        <span>${Number(item.reply_count || (item.replies || []).length || 0)} 条回复</span>
      </div>
      <div class="table-actions">
        <button class="ghost-button" type="button" data-open-feedback-detail="${item.id}">处理</button>
        <select data-feedback-status="${item.id}">
          <option value="open" ${item.status === 'open' ? 'selected' : ''}>待处理</option>
          <option value="processing" ${item.status === 'processing' ? 'selected' : ''}>处理中</option>
          <option value="closed" ${item.status === 'closed' ? 'selected' : ''}>已关闭</option>
        </select>
        <button class="ghost-button" type="button" data-toggle-feedback-public="${item.id}">
          ${item.is_public ? '隐藏' : '公开'}
        </button>
      </div>
    </article>
  `).join('');
  hydrateAdminImages(target).catch(() => {});
  if (adminState.selectedFeedbackId && adminState.feedback.some((item) => Number(item.id) === Number(adminState.selectedFeedbackId))) {
    await loadFeedbackDetail(adminState.selectedFeedbackId);
  } else {
    clearFeedbackDetail();
  }
}

async function loadFeatures() {
  const query = buildQuery({
    q: $('featureSearch').value,
    status: $('featureStatusFilter').value,
    module: $('featureModuleFilter').value,
  });
  const data = await api(`/api/admin/features${query}`);
  adminState.features = data.features || [];
  const statusOptions = Object.entries(FEATURE_STATUS_LABELS)
    .map(([value, label]) => ({ value, label }));
  $('featureTable').innerHTML = table(
    ['ID', '建议', '模块', '优先级', '状态', '票数', '提交人 / 来源', '更新时间', '操作'],
    adminState.features.map((item) => `
      <tr>
        <td>${escapeHtml(item.id)}</td>
        <td>
          <strong>${escapeHtml(item.title)}</strong>
          <div class="admin-row-note">${escapeHtml(shortText(item.body, 140))}</div>
          ${item.use_case ? `<div class="admin-row-note">场景：${escapeHtml(shortText(item.use_case, 120))}</div>` : ''}
        </td>
        <td>${escapeHtml(statusLabel(item.module, FEATURE_MODULE_LABELS))}</td>
        <td>${escapeHtml(statusLabel(item.priority, FEATURE_PRIORITY_LABELS))}</td>
        <td class="${statusClass(item.status)}">${escapeHtml(statusLabel(item.status, FEATURE_STATUS_LABELS))}</td>
        <td>${escapeHtml(item.vote_count || 0)}</td>
        <td>
          <strong>${escapeHtml(item.reporter || item.username || '匿名用户')}</strong>
          <div class="admin-row-note">${escapeHtml(item.user_phone || item.user_email || item.contact || '-')}</div>
          <div class="admin-row-note">IP：${escapeHtml(item.ip || '-')}</div>
        </td>
        <td>
          ${formatTime(item.updated_at)}
          <div class="admin-row-note">提交：${formatTime(item.created_at)}</div>
        </td>
        <td>
          <div class="table-actions">
            <select data-feature-status="${escapeHtml(item.id)}">
              ${statusOptions.map((option) => `
                <option value="${option.value}" ${item.status === option.value ? 'selected' : ''}>${option.label}</option>
              `).join('')}
            </select>
            <button class="danger-button" type="button" data-delete-feature="${escapeHtml(item.id)}">删除</button>
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

function emailStatusLabel(value) {
  return EMAIL_STATUS_LABELS[String(value || '').toLowerCase()] || value || '-';
}

function renderEmailSettings(settings = {}) {
  if (!$('emailSettingsForm')) return;
  $('emailEnabled').checked = Boolean(settings.enabled);
  $('emailSmtpHost').value = settings.smtp_host || '';
  $('emailSmtpPort').value = settings.smtp_port || (settings.smtp_security === 'ssl' ? 465 : 587);
  $('emailSmtpSecurity').value = settings.smtp_security || 'starttls';
  $('emailSmtpUsername').value = settings.smtp_username || '';
  $('emailSmtpPassword').value = '';
  $('emailSmtpPassword').placeholder = settings.has_password ? '已保存密码，留空不修改' : '请输入密码或授权码';
  $('emailClearPassword').checked = false;
  $('emailFromEmail').value = settings.from_email || '';
  $('emailFromName').value = settings.from_name || 'cfquant 官网';
  $('emailSettingsStatus').textContent = settings.enabled
    ? `已启用 · ${formatTime(settings.updated_at)}`
    : `未启用 · ${formatTime(settings.updated_at)}`;
}

function collectEmailSettings() {
  return {
    enabled: $('emailEnabled').checked,
    smtp_host: $('emailSmtpHost').value,
    smtp_port: $('emailSmtpPort').value,
    smtp_security: $('emailSmtpSecurity').value,
    smtp_username: $('emailSmtpUsername').value,
    smtp_password: $('emailSmtpPassword').value,
    clear_password: $('emailClearPassword').checked,
    from_email: $('emailFromEmail').value,
    from_name: $('emailFromName').value,
  };
}

function renderEmailUsers() {
  const select = $('emailUserSelect');
  if (!select) return;
  select.innerHTML = `
    <option value="">手动填写收件邮箱</option>
    ${adminState.emailUsers.map((user) => {
      const email = user.email || '';
      const unavailable = user.status !== 'active' || !email;
      const suffix = email || (user.status === 'active' ? '未填写邮箱' : statusLabel(user.status));
      return `
        <option value="${user.id}" data-email="${escapeHtml(email)}" ${unavailable ? 'disabled' : ''}>
          ${escapeHtml(user.display_name || user.username || `用户 ${user.id}`)} · ${escapeHtml(suffix)}
        </option>
      `;
    }).join('')}
  `;
}

function fillEmailRecipientFromUser() {
  const option = $('emailUserSelect').selectedOptions[0];
  $('emailRecipient').value = option?.dataset.email || '';
}

function renderEmailLogs() {
  $('emailLogTable').innerHTML = table(
    ['时间', '收件人', '用户', '标题', '状态', '错误'],
    adminState.emailLogs.map((item) => `
      <tr>
        <td>${formatTime(item.created_at)}</td>
        <td>${escapeHtml(item.recipient)}</td>
        <td>${escapeHtml(item.user_name || item.username || (item.user_id ? `#${item.user_id}` : '-'))}</td>
        <td>${escapeHtml(item.subject)}</td>
        <td class="email-status-${escapeHtml(item.status)}">${escapeHtml(emailStatusLabel(item.status))}</td>
        <td>${escapeHtml(item.error || '-')}</td>
      </tr>
    `),
  );
}

async function loadEmailLogs() {
  const data = await api('/api/admin/email/logs');
  adminState.emailLogs = data.logs || [];
  renderEmailLogs();
}

async function loadEmail() {
  const [settingsData, usersData, logsData] = await Promise.all([
    api('/api/admin/email/settings'),
    api('/api/admin/email/users'),
    api('/api/admin/email/logs'),
  ]);
  adminState.emailSettings = settingsData.settings || {};
  adminState.emailUsers = usersData.users || [];
  adminState.emailLogs = logsData.logs || [];
  renderEmailSettings(adminState.emailSettings);
  renderEmailUsers();
  renderEmailLogs();
}

async function updateFeedbackStatus(feedbackId, status) {
  await api(`/api/admin/feedback/${feedbackId}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
  await Promise.all([loadOverview(), loadFeedback()]);
  toast('反馈状态已更新');
}

async function updateFeatureStatus(featureId, status) {
  await api(`/api/admin/features/${featureId}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
  await Promise.all([loadOverview(), loadFeatures()]);
  toast('建议状态已更新');
}

async function toggleFeedbackPublic(feedbackId) {
  await api(`/api/admin/feedback/${feedbackId}/public`, {
    method: 'POST',
    body: '{}',
  });
  await Promise.all([loadOverview(), loadFeedback()]);
  toast('反馈公开状态已更新');
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

  $('closeAdminImageModal').addEventListener('click', hideAdminImageModal);
  $('adminImageModal').addEventListener('click', (event) => {
    if (event.target === $('adminImageModal')) hideAdminImageModal();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (!$('adminImageModal').classList.contains('hidden')) {
      hideAdminImageModal();
    }
  });

  document.addEventListener('error', (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    const avatar = image.closest('.avatar-badge');
    if (avatar) avatar.classList.add('is-fallback');
  }, true);

  document.querySelectorAll('[data-admin-section]').forEach((button) => {
    button.addEventListener('click', () => setSection(button.dataset.adminSection));
  });

  $('userFilterForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    await loadUsers().catch((error) => toast(error.message));
  });

  ['userDisplayName', 'userUsername', 'userAvatarColor', 'userAvatarUrl'].forEach((id) => {
    $(id)?.addEventListener('input', renderUserAvatarPreview);
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
      avatar_url: $('userAvatarUrl').value,
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

  $('featureFilterForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    await loadFeatures().catch((error) => toast(error.message));
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

  $('featureTable').addEventListener('change', async (event) => {
    const select = event.target.closest('[data-feature-status]');
    if (!select) return;
    try {
      await updateFeatureStatus(select.dataset.featureStatus, select.value);
    } catch (error) {
      toast(error.message);
    }
  });

  $('featureTable').addEventListener('click', async (event) => {
    const deleteButton = event.target.closest('[data-delete-feature]');
    if (!deleteButton) return;
    if (!confirm('确认删除这条功能建议？该操作不可撤销。')) return;
    try {
      await api(`/api/admin/features/${deleteButton.dataset.deleteFeature}/delete`, {
        method: 'POST',
        body: '{}',
      });
      await Promise.all([loadOverview(), loadFeatures()]);
      toast('功能建议已删除');
    } catch (error) {
      toast(error.message);
    }
  });

  $('feedbackTable').addEventListener('change', async (event) => {
    const select = event.target.closest('[data-feedback-status]');
    if (!select) return;
    try {
      await updateFeedbackStatus(select.dataset.feedbackStatus, select.value);
    } catch (error) {
      toast(error.message);
    }
  });

  $('feedbackTable').addEventListener('click', async (event) => {
    const imageButton = event.target.closest('[data-open-admin-image]');
    if (imageButton) {
      try {
        await openAdminImage(imageButton.dataset.openAdminImage, imageButton.dataset.adminImageName);
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const toggleButton = event.target.closest('[data-toggle-feedback-public]');
    if (toggleButton) {
      try {
        await toggleFeedbackPublic(toggleButton.dataset.toggleFeedbackPublic);
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const detailButton = event.target.closest('[data-open-feedback-detail]');
    if (detailButton) {
      await loadFeedbackDetail(detailButton.dataset.openFeedbackDetail).catch((error) => toast(error.message));
      return;
    }
    const row = event.target.closest('[data-feedback-row]');
    if (!row || event.target.closest('button, select, input, textarea, label, a')) return;
    await loadFeedbackDetail(row.dataset.feedbackRow).catch((error) => toast(error.message));
  });

  $('feedbackTable').addEventListener('keydown', async (event) => {
    if (!['Enter', ' '].includes(event.key)) return;
    const row = event.target.closest('[data-feedback-row]');
    if (!row) return;
    event.preventDefault();
    await loadFeedbackDetail(row.dataset.feedbackRow).catch((error) => toast(error.message));
  });

  $('feedbackDetail').addEventListener('change', async (event) => {
    const statusSelect = event.target.closest('[data-feedback-detail-status]');
    if (statusSelect) {
      try {
        await updateFeedbackStatus(statusSelect.dataset.feedbackDetailStatus, statusSelect.value);
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const fileInput = event.target.closest('[data-feedback-reply-upload]');
    if (!fileInput) return;
    setFeedbackReplyFiles(fileInput.files, { append: true });
    fileInput.value = '';
  });

  $('feedbackDetail').addEventListener('click', async (event) => {
    const editReplyButton = event.target.closest('[data-edit-feedback-reply]');
    if (editReplyButton) {
      adminState.editingFeedbackReplyId = Number(editReplyButton.dataset.editFeedbackReply || 0);
      if (adminState.feedbackDetail) renderFeedbackDetail(adminState.feedbackDetail);
      const editForm = document.querySelector(`[data-feedback-reply-edit-form="${adminState.editingFeedbackReplyId}"]`);
      editForm?.elements.body?.focus();
      return;
    }
    if (event.target.closest('[data-cancel-feedback-reply-edit]')) {
      adminState.editingFeedbackReplyId = 0;
      if (adminState.feedbackDetail) renderFeedbackDetail(adminState.feedbackDetail);
      return;
    }
    const deleteReplyButton = event.target.closest('[data-delete-feedback-reply]');
    if (deleteReplyButton) {
      if (!confirm('确认删除这条处理回复？')) return;
      try {
        await api(`/api/admin/feedback/replies/${deleteReplyButton.dataset.deleteFeedbackReply}/delete`, {
          method: 'POST',
          body: '{}',
        });
        adminState.editingFeedbackReplyId = 0;
        await Promise.all([loadOverview(), loadFeedback()]);
        toast('处理回复已删除');
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const imageButton = event.target.closest('[data-open-admin-image]');
    if (imageButton) {
      try {
        await openAdminImage(imageButton.dataset.openAdminImage, imageButton.dataset.adminImageName);
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const toggleButton = event.target.closest('[data-toggle-feedback-public]');
    if (toggleButton) {
      try {
        await toggleFeedbackPublic(toggleButton.dataset.toggleFeedbackPublic);
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const removeButton = event.target.closest('[data-remove-feedback-reply-image]');
    if (removeButton) {
      adminState.feedbackReplyFiles.splice(Number(removeButton.dataset.removeFeedbackReplyImage), 1);
      renderFeedbackReplyPreview();
      return;
    }
    const previewButton = event.target.closest('[data-preview-feedback-reply-image]');
    if (previewButton) {
      const index = Number(previewButton.dataset.previewFeedbackReplyImage);
      const url = adminState.feedbackReplyPreviewUrls[index];
      const file = adminState.feedbackReplyFiles[index];
      if (url) {
        if (adminState.imageModalObjectUrl) URL.revokeObjectURL(adminState.imageModalObjectUrl);
        adminState.imageModalObjectUrl = '';
        $('adminImageModalTitle').textContent = file?.name || '回复截图';
        $('adminImageModalImage').src = url;
        $('adminImageModalImage').alt = file?.name || '回复截图';
        $('adminImageModal').classList.remove('hidden');
      }
    }
  });

  $('feedbackDetail').addEventListener('submit', async (event) => {
    const editForm = event.target.closest('[data-feedback-reply-edit-form]');
    if (editForm) {
      event.preventDefault();
      const replyId = editForm.dataset.feedbackReplyEditForm;
      const body = editForm.elements.body.value;
      const hasAttachments = editForm.dataset.feedbackReplyHasAttachments === '1';
      if (body.trim().length < 2 && !hasAttachments) {
        toast('回复内容不能少于 2 个字');
        editForm.elements.body.focus();
        return;
      }
      try {
        await api(`/api/admin/feedback/replies/${replyId}`, {
          method: 'POST',
          body: JSON.stringify({ body }),
        });
        adminState.editingFeedbackReplyId = 0;
        await Promise.all([loadOverview(), loadFeedback()]);
        toast('处理回复已保存');
      } catch (error) {
        toast(error.message);
      }
      return;
    }
    const form = event.target.closest('[data-feedback-reply-form]');
    if (!form) return;
    event.preventDefault();
    const body = form.elements.body.value;
    const files = adminState.feedbackReplyFiles;
    if (body.trim().length < 2 && !files.length) {
      toast('回复内容不能为空');
      return;
    }
    try {
      const attachments = await Promise.all(files.map(fileToAttachment));
      await api(`/api/admin/feedback/${adminState.selectedFeedbackId}/replies`, {
        method: 'POST',
        body: JSON.stringify({ body, attachments }),
      });
      form.reset();
      clearFeedbackReplyFiles();
      await Promise.all([loadOverview(), loadFeedback()]);
      toast('反馈回复已提交');
    } catch (error) {
      toast(error.message);
    }
  });

  document.addEventListener('paste', handleAdminFeedbackReplyPaste);

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

  $('emailSettingsForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = collectEmailSettings();
    if (payload.enabled && !isValidEmail(payload.from_email)) {
      toast('发件邮箱格式不正确');
      $('emailFromEmail').focus();
      return;
    }
    try {
      const data = await api('/api/admin/email/settings', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      adminState.emailSettings = data.settings || {};
      renderEmailSettings(adminState.emailSettings);
      toast('邮件服务配置已保存');
    } catch (error) {
      toast(error.message);
    }
  });

  $('emailTestButton').addEventListener('click', async () => {
    const recipient = $('emailTestRecipient').value.trim().toLowerCase();
    if (!isValidEmail(recipient)) {
      toast('请填写有效的测试收件邮箱');
      $('emailTestRecipient').focus();
      return;
    }
    try {
      await api('/api/admin/email/test', {
        method: 'POST',
        body: JSON.stringify({ recipient }),
      });
      await loadEmailLogs();
      toast('测试邮件已发送');
    } catch (error) {
      await loadEmailLogs().catch(() => {});
      toast(error.message);
    }
  });

  $('emailUserSelect').addEventListener('change', fillEmailRecipientFromUser);

  $('refreshEmailLogs').addEventListener('click', () => {
    loadEmailLogs().catch((error) => toast(error.message));
  });

  $('emailSendForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const recipient = $('emailRecipient').value.trim().toLowerCase();
    if (!isValidEmail(recipient)) {
      toast('请填写有效的收件邮箱');
      $('emailRecipient').focus();
      return;
    }
    try {
      await api('/api/admin/email/send', {
        method: 'POST',
        body: JSON.stringify({
          user_id: $('emailUserSelect').value,
          recipient,
          subject: $('emailSubject').value,
          body: $('emailBody').value,
        }),
      });
      $('emailSendForm').reset();
      await loadEmailLogs();
      toast('邮件已发送');
    } catch (error) {
      await loadEmailLogs().catch(() => {});
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
  clearFeedbackDetail();
  if (adminState.token) {
    try {
      setSection('overview');
    } catch (error) {
      toast(error.message);
    }
  }
}

init();
