import Foundation

enum BrokerScreenTemplate {
    case webull, tradier, generic

    init(name: String) {
        switch name.lowercased() {
        case "webull": self = .webull
        case "tradier": self = .tradier
        default: self = .generic
        }
    }

    /// Recognize receipt context; never convert an order-entry screen into a fill.
    func recognize(lines: [String], observedAt: Date = Date()) -> RecognitionOutcome {
        let text = lines.joined(separator: " ").uppercased()
        let broker: String
        switch self {
        case .webull:
            broker = "WEBULL"
            guard text.contains("WEBULL") else { return .ambiguous("Webull identity not visible") }
        case .tradier:
            broker = "TRADIER"
            guard text.contains("TRADIER") else { return .ambiguous("Tradier identity not visible") }
        case .generic:
            return .ambiguous("Unknown brokerage screen; review required")
        }
        // Strictly require the word FILLED or EXECUTED; reject partial, previews
        // and order submission pages until broker-specific semantics are verified.
        guard !text.contains("PARTIALLY FILLED"), !text.contains("PARTIAL FILL"),
              !text.contains("NOT FILLED"), !text.contains("UNFILLED"),
              !text.contains("0 FILLED"),
              !text.contains("ORDER PREVIEW"), !text.contains("ORDER PLACED"),
              !text.contains("ORDER SUBMITTED") else { return .noFill }
        return TradeRecognition.parse(lines: lines, broker: broker, at: observedAt)
    }
}
