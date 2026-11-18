"""Real holiday data, SDK compatibility and Web routing without QMT."""
import datetime
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from cfquant import trading_calendar as calendar, xtdata


def stamp(day):
    return int(datetime.datetime.strptime(day, "%Y%m%d").replace(
        tzinfo=datetime.timezone(datetime.timedelta(hours=8))
    ).timestamp() * 1000)


@pytest.fixture(autouse=True)
def offline_calendar(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("calendar must not require a QMT connection")
    monkeypatch.setattr(xtdata, "get_client", unexpected)
    monkeypatch.setattr(calendar, "_today", lambda: datetime.datetime(
        2026, 10, 10, tzinfo=datetime.timezone(datetime.timedelta(hours=8))))
    loader = calendar._get_calendar
    loader.cache_clear()
    calendar._year_dates.cache_clear()
    yield
    loader.cache_clear()
    calendar._year_dates.cache_clear()


@pytest.mark.parametrize("market", ["SH", "SZ", "BJ", " sh "])
def test_a_share_holidays_weekends_and_millisecond_format(market):
    # SSE 2026 notice: Jan 1-3 closed; Jan 4 remains a weekend closure.
    result = xtdata.get_trading_dates(market, "20260101", "20260107")
    assert result == [stamp(d) for d in ("20260105", "20260106", "20260107")]
    assert all(type(value) is int for value in result)
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("market", ["SH", "SZ", "BJ"])
def test_spring_festival_and_makeup_workday_are_closed(market):
    # SSE notice: Feb 15-23 closed; Feb 14/28 are weekend closures.
    assert xtdata.get_trading_dates(market, "20260213", "20260224") == [stamp("20260213"), stamp("20260224")]
    assert xtdata.get_trading_dates(market, "20260228", "20260301") == []


def test_hong_kong_uses_its_own_calendar():
    assert xtdata.get_trading_dates("HK", "20260101", "20260105") == [stamp("20260102"), stamp("20260105")]


def test_count_filters_range_then_takes_last_dates_across_years():
    assert xtdata.get_trading_dates(market="SZ", start_time="20251201", end_time="20260105", count=3) == [
        stamp(d) for d in ("20251230", "20251231", "20260105")]
    assert xtdata.get_trading_dates("SH", "20260105", "20260107", 10) == [
        stamp(d) for d in ("20260105", "20260106", "20260107")]
    assert xtdata.get_trading_dates("SH", "20260105", "20260107", np.int64(1)) == [stamp("20260107")]


def test_defaults_and_future_bounds():
    expected = [stamp("20261008"), stamp("20261009")]
    assert xtdata.get_trading_dates("SH", count=2) == expected
    assert xtdata.get_trading_dates("SH", end_time="20991231", count=2) == expected
    assert xtdata.get_trading_dates("SH", "20261011", "20991231") == []
    assert xtdata.get_trading_dates("SH", "20260107", "20260106") == []
    assert xtdata.get_trading_dates("SH", count=0) == []


def test_intraday_bounds_and_host_timezone_independence():
    result = xtdata.get_trading_dates("SH", "20260105120000", "20260106120000")
    assert result == [1767628800000]  # Jan 6 00:00 UTC+8 = Jan 5 16:00 UTC.
    assert xtdata.get_trading_dates("SH", "20260106120000", "20260106110000") == []


def test_history_floor_and_beijing_first_session():
    result = xtdata.get_trading_dates("SH", end_time="19910103")
    assert result == [stamp("19910102"), stamp("19910103")]
    assert xtdata.get_trading_dates("BJ", "19900101", "20211116") == [stamp("20211115"), stamp("20211116")]
    assert xtdata.get_trading_dates("SH", "19000101", "19901231") == []


@pytest.mark.parametrize("count", [-2, 1.5, True, None, "2"])
def test_invalid_counts(count):
    with pytest.raises(ValueError, match="count"):
        xtdata.get_trading_dates("SH", count=count)


@pytest.mark.parametrize("market", [None, "", "600000.SH", "IF", "BSE", "SHHK"])
def test_unknown_markets_do_not_silently_use_sse(market):
    with pytest.raises(ValueError, match="market"):
        xtdata.get_trading_dates(market)


@pytest.mark.parametrize("day", ["20260230", "2026-01-01", "202601", "20260101250000", 20260101])
def test_invalid_dates(day):
    with pytest.raises(ValueError):
        xtdata.get_trading_dates("SH", day)


def test_missing_dependency_has_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "pandas_market_calendars", None)
    with pytest.raises(ImportError, match="python -m pip install"):
        xtdata.get_trading_dates("SH", count=1)


