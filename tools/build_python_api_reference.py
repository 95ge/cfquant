"""Build offline API metadata from the checklist and official HTML snapshots.

Usage: python tools/build_python_api_reference.py --source-dir .tmp_pytest_python_reference
Development dependency: beautifulsoup4. No network access or SDK import at build time.
Only API signatures and factual schema are extracted; official prose is linked live.
"""

import argparse
import ast
import csv
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup

from python_api_examples import example_for, parameter_help, reference_solution

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs" / "xtquant原版接口适配清单.md"
OUTPUT = ROOT / "web_dashboard" / "python-api-data.js"
BASE = "https://dict.thinktrader.net/nativeApi/"
STATES = {"已适配": "supported", "部分适配": "partial", "条件待验证": "unverified", "未适配": "unsupported"}


def checklist_entries(text):
    module, group = "", ""
    for line in text.splitlines():
        if line.startswith("## "):
            title = line[3:]
            module = ("xtdata" if title.startswith("xtdata") else
                      "callback" if title.startswith("XtQuantTraderCallback") else
                      "trader" if title.startswith("XtQuantTrader") else
                      "type" if title.startswith("官网交易数据结构") else "")
            group = "官网补充提及" if "补充" in title else {"callback": "交易回调", "type": "数据结构"}.get(module, "")
        elif line.startswith("### "):
            group = line[4:]
        elif module and line.startswith("| `"):
            cells = next(csv.reader([line], delimiter="|", quoting=csv.QUOTE_NONE))[1:-1]
            name, description, status, note = [cell.strip() for cell in cells]
            name = name.strip("`").split("(")[0]
            label = next(label for label in STATES if status.endswith(label))
            yield {"id": module + "." + name, "module": module, "name": name,
                   "group": group, "description": description, "status": STATES[label],
                   "statusLabel": label, "note": note}


def section_nodes(heading):
    level = int(heading.name[1])
    for node in heading.next_siblings:
        if getattr(node, "name", "") in ("h1", "h2", "h3", "h4", "h5") and int(node.name[1]) <= level:
            break
        yield node


def section(heading):
    return BeautifulSoup("".join(str(node) for node in section_nodes(heading)), "html.parser")


def link(page, anchor=""):
    return BASE + page + ("#" + quote(anchor) if anchor else "")


def signature(code, name):
    # Parse the expression to exclude examples, comments and multiline prose.
    try:
        node = ast.parse(code.strip()).body
        if len(node) == 1 and isinstance(node[0], ast.Expr) and isinstance(node[0].value, ast.Call):
            call = node[0].value
            if isinstance(call.func, ast.Name) and call.func.id == name:
                return ast.unparse(call)
    except SyntaxError:
        pass
    return ""


def parameters(sig):
    if not sig:
        return []
    call = ast.parse(sig).body[0].value
    result = []
    for arg in call.args:
        if isinstance(arg, ast.Name) and arg.id != "self":
            result.append({"name": arg.id, "default": "必填", "help": parameter_help(arg.id)})
    for arg in call.keywords:
        result.append({"name": arg.arg, "default": ast.unparse(arg.value), "help": parameter_help(arg.arg)})
    return result


def sdk_signatures():
    result = {}
    for module, filename in (("xtdata", "xtdata.py"), ("trader", "xttrader.py")):
        tree = ast.parse((ROOT / "cfquant" / filename).read_text(encoding="utf-8-sig"))
        nodes = tree.body if module == "xtdata" else next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "XtQuantTrader").body
        for node in nodes:
            if isinstance(node, ast.FunctionDef):
                args = ast.unparse(node.args)
                args = re.sub(r"^self,? ?", "", args)
                name = "XtQuantTrader" if node.name == "__init__" else node.name
                result[module + "." + name] = name + "(" + args + ")"
    return result


def schema(content):
    """Retain technical identifiers, types and enum values, never article text."""
    fields = []
    for table in content.select("table"):
        headers = [cell.get_text(strip=True) for cell in table.select("thead th")]
        if not any(name in headers for name in ("属性", "枚举变量名")):
            continue
        for row in table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) >= 2:
                fields.append([cells[0].get_text(strip=True), cells[1].get_text(strip=True)])
    if not fields:
        for pre in content.select("pre"):
            for line in pre.get_text().splitlines():
                match = re.match(r"\s*['\"]([A-Za-z_][\w]*)['\"]\s*#", line)
                if match:
                    fields.append([match.group(1), line.partition("#")[2].strip()])
                else:
                    enum = re.match(r"\s*([0-9,]+)\s*-\s*(.{1,55})$", line)
                    if enum:
                        fields.append([enum.group(1), enum.group(2)])
    for item in content.select("li"):
        if item.find("ul"):
            continue
        constant = item.find("code")
        if constant and constant.get_text().startswith("xtconstant."):
            name = constant.get_text(strip=True)
            fields.append([name, item.get_text(" ", strip=True).split(" - ")[0]])
    return list(dict.fromkeys(tuple(field) for field in fields))


