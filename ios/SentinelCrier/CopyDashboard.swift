import Foundation
import SwiftUI

/// Incremental byte parser: bounds apply even to ignored events and comments.
struct CopySSEParser {
    struct Frame { var name: String; var data: Data }
    private var line = Data(); private var payload: [String] = []; private var name = "message"
    private var size = 0; private var lines = 0; private var carriageReturn = false
    mutating func append(_ byte: UInt8) throws -> Frame? {
        if carriageReturn { carriageReturn = false; if byte == 10 { return nil } }
        size += 1
        guard size <= 1_048_576 else { throw AlpacaError.invalid("Stream event exceeds limit.") }
        if byte != 10 && byte != 13 { line.append(byte); return nil }
        carriageReturn = byte == 13; lines += 1
        guard lines <= 8192, let text = String(data: line, encoding: .utf8) else { throw AlpacaError.invalid("Invalid stream frame.") }
        line.removeAll(keepingCapacity: true)
        if text.isEmpty {
            let frame = payload.isEmpty ? nil : Frame(name: name, data: Data(payload.joined(separator: "\n").utf8))
            name = "message"; payload = []; size = 0; lines = 0
            return frame
        }
        if text.hasPrefix(":") { return nil }
        let parts = text.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        var value = parts.count > 1 ? String(parts[1]) : ""
        if value.hasPrefix(" ") { value.removeFirst() }
        if parts[0] == "event" { name = value }
        if parts[0] == "data" { payload.append(value) }
        return nil
    }
}

