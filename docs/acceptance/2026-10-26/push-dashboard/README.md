# Phase L verification

Implementation source: `a7ee75c2c723ad35d9bd1404e1587a8a723e0268`. The iOS source is identical to the verified `c757a28` component; the deployed Supabase source is identical to `8ec28bf`. Windows and Python source components are identical to `b62ad53`. The evidence report records Git object identities, CI source revisions and copied-report checksums.

| Check | Result |
| --- | --- |
| Full local Windows Python/OAuth matrix | 1,024 passed; one optional SDK skip |
| Android unit tests / packaging | 162 tests; debug APK assembled |
| Android emulator | Five UI/persistence tests |
| iOS native | 157 tests |
| iOS simulator UI | One test traversing the three practice guides |
| iOS packaging | Simulator build and unsigned hardware archive |
| Windows packaging | Portable smoke; install, upgrade, downgrade refusal and uninstall |
| Supabase | PostgreSQL migration/privacy tests; 13 gateway/stream tests; type and lint checks |
| Push regression | Real local socket; one instruction and a 50-instruction burst; durable order and cursor checks with no polling request |

The cross-platform monetary fixture covers complete closed trades, actual fees, losses, rounding, missing metadata/prices, partial closes, and fresh/stale/future quotes. Telemetry tests preserve execution separation and durable report revisions. Existing intercepted broker-worker tests still verify receiver submission while the host's broker response is withheld.

The isolated [hosted probe](hosted-synthetic-probe.json) created a new paper channel with no broker or Discord consumers. It verified a streamed instruction and cursor, two actors' synthetic reports, expected USD 2.00 gross arithmetic and revoked-receiver denial. Its approximately 1.28-second publish-and-deliver observation is one client/service sample, not cross-device, cross-state or broker execution latency. Initial subscription probes returned 503 before a later probe succeeded; clients retain explicit bounded polling recovery.

Integration review corrected SDK-compatible Android assertions, bounded early reconnects, unknown extension handling, per-trade report coalescing, presence changes and retrying iOS report persistence before upload. The independent reviewer could not run because its selected model reported capacity; manual integration review and recorded automated checks were completed instead.

The dashboard cannot place orders, retry execution or introduce an independent exit strategy. It labels device-reported evidence, unknown fees, incomplete prices, stale presence and unavailable estimates. The host sees channel receivers; a receiver sees only the host and itself, subject to enrollment and revocation.

No real orders or Discord messages were sent. Apple signing/enrollment, Webull Connect approval, real broker-UI reconciliation, customer cross-network latency, physical-device/background acceptance and distribution trust remain [deferred](../../../remaining-work.md). The unsigned iOS archive is not installable.
