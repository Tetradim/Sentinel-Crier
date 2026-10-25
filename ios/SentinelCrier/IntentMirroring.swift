import Foundation
import SwiftUI
import CryptoKit

struct IntentEvent: Codable, Equatable {
    var version = 1
    var event_id: String; var trade_id: String; var sequence: Int; var action: String
    var environment: AlpacaEnvironment; var symbol: String; var asset: String
    var quantity: Int; var limit_price: String; var created_at: String; var expires_at: String
    enum CodingKeys: String, CodingKey, CaseIterable {
        case version, event_id, trade_id, sequence, action, environment, symbol, asset, quantity, limit_price, created_at, expires_at
    }
    private struct AnyKey: CodingKey { var stringValue: String; var intValue: Int? { nil }; init?(stringValue: String) { self.stringValue = stringValue }; init?(intValue: Int) { return nil } }
    init(version: Int = 1, event_id: String, trade_id: String, sequence: Int, action: String, environment: AlpacaEnvironment, symbol: String, asset: String, quantity: Int, limit_price: String, created_at: String, expires_at: String) {
        self.version = version; self.event_id = event_id; self.trade_id = trade_id; self.sequence = sequence; self.action = action
        self.environment = environment; self.symbol = symbol; self.asset = asset; self.quantity = quantity
        self.limit_price = limit_price; self.created_at = created_at; self.expires_at = expires_at
    }
    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: AnyKey.self)
        guard Set(raw.allKeys.map(\.stringValue)) == Set(CodingKeys.allCases.map(\.rawValue)) else { throw AlpacaError.invalid("Unexpected or missing intent fields.") }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = try c.decode(Int.self, forKey: .version)
        event_id = try c.decode(String.self, forKey: .event_id); trade_id = try c.decode(String.self, forKey: .trade_id)
        sequence = try c.decode(Int.self, forKey: .sequence); action = try c.decode(String.self, forKey: .action)
        environment = try c.decode(AlpacaEnvironment.self, forKey: .environment)
        symbol = try c.decode(String.self, forKey: .symbol); asset = try c.decode(String.self, forKey: .asset)
        quantity = try c.decode(Int.self, forKey: .quantity); limit_price = try c.decode(String.self, forKey: .limit_price)
        created_at = try c.decode(String.self, forKey: .created_at); expires_at = try c.decode(String.self, forKey: .expires_at)
    }
    static func validOption(_ symbol: String) -> Bool {
        guard let pattern = try? NSRegularExpression(pattern: "^[A-Z]{1,6}([0-9]{6})[CP][0-9]{8}$"),
              let match = pattern.firstMatch(in: symbol, range: NSRange(symbol.startIndex..., in: symbol)),
              let range = Range(match.range(at: 1), in: symbol) else { return false }
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0); formatter.dateFormat = "yyMMdd"; formatter.isLenient = false
        let text = String(symbol[range])
        guard let date = formatter.date(from: text) else { return false }
        return formatter.string(from: date) == text
    }
    static func make(trade: String, sequence: Int, action: String, environment: AlpacaEnvironment, symbol: String, asset: String, quantity: Int, price: String) -> Self {
        let now = Date(); let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return Self(event_id: UUID().uuidString.lowercased(), trade_id: trade, sequence: sequence, action: action, environment: environment, symbol: symbol, asset: asset, quantity: quantity, limit_price: price, created_at: f.string(from: now), expires_at: f.string(from: now.addingTimeInterval(30)))
    }
    static func date(_ text: String) -> Date? {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: text) ?? ISO8601DateFormatter().date(from: text)
    }
    func validate() throws {
        guard version == 1, UUID(uuidString: event_id)?.uuidString.lowercased() == event_id,
              UUID(uuidString: trade_id)?.uuidString.lowercased() == trade_id, sequence > 0,
              ["enter", "replace", "cancel", "exit"].contains(action), ["option", "stock"].contains(asset),
              quantity > 0, quantity <= 1000, (asset != "option" || Self.validOption(symbol)), let price = Decimal(string: limit_price), price > 0, limit_price.range(of: "^[0-9]+(?:\\.[0-9]+)?$", options: .regularExpression) != nil,
              !symbol.isEmpty, symbol == symbol.uppercased(), symbol.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }),
              let created = Self.date(created_at), let expiry = Self.date(expires_at), expiry >= created,
              (!["enter", "replace"].contains(action) || expiry.timeIntervalSince(created) <= 30) else { throw AlpacaError.invalid("Invalid intent event.") }
    }
}
struct IntentPreferences: Codable {
    var mode = "exact_limit"; var maxSlippageBps = 100; var maxSlippageAmount = "0.02"
    var maxAgeSeconds = 10; var maxQuantity = 1000; var paused = true
    init() {}
    enum CodingKeys: String, CodingKey { case mode, maxSlippageBps, maxSlippageAmount, maxAgeSeconds, maxQuantity, paused }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "exact_limit"
        maxSlippageBps = try c.decodeIfPresent(Int.self, forKey: .maxSlippageBps) ?? 100
        maxSlippageAmount = try c.decodeIfPresent(String.self, forKey: .maxSlippageAmount) ?? "0.02"
        maxAgeSeconds = try c.decodeIfPresent(Int.self, forKey: .maxAgeSeconds) ?? 10
        maxQuantity = try c.decodeIfPresent(Int.self, forKey: .maxQuantity) ?? 1000
        paused = try c.decodeIfPresent(Bool.self, forKey: .paused) ?? true
        _ = try price("1", sell: false)
    }
    func price(_ source: String, sell: Bool) throws -> String? {
        guard ["exact_limit", "market", "bounded_limit"].contains(mode), let value = Decimal(string: source), value > 0,
              (0...1000).contains(maxSlippageBps), let absolute = Decimal(string: maxSlippageAmount), absolute >= 0,
              (1...30).contains(maxAgeSeconds), (1...1000).contains(maxQuantity) else { throw AlpacaError.invalid("Invalid local execution settings.") }
        if mode == "market" { return nil }
        if mode == "exact_limit" { return source }
        let allowance = min(value * Decimal(maxSlippageBps) / 10000, absolute)
        var adjusted = value + (sell ? -allowance : allowance); var rounded = Decimal()
        NSDecimalRound(&rounded, &adjusted, 2, sell ? .up : .down)
        guard rounded > 0 else { throw AlpacaError.invalid("Bounded price must be positive.") }
        return NSDecimalNumber(decimal: rounded).stringValue
    }
}
struct IntentMutation: Codable {
    var clientID: String; var eventID: String; var sell: Bool; var quantity: Int
    var order: AlpacaOrder?; var cancelUnknown = false
    var cancelAttemptedAt: Date?
    // Call only after validating a fresh broker lookup for this mutation.
    func mayRetryCancellation(now: Date) -> Bool {
        guard let order, !["filled", "canceled", "expired", "rejected", "replaced", "pending_cancel"].contains(order.status) else { return false }
        return cancelAttemptedAt.map { now.timeIntervalSince($0) >= 5 } ?? true
    }
    func validate(_ incoming: AlpacaOrder, symbol: String) throws {
        guard incoming.client_order_id == clientID, incoming.symbol == symbol,
              incoming.side == (sell ? "sell" : "buy"), !incoming.id.isEmpty,
              order == nil || order?.id == incoming.id,
              incoming.qty.flatMap({ Decimal(string: $0) }) == Decimal(quantity),
              let filled = Decimal(string: incoming.filled_qty), filled >= 0, filled <= Decimal(quantity),
              filled >= (Decimal(string: order?.filled_qty ?? "0") ?? 0),
              filled == Decimal(NSDecimalNumber(decimal: filled).intValue) else { throw AlpacaError.invalid("Broker order identity or cumulative fill mismatch.") }
    }
}
struct IntentTrade: Codable {
    var desired: IntentEvent?; var invalidated = false; var completed: String?
    var entrySkipped: Bool?
    var mutations: [IntentMutation] = []
    mutating func accept(_ e: IntentEvent, paused: Bool = false) throws {
        try e.validate()
        if let old = desired {
            guard old.symbol == e.symbol, old.asset == e.asset, old.environment == e.environment else { throw AlpacaError.invalid("Trade identity changed.") }
            if e.sequence == old.sequence && e != old { throw AlpacaError.invalid("Conflicting trade sequence.") }
        }
        if e.action == "cancel" || e.action == "exit" { invalidated = true }
        if paused && ["enter", "replace"].contains(e.action) { entrySkipped = true }
        if e.sequence > (desired?.sequence ?? 0) { desired = e }
    }
    var owned: Int {
        max(0, mutations.reduce(0) { $0 + ($1.sell ? -1 : 1) * (Int(Decimal(string: $1.order?.filled_qty ?? "0").map { NSDecimalNumber(decimal: $0).intValue } ?? 0)) })
    }
    func sold(for eventID: String) -> Int {
        mutations.filter { $0.sell && $0.eventID == eventID }.reduce(0) {
            $0 + NSDecimalNumber(decimal: Decimal(string: $1.order?.filled_qty ?? "0") ?? 0).intValue
        }
    }
}
struct IntentState: Codable {
    var cursor = 0; var accountID = ""; var pairingID = ""; var trades: [String: IntentTrade] = [:]
    var outgoing: [IntentEvent] = []; var received: [String: IntentEvent] = [:]
    var diagnostics: [String: IntentDiagnosticRecord]?
    struct Quarantine: Codable { var cursor: Int; var reason: String; var record: String }
    var quarantine: [Quarantine]?
    var unresolved: [String] {
        trades.compactMap { id, trade in
            let working = trade.mutations.contains { $0.order.map { !["filled", "canceled", "expired", "rejected", "replaced"].contains($0.status) } ?? true }
            return working || trade.owned > 0 || (trade.desired != nil && trade.completed != trade.desired?.event_id && !trade.invalidated) ? id : nil
        }.sorted()
    }
    // Validate one envelope at a time. Quarantine and cursor are committed with
    // valid records, so a poison event cannot block later channel instructions.
    mutating func ingestPage(_ data: Data, environment: AlpacaEnvironment) throws -> [IntentEvent] {
        guard let page = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let records = page["events"] as? [[String: Any]] else { throw AlpacaError.invalid("Invalid relay page.") }
        var accepted: [IntentEvent] = []
        for record in records {
            guard let position = record["cursor"] as? Int, position > 0 else { throw AlpacaError.invalid("Relay record has no valid cursor; reconnect without discarding its position.") }
            if position <= cursor { continue }
            let raw = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
            do {
                guard let object = record["event"] else { throw AlpacaError.invalid("Missing intent event.") }
                let event = try JSONDecoder().decode(IntentEvent.self, from: JSONSerialization.data(withJSONObject: object, options: [.fragmentsAllowed]))
                try event.validate()
                guard event.environment == environment else { throw AlpacaError.invalid("Relay environment mismatch.") }
                if let previous = received[event.event_id], previous != event { throw AlpacaError.invalid("Event identity conflict.") }
                var trade = trades[event.trade_id] ?? IntentTrade()
                try trade.accept(event, paused: preferences.paused)
                trades[event.trade_id] = trade; received[event.event_id] = event; accepted.append(event)
            } catch {
                if quarantine == nil { quarantine = [] }
                quarantine?.append(Quarantine(cursor: position, reason: String(describing: error), record: String(decoding: raw, as: UTF8.self)))
            }
            cursor = position
        }
        return accepted
    }
    var preferences = IntentPreferences()
    mutating func discardSupersededEntries() {
        let invalidations = outgoing.filter { ["cancel", "exit"].contains($0.action) }
        outgoing.removeAll { e in ["enter", "replace"].contains(e.action) && invalidations.contains { $0.trade_id == e.trade_id && $0.sequence > e.sequence } }
    }
}
struct IntentPairing: Codable {
    var url: URL; var token: String; var environment: AlpacaEnvironment; var role: String
    static func decode(_ text: String) throws -> Self {
        let p = try JSONDecoder().decode(Self.self, from: Data(text.utf8))
        _ = try QuickConnection.origin(p.url.absoluteString)
        guard ["host", "follower"].contains(p.role), p.token.count >= 32 else { throw AlpacaError.invalid("Use an HTTPS intent pairing with host or follower role.") }
        return p
    }
    var fingerprint: String { SHA256.hash(data: Data((url.absoluteString + token + role).utf8)).map { String(format: "%02x", $0) }.joined() }
    static func load() throws -> Self? {
        guard let data = UserDefaults.standard.data(forKey: "intent-pairing-metadata") else { return nil }
        var p = try JSONDecoder().decode(Self.self, from: data)
        let secret = try AlpacaKeychain.loadPairing(); p.token = secret
        return try decode(String(decoding: JSONEncoder().encode(p), as: UTF8.self))
    }
    func save() throws {
        try AlpacaKeychain.savePairing(token)
        var metadata = self; metadata.token = ""
        UserDefaults.standard.set(try JSONEncoder().encode(metadata), forKey: "intent-pairing-metadata")
    }
}
@MainActor final class IntentController: ObservableObject {
    @Published private(set) var state: IntentState
    @Published private(set) var message = "Intent mirroring disconnected."
    var onHealth: NativeHealthObserver?
    private let file: URL
    private let now: () -> Date
    private let session: URLSession
    private var api: AlpacaREST?; private var pair: IntentPairing?
    private var receiver: Task<Void, Never>?; private var worker: Task<Void, Never>?; private var transmitter: Task<Void, Never>?
    private var diagnosticWorker: Task<Void, Never>?
    private var diagnosticClock: DiagnosticClock?
    private var diagnosticSession = UUID()
    private var quoteCaptures = Set<String>()
    private var processing = false; private var publishing = false
    init(file: URL, now: @escaping () -> Date = Date.init, session: URLSession = CrierHTTPSession.shared) throws {
        self.file = file
        self.now = now
        self.session = session
        state = FileManager.default.fileExists(atPath: file.path) ? try JSONDecoder().decode(IntentState.self, from: Data(contentsOf: file)) : IntentState()
    }
    static func local() throws -> IntentController {
        let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("SentinelCrier")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return try IntentController(file: folder.appendingPathComponent("intent-v1.json"))
    }
    private func commit(_ change: (inout IntentState) throws -> Void) throws {
        var next = state; try change(&next)
        try JSONEncoder().encode(next).write(to: file, options: [.atomic, .completeFileProtection])
        state = next
    }
    func settings(_ p: IntentPreferences) throws { _ = try p.price("1", sell: false); try commit { $0.preferences = p } }
    func validateIdentity(account: String, environment: AlpacaEnvironment, pairing: IntentPairing? = nil) throws {
        guard let pair = try pairing ?? IntentPairing.load() else { return }
        guard pair.environment == environment else { throw AlpacaError.invalid("Pairing environment differs from broker.") }
        guard state.accountID.isEmpty || (state.accountID == account && state.pairingID == pair.fingerprint) else { throw AlpacaError.invalid("Intent journal is pinned to its original account and pairing. Recover its trades before changing channels.") }
    }
    func connect(api: AlpacaREST, account: String, pairing: IntentPairing? = nil, startWorkers: Bool = true) throws {
        guard let pair = try pairing ?? IntentPairing.load() else { return }
        try validateIdentity(account: account, environment: api.environment, pairing: pair)
        try commit { $0.accountID = account; $0.pairingID = pair.fingerprint }
        if self.api !== api { self.api?.invalidate() }
        self.api = api; self.pair = pair
        diagnosticClock = nil
        diagnosticSession = UUID()
        receiver?.cancel(); worker?.cancel(); transmitter?.cancel()
        diagnosticWorker?.cancel()
        guard startWorkers else { return }
        if pair.role == "follower" { receiver = Task { await receiveLoop() } }
        transmitter = Task { while !Task.isCancelled { await publish(); try? await Task.sleep(nanoseconds: 500_000_000) } }
        worker = Task { while !Task.isCancelled { await process(); try? await Task.sleep(nanoseconds: 2_000_000_000) } }
        diagnosticWorker?.cancel()
        diagnosticWorker = Task { while !Task.isCancelled { await syncDiagnostics(); try? await Task.sleep(nanoseconds: 5_000_000_000) } }
        message = "\(pair.role.capitalized) connected. Keep Crier open for delivery."
    }
    func disconnect() { message = "Disconnected; execution journals retained."; diagnosticSession = UUID(); diagnosticWorker?.cancel(); diagnosticWorker = nil; diagnosticClock = nil; receiver?.cancel(); worker?.cancel(); transmitter?.cancel(); receiver = nil; worker = nil; transmitter = nil; api?.invalidate(); api = nil; pair = nil }
    func archiveResolvedChannel() throws {
        guard !processing, !publishing, api == nil else { throw AlpacaError.invalid("Disconnect before changing channel.") }
        guard state.unresolved.isEmpty, state.outgoing.isEmpty else { throw AlpacaError.invalid("Resolve tracked holdings, pending orders and relay outbox before changing channel. Reconnect to the original account to recover.") }
        let archive = file.deletingLastPathComponent().appendingPathComponent("intent-archive-" + UUID().uuidString + ".json")
        try JSONEncoder().encode(state).write(to: archive, options: [.atomic, .completeFileProtection])
        try commit { $0 = IntentState() }
        UserDefaults.standard.removeObject(forKey: "intent-pairing-metadata")
    }
    var hosting: Bool { pair?.role == "host" }
    var connected: Bool { api != nil && pair != nil }
    func host(symbol: String, asset: String, quantity: Int, price: String, tradeID: String? = nil, action: String = "enter") throws -> String {
        guard let pair, hosting else { throw AlpacaError.invalid("Connect an intent host pairing first.") }
        let id = tradeID ?? UUID().uuidString.lowercased()
        let e = IntentEvent.make(trade: id, sequence: (state.trades[id]?.desired?.sequence ?? 0) + 1, action: action, environment: pair.environment, symbol: symbol, asset: asset, quantity: quantity, price: price)
        try commit { s in var t = s.trades[id] ?? IntentTrade(); try t.accept(e); s.trades[id] = t; s.outgoing.append(e) }
        beginDiagnostic(e, stage: "sender", observed: IntentEvent.date(e.created_at) ?? Date())
        Task { await publish() }; Task { await process() }
        return id
    }
    private func relay(_ query: String = "", body: Data? = nil, resource: String = "events") async throws -> Data {
        guard let pair else { throw AlpacaError.invalid("Disconnected.") }
        var request = URLRequest(url: URL(string: pair.url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/sync/" + resource + query)!)
        request.httpMethod = body == nil ? "GET" : "POST"; request.httpBody = body; request.timeoutInterval = 30
        request.setValue("Bearer " + pair.token, forHTTPHeaderField: "Authorization"); request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw AlpacaError.invalid("Relay returned an invalid response.") }
        if [401, 403].contains(response.statusCode) {
            disconnect()
            message = "Relay authentication failed or receiver revoked. Reconnect with valid credentials; journal retained."
            throw AlpacaError.invalid(message)
        }
        guard (200..<300).contains(response.statusCode) else { throw AlpacaError.http(response.statusCode) }
        return data
    }
    func publish() async {
        guard hosting, !publishing else { return }; publishing = true; defer { publishing = false }
        let observed = onHealth
        if state.outgoing.isEmpty { observed?(.relaySend, .idle, .noWork) }
        do {
            while !Task.isCancelled {
                if !state.outgoing.isEmpty { try commit { $0.discardSupersededEntries() } }
                guard let e = state.outgoing.first(where: { ["cancel", "exit"].contains($0.action) }) ?? state.outgoing.first else { break }
                do {
                    _ = try await relay(body: JSONEncoder().encode(e))
                    diagnosticStep(e.event_id, "relay_accepted", "Relay durably accepted event")
                    try commit { $0.outgoing.removeAll { $0.event_id == e.event_id } }
                    observed?(.relaySend, .healthy, .delivered)
                } catch AlpacaError.http(let status) where [400, 409, 422].contains(status) {
                    let record = String(decoding: try JSONEncoder().encode(e), as: UTF8.self)
                    try commit {
                        if $0.quarantine == nil { $0.quarantine = [] }
                        $0.quarantine?.append(IntentState.Quarantine(cursor: 0, reason: "Relay rejected outgoing event HTTP \(status)", record: record))
                        $0.outgoing.removeAll { $0.event_id == e.event_id }
                    }
                    diagnosticStep(e.event_id, "relay_rejected", "HTTP \(status); original revision retained in quarantine")
                    if ["enter", "replace"].contains(e.action), state.trades[e.trade_id]?.desired?.event_id == e.event_id {
                        _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: e.trade_id, action: "cancel")
                    }
                    message = "Relay rejected a revision; inspect quarantine and reconcile the tracked trade."
                    observed?(.relaySend, .blocked, .rejected)
                }
            }
        }
        catch { observed?(.relaySend, .degraded, .connectionFailed); message = "Intent outbox pending: \(error.localizedDescription)" }
    }
    func receiveOnce() async throws {
        let observed = onHealth; let previousQuarantine = state.quarantine?.count ?? 0
        let data = try await relay("?after=\(state.cursor)&wait=20")
        try Task.checkCancellation()
        guard let environment = pair?.environment else { return }
        var accepted: [IntentEvent] = []
        try commit { accepted = try $0.ingestPage(data, environment: environment) }
        for event in accepted { beginDiagnostic(event, stage: "receiver", observed: Date()) }
        let invalid = (state.quarantine?.count ?? 0) > previousQuarantine
        observed?(.relayReceive, invalid ? .degraded : .healthy, invalid ? .invalidEvents : .checked)
        message = "Receiver connected â€¢ cursor \(state.cursor) â€¢ \(state.quarantine?.count ?? 0) quarantined"
    }
    private func receiveLoop() async {
        while !Task.isCancelled {
            let observed = onHealth
            do {
                try await receiveOnce()
                Task { await process() }
            } catch {
                if Task.isCancelled { return }
                observed?(.relayReceive, .degraded, .connectionFailed)
                message = "Reconnect needed: " + error.localizedDescription
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }
    func reconcileBeforeResume() async throws {
        guard let api else { return }
        let observed = onHealth
        let account = try await api.account()
        guard account.id == state.accountID, account.status == "ACTIVE", !account.account_blocked, !account.trading_blocked else { throw AlpacaError.invalid("Reconnect account is changed or blocked.") }
        observed?(.broker, .healthy, .verified)
        for id in state.trades.keys.sorted() {
            guard let trade = state.trades[id], let event = trade.desired else { continue }
            for index in trade.mutations.indices {
                let mutation = trade.mutations[index]
                if let order = mutation.order, terminal(order) { continue }
                let order = try await api.order(clientID: mutation.clientID)
                try mutation.validate(order, symbol: event.symbol)
                try Task.checkCancellation()
                guard self.api === api, pair != nil else { throw AlpacaError.invalid("Reconnect interrupted.") }
                try commit { $0.trades[id]!.mutations[index].order = order }
            }
        }
    }
    func process() async {
        guard !processing, let api else { return }; processing = true; defer { processing = false }
        let observed = onHealth; var needsReconciliation = false
        for id in Array(state.trades.keys) {
            do { try Task.checkCancellation(); try await execute(id, api: api, observe: observed) }
            catch { needsReconciliation = true; if let event = state.trades[id]?.desired { diagnosticStep(event.event_id, "execution_pending", error.localizedDescription) }; message = "Trade \(id.prefix(8)): \(error.localizedDescription)" }
        }
        needsReconciliation = needsReconciliation || state.trades.values.contains { $0.mutations.contains { $0.order == nil || $0.cancelUnknown } }
        observed?(.execution, needsReconciliation ? .blocked : .healthy, needsReconciliation ? .reconciliationRequired : .checked)
    }
    private func diagnosticStep(_ eventID: String, _ stage: String, _ detail: String, at: Date = Date()) {
        try? commit { state in
            guard var record = state.diagnostics?[eventID] else { return }
            if record.timeline.last?.stage == stage && record.timeline.last?.detail == detail { return }
            record.timeline.append(DiagnosticStep(at: IntentDiagnosticRecord.timestamp(at), stage: stage, detail: detail))
            state.diagnostics?[eventID] = record
        }
    }
    private func beginDiagnostic(_ event: IntentEvent, stage: String, observed: Date) {
        guard state.diagnostics?[event.event_id] == nil else { return }
        let clock = diagnosticClock.flatMap { $0.fresh(at: observed) ? $0 : nil }
        let observation = DiagnosticObservation(stage: stage, observed_at: IntentDiagnosticRecord.timestamp(observed), clock_offset_ms: clock?.offset, clock_uncertainty_ms: clock?.uncertainty, clock_sampled_at: clock.map { IntentDiagnosticRecord.timestamp($0.sampled) })
        try? commit { state in
            if state.diagnostics == nil { state.diagnostics = [:] }
            state.diagnostics?[event.event_id] = IntentDiagnosticRecord(event: event, observation: observation, timeline: [DiagnosticStep(at: observation.observed_at, stage: stage == "sender" ? "journaled" : "received", detail: "Exact event revision persisted")])
        }
        guard let api else { return }
        guard quoteCaptures.count < 8 else {
            try? commit { $0.diagnostics?[event.event_id]?.observation.quote_error = "Quote capture capacity reached"; $0.diagnostics?[event.event_id]?.quoteComplete = true }
            return
        }
        quoteCaptures.insert(event.event_id)
        let session = diagnosticSession
        // Independent task: neither quote capture nor diagnostics gates broker dispatch.
        Task {
            defer { quoteCaptures.remove(event.event_id) }
            do {
                let quote = try await api.diagnosticQuote(symbol: event.symbol, option: event.asset == "option")
                guard self.api === api, self.pair != nil, diagnosticSession == session else { return }
                let finished = Date()
                let clock = diagnosticClock.flatMap { $0.fresh(at: finished) ? $0 : nil }
                let age = IntentEvent.date(quote.quote_timestamp).map { finished.addingTimeInterval((clock?.offset ?? 0) / 1000).timeIntervalSince($0) }
                let quoteError = clock == nil ? "Quote freshness unverified: clock unavailable" : ((age.map { (0...5).contains($0) } ?? false) ? nil : "Stale or future quote; excluded from comparison")
                try? commit {
                    guard $0.diagnostics?[event.event_id]?.quoteComplete == false else { return }
                    $0.diagnostics?[event.event_id]?.observation.quote = quote
                    $0.diagnostics?[event.event_id]?.observation.quote_error = quoteError
                    $0.diagnostics?[event.event_id]?.quoteComplete = true
                }
            } catch {
                guard self.api === api, self.pair != nil, diagnosticSession == session else { return }
                try? commit {
                    guard $0.diagnostics?[event.event_id]?.quoteComplete == false else { return }
                    $0.diagnostics?[event.event_id]?.observation.quote_error = "Alpaca quote unavailable (permission, transport, or malformed response)"
                    $0.diagnostics?[event.event_id]?.quoteComplete = true
                }
            }
        }
    }
    private func syncDiagnostics() async {
        guard let activePair = pair else { return }
        let session = diagnosticSession
        if diagnosticClock?.fresh(at: Date()) != true {
            let start = Date(), uptime = ProcessInfo.processInfo.systemUptime
            struct ClockResponse: Decodable { var server_time_ms: Double }
            if let data = try? await relay(resource: "clock"), let response = try? JSONDecoder().decode(ClockResponse.self, from: data) {
                guard !Task.isCancelled, diagnosticSession == session, pair?.fingerprint == activePair.fingerprint else { return }
                diagnosticClock = DiagnosticClock.make(start: start, end: Date(), elapsed: ProcessInfo.processInfo.systemUptime - uptime, server: response.server_time_ms)
            }
        }
        let pending = (state.diagnostics ?? [:]).values.filter { !$0.quoteComplete || (!$0.uploaded && $0.attempts < 6) || $0.fetchAttempts < 12 }
            .sorted { $0.event.created_at < $1.event.created_at }.prefix(20)
        for id in pending.map({ $0.event.event_id }) {
            guard !Task.isCancelled, diagnosticSession == session, pair?.fingerprint == activePair.fingerprint, let record = state.diagnostics?[id] else { return }
            guard !state.outgoing.contains(where: { $0.event_id == id }) else { continue }
            // Wait for capture; after restart a missing capture becomes explicit unavailable.
            if !record.quoteComplete {
                if Date().timeIntervalSince(IntentEvent.date(record.observation.observed_at) ?? Date()) > 20 {
                    try? commit { $0.diagnostics?[id]?.observation.quote_error = "Quote capture interrupted"; $0.diagnostics?[id]?.quoteComplete = true }
                }
                continue
            }
            if !record.uploaded && record.attempts < 6 {
                struct Upload: Encodable { var event_id: String; var observation: DiagnosticObservation }
                try? commit { $0.diagnostics?[id]?.attempts += 1 }
                do {
                    _ = try await relay(body: JSONEncoder().encode(Upload(event_id: id, observation: record.observation)), resource: "diagnostics")
                    guard !Task.isCancelled, diagnosticSession == session else { return }
                    try? commit { $0.diagnostics?[id]?.uploaded = true }
                } catch {
                    guard !Task.isCancelled, diagnosticSession == session else { return }
                    diagnosticStep(id, "diagnostics_pending", "Relay diagnostics upload pending")
                }
            }
            guard record.fetchAttempts < 12 else { continue }
            try? commit { $0.diagnostics?[id]?.fetchAttempts += 1 }
            struct Download: Decodable { var observations: [DiagnosticRemote] }
            if let data = try? await relay("?event_id=" + id, resource: "diagnostics"), let response = try? JSONDecoder().decode(Download.self, from: data) {
                guard !Task.isCancelled, diagnosticSession == session else { return }
                try? commit { $0.diagnostics?[id]?.remote = response.observations }
            }
        }
    }
    private func terminal(_ order: AlpacaOrder) -> Bool { ["filled", "canceled", "expired", "rejected", "replaced"].contains(order.status) }
    private func execute(_ id: String, api: AlpacaREST, observe: NativeHealthObserver? = nil) async throws {
        guard let initial = state.trades[id], let desired = initial.desired else { return }
        if initial.completed == desired.event_id && initial.mutations.allSatisfy({ $0.order.map(terminal) ?? false }) { return }
        let account = try await api.account()
        guard account.id == state.accountID, desired.environment == api.environment, account.status == "ACTIVE", !account.account_blocked, !account.trading_blocked else { throw AlpacaError.invalid("Account is changed or blocked.") }
        observe?(.broker, .healthy, .verified)
        // Every unknown POST is reconciled; a 404 never permits another POST.
        for index in initial.mutations.indices {
            let m = state.trades[id]!.mutations[index]
            if let old = m.order, terminal(old) { continue }
            let order = try await api.order(clientID: m.clientID)
            try m.validate(order, symbol: desired.symbol)
            diagnosticStep(m.eventID, "reconciled", "client=\(m.clientID) broker=\(order.id) status=\(order.status) filled=\(order.filled_qty) average=\(order.filled_avg_price ?? "unavailable")")
            try commit { $0.trades[id]!.mutations[index].order = order }
            if order.status == "rejected", hosting, state.trades[id]?.desired?.action != "cancel" {
                _ = try host(symbol: desired.symbol, asset: desired.asset, quantity: desired.quantity, price: desired.limit_price, tradeID: id, action: "cancel")
            }
        }
        guard let trade = state.trades[id], let e = trade.desired else { return }
        let revise = e.action != "enter" || trade.invalidated
        if revise {
            for index in trade.mutations.indices {
                let m = state.trades[id]!.mutations[index]
                if let order = m.order, !terminal(order), m.eventID != e.event_id || e.action == "cancel" || e.action == "exit" && !m.sell {
                    try Task.checkCancellation()
                    guard self.api === api, pair != nil else { return }
                    let attemptTime = now()
                    if m.mayRetryCancellation(now: attemptTime) {
                        try commit {
                            $0.trades[id]!.mutations[index].cancelUnknown = true
                            $0.trades[id]!.mutations[index].cancelAttemptedAt = attemptTime
                        }
                        diagnosticStep(e.event_id, "cancel_dispatch", "broker=\(order.id)")
                        try await api.cancel(orderID: order.id)
                    }
                    return // Wait for terminal broker status, including racing fills.
                }
            }
        }
        if e.action == "cancel" || (trade.invalidated && e.action != "exit") {
            diagnosticStep(e.event_id, "entry_invalidated", "Entry remainder canceled or superseded; tracked fills retained")
            return
        }
        if trade.completed == e.event_id { return }
        let sell = e.action == "exit"
        let existing = trade.mutations.filter { $0.eventID == e.event_id }
        if !sell && !existing.isEmpty { return }
        if sell && existing.contains(where: { $0.order?.status != "filled" }) { message = "Exit is working or needs broker reconciliation; no duplicate sell submitted."; return }
        if !sell {
            let currentTime = now()
            if let created = IntentEvent.date(e.created_at), created > currentTime {
                diagnosticStep(e.event_id, "entry_deferred", "Waiting for event creation time")
                return
            }
            guard trade.entrySkipped != true, hosting || !state.preferences.paused,
                  let created = IntentEvent.date(e.created_at), let expires = IntentEvent.date(e.expires_at), expires > currentTime,
                  currentTime.timeIntervalSince(created) <= Double(hosting ? 30 : state.preferences.maxAgeSeconds),
                  e.quantity <= (hosting ? 1000 : state.preferences.maxQuantity) else {
                diagnosticStep(e.event_id, "entry_skipped", "Paused, expired, or outside local quantity/age limits")
                try commit { $0.trades[id]!.completed = e.event_id }; return
            }
        }
        let soldForRevision = trade.sold(for: e.event_id)
        var quantity = sell ? min(max(0, e.quantity - soldForRevision), trade.owned) : max(0, e.quantity - trade.owned)
        let desiredQuantity = quantity
        if sell {
            let positions = try await api.positions()
            let available = positions.first(where: { $0.symbol == e.symbol }).flatMap { Decimal(string: $0.qty_available ?? "0") } ?? 0
            quantity = min(quantity, max(0, NSDecimalNumber(decimal: available).intValue))
        }
        if sell && desiredQuantity > 0 && quantity == 0 { message = "Waiting for tracked holdings to become available."; return }
        guard quantity > 0 else { try commit { $0.trades[id]!.completed = e.event_id }; return }
        let preference = hosting ? IntentPreferences() : state.preferences
        let price = try preference.price(e.limit_price, sell: sell)
        // There must be no await between this revision check, durable unknown, and dispatch.
        guard state.trades[id]?.desired?.event_id == e.event_id, sell || state.trades[id]?.invalidated == false else { return }
        try Task.checkCancellation()
        guard self.api === api, pair != nil else { return }
        let clientID = "si-" + e.event_id + (sell ? "-s\(existing.count)" : "-b")
        let mutation = IntentMutation(clientID: clientID, eventID: e.event_id, sell: sell, quantity: quantity)
        try commit { $0.trades[id]!.mutations.append(mutation) }
        let dispatched = Date()
        Task { diagnosticStep(e.event_id, "order_dispatch", "client=\(clientID) quantity=\(quantity) limit=\(price ?? "market")", at: dispatched) }
        do {
            let order = try await api.submitIntent(symbol: e.symbol, quantity: quantity, price: price, sell: sell, option: e.asset == "option", clientID: clientID)
            try mutation.validate(order, symbol: e.symbol)
            diagnosticStep(e.event_id, "broker_response", "client=\(clientID) broker=\(order.id) status=\(order.status) filled=\(order.filled_qty) average=\(order.filled_avg_price ?? "unavailable")")
            try commit { s in let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!; s.trades[id]!.mutations[index].order = order }
            if order.status == "rejected", hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        } catch AlpacaError.http(let code) where [400, 401, 403, 429].contains(code) {
            diagnosticStep(e.event_id, "broker_rejected", "HTTP \(code)")
            // Definitive rejection has no owned quantity; retain a terminal broker-shaped record.
            let rejected = AlpacaOrder(id: clientID, client_order_id: clientID, symbol: e.symbol, status: "rejected", qty: String(quantity), limit_price: price, filled_qty: "0", filled_avg_price: nil, side: sell ? "sell" : "buy")
            try commit { s in let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!; s.trades[id]!.mutations[index].order = rejected }
            if hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        }
    }
}
