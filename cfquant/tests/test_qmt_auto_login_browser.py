"""Binding credential input and login status in desktop/mobile browsers."""
import pytest

from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url, open_app, page


def open_binding(page):
    page.evaluate("""() => {
      document.querySelector('#setupOverlay').classList.add('hidden');
      state.setup = {setup_required: false};
      setView('bindings'); openBindingDialog();
    }""")
    page.locator('#bindingAccountId').fill('fixture-fund')
    page.locator('#bindingQmtDir').fill('D:/QMT-FAKE')


@pytest.mark.parametrize('entry', ['setup', 'onboarding', 'binding'])
def test_auto_restart_requires_credentials_before_save_or_stop(page, frontend_url, entry):
    requests, errors = open_app(page, frontend_url, setup_required=entry == 'setup')
    if entry == 'binding':
        open_binding(page)
    else:
        if entry == 'onboarding':
            page.locator('#onboardingStartConfigBtn').click()
        page.locator(f'#{entry}AccountId').fill('fixture-fund')
        page.locator(f'#{entry}QmtDir').fill('D:/QMT-FAKE')
    expect(page.locator(f'#{entry}QmtAutoLogin')).to_be_checked()
    button = page.locator('#bindingForm [type="submit"]' if entry == 'binding' else
                          '#setupForm [type="submit"]' if entry == 'setup' else '#onboardingSaveConfigBtn')
    status = page.locator('#bindingSaveStatus' if entry == 'binding' else
                          '#setupStatus' if entry == 'setup' else '#onboardingConfigStatus')
    button.click()
    expect(status).to_contain_text('必须填写 QMT 登录账号')
    page.locator(f'#{entry}QmtLoginAccount').fill('fixture-login')
    button.click()
    expect(status).to_contain_text('必须填写 QMT 登录密码')
    assert not any(method == 'POST' and path in ('/api/account-config', '/api/setup/initialize', '/api/qmt/processes/stop')
                   for method, path in requests)
    page.locator(f'#{entry}QmtAutoLogin').uncheck()
    assert page.evaluate('(prefix) => qmtLoginValidationError(prefix, {enabled:false}, "")', entry) == ''
    assert errors == []


@pytest.mark.parametrize('entry', ['setup', 'onboarding', 'binding'])
def test_password_show_hide_works_for_typed_value(page, frontend_url, entry):
    _, errors = open_app(page, frontend_url, setup_required=entry == 'setup')
    if entry == 'binding':
        open_binding(page)
    elif entry == 'onboarding':
        page.locator('#onboardingStartConfigBtn').click()
    password = page.locator(f'#{entry}QmtLoginPassword')
    button = page.locator(f'#{entry}QmtPasswordToggle')
    password.fill('synthetic-typed-secret')
    button.click()
    expect(password).to_have_attribute('type', 'text')
    expect(password).to_have_value('synthetic-typed-secret')
    button.click()
    expect(password).to_have_attribute('type', 'password')
    assert 'synthetic-typed-secret' not in page.evaluate('JSON.stringify(state) + JSON.stringify(localStorage)')
    assert errors == []


def saved_binding(page):
    page.evaluate("""() => {
      const row = {account_key:'fixture', account_id:'fixture-fund', bridge_id:'default',
        qmt_dir:'D:/QMT-FAKE', qmt_auto_login:{enabled:true, restart_times:['09:00'], login_account:'fixture-login', password_saved:true}};
      state.accountConfigs = {fixture:row};
      document.querySelector('#setupOverlay').classList.add('hidden');
      openBindingDialog({accountKey:'fixture'});
    }""")


@pytest.mark.parametrize('entry', ['setup', 'onboarding', 'binding'])
def test_new_bindings_default_all_automation_checked(page, frontend_url, entry):
    _, errors = open_app(page, frontend_url, setup_required=entry == 'setup')
    if entry == 'binding':
        open_binding(page)
    elif entry == 'onboarding':
        page.locator('#onboardingStartConfigBtn').click()
    for suffix in ('QmtAutoLogin', 'QmtAutoUpdate', 'StrategyEnabled', 'StrategyAutorun'):
        expect(page.locator(f'#{entry}{suffix}')).to_be_checked()
    page.locator(f'#{entry}QmtAutoUpdate').uncheck()
    settings = page.evaluate('readBindingQmtAutoLoginSettings()') if entry == 'binding' else None
    if settings is not None:
        assert settings['auto_update'] is False
    assert errors == []


