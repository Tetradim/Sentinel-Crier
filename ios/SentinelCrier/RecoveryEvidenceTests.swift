import XCTest
@testable import SentinelCrier

final class RecoveryEvidenceTests: XCTestCase {
    func testEvidenceRejectsWrongIdentityAndFractionalFill() throws {
        let ticket = AlpacaTicket(id: "client", environment: .paper, accountID: "account", symbol: "SPY", quantity: 2, limitPrice: 10, side: "buy", positionIntent: nil, multiplier: 1, reviewedAt: Date())
        func order(_ client: String, _ filled: String) throws -> AlpacaOrder {
            try JSONDecoder().decode(AlpacaOrder.self, from: JSONSerialization.data(withJSONObject: ["id":"broker","client_order_id":client,"symbol":"SPY","status":"new","qty":"2","limit_price":"10","filled_qty":filled,"side":"buy"]))
        }
        XCTAssertNoThrow(try RecoveryOrderEvidence.validate(order("client", "1"), ticket: ticket))
        XCTAssertThrowsError(try RecoveryOrderEvidence.validate(order("other", "1"), ticket: ticket))
        XCTAssertThrowsError(try RecoveryOrderEvidence.validate(order("client", "0.5"), ticket: ticket))
        XCTAssertThrowsError(try RecoveryOrderEvidence.validate(order("client", "3"), ticket: ticket))
    }
}
