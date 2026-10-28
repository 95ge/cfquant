"""Exercise the actual Pipe entry programs with all application file IO denied."""
import ast
import builtins
import importlib
import io
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

import pytest

from cfquant.qmt_pipe_runtime import ManagedPipeRuntime
from cfquant.qmt_strategy_deploy import QmtStrategyManager, configured_pipe_source, managed_source, read_entry_source
from cfquant.tests.test_qmt_strategy_deploy import deployment, finish_import

SCRIPTS = Path(__file__).resolve().parents[2] / "qmt_scripts"
ENTRIES = sorted(p for p in SCRIPTS.rglob("*.py")
                 if p.name.startswith(("CFQUANT_LITE", "CFQUANT_CTYPE_ALL_LOWLAT")))


class FakeTransport:
    def __init__(self, *args, **kwargs):
        self.Q = queue.Queue()
        self.events = []

    def start(self):
        return self

    def start_txg(self, *args):
        pass

    def close(self):
        pass

    def _get_conn(self):
        return self

    _get_tx_conn = _get_conn

    def push(self, *args, **kwargs):
        self.events.append(args)


class NoThread:
    def __init__(self, *args, **kwargs):
        self.daemon = True

    def start(self):
        pass

    def is_alive(self):
        return False

    def join(self, *args, **kwargs):
        pass


class Context:
    def __init__(self):
        self.intervals = []

    def set_account(self, *args):
        pass

    def set_auto_trade_callback(self, *args):
        pass

    def schedule_run(self, *args, **kwargs):
        self.intervals.append(kwargs['interval'].total_seconds() * 1000)
        return "test-timer"

    def cancel_schedule_run(self, *args, **kwargs):
        pass


