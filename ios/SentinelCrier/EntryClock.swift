import Foundation

/// Local continuity only; no inferred remote/relay clock correction.
final class EntryClock {
    struct Reading { let effective: Date; let wall: Date }
    private let wall: () -> Date; private let mono: () -> TimeInterval
    private let initialWall: Date; private let initialMono: TimeInterval
    private var high: Date
    private let lock = NSLock()
    init(wall: @escaping () -> Date = Date.init, mono: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.wall = wall; self.mono = mono; initialWall = wall(); initialMono = mono(); high = initialWall
    }
    func read() -> Reading? {
        lock.lock(); defer { lock.unlock() }
        let current = wall(); let m = mono(); let elapsed = m - initialMono
        guard current.timeIntervalSince1970.isFinite, initialWall.timeIntervalSince1970.isFinite,
              m.isFinite, initialMono.isFinite, elapsed >= 0,
              abs(current.timeIntervalSince(initialWall) - elapsed) <= 5 else { return nil }
        high = max(high, current, initialWall.addingTimeInterval(elapsed))
        return Reading(effective: high, wall: current)
    }
}

struct IntentDispatchRefused: Error {}
