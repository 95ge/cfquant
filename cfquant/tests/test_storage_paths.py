"""Filesystem paths keep persistence and exclusive ownership across restarts."""
import os

import pytest

from cfquant.algo import AlgoStore
from cfquant.subscription_store import SubscriptionStore


class FilePath:
    def __init__(self, path):
        self.path = path

    def __fspath__(self):
        return os.fspath(self.path)


@pytest.mark.parametrize('store_type', [SubscriptionStore, AlgoStore])
@pytest.mark.parametrize('path_type', ['str', 'path', 'pathlike', 'bytes'])
def test_store_path_types_preserve_data_and_single_owner(tmp_path, store_type, path_type):
    filename = tmp_path / '中文 目录' / 'state.sqlite3'
    paths = {'str': str(filename), 'path': filename,
             'pathlike': FilePath(filename), 'bytes': os.fsencode(filename)}
    store = store_type(paths[path_type])
    try:
        if store_type is SubscriptionStore:
            store.open_owner('test-owner-1234567890', 'test-secret-1234567890', 'client')
            store.sync('test-owner-1234567890', 0, [{
                'id': '1', 'action': 'xtdata.subscribe_quote',
                'params': {'stock_code': '000001.SZ', 'period': 'tick'},
            }], lambda spec: dict(spec, route={'bridge_id': 'test'}))
        else:
            store.save({'algo_id': 'test-task', 'state': 'PAUSED'})
        # Another path representation must address the same lock, not a new file.
        with pytest.raises(RuntimeError, match='another .* owns'):
            store_type(str(filename))
    finally:
        store.close()
    assert filename.is_file()
    assert filename.with_name(filename.name + '.lock').is_file()
    reopened = store_type(filename)
    try:
        if store_type is SubscriptionStore:
            row, = reopened.rows('test-owner-1234567890')
            assert row['desired'] == 1
            assert row['spec']['params']['stock_code'] == '000001.SZ'
        else:
            assert reopened.load() == [{'algo_id': 'test-task', 'state': 'PAUSED'}]
    finally:
        reopened.close()


@pytest.mark.parametrize('store_type', [SubscriptionStore, AlgoStore])
def test_memory_store_does_not_create_owner_lock(tmp_path, monkeypatch, store_type):
    monkeypatch.chdir(tmp_path)
    first, second = store_type(':memory:'), store_type(':memory:')
    try:
        assert first._owner_file is second._owner_file is None
        assert list(tmp_path.iterdir()) == []
    finally:
        first.close()
        second.close()
