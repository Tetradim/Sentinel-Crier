import SwiftUI

struct WebullHostView: View {
    @EnvironmentObject private var connections: ProviderConnections
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var host = WebullHostController.shared
    // A gateway deployment is intentionally configured explicitly; never infer a broker host.
    @AppStorage("webullHostGatewayURL") private var service = ""
    @State private var relay = QuickConnection.defaultService
    @State private var environment = "sandbox"
    @State private var symbol = ""
    @State private var asset = "stock"
    @State private var quantity = "1"
    @State private var price = ""
    @State private var acknowledged = false
    @State private var confirmation: Confirmation?
    private struct Confirmation: Identifiable {
        var id = UUID(); var action: String; var trade: String?; var quantity: Int; var price: String
        var symbol: String; var asset: String; var environment: String
    }
    private var customerIdentity: String { (connections.customer?.user.id ?? "") + "|" + (connections.customer?.serviceURL ?? "") }
    var body: some View {
        Form {
            Section("Webull source → Alpaca PAPER") {
                Text("Submit orders here through your Webull account. Your Windows receiver follows your confirmed instruction immediately, before a Webull fill. It may trade even if Webull later rejects or never fills your order.")
                Text("Webull \(environment.uppercased()) · receiver PAPER").font(.headline)
                Picker("Source account environment", selection: $environment) {
                    Text("Webull sandbox").tag("sandbox")
                    Text("Webull production — real orders").tag("production")
                }
                Toggle(environment == "production" ? "I acknowledge REAL Webull orders → Alpaca PAPER instructions" : "I acknowledge Webull sandbox → Alpaca PAPER instructions", isOn: $acknowledged)
                Text("Keep Crier open to publish queued instructions and reconcile source orders. Unknown source outcomes are never automatically resubmitted.").font(.footnote)
            }
            Section("Crier customer and Webull authorization") {
                NavigationLink("Crier sign-in and session refresh", destination: ProviderConnectionsView())
                Text(connections.customer == nil ? "Sign in to Crier first. No brokerage secrets are stored on this device." : "Crier customer signed in. Webull consent is handled on its official site.")
                TextField("Trusted HTTPS Webull gateway URL", text: $service).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                Text("Only enter your deployed, trusted Crier Webull gateway. Checking sends your Crier customer token to that service and pins its URL to this journal.").font(.caption)
                Button("Check Webull service and connection") { Task { await host.connect(service: service, environment: environment, customer: connections.customer) } }
                Button("Authorize selected Webull environment") {
                    Task { if let url = await host.authorize(environment: environment, customer: connections.customer) { openURL(url) } }
                }.disabled(host.capabilities == nil)
                if let connection = host.connection {
                    Text("\(connection.environment): \(connection.state)")
                    if let account = connection.account_id { Text("Source account: \(account)").font(.caption).textSelection(.enabled) }
                }
            }
            Section("Private PAPER receiver route") {
                Text("This host route is separate from your existing Alpaca connections. Pair only the Windows Alpaca PAPER receiver.").font(.footnote)
                if host.paired {
                    Text("PAPER host route retained in Keychain")
                    Button("Create single-use receiver invitation") { Task { await host.invite() } }
                    if !host.invitation.isEmpty {
                        Text(host.invitation).textSelection(.enabled).privacySensitive()
                        ShareLink("Share private receiver invitation", item: host.invitation)
                    }
                } else {
                    TextField("HTTPS private connection service", text: $relay).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    Button("Create separate PAPER host route") { Task { await host.createPair(service: relay) } }
                }
                Text("Pending paper instructions: \(host.state.outgoing.count)")
                Button("Retry paper outbox") { Task { await host.publish() } }
            }
            Section("New source order · buy limit") {
                Picker("Asset", selection: $asset) { Text("Stock").tag("stock"); Text("Option OCC").tag("option") }
                TextField(asset == "option" ? "Exact OCC symbol" : "Mapped stock symbol", text: $symbol).textInputAutocapitalization(.characters).autocorrectionDisabled()
                TextField("Whole quantity", text: $quantity).keyboardType(.numberPad)
                TextField("Limit price", text: $price).keyboardType(.decimalPad)
                Button("Review buy and paper instruction") {
                    confirmation = Confirmation(action: "enter", quantity: Int(quantity) ?? 0, price: price, symbol: symbol, asset: asset, environment: environment)
                }.disabled(!acknowledged || host.connection?.state != "connected" || host.connection?.environment != environment || !host.paired)
            }
            Section("Tracked source orders and recovery") {
                Text("Revision uses the quantity and limit fields above. The revised quantity is the total entry target. Exit quantity is bounded by this journal’s filled ownership and the current source position.").font(.footnote)
                Button("Reconcile source receipts (GET only)") { Task { await host.reconcile(customer: connections.customer) } }
                ForEach(host.state.trades.values.sorted(by: { $0.id < $1.id })) { trade in
                    VStack(alignment: .leading, spacing: 8) {
                        Text("\(trade.symbol) · \(trade.environment.uppercased())").font(.headline)
                        Text("Instruction \(trade.desired.sequence): \(trade.desired.action) · target \(trade.desired.quantity) @ \(trade.desired.limit_price)")
                        Text("Source filled ownership: \(trade.owned)")
                        ForEach(trade.orders) { order in
                            Text("\(order.sell ? "SELL" : "BUY") \(order.quantity) · \(order.status) · filled \(order.filled)\(order.cancelRequested ? " · cancellation attempted" : "")").font(.caption)
                            Text("Limit $\(order.price) · fill average \(order.averageFillPrice.map { "$" + $0 } ?? "unavailable")").font(.caption)
                            if order.status == "unknown" { Text("Unknown outcome: reconcile this client ID; never submit it again.").font(.caption).foregroundStyle(.orange) }
                            Text(order.clientID).font(.caption2).textSelection(.enabled)
                        }
                        Button("Review cancel entry") { review("cancel", trade: trade) }
                        if ["enter", "replace"].contains(trade.desired.action) {
                            Button("Review revised entry target") { review("replace", trade: trade) }.disabled(!acknowledged)
                        }
                        // Exit performs a fresh source reconciliation. Do not make
                        // the customer wait for the periodic fill-display tick.
                        Button("Review bounded exit") { review("exit", trade: trade) }.disabled(!acknowledged)
                    }
                }
            }
            Section("Status") { Text(host.message).font(.footnote).textSelection(.enabled) }
        }
        .disabled(host.busy)
        .navigationTitle("Webull host")
        .onChange(of: environment) { _ in acknowledged = false; host.clearConnection() }
        .onChange(of: service) { _ in acknowledged = false; host.clearConnection() }
        .onChange(of: customerIdentity) { _ in acknowledged = false; host.clearConnection() }
        .task(id: scenePhase) {
            host.setActive(scenePhase == .active)
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await host.publish()
                await host.reconcile(customer: connections.customer, automatic: true)
                do { try await Task.sleep(nanoseconds: 5_000_000_000) } catch { return }
            }
        }
        .onDisappear { host.setActive(false) }
        .alert(item: $confirmation) { value in
            Alert(title: Text("Confirm \(value.action)\(value.environment == "production" ? " · REAL Webull" : " · sandbox")?"),
                  message: Text("\(value.symbol) · \(value.quantity) units @ \(value.price). Receiver: Alpaca PAPER. Instructions publish before source fills. Revision/exit first reconcile cancellations; source rejection may leave different receiver holdings. Existing fills require an explicit exit."),
                  primaryButton: .destructive(Text("Confirm \(value.action)")) { execute(value) }, secondaryButton: .cancel())
        }
    }
    private func review(_ action: String, trade: WebullHostTrade) {
        confirmation = Confirmation(action: action, trade: trade.id, quantity: action == "cancel" ? trade.desired.quantity : Int(quantity) ?? 0, price: action == "cancel" ? trade.desired.limit_price : price, symbol: trade.symbol, asset: trade.asset, environment: trade.environment)
    }
    private func execute(_ value: Confirmation) {
        Task {
            switch value.action {
            case "enter": await host.confirm(symbol: value.symbol, asset: value.asset, quantity: value.quantity, price: value.price, environment: value.environment, acknowledged: acknowledged, customer: connections.customer)
            case "cancel": if let id = value.trade { await host.cancel(id, customer: connections.customer) }
            case "replace": if let id = value.trade { await host.revise(id, quantity: value.quantity, price: value.price, acknowledged: acknowledged, customer: connections.customer) }
            case "exit": if let id = value.trade { await host.exit(id, quantity: value.quantity, price: value.price, acknowledged: acknowledged, customer: connections.customer) }
            default: break
            }
        }
    }
}
