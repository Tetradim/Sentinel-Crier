import XCTest
@testable import SentinelCrier

final class AlpacaTests: XCTestCase {
    private func ticket(price: Decimal = 2, date: Date = Date()) -> AlpacaTicket {
        AlpacaTicket(id: "crier-test", environment: .paper, accountID: "account-a", symbol: "AAPL", quantity: 2, limitPrice: price, side: "buy", positionIntent: nil, multiplier: 1, reviewedAt: date)
    }
    private func file() -> URL { FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json") }
    private func fill(id: String = "fill-1", price: String = "2") -> AlpacaFill {
        AlpacaFill(id: id, activity_type: "FILL", order_id: "broker-1", symbol: "AAPL", side: "buy", qty: "2", price: price, transaction_time: "2026-10-19T14:00:00Z")
    }
    func testReviewExpiryAndFutureTimestamp() {
        XCTAssertThrowsError(try ticket(date: Date().addingTimeInterval(-61)).validate())
        XCTAssertThrowsError(try ticket(date: Date().addingTimeInterval(1)).validate())
    }
    func testTicketBodyUsesExactDecimalAndDayLimit() throws {
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: ticket(price: Decimal(string: "1.23")!).body()) as? [String: String])
        XCTAssertEqual(body["limit_price"], "1.23")
        XCTAssertEqual(body["type"], "limit")
        XCTAssertEqual(body["time_in_force"], "day")
        XCTAssertEqual(body["client_order_id"], "crier-test")
        XCTAssertNil(body["position_intent"])
    }
    func testSubmissionSurvivesRestartAndCannotRepeat() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let first = try AlpacaJournal(file: url)
        try await first.begin(ticket())
        let second = try AlpacaJournal(file: url)
        do { try await second.begin(ticket()); XCTFail("Duplicate submission accepted") } catch {}
        let snapshot = await second.snapshot()
        XCTAssertEqual(snapshot.submissions.first?.state, "unknown")
    }
    func testDefinitiveRejectionPermitsFreshReviewButRetainsClientID() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let journal = try AlpacaJournal(file: url); let first = ticket()
        try await journal.begin(first)
        try await journal.reject(first, status: 422)
        do { try await journal.begin(first); XCTFail("Rejected ID must never be reused") } catch {}
        let fresh = AlpacaTicket(id: "crier-fresh", environment: .paper, accountID: "account-a", symbol: "AAPL", quantity: 1, limitPrice: 1, side: "buy", positionIntent: nil, multiplier: 1, reviewedAt: Date())
        try await journal.begin(fresh)
        let snapshot = await journal.snapshot(); XCTAssertEqual(snapshot.submissions.count, 2)
    }
    func testServerFailureDoesNotClearUnknown() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let journal = try AlpacaJournal(file: url); let first = ticket()
        try await journal.begin(first); try await journal.reject(first, status: 500)
        let snapshot = await journal.snapshot(); XCTAssertEqual(snapshot.submissions.first?.state, "unknown")
    }
    func testCorruptJournalFailsClosed() throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        try Data("not json".utf8).write(to: url)
        XCTAssertThrowsError(try AlpacaJournal(file: url))
    }
    func testOrderEvidenceMustMatchQuantityAndLimit() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let journal = try AlpacaJournal(file: url); let request = ticket()
        try await journal.begin(request)
        let wrong = AlpacaOrder(id: "broker-1", client_order_id: request.id, symbol: "AAPL", status: "new", qty: "3", limit_price: "2", filled_qty: "0", filled_avg_price: nil, side: "buy")
        do { try await journal.record(wrong, ticket: request); XCTFail("Wrong quantity accepted") } catch {}
        let snapshot = await journal.snapshot(); XCTAssertEqual(snapshot.submissions.first?.state, "unknown")
    }
    func testFillDeduplicationConflictAndAccountIsolation() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let journal = try AlpacaJournal(file: url)
        try await journal.ingest(fill(), environment: .paper, accountID: "a")
        try await journal.ingest(fill(), environment: .paper, accountID: "a")
        do { try await journal.ingest(fill(price: "3"), environment: .paper, accountID: "a"); XCTFail("Conflicting fill accepted") } catch {}
        let wrongAccount = try await journal.claim(environment: .paper, accountID: "b")
        let wrongEnvironment = try await journal.claim(environment: .live, accountID: "a")
        XCTAssertNil(wrongAccount); XCTAssertNil(wrongEnvironment)
        let snapshot = await journal.snapshot(); XCTAssertEqual(snapshot.deliveries.count, 1)
    }
    func testUncertainDeliveryNeverAutomaticallyRetriesAfterRestart() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let journal = try AlpacaJournal(file: url)
        try await journal.ingest(fill(), environment: .paper, accountID: "a")
        let claimed = try await journal.claim(environment: .paper, accountID: "a"); XCTAssertNotNil(claimed)
        let restarted = try AlpacaJournal(file: url)
        let retry = try await restarted.claim(environment: .paper, accountID: "a"); XCTAssertNil(retry)
    }
    func testRateLimitBlocksOtherPendingMessages() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let journal = try AlpacaJournal(file: url)
        try await journal.ingest(fill(), environment: .paper, accountID: "a")
        try await journal.ingest(fill(id: "fill-2"), environment: .paper, accountID: "a")
        let claimed = try await journal.claim(environment: .paper, accountID: "a")
        try await journal.rateLimited(XCTUnwrap(claimed).id, retryAfter: 60)
        let next = try await journal.claim(environment: .paper, accountID: "a"); XCTAssertNil(next)
        let later = try await journal.claim(environment: .paper, accountID: "a", now: Date().addingTimeInterval(61)); XCTAssertNotNil(later)
    }
    func testBaselinePersistsPerAccountAndEnvironment() async throws {
        let url = file(); defer { try? FileManager.default.removeItem(at: url) }
        let journal = try AlpacaJournal(file: url)
        try await journal.setBaseline("last-fill", environment: .paper, accountID: "a")
        let restarted = try AlpacaJournal(file: url)
        let saved = await restarted.baseline(environment: .paper, accountID: "a")
        let other = await restarted.baseline(environment: .live, accountID: "a")
        XCTAssertEqual(saved, "last-fill"); XCTAssertNil(other)
    }
    func testPaperAndLiveHostsAreFixed() {
        XCTAssertEqual(AlpacaEnvironment.paper.baseURL.host, "paper-api.alpaca.markets")
        XCTAssertEqual(AlpacaEnvironment.live.baseURL.host, "api.alpaca.markets")
    }
    func testRedirectDelegateRejectsRedirect() {
        let delegate = NoRedirectDelegate()
        let session = URLSession(configuration: .ephemeral)
        let original = URL(string: "https://paper-api.alpaca.markets/v2/account")!
        let task = session.dataTask(with: original)
        let response = HTTPURLResponse(url: original, statusCode: 302, httpVersion: nil, headerFields: nil)!
        var called = false
        delegate.urlSession(session, task: task, willPerformHTTPRedirection: response, newRequest: URLRequest(url: URL(string: "https://example.com")!)) { request in
            called = true; XCTAssertNil(request)
        }
        XCTAssertTrue(called); session.invalidateAndCancel()
    }
}

