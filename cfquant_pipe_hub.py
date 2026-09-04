# -*- coding: utf-8 -*-
import sys
sys.dont_write_bytecode = True

import argparse
import os


def _path(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start cfquant named-pipe hub.")
    parser.add_argument("--pipe-name", default=None, help=r"Pipe name, e.g. \\.\pipe\cfquant_pipe_hub")
    parser.add_argument("--quiet", action="store_true", help="Disable console logs.")
    parser.add_argument("--default-request-channel", default="cfquant.normal.request")
    parser.add_argument("--home", "--state-dir", dest="home", help="Writable cfquant state directory.")
    parser.add_argument("--runtime-dir", help="Override the runtime directory.")
    parser.add_argument("--status-file", help="Override the PipeHub status JSON file.")
    args = parser.parse_args(argv)
    if args.home:
        home = _path(args.home)
        os.environ["CFQUANT_HOME"] = home
        if not args.runtime_dir:
            os.environ["CFQUANT_RUNTIME_DIR"] = os.path.join(home, "runtime")
    if args.runtime_dir:
        os.environ["CFQUANT_RUNTIME_DIR"] = _path(args.runtime_dir)
    if args.status_file:
        os.environ["CFQUANT_PIPE_HUB_STATUS_FILE"] = _path(args.status_file)

    from cfquant.pipe_hub import run_pipe_hub

    run_pipe_hub(
        pipe_name=args.pipe_name,
        show=not args.quiet,
        default_request_channel=args.default_request_channel,
    )


if __name__ == "__main__":
    main()
