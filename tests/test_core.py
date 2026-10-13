from decimal import Decimal
import pytest

from crier.models import Snapshot, Settings
from crier.cards import render
from crier.store import Store


def event(**changes):
    data = dict(account="private-account", order_id="order-1", symbol="SPY261016C00600000",
                category="US_OPTION", side="BUY", cumulative_qty="1", average_price="1.25",
                occurred_at="2026-10-13T14:42:18Z", status="PARTIAL", intent="OPEN")
    return Snapshot(**(data | changes))


def test_occ_is_decoded_and_dates_are_validated():
    e = event()
    assert e.contract == "SPY $600C"
    assert e.expiration == "2026-10-16"
    for symbol in ("SPY", "SPY261332C00600000", "SPY261016C00000000"):
        with pytest.raises(ValueError): event(symbol=symbol)


@pytest.mark.parametrize("field,value", [("cumulative_qty", "NaN"), ("average_price", "Infinity"),
    ("average_price", "0"), ("cumulative_qty", "-1"), ("cumulative_qty", "1.5"),
    ("occurred_at", "2026-10-13"), ("side", "UNKNOWN")])
def test_bad_data_is_rejected(field, value):
    with pytest.raises(ValueError): event(**{field: value})


def test_incremental_fill_and_restart_deduplication(tmp_path):
    path = tmp_path / "events.sqlite3"
    db = Store(path)
    first = db.ingest(event(), Settings())
    assert first["outcome"] == "queued"
    assert db.ingest(event(), Settings())["outcome"] == "duplicate"
    second = db.ingest(event(cumulative_qty="3", average_price="1.35", status="FILLED"), Settings())
    assert second["fill"]["quantity"] == "2"
    assert Decimal(second["fill"]["price"]) == Decimal("1.40")
    db = Store(path)
    assert db.ingest(event(cumulative_qty="3", average_price="1.35", status="FILLED"), Settings())["outcome"] == "duplicate"
    assert len(db.history()) == 2


def test_conflicting_and_stale_snapshots_do_not_post(tmp_path):
    db = Store(tmp_path / "db")
    db.ingest(event(cumulative_qty="3"), Settings())
    assert db.ingest(event(), Settings())["outcome"] == "stale"
    assert db.ingest(event(cumulative_qty="3", average_price="2"), Settings())["outcome"] == "review"
    assert len(db.history()) == 1


def test_account_identity_is_part_of_dedupe(tmp_path):
    db = Store(tmp_path / "db")
    db.ingest(event(), Settings())
    db.ingest(event(account="another-account"), Settings())
    assert len(db.history()) == 2


def test_price_correction_holds_subsequent_order_fills(tmp_path):
    db = Store(tmp_path / "db")
    db.ingest(event(average_price="1"), Settings())
    assert db.ingest(event(average_price="2"), Settings())["outcome"] == "review"
    assert db.ingest(event(cumulative_qty="2", average_price="2.5"), Settings())["outcome"] == "review"
    assert len(db.history()) == 1
    assert db.history()[0]["status"] == "review"
    assert db.claim() is None


def test_environment_is_part_of_identity(tmp_path):
    db = Store(tmp_path / "db")
    db.ingest(event(environment="sandbox"), Settings())
    db.ingest(event(environment="production"), Settings())
    assert len(db.history()) == 2


def test_baseline_prevents_replaying_preexisting_fill(tmp_path):
    db = Store(tmp_path / "db")
    assert db.ingest(event(), Settings(), baseline=True)["outcome"] == "baseline"
    assert not db.history()
    assert db.ingest(event(cumulative_qty="2"), Settings())["fill"]["quantity"] == "1"


def test_card_uses_homebrew_headline_and_does_not_leak_ids(tmp_path):
    fill = Store(tmp_path / "db").ingest(event(), Settings())["fill"]
    card = render(fill, Settings())
    text = str(card)
    assert "SPY $600C" in text and "Filled" in text and "1.25" in text
    assert "private-account" not in text and "order-1" not in text
    assert "stop" not in text.lower() and "peak" not in text.lower()
    assert card["allowed_mentions"] == {"parse": []}


def test_homebrew_matches_supplied_cardkit_grammar(tmp_path):
    fill = Store(tmp_path / "db").ingest(event(), Settings())["fill"]
    content = render(fill, Settings())["content"]
    assert content.startswith("🟢 **SPY $600C** 10-16-2026 · Your trades\nFilled **1× @ $1.25**")
    assert "peak" not in content and "net" not in content
    assert "SAMPLE" not in content


def test_unknown_buy_does_not_claim_open_and_sell_does_not_claim_close(tmp_path):
    db = Store(tmp_path / "db")
    fill = db.ingest(event(side="SELL", intent="UNKNOWN"), Settings())["fill"]
    content = render(fill, Settings())["content"]
    assert "SELL FILLED" in content and "CLOSED" not in content and "pnl" not in content


def test_rich_card_remains_available(tmp_path):
    fill = Store(tmp_path / "db").ingest(event(), Settings())["fill"]
    assert render(fill, Settings(format="card"))["embeds"][0]["title"].startswith("SPY $600C")


def test_echo_format_requires_explicit_intent(tmp_path):
    fill = Store(tmp_path / "db").ingest(event(intent="UNKNOWN"), Settings())["fill"]
    with pytest.raises(ValueError): render(fill, Settings(format="echo"))
    fill["intent"] = "OPEN"
    assert render(fill, Settings(format="echo"))["content"].startswith("BTO 1 SPY 600C 10/16/2026 @ 1.25")


def test_settings_prevent_markdown_injection_and_bad_timezone():
    for changes in ({"display_name": "@everyone\nBTO"}, {"timezone": "Bad/Timezone"}, {"color": "garbage"}):
        with pytest.raises(ValueError): Settings(**changes)
