"""Persistent execution tasks. All broker IO is injected; no account is opened here."""
import copy
import datetime as dt
import json
from .diagnostic_context import get_logger
import math
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from .diagnostics import quote_time_ms
from .batch_orders import batch_positive_id


ALGO_ACTIONS = frozenset("cftrader." + name for name in (
    "order_algo", "query_algo", "list_algos", "pause_algo", "resume_algo", "cancel_algo"))
TERMINAL = frozenset(("COMPLETED", "CANCELLED", "EXPIRED", "FAILED"))
CHILD_TERMINAL = frozenset(("FILLED", "CANCELLED", "REJECTED"))


def account_identity(account):
    return (str(account.get("account_id") or ""), str(account.get("account_type") or "STOCK"),
            str(account.get("bridge_id") or ""), str(account.get("account_key") or ""))


def positive(value, name, integer=False, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError("%s must be numeric" % name)
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError("%s must be numeric" % name)
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError("%s must be finite and %s" % (name, "nonnegative" if allow_zero else "positive"))
    if integer and number != int(number):
        raise ValueError("%s must be an integer" % name)
    return int(number) if integer else number


def elapsed_trading(windows, now):
    return sum(max(0.0, min(now, end) - start) for start, end in windows)


class AlgoStore:
    def __init__(self, path):
        self._owner_file = None
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            owner_file = open(path + ".lock", "a+b")
            try:
                if os.path.getsize(path + ".lock") == 0:
                    owner_file.write(b"0")
                    owner_file.flush()
                owner_file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(owner_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(owner_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                owner_file.close()
                raise RuntimeError("another algorithm runtime owns this task database")
            self._owner_file = owner_file
        self._lock = threading.RLock()
        self._db = None
        try:
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("CREATE TABLE IF NOT EXISTS algo_tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            self._db.commit()
        except BaseException:
            if self._db is not None:
                self._db.close()
            if self._owner_file is not None:
                self._owner_file.close()
            raise

    def save(self, task):
        payload = json.dumps(task, ensure_ascii=False, allow_nan=False)
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO algo_tasks VALUES (?, ?)", (task["algo_id"], payload))

    def load(self):
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute("SELECT payload FROM algo_tasks")]

    def close(self):
        with self._lock:
            self._db.close()
            if self._owner_file is not None:
                self._owner_file.close()
                self._owner_file = None


class AlgoEngine:
    def __init__(self, quotes, broker, store, clock=None):
        self.quotes, self.broker, self.store = quotes, broker, store
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._account_locks = {}
        self._leases = {}
        self._tasks = {task["algo_id"]: task for task in store.load()}
        self._stop = threading.Event()
        self._wake = getattr(getattr(quotes, "feed", None), "changed", None) or threading.Event()
        self._thread = None
        self._executor = None
        self._busy = set()
        for task in self._tasks.values():
            if task["status"] not in TERMINAL:
                task["recovering"] = True
                task["last_error"] = "Restored task; reconciling broker orders before continuing"

    def _account_lock(self, account):
        with self._lock:
            return self._account_locks.setdefault(account_identity(account), threading.RLock())

    def submit(self, params):
        params = copy.deepcopy(params)
        allowed = {"account", "stock_code", "order_type", "order_volume", "algo", "limit_price",
                   "duration_seconds", "interval_seconds", "max_quote_age", "child_timeout_seconds",
                   "max_child_volume", "price_mode", "participation_rate", "request_key", "start_time",
                   "end_time", "sessions", "price_tick", "min_child_volume", "volume_step",
                   "volume_multiplier", "volume_profile", "lookback_days", "strategy_name", "order_remark"}
        unknown = set(params) - allowed
        if unknown:
            raise ValueError("unknown algorithm parameters: " + ", ".join(sorted(unknown)))
        account = params.get("account")
        if not isinstance(account, dict) or not str(account.get("account_id") or "").strip():
            raise ValueError("account is required")
        algo = str(params.get("algo") or "").upper()
        if algo not in ("TWAP", "VWAP", "POV"):
            raise ValueError("algo must be TWAP, VWAP or POV")
        code = params.get("stock_code")
        if not isinstance(code, str) or "." not in code:
            raise ValueError("stock_code must include its market suffix")
        params["algo"] = algo
        params["order_type"] = positive(params.get("order_type"), "order_type", integer=True)
        params["order_volume"] = positive(params.get("order_volume"), "order_volume", integer=True)
        params["limit_price"] = positive(params.get("limit_price"), "limit_price")
        params["duration_seconds"] = positive(params.get("duration_seconds", 3600), "duration_seconds")
        params["interval_seconds"] = positive(params.get("interval_seconds", 60), "interval_seconds")
        params["max_quote_age"] = positive(params.get("max_quote_age", 15), "max_quote_age")
        params["child_timeout_seconds"] = positive(params.get("child_timeout_seconds", 60), "child_timeout_seconds")
        params["max_child_volume"] = positive(params.get("max_child_volume", params["order_volume"]), "max_child_volume", integer=True)
        params["price_mode"] = str(params.get("price_mode", "opponent"))
        if params["price_mode"] not in ("opponent", "passive", "limit"):
            raise ValueError("price_mode must be opponent, passive or limit")
        if algo == "POV":
            params["participation_rate"] = positive(params.get("participation_rate"), "participation_rate")
            if params["participation_rate"] > 1:
                raise ValueError("participation_rate must be at most 1")
        if "volume_profile" in params:
            profile = params["volume_profile"]
            if not isinstance(profile, (list, tuple)) or not profile:
                raise ValueError("volume_profile must be a nonempty list")
            params["volume_profile"] = [positive(value, "volume_profile", allow_zero=True) for value in profile]
            if not sum(params["volume_profile"]):
                raise ValueError("volume_profile must contain positive volume")
        request_key = str(params.get("request_key") or uuid.uuid4().hex)
        with self._account_lock(account):
            with self._lock:
                existing = next((row for row in self._tasks.values()
                                 if row["request_key"] == request_key and account_identity(row["account"]) == account_identity(account)), None)
            if existing:
                comparable = {key: value for key, value in params.items() if key != "request_key"}
                if comparable != existing["request"]:
                    raise ValueError("request_key already used for different algorithm parameters")
                return existing["algo_id"]
            prepared = self.broker.prepare(params, self.clock())
            windows = prepared["windows"]
            if not windows or any(start >= end for start, end in windows):
                raise ValueError("no valid trading window")
            if any(windows[i][1] > windows[i + 1][0] for i in range(len(windows) - 1)):
                raise ValueError("trading windows must not overlap")
            positive(prepared["volume_step"], "volume_step", integer=True)
            positive(prepared["min_child_volume"], "min_child_volume", integer=True)
            positive(prepared["price_tick"], "price_tick")
            positive(prepared["volume_multiplier"], "volume_multiplier")
            if params["max_child_volume"] < prepared["min_child_volume"]:
                raise ValueError("max_child_volume is smaller than the instrument minimum")
            if params["order_volume"] < prepared["min_child_volume"] or params["order_volume"] % prepared["volume_step"]:
                raise ValueError("order_volume does not satisfy the instrument quantity rules")
            if algo == "VWAP":
                profile = prepared.get("volume_profile") or params.get("volume_profile")
                if not isinstance(profile, (list, tuple)) or not profile:
                    raise ValueError("VWAP requires a historical or explicit volume_profile")
                profile = [positive(value, "volume_profile", allow_zero=True) for value in profile]
                if not sum(profile):
                    raise ValueError("volume_profile must contain positive volume")
                prepared["volume_profile"] = [value / sum(profile) for value in profile]
            task = dict(algo_id="algo_" + uuid.uuid4().hex, request_key=request_key, account=account,
                        request={key: value for key, value in params.items() if key != "request_key"},
                        config=dict(params, **prepared), status="WAITING_MARKET", children=[],
                        created_at=self.clock(), updated_at=self.clock(), filled_volume=0,
                        traded_amount=0.0, remaining_volume=params["order_volume"], reserved_volume=0,
                        last_error="", stop_reason=None, last_submit_at=None, recovering=False,
                        pov_baseline=None, pov_market_volume=0.0, quote_generation=None)
            self.store.save(task)
            with self._lock:
                self._tasks[task["algo_id"]] = task
            self._wake.set()
            return task["algo_id"]

    def query(self, algo_id, account):
        with self._lock:
            task = self._tasks.get(algo_id)
        if task is None or account_identity(task["account"]) != account_identity(account):
            raise ValueError("algorithm task not found for this account")
        with self._account_lock(account):
            result = copy.deepcopy(task)
            result["average_price"] = task["traded_amount"] / task["filled_volume"] if task["filled_volume"] else None
            return result

    def list(self, account):
        with self._lock:
            ids = [row["algo_id"] for row in self._tasks.values() if account_identity(row["account"]) == account_identity(account)]
        return [self.query(algo_id, account) for algo_id in ids]

    def control(self, algo_id, account, action):
        with self._account_lock(account):
            self.query(algo_id, account)
            task = self._tasks[algo_id]
            if task["status"] in TERMINAL:
                return copy.deepcopy(task)
            if action == "pause":
                if task.get("stop_reason"):
                    raise ValueError("cannot pause a task that is already stopping")
                task["status"] = "PAUSED"
            elif action == "resume":
                if task["status"] != "PAUSED":
                    raise ValueError("only a paused task can resume")
                task["status"] = "WAITING_MARKET"
                task["pov_baseline"] = None
            elif action == "cancel":
                task.update(status="CANCELLING", stop_reason="CANCELLED")
            else:
                raise ValueError("unknown algorithm control action")
            self._save(task)
            self._wake.set()
            return copy.deepcopy(task)

    def _save(self, task):
        task["updated_at"] = self.clock()
        self.store.save(task)

    def _reconcile(self, task):
        if not task["children"]:
            task["recovering"] = False
            return
        rows = self.broker.orders(task["account"], task["config"]["stock_code"])
        if not isinstance(rows, list):
            raise RuntimeError("broker order query did not return a list")
        for child in task["children"]:
            child["matched"] = False
            today = dt.datetime.fromtimestamp(self.clock(), dt.timezone(dt.timedelta(hours=8))).date()
            child_date = dt.datetime.fromtimestamp(child["created_at"], dt.timezone(dt.timedelta(hours=8))).date()
            matches = [row for row in rows if row.get("stock_code") == task["config"]["stock_code"]
                       and ((not row.get("order_remark") and child_date == today and child.get("order_id")
                             and str(row.get("order_id")) == str(child["order_id"]))
                            or row.get("order_remark") == child["remark"])]
            if len(matches) > 1:
                raise RuntimeError("ambiguous child order identity; execution is suspended")
            if not matches:
                if child["state"] not in CHILD_TERMINAL:
                    child["state"] = "UNKNOWN"
                continue
            row = matches[0]
            child["matched"] = True
            volume = int(row.get("traded_volume") or 0)
            if volume < 0 or volume > child["volume"]:
                raise RuntimeError("broker reported invalid child filled quantity")
            if volume < child["filled"]:
                continue
            child["filled"] = volume
            child["order_id"] = row.get("order_id") or child.get("order_id")
            child["traded_amount"] = float(row.get("traded_amount") or float(row.get("traded_price") or 0) * volume)
            status = int(row.get("order_status", 255))
            if volume == child["volume"]:
                child["state"] = "FILLED"
            elif status in (53, 54):
                child["state"] = "CANCELLED"
            elif status == 57:
                child["state"] = "REJECTED"
                task["last_error"] = str(row.get("status_msg") or "Child order rejected")
                task["stop_reason"] = "FAILED"
            elif child["state"] not in CHILD_TERMINAL and child["state"] != "CANCEL_PENDING":
                child["state"] = "WORKING"
        task["filled_volume"] = sum(child["filled"] for child in task["children"])
        task["traded_amount"] = sum(child.get("traded_amount", 0) for child in task["children"])
        task["reserved_volume"] = sum(child["volume"] - child["filled"] for child in task["children"]
                                      if child["state"] not in CHILD_TERMINAL)
        task["remaining_volume"] = task["config"]["order_volume"] - task["filled_volume"]
        if task["remaining_volume"] < task["reserved_volume"]:
            raise RuntimeError("parent quantity invariant violated")
        task["recovering"] = False

    def _cancel_children(self, task, now, all_children=False):
        for child in task["children"]:
            if child["state"] in CHILD_TERMINAL or not child.get("order_id") or not child.get("matched"):
                continue
            if not all_children and now - child["created_at"] < task["config"]["child_timeout_seconds"]:
                continue
            if child.get("cancel_at") is not None and now - child["cancel_at"] < 5:
                continue
            child.update(state="CANCEL_PENDING", cancel_at=now)
            self._save(task)
            try:
                result = self.broker.cancel(task["account"], child["order_id"], task["config"]["stock_code"])
                if result is False or (isinstance(result, (int, float)) and result < 0):
                    task["last_error"] = "Cancellation was rejected; waiting for broker reconciliation"
            except Exception as error:
                task["last_error"] = "Cancellation unconfirmed: %s" % error

    def _finish(self, task, status):
        task["status"] = status
        self._save(task)
        lease = self._leases.get(task["algo_id"])
        if lease is not None:
            self.quotes.release(lease)
            self._leases.pop(task["algo_id"], None)

    def step(self, algo_id):
        with self._lock:
            task = self._tasks[algo_id]
        with self._account_lock(task["account"]):
            if task["status"] in TERMINAL:
                lease = self._leases.get(algo_id)
                if lease is not None:
                    self.quotes.release(lease)
                    self._leases.pop(algo_id, None)
                return
            now, config = self.clock(), task["config"]
            self._reconcile(task)
            if task["filled_volume"] == config["order_volume"]:
                return self._finish(task, "COMPLETED")
            if now >= config["windows"][-1][1]:
                task["stop_reason"] = task.get("stop_reason") or "EXPIRED"
            stopping = bool(task.get("stop_reason"))
            self._cancel_children(task, now, stopping or task["status"] == "PAUSED")
            if stopping:
                if task["reserved_volume"] == 0:
                    return self._finish(task, task["stop_reason"])
                task["status"] = "CANCELLING"
                self._save(task)
                return
            if task["status"] == "PAUSED":
                self._save(task)
                return
            if algo_id not in self._leases:
                self._leases[algo_id] = self.quotes.acquire("algo:" + algo_id, [config["stock_code"]], purpose="algo")
            if not any(start <= now < end for start, end in config["windows"]):
                task["status"] = "WAITING_SESSION"
                self._save(task)
                return
            snapshot = self.quotes.snapshot(config["stock_code"], config["max_quote_age"])
            quote = snapshot["quote"] if snapshot else {}
            stamp = quote_time_ms(quote.get("time", quote.get("stime")))
            if not snapshot or stamp is None or now - stamp / 1000 > config["max_quote_age"] or stamp / 1000 > now + 3:
                task["status"] = "WAITING_MARKET"
                self._save(task)
                return
            target = self._target(task, snapshot, now)
            task["target_volume"] = target
            task["status"] = "RUNNING"
            if task["last_submit_at"] is not None and now - task["last_submit_at"] < config["interval_seconds"]:
                self._save(task)
                return
            # An unconfirmed submission/cancel reserves its entire remainder.
            # Do not chase around it even if the schedule has moved forward.
            if any(child["state"] in ("SUBMITTING", "UNKNOWN", "CANCEL_PENDING") for child in task["children"]):
                self._save(task)
                return
            available = min(target - task["filled_volume"] - task["reserved_volume"],
                            task["remaining_volume"] - task["reserved_volume"], config["max_child_volume"])
            volume = int(max(0, available) // config["volume_step"] * config["volume_step"])
            remaining_after = task["remaining_volume"] - task["reserved_volume"] - volume
            remaining = task["remaining_volume"] - task["reserved_volume"]
            if 0 < remaining_after < config["min_child_volume"] and remaining % config["volume_step"] == 0:
                volume -= config["min_child_volume"]
                volume = max(0, volume // config["volume_step"] * config["volume_step"])
            if volume < config["min_child_volume"]:
                self._save(task)
                return
            price = self._price(config, quote)
            if price is None:
                task["status"] = "WAITING_MARKET"
                self._save(task)
                return
            self.broker.check_capacity(task["account"], config, volume, price)
            child = dict(remark=algo_id + ":" + str(len(task["children"]) + 1), volume=volume,
                         filled=0, traded_amount=0, price=price, state="SUBMITTING", order_id=None, created_at=now)
            task["children"].append(child)
            task["reserved_volume"] += volume
            task["last_submit_at"] = now
            # Persist intent before sending. After a crash it is reconciled by
            # its unique remark; an absent response never causes a blind resend.
            self._save(task)
            try:
                order_id = self.broker.submit(task["account"], config, child)
                if not batch_positive_id(order_id):
                    child["state"] = "UNKNOWN"
                else:
                    child.update(order_id=order_id, state="WORKING")
            except Exception as error:
                if getattr(error, "dispatched", None) is False:
                    child["state"] = "REJECTED"
                    task["reserved_volume"] -= volume
                    task["stop_reason"] = "FAILED"
                else:
                    child["state"] = "UNKNOWN"
                task["last_error"] = str(error)
            self._save(task)

    def _target(self, task, snapshot, now):
        config = task["config"]
        total = config["order_volume"]
        elapsed = elapsed_trading(config["windows"], now)
        duration = sum(end - start for start, end in config["windows"])
        if config["algo"] == "TWAP":
            scheduled = (math.floor(elapsed / config["interval_seconds"]) + 1) * config["interval_seconds"]
            return min(total, total * scheduled / duration)
        if config["algo"] == "VWAP":
            profile = config["volume_profile"]
            index = min(len(profile), int(elapsed / duration * len(profile)) + 1)
            return min(total, total * sum(profile[:index]))
        volume = positive(snapshot["quote"].get("volume"), "market volume", allow_zero=True) * config["volume_multiplier"]
        baseline = task.get("pov_baseline")
        if baseline is None or task.get("quote_generation") != snapshot["generation"] or volume < baseline:
            task["pov_baseline"] = volume
            task["quote_generation"] = snapshot["generation"]
        else:
            task["pov_market_volume"] += volume - baseline
            task["pov_baseline"] = volume
        return min(total, task["pov_market_volume"] * config["participation_rate"])

    def _price(self, config, quote):
        buying = config["side"] == "buy"
        if config["price_mode"] == "limit":
            price = config["limit_price"]
        else:
            take_ask = buying if config["price_mode"] == "opponent" else not buying
            prices = quote.get("askPrice" if take_ask else "bidPrice") or []
            if not prices:
                return None
            price = prices[0]
        try:
            price = positive(price, "quote price")
        except ValueError:
            return None
        price = min(price, config["limit_price"]) if buying else max(price, config["limit_price"])
        price_tick = Decimal(str(config["price_tick"]))
        rounding = ROUND_DOWN if buying else ROUND_UP
        price = float((Decimal(str(price)) / price_tick).to_integral_value(rounding=rounding) * price_tick)
        if price <= 0:
            return None
        upper = config.get("upper_limit", 0)
        lower = config.get("lower_limit", 0)
        if (upper and price > upper) or (lower and price < lower):
            return None
        return price

    def start(self):
        with self._lock:
            if self._thread is not None:
                return
            self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cfquant-algo")
            self._thread = threading.Thread(target=self._run, name="cfquant-algo-scheduler", daemon=True)
            self._thread.start()

    def notify(self, event=None):
        self._wake.set()

    def _work(self, algo_id):
        try:
            self.step(algo_id)
        except Exception as error:
            task = self._tasks[algo_id]
            with self._account_lock(task["account"]):
                task["last_error"] = str(error)
                try:
                    self._save(task)
                except Exception:
                    # Persistence is a prerequisite for further order submission.
                    task["status"] = "PAUSED"
                    get_logger(__name__).exception("algorithm persistence failed")
        finally:
            with self._lock:
                self._busy.discard(algo_id)

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                for task in self._tasks.values():
                    algo_id = task["algo_id"]
                    if (task["status"] not in TERMINAL or algo_id in self._leases) and algo_id not in self._busy:
                        self._busy.add(algo_id)
                        self._executor.submit(self._work, algo_id)
            self._wake.wait(0.25)
            self._wake.clear()

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._executor:
            self._executor.shutdown(wait=True)
        for algo_id, lease in list(self._leases.items()):
            self.quotes.release(lease)
            self._leases.pop(algo_id, None)
        self.store.close()
