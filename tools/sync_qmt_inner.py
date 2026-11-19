"""Embed the native API runtime and original callbacks in QMT entry scripts."""
import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '# BEGIN CFQUANT INNER API\n'
END = '# END CFQUANT INNER API\n'
CALLBACK_ARGS = {
    'account_callback': 'ContextInfo, accountInfo',
    'task_callback': 'ContextInfo, taskInfo',
    'order_callback': 'ContextInfo, orderInfo',
    'deal_callback': 'ContextInfo, dealInfo',
    'position_callback': 'ContextInfo, positionInfo',
    'orderError_callback': 'ContextInfo, orderArgs, errMsg',
    'credit_account_callback': 'ContextInfo, seq, result',
    'credit_opvolume_callback': 'ContextInfo, accid, seq, ret, result',
}


def embedded_runtime():
    catalog = (ROOT / 'cfquant/qmt_inner_catalog.py').read_text(encoding='utf-8')
    runtime = (ROOT / 'cfquant/qmt_inner_runtime.py').read_text(encoding='utf-8')
    lines = runtime.splitlines(True)
    for node in reversed(ast.parse(runtime).body):
        if isinstance(node, ast.ImportFrom) and node.level:
            del lines[node.lineno - 1:node.end_lineno]
    return catalog + '\n' + ''.join(lines)


def updated_source(source, lite=False):
    if BEGIN in source:
        start = source.index(BEGIN)
        end = source.index(END, start) + len(END)
        source = source[:start] + source[end:]
    bridge_name = '_normal_bridge' if '_normal_bridge = None' in source else '_cf_bridge'
    helper = '''def _publish_inner_callback(name, *args):
    bridge = globals().get(%r)
%s    if bridge is not None:
        %s
        try:
            publish_inner_callback(bridge, name, *args)
        except Exception as error:
            print('cfquant inner callback failed: %%s' %% error)
''' % (bridge_name,
       "    if globals().get('_LITE_ROLE') == 'trade':\n        return\n" if lite else '',
       'pass' if lite else 'from cfquant.qmt_inner_runtime import publish_inner_callback')
    block = BEGIN + (embedded_runtime() + '\n' if lite else '') + helper + END
    if lite:
        source = source.replace('class TxTradeBridge(object):', block + 'class TxTradeBridge(object):', 1)
        # A few sync tools regenerate _dispatch, so normalize both source forms.
        source = source.replace('            from .qmt_inner_runtime import dispatch_inner_api\n', '')
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TxTradeBridge')
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_dispatch')
        lines = source.splitlines(True)
        body = ''.join(lines[node.lineno - 1:node.end_lineno])
        if 'dispatch_inner_api(self, action, params, msg)' not in body:
            lines[node.lineno:node.lineno] = ['        if action.startswith("qmt_inner."):\n'
                                             '            return dispatch_inner_api(self, action, params, msg)\n']
        source = ''.join(lines)
    else:
        # Before callbacks, after imports/startup definitions; no live side effects.
        index = source.index('def account_callback(')
        source = source[:index] + block + source[index:]
    lines = source.splitlines(True)
    found = set()
    for node in reversed(ast.parse(source).body):
        if not isinstance(node, ast.FunctionDef) or node.name not in CALLBACK_ARGS:
            continue
        found.add(node.name)
        if '_publish_inner_callback(' in ''.join(lines[node.lineno:node.end_lineno]):
            continue
        args = ', '.join(arg.arg for arg in node.args.args)
        lines[node.lineno:node.lineno] = ['    _publish_inner_callback(%r, %s)\n' % (node.name, args)]
    source = ''.join(lines)
    for name, args in CALLBACK_ARGS.items():
        if name not in found:
            source += '\n\ndef %s(%s):\n    _publish_inner_callback(%r, %s)\n' % (name, args, name, args)
    ast.parse(source, feature_version=(3, 6))
    return source


def synchronize(check=False):
    changed = []
    for path in sorted((ROOT / 'qmt_scripts').rglob('CFQUANT*.py')):
        raw = path.read_bytes()
        source = raw.decode('gbk').replace('\r\n', '\n')
        if 'def account_callback(' not in source or ('_normal_bridge = None' not in source and '_cf_bridge = None' not in source):
            continue
        updated = updated_source(source, lite=path.name.startswith('CFQUANT_LITE'))
        if source != updated:
            changed.append(path)
            if not check:
                newline = '\r\n' if b'\r\n' in raw else '\n'
                path.write_bytes(updated.replace('\n', newline).encode('gbk'))
    print('QMT inner API entries %s: %s' % ('outdated' if check else 'updated', len(changed)))
    return int(check and bool(changed))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    raise SystemExit(synchronize(parser.parse_args().check))
