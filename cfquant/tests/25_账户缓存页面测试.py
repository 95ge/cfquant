"""Browser-only account-cache checks with mocked API calls, never a QMT server."""

from cfquant.tests.test_tutorial_reader import browser, frontend_url, open_app, page


def test_visible_account_views_read_cache_without_forcing_qmt(page, frontend_url, tmp_path):
    _, errors = open_app(page, frontend_url)
    calls = page.evaluate("""async () => {
        const calls = [];
        state.appStarted = true;
        selectedAccount = () => 'paper';
        selectedAccountType = () => 'STOCK';
        selectedAccountKey = () => 'default:STOCK:paper';
        selectedBridge = () => 'default';
        selectedChannel = () => 'trade';
        api = async url => { calls.push(url); return {}; };
        for (const view of ['overview', 'trade', 'settings', 'bindings', 'callbacks', 'tutorial']) {
            state.currentView = view;
            await refreshVisibleAccountCache();
        }
        Object.defineProperty(document, 'hidden', { configurable: true, value: true });
        state.currentView = 'trade';
        await refreshVisibleAccountCache();
        return calls;
    }""")
    assert len(calls) == 2
    assert all("sections=asset%2Cpositions" in url for url in calls)
    assert all("force=" not in url and "subscribe=0" not in url for url in calls)
    page.screenshot(path=str(tmp_path / "account-cache.png"))
    assert errors == []


def test_visible_cache_reads_do_not_overlap(page, frontend_url):
    open_app(page, frontend_url)
    result = page.evaluate("""async () => {
        state.appStarted = true;
        state.currentView = 'overview';
        let count = 0;
        let release;
        refreshAccount = () => { count += 1; return new Promise(resolve => { release = resolve; }); };
        const first = refreshVisibleAccountCache();
        await refreshVisibleAccountCache();
        const inFlight = state.accountCacheRefreshInFlight;
        release();
        await first;
        return { count, inFlight, finished: !state.accountCacheRefreshInFlight };
    }""")
    assert result == {"count": 1, "inFlight": True, "finished": True}


def test_trade_callback_refresh_uses_cache_for_asset_and_positions(page, frontend_url):
    open_app(page, frontend_url)
    calls = page.evaluate("""async () => {
        state.appStarted = true;
        state.currentView = 'trade';
        const calls = [];
        refreshAccount = async (sections, options = {}) => { calls.push({ sections, options }); };
        state.orderCallbackRefreshSections = new Set(['asset', 'positions', 'orders', 'trades']);
        runOrderCallbackRefresh();
        await new Promise(resolve => setTimeout(resolve, 0));
        return calls;
    }""")
    assert calls == [
        {"sections": "asset,positions", "options": {}},
        {"sections": "orders,trades", "options": {"force": True, "subscribe": False}},
    ]


def test_account_switch_does_not_render_the_previous_accounts_response(page, frontend_url):
    open_app(page, frontend_url)
    rendered = page.evaluate("""async () => {
        let current = 'old';
        selectedAccount = () => current;
        selectedAccountType = () => 'STOCK';
        selectedAccountKey = () => `default:STOCK:${current}`;
        selectedBridge = () => 'default';
        selectedChannel = () => 'trade';
        let release;
        api = () => new Promise(resolve => { release = resolve; });
        const rendered = [];
        renderAsset = value => rendered.push(value);
        const pending = refreshAccount('asset');
        current = 'new';
        release({ asset: { ok: true, data: { available: 100 } } });
        await pending;
        return rendered;
    }""")
    assert rendered == []


