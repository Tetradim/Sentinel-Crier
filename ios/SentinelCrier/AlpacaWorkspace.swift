import SwiftUI

@MainActor
final class AlpacaWorkspace: ObservableObject {
    @Published var environment: AlpacaEnvironment = .paper {
        didSet {
            guard oldValue != environment else { return }
            if account != nil { environment = oldValue; message = "Disconnect before changing environment."; return }
            readiness.invalidate(); scopeGeneration = UUID()
        }
    }
    @Published private(set) var purpose: GuidedPurpose?
    @Published private(set) var readiness = GuidedReadiness()
    let health: NativeHealth
    private var healthTicket: NativeHealth.Ticket?
    private var healthBaseScope = ""
    private var legacyHealth = false
    let defaults: UserDefaults
    let routeStorage: ConnectionRouteStorage?
    private let routeRegistry: ConnectionRouteRegistry?
    var legacyRoute: Bool { routeStorage?.route.legacy ?? true }
    func savedPairing() throws -> IntentPairing? { try loadIntentPairing() }
    func savePairing(_ pair: IntentPairing) throws {
        if let pinned = intent?.state.pairingID, !pinned.isEmpty, pinned != pair.fingerprint { throw AlpacaError.invalid("This journal is pinned to its original host. Add another connection.") }
        if let routeStorage { try routeStorage.save(pair) } else { try pair.save() }
        if legacyRoute { MirrorPairing.remove() }
    }
    private var effectPermit = OAuthEffectPermit()
    private var scopeGeneration = UUID() { didSet { effectPermit.invalidate(); effectPermit = OAuthEffectPermit(); if let healthTicket { health.stop(healthTicket) }; healthTicket = nil } }
    private var discordScope: String?
    private let testDiscord: () async throws -> String
    private let webhook: () -> URL?
    private let loadIntentPairing: () throws -> IntentPairing?
    private let deliverDiscord: ((AlpacaEnvironment, String) async throws -> Void)?
    private func publishFills(environment: AlpacaEnvironment, accountID: String) async throws {
        let observed = healthTicket; let ledger = health
        if let deliverDiscord { try await deliverDiscord(environment, accountID) }
        else { try await publisher?.deliver(environment: environment, accountID: accountID, permit: effectPermit, observe: { state, reason in
            if let observed { await ledger.record(observed, .discord, state, reason) }
        }) }
    }

    private func healthNote(_ ticket: NativeHealth.Ticket?, _ component: HealthComponent, _ state: HealthObservation, _ reason: HealthReason) {
        if let ticket { health.record(ticket, component, state, reason) }
    }
    private func healthActivity() -> Set<HealthComponent> {
        guard foreground, account != nil else { return [] }
        var active: Set<HealthComponent> = [.broker, .fills]
        if executionJourney, intent?.connected == true {
            active.insert(.execution); active.insert(intent?.hosting == true ? .relaySend : .relayReceive)
        } else if legacyHealth { active.insert(.relaySend) }
        if canDeliver { active.insert(.discord) }; return active
    }
    private func bindHealth() {
        guard foreground, account != nil, !healthBaseScope.isEmpty else { return }
        if let healthTicket { health.stop(healthTicket) }
        let ticket = health.begin(scope: NativeHealth.scope([healthBaseScope, destinationScope()]), active: healthActivity())
        healthTicket = ticket; let ledger = health
        intent?.onHealth = { [weak ledger] component, state, reason in ledger?.record(ticket, component, state, reason) }
    }
    private func updateHealthActivity() { if let healthTicket { health.setActive(healthTicket, healthActivity()) } }

