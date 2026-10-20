# Intent mirroring verification — 2026-10-20

Implementation: `bc5867e`; Android SDK setup repair: `7c4a287`;
PC publisher wake-up: `c2112da`. Changes pushed directly to main.

- Python: **273 passed**, one upstream Starlette/httpx deprecation warning.
  Offline tests cover the relay, authorization, immutable events, sequencing,
  local journaling, cancellation during preflight, partial fills/exits and
  ambiguous submission reconciliation. No brokerage orders were placed.
- PC JavaScript: `node --check crier/static/intent.js` passed.
- [iOS simulator compilation](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39504876144): passed on `bc5867e`.
- [iOS simulator tests](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39504876162):
  **49 tests passed**, including 11 new intent tests, with zero failures on `bc5867e`.
- [Android tests and APK build](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39504990418):
  **13 tests passed**, zero failures or ignored tests, debug APK generated on `7c4a287`.
  Artifact: `android-debug-and-tests`, file `outputs/apk/debug/app-debug.apk`.
  SHA-256: `A0E537FF2EF47E5B2C96766977F927C3F6DBB1AA79CF62953DD97DDD3B288298`.

This is implementation and automated-test evidence, not live-market certification.
No physical cross-device paper trial, signed iPhone installation, Webull Connect
integration or measured end-to-end latency is claimed. Run the
[paper acceptance procedure](intent-paper-acceptance.md) before considering those
checks complete. Keep iOS foregrounded; Android background service limits still apply.
