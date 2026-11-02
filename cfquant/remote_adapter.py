"""Local allowlisted remote-management adapter; no arbitrary RPC forwarding."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import uuid

import psutil

from .remote_management import (Config, PREFIX, RemoteError, atomic_json,
                                ensure_agent, file_lock, local_info, read_json, request_json, site_url)
from .remote_supervisor import process_identity, same_process
from .qmt_credentials import directory_key

LOCAL_PATHS = {"snapshot", "query", "service-plan", "service-stop", "qmt-restart", "qmt-result"}


def norm(path):
    return os.path.normcase(str(Path(path).resolve()))


def token_for(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def registry_dir():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "cfquant" / "remote-runtime-registry"


def resources(web):
    paths = []
    for row in web.WEB_CONFIG.account_configs().values():
        for key in ("qmt_dir", "qmt_trade_dir"):
            if row.get(key):
                paths.append(directory_key(row[key]))
        for market in (row.get("market_bridges") or {}).values():
            if isinstance(market, dict) and market.get("qmt_dir"):
                paths.append(directory_key(market["qmt_dir"]))
    return {"qmt_dirs": sorted(set(paths)), "lttx_port": web.LTTX_PORT,
            "pipe": str(os.environ.get("CFQUANT_PIPE_NAME") or web.DEFAULT_PIPE_NAME)}


def register_runtime(web):
    record = dict(resources(web), process=process_identity(os.getpid()), config=norm(web.WEB_CONFIG.path))
    atomic_json(registry_dir() / (token_for(record["config"])+".json"), record)
    return record


def check_conflicts(web, qmt_dir=None):
    own = register_runtime(web)
    known = {os.getpid()}
    for path in registry_dir().glob("*.json"):
        other = read_json(path)
        identity = other.get("process")
        if not identity or not same_process(identity):
            continue
        known.add(identity["pid"])
        if other.get("config") == own["config"]:
            continue
        conflict = (directory_key(qmt_dir) in other.get("qmt_dirs", []) if qmt_dir else
                    own["lttx_port"] == other.get("lttx_port") or own["pipe"] == other.get("pipe"))
        if conflict:
            raise RemoteError("resource_conflict", "目标资源与另一套部署共用，请在本地处理")
    # An older web process cannot report its resource ownership. Fail closed.
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            args = p.info.get("cmdline") or []
            if p.pid not in known and any(Path(a).name.lower() in {"cfquant_web_server.py", "cfquant_web_server"} for a in args):
                raise RemoteError("resource_conflict", "检测到未登记的 CFQuant 实例，无法确认资源是否共用")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def launch_settings(web):
    launch_env = {k: v for k, v in os.environ.items() if k.startswith("CFQUANT_") and k != "CFQUANT_REMOTE_PRESERVE_QMT"}
    launch_env.update(CFQUANT_BASE_DIR=web.BASE_DIR, CFQUANT_STATE_DIR=web.STATE_DIR,
                      CFQUANT_RUNTIME_DIR=web.RUNTIME_DIR, CFQUANT_WEB_CONFIG_FILE=web.WEB_CONFIG.path,
                      CFQUANT_WEB_SETTINGS_DB_FILE=web.WEB_CONFIG.settings_db_path,
                      CFQUANT_LTTX_PORT=str(web.LTTX_PORT))
    return {"args": [web.runtime_python_executable(), str(Path(web.__file__).resolve()),
                     "--host", web.WEB_BOUND_HOST or "127.0.0.1", "--port", str(web.WEB_BOUND_PORT or web.WEB_CONFIG.web_port())],
            "env": launch_env, "cwd": web.BASE_DIR, "port": web.WEB_BOUND_PORT or web.WEB_CONFIG.web_port(),
            "resources": resources(web)}


def refresh_launch_settings(web):
    store = Config(web.WEB_CONFIG.path)
    if store.read().get("enabled"):
        launch = launch_settings(web)
        store.update(launch=launch, local_url="http://127.0.0.1:%s" % launch["port"], desired_state="running")


def configure(web, data):
    store = Config(web.WEB_CONFIG.path)
    if not isinstance(data, dict):
        raise RemoteError("invalid_input", "配置格式无效")
    if "account" in data or "password" in data:
        raise RemoteError("api_key_required", "请先在官网创建部署并获取项目 API Key，本地不支持官网账号密码接入")
    with file_lock(store.path.with_suffix(".configure.lock"), wait=10):
        config = store.read()
        if data.get("enabled") is False:
            store.update(enabled=False)
            return local_info(web.WEB_CONFIG.path)
        perms = dict(config.get("permissions", {}))
        for key in ("queries", "service_control", "qmt_control"):
            if key in (data.get("permissions") or {}):
                value = data["permissions"][key]
                if not isinstance(value, bool):
                    raise RemoteError("invalid_permissions", "权限必须为布尔值")
                perms[key] = value
        if "device_id" not in config:
            config["device_id"] = token_for(str(uuid.uuid4())+socket_identity()+norm(web.WEB_CONFIG.path))
        config.setdefault("local_token", secrets.token_urlsafe(32))
        supplied = str(data.get("api_key") or "").strip()
        key = supplied or config.get("api_key")
        if not key:
            raise RemoteError("api_key_required", "请先在官网创建部署并获取项目 API Key，再填写到本地")
        # Keep the existing connection intact until the new key is validated.
        url = site_url()
        response = request_json(url+PREFIX+"/agent/validate", {}, {"X-CFQuant-Remote-Key": key})
        instance = response["instance"]
        launch = launch_settings(web)
        store.update(device_id=config["device_id"], local_token=config["local_token"],
                     enabled=True, site_url=url, api_key=key, instance_id=instance["id"], name=instance["name"], note=instance["note"],
                     permissions=perms, launch=launch, local_url="http://127.0.0.1:%s" % launch["port"], desired_state="running")
        ensure_agent(web.WEB_CONFIG.path)
        return local_info(web.WEB_CONFIG.path)


def socket_identity():
    import socket
    return socket.gethostname()


def bindings(web):
    config = web.WEB_CONFIG.account_configs()
    results, mapping = [], {}
    statuses = {b["account_key"]: b for b in web.binding_status_snapshot()["bindings"]}
    for key, row in config.items():
        bid = token_for(key)
        row = dict(row, account_key=key)
        mapping[bid] = row
        account = str(row.get("account_id") or "")
        status = statuses.get(key, {})
        login = status.get("qmt_auto_login") or {}
        route = status.get("status") or {}
        qmt_dir = row.get("qmt_dir") or row.get("python_dir")
        affected = [token_for(k) for k, r in config.items() if qmt_dir and directory_key(r.get("qmt_dir") or r.get("python_dir") or ".") == directory_key(qmt_dir)]
        revision = token_for(json.dumps(row, sort_keys=True, ensure_ascii=True))
        # Do not claim a remembered login is current after its process exits.
        process = process_identity(login.get("pid", 0))
        alive = bool(process and Path(process["exe"]).name.lower() == "xtitclient.exe" and qmt_dir
                     and directory_key(Path(process["exe"]).parent) == directory_key(qmt_dir))
        results.append({"id": bid, "name": row.get("display_name") or "绑定 "+bid[:6],
                        "account_masked": "***"+account[-4:], "account_type": row.get("account_type"), "mode": row.get("mode"),
                        "live": (row.get("qmt_runtime") or {}).get("live"), "enabled": row.get("enabled", True),
                        "qmt_state": "running" if alive else "unknown", "login_state": login.get("login_state", "unknown") if alive else "unknown",
                        "login_message": (login.get("message") or "")[:200] if alive else "",
                        "bridge_state": "ready" if route.get("ready") else "unavailable",
                        "checked_at": time.time(), "revision": revision, "affected_bindings": sorted(affected)})
    return results, mapping


def require(web, capability=None, boot_id=None):
    config = Config(web.WEB_CONFIG.path).read()
    if not config.get("enabled") or (capability and not config.get("permissions", {}).get(capability)):
        raise RemoteError("permission_denied", "本地未授权此操作")
    if boot_id is not None and boot_id != web.MANAGEMENT_BOOT_ID:
        raise RemoteError("resource_conflict", "服务已重新启动，请刷新后重试")
    return config


def service_plan(web, boot_id):
    require(web, "service_control", boot_id)
    if web.PROJECT_UPDATER.is_busy():
        raise RemoteError("resource_busy", "更新任务正在执行")
    check_conflicts(web)
    identities = [process_identity(os.getpid())]
    entries = {norm(web.PIPE_HUB_ENTRY), norm(web.LTTX_ENTRY)}
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            args = p.info.get("cmdline") or []
            module = any(args[i:i+2] == ["-m", web.PIPE_HUB_MODULE] for i in range(len(args)-1))
            if not module and not any(os.path.isabs(a) and norm(a) in entries for a in args):
                continue
            env = p.environ()
            if not env.get("CFQUANT_RUNTIME_DIR"):
                raise RemoteError("resource_conflict", "相关进程缺少部署归属，请在本地处理")
            belongs = norm(env["CFQUANT_RUNTIME_DIR"]) == norm(web.RUNTIME_DIR)
            if not belongs:
                continue
            identity = process_identity(p.pid)
            if identity:
                identities.append(identity)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            raise RemoteError("resource_conflict", "无法核对相关进程归属，停止操作已拒绝") from None
    return {"boot_id": web.MANAGEMENT_BOOT_ID, "processes": identities}


def handle(web, operation, data):
    config = require(web)
    if operation == "snapshot":
        items, _ = bindings(web)
        return {"instance_id": config["instance_id"], "snapshot": {
            "boot_id": web.MANAGEMENT_BOOT_ID, "version": web.CORE_VERSION,
            "service_state": "running" if web.MANAGEMENT_READY else "starting", "checked_at": time.time(), "bindings": items}}
    if operation in {"service-plan", "service-stop"}:
        return service_plan(web, data.get("boot_id"))
    require(web, "queries" if operation == "query" else "qmt_control",
            data.get("boot_id") if operation != "qmt-result" else None)
    items, mapping = bindings(web)
    row = mapping.get(data.get("binding_id"))
    if not row or not row.get("enabled", True):
        raise RemoteError("binding_not_found", "绑定不存在或已禁用")
    if operation == "query":
        action = data.get("action")
        if action not in {"positions", "orders", "trades"}:
            raise RemoteError("unsupported_action", "不支持的查询")
        page, limit = int(data.get("page", 1)), int(data.get("page_size", 50))
        if not 1 <= page <= 10000 or not 1 <= limit <= 100:
            raise RemoteError("invalid_page", "分页参数无效")
        result = web.ACCOUNT_CACHE.get_market_routed(row["bridge_id"], "trade", row["account_id"], [action],
                    force=True, subscribe=False, account_type=row["account_type"], account_key=row["account_key"], timeout=20)
        section = result.get(action) or {}
        if not section.get("ok") or section.get("stale") or section.get("partial_errors"):
            raise RemoteError("query_failed", "QMT 查询失败，请检查账号模式、桥接及交易 session")
        raw = section.get("data")
        if type(raw).__name__ == "DataFrame":
            raw = raw.to_dict(orient="records")
        values = web.to_jsonable(raw)
        if values is None:
            values = []
        if not isinstance(values, list):
            raise RemoteError("unsupported_result", "该账户暂未提供可分页的查询结果")
        total = len(values)
        values = values[(page-1)*limit:page*limit]
        # Transfer only business fields, never arbitrary runtime configuration.
        columns = {"stock_code", "stock_name", "order_id", "order_sysid", "order_status", "status_msg", "order_type", "order_volume", "price", "price_type", "traded_volume", "traded_price", "order_time", "strategy_name", "order_remark", "traded_id", "traded_time", "traded_amount", "volume", "can_use_volume", "open_price", "market_value", "avg_price", "profit", "frozen_volume", "on_road_volume", "direction", "offset_flag"}
        records = [{k: v for k, v in item.items() if k in columns} for item in values if isinstance(item, dict)]
        return {"binding_id": data["binding_id"], "action": action, "rows": records, "page": page, "page_size": limit,
                "has_more": page*limit < total, "checked_at": section.get("checked_at"),
                "source": "QMT", "cache": bool(section.get("cached", False))}
    if operation == "qmt-result":
        result = web._qmt_auto_login_saved_session(row)
        if result.get("pid") != data.get("pid"):
            raise RemoteError("resource_conflict", "QMT 登录任务已被替换")
        if not process_identity(data.get("pid")):
            raise RemoteError("qmt_exited", "QMT 已退出，请检查本地登录状态")
        if result.get("login_state") == "client_login" and next(b for b in items if b["id"] == data["binding_id"])["bridge_state"] == "ready":
            result = dict(result, login_succeeded=True, state="logged_in", login_state="logged_in", message="QMT 交易桥接已恢复")
        return {k: result.get(k) for k in ("pid", "state", "login_state", "login_succeeded", "message")}
    if operation == "qmt-restart":
        item = next(b for b in items if b["id"] == data["binding_id"])
        if data.get("binding_revision") != item["revision"] or sorted(data.get("affected_bindings", [])) != item["affected_bindings"]:
            raise RemoteError("resource_conflict", "QMT 绑定配置已变化，请刷新并确认")
        check_conflicts(web, row["qmt_dir"])
        if web.PROJECT_UPDATER.is_busy():
            raise RemoteError("resource_busy", "项目正在更新")
        result = web.complete_qmt_auto_login({"account_key": row["account_key"]})
        if result.get("error") or not result.get("pid"):
            raise RemoteError("qmt_restart_failed", "QMT 重启失败，请检查自动登录配置与依赖")
        return {"pid": result["pid"]}
    raise RemoteError("unsupported_action", "不支持的操作")
