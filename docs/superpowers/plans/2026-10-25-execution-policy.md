# H.5 execution-policy design implementation plan

Execute the approved design scope directly on main. Preserve saved execution behavior and all broker reconciliation gates.

- [ ] Audit existing source/follower quantity, price, age, exit and contract-size semantics; record active versus proposed behavior and migration requirements.
- [ ] Write failing scenario and invariant tests for a pure entry/exit preview model, strict inputs, legacy projection and zero mutation of real settings/journals.
- [ ] Implement `crier/policy_preview.py` and a read-only scenario runner. Cover source/fixed/ratio/budget targets, decimal notional and requested/proportional/full-tracked exits without connecting the model to execution.
- [ ] Clarify existing quantity caps and pre-submission age versus resting-order lifetime in Windows, Android and iOS settings; add no live sizing modes or new defaults.
- [ ] Run Python, native builds/tests and Windows packaging as appropriate, preserve source-bound evidence, close H.5 design and identify phase I acceptance and external gates separately.
