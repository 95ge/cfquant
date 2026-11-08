/* Sidebar preferences are local to this browser and never change account settings. */
(() => {
  const storageKey = 'cfquant.navigation.v1';
  const root = document.documentElement;
  const sidebar = document.getElementById('primarySidebar');
  const nav = document.getElementById('primaryNavigation');
  const compactButton = document.getElementById('sidebarCompactBtn');
  const visibilityButton = document.getElementById('sidebarVisibilityBtn');
  const appearanceButton = document.getElementById('sidebarAppearanceBtn');
  const appearancePanel = document.getElementById('sidebarAppearancePanel');
  if (!sidebar || !nav || !compactButton || !visibilityButton || !appearanceButton || !appearancePanel) return;

  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch (_) { /* Use defaults if storage is unavailable. */ }
  let display = ['full', 'text', 'compact'].includes(saved.display) ? saved.display : 'full';
  let expandedDisplay = saved.expandedDisplay === 'text' ? 'text' : 'full';
  let hidden = saved.hidden === true;
  const narrow = window.matchMedia('(max-width: 980px)');
  const tooltip = document.createElement('div');
  tooltip.id = 'sidebarNavTooltip';
  tooltip.className = 'sidebar-nav-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  tooltip.hidden = true;
  document.body.append(tooltip);
  let tooltipTarget = null;
  let revealFrame = null;

  function hideTooltip() {
    tooltipTarget?.removeAttribute('aria-describedby');
    tooltipTarget = null;
    tooltip.hidden = true;
  }

  function showTooltip(button) {
    if (display !== 'compact' || hidden) return;
    hideTooltip();
    tooltipTarget = button;
    tooltip.textContent = button.getAttribute('aria-label');
    tooltip.hidden = false;
    button.setAttribute('aria-describedby', tooltip.id);
    const bounds = button.getBoundingClientRect();
    const left = narrow.matches ? bounds.left : sidebar.getBoundingClientRect().right + 8;
    const top = narrow.matches ? bounds.bottom + 8 : bounds.top + (bounds.height - tooltip.offsetHeight) / 2;
    tooltip.style.left = `${Math.max(8, Math.min(left, window.innerWidth - tooltip.offsetWidth - 8))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(top, window.innerHeight - tooltip.offsetHeight - 8))}px`;
  }

  function revealActive() {
    if (hidden) return;
    const active = nav.querySelector('.nav-item.active');
    if (!active) return; // Pinned shortcuts do not scroll the middle menu.
    const viewport = nav.getBoundingClientRect();
    const item = active.getBoundingClientRect();
    if (narrow.matches) {
      if (item.left < viewport.left + 8) nav.scrollLeft += item.left - viewport.left - 8;
      else if (item.right > viewport.right - 8) nav.scrollLeft += item.right - viewport.right + 8;
    } else {
      if (item.top < viewport.top + 8) nav.scrollTop += item.top - viewport.top - 8;
      else if (item.bottom > viewport.bottom - 8) nav.scrollTop += item.bottom - viewport.bottom + 8;
    }
  }

  function scheduleReveal() {
    if (revealFrame != null) cancelAnimationFrame(revealFrame);
    revealFrame = requestAnimationFrame(() => {
      revealFrame = null;
      revealActive();
      if (tooltipTarget) showTooltip(tooltipTarget);
    });
  }

  function closeAppearance(restoreFocus = false) {
    appearancePanel.hidden = true;
    appearanceButton.setAttribute('aria-expanded', 'false');
    if (restoreFocus) appearanceButton.focus({preventScroll: true});
  }

  function apply(persist = true) {
    root.dataset.sidebarMode = display;
    root.dataset.sidebarHidden = String(hidden);
    sidebar.inert = hidden;
    compactButton.setAttribute('aria-pressed', String(display === 'compact'));
    const compactLabel = display === 'compact' ? '展开导航文字' : '收起为图标导航';
    compactButton.setAttribute('aria-label', compactLabel);
    compactButton.title = compactLabel;
    const visibilityLabel = hidden ? '显示导航栏' : '隐藏导航栏';
    visibilityButton.setAttribute('aria-expanded', String(!hidden));
    visibilityButton.setAttribute('aria-label', visibilityLabel);
    visibilityButton.title = visibilityLabel;
    appearancePanel.querySelectorAll('input').forEach(input => { input.checked = input.value === display; });
    hideTooltip();
    if (persist) {
      try { localStorage.setItem(storageKey, JSON.stringify({display, expandedDisplay, hidden})); } catch (_) { /* The controls still work without persistence. */ }
    }
    scheduleReveal();
  }

  sidebar.querySelectorAll('.nav-item').forEach(button => {
    button.setAttribute('aria-label', button.querySelector('span').textContent.trim());
    button.addEventListener('mouseenter', () => showTooltip(button));
    button.addEventListener('focus', () => showTooltip(button));
    button.addEventListener('mouseleave', () => { if (document.activeElement !== button) hideTooltip(); });
    button.addEventListener('blur', hideTooltip);
    button.addEventListener('click', hideTooltip);
  });

  compactButton.addEventListener('click', () => {
    closeAppearance();
    if (display === 'compact') display = expandedDisplay;
    else { expandedDisplay = display; display = 'compact'; }
    apply();
  });
  visibilityButton.addEventListener('click', () => {
    closeAppearance();
    hidden = !hidden;
    apply();
  });
  appearanceButton.addEventListener('click', () => {
    const open = appearancePanel.hidden;
    appearancePanel.hidden = !open;
    appearanceButton.setAttribute('aria-expanded', String(open));
    if (open) appearancePanel.querySelector('input:checked')?.focus({preventScroll: true});
  });
  appearancePanel.addEventListener('change', event => {
    const input = event.target;
    if (!input.matches('input[name="sidebarDisplay"]')) return;
    display = input.value;
    if (display !== 'compact') expandedDisplay = display;
    apply();
  });
  // Keep the chooser open while using arrow keys within its native radio group.
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest('.sidebar-appearance')) closeAppearance();
  });
  document.addEventListener('focusin', event => {
    if (!event.target.closest('.sidebar-appearance')) closeAppearance();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      if (!appearancePanel.hidden) { closeAppearance(true); event.preventDefault(); }
      hideTooltip();
    }
  });
  nav.addEventListener('scroll', hideTooltip, {passive: true});
  window.addEventListener('resize', scheduleReveal, {passive: true});
  window.addEventListener('scroll', hideTooltip, {passive: true});
  new ResizeObserver(scheduleReveal).observe(nav);
  apply(false);
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add('navigation-ready')));
  window.CfquantNavigation = {revealActive};
})();
