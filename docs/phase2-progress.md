# Phase 2 implementation evidence

Phase 2 software implementation and automated validation are complete. The Phase 2 acceptance checklist is in `phase2-acceptance.md`.

Implemented: native invitation setup and receiver controls; Discord card/plain presets or templates, field controls, previews, labeled test messages, delivery status and explicit resolution; authoritative fill ingestion on desktop; journal-preserving credential recovery; per-event quarantine; startup/resume reconciliation; Android service timeout handling; common wire fixtures and platform recovery regressions.

Validation: backend CI passed 367 tests with one platform-specific skip; Android production/test compilation and 41 JUnit tests passed, with APK build successful; iOS simulator compiled and all 82 tests passed. Windows packaging passed; Windows controls construct successfully, and the browser walkthrough passed with all requests intercepted.

Implementation commit: `2e03e3c`; numeric price test correction: `c7045c0`. iOS/backend rerun: https://github.com/Tetradim/Sentinel-Crier/actions/runs/39957885426 . Android build: https://github.com/Tetradim/Sentinel-Crier/actions/runs/39956516748 . Windows package: https://github.com/Tetradim/Sentinel-Crier/actions/runs/39956516774 .

Recovery intentionally preserves account/channel pins. A channel or account cannot replace unresolved ownership evidence. Android offers separate saved profiles; iOS can archive resolved channels. Windows retains its pinned account/channel and permits verified same-account key rotation. The advanced browser service still obtains broker credentials from service configuration; the native Windows app provides account setup controls.

Malformed records with valid cursors are quarantined. A broken page envelope without a trustworthy cursor stops with a visible connection error. Uncertain Discord delivery is never silently replayed; explicit resolution retains original evidence. Physical devices, remote network trials, hosting and signed distribution remain later roadmap phases.

No live broker orders or Discord posts were made during development tests.
