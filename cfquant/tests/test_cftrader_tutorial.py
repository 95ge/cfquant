"""Batch trading documentation and browser checks; no real orders are executed."""

import ast
import inspect
from pathlib import Path
import re

from cfquant.cftrader import CfQuantTrader
from cfquant.xttrader import XtQuantTrader
from cfquant.tests.test_tutorial_reader import (
    assert_reader_layout, browser, expect, frontend_url, open_app, page, python_directory,
)


ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "cftrader\u6279\u91cf\u4ea4\u6613.md"


def verify_example(source):
    tree = ast.parse(source)
    compile(tree, "cftrader-tutorial", "exec")
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
            continue
        owner = call.func.value.id
        cls = {"orders_api": CfQuantTrader, "trader": XtQuantTrader}.get(owner)
        if cls is not None:
            signature = inspect.signature(getattr(cls, call.func.attr))
            signature.bind(None, *[None for arg in call.args], **{arg.arg: None for arg in call.keywords})
    return tree


def test_documentation_examples_match_current_sdk():
    examples = re.findall(r"```python\n(.*?)```", DOC.read_text(encoding="utf-8"), re.S)
    assert len(examples) == 3
    for example in examples:
        verify_example(example)
    assert "order_stock_batch(" in examples[1]
    assert "order_stock_batch_async(" in examples[2]


def test_batch_tutorial_examples_navigation_and_layout(page, frontend_url, tmp_path):
    requests, errors = open_app(page, frontend_url)
    page.locator('#setupOverlay [data-open-tutorial]').click()
    page.locator('#tutorialReader [data-guide="cftrader"]').click()
    panel = page.locator('#tutorialReader [data-guide-panel="cftrader"]')
    expect(panel).to_be_visible()
    expect(panel.locator('pre[data-language="python"]')).to_have_count(2)
    examples = re.findall(r"```python\n(.*?)```", DOC.read_text(encoding="utf-8"), re.S)[1:]
    for code, documented in zip(panel.locator('pre[data-language="python"]').all_text_contents(), examples):
        assert code.strip() == documented.strip()
        verify_example(code)
    assert_reader_layout(page)
    assert page.locator('#tutorialReader .tutorial-content').evaluate('node => node.scrollWidth <= node.clientWidth')
    page.screenshot(path=str(tmp_path / 'cftrader-overview.png'))
    panel.locator('a[href="#cftrader-sync"]').click()
    expect(panel.locator('#cftrader-sync')).to_be_focused()
    page.screenshot(path=str(tmp_path / 'cftrader-sync.png'))
    page.locator('#tutorialReader [data-guide="python"]').click()
    page.locator('[data-python-back]').click()
    page.locator('#tutorialReader [data-guide="cftrader"]').click()
    panel.locator('a[href="#cftrader-async"]').click()
    expect(panel.locator('#cftrader-async')).to_be_focused()
    page.screenshot(path=str(tmp_path / 'cftrader-async.png'))
    page.keyboard.press('Escape')
    expect(page.locator('#setupOverlay')).to_be_visible()
    assert all(method == 'GET' for method, path in requests)
    assert errors == []


