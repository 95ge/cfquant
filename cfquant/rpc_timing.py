"""Per-request diagnostics; never change the RPC method's return value."""
import time


class RpcTiming(object):
    def __init__(self, output, request_id):
        self.output = output
        self.started = time.perf_counter()
        self.received_at = None
        if output is not None:
            output.update({
                "request_id": request_id,
                "qmt": {"available": False, "reason": "no_response"},
                "rpc": {"response_received": False},
            })

    def received(self, message):
        self.received_at = time.perf_counter()
        if self.output is None:
            return
        self.output["rpc"].update({
            "response_received": True,
            "response_ok": bool(message.get("ok")),
            "wait_ms": round((self.received_at - self.started) * 1000, 3),
            "json_decode_ms": message.get("_client_parse_ms"),
        })
        meta = message.get("meta") or {}
        qmt = (meta.get("timing") or {}).get("qmt")
        self.output["qmt"] = dict(qmt) if isinstance(qmt, dict) else {
            "available": False, "reason": "bridge_timing_unavailable",
        }

    def decode(self, value, decoder):
        started = time.perf_counter()
        try:
            return decoder(value)
        finally:
            if self.output is not None:
                self.output["rpc"]["decode_ms"] = round((time.perf_counter() - started) * 1000, 3)

    def finish(self):
        if self.output is not None:
            elapsed = round((time.perf_counter() - self.started) * 1000, 3)
            self.output["rpc"]["total_ms"] = elapsed
            if self.received_at is None:
                self.output["rpc"]["wait_ms"] = elapsed
