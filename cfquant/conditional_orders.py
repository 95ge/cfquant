"""Validated, serializable conditions evaluated against observed quote prices."""
import copy
import math

from .algo import positive
from .algo_broker import execution_time


def validate_conditions(conditions, reference_price=None):
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 32:
        raise ValueError("conditions must contain 1 to 32 rules (any matching rule triggers the group)")
    reference = positive(reference_price, "reference_price") if reference_price is not None else None
    result = []
    fields = {
        "stop_loss": {"price", "percent"}, "take_profit": {"price", "percent"},
        "time_exit": {"at", "only_if_loss"}, "holding_exit": {"seconds", "trading_days", "opened_at", "exit_time"},
        "trailing_stop": {"drawdown_percent", "drawdown_amount", "activation_price", "activation_percent"},
        "breakeven_stop": {"activation_percent", "activation_price", "offset_percent", "offset_amount", "protect_price"},
        "step_stop": {"steps"},
    }
    for index, original in enumerate(conditions):
        if not isinstance(original, dict):
            raise ValueError("each condition must be an object")
        rule = copy.deepcopy(original)
        kind = rule.get("type")
        if kind not in fields or set(rule) - (fields.get(kind, set()) | {"type", "name"}):
            raise ValueError("unknown condition type or fields")
        rule.setdefault("name", "%s_%d" % (kind, index + 1))
        if not isinstance(rule["name"], str) or not rule["name"]:
            raise ValueError("condition name must be nonempty text")
        if kind in ("stop_loss", "take_profit"):
            if ("price" in rule) == ("percent" in rule):
                raise ValueError(kind + " requires exactly one of price or percent")
            if "percent" in rule:
                pct = positive(rule["percent"], "percent")
                if reference is None or (kind == "stop_loss" and pct >= 1):
                    raise ValueError("percentage conditions require reference_price; stop percent must be below 1")
                rule["price"] = reference * (1 + pct if kind == "take_profit" else 1 - pct)
            rule["price"] = positive(rule["price"], "condition price")
        elif kind == "time_exit":
            rule["at"] = execution_time(rule.get("at"))
            if rule["at"] is None:
                raise ValueError("time_exit requires at")
            if not isinstance(rule.get("only_if_loss", False), bool):
                raise ValueError("only_if_loss must be boolean")
            if rule.get("only_if_loss") and reference is None:
                raise ValueError("only_if_loss requires reference_price")
        elif kind == "holding_exit":
            if ("seconds" in rule) == ("trading_days" in rule):
                raise ValueError("holding_exit requires exactly one of seconds or trading_days")
            rule["opened_at"] = execution_time(rule.get("opened_at"))
            if rule["opened_at"] is None:
                raise ValueError("holding_exit requires opened_at")
            if "seconds" in rule:
                rule["at"] = rule["opened_at"] + positive(rule["seconds"], "seconds")
            else:
                rule["trading_days"] = positive(rule["trading_days"], "trading_days", integer=True)
                if rule["trading_days"] > 2500:
                    raise ValueError("trading_days must not exceed 2500")
                import datetime
                datetime.time.fromisoformat(rule.setdefault("exit_time", "14:50"))
        elif kind in ("trailing_stop", "breakeven_stop"):
            if "activation_price" in rule and "activation_percent" in rule:
                raise ValueError("use one activation threshold")
            if "activation_percent" in rule:
                if reference is None:
                    raise ValueError("activation_percent requires reference_price")
                rule["activation_price"] = reference * (1 + positive(rule["activation_percent"], "activation_percent", allow_zero=True))
            if "activation_price" in rule:
                rule["activation_price"] = positive(rule["activation_price"], "activation_price")
            if kind == "trailing_stop":
                if ("drawdown_percent" in rule) == ("drawdown_amount" in rule):
                    raise ValueError("trailing_stop requires exactly one drawdown threshold")
                key = "drawdown_percent" if "drawdown_percent" in rule else "drawdown_amount"
                rule[key] = positive(rule[key], key)
                if key == "drawdown_percent" and rule[key] >= 1:
                    raise ValueError("drawdown_percent must be below 1")
            else:
                if "activation_price" not in rule:
                    raise ValueError("breakeven_stop requires activation_price or activation_percent")
                offsets = set(rule) & {"offset_amount", "offset_percent", "protect_price"}
                if len(offsets) > 1:
                    raise ValueError("use one breakeven protection offset")
                if "protect_price" not in rule:
                    if reference is None:
                        raise ValueError("breakeven_stop requires reference_price or protect_price")
                    rule["protect_price"] = reference + (reference * positive(rule["offset_percent"], "offset_percent", allow_zero=True)
                        if "offset_percent" in rule else positive(rule.get("offset_amount", 0), "offset_amount", allow_zero=True))
                rule["protect_price"] = positive(rule["protect_price"], "protect_price")
                if rule["protect_price"] >= rule["activation_price"]:
                    raise ValueError("protect_price must be below activation_price")
        elif kind == "step_stop":
            if reference is None or not isinstance(rule.get("steps"), list) or not rule["steps"]:
                raise ValueError("step_stop requires reference_price and steps")
            previous_gain = previous_stop = -1
            for step in rule["steps"]:
                if not isinstance(step, dict) or set(step) != {"gain_percent", "protect_percent"}:
                    raise ValueError("each step requires gain_percent and protect_percent")
                gain = positive(step["gain_percent"], "gain_percent", allow_zero=True)
                protect = positive(step["protect_percent"], "protect_percent", allow_zero=True)
                if gain <= previous_gain or protect < previous_stop or protect >= gain:
                    raise ValueError("steps must have increasing gains and nondecreasing protection below each gain")
                previous_gain, previous_stop = gain, protect
        result.append(rule)
    return result