final class AlpacaMockURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            guard let handler = Self.handler else { throw URLError(.badServerResponse) }
            let (status, body) = try handler(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: body)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
final class AlpacaRESTTests: XCTestCase {
    private func api() -> AlpacaREST {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AlpacaMockURLProtocol.self]
        return AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test-key", secret: "test-secret"), session: URLSession(configuration: configuration))
    }
    override func tearDown() { AlpacaMockURLProtocol.handler = nil; super.tearDown() }
    func testAuthenticatedAccountReadUsesPaperEndpoint() async throws {
        AlpacaMockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.absoluteString, "https://paper-api.alpaca.markets/v2/account")
            XCTAssertEqual(request.value(forHTTPHeaderField: "APCA-API-KEY-ID"), "test-key")
            XCTAssertEqual(request.value(forHTTPHeaderField: "APCA-API-SECRET-KEY"), "test-secret")
            return (200, Data(#"{"id":"a","status":"ACTIVE","buying_power":"100","equity":"100","trading_blocked":false,"account_blocked":false}"#.utf8))
        }
        let account = try await api().account(); XCTAssertEqual(account.id, "a")
    }
    func testSubmissionTimeoutIsNotRetried() async throws {
        var posts = 0
        AlpacaMockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST"); posts += 1
            throw URLError(.timedOut)
        }
        let ticket = AlpacaTicket(id: "crier-test", environment: .paper, accountID: "a", symbol: "AAPL", quantity: 1, limitPrice: 1, side: "buy", positionIntent: nil, multiplier: 1, reviewedAt: Date())
        do { _ = try await api().submit(ticket); XCTFail("Expected timeout") } catch {}
        XCTAssertEqual(posts, 1)
    }
    func testHTTPFailureDoesNotLeakBrokerBody() async {
        AlpacaMockURLProtocol.handler = { _ in (403, Data("test-secret".utf8)) }
        do { _ = try await api().account(); XCTFail("Expected failure") }
        catch { XCTAssertFalse(error.localizedDescription.contains("test-secret")) }
    }
}

