# -*- coding: utf-8 -*-
import os
import sys
import types

from cfquant import cli


def test_cli_dry_run_applies_web_runtime_paths(monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    config = tmp_path / "config.json"
    monkeypatch.setenv("CFQUANT_HOME", "")
    monkeypatch.setenv("CFQUANT_WEB_CONFIG_FILE", "")

    result = cli.main([
        "--home",
        str(home),
        "--config",
        str(config),
        "--port",
        "8766",
        "--dry-run",
    ])

    assert result == 0
    assert os.environ["CFQUANT_HOME"] == str(home)
    assert os.environ["CFQUANT_WEB_CONFIG_FILE"] == str(config)
    output = capsys.readouterr().out
    assert "core=" in output
    assert "CFQUANT_HOME=%s" % home in output


def test_cli_delegates_web_arguments(monkeypatch, tmp_path):
    calls = []
    fake_module = types.ModuleType("cfquant_web_server")
    monkeypatch.setenv("CFQUANT_HOME", "")

    def fake_main(argv):
        calls.append(list(argv))
        return 17

    fake_module.main = fake_main
    monkeypatch.setitem(sys.modules, "cfquant_web_server", fake_module)

    result = cli.main([
        "--home",
        str(tmp_path / "state"),
        "--host",
        "127.0.0.1",
        "--port",
        "8767",
    ])

    assert result == 17
    assert calls == [["--host", "127.0.0.1", "--port", "8767"]]


def test_cli_exports_bundled_qmt_scripts(tmp_path):
    output_dir = tmp_path / "qmt"

    result = cli.main(["qmt-scripts", "--output", str(output_dir)])

    assert result == 0
    for relative_name in cli.QMT_SCRIPT_FILES:
        assert (output_dir / relative_name).is_file()


def test_cli_qmt_scripts_default_shows_installed_directory(capsys):
    result = cli.main(["qmt-scripts"])

    assert result == 0
    output = capsys.readouterr().out
    assert "QMT 入口脚本目录" in output
    assert "导出命令" in output
    assert "CFQUANT_CTYPE_ALL_LOWLAT.py" in output
    assert "同账号独立市场/readme.md" in output


def test_cli_qmt_scripts_show_does_not_require_output(capsys):
    result = cli.main(["qmt-scripts", "--show"])

    assert result == 0
    output = capsys.readouterr().out
    assert "QMT 入口脚本目录" in output
    assert "内置脚本文件" not in output


def test_pipe_hub_cli_applies_runtime_paths_before_import(monkeypatch, tmp_path):
    import cfquant.pipe_hub as pipe_hub
    import cfquant_pipe_hub

    calls = []
    monkeypatch.setenv("CFQUANT_HOME", "")
    monkeypatch.setenv("CFQUANT_RUNTIME_DIR", "")
    monkeypatch.setenv("CFQUANT_PIPE_HUB_STATUS_FILE", "")
    monkeypatch.setattr(
        pipe_hub,
        "run_pipe_hub",
        lambda **kwargs: calls.append(kwargs),
    )

    state_dir = tmp_path / "state"
    result = cfquant_pipe_hub.main([
        "--home",
        str(state_dir),
        "--runtime-dir",
        str(state_dir / "runtime"),
        "--pipe-name",
        r"\\.\pipe\cfquant_test",
        "--quiet",
    ])

    assert result is None
    assert os.environ["CFQUANT_HOME"] == str(state_dir)
    assert os.environ["CFQUANT_RUNTIME_DIR"] == str(state_dir / "runtime")
    assert calls == [{
        "pipe_name": r"\\.\pipe\cfquant_test",
        "show": False,
        "default_request_channel": "cfquant.normal.request",
    }]
