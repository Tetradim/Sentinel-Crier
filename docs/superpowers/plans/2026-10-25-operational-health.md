# Phase H operational clarity implementation plan

Execute directly on main under the owner's standing approval. Use the existing checkout and synthetic tests.

## H.1 Windows component health

- [x] Add failing ledger tests for scope isolation, persistence without restored readiness, reconnect reset, stale evidence, monotonic freshness/clock discontinuity and bounded redacted reasons.
- [x] Implement `crier/component_health.py`: durable SQLite evidence, connection-session reset, allowlisted states/reasons, deterministic snapshots.
- [x] Instrument existing account/fill, relay, execution and Discord operations in `desktop_runtime.py`, `intent_device.py` and `delivery.py`; avoid extra network checks and preserve delivery semantics.
- [x] Add hidden-window regressions and a Health tab with timestamps/recovery hints, setup/history navigation and existing disconnect action.
- [x] Verify focused/full Python checks and Windows packaging/installer CI; document source-bound evidence and remaining H scope.

## Remaining H slices

- [x] H.2 Native iOS/Android component health and recovery presentation, retaining foreground/background constraints.
- [ ] H.3 Clock/freshness execution-gate and duplicate-preflight review with targeted regressions; classify transport failures by actual send uncertainty.
- [ ] H.4 Optional Windows tray/startup behavior with explicit opt-in and entries paused; no auto-live authorization.
- [ ] H.5 Deliberate sizing/quantity/notional and entry/exit policy design, preserving existing saved settings and broker reconciliation. Do not silently change execution policy as a UI preset.

H.1 does not close all of H, and no source check closes provider deployment, signing or physical acceptance gates.

## H.1 evidence

Implementation `12778a4`, contention fix `85800d2`, and benchmark-only correction `cc3b4ad` passed **823 local Python tests/one optional SDK skip**. The 49 focused health/delivery/UI checks cover scope and restart boundaries, clock discontinuity, real relay outcomes through injected HTTP, uncertain messages, unavailable health storage and minimum-window navigation. The locked-diagnostics test reproduced a 5.56-second wait before the fix; diagnostic SQLite contention now fails without waiting and is visible separately from execution journals.

The final matrix passed Windows Python 3.11 **823/one skip**, Linux Python 3.11/3.12 **801/23 skips each**. Windows installer packaging and install/upgrade/downgrade/uninstall preservation passed on `85800d2`; the later change is confined to the benchmark script/tests. The default backend passed **727/25 skips** and unchanged native iOS tests passed **107/zero failures**. The earlier Linux benchmark failure at a minute boundary and its bounded-probe correction are retained in the [source-bound report](../../acceptance/2026-10-25/operational-health/source-evidence.json). Production rate limits were not changed.

H.1 and [H.2 native health](2026-10-25-native-health.md) are complete. H.3–H.5 remain implementation work; health clock warnings do not correct execution timestamps or change price/sizing policies. No real order/message, service deployment or physical acceptance was performed.
