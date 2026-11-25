"""Order-only extensions sharing an existing XtQuantTrader session and callbacks."""

from .batch_orders import (
    batch_cancel_result_rows, batch_rejected, batch_result, batch_result_rows, batch_unknown,
    prepare_batch_cancels, prepare_batch_orders, validate_batch_cancel_response, validate_batch_response,
)
from .protocol import new_id
from .position_sizing import calculate_position
from .xttrader import XtQuantTrader, _account_payload
import threading


_algo_client = None
_algo_client_lock = threading.Lock()


def _algo_rpc(action, params):
    """Algorithm tasks always live in the shared service, also for direct SDKs."""
    global _algo_client
    with _algo_client_lock:
        if _algo_client is None:
            import atexit
            from .client import create_rpc_client
            _algo_client = create_rpc_client(transport="center")
            atexit.register(_algo_client.close)
        client = _algo_client
    return client.request(action, params)


__all__ = ["CfQuantTrader", "calculate_position"]

class CfQuantTrader:
    """Use CfQuantTrader(trader) with an existing cfquant XtQuantTrader instance.

    Lifecycle, subscriptions, cancellation and callbacks belong to ``trader``.
    Each batch is sent in one RPC and executed inside QMT. Algorithm methods
    use a lazy connection to the shared Web execution service; tasks run there.
    """

    def __init__(self, trader):
        if not isinstance(trader, XtQuantTrader):
            raise TypeError("trader must be a cfquant.xttrader.XtQuantTrader instance")
        self._trader = trader
        self._algo_accounts = {}

    def order_algo(self, account, stock_code, order_type, order_volume, algo,
                   limit_price, duration_seconds=3600, interval_seconds=60, **options):
        """Return a persistent algo_id. Caller exit does not cancel the task."""
        payload = _account_payload(self._trader._resolve_account(account))
        params = dict(options, account=payload, stock_code=stock_code, order_type=order_type,
                      order_volume=order_volume, algo=algo, limit_price=limit_price,
                      duration_seconds=duration_seconds, interval_seconds=interval_seconds)
        params.setdefault("request_key", new_id("algo_request"))
        algo_id = _algo_rpc("cftrader.order_algo", params)
        self._algo_accounts[algo_id] = payload
        return algo_id

    def order_twap(self, account, stock_code, order_type, order_volume, limit_price, **options):
        return self.order_algo(account, stock_code, order_type, order_volume, "TWAP", limit_price, **options)

    calculate_position = staticmethod(calculate_position)

    def order_condition(self, account, stock_code, conditions, execution, **options):
        """Create a persistent sell protection group; manage it with query/pause/cancel_algo."""
        payload = _account_payload(self._trader._resolve_account(account))
        params = dict(options, account=payload, stock_code=stock_code, conditions=conditions, execution=execution)
        params.setdefault("request_key", new_id("condition_request"))
        task_id = _algo_rpc("cftrader.order_condition", params)
        self._algo_accounts[task_id] = payload
        return task_id

    def order_stop_loss(self, account, stock_code, order_volume, stop_price, limit_price, **options):
        return self.order_condition(account, stock_code, [{"type": "stop_loss", "price": stop_price}],
                                    {"limit_price": limit_price}, order_volume=order_volume, **options)

    def order_take_profit(self, account, stock_code, order_volume, take_profit_price, limit_price, **options):
        return self.order_condition(account, stock_code, [{"type": "take_profit", "price": take_profit_price}],
                                    {"limit_price": limit_price}, order_volume=order_volume, **options)

    def order_trailing_stop(self, account, stock_code, order_volume, drawdown_percent, limit_price,
                            activation_price=None, **options):
        rule = dict(type="trailing_stop", drawdown_percent=drawdown_percent)
        if activation_price is not None:
            rule["activation_price"] = activation_price
        return self.order_condition(account, stock_code, [rule], {"limit_price": limit_price},
                                    order_volume=order_volume, **options)

    def order_breakeven_stop(self, account, stock_code, order_volume, reference_price, activation_percent,
                             limit_price, offset_amount=0, **options):
        return self.order_condition(account, stock_code,
            [dict(type="breakeven_stop", activation_percent=activation_percent, offset_amount=offset_amount)],
            {"limit_price": limit_price}, order_volume=order_volume, reference_price=reference_price, **options)

    def order_time_exit(self, account, stock_code, order_volume, at, limit_price, only_if_loss=False, **options):
        return self.order_condition(account, stock_code, [dict(type="time_exit", at=at, only_if_loss=only_if_loss)],
                                    {"limit_price": limit_price}, order_volume=order_volume, **options)

    def preview_order_plan(self, account, stock_code, sizing, **options):
        """Persist a preview without ordering; account balances are read by the service."""
        payload = _account_payload(self._trader._resolve_account(account))
        params = dict(options, account=payload, stock_code=stock_code, sizing=sizing)
        params.setdefault("request_key", new_id("plan_request"))
        plan = _algo_rpc("cftrader.preview_order_plan", params)
        self._algo_accounts[plan["algo_id"]] = payload
        return plan

    def _plan_control(self, action, plan_id=None, account=None):
        payload = _account_payload(self._trader._resolve_account(account or self._algo_accounts.get(plan_id)))
        return _algo_rpc("cftrader." + action, dict(plan_id=plan_id, account=payload))

    def submit_order_plan(self, plan_id, account=None):
        """Revalidate and submit once. Repeating the same plan_id returns its current state."""
        return self._plan_control("submit_order_plan", plan_id, account)

    def query_order_plan(self, plan_id, account=None):
        return self._plan_control("query_order_plan", plan_id, account)

    def list_order_plans(self, account=None):
        return self._plan_control("list_order_plans", account=account)

    def cancel_order_plan(self, plan_id, account=None):
        """Cancel the entry remainder; retain protection for confirmed fills."""
        return self._plan_control("cancel_order_plan", plan_id, account)

    def order_vwap(self, account, stock_code, order_type, order_volume, limit_price, **options):
        return self.order_algo(account, stock_code, order_type, order_volume, "VWAP", limit_price, **options)

    def order_pov(self, account, stock_code, order_type, order_volume, limit_price, participation_rate, **options):
        return self.order_algo(account, stock_code, order_type, order_volume, "POV", limit_price,
                               participation_rate=participation_rate, **options)

    def _algo_control(self, action, algo_id=None, account=None):
        resolved = account or self._algo_accounts.get(algo_id)
        payload = _account_payload(self._trader._resolve_account(resolved))
        return _algo_rpc("cftrader." + action, dict(algo_id=algo_id, account=payload))

    def query_algo(self, algo_id, account=None):
        return self._algo_control("query_algo", algo_id, account)

    def list_algos(self, account=None):
        return self._algo_control("list_algos", account=account)

    def pause_algo(self, algo_id, account=None):
        """Pause new orders and request cancellation of working children."""
        return self._algo_control("pause_algo", algo_id, account)

    def resume_algo(self, algo_id, account=None):
        return self._algo_control("resume_algo", algo_id, account)

    def cancel_algo(self, algo_id, account=None):
        """CANCELLING remains until the broker confirms all child outcomes."""
        return self._algo_control("cancel_algo", algo_id, account)

    def order_stock(self, account, stock_code, order_type, order_volume, price_type, price,
                    strategy_name="", order_remark=""):
        """Submit one order using the original XtQuantTrader signature and result."""
        return self._trader.order_stock(account, stock_code, order_type, order_volume,
                                        price_type, price, strategy_name, order_remark)

    def order_stock_async(self, account, stock_code, order_type, order_volume, price_type, price,
                          strategy_name="", order_remark=""):
        """Return the original request seq; responses use the original callback."""
        return self._trader.order_stock_async(account, stock_code, order_type, order_volume,
                                              price_type, price, strategy_name, order_remark)

    def order_stock_batch(self, account, orders, strategy_name="", order_remark="", stop_on_error=False):
        """Submit inside QMT, then resolve order IDs in a shared waiting window.

        QMT submits all eligible rows before waiting for IDs. A missing batch
        response means every row may have executed; reconcile before retrying.
        """
        return self._batch(account, orders, strategy_name, order_remark, stop_on_error, asynchronous=False)

    def order_stock_batch_async(self, account, orders, strategy_name="", order_remark="", stop_on_error=False):
        """Send one batch request; QMT submits locally without waiting for IDs.

        Responses and fills arrive through the wrapped trader's existing callback.
        This call waits for request acknowledgements, not for fills or order IDs.
        """
        return self._batch(account, orders, strategy_name, order_remark, stop_on_error, asynchronous=True)

    def cancel_order_stock_batch(self, account, order_ids, stop_on_error=False):
        """Cancel multiple orders inside QMT through one batch request.

        ``order_ids`` may be a list of IDs or dictionaries containing
        ``order_id`` plus optional ``stock_code``/``market`` for market routing.
        """
        return self._cancel_batch(account, order_ids, stop_on_error, asynchronous=False)

    def cancel_order_stock_batch_async(self, account, order_ids, stop_on_error=False):
        """Cancel multiple orders asynchronously; responses use original callbacks."""
        return self._cancel_batch(account, order_ids, stop_on_error, asynchronous=True)

    def _prepare(self, account, orders, strategy_name, order_remark, stop_on_error):
        account = _account_payload(self._trader._resolve_account(account))
        if not str(account.get("account_id") or "").strip():
            raise ValueError("account_id is required")
        batch_id = new_id("cfbatch")
        rows = prepare_batch_orders(orders, batch_id, strategy_name, order_remark, stop_on_error)
        return account, batch_id, rows

    def _batch(self, account, orders, strategy_name, order_remark, stop_on_error, asynchronous):
        account, batch_id, rows = self._prepare(account, orders, strategy_name, order_remark, stop_on_error)
        seqs = [next(self._trader._seq) for row in rows] if asynchronous else []
        params = dict(account=account, batch_id=batch_id, orders=rows, seqs=seqs, stop_on_error=stop_on_error)
        action = "cftrader.order_stock_batch_async" if asynchronous else "cftrader.order_stock_batch"
        if asynchronous:
            # Callbacks can precede the batch acknowledgement; register every
            # correlation before sending the single request.
            for row, seq in zip(rows, seqs):
                self._trader._register_pending_async_order(dict(row, account=account, seq=seq))
        try:
            response = self._trader._trade_request(action, params)
            result = validate_batch_response(response, params, asynchronous)
        except Exception as error:
            results = batch_result_rows(rows, seqs)
            if getattr(error, "dispatched", None) is False:
                batch_rejected(results, error)
            else:
                batch_unknown(results, "Batch response unavailable; QMT may still execute the batch: %s" % error)
            result = batch_result(account, batch_id, asynchronous, results)
            result["request_error"] = str(error) or type(error).__name__
            details = getattr(error, "error_details", None)
            if isinstance(details, dict):
                result.update(error_code=details.get("code", ""), error_stage=details.get("stage", ""),
                              dispatched=details.get("dispatched"), safe_to_retry=details.get("safe_to_retry") is True,
                              retry_when=details.get("retry_when", ""),
                              runtime_instance_id=details.get("runtime_instance_id", ""))
        if asynchronous:
            for row in result["results"]:
                if row["status"] in ("failed", "skipped"):
                    self._trader._discard_pending_async_order(row["seq"])
        return result

    def _prepare_cancel(self, account, order_ids, stop_on_error):
        account = _account_payload(self._trader._resolve_account(account))
        if not str(account.get("account_id") or "").strip():
            raise ValueError("account_id is required")
        batch_id = new_id("cfcancel")
        rows = prepare_batch_cancels(order_ids, batch_id, stop_on_error)
        return account, batch_id, rows

    def _cancel_batch(self, account, order_ids, stop_on_error, asynchronous):
        account, batch_id, rows = self._prepare_cancel(account, order_ids, stop_on_error)
        seqs = [next(self._trader._seq) for row in rows] if asynchronous else []
        params = dict(account=account, batch_id=batch_id, cancels=rows, seqs=seqs, stop_on_error=stop_on_error)
        action = "cftrader.cancel_order_stock_batch_async" if asynchronous else "cftrader.cancel_order_stock_batch"
        try:
            response = self._trader._trade_request(action, params)
            return validate_batch_cancel_response(response, params, asynchronous)
        except Exception as error:
            results = batch_cancel_result_rows(rows, seqs)
            if getattr(error, "dispatched", None) is False:
                batch_rejected(results, error)
            else:
                batch_unknown(results, "Batch cancel response unavailable; QMT may still execute the batch: %s" % error)
            result = batch_result(account, batch_id, asynchronous, results, operation="cancel")
            result["request_error"] = str(error) or type(error).__name__
            details = getattr(error, "error_details", None)
            if isinstance(details, dict):
                result.update(error_code=details.get("code", ""), error_stage=details.get("stage", ""),
                              dispatched=details.get("dispatched"), safe_to_retry=details.get("safe_to_retry") is True,
                              retry_when=details.get("retry_when", ""),
                              runtime_instance_id=details.get("runtime_instance_id", ""))
            return result
