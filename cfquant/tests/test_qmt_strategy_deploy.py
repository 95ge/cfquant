"""QMT deployment regressions using disposable terminals and fake bridges only."""

import ast
import copy
import json
from pathlib import Path
import threading
import time
from xml.dom import minidom

import pytest

from cfquant.qmt_strategy_deploy import (
    QmtStrategyManager, _account_binding, _atomic_write, _read_document,
    _write_json, _resolve_account_binding, account_qmt_roots, managed_source, normalize_strategy_settings,
)
from cfquant.qmt_strategy_package import _cipher, build_package
from cfquant.qmt_strategy_runtime import _CqStrategyLease


SCRIPTS = Path(__file__).resolve().parents[2] / "qmt_scripts"
ACCOUNT = "1000000001"
ACCOUNT_KEY = "3____101____201____49____%s____" % ACCOUNT


@pytest.fixture
def deployment(tmp_path):
    root = tmp_path / "QMT"
    for directory in ("bin.x64", "config", "formulas", "python"):
        (root / directory).mkdir(parents=True)
    (root / "bin.x64" / "XtItClient.exe").write_bytes(b"test-only")
    config = root / "config" / "indexUserConfig.xml"
    config.write_text('''<?xml version="1.0" encoding="utf-8"?>
<ICUserConfigFile><other custom="preserved"/><!--keep--><FormulaCatalog/>
<strategyTrade><item id="7" name="CFQUANT_CTYPE_ALL_LOWLAT" account="%s"
 accountType="3" m_strAccountKey="%s" eStrategyType="4" strategymall="0"
 startupAutorun="1" runMode="1" vendorField="preserved"/>
<item id="8" name="USER_STRATEGY" account="%s" accountType="3"
 m_strAccountKey="%s" startupAutorun="1" runMode="1"/>
<item id="9" name="CFQUANT_LITE" account="2000000002" startupAutorun="1"/>
</strategyTrade></ICUserConfigFile>''' % (ACCOUNT, ACCOUNT_KEY, ACCOUNT, ACCOUNT_KEY), encoding="utf-8")
    running = [False]
    manager = QmtStrategyManager(tmp_path / "jobs.json", SCRIPTS, lambda root: running[0])
    row = {"account_key": "bridge:CREDIT:" + ACCOUNT, "account_id": ACCOUNT,
           "account_type": "CREDIT", "bridge_id": "bridge", "mode": "ctypes", "enabled": True,
           "qmt_dir": str(root / "bin.x64"),
           "qmt_strategy": {"enabled": True, "live": False, "autorun": False}}
    identity = {"account_id": ACCOUNT, "account_type": "CREDIT", "bridge_id": "bridge",
                "channels": {"normal": "test_normal", "trade": "test_trade", "callback": "test_callback"},
                "pipe_name": "test-only"}
    identity_path = root / "bin.x64" / "cfquant_bridge_config.json"
    _write_json(identity_path, identity)
    infos = [{"written": True, "core_dir": str(root / "bin.x64"),
              "path": str(identity_path), "qmt_role": "normal"}]
    return manager, row, infos, running, root


def finish_import(manager, root):
    document, _ = _read_document(root / "config" / "indexUserConfig.xml")
    catalog = document.getElementsByTagName("FormulaCatalog")[0]
    for job in manager.jobs.values():
        for role in job["roles"]:
            entry = document.createElement("catalog")
            entry.setAttribute("name", role["name"])
            catalog.appendChild(entry)
            (root / "python" / (role["name"] + ".py")).write_bytes(b"QMT proprietary container")
            (root / "formulas" / (role["name"] + ".rzrk")).unlink(missing_ok=True)
    (root / "config" / "indexUserConfig.xml").write_bytes(document.toxml(encoding="utf-8"))


def models(root):
    document, _ = _read_document(root / "config" / "indexUserConfig.xml")
    return {item.getAttribute("name"): item for item in document.getElementsByTagName("item")}


