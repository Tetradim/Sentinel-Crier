import Foundation
import SwiftUI

@MainActor final class IntentController: ObservableObject {
    @Published private(set) var state: IntentState
    @Published private(set) var message = "Intent mirroring disconnected."
    @Published private(set) var copyDashboard: CopyDashboard?
    @Published private(set) var copyTransport = "connecting"
    private var copyJournal = CopyTelemetryJournal()
    private var copyReporter: Task<Void, Never>?
    private var copyReportingEnabled = false
    private var reporting = false; private var reportPending = false
    private var processPending = false
    private var copyGeneration = UUID()
    private var brokerObserved: [String: String] = [:]
    private var copyBindings: [String: IntentPolicyBinding] = [:]
    private var copyMetadataTasks: [String: Task<Void, Never>] = [:]
    private var copyMetadataRecovery = CopyMetadataRecovery()
    private var copyFile: URL { file.appendingPathExtension("reports") }
    var onHealth: NativeHealthObserver?
    private let file: URL
    var executionAdmission: () -> Bool = { true }
    // Manual host permission belongs to a deliberate command in the current session.
    // Follower pause is a separate preference and cannot authorize a queued host event.
    private var entryAuthorization = IntentEntryAuthorization()
    var accountBank: AccountIDBank?
    var bankRoute = "legacy"
    var journalFile: URL { file }
    func installAccountBank(_ bank: AccountIDBank?, route: String) throws {
        accountBank = bank; bankRoute = route
        if let bank, !state.accountID.isEmpty,
           try AlpacaEnvironment.allCases.contains(where: { try bank.enabled(BankScope(account: state.accountID, environment: $0)) }) {
            entryAuthorization.revokeHostCommands()
            try commit { $0.preferences.paused = true }
        }
    }
    func persistBankJournal() throws { try commit { _ in } }
    func pauseEntriesForBankTransition() throws { entryAuthorization.revokeHostCommands(); try commit { $0.preferences.paused = true } }
    private func managedBank(_ api: AlpacaREST) throws -> ManagedAccountBank? {
        let scope = BankScope(account: state.accountID, environment: api.environment)
        guard let bank = accountBank, try bank.enabled(scope) else { return nil }
        let registered = try bank.snapshot(scope).journals[bankRoute + "|" + file.path]
        guard registered == state.pairingID else { throw AlpacaError.invalid("Account bank admission required for this route and pairing.") }
        return ManagedAccountBank(bank: bank, scope: scope, route: bankRoute)
    }
    private let now: () -> Date
    private let monotonic: () -> TimeInterval
    private var entryClock: EntryClock
    private let session: URLSession
    private var api: AlpacaREST?; private var pair: IntentPairing?
    private var receiver: Task<Void, Never>?; private var worker: Task<Void, Never>?; private var transmitter: Task<Void, Never>?
    private var diagnosticWorker: Task<Void, Never>?
    private var diagnosticClock: DiagnosticClock?
    private var diagnosticSession = UUID()
    private var quoteCaptures = Set<String>()
    private var processing = false; private var publishing = false
    private var timerSession = UUID().uuidString
    init(file: URL, now: @escaping () -> Date = Date.init, monotonic: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }, session: URLSession = CrierHTTPSession.shared) throws {
        self.file = file
        self.now = now
        self.monotonic = monotonic; entryClock = EntryClock(wall: now, mono: monotonic)
        self.session = session
        state = FileManager.default.fileExists(atPath: file.path) ? try JSONDecoder().decode(IntentState.self, from: Data(contentsOf: file)) : IntentState()
        if state.policySchema == nil {
            guard state.trades.values.allSatisfy({ $0.policySnapshot == nil && $0.policyBinding == nil && $0.entryPlans == nil && $0.entryClosed == nil }) else { throw AlpacaError.invalid("Policy evidence without migration marker; preserve journal.") }
            // Only pre-schema journals are migrated. Current missing records fail closed.
            for id in state.trades.keys {
                if let event = state.trades[id]?.desired { state.trades[id]?.policySnapshot = .legacy(event) }
            }
            state.policySchema = 1
            try JSONEncoder().encode(state).write(to: file, options: [.atomic, .completeFileProtection])
        }
        guard state.policySchema == 1 else { throw AlpacaError.invalid("Unsupported policy journal schema.") }
        try state.validateJournal()
        if state.upgradeDiagnosticProvenHTTPRefusals() {
            try JSONEncoder().encode(state).write(to: file, options: [.atomic, .completeFileProtection])
        }
    }
    static func local() throws -> IntentController {
        let folder = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("SentinelCrier")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return try IntentController(file: folder.appendingPathComponent("intent-v1.json"))
    }
    private func commit(_ change: (inout IntentState) throws -> Void) throws {
        var next = state; try change(&next)
        try next.validateJournal()
        try JSONEncoder().encode(next).write(to: file, options: [.atomic, .completeFileProtection])
        state = next
        if connected { enqueueWork { [self] in await reportCopyStatus() } }
    }
    func settings(_ p: IntentPreferences) throws {
        _ = try p.price("1", sell: false); try p.execution_policy?.validate(market: p.mode == "market")
        guard p.execution_policy == state.preferences.execution_policy || p.paused else { throw AlpacaError.invalid("Policy changes must leave follower entries paused. Save paused, then explicitly resume.") }
        try commit { $0.preferences = p }
    }
    func validateIdentity(account: String, environment: AlpacaEnvironment, pairing: IntentPairing? = nil) throws {
        guard let pair = try pairing ?? IntentPairing.load() else { return }
        guard pair.environment == environment else { throw AlpacaError.invalid("Pairing environment differs from broker.") }
        guard state.accountID.isEmpty || (state.accountID == account && state.pairingID == pair.fingerprint) else { throw AlpacaError.invalid("Intent journal is pinned to its original account and pairing. Recover its trades before changing channels.") }
    }
    func connect(api: AlpacaREST, account: String, pairing: IntentPairing? = nil, startWorkers: Bool = true) throws {
        guard executionAdmission() else { throw AlpacaError.invalid("Account bank transition is running; reconnect afterward.") }
        guard let pair = try pairing ?? IntentPairing.load() else { return }
        try validateIdentity(account: account, environment: api.environment, pairing: pair)
        try commit { $0.accountID = account; $0.pairingID = pair.fingerprint; $0.pairingRole = pair.role }
        entryAuthorization.revokeHostCommands()
        timerSession = UUID().uuidString
        if self.api !== api { self.api?.invalidate() }
        self.api = api; self.pair = pair
        entryClock = EntryClock(wall: now, mono: monotonic)
        diagnosticClock = nil
        diagnosticSession = UUID()
        receiver?.cancel(); worker?.cancel(); transmitter?.cancel()
        diagnosticWorker?.cancel()
        copyReportingEnabled = startWorkers
        copyGeneration = UUID(); copyDashboard = nil; copyTransport = "connecting"
        copyReporter?.cancel()
        for task in copyMetadataTasks.values { task.cancel() }; copyMetadataTasks = [:]; copyMetadataRecovery.reset(); copyBindings = [:]; brokerObserved = [:]
        copyJournal = (try? JSONDecoder().decode(CopyTelemetryJournal.self, from: Data(contentsOf: copyFile))) ?? CopyTelemetryJournal()
        if copyJournal.pair != pair.fingerprint { copyJournal = CopyTelemetryJournal(pair: pair.fingerprint) }
        guard startWorkers else { return }
        receiver = Task { await receiveLoop() }
        copyReporter = Task { while !Task.isCancelled { await reportCopyStatus(presence: true); try? await Task.sleep(nanoseconds: 15_000_000_000) } }
        transmitter = Task { while !Task.isCancelled { await publish(); try? await Task.sleep(nanoseconds: 500_000_000) } }
        worker = Task { while !Task.isCancelled { await process(); try? await Task.sleep(nanoseconds: 2_000_000_000) } }
        diagnosticWorker?.cancel()
        diagnosticWorker = Task { while !Task.isCancelled { await syncDiagnostics(); try? await Task.sleep(nanoseconds: 5_000_000_000) } }
        message = "\(pair.role.capitalized) connected. Keep Crier open for delivery."
    }
    private var stoppedTasks: [Task<Void, Never>] = []
    private var oneShotJobs: [UUID: Task<Void, Never>] = [:]
    /// Keep every spawned job under the same shutdown barrier as loop workers.
    func enqueueWork(_ operation: @escaping @MainActor () async -> Void) {
        let id = UUID()
        oneShotJobs[id] = Task {
            defer { oneShotJobs.removeValue(forKey: id) }
            guard !Task.isCancelled else { return }
            await operation()
        }
    }
    func drainStoppedWork() async {
        while !stoppedTasks.isEmpty || !oneShotJobs.isEmpty || processing || publishing || reporting {
            let tasks = stoppedTasks + Array(oneShotJobs.values); stoppedTasks = []
            for task in tasks { await task.value }
            // Also wait for callers that directly awaited process/publish rather
            // than entering through a scheduled worker or one-shot job.
            if processing || publishing || reporting { await Task.yield() }
        }
    }
    func disconnect() {
        entryAuthorization.revokeHostCommands()
        for task in oneShotJobs.values { task.cancel() }
        stoppedTasks += Array(oneShotJobs.values)
        stoppedTasks += [copyReporter, diagnosticWorker, receiver, worker, transmitter].compactMap { $0 }
        stoppedTasks += Array(copyMetadataTasks.values)
        copyReportingEnabled = false; copyGeneration = UUID(); copyReporter?.cancel(); copyReporter = nil; for task in copyMetadataTasks.values { task.cancel() }; copyMetadataTasks = [:]; copyMetadataRecovery.reset(); copyBindings = [:]; brokerObserved = [:]; copyDashboard = nil; copyTransport = "connecting"; processPending = false; message = "Disconnected; execution journals retained."; diagnosticSession = UUID(); diagnosticWorker?.cancel(); diagnosticWorker = nil; diagnosticClock = nil; receiver?.cancel(); worker?.cancel(); transmitter?.cancel(); receiver = nil; worker = nil; transmitter = nil; api?.invalidate(); api = nil; pair = nil }
    func archiveResolvedChannel() throws {
        guard !processing, !publishing, api == nil else { throw AlpacaError.invalid("Disconnect before changing channel.") }
        guard state.unresolved.isEmpty, state.outgoing.isEmpty else { throw AlpacaError.invalid("Resolve tracked holdings, pending orders and relay outbox before changing channel. Reconnect to the original account to recover.") }
        let archive = file.deletingLastPathComponent().appendingPathComponent("intent-archive-" + UUID().uuidString + ".json")
        try JSONEncoder().encode(state).write(to: archive, options: [.atomic, .completeFileProtection])
        try commit { $0 = IntentState() }
        UserDefaults.standard.removeObject(forKey: "intent-pairing-metadata")
    }
    var hosting: Bool { pair?.role == "host" }
    var connected: Bool { api != nil && pair != nil }
    func host(symbol: String, asset: String, quantity: Int, price: String, tradeID: String? = nil, action: String = "enter") throws -> String {
        guard executionAdmission(), let pair, hosting else { throw AlpacaError.invalid("Connect an intent host pairing after account bank setup finishes.") }
        let id = tradeID ?? UUID().uuidString.lowercased()
        let e = IntentEvent.make(trade: id, sequence: (state.trades[id]?.desired?.sequence ?? 0) + 1, action: action, environment: pair.environment, symbol: symbol, asset: asset, quantity: quantity, price: price)
        try commit { s in var t = s.trades[id] ?? IntentTrade(); if t.policySnapshot == nil { t.policySnapshot = .legacy(e) }; try t.accept(e); s.trades[id] = t; s.outgoing.append(e) }
        entryAuthorization.allowHostCommand(e.event_id)
        beginDiagnostic(e, stage: "sender", observed: IntentEvent.date(e.created_at) ?? Date())
        enqueueWork { [self] in await publish() }; enqueueWork { [self] in await process() }
        return id
    }
    private func relay(_ query: String = "", body: Data? = nil, resource: String = "events") async throws -> Data {
        guard let pair else { throw AlpacaError.invalid("Disconnected.") }
        let generation = copyGeneration
        let (data, response) = try await IntentTransport(session: session).request(pair: pair, query: query, body: body, resource: resource)
        guard generation == copyGeneration, self.pair?.fingerprint == pair.fingerprint, !Task.isCancelled else { throw CancellationError() }
        if [401, 403].contains(response.statusCode) {
            disconnect()
            message = "Relay authentication failed or receiver revoked. Reconnect with valid credentials; journal retained."
            throw AlpacaError.invalid(message)
        }
        guard (200..<300).contains(response.statusCode) else { throw AlpacaError.http(response.statusCode) }
        return data
    }
    func publish() async {
        guard hosting, !publishing else { return }; publishing = true; defer { publishing = false }
        let observed = onHealth
        if state.outgoing.isEmpty { observed?(.relaySend, .idle, .noWork) }
        do {
            while !Task.isCancelled {
                if !state.outgoing.isEmpty { try commit { $0.discardSupersededEntries() } }
                guard let e = state.outgoing.first(where: { ["cancel", "exit"].contains($0.action) }) ?? state.outgoing.first else { break }
                do {
                    _ = try await relay(body: JSONEncoder().encode(e))
                    diagnosticStep(e.event_id, "relay_accepted", "Relay durably accepted event")
                    try commit { $0.outgoing.removeAll { $0.event_id == e.event_id } }
                    observed?(.relaySend, .healthy, .delivered)
                } catch AlpacaError.http(let status) where [400, 409, 422].contains(status) {
                    let record = String(decoding: try JSONEncoder().encode(e), as: UTF8.self)
                    try commit {
                        if $0.quarantine == nil { $0.quarantine = [] }
                        $0.quarantine?.append(IntentState.Quarantine(cursor: 0, reason: "Relay rejected outgoing event HTTP \(status)", record: record))
                        $0.outgoing.removeAll { $0.event_id == e.event_id }
                    }
                    diagnosticStep(e.event_id, "relay_rejected", "HTTP \(status); original revision retained in quarantine")
                    if ["enter", "replace"].contains(e.action), state.trades[e.trade_id]?.desired?.event_id == e.event_id {
                        _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: e.trade_id, action: "cancel")
                    }
                    message = "Relay rejected a revision; inspect quarantine and reconcile the tracked trade."
                    observed?(.relaySend, .blocked, .rejected)
                }
            }
        }
        catch { observed?(.relaySend, .degraded, .connectionFailed); message = "Intent outbox pending: \(error.localizedDescription)" }
    }
    func receiveOnce() async throws {
        let observed = onHealth; let previousQuarantine = state.quarantine?.count ?? 0
        let data = try await relay("?after=\(state.cursor)&wait=20")
        try Task.checkCancellation()
        guard let environment = pair?.environment else { return }
        var accepted: [IntentEvent] = []
        try commit { accepted = try $0.ingestPage(data, environment: environment) }
        for event in accepted { beginDiagnostic(event, stage: "receiver", observed: Date()) }
        let invalid = (state.quarantine?.count ?? 0) > previousQuarantine
        observed?(.relayReceive, invalid ? .degraded : .healthy, invalid ? .invalidEvents : .checked)
        message = "Receiver connected • cursor \(state.cursor) • \(state.quarantine?.count ?? 0) quarantined"
    }
    private func receiveLoop() async {
        let generation = copyGeneration
        while !Task.isCancelled, generation == copyGeneration, let pair {
            do { try await receiveStream(pair: pair, generation: generation) }
            catch {
                guard !Task.isCancelled, generation == copyGeneration else { return }
                copyTransport = "poll"
                // Bounded long polling is the recovery transport. Retry streaming after
                // a completed durable catch-up, never on a normal push timer.
                do {
                    if pair.role == "follower" { try await receiveOnce(); await process() }
                    else { try? await Task.sleep(nanoseconds: 2_000_000_000) }
                    let data = try await relay(resource: "dashboard")
                    let snapshot = try JSONDecoder().decode(CopyDashboard.self, from: data)
                    try snapshot.validate(pair: pair)
                    guard generation == copyGeneration else { return }; copyDashboard = snapshot
                } catch {
                    guard !Task.isCancelled, generation == copyGeneration else { return }
                    onHealth?(.relayReceive, .degraded, .connectionFailed)
                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                }
            }
        }
    }
    private func receiveStream(pair: IntentPairing, generation: UUID) async throws {
        var request = URLRequest(url: pair.url.appendingPathComponent("api/sync/stream"))
        var url = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!
        url.queryItems = [URLQueryItem(name: "after", value: String(state.cursor))]; request.url = url.url
        request.setValue("Bearer " + pair.token, forHTTPHeaderField: "Authorization")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept"); request.timeoutInterval = 100
        let (bytes, response) = try await session.bytes(for: request)
        guard generation == copyGeneration, !Task.isCancelled else { throw CancellationError() }
        guard let http = response as? HTTPURLResponse else { throw AlpacaError.invalid("Invalid stream response.") }
        if [401,403].contains(http.statusCode) { disconnect(); throw AlpacaError.http(http.statusCode) }
        guard http.statusCode == 200, http.value(forHTTPHeaderField: "Content-Type")?.lowercased().hasPrefix("text/event-stream") == true else { throw AlpacaError.invalid("Stream unavailable.") }
        var parser = CopySSEParser()
        for try await byte in bytes {
            guard generation == copyGeneration, !Task.isCancelled else { throw CancellationError() }
            if let frame = try parser.append(byte) { try acceptCopyFrame(frame, pair: pair) }
        }
        throw AlpacaError.invalid("Stream rotated or disconnected.")
    }
    func acceptCopyFrame(_ frame: CopySSEParser.Frame, pair: IntentPairing) throws {
        guard self.pair?.fingerprint == pair.fingerprint, connected else { throw CancellationError() }
        switch frame.name {
        case "ready":
            struct Ready: Decodable { var version: Int; var transport: String }
            let ready = try JSONDecoder().decode(Ready.self, from: frame.data)
            guard ready.version == 1, ready.transport == "push" else { throw AlpacaError.invalid("Invalid stream ready.") }
            copyTransport = "push"; enqueueWork { [self] in await reportCopyStatus(presence: true) }
        case "events":
            // A host observes the channel but never ingests remote execution intents.
            guard pair.role == "follower" else { return }
            var accepted: [IntentEvent] = []
            try commit { accepted = try $0.ingestPage(frame.data, environment: pair.environment) }
            for event in accepted { beginDiagnostic(event, stage: "receiver", observed: Date()) }
            if !accepted.isEmpty { enqueueWork { [self] in await process() } }
            onHealth?(.relayReceive, .healthy, .checked)
        case "dashboard":
            let snapshot = try JSONDecoder().decode(CopyDashboard.self, from: frame.data)
            try snapshot.validate(pair: pair); copyDashboard = snapshot
        case "heartbeat":
            struct Heartbeat: Decodable { var server_time_ms: Double }
            let value = try JSONDecoder().decode(Heartbeat.self, from: frame.data)
            guard value.server_time_ms.isFinite else { throw AlpacaError.invalid("Invalid heartbeat.") }
        default: break
        }
    }
    func reconcileBeforeResume() async throws { try await execution().reconcileBeforeResume(observe: onHealth) }

    /// The execution module reads current identity on every fence and writes only
    /// through this controller's atomic validated journal transaction.
    private func execution() -> IntentExecution {
        let generation = copyGeneration
        let activeAPI = api
        let pairing = pair?.fingerprint
        return IntentExecution(access: IntentExecutionAccess(
            snapshot: { self.state }, commit: { change in
                guard generation == self.copyGeneration, activeAPI != nil, self.api === activeAPI,
                      pairing != nil, self.pair?.fingerprint == pairing, !Task.isCancelled else { throw CancellationError() }
                try self.commit(change)
            },
            api: { self.api }, pair: { self.pair }, bankRoute: bankRoute,
            managedBank: { try self.managedBank($0) }, admission: { self.executionAdmission() },
            entryAllowed: { self.entryAuthorization.allows(eventID: $0, hosting: self.hosting, followerPaused: self.state.preferences.paused) },
            clock: { self.entryClock.read() }, now: now, monotonic: monotonic, timerSession: { self.timerSession },
            diagnostic: { self.diagnosticStep($0, $1, $2, at: $3) },
            brokerObserved: { self.brokerObserved[$0] = $1 },
            message: { self.message = $0 },
            host: { try self.host(symbol: $0, asset: $1, quantity: $2, price: $3, tradeID: $4, action: $5) },
            enqueue: { self.enqueueWork($0) }))
    }

    func process() async {
        if processing { processPending = true; return }
        guard let api else { return }; processing = true
        let generation = copyGeneration
        defer {
            processing = false
            if processPending, generation == copyGeneration, connected {
                processPending = false; enqueueWork { [self] in await process() }
            }
        }
        let observed = onHealth; var needsReconciliation = false
        for id in Array(state.trades.keys) {
            do { try Task.checkCancellation(); try await execution().execute(id, api: api, observe: observed) }
            catch { needsReconciliation = true; if let event = state.trades[id]?.desired {
                diagnosticStep(event.event_id, "execution_pending", error.localizedDescription)
                if state.trades[id]?.policySnapshot?.policy != nil {
                    try? commit { if $0.trades[id]!.policyRefusals == nil { $0.trades[id]!.policyRefusals = [:] }; $0.trades[id]!.policyRefusals![event.event_id] = error.localizedDescription }
                }
            }; message = "Trade \(id.prefix(8)): \(error.localizedDescription)" }
        }
        needsReconciliation = needsReconciliation || state.trades.values.contains { $0.mutations.contains { $0.notSubmitted != true && ($0.order == nil || $0.cancelUnknown) } }
        observed?(.execution, needsReconciliation ? .blocked : .healthy, needsReconciliation ? .reconciliationRequired : .checked)
    }
    private func diagnosticStep(_ eventID: String, _ stage: String, _ detail: String, at: Date = Date()) {
        try? commit { state in
            guard var record = state.diagnostics?[eventID] else { return }
            if record.timeline.last?.stage == stage && record.timeline.last?.detail == detail { return }
            record.timeline.append(DiagnosticStep(at: IntentDiagnosticRecord.timestamp(at), stage: stage, detail: detail))
            state.diagnostics?[eventID] = record
        }
    }
    private func beginDiagnostic(_ event: IntentEvent, stage: String, observed: Date) {
        guard state.diagnostics?[event.event_id] == nil else { return }
        let clock = diagnosticClock.flatMap { $0.fresh(at: observed) ? $0 : nil }
        let observation = DiagnosticObservation(stage: stage, observed_at: IntentDiagnosticRecord.timestamp(observed), clock_offset_ms: clock?.offset, clock_uncertainty_ms: clock?.uncertainty, clock_sampled_at: clock.map { IntentDiagnosticRecord.timestamp($0.sampled) })
        try? commit { state in
            if state.diagnostics == nil { state.diagnostics = [:] }
            state.diagnostics?[event.event_id] = IntentDiagnosticRecord(event: event, observation: observation, timeline: [DiagnosticStep(at: observation.observed_at, stage: stage == "sender" ? "journaled" : "received", detail: "Exact event revision persisted")])
        }
        guard let api else { return }
        guard quoteCaptures.count < 8 else {
            try? commit { $0.diagnostics?[event.event_id]?.observation.quote_error = "Quote capture capacity reached"; $0.diagnostics?[event.event_id]?.quoteComplete = true }
            return
        }
        quoteCaptures.insert(event.event_id)
        let session = diagnosticSession
        // Independent task: neither quote capture nor diagnostics gates broker dispatch.
        enqueueWork { [self] in
            defer { quoteCaptures.remove(event.event_id) }
            do {
                let quote = try await api.diagnosticQuote(symbol: event.symbol, option: event.asset == "option")
                guard self.api === api, self.pair != nil, diagnosticSession == session else { return }
                let finished = Date()
                let clock = diagnosticClock.flatMap { $0.fresh(at: finished) ? $0 : nil }
                let age = IntentEvent.date(quote.quote_timestamp).map { finished.addingTimeInterval((clock?.offset ?? 0) / 1000).timeIntervalSince($0) }
                let quoteError = clock == nil ? "Quote freshness unverified: clock unavailable" : ((age.map { (0...5).contains($0) } ?? false) ? nil : "Stale or future quote; excluded from comparison")
                try? commit {
                    guard $0.diagnostics?[event.event_id]?.quoteComplete == false else { return }
                    $0.diagnostics?[event.event_id]?.observation.quote = quote
                    $0.diagnostics?[event.event_id]?.observation.quote_error = quoteError
                    $0.diagnostics?[event.event_id]?.quoteComplete = true
                }
            } catch {
                guard self.api === api, self.pair != nil, diagnosticSession == session else { return }
                try? commit {
                    guard $0.diagnostics?[event.event_id]?.quoteComplete == false else { return }
                    $0.diagnostics?[event.event_id]?.observation.quote_error = "Alpaca quote unavailable (permission, transport, or malformed response)"
                    $0.diagnostics?[event.event_id]?.quoteComplete = true
                }
            }
        }
    }
    private func syncDiagnostics() async {
        guard let activePair = pair else { return }
        let session = diagnosticSession
        if diagnosticClock?.fresh(at: Date()) != true {
            let start = Date(), uptime = ProcessInfo.processInfo.systemUptime
            struct ClockResponse: Decodable { var server_time_ms: Double }
            if let data = try? await relay(resource: "clock"), let response = try? JSONDecoder().decode(ClockResponse.self, from: data) {
                guard !Task.isCancelled, diagnosticSession == session, pair?.fingerprint == activePair.fingerprint else { return }
                diagnosticClock = DiagnosticClock.make(start: start, end: Date(), elapsed: ProcessInfo.processInfo.systemUptime - uptime, server: response.server_time_ms)
            }
        }
        let pending = (state.diagnostics ?? [:]).values.filter { !$0.quoteComplete || (!$0.uploaded && $0.attempts < 6) || $0.fetchAttempts < 12 }
            .sorted { $0.event.created_at < $1.event.created_at }.prefix(20)
        for id in pending.map({ $0.event.event_id }) {
            guard !Task.isCancelled, diagnosticSession == session, pair?.fingerprint == activePair.fingerprint, let record = state.diagnostics?[id] else { return }
            guard !state.outgoing.contains(where: { $0.event_id == id }) else { continue }
            // Wait for capture; after restart a missing capture becomes explicit unavailable.
            if !record.quoteComplete {
                if Date().timeIntervalSince(IntentEvent.date(record.observation.observed_at) ?? Date()) > 20 {
                    try? commit { $0.diagnostics?[id]?.observation.quote_error = "Quote capture interrupted"; $0.diagnostics?[id]?.quoteComplete = true }
                }
                continue
            }
            if !record.uploaded && record.attempts < 6 {
                struct Upload: Encodable { var event_id: String; var observation: DiagnosticObservation }
                try? commit { $0.diagnostics?[id]?.attempts += 1 }
                do {
                    _ = try await relay(body: JSONEncoder().encode(Upload(event_id: id, observation: record.observation)), resource: "diagnostics")
                    guard !Task.isCancelled, diagnosticSession == session else { return }
                    try? commit { $0.diagnostics?[id]?.uploaded = true }
                } catch {
                    guard !Task.isCancelled, diagnosticSession == session else { return }
                    diagnosticStep(id, "diagnostics_pending", "Relay diagnostics upload pending")
                }
            }
            guard record.fetchAttempts < 12 else { continue }
            try? commit { $0.diagnostics?[id]?.fetchAttempts += 1 }
            struct Download: Decodable { var observations: [DiagnosticRemote] }
            if let data = try? await relay("?event_id=" + id, resource: "diagnostics"), let response = try? JSONDecoder().decode(Download.self, from: data) {
                guard !Task.isCancelled, diagnosticSession == session else { return }
                try? commit { $0.diagnostics?[id]?.remote = response.observations }
            }
        }
    }

}

