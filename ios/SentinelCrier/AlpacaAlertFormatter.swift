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

/// User text is bounded, mentions disabled, and provenance is always appended.
struct DiscordAlertSettings: Codable {
    var template = "{side} {quantity} {symbol} @ ${price}"
    var showTime = true
    var showReference = true
    static func load(_ defaults: UserDefaults = .standard) -> Self {
        guard let data = defaults.data(forKey: "discordAlertSettings"), let value = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        return value
    }
    func save(_ defaults: UserDefaults = .standard) throws {
        guard template.count <= 1200 else { throw AlpacaError.invalid("Alert template must be at most 1,200 characters.") }
        defaults.set(try JSONEncoder().encode(self), forKey: "discordAlertSettings")
    }
    func render(_ delivery: AlpacaJournal.Delivery) -> String {
        let fill = delivery.fill
        let values = ["{side}": fill.side.uppercased(), "{quantity}": fill.qty, "{symbol}": AlpacaAlertFormatter.instrument(fill.symbol), "{price}": fill.price, "{environment}": delivery.environment.rawValue.uppercased()]
        var text = String(template.prefix(1200))
        for (key, value) in values { text = text.replacingOccurrences(of: key, with: value) }
        text += "\n" + delivery.environment.rawValue.uppercased() + " · BROKER-CONFIRMED FILL"
        if showTime { text += "\nBroker time: " + fill.transaction_time }
        if showReference {
            let ref = SHA256.hash(data: Data(delivery.id.utf8)).prefix(6).map { String(format: "%02x", $0) }.joined()
            text += "\nRef " + ref
        }
        return text
    }
    func payload(_ delivery: AlpacaJournal.Delivery, style: String) -> [String: Any] {
        let text = render(delivery)
        if style == "card" {
            return ["allowed_mentions": ["parse": []], "embeds": [["title": "Broker-confirmed fill", "description": text, "color": 5763719]]]
        }
        return ["allowed_mentions": ["parse": []], "content": text]
    }
    static var preview: AlpacaJournal.Delivery {
        AlpacaJournal.Delivery(id: "preview", environment: .paper, accountID: "preview", fill: AlpacaFill(id: "preview", activity_type: "FILL", order_id: "preview", symbol: "SPY261218C00750000", side: "buy", qty: "2", price: "0.20", transaction_time: "2026-10-23T14:00:00Z"), state: "preview", messageID: nil, retryAfter: nil)
    }
    static func test(session: URLSession = CrierHTTPSession.shared) async throws -> String {
        guard let webhook = StandaloneConfiguration.webhook() else { throw AlpacaError.invalid("Save a Discord webhook first.") }
        var parts = URLComponents(url: webhook, resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "wait", value: "true")]
        guard let url = parts.url else { throw AlpacaError.invalid("Invalid webhook.") }
        let settings = load()
        var payload = settings.payload(preview, style: UserDefaults.standard.string(forKey: "discordFillStyle") ?? "plain")
        if let content = payload["content"] as? String { payload["content"] = "TEST ONLY · sample data, no broker execution\n" + content }
        if var embeds = payload["embeds"] as? [[String: Any]] { embeds[0]["title"] = "TEST ONLY · sample data, no broker execution"; payload["embeds"] = embeds }
        var request = URLRequest(url: url); request.httpMethod = "POST"; request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = object["id"] as? String, !id.isEmpty, id.allSatisfy({ $0.isNumber }) else { throw AlpacaError.invalid("Test not confirmed. Check Discord before retrying to avoid a duplicate.") }
        return "Test delivered • message " + id
    }
}
