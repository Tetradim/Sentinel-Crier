import XCTest
@testable import SentinelCrier

final class TradingChartTests: XCTestCase {
    private func bars(_ values: [Double]) -> [ChartCandle] {
        let start = Date(timeIntervalSince1970: 1_780_000_000)
        return values.enumerated().map { index, close in
            ChartCandle(timestamp: start.addingTimeInterval(Double(index) * 60),
                        open: close, high: close + 1, low: close - 1,
                        close: close, volume: 100)
        }
    }

    func testEMARequiresHistoricalWarmup() {
        let candles = bars([10, 12, 14, 16])
        let series = ChartIndicatorMath.ema(candles, period: 3)
        XCTAssertNil(series[0])
        XCTAssertNil(series[1])
        XCTAssertEqual(series[2]!, 12, accuracy: 0.00001)
        XCTAssertEqual(series[3]!, 14, accuracy: 0.00001)
    }

    func testEMAAbsentWhenInsufficientBars() {
        let series = ChartIndicatorMath.ema(bars([10, 12]), period: 9)
        XCTAssertEqual(series.count, 2)
        XCTAssertTrue(series.allSatisfy { $0 == nil })
    }

    func testNoIndicatorsIsAnAllowedPreference() {
        var settings = ChartIndicatorSettings(periods: [9, 20])
        settings.setPeriod(9, enabled: false)
        settings.setPeriod(20, enabled: false)
        XCTAssertEqual(settings.periods, [])
    }

    func testSnapshotRejectsDuplicateTimestamps() {
        let first = bars([10])[0]
        let snapshot = ChartSnapshot(instrument: .stock(symbol: "SPY"),
                                     timeframe: .oneMinute,
                                     candles: [first, first],
                                     receivedAt: Date(), source: "Licensed feed",
                                     isDelayed: false)
        XCTAssertThrowsError(try snapshot.validate())
    }

    func testRejectsInvalidCandlesRatherThanDrawingFakeData() {
        let invalid = ChartCandle(timestamp: Date(), open: 10, high: 9,
                                  low: 8, close: 10, volume: 4)
        let snapshot = ChartSnapshot(instrument: .stock(symbol: "SPY"),
                                     timeframe: .oneMinute, candles: [invalid],
                                     receivedAt: Date(), source: "Licensed feed",
                                     isDelayed: false)
        XCTAssertThrowsError(try snapshot.validate())
    }

    func testUnderlyingAndOCCOptionRemainDistinct() {
        XCTAssertNotEqual(ChartInstrument.stock(symbol: "SPY"),
            ChartInstrument.option(underlying: "SPY",
                                   contractId: "SPY261016C00750000"))
    }

    func testIndicatorPeriodsRemainBounded() {
        var settings = ChartIndicatorSettings(periods: [9])
        settings.setPeriod(300, enabled: true)
        XCTAssertEqual(settings.periods, [9])
    }
}
