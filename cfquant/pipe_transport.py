# -*- coding: utf-8 -*-
import ctypes
import json
import os
import queue
import struct
import threading
import time
from ctypes import wintypes

from .logging_i18n import get_log_enabled, translate_log


DEFAULT_PIPE_NAME = os.environ.get("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub")
PIPE_MESSAGE_PREFIX = "cfpipe:"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
NMPWAIT_WAIT_FOREVER = 0xFFFFFFFF

ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_BUSY = 231
ERROR_NO_DATA = 232
ERROR_PIPE_CONNECTED = 535

DEFAULT_BUFFER_SIZE = 65536
DEFAULT_MAX_FRAME_SIZE = 64 * 1024 * 1024


def is_windows():
    return os.name == "nt"


def normalize_pipe_name(pipe_name=None):
    pipe_name = str(pipe_name or DEFAULT_PIPE_NAME)
    if pipe_name.startswith("\\\\.\\pipe\\"):
        return pipe_name
    name = pipe_name.strip("\\/")
    return r"\\.\pipe\%s" % name


def dumps_pipe_message(payload):
    data = dict(payload)
    data.setdefault("protocol", "cfquant_pipe")
    data.setdefault("ts", int(time.time() * 1000))
    return PIPE_MESSAGE_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def loads_pipe_message(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str) or not raw.startswith(PIPE_MESSAGE_PREFIX):
        return None
    try:
        data = json.loads(raw[len(PIPE_MESSAGE_PREFIX):])
    except Exception:
        return None
    if data.get("protocol") != "cfquant_pipe":
        return None
    return data


class _Kernel32(object):
    def __init__(self):
        if not is_windows():
            raise OSError("named pipe transport requires Windows")
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self.INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        self.dll.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.dll.CreateFileW.restype = wintypes.HANDLE

        self.dll.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        self.dll.CreateNamedPipeW.restype = wintypes.HANDLE

        self.dll.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self.dll.ConnectNamedPipe.restype = wintypes.BOOL

        self.dll.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        self.dll.DisconnectNamedPipe.restype = wintypes.BOOL

        self.dll.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self.dll.ReadFile.restype = wintypes.BOOL

        self.dll.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self.dll.WriteFile.restype = wintypes.BOOL

        self.dll.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self.dll.FlushFileBuffers.restype = wintypes.BOOL

        self.dll.CloseHandle.argtypes = [wintypes.HANDLE]
        self.dll.CloseHandle.restype = wintypes.BOOL

        self.dll.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        self.dll.WaitNamedPipeW.restype = wintypes.BOOL

        self.cancel_io_ex = getattr(self.dll, "CancelIoEx", None)
        if self.cancel_io_ex is not None:
            self.cancel_io_ex.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
            self.cancel_io_ex.restype = wintypes.BOOL

    def last_error(self):
        return ctypes.get_last_error()

    def raise_last_error(self, message):
        error = self.last_error()
        raise OSError(error, "%s failed with winerror=%s" % (message, error))

    def invalid_handle(self, handle):
        return handle in (None, 0, self.INVALID_HANDLE_VALUE)


_kernel32 = None
_kernel32_lock = threading.Lock()


def kernel32():
    global _kernel32
    with _kernel32_lock:
        if _kernel32 is None:
            _kernel32 = _Kernel32()
        return _kernel32


