# H.3 implementation plan

Execute directly on main under the owner's standing approval. Preserve all money/permission defaults and authoritative journals.

- [ ] Reproduce HTTPX pre-send timeout misclassification, add transport-stage regressions, and preserve bounded retries versus uncertain-delivery recovery.
- [ ] Implement/test Python monotonic entry-clock guard and explicit defer/skip reasons at decision and final adapter checks. Retain required broker preflights.
- [ ] Implement/test Android clock guard and visible final-dispatch decisions; leave cancellations/exits and broker reconciliation available.
- [ ] Implement/test iOS clock guard and final main-actor dispatch predicate, with durable local not-submitted markers and unchanged unknown-POST reconciliation. Remove only the immediate duplicate read-only account refresh.
- [ ] Run full Python, native tests/builds and Windows packaging as appropriate; record source-bound evidence and remaining H.4/H.5 work.

Local clock continuity is checked; no cross-device synchronization or physical acceptance is claimed. Static skew, operator automatic-time setup and real provider acceptance remain operational/physical constraints rather than hidden clock correction.
