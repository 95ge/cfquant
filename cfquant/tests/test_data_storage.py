import json
import os
from pathlib import Path
import time

import pytest

from cfquant.data_storage import cleanup, initialize, log_rows, maintenance_lock, save_policy, summary


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "安装目录" / "data"
    root.mkdir(parents=True)
    initialize(root, [])
    return root


def logfile(root, name, size=10, days=40):
    path = root / "logs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_default_thirty_days_preserves_recent_logs_and_business_data(data):
    old = logfile(data, "core/old.log")
    recent = logfile(data, "core/recent.log", days=2)
    database = data / "runtime/accounts.db"
    database.write_bytes(b"user-database")
    config = data / "desktop/settings.json"
    config.write_text('{"keep":true}')
    result = cleanup(data)
    assert result["deleted_files"] == 1
    assert not old.exists() and recent.exists()
    assert database.read_bytes() == b"user-database" and config.exists()
    assert summary(data)["policy"]["days"] == 30


def test_forever_keeps_old_logs_but_allows_explicit_delete(data):
    old = logfile(data, "old.log", days=600)
    save_policy(data, {"mode": "forever"})
    assert cleanup(data)["deleted_files"] == 0 and old.exists()
    assert cleanup(data, ["old.log"])["deleted_files"] == 1


def test_quota_removes_oldest_first(data):
    oldest = logfile(data, "a.log", size=700000, days=10)
    middle = logfile(data, "b.log", size=500000, days=3)
    newest = logfile(data, "c.log", size=400000, days=1)
    save_policy(data, {"mode": "size", "max_bytes": 1024 ** 2})
    result = cleanup(data)
    assert result["deleted_files"] == 1 and not oldest.exists()
    assert middle.exists() and newest.exists() and result["remaining_bytes"] == 900000


def test_quota_reports_protected_excess(data):
    active = logfile(data, "active.log", size=1200000, days=0)
    save_policy(data, {"mode": "size", "max_bytes": 1024 ** 2})
    result = cleanup(data)
    assert result["over_limit_bytes"] > 0 and result["skipped_files"] == 1 and active.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows deny-sharing handles")
def test_idle_open_log_is_not_deleted(data):
    active = logfile(data, "idle.log")
    with active.open("rb"):
        result = cleanup(data)
        assert result["deleted_files"] == 0 and result["skipped_files"] == 1
    assert cleanup(data)["deleted_files"] == 1


def test_path_traversal_and_business_file_selection_rejected(data):
    logfile(data, "safe.log")
    (data / "runtime/orders.db").write_bytes(b"keep")
    for selection in [["../runtime/orders.db"], [str(data / "runtime/orders.db")], ["missing.log"], []]:
        with pytest.raises(ValueError):
            cleanup(data, selection)
    assert (data / "runtime/orders.db").read_bytes() == b"keep"


def test_invalid_policy_stops_cleanup_without_fallback(data):
    old = logfile(data, "old.log")
    (data / "config/log-retention.json").write_text('{"mode":"invalid"}')
    with pytest.raises(ValueError):
        cleanup(data)
    assert old.exists()


def test_hardlinks_and_directory_links_are_not_cleaned(data, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    real = logfile(data, "original.log")
    hardlink = outside / "same.log"
    os.link(real, hardlink)
    assert cleanup(data)["deleted_files"] == 0
    assert real.exists() and hardlink.exists()
    try:
        (data / "logs/linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    (outside / "keep.log").write_text("preserve")
    cleanup(data)
    assert (outside / "keep.log").read_text() == "preserve"


def test_migration_preserves_conflicts_and_removes_verified_sources(data, tmp_path):
    old = tmp_path / "legacy"
    old.mkdir()
    (old / "settings.json").write_text("old-settings")
    (old / "session.bin").write_bytes(b"encrypted-session")
    (data / "desktop/settings.json").write_text("current-settings")
    report = initialize(data, [{"source": str(old), "destination": "desktop"}])
    assert not report["errors"] and report["moved_files"] == 2
    assert not old.exists()
    assert (data / "desktop/settings.json").read_text() == "current-settings"
    assert (data / "desktop/session.bin").read_bytes() == b"encrypted-session"
    assert next((data / "migration-backup").rglob("settings.json")).read_text() == "old-settings"
    assert not initialize(data, [{"source": str(old), "destination": "desktop"}])["errors"]


@pytest.mark.skipif(os.name != "nt", reason="Windows deny-sharing handles")
def test_migration_does_not_copy_an_open_database(data, tmp_path):
    old = tmp_path / "old.db"
    old.write_bytes(b"live-database")
    with old.open("rb"):
        result = initialize(data, [{"source": str(old), "destination": "runtime/new.db"}])
    assert result["errors"] and old.exists() and not (data / "runtime/new.db").exists()


def test_manual_and_background_cleanup_share_a_lock(data):
    logfile(data, "old.log")
    with maintenance_lock(data):
        with pytest.raises(OSError):
            cleanup(data)
    assert cleanup(data)["deleted_files"] == 1


def test_summary_reports_actual_bytes(data):
    logfile(data, "one.log", size=45)
    (data / "runtime/user.db").write_bytes(b"1234567")
    result = summary(data)
    assert result["log_bytes"] == 45 and result["log_count"] == 1
    assert next(row for row in result["categories"] if row["key"] == "runtime")["size"] == 7
