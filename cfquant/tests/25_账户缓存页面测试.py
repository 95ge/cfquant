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


def test_trade_callback_refresh_uses_shared_cache_only_for_visible_sections(page, frontend_url):
    open_app(page, frontend_url)
    calls = page.evaluate("""async () => {
        state.appStarted = true;
        state.currentView = 'trade';
        setDataTab('orders', false);
        const calls = [];
        refreshAccount = async (sections, options = {}) => { calls.push({ sections, options }); };
        state.orderCallbackRefreshSections = new Set(['asset', 'positions', 'orders', 'trades']);
        runOrderCallbackRefresh();
        await new Promise(resolve => setTimeout(resolve, 0));
        return calls;
    }""")
    assert calls == [
        {"sections": "asset,positions,orders", "options": {}},
    ]


def test_callback_bursts_are_bounded_and_poll_after_the_last_trade(page, frontend_url):
    page.clock.install()
    open_app(page, frontend_url)
    page.evaluate("""() => {
        clearOrderCallbackRefresh();
        state.currentView = 'trade';
        setDataTab('trades', false);
        state.orderCallbackRefreshLastAt = -Infinity;
        window.cacheReads = [];
        refreshAccount = async (sections, options = {}) => {
            cacheReads.push({ sections, options, at: performance.now() });
        };
        appendServerCallbackEvent = event => event;
        rememberCfquantOrder = rememberOrderCallbackMeta = () => {};
        mergeOrderCallbackRow = () => true;
        window.burst = () => {
            for (let i = 0; i < 100; i++) handleOrderCallbackEvent({
                event: 'trader:on_stock_trade', data: { traded_id: String(i), order_id: 'order' }
            });
        };
    }""")
    for _ in range(10):
        page.evaluate("burst()")
        page.clock.run_for(1000)
    calls = page.evaluate("cacheReads")
    assert 5 <= len(calls) <= 6
    assert all(call["options"] == {} and "orders" not in call["sections"] for call in calls)
    assert all(b["at"] - a["at"] >= 2000 for a, b in zip(calls, calls[1:]))
    # No more callback: periodic cache reads still retrieve the final snapshot.
    page.clock.run_for(4000)
    assert page.evaluate("cacheReads.length") > len(calls)


def test_hidden_and_unrelated_views_do_not_requery_on_callbacks(page, frontend_url):
    page.clock.install()
    open_app(page, frontend_url)
    page.evaluate("""() => {
        clearOrderCallbackRefresh();
        state.currentView = 'orders';
        state.orderCallbackRefreshLastAt = performance.now();
        window.cacheReads = [];
        refreshAccount = async (sections, options = {}) => cacheReads.push({ sections, options });
        scheduleOrderCallbackRefresh('orders,trades');
        Object.defineProperty(document, 'hidden', { configurable: true, value: true });
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.clock.run_for(6000)
    assert page.evaluate("cacheReads") == []
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', { configurable: true, value: false });
        state.currentView = 'settings';
        for (let i = 0; i < 100; i++) scheduleOrderCallbackRefresh('asset,positions,orders,trades');
    }""")
    page.clock.run_for(6000)
    assert page.evaluate("cacheReads") == []
    page.evaluate("""() => {
        state.currentView = 'orders';
        document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.clock.run_for(2000)
    assert page.evaluate("cacheReads.length") >= 1
    assert all(row == {"sections": "orders", "options": {}} for row in page.evaluate("cacheReads"))
    page.evaluate("document.getElementById('autoRefresh').checked = false")
    before = page.evaluate("cacheReads.length")
    page.clock.run_for(6000)
    assert page.evaluate("cacheReads.length") == before


def test_slow_callback_cache_reads_never_overlap_and_drop_hidden_followups(page, frontend_url):
    page.clock.install()
    open_app(page, frontend_url)
    page.evaluate("""() => {
        clearOrderCallbackRefresh();
        state.currentView = 'orders';
        state.orderCallbackRefreshLastAt = -Infinity;
        window.cacheReadCount = 0;
        refreshAccount = () => {
            cacheReadCount += 1;
            return new Promise(resolve => { window.finishCacheRead = resolve; });
        };
        scheduleOrderCallbackRefresh('orders');
    }""")
    page.clock.run_for(6000)
    assert page.evaluate("cacheReadCount") == 1
    page.evaluate("""() => {
        Object.defineProperty(document, 'hidden', { configurable: true, value: true });
        document.dispatchEvent(new Event('visibilitychange'));
        finishCacheRead();
    }""")
    page.clock.run_for(6000)
    assert page.evaluate("cacheReadCount") == 1
    assert page.evaluate("!state.orderCallbackRefreshInFlight && !state.orderCallbackRefreshTimer")


def test_manual_orders_refresh_still_bypasses_cache(page, frontend_url):
    open_app(page, frontend_url)
    calls = page.evaluate("""async () => {
        clearOrderCallbackRefresh();
        state.currentView = 'settings';
        const calls = [];
        refreshAccount = async (sections, options = {}) => calls.push({ sections, options });
        document.getElementById('ordersBtn').click();
        await Promise.resolve();
        return calls;
    }""")
    assert calls == [{"sections": "orders", "options": {"force": True, "subscribe": False}}]


def test_cached_lists_do_not_undo_newer_callbacks_or_manual_refresh(page, frontend_url):
    open_app(page, frontend_url)
    result = page.evaluate("""() => {
        const identity = ['paper', 'STOCK', 'default', 'trade'];
        const renders = [];
        renderOrders = section => renders.push(section.data?.[0]?.order_id || 'empty');
        const snapshot = (id, at, cached = true) => ({
            ok: true, cached, checked_at: at, data: [{ order_id: id }]
        });
        renderAccountSection('orders', snapshot('cached', 100), identity);
        renderOrders({ data: [{ order_id: 'callback' }] });
        renderAccountSection('orders', snapshot('cached', 100), identity);
        renderAccountSection('orders', snapshot('manual', 105, false), identity);
        renderAccountSection('orders', snapshot('older-cache', 103), identity);
        renderAccountSection('orders', snapshot('reconciled', 106), identity);
        renderAccountSection('orders', snapshot('other-account', 90), ['other', ...identity.slice(1)]);
        renderAccountSection('orders', snapshot('back-to-paper', 106), identity);
        return renders;
    }""")
    assert result == ['cached', 'callback', 'manual', 'reconciled', 'other-account', 'back-to-paper']


def test_market_cache_changes_are_checked_per_market(page, frontend_url):
    open_app(page, frontend_url)
    result = page.evaluate("""() => {
        const identity = ['paper', 'STOCK', 'base', 'trade'];
        const renders = [];
        renderTrades = section => renders.push(section.data[0]);
        const snapshot = (id, sh, sz, cached = true) => ({
            ok: true, cached, data: [id], market_results: {
                SH: { checked_at: sh }, SZ: { checked_at: sz }
            }
        });
        renderAccountSection('trades', snapshot('initial', 100, 90), identity);
        renderAccountSection('trades', snapshot('unchanged', 100, 90), identity);
        renderAccountSection('trades', snapshot('sz-updated', 100, 95), identity);
        renderAccountSection('trades', snapshot('manual', 105, 105, false), identity);
        renderAccountSection('trades', snapshot('old-cache', 100, 95), identity);
        renderAccountSection('trades', snapshot('sh-updated', 110, 105), identity);
        return renders;
    }""")
    assert result == ['initial', 'sz-updated', 'manual', 'sh-updated']


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
