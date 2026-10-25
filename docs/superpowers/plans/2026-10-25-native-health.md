# H.2 implementation plan

Continue the owner's approved H scope directly on main. Native UI follows current controls; no broker policy or permission defaults change.

- [x] Add pure Kotlin ledger tests, then implement scoped session tickets, fixed reason codes, monotonic freshness, safe persistence and restart behavior.
- [x] Wire Android Alerts and Trade/Follow observations to existing operations; add a health/recovery dialog and lifecycle tests. Compile all sources and run JUnit.
- [x] Add Swift ledger tests, implement injectable persistence and ticket fences, and wire workspace/intent/Discord outcomes with a native health view.
- [x] Verify iOS simulator tests/unsigned archive and Android packaging in CI. Fix regressions and preserve source-bound evidence.
- [x] Update H.2 completion and remaining H.3–H.5 scope; commit/push evidence to main.

## Verification and scope

Android source `3bb91e0` and combined native source `7aca957` passed local complete Kotlin compilation and **98 JUnit tests**, [Android packaging](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40206593922), [iOS simulator/unsigned archive](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40206587489), and [114 iOS tests plus 732 backend tests/25 expected skips](https://github.com/Tetradim/Sentinel-Crier/actions/runs/40206590599). The [source-bound report](../../acceptance/2026-10-25/native-health/source-evidence.json) retains counts, revisions and artifact checksums.

Tests exercise durable history without restored readiness, independent Android journey contexts, late-ticket rejection, background/foreground and logout during an account response, actual Discord response classification with no automatic uncertain retry, coalesced asynchronous Android persistence and visible storage errors. Native health views refresh local snapshots without additional HTTP. Existing journals, order policies, paper/live controls and publishing permissions remain authoritative.

H.2 is complete. H.3 execution-clock/freshness/preflight review, H.4 optional tray/startup and H.5 deliberate execution-policy design remain open. Signing, physical acceptance and OAuth/provider activation were not performed.
