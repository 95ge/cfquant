"""Verify quote request forms with mocked APIs on desktop and mobile."""
from cfquant.tests.test_tutorial_reader import browser, frontend_url, open_app, page


def test_whole_quote_form_preserves_arbitrary_markets_and_symbol_case(page, frontend_url, tmp_path):
    _, errors = open_app(page, frontend_url)
    page.evaluate("""() => {
        document.querySelector('#setupOverlay').classList.add('hidden');
        setView('api');
        renderApiDocs('quote_subscribe_whole');
    }""")
    result = page.evaluate("""() => {
        const input = document.querySelector('#apiForm [name="markets"]');
        input.value = 'SH,SZ,BJ,rb2610.SF\uFF0CCUSTOM';
        const mixed = currentApiRequest();
        input.value = '';
        const empty = currentApiRequest();
        input.value = 'SH,SZ,BJ,rb2610.SF,CUSTOM';
        return { mixed, empty };
    }""")
    assert result["mixed"]["body"]["markets"] == ["SH", "SZ", "BJ", "rb2610.SF", "CUSTOM"]
    assert result["empty"]["body"]["markets"] == []
    field = page.locator('#apiForm [name="markets"]')
    assert field.is_visible()
    assert page.locator('#apiDocDetail').evaluate("""node =>
        node.scrollWidth <= node.clientWidth + 1 &&
        Array.from(node.querySelectorAll('td')).every(cell => cell.scrollWidth <= cell.clientWidth + 1)
    """)
    field.scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / "whole-quote-form.png"))
    assert errors == []
