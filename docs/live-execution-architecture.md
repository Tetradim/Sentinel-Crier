# Live broker execution integration boundary

This feature branch adds `crier/live_order_journal.py`, a persistent
**live-order bookkeeping component**, and native iOS trading screens.

## Current posture

- No endpoint currently routes a Crier iOS option ticket into broker submission.
- The journal has no broker SDK, brokerage credentials, HTTP entry point, or
  background submission job. Its methods cannot place an order on their own.
- The preexisting Crier fill observer/Discord system is separate from the new
  trade-intent journal. Existing receipt or OCR input MUST NOT authorize a trade.
- These changes include no customer-facing mock, paper, or simulated trading mode.
- Unit tests use synthetic identifiers purely to check database safety invariants.

## Required integration before real-money orders can be enabled

1. Provision a secure cloud service with authenticated customer identities,
   per-user account authorization, appropriate secret management, TLS, and
   role-separated broker credentials. This SQLite journal is designed for
   one host; a multi-instance service needs a centrally transactional database.
2. Implement official, approved broker adapters independently for each provider.
   Do not reuse the unofficial Webull username/password client from older
   Pulse/Echo code. Verify options orders, account permissions, order previews,
   cancellation, per-execution identifiers and streaming/polling capabilities.
3. Fetch broker-authoritative contract identifiers for **every** selected
   account. Evaluate its own buying power and options permissions. A symbol,
   strike and date alone are insufficient.
4. Obtain independent, current broker previews for each account. Store a
   canonical hash of the complete order parameters, applicable fees, account
   selections, quantity allocation, and expiration. Expire the review if inputs
   or contract data change. The journal binds a confirmation to a digest of the
   staged orders (`order_set_digest`) and expires it; the calling service must
   still compute that digest over what the customer reviewed and the broker previewed.
   Expired confirmations can be renewed with fresh customer consent only while
   every order in the group remains unsubmitted. A reserved or reconciled order
   prevents renewal of the entire group.
5. Require explicit interactive customer confirmation of the full combined
   allocation and exposure. Authentication, CSRF/session protections,
   authorization policy and proof of consent must be enforced by the service.
   `confirm_group` records a confirmation asserted by a **trusted caller**;
   it is not itself evidence of customer consent.
6. Before a network submission, reserve each broker order using
   `reserve_submission` within a committed database transaction. Then submit
   exactly once with a stable broker-recognized client order ID. Do not
   automatically retry timeouts; look up the existing order and reconcile.
   Reconciliation must tolerate out-of-order events without losing fills.
7. Ingest only authenticated broker-confirmed incremental executions.
   Verify broker identity, account, order, instrument, execution ID, quantity
   and price. Reject conflicts and maintain durable per-event deduplication.
   The current journal records execution facts but does **not** authenticate
   their origin; an adapter and verified ingestion boundary remain necessary.
8. Expose minimal, user-scoped account/position/order snapshot endpoints.
   Return freshness timestamps and errors independently per broker. Never
   coerce unavailable buying power or balances to zero.
9. Deliver Discord alerts through a transactional outbox bound to the
   authenticated execution ledger. Ambiguous Discord outcomes must be marked
   uncertain and manually reconciled, not blindly reposted.
10. Validate with unit tests, read-only broker API checks, signed build,
    permission review, and supervised live-money end-to-end tests before
    permitting production order submission. Never enable live trading merely
    because a screen or adapter compiled.

## Execution invariants

- Every group is tenant-scoped and has one order per selected brokerage account.
- Every order uses its own UUID client order ID and positive contract quantity.
- Group confirmation is recorded before any order can be reserved.
- Reservation changes `unsubmitted` to `submission_unknown` *before*
  outbound network I/O. Retries of the same reservation are rejected.
- Broker status is never inferred as rejection solely from a timeout.
- A fill is identified by tenant + broker + account + broker execution ID.
  Exact duplicate events are ignored; conflicting duplicates are rejected.
- Fill quantities cannot exceed the requested contract count.
- Audit entries form a verification-capable SHA-256 chain. Local hashes are
  **tamper-evident, not tamper-proof**: production should externally anchor
  periodic checkpoints and tightly restrict database mutation.
- Optional stops, take-profit, automated Discord trading, risk preferences and
  heavy chart tools are disabled by default. Required broker checks, user
  confirmation, deduplication and reconciliation cannot be turned off.

## Automated verification

Backend safety tests: `python -m pytest tests/test_live_order_journal.py -q`

iOS source/test project: `ios/project.yml`; build and run the iOS
`TradingTests` and `RecognitionTests` targets on macOS with XcodeGen/Xcode.

These commands are instructions; test execution in CI and on actual iPhones
remains outstanding.

## Journal schema upgrade

Schema 2 upgrades the original unversioned journal (and version 1) inside a
single SQLite write transaction. Keep a database backup before deployment.
Orders, reservations, fills, and existing audit entries are preserved.
Execution rows gain the broker order identity from their matching order.
Legacy confirmations require fresh confirmation before an unsubmitted order
can be reserved; unknown submissions remain reserved and cannot be retried.

Unrecognized schemas, damaged audit chains, or fills without a matching broker
order stop the upgrade and roll back all schema/data changes. Resolve these
against broker records; do not delete the database to bypass the error. Legacy
timestamps are preserved; timezone-less or invalid values flag their orders
for reconciliation. Repeated migration is safe.

Callers must now supply `expected_digest=order_set_digest(reviewed_orders)` to
`confirm_group`, and authenticated `broker_id` and `account_id` to
`record_execution`. The digest does not replace customer authentication or a
current broker preview. These helpers do not enable an iOS submission route.
