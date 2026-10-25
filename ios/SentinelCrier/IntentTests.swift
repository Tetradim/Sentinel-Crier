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

@MainActor
final class IntentRecoveryTests: XCTestCase {
    private final class Clock {
        var date = Date(timeIntervalSince1970: 1_800_000_000)
        var reads = 0; var jumpAt: Int?
        func read() -> Date { reads += 1; if reads == jumpAt { date += 60 }; return date }
    }
    private func event(_ clock: Clock, action: String = "cancel") -> IntentEvent {
        var event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 2, action: action, environment: .paper, symbol: "AAPL", asset: "stock", quantity: 2, price: "10")
        event.created_at = IntentDiagnosticRecord.timestamp(clock.date)
        event.expires_at = IntentDiagnosticRecord.timestamp(clock.date.addingTimeInterval(30))
        return event
    }
    private func order(_ client: String, status: String = "new", sell: Bool = false, filled: String = "0") -> AlpacaOrder {
        AlpacaOrder(id: sell ? "sell-broker" : "buy-broker", client_order_id: client, symbol: "AAPL", status: status, qty: "2", limit_price: "10", filled_qty: filled, filled_avg_price: filled == "0" ? nil : "10", side: sell ? "sell" : "buy")
    }
    private func setup(_ event: IntentEvent, clock: Clock, legacy: Bool = false, withMutation: Bool = true) throws -> (IntentController, URL, AlpacaREST, IntentPairing, RecoveryScript) {
        let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        let pair = IntentPairing(url: URL(string: "https://relay.test")!, token: String(repeating: "x", count: 32), environment: .paper, role: "follower")
        var state = IntentState(); state.accountID = "account-a"; state.pairingID = pair.fingerprint; state.preferences.paused = false
        var trade = IntentTrade(); try trade.accept(event)
        if withMutation { trade.mutations = [IntentMutation(clientID: "original-buy", eventID: UUID().uuidString.lowercased(), sell: false, quantity: 2, order: order("original-buy"), cancelUnknown: legacy)] }
        state.trades[event.trade_id] = trade
        try JSONEncoder().encode(state).write(to: path)
        let script = RecoveryScript(); let key = UUID().uuidString
        RecoveryProtocol.register(script, key: key)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [RecoveryProtocol.self]
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: key, secret: "test"), session: URLSession(configuration: config))
        let controller = try IntentController(file: path, now: { clock.read() })
        try controller.connect(api: api, account: "account-a", pairing: pair, startWorkers: false)
        return (controller, path, api, pair, script)
    }
    func testClockChangeBeforeEntryDefersWithoutBlockingLaterValidWork() async throws {
        let clock = Clock(); let desired = event(clock, action: "enter")
        let (controller, file, _, _, script) = try setup(desired, clock: clock, withMutation: false)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        clock.date += 60; await controller.process()
        XCTAssertEqual(script.snapshot().posts, 0)
        XCTAssertTrue(controller.state.trades[desired.trade_id]!.mutations.isEmpty)
        XCTAssertTrue(controller.message.contains("clock"))
        clock.date -= 60; await controller.process(); XCTAssertEqual(script.snapshot().posts, 1)
    }
    func testFinalClockRefusalPersistsNoPostWithoutAnUnknownBrokerLookupOnRestart() async throws {
        let clock = Clock(); let desired = event(clock, action: "enter")
        let (controller, file, api, pair, script) = try setup(desired, clock: clock, withMutation: false)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        clock.jumpAt = clock.reads + 2 // Initial entry gate succeeds; the final HTTP gate sees the discontinuity.
        await controller.process()
        XCTAssertEqual(script.snapshot().posts, 0)
        let mutation = try XCTUnwrap(controller.state.trades[desired.trade_id]?.mutations.first)
        XCTAssertTrue(mutation.notSubmitted == true); XCTAssertNil(mutation.order)
        XCTAssertTrue(controller.state.unresolved.isEmpty)
        controller.disconnect()
        let restored = try IntentController(file: file, now: { clock.date })
        try restored.connect(api: api.freshClient(customer: nil), account: "account-a", pairing: pair, startWorkers: false)
        defer { restored.disconnect() }
        try await restored.reconcileBeforeResume(); await restored.process()
        XCTAssertEqual(script.snapshot().posts, 0); XCTAssertFalse(script.snapshot().requests.contains("lookup"))
    }
    func testCancelFailureReconcilesBeforeRetryAndSurvivesRestart() async throws {
        let clock = Clock(), desired = event(Clock())
        let (controller, file, api, pair, script) = try setup(desired, clock: clock)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        await controller.process()
        XCTAssertEqual(script.snapshot().deletes, 1)
        XCTAssertEqual(controller.state.trades[desired.trade_id]?.mutations.first?.cancelAttemptedAt, clock.date)
        clock.date.addTimeInterval(4)
        await controller.process()
        XCTAssertEqual(script.snapshot().deletes, 1)
        controller.disconnect()
        let restored = try IntentController(file: file, now: { clock.date })
        try restored.connect(api: api.freshClient(customer: nil), account: "account-a", pairing: pair, startWorkers: false)
        defer { restored.disconnect() }
        clock.date.addTimeInterval(1)
        await restored.process()
        let result = script.snapshot()
        XCTAssertEqual(result.deletes, 2)
        XCTAssertEqual(result.posts, 0)
        XCTAssertEqual(result.requests.filter { $0 == "lookup" }.count, 3)
        XCTAssertEqual(Array(result.requests.suffix(2)), ["lookup", "delete"])
    }
    func testLegacyMarkerRecoversButPendingCancelNeverResends() async throws {
        let clock = Clock(), desired = event(Clock())
        let (controller, file, _, _, script) = try setup(desired, clock: clock, legacy: true)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        script.setStatus("pending_cancel")
        await controller.process()
        XCTAssertEqual(script.snapshot().deletes, 0)
        script.setStatus("new")
        await controller.process()
        XCTAssertEqual(script.snapshot().deletes, 1)
        XCTAssertEqual(script.snapshot().posts, 0)
    }
    func testCrashAfterDurableMarkerBeforeDeleteWaitsThenRecovers() async throws {
        let clock = Clock(), desired = event(Clock())
        let (controller, file, api, pair, script) = try setup(desired, clock: clock, legacy: true)
        controller.disconnect()
        defer { try? FileManager.default.removeItem(at: file) }
        var saved = controller.state
        saved.trades[desired.trade_id]!.mutations[0].cancelAttemptedAt = clock.date
        try JSONEncoder().encode(saved).write(to: file)
        let restored = try IntentController(file: file, now: { clock.date })
        try restored.connect(api: api.freshClient(customer: nil), account: "account-a", pairing: pair, startWorkers: false)
        defer { restored.disconnect() }
        clock.date.addTimeInterval(4)
        await restored.process()
        XCTAssertEqual(script.snapshot().deletes, 0)
        clock.date.addTimeInterval(1)
        await restored.process()
        XCTAssertEqual(script.snapshot().deletes, 1)
        XCTAssertEqual(script.snapshot().posts, 0)
        XCTAssertEqual(Array(script.snapshot().requests.suffix(2)), ["lookup", "delete"])
    }
    func testFailedReconciliationNeverRetriesCancelOrCreatesOrder() async throws {
        let clock = Clock(), desired = event(Clock(), action: "exit")
        let (controller, file, _, _, script) = try setup(desired, clock: clock, legacy: true)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        script.setStatus("lookup_missing")
        await controller.process()
        clock.date.addTimeInterval(10)
        await controller.process()
        XCTAssertEqual(script.snapshot().deletes, 0)
        XCTAssertEqual(script.snapshot().posts, 0)
    }
    func testCancelRacingFillDoesNotRetryOrOversell() async throws {
        let clock = Clock(), desired = event(Clock(), action: "exit")
        let (controller, file, _, _, script) = try setup(desired, clock: clock)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        await controller.process()
        script.setStatus("filled"); clock.date.addTimeInterval(6)
        await controller.process()
        await controller.process()
        XCTAssertEqual(script.snapshot().deletes, 1)
        XCTAssertEqual(script.snapshot().posts, 1)
        XCTAssertEqual(script.snapshot().postedQuantities, ["2"])
        XCTAssertEqual(controller.state.trades[desired.trade_id]?.owned, 0)
    }
    func testFutureEntryDefersThenBecomesEligible() async throws {
        let clock = Clock(); var desired = event(clock, action: "enter")
        desired.created_at = IntentDiagnosticRecord.timestamp(clock.date.addingTimeInterval(5))
        desired.expires_at = IntentDiagnosticRecord.timestamp(clock.date.addingTimeInterval(25))
        let (controller, file, _, _, script) = try setup(desired, clock: clock, withMutation: false)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        await controller.process()
        XCTAssertNil(controller.state.trades[desired.trade_id]?.completed)
        XCTAssertNil(controller.state.trades[desired.trade_id]?.entrySkipped)
        XCTAssertEqual(script.snapshot().posts, 0)
        clock.date.addTimeInterval(5)
        await controller.process()
        await controller.process()
        XCTAssertEqual(script.snapshot().posts, 1)
    }
}

