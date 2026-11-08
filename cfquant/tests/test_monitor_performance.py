from cfquant.monitor_performance import PerformanceSampler


def snapshot(stamp, callbacks, requests=0):
    return {
        "bridge_id": "monitor-test",
        "checked_at": 1000 + stamp,
        "monitor": {"transport_mode": "ctypes", "interval_seconds": 5},
        "normal": {
            "online": True,
            "telemetry": {
                "schema": 1,
                "pid": 123,
                "started_at": 900,
                "sampled_at": 1000 + stamp,
                "sample_monotonic": stamp,
                "callback_total": callbacks,
                "quote_callback_batches": callbacks // 2,
                "quote_distribution_batches": callbacks,
                "quote_distribution_symbols": callbacks * 3,
                "request_completed": requests,
                "request_total_ms": requests * 4,
            },
        },
        "trade": {"online": False},
    }


def test_decorate_computes_window_rates_and_keeps_process_probe(monkeypatch):
    sampler = PerformanceSampler(None)
    monkeypatch.setattr(sampler, "process", lambda pid: {"available": True, "pid": int(pid), "rss_bytes": 10} if pid else {"available": False})
    sampler.decorate(snapshot(10, 10, 2))
    current = sampler.decorate(snapshot(15, 20, 5))["normal"]["performance"]

    assert current["qmt_callback_total"] == 30
    assert current["rates"]["callback_total_per_second"] == 2.0
    assert current["rates"]["quote_distribution_symbols_per_second"] == 6.0
    assert current["rates"]["request_avg_ms"] == 4.0
    assert current["process"]["pid"] == 123


def test_decorate_marks_old_sample_stale():
    sampler = PerformanceSampler(None)
    sampler.process = lambda pid: {"available": False, "pid": int(pid)} if pid else {"available": False}
    data = snapshot(0, 1)
    data["checked_at"] = 2000
    data["normal"]["telemetry"]["sampled_at"] = 1000
    sampler.decorate(data)
    assert data["normal"]["performance"]["stale"] is True
