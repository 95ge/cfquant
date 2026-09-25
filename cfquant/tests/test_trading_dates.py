"""Market calendar translation, without a running QMT or trading connection."""
import ast
import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfquant import xtdata
from cfquant.tx_trade_bridge import TxTradeBridge


ROOT = Path(__file__).resolve().parents[2]


def stamp(day):
    return int(datetime.datetime.strptime(day, "%Y%m%d").replace(
        tzinfo=datetime.timezone(datetime.timedelta(hours=8))
    ).timestamp() * 1000)


@pytest.fixture(params=[None] + list((ROOT / "qmt_scripts").rglob("CFQUANT_LITE*.py")))
def adapter(request):
    if request.param is None:
        return TxTradeBridge._get_trading_dates
    tree = ast.parse(request.param.read_text(encoding="gbk"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TxTradeBridge")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_get_trading_dates")
    scope = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(request.param), "exec"), scope)
    return scope[method.name]


def wire(monkeypatch, adapter, calendar):
    bridge = SimpleNamespace(_get_callable=lambda name: calendar if name == "get_trading_calendar" else None)
    def request(action, params):
        assert action == "xtdata.get_trading_dates"
        assert set(params) == {"market", "start_time", "end_time", "count"}
        return adapter(bridge, params)
    monkeypatch.setattr(xtdata, "get_client", lambda: SimpleNamespace(request=request))


@pytest.mark.parametrize("market", ["SH", "SZ", "BJ", "HK", "IF"])
def test_keywords_range_count_and_timestamps(monkeypatch, adapter, market):
    calls = []
    def calendar(*args):
        calls.append(args)
        return ["20260107", "20260105", "20260106", "20260106", "20251231", "20260202"]
    wire(monkeypatch, adapter, calendar)
    assert xtdata.get_trading_dates(market=market, start_time="20260101", end_time="20260131", count=2) == [stamp("20260106"), stamp("20260107")]
    assert calls == [(market, "20260101", "20260131")]
    assert xtdata.get_trading_dates(market, "20260101", "20260131") == [stamp(d) for d in ("20260105", "20260106", "20260107")]


def test_defaults_and_future_cap(monkeypatch, adapter):
    calls = []
    wire(monkeypatch, adapter, lambda *args: calls.append(args) or [])
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y%m%d")
    assert xtdata.get_trading_dates("SH") == []
    assert calls == [("SH", "", today)]
    assert xtdata.get_trading_dates("SH", end_time="20991231") == []
    assert calls[-1] == ("SH", "", today)


def test_empty_and_validation(monkeypatch, adapter):
    def unexpected(*args):
        pytest.fail("invalid/empty query must not invoke QMT")
    wire(monkeypatch, adapter, unexpected)
    assert xtdata.get_trading_dates("SH", count=0) == []
    assert xtdata.get_trading_dates("SH", "20260201", "20260101") == []
    for count in (-2, 1.5, True):
        with pytest.raises(ValueError, match="count"):
            xtdata.get_trading_dates("SH", count=count)
    with pytest.raises(ValueError, match="market"):
        xtdata.get_trading_dates("600000.SH")
    with pytest.raises(ValueError):
        xtdata.get_trading_dates("SH", "20260230")


def test_missing_calendar_and_malformed_result(monkeypatch, adapter):
    wire(monkeypatch, adapter, None)
    with pytest.raises(NotImplementedError, match="get_trading_calendar"):
        xtdata.get_trading_dates("SH")
    wire(monkeypatch, adapter, lambda *args: None)
    with pytest.raises(ValueError, match="returned None"):
        xtdata.get_trading_dates("SH")


def test_intraday_bounds(monkeypatch, adapter):
    calls = []
    wire(monkeypatch, adapter, lambda *args: calls.append(args) or ["20260105", "20260106"])
    assert xtdata.get_trading_dates("SH", "20260105120000", "20260106120000") == [stamp("20260106")]
    assert calls == [("SH", "20260105", "20260106")]