def deny_files(monkeypatch, attempts):
    def denied(*args, **kwargs):
        attempts.append(args)
        raise PermissionError("QMT file IO disabled")
    for owner, names in ((builtins, ("open",)), (io, ("open",)),
                         (os, ("open", "mkdir", "makedirs", "stat", "listdir", "scandir", "remove", "unlink", "replace", "rename"))):
        for name in names:
            monkeypatch.setattr(owner, name, denied)


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: p.stem)
@pytest.mark.parametrize("managed", [False, True])
def test_entry_load_init_status_callbacks_and_stop_without_files(path, managed, tmp_path, monkeypatch, capsys):
    import cfquant.pipe_bridge as pipe_bridge
    import cfquant.pipe_transport as pipe_transport
    mode = "lite" if "LITE" in path.name else "ctypes"
    market = path.stem.rsplit("_", 1)[-1]
    market = market if market in ("SH", "SZ") else ""
    identity = dict(account_id="test-account", account_type="CREDIT", bridge_id="test-bridge",
                    market=market, pipe_name="test-pipe", qmt_log_enabled=False, qmt_timer_interval_ms=7,
                    channels={"normal": "test.normal", "trade": "test.trade", "callback": "test.callback"})
    descriptor = dict(runtime_key=uuid.uuid4().hex, mode=mode, role=market or "normal", generation="current")
    source = (managed_source(path, tmp_path / "absent.json", identity, descriptor) if managed
              else configured_pipe_source(read_entry_source(path), identity))
    assert "_CqStrategyLease" not in source
    assert "_write_lite_runtime_marker" not in source
    tree = ast.parse(source)
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id in ("open", "exec", "eval", "compile") for n in ast.walk(tree))
    # Substitute only the transport boundary; execute real entry/bridge logic.
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.ClassDef) and node.name == "PipeTxClient":
            tree.body.insert(index + 1, ast.parse("PipeTxClient = FakeTransport").body[0])
            break
    code = compile(ast.fix_missing_locations(tree), "<QMT strategy>", "exec")
    attempts = []
    namespace = {"FakeTransport": FakeTransport}
    with monkeypatch.context() as patch:
        patch.setattr(pipe_bridge, "PipeTxClient", FakeTransport)
        patch.setattr(pipe_transport, "PipeTxClient", FakeTransport)
        patch.setattr(importlib, "reload", lambda module: module)
        patch.setattr(threading, "Thread", NoThread)
        patch.setattr(sys, "dont_write_bytecode", True)
        patch.setenv("CFQUANT_QMT_NO_FILE_IO", "1")
        patch.setenv("CFQUANT_QMT_LOG_ENABLED", "1")
        patch.setenv("CFQUANT_CTYPE_TRADE_TIMER_INTERVAL_MS", "99")
        patch.setenv("CFQUANT_ACCOUNT_ID", "stale-other-account")
        # Scripts mutate these process globals; isolate each simulated QMT.
        patch.setattr(os, "environ", os.environ.copy())
        patch.setattr(sys, "path", list(sys.path))
        deny_files(patch, attempts)
        exec(code, namespace)
        normal, trade = namespace["_normal_bridge"], namespace["_trade_bridge"]
        runtime = namespace["_managed_runtime"]
        try:
            context = Context()
            if managed:
                from cfquant.protocol import pack_request
                responses = []
                normal._send_response = lambda msg, result: responses.append(result)
                normal._handle_raw_from_thread(pack_request("cfquant.strategy.control", dict(descriptor, enabled=True)))
                assert responses[0]["state"] == "loaded"
                assert runtime.approved
                runtime.approved = False
            namespace["init"](context)
            namespace["after_init"](context)
            assert namespace['TRADE_TIMER_INTERVAL_MS'] == 7
            assert 7 in context.intervals
            assert namespace['get_log_enabled']() is False
            assert normal._status()['log_enabled'] is False
            assert trade._status()['log_enabled'] is False
            assert capsys.readouterr().out == ''
            if managed:
                with pytest.raises(RuntimeError, match="awaiting"):
                    normal._dispatch("cfquant.set_log_language", {}, {})
                report = normal._dispatch("cfquant.strategy.control", dict(descriptor, enabled=True), {})
                assert report["state"] == "running"
            assert normal._status()["context_ready"]
            assert trade._status()["context_ready"]
            assert normal._runtime_info()["account_id"] == identity["account_id"]
            assert normal.account_type == trade.account_type == "CREDIT"
            normal._publish_runtime_report("test")
            normal._log("fileless console log", force=True)
            trade._log("fileless console log", force=True)
            namespace["order_callback"](context, {"m_strAccountID": "test-account", "m_nOrderID": 123})
            namespace["deal_callback"](context, {"m_strAccountID": "test-account", "m_nOrderID": 123})
            namespace["handlebar"](context)
            with pytest.raises(NotImplementedError, match="file IO"):
                normal._cleanup_qmt_userdata_logs({})
            assert normal.tx.events
        finally:
            namespace["stop"](context)
        assert not normal.running and not trade.running
        assert attempts == []


def test_memory_control_scopes_ownership_and_blocks_stale_requests():
    key = uuid.uuid4().hex
    desc = dict(runtime_key=key, mode="lite", generation="new", role="SH")
    runtime = ManagedPipeRuntime(desc).acquire()
    other = ManagedPipeRuntime(dict(desc, role="SZ")).acquire()
    calls = []
    dispatch = runtime.dispatch(lambda *args: calls.append(args) or "ok")
    try:
        with pytest.raises(RuntimeError, match="Another"):
            ManagedPipeRuntime(dict(desc, mode="ctypes")).acquire()
        with pytest.raises(ValueError, match="scope"):
            runtime.control(dict(desc, runtime_key="another-account", enabled=True))
        with pytest.raises(RuntimeError, match="awaiting"):
            dispatch("trade", {}, {})
        runtime.control(dict(desc, enabled=True, generation="old", accepted_generations=["new"]))
        assert dispatch("trade", {}, {}) == "ok"
        runtime.control(dict(desc, enabled=False))
        with pytest.raises(RuntimeError):
            dispatch("trade", {}, {})
        # A delayed old message cannot reactivate a revoked strategy.
        runtime.control(dict(desc, enabled=True))
        assert not runtime.approved
        assert len(calls) == 1
    finally:
        runtime.close()
        other.close()
    replacement = ManagedPipeRuntime(desc).acquire()
    replacement.close()


