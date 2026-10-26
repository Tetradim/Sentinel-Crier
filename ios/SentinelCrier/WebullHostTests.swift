import XCTest
@testable import SentinelCrier

final class WebullHostTests: XCTestCase {
    func testProductionSourceAlwaysMakesPaperIntentAndPreservesFIFO() throws {
        var state = WebullHostState()
        let trade = try state.enter(symbol: "AAPL", asset: "stock", quantity: 2, price: "1.25", environment: "production", account: "account", stocks: ["AAPL"])
        try state.instruction(trade: trade, action: "cancel", quantity: 2, price: "1.25")
        XCTAssertEqual(state.outgoing.map(\.action), ["enter", "cancel"])
        XCTAssertEqual(state.outgoing.map(\.sequence), [1, 2])
        state.outgoing.removeAll()
        XCTAssertEqual(state.history.map(\.action), ["enter", "cancel"])
        try state.validate()
        XCTAssertTrue(state.outgoing.allSatisfy { $0.environment == .paper })
        XCTAssertEqual(state.trades[trade]?.environment, "production")
    }
    func testRejectsUnmappedStockInvalidOCCAndPrice() {
        for (symbol, asset, price) in [("FAKE", "stock", "1"), ("AAPL261332C00100000", "option", "1"), ("AAPL", "stock", "NaN"), ("AAPL", "stock", "100001"), ("AAPL", "stock", "1.123456789")] {
            var state = WebullHostState()
            XCTAssertThrowsError(try state.enter(symbol: symbol, asset: asset, quantity: 1, price: price, environment: "sandbox", account: "a", stocks: ["AAPL"]))
            XCTAssertTrue(state.outgoing.isEmpty)
        }
    }
    func testUnknownOutcomeIsRetainedAcrossRestartWithoutDuplicateMutation() throws {
        var state = WebullHostState()
        let id = try state.enter(symbol: "AAPL", asset: "stock", quantity: 3, price: "10", environment: "sandbox", account: "a", stocks: ["AAPL"])
        try state.prepareOrder(trade: id, quantity: 3, price: "10", sell: false)
        let restored = try JSONDecoder().decode(WebullHostState.self, from: JSONEncoder().encode(state))
        XCTAssertEqual(restored.trades[id]?.orders.count, 1)
        XCTAssertEqual(restored.trades[id]?.orders.first?.status, "unknown")
        XCTAssertFalse(restored.trades[id]!.settled)
    }
    func testReceiptRejectsMismatchedIDAndRegressingFills() throws {
        var order = WebullHostOrder(clientID: "id", quantity: 4, price: "1", sell: false)
        try order.accept(WebullHostReceipt(client_order_id: "id", status: "partially_filled", filled_quantity: 2))
        XCTAssertThrowsError(try order.accept(WebullHostReceipt(client_order_id: "other", status: "filled", filled_quantity: 4)))
        XCTAssertThrowsError(try order.accept(WebullHostReceipt(client_order_id: "id", status: "accepted", filled_quantity: 1)))
        XCTAssertEqual(order.filled, 2)
    }
    func testExitQuantityBoundedByTrackedAndBrokerHoldings() throws {
        XCTAssertEqual(try WebullHostRules.exitQuantity(requested: 8, tracked: 5, held: 3), 3)
        XCTAssertThrowsError(try WebullHostRules.exitQuantity(requested: 1, tracked: 0, held: 20))
        XCTAssertThrowsError(try WebullHostRules.exitQuantity(requested: 1, tracked: 3, held: -1))
    }
    func testRejectedBuyQueuesOneCancelAfterOriginalEntry() throws {
        var state = WebullHostState()
        let id = try state.enter(symbol: "AAPL", asset: "stock", quantity: 1, price: "1", environment: "sandbox", account: "a", stocks: ["AAPL"])
        try state.prepareOrder(trade: id, quantity: 1, price: "1", sell: false)
        let client = state.trades[id]!.orders[0].clientID
        let receipt = WebullHostReceipt(client_order_id: client, status: "rejected", filled_quantity: 0)
        try state.accept(trade: id, receipt: receipt)
        try state.accept(trade: id, receipt: receipt)
        XCTAssertEqual(state.outgoing.map(\.action), ["enter", "cancel"])
    }
    func testMissingHistoryIsRejectedWithoutConstructingInvalidRange() throws {
        var state = WebullHostState()
        _ = try state.enter(symbol: "AAPL", asset: "stock", quantity: 1, price: "1", environment: "sandbox", account: "a", stocks: ["AAPL"])
        state.history = []; state.outgoing = []
        XCTAssertThrowsError(try state.validate())
    }
    @MainActor func testProductionViewUsesOneJournalOwner() {
        XCTAssertTrue(WebullHostController.shared === WebullHostController.shared)
    }
}

