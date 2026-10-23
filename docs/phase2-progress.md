# Phase 2 integration status

Customer-flow implementation is ready for CI validation. The Phase 2 acceptance checklist is in `phase2-acceptance.md`.

Implemented: native invitation setup and receiver controls; Discord card/plain presets or templates, field controls, previews, labeled test messages, delivery status and explicit resolution; authoritative fill ingestion on desktop; journal-preserving credential recovery; per-event quarantine; startup/resume reconciliation; Android service timeout handling; common wire fixtures and platform recovery regressions.

Local evidence: full Python suite passed 367 tests before the final destination-binding regression; that regression and the full Discord settings group passed separately. Windows controls construct successfully; browser walkthrough passes with all requests intercepted. Android production and test compilation passes locally. iOS native validation requires macOS CI.

Recovery intentionally preserves account/channel pins. A channel or account cannot replace unresolved ownership evidence. Android offers separate saved profiles; iOS can archive resolved channels. Windows retains its pinned account/channel and permits verified same-account key rotation. The advanced browser service still obtains broker credentials from service configuration; the native Windows app provides account setup controls.

Malformed records with valid cursors are quarantined. A broken page envelope without a trustworthy cursor stops with a visible connection error. Uncertain Discord delivery is never silently replayed; explicit resolution retains original evidence. Physical devices, remote network trials, hosting and signed distribution remain later roadmap phases.

No live broker orders or Discord posts were made during development tests.
