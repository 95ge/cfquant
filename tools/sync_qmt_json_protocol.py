"""Sync protocol and table conversion helpers into standalone GBK QMT entries."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {"normalize_json_value", "dumps_message", "loads_message", "pack_request", "pack_response",
             "_encode_dataframe", "decode_value", "dataframe_numeric_rows",
             "_quote_json_default", "pack_quote_latency_event", "pack_whole_quote_event",
             "encode_response_result", "is_readonly_request", "request_expired"}


def main():
    functions = {}
    for filename, names in (("cfquant/protocol.py", FUNCTIONS), ("cfquant/level2.py", {"quote_records"})):
        source = (ROOT / filename).read_text(encoding="utf-8")
        source_lines = source.splitlines(keepends=True)
        functions.update({node.name: "".join(source_lines[node.lineno - 1:node.end_lineno]).replace("\n", "\r\n")
                          for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names})
    for path in sorted((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py")):
        original = path.read_bytes()
        text = original.decode("gbk")
        lines = text.splitlines(keepends=True)
        nodes = {node.name: node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}
        edits = []
        for name, replacement in functions.items():
            if name in nodes:
                node = nodes[name]
                edits.append((node.lineno - 1, node.end_lineno, replacement))
            else:
                index = nodes["dumps_message"].lineno - 1
                edits.append((index, index, replacement + "\r\n\r\n"))
        for start, end, replacement in sorted(edits, reverse=True):
            lines[start:end] = [replacement]
        updated = "".join(lines)
        compile(updated, str(path), "exec")
        payload = updated.encode("gbk")
        if payload != original:
            path.write_bytes(payload)
        print(path.name)


if __name__ == "__main__":
    main()
