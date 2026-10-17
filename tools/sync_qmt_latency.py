"""Embed latency helpers without adding any file IO to standalone QMT scripts."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def updated_source(source):
    source = source.replace('\r\n', '\n')
    replacements = {}
    wanted = {
        'protocol.py': {'encode_response_result', 'pack_response', 'is_readonly_request', 'request_expired'},
        'flow_control.py': {'OrderedSender'},
        'pipe_transport.py': {'PipeTxClient'},
    }
    for filename, names in wanted.items():
        text = (ROOT / 'cfquant' / filename).read_text(encoding='utf-8')
        lines = text.splitlines(True)
        for node in ast.parse(text).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
                replacements[node.name] = ''.join(lines[node.lineno-1:node.end_lineno]) + '\n'
    tree = ast.parse(source)
    lines = source.splitlines(True)
    edits = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in replacements:
            edits.append((node.lineno-1, node.end_lineno, replacements.pop(node.name)))
    normal = (ROOT / 'cfquant/normal_bridge.py').read_text(encoding='utf-8')
    normal_lines = normal.splitlines(True)
    normal_class = next(n for n in ast.parse(normal).body if isinstance(n, ast.ClassDef) and n.name == 'NormalQmtBridge')
    methods = {n.name: ''.join(normal_lines[n.lineno-1:n.end_lineno]) + '\n'
               for n in normal_class.body if isinstance(n, ast.FunctionDef)
               and n.name in {'_drain_coalesced_request', '_send_response', '_drain_single_request', '_status_extra', '_worker_loop'}}
    lite_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'NormalQmtBridge')
    for node in lite_class.body:
        if isinstance(node, ast.FunctionDef) and node.name in methods:
            edits.append((node.lineno-1, node.end_lineno, methods[node.name]))
    anchor = next(n.lineno-1 for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'dumps_message')
    if replacements:
        edits.append((anchor, anchor, '\n\n'.join(replacements.values()) + '\n'))
    for start, end, text in sorted(edits, reverse=True):
        lines[start:end] = [text]
    source = ''.join(lines)
    if 'from collections import deque\n' not in source:
        source = source.replace('import threading\n', 'import threading\nfrom collections import deque\n', 1)
    source = source.replace('pump_max_ms=0,', 'pump_max_ms=5,')
    for name in ('NORMAL', 'TRADE'):
        source = source.replace('"CFQUANT_CTYPE_%s_PUMP_MAX_MS", "0"' % name,
                                '"CFQUANT_CTYPE_%s_PUMP_MAX_MS", "5"' % name)
    while '\n\n\n\n' in source:
        source = source.replace('\n\n\n\n', '\n\n\n')
    ast.parse(source, feature_version=(3, 6))
    return source


def main():
    for path in sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py')):
        original = path.read_bytes()
        updated = updated_source(original.decode('gbk')).replace('\n', '\r\n').encode('gbk')
        if updated != original:
            path.write_bytes(updated)
        print(path.name)


if __name__ == '__main__':
    main()
