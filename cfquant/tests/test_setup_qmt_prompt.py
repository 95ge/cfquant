"""First setup QMT preflight with mocked processes; never touches a real QMT."""
from urllib.parse import parse_qs, urlparse

import pytest

from cfquant.tests.test_tutorial_reader import browser, expect, frontend_url, open_app, page


@pytest.mark.parametrize("action", ["cancel", "stop", "manual", "stopped", "check_error", "stop_error"])
@pytest.mark.parametrize("mode", ["lite", "lttx"])
def test_first_setup_qmt_confirmation(page, frontend_url, action, mode):
    requests, errors = open_app(page, frontend_url)
    running = [action != "stopped"]
    checked, saved, stopped, started = [], [], [], []
    directory = "C:/AuditQMT"

    def processes(route):
        target = parse_qs(urlparse(route.request.url).query)["qmt_dir"][0]
        checked.append(target)
        if action == "check_error":
            route.fulfill(status=500, json={"ok": False, "error": "process check failed"})
        else:
            route.fulfill(json={"ok": True, "data": {
                "qmt_dir": target, "running": running[0],
                "pids": [123] if running[0] else [], "processes": [],
            }})

    def stop(route):
        stopped.append(route.request.post_data_json)
        if action == "stop_error":
            route.fulfill(status=500, json={"ok": False, "error": "stop failed"})
        else:
            running[0] = False
            route.fulfill(json={"ok": True, "data": {
                "targets": [{"qmt_dir": directory, "after": {"running": False}}],
            }})

    def initialize(route):
        assert not running[0]
        saved.append(route.request.post_data_json)
        route.fulfill(json={"ok": True, "data": {"setup": {"setup_required": False}}})

    def start(route):
        assert len(saved) == 1
        started.append(route.request.post_data_json)
        route.fulfill(json={"ok": True, "data": {"targets": []}})

    page.route("**/api/qmt/processes?*", processes)
    page.route("**/api/qmt/processes/stop", stop)
    page.route("**/api/qmt/processes/start", start)
    page.route("**/api/setup/initialize", initialize)
    page.locator('#setupAccountId').fill('AUDIT_ACCOUNT')
    page.locator('#setupQmtDir').fill(directory)
    page.locator('#setupQmtAutoLogin').uncheck()
    page.locator('#setupMode').select_option(mode)
    if mode == 'lttx':
        page.locator('#setupQmtTradeDir').fill(directory + 'Trade')
    submit = page.locator('#setupForm [type="submit"]')
    submit.click()
    overlay = page.locator('#bindingQmtProcessOverlay')
    if action == "check_error":
        expect(page.locator('#setupStatus')).to_contain_text('process check failed')
        expect(submit).to_be_enabled()
        assert saved == []
    elif action != "stopped":
        expect(overlay).to_be_visible()
        expect(page.locator('#bindingQmtProcessPromptStatus')).to_contain_text('123')
        expect(submit).to_be_disabled()
        page.evaluate('submitSetupForm()')
        assert saved == []
        if action == "cancel":
            page.locator('#bindingQmtProcessCancelBtn').click()
            expect(overlay).not_to_be_visible()
            expect(submit).to_be_enabled()
            assert saved == [] and stopped == []
        elif action == "manual":
            page.locator('#bindingQmtProcessRecheckBtn').click()
            expect(page.locator('#bindingQmtProcessPromptStatus')).to_contain_text('仍在运行')
            running[0] = False
            page.locator('#bindingQmtProcessRecheckBtn').click()
        else:
            page.locator('#bindingQmtProcessStopContinueBtn').click()
            if action == "stop_error":
                expect(page.locator('#bindingQmtProcessPromptStatus')).to_contain_text('stop failed')
                expect(overlay).to_be_visible()
                assert saved == []
                page.locator('#bindingQmtProcessCancelBtn').click()
                expect(submit).to_be_enabled()
    if action in ("stop", "manual", "stopped"):
        expect(page.locator('#setupOverlay')).not_to_be_visible()
        expect(submit).to_be_enabled()
        assert len(saved) == 1 and saved[0]['mode'] == mode
        assert saved[0]['qmt_strategy']['enabled'] is True
        assert len(started) == (1 if action == 'stop' else 0)
    expected = {directory + '/bin.x64'}
    if mode == 'lttx':
        expected.add(directory + 'Trade/bin.x64')
    assert {path.replace('\\', '/') for path in checked} == expected
    assert errors == []