def test_existing_binding_explicit_disabled_and_missing_update_stay_off(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    saved_binding(page)
    expect(page.locator('#bindingQmtAutoUpdate')).not_to_be_checked()
    page.evaluate('''() => {
        closeBindingDialog();
        state.accountConfigs.fixture.qmt_auto_login = {enabled:false, auto_update:false};
        state.accountConfigs.fixture.qmt_strategy = {enabled:false, autorun:false};
        openBindingDialog({accountKey:'fixture'});
    }''')
    for suffix in ('QmtAutoLogin', 'QmtAutoUpdate', 'StrategyEnabled', 'StrategyAutorun'):
        expect(page.locator('#binding' + suffix)).not_to_be_checked()
    assert errors == []


def test_edit_reveals_saved_password_only_on_click_and_clears_on_close(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    calls = []
    def reveal(route):
        calls.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'data': {'password': 'synthetic-saved-secret'}})
    page.route('**/api/account-config/qmt-password', reveal)
    saved_binding(page)
    password = page.locator('#bindingQmtLoginPassword')
    button = page.locator('#bindingQmtPasswordToggle')
    expect(password).to_have_value('')
    expect(button).to_have_text('查看已保存密码')
    assert calls == []
    assert page.evaluate('qmtLoginValidationError("binding", readBindingQmtAutoLoginSettings(), "D:/QMT-FAKE")') == ''
    button.click()
    expect(password).to_have_value('synthetic-saved-secret')
    expect(password).to_have_attribute('type', 'text')
    assert calls[0]['account_key'] == 'fixture'
    assert 'password' not in page.evaluate('readBindingQmtAutoLoginSettings()')
    assert 'synthetic-saved-secret' not in page.evaluate('JSON.stringify(state) + JSON.stringify(localStorage)')
    button.click()
    expect(password).to_have_value('')
    button.click()
    expect(password).to_have_value('synthetic-saved-secret')
    page.evaluate('closeBindingDialog()')
    expect(password).to_have_value('')
    page.evaluate('openBindingDialog({accountKey:"fixture"})')
    expect(password).to_have_attribute('type', 'password')
    page.locator('#bindingQmtLoginAccount').fill('other-login')
    expect(button).to_be_disabled()
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingSaveStatus')).to_contain_text('必须填写 QMT 登录密码')
    page.locator('#bindingQmtLoginAccount').fill('fixture-login')
    page.locator('#bindingQmtDir').fill('D:/OtherQMT')
    expect(button).to_be_disabled()
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingSaveStatus')).to_contain_text('必须填写 QMT 登录密码')
    assert errors == []


def test_late_reveal_cannot_populate_reopened_form(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    saved_binding(page)
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = (url, options) => url === '/api/account-config/qmt-password'
        ? new Promise(resolve => { window.finishReveal = () => resolve(new Response(JSON.stringify({ok:true, data:{password:'synthetic-late-secret'}}))); })
        : original(url, options);
    }""")
    page.locator('#bindingQmtPasswordToggle').click()
    expect(page.locator('#bindingQmtPasswordToggle')).to_have_text('读取中…')
    page.evaluate('closeBindingDialog(); openBindingDialog({accountKey:"fixture"}); finishReveal();')
    expect(page.locator('#bindingQmtLoginPassword')).to_have_value('')
    expect(page.locator('#bindingQmtPasswordToggle')).to_have_text('查看已保存密码')
    assert errors == []


def test_binding_credentials_are_sent_once_and_never_refilled(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
      document.querySelector('#setupOverlay').classList.add('hidden');
      state.setup = {setup_required: false};
      setView('bindings'); openBindingDialog();
    }""")
    expect(page.locator('.binding-qmt-restart-time')).to_have_value('09:00')
    page.locator('#bindingAccountId').fill('fixture-fund')
    page.locator('#bindingQmtDir').fill('D:\\QMT-FAKE')
    page.locator('#bindingQmtLoginAccount').fill('fixture-login')
    page.locator('#bindingQmtLoginPassword').fill('synthetic-secret')
    saved = []
    def respond(route):
        payload = route.request.post_data_json
        saved.append(payload)
        settings = dict(payload['qmt_auto_login'])
        settings.pop('password')
        settings['password_saved'] = True
        key = 'default:STOCK:fixture-fund'
        row = dict(payload, qmt_auto_login=settings, account_key=key, bridge_id='default')
        route.fulfill(json={'ok': True, 'data': {'account': row, 'account_configs': {key: row},
            'account_pairs': {}, 'bridges': {}, 'qmt_auto_login': dict(settings, pid=1234, login_state='logging_in')}})
    page.route('**/api/account-config', respond)
    page.locator('#bindingForm button[type="submit"]').click()
    expect(page.locator('#bindingQmtGuideOverlay')).to_be_visible()
    expect(page.locator('#bindingQmtAutoLoginStatus')).to_contain_text('正在登录')
    assert saved[0]['qmt_auto_login']['password'] == 'synthetic-secret'
    assert saved[0]['qmt_auto_login']['login_account'] == 'fixture-login'
    assert 'synthetic-secret' not in page.evaluate('JSON.stringify(state) + JSON.stringify(localStorage)')
    page.evaluate("""() => { closeBindingQmtGuide(); openBindingDialog({accountKey:'default:STOCK:fixture-fund'}); }""")
    expect(page.locator('#bindingQmtLoginPassword')).to_have_value('')
    expect(page.locator('#bindingQmtLoginAccount')).to_have_value('fixture-login')
    expect(page.locator('#bindingQmtPasswordStatus')).to_contain_text('已保存加密密码')
    assert errors == []


