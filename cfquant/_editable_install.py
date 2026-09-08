# -*- coding: utf-8 -*-
"""Bootstrap editable source installs for the local startup scripts."""

from __future__ import print_function

import os
import subprocess
import sys
import tempfile
from pathlib import Path


PACKAGE_NAME = "cfquant"
INSTALLED_CHECK_CODE = (
    "import importlib.metadata as metadata; "
    "metadata.distribution(%r)"
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


def editable_install_args(project_root, python_exe=None):
    # The caller runs pip with cwd=project_root; "." stays a separate argv item
    # and avoids cmd/path quoting problems in Windows Chinese directories.
    return [
        python_exe or sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--editable",
        ".",
    ]


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
        print("%s is already installed; skip editable source install." % PACKAGE_NAME)
        return 0

    command = editable_install_args(project_root, python_exe)
    print("%s is not installed; installing the current project source." % PACKAGE_NAME)
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