def test_import_is_resumable_and_not_confused_with_queue_consumption(deployment):
    manager, row, infos, running, root = deployment
    original = (root / "config" / "indexUserConfig.xml").read_bytes()
    running[0] = True
    status = manager.configure(row, infos)
    assert status["targets"][0]["state"] == "waiting_exit"
    assert (root / "config" / "indexUserConfig.xml").read_bytes() == original
    assert not list((root / "formulas").glob("*.rzrk"))
    running[0] = False
    manager.process_once()
    assert manager.status(row["account_key"])["targets"][0]["state"] == "waiting_import"
    assert models(root)["CFQUANT_CTYPE_ALL_LOWLAT"].getAttribute("startupAutorun") == "0"
    assert models(root)["USER_STRATEGY"].getAttribute("startupAutorun") == "1"
    assert models(root)["CFQUANT_LITE"].getAttribute("startupAutorun") == "1"
    assert next((root / "cfquant_managed" / "backups").glob("*.xml")).read_bytes() == original
    manager = QmtStrategyManager(manager.path, SCRIPTS, lambda root: running[0])
    queued = next((root / "formulas").glob("*.rzrk"))
    queued.unlink()
    running[0] = True
    manager.process_once()
    assert manager.status(row["account_key"])["targets"][0]["state"] == "waiting_manual_start"
    running[0] = False
    manager.process_once()
    assert manager.status(row["account_key"])["targets"][0]["state"] == "error"
    manager.configure(row, infos)
    assert queued.is_file()


def test_model_configuration_preserves_account_and_is_idempotent(deployment):
    manager, row, infos, running, root = deployment
    row["qmt_strategy"].update(live=True, autorun=True)
    manager.configure(row, infos)
    finish_import(manager, root)
    manager.process_once()
    job = next(iter(manager.jobs.values()))
    model = models(root)[job["roles"][0]["name"]]
    assert job["state"] == "configured"
    assert model.getAttribute("id") == "10"
    assert model.getAttribute("account") == ACCOUNT
    assert model.getAttribute("accountType") == "3"
    assert model.getAttribute("m_strAccountKey") == ACCOUNT_KEY
    assert model.getAttribute("runMode") == model.getAttribute("startupAutorun") == "1"
    assert model.getAttribute("vendorField") == "preserved"
    assert json.loads(model.getAttribute("FromulaExpandData")) == {
        "m_qsFormula": model.getAttribute("name"), "m_qsAccount": ACCOUNT, "variableSize": "0"}
    original = (root / "config" / "indexUserConfig.xml").read_bytes()
    manager.configure(row, infos)
    assert (root / "config" / "indexUserConfig.xml").read_bytes() == original
    assert len(models(root)) == 4
    assert b"<!--keep-->" in original and b'custom="preserved"' in original


def test_same_mode_reuses_model_name_when_deployment_fingerprint_changes(deployment):
    manager, row, infos, running, root = deployment
    manager.configure(row, infos)
    finish_import(manager, root)
    manager.process_once()
    first = copy.deepcopy(next(iter(manager.jobs.values())))
    name = first["roles"][0]["name"]
    assert first["state"] == "configured"

    identity_path = Path(infos[0]["path"])
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["bridge_id"] = "bridge-updated"
    _write_json(identity_path, identity)

    manager.configure(row, infos)
    second = next(iter(manager.jobs.values()))
    role = second["roles"][0]
    assert second["generation"] != first["generation"]
    assert role["name"] == name
    assert second["retired"] == []
    assert (root / "formulas" / (name + ".rzrk")).is_file()
    assert not (root / "python" / (name + ".py")).exists()
    assert name not in {
        item.getAttribute("name")
        for group in _read_document(root / "config" / "indexUserConfig.xml")[0].getElementsByTagName("FormulaCatalog")
        for item in group.getElementsByTagName("catalog")
    }
    assert len(models(root)) == 4


