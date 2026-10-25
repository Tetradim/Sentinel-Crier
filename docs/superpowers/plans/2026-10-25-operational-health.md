# Phase H operational clarity implementation plan

Execute directly on main under the owner's standing approval. Use the existing checkout and synthetic tests.

## H.1 Windows component health

- [ ] Add failing ledger tests for scope isolation, persistence without restored readiness, reconnect reset, stale evidence, monotonic freshness/clock discontinuity and bounded redacted reasons.
- [ ] Implement `crier/component_health.py`: durable SQLite evidence, connection-session reset, allowlisted states/reasons, deterministic snapshots.
- [ ] Instrument existing account/fill, relay, execution and Discord operations in `desktop_runtime.py`, `intent_device.py` and `delivery.py`; avoid extra network checks and preserve delivery semantics.
- [ ] Add hidden-window regressions and a Health tab with timestamps/recovery hints, setup/history navigation and existing disconnect action.
- [ ] Verify focused/full Python checks and Windows packaging/installer CI; document source-bound evidence and remaining H scope.

## Remaining H slices

- [ ] H.2 Native iOS/Android component health and recovery presentation, retaining foreground/background constraints.
- [ ] H.3 Clock/freshness execution-gate and duplicate-preflight review with targeted regressions; classify transport failures by actual send uncertainty.
- [ ] H.4 Optional Windows tray/startup behavior with explicit opt-in and entries paused; no auto-live authorization.
- [ ] H.5 Deliberate sizing/quantity/notional and entry/exit policy design, preserving existing saved settings and broker reconciliation. Do not silently change execution policy as a UI preset.

H.1 does not close all of H, and no source check closes provider deployment, signing or physical acceptance gates.
