import XCTest
@testable import SentinelCrier

final class PracticeGuideTests: XCTestCase {
    func testBundledGuideHasThreeReadOnlyPurposes() throws {
        let guide = try PracticeGuide.load()
        XCTAssertEqual(guide.journeys.map(\.id), ["alerts", "trade", "follow"])
        XCTAssertTrue(guide.notice.contains("optional"))
        XCTAssertTrue(guide.privacy.contains("API keys"))
        XCTAssertTrue(guide.journeys[0].steps.contains { $0.body.contains("suppressed baseline") })
    }
    func testUnknownPermissionAndActionFieldsAreRejected() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "customer-practice", withExtension: "json"))
        var root = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        root["enabled"] = true
        XCTAssertThrowsError(try PracticeGuide.parse(JSONSerialization.data(withJSONObject: root)))
        root.removeValue(forKey: "enabled")
        var journeys = root["journeys"] as! [[String: Any]]
        var steps = journeys[0]["steps"] as! [[String: Any]]
        steps[0]["action"] = "submit"; journeys[0]["steps"] = steps; root["journeys"] = journeys
        XCTAssertThrowsError(try PracticeGuide.parse(JSONSerialization.data(withJSONObject: root)))
    }
    func testBadVersionAndDuplicatePurposeAreRejected() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "customer-practice", withExtension: "json"))
        var root = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        root["version"] = true
        XCTAssertThrowsError(try PracticeGuide.parse(JSONSerialization.data(withJSONObject: root)))
        root["version"] = 1
        var journeys = root["journeys"] as! [[String: Any]]
        journeys[1]["id"] = "alerts"; root["journeys"] = journeys
        XCTAssertThrowsError(try PracticeGuide.parse(JSONSerialization.data(withJSONObject: root)))
    }
}
