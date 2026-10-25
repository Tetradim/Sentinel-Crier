import XCTest
@testable import SentinelCrier

final class EntryClockTests: XCTestCase {
    func testBackwardsSlewDoesNotExtendExpiryOrOpenFutureCreationGate() throws {
        var wall = Date(timeIntervalSince1970: 1000); var mono: TimeInterval = 10
        let clock = EntryClock(wall: { wall }, mono: { mono })
        wall -= 1; mono += 1
        let sample = try XCTUnwrap(clock.read())
        XCTAssertEqual(sample.effective, Date(timeIntervalSince1970: 1001))
        XCTAssertEqual(sample.wall, Date(timeIntervalSince1970: 999))
    }
    func testDiscontinuityAndInvalidMonotonicSamplesAreUncertain() {
        var wall = Date(timeIntervalSince1970: 1000); var mono: TimeInterval = 10
        let clock = EntryClock(wall: { wall }, mono: { mono })
        wall += 60; XCTAssertNil(clock.read())
        wall -= 60; mono = 9; XCTAssertNil(clock.read())
        mono = .infinity; XCTAssertNil(clock.read())
    }
    func testLocalNotSubmittedMarkerIsTerminalWithoutInventingABrokerOrder() throws {
        var mutation = IntentMutation(clientID: "known-no-post", eventID: "event", sell: false, quantity: 2)
        mutation.notSubmitted = true
        let decoded = try JSONDecoder().decode(IntentMutation.self, from: JSONEncoder().encode(mutation))
        XCTAssertTrue(decoded.notSubmitted == true); XCTAssertNil(decoded.order)
        let legacy = Data(#"{"clientID":"legacy","eventID":"event","sell":false,"quantity":2,"cancelUnknown":false}"#.utf8)
        XCTAssertNil(try JSONDecoder().decode(IntentMutation.self, from: legacy).notSubmitted)
    }
}
