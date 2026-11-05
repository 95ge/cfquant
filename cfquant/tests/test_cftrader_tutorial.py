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
    assert len(examples) == 5
    for example in examples:
        verify_example(example)
    assert "order_stock_batch(" in examples[1]
    assert "order_stock_batch_async(" in examples[2]
    assert "cancel_order_stock_batch(" in examples[3]
    assert "cancel_order_stock_batch_async(" in examples[4]
    algorithm_doc = (ROOT / "docs/algorithm_trading.md").read_text(encoding="utf-8")
    for example in re.findall(r"```python\n(.*?)```", algorithm_doc, re.S):
        verify_example(example)


def test_batch_tutorial_examples_navigation_and_layout(page, frontend_url, tmp_path):
    requests, errors = open_app(page, frontend_url)
    page.locator('#setupOverlay [data-open-tutorial]').click()
    page.locator('#tutorialReader [data-guide="cftrader"]').click()
    panel = page.locator('#tutorialReader [data-guide-panel="cftrader"]')
    expect(panel).to_be_visible()
    expect(panel.locator('pre[data-language="python"]')).to_have_count(4)
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
    panel.locator('a[href="#cftrader-cancel-sync"]').click()
    expect(panel.locator('#cftrader-cancel-sync')).to_be_focused()
    panel.locator('a[href="#cftrader-cancel-async"]').click()
    expect(panel.locator('#cftrader-cancel-async')).to_be_focused()
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
    page.locator('[data-python-groups-toggle]').click()
    page.locator('#pythonApiSearch').fill('cftrader')
    page.locator('#pythonApiFilter').select_option('extension')
    expect(page.locator('.python-api-nav [data-python-entry^="cftrader."]')).to_have_count(27)
    page.locator('#pythonApiSearch').fill('order_stock_batch')
    expect(page.locator('.python-api-nav [data-python-entry^="cftrader."]')).to_have_count(4)
    page.locator('#pythonApiSearch').fill('cancel_order_stock_batch')
    expect(page.locator('.python-api-nav [data-python-entry^="cftrader."]')).to_have_count(2)
    page.locator('#pythonApiSearch').fill('order_stock_batch')
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
    assert len(entries) == 27
    for entry in entries:
        verify_example(entry['example'])
        method = getattr(CfQuantTrader, entry['name'])
        if isinstance(inspect.getattr_static(CfQuantTrader, entry['name']), staticmethod):
            actual_parameters = list(inspect.signature(method).parameters)
            assert [parameter['name'] for parameter in entry['parameters']] == actual_parameters
            declaration = ast.parse('def ' + entry['signature'].split('.', 1)[1] + ':\n    pass').body[0]
            assert [arg.arg for arg in declaration.args.kwonlyargs] == actual_parameters
            for arg, value in zip(declaration.args.kwonlyargs, declaration.args.kw_defaults):
                if value is not None:
                    assert ast.literal_eval(value) == inspect.signature(method).parameters[arg.arg].default
            continue
        actual_parameters = list(inspect.signature(method).parameters)[1:]
        assert [parameter['name'] for parameter in entry['parameters']] == actual_parameters
        documented = ast.parse(entry['signature']).body[0].value
        assert isinstance(documented, ast.Call)
        assert [arg.id for arg in documented.args] + [arg.arg or arg.value.id for arg in documented.keywords] == actual_parameters
        for keyword in documented.keywords:
            if keyword.arg is not None:
                assert ast.literal_eval(keyword.value) == inspect.signature(method).parameters[keyword.arg].default
        if 'batch' in entry['name']:
            assert 'RPC' in entry['description']
            assert 'QMT' in entry['description']
            assert 'SDK 层按顺序调用' not in entry['description']
    page.evaluate("window.CfquantPythonReference.open('cftrader.order_twap')")
    expect(page.locator('.python-document-head h2')).to_have_text('order_twap')
    expect(page.locator('.python-solution')).to_contain_text('request_key')
    expect(page.locator('.python-solution')).to_contain_text('ENABLE_TRADING = False')
    assert_reader_layout(page)
    assert all(method == 'GET' for method, path in requests)
    assert errors == []


def test_web_api_catalog_shows_sdk_and_preserves_http_batch(page, frontend_url, tmp_path):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    expect(page.locator('[data-api-group="cftrader"]')).to_be_visible()
    expect(page.locator('#apiEndpointList [data-endpoint-id^="cftrader."]')).to_have_count(27)
    page.locator('[data-api-group="cftrader"]').click()
    for method in ('order_stock_batch', 'order_stock_batch_async', 'cancel_order_stock_batch',
                   'cancel_order_stock_batch_async', 'order_stock', 'order_stock_async'):
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
    group = page.locator('.api-group').filter(has=page.locator('[data-endpoint-id="batch_order"]'))
    if group.locator('.api-group-head').get_attribute('aria-expanded') != 'true':
        group.locator('.api-group-head').click()
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


