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
// Local follower policies are never part of the source wire envelope.
struct IntentExecutionPolicy: Codable, Equatable {
    var version = 1; var mode = "source"
    var fixed_quantity: Int?; var ratio_bps: Int?; var budget: String?
    var max_source_quantity = 1000; var max_local_quantity = 1000
    var max_entry_notional: String?; var exit_mode = "requested"; var entry_timeout_seconds: Int?
    init() {}
    enum CodingKeys: String, CodingKey, CaseIterable {
        case version, mode, fixed_quantity, ratio_bps, budget, max_source_quantity, max_local_quantity, max_entry_notional, exit_mode, entry_timeout_seconds
    }
    private struct Key: CodingKey { var stringValue: String; var intValue: Int? { nil }; init?(stringValue: String) { self.stringValue = stringValue }; init?(intValue: Int) { return nil } }
    init(from decoder: Decoder) throws {
        let raw = try decoder.container(keyedBy: Key.self)
        guard Set(raw.allKeys.map(\.stringValue)).isSubset(of: Set(CodingKeys.allCases.map(\.rawValue))) else { throw AlpacaError.invalid("Unknown execution policy field.") }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func defaulted<T: Decodable>(_ type: T.Type, _ key: CodingKeys, _ fallback: T) throws -> T {
            // Only omission chooses a default. An explicit null is malformed for a required policy value.
            if c.contains(key) { return try c.decode(type, forKey: key) }
            return fallback
        }
        version = try defaulted(Int.self, .version, 1)
        mode = try defaulted(String.self, .mode, "source")
        fixed_quantity = try c.decodeIfPresent(Int.self, forKey: .fixed_quantity)
        ratio_bps = try c.decodeIfPresent(Int.self, forKey: .ratio_bps)
        budget = try c.decodeIfPresent(String.self, forKey: .budget)
        max_source_quantity = try defaulted(Int.self, .max_source_quantity, 1000)
        max_local_quantity = try defaulted(Int.self, .max_local_quantity, 1000)
        max_entry_notional = try c.decodeIfPresent(String.self, forKey: .max_entry_notional)
        exit_mode = try defaulted(String.self, .exit_mode, "requested")
        entry_timeout_seconds = try c.decodeIfPresent(Int.self, forKey: .entry_timeout_seconds)
        try validate()
    }
    static func money(_ text: String) throws -> Decimal {
        guard text.range(of: "^(?:0|[1-9][0-9]*)(?:\\.[0-9]{1,8})?$", options: .regularExpression) != nil,
              text.filter({ $0 != "." }).count <= 20, let amount = Decimal(string: text), amount > 0 else { throw AlpacaError.invalid("Invalid policy dollar amount.") }
        return amount
    }
    func validate(market: Bool = false) throws {
        guard version == 1, ["source", "fixed", "ratio", "budget"].contains(mode), ["requested", "proportional", "close_tracked"].contains(exit_mode),
              (1...1000).contains(max_source_quantity), (1...1000).contains(max_local_quantity),
              entry_timeout_seconds.map({ (1...86400).contains($0) }) ?? true else { throw AlpacaError.invalid("Invalid execution policy.") }
        guard mode == "fixed" ? fixed_quantity.map({ (1...1000).contains($0) }) == true : fixed_quantity == nil,
              mode == "ratio" ? ratio_bps.map({ (1...10000).contains($0) }) == true : ratio_bps == nil,
              mode == "budget" ? budget != nil : budget == nil else { throw AlpacaError.invalid("Missing or unused sizing field.") }
        if let budget { _ = try Self.money(budget) }
        if let max_entry_notional { _ = try Self.money(max_entry_notional) }
        guard !market || (mode != "budget" && max_entry_notional == nil) else { throw AlpacaError.invalid("Budget and dollar caps require limit pricing.") }
    }
    func target(source: Int, price: String?, multiplier: Int, bought: Int, spent: Decimal) throws -> Int {
        try validate(market: price == nil)
        guard (1...max_source_quantity).contains(source), multiplier == 1 || multiplier == 100 else { throw AlpacaError.invalid("Source cap or multiplier rejected.") }
        let unit = try price.map { try Self.money($0) * Decimal(multiplier) }
        var target = source
        if mode == "fixed" { target = fixed_quantity! }
        if mode == "ratio" { target = source * ratio_bps! / 10000 }
        if mode == "budget" {
            let remaining = max(0, try IntentBrokerDecimal.add(Self.money(budget!), -spent))
            var quotient = remaining / unit!
            var whole = Decimal()
            NSDecimalRound(&whole, &quotient, 0, .down)
            // Integer conversion is only performed after explicit decimal floor and boundedness checks.
            // Foundation's conversion of a fractional NSDecimalNumber is not the sizing rounding rule.
            guard whole <= Decimal(max_local_quantity), whole >= 0 else { throw AlpacaError.invalid("Local target cap exceeded.") }
            target = bought + NSDecimalNumber(decimal: whole).intValue
        }
        guard target <= max_local_quantity else { throw AlpacaError.invalid("Local target cap exceeded.") }
        if let cap = max_entry_notional, let unit {
            let reserved = try IntentBrokerDecimal.multiply(Decimal(max(0, target - bought)), unit)
            if try IntentBrokerDecimal.add(spent, reserved) > Self.money(cap) { throw AlpacaError.invalid("Entry notional cap exceeded.") }
        }
        return target
    }
}
// Broker weighted average prices are evidence, not policy input amounts. Preserve every
// representable digit and reject precision loss instead of applying the policy's eight-place limit.
enum IntentBrokerDecimal {
    private static func canonical(_ text: String) -> String {
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        let whole = String(parts[0].drop(while: { $0 == "0" }))
        let fraction = parts.count == 2 ? String(parts[1].reversed().drop(while: { $0 == "0" }).reversed()) : ""
        return (whole.isEmpty ? "0" : whole) + (fraction.isEmpty ? "" : "." + fraction)
    }
    static func price(_ text: String) throws -> Decimal {
        guard text.count <= 1024, text.range(of: "^[0-9]+(?:\\.[0-9]+)?$", options: .regularExpression) != nil,
              var value = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX")), !value.isNaN, value > 0 else { throw AlpacaError.invalid("Invalid authoritative broker fill average.") }
        let roundTrip = NSDecimalString(&value, Locale(identifier: "en_US_POSIX"))
        guard roundTrip.range(of: "^[0-9]+(?:\\.[0-9]+)?$", options: .regularExpression) != nil,
              canonical(roundTrip) == canonical(text) else { throw AlpacaError.invalid("Broker fill average exceeds exact decimal precision.") }
        return value
    }
    static func multiply(_ left: Decimal, _ right: Decimal) throws -> Decimal {
        var lhs = left, rhs = right, result = Decimal()
        guard NSDecimalMultiply(&result, &lhs, &rhs, .plain) == .noError else { throw AlpacaError.invalid("Authoritative fill cost loses decimal precision.") }
        return result
    }
    static func add(_ left: Decimal, _ right: Decimal) throws -> Decimal {
        var lhs = left, rhs = right, result = Decimal()
        guard NSDecimalAdd(&result, &lhs, &rhs, .plain) == .noError else { throw AlpacaError.invalid("Cumulative fill cost loses decimal precision.") }
        return result
    }
}
struct IntentPolicySnapshot: Codable, Equatable {
    var legacy: Bool; var policy: IntentExecutionPolicy?
    var pairing: String; var role: String; var accountID: String
    var environment: AlpacaEnvironment; var symbol: String; var asset: String
    static func legacy(_ event: IntentEvent) -> Self { Self(legacy: true, policy: nil, pairing: "", role: "", accountID: "", environment: event.environment, symbol: event.symbol, asset: event.asset) }
    func validate(event: IntentEvent) throws {
        guard environment == event.environment, symbol == event.symbol, asset == event.asset,
              legacy ? policy == nil : (policy != nil && role == "follower" && !pairing.isEmpty) else { throw AlpacaError.invalid("Missing or contradictory policy snapshot; preserve journal for recovery.") }
        try policy?.validate()
    }
}
struct IntentPolicyBinding: Codable, Equatable {
    var accountID: String; var environment: AlpacaEnvironment; var symbol: String; var asset: String
    var instrumentID: String; var multiplier: Int; var currency: String
}
struct IntentPricingBasis: Codable, Equatable {
    var mode: String; var maxSlippageBps: Int; var maxSlippageAmount: String
    init(_ preferences: IntentPreferences) {
        mode = preferences.mode; maxSlippageBps = preferences.maxSlippageBps; maxSlippageAmount = preferences.maxSlippageAmount
    }
    func finalBuyPrice(_ source: String) throws -> String? {
        var preferences = IntentPreferences()
        preferences.mode = mode; preferences.maxSlippageBps = maxSlippageBps; preferences.maxSlippageAmount = maxSlippageAmount
        return try preferences.price(source, sell: false)
    }
}
struct IntentEntryPlan: Codable, Equatable {
    var event: IntentEvent; var snapshot: IntentPolicySnapshot; var target: Int; var price: String?; var binding: IntentPolicyBinding
    var baselineBought: Int; var baselineSpent: String; var pricingBasis: IntentPricingBasis
    func validate() throws {
        try event.validate(); try snapshot.validate(event: event)
        guard let policy = snapshot.policy, !snapshot.legacy, ["enter", "replace"].contains(event.action),
              (0...1000).contains(baselineBought), let spent = Decimal(string: baselineSpent), spent >= 0,
              baselineSpent == NSDecimalNumber(decimal: spent).stringValue,
              target >= 0, target <= policy.max_local_quantity,
              binding.environment == snapshot.environment, binding.symbol == snapshot.symbol, binding.asset == snapshot.asset,
              !binding.accountID.isEmpty, !binding.instrumentID.isEmpty, binding.currency == "USD",
              binding.multiplier == (snapshot.asset == "option" ? 100 : 1),
              snapshot.accountID.isEmpty || snapshot.accountID == binding.accountID else { throw AlpacaError.invalid("Contradictory frozen plan baseline or broker identity.") }
        guard price == (try pricingBasis.finalBuyPrice(event.limit_price)) else { throw AlpacaError.invalid("Frozen final price differs from its source and pricing basis.") }
        let calculated = try policy.target(source: event.quantity, price: price, multiplier: binding.multiplier, bought: baselineBought, spent: spent)
        guard target == calculated else { throw AlpacaError.invalid("Frozen target differs from its policy and cost baseline.") }
    }
}

