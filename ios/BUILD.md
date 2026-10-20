# Standalone iPhone build and validation

The native app connects directly to Alpaca's official personal Trading API. It does not require the Python backend or a PC after installation. Webull Connect remains pending approval; no Webull order placement is implemented. There is no ReplayKit extension in this target.

## Build on macOS

1. Install Xcode with an iOS simulator runtime and XcodeGen.
2. Run `cd ios && xcodegen generate`.
3. Build: `xcodebuild -project SentinelCrier.xcodeproj -scheme SentinelCrier -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`.
4. Test: `xcodebuild -project SentinelCrier.xcodeproj -scheme TradingTests -destination 'platform=iOS Simulator,name=iPhone 17,OS=latest' CODE_SIGNING_ALLOWED=NO test`. Select an installed simulator if that name differs.
5. For physical installation, configure your Apple team, bundle ID, App Group `group.com.tetradim.sentinelcrier`, and Keychain Sharing entitlement `<TeamPrefix>com.tetradim.sentinelcrier.shared`. A signed archive/provisioning profile is required; simulator output cannot install on a phone.

These instructions are not evidence of a successful build. XCTest, signing, device networking, Keychain access, app lifecycle recovery and paper-broker integration require validation on macOS/iPhone. No broker API request or order was executed during implementation.

## Connect and operate

- Open Home → Connections. Paper is always the launch default. Select paper or live explicitly, then save that environment's Alpaca API key and secret. Secrets are device-only Keychain entries. Disconnect before changing environments. Live orders use real money and have an explicit real-money confirmation label.
- Save a Discord channel webhook in Connections. Choose Homebrew Markdown, plain text or card format in Alerts.
- The first successful refresh establishes a durable fill baseline without posting historical fills. Later active refreshes catch up broker FILL activities by exact execution ID, including fills from other clients on the connected account.
- Trade supports whole-share stocks and standard 100-share single-leg options, day limit orders, buys and closes of existing long holdings. Options discovery requires underlying and an exact expiration; nonstandard contracts are filtered out. Live bid/ask quotes, multi-leg strategies, short opening, automated signals/stops/profit-taking and multi-broker execution are not implemented.
- Enter a limit and review the immutable ticket. Review is a local estimate, not a broker preview or approval. Confirm within 60 seconds. Acceptance is not a fill. Pull to refresh the saved order list; cancellation is a request and must be reconciled.
- Client IDs and submissions are written atomically before POST. Unknown results block new submissions for that account until reconciliation finds the order. Never manually replace an unknown order without checking Alpaca. Preserve the journal if it cannot be read; deleting it removes duplicate protection.
- Orders, positions and fills refresh every 15 seconds only while the app is active. iOS suspension stops polling and Discord delivery. Reopening catches up from the durable baseline. Catch-up is bounded to 10,000 events per refresh and fails without advancing the baseline if exceeded.
- Discord entries become uncertain before sending. Successful `wait=true` responses record the message ID. HTTP 429 creates a shared cooldown and safely returns the item to pending. Timeouts, other HTTP errors and crashes remain uncertain and are not automatically resent. Verify these manually in Discord; there is no unsafe retry button.
- Paper/live and account identities isolate persisted orders and fills. Redirects are disabled for broker and Discord requests. Credentials never appear in persisted tickets or broker error messages.

## Validation before live use

Run all `TradingTests`, then use paper credentials on a physical iPhone to verify discovery, reviewed submission, partial fills, cancellation, foreground catch-up, lost-network reconciliation, relaunch persistence, Discord 429 behavior and environment switching. Live capability is implemented but is not a claim of live or paper execution certification. Keep live credentials disconnected until those checks pass.

Official references: [Trading orders](https://docs.alpaca.markets/us/docs/working-with-orders), [options trading](https://docs.alpaca.markets/us/docs/options-trading), [Trading API models](https://alpaca.markets/sdks/python/api_reference/trading/models.html).