def return_types(content):
    for item in content.select("li"):
        label = item.find("p", recursive=False)
        if label and label.get_text(strip=True) == "返回":
            value = item.get_text(" ", strip=True)
            names = re.findall(r"\b(?:pd\.DataFrame|DataFrame|numpy\.ndarray|ndarray|dict|list|int|float|bool|None|Xt[A-Za-z]+|StockAccount|Credit[A-Za-z]+|StkCompacts)\b", value)
            if names:
                return "原版结果涉及的类型：" + "、".join("`" + name + "`" for name in dict.fromkeys(names)) + "。结果的嵌套结构与业务成功条件见对应原文。"
    return ""


def build(source_dir):
    text = CHECKLIST.read_text(encoding="utf-8-sig")
    entries = list(checklist_entries(text))
    sdk = sdk_signatures()
    documents = {}
    for page in ("start_now.html", "xtdata.html", "xttrader.html"):
        documents[page] = BeautifulSoup((source_dir / page).read_text(encoding="utf-8"), "html.parser").select_one(".theme-default-content")
        if documents[page] is None:
            raise ValueError("Missing official document content: " + page)
    used = set()
    for entry in entries:
        page = "xtdata.html" if entry["module"] == "xtdata" else "xttrader.html"
        document = documents[page]
        found, sig = None, ""
        for pre in document.select("pre"):
            sig = signature(pre.get_text(), entry["name"])
            if sig:
                found = pre.find_previous(re.compile("^h[1-5]$"))
                break
        if entry["module"] == "type":
            found = next((h for h in document.select("h3") if entry["name"].lower() in h.get_text().lower()), None)
            sig = "StockAccount(account_id, account_type='STOCK')" if entry["name"] == "StockAccount" else ""
        elif not sig and entry["group"] != "官网补充提及":
            raise ValueError("Official signature missing or changed: " + entry["id"])
        entry["signature"] = sig
        entry["sdkSignature"] = sdk.get(entry["id"], "") if entry["status"] in ("supported", "partial") else ""
        entry["parameters"] = parameters(sig)
        entry["fields"] = schema(section(found)) if found is not None and entry["module"] == "type" else []
        entry["originalReturns"] = return_types(section(found)) if found is not None and entry["module"] != "type" else ""
        if found is not None:
            anchor = found.get("id", "")
            entry["title"] = found.get_text(" ", strip=True).lstrip("# ")
            used.add((page, anchor))
        else:
            anchor = "版本信息" if page == "xtdata.html" else "创建策略"
            if entry["name"] == "query_stock_orders_async":
                anchor = "开启主动请求接口的专用线程"
            entry["title"] = entry["description"]
        entry["source"] = link(page, anchor)
        entry.update(example_for(entry))
        for key in ("example", "originalExample"):
            if entry.get(key):
                ast.parse(entry[key], filename=entry["id"] + ":" + key)
        if entry["status"] in ("supported", "partial") and not entry.get("example"):
            raise ValueError("Missing cfquant solution: " + entry["id"])
    references = []
    for page, document in documents.items():
        for h in document.select("h2, h3, h4"):
            anchor = h.get("id", "")
            if (page, anchor) in used:
                continue
            content = section(h)
            # Leaf chapters cover overview, dictionaries and all field appendices.
            if content.select_one("h3, h4, h5"):
                continue
            ref = {"id": "reference." + page[:-5] + "." + anchor, "module": "reference",
                   "group": {"start_now.html": "快速开始", "xtdata.html": "行情概述与附录", "xttrader.html": "交易概述与字典"}[page],
                   "name": h.get_text(" ", strip=True).lstrip("# "), "source": link(page, anchor),
                   "fields": schema(content), "status": "reference"}
            ref.update(reference_solution(ref))
            references.append(ref)
    for name, page, description, related in (
        ("完整实例", "code_examples.html", "讯投完整策略实例可在本节在线原文中阅读。cfquant 的连接、回调和查询示例使用同样的生命周期顺序，迁移时还需逐项核对策略使用的接口。", ["trader.XtQuantTrader", "callback.on_stock_order"]),
        ("常见问题", "question_function.html", "讯投常见问题对应 MiniQMT 运行环境。cfquant 的连接问题还需检查 Web 绑定、QMT 入口策略及桥状态；参数不一致时以当前 SDK 签名为准。", ["trader.connect", "xtdata.get_financial_data"]),
        ("xtquant 版本下载", "download_xtquant.html", "这里是讯投 xtquant 的官方版本下载入口。cfquant 安装与升级使用 python -m pip install --upgrade cfquant，桥脚本需要随版本更新并重启策略。", ["trader.XtQuantTrader"]),
    ):
        references.append({"id": "reference." + page[:-5], "module": "reference", "group": "实例与帮助", "name": name,
                           "source": link(page), "fields": [], "status": "reference", "description": description,
                           "usage": "对应的 cfquant 接入流程：", "related": related,
                           "example": example_for(next(e for e in entries if e["id"] == "trader.XtQuantTrader"))["example"]})
    payload = {"updated": re.search(r"更新时间：(\d{4}-\d{2}-\d{2})", text).group(1),
               "checklistSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "entries": entries, "references": references}
    OUTPUT.write_text("// Generated by tools/build_python_api_reference.py; edit its sources.\nwindow.CFQUANT_PYTHON_API = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print("Generated %s API entries and %s reference chapters" % (len(entries), len(references)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    build(parser.parse_args().source_dir)
