"""Browser checks for the binding page's live account refresh behavior."""

from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url, open_app, page


def seed_bindings(page):
    return page.evaluate(
        """() => {
        const firstKey = makeAccountKey('FIRST', 'STOCK', 'bridge-a');
        const secondKey = makeAccountKey('SECOND', 'STOCK', 'bridge-b');
        state.accountConfigs = {
          [firstKey]: {account_id: 'FIRST', account_type: 'STOCK', account_key: firstKey,
            bridge_id: 'bridge-a', display_name: '首账号', enabled: true},
          [secondKey]: {account_id: 'SECOND', account_type: 'STOCK', account_key: secondKey,
            bridge_id: 'bridge-b', display_name: '第二账号', enabled: true},
        };
        state.accountPairs = {};
        state.bridges = { 'bridge-a': {name: 'A'}, 'bridge-b': {name: 'B'} };
        state.appStarted = true;
        state.currentView = 'bindings';
        state.bindingAccountKey = '';
        state.bindingAccountIdentity = '';
        state.bindingAccountRevision = 0;
        state.bindingStatusSnapshot = null;
        renderCachedBindingStatuses();
        document.body.dataset.view = 'bindings';
        document.querySelectorAll('.view-bindings').forEach(node => node.classList.remove('hidden'));
        return {firstKey, secondKey};
    }"""
    )


def test_binding_page_defaults_to_first_account_and_refreshes_without_click(page, frontend_url):
    open_app(page, frontend_url)
    keys = seed_bindings(page)
    page.evaluate("""keys => {
        window.bindingOnline = {FIRST: true, SECOND: false};
        window.bindingRequests = [];
        api = async path => {
          bindingRequests.push(path);
          if (path === '/api/bindings/status') return {bindings: [
                {"account_key": keys["firstKey"], "account_id": "FIRST", "account_type": "STOCK",
                 "bridge_id": "bridge-a", "status": {"normal": {"online": bindingOnline.FIRST},
                 "trade": {"online": bindingOnline.FIRST}}},
                {"account_key": keys["secondKey"], "account_id": "SECOND", "account_type": "STOCK",
                 "bridge_id": "bridge-b", "status": {"normal": {"online": bindingOnline.SECOND},
                 "trade": {"online": bindingOnline.SECOND}}},
          ]};
          const accountId = path.includes('FIRST') ? 'FIRST' : 'SECOND';
          const value = accountId === 'FIRST' ? 101 : 202;
          return {asset: {ok: true, data: {balance: value, available: value,
            market_value: value, position_profit: 1}}, positions: {ok: true, data: []},
            cache: {checked_at_text: 'now'}};
        };
    }""", keys)
    page.evaluate("refreshVisibleBindings()")
    page.wait_for_timeout(20)
    expect(page.locator("#bindingAccountSelect")).to_have_value(keys["firstKey"])
    expect(page.locator("#pairAssetGrid strong").first).to_have_text("101.00")
    expect(page.locator("#bindingStatusBody .binding-status-cell .status-dot.online")).to_have_count(1)

    page.evaluate("bindingOnline.SECOND = true")
    page.evaluate("refreshVisibleBindings()")
    page.wait_for_timeout(20)
    expect(page.locator("#bindingStatusBody .binding-status-cell .status-dot.online")).to_have_count(2)
    assert page.evaluate("bindingRequests.includes('/api/bindings/status')")


def test_binding_page_selection_changes_data_and_uses_five_second_timer(page, frontend_url):
    open_app(page, frontend_url)
    keys = seed_bindings(page)
    page.evaluate("""keys => {
        api = async path => {
          if (path === '/api/bindings/status') return {bindings: []};
          const id = path.includes('SECOND') ? 202 : 101;
          return {asset: {ok: true, data: {balance: id}}, positions: {ok: true, data: []}};
        };
        refreshVisibleBindings();
    }""", keys)
    page.wait_for_timeout(20)
    page.locator("#bindingAccountSelect").select_option(keys["secondKey"])
    page.wait_for_timeout(20)
    expect(page.locator("#bindingAccountSelect")).to_have_value(keys["secondKey"])
    expect(page.locator("#pairAssetGrid strong").first).to_have_text("202.00")

    delays = page.evaluate("""() => {
        state.statusTimer = null;
        const delays = [];
        const original = window.setInterval;
        window.setInterval = (callback, delay) => { delays.push(delay); return 1; };
        startTimers();
        window.setInterval = original;
        return delays;
    }""")
    assert 5000 in delays
