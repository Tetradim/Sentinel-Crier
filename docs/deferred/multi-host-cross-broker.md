# D.1 — Multiple Hosts, Connections, and Cross-Broker Copying

Status: **Implementation resumed October 29, 2026. Concurrent independent Alpaca routes are being implemented on Windows, iOS and Android. Shared-account coordination and additional execution adapters remain unfinished.**

See [current routing guide](../multiple-connections.md) and [implementation plan](../superpowers/plans/2026-10-29-multiple-connections.md). The research below describes the full requested scope, not a claim that every broker/route is available.

Researched October 26, 2026. This is outside the completed E–L implementation phases. Recheck broker documentation and granted application permissions before starting implementation. No brokerage requests, orders, customer messages or runtime changes were made for this research.

## Intended customer experience

One installed Crier app can maintain several independent host subscriptions and brokerage connections simultaneously. Customers select which host feeds which account. Opening several copies of the application should not be necessary.

Example future routing:

| Source host and brokerage | Receiver's selected destination | Intended behavior |
| --- | --- | --- |
| Dave / Alpaca | Carol / Webull | Translate Dave's canonical instruction into Carol's authorized Webull order. |
| Alice / Tradier | Carol / Alpaca | Follow Alice in a separate account or broker connection. |
| Erin / Webull | Carol / Tradier | Follow Erin through a third independent route. |
| Dave and Alice | The same Carol account | Preserve separate host allocations while sharing account-level reservations and reconciliation. |
| Dave | Several explicitly selected Carol accounts | Fan out one instruction once per configured destination, with independent outcomes. |

These are requirements to build and test, not descriptions of current broker execution support. Current native execution is Alpaca-based. Tradier is a read-only Python observer; Webull Connect approval and a working native execution adapter remain pending. Each new route runtime retains one pairing; the connection manager permits several independent account routes within the existing application instance.

## Connection models researched

| Model | Use in Crier | Tradeoffs and future decision |
| --- | --- | --- |
| Direct broker APIs with customer OAuth | Separate authorized Alpaca, Tradier and Webull sessions behind one app connection manager. | Preferred first design for destination control and fewer intermediary hops. Requires an adapter, supported permissions and provider approval where applicable. |
| Direct personal API credentials | Customer connects their own permitted accounts using keys/tokens. | Useful where supported; isolate credentials by account and environment. Personal access does not automatically permit public app distribution. |
| Unified brokerage middleware | An optional service such as SnapTrade supplies several brokerage adapters. | Could reduce integration work, but broker/asset capabilities, commercial access, confirmation rules, latency and costs need separate validation. Do not assume one provider supports every requested options route. |
| Independent app processes / isolated OS profiles | Separate runtimes and separate stores per host/account. | Possible architectural alternative on suitable systems, but cumbersome for customers and does not solve shared-account order ownership. Not the preferred phone experience. |
| Read-only aggregation or chart webhooks | Supplementary observations or explicitly labeled signals. | Balance/position access or a chart signal is not authority to place an options order, nor proof of an external app's submission or fill. |

Connection authentication, relay delivery and broker event subscriptions are separate layers. Existing Supabase push can carry host instructions without requiring the host and receiver to use the same broker. MCP is an administration/development interface, not a replacement for the execution adapters or the low-latency transport.

## Broker findings from primary documentation

### Alpaca

Alpaca supports third-party Trading API access through OAuth. An OAuth grant may cover live and paper access; additional paper accounts can require separate authorization. Account identities and environments must remain explicit. [OAuth documentation](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api).

Options use the Orders API, with contract lookup by symbol or ID and account options permissions. Crier must validate each destination's actual contract and permissions rather than copy a broker-specific ID. [Options documentation](https://docs.alpaca.markets/us/docs/options-trading).

