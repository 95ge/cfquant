# -*- coding: utf-8 -*-
import json

from cfquant.runtime_report import publish_qmt_runtime_marker, read_qmt_runtime_markers


def test_publish_qmt_runtime_marker_writes_configured_dir(tmp_path):
    marker_dir = tmp_path / "qmt_runtime"
    result = publish_qmt_runtime_marker(
        reason="test_start",
        version="core_test_01",
        core_version="core_test_01",
        entry_version="entry_test_01",
        entry_script="CFQUANT_TEST.py",
        bridge="TestBridge",
        bridge_id="test",
        account_id="123",
        account_type="STOCK",
        transport="pipe",
        channel_key="normal",
        request_channel="cfquant.test.normal",
        config={"qmt_runtime_marker_dir": str(marker_dir)},
    )

    assert result["ok"] is True
    assert len(result["files"]) == 1
    with open(result["primary_file"], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema"] == "cfquant.qmt.runtime"
    assert data["core_version"] == "core_test_01"
    assert data["entry_version"] == "entry_test_01"
    assert data["bridge_id"] == "test"
    assert data["channel_key"] == "normal"
    assert data["marker_file"] == result["primary_file"]


def test_read_qmt_runtime_markers_returns_marker_data(tmp_path):
    marker_dir = tmp_path / "qmt_runtime"
    publish_qmt_runtime_marker(
        reason="test_read",
        version="core_test_02",
        core_version="core_test_02",
        entry_script="CFQUANT_TEST.py",
        bridge_id="test",
        channel_key="trade",
        config={"qmt_runtime_marker_dir": str(marker_dir)},
    )

    reports = read_qmt_runtime_markers([str(marker_dir)])

    assert len(reports) == 1
    assert reports[0]["core_version"] == "core_test_02"
    assert reports[0]["schema"] == "cfquant.qmt.runtime"
    assert reports[0]["marker_file"]
