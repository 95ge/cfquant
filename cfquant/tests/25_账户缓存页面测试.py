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