def test_incompatible_calendar_annotations_have_actionable_error(monkeypatch):
    import builtins
    original_import = builtins.__import__
    def incompatible(name, *args, **kwargs):
        if name == 'pandas_market_calendars':
            raise TypeError("unsupported operand type(s) for |: 'type' and 'NoneType'")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', incompatible)
    with pytest.raises(ImportError, match='python -m pip install') as failure:
        xtdata.get_trading_dates('SH', count=1)
    assert isinstance(failure.value.__cause__, TypeError)
    message = str(failure.value)
    assert ('pandas-market-calendars==5.2.2' in message) == (sys.version_info < (3, 10))
    assert ('backports.zoneinfo' in message) == (sys.version_info < (3, 9))


def test_old_calendar_cannot_guess_current_holidays(monkeypatch):
    old = SimpleNamespace(adhoc_holidays=[datetime.datetime(2025, 10, 8)])
    monkeypatch.setattr(calendar, "_get_calendar", lambda name: old)
    with pytest.raises(ValueError, match="recorded through 2025; requested 2026"):
        xtdata.get_trading_dates("SH", "20260101", "20260107")


def test_cached_results_are_not_mutable_shared_state():
    result = xtdata.get_trading_dates("SH", "20260105", "20260106")
    result.clear()
    assert xtdata.get_trading_dates("SH", "20260105", "20260106") == [stamp("20260105"), stamp("20260106")]


@pytest.fixture
def web(monkeypatch):
    import cfquant_web_server as module
    def unexpected(*args, **kwargs):
        pytest.fail("calendar must not route to QMT or select an account")
    monkeypatch.setattr(module, "data_provider_candidates", unexpected)
    monkeypatch.setattr(module, "data_account_route_candidates", unexpected)
    monkeypatch.setattr(module, "account_request", unexpected)
    monkeypatch.setattr(module, "CLIENTS", SimpleNamespace(request=unexpected))
    monkeypatch.setattr(module, "WEB_CONFIG", None)
    return module


@pytest.mark.parametrize("account", ["", "OFFLINE_ACCOUNT"])
def test_web_http_handler_and_lttx_route_use_same_local_calendar(web, account):
    params = dict(market="SH", start_time="20260101", end_time="20260107", count="2", account_id=account)
    route = web.get_trading_dates(params)
    assert route["result"] == [stamp("20260106"), stamp("20260107")]
    assert route["source"] == "pandas_market_calendars"
    assert route["mode"] == route["channel"] == "local"
    result, meta = web.route_external_lttx_request(dict(action="xtdata.get_trading_dates", params=params))
    assert result == route["result"]
    assert meta["source"] == "pandas_market_calendars"


@pytest.mark.parametrize("count", [True, 1.5, -2, "1.5"])
def test_web_does_not_truncate_invalid_count(web, count):
    with pytest.raises(ValueError):
        web.get_trading_dates(dict(market="SH", count=count))


def test_other_actions_and_legacy_bar_requests_are_not_intercepted(web):
    assert web.local_trading_dates_request("xtdata.get_full_tick", {"market": "SH"}) is None
    assert web.local_trading_dates_request("xtdata.get_trading_dates", {"stockcode": "600000.SH"}) is None
