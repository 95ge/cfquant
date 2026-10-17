"""Browser tester interactions; every API is intercepted and no orders leave the browser."""

from pathlib import Path
import sys

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from test_tutorial_reader import browser, page, frontend_url, open_app, expect, assert_reader_layout


def open_test(page, frontend_url, entry):
    requests, errors = open_app(page, frontend_url)
    page.locator('#setupOverlay [data-open-tutorial]').click()
    page.evaluate('(id) => window.CfquantPythonReference.open(id)', entry)
    page.locator('#tutorialReader [data-python-test]').click()
    panel = page.locator('#tutorialReader .api-inline-test:not([hidden])')
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
    page.route('**/api/python/xtdata', reply)
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
    page.route('**/api/python/xtdata', lambda route: route.fulfill(status=401, json={'ok': False, 'error': 'invalid credentials'}))
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-status]')).to_have_text('请求失败')
    expect(panel.locator('[data-test-output]')).to_contain_text('invalid credentials')
    assert errors == []


def test_inline_api_tester_prefers_api_key_when_web_auth_enabled(page, frontend_url):
    panel, requests, errors = open_test(page, frontend_url, 'xtdata.get_full_tick')
    page.evaluate("""() => {
        state.serverAccess = {web_auth_enabled: true};
        state.webAuthToken = 'web-token-test';
        state.apiKey = 'api-key-test';
    }""")
    assert page.evaluate("() => apiDebugAuthHeaders()") == {'X-API-Key': 'api-key-test'}
    sent_headers = []

    def reply(route):
        sent_headers.append(route.request.headers)
        route.fulfill(json={'ok': True, 'data': {'result': {'000001.SZ': {'lastPrice': 11.7}}}})

    page.route('**/api/python/xtdata', reply)
    panel.locator('[name="code_list"]').fill('000001.SZ')
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-output]')).to_contain_text('lastPrice')
    assert sent_headers[0].get('x-api-key') == 'api-key-test'
    assert 'x-cfquant-web-token' not in sent_headers[0]
    assert all(method == 'GET' for method, path in requests)
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


@pytest.mark.parametrize('method', ['cancel_order_stock_batch', 'cancel_order_stock_batch_async'])
def test_cancel_batch_test_confirmation_json_results_and_layout(page, frontend_url, method):
    panel, requests, errors = open_test(page, frontend_url, 'cftrader.' + method)
    pending = []
    page.route('**/api/cftrader/' + method, lambda route: pending.append(route))
    panel.locator('[name="account_id"]').fill('TEST_ONLY')
    panel.locator('[name="account_type"]').select_option('CREDIT')
    panel.locator('[type="submit"]').click()
    expect(panel.locator('[data-test-status]')).to_have_text('参数有误')
    assert pending == []
    original = panel.locator('[name="cancels_json"]').input_value()
    panel.locator('[name="cancels_json"]').fill('[bad json')
    panel.locator('[name="confirm_text"]').fill('CFTRADER TEST_ONLY 2')
    panel.locator('[type="submit"]').click()
    assert pending == []
    panel.locator('[name="cancels_json"]').fill(original)
    panel.locator('[name="stop_on_error"]').check()
    panel.locator('[type="submit"]').click()
    assert len(pending) == 1
    body = pending[0].request.post_data_json
    assert len(body['cancels']) == 2 and 'cancels_json' not in body and 'orders' not in body
    assert body['stop_on_error'] is True and body['account_type'] == 'CREDIT'
    asynchronous = method.endswith('_async')
    rows = [dict(index=i, order_id=cancel['order_id'], stock_code=cancel.get('stock_code', ''),
                 market=cancel.get('market', ''), status='submitted', ok=True,
                 cancel_result=0, seq=3001+i if asynchronous else None)
            for i, cancel in enumerate(body['cancels'])]
    pending[0].fulfill(json={'ok': True, 'data': {'latency_ms': 150, 'result': {
        'operation': 'cancel', 'execution': 'qmt', 'ok': True, 'total': 2, 'submitted': 2,
        'failed': 0, 'unknown': 0, 'skipped': 0, 'qmt_submit_ms': 4.2, 'results': rows}}})
    expect(panel.locator('[data-test-status]')).to_have_text('请求完成')
    expect(panel.locator('.api-test-orders tbody tr')).to_have_count(2)
    expect(panel.locator('[data-test-output]')).to_contain_text('cancel_result')
    assert_reader_layout(page)
    assert panel.evaluate('node => node.scrollWidth <= node.clientWidth')
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
    page.locator('#tutorialReader [data-python-test]').click()
    expect(page.locator('#tutorialReader [data-test-output]')).to_contain_text('避免重复提交')
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
    expect(page.locator('#tutorialReader [data-python-test]')).to_have_count(0)
    assert errors == []


def test_main_api_batch_testing_summary_and_clear(page, frontend_url):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    group = page.locator('.api-group').filter(has=page.locator('[data-endpoint-id="cftrader.order_stock_batch"]'))
    if group.locator('.api-group-head').get_attribute('aria-expanded') != 'true':
        group.locator('.api-group-head').click()
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


