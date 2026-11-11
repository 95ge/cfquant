"""Monitor interactions against actual SQLite query responses; no trading service."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cfquant.tests.test_tutorial_reader import browser, page, expect, frontend_url, open_app
from cfquant.tests.test_trading_monitor import callback, NOW, bound_accounts
from cfquant.trading_monitor import TradingMonitor, day_text


def prepare_runtime_history(page, frontend_url, tmp_path):
    _, errors = open_app(page, frontend_url, setup_required=False)
    result = TradingMonitor(tmp_path / 'absent.sqlite3').query()
    result['collector']['enabled'] = True
    result['nodes'] = [{'bridge_id':'qmt-one', 'name':'QMT history', 'mode':'ctypes',
                       'channel':'normal', 'online':True, 'checked_at':NOW,
                       'performance':{'available':False}}]
    queries = []
    def query(route):
        queries.append(route.request.url)
        route.fulfill(json={'ok':True, 'data':result})
    page.route('**/api/monitor?*', query)
    page.evaluate("() => { hideOnboardingModal({force:true}); setView('monitor', true); }")
    expect(page.locator('.monitor-runtime-target')).to_have_count(1)
    page.locator('#monitorAuto').uncheck()
    page.wait_for_function("document.querySelector('#tradingMonitor').getAttribute('aria-busy') === 'false'")
    page.locator('#monitorTabRuntime').click()
    return queries, errors


def runtime_history(count):
    return {'start':'all', 'end':'2026-11-09', 'retention_days':30, 'samples':[
        {'sampled_at':NOW + i * 60, 'normal':{
            'process':{'pid':123, 'name':f'qmt-{i}.exe', 'cpu_percent':i / 100,
                       'rss_bytes':104857600, 'memory_percent':1.2},
            'rates':{'callback_total_per_second':2.0, 'quote_distribution_batches_per_second':0.5,
                     'request_completed_per_second':0.25}}, 'trade':{}}
        for i in range(count)]}


def test_runtime_large_history_bounded_rendering_hover_and_release(page, frontend_url, tmp_path):
    page.clock.install()
    queries, errors = prepare_runtime_history(page, frontend_url, tmp_path)
    runtime_queries = []
    def history(route):
        runtime_queries.append(route.request.url)
        route.fulfill(json={'ok':True, 'data':runtime_history(10000)})
    page.route('**/api/monitor/runtime?*', history)
    page.locator('.monitor-runtime-target').click()
    expect(page.locator('#monitorRuntimeSamples tr')).to_have_count(100)
    expect(page.locator('#monitorRuntimePageText')).to_contain_text('第 100 / 100 页')
    expect(page.locator('#monitorRuntimeSamples tr').first).to_contain_text('qmt-9900.exe')
    expect(page.locator('#monitorRuntimeMetricCards')).to_contain_text('10,000 个样本')
    expect(page.locator('[data-runtime-metric=cpu] strong')).to_have_text('99.99 %')
    expect(page.locator('#monitorRuntimeCharts svg')).to_have_count(5)
    page.evaluate("() => { const auto = document.querySelector('#monitorAuto'); auto.checked = true; auto.dispatchEvent(new Event('change')); }")
    dialog = page.locator('#monitorRuntimeDetail')
    assert dialog.evaluate("node => node.querySelectorAll('*').length") < 2000
    assert dialog.evaluate("node => getComputedStyle(node, '::backdrop').backdropFilter") == 'none'
    layout = dialog.evaluate('node => ({width:node.clientWidth, scroll:node.scrollWidth})')
    assert layout['scroll'] <= layout['width'] + 1
    page.locator('#monitorRuntimePrev').click()
    expect(page.locator('#monitorRuntimePageText')).to_contain_text('第 99 / 100 页')
    expect(page.locator('#monitorRuntimeSamples tr').first).to_contain_text('qmt-9800.exe')
    page.locator('#monitorRuntimeNext').click()
    expect(page.locator('#monitorRuntimeNext')).to_be_disabled()
    assert len(runtime_queries) == 1  # Paging reuses history and preserves full-range charts.
    hover = page.evaluate("""async () => {
        const svg = document.querySelector('#monitorRuntimeCharts svg');
        const tooltip = svg.parentNode.querySelector('.monitor-runtime-chart-tooltip');
        svg.dispatchEvent(new PointerEvent('pointerleave'));
        const rect = svg.getBoundingClientRect();
        let writes = 0;
        const observer = new MutationObserver(records => { writes += records.length; });
        observer.observe(tooltip, {subtree:true, childList:true, characterData:true});
        for (let i = 0; i < 300; i++) svg.dispatchEvent(new PointerEvent('pointermove', {clientX:rect.left + i}));
        const immediateWrites = observer.takeRecords().length;
        await new Promise(requestAnimationFrame);
        await new Promise(requestAnimationFrame);
        observer.disconnect();
        const visible = !tooltip.hidden;
        svg.dispatchEvent(new PointerEvent('pointerleave'));
        return {immediateWrites, writes, visible, hiddenAfterLeave:tooltip.hidden};
    }""")
    assert hover == {'immediateWrites':0, 'writes':2, 'visible':True, 'hiddenAfterLeave':True}
    covered_queries = len(queries)
    page.clock.fast_forward(6000)
    assert len(queries) == covered_queries  # No repeated rendering behind the modal.
    page.locator('#monitorRuntimeDetailClose').click()
    expect(page.locator('#monitorRuntimeSamples tr')).to_have_count(0)
    expect(page.locator('#monitorRuntimeCharts svg')).to_have_count(0)
    expect(page.locator('#monitorRuntimeMetricCards button')).to_have_count(0)
    expect(page.locator('#monitorRuntimePagination')).not_to_be_visible()
    page.clock.fast_forward(6000)
    assert len(queries) > covered_queries
    assert errors == []


def test_runtime_history_replaced_requests_and_close_ignore_late_data(page, frontend_url, tmp_path):
    queries, errors = prepare_runtime_history(page, frontend_url, tmp_path)
    pending, aborted = [], []
    page.on('requestfailed', lambda request: aborted.append(request.url))
    def hold(route):
        pending.append(route)
        page.evaluate('count => { window.heldHistoryRequests = count; }', len(pending))
    page.route('**/api/monitor/runtime?*', hold)
    with page.expect_request('**/api/monitor/runtime?*'):
        page.locator('.monitor-runtime-target').click()
    page.wait_for_function('window.heldHistoryRequests === 1')
    with page.expect_request('**/api/monitor/runtime?*'):
        page.locator('#monitorRuntimeRange').select_option('7')
    page.wait_for_function('window.heldHistoryRequests === 2')
    pending[1].fulfill(json={'ok':True, 'data':runtime_history(1)})
    expect(page.locator('#monitorRuntimeSamples tr')).to_have_count(1)
    pending[0].fulfill(json={'ok':True, 'data':runtime_history(1000)})
    expect(page.locator('#monitorRuntimeSamples tr')).to_have_count(1)
    expect(page.locator('#monitorRuntimePrev')).to_be_disabled()
    expect(page.locator('#monitorRuntimeNext')).to_be_disabled()
    assert any('start=all' in url for url in aborted)
    with page.expect_request('**/api/monitor/runtime?*'):
        page.locator('#monitorRuntimeReload').click()
    page.wait_for_function('window.heldHistoryRequests === 3')
    covered_queries = len(queries)
    page.locator('#monitorRuntimeDetailClose').click()
    expect(page.locator('#monitorRuntimeCharts svg')).to_have_count(0)
    pending[2].fulfill(json={'ok':True, 'data':runtime_history(1000)})
    expect(page.locator('#monitorRuntimeSamples tr')).to_have_count(0)
    expect(page.locator('#monitorRuntimeDetail')).not_to_be_visible()
    assert len(queries) == covered_queries  # Closing respects disabled automatic refresh.
    assert len([url for url in aborted if '/api/monitor/runtime?' in url]) >= 2
    # Empty and missing metrics remain readable after reopening.
    with page.expect_request('**/api/monitor/runtime?*'):
        page.locator('.monitor-runtime-target').click()
    page.wait_for_function('window.heldHistoryRequests === 4')
    pending[3].fulfill(json={'ok':True, 'data':runtime_history(0)})
    expect(page.locator('#monitorRuntimeSamples')).to_contain_text('暂无分钟采样')
    expect(page.locator('#monitorRuntimeMetricCards')).to_contain_text('暂无可用样本')
    expect(page.locator('#monitorRuntimePagination')).not_to_be_visible()
    assert errors == []


def test_monitor_filters_history_paging_errors_and_narrow_layout(page, frontend_url, tmp_path):
    monitor = TradingMonitor(tmp_path / 'monitor.sqlite3')
    monitor.start()
    for i in range(1, 65):
        monitor.record_callback(callback(order_id=i, order_status=57 if i == 1 else 50,
                                         status_msg='<img src=x onerror=alert(1)>' if i == 1 else ''))
    monitor.record_callback(callback('trade', traded_id='fill-1', traded_volume=10))
    monitor.record_snapshot({'bridge_id':'qmt-one','bridge_name':'沪深主账户','checked_at':NOW-2,
                            'monitor':{'transport_mode':'ctypes','interval_seconds':10},
                            'normal':{'online':True}, 'trade':{'online':True}})
    assert monitor.flush()
    _, errors = open_app(page, frontend_url, setup_required=False)
    requests = []
    def respond(route):
        values = {key:items[0] for key,items in parse_qs(urlparse(route.request.url).query).items()}
        requests.append(values)
        result = monitor.query(now=NOW, **values)
        route.fulfill(json={'ok':True,'data':result})
    page.route('**/api/monitor?*', respond)
    page.route('**/api/monitor/settings', lambda route: route.fulfill(json={'ok':True, 'data':monitor.settings()}))
    page.route('**/api/monitor/runtime?*', lambda route: route.fulfill(json={'ok':True, 'data':{
        'start':'2026-11-03', 'end':'2026-11-03', 'retention_days':30, 'samples':[{
            'sampled_at':NOW - 60, 'normal':{
                'process':{'pid':123, 'name':'qmt.exe', 'cpu_percent':12.5, 'rss_bytes':104857600, 'memory_percent':1.2},
                'rates':{'callback_total_per_second':2.0, 'quote_callback_batches_per_second':1.0,
                         'quote_distribution_batches_per_second':0.5, 'request_completed_per_second':0.25},
                'qmt_callback_total':20, 'quote_callback_batches':10, 'quote_distribution_batches':5,
                'request_completed':3,
            }, 'trade':{}, 'process':{}}
        ]
    }}))
    try:
        page.evaluate("() => { hideOnboardingModal({force:true}); setView('monitor'); }")
        expect(page.locator('#viewTitle')).to_have_text('交易监控')
        page.locator('#monitorAuto').uncheck()
        page.locator('[name=start]').fill('2026-11-03')
        page.locator('[name=end]').fill('2026-11-03')
        page.locator('#monitorFilters [type=submit]').click()
        expect(page.locator('#monitorStats')).to_contain_text('64')
        expect(page.locator('#monitorError')).not_to_be_visible()
        expect(page.locator('#monitorTradingPanel')).to_be_visible()
        expect(page.locator('#monitorRuntimePanel')).not_to_be_visible()
        page.locator('#monitorTabRuntime').click()
        expect(page.locator('#monitorRuntimePanel')).to_be_visible()
        expect(page.locator('#monitorTabRuntime')).to_have_attribute('aria-selected', 'true')
        page.locator('#monitorRuntimeTargets .monitor-runtime-target').first.click()
        expect(page.locator('#monitorRuntimeDetail')).to_be_visible()
        dialog_box = page.locator('#monitorRuntimeDetail').bounding_box()
        viewport = page.viewport_size
        assert dialog_box and viewport
        assert abs((dialog_box['x'] + dialog_box['width'] / 2) - viewport['width'] / 2) <= 2
        dialog_layout = page.locator('#monitorRuntimeDetail').evaluate('(node) => ({width: node.clientWidth, scroll: node.scrollWidth})')
        assert dialog_layout['scroll'] <= dialog_layout['width'] + 1
        metric_card_bottom = page.locator('#monitorRuntimeMetricCards .monitor-runtime-metric-card').first.evaluate('(node) => node.getBoundingClientRect().bottom')
        toolbar_top = page.locator('.monitor-runtime-chart-toolbar').evaluate('(node) => node.getBoundingClientRect().top')
        assert toolbar_top >= metric_card_bottom
        expect(page.locator('#monitorRuntimeMetricCards .monitor-runtime-metric-card')).to_have_count(5)
        expect(page.locator('#monitorRuntimeCharts .monitor-runtime-chart-card')).to_have_count(5)
        expect(page.locator('#monitorRuntimeCharts svg')).to_have_count(5)
        page.locator('#monitorRuntimeCharts [data-runtime-chart="cpu"] svg').hover(position={'x': 220, 'y': 80})
        expect(page.locator('.monitor-runtime-chart-tooltip:visible')).to_have_count(1)
        expect(page.locator('#monitorRuntimeSamples')).to_contain_text('qmt.exe')
        page.locator('#monitorRuntimeDetailClose').click()
        expect(page.locator('#monitorRuntimeDetail')).not_to_be_visible()
        page.locator('#monitorTabTrading').click()
        expect(page.locator('#monitorTradingPanel')).to_be_visible()
        expect(page.locator('#monitorRuntimePanel')).not_to_be_visible()
        assert page.locator('#monitorAuto').bounding_box()['width'] <= 20
        expect(page.locator('#monitorNodes')).to_contain_text('沪深主账户')
        expect(page.locator('#monitorChart svg')).to_have_count(1)
        expect(page.locator('#monitorPageText')).to_contain_text('第 1 / 2 页')
        page.locator('#monitorNext').click()
        expect(page.locator('#monitorPageText')).to_contain_text('第 2 / 2 页')
        page.locator('#monitorKind').select_option('abnormal')
        expect(page.locator('#monitorEvents')).to_contain_text('<img src=x onerror=alert(1)>')
        expect(page.locator('#monitorEvents img')).to_have_count(0)
        expect(page.locator('#monitorNext')).to_be_disabled()
        page.locator('#monitorFilters [name=bridge_id]').select_option('qmt-one')
        page.locator('#monitorFilters [name=account]').select_option(label='paper · STOCK')
        page.locator('#monitorFilters [type=submit]').click()
        expect(page.locator('#monitorPageText')).to_contain_text('共 1 条')
        page.wait_for_function("!document.querySelector('#tradingMonitor').matches('[aria-busy=true]')")
        assert requests[-1]['account_id'] == 'paper' and requests[-1]['bridge_id'] == 'qmt-one'
        if page.viewport_size['width'] == 1440:
            page.locator('#monitorKind').select_option('')
            expect(page.locator('#monitorPageText')).to_contain_text('第 1 / 2 页')
            target = Path(__file__).resolve().parents[2] / 'runtime' / 'reports' / 'trading-monitor-desktop.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), full_page=True)
        else:
            target = Path(__file__).resolve().parents[2] / 'runtime' / 'reports' / 'trading-monitor-mobile.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), full_page=True)
        measured = page.locator('#tradingMonitor').evaluate('(node) => ({width:node.clientWidth, scroll:node.scrollWidth})')
        assert measured['scroll'] <= measured['width'] + 1
        page.locator('[name=start]').fill('2026-11-02')
        page.locator('[name=end]').fill('2026-11-02')
        page.locator('#monitorFilters [type=submit]').click()
        expect(page.locator('#monitorFreshness')).to_contain_text('历史回看')
        expect(page.locator('#monitorEvents')).to_contain_text('没有记录')
        expect(page.locator('#monitorNodeNote')).to_contain_text('不表示当前在线状态')
        page.route('**/api/monitor?*', lambda route: route.fulfill(status=500, json={'ok':False,'error':'fixture database unavailable'}))
        page.locator('#monitorFilters [type=submit]').click()
        expect(page.locator('#monitorError')).to_contain_text('fixture database unavailable')
        expect(page.locator('#monitorFreshness')).to_contain_text('刷新失败')
        assert errors == []
    finally:
        monitor.close()


def test_monitor_default_off_toggle_history_and_save_failure(page, frontend_url, tmp_path):
    monitor = TradingMonitor(tmp_path / 'opt-in.sqlite3')
    monitor.update_accounts(bound_accounts())
    _, errors = open_app(page, frontend_url, setup_required=False)
    posted = []
    def settings(route):
        if route.request.method == 'POST':
            posted.append(route.request.post_data_json)
            monitor.configure(**posted[-1])
        route.fulfill(json={'ok':True, 'data':monitor.settings()})
    def query(route):
        values = {key:items[0] for key,items in parse_qs(urlparse(route.request.url).query).items()}
        route.fulfill(json={'ok':True, 'data':monitor.query(**values)})
    page.route('**/api/monitor?*', query)
    page.route('**/api/monitor/settings', settings)
    try:
        page.evaluate("() => { hideOnboardingModal({force:true}); setView('monitor'); }")
        dialog = page.locator('#monitorSettingsDialog')
        expect(dialog).to_be_visible()
        expect(page.locator('#tradingMonitor')).not_to_be_visible()
        expect(page.locator('#monitorDialogTitle')).to_have_text('开启交易监控？')
        expect(page.locator('#monitorImpact')).to_contain_text('ms')
        assert not monitor.path.exists() and monitor._thread is None
        page.locator('#monitorDialogCancel').click()
        expect(dialog).not_to_be_visible()
        assert not posted
        expect(page.locator('#viewTitle')).not_to_have_text('交易监控')
        page.evaluate("setView('monitor')")
        page.locator('#monitorDialogSave').click()
        expect(page.locator('#viewTitle')).to_have_text('交易监控')
        expect(page.locator('#monitorControlStatus')).to_have_text('监控已开启')
        expect(dialog).not_to_be_visible()
        assert posted == [{'enabled':True}]
        page.locator('#monitorAuto').uncheck()
        page.locator('#monitorSettings').click()
        switch = page.get_by_role('switch', name='开启交易监控')
        expect(switch).to_be_checked()
        expect(page.get_by_role('radio', name='全部已绑定账号（默认）')).to_be_checked()
        page.get_by_role('radio', name='指定账号', exact=True).check()
        page.locator('[name=monitorAccount]').nth(1).uncheck()
        page.locator('[name=monitorAccount]').nth(2).uncheck()
        page.locator('#monitorRuntimeRetentionDays').fill('7')
        assert monitor.account_keys is None  # Draft changes do not apply before save.
        target = Path(__file__).resolve().parents[2] / 'runtime' / 'reports' / f'monitor-settings-{page.viewport_size["width"]}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
        measured = dialog.evaluate('(node) => ({width:node.clientWidth, scroll:node.scrollWidth})')
        assert measured['scroll'] <= measured['width'] + 1
        page.locator('#monitorDialogSave').click()
        expect(dialog).not_to_be_visible()
        assert monitor.account_keys == [bound_accounts()[0]['account_key']]
        assert monitor.runtime_retention_days == 7
        page.locator('#monitorSettings').click()
        expect(page.get_by_role('radio', name='指定账号', exact=True)).to_be_checked()
        expect(page.locator('[name=monitorAccount]').nth(0)).to_be_checked()
        expect(page.locator('[name=monitorAccount]').nth(1)).not_to_be_checked()
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        event = callback()
        event['data']['order_date'] = event['data']['trade_date'] = day_text().replace('-', '')
        monitor.record_callback(event)
        assert monitor.flush()
        page.locator('#monitorFilters [type=submit]').click()
        expect(page.locator('#monitorPageText')).to_contain_text('共 1 条')
        page.locator('#monitorSettings').click()
        expect(switch).to_be_enabled()
        switch.uncheck()
        page.locator('#monitorDialogSave').click()
        expect(dialog).not_to_be_visible()
        expect(page.locator('#monitorControlStatus')).to_contain_text('监控已关闭')
        expect(page.locator('#monitorFreshness')).to_contain_text('采集关闭')
        expect(page.locator('#monitorPageText')).to_contain_text('共 1 条')
        assert not monitor.enabled and not monitor._thread.is_alive()
        assert posted[-1] == {'enabled':False, 'account_keys':[bound_accounts()[0]['account_key']]}
        def failed_save(route):
            if route.request.method == 'POST':
                route.fulfill(status=400, json={'ok':False, 'error':'synthetic save failure'})
            else:
                route.fulfill(json={'ok':True, 'data':monitor.settings()})
        page.route('**/api/monitor/settings', failed_save)
        page.evaluate("setView('overview'); setView('monitor')")
        expect(page.locator('#monitorDialogTitle')).to_have_text('开启交易监控？')
        page.locator('#monitorDialogSave').click()
        expect(page.locator('#monitorSettingsError')).to_contain_text('synthetic save failure')
        expect(dialog).to_be_visible()
        expect(page.locator('#tradingMonitor')).not_to_be_visible()
        assert not monitor.enabled
        assert errors == []
    finally:
        monitor.close()


def test_monitor_entry_failure_and_navigation_race(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    page.route('**/api/monitor/settings', lambda route: route.fulfill(status=500, json={'ok':False, 'error':'offline'}))
    page.evaluate("() => { hideOnboardingModal({force:true}); setView('monitor'); }")
    expect(page.locator('#monitorSettingsError')).to_contain_text('offline')
    expect(page.locator('#monitorDialogSave')).to_be_disabled()
    expect(page.locator('#tradingMonitor')).not_to_be_visible()
    page.locator('#monitorDialogCancel').click()
    pending = []
    page.route('**/api/monitor/settings', lambda route: pending.append(route))
    with page.expect_request('**/api/monitor/settings'):
        page.evaluate("setView('monitor')")
    page.evaluate("setView('overview')")
    assert pending
    pending[0].fulfill(json={'ok':True,'data':{'enabled':False,'account_keys':None,'accounts':[]}})
    page.wait_for_timeout(150)
    expect(page.locator('#monitorSettingsDialog')).not_to_be_visible()
    expect(page.locator('#viewTitle')).to_have_text('首页')
    assert errors == []


def test_monitor_remembered_view_requires_opt_in_and_validates_empty_selection(page, frontend_url):
    _, errors = open_app(page, frontend_url, setup_required=False)
    posted = []
    def settings(route):
        if route.request.method == 'POST':
            posted.append(route.request.post_data_json)
        route.fulfill(json={'ok':True, 'data':{'enabled':False, 'account_keys':None, 'accounts':bound_accounts()}})
    page.route('**/api/monitor/settings', settings)
    page.evaluate("localStorage.setItem('cfquant.view', 'monitor')")
    page.reload()
    dialog = page.locator('#monitorSettingsDialog')
    expect(dialog).to_be_visible()
    expect(page.locator('#tradingMonitor')).not_to_be_visible()
    page.locator('#monitorAdjustSettings').click()
    expect(page.get_by_role('switch', name='开启交易监控')).to_be_checked()
    page.get_by_role('radio', name='指定账号', exact=True).check()
    for checkbox in page.locator('[name=monitorAccount]').all():
        checkbox.uncheck()
    page.locator('#monitorDialogSave').click()
    expect(page.locator('#monitorSettingsError')).to_contain_text('至少选择一个')
    assert posted == []
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    expect(page.locator('#tradingMonitor')).not_to_be_visible()
    assert errors == []
