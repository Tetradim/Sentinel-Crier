import XCTest
@testable import SentinelCrier

final class CopyDashboardTests: XCTestCase {
    func testSharedDashboardArithmeticFixtures() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "copy-dashboard", withExtension: "json"))
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        for item in try XCTUnwrap(root["cases"] as? [[String: Any]]) {
            let input = try XCTUnwrap(item["input"] as? [String: Any])
            var raw = try XCTUnwrap(input["report"] as? [String: Any])
            raw.merge(["version": 1, "event_id": UUID().uuidString.lowercased(), "revision": 1,
                       "observed_at": "2026-10-26T00:00:00Z", "state": "received"]) { old, _ in old }
            let report = try JSONDecoder().decode(CopyStatus.self, from: JSONSerialization.data(withJSONObject: raw))
            let expected = try XCTUnwrap(item["expected"] as? [String: Any])
            let now = (input["as_of"] as? String).flatMap(IntentEvent.date) ?? Date()
            let actual: [String: String?] = ["entry_average": CopyMoney.average(report.buy_premium, units: report.bought),
                "exit_average": CopyMoney.average(report.sell_premium, units: report.sold),
                "gross_realized_pnl": CopyMoney.pnl(report), "net_realized_pnl": CopyMoney.pnl(report, net: true),
                "unrealized_estimate": CopyMoney.openEstimate(report, now: now)]
            XCTAssertEqual(report.bought-report.sold, expected["remaining"] as? Int)
            for (key, value) in actual {
                XCTAssertEqual(value.flatMap { Decimal(string: $0) }, (expected[key] as? String).flatMap { Decimal(string: $0) }, "\(item["id"] ?? "case"): \(key)")
            }
        }
    }
    func testIncrementalUTF8CRLFSSEAndComments() throws {
        var parser = CopySSEParser(); var frames: [CopySSEParser.Frame] = []
        for byte in Data(": ignored\r\nevent: dashboard\r\ndata: {\"text\":\"é\"}\r\n\r\n".utf8) {
            if let frame = try parser.append(byte) { frames.append(frame) }
        }
        XCTAssertEqual(frames.count, 1); XCTAssertEqual(frames.first?.name, "dashboard")
        XCTAssertEqual(frames.first.map { String(decoding: $0.data, as: UTF8.self) }, "{\"text\":\"é\"}")
    }
    func testIgnoredEventStillHasByteAndLineBounds() throws {
        var parser = CopySSEParser()
        for _ in 0..<1_048_576 { _ = try parser.append(65) }
        XCTAssertThrowsError(try parser.append(65))
        var lines = CopySSEParser()
        for _ in 0..<8192 { _ = try lines.append(58); _ = try lines.append(10) }
        _ = try lines.append(58); XCTAssertThrowsError(try lines.append(10))
    }
    func testInvalidUTF8FailsSafely() throws {
        var parser = CopySSEParser(); _ = try parser.append(255)
        XCTAssertThrowsError(try parser.append(10))
    }
    func testMoneyNeverGuessesFeesMetadataPartialLotsOrStaleQuote() throws {
        var report = status()
        XCTAssertEqual(CopyMoney.pnl(report), "1.01") // decimal half up, not binary float
        XCTAssertNil(CopyMoney.pnl(report, net: true))
        report.fees = "0.005"; XCTAssertEqual(CopyMoney.pnl(report, net: true), "1")
        report.currency = nil; report.multiplier = nil; XCTAssertNil(CopyMoney.pnl(report))
        report = status(); report.sold = 1; XCTAssertNil(CopyMoney.pnl(report))
        report.sold = 0; report.quote = DiagnosticQuote(source: "test", quote_timestamp: "2026-10-26T00:00:00Z", bid: "11", ask: nil, last: nil)
        XCTAssertNil(CopyMoney.openEstimate(report, now: IntentEvent.date("2026-10-26T00:00:06Z")!))
        XCTAssertEqual(CopyMoney.openEstimate(report, now: IntentEvent.date("2026-10-26T00:00:05Z")!), "2")
        report.buy_premium = String(repeating: "9", count: 80); XCTAssertNil(CopyMoney.openEstimate(report, now: Date()))
        XCTAssertFalse(CopyMoney.valid("1e2")); XCTAssertFalse(CopyMoney.valid("-1"))
        XCTAssertEqual(CopyMoney.average("1", units: 3), "0.33333333")
    }
    func testStrictStatusRejectsContradictoryMetadataAndQuantities() throws {
        var report = status(); try report.validate(asset: "stock")
        report.multiplier = 100; XCTAssertThrowsError(try report.validate(asset: "stock"))
        report = status(); report.sold = 3; XCTAssertThrowsError(try report.validate(asset: "stock"))
        report = status(); report.buy_premium = "0"; XCTAssertThrowsError(try report.validate(asset: "stock"))
        report = status(); report.reason = "raw broker error"; XCTAssertThrowsError(try report.validate(asset: "stock"))
    }
    func testDurableReportRevisionAndOutboxRoundTrip() throws {
        var journal = CopyTelemetryJournal(pair: "opaque")
        var report = status(); report.revision = try journal.next(); journal.outbox["trade"] = report
        let restored = try JSONDecoder().decode(CopyTelemetryJournal.self, from: JSONEncoder().encode(journal))
        XCTAssertEqual(restored.revision, 1); XCTAssertEqual(restored.outbox["trade"]?.revision, 1)
        journal.revision = 9_007_199_254_740_991; XCTAssertThrowsError(try journal.next())
    }
    func status() -> CopyStatus {
        CopyStatus(event_id: UUID().uuidString.lowercased(), revision: 1, observed_at: "2026-10-26T00:00:00Z", state: "closed", bought: 2, sold: 2, buy_premium: "20", sell_premium: "21.005", currency: "USD", multiplier: 1)
    }
}

