import XCTest
@testable import SentinelCrier

@MainActor final class NativeInvariantsTests: XCTestCase {
    private struct Fixture: Decodable {
        let version: Int
        let clock: [ClockCase]
        let bank: [BankCase]
    }
    private struct ClockCase: Decodable {
        let id: String
        let anchor_wall_ms: Double
        let anchor_mono_ms: Double
        let samples: [Sample]
        struct Sample: Decodable {
            let wall_ms: Double
            let mono_ms: Double
            let effective_ms: Double?
            let uncertain: Bool?
        }
    }
    private struct BankCase: Decodable {
        let id: String
        let steps: [Step]
        struct Step: Decodable {
            let op: String
            let alias: String?
            let account: String?
            let route: String?
            let trade: String?
            let event: String?
            let quantity: Int?
            let sell: Bool?
            let refused: Bool?
            let filled: Int?
            let expected_filled: Int?
            let status: String?
            let positions: [String: Int]?
            let available: String?
            let active: Int?
            let orders: Int?
            let blocked: Bool?
        }
    }
    private func fixture() throws -> Fixture {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "native-invariants", withExtension: "json"))
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
        XCTAssertEqual(fixture.version, 1)
        return fixture
    }
    func testSharedClock() throws {
        for item in try fixture().clock {
            var wall = item.anchor_wall_ms / 1000
            var mono = item.anchor_mono_ms / 1000
            let clock = EntryClock(wall: { Date(timeIntervalSince1970: wall) }, mono: { mono })
            for (index, sample) in item.samples.enumerated() {
                wall = sample.wall_ms / 1000; mono = sample.mono_ms / 1000
                let reading = clock.read(); let context = "\(item.id) sample \(index)"
                if sample.uncertain == true { XCTAssertNil(reading, context) }
                else {
                    let actual = try XCTUnwrap(reading, context)
                    XCTAssertEqual(actual.effective.timeIntervalSince1970, try XCTUnwrap(sample.effective_ms) / 1000, accuracy: 0.000001, context)
                    XCTAssertEqual(actual.wall.timeIntervalSince1970, wall, accuracy: 0.000001, context)
                }
            }
        }
    }
    func testSharedBank() throws {
        for item in try fixture().bank {
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: folder) }
            let file = folder.appendingPathComponent("bank.json")
            var bank = try AccountIDBank(file: file)
            for account in ["one", "two"] {
                let scope = BankScope(account: account, environment: .paper)
                try bank.enable(scope, cash: 100, equity: 100, positions: [:])
                for route in ["alice", "bob"] { try bank.configure(scope, route: route, asset: "stock", mode: "dollars", value: "100", fee: "0") }
            }
            var reservations: [String: (String, BankCase.Step)] = [:]
            for (index, step) in item.steps.enumerated() {
                let context = "\(item.id) step \(index)"
                if step.op == "restart" { bank = try AccountIDBank(file: file); continue }
                let scope = BankScope(account: step.account ?? "one", environment: .paper)
                func perform() throws {
                    switch step.op {
                    case "reserve":
                        let route = try XCTUnwrap(step.route); let trade = try XCTUnwrap(step.trade)
                        let event = try XCTUnwrap(step.event); let sell = try XCTUnwrap(step.sell)
                        let cid = AccountIDBank.clientID(scope, route: route, trade: trade, event: event, sell: sell, ordinal: 0)
                        try bank.reserve(scope, route: route, trade: trade, event: event, cid: cid, symbol: "SPY", asset: "stock", multiplier: 1, sell: sell, quantity: try XCTUnwrap(step.quantity), price: "10", ordinal: 0, cash: 100, equity: 100)
                        reservations[try XCTUnwrap(step.alias)] = (cid, step)
                    case "observe":
                        let (cid, original) = try XCTUnwrap(reservations[try XCTUnwrap(step.alias)])
                        try bank.observe(scope, AlpacaOrder(id: "broker-" + cid, client_order_id: cid, symbol: "SPY", status: try XCTUnwrap(step.status), qty: String(try XCTUnwrap(original.quantity)), limit_price: "10", filled_qty: String(try XCTUnwrap(step.filled)), filled_avg_price: "10", side: original.sell == true ? "sell" : "buy"))
                    case "inventory": try bank.inventory(scope, positions: try XCTUnwrap(step.positions))
                    default: XCTAssertEqual(step.op, "check")
                    }
                }
                if step.refused == true { XCTAssertThrowsError(try perform(), context) }
                else { try perform() }
                let report = try bank.snapshot(scope)
                XCTAssertEqual(report.available, try AccountIDBank.money(XCTUnwrap(step.available)), context)
                XCTAssertEqual(report.lots.filter { $0.active }.count, step.active, context)
                XCTAssertEqual(report.orders.count, step.orders, context)
                XCTAssertEqual(!report.blocked.isEmpty, step.blocked ?? false, context)
                if step.op == "observe" {
                    let (cid, original) = try XCTUnwrap(reservations[try XCTUnwrap(step.alias)])
                    let order = try XCTUnwrap(report.orders.first { $0.cid == cid })
                    XCTAssertEqual(order.filled, step.expected_filled ?? step.filled, context); XCTAssertEqual(order.status, step.status, context)
                    let owner = try XCTUnwrap(report.lots.first { $0.id == order.bankID })
                    XCTAssertEqual(owner.route, original.route, context); XCTAssertEqual(owner.trade, original.trade, context)
                }
            }
        }
    }
}
