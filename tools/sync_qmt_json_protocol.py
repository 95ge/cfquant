"""Sync the outgoing JSON boundary into standalone GBK QMT entries."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {"normalize_json_value", "dumps_message", "pack_request"}


def main():
    source = (ROOT / "cfquant/protocol.py").read_text(encoding="utf-8")
    source_lines = source.splitlines(keepends=True)
    functions = {node.name: "".join(source_lines[node.lineno - 1:node.end_lineno]).replace("\n", "\r\n")
                 for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS}
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
