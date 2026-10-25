import Foundation
import Security
import CryptoKit
import SwiftUI

/// Only this exact dedicated Edge base is trusted. The relay token is never used here.
struct ProviderAPI {
    let base: URL
    let session: URLSession
    init(base: String, session: URLSession = CrierHTTPSession.shared) throws {
        guard base.range(of: #"^https://[a-z]{20}\.supabase\.co/functions/v1/crier-oauth\z"#, options: .regularExpression) != nil,
              let url = URL(string: base) else { throw AlpacaError.invalid("Use an exact trusted Supabase OAuth function URL.") }
        self.base = url; self.session = session
    }
    static var defaultBase: String {
        let relay = QuickConnection.defaultService
        guard relay.hasSuffix("/functions/v1/crier") else { return "" }
        return String(relay.dropLast("crier".count)) + "crier-oauth"
    }
    func call<T: Decodable>(_ path: String, body: [String: String]? = nil, token: String? = nil) async throws -> T {
        var request = URLRequest(url: base.appendingPathComponent(path)); request.timeoutInterval = 20
        request.httpMethod = body == nil ? "GET" : "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        if let body {
            let data = try JSONEncoder().encode(body)
            guard data.count <= 8192 else { throw AlpacaError.invalid("Customer request is too large.") }
            request.httpBody = data
        }
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.url == request.url,
              (200..<300).contains(http.statusCode), data.count <= 65536 else {
            throw AlpacaError.invalid("Provider service unavailable or request refused. Start a new flow after an uncertain redemption.")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
struct CustomerSession: Codable {
    struct User: Codable { let id: String }
    let access_token: String; let refresh_token: String; let expires_in: Double; let token_type: String; let user: User
    var expiresAt: Date?
    var serviceURL: String?
    func validated(now: Date = Date()) throws -> CustomerSession {
        guard UUID(uuidString: user.id) != nil, token_type == "bearer", expires_in.isFinite,
              expires_in > 0, expires_in <= 86400, !access_token.isEmpty, !refresh_token.isEmpty,
              access_token.count <= 16384, refresh_token.count <= 16384,
              !access_token.contains(where: { $0.isWhitespace }) else { throw AlpacaError.invalid("Invalid customer session.") }
        // A fresh token must have a bounded JWT expiry; editable metadata never supplies owner identity.
        let segments = access_token.split(separator: ".", omittingEmptySubsequences: false)
        guard segments.count == 3 else { throw AlpacaError.invalid("Invalid customer token.") }
        var encoded = String(segments[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        encoded += String(repeating: "=", count: (4 - encoded.count % 4) % 4)
        guard let data = Data(base64Encoded: encoded), let claims = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let exp = claims["exp"] as? Double, exp > now.timeIntervalSince1970,
              exp <= now.timeIntervalSince1970 + 86400, claims["sub"] as? String == user.id else { throw AlpacaError.invalid("Expired or mismatched customer session.") }
        var result = self; result.expiresAt = min(Date(timeIntervalSince1970: exp), now.addingTimeInterval(expires_in)); return result
    }
}
enum OAuthOwnership {
    static func matches(owner: String?, serviceURL: String?, customer: CustomerSession?) -> Bool {
        guard let owner, UUID(uuidString: owner) != nil, let serviceURL,
              (try? ProviderAPI(base: serviceURL)) != nil else { return false }
        return customer?.user.id == owner && customer?.serviceURL == serviceURL
    }
}
protocol CustomerSessionStorage {
    func load() -> CustomerSession?
    func save(_ value: CustomerSession?) throws
    func binding() -> CustomerSessionVault.Binding?
    func saveBinding(_ binding: CustomerSessionVault.Binding?) throws
}
/// Production custody uses Keychain; unhosted unit tests inject an in-memory store.
struct CustomerSessionVault: CustomerSessionStorage {
    var service = "com.tetradim.sentinelcrier.customer"
    private var query: [String: Any] { [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "session"] }
    struct Binding: Codable, Equatable { let owner: String; let serviceURL: String }
    func binding() -> Binding? {
        var q = query; q[kSecAttrAccount as String] = "identity"; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(Binding.self, from: data)
    }
    func saveBinding(_ binding: Binding?) throws {
        var q = query; q[kSecAttrAccount as String] = "identity"
        guard let binding else { SecItemDelete(q as CFDictionary); return }
        let data = try JSONEncoder().encode(binding)
        var item = q; item[kSecValueData as String] = data; item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecDuplicateItem {
            guard SecItemUpdate(q as CFDictionary, [kSecValueData as String: data] as CFDictionary) == errSecSuccess else { throw AlpacaError.invalid("Identity Keychain unavailable.") }
        } else if status != errSecSuccess { throw AlpacaError.invalid("Identity Keychain unavailable.") }
    }
    func load() -> CustomerSession? {
        var q = query; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(CustomerSession.self, from: data)
    }
    func save(_ value: CustomerSession?) throws {
        guard let value else { SecItemDelete(query as CFDictionary); return }
        guard let serviceURL = value.serviceURL else { throw AlpacaError.invalid("Customer service provenance missing.") }
        try saveBinding(Binding(owner: value.user.id, serviceURL: serviceURL))
        let data = try JSONEncoder().encode(value)
        var q = query; q[kSecValueData as String] = data; q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(q as CFDictionary, nil)
        if status == errSecDuplicateItem {
            guard SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary) == errSecSuccess else { throw AlpacaError.invalid("Session Keychain update failed.") }
        } else if status != errSecSuccess { throw AlpacaError.invalid("Session Keychain unavailable.") }
    }
}
struct ProviderGrant: Decodable {
    let provider: String; let environment: String; let purpose: String; let account_id: String
    let credential: String; let guild_id: String; let channel_id: String; let scopes: [String]
}
@MainActor final class ProviderConnections: ObservableObject {
    struct Capabilities: Decodable { let version: Int; let service_url: String; let providers: [String]; let auth_project_url: String }
    private struct Begin: Decodable { let flow: String; let expires_at: Double; let launch_url: String }
    private struct Status: Decodable { let stage: String; let flow: String; let provider: String; let purpose: String; let environment: String; let expires_at: Double }
    private struct Signup: Decodable { let session: CustomerSession?; let requiresEmailConfirmation: Bool }
    private struct Pending { let matcher: PendingOAuthReturn; let flow: String; let proof: String; let context: OAuthReturnContext }
    @Published private(set) var hasRetainedIdentity = false
    var canResetIdentity: Bool { hasRetainedIdentity || customer != nil || UserDefaults.standard.string(forKey: "discordOAuthOwner") != nil || AlpacaEnvironment.allCases.contains { (try? AlpacaKeychain.load($0))?.owner != nil } }
    @Published private(set) var customer: CustomerSession?
    @Published private(set) var providers: [String] = []
    @Published private(set) var message = "Check service availability. API-key and webhook setup remain available."
    @Published private(set) var busy = false
    @Published private(set) var grant: ProviderGrant?
    private var pending: Pending?
    private var generation = UUID()
    private var active = true
    private var lifecycle = UUID()
    private var activeWaiters: [CheckedContinuation<Void, Never>] = []
    private let vault: any CustomerSessionStorage
    private var api: ProviderAPI?
    private let network: URLSession
    init(vault: any CustomerSessionStorage = CustomerSessionVault(), network: URLSession = CrierHTTPSession.shared) { self.vault = vault; self.network = network; customer = vault.load(); hasRetainedIdentity = vault.binding() != nil }
    func suspend(_ value: Bool) {
        guard active == value else { return }
        active = !value; lifecycle = UUID()
        if active { let waiters = activeWaiters; activeWaiters = []; waiters.forEach { $0.resume() } }
    }
    private func waitUntilActive() async {
        if !active { await withCheckedContinuation { activeWaiters.append($0) } }
    }
    private func clearPending() { pending?.matcher.invalidate(); pending = nil; grant = nil }
    func check(base: String) async {
        generation = UUID(); let stamp = generation; clearPending(); providers = []; api = nil
        do {
            let candidate = try ProviderAPI(base: base, session: network)
            let value: Capabilities = try await candidate.call("oauth/capabilities")
            guard generation == stamp else { return }
            let auth = candidate.base.scheme! + "://" + candidate.base.host!
            guard value.version == 1, value.service_url == base, value.auth_project_url == auth,
                  value.providers.allSatisfy({ ["alpaca", "discord"].contains($0) }) else { throw AlpacaError.invalid("Untrusted provider capabilities.") }
            api = candidate; providers = value.providers; message = providers.isEmpty ? "Provider sign-in is not configured on this service." : "Provider service available."
        } catch { if generation == stamp { message = "Provider sign-in unavailable. Use existing API-key/webhook setup." } }
    }
    func signIn(email: String, password: String, signup: Bool = false) async {
        guard !busy, let api, !providers.isEmpty else { return }
        generation = UUID(); let stamp = generation; let life = lifecycle; clearPending(); busy = true
        defer { busy = false }
        do {
            var value: CustomerSession?
            if signup {
                let result: Signup = try await api.call("auth/signup", body: ["email": email, "password": password])
                value = result.session
            } else { value = try await api.call("auth/login", body: ["email": email, "password": password]) }
            guard active, stamp == generation, life == lifecycle else { return }
            guard let value else { message = "Check your email to confirm your Crier account, then sign in."; return }
            var checked = try value.validated(); checked.serviceURL = api.base.absoluteString
            guard vault.binding() == nil || vault.binding() == CustomerSessionVault.Binding(owner: checked.user.id, serviceURL: checked.serviceURL!) else { throw AlpacaError.invalid("Sign out before changing customer accounts.") }
            try vault.save(checked); hasRetainedIdentity = true; customer = checked; message = "Signed in to Crier. Browser consent may request the same Crier login."
        } catch { if stamp == generation { message = "Crier sign-in failed. Check your credentials and confirmation status." } }
    }
    /// Explicit one-attempt rotation. Never automatically replay a refresh token after uncertainty.
    func refreshSession(workspace: AlpacaWorkspace) async {
        guard !busy, let api, let customer, customer.serviceURL == api.base.absoluteString else { return }
        generation = UUID(); let stamp = generation; let life = lifecycle; clearPending(); busy = true
        let old = customer; workspace.oauthStopWorkers(); self.customer = nil; try? vault.save(nil)
        defer { busy = false }
        do {
            let value: CustomerSession = try await api.call("auth/refresh", body: ["refresh_token": old.refresh_token])
            var checked = try value.validated(); checked.serviceURL = api.base.absoluteString
            guard active, stamp == generation, life == lifecycle, checked.user.id == old.user.id else { return }
            try vault.save(checked); hasRetainedIdentity = true; self.customer = checked; message = "Crier session refreshed."
        } catch { if stamp == generation { message = "Refresh uncertain or expired. Sign in again; the old refresh token will not be retried." } }
    }
    func logout(workspace: AlpacaWorkspace) {
        generation = UUID(); clearPending(); workspace.oauthLogout()
        customer = nil; try? vault.save(nil); try? vault.saveBinding(nil); hasRetainedIdentity = vault.binding() != nil; message = "Signed out. Workers stopped; order and delivery journals retained."
    }
    private func token() throws -> String {
        guard let customer, customer.serviceURL == api?.base.absoluteString, let expiry = customer.expiresAt, expiry.timeIntervalSinceNow > 30 else { throw AlpacaError.invalid("Sign in or explicitly refresh the Crier session first.") }
        return customer.access_token
    }
    func begin(provider: String, environment: AlpacaEnvironment, purpose: String) async -> URL? {
        guard !busy, active, let api, providers.contains(provider), let owner = customer?.user.id,
              let context = OAuthReturnContext(owner: owner, provider: provider, environment: environment.rawValue, purpose: purpose) else { return nil }
        clearPending(); let stamp = generation; let life = lifecycle; busy = true; defer { busy = false }
        do {
            var bytes = [UInt8](repeating: 0, count: 32)
            guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw AlpacaError.invalid("Device proof unavailable.") }
            let proof = Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
            let challenge = SHA256.hash(data: Data(proof.utf8)).map { String(format: "%02x", $0) }.joined()
            let value: Begin = try await api.call("oauth/begin", body: ["provider": provider, "environment": environment.rawValue, "purpose": purpose, "challenge": challenge], token: token())
            guard active, stamp == generation, life == lifecycle, customer?.user.id == owner else { return nil }
            guard value.expires_at > Date().timeIntervalSince1970, value.expires_at <= Date().timeIntervalSince1970 + 301,
                  let matcher = PendingOAuthReturn(flow: value.flow, context: context, expiresAt: value.expires_at),
                  let url = URL(string: value.launch_url), url.scheme == api.base.scheme, url.host == api.base.host,
                  url.port == nil, url.user == nil, url.password == nil, url.fragment == nil,
                  url.path == api.base.path + "/oauth/browser", let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
                  parts.queryItems?.count == 1, parts.queryItems?.first?.name == "ticket",
                  OAuthReturn.validFlow(parts.queryItems?.first?.value ?? "") else { throw AlpacaError.invalid("Invalid consent launch.") }
            pending = Pending(matcher: matcher, flow: value.flow, proof: proof, context: context)
            message = "Complete official provider consent, then return to review installation."; return url
        } catch { if stamp == generation { message = error.localizedDescription }; return nil }
    }
    func receive(_ url: URL, environment: AlpacaEnvironment, purpose: String) async {
        await waitUntilActive()
        guard !busy, let pending, let api, let owner = customer?.user.id,
              let expected = OAuthReturnContext(owner: owner, provider: pending.context.provider, environment: environment.rawValue, purpose: pending.context.provider == "discord" ? "alerts" : purpose),
              OAuthReturn.matchPending(pending.matcher, uri: url.absoluteString, expectedFlow: pending.flow, expectedContext: expected, now: Date().timeIntervalSince1970) != nil else { return }
        self.pending = nil; busy = true; let stamp = generation; defer { busy = false }
        do {
            let bearer = try token()
            let status: Status = try await api.call("oauth/status", body: ["flow": pending.flow], token: bearer)
            await waitUntilActive()
            guard stamp == generation, customer?.user.id == owner, !Task.isCancelled else { return }
            guard status.stage == "ready", status.flow == pending.flow, status.provider == expected.provider,
                  status.purpose == expected.purpose, status.environment == expected.environment,
                  status.expires_at > Date().timeIntervalSince1970 else { throw AlpacaError.invalid("Consent is not ready. Cancel and start a new flow if uncertain.") }
            let value: ProviderGrant = try await api.call("oauth/redeem", body: ["flow": pending.flow, "proof": pending.proof], token: bearer)
            await waitUntilActive()
            guard stamp == generation, customer?.user.id == owner, !Task.isCancelled else { return }
            guard value.provider == expected.provider, value.environment == expected.environment, value.purpose == expected.purpose,
                  !value.credential.isEmpty, value.credential.count <= 8192,
                  value.scopes == (expected.provider == "discord" ? ["webhook.incoming"] : (expected.purpose == "trade" ? ["trading"] : [])) else { throw AlpacaError.invalid("Grant does not match the requested connection.") }
            grant = value; message = "Consent verified. Install while disconnected, then reconnect explicitly."
        } catch { if stamp == generation { message = "Return could not be redeemed. Start a new consent flow; redemption is never retried." } }
    }
    func cancel() async {
        guard let pending, let api else { clearPending(); return }
        clearPending()
        struct Cancelled: Decodable { }
        let _: Cancelled? = try? await api.call("oauth/cancel", body: ["flow": pending.flow, "proof": pending.proof], token: token())
        message = "Local flow cancelled. Provider revocation remains separate."
    }
    func install(workspace: AlpacaWorkspace) async {
        guard !busy, active, let value = grant, let owner = customer?.user.id, let serviceURL = customer?.serviceURL else { return }
        busy = true; grant = nil; let stamp = generation; let life = lifecycle; defer { busy = false }
        do {
            try await workspace.installOAuthGrant(value, owner: owner, serviceURL: serviceURL, stillCurrent: { self.active && self.lifecycle == life && self.generation == stamp && self.customer?.user.id == owner && self.customer?.serviceURL == serviceURL })
            if stamp == generation { message = "Credential saved. Reconnect and review delivery permission explicitly." }
        } catch { if stamp == generation { message = error.localizedDescription } }
    }
}
struct ProviderConnectionsView: View {
    @EnvironmentObject var connections: ProviderConnections
    @EnvironmentObject var workspace: AlpacaWorkspace
    @Environment(\.openURL) private var openURL
    @State private var base = ProviderAPI.defaultBase
    @State private var email = ""
    @State private var password = ""
    var body: some View {
        Form {
            Section("Provider service") {
                Text("Provider sign-in requires a configured, deployed Crier OAuth service. Existing API-key setup is available from Home.")
                DisclosureGroup("Advanced trusted service") { TextField("Exact Supabase OAuth function URL", text: $base).textInputAutocapitalization(.never).autocorrectionDisabled() }
                Button("Check availability") { Task { await connections.check(base: base) } }.disabled(connections.busy)
            }
            if connections.canResetIdentity {
                Section("Saved Crier identity") {
                    Text("Sign out to stop workers and remove OAuth credentials before changing Crier customer or service.")
                    Button("Sign out and remove OAuth credentials", role: .destructive) { connections.logout(workspace: workspace) }
                }
            }
            if !connections.providers.isEmpty {
                Section("Crier customer account") {
                    Text("Use your Crier account password here. Your brokerage password is entered only on the provider’s official consent page. Browser consent may ask you to sign in to the same Crier account separately.")
                    if connections.customer == nil {
                        TextField("Crier email", text: $email).keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                        SecureField("Crier password", text: $password)
                        Button("Sign in to Crier") { authenticate(signup: false) }
                        Button("Create Crier account") { authenticate(signup: true) }
                    } else {
                        Text("Signed in to Crier")
                        Button("Refresh Crier session") { Task { await connections.refreshSession(workspace: workspace) } }
                    }
                }.disabled(connections.busy)
                if connections.customer != nil {
                    Section("Official provider consent") {
                        Text("Select purpose and environment on Home first. Consent saves no trading or delivery permission.")
                        ForEach(connections.providers, id: \.self) { provider in
                            Button("Authorize \(provider.capitalized)") {
                                Task {
                                    let purpose = provider == "discord" || workspace.purpose == .alerts ? "alerts" : "trade"
                                    if let url = await connections.begin(provider: provider, environment: workspace.environment, purpose: purpose) { openURL(url) }
                                }
                            }.disabled(connections.busy || workspace.account != nil || workspace.purpose == nil)
                        }
                        Button("Cancel pending consent") { Task { await connections.cancel() } }.disabled(connections.busy)
                        if let grant = connections.grant {
                            Text("Ready: \(grant.provider) · \(grant.environment) · \(grant.purpose)")
                            Button("Verify and save credential") { Task { await connections.install(workspace: workspace) } }.disabled(connections.busy || workspace.account != nil)
                        }
                    }
                }
            }
            Text(connections.message).font(.footnote)
        }.navigationTitle("Provider connections")
    }
    private func authenticate(signup: Bool) {
        let secret = password; password = ""
        Task { await connections.signIn(email: email, password: secret, signup: signup) }
    }
}
