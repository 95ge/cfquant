"""Deterministic execution tests. No RPC, QMT session or real order is used."""
import copy
from types import SimpleNamespace

import pytest

from cfquant.algo import AlgoEngine, AlgoStore
from cfquant.shared_quotes import SharedQuoteFeed


ACCOUNT = {"account_id": "TEST_ONLY", "account_type": "STOCK"}
CODE = "600000.SH"


def test_task_database_has_one_runtime_owner(tmp_path):
    path = str(tmp_path / "ownership.sqlite3")
    first = AlgoStore(path)
    try:
        with pytest.raises(RuntimeError, match="another algorithm runtime"):
            AlgoStore(path)
    finally:
        first.close()
    AlgoStore(path).close()


class Broker:
    def __init__(self):
        self.rows = []
        self.sent = []
        self.cancelled = []
        self.lose_ack = False
        self.fail_query = False

    def prepare(self, params, now):
        return dict(windows=[[now, now + params["duration_seconds"]]], side="buy",
                    price_tick=0.01, volume_step=100, min_child_volume=100, volume_multiplier=1)

    def orders(self, account, stock_code):
        if self.fail_query:
            raise RuntimeError("query unavailable")
        return copy.deepcopy(self.rows)

    def check_capacity(self, *args):
        pass

    def submit(self, account, config, child):
        self.sent.append(copy.deepcopy(child))
        row = dict(order_id=len(self.sent), stock_code=CODE, order_remark=child["remark"],
                   order_status=50, traded_volume=0, traded_price=child["price"])
        self.rows.append(row)
        if self.lose_ack:
            raise TimeoutError("lost acknowledgement")
        return row["order_id"]

    def cancel(self, account, order_id, code):
        self.cancelled.append(order_id)
        return 0

    def fill(self, index=-1, amount=None):
        row = self.rows[index]
        row["traded_volume"] = amount if amount is not None else self.sent[index]["volume"]
        row["order_status"] = 56 if row["traded_volume"] == self.sent[index]["volume"] else 55


@pytest.fixture
def execution(tmp_path):
    now = [1793691000.0]
    callbacks, subscriptions, releases = [], [], []
    def subscribe(codes, callback, generation):
        callbacks.append(callback)
        subscriptions.append(codes)
        return len(callbacks)
    feed = SharedQuoteFeed(subscribe, lambda handle: releases.append(handle),
                           initial_scope=["SH", "SZ", "BJ"], idle_seconds=0, clock=lambda: now[0])
    broker = Broker()
    path = str(tmp_path / "algos.sqlite3")
    engine = AlgoEngine(feed, broker, AlgoStore(path), clock=lambda: now[0])
    def tick(volume=0, price=10, generation=None):
        callbacks[-1]({CODE: dict(time=int(now[0] * 1000), volume=volume, lastPrice=price,
                                  askPrice=[price], bidPrice=[price - .01])})
    def submit(algo="TWAP", **options):
        args = dict(account=ACCOUNT, stock_code=CODE, order_type=23, order_volume=1000,
                    limit_price=10.05, algo=algo, duration_seconds=100, interval_seconds=10,
                    child_timeout_seconds=200)
        args.update(options)
        task = engine.submit(args)
        engine.step(task)
        return task
    env = SimpleNamespace(now=now, engine=engine, broker=broker, feed=feed, tick=tick, submit=submit,
                          subscriptions=subscriptions, releases=releases, path=path)
    yield env
    env.engine.close()
    feed.close()


def test_twap_schedule_fills_and_reservations_never_exceed_parent(execution):
    e = execution
    task = e.submit()
    for index in range(10):
        e.tick()
        e.engine.step(task)
        assert e.broker.sent[-1]["volume"] == 100
        e.broker.fill()
        e.engine.step(task)
        e.now[0] += 10
    result = e.engine.query(task, ACCOUNT)
    assert result["status"] == "COMPLETED"
    assert result["filled_volume"] == 1000
    assert sum(row["volume"] for row in e.broker.sent) == 1000
    assert e.releases == [1]


def test_partial_fill_and_working_quantity_are_counted_once(execution):
    e = execution
    task = e.submit()
    e.tick()
    e.engine.step(task)
    e.broker.fill(amount=40)
    e.now[0] += 10
    e.tick()
    e.engine.step(task)
    assert len(e.broker.sent) == 2
    assert e.broker.sent[-1]["volume"] == 100
    for _ in range(4):
        e.engine.step(task)
    result = e.engine.query(task, ACCOUNT)
    assert result["filled_volume"] == 40
    assert result["reserved_volume"] == 160
    assert len(e.broker.sent) == 2


def test_reused_order_id_with_other_remark_is_never_cancelled(execution):
    e = execution
    task = e.submit()
    e.tick()
    e.engine.step(task)
    e.broker.rows[0]["order_remark"] = "unrelated-order"
    e.engine.control(task, ACCOUNT, "cancel")
    e.engine.step(task)
    assert not e.broker.cancelled
    result = e.engine.query(task, ACCOUNT)
    assert result["reserved_volume"] == 100
    assert result["status"] == "CANCELLING"


