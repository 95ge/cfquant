"""Path-valued SDK arguments must become text before RPC/HTTP serialization."""
import os

import pytest

from cfquant import xtdata
from cfquant.tests.test_json_serialization import transport
from cfquant.tests.test_storage_paths import FilePath
from cfquant.xttrader import XtQuantTrader
from cfquant.xttype import StockAccount


@pytest.fixture(params=['str', 'path', 'pathlike', 'bytes'])
def api_path(request, tmp_path):
    path = tmp_path / '中文 数据' / 'result.csv'
    value = {'str': str(path), 'path': path, 'pathlike': FilePath(path),
             'bytes': os.fsencode(path)}[request.param]
    return value, str(path)


def test_local_data_path_survives_rpc(transport, monkeypatch, api_path):
    value, expected = api_path
    monkeypatch.setattr(xtdata, 'get_client', lambda: transport.client)
    xtdata.get_local_data(stock_list=['000001.SZ'], data_dir=value)
    assert transport.messages[0]['params']['data_dir'] == expected


def test_local_data_default_keeps_null_directory(transport, monkeypatch):
    monkeypatch.setattr(xtdata, 'get_client', lambda: transport.client)
    xtdata.get_local_data(stock_list=['000001.SZ'])
    assert transport.messages[0]['params']['data_dir'] is None


@pytest.mark.parametrize('method', ['query_data', 'export_data'])
def test_trade_export_path_survives_rpc(transport, monkeypatch, api_path, method):
    value, expected = api_path
    trader = XtQuantTrader(account=StockAccount('OFFLINE_PATH_TEST'))
    monkeypatch.setattr(trader, '_get_client', lambda bridge_id=None: transport.client)
    getattr(trader, method)(trader.account, value, 'order')
    message, = transport.messages
    assert message['action'] == 'xttrader.' + method
    assert message['params']['args'][0] == expected


def test_invalid_path_fails_before_transport_start(transport, monkeypatch):
    monkeypatch.setattr(xtdata, 'get_client', lambda: transport.client)
    with pytest.raises(TypeError):
        xtdata.get_local_data(data_dir=object())
    assert transport.starts == 0 and transport.messages == []
