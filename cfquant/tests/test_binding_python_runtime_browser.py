"""Binding executor selection and download lifecycle, using offline APIs."""
from urllib.parse import parse_qs, urlparse

import pytest

from cfquant.tests.test_tutorial_reader import browser, page, frontend_url, expect
from cfquant.tests.test_binding_runtime_browser import open_bindings


def runtime_status(*, supported=True, configured="py36", py312_installed=False, config_exists=True):
    runtimes = {"py36": {"installed": config_exists}, "py312": {"installed": py312_installed}}
    return {"binding": {
        "qmt_version": "2.1.33.0" if supported else "2.1.19.0",
        "py312_supported": supported,
        "available_runtimes": ["py36", "py312"] if supported else ["py36"],
        "runtime_selection": "selectable" if supported else "fixed_py36",
        "selected_runtime": configured, "configured_runtime": configured,
        "config_exists": config_exists, "runtimes": runtimes,
        "state": "ready" if config_exists and runtimes[configured]["installed"] else "account_config_missing",
    }}


def open_runtime(page, frontend_url, status):
    _, errors = open_bindings(page, frontend_url)
    page.route("**/api/qmt/python-runtime?*", lambda route: route.fulfill(json={"ok": True, "data": status}))
    page.evaluate("openBindingDialog({accountId: 'TEST_ONLY', qmtDir: 'D:/QMT'})")
    page.wait_for_function("state.bindingPythonRuntime && !state.bindingPythonRuntimeChecking")
    return errors


def test_old_version_has_only_py36_and_no_unnecessary_download(page, frontend_url):
    errors = open_runtime(page, frontend_url, runtime_status(supported=False))
    select = page.locator("#bindingPythonRuntimeSelect")
    expect(select.locator("option")).to_have_text(["Python 3.6"])
    expect(select).to_be_disabled()
    expect(page.locator("#bindingPythonRuntimeStatus")).to_contain_text("已安装并配置")
    expect(page.locator("#bindingPythonRuntimeDownloadBtn")).to_be_disabled()
    assert not errors


