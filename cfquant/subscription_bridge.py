"""Fileless, Python 3.6 compatible subscription ownership in the QMT pump."""
import json as _sub_json
import time as _sub_time
import uuid as _sub_uuid

from .protocol import loads_message, dumps_message


MANAGED_SUBSCRIPTION_ACTION = 'cfquant.managed_subscription'
_SUB_PREFIX = 'cfq_sub:'
_SUB_QUOTES = ('xtdata.subscribe_quote', 'xtdata.subscribe_whole_quote',
               'xtdata.subscribe_whole_quote_latency', 'xtdata.subscribe_l2thousand',
               'xtdata.subscribe_l2thousand_queue')


def validate_subscription_spec(spec):
    action, params = spec.get('action'), spec.get('params')
    if not isinstance(params, dict):
        raise ValueError('subscription params must be an object')
    allowed = action in _SUB_QUOTES or action == 'xttrader.subscribe'
    if action == 'qmt_inner.call':
        allowed = (params.get('category') == 'market' and
                   params.get('method') in ('subscribe_quote', 'subscribe_whole_quote'))
    if action == 'qmt_inner.callbacks':
        allowed = bool(params.get('token'))
    if not allowed:
        raise ValueError('action is not a recoverable subscription: %s' % action)
    raw = _sub_json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode('utf-8')) > 65536:
        raise ValueError('subscription specification exceeds 64 KiB')
    return raw


def _subscription_state(bridge):
    state = getattr(bridge, '_managed_subscriptions', None)
    if state is None:
        state = dict(generation=_sub_uuid.uuid4().hex, rows={})
        bridge._managed_subscriptions = state
    return state


def _subscription_release(bridge, key, row):
    row['active'] = False
    action, params = row['spec']['action'], dict(row['spec']['params'])
    msg = {'client_id': _SUB_PREFIX + key}
    if action in _SUB_QUOTES:
        if row['native_id'] is None:
            raise RuntimeError('native subscription result unknown; bridge restart required')
        result = bridge._dispatch('xtdata.unsubscribe_quote', {'subscribe_id': row['native_id']}, msg)
    elif action == 'xttrader.subscribe':
        result = bridge._dispatch('xttrader.unsubscribe', params, msg)
    else:
        result = bridge._dispatch('qmt_inner.close', {'session_id': key}, msg)
    if result is False or (isinstance(result, (int, float)) and result < 0):
        raise RuntimeError('native subscription cleanup failed')


def expire_managed_subscriptions(bridge, close=False):
    state = getattr(bridge, '_managed_subscriptions', None)
    if not state:
        return
    now = _sub_time.monotonic()
    # Bounded cleanup in the QMT request pump; failed cleanup remains fenced.
    for key, row in list(state['rows'].items())[:]:
        if not close and row['deadline'] > now:
            continue
        try:
            _subscription_release(bridge, key, row)
        except Exception as error:
            row['error'] = str(error)
            row['deadline'] = now + 10
        else:
            del state['rows'][key]
        if not close:
            break


def dispatch_managed_subscription(bridge, params, msg):
    state = _subscription_state(bridge)
    op = params.get('op')
    reply = msg.get('client_id') or msg.get('reply_channel')
    if op == 'capabilities':
        return {'version': 1, 'generation': state['generation']}
    epoch = params.get('epoch')
    if type(epoch) is not int or epoch < 1 or not reply:
        raise ValueError('subscription manager epoch and reply channel required')
    if op == 'probe':
        keys = params.get('keys', [])
        if not isinstance(keys, list) or len(keys) > 200:
            raise ValueError('at most 200 subscription keys per probe')
        result = {}
        for key in keys:
            row = state['rows'].get(key)
            if row is None:
                result[key] = {'state': 'missing'}
                continue
            if epoch < row['epoch']:
                raise ValueError('stale subscription manager epoch')
            row['epoch'], row['reply'] = epoch, reply
            if row['active']:
                row['deadline'] = _sub_time.monotonic() + 45
            result[key] = dict(state='active' if row['active'] else 'uncertain',
                               native_id=row.get('native_id'), error=row.get('error', ''))
        return {'generation': state['generation'], 'resources': result}
    key = params.get('key')
    if not isinstance(key, str) or len(key) > 128 or not key:
        raise ValueError('invalid subscription key')
    row = state['rows'].get(key)
    if row and epoch < row['epoch']:
        raise ValueError('stale subscription manager epoch')
    if op == 'release':
        if row:
            _subscription_release(bridge, key, row)
            del state['rows'][key]
        return {'state': 'released', 'generation': state['generation']}
    if op != 'ensure':
        raise ValueError('unsupported subscription operation')
    spec = params.get('spec') or {}
    signature = validate_subscription_spec(spec)
    if row:
        if row['signature'] != signature:
            raise ValueError('subscription key reused with different parameters')
        if not row['active']:
            raise RuntimeError('subscription result uncertain; awaiting resource cleanup')
        row.update(reply=reply, epoch=epoch, deadline=_sub_time.monotonic() + 45)
        return {'state': 'active', 'native_id': row.get('native_id'), 'generation': state['generation']}
    if len(state['rows']) >= 5000:
        raise RuntimeError('bridge managed subscription limit reached')
    row = dict(spec=spec, signature=signature, reply=reply, epoch=epoch, active=True,
               deadline=_sub_time.monotonic() + 45, native_id=None)
    state['rows'][key] = row  # Route synchronous first callbacks before native creation.
    native_params = dict(spec['params'])
    native_params.pop('_managed_recovery', None)
    native_params.pop('lease_timeout', None)  # This registry owns the lease.
    if spec['action'].startswith('qmt_inner.'):
        native_params['session_id'] = key
    try:
        value = bridge._dispatch(spec['action'], native_params, {'client_id': _SUB_PREFIX + key})
        if spec['action'] in _SUB_QUOTES:
            value = value.get('subscribe_id') if isinstance(value, dict) else value
        if spec['action'] in _SUB_QUOTES or spec['action'] == 'qmt_inner.call':
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise RuntimeError('invalid native subscription ID')
        elif value is False or (isinstance(value, (int, float)) and value < 0):
            raise RuntimeError('native subscription rejected')
        row['native_id'] = value
    except Exception as error:
        # Do not re-execute a native call after an ambiguous failure.
        row.update(active=False, error=str(error))
        raise
    return {'state': 'active', 'native_id': value, 'generation': state['generation']}


def push_subscription_event(bridge, payload, client_id):
    """Forward an already encoded event without a second value encoding pass."""
    if not str(client_id).startswith(_SUB_PREFIX):
        return bridge.tx.push('event', payload, client_id)
    key = client_id[len(_SUB_PREFIX):]
    state = getattr(bridge, '_managed_subscriptions', {})
    row = state.get('rows', {}).get(key)
    if not row or not row['active'] or row['deadline'] <= _sub_time.monotonic():
        return
    event = loads_message(payload)
    event['data'] = dict(key=key, generation=state['generation'], epoch=row['epoch'],
                         event=event['event'], payload=event.get('data'))
    event['event'], event['client_id'] = MANAGED_SUBSCRIPTION_ACTION, row['reply']
    return bridge.tx.push('event', dumps_message(event), row['reply'])
