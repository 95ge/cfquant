# -*- coding: utf-8 -*-
"""Build and source identity helpers."""
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

def _valid_commit(value):
    value = str(value or "").strip().lower()
    return value if _COMMIT_RE.fullmatch(value) else ""

def _read_git_dir(source_root):
    marker = Path(source_root) / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        text = marker.read_text(encoding="utf-8", errors="replace").strip()
        if text.lower().startswith("gitdir:"):
            path = Path(text.split(":", 1)[1].strip())
            return path if path.is_absolute() else (marker.parent / path).resolve()
    return None

@lru_cache(maxsize=8)
def get_git_commit(source_root=None):
    """Return the full source commit, or an empty string when unavailable."""
    override = _valid_commit(os.environ.get("CFQUANT_GIT_COMMIT"))
    if override:
        return override
    root = Path(source_root or Path(__file__).resolve().parent.parent).resolve()
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=2, check=False)
        commit = _valid_commit(result.stdout)
        if commit:
            return commit
    except Exception:
        pass
    git_dir = _read_git_dir(root)
    if not git_dir:
        return ""
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii", errors="ignore").strip()
        if head.startswith("ref: "):
            ref = head[5:].strip()
            ref_path = git_dir / ref
            if ref_path.is_file():
                return _valid_commit(ref_path.read_text(encoding="ascii", errors="ignore"))
            packed = git_dir / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="ascii", errors="ignore").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref:
                        return _valid_commit(parts[0])
        return _valid_commit(head)
    except Exception:
        return ""

def build_identity(version, source_root=None):
    commit = get_git_commit(source_root)
    short = commit[:7] if commit else ""
    return {"git_commit": commit, "short_commit": short,
            "build_version": "%s+g%s" % (version, short) if version and short else str(version or "")}
