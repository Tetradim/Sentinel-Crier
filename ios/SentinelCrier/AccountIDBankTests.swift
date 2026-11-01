import XCTest
@testable import SentinelCrier

@MainActor final class AccountIDBankTests: XCTestCase {
    private func bank() throws -> AccountIDBank {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        return try AccountIDBank(file: folder.appendingPathComponent("bank.json"))
    }
    private let scope = BankScope(account: "synthetic", environment: .paper)
    private func setup(_ bank: AccountIDBank) throws {
        try bank.enable(scope, cash: 1000, equity: 1000, positions: [:])
        for route in ["alice", "dave"] { try bank.configure(scope, route: route, asset: "option", mode: "units", value: "10", fee: "0") }
    }
    private func reserve(_ bank: AccountIDBank, route: String = "alice", trade: String = "t", event: String = "e", sell: Bool = false, qty: Int = 3) throws -> String {
        let cid = AccountIDBank.clientID(scope, route: route, trade: trade, event: event, sell: sell, ordinal: 0)
        try bank.reserve(scope, route: route, trade: trade, event: event, cid: cid, symbol: "SPY270115C00600000", asset: "option", multiplier: 100, sell: sell, quantity: qty, price: "1", ordinal: 0, cash: 1000, equity: 1000)
        return cid
    }
    private func proof(_ cid: String, qty: Int = 3, filled: Int, sell: Bool = false, status: String) -> AlpacaOrder {
        AlpacaOrder(id: "broker-" + cid, client_order_id: cid, symbol: "SPY270115C00600000", status: status, qty: String(qty), limit_price: "1", filled_qty: String(filled), filled_avg_price: filled > 0 ? "1" : nil, side: sell ? "sell" : "buy")
    }
    func testReservationsPersistAndCompeteAcrossInstances() throws {
        let bank = try bank(); try setup(bank)
        _ = try reserve(bank, qty: 7)
        let restarted = try AccountIDBank(file: bank.file)
        XCTAssertThrowsError(try reserve(restarted, route: "dave", trade: "other", event: "other", qty: 4))
        XCTAssertEqual(try restarted.snapshot(scope).available, Decimal(300))
        XCTAssertThrowsError(try reserve(restarted, route: "dave", trade: "other", event: "e", qty: 1))
    }
    func testOwnedExitsPendingCancellationAndTombstones() throws {
        let bank = try bank(); try setup(bank)
        let cid = try reserve(bank)
        try bank.observe(scope, proof(cid, filled: 2, status: "pending_cancel"))
        XCTAssertThrowsError(try bank.retire(scope, route: "alice", trade: "t", reason: "cancel"))
        XCTAssertEqual(try bank.snapshot(scope).available, Decimal(700))
        try bank.observe(scope, proof(cid, filled: 2, status: "canceled"))
        XCTAssertEqual(try bank.snapshot(scope).available, Decimal(800))
        XCTAssertThrowsError(try reserve(bank, route: "dave", event: "exit", sell: true, qty: 1))
        let exit = try reserve(bank, event: "exit", sell: true, qty: 2)
        XCTAssertThrowsError(try reserve(bank, event: "exit-again", sell: true, qty: 1))
        try bank.observe(scope, proof(exit, qty: 2, filled: 2, sell: true, status: "filled"))
        XCTAssertTrue(try bank.snapshot(scope).lots.allSatisfy { !$0.active })
        XCTAssertThrowsError(try reserve(bank, event: "reopen"))
    }
    func testTimeoutNeverResubmitsAndMultiplierIsExact() throws {
        let bank = try bank(); try setup(bank)
        let cid = try reserve(bank)
        try bank.markDispatching(scope, cid: cid)
        XCTAssertThrowsError(try bank.markDispatching(scope, cid: cid))
        XCTAssertThrowsError(try bank.retire(scope, route: "alice", trade: "t", reason: "timeout"))
        XCTAssertThrowsError(try bank.reserve(scope, route: "alice", trade: "bad", event: "bad", cid: "bad", symbol: "SPY", asset: "option", multiplier: 10, sell: false, quantity: 1, price: "1", ordinal: 0, cash: 1000, equity: 1000))
    }
    func testInventoryMismatchBlocksAndNeverAdoptsExternalHoldings() throws {
        let bank = try bank(); try setup(bank)
        XCTAssertThrowsError(try bank.inventory(scope, positions: ["SPY": 1]))
        XCTAssertThrowsError(try reserve(bank))
        try bank.inventory(scope, positions: [:])
        _ = try reserve(bank)
    }
    func testCanonicalAmountsAndFallingEquityRefuseAdmission() throws {
        for text in ["1.2.3", ".1", "1.", "01", "1e2", "-1", "NaN", "1 trailing", " 1", "0.123456789", "1234567890123456789012345"] { XCTAssertThrowsError(try AccountIDBank.money(text)) }
        let bank = try bank(); try setup(bank)
        _ = try reserve(bank)
        let cid = AccountIDBank.clientID(scope, route: "dave", trade: "new", event: "new", sell: false, ordinal: 0)
        XCTAssertThrowsError(try bank.reserve(scope, route: "dave", trade: "new", event: "new", cid: cid, symbol: "SPY270115C00600000", asset: "option", multiplier: 100, sell: false, quantity: 1, price: "1", ordinal: 0, cash: 1000, equity: 50))
    }
    func testDebtPersistsAcrossRestartAndOrdinaryRebaseUntilExplicitVerifiedFlatRepair() throws {
        let bank = try bank(); try setup(bank)
        let original = try reserve(bank, qty: 10)
        try bank.observe(scope, proof(original, qty: 10, filled: 0, status: "canceled"))
        try bank.retire(scope, route: "alice", trade: "t", reason: "canceled")
        let competing = try reserve(bank, route: "dave", trade: "dave", event: "dave", qty: 10)
        try bank.observe(scope, proof(original, qty: 10, filled: 2, status: "canceled"))
        XCTAssertEqual(try bank.snapshot(scope).available, -200)
        let restarted = try AccountIDBank(file: bank.file)
        XCTAssertEqual(try restarted.snapshot(scope).available, -200)
        try restarted.rebaseIfFlat(scope, cash: 1000, equity: 1000)
        XCTAssertEqual(try restarted.snapshot(scope).blocked, "capacity_deficit")
        XCTAssertThrowsError(try restarted.repairVerifiedFlat(scope, cash: 1000, equity: 1000, positions: [:], observedAt: Date()))
        try restarted.notSubmitted(scope, cid: competing)
        let exit = try reserve(restarted, event: "exit", sell: true, qty: 2)
        try restarted.observe(scope, proof(exit, qty: 2, filled: 2, sell: true, status: "filled"))
        try restarted.inventory(scope, positions: [:])
        try restarted.rebaseIfFlat(scope, cash: 1000, equity: 1000)
        XCTAssertEqual(try restarted.snapshot(scope).blocked, "capacity_deficit")
        XCTAssertThrowsError(try restarted.repairVerifiedFlat(scope, cash: 1000, equity: 1000, positions: [:], observedAt: Date().addingTimeInterval(-11)))
        try restarted.repairVerifiedFlat(scope, cash: 1000, equity: 1000, positions: [:], observedAt: Date())
        XCTAssertEqual(try restarted.snapshot(scope).blocked, "")
        XCTAssertEqual(try restarted.snapshot(scope).lots.count, 2)
        XCTAssertEqual(try restarted.snapshot(scope).orders.count, 3)
        XCTAssertTrue(try restarted.snapshot(scope).audit?.last?.contains("explicit_verified_flat_repair") == true)
    }
    func testFailedRepairKeepsEntriesDurablyPausedAcrossReconnect() async throws {
        let bank = try bank()
        let file = bank.file.deletingLastPathComponent().appendingPathComponent("intent.json")
        let controller = try IntentController(file: file)
        var preferences = controller.state.preferences; preferences.paused = false
        try controller.settings(preferences)
        XCTAssertFalse(controller.state.preferences.paused)
        try controller.pauseEntriesForBankTransition()
        controller.disconnect(); await controller.drainStoppedWork()
        // No enabled/verified account: a failed repair cannot resume entry settings.
        XCTAssertThrowsError(try bank.repairVerifiedFlat(scope, cash: 1000, equity: 1000, positions: [:], observedAt: Date()))
        let restored = try IntentController(file: file)
        XCTAssertTrue(restored.state.preferences.paused)
        let pair = IntentPairing(url: URL(string: "https://synthetic.invalid/intent")!, token: String(repeating: "x", count: 32), environment: .paper, role: "follower")
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "synthetic", secret: "synthetic"))
        try restored.connect(api: api, account: "synthetic", pairing: pair, startWorkers: false)
        XCTAssertTrue(restored.state.preferences.paused)
        restored.disconnect(); await restored.drainStoppedWork()
    }
    func testGlobalTransitionRefusesSecondConnectAcrossSuspension() async throws {
        let bank = try bank()
        let registry = try ConnectionRouteRegistry(file: bank.file.deletingLastPathComponent().appendingPathComponent("routes.json"), bank: bank)
        let controller = try IntentController(file: bank.file.deletingLastPathComponent().appendingPathComponent("intent.json"))
        controller.executionAdmission = { !registry.bankTransition }
        let pair = IntentPairing(url: URL(string: "https://synthetic.invalid/intent")!, token: String(repeating: "x", count: 32), environment: .paper, role: "host")
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: "synthetic", secret: "synthetic"))
        try registry.beginBankTransition()
        await Task.yield() // Setup's broker reads suspend while the central gate remains held.
        XCTAssertThrowsError(try registry.requireExecutionAdmission())
        XCTAssertThrowsError(try controller.connect(api: api, account: "synthetic", pairing: pair, startWorkers: false))
        XCTAssertFalse(controller.connected)
        XCTAssertThrowsError(try registry.beginBankTransition())
        registry.endBankTransition()
        try controller.connect(api: api, account: "synthetic", pairing: pair, startWorkers: false)
        XCTAssertTrue(controller.connected)
        controller.disconnect(); await controller.drainStoppedWork()
    }
    func testLateFillReactivatesTombstoneAndPermanentlyBlocksEntries() throws {
        let bank = try bank(); try setup(bank)
        let cid = try reserve(bank)
        try bank.observe(scope, proof(cid, filled: 0, status: "canceled"))
        try bank.retire(scope, route: "alice", trade: "t", reason: "cancel")
        try bank.observe(scope, proof(cid, filled: 1, status: "canceled"))
        try bank.inventory(scope, positions: ["SPY270115C00600000": 1])
        XCTAssertEqual(try bank.snapshot(scope).blocked, "late_terminal_fill")
        XCTAssertEqual(try bank.snapshot(scope).lots.first?.active, true)
    }
}

