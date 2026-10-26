# Direct trade mirroring

This documents the **legacy confirmed-fill-to-PC receiver**, a separate path from current native submission-time mirroring. For iOS, Android and PC Host/Receive, use [submission-time mirroring](intent-mirroring.md). The PC-only execution restriction below applies to this legacy receiver.

Crier can send confirmed Alpaca fills from a customer's iPhone directly to a PC receiver, which places matching Alpaca orders. Discord is optional and independent. This version executes on the PC; a phone can open its private web console, but phone-only execution is not implemented.

## Receiver setup

1. Install the current repository with `python -m pip install -e .`.
2. Set `CRIER_MIRROR_ALPACA_KEY` and `CRIER_MIRROR_ALPACA_SECRET` to **the receiving account's** personal Trading API credentials. Set `CRIER_MIRROR_ENV=paper` for testing, or `live` for real money. These are separate from the read-only monitor credentials. Never put them in pairing data.
3. Start `python -m crier serve`. Open `http://127.0.0.1:8765/mirror` on the PC. Unlock with the existing Crier access token (`data/access-token`).
4. Make this service reachable through your HTTPS reverse proxy or private network with HTTPS. On an iPhone, localhost points to the phone, not the PC. The native sender accepts only an HTTPS origin; it does not follow redirects. The PC must remain running. Crier does not provision public hosting, DNS or TLS certificates.
5. Open `/mirror` using that HTTPS address. Enter a customer name and select **Create pairing**. Copy the displayed pairing JSON securely to the customer. It contains a private, revocable send-only token, not your brokerage credentials or owner token. The server stores only its hash.
6. Select **Follow automatically** for that pairing. This authorizes automatic orders in the environment shown until you pause/revoke. No per-order approval is shown. Start with both accounts in paper mode.

## Customer iPhone

1. Install a signed build containing the Mirror settings; signing/TestFlight remains required (see `ios/BUILD.md`).
2. Connect the customer's own Alpaca account and let its initial refresh finish. Historical fills establish a silent baseline.
3. In account settings, under **Direct mirroring**, paste the receiver pairing and tap **Save pairing**. Pairing is stored in Keychain and binds to the first source account it observes. Use a fresh pairing when changing accounts.
4. Keep Crier active. It refreshes approximately every two seconds while paired, plus broker/network latency. It follows confirmed executions, not the instant the brokerage order button is pressed. iOS suspension pauses observation; it does not run an invisible screen watcher.
5. A new supported fill is queued durably, checked against the source broker order, and sent to the receiver. The receiver sends a day limit order for that exact symbol, side, execution quantity and fill price. Opening option buys and closing option sells must have explicit broker-reported position intent. Unknown intent, fractional shares, short orders and unsupported contracts are skipped. Mirrored orders (`crier-m-` client IDs) are not forwarded again.

## What to expect

- Exact OCC symbols carry strike, call/put and expiration year. Each partial execution uses its incremental quantity, not the order's cumulative quantity.
- Paper follows paper; live follows live. No implicit paper-to-live conversion.
- Orders use the source fill price as a limit (rounded conservatively to a supported decimal increment), not a market order. They may not fill when prices move. Receiver and source P&L/holdings can diverge.
- The receiver checks active account, option permissions, standard contract size, open market and available holdings. It will not open shorts or sell more available contracts than it owns. It skips rather than shrinking the requested quantity.
- Fills older than 60 seconds are skipped. Pausing consumes arriving events without ordering; resuming does not replay them. Pause does not cancel existing orders; manage those in the brokerage app.
- Duplicate transport deliveries keep the same event/client order identity. The receiver journals `unknown` before submitting. A timeout never triggers a fresh order POST. **Reconcile broker orders** checks the saved client IDs; unresolved orders block new execution. Inspect unresolved cases in Alpaca before taking any action outside Crier.
- Customer tokens can send fills only. Owner access is required to create/revoke pairings, Follow/Pause and view history. Revoking stops future requests; it cannot undo an already submitted order.
- Changing receiver account or environment invalidates execution for old pairings; create new ones. Preserve the receiver database and iPhone journal, which hold duplicate-prevention history.

## Validation

Development tests use fake brokers and HTTP transports, never customer funds. Test duplicate deliveries, restart, altered replay, expired events, pause/resume, unknown submissions, reconciliation, account/environment mismatch and insufficient holdings before a paper end-to-end trial. A simulator build is not a physical-device or brokerage execution test.

Alpaca references: [order parameters](https://docs.alpaca.markets/us/reference/postorder), [client-ID lookup](https://docs.alpaca.markets/us/reference/getorderbyclientorderid).