def test_switch_and_delete_revoke_old_generation_and_disable_its_model(deployment):
    manager, row, infos, running, root = deployment
    row["qmt_strategy"].update(autorun=True)
    manager.configure(row, infos)
    finish_import(manager, root)
    manager.process_once()
    old = copy.deepcopy(next(iter(manager.jobs.values())))
    row["mode"] = "lite"
    running[0] = True
    manager.configure(row, infos)
    new = next(iter(manager.jobs.values()))
    assert old["generation"] != new["generation"]
    assert json.loads(Path(old["control_path"]).read_text())["mode"] == "lite"
    running[0] = False
    manager.process_once()
    assert models(root)[old["roles"][0]["name"]].getAttribute("startupAutorun") == "0"
    manager.reconcile({})
    assert json.loads(Path(new["control_path"]).read_text())["enabled"] is False
    manager.process_once()
    assert new["state"] == "disabled"
    assert not list((root / "formulas").glob("*.rzrk"))


def test_independent_identity_for_two_accounts_in_one_qmt(deployment):
    manager, row, infos, running, root = deployment
    manager.configure(row, infos)
    first = copy.deepcopy(next(iter(manager.jobs.values())))
    row.update(account_id="1000000002", account_key="bridge:CREDIT:1000000002")
    manager.configure(row, infos)
    assert len(manager.jobs) == 2
    roles = [job["roles"][0] for job in manager.jobs.values()]
    assert roles[0]["identity_path"] != roles[1]["identity_path"]
    assert json.loads(Path(first["roles"][0]["identity_path"]).read_text())["account_id"] == ACCOUNT
    assert len(list((root / "formulas").glob("*.rzrk"))) == 2


def test_no_account_binding_is_never_fabricated(deployment):
    manager, row, infos, running, root = deployment
    row.update(account_id="1000000002", account_key="bridge:CREDIT:1000000002")
    manager.configure(row, infos)
    finish_import(manager, root)
    manager.process_once()
    assert next(iter(manager.jobs.values()))["state"] == "waiting_account"
    document, _ = _read_document(root / "config" / "indexUserConfig.xml")
    with pytest.raises(ValueError, match="Key"):
        _account_binding(document, row["account_id"], "CREDIT", ACCOUNT_KEY)
    with pytest.raises(ValueError, match="Key"):
        _account_binding(document, ACCOUNT, "STOCK", ACCOUNT_KEY)


def test_first_start_has_a_credit_model_even_without_an_existing_model(deployment):
    manager, row, infos, running, root = deployment
    config = root / "config" / "indexUserConfig.xml"
    config.write_text('<ICUserConfigFile><FormulaCatalog/><strategyTrade/></ICUserConfigFile>', encoding="utf-8")
    auth = root / "userdata" / "users" / "test_user" / "authAndConfig.xml"
    auth.parent.mkdir(parents=True)
    auth.write_text('<TTAuthAndConfigFile><TTAlgoConfigFile><AccountAuth key="%s" strategys="1"/>'
                    '<AccountAuth key="%s" strategys="4"/></TTAlgoConfigFile></TTAuthAndConfigFile>'
                    % (ACCOUNT_KEY, ACCOUNT_KEY), encoding="utf-8")
    row["qmt_strategy"].update(live=True, autorun=True)
    manager.configure(row, infos)
    job = next(iter(manager.jobs.values()))
    role = job["roles"][0]
    model = models(root)[role["name"]]
    assert job["state"] == "waiting_import"
    assert role["model_prepared"] is True
    assert model.getAttribute("accountType") == "3"
    assert model.getAttribute("m_strAccountKey") == ACCOUNT_KEY
    assert model.getAttribute("startupAutorun") == model.getAttribute("runMode") == "1"
    assert (root / "formulas" / (role["name"] + ".rzrk")).is_file()
    assert not (root / "python" / (role["name"] + ".py")).exists()
    snapshot = config.read_bytes()
    backup_count = len(list((root / "cfquant_managed" / "backups").glob("*.xml")))
    manager.process_once()
    assert config.read_bytes() == snapshot
    assert len(list((root / "cfquant_managed" / "backups").glob("*.xml"))) == backup_count


