import XCTest
@testable import SentinelCrier
final class IntentTests: XCTestCase {
    func testQueuedInvalidationSuppressesOlderEntry() throws {
        var state = IntentState()
        let entry = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        var cancel = entry; cancel.sequence = 2; cancel.action = "cancel"; cancel.event_id = UUID().uuidString.lowercased()
        state.outgoing = [entry, cancel]; state.discardSupersededEntries()
        XCTAssertEqual(state.outgoing, [cancel])
    }
    func testExitTotalsHandleDecimalBrokerQuantities() throws {
        var trade = IntentTrade()
        let order = AlpacaOrder(id: "broker", client_order_id: "client", symbol: "AAPL", status: "filled", qty: "2.0", limit_price: "1", filled_qty: "2.0", filled_avg_price: "1", side: "sell")
        trade.mutations = [IntentMutation(clientID: "client", eventID: "event", sell: true, quantity: 2, order: order)]
        XCTAssertEqual(trade.sold(for: "event"), 2)
    }
    func testPausedReceiptRemainsSkipped() throws {
        var trade = IntentTrade()
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 2, price: "10")
        try trade.accept(event, paused: true)
        let saved = try JSONDecoder().decode(IntentTrade.self, from: JSONEncoder().encode(trade))
        XCTAssertEqual(saved.entrySkipped, true)
    }
    func testSubmitResponseIdentityIsChecked() throws {
        let mutation = IntentMutation(clientID: "client", eventID: "event", sell: false, quantity: 2)
        let wrong = AlpacaOrder(id: "broker", client_order_id: "other", symbol: "AAPL", status: "filled", qty: "2", limit_price: "1", filled_qty: "2", filled_avg_price: "1", side: "buy")
        XCTAssertThrowsError(try mutation.validate(wrong, symbol: "AAPL"))
    }
    func testBoundsRoundConservatively() throws {
        var p = IntentPreferences(); p.mode = "bounded_limit"
        XCTAssertEqual(try p.price("1.23", sell: false), "1.24")
        XCTAssertEqual(try p.price("1.23", sell: true), "1.22")
    }
    func testCancelPermanentlyInvalidatesEntry() throws {
        var trade = IntentTrade()
        let enter = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        var cancel = enter; cancel.sequence = 3; cancel.action = "cancel"; cancel.event_id = UUID().uuidString.lowercased()
        try trade.accept(cancel); try trade.accept(enter)
        XCTAssertTrue(trade.invalidated)
        XCTAssertEqual(trade.desired?.sequence, 3)
    }
    func testExitTombstoneSurvivesDiskRoundTrip() throws {
        var trade = IntentTrade()
        let exit = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 5, action: "exit", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 2, price: "10")
        try trade.accept(exit)
        let saved = try JSONDecoder().decode(IntentTrade.self, from: JSONEncoder().encode(trade))
        XCTAssertTrue(saved.invalidated)
        XCTAssertEqual(saved.desired, exit)
    }
    func testUnknownMutationSurvivesDiskRoundTrip() throws {
        var state = IntentState()
        var trade = IntentTrade()
        trade.mutations = [IntentMutation(clientID: "ci-test", eventID: "event", sell: false, quantity: 3)]
        state.trades["trade"] = trade
        let restored = try JSONDecoder().decode(IntentState.self, from: JSONEncoder().encode(state))
        XCTAssertNil(restored.trades["trade"]!.mutations[0].order)
        XCTAssertEqual(restored.trades["trade"]!.mutations[0].clientID, "ci-test")
        XCTAssertEqual(restored.trades["trade"]!.owned, 0)
    }
    func testHighestRevisionAndIdentityGuard() throws {
        var trade = IntentTrade()
        var e = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 3, action: "replace", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 2, price: "10")
        try trade.accept(e)
        e.sequence = 2; e.event_id = UUID().uuidString.lowercased()
        try trade.accept(e)
        XCTAssertEqual(trade.desired?.sequence, 3)
        e.symbol = "MSFT"
        XCTAssertThrowsError(try trade.accept(e))
    }
    func testExplicitMarketAndInvalidPreferences() throws {
        var p = IntentPreferences()
        XCTAssertEqual(try p.price("10", sell: false), "10")
        p.mode = "market"
        XCTAssertNil(try p.price("10", sell: false))
        p.maxAgeSeconds = 31
        XCTAssertThrowsError(try p.price("10", sell: false))
    }
    func testRejectMalformedAndExpired() throws {
        var e = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        e.quantity = 1001
        XCTAssertThrowsError(try e.validate())
    }
}
