# Phase K — fresh terminal broker evidence

- [x] K.1 Reproduce terminal-cache and unavailable-evidence cases; fix Python decisions and local no-POST handling.
- [x] K.2 Android fresh broker-backed terminal reconciliation with fault/recovery tests.
- [x] K.3 iOS fresh broker-backed terminal reconciliation with lifecycle and fault/recovery tests.
- [ ] K.4 Review, full/native/platform/package checks and source-bound evidence; update current guides and push main.

Contract: [fresh terminal reconciliation](../specs/2026-10-26-terminal-reconciliation.md). Existing Phase J evidence remains a historical accepted checkpoint; Phase K verifies the added reconciliation boundary. Provider/signing/physical work remains deferred.

Local checks: 989 Python tests passed with one optional SDK skip; Android production/unit sources compiled with 153 tests passed. Independent review also covered cancellation despite an unrelated failed lookup, final Android lifecycle/OAuth cancellation fencing, iOS cancellation-only resume handling, and completion of zero-due/stopped instructions without historical polling. Native iOS and packaging/source-bound CI remain pending.
