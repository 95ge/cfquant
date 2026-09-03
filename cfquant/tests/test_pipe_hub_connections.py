import threading
import time

from cfquant.pipe_hub import CfquantPipeHub


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
