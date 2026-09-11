# -*- coding: utf-8 -*-
"""Bootstrap editable source installs for the local startup scripts."""

from __future__ import print_function

import os
import subprocess
import sys
import tempfile
from pathlib import Path


PACKAGE_NAME = "cfquant"
DEFAULT_PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_INDEX_URL_ENV = "CFQUANT_PIP_INDEX_URL"
INSTALLED_CHECK_CODE = (
    "import importlib.metadata as metadata\n"
    "metadata.distribution(%r)\n"
    "try:\n"
    "    from Crypto.Cipher import AES\n"
    "except ImportError:\n"
    "    from Cryptodome.Cipher import AES"
) % PACKAGE_NAME


def configure_stdio():
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def installed_check_args(python_exe=None):
    return [python_exe or sys.executable, "-c", INSTALLED_CHECK_CODE]


def pip_index_args():
    """Return the configured pip index, defaulting to the Tsinghua mirror."""
    index_url = os.environ.get(PIP_INDEX_URL_ENV, DEFAULT_PIP_INDEX_URL).strip()
    return ["--index-url", index_url] if index_url else []


def editable_install_args(project_root, python_exe=None):
    # The caller runs pip with cwd=project_root; "." stays a separate argv item
    # and avoids cmd/path quoting problems in Windows Chinese directories.
    command = [
        python_exe or sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
    ]
    command.extend(pip_index_args())
    command.append("--editable")
    command.append(".")
    return command


def requirements_install_args(project_root, python_exe=None):
    """Build the pip command used to install the project's runtime dependencies."""
    command = [
        python_exe or sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
    ]
    command.extend(pip_index_args())
    command.extend(["-r", "requirements.txt"])
    return command


def _output_tail(value, limit=6000):
    text = str(value or "")
    if len(text) <= int(limit):
        return text
    return "...(output truncated)...\n" + text[-int(limit):]


def _run_pip_command(
    command,
    project_root,
    timeout=180.0,
    output_limit=6000,
    subprocess_kwargs=None,
):
    kwargs = {
        "cwd": str(project_root),
        "env": python_environment(clear_pythonpath=True),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": float(timeout),
    }
    if subprocess_kwargs:
        kwargs.update(dict(subprocess_kwargs))
    try:
        completed = subprocess.run(command, **kwargs)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "timed_out": False,
            "output": _output_tail(completed.stdout, output_limit),
            "error": "",
        }
    except subprocess.TimeoutExpired as error:
        output = error.output if error.output is not None else error.stdout
        return {
            "ok": False,
            "returncode": None,
            "timed_out": True,
            "output": _output_tail(output, output_limit),
            "error": "pip command timed out",
        }
    except Exception as error:
        return {
            "ok": False,
            "returncode": None,
            "timed_out": False,
            "output": _output_tail(error, output_limit),
            "error": str(error),
        }


def run_requirements_install(
    project_root,
    python_exe=None,
    timeout=180.0,
    output_limit=6000,
    subprocess_kwargs=None,
):
    """Install requirements.txt and return a serializable result."""
    project_root = Path(project_root).resolve()
    requirements_file = project_root / "requirements.txt"
    result = {
        "attempted": False,
        "ok": True,
        "skipped": False,
        "project_dir": str(project_root),
        "requirements_file": str(requirements_file),
        "python_executable": str(python_exe or sys.executable),
        "command": [],
        "command_text": "",
        "returncode": None,
        "timed_out": False,
        "output": "",
        "message": "",
    }
    if not requirements_file.is_file():
        result.update({
            "skipped": True,
            "message": "requirements.txt not found; skipped project requirements install",
        })
        return result

    command = [str(item) for item in requirements_install_args(
        project_root,
        python_exe=python_exe,
    )]
    result.update({
        "attempted": True,
        "command": command,
        "command_text": subprocess.list2cmdline(command),
    })
    execution = _run_pip_command(
        command,
        project_root,
        timeout=timeout,
        output_limit=output_limit,
        subprocess_kwargs=subprocess_kwargs,
    )
    result.update(execution)
    if result["ok"]:
        result["message"] = "project requirements install completed"
    elif result["timed_out"]:
        result["message"] = "project requirements install timed out"
    elif result["returncode"] is not None:
        result["message"] = (
            "project requirements install failed with exit code %s"
            % result["returncode"]
        )
    else:
        result["message"] = "project requirements install failed: %s" % (
            result.get("error") or "unknown error"
        )
    return result