private actor ConfirmationTestGateway: LiveBrokerGateway {
    private(set) var submissions = 0
    func brokers() async throws -> [LiveBrokerDescriptor] { [] }
    func accounts(brokerId: String) async throws -> [LiveAccount] { [] }
    func positions(brokerId: String, accountId: String) async throws -> [LivePosition] { [] }
    func optionChain(brokerId: String, underlying: String, expiration: String) async throws -> [LiveOptionQuote] { [] }
    func preview(_ request: LiveOrderRequest) async throws -> LiveOrderPreview { throw LiveOrderError.unavailable }
    func submit(_ request: LiveOrderRequest) async throws -> LiveOrderReceipt {
        submissions += 1
        return LiveOrderReceipt(brokerId: request.brokerId, accountId: request.accountId, clientOrderId: request.clientOrderId, brokerOrderId: "broker", status: .accepted, receivedAt: Date())
    }
    func orderStatus(brokerId: String, accountId: String, clientOrderId: String) async throws -> LiveOrderReceipt { throw LiveOrderError.unavailable }
    func executions(brokerId: String, accountId: String, brokerOrderId: String) async throws -> [BrokerConfirmedExecution] { [] }
}
final class ConfirmationBindingTests: XCTestCase {
    private func request(quantity: Int) -> LiveOrderRequest {
        LiveOrderRequest(brokerId: "alpaca", accountId: "a", contract: LiveOptionContract(brokerContractId: "opt", underlying: "AAPL", expiration: "2026-12-18", strike: 200, right: "C", multiplier: 100), action: .buyToOpen, contracts: quantity, limitPrice: 2, clientOrderId: "same-id")
    }
    private func preview(date: Date = Date()) -> LiveOrderPreview {
        LiveOrderPreview(brokerId: "alpaca", accountId: "a", clientOrderId: "same-id", estimatedTotal: nil, estimatedFees: nil, buyingPowerEffect: nil, warnings: [], previewedAt: date, expiresAt: nil)
    }
    func testSameIDCannotChangeApprovedQuantity() async throws {
        let gate = LiveOrderConfirmationGate(); let gateway = ConfirmationTestGateway()
        try await gate.begin(request(quantity: 1), preview: preview())
        do { _ = try await gate.submitConfirmed(request(quantity: 2), via: gateway); XCTFail("Changed order was submitted") } catch {}
        let count = await gateway.submissions; XCTAssertEqual(count, 0)
    }
    func testReviewWithoutBrokerExpiryStillExpiresLocally() async throws {
        let gate = LiveOrderConfirmationGate(); let gateway = ConfirmationTestGateway()
        try await gate.begin(request(quantity: 1), preview: preview(date: Date().addingTimeInterval(-61)))
        do { _ = try await gate.submitConfirmed(request(quantity: 1), via: gateway); XCTFail("Stale review was submitted") } catch {}
        let count = await gateway.submissions; XCTAssertEqual(count, 0)
    }
}
