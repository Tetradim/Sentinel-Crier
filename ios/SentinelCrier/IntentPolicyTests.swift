import XCTest
@testable import SentinelCrier

final class IntentPolicyTests: XCTestCase {
    private func event(_ sequence: Int = 1, action: String = "enter", quantity: Int = 10, tradeID: String = UUID().uuidString.lowercased()) -> IntentEvent {
        IntentEvent.make(trade: tradeID, sequence: sequence, action: action, environment: .paper, symbol: "AAPL", asset: "stock", quantity: quantity, price: "10")
    }
    func testStrictPolicyDecodingAndLegacyDefault() throws {
        XCTAssertNil(try JSONDecoder().decode(IntentPreferences.self, from: Data("{}".utf8)).execution_policy)
        for text in [#"{"mode":"fixed","fixed_quantity":true}"#, #"{"mode":"fixed","fixed_quantity":0}"#, #"{"mode":"ratio","ratio_bps":10001}"#, #"{"mode":"budget","budget":"1e2"}"#, #"{"mode":"budget","budget":"01"}"#, #"{"mode":"source","fixed_quantity":1}"#, #"{"unknown":1}"#, #"{"entry_timeout_seconds":86401}"#] {
            XCTAssertThrowsError(try JSONDecoder().decode(IntentExecutionPolicy.self, from: Data(text.utf8)), text)
        }
        for key in ["version", "mode", "max_source_quantity", "max_local_quantity", "exit_mode"] {
            let data = try JSONSerialization.data(withJSONObject: [key: NSNull()])
            XCTAssertThrowsError(try JSONDecoder().decode(IntentExecutionPolicy.self, from: data), key + " must reject explicit null")
        }
        XCTAssertNoThrow(try JSONDecoder().decode(IntentExecutionPolicy.self, from: Data("{}".utf8)))
        var policy = IntentExecutionPolicy(); policy.mode = "budget"; policy.budget = "150"
        XCTAssertThrowsError(try policy.validate(market: true))
        XCTAssertEqual(try policy.target(source: 10, price: "0.22", multiplier: 100, bought: 0, spent: 0), 6)
        XCTAssertEqual(try policy.target(source: 10, price: "0.20", multiplier: 100, bought: 3, spent: 66), 7)
    }
    func testSharedFirstEntryFixtures() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "policy-preview", withExtension: "json"))
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        for row in try XCTUnwrap(fixture["entry"] as? [[String: Any]]) {
            let input = try XCTUnwrap(row["input"] as? [String: Any]); let expected = try XCTUnwrap(row["expected"] as? [String: Any])
            let policy = try JSONDecoder().decode(IntentExecutionPolicy.self, from: JSONSerialization.data(withJSONObject: input["policy"] ?? [:]))
            let multiplier = input["asset"] as? String == "option" ? (input["contract_size"] as? Int ?? 0) : (input["contract_size"] as? Int ?? 1)
            if expected["decision"] as? String == "eligible" || expected["reason"] as? String == "below_one_unit" {
                XCTAssertEqual(try policy.target(source: input["source_quantity"] as! Int, price: input["limit_price"] as? String, multiplier: multiplier, bought: 0, spent: 0), expected["target_quantity"] as? Int, row["id"] as? String ?? "fixture")
            } else {
                XCTAssertThrowsError(try policy.target(source: input["source_quantity"] as! Int, price: input["limit_price"] as? String, multiplier: multiplier, bought: 0, spent: 0), row["id"] as? String ?? "fixture")
            }
        }
    }
    func testSnapshotAtReceiptPinsPolicyAndSourceCap() throws {
        var state = IntentState(); state.pairingID = "scope"; state.pairingRole = "follower"; state.accountID = "account"
        state.preferences.paused = false; state.preferences.maxQuantity = 8
        var policy = IntentExecutionPolicy(); policy.mode = "fixed"; policy.fixed_quantity = 3
        state.preferences.execution_policy = policy
        let first = event(quantity: 7)
        _ = try state.ingestPage(JSONSerialization.data(withJSONObject: ["events": [["cursor": 1, "event": JSONSerialization.jsonObject(with: JSONEncoder().encode(first))]]]), environment: .paper)
        state.preferences.execution_policy?.fixed_quantity = 9
        XCTAssertEqual(state.trades[first.trade_id]?.policySnapshot?.policy?.fixed_quantity, 3)
        XCTAssertEqual(state.trades[first.trade_id]?.policySnapshot?.policy?.max_source_quantity, 8)
        state.pairingRole = "host"
        let host = event()
        _ = try state.ingestPage(JSONSerialization.data(withJSONObject: ["events": [["cursor": 2, "event": JSONSerialization.jsonObject(with: JSONEncoder().encode(host))]]]), environment: .paper)
        XCTAssertEqual(state.trades[host.trade_id]?.policySnapshot?.legacy, true)
    }
    func testCumulativePurchaseCostsNeverReplenishAfterSale() throws {
        var trade = IntentTrade()
        func mutation(_ sell: Bool, quantity: Int, average: String?) -> IntentMutation {
            IntentMutation(clientID: sell ? "sale" : "buy", eventID: "event", sell: sell, quantity: quantity,
                order: AlpacaOrder(id: "broker", client_order_id: sell ? "sale" : "buy", symbol: "AAPL", status: "filled", qty: String(quantity), limit_price: "10", filled_qty: String(quantity), filled_avg_price: average, side: sell ? "sell" : "buy"))
        }
        trade.mutations = [mutation(false, quantity: 7, average: "0.22"), mutation(true, quantity: 3, average: "1")]
        XCTAssertEqual(trade.bought, 7); XCTAssertEqual(trade.owned, 4)
        XCTAssertEqual(try trade.premiumSpent(multiplier: 100), 154)
        trade.mutations[0] = mutation(false, quantity: 7, average: nil)
        XCTAssertThrowsError(try trade.premiumSpent(multiplier: 100))
        XCTAssertEqual(trade.owned, 4)
    }
    func testBrokerWeightedAverageRetainsLongFractionAndRejectsInvalidPrecision() throws {
        let average = "0.1666666667"
        XCTAssertEqual(try IntentBrokerDecimal.price(average), Decimal(string: average))
        var trade = IntentTrade()
        trade.mutations = [IntentMutation(clientID: "buy", eventID: "event", sell: false, quantity: 3,
            order: AlpacaOrder(id: "broker", client_order_id: "buy", symbol: "AAPL", status: "filled", qty: "3", limit_price: "1", filled_qty: "3", filled_avg_price: average, side: "buy"))]
        XCTAssertEqual(try trade.premiumSpent(multiplier: 100), Decimal(string: "50.00000001"))
        for value in ["NaN", "Infinity", "0", "-1", "0.123456789012345678901234567890123456789123456789"] {
            XCTAssertThrowsError(try IntentBrokerDecimal.price(value), value)
        }
        XCTAssertEqual(try IntentBrokerDecimal.price("000.166666666700"), Decimal(string: average))
    }
    func testProportionalHistoryUsesDistinctCumulativeExitIntentAndRejectsGaps() throws {
        let entry = event(); let first = event(2, action: "exit", quantity: 2, tradeID: entry.trade_id)
        let second = event(3, action: "exit", quantity: 3, tradeID: entry.trade_id)
        var trade = IntentTrade()
        trade.mutations = [IntentMutation(clientID: "buy", eventID: entry.event_id, sell: false, quantity: 7,
            order: AlpacaOrder(id: "buy", client_order_id: "buy", symbol: "AAPL", status: "filled", qty: "7", limit_price: "10", filled_qty: "7", filled_avg_price: nil, side: "buy"))]
        let history = [entry.event_id: entry, first.event_id: first, second.event_id: second]
        XCTAssertEqual(try trade.proportionalDue(event: second, history: history), 3)
        XCTAssertThrowsError(try trade.proportionalDue(event: second, history: [entry.event_id: entry, second.event_id: second]))
        trade.sourceHistoryInvalid = true
        XCTAssertThrowsError(try trade.proportionalDue(event: second, history: history))
    }
}

