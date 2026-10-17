"""Shutdown regressions using fake sockets and isolated Python processes."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from cfquant.tx import txl, _ReceiveQueue


@pytest.fixture
def tx(tmp_path, monkeypatch):
    monkeypatch.setenv('CFQUANT_TX_LOG_DIR', str(tmp_path))
    monkeypatch.setattr(txl, 'auto_import', lambda *args: json)
    monkeypatch.setattr(txl, 'get_local_ip', lambda self: '127.0.0.1')
    client = txl('127.0.0.1', 1, 'test-only', show=False)
    yield client
    client.close()


class Socket:
    def __init__(self):
        self.closed = threading.Event()
        self.receiving = threading.Event()
        self.sent = []
        self.timeouts = []

    def shutdown(self, how):
        self.closed.set()

    def close(self):
        self.closed.set()

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def setsockopt(self, *args):
        pass

    def connect(self, address):
        pass

    def sendall(self, data):
        if self.closed.is_set():
            raise OSError('closed')
        self.sent.append(data)

    def recv(self, *args):
        self.receiving.set()
        assert self.closed.wait(3), 'test socket was not shut down'
        return b''


class ObservedQueue(queue.Queue):
    def __init__(self):
        super().__init__()
        self.waiting = threading.Event()

    def get(self, *args, **kwargs):
        self.waiting.set()
        return super().get(*args, **kwargs)


def test_close_wakes_both_senders_receivers_and_flushes_log(tx, tmp_path):
    primary, plus, subscriber = Socket(), Socket(), Socket()
    tx._txl__tx, tx._txl__tx_plus = primary, plus
    tx.txg_dict['test'] = {'con': subscriber, 'txg_running': True}
    tx.tx_que, tx.tx_que_plus = ObservedQueue(), ObservedQueue()
    start = tx._txl__start_thread
    workers = [start(tx.main_tx_que, ()), start(tx.main_tx_que_plus, ()),
               start(tx.recv_msg_broadcast, ('test', subscriber, ''))]
    assert tx.tx_que.waiting.wait(2) and tx.tx_que_plus.waiting.wait(2)
    assert subscriber.receiving.wait(2)
    tx.save_log('final diagnostic before close')
    began = time.monotonic()
    tx.close()
    assert time.monotonic() - began < .8  # No fixed one-second sleep.
    assert all(not worker.is_alive() for worker in workers)
    assert not tx._threads
    assert tx.Q.get(timeout=.1) is None
    assert all(sock.closed.is_set() for sock in (primary, plus, subscriber))
    assert not primary.sent and not plus.sent  # Stop markers never reach wire.
    assert 'final diagnostic before close' in next(tmp_path.glob('*.log')).read_text(encoding='utf-8')
    tx.close()
    assert tx.start_tx()['code'] == -1
    assert tx.start_plus()['code'] == -1


@pytest.mark.parametrize('plus', [False, True])
def test_closing_socket_during_send_cannot_restart_or_resend(tx, plus, monkeypatch):
    entered = threading.Event()
    sock = Socket()

    def send(data):
        entered.set()
        assert sock.closed.wait(3)
        raise OSError('shutdown interrupted send')

    sock.sendall = send
    setattr(tx, '_txl__tx_plus' if plus else '_txl__tx', sock)
    outgoing = tx.tx_que_plus if plus else tx.tx_que
    worker = tx._txl__start_thread(tx.main_tx_que_plus if plus else tx.main_tx_que, ())
    outgoing.put('order' if plus else b'order')
    assert entered.wait(2)
    monkeypatch.setattr(tx, 'start_tx', lambda: pytest.fail('reconnected after close'))
    monkeypatch.setattr(tx, 'start_plus', lambda: pytest.fail('reconnected after close'))
    tx.close()
    assert not worker.is_alive()


@pytest.mark.parametrize('plus', [False, True])
def test_close_interrupts_connection_handshake(tx, monkeypatch, plus):
    sock = Socket()
    monkeypatch.setattr('cfquant.tx.socket.socket', lambda *args: sock)
    caller = threading.Thread(target=tx.start_plus if plus else tx.start_tx)
    caller.start()
    try:
        assert sock.receiving.wait(2)
        tx.close()
        caller.join(1)
        assert not caller.is_alive()
        assert sock.closed.is_set()
        assert 2.0 in sock.timeouts
        assert not tx._connecting_sockets
    finally:
        sock.closed.set()
        caller.join(2)


def test_close_inside_worker_does_not_join_itself(tx):
    done = threading.Event()
    worker = tx._txl__start_thread(lambda: (tx.close(), done.set()), ())
    assert done.wait(2)
    worker.join(1)
    assert not worker.is_alive()


def test_heartbeat_sleep_is_woken_by_close(tx):
    tx._txl__tx = Socket()
    tx.timeout = 60
    sent = threading.Event()
    tx.push = lambda *args: sent.set()
    worker = tx._txl__start_thread(tx.start_tx_hearbeat, ())
    assert sent.wait(1)
    tx.close()
    assert not worker.is_alive()


def test_heartbeat_shutdown_race_does_not_report_a_spurious_thread_error(tx, monkeypatch):
    errors = []
    monkeypatch.setattr(threading, 'excepthook', lambda error: errors.append(error))
    tx._txl__tx = Socket()
    def push(*args):
        tx.close()
        raise ConnectionAbortedError('closed during heartbeat')
    tx.push = push
    worker = tx._txl__start_thread(tx.start_tx_hearbeat, ())
    worker.join(2)
    assert not worker.is_alive()
    assert not errors


def test_receive_queue_keeps_data_and_timeout_contract():
    q = _ReceiveQueue(queue.SimpleQueue)
    with pytest.raises(queue.Empty):
        q.get_nowait()
    with pytest.raises(queue.Empty):
        q.get(timeout=.01)
    q.put('quote')
    assert q.get(timeout=30) == 'quote'
    with pytest.raises(ValueError):
        q.get(timeout=-1)


@pytest.mark.parametrize('plus', [False, True])
def test_sender_still_delivers_protocol_payload_after_handshake(tx, monkeypatch, plus):
    sock = Socket()
    sock.recv = lambda *args: b'{"code":0,"id_code":42,"server_version":3}'
    delivered = threading.Event()
    original_send = sock.sendall

    def send(data):
        original_send(data)
        if b'probe|payload' in data:
            delivered.set()

    sock.sendall = send
    monkeypatch.setattr('cfquant.tx.socket.socket', lambda *args: sock)
    (tx.start_plus if plus else tx.start_tx)()
    (tx.push_plus if plus else tx.push)('probe', 'payload', 'channel')
    assert delivered.wait(2)
    payload = next(data for data in sock.sent if b'probe|payload' in data)
    if plus:
        assert payload == b'probe|payload:who:channel'
    else:
        assert json.loads(payload) == {'func': 'push', 'value': 'probe|payload', 'who': 'channel'}
    tx.close()
    assert not tx._threads


def test_zmq_idle_receiver_and_publisher_close(tx):
    pytest.importorskip('zmq')
    tx.start_MQ(pub_port=1)
    tx.start_MQ_broadcast('offline-test', sub_port=1)
    tx.close()
    assert not tx._threads
    assert tx._txl__ZMQ is None
    assert tx._txl__ZMQ_broadcast is None


def test_cleanup_after_market_run_does_not_reconnect(monkeypatch):
    from cfquant import xtdata
    removed = []
    client = SimpleNamespace(_closed=True, remove_callback=lambda *args: removed.append(args),
                             request=lambda *args: pytest.fail('reconnected during cleanup'))
    monkeypatch.setattr(xtdata, 'get_client', lambda: client)
    callback = lambda data: None
    monkeypatch.setattr(xtdata, '_subscription_callbacks', {42: ('quote:42', callback)})
    assert xtdata.unsubscribe_quote(42) is False
    assert not xtdata._subscription_callbacks
    assert removed == [('quote:42', callback)]


def test_trader_cleanup_does_not_reconnect_closed_rpc(monkeypatch):
    from cfquant.xttrader import XtQuantTrader
    trader = XtQuantTrader()
    closed = []
    trader._clients[trader.bridge_id] = SimpleNamespace(_closed=True, close=lambda: closed.append(True))
    trader._subscribed_accounts['test'] = {'account_id': 'TEST', 'account_type': 'STOCK'}
    monkeypatch.setattr(trader, '_trade_request', lambda *args, **kwargs: pytest.fail('reconnected'))
    trader.stop()
    assert closed == [True]


@pytest.mark.parametrize('stage', ['start_tx', 'start_txg'])
def test_interrupted_rpc_start_closes_partial_transport(stage):
    from cfquant.client import LTtxRpcClient
    closed = []
    def interrupt(*args):
        raise KeyboardInterrupt()
    tx = SimpleNamespace(Q=queue.Queue(), start_tx=lambda: None, start_txg=lambda *args: None,
                         close=lambda: closed.append(True))
    setattr(tx, stage, interrupt)
    client = LTtxRpcClient()
    client._load_txl = lambda: lambda *args: tx
    with pytest.raises(KeyboardInterrupt):
        client.start()
    assert closed == [True]
    assert client._closed and client._tx is None


def test_sdk_close_cancels_startup_without_waiting_for_start_lock():
    from cfquant.client import LTtxRpcClient, CfquantError
    entered, cancelled = threading.Event(), threading.Event()

    class ConnectingTx:
        Q = queue.Queue()
        run_on = True
        def start_tx(self):
            entered.set()
            assert cancelled.wait(3), 'close was blocked by the startup lock'
            return {'code': -1, 'msg': 'closed'}
        def close(self):
            self.run_on = False
            cancelled.set()

    client = LTtxRpcClient()
    client._load_txl = lambda: lambda *args: ConnectingTx()
    errors = []
    def start():
        try:
            client.start()
        except CfquantError as error:
            errors.append(str(error))
    worker = threading.Thread(target=start)
    worker.start()
    try:
        assert entered.wait(2)
        client.close()
        worker.join(1)
        assert not worker.is_alive()
        assert errors == ['closed']
        assert client._closed
    finally:
        cancelled.set()
        worker.join(2)


CHILD = r'''
import _thread,json,queue,sys,threading,time
from cfquant.tx import txl
from cfquant import xtdata
from cfquant.client import LTtxRpcClient
from cfquant.pipe_client import PipeRpcClient
from cfquant.xttrader import XtQuantTrader
txl.auto_import=lambda *args: json
txl.get_local_ip=lambda self: '127.0.0.1'
tx=txl('127.0.0.1',1,'test-only',show=False)
tx.save_log('EXIT_LOG_MARKER')
case=sys.argv[1]
if case == 'normal_return':
    print('MAIN_RETURN',flush=True)
else:
    timer=threading.Timer(.15,_thread.interrupt_main)
    timer.daemon=True
    timer.start()
    try:
        if case == 'public_queue':
            tx.Q.get()
        elif case in ('rpc','pipe_rpc'):
            class FakeTx:
                Q=tx.Q
                def start_tx(self): pass
                def start_txg(self,*args): pass
                def push(self,*args): pass
                def close(self): tx.close()
            class FakePipe:
                def write_frame(self,*args): pass
                def read_frame(self): return tx.Q.get()
                def close(self): tx.Q.put(None)
            if case == 'rpc':
                client=LTtxRpcClient(timeout=30)
                client._load_txl=lambda: lambda *args: FakeTx()
            else:
                import cfquant.pipe_client as pc
                pc.connect_pipe=lambda *args,**kwargs: FakePipe()
                client=PipeRpcClient(timeout=30)
            client.request('test.readonly')
        elif case == 'market_run':
            client=type('Client',(),{'start':lambda self:None,'close':lambda self:tx.close()})()
            xtdata.get_client=lambda:client
            xtdata.run()
        elif case == 'trader_run':
            trader=XtQuantTrader()
            trader.start=lambda:setattr(trader,'connected',True)
            def stop():
                trader.connected=False
                tx.close()
            trader.stop=stop
            trader.run_forever()
    except KeyboardInterrupt:
        if case in ('rpc','pipe_rpc'):
            assert client._closed and not client._pending
        if case in ('market_run','trader_run'):
            assert tx._stop_event.is_set()
        print('INTERRUPTED',flush=True)
    finally:
        timer.cancel()
        if case != 'public_queue':
            tx.close()
'''


@pytest.mark.parametrize('case', ['normal_return', 'public_queue', 'rpc', 'pipe_rpc', 'market_run', 'trader_run'])
def test_python_process_exits_without_user_thread_cleanup(case, tmp_path):
    env = dict(os.environ, CFQUANT_TX_LOG_DIR=str(tmp_path), PYTHONIOENCODING='utf-8')
    process = subprocess.Popen(
        [sys.executable, '-u', '-c', CHILD, case], cwd=Path(__file__).resolve().parents[2],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    try:
        output, error = process.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        output, error = process.communicate(timeout=2)
        pytest.fail('child did not exit: %s\n%s\n%s' % (case, output, error))
    assert process.returncode == 0, output + error
    assert ('MAIN_RETURN' if case == 'normal_return' else 'INTERRUPTED') in output
    assert not error
    assert 'EXIT_LOG_MARKER' in next(tmp_path.glob('*.log')).read_text(encoding='utf-8')
