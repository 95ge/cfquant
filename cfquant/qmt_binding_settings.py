"""Persisted per-binding QMT scheduling and log preferences."""
DEFAULT_TIMER_INTERVAL_MS = 1
MIN_TIMER_INTERVAL_MS = 1
MAX_TIMER_INTERVAL_MS = 1000


def normalize_qmt_runtime_settings(value=None, existing=None, strict=False):
    if value is not None and not isinstance(value, dict):
        if strict:
            raise ValueError("QMT runtime settings must be an object")
        value = None
    data = dict(existing or {})
    data.update(value or {})
    interval = data.get("timer_interval_ms", DEFAULT_TIMER_INTERVAL_MS)
    try:
        if isinstance(interval, bool) or str(interval).strip() != str(int(interval)):
            raise ValueError()
        interval = int(interval)
        if not MIN_TIMER_INTERVAL_MS <= interval <= MAX_TIMER_INTERVAL_MS:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        if strict:
            raise ValueError("QMT 调度间隔必须是 1–1000 ms 的整数")
        interval = DEFAULT_TIMER_INTERVAL_MS
    enabled = data.get("log_enabled")  # None preserves legacy global preferences.
    if enabled is not None and not isinstance(enabled, bool):
        if strict:
            raise ValueError("QMT 日志设置必须为 true、false 或 null（跟随全局）")
        enabled = None
    return {"timer_interval_ms": interval, "log_enabled": enabled}


def qmt_runtime_identity(row, global_log_enabled=True):
    settings = normalize_qmt_runtime_settings((row or {}).get("qmt_runtime"))
    enabled = settings["log_enabled"]
    if (row or {}).get("mode") == "lttx":
        enabled = None  # Advanced entries keep their existing global controls.
    return {"qmt_timer_interval_ms": settings["timer_interval_ms"],
            "qmt_log_enabled": bool(global_log_enabled) if enabled is None else enabled}
