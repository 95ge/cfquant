import ast
import inspect
import json
import re
from pathlib import Path

from cfquant.cftrader import CfQuantTrader, calculate_position
from cfquant.tests.test_cftrader_tutorial import verify_example
from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url, open_app, page


def test_smart_documentation_python_examples():
    text = (Path(__file__).resolve().parents[2] / "docs/conditional_orders.md").read_text(encoding="utf-8")
    examples = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(examples) == 3
    for example in examples:
        verify_example(example)
    scope = {}
    exec(examples[0], scope)
    assert scope["result"]["quantity"] == 1900


def test_smart_reference_examples_navigation_and_copy(page, frontend_url, tmp_path):
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => { window.copiedText = text; }}})")
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    docs = page.locator('#apiDocDetail')
    group = page.locator('[data-api-group="algorithm"]')
    if group.get_attribute('aria-expanded') != 'true':
        group.click()
    entries = page.evaluate("window.CFQUANT_CFTRADER_API.filter(x => x.group === '条件单与仓位计划')")
    assert len(entries) == 12
    for entry in entries:
        assert hasattr(CfQuantTrader, entry['name'])
        page.locator(f'[data-endpoint-id="{entry["id"]}"]').click()
        code = docs.locator('pre[data-language="python"]').inner_text()
        tree = verify_example(code)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Name) and call.func.id == 'calculate_position':
                inspect.signature(calculate_position).bind(**{kw.arg: None for kw in call.keywords})
        docs.locator('[data-api-copy-example="python"]').click()
        assert page.evaluate('window.copiedText') == code
        http = docs.locator('pre[data-language="http"]').inner_text()
        assert json.loads(http.split('\n\n', 1)[1]) == entry['http']['body']
        docs.locator('[data-api-copy-example="http"]').click()
        assert page.evaluate('window.copiedText') == http
        assert docs.evaluate('node => node.scrollWidth <= node.clientWidth')
    page.locator('[data-endpoint-id="cftrader.order_condition"]').click()
    page.screenshot(path=str(tmp_path / 'smart-orders-api.png'))
    page.locator('.nav-item[data-view="api"]').click()
    group = page.locator('[data-api-group="algorithm"]')
    if group.get_attribute('aria-expanded') != 'true':
        group.click()
    page.locator('[data-endpoint-id="cftrader.order_condition"]').click()
    expect(page.locator('#apiDocDetail pre[data-language="http"]')).to_contain_text('/api/trade/condition/submit')
    page.locator('[data-api-sdk-tutorial]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('order_condition')
    page.locator('[data-python-cftrader-guide]').click()
    panel = page.locator('[data-guide-panel="algorithm"]')
    panel.locator('a[href="#algo-protection"]').click()
    expect(panel.locator('#algo-protection')).to_be_focused()
    assert all(method == 'GET' for method, path in requests)
    assert errors == []
