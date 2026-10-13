import pytest
from crier.webull import normalize, quiet_event_client, enroll, enrollment_key
from crier.store import Store
from crier.models import Settings
from test_core import event


def payload(**changes):
    return dict(account_id="a", order_id="o", category="US_STOCK", symbol="AAPL", side="BUY",
                filled_qty="3", filled_price="180", filled_time="2026-10-13T15:00:00+0000",
                scene_type="FINAL_FILLED") | changes


def test_official_webull_fill_mapping():
    snap = normalize(payload(), "a")
    assert snap.cumulative_qty == 3 and snap.intent == "UNKNOWN"
    assert snap.status == "FILLED"


def test_nonfills_and_wrong_accounts_are_not_alerts():
    assert normalize(payload(scene_type="CANCEL_SUCCESS"), "a") is None
    with pytest.raises(ValueError): normalize(payload(), "b")
    with pytest.raises(ValueError): normalize(payload(category="US_OPTION"), "a")
    with pytest.raises(ValueError): normalize(payload(legs=[{}, {}]), "a")


@pytest.mark.parametrize("order_id", [None, True, False, [], {}, "", "  ", 0])
def test_invalid_order_ids_are_quarantined(order_id):
    with pytest.raises(ValueError): normalize(payload(order_id=order_id), "a")


def test_sdk_signing_does_not_print_credentials(capsys):
    pytest.importorskip("webull")
    client = quiet_event_client("test-key", "test-secret", "us", "events-api.sandbox.webull.com")
    request, metadata = client._build_request("test-key", "test-secret", ["a"])
    assert request.accounts[0] == "a" and metadata
    assert not capsys.readouterr().out


def test_enrollment_baselines_preexisting_fill_and_never_overwrites(tmp_path):
    db = Store(tmp_path / "db")
    snap = event(cumulative_qty="4")
    manifest = {"account":snap.account, "environment":"sandbox", "captured_at":"2026-10-13T14:43:00Z", "complete_open_orders":True,
                "snapshots":[snap.model_dump(mode="json")]}
    enroll(db, manifest)
    result = db.ingest(event(cumulative_qty="5"), Settings())
    assert result["fill"]["quantity"] == "1"
    with pytest.raises(ValueError): enroll(db, manifest)


def test_enrollment_requires_complete_matching_snapshot(tmp_path):
    db = Store(tmp_path / "db")
    manifest = {"account":"x", "environment":"sandbox", "captured_at":"2026-10-13T14:43:00Z", "complete_open_orders":False,"snapshots":[]}
    with pytest.raises(ValueError): enroll(db, manifest)
    manifest["complete_open_orders"] = True
    manifest["snapshots"] = [event().model_dump(mode="json")]
    with pytest.raises(ValueError): enroll(db, manifest)
