# Assessment of the external reviews in Fixed.txt

Reviewed against `415d3bd` and the Android inset follow-up on November 1, 2026. The supplied document is feedback, not an instruction source. Its general praise does not replace compilation, regression tests or provider acceptance.

## Verified findings and qualifications

| Claim | Assessment | Evidence / disposition |
| --- | --- | --- |
| Provider OAuth is not activated | Correct for the separately prepared provider service. | `docs/remaining-work.md` and `supabase/provider-connect/README.md` retain deployment/provider prerequisites. The working relay is a different service. Do not deploy credential custody or remove owner authentication just to reduce taps. |
| Customers must create a Crier account | Applies to the optional provider-custody sign-in, not every current installation. | Current manual Alpaca-key/private pairing workflows do not inherently require that sign-in. A device-bound replacement needs real device proof, revocation and recovery; a device identifier alone is insufficient. |
| Quantity cap remains 1000 and the entry timer is optional | Confirmed. | The source-quantity cap is not the same as fixed/ratio/budget follower sizing. `IntentViews.swift`, Android settings and Windows pricing expose separate controls. A required visible onboarding choice is a sound proposed improvement; do not silently impose an arbitrary risk preset or rewrite existing trade policy snapshots. Use shares/contracts labels appropriate to the asset. |
| Relay clock offset should warn without authorizing | Sound proposal. | Diagnostics retain bounded offset/uncertainty evidence; entry-clock guards use local continuity and retained source timestamps. Add a fresh, uncertainty-qualified setup/health warning without letting clock estimates expand trading authority. |
| iPhone requires foreground operation | Correct and already disclosed. | README and GuidedSetup explain it. An earlier runtime-choice explanation would improve onboarding. A remote outage notification requires an observer outside the app that died, explicit recipient permission, deduplication and recovery notices. A local heartbeat alone cannot deliver it. |
| Alpaca monitor has fixed 10-second polling and audit repetition | Confirmed specifically in the standalone CLI observer. | `crier/alpaca.py::_observe` sleeps ten seconds after both success and failure, and audits every failed poll. Add bounded backoff, retry-after handling and incident/recovery audit coalescing. This is separate from submission-time Crier host mirroring. |
| Fills have unknown open/close intent | Deliberate evidence limitation, not a parsing error. | Alpaca activity rows supply side, quantity and execution cost. `normalize()` correctly keeps intent UNKNOWN. A trade-update stream can wake durable catch-up, and authenticated original-order evidence may enrich intent; never infer open/close solely from BUY/SELL or discard the activity watermark/idempotency transaction. |
| OAuth gateway has no rate limiting | Partly qualified, still needs work before activation. | The provider SQL bounds active flows (8 per owner, 4 per challenge), but those are not general request-rate limits for authentication/status/browser routes. The instruction relay has its own persisted rate-limit table and tests. Do not assume Supabase Auth limits cover custom Edge routes; verify deployment configuration and add independently tested admission limits. |
| No installable signed iPhone build; Windows publisher unsigned | Correct and already recorded. | Apple enrollment/signing and physical/provider acceptance remain owner-deferred. Windows has an Ed25519-signed update catalog, which is distinct from Authenticode signing. Android uses its existing operator signing identity. |
| Crier is already a complete multi-broker executor | Overstated in the second review. | Active native execution is Alpaca. Webull is a candidate workflow awaiting an activated approved adapter; Tradier is a read-only Python observer. Container files and interface separation do not establish production scaling or provider acceptance. |
| More disconnected-state UI and documentation indexing work would help | Applicable. | This build adds account-first native layouts, explicit unavailable data and order/recovery navigation. Actual Android acceptance exposed clipped system-bar/navigation controls; that production defect is being fixed with strict native visibility assertions. Acceptance results remain indexed by source and release rather than a generic daily success claim. |

## Proposed follow-up order

These are additional recommendations, separate from the already approved recovery/refactor/UI implementation. They are not silently enabled by this review.

1. Harden the standalone Alpaca observer's retry/audit behavior, retaining cursor/outbox atomicity and redacting upstream errors.
2. Require a deliberate follower sizing/quantity/time-in-force decision in new-account onboarding, with clear stock/option units and preservation of existing policies.
3. Explain foreground/background runtime choices before broker setup; show a fresh clock-offset warning in setup and health.
4. Add durable provider-gateway request admission and test it independently from relay and Supabase Auth limits before provider-service activation.
5. Introduce stream-assisted fill catch-up and optional independently hosted outage notifications, with explicit delivery consent and synthetic disconnect/reconnect tests.

Device-bound sign-in is a design candidate, not a drop-in security simplification. Provider registrations, Apple distribution and commercial/legal operating decisions remain separate from these source changes; this review does not add a new approval gate to the current build.
