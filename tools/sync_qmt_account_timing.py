"""Embed account query diagnostics while preserving Lite's account routing."""
import argparse
import ast
try:
    from tools.sync_qmt_ast import parse_source
except ImportError:
    from sync_qmt_ast import parse_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def methods(source, class_name):
    cls = next(n for n in parse_source(source).body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def updated_source(source):
    source = source.replace('\r\n', '\n')
    lines = source.splitlines(True)
    edits = []
    for filename, cls, names in (
        ('tx_trade_bridge.py', 'TxTradeBridge', {'_dispatch', '_dispatch_timed_account_query'}),
        ('normal_bridge.py', 'NormalQmtBridge', {'_drain_coalesced_request', '_send_error'}),
    ):
        core = (ROOT / 'cfquant' / filename).read_text(encoding='utf-8')
        core_lines = core.splitlines(True)
        shared, embedded = methods(core, cls), methods(source, cls)
        for name in names:
            n = shared[name]
            replacement = ''.join(core_lines[n.lineno - 1:n.end_lineno])
            old = embedded.get(name)
            if old:
                edits.append((old.lineno - 1, old.end_lineno, replacement))
            else:
                anchor = embedded['_dispatch'].lineno - 1
                edits.append((anchor, anchor, replacement + '\n'))
        if cls == 'TxTradeBridge':
            old = embedded['_query_trade_detail']
            query = ''.join(lines[old.lineno - 1:old.end_lineno])
            query = query.replace('def _query_trade_detail(self, params, detail_type):',
                                  'def _query_trade_detail(self, params, detail_type, timing=None):')
            if 'native_func = func' not in query:
                # Copy only the timing wrapper; Lite has distinct account alias
                # fallback logic and must keep its existing query implementation.
                n = shared['_query_trade_detail']
                original = ''.join(core_lines[n.lineno - 1:n.end_lineno])
                wrapper = original[original.index('        if timing is not None:'):original.index('        account =')]
                query = query.replace('        account =', wrapper + '        account =', 1)
            edits.append((old.lineno - 1, old.end_lineno, query))
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    result = ''.join(lines)
    parse_source(result, feature_version=(3, 6))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changed = False
    for path in sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py')):
        source = path.read_bytes().decode('gbk').replace('\r\n', '\n')
        result = updated_source(source)
        if source != result:
            changed = True
            if not args.check:
                path.write_bytes(result.replace('\n', '\r\n').encode('gbk'))
            print(('Outdated: ' if args.check else 'Updated: ') + str(path.relative_to(ROOT)))
    return int(args.check and changed)


if __name__ == '__main__':
    raise SystemExit(main())
