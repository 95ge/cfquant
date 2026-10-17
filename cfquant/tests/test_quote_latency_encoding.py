"""Check full quote JSON interoperability without connecting to QMT."""
import ast
from pathlib import Path

import pytest

from cfquant import protocol
from cfquant.callback_dispatcher import dispatch_callbacks
from cfquant.level2 import quote_plain


LITE_PATHS = sorted((Path(__file__).resolve().parents[2] / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))


@pytest.fixture(params=[None] + LITE_PATHS, ids=['shared'] + [path.stem for path in LITE_PATHS])
def encoder(request):
    if request.param is None:
        return protocol.pack_quote_latency_event
    source = request.param.read_text(encoding='gbk')
    tree = ast.parse(source, feature_version=(3, 6))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('pack_quote_latency_event', '_quote_json_default', 'pack_whole_quote_event')]
    assert len(tree.body) == 3
    namespace = dict(vars(protocol))
    exec(compile(tree, str(request.param), 'exec'), namespace)
    return namespace['pack_quote_latency_event']


@pytest.fixture
def whole_encoder(encoder):
    return encoder.__globals__['pack_whole_quote_event']


def packet(quotes):
    return {'schema': 'cfquant.quote_latency.v1', 'qmt_callback_at_ms': 1792112400001.25,
            'qmt_push_at_ms': 1792112400002.5, 'quotes': quotes}


def test_full_snapshot_matches_legacy_encoder_with_numpy_and_unicode(encoder):
    np = pytest.importorskip('numpy')
    quotes = {'000001.SZ': {
        'time': np.int64(1792112400000), 'lastPrice': np.float64(10.125),
        'volume': np.uint64(2**63 + 17), 'bidPrice': np.array([10.1, 10.0]),
        'askVol': (100, 200), 'active': np.bool_(True), 'name': '\u6d4b\u8bd5', 'empty': None,
    }}
    data = packet(quotes)
    legacy = protocol.loads_message(protocol.pack_event('quote:test', quote_plain(data), 'client', 7))
    direct = protocol.loads_message(encoder('quote:test', data, 'client', 7))
    assert direct['data']['quotes'] == legacy['data']['quotes']
    assert direct['data']['quotes']['000001.SZ']['volume'] == 2**63 + 17
    assert direct['data']['qmt_encode_ms'] >= 0
    assert direct['data']['qmt_encoding'] == 'direct_json'
    for key in ('type', 'event', 'client_id', 'subscription_id', 'protocol', 'version'):
        assert direct[key] == legacy[key]
    received = []
    dispatch_callbacks({'quote:test': [received.append]}, direct, lambda: True)
    assert received[0] is direct['data']
    assert 'qmt_encode_ms' not in data  # Serialization must not mutate native input.


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), b'binary'])
def test_special_values_request_legacy_fallback(encoder, bad):
    with pytest.raises((TypeError, ValueError)):
        encoder('quote:test', packet({'000001.SZ': {'value': bad}}))


def test_plain_marker_skips_recursive_sdk_decoding_for_whole_and_diagnostic_quotes(monkeypatch):
    calls, received = [], []
    def decode(value):
        calls.append(value)
        return 'decoded'
    monkeypatch.setattr('cfquant.callback_dispatcher.decode_value', decode)
    direct = protocol.loads_message(protocol.pack_quote_latency_event('quote:test', packet({'000001.SZ': {}})))
    dispatch_callbacks({'quote:test': [received.append]}, direct, lambda: True)
    assert calls == [] and received[-1] is direct['data']
    ordinary = protocol.loads_message(protocol.pack_whole_quote_event('quote:test', {'000001.SZ': {'lastPrice': 10}}))
    dispatch_callbacks({'quote:test': [received.append]}, ordinary, lambda: True)
    assert calls == [] and received[-1] is ordinary['data']
    unmarked = dict(direct, meta={})
    dispatch_callbacks({'quote:test': [received.append]}, unmarked, lambda: True)
    ordinary_unmarked = dict(ordinary, meta={})
    dispatch_callbacks({'quote:test': [received.append]}, ordinary_unmarked, lambda: True)
    assert calls == [unmarked['data'], ordinary_unmarked['data']]
    assert received[-2:] == ['decoded', 'decoded']


def test_ordinary_whole_quote_encoding_preserves_data_and_supports_old_decoder(whole_encoder):
    np = pytest.importorskip('numpy')
    data = {'000001.SZ': {'lastPrice': np.float32(10.25), 'volume': np.uint64(2**63 + 17),
                          'time': np.int64(1792112400000), 'bidPrice': np.array([10.1, 10.0]),
                          'askVol': (100, 200), 'active': np.bool_(True), 'name': '\u6d4b\u8bd5', 'empty': None},
            '600000.SH': {}}
    expected = protocol.decode_value(protocol.loads_message(protocol.pack_event('quote:test', quote_plain(data)))['data'])
    event = protocol.loads_message(whole_encoder('quote:test', data, 'sdk', 7))
    assert event['data'] == expected
    assert protocol.decode_value(event['data']) == expected  # Old SDKs still consume ordinary JSON.
    assert event['data']['000001.SZ']['volume'] == 2**63 + 17
    assert event['meta']['quote_json_plain'] is True
    assert event['client_id'] == 'sdk' and event['subscription_id'] == 7
    assert set(event['data']) == set(data)
    assert isinstance(data['000001.SZ']['bidPrice'], np.ndarray)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), b'binary'])
def test_ordinary_special_values_request_fallback(whole_encoder, bad):
    with pytest.raises((TypeError, ValueError)):
        whole_encoder('quote:test', {'000001.SZ': {'value': bad}})
