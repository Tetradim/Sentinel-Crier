from decimal import Decimal

import httpx
import pytest

from crier.store import Store
from crier import tradier


def order(**changes):
    return dict(id=42, **{'class': 'option'}, type='limit', symbol='SPY',
                option_symbol='SPY261016C00600000', side='buy_to_open',
                quantity='3', exec_quantity='1', avg_fill_price='1.25',
                transaction_date='2026-10-13T14:42:18Z', status='partially_filled') | changes


def client_for(pages):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'sandbox.tradier.com'
        item = pages[int(request.url.params['page']) - 1]
        if isinstance(item, Exception): raise item
        return httpx.Response(200, json=item)
    return httpx.Client(transport=httpx.MockTransport(handle)), requests


def poll(db, rows, verified=True):
    client, _ = client_for([{'orders': {'order': rows}}])
    with client:
        return tradier.poll_once(db, client, 'account', verified=verified)


def test_normalization_preserves_cumulative_values_and_time_provenance():
    snap = tradier.normalize(order(), 'account')
    assert snap.broker == 'tradier'
    assert snap.intent == 'OPEN'
    assert snap.cumulative_qty == Decimal('1')
    assert snap.average_price == Decimal('1.25')
    assert snap.time_basis == 'order_updated'
    assert snap.symbol == 'SPY261016C00600000'


@pytest.mark.parametrize('changes', [
    {'class': 'multileg'}, {'leg': [{}]}, {'side': 'buy'},
    {'exec_quantity': 'NaN'}, {'exec_quantity': True}, {'avg_fill_price': '0'},
    {'transaction_date': None}, {'transaction_date': '2026-10-13'},
    {'exec_quantity': '4'}, {'status': 'filled'}, {'id': '../x'},
])
def test_ambiguous_order_is_held(changes):
    with pytest.raises(ValueError): tradier.normalize(order(**changes), 'account')


def test_equity_side_and_zero_fill():
    snap = tradier.normalize(order(**{'class': 'equity', 'side': 'sell_short',
                                      'symbol': 'AAPL', 'option_symbol': None}), 'account')
    assert (snap.category, snap.side, snap.intent) == ('US_STOCK', 'SELL', 'OPEN')
    assert tradier.normalize(order(exec_quantity='0', status='open'), 'account') is None


def test_first_baseline_then_increment_and_restart(tmp_path):
    db = Store(tmp_path / 'db')
    assert poll(db, [order()])['state'] == 'observing'
    assert not db.history()
    poll(db, [order(exec_quantity='2', avg_fill_price='1.50')])
    assert db.history()[0]['fill']['quantity'] == '1'
    assert db.history()[0]['fill']['price'] == '1.75'
    db = Store(tmp_path / 'db')
    poll(db, [order(exec_quantity='3', avg_fill_price='1.50', status='filled')])
    poll(db, [order(exec_quantity='3', avg_fill_price='1.50', status='filled')])
    assert len(db.history()) == 2


def test_failed_baseline_does_not_partially_ingest(tmp_path):
    db = Store(tmp_path / 'db')
    with pytest.raises(ValueError): poll(db, [order(), order(id=43, leg=[{}])])
    with db.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
    poll(db, [order(exec_quantity='2')])
    assert not db.history()
    poll(db, [order(exec_quantity='3', status='filled')])
    assert db.history()[0]['fill']['quantity'] == '1'


def test_capture_mode_never_seeds_publish_watermarks(tmp_path):
    db = Store(tmp_path / 'db')
    assert poll(db, [order()], verified=False)['state'] == 'capture_only'
    poll(db, [order(exec_quantity='2')])
    assert not db.history()
    poll(db, [order(exec_quantity='3', status='filled')])
    assert db.history()[0]['fill']['quantity'] == '1'


def test_pagination_failure_and_repeated_page_do_not_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(tradier, 'PAGE_SIZE', 1)
    db = Store(tmp_path / 'db')
    for pages in ([{'orders': {'order': order()}}, httpx.ReadTimeout('private')],
                  [{'orders': {'order': order()}}, {'orders': {'order': order()}}]):
        client, requests = client_for(pages)
        with client, pytest.raises((ValueError, httpx.HTTPError)):
            tradier.poll_once(db, client, 'account', verified=True)
        assert len(requests) == 2
        with db.connect() as con:
            assert con.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0


