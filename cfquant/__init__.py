# -*- coding: utf-8 -*-
"""
cfquant: 基于 LTtx 的 xtquant 兼容层。

外部程序导入本包后，可以按常见 xtquant 方式使用：

    from cfquant import xtdata, xtconstant
    from cfquant.xttrader import XtQuantTrader
    from cfquant.xttype import StockAccount
"""

from . import xtconstant, xtdata, xttrader, xttype
from .client import CfquantError, CfquantTimeout, configure, get_client

__all__ = [
    "xtconstant",
    "xtdata",
    "xttrader",
    "xttype",
    "configure",
    "get_client",
    "CfquantError",
    "CfquantTimeout",
]
