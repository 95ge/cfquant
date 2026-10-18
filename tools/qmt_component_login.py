"""Command-line entry for the packaged QMT component login implementation."""
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cfquant.qmt_component_login import auto_login, main, QtLoginBackend, select_binding

if __name__ == '__main__':
    sys.exit(main())