def test_cftrader_reference_search_examples_and_links(page, frontend_url, tmp_path):
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => { window.copiedText = text; }}})")
    requests, errors = open_app(page, frontend_url)
    page.locator('#setupOverlay [data-open-tutorial]').click()
    page.locator('#tutorialReader [data-guide="python"]').click()
    python_directory(page)
    page.locator('#pythonApiSearch').fill('cftrader')
    page.locator('#pythonApiFilter').select_option('extension')
    expect(page.locator('.python-api-nav [data-python-entry^="cftrader."]')).to_have_count(4)
    page.locator('#pythonApiSearch').fill('order_stock_batch')
    expect(page.locator('.python-api-nav [data-python-entry^="cftrader."]')).to_have_count(2)
    page.locator('.python-api-nav [data-python-entry="cftrader.order_stock_batch_async"]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('order_stock_batch_async')
    expect(page.locator('.python-api-document .python-original')).to_have_count(0)
    expect(page.locator('.python-document-meta a')).to_have_count(0)
    expect(page.locator('.python-solution')).to_contain_text('XtQuantTraderCallback')
    expect(page.locator('.python-solution')).to_contain_text('unknown')
    assert_reader_layout(page)
    assert page.locator('.python-reading-pane').evaluate('node => node.scrollWidth <= node.clientWidth')
    page.screenshot(path=str(tmp_path / 'cftrader-api-reference.png'))
    page.locator('.python-solution [data-python-copy]').click()
    copied = page.evaluate('window.copiedText')
    assert 'order_stock_batch_async(' in copied
    assert 'ENABLE_TRADING = False' in copied
    verify_example(copied)
    page.locator('[data-python-link]').click()
    deep_link = page.evaluate('window.copiedText')
    assert deep_link.endswith('#python-api=cftrader.order_stock_batch_async')
    page.locator('[data-python-cftrader-guide]').click()
    expect(page.locator('[data-guide-panel="cftrader"]')).to_be_visible()
    page.locator('[data-guide-panel="cftrader"] a[href="#python-api=cftrader.order_stock_batch"]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('order_stock_batch')
    page.locator('[data-python-cftrader-guide]').click()
    page.locator('[data-guide-panel="cftrader"] a[href="#python-api=cftrader.order_stock_batch"]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('order_stock_batch')
    page.goto(deep_link)
    page.reload()
    page.locator('#setupOverlay [data-open-tutorial]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('order_stock_batch_async')

    entries = page.evaluate('window.CFQUANT_CFTRADER_API')
    assert len(entries) == 4
    for entry in entries:
        verify_example(entry['example'])
        method = getattr(CfQuantTrader, entry['name'])
        actual_parameters = list(inspect.signature(method).parameters)[1:]
        assert [parameter['name'] for parameter in entry['parameters']] == actual_parameters
        documented = ast.parse(entry['signature']).body[0].value
        assert isinstance(documented, ast.Call)
        assert [arg.id for arg in documented.args] + [arg.arg for arg in documented.keywords] == actual_parameters
        for keyword in documented.keywords:
            assert ast.literal_eval(keyword.value) == inspect.signature(method).parameters[keyword.arg].default
        if 'batch' in entry['name']:
            assert 'RPC' in entry['description']
            assert 'QMT' in entry['description']
            assert 'SDK 层按顺序调用' not in entry['description']
    assert all(method == 'GET' for method, path in requests)
    assert errors == []


def test_web_api_catalog_shows_sdk_and_preserves_http_batch(page, frontend_url, tmp_path):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    expect(page.locator('[data-api-group="cftrader"]')).to_be_visible()
    expect(page.locator('#apiEndpointList [data-endpoint-id^="cftrader."]')).to_have_count(4)
    for method in ('order_stock_batch', 'order_stock_batch_async', 'order_stock', 'order_stock_async'):
        page.locator(f'[data-endpoint-id="cftrader.{method}"]').click()
        expect(page.locator('#apiRoute')).to_contain_text('Python SDK cfquant.cftrader.CfQuantTrader.' + method)
        expect(page.locator('#apiForm button[type="submit"]')).to_be_visible()
        expect(page.locator('#apiHttpPreview')).to_be_visible()
        expect(page.locator('.api-settings-tip')).to_be_visible()
        expect(page.locator('#apiForm [name="confirm_text"]')).to_have_value('')
        code = page.locator('#apiDocDetail pre[data-language="python"]').inner_text()
        verify_example(code)
        assert f'orders_api.{method}(' in code
        assert 'ENABLE_TRADING = False' in code
        assert page.locator('.api-workbench').evaluate('node => node.scrollWidth <= node.clientWidth'), page.locator('.api-workbench').evaluate("node => [...node.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > node.getBoundingClientRect().right).slice(0, 12).map(el => [el.tagName, el.className, el.getBoundingClientRect().width])")
    page.locator('[data-endpoint-id="cftrader.order_stock_batch_async"]').click()
    page.locator('#apiTitle').scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / 'cftrader-web-api.png'))
    page.locator('[data-api-sdk-tutorial]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('order_stock_batch_async')
    page.locator('.nav-item[data-view="api"]').click()
    page.locator('[data-endpoint-id="batch_order"]').click()
    expect(page.locator('#apiRoute')).to_have_text('POST /api/orders/batch')
    expect(page.locator('#apiForm button[type="submit"]')).to_be_visible()
    expect(page.locator('#apiHttpPreview')).to_be_visible()
    expect(page.locator('.api-settings-tip')).to_be_visible()
    request = page.evaluate('currentApiRequest()')
    assert request['method'] == 'POST'
    assert len(request['body']['orders']) == 2
    assert request['body']['confirm_text'] == 'BATCH 2'
    assert not any(method == 'POST' and '/orders' in path for method, path in requests)
    assert errors == []
