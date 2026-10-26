# Webull iPhone host to Alpaca-paper Windows receiver

The owner selected the first route: the customer enters orders inside Crier on iPhone against their own authorized Webull account. A Windows Crier receiver executes through its own Alpaca paper account. This deliberately differs from watching Webull's own app and from copying fills after the fact.

## Boundaries

- A separate Webull Host screen/controller preserves the existing Alpaca workflow and journals. Webull authorization uses a verified customer principal and server-held credentials, never a broker application secret in iOS.
- The Webull host environment (sandbox or production) and destination environment (Alpaca paper for this route) are separate, explicit fields. The existing intent-v1 envelope retains its destination `paper` environment. Never relabel a Webull production fill as a paper fill.
- The source stock/OCC option symbol maps to the existing destination-neutral instrument identity. Whole shares and standard long single-leg options only. Unsupported/ambiguous contracts fail closed.
- Explicit confirmation creates durable intent and source-order identities before dispatch. Instruction publication does not wait for a source fill. A receiver may execute even if the source subsequently rejects; preserve visible status and cancellation evidence.
- Source cancellation/replacement/exit must reconcile late/partial fills, unknown outcomes and owned quantities. No blind resubmission after restart or timeout.
- The server requires authenticated, account-bound calls, persistent idempotency/reservations and an approved Webull transport. Test ports and synthetic fixtures do not constitute provider approval or production acceptance.

## Deliverables

Server gateway/adapter contracts and behavioral tests; native customer authorization/trading/pairing UI and durable host coordinator; receiver compatibility tests; configuration/acceptance instructions. Reuse existing relay transport and Windows executor instead of introducing a second execution protocol.

Webull approval, application configuration, real sandbox validation, deployment credentials, Apple signing and physical cross-network tests remain external dependencies. Unconfigured production routes must return unavailable rather than fabricated account or order success.
