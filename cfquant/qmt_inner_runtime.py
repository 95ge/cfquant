"""Native dispatch for QmtInnerApi; no xttrader translations or order retries."""
import datetime as _inner_dt
import threading as _inner_threading

from .qmt_inner_catalog import (
    INNER_METHODS, INNER_CALLBACKS, INNER_CONTEXT_ATTRIBUTES, inner_method_owner,
)

_INNER_STATE_LOCK = _inner_threading.RLock()


def _inner_plain(value):
    """Preserve native QMT fields, including Boost.Python properties without __dict__."""
    if isinstance(value, dict):
        return {key: _inner_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_inner_plain(item) for item in value]
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return value
    # Some native QMT types do not expose Python's optional type metadata.
    # Leave pandas/numpy objects to the existing protocol codec.
    try:
        module = type(value).__module__.split('.')[0]
    except (AttributeError, KeyError):
        module = ''
    if module == 'pandas' and type(value).__name__ == 'Panel':
        raise TypeError('Legacy pandas.Panel is not supported over RPC; query one stock or use get_market_data_ex')
    if module in ('pandas', 'numpy'):
        return value
    try:
        attrs = dict(value.__dict__)
    except (AttributeError, KeyError):
        attrs = {}
    try:
        names = dir(value)
    except (AttributeError, KeyError):
        names = set(attrs).union(dir(type(value)))
    for name in names:
        if name.startswith('m_'):
            attrs[name] = getattr(value, name)
    if attrs:
        return {key: _inner_plain(item) for key, item in attrs.items()
                if not key.startswith('_') and not callable(item)}
    raise TypeError("Unsupported native QMT result type: %s" % type(value).__name__)


def _inner_callable(bridge, owner, name):
    if owner == 'context':
        context = bridge.context
        function = getattr(context, name, None)
        if not callable(function):
            function = getattr(getattr(context, 'context', None), name, None)
    else:
        function = bridge.globals_dict.get(name)
    if not callable(function):
        raise NotImplementedError("Built-in QMT %s.%s is not available in this strategy runtime" % (owner, name))
    return function


def _inner_sessions(bridge):
    with _INNER_STATE_LOCK:
        if not hasattr(bridge, '_inner_api_sessions'):
            bridge._inner_api_sessions = {}
        return bridge._inner_api_sessions


def _inner_emit(bridge, session, token, args):
    if not session['active']:
        return
    data = {'token': token, 'args': [_inner_plain(arg) if arg is not bridge.context
                                    else {'__qmt_inner__': 'context'} for arg in args]}
    bridge._send_event(session['client_id'], 'qmt_inner:' + session['id'], data,
                       meta={'inner_client_id': session['external_client_id']})


def publish_inner_callback(bridge, name, *args):
    """Entry scripts call this with the original arguments, before compatibility formatting."""
    for session in list(getattr(bridge, '_inner_api_sessions', {}).values()):
        token = session['callbacks'].get(name)
        if token:
            _inner_emit(bridge, session, token, args)


def _inner_decode(bridge, session, value):
    if isinstance(value, list):
        return [_inner_decode(bridge, session, item) for item in value]
    if not isinstance(value, dict):
        return value
    tag = value.get('__qmt_inner__')
    if tag == 'context':
        return bridge.context
    if tag == 'datetime':
        return _inner_dt.datetime.strptime(value['value'], '%Y%m%d%H%M%S.%f')
    if tag == 'timedelta':
        return _inner_dt.timedelta(seconds=value['seconds'])
    if tag == 'callback':
        token = value['token']
        def callback(*args):
            _inner_emit(bridge, session, token, args)
        return callback
    if tag is not None:
        raise ValueError('Unknown QMT argument marker: %s' % tag)
    return {key: _inner_decode(bridge, session, item) for key, item in value.items()}


def dispatch_inner_api(bridge, action, params, msg):
    """Invoke one allowlisted native function once, in the bridge's dispatch context."""
    session_id = params.get('session_id')
    client_id = msg.get('client_id') or msg.get('reply_channel')
    if not isinstance(session_id, str) or not session_id or not client_id:
        raise ValueError('QmtInnerApi requires a session_id and client_id')
    external_id = params.get('_inner_client_id', client_id)
    sessions = _inner_sessions(bridge)
    key = (client_id, external_id, session_id)
    with _INNER_STATE_LOCK:
        session = sessions.setdefault(key, dict(id=session_id, client_id=client_id,
            external_client_id=external_id, active=True, callbacks={}, resources={}))
    if action == 'qmt_inner.capabilities':
        result = {}
        for (category, name), owner in INNER_METHODS.items():
            try:
                _inner_callable(bridge, owner, name)
                available = True
            except NotImplementedError:
                available = False
            result.setdefault(category, {})[name] = available
        return result
    if action == 'qmt_inner.context':
        name = params.get('name')
        if name not in INNER_CONTEXT_ATTRIBUTES:
            raise ValueError('Unsupported ContextInfo attribute: %s' % name)
        return _inner_plain(getattr(bridge.context, name))
    if action == 'qmt_inner.callbacks':
        name, token = params.get('name'), params.get('token')
        if name not in INNER_CALLBACKS:
            raise ValueError('Unsupported QMT callback: %s' % name)
        if token:
            session['callbacks'][name] = token
        else:
            session['callbacks'].pop(name, None)
        return True
    if action == 'qmt_inner.close':
        # Retain failed cleanup entries so an explicit close() can be retried.
        session['active'] = False
        session['callbacks'].clear()
        for resource, cleanup in list(session['resources'].items()):
            _inner_callable(bridge, cleanup[0], cleanup[1])(resource[1])
            del session['resources'][resource]
        sessions.pop(key, None)
        return True
    if action != 'qmt_inner.call':
        raise ValueError('Unsupported QmtInnerApi action: %s' % action)
    if not session['active']:
        raise RuntimeError('QmtInnerApi session is closing; retry close() to release remaining resources')
    category, name = params.get('category'), params.get('method')
    owner = inner_method_owner(category, name)
    raw_args, raw_kwargs = params.get('args', []), params.get('kwargs', {})
    if not isinstance(raw_args, list) or not isinstance(raw_kwargs, dict):
        raise TypeError('QMT arguments must be an array and a keyword object')
    function = _inner_callable(bridge, owner, name)
    args = _inner_decode(bridge, session, raw_args)
    kwargs = _inner_decode(bridge, session, raw_kwargs)
    if owner == 'context_arg':
        has_context = any(arg is bridge.context for arg in args) or any(arg is bridge.context for arg in kwargs.values())
        if not has_context:
            if kwargs:
                kwargs['ContextInfo'] = bridge.context
            else:
                args.append(bridge.context)
    # Callable timers use schedule_run and are transported via event tokens.
    result = function(*args, **kwargs)
    cleanup = {
        'subscribe_quote': ('context', 'unsubscribe_quote'),
        'subscribe_whole_quote': ('context', 'unsubscribe_quote'),
        'schedule_run': ('context', 'cancel_schedule_run'),
    }.get(name)
    if cleanup and result is not None:
        group = (args[4] if len(args) > 4 else kwargs.get('name', '')) if name == 'schedule_run' else ''
        session['resources'][(cleanup[1], result)] = cleanup + (group,)
    if name in ('unsubscribe_quote', 'cancel_schedule_run') and args:
        session['resources'].pop((name, args[0]), None)
        if name == 'cancel_schedule_run' and isinstance(args[0], str) and result:
            for resource, cleanup in list(session['resources'].items()):
                if cleanup[1] == name and cleanup[2] == args[0]:
                    del session['resources'][resource]
    return _inner_plain(result)
