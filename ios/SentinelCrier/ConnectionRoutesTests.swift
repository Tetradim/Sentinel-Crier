import XCTest
@testable import SentinelCrier

@MainActor final class ConnectionRoutesTests: XCTestCase {
    func testRouteLimitAndMalformedBindingsFailClosed() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("routes.json")
        let registry = try ConnectionRouteRegistry(file: file)
        for _ in 0..<15 { try registry.add() }
        XCTAssertThrowsError(try registry.add())
        let malformed = "{\"routes\":[{\"id\":\"legacy\",\"name\":\"Original\",\"account\":\"a\"}],\"selected\":\"legacy\"}"
        try Data(malformed.utf8).write(to: file)
        XCTAssertThrowsError(try ConnectionRouteRegistry(file: file))
    }

    func testLegacyHistoryReservesOwnershipWithoutMovingJournal() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        var history = AlpacaJournal.State(); history.baselines["paper:original-account"] = "fill-cursor"
        let journal = folder.appendingPathComponent("alpaca-journal.json")
        let evidence = try JSONEncoder().encode(history); try evidence.write(to: journal)
        let registry = try ConnectionRouteRegistry(file: folder.appendingPathComponent("routes.json"))
        try registry.reserveLegacyHistory(support: folder)
        let route = try registry.add()
        XCTAssertThrowsError(try registry.bind(route.id, account: "original-account", environment: .paper))
        XCTAssertEqual(try Data(contentsOf: journal), evidence)
        try registry.bind("legacy", account: "original-account", environment: .paper)
    }

    func testLegacyCanRecoverEveryReservedAccountEnvironmentAfterRestart() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        var history = AlpacaJournal.State()
        history.baselines["paper:old-paper"] = "paper-cursor"
        history.baselines["live:old-live"] = "live-cursor"
        try JSONEncoder().encode(history).write(to: folder.appendingPathComponent("alpaca-journal.json"))
        let file = folder.appendingPathComponent("routes.json")
        let registry = try ConnectionRouteRegistry(file: file)
        try registry.reserveLegacyHistory(support: folder)
        try registry.bind("legacy", account: "old-paper", environment: .paper)
        let other = try registry.add()
        let restarted = try ConnectionRouteRegistry(file: file)
        try restarted.bind("legacy", account: "old-live", environment: .live)
        XCTAssertThrowsError(try restarted.bind(other.id, account: "old-paper", environment: .paper))
        XCTAssertThrowsError(try restarted.bind(other.id, account: "old-live", environment: .live))
        XCTAssertThrowsError(try restarted.bind("legacy", account: "unrelated", environment: .live))
    }

    func testDrainWaitsForCancelledOneShotThatHasAlreadyStarted() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: file) }
        let controller = try IntentController(file: file)
        var release: CheckedContinuation<Void, Never>?
        var started = false; var finished = false; var drained = false
        controller.enqueueWork {
            started = true
            await withCheckedContinuation { release = $0 }
            finished = true
        }
        while !started { await Task.yield() }
        controller.disconnect()
        let drain = Task { await controller.drainStoppedWork(); drained = true }
        for _ in 0..<10 { await Task.yield() }
        XCTAssertFalse(drained, "Cancellation alone must not report that an in-flight job has finished")
        release?.resume()
        await drain.value
        XCTAssertTrue(finished); XCTAssertTrue(drained)
    }
    func testAccountOwnershipSurvivesDisconnectAndRestart() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("routes.json")
        let registry = try ConnectionRouteRegistry(file: file)
        let second = try registry.add()
        try registry.bind("legacy", account: "account-one", environment: .paper)
        XCTAssertThrowsError(try registry.bind(second.id, account: "account-one", environment: .paper))
        let restarted = try ConnectionRouteRegistry(file: file)
        XCTAssertThrowsError(try restarted.bind(second.id, account: "account-one", environment: .paper))
        XCTAssertThrowsError(try restarted.bind("legacy", account: "other", environment: .paper))
        try restarted.bind(second.id, account: "account-one", environment: .live)
    }

    func testSelectionRetainsRouteIdentityAndIndependentPausedJournals() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let registry = try ConnectionRouteRegistry(file: folder.appendingPathComponent("routes.json"))
        let first = try registry.add(); let second = try registry.add()
        XCTAssertNotEqual(first.id, second.id)
        try registry.select(first.id)
        try registry.select(second.id)
        XCTAssertEqual(registry.routes.count, 3)
        let one = try IntentController(file: folder.appendingPathComponent("one.json"))
        let two = try IntentController(file: folder.appendingPathComponent("two.json"))
        var preferences = one.state.preferences; preferences.paused = true
        try one.settings(preferences)
        XCTAssertFalse(one.connected); XCTAssertFalse(two.connected)
        XCTAssertTrue(one.state.preferences.paused)
        XCTAssertTrue(two.state.trades.isEmpty)
    }

    func testSameEventInTwoAccountJournalsRetainsIndependentCursorsAndPause() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        var first = IntentState(); first.accountID = "one"; first.cursor = 3; first.received[event.event_id] = event
        var second = IntentState(); second.accountID = "two"; second.cursor = 8; second.received[event.event_id] = event
        let oneFile = folder.appendingPathComponent("one.json"), twoFile = folder.appendingPathComponent("two.json")
        try JSONEncoder().encode(first).write(to: oneFile)
        try JSONEncoder().encode(second).write(to: twoFile)
        let one = try IntentController(file: oneFile), two = try IntentController(file: twoFile)
        var changed = one.state.preferences; changed.paused = false; try one.settings(changed)
        XCTAssertFalse(one.state.preferences.paused); XCTAssertTrue(two.state.preferences.paused)
        let restoredOne = try IntentController(file: oneFile), restoredTwo = try IntentController(file: twoFile)
        XCTAssertEqual(restoredOne.state.cursor, 3); XCTAssertEqual(restoredTwo.state.cursor, 8)
        XCTAssertEqual(restoredOne.state.received[event.event_id], event)
        XCTAssertEqual(restoredTwo.state.received[event.event_id], event)
        XCTAssertFalse(restoredOne.connected); XCTAssertFalse(restoredTwo.connected)
    }
}