@MainActor final class ManagedBankExecutionTests: XCTestCase {
    private func fixture() throws -> (URL, AccountIDBank, AlpacaREST, URLSession, BankHTTPFixture) {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        let fixture = BankHTTPFixture(); let key = UUID().uuidString
        BankFixtureProtocol.register(fixture, key: key)
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [BankFixtureProtocol.self]
        let session = URLSession(configuration: config)
        let api = AlpacaREST(environment: .paper, credentials: AlpacaCredentials(key: key, secret: "synthetic"), session: session)
        let bank = try AccountIDBank(file: folder.appendingPathComponent("bank.json"))
        try bank.enable(BankScope(account: "synthetic", environment: .paper), cash: 1000, equity: 1000, positions: [:])
        return (folder, bank, api, session, fixture)
    }
    private func controller(_ folder: URL, bank: AccountIDBank, api: AlpacaREST, session: URLSession, state supplied: IntentState? = nil) throws -> IntentController {
        let pair = IntentPairing(url: URL(string: "https://synthetic.invalid/intent")!, token: String(repeating: "x", count: 32), environment: .paper, role: "host")
        let file = folder.appendingPathComponent("intent.json")
        let newCommand = supplied == nil && !FileManager.default.fileExists(atPath: file.path)
        if let supplied { try JSONEncoder().encode(supplied).write(to: file) }
        else if newCommand {
            var state = IntentState(); state.accountID = "synthetic"; state.pairingID = pair.fingerprint
            try JSONEncoder().encode(state).write(to: file)
        }
        let controller = try IntentController(file: file, session: session)
        try controller.installAccountBank(bank, route: "alice")
        try bank.register(BankScope(account: "synthetic", environment: .paper), route: "alice", journal: file, pairing: pair.fingerprint)
        try controller.connect(api: api, account: "synthetic", pairing: pair, startWorkers: false)
        if newCommand { _ = try controller.host(symbol: "AAPL", asset: "stock", quantity: 2, price: "10") }
        return controller
    }
    func testStockUsesCommonCashAndOptionCapDebitsTheSameLedger() async throws {
        let (folder, bank, api, session, fixture) = try fixture()
        let scope = BankScope(account: "synthetic", environment: .paper)
        fixture.optionsPower = "0"
        try bank.configure(scope, route: "alice", asset: "stock", mode: "units", value: "10", fee: "0")
        try bank.configure(scope, route: "alice", asset: "option", mode: "units", value: "10", fee: "0")
        let controller = try controller(folder, bank: bank, api: api, session: session)
        await controller.process()
        XCTAssertEqual(fixture.posts, 1, controller.message)
        XCTAssertEqual(try bank.snapshot(scope).available, 980)
        let zeroOptions = try ManagedAccountBank.funds(await api.account())
        XCTAssertEqual(zeroOptions.cash, 1000); XCTAssertEqual(zeroOptions.optionsCash, 0)
        func reserveOption(event: String, quantity: Int, funds: ManagedAccountBank.Funds) throws {
            let cid = AccountIDBank.clientID(scope, route: "alice", trade: event, event: event, sell: false, ordinal: 0)
            try bank.reserve(scope, route: "alice", trade: event, event: event, cid: cid, symbol: "SPY270115C00600000", asset: "option", multiplier: 100, sell: false, quantity: quantity, price: "1", ordinal: 0, cash: funds.admissionCash(asset: "option"), equity: funds.equity)
        }
        XCTAssertThrowsError(try reserveOption(event: "zero-options", quantity: 1, funds: zeroOptions))
        fixture.optionsPower = "100"
        let limited = try ManagedAccountBank.funds(await api.account())
        XCTAssertEqual(limited.cash, 1000); XCTAssertEqual(limited.optionsCash, 100)
        XCTAssertThrowsError(try reserveOption(event: "over-options", quantity: 2, funds: limited))
        try reserveOption(event: "one-option", quantity: 1, funds: limited)
        XCTAssertEqual(try bank.snapshot(scope).available, 880, "Options debit the common ledger; its balance is not replaced by the options cap")
        var account = try await api.account(); account.options_buying_power = nil
        let missing = try ManagedAccountBank.funds(account)
        XCTAssertEqual(try missing.admissionCash(asset: "stock"), 1000)
        XCTAssertThrowsError(try missing.admissionCash(asset: "option"))
        account.options_buying_power = "invalid"
        XCTAssertThrowsError(try ManagedAccountBank.funds(account).admissionCash(asset: "option"))
        controller.disconnect(); await controller.drainStoppedWork()
    }
    func testActualIntentDispatchReservesBeforePostAndTimeoutNeverRepeatsAfterRestart() async throws {
        let (folder, bank, api, session, fixture) = try fixture()
        let scope = BankScope(account: "synthetic", environment: .paper)
        try bank.configure(scope, route: "alice", asset: "stock", mode: "units", value: "10", fee: "0")
        fixture.timeoutPost = true
        let first = try controller(folder, bank: bank, api: api, session: session)
        await first.process()
        XCTAssertEqual(fixture.posts, 1)
        let row = try XCTUnwrap(bank.snapshot(scope).orders.first)
        XCTAssertTrue(row.dispatchStarted); XCTAssertEqual(row.status, "unknown")
        XCTAssertEqual(try bank.snapshot(scope).available, 980)
        first.disconnect(); await first.drainStoppedWork()
        let restored = try controller(folder, bank: bank, api: api.freshClient(customer: nil), session: session)
        await restored.process()
        XCTAssertEqual(fixture.posts, 1)
        XCTAssertEqual(try bank.snapshot(scope).available, 980)
        restored.disconnect(); await restored.drainStoppedWork()
    }
    func testZeroPoolNoPostDoesNotPoisonFreshInstructionAfterPoolConfiguration() async throws {
        let (folder, bank, api, session, fixture) = try fixture()
        let scope = BankScope(account: "synthetic", environment: .paper)
        let first = try controller(folder, bank: bank, api: api, session: session)
        await first.process()
        XCTAssertEqual(fixture.posts, 0)
        XCTAssertTrue(try XCTUnwrap(first.state.trades.values.first?.mutations.first).notSubmitted == true)
        XCTAssertTrue(try bank.snapshot(scope).orders.isEmpty)
        var saved = first.state
        first.disconnect(); await first.drainStoppedWork()
        try bank.configure(scope, route: "alice", asset: "stock", mode: "units", value: "10", fee: "0")
        let e = IntentEvent.make(trade: UUID().uuidString.lowercased(), sequence: 1, action: "enter", environment: .paper, symbol: "AAPL", asset: "stock", quantity: 2, price: "10")
        var trade = IntentTrade(); trade.desired = e; trade.policySnapshot = .legacy(e); saved.trades[e.trade_id] = trade
        let second = try controller(folder, bank: bank, api: api.freshClient(customer: nil), session: session, state: saved)
        _ = try second.host(symbol: "AAPL", asset: "stock", quantity: 2, price: "10", tradeID: e.trade_id)
        await second.process()
        XCTAssertEqual(fixture.posts, 1, second.message)
        XCTAssertEqual(try bank.snapshot(scope).orders.count, 1)
        second.disconnect(); await second.drainStoppedWork()
    }
    func testFinishedExpiredZeroFillSourceArchivesAndCannotReopenItsID() async throws {
        let (folder, bank, api, session, fixture) = try fixture()
        let scope = BankScope(account: "synthetic", environment: .paper)
        try bank.configure(scope, route: "alice", asset: "stock", mode: "units", value: "10", fee: "0")
        fixture.postStatus = "expired"
        let controller = try controller(folder, bank: bank, api: api, session: session)
        await controller.process(); await controller.process()
        let lot = try XCTUnwrap(bank.snapshot(scope).lots.first)
        XCTAssertFalse(lot.active, controller.message); XCTAssertTrue(lot.invalid)
        XCTAssertEqual(fixture.posts, 1)
        XCTAssertTrue(controller.state.trades.values.first?.completed == controller.state.trades.values.first?.desired?.event_id)
        let replay = AccountIDBank.clientID(scope, route: "alice", trade: lot.trade, event: "reopen", sell: false, ordinal: 0)
        XCTAssertThrowsError(try bank.reserve(scope, route: "alice", trade: lot.trade, event: "reopen", cid: replay, symbol: "AAPL", asset: "stock", multiplier: 1, sell: false, quantity: 1, price: "10", ordinal: 0, cash: 1000, equity: 1000))
        controller.disconnect(); await controller.drainStoppedWork()
    }
    func testUndispatchedHostEntryCannotExecuteAfterFlatRepairAndReconnect() async throws {
        let (folder, bank, api, session, fixture) = try fixture()
        let scope = BankScope(account: "synthetic", environment: .paper)
        try bank.configure(scope, route: "alice", asset: "stock", mode: "units", value: "10", fee: "0")
        let first = try controller(folder, bank: bank, api: api, session: session)
        // Revoke synchronously before the host's scheduled processing task can run.
        try first.pauseEntriesForBankTransition()
        first.disconnect(); await first.drainStoppedWork()
        try await ManagedAccountBank(bank: bank, scope: scope, route: "alice").check(api: api.freshClient(customer: nil), repair: true)
        let restored = try controller(folder, bank: bank, api: api.freshClient(customer: nil), session: session)
        await restored.process()
        XCTAssertEqual(fixture.posts, 0, restored.message)
        XCTAssertTrue(restored.state.preferences.paused)
        // A new deliberate host command is permitted despite follower pause.
        _ = try restored.host(symbol: "AAPL", asset: "stock", quantity: 2, price: "10")
        await restored.process()
        XCTAssertEqual(fixture.posts, 1, restored.message)
        restored.disconnect(); await restored.drainStoppedWork()
    }

