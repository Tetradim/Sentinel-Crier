import XCTest
@testable import SentinelCrier

final class GuidedSetupTests: XCTestCase {
    func testEvidenceIsSessionOnlyAndScopedToConfiguration() {
        var readiness = GuidedReadiness()
        readiness.verified = true
        readiness.previewed = true
        readiness.testResult = "Test delivered"
        readiness.deliveryEnabled = true
        readiness.invalidate()
        XCTAssertFalse(readiness.verified)
        XCTAssertFalse(readiness.previewed)
        XCTAssertNil(readiness.testResult)
        XCTAssertFalse(readiness.deliveryEnabled)
        XCTAssertFalse(GuidedReadiness().deliveryEnabled)
    }
    @MainActor
    func testRestartRestoresPurposeWithoutConnectingOrEnabling() throws {
        let suite = UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("alerts", forKey: "guidedPurpose")
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        let intentFile = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: intentFile) }
        let model = AlpacaWorkspace(journal: try AlpacaJournal(file: file), intentController: try IntentController(file: intentFile), defaults: defaults)
        XCTAssertEqual(model.purpose, .alerts)
        XCTAssertNil(model.account)
        XCTAssertFalse(model.readiness.verified)
        XCTAssertFalse(model.readiness.deliveryEnabled)
    }
}

