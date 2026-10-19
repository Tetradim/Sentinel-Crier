import httpx
import pytest
from crier.store import Store
from crier.config import Config


def activity(id='a1', **changes):
    return dict(id=id, activity_type='FILL', type='fill', order_id='o1',
                symbol='AAPL', side='buy', qty='1', cum_qty='1', leaves_qty='0',
                price='10.25', transaction_time='2026-10-19T14:30:00Z') | changes


def poll(store, pages, **kwargs):
    from crier import alpaca
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.url.host == ('api.alpaca.markets' if kwargs.get('environment') == 'live' else 'paper-api.alpaca.markets')
        assert request.url.path == '/v2/account/activities/FILL'
        value = pages[len(requests)-1]
        if isinstance(value, int): return httpx.Response(value)
        return httpx.Response(200, json=value)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = alpaca.poll_once(store, client, 'account', **kwargs)
    return result, requests


def test_monitor_configuration(tmp_path):
    assert Config(data_dir=tmp_path, monitor='alpaca').monitor == 'alpaca'


def test_enrollment_restart_incremental_and_duplicate(tmp_path):
    store = Store(tmp_path/'db')
    poll(store, [[activity(type='partial_fill', leaves_qty='1')]])
    assert store.history() == []
    store = Store(tmp_path/'db')
    row = activity('a2', qty='1', cum_qty='2', price='11.25')
    _, requests = poll(store, [[row]])
    assert requests[0].url.params['page_token'] == 'a1'
    assert store.history()[0]['fill']['price'] == '11.25'
    assert store.history()[0]['fill']['quantity'] == '1'
    poll(store, [[row]])
    assert len(store.history()) == 1


def test_empty_initial_history_then_external_option_trade(tmp_path):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    poll(store, [[activity(symbol='SPY261120C00600000', side='sell')]])
    fill = store.history()[0]['fill']
    assert fill['category'] == 'US_OPTION'
    assert fill['side'] == 'SELL' and fill['intent'] == 'UNKNOWN'
    assert fill['environment'] == 'sandbox'


def test_pagination_and_failure_leave_baseline_unenrolled(tmp_path, monkeypatch):
    from crier import alpaca
    monkeypatch.setattr(alpaca, 'PAGE_SIZE', 1)
    store = Store(tmp_path/'db')
    with pytest.raises(httpx.HTTPStatusError): poll(store, [[activity()], 503])
    assert store.history() == []
    _, requests = poll(store, [[activity()], []])
    assert requests[1].url.params['page_token'] == 'a1'
    assert store.history() == []


@pytest.mark.parametrize('changes', [dict(qty='NaN'), dict(side='unknown'), dict(cum_qty='2'), dict(symbol='BTC/USD'), dict(transaction_time='2026-10-19'), dict(type='correction')])
def test_bad_batch_never_advances_cursor(tmp_path, changes):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    with pytest.raises(ValueError): poll(store, [[activity(**changes)]])
    assert store.history() == []
    poll(store, [[activity()]])
    assert len(store.history()) == 1


def test_environment_scopes_and_live_host(tmp_path):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    poll(store, [[activity()]])
    poll(store, [[activity()]], environment='live')
    assert len(store.history()) == 1
    with pytest.raises(ValueError): poll(store, [[]], environment='production')


def test_whole_batch_rolls_back_on_later_invalid_fill(tmp_path):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    with pytest.raises(ValueError):
        poll(store, [[activity(), activity('a2', order_id='o2', side='bad')]])
    assert store.history() == []
    poll(store, [[activity()]])
    assert len(store.history()) == 1


def test_same_activity_id_changed_is_not_silently_accepted(tmp_path):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    poll(store, [[activity()]])
    with pytest.raises(ValueError): poll(store, [[activity(price='99')]])
    assert store.history()[0]['fill']['price'] == '10.25'


def test_observe_authentication_and_paper_default(tmp_path, monkeypatch):
    from crier import alpaca
    monkeypatch.setenv('APCA_API_KEY_ID', 'test-key')
    monkeypatch.setenv('APCA_API_SECRET_KEY', 'test-secret')
    monkeypatch.delenv('ALPACA_ENV', raising=False)
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'paper-api.alpaca.markets'
        assert request.headers['APCA-API-KEY-ID'] == 'test-key'
        assert request.headers['APCA-API-SECRET-KEY'] == 'test-secret'
        return httpx.Response(200, json={'id': 'account'} if request.url.path == '/v2/account' else [])
    client_type = httpx.Client
    monkeypatch.setattr(alpaca.httpx, 'Client', lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw))
    def stop(_): raise KeyboardInterrupt
    monkeypatch.setattr(alpaca.time, 'sleep', stop)
    with pytest.raises(KeyboardInterrupt): alpaca.observe(Config(data_dir=tmp_path))
    assert len(requests) == 2
    assert 'test-secret' not in (tmp_path/'crier.sqlite3').read_bytes().decode('utf8', errors='ignore')


def test_repeating_full_page_is_rejected(tmp_path, monkeypatch):
    from crier import alpaca
    monkeypatch.setattr(alpaca, 'PAGE_SIZE', 1)
    store = Store(tmp_path/'db')
    with pytest.raises(ValueError): poll(store, [[activity()], [activity()]])
    assert store.history() == []


def test_decimal_weighted_average_keeps_exact_execution_price(tmp_path):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    poll(store, [[activity(qty='2', cum_qty='2', price='1.25', type='partial_fill', leaves_qty='1'),
                  activity('a2', qty='1', cum_qty='3', price='1.50')]])
    fills = {f['fill']['cumulative_qty']: f['fill'] for f in store.history()}
    assert fills['3']['price'] == '1.5'
    assert fills['3']['quantity'] == '1'


def test_store_exact_price_rejects_inconsistent_override(tmp_path):
    from decimal import Decimal
    from crier import alpaca
    store = Store(tmp_path/'db')
    snap, _ = alpaca.normalize(activity(), 'account', 'paper')
    with pytest.raises(ValueError):
        with store.connect() as db:
            store.ingest_in_transaction(db, snap, store.get_settings(), execution_price=Decimal('99'))
    assert store.history() == []


def test_nine_decimal_fractional_stock_fill(tmp_path):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    poll(store, [[activity(qty='0.123456789', cum_qty='0.123456789')]])
    assert store.history()[0]['fill']['quantity'] == '0.123456789'


@pytest.mark.parametrize('value', ['1e999999999', '1e-999999999'])
def test_extreme_numeric_input_is_controlled_failure(tmp_path, value):
    store = Store(tmp_path/'db')
    poll(store, [[]])
    with pytest.raises(ValueError): poll(store, [[activity(price=value)]])
    assert store.history() == []