def test_ambiguous_model_binding_does_not_fall_back_to_another_source(deployment):
    _, _, _, _, root = deployment
    document, _ = _read_document(root / "config" / "indexUserConfig.xml")
    items = document.getElementsByTagName("item")
    items[1].setAttribute("m_strAccountKey", ACCOUNT_KEY.replace("101", "102"))
    assert _resolve_account_binding(root, document, ACCOUNT, "CREDIT", cached=ACCOUNT_KEY) is None


def test_runtime_progress_requires_a_fresh_matching_generation(deployment):
    manager, row, infos, running, root = deployment
    row["qmt_strategy"]["autorun"] = True
    manager.configure(row, infos)
    job = next(iter(manager.jobs.values()))
    role = job["roles"][0]
    running[0] = True
    manager.process_once()
    assert job["state"] == "waiting_start"
    path = role["runtime_status_path"]
    _write_json(path, {"state": "running", "generation": "obsolete", "updated_at": time.time()})
    manager.process_once()
    assert job["state"] == "waiting_start"
    _write_json(path, {"state": "running", "generation": job["generation"], "updated_at": time.time()})
    manager.process_once()
    assert job["state"] == "running"
    _write_json(path, {"state": "running", "generation": job["generation"], "updated_at": time.time() - 20})
    manager.process_once()
    assert job["state"] == "waiting_start"
    _write_json(path, {"state": "error", "generation": job["generation"], "updated_at": time.time(), "error": "fake import failure"})
    manager.process_once()
    assert job["state"] == "error"
    assert "fake import failure" in job["error"]


@pytest.mark.parametrize("mode", ["ctypes", "lite", "lttx"])
def test_all_managed_entry_variants_compile_without_executing(mode, deployment):
    manager, row, infos, running, root = deployment
    row["mode"] = mode
    manager.configure(row, infos)
    role = next(iter(manager.jobs.values()))["roles"][0]
    document = json.loads(_cipher().decrypt(Path(role["package_path"]).read_bytes()).decode("utf-8", "surrogateescape"))
    assert document["detail"]["arguName"] == []
    assert document["detail"]["importUsePwd"] is False
    assert document["detail"]["realName"] == role["name"] + ".py"
    assert document["formulaCatalog"][0].encode("utf-8", "surrogateescape").hex() == "ced2b5c4b2dfc2d4"
    ast.parse(document["content"], feature_version=(3, 6))
    descriptor = {"mode": mode, "generation": "test", "role": "SH", "control_path": "test", "lease_dir": "test"}
    variants = list((SCRIPTS / "同账号独立市场").glob("*.py")) + [SCRIPTS / "CFQUANT_TRADE_LOWLAT.py"]
    for path in variants:
        source = managed_source(path, role["identity_path"], role["identity"], descriptor)
        ast.parse(source, feature_version=(3, 6))


def test_alias_paths_and_strict_setting_types(deployment):
    _, row, _, _, root = deployment
    assert account_qmt_roots(row) == account_qmt_roots(dict(row, qmt_dir=str(root)))
    with pytest.raises(ValueError):
        normalize_strategy_settings({"live": "false"})
    with pytest.raises(ValueError):
        normalize_strategy_settings({"stock": "invalid"})


@pytest.mark.parametrize("encoding", ["utf-8", "gbk", "gb18030"])
def test_managed_package_executes_after_qmt_encoding_with_chinese_paths(tmp_path, encoding):
    directory = tmp_path / "\u534e\u6cf0\u8bc1\u5238 QMT \u6a21\u62df"
    directory.mkdir()
    source_path = directory / "entry.py"
    identity_path = directory / "identity.json"
    identity = {"account_id": ACCOUNT, "account_type": "CREDIT", "bridge_id": "test_bridge"}
    _write_json(identity_path, identity)
    source_path.write_text(
        '# coding: utf-8\nimport json\nMESSAGE = "\u4fe1\u7528\u8d26\u53f7"\n'
        'def _runtime_config_paths():\n    return []\n'
        'def init(context):\n'
        '    with open(_runtime_config_paths()[0], encoding="utf-8") as stream:\n'
        '        context["identity"] = json.load(stream)\n'
        '    context["message"] = MESSAGE\n', encoding="utf-8")
    value = descriptor(directory, "old")
    value["runtime_status_path"] = str(directory / "runtime.status.json")
    grant(value)
    generated = managed_source(source_path, identity_path, identity, value)
    package = build_package("CFQ_ENCODING_TEST", generated)
    content = json.loads(_cipher().decrypt(package).decode("utf-8", "surrogateescape"))["content"]
    code = compile(content.encode(encoding), "<QMT byte source>", "exec")
    namespace = {}
    try:
        exec(code, namespace)
        context = {}
        namespace["init"](context)
        assert context == {"identity": identity, "message": "\u4fe1\u7528\u8d26\u53f7"}
        assert namespace["_cq_descriptor"] == value
        assert namespace["_runtime_config_paths"]() == [str(identity_path)]
    finally:
        if "_cq_guard" in namespace:
            namespace["_cq_guard"].close()


