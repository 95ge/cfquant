"""Embedded into managed QMT strategies; standard library only, Python 3.6+."""

import functools as _cq_functools
import glob as _cq_glob
import json as _cq_json
import os as _cq_os
import threading as _cq_threading
import time as _cq_time


def _cq_lock(path):
    stream = open(path, "a+b")
    try:
        stream.seek(0)
        if _cq_os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except (OSError, IOError):
        stream.close()
        return None


def _cq_unlock(stream):
    if stream is None:
        return
    try:
        stream.seek(0)
        if _cq_os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


class _CqStrategyLease(object):
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.directory = descriptor["lease_dir"]
        self.lease = None
        self.active = False
        self.namespace = None
        self.original_stop = None
        self.mutex = _cq_threading.RLock()
        self.closed = _cq_threading.Event()
        self.calls = 0
        self.bridges_closed = False
        self.last_report = 0.0
        self.failure = ""

    def report(self, state, error=""):
        path = self.descriptor.get("runtime_status_path")
        if not path:
            return
        temporary = path + ".%s.%s.pending" % (_cq_os.getpid(), _cq_threading.get_ident())
        try:
            payload = {"state": state, "error": error, "generation": self.descriptor["generation"],
                       "pid": _cq_os.getpid(), "updated_at": _cq_time.time()}
            with open(temporary, "w", encoding="utf-8") as stream:
                _cq_json.dump(payload, stream, ensure_ascii=True)
            _cq_os.replace(temporary, path)
            self.last_report = payload["updated_at"]
        except OSError:
            pass
        finally:
            try:
                if _cq_os.path.exists(temporary):
                    _cq_os.remove(temporary)
            except OSError:
                pass

    def allowed(self):
        try:
            with open(self.descriptor["control_path"], encoding="utf-8") as stream:
                desired = _cq_json.load(stream)
            accepted = desired.get("accepted_generations")
            if not isinstance(accepted, (list, tuple, set)):
                accepted = ()
            allowed_generations = set([desired.get("generation")])
            allowed_generations.update(str(item) for item in accepted if item)
            return (desired.get("enabled") is True
                    and self.descriptor["generation"] in allowed_generations
                    and desired.get("mode") == self.descriptor["mode"])
        except (OSError, ValueError):
            return False

    def acquire(self, timeout=10.0):
        _cq_os.makedirs(self.directory, exist_ok=True)
        deadline = _cq_time.monotonic() + timeout
        own_path = _cq_os.path.join(self.directory, self.descriptor["role"] + ".lease")
        while self.allowed():
            gate = _cq_lock(_cq_os.path.join(self.directory, "transition.lock"))
            if gate is not None:
                try:
                    busy = False
                    for path in _cq_glob.glob(_cq_os.path.join(self.directory, "*.lease")):
                        probe = _cq_lock(path)
                        if probe is not None:
                            _cq_unlock(probe)
                            continue
                        try:
                            with open(path + ".json", encoding="utf-8") as stream:
                                owner = _cq_json.load(stream)
                            compatible = owner.get("generation") == self.descriptor["generation"]
                        except (OSError, ValueError):
                            compatible = False
                        if path == own_path or not compatible:
                            busy = True
                            break
                    if not busy and self.allowed():
                        self.lease = _cq_lock(own_path)
                        if self.lease is not None:
                            with open(own_path + ".json", "w", encoding="utf-8") as stream:
                                _cq_json.dump(self.descriptor, stream, ensure_ascii=True)
                            self.active = True
                            return self
                finally:
                    _cq_unlock(gate)
            if _cq_time.monotonic() >= deadline:
                raise RuntimeError("Another cfquant strategy still owns this QMT account; start was refused.")
            _cq_time.sleep(0.1)
        raise RuntimeError("This cfquant strategy is disabled or superseded by the account's selected mode.")

    def close(self, context=None):
        with self.mutex:
            if not self.active:
                return
            self.active = False
            self.closed.set()
        # Release ownership only after every bridge and in-flight call stops.
        # A failed close retains the OS lock so another mode cannot overlap.
        try:
            if self.original_stop is not None:
                self.original_stop(context)
            else:
                for name in ("_cf_bridge", "_normal_bridge", "_trade_bridge"):
                    bridge = (self.namespace or {}).get(name)
                    if bridge is not None:
                        bridge.close()
            with self.mutex:
                self.bridges_closed = True
                self.release_if_idle()
            self.report("error" if self.failure else "stopped", self.failure)
        except Exception as error:
            self.failure = str(error)
            self.report("error", self.failure)
            print("cfquant strategy shutdown failed; account lease retained: %s" % error)

    def bind(self, namespace):
        self.namespace = namespace
        self.original_stop = namespace.get("stop")
        for name, value in list(namespace.items()):
            if (name in ("init", "after_init", "handlebar", "cfquant_normal_timer", "cfquant_ctype_trade_timer")
                    or name.endswith("_callback")) and callable(value):
                namespace[name] = self.wrap(value)
        for name in ("_cf_bridge", "_normal_bridge", "_trade_bridge"):
            bridge = namespace.get(name)
            if bridge is not None:
                for method in ("_dispatch", "start", "poll", "pump"):
                    function = getattr(bridge, method, None)
                    if callable(function):
                        setattr(bridge, method, self.wrap(function, reject=method == "_dispatch"))
        namespace["stop"] = self.close
        if not self.allowed():
            self.close()
            raise RuntimeError("The account mode changed while this strategy was loading.")
        self.report("loaded")
        worker = _cq_threading.Thread(target=self.watch, name="cfquant-mode-lease")
        worker.daemon = True
        worker.start()

    def release_if_idle(self):
        if self.bridges_closed and self.calls == 0 and self.lease is not None:
            _cq_unlock(self.lease)
            self.lease = None

    def wrap(self, function, reject=False):
        @_cq_functools.wraps(function)
        def guarded(*args, **kwargs):
            with self.mutex:
                if not self.active or not self.allowed():
                    if reject:
                        raise RuntimeError("The account's cfquant strategy mode has changed.")
                    return None
                self.calls += 1
            # LTtx init runs its bridge loop synchronously. The watchdog must
            # remain able to close that loop while init is still on the stack.
            try:
                return function(*args, **kwargs)
            except Exception as error:
                if function.__name__ == "init":
                    self.failure = str(error)
                    self.close()
                raise
            finally:
                with self.mutex:
                    self.calls -= 1
                    self.release_if_idle()
        return guarded

    def watch(self):
        while not self.closed.wait(0.25):
            if not self.allowed():
                self.close()
                return
            if _cq_time.time() - self.last_report >= 2:
                with self.mutex:
                    if not self.active:
                        return
                    bridges = [self.namespace.get(name) for name in ("_cf_bridge", "_normal_bridge", "_trade_bridge")
                               if self.namespace.get(name) is not None]
                    ready = bridges and all(getattr(bridge, "running", False)
                                            and getattr(bridge, "context", None) is not None for bridge in bridges)
                    self.report("running" if ready else "loaded")
