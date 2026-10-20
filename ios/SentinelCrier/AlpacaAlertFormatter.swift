import Foundation
import CryptoKit

enum AlpacaAlertFormatter {
    static func instrument(_ symbol: String) -> String {
        guard let expression = try? NSRegularExpression(pattern: "^([A-Z]{1,6})([0-9]{2})([0-9]{2})([0-9]{2})([CP])([0-9]{8})$"),
              let match = expression.firstMatch(in: symbol, range: NSRange(symbol.startIndex..., in: symbol)) else { return symbol }
        func part(_ index: Int) -> String {
            guard let range = Range(match.range(at: index), in: symbol) else { return "" }
            return String(symbol[range])
        }
        guard let strike = Decimal(string: part(6)) else { return symbol }
        let price = NSDecimalNumber(decimal: strike / 1000).stringValue
        return "\(part(1)) $\(price)\(part(5)) · \(part(3))-\(part(4))-20\(part(2))"
    }

    static func payload(_ delivery: AlpacaJournal.Delivery, style: String) -> [String: Any] {
        let fill = delivery.fill
        let ref = SHA256.hash(data: Data(delivery.id.utf8)).prefix(6).map { String(format: "%02x", $0) }.joined()
        let environment = delivery.environment.rawValue.uppercased()
        let heading = instrument(fill.symbol)
        let evidence = "\(fill.side.uppercased()) · Alpaca \(environment) · \(fill.transaction_time)"
        let filled = "Filled **\(fill.qty)× @ $\(fill.price)**"
        var result: [String: Any] = ["allowed_mentions": ["parse": []]]
        if style == "card" {
            result["embeds"] = [["title": heading, "description": filled + "\n" + evidence,
                                  "color": fill.side == "buy" ? 5763719 : 15548997,
                                  "footer": ["text": "Broker-confirmed · Ref \(ref)"]]]
        } else if style == "homebrew" {
            let icon = fill.side == "buy" ? "🟢" : "🔴"
            result["content"] = "\(icon) **\(heading)**\n\(filled)\n\(evidence)\nBroker-confirmed · Ref \(ref)"
        } else {
            result["content"] = "\(environment) · BROKER-CONFIRMED FILL\n\(fill.side.uppercased()) \(fill.qty) \(heading) @ $\(fill.price)\nBroker time: \(fill.transaction_time)\nRef \(ref)"
        }
        return result
    }
}
