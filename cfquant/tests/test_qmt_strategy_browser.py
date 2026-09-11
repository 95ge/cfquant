"""Managed strategy controls and progress with mocked APIs, on desktop/mobile."""

from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url, open_app, page


def test_project_update_notice_handles_editable_install(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    result = page.evaluate("""() => {
        const payload = {
            current_version: '9.9.9-test',
            editable_install: {attempted: true, ok: true, installed_version: '9.9.9-test'},
            qmt_core_deploy: {summary: {ok: true, target_count: 1}},
            qmt_restart_required: {required: true, message: '请重启 QMT'},
        };
        const model = buildUpdateNoticeModel(payload, {forceQmtRestart: true});
        renderUpdateNotice('projectUpdateNoticeBox', payload, {forceQmtRestart: true});
        return {
            title: model && model.title,
            editableVersion: model && model.editableInstall && model.editableInstall.installed_version,
            notice: document.querySelector('#projectUpdateNoticeBox').innerText,
        };
    }""")
    assert result["title"] == "更新完成，请重启 QMT"
    assert result["editableVersion"] == "9.9.9-test"
    assert "源码安装" in result["notice"]
    assert errors == []


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


def test_binding_sends_qmt_auto_start_request_with_restart_times(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        state.setup = {setup_required: false};
        setView('bindings');
        openBindingDialog();
    }""")
    expect(page.locator('#bindingQmtAutoLogin')).not_to_be_checked()
    page.locator('#bindingDisplayName').fill('国金证券')
    expect(page.locator('#bindingQmtAutoLogin')).not_to_be_checked()
    page.locator('#bindingQmtAutoLogin').check()
    expect(page.locator('#bindingQmtAutoLoginSettings')).to_be_visible()
    page.locator('#addBindingQmtRestartTimeBtn').click()
    page.locator('.binding-qmt-restart-time').nth(0).fill('06:30')
    page.locator('#addBindingQmtRestartTimeBtn').click()
    page.locator('.binding-qmt-restart-time').nth(1).fill('12:05')
    page.locator('#bindingAccountId').fill('8885060548')
    page.locator('#bindingQmtDir').fill('D:\\国金证券QMT交易端\\bin.x64')
    saved = []
    def respond(route):
        payload = route.request.post_data_json
        saved.append(payload)
        key = 'default:STOCK:8885060548'
        row = dict(payload, account_key=key, bridge_id='default')
        route.fulfill(json={'ok': True, 'data': {'account': row, 'account_configs': {key: row},
            'account_pairs': {}, 'bridges': {'default': {'name': 'default'}},
            'qmt_core_deploy': {'results': [], 'summary': {'message': ''}},
            'qmt_auto_login': {'enabled': True, 'started': True, 'pid': 1234,
                'launch_pid': 1234, 'restart_times': ['06:30', '12:05'],
                'message': 'started'}}})
    page.route('**/api/account-config', respond)
    page.locator('#bindingForm button[type="submit"]').click()
    expect(page.locator('#bindingQmtGuideOverlay')).to_be_visible()
    expect(page.locator('#bindingQmtAutoLoginPanel')).to_be_visible()
    expect(page.locator('#bindingQmtAutoLoginStatus')).to_contain_text('1234')
    assert saved[0]['qmt_auto_login'] == {'enabled': True, 'restart_times': ['06:30', '12:05']}
    assert errors == []


def test_binding_can_set_shared_quote_provider_from_list(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    old_key = "acct_4b2b38c167:CREDIT:900010001595"
    guojin_key = "default:STOCK:8885060548"
    page.evaluate("""([oldKey, guojinKey]) => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        state.setup = {
            setup_required: false,
            default_account_key: guojinKey,
            default_account_id: '8885060548',
            data_provider_account_key: oldKey,
            data_provider_account_id: '900010001595',
            data_provider_account_type: 'CREDIT',
        };
        state.defaultAccountKey = guojinKey;
        state.defaultAccountId = '8885060548';
        state.bridges = {
            acct_4b2b38c167: {name: '旧行情桥'},
            default: {name: 'default'},
        };
        state.accountConfigs = {
            [oldKey]: {
                account_id: '900010001595',
                account_type: 'CREDIT',
                account_key: oldKey,
                bridge_id: 'acct_4b2b38c167',
                display_name: '旧行情源',
                mode: 'ctypes',
                enabled: true,
                data_provider: true,
                qmt_dir: 'D:/OLD-QMT',
            },
            [guojinKey]: {
                account_id: '8885060548',
                account_type: 'STOCK',
                account_key: guojinKey,
                bridge_id: 'default',
                display_name: '国金证券',
                mode: 'ctypes',
                enabled: true,
                data_provider: false,
                qmt_dir: 'D:/GUOJIN-QMT',
            },
        };
        state.accountPairs = {};
        setView('bindings');
        renderAccountPairs();
        renderCachedBindingStatuses();
    }""", [old_key, guojin_key])
    saved = []

    def respond_provider(route):
        payload = route.request.post_data_json
        saved.append(payload)
        old_row = {
            "account_id": "900010001595",
            "account_type": "CREDIT",
            "account_key": old_key,
            "bridge_id": "acct_4b2b38c167",
            "display_name": "旧行情源",
            "mode": "ctypes",
            "enabled": True,
            "data_provider": False,
            "qmt_dir": "D:/OLD-QMT",
        }
        guojin_row = {
            "account_id": "8885060548",
            "account_type": "STOCK",
            "account_key": guojin_key,
            "bridge_id": "default",
            "display_name": "国金证券",
            "mode": "ctypes",
            "enabled": True,
            "data_provider": True,
            "qmt_dir": "D:/GUOJIN-QMT",
        }
        route.fulfill(json={"ok": True, "data": {
            "account": guojin_row,
            "setup": {
                "setup_required": False,
                "default_account_key": guojin_key,
                "default_account_id": "8885060548",
                "default_account_type": "STOCK",
                "data_provider_account_key": guojin_key,
                "data_provider_account_id": "8885060548",
                "data_provider_account_type": "STOCK",
            },
            "account_configs": {old_key: old_row, guojin_key: guojin_row},
            "account_pairs": {},
            "bridges": {"acct_4b2b38c167": {"name": "旧行情桥"}, "default": {"name": "default"}},
        }})

    def respond_status(route):
        route.fulfill(json={"ok": True, "data": {"bindings": [
            {"account_key": old_key, "account_id": "900010001595", "account_type": "CREDIT",
             "bridge_id": "acct_4b2b38c167", "status": {"normal": {"online": False}, "trade": {"online": False}}},
            {"account_key": guojin_key, "account_id": "8885060548", "account_type": "STOCK",
             "bridge_id": "default", "status": {"normal": {"online": False}, "trade": {"online": False}},
             "data_provider": True},
        ]}})

    page.route("**/api/setup/data-provider", respond_provider)
    page.route("**/api/bindings/status", respond_status)
    page.locator('#bindingStatusBody button[data-binding-action="set-data-provider"][data-account-id="8885060548"]').click()
    expect(page.locator("#bindingPageNotice")).to_contain_text("共享行情源已切换为 8885060548")
    result = page.evaluate("""([oldKey, guojinKey]) => ({
        requested: state.setup.data_provider_account_key,
        oldProvider: state.accountConfigs[oldKey].data_provider,
        guojinProvider: state.accountConfigs[guojinKey].data_provider,
        body: document.querySelector('#bindingStatusBody').innerText,
    })""", [old_key, guojin_key])
    assert saved == [{"account_id": "8885060548", "account_type": "STOCK",
                      "account_key": guojin_key, "bridge_id": "default"}]
    assert result["requested"] == guojin_key
    assert result["oldProvider"] is False
    assert result["guojinProvider"] is True
    assert "国金证券" in result["body"]
    assert result["body"].count("共享行情源") == 1
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
