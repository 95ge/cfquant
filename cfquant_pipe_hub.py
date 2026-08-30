# -*- coding: utf-8 -*-
import sys
sys.dont_write_bytecode = True

import argparse

from cfquant.pipe_hub import run_pipe_hub


def main():
    parser = argparse.ArgumentParser(description="Start cfquant named-pipe hub.")
    parser.add_argument("--pipe-name", default=None, help=r"Pipe name, e.g. \\.\pipe\cfquant_pipe_hub")
    parser.add_argument("--quiet", action="store_true", help="Disable console logs.")
    parser.add_argument("--default-request-channel", default="cfquant.normal.request")
    args = parser.parse_args()
    run_pipe_hub(
        pipe_name=args.pipe_name,
        show=not args.quiet,
        default_request_channel=args.default_request_channel,
    )


if __name__ == "__main__":
    main()
