# Alpaca fill monitor

Sentinel Crier can automatically observe account-wide stock and single-leg OCC option fills from the official Alpaca Trading API, including trades placed in the brokerage app or another client. This server observer only performs GET requests. It does not submit, cancel, or manage orders. Webull remains a separate integration requiring its own verification.

## Start with paper trading

Set these **process environment variables** on the server (or copy `.env.example` to a private `.env` for Docker Compose):

```text
CRIER_MONITOR=alpaca
ALPACA_ENV=paper
APCA_API_KEY_ID=<your paper API key ID>
APCA_API_SECRET_KEY=<your paper API secret>
CRIER_DELIVERY_ENABLED=false
```

Run `python -m crier serve --monitor alpaca`, or `python -m crier watch --monitor alpaca` if the console is already running without a managed observer. Only one observer can own a data directory. The Python command reads environment variables; it does not load `.env` by itself. No account ID is configured: the observer obtains it from the authenticated `/v2/account` response.

The first successful complete history fetch silently enrolls existing fills. It never queues that old history for publication. Place a **new paper trade after the observer reports observing**, wait for an actual fill, and check the queued alert. A submitted or accepted order alone is not a fill. The poll interval is ten seconds, plus HTTP request time. No `CRIER_ALPACA_VERIFIED` flag is required for this authenticated official adapter.

Review the configured Discord destination and queued alerts. Enable delivery with the existing publisher settings:

```text
DISCORD_WEBHOOK_URL=<your private webhook URL>
CRIER_PUBLISHER_VERIFIED=true
CRIER_DELIVERY_ENABLED=true
```

Restart the service after changing environment variables. Pending alerts can send once publication is enabled, subject to pause and review state. Keep the data volume persistent; deleting it creates a fresh enrollment and suppresses then-existing history again. Credentials and webhook URLs must stay out of Git, screenshots, and public logs.

## Explicit live selection

Only after paper validation, configure `ALPACA_ENV=live` with the account holder's **live** Alpaca API credentials. Paper uses `https://paper-api.alpaca.markets`; live uses `https://api.alpaca.markets`. Other environment values are rejected. Persisted cursors and execution identities are scoped by environment and authenticated account, so a live account enrolls independently. Public cards retain the existing model labels `sandbox` for paper and `production` for live.

## Fill correctness and limits

- Fetches `/v2/account/activities/FILL` in ascending order, using the last activity ID as the next page token. Pages contain at most 100 activities. A complete poll is capped at 1,000 pages; exceeding that cap fails without advancing progress.
- All pages arrive before database changes. Activity ID deduplication, cumulative execution cost, Store watermarks, frozen alert payloads, and cursor commit in one SQLite transaction. A restart or failed batch retries from committed progress. Changed content under an existing activity ID is rejected.
- Uses decimal arithmetic, including fractional stock quantities to nine decimal places. Options require whole contracts and a valid OCC symbol. Incomplete cumulative history, unsupported symbols (including crypto), malformed quantities, and unsupported activity types fail the entire batch rather than guess.
- Stores cumulative average prices rounded to eight decimals to match the existing Snapshot contract. Alerts use the broker's exact activity execution price; the Store checks that its notional differs from cumulative arithmetic by no more than the combined half-unit rounding bounds of the old and new averages. A materially inconsistent price cannot override the cumulative evidence.
- Activity records provide buy/sell, not reliable open/close position intent. The monitor marks intent `UNKNOWN` and never guesses BTO/STC. Use Homebrew, text, or card format. The existing Echo template requires verified buy-to-open intent and holds these fills for review.
- This is a stock/options fill monitor, not a complete corporate-action, trade-correction, or multi-leg reconstruction service. Unsupported historical activity can prevent enrollment. Cursor polling does not promise detection of subsequently edited older records that the broker does not return again. Reconcile broker statements separately.

The monitor does not synchronize the separate iPhone local trade journal or change order placement permissions. API authentication and real end-to-end Discord delivery need operator verification; automated tests use mocked HTTP and no credentials.

## References and tests

Official API documentation: [account activity pagination and authentication](https://docs.alpaca.markets/us/reference/getaccountactivities-2), [trade activity fields and cumulative quantity](https://docs.alpaca.markets/us/v1.4.2/docs/account-activities).

Run `python -m pytest tests/test_alpaca.py tests/test_monitors.py tests/test_core.py -q` for enrollment, incremental fills, pagination, restart deduplication, error rollback, exact decimal execution prices, environment isolation, and request authentication checks.
