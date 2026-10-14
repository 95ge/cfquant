"""Binding timer/log controls with mocked APIs on desktop and mobile."""
from pathlib import Path

from cfquant.tests.test_tutorial_reader import browser, page, frontend_url, open_app, expect


def open_bindings(page, frontend_url):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="bindings"]').click()
    return requests, errors


def test_binding_runtime_default_save_edit_and_isolation(page, frontend_url):
    requests, errors = open_bindings(page, frontend_url)
    page.locator('#openBindingDialogBtn').click()
    expect(page.locator('#bindingQmtTimerInterval')).to_have_value('1')
    expect(page.locator('#bindingQmtLogEnabled')).to_have_value('off')
    page.locator('#bindingAccountId').fill('TEST_ONLY')
    page.locator('#bindingMode').select_option('lite')
    # No installation or launch even in the mocked request payload.
    page.evaluate("fillQmtStrategySettings('binding', {enabled: false})")
    page.locator('#bindingQmtAutoLogin').uncheck()
    page.locator('#bindingQmtTimerInterval').fill('5')
    page.locator('#bindingQmtLogEnabled').select_option('on')
    saved = []

    def save(route):
        body = route.request.post_data_json
        saved.append(body)
        row = dict(body, account_key='TEST_ONLY|STOCK|test', bridge_id='test')
        route.fulfill(json={'ok': True, 'data': {
            'account': row, 'account_configs': {row['account_key']: row}, 'account_pairs': {},
            'bridges': {'test': {'name': 'Test'}}, 'qmt_strategy_deploy': {'enabled': False},
            'qmt_auto_login': {'enabled': False},
        }})

    page.route('**/api/account-config', save)
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert saved[0]['qmt_runtime'] == {'timer_interval_ms': 5, 'log_enabled': True}
    page.evaluate("""() => {
        document.querySelector('#bindingQmtGuideOverlay').classList.add('hidden');
        openBindingDialog({accountKey: 'TEST_ONLY|STOCK|test'});
    }""")
    expect(page.locator('#bindingQmtTimerInterval')).to_have_value('5')
    expect(page.locator('#bindingQmtLogEnabled')).to_have_value('on')
    page.locator('#bindingQmtLogEnabled').select_option('off')
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert saved[-1]['qmt_runtime'] == {'timer_interval_ms': 5, 'log_enabled': False}
    page.evaluate("""() => {
        document.querySelector('#bindingQmtGuideOverlay').classList.add('hidden');
        openBindingDialog();
    }""")
    expect(page.locator('#bindingQmtTimerInterval')).to_have_value('1')
    expect(page.locator('#bindingQmtLogEnabled')).to_have_value('off')
    page.locator('#bindingRuntimeSettings').scroll_into_view_if_needed()
    folder = Path(__file__).resolve().parents[2] / 'runtime/screenshots'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / ('binding-runtime-%s.png' % page.viewport_size['width'])))
    assert page.locator('#bindingRuntimeSettings').evaluate('el => el.scrollWidth <= el.clientWidth')
    assert page.locator('#bindingDialogOverlay .binding-dialog').evaluate('el => el.scrollWidth <= el.clientWidth'), page.evaluate("""() => {
        const dialog = document.querySelector('#bindingDialogOverlay .binding-dialog');
        const bounds = dialog.getBoundingClientRect();
        return [...dialog.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > bounds.right)
            .map(el => ({tag: el.tagName, id: el.id, cls: el.className, width: el.clientWidth}));
    }""")
    assert errors == []


def test_binding_runtime_legacy_inheritance_validation_and_modes(page, frontend_url):
    requests, errors = open_bindings(page, frontend_url)
    page.evaluate("""() => {
        state.accountConfigs = {old: {account_key: 'old', account_id: 'OLD', account_type: 'STOCK',
            mode: 'ctypes', bridge_id: 'legacy', qmt_strategy: {enabled: false}}};
        openBindingDialog({accountKey: 'old'});
    }""")
    expect(page.locator('#bindingQmtTimerInterval')).to_have_value('1')
    expect(page.locator('#bindingQmtLogEnabled')).to_have_value('inherit')
    for value in ('0', '1001', '2.5', ''):
        page.locator('#bindingQmtTimerInterval').fill(value)
        assert page.locator('#bindingQmtTimerInterval').evaluate('el => !el.checkValidity()')
        assert page.evaluate("readBindingRuntimeSettings(document.querySelector('#bindingForm'))") is None
    page.locator('#bindingQmtTimerInterval').fill('10')
    page.locator('#bindingMode').select_option('lttx')
    expect(page.locator('#bindingRuntimeSettings')).not_to_be_visible()
    expect(page.locator('#bindingQmtTimerInterval')).to_be_disabled()
    page.locator('#bindingMode').select_option('lite')
    expect(page.locator('#bindingRuntimeSettings')).to_be_visible()
    expect(page.locator('#bindingQmtTimerInterval')).to_have_value('10')
    assert errors == []


def test_binding_runtime_reports_backend_that_does_not_save_settings(page, frontend_url):
    _, errors = open_bindings(page, frontend_url)
    page.locator('#openBindingDialogBtn').click()
    page.locator('#bindingAccountId').fill('TEST_ONLY')
    page.evaluate("fillQmtStrategySettings('binding', {enabled: false})")
    page.locator('#bindingQmtAutoLogin').uncheck()
    page.route('**/api/account-config', lambda route: route.fulfill(json={
        'ok': True, 'data': {'account': {'account_id': 'TEST_ONLY', 'bridge_id': 'test'}}}))
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingSaveStatus')).to_contain_text('重启 Web 后端')
    expect(page.locator('#bindingDialogOverlay')).to_be_visible()
    expect(page.locator('#bindingForm [type="submit"]')).to_be_enabled()
    assert errors == []
