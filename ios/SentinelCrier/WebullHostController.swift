import Foundation
import SwiftUI
import Security

/// A dedicated credential slot. Never overwrites IntentPairing's Alpaca slot.
struct WebullHostPairVault {
    private var query: [String: Any] { [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.tetradim.sentinelcrier.webull-host", kSecAttrAccount as String: "pairing"] }
    func load() throws -> IntentPairing? {
        var q = query; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw AlpacaError.invalid("Webull pairing Keychain unavailable.") }
        return try IntentPairing.decode(String(decoding: data, as: UTF8.self))
    }
    func save(_ pair: IntentPairing) throws {
        let data = try JSONEncoder().encode(pair)
        var item = query; item[kSecValueData as String] = data; item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecDuplicateItem {
            guard SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary) == errSecSuccess else { throw AlpacaError.invalid("Could not save Webull host pairing.") }
        } else if status != errSecSuccess { throw AlpacaError.invalid("Could not save Webull host pairing.") }
    }
}
struct WebullHostAPI {
    let base: URL
    let session: URLSession
    init(_ text: String, session: URLSession = CrierHTTPSession.shared) throws {
        guard let parts = URLComponents(string: text), parts.scheme == "https", parts.host != nil,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.port == nil, !parts.percentEncodedPath.contains("%"), let url = parts.url else { throw AlpacaError.invalid("Configure an exact trusted HTTPS Webull gateway URL.") }
        base = url; self.session = session
    }
    func call<T: Decodable>(_ path: String, customer: CustomerSession, query: [URLQueryItem] = [], body: Data? = nil) async throws -> T {
        guard let expiry = customer.expiresAt, expiry.timeIntervalSinceNow > 30, !customer.access_token.isEmpty else { throw AlpacaError.invalid("Sign in or refresh your Crier customer session in Provider connections.") }
        var parts = URLComponents(url: base.appendingPathComponent("v1/" + path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { parts.queryItems = query }
        var request = URLRequest(url: parts.url!); request.timeoutInterval = 20
        request.httpMethod = body == nil ? "GET" : "POST"; request.httpBody = body
        request.setValue("Bearer " + customer.access_token, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.url == request.url, (200..<300).contains(http.statusCode), data.count <= 262144 else { throw AlpacaError.invalid("Webull gateway unavailable, provider approval pending, or request refused. Source outcome may be unknown; reconcile before another order.") }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
@MainActor final class WebullHostController: ObservableObject {
    // Navigation can disappear while a network request is in flight. One owner
    // prevents a reopened screen from loading a stale, competing journal copy.
    static let shared = WebullHostController()
    struct Capabilities: Decodable { var available: Bool; var environments: [String]; var stocks: [String]; var options: Bool; var authorization_available: Bool? }
    struct Connection: Decodable { var state: String; var environment: String; var account_id: String? }
    private struct Begin: Decodable { var authorization_url: String; var flow_id: String }
    private struct AuthorizationStatus: Decodable { var state: String; var generation: Int }
    private struct Position: Decodable { var symbol: String; var quantity: Int }
    private struct OrderRequest: Encodable {
        var client_order_id: String; var account_id: String; var environment: String; var asset: String
        var symbol: String; var quantity: Int; var limit_price: String; var side: String
    }
    @Published private(set) var state = WebullHostState()
    @Published private(set) var message = "Webull service unconfigured. Provider approval and a deployed gateway are required."
    @Published private(set) var busy = false
    @Published private(set) var capabilities: Capabilities?
    @Published private(set) var connection: Connection?
    @Published private(set) var invitation = ""
    @Published private(set) var paired = false
    @Published private(set) var authorizationState: String?
    private var api: WebullHostAPI?
    private var pair: IntentPairing?
    private var blocked = false
    private var publishing = false
    private var active = false
    private var pollCursor = 0
    private var generation = UUID()
    func clearConnection() { generation = UUID(); api = nil; connection = nil; capabilities = nil; authorizationState = nil }
    func setActive(_ value: Bool) { active = value; if !value { clearConnection() } }
    private let file: URL
    private let session: URLSession
    init(file: URL? = nil, session: URLSession = CrierHTTPSession.shared, pairing: IntentPairing? = nil, loadPairing: Bool = true) {
        self.session = session
        self.file = file ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("webull-host-v1.json")
        do {
            if FileManager.default.fileExists(atPath: self.file.path) { state = try JSONDecoder().decode(WebullHostState.self, from: Data(contentsOf: self.file)); try state.validate() }
            pair = try pairing ?? (loadPairing ? WebullHostPairVault().load() : nil)
            if let pair {
                guard pair.role == "host", pair.environment == .paper, state.pairingID.isEmpty || state.pairingID == pair.fingerprint else { throw AlpacaError.invalid("Webull pairing journal mismatch.") }
                if state.pairingID.isEmpty { try commit { $0.pairingID = pair.fingerprint } }
                paired = true
            }
        } catch { blocked = true; message = "Webull recovery blocked: \(error.localizedDescription). Journal retained." }
    }
    private func commit(_ change: (inout WebullHostState) throws -> Void) throws {
        guard !blocked else { throw AlpacaError.invalid("Webull recovery journal is blocked.") }
        var next = state; try change(&next); try next.validate()
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONEncoder().encode(next).write(to: file, options: [.atomic, .completeFileProtection])
        state = next
    }
    private func identity(_ customer: CustomerSession?) throws -> CustomerSession {
        guard active, !blocked, let customer, customer.user.id == state.owner, customer.serviceURL == state.authService,
              api?.base.absoluteString == state.service else { throw AlpacaError.invalid("Connect this Webull host with the original Crier customer and gateway first.") }
        guard let expiry = customer.expiresAt, expiry.timeIntervalSinceNow > 30 else { throw AlpacaError.invalid("Refresh the Crier customer session before continuing.") }
        return customer
    }
    private func context(_ environment: String) -> [URLQueryItem] { [URLQueryItem(name: "environment", value: environment)] }
    private func context(_ trade: WebullHostTrade) -> [URLQueryItem] { context(trade.environment) + [URLQueryItem(name: "account_id", value: trade.account)] }
    func connect(service: String, environment: String, customer: CustomerSession?) async {
        guard active, !busy else { return }; busy = true; defer { busy = false }
        let stamp = generation
        connection = nil; capabilities = nil
        do {
            guard let customer, let auth = customer.serviceURL, (try? ProviderAPI(base: auth)) != nil else { throw AlpacaError.invalid("Sign in to Crier through Provider connections first.") }
            let candidate = try WebullHostAPI(service, session: session)
            guard state.owner.isEmpty || (state.owner == customer.user.id && state.authService == auth && state.service == candidate.base.absoluteString) else { throw AlpacaError.invalid("This journal belongs to another customer or service. Preserve it for recovery.") }
            // First explicit Check pins this HTTPS service to the retained customer journal.
            let caps: Capabilities = try await candidate.call("capabilities", customer: customer)
            guard caps.available || caps.authorization_available == true, caps.environments.contains(environment), caps.environments.allSatisfy({ ["sandbox", "production"].contains($0) }) else { throw AlpacaError.invalid("Webull provider approval pending or environment unavailable.") }
            let value: Connection = try await candidate.call("connection", customer: customer, query: context(environment))
            var authorization: AuthorizationStatus?
            if caps.authorization_available == true { authorization = try await candidate.call("connect/status", customer: customer, query: context(environment)) }
            guard value.environment == environment, ["connected", "authorization_required", "unavailable"].contains(value.state), value.state != "connected" || !(value.account_id ?? "").isEmpty else { throw AlpacaError.invalid("Invalid Webull connection identity.") }
            guard active, generation == stamp, !Task.isCancelled else { return }
            try commit { $0.owner = customer.user.id; $0.authService = auth; $0.service = candidate.base.absoluteString }
            api = candidate; capabilities = caps; connection = value
            authorizationState = authorization?.state
            message = !caps.available ? "Webull authorization service ready; the trading adapter remains unavailable." : value.state == "connected" ? "Webull \(environment) connected. Receiver route: Alpaca PAPER." : "Official Webull authorization required; approval may be pending."
        } catch { message = error.localizedDescription }
    }
    func authorize(environment: String, customer: CustomerSession?) async -> URL? {
        guard !busy, let api else { return nil }; busy = true; defer { busy = false }
        let stamp = generation
        do {
            let customer = try identity(customer)
            let value: Begin = try await api.call("connect/begin", customer: customer, body: JSONEncoder().encode(["environment": environment]))
            let url = try WebullHostRules.authorizationURL(value.authorization_url, service: api.base)
            guard !value.flow_id.isEmpty, active, generation == stamp, !Task.isCancelled else { return nil }
            message = "Complete official Webull consent, then Check connection again."
            return url
        } catch { message = error.localizedDescription; return nil }
    }
    func authorizationAction(_ action: String, environment: String, customer: CustomerSession?) async {
        guard !busy, let api, ["refresh", "revoke"].contains(action), capabilities?.authorization_available == true else { return }
        busy = true; defer { busy = false }; let stamp = generation
        do {
            let customer = try identity(customer)
            let value: AuthorizationStatus = try await api.call("connect/" + action, customer: customer, body: JSONEncoder().encode(["environment": environment]))
            guard active, generation == stamp else { return }
            authorizationState = value.state
            if action == "revoke" { connection = nil }
            message = action == "revoke" ? "Crier's saved Webull access removed. Revoke the grant itself in Webull if needed. Broker orders and receiver holdings remain." : "Webull authorization refreshed."
        } catch { message = error.localizedDescription }
    }
    func createPair(service: String) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        do {
            guard !blocked, pair == nil, state.pairingID.isEmpty, state.trades.isEmpty else { throw AlpacaError.invalid("Existing host route retained; it cannot be replaced while this journal exists.") }
            let value = try await QuickConnection.host(service: service, environment: .paper)
            guard value.role == "host", value.environment == .paper else { throw AlpacaError.invalid("Only a PAPER receiver host route is permitted.") }
            try WebullHostPairVault().save(value)
            try commit { $0.pairingID = value.fingerprint }
            pair = value; paired = true; message = "Separate Webull host route created for Alpaca PAPER receivers."
        } catch { message = error.localizedDescription }
    }
    func invite() async {
        guard let pair, !busy else { return }; busy = true; defer { busy = false }
        do { invitation = try await QuickConnection.invite(pair) } catch { message = error.localizedDescription }
    }
    private func ready(environment: String, customer: CustomerSession?, acknowledged: Bool) throws -> CustomerSession {
        let customer = try identity(customer)
        guard acknowledged, capabilities?.available == true, let connection, connection.state == "connected", connection.environment == environment,
              pair?.role == "host", pair?.environment == .paper, state.pairingID == pair?.fingerprint else { throw AlpacaError.invalid("Check the source account, pair a PAPER receiver, and acknowledge the source-to-paper route.") }
        return customer
    }
    func confirm(symbol: String, asset: String, quantity: Int, price: String, environment: String, acknowledged: Bool, customer: CustomerSession?) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        do {
            let customer = try ready(environment: environment, customer: customer, acknowledged: acknowledged)
            guard asset != "option" || capabilities?.options == true else { throw AlpacaError.invalid("Gateway options approval pending.") }
            var id = ""
            try commit {
                id = try $0.enter(symbol: symbol, asset: asset, quantity: quantity, price: price, environment: environment, account: connection!.account_id!, stocks: capabilities?.stocks ?? [])
                try $0.prepareOrder(trade: id, quantity: quantity, price: price, sell: false)
            }
            // Durable paper intent exists before this first and only source POST attempt.
            Task { await self.publish() }
            try await submit(id, customer: customer)
            message = "Confirmed instruction journaled. Reconcile source and paper receiver independently."
        } catch { message = error.localizedDescription }
    }
    private func submit(_ id: String, customer: CustomerSession) async throws {
        guard active, let api, let trade = state.trades[id], let order = trade.orders.last, connection?.state == "connected", connection?.account_id == trade.account, connection?.environment == trade.environment else { throw AlpacaError.invalid("Source session changed; unknown journal retained for GET recovery.") }
        let body = OrderRequest(client_order_id: order.clientID, account_id: trade.account, environment: trade.environment, asset: trade.asset, symbol: trade.symbol, quantity: order.quantity, limit_price: order.price, side: order.sell ? "sell" : "buy")
        // No retry here, including on HTTP refusal. GET reconciliation is the only recovery path.
        let receipt: WebullHostReceipt = try await api.call("orders", customer: customer, body: JSONEncoder().encode(body))
        try commit { try $0.accept(trade: id, receipt: receipt) }
        Task { await self.publish() }
    }
    private func reconcileTrade(_ id: String, customer: CustomerSession) async throws {
        guard let api, let trade = state.trades[id] else { throw AlpacaError.invalid("Unknown Webull trade.") }
        for order in trade.orders { // Terminal orders are read too, to catch contradictory late fills.
            let receipt: WebullHostReceipt = try await api.call("orders/" + order.clientID, customer: customer, query: context(trade))
            try commit { try $0.accept(trade: id, receipt: receipt) }
        }
    }
    func reconcile(customer: CustomerSession?, automatic: Bool = false) async {
        guard !busy, api != nil else { return }; busy = true; defer { busy = false }
        do {
            let customer = try identity(customer)
            if automatic {
                // At most one pending-order read per five-second foreground tick.
                // Closed history is refreshed explicitly at mutation boundaries,
                // not forever in the background against Webull's user quota.
                let pending = state.trades.keys.sorted().flatMap { id in
                    (state.trades[id]?.orders ?? []).filter { !$0.terminal }.map { (id, $0.clientID) }
                }
                if !pending.isEmpty, let api {
                    let selected = pending[pollCursor % pending.count]; pollCursor = (pollCursor + 1) % pending.count
                    guard let trade = state.trades[selected.0] else { return }
                    let receipt: WebullHostReceipt = try await api.call("orders/" + selected.1, customer: customer, query: context(trade))
                    try commit { try $0.accept(trade: selected.0, receipt: receipt) }
                }
            } else {
                for id in state.trades.keys.sorted() { try await reconcileTrade(id, customer: customer) }
            }
            message = "Source receipts reconciled; no order was resubmitted."
        } catch { message = "Reconciliation pending: \(error.localizedDescription)" }
        await publish()
    }
    private func cancelSource(_ id: String, customer: CustomerSession) async throws {
        try await reconcileTrade(id, customer: customer)
        let currentCustomer = try identity(customer)
        guard let api, let trade = state.trades[id] else { throw AlpacaError.invalid("Source connection changed during cancellation.") }
        for order in trade.orders where !order.terminal {
            _ = try identity(currentCustomer)
            // The cancellation attempt is durable before transport. A future explicit retry is allowed after GET.
            try commit { s in
                guard let index = s.trades[id]?.orders.firstIndex(where: { $0.clientID == order.clientID }) else { return }
                s.trades[id]?.orders[index].cancelRequested = true
            }
            let receipt: WebullHostReceipt = try await api.call("orders/" + order.clientID + "/cancel", customer: customer, body: JSONEncoder().encode(["environment": trade.environment, "account_id": trade.account]))
            try commit { try $0.accept(trade: id, receipt: receipt) }
        }
        try await reconcileTrade(id, customer: customer)
        guard state.trades[id]?.settled == true else { throw AlpacaError.invalid("Source cancellation is not terminal. Reconcile again before replacement or exit.") }
    }
    func cancel(_ id: String, customer: CustomerSession?) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        do {
            let customer = try identity(customer)
            guard let trade = state.trades[id] else { return }
            try commit { try $0.instruction(trade: id, action: "cancel", quantity: trade.desired.quantity, price: trade.desired.limit_price) }
            Task { await self.publish() }
            try await cancelSource(id, customer: customer)
            message = "Cancel journaled for PAPER receiver; source cancellation reconciled. Existing fills remain owned."
        } catch { message = error.localizedDescription }
    }
    func revise(_ id: String, quantity: Int, price: String, acknowledged: Bool, customer: CustomerSession?) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        do {
            guard let original = state.trades[id] else { return }
            let customer = try ready(environment: original.environment, customer: customer, acknowledged: acknowledged)
            guard connection?.account_id == original.account, ["enter", "replace"].contains(original.desired.action) else { throw AlpacaError.invalid("Only an active entry on this source account can be revised.") }
            try WebullHostRules.validate(symbol: original.symbol, asset: original.asset, quantity: quantity, price: price, stocks: capabilities?.stocks ?? [])
            try await cancelSource(id, customer: customer)
            _ = try ready(environment: original.environment, customer: customer, acknowledged: acknowledged)
            guard let trade = state.trades[id], ["enter", "replace"].contains(trade.desired.action), quantity >= trade.bought, trade.orders.allSatisfy({ !$0.sell }) else { throw AlpacaError.invalid("Revised target cannot be below reconciled source buys; exits require a separate instruction.") }
            try commit { s in
                try s.instruction(trade: id, action: "replace", quantity: quantity, price: price)
                if quantity > trade.bought { try s.prepareOrder(trade: id, quantity: quantity - trade.bought, price: price, sell: false) }
            }
            Task { await self.publish() }; if quantity > trade.bought { try await submit(id, customer: customer) }
            message = "Revised remaining source entry and paper target journaled."
        } catch { message = error.localizedDescription }
    }
    func exit(_ id: String, quantity: Int, price: String, acknowledged: Bool, customer: CustomerSession?) async {
        guard !busy else { return }; busy = true; defer { busy = false }
        do {
            guard let original = state.trades[id], let api else { return }
            let customer = try ready(environment: original.environment, customer: customer, acknowledged: acknowledged)
            guard connection?.account_id == original.account else { throw AlpacaError.invalid("Check the original source account before exit.") }
            try WebullHostRules.price(price)
            try await cancelSource(id, customer: customer)
            guard let trade = state.trades[id] else { return }
            let position: Position = try await api.call("positions/" + trade.symbol, customer: customer, query: context(trade))
            guard position.symbol == trade.symbol else { throw AlpacaError.invalid("Broker position differs from tracked symbol.") }
            _ = try ready(environment: original.environment, customer: customer, acknowledged: acknowledged)
            let amount = try WebullHostRules.exitQuantity(requested: quantity, tracked: trade.owned, held: position.quantity)
            try commit { s in
                try s.instruction(trade: id, action: "exit", quantity: amount, price: price)
                try s.prepareOrder(trade: id, quantity: amount, price: price, sell: true)
            }
            Task { await self.publish() }; try await submit(id, customer: customer)
            message = "Bounded exit journaled for source and PAPER receiver."
        } catch { message = error.localizedDescription }
    }
    func publish() async {
        guard active, !blocked, !publishing, let pair, pair.role == "host", pair.environment == .paper, state.pairingID == pair.fingerprint else { return }
        publishing = true; defer { publishing = false }
        do {
            // Strict FIFO: a rejection cancel must never overtake an earlier queued enter.
            while active, let event = state.outgoing.first, !Task.isCancelled {
                var request = URLRequest(url: pair.url.appendingPathComponent("api/sync/events"))
                request.timeoutInterval = 20; request.httpMethod = "POST"; request.httpBody = try JSONEncoder().encode(event)
                request.setValue("Bearer " + pair.token, forHTTPHeaderField: "Authorization")
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                let (_, response) = try await session.data(for: request)
                guard let http = response as? HTTPURLResponse, http.url == request.url, (200..<300).contains(http.statusCode) else { throw AlpacaError.invalid("Paper relay refused the queued revision; outbox retained in sequence order.") }
                try commit { $0.outgoing.removeAll { $0.event_id == event.event_id } }
            }
        } catch { message = "Paper receiver outbox pending: \(error.localizedDescription)" }
    }
}