class NamedPipeConnection(object):
    def __init__(self, handle, name="", owner_server_side=False, max_frame_size=DEFAULT_MAX_FRAME_SIZE):
        self.handle = handle
        self.name = name
        self.owner_server_side = bool(owner_server_side)
        self.max_frame_size = int(max_frame_size)
        self.write_lock = threading.RLock()
        self.closed = False

    def read_frame(self):
        header = self._read_exact(8)
        if header is None:
            return None
        size = struct.unpack("!Q", header)[0]
        if size > self.max_frame_size:
            raise ValueError("named pipe frame too large: %s > %s" % (size, self.max_frame_size))
        if size == 0:
            return ""
        data = self._read_exact(size)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    def write_frame(self, payload):
        if isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = bytes(payload)
        frame = struct.pack("!Q", len(data)) + data
        self._write_all(frame)

    def close(self):
        if self.closed:
            return
        self.closed = True
        k32 = kernel32()
        try:
            if k32.cancel_io_ex is not None:
                try:
                    k32.cancel_io_ex(self.handle, None)
                except Exception:
                    pass
            if self.owner_server_side:
                try:
                    k32.dll.DisconnectNamedPipe(self.handle)
                except Exception:
                    pass
        finally:
            try:
                k32.dll.CloseHandle(self.handle)
            except Exception:
                pass

    def _read_exact(self, size):
        chunks = []
        remaining = int(size)
        k32 = kernel32()
        while remaining > 0:
            chunk_size = min(remaining, DEFAULT_BUFFER_SIZE)
            buf = ctypes.create_string_buffer(chunk_size)
            read = wintypes.DWORD(0)
            ok = k32.dll.ReadFile(self.handle, buf, chunk_size, ctypes.byref(read), None)
            if not ok:
                error = k32.last_error()
                if error in (ERROR_BROKEN_PIPE, ERROR_NO_DATA):
                    return None
                raise OSError(error, "ReadFile failed with winerror=%s" % error)
            if read.value == 0:
                return None
            chunks.append(buf.raw[:read.value])
            remaining -= read.value
        return b"".join(chunks)

    def _write_all(self, data):
        offset = 0
        total = len(data)
        k32 = kernel32()
        with self.write_lock:
            while offset < total:
                chunk = data[offset:offset + DEFAULT_BUFFER_SIZE]
                buf = ctypes.create_string_buffer(chunk)
                written = wintypes.DWORD(0)
                ok = k32.dll.WriteFile(self.handle, buf, len(chunk), ctypes.byref(written), None)
                if not ok:
                    error = k32.last_error()
                    raise OSError(error, "WriteFile failed with winerror=%s" % error)
                if written.value <= 0:
                    raise OSError("WriteFile wrote zero bytes")
                offset += written.value


