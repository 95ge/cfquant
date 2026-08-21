const SITE_TOKEN_KEY = 'cfquant_site_token';
const SITE_USER_KEY = 'cfquant_site_user';

function readStoredUser() {
  try {
    const user = JSON.parse(localStorage.getItem(SITE_USER_KEY) || 'null');
    return user && typeof user === 'object' ? user : null;
  } catch (_error) {
    localStorage.removeItem(SITE_USER_KEY);
    return null;
  }
}

const state = {
  token: localStorage.getItem(SITE_TOKEN_KEY) || '',
  user: readStoredUser(),
  categories: [],
  activeCategory: '',
  selectedThreadId: null,
  currentThread: null,
  currentReplies: [],
  expandedReplyIds: new Set(),
  replyComposeParentId: null,
  replyFiles: {},
  replyPreviewUrls: {},
  imageModalObjectUrl: '',
  authMode: 'register',
  feedbackFiles: [],
  feedbackPreviewUrls: [],
  projectSlide: 0,
  projectTimer: null,
  projectPaused: false,
};

const $ = (id) => document.getElementById(id);
const CONFIG = window.CFQUANT_SITE_CONFIG || {};
const API_BASE = String(CONFIG.apiBase || '').replace(/\/$/, '');
const LOGIN_MEMORY_KEY = 'cfquant_site_login_memory';
const MAX_REPLY_IMAGES = 10;

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

