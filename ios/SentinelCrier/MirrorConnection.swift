import Foundation
import CryptoKit
import Security
import SwiftUI

struct MirrorPairing: Codable {
    let url: URL
    let token: String
    let environment: AlpacaEnvironment
    static func decode(_ text: String) throws -> MirrorPairing {
        let pair = try JSONDecoder().decode(Self.self, from: Data(text.utf8))
        _ = try QuickConnection.origin(pair.url.absoluteString)
        guard pair.token.count >= 32 else {
            throw AlpacaError.invalid("Paste the HTTPS pairing from the receiver's Mirror page.")
        }
        return pair
    }
    static let service = "com.tetradim.sentinelcrier.mirror"
    static func save(_ text: String) throws {
        let pair = try decode(text)
        let data = try JSONEncoder().encode(pair)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "receiver"]
        let result = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if result == errSecItemNotFound {
            var item = query; item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw AlpacaError.invalid("Pairing could not be saved.") }
        } else if result != errSecSuccess { throw AlpacaError.invalid("Pairing could not be updated.") }
    }
    static func load() throws -> MirrorPairing? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
            kSecAttrAccount as String: "receiver", kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw AlpacaError.invalid("Unlock the phone to read pairing.") }
        return try decode(String(decoding: data, as: UTF8.self))
    }
    static func remove() {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "receiver"] as CFDictionary)
    }
    var fingerprint: String { SHA256.hash(data: Data((url.absoluteString + token).utf8)).map { String(format: "%02x", $0) }.joined() }
}

struct MirrorFillEvent: Codable {
    static func confirmedIntent(order: AlpacaOrder, fill: AlpacaFill) throws -> String {
        guard order.id == fill.order_id, order.symbol == fill.symbol, order.side == fill.side,
              !order.client_order_id.hasPrefix("crier-m-"),
              order.order_class == "simple" || order.order_class == "",
              let intent = order.position_intent, ["buy_to_open", "sell_to_close"].contains(intent) else {
            throw AlpacaError.invalid("Source order is mirrored, complex, mismatched or has unverified intent.")
        }
        return intent
    }
    let event_id: String
    let environment: String
    let symbol: String
    let side: String
    let intent: String
    let quantity: Int
    let price: String
    let occurred_at: String
    init(fill: AlpacaFill, environment: AlpacaEnvironment, accountID: String, intent: String) throws {
        guard fill.activity_type == "FILL", let quantity = Decimal(string: fill.qty),
              quantity >= 1, quantity <= 1000, quantity == Decimal(NSDecimalNumber(decimal: quantity).intValue),
              let price = Decimal(string: fill.price), price > 0,
              (fill.side == "buy" && intent == "buy_to_open") || (fill.side == "sell" && intent == "sell_to_close") else {
            throw AlpacaError.invalid("Mirror supports whole shares and long single-leg option fills only.")
        }
        self.event_id = SHA256.hash(data: Data("\(environment.rawValue):\(accountID):\(fill.id)".utf8)).map { String(format: "%02x", $0) }.joined()
        self.environment = environment.rawValue; symbol = fill.symbol; side = fill.side; self.intent = intent
        self.quantity = NSDecimalNumber(decimal: quantity).intValue
        self.price = NSDecimalNumber(decimal: price).stringValue; occurred_at = fill.transaction_time
    }
}

