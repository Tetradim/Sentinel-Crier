# Sentinel Crier: Webull first, iPhone first

Approved in chat on October 13, 2026. The user additionally requested cards close to Homebrew Alerts.

## Product

An always-on service reads authorized brokerage account events and posts actual fills to Discord. A responsive Safari/Home Screen web app controls presentation and shows delivery history. This is not an iOS cross-app screen reader or a native App Store build. Desktop browsers use the same UI; a native PC wrapper is a later milestone.

## Homebrew reference

Read-only inspection of local Echo captures from the explicitly named `homebrew-alerts` channel showed a compact contract headline, trader name, `Filled 4× @ $0.34`, optional stop/target information, and a monospace exit/price/qty/P&L ledger. Other captured `Alerted By` cards came from a different channel and are not the primary reference. Implement the visual grammar with Crier branding and synthetic fixtures; do not publish private captured messages or personal identifiers.

## First release

- Python service, SQLite event/audit/outbox storage, official Webull SDK adapter, Discord webhook delivery.
- Validate stocks and single-leg OCC option symbols; reject incomplete or ambiguous contracts. No inference that BUY means opening or SELL means closing. Source position intent is required for Echo execution compatibility.
- Cumulative fills produce incremental quantities and prices; duplicate, stale, and conflicting observations cannot create fresh buy signals. Source account/order identity stays in local storage, not public cards.
- Independent event cards are the default. Option entries and exits can use an explicit Echo text format only where action intent is known. No invented trim percentage, stop, peak return, or remaining balance.
- Webull stream is opt-in and experimental until real manual-app order coverage is demonstrated. Persist raw events, quarantine unsupported payloads, expose disconnects, and provide read-only order reconciliation tooling. Never place or cancel orders.
- Offline fixture mode is the default. Sample alerts never enter the live Discord outbox. Live connection secrets are server environment variables. All non-public API requests require an access token.
- Homebrew-style card and plain-text customization: display name, color, timezone, quantity/time visibility. Preview before saving. Broker IDs and secrets never reach public output.
- Mobile layout: card preview/editor, activity, connection status, authenticated settings. No third-party assets or credentials in browser storage.

## Acceptance

Tests must cover cumulative partial fills, replay/restart dedupe, malformed data, OCC decoding, unsupported intent, template escaping, Discord 429 and ambiguous sends, persistence, API auth, and generated Echo parsing. Visually inspect at iPhone and desktop widths. No live trading or live posting is needed for development verification.

## Deployment boundary

Requires Webull API eligibility and a controlled read-only check that manual iPhone trades are visible. Hosted HTTPS and a persistent volume are required for remote iPhone access. Local UI can run now. Live readiness must not be claimed from synthetic tests.

## Sources

- https://developer.webull.com/apis/docs/reference/custom/subscribe-trade-events/
- https://developer.webull.com/apis/docs/reference/order-query/
- https://developer.webull.com/apis/docs/sdk/
- https://developer.apple.com/forums/thread/685525
- Local Sentinel-Link capture parser and Sentinel-Echo structured card parser/tests (read only).

## Approved refinements and implemented boundary

The user supplied AlertBot_CardKit.zip, confirming the primary reference is plain Discord Markdown from a Tradier-specific watcher with a reusable formatter. Original Markdown formatting is now the default; rich-card embeds remain optional. The user clarified Crier is free open-source software for Sentinel users; there is no shared Tetradim-hosted account system. This first implementation is a self-hosted foundation. Position-level running P/L and edit-in-place behavior from CardKit are not yet ported, and live brokerage/manual-app compatibility remains unverified. See README for the exact shipped and unimplemented behaviors.
