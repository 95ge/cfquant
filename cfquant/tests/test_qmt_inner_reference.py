"""Native QMT documentation completeness and discoverability; no live QMT calls."""
import ast
import hashlib
import inspect
import json
from pathlib import Path

from cfquant.qmt_inner import QmtInnerApi, QmtSystem, QmtMarket, QmtTrade, QmtCallbacks, QmtReference
from cfquant.qmt_inner_catalog import INNER_METHODS, INNER_CALLBACKS

ROOT = Path(__file__).resolve().parents[2]


def reference_data():
    source = (ROOT / 'web_dashboard/qmt-inner-api-data.js').read_text(encoding='utf-8')
    return json.loads(source.split('window.CFQUANT_QMT_INNER_API = ', 1)[1].rstrip(';\n'))


def test_native_directory_covers_sdk_and_examples_match_signatures():
    data = reference_data()
    assert data['catalogSha256'] == hashlib.sha256((ROOT / 'cfquant/qmt_inner_catalog.py').read_text(encoding='utf-8').encode('utf-8')).hexdigest()
    assert data['sdkSha256'] == hashlib.sha256((ROOT / 'cfquant/qmt_inner.py').read_text(encoding='utf-8').encode('utf-8')).hexdigest()
    expected = {'qmt_inner.' + category + '.' + name for category, name in INNER_METHODS}
    expected.update('qmt_inner.callbacks.' + name for name in INNER_CALLBACKS)
    expected.update('qmt_inner.system.' + name for name in ('QmtInnerApi', 'capabilities', 'close'))
    entries = data['entries']
    assert len(entries) == len(expected)
    assert {entry['id'] for entry in entries} == expected
    assert data['methodCount'] == len(INNER_METHODS)
    assert data['callbackCount'] == len(INNER_CALLBACKS)
    assert set(data['groups']) == {'system', 'market', 'trade', 'callbacks', 'reference'}
    classes = dict(system=QmtSystem, market=QmtMarket, trade=QmtTrade, callbacks=QmtCallbacks,
                   reference=QmtReference)
    for entry in entries:
        assert entry['source'].startswith('https://dict.thinktrader.net/innerApi/')
        assert entry['status'] == 'native'
        assert entry['signature'] and entry['title'] and entry['exampleTitle']
        tree = ast.parse(entry['example'], filename=entry['id'])
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Name) and call.func.id == 'QmtInnerApi':
                signature = inspect.signature(QmtInnerApi)
            elif isinstance(call.func, ast.Attribute):
                owner = call.func.value
                if isinstance(owner, ast.Name) and owner.id == 'qmt':
                    signature = inspect.signature(getattr(QmtInnerApi, call.func.attr))
                elif isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name) and owner.value.id == 'qmt':
                    signature = inspect.signature(getattr(classes[owner.attr], call.func.attr))
                else:
                    continue
                signature = signature.replace(parameters=list(signature.parameters.values())[1:])
            else:
                continue
            signature.bind(*[None for arg in call.args], **{arg.arg: None for arg in call.keywords})


def test_native_methods_are_discoverable_in_both_directories(page, frontend_url):
    from cfquant.tests.test_tutorial_reader import open_app, expect, python_directory
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => { window.copiedText = text; }}})")
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    parent = page.locator('#apiEndpointList > .api-group').filter(has=page.locator('[data-api-group="qmt_inner"]'))
    expect(parent).to_have_count(1)
    expect(parent.locator(':scope > .api-group-head')).to_contain_text('大 QMT 内置接口')
    expect(page.locator('[data-api-group^="qmt_inner_"]')).to_have_count(5)
    expect(page.locator('#apiEndpointList > .api-group > [data-api-group^="qmt_inner_"]')).to_have_count(0)
    expect(page.locator('#apiEndpointList [data-endpoint-id^="qmt_inner."]')).to_have_count(len(reference_data()['entries']))
    page.locator('[data-api-group="qmt_inner"]').click()
    for category, method in [('system', 'QmtInnerApi'), ('market', 'get_full_tick'), ('trade', 'get_trade_detail_data'),
                             ('callbacks', 'order_callback'), ('reference', 'ext_data')]:
        page.locator(f'[data-api-group="qmt_inner_{category}"]').click()
        page.locator(f'[data-endpoint-id="qmt_inner.{category}.{method}"]').click()
        expect(page.locator('#apiTitle')).to_contain_text(method)
        expect(page.locator('#apiRoute')).to_contain_text('Python SDK')
        expect(page.locator('#apiForm button[type="submit"]')).to_have_count(0)
        expect(page.locator('#apiHttpPreview')).not_to_be_visible()
        code = page.locator('#apiDocDetail pre[data-language="python"]').inner_text()
        assert 'from cfquant import QmtInnerApi' in code
        page.locator('[data-api-copy-example="python"]').click()
        assert page.evaluate('window.copiedText') == code
        assert page.locator('.api-workbench').evaluate('node => node.scrollWidth <= node.clientWidth')
    page.locator('[data-api-group="qmt_inner"]').click()
    expect(page.locator('[data-api-group="qmt_inner_market"]')).not_to_be_visible()
    page.locator('[data-api-group="qmt_inner"]').click()
    expect(page.locator('[data-endpoint-id="qmt_inner.reference.ext_data"]')).to_be_visible()
    page.locator('#apiGroupsToggleBtn').click()
    expect(parent.locator('.api-subgroup > .api-group-head')).to_have_count(5)
    # All categories are expanded; the next toggle must collapse parent and children.
    page.locator('#apiGroupsToggleBtn').click()
    expect(page.locator('[data-api-group="qmt_inner"]')).to_have_attribute('aria-expanded', 'false')
    expect(page.locator('[data-api-group="qmt_inner_market"]')).not_to_be_visible()
    page.locator('[data-api-sdk-tutorial]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('ext_data')
    python_directory(page)
    expect(page.locator('#pythonApiNav > [data-python-native-group]')).to_have_count(1)
    expect(page.locator('[data-python-native-group] > .python-nav-group')).to_have_count(5)
    page.locator('#pythonApiFilter').select_option('native')
    page.locator('#pythonApiSearch').fill('get_trade_detail_data')
    expect(page.locator('#pythonApiNav [data-python-entry^="qmt_inner."]')).to_have_count(1)
    page.locator('[data-python-groups-toggle]').click()
    page.locator('[data-python-entry="qmt_inner.trade.get_trade_detail_data"]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('get_trade_detail_data')
    expect(page.locator('.python-document-meta')).to_contain_text('仅 Python 调用')
    expect(page.locator('.python-solution')).to_contain_text('row.m_strInstrumentID')
    python_directory(page)
    for name in ['set_output_index_property', 'paint', 'order_shares', 'call_vba', 'run_time']:
        page.locator('#pythonApiSearch').fill(name)
        expect(page.locator('#pythonApiNav .python-empty')).to_be_visible()
    assert not any(method == 'POST' for method, path in requests)
    assert not errors


# Shared desktop/mobile fixtures serve static files and mock all API requests.
from cfquant.tests.test_tutorial_reader import browser, page, frontend_url
