from pathlib import Path

from cfquant.log_management import RollingLogWriter, log_files, read_log, retention_days


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
    path.write_text("2026-09-21 hello\n", encoding="utf-8")
    rows = log_files(tmp_path, "2026-09-21")
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
