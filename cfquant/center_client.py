"""SDK requests through the independent center, account callbacks through LTtx."""
import threading

from .client import WebLttxRpcClient
from .bridge_center import CENTER_CHANNEL
from .market_channel import ChannelSubscription


class CenterRpcClient(WebLttxRpcClient):
    def __init__(self, request_channel=None, registry=None, **kwargs):
        self.bridge_request_channel = ('trade' if str(request_channel).endswith('.trade.request') else
                                       'normal' if str(request_channel).endswith('.normal.request') else request_channel)
        self.registry = registry or {}
        self._account_channels = {}
        self._account_lock = threading.RLock()
        self._web_services = None
        super().__init__(request_channel=self.registry.get('center_request_channel') or CENTER_CHANNEL,
                         registry=self.registry or {'center_request_channel': CENTER_CHANNEL}, **kwargs)

    def request(self, action, params=None, timeout=None, request_channel=None, response_meta=None):
        # Application services retain their Web lifecycle; raw market/trading IO does not.
        from .algo import ALGO_ACTIONS
        from .smart_orders import SMART_ACTIONS
        if action in ALGO_ACTIONS or action in SMART_ACTIONS or action == 'cfquant.notify.send':
            with self._account_lock:
                if self._web_services is None:
                    self._web_services = WebLttxRpcClient(host=self.host, port=self.port, token=self.token,
                                                        timeout=self.timeout)
                service = self._web_services
            return service.request(action, params, timeout=timeout, response_meta=response_meta)
        params = dict(params or {})
        channel = request_channel or self.bridge_request_channel
        if channel:
            params['_center_request_channel'] = channel
        if action in ('xttrader.subscribe', 'xttrader.unsubscribe', 'cfquant.account_subscription_status'):
            route = super().request('cfquant.center.route', dict(params, action=action), timeout=timeout)
            # Also work with centers started before callback-owner routing was
            # fixed: the pipe normal endpoint owns native account callbacks.
            if route.get('mode') in ('ctypes', 'lite', 'lite_advanced'):
                params['_center_request_channel'] = 'normal'
            if action == 'cfquant.account_subscription_status':
                return super().request(action, params, timeout=timeout, response_meta=response_meta)
            event_channel = route['event_channel']
            with self._account_lock:
                existing = self._account_channels.get(event_channel)
                if action == 'xttrader.unsubscribe':
                    if existing:
                        self._account_channels.pop(event_channel).close()
                    return 0
                if existing is None:
                    cfg = dict(host=self.host, port=self.port, token=self.token)
                    subscription = ChannelSubscription(self._dispatch_event, channel=event_channel,
                                                       config=cfg, event=True)
                    self._account_channels[event_channel] = subscription
                    try:
                        subscription.start()
                    except BaseException:
                        self._account_channels.pop(event_channel, None)
                        raise
        return super().request(action, params, timeout=timeout, response_meta=response_meta)

    def close(self):
        with self._account_lock:
            subscriptions = list(self._account_channels.values())
            self._account_channels.clear()
        for subscription in subscriptions:
            subscription.close()
        if self._web_services is not None:
            self._web_services.close()
            self._web_services = None
        super().close()

    def callback_status(self):
        result = super().callback_status()
        with self._account_lock:
            result['account_channels'] = {key: sub.status() for key, sub in self._account_channels.items()}
        return result