private final class WebullHostHTTPStub: URLProtocol {
    static var handler: ((WebullHostHTTPStub) -> Void)?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { Self.handler?(self) }
    override func stopLoading() {}
    func send(_ body: [String: Any], status: Int = 200) {
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: body))
        client?.urlProtocolDidFinishLoading(self)
    }
    func jsonBody() -> [String: Any] {
        if let data = request.httpBody { return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:] }
        guard let stream = request.httpBodyStream else { return [:] }
        stream.open(); defer { stream.close() }
        var data = Data(); var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }; data.append(contentsOf: buffer.prefix(count))
        }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }
}

final class WebullHostTransportTests: XCTestCase {
    @MainActor func testPublishesWhileSourcePOSTStillPendingAndRestartNeverReposts() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory); WebullHostHTTPStub.handler = nil }
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [WebullHostHTTPStub.self]
        let session = URLSession(configuration: config); defer { session.invalidateAndCancel() }
        let pairing = IntentPairing(url: URL(string: "https://relay.test")!, token: String(repeating: "a", count: 43), environment: .paper, role: "host")
        let file = directory.appendingPathComponent("journal.json")
        var customer = CustomerSession(access_token: "customer-token", refresh_token: "refresh", expires_in: 3600, token_type: "bearer", user: .init(id: UUID().uuidString.lowercased()))
        customer.expiresAt = Date().addingTimeInterval(3600)
        customer.serviceURL = "https://abcdefghijklmnopqrst.supabase.co/functions/v1/crier-oauth"
        let sourceStarted = expectation(description: "Source POST pending")
        let relayReceived = expectation(description: "Paper instruction sent before source response")
        let lock = NSLock()
        var source: WebullHostHTTPStub?; var sourceID = ""; var posts = 0
        WebullHostHTTPStub.handler = { stub in
            switch stub.request.url!.path {
            case "/v1/capabilities": stub.send(["available": true, "environments": ["production"], "stocks": ["AAPL"], "options": true])
            case "/v1/connection": stub.send(["state": "connected", "environment": "production", "account_id": "webull-source"])
            case "/v1/orders":
                lock.lock(); posts += 1; source = stub; sourceID = stub.jsonBody()["client_order_id"] as? String ?? ""; lock.unlock()
                sourceStarted.fulfill() // Intentionally no source response yet.
            case "/api/sync/events":
                let event = stub.jsonBody()
                XCTAssertEqual(event["environment"] as? String, "paper")
                XCTAssertEqual(event["symbol"] as? String, "AAPL")
                XCTAssertNil(event["account_id"]); XCTAssertNil(event["access_token"])
                relayReceived.fulfill(); stub.send(["ok": true])
            default:
                lock.lock(); let id = sourceID; lock.unlock()
                stub.send(["client_order_id": id, "broker_order_id": "source-broker", "status": "filled", "filled_quantity": 2, "average_fill_price": "1.25"])
            }
        }
        let host = WebullHostController(file: file, session: session, pairing: pairing, loadPairing: false)
        host.setActive(true)
        await host.connect(service: "https://webull.test", environment: "production", customer: customer)
        let submission = Task { await host.confirm(symbol: "AAPL", asset: "stock", quantity: 2, price: "1.25", environment: "production", acknowledged: true, customer: customer) }
        await fulfillment(of: [sourceStarted, relayReceived], timeout: 5)
        lock.lock(); let pending = source; let cid = sourceID; lock.unlock()
        pending?.send(["client_order_id": cid, "status": "unknown", "filled_quantity": 0])
        await submission.value
        await host.publish()
        for _ in 0..<100 {
            if host.state.outgoing.isEmpty { break }
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertTrue(host.state.outgoing.isEmpty)
        host.setActive(false)
        let restarted = WebullHostController(file: file, session: session, pairing: pairing, loadPairing: false)
        restarted.setActive(true)
        await restarted.connect(service: "https://webull.test", environment: "production", customer: customer)
        await restarted.reconcile(customer: customer)
        XCTAssertEqual(restarted.state.trades.values.first?.orders.first?.status, "filled")
        lock.lock(); let count = posts; lock.unlock()
        XCTAssertEqual(count, 1)
    }
    @MainActor func testUnconfiguredControllerDoesNotSendAnOrder() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathComponent("journal.json")
        let host = WebullHostController(file: file, loadPairing: false)
        host.setActive(true)
        await host.confirm(symbol: "AAPL", asset: "stock", quantity: 1, price: "1", environment: "production", acknowledged: true, customer: nil)
        XCTAssertTrue(host.state.trades.isEmpty)
    }
}
