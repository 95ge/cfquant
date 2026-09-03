# -*- coding: utf-8 -*-
import queue
import threading
import time

from .normal_bridge import NormalQmtBridge
from .pipe_transport import DEFAULT_PIPE_NAME, PipeTxClient
from .tx_trade_bridge import TxTradeBridge


class PipeNormalQmtBridge(NormalQmtBridge):
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
        pump_max_ms=0,
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
        )
        self.pipe_name = pipe_name or DEFAULT_PIPE_NAME
        self.request_channels = request_channels or [request_channel]
        self.connect_timeout_ms = int(connect_timeout_ms)

    def start(self):
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
        ).start()
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

    def close(self):
        self.running = False
        self.worker_event.set()
        if self.context is not None and self.schedule_key:
            try:
                self.context.cancel_schedule_run(self.schedule_key)
            except Exception:
                pass
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.close()
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
        )
        self.pipe_name = pipe_name or DEFAULT_PIPE_NAME
        self.connect_timeout_ms = int(connect_timeout_ms)

    def start(self):
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
        ).start()
        self.tx.start_txg(self.request_channel)
        self._log(
            "pipe trade bridge started pipe=%s request_channel=%s"
            % (self.pipe_name, self.request_channel)
        )
        self._publish_runtime_report("start")
        return self

    def close(self):
        self.running = False
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass
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
    pump_max_ms=0,
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
