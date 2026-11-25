"""Batch segmentation for independent market bridges, without Web dependencies."""
import time

from .batch_orders import (
    CFTRADER_BATCH_CANCEL_ACTIONS, prepare_batch_request, prepare_batch_cancel_request,
    batch_result_rows, batch_cancel_result_rows, validate_batch_response, validate_batch_cancel_response,
    batch_result, batch_rejected, batch_unknown,
)


def route_batch(action, params, routes, request, timeout):
    from .bridge_center import request_market
    asynchronous = action.endswith('_async')
    cancel = action in CFTRADER_BATCH_CANCEL_ACTIONS
    items = (prepare_batch_cancel_request if cancel else prepare_batch_request)(params, asynchronous)
    name = 'cancels' if cancel else 'orders'
    rows = (batch_cancel_result_rows if cancel else batch_result_rows)(items, params.get('seqs') if asynchronous else None)
    validate = validate_batch_cancel_response if cancel else validate_batch_response
    segments = []
    # Validate every destination before dispatching any part of this batch.
    for index, item in enumerate(items):
        market = request_market(item)
        target = routes.get(market) or {}
        if not target.get('bridge_id') or target.get('enabled', True) is False:
            raise ValueError('no enabled market route for %s[%s]; include stock_code or market' % (name, index))
        if not segments or segments[-1][0] != market:
            segments.append((market, []))
        segments[-1][1].append(index)
    deadline = time.monotonic() + timeout
    submit_ms = 0.0
    error = None
    for market, indices in segments:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        body = dict(params, bridge_id=routes[market]['bridge_id'])
        body[name] = [items[index] for index in indices]
        if asynchronous:
            body['seqs'] = [params['seqs'][index] for index in indices]
        # A channel role must be resolved again for each child bridge.
        body['_center_request_channel'] = 'trade'
        try:
            response = validate(request(action, body, remaining), body, asynchronous)
            submit_ms += float(response.get('qmt_submit_ms') or 0)
            for index, row in zip(indices, response['results']):
                rows[index] = dict(row, index=index)
        except Exception as exc:
            error = exc
            (batch_rejected if getattr(exc, 'dispatched', None) is False else batch_unknown)(
                [rows[index] for index in indices], exc)
            break  # An uncertain write is never retried or replayed.
        if response['unknown'] or (params.get('stop_on_error', False) and response['failed']):
            break
    result = batch_result(params['account'], params['batch_id'], asynchronous, rows,
                          operation='cancel' if cancel else 'order')
    result['qmt_submit_ms'] = round(submit_ms, 3)
    if error is not None:
        result['request_error'] = str(error)
        result.update({key: value for key, value in getattr(error, 'error_details', {}).items()
                       if key in ('dispatched', 'safe_to_retry', 'retry_when', 'runtime_instance_id')})
    return result


def route_legacy_batch(params, routes, request, timeout):
    from .bridge_center import request_market
    orders = params.get('orders') or []
    groups = {}
    for index, item in enumerate(orders):
        market = request_market(item)
        target = routes.get(market) or {}
        if not target.get('bridge_id') or target.get('enabled', True) is False:
            raise ValueError('no enabled market route for orders[%s]' % index)
        groups.setdefault(market, []).append(index)
    started = time.monotonic()
    combined, results = [None] * len(orders), []
    for market, indices in groups.items():
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError('market batch deadline exceeded; earlier groups may have executed')
        bridge_id = routes[market]['bridge_id']
        body = dict(params, orders=[orders[index] for index in indices],
                    bridge_id=bridge_id, _center_request_channel='trade')
        response = request('xttrader.order_stock_batch', body, remaining)
        rows = response.get('results') if isinstance(response, dict) else response if isinstance(response, list) else None
        for local, index in enumerate(indices):
            row = rows[local] if isinstance(rows, list) and local < len(rows) else response
            combined[index] = dict(row, index=index) if isinstance(row, dict) else dict(index=index, ok=True, result=row)
            combined[index].setdefault('market', market)
            combined[index].setdefault('bridge_id', bridge_id)
        results.append(dict(market=market, bridge_id=bridge_id, count=len(indices)))
    return dict(ok=all(row.get('ok', True) for row in combined), market_routing=True,
                results=combined, groups=results, latency_ms=(time.monotonic() - started) * 1000)
