"""Verify quote request forms with mocked APIs on desktop and mobile."""
from cfquant.tests.test_tutorial_reader import browser, frontend_url, open_app, page
from playwright.sync_api import expect
import json
import re
import csv
import pytest
from pathlib import Path
from cfquant.diagnostics import latency_report


def test_whole_quote_form_preserves_arbitrary_markets_and_symbol_case(page, frontend_url, tmp_path):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        setView('api');
        renderApiDocs('quote_subscribe_whole');
    }""")
    result = page.evaluate("""() => {
        const input = document.querySelector('#apiForm [name="markets"]');
        input.value = 'SH,SZ,BJ,rb2610.SF\uFF0CCUSTOM';
        const mixed = currentApiRequest();
        input.value = '';
        const empty = currentApiRequest();
        input.value = 'SH,SZ,BJ,rb2610.SF,CUSTOM';
        return { mixed, empty };
    }""")
    assert result["mixed"]["body"]["markets"] == ["SH", "SZ", "BJ", "rb2610.SF", "CUSTOM"]
    assert result["empty"]["body"]["markets"] == []
    field = page.locator('#apiForm [name="markets"]')
    assert field.is_visible()
    assert page.locator('#apiDocDetail').evaluate("""node =>
        node.scrollWidth <= node.clientWidth + 1 &&
        Array.from(node.querySelectorAll('td')).every(cell => cell.scrollWidth <= cell.clientWidth + 1)
    """)
    field.scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / "whole-quote-form.png"))
    assert errors == []


def test_internal_latency_subscription_stream_and_stop(page, frontend_url, tmp_path):
    sent, stopped, sockets = [], [], []
    page.route_web_socket(re.compile(r'/ws/diagnostics/quotes\?'), lambda ws: sockets.append(ws))
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        setView('api');
        renderApiDocs('quote_latency', {ensureGroupOpen: true});
    }""")
    page.route('**/api/diagnostics/quotes/subscribe', lambda route: (
        sent.append(route.request.post_data_json),
        route.fulfill(json={'ok': True, 'data': {'subscribe_id': '123', 'kind': 'whole_quote_latency'}})))
    page.route('**/api/diagnostics/quotes/unsubscribe', lambda route: (
        stopped.append(route.request.post_data_json), route.fulfill(json={'ok': True, 'data': {'result': True}})))
    page.locator('#apiForm [type="submit"]').click()
    expect(page.locator('#apiResponseBox')).to_contain_text('123')
    assert sent[0]['markets'] == ['SH', 'SZ', 'BJ']
    assert sent[0]['channel'] == 'normal'
    assert sockets == []
    assert page.evaluate('state.quoteLatencyMode') is True
    page.locator('#quoteConnectBtn').click()
    expect(page.locator('#quoteLiveStatus')).to_contain_text('已连接')
    assert len(sockets) == 1
    assert sent[1] == dict(sent[0], resume_subscribe_id='123')
    quote = {'%06d.SZ' % i: {'time': 1792112400000, 'lastPrice': 10.25, 'volume': i,
                            'bidPrice': [10.2, 10.1], 'name': '测试行情'} for i in range(1, 258)}
    quote['000257.SZ']['time'] -= 1000
    report = latency_report({'schema': 'cfquant.quote_latency.v1', 'quotes': quote,
                             'qmt_callback_at_ms': 1792112400027.875, 'qmt_push_at_ms': 1792112400028.375,
                             'qmt_encode_ms': 1.25, 'qmt_encoding': 'direct_json'}, 1792112400032.5)
    sockets[0].send(json.dumps({'type': 'quote', 'event': {'subscribe_id': '999', 'data': quote, 'latency': report}}))
    sockets[0].send(json.dumps({'type': 'quote', 'event': {'subscribe_id': '123', 'data': quote, 'latency': report, 'seq': 1}}))
    expect(page.locator('#quoteLiveBody')).to_contain_text('32.500 ms')
    expect(page.locator('#quoteLiveBody')).to_contain_text('27.875 ms')
    expect(page.locator('#quoteLiveBody td').nth(5)).to_have_attribute(
        'title', '原始行情时间：1792112400000；QMT 回调入口：1792112400027.875（Unix 毫秒）')
    expect(page.locator('#quoteLiveBody')).to_contain_text('4.125 ms')
    expect(page.locator('#quoteLiveBody')).to_contain_text('0.500 ms')
    expect(page.locator('#quoteLatencySummary')).to_contain_text('最近 1 批')
    expect(page.locator('#quoteLatencySummary')).to_contain_text('P95 4.125 ms')
    expect(page.locator('#quoteLatencySummary')).to_contain_text('最大 1027.875 ms（257 只有效）')
    expect(page.locator('#quoteLatencySummary')).to_contain_text('本批全部 257 只')
    expect(page.locator('#quoteLatencySummary')).to_contain_text('QMT 编码 1.250 ms')
    expect(page.locator('#quoteLiveBody tr')).to_have_count(100)
    page.locator('#quoteLatencyNext').click()
    expect(page.locator('#quoteLiveBody tr').first).to_contain_text('000101.SZ')
    page.locator('#quoteLatencyNext').click()
    expect(page.locator('#quoteLiveBody tr')).to_have_count(57)
    expect(page.locator('#quoteLiveBody')).to_contain_text('000257.SZ')
    expect(page.locator('#quoteLatencyNext')).to_be_disabled()
    with page.expect_download() as downloaded:
        page.locator('#quoteLatencyExportJson').click()
    exported = json.loads(Path(downloaded.value.path()).read_text(encoding='utf-8'))
    assert exported['data'] == quote
    assert len(exported['latency']['samples']) == 257
    with page.expect_download() as downloaded:
        page.locator('#quoteLatencyExportCsv').click()
    with Path(downloaded.value.path()).open(encoding='utf-8-sig', newline='') as stream:
        records = list(csv.DictReader(stream))
    assert len(records) == 257
    assert json.loads(records[-1]['quote_json']) == quote['000257.SZ']
    page.locator('#quoteLatencySort').select_option('qmtQuoteLatency')
    expect(page.locator('#quoteLiveBody tr').first).to_contain_text('000257.SZ')
    page.locator('#quoteLatencyFilter').fill('000257')
    expect(page.locator('#quoteLiveBody tr')).to_have_count(1)
    expect(page.locator('#quoteLatencyPageInfo')).to_contain_text('匹配 1 / 本批 257 只')
    expect(page.locator('#quoteLatencySummary')).to_contain_text('257 只有效')
    with page.expect_download() as downloaded:
        page.locator('#quoteLatencyExportCsv').click()
    with Path(downloaded.value.path()).open(encoding='utf-8-sig', newline='') as stream:
        records = list(csv.DictReader(stream))
    assert [row['code'] for row in records] == ['000257.SZ']
    page.locator('#quoteLatencyFilter').fill('')
    page.locator('#quoteLatencySort').select_option('code')
    page.locator('#quoteLatencyPageSize').select_option('500')
    expect(page.locator('#quoteLiveBody tr')).to_have_count(257)
    page.locator('#quoteLivePanel').screenshot(path=str(tmp_path / 'internal-latency.png'))
    overflow = page.locator('#quoteLivePanel').evaluate('''node => ({
        width: node.clientWidth, scroll: node.scrollWidth,
        children: Array.from(node.children).map(child => ({cls: child.className,
            width: child.clientWidth, scroll: child.scrollWidth}))})''')
    assert overflow['scroll'] <= overflow['width'] + 1, overflow
    page.locator('#quoteLatencyPause').click()
    report['samples'][0]['qmt_quote_latency_ms'] = None
    report['qmt_callback_at_ms'] = None
    sockets[0].send(json.dumps({'type': 'quote', 'event': {'subscribe_id': '123', 'data': quote, 'latency': report, 'seq': 2}}))
    page.wait_for_function('state.quoteLatencyPending?.seq === 2')
    expect(page.locator('#quoteLiveBody td').nth(5)).to_have_text('27.875 ms')
    page.locator('#quoteLatencyPause').click()
    expect(page.locator('#quoteLiveBody td').nth(5)).to_have_text('--')
    page.locator('#quoteLatencyPageSize').select_option('100')
    page.locator('#quoteLatencyNext').click()
    # A new callback contains only its own symbols; old rows do not leak into it.
    smaller = dict(report, code_count=1, samples=report['samples'][:1])
    sockets[0].send(json.dumps({'type': 'quote', 'event': {'subscribe_id': '123',
        'data': {'000001.SZ': quote['000001.SZ']}, 'latency': smaller, 'seq': 3}}))
    expect(page.locator('#quoteLiveBody tr')).to_have_count(1)
    expect(page.locator('#quoteLatencyPageInfo')).to_contain_text('第 1 / 1 页')
    page.locator('#quoteStopBtn').click()
    expect(page.locator('#quoteLiveStatus')).to_contain_text('未订阅')
    page.wait_for_function('!state.quoteSubscribeId && !state.apiSocket')
    assert stopped == [{'bridge_id': 'default', 'channel': 'normal', 'subscribe_id': '123', 'shared_only': True}]
    page.evaluate("renderApiDocs('quote_subscribe_whole')")
    expect(page.locator('#quoteLatencySummary')).not_to_be_visible()
    assert errors == []