@pytest.mark.parametrize("already_installed", [False, True], ids=["download", "reuse"])
def test_selected_executor_is_applied_through_existing_job_until_restart_finishes(page, frontend_url, already_installed):
    status = runtime_status(py312_installed=already_installed)
    errors = open_runtime(page, frontend_url, status)
    select = page.locator("#bindingPythonRuntimeSelect")
    expect(select.locator("option")).to_have_text(["Python 3.6", "Python 3.12"])
    expect(select).to_have_value("py36")
    submitted = []
    page.route("**/api/qmt/python-runtime/download", lambda route: (
        submitted.append(route.request.post_data_json),
        route.fulfill(json={"ok": True, "data": {"state": "queued"}})))
    page.route("**/api/qmt/python-runtime/jobs?*", lambda route: route.fulfill(json={"ok": True, "data": {"state": "running"}}))
    select.select_option("py312")
    button = page.locator("#bindingPythonRuntimeDownloadBtn")
    expect(button).to_contain_text("切换到" if already_installed else "下载并使用")
    assert not submitted  # Choosing a value alone has no lifecycle side effects.
    page.evaluate("submitBindingForm({preventDefault() {}, currentTarget: document.querySelector('#bindingForm')})")
    expect(page.locator("#bindingSaveStatus")).to_contain_text("尚未应用")
    button.click()
    page.wait_for_function("!!state.bindingPythonRuntimeJobId")
    page.evaluate("clearBindingPythonRuntimePoll()")
    assert submitted[0]["runtime"] == "py312"
    assert submitted[0]["reuse_installed"] is True
    assert submitted[0]["restart"] is True
    expect(select).to_be_disabled()
    page.locator("#closeBindingDialogBtn").click()
    page.evaluate("openBindingDialog({accountId: 'TEST_ONLY', qmtDir: 'D:/QMT'})")
    page.wait_for_function("state.bindingPythonRuntime && !state.bindingPythonRuntimeChecking")
    expect(select).to_have_value("py312")
    expect(select).to_be_disabled()
    page.evaluate("""bindingPythonRuntimeProgressEvent({
        meta: {job_id: state.bindingPythonRuntimeJobId, stage: 'downloading'},
        data: {phase: 'downloading', bytes_done: 50, bytes_total: 100, percent: 50}
    })""")
    expect(page.locator("#bindingPythonRuntimeProgressMeta")).to_contain_text("50%")
    page.evaluate("""bindingPythonRuntimeProgressEvent({
        meta: {job_id: state.bindingPythonRuntimeJobId, stage: 'installed'},
        data: {phase: 'installed', percent: 100}
    })""")
    assert page.evaluate("!!state.bindingPythonRuntimeJobId")
    expect(button).to_be_disabled()
    assert not page.locator("#bindingPythonRuntimeProgressBar").evaluate("node => node.classList.contains('is-done')")
    expect(page.locator("#bindingPythonRuntimeProgressMeta")).to_contain_text("等待切换")
    for phase in ("extract", "activating", "restarting"):
        page.evaluate("""phase => bindingPythonRuntimeProgressEvent({
            meta: {job_id: state.bindingPythonRuntimeJobId, stage: phase},
            data: {phase, percent: 0, eta: null}
        })""", phase)
        expect(page.locator("#bindingPythonRuntimeProgressMeta")).not_to_contain_text("0%")
        expect(page.locator("#bindingPythonRuntimeProgressMeta")).not_to_contain_text("剩余约 0")
        assert page.locator("#bindingPythonRuntimeProgressBar").evaluate("node => node.getBoundingClientRect().width > 0")
        assert page.evaluate("!!state.bindingPythonRuntimeJobId")
    status["binding"].update(selected_runtime="py312", configured_runtime="py312", state="ready")
    status["binding"]["runtimes"]["py312"]["installed"] = True
    page.evaluate("""bindingPythonRuntimeProgressEvent({
        meta: {job_id: state.bindingPythonRuntimeJobId, stage: 'done'}, data: {phase: 'done'}
    })""")
    expect(button).to_have_text("Python 3.12 已就绪")
    assert not page.evaluate("state.bindingPythonRuntimeChoiceDirty")
    page.locator("#closeBindingDialogBtn").click()
    page.evaluate("openBindingDialog({accountId: 'TEST_ONLY', qmtDir: 'D:/QMT'})")
    expect(select).to_have_value("py312")
    assert page.locator("#bindingPythonRuntimePanel").evaluate("node => node.scrollWidth <= node.clientWidth")
    assert not errors


def test_lost_job_record_releases_busy_state_without_claiming_success(page, frontend_url):
    errors = open_runtime(page, frontend_url, runtime_status(config_exists=False))
    page.route("**/api/qmt/python-runtime/download", lambda route: route.fulfill(json={"ok": True, "data": {"state": "queued"}}))
    page.route("**/api/qmt/python-runtime/jobs?*", lambda route: route.fulfill(status=404, json={"ok": False, "error": "job not found"}))
    page.locator("#bindingPythonRuntimeDownloadBtn").click()
    page.wait_for_function("!state.bindingPythonRuntimeJobId && state.bindingPythonRuntimeProgress?.meta?.stage === 'error'")
    expect(page.locator("#bindingPythonRuntimeProgressText")).to_contain_text("记录已失效")
    expect(page.locator("#bindingPythonRuntimeDownloadBtn")).to_be_enabled()
    assert not errors


