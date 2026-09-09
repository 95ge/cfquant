"""Offline browser regressions; requires playwright and its Chromium install."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect
FRONTEND = Path(__file__).resolve().parents[2] / "web_dashboard"


class StaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def frontend_url():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(StaticHandler, directory=str(FRONTEND))
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%s" % server.server_port
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(params=[1440, 390], ids=["desktop", "mobile"])
def page(browser, request):
    context = browser.new_context(viewport={"width": request.param, "height": 900})
    page = context.new_page()
    page.set_default_timeout(10000)
    yield page
    context.close()


def open_app(page, frontend_url, setup_required=True):
    requests = []
    errors = []

    def respond(route):
        path = urlparse(route.request.url).path
        requests.append((route.request.method, path))
        data = {}
        if path == "/api/config":
            data = {
                "setup": {"setup_required": setup_required},
                "account_configs": {},
                "server_access": {"web_auth_enabled": False},
            }
        route.fulfill(json={"ok": True, "data": data})

    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/api/**", respond)
    page.goto(frontend_url)
    expect(page.locator("#setupOverlay" if setup_required else "#onboardingWizard")).to_be_visible()
    return requests, errors


def assert_reader_layout(page):
    measurements = page.locator("#tutorialReader").evaluate("""reader => ({
        width: reader.clientWidth,
        scrollWidth: reader.scrollWidth,
        bodyWidth: document.querySelector('#tutorialReaderBody').clientWidth,
        bodyScrollWidth: document.querySelector('#tutorialReaderBody').scrollWidth,
        focusedInside: reader.contains(document.activeElement)
    })""")
    assert measurements["scrollWidth"] <= measurements["width"]
    assert measurements["bodyScrollWidth"] <= measurements["bodyWidth"]
    assert measurements["focusedInside"]


def test_first_setup_can_read_without_saving_and_preserves_draft(page, frontend_url, tmp_path):
    requests, errors = open_app(page, frontend_url)
    opener = page.locator("#setupOverlay [data-open-tutorial]")
    expect(page.locator("#setupAccountId")).to_have_value("")
    expect(page.locator("#setupQmtDir")).to_have_value("")
    page.screenshot(path=str(tmp_path / "setup.png"))
    opener.click()
    expect(page.locator("#tutorialReader")).to_be_visible()
    assert page.evaluate("state.setup.setup_required && !state.appStarted")
    page.locator('#tutorialReader [data-guide="python"]').click()
    expect(page.locator("#python-prepare")).to_be_visible()
    expect(page.locator('#tutorialReader pre[data-language="python"]')).to_have_count(15)
    page.screenshot(path=str(tmp_path / "tutorial-start.png"))
    page.locator('#tutorialReader a[href="#python-order"]').click()
    top = page.locator("#python-order").evaluate("node => node.getBoundingClientRect().top")
    content_top = page.locator("#tutorialReader .tutorial-content").evaluate("node => node.getBoundingClientRect().top")
    assert top >= content_top
    assert_reader_layout(page)
    page.screenshot(path=str(tmp_path / "tutorial-reader.png"))
    page.keyboard.press("Escape")
    expect(page.locator("#tutorialReader")).not_to_be_visible()
    expect(opener).to_be_focused()

    draft = {
        "setupAdminUsername": "draft-admin",
        "setupAdminPassword": "draft-password",
        "setupAdminPasswordConfirm": "draft-password",
        "setupAccountId": "DRAFT_ACCOUNT",
        "setupQmtDir": r"D:\QMT-DRAFT",
    }
    for field, value in draft.items():
        page.locator("#" + field).fill(value)
    page.locator("#setupAccountType").select_option("CREDIT")
    page.locator("#setupMode").select_option("lttx")
    draft["setupQmtTradeDir"] = r"D:\QMT-TRADE-DRAFT"
    page.locator("#setupQmtTradeDir").fill(draft["setupQmtTradeDir"])
    opener.click()
    page.locator('[data-python-back]').click()
    page.locator('#tutorialReader [data-guide="quickstart"]').click()
    page.locator("#closeTutorialReaderBtn").click()
    for field, value in draft.items():
        expect(page.locator("#" + field)).to_have_value(value)
    expect(page.locator("#setupAccountType")).to_have_value("CREDIT")
    expect(page.locator("#setupMode")).to_have_value("lttx")
    expect(page.locator(".view-tutorial > .tutorial-layout")).to_have_count(1)
    assert all(method == "GET" for method, path in requests)
    assert errors == []


def test_deployment_images_and_navigation_work_before_setup(page, frontend_url):
    requests, errors = open_app(page, frontend_url)
    page.locator("#setupOverlay [data-open-tutorial]").click()
    page.locator('#tutorialReader [data-guide="deploy"]').click()
    for mode in ("lite", "advanced", "ctypes"):
        page.locator('#tutorialReader [data-deploy-mode="%s"]' % mode).click()
        expect(page.locator('[data-deploy-mode-panel="%s"]' % mode)).to_be_visible()
    screenshot = page.locator("#deployModePanelCtypes .guide-image-card img").first
    expect(screenshot).to_be_visible()
    screenshot.click()
    expect(page.locator("#tutorialReader #imageLightbox.open")).to_be_visible()
    assert page.locator("#imageLightboxImg").evaluate("img => img.complete && img.naturalWidth > 0")
    page.keyboard.press("Escape")
    expect(page.locator("#imageLightbox")).not_to_be_visible()
    expect(page.locator("#tutorialReader")).to_be_visible()
    page.locator('#tutorialReader [data-guide="onboarding"]').click()
    expect(page.locator("#tutorialReader")).not_to_be_visible()
    expect(page.locator("#setupOverlay")).to_be_visible()
    assert page.locator("#imageLightbox").evaluate("node => node.parentElement === document.body")
    assert all(method == "GET" for method, path in requests)
    assert errors == []


def test_onboarding_draft_and_locked_bridge_flow_survive_reading(page, frontend_url):
    requests, errors = open_app(page, frontend_url, setup_required=False)
    page.locator("#onboardingStartConfigBtn").click()
    page.locator("#onboardingAccountId").fill("DRAFT_ACCOUNT")
    page.locator("#onboardingAccountType").select_option("CREDIT")
    page.locator("#onboardingMode").select_option("lttx")
    page.locator("#onboardingQmtDir").fill(r"D:\DRAFT-QMT")
    page.locator("#onboardingQmtTradeDir").fill(r"D:\DRAFT-TRADE")
    page.locator("#onboardingDataProvider").uncheck()
    snapshot = page.evaluate("({values: onboardingValues(), step: state.onboardingStep, done: [...state.onboardingDoneSteps]})")
    opener = page.locator("#onboardingWizard [data-open-tutorial]")
    opener.click()
    page.locator('#tutorialReader [data-guide="python"]').click()
    page.locator("#closeTutorialReaderBtn").click()
    assert page.evaluate("({values: onboardingValues(), step: state.onboardingStep, done: [...state.onboardingDoneSteps]})") == snapshot
    expect(page.locator("#onboardingWizard")).to_be_visible()

    page.evaluate("beginOnboardingRestartFlow(onboardingValues(), {context: 'onboarding', returnTarget: 'deploy'})")
    page.locator("#onboardingRefreshBridgeBtn").click()
    page.wait_for_function("state.onboardingBridgeCheckInFlight")
    token = page.evaluate("state.onboardingBridgeCheckToken")
    opener.click()
    page.locator('[data-python-back]').click()
    page.locator('#tutorialReader [data-guide="troubleshooting"]').click()
    assert_reader_layout(page)
    page.keyboard.press("Escape")
    expect(page.locator("#onboardingWizard")).to_be_visible()
    assert page.evaluate("state.onboardingBindingFlowActive && state.onboardingBridgeCheckInFlight")
    assert page.evaluate("state.onboardingBridgeCheckToken") == token
    assert page.evaluate("state.onboardingStep") == "bridge"
    expect(page.locator("#closeOnboardingBtn")).to_be_disabled()
    page.keyboard.press("Escape")
    expect(page.locator("#onboardingWizard")).to_be_visible()
    assert not any(path == "/api/setup/initialize" or path == "/api/order" for method, path in requests)
    assert errors == []


def python_directory(page):
    menu = page.locator('[data-python-menu]')
    if menu.is_visible() and menu.get_attribute('aria-expanded') != 'true':
        menu.click()


def test_python_api_search_status_examples_and_deep_links(page, frontend_url, tmp_path):
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => { window.copiedText = text; }}})")
    requests, errors = open_app(page, frontend_url)
    remote_requests = []
    page.route('https://dict.thinktrader.net/**', lambda route: (remote_requests.append(route.request.url), route.fulfill(body='<html><body>Official reference fixture</body></html>', content_type='text/html')))
    page.locator('#setupOverlay [data-open-tutorial]').click()
    page.locator('#tutorialReader [data-guide="python"]').click()
    python_directory(page)
    page.locator('#pythonApiSearch').fill('get_financial_data')
    expect(page.locator('.python-api-nav [data-python-entry^="xtdata."]')).to_have_count(1)
    page.locator('.python-api-nav [data-python-entry="xtdata.get_financial_data"]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('get_financial_data')
    expect(page.locator('.python-solution .python-status')).to_have_text('部分适配')
    expect(page.locator('.python-solution')).to_contain_text('field_list')
    assert_reader_layout(page)
    pane = page.locator('.python-reading-pane')
    assert pane.evaluate('node => node.scrollWidth <= node.clientWidth')
    page.screenshot(path=str(tmp_path / 'python-api-reference.png'))
    page.locator('.python-solution [data-python-copy]').last.click()
    assert 'field_list=["ASHAREBALANCESHEET.fix_assets"]' in page.evaluate('window.copiedText')
    assert not remote_requests
    page.locator('.python-original summary').click()
    expect(page.frame_locator('.python-original iframe').locator('body')).to_contain_text('Official reference fixture')
    assert len(remote_requests) == 1
    assert remote_requests[0].startswith('https://dict.thinktrader.net/nativeApi/xtdata.html')
    page.locator('.python-original summary').click()
    page.locator('[data-python-link]').click()
    deep_link = page.evaluate('window.copiedText')
    assert deep_link.endswith('#python-api=xtdata.get_financial_data')

    python_directory(page)
    page.locator('#pythonApiSearch').fill('generate_index_data')
    page.locator('#pythonApiFilter').select_option('unavailable')
    page.locator('.python-api-nav [data-python-entry="xtdata.generate_index_data"]').click()
    expect(page.locator('.python-solution')).to_contain_text('尚未支持')
    expect(page.locator('.python-solution pre')).to_have_count(0)
    page.screenshot(path=str(tmp_path / 'python-api-unsupported.png'))
    page.go_back()
    expect(page.locator('.python-document-head h2')).to_have_text('get_financial_data')

    python_directory(page)
    page.locator('#pythonApiSearch').fill('no_such_interface_123')
    expect(page.locator('[data-python-reset]')).to_be_visible()
    page.locator('[data-python-reset]').click()
    expect(page.locator('#pythonApiSearch')).to_have_value('')
    page.locator('.python-api-nav [data-python-entry="xtdata.subscribe_formula"]').click()
    expect(page.locator('.python-solution .python-status')).to_contain_text('条件待验证')
    expect(page.locator('.python-solution pre')).to_have_count(0)
    page.goto(deep_link)
    page.reload()
    page.locator('#setupOverlay [data-open-tutorial]').click()
    expect(page.locator('.python-document-head h2')).to_have_text('get_financial_data')
    assert all(method == 'GET' for method, path in requests)
    assert errors == []


def test_every_python_reference_entry_renders_without_live_backend(page, frontend_url):
    requests, errors = open_app(page, frontend_url)
    page.locator('#setupOverlay [data-open-tutorial]').click()
    page.locator('#tutorialReader [data-guide="python"]').click()
    failures = page.evaluate("""() => {
        const failures = [];
        for (const entry of [...CFQUANT_PYTHON_API.entries, ...CFQUANT_PYTHON_API.references]) {
            const button = [...document.querySelectorAll('.python-api-nav [data-python-entry]')].find(node => node.dataset.pythonEntry === entry.id);
            if (!button) { failures.push(entry.id + ': missing navigation'); continue; }
            button.click();
            if (document.querySelector('.python-document-head h2').textContent !== entry.name) failures.push(entry.id + ': missing document');
            if (entry.example && !document.querySelector('.python-solution pre').textContent) failures.push(entry.id + ': missing solution');
            const pane = document.querySelector('.python-reading-pane');
            if (pane.scrollWidth > pane.clientWidth) failures.push(entry.id + ': horizontal overflow');
        }
        return failures;
    }""")
    assert failures == []
    page.locator('[data-python-back]').click()
    expect(page.locator('#tutorialReader [data-guide="python"]')).to_be_visible()
    page.locator('#closeTutorialReaderBtn').click()
    assert all(method == 'GET' for method, path in requests)
    assert errors == []
