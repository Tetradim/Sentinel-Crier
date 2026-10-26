# Webull iPhone host candidate verification

Candidate implementation source: `420a07b`. [Source evidence](source-evidence.json) records CI revisions, results and matching component hashes. This accepts the implemented candidate scope, **not real Webull connectivity or an operational customer route**.

| Check | Result |
| --- | --- |
| Python suite | 1,036 passed, one optional SDK skip |
| Gateway/service contracts and signing | 22 Deno tests passed; lint passed |
| Actual candidate SQL in PGlite | Five tests passed: reservation/CAS, customer isolation, cancellation rearming, expired lease recovery and role permissions |
| Native iOS | 172 tests passed at `5ce2002`, including intercepted transport proving relay publication before the source response and no source resubmission after restart |
| Final UI follow-up | `420a07b` simulator build and unsigned hardware archive passed; it makes exit review available before periodic fill display catches up |

The tested controller/models/tests, Python runtime and gateway tree match the final candidate source. Revision details and hashes are explicit in the evidence rather than claiming all tests ran against an identical final commit. The unsigned archive is not an installable signed iPhone app.

Review and regression work corrected permanent cancellation claims, stale journal writers across screen navigation, contradictory broker identities/fills and cached terminal responses masquerading as successful fresh reconciliation. Source averages remain separate from limit prices. Automatic polling reads only one pending order per foreground tick; settled history is refreshed explicitly at action boundaries.

Tests used synthetic provider/authentication responses and intercepted Alpaca HTTP. No real broker orders or Discord messages were sent. SQL tests here do not establish real PostgreSQL concurrency acceptance.

Remaining implementation includes the approved Connect resource/token-custody Provider, browser callback/cookie composition, deployment, protected configuration and rate limiting. Webull approval/sandbox acceptance, Apple distribution and physical cross-network trials remain unpassed. See [route status](../../../webull-iphone-host.md) and the [implementation plan](../../../superpowers/plans/2026-10-26-webull-iphone-alpaca-pc.md).
