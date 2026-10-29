import SwiftUI
import Security

struct ConnectionRoute: Codable, Identifiable {
    let id: String
    var name: String
    var account: String?
    var environment: AlpacaEnvironment?
    var legacy: Bool { id == "legacy" }
}

/// Account ownership is durable, including while disconnected. MainActor serializes
/// competing account() completions before either route may start execution.
@MainActor final class ConnectionRouteRegistry: ObservableObject {
    private struct State: Codable { var routes: [ConnectionRoute]; var selected: String; var reservations: [String: String]? = nil }
    @Published private(set) var routes: [ConnectionRoute]
    @Published private(set) var selected: String
    private let file: URL
    private var reservations: [String: String] = [:]
    init(file: URL) throws {
        self.file = file
        let state = FileManager.default.fileExists(atPath: file.path)
            ? try JSONDecoder().decode(State.self, from: Data(contentsOf: file))
            : State(routes: [ConnectionRoute(id: "legacy", name: "Original connection")], selected: "legacy")
        guard state.routes.count <= 16,
              state.routes.allSatisfy({ !$0.name.isEmpty && $0.name.count <= 80 && (($0.account == nil && $0.environment == nil) || ($0.account?.isEmpty == false && $0.environment != nil)) }),
              state.routes.filter({ $0.legacy }).count == 1,
              Set(state.routes.map(\.id)).count == state.routes.count,
              state.routes.allSatisfy({ $0.legacy || UUID(uuidString: $0.id)?.uuidString.lowercased() == $0.id }),
              state.routes.contains(where: { $0.id == state.selected }) else {
            throw AlpacaError.invalid("Connection registry invalid; preserve it for recovery.")
        }
        routes = state.routes; selected = state.selected; reservations = state.reservations ?? [:]
        let bound = routes.compactMap { route -> String? in
            guard let account = route.account, let environment = route.environment else { return nil }
            return environment.rawValue + ":" + account
        }
        guard reservations.allSatisfy({ key, owner in
            owner == "legacy" && (key.hasPrefix("paper:") || key.hasPrefix("live:")) && key.split(separator: ":", maxSplits: 1).count == 2
        }) else { throw AlpacaError.invalid("Invalid historical account reservations.") }
        guard Set(bound).count == bound.count else { throw AlpacaError.invalid("Conflicting account ownership; execution disabled.") }
    }
    private func save(_ next: [ConnectionRoute], selected: String) throws {
        try JSONEncoder().encode(State(routes: next, selected: selected, reservations: reservations)).write(to: file, options: [.atomic, .completeFileProtection])
        routes = next; self.selected = selected
    }
    @discardableResult func add() throws -> ConnectionRoute {
        guard routes.count < 16 else { throw AlpacaError.invalid("A maximum of 16 connections is supported.") }
        let route = ConnectionRoute(id: UUID().uuidString.lowercased(), name: "Connection \(routes.count + 1)")
        try save(routes + [route], selected: route.id); return route
    }
    func select(_ id: String) throws {
        guard routes.contains(where: { $0.id == id }) else { throw AlpacaError.invalid("Unknown connection.") }
        try save(routes, selected: id)
    }
    func bind(_ id: String, account: String, environment: AlpacaEnvironment) throws {
        guard !account.isEmpty, let index = routes.firstIndex(where: { $0.id == id }) else { throw AlpacaError.invalid("Unknown account route.") }
        let route = routes[index]
        let key = environment.rawValue + ":" + account
        let historicalLegacy = route.legacy && reservations[key] == "legacy"
        guard route.account == nil || (route.account == account && route.environment == environment) || historicalLegacy else {
            throw AlpacaError.invalid("This connection is permanently pinned to its original account and environment. Add another connection.")
        }
        guard !routes.contains(where: { $0.id != id && $0.account == account && $0.environment == environment }) else {
            throw AlpacaError.invalid("This Alpaca account and environment already belong to another connection, including disconnected connections.")
        }
        guard reservations[key] == nil || reservations[key] == id else { throw AlpacaError.invalid("This account has retained history in another connection.") }
        var next = routes; next[index].account = account; next[index].environment = environment
        let previous = reservations
        if route.legacy { reservations[key] = "legacy" }
        do { try save(next, selected: selected) } catch { reservations = previous; throw error }
    }
    func reserveLegacyHistory(support: URL) throws {
        var keys = Set<String>()
        let journal = support.appendingPathComponent("alpaca-journal.json")
        if FileManager.default.fileExists(atPath: journal.path) {
            let history = try JSONDecoder().decode(AlpacaJournal.State.self, from: Data(contentsOf: journal))
            for row in history.submissions { keys.insert(row.ticket.environment.rawValue + ":" + row.ticket.accountID) }
            for row in history.deliveries { keys.insert(row.environment.rawValue + ":" + row.accountID) }
            keys.formUnion(history.baselines.keys)
        }
        let intent = support.appendingPathComponent("SentinelCrier/intent-v1.json")
        if FileManager.default.fileExists(atPath: intent.path) {
            let history = try JSONDecoder().decode(IntentState.self, from: Data(contentsOf: intent))
            if !history.accountID.isEmpty {
                // Old journals do not always retain an environment outside their
                // events. Reserve both conservatively instead of guessing.
                for environment in AlpacaEnvironment.allCases { keys.insert(environment.rawValue + ":" + history.accountID) }
            }
        }
        var next = reservations
        for key in keys {
            guard next[key] == nil || next[key] == "legacy" else { throw AlpacaError.invalid("Legacy journal ownership conflicts with another route.") }
            guard !routes.contains(where: { route in !route.legacy && key == (route.environment?.rawValue ?? "") + ":" + (route.account ?? "") }) else { throw AlpacaError.invalid("Legacy account is already assigned to another route.") }
            next[key] = "legacy"
        }
        let previous = reservations; reservations = next
        do { try save(routes, selected: selected) } catch { reservations = previous; throw error }
    }
}

