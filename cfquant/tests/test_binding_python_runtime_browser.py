"""Binding executor selection and download lifecycle, using offline APIs."""
from urllib.parse import parse_qs, urlparse

import pytest

from cfquant.tests.test_tutorial_reader import browser, page, frontend_url, expect
from cfquant.tests.test_binding_runtime_browser import open_bindings


def runtime_status(*, supported=True, configured="py36", py312_installed=False, config_exists=True):
    runtimes = {"py36": {"installed": True}, "py312": {"installed": py312_installed}}
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