def connect_pipe(pipe_name=None, timeout_ms=3000):
    pipe_name = normalize_pipe_name(pipe_name)
    k32 = kernel32()
    deadline = time.time() + max(float(timeout_ms), 1.0) / 1000.0
    last_error = None
    while True:
        handle = k32.dll.CreateFileW(
            pipe_name,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if not k32.invalid_handle(handle):
            return NamedPipeConnection(handle, pipe_name, owner_server_side=False)
        last_error = k32.last_error()
        if last_error == ERROR_PIPE_BUSY:
            wait_ms = min(250, max(1, int((deadline - time.time()) * 1000)))
            k32.dll.WaitNamedPipeW(pipe_name, wait_ms)
        elif last_error in (ERROR_FILE_NOT_FOUND, ERROR_ACCESS_DENIED):
            time.sleep(0.05)
        else:
            time.sleep(0.05)
        if time.time() >= deadline:
            raise OSError(last_error or 0, "connect named pipe timeout pipe=%s winerror=%s" % (pipe_name, last_error))


def create_pipe_instance(pipe_name=None, in_buffer_size=DEFAULT_BUFFER_SIZE, out_buffer_size=DEFAULT_BUFFER_SIZE):
    pipe_name = normalize_pipe_name(pipe_name)
    k32 = kernel32()
    handle = k32.dll.CreateNamedPipeW(
        pipe_name,
        PIPE_ACCESS_DUPLEX,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
        PIPE_UNLIMITED_INSTANCES,
        int(out_buffer_size),
        int(in_buffer_size),
        0,
        None,
    )
    if k32.invalid_handle(handle):
        k32.raise_last_error("CreateNamedPipeW")
    return NamedPipeConnection(handle, pipe_name, owner_server_side=True)


def wait_for_pipe_client(connection):
    k32 = kernel32()
    ok = k32.dll.ConnectNamedPipe(connection.handle, None)
    if ok:
        return True
    error = k32.last_error()
    if error == ERROR_PIPE_CONNECTED:
        return True
    raise OSError(error, "ConnectNamedPipe failed with winerror=%s" % error)


class PipeTxClient(object):
    """
    QMT-side tx-like adapter over a named pipe hub.

    It intentionally exposes start_tx/start_txg/push/close so bridge classes can
    reuse the existing LTtx-oriented dispatch code without changing behavior.
    """

    def __init__(
        self,
        pipe_name=None,
        request_channel="cfquant.request",
        request_channels=None,
        bridge_id="default",
        endpoint_name="qmt",
        show=True,
        connect_timeout_ms=3000,
        reconnect_interval=1.0,
    ):
        self.pipe_name = normalize_pipe_name(pipe_name)
        self.request_channel = request_channel
        self.request_channels = self._normalize_channels(request_channels or [request_channel])
        self.bridge_id = bridge_id or "default"
        self.endpoint_name = endpoint_name or "qmt"
        self.show = show
        self.connect_timeout_ms = int(connect_timeout_ms)
        self.reconnect_interval = float(reconnect_interval)
        self.Q = queue.Queue(maxsize=10000)
        self.running = False
        self.rx_conn = None
        self.tx_conn = None
        self.conn_lock = threading.RLock()
        self.thread = None

    def start(self):
        if self.running:
            return self
        self.running = True
        self.thread = threading.Thread(target=self._connect_loop)
        self.thread.daemon = True
        self.thread.start()
        return self

    def start_tx(self):
        return self.start()

    def start_txg(self, request_channel=None):
        if request_channel:
            self.request_channel = request_channel
        return {"code": 0, "msg": "pipe request channel registered"}

    def push(self, key, payload, channel):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        envelope = dumps_pipe_message({
            "type": "publish",
            "role": "qmt_tx",
            "bridge_id": self.bridge_id,
            "request_channel": self.request_channel,
            "request_channels": self.request_channels,
            "endpoint_name": self.endpoint_name,
            "key": key,
            "channel": channel,
            "payload": payload,
        })
        conn = self._get_tx_conn()
        if conn is None:
            return {"code": -1, "msg": "pipe not connected"}
        try:
            conn.write_frame(envelope)
            return {"code": 0, "msg": "ok"}
        except Exception as e:
            self._log("pipe push failed: %s" % e)
            self._drop_conn(conn)
            return {"code": -1, "msg": str(e)}

    def close(self):
        self.running = False
        try:
            self.Q.put_nowait(None)
        except Exception:
            pass
        self._drop_conns(self._get_conns())

    def _connect_loop(self):
        while self.running:
            rx_conn = None
            tx_conn = None
            try:
                rx_conn = connect_pipe(self.pipe_name, timeout_ms=self.connect_timeout_ms)
                rx_conn.write_frame(dumps_pipe_message({
                    "type": "hello",
                    "role": "qmt_rx",
                    "bridge_id": self.bridge_id,
                    "request_channel": self.request_channel,
                    "request_channels": self.request_channels,
                    "endpoint_name": self.endpoint_name,
                }))
                tx_conn = connect_pipe(self.pipe_name, timeout_ms=self.connect_timeout_ms)
                tx_conn.write_frame(dumps_pipe_message({
                    "type": "hello",
                    "role": "qmt_tx",
                    "bridge_id": self.bridge_id,
                    "request_channel": self.request_channel,
                    "request_channels": self.request_channels,
                    "endpoint_name": self.endpoint_name,
                }))
                with self.conn_lock:
                    self.rx_conn = rx_conn
                    self.tx_conn = tx_conn
                self._log(
                    "pipe connected pipe=%s request_channel=%s bridge_id=%s"
                    % (self.pipe_name, self.request_channel, self.bridge_id)
                )
                self._read_loop(rx_conn)
            except Exception as e:
                if self.running:
                    self._log("pipe connect/read failed: %s" % e)
            finally:
                self._drop_conns((rx_conn, tx_conn))
            if self.running:
                time.sleep(self.reconnect_interval)

    def _read_loop(self, conn):
        while self.running and self._get_rx_conn() is conn:
            raw = conn.read_frame()
            if raw is None:
                break
            envelope = loads_pipe_message(raw)
            if envelope:
                payload = envelope.get("payload")
                if payload:
                    self.Q.put(payload)
                continue
            self.Q.put(raw)

    def _get_rx_conn(self):
        with self.conn_lock:
            return self.rx_conn

    def _get_tx_conn(self):
        with self.conn_lock:
            return self.tx_conn

    def _get_conn(self):
        return self._get_rx_conn()

    def _get_conns(self):
        with self.conn_lock:
            return self.rx_conn, self.tx_conn

    def _drop_conn(self, conn):
        self._drop_conns((conn,))

    def _drop_conns(self, conns):
        with self.conn_lock:
            for conn in conns:
                if conn is None:
                    continue
                if self.rx_conn is conn:
                    self.rx_conn = None
                if self.tx_conn is conn:
                    self.tx_conn = None
        for conn in conns:
            if conn is None:
                continue
            try:
                conn.close()
            except Exception:
                pass

    def _log(self, msg):
        if self.show and get_log_enabled():
            print("cfquant pipe tx %s" % translate_log(msg))

    def _normalize_channels(self, channels):
        result = []
        for channel in channels or []:
            channel = str(channel or "").strip()
            if channel and channel not in result:
                result.append(channel)
        return result or [self.request_channel]
