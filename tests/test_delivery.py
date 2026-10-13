import httpx
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