def test_complete_pagination_and_empty_session(tmp_path, monkeypatch):
    monkeypatch.setattr(tradier, 'PAGE_SIZE', 1)
    db = Store(tmp_path / 'db')
    client, requests = client_for([{'orders': {'order': order()}}, {'orders': 'null'}])
    with client: tradier.poll_once(db, client, 'account', verified=True)
    assert len(requests) == 2
    monkeypatch.setattr(tradier, 'PAGE_SIZE', 1000)
    poll(db, order(id=43))
    assert len(db.history()) == 1


def test_interrupted_baseline_replays_frozen_quantities(tmp_path, monkeypatch):
    db = Store(tmp_path / 'db')
    original = db.ingest
    calls = 0
    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2: raise RuntimeError('simulated crash')
        return original(*args, **kwargs)
    monkeypatch.setattr(db, 'ingest', interrupted)
    with pytest.raises(RuntimeError): poll(db, [order(), order(id=43)])
    db = Store(tmp_path / 'db')
    poll(db, [order(exec_quantity='2'), order(id=43, exec_quantity='2')])
    assert len(db.history()) == 2
    assert all(row['fill']['quantity'] == '1' for row in db.history())


@pytest.mark.parametrize('body', [{}, {'orders': {}}, {'orders': {'order': 'bad'}}])
def test_unknown_response_shape_never_advances(tmp_path, body):
    db = Store(tmp_path / 'db')
    client, _ = client_for([body])
    with client, pytest.raises(ValueError): tradier.poll_once(db, client, 'account', verified=True)
    assert not db.history()



def test_empty_baseline_allows_first_later_fill(tmp_path):
    db = Store(tmp_path / 'db')
    poll(db, [])
    poll(db, [order()])
    assert len(db.history()) == 1


def test_canceled_partially_executed_order_preserves_execution(tmp_path):
    db = Store(tmp_path / 'db')
    poll(db, [])
    poll(db, [order(status='canceled')])
    fill = db.history()[0]['fill']
    assert fill['quantity'] == '1'
    assert fill['time_basis'] == 'order_updated'


def test_http_error_and_redirect_do_not_advance_baseline(tmp_path):
    for status in (302, 401, 429, 500):
        db = Store(tmp_path / str(status))
        calls = []
        def response(request):
            calls.append(request)
            return httpx.Response(status, headers={'Location': 'https://attacker.invalid/'})
        with httpx.Client(transport=httpx.MockTransport(response), follow_redirects=True) as client:
            with pytest.raises(httpx.HTTPStatusError):
                tradier.poll_once(db, client, 'account', verified=True)
        assert len(calls) == 1
        with db.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM config WHERE id LIKE 'tradier_baseline:%'").fetchone()[0] == 0


def test_bad_account_or_environment_is_rejected_before_request(tmp_path):
    db = Store(tmp_path / 'db')
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('unexpected request'))) as client:
        for account, environment in (('../elsewhere', 'sandbox'), ('a', 'https://other.invalid')):
            with pytest.raises(ValueError):
                tradier.poll_once(db, client, account, environment, True)


def test_later_malformed_poll_does_not_consume_valid_fill(tmp_path):
    db = Store(tmp_path / 'db')
    poll(db, [])
    with pytest.raises(ValueError): poll(db, [order(), order(id=43, leg=[{}])])
    assert not db.history()
    poll(db, [order()])
    assert len(db.history()) == 1


def test_capture_preserves_unsupported_evidence_without_watermarks(tmp_path):
    import json
    db = Store(tmp_path / 'db')
    rows = [order(), order(id=43, leg=[{'private': 'evidence'}])]
    result = poll(db, rows, verified=False)
    assert result['state'] == 'capture_only'
    assert result['invalid_orders'] == 1
    assert result['fills'] == 1
    with db.connect() as con:
        observed = con.execute("SELECT data FROM audit WHERE outcome='tradier_observed'").fetchone()
        assert json.loads(observed[0])['orders'] == rows
        assert con.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM config WHERE id LIKE 'tradier_baseline:%'").fetchone()[0] == 0
    assert not db.history()


def test_verified_unsupported_batch_keeps_evidence_and_holds_watermarks(tmp_path):
    import json
    db = Store(tmp_path / 'db')
    rows = [order(), order(id=43, leg=[{}])]
    with pytest.raises(ValueError): poll(db, rows)
    with db.connect() as con:
        observed = con.execute("SELECT data FROM audit WHERE outcome='tradier_observed'").fetchone()
        assert observed is not None
        assert json.loads(observed[0])['orders'] == rows
        assert con.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
    assert not db.history()
