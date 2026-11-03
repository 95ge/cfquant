"""Offline resource/lifecycle checks for the shared market-data feed."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from cfquant.shared_quotes import SharedQuoteFeed


class Upstream:
    def __init__(self):
        self.calls = []
        self.callbacks = {}
        self.live = set()
        self.maximum_live = 0
        self.fail_stop = False
        self.fail_start = False
        self.initial = None

    def subscribe(self, codes, callback, generation):
        self.calls.append(("subscribe", codes))
        if self.fail_start:
            raise RuntimeError("subscribe failed")
        handle = len(self.callbacks) + 1
        self.callbacks[handle] = callback
        self.live.add(handle)
        self.maximum_live = max(self.maximum_live, len(self.live))
        if self.initial:
            callback(self.initial)
        return handle

    def unsubscribe(self, handle):
        self.calls.append(("unsubscribe", handle))
        if self.fail_stop:
            raise RuntimeError("unsubscribe failed")
        self.live.remove(handle)

    def emit(self, **data):
        self.callbacks[max(self.live)](data)


@pytest.fixture
def shared():
    upstream = Upstream()
    feed = SharedQuoteFeed(upstream.subscribe, upstream.unsubscribe,
                           initial_scope=["SH", "SZ", "BJ"], idle_seconds=0, asynchronous=False)
    yield feed, upstream
    upstream.fail_stop = False
    feed.close()


def test_concurrent_clients_and_algorithms_share_one_subscription(shared):
    feed, upstream = shared
    with ThreadPoolExecutor(max_workers=12) as pool:
        ids = list(pool.map(lambda i: feed.acquire(str(i), ["600000.SH"], purpose="algo"), range(30)))
    assert len(set(ids)) == 30
    assert upstream.calls == [("subscribe", ["SH", "SZ", "BJ"])]
    for lease_id in ids[:-1]:
        feed.release(lease_id)
    assert len(upstream.live) == 1
    feed.release(ids[-1])
    assert upstream.live == set()
    assert upstream.maximum_live == 1


def test_user_unsubscribe_does_not_disconnect_algorithm(shared):
    feed, upstream = shared
    seen = []
    user = feed.acquire("user", ["SH"], seen.append)
    algo = feed.acquire("algo", ["600000.SH"], purpose="algo")
    feed.release(user)
    upstream.emit(**{"600000.SH": {"time": 1000, "lastPrice": 10, "volume": 150}})
    assert seen == []
    assert feed.snapshot("600000.SH")["quote"]["volume"] == 150
    assert feed.status()["consumers"] == 1
    feed.release(algo)
    assert feed.snapshot("600000.SH") is None


def test_scope_expansion_keeps_existing_leases_and_one_native_handle(shared):
    feed, upstream = shared
    old = []
    lease = feed.acquire("stock", ["600000.SH"], old.append)
    first_callback = upstream.callbacks[1]
    feed.acquire("future", ["rb2610.SF"])
    assert upstream.maximum_live == 1
    assert upstream.calls[1][0] == "unsubscribe"
    first_callback({"600000.SH": {"lastPrice": 99}})
    assert feed.snapshot("600000.SH") is None
    upstream.emit(**{"600000.SH": {"lastPrice": 10}, "rb2610.SF": {"lastPrice": 3000}})
    assert old == [{"600000.SH": {"lastPrice": 10}}]
    assert feed.release(lease)
    assert upstream.live


def test_initial_callback_is_frozen_filtered_and_delivered_after_ack(shared):
    feed, upstream = shared
    upstream.initial = {"600000.SH": {"lastPrice": 10, "bidPrice": [9.9]},
                        "000001.SZ": {"lastPrice": 8}}
    seen = []
    feed.acquire("user", ["SH"], seen.append)
    upstream.initial["600000.SH"]["bidPrice"][0] = 100
    seen[0]["600000.SH"]["lastPrice"] = 500
    snapshot = feed.snapshot("600000.SH")
    assert snapshot["quote"] == {"lastPrice": 10, "bidPrice": [9.9]}
    assert "000001.SZ" not in seen[0]


def test_cache_merges_partial_batches_and_rejects_old_ticks(shared):
    feed, upstream = shared
    feed.acquire("algo", ["SH"])
    upstream.emit(**{"600000.SH": {"time": 20, "lastPrice": 10, "volume": 500},
                     "600001.SH": {"time": 20, "lastPrice": 11}})
    upstream.emit(**{"600000.SH": {"time": 21, "volume": 600}})
    upstream.emit(**{"600000.SH": {"time": 19, "lastPrice": 100}})
    assert feed.snapshot("600000.SH")["quote"] == {"time": 21, "lastPrice": 10, "volume": 600}
    assert feed.snapshot("600001.SH")["quote"]["lastPrice"] == 11


def test_retry_same_lease_is_idempotent_and_scope_mismatch_rejected(shared):
    feed, upstream = shared
    first = feed.acquire("stable-request-id", ["SH"])
    assert feed.acquire("stable-request-id", ["SH"]) == first
    with pytest.raises(ValueError):
        feed.acquire("stable-request-id", ["SZ"])
    assert len(upstream.calls) == 1


def test_failed_unsubscribe_retains_handle_and_blocks_duplicate_start(shared):
    feed, upstream = shared
    first = feed.acquire("first", ["SH"])
    upstream.fail_stop = True
    with pytest.raises(RuntimeError):
        feed.release(first)
    with pytest.raises(RuntimeError):
        feed.acquire("second", ["SF"])
    assert upstream.maximum_live == 1
    assert feed.status()["consumers"] == 1
    upstream.fail_stop = False
    feed.release(first)
    assert not upstream.live


def test_failed_start_never_becomes_a_successful_lease(shared):
    feed, upstream = shared
    upstream.fail_start = True
    with pytest.raises(RuntimeError):
        feed.acquire("algo", ["SH"])
    assert feed.status()["consumers"] == 0
    assert feed.status()["state"] == "error"
    upstream.fail_start = False
    feed.acquire("algo", ["SH"])
    assert feed.status()["state"] == "live"


def test_reconnect_invalidates_old_cache_and_old_session_callbacks(shared):
    feed, upstream = shared
    feed.acquire("algo", ["SH"])
    upstream.emit(**{"600000.SH": {"lastPrice": 10}})
    generation = feed.snapshot("600000.SH")["generation"]
    feed.upstream_lost()
    assert feed.snapshot("600000.SH") is None
    feed.reconnect()
    upstream.callbacks[1]({"600000.SH": {"lastPrice": 999}})
    assert feed.snapshot("600000.SH") is None
    upstream.emit(**{"600000.SH": {"lastPrice": 11}})
    assert feed.snapshot("600000.SH")["generation"] > generation


def test_slow_callback_does_not_block_ingestion_or_another_consumer():
    upstream = Upstream()
    feed = SharedQuoteFeed(upstream.subscribe, upstream.unsubscribe, idle_seconds=0)
    entered, release, fast = threading.Event(), threading.Event(), threading.Event()
    def slow(data):
        entered.set()
        release.wait(3)
    try:
        feed.acquire("slow", ["SH"], slow)
        feed.acquire("fast", ["SH"], lambda data: fast.set())
        upstream.emit(**{"600000.SH": {"time": 1, "volume": 100}})
        assert entered.wait(1)
        upstream.emit(**{"600000.SH": {"time": 2, "volume": 200}})
        assert fast.wait(1)
        assert feed.snapshot("600000.SH")["quote"]["volume"] == 200
    finally:
        release.set()
        feed.close()


def test_idle_release_reuses_subscription_when_new_consumer_arrives():
    upstream = Upstream()
    feed = SharedQuoteFeed(upstream.subscribe, upstream.unsubscribe, idle_seconds=30)
    try:
        feed.release(feed.acquire("first", ["SH"]))
        feed.acquire("second", ["SH"])
        assert feed.release_idle() is False
        assert len(upstream.calls) == 1
    finally:
        feed.close()
