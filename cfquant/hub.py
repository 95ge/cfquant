# -*- coding: utf-8 -*-
import json
import os
import socket
import struct
import threading
import time

from .protocol import loads_message


class CfquantHub(object):
    """
    外部 Socket Hub。

    - QMT 端作为 client 连接进来，首帧发送 role:qmt
    - 外部 API client 直接发送 cfquant request
    - Hub 将 request 转发给 QMT，并按 request id 把 response 转回对应 API client
    """

    def __init__(self, host="127.0.0.1", port=58668, show=True):
        self.host = host
        self.port = int(port)
        self.show = show
        self.running = False
        self.server = None
        self.qmt_sock = None
        self.qmt_lock = threading.RLock()
        self.send_locks = {}
        self.send_locks_lock = threading.RLock()
        self.pending = {}
        self.client_by_id = {}
        self.state_lock = threading.RLock()
        self.status_file = os.path.abspath("cfquant_hub_status.json")

    def start(self):
        if self.running:
            return self
        self.running = True
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(100)
        self._log("cfquant Hub已启动:%s:%s" % (self.host, self.port))
        self._write_status()
        try:
            while self.running:
                client, address = self.server.accept()
                self._log("Hub客户端已连接:%s" % (address,))
                threading.Thread(target=self._client_loop, args=(client, address), daemon=True).start()
        finally:
            self.close()
        return self

    def close(self):
        self.running = False
        try:
            self.server.close()
        except Exception:
            pass
        with self.qmt_lock:
            qmt_sock = self.qmt_sock
            self.qmt_sock = None
        self._close_socket(qmt_sock)

    def _client_loop(self, sock, address):
        role = "api"
        try:
            while self.running:
                raw = self._recv_frame(sock)
                if raw is None:
                    break
                if raw == "role:qmt":
                    role = "qmt"
                    with self.qmt_lock:
                        old = self.qmt_sock
                        self.qmt_sock = sock
                    if old is not None and old is not sock:
                        self._close_socket(old)
                    self._log("QMT桥接端已注册:%s" % (address,))
                    self._write_status()
                    continue
                if role == "qmt":
                    self._handle_qmt_message(raw)
                else:
                    self._handle_api_message(sock, raw)
        except Exception as e:
            self._log("Hub客户端循环异常 address=%s role=%s error=%s" % (address, role, e))
        finally:
            if role == "qmt":
                with self.qmt_lock:
                    if self.qmt_sock is sock:
                        self.qmt_sock = None
                self._log("QMT桥接端已断开:%s" % (address,))
                self._write_status()
            else:
                self._drop_api_client(sock)
                self._log("API客户端已断开:%s" % (address,))
                self._write_status()
            self._close_socket(sock)

    def _handle_api_message(self, sock, raw):
        api_received_at = time.perf_counter()
        msg = loads_message(raw)
        if not msg:
            return
        if msg.get("type") != "request":
            return
        request_id = msg.get("id")
        client_id = msg.get("client_id")
        with self.state_lock:
            if request_id:
                self.pending[request_id] = {
                    "sock": sock,
                    "action": msg.get("action"),
                    "api_received_at": api_received_at,
                    "forward_done_at": None,
                }
            if client_id:
                self.client_by_id[client_id] = sock
        qmt_sock = self._get_qmt_sock()
        if qmt_sock is None:
            with self.state_lock:
                self.pending.pop(request_id, None)
            self._send_error(sock, request_id, "QMT桥接端未连接")
            return
        forward_start = time.perf_counter()
        self._send_frame(qmt_sock, raw)
        forward_done = time.perf_counter()
        with self.state_lock:
            pending = self.pending.get(request_id)
            if pending:
                pending["forward_done_at"] = forward_done
        self._log(
            "Hub已转发请求 action=%s id=%s api_to_forward_ms=%.2f send_ms=%.2f raw_len=%s"
            % (
                msg.get("action"),
                request_id,
                self._elapsed_ms(api_received_at, forward_done),
                self._elapsed_ms(forward_start, forward_done),
                len(raw),
            )
        )
        self._write_status()

    def _handle_qmt_message(self, raw):
        qmt_received_at = time.perf_counter()
        msg = loads_message(raw)
        if not msg:
            return
        msg_type = msg.get("type")
        target = None
        if msg_type == "response":
            request_id = msg.get("id")
            pending = None
            with self.state_lock:
                pending = self.pending.pop(request_id, None)
            if isinstance(pending, dict):
                target = pending.get("sock")
                api_received_at = pending.get("api_received_at") or qmt_received_at
                forward_done_at = pending.get("forward_done_at") or api_received_at
                self._log(
                    "Hub收到QMT响应 action=%s id=%s target=%s qmt_roundtrip_ms=%.2f total_to_hub_ms=%.2f response_len=%s"
                    % (
                        pending.get("action"),
                        request_id,
                        bool(target),
                        self._elapsed_ms(forward_done_at, qmt_received_at),
                        self._elapsed_ms(api_received_at, qmt_received_at),
                        len(raw),
                    )
                )
            else:
                target = pending
                self._log("Hub收到QMT响应 id=%s target=%s response_len=%s" % (request_id, bool(target), len(raw)))
            self._write_status()
        elif msg_type == "event":
            client_id = msg.get("client_id")
            with self.state_lock:
                target = self.client_by_id.get(client_id)
            self._log("Hub收到QMT事件 event=%s client_id=%s target=%s" % (msg.get("event"), client_id, bool(target)))
        if target is not None:
            self._send_frame(target, raw)

    def _send_error(self, sock, request_id, message):
        from .protocol import pack_response

        self._send_frame(sock, pack_response(request_id, ok=False, error={"type": "ConnectionError", "message": message}))

    def _get_qmt_sock(self):
        with self.qmt_lock:
            return self.qmt_sock

    def _drop_api_client(self, sock):
        with self.state_lock:
            for key, value in list(self.pending.items()):
                pending_sock = value.get("sock") if isinstance(value, dict) else value
                if pending_sock is sock:
                    self.pending.pop(key, None)
            for key, value in list(self.client_by_id.items()):
                if value is sock:
                    self.client_by_id.pop(key, None)

    def _send_frame(self, sock, payload):
        if isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = payload
        with self._get_send_lock(sock):
            sock.sendall(struct.pack("!Q", len(data)) + data)

    def _recv_frame(self, sock):
        header = self._recv_exact(sock, 8)
        if not header:
            return None
        size = struct.unpack("!Q", header)[0]
        if size <= 0:
            return ""
        data = self._recv_exact(sock, size)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    def _recv_exact(self, sock, size):
        chunks = []
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _get_send_lock(self, sock):
        with self.send_locks_lock:
            lock = self.send_locks.get(sock)
            if lock is None:
                lock = threading.RLock()
                self.send_locks[sock] = lock
            return lock

    def _close_socket(self, sock):
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        with self.send_locks_lock:
            self.send_locks.pop(sock, None)

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
                qmt_connected = self.qmt_sock is not None
            with self.state_lock:
                pending_ids = list(self.pending.keys())[-20:]
                client_count = len(set(self.client_by_id.values()))
            data = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "host": self.host,
                "port": self.port,
                "qmt_connected": qmt_connected,
                "pending_count": len(pending_ids),
                "pending_ids": pending_ids,
                "api_client_count": client_count,
            }
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def run_hub(host="127.0.0.1", port=58668, show=True):
    return CfquantHub(host=host, port=port, show=show).start()
