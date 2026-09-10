"""Browser tester interactions; every API is intercepted and no orders leave the browser."""

from pathlib import Path

import pytest

from cfquant.tests.test_tutorial_reader import browser, page, frontend_url, open_app, expect, assert_reader_layout


def open_test(page, frontend_url, entry):
    requests, errors = open_app(page, frontend_url)
    page.locator('#setupOverlay [data-open-tutorial]').click()
    page.evaluate('(id) => window.CfquantPythonReference.open(id)', entry)
    page.locator('[data-python-test]').click()
    panel = page.locator('.api-inline-test:not([hidden])')
    expect(panel).to_be_visible()
    assert all(method == 'GET' for method, path in requests)
    return panel, requests, errors


def screenshot(page, name):
    folder = Path(__file__).resolve().parents[2] / 'runtime/screenshots'
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / ('api-tester-%s-%s.png' % (name, page.viewport_size['width']))))


def test_tutorial_query_results_copy_reset_and_error(page, frontend_url):
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => {window.copiedTestResult = text;}}})")
    panel, requests, errors = open_test(page, frontend_url, 'xtdata.get_full_tick')
    sent = []
    def reply(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'data': {'result': {'000001.SZ': {'lastPrice': 11.7}}, 'latency_ms': 12.5}})
    page.route('**/api/data/full-tick', reply)
    panel.locator('[name="code_list"]').fill('000001.SZ')
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-status]')).to_have_text('请求完成')
    expect(panel.locator('[data-test-output]')).to_contain_text('lastPrice')
    assert sent[0]['code_list'] == ['000001.SZ']
    panel.locator('[data-test-copy]').click()
    assert 'lastPrice' in page.evaluate('window.copiedTestResult')
    assert_reader_layout(page)
    assert panel.evaluate('node => node.scrollWidth <= node.clientWidth')
    screenshot(page, 'query')
    panel.locator('[data-test-clear]').click()
    expect(panel.locator('[data-test-output]')).to_have_text('')
    panel.locator('[data-test-reset]').click()
    expect(panel.locator('[name="code_list"]')).to_have_value('000001.SZ,600000.SH')
    page.route('**/api/data/full-tick', lambda route: route.fulfill(status=401, json={'ok': False, 'error': 'invalid credentials'}))
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-status]')).to_have_text('请求失败')
    expect(panel.locator('[data-test-output]')).to_contain_text('invalid credentials')
    assert errors == []


@pytest.mark.parametrize('method', ['order_stock_batch', 'order_stock_batch_async'])
def test_batch_test_confirmation_json_busy_results_and_layout(page, frontend_url, method):
    panel, requests, errors = open_test(page, frontend_url, 'cftrader.' + method)
    pending = []
    page.route('**/api/cftrader/' + method, lambda route: pending.append(route))
    panel.locator('[name="account_id"]').fill('TEST_ONLY')
    panel.locator('[name="account_type"]').select_option('CREDIT')
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-status]')).to_have_text('参数有误')
    assert pending == []
    original = panel.locator('[name="orders_json"]').input_value()
    panel.locator('[name="orders_json"]').fill('[bad json')
    panel.locator('[name="confirm_text"]').fill('CFTRADER TEST_ONLY 2')
    panel.locator('[type="submit"]').click()
    assert pending == []
    panel.locator('[name="orders_json"]').fill(original)
    panel.locator('[name="stop_on_error"]').check()
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-status]')).to_have_text('请求中…')
    expect(panel.locator('[type="submit"]')).to_be_disabled()
    panel.locator('form').evaluate('form => form.requestSubmit()')
    assert len(pending) == 1
    body = pending[0].request.post_data_json
    assert len(body['orders']) == 2 and 'orders_json' not in body
    assert body['stop_on_error'] is True and body['account_type'] == 'CREDIT'
    asynchronous = method.endswith('_async')
    rows = [dict(index=i, stock_code=order['stock_code'], status='submitted', ok=True,
                 order_id=None if asynchronous else 1001+i, seq=2001+i if asynchronous else None,
                 order_remark='browser-test-%s' % i) for i, order in enumerate(body['orders'])]
    pending[0].fulfill(json={'ok': True, 'data': {'latency_ms': 150, 'result': {
        'execution': 'qmt', 'ok': True, 'total': 2, 'submitted': 2, 'failed': 0, 'unknown': 0, 'skipped': 0,
        'qmt_submit_ms': 7.1, 'results': rows}}})
    expect(panel.locator('[data-test-status]')).to_have_text('请求完成')
    expect(panel.locator('.api-test-orders tbody tr')).to_have_count(2)
    expect(panel.locator('[data-test-metrics]')).to_contain_text('QMT 内部提交')
    expect(panel.locator('[data-test-output]')).to_contain_text('2001' if asynchronous else '1001')
    panel.locator('[data-test-metrics]').evaluate("node => node.scrollIntoView({block: 'center'})")
    assert_reader_layout(page)
    assert panel.evaluate('node => node.scrollWidth <= node.clientWidth')
    assert panel.locator('.api-test-orders table').evaluate('node => node.getBoundingClientRect().width >= 640')
    screenshot(page, method)
    assert errors == []


