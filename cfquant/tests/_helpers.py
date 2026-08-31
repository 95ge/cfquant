# -*- coding: utf-8 -*-
import json
import os
import sys
import time
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def configure_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def parse_csv(value, default=None, upper=False):
    if value is None or value == "":
        items = list(default or [])
    else:
        items = [item.strip() for item in str(value).split(",") if item.strip()]
    if upper:
        items = [item.upper() for item in items]
    return items


def compact_value(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)[:240]


def object_to_plain(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return value


def summarize(value, sample_size=2):
    if value is None:
        return {"type": "None", "empty": True}
    shape = getattr(value, "shape", None)
    if shape is not None:
        info = {
            "type": type(value).__name__,
            "shape": list(shape),
        }
        columns = getattr(value, "columns", None)
        if columns is not None:
            info["columns"] = [str(item) for item in list(columns)[:20]]
        try:
            info["head"] = str(value.head(sample_size))
        except Exception:
            info["repr"] = repr(value)[:1000]
        return info
    value = object_to_plain(value)
    if isinstance(value, dict):
        sample = {}
        for key, item in list(value.items())[:sample_size]:
            item_shape = getattr(item, "shape", None)
            if item_shape is not None:
                sample[str(key)] = summarize(item, sample_size=sample_size)
                continue
            else:
                item = object_to_plain(item)
            if isinstance(item, dict):
                sample[str(key)] = {
                    "type": "dict",
                    "len": len(item),
                    "keys": [str(k) for k in list(item.keys())[:12]],
                }
            elif isinstance(item, list):
                sample[str(key)] = {
                    "type": "list",
                    "len": len(item),
                    "sample": [compact_value(object_to_plain(x)) for x in item[:1]],
                }
            else:
                sample[str(key)] = compact_value(item)
        return {
            "type": "dict",
            "len": len(value),
            "keys": [str(k) for k in list(value.keys())[:20]],
            "sample": sample,
        }
    if isinstance(value, list):
        sample = []
        for item in value[:sample_size]:
            item = object_to_plain(item)
            if isinstance(item, dict):
                sample.append({
                    "type": "dict",
                    "len": len(item),
                    "keys": [str(k) for k in list(item.keys())[:12]],
                    "sample": {
                        str(k): compact_value(v)
                        for k, v in list(item.items())[:8]
                    },
                })
            else:
                sample.append(compact_value(item))
        return {
            "type": "list",
            "len": len(value),
            "sample": sample,
        }
    return {
        "type": type(value).__name__,
        "repr": repr(value)[:1000],
    }


def emit_call(name, func, example=None):
    # 每个调用示例都独立计时并捕获异常，便于一次运行看到多项接口的可用情况。
    started = time.perf_counter()
    try:
        result = func()
        payload = {
            "case": name,
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "summary": summarize(result),
        }
        if example:
            payload["example"] = example
        print_json(payload)
        return result
    except Exception as error:
        payload = {
            "case": name,
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_type": type(error).__name__,
            "error": str(error),
        }
        if example:
            payload["example"] = example
        print_json(payload)
        return None


def emit_skip(name, reason, example=None):
    # 需要依赖用户输入或现场数据的示例，条件不足时用 skipped 标记说明原因。
    payload = {
        "case": name,
        "ok": False,
        "skipped": True,
        "reason": reason,
    }
    if example:
        payload["example"] = example
    print_json(payload)
    return None


def add_runtime_args(parser):
    parser.add_argument("--transport", default="ctypes", help="cfquant 通信模式，默认 ctypes。")
    parser.add_argument("--bridge-id", default="default", help="桥接 ID，默认 default。")
    parser.add_argument("--timeout", type=float, default=15.0, help="请求超时时间，单位秒。")


def configure_cfquant(args):
    from cfquant import configure

    configure(
        transport=args.transport,
        bridge_id=args.bridge_id,
        timeout=args.timeout,
    )


def default_account_id():
    value = os.environ.get("CFQUANT_ACCOUNT_ID", "").strip()
    if value:
        return value
    paths = [
        PROJECT_ROOT / "runtime" / "config" / "cfquant_web_config.json",
        PROJECT_ROOT / "cfquant_web_config.json",
    ]
    for config_path in paths:
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        account_id = str(data.get("default_account_id") or data.get("data_provider_account_id") or "").strip()
        if account_id:
            return account_id
    return ""


def close_default_client():
    try:
        from cfquant import get_client

        get_client().close()
    except Exception:
        pass
