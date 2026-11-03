"""Synchronize and verify Lite entries together, with a content-based cache."""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

try:
    from tools import sync_qmt_batch as batch, sync_qmt_parity as parity
    from tools.sync_qmt_ast import parse_source
except ImportError:
    import sync_qmt_batch as batch
    import sync_qmt_parity as parity
    from sync_qmt_ast import parse_source

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.local_archive' / 'qmt-sync-cache.json'


def fingerprint(root, targets):
    digest = hashlib.sha256()
    digest.update(('qmt-sync-v1:%s' % (sys.version_info[:2],)).encode('ascii'))
    # Dispatch also reads non-Lite entry templates; include those inputs.
    dependencies = (set(targets) | set((root / 'qmt_scripts').rglob('*.py'))
                    | set((root / 'cfquant').glob('*.py')) | set((root / 'tools').glob('sync_qmt*.py')))
    for path in sorted(dependencies):
        digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def synchronize(*, check=False, no_cache=False, root=ROOT, cache=CACHE):
    started = time.perf_counter()
    targets = sorted((root / 'qmt_scripts').rglob('CFQUANT_LITE*.py'))
    if not targets:
        raise RuntimeError('No Lite entries found')
    signature = fingerprint(root, targets)
    if not no_cache:
        try:
            if json.loads(cache.read_text(encoding='utf-8')).get('fingerprint') == signature:
                print('QMT inputs and verified outputs unchanged; skipped (%.2fs)' % (time.perf_counter() - started), flush=True)
                return 0
        except (OSError, ValueError, AttributeError):
            pass
    core = parity.CORE_PATH.read_text(encoding='utf-8').replace('\r\n', '\n')
    changes = []
    for path in targets:
        raw = path.read_bytes()
        source = raw.decode('gbk').replace('\r\n', '\n')
        updated = batch.update_fileless_source(batch.updated_source(source), lite=True)
        updated = parity.update_fileless_source(parity._patch_source(updated, core), lite=True)
        # Keep the existing post-parity batch verification, using the same
        # bounded parse cache instead of starting another Python process.
        verified = batch.update_fileless_source(batch.updated_source(updated), lite=True)
        if verified != updated:
            raise RuntimeError('Batch/parity synchronization conflict: %s' % path.name)
        parse_source(updated, feature_version=(3, 6))
        newline = '\r\n' if raw.count(b'\r\n') > raw.count(b'\n') / 2 else '\n'
        encoded = updated.replace('\n', newline).encode('gbk')
        if updated != source:
            changes.append((path, encoded))
        print('Verified %s (%.2fs elapsed)' % (path.name, time.perf_counter() - started), flush=True)
    if check and changes:
        for path, _ in changes:
            print('Outdated: %s' % path.relative_to(root), flush=True)
        return 1
    if fingerprint(root, targets) != signature:
        raise RuntimeError('QMT inputs changed while synchronizing; retry with stable sources')
    # All outputs have passed validation before any source file is written.
    for path, data in changes:
        path.write_bytes(data)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix('.%s.tmp' % os.getpid())
    try:
        temporary.write_text(json.dumps({'fingerprint': fingerprint(root, targets)}), encoding='utf-8')
        os.replace(temporary, cache)
    finally:
        if temporary.exists():
            temporary.unlink()
    print('QMT synchronization verified in %.2fs' % (time.perf_counter() - started), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()
    return synchronize(check=args.check, no_cache=args.no_cache)


if __name__ == '__main__':
    raise SystemExit(main())
