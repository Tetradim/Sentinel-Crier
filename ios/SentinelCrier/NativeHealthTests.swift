import XCTest
@testable import SentinelCrier

@MainActor final class NativeHealthTests: XCTestCase {
    private final class Memory: NativeHealthStorage {
        var data: Data?
        var fail = false
        func read() throws -> Data? { data }
        func write(_ value: Data) throws { if fail { throw URLError(.cannotWriteToFile) }; data = value }
    }
    private final class Clock { var wall = Date(timeIntervalSince1970: 1000); var mono: TimeInterval = 10 }
    func testRestartReconnectAndLateTicketsNeverRestoreReadiness() {
        let memory = Memory(); let h = NativeHealth(storage: memory)
        let first = h.begin(scope: "account-a", active: [.broker]); h.record(first, .broker, .healthy, .verified)
        XCTAssertEqual(h.snapshot().first?.state, "healthy")
        let restarted = NativeHealth(storage: memory)
        XCTAssertEqual(restarted.snapshot().first?.state, "stopped"); XCTAssertNotNil(restarted.snapshot().first?.lastSuccess)
        h.stop(first); let next = h.begin(scope: "account-a", active: [.broker])
        h.record(first, .broker, .healthy, .verified); h.stop(first)
        XCTAssertEqual(h.snapshot().first?.state, "waiting")
        h.record(next, .broker, .healthy, .verified); XCTAssertEqual(h.snapshot().first?.state, "healthy")
    }
    func testScopeIsolationMonotonicFreshnessAndClockDiscontinuity() {
        let clock = Clock(); let h = NativeHealth(storage: Memory(), wall: { clock.wall }, mono: { clock.mono })
        let a = h.begin(scope: "a", active: [.broker]); h.record(a, .broker, .healthy, .verified)
        clock.wall += 61; clock.mono += 61
        XCTAssertEqual(h.snapshot().first?.state, "stale")
        clock.wall -= 3600
        XCTAssertEqual(h.snapshot().first?.state, "clock_changed"); XCTAssertEqual(h.snapshot().first?.age, 61)
        _ = h.begin(scope: "b", active: [.broker]); XCTAssertNil(h.snapshot().first?.lastSuccess)
        h.record(a, .broker, .blocked, .authenticationFailed)
        XCTAssertEqual(h.snapshot().first?.state, "waiting")
    }
    func testStorageFailureCannotStopCurrentObservationsOrOverwriteCorruptHistory() {
        let memory = Memory(); memory.fail = true
        let h = NativeHealth(storage: memory); let t = h.begin(scope: "a", active: [.broker])
        h.record(t, .broker, .healthy, .verified)
        XCTAssertTrue(h.unavailable); XCTAssertEqual(h.snapshot().first?.state, "healthy")
        let corrupt = Memory(); corrupt.data = Data("unreadable-history".utf8)
        let broken = NativeHealth(storage: corrupt); let next = broken.begin(scope: "b", active: [.broker])
        broken.record(next, .broker, .healthy, .verified)
        XCTAssertTrue(broken.unavailable); XCTAssertEqual(corrupt.data, Data("unreadable-history".utf8))
    }
    func testIdleIsNotAnAcknowledgementAndScopeContainsNoCredentials() {
        let h = NativeHealth(storage: Memory()); let t = h.begin(scope: "a", active: [.discord])
        h.record(t, .discord, .idle, .noWork)
        XCTAssertNil(h.snapshot().last?.lastSuccess); XCTAssertEqual(h.snapshot().last?.state, "idle")
        let first = NativeHealth.scope(["paper", "account", "private-token"])
        XCTAssertEqual(first.count, 64); XCTAssertFalse(first.contains("private"))
        XCTAssertNotEqual(first, NativeHealth.scope(["paper", "account", "other-token"]))
    }
}
