"""Local QMT credentials protected for the current Windows user with DPAPI."""
import base64
import hashlib
import json
import os
from pathlib import Path
import threading

_LOCK = threading.RLock()


def directory_key(directory):
    root = Path(directory).resolve()
    if root.name.lower() in ("bin.x64", "python"):
        root = root.parent
    return hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()


def _protect(value, entropy):
    import win32crypt
    return win32crypt.CryptProtectData(value, "CFQuant QMT login", entropy, None, None, 1)


def _unprotect(value, entropy):
    import win32crypt
    return win32crypt.CryptUnprotectData(value, entropy, None, None, 1)[1]


class QmtCredentialStore:
    def __init__(self, config_path):
        self.path = Path(config_path).with_name("qmt_login_credentials.json")

    def _read(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def has(self, directory, login_account):
        if not directory:
            return False
        with _LOCK:
            entry = self._read().get(directory_key(directory), {})
            return bool(entry.get("secret") and entry.get("login_account") == login_account)

    def save(self, directory, login_account, password):
        if not directory or not login_account:
            raise ValueError("保存 QMT 密码时必须填写 QMT 目录和登录账号")
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise ValueError("QMT 密码不能为空或超过 1024 字符")
        key = directory_key(directory)
        try:
            encrypted = _protect(password.encode("utf-8"), key.encode("ascii"))
        except Exception:
            raise RuntimeError("无法使用当前 Windows 用户加密 QMT 密码，请检查 pywin32 安装") from None
        with _LOCK:
            data = self._read()
            data[key] = {"login_account": login_account, "secret": base64.b64encode(encrypted).decode("ascii")}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".%s.tmp" % os.getpid())
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(str(temp), str(self.path))

    def password(self, directory, login_account):
        key = directory_key(directory)
        with _LOCK:
            entry = self._read().get(key, {})
        if not entry or entry.get("login_account") != login_account:
            return ""
        try:
            return _unprotect(base64.b64decode(entry["secret"]), key.encode("ascii")).decode("utf-8")
        except Exception:
            raise RuntimeError("无法解密 QMT 密码，请使用保存密码时的 Windows 用户运行，或重新保存密码") from None
