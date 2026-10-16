"""Pure offline checks of the FUTURE/NOT ACTIVE feed selector.

No broker credentials, network access, order routing, or TradingView extraction.
"""
from datetime import datetime, timedelta, timezone

import pytest

from crier.future_unified_market_feed import (
    Coverage, FutureFeedError, LicensedFeed, choose_future_chart_feed,
)

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)


def feed(coverage, *, symbol="IWM", age=1, entitled=True, redistributable=True):
    return LicensedFeed(
        provider=coverage.value,
        coverage=coverage,
        instrument_id=symbol,
        observed_at=NOW - timedelta(seconds=age),
        entitled=entitled,
        redistributable=redistributable,
        is_live=True,
    )


def test_prefers_eligible_consolidated_stock_feed():
    selected = choose_future_chart_feed(
        instrument_id="IWM", now=NOW,
        candidates=[feed(Coverage.IEX), feed(Coverage.SIP, age=3)],
    )
    assert selected.coverage is Coverage.SIP


def test_does_not_promote_nonredistributable_feed():
    selected = choose_future_chart_feed(
        instrument_id="IWM", now=NOW,
        candidates=[feed(Coverage.SIP, redistributable=False), feed(Coverage.IEX)],
    )
    assert selected.coverage is Coverage.IEX


def test_options_require_opra_and_correct_contract():
    symbol = "OCC:IWM261016C00240000"
    with pytest.raises(FutureFeedError):
        choose_future_chart_feed(
            instrument_id=symbol, now=NOW,
            candidates=[feed(Coverage.IEX, symbol=symbol)],
        )
    result = choose_future_chart_feed(
        instrument_id=symbol, now=NOW,
        candidates=[feed(Coverage.OPRA, symbol=symbol)],
    )
    assert result.coverage is Coverage.OPRA


def test_stale_unentitled_and_mismatched_sources_fail_closed():
    for candidate in (
        feed(Coverage.IEX, age=100),
        feed(Coverage.IEX, entitled=False),
        feed(Coverage.IEX, symbol="SPY"),
    ):
        with pytest.raises(FutureFeedError):
            choose_future_chart_feed(instrument_id="IWM", now=NOW,
                                     candidates=[candidate])
