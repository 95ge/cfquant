"""Account/callback diagnostics with offline APIs; no QMT or trading service."""
from cfquant.tests.test_tutorial_reader import browser, page, expect, frontend_url, open_app


def open_logs(page, frontend_url):
    requests, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.getElementById('setupOverlay').remove();
        window.logTestAccount = 'paper-a';
        selectedAccount = () => window.logTestAccount;
        selectedAccountType = () => 'STOCK';
        selectedAccountKey = () => `default:STOCK:${window.logTestAccount}`;
        selectedBridge = () => 'default';
        selectedChannel = () => 'normal';
        window.logTestIdentity = account => [`default:STOCK:${account}`, 'STOCK', 'default', 'normal'];
        window.logTestFailure = {
            ok: false, error_code: 'QMT_BRIDGE_NOT_CONNECTED',
            error: 'QMT pipe bridge not connected for channel=cfquant.normal.request',
            request_channel: 'cfquant.normal.request', checked_at: 1000,
        };
        setView('callbacks');
        document.getElementById('logCategoryFilter').value = 'all';
        document.getElementById('logAccountFilter').value = 'all';
        CfquantActivityLog.clearVisible();
        document.getElementById('logCategoryFilter').value = 'current';
        document.getElementById('logAccountFilter').value = 'current';
        syncActivityLogContext();
    }""")
    return requests, errors


def test_account_failures_merge_without_polluting_callbacks(page, frontend_url, tmp_path):
    _, errors = open_logs(page, frontend_url)
    page.evaluate("""() => {
        const identity = logTestIdentity('paper-a');
        for (const name of ['asset', 'positions', 'orders', 'trades']) {
            renderAccountSection(name, logTestFailure, identity);
        }
        for (const age of [100, 200, 1000]) {
            for (const name of ['asset', 'positions', 'orders', 'trades']) {
                renderAccountSection(name, {...logTestFailure, cache_age_ms: age}, identity);
            }
        }
        log('系统状态已刷新');
        for (const name of ['asset', 'positions', 'orders', 'trades']) {
            renderAccountSection(name, {...logTestFailure, checked_at: 1060}, identity);
        }
    }""")
    expect(page.locator('#logBox .log-entry')).to_have_count(0)
    expect(page.locator('#logCount')).to_have_text('0 条 / 共 2 条')
    page.locator('#logCategoryFilter').select_option('account')
    row = page.locator('#logBox .log-entry')
    expect(row).to_have_count(1)
    expect(row.locator('.log-account')).to_contain_text('paper-a')
    expect(row.locator('.log-meta')).to_contain_text('失败累计 8 次')
    expect(row.locator('.log-affected')).to_have_text('涉及：资产、持仓、委托、成交')
    expect(row.locator('.log-state')).to_have_text('待恢复')
    row.locator('summary').click()
    expect(row.locator('pre')).to_contain_text('QMT_BRIDGE_NOT_CONNECTED')
    page.screenshot(path=str(tmp_path / 'account-log.png'))
    dimensions = page.locator('#activityLogPanel').evaluate('n => ({width: n.clientWidth, scroll: n.scrollWidth})')
    assert dimensions['scroll'] <= dimensions['width']

    page.evaluate("""() => {
        const identity = logTestIdentity('paper-a');
        renderAccountSection('asset', {ok: true, data: {}}, identity);
        renderAccountSection('positions', {ok: true, data: []}, identity);
        renderAccountSection('orders', {ok: false, warming_up: true}, identity);
    }""")
    expect(row.locator('.log-state')).to_have_text('待恢复')
    expect(row.locator('.log-affected')).to_contain_text('待恢复：委托、成交')
    page.evaluate("""() => {
        for (const name of ['orders', 'trades']) renderAccountSection(name, {ok: true, data: []}, logTestIdentity('paper-a'));
    }""")
    expect(row.locator('.log-state')).to_have_text('已恢复')
    expect(row.locator('.log-message')).to_have_text('账号查询已恢复')
    expect(row.locator('.log-meta')).to_contain_text('失败累计 8 次')
    page.evaluate("renderAccountSection('asset', {...logTestFailure, checked_at: 1120}, logTestIdentity('paper-a'))")
    expect(page.locator('#logBox .log-entry')).to_have_count(2)
    expect(page.locator('#logBox [data-status="active"] .log-meta')).to_contain_text('失败累计 1 次')
    assert errors == []


def test_filters_and_clear_keep_other_accounts_and_functions(page, frontend_url):
    _, errors = open_logs(page, frontend_url)
    page.evaluate("""() => {
        for (const account of ['paper-a', 'paper-b']) renderAccountSection('asset', logTestFailure, logTestIdentity(account));
        logCallbackResult(logAccountContext(), 'poll', new Error('callback endpoint unavailable'));
    }""")
    expect(page.locator('#logBox .log-entry')).to_have_count(1)
    expect(page.locator('#logBox .log-category')).to_have_text('回调事件')
    page.locator('#logCategoryFilter').select_option('account')
    expect(page.locator('#logBox .log-account')).to_contain_text('paper-a')
    page.evaluate("window.logTestAccount = 'paper-b'; syncActivityLogContext()")
    expect(page.locator('#logBox .log-account')).to_contain_text('paper-b')
    page.locator('#clearLogBtn').click()
    expect(page.locator('#logBox .log-entry')).to_have_count(0)
    page.locator('#logAccountFilter').select_option('all')
    expect(page.locator('#logBox .log-entry')).to_have_count(1)
    expect(page.locator('#logBox .log-account')).to_contain_text('paper-a')
    page.evaluate("renderAccountSection('asset', {ok: true, data: {}}, logTestIdentity('paper-a'))")
    expect(page.locator('#logBox .log-state')).to_have_text('已恢复')
    page.locator('#logCategoryFilter').select_option('all')
    expect(page.locator('#logBox .log-entry')).to_have_count(2)
    page.evaluate("renderAccountSection('asset', logTestFailure, logTestIdentity('paper-b'))")
    expect(page.locator('#logBox .log-entry')).to_have_count(3)
    assert errors == []


def test_callback_errors_follow_request_account_and_recover_on_empty_response(page, frontend_url):
    _, errors = open_logs(page, frontend_url)
    page.evaluate("""async () => {
        api = async () => { throw new Error('callback endpoint unavailable'); };
        await refreshCallbacks();
        log('unrelated status');
        await refreshCallbacks();
        api = () => new Promise((resolve, reject) => { window.rejectLogRequest = reject; });
        window.pendingLogRequest = refreshCallbacks();
        window.logTestAccount = 'paper-b';
        syncActivityLogContext();
        window.rejectLogRequest(new Error('callback endpoint unavailable'));
        await window.pendingLogRequest;
    }""")
    expect(page.locator('#logBox .log-entry')).to_have_count(0)
    page.locator('#logAccountFilter').select_option('all')
    row = page.locator('#logBox .log-entry')
    expect(row).to_have_count(1)
    expect(row.locator('.log-account')).to_contain_text('paper-a')
    expect(row.locator('.log-meta')).to_contain_text('失败累计 3 次')
    page.evaluate("api = async () => ({events: []}); refreshCallbacks()")
    expect(row.locator('.log-state')).to_have_text('待恢复')
    page.evaluate("window.logTestAccount = 'paper-a'; syncActivityLogContext(); refreshCallbacks()")
    expect(row.locator('.log-state')).to_have_text('已恢复')
    expect(row.locator('.log-message')).to_have_text('回调拉取已恢复')
    assert errors == []


def test_changed_errors_are_not_reported_as_recovery_and_scopes_stay_separate(page, frontend_url):
    _, errors = open_logs(page, frontend_url)
    page.locator('#logCategoryFilter').select_option('account')
    page.evaluate("""() => {
        const identity = logTestIdentity('paper-a');
        renderAccountSection('asset', logTestFailure, identity);
        renderAccountSection('asset', {ok: false, error: 'query timeout', checked_at: 1010}, identity);
        renderAccountSection('asset', logTestFailure, [identity[0], identity[1], identity[2], 'trade']);
    }""")
    expect(page.locator('#logBox [data-status="changed"]')).to_have_count(1)
    expect(page.locator('#logBox [data-status="active"]')).to_have_count(2)
    expect(page.locator('#logBox [data-status="recovered"]')).to_have_count(0)
    page.evaluate("renderAccountSection('asset', {ok: true, data: {}}, logTestIdentity('paper-a'))")
    expect(page.locator('#logBox [data-status="active"]')).to_have_count(1)
    expect(page.locator('#logBox [data-status="active"] .log-channel')).to_have_text('交易通道')
    assert errors == []


def test_market_failure_details_and_retention_are_safe(page, frontend_url):
    _, errors = open_logs(page, frontend_url)
    page.locator('#logCategoryFilter').select_option('all')
    page.evaluate("""() => {
        const failure = {ok: true, refresh_ok: false, data: [], partial_errors: ['SZ timeout'],
            market_results: {SZ: {error: 'timeout', checked_at: 1000}}};
        renderAccountSection('positions', failure, logTestIdentity('paper-a'));
        renderAccountSection('positions', {...failure, cache_age_ms: 100}, logTestIdentity('paper-a'));
        for (let i = 0; i < 185; i++) log(`system ${i}`);
        renderAccountSection('positions', {...failure, market_results: {SZ: {error: 'timeout', checked_at: 1005}}}, logTestIdentity('paper-a'));
        log('<img src=x onerror="window.logXss=true">', {detail: '<script>alert(1)</script>'});
    }""")
    expect(page.locator('#logBox .log-entry')).to_have_count(180)
    assert page.locator('#logBox img, #logBox script').count() == 0
    assert not page.evaluate('Boolean(window.logXss)')
    page.locator('#logCategoryFilter').select_option('account')
    expect(page.locator('#logBox .log-entry')).to_have_count(1)
    expect(page.locator('#logBox .log-meta')).to_contain_text('失败累计 1 次')
    page.locator('#logBox summary').click()
    expect(page.locator('#logBox pre')).to_contain_text('SZ')
    assert errors == []


def test_account_http_errors_are_classified_once_and_recovery_is_specific(page, frontend_url):
    _, errors = open_logs(page, frontend_url)
    page.evaluate("""async () => {
        api = () => new Promise((resolve, reject) => { window.rejectLogRequest = reject; });
        const pending = refreshAccount('asset,positions').catch(error => logRequestError('回调刷新交易数据失败', error));
        window.logTestAccount = 'paper-b';
        syncActivityLogContext();
        window.rejectLogRequest(new Error('HTTP 503'));
        await pending;
    }""")
    expect(page.locator('#logBox .log-entry')).to_have_count(0)
    page.locator('#logCategoryFilter').select_option('all')
    page.locator('#logAccountFilter').select_option('all')
    row = page.locator('#logBox .log-entry')
    expect(row).to_have_count(1)
    expect(row.locator('.log-category')).to_have_text('账号查询')
    expect(row.locator('.log-account')).to_contain_text('paper-a')
    expect(row.locator('.log-meta')).to_contain_text('失败累计 2 次')
    page.evaluate("""async () => {
        window.logTestAccount = 'paper-a';
        syncActivityLogContext();
        api = async () => ({asset: {ok: true, data: {}}});
        await refreshAccount('asset');
    }""")
    expect(row.locator('.log-state')).to_have_text('待恢复')
    expect(row.locator('.log-affected')).to_contain_text('待恢复：持仓接口')
    page.evaluate("""async () => {
        api = async () => ({positions: logTestFailure});
        await refreshAccount('positions');
    }""")
    expect(page.locator('#logBox .log-entry')).to_have_count(2)
    expect(page.locator('#logBox [data-status="recovered"] .log-message')).to_have_text('账号查询接口访问已恢复')
    expect(page.locator('#logBox [data-status="active"] .log-message')).to_have_text('QMT 通道未连接，账号查询失败')
    assert errors == []


def test_websocket_and_parse_failures_recover_independently(page, frontend_url):
    _, errors = open_logs(page, frontend_url)
    page.evaluate("""() => {
        window.WebSocket = class {
            constructor() { window.logTestSocket = this; }
            close() {}
        };
        state.appStarted = true;
        realtimeOrdersEnabled = () => true;
        connectOrderCallbackSocket({force: true});
        state.appStarted = false;
        logTestSocket.onerror();
        logTestSocket.onmessage({data: '{invalid'});
    }""")
    expect(page.locator('#logBox [data-status="active"]')).to_have_count(2)
    page.evaluate('logTestSocket.onopen()')
    expect(page.locator('#logBox [data-status="recovered"] .log-message')).to_have_text('实时回调连接已恢复')
    expect(page.locator('#logBox [data-status="active"]')).to_have_count(1)
    page.evaluate("logTestSocket.onmessage({data: JSON.stringify({events: []})})")
    expect(page.locator('#logBox [data-status="active"]')).to_have_count(0)
    expect(page.locator('#logBox [data-status="recovered"]')).to_have_count(2)
    assert errors == []


def test_successful_order_is_not_reported_as_failed_when_its_refresh_fails(page, frontend_url):
    requests, errors = open_logs(page, frontend_url)
    page.locator('#logCategoryFilter').select_option('all')
    paths = page.evaluate("""async () => {
        const paths = [];
        api = async url => {
            paths.push(url);
            if (url === '/api/order') return {seq: 22};
            throw new Error('HTTP 503');
        };
        await submitOrder({preventDefault() {}, currentTarget: document.getElementById('orderForm')});
        return paths;
    }""")
    assert paths[0] == '/api/order' and len(paths) == 2
    expect(page.locator('#logBox [data-category="trade"] .log-message')).to_have_text('委托已提交')
    expect(page.locator('#logBox [data-category="account"] .log-state')).to_have_text('待恢复')
    assert all(method == 'GET' for method, _ in requests)
    assert errors == []
