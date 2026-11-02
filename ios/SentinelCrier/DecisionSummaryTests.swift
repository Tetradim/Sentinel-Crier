import XCTest
@testable import SentinelCrier

final class DecisionSummaryTests: XCTestCase {
    func testSharedFixture() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "decision-summary", withExtension: "json"))
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let cases = try XCTUnwrap(root["cases"] as? [[String: Any]])
        for item in cases {
            let rows = try XCTUnwrap(item["timeline"] as? [[String: Any]])
            XCTAssertEqual(DecisionSummary.describe(rows, limit: item["limit"] as? Int ?? 8), item["expected"] as? [String], item["id"] as? String ?? "")
        }
    }
    func testAdapterAndPrivacy() {
        let steps = [DiagnosticStep(at: "now", stage: "reconciled", detail: "client=SECRET status=filled filled=99")]
        XCTAssertEqual(DecisionSummary.fromTimeline(steps), ["Broker evidence was refreshed; the recorded outcome is not confirmed."])
        let structured = [DiagnosticStep(at: "now", stage: "broker_reconciled", detail: "{\"status\":\"partially_filled\",\"id\":\"SECRET\"}")]
        XCTAssertEqual(DecisionSummary.fromTimeline(structured), ["The broker reports a partial fill; the full order is not confirmed filled."])
        for limit in [Int.min, 0, 8, Int.max] {
            let rows: [[String: Any]] = (0..<100).map { ["stage": $0 % 2 == 0 ? "sender" : "receiver", "details": ["secret": "SECRET"]] }
            let result = DecisionSummary.describe(rows, limit: limit)
            XCTAssertTrue((1...20).contains(result.count))
            XCTAssertFalse(result.joined().contains("SECRET"))
        }
    }
}
