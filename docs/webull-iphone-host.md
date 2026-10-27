# Webull iPhone host to Alpaca-paper Windows receiver

This route is for orders entered **inside Crier on iPhone**, using the customer's Webull account. The Windows receiver uses its own Alpaca paper account. It does not observe button presses in Webull's own app.

## Implementation and availability

The candidate native Webull Host screen has its own recovery journal and Keychain pairing. The candidate server gateway validates customer/account scope and durably reserves source order identities. Existing intent-v1 transport and the Windows Alpaca-paper executor are reused.

**This is not an activated Webull integration.** The Webull Connect application is still pending approval. The authorization coordinator/token-custody bridge, secure browser callback and deployable function are now composed; see [authorization service assembly](webull-authorization-deployment.md). Approved account/contract/order resource binding, protected configuration, deployment and actual sandbox acceptance remain unfinished. Unconfigured capability checks remain unavailable; fixtures do not supply a real account.

The gateway implementation is in `supabase/webull-host/`; its integration notes identify the exact provider boundary. [Existing Connect authorization components](webull-server-operations.md) now back the composed authorization runtime, not a deployed customer trading service. [Webull's official Connect overview](https://developer.webull.com/apis/docs/connect-api/about-connect-api/) requires approved application details and sandbox testing. Its [OAuth guide](https://developer.webull.com/apis/docs/connect-api/authentication/) keeps application secrets server-side. Connect resource paths must not be inferred from personal Trading API examples.

## Candidate customer flow after service activation

1. Install a signed Crier build on the iPhone. Apple enrollment/signing is still deferred.
2. Sign in to the Crier customer service through Provider connections. The Webull service must verify customers against the same configured authentication project.
3. Open **Webull Host** from Home. Configure the trusted Webull gateway, select sandbox or production, and check its capabilities/connection. Complete official Webull browser authorization when offered, then check the connection again.
4. Create the separate **PAPER receiver** host route and share a private single-use invitation.
5. On Windows, configure Alpaca paper credentials, select Receive and accept that invitation. Review the receiver's execution settings and explicitly enable entries.
6. On iPhone, review the source environment/account and acknowledge that the destination is Alpaca **paper**, even when the source is Webull **production**.
7. Enter the exact supported stock symbol or canonical OCC option symbol, whole-unit quantity and limit price. Confirm explicitly. Inspect the source order and Windows receiver result independently.

Start actual integration acceptance with Webull sandbox and Alpaca paper. Selecting production can place real Webull orders once the provider service is active; the paper destination does not make the source order a paper trade.

If Windows already has a different saved channel, resolve its orders and use the existing archive/change-connection flow before accepting this new invitation. Preserve unresolved journals rather than deleting them to bypass an account/channel pin.

## Submission and recovery semantics

- Confirmation durably records the source order identity and receiver instruction before source submission. The receiver instruction is published without waiting for a Webull fill.
- Source environment/account stay in the Webull journal. The relay event's environment is `paper`, describing the destination. Broker tokens are not copied into the relay.
- Stock symbols and option contracts must map exactly. Standard long single-leg options only; no guessed expiration, strike, right or deliverable. Broker approval/metadata determine actual availability.
- A rejected source buy creates an invalidating cancel instruction. That cancels the receiver's unfilled remainder; it does not automatically liquidate receiver holdings already acquired. The receiver can fill before the source rejects.
- Unknown source submission outcomes remain pending reconciliation by the saved client ID. Restart/reconnect does not automatically POST the order again.
- Foreground automatic reconciliation reads at most one pending source order per five-second tick. Settled history is refreshed explicitly, including at mutation boundaries, rather than consuming broker quota indefinitely. These observations are separate from immediate intent publication.
- Replacement and sale reconcile prior orders and racing fills first. Source sales are bounded by tracked ownership and current available holdings; the approved server adapter must also prevent short creation and oversubscribed working sales.
- Exit review is available before the periodic fill display catches up. Confirmation performs fresh source reconciliation and still requires verified owned quantity; a stale zero on the screen is not itself a reason to delay that check.
- Publication retains ordering and original timestamps. Reconnect must not create a fresh entry instruction from an expired one.

Keep the iPhone app foregrounded while hosting this route. iOS suspension can stop publication/reconciliation. Keep Windows awake and connected. The new source view does not add an unattended watchdog, guaranteed execution latency or broker-native protective stops.

## Verification boundaries

Native tests exercise source/destination separation, journal recovery, receipt validation, cancellation ordering and exit quantities. Gateway tests use synthetic principals/provider responses; receiver tests use the real Alpaca adapter against intercepted HTTP. These tests make no real orders or Discord posts.

The [candidate verification](acceptance/2026-10-26/webull-iphone-host/README.md) and [implementation plan](superpowers/plans/2026-10-26-webull-iphone-alpaca-pc.md) record completed checks and remaining provider integration work. General multiple-host subscriptions and arbitrary cross-broker routing remain [deferred D.1](deferred/multi-host-cross-broker.md); this candidate is a single Webull-host-to-Alpaca-paper route.
