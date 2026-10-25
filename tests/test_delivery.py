import httpx
import pytest
from crier.store import Store
from crier.models import Settings
from crier.delivery import deliver_once
from test_core import event

URL = "https://discord.com/api/webhooks/123456789012345678/example-token"

def prepared(tmp_path):
    db = Store(tmp_path / "db")
    db.ingest(event(), Settings())
    return db

def test_success_records_discord_message_id(tmp_path):
    db = prepared(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={"id":"987"}))) as client:
        deliver_once(db, URL, client)
    row = db.history()[0]
    assert row["status"] == "sent" and row["message_id"] == "987"


def test_health_reports_confirmed_send_and_never_leaks_transport_details(tmp_path):
    db=prepared(tmp_path); observed=[]
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'id':'987'}))) as client:
        deliver_once(db,URL,client,observe=lambda *args:observed.append(args))
    assert observed==[('discord','healthy','delivered')]
    assert db.history()[0]['status']=='sent'
    assert not deliver_once(db,URL,client,observe=lambda *args:observed.append(args))
    assert observed[-1]==('discord','idle','no_work')


def test_health_failure_cannot_interrupt_delivery_or_authorize_uncertain_retry(tmp_path):
    db=prepared(tmp_path)
    def timeout(request): raise httpx.ReadTimeout('Bearer private-credential')
    observed=[]
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        deliver_once(db,URL,client,observe=lambda *args:observed.append(args))
    assert observed==[('discord','blocked','uncertain')]
    assert db.history()[0]['status']=='uncertain'; assert db.claim() is None
    with httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError('No retry')))) as client:
        assert not deliver_once(db,URL,client,observe=lambda *args:observed.append(args))
    assert observed[-1]==('discord','blocked','uncertain')
    db2=prepared(tmp_path/'another')
    def broken(*args): raise RuntimeError('health disk unavailable')
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'id':'988'}))) as client:
        assert deliver_once(db2,URL,client,observe=broken)
    assert db2.history()[0]['status']=='sent'

def test_rate_limit_defers_without_marking_sent(tmp_path):
    db = prepared(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429,json={"retry_after":30}))) as client:
        deliver_once(db, URL, client)
    assert db.history()[0]["status"] == "pending"
    assert db.claim() is None

def test_timeout_requires_review_instead_of_duplicate_post(tmp_path):
    db = prepared(tmp_path)
    def timeout(request): raise httpx.ReadTimeout("ambiguous")
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        deliver_once(db, URL, client)
    assert db.history()[0]["status"] == "uncertain"
    assert db.claim() is None

def test_webhook_is_restricted_to_discord(tmp_path):
    import pytest
    with pytest.raises(ValueError): deliver_once(prepared(tmp_path), "http://localhost/admin", httpx.Client())


def test_rate_limit_defers_all_jobs(tmp_path):
    from test_core import event
    from crier.models import Settings
    db = prepared(tmp_path)
    db.ingest(event(order_id="other"), Settings())
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429,json={"retry_after":30}))) as client:
        deliver_once(db, URL, client)
    assert db.claim() is None


def test_missing_message_id_is_uncertain(tmp_path):
    db = prepared(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={"id":None}))) as client:
        deliver_once(db, URL, client)
    assert db.history()[0]["status"] == "uncertain"


def test_abandoned_delivery_is_not_reposted_after_restart(tmp_path):
    db = prepared(tmp_path)
    assert db.claim()
    db.recover()
    assert db.history()[0]["status"] == "uncertain" and db.claim() is None


def test_connection_failure_retries_without_claiming_delivery(tmp_path):
    db = prepared(tmp_path)
    def disconnected(request):
        raise httpx.ConnectError("cannot connect")
    with httpx.Client(transport=httpx.MockTransport(disconnected)) as client:
        assert deliver_once(db, URL, client)
    assert db.history()[0]["status"] == "pending"
    assert db.claim() is None


@pytest.mark.parametrize('failure',[httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout])
def test_pre_send_transport_failures_keep_the_existing_bounded_retry_budget(tmp_path,failure):
    db=prepared(tmp_path); observations=[]; calls=[]
    def fail(request): calls.append(request); raise failure('private transport detail')
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        for attempt in range(5):
            assert deliver_once(db,URL,client,observe=lambda *args:observations.append(args))
            assert db.history()[0]['status']==('pending' if attempt<4 else 'failed')
            with db.connect() as connection: connection.execute('UPDATE outbox SET due=0')
        assert not deliver_once(db,URL,client)
    assert len(calls)==5
    assert observations[-1]==('discord','blocked','connection_failed')
    assert 'private' not in repr(db.history())


@pytest.mark.parametrize('failure',[httpx.ReadTimeout,httpx.WriteTimeout,httpx.RemoteProtocolError])
def test_possible_post_transmission_failures_never_repost_automatically(tmp_path,failure):
    db=prepared(tmp_path); calls=[]
    def fail(request): calls.append(request); raise failure('private transport detail')
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        assert deliver_once(db,URL,client)
        assert not deliver_once(db,URL,client)
    assert len(calls)==1 and db.history()[0]['status']=='uncertain'
    assert 'private' not in repr(db.history())


def test_server_error_is_uncertain_and_not_automatically_retried(tmp_path):
    db = prepared(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        assert deliver_once(db, URL, client)
    assert db.history()[0]["status"] == "uncertain"
    assert db.claim() is None


def test_webhook_rejection_is_failed_without_reposting(tmp_path):
    db = prepared(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as client:
        assert deliver_once(db, URL, client)
    assert db.history()[0]["status"] == "failed"
    assert db.claim() is None
