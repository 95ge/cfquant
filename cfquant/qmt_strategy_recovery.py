"""Recover the current binding's stopped QMT models through native Qt methods.

No mouse/keyboard events, order calls, whitelist changes, or terminal restarts.
The command line defaults to inspection; --ensure/--watch enable recovery.
"""

from .diagnostic_context import VersionedErrorMixin, versioned_message
from .version import __version__
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from .qmt_component_login import QtLoginBackend, QmtNotReady
from .qmt_native_worker import IsolatedStrategyBackend, QmtAutomationError, StrategyWorkerHost
from .qmt_dependencies import QmtDependencyError, import_login_module
from .qmt_strategy_deploy import (
    _role_stock, _strategy_slot_name, account_qmt_roots,
    _write_json, _digest, PipeStrategyController, normalize_strategy_mode, normalize_strategy_settings, qmt_root,
)


def visible_notice_windows(pid, main_hwnd):
    if os.name != "nt" or not pid or not main_hwnd:
        return []
    win32gui = import_login_module("win32gui")
    win32process = import_login_module("win32process")
    result = []
    def visit(hwnd, _):
        if (hwnd != main_hwnd and win32gui.IsWindowVisible(hwnd)
                and win32process.GetWindowThreadProcessId(hwnd)[1] == pid
                and win32gui.GetClassName(hwnd).startswith("Qt")):
            result.append(hwnd)
    win32gui.EnumWindows(visit, None)
    return result