actor MirrorSender {
    struct Item: Codable {
        let key: String
        let fill: AlpacaFill
        let account: String
        let environment: AlpacaEnvironment
        let pair: String
        var event: MirrorFillEvent?
        var state: String
    }
    struct State: Codable { var items: [Item] = []; var accounts: [String: String] = [:] }
    private let file: URL
    private var state: State
    private var sending = false
    init(file: URL) throws {
        self.file = file
        state = FileManager.default.fileExists(atPath: file.path) ? try JSONDecoder().decode(State.self, from: Data(contentsOf: file)) : State()
    }
    static func local() throws -> MirrorSender {
        let folder = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        return try MirrorSender(file: folder.appendingPathComponent("mirror-outbox.json"))
    }
    private func save(_ next: State) throws {
        try JSONEncoder().encode(next).write(to: file, options: [.atomic, .completeFileProtectionUnlessOpen]); state = next
    }
    func ingest(_ fills: [AlpacaFill], environment: AlpacaEnvironment, account: String) throws {
        guard let pair = try MirrorPairing.load(), pair.environment == environment else { return }
        var next = state
        if let pinned = next.accounts[pair.fingerprint], pinned != account { throw AlpacaError.invalid("Mirror pairing belongs to another source account. Create a new pairing.") }
        next.accounts[pair.fingerprint] = account
        for fill in fills {
            let key = pair.fingerprint + ":" + account + ":" + fill.id
            if !next.items.contains(where: { $0.key == key }) {
                next.items.append(Item(key: key, fill: fill, account: account, environment: environment, pair: pair.fingerprint, event: nil, state: "pending"))
            }
        }
        try save(next)
    }
    private func change(_ key: String, status: String, event: MirrorFillEvent? = nil) throws {
        var next = state
        guard let index = next.items.firstIndex(where: { $0.key == key }) else { return }
        next.items[index].state = status
        if let event { next.items[index].event = event }
        try save(next)
    }
    func deliver(api: AlpacaREST, account: String, permit: OAuthEffectPermit = OAuthEffectPermit(), observe: (@Sendable (HealthObservation, HealthReason) async -> Void)? = nil) async throws -> String {
        guard !sending else { return "Mirror delivery in progress." }
        sending = true; defer { sending = false }
        guard let pair = try MirrorPairing.load() else { return "Not paired." }
        guard pair.environment == api.environment else { return "Pairing is for \(pair.environment.rawValue)." }
        let items = state.items.filter { $0.state == "pending" && $0.account == account && $0.environment == api.environment && $0.pair == pair.fingerprint }
        if items.isEmpty { await observe?(.idle, .noWork) }
        var message = "Paired. Waiting for new fills."
        for item in items {
            let event: MirrorFillEvent
            if let saved = item.event { event = saved }
            else {
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                var time = formatter.date(from: item.fill.transaction_time)
                if time == nil {
                    formatter.formatOptions = [.withInternetDateTime]
                    time = formatter.date(from: item.fill.transaction_time)
                }
                guard let time, Date().timeIntervalSince(time) <= 60, Date().timeIntervalSince(time) >= -5 else {
                    try change(item.key, status: "skipped: expired timestamp"); continue
                }
                let order = try await api.orderByID(item.fill.order_id)
                do {
                    let intent = try MirrorFillEvent.confirmedIntent(order: order, fill: item.fill)
                    event = try MirrorFillEvent(fill: item.fill, environment: item.environment, accountID: item.account, intent: intent)
                }
                catch { try change(item.key, status: "skipped: unsupported fill"); continue }
                try change(item.key, status: "pending", event: event)
            }
            // Immutable event and receiver deduplication make transport retries safe.
            var request = URLRequest(url: pair.url.appendingPathComponent("api/mirror/events"))
            request.httpMethod = "POST"; request.timeoutInterval = 15
            request.setValue("Bearer " + pair.token, forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(event)
            guard permit.isCurrent, !Task.isCancelled else { return "Mirror delivery stopped; journal retained." }
            let (data, response) = try await CrierHTTPSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw AlpacaError.invalid("Mirror receiver unavailable.") }
            if http.statusCode == 422 { try change(item.key, status: "skipped: expired or invalid"); await observe?(.blocked, .rejected); message = "Receiver skipped an expired or unsupported fill."; continue }
            guard http.statusCode == 200 else { throw AlpacaError.invalid("Mirror delivery pending (HTTP \(http.statusCode)). Check pairing and receiver.") }
            struct Result: Decodable { let state: String; let note: String }
            let result = try JSONDecoder().decode(Result.self, from: data)
            // Unknown is retried only for receiver reconciliation, never a second POST to the broker.
            if result.state != "unknown" { try change(item.key, status: result.state) }
            await observe?(result.state == "unknown" ? .blocked : .healthy, result.state == "unknown" ? .reconciliationRequired : .delivered)
            message = "Mirror: \(result.state). \(result.note)"
            if result.state == "unknown" { break }
        }
        return message
    }
}

struct MirrorConnectionForm: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var pairing = ""
    @State private var status = ""
    var body: some View {
        Section("Direct mirroring") {
            Text("Send confirmed fills directly to a paired PC receiver. It places matching orders when its owner enables Follow.").font(.footnote)
            SecureField("Paste receiver pairing", text: $pairing).textInputAutocapitalization(.never).autocorrectionDisabled()
            Button("Save pairing") {
                do { try MirrorPairing.save(pairing); pairing = ""; status = "Paired. Future fills will be sent while Crier is active." }
                catch { status = error.localizedDescription }
            }
            Button("Stop sharing / remove pairing", role: .destructive) { MirrorPairing.remove(); status = "Sharing stopped. Existing receiver orders remain at the brokerage." }
            Text(status.isEmpty ? model.mirrorMessage : status).font(.footnote)
            Text("Paper follows paper; live follows live. Keep Crier open. Source fills are checked during foreground refresh; this is not a background screen watcher.").font(.caption).foregroundStyle(.secondary)
        }
    }
}
