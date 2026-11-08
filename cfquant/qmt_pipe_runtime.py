"""In-memory managed strategy control over the existing Pipe connection (QMT 3.6+)."""

from .diagnostic_context import VersionedErrorMixin, versioned_message

import functools as _cq_functools
import os as _cq_os
import sys as _cq_sys
import threading as _cq_threading
import time as _cq_time
import uuid as _cq_uuid


class ManagedStrategyError(VersionedErrorMixin, RuntimeError):
    """A rejection made before entering any QMT business dispatcher."""

    def __init__(self, message, code, runtime_instance_id, retry_when=""):
        super(ManagedStrategyError, self).__init__(message)
        self.error_details = dict(code=code, stage="before_dispatch", dispatched=False,
                                  safe_to_retry=bool(retry_when), retry_when=retry_when,
                                  runtime_instance_id=runtime_instance_id)


class ManagedPipeRuntime(object):
    def __init__(self, descriptor=None):
        self.descriptor = dict(descriptor or {})
        self.runtime_instance_id = _cq_uuid.uuid4().hex
        self.active = False
        self.approved = False
        self.revoked = False
        self.namespace = {}
        self.original_stop = None
        self.failure = ""
        self.calls = 0
        self.bridges_closed = False
        self.closing = False
        self.attached_bridges = []
        self.mutex = _cq_threading.RLock()

    def acquire(self):
        if not self.descriptor:
            self.active = True
            return self
        # sys survives strategy namespace reloads inside one QMT process.
        # Across processes the Pipe hub arbitrates ownership of request channels.
        registry = _cq_sys.__dict__.setdefault("_cfquant_pipe_strategies", {})
        lock = _cq_sys.__dict__.setdefault("_cfquant_pipe_strategies_lock", _cq_threading.RLock())
        with lock:
            key = (self.descriptor["runtime_key"], self.descriptor["role"])
            incompatible = any(scope[0] == key[0] and (
                owner.descriptor.get("mode") != self.descriptor["mode"]
                or owner.descriptor.get("generation") != self.descriptor["generation"])
                for scope, owner in registry.items())
            if key in registry or incompatible:
                raise RuntimeError("Another cfquant strategy still owns this QMT account role.")
            registry[key] = self
            self.active = True
        return self

    def status(self):
        bridges = [self.namespace.get(name) for name in ("_normal_bridge", "_trade_bridge")
                   if self.namespace.get(name) is not None]
        ready = bool(bridges) and all(getattr(bridge, "running", False)
                                     and getattr(bridge, "context", None) is not None for bridge in bridges)
        state = "error" if self.failure else ("stopped" if not self.active or self.revoked
                                              else ("running" if ready and self.approved else "loaded"))
        return dict(self.descriptor, state=state, error=self.failure,
                    pid=_cq_os.getpid(), updated_at=_cq_time.time(),
                    runtime_instance_id=self.runtime_instance_id)

    def control(self, desired):
        if desired.get("runtime_key") != self.descriptor.get("runtime_key"):
            raise ValueError("Managed strategy account scope mismatch")
        accepted = desired.get("accepted_generations") or []
        if not isinstance(accepted, (tuple, list)):
            accepted = []
        allowed = (desired.get("enabled") is True
                   and desired.get("mode") == self.descriptor["mode"]
                   and self.descriptor["generation"] in [desired.get("generation")] + accepted)
        with self.mutex:
            self.approved = allowed and self.active and not self.revoked
            if not allowed and not self.revoked:
                self.revoked = True
                # Block requests immediately; let the control response leave before closing Pipe.
                worker = _cq_threading.Timer(0.1, self.close)
                worker.daemon = True
                worker.start()
        return self.status()

    def dispatch(self, function):
        dispatch_request = self.wrap(function, reject=True)
        @_cq_functools.wraps(function)
        def guarded(action, params, msg):
            if action == "cfquant.strategy.control":
                return self.control(params or {})
            if action == "cfquant.status":
                return function(action, params, msg)
            with self.mutex:
                if not self.active or self.revoked:
                    raise ManagedStrategyError("The account's cfquant strategy mode has changed.",
                                               "STRATEGY_MODE_CHANGED", self.runtime_instance_id)
                if not self.approved:
                    raise ManagedStrategyError(
                        "Managed strategy is awaiting account mode confirmation from cfquant Web.",
                        "ACCOUNT_MODE_UNCONFIRMED", self.runtime_instance_id, "account_ready")
            result = dispatch_request(action, params, msg)
            if action == "cfquant.ping" and isinstance(result, dict):
                result = dict(result, managed_runtime=self.status())
            return result
        return guarded

    def wrap(self, function, reject=False):
        @_cq_functools.wraps(function)
        def guarded(*args, **kwargs):
            with self.mutex:
                if not self.active or self.revoked:
                    if reject:
                        raise ManagedStrategyError("The account's cfquant strategy mode has changed.",
                                                   "STRATEGY_MODE_CHANGED", self.runtime_instance_id)
                    return None
                self.calls += 1
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

    def bind(self, namespace):
        self.namespace = namespace
        self.original_stop = namespace.get("stop")
        for name, value in list(namespace.items()):
            if (name in ("init", "after_init", "handlebar", "cfquant_normal_timer", "cfquant_ctype_trade_timer")
                    or name.endswith("_callback")) and callable(value):
                namespace[name] = self.wrap(value)
        for name in ("_normal_bridge", "_trade_bridge"):
            bridge = namespace.get(name)
            if bridge is not None:
                self.attach_bridge(bridge)
        namespace["stop"] = self.close

    def attach_bridge(self, bridge):
        if bridge not in self.attached_bridges:
            self.attached_bridges.append(bridge)
        if not self.descriptor or getattr(bridge, "managed_runtime", None) is self:
            return
        bridge.managed_runtime = self
        bridge._dispatch = self.dispatch(bridge._dispatch)
        for method in ("start", "poll", "pump"):
            function = getattr(bridge, method, None)
            if callable(function):
                setattr(bridge, method, self.wrap(function))

    def release_if_idle(self):
        if self.bridges_closed and self.calls == 0:
            registry = _cq_sys.__dict__.get("_cfquant_pipe_strategies", {})
            key = (self.descriptor.get("runtime_key"), self.descriptor.get("role"))
            lock = _cq_sys.__dict__.setdefault("_cfquant_pipe_strategies_lock", _cq_threading.RLock())
            with lock:
                if registry.get(key) is self:
                    registry.pop(key, None)

    def close(self, context=None):
        with self.mutex:
            if self.closing or self.bridges_closed:
                return
            self.closing = True
            self.active = False
            self.approved = False
        errors = []
        completed = False
        bridges = list(self.attached_bridges)
        for name in ("_normal_bridge", "_trade_bridge"):
            bridge = self.namespace.get(name)
            if bridge is not None and bridge not in bridges:
                bridges.append(bridge)
        try:
            # Stop ALL Pipe workers before the entry cancels QMT timers or
            # unsubscribes quotes. Either native operation may block or fail.
            for bridge in bridges:
                stop_transport = getattr(bridge, "stop_transport", None)
                if callable(stop_transport):
                    try:
                        stop_transport()
                    except Exception as error:
                        errors.append(str(error))
            original_failed = False
            if self.original_stop is not None:
                try:
                    self.original_stop(context)
                except Exception as error:
                    original_failed = True
                    errors.append(str(error))
            if self.original_stop is None or original_failed:
                for bridge in bridges:
                    try:
                        bridge.close()
                    except Exception as error:
                        errors.append(str(error))
            worker = self.namespace.get("_trade_thread")
            if worker is not None and worker is not _cq_threading.current_thread() and worker.is_alive():
                worker.join(0.5)
            completed = True
        finally:
            with self.mutex:
                self.closing = False
                self.bridges_closed = completed and not errors
                if self.bridges_closed:
                    self.release_if_idle()
        if errors:
            self.failure = "; ".join(errors)
            print(versioned_message("cfquant strategy shutdown failed: %s" % self.failure))