    func selectPurpose(_ value: GuidedPurpose?) {
        guard !busy, account == nil else { return }
        purpose = value; defaults.set(value?.rawValue, forKey: "guidedPurpose")
        readiness.invalidate(); scopeGeneration = UUID()
    }
    private var executionJourney: Bool { purpose == .trade || purpose == .follow }
    private func destinationScope() -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let settings = (try? encoder.encode(DiscordAlertSettings.load(defaults))) ?? Data()
        return (webhook()?.absoluteString ?? "") + "|" + (defaults.string(forKey: "discordFillStyle") ?? "homebrew") + "|" + String(decoding: settings, as: UTF8.self)
    }
    func discordConfigurationChanged() {
        readiness.previewed = false; readiness.testResult = nil; readiness.deliveryEnabled = false
        discordScope = nil; scopeGeneration = UUID()
        bindHealth()
    }
    func previewDiscord() {
        guard readiness.verified, webhook() != nil else { message = "Connect and save a destination first."; return }
        discordScope = destinationScope(); readiness.previewed = true
        readiness.testResult = nil; readiness.deliveryEnabled = false
        updateHealthActivity()
    }
    func sendDiscordTest() async {
        guard !busy, foreground, readiness.verified, readiness.previewed, discordScope == destinationScope() else { message = "Connect and preview the current destination first."; return }
        busy = true; readiness.testResult = nil
        let generation = scopeGeneration; let scope = destinationScope(); let observed = healthTicket
        defer { busy = false }
        do {
            let result = try await testDiscord()
            guard foreground, generation == scopeGeneration, scope == destinationScope() else { return }
            readiness.testResult = result; message = result
            healthNote(observed, .discord, .healthy, .delivered)
        } catch {
            guard generation == scopeGeneration, scope == destinationScope() else { return }
            readiness.testResult = "Test not confirmed. Check Discord before retrying; it may have arrived."
            message = readiness.testResult!
            healthNote(observed, .discord, .blocked, .uncertain)
        }
    }
    func enableDiscordDelivery(_ enabled: Bool) {
        guard enabled else { readiness.deliveryEnabled = false; updateHealthActivity(); return }
        guard foreground, readiness.verified, readiness.previewed, discordScope == destinationScope(), webhook() != nil else { message = "Connect and preview this destination before enabling delivery."; return }
        readiness.deliveryEnabled = true
        updateHealthActivity()
        message = "Fill delivery enabled for this account and destination while Crier stays active."
    }
    private var canDeliver: Bool {
        foreground && readiness.verified && readiness.deliveryEnabled && discordScope == destinationScope()
    }
    @Published private(set) var account: AlpacaAccount?
    @Published private(set) var positions: [AlpacaPosition] = []
    @Published private(set) var contracts: [AlpacaContract] = []
    @Published private(set) var submissions: [AlpacaJournal.Submission] = []
    @Published private(set) var recoverySnapshot: RecoveryBrokerSnapshot?
    @Published private(set) var deliveries: [AlpacaJournal.Delivery] = []
    @Published var review: AlpacaTicket?
    @Published private(set) var busy = false
    @Published private(set) var message = "Connect Alpaca paper to begin."
    @Published private(set) var updatedAt: Date?
    @Published private(set) var mirrorMessage = "Not paired."
    @Published private(set) var intent: IntentController?
    @Published private(set) var lifecycle = "Foreground • connect to resume"
    private var suspended = false
    private var foreground = true
    private var api: AlpacaREST?
    private var journal: AlpacaJournal?
    private var publisher: AlpacaDiscordDelivery?
    private var mirrorSender: MirrorSender?
    private let makeClient: (AlpacaEnvironment, AlpacaCredentials) -> AlpacaREST
    private let loadCustomer: () -> CustomerSession?
    private let loadCredentials: (AlpacaEnvironment) throws -> AlpacaCredentials
    private let saveCredentials: (AlpacaCredentials, AlpacaEnvironment) throws -> Void
    init(routeStorage: ConnectionRouteStorage? = nil, routeRegistry: ConnectionRouteRegistry? = nil, journal suppliedJournal: AlpacaJournal? = nil, intentController: IntentController? = nil,
         defaults: UserDefaults = .standard, health suppliedHealth: NativeHealth? = nil,
         testDiscord: @escaping () async throws -> String = { try await DiscordAlertSettings.test() },
         webhook: @escaping () -> URL? = StandaloneConfiguration.webhook,
         deliverDiscord: ((AlpacaEnvironment, String) async throws -> Void)? = nil,
         loadIntentPairing: @escaping () throws -> IntentPairing? = IntentPairing.load,
         makeClient: @escaping (AlpacaEnvironment, AlpacaCredentials) -> AlpacaREST = { AlpacaREST(environment: $0, credentials: $1) },
         loadCredentials: @escaping (AlpacaEnvironment) throws -> AlpacaCredentials = AlpacaKeychain.load,
         loadCustomer: @escaping () -> CustomerSession? = { CustomerSessionVault().load() },
         saveCredentials: @escaping (AlpacaCredentials, AlpacaEnvironment) throws -> Void = { try AlpacaKeychain.save($0, environment: $1) }) {
        self.routeStorage = routeStorage; self.routeRegistry = routeRegistry
        let defaults = routeStorage?.defaults ?? defaults
        if let storage = routeStorage {
            self.loadIntentPairing = { try storage.pairing() }
            self.loadCredentials = { try storage.credentials($0) }
            self.saveCredentials = { try storage.save($0, environment: $1) }
        } else {
            self.loadIntentPairing = loadIntentPairing
            self.loadCredentials = loadCredentials
            self.saveCredentials = saveCredentials
        }
        self.health = suppliedHealth ?? NativeHealth(storage: DefaultsHealthStorage(defaults: defaults))
        self.defaults = defaults; self.testDiscord = testDiscord; self.webhook = routeStorage?.route.legacy == false ? { nil } : webhook; self.deliverDiscord = deliverDiscord
        purpose = defaults.string(forKey: "guidedPurpose").flatMap(GuidedPurpose.init(rawValue:))
        self.loadCustomer = loadCustomer; self.makeClient = makeClient
        do {
            let folder: URL?
            if let storage = routeStorage, !storage.route.legacy { folder = try storage.folder() } else { folder = nil }
            let journal = try suppliedJournal ?? (folder.map { try AlpacaJournal(file: $0.appendingPathComponent("alpaca-journal.json")) } ?? AlpacaJournal.local())
            self.journal = journal; publisher = AlpacaDiscordDelivery(journal: journal, webhook: self.webhook, defaults: defaults)
            if suppliedJournal == nil && legacyRoute { mirrorSender = try MirrorSender.local() }
            intent = try intentController ?? (folder.map { try IntentController(file: $0.appendingPathComponent("intent-v1.json")) } ?? IntentController.local())
            if let bound = routeStorage?.route.environment { environment = bound }
        }
        catch { message = "Trading disabled: durable journal could not be read. Preserve it for recovery." }
    }
    private func perform(_ operation: () async throws -> Void) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do { try await operation() }
        catch { message = error.localizedDescription }
        await reloadJournal()
    }
    private func reloadJournal() async {
        guard let journal, let account else { submissions = []; deliveries = []; return }
        let snapshot = await journal.snapshot()
        submissions = snapshot.submissions.filter { $0.ticket.environment == environment && $0.ticket.accountID == account.id }
        deliveries = snapshot.deliveries.filter { $0.environment == environment && $0.accountID == account.id }
    }
    private func connectSavedBroker(key: String = "", secret: String = "") async throws {
        guard purpose != nil else { throw AlpacaError.invalid("Choose Alerts, Trade or Follow first.") }
        readiness.invalidate(); scopeGeneration = UUID()
        let generation = scopeGeneration; let selectedEnvironment = environment
        guard journal != nil else { throw AlpacaError.invalid("Journal unavailable. Trading is disabled.") }
        let supplied = !key.isEmpty || !secret.isEmpty
        let credentials: AlpacaCredentials
        if supplied { credentials = AlpacaCredentials(key: key.trimmingCharacters(in: .whitespacesAndNewlines), secret: secret.trimmingCharacters(in: .whitespacesAndNewlines)) }
        else { credentials = try loadCredentials(environment) }
        if let owner = credentials.owner {
            let customer = loadCustomer()
            guard OAuthOwnership.matches(owner: owner, serviceURL: credentials.serviceURL, customer: customer) else { throw AlpacaError.invalid("Sign in to the Crier customer that owns this OAuth credential, or use API keys.") }
        }
        let client = makeClient(environment, credentials)
        let current = try await client.account()
        guard foreground, generation == scopeGeneration, environment == selectedEnvironment, !Task.isCancelled else { throw AlpacaError.invalid("Connection interrupted. Reconnect explicitly.") }
        if executionJourney, let intent, !intent.state.accountID.isEmpty, intent.state.accountID != current.id {
            throw AlpacaError.invalid("Saved channel belongs to another account. Reconnect its original keys and resolve its journal before changing accounts.")
        }
        let savedPairing = try loadIntentPairing()
        if executionJourney, let pairing = savedPairing {
            try intent?.validateIdentity(account: current.id, environment: environment, pairing: pairing)
        }
        if let routeStorage { try routeRegistry?.bind(routeStorage.route.id, account: current.id, environment: selectedEnvironment) }
        // Verify candidate credentials and journal identity before replacing working keys.
        intent?.disconnect()
        if supplied { try saveCredentials(credentials, environment) }
        review = nil; positions = []; contracts = []
        account = current; api = client; readiness.verified = true
        let legacy = legacyRoute && executionJourney && savedPairing == nil ? try? MirrorPairing.load() : nil
        legacyHealth = legacy != nil
        healthBaseScope = NativeHealth.scope([environment.rawValue, current.id, purpose?.rawValue ?? "", savedPairing?.fingerprint ?? "", legacy?.fingerprint ?? "", credentials.owner ?? "", credentials.serviceURL ?? ""])
        bindHealth(); healthNote(healthTicket, .broker, .healthy, .verified)
        if foreground {
            try await refreshConnected(verifiedAccount: current)
            guard foreground, generation == scopeGeneration, !Task.isCancelled else { throw AlpacaError.invalid("Connection interrupted. Reconnect explicitly.") }
            try await activateIntent(api: client, account: current.id)
            guard foreground, generation == scopeGeneration, !Task.isCancelled else { throw AlpacaError.invalid("Connection interrupted. Reconnect explicitly.") }
            suspended = false
        } else { suspended = true }
    }
    private func activateIntent(api: AlpacaREST, account: String) async throws {
        guard executionJourney, foreground, let intent else { return }
        let generation = scopeGeneration
        do {
            guard let pairing = try loadIntentPairing() else { return }
            try intent.connect(api: api, account: account, pairing: pairing, startWorkers: false)
            try await intent.reconcileBeforeResume()
            guard foreground, generation == scopeGeneration, !Task.isCancelled else {
                throw AlpacaError.invalid("Intent resume interrupted. Reconcile again before restarting execution.")
            }
            try intent.connect(api: api, account: account, pairing: pairing)
            updateHealthActivity()
        } catch { intent.disconnect(); suspended = true; throw error }
    }
    func connect(key: String, secret: String) async {
        await perform {
            do { try await connectSavedBroker(key: key, secret: secret) }
            catch { readiness.invalidate(); throw error }
        }
    }
    // Hold the workspace lifecycle lock from provisioning through broker activation.
    // Persist the channel before any further network operation can fail.
    func quickConnect(host: Bool, service: String, invitation: String, newInvite: Bool = false) async throws -> String? {
        guard executionJourney else { throw AlpacaError.invalid("Choose Trade or Follow before connecting a channel.") }
        guard !busy else { throw AlpacaError.invalid("Wait for the current connection operation to finish.") }
        busy = true
        defer { busy = false }
        let selectedEnvironment = environment; let pairingGeneration = scopeGeneration
        var saved = try loadIntentPairing()
        let created = saved == nil
        if let existing = saved {
            guard existing.role == (host ? "host" : "follower"), existing.environment == selectedEnvironment else {
                throw AlpacaError.invalid("This device already has a different role or environment saved. Its journal remains pinned to that pairing.")
            }
            guard host || invitation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw AlpacaError.invalid("This receiver is already paired. Clear the invitation field and press Receive to reconnect.")
            }
        } else {
            let pair: IntentPairing
            if host { pair = try await QuickConnection.host(service: service, environment: selectedEnvironment) }
            else { pair = try await QuickConnection.receive(QuickConnection.invitation(invitation, service: service), environment: selectedEnvironment) }
            guard foreground, pairingGeneration == scopeGeneration, !Task.isCancelled, environment == selectedEnvironment else { throw AlpacaError.invalid("Pairing interrupted. Reconnect explicitly.") }
            try savePairing(pair); saved = pair
        }
        var link: String?
        var invitationFailure: String?
        if host, (created || newInvite), let pair = saved {
            do { link = try await QuickConnection.invite(pair) }
            catch { invitationFailure = error.localizedDescription }
        }
        do {
            guard foreground, pairingGeneration == scopeGeneration, !Task.isCancelled else { throw AlpacaError.invalid("Connection interrupted. Reconnect explicitly.") }
            guard let intent else { throw AlpacaError.invalid("Intent journal unavailable.") }
            if let api, let account {
                if let pairing = saved { try intent.validateIdentity(account: account.id, environment: environment, pairing: pairing) }
                if foreground { try await refreshConnected(); try await activateIntent(api: api, account: account.id) }
                else { suspended = true }
            } else { try await connectSavedBroker() }
            message = "Saved pairing connected. Keep this app open for delivery."
        } catch {
            message = "Pairing saved. Broker connection needs attention: " + error.localizedDescription
        }
        if let invitationFailure { message += " Invitation: " + invitationFailure }
        await reloadJournal()
        return link
    }
    func disconnect(removeCredentials: Bool = false) {
        guard !busy else { return }
        readiness.invalidate(); scopeGeneration = UUID()
        if removeCredentials { if let routeStorage { routeStorage.remove(environment) } else { AlpacaKeychain.remove(environment) } }
        api?.invalidate(); intent?.disconnect()
        suspended = false
        api = nil; account = nil; review = nil; positions = []; contracts = []; submissions = []; deliveries = []; updatedAt = nil
        message = "Disconnected. Saved orders and fills remain in the journal."
    }
    /// Stops workers synchronously even while an in-flight operation owns busy.
    func oauthStopWorkers() {
        readiness.invalidate(); scopeGeneration = UUID(); api?.invalidate(); intent?.disconnect()
        api = nil; account = nil; review = nil; positions = []; contracts = []; suspended = false
        discordConfigurationChanged()
    }
    func drainStoppedWork() async {
        await intent?.drainStoppedWork()
        while busy { await Task.yield() }
    }
    func oauthLogout() {
        oauthStopWorkers()
        guard legacyRoute else { return }
        for value in AlpacaEnvironment.allCases {
            if (try? loadCredentials(value))?.owner != nil { AlpacaKeychain.remove(value) }
        }
        if UserDefaults.standard.string(forKey: "discordOAuthOwner") != nil {
            StandaloneConfiguration.clear(); UserDefaults.standard.removeObject(forKey: "discordOAuthOwner"); UserDefaults.standard.removeObject(forKey: "discordOAuthServiceURL")
        }
        discordConfigurationChanged()
    }
    func installOAuthGrant(_ grant: ProviderGrant, owner: String, serviceURL: String, stillCurrent: () -> Bool) async throws {
        guard legacyRoute else { throw AlpacaError.invalid("Provider OAuth is available only on the original connection. Use this connection’s Alpaca API keys.") }
        guard !busy, foreground, account == nil, stillCurrent(), grant.environment == environment.rawValue,
              grant.purpose == (grant.provider == "discord" ? "alerts" : (purpose == .alerts ? "alerts" : "trade")),
              purpose != nil, UUID(uuidString: owner) != nil, (try? ProviderAPI(base: serviceURL)) != nil else { throw AlpacaError.invalid("Disconnect and restore the requested purpose and environment before installation.") }
        busy = true; let generation = scopeGeneration; let selected = environment
        defer { busy = false }
        if grant.provider == "alpaca" {
            guard journal != nil, intent != nil else { throw AlpacaError.invalid("Recovery journals unavailable; installation disabled.") }
            let credentials = AlpacaCredentials(bearer: grant.credential, owner: owner, serviceURL: serviceURL)
            let current = try await makeClient(selected, credentials).account()
            guard foreground, generation == scopeGeneration, selected == environment, account == nil, stillCurrent(),
                  current.id == grant.account_id else { throw AlpacaError.invalid("Broker identity or connection context changed. Authorize again.") }
            guard intent?.state.accountID.isEmpty != false || intent?.state.accountID == current.id else { throw AlpacaError.invalid("Saved intent journal belongs to another broker account.") }
            try intent?.validateIdentity(account: current.id, environment: selected, pairing: loadIntentPairing())
            try saveCredentials(credentials, selected)
            readiness.invalidate(); review = nil
        } else {
            guard grant.provider == "discord", !grant.guild_id.isEmpty, !grant.channel_id.isEmpty,
                  grant.guild_id.allSatisfy({ $0.isASCII && $0.isNumber }), grant.channel_id.allSatisfy({ $0.isASCII && $0.isNumber }) else { throw AlpacaError.invalid("Invalid Discord destination.") }
            try await storeDiscordWebhook(grant.credential, stillCurrent: { foreground && generation == scopeGeneration && stillCurrent() && account == nil })
            StandaloneConfiguration.setEnabled(false)
            UserDefaults.standard.set(owner, forKey: "discordOAuthOwner")
            UserDefaults.standard.set(serviceURL, forKey: "discordOAuthServiceURL")
        }
        message = "OAuth credential saved; reconnect explicitly. No trading or publishing permission was enabled."
    }
    func sceneActive(_ active: Bool) async {
        foreground = active
        if !active {
            if routeRegistry != nil {
                oauthStopWorkers()
                await drainStoppedWork()
                suspended = false
            } else {
                suspended = account != nil
                readiness.invalidate(); scopeGeneration = UUID()
                api?.invalidate(); intent?.disconnect()
            }
            review = nil
            lifecycle = "Background / suspended • automatic execution stopped; open Crier to reconcile"
            return
        }
        lifecycle = "Foreground • reconciling before new work"
        if suspended {
            guard !busy else {
                lifecycle = "Foreground • reconciliation pending; refresh or reconnect when the current operation finishes"
                return
            }
            await refresh()
        }
        lifecycle = suspended ? "Reconnect required • reconciliation failed" : "Foreground • keep Crier open for delivery"
    }
    func changeChannel() throws {
        guard routeRegistry == nil else { throw AlpacaError.invalid("Connections keep their original pairing and history. Add another connection to use another host.") }
        guard !busy, account == nil else { throw AlpacaError.invalid("Disconnect before changing channel.") }
        try intent?.archiveResolvedChannel()
        message = "Resolved channel archived. You can host or join a new channel."
    }
    /// Shared manual/OAuth destination guard. An await must never allow a stale write.
    private func storeDiscordWebhook(_ raw: String?, stillCurrent: () -> Bool) async throws {
        guard legacyRoute else { throw AlpacaError.invalid("Discord publishing is available only on the original connection.") }
        guard let journal else { throw AlpacaError.invalid("Delivery journal unavailable.") }
        let previous = StandaloneConfiguration.webhook()
        let outstanding = await journal.hasOutstandingDeliveries()
        guard stillCurrent() else { throw AlpacaError.invalid("Destination change interrupted.") }
        if let raw, previous?.absoluteString == raw { message = "Webhook already saved."; return }
        guard !outstanding else {
            throw AlpacaError.invalid("Deliver or close every pending, rejected and uncertain alert before changing destination. Old fills must not be sent to a different channel by accident.")
        }
        discordConfigurationChanged()
        if let raw {
            guard StandaloneConfiguration.saveWebhook(raw) else { throw AlpacaError.invalid("Invalid webhook or Keychain unavailable.") }
            UserDefaults.standard.removeObject(forKey: "discordOAuthOwner"); UserDefaults.standard.removeObject(forKey: "discordOAuthServiceURL"); message = "Webhook saved securely."
        } else { StandaloneConfiguration.clear(); UserDefaults.standard.removeObject(forKey: "discordOAuthOwner"); UserDefaults.standard.removeObject(forKey: "discordOAuthServiceURL"); message = "Webhook removed." }
    }
    func saveDiscordWebhook(_ raw: String?) async {
        await perform {
            let generation = scopeGeneration
            try await storeDiscordWebhook(raw, stillCurrent: { foreground && generation == scopeGeneration })
        }
    }
    func closeDiscord(_ id: String) async {
        await perform { try await journal?.closeDelivery(id) }
    }
    func retryDiscord(_ id: String, acknowledgeDuplicateRisk: Bool) async {
        await perform {
            guard canDeliver else { throw AlpacaError.invalid("Explicitly enable delivery for the current destination first.") }
            guard let journal else { return }
            let generation = scopeGeneration
            try await journal.retry(id, acknowledgeDuplicateRisk: acknowledgeDuplicateRisk)
            guard canDeliver, generation == scopeGeneration, !Task.isCancelled else { return }
            if let account { try await publishFills(environment: environment, accountID: account.id) }
        }
    }
    func checkRecoveryEvidence() async { await perform {
        recoverySnapshot = nil
        guard foreground, let api, let account else { throw AlpacaError.invalid("Reconnect the original account before checking broker evidence.") }
        let generation = scopeGeneration
        let selectedEnvironment = environment
        @MainActor func current() -> Bool {
            foreground && generation == scopeGeneration && self.api === api && environment == selectedEnvironment && !Task.isCancelled
        }
        let verified = try await api.account()
        guard current(), verified.id == account.id else { throw AlpacaError.invalid("Account or session changed; evidence discarded.") }
        let brokerPositions = try await api.positions()
        guard current() else { throw AlpacaError.invalid("Session changed; evidence discarded.") }
        var evidence: [RecoveryOrderEvidence] = []
        for submission in submissions.suffix(100) {
            guard submission.ticket.accountID == account.id, submission.ticket.environment == selectedEnvironment else { throw AlpacaError.invalid("Saved order scope differs from this account.") }
            let order: AlpacaOrder?
            do { order = try await api.order(clientID: submission.id) }
            catch AlpacaError.http(404) { order = nil }
            guard current() else { throw AlpacaError.invalid("Session changed; evidence discarded.") }
            if let order { try RecoveryOrderEvidence.validate(order, ticket: submission.ticket) }
            evidence.append(RecoveryOrderEvidence(ticket: submission.ticket, order: order))
        }
        recoverySnapshot = RecoveryBrokerSnapshot(accountID: account.id, environment: selectedEnvironment, checkedAt: Date(), orders: evidence, positions: brokerPositions)
        message = "Read-only broker evidence loaded. Missing orders remain unresolved; no orders or permissions changed."
    } }

    func refresh() async { await perform {
        if let previous = api, !previous.permitsMutations {
            guard foreground, suspended else { lifecycle = "Reconnect required - previous broker session stopped"; return }
            // Never revive a client retained by a stale intent task.
            api = try previous.freshClient(customer: loadCustomer())
        }
        do {
            if healthTicket == nil { bindHealth() }
            let generation = scopeGeneration
            try await refreshConnected()
            guard foreground, generation == scopeGeneration, !Task.isCancelled else { return }
            if suspended, let api, let account {
                readiness.verified = true
                try await activateIntent(api: api, account: account.id)
                guard foreground, generation == scopeGeneration, !Task.isCancelled else { return }
                suspended = false
                lifecycle = "Foreground • keep Crier open for delivery"
            }
        } catch { readiness.invalidate(); throw error }
    } }
    private func refreshConnected(verifiedAccount: AlpacaAccount? = nil) async throws {
        guard foreground, let api, let account, let journal else { return }
        let observed = healthTicket; var checking: HealthComponent = .broker
        do {
        let generation = scopeGeneration; let permit = effectPermit; let selectedEnvironment = environment
        let current: AlpacaAccount
        if let verifiedAccount { current = verifiedAccount } else { current = try await api.account() }
        guard generation == scopeGeneration, selectedEnvironment == environment, foreground, current.id == account.id else { throw AlpacaError.invalid("Authenticated account changed. Disconnect and reconnect.") }
        healthNote(observed, .broker, .healthy, .verified)
        let currentPositions = try await api.positions()
        guard foreground, generation == scopeGeneration, permit.isCurrent else { return }
        self.account = current; positions = currentPositions
        let snapshot = await journal.snapshot()
        for submission in snapshot.submissions where executionJourney && submission.ticket.environment == environment && submission.ticket.accountID == account.id {
            guard foreground, generation == scopeGeneration, permit.isCurrent else { return }
            do { let order = try await api.order(clientID: submission.id)
                try await journal.record(order, ticket: submission.ticket) }
            catch AlpacaError.http(404) { continue } // Unknown remains durable. 404 does not authorize resubmission.
        }
        checking = .fills
        let baseline = await journal.baseline(environment: environment, accountID: account.id)
        var cursor: String?; var seen = Set<String>()
        var newest: String?
        var collected: [AlpacaFill] = []
        // First connection establishes a durable baseline without replaying historical fills.
        // Later refreshes page back to that ID and commit the watermark only after every fill is durable.
        repeat {
            try Task.checkCancellation()
            guard foreground, generation == scopeGeneration, permit.isCurrent else { return }
            let fills = try await api.fills(pageToken: cursor)
            if newest == nil { newest = fills.first?.id }
            if baseline == nil { break }
            let fresh = fills.prefix(while: { $0.id != baseline })
            collected.append(contentsOf: fresh)
            if fresh.count < fills.count || fills.count < 100 { break }
            guard let last = fills.last, seen.insert(last.id).inserted else { throw AlpacaError.invalid("Repeated fill activity page.") }
            guard seen.count < 100 else { throw AlpacaError.invalid("Fill catch-up exceeded 10,000 events. Contact support before advancing the saved watermark.") }
            cursor = last.id
        } while true
        guard foreground, generation == scopeGeneration, selectedEnvironment == environment, !Task.isCancelled else { throw AlpacaError.invalid("Refresh interrupted. Reconnect explicitly.") }
        for fill in collected.reversed() { try await journal.ingest(fill, environment: environment, accountID: account.id) }
        if executionJourney, try loadIntentPairing() == nil { try await mirrorSender?.ingest(Array(collected.reversed()), environment: environment, account: account.id) }
        try await journal.setBaseline(newest ?? baseline ?? "__empty__", environment: environment, accountID: account.id)
        healthNote(observed, .fills, .healthy, .checked)
        guard foreground, generation == scopeGeneration, permit.isCurrent, !Task.isCancelled else { return }
        do { if executionJourney, try loadIntentPairing() == nil {
            let ledger = health
            mirrorMessage = try await mirrorSender?.deliver(api: api, account: account.id, permit: permit, observe: { state, reason in
                if let observed { await ledger.record(observed, .relaySend, state, reason) }
            }) ?? "Mirror journal unavailable."
        } }
        catch { mirrorMessage = error.localizedDescription; healthNote(observed, .relaySend, .degraded, .connectionFailed) }
        if canDeliver { checking = .discord; try await publishFills(environment: environment, accountID: account.id) }
        updatedAt = Date(); message = "Account, orders and broker fills refreshed."
        } catch {
            let auth: Bool
            if case AlpacaError.http(let status) = error { auth = [401,403].contains(status) } else { auth = false }
            healthNote(observed, checking, auth ? .blocked : .degraded, auth ? .authenticationFailed : .connectionFailed)
            throw error
        }
    }
    func discover(symbol: String, expiration: String) async {
        await perform {
            review = nil; contracts = []
            guard let api else { throw AlpacaError.invalid("Connect first.") }
            contracts = try await api.contracts(underlying: symbol.uppercased(), expiration: expiration)
            message = "\(contracts.count) standard contracts found. Quotes are not supplied; enter your limit price."
        }
    }
    func prepare(symbol: String, quantity: Int, limit: String, sell: Bool, contract: AlpacaContract?) async {
        await perform {
            review = nil
            guard executionJourney else { throw AlpacaError.invalid("Choose Trade before reviewing an order.") }
            guard let api, let account, let journal, let price = Decimal(string: limit, locale: Locale(identifier: "en_US_POSIX")), price > 0 else { throw AlpacaError.invalid("Connect and enter a positive limit price.") }
            guard await journal.baseline(environment: environment, accountID: account.id) != nil else { throw AlpacaError.invalid("Complete a successful refresh before trading to establish fill monitoring.") }
            let current = try await api.account()
            guard current.id == account.id, current.status == "ACTIVE", !current.account_blocked, !current.trading_blocked else { throw AlpacaError.invalid("Account cannot trade.") }
            let selected = contract?.symbol ?? symbol.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
            guard !selected.isEmpty, selected.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }) else { throw AlpacaError.invalid("Invalid symbol.") }
            if contract == nil { try await api.validateStock(selected) }
            else {
                guard let contract, contracts.contains(contract), contract.size == "100", (current.options_trading_level ?? 0) >= 2 else { throw AlpacaError.invalid("Select a discovered standard contract and enable level 2 options in Alpaca.") }
            }
            if sell {
                let currentPositions = try await api.positions()
                guard let held = currentPositions.first(where: { $0.symbol == selected }), let heldQty = Decimal(string: held.qty_available ?? ""), heldQty >= Decimal(quantity) else { throw AlpacaError.invalid("Sell orders require sufficient existing long holdings. Short opening is unsupported.") }
            }
            let ticket = AlpacaTicket(id: "crier-" + UUID().uuidString.lowercased(), environment: environment, accountID: account.id, symbol: selected, quantity: quantity, limitPrice: price, side: sell ? "sell" : "buy", positionIntent: sell ? "sell_to_close" : (contract == nil ? nil : "buy_to_open"), multiplier: contract == nil ? 1 : 100, reviewedAt: Date())
            try ticket.validate(); review = ticket
            message = "Review is a local estimate, not broker approval. Expires in 60 seconds."
        }
    }
    func confirm(_ ticket: AlpacaTicket) async {
        await perform {
            guard executionJourney, foreground, review == ticket, let api, let account, let journal, account.id == ticket.accountID, environment == ticket.environment else { throw AlpacaError.invalid("Review changed. Review again.") }
            let generation = scopeGeneration; let permit = effectPermit
            try ticket.validate()
            let current = try await api.account()
            guard current.id == ticket.accountID, current.status == "ACTIVE", !current.account_blocked, !current.trading_blocked else { throw AlpacaError.invalid("Account changed or cannot trade.") }
            if ticket.side == "sell" {
                let currentPositions = try await api.positions()
                guard let held = currentPositions.first(where: { $0.symbol == ticket.symbol }),
                      let available = Decimal(string: held.qty_available ?? ""), available >= Decimal(ticket.quantity) else { throw AlpacaError.invalid("Available holdings changed. Review again.") }
            }
            guard foreground, generation == scopeGeneration, self.api === api, permit.isCurrent, !Task.isCancelled else { throw AlpacaError.invalid("Trading session ended. Review again.") }
            try ticket.validate()
            if let intent, intent.hosting {
                guard ticket.side == "buy" else { throw AlpacaError.invalid("Use Exit on the tracked intent trade to sell mirrored holdings.") }
                _ = try intent.host(symbol: ticket.symbol, asset: ticket.multiplier == 100 ? "option" : "stock", quantity: ticket.quantity, price: NSDecimalNumber(decimal: ticket.limitPrice).stringValue)
                review = nil; message = "Intent saved; broker and relay dispatch started concurrently."
                return
            }
            if try loadIntentPairing() != nil { throw AlpacaError.invalid("Follower pairing cannot originate trades. Use a host pairing to submit mirrored orders.") }
            try await journal.begin(ticket)
            guard foreground, generation == scopeGeneration, self.api === api, permit.isCurrent, !Task.isCancelled else { throw AlpacaError.invalid("Trading session ended; journal retained for recovery.") }
            review = nil // Consume before any network await.
            do {
                let order = try await api.submit(ticket, permit: permit)
                try await journal.record(order, ticket: ticket)
                message = "Broker status: \(order.status). Acceptance is not a fill."
            } catch AlpacaError.http(let status) where [400, 401, 403, 422, 429].contains(status) {
                try await journal.reject(ticket, status: status)
                throw AlpacaError.http(status)
            } catch { throw AlpacaError.unknownSubmission }
        }
    }
    func cancel(_ submission: AlpacaJournal.Submission) async {
        await perform {
            guard executionJourney, foreground, let api, let account, submission.ticket.environment == environment, submission.ticket.accountID == account.id, let order = submission.order else { throw AlpacaError.invalid("Reconcile the broker order before cancellation.") }
            let generation = scopeGeneration; let permit = effectPermit
            let current = try await api.account()
            guard foreground, generation == scopeGeneration, self.api === api, permit.isCurrent, !Task.isCancelled else { throw AlpacaError.invalid("Trading session ended; cancellation not sent.") }
            guard current.id == account.id else { throw AlpacaError.invalid("Account changed.") }
            try await api.cancel(orderID: order.id, permit: permit)
            message = "Cancellation requested. Refresh to confirm; a racing fill can still occur."
        }
    }
}

