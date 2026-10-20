from datetime import datetime, timezone, timedelta
import pytest
from crier.mirror import Mirror, MirrorEvent

class Broker:
    environment = 'paper'
    def __init__(self): self.posts = []; self.orders = {}; self.available = 5; self.fail = False; self.account_id = 'receiver'
    def account(self): return {'id': self.account_id, 'status': 'ACTIVE', 'trading_blocked': False, 'account_blocked': False, 'options_trading_level': 2}
    def validate(self, event):
        if event.side == 'sell' and event.quantity > self.available: raise ValueError('Insufficient available holdings')
    def lookup(self, client_id): return self.orders.get(client_id)
    def submit(self, body):
        self.posts.append(body)
        if self.fail: raise TimeoutError()
        result = dict(body, id='broker-order', status='accepted', filled_qty='0')
        self.orders[body['client_order_id']] = result
        return result

def event(**changes):
    return MirrorEvent(**(dict(event_id='fill-1', environment='paper', symbol='SPY261212C00750000', side='buy', intent='buy_to_open', quantity=2, price='1.25', occurred_at=datetime.now(timezone.utc)) | changes))

@pytest.fixture
def setup(tmp_path):
    broker = Broker(); mirror = Mirror(tmp_path/'mirror.db', broker)
    pair = mirror.pair('Customer')
    mirror.follow(pair['id'], True)
    return mirror, broker, pair

def test_duplicate_survives_restart(setup, tmp_path):
    mirror, broker, pair = setup; fill = event()
    assert mirror.receive(pair['token'], fill)['state'] == 'accepted'
    again = Mirror(tmp_path/'mirror.db', broker)
    assert again.receive(pair['token'], fill)['state'] == 'accepted'
    assert len(broker.posts) == 1
    assert broker.posts[0]['symbol'] == fill.symbol
    assert broker.posts[0]['qty'] == '2'

def test_changed_event_identity_is_rejected(setup):
    mirror, broker, pair = setup; fill = event(); mirror.receive(pair['token'], fill)
    with pytest.raises(ValueError): mirror.receive(pair['token'], fill.model_copy(update={'quantity': 3}))
    assert len(broker.posts) == 1

@pytest.mark.parametrize('changes', [dict(environment='live'), dict(occurred_at=datetime.now(timezone.utc)-timedelta(minutes=2)), dict(occurred_at=datetime.now(timezone.utc)+timedelta(minutes=2))])
def test_invalid_context_cannot_trade(setup, changes):
    mirror, broker, pair = setup
    with pytest.raises(ValueError): mirror.receive(pair['token'], event(**changes))
    assert broker.posts == []

def test_paused_fill_never_replays_after_resume(setup):
    mirror, broker, pair = setup; mirror.follow(pair['id'], False); fill = event()
    assert mirror.receive(pair['token'], fill)['state'] == 'skipped'
    mirror.follow(pair['id'], True)
    assert mirror.receive(pair['token'], fill)['state'] == 'skipped'
    assert broker.posts == []

def test_unknown_submission_is_not_reposted(setup):
    mirror, broker, pair = setup; broker.fail = True; fill = event()
    assert mirror.receive(pair['token'], fill)['state'] == 'unknown'
    assert mirror.receive(pair['token'], fill)['state'] == 'unknown'
    assert mirror.receive(pair['token'], event(event_id='fill-2'))['state'] == 'skipped'
    assert len(broker.posts) == 1

def test_sell_checks_holdings(setup):
    mirror, broker, pair = setup; broker.available = 0
    assert mirror.receive(pair['token'], event(side='sell', intent='sell_to_close'))['state'] == 'skipped'
    assert broker.posts == []

def test_account_is_pinned(setup):
    mirror, broker, pair = setup; broker.account_id = 'different'
    assert mirror.receive(pair['token'], event())['state'] == 'skipped'
    assert broker.posts == []

def test_revoked_pair_cannot_submit(setup):
    mirror, broker, pair = setup; mirror.revoke(pair['id'])
    with pytest.raises(PermissionError): mirror.receive(pair['token'], event())
    assert broker.posts == []

@pytest.mark.parametrize('changes', [dict(price='NaN'), dict(price='0'), dict(quantity=1.5), dict(intent='sell_to_open'), dict(symbol='SPY261332C00750000'), dict(occurred_at=datetime.now())])
def test_event_validation(changes):
    with pytest.raises(ValueError): event(**changes)

def test_unknown_reconciles_without_posting_again(setup):
    mirror, broker, pair = setup; broker.fail = True; fill = event()
    mirror.receive(pair['token'], fill)
    body = broker.posts[0]
    broker.orders[body['client_order_id']] = dict(body, id='recovered', status='filled', filled_qty='2')
    mirror.reconcile()
    assert mirror.receive(pair['token'], fill)['state'] == 'filled'
    assert len(broker.posts) == 1

def test_concurrent_duplicate_posts_once(setup):
    from concurrent.futures import ThreadPoolExecutor
    mirror, broker, pair = setup; fill = event()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: mirror.receive(pair['token'], fill), range(20)))
    assert len(broker.posts) == 1
    assert all(r['state'] == 'accepted' for r in results)

def test_partial_executions_use_incremental_quantity(setup):
    mirror, broker, pair = setup
    mirror.receive(pair['token'], event(event_id='execution-1', quantity=2))
    mirror.receive(pair['token'], event(event_id='execution-2', quantity=3))
    assert [p['qty'] for p in broker.posts] == ['2', '3']

def test_broker_adapter_uses_official_stock_class_and_no_redirects():
    import httpx
    from crier.mirror import AlpacaMirrorBroker
    def handle(request):
        assert request.url.host == 'paper-api.alpaca.markets'
        if request.url.path == '/v2/clock': return httpx.Response(200, json={'is_open':True})
        if request.url.path == '/v2/assets/AAPL': return httpx.Response(200, json={'class':'us_equity', 'status':'active', 'tradable':True})
        if request.url.path == '/v2/positions': return httpx.Response(200, json=[])
        raise AssertionError(request.url)
    broker = AlpacaMirrorBroker('paper','test-key','test-secret',httpx.Client(transport=httpx.MockTransport(handle)))
    broker.validate(event(symbol='AAPL'))
