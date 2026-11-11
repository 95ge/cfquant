"""VM/MAC binding controls exercised with offline API fixtures."""
from pathlib import Path

from cfquant.tests.test_tutorial_reader import browser, page, frontend_url, expect
from cfquant.tests.test_binding_runtime_browser import open_bindings


def open_new(page, frontend_url):
    requests, errors = open_bindings(page, frontend_url)
    page.locator('#openBindingDialogBtn').click()
    page.locator('#bindingAccountId').fill('VM_TEST')
    page.locator('#bindingQmtDir').fill('D:\\QMT-TEST')
    page.locator('#bindingQmtAutoLogin').uncheck()
    page.evaluate("fillQmtStrategySettings('binding', {enabled: false})")
    page.locator('#bindingVmSettingsToggle').click()
    return requests, errors


def test_vm_mac_defaults_roundtrip_disable_and_isolation(page, frontend_url):
    _, errors = open_new(page, frontend_url)
    expect(page.locator('#bindingDisableVm')).not_to_be_checked()
    expect(page.locator('#bindingInjectMac')).not_to_be_checked()
    expect(page.locator('#bindingMacAddress')).to_have_value('')
    page.locator('#bindingInjectMac').check()
    page.locator('#bindingMacAddress').fill('02:aa:bb:cc:dd:ee')
    saved = []

    def save(route):
        payload = route.request.post_data_json
        saved.append(payload)
        row = dict(payload, account_key='test:STOCK:VM_TEST', bridge_id='test')
        route.fulfill(json={'ok': True, 'data': {'account': row,
            'account_configs': {row['account_key']: row}, 'account_pairs': {},
            'bridges': {'test': {'name': 'Test'}}, 'qmt_auto_login': {'enabled': False}}})

    page.route('**/api/account-config', save)
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert saved[-1]['qmt_vm'] == {'disable_vm': False, 'inject_mac': True, 'mac_address': '02-AA-BB-CC-DD-EE'}
    page.evaluate("closeBindingQmtGuide(); openBindingDialog({accountKey: 'test:STOCK:VM_TEST'})")
    page.locator('#bindingVmSettingsToggle').click()
    expect(page.locator('#bindingMacAddress')).to_have_value('02-AA-BB-CC-DD-EE')
    expect(page.locator('#bindingInjectMac')).to_be_checked()
    page.locator('#bindingDisableVm').check()
    folder = Path(__file__).resolve().parents[2] / 'runtime/screenshots'
    folder.mkdir(parents=True, exist_ok=True)
    page.locator('#bindingVmSettings').screenshot(path=str(folder / ('binding-vm-%s.png' % page.viewport_size['width'])))
    assert page.locator('#bindingVmSettings').evaluate('el => el.scrollWidth <= el.clientWidth')
    page.locator('#bindingInjectMac').uncheck()
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert saved[-1]['qmt_vm'] == {'disable_vm': True, 'inject_mac': False, 'mac_address': '02-AA-BB-CC-DD-EE'}
    page.evaluate("closeBindingQmtGuide(); openBindingDialog({accountKey: 'test:STOCK:VM_TEST'})")
    page.locator('#bindingVmSettingsToggle').click()
    page.locator('#bindingDisableVm').uncheck()
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert saved[-1]['qmt_vm'] == {'disable_vm': False, 'inject_mac': False, 'mac_address': '02-AA-BB-CC-DD-EE'}
    page.evaluate("closeBindingQmtGuide(); openBindingDialog()")
    page.locator('#bindingVmSettingsToggle').click()
    expect(page.locator('#bindingDisableVm')).not_to_be_checked()
    expect(page.locator('#bindingInjectMac')).not_to_be_checked()
    expect(page.locator('#bindingMacAddress')).to_have_value('')
    assert errors == []


def test_bad_mac_blocks_save_and_process_operations(page, frontend_url):
    requests, errors = open_new(page, frontend_url)
    page.locator('#bindingInjectMac').check()
    for invalid in ('', '01-11-22-33-44-55', '00-00-00-00-00-00', 'invalid'):
        page.locator('#bindingMacAddress').fill(invalid)
        page.locator('#bindingForm [type="submit"]').click()
        expect(page.locator('#bindingSaveStatus')).to_contain_text('有效的非零单播 MAC')
        expect(page.locator('#bindingDialogOverlay')).to_be_visible()
    assert not any(method == 'POST' and path in ('/api/account-config', '/api/qmt/processes/stop') for method, path in requests)
    assert errors == []


def test_old_backend_cannot_silently_discard_enabled_settings(page, frontend_url):
    _, errors = open_new(page, frontend_url)
    page.locator('#bindingDisableVm').check()
    def old_backend(route):
        row = route.request.post_data_json
        row.pop('qmt_vm')
        route.fulfill(json={'ok': True, 'data': {'account': row}})
    page.route('**/api/account-config', old_backend)
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingSaveStatus')).to_contain_text('虚拟机与 MAC 设置未被后端保存')
    expect(page.locator('#bindingDialogOverlay')).to_be_visible()
    assert errors == []
