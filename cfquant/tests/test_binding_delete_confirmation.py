"""Exercise binding deletion with mocked APIs, never real account settings."""
import pytest

from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url, open_app, page


@pytest.fixture
def bindings(page, frontend_url):
    requests, errors = open_app(page, frontend_url)
    config = page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        const selectedKey = makeAccountKey('DEMO_ACCOUNT', 'STOCK', 'first');
        const targetKey = makeAccountKey('DEMO_ACCOUNT', 'CREDIT', 'second');
        const selected = {account_id: 'DEMO_ACCOUNT', account_type: 'STOCK',
            account_key: selectedKey, bridge_id: 'first', display_name: 'Paper stock', enabled: true};
        const target = {account_id: 'DEMO_ACCOUNT', account_type: 'CREDIT',
            account_key: targetKey, bridge_id: 'second', display_name: 'Paper credit', enabled: true};
        state.accountConfigs = {[selectedKey]: selected, [targetKey]: target};
        state.accountPairs = {};
        state.bridges = {first: {name: 'First'}, second: {name: 'Second'}};
        state.accountId = selected.account_id;
        state.accountType = selected.account_type;
        state.accountKey = selectedKey;
        state.defaultAccountId = selected.account_id;
        state.defaultAccountType = selected.account_type;
        state.defaultAccountKey = selectedKey;
        setView('bindings');
        renderAccountPairs();
        renderCachedBindingStatuses();
        return {selected, target, typeLabel: accountTypeLabel('CREDIT')};
    }""")
    deleted = []

    def delete_request(route):
        deleted.append(route.request.post_data_json)
        route.fulfill(json={"ok": True, "data": {
            "account_configs": {config["selected"]["account_key"]: config["selected"]},
            "account_pairs": {},
        }})

    page.route("**/api/account-config/delete", delete_request)
    return config, requests, errors, deleted


@pytest.mark.parametrize("confirm", [False, True], ids=["cancel", "confirm"])
def test_binding_delete_requires_confirmation_for_the_exact_account(page, bindings, confirm, tmp_path):
    config, requests, errors, deleted = bindings
    target = config["target"]
    button = page.locator('#bindingStatusBody [data-binding-action="delete"][data-account-key="%s"]' % target["account_key"])
    dialogs = []

    def handle(dialog):
        dialogs.append((dialog.type, dialog.message))
        assert deleted == []
        if confirm:
            dialog.accept()
        else:
            dialog.dismiss()

    page.once("dialog", handle)
    button.click()
    assert len(dialogs) == 1 and dialogs[0][0] == "confirm"
    for value in (target["display_name"], target["account_id"], config["typeLabel"], target["bridge_id"]):
        assert value in dialogs[0][1]
    if confirm:
        expect(button).to_have_count(0)
        assert deleted == [{key: target[key] for key in ("account_id", "account_type", "account_key")}]
    else:
        expect(button).to_be_visible()
        assert deleted == []
        assert not any(method == "POST" and "delete" in path for method, path in requests)
        assert page.evaluate("Object.keys(state.accountConfigs).length") == 2
    assert page.evaluate("state.accountKey") == config["selected"]["account_key"]
    page.screenshot(path=str(tmp_path / "binding-delete-result.png"))
    assert errors == []


def test_delete_current_account_uses_the_same_confirmation(page, bindings):
    config, requests, errors, deleted = bindings
    dialogs = []

    def dismiss(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.once("dialog", dismiss)
    page.evaluate("removeCurrentAccountPair()")
    assert len(dialogs) == 1 and config["selected"]["display_name"] in dialogs[0]
    assert deleted == []
    assert page.evaluate("state.accountKey") == config["selected"]["account_key"]
    assert errors == []
