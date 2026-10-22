import XCTest
@testable import SentinelCrier
final class IntentDiagnosticsTests: XCTestCase {
    private func observation() -> DiagnosticObservation {
        DiagnosticObservation(stage: "sender", observed_at: "2026-01-01T00:00:01Z", clock_offset_ms: 100, clock_uncertainty_ms: 10, clock_sampled_at: "2026-01-01T00:00:00Z", quote: DiagnosticQuote(source: "alpaca:opra", quote_timestamp: "2026-01-01T00:00:01.200Z", bid: "1.20", ask: "1.25", last: nil))
    }
    func testPremiumUsesSideAndAcceptsNearEventSnapshotAfterObservation() {
        var value = observation()
        XCTAssertEqual(IntentDiagnosticRecord.premium(value, sell: false), Decimal(string: "1.25"))
        XCTAssertEqual(IntentDiagnosticRecord.premium(value, sell: true), Decimal(string: "1.20"))
        value.quote?.quote_timestamp = "2026-01-01T00:00:07Z"
        XCTAssertNil(IntentDiagnosticRecord.premium(value, sell: false))
        value = observation(); value.quote?.source = "alpaca:indicative"
        XCTAssertNil(IntentDiagnosticRecord.premium(value, sell: false))
        value = observation(); value.quote_error = "Stale at fetch completion"
        XCTAssertNil(IntentDiagnosticRecord.premium(value, sell: false))
    }
    func testOldJournalStillDecodesAndDiagnosticsRoundTrip() throws {
        var state = IntentState()
        let legacy = try JSONEncoder().encode(state)
        XCTAssertNil(try JSONDecoder().decode(IntentState.self, from: legacy).diagnostics)
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "1")
        var record = IntentDiagnosticRecord(event: event, observation: observation())
        var receiver = observation(); receiver.stage = "receiver"; receiver.quote?.ask = "1.30"
        record.remote = [DiagnosticRemote(actor: "receiver-opaque", observation: receiver)]
        state.diagnostics = [event.event_id: record]
        let decoded = try JSONDecoder().decode(IntentState.self, from: JSONEncoder().encode(state))
        XCTAssertEqual(decoded.diagnostics?[event.event_id]?.event, event)
        XCTAssertTrue(record.premiumText.contains("0.05"))
        XCTAssertTrue(record.csv.contains("receiver-opaque"))
        record.remote[0].observation.quote?.source = "alpaca:iex"
        XCTAssertTrue(record.premiumText.contains("unavailable"))
    }
    func testExplicitOPRAAndPermissionFailureNeverFallsBack() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [DiagnosticQuoteProtocol.self]
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test", secret: "test"), session: session)
        do { _ = try await api.diagnosticQuote(symbol: "AAPL260116C00100000", option: true); XCTFail("403 quote must be unavailable") }
        catch { XCTAssertTrue(error.localizedDescription.contains("unavailable")) }
    }
    func testClockRejectsWallJumpAndComputesMidpoint() {
        let start = Date(timeIntervalSince1970: 100)
        XCTAssertNil(DiagnosticClock.make(start: start, end: start.addingTimeInterval(2), elapsed: 0.1, server: 100100))
        let sample = DiagnosticClock.make(start: start, end: start.addingTimeInterval(0.1), elapsed: 0.1, server: 100100)!
        XCTAssertEqual(sample.offset, 50, accuracy: 0.001)
        XCTAssertEqual(sample.uncertainty, 50, accuracy: 0.001)
        XCTAssertFalse(sample.fresh(at: start.addingTimeInterval(61)))
        let stable = DiagnosticClock.make(start: start, end: start.addingTimeInterval(0.1), elapsed: 0.1, server: 100100, uptime: 50)!
        XCTAssertTrue(stable.fresh(at: start.addingTimeInterval(1.1), uptime: 51))
        XCTAssertFalse(stable.fresh(at: start.addingTimeInterval(3.1), uptime: 51))
        XCTAssertNil(DiagnosticClock.make(start: start, end: start.addingTimeInterval(0.1), elapsed: 0.1, server: 999_999_999))
    }
    func testLatencyUsesBothOffsetsAndRejectsImpossibleNegative() {
        var sender = DiagnosticObservation(stage: "sender", observed_at: "2026-01-01T00:00:01.000Z", clock_offset_ms: 100, clock_uncertainty_ms: 10, clock_sampled_at: "2026-01-01T00:00:00Z")
        let receiver = DiagnosticObservation(stage: "receiver", observed_at: "2026-01-01T00:00:01.200Z", clock_offset_ms: 0, clock_uncertainty_ms: 10, clock_sampled_at: "2026-01-01T00:00:00Z")
        XCTAssertEqual(DiagnosticLatency.measure(sender, receiver)?.milliseconds ?? -1, 100, accuracy: 0.001)
        sender.clock_offset_ms = 1000
        XCTAssertNil(DiagnosticLatency.measure(sender, receiver))
        sender.clock_offset_ms = 0; sender.clock_sampled_at = "2025-12-31T23:58:00Z"
        XCTAssertNil(DiagnosticLatency.measure(sender, receiver))
    }
    func testCSVQuotesFormulaAndNewline() {
        XCTAssertEqual(IntentDiagnosticRecord.csvCell("=SUM(1,2)"), "\"'=SUM(1,2)\"")
        XCTAssertEqual(IntentDiagnosticRecord.csvCell("a\"b\nc"), "\"a\"\"b\nc\"")
    }
}
private final class DiagnosticQuoteProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        XCTAssertEqual(request.url?.host, "data.alpaca.markets")
        XCTAssertEqual(request.url?.path, "/v1beta1/options/quotes/latest")
        let items = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        XCTAssertEqual(items.first(where: { $0.name == "feed" })?.value, "opra")
        XCTAssertEqual(items.first(where: { $0.name == "symbols" })?.value, "AAPL260116C00100000")
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 403, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data("{}".utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
