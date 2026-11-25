# -*- coding: utf-8 -*-
"""Compatibility launcher. Core services are owned by center A."""
from pathlib import Path
import sys

# Embedded interpreters may otherwise select an older installed SDK.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def management_status():
    """Compatibility marker/API for management updaters from older releases."""
    from cfquant.runtime_services import management_status as status
    return status()


def main(argv=None):
    from cfquant.center_runtime import main as center_main
    return center_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
