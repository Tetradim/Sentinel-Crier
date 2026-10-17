"""FUTURE / NOT ACTIVE — Sentinel Crier Unified Market Feed.

WHAT IT WOULD DO (if explicitly activated in a future project phase):
  1. Accept licensed, customer-entitled real market data from approved providers
     such as Alpaca, Tradier, or Webull.
  2. Normalize instrument identity, timestamps, price, venue, feed, delay and
     source provenance into one *transport* contract for clients.
  3. Prefer the best eligible feed for each specific instrument and customer.
     Recheck freshness and data entitlements on every selection.
  4. Detect duplicates, disconnections and stale quotes, and fail CLOSED if an
     authoritative feed cannot be identified.
  5. Keep live stock candles and OCC option-contract candles distinct.

WHAT IT DOES NOT DO:
  - Does not scrape, extract, or redistribute TradingView-hosted widget data.
  - Does not average quotes from disparate exchanges into fictional prices.
  - Does not combine IEX candles with SIP/OPRA candles into one price history.
  - Does not supply execution reference prices, verify broker fills or send orders.
  - Does not make API requests, create credentials, register routes or subscribe
    to live feeds. No code here is imported by the Crier app or API at present.

STATUS: ARCHIVED FOR POSSIBLE FUTURE USE. This module is deliberately isolated
from the app's active charting and trading paths. Do not activate without
customer authorization, approved market-data redistribution entitlements, an
actual feed implementation, thorough tests and code review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


class FutureFeedError(ValueError):
    """Feed cannot be selected without verified market-data entitlements."""


class Coverage(str, Enum):
    IEX = "iex"
    SIP = "sip"
    OPRA = "opra"


@dataclass(frozen=True)
class LicensedFeed:
    provider: str
    coverage: Coverage
    instrument_id: str
    observed_at: datetime
    entitled: bool
    redistributable: bool
    is_live: bool

    def validate(self) -> None:
        if not self.provider.strip() or not self.instrument_id.strip():
            raise FutureFeedError("missing provider or instrument identity")
        if self.observed_at.tzinfo is None:
            raise FutureFeedError("feed observation time must include timezone")
        if self.observed_at > datetime.now(timezone.utc):
            raise FutureFeedError("future market observation timestamp")


def choose_future_chart_feed(
    *,
    instrument_id: str,
    candidates: list[LicensedFeed],
    now: datetime,
    max_age_seconds: int = 15,
) -> LicensedFeed:
    """Pure *planning* selector, not integrated into any runtime endpoint.

    For stock symbols: eligible consolidated SIP outranks IEX.
    For options: only appropriately entitled OPRA coverage is eligible.
    This cannot attest to accuracy, NBBO, or real-time exchange availability.
    """
    if now.tzinfo is None:
        raise FutureFeedError("now must be timezone-aware")
    if max_age_seconds <= 0:
        raise FutureFeedError("max age must be positive")
    is_option = instrument_id.startswith("OCC:")
    priority = {Coverage.OPRA: 3} if is_option else {Coverage.SIP: 2, Coverage.IEX: 1}
    eligible = []
    for candidate in candidates:
        candidate.validate()
        seconds_old = (now - candidate.observed_at).total_seconds()
        if (candidate.instrument_id == instrument_id and candidate.entitled
                and candidate.redistributable and candidate.is_live
                and candidate.coverage in priority and 0 <= seconds_old <= max_age_seconds):
            eligible.append(candidate)
    if not eligible:
        raise FutureFeedError("no entitled, redistributable, fresh data source")
    return max(eligible, key=lambda feed: (priority[feed.coverage], feed.observed_at))
