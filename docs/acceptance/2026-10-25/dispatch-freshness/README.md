# H.3 dispatch freshness acceptance

Implementation commits `41eaa14` and `88ac564` add local entry-clock continuity and final dispatch checks, preserve unknown-submission recovery, and classify Discord transport failures by whether sending could have started. The [source-bound report](source-evidence.json) records the final revision, CI outcomes, native test totals and preserved artifact checksums.

## Behavior

- Entry expiry and maximum age cannot be extended by turning the clock backwards. Raw wall time still controls the created-at lower bound, so a monotonic estimate cannot open a future entry early. A wall/monotonic discrepancy greater than five seconds defers new entries with `clock_changed`.
- Final dispatch checks reject outdated revisions, lifecycle sessions, entry freshness, quantity caps and pricing settings. Changing pricing during preflight refuses the old order with `pricing_changed`; it does not silently reprice or replay it.
- iOS retains a typed local `notSubmitted` record when the final gate positively prevents dispatch. This is distinct from an uncertain POST and from a broker rejection. Restart validation rejects contradictory records containing both this marker and a broker order/cancellation attempt.
- Android's service uses sleep-inclusive `elapsedRealtime`. iOS reanchors on connection; invalidated API instances cannot authorize a new mutation after suspension or logout.
- The immediate duplicate account read on initial iOS read-only refresh is removed. Subsequent refreshes, mutation authorization and broker reconciliation retain their required checks.
- HTTPX `ConnectError`, `ConnectTimeout` and `PoolTimeout` use the existing bounded delivery budget of five total attempts. Read/write timeouts, protocol errors and ambiguous responses remain uncertain and require the existing recovery flow. Acknowledged message identity remains required to record delivery.

## Verification boundaries

Local verification passed **840 Python tests** with one optional Webull SDK skip, and **105 Android tests**. Final CI passed **121 iOS tests**, Android tests/debug APK, iOS simulator compilation/unsigned hardware archive, and Windows installer lifecycle checks. Python CI passed **840 tests/one skip** on Windows, **818/23 skips** on each Linux matrix environment, and **749/25 skips** in the default backend environment.

The clock guard detects local discontinuities. It does not detect a static offset between devices or establish a shared UTC authority; devices still need correctly configured automatic time. Relay diagnostic offsets are not used to authorize trades. Cancellation, exits and reconciliation bypass the new entry-clock gate; existing cancellation backoff is unchanged.

No real broker order, Discord message, provider consent, service deployment, physical-device acceptance or signing was performed. H.4 optional Windows tray/startup and H.5 deliberate sizing/entry/exit policy remain separate implementation work.
