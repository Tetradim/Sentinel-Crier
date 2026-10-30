# Shared-account host IDs (Windows / Alpaca)

Current main implements an opt-in account bank for several host connections using the same Alpaca destination account on one Windows installation. iPhone and Android apps can provide host instructions through their existing supported transport. Their own shared-account receiver guards remain in place. This does not add a Webull or Tradier execution adapter, or coordinate two separate receiver installations trading the same account.

## Setup

1. Connect the original Windows trade connection to its Alpaca account and pairing. Start with paper trading.
2. Select **Account ID bank → Set up account ID bank**. This disconnects and drains every connection. Older Crier orders must have authoritative terminal outcomes and older Crier lots must be closed. Unresolved or partially filled legacy holdings prevent setup; recover them through their original connection first.
3. In the bank window, save a **stock** and/or **option** pool for this connection. New pools default to zero. Choose aggregate units (shares/contracts), dollars, or percentage of the destination account's current equity. Set a conservative per-order fee reserve. These are reusable exposure ceilings; the existing per-entry sizing settings still determine the requested quantity. Equity percentage is a pool, not a new per-entry percentage-sizing mode.
4. Reconnect the original connection. Add a different connection for each additional host, connect it to the same account/environment and its own private pairing, and configure that connection's pools.
5. Use exact or bounded **limit** pricing. Inspect the existing price, quantity, freshness and exit controls, then explicitly enable orders for each route. Bank setup never enables them.
6. Open **Account ID bank** to inspect active IDs and recent archived IDs. Selecting another connection changes which host's pool settings you edit; the account's ID list contains all its hosts. Refresh reads local evidence and does not submit an order.

## Ownership and retirement

Each source trade receives a persistent numeric display ID. Its immutable owner includes broker, actual destination account, paper/live environment, connection and source-trade identity. Every child order has a separate deterministic client-order ID. IDs are never reused. An identical source event delivered through two connections cannot execute twice in the same destination account; authorized execution in different accounts remains independent.

Example: Alice owns three SPY calls and Dave owns five identical calls. Alice's exit can reserve and sell only her three. It cannot borrow Dave's five. Exit reservations also prevent two instructions from selling the same owned units simultaneously.

Sold, invalidated or canceled IDs leave the **active** bank only after confirmed zero holdings and no unresolved orders. A canceled order that filled two of five contracts keeps its two contracts and its ID. Timeouts and pending cancellations retain their reservations. Archive records, source identities, broker references and audit evidence stay in the private SQLite bank to reject replay and diagnose corrections. There is no destructive clear-ID button.

## Funds, reconciliation and recovery

Cash reservations are committed before the broker POST. SQLite transactions serialize competing allocations, and an account-wide process/file lock covers reconciliation and dispatch. A timeout does not authorize a repeated POST. Definite pre-submission refusals release reservations; ambiguous outcomes retain them across restart.

Admissions use fresh pinned USD account evidence, verified standard contract multipliers (100 for supported options; 1 for stocks), whole units and a finite final limit. Available cash is bounded by cash and broker-reported non-margin/options buying power, using the documented [Alpaca account fields](https://alpaca.markets/sdks/python/api_reference/trading/models.html#alpaca.trading.models.TradeAccount). Broker-held reservations are not added back. Fees are reserved once, losses reduce the owning host's monetary capacity, and fixed-dollar pools do not automatically grow with profits. Whole-account cash can refresh only when every bank ID is flat and reconciled.

Setup records external holdings separately; it never assigns them to a host. Subsequent position discrepancies block new entries rather than silently relabeling units, even when all Crier lots appear flat. A later authoritative inventory matching the unchanged ledger can clear an inventory-only discrepancy (for example, when broker endpoints briefly lag each other). It cannot clear contradictory or late-fill evidence blocks. Inspect the broker and retain the complete profile; restarting or repeating setup does not reset the ledger or invent ownership.

Accounts containing short/fractional or unsupported asset positions fail the managed inventory check. Limit-price execution, declared fees and external/manual account changes can still produce discrepancies requiring investigation. The bank does not guarantee equal fill prices or profitable copying.

Private updater snapshots include the bank and every route's original journals. Startup stays disconnected with entries paused. Support logs remain route-specific; the bank window provides account-level ownership/blocked-state evidence. Never post raw profile backups publicly.

## Research and verification scope

The design uses Alpaca's [unique client-order IDs and order states](https://docs.alpaca.markets/us/reference/postorder), [cumulative trade updates](https://docs.alpaca.markets/us/docs/websocket-streaming), and [order-management guidance](https://docs.alpaca.markets/us/docs/working-with-orders). Broker confirmations remain authoritative; timeout alone is not a reason to resubmit. [IBKR allocation orders](https://www.ibkrguides.com/advisorportal/ug/allocation-orders.htm) and [FIX post-trade allocation practices](https://www.fixtrading.org/wp-content/uploads/download-manager-files/PostTradeViaFIX_Recommended%20Practices_EquitySwaps.pdf) informed the separation between allocation identity, order identity and retained lifecycle evidence. This is Crier's internal ownership ledger, not a claim that Alpaca provides broker-native host subaccounts.

Synthetic tests exercise real Crier engines with two hosts on one account, concurrent cash competition, exact option identity, partial cancellations, owned exits, late evidence, stale funds, restart, migration refusal and UI pool controls. No real broker orders or Discord posts are part of these tests. The screenshot's +3%/−2% autonomous strategy triggers are not introduced here: Crier continues to execute authorized host instructions through its existing controls. Native shared-account receiver parity, physical broker-UI reconciliation and installer acceptance remain separate work. This source change is not yet a newly published installer.