def evaluate_conditions(rules, states, price, now, reference, trigger_on_create=True):
    """Mutate persisted states; return the first trigger. Observed highs never fall."""
    triggered = None
    def above(value, threshold):
        return value >= threshold or math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-10)
    def below(value, threshold):
        return value <= threshold or math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-10)
    for index, rule in enumerate(rules):
        state = states.setdefault(str(index), {})
        kind = rule["type"]
        hit = False
        if kind in ("stop_loss", "take_profit"):
            hit = below(price, rule["price"]) if kind == "stop_loss" else above(price, rule["price"])
        elif kind in ("time_exit", "holding_exit"):
            if now >= rule["at"]:
                # Evaluate the loss gate once, at the first executable fresh snapshot.
                if "time_decision" not in state:
                    state["time_decision"] = not rule.get("only_if_loss") or price < reference
                hit = state["time_decision"]
        elif kind in ("trailing_stop", "breakeven_stop"):
            if above(price, rule.get("activation_price", 0)):
                state.setdefault("activated_at", now)
            if "activated_at" in state:
                if kind == "trailing_stop":
                    state["high"] = max(state.get("high", price), price)
                    candidate = (state["high"] * (1 - rule["drawdown_percent"]) if "drawdown_percent" in rule
                                 else state["high"] - rule["drawdown_amount"])
                else:
                    candidate = rule["protect_price"]
                state["stop"] = max(state.get("stop", candidate), candidate)
                hit = below(price, state["stop"])
        else:
            for step in rule["steps"]:
                if above(price, reference * (1 + step["gain_percent"])):
                    state["stop"] = max(state.get("stop", 0), reference * (1 + step["protect_percent"]))
            hit = "stop" in state and below(price, state["stop"])
        if not hit:
            state["armed"] = True
        if hit and (trigger_on_create or state.get("armed") or kind in ("time_exit", "holding_exit")) and triggered is None:
            triggered = dict(index=index, name=rule["name"], type=kind, price=price, at=now,
                             threshold=state.get("stop", rule.get("price", rule.get("at"))))
    return triggered
