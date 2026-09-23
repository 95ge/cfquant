# -*- coding: utf-8 -*-
"""
cfquant: 面向 QMT 的 xtquant 兼容层。

外部程序导入本包后，可以按常见 xtquant 方式使用：

    from cfquant import xtdata, xtconstant
    from cfquant.xttrader import XtQuantTrader
    from cfquant.xttype import StockAccount
"""

from . import xtconstant, xtdata, xttrader, xttype
from . import cftrader
from .client import CfquantError, CfquantTimeout, configure, get_client
from .version import __version__
from .build_info import build_identity, get_git_commit

_BUILD_IDENTITY = build_identity(__version__)
GIT_COMMIT = _BUILD_IDENTITY["git_commit"]
SHORT_GIT_COMMIT = _BUILD_IDENTITY["short_commit"]
BUILD_VERSION = _BUILD_IDENTITY["build_version"]

__all__ = [
    "xtconstant",
    "xtdata",
    "xttrader",
    "cftrader",
    "xttype",
    "configure",
    "get_client",
    "CfquantError",
    "CfquantTimeout",
    "__version__",
    "GIT_COMMIT",
    "SHORT_GIT_COMMIT",
    "BUILD_VERSION",
    "get_git_commit",
    "build_identity",
]