def test_stop_waiting_does_not_resubmit_and_result_survives_navigation(page, frontend_url):
    panel, requests, errors = open_test(page, frontend_url, 'cftrader.order_stock_batch')
    pending = []
    page.route('**/api/cftrader/order_stock_batch', lambda route: pending.append(route))
    panel.locator('[name="account_id"]').fill('TEST_ONLY')
    panel.locator('[name="confirm_text"]').fill('CFTRADER TEST_ONLY 2')
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-stop]')).to_be_enabled()
    panel.locator('[data-test-stop]').click()
    expect(panel.locator('[data-test-status]')).to_have_text('结果待确认')
    expect(panel.locator('[data-test-output]')).to_contain_text('避免重复提交')
    assert len(pending) == 1
    pending[0].abort()
    page.evaluate("window.CfquantPythonReference.open('xtdata.get_full_tick')")
    page.evaluate("window.CfquantPythonReference.open('cftrader.order_stock_batch')")
    page.locator('[data-python-test]').click()
    expect(page.locator('[data-test-output]')).to_contain_text('避免重复提交')
    assert len(pending) == 1
    assert errors == []


def test_callback_view_filters_original_events_and_types_are_not_executable(page, frontend_url):
    panel, requests, errors = open_test(page, frontend_url, 'callback.on_stock_order')
    pending = []
    def reply(route):
        pending.append(route.request.url)
        route.fulfill(json={'ok': True, 'data': {'events': [{'event': 'trader:on_stock_order', 'data': {'order_id': 1001}}]}})
    page.route('**/api/callbacks?*', reply)
    panel.locator('[name="account_id"]').fill('TEST_ONLY')
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-output]')).to_contain_text('1001')
    assert 'event_name=trader%3Aon_stock_order' in pending[0]
    page.evaluate("window.CfquantPythonReference.open('type.XtAsset')")
    expect(page.locator('[data-python-test]')).to_have_count(0)
    assert errors == []


def test_main_api_batch_testing_summary_and_clear(page, frontend_url):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    page.locator('[data-endpoint-id="cftrader.order_stock_batch"]').click()
    sent = []

    def reply(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'data': {'latency_ms': 25, 'result': {
            'ok': True, 'total': 2, 'submitted': 2, 'failed': 0, 'unknown': 0, 'skipped': 0,
            'qmt_submit_ms': 3.2, 'results': [dict(index=i, stock_code=order['stock_code'],
                status='submitted', order_id=3001+i) for i, order in enumerate(sent[0]['orders'])]}}})

    page.route('**/api/cftrader/order_stock_batch', reply)
    form = page.locator('#apiForm')
    form.locator('[name="account_id"]').fill('TEST_ONLY')
    form.locator('[type="submit"]').click()
    assert sent == []
    form.locator('[name="confirm_text"]').fill('CFTRADER TEST_ONLY 2')
    form.locator('[type="submit"]').click()
    expect(page.locator('#apiResponseBox')).to_contain_text('3001')
    expect(page.locator('#apiResultSummary tbody tr')).to_have_count(2)
    assert len(sent) == 1 and len(sent[0]['orders']) == 2
    assert page.locator('.api-workbench').evaluate('node => node.scrollWidth <= node.clientWidth')
    page.locator('#apiResultSummary').scroll_into_view_if_needed()
    screenshot(page, 'main-batch')
    page.locator('#apiClearResultBtn').click()
    expect(page.locator('#apiResponseBox')).to_have_text('')
    expect(page.locator('#apiResultSummary')).to_have_text('')
    assert errors == []
