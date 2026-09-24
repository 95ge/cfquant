import pandas as pd

from cfquant.qmt_bridge import CfquantQmtBridge
from cfquant.tx_trade_bridge import TxTradeBridge


class EmptyNativeContext:
    def __init__(self, native_result):
        self.native_result = native_result
        self.calls = []

    def get_market_data(self, *args):
        self.calls.append(("native", args))
        return self.native_result

    def get_market_data_ex(self, *args):
        self.calls.append(("extended", args))
        return {"000001.SZ": pd.DataFrame({"close": [11.2, 11.3]})}


def test_empty_native_market_data_falls_back_to_extended_qmt():
    context = EmptyNativeContext(pd.DataFrame())
    bridge = CfquantQmtBridge(context, show=False)

    result = bridge._get_market_data({
        "field_list": ["close"],
        "stock_list": ["000001.SZ"],
        "period": "1d",
        "count": 2,
    })

    assert list(result) == ["close"]
    assert result["close"].loc["000001.SZ"].tolist() == [11.2, 11.3]
    assert [kind for kind, _ in context.calls] == ["native", "extended"]


def test_scalar_native_market_data_falls_back_in_trade_bridge():
    context = EmptyNativeContext(11.3)
    bridge = TxTradeBridge(object(), globals_dict={
        "get_market_data": context.get_market_data,
        "get_market_data_ex": context.get_market_data_ex,
    }, show=False)

    result = bridge._get_market_data({
        "field_list": ["close"],
        "stock_list": ["000001.SZ"],
        "period": "1d",
        "count": 2,
    })

    assert result["close"].loc["000001.SZ"].tolist() == [11.2, 11.3]
    assert [kind for kind, _ in context.calls] == ["native", "extended"]