@pytest.mark.parametrize("state_before_disable", ["running", "error"])
def test_manager_receives_pipe_status_and_sends_disable(deployment, state_before_disable):
    manager, row, infos, running, root = deployment
    row["mode"] = "lite"
    manager.configure(row, infos)
    job = next(iter(manager.jobs.values()))
    role = job["roles"][0]
    from cfquant.qmt_strategy_package import _cipher
    import json
    content = json.loads(_cipher().decrypt(Path(role["package_path"]).read_bytes()).decode("utf-8", "surrogateescape"))["content"]
    config_node = next(n.value for n in ast.parse(content).body if isinstance(n, ast.Assign)
                       and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "EMBEDDED_RUNTIME_CONFIG")
    assert ast.literal_eval(config_node)["managed_strategy"]["runtime_key"] == manager._desired(job)["runtime_key"]
    desc = dict(manager._desired(job), role=role["role"])
    runtime = ManagedPipeRuntime(desc).acquire()
    class Bridge:
        running = True
        context = object()
        def close(self):
            self.running = False
    runtime.namespace = {"_normal_bridge": Bridge()}
    manager.runtime_request = lambda identity, desired: runtime.control(desired)
    running[0] = True
    try:
        manager.process_once()
        assert job["state"] == "running"
        assert Path(role["runtime_status_path"]).is_file()
        job["enabled"] = False
        job["state"] = state_before_disable
        manager.process_once()
        assert runtime.revoked
    finally:
        runtime.close()


@pytest.mark.parametrize("blocked_by", ["none", "error", "backoff", "exhausted", "missing_config", "web_restart"])
def test_manager_reauthorizes_restarted_strategy(deployment, blocked_by):
    manager, row, infos, running, root = deployment
    manager.configure(row, infos)
    finish_import(manager, root)
    manager.process_once()
    job = next(iter(manager.jobs.values()))
    role = job["roles"][0]
    descriptor = dict(manager._desired(job), role=role["role"])

    class Bridge:
        running = True
        context = object()

        def close(self):
            self.running = False

    runtime = ManagedPipeRuntime(descriptor).acquire()
    runtime.namespace = {"_normal_bridge": Bridge()}
    manager.runtime_request = lambda identity, desired: runtime.control(desired)
    running[0] = True
    try:
        manager.process_once()
        assert runtime.status()["state"] == job["state"] == "running"
        runtime.close()
        runtime = ManagedPipeRuntime(descriptor).acquire()
        runtime.namespace = {"_normal_bridge": Bridge()}
        dispatch = runtime.dispatch(lambda *args: "accepted")
        assert runtime.status()["state"] == "loaded"
        with pytest.raises(RuntimeError, match="awaiting account mode confirmation"):
            dispatch("xttrader.query_stock_asset", {}, {})

        if blocked_by in ("error", "backoff", "exhausted", "web_restart"):
            job.update(state="error", error="previous deployment failed")
            if blocked_by in ("backoff", "exhausted"):
                job.update(deploy_retry_count=5 if blocked_by == "exhausted" else 1,
                           deploy_retry_after=time.time() + 3600)
            if blocked_by == "web_restart":
                manager._save()
                manager = QmtStrategyManager(manager.path, manager.scripts_dir, lambda root: running[0],
                                             runtime_request=manager.runtime_request)
                job = next(iter(manager.jobs.values()))
        config = root / "config" / "indexUserConfig.xml"
        if blocked_by == "missing_config":
            config.unlink()
        original = config.read_bytes() if config.exists() else None

        manager.process_once()

        assert runtime.status()["state"] == job["state"] == "running"
        assert dispatch("xttrader.query_stock_asset", {}, {}) == "accepted"
        assert (config.read_bytes() if config.exists() else None) == original
    finally:
        runtime.close()


