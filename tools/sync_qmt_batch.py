"""Sync batch execution and synchronous order-ID lookup into GBK QMT scripts."""

import argparse
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = "# BEGIN GENERATED CFTRADER BATCH\n"
END = "# END GENERATED CFTRADER BATCH\n"


def updated_source(source):
    source = source.replace("\r\n", "\n")
    shared = (ROOT / "cfquant/batch_orders.py").read_text(encoding="ascii")
    block = START + shared.rstrip() + "\n" + END
    if START in source:
        start = source.index(START)
        end = source.index(END, start) + len(END)
        source = source[:start] + block + source[end:]
    else:
        anchor = 'CORE_VERSION = '
        index = source.index(anchor)
        source = source[:index] + block + "\n" + source[index:]
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TxTradeBridge")
    dispatch = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_dispatch")
    lines = source.splitlines(keepends=True)
    branch = ['        if action in CFTRADER_BATCH_ACTIONS:\n',
              '            return execute_qmt_batch(self, params, msg, action.endswith("_async"))\n']
    if lines[dispatch.lineno:dispatch.lineno + 2] != branch:
        lines[dispatch.lineno:dispatch.lineno] = branch
    source = ''.join(lines)
    source = source.replace('def _order_stock(self, params, msg, resolve_order_id=True):',
                            'def _order_stock(self, params, msg, resolve_order_id=True, capture_previous_id=True):', 1)
    source = source.replace('previous_order_id = self._get_last_order_id(account_id, account_type, strategy_name)\n',
                            'previous_order_id = self._get_last_order_id(account_id, account_type, strategy_name) if capture_previous_id else None\n', 1)
    core = (ROOT / 'cfquant/tx_trade_bridge.py').read_text(encoding='utf-8')
    core_cls = next(node for node in ast.parse(core).body if isinstance(node, ast.ClassDef) and node.name == 'TxTradeBridge')
    core_lookup = next(node for node in core_cls.body if isinstance(node, ast.FunctionDef) and node.name == '_find_order_id')
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'TxTradeBridge')
    lookup = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == '_find_order_id')
    lines = source.splitlines(keepends=True)
    lines[lookup.lineno - 1:lookup.end_lineno] = core.splitlines(keepends=True)[core_lookup.lineno - 1:core_lookup.end_lineno]
    source = ''.join(lines)
    ast.parse(source, feature_version=(3, 6))
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    outdated = []
    for path in sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py')):
        raw = path.read_bytes()
        source = raw.decode('gbk')
        updated = updated_source(source)
        if source.replace('\r\n', '\n') == updated:
            continue
        outdated.append(str(path.relative_to(ROOT)))
        if not args.check:
            newline = '\r\n' if raw.count(b'\r\n') > raw.count(b'\n') / 2 else '\n'
            path.write_bytes(updated.replace('\n', newline).encode('gbk'))
    for path in outdated:
        print(('Outdated: ' if args.check else 'Updated: ') + path)
    return 1 if args.check and outdated else 0


if __name__ == '__main__':
    raise SystemExit(main())
