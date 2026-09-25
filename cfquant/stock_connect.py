"""QMT Stock Connect conventions (also embedded in standalone Python 3.6 entries).

Source: https://dict.thinktrader.net/innerApi/variable_convention.html
Orders use HGT/SGT; HK is a distinct quotation market, not an account route.
"""


CONNECT_ACCOUNT_MARKETS = {"HUGANGTONG": "HGT", "SHENGANGTONG": "SGT"}


def connect_account_type(value):
    text = str(value or "").strip().upper()
    return {
        "7": "HUGANGTONG", "HGT": "HUGANGTONG",
        "HUGANGTONG_ACCOUNT": "HUGANGTONG",
        "11": "SHENGANGTONG", "SGT": "SHENGANGTONG",
        "SHENGANGTONG_ACCOUNT": "SHENGANGTONG",
    }.get(text, text)


def normalize_connect_code(value):
    text = str(value or "").strip()
    if "." not in text:
        return text
    code, market = text.rsplit(".", 1)
    market = market.strip().upper()
    if market not in ("HK", "HGT", "SGT"):
        return text
    code = code.strip()
    if not code or len(code) > 5 or not all("0" <= c <= "9" for c in code) or int(code) == 0:
        raise ValueError("HK/HGT/SGT stock code must contain 1 to 5 digits and be positive")
    return "%s.%s" % (code.zfill(5), market)


def validate_connect_market(account_type, stock_code="", market=""):
    account_type = connect_account_type(account_type)
    code = normalize_connect_code(stock_code)
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    market = str(market or "").strip().upper()
    if market and suffix and market != suffix and (market in ("HGT", "SGT") or suffix in ("HGT", "SGT")):
        raise ValueError("Stock Connect market does not match stock_code")
    target = market or suffix
    expected = CONNECT_ACCOUNT_MARKETS.get(account_type)
    if expected and target and target != expected:
        raise ValueError("%s requires .%s securities" % (account_type, expected))
    if target in ("HGT", "SGT") and target != expected:
        raise ValueError(".%s requires its matching HUGANGTONG/SHENGANGTONG account" % target)
    return code


def query_connect_exchange_rate(bridge, params):
    account = params.get("account") or {}
    account_id = str(account.get("account_id") or "").strip()
    kind = connect_account_type(account.get("account_type"))
    if not account_id or kind not in CONNECT_ACCOUNT_MARKETS:
        raise ValueError("get_hkt_exchange_rate requires a HUGANGTONG/SHENGANGTONG account")
    getter = getattr(bridge, "_get_callable", None) or bridge._get_global_func
    func = getter("get_hkt_exchange_rate")
    if not func:
        raise NotImplementedError("This QMT does not expose get_hkt_exchange_rate")
    return func(account_id, kind)


def validate_connect_order(params, account_type):
    code = validate_connect_market(account_type, params.get("stock_code", params.get("code", "")))
    expected = CONNECT_ACCOUNT_MARKETS.get(connect_account_type(account_type))
    if expected and not code.endswith("." + expected):
        raise ValueError("Stock Connect orders require an explicit .%s suffix" % expected)
    if expected:
        operation = next((params[name] for name in ("qmt_optype", "passorder_optype", "optype", "order_type")
                          if params.get(name) is not None), None)
        if operation is not None and str(operation).lower() not in ("23", "24", "buy", "sell", "stock_buy", "stock_sell"):
            raise ValueError("Stock Connect order_stock supports STOCK_BUY/SELL (23/24)")
        if any(params.get(name) for name in ("credit_action", "credit_business", "future_action",
                                            "future_business", "option_action", "option_business",
                                            "stock_option_action", "future_option_action", "derivative_action")):
            raise ValueError("Stock Connect does not support credit or derivative actions")
    if code.upper().endswith(".HK"):
        raise ValueError("Use .HGT/.SGT and the matching account for Stock Connect orders; .HK is quotation only")
    return code
