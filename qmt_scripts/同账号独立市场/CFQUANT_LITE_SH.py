#coding:gbk
#! /usr/bin/python

import io
import os

_MARKET = "SH"
_ENTRY_SCRIPT = "CFQUANT_LITE.py"
_CONFIG_FILENAME = "cfquant_bridge_config_SH.json"


def _base_dir():
    path = globals().get("__file__") or ""
    if path and not str(path).startswith("<"):
        return os.path.dirname(os.path.abspath(path))
    try:
        return os.path.abspath(os.getcwd())
    except Exception:
        return ""


def _first_existing(candidates):
    fallback = ""
    for path in candidates:
        if not path:
            continue
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
        if not fallback:
            fallback = path
        if os.path.isfile(path):
            return path
    return fallback


def _config_path():
    base = _base_dir()
    parent = os.path.dirname(base)
    candidates = []
    if os.path.basename(base).lower() == "python":
        candidates.extend([
            os.path.join(parent, "bin.x64", _CONFIG_FILENAME),
            os.path.join(base, _CONFIG_FILENAME),
        ])
    candidates.extend([
        os.path.join(base, _CONFIG_FILENAME),
        os.path.join(base, "bin.x64", _CONFIG_FILENAME),
        os.path.join(parent, _CONFIG_FILENAME),
        os.path.join(parent, "bin.x64", _CONFIG_FILENAME),
    ])
    return _first_existing(candidates)


def _entry_path():
    base = _base_dir()
    parent = os.path.dirname(base)
    env_path = os.environ.get("CFQUANT_MARKET_ENTRY_FILE") or ""
    candidates = [
        env_path,
        os.path.join(base, _ENTRY_SCRIPT),
        os.path.join(parent, _ENTRY_SCRIPT),
        os.path.join(parent, "qmt_scripts", _ENTRY_SCRIPT),
        os.path.join(parent, "python", _ENTRY_SCRIPT),
    ]
    return _first_existing(candidates)


def _read_source(path):
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            with io.open(path, "r", encoding=encoding) as f:
                return f.read()
        except Exception:
            pass
    with open(path, "r") as f:
        return f.read()


os.environ["CFQUANT_MARKET"] = _MARKET
os.environ["CFQUANT_MARKET_SOURCE"] = "cfquant_market_entry"
if not os.environ.get("CFQUANT_BRIDGE_CONFIG_FILE"):
    os.environ["CFQUANT_BRIDGE_CONFIG_FILE"] = _config_path()
    os.environ["CFQUANT_BRIDGE_CONFIG_FILE_SOURCE"] = "cfquant_market_entry"

_entry = _entry_path()
if not _entry or not os.path.isfile(_entry):
    raise RuntimeError("CFQUANT market entry script not found: %s" % _ENTRY_SCRIPT)

globals()["__file__"] = _entry
exec(compile(_read_source(_entry), _entry, "exec"), globals(), globals())
