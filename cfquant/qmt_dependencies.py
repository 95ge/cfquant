"""Read-only checks and repair instructions for optional QMT login components."""

from .diagnostic_context import VersionedErrorMixin
from ._pywin32_runtime import prepare_pywin32_runtime
import copy
import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
import threading
import time


LOGIN_MODULES = ("frida", "win32api", "win32crypt", "win32event", "win32gui", "win32process")
# Verified QMT baseline. 17.25 introduced a Windows mapper that can abort the
# host on older ntdll builds; do not widen this without Windows/QMT validation.
FRIDA_VERSION = "17.16.4"
FRIDA_REQUIREMENT = "frida==" + FRIDA_VERSION
_LOCK = threading.Lock()
_CACHE = {}
_PROBE_CODE = "RUNTIME_HELPER = %s\n" % ascii(os.path.join(os.path.dirname(__file__), "_pywin32_runtime.py")) + r'''
import importlib, importlib.metadata, json, os, pathlib, runpy, sys
runtime = runpy.run_path(RUNTIME_HELPER)
runtime_info = {}
runtime_error = None
try:
    runtime_info = runtime['prepare_pywin32_runtime']()
except (ImportError, OSError) as error:
    runtime_error = error
checks = []
for name in MODULES:
    try:
        if name.startswith('win32') and runtime_error is not None:
            raise runtime_error
        if name == 'frida' and importlib.metadata.version('frida') != FRIDA_VERSION:
            raise RuntimeError('Unsupported Frida version; install frida==' + FRIDA_VERSION)
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
base_prefix = pathlib.Path(getattr(sys, 'base_prefix', sys.prefix))
conda = (prefix / 'conda-meta').is_dir()
venv = not conda and prefix != base_prefix
environment = 'conda' if conda else 'venv' if venv else 'python'
print(json.dumps(dict(python_executable=sys.executable, python_version=sys.version.split()[0],
    prefix=str(prefix), base_prefix=str(base_prefix), environment=environment,
    global_python=sys.prefix == sys.base_prefix,
    conda_executable=os.environ.get('CONDA_EXE', '') if conda else '',
    pywin32_runtime=runtime_info, **runtime['pywin32_installation'](),
    supported=sys.platform == 'win32', checks=checks, packages=packages), ensure_ascii=True))
'''


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _finish_report(report):
    if report.get("supported"):
        version = (report.get("packages") or {}).get("frida")
        if version and version != FRIDA_VERSION:
            checks = report.setdefault("checks", [])
            check = next((item for item in checks if item["name"] == "frida"), None)
            if check is None:
                check = {"name": "frida"}
                checks.append(check)
            check.update(ok=False, error="Frida %s 未通过本项目兼容性验证，请安装 %s" % (version, FRIDA_REQUIREMENT))
        report["frida_requirement"] = FRIDA_REQUIREMENT
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
    environment = str(report.get("environment") or "").lower()
    if environment not in {"conda", "venv", "python"}:
        environment = "python" if report.get("global_python") else "venv"
    if report.get("supported") and failed:
        if any(item["name"].startswith("win32") for item in failed):
            if environment == "conda" and report.get("conda_pywin32"):
                conda = report.get("conda_executable") or "conda"
                commands.append("& %s install --prefix %s --force-reinstall 'pywin32>=306'" % (
                    _ps_quote(conda), _ps_quote(report["prefix"])))
            else:
                commands.append(python + " -m pip install --no-cache-dir --upgrade --force-reinstall 'pywin32>=306'")
                if environment == "python":
                    commands.append(python + " -m pywin32_postinstall -install")
        if any(item["name"] == "frida" for item in failed):
            commands.append(python + " -m pip install --no-cache-dir --force-reinstall '" + FRIDA_REQUIREMENT + "'")
        commands.append(python + " -c " + _ps_quote(
            "from cfquant.qmt_dependencies import report_startup_dependencies; "
            "r=report_startup_dependencies(); raise SystemExit(0 if r['ok'] else 1)"))
    report["repair_commands"] = commands
    if environment == "conda":
        report["repair_note"] = (
            "已检测到 Conda 环境。pywin32 已安装但提示“找不到指定的程序”时，通常是新版组件加载了残留的旧版 DLL。"
            "先停止 CFQuant，在已激活该环境的 PowerShell 中逐行执行下面的命令；命令已绑定当前环境。"
            "不要在 Conda 环境运行 pywin32_postinstall。验证通过后重启 CFQuant，再重新检测。"
        )
    elif environment == "venv":
        report["repair_note"] = (
            "已检测到 venv 虚拟环境。先停止 CFQuant，在普通 PowerShell 中执行下面的命令；"
            "命令已绑定当前 venv 的 Python，不要切换到系统 Python，也不要运行 pywin32_postinstall。"
            "验证通过后重启 CFQuant，再重新检测。"
        )
    else:
        report["repair_note"] = (
            "已检测到独立 Python 环境。先停止 CFQuant，在 PowerShell 中执行下面的命令；"
            "命令已绑定当前 Python，安装完成后会执行 pywin32_postinstall。"
            "验证通过后重启 CFQuant，再重新检测。"
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
                [executable, "-c", "MODULES = %r\nFRIDA_VERSION = %r\n" % (LOGIN_MODULES, FRIDA_VERSION) + _PROBE_CODE],
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


class QmtDependencyError(VersionedErrorMixin, RuntimeError):
    pass


def require_compatible_frida():
    try:
        version = importlib.metadata.version("frida")
    except importlib.metadata.PackageNotFoundError:
        version = "未安装"
    if version != FRIDA_VERSION:
        raise QmtDependencyError(
            "Frida %s 未通过本项目兼容性验证，已跳过 QMT 自动操作。"
            "请在当前 Python 环境安装 %s；手动登录及行情交易接口仍可使用。" % (version, FRIDA_REQUIREMENT))


def import_login_module(name):
    """Keep in-process import errors actionable, including stale loaded DLLs."""
    if name == "frida":
        require_compatible_frida()
    try:
        if name.startswith("win32"):
            prepare_pywin32_runtime()
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
