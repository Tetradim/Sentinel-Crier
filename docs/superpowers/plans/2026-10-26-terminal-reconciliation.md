# Phase K — fresh terminal broker evidence

- [x] K.1 Reproduce terminal-cache and unavailable-evidence cases; fix Python decisions and local no-POST handling.
- [x] K.2 Android fresh broker-backed terminal reconciliation with fault/recovery tests.
- [x] K.3 iOS fresh broker-backed terminal reconciliation with lifecycle and fault/recovery tests.
- [x] K.4 Review, full/native/platform/package checks and source-bound evidence; update current guides and push main.

Contract: [fresh terminal reconciliation](../specs/2026-10-26-terminal-reconciliation.md). Existing Phase J evidence remains a historical accepted checkpoint; Phase K verifies the added reconciliation boundary. Provider/signing/physical work remains deferred.

Final checks: **990 Python tests passed / one optional Webull SDK skip**, **153 Android tests**, **147 native iOS tests**, **five Android emulator tests**, **one iOS simulator UI test**, Windows/Linux matrices, native/debug/unsigned archive builds, portable smoke and Windows installer lifecycle. The [source-bound evidence](../../acceptance/2026-10-26/terminal-reconciliation/source-evidence.json) records eight successful runs at `a292b06` and the unchanged native/guide components verified at `22595df`.

Independent review covered cancellation despite an unrelated failed lookup, final Android lifecycle/OAuth cancellation fencing, iOS cancellation-only resume handling, stopped/zero-due completion without historical polling, and the diagnostic-proven upgrade of old synthetic HTTP-refusal records. Unknown POSTs are not converted to no-POST outcomes. Execution health remains blocked when cancellation succeeds but other proof is unavailable.

Phase K's code and automated verification scope is complete. Provider activation, signing and real broker/cross-network/physical acceptance remain [deferred](../../remaining-work.md). No real orders or Discord messages were sent.
