"""Existing cfquant account/market routes adapted to the execution engine."""
import datetime as dt
import math
import threading
import time

from .algo import positive
from .diagnostics import quote_time_ms
from .xttype import XtAsset, XtOrder, XtPosition
from .batch_orders import prepare_batch_orders, prepare_batch_cancels


class AlgoOrderRejected(RuntimeError):
    dispatched = False


SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def execution_time(value, default=None):
    if value is None:
        return default
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return positive(value, "execution time")
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value)
    if not isinstance(value, dt.datetime):
        raise ValueError("time must be an ISO date/time or Unix seconds")
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI)
    return value.timestamp()


def trading_windows(start, duration, end=None, sessions=None):
    date = dt.datetime.fromtimestamp(start, SHANGHAI).date()
    sessions = sessions or [("09:30", "11:30"), ("13:00", "14:57")]
    windows = []
    remaining = duration
    for first, last in sessions:
        a = dt.datetime.combine(date, dt.time.fromisoformat(first), SHANGHAI).timestamp()
        b = dt.datetime.combine(date, dt.time.fromisoformat(last), SHANGHAI).timestamp()
        if a >= b:
            raise ValueError("invalid trading session")
        a, b = max(a, start), min(b, end) if end is not None else b
        if a >= b:
            continue
        if end is None:
            b = min(b, a + remaining)
            remaining -= b - a
        windows.append([a, b])
        if end is None and remaining <= 0:
            break
    if not windows or (end is None and remaining > 0.001):
        raise ValueError("execution duration does not fit this trading day; choose an earlier start or shorter duration")
    return windows


