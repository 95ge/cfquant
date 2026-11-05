"""External access to built-in QMT, organized like the official innerApi manual.

    with QmtInnerApi(bridge_id="default") as qmt:
        ticks = qmt.market.get_full_tick(["000001.SZ"])

The QMT bridge must be running. ContextInfo always belongs to that strategy;
this client does not create a separate strategy or backtest engine.
"""
import datetime
import threading
import uuid

from .client import create_rpc_client
from .channels import channels_for_bridge
from .config import get_config
from .qmt_inner_catalog import (
    INNER_CATEGORIES, INNER_DOC_ROOT, INNER_METHODS, INNER_CALLBACKS, INNER_CONTEXT_ATTRIBUTES,
    inner_method_owner,
)


class QmtRecord(dict):
    """Native fields, accessible both as row.m_nVolume and row['m_nVolume']."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _records(value, api):
    if isinstance(value, list):
        return [_records(item, api) for item in value]
    if isinstance(value, dict):
        if value == {'__qmt_inner__': 'context'}:
            return api.context
        return QmtRecord((key, _records(item, api)) for key, item in value.items())
    return value


class QmtContext:
    """Remote ContextInfo reference; attributes are read from the bound QMT strategy."""
    def __init__(self, api):
        self._api = api

    def __getattr__(self, name):
        for (category, method), owner in INNER_METHODS.items():
            if name == method and owner == 'context':
                return getattr(getattr(self._api, category), method)
        if name not in INNER_CONTEXT_ATTRIBUTES:
            raise AttributeError(name)
        return self._api._request('context', name=name)


class _QmtCategory:
    category = ''

    def __init__(self, api):
        self._api = api

    def _call(self, method, *args, **kwargs):
        return self._api.call(self.category, method, *args, **kwargs)


class QmtSystem(_QmtCategory):
    category = 'system'

    def set_account(self, accountid):
        return self._call('set_account', accountid)

    def schedule_run(self, func, time_point, repeat_times=0, interval=None, name=''):
        return self._call('schedule_run', func, time_point, repeat_times, interval, name)

    def cancel_schedule_run(self, key):
        return self._call('cancel_schedule_run', key)

class QmtMarket(_QmtCategory):
    category = 'market'

    def get_market_data_ex(self, fields=None, stock_code=None, period='follow', start_time='',
                           end_time='', count=-1, dividend_type='follow', fill_data=True, subscribe=True):
        return self._call('get_market_data_ex', [] if fields is None else fields,
                          [] if stock_code is None else stock_code, period, start_time, end_time,
                          count, dividend_type, fill_data, subscribe)

    def get_full_tick(self, stock_code=None):
        return self._call('get_full_tick', [] if stock_code is None else stock_code)

    def get_trading_dates(self, stockcode, start_date, end_date, count, period='1d'):
        return self._call('get_trading_dates', stockcode, start_date, end_date, count, period)

    def subscribe_quote(self, stock_code, period='follow', dividend_type='follow', result_type='', callback=None):
        return self._call('subscribe_quote', stock_code, period, dividend_type, result_type, callback)

    def subscribe_whole_quote(self, code_list, callback=None):
        return self._call('subscribe_whole_quote', code_list, callback)

    def unsubscribe_quote(self, subId):
        return self._call('unsubscribe_quote', subId)


class QmtTrade(_QmtCategory):
    category = 'trade'

    def passorder(self, opType, orderType, accountid, orderCode, prType, price, volume, *args, **kwargs):
        """Native overloads: optional strategyName, quickTrade, userOrderId; ContextInfo is automatic.

        QMT's return value is preserved (often None); it is not a broker order ID.
        Never automatically retry a timed out order.
        """
        # Optional native arguments are positional because QMT builds differ in
        # their Boost.Python keyword support. Keep short and long overloads intact.
        if kwargs:
            raise TypeError('Pass optional passorder parameters positionally in QMT documentation order')
        return self._call('passorder', opType, orderType, accountid, orderCode, prType, price, volume, *args)

    def cancel(self, orderId, accountId, accountType):
        return self._call('cancel', orderId, accountId, accountType)

    def get_trade_detail_data(self, accountID, strAccountType, strDatatype, strategyName=None):
        args = (accountID, strAccountType, strDatatype)
        if strategyName is not None:
            args += (strategyName,)
        return self._call('get_trade_detail_data', *args)

    def get_last_order_id(self, accountID, strAccountType, strDatatype, strategyName=None):
        args = (accountID, strAccountType, strDatatype)
        if strategyName is not None:
            args += (strategyName,)
        return self._call('get_last_order_id', *args)


class QmtReference(_QmtCategory):
    category = 'reference'


class QmtCallbacks:
    """Register native callback names. Handler receives (qmt.context, *native_args)."""
    def __init__(self, api):
        self._api = api
        self._tokens = {}

    def register(self, name, callback):
        if name not in INNER_CALLBACKS:
            raise ValueError('Unknown built-in QMT callback: %s' % name)
        if not callable(callback):
            raise TypeError('callback must be callable')
        token = self._api._add_callback(callback)
        try:
            result = self._api._request('callbacks', name=name, token=token)
        except Exception:
            self._api._handlers.pop(token, None)
            raise
        previous = self._tokens.get(name)
        self._tokens[name] = token
        self._api._handlers.pop(previous, None)
        return result

    def unregister(self, name):
        result = self._api._request('callbacks', name=name, token=None)
        self._api._handlers.pop(self._tokens.pop(name, None), None)
        return result


class QmtInnerApi:
    """Independent native API session over cfquant RPC, always using the normal bridge.

    ``account_id``/``account_type`` select the Web route; native function arguments
    still specify the trading account. ``client`` may inject an existing RPC client;
    its connection remains owned by the caller. close() releases this session's
    native quote subscriptions and schedule_run timers.
    """
    def __init__(self, bridge_id=None, account_id=None, account_type='STOCK', account_key=None,
                 transport=None, request_channel=None, timeout=12.0, client=None):
        self._session_id = uuid.uuid4().hex
        self._event = 'qmt_inner:' + self._session_id
        self._handlers = {}
        self._resource_tokens = {}
        self._lock = threading.RLock()
        self._closed = False
        self._used = False
        self._owns_client = client is None
        self._timeout = timeout
        bridge_id = bridge_id or get_config().get('bridge_id') or 'default'
        channel = request_channel or channels_for_bridge(bridge_id)['normal']
        self._client = client or create_rpc_client(transport=transport, timeout=timeout,
                                                   request_channel=channel, bridge_id=bridge_id)
        self._route = dict(bridge_id=bridge_id, account_id=account_id or '',
                           account_type=account_type, account_key=account_key or '', default_channel='normal')
        self.context = QmtContext(self)
        self.system, self.market, self.trade = QmtSystem(self), QmtMarket(self), QmtTrade(self)
        self.callbacks = QmtCallbacks(self)
        self.reference = QmtReference(self)
        self._client.add_callback(self._event, self._on_event)

    def _request(self, action, **params):
        if self._closed:
            raise RuntimeError('QmtInnerApi is closed')
        self._used = True
        payload = dict(self._route, session_id=self._session_id, **params)
        return _records(self._client.request('qmt_inner.' + action, payload, timeout=self._timeout), self)

    def _add_callback(self, callback):
        token = uuid.uuid4().hex
        self._handlers[token] = callback
        return token

    def _encode(self, value, tokens):
        if value is self.context:
            return {'__qmt_inner__': 'context'}
        if isinstance(value, QmtContext):
            raise ValueError('Cannot use ContextInfo from another QmtInnerApi session')
        if callable(value):
            token = self._add_callback(value)
            tokens.append(token)
            return {'__qmt_inner__': 'callback', 'token': token}
        if isinstance(value, datetime.datetime):
            if value.tzinfo is not None:
                raise ValueError('QMT schedule_run expects a naive local datetime')
            return {'__qmt_inner__': 'datetime', 'value': value.strftime('%Y%m%d%H%M%S.%f')}
        if isinstance(value, datetime.timedelta):
            return {'__qmt_inner__': 'timedelta', 'seconds': value.total_seconds()}
        if isinstance(value, (list, tuple)):
            return [self._encode(item, tokens) for item in value]
        if isinstance(value, dict):
            if '__qmt_inner__' in value:
                raise ValueError('__qmt_inner__ is a reserved wire marker')
            return {key: self._encode(item, tokens) for key, item in value.items()}
        return value

    def call(self, category, method, *args, **kwargs):
        """Call a documented native method, preserving overloads and original spelling."""
        inner_method_owner(category, method)
        tokens = []
        try:
            encoded_args = self._encode(args, tokens)
            encoded_kwargs = self._encode(kwargs, tokens)
            result = self._request('call', category=category, method=method,
                                   args=encoded_args, kwargs=encoded_kwargs)
            cleanup = {'subscribe_quote': 'unsubscribe_quote', 'subscribe_whole_quote': 'unsubscribe_quote',
                       'schedule_run': 'cancel_schedule_run'}.get(method)
            if cleanup and result is not None:
                self._resource_tokens[(cleanup, result)] = tokens
            if method in ('unsubscribe_quote', 'cancel_schedule_run') and args:
                for token in self._resource_tokens.pop((method, args[0]), []):
                    self._handlers.pop(token, None)
            return result
        except Exception:
            for token in tokens:
                self._handlers.pop(token, None)
            raise

    def capabilities(self):
        """Probe callable availability without executing native functions."""
        return self._request('capabilities')

    def _on_event(self, data):
        payload = data
        handler = self._handlers.get(payload.get('token'))
        if handler is not None and not self._closed:
            handler(*_records(payload.get('args', []), self))

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self._used:
                self._request('close')
            self._client.remove_callback(self._event, self._on_event)
            self._handlers.clear()
            self._resource_tokens.clear()
            self._closed = True
            if self._owns_client:
                self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def _install_native_methods():
    classes = {cls.category: cls for cls in (QmtSystem, QmtMarket, QmtTrade, QmtReference)}
    def make_method(category, name):
        def method(self, *args, **kwargs):
            return self._call(name, *args, **kwargs)
        method.__name__ = name
        method.__qualname__ = classes[category].__name__ + '.' + name
        method.__doc__ = ('Native QMT %s; pass arguments in documentation order, omitting ContextInfo.\n%s'
                          % (name, INNER_DOC_ROOT + INNER_CATEGORIES[category]))
        return method
    for category, name in INNER_METHODS:
        if not hasattr(classes[category], name):
            setattr(classes[category], name, make_method(category, name))
    def make_callback_registration(name):
        def register(self, callback):
            return self.register(name, callback)
        register.__name__ = name
        register.__doc__ = 'Register the external handler for native ' + name
        return register
    for name in INNER_CALLBACKS:
        setattr(QmtCallbacks, name, make_callback_registration(name))


_install_native_methods()
__all__ = ['QmtInnerApi', 'QmtContext', 'QmtRecord', 'QmtSystem', 'QmtMarket', 'QmtTrade',
           'QmtCallbacks', 'QmtReference']
