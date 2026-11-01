# iOS trading-workspace presentation

The current redesign follows familiar mobile brokerage conventions while identifying the app as Crier. It does not imply broker affiliation, introduce prices, or change account authorization or execution policy.

Implemented source:

- Dark compact workspace header, selected connection and paper/live environment.
- Existing bottom navigation and explicit Stop all control.
- Positions: held-symbol search, quantity/average and market-value columns, last-loaded snapshot guidance and empty-search state.
- Order ticket: separate instrument and order-detail sections, segmented stock/options and buy/close controls, contract-multiplier guidance, prominent Review action and retained final confirmation/account/client-ID evidence.
- Selected option summary: explicit call/put, strike, expiration and exact broker symbol, using discovered contract metadata. No invented bid/ask quotes.
- Chart controls: horizontally scrolling timeframe choices with minimum 44-point targets and spoken selection state. Expanded charts adapt to available height and remain scrollable on compact/landscape screens. Existing provider/delayed labels and unavailable-feed states remain.

The ticket remains Alpaca-backed. Discovering contracts, preparing a review, confirming an order and requesting cancellation still call the original workspace methods. No order is submitted by selecting a segment or editing a field. Inputs remain disabled during a pending review or busy operation. No new chart/quote feed or simulated performance value is introduced.

Native recovery, account-bank setup/pools/check/repair, chart controls, order ticket and positions presentation are implemented. Simulator UI screenshots and native unit tests have automated acceptance. Physical Dynamic Type/VoiceOver/lifecycle acceptance and Apple signing are owner-deferred; broker-specific full option-chain quote layouts and additional execution adapters remain outside this release. See the November 1 account-bank acceptance report.
