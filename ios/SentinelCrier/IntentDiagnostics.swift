import Foundation
import SwiftUI
import UniformTypeIdentifiers

struct DiagnosticClock {
    var offset: Double; var uncertainty: Double; var sampled: Date; var sampledUptime: Double
    static func make(start: Date, end: Date, elapsed: Double, server: Double, uptime: Double = ProcessInfo.processInfo.systemUptime) -> Self? {
        guard elapsed.isFinite, (0...60).contains(elapsed), abs(end.timeIntervalSince(start) - elapsed) <= 0.1, server.isFinite else { return nil }
        let offset = server - (start.timeIntervalSince1970 + end.timeIntervalSince1970) * 500
        guard offset.isFinite, abs(offset) <= 604_800_000 else { return nil }
        return Self(offset: offset, uncertainty: elapsed * 500, sampled: end, sampledUptime: uptime)
    }
    func fresh(at date: Date, uptime: Double = ProcessInfo.processInfo.systemUptime) -> Bool {
        let wall = date.timeIntervalSince(sampled), elapsed = uptime - sampledUptime
        return (0...60).contains(wall) && (0...60).contains(elapsed) && abs(wall - elapsed) <= 0.1
    }
}
struct DiagnosticQuote: Codable {
    var source: String; var quote_timestamp: String; var bid: String?; var ask: String?; var last: String?
    var hasValidPrices: Bool {
        var prices: [String: Decimal] = [:]
        for (field, text) in [("bid", bid), ("ask", ask), ("last", last)] {
            guard let text else { continue }
            guard text.count <= 40,
                  text.range(of: #"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"#, options: .regularExpression) != nil,
                  let price = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX")),
                  NSDecimalNumber(decimal: price).doubleValue.isFinite,
                  price >= 0, price <= Decimal(1_000_000_000_000 as Int64) else { return false }
            prices[field] = price
        }
        guard prices.values.contains(where: { $0 > 0 }) else { return false }
        if let bid = prices["bid"], let ask = prices["ask"], ask < bid { return false }
        return true
    }
}
struct DiagnosticObservation: Codable {
    var stage: String; var observed_at: String; var clock_offset_ms: Double?; var clock_uncertainty_ms: Double?; var clock_sampled_at: String?
    var quote: DiagnosticQuote?; var quote_error: String?
}
struct DiagnosticRemote: Codable { var actor: String; var observation: DiagnosticObservation }
struct DiagnosticLatency {
    var milliseconds: Double; var uncertainty: Double
    static func corrected(_ observation: DiagnosticObservation) -> (Double, Double)? {
            guard let time = IntentEvent.date(observation.observed_at), let sampled = observation.clock_sampled_at.flatMap(IntentEvent.date),
                  (0...60).contains(time.timeIntervalSince(sampled)), let offset = observation.clock_offset_ms, let uncertainty = observation.clock_uncertainty_ms,
                  offset.isFinite, abs(offset) <= 604_800_000, uncertainty.isFinite, (0...30_000).contains(uncertainty) else { return nil }
            return (time.timeIntervalSince1970 * 1000 + offset, uncertainty)
    }
    static func measure(_ sender: DiagnosticObservation, _ receiver: DiagnosticObservation) -> Self? {
        guard sender.stage == "sender", receiver.stage == "receiver", let s = corrected(sender), let r = corrected(receiver), r.0 - s.0 >= -(s.1 + r.1) else { return nil }
        return Self(milliseconds: r.0 - s.0, uncertainty: s.1 + r.1)
    }
}
struct DiagnosticStep: Codable { var at: String; var stage: String; var detail: String }
struct IntentDiagnosticRecord: Codable {
    var event: IntentEvent; var observation: DiagnosticObservation; var timeline: [DiagnosticStep] = []; var remote: [DiagnosticRemote] = []
    var uploaded = false; var attempts = 0; var quoteComplete = false; var fetchAttempts = 0
    static func timestamp(_ date: Date = Date()) -> String {
        let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return formatter.string(from: date)
    }
    static func csvCell(_ value: String) -> String {
        let safe = ["=", "+", "-", "@", "\t", "\r", "\n"].contains(where: value.hasPrefix) ? "'" + value : value
        return "\"" + safe.replacingOccurrences(of: "\"", with: "\"\"") + "\""
    }
    var latencyText: String {
        let observations = remote.map(\.observation) + [observation]
        guard let sender = observations.first(where: { $0.stage == "sender" }), let receiver = observations.first(where: { $0.stage == "receiver" }), let value = DiagnosticLatency.measure(sender, receiver) else { return "Latency unavailable — fresh clock samples required" }
        return String(format: "Estimated delivery %.1f ms ± %.1f ms", value.milliseconds, value.uncertainty)
    }
    static func premium(_ observation: DiagnosticObservation, sell: Bool) -> Decimal? {
        guard DiagnosticLatency.corrected(observation) != nil,
              observation.quote_error == nil, let quote = observation.quote, quote.hasValidPrices, ["alpaca:iex", "alpaca:opra"].contains(quote.source),
              let quoteTime = IntentEvent.date(quote.quote_timestamp), let observed = IntentEvent.date(observation.observed_at),
              let offset = observation.clock_offset_ms, let sampled = observation.clock_sampled_at.flatMap(IntentEvent.date),
              (0...60).contains(observed.timeIntervalSince(sampled)),
              abs(quoteTime.timeIntervalSince(observed.addingTimeInterval(offset / 1000))) <= 5,
              let price = (sell ? quote.bid : quote.ask).flatMap({ Decimal(string: $0) }), price > 0 else { return nil }
        return price
    }
    var premiumText: String {
        guard event.action != "cancel" else { return "Premium comparison not applicable to cancel" }
        let observations = remote.map(\.observation) + [observation]
        guard let sender = observations.first(where: { $0.stage == "sender" }), let receiver = observations.first(where: { $0.stage == "receiver" }),
              sender.quote?.source == receiver.quote?.source,
              let source = Self.premium(sender, sell: event.action == "exit"), let destination = Self.premium(receiver, sell: event.action == "exit") else { return "Premium delta unavailable — matching feed and quotes within 5 seconds required" }
        return "Receiver − sender premium: " + NSDecimalNumber(decimal: destination - source).stringValue
    }
    var csv: String {
        let header = "event_id,trade_id,action,actor,stage,observed_at,clock_offset_ms,clock_uncertainty_ms,clock_sampled_at,quote_source,quote_timestamp,bid,ask,quote_error,timeline_at,timeline_stage,timeline_detail\n"
        let rows = timeline.isEmpty ? [DiagnosticStep(at: observation.observed_at, stage: observation.stage, detail: "")] : timeline
        func row(_ o: DiagnosticObservation, actor: String, step: DiagnosticStep?) -> String {
            var cells = [event.event_id, event.trade_id, event.action, actor, o.stage, o.observed_at]
            cells += [o.clock_offset_ms.map { String($0) } ?? "", o.clock_uncertainty_ms.map { String($0) } ?? "", o.clock_sampled_at ?? ""]
            cells += [o.quote?.source ?? "", o.quote?.quote_timestamp ?? "", o.quote?.bid ?? "", o.quote?.ask ?? "", o.quote_error ?? ""]
            cells += [step?.at ?? "", step?.stage ?? "", step?.detail ?? ""]
            return cells.map(Self.csvCell).joined(separator: ",")
        }
        let local = rows.map { row(observation, actor: "local", step: $0) }
        let shared = remote.map { row($0.observation, actor: $0.actor, step: nil) }
        return header + (local + shared).joined(separator: "\n")
    }
}
struct DiagnosticExport: Transferable {
    var data: Data; var name: String
    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .data) { export in
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let url = folder.appendingPathComponent(export.name)
            try export.data.write(to: url, options: [.atomic, .completeFileProtection])
            return SentTransferredFile(url)
        }
    }
}
struct IntentDiagnosticsView: View {
    @ObservedObject var controller: IntentController
    let tradeID: String
    var body: some View {
        List {
            ForEach((controller.state.diagnostics ?? [:]).values.filter { $0.event.trade_id == tradeID }.sorted { $0.event.sequence < $1.event.sequence }, id: \.event.event_id) { record in
                Section("Revision \(record.event.sequence) · \(record.event.action)") {
                    Text(record.event.event_id).font(.caption).textSelection(.enabled)
                    Text(record.latencyText)
                    Text(record.premiumText)
                    if let quote = record.observation.quote {
                        Text("Near-event snapshot · \(quote.source) · \(quote.quote_timestamp)").font(.caption)
                        Text("\(record.event.action == "exit" ? "Bid" : "Ask"): \((record.event.action == "exit" ? quote.bid : quote.ask) ?? "unavailable")")
                        Text(IntentDiagnosticRecord.premium(record.observation, sell: record.event.action == "exit") == nil ? "Stale or unverified timestamp — excluded from premium comparison" : "Quote observation; execution price may differ").font(.caption)
                    } else { Text(record.observation.quote_error ?? "Quote capture pending") }
                    ForEach(Array(record.timeline.enumerated()), id: \.offset) { _, step in
                        VStack(alignment: .leading) { Text(step.stage); Text("\(step.at) · \(step.detail)").font(.caption) }
                    }
                    ShareLink(item: DiagnosticExport(data: (try? JSONEncoder().encode(record)) ?? Data(), name: "diagnostics-\(record.event.event_id).json"), preview: SharePreview("Trade diagnostics JSON")) { Text("Share JSON") }
                    ShareLink(item: DiagnosticExport(data: Data(record.csv.utf8), name: "diagnostics-\(record.event.event_id).csv"), preview: SharePreview("Trade diagnostics CSV")) { Text("Share CSV") }
                }
            }
        }.navigationTitle("Trade diagnostics")
    }
}