private final class RecoveryScript {
    struct Snapshot { var deletes = 0; var posts = 0; var requests: [String] = []; var postedQuantities: [String] = [] }
    private let lock = NSLock(); private var state = Snapshot(); private var status = "new"
    func snapshot() -> Snapshot { lock.lock(); defer { lock.unlock() }; return state }
    func setStatus(_ value: String) { lock.lock(); defer { lock.unlock() }; status = value }
    func respond(_ request: URLRequest) throws -> (Int, Data) {
        lock.lock(); defer { lock.unlock() }
        let path = request.url!.path
        if path == "/v2/account" { return (200, Data(#"{"id":"account-a","status":"ACTIVE","buying_power":"1000","equity":"1000","trading_blocked":false,"account_blocked":false}"#.utf8)) }
        if path == "/v2/positions" { return (200, Data(#"[{"symbol":"AAPL","qty":"2","qty_available":"2","avg_entry_price":"10"}]"#.utf8)) }
        if request.httpMethod == "DELETE" {
            state.deletes += 1; state.requests.append("delete")
            if state.deletes == 1 { throw URLError(.timedOut) }
            return (204, Data())
        }
        if request.httpMethod == "POST" {
            state.posts += 1; state.requests.append("post")
            var data = request.httpBody ?? Data()
            if let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; data.append(contentsOf: buffer.prefix(count)) }
            }
            let body = try JSONSerialization.jsonObject(with: data) as! [String: Any]
            state.postedQuantities.append(body["qty"] as! String)
            return (200, try order(client: body["client_order_id"] as! String, sell: body["side"] as? String == "sell", status: "filled"))
        }
        state.requests.append("lookup")
        if status == "lookup_missing" { return (404, Data()) }
        let client = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!.first { $0.name == "client_order_id" }!.value!
        return (200, try order(client: client, sell: client != "original-buy", status: status))
    }
    private func order(client: String, sell: Bool, status: String) throws -> Data {
        try JSONEncoder().encode(AlpacaOrder(id: sell ? "sell-broker" : "buy-broker", client_order_id: client, symbol: "AAPL", status: status, qty: "2", limit_price: "10", filled_qty: status == "filled" ? "2" : "0", filled_avg_price: status == "filled" ? "10" : nil, side: sell ? "sell" : "buy"))
    }
}
private final class RecoveryProtocol: URLProtocol {
    private static let lock = NSLock(); private static var scripts: [String: RecoveryScript] = [:]
    static func register(_ script: RecoveryScript, key: String) { lock.lock(); defer { lock.unlock() }; scripts[key] = script }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let script = Self.scripts[request.value(forHTTPHeaderField: "APCA-API-KEY-ID") ?? ""]; Self.lock.unlock()
        do {
            let (code, data) = try XCTUnwrap(script).respond(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
