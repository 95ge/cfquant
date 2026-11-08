"""Persistent protection groups and reviewable cash-equity order plans.

Delegated execution uses AlgoEngine's durable child intents and reconciliation.
All state transitions for an account share its execution lock.
"""
import copy
from .diagnostic_context import get_logger
import uuid

from .algo import AlgoEngine, TERMINAL, positive
from .algo_broker import execution_time
from .conditional_orders import validate_conditions, evaluate_conditions
from .diagnostics import quote_time_ms
from .position_sizing import calculate_position


SMART_ACTIONS = frozenset("cftrader." + name for name in (
    "calculate_position", "order_condition", "preview_order_plan", "submit_order_plan",
    "query_order_plan", "list_order_plans", "cancel_order_plan"))


class SmartOrderEngine(AlgoEngine):
    def _new(self, kind, request, key):
        account = request.get("account")
        if not isinstance(account, dict) or not account.get("account_id"):
            raise ValueError("account is required")
        return dict(algo_id=kind + "_" + uuid.uuid4().hex, kind=kind, account=account,
                    request=copy.deepcopy(request), request_key=key, created_at=self.clock(),
                    updated_at=self.clock(), status="MONITORING", last_error="", events=[],
                    children=[], filled_volume=0, traded_amount=0, reserved_volume=0,
                    remaining_volume=0, recovering=False, stop_reason=None)

    def _existing(self, request, key, kind):
        for task in self.list(request["account"]):
            if task.get("kind") == kind and task["request_key"] == key:
                if task["request"] != request:
                    raise ValueError("request_key already used for different parameters")
                return task["algo_id"]
        return None

    def _event(self, task, event_type, **details):
        event = dict(event_id=uuid.uuid4().hex, at=self.clock(), event=event_type)
        event.update(details)
        task["events"].append(event)
        task["events"] = task["events"][-200:]
        get_logger(__name__).info("smart_order %s %s %s", task["algo_id"], event_type, details)

    def _save(self, task):
        try:
            return super()._save(task)
        except Exception:
            self._persistence_failed = True
            raise

    def _insert(self, task):
        self.store.save(task)
        with self._lock:
            self._tasks[task["algo_id"]] = task
        self._wake.set()
        return task["algo_id"]

    def _fresh(self, task):
        config = task["config"]
        key = task["algo_id"]
        if key not in self._leases:
            self._leases[key] = self.quotes.acquire("algo:" + key, [config["stock_code"]], purpose="algo")
        snapshot = self.quotes.snapshot(config["stock_code"], config.get("max_quote_age", 15))
        quote = snapshot["quote"] if snapshot else {}
        stamp = quote_time_ms(quote.get("time", quote.get("stime")))
        if stamp is None or not -3 <= self.clock() - stamp / 1000 <= config.get("max_quote_age", 15):
            return None
        return quote

    def _execution_options(self, value):
        if not isinstance(value, dict):
            raise ValueError("execution must be an object with an explicit limit_price")
        allowed = {"algo", "limit_price", "duration_seconds", "interval_seconds", "participation_rate", "volume_profile",
                   "lookback_days", "max_child_volume", "child_timeout_seconds", "price_mode", "strategy_name"}
        if set(value) - allowed:
            raise ValueError("unknown execution options")
        result = copy.deepcopy(value)
        result["algo"] = str(result.get("algo", "LIMIT")).upper()
        if result["algo"] not in ("LIMIT", "TWAP", "VWAP", "POV"):
            raise ValueError("execution algo must be LIMIT, TWAP, VWAP or POV")
        result["limit_price"] = positive(result.get("limit_price"), "execution.limit_price")
        for key in ("duration_seconds", "interval_seconds", "child_timeout_seconds", "lookback_days", "max_child_volume"):
            if key in result:
                result[key] = positive(result[key], key, integer=key in ("lookback_days", "max_child_volume"))
        if result.get("price_mode", "opponent") not in ("opponent", "passive", "limit"):
            raise ValueError("invalid execution price_mode")
        if result["algo"] == "POV":
            if positive(result.get("participation_rate"), "participation_rate") > 1:
                raise ValueError("participation_rate must be at most 1")
        if "volume_profile" in result:
            profile = result["volume_profile"]
            if not isinstance(profile, (list, tuple)) or not profile:
                raise ValueError("volume_profile must be a nonempty list")
            result["volume_profile"] = [positive(value, "volume_profile", allow_zero=True) for value in profile]
            if not sum(result["volume_profile"]):
                raise ValueError("volume_profile must contain positive volume")
        if "strategy_name" in result and not isinstance(result["strategy_name"], str):
            raise ValueError("strategy_name must be text")
        return result

    def _condition_config(self, params):
        allowed = {"account", "stock_code", "order_volume", "position_percent", "all_sellable", "reference_price",
                   "conditions", "execution", "max_quote_age", "quote_field", "trigger_on_create", "expires_at"}
        if set(params) - allowed:
            raise ValueError("unknown conditional order parameters: " + ", ".join(sorted(set(params) - allowed)))
        if str(params.get("account", {}).get("account_type", "STOCK")) not in ("STOCK", "CREDIT", "2", "3"):
            raise ValueError("cash-equity protection requires a stock or credit account")
        code = params.get("stock_code")
        rules = self.broker.rules(code)
        reference = positive(params["reference_price"], "reference_price") if params.get("reference_price") is not None else None
        conditions = validate_conditions(params.get("conditions"), reference)
        for rule in conditions:
            if rule["type"] == "holding_exit":
                rule["at"] = self.broker.holding_deadline(code, rule)
        execution = self._execution_options(params.get("execution"))
        if execution.get("max_child_volume", rules["min_volume"]) < rules["min_volume"]:
            raise ValueError("max_child_volume is smaller than the instrument minimum")
        modes = [name for name in ("order_volume", "position_percent", "all_sellable") if name in params]
        if len(modes) != 1:
            raise ValueError("choose exactly one of order_volume, position_percent or all_sellable")
        if "order_volume" in params:
            positive(params["order_volume"], "order_volume", integer=True)
        if "position_percent" in params and positive(params["position_percent"], "position_percent") > 1:
            raise ValueError("position_percent must be at most 1")
        if "all_sellable" in params and params["all_sellable"] is not True:
            raise ValueError("all_sellable must be true")
        field = params.get("quote_field", "lastPrice")
        if field not in ("lastPrice", "bid1", "ask1"):
            raise ValueError("quote_field must be lastPrice, bid1 or ask1")
        if not isinstance(params.get("trigger_on_create", True), bool):
            raise ValueError("trigger_on_create must be boolean")
        expires = execution_time(params.get("expires_at"))
        if expires is not None and expires <= self.clock():
            raise ValueError("expires_at must be in the future")
        return dict(params, conditions=conditions, execution=execution, rules=rules, reference_price=reference,
                    quote_field=field, expires_at=expires, max_quote_age=positive(params.get("max_quote_age", 15), "max_quote_age"))

    def order_condition(self, params, source_id=None):
        request = copy.deepcopy(params)
        key = str(request.pop("request_key", None) or uuid.uuid4().hex)
        with self._account_lock(request.get("account", {})):
            existing = self._existing(request, key, "condition")
            if existing:
                return existing
            config = self._condition_config(request)
            snap = self.broker.snapshot(request["account"], config["stock_code"])
            if source_id:
                volume = request["order_volume"]
            else:
                claimed = sum(self._protected(row) for row in self.list(request["account"])
                              if row.get("kind") == "condition" and row["status"] not in TERMINAL
                              and row["config"]["stock_code"] == config["stock_code"])
                available = max(0, snap["current_volume"] - claimed)
                if "order_volume" in request:
                    volume = request["order_volume"]
                elif "all_sellable" in request:
                    volume = max(0, min(available, snap["sellable_volume"]))
                else:
                    volume = int(available * request["position_percent"])
                    volume = volume // config["rules"]["volume_step"] * config["rules"]["volume_step"]
                if volume <= 0 or volume > available:
                    raise ValueError("protected quantity exceeds unclaimed holdings or is zero")
                if (volume < config["rules"]["min_volume"] or volume % config["rules"]["volume_step"]) and volume != snap["current_volume"]:
                    raise ValueError("protected quantity violates instrument rules; an odd lot must cover the whole holding")
            config["order_volume"] = volume
            task = self._new("condition", request, key)
            task.update(config=config, remaining_volume=volume, source_id=source_id,
                        states={}, trigger=None, exits=[], snapshot=snap)
            self._event(task, "created", protected_volume=volume)
            return self._insert(task)

    def _protected(self, task):
        source = self._tasks.get(task.get("source_id"))
        total = min(task["config"]["order_volume"], source["filled_volume"]) if source else task["config"]["order_volume"]
        return max(0, total - task["filled_volume"])

    def _delegate(self, task, volume, options, suffix, order_type=24, odd_lot=False):
        key = task["algo_id"] + ":" + suffix
        existing = next((row for row in self.list(task["account"]) if row["request_key"] == key), None)
        if existing:
            return existing["algo_id"]
        code = task["config"]["stock_code"]
        end = self.broker.session_end(code, self.clock())
        if end is None or end - self.clock() < 1:
            return None
        options = copy.deepcopy(options)
        direct = options["algo"] == "LIMIT"
        duration = min(options.pop("duration_seconds", 300), end - self.clock())
        interval = duration if direct else min(options.pop("interval_seconds", 30), duration)
        options.update(algo="TWAP" if direct else options["algo"], duration_seconds=duration, interval_seconds=interval,
                       account=task["account"], stock_code=code, order_type=order_type, order_volume=volume,
                       request_key=key, max_quote_age=task["config"].get("max_quote_age", 15))
        if odd_lot:
            options.update(volume_step=1, min_child_volume=1, max_child_volume=volume,
                           algo="TWAP", interval_seconds=duration)
        return super().submit(options)

    def control(self, algo_id, account, action):
        task = self.query(algo_id, account)
        if task.get("kind") == "plan":
            raise ValueError("use cancel_order_plan for plans")
        if task.get("kind") != "condition":
            return super().control(algo_id, account, action)
        with self._account_lock(account):
            task = self._tasks[algo_id]
            if task["status"] in TERMINAL:
                return self.query(algo_id, account)
            if action == "cancel":
                task.update(status="CANCELLING", stop_reason="CANCELLED")
            elif action == "pause" and not task["stop_reason"]:
                task["status"] = "PAUSED"
            elif action == "resume" and task["status"] == "PAUSED":
                task["status"] = "MONITORING"
                task["acknowledged_failures"] = list(task["exits"])
                for child_id in task["exits"]:
                    if self._tasks[child_id]["status"] == "PAUSED":
                        super().control(child_id, account, "resume")
            else:
                raise ValueError("invalid condition control transition")
            self._event(task, action)
            self._save(task)
            for child_id in task["exits"]:
                if self._tasks[child_id]["status"] not in TERMINAL and action in ("cancel", "pause"):
                    super().control(child_id, account, action)
            self._wake.set()
            return self.query(algo_id, account)

    def _condition_step(self, task):
        config, now = task["config"], self.clock()
        source = self._tasks.get(task.get("source_id"))
        # Recover a child committed just before a process crash prevented linking it.
        for row in self.list(task["account"]):
            if row["request_key"].startswith(task["algo_id"] + ":exit:") and row["algo_id"] not in task["exits"]:
                task["exits"].append(row["algo_id"])
                self._save(task)
        # Execution children reconcile themselves; a missing acknowledgement never clears their reservation.
        children = [self._tasks[key] for key in task["exits"]]
        task["filled_volume"] = sum(row["filled_volume"] for row in children)
        task["traded_amount"] = sum(row["traded_amount"] for row in children)
        task["reserved_volume"] = sum(row["remaining_volume"] for row in children if row["status"] not in TERMINAL)
        task["remaining_volume"] = self._protected(task)
        task["recovering"] = False
        working = [row for row in children if row["status"] not in TERMINAL]
        if config["expires_at"] is not None and now >= config["expires_at"]:
            task["stop_reason"] = task["stop_reason"] or "EXPIRED"
        if task["stop_reason"]:
            for row in working:
                super().control(row["algo_id"], task["account"], "cancel")
            if not working:
                self._event(task, task["stop_reason"].lower())
                return self._finish(task, task["stop_reason"])
            task["status"] = "CANCELLING"
            return self._save(task)
        if task["status"] == "PAUSED":
            for row in working:
                if row["status"] != "PAUSED" and not row.get("stop_reason"):
                    super().control(row["algo_id"], task["account"], "pause")
            return self._save(task)
        if task["remaining_volume"] == 0:
            if source and source["status"] not in TERMINAL:
                task["status"] = "WAITING_FILL"
                return self._save(task)
            self._event(task, "completed", filled_volume=task["filled_volume"])
            return self._finish(task, "COMPLETED")
        if working:
            task["status"] = "EXECUTING"
            return self._save(task)
        if children and children[-1]["status"] == "FAILED" and children[-1]["algo_id"] not in task.get("acknowledged_failures", []):
            task["status"] = "PAUSED"
            task["last_error"] = "Exit rejected; inspect the execution task before resuming"
            return self._save(task)
        quote = self._fresh(task)
        if self.broker.session_end(config["stock_code"], now) is None:
            task["status"] = "WAITING_SESSION"
            return self._save(task)
        if not quote:
            task["status"] = "WAITING_MARKET"
            return self._save(task)
        field = config["quote_field"]
        value = quote.get("lastPrice") if field == "lastPrice" else (quote.get("bidPrice" if field == "bid1" else "askPrice") or [0])[0]
        price = positive(value, "condition quote price")
        if not task["trigger"]:
            task["trigger"] = evaluate_conditions(config["conditions"], task["states"], price, now,
                config["reference_price"], config.get("trigger_on_create", True))
            if task["trigger"]:
                self._event(task, "triggered", **task["trigger"])
                self._save(task)
        if not task["trigger"]:
            task["status"] = "MONITORING"
            return self._save(task)
        if source and source["status"] not in TERMINAL:
            super().control(source["algo_id"], task["account"], "cancel")
        snap = self.broker.snapshot(task["account"], config["stock_code"])
        volume = min(task["remaining_volume"], snap["sellable_volume"])
        rules = config["rules"]
        odd = (volume == snap["sellable_volume"] and volume == task["remaining_volume"]
               and (volume < rules["min_volume"] or volume % rules["volume_step"] != 0))
        if not odd:
            volume = int(volume // rules["volume_step"] * rules["volume_step"])
        if volume <= 0 or (volume < rules["min_volume"] and not odd):
            task["status"] = "WAITING_SELLABLE"
            task["last_error"] = "Triggered; waiting for sellable shares satisfying quantity rules (including T+1)"
            return self._save(task)
        # Deterministic key recovers the small crash window between child creation and linking it.
        child_id = self._delegate(task, volume, config["execution"], "exit:%d" % len(task["exits"]), odd_lot=odd)
        if child_id:
            task["exits"].append(child_id)
            task["status"] = "EXECUTING"
            task["last_error"] = ""
            self._event(task, "exit_created", execution_id=child_id, volume=volume)
        self._save(task)

    def _reserved_cash(self, account, excluding=None):
        return sum(row.get("reserved_cash", 0) for row in self.list(account)
                   if row.get("kind") == "plan" and row["algo_id"] != excluding)

    def _size_plan(self, request, excluding=None):
        if str(request.get("account", {}).get("account_type", "STOCK")) not in ("STOCK", "CREDIT", "2", "3"):
            raise ValueError("cash-equity plans require a stock or credit account")
        code = request["stock_code"]
        snapshot = self.broker.snapshot(request["account"], code)
        rules = self.broker.rules(code)
        sizing = copy.deepcopy(request.get("sizing"))
        if not isinstance(sizing, dict):
            raise ValueError("sizing must be an object")
        forbidden = {"stock_code", "total_asset", "available_cash", "reserved_cash", "current_volume", "pending_buy_volume",
                     "price_tick", "min_volume", "volume_step"}
        if set(sizing) & forbidden:
            raise ValueError("account snapshots and instrument rules are supplied by the server")
        if excluding:
            sizing["max_volume"] = min(sizing.get("max_volume", self._tasks[excluding]["preview"]["quantity"]),
                                       self._tasks[excluding]["preview"]["quantity"])
        # Include accepted plans that the broker may not yet reflect in its order query.
        # This can overlap a broker reservation; conservatively avoid exceeding weight caps.
        pending_plans = 0
        for row in self.list(request["account"]):
            if row.get("kind") != "plan" or row["algo_id"] == excluding or row["config"]["stock_code"] != code:
                continue
            entry = self._tasks.get(row.get("entry_id"))
            if row.get("reserved_cash", 0) and (entry is None or entry["status"] not in TERMINAL):
                pending_plans += max(0, row["sizing"]["quantity"] - (entry["filled_volume"] if entry else 0))
        snapshot["pending_buy_volume"] += pending_plans
        snapshot["pending_plan_volume"] = pending_plans
        result = calculate_position(stock_code=code, **sizing,
            **{key: snapshot[key] for key in ("total_asset", "available_cash", "current_volume", "pending_buy_volume")},
            reserved_cash=self._reserved_cash(request["account"], excluding),
            **{key: rules[key] for key in ("min_volume", "volume_step", "price_tick")})
        return result, snapshot

    def preview_order_plan(self, params):
        request = copy.deepcopy(params)
        key = str(request.pop("request_key", None) or uuid.uuid4().hex)
        if set(request) - {"account", "stock_code", "sizing", "execution", "protection", "expires_seconds", "portfolio_risk_cap"}:
            raise ValueError("unknown order plan parameters")
        with self._account_lock(request.get("account", {})):
            existing = self._existing(request, key, "plan")
            if existing:
                return self.query(existing, request["account"])
            result, snapshot = self._size_plan(request)
            execution = self._execution_options(request.get("execution", {"limit_price": result["entry_price"]}))
            if execution["limit_price"] != result["entry_price"]:
                raise ValueError("entry execution limit_price must equal sizing.entry_price")
            protection = request.get("protection")
            if protection is not None:
                if not isinstance(protection, dict) or set(protection) - {"conditions", "execution", "reference_price", "quote_field", "trigger_on_create", "expires_at"}:
                    raise ValueError("invalid protection options")
                protection = dict(protection)
                protection.setdefault("reference_price", result["entry_price"])
                self._condition_config(dict(protection, account=request["account"], stock_code=request["stock_code"],
                                            order_volume=max(1, result["quantity"])))
            if request.get("portfolio_risk_cap") is not None:
                positive(request["portfolio_risk_cap"], "portfolio_risk_cap")
                if result["estimated_loss"] is None:
                    raise ValueError("portfolio_risk_cap requires stop_price")
            lifetime = positive(request.get("expires_seconds", 180), "expires_seconds")
            if lifetime > 3600:
                raise ValueError("plan preview expires_seconds must be at most 3600")
            task = self._new("plan", request, key)
            task.update(status="PREVIEW", preview=result, snapshot=snapshot, expires_at=self.clock() + lifetime,
                        config=dict(stock_code=request["stock_code"], max_quote_age=15),
                        execution=execution, protection=protection, entry_id=None, protection_id=None,
                        reserved_cash=0, reserved_risk=0, ready=False, cancel_requested=False)
            self._event(task, "previewed", quantity=result["quantity"])
            self._insert(task)
            return self.query(task["algo_id"], task["account"])

    def submit_order_plan(self, plan_id, account):
        with self._account_lock(account):
            self.query(plan_id, account)
            task = self._tasks[plan_id]
            if task.get("kind") != "plan":
                raise ValueError("order plan not found")
            if task["status"] != "PREVIEW":
                return self.query(plan_id, account)
            if self.clock() >= task["expires_at"]:
                self._finish(task, "EXPIRED")
                raise ValueError("plan preview has expired; create a new preview")
            quote = self._fresh(task)
            if not quote or self.broker.session_end(task["config"]["stock_code"], self.clock()) is None:
                raise ValueError("a fresh quote in an executable session is required; retry this plan")
            ask = positive((quote.get("askPrice") or [0])[0], "ask1")
            if ask > task["execution"]["limit_price"]:
                raise ValueError("current ask exceeds the reviewed entry limit; create a new preview or wait")
            result, snapshot = self._size_plan(task["request"], plan_id)
            if not result["quantity"]:
                raise ValueError("no legal quantity remains after current cash and risk checks")
            cap = task["request"].get("portfolio_risk_cap")
            reserved_risk = sum(row.get("reserved_risk", 0) for row in self.list(account) if row["algo_id"] != plan_id)
            if cap is not None and reserved_risk + (result["estimated_loss"] or 0) > cap:
                raise ValueError("portfolio nominal stop-risk cap exceeded by submitted plans")
            task.update(status="SUBMITTING", sizing=result, submit_snapshot=snapshot,
                        reserved_cash=result["cash_required"], reserved_risk=result["estimated_loss"] or 0)
            self._event(task, "submission_requested", quantity=result["quantity"])
            self._save(task)
            self._activate_plan(task)
            return self.query(plan_id, account)

    def _activate_plan(self, task):
        if not task["entry_id"]:
            existing = next((row for row in self.list(task["account"]) if row["request_key"] == task["algo_id"] + ":entry"), None)
            if existing:
                task["entry_id"] = existing["algo_id"]
            elif self.clock() >= task["expires_at"] or task["cancel_requested"]:
                task.update(reserved_cash=0, reserved_risk=0)
                return self._finish(task, "CANCELLED" if task["cancel_requested"] else "EXPIRED")
        if not task["entry_id"]:
            task["entry_id"] = self._delegate(task, task["sizing"]["quantity"], task["execution"], "entry", order_type=23)
            if not task["entry_id"]:
                return self._save(task)
            self._save(task)
        if task["protection"] is not None and not task["protection_id"]:
            params = dict(task["protection"], account=task["account"], stock_code=task["config"]["stock_code"],
                          order_volume=task["sizing"]["quantity"], request_key=task["algo_id"] + ":protection")
            task["protection_id"] = self.order_condition(params, source_id=task["entry_id"])
            self._save(task)
        task.update(ready=True, status="SUBMITTED", last_error="")
        self._event(task, "submitted", entry_id=task["entry_id"], protection_id=task["protection_id"])
        self._save(task)

    def cancel_order_plan(self, plan_id, account):
        with self._account_lock(account):
            self.query(plan_id, account)
            task = self._tasks[plan_id]
            if task.get("kind") != "plan":
                raise ValueError("order plan not found")
            if task["status"] == "PREVIEW":
                self._finish(task, "CANCELLED")
            else:
                task["cancel_requested"] = True
                self._event(task, "entry_cancellation_requested")
                self._save(task)
                if task["entry_id"]:
                    super().control(task["entry_id"], account, "cancel")
            return self.query(plan_id, account)

    def _plan_step(self, task):
        if task["status"] == "PREVIEW":
            if self.clock() >= task["expires_at"]:
                self._finish(task, "EXPIRED")
            return
        if not task["ready"]:
            self._activate_plan(task)
            if not task["ready"]:
                return
        entry = self._tasks[task["entry_id"]]
        if task["cancel_requested"] and entry["status"] not in TERMINAL:
            super().control(entry["algo_id"], task["account"], "cancel")
        task["entry_status"] = entry["status"]
        task["filled_volume"] = entry["filled_volume"]
        task["traded_amount"] = entry["traded_amount"]
        protection = self._tasks.get(task["protection_id"])
        task["protection_status"] = protection["status"] if protection else None
        task["recovering"] = bool(entry.get("recovering") or (protection and protection.get("recovering")))
        if entry["status"] in TERMINAL:
            task["reserved_cash"] = 0
            remaining = max(0, entry["filled_volume"] - (protection["filled_volume"] if protection else 0))
            task["reserved_risk"] = (task["sizing"]["estimated_loss"] or 0) * remaining / task["sizing"]["quantity"]
            task["remaining_volume"] = remaining
            if remaining == 0:
                return self._finish(task, entry["status"] if not entry["filled_volume"] else "COMPLETED")
            task["status"] = "PROTECTED" if protection and protection["status"] not in TERMINAL else "HOLDING"
        self._save(task)

    def step(self, algo_id):
        task = self._tasks[algo_id]
        with self._account_lock(task["account"]):
            if getattr(self, "_persistence_failed", False):
                raise RuntimeError("persistence failed; restart the service after repairing storage before continuing")
            if task["status"] in TERMINAL:
                return self._finish(task, task["status"])
            if task.get("kind") == "condition":
                return self._condition_step(task)
            if task.get("kind") == "plan":
                return self._plan_step(task)
            # A plan's entry cannot execute until its protection is durably installed.
            if task["request_key"].startswith("plan_") and task["request_key"].endswith(":entry"):
                parent = self._tasks.get(task["request_key"].rsplit(":", 1)[0])
                if parent is None or not parent.get("ready"):
                    return
            if task["request_key"].startswith("condition_") and ":exit:" in task["request_key"]:
                parent = self._tasks.get(task["request_key"].split(":", 1)[0])
                if parent is None or algo_id not in parent["exits"]:
                    return
                if parent.get("stop_reason"):
                    super().control(algo_id, task["account"], "cancel")
                elif parent["status"] == "PAUSED" and not task.get("stop_reason"):
                    super().control(algo_id, task["account"], "pause")
            return super().step(algo_id)
