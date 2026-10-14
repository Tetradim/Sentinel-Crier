import Foundation

/// Screen OCR is untrusted evidence, never broker-confirmed execution.
struct ScreenTradeCandidate: Equatable {
    let broker: String
    let symbol: String
    let expiration: String
    let right: String
    let strike: Decimal
    let side: String
    let quantity: Int
    let price: Decimal
    let observedAt: Date

    var fingerprint: String {
        [broker, symbol, expiration, right, NSDecimalNumber(decimal: strike).stringValue,
         side, String(quantity), NSDecimalNumber(decimal: price).stringValue].joined(separator: "|")
    }
}

enum RecognitionOutcome: Equatable {
    case noFill
    case ambiguous(String)
    case candidate(ScreenTradeCandidate)
}

/// Conservative, fail-closed prototype. Recognizes a single OCC-style contract
/// and explicit FILLED state. Brokerage-specific templates are still required.
enum TradeRecognition {
    static func parse(lines: [String], broker: String, at date: Date = Date()) -> RecognitionOutcome {
        let text = lines.joined(separator: " ").uppercased()
        if text.contains("PREVIEW") || text.contains("SUBMIT ORDER") ||
            text.contains("PENDING") || text.contains("CANCELLED") ||
            text.contains("CANCELED") || text.contains("REJECTED") {
            return .noFill
        }
        guard text.range(of: #"\b(FILLED|EXECUTED)\b"#, options: .regularExpression) != nil else {
            return .noFill
        }
        // Multiple contracts in the same frame are ambiguous and must not auto-publish.
        let contractPattern = #"\b([A-Z]{1,6})\s+(\d{4}-\d{2}-\d{2})\s+([CP])\s+(\d+(?:\.\d{1,3})?)\b"#
        guard let regex = try? NSRegularExpression(pattern: contractPattern) else { return .ambiguous("Invalid contract parser") }
        let ns = text as NSString
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: ns.length))
        guard matches.count == 1, let match = matches.first else {
            return .ambiguous("Expected exactly one explicit options contract")
        }
        func group(_ index: Int) -> String { ns.substring(with: match.range(at: index)) }
        let symbol = group(1), expiry = group(2), right = group(3)
        guard let strike = Decimal(string: group(4), locale: Locale(identifier: "en_US_POSIX")) else {
            return .ambiguous("Invalid strike")
        }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withFullDate]
        guard iso.date(from: expiry) != nil else { return .ambiguous("Invalid expiry") }

        let sides = ["BUY", "SELL"].filter {
            text.range(of: "\\b" + $0 + "\\b", options: .regularExpression) != nil
        }
        guard sides.count == 1 else { return .ambiguous("Missing or conflicting side") }
        func singleCapture(_ pattern: String) -> String? {
            guard let re = try? NSRegularExpression(pattern: pattern) else { return nil }
            let found = re.matches(in: text, range: NSRange(location: 0, length: ns.length))
            guard found.count == 1, found[0].numberOfRanges > 1 else { return nil }
            return ns.substring(with: found[0].range(at: 1))
        }
        guard let qtyText = singleCapture(#"\b(?:QTY|QUANTITY)\s*:?\s*(\d+)\b"#),
              let qty = Int(qtyText), qty > 0, qty <= 100000 else {
            return .ambiguous("Quantity missing or invalid")
        }
        guard let priceText = singleCapture(#"\b(?:FILL PRICE|FILLED AT|EXECUTION PRICE)\s*:?\s*\$?(\d+(?:\.\d{1,4})?)\b"#),
              let price = Decimal(string: priceText, locale: Locale(identifier: "en_US_POSIX")),
              price > 0 else {
            return .ambiguous("Execution price missing or invalid")
        }
        return .candidate(ScreenTradeCandidate(
            broker: broker, symbol: symbol, expiration: expiry, right: right,
            strike: strike, side: sides[0], quantity: qty, price: price, observedAt: date
        ))
    }
}

/// Coalesce continuous OCR sightings. One missing frame does not re-arm
/// the same receipt; a sustained absence or a changed candidate does.
final class ScreenObservationDeduplicator {
    private var visibleFingerprint: String?
    private var missingFrames = 0
    private let missingFrameThreshold = 3

    func shouldAccept(_ candidate: ScreenTradeCandidate, at now: Date = Date()) -> Bool {
        missingFrames = 0
        guard visibleFingerprint != candidate.fingerprint else { return false }
        visibleFingerprint = candidate.fingerprint
        return true
    }

    func screenChanged() {
        missingFrames += 1
        if missingFrames >= missingFrameThreshold {
            visibleFingerprint = nil
            missingFrames = 0
        }
    }

    func reset() {
        visibleFingerprint = nil
        missingFrames = 0
    }
}