def test_login_result_is_visible_in_status_panel(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    result = page.evaluate("""() => ({
      success: bindingQmtAutoLoginStatusHtml({enabled:true,pid:1234,login_succeeded:true,message:'自动登录完成'}),
      failure: bindingQmtAutoLoginStatusHtml({enabled:true,pid:1234,error:'密码被拒绝',message:'请修改保存的密码'})
    })""")
    assert '已登录' in result['success']
    assert '请修改保存的密码' in result['failure']
    assert errors == []


def test_dependency_failure_shows_repair_command_and_manual_login_action(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    saved_binding(page)
    page.evaluate("""() => {
      state.qmtLoginDependencies = null;
      renderQmtDependencyStatus({
        supported: true, ok: false, python_executable: 'C:/Python311/python.exe',
        environment: 'python', python_version: '3.11.9',
        checks: [{name: 'win32api', ok: false, error: 'DLL load failed while importing win32api'}],
        repair_commands: ["& 'C:/Python311/python.exe' -m pip install --force-reinstall pywin32"],
        repair_note: '先停止 CFQuant 后执行。',
        message: 'QMT 自动登录组件不可用（win32api）。',
      });
    }""")
    panel = page.locator('#bindingQmtDependencies')
    expect(panel).to_be_visible()
    expect(panel).to_contain_text('win32api')
    expect(panel).to_contain_text('C:/Python311/python.exe')
    expect(panel.locator('[data-qmt-dependency-action="manual"]')).to_have_count(1)
    panel.locator('[data-qmt-dependency-action="manual"]').click()
    expect(page.locator('#bindingQmtAutoLogin')).not_to_be_checked()
    assert errors == []


@pytest.mark.parametrize('entry', ['setup', 'onboarding', 'binding'])
def test_client_login_option_disables_credentials_and_dependency_requirement(page, frontend_url, entry):
    _, errors = open_app(page, frontend_url, setup_required=entry == 'setup')
    if entry == 'binding':
        open_binding(page)
    elif entry == 'onboarding':
        page.locator('#onboardingStartConfigBtn').click()
    option = page.locator(f'#{entry}QmtAutoFillCredentials')
    expect(option).to_be_checked()
    page.locator(f'#{entry}QmtLoginPassword').fill('synthetic-unused')
    page.locator(f'#{entry}QmtPasswordToggle').click()
    page.evaluate("renderQmtDependencyStatus({ok:false, supported:true, message:'fixture unavailable'})")
    option.uncheck()
    expect(page.locator(f'#{entry}QmtAutoLogin')).to_be_checked()
    expect(page.locator(f'#{entry}QmtLoginAccount')).to_be_disabled()
    expect(page.locator(f'#{entry}QmtLoginPassword')).to_be_disabled()
    expect(page.locator(f'#{entry}QmtPasswordToggle')).to_be_disabled()
    expect(page.locator(f'#{entry}QmtDependencies')).not_to_be_visible()
    expect(page.locator(f'#{entry}QmtPasswordStatus')).to_contain_text('仅记住密码')
    assert page.evaluate("""prefix => qmtLoginValidationError(prefix,
        {enabled:true, auto_fill_credentials:qmtAutoFillCredentials(prefix)}, 'D:/QMT-FAKE')""", entry) == ''
    assert 'QMT 目录' in page.evaluate("""prefix => qmtLoginValidationError(prefix,
        {enabled:true, auto_fill_credentials:qmtAutoFillCredentials(prefix)}, '')""", entry)
    if entry == 'binding':
        settings = page.evaluate('readBindingQmtAutoLoginSettings()')
        assert settings['auto_fill_credentials'] is False and 'password' not in settings
    elif entry == 'onboarding':
        assert page.evaluate('onboardingValues().qmt_auto_login.auto_fill_credentials') is False
    option.check()
    expect(page.locator(f'#{entry}QmtLoginAccount')).to_be_enabled()
    expect(page.locator(f'#{entry}QmtDependencies')).to_be_visible()
    assert errors == []


def test_binding_can_save_client_login_without_credentials_and_restore_selection(page, frontend_url, tmp_path):
    _, errors = open_app(page, frontend_url)
    open_binding(page)
    page.locator('#bindingQmtLoginPassword').fill('synthetic-unused')
    page.locator('#bindingQmtAutoFillCredentials').uncheck()
    saved = []
    def respond(route):
        payload = route.request.post_data_json
        saved.append(payload)
        settings = payload['qmt_auto_login']
        assert settings['enabled'] and settings['auto_fill_credentials'] is False
        assert 'password' not in settings and 'login_account' not in settings
        key = 'default:STOCK:fixture-fund'
        row = dict(payload, account_key=key, bridge_id='default')
        route.fulfill(json={'ok': True, 'data': {'account': row, 'account_configs': {key: row},
            'account_pairs': {}, 'bridges': {}, 'qmt_auto_login': dict(settings, pid=1234,
            login_state='client_login', message='由 QMT 自行登录')}})
    page.route('**/api/account-config', respond)
    page.locator('#bindingForm button[type="submit"]').click()
    expect(page.locator('#bindingQmtGuideOverlay')).to_be_visible()
    expect(page.locator('#bindingQmtAutoLoginStatus')).to_contain_text('由 QMT 自行登录')
    expect(page.locator('#bindingQmtLoginReminder')).to_contain_text('已关闭自动输入')
    assert len(saved) == 1
    page.evaluate("closeBindingQmtGuide(); openBindingDialog({accountKey:'default:STOCK:fixture-fund'});")
    expect(page.locator('#bindingQmtAutoFillCredentials')).not_to_be_checked()
    expect(page.locator('#bindingQmtLoginAccount')).to_be_disabled()
    expect(page.locator('.binding-qmt-restart-time')).to_have_value('09:00')
    expect(page.locator('#bindingQmtLoginPassword')).to_have_value('')
    page.locator('#bindingQmtAutoFillCredentials').scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / 'client-login-option.png'))
    assert page.locator('#bindingQmtAutoLoginSettings').evaluate('el => el.scrollWidth <= el.clientWidth')
    assert errors == []


