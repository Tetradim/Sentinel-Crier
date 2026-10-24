# Phase 5 automated acceptance - October 24, 2026

Phase 4 implementation is closed with [explicit owner-authorized deferrals](phase4-status.md). The automated Phase 5 checks below passed. Physical-device and real-broker acceptance remain deferred/unverified; this report is not a customer release declaration.

## Integrated execution acceptance

`tests/test_phase5_acceptance.py` exercises actual PC `IntentDevice.command`, publish/receive loops, authorized ASGI relay routes, persisted outbox/cursor and execution journals, and the real Alpaca intent adapter against scripted mock HTTP responses. Four scenarios pass:

| Scenario | Verified behavior |
| --- | --- |
| Entry before host fill and replay | Exact OCC contract, quantity 4, decimal premium 0.20, day limit and buy-to-open reach the follower without a host broker fill; replay after restart produces one follower order. |
| Partial-fill replacement | After 2 contracts fill from an initial target of 4, replacement target 5 at 0.23 cancels the old order before submitting the remaining 3. Restart preserves the cumulative fill. |
| Cancel/fill race and exit | A cancellation races a full fill of 4; the fill remains owned. Exit request 9 submits only 4 sell-to-close, and restart after the completed exit remains settled. |
| Ambiguous submission | Lost POST response, unavailable lookup and repeated restarts preserve unknown ownership and issue only one order POST. Valid later evidence reconciles the original order. |

These are simulated Alpaca responses. Execution is advanced by explicit engine ticks; host broker execution, background concurrency, real fill quality and actual brokerage UI comparison are outside this test's evidence. Existing engine/device tests separately cover additional malformed data, pricing, holdings and recovery cases. Independent review found no actionable defect in the integrated tests or result-retention workflow changes.

## Local relay load/recovery

[Aggregate JSON](acceptance/2026-10-24/local-relay-load.json), harness source `f206dfd`: 3 synthetic hosts, 10 receivers per host and 30 events per host; **900/900 deliveries**, zero reported failures. Restart cursor preservation, replay, duplicate publication and independent revocation passed. Missing authentication/wrong role, malformed event/invitation and receive throttling returned expected error statuses.

Measured in-process delivery percentiles: p50 291.8 ms, p95 454.5 ms, p99 513.6 ms, max 532.4 ms. Transport is `httpx.ASGITransport`, with no network or brokerage. These timings are local harness measurements, not internet/mobile latency or Supabase capacity evidence.

## Hosted HTTPS transport

[Aggregate JSON](acceptance/2026-10-24/hosted-transport.json): the deployed Supabase gateway passed health, independent two-receiver pairing, role isolation, exact payload/idempotency, waiting-receiver option delivery, enter/replace/cancel/exit field preservation and independent revocation. Both synthetic receivers were revoked afterward.

The publish + duplicate + two-read sequence took 1385.398 ms. This includes multiple sequential HTTPS requests and is not single-order latency. No broker API, real account, Discord destination or native device participated.

## Automated source/native evidence

Complete local Python suite: **521 passed**, with one existing FastAPI/Starlette HTTPX deprecation warning. JUnit is retained in `dist/phase5-2026-10-24/python.xml`. The Windows CI investigation exposed a pre-existing collection-time timestamp in the invalid-lifetime test: a long suite could turn the intended invalid lifetime into a valid one. Commit `18e284a` pins that fixture and adds exact 30-second boundary coverage; production trading behavior was not changed.

Android [CI 40066021364](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40066021364), source `c892774`, passed the build and **44 tests across 4 suites**, with zero failures/errors/skips. Downloaded JUnit XML was independently counted under `dist/phase5-2026-10-24/android-c892774/`. The subsequent `18e284a` change affects only the Python timestamp test, not Android source.

Linux [CI 40066108717](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40066108717), source `18e284a`, passed the Python job: 520 passed, one platform-specific skip. Downloaded JUnit contains 521 cases and zero failures/errors.

Windows [CI 40066108700](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40066108700), source `18e284a`, passed 520 Python tests with one platform-specific skip, portable packaging and the packaged offline UI/credential smoke test. The downloaded ZIP's smoke report confirms zero network calls; its SHA-256 and source are retained in [portable evidence](acceptance/2026-10-24/windows-portable.json). This confirms the timestamp-fixture failure was corrected on the runner that exposed it.

iOS [CI 40066108717](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40066108717), source `18e284a`, passed simulator compilation and **83 tests with zero failures**. The `ios-acceptance-results` artifact is retained and its XCTest bundle contents downloaded under `dist/phase5-2026-10-24/ios-18e284a/`. GitHub reports artifact archive SHA-256 `b4a186417d0ddbb1fb8d52115988af5729783d89438f8912731fdd51ab5723e9` (196637 bytes). This is the artifact archive digest, not a hash of a single extracted file. On a Mac, download/extract into a directory ending in `.xcresult` to open with Xcode.

Workflows retain Python JUnit XML, Android JUnit XML/build reports and the iOS XCTest result bundle. Results identify the tested commit; test artifacts do not establish signing or physical installation. The corrected final runs passed. Superseded intermediate runs were canceled; the earlier Windows timestamp-fixture failure is retained in CI history and explained above.

## Deferred and unverified acceptance

- Signed iPhone install, actual Android/Windows install/update, and all six cross-platform host/receiver direction trials on separate networks.
- Alpaca paper UI/order/fill comparison using separate authorized host/follower accounts, real tradable contracts and measured broker acknowledgement/fill timing.
- Phone lock/background/service timeout/network switching and physical restart behavior; simulated lifecycle tests are not physical observations.
- Real Discord outage/recovery and actual channel presentation. Mocked delivery tests do not post messages.
- Webull Connect integration/acceptance pending approval; not part of this Alpaca acceptance evidence.

Physical tests remain deferred under the owner's standing instruction. No real-money orders or public release/store submissions were performed. Do not call the overall supported release accepted until the relevant deferred gates pass.

## Reproduce without broker credentials

```powershell
python -m pytest -q --junitxml=dist/phase5/python.xml
python -m pytest -q tests/test_phase5_acceptance.py
python -m scripts.benchmark_relay --hosts 3 --followers 10 --events 30 --output dist/phase5/load.json
```

The separate `scripts.check_hosted_relay` command creates a synthetic channel on its supplied endpoint. Run it sparingly against an owner-authorized service; it consumes setup limits and revokes its receivers at completion. It is not an offline test.
