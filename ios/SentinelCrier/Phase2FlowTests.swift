import XCTest
@testable import SentinelCrier

final class Phase2FlowTests: XCTestCase {
    func testSharedProtocolExamples() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "phase2-protocol", withExtension: "json"))
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let base = try XCTUnwrap(fixture["base"] as? [String: Any])
        for item in try XCTUnwrap(fixture["cases"] as? [[String: Any]]) {
            var value = base
            for (key, change) in try XCTUnwrap(item["changes"] as? [String: Any]) { value[key] = change }
            let data = try JSONSerialization.data(withJSONObject: value)
            let valid = item["valid"] as? Bool == true
            do {
                let event = try JSONDecoder().decode(IntentEvent.self, from: data)
                try event.validate()
                XCTAssertTrue(valid, item["name"] as? String ?? "")
            } catch { XCTAssertFalse(valid, item["name"] as? String ?? "") }
        }
    }
    func testDiscordProvenanceCannotBeRemovedByTemplate() {
        var settings = DiscordAlertSettings()
        settings.template = "{symbol}"
        settings.showTime = false; settings.showReference = false
        XCTAssertTrue(settings.render(DiscordAlertSettings.preview).contains("BROKER-CONFIRMED FILL"))
    }
}

final class Phase2SettingsTests: XCTestCase {
    func testLegacyFollowerSettingsDefaultToPausedAndRetainKnownValues() throws {
        let preferences = try JSONDecoder().decode(IntentPreferences.self, from: Data(#"{"mode":"bounded_limit","maxQuantity":5}"#.utf8))
        XCTAssertTrue(preferences.paused)
        XCTAssertEqual(preferences.maxQuantity, 5)
        let price = try XCTUnwrap(preferences.price("0.20", sell: false))
        XCTAssertEqual(Decimal(string: price), Decimal(string: "0.20"))
        XCTAssertThrowsError(try JSONDecoder().decode(IntentPreferences.self, from: Data(#"{"mode":"unsafe"}"#.utf8)))
    }
    func testAlertSettingsPersistWithoutWebhookOrAccountAndProvenanceIsPinned() throws {
        let name = "phase2-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        defaults.set("card", forKey: "discordFillStyle")
        var settings = DiscordAlertSettings.load(defaults)
        settings.template = "{quantity}x {symbol} ${price}"
        settings.showTime = false; settings.showReference = false
        try settings.save(defaults)
        let restored = DiscordAlertSettings.load(defaults)
        XCTAssertEqual(restored.template, settings.template)
        XCTAssertEqual(defaults.string(forKey: "discordFillStyle"), "card")
        let payload = restored.payload(DiscordAlertSettings.preview, style: "card")
        let raw = String(decoding: try JSONSerialization.data(withJSONObject: payload), as: UTF8.self)
        XCTAssertTrue(raw.contains("0.20")); XCTAssertTrue(raw.contains("BROKER-CONFIRMED FILL")); XCTAssertTrue(raw.contains("PAPER"))
        XCTAssertFalse(raw.contains("Broker time:")); XCTAssertFalse(raw.contains("Ref "))
        let mentions = try XCTUnwrap(payload["allowed_mentions"] as? [String: [String]])
        XCTAssertEqual(mentions["parse"], [])
        settings.template = String(repeating: "x", count: 1201)
        XCTAssertThrowsError(try settings.save(defaults))
    }
    func testPoisonRecordsAndConflictsDoNotLoseFollowingEvents() throws {
        var state = IntentState()
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "SPY261218C00750000", asset: "option", quantity: 2, price: "0.20")
        var conflict = event; conflict.limit_price = "0.30"
        let later = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        func object(_ event: IntentEvent) throws -> Any { try JSONSerialization.jsonObject(with: JSONEncoder().encode(event)) }
        let page = try JSONSerialization.data(withJSONObject: ["cursor": 4, "events": [
            ["cursor": 1, "event": try object(event)], ["cursor": 2, "event": ["version": 99]],
            ["cursor": 3, "event": try object(conflict)], ["cursor": 4, "event": try object(later)]
        ]])
        let accepted = try state.ingestPage(page, environment: .paper)
        XCTAssertEqual(accepted.map(\.event_id), [event.event_id, later.event_id])
        XCTAssertEqual(state.cursor, 4); XCTAssertEqual(state.quarantine?.count, 2)
        XCTAssertEqual(state.received[event.event_id]?.limit_price, "0.20")
        let restored = try JSONDecoder().decode(IntentState.self, from: JSONEncoder().encode(state))
        XCTAssertEqual(restored.cursor, 4); XCTAssertEqual(restored.quarantine?.count, 2)
        XCTAssertEqual(restored.received.count, 2)
    }
    func testUnknownAndOwnedOrdersRemainUnresolvedAcrossRestart() throws {
        var state = IntentState()
        var trade = IntentTrade()
        trade.mutations = [IntentMutation(clientID: "unknown", eventID: "pending", sell: false, quantity: 2)]
        state.trades["unknown-trade"] = trade
        let restored = try JSONDecoder().decode(IntentState.self, from: JSONEncoder().encode(state))
        XCTAssertEqual(restored.unresolved, ["unknown-trade"])
    }
}

@MainActor
final class Phase2RecoveryTests: XCTestCase {
    private func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AlpacaMockURLProtocol.self]
        return URLSession(configuration: configuration)
    }
    override func tearDown() { AlpacaMockURLProtocol.handler = nil; super.tearDown() }
    private func pair(_ role: String = "follower") -> IntentPairing {
        IntentPairing(url: URL(string: "https://relay.test")!, token: String(repeating: "x", count: 32), environment: .paper, role: role)
    }
    private func makeController(_ state: IntentState = IntentState()) throws -> (IntentController, URL) {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        try JSONEncoder().encode(state).write(to: file)
        return (try IntentController(file: file, session: session()), file)
    }
    private func api() -> AlpacaREST {
        AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "mock-key", secret: "mock-secret"), session: session())
    }
    func testRelayAuthenticationFailureDisconnectsWithoutDiscardingJournal() async throws {
        var saved = IntentState(); saved.cursor = 7
        let (controller, file) = try makeController(saved)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        try controller.connect(api: api(), account: "original-account", pairing: pair("host"), startWorkers: false)
        AlpacaMockURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.host, "relay.test")
            return (401, Data())
        }
        do { try await controller.receiveOnce(); XCTFail("Expected authentication failure") } catch {}
        XCTAssertFalse(controller.hosting)
        XCTAssertEqual(controller.state.cursor, 7)
        XCTAssertEqual(controller.state.accountID, "original-account")
        XCTAssertTrue(controller.message.contains("authentication"))
        let restored = try IntentController(file: file)
        XCTAssertEqual(restored.state.cursor, 7)
    }
    func testAccountOrChannelChangeIsRejectedAndUnknownOrderCannotBeArchived() throws {
        var saved = IntentState(); saved.accountID = "original-account"; saved.pairingID = pair().fingerprint
        var trade = IntentTrade(); trade.mutations = [IntentMutation(clientID: "unknown-client", eventID: "event", sell: false, quantity: 1)]
        saved.trades["pending"] = trade
        let (controller, file) = try makeController(saved)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        XCTAssertThrowsError(try controller.connect(api: api(), account: "other-account", pairing: pair(), startWorkers: false))
        var changed = pair(); changed.token = String(repeating: "y", count: 32)
        XCTAssertThrowsError(try controller.connect(api: api(), account: "original-account", pairing: changed, startWorkers: false))
        try controller.connect(api: api(), account: "original-account", pairing: pair(), startWorkers: false)
        controller.disconnect()
        XCTAssertThrowsError(try controller.archiveResolvedChannel())
        let restored = try IntentController(file: file)
        XCTAssertEqual(restored.state.trades["pending"]?.mutations.first?.clientID, "unknown-client")
        XCTAssertEqual(restored.state.accountID, "original-account")
    }
    func testDefinitiveBrokerRejectionsAreDurableAndNeverReposted() async throws {
        for status in [400, 401, 403, 429] {
            let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "SPY261218C00750000", asset: "option", quantity: 2, price: "0.20")
            var saved = IntentState(); saved.preferences.paused = false
            var trade = IntentTrade(); try trade.accept(event); trade.policySnapshot = .legacy(event); saved.trades[event.trade_id] = trade
            let (controller, file) = try makeController(saved)
            defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
            var posts = 0
            AlpacaMockURLProtocol.handler = { request in
                if request.url?.path == "/v2/account" {
                    return (200, Data(#"{"id":"account","status":"ACTIVE","buying_power":"1000","equity":"1000","trading_blocked":false,"account_blocked":false}"#.utf8))
                }
                XCTAssertEqual(request.httpMethod, "POST"); posts += 1
                return (status, Data())
            }
            try controller.connect(api: api(), account: "account", pairing: pair(), startWorkers: false)
            await controller.process(); await controller.process()
            XCTAssertEqual(posts, 1, "HTTP \(status)")
            XCTAssertEqual(controller.state.trades[event.trade_id]?.mutations.first?.order?.status, "rejected")
            let restored = try IntentController(file: file)
            XCTAssertEqual(restored.state.trades[event.trade_id]?.mutations.first?.order?.status, "rejected")
        }
    }
    func testDuplicate422SubmissionAfterRestartOnlyLooksUpNeverReposts() async throws {
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 2, price: "10")
        var saved = IntentState(); saved.preferences.paused = false
        var trade = IntentTrade(); try trade.accept(event); trade.policySnapshot = .legacy(event); saved.trades[event.trade_id] = trade
        let (controller, file) = try makeController(saved)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        var posts = 0; var lookups = 0
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" {
                return (200, Data(#"{"id":"account","status":"ACTIVE","buying_power":"1000","equity":"1000","trading_blocked":false,"account_blocked":false}"#.utf8))
            }
            if request.httpMethod == "POST" { posts += 1; return (422, Data()) }
            lookups += 1; return (404, Data())
        }
        try controller.connect(api: api(), account: "account", pairing: pair(), startWorkers: false)
        await controller.process(); controller.disconnect()
        let restored = try IntentController(file: file, session: session())
        defer { restored.disconnect() }
        try restored.connect(api: api(), account: "account", pairing: pair(), startWorkers: false)
        await restored.process(); await restored.process()
        XCTAssertEqual(posts, 1); XCTAssertEqual(lookups, 2)
        XCTAssertNil(restored.state.trades[event.trade_id]?.mutations.first?.order)
        XCTAssertEqual(restored.state.unresolved, [event.trade_id])
    }
    func testOptionExitIsBoundedByTrackedPartialFillDespiteUnrelatedHoldings() async throws {
        let symbol = "SPY261218C00750000"
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 2, action: "exit", environment: .paper, symbol: symbol, asset: "option", quantity: 2, price: "0.20")
        var saved = IntentState(); saved.preferences.paused = false
        var trade = IntentTrade(); try trade.accept(event); trade.policySnapshot = .legacy(event)
        trade.mutations = [IntentMutation(clientID: "entry", eventID: "original", sell: false, quantity: 2,
            order: AlpacaOrder(id: "entry-broker", client_order_id: "entry", symbol: symbol, status: "canceled", qty: "2", limit_price: "0.20", filled_qty: "1.0", filled_avg_price: "0.20", side: "buy"))]
        saved.trades[event.trade_id] = trade
        let (controller, file) = try makeController(saved)
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: file) }
        var quantities: [String] = []
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" {
                return (200, Data(#"{"id":"account","status":"ACTIVE","buying_power":"1000","equity":"1000","trading_blocked":false,"account_blocked":false}"#.utf8))
            }
            if request.url?.path == "/v2/positions" {
                return (200, try JSONSerialization.data(withJSONObject: [["symbol": symbol, "qty": "50", "qty_available": "50", "avg_entry_price": "0.20"], ["symbol": "AAPL", "qty": "100", "qty_available": "100", "avg_entry_price": "10"]]))
            }
            XCTAssertEqual(request.httpMethod, "POST")
            var data = request.httpBody ?? Data()
            if let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; data.append(contentsOf: buffer.prefix(count)) }
            }
            let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            quantities.append(try XCTUnwrap(body["qty"] as? String))
            XCTAssertEqual(body["symbol"] as? String, symbol)
            XCTAssertEqual(body["limit_price"] as? String, "0.20")
            XCTAssertEqual(body["position_intent"] as? String, "sell_to_close")
            let clientID = try XCTUnwrap(body["client_order_id"] as? String)
            return (200, try JSONEncoder().encode(AlpacaOrder(id: "exit-broker", client_order_id: clientID, symbol: symbol, status: "filled", qty: "1", limit_price: "0.20", filled_qty: "1", filled_avg_price: "0.20", side: "sell")))
        }
        try controller.connect(api: api(), account: "account", pairing: pair(), startWorkers: false)
        await controller.process(); await controller.process()
        XCTAssertEqual(quantities, ["1"])
        XCTAssertEqual(controller.state.trades[event.trade_id]?.owned, 0)
    }
    func testCredentialRotationVerifiesAccountBeforeSavingAndPreservesUnresolvedJournal() async throws {
        var saved = IntentState(); saved.accountID = "original-account"; saved.pairingID = pair().fingerprint
        var trade = IntentTrade(); trade.mutations = [IntentMutation(clientID: "pending-client", eventID: "event", sell: false, quantity: 1)]
        saved.trades["pending"] = trade
        let (controller, intentFile) = try makeController(saved)
        let journalFile = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { controller.disconnect(); try? FileManager.default.removeItem(at: intentFile); try? FileManager.default.removeItem(at: journalFile) }
        let journal = try AlpacaJournal(file: journalFile)
        var written: [String] = []
        var accountID = "other-account"
        AlpacaMockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            if request.url?.path == "/v2/account" {
                return (200, try JSONSerialization.data(withJSONObject: ["id": accountID, "status": "ACTIVE", "buying_power": "1000", "equity": "1000", "trading_blocked": false, "account_blocked": false]))
            }
            return (200, Data("[]".utf8))
        }
        let model = AlpacaWorkspace(journal: journal, intentController: controller,
            makeClient: { environment, credentials in AlpacaREST(environment: environment, credentials: credentials, session: self.session()) },
            loadCredentials: { _ in AlpacaCredentials(key: "saved-key", secret: "saved-secret") },
            saveCredentials: { credentials, _ in written.append(credentials.key) })
        model.selectPurpose(.trade)
        // Disconnected rotation is still identity checked before replacing saved keys.
        await model.connect(key: "wrong-account-key", secret: "candidate-secret")
        XCTAssertTrue(written.isEmpty); XCTAssertNil(model.account)
        accountID = "original-account"
        await model.connect(key: "rotated-same-account-key", secret: "candidate-secret")
        XCTAssertEqual(written, ["rotated-same-account-key"])
        XCTAssertEqual(model.account?.id, "original-account")
        XCTAssertEqual(controller.state.trades["pending"]?.mutations.first?.clientID, "pending-client")
        await model.sceneActive(false)
        XCTAssertTrue(model.lifecycle.contains("suspended"))
        XCTAssertEqual(controller.state.unresolved, ["pending"])
        model.disconnect()
    }
    func testReceiverListAndRevocationUseHostTokenAndExactReceiver() async throws {
        let id = UUID().uuidString.lowercased()
        var requests: [String] = []
        AlpacaMockURLProtocol.handler = { request in
            requests.append(request.url!.path)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + String(repeating: "x", count: 32))
            if request.httpMethod == "POST" { return (200, Data(#"{"revoked":true}"#.utf8)) }
            return (200, try JSONSerialization.data(withJSONObject: [["id": id, "created": 1_800_000_000, "revoked": 0]]))
        }
        for prefix in ["", "/functions/v1/crier"] {
            requests.removeAll()
            var pairing = pair("host")
            pairing.url = URL(string: "https://project.supabase.co" + prefix)!
            let receivers = try await QuickConnection.receivers(pairing, session: session())
            try await QuickConnection.revoke(XCTUnwrap(receivers.first), pairing: pairing, session: session())
            XCTAssertEqual(requests, [prefix + "/api/connect/receivers", prefix + "/api/connect/receivers/" + id + "/revoke"])
        }
    }
}

final class Phase2DiscordOutboxTests: XCTestCase {
    func testExplicitUncertainRetryAndClosePreserveEvidenceAcrossRestart() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let journal = try AlpacaJournal(file: file)
        let preview = DiscordAlertSettings.preview
        try await journal.ingest(preview.fill, environment: .paper, accountID: "account")
        let delivery = try await journal.claim(environment: .paper, accountID: "account")
        let id = try XCTUnwrap(delivery).id
        do { try await journal.retry(id, acknowledgeDuplicateRisk: false); XCTFail("Uncertain retry requires explicit acknowledgement") } catch {}
        let outstanding = await journal.hasOutstandingDeliveries(); XCTAssertTrue(outstanding)
        try await journal.retry(id, acknowledgeDuplicateRisk: true)
        let reclaimed = try await journal.claim(environment: .paper, accountID: "account"); XCTAssertNotNil(reclaimed)
        try await journal.closeDelivery(id)
        let restored = try AlpacaJournal(file: file)
        let snapshot = await restored.snapshot()
        XCTAssertEqual(snapshot.deliveries.first?.fill, preview.fill)
        XCTAssertEqual(snapshot.deliveries.first?.state, "closed by user")
        let pending = await restored.hasOutstandingDeliveries(); XCTAssertFalse(pending)
        let next = try await restored.claim(environment: .paper, accountID: "account"); XCTAssertNil(next)
    }
    func testManualRetryDoesNotBypassPersistedRateLimit() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let journal = try AlpacaJournal(file: file)
        try await journal.ingest(DiscordAlertSettings.preview.fill, environment: .paper, accountID: "account")
        let claimed = try await journal.claim(environment: .paper, accountID: "account")
        let id = try XCTUnwrap(claimed).id
        try await journal.rateLimited(id, retryAfter: 60)
        try await journal.retry(id, acknowledgeDuplicateRisk: false)
        let restored = try AlpacaJournal(file: file)
        let early = try await restored.claim(environment: .paper, accountID: "account"); XCTAssertNil(early)
        let later = try await restored.claim(environment: .paper, accountID: "account", now: Date().addingTimeInterval(70)); XCTAssertNotNil(later)
    }
    func testDefinitiveWebhookFailureNeedsExplicitRetry() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let journal = try AlpacaJournal(file: file)
        try await journal.ingest(DiscordAlertSettings.preview.fill, environment: .paper, accountID: "account")
        let delivery = try await journal.claim(environment: .paper, accountID: "account")
        let id = try XCTUnwrap(delivery).id
        try await journal.refused(id, status: 401)
        let automatic = try await journal.claim(environment: .paper, accountID: "account"); XCTAssertNil(automatic)
        try await journal.retry(id, acknowledgeDuplicateRisk: false)
        let manual = try await journal.claim(environment: .paper, accountID: "account"); XCTAssertNotNil(manual)
    }
}