/// Each mocked workspace owns its session and temporary stores; no broker or Discord traffic.
@MainActor
final class GuidedJourneyTests: XCTestCase {
    private func file() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }; return url
    }
    private func defaults() -> UserDefaults {
        let suite = UUID().uuidString
        addTeardownBlock { UserDefaults.standard.removePersistentDomain(forName: suite) }
        return UserDefaults(suiteName: suite)!
    }
    private func workspace(test: @escaping () async throws -> String = { "Test delivered • message 123" }, failure: Bool = false, trade: Bool = false) throws -> (AlpacaWorkspace, IntentController, GuidedHTTPLog) {
        let log = GuidedHTTPLog(failure: failure, tradingBlocked: !trade)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [GuidedURLProtocol.self]
        let session = URLSession(configuration: config, delegate: nil, delegateQueue: nil)
        let key = UUID().uuidString
        GuidedURLProtocol.register(log, key: key)
        let pairing = IntentPairing(url: URL(string: "https://relay.test")!, token: String(repeating: "x", count: 32), environment: .paper, role: "host")
        var state = IntentState(); state.accountID = "a"; state.preferences.paused = false
        if trade { state.pairingID = pairing.fingerprint }
        let intentFile = file(); try JSONEncoder().encode(state).write(to: intentFile)
        let intent = try IntentController(file: intentFile, session: session)
        let model = AlpacaWorkspace(journal: try AlpacaJournal(file: file()), intentController: intent, defaults: defaults(), testDiscord: test,
            webhook: { URL(string: "https://discord.com/api/webhooks/123/synthetic") },
            deliverDiscord: { _, _ in log.recordDelivery() },
            loadIntentPairing: { trade ? pairing : nil },
            makeClient: { environment, _ in AlpacaREST(environment: environment, credentials: AlpacaCredentials(key: key, secret: "synthetic"), session: session) },
            loadCredentials: { _ in AlpacaCredentials(key: key, secret: "synthetic") }, saveCredentials: { _, _ in })
        model.selectPurpose(trade ? .trade : .alerts)
        return (model, intent, log)
    }
    func testAlertsReadsFillsWithoutOrdersChannelOrIntentActivation() async throws {
        let (model, intent, log) = try workspace()
        await model.connect(key: "", secret: "")
        XCTAssertEqual(model.account?.id, "a")
        XCTAssertTrue(model.readiness.verified)
        XCTAssertFalse(model.readiness.deliveryEnabled)
        XCTAssertFalse(intent.hosting)
        XCTAssertEqual(intent.message, "Disconnected; execution journals retained.")
        XCTAssertTrue(log.paths.contains("/v2/account/activities/FILL"))
        XCTAssertTrue(log.paths.allSatisfy { ["/v2/account", "/v2/positions", "/v2/account/activities/FILL"].contains($0) })
        await model.prepare(symbol: "AAPL", quantity: 1, limit: "1", sell: false, contract: nil)
        XCTAssertNil(model.review)
        do { _ = try await model.quickConnect(host: true, service: "https://relay.test", invitation: ""); XCTFail("Alerts activated pairing") } catch {}
        await model.sceneActive(false); await model.sceneActive(true)
        XCTAssertFalse(intent.hosting)
        XCTAssertEqual(intent.message, "Disconnected; execution journals retained.")
        XCTAssertFalse(model.readiness.deliveryEnabled)
    }
    func testFailureCannotProduceReadinessOrDeliveryPermission() async throws {
        let (model, _, _) = try workspace(failure: true)
        await model.connect(key: "", secret: "")
        model.previewDiscord(); model.enableDiscordDelivery(true)
        XCTAssertNil(model.account)
        XCTAssertFalse(model.readiness.verified)
        XCTAssertFalse(model.readiness.deliveryEnabled)
    }
    func testExplicitPreviewAndPermissionAreSeparateAndTestIsOptional() async throws {
        let (model, _, _) = try workspace()
        await model.connect(key: "", secret: "")
        model.enableDiscordDelivery(true)
        XCTAssertFalse(model.readiness.deliveryEnabled)
        model.previewDiscord()
        XCTAssertTrue(model.readiness.previewed)
        XCTAssertNil(model.readiness.testResult)
        model.enableDiscordDelivery(true)
        XCTAssertTrue(model.readiness.deliveryEnabled)
        model.discordConfigurationChanged()
        XCTAssertFalse(model.readiness.deliveryEnabled)
        XCTAssertFalse(model.readiness.previewed)
        XCTAssertNil(model.readiness.testResult)
        model.disconnect()
        XCTAssertFalse(model.readiness.verified)
    }
    func testUncertainSyntheticTestDoesNotClaimSuccess() async throws {
        let (model, _, _) = try workspace(test: { throw URLError(.timedOut) })
        await model.connect(key: "", secret: ""); model.previewDiscord()
        await model.sendDiscordTest()
        XCTAssertTrue(model.readiness.testResult?.contains("not confirmed") == true)
        XCTAssertFalse(model.readiness.deliveryEnabled)
    }
    func testUnchangedPreviewCanRepeatedlyEnableAndRefresh() async throws {
        let (model, _, log) = try workspace()
        await model.connect(key: "", secret: "")
        model.previewDiscord()
        // A different dictionary encoding order must never revoke unchanged evidence.
        for _ in 0..<30 {
            model.enableDiscordDelivery(true)
            XCTAssertTrue(model.readiness.deliveryEnabled)
            await model.refresh()
            XCTAssertTrue(model.readiness.deliveryEnabled)
        }
        XCTAssertEqual(log.deliveries, 30)
    }
    func testRapidForegroundReturnRecoversOnFreshRefreshWithoutDeliveryOrEngine() async throws {
        let (model, intent, log) = try workspace()
        await model.connect(key: "", secret: "")
        model.previewDiscord(); model.enableDiscordDelivery(true)
        let started = expectation(description: "refresh account request started")
        log.pauseAccount { started.fulfill() }
        let task = Task { await model.refresh() }
        await fulfillment(of: [started], timeout: 2)
        await model.sceneActive(false)
        await model.sceneActive(true) // Current request still holds the workspace lock.
        XCTAssertTrue(model.lifecycle.contains("pending"))
        XCTAssertFalse(model.readiness.verified)
        log.resumeAccount(); await task.value
        XCTAssertFalse(model.readiness.verified) // The old-scope result cannot verify.
        await model.refresh() // The next current-scope foreground refresh resumes safely.
        XCTAssertTrue(model.readiness.verified)
        XCTAssertFalse(model.lifecycle.contains("pending"))
        XCTAssertFalse(model.readiness.previewed)
        XCTAssertFalse(model.readiness.deliveryEnabled)
        XCTAssertFalse(intent.hosting)
        XCTAssertEqual(intent.message, "Disconnected; execution journals retained.")
    }
    func testInterruptedTradeReconciliationCannotStartStaleWorkers() async throws {
        let (model, intent, log) = try workspace(trade: true)
        defer { intent.disconnect() }
        await model.connect(key: "", secret: "")
        XCTAssertTrue(intent.hosting)
        await model.sceneActive(false)
        let started = expectation(description: "intent reconciliation account request started")
        // Resume refresh reads account first, then intent reconciliation reads it again.
        log.pauseAccount(after: 1) { started.fulfill() }
        let task = Task { await model.sceneActive(true) }
        await fulfillment(of: [started], timeout: 2)
        await model.sceneActive(false)
        await model.sceneActive(true)
        log.resumeAccount(); await task.value
        XCTAssertFalse(intent.hosting)
        XCTAssertFalse(model.readiness.verified)
        XCTAssertFalse(model.readiness.deliveryEnabled)
        await model.refresh()
        XCTAssertTrue(model.readiness.verified)
        XCTAssertTrue(intent.hosting)
        XCTAssertFalse(model.readiness.deliveryEnabled)
    }
    func testLateAccountVerificationCannotConnectAfterSuspension() async throws {
        let (model, _, log) = try workspace()
        let started = expectation(description: "account request started")
        log.pauseAccount { started.fulfill() }
        let task = Task { await model.connect(key: "", secret: "") }
        await fulfillment(of: [started], timeout: 2)
        await model.sceneActive(false)
        log.resumeAccount()
        await task.value
        XCTAssertNil(model.account)
        XCTAssertFalse(model.readiness.verified)
        XCTAssertFalse(model.readiness.deliveryEnabled)
    }
    func testLateTestAcknowledgementIsDiscardedAfterBackground() async throws {
        let started = expectation(description: "test started")
        var complete: CheckedContinuation<String, Never>?
        let (model, _, _) = try workspace(test: {
            await withCheckedContinuation { continuation in complete = continuation; started.fulfill() }
        })
        await model.connect(key: "", secret: ""); model.previewDiscord()
        let task = Task { await model.sendDiscordTest() }
        await fulfillment(of: [started], timeout: 2)
        await model.sceneActive(false)
        complete?.resume(returning: "Test delivered • message 123")
        await task.value
        XCTAssertNil(model.readiness.testResult)
        XCTAssertFalse(model.readiness.previewed)
        XCTAssertFalse(model.readiness.deliveryEnabled)
    }
}

