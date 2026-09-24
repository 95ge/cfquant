"""Sync batch execution and synchronous order-ID lookup into GBK QMT scripts."""

import argparse
import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = "# BEGIN GENERATED CFTRADER BATCH\n"
END = "# END GENERATED CFTRADER BATCH\n"


def _class_method(source, class_name, method_name):
    tree = ast.parse(source)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == method_name)
    return "".join(source.splitlines(keepends=True)[method.lineno - 1:method.end_lineno])


def _replace_class_method(source, class_name, method_name, replacement):
    tree = ast.parse(source)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == method_name)
    lines = source.splitlines(keepends=True)
    lines[method.lineno - 1:method.end_lineno] = replacement.splitlines(keepends=True)
    return "".join(lines)


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
    branch = [
        '        if action in CFTRADER_BATCH_ORDER_ACTIONS:\n',
        '            return execute_qmt_batch(self, params, msg, action.endswith("_async"))\n',
        '        if action in CFTRADER_BATCH_CANCEL_ACTIONS:\n',
        '            return execute_qmt_cancel_batch(self, params, msg, action.endswith("_async"))\n',
    ]
    if lines[dispatch.lineno:dispatch.lineno + len(branch)] != branch:
        if (lines[dispatch.lineno:dispatch.lineno + 2]
                == ['        if action in CFTRADER_BATCH_ACTIONS:\n',
                    '            return execute_qmt_batch(self, params, msg, action.endswith("_async"))\n']):
            lines[dispatch.lineno:dispatch.lineno + 2] = branch
        else:
            lines[dispatch.lineno:dispatch.lineno] = branch
    source = ''.join(lines)
    version_source = (ROOT / "cfquant/version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', version_source)
    if match:
        source = re.sub(r'^CORE_VERSION\s*=\s*"[^"]+"', 'CORE_VERSION = "%s"' % match.group(1),
                        source, count=1, flags=re.M)
    source = source.replace('def _order_stock(self, params, msg, resolve_order_id=True):',
                            'def _order_stock(self, params, msg, resolve_order_id=True, capture_previous_id=True):', 1)
    source = source.replace(
        'def _order_stock(self, params, msg, resolve_order_id=True, capture_previous_id=True):',
        'def _order_stock(self, params, msg, resolve_order_id=True, capture_previous_id=True, trust_request_order_id=True):',
        1,
    )
    source = source.replace('previous_order_id = self._get_last_order_id(account_id, account_type, strategy_name)\n',
                            'previous_order_id = self._get_last_order_id(account_id, account_type, strategy_name) if capture_previous_id else None\n', 1)
    source = source.replace(
        'order_id = self._normalize_order_id(result)\n',
        'order_id = self._normalize_order_id(result) if trust_request_order_id else None\n',
        1,
    )
    if 'self._order_reference_key(order_id) == self._order_reference_key(previous_order_id)' not in source:
        source = source.replace(
            '        order_id = self._normalize_order_id(result) if trust_request_order_id else None\n',
            '        order_id = self._normalize_order_id(result) if trust_request_order_id else None\n'
            '        if (\n'
            '            order_id is not None\n'
            '            and previous_order_id is not None\n'
            '            and self._order_reference_key(order_id) == self._order_reference_key(previous_order_id)\n'
            '        ):\n'
            '            # Some QMT builds expose the previous get_last_order_id value as\n'
            '            # passorder\'s result. Resolve it from detail/callback instead.\n'
            '            order_id = None\n',
            1,
        )
    source = source.replace(
        'result = self._order_stock(params, msg, resolve_order_id=False)\n',
        'result = self._order_stock(params, msg, resolve_order_id=False, trust_request_order_id=False)\n',
        1,
    )
    source = source.replace(
        '        pending = self._async_order_record(params, msg, result)\n'
        '        order_id = self._normalize_order_id(result.get("order_id"))\n'
        '        if order_id is not None:\n'
        '            self._send_async_order_response(pending, order_id)\n'
        '        else:\n'
        '            self._register_pending_async_order(pending)\n',
        '        pending = self._async_order_record(params, msg, result)\n'
        '        self._register_pending_async_order(pending)\n',
        1,
    )
    core = (ROOT / 'cfquant/tx_trade_bridge.py').read_text(encoding='utf-8')

    # The standalone Lite bridge has its own copy of the order path. Keep the
    # same callback wake-up and raw-reference safeguards as the shared bridge.
    if 'self.pending_sync_orders = []' not in source:
        source = source.replace(
            '        self.pending_async_orders_lock = threading.RLock()\n',
            '        self.pending_async_orders_lock = threading.RLock()\n'
            '        self.pending_sync_orders = []\n'
            '        self.pending_sync_orders_lock = threading.RLock()\n',
            1,
        )

    order_stock = _class_method(source, 'TxTradeBridge', '_order_stock')
    previous_line = (
        '        previous_order_id = self._get_last_order_id(account_id, account_type, strategy_name) '
        'if capture_previous_id else None\n'
    )
    if 'pending_sync_order = self._register_pending_sync_order' not in order_stock:
        registration = (
            '        pending_sync_order = None\n'
            '        if resolve_order_id:\n'
            '            pending_sync_order = self._register_pending_sync_order(\n'
            '                account_id,\n'
            '                account_type,\n'
            '                params.get("stock_code", params.get("code", "")),\n'
            '                order_remark,\n'
            '                strategy_name,\n'
            '                previous_order_id,\n'
            '            )\n'
        )
        order_stock = order_stock.replace(previous_line, previous_line + registration, 1)
    if 'pending_sync_order,\n' not in order_stock:
        order_stock = order_stock.replace(
            '                params,\n'
            '            )\n'
            '        if not self._is_failed_order_result(result):\n',
            '                params,\n'
            '                pending_sync_order,\n'
            '            )\n'
            '        if not self._is_failed_order_result(result):\n',
            1,
        )
    if '        self._discard_pending_sync_order(pending_sync_order)\n' not in order_stock:
        order_stock = order_stock.replace(
            '        return {\n',
            '        if pending_sync_order is not None:\n'
            '            self._discard_pending_sync_order(pending_sync_order)\n'
            '        return {\n',
            1,
        )
    if '        try:\n            result = passorder(' not in order_stock:
        pass_start = order_stock.index('        result = passorder(\n')
        pass_end = order_stock.index('        )\n', pass_start) + len('        )\n')
        pass_block = order_stock[pass_start:pass_end]
        wrapped = (
            '        try:\n'
            + ''.join('    ' + line for line in pass_block.splitlines(keepends=True))
            + '        except Exception:\n'
            + '            if pending_sync_order is not None:\n'
            + '                self._discard_pending_sync_order(pending_sync_order)\n'
            + '            raise\n'
        )
        order_stock = order_stock[:pass_start] + wrapped + order_stock[pass_end:]
    source = _replace_class_method(source, 'TxTradeBridge', '_order_stock', order_stock)

    sync_methods = (
        '_register_pending_sync_order',
        '_discard_pending_sync_order',
        '_resolve_pending_sync_order_callback',
        '_order_reference_key',
        '_order_reference_values',
        '_is_previous_order_detail',
    )
    additions = []
    for name in sync_methods:
        replacement = _class_method(core, 'TxTradeBridge', name)
        # Standalone entries forward callbacks explicitly to both bridges.
        replacement = replacement.replace('        _register_sync_order_callback_relay(self)\n', '')
        if 'def %s(' % name in source:
            source = _replace_class_method(source, 'TxTradeBridge', name, replacement)
        else:
            additions.append(replacement)
    if additions:
        anchor = '    def _get_last_order_id(self, account_id, account_type, strategy_name=""):\n'
        source = source.replace(anchor, '\n\n'.join(additions) + '\n\n' + anchor, 1)

    source = _replace_class_method(
        source, 'TxTradeBridge', '_find_order_id',
        _class_method(core, 'TxTradeBridge', '_find_order_id'),
    )
    source = _replace_class_method(
        source, 'TxTradeBridge', '_order_id_from_detail',
        _class_method(core, 'TxTradeBridge', '_order_id_from_detail'),
    )
    callback = (
        '            self._resolve_pending_sync_order_callback(data)\n'
        '            self._handle_async_order_callback(data)\n'
    )
    source = source.replace(
        '            self._handle_async_order_callback(data)\n',
        callback,
        1,
    ) if 'self._resolve_pending_sync_order_callback(data)' not in source else source
    normal = (ROOT / 'cfquant/normal_bridge.py').read_text(encoding='utf-8')
    for name in ('_drain_requests', '_drain_single_request'):
        source = _replace_class_method(source, 'NormalQmtBridge', name,
                                       _class_method(normal, 'NormalQmtBridge', name))
    for name in ('_defer_sync_order_response', '_poll_sync_order_responses'):
        replacement = _class_method(normal, 'NormalQmtBridge', name)
        if 'def %s(' % name in source:
            source = _replace_class_method(source, 'NormalQmtBridge', name, replacement)
        else:
            anchor = '    def _drain_single_request(self, source, msg, received_at):\n'
            source = source.replace(anchor, replacement + '\n' + anchor, 1)
    source = source.replace('if self.dispatch_on_qmt_thread and msg.get(',
                            'if getattr(self, "dispatch_on_qmt_thread", False) and msg.get(')
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