def test_algorithm_examples_are_discoverable_from_api_and_documentation_menus(page, frontend_url, tmp_path):
    import json
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => { window.copiedText = text; }}})")
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    group = page.locator('[data-api-group="algorithm"]')
    expect(group).to_be_visible()
    if group.get_attribute('aria-expanded') != 'true':
        group.click()
    methods = {'order_algo':'submit', 'order_twap':'submit', 'order_vwap':'submit', 'order_pov':'submit',
               'query_algo':'query', 'list_algos':'list', 'pause_algo':'pause', 'resume_algo':'resume', 'cancel_algo':'cancel'}
    for method, operation in methods.items():
        page.locator(f'[data-endpoint-id="cftrader.{method}"]').click()
        code = page.locator('#apiDocDetail pre[data-language="python"]').inner_text()
        verify_example(code)
        assert f'orders_api.{method}(' in code
        page.locator('[data-api-copy-example="python"]').click()
        expect(page.locator('[data-api-copy-example="python"]')).to_have_text('已复制')
        assert page.evaluate('window.copiedText') == code
        http = page.locator('#apiDocDetail pre[data-language="http"]').inner_text()
        assert http.startswith('POST /api/trade/algo/' + operation + '\n')
        body = json.loads(http.split('\n\n', 1)[1])
        assert body['account']['account_id'] == 'YOUR_ACCOUNT_ID'
        if operation == 'submit':
            assert body['request_key']
            assert body['algo'] == {'order_pov':'POV','order_vwap':'VWAP'}.get(method,'TWAP')
        elif operation != 'list':
            assert body['algo_id'] == 'YOUR_ALGO_ID'
        page.locator('[data-api-copy-example="http"]').click()
        expect(page.locator('[data-api-copy-example="http"]')).to_have_text('已复制')
        assert page.evaluate('window.copiedText') == http
        expect(page.locator('#apiForm button[type="submit"]')).to_have_count(0)
        assert page.locator('.api-workbench').evaluate('node => node.scrollWidth <= node.clientWidth')
    page.locator('.nav-item[data-view="docs"]').click()
    docs = page.locator('#cfquantDocs')
    expect(docs.locator('.docs-head h2')).to_have_text('接口文档与调用示例')
    docs.locator('#docsGroup').select_option('algorithm')
    expect(docs.locator('[data-doc-id]')).to_have_count(21)
    for method in methods:
        docs.locator(f'[data-doc-id="cftrader.{method}"]').click()
        expect(docs.locator('.docs-article h2')).to_have_text(method)
        example = docs.locator('pre[data-language="python"]').inner_text()
        verify_example(example)
        assert f'orders_api.{method}(' in example
        docs.locator('[data-doc-copy="python"]').click()
        expect(docs.locator('[data-doc-copy="python"]')).to_have_text('已复制')
        assert page.evaluate('window.copiedText') == example
        expect(docs.locator('[data-python-test]')).to_have_count(0)
    docs.locator('[data-doc-copy="http"]').click()
    expect(docs.locator('[data-doc-copy="http"]')).to_have_text('已复制')
    assert page.evaluate('window.copiedText').startswith('POST /api/trade/algo/cancel\n')
    docs.locator('#docsSearch').fill('order_twap')
    expect(docs.locator('[data-doc-id]')).to_have_count(1)
    expect(docs.locator('.docs-article h2')).to_have_text('order_twap')
    assert docs.evaluate('node => node.scrollWidth <= node.clientWidth')
    page.screenshot(path=str(tmp_path / 'algorithm-main-docs.png'))
    docs.locator('#docsGroup').select_option('xtdata')
    docs.locator('#docsSearch').fill('get_full_tick')
    expect(docs.locator('.docs-article h2')).to_have_text('get_full_tick')
    expect(docs.locator('[data-python-test]')).to_be_visible()
    docs.locator('[data-doc-algorithm-intro]').click()
    panel = page.locator('[data-guide-panel="algorithm"]')
    expect(panel).to_be_visible()
    expect(page.locator('.tutorial-menu-item[data-guide="algorithm"]')).to_be_visible()
    expect(panel.locator('pre[data-language="python"]')).to_have_count(4)
    for name in ('twap','vwap','pov','controls'):
        panel.locator(f'a[href="#algo-{name}"]').click()
        code = panel.locator(f'#algo-{name}-code').inner_text()
        verify_example(code)
        panel.locator(f'[data-algo-copy="algo-{name}-code"]').click()
        expect(panel.locator(f'[data-algo-copy="algo-{name}-code"]')).to_have_text('已复制')
        assert page.evaluate('window.copiedText') == code
    assert page.locator('.tutorial-content').evaluate('node => node.scrollWidth <= node.clientWidth')
    panel.locator('a[href="#python-api=cftrader.order_pov"]').first.click()
    expect(page.locator('.python-document-head h2')).to_have_text('order_pov')
    expect(page.locator('.python-api-document [data-python-test]')).to_have_count(0)
    page.locator('[data-python-cftrader-guide]').click()
    expect(panel).to_be_visible()
    page.screenshot(path=str(tmp_path / 'algorithm-documentation.png'))
    page.locator('.tutorial-menu-item[data-guide="cftrader"]').click()
    page.locator('[data-guide-panel="cftrader"] [data-algorithm-guide]').click()
    expect(panel).to_be_visible()
    page.locator('.nav-item[data-view="api"]').click()
    page.locator('[data-api-algorithm-guide]').click()
    expect(panel).to_be_visible()
    assert all(method == 'GET' for method, path in requests)
    assert errors == []
