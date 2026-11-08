"""Sample runtime counters and local QMT resources outside the trading path."""
import time

from .trading_monitor import number


class PerformanceSampler:
    def __init__(self, psutil_module=None):
        self.psutil = psutil_module
        self._previous = {}
        self._processes = {}

    def process(self, pid):
        pid = int(number(pid))
        if pid <= 0:
            return {"available": False, "reason": "missing_pid"}
        if self.psutil is None:
            return {"available": False, "pid": pid, "reason": "missing_psutil"}
        now = time.monotonic()
        previous = self._processes.get(pid)
        if previous and now - previous[0] < 1:
            return dict(previous[3])
        try:
            proc = self.psutil.Process(pid)
            with proc.oneshot():
                created = proc.create_time()
                cpu = proc.cpu_times()
                cpu_seconds = cpu.user + cpu.system
                row = {"available": True, "pid": pid, "name": proc.name(),
                       "rss_bytes": proc.memory_info().rss, "threads": proc.num_threads(),
                       "memory_percent": round(proc.memory_percent(), 2),
                       "sampled_at": time.time(), "cpu_percent": None}
            # Task Manager convention: 100% means all logical processors busy.
            if previous and created == previous[1] and cpu_seconds >= previous[2]:
                cores = self.psutil.cpu_count() or 1
                row["cpu_percent"] = round(min(100, max(0, 100 * (cpu_seconds - previous[2]) / (now - previous[0]) / cores)), 2)
            self._processes[pid] = (now, created, cpu_seconds, row)
            self._processes = {key: value for key, value in self._processes.items() if now - value[0] < 3600}
            return dict(row)
        except Exception as error:
            self._processes.pop(pid, None)
            return {"available": False, "pid": pid, "reason": type(error).__name__}

    def decorate(self, snapshot):
        mode = (snapshot.get("monitor") or {}).get("transport_mode", "")
        now = number(snapshot.get("checked_at"), time.time())
        for channel in ("normal", "trade"):
            item = snapshot.setdefault(channel, {})
            status = item.get("status") or {}
            raw = item.get("telemetry") or status.get("telemetry") or {}
            runtime = status.get("runtime") or {}
            pid = item.get("process_id") or raw.get("pid") or runtime.get("pid")
            perf = {"available": raw.get("schema") == 1, "process": self.process(pid)}
            if perf["available"]:
                perf.update(raw)
                perf["age_seconds"] = max(0, now - number(raw.get("sampled_at"), now))
                perf["stale"] = perf["age_seconds"] > max(30, number((snapshot.get("monitor") or {}).get("interval_seconds"), 10) * 3)
                perf["qmt_callback_total"] = number(raw.get("callback_total")) + number(raw.get("quote_callback_batches"))
                key = (snapshot.get("bridge_id"), mode, channel)
                previous = self._previous.get(key)
                identity = (pid, raw.get("started_at"))
                stamp = number(raw.get("sample_monotonic"))
                rates = {}
                if previous and previous[0] == identity:
                    delta = stamp - previous[1]
                    if delta == 0:
                        rates = previous[3]
                    elif delta > 0:
                        old = previous[2]
                        for field in ("request_completed", "callback_total", "quote_callback_batches", "quote_distribution_batches", "quote_distribution_symbols"):
                            change = number(raw.get(field)) - number(old.get(field))
                            if change >= 0:
                                rates[field + "_per_second"] = round(change / delta, 3)
                        count = number(raw.get("request_completed")) - number(old.get("request_completed"))
                        elapsed = number(raw.get("request_total_ms")) - number(old.get("request_total_ms"))
                        rates["request_avg_ms"] = round(elapsed / count, 3) if count > 0 and elapsed >= 0 else None
                        rates["window_seconds"] = round(delta, 2)
                perf["rates"] = rates
                self._previous[key] = (identity, stamp, dict(raw), dict(rates))
            item["performance"] = perf
        return snapshot