    func testStaleManualCancellationCannotHideHoldingsDuringBankAdmission() async throws {
        let (folder, _, api, _, fixture) = try fixture()
        let file = folder.appendingPathComponent("manual.json")
        let journal = try AlpacaJournal(file: file)
        let ticket = AlpacaTicket(id: "manual-client", environment: .paper, accountID: "synthetic", symbol: "AAPL", quantity: 2, limitPrice: 10, side: "buy", positionIntent: nil, multiplier: 1, reviewedAt: Date())
        try await journal.begin(ticket)
        let partial = AlpacaOrder(id: "manual-broker", client_order_id: ticket.id, symbol: "AAPL", status: "partially_filled", qty: "2", limit_price: "10", filled_qty: "2", filled_avg_price: "10", side: "buy")
        try await journal.record(partial, ticket: ticket)
        fixture.legacyProof = AlpacaOrder(id: partial.id, client_order_id: ticket.id, symbol: "AAPL", status: "canceled", qty: "2", limit_price: "10", filled_qty: "0", filled_avg_price: nil, side: "buy")
        let retained = try Data(contentsOf: file)
        let controller = try IntentController(file: folder.appendingPathComponent("manual-intent.json"))
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let workspace = AlpacaWorkspace(journal: journal, intentController: controller, defaults: defaults,
            webhook: { nil }, loadIntentPairing: { nil }, makeClient: { _, _ in api },
            loadCredentials: { _ in AlpacaCredentials(key: "synthetic", secret: "synthetic") }, loadCustomer: { nil })
        workspace.selectPurpose(.trade)
        await workspace.connect(key: "", secret: "") // Actual refresh path must reject before overwriting journal.
        XCTAssertTrue(workspace.message.contains("regressed"), workspace.message)
        XCTAssertEqual(try Data(contentsOf: file), retained)
        do { try await ManagedAccountBank.verifyManual(file, api: api, scope: BankScope(account: "synthetic", environment: .paper)); XCTFail("Stale zero fill hid Crier holdings") } catch {}
        XCTAssertEqual(try Data(contentsOf: file), retained)
        XCTAssertEqual(fixture.posts, 0)
    }