@pytest.mark.parametrize('diagnostic', [False, True], ids=['whole', 'latency'])
def test_connect_restores_expired_subscription_and_shows_actual_source(page, frontend_url, diagnostic):
    sent, stopped, sockets = [], [], []
    subscribe_path = '/api/diagnostics/quotes/subscribe' if diagnostic else '/api/quotes/whole/subscribe'
    unsubscribe_path = '/api/diagnostics/quotes/unsubscribe' if diagnostic else '/api/quotes/unsubscribe'
    ws_path = '/ws/diagnostics/quotes' if diagnostic else '/ws/quotes'
    page.route_web_socket(re.compile(re.escape(ws_path) + r'\?'), lambda ws: sockets.append(ws))
    _, errors = open_app(page, frontend_url)
    def subscribe(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'data': {
            'subscribe_id': str(40 + len(sent)), 'bridge_id': 'running-provider',
            'source_reused': True, 'requested_bridge_id': 'default'}})
    page.route('**' + subscribe_path, subscribe)
    page.route('**' + unsubscribe_path, lambda route: (
        stopped.append(route.request.post_data_json), route.fulfill(json={'ok': True, 'data': {'result': True}})))
    page.evaluate("""diagnostic => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        setView('api');
        renderApiDocs(diagnostic ? 'quote_latency' : 'quote_subscribe_whole');
    }""", diagnostic)
    page.locator('#apiForm [type="submit"]').click()
    expect(page.locator('#quoteLiveStatus')).to_contain_text('复用共享行情源：running-provider')
    assert sockets == []
    # Draft form edits must not change the already submitted subscription.
    page.locator('#apiForm [name="markets"]').fill('CUSTOM')
    page.locator('#quoteConnectBtn').click()
    expect(page.locator('#quoteLiveStatus')).to_contain_text('已连接 #42')
    expect(page.locator('#quoteLiveStatus')).to_contain_text('复用共享行情源：running-provider')
    assert sent[1] == dict(sent[0], resume_subscribe_id='41')
    assert len(sockets) == 1
    assert 'subscribe_id=42' in sockets[0].url
    sockets[0].send(json.dumps({'type': 'quote', 'event': {'subscribe_id': '42', 'seq': 1,
        'data': {'600000.SH': {'lastPrice': 10.25, 'time': 1792112400000}}}}))
    expect(page.locator('#quoteLiveBody')).to_contain_text('600000.SH')
    page.locator('#quoteStopBtn').click()
    page.wait_for_function('!state.quoteSubscribeId && !state.apiSocket')
    assert stopped[-1]['subscribe_id'] == '42'
    assert stopped[-1]['shared_only'] is True
    assert errors == []


