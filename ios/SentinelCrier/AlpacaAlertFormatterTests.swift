import XCTest
@testable import SentinelCrier

final class AlpacaAlertFormatterTests: XCTestCase {
    func testOCCPreservesYearAndFractionalStrike() {
        XCTAssertEqual(AlpacaAlertFormatter.instrument("SPY261120C00600500"), "SPY $600.5C · 11-20-2026")
        XCTAssertEqual(AlpacaAlertFormatter.instrument("AAPL"), "AAPL")
    }

    func testEveryFormatPreservesPaperPriceAndTimeWithoutAccountIDs() throws {
        let fill = AlpacaFill(id: "private-execution", activity_type: "FILL", order_id: "private-order", symbol: "SPY261120P00600000", side: "sell", qty: "2", price: "1.23", transaction_time: "2026-10-19T14:00:00Z")
        let entry = AlpacaJournal.Delivery(id: "private-dedup", environment: .paper, accountID: "private-account", fill: fill, state: "pending", messageID: nil, retryAfter: nil)
        for style in ["plain", "homebrew", "card"] {
            let payload = AlpacaAlertFormatter.payload(entry, style: style)
            let raw = String(data: try JSONSerialization.data(withJSONObject: payload), encoding: .utf8)!
            XCTAssertTrue(raw.contains("PAPER"))
            XCTAssertTrue(raw.contains("1.23"))
            XCTAssertTrue(raw.contains("2026-10-19T14:00:00Z"))
            XCTAssertFalse(raw.contains("private-account"))
            XCTAssertFalse(raw.contains("private-execution"))
            XCTAssertFalse(raw.contains("private-order"))
            XCTAssertFalse(raw.contains("CLOSED"))
            let mentions = try XCTUnwrap(payload["allowed_mentions"] as? [String: [String]])
            XCTAssertEqual(mentions["parse"], [])
        }
    }
}
