"""Update handoff: wait for the old center to release ownership, then start A."""
import os
import json
import runpy
import sys
from pathlib import Path


def owned_lttx_processes(runtime_dir):
    """Snapshot only brokers explicitly launched into this runtime directory."""
    import psutil
    expected = Path(runtime_dir).resolve()
    owned = []
    for process in psutil.process_iter(['cmdline']):
        try:
            args = process.info['cmdline'] or []
            is_server = any(Path(arg).name.lower() == 'lttx_server.py' for arg in args)
            is_module = any(args[i:i + 2] == ['-m', 'LTtx.tx.LTtx_server'] for i in range(len(args) - 1))
            if not (is_server or is_module):
                continue
            state = process.environ().get('CFQUANT_RUNTIME_DIR')
            if state and Path(state).resolve() == expected:
                owned.append(dict(pid=process.pid, created=process.create_time()))
        except (psutil.Error, OSError):
            continue
    return owned


def stop_recorded_processes(identities):
    """Never terminate a PID that has been reused since the snapshot."""
    import psutil
    for identity in identities:
        try:
            process = psutil.Process(identity['pid'])
            if abs(process.create_time() - identity['created']) > .05:
                continue
            # LTtx can own a multiprocessing ZMQ publisher. Capture it before
            # terminating the verified broker so it cannot outlive an update.
            children = process.children(recursive=True)
            process.terminate()
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs([process] + children, timeout=10)
            for remaining in alive:
                try:
                    remaining.kill()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(alive, timeout=5)
            if alive:
                raise RuntimeError('old LTtx processes did not stop')
        except psutil.NoSuchProcess:
            pass


def main():
    import psutil
    parent_pid = int(os.environ.pop('CFQUANT_RESTART_PARENT_PID'))
    try:
        parent = psutil.Process(parent_pid)
        created = float(os.environ.pop('CFQUANT_CENTER_PARENT_CREATED', '0'))
        if not created or abs(parent.create_time() - created) <= .05:
            parent.wait(timeout=45)
    except psutil.NoSuchProcess:
        pass
    stop_recorded_processes(json.loads(os.environ.pop('CFQUANT_RESTART_LTTX_IDENTITIES', '[]')))
    # This script is copied outside the replaced source tree before handoff.
    # The selected release may predate center_runtime (a rollback).
    entry = sys.argv[1]
    sys.argv = [entry]
    runpy.run_path(entry, run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
