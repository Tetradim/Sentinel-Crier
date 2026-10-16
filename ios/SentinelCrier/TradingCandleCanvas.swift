import SwiftUI

/// High-performance native candle drawing. Does not request data or execute
/// orders. A bounded visible window keeps redraw cost predictable.
struct TradingCandleCanvas: View {
    let candles: [ChartCandle]
    let emaPeriods: [Int]
    let showVolume: Bool

    @State private var visibleCount = 80
    @State private var cursorFraction: CGFloat?
    private func emaColor(_ period: Int) -> Color {
        switch period {
        case 9: return .yellow
        case 20: return .cyan
        case 50: return .purple
        default: return .orange
        }
    }

    var body: some View {
        GeometryReader { geometry in
            let count = max(1, min(candles.count, visibleCount))
            let start = max(0, candles.count - count)
            let visible = Array(candles.dropFirst(start))
            let ema = emaPeriods.map { ChartIndicatorMath.ema(candles, period: $0) }
            let high = visible.map(\.high).max() ?? 1
            let low = visible.map(\.low).min() ?? 0
            let range = max(0.01, high - low)
            let upper = high + range * 0.10
            let lower = max(0, low - range * 0.10)
            let chartHeight = geometry.size.height * (showVolume ? 0.76 : 0.96)
            let plotHeight = max(1, chartHeight - 15)
            let slot = geometry.size.width / CGFloat(max(1, visible.count))
            let vmax = max(1, visible.map(\.volume).max() ?? 1)
            let scaleY: (Double) -> CGFloat = { price in
                CGFloat((upper - price) / max(0.00001, upper - lower)) * plotHeight + 6
            }

            ZStack(alignment: .topLeading) {
                Canvas(opaque: false) { context, size in
                    guard !visible.isEmpty, size.width > 0, size.height > 0 else { return }
                    for division in 1...4 {
                        let y = CGFloat(division) * plotHeight / 5 + 6
                        var grid = Path()
                        grid.move(to: CGPoint(x: 0, y: y))
                        grid.addLine(to: CGPoint(x: size.width, y: y))
                        context.stroke(grid, with: .color(.gray.opacity(0.18)), lineWidth: 0.5)
                    }
                    for (index, bar) in visible.enumerated() {
                        let x = (CGFloat(index) + 0.5) * slot
                        let rising = bar.close >= bar.open
                        let color: Color = rising ? .green : .red
                        var wick = Path()
                        wick.move(to: CGPoint(x: x, y: scaleY(bar.high)))
                        wick.addLine(to: CGPoint(x: x, y: scaleY(bar.low)))
                        context.stroke(wick, with: .color(color), lineWidth: 1)
                        let top = min(scaleY(bar.open), scaleY(bar.close))
                        let bottom = max(scaleY(bar.open), scaleY(bar.close))
                        let body = Path(roundedRect: CGRect(
                            x: x - max(1, (slot - 2) / 2), y: top,
                            width: max(2, slot - 2), height: max(1.5, bottom - top)),
                            cornerRadius: 0.5)
                        context.fill(body, with: .color(color))
                        if showVolume {
                            let volumeMaxHeight = max(1, size.height - chartHeight - 9)
                            let barHeight = CGFloat(bar.volume / vmax) * volumeMaxHeight
                            let volume = Path(CGRect(
                                x: x - max(1, (slot - 2) / 2),
                                y: size.height - barHeight,
                                width: max(2, slot - 2), height: barHeight))
                            context.fill(volume, with: .color(color.opacity(0.42)))
                        }
                    }
                    for (index, values) in ema.enumerated() {
                        var path = Path()
                        var started = false
                        for position in start..<candles.count {
                            guard let value = values[position], value.isFinite else {
                                started = false
                                continue
                            }
                            let point = CGPoint(
                                x: (CGFloat(position - start) + 0.5) * slot,
                                y: scaleY(value))
                            if !started {
                                path.move(to: point)
                                started = true
                            } else {
                                path.addLine(to: point)
                            }
                        }
                        context.stroke(path, with: .color(emaColor(emaPeriods[index])), lineWidth: 1.7)
                    }
                    if let cursorFraction {
                        let x = max(0, min(size.width, cursorFraction * size.width))
                        var crosshair = Path()
                        crosshair.move(to: CGPoint(x: x, y: 0))
                        crosshair.addLine(to: CGPoint(x: x, y: chartHeight))
                        context.stroke(crosshair, with: .color(.white.opacity(0.6)),
                                       style: StrokeStyle(lineWidth: 0.8, dash: [4, 3]))
                    }
                }

                if let cursorFraction, !visible.isEmpty {
                    let index = min(visible.count - 1,
                                    max(0, Int(cursorFraction * CGFloat(visible.count))))
                    let item = visible[index]
                    VStack(alignment: .leading, spacing: 3) {
                        Text(item.timestamp, style: .date)
                        Text("O \(item.open.formatted(.number.precision(.fractionLength(2))))   H \(item.high.formatted(.number.precision(.fractionLength(2))))")
                        Text("L \(item.low.formatted(.number.precision(.fractionLength(2))))   C \(item.close.formatted(.number.precision(.fractionLength(2))))")
                    }
                    .font(.system(size: 10, design: .monospaced))
                    .padding(6)
                    .background(.black.opacity(0.83), in: RoundedRectangle(cornerRadius: 6))
                    .padding(6)
                }
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { value in
                    cursorFraction = max(0, min(1, value.location.x / max(1, geometry.size.width)))
                }
                .onEnded { _ in cursorFraction = nil })
            .simultaneousGesture(MagnificationGesture()
                .onEnded { factor in
                    guard factor.isFinite, factor > 0 else { return }
                    visibleCount = min(400, max(15,
                        Int(CGFloat(visibleCount) / factor)))
                })
            .accessibilityLabel("Live candlestick chart with \(candles.count) candles")
            .accessibilityHint("Drag to inspect price candles; pinch to zoom")
        }
    }
}
