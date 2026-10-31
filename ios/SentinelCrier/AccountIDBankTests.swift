import XCTest
@testable import SentinelCrier

@MainActor final class AccountIDBankTests: XCTestCase {
    private func bank() throws -> AccountIDBank {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        return try AccountIDBank(file: folder.appendingPathComponent("bank.json"))
    }
    private let scope = BankScope(account: "synthetic", environment: .paper)
    private func setup(_ bank: AccountIDBank) throws {
        try bank.enable(scope, cash: 1000, equity: 1000, positions: [:])
        for route in ["alice", "dave"] { try bank.configure(scope, route: route, asset: "option", mode: "units", value: "10", fee: "0") }
    }
    private func reserve(_ bank: AccountIDBank, route: String = "alice", trade: String = "t", event: String = "e", sell: Bool = false, qty: Int = 3) throws -> String {
        let cid = AccountIDBank.clientID(scope, route: route, trade: trade, event: event, sell: sell, ordinal: 0)
        try bank.reserve(scope, route: route, trade: trade, event: event, cid: cid, symbol: "SPY270115C00600000", asset: "option", multiplier: 100, sell: sell, quantity: qty, price: "1", ordinal: 0, cash: 1000, equity: 1000)
        return cid
    }
    private func proof(_ cid: String, qty: Int = 3, filled: Int, sell: Bool = false, status: String) -> AlpacaOrder {
        AlpacaOrder(id: "broker-" + cid, client_order_id: cid, symbol: "SPY270115C00600000", status: status, qty: String(qty), limit_price: "1", filled_qty: String(filled), filled_avg_price: filled > 0 ? "1" : nil, side: sell ? "sell" : "buy")
    }
    func testReservationsPersistAndCompeteAcrossInstances() throws {
        let bank = try bank(); try setup(bank)
        _ = try reserve(bank, qty: 7)
        let restarted = try AccountIDBank(file: bank.file)
        XCTAssertThrowsError(try reserve(restarted, route: "dave", trade: "other", event: "other", qty: 4))
        XCTAssertEqual(try restarted.snapshot(scope).available, Decimal(300))
        XCTAssertThrowsError(try reserve(restarted, route: "dave", trade: "other", event: "e", qty: 1))
    }
    func testOwnedExitsPendingCancellationAndTombstones() throws {
        let bank = try bank(); try setup(bank)
        let cid = try reserve(bank)
        try bank.observe(scope, proof(cid, filled: 2, status: "pending_cancel"))
        XCTAssertThrowsError(try bank.retire(scope, route: "alice", trade: "t", reason: "cancel"))
        XCTAssertEqual(try bank.snapshot(scope).available, Decimal(700))
        try bank.observe(scope, proof(cid, filled: 2, status: "canceled"))
        XCTAssertEqual(try bank.snapshot(scope).available, Decimal(800))
        XCTAssertThrowsError(try reserve(bank, route: "dave", event: "exit", sell: true, qty: 1))
        let exit = try reserve(bank, event: "exit", sell: true, qty: 2)
        XCTAssertThrowsError(try reserve(bank, event: "exit-again", sell: true, qty: 1))
        try bank.observe(scope, proof(exit, qty: 2, filled: 2, sell: true, status: "filled"))
        XCTAssertTrue(try bank.snapshot(scope).lots.allSatisfy { !$0.active })
        XCTAssertThrowsError(try reserve(bank, event: "reopen"))
    }
    func testTimeoutNeverResubmitsAndMultiplierIsExact() throws {
        let bank = try bank(); try setup(bank)
        let cid = try reserve(bank)
        try bank.markDispatching(scope, cid: cid)
        XCTAssertThrowsError(try bank.markDispatching(scope, cid: cid))
        XCTAssertThrowsError(try bank.retire(scope, route: "alice", trade: "t", reason: "timeout"))
        XCTAssertThrowsError(try bank.reserve(scope, route: "alice", trade: "bad", event: "bad", cid: "bad", symbol: "SPY", asset: "option", multiplier: 10, sell: false, quantity: 1, price: "1", ordinal: 0, cash: 1000, equity: 1000))
    }
    func testInventoryMismatchBlocksAndNeverAdoptsExternalHoldings() throws {
        let bank = try bank(); try setup(bank)
        XCTAssertThrowsError(try bank.inventory(scope, positions: ["SPY": 1]))
        XCTAssertThrowsError(try reserve(bank))
        try bank.inventory(scope, positions: [:])
        _ = try reserve(bank)
    }
    func testLateFillReactivatesTombstoneAndPermanentlyBlocksEntries() throws {
        let bank = try bank(); try setup(bank)
        let cid = try reserve(bank)
        try bank.observe(scope, proof(cid, filled: 0, status: "canceled"))
        try bank.retire(scope, route: "alice", trade: "t", reason: "cancel")
        try bank.observe(scope, proof(cid, filled: 1, status: "canceled"))
        try bank.inventory(scope, positions: ["SPY270115C00600000": 1])
        XCTAssertEqual(try bank.snapshot(scope).blocked, "late_terminal_fill")
        XCTAssertEqual(try bank.snapshot(scope).lots.first?.active, true)
    }
}
