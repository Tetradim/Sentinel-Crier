# Execution diagnostics

The Windows app has a **Diagnostics** tab. Connect to the saved account, select a
trade in **Trading & activity**, then select **Load selected trade**. Refresh with
the same button as new broker evidence arrives. Select buy or sell to choose the
quote comparison side. Export JSON or CSV using the corresponding button.

The report combines the current Python execution engine's recorded events with
local sender/receiver relay milestones for that trade. Event identifiers are
included in both formats. Broker reconciliation can include cumulative filled
quantity, average fill price, and broker timestamps. Diagnostic writes are
best-effort: this is troubleshooting evidence, not a guaranteed audit ledger.

JSON contains the timeline, supplied quote observations, and premium comparison.
CSV contains one row per event with its details retained as JSON. Spreadsheet
formula/control prefixes in text columns are escaped. Neither export includes
broker credentials or pairing tokens. Files contain trade information; choose
their destination accordingly.

## Current boundaries

- These reports cover the local Python/Windows device. They do not automatically
  collect another device's journal or add diagnostics screens to iOS/Android.
- `IntentDevice.trade_report()` and `export_trade()` include local transport and
  engine evidence. `IntentEngine` equivalents contain engine evidence only.
- Real quotes can be supplied through `IntentEngine.record_quote()`. Automatic
  market-data capture is not wired in. Missing quotes are reported as unavailable;
  order limits are never substituted for observed premiums.
- Cross-device latency remains unavailable. Comparing unsynchronized wall clocks
  or monotonic counters from different devices would produce misleading numbers.
- The UI requires a connection and an explicit reload. Export reads a fresh local
  report, so it may include events recorded since the last screen refresh.
