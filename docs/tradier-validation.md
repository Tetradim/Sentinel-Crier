# Tradier read-only monitor validation

## Contract and scope

The adapter calls only `GET /v1/accounts/{account_id}/orders` on fixed official sandbox or production HTTPS hosts. It never submits, modifies, previews, or cancels orders. Redirects are disabled, and the observer's HTTP client ignores proxy environment variables. See [Tradier endpoints](https://docs.tradier.com/docs/endpoints).

Single-leg equities and OCC options are normalized from `exec_quantity` (cumulative filled quantity) and `avg_fill_price` (cumulative average). Option side names explicitly determine opening/closing intent; ordinary equity buy/sell retain unknown intent. Canceled/expired orders with executions retain those executions. Complex classes/legs, inconsistent quantities, unknown sides and missing fields hold the entire poll.

`transaction_date` means the order's last update, **not an execution timestamp**. The snapshot stores `time_basis=order_updated`, and public presentation must label that time accordingly. No observation time, creation time, or guessed execution time is substituted. These semantics come from [Tradier order field definitions](https://docs.tradier.com/docs/orders).

## Enrollment, restart and capture mode

`TRADIER_ACCESS_TOKEN` and `TRADIER_ACCOUNT_ID` stay server-side. `TRADIER_ENV` accepts `sandbox` (default) or `production`. Without `CRIER_TRADIER_VERIFIED=true`, complete fetched polls are private capture records and create no publisher watermarks or Discord jobs. Raw rows are preserved before normalization, including unsupported orders; the poll returns the number of invalid orders and records a validation warning in the private audit. Verified polls also preserve unsupported batches as private evidence, while holding all watermarks for that batch. Valid verified batches do not add raw capture logs. Capture mode is not live coverage verification. Setting the flag requires the operator's account evidence below.

The first verified, fully fetched and validated response becomes a suppressed baseline. Its immutable snapshots are persisted before applying any baseline watermarks. A crash during application replays that saved batch; quantities from the next response are then processed normally. This prevents a restart from silently absorbing newer fills into a replacement baseline. Baselines are scoped by account and environment and survive restarts. An empty complete baseline is valid. Switching from capture mode to verified mode establishes a fresh publication baseline, intentionally suppressing the pre-enrollment quantity.

Later cumulative increases flow through `Store.ingest`, which derives incremental quantities/prices and deduplicates deliveries. Existing conflicting watermarks hold enrollment for manual reconciliation. The observer owns `data_dir/observer.lock`; direct `poll_once` callers must serialize access. The application supervisor handles process shutdown.

## Pagination and coverage limitations

The [account orders endpoint](https://docs.tradier.com/reference/brokerage-api-accounts-get-account-orders) covers the current market session. Polls request 1,000 orders per page until a short/empty page, with a 100-page safety limit. Singleton-object and list responses are accepted. Missing envelopes, repeated IDs across pages, HTTP failures and malformed orders cannot establish readiness or consume fill watermarks. Pagination is not an atomic broker snapshot: concurrent order-list changes can cause undetectable omissions. A successful traversal means a complete response traversal, not proof of complete account history.

Polling every ten seconds can combine several fills into one cumulative increment. It cannot reconstruct execution-by-execution timestamps. Downtime across sessions can permanently miss orders no longer returned by this endpoint; restarting does not backfill previous sessions. A preexisting GTC order first becoming visible after enrollment may be treated as new. Operator reconciliation is required after gaps or uncertain coverage. This adapter does not claim streaming reliability, historical backfill, arbitrary broker coverage, or multi-leg support.

## Evidence required before enabling publication

Using the ordinary broker UI and a sandbox account, independently compare captured orders with broker records for a stock and an option, opening and closing, partial then final fill, cancellation after partial execution, restart and a market-session rollover. Confirm account scope, cumulative average semantics, timestamp labeling, missing-event behavior and baseline suppression. Keep credentials and private records out of screenshots and public issues. No live-account coverage was tested for this implementation.

## Automated checks

Run `python -m pytest tests/test_tradier.py -q`. Fake HTTP tests exercise strict normalization, timestamp provenance, first baseline, empty baseline, subsequent partial/final increments, restart deduplication, interrupted baseline recovery, capture-to-verified enrollment, pagination and overlapping pages, malformed responses, unsupported legs, network/HTTP failures, redirects and invalid request scope. These tests neither use broker credentials nor contact Tradier or Discord.
