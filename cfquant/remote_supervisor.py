"""Instance-scoped lifecycle operations. Never execute the broad stop scripts."""
import os
from pathlib import Path
import socket
import subprocess
import time

import psutil

from .remote_management import RemoteError


def process_identity(pid):
    try:
        p = psutil.Process(int(pid))
        return {"pid": p.pid, "created": p.create_time(), "exe": p.exe(), "args": p.cmdline()}
    except (psutil.Error, ValueError, TypeError):
        return None


def same_process(identity):
    current = process_identity(identity["pid"])
    return bool(current and current == identity)


def port_busy(port):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


class Supervisor:
    def __init__(self, store, local):
        self.store, self.local = store, local

    def wait_exit(self, identity, timeout=30):
        deadline = time.monotonic()+timeout
        while same_process(identity):
            if time.monotonic() >= deadline:
                raise RemoteError("stop_timeout", "旧进程尚未退出，已停止后续启动")
            time.sleep(0.2)

    def execute(self, task):
        config = self.store.read()
        if not config.get("enabled") or not config.get("permissions", {}).get("service_control"):
            raise RemoteError("permission_denied", "本地未授权服务启停")
        action = task["action"]
        if action not in {"start_cfquant", "restart_cfquant", "stop_cfquant"}:
            raise RemoteError("unsupported_action", "不支持的服务操作")
        launch = config["launch"]
        if action != "start_cfquant" or port_busy(launch["port"]):
            plan = self.local("service-plan", {"boot_id": task["boot_id"]})
            if action == "start_cfquant":
                return {"state": "running", "boot_id": plan["boot_id"], "reused": True}
            # Plan captures only exact, verified instance-owned components.
            identities = plan["processes"]
            if not all(same_process(p) for p in identities):
                raise RemoteError("resource_conflict", "进程身份已变化，请刷新后重试")
            self.store.update(desired_state="stopped")
            self.local("service-stop", {"boot_id": plan["boot_id"]})
            self.wait_exit(identities[0])
            for identity in identities[1:]:
                if same_process(identity):
                    # No taskkill /T: QMT and the independent agent are excluded.
                    psutil.Process(identity["pid"]).terminate()
                    self.wait_exit(identity)
            if action == "stop_cfquant":
                return {"state": "stopped", "qmt_preserved": True}
        current = self.store.read()
        if not current.get("enabled") or not current.get("permissions", {}).get("service_control"):
            raise RemoteError("disabled", "接入已关闭，未启动业务服务")
        self.check_start_resources(launch)
        if port_busy(launch["port"]):
            raise RemoteError("port_conflict", "控制端口仍被占用，未重复启动")
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("CFQUANT_"):
                env.pop(key)
        env.update(launch["env"])
        env["CFQUANT_REMOTE_PRESERVE_QMT"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        kwargs = {"cwd": launch["cwd"], "env": env, "stdin": subprocess.DEVNULL,
                  "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        child = subprocess.Popen(launch["args"], **kwargs)
        self.store.update(desired_state="running")
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RemoteError("service_exited", "服务启动后退出，请查看本地启动日志")
            try:
                result = self.local("snapshot", timeout=3)
                snapshot = result["snapshot"]
                if (result["instance_id"] == config["instance_id"] and snapshot["service_state"] == "running"
                        and snapshot["boot_id"] != task["boot_id"]):
                    return {"state": "running", "boot_id": snapshot["boot_id"], "qmt_preserved": True}
            except RemoteError:
                pass
            time.sleep(0.5)
        raise RemoteError("startup_timeout", "尚未确认服务启动完成，请查看当前状态")

    def check_start_resources(self, launch):
        from .remote_adapter import registry_dir, norm, read_json
        own = launch["resources"]
        known = set()
        for path in registry_dir().glob("*.json"):
            other = read_json(path)
            identity = other.get("process")
            if not identity or not same_process(identity):
                continue
            known.add(identity["pid"])
            if other.get("parent") and same_process(other["parent"]):
                known.add(other["parent"]["pid"])
            if (other.get("config") == norm(self.store.web_config) or own["lttx_port"] == other.get("lttx_port")
                    or own["pipe"] == other.get("pipe")):
                raise RemoteError("resource_conflict", "目标资源已被运行中的部署占用")
        for process in psutil.process_iter(["cmdline"]):
            if process.pid not in known and any(Path(a).name.lower() in {"cfquant_web_server.py", "cfquant_web_server"} for a in process.info.get("cmdline") or []):
                raise RemoteError("resource_conflict", "检测到未登记的部署，无法确认资源隔离")