def test_control_failure_is_reported_and_retried(deployment):
    manager, row, infos, running, root = deployment
    manager.configure(row, infos)
    job = next(iter(manager.jobs.values()))
    role = job["roles"][0]
    runtime = ManagedPipeRuntime(dict(manager._desired(job), role=role["role"])).acquire()
    attempts = []

    def deliver(identity, desired):
        attempts.append(desired)
        if len(attempts) == 1:
            raise OSError("test Pipe unavailable")
        return runtime.control(desired)

    manager.runtime_request = deliver
    running[0] = True
    try:
        manager.process_once()
        failed = manager.status(row["account_key"])["targets"][0]["control_sync"][0]
        assert not runtime.approved
        assert failed["last_attempt_at"] > 0
        assert "test Pipe unavailable" in failed["last_error"]
        assert not failed.get("last_success_at")
        assert failed["request_channel"] == "test_normal"

        manager.process_once()
        recovered = manager.status(row["account_key"])["targets"][0]["control_sync"][0]
        assert len(attempts) == 2
        assert runtime.approved
        assert recovered["last_error"] == ""
        assert recovered["last_success_at"] >= failed["last_attempt_at"]
        assert recovered["generation"] == job["generation"]
        assert recovered["state"] == "loaded"  # No QMT context in this test.
    finally:
        runtime.close()


def test_control_continues_after_deployment_retries_are_exhausted(deployment):
    manager, row, infos, running, root = deployment
    manager.configure(row, infos)
    job = next(iter(manager.jobs.values()))
    role = job["roles"][0]
    runtime = ManagedPipeRuntime(dict(manager._desired(job), role=role["role"])).acquire()
    job.update(state="error", error="deployment failed", deploy_retry_count=5)
    attempts = []

    def deliver(identity, desired):
        attempts.append(desired)
        if len(attempts) == 1:
            raise OSError("test Pipe unavailable")
        return runtime.control(desired)

    manager.runtime_request = deliver
    # A failed/offline process probe must not gate the Pipe handshake either.
    running[0] = False
    try:
        manager.process_once()
        assert not runtime.approved
        manager.process_once()
        assert runtime.approved
        assert len(attempts) == 2
        assert job["state"] == "error"
        assert job["deploy_retry_count"] == 5
    finally:
        runtime.close()


def test_changed_pipe_endpoint_receives_disable_at_its_previous_address(deployment):
    import json
    manager, row, infos, running, root = deployment
    manager.configure(row, infos)
    previous = next(iter(manager.jobs.values()))["roles"][0]["identity"]
    identity_path = Path(infos[0]["path"])
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["channels"]["normal"] = "new.normal"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    running[0] = True
    received = []
    manager.runtime_request = lambda endpoint, desired: received.append((endpoint, desired))
    manager.configure(row, infos)
    assert any(endpoint == previous and desired["enabled"] is False for endpoint, desired in received)
    assert any(endpoint["channels"]["normal"] == "new.normal" and desired["enabled"] for endpoint, desired in received)


def test_init_error_and_inflight_call_retain_ownership_until_exit():
    desc = dict(runtime_key=uuid.uuid4().hex, mode="lite", generation="new", role="normal")
    runtime = ManagedPipeRuntime(desc).acquire()
    entered, finish = threading.Event(), threading.Event()
    def request():
        entered.set()
        finish.wait(3)
    worker = threading.Thread(target=runtime.wrap(request))
    worker.start()
    try:
        assert entered.wait(2)
        runtime.close()
        with pytest.raises(RuntimeError, match="Another"):
            ManagedPipeRuntime(desc).acquire()
    finally:
        finish.set()
        worker.join(3)
        runtime.close()
    replacement = ManagedPipeRuntime(desc).acquire()
    def init(context):
        raise RuntimeError("init failure")
    namespace = {"init": init}
    replacement.bind(namespace)
    with pytest.raises(RuntimeError, match="init failure"):
        namespace["init"](None)
    assert replacement.status()["state"] == "error"
    last = ManagedPipeRuntime(desc).acquire()
    last.close()
