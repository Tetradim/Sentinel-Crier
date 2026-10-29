# Multiple host and account connections

Crier can retain several independent Alpaca Host/Receive connections in one installed application. Each connection pairs one host channel with one selected account and environment. Selecting another connection changes the editor; it does not stop an already connected route. Entries start paused and app restart never reconnects or enables them automatically.

## Set up

1. Keep the original connection and its journals. Add a new connection for each different host/account route.
2. Create a Host pairing or accept the intended host's private invitation in that connection.
3. Verify that connection's own Alpaca account and paper/live environment. Use a different destination account/environment for each route.
4. Inspect its sizing, price and exit settings, then explicitly enable entries when ready.
5. Select another connection and repeat. Each route retains separate credentials, pairing, trade history, cursors and execution controls.

Support exports the selected Windows route's technical log. Select and export each affected route when reporting a multi-connection issue; do not share raw recovery snapshots.

Windows: use the **Connection (Alpaca)** selector and **Add connection** above the main tabs. The normal Disconnect action stops only the selected route. Quit and installer update drain all routes. Update recovery snapshots retain the complete root profile, including every route's journals.

iPhone: use the connection picker and **Add**. The original session remains retained while another is displayed. **Stop all** and app backgrounding revoke and drain all retained runtimes. Additional connections currently support Alpaca API-key trading/Host/Receive; customer OAuth, candidate Webull and Discord Alerts remain restricted to the original connection. Keep the app foregrounded; this does not bypass iOS suspension.

Android: use **Select connection / account**; create another Host or Receive connection and save/verify its own account. The foreground service retains independently scoped workers for started routes. Selection recreates the editor and leaves other routes running. Start and Stop affect the selected route; Stop all stops every route. Shared customer OAuth and Alerts-only setup stay on the original connection; additional routes use Alpaca API keys. Android can still suspend/stop the service.

## Ownership and recovery

A broker/account/environment remains assigned to its original connection even after disconnect. Reuse that route to recover existing orders. Crier refuses assigning the same destination account/environment to another route; it does not silently merge holdings or allow one host's exits to sell another host's allocation. Existing legacy journal ownership is reserved in place, including when saved credentials are absent. No route deletion or automatic journal migration is offered. Preserve the entire profile before reinstalling or recovering.

One source event can execute independently in two different authorized accounts. Duplicate delivery within a route remains idempotent. A failure or disconnect in one route does not authorize a retry or change credentials in another. Existing broker orders remain active when Crier stops.

## Current limits

This implements concurrent routes using the existing Alpaca executor. Webull OpenAPI account authentication was separately verified on the owner's PC; Webull resource execution and customer Connect activation are not completed by this feature. Tradier remains a read-only observer. Unavailable brokers never redirect trades to an Alpaca account.

Several hosts sharing the same destination account, shared cash/quantity reservations, arbitrary cross-broker execution and multi-hop feedback-loop routing remain unfinished D.1 work. There is no public host directory, unsolicited invitation broadcast, independent strategy or automatic market fallback. This is not completion of all D.1 scope.

Automated tests use synthetic accounts/events and intercepted transports. Native signing, physical cross-network/lifecycle tests and independent broker-UI reconciliation remain external acceptance work.
