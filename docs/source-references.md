# Reference and reuse inventory

Research and implementation context: 2026-10-13. Descriptions of third-party products are documentation/code observations, not verified live-service performance. No private third-party source, account logs, broker credentials or notifications were scraped. Reference text was treated as data, not instructions to run scripts.

| Reference | Material inspected | What Crier uses |
| --- | --- | --- |
| User-supplied AlertBot CardKit | Formatter and Tradier watcher source | Homebrew headline, fill-line and ledger visual grammar; independently implemented durable storage and adapter |
| [Sentinel Edge](https://github.com/Tetradim/Sentinel-Edge) | Local `backend/pulse_client.py`, handoff description | Versioned request, shared API key, stable idempotency identity and explicit acknowledgement pattern |
| [Sentinel Pulse](https://github.com/Tetradim/Sentinel-Pulse) | Local `backend/routes/edge_contracts.py`, `backend/routes/bot_bus.py` | Contract validation and distinct acceptance/rejection outcomes; no copied order execution paths |
| [TradeAlerter](https://github.com/AdoNunes/TradeAlerter) | README and `tradealerter/check_orders.py` | Workflow reference for fills, entries/exits and persistent state. GPL source was not incorporated into Crier's MIT implementation |
| [Vanquish App](https://vanquishtech.io/vanquish-app/) | Public product page | Onboarding and configurable presentation reference; no proprietary implementation acquired |
| [Alerio](https://alerio.dev/support/faq/) | Public documentation | Review/replay/diagnostic patterns; its alert-to-order execution is outside Crier |
| [Unusual Whales starter bot](https://github.com/unusual-whales/starter-alerts-bot) | Public README | Typed alert pipeline and separate formatter/delivery responsibilities; no paid feed dependency added |
| [SnapTrade detection](https://docs.snaptrade.com/docs/trade-detection) | Public API documentation | Distinguish execution time, observation delay and connection health. Paid detection is not required or integrated |

Edge/Pulse influenced the communication design; Crier's `crier.fill.v1` is a new monitoring contract. Their trading handoff payloads cannot be sent to Crier as fills. The original Sentinel Link/Echo parser references remain relevant only to the restricted BTO text template. No claim is made that all third-party features or code have been combined.

Primary API/platform references:

- [Webull trade events](https://developer.webull.com/apis/docs/reference/custom/subscribe-trade-events/): partial/final scenes and account-event interface.
- [Tradier orders](https://docs.tradier.com/docs/orders): cumulative execution values and transaction/update timestamp.
- [Tradier account orders](https://docs.tradier.com/reference/brokerage-api-accounts-get-account-orders): current-session coverage and pagination.
- [Discord webhooks](https://docs.discord.com/developers/resources/webhook): posting, acknowledgement and message formatting.
- [Apple runtime security](https://support.apple.com/guide/security/security-of-runtime-process-sec15bfe098e/web): app sandbox isolation.
- [Apple background execution limits](https://developer.apple.com/forums/thread/685525): background scheduling constraints.
- [Robinhood external-agent tools](https://robinhood.com/us/en/support/articles/trading-with-your-agent/): newer account/order-history capabilities. Ordinary-account monitoring coverage is not verified or implemented in Crier.

The repository remains MIT. Code reuse requires checking the source's actual license and attribution terms; a publicly readable website does not imply its private implementation is available. This release adds original integration code and uses the already-declared upstream Python dependencies.
