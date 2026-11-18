"""Cold imports in the host interpreter and real QMT Python 3.6/3.12.

Set CFQUANT_TEST_PYTHON36 to QMT's bin.x64/pythonw.exe (or python.exe),
and CFQUANT_TEST_PYTHON312 to bin.x64/python312/python.exe.
The host test always rejects imports of external login dependencies, even
when neither QMT interpreter is configured.
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

EXTERNAL_MODULES = ("cfquant.qmt_dependencies", "cfquant._pywin32_runtime", "cfquant._frida_runtime",
                    "frida", "win32api", "win32crypt", "win32event",
                    "win32gui", "win32process")

class NoExternalLoginDependencies:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in EXTERNAL_MODULES:
            raise AssertionError("Bridge import requires external login dependency: " + fullname)

sys.meta_path.insert(0, NoExternalLoginDependencies())

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
    # Public notification/binding helpers must also work inside QMT without
    # importing the credential encryption or automatic login components.
    from cfquant.webhook import public_binding, validate_message
    from cfquant.qmt_proxy import QmtProxyCredentialStore
    row = public_binding({"qmt_proxy": {
        "enabled": True, "type": "http", "host": "127.0.0.1", "port": 8080,
        "password": "private-proxy-password"}})
    assert row["qmt_proxy"]["enabled"]
    assert "password" not in row["qmt_proxy"]
    assert validate_message("test") == 8
    assert callable(namespace["notify"].send)
    store = QmtProxyCredentialStore(sys.argv[1] + ".config")
    assert store.password("missing-account") == ""
    store.clear("missing-account")
    assert not any(name in sys.modules for name in EXTERNAL_MODULES)
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


@pytest.mark.parametrize("runtime", ["host", "qmt36", "qmt312"])
def test_strategy_package_cold_import(tmp_path, runtime):
    executable = sys.executable
    qmt_bin = ""
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    versions = {"qmt36": (3, 6), "qmt312": (3, 12)}
    if runtime in versions:
        variable = "CFQUANT_TEST_PYTHON" + runtime[3:]
        executable = env.get(variable)
        if not executable:
            pytest.skip("Set %s to run with %s" % (variable, runtime))
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
        timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.returncode == 0, process.stderr
    assert result_path.is_file(), process.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if runtime in versions:
        assert result["version"][:2] == list(versions[runtime]), result
    assert result.get("ok"), result.get("error", result)
