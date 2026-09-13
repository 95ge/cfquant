"""Managed strategy controls and progress with mocked APIs, on desktop/mobile."""

import pytest

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


def test_project_reload_waits_for_health_before_marking_progress_done(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    health_requests = []
    page.route("**/api/health*", lambda route: (
        health_requests.append(route.request.url),
        route.fulfill(json={"ok": True, "data": {"status": "ok"}}),
    ))

    result = page.evaluate("""async () => {
        openQmtUpdateProgress('project-official', 'Reload test', 'Installing');
        const outcome = await handleProjectReload(
            {next_url: window.location.href},
            'Reloading web',
            {current_version: 'reload-test'},
            {navigate: false, initialDelayMs: 0, pollIntervalMs: 20, timeoutMs: 500}
        );
        const progress = state.qmtUpdateProgress || {};
        return {
            outcome,
            status: progress.status || '',
            detail: progress.detail || '',
            percent: progress.percent || 0,
            visible: !document.querySelector('#qmtUpdateProgressOverlay').classList.contains('hidden'),
        };
    }""")

    assert result["outcome"]["reloaded"] is True
    assert result["status"] == "done"
    assert result["percent"] == 100
    assert result["visible"] is True
    assert "Web" in result["detail"]
    assert health_requests
    assert errors == []


def test_binding_sends_strategy_flags_and_displays_pending_deployment(page, frontend_url, tmp_path):
    requests, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        state.setup = {setup_required: false};
        setView('bindings');
        openBindingDialog();
    }""")
    expect(page.locator('#bindingStrategyEnabled')).to_be_checked()
    expect(page.locator('#bindingStrategyAutorun')).to_be_checked()
    expect(page.locator('#bindingStrategyRunMode')).to_have_value('1')
    page.locator('#bindingAccountId').fill('1000000001')
    page.locator('#bindingQmtDir').fill('D:\\QMT-FAKE')
    page.locator('#bindingMode').select_option('lite')
    page.locator('#bindingStrategyRunMode').select_option('1')
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
    assert saved[0]['qmt_dir'].endswith('\\bin.x64')
    assert saved[0]['qmt_strategy'] == {'enabled': True, 'live': True, 'autorun': True,
        'stock': 'SH000300', 'account_keys': {'normal': '2____101____201____49____1000000001____',
                                            'trade': '', 'SH': '', 'SZ': ''}}
    expect(page.locator('#bindingQmtGuideOverlay')).to_be_visible()
    expect(page.locator('#bindingQmtGuideInstruction')).to_contain_text('请正常退出')
    expect(page.locator('#bindingQmtGuideOverlay [data-qmt-script-copy]')).to_have_count(0)
    assert page.locator('body').inner_text().find('Waiting for QMT exit') >= 0
    page.route('**/api/status*', lambda route: route.fulfill(json={
        'ok': True,
        'data': {
            'account_id': '1000000001',
            'account_type': 'STOCK',
            'bridge_id': 'bridge',
            'status': {'normal': {'online': True}, 'trade': {'online': True}},
            'market_routing_enabled': False,
        },
    }))
    page.locator('#checkBindingQmtConnectionBtn').click()
    expect(page.locator('#bindingQmtGuideOverlay')).to_be_visible()
    expect(page.locator('#bindingQmtLoginCheckStatus')).to_contain_text('在线')
    expect(page.locator('#bindingQmtGuideInstruction')).to_contain_text('检测成功')
    page.locator('#backBindingQmtGuideBtn').click()
    expect(page.locator('#bindingDialogOverlay')).to_be_visible()
    expect(page.locator('#bindingQmtDir')).to_have_value('D:\\QMT-FAKE\\bin.x64')
    expect(page.locator('#bindingQmtAutoLogin')).to_be_checked()
    expect(page.locator('#bindingStrategyAutorun')).to_be_checked()
    page.locator('#cancelBindingDialogBtn').click()
    expect(page.locator('#bindingQmtGuideOverlay')).not_to_be_visible()
    expect(page.locator('#onboardingWizard')).not_to_be_visible()
    assert not page.evaluate('state.onboardingBindingFlowActive')
    assert not any(path == '/api/qmt-scripts/source' for _, path in requests)
    assert errors == []


@pytest.mark.parametrize('entry', ['setup', 'onboarding'])
def test_initialization_saves_credit_account_and_shows_login_reminder(page, frontend_url, tmp_path, entry):
    requests, errors = open_app(page, frontend_url, setup_required=entry == 'setup')
    if entry == 'onboarding':
        page.locator('#onboardingStartConfigBtn').click()
    if entry == 'setup' and page.locator('#setupAdminUsername').is_visible():
        page.locator('#setupAdminUsername').fill('test-admin')
        page.locator('#setupAdminPassword').fill('test-password')
        page.locator('#setupAdminPasswordConfirm').fill('test-password')
    page.locator(f'#{entry}AccountId').fill('900010001595')
    page.locator(f'#{entry}AccountType').select_option('CREDIT')
    page.locator(f'#{entry}QmtDir').fill('D:/GUOJIN-QMT-FAKE/bin.x64')
    expect(page.locator(f'#{entry}QmtAutoLogin')).to_be_checked()
    expect(page.locator(f'#{entry}StrategyAutorun')).to_be_checked()
    saved = []

    def respond(route):
        payload = route.request.post_data_json
        saved.append(payload)
        key = 'default:CREDIT:900010001595'
        row = {name: payload[name] for name in (
            'account_id', 'account_type', 'mode', 'qmt_dir', 'qmt_strategy', 'qmt_auto_login')}
        row.update(account_key=key, bridge_id='default')
        data = {'account': row, 'account_configs': {key: row}, 'account_pairs': {},
            'bridges': {'default': {'name': 'default'}},
            'setup': {'setup_required': False, 'default_account_key': key,
                      'default_account_id': row['account_id'], 'default_account_type': 'CREDIT'},
            'server_access': {'web_auth_enabled': False},
            'qmt_core_deploy': {'results': [{'updated': True, 'python_dir': row['qmt_dir']} ]},
            'qmt_strategy_deploy': {'enabled': True, 'targets': [{'state': 'waiting_start',
                'strategies': ['CFQ_TEST'], 'message': '等待托管策略启动及通道连接'}]},
            'qmt_auto_login': {'enabled': True, 'started': True, 'pid': 1234}}
        page.route('**/api/config', lambda route: route.fulfill(json={'ok': True, 'data': data}))
        route.fulfill(json={'ok': True, 'data': data})

    endpoint = 'setup/initialize' if entry == 'setup' else 'account-config'
    page.route(f'**/api/{endpoint}', respond)
    page.locator('#setupForm button[type="submit"]' if entry == 'setup' else '#onboardingSaveConfigBtn').click()
    expect(page.locator('#bindingQmtGuideOverlay')).to_be_visible()
    assert len(saved) == 1
    assert saved[0]['account_type'] == 'CREDIT'
    assert saved[0]['qmt_auto_login']['enabled'] is True
    if entry == 'setup':
        assert 'admin_username' not in saved[0]
        assert 'admin_password' not in saved[0]
    expect(page.locator('#bindingQmtGuideInstruction')).to_contain_text('已勾选自动启动 QMT')
    expect(page.locator('#bindingQmtLoginReminder')).to_contain_text('等待自动登录完成')
    expect(page.locator('#bindingQmtLoginReminder')).to_contain_text('请手动输入密码登录')
    assert not any(path == '/api/qmt-scripts/source' for _, path in requests)
    expect(page.locator('#copyBindingQmtGuideBtn, #onboardingCopyQmtScriptBtn, #copyBindingQmtScriptBtn')).to_have_count(0)
    assert page.locator('.binding-qmt-guide-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    expect(page.locator('#bindingQmtGuideTitle')).to_be_in_viewport()
    page.screenshot(path=str(tmp_path / 'qmt-startup-reminder.png'))
    page.route('**/api/status*', lambda route: route.fulfill(json={
        'ok': True,
        'data': {
            'account_id': '900010001595',
            'account_type': 'CREDIT',
            'bridge_id': 'default',
            'status': {'normal': {'online': True}, 'trade': {'online': True}},
            'market_routing_enabled': False,
        },
    }))
    page.locator('#checkBindingQmtConnectionBtn').click()
    expect(page.locator('#bindingQmtGuideOverlay')).to_be_visible()
    expect(page.locator('#bindingQmtLoginCheckPanel')).to_be_visible()
    expect(page.locator('#bindingQmtLoginCheckStatus')).to_contain_text('在线')
    expect(page.locator('#bindingQmtGuideInstruction')).to_contain_text('检测成功')
    page.locator('#backBindingQmtGuideBtn').click()
    expect(page.locator('#onboardingWizard')).to_be_visible()
    expect(page.locator('#onboardingConfigForm')).to_be_visible()
    expect(page.locator('#onboardingQmtDir')).to_have_value('D:/GUOJIN-QMT-FAKE/bin.x64')
    page.locator('#closeOnboardingBtn').click()
    expect(page.locator('#onboardingWizard')).not_to_be_visible()
    expect(page.locator('#bindingQmtGuideOverlay')).not_to_be_visible()
    assert errors == []


def test_setup_help_tooltip_is_clickable_and_admin_is_optional(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=True)
    expect(page.locator('#setupAdminFields')).not_to_be_visible()
    trigger = page.locator('#setupOverlay .help-tooltip-trigger').first
    trigger.click()
    assert trigger.get_attribute('aria-expanded') == 'true'
    assert trigger.evaluate("(node) => node.classList.contains('is-open')")
    page.locator('#setupOverlay').click(position={'x': 10, 'y': 10})
    assert trigger.get_attribute('aria-expanded') == 'false'
    assert errors == []


def test_startup_reminders_distinguish_pending_failure_disabled_and_manual_run(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    cases = [
        ({}, '请重启对应 QMT 并登录'),
        ({'enabled': False}, '账号绑定已停用'),
        ({'qmt_strategy': {'enabled': False}}, '自动导入并管理 QMT 策略未启用'),
        ({'qmt_strategy': {'enabled': True, 'autorun': False}}, '运行已导入的托管策略'),
        ({'qmt_auto_login': {'enabled': True, 'error': 'launch failed'}}, 'QMT 自动启动失败'),
        ({'qmt_strategy_deploy': {'error': 'permission denied'}}, '策略部署失败'),
        ({'qmt_strategy_deploy': {'targets': [{'state': 'error', 'error': 'invalid directory'}]}}, '策略部署失败'),
        ({'qmt_strategy_deploy': {'targets': [{'state': 'waiting_account'}]}}, '补充模型账号 Key'),
        ({'qmt_auto_login': {'enabled': True},
          'qmt_strategy_deploy': {'targets': [{'state': 'waiting_exit'}]}}, '等待绑定列表显示模型配置完成'),
        ({'qmt_auto_login': {'enabled': True},
          'qmt_strategy_deploy': {'targets': [{'state': 'waiting_import_save'}]}}, '请正常退出'),
        ({'mode': 'lttx', 'qmt_dir': 'D:/QMT', 'qmt_trade_dir': 'D:/TRADE',
          'qmt_auto_login': {'enabled': True}}, '其他目录的 QMT 请分别启动并登录'),
    ]
    for values, expected in cases:
        result = page.evaluate('(values) => qmtStartupInstruction(values)', values)
        assert expected in result
        assert '粘贴' not in result
    page.evaluate("""() => showBindingQmtGuide({
        qmt_strategy_deploy: {targets: [{state: 'error',
            strategies: ['CFQ_CTYPES_5CF95C06_NORMAL'], error: 'invalid directory'}]}
    })""")
    expect(page.locator('#bindingQmtStrategyStatus')).to_contain_text('CFQ_CTYPES_5CF95C06_NORMAL')
    expect(page.locator('#bindingQmtStrategyStatus')).to_contain_text('invalid directory')
    expect(page.locator('#bindingQmtGuideInstruction')).to_contain_text('invalid directory')
    assert errors == []


def test_web_settings_reset_password_displays_file_path_without_secret(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    page.evaluate("""() => {
        state.serverAccess = {web_auth_enabled: true, web_auth_username: 'admin',
            web_auth: {enabled: true, configured: true, username: 'admin'},
            web_auth_password_file: 'D:\\\\cfquant\\\\cfquant_web_reset_password.txt',
            configured_host: '127.0.0.1', configured_port: 8765, web_port: 8765,
            allow_remote: false, allowed_domains: []};
        hideOnboardingModal({force: true});
        setView('settings');
        setSettingsTab('web-access');
        renderServerAccess(state.serverAccess);
    }""")
    expect(page.locator('#resetWebAuthPasswordBtn')).to_be_visible()
    expect(page.locator('#webAuthPasswordFilePath')).to_contain_text('D:\\cfquant\\cfquant_web_reset_password.txt')
    page.on('dialog', lambda dialog: dialog.accept())
    page.route('**/api/web-auth/reset-password', lambda route: route.fulfill(json={
        'ok': True, 'data': {'username': 'admin',
            'password_file': r'D:\cfquant\cfquant_web_reset_password.txt',
            'message': '密码已重置'}}))
    page.locator('#resetWebAuthPasswordBtn').click()
    expect(page.locator('#webAuthResetStatus')).to_contain_text('D:\\cfquant\\cfquant_web_reset_password.txt')
    expect(page.locator('#webAuthPasswordFilePath')).to_contain_text('D:\\cfquant\\cfquant_web_reset_password.txt')
    expect(page.locator('#webAuthResetStatus')).not_to_contain_text('新密码')
    expect(page.locator('#webAuthOverlay')).to_be_visible()
    expect(page.locator('#webAuthLoginResetBtn')).to_be_visible()
    assert errors == []


def test_binding_sends_qmt_auto_start_request_with_restart_times(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        state.setup = {setup_required: false};
        setView('bindings');
        openBindingDialog();
    }""")
    expect(page.locator('#bindingQmtAutoLogin')).to_be_checked()
    page.locator('#bindingDisplayName').fill('国金证券')
    expect(page.locator('#bindingQmtAutoLogin')).to_be_checked()
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
    expect(page.locator('#bindingQmtGuideInstruction')).to_contain_text('已勾选自动启动 QMT')
    expect(page.locator('#bindingQmtLoginReminder')).to_contain_text('国金 QMT：请手动输入密码登录')
    expect(page.locator('#bindingQmtLoginReminder')).to_contain_text('非国金 QMT')
    assert saved[0]['qmt_auto_login'] == {'enabled': True, 'restart_times': ['06:30', '12:05']}
    assert saved[0]['qmt_dir'].endswith('\\bin.x64')
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
