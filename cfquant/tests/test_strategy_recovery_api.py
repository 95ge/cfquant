"""Real HTTP/SDK recovery with synthetic QMT models and no terminal operations."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace

import pytest

from cfquant.management import ManagementError, RuntimeManager
from cfquant.qmt_native_worker import QmtAutomationError
from cfquant.qmt_strategy_recovery import QmtStrategyRecoveryScheduler
from cfquant.tests.test_management import service
from cfquant.tests.test_qmt_strategy_recovery import recovery_case


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("CFQUANT_RUNTIME_DIR", str(tmp_path / "runtime"))


@pytest.fixture
def recovery_api(service, recovery_case, monkeypatch, tmp_path):
    _, backend, calls, now, job, accounts = recovery_case
    accounts["binding"].update(account_type="STOCK", bridge_id="test")
    service.config._data["account_configs"] = accounts
    manager = SimpleNamespace(lock=threading.RLock(), jobs={"target": job})
    scheduler = QmtStrategyRecoveryScheduler(manager, lambda: accounts if
        service.web.management_qmt_start_policy() is not False else {}, tmp_path / "recovery.json")
    scheduler.recovery.backend_factory = lambda root: backend
    scheduler.recovery.clock = lambda: now[0]
    scheduler.recovery.notice_probe = lambda *args: False
    scheduler.recovery.event_sink = lambda event: None
    monkeypatch.setattr(service.web, "QMT_STRATEGY_RECOVERY", scheduler)
    return SimpleNamespace(service=service, sdk=service.runtime.accounts, backend=backend,
                           calls=calls, now=now, job=job, accounts=accounts, scheduler=scheduler)


@pytest.mark.parametrize("entry", ["runtime", "accounts"])
def test_sdk_recovers_stopped_model_and_distinguishes_submission_from_running(recovery_api, entry):
    case = recovery_api
    recover = (case.service.runtime if entry == "runtime" else case.sdk).recover_strategy
    result = recover("TEST001", account_type="stock", bridge_id="test")
    assert result["account_key"] == "binding" and result["state"] == "start_requested"
    assert result["start_requested"] and not result["running"] and not result["bridge_confirmed"]
    assert [item["name"] for item in case.calls] == ["CFQ_TEST001_LITE"]
    assert result["targets"][0]["recovery"]["attempts"] == {"CFQ_TEST001_LITE": 1}
    case.backend.models[0]["running"] = True
    result = recover(account_key="binding")
    assert result["running"] and result["bridge_confirmed"] and not result["start_requested"]
    assert len(case.calls) == 1


def test_runtime_recovery_checks_managed_home_before_controlling_another_instance(recovery_api, tmp_path):
    case = recovery_api
    case.service.config.set_api_key("fixture-api-key")
    other = RuntimeManager(tmp_path / "another-service", port=case.service.server.server_port,
                           api_key="fixture-api-key")
    with pytest.raises(ManagementError) as error:
        other.recover_strategy("TEST001")
    assert error.value.code == "instance_mismatch" and not case.calls


def test_immediate_request_rechecks_cached_running_state_without_waiting_for_poll(recovery_api):
    case = recovery_api
    case.backend.models[0]["running"] = True
    case.scheduler.run_once()
    case.backend.models[0]["running"] = False
    assert case.sdk.recover_strategy("TEST001")["start_requested"]
    assert len(case.calls) == 1


def test_http_recovery_preserves_backoff_retry_limit_and_other_account_state(recovery_api):
    case = recovery_api
    case.scheduler.states["other"] = {"state": "running", "attempts": {"other": 2}}
    assert case.sdk.recover_strategy("TEST001")["start_requested"]
    assert case.sdk.recover_strategy("TEST001")["state"] == "backoff"
    assert len(case.calls) == 1
    case.scheduler.states["target"]["attempts"]["CFQ_TEST001_LITE"] = 5
    assert case.sdk.recover_strategy("TEST001")["state"] == "retry_exhausted"
    assert len(case.calls) == 1
    persisted = json.loads(case.scheduler.report_path.read_text(encoding="utf-8"))
    assert persisted["targets"]["other"] == {"state": "running", "attempts": {"other": 2}}
    assert persisted["targets"]["target"]["attempts"]["CFQ_TEST001_LITE"] == 5


def test_manual_request_keeps_native_failure_cooldown(recovery_api):
    case = recovery_api
    attaches = []
    def fail(root):
        attaches.append(root)
        raise QmtAutomationError("fixture native failure")
    case.scheduler.recovery.backend_factory = fail
    assert case.sdk.recover_strategy("TEST001")["state"] == "unavailable"
    assert case.sdk.recover_strategy("TEST001")["state"] == "unavailable"
    assert len(attaches) == 1 and not case.calls


@pytest.mark.parametrize("condition,reason", [
    ("disabled", "binding_disabled"), ("manual", "automation_disabled"),
    ("pending", "deployment_pending"), ("policy", "binding_unavailable"),
])
def test_recovery_reports_ineligible_reason_without_attaching(recovery_api, monkeypatch, condition, reason):
    case = recovery_api
    if condition == "disabled": case.accounts["binding"]["enabled"] = False
    if condition == "manual": case.accounts["binding"]["qmt_strategy"]["autorun"] = False
    if condition == "pending": case.job["roles"][0]["reimport_required"] = True
    if condition == "policy": monkeypatch.setenv("CFQUANT_QMT_AUTO_START", "0")
    case.scheduler.recovery.backend_factory = lambda root: pytest.fail("must not attach")
    result = case.sdk.recover_strategy(account_key="binding")
    state = result["targets"][0]["recovery"]
    assert result["state"] == "ineligible" and state["reason"] == reason and state["message"]
    assert not result["running"] and not result["start_requested"] and not case.calls


def test_account_lookup_requires_unique_consistent_selectors(recovery_api):
    case = recovery_api
    case.accounts["other"] = dict(case.accounts["binding"], account_key="other", bridge_id="other")
    for selector in ({"account_id": "TEST001"},
                     {"account_id": "TEST001", "account_key": "missing"},
                     {"account_key": "binding", "bridge_id": "other"}):
        with pytest.raises(ManagementError) as error:
            case.sdk.recover_strategy(**selector)
        assert error.value.status == 400
    assert not case.calls
    assert case.sdk.recover_strategy("TEST001", bridge_id="test")["start_requested"]


@pytest.mark.parametrize("body", [{}, {"account_id": ""}, {"account_id": 123},
                                 {"account_key": None}, {"bridge_id": "test"}, []])
def test_bad_http_selectors_cannot_default_to_an_account(recovery_api, body):
    with pytest.raises(ManagementError) as error:
        recovery_api.service.runtime._request("POST", "/api/qmt/strategies/recover", body)
    assert error.value.status == 400 and not recovery_api.calls


def test_endpoint_requires_auth_even_when_web_auth_and_api_key_are_disabled(recovery_api, monkeypatch):
    case = recovery_api
    monkeypatch.delenv("CFQUANT_MANAGEMENT_TOKEN_FILE")
    case.service.config._data["web_auth_enabled"] = False
    case.service.config._data["api_key"] = ""
    external = RuntimeManager(base_url=case.service.runtime.base_url)
    with pytest.raises(ManagementError) as error:
        external.recover_strategy("TEST001")
    assert error.value.status == 401 and not case.calls
    case.service.config.set_api_key("fixture-api-key")
    external.api_key = "fixture-api-key"
    assert external.recover_strategy("TEST001")["start_requested"]


def test_request_and_background_pass_cannot_start_the_same_model_concurrently(recovery_api):
    case = recovery_api
    entered, release = threading.Event(), threading.Event()
    snapshot = case.backend.snapshot
    def slow_snapshot():
        entered.set()
        assert release.wait(5)
        return snapshot()
    case.backend.snapshot = slow_snapshot
    with ThreadPoolExecutor() as pool:
        first = pool.submit(case.sdk.recover_strategy, "TEST001")
        try:
            assert entered.wait(5)
            case.scheduler.run_once()
            with pytest.raises(ManagementError) as error:
                case.sdk.recover_strategy("TEST001")
            assert error.value.status == 409 and error.value.code == "strategy_recovery_busy"
        finally:
            release.set()
        assert first.result(timeout=5)["start_requested"]
    assert len(case.calls) == 1


def test_binding_change_during_http_query_prevents_start(recovery_api):
    case = recovery_api
    snapshot = case.backend.snapshot
    def changed():
        case.job["generation"] = "replacement"
        return snapshot()
    case.backend.snapshot = changed
    assert case.sdk.recover_strategy("TEST001")["state"] == "binding_changed"
    assert not case.calls


def test_project_update_blocks_request_before_native_work(recovery_api, monkeypatch):
    case = recovery_api
    monkeypatch.setattr(case.service.web.PROJECT_UPDATER, "is_busy", lambda: True)
    with pytest.raises(ManagementError) as error:
        case.sdk.recover_strategy("TEST001")
    assert error.value.status == 409 and error.value.code == "project_update_busy"
    assert not case.calls


def test_missing_deployment_is_an_explicit_error(recovery_api):
    recovery_api.scheduler.manager.jobs.clear()
    with pytest.raises(ManagementError) as error:
        recovery_api.sdk.recover_strategy("TEST001")
    assert error.value.status == 400 and not recovery_api.calls


def test_retired_mode_does_not_make_current_binding_recovery_partial(recovery_api):
    case = recovery_api
    retired = copy.deepcopy(case.job)
    retired.update(enabled=False, mode="lttx", root=retired["root"] + "-retired")
    case.scheduler.manager.jobs["retired"] = retired
    case.scheduler.states["retired"] = {"state": "ineligible", "reason": "binding_disabled"}
    case.backend.models[0]["running"] = True
    result = case.service.runtime.recover_strategy("TEST001")
    assert result["state"] == "running" and result["running"] and result["bridge_confirmed"]
    assert len(result["targets"]) == 1 and result["targets"][0]["root"] == case.job["root"]
    assert case.scheduler.states["retired"]["reason"] == "binding_disabled"
    assert not case.calls


def test_disabled_deployment_still_reports_why_recovery_is_ineligible(recovery_api):
    case = recovery_api
    case.job["enabled"] = False
    result = case.service.runtime.recover_strategy("TEST001")
    assert result["state"] == "ineligible"
    assert result["targets"][0]["recovery"]["reason"] == "binding_disabled"
    assert not case.calls


def test_shutdown_mid_request_does_not_report_unchecked_targets_as_running(recovery_api):
    case = recovery_api
    second = copy.deepcopy(case.job)
    second["root"] += "-other-terminal"
    case.scheduler.manager.jobs["second"] = second
    case.backend.models[0]["running"] = True
    recover = case.scheduler.recovery
    def stop_after_first(*args, **kwargs):
        result = recover(*args, **kwargs)
        case.scheduler.stop_event.set()
        return result
    case.scheduler.recovery = stop_after_first
    result = case.sdk.recover_strategy("TEST001")
    assert result["state"] == "partial" and not result["running"]
    assert [target["recovery"]["state"] for target in result["targets"]] == ["running", "cancelled"]
    assert not case.calls
