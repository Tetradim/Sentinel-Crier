import Foundation

/// Chart candles are authoritative market-data observations, never order fills.
/// No synthetic, local-preview, or paper-trading feeds are supported.
enum ChartTimeframe: String, Codable, CaseIterable, Identifiable {
    case oneMinute = "1m"
    case fiveMinutes = "5m"
    case fifteenMinutes = "15m"
    case oneHour = "1h"
    case oneDay = "1D"

    var id: String { rawValue }
}

enum ChartInstrument: Hashable {
    case stock(symbol: String)
    case option(underlying: String, contractId: String)

    var title: String {
        switch self {
        case .stock(let symbol): return symbol
        case .option(_, let contractId): return contractId
        }
    }
}

struct ChartCandle: Codable, Hashable {
    let timestamp: Date
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let volume: Double

    var isValid: Bool {
        let values = [open, high, low, close, volume]
        return values.allSatisfy(\.isFinite)
            && low >= 0 && open > 0 && close > 0 && high > 0
            && high >= max(open, close, low)
            && low <= min(open, close, high)
            && volume >= 0
    }
}

struct ChartSnapshot {
    let instrument: ChartInstrument
    let timeframe: ChartTimeframe
    let candles: [ChartCandle]
    let receivedAt: Date
    let source: String
    let isDelayed: Bool

    /// Bars are strictly ascending and from one actual financial instrument.
    /// Rejected records must not be patched using fictional prices.
    func validate() throws {
        guard !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              receivedAt.isFiniteForChart else { throw ChartDataError.invalidPayload }
        var previous: Date?
        for bar in candles {
            guard bar.isValid, bar.timestamp.isFiniteForChart,
                  previous == nil || bar.timestamp > previous! else {
                throw ChartDataError.invalidPayload
            }
            previous = bar.timestamp
        }
    }
}

private extension Date {
    var isFiniteForChart: Bool { timeIntervalSince1970.isFinite }
}

enum ChartDataError: Error {
    case unauthorized
    case unavailable
    case invalidPayload
    case insufficientHistory
}

/// A data source must provide separately licensed underlying and OCC-contract
/// candles, with timestamped source/delay metadata. It must never infer option
/// prices from a stock's chart.
protocol LiveChartFeed {
    func load(instrument: ChartInstrument, timeframe: ChartTimeframe,
              limit: Int) async throws -> ChartSnapshot
}

enum ChartIndicatorMath {
    /// Seeds the EMA with a simple average of the first `period` closes.
    /// Returns nil during warmup instead of visually implying prior history.
    static func ema(_ candles: [ChartCandle], period: Int) -> [Double?] {
        guard period >= 2 && period <= 200 else {
            return Array(repeating: nil, count: candles.count)
        }
        var values = Array<Double?>(repeating: nil, count: candles.count)
        guard candles.count >= period else { return values }
        let closes = candles.map(\.close)
        var ema = closes.prefix(period).reduce(0, +) / Double(period)
        values[period - 1] = ema
        let alpha = 2.0 / (Double(period) + 1.0)
        if candles.count > period {
            for i in period..<candles.count {
                ema = (closes[i] - ema) * alpha + ema
                values[i] = ema
            }
        }
        return values
    }
}

/// Customer-approved chart defaults; each overlay remains optional.
struct ChartIndicatorSettings {
    var periods: [Int] = [5, 10, 20]
    var showVolume: Bool = true

    mutating func setPeriod(_ period: Int, enabled: Bool) {
        guard (2...200).contains(period) else { return }
        periods.removeAll(where: { $0 == period })
        if enabled { periods.append(period) }
        periods.sort()
    }
}
