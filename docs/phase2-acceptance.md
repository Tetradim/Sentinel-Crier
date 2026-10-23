# Phase 2 acceptance evidence

This checklist defines customer-flow and protocol acceptance. Physical-device and remote-network acceptance remains Phase 5; hosting remains Phase 3.

## Customer walkthrough

Run on iOS, Android, and Windows with mocked transports first, then authorized paper accounts during physical acceptance.

1. Start a fresh installation. Select paper, enter credentials, and verify the account identity displayed by the broker.
2. Select Host, create an invitation, and join from Receive using the invitation. Verify both roles and the paper environment; receivers start paused.
3. Enable receiving, submit a tracked stock or standard long option, and inspect the durable instruction and broker reconciliation independently.
4. Open connection management, list receivers, revoke one, and confirm that its next authenticated fetch is rejected. Revocation does not cancel an existing brokerage order.
5. Configure a Discord destination, select card/plain text, choose a template and fields, preview, and send an explicitly labeled test message. Verify delivery status and retry controls using a mocked failure followed by success.
6. Confirm instruction/manual/broker-fill provenance stays visible in all applicable messages. Only authoritative cumulative fills may produce broker-fill alerts. Quantity must represent the new fill amount, not the full cumulative quantity on every poll.
7. Disconnect and reconnect without deleting the journal. Rotate credentials for the same account; an account/channel change with unresolved orders must preserve the original recovery context.
8. Inspect unknown, pending-cancel, rejected, partially filled, and completed orders. Resume reconciliation before allowing new submissions.
9. Background and foreground each mobile client. Inspect visible execution status; simulate Android service timeout and verify clean shutdown and explicit restart behavior.
10. Upgrade from existing settings and journal schemas. Preserve account pins, client order IDs, delivery state, and unresolved outcomes.

## Shared wire validation

`tests/fixtures/phase2-protocol.json` supplies identical base/patch examples to the Python, Kotlin, and Swift tests. It covers stock and OCC option identities, fractional timestamps, malformed versions/actions/contracts/quantities/prices/sequences/timezones/lifetimes, and unknown fields.

Additional execution tests must cover conflicting revisions, invalid events followed by valid events, authentication failures, definitive rejection versus ambiguous submission, restart, cancellation/fill races, partial exits, and unrelated holdings. Tests must not contact a real broker or Discord destination.

## Evidence to retain

- Commit and complete backend/native test results.
- Build results for Windows, Android, and iOS simulator.
- Mock request sequences showing no blind duplicate order POST.
- Settings migration and durable outbox replay results.
- Outstanding physical tests and external dependencies, reported separately from implemented code.
