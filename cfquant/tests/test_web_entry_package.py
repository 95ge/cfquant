"""Direct source launches must not mix an embedded runtime's older wheel."""
from pathlib import Path
import json
import subprocess
import sys


def test_isolated_web_entry_selects_adjacent_package_before_first_import(tmp_path):
    source_root = Path(__file__).resolve().parents[2]
    stale = tmp_path / "installed" / "cfquant"
    stale.mkdir(parents=True)
    (stale / "__init__.py").write_text("", encoding="utf-8")
    code = '''
import importlib.abc, importlib.machinery, json, pathlib, runpy, sys
sys.path.insert(0, STALE_ROOT)
class FirstImport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'cfquant':
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            print(json.dumps(str(pathlib.Path(spec.origin).resolve()), ensure_ascii=True))
            raise SystemExit(0)
sys.meta_path.insert(0, FirstImport())
runpy.run_path(ENTRY, run_name='__main__')
'''.replace("STALE_ROOT", ascii(str(stale.parent))).replace(
        "ENTRY", ascii(str(source_root / "cfquant_web_server.py")))
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout.strip())) == source_root / "cfquant" / "__init__.py"
