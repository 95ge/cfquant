"""Order-only extensions sharing an existing XtQuantTrader session and callbacks."""

from .batch_orders import (
    batch_result, batch_result_rows, batch_unknown, prepare_batch_orders, validate_batch_response,
)
from .protocol import new_id
from .xttrader import XtQuantTrader, _account_payload


__all__ = ["CfQuantTrader"]

class CfQuantTrader:
    """Use CfQuantTrader(trader) with an existing cfquant XtQuantTrader instance.

    Lifecycle, subscriptions, cancellation and callbacks belong to ``trader``.
    Each batch is sent in one RPC and executed inside QMT. It does not add a
    worker, connection, callback channel or automatic retry in the SDK.
    """

    def __init__(self, trader):
        if not isinstance(trader, XtQuantTrader):
            raise TypeError("trader must be a cfquant.xttrader.XtQuantTrader instance")
        self._trader = trader

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
            batch_unknown(results, "Batch response unavailable; QMT may still execute the batch: %s" % error)
            result = batch_result(account, batch_id, asynchronous, results)
            result["request_error"] = str(error) or type(error).__name__
        if asynchronous:
            for row in result["results"]:
                if row["status"] in ("failed", "skipped"):
                    self._trader._discard_pending_async_order(row["seq"])
        return result