def test_save_rechecks_completed_runtime_job_even_without_progress_notification(page, frontend_url):
    errors = open_runtime(page, frontend_url, runtime_status(config_exists=False))
    page.route("**/api/qmt/python-runtime/jobs?*", lambda route: route.fulfill(json={
        "ok": True, "data": {"state": "done", "result": {"account_config_required": True}}}))
    saved = []
    def save(route):
        body = route.request.post_data_json
        saved.append(body)
        row = dict(body, account_key="TEST_ONLY|STOCK|test", bridge_id="test")
        route.fulfill(json={"ok": True, "data": {
            "account": row, "account_configs": {row["account_key"]: row}, "account_pairs": {},
            "bridges": {"test": {"name": "Test"}}, "qmt_strategy_deploy": {"enabled": False},
            "qmt_auto_login": {"enabled": False}}})
    page.route("**/api/account-config", save)
    page.locator("#bindingQmtAutoLogin").uncheck()
    page.evaluate("""() => {
        fillQmtStrategySettings('binding', {enabled: false});
        state.bindingPythonRuntimeJobId = 'missed-done';
        state.bindingPythonRuntimeJobContext = bindingPythonRuntimeContextKey();
        state.bindingPythonRuntimeJobRuntime = 'py36';
    }""")
    page.locator('#bindingForm [type="submit"]').click()
    expect(page.locator("#bindingDialogOverlay")).not_to_be_visible()
    assert len(saved) == 1
    assert not page.evaluate("state.bindingPythonRuntimeJobId")
    assert not errors


def test_directory_change_invalidates_options_and_discards_late_response(page, frontend_url):
    errors = open_runtime(page, frontend_url, runtime_status())
    pending = []
    page.route("**/api/qmt/python-runtime?*", lambda route: pending.append(route))
    page.locator("#bindingPythonRuntimeRefreshBtn").click()
    page.wait_for_function("state.bindingPythonRuntimeChecking")
    page.locator("#bindingQmtDir").fill("D:/OLD_QMT")
    expect(page.locator("#bindingPythonRuntimeSelect option")).to_have_text(["Python 3.6"])
    expect(page.locator("#bindingPythonRuntimeDownloadBtn")).to_be_disabled()
    page.wait_for_timeout(450)
    assert len(pending) == 2
    assert "OLD_QMT" in parse_qs(urlparse(pending[1].request.url).query)["qmt_dir"][0]
    pending[1].fulfill(json={"ok": True, "data": runtime_status(supported=False)})
    page.wait_for_function("!state.bindingPythonRuntimeChecking")
    pending[0].fulfill(json={"ok": True, "data": runtime_status()})
    expect(page.locator("#bindingPythonRuntimeSelect option")).to_have_text(["Python 3.6"])
    assert not page.evaluate("state.bindingPythonRuntime.binding.py312_supported")
    assert not errors


def test_missing_account_config_shows_capabilities_but_requires_login(page, frontend_url):
    errors = open_runtime(page, frontend_url, runtime_status(config_exists=False))
    expect(page.locator("#bindingPythonRuntimeSelect option")).to_have_count(2)
    page.locator("#bindingPythonRuntimeSelect").select_option("py312")
    submitted = []
    page.route("**/api/qmt/python-runtime/download", lambda route: (
        submitted.append(route.request.post_data_json),
        route.fulfill(json={"ok": True, "data": {"state": "queued"}})))
    expect(page.locator("#bindingPythonRuntimeDownloadBtn")).to_be_enabled()
    expect(page.locator("#bindingPythonRuntimeChoiceHint")).to_contain_text("先下载")
    page.locator("#bindingPythonRuntimeDownloadBtn").click()
    page.wait_for_function("state.bindingPythonRuntimeJobId")
    assert submitted[0]["allow_missing_account_config"] is True
    assert not errors


