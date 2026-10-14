"""Embed the common QMT caller-thread dispatcher in all standalone Lite entries."""
import argparse
import ast
from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def _function(source, name, class_name=None):
    body = ast.parse(source).body
    if class_name:
        body = next(n.body for n in body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)
    return node, textwrap.dedent(''.join(source.splitlines(True)[node.lineno - 1:node.end_lineno]))


def _replace(source, name, replacement, class_name=None):
    node, _ = _function(source, name, class_name)
    lines = source.splitlines(True)
    lines[node.lineno - 1:node.end_lineno] = [textwrap.indent(replacement, '    ' if class_name else '')]
    return ''.join(lines)


def updated_source(source):
    source = source.replace('\r\n', '\n')
    normal = (ROOT / 'cfquant/normal_bridge.py').read_text(encoding='utf-8')
    pipe = (ROOT / 'cfquant/pipe_bridge.py').read_text(encoding='utf-8')
    entry = (ROOT / 'qmt_scripts/CFQUANT_CTYPE_ALL_LOWLAT.py').read_text(encoding='gbk')

    # Lite deliberately omits disk-backed order metadata. Keep its constructor
    # and copy only the common dispatch option; never embed that file IO.
    _, constructor = _function(source, '__init__', 'NormalQmtBridge')
    if 'dispatch_on_qmt_thread=False' not in constructor:
        constructor = constructor.replace('    pump_max_ms=0,\n',
                                          '    pump_max_ms=0,\n    dispatch_on_qmt_thread=False,\n', 1)
    if 'self.dispatch_on_qmt_thread =' not in constructor:
        constructor = constructor.replace('    self.pump_max_ms = float(pump_max_ms)\n',
                                          '    self.pump_max_ms = float(pump_max_ms)\n'
                                          '    self.dispatch_on_qmt_thread = bool(dispatch_on_qmt_thread)\n', 1)
    source = _replace(source, '__init__', constructor, 'NormalQmtBridge')
    for name in ('set_context', 'pump', 'on_timer', '_drain_requests',
                 '_drain_single_request', '_defer_sync_order_response',
                 '_poll_sync_order_responses', '_status_extra'):
        _, method = _function(normal, name, 'NormalQmtBridge')
        method = method.replace('    if self.order_meta_enabled and self.account_id:\n'
                                '        self._ensure_order_meta_account_subscription(self.account_id, self.account_type)\n', '')
        method = method.replace('    self._maybe_reset_order_meta_stores()\n', '')
        method = method.replace('    self._flush_pending_order_errors()\n', '')
        source = _replace(source, name, method, 'NormalQmtBridge')
    _, constructor = _function(pipe, '__init__', 'PipeNormalQmtBridge')
    constructor = constructor.replace('        order_meta_enabled=False,\n', '')
    source = _replace(source, '__init__', constructor, 'PipeNormalQmtBridge')
    for name, origin in (('start_normal_bridge', normal), ('start_pipe_normal_bridge', pipe)):
        source = _replace(source, name, _function(origin, name)[1])

    # Share the entry's configurable QMT timer, rather than also installing
    # the bridge's legacy 500 ms timer. Reception threads still only enqueue.
    call = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == 'start_pipe_normal_bridge')
    lines = source.splitlines(True)
    creation = ''.join(lines[call.lineno - 1:call.end_lineno])
    creation = creation.replace('schedule_timer=True,', 'schedule_timer=False,')
    if 'dispatch_on_qmt_thread=' not in creation:
        creation = creation.replace('        pump_max_ms=NORMAL_PUMP_MAX_MS,\n',
                                    '        pump_max_ms=NORMAL_PUMP_MAX_MS,\n'
                                    '        dispatch_on_qmt_thread=True,\n')
    lines[call.lineno - 1:call.end_lineno] = [creation]
    source = ''.join(lines)

    bind = _function(entry, '_bind_dispatch_context')[1]
    timer = _function(entry, 'cfquant_ctype_trade_timer')[1].replace('cfquant ctypes ', 'cfquant lite ')
    if 'def _bind_dispatch_context(' in source:
        source = _replace(source, '_bind_dispatch_context', bind)
    else:
        timer = bind + '\n\n' + timer
    source = _replace(source, 'cfquant_ctype_trade_timer', timer)
    # Preserve Lite's startup report retries while refreshing callback context.
    _, handlebar = _function(source, 'handlebar')
    if '_bind_dispatch_context(ContextInfo)' not in handlebar:
        handlebar = handlebar.replace('def handlebar(ContextInfo):\n',
                                      'def handlebar(ContextInfo):\n    _bind_dispatch_context(ContextInfo)\n', 1)
    source = _replace(source, 'handlebar', handlebar)
    source = source.replace('"xttrader_to_normal_worker"', '"xttrader_to_normal_qmt_timer"')
    source = source.replace('LITE_ENTRY_VERSION = "lite_20260828_01"',
                            'LITE_ENTRY_VERSION = "lite_20261014_01"')
    ast.parse(source, feature_version=(3, 6))
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    outdated = []
    for path in sorted((ROOT / 'qmt_scripts').rglob('CFQUANT_LITE*.py')):
        source = path.read_bytes().decode('gbk').replace('\r\n', '\n')
        updated = updated_source(source)
        if updated == source:
            continue
        outdated.append(path)
        if not args.check:
            path.write_bytes(updated.replace('\n', '\r\n').encode('gbk'))
        print(('Outdated: ' if args.check else 'Updated: ') + str(path.relative_to(ROOT)))
    return int(args.check and bool(outdated))


if __name__ == '__main__':
    raise SystemExit(main())