    func testLegacyOpenLotRefusesAdmissionWithoutChangingJournal() async throws {
        let (folder, bank, api, session, fixture) = try fixture()
        let controller = try controller(folder, bank: bank, api: api, session: session)
        controller.disconnect(); await controller.drainStoppedWork()
        var saved = controller.state; let id = try XCTUnwrap(saved.trades.keys.first)
        let event = try XCTUnwrap(saved.trades[id]?.desired)
        let proof = AlpacaOrder(id: "old", client_order_id: "si-old", symbol: "AAPL", status: "filled", qty: "2.0", limit_price: "10", filled_qty: "2.0", filled_avg_price: "10", side: "buy")
        saved.trades[id]?.mutations = [IntentMutation(clientID: "si-old", eventID: event.event_id, sell: false, quantity: 2, order: proof)]
        let data = try JSONEncoder().encode(saved); try data.write(to: controller.journalFile)
        fixture.legacyProof = proof
        do { try await ManagedAccountBank.verifyJournal(controller.journalFile, api: api.freshClient(customer: nil), scope: BankScope(account: "synthetic", environment: .paper), bank: nil, route: "alice"); XCTFail("Open legacy ownership admitted") } catch {}
        XCTAssertEqual(try Data(contentsOf: controller.journalFile), data)
        XCTAssertEqual(fixture.posts, 0)
    }
}

