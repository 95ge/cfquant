# -*- coding: utf-8 -*-
import json
import os
import threading
import time

from .pipe_transport import (
    DEFAULT_PIPE_NAME,
    create_pipe_instance,
    dumps_pipe_message,
    loads_pipe_message,
    normalize_pipe_name,
    wait_for_pipe_client,
)
from .protocol import loads_message, pack_event, pack_response
from .version import __version__ as CORE_VERSION


def default_status_file(filename):
    runtime_dir = os.path.abspath(os.environ.get("CFQUANT_RUNTIME_DIR") or os.path.join(os.getcwd(), "runtime"))
    return os.path.join(runtime_dir, "status", filename)


class CfquantPipeHub(object):
    """
    External named-pipe hub.

    QMT-side pipe bridges register as role=qmt with a request_channel.
    External API clients register as role=api and send cfquant request payloads.
    The hub forwards requests to the matching QMT bridge and routes responses or
    events back to the originating API client.
    """

    def __init__(self, pipe_name=None, show=True, default_request_channel="cfquant.normal.request"):
        self.pipe_name = normalize_pipe_name(pipe_name or DEFAULT_PIPE_NAME)
        self.show = show
        self.default_request_channel = default_request_channel
        self.running = False
        self.listener = None
        self.verbose_events = str(os.environ.get("CFQUANT_PIPE_HUB_VERBOSE_EVENTS") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.qmt_rx_by_channel = {}
        self.qmt_tx_by_channel = {}
        self.qmt_channel_by_conn = {}
        self.qmt_lock = threading.RLock()
        self.pending = {}
        self.client_by_id = {}
        self.client_tx_by_id = {}
        self.client_ids_by_conn = {}
        self.state_lock = threading.RLock()
        self.status_file = os.path.abspath(
            os.environ.get("CFQUANT_PIPE_HUB_STATUS_FILE") or default_status_file("cfquant_pipe_hub_status.json")
        )
        self.pending_timeout_seconds = float(os.environ.get("CFQUANT_PIPE_HUB_PENDING_TIMEOUT", "60"))
        self.maintenance_interval_seconds = float(os.environ.get("CFQUANT_PIPE_HUB_MAINTENANCE_INTERVAL", "2"))
        self.maintenance_thread = None

    def start(self):
        if self.running:
            return self
        self.running = True
        self._log("pipe hub started pipe=%s" % self.pipe_name)
        self._start_maintenance()
        self._write_status()
        while self.running:
            conn = None
            try:
                conn = create_pipe_instance(self.pipe_name)
                self.listener = conn
                wait_for_pipe_client(conn)
                self._log("pipe client connected")
                thread = threading.Thread(target=self._client_loop, args=(conn,))
                thread.daemon = True
                thread.start()
            except Exception as e:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                if self.running:
                    self._log("pipe accept failed: %s" % e)
                    time.sleep(0.2)
        return self

    def close(self):
        self.running = False
        try:
            if self.listener is not None:
                self.listener.close()
        except Exception:
            pass
        with self.qmt_lock:
            conns = list(self.qmt_rx_by_channel.values()) + list(self.qmt_tx_by_channel.values())
            self.qmt_rx_by_channel.clear()
            self.qmt_tx_by_channel.clear()
            self.qmt_channel_by_conn.clear()
        with self.state_lock:
            conns.extend(self.client_ids_by_conn.keys())
            self.pending.clear()
            self.client_by_id.clear()
            self.client_tx_by_id.clear()
            self.client_ids_by_conn.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception:
                pass
        self._write_status()

    def _client_loop(self, conn):
        role = "api"
        try:
            while self.running:
                raw = conn.read_frame()
                if raw is None:
                    break
                envelope = loads_pipe_message(raw)
                if envelope:
                    msg_type = envelope.get("type")
                    if msg_type == "hello":
                        role = self._handle_hello(conn, envelope, role)
                        if role in ("api_rx", "qmt_rx"):
                            self._passive_rx_loop(conn, role)
                            break
                    elif msg_type == "request":
                        role = "api"
                        self._handle_api_request(conn, envelope)
                    elif msg_type == "publish":
                        role = "qmt"
                        self._handle_qmt_publish(conn, envelope)
                    else:
                        self._log("pipe ignored envelope type=%s role=%s" % (msg_type, role))
                else:
                    self._handle_api_request(conn, {
                        "payload": raw,
                        "request_channel": self.default_request_channel,
                    })
        except Exception as e:
            if self.running:
                self._log("pipe client loop failed role=%s error=%s" % (role, e))
        finally:
            self._drop_conn(conn)
            try:
                conn.close()
            except Exception:
                pass
            self._log("pipe client disconnected role=%s" % role)
            self._write_status()

    def _passive_rx_loop(self, conn, role):
        while self.running:
            if role == "qmt_rx":
                with self.qmt_lock:
                    if conn not in self.qmt_channel_by_conn:
                        break
            elif role == "api_rx":
                with self.state_lock:
                    if conn not in self.client_ids_by_conn:
                        break
            try:
                raw = conn.read_frame()
            except Exception as e:
                if self.running:
                    self._log("pipe passive rx closed role=%s error=%s" % (role, e))
                break
            if raw is None:
                break
            self._log("pipe ignored passive frame role=%s len=%s" % (role, len(raw or "")))

    def _handle_hello(self, conn, envelope, current_role):
        role = envelope.get("role") or current_role
        if role in ("qmt", "qmt_rx", "qmt_tx"):
            channels = self._envelope_channels(envelope)
            with self.qmt_lock:
                target = self.qmt_rx_by_channel if role in ("qmt", "qmt_rx") else self.qmt_tx_by_channel
                for channel in channels:
                    old = target.get(channel)
                    target[channel] = conn
                    self.qmt_channel_by_conn.setdefault(conn, set()).add(channel)
                    if old is not None and old is not conn:
                        try:
                            old.close()
                        except Exception:
                            pass
            self._log(
                "qmt pipe bridge registered role=%s channels=%s bridge_id=%s"
                % (role, ",".join(channels), envelope.get("bridge_id") or "-")
            )
        elif role in ("api", "api_rx", "api_tx"):
            client_id = envelope.get("client_id")
            if client_id:
                self._remember_client(conn, client_id, receive_conn=role in ("api", "api_rx"))
            self._log("api pipe client registered role=%s client_id=%s" % (role, client_id or "-"))
        self._write_status()
        return role

    def _envelope_channels(self, envelope):
        raw = envelope.get("request_channels")
        if raw is None:
            raw = [envelope.get("request_channel") or self.default_request_channel]
        result = []
        for channel in raw:
            channel = str(channel or "").strip()
            if channel and channel not in result:
                result.append(channel)
        return result or [self.default_request_channel]

    def _handle_api_request(self, conn, envelope):
        api_received_at = time.perf_counter()
        raw = envelope.get("payload")
        msg = loads_message(raw)
        if not msg or msg.get("type") != "request":
            return
        request_id = msg.get("id")
        client_id = envelope.get("client_id") or msg.get("client_id") or msg.get("reply_channel")
        request_channel = envelope.get("request_channel") or self.default_request_channel
        if client_id:
            self._remember_client(conn, client_id, receive_conn=False)
        response_conn = self._client_rx_conn(client_id) or conn
        with self.state_lock:
            if request_id:
                self.pending[request_id] = {
                    "conn": response_conn,
                    "qmt_conn": None,
                    "action": msg.get("action"),
                    "request_channel": request_channel,
                    "api_received_at": api_received_at,
                    "forward_done_at": None,
                }
        qmt = self._qmt_rx_conn(request_channel)
        if qmt is None:
            with self.state_lock:
                self.pending.pop(request_id, None)
            self._send_error(response_conn, request_id, "QMT pipe bridge not connected for channel=%s" % request_channel)
            return
        with self.state_lock:
            pending = self.pending.get(request_id)
            if pending:
                pending["qmt_conn"] = qmt
        forward_start = time.perf_counter()
        try:
            self._send_delivery(qmt, raw, request_channel=request_channel, client_id=client_id)
        except Exception as e:
            self._drop_conn(qmt)
            with self.state_lock:
                self.pending.pop(request_id, None)
            self._send_error(
                response_conn,
                request_id,
                "QMT pipe bridge send failed for channel=%s error=%s" % (request_channel, e),
            )
            return
        forward_done = time.perf_counter()
        with self.state_lock:
            pending = self.pending.get(request_id)
            if pending:
                pending["forward_done_at"] = forward_done
        self._log(
            "pipe forwarded request action=%s id=%s channel=%s api_to_forward_ms=%.2f send_ms=%.2f len=%s"
            % (
                msg.get("action"),
                request_id,
                request_channel,
                self._elapsed_ms(api_received_at, forward_done),
                self._elapsed_ms(forward_start, forward_done),
                len(raw or ""),
            )
        )
        self._write_status()

    def _handle_qmt_publish(self, conn, envelope):
        qmt_received_at = time.perf_counter()
        raw = envelope.get("payload")
        msg = loads_message(raw)
        target = None
        if not msg:
            client_id = envelope.get("channel") or envelope.get("client_id")
            if client_id:
                with self.state_lock:
                    target = self.client_by_id.get(client_id)
            if target is not None:
                try:
                    callback_event = self._pack_callback_event(raw)
                    if callback_event is not None:
                        self._send_delivery(target, callback_event)
                        if self.verbose_events:
                            self._log(
                                "pipe got raw qmt callback channel=%s target=%s len=%s"
                                % (client_id, bool(target), len(raw or ""))
                            )
                        return
                except Exception as e:
                    self._log("pipe raw qmt callback pack failed: %s" % e)
            return
        msg_type = msg.get("type")
        if msg_type == "response":
            request_id = msg.get("id")
            with self.state_lock:
                pending = self.pending.pop(request_id, None)
            if pending:
                target = pending.get("conn")
                api_received_at = pending.get("api_received_at") or qmt_received_at
                forward_done_at = pending.get("forward_done_at") or api_received_at
                self._log(
                    "pipe got qmt response action=%s id=%s channel=%s qmt_roundtrip_ms=%.2f total_to_hub_ms=%.2f len=%s"
                    % (
                        pending.get("action"),
                        request_id,
                        pending.get("request_channel"),
                        self._elapsed_ms(forward_done_at, qmt_received_at),
                        self._elapsed_ms(api_received_at, qmt_received_at),
                        len(raw or ""),
                    )
                )
        elif msg_type == "event":
            client_id = msg.get("client_id") or envelope.get("channel")
            with self.state_lock:
                target = self.client_by_id.get(client_id)
            if self.verbose_events:
                self._log(
                    "pipe got qmt event event=%s client_id=%s target=%s len=%s"
                    % (msg.get("event"), client_id, bool(target), len(raw or ""))
                )
        if target is not None:
            try:
                self._send_delivery(target, raw)
            except Exception as e:
                self._log("pipe response/event delivery failed: %s" % e)
                self._drop_conn(target)

    def _pack_callback_event(self, raw):
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        event_name = str(payload.get("event") or payload.get("event_name") or "callback")
        client_id = str(payload.get("client_id") or payload.get("account_id") or payload.get("bridge_id") or "")
        return pack_event(
            event_name,
            data=payload,
            client_id=client_id or None,
            subscription_id=payload.get("subscription_id") or payload.get("subscribe_id"),
        )

    def _send_error(self, conn, request_id, message):
        try:
            self._send_delivery(
                conn,
                pack_response(request_id, ok=False, error={"type": "ConnectionError", "message": message}),
            )
        except Exception as e:
            self._log("pipe error delivery failed: %s" % e)
            self._drop_conn(conn)

    def _send_delivery(self, conn, payload, request_channel=None, client_id=None):
        conn.write_frame(dumps_pipe_message({
            "type": "delivery",
            "payload": payload,
            "request_channel": request_channel,
            "client_id": client_id,
        }))

    def _qmt_rx_conn(self, request_channel):
        with self.qmt_lock:
            return self.qmt_rx_by_channel.get(request_channel)

    def _client_rx_conn(self, client_id):
        if not client_id:
            return None
        with self.state_lock:
            return self.client_by_id.get(client_id)

    def _remember_client(self, conn, client_id, receive_conn=True):
        with self.state_lock:
            if receive_conn:
                self.client_by_id[client_id] = conn
            else:
                self.client_tx_by_id[client_id] = conn
            self.client_ids_by_conn.setdefault(conn, set()).add(client_id)

    def _drop_conn(self, conn):
        failed_pending = []
        with self.qmt_lock:
            channels = self.qmt_channel_by_conn.pop(conn, set())
            for channel in channels:
                if self.qmt_rx_by_channel.get(channel) is conn:
                    self.qmt_rx_by_channel.pop(channel, None)
                if self.qmt_tx_by_channel.get(channel) is conn:
                    self.qmt_tx_by_channel.pop(channel, None)
        close_peers = []
        with self.state_lock:
            client_ids = self.client_ids_by_conn.pop(conn, set())
            for client_id in client_ids:
                rx_conn = self.client_by_id.pop(client_id, None)
                tx_conn = self.client_tx_by_id.pop(client_id, None)
                for peer in (rx_conn, tx_conn):
                    if peer is not None and peer is not conn and peer not in close_peers:
                        close_peers.append(peer)
                    self.client_ids_by_conn.pop(peer, None)
            for request_id, pending in list(self.pending.items()):
                pending_conn = pending.get("conn")
                qmt_conn = pending.get("qmt_conn")
                if pending_conn is conn or pending_conn in close_peers:
                    self.pending.pop(request_id, None)
                elif qmt_conn is conn:
                    self.pending.pop(request_id, None)
                    failed_pending.append((
                        request_id,
                        pending,
                        "QMT pipe bridge disconnected for channel=%s" % pending.get("request_channel"),
                    ))
        for peer in close_peers:
            try:
                peer.close()
            except Exception:
                pass
        for request_id, pending, message in failed_pending:
            self._send_error(pending.get("conn"), request_id, message)

    def _start_maintenance(self):
        if self.maintenance_thread is not None and self.maintenance_thread.is_alive():
            return
        self.maintenance_thread = threading.Thread(target=self._maintenance_loop)
        self.maintenance_thread.daemon = True
        self.maintenance_thread.start()

    def _maintenance_loop(self):
        while self.running:
            try:
                expired_count = self._cleanup_expired_pending()
                if expired_count:
                    self._write_status()
            except Exception as e:
                self._log("pipe hub maintenance failed: %s" % e)
            time.sleep(max(0.2, self.maintenance_interval_seconds))

    def _cleanup_expired_pending(self):
        timeout = max(0.0, self.pending_timeout_seconds)
        if timeout <= 0:
            return 0
        now = time.perf_counter()
        expired = []
        with self.state_lock:
            for request_id, pending in list(self.pending.items()):
                started = pending.get("api_received_at") or now
                if now - started < timeout:
                    continue
                self.pending.pop(request_id, None)
                expired.append((request_id, pending))
        for request_id, pending in expired:
            self._send_error(
                pending.get("conn"),
                request_id,
                "QMT pipe bridge response timeout for action=%s channel=%s"
                % (pending.get("action"), pending.get("request_channel")),
            )
        if expired:
            self._log("pipe cleaned expired pending requests count=%s" % len(expired))
        return len(expired)

    def _log(self, msg):
        if self.show:
            print("%s %s" % (self._timestamp_ms(), msg), flush=True)

    def _timestamp_ms(self):
        now = time.time()
        local = time.localtime(now)
        return "%s.%03d" % (time.strftime("%Y-%m-%d %H:%M:%S", local), int((now - int(now)) * 1000))

    def _elapsed_ms(self, start, end=None):
        if end is None:
            end = time.perf_counter()
        return (end - start) * 1000.0

    def _write_status(self):
        try:
            with self.qmt_lock:
                qmt_rx_channels = sorted(set(self.qmt_rx_by_channel.keys()))
                qmt_tx_channels = sorted(set(self.qmt_tx_by_channel.keys()))
                qmt_channels = sorted(set(qmt_rx_channels) | set(qmt_tx_channels))
                qmt_ready_channels = sorted(set(qmt_rx_channels) & set(qmt_tx_channels))
            with self.state_lock:
                pending_ids = list(self.pending.keys())[-20:]
                client_count = len(set(self.client_by_id.values()))
            data = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "pipe_name": self.pipe_name,
                "core_version": CORE_VERSION,
                "hub_status_schema": 2,
                "running": self.running,
                "pid": os.getpid(),
                "qmt_channels": qmt_channels,
                "qmt_rx_channels": qmt_rx_channels,
                "qmt_tx_channels": qmt_tx_channels,
                "qmt_ready_channels": qmt_ready_channels,
                "qmt_connected": bool(qmt_ready_channels or qmt_channels),
                "pending_count": len(self.pending),
                "pending_ids": pending_ids,
                "api_client_count": client_count,
            }
            status_dir = os.path.dirname(self.status_file)
            if status_dir:
                os.makedirs(status_dir, exist_ok=True)
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def run_pipe_hub(pipe_name=None, show=True, default_request_channel="cfquant.normal.request"):
    return CfquantPipeHub(
        pipe_name=pipe_name,
        show=show,
        default_request_channel=default_request_channel,
    ).start()