def test_changing_only_live_and_autorun_updates_model_without_reimport(deployment):
    manager, row, infos, running, root = deployment
    manager.configure(row, infos)
    finish_import(manager, root)
    manager.process_once()
    old = copy.deepcopy(next(iter(manager.jobs.values())))
    row["qmt_strategy"].update(live=True, autorun=True)
    running[0] = True
    manager.configure(row, infos)
    assert next(iter(manager.jobs.values()))["state"] == "waiting_exit"
    assert next(iter(manager.jobs.values()))["generation"] == old["generation"]
    running[0] = False
    manager.process_once()
    model = models(root)[old["roles"][0]["name"]]
    assert model.getAttribute("runMode") == model.getAttribute("startupAutorun") == "1"
    assert len(models(root)) == 4
    assert not list((root / "formulas").glob("*.rzrk"))


def test_market_routes_only_import_market_entries_and_use_their_own_stock(deployment):
    manager, row, infos, running, root = deployment
    row["market_routing_enabled"] = True
    market_infos = []
    for market in ("SH", "SZ"):
        identity = json.loads(Path(infos[0]["path"]).read_text())
        identity.update(market=market, bridge_id="bridge_" + market)
        path = root / "bin.x64" / (market + ".json")
        _write_json(path, identity)
        market_infos.append(dict(infos[0], path=str(path), market=market))
    manager.configure(row, infos + market_infos)
    job = next(iter(manager.jobs.values()))
    assert {role["role"] for role in job["roles"]} == {"SH", "SZ"}
    finish_import(manager, root)
    manager.process_once()
    for role in job["roles"]:
        model = models(root)[role["name"]]
        assert model.getAttribute("stock") == {"SH": "SH000300", "SZ": "SZ399001"}[role["role"]]


def descriptor(tmp_path, generation, role="normal"):
    return {"control_path": str(tmp_path / "desired.json"), "lease_dir": str(tmp_path / "leases"),
            "generation": generation, "role": role, "mode": "lite" if generation == "new" else "ctypes"}


def grant(value):
    _write_json(value["control_path"], dict(value, enabled=True))


def test_runtime_heartbeat_requires_initialized_bridges_and_reports_stop(tmp_path):
    value = descriptor(tmp_path, "old")
    path = tmp_path / "runtime.status.json"
    value["runtime_status_path"] = str(path)
    grant(value)
    class Bridge:
        running = True
        context = None
        def close(self):
            self.running = False
    bridge = Bridge()
    lease = _CqStrategyLease(value).acquire()
    try:
        lease.bind({"_normal_bridge": bridge})
        assert json.loads(path.read_text())["state"] == "loaded"
        bridge.context = object()
        lease.last_report = 0
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if json.loads(path.read_text())["state"] == "running":
                break
            time.sleep(0.02)
        assert json.loads(path.read_text())["state"] == "running"
    finally:
        lease.close()
    assert json.loads(path.read_text())["state"] == "stopped"
    assert bridge.running is False


