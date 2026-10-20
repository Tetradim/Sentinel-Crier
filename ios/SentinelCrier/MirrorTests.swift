import XCTest
@testable import SentinelCrier

final class MirrorTests: XCTestCase {
    func testPairingRequiresHTTPSAndNoEmbeddedCredentials() throws {
        XCTAssertThrowsError(try MirrorPairing.decode(#"{"url":"http://example.com","token":"abcdefghijklmnopqrstuvwxyz1234567890","environment":"paper"}"#))
        XCTAssertThrowsError(try MirrorPairing.decode(#"{"url":"https://user:secret@example.com","token":"abcdefghijklmnopqrstuvwxyz1234567890","environment":"paper"}"#))
        XCTAssertNoThrow(try MirrorPairing.decode(#"{"url":"https://example.com","token":"abcdefghijklmnopqrstuvwxyz1234567890","environment":"paper"}"#))
    }
    func testExactOptionAndPartialQuantity() throws {
        let fill = AlpacaFill(id: "fill-1", activity_type: "FILL", order_id: "order-1", symbol: "SPY261212C00750000", side: "buy", qty: "2", price: "1.25", transaction_time: "2026-10-20T15:00:00Z")
        let event = try MirrorFillEvent(fill: fill, environment: .paper, accountID: "source", intent: "buy_to_open")
        XCTAssertEqual(event.quantity, 2)
        XCTAssertEqual(event.symbol, "SPY261212C00750000")
        XCTAssertEqual(event.price, "1.25")
        XCTAssertNotEqual(event.event_id, try MirrorFillEvent(fill: fill, environment: .paper, accountID: "other", intent: "buy_to_open").event_id)
        XCTAssertThrowsError(try MirrorFillEvent(fill: fill, environment: .paper, accountID: "source", intent: "sell_to_open"))
    }
}
