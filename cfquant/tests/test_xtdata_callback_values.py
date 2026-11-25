"""Download callback boundaries, with no QMT or network connection."""
from collections import defaultdict

import pytest

from cfquant import xtdata


@pytest.fixture
def callback_client(monkeypatch):
    class Client:
        def __init__(self):
            self.callbacks = defaultdict(list)
            self.sent = []
            self.fail = False

        def add_callback(self, event, callback):
            self.callbacks[event].append(callback)

        def remove_callback(self, event, callback):
            self.callbacks[event].remove(callback)
            if not self.callbacks[event]:
                del self.callbacks[event]

        def request(self, action, params, **kwargs):
            self.sent.append((action, params))
            if self.fail:
                raise RuntimeError('offline request failed')
            return params.get('callback_event')

        def emit(self, event, data):
            for callback in self.callbacks[event]:
                callback(data)

    client = Client()
    monkeypatch.setattr(xtdata, 'get_client', lambda: client)
    return client


@pytest.fixture(params=['history', 'history2', 'financial', 'financial2', 'generic'])
def download(request):
    def call(callback, **kwargs):
        if request.param == 'history':
            return xtdata.download_history_data('000001.SZ', '1d', callback=callback, **kwargs)
        if request.param == 'history2':
            return xtdata.download_history_data2(['000001.SZ'], '1d', callback=callback, **kwargs)
        if request.param == 'financial':
            return xtdata.download_financial_data(['000001.SZ'], callback=callback, **kwargs)
        if request.param == 'financial2':
            return xtdata.download_financial_data2(['000001.SZ'], callback=callback, **kwargs)
        return xtdata.download_index_weight(callback=callback, **kwargs)
    call.supports_keep_callback = request.param != 'history'
    return call


@pytest.mark.parametrize('callback', [0, False, [], 'not callable'])
def test_invalid_callback_rejected_before_rpc(download, callback_client, callback):
    with pytest.raises(TypeError, match='callback must be callable'):
        download(callback)
    assert not callback_client.sent
    assert not callback_client.callbacks


@pytest.mark.parametrize('fail', [False, True])
def test_false_valued_callable_is_registered_and_cleaned_up(download, callback_client, fail):
    class Callback:
        def __bool__(self):
            return False

        def __call__(self, data):
            pass

    callback_client.fail = fail
    if fail:
        with pytest.raises(RuntimeError, match='offline request failed'):
            download(Callback())
    else:
        download(Callback())
    assert callback_client.sent[0][1]['callback_event']
    assert not callback_client.callbacks


def test_same_time_downloads_have_isolated_callbacks(download, callback_client, monkeypatch):
    monkeypatch.setattr(xtdata.time, 'time', lambda: 1000.0)
    received = [[], []]
    kwargs = {'keep_callback': True} if download.supports_keep_callback else {}
    first = download(received[0].append, **kwargs)
    second = download(received[1].append, **kwargs)
    assert first != second
    if download.supports_keep_callback:
        callback_client.emit(first, 'first job progress')
        callback_client.emit(second, 'second job progress')
        assert received == [['first job progress'], ['second job progress']]


def test_request_and_cleanup_use_registration_client(download, callback_client, monkeypatch):
    lookups = []

    def get_client():
        lookups.append(True)
        if len(lookups) > 1:
            raise AssertionError('callback ownership must not change during a request')
        return callback_client

    monkeypatch.setattr(xtdata, 'get_client', get_client)
    download(lambda data: None)
    assert not callback_client.callbacks
