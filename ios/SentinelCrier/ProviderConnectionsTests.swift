import XCTest
@testable import SentinelCrier

/// Per-session URLProtocol routes; no live customer, provider, message or order calls.
private final class ProviderMockProtocol: URLProtocol {
    static let lock = NSLock()
    static var routes: [String: (URLRequest) throws -> Data] = [:]
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            Self.lock.lock(); let route = Self.routes[request.url!.host!]; Self.lock.unlock()
            let data = try XCTUnwrap(route)(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
final class ProviderConnectionsTests: XCTestCase {
    let base = "https://abcdefghijklmnopqrst.supabase.co/functions/v1/crier-oauth"
    let owner = "11111111-1111-4111-8111-111111111111"
    private func encode(_ value: Any) throws -> Data { try JSONSerialization.data(withJSONObject: value) }
    private func token(owner candidate: String? = nil) throws -> String {
        let body = try encode(["sub": candidate ?? owner, "exp": Date().addingTimeInterval(1800).timeIntervalSince1970])
        return "e30." + body.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") + ".test"
    }
    private func network(_ route: @escaping (URLRequest) throws -> Data) -> URLSession {
        ProviderMockProtocol.lock.lock()
        ProviderMockProtocol.routes["abcdefghijklmnopqrst.supabase.co"] = route
        ProviderMockProtocol.routes["paper-api.alpaca.markets"] = route
        ProviderMockProtocol.lock.unlock()
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ProviderMockProtocol.self]
        return URLSession(configuration: config)
    }
    func testExactServiceBoundaryAndLegacyCredentials() throws {
        for rejected in [base + "/", base + "?x=1", base.replacingOccurrences(of: "https", with: "http"), base.replacingOccurrences(of: "abcdefghijklmnopqrst", with: "ABCdefghijklmnopqrst")] {
            XCTAssertThrowsError(try ProviderAPI(base: rejected))
        }
        let old = try JSONDecoder().decode(AlpacaCredentials.self, from: encode(["key": "key", "secret": "secret"]))
        var request = URLRequest(url: URL(string: "https://paper-api.alpaca.markets")!)
        try old.authorize(&request); XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
        var legacyOAuthRequest = URLRequest(url: request.url!)
        XCTAssertThrowsError(try AlpacaCredentials(bearer: "synthetic", owner: owner).authorize(&legacyOAuthRequest))
        let oauth = AlpacaCredentials(bearer: "synthetic", owner: owner, serviceURL: base)
        request = URLRequest(url: request.url!); try oauth.authorize(&request)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer synthetic")
        XCTAssertNil(request.value(forHTTPHeaderField: "APCA-API-KEY-ID")); XCTAssertNil(request.value(forHTTPHeaderField: "APCA-API-SECRET-KEY"))
    }
    @MainActor func testMockedSignInConsentReturnAndExplicitSafeInstall() async throws {
        let vault = CustomerSessionVault(service: "test.customer." + UUID().uuidString)
        defer { try? vault.save(nil); try? vault.saveBinding(nil) }
        let flow = String(repeating: "A", count: 43)
        let jwt = try token(); var redeemCount = 0; var accountGets = 0; var saved: AlpacaCredentials?
        let statusEntered = expectation(description: "status entered")
        let releaseStatus = DispatchSemaphore(value: 0)
        let session = network { [self] request in
            let path = request.url!.path
            switch path {
            case "/functions/v1/crier-oauth/oauth/capabilities":
                return try encode(["version": 1, "service_url": base, "providers": ["alpaca"], "auth_project_url": "https://abcdefghijklmnopqrst.supabase.co"])
            case "/functions/v1/crier-oauth/auth/login":
                XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
                return try encode(["access_token": jwt, "refresh_token": "refresh", "expires_in": 1800, "token_type": "bearer", "user": ["id": owner]])
            case "/functions/v1/crier-oauth/oauth/begin":
                XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + jwt)
                return try encode(["flow": flow, "expires_at": Date().addingTimeInterval(240).timeIntervalSince1970, "launch_url": base + "/oauth/browser?ticket=" + flow])
            case "/functions/v1/crier-oauth/oauth/status":
                statusEntered.fulfill(); _ = releaseStatus.wait(timeout: .now() + 10)
                return try encode(["stage": "ready", "flow": flow, "provider": "alpaca", "purpose": "alerts", "environment": "paper", "expires_at": Date().addingTimeInterval(200).timeIntervalSince1970])
            case "/functions/v1/crier-oauth/oauth/redeem":
                redeemCount += 1
                return try encode(["provider": "alpaca", "environment": "paper", "purpose": "alerts", "account_id": "account-a", "credential": "synthetic-provider-token", "guild_id": "", "channel_id": "", "scopes": []])
            case "/v2/account":
                accountGets += 1
                XCTAssertEqual(request.httpMethod, "GET")
                XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer synthetic-provider-token")
                XCTAssertNil(request.value(forHTTPHeaderField: "APCA-API-KEY-ID"))
                return try encode(["id": "account-a", "status": "ACTIVE", "buying_power": "1", "equity": "1", "trading_blocked": false, "account_blocked": false])
            default: XCTFail("Unexpected network operation: " + path); throw URLError(.unsupportedURL)
            }
        }
        defer { session.invalidateAndCancel() }
        let connections = ProviderConnections(vault: vault, network: session)
        await connections.check(base: base); XCTAssertEqual(connections.providers, ["alpaca"])
        await connections.signIn(email: "synthetic@example.test", password: "crier-only")
        XCTAssertEqual(vault.load()?.user.id, owner)
        let url = await connections.begin(provider: "alpaca", environment: .paper, purpose: "alerts")
        XCTAssertNotNil(url)
        let callback = URL(string: "sentinelcrier://oauth/complete?flow=" + flow)!
        connections.suspend(true)
        let receipt = Task { await connections.receive(callback, environment: .paper, purpose: "alerts") }
        await Task.yield()
        XCTAssertEqual(redeemCount, 0)
        connections.suspend(false)
        await fulfillment(of: [statusEntered], timeout: 5)
        connections.suspend(true); releaseStatus.signal()
        await Task.yield(); connections.suspend(false)
        await receipt.value
        await connections.receive(callback, environment: .paper, purpose: "alerts")
        XCTAssertEqual(redeemCount, 1); XCTAssertNil(saved); XCTAssertEqual(accountGets, 0)
        let journalURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: journalURL) }
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let intentURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: intentURL) }
        let workspace = AlpacaWorkspace(journal: try AlpacaJournal(file: journalURL), intentController: try IntentController(file: intentURL, session: session), defaults: defaults, loadIntentPairing: { nil },
            makeClient: { AlpacaREST(environment: $0, credentials: $1, session: session) },
            loadCredentials: { _ in throw AlpacaError.invalid("empty") }, saveCredentials: { value, _ in saved = value })
        workspace.selectPurpose(.alerts)
        await connections.install(workspace: workspace)
        XCTAssertEqual(saved?.owner, owner); XCTAssertEqual(saved?.serviceURL, base); XCTAssertEqual(accountGets, 1)
        XCTAssertNil(workspace.account); XCTAssertFalse(workspace.readiness.verified); XCTAssertFalse(workspace.readiness.deliveryEnabled)
        connections.logout(workspace: workspace); XCTAssertNil(vault.load()); XCTAssertNil(connections.customer)
    }
    @MainActor func testColdReturnAndMismatchedBrokerNeverInstall() async throws {
        var requests = 0; var saves = 0
        let session = network { [self] request in
            requests += 1
            XCTAssertEqual(request.url?.path, "/v2/account")
            return try encode(["id": "different-account", "status": "ACTIVE", "buying_power": "1", "equity": "1", "trading_blocked": false, "account_blocked": false])
        }
        defer { session.invalidateAndCancel() }
        let vault = CustomerSessionVault(service: "test.customer." + UUID().uuidString)
        defer { try? vault.save(nil); try? vault.saveBinding(nil) }
        let connections = ProviderConnections(vault: vault, network: session)
        await connections.receive(URL(string: "sentinelcrier://oauth/complete?flow=" + String(repeating: "A", count: 43))!, environment: .paper, purpose: "alerts")
        XCTAssertEqual(requests, 0)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let workspace = AlpacaWorkspace(journal: try AlpacaJournal(file: folder.appendingPathComponent("broker.json")),
            intentController: try IntentController(file: folder.appendingPathComponent("intent.json"), session: session),
            defaults: UserDefaults(suiteName: UUID().uuidString)!, loadIntentPairing: { nil },
            makeClient: { AlpacaREST(environment: $0, credentials: $1, session: session) },
            saveCredentials: { _, _ in saves += 1 })
        workspace.selectPurpose(.alerts)
        let grant = ProviderGrant(provider: "alpaca", environment: "paper", purpose: "alerts", account_id: "expected-account", credential: "synthetic", guild_id: "", channel_id: "", scopes: [])
        do { try await workspace.installOAuthGrant(grant, owner: owner, serviceURL: base, stillCurrent: { true }); XCTFail("Mismatched identity accepted") } catch {}
        XCTAssertEqual(saves, 0); XCTAssertEqual(requests, 1); XCTAssertNil(workspace.account)
        do { try await workspace.installOAuthGrant(grant, owner: owner, serviceURL: base, stillCurrent: { false }); XCTFail("Stale session accepted") } catch {}
        XCTAssertEqual(requests, 1); XCTAssertEqual(saves, 0)
    }
    @MainActor func testLogoutDuringConfirmAccountCheckPreventsSubmissionAndCancellation() async throws {
        for cancel in [false, true] {
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: folder) }
            let entered = expectation(description: "account validation paused")
            let release = DispatchSemaphore(value: 0)
            var hold = false; var mutations = 0
            let session = network { [self] request in
                if request.httpMethod == "POST" || request.httpMethod == "DELETE" { mutations += 1; return try encode([:]) }
                if request.url?.path == "/v2/account" {
                    if hold { entered.fulfill(); _ = release.wait(timeout: .now() + 10) }
                    return try encode(["id": "account-a", "status": "ACTIVE", "buying_power": "1", "equity": "1", "trading_blocked": false, "account_blocked": false])
                }
                return try encode([])
            }
            defer { session.invalidateAndCancel() }
            let journal = try AlpacaJournal(file: folder.appendingPathComponent("broker.json"))
            let workspace = AlpacaWorkspace(journal: journal, intentController: try IntentController(file: folder.appendingPathComponent("intent.json"), session: session),
                defaults: UserDefaults(suiteName: UUID().uuidString)!, loadIntentPairing: { nil },
                makeClient: { AlpacaREST(environment: $0, credentials: $1, session: session) },
                loadCredentials: { _ in AlpacaCredentials(key: "synthetic", secret: "synthetic") })
            workspace.selectPurpose(.trade); await workspace.connect(key: "", secret: "")
            XCTAssertNotNil(workspace.account)
            let ticket = AlpacaTicket(id: "test-paused-confirm", environment: .paper, accountID: "account-a", symbol: "AAPL", quantity: 1, limitPrice: 1, side: "buy", positionIntent: nil, multiplier: 1, reviewedAt: Date())
            workspace.review = ticket
            let order = try JSONDecoder().decode(AlpacaOrder.self, from: encode(["id": "broker-order", "client_order_id": ticket.id, "symbol": "AAPL", "status": "new", "qty": "1", "filled_qty": "0", "side": "buy"]))
            if cancel { try await journal.begin(ticket); try await journal.record(order, ticket: ticket) }
            let snapshot = await journal.snapshot()
            let submission = snapshot.submissions.first
            hold = true
            let operation = Task { if cancel, let submission { await workspace.cancel(submission) } else { await workspace.confirm(ticket) } }
            await fulfillment(of: [entered], timeout: 5)
            workspace.oauthLogout(); release.signal(); await operation.value
            XCTAssertEqual(mutations, 0); XCTAssertNil(workspace.account)
        }
    }
    @MainActor func testRefreshFailureStopsConnectedWorkspaceAndKeepsOwnerFence() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let vault = CustomerSessionVault(service: "test.customer." + UUID().uuidString)
        defer { try? vault.save(nil); try? vault.saveBinding(nil) }
        let other = "22222222-2222-4222-8222-222222222222"
        let jwt = try token(); let otherJWT = try token(owner: other)
        var logins = 0
        let refreshEntered = expectation(description: "refresh paused")
        let refreshGate = DispatchSemaphore(value: 0)
        let session = network { [self] request in
            switch request.url!.path {
            case "/functions/v1/crier-oauth/oauth/capabilities": return try encode(["version": 1, "service_url": base, "providers": ["alpaca"], "auth_project_url": "https://abcdefghijklmnopqrst.supabase.co"])
            case "/functions/v1/crier-oauth/auth/login":
                logins += 1
                return try encode(["access_token": logins == 1 ? jwt : otherJWT, "refresh_token": "refresh", "expires_in": 1800, "token_type": "bearer", "user": ["id": logins == 1 ? owner : other]])
            case "/functions/v1/crier-oauth/auth/refresh":
                refreshEntered.fulfill(); _ = refreshGate.wait(timeout: .now() + 10); throw URLError(.networkConnectionLost)
            case "/v2/account": return try encode(["id": "account-a", "status": "ACTIVE", "buying_power": "1", "equity": "1", "trading_blocked": false, "account_blocked": false])
            default: return try encode([])
            }
        }
        defer { session.invalidateAndCancel() }
        let workspace = AlpacaWorkspace(journal: try AlpacaJournal(file: folder.appendingPathComponent("broker.json")),
            intentController: try IntentController(file: folder.appendingPathComponent("intent.json"), session: session),
            defaults: UserDefaults(suiteName: UUID().uuidString)!, loadIntentPairing: { nil },
            makeClient: { AlpacaREST(environment: $0, credentials: $1, session: session) },
            loadCredentials: { _ in AlpacaCredentials(key: "synthetic", secret: "synthetic") })
        let connections = ProviderConnections(vault: vault, network: session)
        await connections.check(base: base); await connections.signIn(email: "one@example.test", password: "crier-only")
        workspace.selectPurpose(.trade); await workspace.connect(key: "", secret: ""); XCTAssertNotNil(workspace.account)
        let refreshing = Task { await connections.refreshSession(workspace: workspace) }
        await fulfillment(of: [refreshEntered], timeout: 5)
        XCTAssertNil(workspace.account); XCTAssertFalse(workspace.readiness.verified)
        XCTAssertEqual(vault.binding()?.owner, owner); XCTAssertEqual(vault.binding()?.serviceURL, base)
        refreshGate.signal(); await refreshing.value
        XCTAssertNil(connections.customer); XCTAssertNil(vault.load()); XCTAssertTrue(connections.canResetIdentity)
        await connections.check(base: "https://unavailable.invalid/functions/v1/crier-oauth")
        XCTAssertTrue(connections.providers.isEmpty); XCTAssertTrue(connections.canResetIdentity)
        await connections.check(base: base)
        await connections.signIn(email: "two@example.test", password: "crier-only")
        XCTAssertNil(connections.customer); XCTAssertEqual(vault.binding()?.owner, owner)
        connections.logout(workspace: workspace); XCTAssertNil(vault.binding()); XCTAssertFalse(connections.hasRetainedIdentity)
    }
    @MainActor func testSameUUIDInDifferentProjectCannotUseSavedOAuthCredential() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        var requests = 0
        let session = network { _ in requests += 1; throw URLError(.unsupportedURL) }
        defer { session.invalidateAndCancel() }
        var customer = try JSONDecoder().decode(CustomerSession.self, from: encode(["access_token": token(), "refresh_token": "refresh", "expires_in": 1800, "token_type": "bearer", "user": ["id": owner]]))
        customer.serviceURL = "https://zyxwvutsrqponmlkjihg.supabase.co/functions/v1/crier-oauth"
        XCTAssertFalse(OAuthOwnership.matches(owner: owner, serviceURL: base, customer: customer))
        XCTAssertFalse(OAuthOwnership.matches(owner: owner, serviceURL: nil, customer: customer))
        XCTAssertTrue(OAuthOwnership.matches(owner: owner, serviceURL: customer.serviceURL, customer: customer))
        for service in [base, nil] {
            let workspace = AlpacaWorkspace(journal: try AlpacaJournal(file: folder.appendingPathComponent(UUID().uuidString)),
                intentController: try IntentController(file: folder.appendingPathComponent(UUID().uuidString), session: session),
                defaults: UserDefaults(suiteName: UUID().uuidString)!, loadIntentPairing: { nil },
                makeClient: { AlpacaREST(environment: $0, credentials: $1, session: session) },
                loadCredentials: { _ in AlpacaCredentials(bearer: "synthetic", owner: self.owner, serviceURL: service) }, loadCustomer: { customer })
            workspace.selectPurpose(.alerts); await workspace.connect(key: "", secret: "")
            XCTAssertNil(workspace.account)
        }
        XCTAssertEqual(requests, 0)
    }
    @MainActor func testStaleIntentClientCannotMutateAfterLogoutAndLedgerRemains() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        var mutations = 0
        let session = network { [self] request in
            if request.httpMethod != "GET" { mutations += 1; throw URLError(.unsupportedURL) }
            if request.url?.path == "/v2/account" { return try encode(["id": "account-a", "status": "ACTIVE", "buying_power": "1", "equity": "1", "trading_blocked": false, "account_blocked": false]) }
            return try encode([])
        }
        defer { session.invalidateAndCancel() }
        var retainedClient: AlpacaREST?
        let ledger = folder.appendingPathComponent("intent.json")
        let intent = try IntentController(file: ledger, session: session)
        let workspace = AlpacaWorkspace(journal: try AlpacaJournal(file: folder.appendingPathComponent("broker.json")), intentController: intent,
            defaults: UserDefaults(suiteName: UUID().uuidString)!, loadIntentPairing: { nil },
            makeClient: { let client = AlpacaREST(environment: $0, credentials: $1, session: session); retainedClient = client; return client },
            loadCredentials: { _ in AlpacaCredentials(key: "synthetic", secret: "synthetic") })
        workspace.selectPurpose(.trade); await workspace.connect(key: "", secret: "")
        let client = try XCTUnwrap(retainedClient)
        let pair = IntentPairing(url: URL(string: "https://synthetic.example.test")!, token: "synthetic", environment: .paper, role: "host")
        try intent.connect(api: client, account: "account-a", pairing: pair, startWorkers: false)
        let before = try Data(contentsOf: ledger)
        let released = expectation(description: "stale task released")
        let gate = DispatchSemaphore(value: 0)
        let stale = Task.detached {
            released.fulfill(); _ = gate.wait(timeout: .now() + 10)
            do { _ = try await client.submitIntent(symbol: "AAPL", quantity: 1, price: "1", sell: false, option: false, clientID: "stale-intent"); XCTFail("Stale intent submitted") } catch {}
            do { try await client.cancel(orderID: "stale-order"); XCTFail("Stale intent cancellation sent") } catch {}
        }
        await fulfillment(of: [released], timeout: 5)
        workspace.oauthLogout(); gate.signal(); await stale.value
        XCTAssertFalse(client.permitsMutations); XCTAssertEqual(mutations, 0)
        XCTAssertEqual(try Data(contentsOf: ledger), before)
    }
    func testFreshForegroundClientDoesNotReactivateStaleClient() async throws {
        var mutations = 0
        let session = network { request in
            XCTAssertEqual(request.httpMethod, "DELETE"); mutations += 1; return Data()
        }
        defer { session.invalidateAndCancel() }
        let stopped = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "synthetic", secret: "synthetic"), session: session)
        stopped.invalidate()
        let resumed = try stopped.freshClient(customer: nil)
        do { try await stopped.cancel(orderID: "stale"); XCTFail("Stopped client dispatched") } catch {}
        try await resumed.cancel(orderID: "resumed")
        XCTAssertFalse(stopped.permitsMutations); XCTAssertTrue(resumed.permitsMutations)
        XCTAssertEqual(mutations, 1)
    }
    func testSessionExpiryAndOwnerValidation() throws {
        let raw = try encode(["access_token": token(), "refresh_token": "refresh", "expires_in": 1800, "token_type": "bearer", "user": ["id": owner]])
        let value = try JSONDecoder().decode(CustomerSession.self, from: raw)
        XCTAssertNoThrow(try value.validated())
        XCTAssertThrowsError(try value.validated(now: Date().addingTimeInterval(3600)))
    }
}
