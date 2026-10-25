import Foundation
import CryptoKit

enum HealthComponent: String, Codable, CaseIterable, Hashable, Sendable {
    case broker, fills, relaySend = "relay_send", relayReceive = "relay_receive", execution, discord
    var label: String {
        switch self {
        case .broker: return "Broker account"
        case .fills: return "Fill monitoring"
        case .relaySend: return "Trade sharing"
        case .relayReceive: return "Trade receiving"
        case .execution: return "Execution worker"
        case .discord: return "Discord delivery"
        }
    }
    var ttl: TimeInterval { self == .execution ? 15 : self == .fills ? 45 : 60 }
    var recovery: String {
        switch self {
        case .discord: return "Inspect delivery history before retrying uncertain messages."
        case .execution: return "Inspect broker orders and reconnect for reconciliation."
        case .relaySend, .relayReceive: return "Inspect the saved connection; reconnect explicitly."
        default: return "Reconnect the same account; saved journals remain."
        }
    }
}
enum HealthObservation: String, Codable, Sendable { case healthy, degraded, blocked, idle }
typealias NativeHealthObserver = @MainActor (HealthComponent, HealthObservation, HealthReason) -> Void
enum HealthReason: String, Codable, Sendable {
    case verified, checked, delivered, noWork = "no_work", connectionFailed = "connection_failed"
    case authenticationFailed = "authentication_failed", rejected, uncertain, rateLimited = "rate_limited"
    case invalidEvents = "invalid_events", reconciliationRequired = "reconciliation_required"
    case customerRequired = "customer_required", waitingRetry = "waiting_retry"
}
struct HealthRow: Identifiable {
    let component: HealthComponent; let state: String; let lastSuccess: Date?; let age: TimeInterval?; let reason: HealthReason?
    var id: String { component.rawValue }
    var recovery: String { state == "clock_changed" ? "Check the device clock, then reconnect." : component.recovery }
}
protocol NativeHealthStorage { func read() throws -> Data?; func write(_ value: Data) throws }
struct DefaultsHealthStorage: NativeHealthStorage {
    let defaults: UserDefaults
    func read() throws -> Data? {
        guard let value = defaults.object(forKey: "componentHealth.v1") else { return nil }
        guard let data = value as? Data else { throw URLError(.cannotDecodeContentData) }; return data
    }
    func write(_ value: Data) throws { defaults.set(value, forKey: "componentHealth.v1") }
}

/// Scoped, informational evidence. Persisted successes never restore active readiness.
@MainActor final class NativeHealth {
    struct Ticket: Equatable, Sendable { let scope: String; let generation: UUID }
    private struct Record: Codable { let generation: UUID; let state: HealthObservation; let reason: HealthReason; let success: Date? }
    private struct History: Codable { var version = 1; var latest = ""; var rows: [String: [String: Record]] = [:] }
    private struct Session { let ticket: Ticket; var active: Set<HealthComponent>; let wall: Date; let mono: TimeInterval }
    private struct Sample { let state: HealthObservation; let reason: HealthReason; let mono: TimeInterval; let success: TimeInterval? }
    private let storage: NativeHealthStorage
    private let wall: () -> Date; private let mono: () -> TimeInterval
    private var history = History(); private var readable = true
    private var sessions: [String: Session] = [:]; private var samples: [String: Sample] = [:]
    private(set) var unavailable = false
    init(storage: NativeHealthStorage, wall: @escaping () -> Date = Date.init, mono: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.storage = storage; self.wall = wall; self.mono = mono
        do {
            if let data = try storage.read() {
                let decoded = try JSONDecoder().decode(History.self, from: data)
                guard decoded.version == 1 else { throw URLError(.cannotDecodeContentData) }
                history = decoded
            }
        } catch { unavailable = true; readable = false }
    }
    static func scope(_ fields: [String]) -> String {
        let data = (try? JSONEncoder().encode(fields)) ?? Data()
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    private func persist() {
        guard readable else { return }
        do { try storage.write(JSONEncoder().encode(history)); unavailable = false }
        catch { unavailable = true }
    }
    func begin(scope: String, active: Set<HealthComponent>) -> Ticket {
        sessions = [:]; samples = [:]
        let ticket = Ticket(scope: scope, generation: UUID())
        sessions[scope] = Session(ticket: ticket, active: active, wall: wall(), mono: mono())
        history.latest = scope; persist(); return ticket
    }
    func setActive(_ ticket: Ticket, _ active: Set<HealthComponent>) {
        guard sessions[ticket.scope]?.ticket == ticket else { return }; sessions[ticket.scope]?.active = active
    }
    func stop(_ ticket: Ticket) { if sessions[ticket.scope]?.ticket == ticket { sessions[ticket.scope] = nil } }
    func record(_ ticket: Ticket, _ component: HealthComponent, _ state: HealthObservation, _ reason: HealthReason) {
        guard sessions[ticket.scope]?.ticket == ticket else { return }
        let key = ticket.scope + ":" + component.rawValue; let before = samples[key]; let now = mono()
        if let before, before.state == state, before.reason == reason, state != .healthy || now - before.mono < 2 { return }
        let old = history.rows[ticket.scope]?[component.rawValue]
        let value = Record(generation: ticket.generation, state: state, reason: reason, success: state == .healthy ? wall() : old?.success)
        history.rows[ticket.scope, default: [:]][component.rawValue] = value
        samples[key] = Sample(state: state, reason: reason, mono: now, success: state == .healthy ? now : before?.success)
        persist()
    }
    func snapshot(scope: String? = nil) -> [HealthRow] {
        let scope = scope ?? history.latest; let session = sessions[scope]; let now = mono()
        let drift = session.map { abs(wall().timeIntervalSince($0.wall) - (now - $0.mono)) > 5 } ?? false
        return HealthComponent.allCases.map { component in
            let r = history.rows[scope]?[component.rawValue]
            let age = samples[scope + ":" + component.rawValue]?.success.map { max(0, now - $0) }
            var state = "stopped"
            if let session, session.active.contains(component) { state = r?.generation == session.ticket.generation ? r!.state.rawValue : "waiting" }
            if state == "healthy" { state = drift ? "clock_changed" : (age == nil || age! >= component.ttl) ? "stale" : state }
            return HealthRow(component: component, state: state, lastSuccess: r?.success, age: age, reason: r?.reason)
        }
    }
}
