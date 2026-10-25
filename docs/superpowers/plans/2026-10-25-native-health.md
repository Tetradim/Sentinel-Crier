# H.2 implementation plan

Continue the owner's approved H scope directly on main. Native UI follows current controls; no broker policy or permission defaults change.

- [ ] Add pure Kotlin ledger tests, then implement scoped session tickets, fixed reason codes, monotonic freshness, safe persistence and restart behavior.
- [ ] Wire Android Alerts and Trade/Follow observations to existing operations; add a health/recovery dialog and lifecycle tests. Compile all sources and run JUnit.
- [ ] Add Swift ledger tests, implement injectable persistence and ticket fences, and wire workspace/intent/Discord outcomes with a native health view.
- [ ] Verify iOS simulator tests/unsigned archive and Android packaging in CI. Fix regressions and preserve source-bound evidence.
- [ ] Update H.2 completion and remaining H.3–H.5 scope; commit/push evidence to main.
