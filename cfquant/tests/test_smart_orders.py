"""Deterministic account/quote/broker fakes; these tests never contact QMT."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from cfquant.algo import AlgoStore
from cfquant.conditional_orders import evaluate_conditions, validate_conditions
from cfquant.position_sizing import calculate_position, instrument_rules
from cfquant.smart_orders import SmartOrderEngine
from cfquant.tests.test_algo import Broker, ACCOUNT, CODE


def size(**options):
    return calculate_position(**dict(dict(stock_code=CODE, entry_price=10, stop_price=9,
        method="risk_percent", total_asset=100000, risk_percent=.02, available_cash=100000), **options))


def test_risk_sizing_includes_both_minimum_fees_and_never_rounds_up():
    result = size()
    assert result["theoretical_quantity"] == 2000
    assert result["quantity"] == 1900
    assert result["estimated_loss"] <= 2000
    assert "stop_risk_budget" in result["limiting_reasons"]
    assert size(method="risk_amount", risk_amount=100)["quantity"] == 0
    assert size(method="risk_amount", risk_amount=111)["quantity"] == 100


@pytest.mark.parametrize("code,minimum,step", [(CODE, 100, 100), ("688001.SH", 200, 1), ("920001.BJ", 100, 1)])
def test_instrument_minimum_and_increment(code, minimum, step):
    result = size(stock_code=code, method="cash_amount", cash_amount=minimum * 10 + 6)
    assert result["quantity"] == minimum
    assert result["rules"]["volume_step"] == step
    assert size(stock_code=code, method="cash_amount", cash_amount=minimum * 10)["quantity"] == 0


def test_cash_allocation_target_and_position_caps():
    assert size(method="cash_amount", cash_amount=10000)["quantity"] == 900
    assert size(method="allocation_percent", allocation_percent=.1)["quantity"] == 900
    assert size(method="allocation_percent", allocation_percent=.5, allocation_base="available_cash",
                available_cash=10000, reserved_cash=2000)["quantity"] == 300
    assert size(method="target_weight", target_weight=.1, current_volume=400, pending_buy_volume=100)["quantity"] == 400
    assert size(method="target_weight", target_weight=.1, current_volume=2000)["quantity"] == 0
    assert size(max_position_percent=.1, current_volume=500, pending_buy_volume=100)["quantity"] == 400
    assert size(available_cash=1000)["quantity"] == 0
    assert size(take_profit_price=12)["reward_risk_ratio"] > 1.9


@pytest.mark.parametrize("options", [dict(stop_price=10), dict(stop_price=11), dict(stop_price=0),
    dict(entry_price=float("nan")), dict(risk_percent=2), dict(entry_price=True), dict(entry_price=10.001),
    dict(stock_code="510300.SH"), dict(stock_code="600000.HK"), dict(available_cash=-1),
    dict(method="short"), dict(current_volume=1.5)])
def test_invalid_sizing_rejected(options):
    with pytest.raises(ValueError):
        size(**options)


def test_trailing_activation_high_and_monotonic_steps():
    rules = validate_conditions([dict(type="trailing_stop", activation_percent=.1, drawdown_percent=.05)], 10)
    states = {}
    assert evaluate_conditions(rules, states, 10, 1, 10) is None
    assert "high" not in states["0"]
    assert evaluate_conditions(rules, states, 12, 2, 10) is None
    assert evaluate_conditions(rules, states, 11.5, 3, 10) is None
    assert states["0"]["high"] == 12
    assert evaluate_conditions(rules, states, 11.4, 4, 10)["type"] == "trailing_stop"
    rules = validate_conditions([dict(type="step_stop", steps=[dict(gain_percent=.1, protect_percent=.02),
                                                              dict(gain_percent=.2, protect_percent=.1)])], 10)
    states = {}
    evaluate_conditions(rules, states, 12, 1, 10)
    evaluate_conditions(rules, states, 11.5, 2, 10)
    assert states["0"]["stop"] == 11
    assert evaluate_conditions(rules, states, 11, 3, 10)


def test_time_loss_gate_once_and_breakeven():
    rules = validate_conditions([dict(type="time_exit", at=100, only_if_loss=True)], 10)
    states = {}
    assert evaluate_conditions(rules, states, 11, 100, 10) is None
    assert evaluate_conditions(rules, states, 9, 110, 10) is None
    rules = validate_conditions([dict(type="breakeven_stop", activation_percent=.1, offset_amount=.05)], 10)
    states = {}
    assert evaluate_conditions(rules, states, 9, 1, 10) is None
    assert evaluate_conditions(rules, states, 11.1, 2, 10) is None
    assert evaluate_conditions(rules, states, 10.04, 3, 10)


class Quotes:
    def __init__(self, now):
        self.now = now
        self.value = None
        self.leases = set()

    def acquire(self, name, *args, **kwargs):
        self.leases.add(name)
        return name

    def release(self, lease):
        self.leases.discard(lease)

    def snapshot(self, *args):
        return copy.deepcopy(self.value)

    def tick(self, price=10, age=0):
        self.value = dict(quote=dict(lastPrice=price, bidPrice=[price], askPrice=[price],
                                    time=int((self.now[0] - age) * 1000), volume=100000), generation=1)


class PlanningFake(Broker):
    def __init__(self):
        super().__init__()
        self.cash = 100000
        self.holdings = 1000
        self.sellable = 1000
        self.session = True

    def rules(self, code):
        return instrument_rules(code)

    def snapshot(self, account, code):
        return dict(total_asset=100000, available_cash=self.cash, current_volume=self.holdings,
                    pending_buy_volume=0, sellable_volume=self.sellable, captured_at=0)

    def session_end(self, code, now):
        return now + 3600 if self.session else None

    def holding_deadline(self, code, rule):
        return rule.get("at", rule["opened_at"] + 86400 * rule.get("trading_days", 1))

    def prepare(self, params, now):
        return dict(super().prepare(params, now), side="buy" if params["order_type"] == 23 else "sell",
                    min_child_volume=params.get("min_child_volume", 100), volume_step=params.get("volume_step", 100))


@pytest.fixture
def env(tmp_path):
    now = [1793691000.0]
    quotes, broker = Quotes(now), PlanningFake()
    path = str(tmp_path / "smart.sqlite3")
    engine = SmartOrderEngine(quotes, broker, AlgoStore(path), clock=lambda: now[0])
    quotes.tick()
    value = SimpleNamespace(now=now, quotes=quotes, broker=broker, engine=engine, path=path)
    yield value
    value.engine.close()


def condition(e, **options):
    return e.engine.order_condition(dict(dict(account=ACCOUNT, stock_code=CODE, order_volume=1000,
        conditions=[dict(type="stop_loss", price=9), dict(type="take_profit", price=12)],
        execution=dict(limit_price=8)), **options))


def preview(e, **options):
    return e.engine.preview_order_plan(dict(dict(account=ACCOUNT, stock_code=CODE,
        sizing=dict(method="risk_amount", entry_price=10, stop_price=9, risk_amount=1100),
        protection=dict(conditions=[dict(type="stop_loss", price=9)], execution=dict(limit_price=8))), **options))


def test_oco_fires_once_ignores_stale_quotes_and_waits_for_sellable(env):
    e = env
    key = condition(e)
    e.quotes.tick(8, age=30)
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["trigger"] is None
    e.broker.sellable = 0
    e.quotes.tick(8)
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["status"] == "WAITING_SELLABLE"
    assert not e.broker.sent
    e.broker.sellable = 1000
    e.engine.step(key)
    child = e.engine.query(key, ACCOUNT)["exits"][0]
    e.engine.step(child)
    assert len(e.broker.sent) == 1
    e.quotes.tick(13)
    e.engine.step(key)
    assert len(e.engine.query(key, ACCOUNT)["exits"]) == 1
    e.broker.fill()
    e.engine.step(child)
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["status"] == "COMPLETED"


def test_restart_preserves_high_and_unknown_exit_no_duplicate(env):
    e = env
    key = condition(e, conditions=[dict(type="trailing_stop", drawdown_percent=.05)])
    e.quotes.tick(12)
    e.engine.step(key)
    e.engine.close()
    e.engine = SmartOrderEngine(e.quotes, e.broker, AlgoStore(e.path), clock=lambda: e.now[0])
    e.quotes.tick(11)
    e.engine.step(key)
    child = e.engine.query(key, ACCOUNT)["exits"][0]
    e.broker.lose_ack = True
    e.engine.step(child)
    e.broker.rows.clear()
    e.engine.close()
    e.engine = SmartOrderEngine(e.quotes, e.broker, AlgoStore(e.path), clock=lambda: e.now[0])
    e.now[0] += 120
    e.quotes.tick(11)
    e.engine.step(child)
    e.engine.step(key)
    assert len(e.broker.sent) == 1
    assert e.engine.query(child, ACCOUNT)["children"][0]["state"] == "UNKNOWN"
    assert e.engine.query(key, ACCOUNT)["states"]["0"]["high"] == 12


def test_condition_account_isolation_idempotence_and_claims(env):
    key = condition(env, request_key="same")
    assert condition(env, request_key="same") == key
    with pytest.raises(ValueError, match="different"):
        condition(env, request_key="same", order_volume=200)
    with pytest.raises(ValueError, match="unclaimed"):
        condition(env)
    with pytest.raises(ValueError, match="not found"):
        env.engine.query(key, dict(ACCOUNT, bridge_id="other"))


def test_initial_crossing_pause_expiry_and_session(env):
    e = env
    key = condition(e, trigger_on_create=False, expires_at=e.now[0] + 100)
    e.quotes.tick(8)
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["trigger"] is None
    e.quotes.tick(10)
    e.engine.step(key)
    e.engine.control(key, ACCOUNT, "pause")
    e.quotes.tick(8)
    e.engine.step(key)
    assert not e.engine.query(key, ACCOUNT)["trigger"]
    e.engine.control(key, ACCOUNT, "resume")
    e.broker.session = False
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["status"] == "WAITING_SESSION"
    e.now[0] += 101
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["status"] == "EXPIRED"


def test_plan_preview_no_order_submit_once_partial_fills_only_and_t_plus_one(env):
    e = env
    plan = preview(e)
    key = plan["algo_id"]
    e.engine.step(key)
    assert not e.broker.sent
    plan = e.engine.submit_order_plan(key, ACCOUNT)
    assert e.engine.submit_order_plan(key, ACCOUNT)["entry_id"] == plan["entry_id"]
    entry, protection = plan["entry_id"], plan["protection_id"]
    e.engine.step(protection)
    assert e.engine.query(protection, ACCOUNT)["status"] == "WAITING_FILL"
    e.engine.step(entry)
    assert len(e.broker.sent) == 1
    e.broker.fill(amount=300)
    e.engine.step(entry)
    e.broker.sellable = 0
    e.quotes.tick(8.5)
    e.engine.step(protection)
    p = e.engine.query(protection, ACCOUNT)
    assert p["remaining_volume"] == 300
    assert p["status"] == "WAITING_SELLABLE"
    assert e.engine.query(entry, ACCOUNT)["status"] == "CANCELLING"
    e.broker.rows[0]["order_status"] = 54
    e.engine.step(entry)
    e.broker.sellable = 300
    e.engine.step(protection)
    exit_id = e.engine.query(protection, ACCOUNT)["exits"][0]
    e.engine.step(exit_id)
    assert e.broker.sent[-1]["volume"] == 300
    e.broker.fill()
    e.engine.step(exit_id)
    e.engine.step(protection)
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["status"] == "COMPLETED"
    assert e.engine.query(key, ACCOUNT)["reserved_cash"] == 0


def test_concurrent_plan_cash_reservation_and_expiration(env):
    e = env
    e.broker.cash = 10005.1
    first, second = preview(e)["algo_id"], preview(e)["algo_id"]
    barrier = threading.Barrier(2)
    def submit(key):
        barrier.wait()
        try:
            return e.engine.submit_order_plan(key, ACCOUNT)["sizing"]["quantity"]
        except ValueError:
            return 0
    with ThreadPoolExecutor(2) as pool:
        quantities = list(pool.map(submit, [first, second]))
    assert sum(quantities) == 1000
    assert sum(e.engine.query(key, ACCOUNT)["reserved_cash"] for key in (first, second)) <= e.broker.cash
    third = preview(e, expires_seconds=1)["algo_id"]
    e.now[0] += 2
    with pytest.raises(ValueError, match="expired"):
        e.engine.submit_order_plan(third, ACCOUNT)


def test_submit_revalidates_cash_quote_and_portfolio_risk(env):
    e = env
    plan = preview(e, portfolio_risk_cap=100)
    with pytest.raises(ValueError, match="risk cap"):
        e.engine.submit_order_plan(plan["algo_id"], ACCOUNT)
    e.quotes.tick(10.5)
    plan = preview(e)
    with pytest.raises(ValueError, match="ask exceeds"):
        e.engine.submit_order_plan(plan["algo_id"], ACCOUNT)
    e.quotes.tick(10)
    e.broker.cash = 2500
    result = e.engine.submit_order_plan(plan["algo_id"], ACCOUNT)
    assert result["sizing"]["quantity"] == 200


def test_cancel_plan_retains_protection_and_crash_before_ready_blocks_entry(env):
    e = env
    plan = e.engine.submit_order_plan(preview(e)["algo_id"], ACCOUNT)
    task = e.engine._tasks[plan["algo_id"]]
    task.update(ready=False, status="SUBMITTING")
    e.engine._save(task)
    e.engine.step(plan["entry_id"])
    assert not e.broker.sent
    e.engine.close()
    e.engine = SmartOrderEngine(e.quotes, e.broker, AlgoStore(e.path), clock=lambda: e.now[0])
    e.engine.step(plan["algo_id"])
    e.engine.step(plan["entry_id"])
    e.broker.fill(amount=100)
    e.engine.step(plan["entry_id"])
    e.engine.cancel_order_plan(plan["algo_id"], ACCOUNT)
    assert e.engine.query(plan["protection_id"], ACCOUNT)["stop_reason"] is None
    assert e.engine.query(plan["entry_id"], ACCOUNT)["status"] == "CANCELLING"


def test_failed_persistence_prevents_entry_send(env, monkeypatch):
    e = env
    plan = e.engine.submit_order_plan(preview(e)["algo_id"], ACCOUNT)
    def fail(task):
        raise OSError("disk full")
    monkeypatch.setattr(e.engine.store, "save", fail)
    with pytest.raises(OSError):
        e.engine.step(plan["entry_id"])
    assert not e.broker.sent
    with pytest.raises(RuntimeError, match="persistence failed"):
        e.engine.step(plan["entry_id"])


def test_target_weight_counts_plans_not_yet_visible_at_broker(env):
    e = env
    e.broker.holdings = 0
    sizing = dict(method="target_weight", target_weight=.1, entry_price=10)
    first, second = preview(e, sizing=sizing), preview(e, sizing=sizing)
    one = e.engine.submit_order_plan(first["algo_id"], ACCOUNT)
    with pytest.raises(ValueError, match="no legal quantity"):
        e.engine.submit_order_plan(second["algo_id"], ACCOUNT)
    assert one["sizing"]["quantity"] == 900


def test_cancel_orphan_exit_after_crash_before_linking(env):
    e = env
    key = condition(e)
    e.quotes.tick(8)
    e.engine.step(key)
    task = e.engine._tasks[key]
    child = task["exits"].pop()
    e.engine._save(task)
    e.engine.step(child)
    assert not e.broker.sent
    e.engine.control(key, ACCOUNT, "cancel")
    e.engine.step(key)
    e.engine.step(child)
    e.engine.step(key)
    assert e.engine.query(key, ACCOUNT)["status"] == "CANCELLED"
    assert not e.broker.sent


@pytest.mark.parametrize("code,volume", [(CODE, 40), ("688001.SH", 120), ("920001.BJ", 50)])
def test_whole_odd_lot_exit_is_not_rounded_up(env, code, volume):
    e = env
    e.broker.holdings = e.broker.sellable = volume
    key = condition(e, stock_code=code, order_volume=volume)
    e.quotes.tick(8)
    e.engine.step(key)
    child = e.engine.query(key, ACCOUNT)["exits"][0]
    assert e.engine.query(child, ACCOUNT)["config"]["order_volume"] == volume
    e.engine.step(child)
    assert e.broker.sent[0]["volume"] == volume
