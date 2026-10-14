"""Keep the six Pipe QMT entries free of application-managed filesystem IO."""
import argparse
import ast
from pathlib import Path
import textwrap

try:
    from .sync_qmt_dispatch import updated_source as update_dispatch_source
    from .sync_qmt_binding_settings import updated_source as update_binding_source
except ImportError:
    from sync_qmt_dispatch import updated_source as update_dispatch_source
    from sync_qmt_binding_settings import updated_source as update_binding_source

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '# BEGIN GENERATED PIPE RUNTIME\n'
END = '# END GENERATED PIPE RUNTIME\n'


def replace_functions(source, replacements, class_name=None):
    tree = ast.parse(source)
    body = tree.body
    if class_name:
        body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name).body
    lines = source.splitlines(True)
    for node in reversed(body):
        if isinstance(node, ast.FunctionDef) and node.name in replacements:
            value = replacements[node.name]
            lines[node.lineno - 1:node.end_lineno] = [textwrap.indent(value, '    ' if class_name else '')]
    return ''.join(lines)


def updated_source(source, lite):
    source = source.replace('\r\n', '\n')
    if 'EMBEDDED_RUNTIME_CONFIG = ' not in source:
        source = source.replace('RUNTIME_CONFIG = {}', 'EMBEDDED_RUNTIME_CONFIG = {}\nRUNTIME_CONFIG = {}', 1)
    replacements = {
        '_cfquant_market_base_dir': '', '_cfquant_market_config_path': '',
        '_cfquant_market_should_set_config_path': '',
        '_entry_base_dir': '''def _entry_base_dir():
    entry = _entry_file_path()
    if entry:
        return os.path.dirname(entry)
    return (os.environ.get("CFQUANT_QMT_SCRIPT_DIR") or os.environ.get("CFQUANT_SCRIPT_DIR")
            or os.environ.get("CFQUANT_ENTRY_DIR") or os.getcwd())
''',
        '_ensure_path': '''def _ensure_path():
    base = _entry_base_dir()
    parent = os.path.dirname(base)
    candidates = [p for p in os.environ.get("CFQUANT_PYTHONPATH", "").split(os.pathsep) if p]
    candidates += [base, os.path.join(parent, "bin.x64"), parent]
    for path in reversed(candidates):
        if path and path not in sys.path:
            sys.path.insert(0, path)
''',
        '_runtime_log_path': '', '_runtime_config_paths': '',
        '_runtime_path_maybe_file': '', '_read_text_file_ctypes': '',
        '_write_runtime_log': '''def _write_runtime_log(message):
    enabled = globals().get("get_log_enabled")
    if not callable(enabled) or enabled():
        print(message)
''',
        '_load_runtime_config': '''def _load_runtime_config():
    if EMBEDDED_RUNTIME_CONFIG:
        return "embedded", dict(EMBEDDED_RUNTIME_CONFIG)
    text = os.environ.get("CFQUANT_RUNTIME_CONFIG_JSON", "").strip()
    if text:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("CFQUANT_RUNTIME_CONFIG_JSON must be a JSON object")
        return "environment", data
    return "", {}
''',
    }
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (node.name.startswith('_lite_marker_')
                or node.name in ('_lite_runtime_marker_dirs', '_write_lite_runtime_marker')):
            replacements[node.name] = ''
    source = replace_functions(source, replacements)
    lines = source.splitlines(True)
    for node in reversed(ast.parse(source).body):
        obsolete = (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in (
            '_CFQUANT_CONFIG_FILENAME', '_runtime_marker_started_at') for t in node.targets))
        obsolete = obsolete or (isinstance(node, ast.If) and isinstance(node.test, ast.Call)
                                and isinstance(node.test.func, ast.Name)
                                and node.test.func.id == '_cfquant_market_should_set_config_path')
        if obsolete:
            lines[node.lineno - 1:node.end_lineno] = []
    source = ''.join(lines).replace('import io\n', '')
    source = source.replace('if data.get("account_id") and not DEFAULT_ACCOUNT_ID:',
                            'if data.get("account_id") and (EMBEDDED_RUNTIME_CONFIG or not DEFAULT_ACCOUNT_ID):')
    source = source.replace('    _write_runtime_log(translated)\n', '')
    source = source.replace('    marker = _write_lite_runtime_marker(reason)\n', '')
    source = source.replace('        return bool(marker.get("ok"))\n', '        return False\n')
    source = source.replace('_write_lite_runtime_marker("module_loaded")\n', '')
    source = source.replace('    value = str(os.environ.get(name) or "").strip()\n',
                            '    if EMBEDDED_RUNTIME_CONFIG:\n        return True\n'
                            '    value = str(os.environ.get(name) or "").strip()\n') if '    if EMBEDDED_RUNTIME_CONFIG:\n        return True' not in source else source
    if 'sys.dont_write_bytecode = True' not in source:
        source = source.replace('import sys\n', 'import sys\nsys.dont_write_bytecode = True\n'
                                'os.environ["CFQUANT_QMT_NO_FILE_IO"] = "1"\n', 1)
    if lite:
        # Gate business requests before either Pipe endpoint becomes visible.
        for class_name in ('PipeNormalQmtBridge', 'PipeTradeBridge'):
            cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == class_name)
            method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'start')
            body = textwrap.dedent(''.join(source.splitlines(True)[method.lineno-1:method.end_lineno]))
            if 'runtime.attach_bridge(self)' not in body:
                body = body.replace('def start(self):\n', 'def start(self):\n'
                                    '    runtime = self.globals_dict.get("_managed_runtime")\n'
                                    '    if runtime is not None:\n        runtime.attach_bridge(self)\n', 1)
                source = replace_functions(source, {'start': body}, class_name)
        source = replace_functions(source, {
            '_default_log_file': 'def _default_log_file(self):\n    return ""\n',
            '_log': '''def _log(self, msg, force=False):
    if self.show and (force or get_log_enabled()):
        print(translate_log(msg))
''',
            '_cleanup_qmt_userdata_logs': '''def _cleanup_qmt_userdata_logs(self, params):
    raise NotImplementedError("QMT file IO is disabled; clean logs from the external Web process.")
''',
            '_qmt_userdata_log_dir': '',
        }, 'TxTradeBridge')
        normal = (ROOT / 'cfquant/normal_bridge.py').read_text(encoding='utf-8')
        body = next(n.body for n in ast.parse(normal).body if isinstance(n, ast.ClassDef) and n.name == 'NormalQmtBridge')
        method = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == '_handle_raw_from_thread')
        replacement = textwrap.dedent(''.join(normal.splitlines(True)[method.lineno-1:method.end_lineno]))
        replacement = replacement.replace('    if self.order_meta_enabled and self._handle_order_meta_raw(raw):\n        return\n', '')
        source = replace_functions(source, {'_handle_raw_from_thread': replacement}, 'NormalQmtBridge')
    helper = ((ROOT / 'cfquant/qmt_pipe_runtime.py').read_text(encoding='utf-8') if lite
              else 'from cfquant.qmt_pipe_runtime import ManagedPipeRuntime\n')
    block = BEGIN + helper.rstrip() + '\n' + END
    if BEGIN in source:
        start, end = source.index(BEGIN), source.index(END) + len(END)
        source = source[:start] + block + source[end:]
    else:
        anchor = '_normal_bridge = start_pipe_normal_bridge('
        source = source.replace(anchor, block + '\n' + anchor, 1)
    if '_managed_runtime = ManagedPipeRuntime(' not in source:
        start = source.index('_normal_bridge = start_pipe_normal_bridge(')
        end = source.index('_print_log(', start)
        creation = source[start:end].rstrip() + '\n'
        source = (source[:start] + '_managed_runtime = ManagedPipeRuntime(RUNTIME_CONFIG.get("managed_strategy")).acquire()\n'
                  '_managed_runtime.namespace = globals()\ntry:\n' + textwrap.indent(creation, '    ')
                  + 'except BaseException:\n    _managed_runtime.close()\n    raise\n\n' + source[end:])
        source = source.rstrip() + '\n\n_managed_runtime.bind(globals())\n'
    if '    for _account_bridge in (_normal_bridge, _trade_bridge):' not in source:
        source = source.replace('except BaseException:\n    _managed_runtime.close()',
                                '    for _account_bridge in (_normal_bridge, _trade_bridge):\n'
                                '        _account_bridge.account_type = DEFAULT_ACCOUNT_TYPE\n'
                                'except BaseException:\n    _managed_runtime.close()', 1)
    # Removed functions leave large empty gaps in old generated entries.
    while '\n\n\n\n' in source:
        source = source.replace('\n\n\n\n', '\n\n\n')
    if lite:
        source = update_dispatch_source(source)
    source = update_binding_source(source, lite)
    ast.parse(source, feature_version=(3, 6))
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    outdated = []
    for path in sorted((ROOT / 'qmt_scripts').rglob('*.py')):
        if not path.name.startswith(('CFQUANT_LITE', 'CFQUANT_CTYPE_ALL_LOWLAT')):
            continue
        raw = path.read_bytes()
        source = raw.decode('gbk')
        updated = updated_source(source, path.name.startswith('CFQUANT_LITE'))
        if updated == source.replace('\r\n', '\n'):
            continue
        outdated.append(path)
        if not args.check:
            path.write_bytes(updated.replace('\n', '\r\n').encode('gbk'))
        print(('Outdated: ' if args.check else 'Updated: ') + str(path.relative_to(ROOT)))
    return int(args.check and bool(outdated))


if __name__ == '__main__':
    raise SystemExit(main())
