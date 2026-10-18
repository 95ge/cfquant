# -*- coding: utf-8 -*-
"""Market dates from the same calendar dependency used by LTtx, outside QMT."""
import datetime
from functools import lru_cache
from numbers import Integral


_ZONE = datetime.timezone(datetime.timedelta(hours=8))
# SSE's recorded holiday history starts in 1991. BJ starts at its first session.
# BSE in pandas_market_calendars means Bombay, not Beijing.
_MARKETS = {
    "SH": ("SSE", "19910101"),
    "SZ": ("SSE", "19910101"),
    "BJ": ("SSE", "20211115"),
    "HK": ("HKEX", "19910101"),
}


def _parse_date(value):
    if not isinstance(value, str) or len(value) not in (8, 14) or not value.isascii() or not value.isdigit():
        raise ValueError("trading date must be YYYYMMDD or YYYYMMDDhhmmss")
    return datetime.datetime.strptime(
        value, "%Y%m%d" if len(value) == 8 else "%Y%m%d%H%M%S"
    ).replace(tzinfo=_ZONE)


def _today():
    return datetime.datetime.now(_ZONE).replace(hour=0, minute=0, second=0, microsecond=0)


@lru_cache(maxsize=2)
def _get_calendar(name):
    try:
        import pandas_market_calendars as mcal
    except ImportError as error:
        raise ImportError(
            "get_trading_dates requires pandas-market-calendars in the external Python "
            "environment; run: python -m pip install -U pandas-market-calendars"
        ) from error
    return mcal.get_calendar(name)


def _check_coverage(calendar, name, end):
    if name == "SSE":
        # SSE extrapolates holidays beyond its explicit holiday table. Those
        # guesses must not silently become historical trading dates next year.
        last_year = max(day.year for day in calendar.adhoc_holidays)
        if end.year > last_year:
            raise ValueError(
                "SSE calendar holidays are only recorded through %s; requested %s. "
                "Update pandas-market-calendars in this Python environment and restart."
                % (last_year, end.year)
            )


@lru_cache(maxsize=128)
def _year_dates(name, year):
    calendar = _get_calendar(name)
    # Ask for session dates, not market_open (09:30) or UTC midnight. Converting
    # each datetime also works with pandas indexes stored in microseconds.
    days = calendar.valid_days(
        start_date="%04d-01-01" % year,
        end_date="%04d-12-31" % year,
        tz="Asia/Shanghai",
    )
    return tuple(sorted({int(day.timestamp() * 1000) for day in days}))


def get_trading_dates(market, start_time="", end_time="", count=-1):
    """Return ascending UTC+8 midnight millisecond timestamps, through today.

    SH/SZ/BJ use SSE session dates; HK uses HKEX (not Stock Connect).
    The supported history starts in 1991, or 2021-11-15 for BJ. Positive
    count selects the last N sessions inside the range; -1 selects all.
    """
    if not isinstance(market, str) or market.strip().upper() not in _MARKETS:
        raise ValueError("unsupported market; expected SH, SZ, BJ or HK")
    if isinstance(count, bool) or not isinstance(count, Integral) or count < -1:
        raise ValueError("count must be -1 or a non-negative integer")
    name, first_day = _MARKETS[market.strip().upper()]
    first = _parse_date(first_day)
    lower = max(_parse_date(start_time) if start_time else first, first)
    upper = min(_parse_date(end_time) if end_time else _today(), _today())
    if count == 0 or lower > upper:
        return []
    calendar = _get_calendar(name)
    _check_coverage(calendar, name, upper)
    lower_ms, upper_ms = int(lower.timestamp() * 1000), int(upper.timestamp() * 1000)
    chunks = []
    size = 0
    # Start at the end so count=1 does not load decades of calendar history.
    for year in range(upper.year, lower.year - 1, -1):
        chunk = [day for day in _year_dates(name, year) if lower_ms <= day <= upper_ms]
        chunks.append(chunk)
        size += len(chunk)
        if count > 0 and size >= count:
            break
    dates = [day for chunk in reversed(chunks) for day in chunk]
    return dates[-int(count):] if count > 0 else dates


def is_trading_day(day, market="SH"):
    """Check a session date, including future dates within recorded holidays."""
    name, first_day = _MARKETS[market]
    date = _parse_date(day.strftime("%Y%m%d"))
    _check_coverage(_get_calendar(name), name, date)
    return date >= _parse_date(first_day) and int(date.timestamp() * 1000) in _year_dates(name, date.year)
