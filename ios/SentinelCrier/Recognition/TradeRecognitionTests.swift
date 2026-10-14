import XCTest

final class TradeRecognitionTests: XCTestCase {
    private let receipt = ["WEBULL", "FILLED", "SPY 2026-10-16 C 600", "BUY", "QTY: 4", "FILL PRICE: $1.25"]

    func testCompletedFill() {
        guard case .candidate(let trade) = BrokerScreenTemplate(name: "webull").recognize(lines: receipt) else {
            return XCTFail("Expected recognized candidate")
        }
        XCTAssertEqual(trade.symbol, "SPY")
        XCTAssertEqual(trade.quantity, 4)
        XCTAssertEqual(trade.price, Decimal(string: "1.25"))
    }

    func testPreviewRejected() {
        XCTAssertEqual(BrokerScreenTemplate(name: "webull").recognize(lines: receipt + ["ORDER PREVIEW"]), .noFill)
    }

    func testPartialFillHeld() {
        XCTAssertEqual(BrokerScreenTemplate(name: "webull").recognize(lines: receipt + ["PARTIALLY FILLED"]), .noFill)
    }

    func testUnknownBrokerHeld() {
        guard case .ambiguous = BrokerScreenTemplate(name: "unknown").recognize(lines: receipt) else {
            return XCTFail("Unknown broker must not be auto-accepted")
        }
    }

    func testMultipleContractsHeld() {
        guard case .ambiguous = BrokerScreenTemplate(name: "webull").recognize(lines: receipt + ["QQQ 2026-10-16 P 400"]) else {
            return XCTFail("Multiple contracts must be held")
        }
    }

    func testLocalDuplicateSuppression() {
        guard case .candidate(let trade) = BrokerScreenTemplate(name: "webull").recognize(lines: receipt) else {
            return XCTFail("Missing candidate")
        }
        let dedup = ScreenObservationDeduplicator()
        XCTAssertTrue(dedup.shouldAccept(trade))
        XCTAssertFalse(dedup.shouldAccept(trade))
    }

    func testNoOrderSubmission() {
        XCTAssertEqual(BrokerScreenTemplate(name: "webull").recognize(lines: receipt + ["ORDER SUBMITTED"]), .noFill)
    }
    func testUnfilledWebullOrderRejected() {
        XCTAssertEqual(BrokerScreenTemplate(name: "webull").recognize(lines: receipt + ["NOT FILLED"]), .noFill)
        XCTAssertEqual(BrokerScreenTemplate(name: "webull").recognize(lines: receipt + ["0 FILLED"]), .noFill)
    }

    func testDistinctIdenticalExecutionsAreNotSuppressedForever() {
        guard case .candidate(let trade) = BrokerScreenTemplate(name: "webull").recognize(lines: receipt) else {
            return XCTFail("Missing candidate")
        }
        let dedup = ScreenObservationDeduplicator()
        let start = Date(timeIntervalSince1970: 1_000)
        XCTAssertTrue(dedup.shouldAccept(trade, at: start))
        XCTAssertFalse(dedup.shouldAccept(trade, at: start.addingTimeInterval(1)))
        XCTAssertTrue(dedup.shouldAccept(trade, at: start.addingTimeInterval(4)))
    }

}
