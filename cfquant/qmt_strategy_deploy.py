"""Resumable QMT strategy import and offline model configuration for Web bindings."""

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import tokenize
import uuid
from xml.dom import minidom

from .qmt_strategy_package import build_package


SCRIPTS = {"ctypes": "CFQUANT_CTYPE_ALL_LOWLAT.py", "lite": "CFQUANT_LITE.py",
           "lttx": "CFQUANT.py"}
LEGACY_NAMES = {Path(name).stem for name in SCRIPTS.values()} | {"CFQUANT_TRADE_LOWLAT"}
LEGACY_NAMES |= {name + "_" + market for name in tuple(LEGACY_NAMES) for market in ("SH", "SZ")}
STATES = {
    "waiting_exit": "请正常退出对应 QMT，并等待模型配置完成后再启动",
    "waiting_import": "导入包和模型已准备，请启动并登录 QMT",
    "waiting_import_save": "策略已导入但模型尚未配置，请退出 QMT 并等待配置完成",
    "waiting_start": "QMT 已启动，等待托管策略启动及通道连接",
    "waiting_manual_start": "QMT 已启动，自启未开启，请在模型交易中运行托管策略",
    "running": "托管策略已运行",
    "waiting_account": "未找到此资金账号的 QMT 绑定键，请补充模型账号 Key",
    "configured": "模型已配置，等待下次启动 QMT 生效",
    "disabled": "自动运行已关闭，托管策略已禁用",
    "error": "策略部署失败",
}


def normalize_strategy_settings(value):
    value = value if isinstance(value, dict) else {}
    result = {}
    for name, default in (("enabled", False), ("live", False), ("autorun", False)):
        raw = value.get(name, default)
        if not isinstance(raw, bool):
            raise ValueError("qmt_strategy.%s must be a boolean" % name)
        result[name] = raw
    stock = str(value.get("stock") or "SH000300").strip().upper()
    if not re.fullmatch(r"(?:SH|SZ)[0-9]{6}", stock):
        raise ValueError("QMT 主图品种必须为 SH/SZ 加六位代码")
    result["stock"] = stock
    result["period"] = 86400
    keys = value.get("account_keys") or {}
    if not isinstance(keys, dict):
        raise ValueError("qmt_strategy.account_keys must be an object")
    result["account_keys"] = {role: str(keys.get(role) or "").strip()
                              for role in ("normal", "trade", "SH", "SZ")}
    return result


def qmt_root(directory, validate=False):
    path = Path(str(directory)).expanduser().resolve()
    if path.name.lower() in ("bin.x64", "bin", "python"):
        path = path.parent
    if validate:
        if not (path / "bin.x64" / "XtItClient.exe").is_file():
            raise ValueError("QMT 目录缺少 bin.x64/XtItClient.exe: %s" % path)
        if not (path / "config" / "indexUserConfig.xml").is_file():
            raise ValueError("QMT 目录缺少 config/indexUserConfig.xml: %s" % path)
        if not (path / "formulas").is_dir():
            raise ValueError("QMT 目录缺少 formulas 导入队列: %s" % path)
    return path


def account_qmt_roots(row):
    paths = [row.get("qmt_dir")]
    if row.get("mode") == "lttx":
        paths.append(row.get("qmt_trade_dir"))
    if row.get("market_routing_enabled"):
        paths = [route.get("qmt_dir") for route in (row.get("market_bridges") or {}).values()
                 if isinstance(route, dict) and route.get("enabled", True)]
    return {os.path.normcase(str(qmt_root(path))) for path in paths if path}


def _role_stock(settings, role):
    stock = settings["stock"]
    if role == "SH" and not stock.startswith("SH"):
        return "SH000300"
    if role == "SZ" and not stock.startswith("SZ"):
        return "SZ399001"
    return stock


