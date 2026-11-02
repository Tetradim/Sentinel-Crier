# What happened? — recorded execution explanations

Crier 0.5.3 translates existing local journal and trace records into short explanations. This is an observational display, not a broker-health check, trading permission, or a substitute for broker reconciliation.

## Open it

- Windows: Home or Account → **What happened?**. Choose a tracked trade and click **Read local evidence**. **Detailed timeline** selects that trade in Health → Trade timeline, retaining the existing quantities, JSON/CSV exports and advanced evidence. No broker lookup is triggered by opening this panel; the read uses local diagnostics. Reconnect to access a selected account's journal through the existing session boundary.
- Android: **Diagnostics · timeline, premiums and latency**, then choose an event. The What happened explanation precedes the advanced timeline.
- iOS: the recovery screen's **Paired execution diagnostics** links open a trade's recorded revisions. Each revision shows What happened before Advanced evidence.

The display shows up to eight explanations by default, with an absolute twenty-message cap and adjacent repeats coalesced. Input chronology is retained. Windows presents up to fifty recent tracked trades in its picker and rejects late results after account, trade or action-epoch changes. It clears the result on route changes/disconnection. Reads are explicit; the panel does not automatically poll broker APIs.

## Meaning and limits

Instruction saved, relay acknowledgement, broker submission started/returned, cancellation requested, broker evidence refreshed, refusal, paused/expired entries and uncertain outcomes have separate descriptions. Submission acknowledgement never proves a fill. A cancellation request never proves terminal cancellation; a canceled order can retain earlier fills. A recorded filled status is historical evidence, not proof that positions are currently flat or that another device got the same fill.

Only fixed, allowlisted explanations appear in the summary. Unknown stages or unstructured text produce an explicit generic explanation; raw details, IDs, credentials and exception messages are not interpolated. Android's exact journal status/reason enums are adapted to the shared format. Older iOS free-text status records remain generic rather than being parsed as authoritative fills. The advanced timeline and explicit exports retain their prior behavior and detail.

## Shared conformance

`tests/fixtures/decision-summary.json` version 1 supplies 77 common examples to Python, Kotlin and Swift. Tests cover semantic stages, explicit partial/terminal/unknown status, cancellation distinction, chronology, duplicate coalescing and safe unknown detail. Separate adapter tests use native journal shapes; Python additionally checks malformed inputs and invalid limit types. The fixture demonstrates these explanations, not general execution-engine parity.

The complementary [native invariant scenarios](protocol/native-invariants.md) exercise seven selected clock/account-bank scenarios against the production implementations on all three platforms. Native lifecycle/storage differences remain documented.

## Selected technical failures

The existing bounded technical logger now records `diagnostics.trace_dropped`, `diagnostics.enqueue_failed`, `diagnostics.clock_failed` and `diagnostics.transport_failed`. These are fixed codes with sanitized exception type/stack and valid scoped trade IDs only. Exception messages and broker payloads are excluded. The existing queue, rotation, suppression and dropped-record indicators bound logging. Broken logging remains nonfatal; it cannot change durable broker work, diagnostic retry limits or stop behavior. Expected timer/wait timeouts remain quiet, and the logger does not recursively report its own failures.