// Observational transport has its own durable revisions and outbox. It cannot
// create trading events or call broker mutations.
extension IntentController {
    private func saveCopyJournal() throws {
        try JSONEncoder().encode(copyJournal).write(to: copyFile, options: [.atomic, .completeFileProtection])
    }
    private func reportCopyStatus(presence: Bool = false) async {
        if reporting { reportPending = true; return }
        guard copyReportingEnabled, let pair, let api else { return }
        reporting = true; let generation = copyGeneration
        defer { reporting = false; if reportPending, generation == copyGeneration { reportPending = false; enqueueWork { [self] in await reportCopyStatus(presence: true) } } }
        do {
            for (id, trade) in state.trades {
                guard let event = trade.desired else { continue }
                if trade.policyBinding == nil, copyBindings[id] == nil, copyMetadataTasks[id] == nil,
                   let attempt = copyMetadataRecovery.begin(tradeID: id, now: monotonic()) {
                    let accountID = state.accountID
                    copyMetadataTasks[id] = Task {
                        guard generation == copyGeneration, self.api === api, self.pair?.fingerprint == pair.fingerprint,
                              state.accountID == accountID, copyReportingEnabled, !Task.isCancelled else { return }
                        let binding = try? await api.policyBinding(symbol: event.symbol, option: event.asset == "option", accountID: accountID)
                        guard generation == copyGeneration, self.api === api, self.pair?.fingerprint == pair.fingerprint,
                              state.accountID == accountID, copyReportingEnabled, !Task.isCancelled else { return }
                        copyMetadataTasks.removeValue(forKey: id)
                        copyMetadataRecovery.finish(tradeID: id, attempt: attempt, succeeded: binding != nil, now: monotonic())
                        if let binding { copyBindings[id] = binding; await reportCopyStatus() }
                    }
                }
                var report = IntentTelemetry(accountID: state.accountID, hosting: hosting, paused: state.preferences.paused, binding: copyBindings[id], brokerObserved: brokerObserved[id], quote: state.diagnostics?[event.event_id]?.observation.quote).report(trade, event: event)
                let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
                let signature = String(decoding: try encoder.encode(report), as: UTF8.self)
                if copyJournal.signatures[id] != signature {
                    report.revision = try copyJournal.next(); report.observed_at = IntentDiagnosticRecord.timestamp()
                    try report.validate(asset: event.asset)
                    copyJournal.outbox[id] = report; copyJournal.signatures[id] = signature; try saveCopyJournal()
                }
            }
            // Presence remains independent of whether the relay accepts a report.
            // Retry a previously failed journal write before any later upload.
            try saveCopyJournal()
            if presence {
                let revision = try copyJournal.next(); try saveCopyJournal()
                let body = CopyPresence(revision: revision, observed_at: IntentDiagnosticRecord.timestamp(), transport: copyTransport, entries_enabled: hosting ? entryAuthorization.hasHostCommands : !state.preferences.paused)
                _ = try? await relay(body: JSONEncoder().encode(body), resource: "presence")
            }
            for (id, report) in copyJournal.outbox {
                guard generation == copyGeneration, !Task.isCancelled else { return }
                do {
                    _ = try await relay(body: JSONEncoder().encode(report), resource: "status")
                    guard generation == copyGeneration else { return }
                    if copyJournal.outbox[id]?.revision == report.revision { copyJournal.outbox.removeValue(forKey: id); try saveCopyJournal() }
                } catch { /* Retain the same revision for idempotent retry. */ }
            }
        } catch { /* Telemetry failure never quarantines or changes execution. */ }
    }
}