def run_editable_install(
    project_root,
    python_exe=None,
    timeout=180.0,
    output_limit=6000,
    subprocess_kwargs=None,
):
    """Run pip editable installation and return a serializable result."""
    project_root = Path(project_root).resolve()
    result = {
        "attempted": False,
        "ok": True,
        "skipped": False,
        "project_dir": str(project_root),
        "python_executable": str(python_exe or sys.executable),
        "command": [],
        "command_text": "",
        "returncode": None,
        "timed_out": False,
        "output": "",
        "installed_version": "",
        "message": "",
        "requirements_install": None,
        "requirements_attempted": False,
        "editable_attempted": False,
    }
    if not (project_root / "pyproject.toml").is_file():
        result.update({
            "skipped": True,
            "message": "pyproject.toml not found; skipped editable source install",
        })
        return result

    requirements = run_requirements_install(
        project_root,
        python_exe=python_exe,
        timeout=timeout,
        output_limit=output_limit,
        subprocess_kwargs=subprocess_kwargs,
    )
    result["requirements_install"] = requirements
    result["requirements_attempted"] = bool(requirements.get("attempted"))
    if not requirements.get("ok"):
        result.update({
            "attempted": bool(requirements.get("attempted")),
            "ok": False,
            "returncode": requirements.get("returncode"),
            "timed_out": bool(requirements.get("timed_out")),
            "output": requirements.get("output") or "",
            "message": requirements.get("message") or "project requirements install failed",
        })
        return result

    command = editable_install_args(project_root, python_exe=python_exe)
    result.update({
        "attempted": True,
        "editable_attempted": True,
        "command": [str(item) for item in command],
        "command_text": subprocess.list2cmdline([str(item) for item in command]),
    })
    kwargs = {
        "cwd": str(project_root),
        "env": python_environment(clear_pythonpath=True),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": float(timeout),
    }
    if subprocess_kwargs:
        kwargs.update(dict(subprocess_kwargs))
    try:
        completed = subprocess.run(command, **kwargs)
        output = _output_tail(completed.stdout, output_limit)
        result["returncode"] = completed.returncode
        result["output"] = output
        result["ok"] = completed.returncode == 0
        if result["ok"]:
            try:
                try:
                    from importlib import metadata as importlib_metadata
                except ImportError:
                    import importlib_metadata
                result["installed_version"] = str(importlib_metadata.version(PACKAGE_NAME))
            except Exception:
                pass
            result["message"] = "cfquant 源码可编辑安装已完成"
        else:
            result["message"] = "cfquant 源码可编辑安装失败，退出码 %s" % completed.returncode
    except subprocess.TimeoutExpired as error:
        output = error.output if error.output is not None else error.stdout
        result.update({
            "ok": False,
            "timed_out": True,
            "output": _output_tail(output, output_limit),
            "message": "cfquant 源码可编辑安装超时",
        })
    except Exception as error:
        result.update({
            "ok": False,
            "output": _output_tail(error, output_limit),
            "message": "cfquant 源码可编辑安装异常：%s" % error,
        })
    return result


def python_environment(clear_pythonpath=False):
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if clear_pythonpath:
        env.pop("PYTHONPATH", None)
    return env


def neutral_check_cwd():
    return Path(tempfile.gettempdir()).resolve()


def run(args, cwd, quiet=False, clear_pythonpath=False):
    stdout = subprocess.DEVNULL if quiet else None
    stderr = subprocess.DEVNULL if quiet else None
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        env=python_environment(clear_pythonpath=clear_pythonpath),
        stdout=stdout,
        stderr=stderr,
    )


def is_cfquant_installed(python_exe=None):
    # Run outside the source tree so a leftover local cfquant.egg-info cannot
    # masquerade as an installed package in the active Python environment.
    completed = run(
        installed_check_args(python_exe),
        neutral_check_cwd(),
        quiet=True,
        clear_pythonpath=True,
    )
    return completed.returncode == 0


def ensure_cfquant_installed(project_root, python_exe=None):
    project_root = Path(project_root).resolve()
    if not (project_root / "pyproject.toml").is_file():
        print("[ERROR] pyproject.toml not found: %s" % project_root, file=sys.stderr)
        return 2

    python_exe = python_exe or sys.executable
    print("Checking whether %s is installed in this Python environment..." % PACKAGE_NAME)
    if is_cfquant_installed(python_exe):
        print("%s and its runtime dependencies are ready; skip editable source install." % PACKAGE_NAME)
        return 0

    command = editable_install_args(project_root, python_exe)
    print("%s or its runtime dependencies are missing; installing the current project source." % PACKAGE_NAME)
    print("Running: %s" % subprocess.list2cmdline(command))
    completed = run(command, project_root)
    if completed.returncode != 0:
        print("[ERROR] editable source install failed with exit code %s." % completed.returncode, file=sys.stderr)
        return completed.returncode

    if not is_cfquant_installed(python_exe):
        print("[ERROR] %s is still not visible after editable install." % PACKAGE_NAME, file=sys.stderr)
        return 1
    print("%s package is installed." % PACKAGE_NAME)
    return 0


def main(argv=None):
    configure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    project_root = argv[0] if argv else Path(__file__).resolve().parents[1]
    return ensure_cfquant_installed(project_root)


if __name__ == "__main__":
    raise SystemExit(main())
