# Submission-time mirroring (iOS, Android and PC)

Crier now has a separate **intent** path: the host creates a durable instruction when placing an order inside Crier. Local broker execution and relay delivery run independently. Followers do not wait for a host fill. The existing Discord publisher still reports confirmed fills; it does not drive this path.

## Pair once

1. Run the PC service with `python -m crier serve` and open `/intent`. Unlock with the Crier owner token. This instance can be only a relay, or also a trading device.
2. Expose the relay through HTTPS using your existing reverse proxy/private network. A mobile device cannot reach the PC's `localhost`. Crier does not provision hosting, DNS or TLS certificates.
3. Create a paper channel. The console gives separate **host** and **follower** pairing JSON. Paste the host pairing into the trading customer's app, and the follower pairing into your app. Any supported platform may take either role. A channel supports one host and multiple followers; each device keeps its own cursor and journal. Keep the pairing secrets private.
4. Configure each device's own Alpaca account. No brokerage keys pass through the relay. Paper and live channels are separate; test paper first.
5. Enable following and select local pricing policy. Create buys inside the host app, then use that tracked trade's Replace, Cancel or Exit controls.

## Platform setup

- **iOS:** build/sign the current native project using `ios/BUILD.md`. In account settings, save an intent host/follower pairing while disconnected, then reconnect Alpaca. Follower settings start paused. Use Trade to submit a host buy and the tracked intent trade controls to modify/cancel/exit. Keep Crier active; iOS can suspend its network execution in the background. This is native local execution, not the old PC-only receiver.
- **Android:** see `android/README.md`. The native app has its own account, pairing, order entry and follower execution. Android Keystore protects local secrets. An explicit foreground service receives while active; Android can still stop it or limit background data-sync time. The build workflow produces a debug APK for device testing, not a published Play Store release.
- **PC:** set `CRIER_INTENT_ENV` (`paper`/`live`), `CRIER_INTENT_ALPACA_KEY`, `CRIER_INTENT_ALPACA_SECRET` and `CRIER_INTENT_ALPACA_ACCOUNT` (the account UUID returned by Alpaca's account endpoint), then restart `python -m crier serve`. Open `/intent`, paste this PC's pairing and configure execution. The console runs in a browser; Python performs execution locally. On Windows the pairing secret is user-bound DPAPI encrypted; on other platforms it is stored in a mode-0600 file. Broker credentials stay in process environment. No `.env` auto-loading is added.

## Trading behavior

- **Enter:** immediately journal and dispatch a full contract/side/quantity/price instruction, alongside local execution. No fill-based trigger.
- **Replace:** cancel the prior entry remainder, reconcile its terminal broker result, then submit only the new target quantity minus already acquired quantity. A confirmed cancellation can race a fill; remaining quantity comes from actual broker reports.
- **Cancel:** invalidate pending entry instructions and cancel working entry orders. It stops unfilled remainder; it does not liquidate already filled holdings. Use **Exit** to close those.
- **Exit:** invalidate pending entries, cancel any working entry remainder, wait for its terminal state, and sell only actual holdings acquired by that tracked trade, capped by requested quantity and broker availability. Availability-limited exits can continue after earlier sell orders fill, without exceeding the original requested exit quantity. Canceled/rejected exits require inspection or a new exit instruction; ambiguous POSTs never automatically repeat.
- Newer cancellation/exit wins over delayed entry. Queued stale entry instructions are superseded before reconnect delivery. Every instruction has immutable IDs and a monotonic trade revision. Maximum entry age is configurable up to 30 seconds.
- **Exact limit**, **market**, and **bounded limit** policies are selected on each follower. Bounded allowance is the smaller of absolute dollars and basis-point allowance, with conservative tick rounding. It limits price; it does not promise a fill. A market order has no price bound. No execution timing, premium or profit guarantee is possible across accounts.
- Pausing blocks new entries, while cancel/exit handling for tracked trades continues. Revoking a channel blocks future transport and does not cancel broker orders already submitted. Preserve local journals and use the brokerage app to inspect unresolved orders.

The wire contract is in [intent-v1.md](protocol/intent-v1.md). HTTPS protects transport; the relay operator can read and retain order instructions and can revoke pairing. Tokens have separate host publish and follower read scopes. There is no per-trade approval conversation between devices; HTTP delivery tracking and broker reconciliation are internal.

## Current broker scope and validation

Alpaca personal Trading API is implemented on all three platforms. Webull Connect remains awaiting access/integration; copying a client does not create broker access. Supported trading is whole shares and standard long single-leg options; no short opening or multi-leg strategy replication.

Tests use fake broker clients and HTTP transports, not actual orders. Simulator/JVM/backend tests do not replace a physical iPhone/Android/PC paper-account test over the real network. Signing, account credentials, hosting and the paper trial remain installation/release steps.
