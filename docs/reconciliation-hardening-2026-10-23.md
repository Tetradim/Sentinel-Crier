# PC intent reconciliation hardening

## Reproduced defect

The Python intent executor accepted broker snapshots containing fractional filled quantities for standard options, blank/non-string broker IDs, unknown status values, or nonpositive/nonfinite supplied average fill prices. Nine regression cases reproduced acceptance before the fix. Invalid evidence could enter the execution journal and diagnostics instead of requiring reconciliation.

## Change

Before updating `intent_orders`, reconciliation now requires a nonblank string broker ID, a recognized Alpaca status, an integral cumulative filled quantity within the reserved quantity and at least the previous filled quantity, and a finite positive average fill price when supplied. Existing symbol, side, client-order ID and broker-order ID bindings remain enforced. Whole shares and standard single-leg options remain the supported intent assets.

Malformed evidence leaves the durable order unknown or at its last validated state. It cannot authorize an exit or a duplicate entry. Once corrected evidence arrives, normal reconciliation can resume, including after restart. An absent average price remains absent; this change does not invent a fill price or require a price on an unfilled order.

## Verification

Focused executor suite: 53 tests passed. Complete Python suite: 486 tests passed, with one existing FastAPI/Starlette HTTPX deprecation warning. Regressions cover malformed first snapshots, blocked exit after invalid evidence, restart and subsequent valid partial-fill recovery without another buy. Independent review found no actionable regression; its requested explicit assertion that status remains unknown was added and the ten affected regression cases passed again.

No broker connections or orders are used in these tests. These source changes do not replace the separately required physical/paper acceptance, and previously packaged Windows artifacts do not contain this fix until rebuilt.
