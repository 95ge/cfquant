"""Managed strategy controls and progress with mocked APIs, on desktop/mobile."""

from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url, open_app, page


def test_binding_sends_strategy_flags_and_displays_pending_deployment(page, frontend_url, tmp_path):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        state.setup = {setup_required: false};
        setView('bindings');
        openBindingDialog();
    }""")
    expect(page.locator('#bindingStrategyEnabled')).to_be_checked()
    expect(page.locator('#bindingStrategyAutorun')).not_to_be_checked()
    expect(page.locator('#bindingStrategyRunMode')).to_have_value('0')
    page.locator('#bindingAccountId').fill('1000000001')
    page.locator('#bindingQmtDir').fill('D:\\QMT-FAKE')
    page.locator('#bindingMode').select_option('lite')
    page.locator('#bindingStrategyRunMode').select_option('1')
    page.locator('#bindingStrategyAutorun').check()
    page.locator('#bindingStrategySettings details summary').click()
    page.locator('#bindingStrategyKey_normal').fill('2____101____201____49____1000000001____')
    page.locator('#bindingStrategySettings').scroll_into_view_if_needed()
    assert page.locator('#bindingForm').evaluate('(node) => node.scrollWidth <= node.clientWidth')
    page.screenshot(path=str(tmp_path / 'qmt-strategy-binding.png'))
    saved = []
    def respond(route):
        payload = route.request.post_data_json
        saved.append(payload)
        key = 'bridge:STOCK:1000000001'
        row = dict(payload, account_key=key, bridge_id='bridge')
        route.fulfill(json={'ok': True, 'data': {'account': row, 'account_configs': {key: row},
            'account_pairs': {}, 'bridges': {'bridge': {'name': 'Test'}},
            'qmt_strategy_deploy': {'enabled': True, 'targets': [{
                'state': 'waiting_exit', 'strategies': ['CFQ_LITE_TEST'],
                'message': 'Waiting for QMT exit', 'error': ''}]}}})
    page.route('**/api/account-config', respond)
    page.locator('#bindingForm button[type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert len(saved) == 1
    assert saved[0]['qmt_strategy'] == {'enabled': True, 'live': True, 'autorun': True,
        'stock': 'SH000300', 'account_keys': {'normal': '2____101____201____49____1000000001____',
                                            'trade': '', 'SH': '', 'SZ': ''}}
    expect(page.locator('#bindingQmtGuideOverlay')).not_to_be_visible()
    assert page.locator('body').inner_text().find('Waiting for QMT exit') >= 0
    assert errors == []


def test_edit_preserves_flags_and_setup_onboarding_use_same_controls(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        const strategy = {enabled: true, live: true, autorun: false, stock: 'SZ399001',
            account_keys: {normal: '2____101____201____49____1000000001____'}};
        const row = {account_id: '1000000001', account_type: 'STOCK', account_key: 'test',
            bridge_id: 'test', mode: 'lite', qmt_dir: 'D:/FAKE-QMT', qmt_strategy: strategy};
        state.accountConfigs = {test: row};
        document.querySelector('#setupOverlay').classList.add('hidden');
        openBindingDialog({accountKey: 'test'});
    }""")
    expect(page.locator('#bindingStrategyRunMode')).to_have_value('1')
    expect(page.locator('#bindingStrategyAutorun')).not_to_be_checked()
    expect(page.locator('#bindingStrategyStock')).to_have_value('SZ399001')
    page.locator('#bindingStrategyEnabled').uncheck()
    expect(page.locator('#bindingStrategyRunMode')).to_be_disabled()
    expect(page.locator('#bindingStrategyAutorun')).to_be_disabled()
    result = page.evaluate("""() => {
        const settings = {enabled: true, live: false, autorun: true, stock: 'SH000300'};
        fillQmtStrategySettings('setup', settings);
        fillQmtStrategySettings('onboarding', settings);
        return [readQmtStrategySettings('setup'), readQmtStrategySettings('onboarding')];
    }""")
    assert all(item['enabled'] and item['autorun'] and not item['live'] for item in result)
    assert errors == []


def test_disabled_market_routing_is_not_reenabled_by_residual_routes(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        const row = {account_id: '1000000001', account_type: 'CREDIT', account_key: 'test',
            bridge_id: 'test', mode: 'ctypes', qmt_dir: 'D:/FAKE-QMT',
            market_routing_enabled: false,
            market_bridges: {SH: {bridge_id: 'test_sh'}, SZ: {bridge_id: 'test_sz'}},
            qmt_strategy: {enabled: true}};
        state.accountConfigs = {test: row};
        document.querySelector('#setupOverlay').classList.add('hidden');
        openBindingDialog({accountKey: 'test'});
    }""")
    expect(page.locator('#bindingMarketRoutingEnabled')).not_to_be_checked()
    assert errors == []


def test_managed_market_routes_validate_directories_before_sending(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        state.setup = {setup_required: false};
        setView('bindings');
        openBindingDialog();
    }""")
    saved = []
    def respond(route):
        saved.append(route.request.post_data_json)
        route.fulfill(json={'ok': False, 'error': 'Unexpected save'})
    page.route('**/api/account-config', respond)
    page.locator('#bindingAccountId').fill('1000000001')
    page.locator('#bindingQmtDir').fill('D:/FAKE-QMT')
    page.locator('#bindingMarketRoutingEnabled').check()
    page.locator('#bindingForm button[type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).to_be_visible()
    expect(page.locator('#bindingMarketShQmtDir')).to_be_focused()
    assert saved == []
    assert page.locator('body').inner_text().find('SH/SZ') >= 0
    assert errors == []
