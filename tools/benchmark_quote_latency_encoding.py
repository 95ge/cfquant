"""Offline benchmark of complete snapshot encoding; no QMT/account connection."""
import argparse
import json
from pathlib import Path
import platform
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cfquant.level2 import quote_plain
from cfquant.protocol import loads_message, pack_event, pack_quote_latency_event, pack_whole_quote_event


def benchmark(count, repeat, kind='diagnostic'):
    quotes = {}
    for index in range(count):
        price = 10 + (index % 10000) / 100.0
        quotes['%06d.SH' % index] = {
            'time': 1792112400000, 'lastPrice': price, 'open': price - 0.5, 'high': price + 1,
            'low': price - 1, 'lastClose': price - 0.1, 'amount': price * 100000,
            'volume': 1000 + index, 'pvolume': 100000 + index, 'stockStatus': 0,
            'openInt': 13, 'lastSettlementPrice': 0.0, 'transactionNum': index,
            'askPrice': [round(price + i / 100, 2) for i in range(1, 6)],
            'bidPrice': [round(price - i / 100, 2) for i in range(1, 6)],
            'askVol': [100, 200, 300, 400, 500], 'bidVol': [500, 400, 300, 200, 100],
        }
    data = {'schema': 'cfquant.quote_latency.v1', 'qmt_callback_at_ms': 1792112400001.25,
            'qmt_push_at_ms': 1792112400002.5, 'quotes': quotes}
    if kind == 'whole':
        data = quotes
    pack_direct = pack_whole_quote_event if kind == 'whole' else pack_quote_latency_event
    def legacy():
        return pack_event('quote:benchmark', quote_plain(data), 'offline', 1)
    def direct():
        return pack_direct('quote:benchmark', data, 'offline', 1)
    old, new = legacy(), direct()  # Warm up and verify semantics before timing.
    old_data, new_data = loads_message(old)['data'], loads_message(new)['data']
    assert (old_data == new_data if kind == 'whole' else old_data['quotes'] == new_data['quotes'])
    times = {'legacy_ms': [], 'direct_ms': []}
    for iteration in range(repeat):
        # Alternate order to reduce systematic warm-cache bias.
        paths = [('legacy_ms', legacy), ('direct_ms', direct)]
        for key, encode in paths[::1 if iteration % 2 == 0 else -1]:
            start = time.perf_counter()
            encode()
            times[key].append(round((time.perf_counter() - start) * 1000, 3))
    medians = {key: round(statistics.median(values), 3) for key, values in times.items()}
    return {'python': platform.python_version(), 'symbols': count, 'repeat': repeat, 'kind': kind,
            'payload_equal': True, 'legacy_bytes': len(old.encode('utf-8')), 'direct_bytes': len(new.encode('utf-8')),
            'median': medians, 'speedup': round(medians['legacy_ms'] / medians['direct_ms'], 2),
            'runs': times, 'scope': 'synthetic snapshot encoding only; excludes transport and live QMT'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=26475)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--kind', choices=['diagnostic', 'whole'], default='diagnostic')
    args = parser.parse_args()
    if args.count < 1 or args.repeat < 1:
        parser.error('count and repeat must be positive')
    print(json.dumps(benchmark(args.count, args.repeat, args.kind), ensure_ascii=False, indent=2))