@MainActor final class CopyStreamLifecycleTests: XCTestCase {
    private func setup(role: String = "follower") throws -> (IntentController, IntentPairing, URL) {
        let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let pair = IntentPairing(url: URL(string: "https://copy.invalid")!, token: String(repeating: "x", count: 32), environment: .paper, role: role)
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test", secret: "test"))
        let controller = try IntentController(file: path)
        try controller.connect(api: api, account: "test", pairing: pair, startWorkers: false)
        return (controller, pair, path)
    }
    private func frame(_ event: IntentEvent) throws -> CopySSEParser.Frame {
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(event))
        return .init(name: "events", data: try JSONSerialization.data(withJSONObject: ["events": [["cursor": 1, "event": object]], "cursor": 1]))
    }
    func testHostNeverIngestsRemoteIntents() throws {
        let (controller, pair, path) = try setup(role: "host")
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: path) }
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "cancel", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        try controller.acceptCopyFrame(frame(event), pair: pair)
        XCTAssertTrue(controller.state.trades.isEmpty); XCTAssertEqual(controller.state.cursor, 0)
    }
    func testDuplicateCursorDurabilityAndLateFrameFence() throws {
        let (controller, pair, path) = try setup()
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: path) }
        // Paused entries and cancel instructions avoid broker actions in this test.
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "cancel", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        let page = try frame(event)
        try controller.acceptCopyFrame(page, pair: pair); try controller.acceptCopyFrame(page, pair: pair)
        XCTAssertEqual(controller.state.cursor, 1); XCTAssertEqual(controller.state.received.count, 1)
        let restored = try JSONDecoder().decode(IntentState.self, from: Data(contentsOf: path))
        XCTAssertEqual(restored.cursor, 1)
        controller.disconnect(); XCTAssertNil(controller.copyDashboard)
        XCTAssertThrowsError(try controller.acceptCopyFrame(page, pair: pair))
    }
    func testFollowerSnapshotRejectsOtherReceiver() throws {
        let (_, pair, path) = try setup(); defer { try? FileManager.default.removeItem(at: path) }
        let actor = UUID().uuidString.lowercased()
        var snapshot = CopyDashboard(version: 1, channel_id: UUID().uuidString.lowercased(), environment: .paper, role: "follower", actor: actor,
            generated_at: "2026-10-26T00:00:00Z", members: [.init(actor: "host", role: "host", revoked: false)], events: [], statuses: [], diagnostics: [], truncated: false)
        try snapshot.validate(pair: pair)
        snapshot.members.append(.init(actor: UUID().uuidString.lowercased(), role: "follower", revoked: false))
        XCTAssertThrowsError(try snapshot.validate(pair: pair))
    }
}
