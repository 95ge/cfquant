"""Measure local serialization savings without importing Web configuration or connecting to QMT."""
import argparse
import ast
import base64
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cfquant import protocol


def web_helpers():
    tree = ast.parse((ROOT / 'cfquant_web_server.py').read_text(encoding='utf-8'))
    names = {'to_jsonable', 'jsonable_key', 'JsonReadyResponse', 'web_json_bytes', 'ok'}
    body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    namespace = dict(json=json, math=math, base64=base64, time=time,
                     dataframe_numeric_rows=protocol.dataframe_numeric_rows)
    exec(compile(ast.Module(body=body, type_ignores=[]), '<web serialization only>', 'exec'), namespace)
    return namespace


def benchmark(count=26475, repeat=3):
    web = web_helpers()
    quotes = {'%06d.SH' % i: {'time': 1792112400000, 'lastPrice': 10.25, 'open': 10.0,
              'high': 10.5, 'low': 9.9, 'lastClose': 10.1, 'volume': 2**53 + i,
              'amount': 1025000.0, 'askPrice': [10.26, 10.27, 10.28, 10.29, 10.3],
              'bidPrice': [10.24, 10.23, 10.22, 10.21, 10.2],
              'askVol': [100, 200, 300, 400, 500], 'bidVol': [500, 400, 300, 200, 100]}
              for i in range(count)}
    ready = web['ok'](quotes)
    def old_http():
        return json.dumps(web['to_jsonable'](ready), ensure_ascii=False, separators=(',', ':')).encode()
    def new_http():
        return web['web_json_bytes'](ready)
    event = {'type': 'quote', 'event': {'seq': 1, 'data': quotes, 'meta': {'quote_json_plain': True}}}
    def old_broadcast():
        return [web['web_json_bytes'](event) for _ in range(3)]
    def new_broadcast():
        encoded = web['web_json_bytes'](web['JsonReadyResponse'](event))
        return [encoded] * 3
    def old_coalesce():
        return [protocol.pack_response(str(i), result=quotes) for i in range(6)]
    def new_coalesce():
        encoded = protocol.encode_response_result(quotes)
        return [protocol.pack_response(str(i), encoded_result=encoded) for i in range(6)]

    assert old_http() == new_http()
    assert old_broadcast() == new_broadcast()
    old, new = old_coalesce(), new_coalesce()
    assert all(protocol.loads_message(a)['result'] == protocol.loads_message(b)['result'] for a, b in zip(old, new))
    results = {}
    for name, before, after in [('http_after_ok', old_http, new_http),
                                 ('broadcast_3_clients', old_broadcast, new_broadcast),
                                 ('coalesced_6_waiters', old_coalesce, new_coalesce)]:
        samples = {'before_ms': [], 'after_ms': []}
        for i in range(repeat):
            paths = [('before_ms', before), ('after_ms', after)]
            for key, function in paths[::1 if i % 2 == 0 else -1]:
                started = time.perf_counter()
                function()
                samples[key].append((time.perf_counter() - started) * 1000)
        row = {key: round(statistics.median(values), 3) for key, values in samples.items()}
        row['speedup'] = round(row['before_ms'] / row['after_ms'], 2)
        results[name] = row
    wire = protocol.pack_whole_quote_event('quote:test', quotes)
    parse_times = []
    for _ in range(repeat):
        started = time.perf_counter()
        protocol.loads_message(wire)
        parse_times.append((time.perf_counter() - started) * 1000)
    return {'python': platform.python_version(), 'symbols': count, 'repeat': repeat,
            'json_bytes': len(new_http()), 'data_equal': True, 'stages': results,
            'hub_inner_json_parse_removed_ms': round(statistics.median(parse_times), 3),
            'scope': 'synthetic local serialization only; excludes native QMT, network, scheduling and disk spill'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=26475)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if min(args.count, args.repeat) < 1:
        parser.error('count and repeat must be positive')
    result = json.dumps(benchmark(args.count, args.repeat), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    print(result)
