"""Pure long-only cash-equity sizing. No connection or order is created here."""
from decimal import Decimal, ROUND_FLOOR

from .algo import positive


def instrument_rules(stock_code, min_volume=None, volume_step=None, price_tick=0.01):
    symbol, _, market = str(stock_code).upper().rpartition(".")
    stock = (len(symbol) == 6 and symbol.isdigit() and
             ((market == "SH" and symbol.startswith(("60", "68"))) or
              (market == "SZ" and symbol.startswith(("00", "30"))) or
              (market == "BJ" and symbol.startswith(("43", "83", "87", "88", "92")))))
    if not stock:
        raise ValueError("position sizing currently supports SH/SZ/BJ cash equities only")
    star = market == "SH" and symbol.startswith("68")
    minimum = positive(min_volume if min_volume is not None else (200 if star else 100), "min_volume", integer=True)
    step = positive(volume_step if volume_step is not None else (1 if star or market == "BJ" else 100), "volume_step", integer=True)
    if minimum % step:
        raise ValueError("min_volume must be a multiple of volume_step")
    return dict(min_volume=minimum, volume_step=step, price_tick=positive(price_tick, "price_tick"),
                source="explicit" if min_volume is not None or volume_step is not None else "cash_equity_defaults")


def calculate_position(*, stock_code, entry_price, method="risk_percent", stop_price=None,
                       total_asset=None, available_cash=None, risk_amount=None, risk_percent=None,
                       cash_amount=None, allocation_percent=None, allocation_base="total_asset",
                       target_weight=None, current_volume=0, pending_buy_volume=0,
                       max_position_percent=None, max_volume=None, reserved_cash=0,
                       commission_rate=0.0003, min_commission=5, sell_tax_rate=0.0005,
                       transfer_fee_rate=0.00001, slippage_per_share=0,
                       take_profit_price=None, min_volume=None, volume_step=None, price_tick=0.01):
    """Largest legal buy quantity satisfying cash, estimated stop risk and position caps.

    Percentages are fractions (0.02 = 2%). Fees are configurable estimates,
    including minimum commission on each side. Missing cash imposes no cash cap;
    server-side plans always supply a fresh account snapshot.
    """
    rules = instrument_rules(stock_code, min_volume, volume_step, price_tick)
    p = Decimal(str(positive(entry_price, "entry_price")))
    tick = Decimal(str(rules["price_tick"]))
    if p % tick:
        raise ValueError("entry_price must align with price_tick")
    stop = Decimal(str(positive(stop_price, "stop_price"))) if stop_price is not None else None
    if stop is not None and (stop >= p or stop % tick):
        raise ValueError("long stop_price must be below entry_price and align with price_tick")
    methods = ("risk_amount", "risk_percent", "cash_amount", "allocation_percent", "target_weight")
    if method not in methods:
        raise ValueError("unknown sizing method: " + str(method))
    def number(value, name, zero=True):
        return Decimal(str(positive(value, name, allow_zero=zero)))
    def fraction(value, name):
        value = number(value, name)
        if value > 1:
            raise ValueError(name + " must be a fraction between 0 and 1")
        return value
    equity = number(total_asset, "total_asset") if total_asset is not None else None
    cash = number(available_cash, "available_cash") if available_cash is not None else None
    reserved = number(reserved_cash, "reserved_cash")
    spendable = max(Decimal(0), cash - reserved) if cash is not None else None
    current = positive(current_volume, "current_volume", integer=True, allow_zero=True)
    pending = positive(pending_buy_volume, "pending_buy_volume", integer=True, allow_zero=True)
    commission = number(commission_rate, "commission_rate")
    minimum_fee = number(min_commission, "min_commission")
    tax = number(sell_tax_rate, "sell_tax_rate")
    transfer = number(transfer_fee_rate, "transfer_fee_rate")
    slip = number(slippage_per_share, "slippage_per_share")
    risk = budget = None
    if method in ("risk_amount", "risk_percent"):
        if stop is None:
            raise ValueError("risk sizing requires stop_price")
        if method == "risk_amount":
            risk = number(risk_amount, "risk_amount", False)
        else:
            if equity is None or equity <= 0:
                raise ValueError("risk_percent requires positive total_asset")
            risk = equity * fraction(risk_percent, "risk_percent")
        theoretical = risk / (p - stop)
    else:
        if method == "cash_amount":
            budget = number(cash_amount, "cash_amount", False)
        elif method == "allocation_percent":
            if allocation_base not in ("total_asset", "available_cash"):
                raise ValueError("allocation_base must be total_asset or available_cash")
            base = equity if allocation_base == "total_asset" else spendable
            if base is None:
                raise ValueError("allocation base is required")
            budget = base * fraction(allocation_percent, "allocation_percent")
        else:
            if equity is None or equity <= 0:
                raise ValueError("target_weight requires positive total_asset")
            budget = max(Decimal(0), equity * fraction(target_weight, "target_weight") - (current + pending) * p)
        theoretical = budget / p
    caps = {"sizing_budget": theoretical}
    if spendable is not None:
        caps["available_cash"] = spendable / p
    if max_position_percent is not None:
        if equity is None or equity <= 0:
            raise ValueError("max_position_percent requires positive total_asset")
        caps["position_cap"] = max(Decimal(0), equity * fraction(max_position_percent, "max_position_percent") / p - current - pending)
    if max_volume is not None:
        caps["max_volume"] = Decimal(positive(max_volume, "max_volume", integer=True, allow_zero=True))
    def costs(q):
        if not q:
            return Decimal(0), Decimal(0), Decimal(0), Decimal(0)
        buy = q * p
        entry_fee = max(minimum_fee, buy * commission) + buy * transfer
        exit_value = q * stop if stop is not None else Decimal(0)
        exit_fee = max(minimum_fee, exit_value * commission) + exit_value * (tax + transfer) if stop is not None else Decimal(0)
        loss = q * (p - stop + slip) + entry_fee + exit_fee if stop is not None else Decimal(0)
        return buy + entry_fee, loss, entry_fee, exit_fee
    def failures(q):
        cash_used, loss, _, _ = costs(q)
        reasons = [name for name, cap in caps.items() if q > cap]
        if spendable is not None and cash_used > spendable:
            reasons.append("available_cash")
        if budget is not None and cash_used > budget:
            reasons.append("sizing_budget")
        if risk is not None and loss > risk:
            reasons.append("stop_risk_budget")
        return sorted(set(reasons))
    step = rules["volume_step"]
    low, high = 0, int((min(caps.values()) / step).to_integral_value(rounding=ROUND_FLOOR))
    while low < high:
        mid = (low + high + 1) // 2
        if failures(mid * step):
            high = mid - 1
        else:
            low = mid
    quantity = low * step
    if quantity < rules["min_volume"]:
        quantity = 0
    used, loss, entry_fee, exit_fee = costs(quantity)
    reasons = failures(quantity + step if quantity else rules["min_volume"])
    if not quantity:
        reasons.append("below_minimum_order")
    profit = ratio = None
    if take_profit_price is not None:
        tp = number(take_profit_price, "take_profit_price", False)
        if tp <= p or tp % tick:
            raise ValueError("take_profit_price must exceed entry_price and align with price_tick")
        exit_tp_fee = max(minimum_fee, quantity * tp * commission) + quantity * tp * (tax + transfer) if quantity else Decimal(0)
        profit = quantity * (tp - p - slip) - entry_fee - exit_tp_fee
        ratio = profit / loss if loss else None
    return dict(stock_code=stock_code, method=method, quantity=quantity, theoretical_quantity=float(theoretical),
                entry_price=float(p), stop_price=float(stop) if stop is not None else None,
                notional=float(quantity * p), cash_required=float(used),
                risk_budget=float(risk) if risk is not None else None,
                estimated_loss=float(loss) if stop is not None else None,
                risk_percent=float(loss / equity) if stop is not None and equity else None,
                position_percent=float((current + pending + quantity) * p / equity) if equity else None,
                entry_fee=float(entry_fee), exit_fee=float(exit_fee), slippage_amount=float(quantity * slip),
                estimated_profit=float(profit) if profit is not None else None,
                reward_risk_ratio=float(ratio) if ratio is not None else None,
                limiting_reasons=reasons, rules=rules,
                assumptions=dict(total_asset=float(equity) if equity is not None else None,
                                 available_cash=float(cash) if cash is not None else None,
                                 reserved_cash=float(reserved), current_volume=current, pending_buy_volume=pending,
                                 commission_rate=float(commission), min_commission=float(minimum_fee),
                                 sell_tax_rate=float(tax), transfer_fee_rate=float(transfer),
                                 slippage_per_share=float(slip)),
                risk_note="Estimated loss at the assumed stop fill; gaps, liquidity and T+1 can increase actual loss.")
