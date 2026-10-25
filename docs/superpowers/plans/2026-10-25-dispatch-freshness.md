# H.3 implementation plan

Execute directly on main under the owner's standing approval. Preserve all money/permission defaults and authoritative journals.

- [x] Reproduce HTTPX pre-send timeout misclassification, add transport-stage regressions, and preserve bounded retries versus uncertain-delivery recovery.
- [x] Implement/test Python monotonic entry-clock guard and explicit defer/skip reasons at decision and final adapter checks. Retain required broker preflights.
- [x] Implement/test Android clock guard and visible final-dispatch decisions; leave cancellations/exits and broker reconciliation available.
- [x] Implement/test iOS clock guard and final main-actor dispatch predicate, with durable local not-submitted markers and unchanged unknown-POST reconciliation. Remove only the immediate duplicate read-only account refresh.
- [x] Run full Python, native tests/builds and Windows packaging as appropriate; record source-bound evidence and remaining H.4/H.5 work.

Local clock continuity is checked; no cross-device synchronization or physical acceptance is claimed. Static skew, operator automatic-time setup and real provider acceptance remain operational/physical constraints rather than hidden clock correction.

## Completion evidence

Source `41eaa14` plus final review corrections `88ac564` passed **840 local Python tests/one optional SDK skip**, **105 Android tests** and **121 iOS tests**. Final CI on `88ac564` passed Windows Python 3.11 **840/one skip**, Linux Python 3.11/3.12 **818/23 platform skips each**, and the default backend **749/25 expected skips**. Android debug packaging, iOS simulator compilation and unsigned hardware archive validation, and Windows installer lifecycle checks passed on the same revision. See the [source-bound report](../../acceptance/2026-10-25/dispatch-freshness/source-evidence.json).

Final review also rejects pricing settings changed during preflight, validates contradictory iOS not-submitted journal records, and uses Android sleep-inclusive elapsed time. These preserve current policy rather than choosing new price or sizing defaults. H.3 source work is complete; H.4 optional Windows tray/startup and H.5 deliberate execution-policy design remain open. Signing, physical acceptance and provider activation remain external.