private final class GuidedHTTPLog {
    let failure: Bool
    let tradingBlocked: Bool
    private let lock = NSLock()
    private var requests: [String] = []
    private var deliveryCount = 0
    var deliveries: Int { lock.lock(); defer { lock.unlock() }; return deliveryCount }
    func recordDelivery() { lock.lock(); defer { lock.unlock() }; deliveryCount += 1 }
    private var accountsBeforePause = 0
    private var paused: (() -> Void)?
    private var waiting: (() -> Void)?
    func pauseAccount(after: Int = 0, _ started: @escaping () -> Void) { lock.lock(); defer { lock.unlock() }; accountsBeforePause = after; paused = started }
    func deferAccount(_ completion: @escaping () -> Void) -> Bool {
        lock.lock()
        guard let started = paused else { lock.unlock(); return false }
        if accountsBeforePause > 0 { accountsBeforePause -= 1; lock.unlock(); return false }
        paused = nil; waiting = completion; lock.unlock(); started(); return true
    }
    func resumeAccount() {
        lock.lock(); let completion = waiting; waiting = nil; lock.unlock(); completion?()
    }
    init(failure: Bool, tradingBlocked: Bool) { self.failure = failure; self.tradingBlocked = tradingBlocked }
    var paths: [String] { lock.lock(); defer { lock.unlock() }; return requests }
    func response(_ request: URLRequest) throws -> (Int, Data) {
        lock.lock(); defer { lock.unlock() }
        guard request.httpMethod == "GET" else { throw URLError(.unsupportedURL) }
        let path = request.url!.path; requests.append(path)
        if failure { return (401, Data()) }
        if path == "/v2/account" {
            // Trading permission is deliberately blocked; read-only verification must still succeed.
            return (200, try JSONSerialization.data(withJSONObject: ["id": "a", "status": "ACTIVE", "buying_power": "100", "equity": "100", "trading_blocked": tradingBlocked, "account_blocked": false]))
        }
        guard ["/v2/positions", "/v2/account/activities/FILL"].contains(path) else { throw URLError(.unsupportedURL) }
        return (200, Data("[]".utf8))
    }
}
private final class GuidedURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var logs: [String: GuidedHTTPLog] = [:]
    static func register(_ log: GuidedHTTPLog, key: String) { lock.lock(); defer { lock.unlock() }; logs[key] = log }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let log = Self.logs[request.value(forHTTPHeaderField: "APCA-API-KEY-ID") ?? ""]; Self.lock.unlock()
        guard let log else { client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL)); return }
        if request.url?.path == "/v2/account", log.deferAccount({ [weak self] in self?.respond(log) }) { return }
        respond(log)
    }
    private func respond(_ log: GuidedHTTPLog) {
        do {
            let (status, data) = try log.response(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