def test_main_market_timing_success_timeout_and_old_bridge(page, frontend_url):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    page.locator('[data-api-group="data"]').click()
    page.locator('[data-endpoint-id="full_tick"]').click()
    replies = [{
        'ok': True, 'data': {'latency_ms': 500, 'result': {'000001.SZ': {'lastPrice': 11.3}},
        'timing': {'qmt': {'available': True, 'queue_ms': 400, 'native_ms': 70,
                          'convert_ms': 5, 'encode_ms': 4, 'json_encode_ms': 1, 'fallback_used': True},
                   'rpc': {'wait_ms': 495, 'decode_ms': 2, 'json_decode_ms': 1.5}, 'web': {'result_convert_ms': 3}}}},
        {'ok': False, 'error': 'cfquant pipe request timeout', 'status': 400,
         'timing': {'qmt': {'available': False, 'reason': 'no_response'}, 'rpc': {'wait_ms': 12000}}},
        {'ok': True, 'data': {'latency_ms': 80, 'result': {},
         'timing': {'qmt': {'available': False, 'reason': 'bridge_timing_unavailable'}}}},
    ]
    page.route('**/api/data/full-tick', lambda route: route.fulfill(json=replies.pop(0), headers={'Server-Timing': 'web_json;dur=2.5'}))
    form = page.locator('#apiForm')
    form.locator('[type="submit"]').click()
    timing = page.locator('#apiResponseLatencyMeta')
    expect(timing).to_contain_text('QMT 原生取数 70.0 ms')
    expect(timing).to_contain_text('兼容格式转换 5.00 ms')
    expect(timing).to_contain_text('Web 结果转换 3.00 ms')
    expect(timing).to_contain_text('Web JSON 编码 2.50 ms')
    expect(timing).to_contain_text('其中 JSON 编码 1.00 ms')
    expect(timing).to_contain_text('客户端 JSON 解析（计入 RPC 等待） 1.50 ms')
    expect(timing).to_contain_text('旧行情接口已回退到扩展接口')
    assert page.locator('.api-workbench').evaluate('node => node.scrollWidth <= node.clientWidth')
    page.locator('#apiResponseLatency').scroll_into_view_if_needed()
    screenshot(page, 'market-timing')
    form.locator('[type="submit"]').click()
    expect(timing).to_contain_text('QMT 耗时未取得（未收到回包）')
    expect(timing).not_to_contain_text('QMT 原生取数')
    form.locator('[type="submit"]').click()
    expect(timing).to_contain_text('QMT 耗时未取得（桥接脚本未提供）')
    assert errors == []


def test_market_ex_switch_keeps_query_and_displays_response_timing(page, frontend_url):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator('#closeOnboardingBtn').click()
    page.mouse.move(page.viewport_size['width'] - 1, page.viewport_size['height'] - 1)
    page.keyboard.press('Escape')
    page.locator('.nav-item[data-view="api"]').click()
    page.locator('[data-api-group="data"]').click()
    entry = page.locator('[data-endpoint-id="market_data_ex"]')
    expect(entry).to_contain_text('get_market_data_ex')
    page.locator('[data-endpoint-id="market_data"]').click()
    form = page.locator('#apiForm')
    fields = {'field_list': 'open,close,volume', 'stock_list': '000001.SZ,600000.SH',
              'start_time': '20260101', 'end_time': '20261014', 'count': '20', 'timeout': '15'}
    for name, value in fields.items():
        form.locator('[name="%s"]' % name).fill(value)
    form.locator('[name="period"]').fill('1d')
    form.locator('[name="fill_data"]').fill('0')
    page.locator('#apiResponseBox').evaluate("node => node.textContent = 'old response'")
    before = page.evaluate('currentApiRequest().body')
    form.locator('[data-market-variant="market_data_ex"]').click()
    expect(page.locator('#apiTitle')).to_contain_text('get_market_data_ex')
    expect(page.locator('#apiRoute')).to_have_text('POST /api/data/market-ex')
    expect(page.locator('#apiResponseBox')).to_have_text('')
    assert page.evaluate('currentApiRequest().body') == before
    pending = []
    page.route('**/api/data/market-ex', lambda route: pending.append(route))
    form.locator('[type="submit"]').click()
    expect(form.locator('[type="submit"]')).to_be_disabled()
    expect(form.locator('[data-market-variant]')).to_be_disabled()
    page.wait_for_function("state.apiDebugBusy")
    assert len(pending) == 1
    assert pending[0].request.post_data_json == before
    assert before['stock_list'] == ['000001.SZ', '600000.SH']
    assert before['field_list'] == ['open', 'close', 'volume']
    assert before['count'] == 20 and before['fill_data'] is False
    pending[0].fulfill(json={'ok': True, 'data': {'latency_ms': 85, 'result': {
        '000001.SZ': {'20261014': {'open': 11.0, 'close': 11.5, 'volume': 120000}}},
        'timing': {'qmt': {'available': True, 'queue_ms': 20, 'native_ms': 5,
                          'convert_ms': 0, 'encode_ms': 3, 'fallback_used': False},
                   'rpc': {'wait_ms': 80, 'decode_ms': 2}, 'web': {'result_convert_ms': 1}}}})
    expect(page.locator('#apiResponseBox')).to_contain_text('120000')
    expect(page.locator('#apiResponseLatencyMeta')).to_contain_text('QMT 原生取数 5.00 ms')
    expect(page.locator('#apiResponseLatencyMeta')).to_contain_text('QMT 结果编码 3.00 ms')
    expect(page.locator('#apiResponseLatencyMeta')).not_to_contain_text('旧行情接口已回退')
    expect(form.locator('[data-market-variant]')).to_be_enabled()
    assert page.locator('.api-workbench').evaluate('node => node.scrollWidth <= node.clientWidth')
    assert page.locator('#apiEndpointList').evaluate('node => node.scrollWidth <= node.clientWidth')
    screenshot(page, 'market-ex')
    form.locator('[data-market-variant="market_data"]').click()
    expect(page.locator('#apiRoute')).to_have_text('POST /api/data/market')
    assert page.evaluate('currentApiRequest().body') == before
    assert all(method == 'GET' for method, path in requests)
    assert errors == []
