"""Validate published documentation against the checklist and current SDK."""

import ast
import hashlib
import inspect
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def reference_data():
    source = (ROOT / "web_dashboard/python-api-data.js").read_text(encoding="utf-8")
    return json.loads(source.split("window.CFQUANT_PYTHON_API = ", 1)[1].rstrip(";\n"))


def test_reference_covers_current_checklist_without_promoting_unverified_support():
    data = reference_data()
    checklist = ROOT / "docs/xtquant原版接口适配清单.md"
    assert data["checklistSha256"] == hashlib.sha256(checklist.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest(), "Rebuild the reference after checklist changes"
    rows = re.findall(r"^\| `([^`]+)` \| (.*?) \| ([^|]+) \| (.*?) \|$", checklist.read_text(encoding="utf-8"), re.M)
    entries = data["entries"]
    assert len(entries) == len(rows) == 115
    assert len({entry["id"] for entry in entries}) == len(entries)
    for entry, row in zip(entries, rows):
        assert entry["name"] == row[0].split("(")[0]
        assert entry["note"] == row[3]
        assert entry["source"].startswith("https://dict.thinktrader.net/nativeApi/")
        if row[2].startswith("❌"):
            assert entry["status"] in ("unverified", "unsupported")
            assert not entry["example"]
        else:
            assert entry["status"] in ("supported", "partial")
            assert entry["example"]
            assert "from cfquant" in entry["example"]
    assert len(data["references"]) >= 43


def function_signature(node):
    parameters = []
    arguments = node.args
    positional = arguments.posonlyargs + arguments.args
    defaults = [inspect.Parameter.empty] * (len(positional) - len(arguments.defaults)) + [None] * len(arguments.defaults)
    for arg, default in zip(positional, defaults):
        if arg.arg != "self":
            parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default))
    if arguments.vararg:
        parameters.append(inspect.Parameter(arguments.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY, default=None if default else inspect.Parameter.empty))
    if arguments.kwarg:
        parameters.append(inspect.Parameter(arguments.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    return inspect.Signature(parameters)


def test_all_examples_compile_and_call_existing_sdk_parameters_without_executing_trades():
    signatures = {}
    for module, file in (("xtdata", "xtdata.py"), ("trader", "xttrader.py")):
        tree = ast.parse((ROOT / "cfquant" / file).read_text(encoding="utf-8-sig"))
        nodes = tree.body if module == "xtdata" else next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "XtQuantTrader").body
        for node in nodes:
            if isinstance(node, ast.FunctionDef):
                signatures[module + "." + node.name] = function_signature(node)
    data = reference_data()
    for entry in data["entries"] + data["references"]:
        for key in ("example", "originalExample"):
            source = entry.get(key)
            if not source:
                continue
            tree = ast.parse(source, filename=entry["id"] + ":" + key)
            compile(tree, entry["id"], "exec")
            if key != "example":
                continue
            for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                owner = call.func.value
                if not isinstance(owner, ast.Name) or owner.id not in ("xtdata", "trader"):
                    continue
                signature = signatures[owner.id + "." + call.func.attr]
                signature.bind(*[None for arg in call.args], **{arg.arg: None for arg in call.keywords})


def test_reference_retains_factual_field_and_enum_appendices():
    references = {entry["id"]: entry for entry in reference_data()["references"]}
    assert len(references["reference.xtdata.balance-资产负债表"]["fields"]) > 100
    assert any(row[0] == "xtconstant.SH_MARKET" for row in references["reference.xttrader.交易市场-market"]["fields"])
    assert any(row[0] == "xtconstant.ORDER_SUCCEEDED" for row in references["reference.xttrader.委托状态-order-status"]["fields"])
