# Sentinel Crier — competitive research and iOS product plan (October 2026)

## Product distinction
Crier is a **broker fill → Discord notification** product, not a Discord signal → broker auto-trading product. Do not claim that an iPhone can continuously read other brokerage apps or execute unrestricted background polling. The current implementation is a self-hosted Python service with a mobile web console; a native iOS client does not yet exist.

## Adjacent products and feature comparison
| Product | Primary workflow | Relevant ideas | Important difference |
| --- | --- | --- | --- |
| TradersPost | TradingView/TrendSpider webhook signal → broker order | Normalized options symbols, broker-specific adapters, structured webhook events, event histories | Opposite direction: order execution rather than publishing observed fills |
| Option Alpha | Options automation and monitoring | Templates, event logs, strategy-specific controls, notifications | Automation platform, not a drop-in brokerage-fill-to-Discord publisher |
| Sentinel Echo (same product family) | Discord analyst alert → broker execution | Consistent BTO/STC nomenclature, source policies, order/fill reconciliation | Reverse direction; do not reuse its execution permissions in Crier |
| Sentinel Crier (current) | Verified broker fill → durable Discord alert | Durable outbox, deduplication, preview, audit, Discord rate-limit handling | Only experimental Webull/Tradier observation; iOS is a web console |

References:
- https://docs.traderspost.io/docs/assets/stock-options-trading
- https://docs.traderspost.io/docs/core-concepts/signals
- https://github.com/Tetradim/Sentinel-Echo
- https://github.com/Tetradim/Sentinel-Crier

## Priority features for customers
1. **Native iOS companion:** SwiftUI onboarding, broker connection status, Discord channel test, live alert timeline, pause/resume, and troubleshooting. Show clearly whether the cloud observer is online. Native UI is not the fill observer.
2. **Always-on hosted observer:** Server-side broker OAuth/API authorization where supported, token rotation and revocation, encrypted secrets, tenant-isolated accounts, health checks, and retry queues. Never embed broker or Discord webhook secrets in the app.
3. **Broker compatibility matrix:** For each broker document official API eligibility, fills vs orders vs positions, options coverage, latency, rate limits, OAuth scopes, and whether retail accounts can connect. Mark unsupported brokers explicitly.
4. **Rich actionable alert cards:** Underlying, OCC contract, strike, call/put, expiration year, action when confirmed, incremental quantity, execution price, timestamp, fill status, broker label, and source provenance. Never infer BTO/STC from BUY/SELL alone.
5. **Partial-fill lifecycle:** Idempotent cumulative fill reconciliation, optional message edits, cancel/reject annotations, stale data markers, and distinct order IDs. Avoid duplicate alerts on reconnect.
6. **Community controls:** Configurable destination channel, per-account publish rules, ticker allow/block lists, options-only mode, quiet hours, optional redaction of quantity and price, and an emergency publishing pause. Preserve audit history.
7. **Operational reliability:** Health notifications, last-seen broker timestamp, reconnect backoff, end-to-end delivery latency measurements, dead-letter review, and manual recovery for ambiguous Discord sends.
8. **Safe follower context:** A non-executing copyable contract string, delayed-fill warning, and educational disclaimer. Never imply followers will receive the leader's execution price.

## Architecture
```text
Official broker API / verified read-only observer
    -> per-customer authenticated ingestion
    -> normalization and cumulative-fill ledger
    -> transactional outbox / idempotency
    -> Discord delivery worker
    -> status + history API
    -> SwiftUI iOS companion (later Android / desktop)
```

Use event identifiers scoped by broker, environment, account, order, contract, and cumulative execution revision. Preserve the raw evidence privately for audit; redact public messages. Design multi-tenancy before offering shared hosting.

## Release gates
- **Broker gate:** Verify manual brokerage trades appear in the supported official API and that cumulative price/quantity semantics are correct.
- **Privacy gate:** Confirm user consent for sharing trade details to a Discord server, configurable redaction, secure deletion, and credential revocation.
- **Delivery gate:** Verify duplicate prevention across restarts, partial fills, 429 retries, and uncertain sends.
- **iOS gate:** Test app background/foreground transitions without claiming the app itself is continuously observing; verify hosted observer continues when the phone is off.
- **Security gate:** Tenant isolation, OAuth callback protection, least privilege, secret encryption, webhook rotation, request authentication, and abuse/rate controls.
- **Store gate:** Review Apple App Store policies and brokerage platform agreements before distribution.

## Practical implementation order
**Phase 1:** Broker capability verification and hosted single-tenant observer reliability. **Phase 2:** SwiftUI companion backed by a documented status/history API. **Phase 3:** Hosted multi-tenant service and broker onboarding. **Phase 4:** Android and desktop clients sharing the same backend.

**Research limitation:** The comparison covers documented adjacent capabilities, not hands-on competitive benchmarking. No broker or Discord credentials were used and no live fill was observed during this research.
