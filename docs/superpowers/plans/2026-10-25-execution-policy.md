# H.5 execution-policy design implementation plan

Execute the approved design scope directly on main. Preserve saved execution behavior and all broker reconciliation gates.

- [x] Audit existing source/follower quantity, price, age, exit and contract-size semantics; record active versus proposed behavior and migration requirements.
- [x] Write failing scenario and invariant tests for a pure entry/exit preview model, strict inputs, legacy projection and zero mutation of real settings/journals.
- [x] Implement `crier/policy_preview.py` and a read-only scenario runner. Cover source/fixed/ratio/budget targets, decimal notional and requested/proportional/full-tracked exits without connecting the model to execution.
- [x] Clarify existing quantity caps and pre-submission age versus resting-order lifetime in Windows, Android and iOS settings; add no live sizing modes or new defaults.
- [x] Run Python, native builds/tests and Windows packaging as appropriate, preserve source-bound evidence, close H.5 design and identify phase I acceptance and external gates separately.

## Completion evidence

Source `993ee65` passed **922 local Python tests/one optional SDK skip**, **119 focused policy/engine/clock tests**, **55 reference tests**, and the **28-scenario** read-only runner. The reference ran with network/file I/O forbidden, and its legacy-cap projection preserved a real settings/journal snapshot. Production execution engines do not call this model.

Final CI passed Windows Python 3.11 **922/one skip**, Linux Python 3.11/3.12 **892/31 expected skips each**, default backend **823/33 expected skips**, **105 Android tests** with debug packaging, **121 iOS tests**, simulator compilation/unsigned hardware archive, and Windows installer lifecycle checks. The Windows release environment passed **853/three optional skips** before packaging. See the [source-bound report](../../acceptance/2026-10-25/execution-policy/source-evidence.json).

H.5's approved design scope is complete. The [customer settings guide](../../execution-policies.md) distinguishes shipped behavior from the proposed modes. Live fixed/ratio/budget sizing, local notional enforcement, proportional/full-tracked exit selection and timed cancellation remain unimplemented design options; no new execution policy was activated. Phase I customer acceptance is the next approved source-work phase. Provider activation, signing and physical acceptance remain external.
