"""First launch uses the same binding form as subsequent account additions."""
import pytest

from cfquant.tests.test_tutorial_reader import browser, page, frontend_url, open_app, expect


@pytest.mark.parametrize("setup_required", [True, False])
def test_empty_project_opens_binding_without_legacy_setup(page, frontend_url, setup_required):
    page.add_init_script("localStorage.setItem('cfquant.view', 'home')")
    requests, errors = open_app(page, frontend_url, setup_required=setup_required, legacy_entry=False)
    expect(page.locator('body')).to_have_attribute('data-view', 'bindings')
    expect(page.locator('#bindingDialogTitle')).to_have_text('添加账号绑定')
    expect(page.locator('#bindingAccountId')).to_have_value('')
    expect(page.locator('#setupOverlay')).not_to_be_visible()
    expect(page.locator('#onboardingWizard')).not_to_be_visible()
    page.locator('#closeBindingDialogBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('#openBindingDialogBtn').click()
    expect(page.locator('#bindingDialogTitle')).to_have_text('添加账号绑定')
    assert all(method == 'GET' for method, _ in requests)
    assert not errors


def test_existing_binding_does_not_trigger_wizard_on_new_browser(page, frontend_url):
    page.add_init_script("localStorage.setItem('cfquant.view', 'bindings')")
    _, errors = open_app(page, frontend_url, setup_required=False, legacy_entry=False,
                         account_configs={'saved': {'account_id': 'TEST_ONLY', 'bridge_id': 'test'}})
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    expect(page.locator('#setupOverlay')).not_to_be_visible()
    expect(page.locator('#onboardingWizard')).not_to_be_visible()
    page.reload()
    page.wait_for_function('state.appStarted')
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    expect(page.locator('#onboardingWizard')).not_to_be_visible()
    assert not errors


def test_first_binding_saves_through_account_config_api(page, frontend_url):
    requests, errors = open_app(page, frontend_url, legacy_entry=False)
    saved = []
    def save(route):
        body = route.request.post_data_json
        saved.append(body)
        row = dict(body, account_key='TEST_ONLY|STOCK|test', bridge_id='test')
        route.fulfill(json={'ok': True, 'data': {
            'account': row, 'account_configs': {row['account_key']: row}, 'account_pairs': {},
            'bridges': {'test': {'name': 'Test'}}, 'setup': {'setup_required': False},
            'qmt_auto_login': {'enabled': False}, 'qmt_strategy_deploy': {'enabled': False}}})
    page.route('**/api/account-config', save)
    page.locator('#bindingAccountId').fill('TEST_ONLY')
    page.locator('#bindingQmtAutoLogin').uncheck()
    page.evaluate("fillQmtStrategySettings('binding', {enabled: false})")
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert len(saved) == 1
    assert not page.evaluate('state.setup.setup_required')
    assert not any(path == '/api/setup/initialize' for _, path in requests)
    assert not errors
