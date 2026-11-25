# -*- coding: utf-8 -*-
"""Programmatic management of a local cfquant service (no browser required).

The service has its own source directory. Updating it never installs packages
into, or reloads modules in, the calling application's Python environment.
"""

from .diagnostic_context import VersionedErrorMixin

import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

_UNSET = object()


class ManagementError(VersionedErrorMixin, RuntimeError):
    """Management failure, including the server's status and response details."""

    def __init__(self, message, code="management_error", status=None, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details


def _path(value):
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def summarize_update_status(state):
    """Shared by the SDK and conditional-update HTTP endpoint."""
    version = state.get("version_info") or {}
    remote = version.get("remote") or {}
    receipt = state.get("last_update") or {}
    installed = (receipt.get("source") or {}).get("fetch") or {}
    actual_hash = str(installed.get("sha256") or "").strip().lower()
    remote_hash = str(remote.get("sha256") or "").strip().lower()
    current = state.get("current_version") or version.get("current_version")
    latest = remote.get("core_version") or remote.get("version")
    comparison = version.get("core_comparison") or version.get("comparison")
    if not comparison and current == latest and current:
        comparison = "same"
    web_comparison = version.get("installed_web_comparison") or version.get("web_comparison")
    if remote.get("error") or not latest or comparison in (None, "unknown", "unchecked", "different"):
        available, reason = None, "check_failed"
    elif comparison == "older" or web_comparison == "older":
        available, reason = False, "local_newer"
    elif comparison == "newer" or web_comparison == "newer":
        available, reason = True, "version_changed"
    elif remote_hash and remote_hash != actual_hash:
        available, reason = True, "package_changed" if actual_hash else "package_unknown"
    elif (receipt.get("qmt_core_deploy") or {}).get("summary", {}).get("ok") is False:
        available, reason = True, "deployment_incomplete"
    else:
        available, reason = False, "up_to_date"
    return {"available": available, "reason": reason, "current_version": current,
            "running_version": version.get("running_core_version") or version.get("imported_core_version"),
            "latest_version": latest, "remote": remote, "installed_sha256": actual_hash,
            "sha256_known": bool(actual_hash), "restart_required": bool(version.get("restart_required")),
            "status": state}


class RuntimeManager:
    """Manage an isolated service, or attach to an existing service with an API key.

    ``auto_start_qmt=None`` honors each binding; False suppresses automatic QMT
    startup/restarts; True enables automatic startup for enabled bindings.
    The chosen Python must already have cfquant's dependencies installed.
    """

    def __init__(self, home=None, *, port=8765, python_executable=None,
                 base_url=None, api_key=None, timeout=30, lttx_port=2049,
                 pipe_name=None):
        default = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "cfquant-managed"
        self.home = _path(home or default)
        self.project_dir = self.home / "service"
        self.python_executable = str(_path(python_executable or sys.executable))
        self.port = int(port)
        self.lttx_port = int(lttx_port)
        if not 0 < self.port < 65536 or not 0 < self.lttx_port < 65536:
            raise ValueError("port must be between 1 and 65535")
        self.base_url = (base_url or "http://127.0.0.1:%s" % self.port).rstrip("/")
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
            raise ValueError("base_url must be an HTTP(S) service URL without credentials")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.attached = base_url is not None
        self.pipe_name = pipe_name or r"\\.\pipe\cfquant_pipe_hub"
        self._process = None
        self.accounts = AccountManager(self)
        self.updates = UpdateManager(self)
        self.remote = RemoteManager(self)
        # Local service requests should never be sent to an HTTP proxy.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @property
    def _token_file(self):
        return self.home / "management.key"

    def _token(self, create=False):
        if create:
            self.home.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(str(self._token_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "w", encoding="ascii") as stream:
                    stream.write(secrets.token_urlsafe(32))
        try:
            return self._token_file.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return ""

    def _request(self, method, path, body=None, timeout=None):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        elif not self.attached:
            token = self._token()
            if token:
                headers["X-CFQuant-Management-Key"] = token
        raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=raw, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout if timeout is None else timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except (ValueError, UnicodeError):
                payload = {"error": "HTTP %s" % error.code}
            message = payload.get("error") or "HTTP %s" % error.code
            code = payload.get("code") or ("authentication_failed" if error.code in (401, 403) else "request_failed")
            raise ManagementError(str(message), code, error.code, payload) from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ManagementError(str(error), "service_unavailable") from error
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ManagementError(str(payload.get("error") if isinstance(payload, dict) else payload),
                                  "request_failed", details=payload)
        return payload.get("data")

    def ensure_installed(self):
        """Copy the installed distribution into home/service once; never run pip."""
        if self.attached:
            raise ManagementError("An attached service must be installed by its owner", "attached_service")
        marker = self.project_dir / "cfquant_web_server.py"
        if marker.is_file() and (self.project_dir / "cfquant/management.py").is_file():
            return {"installed": True, "created": False, "project_dir": str(self.project_dir)}
        if self.project_dir.exists():
            raise ManagementError("Incomplete service directory: %s" % self.project_dir, "incomplete_install")
        self.home.mkdir(parents=True, exist_ok=True)
        root = Path(__file__).resolve().parent.parent
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=str(self.home)))
        try:
            allowed = {".py", ".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg",
                       ".webp", ".ico", ".woff", ".woff2", ".ttf", ".md"}
            for package in ("cfquant", "LTtx", "qmt_scripts", "web_dashboard"):
                spec = importlib.util.find_spec(package)
                locations = list(spec.submodule_search_locations or []) if spec else []
                if not locations:
                    raise ManagementError("Missing service package: " + package, "missing_package")
                source = Path(locations[0])
                for path in source.rglob("*"):
                    rel = path.relative_to(source)
                    if any(part.startswith(".") or part in ("__pycache__", "log", "runtime", "tests") for part in rel.parts):
                        continue
                    if path.is_file() and not path.is_symlink() and (path.suffix.lower() in allowed or rel.as_posix() == 'tx/Config.txt'):
                        target = staging / package / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(str(path), str(target))
            for module in ("cfquant_web_server", "cfquant_pipe_hub"):
                spec = importlib.util.find_spec(module)
                if not spec or not spec.origin:
                    raise ManagementError("Missing service module: " + module, "missing_package")
                shutil.copyfile(spec.origin, str(staging / (module + ".py")))
            for name in ("pyproject.toml", "requirements.txt", "README.md", "LICENSE"):
                if (root / name).is_file():
                    shutil.copyfile(str(root / name), str(staging / name))
            if not (staging / "pyproject.toml").exists():
                from .version import __version__
                (staging / "pyproject.toml").write_text(
                    '[project]\nname = "cfquant"\nversion = "%s"\n' % __version__, encoding="utf-8")
            if not (staging / "web_dashboard/index.html").is_file():
                raise ManagementError("Missing dashboard resources", "missing_package")
            staging.rename(self.project_dir)
        finally:
            if staging.exists():
                shutil.rmtree(str(staging))
        return {"installed": True, "created": True, "project_dir": str(self.project_dir)}

    def status(self, timeout=None):
        result = self._request("GET", "/api/management/status", timeout=timeout)
        if not self.attached and _path(result["state_dir"]) != self.home:
            raise ManagementError("Port belongs to another cfquant instance", "instance_mismatch")
        return result

    def version_info(self, *, include_remote=True, force=False):
        """Return running/installed versions and optionally the remote release."""
        if not isinstance(include_remote, bool) or not isinstance(force, bool):
            raise ValueError("include_remote and force must be bools")
        query = urllib.parse.urlencode({"remote": int(include_remote), "force_remote": int(force)})
        result = self._request("GET", "/api/version?" + query)
        remote = result.get("remote") or {}
        return {"running_version": result.get("running_core_version") or result.get("imported_core_version"),
                "installed_version": result.get("current_version"),
                "web_version": result.get("web_version"),
                "installed_web_version": result.get("installed_web_version"),
                "latest_version": remote.get("core_version") or remote.get("version"),
                "latest_web_version": remote.get("web_version"),
                "restart_required": bool(result.get("restart_required")),
                "remote": remote, "details": result}

    def _listening(self):
        parsed = urllib.parse.urlparse(self.base_url)
        try:
            with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.5):
                return True
        except OSError:
            return False

    def start(self, *, auto_start_qmt=None, open_browser=False, timeout=90):
        """Start a hidden child, or reuse an authenticated matching instance."""
        if auto_start_qmt is not None and not isinstance(auto_start_qmt, bool):
            raise ValueError("auto_start_qmt must be True, False or None")
        if self.attached:
            return self.status()
        if self._listening():
            result = self.status()
            if result.get("auto_start_qmt") != auto_start_qmt:
                raise ManagementError("Running service has a different QMT startup policy; restart it explicitly",
                                      "policy_mismatch", details=result)
            return dict(result, reused=True)
        self.ensure_installed()
        self._token(create=True)
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith("CFQUANT_") and key.upper() not in ("PYTHONPATH", "PYTHONHOME")}
        env.update({"CFQUANT_HOME": str(self.home),
                    "CFQUANT_MANAGEMENT_TOKEN_FILE": str(self._token_file),
                    "CFQUANT_QMT_AUTO_START": "saved" if auto_start_qmt is None else str(int(auto_start_qmt)),
                    "CFQUANT_WEB_HOST": "127.0.0.1", "CFQUANT_WEB_PORT": str(self.port),
                    "CFQUANT_LTTX_PORT": str(self.lttx_port), "CFQUANT_PIPE_NAME": self.pipe_name,
                    "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
        log_dir = self.home / "log" / "startup"
        log_dir.mkdir(parents=True, exist_ok=True)
        kwargs = {"cwd": str(self.project_dir), "env": env, "stdin": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        with (log_dir / "management-service.log").open("ab") as log:
            self._process = subprocess.Popen(
                [self.python_executable, "-u", str(self.project_dir / "cfquant_web_server.py"),
                 "--host", "127.0.0.1", "--port", str(self.port)], stdout=log, stderr=log, **kwargs)
        result = self._wait_service(timeout, process=self._process)
        if open_browser:
            import webbrowser
            webbrowser.open(self.base_url)
        return dict(result, reused=False)

    def _wait_service(self, timeout, previous_boot=None, process=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise ManagementError("Service exited with code %s; see %s" %
                                      (process.returncode, self.home / "log/startup/management-service.log"), "service_exited")
            try:
                result = self.status(timeout=min(2, max(0.1, deadline - time.monotonic())))
                if result.get("ready") and result.get("boot_id") != previous_boot:
                    return result
            except ManagementError as error:
                if error.code != "service_unavailable":
                    raise
            time.sleep(0.2)
        raise ManagementError("Timed out waiting for cfquant service", "service_timeout")

    def stop(self, timeout=30):
        """Stop the cfquant HTTP/router process. QMT is left running."""
        before = self.status()
        result = self._request("POST", "/api/management/stop", {})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                current = self.status(timeout=1)
                if current.get("boot_id") != before.get("boot_id"):
                    return result
            except ManagementError as error:
                if error.code == "service_unavailable":
                    return result
                raise
            time.sleep(0.2)
        raise ManagementError("Timed out stopping cfquant", "service_timeout")

    def restart(self, *, auto_start_qmt=_UNSET, timeout=90):
        if auto_start_qmt is not _UNSET and auto_start_qmt is not None and not isinstance(auto_start_qmt, bool):
            raise ValueError("auto_start_qmt must be True, False or None")
        before = self.status()
        body = {} if auto_start_qmt is _UNSET else {"auto_start_qmt": auto_start_qmt}
        self._request("POST", "/api/management/restart", body)
        return self._wait_service(timeout, previous_boot=before["boot_id"])

    def initialize(self, account_id, qmt_dir, **options):
        """Initialize the first binding; subsequent calls upsert that binding."""
        return self.accounts.upsert(account_id, qmt_dir, _initialize=True, **options)

    def recover_strategy(self, account_id=None, *, account_type=None, bridge_id=None,
                         account_key=None, timeout=180):
        """Recover a binding using the same managed service as initialize().

        Reuse this RuntimeManager after binding accounts. Local managed services
        automatically use home/management.key, just like account management.
        """
        return self.accounts.recover_strategy(account_id, account_type=account_type,
                                             bridge_id=bridge_id, account_key=account_key,
                                             timeout=timeout)

    def wait_ready(self, account_id, *, account_type="STOCK", bridge_id=None, timeout=120):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            bindings = self.accounts.status(timeout=min(5, max(0.1, deadline - time.monotonic())))
            matches = [row for row in bindings["bindings"] if row["account_id"] == str(account_id)
                       and row["account_type"] == account_type
                       and (bridge_id is None or row["bridge_id"] == bridge_id)]
            if len(matches) > 1:
                raise ManagementError("Specify bridge_id for this account", "ambiguous_account")
            last = matches[0] if matches else None
            if last and last.get("enabled") and (last.get("status") or {}).get("ready"):
                return last
            time.sleep(0.3)
        raise ManagementError("QMT bridge is not ready; start/login QMT and run its bridge strategy",
                              "qmt_not_ready", details=last)

    def configure_client(self):
        """Point cfquant's data/trading clients at this service's LTtx router."""
        info = self.status()
        from . import configure
        configure(host=info["lttx_host"], port=info["lttx_port"], transport="web_lttx")


class RemoteManager:
    """Opt-in connection using a project API key created on the official site."""

    def __init__(self, runtime):
        self.runtime = runtime

    def status(self):
        return self.runtime._request("GET", "/api/remote-management")

    def configure(self, *, enabled=True, api_key=None, permissions=None):
        body = {"enabled": bool(enabled)}
        body.update({k: v for k, v in {"api_key": api_key, "permissions": permissions}.items() if v is not None})
        return self.runtime._request("POST", "/api/remote-management", body)


class AccountManager:
    def __init__(self, runtime):
        self.runtime = runtime

    def list(self):
        return self.runtime.status()["account_configs"]

    def status(self, timeout=None):
        return self.runtime._request("GET", "/api/bindings/status", timeout=timeout)

    def proxy(self, account_id=None, *, account_type="STOCK", bridge_id=None,
              account_key=None, timeout=None):
        """Return the sanitized proxy profile for one binding."""
        selectors = {"account_id": account_id, "account_type": account_type,
                     "bridge_id": bridge_id, "account_key": account_key}
        body = {key: value for key, value in selectors.items()
                if value is not None and str(value).strip()}
        if not body.get("account_id") and not body.get("account_key"):
            raise ValueError("account_id or account_key is required")
        query = urllib.parse.urlencode(body)
        result = self.runtime._request("GET", "/api/account-config/proxy?" + query, timeout=timeout)
        return result.get("proxy") or {}

    def set_proxy(self, proxy, account_id=None, *, account_type="STOCK", bridge_id=None,
                  account_key=None, restart=False, timeout=180):
        """Save a binding proxy profile and optionally restart QMT."""
        if not isinstance(proxy, dict):
            raise ValueError("proxy must be a dict")
        body = {key: value for key, value in {
            "account_id": account_id, "account_type": account_type,
            "bridge_id": bridge_id, "account_key": account_key,
        }.items() if value is not None and str(value).strip()}
        if not body.get("account_id") and not body.get("account_key"):
            raise ValueError("account_id or account_key is required")
        body.update(qmt_proxy=dict(proxy), restart=bool(restart))
        return self.runtime._request("POST", "/api/account-config/proxy", body, timeout=timeout)

    def recover_strategy(self, account_id=None, *, account_type=None, bridge_id=None,
                         account_key=None, timeout=180):
        """Check and recover this binding's stopped managed QMT strategies.

        Requires enabled strategy automation and a completed deployment. Returns
        running/start_requested and per-target recovery states; submitting a start
        is not confirmation that the strategy or its bridge is already running.
        Uses the Web service, so it also works while the QMT bridge is offline.
        """
        body = {key: str(value).strip() for key, value in {
            "account_id": account_id, "account_type": account_type,
            "bridge_id": bridge_id, "account_key": account_key,
        }.items() if value is not None}
        if not body.get("account_id") and not body.get("account_key"):
            raise ValueError("account_id or account_key is required")
        if any(not value for value in body.values()):
            raise ValueError("account selectors must not be empty")
        if not self.runtime.attached:
            self.runtime.status()  # Verify managed instance ownership first.
        return self.runtime._request("POST", "/api/qmt/strategies/recover", body, timeout=timeout)

    def upsert(self, account_id, qmt_dir, *, account_type="STOCK", mode="ctypes",
               auto_start_qmt=False, deploy_strategy=True, strategy_autorun=True,
               live=True, auto_close_qmt=False, force=False, _initialize=False, **options):
        for name, value in (("auto_start_qmt", auto_start_qmt), ("deploy_strategy", deploy_strategy),
                            ("strategy_autorun", strategy_autorun), ("live", live),
                            ("auto_close_qmt", auto_close_qmt)):
            if not isinstance(value, bool):
                raise ValueError(name + " must be a bool")
        if account_id is None or qmt_dir is None or not str(account_id).strip() or not str(qmt_dir).strip():
            raise ValueError("account_id and qmt_dir are required")
        body = dict(options, account_id=str(account_id).strip(), account_type=account_type,
                    qmt_dir=os.fsdecode(qmt_dir), mode=mode, auto_close_qmt=auto_close_qmt)
        if body.get("qmt_trade_dir") is not None:
            body["qmt_trade_dir"] = os.fsdecode(body["qmt_trade_dir"])
        body["qmt_strategy"] = dict(options.get("qmt_strategy") or {}, enabled=deploy_strategy,
                                    autorun=strategy_autorun, live=live)
        body["qmt_auto_login"] = dict(options.get("qmt_auto_login") or {}, enabled=auto_start_qmt)
        config = self.runtime.status()
        candidates = [row for row in config["account_configs"].values()
                      if row["account_id"] == body["account_id"] and row["account_type"] == account_type
                      and (not body.get("bridge_id") or body["bridge_id"] == row["bridge_id"])]
        if len(candidates) > 1:
            raise ManagementError("Specify bridge_id for this account", "ambiguous_account")
        if candidates and not force:
            row = candidates[0]
            def equal(key, value):
                saved = row.get(key)
                if isinstance(value, dict):
                    return isinstance(saved, dict) and all(saved.get(k) == v for k, v in value.items())
                if key in ("qmt_dir", "qmt_trade_dir"):
                    return bool(saved) and _path(saved) == _path(value)
                return saved == value
            ignored = {"auto_close_qmt", "auto_deploy_qmt_core"}
            if all(equal(key, value) for key, value in body.items() if key not in ignored):
                return {"unchanged": True, "account": row, "setup": config["setup"]}
        path = "/api/setup/initialize" if _initialize and config["setup"].get("setup_required") else "/api/account-config"
        return self.runtime._request("POST", path, body, timeout=180)

    def delete(self, account_id, account_type="STOCK", **options):
        return self.runtime._request("POST", "/api/account-config/delete",
                                     dict(options, account_id=account_id, account_type=account_type))


class UpdateManager:
    def __init__(self, runtime):
        self.runtime = runtime

    def check(self, *, force=False):
        """Check the official release, including same-version package changes."""
        if not isinstance(force, bool):
            raise ValueError("force must be a bool")
        state = self.runtime._request("GET", "/api/project-updates/status?remote=1&force=" + str(int(force)))
        return summarize_update_status(state)

    def ensure_latest(self, *, auto_close_qmt=False, restart=True, timeout=300, restart_timeout=90):
        """Check afresh and update only when needed; never automatically downgrade.

        Returns status/message/updated plus check and optional update details.
        Remote lookup failures return check_failed; installation failures raise
        ManagementError. Applies to the default official release channel.
        """
        if not isinstance(auto_close_qmt, bool) or not isinstance(restart, bool):
            raise ValueError("auto_close_qmt and restart must be bools")
        self.runtime.status()  # Authenticate and verify local instance ownership.
        result = self.runtime._request("POST", "/api/project-updates/ensure-latest",
                                       {"auto_close_qmt": auto_close_qmt, "reload": False}, timeout=timeout)
        if restart and result.get("restart_required") and result["status"] != "check_failed":
            result["service"] = self.runtime.restart(timeout=restart_timeout)
            result["running_version"] = result["service"].get("running_core_version") or result["service"].get("core_version")
            result["restart_required"] = False
            if result["status"] == "restart_required":
                result.update(status="up_to_date", message="已是最新版本，后台服务已重启生效")
            elif result["status"] == "updated":
                result["message"] = "已更新，后台服务已重启生效"
        return result

    def apply(self, *, source="official", ref="main", repo_url=None, site_url=None,
              auto_close_qmt=False, restart=True, timeout=300, restart_timeout=90):
        if not isinstance(auto_close_qmt, bool) or not isinstance(restart, bool):
            raise ValueError("auto_close_qmt and restart must be bools")
        before = self.runtime.status()
        if not before.get("running_from_source"):
            raise ManagementError("Use RuntimeManager.ensure_installed() to update an isolated service",
                                  "unmanaged_install")
        if source not in ("official", "github"):
            raise ValueError("source must be official or github")
        body = {"auto_close_qmt": auto_close_qmt, "reload": False, "ref": ref}
        if repo_url:
            body["repo_url"] = repo_url
        if site_url:
            body["site_url"] = site_url
        result = self.runtime._request("POST", "/api/project-updates/" + source, body, timeout=timeout)
        if restart:
            result["service"] = self.runtime.restart(timeout=restart_timeout)
        return result

    def rollback(self, backup, *, auto_close_qmt=False, restart=True, timeout=300):
        if not isinstance(auto_close_qmt, bool) or not isinstance(restart, bool):
            raise ValueError("auto_close_qmt and restart must be bools")
        result = self.runtime._request("POST", "/api/project-updates/rollback",
                                       {"backup": backup, "reload": False, "auto_close_qmt": auto_close_qmt},
                                       timeout=timeout)
        if restart:
            result["service"] = self.runtime.restart()
        return result
