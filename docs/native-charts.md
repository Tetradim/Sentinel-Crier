# Stock and option chart windows

The native SwiftUI Markets screen has a compact chart workspace and a full-screen
view. Charts use native Canvas rendering (not a remote web-based chart widget)
with touch crosshair, pinch zoom, bounded redraw window, volume, and EMA lines.

## Chart instrument and data integrity

- Stocks are identified by their underlying ticker.
- Option contracts are separate instruments identified by exact contract IDs,
  not by stock price or a theoretical premium inferred from the underlying.
- `LiveChartFeed` is the contract for future approved/licensed OHLCV sources.
  The returned `ChartSnapshot` must match the selected instrument and interval,
  identify its source, and include a received-at timestamp and delay indicator.
- Bars must be chronologically increasing, numeric, positive where relevant,
  internally consistent OHLC values, and nonnegative volume.
- A missing feed, missing history, delayed entitlement, or unsupported option
  contract must be surfaced as **unavailable**, not fictional chart data.
- The chart module has no order-submission capability, no synthetic
  price-preview mode, and no connection to the old OCR workflow.

## Controls in the first release

- Stock / Option switch
- Timeframes: 1m, 5m, 15m, 1h, 1D
- Candlestick chart, volume, price inspection by dragging, pinch zoom
- EMA 5/10/20 visible by default; each can be independently disabled
- EMA overlays can all be disabled; no indicator may be forced on
- Full-screen chart window
- Preferences persisted locally

The customer explicitly selected EMA 5, EMA 10 and EMA 20 as default overlays.
The chart remains configurable and supports a clean view without overlays.

## Calculations

EMA uses an initial SMA seed after `period` bars, then the standard
`alpha=2/(period+1)` recurrence. Warm-up points are omitted instead of
drawing a line from insufficient history. This intentionally differs from
Sentinel Edge's first-close EMA initialization. The full history is used
before slicing the visible chart window.

## Next integration gate

- License live stock and per-contract option candle redistribution.
- Supply appropriately entitled historical and streaming OHLCV.
- Resolve option contract identity from the live option chain rather than
  relying on manual symbol entry.
- Update bars incrementally without erasing history or mismatching the active
  interval.
- Test on actual iPhone hardware for rendering latency, memory pressure,
  VoiceOver usability, history sizes and long-session stability.
- If native Canvas proves insufficient for advanced drawing tools, evaluate
  TradingView Lightweight Charts as a separately vetted chart-only renderer,
  taking account of attribution/license and native iOS compatibility.
- Never let chart state bypass the broker-confirmed order preview or live-order
  authorization flow.


## TradingView hosted data — display only, approval gated

Product choice (October 2026): use TradingView **hosted chart widgets** as
the preferred source of **displayed chart visuals** for IWM once applicable
commercial embedded-app permission and exchange data licensing are confirmed.

This is intentionally **not** the same as TradingView Lightweight Charts,
which provides rendering only and contains no market data:
https://tradingview.github.io/lightweight-charts/docs/product-comparison

The TradingView-hosted Advanced Chart widget can itself display
TradingView-sourced prices, but these are licensed for display, **not** an API
feed for Crier. TradingView specifically restricts non-display and trading/
order-verification uses of its market data:
https://www.tradingview.com/policies/
https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/

`TradingViewHostedChart.swift` contains a WebKit wrapper, restricted to a
verified ETF symbol mapping (IWM), with the official TradingView attribution
visible. Its `commercialEmbedApproved` flag stays **false** pending written
approval of the particular mobile commercial use, market coverage and widget
integration. The embedded widget is never wired into order submission,
execution price checks or automated indicator signals.

The user-approved native EMA 5/10/20 renderer remains available for actual
licensed candle data. TradingView's hosted widget has its own studies/UI and
cannot be assumed to inherit Crier's EMA settings; verify three period-specific
EMAs and display permissions before activating the widget. TradingView does
not guarantee charting for all individual OCC option contracts; those remain
unavailable until an independently licensed per-contract data feed is approved.

## Future architecture preserved separately (not active)

`crier/future_unified_market_feed.py` is intentionally isolated and labeled
**FUTURE / NOT ACTIVE**. It documents and implements only pure eligibility
selection for possibly combining authorized provider subscriptions into one
Crier *delivery* stream. It does not connect to providers, aggregate or average
prices, extract TradingView data, or participate in the active app/API.

The unified market feed is postponed unless the product direction changes.
