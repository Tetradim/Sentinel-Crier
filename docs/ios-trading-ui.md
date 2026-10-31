# iOS trading-workspace presentation

The current redesign follows familiar mobile brokerage conventions while identifying the app as Crier. It does not imply broker affiliation, introduce prices, or change account authorization or execution policy.

Implemented source:

- Dark compact workspace header, selected connection and paper/live environment.
- Existing bottom navigation and explicit Stop all control.
- Positions: held-symbol search, quantity/average and market-value columns, last-loaded snapshot guidance and empty-search state.
- Order ticket: separate instrument and order-detail sections, segmented stock/options and buy/close controls, contract-multiplier guidance, prominent Review action and retained final confirmation/account/client-ID evidence.

The ticket remains Alpaca-backed. Discovering contracts, preparing a review, confirming an order and requesting cancellation still call the original workspace methods. No order is submitted by selecting a segment or editing a field. Inputs remain disabled during a pending review or busy operation. No new chart/quote feed or simulated performance value is introduced.

Remaining: simulator screenshots on compact and large phones, Dynamic Type/VoiceOver and landscape acceptance, detailed chart and option-chain layout, mobile recovery integration, and a complete app-wide visual consistency pass. CI compilation is necessary but is not visual acceptance. Apple signing and customer-device acceptance remain separate distribution requirements.