function excerpt(value, max = 150) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max)}...`;
}

function formatSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return '-';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
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

function validateImageFiles(files, label = '图片') {
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

function validateFeedbackFiles(files) {
  return validateImageFiles(files, '截图');
}

function setFeedbackFiles(files, options = {}) {
  const selected = validateFeedbackFiles(files);
  if (!selected.length) return;
  const append = options.append === true;
  const current = append ? state.feedbackFiles : [];
  const capacity = 4 - current.length;
  if (capacity <= 0) {
    toast('最多上传 4 张截图');
    return;
  }
  const kept = selected.slice(0, capacity);
  if (selected.length > capacity) {
    toast(`最多上传 4 张截图，已保留 ${capacity} 张`);
  }
  state.feedbackFiles = [...current, ...kept];
  renderFeedbackPreview();
}

function revokeFeedbackPreviewUrls() {
  state.feedbackPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  state.feedbackPreviewUrls = [];
}

function renderFeedbackPreview() {
  const target = $('feedbackPreview');
  if (!target) return;
  revokeFeedbackPreviewUrls();
  state.feedbackPreviewUrls = state.feedbackFiles.map((file) => URL.createObjectURL(file));
  target.innerHTML = state.feedbackFiles.map((file, index) => `
    <figure class="screenshot-item">
      <img src="${escapeHtml(state.feedbackPreviewUrls[index])}" alt="${escapeHtml(file.name)}">
      <figcaption>
        <span>${escapeHtml(file.name)}</span>
        <button class="icon-button" type="button" data-remove-screenshot="${index}" aria-label="移除截图">X</button>
      </figcaption>
    </figure>
  `).join('');
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

function handleFeedbackPaste(event) {
  const view = $('view-feedback');
  if (!view || !view.classList.contains('is-active')) return;
  const files = pastedImageFiles(event);
  if (!files.length) return;
  event.preventDefault();
  setFeedbackFiles(files, { append: true });
  const hint = $('feedbackDropHint');
  if (!hint) return;
  hint.classList.add('is-active');
  clearTimeout(handleFeedbackPaste.timer);
  handleFeedbackPaste.timer = setTimeout(() => hint.classList.remove('is-active'), 1200);
}

function replyKey(parentId = null) {
  return parentId ? String(parentId) : 'root';
}

function replyFiles(parentId = null) {
  return state.replyFiles[replyKey(parentId)] || [];
}

function revokeReplyPreviewUrls(key) {
  (state.replyPreviewUrls[key] || []).forEach((url) => URL.revokeObjectURL(url));
  state.replyPreviewUrls[key] = [];
}

function renderReplyImagePreview(parentId = null) {
  const key = replyKey(parentId);
  const files = replyFiles(parentId);
  revokeReplyPreviewUrls(key);
  state.replyPreviewUrls[key] = files.map((file) => URL.createObjectURL(file));
  return files.map((file, index) => `
    <figure class="reply-image-item">
      <button
        class="reply-image-preview-button"
        type="button"
        data-preview-reply-image="${index}"
        aria-label="查看图片：${escapeHtml(file.name)}"
      >
        <img src="${escapeHtml(state.replyPreviewUrls[key][index])}" alt="${escapeHtml(file.name)}">
      </button>
      <figcaption>
        <span>${escapeHtml(file.name)}</span>
        <button class="icon-button" type="button" data-remove-reply-image="${index}" aria-label="移除图片">X</button>
      </figcaption>
    </figure>
  `).join('');
}

function updateReplyImagePreview(parentId = null) {
  const key = replyKey(parentId);
  const target = document.querySelector(`[data-reply-preview="${key}"]`);
  if (!target) return;
  target.innerHTML = renderReplyImagePreview(parentId);
  target.classList.toggle('is-empty', !replyFiles(parentId).length);
}

function setReplyFiles(parentId, files, options = {}) {
  const selected = validateImageFiles(files, '图片');
  if (!selected.length) return;
  const key = replyKey(parentId);
  const append = options.append === true;
  const current = append ? replyFiles(parentId) : [];
  const capacity = MAX_REPLY_IMAGES - current.length;
  if (capacity <= 0) {
    toast(`单次回复最多上传 ${MAX_REPLY_IMAGES} 张图片`);
    return;
  }
  const kept = selected.slice(0, capacity);
  if (selected.length > capacity) {
    toast(`单次回复最多上传 ${MAX_REPLY_IMAGES} 张图片，已保留 ${capacity} 张`);
  }
  state.replyFiles[key] = [...current, ...kept];
  updateReplyImagePreview(parentId);
}

function clearReplyFiles(parentId = null) {
  const key = replyKey(parentId);
  revokeReplyPreviewUrls(key);
  delete state.replyFiles[key];
  delete state.replyPreviewUrls[key];
}

function clearAllReplyFiles() {
  Object.keys(state.replyPreviewUrls).forEach(revokeReplyPreviewUrls);
  state.replyFiles = {};
  state.replyPreviewUrls = {};
}

function parentIdFromReplyForm(form) {
  const value = form?.dataset.parentId || '';
  return value ? Number(value) : null;
}

function handleReplyPaste(event) {
  const view = $('view-thread');
  if (!view || !view.classList.contains('is-active')) return;
  const target = event.target instanceof Element ? event.target : null;
  const form = target?.closest('[data-reply-form]') || document.querySelector('[data-reply-form]:focus-within');
  if (!form) return;
  const files = pastedImageFiles(event);
  if (!files.length) return;
  event.preventDefault();
  setReplyFiles(parentIdFromReplyForm(form), files, { append: true });
}

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  return headers;
}

async function api(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    if (response.status === 401 && state.token) {
      clearSession();
      updateAuthUi();
    }
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.classList.remove('hidden');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.add('hidden'), 2600);
}

function track(event, target = '') {
  api('/api/track', {
    method: 'POST',
    body: JSON.stringify({
      event,
      target,
      path: `${location.pathname}${location.hash || ''}`,
    }),
  }).catch(() => {});
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('cfquant_site_theme', theme);
  $('themeToggle').querySelector('.theme-icon').textContent = theme === 'dark' ? 'L' : 'D';
}

function initTheme() {
  const saved = localStorage.getItem('cfquant_site_theme');
  const preferred = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  setTheme(saved || preferred);
}

function emptyLoginMemory() {
  return { account: '', remember: true };
}

function encodeLoginMemory(value) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(value))));
}

function decodeLoginMemory(value) {
  return JSON.parse(decodeURIComponent(escape(atob(value))));
}

function readLoginMemory() {
  const raw = localStorage.getItem(LOGIN_MEMORY_KEY);
  if (!raw) return emptyLoginMemory();
  try {
    const data = decodeLoginMemory(raw);
    const memory = {
      account: String(data.account || ''),
      remember: data.remember !== false,
    };
    if (data.password || Object.prototype.hasOwnProperty.call(data, 'autoLogin')) {
      writeLoginMemory(memory);
    }
    return memory;
  } catch (_error) {
    localStorage.removeItem(LOGIN_MEMORY_KEY);
    return emptyLoginMemory();
  }
}

function writeLoginMemory(data) {
  if (!data.remember) {
    localStorage.removeItem(LOGIN_MEMORY_KEY);
    return;
  }
  localStorage.setItem(LOGIN_MEMORY_KEY, encodeLoginMemory({
    account: String(data.account || '').trim(),
    remember: true,
  }));
}

function fillLoginFormFromMemory() {
  const accountInput = $('loginAccount');
  const passwordInput = $('loginPassword');
  const rememberInput = $('loginRemember');
  const autoLoginInput = $('loginAutoLogin');
  if (!accountInput || !passwordInput || !rememberInput || !autoLoginInput) return;
  const memory = readLoginMemory();
  if (memory.account && !accountInput.value) accountInput.value = memory.account;
  rememberInput.checked = memory.remember;
  autoLoginInput.checked = true;
  autoLoginInput.disabled = true;
}

function saveLoginMemoryFromForm() {
  const rememberInput = $('loginRemember');
  const autoLoginInput = $('loginAutoLogin');
  if (!rememberInput || !autoLoginInput) return;
  writeLoginMemory({
    account: $('loginAccount').value,
    remember: rememberInput.checked,
  });
}

function disableRememberedAutoLogin() {
  fillLoginFormFromMemory();
}

function bindLoginMemoryControls() {
  fillLoginFormFromMemory();
  $('loginRemember').addEventListener('change', () => {
    $('loginAutoLogin').checked = true;
    $('loginAutoLogin').disabled = true;
    saveLoginMemoryFromForm();
  });
  $('loginAutoLogin').addEventListener('change', saveLoginMemoryFromForm);
}

function switchView(view, options = {}) {
  const navView = view === 'thread' ? 'forum' : view;
  document.querySelector('.site-shell')?.classList.toggle('project-mode', view === 'project');
  document.querySelectorAll('.nav-tab').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.view === navView);
  });
  document.querySelectorAll('.view').forEach((section) => {
    section.classList.toggle('is-active', section.id === `view-${view}`);
  });
  if (!options.skipHash) {
    location.hash = options.hash || view;
  }
  track('nav', options.hash || view);
  if (view === 'downloads') loadDownloads();
  if (view === 'center') renderCenter();
  if (view === 'forum') loadThreads();
  if (view === 'feedback') loadFeedbackPanels().catch((error) => toast(error.message));
  if (view === 'project') startProjectCarousel();
  if (view !== 'project') stopProjectCarousel();
  if (view !== 'project') loadPublic().catch((error) => toast(error.message));
}

async function loadPublic() {
  const data = await api('/api/public');
  $('statUsers').textContent = data.stats.users;
  $('statThreads').textContent = data.stats.threads;
  $('statReplies').textContent = data.stats.replies;
  $('statDownloads').textContent = data.stats.downloads;
  $('hotThreads').innerHTML = (data.hot_threads || []).map((thread) => `
    <div class="compact-item">
      <button type="button" data-hot-thread="${thread.id}">${escapeHtml(thread.title)}</button>
      <span>${escapeHtml(thread.category_name || '')} · ${thread.reply_count} 回复 · ${thread.views} 浏览</span>
    </div>
  `).join('') || '<div class="empty-state"><span>暂无讨论</span></div>';
}

async function loadCategories() {
  const data = await api('/api/forum/categories');
  state.categories = data.categories || [];
  const tabs = [
    `<button type="button" class="${state.activeCategory ? '' : 'is-active'}" data-category="">全部</button>`,
    ...state.categories.map((item) => `
      <button type="button" class="${state.activeCategory === item.slug ? 'is-active' : ''}" data-category="${escapeHtml(item.slug)}">${escapeHtml(item.name)}</button>
    `),
  ];
  $('categoryTabs').innerHTML = tabs.join('');
  $('threadCategory').innerHTML = state.categories.map((item) => `
    <option value="${escapeHtml(item.slug)}">${escapeHtml(item.name)}</option>
  `).join('');
}

async function loadThreads() {
  const params = new URLSearchParams();
  if (state.activeCategory) params.set('category', state.activeCategory);
  const q = $('threadSearch').value.trim();
  if (q) params.set('q', q);
  const data = await api(`/api/forum/threads?${params.toString()}`);
  renderThreads(data.threads || []);
}

function renderThreads(threads) {
  if (!threads.length) {
    $('threadList').innerHTML = '<div class="empty-state"><strong>暂无匹配讨论</strong><span>换个关键词或发起新问题。</span></div>';
    return;
  }
  $('threadList').innerHTML = threads.map((thread) => {
    const tags = String(thread.tags || '').split(',').map((tag) => tag.trim()).filter(Boolean);
    return `
      <article class="thread-card" role="button" tabindex="0" data-thread-id="${thread.id}" aria-label="进入讨论：${escapeHtml(thread.title)}">
        <h2>${escapeHtml(thread.title)}</h2>
        <p>${escapeHtml(excerpt(thread.body))}</p>
        <div class="tag-line">
          <span class="status-pill ${thread.status === 'locked' ? 'locked' : ''}">${thread.status === 'locked' ? '已锁定' : '开放'}</span>
          ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
        </div>
        <div class="meta-line">
          <span>${escapeHtml(thread.category_name || '')}</span>
          <span>${escapeHtml(thread.author_name || '')}</span>
          <span>${thread.reply_count} 回复</span>
          <span>${thread.views} 浏览</span>
          <span>${formatTime(thread.last_activity_at)}</span>
        </div>
      </article>
    `;
  }).join('');
}

async function openThread(threadId, options = {}) {
  const changedThread = String(state.selectedThreadId || '') !== String(threadId);
  state.selectedThreadId = threadId;
  if (changedThread) {
    state.expandedReplyIds.clear();
    state.replyComposeParentId = null;
    clearAllReplyFiles();
  }
  const data = await api(`/api/forum/threads/${threadId}`);
  const thread = data.thread;
  const replies = data.replies || [];
  state.currentThread = thread;
  state.currentReplies = replies;
  renderThreadPage(thread, replies);
  switchView('thread', { hash: `thread-${threadId}` });
  if (!options.skipTrack) track('thread_open', String(threadId));
}

function renderThreadPage(thread, replies) {
  const tags = String(thread.tags || '').split(',').map((tag) => tag.trim()).filter(Boolean);
  const { roots, childrenByParent } = groupReplies(replies);
  $('threadPageContent').innerHTML = `
    <article class="thread-article">
      <div class="detail-head">
        <p class="eyebrow">${escapeHtml(thread.category_name || 'Forum')}</p>
        <h2>${escapeHtml(thread.title)}</h2>
        <div class="meta-line">
          <span><i class="avatar-dot" style="background:${escapeHtml(thread.author_color || '#1f6feb')}"></i>${escapeHtml(thread.author_name || '')}</span>
          <span>${formatTime(thread.created_at)}</span>
          <span>${thread.views} 浏览</span>
          <span>${replies.length} 回复</span>
        </div>
        <div class="tag-line">
          <span class="status-pill ${thread.status === 'locked' ? 'locked' : ''}">${thread.status === 'locked' ? '已锁定' : '开放'}</span>
          ${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
        </div>
      </div>
      <div class="detail-body">${escapeHtml(thread.body)}</div>
    </article>
    <section class="conversation-card">
      <div class="panel-head">
        <h3>交流回复</h3>
        <span class="meta-line">${replies.length} 条回复</span>
      </div>
      <div class="reply-list">
        ${roots.map((reply) => renderReplyThread(reply, childrenByParent.get(Number(reply.id)) || [], thread)).join('') || '<div class="empty-state"><span>还没有回复</span></div>'}
      </div>
      ${renderReplyForm(thread)}
    </section>
  `;
}

function groupReplies(replies) {
  const byId = new Map(replies.map((reply) => [Number(reply.id), reply]));
  const roots = [];
  const childrenByParent = new Map();
  replies.forEach((reply) => {
    const parentId = Number(reply.parent_id || 0);
    if (!parentId || !byId.has(parentId)) {
      roots.push(reply);
      return;
    }
    const parent = byId.get(parentId);
    const rootId = Number(parent.parent_id || parentId);
    if (!childrenByParent.has(rootId)) childrenByParent.set(rootId, []);
    childrenByParent.get(rootId).push(reply);
  });
  return { roots, childrenByParent };
}

function renderReplyAttachments(attachments = []) {
  if (!attachments.length) return '';
  return `
    <div class="reply-attachments">
      ${attachments.map((attachment) => `
        <button
          class="reply-image-thumb"
          type="button"
          data-reply-attachment-url="${escapeHtml(attachment.url || '')}"
          data-reply-attachment-name="${escapeHtml(attachment.file_name || '回复图片')}"
          aria-label="查看图片：${escapeHtml(attachment.file_name || '回复图片')}"
        >
          <img src="${escapeHtml(apiUrl(attachment.url || ''))}" alt="${escapeHtml(attachment.file_name || '回复图片')}">
        </button>
      `).join('')}
    </div>
  `;
}

function renderReplyBody(reply) {
  return `
    <div class="reply-author">
      <span><i class="avatar-dot" style="background:${escapeHtml(reply.author_color || '#1f6feb')}"></i>${escapeHtml(reply.author_name || '')}</span>
      <span>${formatTime(reply.created_at)}</span>
    </div>
    ${reply.body ? `<div class="reply-body">${escapeHtml(reply.body)}</div>` : ''}
    ${renderReplyAttachments(reply.attachments || [])}
  `;
}

function renderReplyActions(reply, thread) {
  if (thread.status === 'locked') return '';
  return `
    <div class="reply-actions">
      <button class="reply-link-button" type="button" data-reply-parent-id="${reply.id}">回复</button>
    </div>
  `;
}

function renderChildReply(reply, thread) {
  const parentId = Number(reply.id);
  return `
    <article class="reply-item reply-child" data-reply-id="${parentId}">
      ${renderReplyBody(reply)}
      ${renderReplyActions(reply, thread)}
      ${state.replyComposeParentId === parentId ? renderReplyForm(thread, parentId) : ''}
    </article>
  `;
}

function renderReplyThread(reply, children, thread) {
  const replyId = Number(reply.id);
  const expanded = state.expandedReplyIds.has(replyId);
  return `
    <article class="reply-item reply-root" data-reply-id="${replyId}">
      ${renderReplyBody(reply)}
      ${renderReplyActions(reply, thread)}
      ${state.replyComposeParentId === replyId ? renderReplyForm(thread, replyId) : ''}
      ${children.length ? `
        <button class="reply-expand" type="button" data-toggle-replies="${replyId}" data-child-count="${children.length}">
          ${expanded ? '收起回复' : `展开 ${children.length} 条回复`}
        </button>
        <div class="child-replies ${expanded ? '' : 'hidden'}" data-child-replies="${replyId}">
          ${children.map((child) => renderChildReply(child, thread)).join('')}
        </div>
      ` : ''}
    </article>
  `;
}

function renderReplyForm(thread, parentId = null) {
  if (thread.status === 'locked') {
    return '<div class="empty-state"><span>帖子已锁定，暂不能继续回复。</span></div>';
  }
  if (!state.user) {
    return '<button class="primary-button full" type="button" data-open-auth>登录后回复</button>';
  }
  const key = replyKey(parentId);
  const childClass = parentId ? ' is-child-form' : '';
  const previewClass = replyFiles(parentId).length ? '' : ' is-empty';
  return `
    <form class="reply-form${childClass}" data-reply-form data-parent-id="${parentId || ''}">
      <label class="reply-editor-label">
        <span>${parentId ? '回复这条讨论' : '回复内容'}</span>
        <div class="reply-editor-box">
          <textarea name="body" rows="${parentId ? 3 : 4}"></textarea>
          <div class="reply-image-preview${previewClass}" data-reply-preview="${key}">
            ${renderReplyImagePreview(parentId)}
          </div>
        </div>
      </label>
      <div class="reply-tool-row">
        <label class="reply-image-picker" title="选择图片，或在回复框中粘贴图片">
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple data-reply-upload>
          <span>图片</span>
        </label>
        ${parentId ? '<button class="ghost-button" type="button" data-cancel-reply>取消</button>' : ''}
        <button class="primary-button" type="submit">提交回复</button>
      </div>
    </form>
  `;
}

async function loadDownloads() {
  const [data, releaseResult] = await Promise.all([
    api('/api/downloads'),
    api('/api/releases/latest').catch((error) => ({ error: error.message })),
  ]);
  renderLatestRelease(releaseResult && releaseResult.release ? releaseResult.release : null, releaseResult && releaseResult.error);
  const downloads = data.downloads || [];
  $('downloadList').innerHTML = downloads.map((item) => `
    <article class="download-card">
      <div>
        <span class="tag">${escapeHtml(item.channel || 'stable')}</span>
      </div>
      <h2>${escapeHtml(item.title)}</h2>
      <p>核心：${escapeHtml(item.core_version || item.version)}${item.web_version ? ` · Web：${escapeHtml(item.web_version)}` : ''} · 大小：${formatSize(item.file_size)} · 下载次数：${item.download_count}</p>
      <p>${escapeHtml(item.notes || '')}</p>
      ${item.sha256 ? `<code class="hash-line" title="${escapeHtml(item.sha256)}">SHA256 ${escapeHtml(item.sha256.slice(0, 16))}...</code>` : ''}
      <div class="form-actions">
        <a class="primary-button" href="${escapeHtml(apiUrl(`/api/downloads/${item.id}/download`))}" data-download-id="${item.id}">下载</a>
        ${item.external_url ? `<a class="ghost-button" href="${escapeHtml(item.external_url)}" target="_blank" rel="noreferrer">外部链接</a>` : ''}
      </div>
    </article>
  `).join('') || '<div class="empty-state"><strong>暂无更新包</strong><span>管理员可在后台登记本地包或镜像链接。</span></div>';
}

function renderLatestRelease(release, error = '') {
  const panel = $('releasePanel');
  if (!panel) return;
  if (!release) {
    panel.innerHTML = `
      <article class="release-card release-placeholder">
        <div class="release-main">
          <span class="tag">fallback</span>
          <h2>官网镜像包待登记</h2>
          <p>后台登记 official_site/packages 里的 zip 后，这里会显示版本、大小、SHA256 和更新日志。</p>
          ${error ? `<p class="meta-line">${escapeHtml(error)}</p>` : ''}
        </div>
        <div class="release-actions">
          <a class="ghost-button" href="https://github.com/95ge/cfquant" target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </article>`;
    return;
  }
  const changelog = release.changelog || {};
  const items = Array.isArray(changelog.items) ? changelog.items : [];
  panel.innerHTML = `
    <article class="release-card">
      <div class="release-main">
        <span class="tag">${escapeHtml(release.channel || 'project')}</span>
        <h2>${escapeHtml(release.title || 'cfquant 项目包')}</h2>
        <div class="release-meta">
          <span>核心 ${escapeHtml(release.core_version || release.version || '--')}</span>
          ${release.web_version ? `<span>Web ${escapeHtml(release.web_version)}</span>` : ''}
          <span>大小 ${formatSize(release.file_size)}</span>
          <span>更新 ${escapeHtml(formatTime(release.updated_at))}</span>
          <span>下载 ${Number(release.download_count || 0)}</span>
        </div>
        ${release.sha256 ? `<code class="hash-line" title="${escapeHtml(release.sha256)}">SHA256 ${escapeHtml(release.sha256)}</code>` : ''}
      </div>
      <div class="release-actions">
        <a class="primary-button" href="${escapeHtml(apiUrl('/api/releases/latest/download'))}" data-download-id="${release.id || 'latest'}">下载最新项目</a>
        ${release.repo_url ? `<a class="ghost-button" href="${escapeHtml(release.repo_url)}" target="_blank" rel="noreferrer">GitHub</a>` : ''}
      </div>
      <div class="release-log">
        <h3>更新日志</h3>
        <ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('') || '<li>暂无更新日志</li>'}</ul>
      </div>
    </article>`;
}

function feedbackStatusLabel(value) {
  return {
    open: '待处理',
    processing: '处理中',
    closed: '已关闭',
  }[value] || value || '-';
}

function feedbackStatusClass(value) {
  return String(value || 'open').replace(/[^a-z0-9_-]/gi, '').toLowerCase();
}

function renderFeedbackAttachments(attachments = []) {
  if (!attachments.length) return '';
  return `
    <div class="feedback-attachments">
      ${attachments.map((attachment) => `
        <button
          class="attachment-chip"
          type="button"
          data-feedback-attachment-url="${escapeHtml(attachment.url || '')}"
          data-feedback-attachment-name="${escapeHtml(attachment.file_name || '反馈图片')}"
        >
          <span>${escapeHtml(attachment.file_name || '截图')}</span>
          <small>${formatSize(attachment.file_size)}</small>
        </button>
      `).join('')}
    </div>
  `;
}

function renderFeedbackFeed(targetId, items, options = {}) {
  const target = $(targetId);
  if (!target) return;
  if (options.kind === 'mine' && !state.user) {
    target.innerHTML = `
      <div class="empty-state">
        <strong>登录后查看处理进度</strong>
        <span>已注册用户提交的问题会自动汇总到这里。</span>
        <button class="ghost-button" type="button" data-open-auth>注册 / 登录</button>
      </div>
    `;
    return;
  }
  if (!items.length) {
    target.innerHTML = options.kind === 'mine'
      ? '<div class="empty-state"><span>暂未提交反馈</span></div>'
      : '<div class="empty-state"><span>暂无公开反馈</span></div>';
    return;
  }
  target.innerHTML = items.map((item) => {
    const isPublic = Boolean(Number(item.is_public));
    return `
      <article class="feedback-item">
        <div class="feedback-item-head">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <span>#${escapeHtml(item.id)} · ${formatTime(item.created_at)}</span>
          </div>
          <div class="feedback-state-line">
            <span class="status-pill ${feedbackStatusClass(item.status)}">${feedbackStatusLabel(item.status)}</span>
            ${options.showVisibility ? `<span class="visibility-pill ${isPublic ? 'is-public' : ''}">${isPublic ? '已公开' : '未公开'}</span>` : ''}
          </div>
        </div>
        ${options.showReporter ? `<div class="meta-line"><span>${escapeHtml(item.reporter || '匿名用户')}</span></div>` : ''}
        <p>${escapeHtml(excerpt(item.body, 180))}</p>
        ${renderFeedbackAttachments(item.attachments || [])}
        <div class="meta-line">
          <span>更新：${formatTime(item.updated_at)}</span>
        </div>
      </article>
    `;
  }).join('');
}

async function loadMyFeedback() {
  if (!state.user) {
    renderFeedbackFeed('myFeedbackList', [], { kind: 'mine', showVisibility: true });
    return;
  }
  const data = await api('/api/feedback/mine');
  renderFeedbackFeed('myFeedbackList', data.feedback || [], { kind: 'mine', showVisibility: true });
}

async function loadPublicFeedback() {
  const data = await api('/api/feedback/public');
  renderFeedbackFeed('publicFeedbackList', data.feedback || [], { kind: 'public', showReporter: true });
}

async function loadFeedbackPanels() {
  await Promise.all([loadPublicFeedback(), loadMyFeedback()]);
}

function hideImageModal() {
  const modal = $('imageModal');
  const image = $('imageModalImage');
  if (!modal || !image) return;
  modal.classList.add('hidden');
  image.removeAttribute('src');
  image.alt = '图片预览';
  if (state.imageModalObjectUrl) {
    URL.revokeObjectURL(state.imageModalObjectUrl);
    state.imageModalObjectUrl = '';
  }
}

function showImageModal(src, title = '图片预览', options = {}) {
  const modal = $('imageModal');
  const image = $('imageModalImage');
  const titleNode = $('imageModalTitle');
  if (!modal || !image || !titleNode || !src) return;
  if (state.imageModalObjectUrl && state.imageModalObjectUrl !== src) {
    URL.revokeObjectURL(state.imageModalObjectUrl);
    state.imageModalObjectUrl = '';
  }
  state.imageModalObjectUrl = options.objectUrl ? src : '';
  titleNode.textContent = title || '图片预览';
  image.src = src;
  image.alt = title || '图片预览';
  modal.classList.remove('hidden');
}

function openReplyAttachment(url, title = '回复图片') {
  if (!url) return;
  showImageModal(apiUrl(url), title || '回复图片');
}

async function openFeedbackAttachment(url, title = '反馈图片') {
  if (!url) return;
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(apiUrl(url), { headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `附件打开失败：${response.status}`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  showImageModal(objectUrl, title || '反馈图片', { objectUrl: true });
}

function showAuth(mode = 'register') {
  state.authMode = mode;
  document.querySelectorAll('.switch-tab').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.authMode === mode);
  });
  $('registerForm').classList.toggle('hidden', mode !== 'register');
  $('loginForm').classList.toggle('hidden', mode !== 'login');
  if (mode === 'login') fillLoginFormFromMemory();
  $('authModal').classList.remove('hidden');
}

function hideAuth() {
  $('authModal').classList.add('hidden');
}

function saveSession(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem(SITE_TOKEN_KEY, token);
  localStorage.setItem(SITE_USER_KEY, JSON.stringify(user || null));
  updateAuthUi();
}

function clearSession() {
  state.token = '';
  state.user = null;
  localStorage.removeItem(SITE_TOKEN_KEY);
  localStorage.removeItem(SITE_USER_KEY);
}

function updateAuthUi() {
  if (state.user) {
    $('authButton').classList.add('hidden');
    $('userButton').classList.remove('hidden');
    $('userButton').textContent = `${state.user.display_name}${state.user.unread_count ? ` · ${state.user.unread_count}` : ''}`;
  } else {
    $('authButton').classList.remove('hidden');
    $('userButton').classList.add('hidden');
    $('userButton').textContent = '';
  }
}

async function refreshMe() {
  if (!state.token) {
    updateAuthUi();
    return;
  }
  try {
    const data = await api('/api/me');
    saveSession(state.token, data.user);
  } catch (_error) {
    clearSession();
  }
  updateAuthUi();
}

async function refreshActiveAuthViews() {
  if ($('view-center').classList.contains('is-active')) {
    await renderCenter();
  }
  if ($('view-feedback').classList.contains('is-active')) {
    await loadMyFeedback();
  }
  if ($('view-thread').classList.contains('is-active') && state.selectedThreadId) {
    await openThread(state.selectedThreadId, { skipTrack: true });
  }
}

async function renderCenter() {
  const target = $('centerContent');
  if (!state.user) {
    target.innerHTML = `
      <div class="profile-panel">
        <h2>未登录</h2>
        <p class="meta-line">注册或登录后可查看互动通知与站内通知。</p>
        <button class="primary-button" type="button" data-open-auth>注册 / 登录</button>
      </div>
    `;
    return;
  }
  const data = await api('/api/notifications');
  const notifications = data.notifications || [];
  target.innerHTML = `
    <aside class="profile-panel">
      <h2>${escapeHtml(state.user.display_name)}</h2>
      <p class="meta-line">用户名：${escapeHtml(state.user.username || '未设置')}</p>
      <p class="meta-line">手机号：${escapeHtml(state.user.phone)}</p>
      <p class="meta-line">邮箱：${escapeHtml(state.user.email || '未填写')}</p>
      <p class="meta-line">注册时间：${formatTime(state.user.created_at)}</p>
      <form class="auth-form account-password-form" data-password-form>
        <input name="username" type="text" autocomplete="username" value="${escapeHtml(state.user.username || '')}" hidden>
        <label>
          <span>${state.user.has_password ? '更新登录密码' : '设置登录密码'}</span>
          <input name="password" type="password" minlength="6" maxlength="128" autocomplete="new-password" required>
        </label>
        <label>
          <span>确认密码</span>
          <input name="passwordConfirm" type="password" minlength="6" maxlength="128" autocomplete="new-password" required>
        </label>
        <button class="ghost-button" type="submit">${state.user.has_password ? '更新密码' : '设置密码'}</button>
      </form>
      <div class="form-actions">
        <button class="ghost-button" type="button" data-logout>退出登录</button>
      </div>
    </aside>
    <section class="notifications-panel">
      <div class="panel-head">
        <h2>通知</h2>
        <button class="ghost-button" type="button" data-read-all>全部已读</button>
      </div>
      <div class="notification-list">
        ${notifications.map((item) => `
          <article class="notification-item ${item.read_at ? '' : 'unread'}">
            <div class="panel-head">
              <strong>${escapeHtml(item.title)}</strong>
              <span class="meta-line">${item.read_at ? '已读' : '未读'}</span>
            </div>
            <p>${escapeHtml(item.body)}</p>
            <div class="meta-line">
              <span>${formatTime(item.created_at)}</span>
              ${item.read_at ? '' : `<button class="ghost-button" type="button" data-read-notice="${item.id}">标记已读</button>`}
            </div>
          </article>
        `).join('') || '<div class="empty-state"><span>暂无通知</span></div>'}
      </div>
    </section>
  `;
}

function renderProjectDots() {
  const target = $('projectDots');
  if (!target) return;
  const slides = Array.from(document.querySelectorAll('.project-slide'));
  target.innerHTML = slides.map((_, index) => `
    <button class="${index === state.projectSlide ? 'is-active' : ''}" type="button" data-project-slide="${index}" aria-label="第 ${index + 1} 张"></button>
  `).join('');
}

function setProjectSlide(nextIndex) {
  const slides = Array.from(document.querySelectorAll('.project-slide'));
  if (!slides.length) return;
  state.projectSlide = (nextIndex + slides.length) % slides.length;
  slides.forEach((slide, index) => {
    slide.classList.toggle('is-active', index === state.projectSlide);
  });
  renderProjectDots();
}

function nextProjectSlide(delta = 1) {
  setProjectSlide(state.projectSlide + delta);
}

function startProjectCarousel() {
  renderProjectDots();
  stopProjectCarousel();
  if (state.projectPaused || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  state.projectTimer = setInterval(() => nextProjectSlide(1), 5200);
}

function stopProjectCarousel() {
  if (!state.projectTimer) return;
  clearInterval(state.projectTimer);
  state.projectTimer = null;
}

function toggleProjectAutoplay() {
  state.projectPaused = !state.projectPaused;
  const button = $('projectPause');
  button.textContent = state.projectPaused ? '▶' : 'Ⅱ';
  button.title = state.projectPaused ? '继续轮播' : '暂停轮播';
  button.setAttribute('aria-label', button.title);
  if (state.projectPaused) stopProjectCarousel();
  else startProjectCarousel();
}

async function handleRoute() {
  const route = currentRoute();
  if (/^thread-\d+$/.test(route)) {
    await openThread(route.replace('thread-', ''));
    return;
  }
  if (['forum', 'downloads', 'project', 'feedback', 'center'].includes(route)) {
    switchView(route, { skipHash: true });
  }
}

function currentRoute() {
  const hashRoute = (location.hash || '').replace(/^#\/?/, '').trim();
  if (hashRoute) return hashRoute;
  const pathRoute = location.pathname.replace(/^\/+|\/+$/g, '').trim();
  if (['forum', 'downloads', 'project', 'feedback', 'center'].includes(pathRoute)) return pathRoute;
  if (/^thread-\d+$/.test(pathRoute)) return pathRoute;
  return 'project';
}

function bindEvents() {
  bindLoginMemoryControls();

  $('themeToggle').addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    track('theme_toggle', document.documentElement.dataset.theme);
  });

  document.querySelectorAll('.nav-tab').forEach((button) => {
    button.addEventListener('click', () => switchView(button.dataset.view));
  });

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-jump-view]');
    if (!button) return;
    event.preventDefault();
    switchView(button.dataset.jumpView);
  });

  $('projectPrev').addEventListener('click', () => {
    nextProjectSlide(-1);
    startProjectCarousel();
  });

  $('projectNext').addEventListener('click', () => {
    nextProjectSlide(1);
    startProjectCarousel();
  });

  $('projectPause').addEventListener('click', toggleProjectAutoplay);

  $('projectDots').addEventListener('click', (event) => {
    const button = event.target.closest('[data-project-slide]');
    if (!button) return;
    setProjectSlide(Number(button.dataset.projectSlide));
    startProjectCarousel();
  });

  $('authButton').addEventListener('click', () => showAuth('register'));
  $('userButton').addEventListener('click', () => switchView('center'));
  $('closeAuth').addEventListener('click', hideAuth);
  $('authModal').addEventListener('click', (event) => {
    if (event.target === $('authModal')) hideAuth();
  });
  $('closeImageModal').addEventListener('click', hideImageModal);
  $('imageModal').addEventListener('click', (event) => {
    if (event.target === $('imageModal')) hideImageModal();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (!$('imageModal').classList.contains('hidden')) {
      hideImageModal();
    }
  });

  document.querySelectorAll('.switch-tab').forEach((button) => {
    button.addEventListener('click', () => showAuth(button.dataset.authMode));
  });

  $('categoryTabs').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-category]');
    if (!button) return;
    state.activeCategory = button.dataset.category;
    loadCategories();
    loadThreads();
    track('forum_category', state.activeCategory || 'all');
  });

  let searchTimer = 0;
  $('threadSearch').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadThreads, 260);
  });

  $('threadList').addEventListener('click', (event) => {
    const card = event.target.closest('[data-thread-id]');
    if (!card) return;
    openThread(card.dataset.threadId).catch((error) => toast(error.message));
  });

  $('threadList').addEventListener('keydown', (event) => {
    if (!['Enter', ' '].includes(event.key)) return;
    const card = event.target.closest('[data-thread-id]');
    if (!card) return;
    event.preventDefault();
    openThread(card.dataset.threadId).catch((error) => toast(error.message));
  });

  $('hotThreads').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-hot-thread]');
    if (!button) return;
    switchView('forum');
    openThread(button.dataset.hotThread).catch((error) => toast(error.message));
  });

  $('backToForumButton').addEventListener('click', () => switchView('forum'));

  $('newThreadButton').addEventListener('click', () => {
    if (!state.user) {
      showAuth('register');
      return;
    }
    $('threadForm').classList.toggle('hidden');
    track('thread_compose_open');
  });

  $('cancelThreadButton').addEventListener('click', () => $('threadForm').classList.add('hidden'));

  $('threadForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!state.user) {
      showAuth('register');
      return;
    }
    try {
      const data = await api('/api/forum/threads', {
        method: 'POST',
        body: JSON.stringify({
          category: $('threadCategory').value,
          tags: $('threadTags').value,
          title: $('threadTitle').value,
          body: $('threadBody').value,
        }),
      });
      event.target.reset();
      $('threadForm').classList.add('hidden');
      await loadPublic();
      await loadThreads();
      await openThread(data.thread_id);
      toast('帖子已发布');
    } catch (error) {
      toast(error.message);
    }
  });

  $('threadPageContent').addEventListener('click', (event) => {
    if (event.target.closest('[data-open-auth]')) {
      showAuth('login');
      return;
    }
    const expandButton = event.target.closest('[data-toggle-replies]');
    if (expandButton) {
      const replyId = Number(expandButton.dataset.toggleReplies);
      const children = document.querySelector(`[data-child-replies="${replyId}"]`);
      if (!children) return;
      const nextExpanded = children.classList.contains('hidden');
      children.classList.toggle('hidden', !nextExpanded);
      if (nextExpanded) state.expandedReplyIds.add(replyId);
      else state.expandedReplyIds.delete(replyId);
      expandButton.textContent = nextExpanded ? '收起回复' : `展开 ${expandButton.dataset.childCount} 条回复`;
      return;
    }
    const replyButton = event.target.closest('[data-reply-parent-id]');
    if (replyButton) {
      if (!state.user) {
        showAuth('login');
        return;
      }
      const parentId = Number(replyButton.dataset.replyParentId);
      if (state.replyComposeParentId && state.replyComposeParentId !== parentId) {
        clearReplyFiles(state.replyComposeParentId);
      }
      state.replyComposeParentId = state.replyComposeParentId === parentId ? null : parentId;
      if (state.replyComposeParentId) {
        const parentReply = state.currentReplies.find((reply) => Number(reply.id) === parentId);
        const rootId = Number(parentReply?.parent_id || parentId);
        state.expandedReplyIds.add(rootId);
      }
      renderThreadPage(state.currentThread, state.currentReplies);
      return;
    }
    if (event.target.closest('[data-cancel-reply]')) {
      if (state.replyComposeParentId) clearReplyFiles(state.replyComposeParentId);
      state.replyComposeParentId = null;
      renderThreadPage(state.currentThread, state.currentReplies);
      return;
    }
    const removeImageButton = event.target.closest('[data-remove-reply-image]');
    if (removeImageButton) {
      const form = removeImageButton.closest('[data-reply-form]');
      const parentId = parentIdFromReplyForm(form);
      const files = replyFiles(parentId);
      files.splice(Number(removeImageButton.dataset.removeReplyImage), 1);
      state.replyFiles[replyKey(parentId)] = files;
      updateReplyImagePreview(parentId);
      return;
    }
    const previewImageButton = event.target.closest('[data-preview-reply-image]');
    if (previewImageButton) {
      const form = previewImageButton.closest('[data-reply-form]');
      const parentId = parentIdFromReplyForm(form);
      const index = Number(previewImageButton.dataset.previewReplyImage);
      const file = replyFiles(parentId)[index];
      const url = state.replyPreviewUrls[replyKey(parentId)]?.[index];
      if (url) showImageModal(url, file?.name || '回复图片');
      return;
    }
    const attachment = event.target.closest('[data-reply-attachment-url]');
    if (attachment) {
      openReplyAttachment(attachment.dataset.replyAttachmentUrl, attachment.dataset.replyAttachmentName);
    }
  });

  $('threadPageContent').addEventListener('change', (event) => {
    const input = event.target.closest('[data-reply-upload]');
    if (!input) return;
    const form = input.closest('[data-reply-form]');
    setReplyFiles(parentIdFromReplyForm(form), input.files, { append: true });
    input.value = '';
  });

  $('threadPageContent').addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-reply-form]');
    if (!form) return;
    event.preventDefault();
    const parentId = parentIdFromReplyForm(form);
    const body = form.elements.body.value;
    const files = replyFiles(parentId);
    if (body.trim().length < 2 && !files.length) {
      toast('回复内容不能为空');
      return;
    }
    try {
      const parentReply = parentId ? state.currentReplies.find((reply) => Number(reply.id) === parentId) : null;
      const rootId = parentId ? Number(parentReply?.parent_id || parentId) : null;
      const attachments = await Promise.all(files.map(fileToAttachment));
      await api(`/api/forum/threads/${state.selectedThreadId}/replies`, {
        method: 'POST',
        body: JSON.stringify({ body, parent_id: parentId, attachments }),
      });
      form.reset();
      clearReplyFiles(parentId);
      if (rootId) state.expandedReplyIds.add(rootId);
      state.replyComposeParentId = null;
      await loadPublic();
      await loadThreads();
      await openThread(state.selectedThreadId);
      toast('回复已提交');
    } catch (error) {
      toast(error.message);
    }
  });

  $('downloadList').addEventListener('click', (event) => {
    const link = event.target.closest('[data-download-id]');
    if (link) track('download', link.dataset.downloadId);
  });

  $('feedbackScreenshots').addEventListener('change', (event) => {
    setFeedbackFiles(event.target.files, { append: true });
    event.target.value = '';
  });

  $('feedbackPreview').addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-screenshot]');
    if (!button) return;
    state.feedbackFiles.splice(Number(button.dataset.removeScreenshot), 1);
    $('feedbackScreenshots').value = '';
    renderFeedbackPreview();
  });

  document.addEventListener('paste', handleFeedbackPaste);
  document.addEventListener('paste', handleReplyPaste);

  $('refreshMyFeedback').addEventListener('click', () => {
    loadMyFeedback().catch((error) => toast(error.message));
  });

  $('refreshPublicFeedback').addEventListener('click', () => {
    loadPublicFeedback().catch((error) => toast(error.message));
  });

  $('view-feedback').addEventListener('click', async (event) => {
    if (event.target.closest('[data-open-auth]')) {
      showAuth('register');
      return;
    }
    const attachment = event.target.closest('[data-feedback-attachment-url]');
    if (!attachment) return;
    try {
      await openFeedbackAttachment(attachment.dataset.feedbackAttachmentUrl, attachment.dataset.feedbackAttachmentName);
    } catch (error) {
      toast(error.message);
    }
  });

  $('feedbackForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const attachments = await Promise.all(state.feedbackFiles.map(fileToAttachment));
      await api('/api/feedback', {
        method: 'POST',
        body: JSON.stringify({
          title: $('feedbackTitle').value,
          contact: $('feedbackContact').value,
          body: $('feedbackBody').value,
          attachments,
        }),
      });
      event.target.reset();
      state.feedbackFiles = [];
      renderFeedbackPreview();
      await loadFeedbackPanels();
      toast('反馈已提交');
    } catch (error) {
      toast(error.message);
    }
  });

  $('centerContent').addEventListener('click', async (event) => {
    if (event.target.closest('[data-open-auth]')) {
      showAuth('register');
      return;
    }
    if (event.target.closest('[data-logout]')) {
      await api('/api/auth/logout', { method: 'POST', body: '{}' }).catch(() => {});
      clearSession();
      disableRememberedAutoLogin();
      updateAuthUi();
      await refreshActiveAuthViews();
      toast('已退出登录');
      return;
    }
    const noticeButton = event.target.closest('[data-read-notice]');
    if (noticeButton) {
      await api(`/api/notifications/${noticeButton.dataset.readNotice}/read`, { method: 'POST', body: '{}' });
      await refreshMe();
      await renderCenter();
      return;
    }
    if (event.target.closest('[data-read-all]')) {
      await api('/api/notifications/read-all', { method: 'POST', body: '{}' });
      await refreshMe();
      await renderCenter();
    }
  });

  $('centerContent').addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-password-form]');
    if (!form) return;
    event.preventDefault();
    const password = form.elements.password.value;
    if (password !== form.elements.passwordConfirm.value) {
      toast('两次输入的密码不一致');
      return;
    }
    try {
      const data = await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      state.user = data.user;
      updateAuthUi();
      await renderCenter();
      toast('登录密码已更新');
    } catch (error) {
      toast(error.message);
    }
  });

  $('registerForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if ($('registerPassword').value !== $('registerPasswordConfirm').value) {
      toast('两次输入的密码不一致');
      return;
    }
    try {
      const data = await api('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          username: $('registerUsername').value,
          phone: $('registerPhone').value,
          email: $('registerEmail').value,
          display_name: $('registerName').value,
          password: $('registerPassword').value,
        }),
      });
      saveSession(data.token, data.user);
      hideAuth();
      toast('注册成功');
      await refreshActiveAuthViews();
    } catch (error) {
      toast(error.message);
    }
  });

  $('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          account: $('loginAccount').value,
          password: $('loginPassword').value,
        }),
      });
      saveSession(data.token, data.user);
      saveLoginMemoryFromForm();
      hideAuth();
      toast('登录成功');
      await refreshActiveAuthViews();
    } catch (error) {
      toast(error.message);
    }
  });

  window.addEventListener('hashchange', () => {
    handleRoute().catch((error) => toast(error.message));
  });
}

async function init() {
  initTheme();
  bindEvents();
  updateAuthUi();
  await Promise.all([loadPublic(), loadCategories(), loadThreads(), refreshMe()]);
  await handleRoute();
}

init().catch((error) => toast(error.message));
