"""Read-only checks and repair instructions for optional QMT login components."""
import copy
import importlib
import json
import os
import subprocess
import sys
import threading
import time


LOGIN_MODULES = ("frida", "win32api", "win32crypt", "win32event", "win32gui", "win32process")
_LOCK = threading.Lock()
_CACHE = {}
_PROBE_CODE = r'''
import importlib, importlib.metadata, json, pathlib, sys
checks = []
for name in MODULES:
    try:
        module = importlib.import_module(name)
        checks.append(dict(name=name, ok=True, path=getattr(module, '__file__', '')))
    except Exception as error:
        checks.append(dict(name=name, ok=False, error=str(error), error_type=type(error).__name__))
packages = {}
for name in ('pywin32', 'frida'):
    try:
        packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        packages[name] = ''
prefix = pathlib.Path(sys.prefix)
conda = (prefix / 'conda-meta').is_dir()
print(json.dumps(dict(python_executable=sys.executable, python_version=sys.version.split()[0],
    prefix=str(prefix), environment='conda' if conda else 'venv' if sys.prefix != sys.base_prefix else 'python',
    global_python=sys.prefix == sys.base_prefix,
    conda_pywin32=conda and bool(list((prefix / 'conda-meta').glob('pywin32-*.json'))),
    supported=sys.platform == 'win32', checks=checks, packages=packages), ensure_ascii=True))
'''


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _finish_report(report):
    report["checked_at"] = time.time()
    report["ok"] = bool(report.get("supported") and not report.get("error")
                        and all(item["ok"] for item in report.get("checks", [])))
    failed = [item for item in report.get("checks", []) if not item["ok"]]
    if not report.get("supported") and not report.get("error"):
        report["message"] = "当前系统不支持 QMT 组件自动登录，请手动启动并登录 QMT。"
    elif report["ok"]:
        report["message"] = "QMT 自动登录组件检测通过。"
    else:
        names = "、".join(item["name"] for item in failed) or "Python 环境"
        report["message"] = "QMT 自动登录组件不可用（%s）。可取消自动启动，保存配置后手动启动并登录 QMT。" % names
    commands = []
    python = "& " + _ps_quote(report["python_executable"])
    if report.get("supported") and failed:
        if any(item["name"].startswith("win32") for item in failed):
            if report.get("conda_pywin32"):
                commands.append("conda install --prefix %s --force-reinstall 'pywin32>=306'" % _ps_quote(report["prefix"]))
            else:
                commands.append(python + " -m pip install --no-cache-dir --force-reinstall 'pywin32>=306'")
                if report.get("global_python"):
                    commands.append(python + " -m pywin32_postinstall -install")
        if any(item["name"] == "frida" for item in failed):
            commands.append(python + " -m pip install --no-cache-dir --force-reinstall 'frida>=17.0,<18'")
        commands.append(python + " -c " + _ps_quote("import " + ", ".join(LOGIN_MODULES) + "; print('QMT login components OK')"))
    report["repair_commands"] = commands
    report["repair_note"] = (
        "先停止 CFQuant，再在此电脑的 PowerShell 中执行；Conda 命令请使用 Anaconda PowerShell Prompt。"
        "验证通过后重启 CFQuant，再重新检测。若仍报 DLL 错误，需要检查旧 DLL 残留；"
        "虚拟环境中不要运行 pywin32_postinstall。"
    )
    return report


def check_login_dependencies(python_exe=None, refresh=False, timeout=15):
    """Probe the actual interpreter without installing packages or loading DLLs here."""
    executable = str(python_exe or sys.executable)
    with _LOCK:
        if not refresh and executable in _CACHE:
            return copy.deepcopy(_CACHE[executable])
        report = {"python_executable": executable, "supported": sys.platform == "win32", "checks": []}
        if not report["supported"]:
            _CACHE[executable] = _finish_report(report)
            return copy.deepcopy(_CACHE[executable])
        try:
            run_kwargs = {}
            if os.name == "nt":
                run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(
                [executable, "-c", "MODULES = %r\n" % (LOGIN_MODULES,) + _PROBE_CODE],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
                **run_kwargs,
            )
            if completed.returncode:
                raise RuntimeError((completed.stderr or completed.stdout or "Python dependency probe failed")[-4000:])
            # Startup hooks may print before our JSON report.
            report.update(json.loads(completed.stdout.strip().splitlines()[-1]))
        except Exception as error:
            report["error"] = str(error)
        _CACHE[executable] = _finish_report(report)
        return copy.deepcopy(_CACHE[executable])


class QmtDependencyError(RuntimeError):
    pass


def import_login_module(name):
    """Keep in-process import errors actionable, including stale loaded DLLs."""
    try:
        return importlib.import_module(name)
    except (ImportError, OSError) as error:
        raise QmtDependencyError(
            "QMT 自动登录组件 %s 无法加载；运行环境：%s；原因：%s。"
            "请查看自动登录组件检测中的修复说明，或取消自动启动后手动登录 QMT。"
            % (name, sys.executable, error)
        ) from error


def report_startup_dependencies(python_exe=None):
    report = check_login_dependencies(python_exe, refresh=True)
    if not report.get("supported"):
        return report
    level = "INFO" if report["ok"] else "WARN"
    print("[%s] %s Python=%s" % (level, report["message"], report["python_executable"]))
    for item in report["checks"]:
        if not item["ok"]:
            print("[WARN] %s: %s" % (item["name"], item["error"]))
    if report.get("error"):
        print("[WARN] %s" % report["error"])
    for command in report["repair_commands"]:
        print("[REPAIR] %s" % command)
    return report
