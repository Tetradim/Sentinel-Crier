import Foundation
import Security

// Official personal Trading API only. Credentials and account IDs never choose a host.
enum AlpacaEnvironment: String, Codable, CaseIterable, Identifiable {
    case paper, live
    var id: String { rawValue }
    var baseURL: URL { URL(string: self == .paper ? "https://paper-api.alpaca.markets" : "https://api.alpaca.markets")! }
}
struct AlpacaCredentials: Codable {
    let key: String; let secret: String
    let bearer: String?; let owner: String?; let serviceURL: String?
    init(key: String, secret: String) { self.key = key; self.secret = secret; bearer = nil; owner = nil; serviceURL = nil }
    init(bearer: String, owner: String, serviceURL: String? = nil) { key = ""; secret = ""; self.bearer = bearer; self.owner = owner; self.serviceURL = serviceURL }
    func authorize(_ request: inout URLRequest) throws {
        if let bearer {
            guard key.isEmpty, secret.isEmpty, !bearer.isEmpty, bearer.count <= 8192,
                  !bearer.contains(where: { $0.isWhitespace || $0.isNewline }),
                  let owner, UUID(uuidString: owner) != nil, let serviceURL, (try? ProviderAPI(base: serviceURL)) != nil else { throw AlpacaError.invalid("Invalid OAuth credentials.") }
            request.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization")
        } else {
            guard owner == nil, serviceURL == nil, !key.isEmpty, !secret.isEmpty else { throw AlpacaError.invalid("Both API key and secret are required.") }
            request.setValue(key, forHTTPHeaderField: "APCA-API-KEY-ID")
            request.setValue(secret, forHTTPHeaderField: "APCA-API-SECRET-KEY")
        }
    }
}
enum AlpacaKeychain {
    static func query(_ environment: AlpacaEnvironment) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.tetradim.sentinelcrier.alpaca", kSecAttrAccount as String: environment.rawValue]
    }
    static func save(_ credentials: AlpacaCredentials, environment: AlpacaEnvironment) throws {
        var validation = URLRequest(url: environment.baseURL); try credentials.authorize(&validation)
        let data = try JSONEncoder().encode(credentials)
        let q = query(environment)
        var item = q
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecDuplicateItem {
            guard SecItemUpdate(q as CFDictionary, [kSecValueData as String: data] as CFDictionary) == errSecSuccess else { throw AlpacaError.invalid("Keychain update failed.") }
        } else if status != errSecSuccess { throw AlpacaError.invalid("Keychain save failed.") }
    }
    static func load(_ environment: AlpacaEnvironment) throws -> AlpacaCredentials {
        var q = query(environment); q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { throw AlpacaError.invalid("Save API credentials for this environment first.") }
        return try JSONDecoder().decode(AlpacaCredentials.self, from: data)
    }
    static func remove(_ environment: AlpacaEnvironment) { SecItemDelete(query(environment) as CFDictionary) }
}
enum AlpacaError: LocalizedError {
    case invalid(String), http(Int), unknownSubmission
    var errorDescription: String? {
        switch self {
        case .invalid(let text): return text
        case .http(let status): return "Alpaca HTTP \(status). Check account permissions and order parameters."
        case .unknownSubmission: return "Submission outcome is unknown. Reconcile the saved client ID; do not place a replacement order."
        }
    }
}
struct AlpacaAccount: Codable {
    let id: String; let status: String; let buying_power: String; let equity: String
    let trading_blocked: Bool; let account_blocked: Bool
    let options_trading_level: Int?
    var currency: String? = nil
}
struct AlpacaPosition: Codable, Identifiable {
    var id: String { symbol }
    let symbol: String; let qty: String; let qty_available: String?; let avg_entry_price: String; let market_value: String?
}
struct AlpacaContract: Codable, Identifiable, Hashable {
    let id: String; let symbol: String; let name: String; let status: String
    let tradable: Bool; let expiration_date: String; let strike_price: String; let type: String
    let size: String?
}
struct AlpacaContractPage: Codable { let option_contracts: [AlpacaContract]; let next_page_token: String? }
struct AlpacaOrder: Codable, Identifiable {
    let id: String; let client_order_id: String; let symbol: String; let status: String
    let qty: String?; let limit_price: String?; let filled_qty: String; let filled_avg_price: String?; let side: String
    var position_intent: String?
    var order_class: String?
}
struct AlpacaFill: Codable, Identifiable, Equatable {
    let id: String; let activity_type: String; let order_id: String; let symbol: String
    let side: String; let qty: String; let price: String; let transaction_time: String
}
struct AlpacaTicket: Codable, Equatable, Identifiable {
    let id: String
    let environment: AlpacaEnvironment
    let accountID: String
    let symbol: String
    let quantity: Int
    let limitPrice: Decimal
    let side: String
    let positionIntent: String?
    let multiplier: Int
    let reviewedAt: Date
    func validate(now: Date = Date()) throws {
        guard !accountID.isEmpty, !symbol.isEmpty, quantity > 0, limitPrice > 0,
              ["buy", "sell"].contains(side), multiplier == 1 || multiplier == 100,
              reviewedAt <= now, now.timeIntervalSince(reviewedAt) < 60,
              id.count <= 48, !id.isEmpty else { throw AlpacaError.invalid("Order review expired or invalid. Review again.") }
        if multiplier == 100 {
            guard let intent = positionIntent,
                  (side == "buy" && intent == "buy_to_open") || (side == "sell" && intent == "sell_to_close") else { throw AlpacaError.invalid("Only buy-to-open and sell-to-close single-leg options are supported.") }
        } else if positionIntent != nil && !(side == "sell" && positionIntent == "sell_to_close") { throw AlpacaError.invalid("Unsupported stock position intent.") }
    }
    func body() throws -> Data {
        var values: [String: Any] = ["symbol": symbol, "qty": String(quantity), "side": side,
            "type": "limit", "time_in_force": "day", "limit_price": NSDecimalNumber(decimal: limitPrice).stringValue,
            "client_order_id": id]
        if let positionIntent { values["position_intent"] = positionIntent }
        return try JSONSerialization.data(withJSONObject: values)
    }
}
final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
enum CrierHTTPSession {
    static let shared = URLSession(configuration: .ephemeral, delegate: NoRedirectDelegate(), delegateQueue: nil)
}
final class AlpacaREST {
    let environment: AlpacaEnvironment
    private let credentials: AlpacaCredentials
    private let session: URLSession
    private let lifetime = OAuthEffectPermit()
    func invalidate() { lifetime.invalidate() }
    var permitsMutations: Bool { lifetime.isCurrent }
    func freshClient(customer: CustomerSession?) throws -> AlpacaREST {
        if credentials.owner != nil {
            guard OAuthOwnership.matches(owner: credentials.owner, serviceURL: credentials.serviceURL, customer: customer) else { throw AlpacaError.invalid("Original Crier customer and service required to resume.") }
        }
        return AlpacaREST(environment: environment, credentials: credentials, session: session)
    }
    init(environment: AlpacaEnvironment, credentials: AlpacaCredentials, session: URLSession = CrierHTTPSession.shared) {
        self.environment = environment; self.credentials = credentials; self.session = session
    }
    @MainActor private func request(_ path: String, query: [URLQueryItem] = [], method: String = "GET", body: Data? = nil, permit: OAuthEffectPermit? = nil, canSubmit: (@MainActor () -> Bool)? = nil) async throws -> Data {
        var parts = URLComponents(url: environment.baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { parts.queryItems = query }
        var request = URLRequest(url: parts.url!); request.httpMethod = method; request.httpBody = body; request.timeoutInterval = 20
        try credentials.authorize(&request)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        guard (method == "GET" || lifetime.isCurrent), permit?.isCurrent != false, !Task.isCancelled else {
            if canSubmit != nil { throw IntentDispatchRefused() }
            throw AlpacaError.invalid("Broker operation stopped before dispatch.")
        }
        guard canSubmit?() != false else { throw IntentDispatchRefused() }
        // Never retry POST, including transport failures and throttling.
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AlpacaError.invalid("Invalid broker response.") }
        guard (200..<300).contains(http.statusCode) else { throw AlpacaError.http(http.statusCode) }
        return data
    }
    func diagnosticQuote(symbol: String, option: Bool) async throws -> DiagnosticQuote {
        var parts = URLComponents(string: "https://data.alpaca.markets" + (option ? "/v1beta1/options/quotes/latest" : "/v2/stocks/\(symbol)/quotes/latest"))!
        parts.queryItems = [URLQueryItem(name: "feed", value: option ? "opra" : "iex")]
        if option { parts.queryItems!.append(URLQueryItem(name: "symbols", value: symbol)) }
        var request = URLRequest(url: parts.url!); request.timeoutInterval = 10
        try credentials.authorize(&request)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AlpacaError.invalid("Live quote unavailable (feed permission or transport failure).") }
        struct Quote: Decodable { var t: String; var bp: Decimal?; var ap: Decimal? }
        struct Response: Decodable { var quote: Quote?; var quotes: [String: Quote]? }
        let body = try JSONDecoder().decode(Response.self, from: data)
        guard let quote = option ? body.quotes?[symbol] : body.quote, IntentEvent.date(quote.t) != nil else { throw AlpacaError.invalid("Quote missing for exact contract.") }
        let result = DiagnosticQuote(source: option ? "alpaca:opra" : "alpaca:iex", quote_timestamp: quote.t, bid: quote.bp.map { NSDecimalNumber(decimal: $0).stringValue }, ask: quote.ap.map { NSDecimalNumber(decimal: $0).stringValue }, last: nil)
        guard result.hasValidPrices else { throw AlpacaError.invalid("Quote contains invalid or crossed prices.") }
        return result
    }
    func account() async throws -> AlpacaAccount { try JSONDecoder().decode(AlpacaAccount.self, from: await request("v2/account")) }
    func positions() async throws -> [AlpacaPosition] { try JSONDecoder().decode([AlpacaPosition].self, from: await request("v2/positions")) }
    func contracts(underlying: String, expiration: String) async throws -> [AlpacaContract] {
        var result: [AlpacaContract] = []; var token: String?; var seen = Set<String>()
        repeat {
            var query = [URLQueryItem(name: "underlying_symbols", value: underlying), URLQueryItem(name: "expiration_date", value: expiration), URLQueryItem(name: "status", value: "active"), URLQueryItem(name: "limit", value: "1000")]
            if let token { query.append(URLQueryItem(name: "page_token", value: token)) }
            let page = try JSONDecoder().decode(AlpacaContractPage.self, from: await request("v2/options/contracts", query: query))
            result += page.option_contracts.filter { $0.tradable && $0.status == "active" && $0.size == "100" }
            token = page.next_page_token
            if let token, !token.isEmpty, !seen.insert(token).inserted { throw AlpacaError.invalid("Repeated contract page token.") }
        } while token != nil && token != ""
        return result
    }
    func validateStock(_ symbol: String) async throws {
        struct Asset: Decodable { let tradable: Bool; let status: String; let assetClass: String
            enum CodingKeys: String, CodingKey { case tradable, status; case assetClass = "class" }
        }
        let asset = try JSONDecoder().decode(Asset.self, from: await request("v2/assets/" + symbol))
        guard asset.tradable, asset.status == "active", asset.assetClass == "us_equity" else { throw AlpacaError.invalid("Select an active tradable US stock.") }
    }
    func submit(_ ticket: AlpacaTicket, permit: OAuthEffectPermit? = nil) async throws -> AlpacaOrder {
        try ticket.validate()
        guard ticket.environment == environment else { throw AlpacaError.invalid("Environment changed. Review again.") }
        return try JSONDecoder().decode(AlpacaOrder.self, from: await request("v2/orders", method: "POST", body: ticket.body(), permit: permit))
    }
    func policyBinding(symbol: String, option: Bool, accountID: String) async throws -> IntentPolicyBinding {
        let verified = try await account()
        guard verified.id == accountID, verified.currency == "USD", verified.status == "ACTIVE", !verified.trading_blocked, !verified.account_blocked else { throw AlpacaError.invalid("Advanced follower policies require a verified active USD account.") }
        struct Instrument: Decodable {
            var id: String; var symbol: String; var status: String; var tradable: Bool
            var assetClass: String?; var size: String?; var currency: String?
            enum CodingKeys: String, CodingKey { case id, symbol, status, tradable, size, currency; case assetClass = "class" }
        }
        let path = option ? "v2/options/contracts/" : "v2/assets/"
        let instrument = try JSONDecoder().decode(Instrument.self, from: await request(path + symbol))
        guard !instrument.id.isEmpty, instrument.symbol == symbol, instrument.status == "active", instrument.tradable,
              instrument.currency == nil || instrument.currency == "USD",
              option ? (instrument.size == "100" && (instrument.assetClass == nil || instrument.assetClass == "us_option")) : instrument.assetClass == "us_equity" else { throw AlpacaError.invalid("USD instrument identity or standard multiplier could not be verified.") }
        return IntentPolicyBinding(accountID: accountID, environment: environment, symbol: symbol, asset: option ? "option" : "stock", instrumentID: instrument.id, multiplier: option ? 100 : 1, currency: "USD")
    }
    func submitIntent(symbol: String, quantity: Int, price: String?, sell: Bool, option: Bool, clientID: String, policyBinding binding: IntentPolicyBinding? = nil, canSubmit: (@MainActor () -> Bool)? = nil) async throws -> AlpacaOrder {
        if let binding {
            do {
                let fresh = try await policyBinding(symbol: symbol, option: option, accountID: binding.accountID)
                guard fresh == binding, binding.environment == environment, binding.symbol == symbol, binding.asset == (option ? "option" : "stock") else { throw IntentDispatchRefused() }
            } catch { throw IntentDispatchRefused() }
        }
        var body: [String: Any] = ["symbol": symbol, "qty": String(quantity), "side": sell ? "sell" : "buy", "type": price == nil ? "market" : "limit", "time_in_force": "day", "client_order_id": clientID]
        if let price { body["limit_price"] = price }
        if option || sell { body["position_intent"] = sell ? "sell_to_close" : "buy_to_open" }
        return try JSONDecoder().decode(AlpacaOrder.self, from: await request("v2/orders", method: "POST", body: JSONSerialization.data(withJSONObject: body), canSubmit: canSubmit))
    }
    func order(clientID: String) async throws -> AlpacaOrder {
        try JSONDecoder().decode(AlpacaOrder.self, from: await request("v2/orders:by_client_order_id", query: [URLQueryItem(name: "client_order_id", value: clientID)]))
    }
    func orderByID(_ id: String) async throws -> AlpacaOrder {
        guard !id.isEmpty, id.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }) else { throw AlpacaError.invalid("Invalid broker order ID.") }
        return try JSONDecoder().decode(AlpacaOrder.self, from: await request("v2/orders/" + id))
    }
    func cancel(orderID: String, permit: OAuthEffectPermit? = nil, canCancel: (@MainActor () -> Bool)? = nil) async throws { _ = try await request("v2/orders/" + orderID, method: "DELETE", permit: permit, canSubmit: canCancel) }
    func fills(pageToken: String? = nil) async throws -> [AlpacaFill] {
        var query = [URLQueryItem(name: "direction", value: "desc"), URLQueryItem(name: "page_size", value: "100")]
        if let pageToken { query.append(URLQueryItem(name: "page_token", value: pageToken)) }
        return try JSONDecoder().decode([AlpacaFill].self, from: await request("v2/account/activities/FILL", query: query))
    }
}

extension AlpacaKeychain {
    static func savePairing(_ token: String) throws {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.tetradim.sentinelcrier.intent", kSecAttrAccount as String: "relay"]
        let data = Data(token.utf8)
        let status = SecItemUpdate(q as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = q; item[kSecValueData as String] = data; item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw AlpacaError.invalid("Pairing Keychain write failed.") }
        } else if status != errSecSuccess { throw AlpacaError.invalid("Pairing Keychain update failed.") }
    }
    static func loadPairing() throws -> String {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.tetradim.sentinelcrier.intent", kSecAttrAccount as String: "relay", kSecReturnData as String: true]
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { throw AlpacaError.invalid("Unlock to load relay pairing.") }
        return String(decoding: data, as: UTF8.self)
    }
}
