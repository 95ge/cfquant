"""Embed the shared whole-quote multiplexer in standalone QMT entries."""
import ast
from pathlib import Path

try:
    from tools.sync_qmt_ast import parse_source
except ImportError:
    from sync_qmt_ast import parse_source

ROOT = Path(__file__).resolve().parents[1]
START = "# BEGIN GENERATED SHARED QUOTES\n"
END = "# END GENERATED SHARED QUOTES\n"


def updated_source(source):
    source = source.replace("\r\n", "\n")
    shared = (ROOT / "cfquant/shared_quotes.py").read_text(encoding="utf-8")
    block = START + shared.rstrip() + "\n" + END + "\n"
    if START in source:
        begin = source.index(START)
        end = source.index(END, begin) + len(END)
        source = source[:begin] + block.rstrip("\n") + "\n" + source[end:]
    else:
        index = source.index("class NormalQmtBridge(")
        source = source[:index] + block + source[index:]
    normal = (ROOT / "cfquant/normal_bridge.py").read_text(encoding="utf-8")
    wanted = {"_get_whole_quote_feed", "_subscribe_native_quote", "_handle_quote_unsubscribe",
              "_close_quote_subscriptions", "_subscribe_internal_whole_quote", "_expire_whole_quote_leases",
              "_on_whole_quote"}
    cls = next(n for n in parse_source(normal).body if isinstance(n, ast.ClassDef) and n.name == "NormalQmtBridge")
    lines = normal.splitlines(True)
    methods = {n.name: "".join(lines[n.lineno - 1:n.end_lineno]) + "\n"
               for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in wanted}
    # Standalone Lite already embeds SharedQuoteFeed above the bridge class.
    # Even an unreachable package import violates the standalone deployment check.
    methods["_get_whole_quote_feed"] = methods["_get_whole_quote_feed"].replace(
        '            feed_type = globals().get("SharedQuoteFeed")\n'
        '            if feed_type is None:\n'
        '                from cfquant.shared_quotes import SharedQuoteFeed as feed_type\n',
        '            feed_type = SharedQuoteFeed\n',
    )
    cls = next(n for n in parse_source(source).body if isinstance(n, ast.ClassDef) and n.name == "NormalQmtBridge")
    lines = source.splitlines(True)
    edits = []
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in methods:
            edits.append((node.lineno - 1, node.end_lineno, methods.pop(node.name)))
    if methods:
        edits.append((cls.end_lineno, cls.end_lineno, "\n" + "\n".join(methods.values())))
    for begin, end, replacement in sorted(edits, reverse=True):
        lines[begin:end] = [replacement]
    source = "".join(lines)
    parse_source(source, feature_version=(3, 6))
    return source
