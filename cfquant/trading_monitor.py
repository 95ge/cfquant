"""Passive trading telemetry. SQLite writes never run on a trading callback thread."""

import hashlib
import json
import math
import os
import queue
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8))
CALLBACKS = {"trader:on_stock_order": "order", "trader:on_stock_trade": "trade",
             "trader:on_order_error": "order_error", "trader:on_cancel_error": "cancel_error"}
CANCELED = {53, 54}  # 52 is a pending cancellation, not a confirmed cancellation.
_UNCHANGED = object()
DEFAULT_RUNTIME_RETENTION_DAYS = 30
MAX_RUNTIME_RETENTION_DAYS = 3650
RUNTIME_RETENTION_ALL = 0


def is_trading_time(timestamp=None):
    """Return whether a timestamp falls in a mainland China stock session."""
    value = time.time() if timestamp is None else number(timestamp, None)
    if value is None:
        return False
    current = datetime.fromtimestamp(value, SHANGHAI)
    if current.weekday() >= 5:
        return False
    minute = current.hour * 60 + current.minute
    return 570 <= minute < 690 or 780 <= minute < 900


def day_text(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp, SHANGHAI).strftime("%Y-%m-%d")


def number(value, default=0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError, OverflowError):
        return default


def identity(value):
    text = str(value or "").strip()
    return "" if text in ("0", "-1", "None") else text


