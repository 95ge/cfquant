"""Apply per-strategy timer/log settings to the six fileless QMT entries."""
import ast

try:
    from .sync_qmt_dispatch import ROOT, _function, _replace
except ImportError:
    from sync_qmt_dispatch import ROOT, _function, _replace


BEGIN = '# BEGIN GENERATED BINDING SETTINGS\n'
END = '# END GENERATED BINDING SETTINGS\n'
HELPERS = '''_QMT_BOUND_LOG_ENABLED = None


def get_log_enabled():
    if _QMT_BOUND_LOG_ENABLED is not None:
        return _QMT_BOUND_LOG_ENABLED
    value = RUNTIME_CONFIG.get("qmt_log_enabled", os.environ.get("CFQUANT_QMT_LOG_ENABLED", "1"))
    return _config_bool(value, True)


def set_log_enabled(value):
    global _QMT_BOUND_LOG_ENABLED
    _QMT_BOUND_LOG_ENABLED = _config_bool(value, True)
    return _QMT_BOUND_LOG_ENABLED


def _qmt_timer_interval(data):
    value = data.get("qmt_timer_interval_ms", os.environ.get("CFQUANT_CTYPE_TRADE_TIMER_INTERVAL_MS", "1"))
    try:
        if isinstance(value, bool) or str(value).strip() != str(int(value)):
            return 1
        value = int(value)
        return value if 1 <= value <= 1000 else 1
    except (TypeError, ValueError, OverflowError):
        return 1
'''


def updated_source(source, lite):
    source = source.replace('\r\n', '\n')
    for previous in ('20', '30'):
        source = source.replace('"CFQUANT_CTYPE_TRADE_TIMER_INTERVAL_MS", "%s"' % previous,
                                '"CFQUANT_CTYPE_TRADE_TIMER_INTERVAL_MS", "1"')
    block = BEGIN + HELPERS + END
    if BEGIN in source:
        start, end = source.index(BEGIN), source.index(END) + len(END)
        source = source[:start] + block + source[end:]
    else:
        source = source.replace('\n_apply_runtime_config()\n', '\n' + block + '\n_apply_runtime_config()\n', 1)
    source = source.replace('get_log_enabled = _logging_i18n.get_log_enabled\n', '')
    _, method = _function(source, '_apply_runtime_config')
    method = method.replace('    if not os.environ.get("CFQUANT_QMT_LOG_ENABLED") and "qmt_log_enabled" in data:\n'
                            '        os.environ["CFQUANT_QMT_LOG_ENABLED"] = "1" if _config_bool(data.get("qmt_log_enabled"), True) else "0"\n', '')
    if 'global TRADE_TIMER_INTERVAL_MS' not in method:
        method = method.replace('def _apply_runtime_config():\n',
                                'def _apply_runtime_config():\n    global TRADE_TIMER_INTERVAL_MS\n', 1)
    if 'TRADE_TIMER_INTERVAL_MS = _qmt_timer_interval(data)' not in method:
        method = method.replace('    RUNTIME_CONFIG = data\n',
                                '    RUNTIME_CONFIG = data\n    TRADE_TIMER_INTERVAL_MS = _qmt_timer_interval(data)\n', 1)
    source = _replace(source, '_apply_runtime_config', method)
    if lite:
        core = (ROOT / 'cfquant/tx_trade_bridge.py').read_text(encoding='utf-8')
        if '    def _get_log_enabled(self):' not in source:
            anchor = '    def _set_log_enabled(self, params):\n'
            import textwrap
            source = source.replace(anchor, textwrap.indent(_function(core, '_get_log_enabled', 'TxTradeBridge')[1], '    ')
                                    + '\n' + anchor, 1)
        for name in ('_get_log_enabled', '_set_log_enabled'):
            source = _replace(source, name, _function(core, name, 'TxTradeBridge')[1], 'TxTradeBridge')
        source = source.replace('return {"enabled": get_log_enabled()}', 'return {"enabled": self._get_log_enabled()}')
        source = source.replace('"log_enabled": get_log_enabled(),', '"log_enabled": self._get_log_enabled(),')
        source = source.replace('if self.show and (force or get_log_enabled()):',
                                'if self.show and (force or self._get_log_enabled()):')
        pipe = (ROOT / 'cfquant/pipe_bridge.py').read_text(encoding='utf-8')
        for name in ('PipeNormalQmtBridge', 'PipeTradeBridge'):
            source = _replace(source, 'start', _function(pipe, 'start', name)[1], name)
        for previous in ('lite_20261014_01', 'lite_20261014_02'):
            source = source.replace(previous, 'lite_20261014_03')
    # Avoid inspecting a native callback just to build a disabled log message.
    _, callback = _function(source, '_publish_callback')
    for line in callback.splitlines(True):
        if '_print_log(' in line and '_callback_brief(' in line:
            prefix = line[:len(line) - len(line.lstrip())]
            if 'if get_log_enabled():\n' not in callback:
                callback = callback.replace(line, prefix + 'if get_log_enabled():\n    ' + line)
    source = _replace(source, '_publish_callback', callback)
    ast.parse(source, feature_version=(3, 6))
    return source
