"""Offline browser checks for independent release and QMT version requests."""

from urllib.parse import parse_qs, urlparse

import pytest

from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url
from cfquant.tests.test_navigation_browser import open_console


@pytest.fixture(params=[1920, 390], ids=["desktop", "mobile"])
def page(browser, request):
    mobile = request.param < 600
    context = browser.new_context(viewport={"width": request.param, "height": 1080}, has_touch=mobile)
    page = context.new_page()
    page.set_default_timeout(10000)
    yield page
    context.close()


def activate(page, selector):
    control = page.locator(selector)
    if page.viewport_size["width"] < 600:
        control.tap()
    else:
        control.click()


def version_response(version="2.0.0", bridge_id="default"):
    return {
        "core_version": "1.0.0", "current_version": "1.0.0", "bridge_id": bridge_id,
        "comparison": "newer", "core_comparison": "newer",
        "remote": {"version": version, "source": "cfquant.org"},
        "qmt_runtime": {"reported": False},
    }


def test_slow_qmt_does_not_block_release_result_or_duplicate_requests(page, frontend_url):
    _, errors = open_console(page, frontend_url)
    page.wait_for_function("!state.versionCheckInFlight")
    releases, pending_qmt = [], []

    def respond(route):
        query = parse_qs(urlparse(route.request.url).query)
        if query.get("probe_qmt") == ["1"]:
            pending_qmt.append(route)
        else:
            releases.append(query)
            data = version_response("2.0.0" if len(releases) == 1 else "3.0.0")
            route.fulfill(json={"ok": True, "data": data})

    page.route("**/api/version?*", respond)
    activate(page, "#versionBadge")
    expect(page.locator("#versionBadgeLatestLabel")).to_have_text("2.0.0")
    expect(page.locator("[data-version-runtime] strong")).to_have_text("后台检查中")
    expect(page.locator('[data-version-action="recheck"]')).to_be_enabled()
    assert len(releases) == len(pending_qmt) == 1
    assert releases[0]["probe_qmt"] == ["0"]
    assert releases[0]["force_remote"] == ["0"]

    activate(page, '[data-version-action="recheck"]')
    expect(page.locator("#versionBadgeLatestLabel")).to_have_text("3.0.0")
    assert len(releases) == 2 and len(pending_qmt) == 1
    assert releases[1]["force_remote"] == ["1"]
    pending_qmt[0].fulfill(json={"ok": True, "data": {
        "bridge_id": "default", "remote": None,
        "qmt_runtime": {"reported": False, "message": "QMT test timeout"},
    }})
    expect(page.locator("[data-version-runtime] small")).to_have_text("QMT test timeout")
    expect(page.locator("#versionBadgeLatestLabel")).to_have_text("3.0.0")
    expect(page.locator("#versionAlert")).to_be_hidden()
    page.keyboard.press("Escape")
    page.mouse.move(page.viewport_size["width"] - 1, page.viewport_size["height"] - 1)
    activate(page, "#versionBadge")
    assert len(releases) == 2 and len(pending_qmt) == 1
    assert not errors


def test_release_cache_expires_and_local_refresh_preserves_remote(page, frontend_url):
    _, errors = open_console(page, frontend_url)
    page.wait_for_function("!state.versionCheckInFlight")
    requests = []

    def respond(route):
        query = parse_qs(urlparse(route.request.url).query)
        requests.append(query)
        data = version_response()
        if query["remote"] == ["0"]:
            data.update(remote=None, comparison="unchecked", core_comparison="unknown")
        route.fulfill(json={"ok": True, "data": data})

    page.route("**/api/version?*", respond)
    page.evaluate("Promise.all([refreshProjectVersion(), refreshProjectVersion()])")
    assert len(requests) == 1
    page.evaluate("refreshProjectVersion()")
    assert len(requests) == 1
    page.evaluate("refreshProjectVersion({remote: false, force: true})")
    assert len(requests) == 2 and requests[-1]["probe_qmt"] == ["0"]
    expect(page.locator("#versionBadgeLatestLabel")).to_have_text("2.0.0")
    assert page.evaluate("state.versionInfo.comparison") == "newer"
    page.evaluate("state.versionRemoteCheckedAt -= 300001")
    page.evaluate("refreshProjectVersion()")
    assert len(requests) == 3 and requests[-1]["force_remote"] == ["0"]
    assert not errors


def test_qmt_failure_preserves_release_and_previous_bridge_reply_is_ignored(page, frontend_url):
    _, errors = open_console(page, frontend_url)
    page.wait_for_function("!state.versionCheckInFlight")
    page.evaluate("renderProjectVersion({core_version: '1.0.0', remote: {version: '2.0.0'}})")
    pending = []
    page.route("**/api/version?*", lambda route: pending.append(route))
    page.evaluate("void refreshQmtRuntimeVersion()")
    page.wait_for_function("!!state.qmtVersionCheckPromise")
    page.evaluate("state.bridgeId = 'other'; document.querySelector('#bridgeSelect').value = 'other'")
    pending[0].fulfill(json={"ok": True, "data": {
        "bridge_id": "default", "qmt_runtime": {"reported": True, "version": "old-bridge"},
    }})
    page.wait_for_function("!state.qmtVersionCheckPromise")
    assert page.evaluate("state.qmtVersionInfo") is None
    page.evaluate("void refreshQmtRuntimeVersion()")
    page.wait_for_function("!!state.qmtVersionCheckPromise")
    pending[1].abort()
    page.wait_for_function("!state.qmtVersionCheckPromise")
    expect(page.locator("#versionBadgeLatestLabel")).to_have_text("2.0.0")
    assert page.evaluate("state.qmtVersionError")
    assert not page.evaluate("state.versionInfo.remote.error")
    assert not errors