Order/account events use a separate trade-update WebSocket from market data. Use that channel for reconciliation where supported, with durable recovery reads; quote streams are not fill evidence. [Order streaming](https://docs.alpaca.markets/us/v1.4.2/docs/websocket-streaming).

### Tradier

The trading API supports equities and options, order changes/cancellation, and separate production and paper endpoints. Options identify the OCC contract and distinguish opening from closing actions. An optional order tag must not be assumed to enforce idempotency. [Trading](https://docs.tradier.com/brokerage-api/trading), [order fields](https://docs.tradier.com/docs/orders).

Account streaming can cover multiple accounts authorized by the same token. Its documentation permits one account stream and one market-data stream at a time, not one of each per host; account streaming is labeled Beta. Paper and live accounts cannot share the same account stream. Recheck sandbox streaming availability separately; the FAQ says delayed paper streaming is unavailable. [Streaming](https://docs.tradier.com/docs/streaming), [FAQ](https://docs.tradier.com/overview/faq).

Distributed applications require Tradier Partner access; personal tokens alone do not establish approval to distribute Crier's integration. Sandbox market data is delayed, so its timings cannot establish live execution latency. [Integration overview](https://docs.tradier.com/docs/getting-started-advisors).

### Webull

Webull Connect is the customer-facing OAuth integration path and documents account access, trading and options subject to application permissions. Its application, integration-detail and sandbox approval steps remain external dependencies for Crier. Use the documented Connect endpoints and headers; do not interchange them with personal OpenAPI authentication. [Connect documentation](https://developer.webull.com/apis/docs/connect-api/about-connect-api/).

The same page currently specifies **fewer than 90 API requests per minute per authorized user**. Multiple hosts sharing that user's connection therefore need a shared request budget, pooled reconciliation and reserved capacity for urgent order actions. Do not multiply that allowance by the number of hosts. Verify the approved integration's actual limits before implementation. [Connect limits](https://developer.webull.com/apis/docs/connect-api/about-connect-api/#rate-limits).

Separately, personal OpenAPI documents a gRPC order-event subscription, including client/broker order identifiers and fill/modify/cancel outcomes. That is not proof that the pending Connect integration grants the same stream or supplies every initial submission event. [OpenAPI trade events](https://developer.webull.com/apis/docs/reference/custom/subscribe-trade-events/).

### Middleware reference: SnapTrade

SnapTrade documents multiple brokerage integrations and brokerage-dependent options support, with separate integrations for some regions and paper accounts. Its trading guide recommends roughly one trade request per second per account. Its confirmation guidance also needs explicit compatibility review before choosing it for unattended mirroring. Treat it as an optional research candidate, not a verified substitute for all three direct adapters or a guaranteed free service. [Integration model](https://docs.snaptrade.com/docs/integrations), [trading support](https://docs.snaptrade.com/docs/trading-with-snaptrade), [confirmation requirements](https://docs.snaptrade.com/docs/order-impact-and-confirmation).

## Cross-broker example: Dave on Alpaca, Carol on Webull

Proposed flow, preserving the existing submission-first design:

1. Dave enters an order inside Crier. Crier saves and publishes the canonical instruction without waiting for Dave's fill.
2. Carol's explicit subscription selects her Webull connection and account. Dave's credentials and broker order ID are not execution authority for Carol.
3. Resolve the exact contract on Webull: underlying, full expiry including year, call/put, strike, currency, contract size and deliverable. For illustration, a SPY December 18, 2026 $750 call is a contract identity, not a current listing or price claim. Confirm actual availability through the destination API.
4. Build a new Webull order using Carol's configured quantity/pricing policy and opening/closing intent. Unsupported contracts, permissions or order features produce a visible blocked result; never silently substitute another strike, expiry, asset, broker or account.
5. Persist Carol's own submission identity and destination order ID. Reconcile her fills independently of Dave's.
6. Dave's changes, cancellation and exit remain tied to his source trade and Carol's particular child orders/allocated fills. A cancellation request does not prove an order was canceled before a fill.

Matching a contract does not guarantee matching fills, premiums or outcomes across brokers. Mirror intent; record each account's actual execution. Observation of an order placed in another brokerage's vanilla UI remains dependent on what that broker exposes and when it exposes it.

## Required architecture before enabling simultaneous routes

- **Distinct identities:** separate broker authorization, broker account, host subscription and routing rule. Role is per channel; a device may eventually host one channel while following others. Keep existing pairings intact through migration.
- **Immutable routing:** capture host subscription, destination connection/account, environment and route revision when accepting an instruction. A later settings change must not move an existing trade to another account. No automatic fallback to an unselected broker.
- **Scoped idempotency:** durable child-submission identity per subscription, source event and destination route. Learn each broker's order-ID/tag guarantees. A timed-out POST remains unknown until reconciled; do not assume a tag makes blind retries safe.
- **Position ownership:** record per-host, per-trade destination fills. If Dave contributes two contracts and Alice three to the same net broker position, Dave's exit must affect only Dave's allocation, capped by verified available holdings after other reservations. Preserve separate accounting for manual trades and unexplained broker changes.
- **Shared-account coordination:** serialize conflicting mutations and reserve quantities/buying power across every host using that account. Independent per-host limits cannot each spend the same available funds.
- **Connection pooling:** share broker streams only where supported, keyed by customer authorization and environment, then fan out internally. Maintain separate relay cursors per host; one disconnected broker should not stop unrelated routes. Avoid a single global broker selector or one timer/stream per host.
- **No copying loops:** do not publish a received mirror order as a fresh originating host instruction. Preserve original provenance and enforce loop suppression across devices/channels, including orders rediscovered by a broker fill observer.
- **Permission and lifecycle boundaries:** independently pause/revoke routes, reject late callbacks after account/logout changes, and preserve unresolved orders and ownership journals. Removing a subscription must not silently abandon reconciliation or erase allocations. Do not add autonomous exits or a strategy that opposes the host.
- **Simple UI:** a Connections page plus a host-to-account routing table, explicit destination/environment and per-route health. Opt-in host discovery can be evaluated separately; no global invitation broadcasts or automatic pairing.
- **Capability matrix:** verify broker, region, account, asset, order type, session, tick size, options approval and environment. Begin with the existing whole-share/standard long single-leg scope. Multi-leg strategies, adjusted contracts and other instruments require separately validated semantics.

## Future work sequence and acceptance

1. Connection/subscription/route data model and backward-compatible persistence; no execution changes yet.
2. Isolated multiple-host receipt, dashboard and lifecycle support on Windows, Android and iOS.
3. Shared destination-account coordinator, allocation ledger, idempotency and provenance/loop protection.
4. Direct broker adapters and exact instrument resolution, gated by actual granted integration capabilities.
5. Destination routing UI, independent status and account-level quota scheduling.
6. Exercise all nine directional pairs among Alpaca, Tradier and Webull where supported. Cover two hosts buying the same contract, partial fills, replacements, cancellation races, unknown submissions, manual position changes, revoked access, expired tokens, restarts, reconnects and simultaneous cash reservations. Verify one-to-many routes and no duplicates or cross-host sells.
7. Use supported broker sandboxes for accounting/protocol checks; keep synthetic, delayed-paper and real cross-network timing evidence distinct. Physical/mobile lifecycle, real broker-UI reconciliation and provider acceptance remain separate gates.

The initial implementation supports independent Alpaca routes within one app. Shared-account coordination, additional execution adapters, public discovery and automatic brokerage switching remain unfinished. Preserve each host's instructions and each receiver's actual order ownership.