def test_connect_failure_is_visible_and_retryable(page, frontend_url):
    sent, sockets = [], []
    page.route_web_socket(re.compile(r'/ws/quotes\?'), lambda ws: sockets.append(ws))
    _, errors = open_app(page, frontend_url)
    def subscribe(route):
        sent.append(route.request.post_data_json)
        if len(sent) == 2:
            route.fulfill(status=400, json={'ok': False, 'error': 'QMT provider unavailable'})
        else:
            route.fulfill(json={'ok': True, 'data': {'subscribe_id': '123'}})
    page.route('**/api/quotes/whole/subscribe', subscribe)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        setView('api'); renderApiDocs('quote_subscribe_whole');
    }""")
    page.locator('#apiForm [type="submit"]').click()
    expect(page.locator('#quoteConnectBtn')).to_be_enabled()
    page.locator('#quoteConnectBtn').click()
    expect(page.locator('#apiResponseBox')).to_contain_text('QMT provider unavailable')
    expect(page.locator('#quoteLiveStatus')).to_contain_text('连接失败')
    expect(page.locator('#quoteConnectBtn')).to_be_enabled()
    assert sockets == []
    page.locator('#quoteConnectBtn').click()
    expect(page.locator('#quoteLiveStatus')).to_contain_text('已连接')
    assert len(sockets) == 1
    assert errors == []


def test_stop_during_recovery_releases_late_subscription_without_connecting(page, frontend_url):
    pending, stopped, sockets = [], [], []
    page.route_web_socket(re.compile(r'/ws/quotes\?'), lambda ws: sockets.append(ws))
    _, errors = open_app(page, frontend_url)
    def subscribe(route):
        if route.request.post_data_json.get('resume_subscribe_id'):
            pending.append(route)
        else:
            route.fulfill(json={'ok': True, 'data': {'subscribe_id': '1'}})
    page.route('**/api/quotes/whole/subscribe', subscribe)
    page.route('**/api/quotes/unsubscribe', lambda route: (
        stopped.append(route.request.post_data_json['subscribe_id']),
        route.fulfill(json={'ok': True, 'data': {'result': True}})))
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        setView('api'); renderApiDocs('quote_subscribe_whole');
    }""")
    page.locator('#apiForm [type="submit"]').click()
    expect(page.locator('#quoteConnectBtn')).to_be_enabled()
    with page.expect_request('**/api/quotes/whole/subscribe'):
        page.locator('#quoteConnectBtn').click()
    page.locator('#quoteStopBtn').click()
    expect(page.locator('#quoteLiveStatus')).to_contain_text('未订阅')
    assert len(pending) == 1
    with page.expect_request('**/api/quotes/unsubscribe'):
        pending[0].fulfill(json={'ok': True, 'data': {'subscribe_id': '2'}})
    page.wait_for_function('!state.quoteSubscribeId && !state.apiSocket')
    assert stopped == ['1', '2']
    assert sockets == []
    assert errors == []
