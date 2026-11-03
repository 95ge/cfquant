"""Offline monitor overhead benchmark. No QMT, sockets or real orders are used."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time


def summarize(samples):
    ordered = sorted(samples)
    return {'median_us': statistics.median(ordered) / 1000,
            'mean_us': statistics.mean(ordered) / 1000,
            'p95_us': ordered[math.ceil(len(ordered) * .95) - 1] / 1000,
            'p99_us': ordered[math.ceil(len(ordered) * .99) - 1] / 1000,
            'max_us': ordered[-1] / 1000}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--samples', type=int, default=2000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.rounds < 1 or not 1 <= args.samples <= 5000:
        parser.error('rounds must be positive; samples must be between 1 and 5000')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory(prefix='cfquant-monitor-benchmark-') as folder:
        os.environ['CFQUANT_HOME'] = folder
        os.environ['CFQUANT_RUNTIME_DIR'] = str(Path(folder) / 'runtime')
        import cfquant_web_server as web
        from cfquant.trading_monitor import TradingMonitor, day_text
        monitor = TradingMonitor(Path(folder) / 'benchmark.sqlite3', account_type_normalizer=web.normalize_account_type)
        monitor.update_accounts([{'account_key':'benchmark:STOCK:SYNTHETIC', 'bridge_id':'benchmark',
                                  'account_id':'SYNTHETIC', 'account_type':'STOCK'}])
        web.TRADING_MONITOR = monitor
        client = web.GlobalTxClient()
        client._request = lambda *a, **kw: {'order_id': 123, 'request_result': 0}
        params = {'account': {'account_id': 'SYNTHETIC', 'account_type': 'STOCK'},
                  'stock_code': '000001.SZ', 'order_volume': 100}
        event = {'event': 'trader:on_stock_order', 'bridge_id': 'benchmark',
                 'account_id': 'SYNTHETIC', 'account_type': 'STOCK', 'received_at': time.time(),
                 'data': {'order_date': day_text(), 'order_id': 1, 'stock_code': '000001.SZ', 'order_status': 50}}
        stages = ('request_direct', 'request_disabled', 'request_enabled', 'callback_disabled', 'callback_enabled')
        samples = {stage: [] for stage in stages}
        rounds = []
        try:
            # Warm imports, SQLite schema and native bytecode caches outside measurement.
            monitor.start()
            monitor.record_callback(event)
            assert monitor.flush(15), monitor.health()
            monitor.close()
            for index in range(args.rounds):
                row = {}
                for stage in (stages if index % 2 == 0 else tuple(reversed(stages))):
                    enabled = stage.endswith('_enabled')
                    if enabled:
                        monitor.start()
                    else:
                        monitor.close()
                    durations = []
                    for sample in range(args.samples):
                        event['data']['order_id'] = 1 + index * args.samples + sample
                        if stage.startswith('request'):
                            call = client._request if stage == 'request_direct' else client.request
                            started = time.perf_counter_ns()
                            call('benchmark', 'trade', 'xttrader.order_stock', params)
                            durations.append(time.perf_counter_ns() - started)
                        else:
                            started = time.perf_counter_ns()
                            monitor.record_callback(event)
                            durations.append(time.perf_counter_ns() - started)
                    row[stage] = summarize(durations)
                    samples[stage].extend(durations)
                    assert monitor.flush(30), monitor.health()
                    assert monitor.dropped == 0 and not monitor.last_error, monitor.health()
                rounds.append(row)
            metrics = {stage: summarize(values) for stage, values in samples.items()}
            extra = [row['request_enabled']['median_us'] - row['request_disabled']['median_us'] for row in rounds]
            result = {'measured_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'python': platform.python_version(),
                      'platform': platform.platform(), 'processor': platform.processor(),
                      'rounds': args.rounds, 'samples_per_stage_per_round': args.samples,
                      'samples_per_stage': args.rounds * args.samples, 'metrics': metrics,
                      'request_extra_median_us_range': [min(extra), max(extra)],
                      'round_results': rounds, 'dropped': monitor.dropped,
                      'scope': 'In-process request wrapper / callback enqueue only, with an actual background SQLite writer. Fake native request; no QMT or network. Excludes broker latency. Tail latency and resource contention depend on workload.'}
        finally:
            monitor.close()
            if web._LOG_FP:
                web._LOG_FP.close()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'round_results'}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
