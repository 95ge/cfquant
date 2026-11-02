"""Optional outbound management agent, independent of the local web process.

Credentials and launch settings use Windows DPAPI. Remote tasks are journaled
before execution; an interrupted task is reconciled or reported as unknown.
"""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .qmt_credentials import _protect, _unprotect

VERSION = "1"
PREFIX = "/api/remote/v1"
ACTIONS = {"positions": "queries", "orders": "queries", "trades": "queries",
           "start_cfquant": "service_control", "restart_cfquant": "service_control",
           "stop_cfquant": "service_control", "restart_qmt": "qmt_control"}
FINAL = {"succeeded", "failed", "expired", "cancelled", "outcome_unknown"}


class RemoteError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as out:
            json.dump(data, out, ensure_ascii=False, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(str(temp), str(path))
    finally:
        if temp.exists():
            temp.unlink()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@contextmanager
def file_lock(path, wait=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    acquired = False
    deadline = time.monotonic()+wait
    try:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RemoteError("resource_busy", "已有任务正在操作此部署") from None
                time.sleep(0.1)
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


class Config:
    def __init__(self, web_config):
        self.web_config = Path(web_config).resolve()
        prefix = self.web_config.stem + ".remote_management"
        self.path = self.web_config.with_name(prefix+".secure.json")
        self.status_path = self.web_config.with_name(prefix+".status.json")
        self.lock_path = self.web_config.with_name(prefix+".agent.lock")

    def read(self):
        if not self.path.exists():
            return {"enabled": False, "permissions": {}}
        try:
            encrypted = read_json(self.path)["protected"]
            raw = _unprotect(base64.b64decode(encrypted), str(self.path).encode("utf-8"))
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise RemoteError("credential_unavailable", "无法解密远程接入配置，请使用保存配置的 Windows 用户") from None

    def save(self, data):
        try:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            protected = _protect(raw, str(self.path).encode("utf-8"))
        except Exception:
            raise RemoteError("credential_unavailable", "无法加密接入凭据，请检查 Windows 用户与 pywin32 依赖") from None
        atomic_json(self.path, {"protected": base64.b64encode(protected).decode("ascii")})

    def update(self, **updates):
        with file_lock(self.path.with_suffix(".lock"), wait=10):
            data = self.read()
            data.update(updates)
            self.save(data)
            return data


def site_url():
    # Administrator-controlled override for isolated testing/private deployment.
    # Browser form data cannot redirect project keys to arbitrary endpoints.
    url = os.environ.get("CFQUANT_REMOTE_SITE_URL", "https://cfquant.org").rstrip("/")
    p = urllib.parse.urlparse(url)
    if p.username or p.password or p.query or p.fragment or p.path or not p.hostname:
        raise RemoteError("invalid_site", "官网地址配置无效")
    if p.scheme != "https" and not (p.scheme == "http" and p.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise RemoteError("invalid_site", "远程接入必须使用 HTTPS")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RemoteError("redirect_refused", "远程接口返回了重定向，已停止发送凭据")


def request_json(url, body=None, headers=None, timeout=15, local=False):
    headers = dict(headers or {})
    data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    headers["Content-Type"] = "application/json"
    handlers = [NoRedirect()]
    if local:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        response = opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as error:
        with error:
            try:
                payload = json.loads(error.read(600001).decode("utf-8"))
                code = str(payload.get("code") or "request_rejected")[:80]
                message = str(payload.get("error") or "请求被拒绝，请检查接入凭据、权限或任务状态")[:300]
            except (ValueError, UnicodeError, TypeError, AttributeError):
                code = "request_rejected"
                message = "请求被拒绝，请检查接入凭据、权限或任务状态"
        raise RemoteError(code, message) from None
    except (OSError, urllib.error.URLError):
        raise RemoteError("connection_failed", "无法连接服务，请检查网络与服务状态") from None
    with response:
        raw = response.read(600001)
    if len(raw) > 600000:
        raise RemoteError("result_too_large", "响应过大")
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ValueError()
        return payload
    except (ValueError, UnicodeError):
        raise RemoteError("invalid_response", "服务响应无效") from None


def local_info(web_config):
    store = Config(web_config)
    try:
        data = store.read()
    except RemoteError as error:
        return {"enabled": False, "configured": True, "connected": False,
                "state": "credential_unavailable", "error_code": error.code, "permissions": {}}
    status = read_json(store.status_path)
    if status.get("instance_id") != data.get("instance_id"):
        status = {}
    connected = data.get("enabled") and status.get("state") == "connected" and time.time()-status.get("time", 0) < 60
    return {"enabled": bool(data.get("enabled")), "configured": bool(data.get("api_key")),
            "site_url": data.get("site_url") or site_url(), "instance_id": data.get("instance_id", ""), "name": status.get("name", data.get("name", "")),
            "note": status.get("note", data.get("note", "")), "key_prefix": data.get("api_key", "")[:12],
            "permissions": data.get("permissions", {}), "connected": bool(connected),
            "state": "disabled" if not data.get("enabled") else "disconnected" if status.get("state") == "connected" and not connected else status.get("state", "connecting"),
            "error_code": status.get("error_code", ""), "last_contact": status.get("time", 0)}


def ensure_agent(web_config):
    store = Config(web_config)
    if not store.read().get("enabled"):
        return {"started": False}
    try:
        with file_lock(store.lock_path):
            pass
    except RemoteError:
        return {"started": False, "already_running": True}
    # The child takes the same OS lock before doing anything; concurrent spawns
    # cannot create two active agents, and PID reuse cannot impersonate a lock.
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "cwd": str(Path(__file__).resolve().parents[1])}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    child = subprocess.Popen([sys.executable, "-m", "cfquant.remote_management", "--config", str(store.web_config)], **kwargs)
    return {"started": True, "pid": child.pid}


class RemoteAgent:
    def __init__(self, web_config):
        self.store = Config(web_config)
        self.stop = threading.Event()
        self.session_token = secrets.token_urlsafe(32)
        self.session_id = ""
        self.worker = None
        self.permissions = {}
        self.last_snapshot = {}
        self.config_generation = ""
        self.instance_id = ""
        self.journal = self.store.path.with_suffix(".tasks.sqlite3")
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT NOT NULL, updated REAL NOT NULL)")

    def db(self):
        c = sqlite3.connect(str(self.journal), timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def save_task(self, tid, state, result=None):
        raw = json.dumps(result or {}, ensure_ascii=False).encode("utf-8")
        encrypted = base64.b64encode(_protect(raw, (str(self.journal)+tid).encode("utf-8"))).decode("ascii")
        with self.db() as c:
            c.execute("INSERT OR REPLACE INTO tasks VALUES(?,?,?,?)", (tid, state, encrypted, time.time()))
            c.execute("DELETE FROM tasks WHERE updated<?", (time.time()-90*86400,))

    def cloud(self, op, body=None):
        data = self.store.read()
        if not data.get("enabled"):
            raise RemoteError("disabled", "远程接入已关闭")
        return request_json(data["site_url"]+PREFIX+"/agent/"+op,
                            dict(body or {}, instance_id=data["instance_id"], session_token=self.session_token),
                            {"X-CFQuant-Remote-Key": data["api_key"]})

    def local(self, op, body=None, timeout=15):
        config = self.store.read()
        return request_json(config["local_url"]+"/api/remote-agent/"+op, body,
                            {"X-CFQuant-Agent-Key": config["local_token"]}, timeout, local=True)["data"]

    def snapshot(self):
        config = self.store.read()
        try:
            result = self.local("snapshot", timeout=10)
            if result.get("instance_id") != config["instance_id"]:
                raise RemoteError("identity_conflict", "本地服务身份发生变化")
            self.last_snapshot = result["snapshot"]
        except RemoteError as error:
            state = "stopped" if config.get("desired_state") == "stopped" else "unavailable"
            self.last_snapshot = dict(self.last_snapshot, service_state=state, checked_at=time.time(), boot_id="", bindings=[])
        result = dict(self.last_snapshot, agent_version=VERSION, permissions=config.get("permissions", {}))
        result["capabilities"] = [a for a in ACTIONS if config.get("permissions", {}).get(ACTIONS[a]) and
                                  (result.get("service_state") == "running" or a == "start_cfquant")]
        return result

    def run_task(self, task):
        tid = task["id"]
        try:
            with self.db() as c:
                previous = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            if previous or task["state"] == "running":
                if previous and previous["state"] == "finished":
                    try:
                        result = json.loads(_unprotect(base64.b64decode(previous["result"]), (str(self.journal)+tid).encode("utf-8")).decode("utf-8"))
                    except Exception:
                        result = {"state": "outcome_unknown", "error_code": "journal_unavailable", "progress": "无法读取上次执行记录，请核对当前状态"}
                else:
                    result = {"state": "outcome_unknown", "error_code": "execution_interrupted", "progress": "上次执行中断，请核对当前状态后重新发起"}
                if task["state"] == "queued":
                    self.cloud("tasks/%s/begin" % tid)
                self.cloud("tasks/%s/result" % tid, result)
                return
            config = self.store.read()
            action = task["action"]
            if task["session_id"] != self.session_id:
                return
            if action not in ACTIONS or not config.get("permissions", {}).get(ACTIONS[action]):
                return
            self.save_task(tid, "prepared")
            self.cloud("tasks/%s/begin" % tid)
            self.save_task(tid, "started")
            try:
                if action in {"start_cfquant", "restart_cfquant", "stop_cfquant"}:
                    result = self.service_action(task)
                elif action == "restart_qmt":
                    result = self.restart_qmt(task)
                else:
                    result = self.local("query", dict(task["payload"], action=action, boot_id=task["boot_id"]), timeout=35)
                response = {"state": "succeeded", "result": result, "progress": "操作完成"}
            except RemoteError as error:
                uncertain = error.code in {"connection_failed", "stop_timeout", "startup_timeout", "disabled", "cancelled"}
                response = {"state": "outcome_unknown" if uncertain else "failed", "error_code": error.code, "progress": str(error)[:500]}
            except Exception:
                response = {"state": "outcome_unknown", "error_code": "execution_interrupted", "progress": "执行结果无法确认，请检查当前状态"}
            self.save_task(tid, "finished", response)
            self.cloud("tasks/%s/result" % tid, response)
        except RemoteError:
            # The next poll resends a durable result, never the operation itself.
            return

    def restart_qmt(self, task):
        data = self.local("qmt-restart", dict(task["payload"], boot_id=task["boot_id"]), timeout=30)
        pid = data["pid"]
        last_progress = 0
        while not self.stop.wait(1):
            if not self.store.read().get("enabled"):
                raise RemoteError("disabled", "接入已关闭，操作结果需在本地确认")
            status = self.local("qmt-result", {"binding_id": task["payload"]["binding_id"], "pid": pid})
            if status.get("login_succeeded"):
                return status
            if status.get("state") == "login_failed" or status.get("terminal"):
                raise RemoteError(status.get("login_state", "login_failed"), status.get("message", "QMT 登录未完成"))
            if time.monotonic()-last_progress >= 5:
                self.cloud("tasks/%s/result" % task["id"], {"state": "running", "progress": str(status.get("message") or "正在等待 QMT 更新与登录")[:500]})
                last_progress = time.monotonic()
            # Heartbeats and polling run in another thread while updates/login wait.
        raise RemoteError("cancelled", "代理已停止，需核对 QMT 状态")

    def service_action(self, task):
        from .remote_supervisor import Supervisor
        return Supervisor(self.store, self.local).execute(task)

    def step(self):
        config = self.store.read()
        if not config.get("enabled"):
            return False
        self.instance_id = config["instance_id"]
        generation = hashlib.sha256((config["api_key"]+config["site_url"]).encode()).hexdigest()
        if generation != self.config_generation:
            self.config_generation, self.session_id = generation, ""
        if not self.session_id:
            response = self.cloud("register", {"device_id": config["device_id"]})
            self.session_id, self.permissions = response["session_id"], response["permissions"]
        response = self.cloud("heartbeat", {"snapshot": self.snapshot()})
        self.permissions = response["permissions"]
        atomic_json(self.store.status_path, {"time": time.time(), "instance_id": config["instance_id"], "state": "connected", "name": response["name"], "note": response["note"]})
        if not self.worker or not self.worker.is_alive():
            task = self.cloud("poll").get("task")
            if task:
                self.worker = threading.Thread(target=self.run_task, args=(task,), daemon=True)
                self.worker.start()
        return True

    def run(self):
        with file_lock(self.store.lock_path):
            failures = 0
            while not self.stop.is_set():
                try:
                    if not self.step():
                        break
                    failures, delay = 0, 5
                except RemoteError as error:
                    if error.code == "session_expired":
                        self.session_id = ""
                    failures += 1
                    delay = min(30, 2**min(5, failures))+random.random()
                    atomic_json(self.store.status_path, {"time": time.time(), "instance_id": self.instance_id, "state": "disconnected", "error_code": error.code})
                except Exception:
                    delay = 30
                    atomic_json(self.store.status_path, {"time": time.time(), "instance_id": self.instance_id, "state": "disconnected", "error_code": "agent_error"})
                if self.stop.wait(delay):
                    break
            self.stop.set()
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="CFQuant remote-management agent")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        return RemoteAgent(args.config).run()
    except RemoteError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
