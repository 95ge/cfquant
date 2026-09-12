"""Project update backup, rollback, and trading-lock regressions."""

import pytest


@pytest.fixture
def project_updater(tmp_path, monkeypatch):
    import cfquant_web_server as web

    project_root = tmp_path / "project"
    (project_root / "cfquant").mkdir(parents=True)
    (project_root / "web_dashboard").mkdir()
    (project_root / "cfquant_web_server.py").write_text("server", encoding="utf-8")
    (project_root / "cfquant" / "__init__.py").write_text(
        "__version__ = '1.0.0'\n",
        encoding="utf-8",
    )
    (project_root / "web_dashboard" / "index.html").write_text(
        "<html></html>",
        encoding="utf-8",
    )
    (project_root / "legacy.txt").write_text("legacy", encoding="utf-8")
    (project_root / "cfquant" / "old_module.py").write_text(
        "OLD = True\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(web, "BASE_DIR", str(project_root))
    monkeypatch.setattr(web, "PROJECT_UPDATE_DIR", str(tmp_path / "updates"))
    monkeypatch.setattr(
        web,
        "auto_deploy_qmt_core_for_all_accounts",
        lambda source_dir: {"summary": {"ok": True, "target_count": 0}},
    )
    updater = web.CfquantProjectUpdater()
    monkeypatch.setattr(
        updater,
        "_run_editable_install",
        lambda reason: {"attempted": False, "ok": True, "reason": reason},
    )
    monkeypatch.setattr(updater, "_require_editable_install", lambda result: None)
    return web, updater, project_root


def test_complete_backup_restores_old_files_and_removes_new_files(project_updater):
    _, updater, project_root = project_updater

    backup = updater._backup_project(
        ["legacy.txt", "new_file.txt"],
        label="backup",
        managed_rel_files=["legacy.txt", "new_file.txt"],
    )
    (project_root / "legacy.txt").write_text("new version", encoding="utf-8")
    (project_root / "new_file.txt").write_text("new file", encoding="utf-8")

    updater._restore_backup(backup)

    assert backup["complete"] is True
    assert (project_root / "legacy.txt").read_text(encoding="utf-8") == "legacy"
    assert not (project_root / "new_file.txt").exists()


def test_project_update_backup_covers_current_files_and_new_source_files(project_updater, tmp_path):
    _, updater, project_root = project_updater
    source_root = tmp_path / "source"
    (source_root / "cfquant").mkdir(parents=True)
    (source_root / "web_dashboard").mkdir()
    (source_root / "cfquant_web_server.py").write_text("updated server", encoding="utf-8")
    (source_root / "cfquant" / "__init__.py").write_text(
        "__version__ = '2.0.0'\n",
        encoding="utf-8",
    )
    (source_root / "cfquant" / "new_module.py").write_text(
        "NEW = True\n",
        encoding="utf-8",
    )
    (source_root / "web_dashboard" / "index.html").write_text(
        "<html>updated</html>",
        encoding="utf-8",
    )

    result = updater._install_source(str(source_root), {"source": "test"})
    backup = result["backup"]
    (project_root / "legacy.txt").unlink()
    assert (project_root / "cfquant" / "new_module.py").exists()

    updater._restore_backup(backup)

    assert (project_root / "legacy.txt").read_text(encoding="utf-8") == "legacy"
    assert (project_root / "cfquant" / "old_module.py").read_text(encoding="utf-8") == "OLD = True\n"
    assert not (project_root / "cfquant" / "new_module.py").exists()
    assert (project_root / "cfquant_web_server.py").read_text(encoding="utf-8") == "server"


def test_project_update_backup_names_are_unique(project_updater):
    _, updater, _ = project_updater

    first = updater._backup_project(["legacy.txt"], label="backup")
    second = updater._backup_project(["legacy.txt"], label="backup")

    assert first["name"] != second["name"]
    assert len(updater._list_backups()) == 2


def test_public_rollback_restores_selected_version_and_keeps_recovery_point(project_updater, tmp_path):
    _, updater, project_root = project_updater
    source_root = tmp_path / "rollback-source"
    (source_root / "cfquant").mkdir(parents=True)
    (source_root / "web_dashboard").mkdir()
    (source_root / "cfquant_web_server.py").write_text("updated server", encoding="utf-8")
    (source_root / "cfquant" / "__init__.py").write_text(
        "__version__ = '2.0.0'\n",
        encoding="utf-8",
    )
    (source_root / "web_dashboard" / "index.html").write_text(
        "<html>updated</html>",
        encoding="utf-8",
    )
    (source_root / "new_module.py").write_text("NEW = True\n", encoding="utf-8")

    update_result = updater._install_source(str(source_root), {"source": "test"})
    rollback_result = updater.rollback(update_result["backup"]["name"])

    assert rollback_result["restored_backup"]["name"] == update_result["backup"]["name"]
    assert rollback_result["rollback_backup"]["complete"] is True
    assert (project_root / "cfquant_web_server.py").read_text(encoding="utf-8") == "server"
    assert not (project_root / "new_module.py").exists()
    assert updater.operation_status()["busy"] is False


def test_project_update_operation_blocks_new_trade_requests(project_updater):
    web, updater, _ = project_updater

    assert web.is_project_update_trade_write_path("/api/order")
    assert web.is_project_update_trade_write_path("/api/cftrader/order_stock")
    assert not web.is_project_update_trade_write_path("/api/data/market")

    with updater._operation("update"):
        assert updater.is_busy()
        with updater.trade_request("/api/order"):
            pass
        updater._set_operation_phase(
            "backup",
            "正在创建当前项目的完整回退点",
            trade_locked=True,
        )
        with pytest.raises(web.ProjectUpdateBusyError):
            with updater.trade_request("/api/order"):
                pass
        with pytest.raises(web.ProjectUpdateBusyError):
            with updater._operation("rollback"):
                pass

    assert updater.operation_status()["busy"] is False
