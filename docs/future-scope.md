# Future scope

These are proposed enhancements, not implemented capabilities or changes to execution defaults. External release/provider/device dependencies are tracked in [remaining work](remaining-work.md). Donor source references and limitations are in the [Sentinel inventory](sentinel-feature-inventory.md).

## D.1 â€” Multiple Hosts, Connections, and Cross-Broker Copying

Retain the [deferred research](deferred/multi-host-cross-broker.md): multiple private host subscriptions, simultaneous brokerage sessions and explicit host-to-destination-account routing. For example, a receiver could follow an Alpaca host through an authorized Webull account while another connection follows a different host through Tradier.

- A connection list showing host, destination account, paper/live environment, asset capabilities, status and entry permission per route.
- Private invitations and deliberate subscriptions, without global host discovery or unsolicited invitation flooding.
- Per-route pause/revoke and allocation controls, preserving reconciliation and authorized exits for existing positions.
- Durable identities scoped by source event, destination account/environment and order revision, with feedback-loop prevention.
- Per-host ownership when several hosts use the same instrument/account, plus shared cash and exit-quantity reservations.
- Explicit contract mapping and broker capability checks. An unavailable broker must not silently redirect an order to another account.

Status: implementation resumed October 29. Concurrent independent Alpaca account routes are being implemented; shared-account reservations and arbitrary cross-broker execution remain future work. See [current multiple connections guide](multiple-connections.md).

## D.2 â€” Independent Trading Policies and Stock/Option Allocation

### Authority and independent entries/exits

Preserve host-follow as the default. Receiver protection and independent strategies would require explicit, separate opt-ins. Record authority and policy with each admitted trade. Independent trades need their own ownership and funding records rather than attribution to the host.

Candidate controls: independent stock/option entry switches, signal/data freshness, scale-in/reentry limits and a preview explaining what can cause a local entry or exit. Settings changes must distinguish future trades from explicit migration of existing positions.

### Stops, trailing and staged exits

Adapt Echo's coordinated policy through one executor:

- Fixed price/percentage stops, break-even activation, profit floors and staged partial profit taking.
- Trailing activation, distance, minimum cents, spread allowance, optional tightening and runner allocation.
- Fresh executable quotes, persisted high-water marks and a floor that never loosens after arming.
- Time/expiry-aware exits with explicit treatment of working entries and partial fills.
- One coordinator for host exits, protective exits and pending orders, with durable owned-quantity reservations.
- Visible distinction between broker-native and app-managed protection. App-managed protection depends on worker availability; mobile suspension remains relevant.

### Optional execution fallback

Configure entries and exits separately, default off. Choices could include cancellation without replacement, bounded aggressive limit repricing or an explicitly authorized market replacement.

Before replacement: reconcile the prior order, confirm terminal/cancellation evidence, account for late fills, calculate only the remainder and persist a distinct child-order reservation. Unknown submission/cancellation status blocks another submission. A host cancel/exit must invalidate a pending entry fallback appropriately.

Candidate inputs: wait time, eligible order types, replacement-attempt limit, limit-price tolerance, session/liquidity eligibility and a recorded fallback reason. Market orders cannot guarantee a maximum purchase price or minimum sale price. Funding, permission and contract errors must not trigger market fallback.

### Separate stock/options funding

Crier already supports both instruments. Proposed additions are separate enablement, sizing and funding:

- Per-account dollar/percentage pools for stocks, options and unallocated cash.
- Per-trade caps and shared reservations across hosts, routes and asset pools, bounded by verified account capacity.
- Explicit accounting for pending buys, unknown submissions, fees, released capital and optional borrowing between pools.
- Shares/lot rules for stocks; verified deliverables, multipliers and open/close intent for options.
- No automatic transfers between brokers or assumption that buying power equals settled cash available for every asset.

The current per-trade entry budget does not replenish when units are sold. A reusable allocation mode must be a separate policy.

### Optional recurring stock-card mode inspired by Pulse

Pulse is stock-only. Its intended model assigns capital to stock/ETF cards and reuses each allocation across repeated buy/sell cycles. A $10,000 account can assign $1,000 to SPY, $5,000 to QQQ and $4,000 to IWM, with percentage or absolute-price triggers. Unlimited cycles do not imply unlimited concurrent spending.

That model is valid for Pulse. Missing option multipliers or stock/options pools are not Pulse defects. A helper without an atomic ledger does not alone prove overspending: card budgets, reservations and execution serialization must be traced first. Identity collisions and crash recovery remain separate source-review concerns whose reachable production paths need verification.

For Crier, consider reusable per-card allocations, independent buy/sell thresholds, optional profit reinvestment, explicit reentry/cooldown rules and complete cycle history. Replenish only from reconciled broker evidence, respecting account cash rules and outstanding orders. Keep recurring cards separate from one-shot host-follow trades, with a durable identity per cycle.

## Research and acceptance ideas

- A broker capability matrix: stocks/options, fractional shares, native stops/trailing, order streams, cancel/replace and sessions.
- Record/replay tests for late fills, ambiguous cancellations, duplicate delivery, restart, stale quotes and competing host/protective exits.
- A funding view explaining allocated, reserved, invested and available amounts by account, asset pool and host/card.
- Preview-only policy comparison using recorded evidence; replay must never accidentally create live orders.
- Measured cross-network delivery/acknowledgement/fill timelines with clock uncertainty, stream/poll status and suspension gaps.

Suggested sequence: define authority/accounting; establish the common reservation/reconciliation boundary; adapt pure stop/trailing decisions; add optional fallback and asset pools; evaluate recurring cards; resume D.1 only when selected. Each item needs its own implementation and acceptance scope.
