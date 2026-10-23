# Verified Supabase test run — October 23, 2026

Application/build commit: `30b96d9`. The hosted check was expanded during this test run; no production relay or trading code changed.

| Check | Result |
| --- | --- |
| Local Python suite | 422 passed; one existing dependency deprecation warning |
| Linux CI backend | 421 passed, 1 platform-specific skip |
| Supabase Edge gateway | 10 passed; type checking passed |
| SQL migration/security/batch tests | Passed locally and in real PostgreSQL CI |
| SQL concurrent publication/invitation tests | Passed in real PostgreSQL CI |
| Android build and tests | Passed; APK downloaded and configured gateway verified |
| iOS simulator trading suite | 83 tests passed, 0 failures |
| iOS compilation | Passed |
| Windows build | Passed |
| Packaged Windows offline self-test | UI and protected credential round-trip passed; zero network calls |
| Packaged configuration | Android APK and Windows package contain verified Supabase gateway URL |

## Hosted endpoint

The isolated synthetic PAPER check passed readiness, independent pairing for two receivers, missing-auth and wrong-role rejection, exact stock-event payload delivery, idempotent publication, waiting-receiver option delivery, exact option enter/replace/cancel/exit replay, and independent receiver revocation. Both test receivers were revoked afterward. No brokerage credentials, orders, or Discord posts were used.

The publish + duplicate + two-read sequence took 1646.296 ms on the expanded run. This aggregate includes several sequential requests and is not a single-order latency measurement or guarantee. The transport is bounded HTTP polling; Supabase Realtime push is not implemented.

## Retained evidence

- [iOS and backend CI](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40011063386)
- [Android build/tests](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40011063472)
- [Windows packaging](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40011063584)
- [Supabase real PostgreSQL and Edge CI](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40009814635)
- Local redacted hosted report: `dist/supabase-hosted-check.json`
- Local Windows package/self-test: `dist/windows-supabase-30b96d9/`
- Local Android APK/test reports: `dist/android-supabase-30b96d9/`

Physical iPhone/Android testing, communication between those real devices and a PC on separate networks, and broker paper-account accuracy/latency acceptance remain outstanding. These automated and hosted transport checks do not substitute for those tests.