def test_failed_init_reports_error_and_releases_account_lease(tmp_path):
    value = descriptor(tmp_path, "old")
    path = tmp_path / "runtime.status.json"
    value["runtime_status_path"] = str(path)
    grant(value)
    def init(context):
        raise RuntimeError("fake QMT init failure")
    lease = _CqStrategyLease(value).acquire()
    namespace = {"init": init}
    lease.bind(namespace)
    with pytest.raises(RuntimeError, match="fake QMT init failure"):
        namespace["init"](None)
    assert lease.lease is None
    assert json.loads(path.read_text())["error"] == "fake QMT init failure"
    assert json.loads(path.read_text())["state"] == "error"


def test_mode_lease_closes_old_bridge_before_new_starts_and_gates_callbacks(tmp_path):
    old = descriptor(tmp_path, "old")
    grant(old)
    closed, calls = [], []
    lease = _CqStrategyLease(old).acquire()
    namespace = {"stop": lambda context: closed.append("old"), "handlebar": lambda context: calls.append("bar")}
    lease.bind(namespace)
    namespace["handlebar"](None)
    with pytest.raises(RuntimeError):
        _CqStrategyLease(old).acquire(timeout=0.05)
    new = descriptor(tmp_path, "new")
    grant(new)
    replacement = _CqStrategyLease(new).acquire(timeout=3)
    try:
        assert closed == ["old"]
        namespace["handlebar"](None)
        assert calls == ["bar"]
        with pytest.raises(RuntimeError):
            _CqStrategyLease(old).acquire(timeout=0.05)
    finally:
        replacement.close()
        lease.close()


def test_mode_lease_allows_same_generation_markets_but_blocks_failed_shutdown(tmp_path):
    first = descriptor(tmp_path, "old", "SH")
    grant(first)
    leases = [_CqStrategyLease(first).acquire(), _CqStrategyLease(descriptor(tmp_path, "old", "SZ")).acquire()]
    try:
        leases[0].bind({"stop": lambda context: (_ for _ in ()).throw(RuntimeError("fake close error"))})
        grant(descriptor(tmp_path, "new"))
        with pytest.raises(RuntimeError):
            _CqStrategyLease(descriptor(tmp_path, "new")).acquire(timeout=0.4)
    finally:
        from cfquant.qmt_strategy_runtime import _cq_unlock
        for lease in leases:
            lease.close()
            if lease.lease is not None:
                _cq_unlock(lease.lease)
                lease.lease = None


def test_blocking_init_can_be_stopped_during_mode_switch(tmp_path):
    old = descriptor(tmp_path, "old")
    grant(old)
    exited, entered = threading.Event(), threading.Event()
    def initialize(context):
        entered.set()
        exited.wait(5)
    lease = _CqStrategyLease(old).acquire()
    namespace = {"init": initialize, "stop": lambda context: exited.set()}
    lease.bind(namespace)
    worker = threading.Thread(target=namespace["init"], args=(None,))
    worker.start()
    try:
        assert entered.wait(2)
        grant(descriptor(tmp_path, "new"))
        assert exited.wait(2)
    finally:
        exited.set()
        worker.join(2)
        lease.close()


def test_new_mode_waits_for_inflight_request_even_after_bridge_close(tmp_path):
    old = descriptor(tmp_path, "old")
    grant(old)
    entered, finish, closed = threading.Event(), threading.Event(), threading.Event()
    class Bridge:
        def _dispatch(self):
            entered.set()
            finish.wait(5)
        def close(self):
            closed.set()
    bridge = Bridge()
    lease = _CqStrategyLease(old).acquire()
    lease.bind({"_trade_bridge": bridge})
    worker = threading.Thread(target=bridge._dispatch)
    worker.start()
    try:
        assert entered.wait(2)
        new = descriptor(tmp_path, "new")
        grant(new)
        assert closed.wait(2)
        with pytest.raises(RuntimeError):
            _CqStrategyLease(new).acquire(timeout=0.1)
        finish.set()
        worker.join(2)
        replacement = _CqStrategyLease(new).acquire(timeout=1)
        replacement.close()
    finally:
        finish.set()
        worker.join(2)
        lease.close()