def test_stale_data_is_visible_but_failure_is_logged_once_per_query(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    result = page.evaluate("""() => {
        const identity = ['paper:STOCK', 'STOCK', 'default', 'normal'];
        const notices = [];
        log = (message, data) => notices.push(message);
        const success = { ok: true, data: { available: 100, balance: 1000 }, checked_at: 1000 };
        renderAccountSection('asset', success, identity);
        const failed = { ...success, ok: false, refresh_ok: false, stale: true, has_data: true,
          error: 'timeout', checked_at: 1030, data_checked_at_text: '2026-10-21 10:00:00', next_retry_at: 1035 };
        for (const age of [30000, 36000, 45000]) renderAccountSection('asset', { ...failed, cache_age_ms: age }, identity);
        const text = document.querySelector('[data-account-refresh-section="asset"]').textContent;
        const balance = document.querySelectorAll('#assetGrid strong')[1].textContent;
        renderAccountSection('asset', { ...failed, checked_at: 1040 }, identity);
        renderAccountSection('asset', success, identity);
        renderAccountSection('asset', success, identity);
        const hidden = document.querySelector('[data-account-refresh-section="asset"]').hidden;
        return { notices, text, balance, hidden };
    }""")
    assert result["notices"] == ["资产查询失败", "资产查询失败", "资产查询已恢复"]
    assert result["balance"] == "100.00" and result["hidden"] is True
    assert "数据已过期" in result["text"] and "2026-10-21 10:00:00" in result["text"]
    assert errors == []


def test_first_failure_clears_previous_account_values_without_zeroes(page, frontend_url):
    open_app(page, frontend_url)
    result = page.evaluate("""() => {
        log = () => {};
        const old = ['old', 'STOCK', 'default', 'normal'];
        const next = ['new', 'STOCK', 'default', 'normal'];
        renderAccountSection('asset', { ok: true, data: { available: 999 } }, old);
        renderAccountSection('positions', { ok: true, data: [{ stock_code: '000001.SZ', volume: 100 }] }, old);
        const failure = { ok: false, has_data: false, stale: false, error: 'timeout', checked_at: 1000 };
        renderAccountSection('asset', failure, next);
        renderAccountSection('positions', failure, next);
        return {
          assets: [...document.querySelectorAll('#assetGrid strong')].map(n => n.textContent),
          counts: document.querySelector('#positionCount').textContent,
          tables: ['positionsBody', 'tradePositionsBody'].map(id => document.getElementById(id).textContent),
          notices: [...document.querySelectorAll('[data-account-refresh-section="positions"]')].map(n => n.textContent)
        };
    }""")
    assert result["assets"] == ["--"] * 4 and result["counts"] == "--"
    assert all("暂无可用数据" in text for text in result["tables"] + result["notices"])


def test_error_deduplication_is_scoped_to_account_and_section(page, frontend_url):
    open_app(page, frontend_url)
    messages = page.evaluate("""() => {
        const messages = [];
        log = message => messages.push(message);
        const a = ['a', 'STOCK', 'default', 'normal'];
        const b = ['b', 'STOCK', 'default', 'normal'];
        const failure = { ok: false, error: 'timeout', checked_at: 1000 };
        for (const identity of [a, a, b, b, a]) renderAccountSection('asset', failure, identity);
        renderAccountSection('positions', failure, a);
        renderAccountSection('asset', { ok: true, data: {} }, a);
        renderAccountSection('asset', failure, a);
        return messages;
    }""")
    assert messages == ["资产查询失败", "资产查询失败", "持仓查询失败", "资产查询已恢复", "资产查询失败"]


def test_market_failure_signature_ignores_cache_age(page, frontend_url):
    open_app(page, frontend_url)
    count = page.evaluate("""() => {
        let count = 0;
        log = () => { count += 1; };
        const identity = ['paper', 'STOCK', 'base', 'trade'];
        const row = { ok: false, error: 'SZ timeout', stale: true, has_data: true, data: [],
          market_results: { SZ: { checked_at: 1000, error: 'timeout', cache_age_ms: 100 } } };
        renderAccountSection('positions', row, identity);
        row.market_results.SZ.cache_age_ms = 1000;
        renderAccountSection('positions', row, identity);
        row.market_results.SZ.checked_at = 1005;
        renderAccountSection('positions', row, identity);
        return count;
    }""")
    assert count == 2