struct CopyPresence: Codable {
    var version = 1; var revision: Int; var observed_at: String; var platform = "ios"
    var transport: String; var entries_enabled: Bool
}
struct CopyStatus: Codable {
    var version = 1; var event_id: String; var revision: Int; var observed_at: String
    var broker_observed_at: String?; var state: String; var target_quantity: Int?
    var bought: Int; var sold: Int; var buy_premium: String?; var sell_premium: String?
    var currency: String?; var multiplier: Int?; var fees: String?; var quote: DiagnosticQuote?; var reason: String?
    static let states = Set(["received", "submitted", "working", "partially_filled", "filled", "cancel_pending", "canceled", "closed", "blocked", "unknown", "not_submitted"])
    static let reasons = Set(["broker_unavailable", "reconciliation_required", "entries_paused", "invalid_instruction", "not_submitted", "quantity_unavailable", "expired", "clock_uncertain", "client_unavailable"])
    func validate(asset: String?) throws {
        guard version == 1, UUID(uuidString: event_id)?.uuidString.lowercased() == event_id,
              (1...9_007_199_254_740_991).contains(revision), IntentEvent.date(observed_at) != nil,
              broker_observed_at.map({ IntentEvent.date($0) != nil }) ?? true,
              Self.states.contains(state), reason.map(Self.reasons.contains) ?? true,
              (0...1_000_000).contains(bought), (0...bought).contains(sold),
              target_quantity.map({ (0...1000).contains($0) }) ?? true,
              (currency == nil && multiplier == nil) || (currency == "USD" && (asset == nil ? [1,100].contains(multiplier ?? 0) : multiplier == (asset == "stock" ? 1 : 100))) else { throw AlpacaError.invalid("Invalid observational status.") }
        for (text, units) in [(buy_premium, bought), (sell_premium, sold)] {
            if let text { guard CopyMoney.valid(text), (units > 0 ? CopyMoney.positive(text) : !CopyMoney.positive(text)) else { throw AlpacaError.invalid("Invalid premium evidence.") } }
        }
        if let fees { guard currency != nil, CopyMoney.valid(fees) else { throw AlpacaError.invalid("Invalid fees.") } }
        if let quote { guard quote.hasValidPrices, IntentEvent.date(quote.quote_timestamp) != nil, !quote.source.isEmpty, quote.source.count <= 80 else { throw AlpacaError.invalid("Invalid quote.") } }
    }
}
/// Foundation Decimal is deliberately limited to exact representable inputs. Larger
/// valid wire decimals stay unavailable instead of being silently rounded as evidence.
enum CopyMoney {
    static func valid(_ text: String) -> Bool {
        text.count <= 120 && text.range(of: #"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"#, options: .regularExpression) != nil && String(text.filter(\.isNumber)).trimmingCharacters(in: CharacterSet(charactersIn: "0")).count <= 80
    }
    static func positive(_ text: String) -> Bool { text.contains { $0 >= "1" && $0 <= "9" } }
    static func decimal(_ text: String?) -> Decimal? {
        guard let text, valid(text), text.filter(\.isNumber).count <= 38, let result = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX")), !result.isNaN else { return nil }; return result
    }
    static func display(_ value: Decimal, places: Int) -> String {
        var value = value; var rounded = Decimal(); NSDecimalRound(&rounded, &value, places, .plain)
        return NSDecimalNumber(decimal: rounded).stringValue
    }
    static func average(_ sum: String?, units: Int) -> String? {
        guard units > 0, let sum = decimal(sum) else { return nil }; return display(sum / Decimal(units), places: 8)
    }
    static func pnl(_ status: CopyStatus, net: Bool = false) -> String? {
        guard status.currency == "USD", [1,100].contains(status.multiplier ?? 0), status.bought > 0, status.bought == status.sold,
              let buy = decimal(status.buy_premium), let sell = decimal(status.sell_premium) else { return nil }
        guard !net || decimal(status.fees) != nil else { return nil }
        return display((sell - buy) * Decimal(status.multiplier!) - (net ? decimal(status.fees)! : 0), places: 2)
    }
    static func openEstimate(_ status: CopyStatus, now: Date) -> String? {
        guard status.bought > status.sold, status.currency == "USD", [1,100].contains(status.multiplier ?? 0),
              let cost = decimal(status.buy_premium), let quote = status.quote, quote.hasValidPrices,
              let time = IntentEvent.date(quote.quote_timestamp), (0...5).contains(now.timeIntervalSince(time)), let bid = decimal(quote.bid) else { return nil }
        return display((bid - cost / Decimal(status.bought)) * Decimal(status.bought-status.sold) * Decimal(status.multiplier!), places: 2)
    }
}
struct CopyDashboard: Codable {
    struct Member: Codable { var actor: String; var role: String; var revoked: Bool; var last_seen_at: String?; var presence: CopyPresence? }
    struct Status: Codable { var actor: String; var received_at: String; var report: CopyStatus }
    struct Diagnostic: Codable { var event_id: String; var actor: String; var observation: DiagnosticObservation }
    var version: Int; var channel_id: String; var environment: AlpacaEnvironment; var role: String; var actor: String
    var generated_at: String; var members: [Member]; var events: [IntentEvent]; var statuses: [Status]; var diagnostics: [Diagnostic]; var truncated: Bool
    func validate(pair: IntentPairing) throws {
        guard version == 1, UUID(uuidString: channel_id) != nil, environment == pair.environment, role == pair.role,
              (role == "host" ? actor == "host" : UUID(uuidString: actor) != nil), IntentEvent.date(generated_at) != nil,
              members.count <= 200, events.count <= 50, statuses.count <= 200, diagnostics.count <= 200 else { throw AlpacaError.invalid("Invalid dashboard scope.") }
        func permitted(_ value: String) -> Bool { (value == "host" || UUID(uuidString: value) != nil) && (role == "host" || value == "host" || value == actor) }
        for member in members {
            guard permitted(member.actor), member.role == (member.actor == "host" ? "host" : "follower"), member.last_seen_at.map({ IntentEvent.date($0) != nil }) ?? true else { throw AlpacaError.invalid("Invalid dashboard member.") }
            if let p = member.presence { guard p.version == 1, (1...9_007_199_254_740_991).contains(p.revision), ["windows","android","ios","python"].contains(p.platform), ["push","poll","connecting"].contains(p.transport), IntentEvent.date(p.observed_at) != nil else { throw AlpacaError.invalid("Invalid presence.") } }
        }
        for event in events { try event.validate(); guard event.environment == environment else { throw AlpacaError.invalid("Dashboard environment mismatch.") } }
        for status in statuses {
            guard permitted(status.actor), IntentEvent.date(status.received_at) != nil else { throw AlpacaError.invalid("Private dashboard status.") }
            let asset = events.first { $0.event_id == status.report.event_id }?.asset
            // Missing source identity is allowed only with unverified money metadata.
            try status.report.validate(asset: asset)
        }
        for diagnostic in diagnostics { guard permitted(diagnostic.actor) else { throw AlpacaError.invalid("Private dashboard diagnostic.") } }
    }
}
struct CopyTelemetryJournal: Codable {
    var pair = ""; var revision = 0; var outbox: [String: CopyStatus] = [:]; var signatures: [String: String] = [:]
    mutating func next() throws -> Int { guard revision < 9_007_199_254_740_991 else { throw AlpacaError.invalid("Report revisions exhausted.") }; revision += 1; return revision }
}

struct CopyDashboardView: View {
    @ObservedObject var controller: IntentController
    private func comparison(_ snapshot: CopyDashboard, _ event: IntentEvent, _ status: CopyDashboard.Status) -> String {
        guard status.actor != "host" else { return "Host reference evidence" }
        var lines: [String] = []
        if let host = snapshot.statuses.first(where: { $0.actor == "host" && $0.report.event_id == event.event_id })?.report {
            for sell in [false, true] {
                let local = CopyMoney.average(sell ? status.report.sell_premium : status.report.buy_premium, units: sell ? status.report.sold : status.report.bought).flatMap { Decimal(string: $0) }
                let source = CopyMoney.average(sell ? host.sell_premium : host.buy_premium, units: sell ? host.sold : host.bought).flatMap { Decimal(string: $0) }
                let delta = local.flatMap { l in source.map { CopyMoney.display(l - $0, places: 8) } } ?? "unavailable"
                lines.append("Receiver − host actual \(sell ? "exit" : "entry") premium: \(delta) (rounded)")
            }
        }
        if let sender = snapshot.diagnostics.first(where: { $0.event_id == event.event_id && $0.actor == "host" })?.observation,
           let receiver = snapshot.diagnostics.first(where: { $0.event_id == event.event_id && $0.actor == status.actor })?.observation {
            let record = IntentDiagnosticRecord(event: event, observation: sender, remote: [DiagnosticRemote(actor: status.actor, observation: receiver)])
            lines.append(record.latencyText); lines.append(record.premiumText)
        } else { lines.append("Delivery and near-event quote comparison unavailable: matching evidence required") }
        return lines.joined(separator: "\n")
    }
    var body: some View {
        List {
            Section {
                Text("Tracked status sharing includes instructions and device-reported fills only. Each device retains its own broker credentials. Balances and unrelated positions are not shared.")
                Text("Delivery: \(controller.copyTransport). iOS requires the app in the foreground.").accessibilityIdentifier("copy.transport")
                Text("Observational only. Host instructions and device fills may differ.")
            }
            if let snapshot = controller.copyDashboard {
                Section("Devices") {
                    ForEach(snapshot.members, id: \.actor) { member in
                        let age = member.last_seen_at.flatMap(IntentEvent.date).map { Date().timeIntervalSince($0) }
                        VStack(alignment: .leading) {
                            Text("\(member.actor) · \(member.role) · \(member.presence?.platform ?? "unknown")")
                            Text("\(member.presence?.transport ?? "unknown") · \(member.revoked ? "revoked" : age.map { $0 > 45 ? "stale/offline" : "seen \(Int(max(0,$0)))s ago" } ?? "last seen unknown")")
                        }.accessibilityElement(children: .combine)
                    }
                }
                Section("Host instructions and device-reported fills") {
                    ForEach(snapshot.events, id: \.trade_id) { event in
                        DisclosureGroup("\(event.symbol) · source \(event.action) \(event.quantity) @ \(event.limit_price)") {
                            Text("Source revision \(event.sequence) · \(event.created_at)")
                            ForEach(Array(snapshot.statuses.filter { $0.report.event_id == event.event_id }.enumerated()), id: \.offset) { _, status in
                                VStack(alignment: .leading) {
                                    Text("\(status.actor) · \(status.report.state) · \(status.report.reason ?? "")")
                                    Text("Local target \(status.report.target_quantity.map(String.init) ?? "unknown") · bought \(status.report.bought) · sold \(status.report.sold) · remaining \(status.report.bought-status.report.sold)")
                                    Text("Entry average \(CopyMoney.average(status.report.buy_premium, units: status.report.bought) ?? "unavailable") · exit average \(CopyMoney.average(status.report.sell_premium, units: status.report.sold) ?? "unavailable")")
                                    Text("Closed gross USD \(CopyMoney.pnl(status.report) ?? "unavailable") · net USD \(CopyMoney.pnl(status.report, net: true) ?? "unavailable")")
                                    Text("Open estimate USD \(CopyMoney.openEstimate(status.report, now: Date()) ?? "unavailable")")
                                    if let quote = status.report.quote { Text("Quote \(quote.source) as of \(quote.quote_timestamp)") }
                                    Text("Device report \(status.report.observed_at); broker observation \(status.report.broker_observed_at ?? "unknown")")
                                    Text(comparison(snapshot, event, status))
                                }.font(.caption).accessibilityElement(children: .combine)
                            }
                            if controller.state.diagnostics?[event.event_id] != nil {
                                NavigationLink("Timing and near-event premium evidence") { IntentDiagnosticsView(controller: controller, tradeID: event.trade_id) }
                            }
                        }
                    }
                    ForEach(Array(snapshot.statuses.filter { status in !snapshot.events.contains { $0.event_id == status.report.event_id } }.enumerated()), id: \.offset) { _, status in
                        Text("\(status.actor): source instruction unavailable · \(status.report.state)")
                    }
                }
                Text("Snapshot \(snapshot.generated_at). \(snapshot.truncated ? "Truncated; omitted rows prevent complete totals." : "Tracked trades only; unknown rows have no assumed value.")")
            } else { Text("Dashboard unavailable; waiting for an authorized snapshot.").accessibilityIdentifier("copy.unavailable") }
        }.navigationTitle("Copy dashboard").accessibilityIdentifier("copy.dashboard")
    }
}
