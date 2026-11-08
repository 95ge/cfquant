"""Navigation layout and preferences, using offline APIs without a trading service."""
from cfquant.tests.test_tutorial_reader import browser, page, expect, frontend_url, open_app


def open_console(page, frontend_url):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    return requests, errors


def test_pinned_shortcuts_survive_menu_growth_and_navigation(page, frontend_url):
    requests, errors = open_console(page, frontend_url)
    sidebar = page.locator('#primarySidebar')
    expect(sidebar.locator('.nav-item')).to_have_count(11)
    expect(page.locator('.side-nav .nav-section-title')).to_have_text(['交易管理', '运行管理', '开发调试'])
    expect(page.locator('.sidebar-shortcuts .nav-item')).to_have_text(['接口测试', '使用教程', '系统设置'])
    if page.viewport_size['width'] > 980:
        page.set_viewport_size({'width': 1366, 'height': 600})
    nav = page.locator('#primaryNavigation')
    footer = page.locator('.sidebar-footer')
    original = footer.bounding_box()
    nav.evaluate('''node => {
        for (let i = 0; i < 24; i++) {
            const row = document.createElement('div');
            row.style.cssText = 'flex:0 0 40px;min-width:100px;min-height:40px';
            row.textContent = 'Future menu ' + i;
            node.append(row);
        }
        node.scrollTop = node.scrollHeight;
        node.scrollLeft = node.scrollWidth;
    }''')
    assert nav.evaluate('n => n.scrollTop > 0 || n.scrollLeft > 0')
    current = footer.bounding_box()
    assert abs(current['y'] - original['y']) < 1
    assert current['y'] + current['height'] <= page.viewport_size['height'] + 1
    for view, category in [('api', '文档帮助'), ('tutorial', '文档帮助'), ('settings', '系统管理')]:
        sidebar.locator(f'[data-view="{view}"]').click()
        expect(page.locator('body')).to_have_attribute('data-view', view)
        expect(sidebar.locator('[aria-current="page"]')).to_have_count(1)
        expect(sidebar.locator('[aria-current="page"]')).to_have_attribute('data-view', view)
        expect(page.locator('#viewCategory')).to_have_text(category)
    page.evaluate("setView('bindings')")
    expect(sidebar.locator('[aria-current="page"]')).to_have_attribute('data-view', 'bindings')
    active = sidebar.locator('[aria-current="page"]').bounding_box()
    viewport = nav.bounding_box()
    assert viewport['x'] <= active['x'] and active['x'] + active['width'] <= viewport['x'] + viewport['width'] + 1
    assert viewport['y'] <= active['y'] and active['y'] + active['height'] <= viewport['y'] + viewport['height'] + 1
    assert all(method == 'GET' for method, _ in requests)
    assert not errors


def test_display_modes_keyboard_tooltips_and_hidden_state_persist(page, frontend_url):
    requests, errors = open_console(page, frontend_url)
    sidebar = page.locator('#primarySidebar')
    chooser = page.locator('#sidebarAppearancePanel')
    page.locator('#sidebarAppearanceBtn').click()
    chooser.locator('[value="text"]').check()
    expect(page.locator('html')).to_have_attribute('data-sidebar-mode', 'text')
    expect(sidebar.locator('.nav-icon:visible')).to_have_count(0)
    page.keyboard.press('Escape')
    expect(page.locator('#sidebarAppearanceBtn')).to_be_focused()
    page.locator('#sidebarCompactBtn').click()
    expect(page.locator('html')).to_have_attribute('data-sidebar-mode', 'compact')
    api = sidebar.get_by_role('button', name='接口测试', exact=True)
    api.focus()
    expect(page.locator('#sidebarNavTooltip')).to_have_text('接口测试')
    expect(page.locator('#sidebarNavTooltip')).to_be_visible()
    page.keyboard.press('Enter')
    expect(page.locator('body')).to_have_attribute('data-view', 'api')
    page.evaluate("localStorage.setItem('cfquant.view', 'docs')")
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-sidebar-mode', 'compact')
    expect(sidebar.locator('[aria-current="page"]')).to_have_attribute('data-view', 'api')
    page.evaluate('hideOnboardingModal({force:true})')
    page.locator('#sidebarCompactBtn').click()
    expect(page.locator('html')).to_have_attribute('data-sidebar-mode', 'text')
    page.locator('#sidebarAppearanceBtn').click()
    chooser.locator('[value="full"]').focus()
    page.keyboard.press('Space')
    expect(page.locator('html')).to_have_attribute('data-sidebar-mode', 'full')
    page.keyboard.press('Escape')
    page.get_by_role('button', name='隐藏导航栏', exact=True).click()
    expect(sidebar).not_to_be_visible()
    assert sidebar.evaluate('node => node.inert')
    expect(page.get_by_role('button', name='显示导航栏', exact=True)).to_be_visible()
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-sidebar-hidden', 'true')
    page.evaluate('hideOnboardingModal({force:true})')
    page.get_by_role('button', name='显示导航栏', exact=True).click()
    expect(sidebar).to_be_visible()
    expect(api).to_have_attribute('aria-current', 'page')
    expect(sidebar.locator('.nav-icon:visible')).to_have_count(11)
    assert all(method == 'GET' for method, _ in requests)
    assert not errors
