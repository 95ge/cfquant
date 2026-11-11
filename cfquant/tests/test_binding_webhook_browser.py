"""Account Webhook editing and docs on desktop/mobile; all APIs are offline."""
import ast
import inspect

from cfquant import notify
from cfquant.tests.test_tutorial_reader import browser, page, frontend_url, expect
from cfquant.tests.test_binding_runtime_browser import open_bindings


def test_new_binding_webhook_save_edit_preserves_credentials_and_clears(page, frontend_url, tmp_path):
    _, errors = open_bindings(page, frontend_url)
    page.locator('#openBindingDialogBtn').click()
    page.locator('#bindingAccountId').fill('TEST_ONLY')
    page.evaluate("fillQmtStrategySettings('binding', {enabled: false})")
    page.locator('#bindingQmtAutoLogin').uncheck()
    expect(page.locator('#bindingWebhookFields')).not_to_be_visible()
    expect(page.locator('#bindingWebhookSaveBtn')).not_to_be_visible()
    page.locator('#bindingWebhookEnabled').check()
    page.locator('#bindingWebhookProvider').select_option('feishu')
    page.locator('#bindingWebhookUrl').fill('https://example.invalid/PRIVATE_TOKEN')
    page.locator('#bindingWebhookSecret').fill('PRIVATE_SECRET')
    saved = []
    rows = {}

    def save(route):
        body = route.request.post_data_json
        saved.append(body)
        row = dict(body, account_key='test:STOCK:TEST_ONLY', bridge_id='test', notification_webhook={
            'enabled': True, 'provider': 'feishu', 'url': '', 'secret': '',
            'url_configured': True, 'secret_configured': True})
        rows[row['account_key']] = row
        route.fulfill(json={'ok': True, 'data': {'account': row, 'account_configs': rows,
            'account_pairs': {}, 'bridges': {'test': {'name': 'Test'}},
            'qmt_strategy_deploy': {'enabled': False}, 'qmt_auto_login': {'enabled': False}}})

    page.route('**/api/account-config', save)
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator('#bindingDialogOverlay')).not_to_be_visible()
    assert saved[0]['notification_webhook'] == {'enabled': True, 'provider': 'feishu',
        'url': 'https://example.invalid/PRIVATE_TOKEN', 'secret': 'PRIVATE_SECRET', 'clear_secret': False}
    assert page.locator('#bindingWebhookUrl').input_value() == ''
    page.evaluate("""() => {
        document.querySelector('#bindingQmtGuideOverlay').classList.add('hidden');
        openBindingDialog({accountKey: 'test:STOCK:TEST_ONLY'});
    }""")
    expect(page.locator('#bindingWebhookProvider')).to_have_value('feishu')
    expect(page.locator('#bindingWebhookUrlHint')).to_contain_text('已配置')
    expect(page.locator('#bindingWebhookSecret')).to_have_value('')
    updates = []

    def partial(route):
        body = route.request.post_data_json
        updates.append(body)
        row = rows[body['account_key']]
        if body['notification_webhook'].get('clear'):
            row['notification_webhook'] = {'enabled': False, 'provider': 'wecom',
                'url_configured': False, 'secret_configured': False}
        route.fulfill(json={'ok': True, 'data': {'account': row}})

    page.route('**/api/account-config/webhook', partial)
    page.locator('#bindingWebhookSaveBtn').click()
    expect(page.locator('#bindingWebhookSaveStatus')).to_contain_text('已保存')
    assert 'url' not in updates[0]['notification_webhook']
    assert 'secret' not in updates[0]['notification_webhook']
    assert len(saved) == 1
    page.locator('#bindingWebhookProvider').select_option('dingtalk')
    page.locator('#bindingWebhookSaveBtn').click()
    expect(page.locator('#bindingSaveStatus')).to_contain_text('重新填写')
    assert len(updates) == 1
    page.locator('#bindingWebhookClearBtn').click()
    page.locator('#bindingWebhookSaveBtn').click()
    expect(page.locator('#bindingWebhookSaveStatus')).to_contain_text('已保存')
    assert updates[-1]['notification_webhook'] == {'clear': True}
    page.locator('#closeBindingDialogBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('#openBindingDialogBtn').click()
    expect(page.locator('#bindingWebhookEnabled')).not_to_be_checked()
    expect(page.locator('#bindingWebhookUrl')).to_have_value('')
    page.locator('#bindingWebhookEnabled').check()
    page.locator('#bindingWebhookSettings').scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / 'binding-webhook.png'))
    assert page.locator('#bindingWebhookSettings').evaluate('node => node.scrollWidth <= node.clientWidth')
    assert page.locator('#bindingDialogOverlay .binding-dialog').evaluate('node => node.scrollWidth <= node.clientWidth')
    assert not errors


def test_notification_docs_are_discoverable_and_examples_match_sdk(page, frontend_url):
    requests, errors = open_bindings(page, frontend_url)
    page.locator('.nav-item[data-view="api"]').click()
    group = page.locator('[data-api-group="system"]')
    if group.get_attribute('aria-expanded') != 'true':
        group.click()
    page.locator('[data-endpoint-id="notification_send"]').click()
    docs = page.locator('#apiDocDetail')
    expect(docs).to_contain_text('资金账号字符串')
    code = docs.locator('pre[data-language="python"]').inner_text()
    for call in (node for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Call)):
        if isinstance(call.func, ast.Attribute) and call.func.attr == 'send':
            inspect.signature(notify.send).bind(*[None for _ in call.args], **{kw.arg: None for kw in call.keywords})
    page.locator('[data-api-sdk-tutorial]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('send')
    expect(page.locator('.python-breadcrumb')).to_contain_text('消息推送')
    assert page.locator('[data-python-cftrader-guide]').count() == 0
    assert all(method == 'GET' for method, path in requests)
    assert not errors
