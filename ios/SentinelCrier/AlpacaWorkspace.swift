import SwiftUI

@MainActor
final class AlpacaWorkspace: ObservableObject {
    @Published var environment: AlpacaEnvironment = .paper
    @Published private(set) var account: AlpacaAccount?
    @Published private(set) var positions: [AlpacaPosition] = []
    @Published private(set) var contracts: [AlpacaContract] = []
    @Published private(set) var submissions: [AlpacaJournal.Submission] = []
    @Published private(set) var deliveries: [AlpacaJournal.Delivery] = []
    @Published var review: AlpacaTicket?
    @Published private(set) var busy = false
    @Published private(set) var message = "Connect Alpaca paper to begin."
    @Published private(set) var updatedAt: Date?
    @Published private(set) var mirrorMessage = "Not paired."
    private var api: AlpacaREST?
    private var journal: AlpacaJournal?
    private var publisher: AlpacaDiscordDelivery?
    private var mirrorSender: MirrorSender?
    init() {
        do { let journal = try AlpacaJournal.local(); self.journal = journal; publisher = AlpacaDiscordDelivery(journal: journal); mirrorSender = try MirrorSender.local() }
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
    func connect(key: String, secret: String) async {
        await perform {
            guard journal != nil else { throw AlpacaError.invalid("Journal unavailable. Trading is disabled.") }
            review = nil; account = nil; api = nil; positions = []; contracts = []
            if !key.isEmpty || !secret.isEmpty {
                try AlpacaKeychain.save(AlpacaCredentials(key: key.trimmingCharacters(in: .whitespacesAndNewlines), secret: secret.trimmingCharacters(in: .whitespacesAndNewlines)), environment: environment)
            }
            let client = AlpacaREST(environment: environment, credentials: try AlpacaKeychain.load(environment))
            let current = try await client.account()
            account = current; api = client
            try await refreshConnected()
        }
    }
    func disconnect(removeCredentials: Bool = false) {
        guard !busy else { return }
        if removeCredentials { AlpacaKeychain.remove(environment) }
        api = nil; account = nil; review = nil; positions = []; contracts = []; submissions = []; deliveries = []; updatedAt = nil
        message = "Disconnected. Saved orders and fills remain in the journal."
    }
    func refresh() async { await perform { try await refreshConnected() } }
    private func refreshConnected() async throws {
        guard let api, let account, let journal else { return }
        let current = try await api.account()
        guard current.id == account.id else { throw AlpacaError.invalid("Authenticated account changed. Disconnect and reconnect.") }
        self.account = current; positions = try await api.positions()
        let snapshot = await journal.snapshot()
        for submission in snapshot.submissions where submission.ticket.environment == environment && submission.ticket.accountID == account.id {
            do { let order = try await api.order(clientID: submission.id)
                try await journal.record(order, ticket: submission.ticket) }
            catch AlpacaError.http(404) { continue } // Unknown remains durable. 404 does not authorize resubmission.
        }
        let baseline = await journal.baseline(environment: environment, accountID: account.id)
        var cursor: String?; var seen = Set<String>()
        var newest: String?
        var collected: [AlpacaFill] = []
        // First connection establishes a durable baseline without replaying historical fills.
        // Later refreshes page back to that ID and commit the watermark only after every fill is durable.
        repeat {
            try Task.checkCancellation()
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
        for fill in collected.reversed() { try await journal.ingest(fill, environment: environment, accountID: account.id) }
        try await mirrorSender?.ingest(Array(collected.reversed()), environment: environment, account: account.id)
        try await journal.setBaseline(newest ?? baseline ?? "__empty__", environment: environment, accountID: account.id)
        do { mirrorMessage = try await mirrorSender?.deliver(api: api, account: account.id) ?? "Mirror journal unavailable." }
        catch { mirrorMessage = error.localizedDescription }
        try await publisher?.deliver(environment: environment, accountID: account.id)
        updatedAt = Date(); message = "Account, orders and broker fills refreshed."
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
            guard review == ticket, let api, let account, let journal, account.id == ticket.accountID, environment == ticket.environment else { throw AlpacaError.invalid("Review changed. Review again.") }
            try ticket.validate()
            let current = try await api.account()
            guard current.id == ticket.accountID, current.status == "ACTIVE", !current.account_blocked, !current.trading_blocked else { throw AlpacaError.invalid("Account changed or cannot trade.") }
            if ticket.side == "sell" {
                let currentPositions = try await api.positions()
                guard let held = currentPositions.first(where: { $0.symbol == ticket.symbol }),
                      let available = Decimal(string: held.qty_available ?? ""), available >= Decimal(ticket.quantity) else { throw AlpacaError.invalid("Available holdings changed. Review again.") }
            }
            try ticket.validate()
            try await journal.begin(ticket)
            review = nil // Consume before any network await.
            do {
                let order = try await api.submit(ticket)
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
            guard let api, let account, submission.ticket.environment == environment, submission.ticket.accountID == account.id, let order = submission.order else { throw AlpacaError.invalid("Reconcile the broker order before cancellation.") }
            let current = try await api.account()
            guard current.id == account.id else { throw AlpacaError.invalid("Account changed.") }
            try await api.cancel(orderID: order.id)
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
        MirrorConnectionForm()
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
                Section("\(model.environment.rawValue.uppercased()) • day limit order") {
                    Toggle("Options", isOn: $options)
                    TextField("Underlying / stock symbol", text: $symbol).textInputAutocapitalization(.characters).autocorrectionDisabled()
                    if options {
                        TextField("Expiration YYYY-MM-DD", text: $expiration).keyboardType(.numbersAndPunctuation)
                        Button("Discover option contracts") { Task { await model.discover(symbol: symbol, expiration: expiration) } }
                        Picker("Contract", selection: $contractID) {
                            Text("Choose contract").tag("")
                            ForEach(model.contracts) { Text($0.name).tag($0.id) }
                        }
                    }
                    Toggle(options ? "Sell to close" : "Sell existing shares", isOn: $sell)
                    Stepper("Quantity: \(quantity)", value: $quantity, in: 1...1000)
                    TextField("Limit price per share", text: $limit).keyboardType(.decimalPad)
                    Button("Review order") {
                        Task { await model.prepare(symbol: symbol, quantity: quantity, limit: limit, sell: sell, contract: options ? model.contracts.first(where: { $0.id == contractID }) : nil) }
                    }.disabled(model.account == nil || (options && !model.contracts.contains(where: { $0.id == contractID })))
                }.disabled(model.busy || model.review != nil)
                if let ticket = model.review {
                    Section("Final confirmation • \(ticket.environment.rawValue.uppercased())") {
                        Text("\(ticket.side.uppercased()) \(ticket.quantity) \(ticket.symbol) @ $\(NSDecimalNumber(decimal: ticket.limitPrice).stringValue)")
                        Text("Limit notional: $\(NSDecimalNumber(decimal: ticket.limitPrice * Decimal(ticket.quantity * ticket.multiplier)).stringValue). Fees excluded; execution not guaranteed.")
                        Text("Account: \(ticket.accountID)").font(.caption).textSelection(.enabled)
                        Text("Client ID: \(ticket.id)").font(.caption).textSelection(.enabled)
                        Button(ticket.environment == .live ? "CONFIRM REAL-MONEY ORDER" : "Confirm paper order", role: ticket.environment == .live ? .destructive : nil) { Task { await model.confirm(ticket) } }.disabled(model.busy)
                        Button("Discard review") { model.review = nil }.disabled(model.busy)
                    }
                }
                Section { Text(model.message).font(.footnote) }
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
            }.navigationTitle("Trade").refreshable { await model.refresh() }
        }
    }
}