@MainActor
final class IntentPolicyRuntimeTests: XCTestCase {
    private var file: URL!
    override func setUp() { super.setUp(); file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json") }
    override func tearDown() { AlpacaMockURLProtocol.handler = nil; if let file { try? FileManager.default.removeItem(at: file) }; super.tearDown() }
    private func session() -> URLSession { let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [AlpacaMockURLProtocol.self]; return URLSession(configuration: config) }
    private func pair() -> IntentPairing { IntentPairing(url: URL(string: "https://relay.test")!, token: String(repeating: "x", count: 32), environment: .paper, role: "follower") }
    private func write(_ state: IntentState) throws { try JSONEncoder().encode(state).write(to: file) }
    private func make(policy: IntentExecutionPolicy, uptime: @escaping () -> TimeInterval = { 100 }) throws -> (IntentController, IntentEvent, AlpacaREST) {
        var state = IntentState(); state.preferences.paused = false; state.preferences.execution_policy = policy
        state.pairingID = pair().fingerprint; state.pairingRole = "follower"; state.accountID = "account"
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 10, price: "10")
        let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(event))
        _ = try state.ingestPage(JSONSerialization.data(withJSONObject: ["events": [["cursor": 1, "event": object]]]), environment: .paper)
        try write(state)
        let controller = try IntentController(file: file, monotonic: uptime, session: session())
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test", secret: "test"), session: session())
        try controller.connect(api: api, account: "account", pairing: pair(), startWorkers: false)
        return (controller, event, api)
    }
    private static let account = Data(#"{"id":"account","status":"ACTIVE","currency":"USD","buying_power":"10000","equity":"10000","trading_blocked":false,"account_blocked":false}"#.utf8)
    private static let asset = Data(#"{"id":"asset-id","symbol":"AAPL","status":"active","tradable":true,"class":"us_equity"}"#.utf8)
    private func order(_ client: String, quantity: String = "3", status: String = "new", filled: String = "0") throws -> Data {
        try JSONSerialization.data(withJSONObject: ["id": "broker-id", "client_order_id": client, "symbol": "AAPL", "status": status, "qty": quantity, "limit_price": "10", "filled_qty": filled, "filled_avg_price": "10", "side": "buy"])
    }
    private static func body(_ request: URLRequest) throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; data.append(contentsOf: buffer.prefix(count)) }
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
    func testMigrationOnlyAppliesToPreSchemaJournal() throws {
        let event = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 1, price: "10")
        var trade = IntentTrade(); try trade.accept(event)
        var state = IntentState(); state.trades[event.trade_id] = trade
        try write(state)
        XCTAssertThrowsError(try IntentController(file: file))
        state.policySchema = nil; try write(state)
        let migrated = try IntentController(file: file)
        XCTAssertEqual(migrated.state.policySchema, 1); XCTAssertEqual(migrated.state.trades[event.trade_id]?.policySnapshot?.legacy, true)
        XCTAssertNil(migrated.state.trades[event.trade_id]?.policySnapshot?.policy)
    }
    func testPolicyEditMustRemainPausedAndDoesNotAlterReceiptSnapshot() throws {
        var policy = IntentExecutionPolicy(); policy.mode = "fixed"; policy.fixed_quantity = 3
        let (controller, event, _) = try make(policy: policy); defer { controller.disconnect() }
        var preferences = controller.state.preferences; preferences.execution_policy?.fixed_quantity = 7
        XCTAssertThrowsError(try controller.settings(preferences))
        preferences.paused = true; try controller.settings(preferences)
        XCTAssertEqual(controller.state.trades[event.trade_id]?.policySnapshot?.policy?.fixed_quantity, 3)
        preferences.paused = false; try controller.settings(preferences)
    }
    func testFrozenTargetAndFinalMetadataRefusalNeverPostUnchecked() async throws {
        var policy = IntentExecutionPolicy(); policy.mode = "fixed"; policy.fixed_quantity = 3
        let (controller, event, _) = try make(policy: policy); defer { controller.disconnect() }
        var assetReads = 0; var posts = 0
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" { return (200, Self.account) }
            if request.url?.path == "/v2/assets/AAPL" {
                assetReads += 1
                if assetReads == 2 { return (200, Data(#"{"id":"changed","symbol":"AAPL","status":"active","tradable":true,"class":"us_equity"}"#.utf8)) }
                return (200, Self.asset)
            }
            posts += 1; return (500, Data())
        }
        await controller.process()
        XCTAssertEqual(posts, 0); XCTAssertEqual(assetReads, 2)
        XCTAssertEqual(controller.state.trades[event.trade_id]?.entryPlans?[event.event_id]?.target, 3)
        XCTAssertEqual(controller.state.trades[event.trade_id]?.mutations.first?.notSubmitted, true)
        let restored = try IntentController(file: file)
        XCTAssertEqual(restored.state.trades[event.trade_id]?.entryPlans?[event.event_id]?.target, 3)
        var corrupted = restored.state
        corrupted.trades[event.trade_id]!.entryPlans![event.event_id]!.target = 1001
        try write(corrupted)
        XCTAssertThrowsError(try IntentController(file: file))
        corrupted = restored.state
        corrupted.trades[event.trade_id]!.entryPlans![event.event_id]!.target = 4
        try write(corrupted)
        XCTAssertThrowsError(try IntentController(file: file)) // Within cap, but inconsistent with frozen fixed quantity.
        corrupted = restored.state
        corrupted.trades[event.trade_id]!.entryPlans![event.event_id]!.price = "100"
        try write(corrupted)
        XCTAssertThrowsError(try IntentController(file: file)) // A positive fixed-mode price must match frozen pricing evidence.
        corrupted = restored.state; corrupted.policySchema = nil; try write(corrupted)
        XCTAssertThrowsError(try IntentController(file: file)) // A lost migration marker must never downgrade advanced plans.
    }
    func testTimerStartsAfterLookupAndCancelsPartialRemainderWithoutSelling() async throws {
        var policy = IntentExecutionPolicy(); policy.mode = "fixed"; policy.fixed_quantity = 3; policy.entry_timeout_seconds = 5
        var uptime: TimeInterval = 100
        let (controller, event, _) = try make(policy: policy, uptime: { uptime }); defer { controller.disconnect() }
        var client = ""; var posts = 0; var deletes = 0
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" { return (200, Self.account) }
            if request.url?.path == "/v2/assets/AAPL" { return (200, Self.asset) }
            if request.httpMethod == "POST" {
                posts += 1; let body = try Self.body(request); client = try XCTUnwrap(body["client_order_id"] as? String)
                XCTAssertEqual(body["qty"] as? String, "3"); XCTAssertNil(body["policyBinding"])
                return (200, try self.order(client))
            }
            if request.httpMethod == "DELETE" { deletes += 1; XCTAssertEqual(request.url?.path, "/v2/orders/broker-id"); return (204, Data()) }
            return (200, try self.order(client, status: "partially_filled", filled: "1"))
        }
        await controller.process()
        XCTAssertNil(controller.state.trades[event.trade_id]?.mutations.first?.acknowledgedSession)
        await controller.process()
        XCTAssertNotNil(controller.state.trades[event.trade_id]?.mutations.first?.acknowledgedSession)
        uptime += 6; await controller.process()
        XCTAssertEqual(posts, 1); XCTAssertEqual(deletes, 1)
        XCTAssertEqual(controller.state.trades[event.trade_id]?.entryClosed, true)
        XCTAssertEqual(controller.state.trades[event.trade_id]?.owned, 1)
    }
    func testRestartCancelsAcknowledgedBuyOnlyAfterFreshLookup() async throws {
        var policy = IntentExecutionPolicy(); policy.mode = "fixed"; policy.fixed_quantity = 3; policy.entry_timeout_seconds = 60
        let (controller, event, _) = try make(policy: policy)
        var client = ""; var deletes = 0; var lookups = 0
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" { return (200, Self.account) }
            if request.url?.path == "/v2/assets/AAPL" { return (200, Self.asset) }
            if request.httpMethod == "POST" { client = try XCTUnwrap(Self.body(request)["client_order_id"] as? String); return (200, try self.order(client)) }
            if request.httpMethod == "DELETE" { deletes += 1; XCTAssertGreaterThan(lookups, 1); return (204, Data()) }
            lookups += 1; return (200, try self.order(client))
        }
        await controller.process(); await controller.process(); controller.disconnect()
        var damagedAcknowledgement = controller.state
        damagedAcknowledgement.trades[event.trade_id]!.mutations[0].acknowledgedSession = nil
        damagedAcknowledgement.trades[event.trade_id]!.mutations[0].acknowledgedUptime = nil
        try write(damagedAcknowledgement)
        let restored = try IntentController(file: file, monotonic: { 1 }, session: session())
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test", secret: "test"), session: session())
        try restored.connect(api: api, account: "account", pairing: pair(), startWorkers: false); defer { restored.disconnect() }
        await restored.process()
        XCTAssertEqual(deletes, 1); XCTAssertEqual(restored.state.trades[event.trade_id]?.entryClosed, true)
    }
    func testUnknownPostFirstObservedAfterRestartStartsTimerWithoutImmediateCancel() async throws {
        var policy = IntentExecutionPolicy(); policy.mode = "fixed"; policy.fixed_quantity = 3; policy.entry_timeout_seconds = 5
        let (controller, event, _) = try make(policy: policy)
        var client = ""; var deletes = 0; var posts = 0
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" { return (200, Self.account) }
            if request.url?.path == "/v2/assets/AAPL" { return (200, Self.asset) }
            if request.httpMethod == "POST" {
                posts += 1; client = try XCTUnwrap(Self.body(request)["client_order_id"] as? String)
                return (422, Data()) // Ambiguous/duplicate response remains unknown, never replayed.
            }
            if request.httpMethod == "DELETE" { deletes += 1; return (204, Data()) }
            return (200, try self.order(client))
        }
        await controller.process(); controller.disconnect()
        XCTAssertNil(controller.state.trades[event.trade_id]?.mutations.first?.order)
        var uptime: TimeInterval = 1
        let restored = try IntentController(file: file, monotonic: { uptime }, session: session())
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test", secret: "test"), session: session())
        try restored.connect(api: api, account: "account", pairing: pair(), startWorkers: false); defer { restored.disconnect() }
        await restored.process()
        XCTAssertEqual(posts, 1); XCTAssertEqual(deletes, 0)
        XCTAssertNotNil(restored.state.trades[event.trade_id]?.mutations.first?.acknowledgedSession)
        uptime += 6; await restored.process()
        XCTAssertEqual(deletes, 1); XCTAssertEqual(restored.state.trades[event.trade_id]?.entryClosed, true)
    }

    func testMissingPriorBuyPlanBlocksReplaceButAllowsTrackedExit() async throws {
        var policy = IntentExecutionPolicy(); policy.mode = "fixed"; policy.fixed_quantity = 3; policy.exit_mode = "close_tracked"
        let (controller, first, _) = try make(policy: policy)
        var posts = 0
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" { return (200, Self.account) }
            if request.url?.path == "/v2/assets/AAPL" { return (200, Self.asset) }
            posts += 1
            let body = try Self.body(request)
            return (200, try self.order(try XCTUnwrap(body["client_order_id"] as? String), status: "filled", filled: "3"))
        }
        await controller.process(); controller.disconnect()
        XCTAssertEqual(posts, 1)
        var saved = controller.state
        saved.trades[first.trade_id]!.entryPlans?.removeValue(forKey: first.event_id)
        var replacement = first; replacement.sequence = 2; replacement.action = "replace"; replacement.event_id = UUID().uuidString.lowercased()
        try saved.trades[first.trade_id]!.accept(replacement); saved.received[replacement.event_id] = replacement
        try write(saved)
        let restored = try IntentController(file: file, session: session())
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test", secret: "test"), session: session())
        try restored.connect(api: api, account: "account", pairing: pair(), startWorkers: false)
        await restored.process(); restored.disconnect()
        XCTAssertEqual(posts, 1)
        XCTAssertNil(restored.state.trades[first.trade_id]?.entryPlans?[replacement.event_id])
        XCTAssertTrue(restored.state.trades[first.trade_id]?.policyRefusals?[replacement.event_id]?.contains("no frozen plan") == true)
        var exiting = restored.state
        var exit = replacement; exit.sequence = 3; exit.action = "exit"; exit.event_id = UUID().uuidString.lowercased(); exit.quantity = 1
        try exiting.trades[first.trade_id]!.accept(exit); exiting.received[exit.event_id] = exit
        try write(exiting)
        let exitController = try IntentController(file: file, session: session())
        let exitAPI = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "test", secret: "test"), session: session())
        try exitController.connect(api: exitAPI, account: "account", pairing: pair(), startWorkers: false); defer { exitController.disconnect() }
        AlpacaMockURLProtocol.handler = { request in
            if request.url?.path == "/v2/account" { return (200, Self.account) }
            if request.url?.path == "/v2/assets/AAPL" { return (200, Self.asset) }
            if request.url?.path == "/v2/positions" { return (200, Data(#"[{"symbol":"AAPL","qty":"100","qty_available":"100","avg_entry_price":"10"}]"#.utf8)) }
            posts += 1; let body = try Self.body(request)
            XCTAssertEqual(body["side"] as? String, "sell"); XCTAssertEqual(body["qty"] as? String, "3")
            return (200, try JSONSerialization.data(withJSONObject: ["id": "sell-broker", "client_order_id": try XCTUnwrap(body["client_order_id"] as? String), "symbol": "AAPL", "status": "filled", "qty": "3", "filled_qty": "3", "filled_avg_price": "10", "side": "sell"]))
        }
        await exitController.process()
        XCTAssertEqual(posts, 2); XCTAssertEqual(exitController.state.trades[first.trade_id]?.owned, 0)
    }

}