/// No migration/copy: the original route continues to use its exact old paths.
struct ConnectionRouteStorage {
    let route: ConnectionRoute
    var defaults: UserDefaults { route.legacy ? .standard : UserDefaults(suiteName: "com.tetradim.sentinelcrier.route." + route.id)! }
    func folder() throws -> URL {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let folder = support.appendingPathComponent("SentinelCrier/routes/" + route.id)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder
    }
    private func query(_ name: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.tetradim.sentinelcrier.route." + route.id, kSecAttrAccount as String: name]
    }
    private func read(_ name: String) throws -> Data {
        var q = query(name); q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var value: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &value) == errSecSuccess, let data = value as? Data else { throw AlpacaError.invalid("Unlock and save this connection's credentials first.") }
        return data
    }
    private func write(_ name: String, data: Data) throws {
        let q = query(name); var item = q; item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecDuplicateItem {
            guard SecItemUpdate(q as CFDictionary, [kSecValueData as String: data] as CFDictionary) == errSecSuccess else { throw AlpacaError.invalid("Connection Keychain update failed.") }
        } else if status != errSecSuccess { throw AlpacaError.invalid("Connection Keychain save failed.") }
    }
    func credentials(_ environment: AlpacaEnvironment) throws -> AlpacaCredentials {
        if route.legacy { return try AlpacaKeychain.load(environment) }
        return try JSONDecoder().decode(AlpacaCredentials.self, from: read(environment.rawValue))
    }
    func save(_ credentials: AlpacaCredentials, environment: AlpacaEnvironment) throws {
        if route.legacy { try AlpacaKeychain.save(credentials, environment: environment); return }
        var request = URLRequest(url: environment.baseURL); try credentials.authorize(&request)
        try write(environment.rawValue, data: JSONEncoder().encode(credentials))
    }
    func remove(_ environment: AlpacaEnvironment) {
        if route.legacy { AlpacaKeychain.remove(environment) } else { SecItemDelete(query(environment.rawValue) as CFDictionary) }
    }
    func pairing() throws -> IntentPairing? {
        if route.legacy { return try IntentPairing.load() }
        guard let data = defaults.data(forKey: "intent-pairing-metadata") else { return nil }
        var pair = try JSONDecoder().decode(IntentPairing.self, from: data)
        pair.token = String(decoding: try read("relay"), as: UTF8.self)
        return try IntentPairing.decode(String(decoding: JSONEncoder().encode(pair), as: UTF8.self))
    }
    func save(_ pair: IntentPairing) throws {
        if route.legacy { try pair.save(); return }
        if let previous = try pairing(), previous.fingerprint != pair.fingerprint { throw AlpacaError.invalid("Pairing is pinned to this connection. Add another connection.") }
        try write("relay", data: Data(pair.token.utf8))
        var metadata = pair; metadata.token = ""
        defaults.set(try JSONEncoder().encode(metadata), forKey: "intent-pairing-metadata")
    }
}

@MainActor final class ConnectionRoutes: ObservableObject {
    let registry: ConnectionRouteRegistry
    @Published private(set) var sessions: [String: AlpacaWorkspace] = [:]
    @Published var selected: String
    init() throws {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
        registry = try ConnectionRouteRegistry(file: support.appendingPathComponent("connection-routes-v1.json"))
        try registry.reserveLegacyHistory(support: support)
        selected = registry.selected
        for route in registry.routes { sessions[route.id] = AlpacaWorkspace(routeStorage: ConnectionRouteStorage(route: route), routeRegistry: registry) }
    }
    var model: AlpacaWorkspace { sessions[selected]! }
    func select(_ id: String) throws { try registry.select(id); selected = id }
    func add() throws {
        let route = try registry.add()
        sessions[route.id] = AlpacaWorkspace(routeStorage: ConnectionRouteStorage(route: route), routeRegistry: registry)
        selected = route.id
    }
    func stopAll() async {
        for model in sessions.values { model.oauthStopWorkers() }
        for model in sessions.values { await model.drainStoppedWork() }
    }
    func sceneActive(_ active: Bool) async {
        if !active { for model in sessions.values { model.oauthStopWorkers() } }
        for model in sessions.values { await model.sceneActive(active) }
    }
    func refresh() async { for model in sessions.values { await model.refresh() } }
}
