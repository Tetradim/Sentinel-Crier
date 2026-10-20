import Foundation
import SwiftUI
import CryptoKit

struct IntentEvent: Codable, Equatable {
    var version = 1
    var event_id: String; var trade_id: String; var sequence: Int; var action: String
    var environment: AlpacaEnvironment; var symbol: String; var asset: String
    var quantity: Int; var limit_price: String; var created_at: String; var expires_at: String
    static func make(trade: String, sequence: Int, action: String, environment: AlpacaEnvironment, symbol: String, asset: String, quantity: Int, price: String) -> Self {
        let now = Date(); let f = ISO8601DateFormatter()
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
              quantity > 0, quantity <= 1000, let price = Decimal(string: limit_price), price > 0,
              !symbol.isEmpty, symbol == symbol.uppercased(), symbol.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }),
              let created = Self.date(created_at), let expiry = Self.date(expires_at), expiry >= created,
              (!["enter", "replace"].contains(action) || expiry.timeIntervalSince(created) <= 30) else { throw AlpacaError.invalid("Invalid intent event.") }
    }
}
struct IntentPreferences: Codable {
    var mode = "exact_limit"; var maxSlippageBps = 100; var maxSlippageAmount = "0.02"
    var maxAgeSeconds = 10; var maxQuantity = 1000; var paused = true
    func price(_ source: String, sell: Bool) throws -> String? {
        guard ["exact_limit", "market", "bounded_limit"].contains(mode), let value = Decimal(string: source), value > 0,
              maxSlippageBps >= 0, let absolute = Decimal(string: maxSlippageAmount), absolute >= 0,
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
        guard p.url.scheme == "https", p.url.host != nil, p.url.user == nil, p.url.password == nil,
              p.url.query == nil, p.url.fragment == nil, ["", "/"].contains(p.url.path),
              ["host", "follower"].contains(p.role), p.token.count >= 32 else { throw AlpacaError.invalid("Use an HTTPS intent pairing with host or follower role.") }
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
    private let file: URL
    private var api: AlpacaREST?; private var pair: IntentPairing?
    private var receiver: Task<Void, Never>?; private var worker: Task<Void, Never>?; private var transmitter: Task<Void, Never>?
    private var processing = false; private var publishing = false
    init(file: URL) throws {
        self.file = file
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
    func connect(api: AlpacaREST, account: String) throws {
        guard let pair = try IntentPairing.load() else { return }
        guard pair.environment == api.environment else { throw AlpacaError.invalid("Pairing environment differs from broker.") }
        guard state.accountID.isEmpty || (state.accountID == account && state.pairingID == pair.fingerprint) else { throw AlpacaError.invalid("Intent journal is pinned to its original account and pairing. Recover its trades before changing channels.") }
        try commit { $0.accountID = account; $0.pairingID = pair.fingerprint }
        self.api = api; self.pair = pair
        receiver?.cancel(); worker?.cancel(); transmitter?.cancel()
        if pair.role == "follower" { receiver = Task { await receiveLoop() } }
        transmitter = Task { while !Task.isCancelled { await publish(); try? await Task.sleep(nanoseconds: 500_000_000) } }
        worker = Task { while !Task.isCancelled { await process(); try? await Task.sleep(nanoseconds: 2_000_000_000) } }
        message = "\(pair.role.capitalized) connected. Keep Crier open for delivery."
    }
    func disconnect() { receiver?.cancel(); worker?.cancel(); transmitter?.cancel(); receiver = nil; worker = nil; transmitter = nil; api = nil; pair = nil }
    var hosting: Bool { pair?.role == "host" }
    func host(symbol: String, asset: String, quantity: Int, price: String, tradeID: String? = nil, action: String = "enter") throws -> String {
        guard let pair, hosting else { throw AlpacaError.invalid("Connect an intent host pairing first.") }
        let id = tradeID ?? UUID().uuidString.lowercased()
        let e = IntentEvent.make(trade: id, sequence: (state.trades[id]?.desired?.sequence ?? 0) + 1, action: action, environment: pair.environment, symbol: symbol, asset: asset, quantity: quantity, price: price)
        try commit { s in var t = s.trades[id] ?? IntentTrade(); try t.accept(e); s.trades[id] = t; s.outgoing.append(e) }
        Task { await publish() }; Task { await process() }
        return id
    }
    private func relay(_ query: String = "", body: Data? = nil) async throws -> Data {
        guard let pair else { throw AlpacaError.invalid("Disconnected.") }
        var request = URLRequest(url: URL(string: pair.url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/sync/events" + query)!)
        request.httpMethod = body == nil ? "GET" : "POST"; request.httpBody = body; request.timeoutInterval = 30
        request.setValue("Bearer " + pair.token, forHTTPHeaderField: "Authorization"); request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await CrierHTTPSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else { throw AlpacaError.invalid("Relay refused request.") }
        return data
    }
    private func publish() async {
        guard hosting, !publishing else { return }; publishing = true; defer { publishing = false }
        do {
            while !Task.isCancelled {
                if !state.outgoing.isEmpty { try commit { $0.discardSupersededEntries() } }
                guard let e = state.outgoing.first(where: { ["cancel", "exit"].contains($0.action) }) ?? state.outgoing.first else { break }
                _ = try await relay(body: JSONEncoder().encode(e))
                try commit { $0.outgoing.removeAll { $0.event_id == e.event_id } }
            }
        }
        catch { message = "Intent outbox pending: \(error.localizedDescription)" }
    }
    private func receiveLoop() async {
        struct Page: Decodable { struct Item: Decodable { var cursor: Int; var event: IntentEvent }; var events: [Item]; var cursor: Int }
        while !Task.isCancelled {
            do {
                let page = try JSONDecoder().decode(Page.self, from: await relay("?after=\(state.cursor)&wait=20"))
                try Task.checkCancellation()
                for item in page.events {
                    guard item.event.environment == pair?.environment else { throw AlpacaError.invalid("Relay environment mismatch.") }
                    try commit { s in
                        if let old = s.received[item.event.event_id], old != item.event { throw AlpacaError.invalid("Event identity conflict.") }
                        var t = s.trades[item.event.trade_id] ?? IntentTrade(); try t.accept(item.event, paused: s.preferences.paused)
                        s.trades[item.event.trade_id] = t; s.received[item.event.event_id] = item.event; s.cursor = max(s.cursor, item.cursor)
                    }
                }
                Task { await process() }
            } catch { message = error.localizedDescription; try? await Task.sleep(nanoseconds: 2_000_000_000) }
        }
    }
    private func process() async {
        guard !processing, let api else { return }; processing = true; defer { processing = false }
        for id in Array(state.trades.keys) {
            do { try Task.checkCancellation(); try await execute(id, api: api) }
            catch { message = "Trade \(id.prefix(8)): \(error.localizedDescription)" }
        }
    }
    private func terminal(_ order: AlpacaOrder) -> Bool { ["filled", "canceled", "expired", "rejected", "replaced"].contains(order.status) }
    private func execute(_ id: String, api: AlpacaREST) async throws {
        guard let initial = state.trades[id], let desired = initial.desired else { return }
        if initial.completed == desired.event_id && initial.mutations.allSatisfy({ $0.order.map(terminal) ?? false }) { return }
        let account = try await api.account()
        guard account.id == state.accountID, desired.environment == api.environment, account.status == "ACTIVE", !account.account_blocked, !account.trading_blocked else { throw AlpacaError.invalid("Account is changed or blocked.") }
        // Every unknown POST is reconciled; a 404 never permits another POST.
        for index in initial.mutations.indices {
            let m = state.trades[id]!.mutations[index]
            if let old = m.order, terminal(old) { continue }
            let order = try await api.order(clientID: m.clientID)
            try m.validate(order, symbol: desired.symbol)
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
                    if !m.cancelUnknown {
                        try commit { $0.trades[id]!.mutations[index].cancelUnknown = true }
                        try await api.cancel(orderID: order.id)
                    }
                    return // Wait for terminal broker status, including racing fills.
                }
            }
        }
        if e.action == "cancel" || (trade.invalidated && e.action != "exit") { return }
        if trade.completed == e.event_id { return }
        let sell = e.action == "exit"
        let existing = trade.mutations.filter { $0.eventID == e.event_id }
        if !sell && !existing.isEmpty { return }
        if sell && existing.contains(where: { $0.order?.status != "filled" }) { message = "Exit is working or needs broker reconciliation; no duplicate sell submitted."; return }
        if !sell {
            guard trade.entrySkipped != true, hosting || !state.preferences.paused,
                  let created = IntentEvent.date(e.created_at), let expires = IntentEvent.date(e.expires_at), created <= Date(), expires > Date(),
                  Date().timeIntervalSince(created) <= Double(hosting ? 30 : state.preferences.maxAgeSeconds),
                  e.quantity <= (hosting ? 1000 : state.preferences.maxQuantity) else { try commit { $0.trades[id]!.completed = e.event_id }; return }
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
        do {
            let order = try await api.submitIntent(symbol: e.symbol, quantity: quantity, price: price, sell: sell, option: e.asset == "option", clientID: clientID)
            try mutation.validate(order, symbol: e.symbol)
            try commit { s in let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!; s.trades[id]!.mutations[index].order = order }
            if order.status == "rejected", hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        } catch AlpacaError.http(let code) where [400, 401, 403, 429].contains(code) {
            // Definitive rejection has no owned quantity; retain a terminal broker-shaped record.
            let rejected = AlpacaOrder(id: clientID, client_order_id: clientID, symbol: e.symbol, status: "rejected", qty: String(quantity), limit_price: price, filled_qty: "0", filled_avg_price: nil, side: sell ? "sell" : "buy")
            try commit { s in let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!; s.trades[id]!.mutations[index].order = rejected }
            if hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        }
    }
}