class RecoveryJournal:
    """Append UTF-8 JSON lines; flush to disk before acknowledging a warning."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.Lock()

    def __call__(self, event):
        stamp = datetime.datetime.now().astimezone()
        event = dict(event, timestamp=stamp.isoformat(timespec="milliseconds"), cfquant_version=__version__)
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / (stamp.strftime("%Y-%m-%d") + ".jsonl")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())


def confirm_recovery_bridge(job, pid):
    controller = PipeStrategyController()
    desired = dict(enabled=True, mode=job["mode"], generation=job["generation"],
                   runtime_key=_digest([os.path.normcase(job["root"]), job["account_id"]])[:24])
    try:
        for role in job["roles"]:
            reply = controller(role["identity"], desired)
            if (reply.get("state") != "running" or reply.get("pid") != pid
                    or reply.get("generation") != job["generation"]
                    or reply.get("role") != role["role"]
                    or reply.get("runtime_key") != desired["runtime_key"]):
                return False
        return True
    finally:
        controller.close()


class UnsupportedQmt(VersionedErrorMixin, RuntimeError):
    pass


class StrategyRecoveryBusy(VersionedErrorMixin, RuntimeError):
    pass


class QtStrategyBackend(QtLoginBackend):
    def __init__(self, root):
        directory = qmt_root(root) / "bin.x64"
        extension = Path(__file__).with_name("qmt_strategy_agent.js").read_text(encoding="utf-8")
        super().__init__(directory, agent_extension=extension, strategy=True)
        try:
            if not self.already_logged_in():
                raise QmtNotReady("QMT 尚未登录，等待主界面")
            self.capabilities = self.api.strategycapabilities()
            if not self.capabilities.get("can_query"):
                raise UnsupportedQmt("QMT 缺少策略运行检测接口: " + ", ".join(self.capabilities.get("missing_query", [])))
        except Exception:
            self.close()
            raise

    def snapshot(self):
        return self.api.strategystatus(str(self.main_hwnd))["result"]

    def start_strategy(self, expected):
        return self.api.strategystart(str(self.main_hwnd), expected)["result"]

    def notices(self):
        if not self.capabilities.get("can_read_notices"):
            return []
        result = []
        for hwnd in visible_notice_windows(self.pid, self.main_hwnd):
            notice = self.api.illegalipnotice(str(hwnd))["result"]
            if notice:
                result.append(notice)
        return result

    def dismiss_notice(self, notice, expected):
        return self.api.dismissillegalip(str(self.main_hwnd), notice["hwnd"], notice["text"], expected)["result"]


def expected_models(job, accounts):
    """Build an exact allowlist from the CURRENT binding and deployed job."""
    row = accounts.get(job.get("account_key")) or {}
    settings = normalize_strategy_settings(row.get("qmt_strategy"))
    if (not row or not row.get("enabled", True) or not job.get("enabled")
            or not settings["enabled"] or not settings["autorun"]
            or str(row.get("account_id")) != job.get("account_id")
            or normalize_strategy_mode(row.get("mode")) != job.get("mode")
            or os.path.normcase(str(qmt_root(job["root"]))) not in account_qmt_roots(row)
            or settings != job.get("settings")
            or job.get("control_generation") or job.get("accepted_generations")):
        return []
    expected = []
    for role in job.get("roles", []):
        name = _strategy_slot_name(job["account_id"], job["mode"], role["role"])
        if (role.get("name") != name or not role.get("model_prepared")
                or role.get("reimport_required") or not role.get("model_id")
                or not role.get("resolved_account_key")):
            return []
        expected.append({
            "id": str(role["model_id"]), "name": name, "account": job["account_id"],
            "m_strAccountKey": role["resolved_account_key"],
            "runMode": "1" if settings["live"] else "0", "startupAutorun": "1",
            "eStrategyType": "4", "stock": _role_stock(settings, role["role"]),
            "peroid": str(settings["period"]),
        })
    return expected


def match_models(snapshot, expected):
    matched = []
    for target in expected:
        candidates = [item for item in snapshot["models"] if item.get("name") == target["name"]]
        if len(candidates) != 1 or any(candidates[0].get(k) != v for k, v in target.items()):
            raise ValueError("QMT 内存策略与当前绑定不一致: " + target["name"])
        matched.append(candidates[0])
    return matched


class QmtStrategyRecovery:
    def __init__(self, accounts_provider, *, backend_factory=None,
                 job_is_current=lambda job: True, clock=time.time, interval=20.0,
                 notice_probe=visible_notice_windows, event_sink=None, bridge_verifier=confirm_recovery_bridge):
        self.accounts_provider = accounts_provider
        self._worker_host = StrategyWorkerHost() if backend_factory is None else None
        self.backend_factory = backend_factory or self._worker_host
        self.job_is_current = job_is_current
        self.clock = clock
        self.interval = interval
        self.notice_probe = notice_probe
        self.event_sink = event_sink or RecoveryJournal(Path("runtime/logs/qmt_strategy_recovery"))
        self.bridge_verifier = bridge_verifier

    def close(self):
        if self._worker_host is not None:
            self._worker_host.close()

    def _event(self, job, status, event, **details):
        self.event_sink(dict(event=event, account_id=job["account_id"], account_key=job["account_key"],
                             mode=job["mode"], pid=status.get("pid"), generation=job["generation"],
                             event_id=(status.get("incident") or {}).get("id"), **details))

    def _notices(self, job, status, backend, expected):
        try:
            notices = backend.notices()
            status.pop("notice_error", None)
        except Exception as error:
            # An optional broker-specific message widget must not disable
            # the independently supported strategy-state query.
            status["notice_error"] = str(error)
            return
        for notice in notices:
            if expected_models(job, self.accounts_provider()) != expected or not self.job_is_current(job):
                raise ValueError("Binding changed before warning dismissal")
            incident = status.get("incident") or {}
            if (incident.get("text") != notice["text"] or incident.get("hwnd") != notice["hwnd"]
                    or incident.get("dismissed") or incident.get("handled")):
                incident = dict(id=uuid.uuid4().hex, text=notice["text"], hwnd=notice["hwnd"], detected_at=self.clock())
                # Detection must be durably recorded before dismissing the popup.
                status["incident"] = incident
            if not incident.get("recorded"):
                self._event(job, status, "illegal_ip_detected", message=notice["text"])
                incident["recorded"] = True
            outcome = backend.dismiss_notice(notice, expected)
            self._event(job, status, "illegal_ip_popup_result", **outcome)
            incident["dismissed"] = outcome.get("closed") is True
            incident["dismissal"] = outcome["outcome"]
            status["next_check_at"] = self.clock() + 1

    def _confirm_incident(self, job, status, backend, expected):
        incident = status.get("incident") or {}
        if not incident or incident.get("handled"):
            return
        status["next_check_at"] = self.clock() + (1 if self.clock() - incident["detected_at"] < 60 else self.interval)
        if expected_models(job, self.accounts_provider()) != expected or not self.job_is_current(job):
            return
        models = match_models(backend.snapshot(), expected)
        if not all(model["running"] for model in models):
            return
        try:
            confirmed = self.bridge_verifier(job, backend.pid)
        except Exception as error:
            status["bridge_error"] = str(error)
            return
        status["bridge_confirmed"] = confirmed
        if confirmed:
            status.pop("bridge_error", None)
        if confirmed and incident.get("dismissed"):
            self._event(job, status, "illegal_ip_handled", message="非法 IP 弹窗已关闭，绑定策略及通信恢复成功",
                        strategies=[model["name"] for model in models], popup_closed=True, bridge_confirmed=True)
            incident["handled"] = True
            status.update(state="running", strategies=[{"name": m["name"], "running": True} for m in models])
            status["next_check_at"] = self.clock() + self.interval

    def __call__(self, job, *, inspect_only=False, immediate=False):
        now = self.clock()
        expected = expected_models(job, self.accounts_provider())
        if not expected or not self.job_is_current(job):
            row = self.accounts_provider().get(job.get("account_key")) or {}
            settings = row.get("qmt_strategy") or {}
            if not row:
                reason, message = "binding_unavailable", "当前绑定不可用，或服务已禁止策略自动恢复"
            elif not row.get("enabled", True) or not job.get("enabled"):
                reason, message = "binding_disabled", "账号绑定或策略部署已禁用"
            elif not settings.get("enabled") or not settings.get("autorun"):
                reason, message = "automation_disabled", "请先开启自动导入策略和策略自动运行"
            elif (job.get("control_generation") or job.get("accepted_generations")
                  or any(not role.get("model_prepared") or role.get("reimport_required")
                         for role in job.get("roles", []))):
                reason, message = "deployment_pending", "策略部署尚未完成，请先完成对应 QMT 的导入和模型配置"
            else:
                reason, message = "binding_changed", "策略部署与当前绑定不一致，请检查绑定配置"
            job["recovery"] = {"state": "ineligible", "reason": reason, "message": message, "last_checked_at": now}
            return job["recovery"]
        previous = job.get("recovery") or {}
        if (not inspect_only and (not immediate or previous.get("native_failure"))
                and now < previous.get("next_check_at", 0)
                and (previous.get("native_failure")
                     or not self.notice_probe(previous.get("pid"), previous.get("main_hwnd")))):
            return previous
        status = dict(previous, last_checked_at=now, next_check_at=now + self.interval)
        status.pop("error", None)
        status.pop("native_failure", None)
        backend = None
        try:
            backend = self.backend_factory(job["root"])
            if (status.get("pid"), status.get("generation")) != (backend.pid, job["generation"]):
                status = {"last_checked_at": now, "next_check_at": now + self.interval,
                          "pid": backend.pid, "generation": job["generation"], "attempts": {}}
            snapshot = backend.snapshot()
            models = match_models(snapshot, expected)
            status["capabilities"] = snapshot.get("capabilities") or {}
            status["main_hwnd"] = getattr(backend, "main_hwnd", None)
            if not inspect_only:
                self._notices(job, status, backend, expected)
            status["strategies"] = [{"name": item["name"], "running": item["running"]} for item in models]
            status["bridge_confirmed"] = all(item["running"] for item in models) and all(
                (role.get("control_sync") or {}).get("pid") == backend.pid
                and (role.get("control_sync") or {}).get("state") == "running"
                and 0 <= now - (role.get("control_sync") or {}).get("last_success_at", 0) < 10
                for role in job["roles"])
            stopped = [target for target, model in zip(expected, models) if not model["running"]]
            if not stopped:
                status["state"] = "running"
                if status["bridge_confirmed"]:
                    status.setdefault("stable_since", now)
                    if now - status["stable_since"] >= 300:
                        status["attempts"] = {}
                else:
                    status.pop("stable_since", None)
            else:
                status.pop("stable_since", None)
                status["state"] = "stopped"
                if not inspect_only and status["capabilities"].get("can_start") is False:
                    status["state"] = "detection_only"
                elif not inspect_only:
                    attempts = dict(status.get("attempts") or {})
                    status["attempts"] = attempts
                    if any(attempts.get(target["name"], 0) >= 5 for target in stopped):
                        status["state"] = "retry_exhausted"
                    elif now < status.get("retry_after", 0):
                        status["state"] = "backoff"
                    else:
                        for target in stopped:
                            # Re-check the binding after attach/observation and before each start.
                            if (expected_models(job, self.accounts_provider()) != expected
                                    or not self.job_is_current(job)):
                                status["state"] = "binding_changed"
                                break
                            count = attempts.get(target["name"], 0) + 1
                            attempts[target["name"]] = count
                            status["retry_after"] = now + min(300, 60 * 2 ** (count - 1))
                            # Reserve the attempt before a call that may time out ambiguously.
                            job["recovery"] = status
                            outcome = backend.start_strategy(target)
                            status["state"] = outcome["outcome"]
                            if outcome.get("requested"):
                                status["last_started_at"] = now
                                self._event(job, status, "strategy_start_requested", strategy=target["name"])
                            else:
                                attempts[target["name"]] -= 1
                                status["retry_after"] = now
            if not inspect_only:
                self._confirm_incident(job, status, backend, expected)
                if status.get("state") in ("retry_exhausted", "backoff") and status.get("incident"):
                    if status.get("last_logged_state") != status["state"]:
                        self._event(job, status, "illegal_ip_recovery_pending", state=status["state"])
                        status["last_logged_state"] = status["state"]
        except Exception as error:
            status.update(state="unsupported" if isinstance(error, UnsupportedQmt) else "unavailable",
                          error=str(error), next_check_at=now + max(self.interval, 60))
            status["native_failure"] = isinstance(error, (QmtAutomationError, QmtDependencyError))
            if status.get("incident") and status.get("last_logged_error") != str(error):
                try:
                    self._event(job, status, "illegal_ip_processing_failed", error=str(error))
                    status["last_logged_error"] = str(error)
                except OSError:
                    pass  # Preserve the original journal failure in status; never claim success.
        finally:
            if backend is not None:
                backend.close()
        job["recovery"] = status
        return status


class QmtStrategyRecoveryScheduler:
    """Separate worker: native GUI waits must not delay the Pipe control loop."""
    def __init__(self, manager, accounts_provider, report_path, interval=20.0):
        self.manager = manager
        self.accounts_provider = accounts_provider
        self.report_path = Path(report_path)
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.states = {}
        try:
            self.states = json.loads(self.report_path.read_text(encoding="utf-8")).get("targets", {})
        except (OSError, ValueError):
            pass
        self.recovery = QmtStrategyRecovery(accounts_provider, job_is_current=self._current, interval=interval,
            event_sink=RecoveryJournal(self.report_path.parent.parent / "logs/qmt_strategy_recovery"))

    def _current(self, job):
        if self.stop_event.is_set():
            return False
        with self.manager.lock:
            accounts = self.accounts_provider()
            return any(item.get("account_key") == job["account_key"]
                       and item.get("root") == job["root"]
                       and item.get("generation") == job["generation"]
                       and expected_models(item, accounts) == expected_models(job, accounts)
                       for item in self.manager.jobs.values())

    def run_once(self):
        # HTTP recovery and the scheduled pass share attempts and native calls.
        if not self.run_lock.acquire(blocking=False):
            return
        try:
            with self.manager.lock:
                jobs = copy.deepcopy(self.manager.jobs)
            self._run_jobs(jobs, replace=True)
        finally:
            self.run_lock.release()

    def recover_now(self, account_key):
        if self.stop_event.is_set() or not self.run_lock.acquire(blocking=False):
            raise StrategyRecoveryBusy("策略检测或恢复正在执行，请稍后查询状态或重试")
        try:
            with self.manager.lock:
                jobs = {key: copy.deepcopy(job) for key, job in self.manager.jobs.items()
                        if job.get("account_key") == account_key}
            if not jobs:
                raise ValueError("该账号没有托管策略部署任务")
            # Retired roots/modes remain in the deployment history. They must
            # not turn a successful current binding into a partial result.
            enabled_jobs = {key: job for key, job in jobs.items() if job.get("enabled")}
            if enabled_jobs:
                jobs = enabled_jobs
            result = self._run_jobs(jobs, immediate=True)
            targets = [dict(root=jobs[key]["root"], generation=jobs[key]["generation"], recovery=value)
                       for key, value in result.items()]
            states = {target["recovery"].get("state") for target in targets}
            running = bool(targets) and states == {"running"}
            requested = "start_requested" in states
            return {"account_key": account_key, "checked_at": time.time(), "targets": targets,
                    "state": next(iter(states)) if len(states) == 1 else "partial",
                    "running": running, "start_requested": requested,
                    "bridge_confirmed": running and all(target["recovery"].get("bridge_confirmed", False)
                                                        for target in targets)}
        finally:
            self.run_lock.release()

    def _run_jobs(self, jobs, *, immediate=False, replace=False):
        with self.lock:
            states = copy.deepcopy(self.states)
        result = {}
        for key, job in jobs.items():
            if self.stop_event.is_set():
                result[key] = {"state": "cancelled", "message": "服务正在停止，本目标未执行恢复",
                               "last_checked_at": time.time()}
                continue
            job["recovery"] = states.get(key, {})
            try:
                result[key] = self.recovery(job, immediate=immediate)
            except Exception as error:
                result[key] = dict(job["recovery"], state="unavailable", error=str(error))
        with self.lock:
            if replace:
                self.states = result
            else:
                self.states.update(result)
            saved = copy.deepcopy(self.states)
        _write_json(self.report_path, {"checked_at": time.time(), "targets": saved})
        return result

    def decorate(self, account_key, status):
        status = copy.deepcopy(status)
        with self.manager.lock:
            keys = {job["root"]: (key, job.get("generation")) for key, job in self.manager.jobs.items()
                    if job.get("account_key") == account_key}
        with self.lock:
            for target in status.get("targets", []):
                key, generation = keys.get(target.get("root"), (None, None))
                recovery = copy.deepcopy(self.states.get(key, {}))
                if (recovery.get("generation") not in (None, generation)
                        or time.time() - recovery.get("last_checked_at", 0) > 120):
                    recovery = {}
                target["recovery"] = recovery
                state = recovery.get("state")
                if state in ("start_requested", "backoff", "retry_exhausted"):
                    target["state"] = "waiting_start"
                    target["message"] = {
                        "start_requested": "已检测到托管策略停止，已直接提交启动，等待通道恢复",
                        "backoff": "托管策略尚未恢复，等待冷却后重试",
                        "retry_exhausted": "托管策略连续启动失败，已暂停重试，请检查 QMT 提示",
                    }[state]
                elif state == "detection_only":
                    target["state"] = "waiting_manual_start"
                    target["message"] = "已检测到托管策略停止，当前 QMT 缺少自动恢复接口，请手动启动策略"
                elif state == "unsupported" and target.get("state") != "running":
                    target["message"] = recovery.get("error", "当前 QMT 缺少策略运行检测接口")
        return status

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def run():
            while not self.stop_event.is_set():
                try:
                    self.run_once()
                except Exception:
                    pass  # Transient config/status IO failures retry on the next interval.
                self.stop_event.wait(1.0)
        self.thread = threading.Thread(target=run, name="qmt-strategy-recovery", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.recovery.close()
        if self.thread:
            self.thread.join(timeout=2)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--config", type=Path, default=Path("runtime/config/cfquant_web_config.json"))
    parser.add_argument("--jobs", type=Path, default=Path("runtime/config/qmt_strategy_jobs.json"))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--ensure", action="store_true")
    action.add_argument("--watch", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--parent-pid", type=int, help="Stop the temporary watcher when this Web process exits")
    args = parser.parse_args()

    def accounts():
        return json.loads(args.config.read_text(encoding="utf-8"))["account_configs"]

    def jobs():
        return json.loads(args.jobs.read_text(encoding="utf-8"))["jobs"]

    def current(job):
        return any(item.get("account_key") == job["account_key"]
                   and item.get("root") == job["root"]
                   and item.get("generation") == job["generation"]
                   and item.get("enabled")
                   and expected_models(item, accounts()) == expected_models(job, accounts())
                   for item in jobs().values())

    parent = None
    if args.parent_pid:
        import psutil
        parent = psutil.Process(args.parent_pid)
    recovery = QmtStrategyRecovery(accounts, job_is_current=lambda job: (
        (parent is None or parent.is_running()) and current(job)),
        event_sink=RecoveryJournal(args.config.parent.parent / "logs/qmt_strategy_recovery"))
    try:
        states = {}
        if args.report and args.report.exists():
            states = json.loads(args.report.read_text(encoding="utf-8")).get("targets", {})
        while True:
            if parent is not None and not parent.is_running():
                return 0
            output = {"account_id": args.account_id, "checked_at": time.time(), "targets": {},
                      "cfquant_version": __version__}
            try:
                for key, original in jobs().items():
                    if original.get("account_id") != args.account_id:
                        continue
                    job = copy.deepcopy(original)
                    if key in states:
                        job["recovery"] = states[key]
                    result = recovery(job, inspect_only=not (args.ensure or args.watch))
                    output["targets"][key] = result
            except Exception as error:
                if not args.watch:
                    raise
                output.update(targets=states, error=versioned_message(error))
            states = output["targets"]
            text = json.dumps(output, ensure_ascii=False, indent=2)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.report.with_suffix(".pending")
                temporary.write_text(text, encoding="utf-8")
                temporary.replace(args.report)
            if not args.watch:
                print(text)
                return 0 if states and all(s["state"] in ("running", "start_requested") for s in states.values()) else 1
            time.sleep(1)
    finally:
        recovery.close()


if __name__ == "__main__":
    sys.exit(main())
