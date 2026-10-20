import XCTest
@testable import SentinelCrier

final class MirrorTests: XCTestCase {
    func testMirroredAndMultilegOrdersCannotBeForwarded() throws {
        let fill = AlpacaFill(id: "f1", activity_type: "FILL", order_id: "o1", symbol: "SPY261212C00750000", side: "buy", qty: "1", price: "1", transaction_time: "2026-10-20T15:00:00Z")
        var order = AlpacaOrder(id: "o1", client_order_id: "customer-order", symbol: fill.symbol, status: "filled", qty: "1", limit_price: "1", filled_qty: "1", filled_avg_price: "1", side: "buy", position_intent: "buy_to_open", order_class: "simple")
        XCTAssertEqual(try MirrorFillEvent.confirmedIntent(order: order, fill: fill), "buy_to_open")
        order.order_class = "mleg"
        XCTAssertThrowsError(try MirrorFillEvent.confirmedIntent(order: order, fill: fill))
        order.order_class = "simple"
        order = AlpacaOrder(id: "o1", client_order_id: "crier-m-copied", symbol: fill.symbol, status: "filled", qty: "1", limit_price: "1", filled_qty: "1", filled_avg_price: "1", side: "buy", position_intent: "buy_to_open", order_class: "simple")
        XCTAssertThrowsError(try MirrorFillEvent.confirmedIntent(order: order, fill: fill))
    }
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
