"""Offline browser verification of Stock Connect binding and order confirmation."""
from cfquant.tests.test_tutorial_reader import browser, frontend_url, open_app, page


def test_connect_account_options_and_confirmation(page, frontend_url):
    _, errors = open_app(page, frontend_url)
    result = page.evaluate("""() => {
        const options = [...document.querySelectorAll('select[name="account_type"]')]
            .map(select => [...select.options].map(option => option.value));
        const code = normalizeStockCode('700.hgt');
        state.accountType = 'HUGANGTONG';
        const confirmation = buildOrderConfirmation({side: {value: 'buy'},
            stock_code: {value: '700.hgt'}, volume: {value: '100'},
            price: {value: '350'}, price_type: {value: '11'}});
        return {options, code, confirmation, deep: normalizeStockCode('941.sgt'),
                kind: normalizeAccountType('11')};
    }""")
    assert result['options']
    assert all('HUGANGTONG' in values and 'SHENGANGTONG' in values for values in result['options'])
    assert result['code'] == '00700.HGT'
    assert result['deep'] == '00941.SGT'
    assert result['kind'] == 'SHENGANGTONG'
    assert '00700.HGT' in result['confirmation']
    assert errors == []
