# H.5 sizing and entry/exit policy contract

Status: design and non-executing reference calculations. These proposed modes are **not connected to order execution or customer settings**. The active source-quantity behavior, saved quantity caps, pricing and reconciliation remain unchanged. This closes the design scope of H.5, not implementation of new live sizing modes.

## Current behavior and migration boundary

| Concern | Active behavior | Proposed explicit choice |
| --- | --- | --- |
| Entry quantity | Source instruction quantity, less cumulative purchases; whole shares/contracts | Source quantity, fixed units, source ratio, or limit-price budget |
| Quantity cap | Reject a source instruction above the saved cap; default 1,000 is a cap, not an order size | Preserve this as `max_source_quantity`; add a separate local-target cap |
| Entry notional | No customer notional cap | Optional explicit limit; unknown valuation blocks notional-controlled entries |
| Partial exits | Requested units, bounded by journal-owned units and available holdings | Keep requested units as default; proportional cumulative exits or close tracked holdings require explicit selection |
| Entry age | Maximum time to submit a new entry | Preserve; never treat it as resting-order lifetime |
| Resting orders | Broker day order; may work after the entry instruction expires | Preserve by default; optional future unfilled-entry cancellation timer is a separate policy |
| Pricing | Exact limit, bounded limit, or explicitly selected market | Preserve; no automatic exit repricing or fallback to market |

Existing settings must migrate to the legacy behavior without decreasing or increasing a cap, enabling entries, choosing a market order, or rewriting an open trade. The reference `from_legacy` projects the existing cap into a proposed model without modifying those settings or journals. Defaults in the proposed schema describe legacy behavior; they are not persisted by this phase.

## Entry arithmetic

All quantities are whole units. Decimal amounts are strings, never binary floating-point values. Reject booleans as numbers, malformed/nonfinite/negative values and unknown fields. The reference has technical bounds of 20 decimal digits and eight fractional places; source/fixed/target caps remain at most 1,000, matching the current protocol envelope.

The local target is calculated once for an accepted entry plan:

- **Source:** source quantity.
- **Fixed:** explicitly chosen local units, which may differ from the source quantity.
- **Ratio:** `floor(source_quantity × ratio_bps / 10000)`, with 1–10,000 basis points. No minimum-one rounding up.
- **Budget:** `floor(budget / (final_buy_limit × verified_multiplier))`. Use the actual proposed limit after bounded pricing, not the source premium or a stale quote. A market order has no hard price bound and cannot use this budget rule.

The existing source cap is checked before transformation. The local cap and optional notional guard reject an oversized target; they do not silently clamp it. A target below one unit produces no order. Standard option valuation requires the broker-verified size of 100 already required by the Python adapter; unknown/adjusted sizes cannot be guessed. Stocks use one share per unit. Reference notional excludes fees and is an estimate, not buying-power approval or a guarantee of execution price.

Example: at a final option limit of $0.20 and size 100, a $150 budget proposes seven contracts and $140 premium notional. At a bounded final limit of $0.22 it proposes six and $132. Neither estimate proves sufficient buying power or permits a broker submission.

## Exit arithmetic and reconciliation

The reference exit model requires explicitly reconciled state. It cannot resolve an unknown POST, an outstanding reservation or a cancellation. Quantity is always bounded by both journal-tracked remaining units and current available holdings; unrelated account holdings cannot increase that bound.

- **Requested units (legacy):** `min(requested_units - sold_for_this_instruction, tracked_bought - tracked_sold, available_holdings)`.
- **Proportional cumulative:** derive the target total sold as `floor(actual_local_bought × cumulative_source_exit_units / pinned_source_entry_units)`, subtract actual local units already sold, then apply tracked/available bounds. A complete source exit closes tracked late fills after they are reconciled. Fractional results stay at zero until sufficient cumulative intent exists.
- **Close tracked holdings:** use all tracked remaining units, bounded by current availability. This is a distinct opt-in policy; a partial source exit must not silently become a full close.

Source cumulative exit units must be authenticated, deduplicated and tied to the pinned source-entry revision. The current v1 wire event alone does not establish that cumulative history. Proportional execution therefore needs a complete validated source ledger or a separately versioned protocol contract; it must not infer a counter from a single partial-exit event. Reject inconsistent counters rather than guessing. Entry pause, age and notional gates do not suppress exits or source cancellations.

A zero due quantity in this preview is not proof of broker terminal status and must not mark a trade resolved. Late fills, existing reservations and newer source revisions remain the responsibility of the authoritative journal/reconciliation flow.

## Required runtime design before activation

The following are prerequisites to a later execution implementation, not claims about this reference model:

1. Save an immutable local plan with account/environment/pair/trade identity, source revision, policy version/revision, sizing inputs, verified contract size, final price basis and target. Persist it before the durable unknown-order reservation. Do not modify the signed source event.
2. Apply changed policies only to new trades after explicit review while entries are paused. Open trades retain their plan through restart. An explicit source replace revision may create a new plan revision; favorable quotes alone never increase the target or produce another buy.
3. Subtract **cumulative purchases**, not current net holdings, when calculating remaining entry units. Selling must not replenish a trade's entry budget. Check confirmed spent notional plus live reservations and the proposed buy against the limit. Missing fill cost/contract size or uncertain reservations block additional notional-controlled entries.
4. Recheck plan/revision, current permissions, quantity/notional bounds and broker identity at final dispatch. A source cancel invalidates entry and cancels outstanding orders through existing reconciliation; it does not close already-filled holdings by implication. Unknown mutations are reconciled and never replayed merely because a policy changed.
5. Preserve legacy open journals without inventing costs, targets, provider identities or source-exit history. Missing information requires inspection; it cannot be marked resolved manually.
6. Keep broker day lifetime as default. A future unfilled-entry timer starts from verified broker acceptance and must survive restart conservatively, reconcile before cancellation, retain cancellation uncertainty and never auto-replace/reprice. Do not implement an exit-price ladder as a UI shortcut.

## Validation and delivery

`crier/policy_preview.py` is a pure reference: no broker client, storage, network, credential or execution permission. Shared JSON scenarios cover stock/standard-option arithmetic, price-budget changes, quantity/notional rejection, strict parsing, partial/cumulative exits, unknown reconciliation and unrelated holdings. Output always identifies itself as preview-only. Eligibility means arithmetic eligibility only; it is not a trade authorization.

Current Windows, Android and iOS settings receive plain-language clarification of source caps and order lifetime, with no new sizing selector or altered default. Before any later execution activation, implement durable-plan migration, complete source-exit provenance and the same fixture contract in each platform, then test unknown submissions, partial fills, restart, policy edits during preflight and per-trade notional reservations. Physical/broker acceptance remains separate.

H.5 design does not implement new live sizing, notional enforcement, proportional exits, timed entry cancellation, or automatic repricing. The next approved customer-ease phase remains **I: customer acceptance** of the implemented app.
