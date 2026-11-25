"""LTtx file destinations are joined as paths without connecting to a server."""
import importlib
import json

import pytest


@pytest.mark.parametrize('module_name', ['cfquant.tx', 'LTtx.tx.tx'])
@pytest.mark.parametrize('operation', ['receive', 'self_update'])
@pytest.mark.parametrize('use_path', [False, True])
def test_file_download_stays_in_destination(tmp_path, monkeypatch, module_name, operation, use_path):
    module = importlib.import_module(module_name)
    directory = tmp_path / '中文 目录'
    directory.mkdir()
    target = directory / 'sample.py'
    target.write_bytes(b'old content')
    messages, destinations = [], []

    class Socket:
        def __init__(self, *args):
            self.parts = iter([b'file exist', b'new content', b''])

        def setsockopt(self, *args):
            pass

        def connect(self, address):
            destinations.append(address)

        def sendall(self, payload):
            messages.append(json.loads(payload))

        def recv(self, length):
            return next(self.parts)

    monkeypatch.setattr(module.socket, 'socket', Socket)
    client = module.txl.__new__(module.txl)
    client.ip, client.port, client.tocken = 'test-only', 1, 'fixture'
    client.sys_print = lambda *args, **kwargs: None
    directory_arg = directory if use_path else str(directory)
    if operation == 'self_update':
        client.current_dir = directory_arg
        code, _ = client._txl__get_lastest_file('sample.py')
    else:
        code, _ = client.recv_file('sample.py', directory_arg)
    assert code == 0
    assert destinations and messages[0]['file_name'] == 'sample.py'
    assert target.read_bytes() == b'new content'
    assert sorted(p.name for p in tmp_path.iterdir()) == [directory.name]
    assert sorted(p.name for p in directory.iterdir()) == ['sample.py']


@pytest.mark.parametrize('module_name', ['cfquant.tx', 'LTtx.tx.tx'])
@pytest.mark.parametrize('use_path', [False, True])
def test_upload_sends_only_basename_for_native_windows_paths(tmp_path, monkeypatch, module_name, use_path):
    module = importlib.import_module(module_name)
    path = tmp_path / '中文 upload.txt'
    path.write_bytes(b'offline upload')
    headers, chunks = [], []

    class Socket:
        def __init__(self, *args):
            pass
        def setsockopt(self, *args):
            pass
        def connect(self, address):
            pass
        def sendall(self, payload):
            headers.append(json.loads(payload))
        def recv(self, length):
            return b'i am ok'
        def send(self, data):
            chunks.append(data)
            return len(data)
        def close(self):
            pass

    monkeypatch.setattr(module.socket, 'socket', Socket)
    client = module.txl.__new__(module.txl)
    client.ip, client.port, client.tocken = 'test-only', 1, 'fixture'
    client.sys_print = lambda *args, **kwargs: None
    client.send_file(path if use_path else str(path), show_on=False)
    assert headers[0]['file_name'] == path.name
    assert b''.join(chunks) == path.read_bytes()