def event_day(data, kind, received):
    fields = (("trade_date", "deal_date", "m_strTradeDate", "m_strDealDate") if kind == "trade"
              else ("order_date", "entrust_date", "m_strOrderDate", "m_strEntrustDate"))
    for field in ("trading_day", "m_strTradingDay") + fields:
        value = str(data.get(field) or "").replace("-", "")
        if len(value) == 8 and value.isdigit():
            try:
                return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                pass
    time_fields = (("traded_time", "trade_time", "m_strTradeTime", "m_nTradeTime") if kind == "trade"
                   else ("order_time", "entrust_time", "m_strOrderTime", "m_nOrderTime"))
    raw_time = next((data.get(field) for field in time_fields if data.get(field)), None)
    text = str(raw_time or "")
    if len(text) >= 10 and text[4:5] == "-":
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    if len(text) in (14, 17) and text.isdigit():
        try:
            return datetime.strptime(text[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d")
        except ValueError:
            pass
    value = number(raw_time)
    if value > 1e12:
        value /= 1000
    if 946684800 < value < 4102444800:
        return day_text(value)
    return day_text(received)


def monitored_request(action):
    return str(action).startswith(("xttrader.order_", "xttrader.cancel_", "cftrader.order_", "cftrader.cancel_"))


def request_failed(result):
    if isinstance(result, dict):
        if result.get("ok") is False or result.get("accepted") is False or number(result.get("failed")) > 0:
            return True
        if "cancel_result" in result and number(result["cancel_result"]) < 0:
            return True
        if "request_result" in result and request_failed(result["request_result"]):
            return True
        return False
    return result is False or (isinstance(result, (int, float)) and result < 0) or result == "-1"


class TradingMonitor:
    def __init__(self, path, queue_size=20000, settings_path=None, account_type_normalizer=None,
                 runtime_retention_days=DEFAULT_RUNTIME_RETENTION_DAYS):
        self.path = Path(path).resolve()
        self.settings_path = Path(settings_path).resolve() if settings_path else self.path.with_suffix('.settings.json')
        self.enabled = False
        self._queue = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self.dropped = 0
        self.last_error = ""
        self.last_saved_at = None
        self.account_keys = None  # None follows all current and future bindings.
        self._accounts = None  # Standalone collectors may have no binding registry.
        self._scope = (None, None)
        self._account_type = account_type_normalizer or (lambda value: str(value or '').strip().upper())
        self.runtime_retention_days = self._validate_retention_days(runtime_retention_days)
        self._last_runtime_cleanup = 0.0

    @staticmethod
    def _validate_keys(keys):
        if keys is not None and (not isinstance(keys, list) or
                any(not isinstance(key, str) or not key.strip() for key in keys)):
            raise ValueError('account_keys 必须为 null（全部账号）或绑定账号标识列表')
        return None if keys is None else sorted(set(keys))

    @staticmethod
    def _validate_retention_days(days):
        if type(days) is not int or not RUNTIME_RETENTION_ALL <= days <= MAX_RUNTIME_RETENTION_DAYS:
            raise ValueError('runtime_retention_days 必须为 1 到 %d 的整数，或为 0 表示全部保留' % MAX_RUNTIME_RETENTION_DAYS)
        return days

    def update_accounts(self, accounts):
        """Rebuild immutable lookup sets outside the trading path when bindings change."""
        with self._lifecycle_lock:
            self._accounts = {row['account_key']: dict(row) for row in accounts}
            self._rebuild_scope()

    def _rebuild_scope(self):
        if self._accounts is None:
            self._scope = (None, None) if self.account_keys is None else (frozenset(), frozenset())
            return
        identities, bridges = set(), set()
        selected = self._accounts if self.account_keys is None else self.account_keys
        for key in selected:
            row = self._accounts.get(key)
            if not row:
                continue
            for bridge in row.get('bridge_ids') or [row['bridge_id']]:
                identities.add((bridge, row['account_id'], row['account_type']))
                bridges.add(bridge)
        self._scope = (frozenset(identities), frozenset(bridges))

    def _accepts(self, bridge, account, account_type):
        identities = self._scope[0]
        return identities is None or (account_type not in (None, '') and
                (str(bridge or ''), str(account or ''), self._account_type(account_type)) in identities)

    def settings(self):
        with self._lifecycle_lock:
            return dict(self.health(), accounts=list((self._accounts or {}).values()))

    def start(self):
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError("监控仍在保存待写入记录，请稍后再开启")
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="cfquant-monitor-db", daemon=True)
            self._thread.start()
            self.enabled = True

    def close(self):
        with self._lifecycle_lock:
            with self._lock:
                self.enabled = False
                self._stop.set()
            if self._thread:
                self._thread.join(10)

    def restore(self):
        """Opt in only when an explicit saved boolean enables collection."""
        try:
            saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if not isinstance(saved, dict) or type(saved.get('enabled')) is not bool:
                raise ValueError('invalid enabled setting')
            keys = self._validate_keys(saved.get('account_keys'))
            retention_days = self._validate_retention_days(
                saved.get('runtime_retention_days', DEFAULT_RUNTIME_RETENTION_DAYS))
            if saved['enabled'] and keys == []:
                raise ValueError('enabled scope cannot be empty')
        except FileNotFoundError:
            return self.health()
        except (ValueError, OSError) as error:
            self.last_error = "监控设置无法读取，已保持关闭：%s" % error
            return self.health()
        with self._lifecycle_lock:
            self.account_keys = keys
            self.runtime_retention_days = retention_days
            self._last_runtime_cleanup = 0.0
            self._rebuild_scope()
            if saved['enabled']:
                self.start()
        return self.health()

    def configure(self, enabled, account_keys=_UNCHANGED, runtime_retention_days=_UNCHANGED):
        if type(enabled) is not bool:
            raise ValueError('enabled 必须为 true 或 false')
        with self._lifecycle_lock:
            keys = self.account_keys if account_keys is _UNCHANGED else self._validate_keys(account_keys)
            retention_days = (self.runtime_retention_days if runtime_retention_days is _UNCHANGED
                              else self._validate_retention_days(runtime_retention_days))
            if account_keys is not _UNCHANGED and keys is not None and self._accounts is not None:
                if set(keys) - self._accounts.keys():
                    raise ValueError('所选账号绑定已变更，请重新打开设置后选择')
            if enabled and keys is not None and not keys:
                raise ValueError('请至少选择一个已绑定的 QMT 账号，或选择全部账号')
            if enabled and self._thread and self._thread.is_alive() and self._stop.is_set():
                raise RuntimeError("监控仍在保存待写入记录，请稍后再开启")
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(self.settings_path.parent),
                                                 prefix='.monitor-', suffix='.tmp', delete=False) as stream:
                    temporary = stream.name
                    json.dump({'enabled': enabled, 'account_keys': keys,
                               'runtime_retention_days': retention_days}, stream)
                os.replace(temporary, str(self.settings_path))
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            self.account_keys = keys
            self.runtime_retention_days = retention_days
            self._last_runtime_cleanup = 0.0
            self._rebuild_scope()
            if enabled:
                self.start()
            else:
                self.close()
            return self.health()

    def health(self):
        return {"enabled": self.enabled, "account_keys": self.account_keys,
                "running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
                "draining": bool(self._thread and self._thread.is_alive() and self._stop.is_set()),
                "pending": self._queue.unfinished_tasks, "dropped": self.dropped,
                "error": self.last_error, "last_saved_at": self.last_saved_at,
                "database": self.path.name, "runtime_retention_days": self.runtime_retention_days}

    def _submit(self, kind, data):
        if not self.enabled:
            return
        with self._lock:
            if not self.enabled:
                return
            try:
                self._queue.put_nowait((kind, data))
            except queue.Full:
                self.dropped += 1

    def record_callback(self, event):
        if not self.enabled:
            return
        kind = CALLBACKS.get(event.get("event"))
        data = event.get("data")
        if kind and isinstance(data, dict):
            if self._scope[0] is not None:
                meta = event.get('meta') if isinstance(event.get('meta'), dict) else {}
                bridge = event.get('bridge_id') or meta.get('bridge_id')
                account = event.get('account_id') or data.get('account_id')
                account_type = event.get('account_type') or data.get('account_type')
                if not self._accepts(bridge, account, account_type):
                    return
                event = dict(event, bridge_id=bridge, account_id=account,
                             account_type=self._account_type(account_type))
            # Copy the event before the caller can mutate it; persist only selected fields.
            self._submit("callback", (kind, dict(event, data=dict(data))))

    def record_request(self, bridge, action, params, elapsed_ms, result=None, error=None):
        if not self.enabled or not monitored_request(action):
            return
        account = params.get("account") or params.get("account_id") or ""
        account_type = params.get("account_type") or ""
        if isinstance(account, dict):
            account_type = account.get("account_type") or account_type
            account = account.get("account_id") or ""
        if not self._accepts(bridge, account, account_type):
            return
        failed = error is not None or request_failed(result)
        order_id = identity(params.get("order_id"))
        if not order_id and isinstance(result, dict):
            order_id = identity(result.get("order_id"))
        self._submit("request", {"bridge_id": str(bridge or ""), "account_id": str(account),
            "account_type": str(account_type), "action": action, "latency_ms": number(elapsed_ms, None),
            "failed": bool(failed), "message": str(error or ("请求返回失败，请检查回调" if failed else ""))[:1000],
            "received_at": time.time(), "order_id": order_id,
            "symbol": str(params.get("stock_code") or "")})

    def record_snapshot(self, snapshot):
        if not self.enabled:
            return
        bridges = self._scope[1]
        if bridges is not None and snapshot.get('bridge_id') not in bridges:
            return
        self._submit("snapshot", snapshot)

    def flush(self, timeout=5):
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(.01)
        return self._queue.unfinished_tasks == 0

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS monitor_events (
                id INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
                trade_date TEXT NOT NULL, received_at REAL NOT NULL,
                bridge_id TEXT NOT NULL, account_id TEXT NOT NULL, account_type TEXT NOT NULL,
                kind TEXT NOT NULL, order_id TEXT NOT NULL, symbol TEXT NOT NULL,
                status INTEGER, volume REAL NOT NULL DEFAULT 0, amount REAL NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '', latency_ms REAL, failed INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS monitor_events_date ON monitor_events(trade_date, bridge_id, account_id);
            CREATE INDEX IF NOT EXISTS monitor_events_time ON monitor_events(received_at);
            CREATE INDEX IF NOT EXISTS monitor_events_order ON monitor_events(trade_date,bridge_id,account_id,account_type,symbol,order_id,kind);
            CREATE TABLE IF NOT EXISTS monitor_orders (
                order_key TEXT PRIMARY KEY, trade_date TEXT NOT NULL, bridge_id TEXT NOT NULL,
                account_id TEXT NOT NULL, account_type TEXT NOT NULL, order_id TEXT NOT NULL,
                symbol TEXT NOT NULL, first_seen REAL NOT NULL, canceled_at REAL,
                filled INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS monitor_orders_date ON monitor_orders(trade_date, bridge_id, account_id);
            CREATE TABLE IF NOT EXISTS monitor_nodes (
                id INTEGER PRIMARY KEY, bridge_id TEXT NOT NULL, name TEXT NOT NULL, mode TEXT NOT NULL,
                channel TEXT NOT NULL, checked_at REAL NOT NULL, online INTEGER NOT NULL,
                latency_ms REAL, message TEXT NOT NULL, interval_seconds REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS monitor_nodes_time ON monitor_nodes(checked_at, bridge_id);
            CREATE INDEX IF NOT EXISTS monitor_nodes_identity ON monitor_nodes(bridge_id, mode, channel, checked_at);
            CREATE TABLE IF NOT EXISTS monitor_runtime_samples (
                runtime_key TEXT PRIMARY KEY, sampled_at REAL NOT NULL, sample_minute INTEGER NOT NULL,
                bridge_id TEXT NOT NULL, name TEXT NOT NULL, mode TEXT NOT NULL,
                normal_json TEXT NOT NULL, trade_json TEXT NOT NULL, process_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS monitor_runtime_time ON monitor_runtime_samples(sampled_at, bridge_id);
            CREATE INDEX IF NOT EXISTS monitor_runtime_identity ON monitor_runtime_samples(bridge_id, sample_minute);
            CREATE TABLE IF NOT EXISTS monitor_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        if "performance_json" not in {row[1] for row in conn.execute("PRAGMA table_info(monitor_nodes)")}:
            conn.execute("ALTER TABLE monitor_nodes ADD COLUMN performance_json TEXT NOT NULL DEFAULT '{}'")
        conn.execute("INSERT OR IGNORE INTO monitor_meta VALUES ('started_at', ?)", (str(time.time()),))
        conn.commit()
        return conn

    def _run(self):
        conn, batch = None, []
        try:
            while not self._stop.is_set() or batch or not self._queue.empty():
                try:
                    if conn is None:
                        conn = self._connect()
                    if not batch:
                        try:
                            batch.append(self._queue.get(timeout=.2))
                        except queue.Empty:
                            continue
                        while len(batch) < 500:
                            try:
                                batch.append(self._queue.get_nowait())
                            except queue.Empty:
                                break
                    malformed = 0
                    with conn:
                        conn.execute("BEGIN")
                        for kind, data in batch:
                            conn.execute("SAVEPOINT monitor_item")
                            try:
                                if kind == "callback":
                                    self._write_callback(conn, *data)
                                elif kind == "request":
                                    self._write_request(conn, data)
                                else:
                                    self._write_snapshot(conn, data)
                            except (sqlite3.Error, OSError):
                                raise
                            except Exception:
                                conn.execute("ROLLBACK TO monitor_item")
                                malformed += 1
                            finally:
                                conn.execute("RELEASE monitor_item")
                    with self._lock:
                        self.dropped += malformed
                    self.last_saved_at, self.last_error = time.time(), ""
                    for _ in batch:
                        self._queue.task_done()
                    batch = []
                except (sqlite3.Error, OSError) as error:
                    self.last_error = "监控数据保存失败：%s" % error
                    if conn:
                        conn.close()
                    conn = None
                    if self._stop.is_set():
                        time.sleep(1)  # Keep accepted records while a disabled collector drains.
                    else:
                        self._stop.wait(1)
                except Exception as error:
                    # A malformed event must not kill the collector or block later events.
                    self.last_error = "监控事件处理失败：%s" % error
                    with self._lock:
                        self.dropped += len(batch)
                    for _ in batch:
                        self._queue.task_done()
                    batch = []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def _insert(conn, row):
        columns = tuple(row)
        return conn.execute("INSERT OR IGNORE INTO monitor_events (%s) VALUES (%s)" %
                            (",".join(columns), ",".join("?" for _ in columns)), tuple(row.values())).rowcount

    def _write_callback(self, conn, kind, event):
        data = event["data"]
        received = number(event.get("received_at"), time.time())
        # Reuse the bridge's QMT/MiniQMT field aliases without depending on local timezone conversion.
        from .xttype import XtOrder, XtTrade, XtOrderError, XtCancelError
        raw = data
        converter = {"order": XtOrder, "trade": XtTrade, "order_error": XtOrderError, "cancel_error": XtCancelError}[kind]
        data = vars(converter.from_any(data))
        trade_date = event_day(raw, kind, received)
        bridge = str(event.get("bridge_id") or (event.get("meta") or {}).get("bridge_id") or "")
        account = str(event.get("account_id") or data.get("account_id") or "")
        account_type = str(event.get("account_type") or data.get("account_type") or "STOCK")
        order_id = identity(data.get("order_id")) or identity(data.get("order_sysid"))
        symbol = str(data.get("stock_code") or "")
        status = int(number(data.get("order_status"), -1))
        volume = number(data.get("traded_volume"))
        message = str(data.get("error_msg") or data.get("status_msg") or data.get("message") or "")[:1000]
        order_parts = (trade_date, bridge, account, account_type, symbol, order_id)
        order_key = json.dumps(order_parts, ensure_ascii=False)
        trade_id = identity(data.get("traded_id"))
        if kind == "trade" and trade_id:
            parts = (trade_date, bridge, account, account_type, symbol, kind, trade_id)
        else:
            parts = (*order_parts, kind, status, volume, message, data.get("traded_time") if kind == "trade" else None,
                     data.get("traded_price") if kind == "trade" else None, data.get("error_id"))
        if not order_id and not trade_id:
            # No business identity: identical callbacks cannot safely be deduplicated.
            parts = (*parts, uuid.uuid4().hex)
        key = hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
        row = {"event_key": key, "trade_date": trade_date, "received_at": received, "bridge_id": bridge,
               "account_id": account, "account_type": account_type, "kind": kind, "order_id": order_id,
               "symbol": symbol, "status": status, "volume": volume,
               "amount": number(data.get("traded_amount")) if kind == "trade" else 0,
               "message": message, "failed": int(kind.endswith("error") or (kind == "order" and status == 57))}
        if not self._insert(conn, row):
            return
        if kind == "order" and order_id:
            canceled_at = received if status in CANCELED else None
            has_trade = conn.execute("SELECT 1 FROM monitor_events WHERE trade_date=? AND bridge_id=? AND account_id=? AND account_type=? AND symbol=? AND order_id=? AND kind='trade' LIMIT 1", order_parts).fetchone()
            conn.execute("""INSERT INTO monitor_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(order_key) DO UPDATE SET
                canceled_at=COALESCE(monitor_orders.canceled_at, excluded.canceled_at),
                filled=MAX(monitor_orders.filled, excluded.filled),
                rejected=MAX(monitor_orders.rejected, excluded.rejected)""",
                (order_key, trade_date, bridge, account, account_type, order_id, symbol, received,
                 canceled_at, int(volume > 0 or status == 56 or bool(has_trade)), int(status == 57)))
        elif kind == "trade" and order_id:
            conn.execute("UPDATE monitor_orders SET filled=1 WHERE order_key=?", (order_key,))

    def _write_request(self, conn, data):
        row = dict(data)
        if row.get('account_type'):
            row['account_type'] = self._account_type(row['account_type'])
        action = row.pop("action")
        row.update(event_key=uuid.uuid4().hex, trade_date=day_text(row["received_at"]),
                   kind="cancel_request" if ".cancel_" in action else "order_request")
        self._insert(conn, row)

    def _write_snapshot(self, conn, snapshot):
        monitor = snapshot.get("monitor") or {}
        checked_at = number(snapshot.get("checked_at"), time.time())
        normal = snapshot.get("normal") or {}
        trade = snapshot.get("trade") or {}
        for channel in ("normal", "trade"):
            item = snapshot.get(channel) or {}
            # Pipe status is a connectivity observation; its file-read time is not QMT RTT.
            conn.execute("INSERT INTO monitor_nodes (bridge_id,name,mode,channel,checked_at,online,latency_ms,message,interval_seconds,performance_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(snapshot.get("bridge_id") or ""), str(snapshot.get("bridge_name") or ""),
                 str(monitor.get("transport_mode") or ""), channel, checked_at,
                 int(bool(item.get("online"))),
                 None if monitor.get("transport_mode") == "ctypes" else number(item.get("latency_ms"), None),
                 str(item.get("error") or "")[:1000], number(monitor.get("interval_seconds"), 10),
                 json.dumps(item.get("performance") or {}, ensure_ascii=True)))
        # Runtime diagnostics are useful outside trading hours too: they show
        # whether the QMT bridge, process and pipes remain healthy while idle.
        # Keep one sample per minute so all-day collection remains bounded.
        bridge_id = str(snapshot.get("bridge_id") or "")
        mode = str(monitor.get("transport_mode") or "")
        sample_minute = int(checked_at // 60) * 60
        runtime_key = "%s|%s|%d" % (bridge_id, mode, sample_minute)
        normal_performance = normal.get("performance") or {}
        trade_performance = trade.get("performance") or {}
        conn.execute("""INSERT INTO monitor_runtime_samples
            (runtime_key,sampled_at,sample_minute,bridge_id,name,mode,normal_json,trade_json,process_json)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(runtime_key) DO UPDATE SET
            sampled_at=excluded.sampled_at, name=excluded.name,
            normal_json=excluded.normal_json, trade_json=excluded.trade_json,
            process_json=excluded.process_json""",
            (runtime_key, checked_at, sample_minute, bridge_id,
             str(snapshot.get("bridge_name") or ""), mode,
             json.dumps(normal_performance, ensure_ascii=True),
             json.dumps(trade_performance, ensure_ascii=True),
             json.dumps({"normal": normal_performance.get("process") or {},
                         "trade": trade_performance.get("process") or {}}, ensure_ascii=True)))
        # Cleanup is checked on every status snapshot, including while idle,
        # so expired history does not wait for a trading session.
        self._cleanup_runtime_samples(conn)

    def _cleanup_runtime_samples(self, conn, force=False):
        now = time.monotonic()
        if not force and now - self._last_runtime_cleanup < 3600:
            return
        if self.runtime_retention_days == RUNTIME_RETENTION_ALL:
            self._last_runtime_cleanup = now
            return
        cutoff = time.time() - self.runtime_retention_days * 86400
        conn.execute("DELETE FROM monitor_runtime_samples WHERE sampled_at < ?", (cutoff,))
        self._last_runtime_cleanup = now

    @staticmethod
    def _runtime_dates(start, end, now, max_days=31, allow_all=False):
        all_history = allow_all and str(start or '').strip().lower() in ('all', '*', 'history')
        if all_history:
            end = end or day_text(now)
            try:
                finish = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=SHANGHAI) + timedelta(days=1)
            except (ValueError, TypeError):
                raise ValueError("日期格式应为 YYYY-MM-DD")
            if end != (finish - timedelta(days=1)).strftime("%Y-%m-%d"):
                raise ValueError("日期格式应为 YYYY-MM-DD")
            return "all", end, datetime(1970, 1, 1, tzinfo=SHANGHAI), finish
        start, end = start or day_text(now), end or start or day_text(now)
        try:
            begin = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=SHANGHAI)
            finish = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=SHANGHAI) + timedelta(days=1)
        except (ValueError, TypeError):
            raise ValueError("日期格式应为 YYYY-MM-DD")
        if start != begin.strftime("%Y-%m-%d") or end != (finish - timedelta(days=1)).strftime("%Y-%m-%d"):
            raise ValueError("日期格式应为 YYYY-MM-DD")
        if not 0 < (finish - begin).days <= max_days:
            raise ValueError("开始日期不能晚于结束日期，单次最多查询 %d 天" % max_days)
        return start, end, begin, finish

    def query_runtime(self, start=None, end=None, bridge_id="", mode="", limit=5000, now=None, minutes=None):
        now = time.time() if now is None else now
        if minutes is not None:
            if isinstance(minutes, bool) or not str(minutes).isascii() or not str(minutes).isdigit():
                raise ValueError("最近分钟数必须为正整数")
            minutes = int(minutes)
            if not 1 <= minutes <= MAX_RUNTIME_RETENTION_DAYS * 1440:
                raise ValueError("最近分钟数须在 1 至 %d 之间" % (MAX_RUNTIME_RETENTION_DAYS * 1440))
            finish = datetime.fromtimestamp(now, SHANGHAI)
            begin = finish - timedelta(minutes=minutes)
            start, end = begin.isoformat(timespec='seconds'), finish.isoformat(timespec='seconds')
        else:
            start, end, begin, finish = self._runtime_dates(
                start, end, now, max_days=MAX_RUNTIME_RETENTION_DAYS, allow_all=True)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError("limit 必须为整数")
        if not 1 <= limit <= 10000:
            raise ValueError("limit 超出范围")
        result = {"start": start, "end": end, "timezone": "Asia/Shanghai", "bridge_id": str(bridge_id or ""),
                  "mode": str(mode or ""),
                  "samples": [], "retention_days": self.runtime_retention_days, "generated_at": now}
        if minutes is not None:
            result.update(minutes=minutes, window_start=begin.timestamp(), window_end=finish.timestamp())
        if not self.path.exists():
            return result
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_runtime_samples'").fetchone():
                return result
            clauses = ["sampled_at>=?", "sampled_at<=?" if minutes is not None else "sampled_at<?"]
            args = [begin.timestamp(), finish.timestamp()]
            if bridge_id:
                clauses.append("bridge_id=?")
                args.append(str(bridge_id))
            if mode:
                clauses.append("mode=?")
                args.append(str(mode))
            rows = conn.execute("SELECT * FROM monitor_runtime_samples WHERE %s ORDER BY sampled_at DESC LIMIT ?" %
                                " AND ".join(clauses), args + [limit]).fetchall()
            samples = []
            for row in reversed(rows):
                item = dict(row)
                for source, target in (("normal_json", "normal"), ("trade_json", "trade"), ("process_json", "process")):
                    try:
                        item[target] = json.loads(item.pop(source) or "{}")
                    except (ValueError, TypeError):
                        item[target] = {}
                samples.append(item)
            result["samples"] = samples
            return result
        finally:
            conn.close()

    def clear_runtime_history(self, scope="all"):
        """Delete persisted runtime samples without touching trading records."""
        scope = str(scope or "all").strip().lower()
        if scope not in ("all", "expired"):
            raise ValueError("scope 必须为 all 或 expired")
        if not self.path.exists():
            return {"scope": scope, "deleted": 0, "remaining": 0,
                    "retention_days": self.runtime_retention_days, "vacuumed": False}
        if not self.flush(timeout=10):
            raise RuntimeError("运行时序仍有待写入记录，请稍后重试")
        conn = sqlite3.connect(str(self.path), timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_runtime_samples'").fetchone():
                return {"scope": scope, "deleted": 0, "remaining": 0,
                        "retention_days": self.runtime_retention_days, "vacuumed": False}
            if scope == "expired":
                if self.runtime_retention_days == RUNTIME_RETENTION_ALL:
                    remaining = conn.execute("SELECT COUNT(*) FROM monitor_runtime_samples").fetchone()[0]
                    return {"scope": scope, "deleted": 0, "remaining": remaining,
                            "retention_days": self.runtime_retention_days, "vacuumed": False}
                cutoff = time.time() - self.runtime_retention_days * 86400
                cursor = conn.execute("DELETE FROM monitor_runtime_samples WHERE sampled_at < ?", (cutoff,))
            else:
                cursor = conn.execute("DELETE FROM monitor_runtime_samples")
            deleted = max(0, int(cursor.rowcount or 0))
            conn.commit()
            vacuumed = False
            if scope == "all" and deleted:
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.execute("VACUUM")
                    vacuumed = True
                except sqlite3.Error:
                    # Deletion is complete even if compaction is temporarily locked.
                    pass
            remaining = conn.execute("SELECT COUNT(*) FROM monitor_runtime_samples").fetchone()[0]
            self._last_runtime_cleanup = time.monotonic()
            return {"scope": scope, "deleted": deleted, "remaining": remaining,
                    "retention_days": self.runtime_retention_days, "vacuumed": vacuumed}
        finally:
            conn.close()

    def query(self, start=None, end=None, bridge_id="", account_id="", account_type="", kind="", page=1, now=None):
        now = time.time() if now is None else now
        start, end = start or day_text(now), end or start or day_text(now)
        try:
            begin = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=SHANGHAI)
            finish = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=SHANGHAI) + timedelta(days=1)
        except (ValueError, TypeError):
            raise ValueError("日期格式应为 YYYY-MM-DD")
        if start != begin.strftime("%Y-%m-%d") or end != (finish - timedelta(days=1)).strftime("%Y-%m-%d"):
            raise ValueError("日期格式应为 YYYY-MM-DD")
        if not 0 < (finish - begin).days <= 31:
            raise ValueError("开始日期不能晚于结束日期，单次最多查询 31 天")
        page = int(page)
        if not 1 <= page <= 1000000:
            raise ValueError("页码超出范围")
        if kind not in ("", "order", "trade", "abnormal", "order_request", "cancel_request"):
            raise ValueError("不支持的事件类型")
        clauses, args = ["trade_date BETWEEN ? AND ?"], [start, end]
        for field, value in (("bridge_id", bridge_id), ("account_id", account_id), ("account_type", account_type)):
            if value:
                clauses.append(field + "=?")
                args.append(value)
        where = " AND ".join(clauses)
        live = start <= day_text(now) <= end
        step = max(60, math.ceil((finish - begin).total_seconds() / 1440 / 60) * 60)
        if not self.path.exists():
            return self._empty_result(start, end, page, now, live, step)
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN")  # All panels use one consistent WAL snapshot.
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_meta'").fetchone():
                return self._empty_result(start, end, page, now, live, step)
            orders = dict(conn.execute("""SELECT COUNT(*) order_count, COALESCE(SUM(filled),0) filled_order_count,
                COALESCE(SUM(rejected),0) rejected_count, COUNT(canceled_at) canceled_count
                FROM monitor_orders WHERE """ + where, args).fetchone())
            stats = dict(conn.execute("""SELECT COUNT(CASE WHEN kind='trade' THEN 1 END) trade_count,
                COALESCE(SUM(CASE WHEN kind='trade' THEN amount END),0) traded_amount,
                COUNT(CASE WHEN kind IN ('order_error','cancel_error') THEN 1 END) error_count,
                COUNT(CASE WHEN kind IN ('order_request','cancel_request') THEN 1 END) request_count,
                COUNT(CASE WHEN kind IN ('order_request','cancel_request') AND failed=1 THEN 1 END) failed_request_count,
                COUNT(CASE WHEN kind='cancel_request' THEN 1 END) cancel_request_count
                FROM monitor_events WHERE """ + where, args).fetchone())
            stats.update(orders)
            denominator = stats["order_count"]
            stats["fill_ratio"] = stats["filled_order_count"] / denominator if denominator else None
            stats["cancel_ratio"] = stats["canceled_count"] / denominator if denominator else None
            stats["report_cancel_ratio"] = denominator / stats["canceled_count"] if stats["canceled_count"] else None
            stats["abnormal_count"] = stats["rejected_count"] + stats["error_count"] + stats["failed_request_count"]
            latencies = conn.execute("SELECT COUNT(*), AVG(latency_ms), MAX(latency_ms) FROM monitor_events WHERE " + where + " AND latency_ms IS NOT NULL", args).fetchone()
            count = latencies[0]
            p95 = conn.execute("SELECT latency_ms FROM monitor_events WHERE " + where + " AND latency_ms IS NOT NULL ORDER BY latency_ms LIMIT 1 OFFSET ?", args + [max(0, math.ceil(count * .95) - 1)]).fetchone() if count else None
            stats["latency"] = {"count": count, "avg_ms": latencies[1], "max_ms": latencies[2], "p95_ms": p95[0] if p95 else None}
            stats["order_rate"] = conn.execute("SELECT COUNT(*) FROM monitor_orders WHERE " + where + " AND first_seen>? AND first_seen<=?", args + [now - 60, now]).fetchone()[0] / 60 if live and self.enabled else None
            stats["trade_rate"] = conn.execute("SELECT COUNT(*) FROM monitor_events WHERE " + where + " AND kind='trade' AND received_at>? AND received_at<=?", args + [now - 60, now]).fetchone()[0] / 60 if live and self.enabled else None
            series = {}
            for source, stamp, label, extra in (("monitor_orders", "first_seen", "orders", ""),
                    ("monitor_orders", "canceled_at", "cancels", " AND canceled_at IS NOT NULL"),
                    ("monitor_events", "received_at", "trades", " AND kind='trade'")):
                for row in conn.execute("SELECT CAST(%s / ? AS INTEGER)*? bucket, COUNT(*) count FROM %s WHERE %s%s AND %s>=? AND %s<? GROUP BY bucket" %
                        (stamp, source, where, extra, stamp, stamp), [step, step] + args + [begin.timestamp(), finish.timestamp()]):
                    series.setdefault(row["bucket"], {"time": row["bucket"], "orders": 0, "trades": 0, "cancels": 0})[label] = row["count"]
            event_where = where + (" AND failed=1" if kind == "abnormal" else " AND kind=?" if kind else "")
            event_args = args + ([kind] if kind and kind != "abnormal" else [])
            total = conn.execute("SELECT COUNT(*) FROM monitor_events WHERE " + event_where, event_args).fetchone()[0]
            events = [dict(row) for row in conn.execute("SELECT * FROM monitor_events WHERE " + event_where + " ORDER BY received_at DESC,id DESC LIMIT 50 OFFSET ?", event_args + [(page - 1) * 50])]
            for event in events:
                event.pop("event_key", None)
            node_args = [begin.timestamp(), finish.timestamp()]
            node_where = "checked_at>=? AND checked_at<?"
            if bridge_id:
                node_where += " AND bridge_id=?"
                node_args.append(bridge_id)
            nodes = [dict(row) for row in conn.execute("SELECT * FROM monitor_nodes WHERE id IN (SELECT MAX(id) FROM monitor_nodes WHERE " + node_where + " GROUP BY bridge_id,mode,channel)", node_args)]
            scope_bridges = self._scope[1]
            for node in nodes:
                try:
                    node["performance"] = json.loads(node.pop("performance_json", "{}"))
                except (ValueError, TypeError):
                    node["performance"] = {}
                node["stale"] = bool(live and now - node["checked_at"] > max(30, node["interval_seconds"] * 3))
                node['collecting'] = bool(self.enabled and (scope_bridges is None or node['bridge_id'] in scope_bridges))
            options = [dict(row) for row in conn.execute("SELECT DISTINCT bridge_id,account_id,account_type FROM monitor_events WHERE trade_date BETWEEN ? AND ? ORDER BY bridge_id,account_id", [start, end])]
            started = conn.execute("SELECT value FROM monitor_meta WHERE key='started_at'").fetchone()
            return {"start": start, "end": end, "live": live, "timezone": "Asia/Shanghai", "stats": stats,
                    "series": sorted(series.values(), key=lambda item: item["time"]), "bucket_seconds": step,
                    "nodes": nodes, "events": events, "total": total, "page": page, "page_size": 50,
                    "options": options, "collector": self.health(), "started_at": float(started[0]) if started else None,
                    "generated_at": now}
        finally:
            conn.close()

    def _empty_result(self, start, end, page, now, live, step):
        stats = dict.fromkeys(('order_count', 'filled_order_count', 'rejected_count', 'canceled_count',
            'trade_count', 'traded_amount', 'error_count', 'request_count', 'failed_request_count',
            'cancel_request_count', 'abnormal_count'), 0)
        stats.update(fill_ratio=None, cancel_ratio=None, report_cancel_ratio=None,
                     order_rate=None, trade_rate=None,
                     latency={'count': 0, 'avg_ms': None, 'max_ms': None, 'p95_ms': None})
        return {'start': start, 'end': end, 'live': live, 'timezone': 'Asia/Shanghai', 'stats': stats,
                'series': [], 'bucket_seconds': step, 'nodes': [], 'events': [], 'total': 0,
                'page': page, 'page_size': 50, 'options': [], 'collector': self.health(),
                'started_at': None, 'generated_at': now}
