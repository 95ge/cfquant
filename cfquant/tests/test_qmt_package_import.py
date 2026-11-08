"""Cold imports in the host interpreter and an optional real QMT Python 3.6.

Set CFQUANT_TEST_PYTHON36 to QMT's bin.x64/pythonw.exe (or python.exe).
The subprocess only imports modules; it never starts a bridge or a strategy.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
PROBE = r'''
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[2])
if sys.argv[3]:
    sys.path[1:1] = [sys.argv[3] + "/lib", sys.argv[3] + "/DLLs"]

import importlib
import json
import traceback

result = {"version": list(sys.version_info[:3])}
try:
    # Reproduce the first import in _install_logging_compat, then load the
    # dependencies used by the ctypes and LTtx strategy entries.
    for name in ("logging_i18n", "pipe_bridge", "qmt_pipe_runtime", "qmt_bridge"):
        importlib.import_module("cfquant." + name)
    import cfquant
    namespace = {}
    exec("from cfquant import *", namespace)
    for name in ("xtdata", "xtconstant", "xttrader", "QmtInnerApi"):
        assert name in namespace, name
    if sys.version_info[:2] == (3, 6):
        assert "cfquant.qmt_python_runtime" not in sys.modules
        assert "QmtPythonRuntime" not in namespace
    else:
        from cfquant import qmt_python_runtime
        for name in ("QmtPythonRuntime", "QmtPythonRuntimeError",
                     "QmtPythonPackage", "QmtPythonProgress"):
            assert namespace[name] is getattr(qmt_python_runtime, name), name
        progress = cfquant.QmtPythonProgress("py36", "download")
        assert progress.as_dict()["phase"] == "download"
    result["ok"] = True
except BaseException:
    result["error"] = traceback.format_exc()
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump(result, stream)
'''


@pytest.mark.parametrize("runtime", ["host", "qmt36"])
def test_strategy_package_cold_import(tmp_path, runtime):
    executable = sys.executable
    qmt_bin = ""
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    if runtime == "qmt36":
        executable = env.get("CFQUANT_TEST_PYTHON36")
        if not executable:
            pytest.skip("Set CFQUANT_TEST_PYTHON36 to run with QMT Python 3.6")
        executable = str(Path(executable).resolve())
        assert Path(executable).is_file(), executable
        qmt_bin = str(Path(executable).parent)
        env["PYTHONHOME"] = qmt_bin
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["CFQUANT_QMT_NO_FILE_IO"] = "1"
    probe = tmp_path / "probe.py"
    result_path = tmp_path / "result.json"
    probe.write_text(PROBE, encoding="utf-8")
    process = subprocess.run(
        [executable, "-S", str(probe), str(result_path), str(ROOT), qmt_bin],
        cwd=str(tmp_path), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    assert result_path.is_file(), process.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if runtime == "qmt36":
        assert result["version"][:2] == [3, 6], result
    assert result.get("ok"), result.get("error", result)
