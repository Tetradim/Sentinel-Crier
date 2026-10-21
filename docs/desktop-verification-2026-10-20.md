# Windows desktop verification — 2026-10-20

- Full offline Python suite: **279 passed**, one existing Starlette/httpx warning.
- Six desktop tests cover account discovery, protected credentials, paused reconnect,
  immutable account/channel binding, failed-verification persistence, explicit live
  selection and an iOS-format instruction delivered through the real relay routes to
  a fake desktop broker. The instruction preserved the OCC symbol, two-contract
  quantity and $0.20 limit; the simulated order remained unfilled.
- `python -m crier.desktop --self-test` passed locally on Windows.
- `desktop/build.ps1` built the portable executable with PyInstaller 6.16.0 and
  Python 3.11.9. The packaged executable passed the offline Tk startup and DPAPI
  credential round-trip smoke test. No broker or relay requests were made by that test.
- The executable and ZIP are build outputs in `dist/`, not source-controlled binaries.
  The Windows desktop workflow builds and uploads a portable ZIP on GitHub.
- [Clean Windows CI run](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39523173846)
  passed on implementation commit `9ce4b4e`: full tests, packaging, packaged smoke
  test and artifact upload. Download the `SentinelCrier-Windows` artifact there.

No actual iPhone-to-PC paper order or live order was placed. HTTPS relay availability,
account access, physical-device delivery latency and live execution remain deployment
and acceptance checks. The Windows build is unsigned. See [setup](../desktop/README.md)
and [paper acceptance](intent-paper-acceptance.md).
