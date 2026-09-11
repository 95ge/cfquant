import threading
import time

from cfquant.pipe_hub import CfquantPipeHub
from cfquant.pipe_transport import PipeTxClient


class FakePipeConn(object):
    def __init__(self, name):
        self.name = name
        self.closed = False
        self.read_count = 0
        self.writes = []

    def read_frame(self):
        self.read_count += 1
        raise AssertionError("passive response pipe must not be read by hub")

    def write_frame(self, payload):
        self.writes.append(payload)

    def close(self):
        self.closed = True


def qmt_hello(role, bridge_id="bridge-1", instance_id="instance-1", channel="cfquant.normal.request", heartbeat=10):
    return {
        "type": "hello",
        "role": role,
        "bridge_id": bridge_id,
        "endpoint_name": "normal",
        "instance_id": instance_id,
        "process_id": instance_id,
        "request_channel": channel,
        "request_channels": [channel],
        "heartbeat_interval": heartbeat,
    }


def test_api_rx_passive_loop_keeps_connection_without_reading():
    hub = CfquantPipeHub(pipe_name="unit_pipe", show=False)
    conn = FakePipeConn("api-rx")
    hub.running = True
    hub._remember_client(conn, "client-1", receive_conn=True)

    thread = threading.Thread(target=hub._passive_rx_loop, args=(conn, "api_rx"))
    thread.daemon = True
    thread.start()
    time.sleep(0.05)
    with hub.state_lock:
        hub._detach_client_conn_locked(conn, "client-1")
    thread.join(1.0)

    assert not thread.is_alive()
    assert conn.read_count == 0


def test_qmt_rx_passive_loop_keeps_connection_without_reading():
    hub = CfquantPipeHub(pipe_name="unit_pipe", show=False)
    conn = FakePipeConn("qmt-rx")
    hub.running = True
    with hub.qmt_lock:
        hub.qmt_channel_by_conn[conn] = {"cfquant.normal.request"}

    thread = threading.Thread(target=hub._passive_rx_loop, args=(conn, "qmt_rx"))
    thread.daemon = True
    thread.start()
    time.sleep(0.05)
    with hub.qmt_lock:
        hub.qmt_channel_by_conn.pop(conn, None)
    thread.join(1.0)

    assert not thread.is_alive()
    assert conn.read_count == 0


def test_old_client_connection_drop_does_not_remove_new_generation():
    hub = CfquantPipeHub(pipe_name="unit_pipe", show=False)
    old_rx = FakePipeConn("old-rx")
    old_tx = FakePipeConn("old-tx")
    new_rx = FakePipeConn("new-rx")
    new_tx = FakePipeConn("new-tx")

    hub._remember_client(old_rx, "client-1", receive_conn=True)
    hub._remember_client(old_tx, "client-1", receive_conn=False)
    hub._remember_client(new_rx, "client-1", receive_conn=True)

    assert old_rx.closed is True
    hub._drop_conn(old_tx)

    assert new_rx.closed is False
    assert hub._client_rx_conn("client-1") is new_rx
    assert hub.client_tx_by_id.get("client-1") is None

    hub._remember_client(new_tx, "client-1", receive_conn=False)
    hub._drop_conn(new_rx)

    assert new_tx.closed is True
    assert hub._client_rx_conn("client-1") is None
    assert hub.client_tx_by_id.get("client-1") is None


def test_qmt_tx_client_drop_closes_rx_tx_pair():
    client = PipeTxClient(pipe_name="unit_pipe", heartbeat_interval=0)
    rx_conn = FakePipeConn("qmt-rx")
    tx_conn = FakePipeConn("qmt-tx")
    with client.conn_lock:
        client.rx_conn = rx_conn
        client.tx_conn = tx_conn
        client.connection_generation = 1

    client._drop_conn(tx_conn)

    assert rx_conn.closed is True
    assert tx_conn.closed is True
    assert client._get_conn() is None


def test_duplicate_qmt_channel_registration_records_conflict_and_drops_old_pair():
    hub = CfquantPipeHub(pipe_name="unit_pipe", show=False)
    hub._write_status = lambda: None
    old_rx = FakePipeConn("old-rx")
    old_tx = FakePipeConn("old-tx")
    new_rx = FakePipeConn("new-rx")

    hub._handle_hello(old_rx, qmt_hello("qmt_rx", "bridge-old", "instance-old", "shared"), "api")
    hub._handle_hello(old_tx, qmt_hello("qmt_tx", "bridge-old", "instance-old", "shared"), "api")
    hub._handle_hello(new_rx, qmt_hello("qmt_rx", "bridge-new", "instance-new", "shared"), "api")

    assert old_rx.closed is True
    assert old_tx.closed is True
    assert new_rx.closed is False
    assert hub.qmt_rx_by_channel["shared"] is new_rx
    assert "shared" not in hub.qmt_tx_by_channel
    assert hub.qmt_registration_conflicts
    assert hub.qmt_registration_conflicts[-1]["channel"] == "shared"


def test_pipe_hub_status_marks_half_connected_qmt_as_degraded():
    hub = CfquantPipeHub(pipe_name="unit_pipe", show=False)
    hub._write_status = lambda: None
    rx_conn = FakePipeConn("qmt-rx")

    hub._handle_hello(rx_conn, qmt_hello("qmt_rx", channel="half"), "api")
    status = hub.status()

    assert status["qmt_connected"] is False
    assert status["qmt_ready_channels"] == []
    assert status["qmt_degraded_channels"] == ["half"]
    assert status["qmt_channel_states"]["half"]["status"] == "degraded"


def test_pipe_hub_status_marks_ready_qmt_connected():
    hub = CfquantPipeHub(pipe_name="unit_pipe", show=False)
    hub._write_status = lambda: None
    rx_conn = FakePipeConn("qmt-rx")
    tx_conn = FakePipeConn("qmt-tx")

    hub._handle_hello(rx_conn, qmt_hello("qmt_rx", channel="ready"), "api")
    hub._handle_hello(tx_conn, qmt_hello("qmt_tx", channel="ready"), "api")
    status = hub.status()

    assert status["qmt_connected"] is True
    assert status["qmt_ready_channels"] == ["ready"]
    assert status["qmt_channel_states"]["ready"]["status"] == "ready"


def test_pipe_hub_stale_qmt_heartbeat_drops_connection_pair():
    hub = CfquantPipeHub(pipe_name="unit_pipe", show=False)
    hub._write_status = lambda: None
    hub.qmt_heartbeat_timeout_seconds = 0.01
    rx_conn = FakePipeConn("qmt-rx")
    tx_conn = FakePipeConn("qmt-tx")

    hub._handle_hello(rx_conn, qmt_hello("qmt_rx", channel="stale", heartbeat=0.01), "api")
    hub._handle_hello(tx_conn, qmt_hello("qmt_tx", channel="stale", heartbeat=0.01), "api")
    with hub.qmt_lock:
        hub.qmt_conn_meta_by_conn[tx_conn]["_last_seen_mono"] -= 1.0
        hub.qmt_conn_meta_by_conn[tx_conn]["last_seen_at"] -= 1.0

    assert hub._cleanup_stale_qmt() == 1
    assert rx_conn.closed is True
    assert tx_conn.closed is True
    assert hub.status()["qmt_ready_channels"] == []