private final class BankHTTPFixture {
    private let lock = NSLock()
    private var postCount = 0
    var timeoutPost = false
    var legacyProof: AlpacaOrder?
    var postStatus = "new"
    var optionsPower = "1000"
    private var postProof: AlpacaOrder?
    var posts: Int { lock.lock(); defer { lock.unlock() }; return postCount }
    func respond(_ request: URLRequest) throws -> (Int, Data) {
        lock.lock(); defer { lock.unlock() }
        let path = request.url!.path
        if request.httpMethod == "POST", path == "/v2/orders" {
            postCount += 1
            if timeoutPost { throw URLError(.timedOut) }
            var body = request.httpBody ?? Data()
            if body.isEmpty, let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; body.append(buffer, count: count) }
            }
            let parsed = try XCTUnwrap(try JSONSerialization.jsonObject(with: body) as? [String: String])
            let proof = AlpacaOrder(id: "synthetic-order", client_order_id: parsed["client_order_id"]!, symbol: parsed["symbol"]!, status: postStatus, qty: parsed["qty"], limit_price: parsed["limit_price"], filled_qty: "0", filled_avg_price: nil, side: parsed["side"]!)
            postProof = proof
            return (200, try JSONEncoder().encode(proof))
        }
        if path == "/v2/account" {
            let account: [String: Any] = ["id": "synthetic", "status": "ACTIVE", "buying_power": "4000", "cash": "1000", "equity": "1000", "non_marginable_buying_power": "1000", "options_buying_power": optionsPower, "currency": "USD", "trading_blocked": false, "account_blocked": false]
            return (200, try JSONSerialization.data(withJSONObject: account))
        }
        if path == "/v2/positions" { return (200, Data("[]".utf8)) }
        if path == "/v2/assets/AAPL" { return (200, Data(#"{"id":"stock-aapl","symbol":"AAPL","status":"active","tradable":true,"class":"us_equity","currency":"USD"}"#.utf8)) }
        if path == "/v2/orders:by_client_order_id" {
            if let legacyProof { return (200, try JSONEncoder().encode(legacyProof)) }
            if let postProof { return (200, try JSONEncoder().encode(postProof)) }
            return (404, Data("{}".utf8))
        }
        // Relay telemetry is intercepted too. This fixture never contacts a network.
        return (200, Data("{}".utf8))
    }
}
private final class BankFixtureProtocol: URLProtocol {
    private static let lock = NSLock(); private static var fixtures: [String: BankHTTPFixture] = [:]
    static func register(_ fixture: BankHTTPFixture, key: String) { lock.lock(); defer { lock.unlock() }; fixtures[key] = fixture }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let fixture = Self.fixtures[request.value(forHTTPHeaderField: "APCA-API-KEY-ID") ?? ""]; Self.lock.unlock()
        do {
            let response = try fixture?.respond(request) ?? (200, Data("{}".utf8))
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: response.0, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: response.1); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
