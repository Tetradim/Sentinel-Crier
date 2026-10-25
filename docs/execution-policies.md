# What the execution settings mean

## Available now

Following uses the source instruction's whole shares or contracts. **Source quantity cap** rejects an instruction above the selected cap; it does not set every order to that size or automatically reduce a larger instruction. The existing default is 1,000 and can be lowered in the app.

**Entry submit age** limits how old an instruction may be when a new entry is submitted. An already-submitted day order can remain working after that age. Inspect actual broker status to see whether it is filled, canceled, expired or still working. Pausing new entries leaves source cancel and exit instructions active and does not itself cancel existing broker orders.

Exact-limit, bounded-limit and explicitly selected market pricing retain their existing behavior. Bounded pricing uses the configured slippage allowance. Market orders have no limit-price bound. These settings do not guarantee fills or matching execution prices between accounts.

Exits use the requested quantity, bounded by the remaining units tracked for that trade and the broker's available holdings. Extra holdings in the account do not increase the trade's tracked ownership. Unknown broker outcomes require reconciliation; changing a setting does not resolve them.

## Design-only options

H.5 specifies fixed-unit, source-ratio and limit-budget sizing, separate local quantity/notional limits, proportional cumulative exits, full tracked exits, and a separately configurable entry-order lifetime. These are proposed policies, **not selectable live execution features**. Existing saved behavior remains unchanged.

The [technical design](superpowers/specs/2026-10-25-execution-policy-design.md) explains the required durable trade plans, contract-size checks, cumulative source history, partial-fill costs and reservation handling before those modes can be activated. A premium estimate excludes fees and is not a broker buying-power check.

## Contributor reference checks

From a checkout with the test environment installed, run:

```powershell
python scripts/check_policy_preview.py
python -m pytest tests/test_policy_preview.py -q
```

The first command checks 28 JSON scenarios. The preview model performs no network or file I/O, submits no orders, and saves no settings; the scenario runner reads its fixture file. Passing a calculation is not permission to submit a trade. The model is not connected to Crier's execution engines.