@pytest.mark.parametrize("socket_throws", [False, True], ids=["socket-disconnected", "socket-unavailable"])
def test_poll_completion_before_first_login_unlocks_binding(page, frontend_url, socket_throws):
    status = runtime_status(config_exists=False)
    errors = open_runtime(page, frontend_url, status)
    submitted = []
    page.route("**/api/qmt/python-runtime/download", lambda route: (
        submitted.append(route.request.post_data_json),
        route.fulfill(json={"ok": True, "data": {"state": "queued"}})))
    # The last progress event is not a terminal event. HTTP state/result must
    # recover completion even if the WebSocket notification never arrived.
    page.route("**/api/qmt/python-runtime/jobs?*", lambda route: route.fulfill(json={
        "ok": True, "data": {"state": "done", "progress": {"phase": "installed", "percent": 100},
        "result": {"account_config_required": True, "restarted": None}}}))
    if socket_throws:
        page.evaluate("() => { window.WebSocket = function() { throw new Error('WebSocket unavailable'); }; }")
    page.locator("#bindingPythonRuntimeDownloadBtn").click()
    page.wait_for_function("state.bindingPythonRuntimeJobId === '' && state.bindingPythonRuntimeProgress?.meta?.stage === 'done'")
    assert len(submitted) == 1
    assert page.evaluate("state.bindingPythonRuntimeDeferred")
    assert not page.evaluate("state.bindingPythonRuntimeChoiceDirty")
    expect(page.locator("#bindingPythonRuntimeProgressMeta")).to_contain_text("100%")
    expect(page.locator("#bindingPythonRuntimeProgressText")).to_contain_text("登录")
    assert not errors


def test_fresh_py36_install_updates_open_dialog_without_account_login(page, frontend_url):
    status = runtime_status(supported=False, config_exists=False)
    errors = open_runtime(page, frontend_url, status)
    page.route("**/api/qmt/python-runtime/download", lambda route: route.fulfill(
        json={"ok": True, "data": {"state": "queued"}}))
    job = {"state": "running", "progress": {"phase": "extract"}}
    page.route("**/api/qmt/python-runtime/jobs?*", lambda route: route.fulfill(json={"ok": True, "data": job}))
    page.locator('#bindingPythonRuntimeDownloadBtn').click()
    expect(page.locator('#bindingPythonRuntimeProgressMeta')).to_contain_text('解压安装中')
    status['binding']['runtimes']['py36']['installed'] = True
    # Deliberately leave progress at extract: the terminal state is authoritative.
    job.update(state='done', result={'account_config_required': True, 'installed': {'installed': True}})
    expect(page.locator('#bindingPythonRuntimeProgressMeta')).to_contain_text('已完成，100%')
    expect(page.locator('#bindingPythonRuntimeStatus')).to_contain_text('已安装，登录后应用')
    expect(page.locator('#bindingPythonRuntimeChoiceHint')).to_contain_text('可以保存绑定')
    expect(page.locator('#bindingPythonRuntimeDownloadBtn')).to_have_text('已安装 Python 3.6，登录后应用')
    expect(page.locator('#bindingPythonRuntimeDownloadBtn')).to_be_disabled()
    assert not page.evaluate('state.bindingPythonRuntimeJobId')
    assert not errors


def test_manual_recheck_reconciles_completed_job(page, frontend_url):
    status = runtime_status(supported=False, config_exists=False)
    errors = open_runtime(page, frontend_url, status)
    page.evaluate("""() => {
        state.bindingPythonRuntimeJobId = 'stale-install';
        state.bindingPythonRuntimeJobContext = bindingPythonRuntimeContextKey();
        state.bindingPythonRuntimeJobRuntime = 'py36';
        renderBindingPythonRuntimeStatus();
    }""")
    status['binding']['runtimes']['py36']['installed'] = True
    page.route('**/api/qmt/python-runtime/jobs?*', lambda route: route.fulfill(json={
        'ok': True, 'data': {'state': 'done', 'result': {'account_config_required': True}}}))
    page.locator('#bindingPythonRuntimeRefreshBtn').click()
    expect(page.locator('#bindingPythonRuntimeDownloadBtn')).to_have_text('已安装 Python 3.6，登录后应用')
    assert not page.evaluate('state.bindingPythonRuntimeJobId')
    assert not errors