struct IntentPreferences: Codable {
    var mode = "exact_limit"; var maxSlippageBps = 100; var maxSlippageAmount = "0.02"
    var maxAgeSeconds = 10; var maxQuantity = 1000; var paused = true
    var execution_policy: IntentExecutionPolicy?
    init() {}
    enum CodingKeys: String, CodingKey { case mode, maxSlippageBps, maxSlippageAmount, maxAgeSeconds, maxQuantity, paused, execution_policy }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "exact_limit"
        maxSlippageBps = try c.decodeIfPresent(Int.self, forKey: .maxSlippageBps) ?? 100
        maxSlippageAmount = try c.decodeIfPresent(String.self, forKey: .maxSlippageAmount) ?? "0.02"
        maxAgeSeconds = try c.decodeIfPresent(Int.self, forKey: .maxAgeSeconds) ?? 10
        maxQuantity = try c.decodeIfPresent(Int.self, forKey: .maxQuantity) ?? 1000
        paused = try c.decodeIfPresent(Bool.self, forKey: .paused) ?? true
        execution_policy = try c.decodeIfPresent(IntentExecutionPolicy.self, forKey: .execution_policy)
        try execution_policy?.validate(market: mode == "market")
        _ = try price("1", sell: false)
    }
    func samePricing(as other: IntentPreferences) -> Bool {
        mode == other.mode && maxSlippageBps == other.maxSlippageBps && maxSlippageAmount == other.maxSlippageAmount
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
    var notSubmitted: Bool?
    var acknowledgedSession: String?; var acknowledgedUptime: TimeInterval?
    var brokerResponseSession: String?
    var priorHTTPRefusalOrder: AlpacaOrder?
    func validateLocalDisposition() throws {
        guard priorHTTPRefusalOrder == nil || (notSubmitted == true && order == nil) else { throw AlpacaError.invalid("Contradictory HTTP-refusal upgrade evidence.") }
        guard (acknowledgedSession == nil) == (acknowledgedUptime == nil),
              acknowledgedUptime.map({ $0.isFinite && $0 >= 0 }) ?? true,
              acknowledgedSession.map({ !$0.isEmpty && !sell && order != nil && notSubmitted != true }) ?? true else { throw AlpacaError.invalid("Contradictory timed-order acknowledgement.") }
        guard notSubmitted != true || (order == nil && !cancelUnknown && cancelAttemptedAt == nil) else {
            throw AlpacaError.invalid("Contradictory not-submitted order record. Preserve the journal for recovery.")
        }
    }
    // Call only after validating a fresh broker lookup for this mutation.
    func mayRetryCancellation(now: Date) -> Bool {
        guard let order, !["filled", "canceled", "expired", "rejected", "replaced", "pending_cancel"].contains(order.status) else { return false }
        return cancelAttemptedAt.map { now.timeIntervalSince($0) >= 5 } ?? true
    }
    func validate(_ incoming: AlpacaOrder, symbol: String) throws {
        let statuses = ["new", "partially_filled", "filled", "done_for_day", "canceled", "expired", "replaced", "pending_cancel", "pending_replace", "accepted", "pending_new", "accepted_for_bidding", "stopped", "rejected", "suspended", "calculated"]
        guard statuses.contains(incoming.status), incoming.client_order_id == clientID, incoming.symbol == symbol,
              incoming.side == (sell ? "sell" : "buy"), !incoming.id.isEmpty,
              order == nil || order?.id == incoming.id,
              incoming.qty.flatMap({ Decimal(string: $0) }) == Decimal(quantity),
              let filled = Decimal(string: incoming.filled_qty), filled >= 0, filled <= Decimal(quantity),
              filled >= (Decimal(string: order?.filled_qty ?? "0") ?? 0),
              filled == Decimal(NSDecimalNumber(decimal: filled).intValue) else { throw AlpacaError.invalid("Broker order identity or cumulative fill mismatch.") }
        if let average = incoming.filled_avg_price { _ = try IntentBrokerDecimal.price(average) }
    }
}
struct IntentTrade: Codable {
    var desired: IntentEvent?; var invalidated = false; var completed: String?
    var policySnapshot: IntentPolicySnapshot?; var policyBinding: IntentPolicyBinding?
    var entryPlans: [String: IntentEntryPlan]?; var entryClosed: Bool?; var sourceHistoryInvalid: Bool?
    var policyRefusals: [String: String]?
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
    var bought: Int { mutations.filter { !$0.sell }.reduce(0) { $0 + NSDecimalNumber(decimal: Decimal(string: $1.order?.filled_qty ?? "0") ?? 0).intValue } }
    var totalSold: Int { mutations.filter { $0.sell }.reduce(0) { $0 + NSDecimalNumber(decimal: Decimal(string: $1.order?.filled_qty ?? "0") ?? 0).intValue } }
    func validateBuyPlans(tradeID: String, history: [String: IntentEvent]) throws {
        guard let snapshot = policySnapshot, !snapshot.legacy else { return }
        for mutation in mutations where !mutation.sell {
            guard let plan = entryPlans?[mutation.eventID] else { throw AlpacaError.invalid("Prior advanced buy has no frozen plan; new entries blocked. Cancels and quantity-proven exits remain available.") }
            try plan.validate()
            guard plan.event.event_id == mutation.eventID, plan.event.trade_id == tradeID,
                  history[mutation.eventID] == plan.event, plan.snapshot == snapshot, plan.binding == policyBinding,
                  mutation.quantity > 0, mutation.quantity == max(0, plan.target - plan.baselineBought) else { throw AlpacaError.invalid("Prior advanced buy plan, source event, or reserved quantity is contradictory.") }
        }
    }
    func premiumSpent(multiplier: Int) throws -> Decimal {
        try mutations.filter { !$0.sell }.reduce(Decimal(0)) { sum, mutation in
            let filled = Decimal(string: mutation.order?.filled_qty ?? "0") ?? 0
            guard filled > 0 else { return sum }
            guard let text = mutation.order?.filled_avg_price else { throw AlpacaError.invalid("Cumulative buy fill cost unavailable.") }
            let average = try IntentBrokerDecimal.price(text)
            let filledPremium = try IntentBrokerDecimal.multiply(filled, average)
            let cost = try IntentBrokerDecimal.multiply(filledPremium, Decimal(multiplier))
            return try IntentBrokerDecimal.add(sum, cost)
        }
    }
    func proportionalDue(event: IntentEvent, history: [String: IntentEvent]) throws -> Int {
        let events = history.values.filter { $0.trade_id == event.trade_id && $0.sequence <= event.sequence }.sorted { $0.sequence < $1.sequence }
        guard sourceHistoryInvalid != true, events.count == event.sequence, events.first?.action == "enter" else { throw AlpacaError.invalid("Complete source intent history required.") }
        var denominator = 0; var numerator = 0; var closed = false
        for (offset, item) in events.enumerated() {
            guard item.sequence == offset + 1, item.symbol == event.symbol, item.asset == event.asset, item.environment == event.environment else { throw AlpacaError.invalid("Conflicting source intent history.") }
            if ["enter", "replace"].contains(item.action) {
                guard !closed, offset == 0 || item.action == "replace" else { throw AlpacaError.invalid("Entry after source invalidation.") }
                denominator = item.quantity
            } else {
                closed = true
                if item.action == "exit" { numerator = min(denominator, numerator + item.quantity) }
            }
        }
        guard denominator > 0 else { throw AlpacaError.invalid("Source denominator unavailable.") }
        return max(0, bought * numerator / denominator - totalSold)
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
    var policySchema: Int? = 1; var pairingRole: String?
    var cursor = 0; var accountID = ""; var pairingID = ""; var trades: [String: IntentTrade] = [:]
    var outgoing: [IntentEvent] = []; var received: [String: IntentEvent] = [:]
    var diagnostics: [String: IntentDiagnosticRecord]?
    struct Quarantine: Codable { var cursor: Int; var reason: String; var record: String }
    var quarantine: [Quarantine]?
    var unresolved: [String] {
        trades.compactMap { id, trade in
            let working = trade.mutations.contains { $0.notSubmitted != true && ($0.order.map { !["filled", "canceled", "expired", "rejected", "replaced"].contains($0.status) } ?? true) }
            return working || trade.owned > 0 || (trade.desired != nil && trade.completed != trade.desired?.event_id && !trade.invalidated && trade.entryClosed != true) ? id : nil
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
                if let previous = received[event.event_id], previous != event { trades[previous.trade_id]?.sourceHistoryInvalid = true; trades[event.trade_id]?.sourceHistoryInvalid = true; throw AlpacaError.invalid("Event identity conflict.") }
                var trade = trades[event.trade_id] ?? IntentTrade()
                if trades[event.trade_id] == nil {
                    if let policy = preferences.execution_policy, pairingRole != "host" {
                        guard pairingRole == "follower", !pairingID.isEmpty else { throw AlpacaError.invalid("Advanced follower policy requires a pinned pairing scope.") }
                        try policy.validate(market: preferences.mode == "market")
                        var pinned = policy; pinned.max_source_quantity = min(policy.max_source_quantity, preferences.maxQuantity)
                        trade.policySnapshot = IntentPolicySnapshot(legacy: false, policy: pinned, pairing: pairingID, role: "follower", accountID: accountID, environment: event.environment, symbol: event.symbol, asset: event.asset)
                    } else { trade.policySnapshot = .legacy(event) }
                }
                guard let snapshot = trade.policySnapshot else { throw AlpacaError.invalid("Policy snapshot missing; preserve journal.") }
                try snapshot.validate(event: event)
                if received.values.contains(where: { $0.trade_id == event.trade_id && $0.sequence == event.sequence && $0 != event }) { trades[event.trade_id]?.sourceHistoryInvalid = true; throw AlpacaError.invalid("Conflicting historical source sequence.") }
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
    mutating func upgradeDiagnosticProvenHTTPRefusals() -> Bool {
        var upgraded = false
        for (id, trade) in trades {
            for (index, mutation) in trade.mutations.enumerated() {
                guard mutation.notSubmitted == nil, mutation.priorHTTPRefusalOrder == nil,
                      !mutation.cancelUnknown, mutation.cancelAttemptedAt == nil,
                      mutation.acknowledgedSession == nil, mutation.acknowledgedUptime == nil, mutation.brokerResponseSession == nil,
                      let order = mutation.order, order.id == mutation.clientID, order.client_order_id == mutation.clientID,
                      order.status == "rejected", order.filled_qty == "0", order.filled_avg_price == nil,
                      order.qty == String(mutation.quantity), order.side == (mutation.sell ? "sell" : "buy"),
                      order.position_intent == nil, order.order_class == nil,
                      var diagnostic = diagnostics?[mutation.eventID], diagnostic.event.event_id == mutation.eventID,
                      diagnostic.event.trade_id == id, diagnostic.event.symbol == order.symbol,
                      diagnostic.event.environment == trade.desired?.environment,
                      (try? diagnostic.event.validate()) != nil,
                      mutation.sell ? diagnostic.event.action == "exit" : ["enter", "replace"].contains(diagnostic.event.action),
                      mutation.clientID == "si-" + mutation.eventID + (mutation.sell ? "-s\(indexForExit(mutation, in: trade))" : "-b"),
                      diagnostic.timeline.contains(where: { $0.stage == "broker_rejected" && ["HTTP 400", "HTTP 401", "HTTP 403", "HTTP 429"].contains($0.detail) }),
                      !diagnostic.timeline.contains(where: { ["broker_response", "reconciled"].contains($0.stage) && $0.detail.hasPrefix("client=" + mutation.clientID + " ") }) else { continue }
                // The exact old writer shape plus its durable definitive HTTP diagnostic proves
                // local refusal. Retain both the old row and original timeline as audit evidence.
                trades[id]!.mutations[index].priorHTTPRefusalOrder = order
                trades[id]!.mutations[index].order = nil
                trades[id]!.mutations[index].notSubmitted = true
                diagnostic.timeline.append(DiagnosticStep(at: IntentDiagnosticRecord.timestamp(), stage: "local_refusal_upgraded", detail: "Retained synthetic HTTP-refusal order as audit evidence; no broker order asserted"))
                diagnostics?[mutation.eventID] = diagnostic
                upgraded = true
            }
        }
        return upgraded
    }
    private func indexForExit(_ mutation: IntentMutation, in trade: IntentTrade) -> Int {
        trade.mutations.filter { $0.eventID == mutation.eventID && $0.sell }.firstIndex(where: { $0.clientID == mutation.clientID }) ?? -1
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
    private let monotonic: () -> TimeInterval
    private var entryClock: EntryClock
    private let session: URLSession
    private var api: AlpacaREST?; private var pair: IntentPairing?
    private var receiver: Task<Void, Never>?; private var worker: Task<Void, Never>?; private var transmitter: Task<Void, Never>?
    private var diagnosticWorker: Task<Void, Never>?
    private var diagnosticClock: DiagnosticClock?
    private var diagnosticSession = UUID()
    private var quoteCaptures = Set<String>()
    private var processing = false; private var publishing = false
    private var timerSession = UUID().uuidString
    init(file: URL, now: @escaping () -> Date = Date.init, monotonic: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }, session: URLSession = CrierHTTPSession.shared) throws {
        self.file = file
        self.now = now
        self.monotonic = monotonic; entryClock = EntryClock(wall: now, mono: monotonic)
        self.session = session
        state = FileManager.default.fileExists(atPath: file.path) ? try JSONDecoder().decode(IntentState.self, from: Data(contentsOf: file)) : IntentState()
        if state.policySchema == nil {
            guard state.trades.values.allSatisfy({ $0.policySnapshot == nil && $0.policyBinding == nil && $0.entryPlans == nil && $0.entryClosed == nil }) else { throw AlpacaError.invalid("Policy evidence without migration marker; preserve journal.") }
            // Only pre-schema journals are migrated. Current missing records fail closed.
            for id in state.trades.keys {
                if let event = state.trades[id]?.desired { state.trades[id]?.policySnapshot = .legacy(event) }
            }
            state.policySchema = 1
            try JSONEncoder().encode(state).write(to: file, options: [.atomic, .completeFileProtection])
        }
        guard state.policySchema == 1 else { throw AlpacaError.invalid("Unsupported policy journal schema.") }
        for trade in state.trades.values {
            if let event = trade.desired {
                guard let snapshot = trade.policySnapshot else { throw AlpacaError.invalid("Policy snapshot missing; preserve journal for recovery.") }
                try snapshot.validate(event: event)
                if snapshot.legacy {
                    guard trade.policyBinding == nil, trade.entryPlans == nil, trade.entryClosed == nil else { throw AlpacaError.invalid("Legacy trade contains advanced policy evidence.") }
                }
                for (revision, plan) in (trade.entryPlans ?? [:]) {
                    try plan.validate()
                    guard revision == plan.event.event_id, plan.snapshot == snapshot, plan.binding == trade.policyBinding, plan.event.trade_id == event.trade_id,
                          plan.binding.environment == snapshot.environment, plan.binding.symbol == snapshot.symbol, plan.binding.asset == snapshot.asset,
                          !plan.binding.accountID.isEmpty, !plan.binding.instrumentID.isEmpty, plan.binding.currency == "USD",
                          plan.binding.multiplier == (snapshot.asset == "option" ? 100 : 1),
                          snapshot.accountID.isEmpty || snapshot.accountID == plan.binding.accountID,
                          plan.target >= 0, plan.target <= (snapshot.policy?.max_local_quantity ?? 1000) else { throw AlpacaError.invalid("Contradictory frozen entry plan.") }
                }
            }
            for mutation in trade.mutations { try mutation.validateLocalDisposition() }
        }
        if state.upgradeDiagnosticProvenHTTPRefusals() {
            try JSONEncoder().encode(state).write(to: file, options: [.atomic, .completeFileProtection])
        }
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
    func settings(_ p: IntentPreferences) throws {
        _ = try p.price("1", sell: false); try p.execution_policy?.validate(market: p.mode == "market")
        guard p.execution_policy == state.preferences.execution_policy || p.paused else { throw AlpacaError.invalid("Policy changes must leave follower entries paused. Save paused, then explicitly resume.") }
        try commit { $0.preferences = p }
    }
    func validateIdentity(account: String, environment: AlpacaEnvironment, pairing: IntentPairing? = nil) throws {
        guard let pair = try pairing ?? IntentPairing.load() else { return }
        guard pair.environment == environment else { throw AlpacaError.invalid("Pairing environment differs from broker.") }
        guard state.accountID.isEmpty || (state.accountID == account && state.pairingID == pair.fingerprint) else { throw AlpacaError.invalid("Intent journal is pinned to its original account and pairing. Recover its trades before changing channels.") }
    }
    func connect(api: AlpacaREST, account: String, pairing: IntentPairing? = nil, startWorkers: Bool = true) throws {
        guard let pair = try pairing ?? IntentPairing.load() else { return }
        try validateIdentity(account: account, environment: api.environment, pairing: pair)
        try commit { $0.accountID = account; $0.pairingID = pair.fingerprint; $0.pairingRole = pair.role }
        timerSession = UUID().uuidString
        if self.api !== api { self.api?.invalidate() }
        self.api = api; self.pair = pair
        entryClock = EntryClock(wall: now, mono: monotonic)
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
        try commit { s in var t = s.trades[id] ?? IntentTrade(); if t.policySnapshot == nil { t.policySnapshot = .legacy(e) }; try t.accept(e); s.trades[id] = t; s.outgoing.append(e) }
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
        var failures: [String] = []; var freshByTrade: [String: Set<Int>] = [:]; var failedTrades = Set<String>()
        for id in state.trades.keys.sorted() {
            guard let trade = state.trades[id], let event = trade.desired else { continue }
            if settled(trade) { continue }
            for index in trade.mutations.indices {
                let mutation = trade.mutations[index]
                do {
                    try mutation.validateLocalDisposition()
                    if mutation.notSubmitted == true { continue }
                    let order = try await api.order(clientID: mutation.clientID)
                    try mutation.validate(order, symbol: event.symbol)
                    try Task.checkCancellation()
                    guard self.api === api, pair != nil else { throw AlpacaError.invalid("Reconnect interrupted.") }
                    try recordReconciliation(id: id, index: index, order: order)
                    freshByTrade[id, default: []].insert(index)
                } catch {
                    try Task.checkCancellation()
                    guard self.api === api, pair != nil else { throw error }
                    failedTrades.insert(id)
                    failures.append(mutation.clientID + ": " + error.localizedDescription)
                }
            }
        }
        // Resume is cancellation-only: a failure elsewhere cannot prevent canceling a
        // separately freshly verified working order before the workspace disconnects.
        for id in freshByTrade.keys.sorted() {
            do {
                let cancelPending = try await cancelFreshWorkingMutation(id, api: api, freshIndexes: freshByTrade[id]!)
                if !cancelPending, !failedTrades.contains(id), let trade = state.trades[id], let event = trade.desired {
                    let stoppedEntry = event.action == "cancel" || ((trade.invalidated || trade.entryClosed == true) && event.action != "exit")
                    let stoppedExit = event.action == "exit" && trade.mutations.contains { $0.eventID == event.event_id && $0.order?.status != "filled" }
                    if stoppedEntry || stoppedExit { try completeTerminalInstruction(id, eventID: event.event_id) }
                }
            }
            catch {
                try Task.checkCancellation()
                guard self.api === api, pair != nil else { throw error }
                failedTrades.insert(id)
                failures.append(id + ": " + error.localizedDescription)
            }
        }
        if !failures.isEmpty { throw AlpacaError.invalid("Broker reconciliation required: " + failures.joined(separator: "; ")) }
    }

    func process() async {
        guard !processing, let api else { return }; processing = true; defer { processing = false }
        let observed = onHealth; var needsReconciliation = false
        for id in Array(state.trades.keys) {
            do { try Task.checkCancellation(); try await execute(id, api: api, observe: observed) }
            catch { needsReconciliation = true; if let event = state.trades[id]?.desired {
                diagnosticStep(event.event_id, "execution_pending", error.localizedDescription)
                if state.trades[id]?.policySnapshot?.policy != nil {
                    try? commit { if $0.trades[id]!.policyRefusals == nil { $0.trades[id]!.policyRefusals = [:] }; $0.trades[id]!.policyRefusals![event.event_id] = error.localizedDescription }
                }
            }; message = "Trade \(id.prefix(8)): \(error.localizedDescription)" }
        }
        needsReconciliation = needsReconciliation || state.trades.values.contains { $0.mutations.contains { $0.notSubmitted != true && ($0.order == nil || $0.cancelUnknown) } }
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
    private func recordReconciliation(id: String, index: Int, order: AlpacaOrder) throws {
        let uptime = monotonic(); let session = timerSession
        try commit { state in
            let prior = state.trades[id]!.mutations[index]
            state.trades[id]!.mutations[index].order = order
            guard !state.trades[id]!.mutations[index].sell, !terminal(order),
                  let seconds = state.trades[id]!.policySnapshot?.policy?.entry_timeout_seconds else { return }
            let mutation = state.trades[id]!.mutations[index]
            if let acknowledged = mutation.acknowledgedSession {
                if acknowledged != session || mutation.acknowledgedUptime.map({ uptime < $0 || uptime - $0 >= Double(seconds) }) != false {
                    state.trades[id]!.entryClosed = true
                }
            } else if prior.order != nil && prior.brokerResponseSession != session {
                // A previously known live order with absent acknowledgement evidence cannot get a renewed timer.
                state.trades[id]!.entryClosed = true
            } else {
                // Unknown POSTs first observed after restart start here, never at local reservation/POST.
                state.trades[id]!.mutations[index].acknowledgedSession = session
                state.trades[id]!.mutations[index].acknowledgedUptime = uptime
            }
        }
    }
    private func requiresCancellation(_ trade: IntentTrade, mutation: IntentMutation) -> Bool {
        guard let event = trade.desired,
              event.action != "enter" || trade.invalidated || trade.entryClosed == true else { return false }
        return mutation.eventID != event.event_id || event.action == "cancel" || ((event.action == "exit" || trade.entryClosed == true) && !mutation.sell)
    }
    private func cancelFreshWorkingMutation(_ id: String, api: AlpacaREST, freshIndexes: Set<Int>) async throws -> Bool {
        guard let trade = state.trades[id], let event = trade.desired else { return false }
        for index in trade.mutations.indices where freshIndexes.contains(index) {
            let mutation = trade.mutations[index]
            guard let order = mutation.order, !terminal(order), requiresCancellation(trade, mutation: mutation) else { continue }
            try Task.checkCancellation()
            guard self.api === api, let pairing = pair else { throw AlpacaError.invalid("Cancellation interrupted.") }
            let attemptTime = now()
            if mutation.mayRetryCancellation(now: attemptTime) {
                try commit {
                    $0.trades[id]!.mutations[index].cancelUnknown = true
                    $0.trades[id]!.mutations[index].cancelAttemptedAt = attemptTime
                }
                diagnosticStep(event.event_id, "cancel_dispatch", "broker=\(order.id)")
                try await api.cancel(orderID: order.id, canCancel: { [self] in
                    guard !Task.isCancelled, self.api === api, pair?.fingerprint == pairing.fingerprint,
                          let current = state.trades[id], current.mutations.indices.contains(index) else { return false }
                    let bound = current.mutations[index]
                    return bound.clientID == mutation.clientID && bound.order?.id == order.id && bound.order.map({ !terminal($0) }) == true && requiresCancellation(current, mutation: bound)
                })
            }
            return true // Cancellation was attempted or is awaiting fresh terminal proof/cooldown.
        }
        return false
    }
    private func settled(_ trade: IntentTrade) -> Bool {
        trade.desired != nil && trade.completed == trade.desired?.event_id && trade.mutations.allSatisfy { $0.notSubmitted == true || ($0.order.map(terminal) ?? false) }
    }
    private func completeTerminalInstruction(_ id: String, eventID: String) throws {
        // Call only after this pass successfully reconciled all broker-backed rows.
        try commit { state in
            guard let trade = state.trades[id], trade.desired?.event_id == eventID,
                  trade.mutations.allSatisfy({ $0.notSubmitted == true || ($0.order.map(terminal) ?? false) }) else { return }
            state.trades[id]!.completed = eventID
        }
    }
    private func terminal(_ order: AlpacaOrder) -> Bool { ["filled", "canceled", "expired", "rejected", "replaced"].contains(order.status) }
    private func execute(_ id: String, api: AlpacaREST, observe: NativeHealthObserver? = nil) async throws {
        guard let initial = state.trades[id], let desired = initial.desired else { return }
        if settled(initial) { return }
        let account = try await api.account()
        guard account.id == state.accountID, desired.environment == api.environment, account.status == "ACTIVE", !account.account_blocked, !account.trading_blocked else { throw AlpacaError.invalid("Account is changed or blocked.") }
        observe?(.broker, .healthy, .verified)
        // Refresh every broker-backed mutation, including terminal records. An unrelated
        // lookup failure blocks new orders but must not conceal a separately verified cancelable buy.
        var freshIndexes = Set<Int>(); var failures: [String] = []
        for index in initial.mutations.indices {
            let mutation = state.trades[id]!.mutations[index]
            do {
                try mutation.validateLocalDisposition()
                if mutation.notSubmitted == true { continue }
                let order = try await api.order(clientID: mutation.clientID)
                try mutation.validate(order, symbol: desired.symbol)
                try Task.checkCancellation()
                guard self.api === api, pair != nil else { return }
                diagnosticStep(mutation.eventID, "reconciled", "client=\(mutation.clientID) broker=\(order.id) status=\(order.status) filled=\(order.filled_qty) average=\(order.filled_avg_price ?? "unavailable")")
                try recordReconciliation(id: id, index: index, order: order)
                freshIndexes.insert(index)
                if order.status == "rejected", hosting, state.trades[id]?.desired?.action != "cancel" {
                    _ = try host(symbol: desired.symbol, asset: desired.asset, quantity: desired.quantity, price: desired.limit_price, tradeID: id, action: "cancel")
                }
            } catch {
                try Task.checkCancellation()
                guard self.api === api, pair != nil else { return }
                failures.append(mutation.clientID + ": " + error.localizedDescription)
            }
        }
        guard let trade = state.trades[id], let e = trade.desired else { return }
        if try await cancelFreshWorkingMutation(id, api: api, freshIndexes: freshIndexes) {
            if !failures.isEmpty { throw AlpacaError.invalid("Broker reconciliation required: " + failures.joined(separator: "; ")) }
            return
        }
        if !failures.isEmpty { throw AlpacaError.invalid("Broker reconciliation required: " + failures.joined(separator: "; ")) }
        if e.action == "cancel" || ((trade.invalidated || trade.entryClosed == true) && e.action != "exit") {
            diagnosticStep(e.event_id, "entry_invalidated", "Entry remainder canceled or superseded; tracked fills retained")
            try completeTerminalInstruction(id, eventID: e.event_id)
            return
        }
        if trade.mutations.contains(where: { $0.notSubmitted != true && ($0.order.map { !terminal($0) } ?? true) }) { return }
        if trade.completed == e.event_id { return }
        let sell = e.action == "exit"
        let existing = trade.mutations.filter { $0.eventID == e.event_id }
        if !sell && !existing.isEmpty {
            try completeTerminalInstruction(id, eventID: e.event_id)
            return
        }
        if sell && existing.contains(where: { $0.order?.status != "filled" }) {
            try completeTerminalInstruction(id, eventID: e.event_id)
            message = "Exit is terminal or needs broker reconciliation; no duplicate sell submitted."
            return
        }
        if !sell {
            guard let sample = entryClock.read() else {
                diagnosticStep(e.event_id, "entry_deferred", "clock_changed: check device time and reconnect; cancellation/exit handling remains active")
                message = "New entry deferred: device clock changed. Check time and reconnect."
                return
            }
            let currentTime = sample.effective
            if let created = IntentEvent.date(e.created_at), created > sample.wall {
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
        guard let snapshot = trade.policySnapshot else { throw AlpacaError.invalid("Missing policy snapshot; preserve journal.") }
        try snapshot.validate(event: e)
        let policy = hosting ? nil : snapshot.policy
        if policy != nil {
            guard pair?.role == snapshot.role, pair?.fingerprint == snapshot.pairing,
                  snapshot.accountID.isEmpty || snapshot.accountID == account.id else { throw AlpacaError.invalid("Pinned policy pairing/account changed.") }
        }
        if !sell && policy != nil { try trade.validateBuyPlans(tradeID: id, history: state.received) }
        let preference = hosting ? IntentPreferences() : state.preferences
        var price = try preference.price(e.limit_price, sell: sell)
        var checkedBinding: IntentPolicyBinding?
        if policy != nil {
            let fresh = try await api.policyBinding(symbol: e.symbol, option: e.asset == "option", accountID: account.id)
            guard self.api === api, pair?.fingerprint == snapshot.pairing else { return }
            if let pinned = trade.policyBinding, pinned != fresh { throw AlpacaError.invalid("Pinned broker instrument/account binding changed.") }
            if trade.policyBinding == nil {
                try commit { $0.trades[id]!.policyBinding = fresh }
            }
            checkedBinding = fresh
        }
        let soldForRevision = trade.sold(for: e.event_id)
        var quantity = sell ? min(max(0, e.quantity - soldForRevision), trade.owned) : max(0, e.quantity - trade.owned)
        if let policy, let binding = checkedBinding {
            if sell {
                if policy.exit_mode == "close_tracked" { quantity = trade.owned }
                if policy.exit_mode == "proportional" { quantity = min(trade.owned, try trade.proportionalDue(event: e, history: state.received)) }
            } else {
                let plan: IntentEntryPlan
                if let frozen = trade.entryPlans?[e.event_id] {
                    try frozen.validate()
                    guard frozen.event == e, frozen.snapshot == snapshot, frozen.binding == binding else { throw AlpacaError.invalid("Frozen plan identity changed.") }
                    plan = frozen
                } else {
                    let needsCost = policy.mode == "budget" || policy.max_entry_notional != nil
                    let spent = needsCost ? try trade.premiumSpent(multiplier: binding.multiplier) : 0
                    let target = try policy.target(source: e.quantity, price: price, multiplier: binding.multiplier, bought: trade.bought, spent: spent)
                    plan = IntentEntryPlan(event: e, snapshot: snapshot, target: target, price: price, binding: binding, baselineBought: trade.bought, baselineSpent: NSDecimalNumber(decimal: spent).stringValue, pricingBasis: IntentPricingBasis(preference))
                    try plan.validate()
                    try commit { if $0.trades[id]!.entryPlans == nil { $0.trades[id]!.entryPlans = [:] }; $0.trades[id]!.entryPlans![e.event_id] = plan }
                }
                price = plan.price
                quantity = max(0, plan.target - trade.bought)
                if policy.mode == "budget" || policy.max_entry_notional != nil {
                    let spent = try trade.premiumSpent(multiplier: binding.multiplier)
                    guard let price else { throw AlpacaError.invalid("Final valuation unavailable.") }
                    let premium = try IntentBrokerDecimal.multiply(Decimal(quantity), IntentExecutionPolicy.money(price))
                    let reserved = try IntentBrokerDecimal.multiply(premium, Decimal(binding.multiplier))
                    let total = try IntentBrokerDecimal.add(spent, reserved)
                    if let budget = policy.budget, total > (try IntentExecutionPolicy.money(budget)) { throw AlpacaError.invalid("Entry budget exhausted.") }
                    if let cap = policy.max_entry_notional, total > (try IntentExecutionPolicy.money(cap)) { throw AlpacaError.invalid("Entry notional cap exceeded.") }
                }
            }
        }
        let desiredQuantity = quantity
        if sell {
            let positions = try await api.positions()
            let available = positions.first(where: { $0.symbol == e.symbol }).flatMap { Decimal(string: $0.qty_available ?? "0") } ?? 0
            quantity = min(quantity, max(0, NSDecimalNumber(decimal: available).intValue))
        }
        if sell && desiredQuantity > 0 && quantity == 0 { message = "Waiting for tracked holdings to become available."; return }
        guard quantity > 0 else { try commit { $0.trades[id]!.completed = e.event_id }; return }
        // There must be no await between this revision check, durable unknown, and dispatch.
        guard state.trades[id]?.desired?.event_id == e.event_id, sell || state.trades[id]?.invalidated == false else { return }
        try Task.checkCancellation()
        guard self.api === api, pair != nil else { return }
        let clientID = "si-" + e.event_id + (sell ? "-s\(existing.count)" : "-b")
        let mutation = IntentMutation(clientID: clientID, eventID: e.event_id, sell: sell, quantity: quantity)
        try commit { $0.trades[id]!.mutations.append(mutation) }
        let dispatched = Date()
        Task { diagnosticStep(e.event_id, "order_dispatch", "client=\(clientID) quantity=\(quantity) limit=\(price ?? "market")", at: dispatched) }
        var refusal = checkedBinding == nil ? "operation_stopped" : "metadata_or_operation_stopped"
        do {
            let order = try await api.submitIntent(symbol: e.symbol, quantity: quantity, price: price, sell: sell, option: e.asset == "option", clientID: clientID, policyBinding: checkedBinding, canSubmit: { [self] in
                guard !Task.isCancelled, self.api === api, pair != nil else { refusal = "operation_stopped"; return false }
                guard state.trades[id]?.desired?.event_id == e.event_id else { refusal = "revision_changed"; return false }
                guard hosting || state.preferences.samePricing(as: preference) else { refusal = "pricing_changed"; return false }
                if policy != nil {
                    guard pair?.fingerprint == snapshot.pairing, pair?.role == snapshot.role,
                          state.trades[id]?.policySnapshot == snapshot, state.trades[id]?.policyBinding == checkedBinding else { refusal = "policy_binding_changed"; return false }
                }
                if sell { return true }
                guard let sample = entryClock.read() else { refusal = "clock_changed"; return false }
                guard state.trades[id]?.invalidated == false, state.trades[id]?.entrySkipped != true, state.trades[id]?.entryClosed != true else { refusal = "invalidated"; return false }
                guard hosting || !state.preferences.paused else { refusal = "entries_paused"; return false }
                guard let created = IntentEvent.date(e.created_at), let expiry = IntentEvent.date(e.expires_at), sample.wall >= created else { refusal = "future_created_at"; return false }
                guard sample.effective < expiry else { refusal = "expired"; return false }
                guard sample.effective.timeIntervalSince(created) <= Double(hosting ? 30 : state.preferences.maxAgeSeconds) else { refusal = "max_age"; return false }
                guard e.quantity <= (hosting ? 1000 : state.preferences.maxQuantity) else { refusal = "max_quantity"; return false }
                if let policy {
                    guard pair?.fingerprint == snapshot.pairing, pair?.role == snapshot.role,
                          e.quantity <= policy.max_source_quantity,
                          state.trades[id]?.policySnapshot == snapshot, state.trades[id]?.policyBinding == checkedBinding else { refusal = "policy_binding_changed"; return false }
                }
                return true
            })
            try mutation.validate(order, symbol: e.symbol)
            diagnosticStep(e.event_id, "broker_response", "client=\(clientID) broker=\(order.id) status=\(order.status) filled=\(order.filled_qty) average=\(order.filled_avg_price ?? "unavailable")")
            try commit { s in let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!; s.trades[id]!.mutations[index].order = order; s.trades[id]!.mutations[index].brokerResponseSession = timerSession }
            if order.status == "rejected", hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        } catch is IntentDispatchRefused {
            try commit { s in
                let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!
                s.trades[id]!.mutations[index].notSubmitted = true
                s.trades[id]!.completed = e.event_id
            }
            diagnosticStep(e.event_id, "order_not_submitted", refusal)
            message = "Not submitted before dispatch: \(refusal). Journal retained; use a new revision if needed."
        } catch AlpacaError.http(let code) where [400, 401, 403, 429].contains(code) {
            diagnosticStep(e.event_id, "broker_rejected", "HTTP \(code)")
            // A definitive HTTP refusal is a local no-order disposition, never fabricated broker proof.
            try commit { s in
                let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!
                s.trades[id]!.mutations[index].notSubmitted = true
                s.trades[id]!.completed = e.event_id
            }
            if hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        }
    }
}
