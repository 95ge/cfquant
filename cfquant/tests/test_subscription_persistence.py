import tempfile
import time

from cfquant.subscription_manager import SubscriptionManager
from cfquant.subscription_store import SubscriptionStore


class Adapter:
    def __init__(self):
        self.calls = []
        self.native = {}

    def prepare(self, spec):
        result = dict(spec)
        result['route'] = {'bridge_id': 'test'}
        return result

    def control(self, spec, **params):
        self.calls.append((params['op'], params.get('key')))
        if params['op'] == 'probe':
            return {'generation': 'bridge-1', 'resources': {
                key: ({'state': 'active', 'native_id': self.native[key]}
                      if key in self.native else {'state': 'missing'})
                for key in params['keys']}}
        if params['op'] == 'ensure':
            value = len(self.native) + 10
            self.native[params['key']] = value
            return {'generation': 'bridge-1', 'native_id': value}
        if params['op'] == 'release':
            self.native.pop(params['key'], None)
            return {'state': 'released', 'generation': 'bridge-1'}
        raise AssertionError(params)

    def emit(self, *args):
        pass


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    assert predicate()


def new_store():
    handle = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
    handle.close()
    return handle.name


def open_session(manager, owner, secret, client='client'):
    handshake = manager.handle({'op': 'open', 'owner': owner, 'secret': secret}, client)
    return dict(owner=owner, **handshake)


def test_sqlite_intent_waits_for_current_client_and_recovers_after_manager_restart():
    path = new_store()
    owner, secret = 'owner-' + ('a' * 27), 'secret-' + ('b' * 25)
    adapter = Adapter()
    manager = SubscriptionManager(SubscriptionStore(path), adapter, start=False)
    base = open_session(manager, owner, secret)
    manager.handle(dict(op='sync', revision=0, specs=[{
        'id': '1', 'action': 'xtdata.subscribe_whole_quote', 'params': {'code_list': ['SH']},
    }], **base), 'client')
    manager.tick()
    wait_for(lambda: manager.status(owner)['1']['state'] == 'active')
    assert adapter.native
    manager.close()

    # A new service boot does not restore from the database until this client
    # completes the new handshake and submits its current manifest.
    adapter2 = Adapter()
    manager2 = SubscriptionManager(SubscriptionStore(path), adapter2, start=False)
    assert manager2.store.rows(owner)[0]['desired']
    assert adapter2.calls == []
    manager2.tick()
    time.sleep(.05)
    assert adapter2.calls == []
    base2 = open_session(manager2, owner, secret)
    manager2.handle(dict(op='sync', revision=0, specs=[{
        'id': '1', 'action': 'xtdata.subscribe_whole_quote', 'params': {'code_list': ['SH']},
    }], **base2), 'client')
    manager2.tick()
    wait_for(lambda: manager2.status(owner)['1']['state'] == 'active')
    wait_for(lambda: [call[0] for call in adapter2.calls] == ['probe', 'ensure'])
    manager2.close()


def test_manifest_cancellation_is_persisted_before_resource_release():
    path = new_store()
    owner, secret = 'owner-' + ('c' * 27), 'secret-' + ('d' * 25)
    adapter = Adapter()
    manager = SubscriptionManager(SubscriptionStore(path), adapter, start=False)
    base = open_session(manager, owner, secret)
    manager.handle(dict(op='sync', revision=0, specs=[{
        'id': '1', 'action': 'xtdata.subscribe_quote', 'params': {'stock_code': '000001.SZ'},
    }], **base), 'client')
    manager.tick()
    wait_for(lambda: manager.status(owner)['1']['state'] == 'active')
    manager.handle(dict(op='sync', revision=1, specs=[], **base), 'client')
    assert manager.store.rows(owner)[0]['desired'] == 0
    manager.tick()
    wait_for(lambda: manager.status(owner)['1']['state'] == 'released')
    assert adapter.native == {}
    manager.close()
