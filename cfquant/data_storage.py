"""Installation-local data accounting and conservative log retention (stdlib only)."""
import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import uuid

DEFAULT_POLICY = {"mode": "days", "days": 30, "max_bytes": 1024 ** 3}
LOG_SUFFIXES = {".log", ".txt", ".csv"}
QUIET_SECONDS = 300


def stream_digest(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.digest()


def linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def safe_root(root):
    root = Path(root).absolute()
    if not root.is_absolute() or root.name.lower() != "data":
        raise ValueError("数据目录必须为安装目录下的 data 文件夹")
    for parent in (root, *root.parents):
        if parent.exists() and linked(parent):
            raise ValueError("数据目录不能经过符号链接或目录联接")
    if not root.is_dir():
        raise ValueError("数据目录不存在")
    return root


def safe_child(root, name):
    candidate = root / name
    if not name or Path(name).is_absolute() or any(p in {"..", "."} for p in Path(name).parts):
        raise ValueError("无效的数据路径")
    for parent in (candidate, *candidate.parents):
        if parent == root:
            return candidate
        if parent.exists() and linked(parent):
            raise ValueError("不允许访问链接或目录联接")
    raise ValueError("数据路径超出管理范围")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_policy(value):
    if not isinstance(value, dict) or value.get("mode") not in {"days", "forever", "size"}:
        raise ValueError("请选择按天数、永久保存或按容量保留")
    result = dict(DEFAULT_POLICY, **value)
    if type(result["days"]) is not int or not 1 <= result["days"] <= 3650:
        raise ValueError("保留天数必须为 1 至 3650 的整数")
    if type(result["max_bytes"]) is not int or not 1024 ** 2 <= result["max_bytes"] <= 1024 ** 4:
        raise ValueError("日志容量上限必须在 1 MB 至 1 TB 之间")
    return {key: result[key] for key in DEFAULT_POLICY}


def policy_path(root):
    return safe_child(root, "config/log-retention.json")


def read_policy(root):
    path = policy_path(root)
    if not path.exists():
        return dict(DEFAULT_POLICY)
    # Corrupt policy must stop cleanup, never silently enable destructive defaults.
    return validate_policy(json.loads(path.read_text(encoding="utf-8")))


def save_policy(root, policy):
    root = safe_root(root)
    policy = validate_policy(policy)
    atomic_json(policy_path(root), policy)
    return policy


def files_under(root, directory):
    base = safe_child(root, directory)
    if not base.is_dir():
        return
    for current, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = [name for name in dirs if not linked(Path(current, name))]
        for name in files:
            path = Path(current, name)
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or linked(path) or info.st_nlink != 1:
                    continue
                yield path, info
            except FileNotFoundError:
                continue


def log_file(path):
    return path.suffix.lower() in LOG_SUFFIXES or ".log." in path.name.lower()


def log_rows(root):
    rows = []
    for path, info in files_under(root, "logs"):
        if log_file(path):
            rows.append({"name": path.relative_to(root / "logs").as_posix(), "size": info.st_size,
                         "modified": info.st_mtime, "identity": (info.st_dev, info.st_ino),
                         "protected": time.time() - info.st_mtime < QUIET_SECONDS})
    return rows


@contextlib.contextmanager
def maintenance_lock(root):
    path = safe_child(root, "config/log-maintenance.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def closed_file(path):
    """Hold a Windows deny-sharing handle throughout copying or deletion."""
    if os.name == "nt":
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetFileInformationByHandle.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(path), 0x80000000 | 0x10000, 0, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "日志正在使用或无删除权限")
        descriptor = None
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
            def remove():
                delete = ctypes.c_ubyte(1)
                if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
                    raise OSError(ctypes.get_last_error(), "无法删除文件")
            with os.fdopen(descriptor, "rb", closefd=False) as reader:
                yield reader, remove
        finally:
            if descriptor is None:
                kernel.CloseHandle(handle)
            else:
                os.close(descriptor)
    else:
        with path.open("rb") as reader:
            import fcntl
            fcntl.flock(reader.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield reader, path.unlink


def delete_closed_log(root, row, now):
    path = safe_child(root, "logs/" + row["name"])
    info = path.lstat()
    if not log_file(path) or info.st_nlink != 1 or linked(path) or not stat.S_ISREG(info.st_mode):
        raise ValueError("不是可清理的普通日志文件")
    if (info.st_dev, info.st_ino) != tuple(row["identity"]) or info.st_size != row["size"] or info.st_mtime != row["modified"]:
        raise ValueError("日志在扫描后已变化，已跳过")
    if now - info.st_mtime < QUIET_SECONDS:
        raise ValueError("日志最近仍在写入，已跳过")
    with closed_file(path) as (reader, remove):
        current = os.fstat(reader.fileno())
        if (current.st_dev, current.st_ino) != tuple(row["identity"]) or current.st_nlink != 1:
            raise ValueError("日志文件已变化")
        remove()
    return info.st_size


def cleanup(root, selected=None):
    root = safe_root(root)
    with maintenance_lock(root):
        policy = read_policy(root)
        rows = log_rows(root)
        total = sum(row["size"] for row in rows)
        result = {"deleted_files": 0, "deleted_bytes": 0, "skipped_files": 0, "errors": [], "ran_at": time.time()}
        if selected is not None:
            if not isinstance(selected, list) or not selected or len(selected) > 200 or any(not isinstance(n, str) for n in selected):
                raise ValueError("请选择 1 至 200 个日志文件")
            unknown = set(selected) - {row["name"] for row in rows}
            if unknown:
                raise ValueError("所选日志不存在或不在管理范围，请刷新列表")
            rows = [row for row in rows if row["name"] in selected]
        for row in sorted(rows, key=lambda row: (row["modified"], row["name"])):
            eligible = selected is not None or (
                policy["mode"] == "days" and row["modified"] < time.time() - policy["days"] * 86400
            ) or (policy["mode"] == "size" and total > policy["max_bytes"])
            if not eligible:
                continue
            try:
                removed = delete_closed_log(root, row, time.time())
                result["deleted_files"] += 1
                result["deleted_bytes"] += removed
                total -= removed
            except (OSError, ValueError) as error:
                result["skipped_files"] += 1
                if len(result["errors"]) < 20:
                    result["errors"].append({"name": row["name"], "reason": str(error)})
        result["remaining_bytes"] = total
        result["over_limit_bytes"] = max(0, total - policy["max_bytes"]) if policy["mode"] == "size" else 0
        atomic_json(safe_child(root, "config/log-cleanup-last.json"), result)
        return result


def summary(root):
    root = safe_root(root)
    categories = []
    for name, title in [("logs", "日志"), ("runtime", "运行数据"), ("desktop", "桌面配置与会话"),
                        ("webview", "界面缓存"), ("cache", "缓存"), ("temp", "临时文件"),
                        ("migration-backup", "迁移保留数据"), ("appdata", "组件数据"),
                        ("config", "数据管理配置"), ("helpers", "维护组件")]:
        entries = list(files_under(root, name))
        categories.append({"key": name, "title": title, "size": sum(info.st_size for _, info in entries), "files": len(entries)})
    rows = sorted(log_rows(root), key=lambda row: row["modified"], reverse=True)
    for row in rows:
        row.pop("identity")
    last_path = safe_child(root, "config/log-cleanup-last.json")
    migration = safe_child(root, "config/migration-report.json")
    return {"data_root": str(root), "logs_root": str(root / "logs"), "policy": read_policy(root),
            "categories": categories, "total_bytes": sum(item["size"] for item in categories),
            "log_bytes": sum(row["size"] for row in rows), "log_count": len(rows), "logs": rows[:200],
            "list_truncated": len(rows) > 200, "last_cleanup": json.loads(last_path.read_text(encoding="utf-8")) if last_path.exists() else None,
            "migration": json.loads(migration.read_text(encoding="utf-8")) if migration.exists() else None}


def migrate_file(source, destination):
    """Copy, verify and remove exactly one closed source; never overwrite user data."""
    before = source.stat()
    if linked(source) or before.st_nlink != 1:
        raise ValueError("迁移跳过链接文件")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".migration-" + uuid.uuid4().hex)
    digest = hashlib.sha256()
    try:
        with closed_file(source) as (reader, remove):
            current = os.fstat(reader.fileno())
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("迁移源文件已变化")
            with temporary.open("xb") as writer:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(block)
                    digest.update(block)
                writer.flush()
                os.fsync(writer.fileno())
            after = os.fstat(reader.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError("源文件仍在变化，请关闭旧客户端后重试迁移")
            with temporary.open("rb") as check:
                verified = stream_digest(check)
            if digest.digest() != verified:
                raise ValueError("数据迁移校验失败")
            os.utime(temporary, ns=(before.st_atime_ns, before.st_mtime_ns))
            if destination.exists():
                with destination.open("rb") as existing:
                    if stream_digest(existing) != digest.digest():
                        raise FileExistsError("目标已有不同内容，保留源文件")
            else:
                os.replace(temporary, destination)
            remove()
        return before.st_size
    finally:
        temporary.unlink(missing_ok=True)


def initialize(root, sources):
    root = safe_root(root)
    for directory in ("config", "logs/core", "logs/desktop", "logs/installer", "runtime", "desktop", "webview", "cache", "temp", "appdata/Local", "appdata/Roaming"):
        safe_child(root, directory).mkdir(parents=True, exist_ok=True)
    if not policy_path(root).exists():
        save_policy(root, DEFAULT_POLICY)
    report = {"moved_files": 0, "moved_bytes": 0, "errors": [], "checked_at": time.time()}
    for source_spec in sources:
        source = Path(source_spec["source"])
        destination = safe_child(root, source_spec["destination"])
        if not source.exists() or source.resolve() == destination.resolve():
            continue
        if any(linked(p) for p in (source, *source.parents) if p.exists()):
            report["errors"].append({"source": str(source), "reason": "迁移跳过链接目录"})
            continue
        pairs = [(source, destination)] if source.is_file() else []
        if source.is_dir():
            for current, dirs, files in os.walk(source, followlinks=False):
                dirs[:] = [name for name in dirs if not linked(Path(current, name))]
                pairs.extend((Path(current, name), destination / Path(current, name).relative_to(source)) for name in files)
        for old, new in pairs:
            try:
                safe_child(root, new.relative_to(root).as_posix())
                if new.exists():
                    with old.open("rb") as a, new.open("rb") as b:
                        different = stream_digest(a) != stream_digest(b)
                    if different:
                        key = hashlib.sha256(str(old).encode("utf-8")).hexdigest()[:16]
                        new = safe_child(root, "migration-backup/" + key + "/" + old.name)
                report["moved_bytes"] += migrate_file(old, new)
                report["moved_files"] += 1
            except (OSError, ValueError) as error:
                if len(report["errors"]) < 40:
                    report["errors"].append({"source": str(old), "reason": str(error)})
        if source.is_dir():
            # Only remove now-empty directories within this exact migration source.
            for current, _, _ in os.walk(source, topdown=False, followlinks=False):
                path = Path(current)
                if path == source or source in path.parents:
                    try:
                        if not linked(path):
                            path.rmdir()
                    except OSError:
                        pass
    atomic_json(safe_child(root, "config/migration-report.json"), report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--action", choices=["summary", "cleanup", "save", "initialize"], required=True)
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args()
    root = safe_root(args.root)
    payload = json.loads(args.payload)
    if args.action == "summary":
        result = summary(root)
    elif args.action == "cleanup":
        result = cleanup(root, payload.get("selected"))
    elif args.action == "save":
        result = save_policy(root, payload)
    else:
        result = initialize(root, payload.get("sources", []))
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