def test_disabling_fill_discards_pending_saved_password_reveal(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    saved_binding(page)
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = (url, options) => url === '/api/account-config/qmt-password'
        ? new Promise(resolve => { window.finishReveal = () => resolve(new Response(JSON.stringify({ok:true, data:{password:'synthetic-late-secret'}}))); })
        : original(url, options);
    }""")
    page.locator('#bindingQmtPasswordToggle').click()
    expect(page.locator('#bindingQmtPasswordToggle')).to_have_text('读取中…')
    page.locator('#bindingQmtAutoFillCredentials').uncheck()
    page.evaluate('finishReveal()')
    expect(page.locator('#bindingQmtLoginPassword')).to_have_value('')
    expect(page.locator('#bindingQmtPasswordToggle')).to_be_disabled()
    assert 'password' not in page.evaluate('readBindingQmtAutoLoginSettings()')
    assert errors == []


def test_manual_compatibility_fallback_shows_warning_and_keeps_auto_fill_preference(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    saved_binding(page)
    page.evaluate("""() => {
      renderBindingQmtAutoLoginStatus({enabled:true, auto_fill_credentials:true,
        effective_auto_fill_credentials:false, pid:1234, login_degraded:true,
        login_succeeded:false, login_state:'manual_login_required',
        message:'Qt 5.15.3 暂未适配，请手动登录；原设置保留。', restart_times:['09:00']});
    }""")
    panel = page.locator('#bindingQmtAutoLoginStatus')
    expect(panel.locator('.is-warn b')).to_have_text('等待手动登录')
    expect(panel).to_contain_text('Qt 5.15.3')
    expect(panel).to_contain_text('原设置保留')
    expect(panel.locator('.is-success')).to_have_count(0)
    expect(page.locator('#bindingQmtAutoFillCredentials')).to_be_checked()
    assert errors == []
