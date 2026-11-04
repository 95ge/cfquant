# -*- coding: utf-8 -*-
import queue
import threading
import time

from .normal_bridge import NormalQmtBridge
from .pipe_transport import DEFAULT_PIPE_NAME, PipeTxClient
from .tx_trade_bridge import TxTradeBridge


class PipeNormalQmtBridge(NormalQmtBridge):
    file_io_enabled = False

    def __init__(
        self,
        context,
        pipe_name=None,
        request_channel="cfquant.normal.request",
        request_channels=None,
        callback_event_channel="cfquant.callback.event",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
        schedule_timer=True,
        pump_max_count=20,
        pump_max_ms=5,
        dispatch_on_qmt_thread=False,
        connect_timeout_ms=3000,
    ):
        super(PipeNormalQmtBridge, self).__init__(
            context,
            ip="127.0.0.1",
            port=0,
            token="",
            request_channel=request_channel,
            callback_event_channel=callback_event_channel,
            bridge_id=bridge_id,
            account_id=account_id,
            show=show,
            globals_dict=globals_dict,
            schedule_timer=schedule_timer,
            pump_max_count=pump_max_count,
            pump_max_ms=pump_max_ms,
            dispatch_on_qmt_thread=dispatch_on_qmt_thread,
            order_meta_enabled=False,
        )
        self.pipe_name = pipe_name or DEFAULT_PIPE_NAME
        self.request_channels = list(request_channels or [request_channel])
        self.connect_timeout_ms = int(connect_timeout_ms)
        self._pipe_lock = threading.RLock()
        self._pipe_closed = False

    def start(self):
        with self._pipe_lock:
            if self._pipe_closed:
                raise RuntimeError("pipe bridge is closed")
            return self._start_transport()

    def _start_transport(self):
        runtime = self.globals_dict.get("_managed_runtime")
        if runtime is not None:
            runtime.attach_bridge(self)
        if self.running:
            return self
        self.running = True
        if not self.started_at:
            self.started_at = time.time()
        self.tx = PipeTxClient(
            pipe_name=self.pipe_name,
            request_channel=self.request_channel,
            request_channels=self.request_channels,
            bridge_id=self.bridge_id,
            endpoint_name="normal",
            show=self.show,
            connect_timeout_ms=self.connect_timeout_ms,
        )
        self.tx._log = self._log
        self.tx.start()
        self.tx.start_txg(self.request_channel)
        self.recv_thread = threading.Thread(target=self._recv_loop)
        self.recv_thread.daemon = True
        self.recv_thread.start()
        self._log(
            "pipe normal bridge started pipe=%s request_channel=%s"
            % (self.pipe_name, self.request_channel)
        )
        self._publish_runtime_report("start")
        return self

    def stop_transport(self):
        # This phase must not wait for QMT native work or dispatch_lock.
        with self._pipe_lock:
            self._pipe_closed = True
            self.running = False
            tx, self.tx = self.tx, None
        event = getattr(self, "worker_event", None)
        if event is not None:
            event.set()
        if tx is not None:
            tx.close()
        deadline = time.monotonic() + 0.5
        for worker in (getattr(self, "recv_thread", None), getattr(self, "worker_thread", None)):
            if worker is not None and worker is not threading.current_thread() and worker.is_alive():
                worker.join(max(0.0, deadline - time.monotonic()))

    def close(self):
        self.stop_transport()
        self._flush_pending_order_errors(force=True)
        self._close_quote_subscriptions()
        if self.context is not None and self.schedule_key:
            try:
                self.context.cancel_schedule_run(self.schedule_key)
            except Exception:
                pass
        self._log("pipe normal bridge stopped")

    def _status_extra(self):
        data = super(PipeNormalQmtBridge, self)._status_extra()
        data.update({
            "transport": "pipe",
            "pipe_name": self.pipe_name,
            "pipe_request_channels": list(self.request_channels),
            "pipe_connected": self.tx is not None and self.tx._get_conn() is not None,
        })
        return data


class PipeTradeBridge(TxTradeBridge):
    file_io_enabled = False

    def __init__(
        self,
        context,
        pipe_name=None,
        request_channel="cfquant.trade.request",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
        connect_timeout_ms=3000,
    ):
        super(PipeTradeBridge, self).__init__(
            context,
            ip="127.0.0.1",
            port=0,
            token="",
            request_channel=request_channel,
            bridge_id=bridge_id,
            account_id=account_id,
            show=show,
            globals_dict=globals_dict,
            order_meta_enabled=False,
        )
        self.pipe_name = pipe_name or DEFAULT_PIPE_NAME
        self.connect_timeout_ms = int(connect_timeout_ms)
        self._pipe_lock = threading.RLock()
        self._pipe_closed = False

    def start(self):
        with self._pipe_lock:
            if self._pipe_closed:
                raise RuntimeError("pipe bridge is closed")
            return self._start_transport()

    def _start_transport(self):
        runtime = self.globals_dict.get("_managed_runtime")
        if runtime is not None:
            runtime.attach_bridge(self)
        if self.running:
            return self
        self.running = True
        if not self.started_at:
            self.started_at = time.time()
        self.tx = PipeTxClient(
            pipe_name=self.pipe_name,
            request_channel=self.request_channel,
            bridge_id=self.bridge_id,
            endpoint_name="trade",
            show=self.show,
            connect_timeout_ms=self.connect_timeout_ms,
        )
        self.tx._log = self._log
        self.tx.start()
        self.tx.start_txg(self.request_channel)
        self._log(
            "pipe trade bridge started pipe=%s request_channel=%s"
            % (self.pipe_name, self.request_channel)
        )
        self._publish_runtime_report("start")
        return self

    def stop_transport(self):
        PipeNormalQmtBridge.stop_transport(self)

    def close(self):
        self.stop_transport()
        self._log("pipe trade bridge stopped")

    def poll(self, max_messages=100, timeout=0):
        self.start()
        count = 0
        while self.running and count < max_messages:
            try:
                raw = self.tx.Q.get(timeout=timeout if count == 0 else 0)
            except queue.Empty:
                break
            except Exception:
                break
            if raw is None:
                break
            self._handle_raw(raw)
            count += 1
        return count

    def _status_extra(self):
        return {
            "transport": "pipe",
            "pipe_name": self.pipe_name,
            "pipe_connected": self.tx is not None and self.tx._get_conn() is not None,
        }


def start_pipe_normal_bridge(
    context,
    pipe_name=None,
        request_channel="cfquant.normal.request",
        request_channels=None,
        callback_event_channel="cfquant.callback.event",
    bridge_id="default",
    account_id="",
    show=True,
    schedule_timer=True,
    pump_max_count=20,
    pump_max_ms=5,
    dispatch_on_qmt_thread=False,
    connect_timeout_ms=3000,
):
    import sys

    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return PipeNormalQmtBridge(
        context,
        pipe_name=pipe_name,
        request_channel=request_channel,
        request_channels=request_channels,
        callback_event_channel=callback_event_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
        schedule_timer=schedule_timer,
        pump_max_count=pump_max_count,
        pump_max_ms=pump_max_ms,
        dispatch_on_qmt_thread=dispatch_on_qmt_thread,
        connect_timeout_ms=connect_timeout_ms,
    ).start()


def start_pipe_trade_bridge(
    context,
    pipe_name=None,
    request_channel="cfquant.trade.request",
    bridge_id="default",
    account_id="",
    show=True,
    connect_timeout_ms=3000,
):
    import sys

    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return PipeTradeBridge(
        context,
        pipe_name=pipe_name,
        request_channel=request_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
        connect_timeout_ms=connect_timeout_ms,
    ).start()