def qmt_is_running(root):
    import psutil
    executable = os.path.normcase(str(root / "bin.x64" / "XtItClient.exe"))
    for process in psutil.process_iter(["name"]):
        try:
            if str(process.info.get("name") or "").lower() != "xtitclient.exe":
                continue
            if os.path.normcase(str(Path(process.exe()).resolve())) == executable:
                return True
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            # An uninspectable QMT may be the target. Do not write its XML.
            return True
    return False


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True).encode("ascii")).hexdigest()


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path, value):
    _atomic_write(path, json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8"))


def _generation_values(value):
    if not isinstance(value, (list, tuple, set)):
        return []
    result = []
    for item in value:
        item = str(item or "").strip()
        if item and item not in result:
            result.append(item)
    return result


def _runtime_generation(role):
    path = role.get("runtime_status_path") if isinstance(role, dict) else ""
    if not path:
        return ""
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    generation = report.get("generation")
    return str(generation or "").strip()


def _read_document(path, expected_root="ICUserConfigFile"):
    content = path.read_bytes()
    if len(content) > 16 * 1024 * 1024 or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("Unsupported QMT XML configuration")
    document = minidom.parseString(content)
    if document.documentElement.tagName != expected_root:
        raise ValueError("Unsupported QMT XML root")
    return document, content


def _model_items(document):
    sections = document.getElementsByTagName("strategyTrade")
    if len(sections) > 1:
        raise ValueError("Multiple QMT strategyTrade sections are not supported")
    if not sections:
        section = document.createElement("strategyTrade")
        document.documentElement.appendChild(section)
    else:
        section = sections[0]
    return section, list(section.getElementsByTagName("item"))


def _strategy_slot_name(mode, group_key, role):
    """Return the stable QMT model name for one managed deployment slot."""
    return "CFQ_%s_%s_%s" % (
        str(mode or "").upper(),
        str(group_key or "").upper()[:8],
        str(role or "normal").upper(),
    )


def _valid_managed_strategy_name(name):
    return bool(re.fullmatch(r"CFQ_[A-Z0-9_]{1,59}", str(name or "")))


def _remove_formula_catalog_entries(document, names):
    names = {str(name or "") for name in names if name}
    changed = False
    for catalog_group in document.getElementsByTagName("FormulaCatalog"):
        for entry in list(catalog_group.getElementsByTagName("catalog")):
            if entry.getAttribute("name") in names:
                catalog_group.removeChild(entry)
                changed = True
    return changed


def _account_binding(document, account_id, account_type, supplied=""):
    candidates = set()
    for item in document.getElementsByTagName("item"):
        if item.getAttribute("account") == account_id:
            key, kind = item.getAttribute("m_strAccountKey"), item.getAttribute("accountType")
            if key and kind:
                candidates.add((kind, key))
    if supplied:
        parts = supplied.split("____")
        binding = (parts[0], supplied)
    elif len(candidates) == 1:
        binding = next(iter(candidates))
    else:
        return None
    parts = binding[1].split("____")
    if (len(parts) != 6 or parts[-1] or parts[-2] != account_id
            or parts[0] != binding[0] or not all(p.isdigit() for p in parts[:-1])):
        raise ValueError("模型账号 Key 与资金账号不匹配")
    if account_type in ("STOCK", "CREDIT") and binding[0] != {"STOCK": "2", "CREDIT": "3"}[account_type]:
        raise ValueError("模型账号 Key 与普通/信用账户类型不匹配")
    return binding


def _resolve_account_binding(root, document, account_id, account_type, supplied="", cached=""):
    binding = _account_binding(document, account_id, account_type, supplied)
    if binding or supplied:
        return binding
    # A conflicting selection must not be silently resolved using another source.
    if any(item.getAttribute("account") == account_id and item.getAttribute("m_strAccountKey")
           for item in document.getElementsByTagName("item")):
        return None
    candidates = set()
    for path in (root / "userdata" / "users").glob("*/authAndConfig.xml"):
        try:
            auth, _ = _read_document(path, expected_root="TTAuthAndConfigFile")
        except Exception:
            continue
        for node in auth.getElementsByTagName("AccountAuth"):
            key = node.getAttribute("key")
            if key.split("____")[-2:-1] != [account_id]:
                continue
            try:
                candidates.add(_account_binding(document, account_id, account_type, key))
            except ValueError:
                continue
    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates and cached:
        return _account_binding(document, account_id, account_type, cached)
    return None


def managed_source(source_path, identity_path, identity, descriptor):
    with tokenize.open(str(source_path)) as stream:
        source = stream.read()
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    replacements = []
    constants = {"DEFAULT_ACCOUNT_ID": identity["account_id"], "DEFAULT_ACCOUNT_TYPE": identity["account_type"],
                 "USER_BRIDGE_ID": identity["bridge_id"], "BRIDGE_ID": identity["bridge_id"],
                 "QMT_MARKET": identity.get("market", "")}
    seen = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in constants and (name not in seen or name == "QMT_MARKET"):
                replacements.append((node.lineno - 1, node.end_lineno, name + " = " + ascii(constants[name]) + "\n"))
                seen.add(name)
        elif isinstance(node, ast.FunctionDef) and node.name == "_runtime_config_paths":
            replacements.append((node.lineno - 1, node.end_lineno,
                                 "def _runtime_config_paths():\n    return [%s]\n" % ascii(str(identity_path))))
        elif isinstance(node, ast.FunctionDef) and node.name == "_env_allows_runtime_override":
            replacements.append((node.lineno - 1, node.end_lineno,
                                 "def _env_allows_runtime_override(name, default_value=''):\n    return True\n"))
    for start, end, text in sorted(replacements, reverse=True):
        lines[start:end] = [text]
    lines[0] = "# coding: utf-8\n"
    source = "".join(lines)
    ast.parse(source, feature_version=(3, 6))
    helper = Path(__file__).with_name("qmt_strategy_runtime.py").read_text(encoding="utf-8")
    generated = ("# coding: utf-8\n" + helper + "\n_cq_descriptor = " + ascii(descriptor)
            + "\n_cq_guard = _CqStrategyLease(_cq_descriptor).acquire()\n"
            + "_cq_guard.namespace = globals()\ntry:\n"
            + "    exec(compile(%s, %s, 'exec'), globals())\n" % (ascii(source), ascii(str(source_path)))
            + "    for _cq_name in ('_cf_bridge', '_normal_bridge', '_trade_bridge'):\n"
            + "        if globals().get(_cq_name) is not None:\n"
            + "            globals()[_cq_name].account_type = %s\n" % ascii(identity["account_type"])
            + "    _cq_guard.bind(globals())\nexcept BaseException as _cq_error:\n"
            + "    _cq_guard.failure = str(_cq_error)\n    _cq_guard.close()\n    raise\n")
    # QMT may recode source through the Windows ANSI code page before compiling.
    generated.encode("ascii")
    return generated


class QmtStrategyManager:
    def __init__(self, state_path, scripts_dir, process_checker=qmt_is_running):
        self.path = Path(state_path)
        self.scripts_dir = Path(scripts_dir)
        self.process_checker = process_checker
        self.lock = threading.RLock()
        self.event = threading.Event()
        self.stopping = threading.Event()
        self.worker = None
        self.jobs = {}
        self.errors = {}
        self.load_error = ""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or not isinstance(data.get("jobs"), dict):
                    raise ValueError("unsupported deployment state")
                self.jobs = data["jobs"]
                self.errors = data.get("errors", {})
            except (OSError, ValueError, TypeError) as error:
                self.load_error = "QMT 策略任务文件无法读取，请检查 %s: %s" % (self.path, error)

    def _save(self):
        if self.load_error:
            return
        _write_json(self.path, {"version": 1, "jobs": self.jobs, "errors": self.errors})

    def report_error(self, account_key, error):
        with self.lock:
            self.errors[account_key] = str(error)
            self._save()
            return self.status(account_key)

    def _state(self, job, state, error=""):
        if job.get("state") == state and job.get("error", "") == error:
            return
        job.update(state=state, message=error or STATES[state], error=error, updated_at=time.time())

    def _clear_generation_transition(self, job):
        changed = False
        for key in ("control_generation", "accepted_generations"):
            if key in job:
                job.pop(key, None)
                changed = True
        return changed

    def _prepare_generation_transition(self, job, previous=None):
        """Keep old same-name containers valid until the replacement starts."""
        if not job.get("enabled"):
            return self._clear_generation_transition(job)

        generation = str(job.get("generation") or "").strip()
        if not generation:
            return False

        if previous is not None:
            previous_roles = {
                role.get("role"): role
                for role in previous.get("roles", [])
                if isinstance(role, dict)
            }
            reused = any(
                isinstance(previous_roles.get(role.get("role")), dict)
                and previous_roles[role["role"]].get("name") == role.get("name")
                for role in job.get("roles", [])
            )
            if previous.get("mode") != job.get("mode") or not reused:
                return self._clear_generation_transition(job)
            candidates = _generation_values(previous.get("accepted_generations"))
            if previous.get("control_generation"):
                candidates.insert(0, str(previous["control_generation"]).strip())
            candidates.extend(
                _runtime_generation(previous_roles[role.get("role")])
                for role in job.get("roles", [])
                if isinstance(previous_roles.get(role.get("role")), dict)
            )
            if previous.get("generation"):
                candidates.append(str(previous["generation"]).strip())
        else:
            candidates = _generation_values(job.get("accepted_generations"))
            if job.get("control_generation"):
                candidates.insert(0, str(job["control_generation"]).strip())
            candidates.extend(_runtime_generation(role) for role in job.get("roles", []))

        legacy = next((item for item in candidates if item and item != generation), "")
        if not legacy:
            return False

        accepted = [item for item in _generation_values(job.get("accepted_generations"))
                    if item not in (legacy, generation)]
        accepted.append(generation)
        changed = (
            job.get("control_generation") != legacy
            or _generation_values(job.get("accepted_generations")) != accepted
        )
        job["control_generation"] = legacy
        job["accepted_generations"] = accepted
        if previous is None:
            for role in job.get("roles", []):
                if _runtime_generation(role) == legacy:
                    updates = {
                        "reimport_required": True,
                        "imported": False,
                        "queued": False,
                        "model_prepared": False,
                    }
                    for key, value in updates.items():
                        if role.get(key) != value:
                            role[key] = value
                            changed = True
        if changed and job.get("state") == "error":
            self._state(job, "waiting_exit")
        return changed

    def status(self, account_key):
        with self.lock:
            jobs = [job for job in self.jobs.values() if job["account_key"] == account_key]
            fields = ("root", "state", "message", "error", "mode", "updated_at", "backup")
            result = {"enabled": any(job.get("enabled") for job in jobs),
                    "targets": [dict({k: job.get(k, "") for k in fields},
                                     strategies=[r["name"] for r in job.get("roles", [])]) for job in jobs]}
            if account_key in self.errors:
                result.update(error=self.errors[account_key], message="账号已保存，策略部署失败: " + self.errors[account_key])
            if self.load_error:
                result.update(error=self.load_error, message=self.load_error)
            return result

    def configure(self, row, identities):
        if self.load_error:
            raise ValueError(self.load_error)
        settings = normalize_strategy_settings(row.get("qmt_strategy"))
        enabled = row.get("enabled", True) and settings["enabled"]
        with self.lock:
            wanted = set()
            grouped = {}
            if enabled:
                if row.get("market_routing_enabled"):
                    identities = [info for info in identities if info.get("market") in ("SH", "SZ")]
                for info in identities:
                    if not info.get("written"):
                        raise ValueError(info.get("error") or info.get("warning") or "QMT 身份配置写入失败")
                    root = qmt_root(info["core_dir"], validate=True)
                    identity = json.loads(Path(info["path"]).read_text(encoding="utf-8"))
                    identity.update(account_id=row["account_id"], account_type=row["account_type"],
                                    account_key=row["account_key"], accounts=[{
                                        "account_id": row["account_id"], "account_type": row["account_type"],
                                        "account_key": row["account_key"]}])
                    market = info.get("market") or identity.get("market") or ""
                    role = market or info.get("qmt_role") or "normal"
                    filename = SCRIPTS[row["mode"]]
                    if row["mode"] == "lttx" and role != "normal":
                        filename = "CFQUANT_TRADE_LOWLAT.py"
                    source_path = self.scripts_dir / filename
                    if market:
                        source_path = self.scripts_dir / "同账号独立市场" / (Path(filename).stem + "_" + market + ".py")
                    if not source_path.is_file():
                        raise ValueError("QMT 内置脚本不存在: %s" % source_path)
                    for key in ("updated_at", "updated_at_text"):
                        identity.pop(key, None)
                    group_key = _digest([os.path.normcase(str(root)), row["account_id"]])[:24]
                    grouped.setdefault(group_key, {"root": str(root), "roles": []})["roles"].append({
                        "role": role, "source": str(source_path), "identity": identity,
                        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                        "account_key": settings["account_keys"].get(role, "")})
                if not grouped:
                    raise ValueError("自动导入策略需要填写 QMT 目录")
            for key, group in grouped.items():
                wanted.add(key)
                previous = self.jobs.get(key, {})
                source_group = copy.deepcopy(group)
                for role in source_group["roles"]:
                    role.pop("account_key", None)
                fingerprint = _digest([source_group, row["mode"], [
                    hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest()
                    for filename in ("qmt_strategy_runtime.py", "qmt_strategy_package.py", "qmt_strategy_deploy.py")]])
                if previous.get("fingerprint") == fingerprint and previous.get("enabled"):
                    previous["account_key"] = row["account_key"]
                    self._prepare_generation_transition(previous)
                    if previous["settings"] != settings:
                        previous["settings"] = settings
                        for role in previous["roles"]:
                            role["account_key"] = settings["account_keys"].get(role["role"], "")
                            role["model_prepared"] = False
                        self._state(previous, "waiting_exit")
                    if previous.get("state") == "error":
                        for role in previous["roles"]:
                            role["queued"] = False
                        self._state(previous, "waiting_exit")
                    continue
                generation = uuid.uuid4().hex
                directory = Path(group["root"]) / "cfquant_managed" / key
                previous_roles = {
                    role.get("role"): role
                    for role in previous.get("roles", [])
                    if isinstance(role, dict)
                }
                role_names = {}
                for role in group["roles"]:
                    old_role = previous_roles.get(role["role"])
                    old_name = old_role.get("name") if isinstance(old_role, dict) else ""
                    if (previous.get("mode") == row["mode"]
                            and _valid_managed_strategy_name(old_name)):
                        role_names[role["role"]] = old_name
                    else:
                        role_names[role["role"]] = _strategy_slot_name(
                            row["mode"], key, role["role"]
                        )
                current_names = set(role_names.values())
                retired = set(previous.get("retired", []))
                retired.update(
                    role.get("name")
                    for role in previous.get("roles", [])
                    if isinstance(role, dict) and role.get("name")
                )
                retired.difference_update(current_names)
                job = dict(group, account_key=row["account_key"], account_id=row["account_id"],
                           account_type=row["account_type"], mode=row["mode"], settings=settings,
                           enabled=True, generation=generation, fingerprint=fingerprint,
                           control_path=str(directory / "desired.json"),
                           retired=sorted(retired))
                for role in job["roles"]:
                    role["name"] = role_names[role["role"]]
                    role["reimport_required"] = bool(
                        previous.get("fingerprint")
                        and isinstance(previous_roles.get(role["role"]), dict)
                        and previous_roles[role["role"]].get("name") == role["name"]
                    )
                    role["identity_path"] = str(directory / (role["name"] + ".json"))
                    _write_json(role["identity_path"], role["identity"])
                    role["runtime_status_path"] = str(directory / (role["name"] + ".status.json"))
                    descriptor = {"mode": job["mode"], "generation": generation, "role": role["role"],
                                  "control_path": job["control_path"], "lease_dir": str(directory / "leases"),
                                  "runtime_status_path": role["runtime_status_path"]}
                    source = managed_source(Path(role["source"]), role["identity_path"], role["identity"], descriptor)
                    package = build_package(role["name"], source, _role_stock(settings, role["role"]), settings["period"])
                    role["package_path"] = str(directory / (role["name"] + ".rzrk"))
                    _atomic_write(role["package_path"], package)
                    role["package_sha256"] = hashlib.sha256(package).hexdigest()
                self._prepare_generation_transition(job, previous=previous)
                self._state(job, "waiting_exit")
                self.jobs[key] = job
            for key, job in self.jobs.items():
                if job["account_key"] == row["account_key"] and key not in wanted:
                    job["enabled"] = False
                    self._state(job, "waiting_exit")
            # Persist jobs before granting a new generation ownership. A restart
            # can resume an interrupted write without losing the selected mode.
            self.errors.pop(row["account_key"], None)
            self._save()
            for job in self.jobs.values():
                if job["account_key"] == row["account_key"]:
                    self._control(job)
            self.process_once()
            self.event.set()
            return self.status(row["account_key"])

    def _control(self, job):
        generation = str(job.get("control_generation") or job.get("generation") or "")
        payload = {"enabled": bool(job.get("enabled")), "generation": generation, "mode": job.get("mode", "")}
        accepted = [item for item in _generation_values(job.get("accepted_generations"))
                    if item and item != generation]
        if accepted:
            payload["accepted_generations"] = accepted
        _write_json(job["control_path"], payload)

    def reconcile(self, accounts):
        with self.lock:
            changed = False
            for job in self.jobs.values():
                row = accounts.get(job["account_key"], {})
                valid = (row.get("enabled", True) and row.get("qmt_strategy", {}).get("enabled")
                         and row.get("mode") == job["mode"]
                         and os.path.normcase(job["root"]) in account_qmt_roots(row))
                if job.get("enabled") and not valid:
                    job["enabled"] = False
                    self._clear_generation_transition(job)
                    self._state(job, "waiting_exit")
                    self._control(job)
                    changed = True
                elif job.get("enabled") and self._prepare_generation_transition(job):
                    changed = True
                self._control(job)
            for key in list(self.errors):
                if key not in accounts:
                    self.errors.pop(key)
                    changed = True
            if changed:
                self._save()
                self.event.set()

    def process_once(self):
        with self.lock:
            changed = False
            for job in self.jobs.values():
                before = copy.deepcopy(job)
                if job.get("state") == "disabled":
                    continue
                if job.get("state") == "error":
                    self._prepare_generation_transition(job)
                    if not job.get("control_generation") and not _generation_values(
                            job.get("accepted_generations")):
                        continue
                try:
                    self._advance(job)
                except Exception as error:
                    self._state(job, "error", str(error))
                changed = changed or before != job
            if changed:
                self._save()

    def _advance(self, job):
        root = qmt_root(job["root"], validate=True)
        if self.process_checker(root):
            self._observe_runtime(job)
            return
        if (job.get("state") in ("configured", "running", "waiting_start", "waiting_manual_start")
                and all(role.get("imported") for role in job["roles"])):
            self._state(job, "configured")
            return
        config = root / "config" / "indexUserConfig.xml"
        document, original = _read_document(config)
        section, items = _model_items(document)
        owned_names = set(job.get("retired", [])) | {role["name"] for role in job["roles"]}
        changed = False
        for item in items:
            if (item.getAttribute("account") == job["account_id"]
                    and item.getAttribute("name") in (set(job.get("retired", [])) | LEGACY_NAMES
                                                      | (owned_names if not job["enabled"] else set()))
                    and item.getAttribute("startupAutorun") != "0"):
                item.setAttribute("startupAutorun", "0")
                changed = True
        reimport_names = {
            role["name"] for role in job["roles"]
            if job["enabled"] and role.get("reimport_required")
        }
        if reimport_names:
            # QMT stores imported Python strategies separately from the
            # .rzrk queue. Replace only the managed slot being refreshed.
            changed = _remove_formula_catalog_entries(document, reimport_names) or changed
            for role in job["roles"]:
                if role["name"] not in reimport_names:
                    continue
                generated = root / "python" / (role["name"] + ".py")
                if generated.exists():
                    generated.unlink()
                    changed = True
                role["imported"] = False
                role["queued"] = False
                role["model_prepared"] = False
        state = "disabled"
        if job["enabled"]:
            catalog = {item.getAttribute("name") for group in document.getElementsByTagName("FormulaCatalog")
                       for item in group.getElementsByTagName("catalog")}
            state = "configured"
            for role in job["roles"]:
                name = role["name"]
                queue = root / "formulas" / (name + ".rzrk")
                imported = name in catalog and (root / "python" / (name + ".py")).is_file()
                if not imported:
                    if not role.get("queued"):
                        if (root / "python" / (name + ".py")).exists() or name in catalog:
                            raise ValueError("QMT 策略名称冲突: %s" % name)
                        package = Path(role["package_path"]).read_bytes()
                        if queue.exists() and queue.read_bytes() != package:
                            if role.get("reimport_required"):
                                _atomic_write(queue, package)
                            else:
                                raise ValueError("QMT 导入队列存在同名文件: %s" % name)
                        elif not queue.exists():
                            _atomic_write(queue, package)
                        role["queued"] = True
                    elif not queue.exists():
                        raise ValueError("导入队列已被消费，但未找到完整策略登记；请查看 QMT 日志后重试: %s" % name)
                    role["reimport_required"] = False
                    if state != "waiting_account":
                        state = "waiting_import"
                else:
                    role["imported"] = True
                    role["reimport_required"] = False
                binding = _resolve_account_binding(root, document, job["account_id"], job["account_type"],
                                                   role["account_key"], role.get("resolved_account_key", ""))
                if not binding:
                    state = "waiting_account"
                    continue
                role["resolved_account_key"] = binding[1]
                matches = [item for item in items if item.getAttribute("name") == name]
                if len(matches) > 1:
                    raise ValueError("QMT 中存在重复的托管模型: %s" % name)
                if matches:
                    item = matches[0]
                    if item.getAttribute("account") != job["account_id"]:
                        raise ValueError("托管模型被绑定到其他资金账号: %s" % name)
                else:
                    templates = [item for item in items if item.getAttribute("account") == job["account_id"]
                                 and item.getAttribute("eStrategyType") in ("4", "5")]
                    item = templates[0].cloneNode(deep=True) if templates else document.createElement("item")
                    ids = [int(item.getAttribute("id")) for item in items if item.getAttribute("id").isdigit()]
                    item.setAttribute("id", str(max(ids or [0]) + 1))
                    section.appendChild(item)
                    items.append(item)
                attributes = {"name": name, "account": job["account_id"], "accountType": binding[0],
                              "m_strAccountKey": binding[1], "stock": _role_stock(job["settings"], role["role"]),
                              "peroid": str(job["settings"]["period"]), "eStrategyType": "4",
                              "strategymall": "0", "specialType": "48", "recover_type": "14",
                              "runname": "", "strategyRemark": "cfquant managed",
                              "runMode": "1" if job["settings"]["live"] else "0",
                              "startupAutorun": "1" if job["settings"]["autorun"] else "0",
                              "FromulaExpandData": json.dumps({"m_qsFormula": name,
                                  "m_qsAccount": job["account_id"], "variableSize": "0"}, ensure_ascii=True)}
                for key, value in attributes.items():
                    if item.getAttribute(key) != value:
                        item.setAttribute(key, value)
                        changed = True
                role["model_id"] = item.getAttribute("id")
        else:
            for name in owned_names:
                queue = root / "formulas" / (name + ".rzrk")
                if queue.exists():
                    queue.unlink()
        if changed:
            if self.process_checker(root) or config.read_bytes() != original:
                self._state(job, "waiting_exit")
                return
            backup = root / "cfquant_managed" / "backups" / (uuid.uuid4().hex + ".xml")
            _atomic_write(backup, original)
            updated = document.toxml(encoding="utf-8")
            minidom.parseString(updated)
            if self.process_checker(root):
                self._state(job, "waiting_exit")
                return
            _atomic_write(config, updated)
            job["backup"] = str(backup)
        for role in job["roles"]:
            if role.get("model_id"):
                role["model_prepared"] = True
        self._state(job, state)

    def _observe_runtime(self, job):
        if not job["enabled"]:
            self._state(job, "waiting_exit")
            return
        prepared = all(role.get("model_prepared") for role in job["roles"])
        if not prepared:
            state = "waiting_import_save" if any(role.get("queued") and not role.get("imported") for role in job["roles"]) else "waiting_exit"
            self._state(job, state)
            return
        transition_generations = set(_generation_values(job.get("accepted_generations")))
        if job.get("control_generation"):
            transition_generations.add(str(job["control_generation"]).strip())
        valid_generations = set([str(job["generation"])]) | transition_generations
        reports = []
        states = []
        for role in job["roles"]:
            try:
                report = json.loads(Path(role["runtime_status_path"]).read_text(encoding="utf-8"))
                report_generation = str(report.get("generation") or "").strip()
                valid = (report_generation in valid_generations
                         and 0 <= time.time() - float(report.get("updated_at", 0)) < 10)
                report_state = report.get("state") or ""
                reports.append((valid, report_generation, report_state))
                if valid and report_generation == str(job["generation"]) and report_state == "error":
                    self._state(job, "error", "QMT 策略启动失败: " + str(report.get("error") or role["name"]))
                    return
                states.append(report_state if valid and report_state != "error" else "")
            except (OSError, ValueError, KeyError, TypeError):
                reports.append((False, "", ""))
                states.append("")
        if (transition_generations and reports
                and all(valid and generation == str(job["generation"])
                        and state in ("loaded", "running")
                        for valid, generation, state in reports)):
            self._clear_generation_transition(job)
            self._control(job)
        state = "running" if states and all(item == "running" for item in states) else (
            "waiting_start" if job["settings"]["autorun"] else "waiting_manual_start")
        self._state(job, state)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stopping.clear()
        self.worker = threading.Thread(target=self._run, name="qmt-strategy-deploy", daemon=True)
        self.worker.start()

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.process_once()
            except Exception:
                # Per-target errors are reported by process_once; a state-file
                # write failure will be retried without terminating the worker.
                pass
            self.event.wait(2.0)
            self.event.clear()

    def close(self):
        self.stopping.set()
        self.event.set()
        if self.worker:
            self.worker.join(timeout=5.0)
