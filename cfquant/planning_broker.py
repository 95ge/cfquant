"""Account snapshots and exchange calendars used by persistent order plans."""
import datetime as dt
import time

from .algo import positive
from .algo_broker import RoutedAlgoBroker, SHANGHAI
from .diagnostics import quote_time_ms
from .position_sizing import instrument_rules
from .xttype import XtAsset, XtPosition


class PlanningBroker(RoutedAlgoBroker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._calendar = {}

    def rules(self, code):
        detail = self.market_request("xtdata.get_instrument_detail", dict(stock_code=code, iscomplete=True))
        if not isinstance(detail, dict):
            raise ValueError("instrument metadata unavailable")
        return instrument_rules(code, price_tick=positive(detail.get("PriceTick"), "PriceTick"))

    def snapshot(self, account, code):
        params = dict(account=account, stock_code=code)
        asset = self.trade_request(account, "xttrader.query_stock_asset", params)
        if isinstance(asset, list):
            asset = asset[0] if len(asset) == 1 else None
        if asset is None:
            raise RuntimeError("account assets unavailable")
        asset = XtAsset.from_any(asset)
        rows = self.trade_request(account, "xttrader.query_stock_positions", params)
        if not isinstance(rows, (list, tuple)):
            raise RuntimeError("account positions unavailable")
        positions = [XtPosition.from_any(row) for row in rows]
        positions = [row for row in positions if row.stock_code == code]
        orders = self.orders(account, code)
        pending = sum(max(0, int(row.get("order_volume") or 0) - int(row.get("traded_volume") or 0))
                      for row in orders if row.get("stock_code") == code and int(row.get("order_type") or 0) == 23
                      and int(row.get("order_status", 255)) not in (53, 54, 56, 57))
        return dict(total_asset=positive(asset.total_asset, "total_asset", allow_zero=True),
                    available_cash=positive(asset.cash, "available_cash", allow_zero=True),
                    current_volume=sum(int(row.volume) for row in positions),
                    sellable_volume=sum(int(row.can_use_volume) for row in positions),
                    pending_buy_volume=pending, captured_at=time.time())

    def trading_dates(self, market, first, last):
        key = (market, first, last)
        cached = self._calendar.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        values = self.market_request("xtdata.get_trading_dates", dict(market=market, start_time=first, end_time=last, count=-1))
        if values is None:
            raise RuntimeError("exchange calendar unavailable")
        dates = set()
        for value in values:
            text = str(value).replace("-", "")
            if len(text) == 8 and text.isdigit():
                dates.add(text)
            else:
                stamp = quote_time_ms(value)
                if stamp is not None:
                    dates.add(dt.datetime.fromtimestamp(stamp / 1000, SHANGHAI).strftime("%Y%m%d"))
        result = sorted(dates)
        self._calendar[key] = (time.monotonic(), result)
        return result

    def session_end(self, code, now):
        local = dt.datetime.fromtimestamp(now, SHANGHAI)
        date = local.strftime("%Y%m%d")
        if date not in self.trading_dates(code.rsplit(".", 1)[-1], date, date):
            return None
        for begin, end in (("09:30", "11:30"), ("13:00", "14:57")):
            a = dt.datetime.combine(local.date(), dt.time.fromisoformat(begin), SHANGHAI).timestamp()
            b = dt.datetime.combine(local.date(), dt.time.fromisoformat(end), SHANGHAI).timestamp()
            if a <= now < b:
                return b
        return None

    def holding_deadline(self, code, rule):
        if "at" in rule:
            return rule["at"]
        opened = dt.datetime.fromtimestamp(rule["opened_at"], SHANGHAI)
        count = rule["trading_days"]
        # Query actual exchange days; never infer holidays from weekdays.
        dates = self.trading_dates(code.rsplit(".", 1)[-1], (opened + dt.timedelta(days=1)).strftime("%Y%m%d"),
                                   (opened + dt.timedelta(days=count * 3 + 30)).strftime("%Y%m%d"))
        if len(dates) < count:
            raise ValueError("exchange calendar does not yet cover the requested holding period")
        day = dt.datetime.strptime(dates[count - 1], "%Y%m%d").date()
        return dt.datetime.combine(day, dt.time.fromisoformat(rule["exit_time"]), SHANGHAI).timestamp()
