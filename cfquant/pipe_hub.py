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
        self.qmt_conn_meta_by_conn = {}
        self.qmt_registration_conflicts = []
        self.qmt_lock = threading.RLock()
        self.pending = {}
        self.client_by_id = {}
        self.client_tx_by_id = {}
        self.client_ids_by_conn = {}
        self.client_conn_meta_by_conn = {}
        self.client_generation_by_id = {}
        self.state_lock = threading.RLock()
        self.status_file = os.path.abspath(
            os.environ.get("CFQUANT_PIPE_HUB_STATUS_FILE") or default_status_file("cfquant_pipe_hub_status.json")
        )
        self.pending_timeout_seconds = float(os.environ.get("CFQUANT_PIPE_HUB_PENDING_TIMEOUT", "60"))
        self.qmt_heartbeat_timeout_seconds = float(os.environ.get("CFQUANT_PIPE_HUB_QMT_HEARTBEAT_TIMEOUT", "30"))
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
            self.qmt_conn_meta_by_conn.clear()
        with self.state_lock:
            conns.extend(self.client_ids_by_conn.keys())
            self.pending.clear()
            self.client_by_id.clear()
            self.client_tx_by_id.clear()
            self.client_ids_by_conn.clear()
            self.client_conn_meta_by_conn.clear()
            self.client_generation_by_id.clear()
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
                    elif msg_type == "heartbeat":
                        role = envelope.get("role") or role
                        self._handle_qmt_heartbeat(conn, envelope)
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
                    active = conn in self.qmt_channel_by_conn
            elif role == "api_rx":
                with self.state_lock:
                    active = conn in self.client_ids_by_conn
            else:
                active = False
            if not active:
                break
            time.sleep(0.2)

    def _handle_hello(self, conn, envelope, current_role):
        role = envelope.get("role") or current_role
        if role in ("qmt", "qmt_rx", "qmt_tx"):
            channels = self._envelope_channels(envelope)
            old_conns = []
            with self.qmt_lock:
                meta = self._qmt_conn_meta(envelope, role, channels)
                self.qmt_conn_meta_by_conn[conn] = meta
                target = self.qmt_rx_by_channel if role in ("qmt", "qmt_rx") else self.qmt_tx_by_channel
                for channel in channels:
                    old = target.get(channel)
                    target[channel] = conn
                    self.qmt_channel_by_conn.setdefault(conn, set()).add(channel)
                    if old is not None and old is not conn:
                        old_meta = self.qmt_conn_meta_by_conn.get(old) or {}
                        if not self._same_qmt_instance(old_meta, meta):
                            self._remember_qmt_conflict_locked(channel, role, old_meta, meta)
                        if old not in old_conns:
                            old_conns.append(old)
            for old in old_conns:
                self._drop_conn(old)
            self._log(
                "qmt pipe bridge registered role=%s channels=%s bridge_id=%s endpoint=%s instance=%s pid=%s"
                % (
                    role,
                    ",".join(channels),
                    envelope.get("bridge_id") or "-",
                    envelope.get("endpoint_name") or "-",
                    envelope.get("instance_id") or "-",
                    envelope.get("process_id") or envelope.get("pid") or "-",
                )
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

    def _qmt_conn_meta(self, envelope, role, channels):
        now = time.time()
        try:
            heartbeat_interval = float(envelope.get("heartbeat_interval") or 0)
        except Exception:
            heartbeat_interval = 0.0
        return {
            "role": role,
            "bridge_id": str(envelope.get("bridge_id") or "-"),
            "endpoint_name": str(envelope.get("endpoint_name") or ""),
            "instance_id": str(envelope.get("instance_id") or ""),
            "process_id": str(envelope.get("process_id") or envelope.get("pid") or ""),
            "heartbeat_interval": max(0.0, heartbeat_interval),
            "connected_at": now,
            "last_seen_at": now,
            "_last_seen_mono": time.monotonic(),
            "channels": list(channels or []),
        }

    def _same_qmt_instance(self, left, right):
        left = left or {}
        right = right or {}
        left_instance = str(left.get("instance_id") or "").strip()
        right_instance = str(right.get("instance_id") or "").strip()
        if left_instance and right_instance:
            return left_instance == right_instance
        left_pid = str(left.get("process_id") or "").strip()
        right_pid = str(right.get("process_id") or "").strip()
        if not left_pid or not right_pid or left_pid != right_pid:
            return False
        return (
            str(left.get("bridge_id") or "") == str(right.get("bridge_id") or "")
            and str(left.get("endpoint_name") or "") == str(right.get("endpoint_name") or "")
        )

    def _remember_qmt_conflict_locked(self, channel, role, old_meta, new_meta):
        now = time.time()
        self.qmt_registration_conflicts.append({
            "ts": now,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "channel": channel,
            "role": role,
            "old": self._public_qmt_meta(old_meta),
            "new": self._public_qmt_meta(new_meta),
        })
        self.qmt_registration_conflicts = self.qmt_registration_conflicts[-50:]

    def _touch_qmt_conn(self, conn, envelope=None):
        with self.qmt_lock:
            meta = self.qmt_conn_meta_by_conn.get(conn)
            if not meta:
                return False
            now = time.time()
            meta["last_seen_at"] = now
            meta["_last_seen_mono"] = time.monotonic()
            if envelope:
                if envelope.get("role"):
                    meta["role"] = envelope.get("role")
                if envelope.get("bridge_id"):
                    meta["bridge_id"] = str(envelope.get("bridge_id"))
                if envelope.get("endpoint_name"):
                    meta["endpoint_name"] = str(envelope.get("endpoint_name"))
                if envelope.get("instance_id"):
                    meta["instance_id"] = str(envelope.get("instance_id"))
                if envelope.get("process_id") or envelope.get("pid"):
                    meta["process_id"] = str(envelope.get("process_id") or envelope.get("pid"))
                try:
                    heartbeat_interval = float(envelope.get("heartbeat_interval") or meta.get("heartbeat_interval") or 0)
                    meta["heartbeat_interval"] = max(0.0, heartbeat_interval)
                except Exception:
                    pass
            return True

    def _handle_qmt_heartbeat(self, conn, envelope):
        if self._touch_qmt_conn(conn, envelope):
            self._write_status()

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
        self._touch_qmt_conn(conn, envelope)
        qmt_received_at = time.perf_counter()
        raw = envelope.get("payload")
        msg = loads_message(raw)
        target = None
        status_changed = False
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
            status_changed = pending is not None
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
        if status_changed:
            self._write_status()

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
        close_old = []
        with self.state_lock:
            if receive_conn:
                generation = int(self.client_generation_by_id.get(client_id) or 0) + 1
                self.client_generation_by_id[client_id] = generation
                mapping = self.client_by_id
            else:
                generation = int(self.client_generation_by_id.get(client_id) or 0) or 1
                self.client_generation_by_id[client_id] = generation
                mapping = self.client_tx_by_id
            old = mapping.get(client_id)
            if old is not None and old is not conn:
                self._detach_client_conn_locked(old, client_id)
                close_old.append(old)
            if receive_conn:
                self.client_by_id[client_id] = conn
            else:
                self.client_tx_by_id[client_id] = conn
            self.client_ids_by_conn.setdefault(conn, set()).add(client_id)
            self.client_conn_meta_by_conn.setdefault(conn, {})[client_id] = {
                "receive": bool(receive_conn),
                "generation": generation,
            }
        for old in close_old:
            try:
                old.close()
            except Exception:
                pass

    def _qmt_pair_peers_locked(self, conn, channels, meta):
        role = str((meta or {}).get("role") or "")
        peers = []
        for channel in channels or []:
            candidates = []
            if role in ("", "qmt", "qmt_rx"):
                candidates.append(self.qmt_tx_by_channel.get(channel))
            if role in ("", "qmt", "qmt_tx"):
                candidates.append(self.qmt_rx_by_channel.get(channel))
            for peer in candidates:
                if peer is None or peer is conn or peer in peers:
                    continue
                peer_meta = self.qmt_conn_meta_by_conn.get(peer) or {}
                if self._same_qmt_instance(meta, peer_meta):
                    peers.append(peer)
        return peers

    def _detach_qmt_conn_locked(self, conn):
        meta = self.qmt_conn_meta_by_conn.pop(conn, None) or {}
        channels = set(self.qmt_channel_by_conn.pop(conn, set()))
        for channel in list(channels):
            if self.qmt_rx_by_channel.get(channel) is conn:
                self.qmt_rx_by_channel.pop(channel, None)
            if self.qmt_tx_by_channel.get(channel) is conn:
                self.qmt_tx_by_channel.pop(channel, None)
        return channels, meta

    def _drop_conn(self, conn):
        failed_pending = []
        close_qmt_conns = []
        qmt_failed_conns = []
        with self.qmt_lock:
            channels = set(self.qmt_channel_by_conn.get(conn, set()))
            meta = self.qmt_conn_meta_by_conn.get(conn) or {}
            qmt_conn_registered = bool(channels or conn in self.qmt_conn_meta_by_conn)
            qmt_pair_peers = self._qmt_pair_peers_locked(conn, channels, meta)
            self._detach_qmt_conn_locked(conn)
            if qmt_conn_registered:
                close_qmt_conns.append(conn)
                qmt_failed_conns.append(conn)
            for peer in qmt_pair_peers:
                peer_registered = peer in self.qmt_channel_by_conn or peer in self.qmt_conn_meta_by_conn
                self._detach_qmt_conn_locked(peer)
                if peer_registered:
                    close_qmt_conns.append(peer)
                    qmt_failed_conns.append(peer)
        qmt_failed_set = set(qmt_failed_conns)
        close_peers = []
        with self.state_lock:
            meta_by_client = self.client_conn_meta_by_conn.pop(conn, {})
            client_ids = set(self.client_ids_by_conn.pop(conn, set())) | set(meta_by_client.keys())
            for client_id in client_ids:
                meta = meta_by_client.get(client_id) or {}
                generation = meta.get("generation")
                receive_conn = meta.get("receive")
                rx_conn = self.client_by_id.get(client_id)
                tx_conn = self.client_tx_by_id.get(client_id)
                rx_generation = self._client_conn_generation_locked(rx_conn, client_id)
                tx_generation = self._client_conn_generation_locked(tx_conn, client_id)

                if rx_conn is conn:
                    self.client_by_id.pop(client_id, None)
                if tx_conn is conn:
                    self.client_tx_by_id.pop(client_id, None)

                if receive_conn is True:
                    peer = tx_conn
                    peer_generation = tx_generation
                    peer_mapping = self.client_tx_by_id
                elif receive_conn is False:
                    peer = rx_conn
                    peer_generation = rx_generation
                    peer_mapping = self.client_by_id
                else:
                    peer = None
                    peer_generation = None
                    peer_mapping = None

                if (
                    peer is not None
                    and peer is not conn
                    and generation is not None
                    and peer_generation == generation
                    and peer not in close_peers
                ):
                    close_peers.append(peer)
                    if peer_mapping is not None and peer_mapping.get(client_id) is peer:
                        peer_mapping.pop(client_id, None)
                    self._detach_client_conn_locked(peer, client_id)

                if self.client_by_id.get(client_id) is None and self.client_tx_by_id.get(client_id) is None:
                    self.client_generation_by_id.pop(client_id, None)
            for request_id, pending in list(self.pending.items()):
                pending_conn = pending.get("conn")
                qmt_conn = pending.get("qmt_conn")
                if pending_conn is conn or pending_conn in close_peers:
                    self.pending.pop(request_id, None)
                elif qmt_conn in qmt_failed_set:
                    self.pending.pop(request_id, None)
                    failed_pending.append((
                        request_id,
                        pending,
                        "QMT pipe bridge disconnected for channel=%s" % pending.get("request_channel"),
                    ))
        for qmt_conn in close_qmt_conns:
            try:
                qmt_conn.close()
            except Exception:
                pass
        for peer in close_peers:
            try:
                peer.close()
            except Exception:
                pass
        for request_id, pending, message in failed_pending:
            self._send_error(pending.get("conn"), request_id, message)

    def _detach_client_conn_locked(self, conn, client_id):
        if conn is None:
            return
        client_ids = self.client_ids_by_conn.get(conn)
        if client_ids is not None:
            client_ids.discard(client_id)
            if not client_ids:
                self.client_ids_by_conn.pop(conn, None)
        meta_by_client = self.client_conn_meta_by_conn.get(conn)
        if meta_by_client is not None:
            meta_by_client.pop(client_id, None)
            if not meta_by_client:
                self.client_conn_meta_by_conn.pop(conn, None)

    def _client_conn_generation_locked(self, conn, client_id):
        if conn is None:
            return None
        meta_by_client = self.client_conn_meta_by_conn.get(conn) or {}
        meta = meta_by_client.get(client_id) or {}
        return meta.get("generation")

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
                stale_qmt_count = self._cleanup_stale_qmt()
                if expired_count or stale_qmt_count:
                    self._write_status()
            except Exception as e:
                self._log("pipe hub maintenance failed: %s" % e)
            time.sleep(max(0.2, self.maintenance_interval_seconds))

    def _qmt_heartbeat_deadline_seconds(self, meta):
        try:
            interval = float((meta or {}).get("heartbeat_interval") or 0)
        except Exception:
            interval = 0.0
        if interval <= 0:
            return 0.0
        return max(float(self.qmt_heartbeat_timeout_seconds), interval * 3.0)

    def _qmt_meta_stale(self, meta, now_mono=None):
        deadline = self._qmt_heartbeat_deadline_seconds(meta)
        if deadline <= 0:
            return False
        if now_mono is None:
            now_mono = time.monotonic()
        try:
            last_seen = float((meta or {}).get("_last_seen_mono") or 0)
        except Exception:
            last_seen = 0.0
        return last_seen > 0 and now_mono - last_seen > deadline

    def _cleanup_stale_qmt(self):
        now_mono = time.monotonic()
        stale = []
        with self.qmt_lock:
            for conn, meta in list(self.qmt_conn_meta_by_conn.items()):
                role = str((meta or {}).get("role") or "")
                if role not in ("qmt", "qmt_tx"):
                    continue
                if self._qmt_meta_stale(meta, now_mono):
                    stale.append((conn, dict(meta)))
        for conn, meta in stale:
            self._log(
                "pipe qmt heartbeat expired role=%s channels=%s bridge_id=%s endpoint=%s instance=%s"
                % (
                    meta.get("role") or "-",
                    ",".join(meta.get("channels") or []),
                    meta.get("bridge_id") or "-",
                    meta.get("endpoint_name") or "-",
                    meta.get("instance_id") or "-",
                )
            )
            self._drop_conn(conn)
        return len(stale)

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

    def status(self):
        return self._status_snapshot()

    def _public_qmt_meta(self, meta, now=None, now_mono=None):
        if not meta:
            return None
        if now is None:
            now = time.time()
        if now_mono is None:
            now_mono = time.monotonic()
        try:
            last_seen_at = float(meta.get("last_seen_at") or 0)
        except Exception:
            last_seen_at = 0.0
        try:
            connected_at = float(meta.get("connected_at") or 0)
        except Exception:
            connected_at = 0.0
        try:
            heartbeat_interval = float(meta.get("heartbeat_interval") or 0)
        except Exception:
            heartbeat_interval = 0.0
        deadline = self._qmt_heartbeat_deadline_seconds(meta)
        return {
            "role": meta.get("role") or "",
            "bridge_id": meta.get("bridge_id") or "",
            "endpoint_name": meta.get("endpoint_name") or "",
            "instance_id": meta.get("instance_id") or "",
            "process_id": meta.get("process_id") or "",
            "heartbeat_interval": heartbeat_interval,
            "connected_at": connected_at,
            "last_seen_at": last_seen_at,
            "age_seconds": round(max(0.0, now - last_seen_at), 1) if last_seen_at else None,
            "connected_age_seconds": round(max(0.0, now - connected_at), 1) if connected_at else None,
            "stale_after_seconds": round(deadline, 1) if deadline else 0,
            "stale": self._qmt_meta_stale(meta, now_mono),
            "channels": list(meta.get("channels") or []),
        }

    def _status_snapshot(self):
        now = time.time()
        now_mono = time.monotonic()
        with self.qmt_lock:
            qmt_rx_by_channel = dict(self.qmt_rx_by_channel)
            qmt_tx_by_channel = dict(self.qmt_tx_by_channel)
            qmt_meta_by_conn = {
                conn: dict(meta)
                for conn, meta in self.qmt_conn_meta_by_conn.items()
            }
            qmt_registration_conflicts = list(self.qmt_registration_conflicts)
        qmt_rx_channels = sorted(set(qmt_rx_by_channel.keys()))
        qmt_tx_channels = sorted(set(qmt_tx_by_channel.keys()))
        qmt_channels = sorted(set(qmt_rx_channels) | set(qmt_tx_channels))
        qmt_ready_channels = []
        qmt_degraded_channels = []
        qmt_stale_channels = []
        qmt_channel_states = {}
        for channel in qmt_channels:
            rx_conn = qmt_rx_by_channel.get(channel)
            tx_conn = qmt_tx_by_channel.get(channel)
            rx_meta = qmt_meta_by_conn.get(rx_conn) or {}
            tx_meta = qmt_meta_by_conn.get(tx_conn) or {}
            tx_stale = bool(tx_conn is not None and self._qmt_meta_stale(tx_meta, now_mono))
            ready = bool(rx_conn is not None and tx_conn is not None and not tx_stale)
            if ready:
                status = "ready"
                qmt_ready_channels.append(channel)
            else:
                status = "stale" if tx_stale else "degraded"
                qmt_degraded_channels.append(channel)
                if tx_stale:
                    qmt_stale_channels.append(channel)
            qmt_channel_states[channel] = {
                "status": status,
                "ready": ready,
                "rx_connected": rx_conn is not None,
                "tx_connected": tx_conn is not None,
                "rx": self._public_qmt_meta(rx_meta, now, now_mono),
                "tx": self._public_qmt_meta(tx_meta, now, now_mono),
            }
        with self.state_lock:
            pending_ids = list(self.pending.keys())[-20:]
            pending_count = len(self.pending)
            client_count = len(set(self.client_by_id.values()))
        return {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "pipe_name": self.pipe_name,
            "core_version": CORE_VERSION,
            "hub_status_schema": 3,
            "running": self.running,
            "pid": os.getpid(),
            "qmt_channels": qmt_channels,
            "qmt_rx_channels": qmt_rx_channels,
            "qmt_tx_channels": qmt_tx_channels,
            "qmt_ready_channels": sorted(qmt_ready_channels),
            "qmt_degraded_channels": sorted(qmt_degraded_channels),
            "qmt_stale_channels": sorted(qmt_stale_channels),
            "qmt_channel_states": qmt_channel_states,
            "qmt_registration_conflicts": qmt_registration_conflicts[-50:],
            "qmt_connected": bool(qmt_ready_channels),
            "pending_count": pending_count,
            "pending_ids": pending_ids,
            "api_client_count": client_count,
        }

    def _write_status(self):
        try:
            data = self._status_snapshot()
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
