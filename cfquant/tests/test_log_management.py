import datetime
from pathlib import Path

from cfquant.log_management import (
    RollingLogWriter,
    component_log_dir,
    component_log_dirs,
    log_files,
    read_log,
    retention_days,
)


def test_component_log_dirs_create_stable_subdirectories(tmp_path):
    root = tmp_path / "log"
    dirs = component_log_dirs(root)
    assert set(dirs) == {"web", "center", "startup", "lttx", "pipe_hub", "qmt_bridge"}
    assert all(Path(path).is_dir() for path in dirs.values())
    assert component_log_dir(root, "LTtx") == dirs["lttx"]

    day = datetime.date.today().isoformat()
    csv_path = Path(dirs["lttx"]) / (day + "_log.csv")
    csv_path.write_text("event\n", encoding="utf-8")
    rows = log_files(root, day)
    assert rows and rows[0]["name"] == "lttx/" + day + "_log.csv"
    assert read_log(root, rows[0]["name"])["text"].replace("\r\n", "\n") == "event\n"


def test_retention_days_is_bounded():
    assert retention_days("30") == 30
    try:
        retention_days("0")
    except ValueError:
        pass
    else:
        raise AssertionError("zero retention must be rejected")


def test_log_listing_and_tail_are_bounded(tmp_path):
    path = tmp_path / "server.log"
    day = datetime.date.today().isoformat()
    path.write_text(day + " hello\n", encoding="utf-8")
    rows = log_files(tmp_path, day)
    assert rows and rows[0]["name"] == "server.log"
    result = read_log(tmp_path, "server.log")
    assert "hello" in result["text"]


def test_writer_rotates_large_file(tmp_path):
    path = tmp_path / "runtime.log"
    writer = RollingLogWriter(path, max_bytes=8)
    writer.write("12345678\n")
    writer.write("next\n")
    writer.flush()
    writer.close()
    assert list(tmp_path.glob("runtime.*.log"))
