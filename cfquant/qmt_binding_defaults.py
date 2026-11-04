"""One-time migration of QMT automation preferences, using saved version evidence."""
import copy
import re


AUTOMATION_DEFAULTS_VERSION = "0.2.59"
MIGRATION_KEY = "qmt_automation_defaults_migration"


def is_pre_automation_defaults_version(value):
    """Schema numbers, missing values and unrecognized versions are not evidence."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)\d+)?(?:\.post\d+)?(?:\+[-\w.]+)?", str(value or "").strip())
    if not match:
        return False
    version = tuple(int(match.group(i)) for i in (1, 2, 3))
    return version < (0, 2, 59) or (version == (0, 2, 59) and bool(match.group(4)))


def migrate_qmt_automation_defaults(raw):
    """Return a copy only when a known old configuration needs migration.

    The running/installed version and QMT's version do not date user preferences.
    They must never be used as substitutes for the saved configuration version.
    """
    if not isinstance(raw, dict) or raw.get(MIGRATION_KEY):
        return raw, 0
    source_version = raw.get("saved_core_version", raw.get("core_version"))
    if not is_pre_automation_defaults_version(source_version):
        return raw, 0
    result = copy.deepcopy(raw)
    changed = 0
    for collection in ("account_configs", "account_pairs"):
        rows = result.get(collection) or {}
        rows = rows.values() if isinstance(rows, dict) else rows if isinstance(rows, list) else []
        for row in rows:
            if not isinstance(row, dict) or not row.get("account_id"):
                continue
            login = row.get("qmt_auto_login")
            login = dict(login) if isinstance(login, dict) else {}
            login.update(enabled=True, auto_update=True)
            # Preserve custom schedules and explicit empty schedules. Only absent
            # schedules receive the same default as a new binding.
            if not any(key in login for key in ("restart_times", "restartTimes", "restart_time", "restartTime")):
                login["restart_times"] = ["09:00"]
            row["qmt_auto_login"] = login
            if collection == "account_configs":
                strategy = row.get("qmt_strategy")
                strategy = dict(strategy) if isinstance(strategy, dict) else {}
                strategy.update(enabled=True, autorun=True)
                row["qmt_strategy"] = strategy
                changed += 1
    result[MIGRATION_KEY] = {"version": AUTOMATION_DEFAULTS_VERSION, "source_version": str(source_version),
                             "bindings": changed}
    return result, changed