struct AlpacaConnectionForm: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var key = ""
    @State private var secret = ""
    var body: some View {
        Section("Alpaca personal Trading API") {
            Picker("Environment", selection: $model.environment) {
                Text("Paper • simulated funds").tag(AlpacaEnvironment.paper)
                Text("Live • real money").tag(AlpacaEnvironment.live)
            }.disabled(model.account != nil || model.busy)
            Text(model.environment == .paper
                 ? "Paper uses simulated funds. Use API keys from your Alpaca paper account."
                 : "Live orders use real money. Use API keys from your Alpaca live account; every manual order requires final confirmation.")
                .font(.footnote)
            Text("Keep Crier open for monitoring, following trades and Discord delivery. These pause when iOS suspends the app.")
                .font(.footnote)
            SecureField("API key ID", text: $key).textInputAutocapitalization(.never).autocorrectionDisabled()
            SecureField("API secret", text: $secret).textInputAutocapitalization(.never).autocorrectionDisabled()
            Button("Save & connect (or use saved keys)") { Task { await model.connect(key: key, secret: secret); key = ""; secret = "" } }.disabled(model.busy)
            if model.account != nil {
                Button("Disconnect") { model.disconnect() }.disabled(model.busy)
            }
            Button("Remove this environment’s credentials", role: .destructive) { model.disconnect(removeCredentials: true) }.disabled(model.busy)
            Text(model.message).font(.footnote)
            Text("Webull Connect approval pending. Tradier is not integrated. No brokerage password is requested.").font(.footnote).foregroundStyle(.secondary)
        }
        if model.purpose == .trade || model.purpose == .follow {
            IntentConnectionForm()
            if model.legacyRoute && (try? model.savedPairing()) == nil { MirrorConnectionForm() }
        }
    }
}
struct AlpacaTradingView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var symbol = ""
    @State private var expiration = ""
    @State private var options = false
    @State private var contractID = ""
    @State private var quantity = 1
    @State private var limit = ""
    @State private var sell = false
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("ORDER TICKET").font(.caption.weight(.semibold)).tracking(1.5).foregroundStyle(.secondary)
                            Text(sell ? "Close position" : "Open position").font(.title2.weight(.bold))
                        }
                        Spacer()
                        Text(model.environment.rawValue.uppercased())
                            .font(.caption.weight(.bold)).padding(8)
                            .background(Color.blue.opacity(0.16), in: Capsule())
                    }
                    Text("Alpaca • Limit order • Day duration")
                        .font(.caption).foregroundStyle(.secondary)
                    if model.account == nil {
                        Label("Connect an account before reviewing an order", systemImage: "info.circle")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                Section("Instrument") {
                    Picker("Asset type", selection: $options) {
                        Text("Stocks").tag(false)
                        Text("Options").tag(true)
                    }.pickerStyle(.segmented)
                    TextField("Underlying / stock symbol", text: $symbol).textInputAutocapitalization(.characters).autocorrectionDisabled()
                    if options {
                        TextField("Expiration YYYY-MM-DD", text: $expiration).keyboardType(.numbersAndPunctuation)
                        Button("Discover option contracts") { Task { await model.discover(symbol: symbol, expiration: expiration) } }
                        Picker("Contract", selection: $contractID) {
                            Text("Choose contract").tag("")
                            ForEach(model.contracts) { Text($0.name).tag($0.id) }
                        }
                        if let selected = model.contracts.first(where: { $0.id == contractID }) {
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(selected.type.uppercased()).font(.caption.weight(.bold))
                                    Spacer()
                                    Text("Strike $" + selected.strike_price).monospacedDigit()
                                }
                                Text("Expires " + selected.expiration_date).font(.subheadline)
                                Text(selected.symbol).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                            }.padding(.vertical, 6)
                                .accessibilityElement(children: .combine)
                        } else {
                            Text("Discover and choose an exact contract before reviewing. No bid/ask quote is supplied by this selector.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }.disabled(model.busy || model.review != nil)
                Section("Order details") {
                    Picker("Order side", selection: $sell) {
                        Text(options ? "Buy to open" : "Buy shares").tag(false)
                        Text(options ? "Sell to close" : "Sell shares").tag(true)
                    }.pickerStyle(.segmented)
                    Stepper("\(options ? "Contracts" : "Shares"): \(quantity)", value: $quantity, in: 1...1000)
                        .monospacedDigit()
                    TextField(options ? "Limit premium per share" : "Limit price per share", text: $limit).keyboardType(.decimalPad)
                    if options {
                        Text("Standard contracts represent 100 shares. Premium × 100 × contracts determines limit notional, before fees.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Button("Review order") {
                        Task { await model.prepare(symbol: symbol, quantity: quantity, limit: limit, sell: sell, contract: options ? model.contracts.first(where: { $0.id == contractID }) : nil) }
                    }.buttonStyle(.borderedProminent).controlSize(.large)
                        .accessibilityIdentifier("crier.order.review")
                        .disabled(model.account == nil || (options && !model.contracts.contains(where: { $0.id == contractID })))
                }.disabled(model.busy || model.review != nil)
                if let ticket = model.review {
                    Section("Final confirmation • \(ticket.environment.rawValue.uppercased())") {
                        Text("\(ticket.side.uppercased()) \(ticket.quantity) \(ticket.symbol) @ $\(NSDecimalNumber(decimal: ticket.limitPrice).stringValue)")
                            .font(.headline).monospacedDigit().textSelection(.enabled)
                        Text("Limit notional: $\(NSDecimalNumber(decimal: ticket.limitPrice * Decimal(ticket.quantity * ticket.multiplier)).stringValue). Fees excluded; execution not guaranteed.")
                        Text("Account: \(ticket.accountID)").font(.caption).textSelection(.enabled)
                        Text("Client ID: \(ticket.id)").font(.caption).textSelection(.enabled)
                        Button(ticket.environment == .live ? "CONFIRM REAL-MONEY ORDER" : "Confirm paper order", role: ticket.environment == .live ? .destructive : nil) { Task { await model.confirm(ticket) } }.disabled(model.busy)
                        Button("Discard review") { model.review = nil }.disabled(model.busy)
                    }
                }
                Section { Text(model.message).font(.footnote) }
                if let intent = model.intent { IntentTradesView(controller: intent) }
                Section("Saved orders • pull to reconcile") {
                    ForEach(model.submissions.reversed()) { submission in
                        VStack(alignment: .leading) {
                            Text("\(submission.ticket.symbol) • \(submission.state)")
                            Text(submission.id).font(.caption).textSelection(.enabled)
                            if submission.order != nil {
                                Button("Request cancellation", role: .destructive) { Task { await model.cancel(submission) } }.disabled(model.busy)
                            }
                        }
                    }
                }
            }.scrollContentBackground(.hidden)
                .background(Color(red: 0.035, green: 0.045, blue: 0.06))
                .navigationTitle("Trade").navigationBarTitleDisplayMode(.inline)
                .refreshable { await model.refresh() }
        }
    }
}