def test_vwap_uses_volume_curve_instead_of_equal_slices(execution):
    e = execution
    task = e.submit("VWAP", duration_seconds=90, interval_seconds=30, volume_profile=[5, 3, 2])
    for quantity in (500, 300, 200):
        e.tick()
        e.engine.step(task)
        assert e.broker.sent[-1]["volume"] == quantity
        e.broker.fill()
        e.engine.step(task)
        e.now[0] += 30
    assert e.engine.query(task, ACCOUNT)["status"] == "COMPLETED"


def test_pov_excludes_volume_before_task_start_and_rebases_after_reset(execution):
    e = execution
    task = e.submit("POV", participation_rate=.1)
    e.tick(volume=1_000_000)
    e.engine.step(task)
    assert not e.broker.sent
    e.now[0] += 10
    e.tick(volume=1_002_000)
    e.engine.step(task)
    assert e.broker.sent[-1]["volume"] == 200
    e.broker.fill()
    e.now[0] += 10
    e.tick(volume=500)
    e.engine.step(task)
    assert len(e.broker.sent) == 1
    e.now[0] += 10
    e.tick(volume=1500)
    e.engine.step(task)
    assert e.broker.sent[-1]["volume"] == 100


def test_unknown_submit_never_replayed_until_broker_reconciliation(execution):
    e = execution
    task = e.submit()
    e.tick()
    e.broker.lose_ack = True
    e.engine.step(task)
    accepted = e.broker.rows.pop()
    e.now[0] += 40
    e.tick()
    e.engine.step(task)
    assert len(e.broker.sent) == 1
    assert e.engine.query(task, ACCOUNT)["children"][0]["state"] == "UNKNOWN"
    e.engine.control(task, ACCOUNT, "cancel")
    e.engine.step(task)
    assert e.engine.query(task, ACCOUNT)["status"] == "CANCELLING"
    e.broker.rows.append(accepted)
    e.engine.step(task)
    assert e.broker.cancelled == [1]
    accepted.update(order_status=54, traded_volume=40)
    e.engine.step(task)
    result = e.engine.query(task, ACCOUNT)
    assert result["status"] == "CANCELLED" and result["filled_volume"] == 40


def test_pause_cancels_children_and_resume_waits_for_confirmed_cancellation(execution):
    e = execution
    task = e.submit()
    e.tick()
    e.engine.step(task)
    e.engine.control(task, ACCOUNT, "pause")
    e.engine.step(task)
    assert e.broker.cancelled == [1]
    e.now[0] += 20
    e.tick()
    e.engine.control(task, ACCOUNT, "resume")
    e.engine.step(task)
    assert len(e.broker.sent) == 1
    e.broker.rows[0]["order_status"] = 54
    e.engine.step(task)
    assert e.broker.sent[-1]["volume"] == 300


def test_deadline_cancels_then_reports_expired_with_partial_completion(execution):
    e = execution
    task = e.submit()
    e.tick()
    e.engine.step(task)
    e.broker.fill(amount=40)
    e.now[0] += 100
    e.engine.step(task)
    assert e.engine.query(task, ACCOUNT)["status"] == "CANCELLING"
    e.broker.rows[0]["order_status"] = 53
    e.engine.step(task)
    result = e.engine.query(task, ACCOUNT)
    assert result["status"] == "EXPIRED" and result["remaining_volume"] == 960
    assert len(e.broker.sent) == 1


def test_stale_or_missing_quotes_prevent_submission_and_price_is_capped(execution):
    e = execution
    task = e.submit()
    e.engine.step(task)
    assert not e.broker.sent
    e.tick(price=11)
    e.now[0] += 16
    e.engine.step(task)
    assert not e.broker.sent
    e.tick(price=11)
    e.engine.step(task)
    assert e.broker.sent[0]["price"] == 10.05


def test_restart_reconciles_existing_children_before_creating_new_orders(execution):
    e = execution
    task = e.submit()
    e.tick()
    e.broker.lose_ack = True
    e.engine.step(task)
    e.engine.close()
    e.engine = AlgoEngine(e.feed, e.broker, AlgoStore(e.path), clock=lambda: e.now[0])
    e.broker.fail_query = True
    with pytest.raises(RuntimeError, match="query unavailable"):
        e.engine.step(task)
    assert len(e.broker.sent) == 1
    e.broker.fail_query = False
    e.engine.step(task)
    assert len(e.broker.sent) == 1
    assert e.engine.query(task, ACCOUNT)["children"][0]["order_id"] == 1


def test_durable_intent_failure_prevents_order_submission(execution, monkeypatch):
    e = execution
    task = e.submit()
    e.tick()
    save = e.engine.store.save
    def failing(task):
        if task["children"]:
            raise OSError("disk unavailable")
        return save(task)
    monkeypatch.setattr(e.engine.store, "save", failing)
    with pytest.raises(OSError):
        e.engine.step(task)
    assert not e.broker.sent


def test_task_id_is_account_scoped_and_repeated_request_key_is_idempotent(execution):
    e = execution
    first = e.submit(request_key="my-decision")
    second = e.submit(request_key="my-decision")
    assert first == second
    with pytest.raises(ValueError, match="different"):
        e.submit(request_key="my-decision", order_volume=2000)
    with pytest.raises(ValueError, match="not found"):
        e.engine.query(first, {"account_id": "ANOTHER"})
