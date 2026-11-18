"""Use typing backports inside Frida without changing stdlib typing or files.

Frida 17.16.4 declares Python >=3.7 but imports NotRequired and ParamSpec
directly from typing. Its native extension is unchanged; only its Python
modules receive a local import function for their typing annotations.
Dependency probes also load this helper by path, without importing cfquant.
"""
import builtins
import importlib.machinery
import sys
import threading
import typing


TYPING_REQUIREMENT = "typing_extensions>=4.4"
_LOCK = threading.Lock()


class FridaTypingCompatibilityError(ImportError):
    pass


class _TypingLoader:
    def __init__(self, loader, backport):
        self.loader = loader
        self.backport = backport

    def create_module(self, spec):
        return self.loader.create_module(spec)

    def _import(self, name, globals=None, locals=None, fromlist=(), level=0):
        if name == "typing" and level == 0:
            return self.backport
        return builtins.__import__(name, globals, locals, fromlist, level)

    def exec_module(self, module):
        module.__dict__["__builtins__"] = dict(vars(builtins), __import__=self._import)
        self.loader.exec_module(module)

    def __getattr__(self, name):
        return getattr(self.loader, name)


class _TypingFinder:
    def __init__(self, backport):
        self.backport = backport

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in ("frida", "frida.aio"):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None and spec.loader is not None:
            spec.loader = _TypingLoader(spec.loader, self.backport)
        return spec


def prepare_frida_runtime():
    if hasattr(typing, "NotRequired") and hasattr(typing, "ParamSpec"):
        return
    with _LOCK:
        if any(isinstance(finder, _TypingFinder) for finder in sys.meta_path):
            return
        try:
            import typing_extensions
            for name in ("NotRequired", "ParamSpec", "TypedDict"):
                getattr(typing_extensions, name)
        except (ImportError, AttributeError) as error:
            raise FridaTypingCompatibilityError(
                "Frida 在 Python 3.8–3.10 中需要 %s；请在当前 Python 环境安装或升级该依赖。"
                % TYPING_REQUIREMENT) from error
        sys.meta_path.insert(0, _TypingFinder(typing_extensions))
