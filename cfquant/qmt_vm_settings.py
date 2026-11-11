"""Per-binding settings for the optional QMT VM and MAC launch hooks."""

import re


_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def normalize_qmt_vm_mac(value, *, strict=False):
    """Return a canonical uppercase, dash-separated unicast MAC address."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not _MAC_RE.fullmatch(text):
        if strict:
            raise ValueError("MAC 地址必须是六组十六进制字节，例如 02-11-22-33-44-55")
        return ""
    normalized = text.upper().replace(":", "-")
    octets = bytes.fromhex(normalized.replace("-", ""))
    if not any(octets) or octets[0] & 1:
        if strict:
            raise ValueError("MAC 地址必须是非零单播地址")
        return ""
    return normalized


def _setting_bool(data, names, default, strict):
    present = next((name for name in names if name in data), None)
    if present is None:
        return bool(default)
    value = data.get(present)
    if isinstance(value, bool):
        return value
    if strict:
        raise ValueError("QMT 虚拟机设置中的 %s 必须是 true 或 false" % present)
    return False


def normalize_qmt_vm_settings(value=None, existing=None, strict=False):
    """Normalize saved settings without enabling either hook by inference.

    ``disable_vm`` controls the two VM predicate hooks. ``inject_mac`` controls
    the process-local MAC rewrite. Missing flags always default to false.
    """
    current = dict(existing) if isinstance(existing, dict) else {}
    if value is not None:
        if not isinstance(value, dict):
            if strict:
                raise ValueError("QMT 虚拟机设置必须是对象")
        else:
            current.update(value)
    disable_vm = _setting_bool(current, ("disable_vm",), False, strict)
    inject_mac = _setting_bool(current, ("inject_mac",), False, strict)
    mac_source = current.get("mac_address", "")
    mac_address = normalize_qmt_vm_mac(mac_source, strict=strict)
    if inject_mac and not mac_address:
        if strict:
            raise ValueError("启用 MAC 注入时必须填写有效的 MAC 地址")
        inject_mac = False
    return {
        "disable_vm": bool(disable_vm),
        "inject_mac": bool(inject_mac),
        "mac_address": mac_address,
    }


def qmt_vm_settings_enabled(value=None):
    settings = normalize_qmt_vm_settings(value)
    return bool(settings["disable_vm"] or settings["inject_mac"])
