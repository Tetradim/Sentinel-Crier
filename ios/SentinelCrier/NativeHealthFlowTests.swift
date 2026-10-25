import XCTest
@testable import SentinelCrier

private final class HealthMockProtocol: URLProtocol {
    static let lock = NSLock()
    static var routes: [String: (URLRequest) throws -> (Int, Data)] = [:]
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            Self.lock.lock(); let route = Self.routes[request.value(forHTTPHeaderField: "X-Crier-Health-Test") ?? ""]; Self.lock.unlock()
            let (status, data) = try XCTUnwrap(route)(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
@MainActor final class NativeHealthFlowTests: XCTestCase {
    private final class Memory: NativeHealthStorage {
        var data: Data?
        func read() throws -> Data? { data }
        func write(_ value: Data) throws { data = value }
    }
    private func network(_ route: @escaping (URLRequest) throws -> (Int, Data)) -> URLSession {
        let identity = UUID().uuidString
        HealthMockProtocol.lock.lock(); HealthMockProtocol.routes[identity] = route; HealthMockProtocol.lock.unlock()
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [HealthMockProtocol.self]
        config.httpAdditionalHeaders = ["X-Crier-Health-Test": identity]
        return URLSession(configuration: config)
    }
    private func response(_ request: URLRequest) throws -> (Int, Data) {
        XCTAssertEqual(request.httpMethod, "GET")
        if request.url?.path == "/v2/account" {
            return (200, try JSONSerialization.data(withJSONObject: ["id": "health-account", "status": "ACTIVE", "buying_power": "1", "equity": "1", "trading_blocked": false, "account_blocked": false]))
        }
        return (200, Data("[]".utf8))
    }
    private func workspace(_ folder: URL, _ session: URLSession, _ health: NativeHealth) throws -> AlpacaWorkspace {
        AlpacaWorkspace(journal: try AlpacaJournal(file: folder.appendingPathComponent("broker.json")),
            intentController: try IntentController(file: folder.appendingPathComponent("intent.json"), session: session),
            defaults: UserDefaults(suiteName: UUID().uuidString)!, health: health,
            loadIntentPairing: { nil }, makeClient: { AlpacaREST(environment: $0, credentials: $1, session: session) },
            loadCredentials: { _ in AlpacaCredentials(key: "synthetic", secret: "synthetic") })
    }
    func testHealthViewReadsDoNotFetchDataAndBackgroundRequiresFreshChecks() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        var calls = 0
        let session = network { [self] request in calls += 1; return try response(request) }
        defer { session.invalidateAndCancel() }
        let h = NativeHealth(storage: Memory()); let model = try workspace(folder, session, h)
        model.selectPurpose(.alerts); await model.connect(key: "", secret: "")
        XCTAssertEqual(h.snapshot()[0].state, "healthy"); XCTAssertEqual(h.snapshot()[1].state, "healthy")
        let count = calls; _ = h.snapshot(); _ = h.snapshot(); XCTAssertEqual(calls, count)
        XCTAssertFalse(model.readiness.deliveryEnabled)
        await model.sceneActive(false); XCTAssertTrue(h.snapshot().allSatisfy { $0.state == "stopped" })
        await model.sceneActive(true); XCTAssertEqual(h.snapshot()[0].state, "healthy"); XCTAssertEqual(h.snapshot()[1].state, "healthy")
        XCTAssertFalse(model.readiness.deliveryEnabled)
        model.disconnect(); XCTAssertTrue(h.snapshot().allSatisfy { $0.state == "stopped" })
    }
    func testLateAccountResponseAfterLogoutCannotRefreshHealth() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let entered = expectation(description: "account check paused"); let gate = DispatchSemaphore(value: 0); var hold = false
        let session = network { [self] request in
            if hold && request.url?.path == "/v2/account" { entered.fulfill(); _ = gate.wait(timeout: .now() + 10) }
            return try response(request)
        }
        defer { session.invalidateAndCancel() }
        let h = NativeHealth(storage: Memory()); let model = try workspace(folder, session, h)
        model.selectPurpose(.alerts); await model.connect(key: "", secret: "")
        hold = true; let check = Task { await model.refresh() }
        await fulfillment(of: [entered], timeout: 5)
        model.oauthLogout(); gate.signal(); await check.value
        XCTAssertTrue(h.snapshot().allSatisfy { $0.state == "stopped" }); XCTAssertNil(model.account)
    }
    func testActualDiscordOutcomesKeepUnknownDeliveriesVisibleWithoutAutomaticRetry() async throws {
        for status in [200, 403, 429, 503] {
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: folder) }
            let journal = try AlpacaJournal(file: folder.appendingPathComponent("journal.json"))
            try await journal.ingest(AlpacaFill(id: "fill", activity_type: "FILL", order_id: "order", symbol: "AAPL", side: "buy", qty: "1", price: "1.25", transaction_time: "2026-10-25T00:00:00Z"), environment: .paper, accountID: "account")
            var calls = 0
            let session = network { request in
                calls += 1; XCTAssertEqual(request.httpMethod, "POST")
                let body: [String: Any] = status == 200 ? ["id": "123"] : ["retry_after": 60]
                return (status, try JSONSerialization.data(withJSONObject: body))
            }
            defer { session.invalidateAndCancel() }
            let h = NativeHealth(storage: Memory()); let ticket = h.begin(scope: "discord", active: [.discord])
            let publisher = AlpacaDiscordDelivery(journal: journal, session: session, webhook: { URL(string: "https://discord.com/api/webhooks/123/synthetic") }, defaults: UserDefaults(suiteName: UUID().uuidString)!)
            let observer: @Sendable (HealthObservation, HealthReason) async -> Void = { state, reason in await h.record(ticket, .discord, state, reason) }
            try await publisher.deliver(environment: .paper, accountID: "account", observe: observer)
            XCTAssertEqual(h.snapshot().last?.state, status == 200 ? "healthy" : status == 429 ? "degraded" : "blocked")
            try await publisher.deliver(environment: .paper, accountID: "account", observe: observer)
            XCTAssertEqual(calls, 1)
            if status == 503 { XCTAssertEqual(h.snapshot().last?.reason, .uncertain) }
            let saved = await journal.snapshot()
            XCTAssertEqual(saved.deliveries.first?.state, status == 200 ? "sent" : status == 429 ? "pending" : status == 403 ? "rejected HTTP 403" : "uncertain")
        }
    }
}