class RoutedAlgoBroker:
    def __init__(self, trade_request, market_request):
        self.trade_request = trade_request
        self.market_request = market_request
        self._query_lock = threading.RLock()
        self._order_cache = {}

    def prepare(self, config, now):
        code = config["stock_code"]
        symbol, market = code.rsplit(".", 1)
        if market not in ("SH", "SZ", "BJ"):
            raise ValueError("this execution adapter currently supports SH/SZ/BJ securities")
        if config["order_type"] not in (23, 24):
            raise ValueError("this execution adapter supports ordinary buy/sell order types 23/24")
        if str(config["account"].get("account_type", "STOCK")) not in ("STOCK", "CREDIT", "2", "3"):
            raise ValueError("a stock or credit account is required")
        start = execution_time(config.get("start_time"), now)
        if start < now - 1:
            raise ValueError("start_time must not be in the past")
        end = execution_time(config.get("end_time"))
        date = dt.datetime.fromtimestamp(start, SHANGHAI).strftime("%Y%m%d")
        dates = self.market_request("xtdata.get_trading_dates", dict(market=market, start_time=date, end_time=date, count=-1))
        valid_dates = set()
        for value in dates if dates is not None else []:
            text = str(value).replace("-", "")
            stamp = quote_time_ms(value)
            if len(text) == 8 and text.isdigit():
                valid_dates.add(text)
            elif stamp is not None:
                valid_dates.add(dt.datetime.fromtimestamp(stamp / 1000, SHANGHAI).strftime("%Y%m%d"))
        if date not in valid_dates:
            raise ValueError("the execution date is not a trading day")
        instrument = self.market_request("xtdata.get_instrument_detail", dict(stock_code=code, iscomplete=True))
        if not isinstance(instrument, dict):
            raise ValueError("instrument metadata is unavailable")
        tick = positive(config.get("price_tick", instrument.get("PriceTick")), "price_tick")
        windows = trading_windows(start, config["duration_seconds"], end, config.get("sessions"))
        is_stock = symbol.startswith(("00", "30", "60", "68", "43", "83", "87", "88", "92"))
        if not is_stock and ("volume_step" not in config or "min_child_volume" not in config):
            raise ValueError("provide volume_step and min_child_volume for non-stock securities")
        minimum = 200 if market == "SH" and symbol.startswith(("688", "689")) else 100
        step = 1 if minimum == 200 or market == "BJ" else 100
        result = dict(windows=windows, side="buy" if config["order_type"] == 23 else "sell",
                      min_child_volume=positive(config.get("min_child_volume", minimum), "min_child_volume", integer=True),
                      volume_step=positive(config.get("volume_step", step), "volume_step", integer=True),
                      price_tick=tick, volume_multiplier=positive(config.get("volume_multiplier", 100), "volume_multiplier"),
                      upper_limit=float(instrument.get("UpStopPrice") or 0),
                      lower_limit=float(instrument.get("DownStopPrice") or 0))
        if config["algo"] == "VWAP" and not config.get("volume_profile"):
            result["volume_profile"] = self._historical_profile(config, windows, start)
        return result

    def _historical_profile(self, config, windows, start):
        import pandas as pd
        lookback = positive(config.get("lookback_days", 20), "lookback_days", integer=True)
        start_date = dt.datetime.fromtimestamp(start, SHANGHAI)
        data = self.market_request("xtdata.get_market_data_ex", dict(
            field_list=["volume"], stock_list=[config["stock_code"]], period="1m",
            start_time=(start_date - dt.timedelta(days=lookback * 3 + 7)).strftime("%Y%m%d"),
            end_time=(start_date - dt.timedelta(days=1)).strftime("%Y%m%d") + "235959",
            count=-1, dividend_type="none", fill_data=False))
        frame = data.get(config["stock_code"]) if isinstance(data, dict) else None
        if frame is None:
            raise ValueError("VWAP historical minute data unavailable; download history or provide volume_profile")
        frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
        if frame.empty or "volume" not in frame:
            raise ValueError("VWAP historical minute volumes are missing")
        times = frame["time"] if "time" in frame else frame.index
        rows = []
        for stamp, volume in zip(times, frame["volume"]):
            if isinstance(stamp, dt.datetime):
                date_time = stamp if stamp.tzinfo else stamp.replace(tzinfo=SHANGHAI)
            else:
                milliseconds = quote_time_ms(stamp)
                if milliseconds is None:
                    continue
                date_time = dt.datetime.fromtimestamp(milliseconds / 1000, SHANGHAI)
            if date_time.date() >= start_date.date():
                continue
            try:
                volume = positive(volume, "historical volume", allow_zero=True)
            except ValueError:
                continue
            rows.append((date_time.date(), date_time.hour * 3600 + date_time.minute * 60, volume))
        days = set(sorted(set(row[0] for row in rows))[-lookback:])
        total = sum(end - first for first, end in windows)
        count = max(1, int(math.ceil(total / config["interval_seconds"])))
        profile = [0.0] * count
        target_date = start_date.date()
        for day, seconds, volume in rows:
            if day not in days:
                continue
            stamp = dt.datetime.combine(target_date, dt.time(), SHANGHAI).timestamp() + seconds
            offset = 0.0
            for first, last in windows:
                # Minute bars contribute their overlap with the execution window.
                overlap_start, overlap_end = max(first, stamp), min(last, stamp + 60)
                if overlap_end > overlap_start:
                    first_bin = int((offset + overlap_start - first) / total * count)
                    last_bin = min(count - 1, int((offset + overlap_end - first - 1e-6) / total * count))
                    for index in range(first_bin, last_bin + 1):
                        left = max(offset + overlap_start - first, index * total / count)
                        right = min(offset + overlap_end - first, (index + 1) * total / count)
                        profile[index] += volume * max(0, right - left) / 60
                offset += last - first
        if not sum(profile):
            raise ValueError("no historical volumes overlap the execution window; provide volume_profile")
        return profile

    def orders(self, account, stock_code):
        key = (tuple(sorted(account.items())), stock_code.rsplit(".", 1)[-1])
        with self._query_lock:
            cached = self._order_cache.get(key)
            if cached and time.monotonic() - cached[0] < 0.5:
                return cached[1]
            rows = self.trade_request(account, "xttrader.query_stock_orders",
                                       {"account": account, "cancelable_only": False, "stock_code": stock_code})
            if not isinstance(rows, (list, tuple)):
                raise RuntimeError("invalid broker order query response")
            rows = [vars(XtOrder.from_any(row)) for row in rows]
            self._order_cache[key] = (time.monotonic(), rows)
            return rows

    def check_capacity(self, account, config, volume, price):
        if config["side"] == "buy":
            result = self.trade_request(account, "xttrader.query_stock_asset",
                                         {"account": account, "stock_code": config["stock_code"]})
            if isinstance(result, list):
                result = result[0] if result else None
            cash = getattr(XtAsset.from_any(result), "cash", None) if result is not None else None
            if cash is None or float(cash) < volume * price * 1.001:
                raise RuntimeError("insufficient available cash for algorithm child order including fee buffer")
        else:
            rows = self.trade_request(account, "xttrader.query_stock_positions",
                                       {"account": account, "stock_code": config["stock_code"]})
            positions = [XtPosition.from_any(row) for row in (rows or [])]
            available = sum(int(getattr(row, "can_use_volume", 0) or 0) for row in positions
                            if getattr(row, "stock_code", "") == config["stock_code"])
            if available < volume:
                raise RuntimeError("insufficient sellable position for algorithm child order")

    def submit(self, account, config, child):
        row = dict(stock_code=config["stock_code"], order_type=config["order_type"],
                   order_volume=child["volume"], price_type=11, price=child["price"],
                   strategy_name=config.get("strategy_name") or "cfquant_" + config["algo"], order_remark=child["remark"])
        rows = prepare_batch_orders([row], child["remark"], row["strategy_name"], child["remark"], False)
        result = self.trade_request(account, "cftrader.order_stock_batch",
                                    dict(account=account, batch_id=child["remark"], orders=rows, stop_on_error=False))
        response = result["results"][0]
        if response["status"] in ("failed", "skipped"):
            raise AlgoOrderRejected(response.get("error") or "child order rejected before submission")
        return response.get("order_id") if response["status"] == "submitted" else None

    def cancel(self, account, order_id, stock_code):
        batch_id = "algo_cancel_" + str(order_id)
        rows = prepare_batch_cancels([dict(order_id=order_id, stock_code=stock_code)], batch_id, False)
        result = self.trade_request(account, "cftrader.cancel_order_stock_batch",
                                    dict(account=account, batch_id=batch_id, cancels=rows, stop_on_error=False))
        response = result["results"][0]
        if response["status"] in ("failed", "skipped"):
            raise RuntimeError(response.get("error") or "child cancellation rejected")
        return response.get("cancel_result")
