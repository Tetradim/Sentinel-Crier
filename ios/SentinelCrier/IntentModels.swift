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

// Shared by load and every atomic controller commit. Extracted workers cannot
// bypass the same policy and local-disposition invariants as a restored journal.
extension IntentState {
    func validateJournal() throws {
        for trade in trades.values {
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
    }
}
